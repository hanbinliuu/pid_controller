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

其他工具
--------
- parse_timestamp: 解析各种格式的时间戳
- get_recommendation: 根据评分获取推荐等级
- determine_turning_type: 根据PID参数确定整定类型 (P/PI/PID)
"""

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


def normalize_pid_keys(pid_params: dict) -> dict:
    """规范化 PID 参数 key 为大写 Kp/Ki/Kd。
    
    兼容输入 'kp'/'Kp' 两种格式，统一返回大写 key。
    """
    return {
        'Kp': float(pid_params.get('Kp', pid_params.get('kp', 1.0))),
        'Ki': float(pid_params.get('Ki', pid_params.get('ki', 0.0))),
        'Kd': float(pid_params.get('Kd', pid_params.get('kd', 0.0))),
    }


def pid_to_full_dict(Kp: float, Ki: float, Kd: float, eps: float = 1e-10) -> dict:
    """从 Kp/Ki/Kd 生成完整 PID 参数字典（含 pb/ti/td 和双格式 key）。
    
    统一 PID 参数转换逻辑，避免在各模块重复计算 pb/ti/td。
    """
    pb = 100.0 / abs(Kp) if abs(Kp) > eps else 999.0
    ti = abs(Kp / Ki) if abs(Ki) > eps else 0.0
    td = abs(Kd / Kp) if abs(Kp) > eps else 0.0
    return {
        'Kp': round(float(Kp), 8),
        'Ki': round(float(Ki), 8),
        'Kd': round(float(Kd), 8),
        'kp': round(float(Kp), 8),
        'ki': round(float(Ki), 8),
        'kd': round(float(Kd), 8),
        'pb': round(pb, 2),
        'ti': round(ti, 2),
        'td': round(td, 2),
    }


def build_segment_info(segments: list, segment_results: list) -> list:
    """
    构建段信息用于可视化（独立工具函数）
    
    从 OutputBuilder 中提取为独立函数，消除 output_builder ↔ oscillation_tuner 循环依赖。
    
    Args:
        segments: 段数据列表 (HistoricalData)
        segment_results: 段结果列表 (SegmentResult)
        
    Returns:
        段信息列表
    """
    segment_info = []
    if not segments or not segment_results:
        return segment_info
        
    for i, (seg, result) in enumerate(zip(segments, segment_results)):
        if len(seg.timestamp) > 0:
            # 获取属性值，兼容对象和字典
            if hasattr(result, 'step_response_score'):
                step_score = result.step_response_score
                osc_ratio = result.oscillation_ratio
            else:
                step_score = result.get('step_response_score', 0.5)
                osc_ratio = result.get('oscillation_ratio', 0.5)
            
            # 判断段类型：阶跃特征好且振荡低 → 整定段
            is_tuning = (step_score >= 0.5 and osc_ratio < 0.5)
            
            segment_info.append({
                'index': i,
                'start_time': int(seg.timestamp[0]),
                'end_time': int(seg.timestamp[-1]),
                'data_points': len(seg.pv),
                'step_response_score': round(step_score, 2),
                'oscillation_ratio': round(osc_ratio, 2),
                'type': 'tuning' if is_tuning else 'oscillation'
            })
    return segment_info
