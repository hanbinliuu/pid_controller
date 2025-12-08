"""模型选择器模块 - 多模型拟合与参数融合（重构版）"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from scipy.optimize import least_squares

from .config import Config, ModelType
from .models import SegmentResult, FusionResult, TuningInput, TuningWindow, HistoricalData
from .identifier import ModelIdentifier
from .fusion_strategy import PIDFusionStrategy, WindowResult as FusionWindowResult
from .data_preprocessor import DataPreprocessor
from .segment_processor import SegmentProcessor
from .simulator import ModelSimulator
from .pid_calculator import PIDCalculator
from .utils import (
    calculate_r2, calculate_rmse, calculate_rss, calculate_aic, calculate_bic,
    parse_timestamp, get_recommendation, determine_turning_type
)


class ModelSelector:
    """
    模型类型选择器
    
    核心流程：
    1. 剔除无效/扰动段 → 有效段筛选
    2. 对每个有效段尝试多种模型拟合 → 获取各段各模型的KTL
    3. 基于AIC/RSS/形状特征选择最优模型结构 → 确定模型类型
    4. 融合各段参数 → 唯一K, T, L（加权平均 / 全局优化）
    5. 验证一致性与仿真匹配度 → 最终输出
    """
    
    # 候选模型
    CANDIDATE_MODELS = [
        ModelType.FOPDT,
        ModelType.FO,
        ModelType.SO,
        ModelType.SOPDT,
        ModelType.FOPI,
    ]
    
    # 模型参数数量
    MODEL_PARAM_COUNT = {
        ModelType.FOPDT: 3,
        ModelType.FO: 2,
        ModelType.SO: 3,
        ModelType.SOPDT: 4,
        ModelType.FOPI: 2,
    }
    
    # 模型辨识方法
    IDENTIFY_METHODS = {
        ModelType.FOPDT: ModelIdentifier.identify_fopdt,
        ModelType.FO: ModelIdentifier.identify_first_order,
        ModelType.SO: ModelIdentifier.identify_second_order,
        ModelType.SOPDT: ModelIdentifier.identify_sopdt,
        ModelType.FOPI: ModelIdentifier.identify_integral_delay,
    }
    
    # 验证阈值常量
    MIN_R2_FOR_VOTE = 0.3
    MIN_R2_FOR_QUALITY = 0.4
    R2_THRESHOLDS = [0.5, 0.3, 0.15, 0.0]
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(verbose=verbose)
        self._segment_processor = SegmentProcessor(verbose=verbose)
        self._simulator = ModelSimulator()
        self._pid_calculator = PIDCalculator()
    
    @property
    def verbose(self) -> bool:
        return self._verbose
    
    def log(self, msg: str):
        if self._verbose:
            print(msg)
    
    # ============================================================
    # 主入口（新格式）
    # ============================================================
    
    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """模型整定主入口（新格式）"""
        history_data = input_data.get('history_data', [])
        params = input_data.get('params', {})
        qualified_windows = input_data.get('qualified_windows', [])
        
        if not history_data:
            return self._empty_result_new(params)
        
        if not qualified_windows:
            return self._empty_result_new(params)
        
        tuning_input = {
            'start_time': history_data[0].get('timestamp') if history_data else None,
            'end_time': history_data[-1].get('timestamp') if history_data else None,
            'tuning_window': [
                {'start_time': w.get('start_time'), 'end_time': w.get('end_time')}
                for w in qualified_windows
            ]
        }
        
        result = self.fit(tuning_input, history_data, lambda_factor=0.8)
        return self._convert_output_format(result, params)
    
    def _convert_output_format(self, result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """转换为新输出格式"""
        model_rating = result.get('model_rating', 0)
        recommendation = get_recommendation(model_rating)
        
        pid_params = result.get('pid_parameters', {})
        Kp = pid_params.get('Kp', 1.0)
        Ki = pid_params.get('Ki', 0.0)
        Kd = pid_params.get('Kd', 0.0)
        
        Ti = Kp / Ki if Ki > self._epsilon else 0.0
        Td = Kd / Kp if Kp > self._epsilon else 0.0
        Pb = 100.0 / Kp if Kp > self._epsilon else 100.0
        
        turning_type = params.get('turning_type') or determine_turning_type(Kp, Ti, Td)
        
        fitting_result = result.get('fitting_result', {})
        fitting_result['recommendation'] = recommendation
        
        return {
            'success': result.get('success', False),
            'model_type': result.get('model_type', 'FOPDT'),
            'turning_type': turning_type,
            'model_rating': model_rating,
            'start_time': result.get('start_time'),
            'end_time': result.get('end_time'),
            'model_parameters': result.get('model_parameters', {}),
            'pid_parameters': {
                'pb': round(float(Pb), 4),
                'ti': round(float(Ti), 4),
                'td': round(float(Td), 4),
                'kp': round(float(Kp), 4),
                'ki': round(float(Ki), 4),
                'kd': round(float(Kd), 4)
            },
            'fitting_result': fitting_result
        }
    
    def _empty_result_new(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """新格式空结果"""
        return {
            'success': False,
            'model_type': params.get('model_type') or 'FOPDT',
            'turning_type': params.get('turning_type') or 'PID',
            'model_rating': 0.0,
            'start_time': None,
            'end_time': None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {
                'pb': 100.0, 'ti': 0.0, 'td': 0.0,
                'kp': 1.0, 'ki': 0.0, 'kd': 0.0
            },
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0,
                'recommendation': '不可用'
            }
        }
    
    # ============================================================
    # 原有入口（保持兼容）
    # ============================================================
    
    def fit(self, tuning_input: Union[Dict, TuningInput],
            raw_data: List[Dict],
            lambda_factor: float = 0.8) -> Dict[str, Any]:
        """模型整定主入口"""
        input_data = self._parse_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result(input_data)
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        self.log(f"📥 输入: {len(input_data.tuning_window)} 个扰动窗口, {len(raw_data)} 条数据")
        
        # Step 1: 剔除无效扰动段
        segments = self._segment_processor.extract_segments(hist_data, input_data.tuning_window)
        valid_segments, segment_results = self._segment_processor.filter_invalid_segments(segments)
        
        if not valid_segments:
            self.log("⚠️ 无有效扰动段")
            return self._empty_result(input_data)
        
        self.log(f"📊 有效扰动段: {len(valid_segments)}/{len(segments)}")
        
        # Step 2: 对每个有效段尝试多种模型拟合
        segment_results = self._fit_all_segments(valid_segments, segment_results)
        
        # Step 3: 基于AIC/RSS/形状特征选择最优模型结构
        best_model_type = self._select_best_model_type(segment_results)
        self.log(f"🎯 选择模型类型: {best_model_type}")
        
        # Step 4: 融合各段参数
        fusion_result = self._fuse_parameters(segment_results, best_model_type, valid_segments)
        
        # Step 5: 验证一致性与仿真匹配度
        fusion_result = self._validate_and_refine(fusion_result, valid_segments, hist_data)
        
        # 构建最终输出
        return self._build_output(fusion_result, hist_data, time_range, lambda_factor)
    
    # ============================================================
    # Step 2: 多模型拟合
    # ============================================================
    
    def _fit_all_segments(self, segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> List[SegmentResult]:
        """对每个有效段拟合所有候选模型"""
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 2: 多模型拟合")
        self.log('='*60)
        
        valid_idx = 0
        for i, result in enumerate(segment_results):
            if not result.is_valid:
                continue
            
            seg = segments[valid_idx]
            valid_idx += 1
            
            valid_mask = seg.pv != 0
            y = seg.pv[valid_mask]
            u = seg.mv[valid_mask]
            t = np.arange(len(y), dtype=float)
            y0 = y[0]
            
            # 计算理论K值范围
            pv_range = np.max(y) - np.min(y)
            mv_range = np.max(u) - np.min(u)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 0.1 else 1.0
            k_min = k_expected * 0.1
            k_max = k_expected * 5.0
            
            self.log(f"\n📊 段{i+1}: {len(y)}点")
            
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated
            
            for model_type in self.CANDIDATE_MODELS:
                try:
                    if use_multi_start:
                        params_raw, _ = self._multi_start_fit(t, y, u, model_type)
                    else:
                        method = self.IDENTIFY_METHODS.get(model_type)
                        params_raw = method(t, y, u)
                    
                    params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                    y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                    
                    r2 = calculate_r2(y, y_pred)
                    rss = calculate_rss(y, y_pred)
                    n_params = self.MODEL_PARAM_COUNT[model_type]
                    aic = calculate_aic(rss, len(y), n_params)
                    bic = calculate_bic(rss, len(y), n_params)
                    
                    fitted_k = abs(params_dict['K'])
                    k_reasonable = k_min <= fitted_k <= k_max
                    
                    if not k_reasonable and r2 > 0:
                        r2_adjusted = r2 * 0.3
                        self.log(f"   {model_type}: K={params_dict['K']:.4f} 超出合理范围[{k_min:.4f}, {k_max:.4f}], R²降权")
                    else:
                        r2_adjusted = r2
                    
                    result.model_results[model_type] = {
                        'K': params_dict['K'],
                        'T1': params_dict['T1'],
                        'T2': params_dict['T2'],
                        'L': params_dict['L'],
                        'params_raw': params_raw,
                        'r2': r2,
                        'r2_adjusted': r2_adjusted,
                        'rss': rss,
                        'aic': aic,
                        'bic': bic,
                        'y_pred': y_pred,
                        'k_expected': k_expected,
                        'k_reasonable': k_reasonable
                    }
                    
                    k_flag = "✓" if k_reasonable else "✗"
                    self.log(f"   {model_type}: R²={r2:.4f}, AIC={aic:.1f}, "
                             f"K={params_dict['K']:.4f} {k_flag}, T1={params_dict['T1']:.2f}")
                    
                except Exception as e:
                    self.log(f"   {model_type}: 拟合失败 - {e}")
                    result.model_results[model_type] = {
                        'r2': 0.0, 'rss': float('inf'), 'aic': float('inf')
                    }
            
            self._select_segment_best_model(result, i)
        
        return segment_results
    
    def _select_segment_best_model(self, result: SegmentResult, idx: int):
        """选择该段的最佳模型"""
        if not result.model_results:
            return
        
        valid_models = {m: r for m, r in result.model_results.items() 
                       if r.get('r2_adjusted', r.get('r2', 0)) >= 0.4 and r.get('k_reasonable', True)}
        
        if valid_models:
            best_model = max(valid_models.keys(),
                            key=lambda m: valid_models[m].get('r2_adjusted', 0))
            result.best_model = best_model
            result.best_r2 = result.model_results[best_model].get('r2', 0)
            result.best_aic = result.model_results[best_model].get('aic', float('inf'))
        else:
            best_model = max(result.model_results.keys(),
                            key=lambda m: result.model_results[m].get('r2_adjusted', 
                                          result.model_results[m].get('r2', 0)))
            result.best_model = best_model
            result.best_r2 = result.model_results[best_model].get('r2', 0)
            result.best_aic = result.model_results[best_model].get('aic', float('inf'))
            
            if result.best_r2 < 0.4:
                self.log(f"   ⚠️ 段{idx+1}所有模型R²<0.4或K值异常")
    
    # ============================================================
    # Step 3: 模型选择
    # ============================================================
    
    def _select_best_model_type(self, segment_results: List[SegmentResult]) -> str:
        """选择最优模型结构"""
        self.log(f"\n{'='*60}")
        self.log("📊 Step 3: 模型结构选择")
        self.log('='*60)
        
        model_r2_scores = {m: [] for m in self.CANDIDATE_MODELS}
        model_votes = {m: 0 for m in self.CANDIDATE_MODELS}
        
        valid_results = [r for r in segment_results if r.is_valid and r.model_results]
        
        if not valid_results:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        high_quality_count = 0
        
        for result in valid_results:
            for model_type, fit_result in result.model_results.items():
                r2 = fit_result.get('r2', 0)
                if r2 >= self.MIN_R2_FOR_VOTE:
                    model_r2_scores[model_type].append(r2)
            
            if result.best_r2 >= self.MIN_R2_FOR_VOTE and result.best_model:
                model_votes[result.best_model] += 1
                high_quality_count += 1
        
        self.log(f"\n   高质量段(R²≥{self.MIN_R2_FOR_VOTE}): {high_quality_count}/{len(valid_results)}")
        
        self.log("\n   模型评估汇总:")
        self.log(f"   {'模型':<15} | {'平均R²':>10} | {'有效段':>6} | {'投票':>6} | {'综合分':>10}")
        self.log("   " + "-" * 60)
        
        model_composite_scores = {}
        
        for model_type in self.CANDIDATE_MODELS:
            r2_scores = model_r2_scores[model_type]
            votes = model_votes[model_type]
            
            if r2_scores:
                avg_r2 = np.mean(r2_scores)
                n_valid = len(r2_scores)
                
                vote_normalized = votes / max(high_quality_count, 1)
                composite = 0.7 * avg_r2 + 0.3 * vote_normalized
                model_composite_scores[model_type] = composite
                
                self.log(f"   {model_type:<15} | {avg_r2:>10.4f} | {n_valid:>6} | {votes:>6} | {composite:>10.4f}")
            else:
                all_r2 = [r.model_results.get(model_type, {}).get('r2', 0) 
                         for r in valid_results if r.model_results.get(model_type)]
                if all_r2:
                    avg_r2 = np.mean(all_r2) * 0.5
                    model_composite_scores[model_type] = avg_r2
                    self.log(f"   {model_type:<15} | {np.mean(all_r2):>10.4f}* | {0:>6} | {votes:>6} | {avg_r2:>10.4f}")
        
        if model_composite_scores:
            best_model = max(model_composite_scores.keys(), 
                           key=lambda m: model_composite_scores[m])
            best_score = model_composite_scores[best_model]
            
            if best_score < 0.4:
                self.log(f"\n   ⚠️ 所有模型拟合质量都较差")
            
            if best_model == ModelType.FOPI and best_score < 0.6:
                alternative_models = {m: s for m, s in model_composite_scores.items() 
                                     if m != ModelType.FOPI and s > 0.3}
                if alternative_models:
                    best_model = max(alternative_models.keys(), 
                                   key=lambda m: alternative_models[m])
                    self.log(f"   ⚠️ 积分器模型拟合质量不佳，回退到 {best_model}")
                else:
                    best_model = ModelType.FOPDT
                    self.log(f"   ⚠️ 积分器模型拟合质量不佳，回退到 FOPDT")
        else:
            best_model = ModelType.FOPDT
        
        self.log(f"\n   → 选择模型: {best_model}")
        return best_model
    
    # ============================================================
    # Step 4: 参数融合
    # ============================================================
    
    def _fuse_parameters(self, segment_results: List[SegmentResult],
                         model_type: str,
                         segments: List[HistoricalData] = None) -> FusionResult:
        """融合各段参数"""
        self.log(f"\n{'='*60}")
        self.log("📊 Step 4: 参数融合")
        self.log('='*60)
        
        fusion = FusionResult(model_type=model_type)
        
        window_results = []
        added_indices = set()
        valid_segment_idx = 0
        
        for threshold in self.R2_THRESHOLDS:
            valid_segment_idx = 0
            for result in segment_results:
                if not result.is_valid:
                    continue
                
                if result.segment_idx in added_indices:
                    valid_segment_idx += 1
                    continue
                
                fit_result = result.model_results.get(model_type)
                if fit_result is None:
                    valid_segment_idx += 1
                    continue
                
                r2 = fit_result.get('r2', 0)
                if r2 < threshold:
                    valid_segment_idx += 1
                    continue
                
                K, T1 = fit_result.get('K', 0), fit_result.get('T1', 0)
                if K == 0 and T1 == 0:
                    valid_segment_idx += 1
                    continue
                
                stability_score, oscillation_ratio, settling_quality, is_steady = 1.0, 0.0, 1.0, True
                if segments is not None and valid_segment_idx < len(segments):
                    seg = segments[valid_segment_idx]
                    stability_score, oscillation_ratio, settling_quality, is_steady = \
                        self._segment_processor.analyze_segment_stability(seg, fit_result)
                
                quality_adjusted_stability = stability_score
                if result.nonlinearity_score > 0.3:
                    quality_adjusted_stability *= (1 - result.nonlinearity_score * 0.5)
                if result.quality_score < 0.5:
                    quality_adjusted_stability *= (0.5 + result.quality_score)
                
                if result.oscillation_ratio > 0:
                    oscillation_ratio = result.oscillation_ratio
                
                window_results.append(FusionWindowResult(
                    window_idx=result.segment_idx,
                    K=K, T1=T1, 
                    T2=fit_result.get('T2', 0), 
                    L=fit_result.get('L', 0),
                    r2=r2,
                    data_points=result.data_points,
                    stability_score=quality_adjusted_stability,
                    oscillation_ratio=oscillation_ratio,
                    settling_quality=settling_quality,
                    is_steady=is_steady and not result.is_nonlinear
                ))
                added_indices.add(result.segment_idx)
                valid_segment_idx += 1
            
            if window_results:
                if threshold < self.R2_THRESHOLDS[0]:
                    self.log(f"   ⚠️ 使用阈值 R²≥{threshold} 收集到 {len(window_results)} 个有效段")
                break
        
        if not window_results:
            self.log("   ⚠️ 无有效参数，使用默认值")
            return fusion
        
        steady_count = sum(1 for w in window_results if w.is_steady)
        avg_stability = np.mean([w.stability_score for w in window_results])
        
        self.log(f"   收集到 {len(window_results)} 个有效段 (稳态段: {steady_count}, 平均稳态评分: {avg_stability:.2f}):")
        for w in window_results:
            steady_flag = "✓稳态" if w.is_steady else "⚠非稳态"
            self.log(f"      段{w.window_idx+1}: K={w.K:.4f}, T1={w.T1:.2f}, R²={w.r2:.3f}, "
                    f"稳态={w.stability_score:.2f} {steady_flag}")
        
        try:
            fusion_strategy = PIDFusionStrategy(verbose=self._verbose)
            fusion_result = fusion_strategy.fuse(window_results)
            
            fusion.K = fusion_result.K
            fusion.T1 = fusion_result.T1
            fusion.T2 = fusion_result.T2
            fusion.L = fusion_result.L
            fusion.fusion_method = fusion_result.strategy_used.value
            fusion.consistency_score = fusion_result.confidence
            fusion.n_segments_used = len(fusion_result.windows_used)
            
            if len(window_results) > 1:
                fusion.K_std = float(np.std([w.K for w in window_results]))
                fusion.T1_std = float(np.std([w.T1 for w in window_results]))
            else:
                fusion.K_std = 0.0
                fusion.T1_std = 0.0
            
            self.log(f"\n   融合策略: {fusion.fusion_method}")
            self.log(f"   决策原因: {fusion_result.reasoning}")
            self.log(f"   使用窗口: {[i+1 for i in fusion_result.windows_used]}")
            
        except Exception as e:
            self.log(f"   ⚠️ PIDFusionStrategy 失败: {e}，使用备用逻辑")
            best_window = max(window_results, key=lambda w: w.r2)
            fusion.K = best_window.K
            fusion.T1 = best_window.T1
            fusion.T2 = best_window.T2
            fusion.L = best_window.L
            fusion.fusion_method = "best_window_fallback"
            fusion.consistency_score = best_window.r2
            fusion.n_segments_used = 1
        
        self.log(f"\n   融合结果 ({fusion.fusion_method}, {fusion.n_segments_used}段):")
        self.log(f"   K  = {fusion.K:.4f} ± {fusion.K_std:.4f}")
        self.log(f"   T1 = {fusion.T1:.2f} ± {fusion.T1_std:.2f}")
        self.log(f"   T2 = {fusion.T2:.2f}")
        self.log(f"   L  = {fusion.L:.2f}")
        self.log(f"   一致性评分: {fusion.consistency_score:.2f}")
        
        return fusion
    
    # ============================================================
    # Step 5: 验证与优化
    # ============================================================
    
    def _validate_and_refine(self, fusion: FusionResult,
                              segments: List[HistoricalData],
                              hist_data: HistoricalData) -> FusionResult:
        """验证融合参数，必要时进行全局优化"""
        self.log(f"\n{'='*60}")
        self.log("📊 Step 5: 验证与优化")
        self.log('='*60)
        
        model_type = fusion.model_type
        params = self._simulator.fusion_to_params(fusion)
        
        if abs(fusion.K) < self._epsilon or fusion.T1 < self._epsilon:
            self.log("   ⚠️ 参数无效(K或T1为0)")
            fusion.global_r2 = 0.0
            fusion.global_rmse = 0.0
            return fusion
        
        valid_mask = hist_data.pv != 0
        y_full = hist_data.pv[valid_mask]
        u_full = hist_data.mv[valid_mask]
        sv_full = hist_data.sv[valid_mask] if hist_data.sv is not None else None
        
        y_pred_full = self._simulator.simulate_segmented(params, model_type, y_full, u_full, 
                                                          reset_on_sv_change=True, sv=sv_full)
        global_r2 = calculate_r2(y_full, y_pred_full)
        global_rmse = calculate_rmse(y_full, y_pred_full)
        
        self.log(f"   初始全量R²: {global_r2:.4f}, RMSE: {global_rmse:.4f}")
        
        # 分段R²用于诊断
        segment_r2s = []
        for seg in segments:
            seg_valid = seg.pv != 0
            y = seg.pv[seg_valid]
            u = seg.mv[seg_valid]
            if len(y) < 5:
                continue
            y0 = y[0]
            t = np.arange(len(y), dtype=float)
            y_pred = self._simulator.simulate(params, model_type, t, u, y0)
            r2 = calculate_r2(y, y_pred)
            segment_r2s.append(r2)
        
        if segment_r2s:
            self.log(f"   分段R²: {[f'{r:.3f}' for r in segment_r2s]}")
        
        OPTIMIZATION_THRESHOLD = 0.85
        min_segment_r2 = min(segment_r2s) if segment_r2s else 0
        segment_r2_std = np.std(segment_r2s) if len(segment_r2s) > 1 else 0
        
        need_optimization = (
            global_r2 < OPTIMIZATION_THRESHOLD or
            min_segment_r2 < 0.3 or
            segment_r2_std > 0.25
        )
        
        if need_optimization:
            self.log(f"   → R²<{OPTIMIZATION_THRESHOLD}，尝试全量数据优化...")
            
            optimized_params = self._global_optimize_full(y_full, u_full, sv_full, 
                                                           model_type, params)
            
            if optimized_params is not None:
                y_pred_opt = self._simulator.simulate_segmented(optimized_params, model_type, y_full, u_full,
                                                                 reset_on_sv_change=True, sv=sv_full)
                r2_opt = calculate_r2(y_full, y_pred_opt)
                rmse_opt = calculate_rmse(y_full, y_pred_opt)
                
                self.log(f"   优化后全量R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                if r2_opt > global_r2:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._simulator.params_to_fusion(optimized_params, model_type, fusion)
                    fusion.fusion_method += " + 全量优化"
                    self.log(f"   → 采用优化结果")
        
        fusion.global_r2 = global_r2
        fusion.global_rmse = global_rmse
        
        if global_r2 >= 0.9:
            quality = "优秀"
        elif global_r2 >= 0.7:
            quality = "良好"
        elif global_r2 >= 0.5:
            quality = "一般"
        else:
            quality = "较差"
        
        self.log(f"\n   最终评估: R²={global_r2:.4f} ({quality})")
        
        if global_r2 < 0.5:
            self.log(f"\n   ⚠️ 模型拟合质量较差，可能原因：")
            if min_segment_r2 < 0.1:
                self.log(f"      - 扰动段数据不符合阶跃响应特征")
            if segment_r2_std > 0.3:
                self.log(f"      - 各段响应特性差异大，可能存在非线性")
            self.log(f"   💡 建议：")
            self.log(f"      - 确认数据来自开环阶跃测试")
            self.log(f"      - 检查是否存在多个扰动叠加")
            self.log(f"      - 考虑使用更长的稳定响应数据")
        
        return fusion
    
    def _global_optimize_full(self, y_full: np.ndarray, u_full: np.ndarray,
                               sv_full: np.ndarray, model_type: str,
                               initial_params: tuple) -> Optional[tuple]:
        """全量数据优化"""
        try:
            reset_points = [0]
            if sv_full is not None and len(sv_full) > 0:
                sv_diff = np.abs(np.diff(sv_full))
                sv_threshold = max(0.1, np.std(sv_full) * 0.5) if np.std(sv_full) > 0 else 0.1
                change_points = np.where(sv_diff > sv_threshold)[0] + 1
                reset_points.extend(change_points.tolist())
            
            MAX_SEGMENT = 500
            for start in range(0, len(y_full), MAX_SEGMENT):
                if start not in reset_points and start > 0:
                    reset_points.append(start)
            
            reset_points = sorted(set(reset_points))
            reset_points.append(len(y_full))
            
            def objective(params):
                y_pred_all = np.zeros_like(y_full)
                
                for i in range(len(reset_points) - 1):
                    start_idx = reset_points[i]
                    end_idx = reset_points[i + 1]
                    
                    if end_idx <= start_idx:
                        continue
                    
                    y0 = y_full[start_idx]
                    t_seg = np.arange(end_idx - start_idx, dtype=float)
                    u_seg = u_full[start_idx:end_idx]
                    
                    y_seg = self._simulator.simulate(tuple(params), model_type, t_seg, u_seg, y0)
                    y_pred_all[start_idx:end_idx] = y_seg
                
                y_std = np.std(y_full)
                if y_std < self._epsilon:
                    y_std = 1.0
                return (y_full - y_pred_all) / y_std
            
            bounds = self._get_bounds(model_type)
            
            best_params = None
            best_cost = float('inf')
            
            pv_range = np.max(y_full) - np.min(y_full)
            mv_range = np.max(u_full) - np.min(u_full)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 5 else 0.5
            
            init_points = [
                initial_params,
                self._simulator.create_init_params(model_type, k_expected, 5.0),
                self._simulator.create_init_params(model_type, k_expected * 0.5, 10.0),
                self._simulator.create_init_params(model_type, -k_expected, 5.0),
            ]
            
            for init_p in init_points:
                try:
                    result = least_squares(objective, init_p, bounds=bounds,
                                           method='trf', max_nfev=1000)
                    
                    if result.success and result.cost < best_cost:
                        best_cost = result.cost
                        best_params = tuple(result.x)
                except:
                    continue
            
            return best_params
            
        except Exception as e:
            self.log(f"   全量优化失败: {e}")
        
        return None
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _multi_start_fit(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                         model_type: str, n_starts: int = 3) -> Tuple[tuple, float]:
        """多起点优化拟合"""
        y0 = y[0]
        method = self.IDENTIFY_METHODS.get(model_type)
        bounds = self._get_bounds(model_type)
        
        best_params = None
        best_r2 = -1
        
        try:
            params = method(t, y, u)
            y_pred = self._simulator.simulate(params, model_type, t, u, y0)
            r2 = calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except:
            pass
        
        try:
            y_f, u_f = self._preprocessor.preprocess(y, u)
            params = method(t, y_f, u_f)
            y_pred = self._simulator.simulate(params, model_type, t, u, y0)
            r2 = calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except:
            pass
        
        if best_params is not None and n_starts > 2:
            try:
                perturbed = tuple(p * (1 + 0.2 * np.random.randn()) for p in best_params)
                perturbed = tuple(
                    np.clip(p, bounds[0][i], bounds[1][i]) 
                    for i, p in enumerate(perturbed)
                )
                result = least_squares(
                    lambda params: self._simulator.simulate(params, model_type, t, u, y0) - y,
                    perturbed, bounds=bounds, method='trf', max_nfev=200
                )
                if result.success:
                    y_pred = self._simulator.simulate(tuple(result.x), model_type, t, u, y0)
                    r2 = calculate_r2(y, y_pred)
                    if r2 > best_r2:
                        best_r2 = r2
                        best_params = tuple(result.x)
            except:
                pass
        
        return best_params if best_params else method(t, y, u), max(best_r2, 0)
    
    def _parse_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        """解析整定输入"""
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    
    def _get_bounds(self, model_type: str) -> Tuple[List, List]:
        """获取参数边界"""
        bounds_config = Config.MODEL_BOUNDS.get(model_type, {})
        if 'initial' in bounds_config:
            return bounds_config['initial']
        
        if model_type == ModelType.FOPDT:
            return ([-20, 0.1, 0], [20, 1000, 100])
        elif model_type == ModelType.FO:
            return ([-20, 0.1], [20, 1000])
        elif model_type == ModelType.SO:
            return ([-20, 0.1, 0.1], [20, 1000, 1000])
        elif model_type == ModelType.SOPDT:
            return ([-20, 0.1, 0.1, 0], [20, 1000, 1000, 100])
        elif model_type == ModelType.FOPI:
            return ([-20, 0], [20, 100])
        return ([-20, 0.1, 0], [20, 1000, 100])
    
    def _build_output(self, fusion: FusionResult, hist_data: HistoricalData,
                      time_range: Dict, lambda_factor: float) -> Dict[str, Any]:
        """构建最终输出"""
        pid_params = self._pid_calculator.calculate_from_fusion(fusion, lambda_factor)
        
        params = self._simulator.fusion_to_params(fusion)
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = hist_data.timestamp[valid_mask]
        sv = hist_data.sv[valid_mask]
        
        pv_model = self._simulator.simulate_segmented(params, fusion.model_type, y, u, 
                                                       reset_on_sv_change=True, sv=sv)
        
        sim_r2 = calculate_r2(y, pv_model)
        
        pv_diff = np.diff(y)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        oscillation_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
        
        pv_range = np.ptp(y)
        model_range = np.ptp(pv_model)
        amplitude_ratio = model_range / (pv_range + self._epsilon) if pv_range > 0.1 else 1.0
        
        self.log(f"   pv_model检查: sim_R²={sim_r2:.3f}, 振荡={oscillation_ratio:.2f}, "
                f"PV范围={pv_range:.2f}, 模型范围={model_range:.2f}, 幅度比={amplitude_ratio:.2f}")
        
        sim_quality_poor = (
            sim_r2 < 0.5 or
            fusion.global_r2 < 0.3 or
            oscillation_ratio > 0.4 or
            amplitude_ratio < 0.5 or amplitude_ratio > 2.0
        )
        
        fitting_failed = (
            fusion.n_segments_used == 0 or
            sim_r2 < 0.1 or
            amplitude_ratio < 0.3 or amplitude_ratio > 3.0
        )
        
        if fitting_failed:
            self.log(f"   ❌ 拟合完全失败，保留原始pv_model用于诊断分析")
        elif sim_quality_poor:
            reason = []
            if sim_r2 < 0.5:
                reason.append(f"R²={sim_r2:.3f}")
            if oscillation_ratio > 0.4:
                reason.append(f"振荡={oscillation_ratio:.2f}")
            if amplitude_ratio < 0.5 or amplitude_ratio > 2.0:
                reason.append(f"幅度比={amplitude_ratio:.2f}")
            self.log(f"   ⚠️ 模型仿真质量较差({', '.join(reason)})")
        
        total_data_points = int(np.sum(valid_mask))
        model_rating, score_details = self._pid_calculator.calculate_model_rating(
            fusion, total_data_points, verbose=self._verbose
        )
        
        if self._verbose:
            self.log(f"\n   📊 评分详情:")
            self.log(f"      拟合质量 (R²={fusion.global_r2:.3f}): {score_details.get('r2_score', 0):.1f}/10 × 40%")
            self.log(f"      参数一致性: {score_details.get('consistency_score', 0):.1f}/10 × 25%")
            self.log(f"      参数合理性: {score_details.get('validity_score', 0):.1f}/10 × 20%")
            self.log(f"      数据覆盖度 ({fusion.n_segments_used}段/{total_data_points}点): {score_details.get('coverage_score', 0):.1f}/10 × 15%")
            self.log(f"      → 综合评分: {model_rating}/10")
        
        return {
            'success': not fitting_failed,
            'model_type': fusion.model_type,
            'model_rating': model_rating,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {
                'K': round(fusion.K, 4),
                'T1': round(fusion.T1, 4),
                'T2': round(fusion.T2, 4),
                'L': round(fusion.L, 4)
            },
            'pid_parameters': pid_params,
            'fitting_result': {
                'timestamp': ts.tolist(),
                'sv': sv.tolist(),
                'pv': y.tolist(),
                'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': round(fusion.global_r2, 4),
                'rmse': round(fusion.global_rmse, 4)
            },
            'fusion_info': {
                'method': fusion.fusion_method,
                'n_segments': fusion.n_segments_used,
                'consistency_score': round(fusion.consistency_score, 4),
                'K_std': round(fusion.K_std, 4),
                'T1_std': round(fusion.T1_std, 4)
            },
            'rating_details': score_details
        }
    
    def _empty_result(self, input_data: Optional[TuningInput]) -> Dict[str, Any]:
        """空结果"""
        return {
            'success': False,
            'model_type': ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': getattr(input_data, 'start_time', None) if input_data else None,
            'end_time': getattr(input_data, 'end_time', None) if input_data else None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            },
            'fusion_info': {
                'method': 'none',
                'n_segments': 0,
                'consistency_score': 0.0
            },
            'rating_details': {
                'r2_score': 0.0,
                'consistency_score': 0.0,
                'validity_score': 0.0,
                'coverage_score': 0.0,
                'n_segments': 0,
                'total_data_points': 0
            }
        }
