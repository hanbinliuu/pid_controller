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
import numpy as np


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
    调整：
    - K>6 时适度增加 pb
    - K>6 时增加 Ti 避免积分过冲
    """
    
    @property
    def loop_type(self) -> str:
        return 'flow'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # Flow 回路仅在极高增益 (K>6) 时进行 pb 调整
        if K_approx > 6.0:
            flow_gain_factor = 1.0 + (K_approx - 6.0) * 0.2
            flow_gain_factor = min(flow_gain_factor, 2.0)
            pb_base *= flow_gain_factor
            if log_func:
                log_func(f"   ⚠️ Flow极高增益(K={K_approx:.1f}): pb保守 ×{flow_gain_factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # Flow 中极高增益(K>6)：增加 Ti 避免积分过冲
        if K_approx > 6.0:
            flow_high_gain_ti = 1.0 + (K_approx - 6.0) * 0.3
            flow_high_gain_ti = min(flow_high_gain_ti, 1.8)
            ti_mult *= flow_high_gain_ti
            if log_func:
                log_func(f"   📊 Flow高增益Ti调整(K={K_approx:.1f}): ×{flow_high_gain_ti:.2f}")
        
        return ti_mult


class TemperatureLoopStrategy(LoopTypeStrategy):
    """
    温度回路策略
    
    特点：响应慢，热惯性大，大滞后
    调整：
    - K>4 时适度增加 pb
    - K>4 时增加 Ti 避免振荡
    """
    
    @property
    def loop_type(self) -> str:
        return 'temperature'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 温度回路高增益 (K>4) 适度保守
        if K_approx > 4.0:
            temp_gain_factor = 1.0 + (K_approx - 4.0) * 0.15
            temp_gain_factor = min(temp_gain_factor, 1.8)
            pb_base *= temp_gain_factor
            if log_func:
                log_func(f"   ⚠️ Temp高增益(K={K_approx:.1f}): pb保守 ×{temp_gain_factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # Temperature 中高增益场景(K>4)：增加 Ti 避免振荡
        if K_approx > 4.0:
            temp_high_gain_ti = 1.0 + (K_approx - 4.0) * 0.25
            temp_high_gain_ti = min(temp_high_gain_ti, 1.5)
            ti_mult *= temp_high_gain_ti
            if log_func:
                log_func(f"   📊 Temp高增益Ti调整(K={K_approx:.1f}): ×{temp_high_gain_ti:.2f}")
        
        return ti_mult


class PressureLoopStrategy(LoopTypeStrategy):
    """
    压力回路策略
    
    特点：响应快，对增益变化敏感
    调整：
    - K>5 时适度增加 pb
    - Pu<15 额外保守
    """
    
    @property
    def loop_type(self) -> str:
        return 'pressure'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # 压力回路高增益 (K>5) 保守处理
        if K_approx > 5.0:
            press_gain_factor = 1.0 + (K_approx - 5.0) * 0.2
            press_gain_factor = min(press_gain_factor, 1.8)
            pb_base *= press_gain_factor
            if log_func:
                log_func(f"   ⚠️ Press高增益(K={K_approx:.1f}): pb保守 ×{press_gain_factor:.2f}")
        
        # 快速系统 (Pu<15) 保守处理
        if Pu < 15.0:
            fast_factor = 1.0 + (15.0 - Pu) * 0.03
            fast_factor = min(fast_factor, 1.4)
            pb_base *= fast_factor
            if log_func:
                log_func(f"   ⚠️ Press快速系统(Pu={Pu:.1f}s): pb保守 ×{fast_factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 压力回路高增益 (K>5)：增加 Ti
        if K_approx > 5.0:
            press_high_gain_ti = 1.0 + (K_approx - 5.0) * 0.15
            press_high_gain_ti = min(press_high_gain_ti, 1.5)
            ti_mult *= press_high_gain_ti
            if log_func:
                log_func(f"   📊 Press高增益Ti调整(K={K_approx:.1f}): ×{press_high_gain_ti:.2f}")
        
        return ti_mult


class LevelLoopStrategy(LoopTypeStrategy):
    """
    液位回路策略
    
    特点：积分过程特性，响应慢
    调整：
    - 所有液位回路适用基础 Ti 乘数
    - Pu>100 时限制 Ti 增幅
    """
    
    @property
    def loop_type(self) -> str:
        return 'level'
    
    def adjust_pb_for_extreme(self, pb_base: float, K_approx: float, Pu: float,
                              log_func=None) -> float:
        # Level 回路高增益 (K>3) 适度保守处理
        if K_approx > 3.0:
            level_gain_factor = 1.0 + (K_approx - 3.0) * 0.2
            level_gain_factor = min(level_gain_factor, 1.6)
            pb_base *= level_gain_factor
            if log_func:
                log_func(f"   ⚠️ Level高增益(K={K_approx:.1f}): pb保守 ×{level_gain_factor:.2f}")
        
        return pb_base
    
    def adjust_ti_multiplier(self, ti_mult: float, K_approx: float, Pu: float,
                             oscillation_ratio: float, osc_config: Dict,
                             log_func=None) -> float:
        # 液位回路：积分过程特性，需要更大 Ti 避免积分饱和
        level_ti_multiplier = osc_config.get('level_ti_multiplier', 1.4)
        
        # 极慢液位系统(Pu>100)：减小 Ti 增幅，加快响应
        if Pu > 100.0:
            level_ti_multiplier = min(level_ti_multiplier, 1.2)
            if log_func:
                log_func(f"   📊 极慢液位Ti限制: ×{level_ti_multiplier}")
        
        ti_mult *= level_ti_multiplier
        if log_func:
            log_func(f"   📊 液位回路Ti调整: ×{level_ti_multiplier}")
        
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
