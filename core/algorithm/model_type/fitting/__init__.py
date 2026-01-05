"""
拟合子模块 (Fitting Submodule)
==============================

负责模型辨识、多段拟合和参数融合。

新增辨识方法：
- StepResponseIdentifier: 阶跃响应法 (63%, 面积法, 两点法)
- FrequencyDomainIdentifier: 频域法 (互相关, FFT)
- EnsembleIdentifier: 多方法融合辨识
"""

from .model_identifier import ModelIdentifier, EnsembleIdentifier
from .segment_fitter import SegmentFitter
from .fusion_strategy import PIDFusionStrategy, WindowResult, FusionResult as StrategyFusionResult
from .type_selector import UnifiedModelSelector, SegmentModelFit
from .step_response_identifier import StepResponseIdentifier
from .frequency_domain_identifier import FrequencyDomainIdentifier
from .relay_identifier import RelayIdentifier, RelayResult, LimitCycleInfo

__all__ = [
    'ModelIdentifier',
    'EnsembleIdentifier',
    'SegmentFitter', 
    'PIDFusionStrategy', 
    'WindowResult',
    'StrategyFusionResult',
    'UnifiedModelSelector',
    'SegmentModelFit',
    'StepResponseIdentifier',
    'FrequencyDomainIdentifier',
    'RelayIdentifier',
    'RelayResult',
    'LimitCycleInfo',
]

