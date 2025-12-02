"""
类型定义

定义模型检测相关的枚举和数据类型。
"""

from enum import Enum


class ModelType(str, Enum):
    """模型类型枚举"""
    FIRST_ORDER = "first_order"  # 一阶模型：K, T
    FOPDT = "fopdt"  # 一阶加纯滞后模型：K, T, L
    SECOND_ORDER = "second_order"  # 二阶模型：K, T1, T2

