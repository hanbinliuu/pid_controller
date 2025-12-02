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
        'fopdt': {
            'initial': ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0]),
            'retry': ([0.01, 1.0, 0.0], [2.0, 300.0, 30.0]),
            'clip': [(0.05, 1.5), (5.0, 150.0), (0.0, 20.0)]
        },
        'second_order': {
            'initial': ([0.05, 1.0, 1.0], [2.0, 200.0, 200.0]),
            'retry': ([0.01, 0.5, 0.5], [3.0, 500.0, 500.0]),
            'clip': [(0.05, 2.0), (1.0, 200.0), (1.0, 200.0)]
        },
        'fopdt_with_heat_loss': {
            'initial': ([0.05, 5.0, 0.0, 0.0], [1.5, 300.0, 30.0, 0.5]),
            'retry': ([0.01, 1.0, 0.0, 0.0], [2.0, 500.0, 50.0, 1.0]),
            'clip': [(0.05, 1.5), (5.0, 300.0), (0.0, 30.0), (0.0, 0.5)]
        },
        'integral_delay': {
            'initial': ([0.001, 0.0], [1.0, 5.0]),
            'retry': ([0.001, 0.0], [1.0, 5.0]),
            'clip': [(0.001, 1.0), (0.0, 5.0)]
        }
    }

