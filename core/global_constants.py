#!/usr/bin/env python3
"""
全局通用常量定义
汇总项目中所有的全局常量和配置变量，方便统一管理和引用
"""

# ==================== 配置导入 ====================
from core.config import Config

# ==================== PID控制字段映射 ====================
# 默认PID控制字段与模型browse_name名称映射关系（从配置文件加载）
DEFAULT_PID_POINT_MAP = Config.get_pid_point_map()

# IoTDA字段映射（测点名称）
DEFAULT_FIELD_MAPPING = {
    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
    "pv": "ns=100;s=FIC101A_PV.In_Channel0",
    "sv": "ns=100;s=FIC101A_SV.In_Channel0",
    "pb": "ns=100;s=FIC101A_PB.In_Channel0",
    "ti": "ns=100;s=FIC101A_TI.In_Channel0",
    "td": "ns=100;s=FIC101A_TD.In_Channel0"
}

# ==================== BFF模型查询API路径 ====================
BFF_API_PATHS = {
    'QUERY_VALUE_BY_BROWSE_PATH': '/bff/aggquery/v2/model/queryValueByBrowsePath',
    'QUERY_CURRENT_RAW_VALUE': '/bff/aggquery/v2/query/v2/queryCurrentRawValueByBrowsePath',
    'LIST_INSTANCE_UNDER_TREE': '/bff/v2/instance/listInstanceUnderInstanceTree',
    'GET_NEXT_LEVEL_SUBMODEL': '/bff/v2/model/getNextLevelSubModel',
    'QUERY_NODES_BY_URIS': '/bff/aggquery/v2/model/queryNodesByUris',
    'QUERY_INSTANCE_TREE': '/bff/v2/instance/queryInstanceTree',
    'SEARCH_BY_MODELS': '/bff/v2/instance/searchByModels'
}

# ==================== 模型树加载配置 ====================
# 单回路模型URI
MODEL_IDENTIFIER_LIST = [Config.BFF_MODEL_LOOP_MODEL_URI]
# 从根节点开始
START_IDENTIFIER_LIST = [Config.BFF_MODEL_ROOT_URI]

# ==================== 控制系统模式配置 ====================
# PID控制模式
PID_MODES = {
    "standard": "标准PID模式",
    "derivative_on_measurement": "微分先行模式",
    "proportional_derivative_on_measurement": "比例微分先行模式"
}

# 系统运行模式
SYSTEM_MODES = {
    "standard": "标准模式",
    "anti_disturbance": "抗扰动模式",
    "anti_noise": "抗噪声模式"
}

# ==================== 噪声降噪级别配置 ====================
NOISE_REDUCTION_LEVELS = {
    "low": {"cutoff_freq": 0.08, "order": 2},      # 低强度降噪
    "medium": {"cutoff_freq": 0.05, "order": 3},   # 中等强度降噪
    "high": {"cutoff_freq": 0.03, "order": 4}      # 高强度降噪
}

# ==================== 默认数值参数 ====================
# 默认比例系数
DEFAULT_KP = 1.0
# 默认积分系数
DEFAULT_KI = 0.1
# 默认微分系数
DEFAULT_KD = 0.05
# 默认控制周期（秒）
DEFAULT_CONTROL_PERIOD = 1.0
# 默认目标温度（℃）
DEFAULT_TARGET_TEMPERATURE = 400.0
# 默认初始温度（℃）
DEFAULT_INIT_TEMPERATURE = 380.0

# ==================== 时间窗口配置 ====================
# 默认窗口大小（分钟）
DEFAULT_WINDOW_SIZE = 120
# 默认步长（分钟）
DEFAULT_STEP_SIZE = 10
# 默认插值采样间隔（秒）
DEFAULT_WINDOW_SEC = 60
# 默认数据查询限制（条）
DEFAULT_QUERY_LIMIT = 1500

# ==================== 稳态检测参数 ====================
# 温度波动允许阈值（℃）
STABILIZATION_THRESHOLD = 0.8
# 稳态判断窗口大小
STABILIZATION_WINDOW = 50
# 扰动检测窗口大小
DETECTION_WINDOW = 60
# 误差阈值
ERROR_THRESHOLD = 1.5
# 标准差阈值
STD_THRESHOLD = 1.2
# 温度变化率阈值
SLOPE_THRESHOLD = 0.05
# 阀门变化阈值
VALVE_CHANGE_THRESHOLD = 25
# 相关性阈值
CORRELATION_THRESHOLD = 0.3

# ==================== 滞波器参数 ====================
# 滞波器阶数
FILTER_ORDER = 3
# 截止频率（相对于采样频率的比例）
FILTER_CUTOFF_FREQ = 0.05
# 是否对输入信号也应用滞波
FILTER_APPLY_TO_INPUT = True

