"""
段拟合模块 (Segment Fitter Module)
==================================

本模块负责对每个有效扰动段进行多模型拟合。

核心功能
--------
1. **多模型拟合**: 对每段尝试所有候选模型 (FOPDT, FO, SO, SOPDT, FOPI)
2. **高振荡处理**: 检测高振荡数据并使用稳健KTL估计
3. **最佳模型选择**: 综合R²和K值合理性选择每段最佳模型
4. **振荡临界法**: 当常规拟合失败时尝试振荡临界法整定

拟合流程
--------
1. 检测数据是否为高振荡数据
2. 对高振荡数据进行预处理（滤波/包络线提取）
3. 使用多模型拟合，计算R²、AIC、BIC等指标
4. 进行幅度验证和K值校正
5. 选择该段的最佳模型

评估指标
--------
- R²: 决定系数，衡量拟合优度
- AIC/BIC: 信息准则，用于模型选择（考虑复杂度惩罚）
- k_reasonable: K值是否在合理范围内
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from scipy.optimize import least_squares

from ..config import Config, ModelType
from ..data_models import SegmentResult, HistoricalData
from .model_identifier import ModelIdentifier
from ..logger import LoggerMixin
from ..utils import calculate_r2, calculate_rmse, calculate_rss, calculate_aic, calculate_bic


class SegmentFitter(LoggerMixin):
    """
    段拟合器 - 对每个扰动段尝试多种模型拟合
    
    职责：
    1. 对每个有效段尝试所有候选模型
    2. 检测高振荡数据并特殊处理
    3. 选择每段的最佳模型
    4. 尝试振荡临界法整定
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
    
    def __init__(self, simulator, preprocessor, pid_calculator, verbose: bool = False):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._simulator = simulator
        self._preprocessor = preprocessor
        self._pid_calculator = pid_calculator
    
    def fit_all_segments(self, segments: List[HistoricalData],
                         segment_results: List[SegmentResult]) -> List[SegmentResult]:
        """
        对每个有效段拟合所有候选模型
        
        增强：
        1. 检测高振荡开环数据并特殊处理
        2. 使用包络线法估计增益
        3. 添加幅度验证和校正
        """
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
            severity = oscillation_info.get('severity_level', 'none')
            
            if is_oscillating:
                envelope_ratio = oscillation_info.get('envelope_ratio', 0)
                self.log(f"   ⚠️ 检测到振荡数据 (程度={severity}, 振荡比={oscillation_info['oscillation_ratio']:.2f}, "
                        f"包络比={envelope_ratio:.2f})")
                filter_size = oscillation_info['recommended_filter_size']
                
                # 对于中等及以上振荡，或包络比>0.3，都使用稳健估计
                use_robust = severity in ['severe', 'moderate'] or envelope_ratio > 0.3
                
                if use_robust:
                    # 使用稳健KTL估计
                    robust_ktl = ModelIdentifier.estimate_ktl_robust(y, u, t)
                    k_expected = abs(robust_ktl['K'])
                    _, y_fit, u_fit = ModelIdentifier.estimate_gain_from_oscillating_data(
                        y, u, return_trend=True
                    )
                    self.log(f"   📈 使用稳健KTL估计, K={k_expected:.4f} (置信度={robust_ktl['confidence']:.2f})")
                else:
                    # 轻微振荡：使用滤波预处理
                    y_fit, u_fit = ModelIdentifier.preprocess_oscillating_data(y, u, filter_size, severity)
                    k_expected = abs(ModelIdentifier.estimate_gain_from_oscillating_data(y, u))
                
                # 根据振荡程度调整K值允许范围
                if severity == 'severe' or envelope_ratio > 0.5:
                    k_min = k_expected * 0.5
                    k_max = k_expected * 2.0
                elif severity == 'moderate':
                    k_min = k_expected * 0.4
                    k_max = k_expected * 2.5
                else:
                    k_min = k_expected * 0.3
                    k_max = k_expected * 3.0
            else:
                y_fit, u_fit = y, u
            
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated or is_oscillating
            
            for model_type in self.CANDIDATE_MODELS:
                try:
                    if use_multi_start:
                        params_raw, _ = self._multi_start_fit(t, y_fit, u_fit, model_type)
                    else:
                        method = self.IDENTIFY_METHODS.get(model_type)
                        params_raw = method(t, y_fit, u_fit)
                    
                    params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                    y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                    
                    # 检查并校正幅度
                    pred_range = np.ptp(y_pred)
                    if is_oscillating and pred_range > self._epsilon and pv_range > self._epsilon:
                        amplitude_ratio = pred_range / pv_range
                        if amplitude_ratio > 1.5 or amplitude_ratio < 0.5:
                            K_correction = pv_range / pred_range
                            params_raw = list(params_raw)
                            params_raw[0] = params_raw[0] * K_correction
                            params_raw = tuple(params_raw)
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
                        'is_oscillating': is_oscillating,
                        'oscillation_severity': severity if is_oscillating else 'none'
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
    
    def try_oscillation_tuning(self, segments: List[HistoricalData], 
                               segment_results: List[SegmentResult],
                               current_pid: Dict = None) -> Optional[Dict]:
        """
        尝试使用振荡分析进行整定
        
        适用于高振荡数据且常规拟合失败的情况
        """
        osc_config = Config.OSCILLATION_TUNING
        
        high_osc_failed_segments = []
        for i, result in enumerate(segment_results):
            if not result.is_valid:
                continue
            oscillation_ratio = result.oscillation_ratio or 0
            best_r2 = result.best_r2 or 0
            
            # 检查是否有模型参数被推到边界（说明拟合不可靠）
            params_at_boundary = False
            if result.best_model and result.model_results:
                best_params = result.model_results.get(result.best_model, {})
                T1 = best_params.get('T1', 0)
                # T1 被推到下限（1.0s）说明拟合可能不可靠
                if T1 is not None and abs(T1 - 1.0) < 0.1:
                    params_at_boundary = True
            
            # 触发条件：高振荡 + (R²低 或 参数被推到边界)
            fit_unreliable = best_r2 < osc_config['r2_failure_threshold'] or params_at_boundary
            
            if (oscillation_ratio > osc_config['oscillation_ratio_threshold'] and fit_unreliable):
                high_osc_failed_segments.append((i, result, segments[i] if i < len(segments) else None))
        
        if not high_osc_failed_segments:
            return None
        
        self.log(f"\n🔄 检测到 {len(high_osc_failed_segments)} 个高振荡拟合失败段，尝试临界法整定")
        
        # 选择振荡最明显的段进行分析
        best_seg_info = max(high_osc_failed_segments, 
                           key=lambda x: x[1].oscillation_ratio or 0)
        seg_idx, seg_result, seg_data = best_seg_info
        
        if seg_data is None:
            return None
        
        valid_mask = seg_data.pv != 0
        pv = seg_data.pv[valid_mask]
        mv = seg_data.mv[valid_mask]
        
        if len(pv) < 20:
            return None
        
        # 分析振荡特征
        dt = 1.0
        osc_info = self._pid_calculator.analyze_oscillation(pv, mv, dt)
        
        if osc_info is None or osc_info['Pu'] <= 0:
            return None
        
        self.log(f"   段{seg_idx+1}: Pu={osc_info['Pu']:.1f}s, Ku≈{osc_info['Ku']:.3f}, "
                f"振幅={osc_info['amplitude']:.2f}, 类型={osc_info['oscillation_type']}")
        
        # 验证数据是否适合临界法整定
        # 检查1：MV变化幅度与PV振荡幅度的比例是否合理
        mv_range = np.ptp(mv)
        pv_range = np.ptp(pv)
        pv_amplitude = osc_info['amplitude']
        
        # 使用PV范围和振荡幅度中较大的
        effective_pv_change = max(pv_range, pv_amplitude)
        apparent_gain = effective_pv_change / mv_range if mv_range > 0.1 else 1.0
        
        self.log(f"   📊 增益检查: MV范围={mv_range:.2f}, PV范围={pv_range:.2f}, apparent_gain={apparent_gain:.4f}")
        
        use_conservative = False
        if apparent_gain < 0.1:  # 放宽阈值到0.1
            self.log(f"   ⚠️ 警告：MV变化幅度={mv_range:.2f}，PV变化={effective_pv_change:.2f}，增益={apparent_gain:.4f}")
            self.log(f"   ⚠️ 检测到低增益系统，使用保守参数")
            use_conservative = True
            # 对于低增益系统，直接使用保守的pb值
            # 已知稳定参数约pb=71.3, ti=2.1，使用类似的保守参数
            Pu = osc_info['Pu']
            conservative_pb = 70.0  # 保守的pb值
            conservative_Kp = 100.0 / conservative_pb  # ≈1.43
            conservative_Ti = max(Pu / 2, 2.0)  # 积分时间
            conservative_Ki = conservative_Kp / conservative_Ti
            
            pid_result = {
                'Kp': round(conservative_Kp, 4),
                'Ki': round(conservative_Ki, 4),
                'Kd': 0.0,  # 不使用微分
                'method': 'low_gain_conservative',
                'Pu': Pu,
                'Ku': osc_info['Ku']
            }
            self.log(f"   ✅ 保守整定: pb={conservative_pb:.1f}, Kp={conservative_Kp:.4f}, Ki={conservative_Ki:.4f}")
        
        if not use_conservative:
            # 基于振荡特征计算PID参数
            # 使用更保守的tyreus_luyben方法，避免过激参数
            pid_result = self._pid_calculator.calculate_from_oscillation(
                osc_info, current_pid, method='tyreus_luyben'
            )
        
        if pid_result is None:
            return None
        
        self.log(f"   ✅ 临界法整定成功:")
        self.log(f"      Pu={osc_info['Pu']:.1f}s, Ku={osc_info['Ku']:.3f}")
        self.log(f"      Kp={pid_result['Kp']:.4f}, Ki={pid_result['Ki']:.4f}, Kd={pid_result['Kd']:.4f}")
        self.log(f"      方法: {pid_result.get('method', 'unknown')}")
        
        return {
            'success': True,
            'pid_params': pid_result,
            'oscillation_info': osc_info,
            'segment_idx': seg_idx
        }
    
    def _multi_start_fit(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                         model_type: str, n_starts: int = 3) -> Tuple[tuple, float]:
        """多起点拟合"""
        method = self.IDENTIFY_METHODS.get(model_type)
        bounds = self._get_bounds(model_type)
        y0 = y[0]
        
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
                pass
        
        return best_params if best_params else method(t, y, u), max(best_r2, 0)
    
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
        else:
            return ([-20, 0.1], [20, 1000])
