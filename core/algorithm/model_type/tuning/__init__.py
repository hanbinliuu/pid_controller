"""
整定子模块 (Tuning Submodule)
=============================

负责PID参数计算、振荡整定和闭环验证。
"""

from .pid_calculator import PIDCalculator, DataQualityInfo
from .oscillation_tuner import OscillationTuner

__all__ = ['PIDCalculator', 'DataQualityInfo', 'OscillationTuner']
