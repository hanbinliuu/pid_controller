"""
Backend Configuration File
所有硬编码的配置参数集中管理
"""
import os
from pathlib import Path


class ServerConfig:
    """服务器配置"""
    # FastAPI配置
    TITLE = "PID Tuning Interface"
    VERSION = "2.0.3"
    
    # CORS配置
    CORS_ALLOW_ORIGINS = ["*"]
    CORS_ALLOW_CREDENTIALS = True
    CORS_ALLOW_METHODS = ["*"]
    CORS_ALLOW_HEADERS = ["*"]


class AIConfig:
    """AI配置"""
    # 从环境变量读取，提供默认值
    API_KEY = os.getenv("OPENAI_API_KEY", "")
    API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    MODEL = os.getenv("OPENAI_MODEL", os.getenv("AI_MODEL", "gpt-3.5-turbo"))


class TuningConfig:
    """整定配置"""
    # 默认整定方法
    DEFAULT_TUNING_METHOD = "LAMBDA"
    DEFAULT_CONTROL_MODE = "STANDARD"
    DEFAULT_ENABLE_SEGMENTATION = True
    
    # 时间处理
    MIN_TIME_RANGE = 1.0  # 最小时间范围（秒）
    TIME_UNIT_THRESHOLD = 1000.0  # 毫秒转秒的阈值
    DEFAULT_SAMPLING_INTERVAL = 2.0  # 默认采样间隔（秒）
    
    # 稳态检测
    STEADY_TOLERANCE = 0.3  # 稳态容差
    STEADY_STD_TOLERANCE = 0.15  # 稳态标准差容差
    STEADY_MIN_LENGTH = 20  # 最小稳态长度
    INITIAL_STEADY_LENGTH = 100  # 初始稳态段长度
    INITIAL_STEADY_MIN_LENGTH = 30  # 初始稳态最小长度
    
    # 参数更新点计算
    PARAM_UPDATE_DEFAULT_RATIO = 0.333  # 默认参数更新点位置（数据的1/3处）
    STEADY_WINDOW_SIZE = 50  # 稳态窗口大小
    STEADY_WINDOW_STEP = 25  # 稳态窗口步长（window_size // 2）
    
    # 设定值分段
    MIN_SETPOINT_CHANGE = 0.5  # 最小设定值变化
    MIN_STABLE_POINTS = 20  # 最小稳定点数
    
    # SV处理
    SV_VARIATION_THRESHOLD = 0.15  # SV变化率阈值（15%）


class ModelConfig:
    """模型配置"""
    # 模型类型
    FOPDT = 'fopdt'
    SECOND_ORDER = 'second_order'
    FOPDT_WITH_HEAT_LOSS = 'fopdt_with_heat_loss'
    INTEGRAL_DELAY = 'integral_delay'
    
    # 模型参数限制
    MIN_DELAY = 0.1  # 最小延迟
    MIN_INTEGRAL_DELAY = 1.0  # 积分模型最小延迟
    MAX_INTEGRAL_DELAY = 300.0  # 积分模型最大延迟
    MIN_INTEGRAL_PB = 20.0  # 积分模型最小比例带
    MAX_INTEGRAL_PB = 200.0  # 积分模型最大比例带
    MIN_INTEGRAL_TI = 30.0  # 积分模型最小积分时间
    MAX_INTEGRAL_TI = 300.0  # 积分模型最大积分时间
    
    # 拟合误差估算系数
    FOPDT_FIT_ERROR_COEF = 0.05  # FOPDT拟合误差系数
    FOPDT_FIT_RMSE_COEF = 0.08
    SECOND_ORDER_FIT_ERROR_COEF = 0.08
    SECOND_ORDER_FIT_RMSE_COEF = 0.12
    INTEGRAL_DELAY_FIT_ERROR_COEF = 0.03
    INTEGRAL_DELAY_FIT_RMSE_COEF = 0.05
    DEFAULT_FIT_ERROR_COEF = 0.1
    DEFAULT_FIT_RMSE_COEF = 0.15
    
    # 默认拟合误差
    DEFAULT_FIT_ERROR = 0.001
    DEFAULT_FIT_RMSE = 0.001


class SimulationConfig:
    """仿真配置"""
    # 仿真参数
    DEFAULT_INITIAL_PV = 0.0
    DEFAULT_INITIAL_MV = 50.0
    
    # 数据限制
    MAX_DATA_POINTS = 10000  # 最大数据点数


