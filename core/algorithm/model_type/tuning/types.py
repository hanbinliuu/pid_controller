"""
类型定义模块 (Types Module)
===========================

定义整定方法使用的类型提示，提高代码可读性和IDE支持。
"""

from typing import TypedDict, Optional, List, Dict, Any


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


class ConservativePIDParamsWithLLM(ConservativePIDParams, total=False):
    """包含 LLM 决策信息的保守 PID 参数"""
    llm_decision: Optional[Dict[str, Any]]


class OscillationRatingDetails(TypedDict, total=False):
    """振荡整定评分详情"""
    stability_score: float
    data_quality_score: float
    boundary_score: float
    method_score: float
    oscillation_ratio: float
    raw_data_quality: float
    nonlinearity: float
    pb: float
    method: str
    weights: Dict[str, float]
    warnings: List[str]
    risk_factors: int
    valve_issues: ValveIssues


class OscillationInfo(TypedDict, total=False):
    """振荡分析信息"""
    Pu: float
    Ku: float
    amplitude: float
    mv_amplitude: float
    decay_ratio: float
    oscillation_type: str
    n_cycles: int
    is_valid: bool
    confidence: float
    oscillation_ratio: float


class OscillationTuningResult(TypedDict, total=False):
    """振荡整定结果"""
    success: bool
    pid_params: ConservativePIDParams
    oscillation_info: OscillationInfo
    segment_idx: int
    method: str
    data_quality: float
    nonlinearity: float
    valve_issues: ValveIssues


class ClosedLoopInfo(TypedDict, total=False):
    """闭环验证信息"""
    is_stable: bool
    settling_time: float
    overshoot: float
    rise_time: float
    steady_state_error: float
    oscillation_count: int
    decay_ratio: float
    sp_initial: float
    sp_final: float
    pv_initial: float


class FallbackParams(TypedDict):
    """回路类型 fallback 参数"""
    pb_base: float
    t1_divisor: float
    t1_min: float
    ti_multiplier: float
