"""
system_tuning core2 模块
整定段选取和分析相关功能

整合了：
1. 滑动窗口方差分析（find_high_variability_periods）
2. core目录的整定段选取逻辑：
   - StabilityDetector的稳态检测方法
   - DataAnalyzer的CASE分类和整定段提取方法
"""
from .tuning_segment_selector import TuningSegmentSelector, find_high_variability_periods

__all__ = [
    'TuningSegmentSelector',
    'find_high_variability_periods'
]
