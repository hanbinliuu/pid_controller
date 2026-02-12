"""PID参数计算模块 (PID Calculator Module)
=======================================

本模块基于辨识的模型参数计算最优PID整定参数。

核心功能
--------
1. **多种整定方法**: Lambda/IMC法、Cohen-Coon法、Ziegler-Nichols临界法
2. **自适应保守调整**: 根据数据质量自动调整保守程度
3. **振荡分析整定**: 对高振荡数据使用临界法整定
4. **闭环稳定性验证**: 仿真验证PID参数的闭环性能
"""

import numpy as np
from typing import Dict, Tuple, Optional

from ...config import Config, ModelType
from ...data_models import FusionResult

from .data_classes import ClosedLoopMetrics, DataQualityInfo
from .tuning_methods import TuningMethodsMixin
from ..oscillation.oscillation_analysis import OscillationAnalysisMixin
from ..verification.closed_loop_sim import ClosedLoopSimMixin
from ..verification.model_rating import ModelRatingMixin
from ...config.loop_presets import get_loop_preset


EPSILON = Config.EPSILON


class PIDCalculator(TuningMethodsMixin, OscillationAnalysisMixin, 
                    ClosedLoopSimMixin, ModelRatingMixin):
    """
    PID参数计算器
    
    继承自:
    - TuningMethodsMixin: 整定公式 (_tune_fo, _tune_fopdt, 等)
    - OscillationAnalysisMixin: 振荡分析 (analyze_oscillation, 等)
    - ClosedLoopSimMixin: 闭环仿真 (simulate_closed_loop, 等)
    - ModelRatingMixin: 模型评分 (calculate_model_rating)
    """
    
    def __init__(self):
        self._epsilon = EPSILON
        self._pid_constraints = Config.PID_CONSTRAINTS
    
    def _get_fallback_params(self, Ti_override: float = None) -> Tuple[float, float, float]:
        """获取回退PID参数"""
        cfg = self._pid_constraints
        Kp = cfg.get('fallback_kp', 1.0)
        Ti = Ti_override if Ti_override is not None else cfg.get('fallback_ti', 20.0)
        Td = cfg.get('fallback_td', 0.0)
        return Kp, Ti, Td
    
    def _get_max_kp(self, pb_min: float) -> float:
        """根据pb_min计算Kp上限"""
        kp_max_from_pb = self._pid_constraints.get('kp_max_from_pb', 100.0)
        return kp_max_from_pb / pb_min
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float,
                  method: str = 'lambda',
                  quality_info: Optional[DataQualityInfo] = None,
                  response_mode: str = 'balanced',
                  loop_type: str = None) -> Dict[str, float]:
        """根据模型类型和整定方法计算PID参数"""
        K_sign = 1 if K >= 0 else -1
        K_abs = max(abs(K), self._epsilon)
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T2 = max(T2, 0.0)
        
        conservative_level, pb_min = self._calculate_conservative_level(quality_info, response_mode)
        
        # 应用回路类型预设的安全系数
        if loop_type:
            preset = get_loop_preset(loop_type)
            safety = preset.get('safety_factor', 1.0)
            if safety != 1.0:
                conservative_level *= safety
        
        if model_type == ModelType.FO:
            Kp, Ti, Td = self._tune_fo(K_abs, T1, lambda_factor, method,
                                        conservative_level, pb_min, loop_type)
        elif model_type == ModelType.FOPDT:
            Kp, Ti, Td = self._tune_fopdt(K_abs, T1, L, lambda_factor, method,
                                           conservative_level, pb_min, loop_type)
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            Kp, Ti, Td = self._tune_sopdt(K_abs, T1, T2, L, lambda_factor,
                                           conservative_level, pb_min)
        elif model_type == ModelType.FOPI:
            Kp, Ti, Td = self._tune_integrator(K_abs, T1, lambda_factor,
                                                conservative_level, pb_min)
        elif model_type in [ModelType.HAMMERSTEIN, ModelType.DEADBAND_FOPDT, ModelType.SATURATION_FOPDT]:
            Kp, Ti, Td = self._tune_nonlinear(K_abs, T1, L, lambda_factor, method,
                                               conservative_level, pb_min, model_type)
        else:
            fallback = self._pid_constraints
            Kp, Ti, Td = fallback['fallback_kp'], fallback['fallback_ti'], fallback['fallback_td']
        
        Kp = Kp * K_sign
        Kp, Ti, Td = self._apply_constraints(Kp, Ti, Td, K_sign)
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        return {
            'Kp': round(float(Kp), 2),
            'Ki': round(float(Ki), 2),
            'Kd': round(float(Kd), 2)
        }
    
    def _calculate_conservative_level(self, quality_info: Optional[DataQualityInfo],
                                       response_mode: str = 'balanced') -> Tuple[float, float]:
        """根据数据质量和响应模式计算自适应保守等级"""
        MODE_PARAMS = {
            'fast': {
                'level_range': (0.8, 1.5), 'pb_range': (8, 25),
                'default_level': 1.0, 'default_pb': 15,
                'r2_multipliers': {0.95: 0.3, 0.9: 0.4, 0.85: 0.5, 0.8: 0.65}
            },
            'balanced': {
                'level_range': (1.0, 2.0), 'pb_range': (12, 35),
                'default_level': 1.5, 'default_pb': 25,
                'r2_multipliers': {0.95: 0.35, 0.9: 0.5, 0.85: 0.65, 0.8: 0.8}
            },
            'conservative': {
                'level_range': (1.5, 3.0), 'pb_range': (25, 50),
                'default_level': 2.0, 'default_pb': 35,
                'r2_multipliers': {0.95: 0.5, 0.9: 0.65, 0.85: 0.75, 0.8: 0.85}
            }
        }
        
        params = MODE_PARAMS.get(response_mode, MODE_PARAMS['balanced'])
        level_min, level_max = params['level_range']
        pb_min_range, pb_max_range = params['pb_range']
        
        if quality_info is None:
            return params['default_level'], params['default_pb']
        
        q_score = quality_info.quality_score
        osc_ratio = quality_info.oscillation_ratio
        r2 = quality_info.r_squared
        consistency = quality_info.consistency_score
        
        quality_factor = 1.0 - q_score
        osc_factor = osc_ratio * 0.5
        r2_factor = max(0, 1.0 - r2)
        
        if r2 > 0.85:
            consist_factor = max(0, 1.0 - consistency) * 0.3
        elif r2 > 0.7:
            consist_factor = max(0, 1.0 - consistency) * 0.6
        else:
            consist_factor = max(0, 1.0 - consistency)
        
        conservativeness = (0.25 * quality_factor + 0.20 * osc_factor +
                           0.30 * r2_factor + 0.25 * consist_factor)
        
        r2_multipliers = params['r2_multipliers']
        if r2 > 0.95:
            conservativeness *= r2_multipliers[0.95]
        elif r2 > 0.9:
            conservativeness *= r2_multipliers[0.9]
        elif r2 > 0.85:
            conservativeness *= r2_multipliers[0.85]
        elif r2 > 0.8:
            conservativeness *= r2_multipliers[0.8]
        
        valve_cfg = self._pid_constraints.get('valve_compensation', {})
        osc_th_high = valve_cfg.get('osc_threshold_high', 0.5)
        osc_th_med = valve_cfg.get('osc_threshold_med', 0.6)
        r2_th = valve_cfg.get('r2_threshold', 0.85)
        
        valve_compensation = 1.0
        if osc_ratio > osc_th_high and r2 < r2_th:
            valve_compensation = 1.3 + (osc_ratio - osc_th_high) * 0.6
        elif osc_ratio > osc_th_med:
            valve_compensation = 1.2 + (osc_ratio - osc_th_med) * 0.5
        valve_compensation = min(valve_compensation, 1.4)
        
        conservative_level = level_min + conservativeness * (level_max - level_min) * valve_compensation
        pb_min = pb_min_range + conservativeness * (pb_max_range - pb_min_range) * valve_compensation
        
        def soft_clip(x, x_min, x_max):
            range_half = (x_max - x_min) / 2
            if x > x_max:
                overshoot = x - x_max
                return x_max + range_half * 0.1 * (1 - np.exp(-overshoot / range_half))
            elif x < x_min:
                undershoot = x_min - x
                return x_min - range_half * 0.1 * (1 - np.exp(-undershoot / range_half))
            return x
        
        conservative_level = soft_clip(conservative_level, level_min, level_max)
        pb_min = soft_clip(pb_min, pb_min_range, pb_max_range)
        return conservative_level, pb_min
    
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float,
                               quality_info: Optional[DataQualityInfo] = None,
                               response_mode: str = 'balanced',
                               loop_type: str = None) -> Dict[str, float]:
        """从FusionResult计算PID参数"""
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor,
            quality_info=quality_info,
            response_mode=response_mode,
            loop_type=loop_type
        )