class OPCUAConfig:
    """OPC UA配置"""
    # 运行模式
    MODE_SIMULATION = 'simulation'
    MODE_PRODUCTION = 'production'
    DEFAULT_MODE = MODE_PRODUCTION
    
    # 连接配置
    DEFAULT_SECURITY_STRING = "None"
    
    # 采集配置
    DEFAULT_COLLECTION_INTERVAL_MS = 1000  # 默认采样间隔（毫秒）
    DEFAULT_COLLECTION_DURATION_SECONDS = 60  # 默认采集时长（秒）
    MAX_COLLECTION_DATA_POINTS = 1000  # 最大保留数据点数
    
    # 节点浏览
    DEFAULT_BROWSE_NODE_ID = "i=85"  # Objects文件夹
    DEFAULT_MAX_BROWSE_DEPTH = 1
    
    # 状态节点
    DEFAULT_STATE_NODE_ID = "ns=2;i=1010"  # 默认状态节点ID
    
    # 扰动计数器节点
    DEFAULT_DISTURB_COUNTER_NODE_ID = "ns=2;i=1020"  # 默认扰动计数器节点ID

class AutoTuningConfig:
    """自动整定系统配置"""
    # 监控配置
    CHECK_INTERVAL = 1  # 检测间隔（秒）
    BUFFER_SIZE = 60  # 数据缓冲区大小
    
    # 稳态检测阈值
    STEADY_TOLERANCE = 1.0  # 稳态容差
    STEADY_STD_TOLERANCE = 0.5  # 稳态标准差容差
    
    # 扰动检测
    DISTURBANCE_THRESHOLD = 3  # 连续N次检测到非稳态才触发
    STABILIZATION_WINDOW = 15  # 初始观察期（秒）- 缩短为15秒
    MAX_TUNING_DURATION = 120  # 最大整定时长（秒）
    MIN_OBSERVATION_TIME = 10  # 最小观察时间（秒）
    MAX_STABILIZING_DURATION = 180  # 最大稳定期时间（秒）
    
    # 数据采集
    MIN_NEW_DATA_POINTS = 100  # 最小新数据点数
    DATA_POINTS_TO_USE = 100  # 整定使用的数据点数
    DATA_LIMIT_DISTURBANCE = 150  # 扰动状态数据限制
    MIN_DISTURB_DATA_POINTS = 100  # 开始整定前需要的最小扰动数据点数
    
    # 参数差异阈值
    PARAM_IDENTICAL_THRESHOLD = 0.01  # 参数相同的判断阈值
    PARAM_IMPROVEMENT_THRESHOLD = 0.05  # 参数改善阈值（5%）
    
    # 状态锁定机制
    UNSTEADY_LOCK_ENABLED = True  # 启用非稳态锁定机制
    MIN_STABLE_DURATION = 20  # 最小稳定持续时间（秒）- 缩短为20秒
    
    # 动态稳定检测
    FAST_STABLE_ERROR_THRESHOLD = 0.5  # 快速稳定误差阈值（%）
    FAST_STABLE_DURATION = 10  # 快速稳定持续时间（秒）


class PerformanceConfig:
    """性能监控配置"""
    # 更新间隔
    UPDATE_INTERVAL = 10  # 每10秒更新一次
    
    # 数据要求
    MIN_DATA_POINTS = 20  # 最小数据点数
    PERFORMANCE_DATA_LIMIT = 100  # 性能计算数据限制
    
    # 等级映射
    GRADE_MAP = {
        'A': '优秀',
        'B': '良好',
        'C': '中等',
        'D': '及格',
        'F': '较差'
    }


class StabilityConfig:
    """稳定性监控配置（从stability_config.py迁移）"""
    # 稳定性阈值
    THRESHOLDS = {
        'steady_state_error': 0.02,  # 稳态误差阈值
        'oscillation_amplitude': 0.05,  # 振荡幅度阈值
        'control_effort': 80.0,  # 控制努力阈值
        'iae': 100.0,  # IAE阈值
    }
    
    # 监控配置
    MONITORING = {
        'check_interval': 5,  # 检查间隔（秒）
        'min_data_points': 30,  # 最小数据点数
        'alert_threshold': 3,  # 连续N次超阈值才报警
    }


class PathConfig:
    """路径配置"""
    # 项目根目录
    PROJECT_ROOT = Path(__file__).parent.parent
    
    # 数据目录
    DATA_DIR = PROJECT_ROOT / "data"
    LOGS_DIR = PROJECT_ROOT / "logs"
    
    # 确保目录存在
    DATA_DIR.mkdir(exist_ok=True)
    LOGS_DIR.mkdir(exist_ok=True)


class LoggingConfig:
    """日志配置"""
    # 日志级别
    LEVEL = os.getenv("LOG_LEVEL", "INFO")
    
    # 日志格式
    FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    
    # 日志文件
    LOG_FILE = PathConfig.LOGS_DIR / "app.log"
    MAX_BYTES = 10 * 1024 * 1024  # 10MB
    BACKUP_COUNT = 5


# 导出所有配置类
__all__ = [
    'ServerConfig',
    'AIConfig',
    'TuningConfig',
    'ModelConfig',
    'SimulationConfig',
    'OPCUAConfig',
    'AutoTuningConfig',
    'PerformanceConfig',
    'StabilityConfig',
    'PathConfig',
    'LoggingConfig',
]
