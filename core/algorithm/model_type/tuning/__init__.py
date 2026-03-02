"""
整定模块 (Tuning Module)
========================

提供 PID 参数计算、振荡分析、稳定性验证等功能。
"""

from .core.data_classes import DataQualityInfo, ClosedLoopMetrics
from .core.pid_calculator import PIDCalculator
from .oscillation.oscillation_tuner import OscillationTuner
from .method_selector import TuningMethodSelector, TuningMethod, TuningMethodResult
from .verification.stability_analyzer import StabilityAnalyzer, StabilityMargins

__all__ = [
    "PIDCalculator",
    "DataQualityInfo",
    "ClosedLoopMetrics",
    "OscillationTuner",
    "TuningMethodSelector",
    "TuningMethod",
    "TuningMethodResult",
    "StabilityAnalyzer",
    "StabilityMargins",
]
