"""
振荡整定子模块 (Oscillation Tuning Submodule)
=============================================

处理高振荡数据的临界法整定。

模块内容
--------
- oscillation_tuner.py: 振荡整定器主入口 (OscillationTuner)
- oscillation_analysis.py: 振荡分析 (OscillationAnalysisMixin)
- oscillation_rating.py: 振荡整定评分 (OscillationRatingCalculator)
- conservative_pid.py: 保守PID计算 (ConservativePIDCalculator)
"""

from .oscillation_tuner import OscillationTuner
from .oscillation_analysis import OscillationAnalysisMixin
from .oscillation_rating import OscillationRatingCalculator
from .conservative_pid import ConservativePIDCalculator

__all__ = [
    'OscillationTuner',
    'OscillationAnalysisMixin',
    'OscillationRatingCalculator',
    'ConservativePIDCalculator',
]
