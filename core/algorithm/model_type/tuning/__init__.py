"""
整定子模块 (Tuning Submodule)
=============================

负责PID参数计算、振荡整定和闭环验证。

模块结构:
- data_classes.py: 数据类 (ClosedLoopMetrics, DataQualityInfo)
- tuning_methods.py: 整定公式 (TuningMethodsMixin)
- oscillation_analysis.py: 振荡分析 (OscillationAnalysisMixin)
- closed_loop_sim.py: 闭环仿真 (ClosedLoopSimMixin)
- model_rating.py: 模型评分 (ModelRatingMixin)
- pid_calculator.py: 主计算器 (PIDCalculator)
"""

from .data_classes import ClosedLoopMetrics, DataQualityInfo
from .pid_calculator import PIDCalculator
from .oscillation_tuner import OscillationTuner

__all__ = [
    'PIDCalculator', 
    'DataQualityInfo', 
    'ClosedLoopMetrics',
    'OscillationTuner'
]
