"""
PID计算器数据类模块
==================

定义PID计算器使用的数据类。
"""

import numpy as np
from dataclasses import dataclass


@dataclass
class ClosedLoopMetrics:
    """闭环性能指标"""
    is_stable: bool              # 是否稳定
    settling_time: float         # 调节时间（进入±2%误差带）
    overshoot: float             # 超调量 (%)
    rise_time: float             # 上升时间（10%到90%）
    steady_state_error: float    # 稳态误差
    oscillation_count: int       # 振荡次数
    decay_ratio: float           # 衰减比
    pv_history: np.ndarray       # PV响应历史
    mv_history: np.ndarray       # MV输出历史


@dataclass
class DataQualityInfo:
    """数据质量信息，用于自适应保守调整"""
    quality_score: float = 0.5      # 质量评分 (0~1)
    oscillation_ratio: float = 0.0  # 振荡比 (0~1)
    r_squared: float = 0.5          # 拟合R² (0~1)
    is_noisy: bool = False          # 是否高噪声
    consistency_score: float = 0.5  # 参数一致性 (0~1)
    correlation: float = 0.0        # PV-MV相关性 (-1~1)
    controller_sign: int = 1        # 当前控制器的Kp符号 (1或-1)
