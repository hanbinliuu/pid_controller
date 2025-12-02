"""
PID模型自动选择功能模块

该模块提供基于最小二乘法的PID模型自动选择功能，能够自动识别数据属于一阶、一阶加纯滞后（FOPDT）还是二阶模型。
"""

from .model_types import ModelType
from .model_detector import ModelDetector, DetectionResult
from .visualizer import Visualizer
from .data_generator import DataGenerator
from .accuracy_evaluator import AccuracyEvaluator, EvaluationResult
from .model_selector import ModelSelector
from .config import ModelSelectionConfig, default_config

__all__ = [
    'ModelDetector',
    'ModelType',
    'DetectionResult',
    'Visualizer',
    'DataGenerator',
    'AccuracyEvaluator',
    'EvaluationResult',
    'ModelSelector',
    'ModelSelectionConfig',
    'default_config'
]

