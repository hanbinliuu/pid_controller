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
from ..strategies.loop_type_strategies import get_loop_strategy, LoopTypeStrategy


class ConservativePIDCalculator(LoggerMixin):
    """保守PID参数计算器"""
    
    def __init__(self, verbose: bool = False, llm_client=None, 
                 loop_type: str = "", loop_name: str = ""):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._llm_client = llm_client
        self._llm_advisor = None
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        
        if llm_client is not None:
            self._init_llm_advisor(llm_client)
    
    def set_llm_client(self, llm_client, loop_type: str = "", loop_name: str = ""):
        """设置 LLM 客户端"""
        self._llm_client = llm_client
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        self._init_llm_advisor(llm_client)
    
    def _init_llm_advisor(self, llm_client):
        """初始化 LLM 顾问"""
        try:
            from ..strategies.llm_conservative_advisor import LLMOscillationTuningAdvisor
            self._llm_advisor = LLMOscillationTuningAdvisor(llm_client=llm_client, verbose=self._verbose)
        except ImportError:
            self._llm_advisor = None

    def calculate(self, Pu: float, Ku: float, 
                  K_approx: float = 1.0, reason: str = 'generic',
                  oscillation_ratio: float = 0.0, data_quality: float = 0.5,
                  nonlinearity: float = 0.0, valve_issues: Dict = None,
                  confidence: float = 0.5) -> Dict[str, Any]:
        """计算保守PID参数"""
        if valve_issues is None:
            valve_issues = {}
        
        llm_strategy, llm_decision_info = self._get_llm_strategy(
            Pu, Ku, K_approx, oscillation_ratio, data_quality,
            nonlinearity, valve_issues, confidence
        )
        
        pb_base, pb_from_K, pb_from_Ku, slow_factor = self._calculate_base_pb(Ku, K_approx, Pu)
        pb_base = self._apply_quality_factors(pb_base, reason, data_quality, nonlinearity, valve_issues)
        pb_base, delay_ratio = self._apply_extreme_factors(pb_base, K_approx, Pu, oscillation_ratio)
        pb_base, safety_factor = self._apply_oscillation_adjustment(pb_base, oscillation_ratio, llm_strategy)
        pb_safe = self._apply_pb_bounds(pb_base, K_approx, confidence, reason, pb_from_K, pb_from_Ku, Pu, Ku, slow_factor, delay_ratio)
        Ti, Td, ti_multiplier, td_multiplier = self._calculate_ti_td(Pu, oscillation_ratio, K_approx, llm_strategy)
        
        return self._build_result(pb_safe, Ti, Td, Pu, Ku, reason, llm_strategy, llm_decision_info)
    
    def _get_llm_strategy(self, Pu: float, Ku: float, K_approx: float,
                          oscillation_ratio: float, data_quality: float,
                          nonlinearity: float, valve_issues: Dict,
                          confidence: float) -> Tuple[Any, Optional[Dict]]:
        """获取 LLM 策略参数"""
        osc_config = Config.OSCILLATION_TUNING
        enable_llm = osc_config.get('enable_llm', True)
        
        if not enable_llm or self._llm_advisor is None:
            return None, None
        
        has_valve_issues = valve_issues.get('has_deadband', False) or valve_issues.get('has_stiction', False)
        should_use_llm = (has_valve_issues or data_quality < 0.5 or nonlinearity > 0.5 or confidence < 0.5 or oscillation_ratio > 0.7)
        
        if not should_use_llm:
            self.log(f"   📊 场景简单，跳过LLM，使用规则引擎")
            return None, None
        
        self.log(f"   🤖 困难场景，启用LLM")
        try:
            llm_strategy = self._llm_advisor.decide_conservative_strategy(
                Pu=Pu, Ku=Ku, K_approx=K_approx, oscillation_ratio=oscillation_ratio,
                data_quality=data_quality, nonlinearity=nonlinearity, valve_issues=valve_issues,
                confidence=confidence, loop_type=self._loop_type, loop_name=self._loop_name
            )
            if llm_strategy is not None:
                llm_decision_info = {
                    'strategy_params': {
                        'safety_factor': llm_strategy.safety_factor,
                        'pb_extra_factor': llm_strategy.pb_extra_factor,
                        'ti_multiplier': llm_strategy.ti_multiplier,
                        'enable_derivative': llm_strategy.enable_derivative,
                        'td_factor': llm_strategy.td_factor,
                    },
                    'reasoning': llm_strategy.reasoning,
                    'confidence': llm_strategy.confidence,
                }
                return llm_strategy, llm_decision_info
        except Exception as e:
            self.log(f"   ⚠️ LLM 策略决策失败: {e}")
        return None, None

    def _calculate_base_pb(self, Ku: float, K_approx: float, Pu: float) -> Tuple[float, float, float, float]:
        """计算基础 pb 值"""
        osc_config = Config.OSCILLATION_TUNING
        pb_from_k_factor = osc_config.get('pb_from_k_factor', 1.5)
        pb_from_K = 100.0 * K_approx * pb_from_k_factor if K_approx > 0.01 else 80.0
        
        kp_from_ku_factor = osc_config.get('kp_from_ku_factor', 0.2)
        if Ku > 0.1:
            Kp_from_Ku = kp_from_ku_factor * Ku
            pb_from_Ku = 100.0 / max(Kp_from_Ku, 0.1)
        else:
            pb_from_Ku = 100.0
        
        pu_thresholds = osc_config.get('slow_system_pu_thresholds', [30.0, 15.0])
        slow_factors = osc_config.get('slow_system_factors', [1.3, 1.15, 1.0])
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
        """应用极端场景因子"""
        if K_approx > 4.0:
            if K_approx > 6.0:
                extreme_gain_factor = min(1.0 + (K_approx - 4.0) * 0.25, 3.0)
            else:
                extreme_gain_factor = min(1.0 + (K_approx - 4.0) * 0.15, 2.0)
            pb_base *= extreme_gain_factor
            self.log(f"   ⚠️ 极高增益场景(K={K_approx:.1f}): 保守因子 ×{extreme_gain_factor:.2f}")
        
        pb_base = self._strategy.adjust_pb_for_extreme(pb_base, K_approx, Pu, log_func=self.log)
        
        estimated_L = Pu / 4.0
        T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
        delay_ratio = estimated_L / max(T1_approx, 1.0)
        
        if delay_ratio > 0.8:
            delay_factor = 2.5
        elif delay_ratio > 0.6:
            delay_factor = min(1.6 + (delay_ratio - 0.6) * 4.0, 2.4)
        elif delay_ratio > 0.4:
            delay_factor = 1.3 + (delay_ratio - 0.4) * 1.5
        else:
            delay_factor = 1.0
        
        if delay_factor > 1.0:
            pb_base *= delay_factor
            self.log(f"   ⚠️ 滞后比(L/T1≈{delay_ratio:.2f}): 保守 ×{delay_factor:.2f}")
        
        if oscillation_ratio > 0.85:
            extreme_osc_factor = min(1.2 + (oscillation_ratio - 0.85) * 2.0, 1.6)
            pb_base *= extreme_osc_factor
            self.log(f"   ⚠️ 极端振荡场景: 保守因子 ×{extreme_osc_factor:.2f}")
        
        return pb_base, delay_ratio
    
    def _apply_oscillation_adjustment(self, pb_base: float, oscillation_ratio: float,
                                      llm_strategy: Any) -> Tuple[float, float]:
        """应用振荡比自适应调整"""
        osc_config = Config.OSCILLATION_TUNING
        pb_gradient = osc_config.get('pb_gradient', 2.0)
        pb_osc_start = osc_config.get('pb_oscillation_start', 0.4)
        safety_base = osc_config.get('safety_factor_base', 1.4)
        safety_thresholds = osc_config.get('safety_factor_thresholds', [0.5, 0.7, 0.85])
        safety_slopes = osc_config.get('safety_factor_slopes', [0.5, 1.0, 2.0])
        
        if llm_strategy is not None:
            safety_factor = llm_strategy.safety_factor
        else:
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
        
        total_multiplier = safety_factor
        if llm_strategy is not None:
            total_multiplier *= llm_strategy.pb_extra_factor
        
        if oscillation_ratio > pb_osc_start:
            effective_osc = oscillation_ratio - pb_osc_start
            osc_multiplier = 1.0 + np.sqrt(effective_osc) * pb_gradient
            total_multiplier *= osc_multiplier
            max_mult = osc_config.get('max_multiplier_high_osc', 3.0) if oscillation_ratio > safety_thresholds[2] else osc_config.get('max_multiplier_normal', 2.5)
            total_multiplier = min(total_multiplier, max_mult)
        
        pb_base *= total_multiplier
        return pb_base, safety_factor

    def _apply_pb_bounds(self, pb_base: float, K_approx: float, confidence: float, reason: str,
                        pb_from_K: float, pb_from_Ku: float, Pu: float, Ku: float, 
                        slow_factor: float, delay_ratio: float = 0.0) -> float:
        """应用 pb 边界限制"""
        osc_config = Config.OSCILLATION_TUNING
        pb_min_base = osc_config.get('pb_min', 80.0)
        pb_max_config = osc_config.get('pb_max', 600.0)
        
        if confidence >= 0.8:
            pb_max = min(pb_max_config, 400.0)
        elif confidence >= 0.5:
            pb_max = min(pb_max_config, 600.0)
        else:
            pb_max = min(pb_max_config * 1.3, 800.0)
        
        pb_k_factor = osc_config.get('pb_k_adjustment_factor', 0.3)
        if K_approx > 0.01:
            pb_min_dynamic = min(pb_min_base * (1.0 + pb_k_factor / K_approx), 400.0)
        else:
            pb_min_dynamic = 400.0
        pb_min = max(pb_min_base, pb_min_dynamic)
        
        if reason == 'low_gain':
            pb_min = min(pb_min * osc_config.get('ku_k_extreme_pb_factor', 1.5), 500.0)
        
        pb_safe = np.clip(pb_base, pb_min, pb_max)
        self.log(f"   📊 动态pb计算: K={K_approx:.3f}→pb={pb_from_K:.1f}, Ku={Ku:.3f}→pb={pb_from_Ku:.1f}, 最终pb={pb_safe:.1f}")
        return pb_safe
    
    def _calculate_ti_td(self, Pu: float, oscillation_ratio: float, K_approx: float, 
                         llm_strategy: Any) -> Tuple[float, float, float, float]:
        """计算保守的 Ti 和 Td 值"""
        osc_config = Config.OSCILLATION_TUNING
        ti_min_base = osc_config.get('ti_min_base', 1.5)
        # 减小基础除数：Pu/3 而非 Pu/2，让 Ti 不容易触顶
        base_Ti = max(Pu / 3, ti_min_base) if Pu > 0 else 2.0
        
        ti_osc_start = osc_config.get('ti_osc_start', 0.6)
        ti_osc_factor = osc_config.get('ti_osc_factor', 0.5)
        ti_multiplier = 1.0 + np.sqrt(oscillation_ratio - ti_osc_start) * ti_osc_factor if oscillation_ratio > ti_osc_start else 1.0
        
        ti_slow_thresholds = osc_config.get('ti_slow_pu_thresholds', [20.0, 10.0])
        ti_slow_factors = osc_config.get('ti_slow_factors', [1.1, 1.05, 1.0])
        for i, threshold in enumerate(ti_slow_thresholds):
            if Pu > threshold:
                ti_multiplier *= ti_slow_factors[i]
                break
        
        if llm_strategy is None:
            ti_multiplier = self._strategy.adjust_ti_multiplier(ti_multiplier, K_approx, Pu, oscillation_ratio, osc_config, log_func=self.log)
        else:
            ti_multiplier *= llm_strategy.ti_multiplier
        
        conservative_Ti = np.clip(base_Ti * ti_multiplier, *osc_config.get('ti_range', [1.5, 25.0]))
        
        conservative_Td = 0.0
        td_multiplier = 0.0
        enable_derivative = osc_config.get('enable_adaptive_derivative', True)
        derivative_threshold = osc_config.get('derivative_oscillation_threshold', 0.5)
        
        if llm_strategy is not None:
            enable_derivative = llm_strategy.enable_derivative
        
        if enable_derivative and (oscillation_ratio > derivative_threshold or (llm_strategy and llm_strategy.enable_derivative)):
            # 增大基础除数：默认 12 而非 8，让 Td 不容易触顶
            td_base_divisor = osc_config.get('td_base_divisor', 12.0)
            base_Td = Pu / td_base_divisor if Pu > 0 else 0.5
            td_mult_factor = osc_config.get('td_multiplier_factor', 1.5)
            effective_osc = max(0, oscillation_ratio - derivative_threshold)
            td_multiplier = 1.0 + np.sqrt(effective_osc) * td_mult_factor
            if llm_strategy is not None and llm_strategy.td_factor > 0:
                td_multiplier *= llm_strategy.td_factor
            conservative_Td = np.clip(base_Td * td_multiplier, *osc_config.get('td_range', [0.3, 3.0]))
        
        return conservative_Ti, conservative_Td, ti_multiplier, td_multiplier
    
    def _build_result(self, pb: float, Ti: float, Td: float, Pu: float, Ku: float, 
                      reason: str, llm_strategy: Any, llm_decision_info: Optional[Dict]) -> Dict[str, Any]:
        """构建保守 PID 参数结果"""
        conservative_Kp = 100.0 / pb
        conservative_Ki = conservative_Kp / Ti
        conservative_Kd = conservative_Kp * Td if Td > 0 else 0.0
        
        result = {
            'Kp': round(conservative_Kp, 2), 'Ki': round(conservative_Ki, 2), 'Kd': round(conservative_Kd, 2),
            'Ti': round(Ti, 4), 'Td': round(Td, 4) if Td > 0 else 0.0,
            'method': f'{reason}_llm' if llm_strategy else f'{reason}_adaptive',
            'Pu': round(Pu, 2), 'Ku': round(Ku, 2), 'pb': round(pb, 2)
        }
        if llm_decision_info is not None:
            result['llm_decision'] = llm_decision_info
        return result
