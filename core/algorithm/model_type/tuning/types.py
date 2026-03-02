"""
类型定义模块 (Types Module)
===========================

定义整定方法使用的类型提示，提高代码可读性和IDE支持。
"""

from typing import TypedDict, List


class ValveIssues(TypedDict, total=False):
    """阀门问题检测结果"""
    has_deadband: bool
    has_stiction: bool
    has_saturation: bool
    deadband_size: float
    stiction_severity: float
    saturation_ratio: float
    issues_detected: List[str]


class ConservativePIDParams(TypedDict):
    """保守 PID 参数结果"""
    Kp: float
    Ki: float
    Kd: float
    Ti: float
    Td: float
    method: str
    Pu: float
    Ku: float
    pb: float
