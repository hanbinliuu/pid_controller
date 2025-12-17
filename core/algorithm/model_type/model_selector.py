import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from scipy.optimize import least_squares

from api.commond.time_util import parse_time_to_milliseconds
from .config import Config, ModelType
from .data_models import SegmentResult, FusionResult, TuningInput, HistoricalData
from .utils import (
    calculate_r2, calculate_rmse, calculate_rss, calculate_aic, calculate_bic,
    get_recommendation, determine_turning_type
)

# 子模块导入
from .preprocessing import DataPreprocessor, SegmentProcessor
from .fitting import (
    ModelIdentifier, SegmentFitter, PIDFusionStrategy, 
    WindowResult as FusionWindowResult, UnifiedModelSelector, SegmentModelFit
)
from .tuning import PIDCalculator, DataQualityInfo, OscillationTuner
from .simulation import ModelSimulator

# 其他模块
from .output_builder import OutputBuilder


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
    
    # 验证阈值常量 (从配置读取)
    MIN_R2_FOR_VOTE = Config.MODEL_SELECTOR['min_r2_for_vote']
    MIN_R2_FOR_QUALITY = Config.MODEL_SELECTOR['min_r2_for_quality']
    R2_THRESHOLDS = Config.MODEL_SELECTOR['r2_thresholds']
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        
        # 初始化子模块
        self._preprocessor = DataPreprocessor(verbose=verbose)
        self._segment_processor = SegmentProcessor(verbose=verbose)
        self._simulator = ModelSimulator()
        self._pid_calculator = PIDCalculator()
        self._unified_selector = UnifiedModelSelector(verbose=verbose)
        
        # 拆分后的子模块
        self._segment_fitter = SegmentFitter(
            self._simulator, self._preprocessor, self._pid_calculator, verbose
        )
        self._output_builder = OutputBuilder(
            self._simulator, self._pid_calculator, verbose
        )
        self._oscillation_tuner = OscillationTuner(
            self._pid_calculator, self._simulator, verbose
        )
    
    @property
    def verbose(self) -> bool:
        return self._verbose
    
    def log(self, msg: str) -> None:
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
        current_pid = input_data.get('current_pid', None)  # 当前 PID 参数
        
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
        
        result = self.fit(tuning_input, history_data, lambda_factor=0.8, 
                          current_pid=current_pid)
        return self._convert_output_format(result, params)
    
    def _convert_output_format(self, result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """转换为新输出格式"""
        model_rating = result.get('model_rating', 0)
        recommendation = get_recommendation(model_rating)
        
        pid_params = result.get('pid_parameters', {})
        Kp = pid_params.get('Kp', 1.0)
        Ki = pid_params.get('Ki', 0.0)
        Kd = pid_params.get('Kd', 0.0)
        
        # 处理反向作用系统（Kp/Ki/Kd可能为负）
        Ti = Kp / Ki if abs(Ki) > self._epsilon else 0.0
        Td = Kd / Kp if abs(Kp) > self._epsilon else 0.0
        Pb = 100.0 / abs(Kp) if abs(Kp) > self._epsilon else 100.0
        
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
            'fitting_result': fitting_result,
            'fusion_info': result.get('fusion_info', {}),
            'closed_loop_verification': result.get('closed_loop_verification', {}),
            'rating_details': result.get('rating_details', {})
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
            lambda_factor: float = None,
            current_pid: Dict = None,
            enable_downsample: bool = None,
            downsample_target: int = None) -> Dict[str, Any]:
        """模型整定主入口
        
        Args:
            tuning_input: 整定输入
            raw_data: 原始数据
            lambda_factor: Lambda整定系数
            current_pid: 当前PID参数 {'Kp': ..., 'Ki': ..., 'Kd': ...}，用于振荡分析
            enable_downsample: 是否启用智能降采样
            downsample_target: 降采样目标点数
        """
        # 使用配置默认值
        tuning_defaults = Config.TUNING_DEFAULTS
        if lambda_factor is None:
            lambda_factor = tuning_defaults['lambda_factor']
        if enable_downsample is None:
            enable_downsample = tuning_defaults['enable_downsample']
        if downsample_target is None:
            downsample_target = tuning_defaults['downsample_target']
        
        input_data = self._parse_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result(input_data)
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        self.log(f"📥 输入: {len(input_data.tuning_window)} 个扰动窗口, {len(raw_data)} 条数据")
        
        # Step 1: 剔除无效扰动段
        segments = self._segment_processor.extract_segments(hist_data, input_data.tuning_window)
        valid_segments, segment_results = self._segment_processor.filter_invalid_segments(segments)
        
        # Step 1.5: 智能降采样（加速整定）
        if enable_downsample and valid_segments:
            valid_segments = self._apply_smart_downsample(valid_segments, downsample_target)
        
        if not valid_segments:
            self.log("⚠️ 无有效扰动段")
            return self._empty_result(input_data)
        
        self.log(f"📊 有效扰动段: {len(valid_segments)}/{len(segments)}")
        
        # Step 2: 对每个有效段尝试多种模型拟合
        segment_results = self._fit_all_segments(valid_segments, segment_results)
        
        # Step 2.5: 检查是否所有段都是高振荡且拟合失败（使用独立模块）
        oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
            valid_segments, segment_results, current_pid
        )
        if oscillation_result is not None:
            # 使用振荡分析结果，跳过后续的模型融合
            return self._oscillation_tuner.build_oscillation_output(
                oscillation_result, hist_data, time_range, input_data.tuning_window
            )
        
        # Step 3: 基于AIC/RSS/形状特征选择最优模型结构（支持全量数据验证）
        best_model_type = self._select_best_model_type(segment_results, hist_data)
        self.log(f"🎯 选择模型类型: {best_model_type}")
        
        # Step 4: 融合各段参数
        fusion_result = self._fuse_parameters(segment_results, best_model_type, valid_segments)
        
        # Step 5: 验证一致性与仿真匹配度
        fusion_result = self._validate_and_refine(fusion_result, valid_segments, hist_data)
        
        # 构建数据质量信息，用于自适应保守PID整定
        quality_info = self._build_quality_info(valid_segments, segment_results, fusion_result)
        
        # 构建最终输出（传入扰动段信息和质量信息）
        return self._build_output(fusion_result, hist_data, time_range, lambda_factor, 
                                  input_data.tuning_window, quality_info)
    
    def _build_quality_info(self, valid_segments: List[HistoricalData],
                            segment_results: List[SegmentResult],
                            fusion_result: FusionResult) -> DataQualityInfo:
        """
        构建数据质量信息，用于自适应保守PID整定
        
        评估因素:
        1. 数据质量评分 - 基于噪声、相关性等
        2. 振荡比 - 数据振荡程度
        3. 拟合R² - 模型拟合质量
        4. 参数一致性 - 多段参数一致程度
        """
        # 计算平均振荡比和质量评分（一次遍历，避免重复调用 analyze_quality）
        oscillation_ratios = []
        quality_scores = []
        is_noisy = False
        
        for seg in valid_segments:
            y = seg.pv
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            osc_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            oscillation_ratios.append(osc_ratio)
            
            # 使用预处理器分析质量（只调用一次）
            quality = self._preprocessor.analyze_quality(y, seg.mv)
            quality_scores.append(quality.quality_score if hasattr(quality, 'quality_score') else 0.5)
            
            # 检查是否有高噪声段
            if hasattr(quality, 'is_noisy') and quality.is_noisy:
                is_noisy = True
        
        avg_oscillation = np.mean(oscillation_ratios) if oscillation_ratios else 0.0
        avg_quality = np.mean(quality_scores) if quality_scores else 0.5
        
        quality_info = DataQualityInfo(
            quality_score=avg_quality,
            oscillation_ratio=avg_oscillation,
            r_squared=fusion_result.global_r2,
            is_noisy=is_noisy,
            consistency_score=fusion_result.consistency_score
        )
        
        # 日志输出保守等级信息
        conservative_level, pb_min = self._pid_calculator._calculate_conservative_level(quality_info)
        self.log(f"   📊 自适应保守调整: 质量={avg_quality:.2f}, 振荡={avg_oscillation:.2f}, "
                f"R²={fusion_result.global_r2:.2f}, 一致性={fusion_result.consistency_score:.2f}")
        self.log(f"   → 保守等级={conservative_level:.1f}, pb最小值={pb_min:.0f}")
        
        return quality_info
    
    # ============================================================
    # Step 1.5: 智能降采样
    # ============================================================
    
    def _apply_smart_downsample(self, segments: List[HistoricalData], 
                                 target_points: int = 1000) -> List[HistoricalData]:
        """
        对每个扰动段应用智能降采样
        
        Args:
            segments: 有效扰动段列表
            target_points: 每段目标点数
        
        Returns:
            降采样后的扰动段列表
        """
        downsampled = []
        total_original = 0
        total_downsampled = 0
        
        for i, seg in enumerate(segments):
            n = len(seg.pv)
            total_original += n
            
            # 自动估计目标点数（根据数据特征自适应）
            auto_target = self._preprocessor.estimate_optimal_target_points(
                n, pv=seg.pv, sv=seg.sv
            )
            actual_target = min(target_points, auto_target)
            
            if n <= actual_target:
                # 数据量小，不需要降采样
                downsampled.append(seg)
                total_downsampled += n
            else:
                # 执行智能降采样
                result = self._preprocessor.smart_downsample(
                    seg.pv, seg.mv, seg.sv, seg.timestamp,
                    target_points=actual_target,
                    min_points=100,
                    preserve_features=True
                )
                
                pv_down, mv_down, sv_down, ts_down = result
                
                # 创建新的 HistoricalData
                new_seg = HistoricalData(
                    timestamp=ts_down,
                    pv=pv_down,
                    sv=sv_down,
                    mv=mv_down
                )
                downsampled.append(new_seg)
                total_downsampled += len(pv_down)
                
                self.log(f"   📉 段{i+1}: {n} → {len(pv_down)} 点 (降采样率 {len(pv_down)/n*100:.1f}%)")
        
        if total_original > total_downsampled:
            reduction = (1 - total_downsampled / total_original) * 100
            self.log(f"📉 智能降采样: {total_original} → {total_downsampled} 点 (减少 {reduction:.1f}%)")
        
        return downsampled
    
    # ============================================================
    # Step 2: 多模型拟合
    # ============================================================
    
    def _fit_all_segments(self, segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> List[SegmentResult]:
        """
        对每个有效段拟合所有候选模型
        
        增强：
        1. 检测高振荡开环数据并特殊处理
        2. 使用包络线法估计增益
        3. 添加幅度验证和校正
        """
        from .fitting import ModelIdentifier
        
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
            
            # 检测高振荡数据
            oscillation_info = ModelIdentifier.detect_high_oscillation(y, u)
            is_oscillating = oscillation_info['is_oscillating']
            
            if is_oscillating:
                self.log(f"   ⚠️ 检测到高振荡开环数据 (振荡比={oscillation_info['oscillation_ratio']:.2f})")
                # 对高振荡数据使用预处理后的数据进行辨识
                filter_size = oscillation_info['recommended_filter_size']
                y_fit, u_fit = ModelIdentifier.preprocess_oscillating_data(y, u, filter_size)
                
                # 振荡数据的K值估计：使用多种方法取最大值
                # 方法1：包络线法
                k_envelope = abs(ModelIdentifier.estimate_gain_from_oscillating_data(y, u))
                # 方法2：简单比值法（对稳态振荡更准确）
                k_simple = pv_range / (mv_range + self._epsilon) if mv_range > 0.1 else 0.5
                # 取较大值（避免稳态振荡时包络线法低估）
                k_expected = max(k_envelope, k_simple)
                # 对振荡数据放宽K值范围（×0.1 ~ ×10）
                k_min = k_expected * 0.1
                k_max = k_expected * 10.0
            else:
                y_fit, u_fit = y, u
            
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated or is_oscillating
            
            for model_type in self.CANDIDATE_MODELS:
                try:
                    # 使用预处理后的数据进行辨识
                    if use_multi_start:
                        params_raw, _ = self._multi_start_fit(t, y_fit, u_fit, model_type)
                    else:
                        method = self.IDENTIFY_METHODS.get(model_type)
                        params_raw = method(t, y_fit, u_fit)
                    
                    params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                    
                    # 使用原始数据验证拟合效果
                    y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                    
                    # 检查并校正幅度
                    pred_range = np.ptp(y_pred)
                    if is_oscillating and pred_range > self._epsilon and pv_range > self._epsilon:
                        amplitude_ratio = pred_range / pv_range
                        if amplitude_ratio > 1.5 or amplitude_ratio < 0.5:
                            # 校正K值
                            K_correction = pv_range / pred_range
                            params_raw = list(params_raw)
                            params_raw[0] = params_raw[0] * K_correction
                            params_raw = tuple(params_raw)
                            params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                            # 重新仿真
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
                    
                    # 对高振荡数据，额外奖励幅度匹配好的结果
                    if is_oscillating:
                        amplitude_match = 1 - min(abs(np.ptp(y_pred) - pv_range) / (pv_range + self._epsilon), 0.5)
                        r2_adjusted = r2_adjusted * (0.7 + 0.3 * amplitude_match)
                    
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
                        'k_reasonable': k_reasonable,
                        'is_oscillating': is_oscillating
                    }
                    
                    k_flag = "✓" if k_reasonable else "✗"
                    osc_flag = " [振荡]" if is_oscillating else ""
                    self.log(f"   {model_type}: R²={r2:.4f}, AIC={aic:.1f}, "
                             f"K={params_dict['K']:.4f} {k_flag}, T1={params_dict['T1']:.2f}{osc_flag}")
                    
                except Exception as e:
                    self.log(f"   {model_type}: 拟合失败 - {e}")
                    result.model_results[model_type] = {
                        'r2': 0.0, 'rss': float('inf'), 'aic': float('inf')
                    }
            
            self._select_segment_best_model(result, i)
        
        return segment_results
    
    def _select_segment_best_model(self, result: SegmentResult, idx: int) -> None:
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
    # Step 2.5: 振荡分析与临界法整定（已移至 oscillation_tuner.py）
    # ============================================================
    
    # 以下方法已移至 OscillationTuner 类，保留为代理调用以保持向后兼容
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, 
                                      K_approx: float = 1.0,
                                      reason: str = 'generic') -> Dict[str, Any]:
        """获取保守PID参数（代理到 OscillationTuner）"""
        return self._oscillation_tuner.get_conservative_pid_params(Pu, Ku, K_approx, reason)
    
    def _try_oscillation_tuning(self, segments: List[HistoricalData], 
                                segment_results: List[SegmentResult],
                                current_pid: Dict = None) -> Optional[Dict]:
        """尝试振荡分析整定（代理到 OscillationTuner）"""
        return self._oscillation_tuner.try_oscillation_tuning(segments, segment_results, current_pid)
    
    def _build_oscillation_output(self, osc_result: Dict, hist_data: HistoricalData,
                                  time_range: Dict, tuning_windows: List) -> Dict[str, Any]:
        """构建振荡整定输出（代理到 OscillationTuner）"""
        return self._oscillation_tuner.build_oscillation_output(osc_result, hist_data, time_range, tuning_windows)
    
    # ============================================================
    # Step 3: 模型选择（使用统一模型选择器）
    # ============================================================
    
    def _select_best_model_type(self, segment_results: List[SegmentResult],
                                 hist_data: 'HistoricalData' = None) -> str:
        """
        选择最优模型结构（统一模型选择）
        
        改进：
        1. 使用质量加权投票而非简单计数
        2. 应用复杂度惩罚（奥卡姆剃刀）
        3. 处理各段模型不一致的情况
        4. 扰动段无法判断时，使用全量数据验证
        """
        # 转换为SegmentModelFit格式
        segment_fits = self._convert_to_segment_fits(segment_results)
        
        if not segment_fits:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        # 使用统一模型选择器
        best_model, reasoning, need_fulldata = self._unified_selector.select_unified_model_type(segment_fits)
        
        # 诊断不一致性
        diagnosis = self._unified_selector.handle_inconsistent_segments(segment_fits)
        if diagnosis['has_inconsistency']:
            self.log("\n   ⚠️ 检测到段间不一致:")
            for issue in diagnosis['issues']:
                self.log(f"      - {issue}")
            if diagnosis['recommendations']:
                self.log("   💡 建议:")
                for rec in diagnosis['recommendations']:
                    self.log(f"      - {rec}")
        
        self.log(f"\n🎯 统一模型选择: {best_model}")
        
        # 如果扰动段无法有效判断且有全量数据，使用全量数据验证
        if need_fulldata and hist_data is not None:
            fulldata_model = self._validate_model_type_with_fulldata(best_model, hist_data)
            if fulldata_model != best_model:
                self.log(f"   📊 全量数据验证: {best_model} → {fulldata_model}")
                best_model = fulldata_model
        
        return best_model
    
    def _validate_model_type_with_fulldata(self, current_model: str, 
                                            hist_data: 'HistoricalData') -> str:
        """
        使用全量数据验证/选择模型类型
        
        当扰动段拟合质量差时，用全量数据做多模型拟合来辅助判断
        """
        self.log("\n   📊 全量数据模型验证:")
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        
        if len(y) < 50:
            self.log("      数据点数不足，保持原选择")
            return current_model
        
        t = np.arange(len(y))
        y0 = y[0]
        
        model_r2s = {}
        
        for model_type in self.CANDIDATE_MODELS:
            try:
                method = self.IDENTIFY_METHODS.get(model_type)
                if method is None:
                    continue
                
                params_raw = method(t, y, u)
                y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                r2 = calculate_r2(y, y_pred)
                
                # 应用复杂度惩罚
                penalty = self._unified_selector.COMPLEXITY_PENALTY.get(model_type, 0)
                adjusted_r2 = r2 - penalty
                
                model_r2s[model_type] = {
                    'r2': r2,
                    'adjusted_r2': adjusted_r2
                }
                self.log(f"      {model_type}: R²={r2:.4f}, 调整R²={adjusted_r2:.4f}")
                
            except Exception as e:
                self.log(f"      {model_type}: 拟合失败 - {e}")
        
        if not model_r2s:
            return current_model
        
        # 选择调整R²最高的模型
        best_fulldata_model = max(model_r2s.keys(), 
                                   key=lambda m: model_r2s[m]['adjusted_r2'])
        best_r2 = model_r2s[best_fulldata_model]['adjusted_r2']
        current_r2 = model_r2s.get(current_model, {}).get('adjusted_r2', 0)
        
        # 只有当全量数据选择的模型明显更好时才替换
        if best_r2 > current_r2 + 0.05:
            self.log(f"      → 全量数据选择: {best_fulldata_model} (R²提升: {best_r2 - current_r2:.4f})")
            return best_fulldata_model
        else:
            self.log(f"      → 保持原选择: {current_model}")
            return current_model
    
    def _convert_to_segment_fits(self, segment_results: List[SegmentResult]) -> List[SegmentModelFit]:
        """将SegmentResult转换为SegmentModelFit格式"""
        segment_fits = []
        
        for result in segment_results:
            if not result.is_valid or not result.model_results:
                continue
            
            fit = SegmentModelFit(
                segment_idx=result.segment_idx,
                data_points=result.data_points,
                quality_score=result.quality_score,
                nonlinearity_score=result.nonlinearity_score,
                is_nonlinear=result.is_nonlinear,
                model_fits=result.model_results
            )
            segment_fits.append(fit)
        
        return segment_fits
    
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
                
                # 跳过K值不合理的段（已在拟合阶段标记）
                k_reasonable = fit_result.get('k_reasonable', True)
                if not k_reasonable:
                    self.log(f"      段{result.segment_idx+1}: K={K:.4f} 超出合理范围，跳过融合")
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
                    is_steady=is_steady and not result.is_nonlinear,
                    nonlinearity_score=result.nonlinearity_score,
                    quality_score=result.quality_score
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
        
        # 模型参数合理性约束（从配置获取阈值）
        param_constraints = Config.PARAMETER_CONSTRAINTS
        T1_max = param_constraints['T1_max']
        L_max = param_constraints['L_max']
        
        if fusion.T1 > T1_max:
            self.log(f"   ⚠️ T1={fusion.T1:.2f}s 过大，限制为 {T1_max}s")
            fusion.T1 = T1_max
        if fusion.L > L_max:
            self.log(f"   ⚠️ L={fusion.L:.2f}s 过大，限制为 {L_max}s")
            fusion.L = L_max
        
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
    
    def _compute_segment_metrics(self, segments: List[HistoricalData], params: tuple,
                                  model_type: str, enhanced: bool = False
                                  ) -> Tuple[List[float], List[float], List[int]]:
        """
        计算扰动段的R²和RMSE指标
        
        Args:
            segments: 扰动段数据列表
            params: 模型参数
            model_type: 模型类型
            enhanced: 是否使用增强仿真（幅度校准+偏移校正+振荡叠加）
        
        Returns:
            (r2_list, rmse_list, points_list)
        """
        r2_list = []
        rmse_list = []
        points_list = []
        
        for seg in segments:
            seg_valid = seg.pv != 0
            y = seg.pv[seg_valid]
            u = seg.mv[seg_valid]
            sv = seg.sv[seg_valid] if hasattr(seg, 'sv') and seg.sv is not None else None
            if len(y) < 5:
                continue
            
            y_pred = self._simulator.simulate_segmented(
                params, model_type, y, u,
                reset_on_sv_change=True, sv=sv,
                enable_smooth=True,
                enable_amplitude_calibration=enhanced,
                enable_offset_correction=enhanced,
                enable_oscillation_overlay=enhanced
            )
            
            r2_list.append(calculate_r2(y, y_pred))
            rmse_list.append(calculate_rmse(y, y_pred))
            points_list.append(len(y))
        
        return r2_list, rmse_list, points_list
    
    def _compute_weighted_metrics(self, r2_list: List[float], rmse_list: List[float],
                                   points_list: List[int]) -> Tuple[float, float]:
        """计算加权平均R²和RMSE"""
        if not r2_list:
            return 0.0, 0.0
        total_pts = sum(points_list)
        weighted_r2 = sum(r2 * pts for r2, pts in zip(r2_list, points_list)) / total_pts
        weighted_rmse = sum(rmse * pts for rmse, pts in zip(rmse_list, points_list)) / total_pts
        return weighted_r2, weighted_rmse
    
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
        
        # 验证阶段：不使用振荡叠加，计算原始模型的R²
        y_pred_full = self._simulator.simulate_segmented(
            params, model_type, y_full, u_full, 
            reset_on_sv_change=True, sv=sv_full,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=False
        )
        global_r2 = calculate_r2(y_full, y_pred_full)
        global_rmse = calculate_rmse(y_full, y_pred_full)
        
        self.log(f"   全量数据R²: {global_r2:.4f}, RMSE: {global_rmse:.4f}")
        
        # 计算扰动段指标（纯模型用于评分，增强用于参考）
        segment_r2s_pure, segment_rmses, segment_points = self._compute_segment_metrics(
            segments, params, model_type, enhanced=False
        )
        segment_r2s_enhanced, _, _ = self._compute_segment_metrics(
            segments, params, model_type, enhanced=True
        )
        
        # 计算加权平均
        weighted_r2, weighted_rmse = self._compute_weighted_metrics(
            segment_r2s_pure, segment_rmses, segment_points
        )
        weighted_r2_enhanced, _ = self._compute_weighted_metrics(
            segment_r2s_enhanced, segment_rmses, segment_points
        )
        
        segment_r2s = segment_r2s_pure
        
        if segment_r2s:
            self.log(f"   扰动段R²(纯模型): {[f'{r:.3f}' for r in segment_r2s_pure]}, 加权R²: {weighted_r2:.4f}")
            if any(r2_e > r2_p + 0.1 for r2_e, r2_p in zip(segment_r2s_enhanced, segment_r2s_pure)):
                self.log(f"   扰动段R²(增强后): {[f'{r:.3f}' for r in segment_r2s_enhanced]}, 加权R²: {weighted_r2_enhanced:.4f}")
        
        # 从集中化配置获取优化阈值
        opt_config = Config.OPTIMIZATION
        r2_threshold = opt_config['r2_threshold']
        min_seg_r2_threshold = opt_config['min_segment_r2']
        seg_r2_std_max = opt_config['segment_r2_std_max']
        
        min_segment_r2 = min(segment_r2s) if segment_r2s else 0
        segment_r2_std = np.std(segment_r2s) if len(segment_r2s) > 1 else 0
        
        # 保存当前参数，用于后续重新计算
        current_params = params
        
        need_optimization = (
            global_r2 < r2_threshold or
            min_segment_r2 < min_seg_r2_threshold or
            segment_r2_std > seg_r2_std_max
        )
        
        if need_optimization:
            self.log(f"   → R²<{r2_threshold}，尝试全量数据优化...")
            
            optimized_params = self._global_optimize_full(y_full, u_full, sv_full, 
                                                           model_type, params)
            
            if optimized_params is not None:
                y_pred_opt = self._simulator.simulate_segmented(
                    optimized_params, model_type, y_full, u_full,
                    reset_on_sv_change=True, sv=sv_full,
                    enable_smooth=True,
                    enable_amplitude_calibration=True,
                    enable_offset_correction=True,
                    enable_oscillation_overlay=False  # 验证时不叠加振荡
                )
                r2_opt = calculate_r2(y_full, y_pred_opt)
                rmse_opt = calculate_rmse(y_full, y_pred_opt)
                
                self.log(f"   优化后全量R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                # 检查优化后K值是否合理
                K_original = params[0]
                K_optimized = optimized_params[0]
                k_reasonable = True
                
                # K值合理性检查（从配置获取阈值）
                k_min = Config.PARAMETER_CONSTRAINTS['k_reasonable_min']
                k_ratio_max = opt_config['k_magnitude_ratio_max']
                
                if abs(K_original) > k_min:
                    if opt_config['k_sign_check'] and K_original * K_optimized < 0:  # 符号反转
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值符号反转({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) < abs(K_original) / k_ratio_max:  # K变得太小
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过小({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) > abs(K_original) * k_ratio_max:  # K变得太大
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过大({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                
                if r2_opt > global_r2 and k_reasonable:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._simulator.params_to_fusion(optimized_params, model_type, fusion)
                    
                    # 优化后也应用参数约束（从配置获取）
                    param_constraints = Config.PARAMETER_CONSTRAINTS
                    if fusion.T1 > param_constraints['T1_max']:
                        fusion.T1 = param_constraints['T1_max']
                    if fusion.L > param_constraints['L_max']:
                        fusion.L = param_constraints['L_max']
                    
                    fusion.fusion_method += " + 全量优化"
                    self.log(f"   → 采用优化结果")
        
        # 使用扰动段加权平均R²作为最终评估指标（更能反映模型在整定数据上的拟合质量）
        # 如果优化后全量R²更高，也重新计算扰动段R²（使用纯模型，不叠加振荡）
        if segment_r2s:
            # 重新计算扰动段R²（使用可能优化后的参数）
            current_params = self._simulator.fusion_to_params(fusion)
            new_segment_r2s, new_segment_rmses, new_segment_points = self._compute_segment_metrics(
                segments, current_params, model_type, enhanced=False
            )
            if new_segment_r2s:
                weighted_r2, weighted_rmse = self._compute_weighted_metrics(
                    new_segment_r2s, new_segment_rmses, new_segment_points
                )
        
        # 输出使用扰动段加权平均R²（更准确反映模型质量）
        fusion.global_r2 = weighted_r2 if segment_r2s else global_r2
        fusion.global_rmse = weighted_rmse if segment_r2s else global_rmse
        
        # 同时保存全量R²用于参考
        fusion.full_data_r2 = global_r2
        
        eval_r2 = fusion.global_r2
        if eval_r2 >= 0.9:
            quality = "优秀"
        elif eval_r2 >= 0.7:
            quality = "良好"
        elif eval_r2 >= 0.5:
            quality = "一般"
        else:
            quality = "较差"
        
        self.log(f"\n   最终评估: 扰动段R²={eval_r2:.4f} ({quality}), 全量R²={global_r2:.4f}")
        
        if eval_r2 < 0.5:
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
        """
        全量数据优化
        
        增强：
        1. 检测高振荡数据并预处理
        2. 添加幅度约束确保K值合理
        3. 多起点优化提高鲁棒性
        """
        try:
            from .fitting import ModelIdentifier
            
            # 检测是否为高振荡数据
            oscillation_info = ModelIdentifier.detect_high_oscillation(y_full, u_full)
            
            if oscillation_info['is_oscillating']:
                # 对高振荡数据预处理
                filter_size = oscillation_info['recommended_filter_size']
                y_opt, u_opt = ModelIdentifier.preprocess_oscillating_data(y_full, u_full, filter_size)
                self.log(f"   检测到高振荡数据(振荡比={oscillation_info['oscillation_ratio']:.2f})，使用滤波预处理")
            else:
                y_opt, u_opt = y_full, u_full
            
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
            
            # 计算期望的K值范围用于约束
            pv_range = np.max(y_full) - np.min(y_full)
            mv_range = np.max(u_full) - np.min(u_full)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 0.5 else 0.5
            k_min = k_expected * 0.2
            k_max = k_expected * 3.0
            
            def objective(params):
                y_pred_all = np.zeros_like(y_opt)
                
                for i in range(len(reset_points) - 1):
                    start_idx = reset_points[i]
                    end_idx = reset_points[i + 1]
                    
                    if end_idx <= start_idx:
                        continue
                    
                    y0 = y_opt[start_idx]
                    t_seg = np.arange(end_idx - start_idx, dtype=float)
                    u_seg = u_opt[start_idx:end_idx]
                    
                    y_seg = self._simulator.simulate(tuple(params), model_type, t_seg, u_seg, y0)
                    y_pred_all[start_idx:end_idx] = y_seg
                
                y_std = np.std(y_opt)
                if y_std < self._epsilon:
                    y_std = 1.0
                
                residuals = (y_opt - y_pred_all) / y_std
                
                # 添加K值范围惩罚
                K = abs(params[0])
                if K < k_min or K > k_max:
                    k_penalty = min(abs(K - k_expected) / k_expected, 1.0) * 0.1
                    residuals = residuals * (1 + k_penalty)
                
                return residuals
            
            bounds = self._get_bounds(model_type)
            
            best_params = None
            best_cost = float('inf')
            
            # 使用更合理的初始点
            init_points = [
                initial_params,
                self._simulator.create_init_params(model_type, k_expected, 5.0),
                self._simulator.create_init_params(model_type, k_expected * 0.7, 10.0),
                self._simulator.create_init_params(model_type, k_expected * 0.5, 15.0),
            ]
            
            # 如果检测到负相关，添加负增益初始点
            corr = np.corrcoef(u_full, y_full)[0, 1] if len(u_full) > 2 else 0
            if not np.isnan(corr) and corr < -0.3:
                init_points.append(self._simulator.create_init_params(model_type, -k_expected, 5.0))
            
            for init_p in init_points:
                try:
                    result = least_squares(objective, init_p, bounds=bounds,
                                           method='trf', max_nfev=1000)
                    
                    if result.success and result.cost < best_cost:
                        # 验证结果的幅度合理性
                        y_pred_check = self._simulator.simulate_segmented(
                            tuple(result.x), model_type, y_full, u_full,
                            reset_on_sv_change=True, sv=sv_full,
                            enable_amplitude_calibration=False,
                            enable_offset_correction=False,
                            enable_smooth=False
                        )
                        pred_range = np.ptp(y_pred_check)
                        amplitude_ratio = pred_range / (pv_range + self._epsilon)
                        
                        # 只接受幅度合理的结果（从配置获取阈值）
                        amp_min = Config.OPTIMIZATION['amplitude_ratio_min']
                        amp_max = Config.OPTIMIZATION['amplitude_ratio_max']
                        if amp_min < amplitude_ratio < amp_max:
                            best_cost = result.cost
                            best_params = tuple(result.x)
                except Exception:
                    # 优化失败，尝试下一个初始点
                    continue
            
            # 如果优化结果的K值不合理，进行校正
            if best_params is not None:
                y_pred_final = self._simulator.simulate_segmented(
                    best_params, model_type, y_full, u_full,
                    reset_on_sv_change=True, sv=sv_full,
                    enable_amplitude_calibration=False,
                    enable_offset_correction=False,
                    enable_smooth=False
                )
                pred_range = np.ptp(y_pred_final)
                
                if pred_range > self._epsilon and pv_range > self._epsilon:
                    amplitude_ratio = pred_range / pv_range
                    if amplitude_ratio > 1.5 or amplitude_ratio < 0.5:
                        # 校正K值
                        K_correction = pv_range / pred_range
                        best_params = list(best_params)
                        best_params[0] = best_params[0] * K_correction
                        best_params = tuple(best_params)
                        self.log(f"   K值校正: 幅度比={amplitude_ratio:.2f}, 校正因子={K_correction:.2f}")
            
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
        except Exception as e:
            self.log(f"      默认拟合失败: {e}")
        
        try:
            y_f, u_f = self._preprocessor.preprocess(y, u)
            params = method(t, y_f, u_f)
            y_pred = self._simulator.simulate(params, model_type, t, u, y0)
            r2 = calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except Exception as e:
            self.log(f"      预处理拟合失败: {e}")
        
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
            except Exception:
                # 扰动优化失败，使用已有最佳结果
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
                      time_range: Dict, lambda_factor: float,
                      tuning_windows: List[Dict] = None,
                      quality_info: DataQualityInfo = None) -> Dict[str, Any]:
        """
        构建最终输出
        
        Args:
            quality_info: 数据质量信息，用于自适应保守PID整定
        """
        pid_params = self._pid_calculator.calculate_from_fusion(
            fusion, lambda_factor, quality_info=quality_info
        )
        
        params = self._simulator.fusion_to_params(fusion)
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = np.array(hist_data.timestamp[valid_mask], dtype=np.int64)  # 确保是 int64 类型
        sv = hist_data.sv[valid_mask]
        
        # 构建扰动段掩码：只在扰动段内使用模型拟合
        disturbance_mask = np.zeros(len(ts), dtype=bool)
        if tuning_windows:
            for window in tuning_windows:
                # 支持 TuningWindow 对象或字典
                if hasattr(window, 'start_time'):
                    start_ts = parse_time_to_milliseconds(window.start_time)
                    end_ts = parse_time_to_milliseconds(window.end_time)
                else:
                    start_ts = parse_time_to_milliseconds(window.get('start_time'))
                    end_ts = parse_time_to_milliseconds(window.get('end_time'))
                disturbance_mask |= (ts >= start_ts) & (ts <= end_ts)
        
        # 对全量数据进行模型仿真
        pv_model_full = self._simulator.simulate_segmented(
            params, fusion.model_type, y, u, 
            reset_on_sv_change=True, sv=sv,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=True
        )
        
        # pv_model: 扰动段用模型拟合，稳态段用实际PV
        pv_model = y.copy()  # 先用实际PV填充
        pv_model[disturbance_mask] = pv_model_full[disturbance_mask]  # 扰动段用模型值
        
        sim_r2 = calculate_r2(y, pv_model)
        
        pv_diff = np.diff(y)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        oscillation_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
        
        pv_range = np.ptp(y)
        model_range = np.ptp(pv_model)
        amplitude_ratio = model_range / (pv_range + self._epsilon) if pv_range > 0.1 else 1.0
        
        self.log(f"   pv_model检查: sim_R²={sim_r2:.3f}, 振荡={oscillation_ratio:.2f}, "
                f"PV范围={pv_range:.2f}, 模型范围={model_range:.2f}, 幅度比={amplitude_ratio:.2f}")
        
        # 从配置读取阈值
        ms_cfg = Config.MODEL_SELECTOR
        
        sim_quality_poor = (
            sim_r2 < ms_cfg['sim_r2_poor_threshold'] or
            fusion.global_r2 < Config.MODEL_FITTING['r2_poor_threshold'] or
            oscillation_ratio > ms_cfg['oscillation_poor_threshold'] or
            amplitude_ratio < ms_cfg['amplitude_ratio_min'] or 
            amplitude_ratio > ms_cfg['amplitude_ratio_max']
        )
        
        fitting_failed = (
            fusion.n_segments_used == 0 or
            sim_r2 < ms_cfg['sim_r2_fail_threshold'] or
            amplitude_ratio < ms_cfg['amplitude_ratio_fail_min'] or 
            amplitude_ratio > ms_cfg['amplitude_ratio_fail_max']
        )
        
        if fitting_failed:
            self.log(f"   ❌ 拟合完全失败，保留原始pv_model用于诊断分析")
        elif sim_quality_poor:
            reason = []
            if sim_r2 < ms_cfg['sim_r2_poor_threshold']:
                reason.append(f"R²={sim_r2:.3f}")
            if oscillation_ratio > ms_cfg['oscillation_poor_threshold']:
                reason.append(f"振荡={oscillation_ratio:.2f}")
            if amplitude_ratio < ms_cfg['amplitude_ratio_min'] or amplitude_ratio > ms_cfg['amplitude_ratio_max']:
                reason.append(f"幅度比={amplitude_ratio:.2f}")
            self.log(f"   ⚠️ 模型仿真质量较差({', '.join(reason)})")
        
        total_data_points = int(np.sum(valid_mask))
        
        # 先进行闭环稳定性验证（使用实际数据的初值）
        sp_initial = float(sv[0]) if len(sv) > 0 else ms_cfg['default_sp_initial']
        sp_final = float(sv[-1]) if len(sv) > 0 else ms_cfg['default_sp_final']
        pv_initial = float(y[0]) if len(y) > 0 else sp_initial
        
        # 确保有足够的阶跃幅度，并且初值合理
        sp_change = abs(sp_final - sp_initial)
        pv_sp_diff = abs(pv_initial - sp_initial)
        
        # 如果 SP 阶跃幅度太小，或者 PV 初值与 SP 初值差距太大，使用默认阶跃测试
        if sp_change < ms_cfg['min_sp_change'] or pv_sp_diff > sp_change * 2:
            sp_initial = ms_cfg['default_sp_initial']
            sp_final = ms_cfg['default_sp_final']
            pv_initial = ms_cfg['default_pv_initial']
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            fusion, pid_params, 
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            verbose=self._verbose
        )
        
        # 再计算 model_rating（传入闭环指标）
        model_rating, score_details = self._pid_calculator.calculate_model_rating(
            fusion, total_data_points, cl_metrics=cl_metrics, verbose=self._verbose
        )
        
        if self._verbose:
            self.log(f"\n   📊 评分详情:")
            self.log(f"      拟合质量 (R²={fusion.global_r2:.3f}): {score_details.get('r2_score', 0):.1f}/10 × 30%")
            self.log(f"      参数一致性: {score_details.get('consistency_score', 0):.1f}/10 × 20%")
            self.log(f"      参数合理性: {score_details.get('validity_score', 0):.1f}/10 × 15%")
            self.log(f"      数据覆盖度 ({fusion.n_segments_used}段/{total_data_points}点): {score_details.get('coverage_score', 0):.1f}/10 × 10%")
            self.log(f"      闭环稳定性: {score_details.get('stability_score', 0):.1f}/10 × 25%")
            self.log(f"      → 综合评分: {model_rating}/10")
        
        closed_loop_info = {
            'is_stable': is_stable,
            'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot,
            'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error,
            'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio
        }
        
        # success条件：拟合成功 且 闭环稳定
        success = (not fitting_failed) and is_stable
        
        return {
            'success': success,
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
            'closed_loop_verification': closed_loop_info,
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
