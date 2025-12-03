"""系统整定配置模块：包含所有配置类和常量"""


# ============ 自定义异常类 ============

class TuningException(Exception):
    """整定相关异常的基类"""
    pass


class DataQualityError(TuningException):
    """数据质量不足异常"""
    pass


class ModelIdentificationError(TuningException):
    """模型辨识失败异常"""
    pass


class DataPreprocessingError(TuningException):
    """数据预处理失败异常"""
    pass


class ParameterValidationError(TuningException):
    """参数验证失败异常"""
    pass


class InsufficientDataError(DataQualityError):
    """数据量不足异常"""
    pass


# ============ 枚举类 ============

class Mode:
    """控制模式枚举"""
    STANDARD = "STANDARD"
    ANTI_DISTURBANCE = "ANTI_DISTURBANCE"
    ANTI_NOISE = "ANTI_NOISE"
    FLOW_CONTROL = "FLOW_CONTROL"


class TuningMethod:
    """整定方法枚举"""
    LAMBDA = "LAMBDA"
    COHEN_COON = "COHEN_COON"
    ZIEGLER_NICHOLS = "ZIEGLER_NICHOLS"      # 适用于纯一阶惯性（压力控制）
    IMPROVED_PI = "IMPROVED_PI"              # 适用于积分过程（液位控制）
    DERIVATIVE_FIRST = "DERIVATIVE_FIRST"    # 适用于SOPDT（二阶滞后）
    DAMPING_PID = "DAMPING_PID"              # 适用于SO+DT（二阶振荡）


class ModelType:
    """模型类型枚举
    
    模型类型及其适配场景：
    - FOPDT: 一阶滞后，占比40%，适合阶跃响应
    - FIRST_ORDER: 纯一阶惯性，占比10%，适合压力控制
    - IDT: 积分+滞后，占比15%，适合液位控制
    - SOPDT: 二阶滞后，占比15%，二阶惯性系统
    - SO_DT: 二阶振荡+滞后，占比15%，振荡系统
    """
    FOPDT = "fopdt"                    # K/(Ts+1)*e^(-Ls) - 一阶滞后
    FIRST_ORDER = "first_order"        # K/(Ts+1) - 纯一阶惯性（无滞后）
    IDT = "integral_delay"             # K/s*e^(-Ls) - 积分+滞后
    SOPDT = "sopdt"                    # K/((T1s+1)(T2s+1))*e^(-Ls) - 二阶滞后
    SO_DT = "so_dt"                    # K/(T²s²+2ζTs+1)*e^(-Ls) - 二阶振荡+滞后
    FOPDT_HEAT_LOSS = "fopdt_with_heat_loss"  # 带热损失的FOPDT
    SECOND_ORDER = "second_order"      # 二阶模型（无滞后）


