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
from typing import Dict
from dataclasses import dataclass


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
    is_very_high_delay_ratio: bool = False # 估算 L/T1 > 0.8
    is_high_oscillation: bool = False  # oscillation_ratio > 0.7
    delay_ratio: float = 0.0        # 估算的滞后比
    
    @property
    def has_extreme_condition(self) -> bool:
        """是否存在任何极端条件"""
        return any([
            self.is_high_gain, self.is_very_high_gain,
            self.is_slow_system, self.is_very_slow_system,
            self.is_fast_system, self.is_very_fast_system,
            self.is_high_delay_ratio, self.is_very_high_delay_ratio,
            self.is_high_oscillation
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
        is_very_high_delay_ratio=delay_ratio > 0.8,
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
    
    @abstractmethod
    def get_fallback_params(self) -> Dict[str, float]:
        """
        获取 fallback 整定参数（回路特定）
        
        当振荡分析无法提取有效特征时，使用这些参数进行保守整定。
        
        Returns:
            Dict with keys:
            - pb_base: 基础 pb 值
            - t1_divisor: 数据时长除数（用于估算 T1）
            - t1_min: T1 最小值
            - ti_multiplier: Ti 乘数
        """
        pass


class FlowLoopStrategy(LoopTypeStrategy):
    """流量回路策略"""
    
    @property
    def loop_type(self) -> str:
        return 'flow'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, gain_threshold=5.0, very_high_gain_threshold=6.0)
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            factor = 1.0 + (K_approx - 6.0) * 0.4
            factor = min(factor, 2.0)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 5.0) * 0.2
            factor = min(factor, 1.4)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.6:
            factor = 1.1 + (scenario.delay_ratio - 0.6) * 0.8
            factor = min(factor, 1.4)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_very_fast_system:
            factor = 1.05 + (8.0 - Pu) * 0.02
            factor = min(factor, 1.1)    # 1.3 -> 1.1
            reason = f"极快系统(Pu={Pu:.1f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Flow{reason}: pb保守 ×{factor:.2f}")
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict, log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, oscillation_ratio, gain_threshold=5.0, very_high_gain_threshold=6.0)
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            factor = 1.0 + (K_approx - 6.0) * 0.3
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 5.0) * 0.15
            factor = min(factor, 1.3)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_very_high_delay_ratio:
            factor = 1.1 + (scenario.delay_ratio - 0.8) * 0.5
            factor = min(factor, 1.2)  # 1.4 -> 1.2
            reason = f"极大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_high_delay_ratio:
            factor = 1.05 + (scenario.delay_ratio - 0.6) * 0.4
            factor = min(factor, 1.1)  # 1.4 -> 1.1
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_high_oscillation:
            factor = 1.0 + (oscillation_ratio - 0.7) * 0.8
            factor = min(factor, 1.4)
            reason = f"高振荡({oscillation_ratio:.2f})"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Flow Ti调整({reason}): ×{factor:.2f}")
        return ti_mult
    
    def get_fallback_params(self) -> Dict[str, float]:
        # 平衡优化: 流量回路恢复稳定性
        return {'pb_base': 60.0, 't1_divisor': 5.0, 't1_min': 5.0, 'ti_multiplier': 0.8}


class TemperatureLoopStrategy(LoopTypeStrategy):
    """温度回路策略"""
    
    @property
    def loop_type(self) -> str:
        return 'temperature'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, gain_threshold=4.0, very_high_gain_threshold=6.0)
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            factor = 1.2 + (K_approx - 6.0) * 0.15
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 4.0) * 0.1
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.4:
            factor = 1.15 + (scenario.delay_ratio - 0.4) * 1.0
            factor = min(factor, 1.6)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_slow_system:
            factor = 1.0 + (Pu - 60.0) / 80.0
            factor = min(factor, 1.4)
            reason = f"慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Temp{reason}: pb保守 ×{factor:.2f}")
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict, log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, oscillation_ratio, gain_threshold=4.0, very_high_gain_threshold=6.0)
        factor = 1.0
        reason = None
        
        if scenario.is_high_gain:
            factor = 1.0 + (K_approx - 4.0) * 0.25
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_high_delay_ratio and scenario.delay_ratio > 0.4:
            factor = 1.1 + (scenario.delay_ratio - 0.4) * 0.8
            factor = min(factor, 1.4)
            reason = f"大滞后比(L/T1={scenario.delay_ratio:.2f})"
        elif scenario.is_slow_system:
            factor = 1.0 + (Pu - 60.0) / 100.0
            factor = min(factor, 1.3)
            reason = f"慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Temp Ti调整({reason}): ×{factor:.2f}")
        return ti_mult
    
    def get_fallback_params(self) -> Dict[str, float]:
        # 平衡优化: 温度回路恢复稳定性
        return {'pb_base': 60.0, 't1_divisor': 3.0, 't1_min': 25.0, 'ti_multiplier': 2.2}


