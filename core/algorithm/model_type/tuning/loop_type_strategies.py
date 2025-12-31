"""
回路类型策略模块 (Loop Type Strategies Module)
=================================================

本模块使用策略模式封装不同回路类型的特定调整逻辑。

回路类型特点
------------
- **流量回路 (flow)**: 响应快，对高增益敏感，K>6 时需要额外保守
- **温度回路 (temperature)**: 响应慢，需要更大 Ti，K>4 时增加 Ti
- **压力回路 (pressure)**: 响应快，使用默认逻辑
- **液位回路 (level)**: 积分特性，Pu>100 时特殊处理

使用方式
--------
```python
strategy = get_loop_strategy('flow')
pb_base = strategy.adjust_pb_for_extreme(pb_base, K_approx, Pu)
ti_mult = strategy.adjust_ti_multiplier(ti_mult, K_approx, Pu, osc_ratio, config)
```
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional
from dataclasses import dataclass
import numpy as np


@dataclass
class ExtremeScenario:
    """
    极端场景检测结果
    
    用于识别需要特殊处理的极端工况
    """
    is_high_gain: bool = False      # K > 阈值（按回路类型不同）
    is_very_high_gain: bool = False # K > 高阈值（极端情况）
    is_slow_system: bool = False    # Pu > 60s
    is_very_slow_system: bool = False  # Pu > 100s
    is_fast_system: bool = False    # Pu < 15s
    is_very_fast_system: bool = False  # Pu < 8s
    is_high_delay_ratio: bool = False  # 估算 L/T1 > 0.5
    is_high_oscillation: bool = False  # oscillation_ratio > 0.7
    delay_ratio: float = 0.0        # 估算的滞后比
    
    @property
    def has_extreme_condition(self) -> bool:
        """是否存在任何极端条件"""
        return any([
            self.is_high_gain, self.is_very_high_gain,
            self.is_slow_system, self.is_very_slow_system,
            self.is_fast_system, self.is_very_fast_system,
            self.is_high_delay_ratio, self.is_high_oscillation
        ])


def detect_extreme_scenario(K_approx: float, Pu: float, 
                           oscillation_ratio: float = 0.0,
                           gain_threshold: float = 4.0,
                           very_high_gain_threshold: float = 6.0) -> ExtremeScenario:
    """
    检测极端场景
    
    Args:
        K_approx: 估计的过程增益
        Pu: 临界周期
        oscillation_ratio: 振荡比
        gain_threshold: 高增益阈值（按回路类型调整）
        very_high_gain_threshold: 极高增益阈值
        
    Returns:
        ExtremeScenario: 极端场景检测结果
    """
    # 估算滞后比 L/T1
    # 使用 Ziegler-Nichols 近似: Pu ≈ 4L, T1 ≈ Pu * (1 + 1/K) / 4
    estimated_L = Pu / 4.0
    T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
    delay_ratio = estimated_L / max(T1_approx, 1.0)
    
    return ExtremeScenario(
        is_high_gain=K_approx > gain_threshold,
        is_very_high_gain=K_approx > very_high_gain_threshold,
        is_slow_system=Pu > 60.0,
        is_very_slow_system=Pu > 100.0,
        is_fast_system=Pu < 15.0,
        is_very_fast_system=Pu < 8.0,
        is_high_delay_ratio=delay_ratio > 0.5,
        is_high_oscillation=oscillation_ratio > 0.7,
        delay_ratio=delay_ratio
    )


class LoopTypeStrategy(ABC):
    """
    回路类型策略基类
    
    所有回路类型策略都需要实现两个核心方法：
    1. adjust_pb_for_extreme - 极端场景 pb 调整
    2. adjust_ti_multiplier - Ti 乘数调整
    """
    
    @property
    @abstractmethod
    def loop_type(self) -> str:
        """回路类型标识"""
        pass
    
    @abstractmethod
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        """
        极端场景 pb 调整
        
        Args:
            pb_base: 基础 pb 值
            K_approx: 估计的过程增益
            Pu: 临界周期
            log_func: 日志函数（可选）
            
        Returns:
            调整后的 pb 值
        """
        pass
    
    @abstractmethod
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        """
        Ti 乘数调整
        
        Args:
            ti_mult: 当前 Ti 乘数
            K_approx: 估计的过程增益
            Pu: 临界周期
            oscillation_ratio: 振荡比
            osc_config: 振荡整定配置
            log_func: 日志函数（可选）
            
        Returns:
            调整后的 Ti 乘数
        """
        pass


class FlowLoopStrategy(LoopTypeStrategy):
    """
    流量回路策略
    
    特点：响应快，对高增益敏感
    极端场景处理：
    - 极高增益 (K>6): pb ×1.2-2.0, Ti ×1.3-1.8
    - 快速系统 (Pu<10): pb ×1.1-1.3
    - 大滞后比 (L/T1>0.5): pb ×1.15-1.4, Ti ×1.1-1.3
    """
    
    @property
    def loop_type(self) -> str:
        return 'flow'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 检测极端场景
        scenario = detect_extreme_scenario(
            K_approx, Pu, 
            gain_threshold=5.0,  # Flow 对高增益更敏感
            very_high_gain_threshold=6.0
        )
        
        # 选择性应用：只选择最主导的因子
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            # 极高增益 (K>6): 主导因素
            factor = 1.0 + (K_approx - 6.0) * 0.15
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.6:
            # 大滞后比 (L/T1>0.6)
            factor = 1.1 + (scenario.delay_ratio - 0.6) * 0.8
            factor = min(factor, 1.4)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_very_fast_system:
            # 极快系统 (Pu<8)
            factor = 1.1 + (8.0 - Pu) * 0.03
            factor = min(factor, 1.3)
            reason = f"极快系统(Pu={Pu:.1f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Flow{reason}: pb保守 ×{factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 检测极端场景
        scenario = detect_extreme_scenario(
            K_approx, Pu, oscillation_ratio,
            gain_threshold=5.0,
            very_high_gain_threshold=6.0
        )
        
        # 选择性应用
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            # 极高增益：增加 Ti 避免积分过冲
            factor = 1.0 + (K_approx - 6.0) * 0.25
            factor = min(factor, 1.8)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.6:
            # 大滞后比：适度增加 Ti
            factor = 1.0 + (scenario.delay_ratio - 0.6) * 0.6
            factor = min(factor, 1.3)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_high_oscillation:
            # 高振荡：增加 Ti
            factor = 1.0 + (oscillation_ratio - 0.7) * 0.8
            factor = min(factor, 1.4)
            reason = f"高振荡({oscillation_ratio:.2f})"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Flow Ti调整({reason}): ×{factor:.2f}")
        
        return ti_mult


class TemperatureLoopStrategy(LoopTypeStrategy):
    """
    温度回路策略
    
    特点：响应慢，热惯性大，大滞后
    极端场景处理：
    - 高增益 (K>4): pb ×1.15-1.8, Ti ×1.25-1.5
    - 极慢系统 (Pu>60): pb ×1.1-1.4, Ti ×1.1-1.3
    - 大滞后 (L/T1>0.4): pb ×1.2-1.6, Ti ×1.15-1.4
    """
    
    @property
    def loop_type(self) -> str:
        return 'temperature'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 检测极端场景（温度回路阈值较低）
        scenario = detect_extreme_scenario(
            K_approx, Pu,
            gain_threshold=4.0,
            very_high_gain_threshold=6.0
        )
        
        # 选择性应用
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            # 极高增益 (K>6)
            factor = 1.2 + (K_approx - 6.0) * 0.15
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            # 高增益 (K>4)
            factor = 1.0 + (K_approx - 4.0) * 0.1
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.4:
            # 大滞后比 (L/T1>0.4) - 温度回路常见
            factor = 1.15 + (scenario.delay_ratio - 0.4) * 1.0
            factor = min(factor, 1.6)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_slow_system:
            # 慢系统 (Pu>60)
            factor = 1.0 + (Pu - 60.0) / 80.0
            factor = min(factor, 1.4)
            reason = f"慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Temp{reason}: pb保守 ×{factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 检测极端场景
        scenario = detect_extreme_scenario(
            K_approx, Pu, oscillation_ratio,
            gain_threshold=4.0,
            very_high_gain_threshold=6.0
        )
        
        # 选择性应用
        factor = 1.0
        reason = None
        
        if scenario.is_high_gain:
            # 高增益：增加 Ti 避免振荡
            factor = 1.0 + (K_approx - 4.0) * 0.2
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.4:
            # 大滞后比：适度增加 Ti
            factor = 1.1 + (scenario.delay_ratio - 0.4) * 0.8
            factor = min(factor, 1.4)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_slow_system:
            # 慢系统：适度增加 Ti
            factor = 1.0 + (Pu - 60.0) / 100.0
            factor = min(factor, 1.3)
            reason = f"慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Temp Ti调整({reason}): ×{factor:.2f}")
        
        return ti_mult


class PressureLoopStrategy(LoopTypeStrategy):
    """
    压力回路策略
    
    特点：响应快，对增益变化敏感
    极端场景处理：
    - 高增益 (K>5): pb ×1.2-1.8, Ti ×1.15-1.5
    - 快速系统 (Pu<15): pb ×1.1-1.4
    - 高振荡 (osc>0.7): pb ×1.2-1.5, Ti ×1.2-1.4
    """
    
    @property
    def loop_type(self) -> str:
        return 'pressure'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 检测极端场景
        scenario = detect_extreme_scenario(
            K_approx, Pu,
            gain_threshold=5.0,
            very_high_gain_threshold=7.0
        )
        
        # 选择性应用（只选最主导因素）
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            # 极高增益 (K>7)
            factor = 1.3 + (K_approx - 7.0) * 0.15
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            # 高增益 (K>5)
            factor = 1.0 + (K_approx - 5.0) * 0.15
            factor = min(factor, 1.6)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_very_fast_system:
            # 极快系统 (Pu<8) - 压力回路常见
            factor = 1.15 + (8.0 - Pu) * 0.04
            factor = min(factor, 1.4)
            reason = f"极快系统(Pu={Pu:.1f}s)"
        elif scenario.is_fast_system:
            # 快速系统 (Pu<15)
            factor = 1.0 + (15.0 - Pu) * 0.02
            factor = min(factor, 1.3)
            reason = f"快速系统(Pu={Pu:.1f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Press{reason}: pb保守 ×{factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 检测极端场景
        scenario = detect_extreme_scenario(
            K_approx, Pu, oscillation_ratio,
            gain_threshold=5.0,
            very_high_gain_threshold=7.0
        )
        
        # 选择性应用
        factor = 1.0
        reason = None
        
        if scenario.is_high_oscillation:
            # 高振荡优先（压力回路最常见问题）
            factor = 1.1 + (oscillation_ratio - 0.7) * 1.0
            factor = min(factor, 1.4)
            reason = f"高振荡({oscillation_ratio:.2f})"
        elif scenario.is_high_gain:
            # 高增益：增加 Ti
            factor = 1.0 + (K_approx - 5.0) * 0.12
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Press Ti调整({reason}): ×{factor:.2f}")
        
        return ti_mult


class LevelLoopStrategy(LoopTypeStrategy):
    """
    液位回路策略
    
    特点：积分过程特性，响应慢，对增益变化敏感
    极端场景处理：
    - 中等增益 (K>1.5): pb ×1.05-1.15（新增）
    - 高增益 (K>2.0): pb ×1.1-1.5
    - 极高增益 (K>4.0): pb ×1.3-1.6
    - 大时间常数 (T1>60): pb ×1.1-1.4（新增）
    - 极慢系统 (Pu>80): Ti 调整
    - 高振荡: pb ×1.15-1.4
    - 积分特性: 基础 Ti ×1.6
    """
    
    @property
    def loop_type(self) -> str:
        return 'level'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 从配置读取液位回路专用阈值
        from ..config import Config
        osc_config = Config.OSCILLATION_TUNING
        
        gain_threshold = osc_config.get('level_gain_threshold', 2.0)
        very_high_gain_threshold = osc_config.get('level_very_high_gain_threshold', 4.0)
        mid_gain_range = osc_config.get('level_mid_gain_range', [1.5, 3.0])
        mid_gain_factor = osc_config.get('level_mid_gain_factor', 0.1)
        large_t1_threshold = osc_config.get('level_large_t1_threshold', 60.0)
        large_t1_factor_divisor = osc_config.get('level_large_t1_factor', 150.0)
        
        # 检测极端场景（使用配置的阈值）
        scenario = detect_extreme_scenario(
            K_approx, Pu,
            gain_threshold=gain_threshold,
            very_high_gain_threshold=very_high_gain_threshold
        )
        
        # 估算T1（用于大时间常数检测）
        T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
        
        # 选择性应用（按优先级，只选最主导因素）
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            # 极高增益 (K>4.0)
            factor = 1.3 + (K_approx - very_high_gain_threshold) * 0.15
            factor = min(factor, 1.6)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            # 高增益 (K>2.0)
            factor = 1.0 + (K_approx - gain_threshold) * 0.15
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif mid_gain_range[0] < K_approx <= mid_gain_range[1]:
            # 【新增】中等增益场景 (K=1.5~3.0)
            # 液位回路对中等增益也敏感，需要适度保守
            factor = 1.0 + (K_approx - mid_gain_range[0]) * mid_gain_factor
            factor = min(factor, 1.15)
            reason = f"中等增益(K={K_approx:.1f})"
        elif T1_approx > large_t1_threshold:
            # 【新增】大时间常数场景 (T1>60s估算)
            # 液位回路大T1意味着积分特性更强
            factor = 1.0 + (T1_approx - large_t1_threshold) / large_t1_factor_divisor
            factor = min(factor, 1.4)
            reason = f"大T1(≈{T1_approx:.0f}s)"
        elif scenario.is_very_slow_system:
            # 极慢系统 (Pu>100)
            factor = 1.0 + (Pu - 100.0) / 200.0
            factor = min(factor, 1.3)
            reason = f"极慢系统(Pu={Pu:.0f}s)"
        elif scenario.is_slow_system:
            # 【新增】慢系统 (Pu>60)
            factor = 1.0 + (Pu - 60.0) / 150.0
            factor = min(factor, 1.2)
            reason = f"慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Level{reason}: pb保守 ×{factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 检测极端场景（使用配置的阈值）
        gain_threshold = osc_config.get('level_gain_threshold', 2.0)
        very_high_gain_threshold = osc_config.get('level_very_high_gain_threshold', 4.0)
        
        scenario = detect_extreme_scenario(
            K_approx, Pu, oscillation_ratio,
            gain_threshold=gain_threshold,
            very_high_gain_threshold=very_high_gain_threshold
        )
        
        # 液位回路：积分过程特性，需要更大 Ti 避免积分饱和
        # 基础乘数从配置读取
        level_ti_base = osc_config.get('level_ti_multiplier', 1.6)
        level_integrating_t1_threshold = osc_config.get('level_integrating_t1_threshold', 80.0)
        level_integrating_ti_max = osc_config.get('level_integrating_ti_max', 2.2)
        level_slow_pu = osc_config.get('level_slow_system_pu', 80.0)
        
        # 估算T1
        T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
        
        # 根据极端场景调整基础乘数
        if T1_approx > level_integrating_t1_threshold:
            # 近似积分过程：使用渐进策略
            integrating_factor = 1.0 + min((T1_approx - level_integrating_t1_threshold) / 100.0, 0.4)
            level_ti_base *= integrating_factor
            level_ti_base = min(level_ti_base, level_integrating_ti_max)
            if log_func:
                log_func(f"   📊 Level积分过程(T1≈{T1_approx:.0f}s): Ti乘数={level_ti_base:.2f}")
        elif Pu > level_slow_pu:
            # 慢系统：适度增加Ti
            level_ti_base = max(level_ti_base, 1.4)
            if log_func:
                log_func(f"   📊 Level慢系统(Pu={Pu:.0f}s): Ti乘数={level_ti_base:.2f}")
        elif scenario.is_high_oscillation:
            # 高振荡：增加 Ti
            extra_factor = 1.0 + (oscillation_ratio - 0.7) * 0.5
            extra_factor = min(extra_factor, 1.3)
            level_ti_base *= extra_factor
            level_ti_base = min(level_ti_base, level_integrating_ti_max)
            if log_func:
                log_func(f"   📊 Level高振荡Ti增强: ×{level_ti_base:.2f}")
        else:
            if log_func:
                log_func(f"   📊 Level积分特性Ti调整: ×{level_ti_base:.2f}")
        
        ti_mult *= level_ti_base
        
        return ti_mult


class DefaultLoopStrategy(LoopTypeStrategy):
    """
    默认回路策略
    
    用于未指定回路类型或不匹配任何已知类型时
    不进行任何特殊调整
    """
    
    @property
    def loop_type(self) -> str:
        return 'default'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        return ti_mult


# 策略注册表
_STRATEGY_REGISTRY: Dict[str, LoopTypeStrategy] = {
    'flow': FlowLoopStrategy(),
    'temperature': TemperatureLoopStrategy(),
    'pressure': PressureLoopStrategy(),
    'level': LevelLoopStrategy(),
}

_DEFAULT_STRATEGY = DefaultLoopStrategy()


def get_loop_strategy(loop_type: str) -> LoopTypeStrategy:
    """
    获取回路类型策略
    
    Args:
        loop_type: 回路类型 (flow/temperature/pressure/level)
        
    Returns:
        对应的策略实例，如果类型不匹配则返回默认策略
    """
    return _STRATEGY_REGISTRY.get(loop_type, _DEFAULT_STRATEGY)


def register_loop_strategy(loop_type: str, strategy: LoopTypeStrategy) -> None:
    """
    注册自定义回路类型策略
    
    Args:
        loop_type: 回路类型标识
        strategy: 策略实例
    """
    _STRATEGY_REGISTRY[loop_type] = strategy
