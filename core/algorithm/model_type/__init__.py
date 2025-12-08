"""
模型类型选择模块

流程：
1. 剔除无效/扰动段
2. 对每个有效段尝试多种模型拟合
3. 基于AIC/RSS/形状特征选择最优模型结构
4. 融合各段参数 → 唯一K, T, L
5. 验证一致性与仿真匹配度

模块结构：
- config.py: 配置和模型类型定义
- models.py: 数据结构定义
- utils.py: 工具函数
- identifier.py: 模型辨识
- data_preprocessor.py: 数据预处理
- fusion_strategy.py: 融合策略
- segment_processor.py: 段提取和过滤
- simulator.py: 仿真逻辑
- pid_calculator.py: PID计算
- model_selector.py: 主类
"""

from .config import Config, ModelType
from .models import SegmentResult, FusionResult, TuningInput, TuningWindow, HistoricalData
from .model_selector import ModelSelector
from .simulator import ModelSimulator
from .pid_calculator import PIDCalculator
from .segment_processor import SegmentProcessor

__all__ = [
    'ModelSelector', 
    'SegmentResult', 
    'FusionResult',
    'TuningInput',
    'TuningWindow', 
    'HistoricalData',
    'ModelType',
    'Config',
    'ModelSimulator',
    'PIDCalculator',
    'SegmentProcessor',
]
