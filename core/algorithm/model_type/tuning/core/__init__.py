"""
核心PID计算子模块 (Core PID Calculation Submodule)
=================================================

包含PID参数计算的核心逻辑。

模块结构:
- pid_calculator.py: 主PID计算器 (PIDCalculator)
- tuning_methods.py: 整定公式 (TuningMethodsMixin)
- data_classes.py: 数据类 (ClosedLoopMetrics, DataQualityInfo)
"""

from .data_classes import ClosedLoopMetrics, DataQualityInfo
from .pid_calculator import PIDCalculator

__all__ = [
    'PIDCalculator',
    'ClosedLoopMetrics',
    'DataQualityInfo',
]
