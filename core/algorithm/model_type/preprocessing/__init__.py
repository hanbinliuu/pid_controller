"""
预处理子模块 (Preprocessing Submodule)
=====================================

负责数据预处理和扰动段处理。

模块结构:
- data_preprocessor.py: 数据预处理 (DataPreprocessor)
- segment_processor.py: 扰动段处理 (SegmentProcessor)
- segment_manager.py: 段管理器 (SegmentManager) - 段合并、分类、降采样
"""

from .data_preprocessor import DataPreprocessor
from .segment_processor import SegmentProcessor
from .segment_manager import SegmentManager

__all__ = ['DataPreprocessor', 'SegmentProcessor', 'SegmentManager']
