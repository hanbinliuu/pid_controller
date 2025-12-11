"""工具函数模块"""

import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

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
    return float(np.clip(r2, 0.0, 1.0))


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
