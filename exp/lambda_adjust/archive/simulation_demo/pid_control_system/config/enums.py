"""枚举类型定义"""
from enum import Enum


class Mode(str, Enum):
    """系统运行模式枚举"""
    STANDARD = "standard"
    ANTI_DISTURBANCE = "anti_disturbance"
    ANTI_NOISE = "anti_noise"
    FLOW_CONTROL = "flow_control"  # 水阀流量控制模式


class PIDMode(str, Enum):
    """PID控制模式枚举"""
    STANDARD = "standard"
    DERIVATIVE_ON_MEASUREMENT = "derivative_on_measurement"
    PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT = "proportional_derivative_on_measurement"


class DisturbanceType(str, Enum):
    """扰动类型枚举"""
    OVERSHOOT = "overshoot"
    STEADY_ERROR = "steady_error"
    SLOW_RECOVERY = "slow_recovery"
    VALVE_STICTION = "valve_stiction"
    SENSOR_DRIFT = "sensor_drift"
    HEAT_LOSS = "heat_loss"
    CONTROL_VALVE_WEAR = "control_valve_wear"
    THERMAL_INERTIA = "thermal_inertia"
    FLOW_NOISE = "flow_noise"  # 流量噪声
    FLOW_STICTION = "flow_stiction"  # 流量阀门卡涩


class NoiseReductionLevel(str, Enum):
    """降噪强度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TuningMethod(str, Enum):
    """PID整定方法枚举"""
    LAMBDA = "lambda"
    COHEN_COON = "cohen-coon"

