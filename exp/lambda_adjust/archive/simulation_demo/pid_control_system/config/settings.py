import os
import sys

# 支持作为脚本直接运行和作为包导入
try:
    from .enums import Mode, PIDMode, DisturbanceType, NoiseReductionLevel, TuningMethod
except ImportError:
    # 相对导入失败时，使用绝对导入
    from enums import Mode, PIDMode, DisturbanceType, NoiseReductionLevel, TuningMethod

class Config:

    """系统配置参数集中管理"""

    # 温度参数

    INIT_TEMPERATURE = 0

    TARGET_TEMPERATURE = 5

    TARGET_FLOW = 5  # 新增：目标流量



    # 稳态判断参数

    STABILIZATION_THRESHOLD = 0.8  # 温度波动允许阈值(℃)

    STABILIZATION_WINDOW = 50  # 稳态判断窗口大小



    # 扰动配置

    DISTURBANCE_TYPES = [

        {"type": DisturbanceType.OVERSHOOT, "description": "超调量大"},

        {"type": DisturbanceType.STEADY_ERROR, "description": "稳态误差变大"},

        {"type": DisturbanceType.SLOW_RECOVERY, "description": "恢复时间延长"},

        {"type": DisturbanceType.VALVE_STICTION, "description": "阀门卡涩"},

        {"type": DisturbanceType.SENSOR_DRIFT, "description": "传感器漂移"},

        {"type": DisturbanceType.HEAT_LOSS, "description": "热损失增加"},

        {"type": DisturbanceType.CONTROL_VALVE_WEAR, "description": "控制阀磨损"},

        {"type": DisturbanceType.THERMAL_INERTIA, "description": "热惯性变化"},

        {"type": DisturbanceType.FLOW_NOISE, "description": "流量噪声增大"},  # 新增

        {"type": DisturbanceType.FLOW_STICTION, "description": "流量阀门卡涩"}  # 新增

    ]



    # 系统老化与辨识参数

    AGING_START_TIME = 300  # 老化开始时间(s)

    IDENTIFY_WINDOW = 200  # 参数辨识窗口大小(点数)

    PARAM_UPDATE_SMOOTH_FACTOR = 0.3  # 参数更新平滑因子



    # 扰动检测相关参数 - 优化后

    DETECTION_WINDOW = 60  # 扰动检测窗口大小

    ERROR_THRESHOLD = 1.5  # 误差阈值

    STD_THRESHOLD = 1.2  # 标准差阈值

    SLOPE_THRESHOLD = 0.05  # 温度变化率阈值

    VALVE_CHANGE_THRESHOLD = 25  # 阀门变化阈值

    CORRELATION_THRESHOLD = 0.3  # 相关性阈值



    # 自适应检测参数

    ADAPTIVE_DETECTION_ENABLED = True  # 是否启用自适应检测

    MIN_DETECTION_WINDOW = 30  # 最小检测窗口

    MAX_DETECTION_WINDOW = 120  # 最大检测窗口

    DETECTION_SENSITIVITY = 0.8  # 检测敏感度（0-1，越小越敏感）



    # 仿真与存储参数

    DATA_SAVE_DIR = "../data_simulation/data_generation"  # 数据保存目录

    PLOT_REFRESH_INTERVAL = 20  # 绘图刷新间隔(步)



    # 模式配置

    MODES = {

        Mode.STANDARD: "标准模式",

        Mode.ANTI_DISTURBANCE: "抗扰动模式",

        Mode.ANTI_NOISE: "抗噪声模式",

        Mode.FLOW_CONTROL: "流量控制模式"  # 新增

    }



    # 低通滤波参数

    FILTER_ORDER = 3  # 滤波器阶数

    FILTER_CUTOFF_FREQ = 0.05  # 截止频率（相对于采样频率的比例）

    FILTER_APPLY_TO_INPUT = True  # 是否对输入信号也应用滤波

    NOISE_REDUCTION_LEVELS = {

        NoiseReductionLevel.LOW: {"cutoff_freq": 0.08, "order": 2},  # 低强度降噪

        NoiseReductionLevel.MEDIUM: {"cutoff_freq": 0.05, "order": 3},  # 中等强度降噪

        NoiseReductionLevel.HIGH: {"cutoff_freq": 0.03, "order": 4}  # 高强度降噪

    }



    # PID模式选择

    PID_MODES = {

        PIDMode.STANDARD: "标准PID模式",

        PIDMode.DERIVATIVE_ON_MEASUREMENT: "微分先行模式",

        PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT: "比例微分先行模式"

    }



    # PID参数边界

    PB_MIN = 10.0

    PB_MAX = 200.0

    TI_MIN = 1.0

    TI_MAX = 200.0

    TD_MIN = 0.0

    TD_MAX = 50.0



    # 控制输出边界

    MV_MIN = 0.0

    MV_MAX = 100.0



    # 扰动处理模式因子配置（优化：避免重复的if-elif判断）

    DISTURBANCE_MODE_FACTORS = {

        Mode.STANDARD: 1.0,

        Mode.ANTI_DISTURBANCE: 0.7,

        Mode.ANTI_NOISE: 0.8,

        Mode.FLOW_CONTROL: 0.6  # 默认值，某些扰动类型会覆盖

    }

    

    # 特定扰动类型的模式因子（覆盖默认值）

    DISTURBANCE_SPECIFIC_FACTORS = {

        DisturbanceType.OVERSHOOT: {Mode.FLOW_CONTROL: 0.5},

        DisturbanceType.SLOW_RECOVERY: {Mode.FLOW_CONTROL: 0.5},

        DisturbanceType.VALVE_STICTION: {Mode.FLOW_CONTROL: 0.4},

        DisturbanceType.THERMAL_INERTIA: {Mode.FLOW_CONTROL: 0.7}

    }

    

    # 数值精度阈值

    EPSILON = 1e-6

    

    # 扰动调整策略配置字典（优化：替代重复的if-elif链）

    DISTURBANCE_ADJUSTMENT_STRATEGIES = {

        DisturbanceType.OVERSHOOT: {'pb': 1.1, 'ti': 1.0, 'td': 1.0, 'description': '超调优化'},

        DisturbanceType.STEADY_ERROR: {'pb': 1.0, 'ti': 0.8, 'td': 1.0, 'description': '稳态误差优化'},

        DisturbanceType.SLOW_RECOVERY: {'pb': 0.9, 'ti': 1.0, 'td': 1.1, 'description': '恢复优化'},

        DisturbanceType.VALVE_STICTION: {'pb': 1.15, 'ti': 1.2, 'td': 1.0, 'description': '阀门卡涩优化'},

        DisturbanceType.SENSOR_DRIFT: {'pb': 1.0, 'ti': 1.0, 'td': 1.3, 'description': '传感器漂移优化'},

        DisturbanceType.HEAT_LOSS: {'pb': 0.85, 'ti': 0.85, 'td': 1.0, 'description': '热损失优化'},

        DisturbanceType.CONTROL_VALVE_WEAR: {'pb': 1.2, 'ti': 1.0, 'td': 0.9, 'description': '控制阀磨损优化'},

        DisturbanceType.THERMAL_INERTIA: {'pb': 1.0, 'ti': 1.2, 'td': 1.2, 'description': '热惯性优化'},

        DisturbanceType.FLOW_NOISE: {'pb': 1.0, 'ti': 1.0, 'td': 0.0, 'description': '流量噪声优化'},

        DisturbanceType.FLOW_STICTION: {'pb': 1.2, 'ti': 1.2, 'td': 0.0, 'description': '流量卡涩优化'},

    }



    @classmethod

    def ensure_data_dir(cls):

        """确保数据目录存在"""

        os.makedirs(cls.DATA_SAVE_DIR, exist_ok=True)

    

    @classmethod

    def get_mode_factor(cls, mode, disturbance_type=None):

        """获取模式因子，优化重复判断逻辑"""

        if disturbance_type and disturbance_type in cls.DISTURBANCE_SPECIFIC_FACTORS:

            specific_factors = cls.DISTURBANCE_SPECIFIC_FACTORS[disturbance_type]

            if mode in specific_factors:

                return specific_factors[mode]

        return cls.DISTURBANCE_MODE_FACTORS.get(mode, 1.0)





Config.TUNING_METHODS = {

    TuningMethod.LAMBDA: "Lambda整定法",

    TuningMethod.COHEN_COON: "Cohen-Coon整定法"

}





# ----数据处理模块----