class Config:
    """系统配置类：包含所有配置参数和边界值"""
    EPSILON = 1e-9
    DEFAULT_LOG_LEVEL = "INFO"
    
    # PID参数边界
    PB_MIN = 10.0
    PB_MAX = 200.0
    TI_MIN = 1.0
    TI_MAX = 200.0
    TD_MIN = 0.0
    TD_MAX = 50.0

    # 稳态判断标准（统一配置）
    STEADY_STATE_STRICT = {
        'tol': 0.3,           # 严格容差
        'std_tol': 0.15,      # 严格标准差阈值
        'min_len': 20         # 最小数据长度
    }
    
    STEADY_STATE_NORMAL = {
        'tol': 0.5,           # 正常容差
        'std_tol': 0.3,       # 正常标准差阈值
        'min_len': 20         # 最小数据长度
    }
    
    STEADY_STATE_LOOSE = {
        'tol': 1.0,           # 宽松容差
        'std_tol': 0.5,       # 宽松标准差阈值
        'min_len': 20         # 最小数据长度
    }
    
    # 数据质量标准
    DATA_QUALITY_REQUIREMENTS = {
        'min_length': 100,              # 最小数据长度
        'min_pv_std': 0.1,              # PV最小标准差（检测是否有变化）
        'min_mv_std': 0.1,              # MV最小标准差
        'min_snr': 3.0,                 # 最小信噪比
        'max_missing_ratio': 0.05,      # 最大缺失数据比例（5%）
        'max_sampling_jitter': 0.2      # 最大采样抖动比例（20%）
    }
    
    # 振荡检测阈值
    OSCILLATION_THRESHOLDS = {
        'absolute_range': 2.0,          # 绝对振荡幅度阈值
        'relative_range_ratio': 0.15,   # 相对振荡幅度比例（15%设定值）
        'std_threshold': 0.8            # 标准差阈值
    }
    
    # 参数合理性验证标准
    PARAMETER_VALIDATION = {
        'pb_range': (5.0, 300.0),       # Pb合理范围
        'ti_range': (0.0, 300.0),       # Ti合理范围
        'td_range': (0.0, 100.0),       # Td合理范围
        'pb_ti_ratio_range': (0.05, 10.0),  # Pb/Ti合理比例范围
        'ti_td_ratio_range': (1.0, 50.0),   # Ti/Td合理比例范围
        'min_score_threshold': 50.0     # 最低可接受评分
    }

    # 模型参数边界配置（用于优化和限幅）
    MODEL_BOUNDS = {
        # FOPDT: K/(Ts+1)*e^(-Ls) - 一阶滞后（占比40%）
        'fopdt': {
            'initial': ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0]),
            'retry': ([0.01, 1.0, 0.0], [2.0, 300.0, 30.0]),
            'clip': [(0.05, 1.5), (5.0, 150.0), (0.0, 20.0)]
        },
        # 纯一阶惯性: K/(Ts+1) - 无滞后（占比10%，适合压力控制）
        'first_order': {
            'initial': ([0.05, 5.0], [2.0, 150.0]),  # K, T
            'retry': ([0.01, 1.0], [3.0, 300.0]),
            'clip': [(0.05, 2.0), (5.0, 150.0)]
        },
        # 二阶模型（无滞后）: K/((T1s+1)(T2s+1))
        'second_order': {
            'initial': ([0.05, 1.0, 1.0], [2.0, 200.0, 200.0]),
            'retry': ([0.01, 0.5, 0.5], [3.0, 500.0, 500.0]),
            'clip': [(0.05, 2.0), (1.0, 200.0), (1.0, 200.0)]
        },
        # SOPDT: K/((T1s+1)(T2s+1))*e^(-Ls) - 二阶滞后（占比15%）
        'sopdt': {
            'initial': ([0.05, 1.0, 1.0, 0.0], [2.0, 150.0, 150.0, 20.0]),  # K, T1, T2, L
            'retry': ([0.01, 0.5, 0.5, 0.0], [3.0, 300.0, 300.0, 30.0]),
            'clip': [(0.05, 2.0), (1.0, 150.0), (1.0, 150.0), (0.0, 20.0)]
        },
        # SO+DT: K/(T²s²+2ζTs+1)*e^(-Ls) - 二阶振荡+滞后（占比15%）
        'so_dt': {
            'initial': ([0.05, 5.0, 0.1, 0.0], [2.0, 150.0, 2.0, 20.0]),  # K, T, zeta, L
            'retry': ([0.01, 1.0, 0.05, 0.0], [3.0, 300.0, 3.0, 30.0]),
            'clip': [(0.05, 2.0), (5.0, 150.0), (0.1, 2.0), (0.0, 20.0)]
        },
        # FOPDT带热损失（石油温控）
        'fopdt_with_heat_loss': {
            'initial': ([0.05, 5.0, 0.0, 0.0], [1.5, 300.0, 30.0, 0.5]),
            'retry': ([0.01, 1.0, 0.0, 0.0], [2.0, 500.0, 50.0, 1.0]),
            'clip': [(0.05, 1.5), (5.0, 300.0), (0.0, 30.0), (0.0, 0.5)]
        },
        # IDT: K/s*e^(-Ls) - 积分延迟（占比15%，适合液位控制）
        'integral_delay': {
            'initial': ([0.001, 0.0], [1.0, 5.0]),
            'retry': ([0.001, 0.0], [1.0, 5.0]),
            'clip': [(0.001, 1.0), (0.0, 5.0)]
        }
    }

