"""
性能评分模块 (Performance Rating Module)
=======================================

提供独立于参数产生方式的纯控制品质评分逻辑。
用于统一评估模型辨识、振荡整定等不同方法产生的 PID 参数。
"""

from typing import Optional
from .data_classes import ClosedLoopMetrics


def calculate_control_performance(metrics: Optional[ClosedLoopMetrics]) -> float:
    """
    统一的 PID 控制效果评分 (0-10 分)
    专用于评价阶跃响应波形的纯控制品质，不关心该参数是如何算出来的。
    
    Args:
        metrics: 闭环仿真指标数据
        
    Returns:
        float: 0.0 ~ 10.0 的得分
    """
    if metrics is None:
        return 5.0
        
    # 一票否决：不稳定直接给极低分（1.0 分）
    if not metrics.is_stable:
        return 1.0
        
    # 如果稳定，基础分为 6.0 分（及格），后续根据波形质量加减分
    score = 6.0
    
    # 【1】超调量评估 (理想状态是小幅超调或无超调)
    if metrics.overshoot <= 5:
        score += 1.5           # 几乎无超调，非常完美
    elif metrics.overshoot <= 15:
        score += 1.0           # 经典工业容忍范围内
    elif metrics.overshoot <= 30:
        score += 0.5           # 偏激进但可用
    elif metrics.overshoot <= 50:
        score -= 0.5           # 超调过大，扣分
    else:
        score -= 1.5           # 超调极差，重度惩罚
        
    # 【2】调节时间评估 (进入误差带并稳定下来的时间)
    if metrics.settling_time < float('inf'):
        if metrics.settling_time <= 30:
            score += 1.0       # 极快稳定
        elif metrics.settling_time <= 60:
            score += 0.5       # 正常稳定
        elif metrics.settling_time > 120:
            score -= 0.5       # 太慢了（例如单纯依靠很弱的积分在爬）
            
    # 【3】稳态误差评估 (无静差是基础要求)
    if metrics.steady_state_error <= 1.0:
        score += 1.0           # 完美消除静差
    elif metrics.steady_state_error <= 2.0:
        score += 0.5
    elif metrics.steady_state_error > 5.0 and metrics.steady_state_error <= 10.0:
        score -= 0.5           # 有明显残余偏差
    elif metrics.steady_state_error > 10.0:
        score -= 1.0           # 无法消除静差
        
    # 【4】振荡控制评估 (衰减比与振荡次数)
    if metrics.oscillation_count == 0:
        score += 0.5           # 过阻尼或临界阻尼（平滑）
    elif metrics.oscillation_count <= 2:
        score += 1.0           # 最理想的 4:1 经典衰减，1~2个小波峰
    elif metrics.oscillation_count <= 4:
        score += 0.5           # 稍微有点震，但能收敛
    elif metrics.oscillation_count > 5:
        score -= 0.5           # 震荡太多次
        
    if metrics.decay_ratio <= 0.25:
        score += 0.5           # 衰减极快，收敛极好
    elif metrics.decay_ratio >= 0.8:
        score -= 1.0           # 衰减极慢，接近等幅振荡边缘
        
    return round(min(10.0, max(0.0, score)), 2)
