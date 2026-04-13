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

from .data_classes import DataQualityInfo
from .tuning_methods import TuningMethodsMixin
from ..oscillation.oscillation_analysis import OscillationAnalysisMixin
from ..verification.closed_loop_sim import ClosedLoopSimMixin

EPSILON = Config.EPSILON


class PIDCalculator(TuningMethodsMixin, OscillationAnalysisMixin, 
                    ClosedLoopSimMixin):
    """
    PID参数计算器
    
    继承自:
    - TuningMethodsMixin: 整定公式 (_tune_fo, _tune_fopdt, 等)
    - OscillationAnalysisMixin: 振荡分析 (analyze_oscillation, 等)
    - ClosedLoopSimMixin: 闭环仿真 (simulate_closed_loop, 等)
    """
    
    def __init__(self):
        self._epsilon = EPSILON
        self._pid_constraints = Config.PID_CONSTRAINTS
    
    def _get_fallback_params(self, Ti_override: float = None, loop_type: str = 'flow', tuning_constraints: dict = None) -> Tuple[float, float, float]:
        """获取回退PID参数"""
        tuning_constraints = tuning_constraints or {}
        from core.algorithm.model_type.tuning.strategies.loop_type_strategies import get_loop_strategy
        strategy = get_loop_strategy(loop_type)
        fallback_cfg = strategy.get_fallback_params()
        
        pb = fallback_cfg.get('pb_base', 200.0)
        Kp = 100.0 / max(pb, 1.0)
        Ti = Ti_override if Ti_override is not None else fallback_cfg.get('fallback_ti', 20.0)
        Td = 0.0
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
                  loop_type: str = None,
                  tuning_constraints: dict = None) -> Dict[str, float]:
        """根据模型类型和整定方法计算PID参数"""
        tuning_constraints = tuning_constraints or {}
        K_sign = 1 if K >= 0 else -1
        K_abs = max(abs(K), self._epsilon)
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T2 = max(T2, 0.0)
        
        conservative_level, pb_min = self._calculate_conservative_level(quality_info, response_mode, loop_type, tuning_constraints)
        
        # [NEW] 回路类型预设同步 (v3.11)
        if loop_type:
            preset = tuning_constraints
            safety = preset.get('safety_factor', 1.0)
            if safety != 1.0:
                conservative_level *= safety
        
        # [NEW] 符号冲突检测 (v3.11) - 移动到计算之前，确保对所有模型生效
        if quality_info and abs(quality_info.correlation) > 0.3:
            if (quality_info.correlation > 0.3 and K_sign < 0) or \
               (quality_info.correlation < -0.3 and K_sign > 0):
                self._log_robust(f"   ⚠️ 符号冲突检测: correlation={quality_info.correlation:.2f}, K_sign={K_sign}")
                penalty = Config.ROBUST_TUNING.get('sign_mismatch_penalty', 3.0)
                conservative_level *= penalty
                pb_min = max(pb_min, 60.0) # 符号冲突时强行拉高 PB 下限
                self._log_robust(f"   → 触发极端保守模式: pb_min={pb_min}, level={conservative_level:.1f}")

        if model_type == ModelType.FO:
            Kp, Ti, Td = self._tune_fo(K_abs, T1, lambda_factor, method,
                                        conservative_level, pb_min, loop_type, tuning_constraints)
        elif model_type == ModelType.FOPDT:
            Kp, Ti, Td = self._tune_fopdt(K_abs, T1, L, lambda_factor, method,
                                           conservative_level, pb_min, loop_type, tuning_constraints)
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            Kp, Ti, Td = self._tune_sopdt(K_abs, T1, T2, L, lambda_factor,
                                           conservative_level, pb_min, loop_type, tuning_constraints)
        elif model_type == ModelType.FOPI:
            Kp, Ti, Td = self._tune_integrator(K_abs, T1, lambda_factor,
                                                conservative_level, pb_min, loop_type, tuning_constraints)
        elif model_type in [ModelType.HAMMERSTEIN, ModelType.DEADBAND_FOPDT, ModelType.SATURATION_FOPDT]:
            Kp, Ti, Td = self._tune_nonlinear(K_abs, T1, L, lambda_factor, method,
                                               conservative_level, pb_min, model_type, loop_type, tuning_constraints)
        else:
            Kp, Ti, Td = self._get_fallback_params(loop_type=loop_type, tuning_constraints=tuning_constraints)
        
        Kp = Kp * K_sign
        Kp, Ti, Td = self._apply_constraints(Kp, Ti, Td, K_sign, loop_type, tuning_constraints)
        
        # [FIX] 极端积分下限保护（防止微观假象导致真实DCS崩溃）
        # level 回路积分特性强，Ti 下限设高；temperature 回路可能有快速场景，下限适中
        if loop_type == 'level':
            Ti = max(Ti, 20.0)
        elif loop_type == 'temperature':
            Ti = max(Ti, 5.0)
            
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        pb = 100.0 / abs(Kp) if abs(Kp) > self._epsilon else 100.0
        
        return {
            'Kp': round(float(Kp), 4),
            'Ki': round(float(Ki), 4),
            'Kd': round(float(Kd), 4),
            'Ti': round(float(Ti), 4),
            'Td': round(float(Td), 4),
            'pb': round(float(pb), 2)
        }
    
    def _calculate_conservative_level(self, quality_info: Optional[DataQualityInfo],
                                       response_mode: str = 'balanced',
                                       loop_type: str = None,
                                       tuning_constraints: dict = None) -> Tuple[float, float]:
        """根据数据质量和响应模式计算自适应保守等级"""
        tuning_constraints = tuning_constraints or {}
        MODE_PARAMS = {
            'fast': {
                'level_range': (0.8, 1.5), 'pb_range': (8, 25),
                'default_level': 1.0, 'default_pb': 15,
                # [FIX] BUG-3: 补充 R2 < 0.8 的乘数
                'r2_multipliers': {0.95: 0.3, 0.9: 0.4, 0.85: 0.5, 0.8: 0.65, 0.7: 0.75, 0.6: 0.85}
            },
            'balanced': {
                'level_range': (1.0, 2.0), 'pb_range': (12, 35),
                'default_level': 1.5, 'default_pb': 25,
                'r2_multipliers': {0.95: 0.35, 0.9: 0.5, 0.85: 0.65, 0.8: 0.8, 0.7: 0.85, 0.6: 0.9}
            },
            'conservative': {
                'level_range': (1.5, 3.0), 'pb_range': (25, 50),
                'default_level': 2.0, 'default_pb': 35,
                'r2_multipliers': {0.95: 0.5, 0.9: 0.65, 0.85: 0.75, 0.8: 0.85, 0.7: 0.9, 0.6: 0.95}
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
        correlation = getattr(quality_info, 'correlation', 0.0)
        
        # [NEW] 指数级 R² 惩罚 (v3.11)
        # 当 R² 低于 0.6 时，说明模型不可信，大幅增加保守度
        r2_robust_th = Config.ROBUST_TUNING.get('r2_robust_threshold', 0.6)
        r2_penalty = 0.0
        if r2 < r2_robust_th:
            # 这种惩罚会在 R²=0.4 时达到 ~8.8，R²=0.2 时更夸张，迫使进入极端保守模式
            r2_penalty = 2.0 * (np.exp(2.5 * (r2_robust_th - r2)) - 1.0)

        
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
        
        # 应用指数惩罚
        conservativeness += r2_penalty
        
        r2_multipliers = params['r2_multipliers']
        if r2 > 0.95:
            conservativeness *= r2_multipliers[0.95]
        elif r2 > 0.9:
            conservativeness *= r2_multipliers[0.9]
        elif r2 > 0.85:
            conservativeness *= r2_multipliers[0.85]
        elif r2 > 0.8:
            conservativeness *= r2_multipliers[0.8]
        elif r2 > 0.7:
            conservativeness *= r2_multipliers[0.7]
        elif r2 > 0.6:
            conservativeness *= r2_multipliers[0.6]
        
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
        
        # [NEW] 回路特定最小 PB 保护 (v3.11)
        # 防止由于模型严重低估增益导致的 PB 膨胀到不合理的低值
        if r2 < 0.7:
            robust_cfg = Config.ROBUST_TUNING
            if loop_type in ['flow', 'pressure']:
                pb_min = max(pb_min, robust_cfg.get('min_pb_flow', 50.0))
            elif loop_type in ['temperature', 'level']:
                pb_min = max(pb_min, robust_cfg.get('min_pb_temp', 100.0))
                
        # [FIX] 从 tuning_constraints (来源于 loop_presets) 应用回路硬性下限保护
        preset_pb_min = tuning_constraints.get('pb_min', 0.0)
        if preset_pb_min > 0:
            pb_min = max(pb_min, preset_pb_min)
            
        return conservative_level, pb_min
    
    def _log_robust(self, msg: str):
        """记录鲁棒整定相关的日志"""
        if hasattr(self, 'log'):
            self.log(msg)
        else:
            print(msg)
            
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float,
                               quality_info: Optional[DataQualityInfo] = None,
                               response_mode: str = 'balanced',
                               loop_type: str = None,
                               tuning_constraints: dict = None) -> Dict[str, float]:
        """从FusionResult计算PID参数"""
        
        # ⭐ 核心修复：自优化网格搜索时 (stage_05b) 不会传入 quality_info，
        # 这导致它回退到了 default_pb (如25%), 完全忽略了基于低R²和回路类型的鲁棒保护(pb_min=100)！
        # 在这里如果未传参，则必须从 fusion 倒推伪造一个基础的 quality_info 提供保护。
        if quality_info is None:
            quality_info = DataQualityInfo(
                quality_score=0.5,
                oscillation_ratio=0.0,
                r_squared=getattr(fusion, 'global_r2', 0.5),
                is_noisy=False,
                consistency_score=getattr(fusion, 'consistency_score', 0.5),
                correlation=0.0,
                controller_sign=1
            )
            
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor,
            quality_info=quality_info,
            response_mode=response_mode,
            loop_type=loop_type,
            tuning_constraints=tuning_constraints
        )
