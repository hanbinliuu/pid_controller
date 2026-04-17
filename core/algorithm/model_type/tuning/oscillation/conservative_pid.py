"""
保守PID参数计算模块 (Conservative PID Module)
=============================================

本模块封装振荡整定时的保守PID参数计算逻辑。

核心功能
--------
1. **基础pb计算**: 基于过程增益和临界参数
2. **质量因子调整**: 数据质量、非线性、阀门问题
3. **极端场景调整**: 高增益、大滞后、极端振荡
4. **振荡比自适应**: 渐进式保守策略
5. **Ti/Td计算**: 自适应积分和微分时间
"""

import numpy as np
from typing import Dict, Any, Optional, Tuple

from ...config import Config
from ...logger import LoggerMixin
from ..strategies.loop_type_strategies import get_loop_strategy


class ConservativePIDCalculator(LoggerMixin):
    """保守PID参数计算器"""
    
    def __init__(self, verbose: bool = False, loop_type: str = "", loop_name: str = ""):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)

    def calculate(self, Pu: float, Ku: float, 
                  K_approx: float = 1.0, reason: str = 'generic',
                  oscillation_ratio: float = 0.0, data_quality: float = 0.5,
                  nonlinearity: float = 0.0, valve_issues: Dict = None,
                  confidence: float = 0.5, tuning_constraints: dict = None,
                  has_current_pid: bool = False, current_kp: float = 0.0,
                  current_ti: float = 0.0) -> Dict[str, Any]:
        """计算保守PID参数"""
        tuning_constraints = tuning_constraints or {}
        if valve_issues is None:
            valve_issues = {}

        pb_base, pb_from_K, pb_from_Ku, slow_factor = self._calculate_base_pb(Ku, K_approx, Pu)
        pb_base = self._apply_quality_factors(pb_base, reason, data_quality, nonlinearity, valve_issues)
        pb_base, delay_ratio = self._apply_extreme_factors(pb_base, K_approx, Pu, oscillation_ratio)
        pb_base, safety_factor = self._apply_oscillation_adjustment(pb_base, oscillation_ratio, tuning_constraints)
        # 统一风险因子压缩：避免多来源保守因子在同一轮中过度连乘
        pb_base = self._normalize_risk_multiplier(
            pb_base=pb_base,
            pb_from_k=pb_from_K,
            pb_from_ku=pb_from_Ku,
            confidence=confidence,
            oscillation_ratio=oscillation_ratio,
        )
        pb_safe = self._apply_pb_bounds(
            pb_base, K_approx, confidence, reason, pb_from_K, pb_from_Ku, Pu, Ku, slow_factor,
            delay_ratio, tuning_constraints, has_current_pid=has_current_pid, current_kp=current_kp
        )
        Ti, Td, ti_multiplier, td_multiplier = self._calculate_ti_td(
            Pu, oscillation_ratio, K_approx, tuning_constraints,
            has_current_pid=has_current_pid, current_ti=current_ti
        )
        
        return self._build_result(pb_safe, Ti, Td, Pu, Ku, reason)

    def _calculate_base_pb(self, Ku: float, K_approx: float, Pu: float) -> Tuple[float, float, float, float]:
        """计算基础 pb 值"""
        osc_config = Config.OSCILLATION_TUNING
        pb_from_k_factor = osc_config.get('pb_from_k_factor', 1.0)
        kp_from_ku_factor = osc_config.get('kp_from_ku_factor', 0.45)
        
        # [NEW] 针对流量和压力回路，平衡符合度与稳定性 (v3.10 Final Push)
        # [NEW] 针对流量和压力回路，平衡符合度与稳定性 (v3.10 Final Push)
        # if self._loop_type in ['flow', 'pressure']:
        #     pb_from_k_factor *= 0.85   # 决战 150% 目标 (0.72 -> 0.85 恢复稳定性)
        #     kp_from_ku_factor = 0.75   # 保持响应速度
            
        pb_from_K = 100.0 * K_approx * pb_from_k_factor if K_approx > 0.01 else 80.0
        
        if Ku > 0.1:
            Kp_from_Ku = kp_from_ku_factor * Ku
            pb_from_Ku = 100.0 / max(Kp_from_Ku, 0.1)
        else:
            pb_from_Ku = 100.0
        
        pu_thresholds = osc_config.get('slow_system_pu_thresholds', [30.0, 15.0])
        slow_factors = osc_config.get('slow_system_factors', [1.15, 1.05, 1.0])
        slow_factor = slow_factors[-1]
        for i, threshold in enumerate(pu_thresholds):
            if Pu > threshold:
                slow_factor = slow_factors[i]
                break
        
        pb_base = max(pb_from_K, pb_from_Ku) * slow_factor
        return pb_base, pb_from_K, pb_from_Ku, slow_factor
    
    def _apply_quality_factors(self, pb_base: float, reason: str, data_quality: float, 
                               nonlinearity: float, valve_issues: Dict) -> float:
        """应用数据质量、非线性、阀门问题等因子"""
        osc_config = Config.OSCILLATION_TUNING
        
        if reason == 'high_gain':
            pb_base *= osc_config.get('high_gain_extra_factor', 1.1)
        
        quality_threshold = osc_config.get('quality_adjustment_threshold', 0.5)
        if data_quality < quality_threshold:
            quality_factor = 1.0 + (quality_threshold - data_quality) * osc_config.get('quality_adjustment_factor', 0.6)
            pb_base *= quality_factor
            self.log(f"   📊 数据质量调整: 因子=×{quality_factor:.2f}")
        
        nonlin_threshold = osc_config.get('nonlinearity_threshold', 0.5)
        if nonlinearity > nonlin_threshold:
            nonlin_factor = 1.0 + (nonlinearity - nonlin_threshold) * osc_config.get('nonlinearity_factor', 0.4)
            pb_base *= nonlin_factor
            self.log(f"   📊 非线性调整: 因子=×{nonlin_factor:.2f}")
        
        valve_factor = 1.0
        if valve_issues.get('has_deadband', False):
            valve_factor *= osc_config.get('valve_deadband_factor', 1.15)
        if valve_issues.get('has_stiction', False):
            valve_factor *= osc_config.get('valve_stiction_factor', 1.2)
        if valve_issues.get('has_saturation', False):
            valve_factor *= osc_config.get('valve_saturation_factor', 1.1)
        pb_base *= valve_factor
        return pb_base

    def _apply_extreme_factors(self, pb_base: float, K_approx: float, 
                               Pu: float, oscillation_ratio: float) -> Tuple[float, float]:
        """应用极端场景因子 (恢复稳定性)"""
        # [FIX] 仅针对未知回路应用全局因子，避免与策略类叠加 (v3.7)
        if self._loop_type in ['default', 'unknown', '']:
            if K_approx > 4.0:
                if K_approx > 6.0:
                    # 恢复稳定性: 提高因子
                    extreme_gain_factor = min(1.0 + (K_approx - 4.0) * 0.25, 2.5)
                else:
                    extreme_gain_factor = min(1.0 + (K_approx - 4.0) * 0.15, 1.8)
                pb_base *= extreme_gain_factor
                self.log(f"   ⚠️ 极高增益场景(K={K_approx:.1f}): 保守因子 ×{extreme_gain_factor:.2f}")
        
        pb_base = self._strategy.adjust_pb_for_extreme(pb_base, K_approx, Pu, log_func=self.log)
        
        estimated_L = Pu / 4.0
        T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
        delay_ratio = estimated_L / max(T1_approx, 1.0)
        
        # 滞后因子：只在真正大滞后时生效 [阈值从0.4提高到0.6，避免与其他因子叠加]
        if delay_ratio > 0.8:
            delay_factor = 1.8  # 极大滞后 [降低：2.3→1.8]
        elif delay_ratio > 0.6:
            delay_factor = 1.2 + (delay_ratio - 0.6) * 3.0  # [降低起始：1.6→1.2]
        else:
            delay_factor = 1.0  # 中等滞后不再额外放大 [阈值从0.4提高到0.6]
        
        if delay_factor > 1.0:
            pb_base *= delay_factor
            self.log(f"   ⚠️ 滞后比(L/T1≈{delay_ratio:.2f}): 保守 ×{delay_factor:.2f}")
        
        # 恢复稳定性: 提高振荡因子
        if oscillation_ratio > 0.85:
            extreme_osc_factor = min(1.15 + (oscillation_ratio - 0.85) * 2.0, 1.5)
            pb_base *= extreme_osc_factor
            self.log(f"   ⚠️ 极端振荡场景: 保守因子 ×{extreme_osc_factor:.2f}")
        
        return pb_base, delay_ratio
    
    def _apply_oscillation_adjustment(self, pb_base: float, oscillation_ratio: float,
                                      tuning_constraints: dict) -> Tuple[float, float]:
        """应用振荡比自适应调整"""
        osc_config = Config.OSCILLATION_TUNING
        pb_gradient = osc_config.get('pb_gradient', 2.0)
        pb_osc_start = osc_config.get('pb_oscillation_start', 0.4)
        safety_base = osc_config.get('safety_factor_base', 1.4)
        safety_thresholds = osc_config.get('safety_factor_thresholds', [0.5, 0.7, 0.85])
        safety_slopes = osc_config.get('safety_factor_slopes', [0.5, 1.0, 2.0])
        
        if oscillation_ratio < safety_thresholds[0]:
            safety_factor = safety_base
        elif oscillation_ratio < safety_thresholds[1]:
            safety_factor = safety_base + (oscillation_ratio - safety_thresholds[0]) * safety_slopes[0]
        elif oscillation_ratio < safety_thresholds[2]:
            prev_value = safety_base + (safety_thresholds[1] - safety_thresholds[0]) * safety_slopes[0]
            safety_factor = prev_value + (oscillation_ratio - safety_thresholds[1]) * safety_slopes[1]
        else:
            prev_value = safety_base + (safety_thresholds[1] - safety_thresholds[0]) * safety_slopes[0]
            prev_value += (safety_thresholds[2] - safety_thresholds[1]) * safety_slopes[1]
            safety_factor = prev_value + (oscillation_ratio - safety_thresholds[2]) * safety_slopes[2]

        # [NEW] 叠加 Loop Preset 的 safety_factor (例如 Flow=1.1, Pressure=1.1)
        preset = tuning_constraints
        loop_safety_factor = preset.get('safety_factor', 1.05)
        safety_factor *= loop_safety_factor
        
        # [NEW] 回路类型自适应梯度：流量和压力回路对振荡更宽容，适度减缓 PB 增加速度(v3.10)
        loop_gradient = pb_gradient
        if self._loop_type in ['flow', 'pressure']:
            loop_gradient = pb_gradient * 0.7   # 梯度压制 (0.45 -> 0.7 增加阻尼)
            # safety_factor *= 0.95               # 安全系数终极减免 (0.95 保持)
        
        total_multiplier = safety_factor
        
        if oscillation_ratio > pb_osc_start:
            effective_osc = oscillation_ratio - pb_osc_start
            osc_multiplier = 1.0 + np.sqrt(effective_osc) * loop_gradient
            total_multiplier *= osc_multiplier
            max_mult = osc_config.get('max_multiplier_high_osc', 3.0) if oscillation_ratio > safety_thresholds[2] else osc_config.get('max_multiplier_normal', 2.5)
            total_multiplier = min(total_multiplier, max_mult)
        
        pb_base *= total_multiplier
        return pb_base, safety_factor

    def _normalize_risk_multiplier(
        self,
        pb_base: float,
        pb_from_k: float,
        pb_from_ku: float,
        confidence: float,
        oscillation_ratio: float,
    ) -> float:
        """
        将“多模块连乘”得到的 PB 放大倍率压缩到单一 risk_factor 视角，降低重复放大的风险。
        """
        baseline = max(float(pb_from_k), float(pb_from_ku), 1.0)
        raw_mult = max(1.0, float(pb_base) / baseline)

        # 置信度越高，越不需要过度保守；置信度低则保守压缩更弱
        osc_cfg = Config.OSCILLATION_TUNING
        if confidence >= 0.75:
            damping = float(osc_cfg.get('risk_factor_damping_high_conf', 0.74))
        elif confidence >= 0.45:
            damping = float(osc_cfg.get('risk_factor_damping_mid_conf', 0.80))
        else:
            damping = float(osc_cfg.get('risk_factor_damping_low_conf', 0.88))

        # 极端振荡保留更多保守性，避免压缩过头
        if oscillation_ratio > 0.85:
            damping = min(0.92, damping + float(osc_cfg.get('risk_factor_extreme_osc_boost', 0.06)))

        cap_map = osc_cfg.get('risk_factor_cap_by_loop', {}) or {}
        mult_cap = float(cap_map.get(self._loop_type, cap_map.get('default', 3.2)))
        risk_factor = float(np.clip(np.exp(np.log(raw_mult) * damping), 1.0, mult_cap))

        pb_normalized = baseline * risk_factor
        if raw_mult > 1.05:
            self.log(
                f"   📉 风险因子归一: raw×{raw_mult:.2f} → risk×{risk_factor:.2f} "
                f"(基线PB={baseline:.1f}, damping={damping:.2f})"
            )
        return pb_normalized

    def _apply_pb_bounds(self, pb_base: float, K_approx: float, confidence: float, reason: str,
                        pb_from_K: float, pb_from_Ku: float, Pu: float, Ku: float, 
                        slow_factor: float, delay_ratio: float = 0.0, tuning_constraints: dict = None,
                        has_current_pid: bool = False, current_kp: float = 0.0) -> float:
        """应用 pb 边界限制"""
        tuning_constraints = tuning_constraints or {}
        osc_config = Config.OSCILLATION_TUNING
        pb_min_base = osc_config.get('pb_min', 80.0)
        pb_max_config = osc_config.get('pb_max', 400.0)  # 恢复到400
        
        # 根据置信度调整上限 (恢复一些余量)
        if confidence >= 0.8:
            pb_max = min(pb_max_config, 350.0)
        elif confidence >= 0.5:
            pb_max = min(pb_max_config, 450.0)
        else:
            pb_max = min(pb_max_config * 1.2, 550.0)
        
        # 按回路类型动态调整pb范围 (使用回路预设)
        preset = tuning_constraints
        pb_min_preset, pb_max_preset = preset.get('pb_min', 60.0), preset.get('pb_max', 350.0)
        pb_max = min(pb_max, pb_max_preset)
        
        # 注意：loop safety_factor 不再乘入 PB
        # 因为 _apply_oscillation_adjustment 已经应用了 safety_factor
        # 双重应用是导致 PB 中位数卡住 pb_max 的主因
        
        pb_k_factor = osc_config.get('pb_k_adjustment_factor', 0.3)
        if K_approx > 0.01:
            pb_min_dynamic = min(pb_min_base * (1.0 + pb_k_factor / K_approx), 350.0)  # 恢复
        else:
            pb_min_dynamic = 350.0
        pb_min = max(pb_min_preset, pb_min_dynamic)
        
        if reason == 'low_gain':
            pb_min = min(pb_min * osc_config.get('ku_k_extreme_pb_factor', 1.4), 450.0)  # 恢复
        
        pb_safe = np.clip(pb_base, pb_min, pb_max)

        # 分路径策略：
        # 1) 有 current_pid：使用相对变更限制（防激进/防过度变弱）
        # 2) 无 current_pid：使用绝对安全带（回路先验）
        if has_current_pid and abs(float(current_kp)) > 1e-9:
            current_pb = 100.0 / max(abs(float(current_kp)), 1e-6)
            rel_min = float(osc_config.get('current_pid_pb_min_ratio', 0.70))
            rel_max = float(osc_config.get('current_pid_pb_max_ratio', 3.50))
            pb_rel_low = current_pb * rel_min
            pb_rel_high = current_pb * rel_max
            pb_safe = float(np.clip(pb_safe, pb_rel_low, pb_rel_high))
        else:
            abs_min_map = osc_config.get('no_current_pid_pb_abs_min_by_loop', {}) or {}
            abs_max_map = osc_config.get('no_current_pid_pb_abs_max_by_loop', {}) or {}
            abs_pb_min = float(abs_min_map.get(self._loop_type, abs_min_map.get('default', 100.0)))
            abs_pb_max = float(abs_max_map.get(self._loop_type, abs_max_map.get('default', 600.0)))
            pb_safe = float(np.clip(pb_safe, max(pb_min, abs_pb_min), min(pb_max, abs_pb_max)))

        self.log(f"   📊 动态pb计算: K={K_approx:.3f}→pb={pb_from_K:.1f}, Ku={Ku:.3f}→pb={pb_from_Ku:.1f}, 最终pb={pb_safe:.1f}")
        return pb_safe
    
    def _calculate_ti_td(self, Pu: float, oscillation_ratio: float, K_approx: float,
                         tuning_constraints: dict,
                         has_current_pid: bool = False, current_ti: float = 0.0) -> Tuple[float, float, float, float]:
        """计算保守的 Ti 和 Td 值"""
        osc_config = Config.OSCILLATION_TUNING
        preset = tuning_constraints
        
        ti_min_base = osc_config.get('ti_min_base', 1.5)
        
        # 基础 Ti 应该严重依赖极限周期 Pu (参考 Tyreus-Luyben 为 Pu * 2.2)
        # 为保持框架的各路乘数 (如Level的ti_multiplier=2.8) 能够达到最终合理值
        # 取 Pu 的 0.8 倍作为基准: 这样 Level回路最终 Ti ≈ Pu * 0.8 * 2.8 ≈ 2.24 Pu (完美契合 TL 法)
        base_Ti = max(Pu * 0.8, 10.0, ti_min_base)
        
        ti_osc_start = osc_config.get('ti_osc_start', 0.6)
        ti_osc_factor = osc_config.get('ti_osc_factor', 0.5)
        ti_multiplier = 1.0 + np.sqrt(oscillation_ratio - ti_osc_start) * ti_osc_factor if oscillation_ratio > ti_osc_start else 1.0
        
        ti_multiplier = self._strategy.adjust_ti_multiplier(
            ti_multiplier, K_approx, Pu, oscillation_ratio, osc_config, log_func=self.log
        )
            
        # [FIX] 应用 Loop Preset 的 Ti Multiplier，但 Pu-based 模式下跳过
        # Pu-based base_Ti 已经包含慢系统补偿，不需要再叠加
        preset_ti_mult = preset.get('ti_multiplier', 1.0)
        if Pu <= 200.0 and preset_ti_mult != 1.0:
            ti_multiplier *= preset_ti_mult
            self.log(f"   📊 回路类型[{self._loop_type}] Ti调整: ×{preset_ti_mult:.2f}")
        elif Pu > 200.0 and preset_ti_mult != 1.0:
            self.log(f"   📊 慢系统(Pu={Pu:.0f}s): 跳过preset Ti乘数×{preset_ti_mult:.2f}")
        
        conservative_Ti = np.clip(base_Ti * ti_multiplier, *osc_config.get('ti_range', [1.5, 600.0]))

        if has_current_pid and float(current_ti) > 1e-9:
            rel_min = float(osc_config.get('current_pid_ti_min_ratio', 0.60))
            rel_max = float(osc_config.get('current_pid_ti_max_ratio', 2.80))
            conservative_Ti = float(np.clip(conservative_Ti, float(current_ti) * rel_min, float(current_ti) * rel_max))
        else:
            ti_min_map = osc_config.get('no_current_pid_ti_abs_min_by_loop', {}) or {}
            ti_max_map = osc_config.get('no_current_pid_ti_abs_max_by_loop', {}) or {}
            ti_abs_min = float(ti_min_map.get(self._loop_type, ti_min_map.get('default', 10.0)))
            ti_abs_max = float(ti_max_map.get(self._loop_type, ti_max_map.get('default', 600.0)))
            conservative_Ti = float(np.clip(conservative_Ti, ti_abs_min, ti_abs_max))
        
        conservative_Td = 0.0
        td_multiplier = 0.0
        
        # [NEW] 检查 Loop Preset 是否允许微分
        enable_derivative = preset.get('td_enable', osc_config.get('enable_adaptive_derivative', True))
        
        if not enable_derivative:
            # 强制禁用微分 (Flow/Level)
            conservative_Td = 0.0
            td_multiplier = 0.0
        else:
            # 允许微分 (Temp/Pressure)
            derivative_threshold = osc_config.get('derivative_oscillation_threshold', 0.5)
            
            # 如果预设指定了 td_ratio (如 Temp=0.25)，优先使用
            preset_td_ratio = preset.get('td_ratio', 0.0)
            
            if preset_td_ratio > 0:
                # 使用预设比例，并应用 td_max 上限
                td_max = preset.get('td_max', 50.0)
                conservative_Td = min(conservative_Ti * preset_td_ratio, td_max)
                td_multiplier = 1.0
            elif oscillation_ratio > derivative_threshold:
                # 自适应微分
                td_base_divisor = osc_config.get('td_base_divisor', 12.0)
                base_Td = Pu / td_base_divisor if Pu > 0 else 0.5
                td_mult_factor = osc_config.get('td_multiplier_factor', 1.5)
                effective_osc = max(0, oscillation_ratio - derivative_threshold)
                td_multiplier = 1.0 + np.sqrt(effective_osc) * td_mult_factor
                conservative_Td = np.clip(base_Td * td_multiplier, *osc_config.get('td_range', [0.3, 3.0]))
        
        return conservative_Ti, conservative_Td, ti_multiplier, td_multiplier
    
    def _build_result(self, pb: float, Ti: float, Td: float, Pu: float, Ku: float,
                      reason: str) -> Dict[str, Any]:
        """构建保守 PID 参数结果"""
        conservative_Kp = 100.0 / pb
        conservative_Ki = conservative_Kp / Ti
        conservative_Kd = conservative_Kp * Td if Td > 0 else 0.0
        
        result = {
            'Kp': round(conservative_Kp, 6), 'Ki': round(conservative_Ki, 6), 'Kd': round(conservative_Kd, 6),
            'Ti': round(Ti, 4), 'Td': round(Td, 4) if Td > 0 else 0.0,
            'method': f'{reason}_adaptive',
            'Pu': round(Pu, 2), 'Ku': round(Ku, 2), 'pb': round(pb, 2)
        }
        return result
