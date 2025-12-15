"""
模型类型辨识模块 (Model Type Identification Module)
====================================================

本模块实现了基于历史数据的系统模型辨识和PID参数整定功能。

核心功能
--------
1. **多模型辨识**: 支持 FOPDT、FO、SOPDT、SO、FOPI 等多种过程模型
2. **多段融合**: 对多个扰动段进行参数融合，提高辨识精度
3. **PID整定**: 基于辨识结果计算最优PID参数
4. **质量评估**: 评估模型拟合质量和数据可靠性

主要类
------
- **ModelSelector**: 主入口类，协调整个辨识流程
- **SegmentProcessor**: 扰动段提取和预处理
- **SegmentFitter**: 多模型拟合
- **UnifiedModelSelector**: 统一模型类型选择
- **PIDCalculator**: PID参数计算
- **ModelSimulator**: 模型仿真验证
- **OutputBuilder**: 结果输出构建

使用示例
--------
>>> from core.algorithm.model_type import ModelSelector
>>> selector = ModelSelector(verbose=True)
>>> result = selector.select(input_data, lambda_factor=1.0)
>>> print(result['pid_parameters'])
"""

from .config import Config, ModelType
from .models import SegmentResult, FusionResult, TuningInput, TuningWindow, HistoricalData
from .model_selector import ModelSelector
from .simulator import ModelSimulator
from .pid_calculator import PIDCalculator
from .segment_processor import SegmentProcessor
from .segment_fitter import SegmentFitter
from .output_builder import OutputBuilder
from .unified_model_selector import UnifiedModelSelector, SegmentModelFit
from .logger import LoggerMixin, get_logger

__all__ = [
    # ============================================================
    # 主入口类
    # ============================================================
    'ModelSelector', 
    
    # ============================================================
    # 数据模型类
    # ============================================================
    'SegmentResult',      # 单个扰动段的拟合结果
    'FusionResult',       # 多段参数融合结果
    'TuningInput',        # 整定输入参数
    'TuningWindow',       # 整定窗口定义
    'HistoricalData',     # 历史数据容器
    
    # ============================================================
    # 配置类
    # ============================================================
    'ModelType',          # 模型类型枚举
    'Config',             # 全局配置参数
    
    # ============================================================
    # 功能子模块
    # ============================================================
    'ModelSimulator',     # 模型仿真器
    'PIDCalculator',      # PID参数计算器
    'SegmentProcessor',   # 扰动段处理器
    'SegmentFitter',      # 多模型拟合器
    'OutputBuilder',      # 输出构建器
    'UnifiedModelSelector',  # 统一模型选择器
    'SegmentModelFit',    # 单段多模型拟合结果
    
    # ============================================================
    # 日志工具
    # ============================================================
    'LoggerMixin',        # 日志混入类
    'get_logger',         # 获取日志器
]
