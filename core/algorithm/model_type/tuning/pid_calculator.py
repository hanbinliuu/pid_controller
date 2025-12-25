"""PID参数计算模块 (PID Calculator Module)
=======================================

本模块基于辨识的模型参数计算最优PID整定参数。

模块结构
--------
- data_classes.py: 数据类定义 (ClosedLoopMetrics, DataQualityInfo)
- tuning_methods.py: 整定公式 (TuningMethodsMixin)
- oscillation_analysis.py: 振荡分析 (OscillationAnalysisMixin)
- closed_loop_sim.py: 闭环仿真 (ClosedLoopSimMixin)
- model_rating.py: 模型评分 (ModelRatingMixin)

核心功能
--------
1. **多种整定方法**: Lambda/IMC法、Cohen-Coon法、Ziegler-Nichols临界法
2. **自适应保守调整**: 根据数据质量自动调整保守程度
3. **振荡分析整定**: 对高振荡数据使用临界法整定
4. **闭环稳定性验证**: 仿真验证PID参数的闭环性能
"""

import numpy as np
from typing import Dict, Tuple, Optional

from ..config import Config, ModelType
from ..data_models import FusionResult

from .data_classes import ClosedLoopMetrics, DataQualityInfo
from .tuning_methods import TuningMethodsMixin
from .oscillation_analysis import OscillationAnalysisMixin
from .closed_loop_sim import ClosedLoopSimMixin
from .model_rating import ModelRatingMixin


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
        """获取回退PID参数（从配置读取）"""
        cfg = self._pid_constraints
        Kp = cfg.get('fallback_kp', 1.0)
        Ti = Ti_override if Ti_override is not None else cfg.get('fallback_ti', 20.0)
        Td = cfg.get('fallback_td', 0.0)
        return Kp, Ti, Td
    
    def _get_max_kp(self, pb_min: float) -> float:
        """根据pb_min计算Kp上限（从配置读取系数）"""
        kp_max_from_pb = self._pid_constraints.get('kp_max_from_pb', 100.0)
        return kp_max_from_pb / pb_min
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float,
                  method: str = 'lambda',
                  quality_info: Optional[DataQualityInfo] = None,
                  response_mode: str = 'balanced') -> Dict[str, float]:
        """
        根据模型类型和整定方法计算PID参数
        
        Args:
            K: 增益（可为负，表示反向作用系统）
            T1: 时间常数1
            T2: 时间常数2（二阶模型）
            L: 滞后时间
            model_type: 模型类型 (FOPDT, FO, SOPDT, SO, FOPI)
            lambda_factor: Lambda/IMC 整定系数（闭环时间常数 = T1 * lambda_factor）
            method: 整定方法
                - 'lambda': Lambda/IMC 法（默认，适用于所有模型）
                - 'cohen_coon': Cohen-Coon 法（仅 FOPDT）
                - 'imc_aggressive': IMC 激进模式（更快响应）
            quality_info: 数据质量信息，用于自适应保守调整
            response_mode: 响应模式
                - 'fast': 快速响应（允许10-20%超调，调节时间短）
                - 'balanced': 平衡模式（默认，小超调，较快响应）
                - 'conservative': 保守模式（无超调，响应较慢）
        
        Returns:
            PID参数字典 {Kp, Ki, Kd}，Kp符号与K一致
        """
        # 保留K的符号信息（反向作用系统K为负）
        K_sign = 1 if K >= 0 else -1
        K_abs = max(abs(K), self._epsilon)
        
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T2 = max(T2, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        
        # 计算自适应保守等级（考虑响应模式）
        conservative_level, pb_min = self._calculate_conservative_level(quality_info, response_mode)
        
        # 根据模型类型和方法选择整定公式
        if model_type == ModelType.FO:
            # ========== 一阶无滞后 (FO) ==========
            Kp, Ti, Td = self._tune_fo(K_abs, T1, lambda_factor, method,
                                        conservative_level, pb_min)
            
        elif model_type == ModelType.FOPDT:
            # ========== 一阶加纯滞后 (FOPDT) ==========
            Kp, Ti, Td = self._tune_fopdt(K_abs, T1, L, lambda_factor, method,
                                           conservative_level, pb_min)
            
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            # ========== 二阶系统 (SO/SOPDT) ==========
            Kp, Ti, Td = self._tune_sopdt(K_abs, T1, T2, L, lambda_factor,
                                           conservative_level, pb_min)
            
        elif model_type == ModelType.FOPI:
            # ========== 积分过程 (FOPI) ==========
            Kp, Ti, Td = self._tune_integrator(K_abs, T1, lambda_factor,
                                                conservative_level, pb_min)
        
        elif model_type in [ModelType.HAMMERSTEIN, ModelType.DEADBAND_FOPDT, ModelType.SATURATION_FOPDT]:
            # ========== 非线性模型 ==========
            # 使用等效线性化参数，按FOPDT整定，并增加保守度
            Kp, Ti, Td = self._tune_nonlinear(K_abs, T1, L, lambda_factor, method,
                                               conservative_level, pb_min, model_type)
            
        else:
            # 默认保守参数（从配置读取）
            fallback = self._pid_constraints
            Kp, Ti, Td = fallback['fallback_kp'], fallback['fallback_ti'], fallback['fallback_td']
        
        # 应用K的符号到Kp（反向作用系统Kp为负）
        Kp = Kp * K_sign
        
        # 参数合理性约束
        Kp, Ti, Td = self._apply_constraints(Kp, Ti, Td, K_sign)
        
        # 转换为 Ki, Kd
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        return {
            'Kp': round(float(Kp), 2),
            'Ki': round(float(Ki), 2),
            'Kd': round(float(Kd), 2)
        }
    
    def _calculate_conservative_level(self, quality_info: Optional[DataQualityInfo],
                                       response_mode: str = 'balanced') -> Tuple[float, float]:
        """
        根据数据质量和响应模式计算自适应保守等级
        
        Args:
            quality_info: 数据质量信息
            response_mode: 响应模式
                - 'fast': 快速响应（允许10-20%超调）
                - 'balanced': 平衡模式（默认）
                - 'conservative': 保守模式（无超调）
        
        Returns:
            (conservative_level, pb_min)
            - conservative_level: 保守因子，越大越保守
            - pb_min: pb最小值
        """
        # 响应模式基准参数（优化：收窄范围，避免过于保守）
        # fast: 更小的保守因子，更低的pb_min，响应更快但可能有超调
        # balanced: 适中参数
        # conservative: 更大的保守因子，响应慢但稳定
        MODE_PARAMS = {
            'fast': {
                'level_range': (0.8, 1.5),    # 保守因子范围（收窄上限）
                'pb_range': (8, 25),          # pb_min范围（收窄上限）
                'default_level': 1.0,
                'default_pb': 15,
                'r2_multipliers': {0.95: 0.3, 0.9: 0.4, 0.85: 0.5, 0.8: 0.65}
            },
            'balanced': {
                'level_range': (1.0, 2.0),    # 收窄：原(1.2, 2.5)
                'pb_range': (12, 35),         # 收窄：原(15, 45)
                'default_level': 1.5,
                'default_pb': 25,
                'r2_multipliers': {0.95: 0.35, 0.9: 0.5, 0.85: 0.65, 0.8: 0.8}
            },
            'conservative': {
                'level_range': (1.5, 3.0),    # 收窄：原(2.0, 4.0)
                'pb_range': (25, 50),         # 收窄：原(30, 70)
                'default_level': 2.0,
                'default_pb': 35,
                'r2_multipliers': {0.95: 0.5, 0.9: 0.65, 0.85: 0.75, 0.8: 0.85}
            }
        }
        
        params = MODE_PARAMS.get(response_mode, MODE_PARAMS['balanced'])
        level_min, level_max = params['level_range']
        pb_min_range, pb_max_range = params['pb_range']
        
        if quality_info is None:
            return params['default_level'], params['default_pb']
        
        # 计算综合质量得分
        q_score = quality_info.quality_score
        osc_ratio = quality_info.oscillation_ratio
        r2 = quality_info.r_squared
        consistency = quality_info.consistency_score
        
        # 质量因子：越差越保守（降低权重）
        quality_factor = 1.0 - q_score  # 0~1
        
        # 振荡因子：振荡越大越保守（大幅降低权重）
        osc_factor = osc_ratio * 0.5  # 进一步降低振荡的惩罚
        
        # 拟合因子：R²越低越保守
        r2_factor = max(0, 1.0 - r2)  # 0~1
        
        # 一致性因子：一致性越低越保守
        if r2 > 0.85:
            consist_factor = max(0, 1.0 - consistency) * 0.3
        elif r2 > 0.7:
            consist_factor = max(0, 1.0 - consistency) * 0.6
        else:
            consist_factor = max(0, 1.0 - consistency)
        
        # 综合保守度：加权平均（优化：降低R²权重，更均衡）
        conservativeness = (
            0.25 * quality_factor +
            0.20 * osc_factor +
            0.30 * r2_factor +      # 降低：原0.45，避免低R²时过于保守
            0.25 * consist_factor
        )
        
        # 根据R²和响应模式调整保守度
        r2_multipliers = params['r2_multipliers']
        if r2 > 0.95:
            conservativeness *= r2_multipliers[0.95]
        elif r2 > 0.9:
            conservativeness *= r2_multipliers[0.9]
        elif r2 > 0.85:
            conservativeness *= r2_multipliers[0.85]
        elif r2 > 0.8:
            conservativeness *= r2_multipliers[0.8]
        
        # 阀门补偿：高振荡+低R²时自动增加保守度（可能存在阀门死区/黏连）
        valve_cfg = self._pid_constraints.get('valve_compensation', {})
        osc_th_high = valve_cfg.get('osc_threshold_high', 0.5)
        osc_th_med = valve_cfg.get('osc_threshold_med', 0.6)
        r2_th = valve_cfg.get('r2_threshold', 0.85)
        factor_high_base = valve_cfg.get('factor_high_base', 1.3)
        factor_high_slope = valve_cfg.get('factor_high_slope', 0.6)
        factor_med_base = valve_cfg.get('factor_med_base', 1.2)
        factor_med_slope = valve_cfg.get('factor_med_slope', 0.5)
        
        valve_compensation = 1.0
        if osc_ratio > osc_th_high and r2 < r2_th:
            valve_compensation = factor_high_base + (osc_ratio - osc_th_high) * factor_high_slope
        elif osc_ratio > osc_th_med:
            valve_compensation = factor_med_base + (osc_ratio - osc_th_med) * factor_med_slope
        
        # 限制 valve_compensation 避免过度放大（优化：加上限）
        valve_compensation = min(valve_compensation, 1.4)
        
        # 映射到保守等级和pb_min（应用阀门补偿）
        conservative_level = level_min + conservativeness * (level_max - level_min) * valve_compensation
        pb_min = pb_min_range + conservativeness * (pb_max_range - pb_min_range) * valve_compensation
        
        # 使用 soft clipping 替代硬边界，避免撞边界（优化）
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
    
    # 整定方法已移至 TuningMethodsMixin:
    # _tune_fo, _tune_fopdt, _tune_sopdt, _tune_integrator, _tune_nonlinear, _apply_constraints
    
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float,
                               quality_info: Optional[DataQualityInfo] = None,
                               response_mode: str = 'balanced') -> Dict[str, float]:
        """
        从FusionResult计算PID参数
        
        Args:
            fusion: 融合结果
            lambda_factor: Lambda系数
            quality_info: 数据质量信息，用于自适应保守调整
            response_mode: 响应模式 ('fast', 'balanced', 'conservative')
        """
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor,
            quality_info=quality_info,
            response_mode=response_mode
        )
    
    # 以下方法已移至各 Mixin 类:
    # - OscillationAnalysisMixin: analyze_oscillation, calculate_from_oscillation, 等
    # - ModelRatingMixin: calculate_model_rating
    # - ClosedLoopSimMixin: simulate_closed_loop, verify_pid_stability, 等

