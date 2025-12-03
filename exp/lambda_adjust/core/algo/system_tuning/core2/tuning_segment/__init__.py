"""
稳定性检测模块

保持与原detector.py相同的处理逻辑，只是输入输出格式改变：
- 输入: Pandas Series with datetime index
- 输出: dict包含 table, start_time, end_time, params, total_windows, std_max_window
"""

from .stability_detector import (
    find_high_variability_periods,
    StabilityDetector,
    merge_adjacent_periods,
    HighVariabilityDetector
)

__all__ = [
    'find_high_variability_periods',
    'StabilityDetector',
    'merge_adjacent_periods',
    'HighVariabilityDetector'
]