# ==================== 回路优化阈值配置 ====================
# 性能分数阈值（低于此值认为需要优化）
LOOP_PERFORMANCE_THRESHOLD = Config.LOOP_PERFORMANCE_THRESHOLD
# 稳定率阈值（低于此值认为需要优化）
LOOP_STABILITY_THRESHOLD = Config.LOOP_STABILITY_THRESHOLD
# 自控率阈值（高于此值认为是自控回路）
LOOP_AUTO_CONTROL_THRESHOLD = Config.LOOP_AUTO_CONTROL_THRESHOLD
# 平稳率阈值（高于此值认为是平稳回路）
LOOP_STABLE_THRESHOLD = Config.LOOP_STABLE_THRESHOLD

# ==================== 仿真参数 ====================
# 仿真总时长（秒）
SIMULATION_DURATION = 10000
# 绘图刷新间隔（步）
PLOT_REFRESH_INTERVAL = 20
# 老化开始时间（秒）
AGING_START_TIME = 300
# 参数辨识窗口大小（点数）
IDENTIFY_WINDOW = 200
# 参数更新平滑因子
PARAM_UPDATE_SMOOTH_FACTOR = 0.2

# ==================== HTTP状态码 ====================
HTTP_STATUS_OK = 200
HTTP_STATUS_BAD_REQUEST = 400
HTTP_STATUS_UNAUTHORIZED = 401
HTTP_STATUS_NOT_FOUND = 404
HTTP_STATUS_INTERNAL_ERROR = 500

# ==================== 响应模式 ====================
RESPONSE_MODE_BLOCKING = "blocking"
RESPONSE_MODE_STREAMING = "streaming"

# ==================== 整定模式 ====================
TUNING_MODE_AUTO = "auto"
TUNING_MODE_MANUAL = "manual"

# ==================== 扰动类型 ====================
DISTURBANCE_TYPES = [
    {"type": "overshoot", "description": "超调量大"},
    {"type": "steady_error", "description": "稳态误差变大"},
    {"type": "slow_recovery", "description": "恢复时间延长"},
    {"type": "valve_stiction", "description": "阀门卡涩"},
    {"type": "sensor_drift", "description": "传感器漂移"},
    {"type": "heat_loss", "description": "热损失增加"},
    {"type": "control_valve_wear", "description": "控制阀磨损"},
    {"type": "thermal_inertia", "description": "热惯性变化"}
]

# ==================== 导出所有常量 ====================
__all__ = [
    # 配置
    'Config',
    
    # PID字段映射
    'DEFAULT_PID_POINT_MAP',
    'DEFAULT_FIELD_MAPPING',
    
    # BFF API路径
    'BFF_API_PATHS',
    
    # 模型树配置
    'MODEL_IDENTIFIER_LIST',
    'START_IDENTIFIER_LIST',
    
    # 模式配置
    'PID_MODES',
    'SYSTEM_MODES',
    'NOISE_REDUCTION_LEVELS',
    
    # 默认数值参数
    'DEFAULT_KP',
    'DEFAULT_KI',
    'DEFAULT_KD',
    'DEFAULT_CONTROL_PERIOD',
    'DEFAULT_TARGET_TEMPERATURE',
    'DEFAULT_INIT_TEMPERATURE',
    
    # 时间窗口配置
    'DEFAULT_WINDOW_SIZE',
    'DEFAULT_STEP_SIZE',
    'DEFAULT_WINDOW_SEC',
    'DEFAULT_QUERY_LIMIT',
    
    # 稳态检测参数
    'STABILIZATION_THRESHOLD',
    'STABILIZATION_WINDOW',
    'DETECTION_WINDOW',
    'ERROR_THRESHOLD',
    'STD_THRESHOLD',
    'SLOPE_THRESHOLD',
    'VALVE_CHANGE_THRESHOLD',
    'CORRELATION_THRESHOLD',
    
    # 滞波器参数
    'FILTER_ORDER',
    'FILTER_CUTOFF_FREQ',
    'FILTER_APPLY_TO_INPUT',
        
    # 回路优化阈值
    'LOOP_PERFORMANCE_THRESHOLD',
    'LOOP_STABILITY_THRESHOLD',
    'LOOP_AUTO_CONTROL_THRESHOLD',
    'LOOP_STABLE_THRESHOLD',
    
    # 仿真参数
    'SIMULATION_DURATION',
    'PLOT_REFRESH_INTERVAL',
    'AGING_START_TIME',
    'IDENTIFY_WINDOW',
    'PARAM_UPDATE_SMOOTH_FACTOR',
    
    # HTTP状态码
    'HTTP_STATUS_OK',
    'HTTP_STATUS_BAD_REQUEST',
    'HTTP_STATUS_UNAUTHORIZED',
    'HTTP_STATUS_NOT_FOUND',
    'HTTP_STATUS_INTERNAL_ERROR',
    
    # 响应模式
    'RESPONSE_MODE_BLOCKING',
    'RESPONSE_MODE_STREAMING',
    
    # 整定模式
    'TUNING_MODE_AUTO',
    'TUNING_MODE_MANUAL',
    
    # 扰动类型
    'DISTURBANCE_TYPES'
]
