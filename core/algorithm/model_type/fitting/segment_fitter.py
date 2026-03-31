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
from .nonlinear_fitter import NonlinearFitter
from ..logger import LoggerMixin
from ..utils import calculate_r2, calculate_rss, calculate_aic, calculate_bic


class SegmentFitter(LoggerMixin):
    """
    段拟合器 - 对每个扰动段尝试多种模型拟合
    
    职责：
    1. 对每个有效段尝试所有候选模型
    2. 检测高振荡数据并特殊处理
    3. 选择每段的最佳模型
    4. 尝试振荡临界法整定
    """
    
    # 使用统一的常量定义（来自 ModelType）
    CANDIDATE_MODELS = ModelType.CANDIDATE_MODELS
    MODEL_PARAM_COUNT = ModelType.MODEL_PARAM_COUNT
    
    # 模型优先级（简单→复杂），用于早停优化
    MODEL_PRIORITY = [ModelType.FOPDT, ModelType.FO, ModelType.SO, ModelType.SOPDT, ModelType.FOPI]
    # 振荡数据时跳过的模型（这些模型对振荡数据效果差）
    SKIP_ON_OSCILLATION = {ModelType.SOPDT, ModelType.FOPI}
    # 早停R²阈值：简单模型达到此阈值则跳过复杂模型
    EARLY_STOP_R2 = 0.7
    
    # 模型辨识方法映射（保留在此处，因为依赖 ModelIdentifier）
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
        self._nonlinear_fitter = NonlinearFitter(verbose=verbose)
    
    def fit_all_segments(self, segments: List[HistoricalData],
                         segment_results: List[SegmentResult],
                         controller_sign: int = 1) -> List[SegmentResult]:
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
            
            valid_mask = seg.valid_mask()
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
                    # 轻微振荡：使用自适应滤波预处理
                    y_fit, u_fit, filter_info = self._preprocessor.adaptive_filter(
                        y, u, 
                        oscillation_ratio=oscillation_info['oscillation_ratio'],
                        noise_ratio=None
                    )
                    self.log(f"   🔧 自适应滤波: {filter_info['method']}, window={filter_info['window']}")
                    k_expected = abs(ModelIdentifier.estimate_gain_from_oscillating_data(y, u))
                
                # 根据振荡程度调整K值允许范围
                # 放宽上限：积分环节(液位)用一阶模型拟合时，K和T1会极大，不应被严格的稳态比率截断
                if severity == 'severe' or envelope_ratio > 0.5:
                    k_min = k_expected * 0.2
                    k_max = max(k_expected * 10.0, 50.0)
                elif severity == 'moderate':
                    k_min = k_expected * 0.1
                    k_max = max(k_expected * 15.0, 100.0)
                else:
                    k_min = k_expected * 0.1
                    k_max = max(k_expected * 20.0, 200.0)
            else:
                # 非振荡数据：也应用自适应滤波（如果数据噪声较大）
                # 同样放宽默认上限
                k_min = k_expected * 0.1
                k_max = max(k_expected * 20.0, 200.0)
                
                y_fit, u_fit, filter_info = self._preprocessor.adaptive_filter(y, u)
                if filter_info.get('adaptive') and filter_info.get('noise_level') != 'low':
                    self.log(f"   🔧 自适应滤波: {filter_info['method']}, window={filter_info['window']}")
            
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated or is_oscillating
            
            best_r2_so_far = 0.0
            for model_type in self.MODEL_PRIORITY:
                # 早停优化：简单模型效果已经很好，跳过复杂模型
                if best_r2_so_far >= self.EARLY_STOP_R2 and model_type in {ModelType.SOPDT, ModelType.FOPI}:
                    self.log(f"   {model_type}: 跳过(早停, R²={best_r2_so_far:.2f})")
                    continue
                
                # 振荡数据跳过不适合的模型
                if is_oscillating and model_type in self.SKIP_ON_OSCILLATION:
                    self.log(f"   {model_type}: 跳过(振荡数据)")
                    continue
                
                try:
                    if use_multi_start:
                        params_raw, _ = self._multi_start_fit(t, y_fit, u_fit, model_type, controller_sign=controller_sign)
                    else:
                        method = self.IDENTIFY_METHODS.get(model_type)
                        params_raw = method(t, y_fit, u_fit, controller_sign=controller_sign)
                    
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
                    
                    # ========== 剧烈震荡导致负K值的自动校正 ==========
                    # 当检测到高振荡且K为负时，很可能是相位偏移导致的误判
                    # 真正的反向作用系统（制冷、减压）通常不会有剧烈震荡
                    fitted_k_raw = params_dict['K']
                    k_sign_corrected = False
                    oscillation_ratio = oscillation_info.get('oscillation_ratio', 0) if is_oscillating else 0
                    
                    if fitted_k_raw < 0 and is_oscillating:
                        # 剧烈震荡（ratio > 0.5）时，负K很可能是相位偏移导致
                        # [Phase G] 如果控制器符号为负且K也为负，说明辨识结果与现状一致，应保留
                        if controller_sign == -1:
                            self.log(f"   ℹ️ {model_type}: 检测到震荡且负K={fitted_k_raw:.4f}，"
                                    f"与反向控制器符号一致，跳过校正。")
                        else:
                            osc_negative_k_threshold = Config.OSCILLATION_TUNING.get('negative_k_oscillation_threshold', 0.3)
                            osc_severe_threshold = Config.OSCILLATION_TUNING.get('negative_k_severe_threshold', 0.5)
                            
                            if oscillation_ratio > osc_severe_threshold:
                                # 剧烈震荡：直接取绝对值
                                params_raw = list(params_raw)
                                params_raw[0] = abs(params_raw[0])
                                params_raw = tuple(params_raw)
                                params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                                y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                                r2 = calculate_r2(y, y_pred)
                                k_sign_corrected = True
                                self.log(f"   ⚠️ {model_type}: 剧烈震荡(ratio={oscillation_ratio:.2f})导致负K={fitted_k_raw:.4f}，"
                                        f"自动校正为K={params_dict['K']:.4f}")
                            elif oscillation_ratio > osc_negative_k_threshold:
                                # 中等震荡：比较正负K的拟合效果
                                params_raw_pos = list(params_raw)
                                params_raw_pos[0] = abs(params_raw_pos[0])
                                params_raw_pos = tuple(params_raw_pos)
                                y_pred_pos = self._simulator.simulate(params_raw_pos, model_type, t, u, y0)
                                r2_pos = calculate_r2(y, y_pred_pos)
                                
                                # 如果正K的R²更好或相近，使用正K
                                if r2_pos >= r2 - 0.05:
                                    params_raw = params_raw_pos
                                    params_dict = self._simulator.PARAM_FORMATS[model_type](params_raw)
                                    y_pred = y_pred_pos
                                    r2 = r2_pos
                                    k_sign_corrected = True
                                    self.log(f"   ⚠️ {model_type}: 中等震荡(ratio={oscillation_ratio:.2f})，"
                                            f"负K={fitted_k_raw:.4f}校正为K={params_dict['K']:.4f} (R²: {r2:.4f})")
                    
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
                        'k_sign_corrected': k_sign_corrected,  # 标记K符号是否被校正
                        'k_original': fitted_k_raw if k_sign_corrected else params_dict['K'],  # 原始K值
                        'is_oscillating': is_oscillating,
                        'oscillation_severity': severity if is_oscillating else 'none',
                        'oscillation_ratio': oscillation_ratio
                    }
                    
                    # 更新最佳R²用于早停判断
                    if r2_adjusted > best_r2_so_far and k_reasonable:
                        best_r2_so_far = r2_adjusted
                    
                    k_flag = "✓" if k_reasonable else "✗"
                    osc_flag = " [振荡]" if is_oscillating else ""
                    self.log(f"   {model_type}: R²={r2:.4f}, AIC={aic:.1f}, "
                             f"K={params_dict['K']:.4f} {k_flag}, T1={params_dict['T1']:.2f}{osc_flag}")
                    
                except (ValueError, np.linalg.LinAlgError, RuntimeError, FloatingPointError) as e:
                    self.log(f"   {model_type}: 拟合失败 - {e}")
                    result.model_results[model_type] = {
                        'r2': 0.0, 'rss': float('inf'), 'aic': float('inf')
                    }
            
            self._select_segment_best_model(result, i)
            
            # 非线性模型拟合（当检测到非线性特征时）
            if Config.NONLINEAR_FITTING.get('enable', True):
                self._try_nonlinear_fitting(result, y, u, i)
        
        return segment_results
    
    def _try_nonlinear_fitting(self, result: SegmentResult, y: np.ndarray, 
                               u: np.ndarray, idx: int):
        """
        尝试非线性模型拟合
        
        当检测到非线性特征且线性模型拟合不佳时，尝试非线性模型
        """
        # 检测非线性特征
        try:
            detection = self._nonlinear_fitter.detect_nonlinearity(y, u)
        except Exception as e:
            self.log(f"   ⚠️ 非线性检测异常: {e}")
            return
        
        # 记录非线性检测结果
        result.nonlinearity_score = detection.nonlinearity_score
        nonlinear_threshold = Config.NONLINEAR_FITTING.get('nonlinearity_threshold', 0.4)
        result.is_nonlinear = detection.nonlinearity_score > nonlinear_threshold
        
        # 判断是否需要尝试非线性模型
        should_try_nonlinear = (
            detection.nonlinearity_score > nonlinear_threshold or
            detection.has_deadband or
            detection.has_saturation or
            (result.best_r2 < 0.6 and detection.nonlinearity_score > 0.2)
        )
        
        self.log(f"   📊 非线性检测: score={detection.nonlinearity_score:.3f}, "
                f"死区={detection.has_deadband}, 饱和={detection.has_saturation}, "
                f"阈值={nonlinear_threshold}, 触发={should_try_nonlinear}")
        
        if not should_try_nonlinear:
            return
        
        self.log(f"   🔍 检测到非线性特征: 非线性度={detection.nonlinearity_score:.2f}, "
                f"死区={detection.has_deadband}, 饱和={detection.has_saturation}")
        
        # 获取线性模型的R²作为基准
        linear_r2 = result.best_r2 or 0
        
        # 拟合非线性模型
        nonlinear_results = self._nonlinear_fitter.fit_nonlinear_models(
            y, u, detection, linear_r2
        )
        
        # 选择最佳模型
        if nonlinear_results:
            best_nonlinear = max(nonlinear_results, key=lambda r: r.r2)
            
            # 如果非线性模型显著优于线性模型，更新结果
            improvement_threshold = Config.NONLINEAR_FITTING['r2_improvement_threshold']
            if best_nonlinear.improvement_over_linear > improvement_threshold:
                self.log(f"   ✅ 非线性模型 {best_nonlinear.model_type} 更优: "
                        f"R²={best_nonlinear.r2:.4f} (提升{best_nonlinear.improvement_over_linear:.4f})")
                
                # 将非线性模型结果添加到 model_results
                result.model_results[best_nonlinear.model_type] = {
                    'K': best_nonlinear.params.get('K', best_nonlinear.linear_equivalent.get('K', 1.0)),
                    'T1': best_nonlinear.params.get('T1', best_nonlinear.linear_equivalent.get('T1', 10.0)),
                    'T2': 0.0,
                    'L': best_nonlinear.params.get('L', best_nonlinear.linear_equivalent.get('L', 0.0)),
                    'params_raw': tuple(best_nonlinear.params.values()),
                    'r2': best_nonlinear.r2,
                    'r2_adjusted': best_nonlinear.r2,
                    'rmse': best_nonlinear.rmse,
                    'rss': best_nonlinear.rmse ** 2 * len(y),
                    'aic': float('inf'),  # 非线性模型不计算AIC
                    'k_reasonable': True,
                    'is_nonlinear': True,
                    'nonlinear_params': best_nonlinear.params,
                    'linear_equivalent': best_nonlinear.linear_equivalent,
                }
                
                # 更新最佳模型
                result.best_model = best_nonlinear.model_type
                result.best_r2 = best_nonlinear.r2
            else:
                self.log(f"   📊 非线性模型提升不足 ({best_nonlinear.improvement_over_linear:.4f}), 保持线性模型")
    
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
    
    def _multi_start_fit(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                         model_type: str, n_starts: int = 3, controller_sign: int = 1) -> Tuple[tuple, float]:
        """多起点拟合"""
        method = self.IDENTIFY_METHODS.get(model_type)
        bounds = self._get_bounds(model_type)
        y0 = y[0]
        
        best_params = None
        best_r2 = -1
        
        try:
            params = method(t, y, u, controller_sign=controller_sign)
            y_pred = self._simulator.simulate(params, model_type, t, u, y0)
            r2 = calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except Exception as e:
            self.log(f"      默认拟合失败: {e}")
        
        try:
            y_f, u_f = self._preprocessor.preprocess(y, u)
            params = method(t, y_f, u_f, controller_sign=controller_sign)
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
                    perturbed, bounds=bounds, method='trf', 
                    max_nfev=100,  # 减少最大函数评估次数
                    ftol=1e-4,     # 放宽函数收敛容差
                    xtol=1e-4,     # 放宽参数收敛容差
                    gtol=1e-4      # 放宽梯度容差
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
        """获取参数边界（委托给 ModelType.get_bounds）"""
        return ModelType.get_bounds(model_type)
