"""
验证与评分子模块 (Verification Submodule)
========================================

闭环仿真验证和模型评分。

模块内容
--------
- closed_loop_sim.py: 闭环仿真 (ClosedLoopSimMixin)
- model_rating.py: 模型评分 (ModelRatingMixin)
"""

from .closed_loop_sim import ClosedLoopSimMixin
from .model_rating import ModelRatingMixin

__all__ = [
    'ClosedLoopSimMixin',
    'ModelRatingMixin',
]
