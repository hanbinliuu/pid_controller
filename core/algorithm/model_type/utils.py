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


def normalize_pid_keys(pid_params: dict, eps: float = 1e-10) -> dict:
    """规范化 PID 参数 key 为大写 Kp/Ki/Kd。
    
    兼容输入 'kp'/'Kp' 或 'pb'/'ti'/'td' 两种格式，统一返回大写 key。
    """
    if 'Kp' in pid_params or 'kp' in pid_params:
        Kp = float(pid_params.get('Kp', pid_params.get('kp', 1.0)))
        Ki = float(pid_params.get('Ki', pid_params.get('ki', 0.0)))
        Kd = float(pid_params.get('Kd', pid_params.get('kd', 0.0)))
    elif 'pb' in pid_params or 'PB' in pid_params:
        pb = float(pid_params.get('pb', pid_params.get('PB', 100.0)))
        ti = float(pid_params.get('ti', pid_params.get('TI', 10.0)))
        td = float(pid_params.get('td', pid_params.get('TD', 0.0)))
        
        Kp = 100.0 / pb if abs(pb) > eps else 1.0
        Ki = Kp / ti if abs(ti) > eps else 0.0
        Kd = Kp * td
    else:
        Kp, Ki, Kd = 1.0, 0.0, 0.0
        
    result = dict(pid_params)
    result.update({
        'Kp': Kp,
        'Ki': Ki,
        'Kd': Kd,
    })
    return result


def pid_to_full_dict(Kp: float, Ki: float, Kd: float, eps: float = 1e-10) -> dict:
    """从 Kp/Ki/Kd 生成完整 PID 参数字典（含 pb/ti/td 和双格式 key）。
    
    统一 PID 参数转换逻辑，避免在各模块重复计算 pb/ti/td。
    """
    pb = 100.0 / abs(Kp) if abs(Kp) > eps else 999.0
    ti = abs(Kp / Ki) if abs(Ki) > eps else 0.0
    td = abs(Kd / Kp) if abs(Kp) > eps else 0.0
    result = {
        'Kp': round(float(Kp), 8),
        'Ki': round(float(Ki), 8),
        'Kd': round(float(Kd), 8),
        'kp': round(float(Kp), 8),
        'ki': round(float(Ki), 8),
        'kd': round(float(Kd), 8),
        'pb': round(pb, 2),
        'ti': round(ti, 2),
        'td': round(td, 2),
        'Ti': round(ti, 2),
        'Td': round(td, 2),
    }
    return result


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


# ============================================================
# 共享工具函数 — 消除多处重复代码 (v4.2)
# ============================================================

def compute_sampling_period(hist_data) -> float:
    """从历史数据计算采样周期(秒)。

    统一替代在 stage_05_refinement / stage_05b_self_optimize / output_builder 中
    各自重复实现的 dt_data 计算逻辑。

    Args:
        hist_data: HistoricalData 对象（可以为 None）

    Returns:
        采样周期，单位秒，默认 1.0
    """
    if hist_data is None:
        return 1.0
    if not hasattr(hist_data, 'timestamp') or len(hist_data.timestamp) < 2:
        return 1.0
    ts = np.array(hist_data.timestamp, dtype=np.int64)
    ts_diff = np.diff(ts[ts > 0]) / 1000.0
    if len(ts_diff) > 0:
        return float(np.median(ts_diff))
    return 1.0


def build_cl_verification(cl_metrics, sp_initial: float, sp_final: float,
                          pv_initial: float, is_stable: bool = None,
                          **extra_fields) -> dict:
    """构建 closed_loop_verification 字典。

    统一替代在 output_builder / stage_05_refinement / oscillation_tuner /
    stage_05b_self_optimize 中各自重复构建的 closed_loop_info 字典。

    Args:
        cl_metrics: ClosedLoopMetrics 对象
        sp_initial: 设定值初值
        sp_final: 设定值终值
        pv_initial: PV 初值
        is_stable: 由 verify_pid_stability 返回的稳定性判定。
                   如为 None，则降级为 settling_time < inf 判定（不推荐）。
        **extra_fields: 额外字段（如 gain_margin, phase_margin 等），直接合并到输出字典。

    Returns:
        closed_loop_verification 字典
    """
    if is_stable is None:
        is_stable = cl_metrics.settling_time < float('inf')
    result = {
        'is_stable': is_stable,
        'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
        'overshoot': cl_metrics.overshoot,
        'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
        'steady_state_error': cl_metrics.steady_state_error,
        'oscillation_count': cl_metrics.oscillation_count,
        'decay_ratio': cl_metrics.decay_ratio,
        'sp_initial': sp_initial,
        'sp_final': sp_final,
        'pv_initial': pv_initial,
    }
    result.update(extra_fields)
    return result


def compute_sim_params(hist_data, config: dict = None) -> tuple:
    """从历史数据推导闭环仿真初始参数 (sp_initial, sp_final, pv_initial)。

    统一替代在 output_builder / stage_05_refinement / stage_05b_self_optimize 中
    各自重复实现的仿真参数推导逻辑。

    Args:
        hist_data: HistoricalData 对象
        config: MODEL_SELECTOR 配置字典，默认使用 Config.MODEL_SELECTOR

    Returns:
        (sp_initial, sp_final, pv_initial) 元组，如果数据无效则返回 None
    """
    if hist_data is None:
        return None
    if config is None:
        config = Config.MODEL_SELECTOR

    valid_mask = hist_data.valid_mask()
    y = hist_data.pv[valid_mask]
    sv = hist_data.sv[valid_mask]

    if len(y) == 0 or len(sv) == 0:
        return None

    sp_initial = float(sv[0])
    sp_final = float(sv[-1])
    pv_initial = float(y[0])

    sp_change = abs(sp_final - sp_initial)
    pv_sp_diff = abs(pv_initial - sp_initial)
    min_sp_change = float(config.get('min_sp_change', 0.5))

    # 无明显SV阶跃：使用“工作点附近小步进”验证，避免 50->60 这类失真评分场景
    if sp_change < min_sp_change:
        sv_med = float(np.median(sv))
        pv_med = float(np.median(y))
        pv_std = float(np.std(y))
        base = max(abs(sv_med), abs(pv_med), 1.0)
        step_mag = max(pv_std * 4.0, base * 0.01, 0.02)
        step_mag = min(step_mag, base * 0.08)
        direction = 1.0
        diff = sv_med - pv_med
        if abs(diff) > 1e-9:
            direction = float(np.sign(diff))
        sp_initial = pv_med
        sp_final = pv_med + direction * step_mag
        pv_initial = pv_med
    elif pv_sp_diff > sp_change * 2:
        # SP/PV 工作点明显错位：仍保留真实量纲，避免回落到固定 50/60
        sv_med = float(np.median(sv))
        pv_med = float(np.median(y))
        direction = float(np.sign(sp_final - sp_initial)) if abs(sp_final - sp_initial) > 1e-9 else 1.0
        step_mag = max(sp_change, max(abs(sv_med), abs(pv_med), 1.0) * 0.01)
        sp_initial = sv_med
        sp_final = sv_med + direction * step_mag
        pv_initial = pv_med

    return sp_initial, sp_final, pv_initial
