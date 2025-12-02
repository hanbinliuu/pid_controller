"""
核心算法模块
提供PID参数整定、扰动检测、模型选择等核心功能
"""

try:
    from .system_tuning import SystemIdentifier, Config, Mode, TuningMethod
except ImportError:
    # 如果导入失败，尝试相对导入
    from .system_tuning.config import Config, Mode, TuningMethod
    from .system_tuning.core.tuning.identifier import SystemIdentifier

__all__ = [
    'SystemIdentifier',
    'Config',
    'Mode',
    'TuningMethod',
]

