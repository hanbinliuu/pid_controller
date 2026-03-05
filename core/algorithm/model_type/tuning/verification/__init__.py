"""
验证模块 (Verification Module)
==============================

提供闭环仿真和模型评分功能。
"""

from .closed_loop_sim import ClosedLoopSimMixin
from .stability_analyzer import StabilityAnalyzer, StabilityMargins

__all__ = ["ClosedLoopSimMixin", "StabilityAnalyzer", "StabilityMargins"]
