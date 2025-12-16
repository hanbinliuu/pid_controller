"""
拟合子模块 (Fitting Submodule)
==============================

负责模型辨识、多段拟合和参数融合。
"""

from .model_identifier import ModelIdentifier
from .segment_fitter import SegmentFitter
from .fusion_strategy import PIDFusionStrategy, WindowResult, FusionResult as StrategyFusionResult
from .type_selector import UnifiedModelSelector, SegmentModelFit

__all__ = [
    'ModelIdentifier', 
    'SegmentFitter', 
    'PIDFusionStrategy', 
    'WindowResult',
    'StrategyFusionResult',
    'UnifiedModelSelector',
    'SegmentModelFit'
]