class PressureLoopStrategy(LoopTypeStrategy):
    """压力回路策略"""
    
    @property
    def loop_type(self) -> str:
        return 'pressure'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, gain_threshold=5.0, very_high_gain_threshold=7.0)
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            factor = 1.3 + (K_approx - 7.0) * 0.15
            factor = min(factor, 1.8)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 5.0) * 0.15
            factor = min(factor, 1.6)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_very_fast_system:
            factor = 1.15 + (8.0 - Pu) * 0.04
            factor = min(factor, 1.4)
            reason = f"极快系统(Pu={Pu:.1f}s)"
        elif scenario.is_fast_system:
            factor = 1.0 + (15.0 - Pu) * 0.02
            factor = min(factor, 1.3)
            reason = f"快速系统(Pu={Pu:.1f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Press{reason}: pb保守 ×{factor:.2f}")
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict, log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, oscillation_ratio, gain_threshold=5.0, very_high_gain_threshold=7.0)
        factor = 1.0
        reason = None
        
        if scenario.is_high_oscillation:
            factor = 1.1 + (oscillation_ratio - 0.7) * 1.0
            factor = min(factor, 1.4)
            reason = f"高振荡({oscillation_ratio:.2f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 5.0) * 0.12
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        
        if factor > 1.0:
            ti_mult *= factor
            if log_func:
                log_func(f"   📊 Press Ti调整({reason}): ×{factor:.2f}")
        return ti_mult
    
    def get_fallback_params(self) -> Dict[str, float]:
        # 平衡优化: 压力回路恢复稳定性
        return {'pb_base': 70.0, 't1_divisor': 4.0, 't1_min': 10.0, 'ti_multiplier': 1.0}


class LevelLoopStrategy(LoopTypeStrategy):
    """液位回路策略"""
    
    @property
    def loop_type(self) -> str:
        return 'level'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, gain_threshold=3.0, very_high_gain_threshold=5.0)
        factor = 1.0
        reason = None
        
        if scenario.is_very_high_gain:
            factor = 1.3 + (K_approx - 5.0) * 0.15
            factor = min(factor, 1.6)
            reason = f"极高增益(K={K_approx:.1f})"
        elif scenario.is_high_gain:
            factor = 1.0 + (K_approx - 3.0) * 0.15
            factor = min(factor, 1.5)
            reason = f"高增益(K={K_approx:.1f})"
        elif scenario.is_very_slow_system:
            factor = 1.0 + (Pu - 100.0) / 100.0
            factor = min(factor, 1.8)
            reason = f"极慢系统(Pu={Pu:.0f}s)"
        
        if factor > 1.0:
            pb_base *= factor
            if log_func:
                log_func(f"   ⚠️ Level{reason}: pb保守 ×{factor:.2f}")
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict, log_func=None) -> float:
        scenario = detect_extreme_scenario(K_approx, Pu, oscillation_ratio, gain_threshold=3.0, very_high_gain_threshold=5.0)
        level_ti_base = osc_config.get('level_ti_multiplier', 1.4)
        
        if scenario.is_very_slow_system:
            level_ti_base = min(level_ti_base, 1.2)
            if log_func:
                log_func(f"   📊 Level极慢系统Ti限制: ×{level_ti_base:.2f}")
        elif scenario.is_high_oscillation:
            extra_factor = 1.0 + (oscillation_ratio - 0.7) * 0.5
            extra_factor = min(extra_factor, 1.3)
            level_ti_base *= extra_factor
            level_ti_base = min(level_ti_base, 1.6)
            if log_func:
                log_func(f"   📊 Level高振荡Ti增强: ×{level_ti_base:.2f}")
        else:
            if log_func:
                log_func(f"   📊 Level积分特性Ti调整: ×{level_ti_base:.2f}")
        
        ti_mult *= level_ti_base
        return ti_mult
    
    def get_fallback_params(self) -> Dict[str, float]:
        # 平衡优化: 液位回路恢复稳定性
        return {'pb_base': 120.0, 't1_divisor': 3.0, 't1_min': 35.0, 'ti_multiplier': 2.8}


class DefaultLoopStrategy(LoopTypeStrategy):
    """默认回路策略"""
    
    @property
    def loop_type(self) -> str:
        return 'default'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict, log_func=None) -> float:
        return ti_mult
    
    def get_fallback_params(self) -> Dict[str, float]:
        # 石化优化v2: 默认回路
        return {'pb_base': 80.0, 't1_divisor': 4.0, 't1_min': 12.0, 'ti_multiplier': 1.2}


# 策略注册表
_STRATEGY_REGISTRY: Dict[str, LoopTypeStrategy] = {
    'flow': FlowLoopStrategy(),
    'temperature': TemperatureLoopStrategy(),
    'pressure': PressureLoopStrategy(),
    'level': LevelLoopStrategy(),
}

_DEFAULT_STRATEGY = DefaultLoopStrategy()


def get_loop_strategy(loop_type: str) -> LoopTypeStrategy:
    """获取回路类型策略"""
    return _STRATEGY_REGISTRY.get(loop_type, _DEFAULT_STRATEGY)


def register_loop_strategy(loop_type: str, strategy: LoopTypeStrategy) -> None:
    """注册自定义回路类型策略"""
    _STRATEGY_REGISTRY[loop_type] = strategy
