"""
模型类型选择模块

模块结构：
- config.py          - 模型类型枚举和全局配置常量
- utils.py           - 公共工具方法（指标计算、时间戳解析等）
- identifier.py      - 模型辨识器（各种模型的参数辨识）
- data_preprocessor.py - 数据预处理（滤波、去噪、非线性检测）
- fusion_strategy.py - PID参数融合策略
- segment_validator.py - 扰动段验证
- pid_calculator.py  - PID参数计算（Lambda方法）
- model_evaluator.py - 模型评分和质量验证
- model_selector.py  - 主协调器

流程：
1. 剔除无效/扰动段 (SegmentValidator)
2. 对每个有效段尝试多种模型拟合 (ModelIdentifier)
3. 基于AIC/RSS/形状特征选择最优模型结构
4. 融合各段参数 → 唯一K, T, L (PIDFusionStrategy)
5. 验证一致性与仿真匹配度 (ModelEvaluator)
"""

# 核心类
from .model_selector import ModelSelector, SegmentResult, FusionResult
from .config import Config, ModelType
from .identifier import ModelIdentifier

# 工具类
from .utils import MetricsCalculator, TimestampParser, DataValidator, SimulationHelper
from .segment_validator import SegmentValidator, HistoricalData, TuningWindow
from .pid_calculator import PIDCalculator, PIDParameters
from .model_evaluator import ModelEvaluator, RatingDetails
from .fusion_strategy import PIDFusionStrategy, FusionStrategy, WindowResult
from .data_preprocessor import DataPreprocessor, DataQuality, NonlinearityAnalysis

__all__ = [
    # 主类
    'ModelSelector',
    'SegmentResult', 
    'FusionResult',
    
    # 配置
    'Config',
    'ModelType',
    
    # 辨识器
    'ModelIdentifier',
    
    # 工具类
    'MetricsCalculator',
    'TimestampParser',
    'DataValidator',
    'SimulationHelper',
    
    # 段验证
    'SegmentValidator',
    'HistoricalData',
    'TuningWindow',
    
    # PID计算
    'PIDCalculator',
    'PIDParameters',
    
    # 评估
    'ModelEvaluator',
    'RatingDetails',
    
    # 融合策略
    'PIDFusionStrategy',
    'FusionStrategy',
    'WindowResult',
    
    # 数据预处理
    'DataPreprocessor',
    'DataQuality',
    'NonlinearityAnalysis',
]
