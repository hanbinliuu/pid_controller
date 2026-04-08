"""特征计算工具包：供 OS 中台参考实现 characterization API"""
from .feature_calculator import (
    calculate_characterization,
    calculate_characterization_as_dict,
    calculate_oscillation_ratio,
    calculate_noise_level,
    calculate_linearity_index,
    calculate_dominant_period_s,
    calculate_stiction_index,
    calculate_deadband_estimated,
    calculate_reversal_error,
    calculate_recent_step_events,
    calculate_performance_score,
)

__all__ = [
    'calculate_characterization',
    'calculate_characterization_as_dict',
    'calculate_oscillation_ratio',
    'calculate_noise_level',
    'calculate_linearity_index',
    'calculate_dominant_period_s',
    'calculate_stiction_index',
    'calculate_deadband_estimated',
    'calculate_reversal_error',
    'calculate_recent_step_events',
    'calculate_performance_score',
]
