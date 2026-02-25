"""
工具函数模块 (Utility Functions Module)
=======================================

本模块提供模型辨识过程中常用的工具函数。

统计指标计算
------------
- calculate_r2: 计算决定系数 R²
- calculate_rmse: 计算均方根误差 RMSE
- calculate_rss: 计算残差平方和 RSS
- calculate_aic: 计算 AIC (赤池信息准则)
- calculate_bic: 计算 BIC (贝叶斯信息准则)

信号分析
--------
- calculate_oscillation_ratio: 计算振荡比
- calculate_signal_range: 计算信号范围和增益估计

其他工具
--------
- parse_timestamp: 解析各种格式的时间戳
- get_recommendation: 根据评分获取推荐等级
- determine_turning_type: 根据PID参数确定整定类型 (P/PI/PID)
"""

import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Tuple

# 北京时区 (UTC+8)
BEIJING_TZ = timezone(timedelta(hours=8))

from .config import Config


EPSILON = Config.EPSILON


def calculate_r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """计算决定系数 R²"""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    if ss_tot < EPSILON:
        return 0.0
    r2 = 1 - ss_res / ss_tot
    return float(min(r2, 1.0))


def calculate_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """计算均方根误差 RMSE"""
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def calculate_rss(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """计算残差平方和 RSS"""
    return float(np.sum((y_true - y_pred) ** 2))


def calculate_aic(rss: float, n: int, k: int) -> float:
    """计算 AIC (Akaike Information Criterion)"""
    if rss <= 0 or n <= k:
        return float('inf')
    return n * np.log(rss / n) + 2 * k


def calculate_bic(rss: float, n: int, k: int) -> float:
    """计算 BIC (Bayesian Information Criterion)"""
    if rss <= 0 or n <= k:
        return float('inf')
    return n * np.log(rss / n) + k * np.log(n)


def calculate_oscillation_ratio(signal: np.ndarray) -> float:
    """
    计算信号的振荡比（符号变化频率）
    
    振荡比 = 符号变化次数 / (信号长度 - 2)
    
    Args:
        signal: 输入信号数组
    
    Returns:
        振荡比 [0, 1]，越大表示振荡越剧烈
    """
    if len(signal) < 3:
        return 0.0
    
    signal_diff = np.diff(signal)
    sign_changes = np.sum(np.abs(np.diff(np.sign(signal_diff))) > 0)
    oscillation_ratio = sign_changes / (len(signal) - 2)
    
    return float(min(oscillation_ratio, 1.0))


def calculate_signal_range(pv: np.ndarray, mv: np.ndarray, 
                           epsilon: float = None) -> Tuple[float, float, float]:
    """
    计算信号范围和估计增益
    
    Args:
        pv: 过程变量数组
        mv: 操作变量数组
        epsilon: 最小值阈值，默认使用 Config.EPSILON
    
    Returns:
        (pv_range, mv_range, k_estimate): PV范围、MV范围、估计增益
    """
    if epsilon is None:
        epsilon = EPSILON
    
    pv_range = float(np.ptp(pv))
    mv_range = float(np.ptp(mv))
    
    if mv_range > epsilon:
        k_estimate = pv_range / mv_range
    else:
        k_estimate = 1.0
    
    return pv_range, mv_range, k_estimate


def parse_timestamp(ts: Any) -> Optional[float]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        ts_clean = ts.strip().replace('Z', '').split('+')[0]
        for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
            try:
                dt_naive = datetime.strptime(ts_clean, fmt)
                dt_aware = dt_naive.replace(tzinfo=BEIJING_TZ)
                return dt_aware.timestamp() * 1000
            except ValueError:
                continue
        return None
    if hasattr(ts, 'timestamp'):
        return ts.timestamp() * 1000
    return None


def get_recommendation(model_rating: float) -> str:
    """根据评分获取推荐等级"""
    if model_rating >= 8.0:
        return '优秀'
    elif model_rating >= 6.0:
        return '良好'
    elif model_rating >= 4.0:
        return '可接受'
    elif model_rating >= 2.0:
        return '较差'
    else:
        return '不可用'


def determine_turning_type(Kp: float, Ti: float, Td: float) -> str:
    """根据 PID 参数确定整定类型"""
    if Td > EPSILON:
        return 'PID'
    elif Ti > EPSILON:
        return 'PI'
    else:
        return 'P'
