from collections import deque
from datetime import datetime
from enum import Enum
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
import numpy as np
from scipy import signal
from scipy.optimize import least_squares


# 流数据仿真+自识别扰动段+整定法可选+流量阀门模式可选


##### 更新：
#            1. 加入日志模块
#            2. 加入低通滤波，降噪强度选择
#            3. pid控制模块加入不同参数更新模式
#            4. 加入模式选择（标准模式、抗扰动模式、抗噪声模式）
#            5. 修改仿真数据为数据流形式
#            6. json读取数据+自动识别扰动段+更新新pid参数后的仿真段
#            7. 可视化加入不带pid整定的温度变化
#            8. 加入Cohen-Coon整定法,整定法可选
#            9. 异常扰动段检测方法优化
#            10. 优化json数据读取三种case:
#                    情况 1：全新启动，无有效历史 PID，全程非稳态
#                    情况 2：已稳态运行 → 出现扰动 → 需重新整定
#                    情况 3：已有可用 PID，从初始温升到目标温，之后可能扰动（扰动后需要更新）
#            11. 新增FLOW_CONTROL模式，针对水阀流量控制优化
#            12. 将控制模式选择移到json数据读取阶段
#            13. 优化PID控制平滑性，特别是在流量控制模式下
#            14. 在仿真模式下加入流量控制仿真选项
#            15. 优化扰动生成算法，避免无限循环
#            16. 增加了手动调整参数后，如果50秒后仍检测到扰动，说明参数不合适，需要重新整定
#            17. 增加pid控制评分体系（稳态后+定时+扰动恢复后）



# ---log模块---
class LoggerSetup:
    """日志配置工具 - 按日期分割日志文件"""

    @staticmethod
    def setup_logger():
        # 创建日志目录
        log_dir = os.path.join(Config.DATA_SAVE_DIR, 'logs')
        os.makedirs(log_dir, exist_ok=True)

        # 创建logger实例
        logger = logging.getLogger('control_system')
        logger.setLevel(logging.INFO)

        # 清除已有的处理器，避免重复
        if logger.handlers:
            logger.handlers.clear()

        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)

        # 按日期分割的日志文件处理器
        log_file_path = os.path.join(log_dir, 'control_system.log')
        file_handler = TimedRotatingFileHandler(
            filename=log_file_path,
            when='midnight',  # 每天午夜分割
            interval=1,  # 每1天分割一次
            backupCount=30,  # 保留最近30天的日志
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

        # 添加日志轮转信息
        logger.info(f"日志系统已启动，日志将按日期分割保存到: {log_dir}")
        logger.info(f"当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        return logger


class Mode(str, Enum):
    """系统运行模式枚举"""
    STANDARD = "standard"
    ANTI_DISTURBANCE = "anti_disturbance"
    ANTI_NOISE = "anti_noise"
    FLOW_CONTROL = "flow_control"  # 新增：水阀流量控制模式


class PIDMode(str, Enum):
    """PID控制模式枚举"""
    STANDARD = "standard"
    DERIVATIVE_ON_MEASUREMENT = "derivative_on_measurement"
    PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT = "proportional_derivative_on_measurement"


# -----随机非稳态段生成------
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
    FLOW_NOISE = "flow_noise"  # 新增：流量噪声
    FLOW_STICTION = "flow_stiction"  # 新增：流量阀门卡涩


class DisturbanceGenerator:
    """扰动生成器：生成各种系统扰动"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode

    @staticmethod
    def generate_random_disturbances():
        """生成随机扰动配置 - 考虑更多失效场景，每次最多4种"""
        # 计算合理的扰动数量：根据时间范围和最小间隔动态调整
        time_start_min = 500
        time_start_max = 5000
        time_range = time_start_max - time_start_min  # 可用时间范围：4500秒
        min_separation = 800  # 最小间隔800秒
        max_duration = 250  # 最大持续时间
        
        # 计算理论最大扰动数量：每个扰动至少需要min_separation秒的间隔
        max_possible_disturbances = max(2, int(time_range / (min_separation + max_duration)))
        num_disturbances = min(5, len(Config.DISTURBANCE_TYPES), max_possible_disturbances)

        # 从所有可用的扰动类型中选择num_disturbances种
        available_types = Config.DISTURBANCE_TYPES.copy()
        selected_types = np.random.choice(available_types, size=num_disturbances, replace=False)

        # 优化：预先分配时间段，避免随机生成导致的冲突和无限循环
        # 将时间范围分成num_disturbances个区间，每个区间内随机选择时间点
        time_slots = []
        if num_disturbances > 1:
            slot_size = time_range / num_disturbances
            for i in range(num_disturbances):
                slot_start = time_start_min + i * slot_size
                slot_end = time_start_min + (i + 1) * slot_size - min_separation
                # 在每个区间内随机选择时间点，确保不超出边界
                time_start = np.random.randint(int(slot_start), int(min(slot_end, time_start_max - min_separation)))
                time_slots.append(time_start)
        else:
            time_slots.append(np.random.randint(time_start_min, time_start_max - min_separation))

        # 对时间点进行小幅随机调整，增加随机性（但保持最小间隔）
        time_slots = np.array(time_slots)
        for i in range(len(time_slots)):
            # 在保持最小间隔的前提下，允许小幅随机调整
            if i == 0:
                adjust_range = min(200, (time_slots[i+1] - time_slots[i] - min_separation) // 2) if len(time_slots) > 1 else 200
            elif i == len(time_slots) - 1:
                adjust_range = min(200, (time_slots[i] - time_slots[i-1] - min_separation) // 2)
            else:
                adjust_range = min(200, 
                                   (time_slots[i] - time_slots[i-1] - min_separation) // 2,
                                   (time_slots[i+1] - time_slots[i] - min_separation) // 2)
            if adjust_range > 0:
                time_slots[i] += np.random.randint(-adjust_range, adjust_range)
                time_slots[i] = np.clip(time_slots[i], time_start_min, time_start_max - min_separation)

        disturbances = []
        for i in range(num_disturbances):
            disturbance_type = selected_types[i]
            
            # 随机生成扰动参数
            duration = np.random.randint(80, 250)  # 持续时间 80-250s
            amplitude = np.random.uniform(1.2, 4.0)  # 幅值 1.2-4.0℃

            disturbance = {
                "time": int(time_slots[i]),
                "type": disturbance_type["type"],
                "duration": duration,
                "amplitude": amplitude,
                "description": disturbance_type["description"]
            }
            disturbances.append(disturbance)

        # 按时间排序
        disturbances.sort(key=lambda x: x["time"])

        return disturbances


class DisturbanceHandler:
    """扰动处理模块：管理各种系统扰动"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode
        self.disturbance_functions = {
            DisturbanceType.OVERSHOOT: self._apply_overshoot,
            DisturbanceType.STEADY_ERROR: self._apply_steady_error,
            DisturbanceType.SLOW_RECOVERY: self._apply_slow_recovery,
            DisturbanceType.VALVE_STICTION: self._apply_valve_stiction,
            DisturbanceType.SENSOR_DRIFT: self._apply_sensor_drift,
            DisturbanceType.HEAT_LOSS: self._apply_heat_loss,
            DisturbanceType.CONTROL_VALVE_WEAR: self._apply_control_valve_wear,
            DisturbanceType.THERMAL_INERTIA: self._apply_thermal_inertia,
            DisturbanceType.FLOW_NOISE: self._apply_flow_noise,  # 新增
            DisturbanceType.FLOW_STICTION: self._apply_flow_stiction  # 新增
        }

    def apply_disturbance(self, disturbance_type, time, current_var, valve_opening,
                          amplitude, duration, start_time, system_state):
        """应用扰动对变量的影响"""
        if disturbance_type in self.disturbance_functions:
            return self.disturbance_functions[disturbance_type](
                time, current_var, valve_opening, amplitude, duration, start_time, system_state
            )
        return current_var

    # 温控相关
    def _apply_overshoot(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        decay = 1 - (time - start_time) / duration
        # 根据模式调整扰动强度（优化：使用配置字典）
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.OVERSHOOT)
        return current_temp + amplitude * (1.2 - decay) * mode_factor + np.random.normal(0, 1.2)

    def _apply_steady_error(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.STEADY_ERROR)
        turbulent = np.sin((time - start_time) * 0.1) * amplitude * 0.3
        return current_temp + amplitude * mode_factor + turbulent + np.random.normal(0, 0.9)

    def _apply_slow_recovery(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.SLOW_RECOVERY)
        fluctuation = np.sin((time - start_time) * 0.2) * amplitude * 0.8
        return current_temp + fluctuation * mode_factor + np.random.normal(0, 1.3)

    def _apply_valve_stiction(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        system_state['valve_stiction_level'] = amplitude * 0.1
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.VALVE_STICTION)
        return current_temp + np.random.normal(0, amplitude * 0.3 * mode_factor)

    def _apply_sensor_drift(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        sensor_drift = amplitude * np.sin((time - start_time) * 0.01)
        system_state['sensor_drift'] = sensor_drift
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.SENSOR_DRIFT)
        return current_temp + sensor_drift + np.random.normal(0, 0.5 * mode_factor)

    def _apply_heat_loss(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        loss_factor = 1 - amplitude * 0.001 * (time - start_time) / duration
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.HEAT_LOSS)
        return current_temp * loss_factor + np.random.normal(0, 0.8 * mode_factor)

    def _apply_control_valve_wear(self, time, current_temp, valve_opening, amplitude, duration, start_time,
                                  system_state):
        wear_factor = 1 - amplitude * 0.0005 * (time - start_time) / duration
        system_state['K'] = system_state['initial_K'] * wear_factor
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.CONTROL_VALVE_WEAR)
        return current_temp + np.random.normal(0, 0.6 * mode_factor)

    def _apply_thermal_inertia(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        inertia_factor = 1 + amplitude * 0.001 * (time - start_time) / duration
        system_state['T'] = system_state['initial_T'] * inertia_factor
        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.THERMAL_INERTIA)
        return current_temp + np.random.normal(0, 0.7 * mode_factor)

    # 新增：流量相关扰动
    def _apply_flow_noise(self, time, current_flow, valve_opening, amplitude, duration, start_time, system_state):
        """流量噪声扰动"""
        noise_level = amplitude * 0.2
        return current_flow + np.random.normal(0, noise_level)

    def _apply_flow_stiction(self, time, current_flow, valve_opening, amplitude, duration, start_time, system_state):
        """流量阀门卡涩扰动"""
        stiction_level = amplitude * 0.1
        # 模拟阀门响应不灵敏
        effective_flow = current_flow * (1 - stiction_level) + system_state.get('last_flow',
                                                                                current_flow) * stiction_level
        system_state['last_flow'] = current_flow
        return effective_flow


class NoiseReductionLevel(str, Enum):
    """降噪强度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TuningMethod(str, Enum):
    """PID整定方法枚举"""
    LAMBDA = "lambda"
    COHEN_COON = "cohen-coon"


# ----config参数管理-----
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
    PLOT_REFRESH_INTERVAL = 5  # 绘图刷新间隔(步)

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
class DataHandler:
    """数据处理工具：读取、生成、选择数据源"""

    def __init__(self, logger=None):
        self.logger = logger or LoggerSetup.setup_logger()
        self.noise_reduction_level = NoiseReductionLevel.MEDIUM  # 默认降噪强度

    def apply_low_pass_filter(self, data, fs=1.0):
        """
        应用低通滤波器
        :param data: 输入数据数组
        :param fs: 采样频率 (默认为1Hz)
        :return: 滤波后的数据
        """
        params = Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]
        cutoff_freq = params["cutoff_freq"]
        order = params["order"]

        # 计算归一化截止频率
        nyquist_freq = 0.5 * fs
        normalized_cutoff = min(cutoff_freq / nyquist_freq, 0.99)  # 确保在合理范围内

        # 设计Butterworth低通滤波器
        b, a = signal.butter(order, normalized_cutoff, btype='low', analog=False)

        # 应用滤波器 (使用filtfilt避免相位延迟)
        return signal.filtfilt(b, a, data)

    def read_json_data(self, file_path):
        """读取JSON格式的温度数据，支持完整PID数据解析"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)

            if json_data.get("status") != "success":
                raise ValueError(f"JSON文件状态不是success: {json_data.get('status')}")

            if "data" not in json_data:
                raise ValueError("JSON文件缺少data字段")

            data_list = json_data["data"]
            if not data_list:
                raise ValueError("JSON文件data字段为空")

            # 解析数据 - 包含所有字段
            t, pv_data, mv_data, sv_data = [], [], [], []
            kp_data, ki_data, kd_data, pb_data, ti_data, td_data = [], [], [], [], [], []

            for item in data_list:
                timestamp = item.get("timestamp", 0)
                pv = item.get("pv", 0)  # 过程值，作为实际温度
                mv = item.get("mv", 0)  # 操纵变量
                sv_val = item.get("sv", Config.TARGET_TEMPERATURE)  # 设定值

                # PID参数
                kp = item.get("kp", 0)
                ki = item.get("ki", 0)
                kd = item.get("kd", 0)
                pb = item.get("pb", 100)
                ti = item.get("ti", 20)
                td = item.get("td", 0)

                # 转换时间戳（毫秒转秒）
                time_sec = timestamp / 1000.0
                t.append(time_sec)
                pv_data.append(pv)
                mv_data.append(mv)
                sv_data.append(sv_val)
                kp_data.append(kp)
                ki_data.append(ki)
                kd_data.append(kd)
                pb_data.append(pb)
                ti_data.append(ti)
                td_data.append(td)

            t = np.array(t)
            pv_data = np.array(pv_data)
            mv_data = np.array(mv_data)
            sv_data = np.array(sv_data)
            kp_data = np.array(kp_data)
            ki_data = np.array(ki_data)
            kd_data = np.array(kd_data)
            pb_data = np.array(pb_data)
            ti_data = np.array(ti_data)
            td_data = np.array(td_data)

            # 确保时间序列单调递增
            if not np.all(np.diff(t) >= 0):
                sorted_indices = np.argsort(t)
                t = t[sorted_indices]
                pv_data = pv_data[sorted_indices]
                mv_data = mv_data[sorted_indices]
                sv_data = sv_data[sorted_indices]
                kp_data = kp_data[sorted_indices]
                ki_data = ki_data[sorted_indices]
                kd_data = kd_data[sorted_indices]
                pb_data = pb_data[sorted_indices]
                ti_data = ti_data[sorted_indices]
                td_data = td_data[sorted_indices]

            # 应用低通滤波到温度数据
            pv_data = self.apply_low_pass_filter(pv_data)
            self.logger.info(
                f"对温度数据应用了低通滤波 (降噪强度: {self.noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]['cutoff_freq']})")

            # 对其他数据也应用滤波
            if mv_data is not None:
                mv_data = self.apply_low_pass_filter(mv_data)
            if sv_data is not None:
                sv_data = self.apply_low_pass_filter(sv_data)

            self.logger.info(f"成功读取JSON数据：{file_path}")
            self.logger.info(f"数据范围：{t.min():.0f}s ~ {t.max():.0f}s，共{len(t)}个点")
            self.logger.info(f"数据字段：时间、温度(pv)、操纵变量(mv)、设定值(sv)、PID参数")

            return t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data

        except FileNotFoundError:
            self.logger.error(f"未找到文件 '{file_path}'")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON解析失败：{str(e)}")
            raise
        except Exception as e:
            self.logger.error(f"读取失败：{str(e)}")
            raise

    def _generate_default_input_signal(self, t):
        """生成默认输入信号"""
        u = np.zeros_like(t, dtype=np.float64)
        # 分段阶梯输入
        u[t >= 50] += 25.0
        u[t >= 150] += 15.0
        u[t >= 250] -= 5.0
        u[t >= 350] += 20.0
        u[t >= 450] -= 10.0
        # 添加随机噪声并限制范围
        u += np.random.normal(0, 1.5, size=len(t))
        return np.clip(u, Config.MV_MIN, Config.MV_MAX)

    def _generate_flow_input_signal(self, t):
        """生成流量控制的默认输入信号（更平滑）"""
        u = np.zeros_like(t, dtype=np.float64)
        # 平滑的阶跃输入
        u[t >= 50] += 20.0
        u[t >= 150] += 10.0
        u[t >= 250] -= 5.0
        # 添加更多噪声模拟流量波动
        u += np.random.normal(0, 2.0, size=len(t))
        return np.clip(u, Config.MV_MIN, Config.MV_MAX)

    def choose_data_source(self, data_type="dynamic_response"):
        """选择数据来源（仿真生成或读取JSON）"""
        print(f"\n=== 选择{data_type}数据来源 ===")
        print("1. 自动生成非阶跃仿真数据（默认）")
        print("2. 读取外部JSON数据（支持完整PID数据）")

        while True:
            choice = input("请输入选择（1/2，直接回车选1）：").strip() or "1"
            if choice == "1":
                return np.array([]), None, None, None, None, None, None, None, None, None
            elif choice == "2":
                file_path = input(f"请输入{data_type}JSON路径（如'./data.json'）：").strip()
                if not file_path:
                    print("❌ 路径不能为空，请重新输入")
                    continue
                if not os.path.isfile(file_path):
                    print("❌ 文件不存在，请重新输入")
                    continue
                if not file_path.lower().endswith('.json'):
                    print("❌ 文件格式错误，必须是JSON文件，请重新输入")
                    continue
                t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.read_json_data(
                    file_path)
                return t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data
            else:
                print("❌ 输入错误，请选择1或2")

    def choose_mode(self, using_json_data=False, t=None, pv_data=None, mv_data=None):
        """
        自动检测场景并选择运行模式（不再需要用户手动选择）
        
        Args:
            using_json_data: 是否使用JSON数据
            t: 时间数据（用于场景检测）
            pv_data: 过程值数据（用于场景检测）
            mv_data: 操纵变量数据（用于场景检测）
        """
        if using_json_data and t is not None and pv_data is not None and mv_data is not None:
            # ========== 自动场景检测 ==========
            print(f"\n=== 自动检测控制场景 ===")
            identifier = SystemIdentifier()  # 创建SystemIdentifier实例用于场景检测
            detected_scenario = identifier.detect_control_scenario(t, pv_data, mv_data)
            
            if detected_scenario == 'temperature':
                print(f"✅ 自动检测结果: 温度控制场景")
                print(f"\n=== 选择运行模式 ===")
                for i, (key, desc) in enumerate(Config.MODES.items(), 1):
                    if key != Mode.FLOW_CONTROL:  # 温度模式下不显示流量控制模式
                        print(f"{i}. {desc} ({key})")

                while True:
                    mode_choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"
                    if mode_choice in ["1", "2", "3"]:
                        # 映射到非流量控制模式
                        non_flow_modes = [Mode.STANDARD, Mode.ANTI_DISTURBANCE, Mode.ANTI_NOISE]
                        return non_flow_modes[int(mode_choice) - 1]
                    else:
                        print("❌ 输入错误，请选择1-3")
            elif detected_scenario == 'level':
                print(f"✅ 自动检测结果: 液位控制场景")
                print(f"\n=== 选择运行模式 ===")
                print("1. 标准流量控制模式")
                print("2. 抗扰动流量控制模式")
                print("3. 抗噪声流量控制模式")

                while True:
                    flow_choice = input("请选择流量控制模式（1-3，直接回车选1）：").strip() or "1"
                    if flow_choice in ["1", "2", "3"]:
                        # 液位控制场景使用FLOW_CONTROL模式
                        return Mode.FLOW_CONTROL
                    else:
                        print("❌ 输入错误，请选择1-3")
            else:
                # 无法确定场景，默认使用温度控制模式
                print(f"⚠️ 无法确定场景类型，默认使用温度控制模式")
                print(f"\n=== 选择运行模式 ===")
                for i, (key, desc) in enumerate(Config.MODES.items(), 1):
                    if key != Mode.FLOW_CONTROL:
                        print(f"{i}. {desc} ({key})")

                while True:
                    mode_choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"
                    if mode_choice in ["1", "2", "3"]:
                        non_flow_modes = [Mode.STANDARD, Mode.ANTI_DISTURBANCE, Mode.ANTI_NOISE]
                        return non_flow_modes[int(mode_choice) - 1]
                    else:
                        print("❌ 输入错误，请选择1-3")
        else:
            # 仿真模式：无法自动检测，需要用户选择
            print(f"\n=== 选择控制模式 ===")
            print("1. 温度控制模式")
            print("2. 水阀流量控制模式")

            while True:
                choice = input("请选择控制模式（1-2，直接回车选1）：").strip() or "1"
                if choice == "1":
                    print(f"\n=== 选择运行模式 ===")
                    for i, (key, desc) in enumerate(Config.MODES.items(), 1):
                        if key != Mode.FLOW_CONTROL:
                            print(f"{i}. {desc} ({key})")

                    while True:
                        mode_choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"
                        if mode_choice in ["1", "2", "3"]:
                            non_flow_modes = [Mode.STANDARD, Mode.ANTI_DISTURBANCE, Mode.ANTI_NOISE]
                            return non_flow_modes[int(mode_choice) - 1]
                        else:
                            print("❌ 输入错误，请选择1-3")
                elif choice == "2":
                    print(f"\n=== 选择流量控制模式 ===")
                    print("1. 标准流量控制模式")
                    print("2. 抗扰动流量控制模式")
                    print("3. 抗噪声流量控制模式")

                    while True:
                        flow_choice = input("请选择流量控制模式（1-3，直接回车选1）：").strip() or "1"
                        if flow_choice in ["1", "2", "3"]:
                            return Mode.FLOW_CONTROL
                        else:
                            print("❌ 输入错误，请选择1-3")
                else:
                    print("❌ 输入错误，请选择1或2")

    def choose_noise_reduction_level(self):
        """选择降噪强度"""
        print(f"\n=== 选择降噪强度 ===")
        print("1. 低强度降噪 (截止频率较高，保留更多细节)")
        print("2. 中等强度降噪 (平衡降噪效果和细节保留)")
        print("3. 高强度降噪 (截止频率较低，降噪效果显著)")

        while True:
            choice = input("请选择降噪强度（1-3，直接回车选2）：").strip() or "2"
            if choice in ["1", "2", "3"]:
                levels = [NoiseReductionLevel.LOW, NoiseReductionLevel.MEDIUM, NoiseReductionLevel.HIGH]
                self.noise_reduction_level = levels[int(choice) - 1]
                return self.noise_reduction_level
            else:
                print("❌ 输入错误，请选择1-3")

    def choose_pid_mode(self):
        """选择PID控制模式"""
        print(f"\n=== 选择PID控制模式 ===")
        for i, (key, desc) in enumerate(Config.PID_MODES.items(), 1):
            print(f"{i}. {desc} ({key})")

        while True:
            choice = input("请选择PID模式（1-3，直接回车选1）：").strip() or "1"
            if choice in ["1", "2", "3"]:
                return list(Config.PID_MODES.keys())[int(choice) - 1]
            else:
                print("❌ 输入错误，请选择1-3")

    def choose_tuning_method(self):
        """选择PID整定方法"""
        print(f"\n=== 选择PID整定方法 ===")
        for i, (key, desc) in enumerate(Config.TUNING_METHODS.items(), 1):
            print(f"{i}. {desc} ({key})")

        while True:
            choice = input("请选择整定方法（1-2，直接回车选1）：").strip() or "1"
            if choice in ["1", "2"]:
                return list(Config.TUNING_METHODS.keys())[int(choice) - 1]
            else:
                print("❌ 输入错误，请选择1-2")

    def save_data(self, data, columns, filename):
        """保存数据到CSV"""
        save_path = os.path.join(Config.DATA_SAVE_DIR, filename)
        np.savetxt(
            save_path,
            data,
            delimiter=",",
            header=",".join(columns),
            comments=""
        )
        self.logger.info(f"数据已保存至：{save_path}")
        return save_path

    def save_simulation_to_json(self, time_data, temp_data, valve_data, setpoint, pb_data, ti_data, td_data, kp_data,
                                ki_data, kd_data, start_time, end_time, table_name="PID_FEP_Gateway_Device_001default"):
        """将仿真数据保存为JSON格式"""
        # 转换时间为毫秒时间戳
        timestamps = [int((t + start_time.timestamp()) * 1000) for t in time_data]

        # 构建数据列表
        data_list = []
        for i in range(len(time_data)):
            data_point = {
                "timestamp": timestamps[i],
                "sv": setpoint,
                "ti": ti_data[i] * 10 if len(ti_data) > i else 20,  # 反向缩放显示
                "pb": pb_data[i] if len(pb_data) > i else 100,
                "pv": temp_data[i] if len(temp_data) > i else 0,
                "td": td_data[i] / 2 if len(td_data) > i else 0,  # 反向缩放显示
                "mv": valve_data[i] if len(valve_data) > i else 0,
                "kp": 100 / pb_data[i] if len(pb_data) > i and pb_data[i] != 0 else 5,
                "ki": (100 / pb_data[i]) / ti_data[i] * 10 if len(pb_data) > i and len(ti_data) > i and pb_data[
                    i] != 0 and ti_data[i] != 0 else 0.25,
                "kd": td_data[i] / 2 if len(td_data) > i else 0  # 反向缩放显示
            }
            data_list.append(data_point)

        # 构建JSON结构
        json_result = {
            "status": "success",
            "table": table_name,
            "start_time": datetime.fromtimestamp(start_time.timestamp()).strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": datetime.fromtimestamp(end_time.timestamp()).strftime("%Y-%m-%d %H:%M:%S"),
            "totalRecords": len(data_list),
            "data": data_list
        }

        # 保存到文件
        save_path = os.path.join(Config.DATA_SAVE_DIR, f"simulation_data_{int(start_time.timestamp())}.json")
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(json_result, f, ensure_ascii=False, indent=2)

        self.logger.info(f"仿真数据已保存为JSON格式：{save_path}")
        return save_path


# ----水阀流量和温控系统仿真----
class FlowSystem:
    """水阀流量系统模型：模拟流量动态响应"""

    def __init__(self, K=1.0, T=1.0, noise_level=0.5, mode=Mode.FLOW_CONTROL):
        self.mode = mode
        self.K = K  # 增益
        self.T = T  # 时间常数（流量系统通常很小）
        self.noise_level = noise_level
        self.disturbance_handler = DisturbanceHandler(mode=mode)

        # 状态变量
        self.last_flow = 0.0
        self.buffer = np.ones(1) * self.last_flow

        # 新增：流量控制平滑参数
        self.flow_smooth_factor = 0.1  # 流量变化平滑因子

    def add_disturbance(self, time, current_flow, valve_opening, disturbances):
        """添加扰动对流量的影响"""
        system_state = {
            'K': self.K,
            'T': self.T,
            'initial_K': self.K,
            'initial_T': self.T,
            'last_flow': self.last_flow
        }

        for disturbance in disturbances:
            start = disturbance["time"]
            end = disturbance["time"] + disturbance["duration"]
            if start <= time < end:
                current_flow = self.disturbance_handler.apply_disturbance(
                    disturbance["type"], time, current_flow, valve_opening,
                    disturbance["amplitude"], disturbance["duration"], start, system_state
                )

        # 更新系统状态
        self.K = system_state['K']
        self.T = system_state['T']
        self.last_flow = system_state['last_flow']

        return current_flow

    def generate_flow_input(self, t):
        """生成流量控制的输入信号（阀门开度，0-100%）"""
        data_handler = DataHandler()
        return data_handler._generate_flow_input_signal(t)

    def simulate_with_input(self, t, u, disturbances):
        """基于输入信号仿真流量响应"""
        flow = np.ones_like(t) * 0.0
        self.last_flow = 0.0

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            steady_state = u[i] * self.K

            # 流量控制平滑算法
            new_flow = self.last_flow + (steady_state - self.last_flow) / self.T * dt
            # 应用平滑因子，使流量变化更平滑
            self.last_flow = self.last_flow * (1 - self.flow_smooth_factor) + new_flow * self.flow_smooth_factor

            # 添加扰动和噪声
            output_flow = self.add_disturbance(t[i], self.last_flow, u[i], disturbances)

            # 根据模式调整噪声水平
            if self.mode == Mode.ANTI_NOISE:
                # 抗噪声模式下降低噪声
                noise = np.random.normal(0, self.noise_level * 0.6)
            elif self.mode == Mode.FLOW_CONTROL:
                # 流量控制模式下可能噪声更大
                noise = np.random.normal(0, self.noise_level * 1.5)
            else:
                noise = np.random.normal(0, self.noise_level)

            output_flow += noise
            flow[i] = output_flow

        return flow

    def update(self, valve_opening, time, dt=1, disturbances=None):
        """实时更新系统流量"""
        if disturbances is None:
            disturbances = []

        steady_state = valve_opening * self.K

        # 流量控制平滑算法
        new_flow = self.last_flow + (steady_state - self.last_flow) / self.T * dt
        # 应用平滑因子，使流量变化更平滑
        self.last_flow = self.last_flow * (1 - self.flow_smooth_factor) + new_flow * self.flow_smooth_factor

        # 添加扰动和噪声
        output_flow = self.add_disturbance(time, self.last_flow, valve_opening, disturbances)

        # 根据模式调整噪声水平
        if self.mode == Mode.ANTI_NOISE:
            # 抗噪声模式下降低噪声
            noise = np.random.normal(0, self.noise_level * 0.6)
        elif self.mode == Mode.FLOW_CONTROL:
            # 流量控制模式下可能噪声更大
            noise = np.random.normal(0, self.noise_level * 1.5)
        else:
            noise = np.random.normal(0, self.noise_level)

        output_flow += noise

        return output_flow


class TemperatureSystem:
    """温度系统模型：模拟温度动态响应、老化和扰动"""

    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3, mode=Mode.STANDARD):
        self.mode = mode
        self.initial_K = K
        self.initial_T = T
        self.initial_L = L
        self.K = K  # 当前增益
        self.T = T  # 当前时间常数
        self.L = L  # 当前滞后时间
        self.noise_level = noise_level
        self.disturbance_handler = DisturbanceHandler(mode=mode)

        # 状态变量
        self.last_temp = Config.INIT_TEMPERATURE
        self.buffer = np.ones(int(np.ceil(L))) * self.last_temp
        self.valve_stiction_level = 0  # 阀门卡涩程度
        self.sensor_drift = 0  # 传感器漂移

    def apply_aging(self, time):
        """应用老化对系统参数的影响"""
        if time < Config.AGING_START_TIME:
            return

        # 老化因子（最大变化80%）
        aging_factor = min(0.002 * (time - Config.AGING_START_TIME), 0.8)

        # 根据模式调整老化速度
        if self.mode == Mode.ANTI_DISTURBANCE:
            aging_factor *= 0.8  # 减缓老化
        elif self.mode == Mode.ANTI_NOISE:
            aging_factor *= 0.9  # 减缓老化

        self.K = self.initial_K * (1 - aging_factor * 0.4)  # 增益降低
        self.T = self.initial_T * (1 + aging_factor * 0.8)  # 时间常数增大
        self.L = self.initial_L * (1 + aging_factor * 0.9)  # 滞后时间增加

        # 动态调整滞后缓冲器大小
        new_buffer_size = int(np.ceil(self.L))
        if len(self.buffer) != new_buffer_size:
            self.buffer = np.ones(new_buffer_size) * self.last_temp

    def add_disturbance(self, time, current_temp, valve_opening, disturbances):
        """添加扰动对温度的影响"""
        system_state = {
            'K': self.K,
            'T': self.T,
            'L': self.L,
            'initial_K': self.initial_K,
            'initial_T': self.initial_T,
            'initial_L': self.initial_L,
            'valve_stiction_level': self.valve_stiction_level,
            'sensor_drift': self.sensor_drift
        }

        for disturbance in disturbances:
            start = disturbance["time"]
            end = disturbance["time"] + disturbance["duration"]
            if start <= time < end:
                current_temp = self.disturbance_handler.apply_disturbance(
                    disturbance["type"], time, current_temp, valve_opening,
                    disturbance["amplitude"], disturbance["duration"], start, system_state
                )

        # 更新系统状态
        self.K = system_state['K']
        self.T = system_state['T']
        self.L = system_state['L']
        self.valve_stiction_level = system_state['valve_stiction_level']
        self.sensor_drift = system_state['sensor_drift']

        return current_temp

    def generate_non_step_input(self, t):
        """生成非阶跃输入信号（阀门开度，0-100%）"""
        data_handler = DataHandler()
        return data_handler._generate_default_input_signal(t)

    def simulate_with_input(self, t, u, disturbances):
        """基于输入信号仿真温度响应"""
        temp = np.ones_like(t) * Config.INIT_TEMPERATURE
        self.last_temp = Config.INIT_TEMPERATURE
        self.buffer = np.ones(int(np.ceil(self.L))) * self.last_temp

        for i in range(len(t)):
            self.apply_aging(t[i])
            dt = t[i] - t[i - 1] if i > 0 else 1
            steady_state = Config.INIT_TEMPERATURE + u[i] * self.K
            self.last_temp += (steady_state - self.last_temp) / self.T * dt

            # 处理滞后
            self.buffer = np.roll(self.buffer, 1)
            self.buffer[0] = self.last_temp
            output_temp = self.buffer[-1] if len(self.buffer) > 0 else self.last_temp

            # 添加扰动和噪声
            output_temp = self.add_disturbance(t[i], output_temp, u[i], disturbances)

            # 根据模式调整噪声水平
            if self.mode == Mode.ANTI_NOISE:
                # 抗噪声模式下降低噪声
                noise = np.random.normal(0, self.noise_level * 0.6)
            else:
                noise = np.random.normal(0, self.noise_level)

            output_temp += noise
            temp[i] = output_temp

        return temp

    def update(self, valve_opening, time, dt=1, disturbances=None):
        """实时更新系统温度"""
        if disturbances is None:
            disturbances = []
        self.apply_aging(time)

        # 应用阀门卡涩效应
        effective_valve = valve_opening
        if self.valve_stiction_level > 0:
            # 阀门卡涩：响应变慢
            effective_valve = effective_valve * (
                    1 - self.valve_stiction_level) + self.last_temp * self.valve_stiction_level * 0.1

        steady_state = Config.INIT_TEMPERATURE + effective_valve * self.K
        self.last_temp += (steady_state - self.last_temp) / self.T * dt

        # 处理滞后
        self.buffer = np.roll(self.buffer, 1)
        self.buffer[0] = self.last_temp
        output_temp = self.buffer[-1] if len(self.buffer) > 0 else self.last_temp

        # 添加扰动和噪声
        output_temp = self.add_disturbance(time, output_temp, valve_opening, disturbances)

        # 根据模式调整噪声水平
        if self.mode == Mode.ANTI_NOISE:
            # 抗噪声模式下降低噪声
            noise = np.random.normal(0, self.noise_level * 0.6)
        else:
            noise = np.random.normal(0, self.noise_level)

        output_temp += noise

        # 返回真实温度（不包含传感器漂移）
        return output_temp - self.sensor_drift


class PIDController:
    """PID控制器：实现PID控制与参数平滑更新"""

    def __init__(self, pb=100, ti=0, td=0, dt=1, u_min=Config.MV_MIN, u_max=Config.MV_MAX, mode=PIDMode.STANDARD,
                 system_mode=Mode.STANDARD):
        # 转换参数：pb = 100/Kp，ti = Ti，td = Td
        self.pb = self._clip_pb(pb)  # 比例带
        self.ti = self._clip_ti(ti)  # 积分时间
        self.td = self._clip_td(td)  # 微分时间

        # 从转换参数计算内部使用的Kp, Ti, Td
        self.Kp = 100 / self.pb if self.pb != 0 else 0  # 比例增益
        self.Ti = self.ti  # 积分时间
        self.Td = self.td  # 微分时间

        # 目标参数（用于平滑更新）
        self.target_pb = self.pb
        self.target_ti = self.ti
        self.target_td = self.td
        self.target_Kp = 100 / self.pb if self.pb != 0 else 0
        self.target_Ti = self.ti
        self.target_Td = self.td

        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max

        # 控制状态
        self.last_error = 0.0
        self.integral = 0.0
        self.derivative = 0.0
        self.last_process_var = 0.0  # 用于微分先行
        self.mode = mode  # PID模式选择
        self.system_mode = system_mode  # 系统运行模式（用于调整参数）
        self.smoothing_factor = Config.PARAM_UPDATE_SMOOTH_FACTOR  # 平滑因子
        self.setpoint = 0.0  # 用于比例微分先行模式的设定值
        self.first_call = True  # 标记首次调用

        # 新增：性能指标跟踪
        self.error_history = deque(maxlen=200)
        self.control_effort_history = deque(maxlen=200)

        # 新增：流量控制优化参数
        self.flow_control_smooth_factor = 0.05  # 流量控制输出平滑因子
        self.last_output = 0.0  # 上次输出值，用于平滑

    def _clip_pb(self, pb):
        """限制Pb在合理范围内"""
        return np.clip(pb, Config.PB_MIN, Config.PB_MAX)

    def _clip_ti(self, ti):
        """限制Ti在合理范围内"""
        return np.clip(ti, Config.TI_MIN, Config.TI_MAX)

    def _clip_td(self, td):
        """限制Td在合理范围内"""
        return np.clip(td, Config.TD_MIN, Config.TD_MAX)

    def _update_integral(self, error, temp_output):
        """通用积分更新逻辑"""
        if self.Ti > Config.EPSILON:
            integral_term = (self.Kp / self.Ti) * error * self.dt
            # 预计算输出，判断是否饱和
            if not (self.u_min <= temp_output <= self.u_max):
                integral_term = 0  # 输出饱和时不累积积分
            self.integral += integral_term
            # 积分限幅
            self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

    def _update_derivative(self, value_diff, alpha=0.3):
        """通用微分更新逻辑，支持平滑系数"""
        if self.Td > Config.EPSILON:
            derivative_term = (self.Kp * self.Td) * value_diff / self.dt
            self.derivative = (1 - alpha) * self.derivative + alpha * derivative_term

    def compute(self, setpoint, process_var):
        """计算PID输出（含抗积分饱和）"""
        error = setpoint - process_var
        self.setpoint = setpoint  # 记录设定值

        # 记录误差和控制努力用于性能评估
        self.error_history.append(abs(error))
        self.control_effort_history.append(abs(self.derivative if hasattr(self, 'derivative') else 0))

        # 根据系统模式调整控制策略
        if self.system_mode == Mode.ANTI_DISTURBANCE:
            # 抗扰动模式：降低微分增益，减少对扰动的敏感性
            adjusted_Td = self.Td * 0.7
        elif self.system_mode == Mode.ANTI_NOISE:
            # 抗噪声模式：降低微分增益，减少对噪声的敏感性
            adjusted_Td = self.Td * 0.5
        elif self.system_mode == Mode.FLOW_CONTROL:
            # 流量控制模式：降低微分项，减少噪声影响
            adjusted_Td = self.Td * 0.2
        else:
            adjusted_Td = self.Td

        # 根据不同模式计算输出
        if self.mode == PIDMode.STANDARD:
            # 标准PID: u(t) = Kp * e(t) + Ki * ∫e(t)dt + Kd * de(t)/dt
            proportional = self.Kp * error

            # 预计算输出（不含积分项），用于积分饱和判断
            temp_output = proportional + self.integral + self.derivative

            # 更新积分项
            self._update_integral(error, temp_output)

            # 更新微分项（基于误差）
            if adjusted_Td > Config.EPSILON:
                error_diff = error - self.last_error
                self._update_derivative(error_diff, alpha=0.3)

        elif self.mode == PIDMode.DERIVATIVE_ON_MEASUREMENT:
            # 微分先行: u(t) = Kp * e(t) + Ki * ∫e(t)dt - Kd * dy(t)/dt
            proportional = self.Kp * error

            # 预计算输出（不含微分项），用于积分饱和判断
            temp_output = proportional + self.integral - self.derivative

            # 更新积分项
            self._update_integral(error, temp_output)

            # 更新微分项（基于测量值变化）
            if adjusted_Td > Config.EPSILON:
                process_var_diff = self.last_process_var - process_var
                self._update_derivative(process_var_diff, alpha=0.3)

        elif self.mode == PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT:
            # 比例微分先行: u(t) = Ki * ∫e(t)dt + Kp * (setpoint - y(t)) - Kd * dy(t)/dt
            proportional = self.Kp * (setpoint - process_var)  # 比例项基于设定值与测量值的差

            # 预计算输出（不含积分项），用于积分饱和判断
            temp_output = self.integral + proportional - self.derivative

            # 更新积分项
            self._update_integral(error, temp_output)

            # 更新微分项（基于测量值变化）
            if adjusted_Td > Config.EPSILON:
                process_var_diff = self.last_process_var - process_var
                self._update_derivative(process_var_diff, alpha=0.3)

        # 总输出与限幅
        if self.mode == PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT:
            output = self.integral + proportional - self.derivative
        else:
            output = proportional + self.integral + self.derivative

        output = np.clip(output, self.u_min, self.u_max)
        self.last_error = error
        self.last_process_var = process_var  # 记录当前测量值

        # 平滑更新参数
        self._smooth_update()

        # 流量控制平滑输出
        if self.system_mode == Mode.FLOW_CONTROL:
            # 应用输出平滑，使控制信号变化更平滑
            output = self.last_output * (1 - self.flow_control_smooth_factor) + output * self.flow_control_smooth_factor
            self.last_output = output

        return output

    def _smooth_update(self):
        """平滑更新PID参数，避免突变"""
        self.pb = self.pb * (1 - self.smoothing_factor) + self.target_pb * self.smoothing_factor
        self.ti = self.ti * (1 - self.smoothing_factor) + self.target_ti * self.smoothing_factor
        self.td = self.td * (1 - self.smoothing_factor) + self.target_td * self.smoothing_factor

        # 重新计算内部Kp, Ti, Td
        self.Kp = 100 / self.pb if self.pb != 0 else 0
        self.Ti = self.target_ti
        self.Td = self.target_td

        # 重新限制参数边界
        self.pb = self._clip_pb(self.pb)
        self.ti = self._clip_ti(self.ti)
        self.td = self._clip_td(self.td)

    def set_target_params(self, pb, ti, td, reset_integral=False):
        """设置目标参数（用于平滑更新）"""
        self.target_pb = self._clip_pb(pb)
        self.target_ti = self._clip_ti(ti)
        self.target_td = self._clip_td(td)
        self.target_Kp = 100 / self.target_pb if self.target_pb != 0 else 0
        self.target_Ti = self.target_ti
        self.target_Td = self.target_td

        if reset_integral:
            self.integral = 0.0  # 参数更新时重置积分项

    def reset(self):
        """重置控制器状态"""
        self.last_error = 0.0
        self.integral = 0.0
        self.derivative = 0.0
        self.last_process_var = 0.0
        self.first_call = True

    def adjust_parameters_based_on_disturbance(self, disturbance_type):
        """根据扰动类型调整PID参数"""
        original_pb, original_ti, original_td = self.pb, self.ti, self.td

        if DisturbanceType.OVERSHOOT in disturbance_type:
            self.set_target_params(pb=self.pb * 1.1, ti=self.ti * 0.9, td=self.td * 0.8)
        elif DisturbanceType.STEADY_ERROR in disturbance_type:
            self.set_target_params(pb=self.pb * 0.9, ti=self.ti * 1.1, td=self.td * 1.2)
        elif DisturbanceType.SLOW_RECOVERY in disturbance_type:
            self.set_target_params(pb=self.pb * 0.8, ti=self.ti * 0.9, td=self.td * 1.1)
        elif DisturbanceType.VALVE_STICTION in disturbance_type:
            self.set_target_params(pb=self.pb * 1.2, ti=self.ti * 1.1, td=self.td * 0.9)
        elif DisturbanceType.SENSOR_DRIFT in disturbance_type:
            self.set_target_params(pb=self.pb * 1.0, ti=self.ti * 0.8, td=self.td * 1.3)
        elif DisturbanceType.HEAT_LOSS in disturbance_type:
            self.set_target_params(pb=self.pb * 0.8, ti=self.ti * 1.2, td=self.td * 1.0)
        elif DisturbanceType.CONTROL_VALVE_WEAR in disturbance_type:
            self.set_target_params(pb=self.pb * 1.1, ti=self.ti * 1.0, td=self.td * 0.9)
        elif DisturbanceType.THERMAL_INERTIA in disturbance_type:
            self.set_target_params(pb=self.pb * 0.9, ti=self.ti * 1.2, td=self.td * 1.1)
        elif DisturbanceType.FLOW_NOISE in disturbance_type:
            # 流量噪声：降低微分项
            self.set_target_params(pb=self.pb, ti=self.ti, td=0.0)
        elif DisturbanceType.FLOW_STICTION in disturbance_type:
            # 流量卡涩：降低比例增益，增加积分时间
            self.set_target_params(pb=self.pb * 1.2, ti=self.ti * 1.2, td=0.0)
        else:
            # 默认调整
            self.set_target_params(pb=self.pb * 0.95, ti=self.ti * 1.05, td=self.td * 1.05)

        print(f"🔧 扰动类型: {disturbance_type}")
        print(f"   参数调整: Pb: {original_pb:.2f} → {self.pb:.2f}%, "
              f"Ti: {original_ti:.1f}s → {self.ti:.1f}s, "
              f"Td: {original_td:.1f}s → {self.td:.1f}s")

    def get_performance_metrics(self):
        """获取性能指标"""
        if len(self.error_history) == 0:
            return 0, 0, 0
        error_array = np.array(list(self.error_history))
        control_effort_array = np.array(list(self.control_effort_history))

        # 计算 IAE (Integral Absolute Error)
        iae = np.mean(error_array)
        # 计算 ISE (Integral Square Error)
        ise = np.mean(error_array ** 2)
        # 计算控制努力
        control_effort = np.mean(control_effort_array)

        return iae, ise, control_effort


# ---系统辨识----
class SystemIdentifier:
    """系统辨识与PID整定工具：基于FOPDT模型和Lambda方法"""

    @staticmethod
    def fopdt_model(params, t, u, y0):
        """一阶加纯滞后（FOPDT）模型"""
        K, T, L = params
        y = np.ones_like(t) * y0
        L_int = int(np.round(L))  # 滞后时间（整数化）

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            u_delay = u[max(0, i - L_int)]  # 滞后输入
            y[i] = y[i - 1] + (K * u_delay - (y[i - 1] - y0)) / T * dt

        return y

    @staticmethod
    def fopdt_with_heat_loss(params, t, u, y0, ambient_temp=0.0):
        """
        带热损失的 FOPDT 模型（适用于石油温控）
        
        参数:
            params: [K, T, L, alpha] - 增益、时间常数、滞后、热损失系数
            ambient_temp: 环境温度（热损失基准）
        """
        K, T, L, alpha = params
        y = np.ones_like(t) * y0
        L_int = int(np.round(L))
        
        for i in range(len(t)):
            dt = t[i] - t[i-1] if i > 0 else 1
            u_delay = u[max(0, i - L_int)]
            
            # 标准 FOPDT 响应
            y[i] = y[i-1] + (K * u_delay - (y[i-1] - y0)) / T * dt
            
            # 添加热损失项（与环境温度差成正比）
            heat_loss = alpha * (y[i] - ambient_temp) * dt / T
            y[i] -= heat_loss
        
        return y

    @staticmethod
    def first_order_model(params, t, u, y0):
        """一阶模型（无滞后）"""
        K, T = params
        y = np.ones_like(t) * y0

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            steady_state = u[i] * K
            y[i] = y[i - 1] + (steady_state - y[i - 1]) / T * dt

        return y

    @staticmethod
    def residuals(params, t, u, y_measured, y0, model_type='fopdt'):
        """最小二乘优化的残差函数"""
        if model_type == 'first_order':
            y_predicted = SystemIdentifier.first_order_model(params, t, u, y0)
        else:
            y_predicted = SystemIdentifier.fopdt_model(params, t, u, y0)
        return y_predicted - y_measured

    @staticmethod
    def estimate_initial_guess_from_operational_data(t, y, u, y0):
        """
        从正常运行数据估计 FOPDT 参数初始值（不依赖阶跃响应）
        
        方法：
        1. 使用互相关分析估计滞后 L
        2. 使用输入输出变化率估计增益 K
        3. 使用响应速度估计时间常数 T
        """
        n = len(t)
        if n < 20:
            return {'K': 0.5, 'T': 30.0, 'L': 5.0}  # 默认值
        
        dt = t[1] - t[0] if n > 1 else 1.0
        
        # 1. 估计滞后时间 L（使用互相关分析）
        L_est = SystemIdentifier._estimate_lag_from_correlation(u, y, dt)
        
        # 2. 估计增益 K（使用输入输出变化的相关性）
        K_est = SystemIdentifier._estimate_gain_from_correlation(u, y, y0)
        
        # 3. 估计时间常数 T（使用响应速度）
        T_est = SystemIdentifier._estimate_time_constant_from_response_speed(t, y, u, L_est)
        
        return {
            'K': np.clip(K_est, 0.05, 1.5),
            'T': np.clip(T_est, 5.0, 300.0),
            'L': np.clip(L_est, 0.0, 30.0)
        }

    @staticmethod
    def _estimate_lag_from_correlation(u, y, dt):
        """使用互相关分析估计滞后时间"""
        # 去除均值
        u_centered = u - np.mean(u)
        y_centered = y - np.mean(y)
        
        # 计算互相关
        correlation = np.correlate(y_centered, u_centered, mode='full')
        lags = np.arange(-len(u)+1, len(y))
        
        # 找到最大相关性的滞后
        max_corr_idx = np.argmax(np.abs(correlation))
        lag_samples = lags[max_corr_idx]
        
        # 转换为时间
        L_est = abs(lag_samples) * dt
        
        # 限制在合理范围
        return np.clip(L_est, 0.0, 30.0)

    @staticmethod
    def _estimate_gain_from_correlation(u, y, y0):
        """使用输入输出变化的相关性估计增益"""
        # 计算输入输出的变化
        du = np.diff(u)
        dy = np.diff(y)
        
        # 去除零变化点（避免除零）
        valid_mask = np.abs(du) > Config.EPSILON
        if np.sum(valid_mask) < 5:
            # 如果有效点太少，使用整体统计
            if np.std(u) > Config.EPSILON:
                return (np.max(y) - np.min(y)) / (np.max(u) - np.min(u)) if (np.max(u) - np.min(u)) > Config.EPSILON else 0.5
            return 0.5
        
        # 使用有效点的变化率估计增益
        gains = dy[valid_mask] / du[valid_mask]
        
        # 去除异常值（使用 IQR）
        Q1 = np.percentile(gains, 25)
        Q3 = np.percentile(gains, 75)
        IQR = Q3 - Q1
        valid_gains = gains[(gains >= Q1 - 1.5*IQR) & (gains <= Q3 + 1.5*IQR)]
        
        if len(valid_gains) > 0:
            # 使用中位数（对异常值更鲁棒）
            K_est = np.median(valid_gains)
        else:
            # 回退到简单估计
            if np.std(u) > Config.EPSILON:
                K_est = (np.max(y) - np.min(y)) / (np.max(u) - np.min(u)) if (np.max(u) - np.min(u)) > Config.EPSILON else 0.5
            else:
                K_est = 0.5
        
        return np.clip(K_est, 0.05, 1.5)

    @staticmethod
    def _estimate_time_constant_from_response_speed(t, y, u, L_est):
        """从响应速度估计时间常数"""
        n = len(y)
        if n < 20:
            return 30.0
        
        # 计算输出的变化率（响应速度）
        dy_dt = np.gradient(y, t)
        
        # 考虑滞后，使用滞后的输入
        L_samples = int(np.round(L_est / (t[1] - t[0])) if len(t) > 1 else 0)
        u_delayed = np.roll(u, L_samples)
        
        # 找到输入变化较大的时间段
        du = np.abs(np.diff(u_delayed))
        significant_change_mask = du > np.percentile(du, 75)  # 前25%的变化
        
        if np.sum(significant_change_mask) < 3:
            # 如果变化不明显，使用整体响应速度
            # 估计：T ≈ (y变化范围) / (最大变化率)
            max_dy_dt = np.max(np.abs(dy_dt))
            y_range = np.max(y) - np.min(y)
            if max_dy_dt > Config.EPSILON:
                T_est = y_range / max_dy_dt
            else:
                T_est = 30.0
        else:
            # 使用显著变化段的响应速度
            significant_dy_dt = dy_dt[1:][significant_change_mask]
            significant_y = y[1:][significant_change_mask]
            
            if len(significant_dy_dt) > 0 and np.max(np.abs(significant_dy_dt)) > Config.EPSILON:
                # 使用平均响应速度估计
                avg_response_speed = np.mean(np.abs(significant_dy_dt))
                y_range = np.max(significant_y) - np.min(significant_y)
                if avg_response_speed > Config.EPSILON:
                    T_est = y_range / avg_response_speed
                else:
                    T_est = 30.0
            else:
                T_est = 30.0
        
        return np.clip(T_est, 5.0, 300.0)

    @staticmethod
    def identify_fopdt(t, y, u):
        """用最小二乘法辨识FOPDT模型参数（K, T, L）- 使用改进的初始猜测"""
        y0 = np.mean(y[-30:]) if len(y) > 30 else np.mean(y)  # 初始值估计
        
        # 使用改进的初始猜测方法（不依赖阶跃响应）
        initial_params = SystemIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y0)
        initial_guess = [initial_params['K'], initial_params['T'], initial_params['L']]
        
        bounds = ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'fopdt'),
                bounds=bounds,
                method='trf',
                ftol=1e-6,
                xtol=1e-6,
                max_nfev=1000,
                verbose=0
            )
            
            if result.success:
                K, T, L = result.x
            else:
                # 如果失败，尝试放宽约束
                result2 = least_squares(
                    SystemIdentifier.residuals,
                    initial_guess,
                    args=(t, u, y, y0, 'fopdt'),
                    bounds=([0.01, 1.0, 0.0], [2.0, 300.0, 30.0]),  # 更宽的边界
                    method='trf',
                    ftol=1e-4,
                    xtol=1e-4,
                    max_nfev=500,
                    verbose=0
                )
                K, T, L = result2.x if result2.success else initial_guess
        except Exception as e:
            print(f"⚠️ 参数辨识失败：{e}，使用初始猜测值")
            K, T, L = initial_guess

        # 确保参数在合理范围
        K = np.clip(K, 0.05, 1.5)
        T = np.clip(T, 5.0, 150.0)
        L = np.clip(L, 0.0, 20.0)
        return K, T, L

    @staticmethod
    def identify_fopdt_with_heat_loss(t, y, u, ambient_temp=0.0):
        """
        辨识带热损失的 FOPDT 模型（使用改进的最小二乘法，不依赖阶跃响应）
        
        适用于石油温控场景，考虑热损失效应
        
        Args:
            t: 时间数组
            y: 输出数据（温度）
            u: 输入数据（阀门开度）
            ambient_temp: 环境温度（热损失基准），默认0.0
            
        Returns:
            Tuple: (K, T, L, alpha) - 增益、时间常数、滞后、热损失系数
        """
        y0 = np.mean(y[:10]) if len(y) > 10 else np.mean(y)
        
        # 使用改进的初始猜测方法（不依赖阶跃响应）
        initial_params = SystemIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y0)
        K_guess, T_guess, L_guess = initial_params['K'], initial_params['T'], initial_params['L']
        
        # 估计热损失系数（使用稳态数据）
        if len(y) > 50:
            # 稳态时，热损失 = 输入功率
            steady_y = np.mean(y[-30:])
            steady_u = np.mean(u[-30:])
            if abs(steady_y - ambient_temp) > 1.0:
                alpha_guess = steady_u / (steady_y - ambient_temp) * 0.1
            else:
                alpha_guess = 0.01
        else:
            alpha_guess = 0.01
        
        initial_guess = [K_guess, T_guess, L_guess, alpha_guess]
        bounds = ([0.05, 5.0, 0.0, 0.0], [1.5, 300.0, 30.0, 0.5])  # T 上限增加到 300
        
        def residuals_hl(params, t, u, y_measured, y0, ambient_temp):
            y_pred = SystemIdentifier.fopdt_with_heat_loss(params, t, u, y0, ambient_temp)
            return y_pred - y_measured
        
        # 改进的最小二乘优化：使用多种优化方法提高鲁棒性
        try:
            # 方法1：标准最小二乘
            result = least_squares(
                residuals_hl,
                initial_guess,
                args=(t, u, y, y0, ambient_temp),
                bounds=bounds,
                method='trf',  # Trust Region Reflective
                ftol=1e-6,
                xtol=1e-6,
                max_nfev=1000,
                verbose=0
            )
            
            # 如果优化失败，尝试其他方法
            if not result.success:
                # 方法2：使用 L-BFGS-B（无边界约束时）
                try:
                    from scipy.optimize import minimize
                    result2 = minimize(
                        lambda p: np.sum(residuals_hl(p, t, u, y, y0, ambient_temp)**2),
                        initial_guess,
                        method='L-BFGS-B',
                        bounds=list(zip(*bounds)),
                        options={'maxiter': 500}
                    )
                    if result2.success:
                        K, T, L, alpha = result2.x
                    else:
                        K, T, L, alpha = result.x
                except:
                    K, T, L, alpha = result.x
            else:
                K, T, L, alpha = result.x
                
        except Exception as e:
            print(f"⚠️ 带热损失模型辨识失败：{e}，使用初始猜测值")
            K, T, L, alpha = initial_guess
        
        # 确保参数在合理范围
        K = np.clip(K, 0.05, 1.5)
        T = np.clip(T, 5.0, 300.0)
        L = np.clip(L, 0.0, 30.0)
        alpha = np.clip(alpha, 0.0, 0.5)
        
        return K, T, L, alpha

    @staticmethod
    def identify_first_order(t, y, u):
        """用最小二乘法辨识一阶模型参数（K, T）- 使用改进的初始猜测"""
        y0 = np.mean(y[:10]) if len(y) > 10 else np.mean(y)  # 初始值估计
        
        # 使用改进的初始猜测
        initial_params = SystemIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y0)
        K_guess = initial_params['K']
        T_guess = initial_params['T']
        
        # 对于一阶模型，T 应该更小
        T_guess = min(T_guess, 10.0)
        
        initial_guess = [K_guess, T_guess]
        bounds = ([0.05, 0.1], [2.0, 10.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'first_order'),
                bounds=bounds,
                method='trf',
                ftol=1e-6,
                xtol=1e-6,
                max_nfev=1000,
                verbose=0
            )
            K, T = result.x if result.success else initial_guess
        except Exception as e:
            print(f"⚠️ 一阶模型参数辨识失败：{e}，使用初始猜测值")
            K, T = initial_guess

        # 确保参数在合理范围
        K = np.clip(K, 0.05, 2.0)
        T = np.clip(T, 0.1, 10.0)
        return K, T

    @staticmethod
    def lambda_tuning(K, T, L, lambda_val=None, mode=Mode.STANDARD):
        """基于Lambda方法整定PID参数，根据模式调整参数"""
        if lambda_val is None:
            lambda_val = T * 0.8
        print('lambda值是：', lambda_val)
        denominator = K * (lambda_val + L / 2)
        if denominator < Config.EPSILON:
            return 1.0, 20.0, 1.0  # 异常时返回默认安全值

        # 计算Kp, Ti, Td
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0

        # 根据模式调整参数
        if mode == Mode.ANTI_DISTURBANCE:
            # 抗扰动模式：降低比例增益和微分增益，增加积分时间
            Kp *= 0.8
            Ti *= 1.2
            Td *= 0.7
        elif mode == Mode.ANTI_NOISE:
            # 抗噪声模式：降低比例增益和微分增益，增加积分时间
            Kp *= 0.7
            Ti *= 1.3
            Td *= 0.5
        elif mode == Mode.FLOW_CONTROL:
            # 流量控制模式：降低比例增益，增加积分时间，减少微分
            Kp *= 0.6
            Ti *= 1.5
            Td *= 0.3  # 保持微分但降低

        # 参数限幅
        Kp = np.clip(Kp, 0.5, 6.0)
        Ti = np.clip(Ti, 8.0, 120.0)
        Td = np.clip(Td, 0.0, 25.0)

        # 转换为pb, ti, td
        pb = 100 / Kp if Kp != 0 else 100.0
        ti = Ti
        td = Td

        # 应用全局参数边界保护
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)
        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)

        return pb, ti, td

    # 温度
    @staticmethod
    def lambda_tuning_for_temperature_control(K, T, L, lambda_val=None, mode=Mode.STANDARD):
        """
        针对石油温控的 Lambda 整定方法
        
        特点：
        - 大滞后系统（L/T 可能 > 0.5）
        - 更保守的参数选择
        - 考虑热损失和稳定性
        """
        if lambda_val is None:
            # 对于大滞后系统，lambda 应该更大（更保守）
            L_T_ratio = L / T if T > Config.EPSILON else 0.5
            if L_T_ratio > 0.5:
                # 大滞后系统：lambda = max(T, 2*L)
                lambda_val = max(T, 2 * L)
            else:
                lambda_val = T * 0.8
        
        denominator = K * (lambda_val + L / 2)
        if denominator < Config.EPSILON:
            return 1.0, 20.0, 1.0
        
        # 标准 Lambda 公式
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0
        
        # 针对温控的特殊调整
        L_T_ratio = L / T if T > Config.EPSILON else 0.5
        
        if L_T_ratio > 0.5:
            # 大滞后系统：进一步降低增益，增加积分时间
            Kp *= 0.85  # 更保守
            Ti *= 1.15  # 更慢的积分
            Td *= 0.9   # 保持微分但略微降低
        elif L_T_ratio > 0.3:
            # 中等滞后
            Kp *= 0.9
            Ti *= 1.1
        
        # 根据模式调整
        if mode == Mode.ANTI_DISTURBANCE:
            Kp *= 0.8
            Ti *= 1.2
            Td *= 0.7
        elif mode == Mode.ANTI_NOISE:
            Kp *= 0.7
            Ti *= 1.3
            Td *= 0.5
        
        # 参数限幅（温控系统更宽的范围）
        Kp = np.clip(Kp, 0.3, 5.0)  # 更小的最小增益
        Ti = np.clip(Ti, 10.0, 300.0)  # 更大的积分时间上限
        Td = np.clip(Td, 0.0, 30.0)  # 更大的微分时间上限
        
        pb = 100 / Kp if Kp != 0 else 100.0
        ti = Ti
        td = Td
        
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti = np.clip(ti, Config.TI_MIN, 300.0)  # 扩展上限
        td = np.clip(td, Config.TD_MIN, 30.0)   # 扩展上限
        
        return pb, ti, td

    # 液位
    @staticmethod
    def lambda_tuning_for_level_control(K, T, L=0.0, mode=None):
        """
        针对蒸馏液位控制的 Lambda 整定方法
        
        特点：
        - 快速响应需求
        - 抗噪声
        - 避免振荡
        - 考虑积分特性
        """
        # 液位系统通常滞后很小
        L = max(L, 0.1)  # 最小滞后
        
        # Lambda 选择：快速响应
        # 对于液位，lambda 应该较小（T/2 ~ T/3）
        lambda_val = T * 0.5  # 比标准方法更激进
        
        denominator = K * (lambda_val + L / 2)
        if denominator < Config.EPSILON:
            return 1.0, 20.0, 0.0
        
        # 标准 Lambda 公式
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0
        
        # 针对液位的特殊调整
        # 1. 降低增益避免振荡（液位容易振荡）
        Kp *= 0.7
        
        # 2. 增加积分时间（减弱积分作用，避免过调）
        Ti *= 1.3
        
        # 3. 关闭或极小微分（液位噪声大）
        Td = 0.0
        
        # 4. 如果系统是积分型（T 很大或接近积分），进一步调整
        if T > 50:  # 接近积分系统
            # 积分系统：主要靠积分项，降低比例增益
            Kp *= 0.6
            Ti = T * 1.5  # 积分时间应该更大
        
        # 参数限幅（液位控制）
        Kp = np.clip(Kp, 0.2, 4.0)
        Ti = np.clip(Ti, 2.0, 60.0)  # 积分时间范围
        Td = 0.0  # 强制关闭微分
        
        pb = 100 / Kp if Kp != 0 else 100.0
        return pb, Ti, Td

    # 流量
    @staticmethod
    def lambda_tuning_for_flow(K, T, L=0.0, mode=None):
        """
        针对流量控制的 PID 整定（快过程）
        假设 L ≈ 0，使用简化 Lambda 方法或经验公式
        """
        # 流量系统通常 L 很小，强制设为 0 避免过度保守
        L = 0.05

        # Lambda 选择：快响应，取较小值（如 T/3 ~ T/2）
        # lambda_val = max(T * 0.8, 0.1)  # 避免除零，最小 0.1s
        lambda_val = 0.8*T

        # 分母保护
        denominator = K * (lambda_val + L / 2)
        if denominator < Config.EPSILON:
            return 1.0, 20.0, 0.0  # 默认安全值（P主导，I弱，D=0）

        # 标准 Lambda 公式
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0

        # 针对流量的特殊调整
        if mode == Mode.FLOW_CONTROL:
            # 1. 降低 Kp 避免超调（流量易振荡）
            Kp *= 0.6
            # 2. 增大 Ti（减弱积分，防阀门频繁动作）
            Ti *= 1.5
            # 3. 微分通常关闭或极小（流量噪声大）
            Td = 0.0

        # 参数限幅（流量控制更严格）
        Kp = np.clip(Kp, 0.2, 3.0)  # 比例增益更小
        Ti = np.clip(Ti, 5.0, 60.0)  # 积分时间更短但不过激
        Td = 0.0  # 强制关闭微分（推荐）

        # 转换为工程单位
        Pb = 100 / Kp if Kp != 0 else 100.0
        return Pb, Ti, Td

    @staticmethod
    def cohen_coon_tuning(K, T, L):
        """Cohen-Coon 整定方法（适用于FOPDT模型）"""
        if L <= 0 or T <= 0:
            print("⚠️ Cohen-Coon 要求 T > 0 且 L > 0，返回默认参数")
            return 1.0, 20.0, 1.0

        # Cohen-Coon 公式
        Kc = (1 / K) * (T / L) * (4.0 / 3.0 + (L / (4 * T)))
        Ti = L * (32 + 6 * (L / T)) / (13 + 8 * (L / T))
        Td = (4 * L) / (11 + 2 * (L / T))

        # 转换为 pb（比例带 = 100 / Kp）
        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td

        # 参数限幅（与 Lambda 方法一致）
        pb = np.clip(pb, 100 / 6.0, 100 / 0.5)  # 对应 Kp ∈ [0.5, 6.0]
        ti = np.clip(ti, 8.0, 120.0)
        td = np.clip(td, 0.0, 25.0)

        return pb, ti, td

    def classify_case(self, temp_data, setpoint, tol=0.5, std_tol=0.2, min_len=10):
        """判断JSON数据属于哪种情形（Case 1 / 2 / 3）"""
        n = len(temp_data)
        if n < 30:  # 数据太少，无法判断
            return "UNKNOWN"

        # 特征1：初始点是否远离设定点
        initial_dev = abs(temp_data[0] - setpoint)
        is_cold_start = initial_dev > 2.0

        # 特征2：前段是否稳态（前50点或1/3数据）
        head_len = min(50, n // 3)
        head_steady = self.is_steady_state(temp_data[:head_len], setpoint, tol, std_tol, min_len)

        # 特征3：尾段是否稳态（最后30点）
        tail_len = min(30, n // 4)
        tail_steady = self.is_steady_state(temp_data[-tail_len:], setpoint, tol, std_tol, min_len)

        # 特征4：是否存在中间扰动（先稳后乱）
        # 检查是否存在"稳态 → 偏离 → 恢复"模式
        has_disturbance = False
        if head_steady:
            # 从 head_len 开始找第一个显著偏离点
            for i in range(head_len, n):
                if abs(temp_data[i] - setpoint) > 1.0:
                    # 再检查后续是否有恢复趋势（可选）
                    has_disturbance = True
                    break

        # 分类
        if is_cold_start and not tail_steady:
            return "CASE_1"  # 全程非稳态，冷启动
        elif head_steady and has_disturbance:
            return "CASE_2"  # 先稳后扰
        elif not head_steady and tail_steady:
            return "CASE_3"  # 有完整升温+稳态过程
        elif head_steady and not has_disturbance and tail_steady:
            return "ALREADY_STABLE"  # 无需整定
        else:
            # 模糊情况：优先按 CASE_3 处理（尝试找首次升温段）
            return "CASE_3_FALLBACK"

    def is_steady_state(self, temps, setpoint, tol=0.5, std_tol=0.2, min_len=10):
        """判断一段温度是否处于稳态"""
        if len(temps) < min_len:
            return False
        within_band = np.all(np.abs(temps - setpoint) <= tol)
        low_std = np.std(temps) < std_tol
        return within_band and low_std

    def find_first_steady_entry(self, temp_data, setpoint, window=20, tol=0.5, std_tol=0.2):
        """找到首次进入稳态的时间点"""
        for i in range(window, len(temp_data)):
            if self.is_steady_state(temp_data[i - window + 1:i + 1], setpoint, tol, std_tol):
                return i - window + 1  # 返回稳态开始索引
        return None

    def find_disturbance_start(self, temp_data, setpoint, steady_head_len, threshold=1.0):
        """定位扰动起始点"""
        for i in range(steady_head_len, len(temp_data)):
            if abs(temp_data[i] - setpoint) > threshold:
                # 可加斜率突变判断：|dT/dt| 突增
                return i
        return None

    def extract_tuning_segment(self, case, t, temp_data, setpoint, u_data=None):
        """根据情形提取有效整定段"""
        if case == "CASE_1":
            # 全程非稳态，整段作为整定段
            if u_data is not None:
                return t, temp_data, u_data
            return t, temp_data
        elif case == "CASE_2":
            # 扰动后恢复段
            head_len = min(50, len(temp_data) // 3)
            start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
            if start_idx is not None:
                if u_data is not None:
                    return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                return t[start_idx:], temp_data[start_idx:]
            else:
                # 如果没找到扰动点，可能数据有问题，返回后半段
                mid = len(t) // 2
                if u_data is not None:
                    return t[mid:], temp_data[mid:], u_data[mid:]
                return t[mid:], temp_data[mid:]
        elif case in ["CASE_3", "CASE_3_FALLBACK"]:
            # 首次升温段
            steady_idx = self.find_first_steady_entry(temp_data, setpoint)
            if steady_idx:
                # 多取一点包含超调或稳定过程
                end_idx = min(steady_idx + 20, len(t))
                if u_data is not None:
                    return t[:end_idx], temp_data[:end_idx], u_data[:end_idx]
                return t[:end_idx], temp_data[:end_idx]
            else:
                # 退化为 CASE_2
                head_len = min(50, len(temp_data) // 3)
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
                if start_idx is not None:
                    if u_data is not None:
                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                    return t[start_idx:], temp_data[start_idx:]
                else:
                    # 如果都找不到，返回前半段
                    mid = len(t) // 2
                    if u_data is not None:
                        return t[:mid], temp_data[:mid], u_data[:mid]
                    return t[:mid], temp_data[:mid]
        else:
            # UNKNOWN 或 ALREADY_STABLE，返回 None
            if u_data is not None:
                return None, None, None
            return None, None

    def auto_tune_from_json(self, t, temp_data, setpoint, tuning_method, mode=Mode.STANDARD, u_data=None):
        """根据JSON数据自动整定PID参数 - 自动检测场景并选择相应模型"""
        case = self.classify_case(temp_data, setpoint)
        print(f"📊 JSON数据情形: {case}")

        if case == "ALREADY_STABLE":
            print("✅ 数据已稳定，无需整定")
            return None

        # 提取整定段，如果提供了输入信号数据，也同时提取
        if u_data is not None:
            t_seg, y_seg, u_seg = self.extract_tuning_segment(case, t, temp_data, setpoint, u_data)
        else:
            t_seg, y_seg = self.extract_tuning_segment(case, t, temp_data, setpoint)
            u_seg = None

        if t_seg is None or len(t_seg) < 20:
            print("⚠️ 无法提取有效整定段，数据不足")
            return None

        print(f"📈 提取整定段: {len(t_seg)} 个点")
        # 重置时间轴为从0开始
        t_seg_rel = t_seg - t_seg[0]

        # 如果没有输入信号数据，使用设定值作为默认输入（不理想但至少能运行）
        if u_seg is None:
            print("⚠️ 警告：未提供输入信号数据，使用设定值作为默认输入进行辨识（可能不准确）")
            u_seg = np.full_like(t_seg_rel, setpoint)

        # ========== 自动场景检测 ==========
        detected_scenario = self.detect_control_scenario(t_seg_rel, y_seg, u_seg)
        print(f"🔍 自动检测场景类型: {detected_scenario}")

        # ========== 根据场景选择数据预处理 ==========
        if detected_scenario == 'temperature':
            # 温控场景：使用温控预处理
            try:
                t_seg_rel, y_seg, u_seg = self.preprocess_temperature_data(t_seg_rel, y_seg, u_seg)
                print("✅ 已应用温控数据预处理（去除瞬态、热损失补偿、平滑）")
            except Exception as e:
                print(f"⚠️ 温控预处理失败: {e}，继续使用原始数据")
        elif detected_scenario == 'level':
            # 液位场景：使用液位预处理
            try:
                t_seg_rel, y_seg, u_seg = self.preprocess_level_data(t_seg_rel, y_seg, u_seg, noise_reduction='medium')
                print("✅ 已应用液位数据预处理（异常值移除、噪声滤波、周期性波动去除）")
            except Exception as e:
                print(f"⚠️ 液位预处理失败: {e}，继续使用原始数据")

        # ========== 根据场景选择模型 ==========
        try:
            if mode == Mode.FLOW_CONTROL:
                # 流量模式使用一阶模型
                K, T = self.identify_first_order(t_seg_rel, y_seg, u_seg)
                L = 0.0  # 假设无滞后
                print(f"🔍 一阶模型辨识结果: K={K:.3f}, T={T:.3f}")
            elif detected_scenario == 'level':
                # 液位场景：使用液位控制模型（自动选择积分-延迟/一阶/FOPDT）
                params = self.identify_level_control_model(t_seg_rel, y_seg, u_seg)
                if len(params) == 2:  # 积分-延迟模型
                    K, L = params
                    T = 100  # 大时间常数表示积分特性
                    print(f"🔍 积分-延迟模型辨识结果: K={K:.3f}, L={L:.3f} (积分系统)")
                elif len(params) == 3:  # FOPDT模型
                    K, T, L = params
                    print(f"🔍 FOPDT模型辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}")
                else:  # 一阶模型
                    K, T = params
                    L = 0.0
                print(f"🔍 一阶模型辨识结果: K={K:.3f}, T={T:.3f}")
            else:
                # 温控场景：检测热损失并选择模型
                # 检测是否有热损失（通过稳态段的温度下降趋势）
                has_heat_loss = False
                ambient_temp = np.min(y_seg) if len(y_seg) > 0 else 0.0  # 估计环境温度
                
                if len(y_seg) > 200:
                    # 检查稳态段是否有下降趋势
                    steady_segment = y_seg[-100:]
                    if np.std(steady_segment) < 0.5:  # 稳态
                        x = np.arange(len(steady_segment))
                        coeffs = np.polyfit(x, steady_segment, 1)
                        if coeffs[0] < -0.01:  # 有下降趋势，可能存在热损失
                            has_heat_loss = True
                            print(f"🔍 检测到热损失趋势，使用带热损失的FOPDT模型")
                
                if has_heat_loss:
                    # 使用带热损失的FOPDT模型
                    K, T, L, alpha = self.identify_fopdt_with_heat_loss(t_seg_rel, y_seg, u_seg, ambient_temp)
                    print(f"🔍 带热损失FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}, α={alpha:.4f}")
                else:
                    # 使用标准FOPDT模型
                    K, T, L = self.identify_fopdt(t_seg_rel, y_seg, u_seg)
                    print(f"🔍 FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}")
        except Exception as e:
            print(f"❌ 模型拟合失败: {e}")
            return None

        # ========== 根据场景选择整定方法 ==========
        lambda_val = T  # 可配置
        if tuning_method == TuningMethod.LAMBDA:
            if mode == Mode.FLOW_CONTROL:
                pb, ti, td = self.lambda_tuning_for_flow(K, T, L, mode)
            elif detected_scenario == 'temperature':
                # 温控场景：使用温控专用整定方法
                pb, ti, td = self.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode)
            elif detected_scenario == 'level':
                # 液位场景：使用液位专用整定方法
                pb, ti, td = self.lambda_tuning_for_level_control(K, T, L, mode)
            else:
                pb, ti, td = self.lambda_tuning(K, T, L, lambda_val, mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            # Cohen-Coon方法主要用于FOPDT模型
            if detected_scenario == 'level' and len(params) == 2:
                # 积分-延迟模型不适合Cohen-Coon，使用液位专用方法
                pb, ti, td = self.lambda_tuning_for_level_control(K, T, L, mode)
            else:
                pb, ti, td = self.cohen_coon_tuning(K, T, L)
        else:
            # 默认使用标准Lambda方法
            if detected_scenario == 'temperature':
                pb, ti, td = self.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode)
            elif detected_scenario == 'level':
                pb, ti, td = self.lambda_tuning_for_level_control(K, T, L, mode)
            else:
                pb, ti, td = self.lambda_tuning(K, T, L, lambda_val, mode)

        print(f"🎯 计算PID参数: Pb={pb:.2f}%, Ti={ti:.2f}s, Td={td:.2f}s")
        return {"pb": pb, "ti": ti, "td": td, "case": case, "scenario": detected_scenario}

    @staticmethod
    def preprocess_temperature_data(t, y, u, min_data_points=100):
        """
        针对石油温控的数据预处理
        
        特点：
        - 需要更长的数据窗口
        - 去除初始瞬态
        - 检测并处理热损失
        """
        # 1. 检查数据长度（温控需要更多数据点）
        if len(t) < min_data_points:
            # 不抛出异常，只警告
            print(f"⚠️ 警告：温控系统建议至少 {min_data_points} 个数据点，当前只有 {len(t)} 个")
        
        # 2. 去除初始瞬态（前 10% 数据可能不稳定）
        skip_points = max(10, len(t) // 10)
        if skip_points > 0 and len(t) > skip_points:
            t = t[skip_points:]
            y = y[skip_points:]
            u = u[skip_points:]
        
        # 3. 检测并补偿热损失（如果数据足够长）
        if len(y) > 200:
            # 使用稳态段估计热损失
            steady_segment = y[-100:]
            if np.std(steady_segment) < 0.5:  # 稳态
                # 检测是否有缓慢下降趋势（热损失）
                x = np.arange(len(steady_segment))
                coeffs = np.polyfit(x, steady_segment, 1)
                if coeffs[0] < -0.01:  # 有下降趋势
                    # 补偿热损失
                    trend = np.polyval(coeffs, np.arange(len(y)))
                    y = y - trend + trend[0]  # 去除趋势，保持初始值
        
        # 4. 平滑处理（大惯性系统可以更激进地平滑）
        from scipy.signal import savgol_filter
        if len(y) > 21:
            window_length = min(21, len(y) // 2 * 2 - 1)  # 必须是奇数
            y = savgol_filter(y, window_length, 3)
        
        return t, y, u

    @staticmethod
    def preprocess_level_data(t, y, u, noise_reduction='medium'):
        """
        针对蒸馏液位的数据预处理
        
        特点：
        - 强噪声滤波
        - 去除异常波动
        - 检测并处理耦合效应
        """
        # 1. 异常值检测和移除（使用 IQR 方法）
        if len(y) > 10:
            Q1 = np.percentile(y, 25)
            Q3 = np.percentile(y, 75)
            IQR = Q3 - Q1
            if IQR > Config.EPSILON:
                lower_bound = Q1 - 2.5 * IQR  # 更宽松的边界
                upper_bound = Q3 + 2.5 * IQR
                
                # 标记异常值
                outlier_mask = (y < lower_bound) | (y > upper_bound)
                if np.any(outlier_mask):
                    # 用前后值插值替换异常值
                    valid_indices = np.where(~outlier_mask)[0]
                    if len(valid_indices) > 0:
                        outlier_indices = np.where(outlier_mask)[0]
                        y_interp = np.interp(outlier_indices, valid_indices, y[valid_indices])
                        y[outlier_mask] = y_interp
        
        # 2. 噪声滤波（根据噪声水平选择强度）
        from scipy.signal import savgol_filter, butter, filtfilt
        
        if noise_reduction == 'high':
            # 高强度滤波
            if len(y) > 31:
                window_length = min(31, len(y) // 2 * 2 - 1)
                y = savgol_filter(y, window_length, 3)
            # 额外低通滤波
            if len(y) > 10:
                try:
                    b, a = butter(3, 0.1, 'low')
                    y = filtfilt(b, a, y)
                except:
                    pass  # 如果滤波失败，继续
        elif noise_reduction == 'medium':
            # 中等强度滤波
            if len(y) > 15:
                window_length = min(15, len(y) // 2 * 2 - 1)
                y = savgol_filter(y, window_length, 3)
        else:
            # 低强度滤波
            if len(y) > 7:
                window_length = min(7, len(y) // 2 * 2 - 1)
                y = savgol_filter(y, window_length, 3)
        
        # 3. 检测并去除周期性波动（如沸腾引起的波动）
        if len(y) > 50 and len(t) > 1:
            try:
                # 使用 FFT 检测周期性
                fft_y = np.fft.fft(y - np.mean(y))
                dt = t[1] - t[0]
                freqs = np.fft.fftfreq(len(y), dt)
                power = np.abs(fft_y)
                
                # 找到主要频率
                positive_freq_idx = np.where(freqs > 0)[0]
                if len(positive_freq_idx) > 0:
                    dominant_freq_idx = positive_freq_idx[np.argmax(power[positive_freq_idx])]
                    dominant_freq = abs(freqs[dominant_freq_idx])
                    
                    # 如果存在明显的周期性（周期 < 总时间的 1/5），尝试去除
                    if dominant_freq > 0 and 1/dominant_freq < (t[-1] - t[0]) / 5:
                        # 使用带阻滤波器去除该频率
                        from scipy.signal import iirnotch
                        fs = 1 / dt if dt > 0 else 1
                        if fs > 2 * dominant_freq:
                            Q = 30  # 品质因数
                            b, a = iirnotch(dominant_freq, Q, fs)
                            y = filtfilt(b, a, y)
            except:
                pass  # 如果FFT分析失败，继续
        
        # 4. 输入信号也需要平滑（如果噪声大）
        if len(u) > 15:
            window_length = min(15, len(u) // 2 * 2 - 1)
            u = savgol_filter(u, window_length, 3)
        
        return t, y, u

    @staticmethod
    def detect_control_scenario(t, y, u):
        """
        自动检测控制场景类型（不依赖阶跃响应）
        
        返回: 'temperature' 或 'level'
        """
        if len(y) < 20:
            return 'temperature'  # 默认
        
        # 1. 估计响应速度（使用变化率，不依赖阶跃）
        dy_dt = np.gradient(y, t)
        avg_response_speed = np.mean(np.abs(dy_dt))
        max_response_speed = np.max(np.abs(dy_dt))
        
        # 2. 噪声水平
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > Config.EPSILON else 100
        
        # 3. 估计时间常数（使用响应速度）
        y_range = np.max(y) - np.min(y)
        if max_response_speed > Config.EPSILON:
            estimated_T = y_range / max_response_speed
        else:
            estimated_T = 30.0  # 默认值
        
        # 4. 检测积分特性（液位系统）
        # 如果输出变化与输入积分高度相关，可能是积分系统
        if len(u) == len(y):
            dt = t[1] - t[0] if len(t) > 1 else 1.0
            u_integral = np.cumsum(u) * dt
            try:
                correlation_with_integral = np.corrcoef(y, u_integral)[0, 1]
                if np.isnan(correlation_with_integral):
                    correlation_with_integral = 0
            except:
                correlation_with_integral = 0
        else:
            correlation_with_integral = 0
        
        # 5. 判断规则
        # 温控特征：慢响应、低噪声、大时间常数
        # 液位特征：快响应、高噪声、积分特性、小时间常数
        
        if estimated_T > 20 and snr > 10 and avg_response_speed < 0.5:
            return 'temperature'
        elif estimated_T < 10 and (snr < 8 or correlation_with_integral > 0.7):
            return 'level'
        elif estimated_T < 10:
            return 'level'
        else:
            return 'temperature'  # 默认温控

    @staticmethod
    def integral_delay_model(params, t, u, y0):
        """
        积分-延迟模型（适用于液位控制）
        
        模型：y(s) = (K/s) * e^(-Ls) * u(s)
        离散形式：y[i] = y[i-1] + K * u_delay * dt
        """
        K, L = params  # 积分增益、滞后时间
        y = np.ones_like(t) * y0
        L_int = int(np.round(L))
        
        for i in range(len(t)):
            dt = t[i] - t[i-1] if i > 0 else 1
            u_delay = u[max(0, i - L_int)]
            y[i] = y[i-1] + K * u_delay * dt
        
        return y

    @staticmethod
    def identify_level_control_model(t, y, u):
        """
        辨识液位控制模型（使用改进的最小二乘法，不依赖阶跃响应）
        
        选择策略：
        1. 如果数据噪声大 → 使用积分-延迟模型
        2. 如果数据平滑 → 使用一阶模型
        3. 如果滞后明显 → 使用 FOPDT 模型
        """
        # 1. 评估数据质量（噪声水平）
        if len(y) > 10:
            noise_level = np.std(np.diff(y))
            signal_level = np.std(y)
            snr = signal_level / noise_level if noise_level > Config.EPSILON else 100
            
            # 2. 检测滞后（使用互相关，不依赖阶跃）
            if len(u) == len(y):
                dt = t[1] - t[0] if len(t) > 1 else 1.0
                L_est = SystemIdentifier._estimate_lag_from_correlation(u, y, dt)
            else:
                L_est = 0
            
            # 3. 选择模型
            if snr < 5 and L_est < 2:
                # 高噪声、小滞后 → 积分-延迟模型
                return SystemIdentifier._identify_integral_delay(t, y, u)
            elif L_est > 1:
                # 明显滞后 → FOPDT（使用改进的初始猜测）
                return SystemIdentifier.identify_fopdt(t, y, u)
            else:
                # 标准情况 → 一阶模型（使用改进的初始猜测）
                return SystemIdentifier.identify_first_order(t, y, u)
        else:
            return SystemIdentifier.identify_first_order(t, y, u)

    @staticmethod
    def _identify_integral_delay(t, y, u):
        """辨识积分-延迟模型参数（使用改进的最小二乘法）"""
        y0 = np.mean(y[:10]) if len(y) > 10 else np.mean(y)
        
        # 估计积分增益 K（使用斜率，不依赖阶跃）
        if len(y) > 20:
            dy_dt = np.gradient(y, t)
            # 去除噪声：使用中位数
            valid_mask = np.abs(dy_dt) < np.percentile(np.abs(dy_dt), 90)
            valid_u = u[valid_mask] if np.any(valid_mask) else u
            valid_dy_dt = dy_dt[valid_mask] if np.any(valid_mask) else dy_dt
            
            # 避免除零
            non_zero_u_mask = np.abs(valid_u) > Config.EPSILON
            if np.sum(non_zero_u_mask) > 0:
                K_est = np.median(valid_dy_dt[non_zero_u_mask] / valid_u[non_zero_u_mask])
            else:
                K_est = 0.1
        else:
            # 使用整体变化率
            if len(t) > 1:
                total_change = y[-1] - y[0]
                total_input = np.trapz(u, t)  # 输入积分
                K_est = total_change / total_input if abs(total_input) > Config.EPSILON else 0.1
            else:
                K_est = 0.1
        
        # 估计滞后 L（使用互相关，不依赖阶跃）
        dt = t[1] - t[0] if len(t) > 1 else 1.0
        L_est = SystemIdentifier._estimate_lag_from_correlation(u, y, dt)
        L_est = min(L_est, 5.0)  # 液位系统滞后通常较小
        
        initial_guess = [max(K_est, 0.01), L_est]
        bounds = ([0.001, 0.0], [1.0, 5.0])
        
        def residuals_id(params, t, u, y_measured, y0):
            y_pred = SystemIdentifier.integral_delay_model(params, t, u, y0)
            return y_pred - y_measured
        
        try:
            result = least_squares(
                residuals_id,
                initial_guess,
                args=(t, u, y, y0),
                bounds=bounds,
                method='trf',
                ftol=1e-6,
                xtol=1e-6,
                max_nfev=1000,
                verbose=0
            )
            K, L = result.x if result.success else initial_guess
        except Exception as e:
            print(f"⚠️ 积分-延迟模型辨识失败：{e}")
            K, L = initial_guess
        
        # 确保参数在合理范围
        K = np.clip(K, 0.001, 1.0)
        L = np.clip(L, 0.0, 5.0)
        
        return K, L

    def is_steady_state_for_level(self, level_data, setpoint, tol=1.0, std_tol=0.5, min_len=20):
        """
        针对液位控制的稳态判断
        
        特点：
        - 允许更大的波动范围
        - 考虑波动模式而非绝对稳定
        - 使用统计方法而非严格阈值
        """
        if len(level_data) < min_len:
            return False
        
        # 1. 均值接近设定点（允许更大偏差）
        mean_level = np.mean(level_data)
        if abs(mean_level - setpoint) > tol:
            return False
        
        # 2. 标准差在合理范围（液位允许一定波动）
        std_level = np.std(level_data)
        if std_level > std_tol:
            return False
        
        # 3. 趋势检测（使用线性回归）
        x = np.arange(len(level_data))
        coeffs = np.polyfit(x, level_data, 1)
        slope = coeffs[0]
        
        # 斜率应该很小（接近水平）
        if abs(slope) > std_tol / len(level_data):
            return False
        
        # 4. 波动模式检测（液位可能有周期性波动）
        # 如果波动是周期性的且幅度稳定，也算稳态
        if len(level_data) > 30:
            # 计算自相关，检测周期性
            autocorr = np.correlate(level_data - mean_level, 
                                   level_data - mean_level, mode='full')
            autocorr = autocorr[len(autocorr)//2:]
            if len(autocorr) > 0 and autocorr[0] > Config.EPSILON:
                autocorr = autocorr / autocorr[0]  # 归一化
                
                # 如果存在明显的周期性（自相关峰值 > 0.5），且波动幅度稳定
                if len(autocorr) > 10:
                    max_autocorr = np.max(autocorr[1:min(10, len(autocorr))])
                    if max_autocorr > 0.5 and std_level < std_tol * 0.8:
                        return True  # 周期性波动但稳定
        
        return True


# ----稳定性和扰动判断----
class StateAnalyzer:
    """系统状态分析工具：判断稳定性与扰动"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode
        # 用于检测异常模式的滑动窗口
        self.temp_window = deque(maxlen=Config.DETECTION_WINDOW)
        self.error_window = deque(maxlen=Config.DETECTION_WINDOW)
        self.valve_window = deque(maxlen=Config.DETECTION_WINDOW)
        self.time_window = deque(maxlen=Config.DETECTION_WINDOW)

        # 新增：自适应窗口大小
        self.current_window_size = Config.DETECTION_WINDOW
        self.window_growth_factor = 1.05  # 窗口增长因子

        # 新增：性能指标跟踪
        self.performance_history = deque(maxlen=100)
        self.disturbance_count = 0
        self.last_disturbance_time = 0
        
        # 优化：缓存统计结果，减少重复计算
        self._cached_stats = {}
        self._cache_valid = False
        self._last_data_hash = None

    def is_stable(self, temp_data, setpoint):
        """判断系统是否稳定在目标温度附近"""
        if len(temp_data) < Config.STABILIZATION_WINDOW:
            return False
        recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])

        # 根据模式调整稳定阈值
        if self.mode == Mode.ANTI_DISTURBANCE:
            threshold = Config.STABILIZATION_THRESHOLD * 1.2  # 放宽稳定阈值
        elif self.mode == Mode.ANTI_NOISE:
            threshold = Config.STABILIZATION_THRESHOLD * 1.1  # 略微放宽稳定阈值
        elif self.mode == Mode.FLOW_CONTROL:
            threshold = Config.STABILIZATION_THRESHOLD * 0.8  # 流量控制更严格
        else:
            threshold = Config.STABILIZATION_THRESHOLD

        # 均值需接近目标温度（±0.5℃）
        mean_temp = np.mean(recent_temps)
        if not (setpoint - 0.5 <= mean_temp <= setpoint + 0.5):
            return False
        # 波动判断
        deviations = np.abs(recent_temps - setpoint)
        return (np.all(deviations < threshold) and
                np.std(deviations) < threshold / 2)

    def _update_cached_stats(self, temp_data, valve_data, setpoint, window_size):
        """
        更新缓存的统计信息（优化：减少重复计算）
        
        Args:
            temp_data: 温度数据数组
            valve_data: 阀门数据数组
            setpoint: 目标温度
            window_size: 窗口大小
        """
        # 计算数据哈希，判断是否需要更新缓存
        data_hash = hash((len(temp_data), window_size, setpoint))
        if self._cache_valid and self._last_data_hash == data_hash:
            return  # 缓存有效，无需更新
        
        # 获取窗口数据
        recent_temps = np.array(temp_data[-window_size:])
        recent_valves = np.array(valve_data[-window_size:])
        errors = recent_temps - setpoint
        
        # 计算并缓存统计量
        self._cached_stats = {
            'mean_error': np.mean(errors),
            'std_error': np.std(errors),
            'max_error': np.max(np.abs(errors)),
            'temp_std': np.std(recent_temps),
            'recent_temps': recent_temps,
            'recent_valves': recent_valves,
            'errors': errors,
        }
        
        # 温度变化率
        if len(recent_temps) > 1:
            temp_deriv = np.diff(recent_temps)
            self._cached_stats['mean_abs_deriv'] = np.mean(np.abs(temp_deriv))
            self._cached_stats['temp_deriv'] = temp_deriv
        else:
            self._cached_stats['mean_abs_deriv'] = 0
            self._cached_stats['temp_deriv'] = np.array([0])
        
        # 阀门动作
        if len(recent_valves) > 1:
            valve_changes = np.diff(recent_valves)
            self._cached_stats['valve_activity'] = np.sum(np.abs(valve_changes))
            self._cached_stats['valve_changes'] = valve_changes
        else:
            self._cached_stats['valve_activity'] = 0
            self._cached_stats['valve_changes'] = np.array([0])
        
        # 趋势斜率
        if len(recent_temps) > 20:
            x = np.arange(len(recent_temps))
            coeffs = np.polyfit(x, recent_temps, 1)
            self._cached_stats['trend_slope'] = abs(coeffs[0])
        else:
            self._cached_stats['trend_slope'] = 0
        
        # 阀门振荡
        if len(recent_valves) > 10:
            valve_changes_abs = np.abs(np.diff(recent_valves))
            self._cached_stats['valve_oscillation'] = np.mean(valve_changes_abs)
        else:
            self._cached_stats['valve_oscillation'] = 0
        
        # 温度模式变化
        if len(recent_temps) > 30:
            first_half = recent_temps[:len(recent_temps) // 2]
            second_half = recent_temps[len(recent_temps) // 2:]
            self._cached_stats['temp_pattern_change'] = abs(np.std(second_half) - np.std(first_half))
        else:
            self._cached_stats['temp_pattern_change'] = 0
        
        # 预测残差
        if len(recent_temps) > 40:
            mid_point = len(recent_temps) // 2
            first_half = recent_temps[:mid_point]
            second_half = recent_temps[mid_point:mid_point + len(first_half)]
            predicted_second_half = np.full_like(second_half, np.mean(first_half))
            self._cached_stats['prediction_residual'] = np.mean(np.abs(second_half - predicted_second_half))
        else:
            self._cached_stats['prediction_residual'] = 0
        
        # 自相关性
        if len(recent_temps) > 20 and len(recent_temps) > 1:
            autocorr = np.corrcoef(recent_temps[:-1], recent_temps[1:])[0, 1]
            self._cached_stats['autocorr_strength'] = abs(autocorr) if not np.isnan(autocorr) else 0
        else:
            self._cached_stats['autocorr_strength'] = 0
        
        # 更新缓存状态
        self._cache_valid = True
        self._last_data_hash = data_hash

    def detect_instability_optimized(self, temp_data, setpoint, valve_data, time_data):
        """
        优化的扰动检测算法 - 增强对轻微扰动的检测能力（优化：使用缓存减少重复计算）
        """
        if len(temp_data) < Config.MIN_DETECTION_WINDOW:
            return False, ""

        # 获取当前窗口的数据 - 使用自适应窗口大小
        window_size = min(len(temp_data), self.current_window_size)
        window_size = int(window_size)
        
        # 更新缓存统计信息（仅在需要时计算）
        self._update_cached_stats(temp_data, valve_data, setpoint, window_size)
        
        # 从缓存中获取统计量（优化：避免重复计算）
        mean_error = self._cached_stats['mean_error']
        std_error = self._cached_stats['std_error']
        max_error = self._cached_stats['max_error']
        temp_std = self._cached_stats['temp_std']
        mean_abs_deriv = self._cached_stats['mean_abs_deriv']
        valve_activity = self._cached_stats['valve_activity']
        trend_slope = self._cached_stats['trend_slope']
        valve_oscillation = self._cached_stats['valve_oscillation']
        temp_pattern_change = self._cached_stats['temp_pattern_change']
        prediction_residual = self._cached_stats['prediction_residual']
        autocorr_strength = self._cached_stats['autocorr_strength']

        # 10. 基于模式的自适应阈值调整
        error_threshold = Config.ERROR_THRESHOLD
        std_threshold = Config.STD_THRESHOLD
        slope_threshold = Config.SLOPE_THRESHOLD
        valve_change_threshold = Config.VALVE_CHANGE_THRESHOLD

        if self.mode == Mode.ANTI_DISTURBANCE:
            # 抗扰动模式：降低检测灵敏度，避免误判
            error_threshold *= 1.5
            std_threshold *= 1.4
            slope_threshold *= 1.3
            valve_change_threshold *= 1.5
        elif self.mode == Mode.ANTI_NOISE:
            # 抗噪声模式：降低检测灵敏度，避免噪声误判
            error_threshold *= 1.8
            std_threshold *= 1.6
            slope_threshold *= 1.5
            valve_change_threshold *= 1.8
        elif self.mode == Mode.FLOW_CONTROL:
            # 流量控制模式：提高检测灵敏度，因为响应快
            error_threshold *= 0.7
            std_threshold *= 0.8
            slope_threshold *= 0.6
            valve_change_threshold *= 0.9

        # 11. 综合判断 - 使用加权评分机制
        scores = {}

        # 超调检测
        overshoot_score = (max_error / (error_threshold * 0.7)) * (mean_error / 0.8) * (std_error / 0.4)
        if overshoot_score > 1.0:
            scores['overshoot'] = overshoot_score

        # 稳态误差检测
        steady_error_score = abs(mean_error) / 1.0 * std_error / 0.8
        if steady_error_score > 1.0 and std_error < 0.8:
            scores['steady_error'] = steady_error_score

        # 系统振荡检测
        oscillation_score = std_error / std_threshold * mean_abs_deriv / slope_threshold
        if oscillation_score > 1.0:
            scores['oscillation'] = oscillation_score

        # 阀门过度动作检测
        valve_score = valve_activity / valve_change_threshold * std_error / 0.5
        if valve_score > 1.0:
            scores['valve'] = valve_score

        # 趋势性变化检测
        trend_score = trend_slope / slope_threshold * std_error / 0.4
        if trend_score > 1.0:
            scores['trend'] = trend_score

        # 阀门振荡检测
        valve_oscillation_score = valve_oscillation / 2.0 * std_error / 0.3
        if valve_oscillation_score > 1.0:
            scores['valve_oscillation'] = valve_oscillation_score

        # 温度模式变化检测
        pattern_score = temp_pattern_change / 0.5
        if pattern_score > 1.0:
            scores['pattern'] = pattern_score

        # 预测模型异常检测
        prediction_score = prediction_residual / 0.6 * std_error / 0.4
        if prediction_score > 1.0:
            scores['prediction'] = prediction_score

        # 自相关性异常检测
        autocorr_score = autocorr_strength / 0.8 * std_error / 0.5
        if autocorr_score > 1.0:
            scores['autocorr'] = autocorr_score

        # 传感器漂移或控制阀磨损等轻微扰动的检测
        drift_score = std_error / 0.4 * valve_oscillation / 1.5
        if drift_score > 1.0:
            scores['drift'] = drift_score

        # 判断是否为扰动
        is_disturbance = False
        disturbance_type = ""

        if scores:
            # 选择最高分的扰动类型
            max_score_type = max(scores.keys(), key=lambda k: scores[k])
            max_score = scores[max_score_type]

            # 根据检测敏感度调整阈值
            detection_threshold = 1.0 * (2.0 - Config.DETECTION_SENSITIVITY)  # 敏感度越高，阈值越低

            if max_score > detection_threshold:
                is_disturbance = True
                if max_score_type == 'overshoot':
                    disturbance_type = f"超调量大({max_error:.1f}℃)"
                elif max_score_type == 'steady_error':
                    disturbance_type = f"稳态误差({mean_error:.1f}℃)"
                elif max_score_type == 'oscillation':
                    disturbance_type = f"系统振荡(σ={std_error:.2f})"
                elif max_score_type == 'valve':
                    disturbance_type = f"控制不稳定(阀门动作={valve_activity:.1f})"
                elif max_score_type == 'trend':
                    disturbance_type = f"趋势性偏离(斜率={trend_slope:.3f})"
                elif max_score_type == 'valve_oscillation':
                    disturbance_type = f"阀门振荡({valve_oscillation:.2f})"
                elif max_score_type == 'pattern':
                    disturbance_type = f"温度模式变化({temp_pattern_change:.2f})"
                elif max_score_type == 'prediction':
                    disturbance_type = f"预测异常({prediction_residual:.2f})"
                elif max_score_type == 'autocorr':
                    disturbance_type = f"自相关异常({autocorr_strength:.2f})"
                elif max_score_type == 'drift':
                    disturbance_type = f"系统参数漂移(σ={std_error:.2f}, 阀门={valve_oscillation:.2f})"
                else:
                    disturbance_type = max_score_type

        # 12. 自适应窗口调整
        if Config.ADAPTIVE_DETECTION_ENABLED:
            if is_disturbance:
                # 扰动时增大窗口以获得更稳定的检测结果
                self.current_window_size = min(self.current_window_size * self.window_growth_factor,
                                               Config.MAX_DETECTION_WINDOW)
                self.disturbance_count += 1
                self.last_disturbance_time = time_data[-1] if time_data else 0
        
        # 标记缓存失效，以便下次调用时重新计算（优化：确保数据一致性）
        self._cache_valid = False

        return is_disturbance, disturbance_type

    def evaluate_stability_comprehensive(self, temp_data, setpoint, valve_data, time_data, pid_params=None):
        """
        全面评估整个回路的稳定性
        
        评估维度包括：
        1. 时域稳定性指标：稳态误差、超调量、调节时间、振荡次数、标准差
        2. 频域稳定性指标：主要振荡频率、频域能量分布
        3. 控制性能指标：控制努力、响应速度
        4. 鲁棒性指标：对扰动的恢复能力
        
        Args:
            temp_data: 温度数据数组
            setpoint: 目标温度
            valve_data: 阀门数据数组
            time_data: 时间数据数组
            pid_params: PID参数字典，包含kp, ki, kd（可选，用于理论分析）
        
        Returns:
            dict: 包含所有稳定性评估指标的字典
            
        Usage Example（使用示例）:
            # 1. 基本使用
            state_analyzer = StateAnalyzer(mode=Mode.STANDARD)
            stability_result = state_analyzer.evaluate_stability_comprehensive(
                temp_data=temp_data,
                setpoint=setpoint,
                valve_data=valve_data,
                time_data=time_data
            )
            
            # 2. 查看评估结果
            print(f"综合评分: {stability_result['overall_stability']['score']}/100")
            print(f"稳定性等级: {stability_result['overall_stability']['level']}")
            
            # 3. 查看时域指标
            time_metrics = stability_result['time_domain_metrics']
            print(f"稳态误差: {time_metrics['steady_state_error']['abs']}℃")
            print(f"波动性: {time_metrics['variability']['std']}")
            
            # 4. 查看频域指标
            freq_metrics = stability_result['frequency_domain_metrics']
            if 'dominant_frequency' in freq_metrics:
                print(f"主要振荡频率: {freq_metrics['dominant_frequency']['value']} Hz")
            
            # 5. 查看改进建议
            for rec in stability_result['recommendations']:
                print(f"[{rec['priority']}] {rec['issue']}: {rec['suggestion']}")
            
            # 6. 在控制循环中的典型使用场景：
            #    - 系统达到稳态时评估（见代码行3108-3156）
            #    - 定期监控稳定性（见代码行3369-3387）
            #    - 扰动恢复后评估（见代码行3335-3349）
        """
        if len(temp_data) < 30:
            return {
                "error": "数据点不足，无法进行稳定性评估",
                "data_points": len(temp_data)
            }
        
        # 转换为numpy数组
        temp_array = np.array(temp_data)
        valve_array = np.array(valve_data)
        time_array = np.array(time_data) if time_data else np.arange(len(temp_data))
        errors = temp_array - setpoint
        
        # 计算采样间隔
        if len(time_array) > 1:
            dt = np.mean(np.diff(time_array)) if len(np.unique(np.diff(time_array))) > 1 else np.diff(time_array)[0]
            fs = 1.0 / dt if dt > 0 else 1.0
        else:
            dt = 1.0
            fs = 1.0
        
        # ========== 1. 时域稳定性指标 ==========
        stability_metrics = {}
        
        # 1.1 稳态误差
        recent_window = min(50, len(temp_array))
        recent_errors = errors[-recent_window:]
        steady_state_error = np.mean(recent_errors)
        steady_state_error_abs = np.abs(steady_state_error)
        stability_metrics['steady_state_error'] = {
            'mean': float(steady_state_error),
            'abs': float(steady_state_error_abs),
            'status': 'good' if steady_state_error_abs < 0.5 else ('acceptable' if steady_state_error_abs < 1.0 else 'poor')
        }
        
        # 1.2 标准差（波动程度）
        temp_std = np.std(recent_errors)
        stability_metrics['variability'] = {
            'std': float(temp_std),
            'status': 'stable' if temp_std < 0.5 else ('moderate' if temp_std < 1.0 else 'unstable')
        }
        
        # 1.3 超调量
        if len(errors) > 0:
            max_overshoot = np.max(errors) if np.max(errors) > 0 else 0
            max_undershoot = abs(np.min(errors)) if np.min(errors) < 0 else 0
            stability_metrics['overshoot'] = {
                'max_overshoot': float(max_overshoot),
                'max_undershoot': float(max_undershoot),
                'status': 'good' if max_overshoot < 1.0 and max_undershoot < 1.0 else ('acceptable' if max_overshoot < 2.0 else 'poor')
            }
        else:
            stability_metrics['overshoot'] = {'max_overshoot': 0, 'max_undershoot': 0, 'status': 'unknown'}
        
        # 1.4 调节时间（settling time）- 进入稳态的时间
        settling_time = None
        settling_threshold = 0.05 * abs(setpoint - temp_array[0]) if abs(setpoint - temp_array[0]) > 0.1 else 0.5
        for i in range(len(errors) - 1, max(0, len(errors) - 100), -1):
            if abs(errors[i]) <= settling_threshold:
                # 检查后续是否持续在阈值内
                window_check = min(20, len(errors) - i)
                if window_check > 0 and np.all(np.abs(errors[i:i+window_check]) <= settling_threshold * 1.5):
                    settling_time = float(time_array[i] - time_array[0]) if len(time_array) > 1 else float(i)
                    break
        
        stability_metrics['settling_time'] = {
            'value': settling_time,
            'status': 'fast' if settling_time and settling_time < 100 else ('moderate' if settling_time and settling_time < 300 else 'slow')
        }
        
        # 1.5 振荡次数（零交叉次数）
        error_sign_changes = np.sum(np.diff(np.sign(errors)) != 0)
        oscillation_count = error_sign_changes // 2  # 每两次符号变化算一次振荡
        stability_metrics['oscillation'] = {
            'count': int(oscillation_count),
            'frequency': float(oscillation_count / (time_array[-1] - time_array[0])) if len(time_array) > 1 and (time_array[-1] - time_array[0]) > 0 else 0,
            'status': 'stable' if oscillation_count < 5 else ('moderate' if oscillation_count < 15 else 'unstable')
        }
        
        # 1.6 趋势分析
        if len(temp_array) > 20:
            x = np.arange(len(temp_array))
            coeffs = np.polyfit(x, temp_array, 1)
            trend_slope = coeffs[0]
            stability_metrics['trend'] = {
                'slope': float(trend_slope),
                'status': 'stable' if abs(trend_slope) < 0.01 else ('drifting' if abs(trend_slope) < 0.05 else 'unstable')
            }
        else:
            stability_metrics['trend'] = {'slope': 0, 'status': 'unknown'}
        
        # ========== 2. 频域稳定性指标 ==========
        frequency_metrics = {}
        
        if len(temp_array) > 30:
            # 去除趋势
            temp_detrended = temp_array - np.mean(temp_array)
            
            # FFT分析
            fft_vals = np.fft.fft(temp_detrended)
            fft_freqs = np.fft.fftfreq(len(temp_detrended), dt) if dt > 0 else np.fft.fftfreq(len(temp_detrended))
            fft_magnitude = np.abs(fft_vals)
            
            # 只考虑正频率
            positive_freq_idx = fft_freqs > 0
            positive_freqs = fft_freqs[positive_freq_idx]
            positive_magnitude = fft_magnitude[positive_freq_idx]
            
            if len(positive_freqs) > 0:
                # 主要振荡频率
                dominant_freq_idx = np.argmax(positive_magnitude[1:]) + 1  # 跳过DC分量
                dominant_freq = positive_freqs[dominant_freq_idx]
                dominant_magnitude = positive_magnitude[dominant_freq_idx]
                
                frequency_metrics['dominant_frequency'] = {
                    'value': float(dominant_freq),
                    'magnitude': float(dominant_magnitude),
                    'period': float(1.0 / dominant_freq) if dominant_freq > 0 else 0
                }
                
                # 频域能量分布
                total_energy = np.sum(positive_magnitude ** 2)
                low_freq_energy = np.sum(positive_magnitude[positive_freqs < 0.01] ** 2) if np.any(positive_freqs < 0.01) else 0
                mid_freq_energy = np.sum(positive_magnitude[(positive_freqs >= 0.01) & (positive_freqs < 0.1)] ** 2)
                high_freq_energy = np.sum(positive_magnitude[positive_freqs >= 0.1] ** 2)
                
                frequency_metrics['energy_distribution'] = {
                    'low_freq_ratio': float(low_freq_energy / total_energy) if total_energy > 0 else 0,
                    'mid_freq_ratio': float(mid_freq_energy / total_energy) if total_energy > 0 else 0,
                    'high_freq_ratio': float(high_freq_energy / total_energy) if total_energy > 0 else 0,
                    'status': 'stable' if low_freq_energy / total_energy > 0.7 else ('moderate' if low_freq_energy / total_energy > 0.5 else 'unstable')
                }
            else:
                frequency_metrics['dominant_frequency'] = {'value': 0, 'magnitude': 0, 'period': 0}
                frequency_metrics['energy_distribution'] = {'low_freq_ratio': 0, 'mid_freq_ratio': 0, 'high_freq_ratio': 0, 'status': 'unknown'}
        else:
            frequency_metrics['error'] = '数据点不足，无法进行频域分析'
        
        # ========== 3. 控制性能指标 ==========
        control_metrics = {}
        
        # 3.1 控制努力（阀门动作幅度）
        if len(valve_array) > 1:
            valve_changes = np.diff(valve_array)
            control_effort = np.mean(np.abs(valve_changes))
            control_effort_total = np.sum(np.abs(valve_changes))
            
            control_metrics['control_effort'] = {
                'mean_change': float(control_effort),
                'total_change': float(control_effort_total),
                'status': 'efficient' if control_effort < 2.0 else ('moderate' if control_effort < 5.0 else 'excessive')
            }
            
            # 阀门振荡检测
            valve_oscillation = np.std(valve_changes)
            control_metrics['valve_oscillation'] = {
                'std': float(valve_oscillation),
                'status': 'stable' if valve_oscillation < 1.0 else ('moderate' if valve_oscillation < 3.0 else 'unstable')
            }
        else:
            control_metrics['control_effort'] = {'mean_change': 0, 'total_change': 0, 'status': 'unknown'}
            control_metrics['valve_oscillation'] = {'std': 0, 'status': 'unknown'}
        
        # 3.2 响应速度（上升时间）
        if len(temp_array) > 10:
            initial_temp = temp_array[0]
            target_range = setpoint * 0.9  # 90%的目标值
            if abs(setpoint - initial_temp) > 0.1:
                rise_time = None
                for i in range(len(temp_array)):
                    if temp_array[i] >= target_range:
                        rise_time = float(time_array[i] - time_array[0]) if len(time_array) > 1 else float(i)
                        break
                control_metrics['rise_time'] = {
                    'value': rise_time,
                    'status': 'fast' if rise_time and rise_time < 50 else ('moderate' if rise_time and rise_time < 150 else 'slow')
                }
            else:
                control_metrics['rise_time'] = {'value': None, 'status': 'already_at_setpoint'}
        else:
            control_metrics['rise_time'] = {'value': None, 'status': 'unknown'}
        
        # ========== 4. 综合稳定性评分 ==========
        # 基于各项指标计算综合稳定性分数（0-100）
        stability_score = 100.0
        
        # 稳态误差扣分
        if steady_state_error_abs > 0.5:
            stability_score -= min(20, steady_state_error_abs * 10)
        
        # 波动性扣分
        if temp_std > 0.5:
            stability_score -= min(20, temp_std * 15)
        
        # 超调扣分
        if max_overshoot > 1.0:
            stability_score -= min(15, max_overshoot * 7)
        
        # 振荡扣分
        if oscillation_count > 5:
            stability_score -= min(15, (oscillation_count - 5) * 1.5)
        
        # 趋势漂移扣分
        if abs(trend_slope) > 0.01:
            stability_score -= min(10, abs(trend_slope) * 100)
        
        # 控制努力扣分（过度控制）
        if control_effort > 5.0:
            stability_score -= min(10, (control_effort - 5.0) * 2)
        
        stability_score = max(0, min(100, stability_score))
        
        # 稳定性等级
        if stability_score >= 80:
            stability_level = 'excellent'
        elif stability_score >= 60:
            stability_level = 'good'
        elif stability_score >= 40:
            stability_level = 'acceptable'
        else:
            stability_level = 'poor'
        
        # ========== 5. 鲁棒性评估（基于历史扰动恢复能力） ==========
        robustness_metrics = {}
        
        # 检测扰动后的恢复能力
        if hasattr(self, 'disturbance_count') and self.disturbance_count > 0:
            robustness_metrics['disturbance_recovery'] = {
                'disturbance_count': int(self.disturbance_count),
                'status': 'good' if self.disturbance_count < 3 else ('moderate' if self.disturbance_count < 5 else 'poor')
            }
        else:
            robustness_metrics['disturbance_recovery'] = {
                'disturbance_count': 0,
                'status': 'no_disturbance_detected'
            }
        
        # ========== 6. 综合评估结果 ==========
        comprehensive_result = {
            'overall_stability': {
                'score': float(stability_score),
                'level': stability_level,
                'status': 'stable' if stability_score >= 60 else 'unstable'
            },
            'time_domain_metrics': stability_metrics,
            'frequency_domain_metrics': frequency_metrics,
            'control_performance_metrics': control_metrics,
            'robustness_metrics': robustness_metrics,
            'recommendations': self._generate_stability_recommendations(
                stability_metrics, frequency_metrics, control_metrics, stability_score
            )
        }
        
        return comprehensive_result
    
    def _generate_stability_recommendations(self, stability_metrics, frequency_metrics, control_metrics, stability_score):
        """根据稳定性评估结果生成改进建议"""
        recommendations = []
        
        # 稳态误差建议
        if stability_metrics['steady_state_error']['abs'] > 1.0:
            recommendations.append({
                'issue': '稳态误差较大',
                'suggestion': '增加积分项（Ki）以消除稳态误差，或检查系统是否存在外部扰动',
                'priority': 'high'
            })
        
        # 波动性建议
        if stability_metrics['variability']['std'] > 1.0:
            recommendations.append({
                'issue': '系统波动较大',
                'suggestion': '减小比例增益（Kp）或增加微分项（Kd）以提高系统稳定性',
                'priority': 'high'
            })
        
        # 超调建议
        if stability_metrics['overshoot']['max_overshoot'] > 2.0:
            recommendations.append({
                'issue': '超调量过大',
                'suggestion': '减小比例增益（Kp）或增加微分项（Kd）以减少超调',
                'priority': 'medium'
            })
        
        # 振荡建议
        if stability_metrics['oscillation']['count'] > 15:
            recommendations.append({
                'issue': '系统振荡频繁',
                'suggestion': '减小比例增益（Kp），增加积分时间（Ti），或调整微分项（Kd）',
                'priority': 'high'
            })
        
        # 控制努力建议
        if control_metrics.get('control_effort', {}).get('mean_change', 0) > 5.0:
            recommendations.append({
                'issue': '控制动作过于频繁',
                'suggestion': '减小比例增益（Kp），增加积分时间（Ti），或添加死区以减少不必要的控制动作',
                'priority': 'medium'
            })
        
        # 频域建议
        if 'energy_distribution' in frequency_metrics:
            if frequency_metrics['energy_distribution'].get('high_freq_ratio', 0) > 0.3:
                recommendations.append({
                    'issue': '高频噪声较多',
                    'suggestion': '增加低通滤波器或减小微分项（Kd）以减少对高频噪声的敏感度',
                    'priority': 'low'
                })
        
        # 综合建议
        if stability_score < 40:
            recommendations.append({
                'issue': '系统稳定性较差',
                'suggestion': '建议重新进行PID参数整定，考虑使用更保守的参数设置',
                'priority': 'high'
            })
        elif stability_score < 60:
            recommendations.append({
                'issue': '系统稳定性一般',
                'suggestion': '可以尝试微调PID参数以进一步改善系统性能',
                'priority': 'medium'
            })
        
        return recommendations


class PlotManager:
    """可视化管理器：初始化图表、更新绘图与参数显示"""

    def __init__(self):
        # 确保中文显示
        plt.rcParams["font.family"] = ["Heiti TC"]
        plt.rcParams['axes.unicode_minus'] = False
        self.fig = None
        self.plot_data = None

    def init_real_time_fig(self, t, u, setpoint, system_params, pid_params, response_data, true_params, disturbances,
                           pid_mode, system_mode, tuning_method):
        """初始化实时监控图表"""
        self.fig = plt.figure(figsize=(14, 14))
        gs = gridspec.GridSpec(6, 2)

        # 1. 输入信号曲线
        ax0 = self.fig.add_subplot(gs[0, 0])
        ax0.plot(t, u, 'b-')
        ax0.set_title('系统输入信号（非阶跃）')
        ax0.set_xlabel('时间 (s)')
        ax0.set_ylabel('阀门开度 (%)')
        ax0.grid(True, alpha=0.3)

        # 2. 系统响应与辨识模型对比
        ax1 = self.fig.add_subplot(gs[0, 1])
        K, T, L = system_params['K'], system_params['T'], system_params['L']
        identified_y = SystemIdentifier.fopdt_model([K, T, L], t, u, Config.INIT_TEMPERATURE)
        ax1.plot(t, response_data, 'b-', label='实际响应', linewidth=1.5)
        ax1.plot(t, identified_y, 'r--', label='辨识模型', linewidth=1.5)
        ax1.set_title(
            f'系统响应与辨识模型对比 (PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]})')
        ax1.set_xlabel('时间 (s)')
        ax1.set_ylabel('温度 (℃)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 3. 温度控制曲线（不含无控制器模拟）
        ax2 = self.fig.add_subplot(gs[1:3, :])
        ax2.set_xlim(0, 10000)  # 初始设置，后续会动态调整
        ax2.set_ylim(Config.INIT_TEMPERATURE - 15, setpoint + 25)
        ax2.axhline(setpoint, color='r', linestyle='--', label='设定值', linewidth=1.5)
        ax2.axhline(Config.INIT_TEMPERATURE, color='orange', linestyle='-.',
                    label=f'初始温度 {Config.INIT_TEMPERATURE}℃', linewidth=1.5)

        # 扰动标记 - 仅在使用仿真数据时显示
        disturbance_colors = {
            DisturbanceType.OVERSHOOT: "red",
            DisturbanceType.STEADY_ERROR: "orange",
            DisturbanceType.SLOW_RECOVERY: "brown",
            DisturbanceType.VALVE_STICTION: "purple",
            DisturbanceType.SENSOR_DRIFT: "pink",
            DisturbanceType.HEAT_LOSS: "gray",
            DisturbanceType.CONTROL_VALVE_WEAR: "olive",
            DisturbanceType.THERMAL_INERTIA: "cyan",
            DisturbanceType.FLOW_NOISE: "yellow",  # 新增
            DisturbanceType.FLOW_STICTION: "darkgreen"  # 新增
        }

        # 为每种扰动类型添加图例
        legend_handles = []
        legend_labels = []
        for i, dist_type in enumerate(Config.DISTURBANCE_TYPES):
            color = disturbance_colors[dist_type["type"]]
            legend_handles.append(plt.Rectangle((0, 0), 1, 1, color=color, alpha=0.2))
            legend_labels.append(f'{dist_type["description"]} ({dist_type["type"]})')

        # 仅在使用仿真数据时绘制扰动区域
        for d in disturbances:
            ax2.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)

        ax2.set_title(
            f'温度控制曲线（含扰动与参数更新 - PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]}）')
        ax2.set_xlabel('时间 (s)')
        ax2.set_ylabel('温度 (℃)')
        ax2.legend(legend_handles, legend_labels, loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)

        # 绘制实际响应温度曲线（移除了无控制器模拟）
        temp_line, = ax2.plot([], [], 'b-', label='实际响应温度', linewidth=1.5)
        # 添加无PID控制的温度曲线
        no_pid_temp_line, = ax2.plot([], [], 'm--', label='无PID控制温度', linewidth=1.5, alpha=0.7)
        stabilization_line = ax2.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
        update_lines = []  # 参数更新线
        update_marker, = ax2.plot([], [], 'bo', markersize=6, label='参数更新点')

        # 新PID参数下的仿真曲线
        new_pid_line, = ax2.plot([], [], 'g--', label='新PID参数仿真', linewidth=1.5, alpha=0.7)

        # 4. 阀门开度曲线
        ax3 = self.fig.add_subplot(gs[3, 0])
        ax3.set_xlim(0, 10000)  # 初始设置，后续会动态调整
        ax3.set_ylim(0, 100)
        # 仅在使用仿真数据时绘制扰动区域
        for d in disturbances:
            ax3.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)
        ax3.set_title('阀门开度变化')
        ax3.set_xlabel('时间 (s)')
        ax3.set_ylabel('开度 (%)')
        ax3.grid(True, alpha=0.3)
        valve_line, = ax3.plot([], [], 'g-', label='阀门开度', linewidth=1.5)
        ax3.legend()

        # 5. 控制误差曲线
        ax4 = self.fig.add_subplot(gs[3, 1])
        ax4.set_xlim(0, 10000)  # 初始设置，后续会动态调整
        ax4.set_ylim(-15, 15)
        ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
        # 仅在使用仿真数据时绘制扰动区域
        for d in disturbances:
            ax4.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)
        ax4.set_title('控制误差曲线')
        ax4.set_xlabel('时间 (s)')
        ax4.set_ylabel('误差 (℃)')
        ax4.grid(True, alpha=0.3)
        error_line, = ax4.plot([], [], 'r-', label='控制误差', linewidth=1.5)
        ax4.legend()

        # 6. PID参数变化曲线
        ax5 = self.fig.add_subplot(gs[4, :])
        ax5.set_xlim(0, 10000)  # 初始设置，后续会动态调整
        ax5.set_ylim(0, 6)
        # 仅在使用仿真数据时绘制扰动区域
        for d in disturbances:
            ax5.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)
        ax5.set_title(
            f'PID参数变化趋势 (PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]})')
        ax5.set_xlabel('时间 (s)')
        ax5.set_ylabel('参数值（Ti/10，Td*2）')
        ax5.grid(True, alpha=0.3)
        pb_line, = ax5.plot([], [], 'r-', label='Pb', linewidth=1.5)
        ti_line, = ax5.plot([], [], 'g-', label='Ti/10', linewidth=1.5)
        td_line, = ax5.plot([], [], 'b-', label='Td*2', linewidth=1.5)
        ax5.legend()

        # 7. 参数文本显示
        ax6 = self.fig.add_subplot(gs[5, :])
        ax6.axis('off')
        params_text = ax6.text(0.05, 0.5, "", fontsize=10,
                               verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
        self.update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'],
                                pid_mode=pid_mode, system_mode=system_mode, tuning_method=tuning_method)

        # Lambda参数滑块和PID参数滑块
        plt.subplots_adjust(bottom=0.25)
        
        # Lambda滑块
        ax_lambda_slider = plt.axes([0.2, 0.15, 0.65, 0.03])
        lambda_slider = Slider(
            ax=ax_lambda_slider,
            label='Lambda 参数（减小→响应更快）',
            valmin=0.3 * system_params['T'],
            valmax=2 * system_params['T'],
            valinit=system_params['T'] * 0.6
        )
        
        # PID参数滑块
        ax_pb_slider = plt.axes([0.2, 0.11, 0.65, 0.03])
        pb_slider = Slider(
            ax=ax_pb_slider,
            label='Pb (比例带)',
            valmin=Config.PB_MIN,
            valmax=Config.PB_MAX,
            valinit=pid_params['Pb']
        )
        
        ax_ti_slider = plt.axes([0.2, 0.07, 0.65, 0.03])
        ti_slider = Slider(
            ax=ax_ti_slider,
            label='Ti (积分时间)',
            valmin=Config.TI_MIN,
            valmax=Config.TI_MAX,
            valinit=pid_params['Ti']
        )
        
        ax_td_slider = plt.axes([0.2, 0.03, 0.65, 0.03])
        td_slider = Slider(
            ax=ax_td_slider,
            label='Td (微分时间)',
            valmin=Config.TD_MIN,
            valmax=Config.TD_MAX,
            valinit=pid_params['Td']
        )
        
        # 添加预览轨迹线（用虚线表示）
        preview_line, = ax2.plot([], [], 'c--', label='PID参数预览轨迹', linewidth=2, alpha=0.8)

        plt.ion()
        plt.tight_layout(rect=[0, 0.1, 1, 1])
        plt.show(block=False)

        self.plot_data = {
            'axes': (ax2, ax3, ax4, ax5),
            'lines': (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line),
            'text': params_text,
            'slider': lambda_slider,
            'pid_sliders': (pb_slider, ti_slider, td_slider),
            'markers': (stabilization_line, update_lines, update_marker),
            'colors': disturbance_colors
        }
        return self.fig, self.plot_data

    @staticmethod
    def update_params_text(text_obj, system_params, pid_params, lambda_val, update_count=0, initial_params=None,
                           pid_mode=PIDMode.STANDARD, system_mode=Mode.STANDARD, tuning_method=TuningMethod.LAMBDA):
        """更新参数显示文本"""
        K, T, L = system_params['K'], system_params['T'], system_params['L']
        Pb, Ti, Td = pid_params['Pb'], pid_params['Ti'], pid_params['Td']
        status = f"（已更新{update_count}次）" if update_count > 0 else ""

        # 初始参数对比
        initial_text = ""
        if initial_params and update_count > 0:
            init_Pb, init_Ti, init_Td = initial_params
            initial_text = f"""初始有效参数:
    Pb = {init_Pb:.2f}, Ti = {init_Ti:.1f}s, Td = {init_Td:.1f}s
    """

        text = f"""系统辨识参数:
    增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s

{initial_text}当前PID参数 {status}(λ={lambda_val:.1f}, PID模式:{Config.PID_MODES[pid_mode]}, 系统模式:{Config.MODES[system_mode]}, 整定方法:{Config.TUNING_METHODS[tuning_method]}):
    比例带 Pb = {Pb:.2f}%
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

目标温度: {Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW}℃ | 初始温度: {Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0}℃"""
        text_obj.set_text(text)

    def update_plots(self, time_data, temp_data, valve_data, error_data, pb_data, ti_data, td_data,
                     update_lines, new_pid_time_data=None, new_pid_temp_data=None, no_pid_temp_data=None):
        """实时更新绘图数据"""
        (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line) = self.plot_data[
            'lines']
        (ax2, _, _, _) = self.plot_data['axes']
        _, _, update_marker = self.plot_data['markers']

        # 更新曲线数据
        temp_line.set_data(time_data, temp_data)
        valve_line.set_data(time_data, valve_data)
        error_line.set_data(time_data, error_data)
        pb_line.set_data(time_data, pb_data)
        ti_line.set_data(time_data, ti_data)
        td_line.set_data(time_data, td_data)

        # 更新新PID参数仿真曲线
        if new_pid_time_data is not None and new_pid_temp_data is not None:
            new_pid_line.set_data(new_pid_time_data, new_pid_temp_data)

        # 更新无PID控制的温度曲线
        if no_pid_temp_data is not None:
            no_pid_temp_line.set_data(time_data, no_pid_temp_data)

        # 更新x轴范围（动态扩展）
        if time_data:
            current_max_time = max(time_data)
            ax2.set_xlim(0, current_max_time * 1.1)
            self.plot_data['axes'][1].set_xlim(0, current_max_time * 1.1)  # ax3
            self.plot_data['axes'][2].set_xlim(0, current_max_time * 1.1)  # ax4
            self.plot_data['axes'][3].set_xlim(0, current_max_time * 1.1)  # ax5

        # 更新参数更新标记
        update_times = [line.get_xdata()[0] for line in update_lines]
        update_marker.set_data(update_times, [Config.TARGET_TEMPERATURE + 8] * len(update_times))

        # 更新标题
        current_time = time_data[-1] if time_data else 0
        ax2.set_title(f'温度控制曲线（当前时间：{current_time:.0f}s）')

        # 刷新画布
        self.fig.canvas.draw_idle()
        plt.pause(0.01)


class ControlMonitor:
    """控制监控主逻辑：协调系统、控制器、辨识器等模块运行"""

    def __init__(self):
        self.data_handler = DataHandler()
        self.plot_manager = PlotManager()
        self.identifier = SystemIdentifier()
        self.disturbance_generator = DisturbanceGenerator()
        self.logger = LoggerSetup.setup_logger()

    def run(self):
        """启动控制监控流程"""
        # 记录启动时间
        start_time = datetime.now()
        self.logger.info(f"控制监控系统启动 - 时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # 初始化配置
        Config.ensure_data_dir()

        # 选择数据来源
        t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.data_handler.choose_data_source(
            data_type="dynamic_response")

        # 标记是否使用JSON数据
        using_json_data = pv_data is not None

        # 自动检测场景并选择控制模式（传入数据用于场景检测）
        system_mode = self.data_handler.choose_mode(using_json_data=using_json_data, 
                                                    t=t, pv_data=pv_data, mv_data=mv_data)
        self.logger.info(f"选择系统控制模式: {Config.MODES[system_mode]}")

        # 选择降噪强度
        noise_reduction_level = self.data_handler.choose_noise_reduction_level()
        self.logger.info(f"选择降噪强度: {noise_reduction_level}")

        # 选择PID控制模式
        pid_mode = self.data_handler.choose_pid_mode()
        self.logger.info(f"选择PID控制模式: {Config.PID_MODES[pid_mode]}")

        # 选择PID整定方法
        tuning_method = self.data_handler.choose_tuning_method()
        self.logger.info(f"选择PID整定方法: {Config.TUNING_METHODS[tuning_method]}")

        # 初始化状态分析器
        state_analyzer = StateAnalyzer(mode=system_mode)
        self.disturbance_generator = DisturbanceGenerator(mode=system_mode)

        # 初始化系统与输入
        if system_mode == Mode.FLOW_CONTROL:
            # 流量控制模式使用不同系统
            initial_true_params = {'K': 1.0, 'T': 1.0, 'noise_level': 0.5}
            temp_system = FlowSystem(**initial_true_params, mode=system_mode)
        else:
            initial_true_params = {'K': 0.3, 'T': 20, 'L': 4, 'noise_level': 0.3}
            temp_system = TemperatureSystem(**initial_true_params, mode=system_mode)

        # 根据数据来源设置扰动生成
        if using_json_data:
            # 使用JSON数据时，不生成额外的随机扰动，因为JSON数据本身可能包含扰动
            disturbances = []
            print("📊 使用JSON数据，不生成额外随机扰动（JSON数据可能已包含扰动）")
        else:
            # 生成随机扰动（仿真模式）
            self.logger.info("生成随机扰动配置...")
            disturbances = self.disturbance_generator.generate_random_disturbances()
            self.logger.info(f"生成了 {len(disturbances)} 个随机扰动:")
            for i, d in enumerate(disturbances):
                self.logger.info(
                    f"  {i + 1}. {d['time']}s: {d['description']} (持续{d['duration']}s, 幅值{d['amplitude']:.1f}℃)")
                print(f"  {i + 1}. {d['time']}s: {d['description']} (持续{d['duration']}s, 幅值{d['amplitude']:.1f}℃)")

        if using_json_data:
            # 使用JSON数据作为实际温度曲线
            response_data = pv_data  # pv_data作为实际温度曲线
            u = mv_data if mv_data is not None else temp_system.generate_non_step_input(t)
            setpoint = sv_data if sv_data is not None else Config.TARGET_TEMPERATURE

            # 从JSON数据中获取初始PID参数
            if len(pb_data) > 0 and len(ti_data) > 0 and len(td_data) > 0:
                # 使用JSON中的PID参数作为初始参数
                init_pb = pb_data[0] if pb_data[0] != 0 else 100
                init_ti = ti_data[0] if ti_data[0] != 0 else 20
                init_td = td_data[0] if td_data[0] != 0 else 0
            else:
                # 如果没有有效的PID参数，则进行系统辨识
                # 新增：基于JSON数据的智能整定（自动场景检测）
                new_params = self.identifier.auto_tune_from_json(t, response_data, setpoint, tuning_method, system_mode, u_data=u)
                if new_params:
                    init_pb, init_ti, init_td = new_params['pb'], new_params['ti'], new_params['td']
                    detected_scenario = new_params.get('scenario', None)
                    print(f"✅ 基于JSON数据自动整定PID参数: Pb={init_pb:.2f}%, Ti={init_ti:.2f}s, Td={init_td:.2f}s")
                    if detected_scenario:
                        print(f"   检测到的场景: {detected_scenario}")
                else:
                    # 如果auto_tune_from_json失败，使用直接辨识
                    detected_scenario = self.identifier.detect_control_scenario(t, response_data, u)
                    if system_mode == Mode.FLOW_CONTROL:
                        K, T = self.identifier.identify_first_order(t, response_data, u)
                        L = 0.0  # 流量控制模式无滞后
                        init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)
                    else:
                        if detected_scenario == 'level':
                            params = self.identifier.identify_level_control_model(t, response_data, u)
                            if len(params) == 2:
                                K, L = params
                                T = 100
                            elif len(params) == 3:
                                K, T, L = params
                            else:
                                K, T = params
                                L = 0.0
                        else:
                            K, T, L = self.identifier.identify_fopdt(t, response_data, u)
                        init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)
        else:
            # 生成仿真数据（如未提供）
            initial_time = np.arange(0, 1000, 1)  # 初始生成1000个点
            if system_mode == Mode.FLOW_CONTROL:
                u = temp_system.generate_flow_input(initial_time)
            else:
                u = temp_system.generate_non_step_input(initial_time)
            response_data = temp_system.simulate_with_input(initial_time, u, disturbances)
            # 应用低通滤波到仿真生成的数据
            response_data = self.data_handler.apply_low_pass_filter(response_data)
            self.logger.info(
                f"对仿真生成的温度数据应用了低通滤波 (降噪强度: {noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]['cutoff_freq']})")

            # 如果需要对输入信号也应用滤波
            if Config.FILTER_APPLY_TO_INPUT:
                u = self.data_handler.apply_low_pass_filter(u)
                self.logger.info(
                    f"对仿真生成的输入信号应用了低通滤波 (降噪强度: {noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]['cutoff_freq']})")

            # 从仿真数据中获取初始PID参数（自动场景检测）
            detected_scenario = self.identifier.detect_control_scenario(initial_time, response_data, u)
            if system_mode == Mode.FLOW_CONTROL:
                K, T = self.identifier.identify_first_order(initial_time, response_data, u)
                L = 0.0  # 流量控制模式无滞后
                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)
            else:
                if detected_scenario == 'level':
                    params = self.identifier.identify_level_control_model(initial_time, response_data, u)
                    if len(params) == 2:
                        K, L = params
                        T = 100
                    elif len(params) == 3:
                        K, T, L = params
                    else:
                        K, T = params
                        L = 0.0
                else:
                    K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)
                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)

        # 初始参数辨识 - 自动场景检测
        print(
            f"\n全局初始值：{Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0}℃ | 目标值：{Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW}")
        print("正在辨识系统初始参数（K, T, L）...")
        
        # ========== 自动场景检测 ==========
        if using_json_data:
            detected_scenario = self.identifier.detect_control_scenario(t, response_data, u)
        else:
            detected_scenario = self.identifier.detect_control_scenario(initial_time, response_data, u)
        print(f"🔍 自动检测场景类型: {detected_scenario}")
        
        if using_json_data:
            # 使用JSON数据进行初始参数辨识
            # 根据场景选择预处理
            if detected_scenario == 'temperature':
                try:
                    t_proc, y_proc, u_proc = self.identifier.preprocess_temperature_data(t, response_data, u)
                    t, response_data, u = t_proc, y_proc, u_proc
                    print("✅ 已应用温控数据预处理")
                except:
                    pass
            elif detected_scenario == 'level':
                try:
                    t_proc, y_proc, u_proc = self.identifier.preprocess_level_data(t, response_data, u, noise_reduction='medium')
                    t, response_data, u = t_proc, y_proc, u_proc
                    print("✅ 已应用液位数据预处理")
                except:
                    pass
            
            # 根据场景选择模型
            if system_mode == Mode.FLOW_CONTROL:
                K, T = self.identifier.identify_first_order(t, response_data, u)
                L = 0.0
            elif detected_scenario == 'level':
                params = self.identifier.identify_level_control_model(t, response_data, u)
                if len(params) == 2:  # 积分-延迟模型
                    K, L = params
                    T = 100  # 大时间常数表示积分特性
                elif len(params) == 3:  # FOPDT模型
                    K, T, L = params
                else:  # 一阶模型
                    K, T = params
                L = 0.0
            else:
                # 温控场景：检测热损失并选择模型
                has_heat_loss = False
                ambient_temp = np.min(response_data) if len(response_data) > 0 else 0.0
                
                if len(response_data) > 200:
                    steady_segment = response_data[-100:]
                    if np.std(steady_segment) < 0.5:
                        x = np.arange(len(steady_segment))
                        coeffs = np.polyfit(x, steady_segment, 1)
                        if coeffs[0] < -0.01:
                            has_heat_loss = True
                            print(f"🔍 检测到热损失趋势，使用带热损失的FOPDT模型")
                
                if has_heat_loss:
                    K, T, L, alpha = self.identifier.identify_fopdt_with_heat_loss(t, response_data, u, ambient_temp)
                    print(f"🔍 带热损失FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}, α={alpha:.4f}")
                else:
                    K, T, L = self.identifier.identify_fopdt(t, response_data, u)
        else:
            # 使用仿真数据进行初始参数辨识
            # 根据场景选择预处理
            if detected_scenario == 'temperature':
                try:
                    initial_time_proc, response_data_proc, u_proc = self.identifier.preprocess_temperature_data(initial_time, response_data, u)
                    initial_time, response_data, u = initial_time_proc, response_data_proc, u_proc
                    print("✅ 已应用温控数据预处理")
                except:
                    pass
            elif detected_scenario == 'level':
                try:
                    initial_time_proc, response_data_proc, u_proc = self.identifier.preprocess_level_data(initial_time, response_data, u, noise_reduction='medium')
                    initial_time, response_data, u = initial_time_proc, response_data_proc, u_proc
                    print("✅ 已应用液位数据预处理")
                except:
                    pass
            
            # 根据场景选择模型
            if system_mode == Mode.FLOW_CONTROL:
                K, T = self.identifier.identify_first_order(initial_time, response_data, u)
                L = 0.0
            elif detected_scenario == 'level':
                params = self.identifier.identify_level_control_model(initial_time, response_data, u)
                if len(params) == 2:  # 积分-延迟模型
                    K, L = params
                    T = 100  # 大时间常数表示积分特性
                elif len(params) == 3:  # FOPDT模型
                    K, T, L = params
                else:  # 一阶模型
                    K, T = params
                L = 0.0
            else:
                # 温控场景：检测热损失并选择模型
                has_heat_loss = False
                ambient_temp = np.min(response_data) if len(response_data) > 0 else 0.0
                
                if len(response_data) > 200:
                    steady_segment = response_data[-100:]
                    if np.std(steady_segment) < 0.5:
                        x = np.arange(len(steady_segment))
                        coeffs = np.polyfit(x, steady_segment, 1)
                        if coeffs[0] < -0.01:
                            has_heat_loss = True
                            print(f"🔍 检测到热损失趋势，使用带热损失的FOPDT模型")
                
                if has_heat_loss:
                    K, T, L, alpha = self.identifier.identify_fopdt_with_heat_loss(initial_time, response_data, u, ambient_temp)
                    print(f"🔍 带热损失FOPDT辨识结果: K={K:.3f}, τ={T:.3f}, L={L:.3f}, α={alpha:.4f}")
                else:
                    K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)
        
        identified_params = {'K': K, 'T': T, 'L': L, 'scenario': detected_scenario}

        # 启动实时监控
        print(
            f"\n启动控制监控 (系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]})...")
        self._run_real_time_monitor(u,
                                    setpoint=Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW,
                                    true_params=initial_true_params,
                                    identified_params=identified_params, response_data=response_data,
                                    disturbances=disturbances, start_time=start_time, pid_mode=pid_mode,
                                    system_mode=system_mode, state_analyzer=state_analyzer,
                                    using_json_data=using_json_data,
                                    pb_data=pb_data, ti_data=ti_data, td_data=td_data, tuning_method=tuning_method)

    def _get_initial_params(self, K, T, L, tuning_method, system_mode, scenario=None):
        """
        统一的初始参数获取方法（优化：合并了流量控制和温度控制，支持场景自适应）
        
        Args:
            K: 静态增益
            T: 时间常数
            L: 滞后时间（流量控制模式下会被忽略）
            tuning_method: 整定方法
            system_mode: 系统模式
            scenario: 检测到的场景类型（'temperature' 或 'level'），如果为None则根据system_mode判断
            
        Returns:
            Tuple[float, float, float]: (pb, ti, td)
        """
        if system_mode == Mode.FLOW_CONTROL:
            # 流量控制模式：使用专门的流量整定方法
            # 对于流量控制，Cohen-Coon可能不太适用，统一使用Lambda方法
            return self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)
        
        # 根据场景选择整定方法
        if scenario is None:
            # 如果没有提供场景，根据T和L推断（简单启发式）
            if T > 50:  # 大时间常数，可能是温控
                scenario = 'temperature'
            else:
                scenario = 'level'  # 默认液位
        
        if tuning_method == TuningMethod.LAMBDA:
            if scenario == 'temperature':
                # 温控场景：使用温控专用整定方法
                return self.identifier.lambda_tuning_for_temperature_control(K, T, L, mode=system_mode)
            elif scenario == 'level':
                # 液位场景：使用液位专用整定方法
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.lambda_tuning(K, T, L, mode=system_mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            # Cohen-Coon方法主要用于FOPDT模型（温控场景）
            if scenario == 'level':
                # 液位场景如果使用积分-延迟模型，不适合Cohen-Coon，改用液位专用方法
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.cohen_coon_tuning(K, T, L)
        else:
            # 默认使用Lambda方法
            if scenario == 'temperature':
                return self.identifier.lambda_tuning_for_temperature_control(K, T, L, mode=system_mode)
            elif scenario == 'level':
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.lambda_tuning(K, T, L, mode=system_mode)

    def _run_real_time_monitor(self, u, setpoint, true_params, identified_params, response_data, disturbances,
                               start_time, pid_mode, system_mode, state_analyzer, using_json_data, pb_data, ti_data,
                               td_data, tuning_method):
        """实时监控主循环 - 无限运行版本"""
        # 创建初始时间数组
        initial_time = np.arange(len(response_data)) if len(response_data) > 0 else np.arange(len(u))

        # 数据存储列表
        time_data = []
        temp_data = []
        valve_data = []
        error_data = []
        pb_data_list = []
        ti_data_list = []
        td_data_list = []
        # 无PID控制的温度数据
        no_pid_temp_data = []

        # 初始化系统与控制器
        K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
        # 获取检测到的场景（如果有）
        detected_scenario = identified_params.get('scenario', None)

        # 根据是否使用JSON数据来初始化PID参数
        if using_json_data:
            # 使用JSON中的PID参数作为初始参数（如果存在且有效）
            if pb_data is not None and ti_data is not None and td_data is not None and len(pb_data) > 0 and len(
                    ti_data) > 0 and len(td_data) > 0:
                init_pb = pb_data[0] if pb_data[0] != 0 else 100
                init_ti = ti_data[0] if ti_data[0] != 0 else 20
                init_td = td_data[0] if td_data[0] != 0 else 0
            else:
                # 如果JSON中没有PID参数，使用辨识结果（传入场景信息）
                if system_mode == Mode.FLOW_CONTROL:
                    L = 0.0  # 流量控制模式无滞后
                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)
        else:
            # 使用辨识得到的参数（传入场景信息）
            if system_mode == Mode.FLOW_CONTROL:
                L = 0.0  # 流量控制模式无滞后
            init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode, scenario=detected_scenario)

        if system_mode == Mode.FLOW_CONTROL:
            system = FlowSystem(**true_params, mode=system_mode)
        else:
            system = TemperatureSystem(**true_params, mode=system_mode)
        pid = PIDController(pb=init_pb, ti=init_ti, td=init_td, dt=1, mode=pid_mode, system_mode=system_mode)

        # 初始化图表（在PID参数确定后）
        initial_pid_params = {'Pb': init_pb, 'Ti': init_ti, 'Td': init_td}
        fig, plot_data = self.plot_manager.init_real_time_fig(initial_time, u, setpoint, identified_params,
                                                              initial_pid_params, response_data, true_params,
                                                              disturbances, pid_mode, system_mode, tuning_method)
        (ax2, _, _, _) = plot_data['axes']
        params_text = plot_data['text']
        lambda_slider = plot_data['slider']
        pb_slider, ti_slider, td_slider = plot_data['pid_sliders']
        stabilization_line, update_lines, _ = plot_data['markers']
        temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line = plot_data[
            'lines']

        # 初始化当前温度
        if using_json_data:
            current_var = response_data[0] if len(response_data) > 0 else (
                Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0)
        else:
            current_var = Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0

        # 状态变量
        stabilization_time = None
        tuning_enabled = True  # 立即启用整定功能，不需要等待稳态
        params_update_count = 0
        initial_valid_params = (pid.pb, pid.ti, pid.td)  # 记录初始参数
        recovery_status = {d["type"]: False for d in disturbances}

        # 为扰动添加更新标记属性
        for d in disturbances:
            d['updated'] = False  # 标记是否已更新参数

        # 打印初始信息
        print(f"\n" + "=" * 50)
        print(
            f"系统运行模式: {Config.MODES[system_mode]} | PID控制模式: {Config.PID_MODES[pid_mode]} | 整定方法: {Config.TUNING_METHODS[tuning_method]}")
        print(f"使用数据源: {'JSON数据' if using_json_data else '仿真数据'}")
        print("初始系统参数辨识结果：")
        print(f"静态增益 K = {K:.2f} | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s")
        print(f"初始PID参数：Pb={init_pb:.2f}%, Ti={init_ti:.1f}s, Td={init_td:.1f}s")
        if not using_json_data:
            print("\n随机扰动计划：")
            for d in disturbances:
                print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s，幅值{d['amplitude']:.1f}℃）")
        else:
            print("\n使用JSON数据（不包含额外随机扰动）")
        print("=" * 50 + "\n")

        # 预览轨迹模拟函数
        def simulate_preview_trajectory(preview_pb, preview_ti, preview_td):
            """使用新的PID参数模拟未来一段时间的响应轨迹"""
            if len(time_data) == 0:
                return [], []
            
            # 从当前状态开始模拟
            preview_start_time = time_data[-1] if time_data else 0
            preview_duration = 300  # 预览未来300秒
            preview_steps = min(int(preview_duration), 300)
            
            # 创建预览用的PID控制器和系统副本
            preview_pid = PIDController(pb=preview_pb, ti=preview_ti, td=preview_td, dt=1, 
                                       mode=pid_mode, system_mode=system_mode)
            # 复制当前PID控制器的状态（积分项等）
            preview_pid.integral = pid.integral
            preview_pid.last_error = pid.last_error
            preview_pid.last_process_var = pid.last_process_var
            
            # 创建系统副本，复制当前状态
            if system_mode == Mode.FLOW_CONTROL:
                preview_system = FlowSystem(K=system.K, T=system.T, noise_level=system.noise_level, mode=system_mode)
                preview_system.last_flow = system.last_flow
            else:
                preview_system = TemperatureSystem(K=system.K, T=system.T, L=system.L, 
                                                   noise_level=system.noise_level, mode=system_mode)
                preview_system.last_temp = system.last_temp
                preview_system.buffer = system.buffer.copy() if hasattr(system, 'buffer') else np.array([])
            
            # 模拟预览轨迹
            preview_time_data = []
            preview_temp_data = []
            preview_current_var = current_var
            preview_time = preview_start_time
            
            # 设置随机种子以确保预览的确定性（可选）
            np.random.seed(42)
            
            for i in range(preview_steps):
                preview_time += 1
                # 计算控制输出
                preview_valve = preview_pid.compute(setpoint, preview_current_var)
                # 更新系统状态
                if system_mode == Mode.FLOW_CONTROL:
                    preview_current_var = preview_system.update(preview_valve, preview_time, disturbances=disturbances)
                else:
                    preview_current_var = preview_system.update(preview_valve, preview_time, disturbances=disturbances)
                
                preview_time_data.append(preview_time)
                preview_temp_data.append(preview_current_var)
            
            # 恢复随机种子
            np.random.seed()
            
            return preview_time_data, preview_temp_data
        
        # Lambda滑块回调
        def on_lambda_slider_change(val):
            nonlocal K, T, L
            if system_mode == Mode.FLOW_CONTROL:
                new_pb, new_ti, new_td = self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)
            else:
                new_pb, new_ti, new_td = self.identifier.lambda_tuning(K, T, L, val, mode=system_mode)
            # 更新PID滑块的值
            pb_slider.set_val(new_pb)
            ti_slider.set_val(new_ti)
            td_slider.set_val(new_td)
            pid.set_target_params(new_pb, new_ti, new_td)
            self.plot_manager.update_params_text(params_text, identified_params,
                                                 {'Pb': pid.target_pb, 'Ti': pid.target_ti, 'Td': pid.target_td},
                                                 val, params_update_count, initial_valid_params, pid_mode, system_mode,
                                                 tuning_method)
            # 更新预览轨迹
            preview_t, preview_y = simulate_preview_trajectory(new_pb, new_ti, new_td)
            preview_line.set_data(preview_t, preview_y)
            fig.canvas.draw_idle()
        
        # 标记是否通过滑块手动调整了参数（用于扰动检测）
        manual_param_adjusted = False
        manual_adjust_time = None
        
        # PID参数滑块回调
        def on_pid_slider_change(val=None):
            """当PID参数滑块改变时，更新预览轨迹并应用参数"""
            nonlocal manual_param_adjusted, manual_adjust_time
            
            preview_pb = pb_slider.val
            preview_ti = ti_slider.val
            preview_td = td_slider.val
            
            # 更新预览轨迹
            preview_t, preview_y = simulate_preview_trajectory(preview_pb, preview_ti, preview_td)
            preview_line.set_data(preview_t, preview_y)
            
            # 实际应用参数到控制器（滑块调整后立即应用）
            pid.set_target_params(preview_pb, preview_ti, preview_td, reset_integral=False)
            
            # 标记手动调整参数的时间和标志
            manual_param_adjusted = True
            manual_adjust_time = time if len(time_data) > 0 else 0
            
            # 更新参数文本显示
            self.plot_manager.update_params_text(params_text, identified_params,
                                                 {'Pb': preview_pb, 'Ti': preview_ti, 'Td': preview_td},
                                                 lambda_slider.val, params_update_count, initial_valid_params, 
                                                 pid_mode, system_mode, tuning_method)
            
            print(f"🔧 手动调整PID参数: Pb={preview_pb:.2f}%, Ti={preview_ti:.1f}s, Td={preview_td:.1f}s")
            self.logger.info(f"手动调整PID参数: Pb={preview_pb:.2f}%, Ti={preview_ti:.1f}s, Td={preview_td:.1f}s (时间: {manual_adjust_time:.0f}s)")
            
            fig.canvas.draw_idle()
        
        lambda_slider.on_changed(on_lambda_slider_change)
        pb_slider.on_changed(on_pid_slider_change)
        ti_slider.on_changed(on_pid_slider_change)
        td_slider.on_changed(on_pid_slider_change)

        # 新增：用于避免PID整定过程中重复识别扰动的标志
        in_pid_tuning_phase = False  # 标记是否正在PID参数整定阶段
        tuning_start_time = None  # 记录PID整定开始时间
        tuning_duration = 200  # PID整定阶段的持续时间（秒），避免在此期间重复检测扰动

        # 无限仿真循环
        time = 0
        step = 0

        # 标记是否处于从初始温度上升到目标温度的阶段
        is_rising_to_target = False
        if using_json_data:
            # 如果JSON数据中的初始温度与目标温度不同，则需要上升
            if abs(response_data[0] - setpoint) > 0.5:
                is_rising_to_target = True
                print(f"📊 检测到JSON数据需要从初始温度 {response_data[0]:.1f}℃ 上升到目标温度 {setpoint}℃")
            else:
                print(f"📊 检测到JSON数据已处于目标温度 {setpoint}℃ 附近，无需上升")
        else:
            # 仿真模式下，从初始温度上升
            is_rising_to_target = True
            print(
                f"📊 仿真模式：从初始温度 {'0.0' if system_mode == Mode.FLOW_CONTROL else str(Config.INIT_TEMPERATURE)}℃ 上升到目标温度 {setpoint}℃")

        # 为可视化新PID参数下的仿真轨迹，我们创建一个数组来存储仿真数据
        new_pid_time_data = []
        new_pid_temp_data = []
        new_pid_simulated = False  # 标记是否已开始新PID参数下的仿真

        # 初始化无PID控制的系统（用于对比）
        if system_mode == Mode.FLOW_CONTROL:
            no_pid_system = FlowSystem(**true_params, mode=system_mode)
        else:
            no_pid_system = TemperatureSystem(**true_params, mode=system_mode)
        # 记录初始值
        no_pid_current_var = current_var
        # 使用初始输入信号模拟无PID控制的温度变化
        no_pid_input_signal = u[0] if len(u) > 0 else 25

        try:
            while True:  # 无限运行主循环
                # 如果使用JSON数据，则直接从数据中获取当前温度
                if using_json_data:
                    # 检查是否还有JSON数据可读取
                    if step < len(response_data):
                        # 从JSON数据中获取当前温度
                        current_var = response_data[step]
                        # 从JSON数据中获取当前阀门开度
                        if step < len(u):
                            valve_opening = u[step]
                        else:
                            valve_opening = 50.0  # 默认值
                    else:
                        # JSON数据已读完，停止仿真
                        print(f"✅ JSON数据已读取完毕，共{len(response_data)}个数据点，仿真结束")
                        break
                else:
                    # 计算控制输出与当前温度（仿真模式）
                    valve_opening = pid.compute(setpoint, current_var)
                    current_var = system.update(valve_opening, time, disturbances=disturbances)

                # 计算无PID控制的温度变化（修正：使用固定输入信号）
                if using_json_data:
                    # 如果使用JSON数据，无PID控制的温度应该跟随输入信号
                    # 但为了与PID控制形成对比，我们使用一个固定输入信号
                    no_pid_input_signal = u[step] if step < len(u) else no_pid_input_signal
                else:
                    # 在仿真模式下，使用当前输入信号
                    no_pid_input_signal = u[step] if step < len(u) else 50.0

                # 使用相同输入信号但无PID控制更新无PID温度
                no_pid_current_var = no_pid_system.update(no_pid_input_signal, time, disturbances=disturbances)
                no_pid_temp_data.append(no_pid_current_var)

                error = setpoint - current_var

                # 记录数据
                time_data.append(time)
                temp_data.append(current_var)
                valve_data.append(valve_opening)
                error_data.append(error)
                pb_data_list.append(pid.pb)
                ti_data_list.append(pid.ti / 10)  # 缩放显示
                td_data_list.append(pid.td * 2)  # 缩放显示

                # 检测初始稳态（达到目标温度后开启整定）
                if stabilization_time is None and state_analyzer.is_stable(temp_data, setpoint):
                    stabilization_time = time
                    stabilization_line.set_xdata([time])
                    print(f"✅ 系统达到初始稳态（{time:.0f}s）")
                    print(
                        f"初始有效PID参数：Pb={initial_valid_params[0]:.2f}%, Ti={initial_valid_params[1]:.1f}s, Td={initial_valid_params[2]:.1f}s")
                    self.plot_manager.update_params_text(params_text, identified_params,
                                                         {'Pb': pid.pb, 'Ti': pid.ti, 'Td': pid.td},
                                                         lambda_slider.val, params_update_count, initial_valid_params,
                                                         pid_mode, system_mode, tuning_method)
                    
                    # ========== 使用示例：在系统达到稳态时进行全面的稳定性评估 ==========
                    if len(temp_data) >= 30:  # 确保有足够的数据点
                        stability_result = state_analyzer.evaluate_stability_comprehensive(
                            temp_data=temp_data,
                            setpoint=setpoint,
                            valve_data=valve_data,
                            time_data=time_data,
                            pid_params={'kp': 100.0/pid.pb if pid.pb > 0 else 0, 'ki': 100.0/(pid.pb*pid.ti) if pid.pb*pid.ti > 0 else 0, 'kd': 100.0*pid.td/pid.pb if pid.pb > 0 else 0}
                        )
                        
                        # 打印稳定性评估结果
                        print(f"\n{'='*60}")
                        print(f"📊 系统稳定性评估报告（时间: {time:.0f}s）")
                        print(f"{'='*60}")
                        print(f"综合稳定性评分: {stability_result['overall_stability']['score']:.1f}/100")
                        print(f"稳定性等级: {stability_result['overall_stability']['level']} ({stability_result['overall_stability']['status']})")
                        print(f"\n【时域指标】")
                        print(f"  - 稳态误差: {stability_result['time_domain_metrics']['steady_state_error']['abs']:.3f}℃ ({stability_result['time_domain_metrics']['steady_state_error']['status']})")
                        print(f"  - 波动性(标准差): {stability_result['time_domain_metrics']['variability']['std']:.3f} ({stability_result['time_domain_metrics']['variability']['status']})")
                        print(f"  - 最大超调: {stability_result['time_domain_metrics']['overshoot']['max_overshoot']:.3f}℃ ({stability_result['time_domain_metrics']['overshoot']['status']})")
                        if stability_result['time_domain_metrics']['settling_time']['value']:
                            print(f"  - 调节时间: {stability_result['time_domain_metrics']['settling_time']['value']:.1f}s ({stability_result['time_domain_metrics']['settling_time']['status']})")
                        print(f"  - 振荡次数: {stability_result['time_domain_metrics']['oscillation']['count']} ({stability_result['time_domain_metrics']['oscillation']['status']})")
                        
                        if 'dominant_frequency' in stability_result['frequency_domain_metrics']:
                            print(f"\n【频域指标】")
                            print(f"  - 主要振荡频率: {stability_result['frequency_domain_metrics']['dominant_frequency']['value']:.4f} Hz")
                            print(f"  - 振荡周期: {stability_result['frequency_domain_metrics']['dominant_frequency']['period']:.1f}s")
                            if 'energy_distribution' in stability_result['frequency_domain_metrics']:
                                ed = stability_result['frequency_domain_metrics']['energy_distribution']
                                print(f"  - 能量分布: 低频{ed['low_freq_ratio']*100:.1f}% / 中频{ed['mid_freq_ratio']*100:.1f}% / 高频{ed['high_freq_ratio']*100:.1f}%")
                        
                        print(f"\n【控制性能】")
                        print(f"  - 控制努力(平均变化): {stability_result['control_performance_metrics']['control_effort']['mean_change']:.2f} ({stability_result['control_performance_metrics']['control_effort']['status']})")
                        print(f"  - 阀门振荡: {stability_result['control_performance_metrics']['valve_oscillation']['std']:.2f} ({stability_result['control_performance_metrics']['valve_oscillation']['status']})")
                        
                        # 打印改进建议
                        if stability_result['recommendations']:
                            print(f"\n【改进建议】")
                            for i, rec in enumerate(stability_result['recommendations'], 1):
                                priority_icon = "🔴" if rec['priority'] == 'high' else ("🟡" if rec['priority'] == 'medium' else "🟢")
                                print(f"  {priority_icon} [{rec['priority']}] {rec['issue']}")
                                print(f"     → {rec['suggestion']}")
                        else:
                            print(f"\n【改进建议】无，系统运行良好！")
                        print(f"{'='*60}\n")
                        
                        # 记录到日志
                        self.logger.info(f"稳定性评估完成 - 评分: {stability_result['overall_stability']['score']:.1f}, 等级: {stability_result['overall_stability']['level']}")

                # 自动扰动检测逻辑（仅在未处于PID整定阶段时执行）
                # 优化：即使手动调整了参数，如果出现扰动也要重新整定
                if not in_pid_tuning_phase:
                    # 使用优化的扰动检测算法
                    is_disturbance, disturbance_desc = state_analyzer.detect_instability_optimized(
                        temp_data, setpoint, valve_data, time_data
                    )

                    # 如果手动调整参数后出现扰动，需要重新整定
                    # 给手动调整后的参数一些适应时间（比如50秒），如果之后仍不稳定则重新整定
                    should_retune = False
                    if is_disturbance:
                        if manual_param_adjusted and manual_adjust_time is not None:
                            # 手动调整参数后，如果50秒后仍检测到扰动，说明参数不合适，需要重新整定
                            if time - manual_adjust_time > 50:
                                should_retune = True
                                print(f"\n⚠️ 手动调整的参数在扰动下表现不佳，将重新整定参数...")
                                self.logger.warning(f"手动调整的参数在扰动下表现不佳，开始重新整定 (调整时间: {manual_adjust_time:.0f}s, 当前时间: {time:.0f}s)")
                        else:
                            # 非手动调整的情况，正常处理扰动
                            should_retune = True

                    if is_disturbance and should_retune:
                        # 检查当前时间是否在任何手动定义的扰动区间内（仅在仿真模式下）
                        current_disturbance = None
                        if not using_json_data:
                            current_disturbance = next((d for d in disturbances
                                                        if d["time"] <= time < d["time"] + d["duration"]), None)

                        if current_disturbance:
                            # 扰动开始后50s内强制更新参数（避免初期波动误判）
                            if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:
                                print(f"\n⚠️ 检测到[{current_disturbance['description']}]，自动重新整定参数...")
                                self.logger.warning(
                                    f"检测到扰动[{current_disturbance['description']}]，开始自动重新整定参数...")

                                # 使用统一的参数更新方法
                                new_pb, new_ti, new_td, new_K, new_T, new_L = self._update_pid_params_for_disturbance(
                                    time, time_data, temp_data, valve_data, system_mode, identified_params,
                                    lambda_slider, tuning_method, current_disturbance)
                                K, T, L = new_K, new_T, new_L
                                lambda_val = lambda_slider.val

                                # 执行参数更新（带平滑）
                                pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
                                
                                # 同步更新滑块值（如果是手动调整导致的重新整定）
                                if manual_param_adjusted:
                                    pb_slider.set_val(new_pb)
                                    ti_slider.set_val(new_ti)
                                    td_slider.set_val(new_td)
                                    manual_param_adjusted = False  # 重置手动调整标志
                                    print(f"🔄 已更新PID滑块值以匹配重新整定的参数")
                                
                                update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
                                update_lines.append(update_line)
                                params_update_count += 1
                                current_disturbance['updated'] = True  # 标记已更新

                                # 记录参数更新日志
                                self.logger.info(f"参数更新 {params_update_count} 次 - 时间: {time:.0f}s")
                                self.logger.info(
                                    f"扰动类型: {current_disturbance['type']} - {current_disturbance['description']}")
                                self.logger.info(f"新参数: Pb={new_pb:.2f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
                                self.logger.info(f"旧参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")

                                # 打印参数变化（旧→新）
                                print(f"参数更新 {params_update_count} 次：")
                                print(f"Pb: {pid.pb:.2f}% → {new_pb:.2f}%")
                                print(f"Ti: {pid.ti:.1f}s → {new_ti:.1f}s")
                                print(f"Td: {pid.td:.1f}s → {new_td:.1f}s\n")
                                self.plot_manager.update_params_text(params_text, identified_params,
                                                                     {'Pb': new_pb, 'Ti': new_ti, 'Td': new_td},
                                                                     lambda_val, params_update_count,
                                                                     initial_valid_params, pid_mode, system_mode,
                                                                     tuning_method)

                                # 进入PID整定阶段，设置标志和时间
                                in_pid_tuning_phase = True
                                tuning_start_time = time

                                # 开始基于新PID参数的仿真
                                new_pid_simulated = True
                                new_pid_time_data = [time]
                                new_pid_temp_data = [current_var]

                        # 对于JSON数据，直接检测扰动并更新参数（不依赖预定义的扰动）
                        # 或者手动调整参数后出现扰动的情况
                        elif using_json_data or (manual_param_adjusted and should_retune):
                            if manual_param_adjusted:
                                print(f"\n⚠️ 手动调整的参数在扰动下表现不佳，自动重新整定参数...")
                                self.logger.warning(f"手动调整的参数在扰动下表现不佳，开始自动重新整定参数...")
                            else:
                                print(f"\n⚠️ 检测到系统扰动，自动重新整定参数...")
                                self.logger.warning(f"检测到系统扰动，开始自动重新整定参数...")

                            # 使用统一的参数更新方法（JSON数据或手动调整后无预定义扰动）
                            new_pb, new_ti, new_td, new_K, new_T, new_L = self._update_pid_params_for_disturbance(
                                time, time_data, temp_data, valve_data, system_mode, identified_params,
                                lambda_slider, tuning_method, current_disturbance=None)
                            K, T, L = new_K, new_T, new_L
                            lambda_val = lambda_slider.val

                            # 执行参数更新（带平滑）
                            pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
                            
                            # 同步更新滑块值（如果是手动调整导致的重新整定）
                            if manual_param_adjusted:
                                pb_slider.set_val(new_pb)
                                ti_slider.set_val(new_ti)
                                td_slider.set_val(new_td)
                                manual_param_adjusted = False  # 重置手动调整标志
                                print(f"🔄 已更新PID滑块值以匹配重新整定的参数")
                            
                            update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
                            update_lines.append(update_line)
                            params_update_count += 1

                            # 记录参数更新日志
                            self.logger.info(f"参数更新 {params_update_count} 次 - 时间: {time:.0f}s")
                            self.logger.info(f"新参数: Pb={new_pb:.2f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
                            self.logger.info(f"旧参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")

                            # 打印参数变化（旧→新）
                            print(f"参数更新 {params_update_count} 次：")
                            print(f"Pb: {pid.pb:.2f}% → {new_pb:.2f}%")
                            print(f"Ti: {pid.ti:.1f}s → {new_ti:.1f}s")
                            print(f"Td: {pid.td:.1f}s → {new_td:.1f}s\n")
                            self.plot_manager.update_params_text(params_text, identified_params,
                                                                 {'Pb': new_pb, 'Ti': new_ti, 'Td': new_td},
                                                                 lambda_val, params_update_count,
                                                                 initial_valid_params, pid_mode, system_mode,
                                                                 tuning_method)

                            # 进入PID整定阶段，设置标志和时间
                            in_pid_tuning_phase = True
                            tuning_start_time = time

                            # 开始基于新PID参数的仿真
                            new_pid_simulated = True
                            new_pid_time_data = [time]
                            new_pid_temp_data = [current_var]

                # 在参数更新后，模拟新PID参数下的温度响应
                if new_pid_simulated and len(time_data) > len(new_pid_time_data):
                    # 优化：重用PID控制器，只在参数更新时重新创建
                    if not hasattr(self, '_new_pid_controller') or self._new_pid_controller is None:
                        self._new_pid_controller = PIDController(pb=pid.pb, ti=pid.ti, td=pid.td, dt=1, 
                                                                  mode=pid_mode, system_mode=system_mode)
                    else:
                        # 更新参数而不重新创建对象
                        self._new_pid_controller.set_target_params(pid.pb, pid.ti, pid.td)
                    
                    new_valve_opening = self._new_pid_controller.compute(setpoint, new_pid_temp_data[-1])
                    # 优化：消除重复的system.update调用
                    new_temp = system.update(new_valve_opening, time, disturbances=disturbances)
                    new_pid_time_data.append(time)
                    new_pid_temp_data.append(new_temp)

                # 检查是否退出PID整定阶段
                if in_pid_tuning_phase:
                    if time - tuning_start_time >= tuning_duration:
                        in_pid_tuning_phase = False
                        tuning_start_time = None
                        print(f"✅ PID整定阶段结束，退出避免重复检测模式（{time:.0f}s）")
                        self.logger.info(f"PID整定阶段结束 - 时间: {time:.0f}s")

                # 扰动后恢复判断
                for d in disturbances:
                    if (d['updated'] and not recovery_status[d["type"]] and
                            time > d["time"] + d["duration"] + 60):  # 扰动结束后60s判断（增加恢复时间）
                        if state_analyzer.is_stable(temp_data, setpoint):
                            recovery_status[d["type"]] = True
                            print(f"🎉 {d['description']}已恢复稳定（{time:.0f}s），当前温度: {current_var:.1f}℃")
                            self.logger.info(
                                f"扰动 {d['description']} 已恢复稳定 - 时间: {time:.0f}s, 温度: {current_var:.1f}℃")
                            
                            # ========== 使用示例：在扰动恢复后进行稳定性评估 ==========
                            if len(temp_data) >= 30:
                                stability_result = state_analyzer.evaluate_stability_comprehensive(
                                    temp_data=temp_data,
                                    setpoint=setpoint,
                                    valve_data=valve_data,
                                    time_data=time_data,
                                    pid_params={'kp': 100.0/pid.pb if pid.pb > 0 else 0, 'ki': 100.0/(pid.pb*pid.ti) if pid.pb*pid.ti > 0 else 0, 'kd': 100.0*pid.td/pid.pb if pid.pb > 0 else 0}
                                )
                                
                                print(f"   恢复后稳定性评分: {stability_result['overall_stability']['score']:.1f}/100 ({stability_result['overall_stability']['level']})")
                                print(f"   稳态误差: {stability_result['time_domain_metrics']['steady_state_error']['abs']:.3f}℃, "
                                      f"波动性: {stability_result['time_domain_metrics']['variability']['std']:.3f}")
                                self.logger.info(f"扰动恢复后稳定性评估 - 评分: {stability_result['overall_stability']['score']:.1f}, "
                                                f"稳态误差: {stability_result['time_domain_metrics']['steady_state_error']['abs']:.3f}℃")

                # 持续扰动逻辑：在系统稳定后，如果所有扰动都已恢复，则生成新的扰动
                if tuning_enabled and not using_json_data:
                    # 检查是否需要生成新扰动
                    if all(recovery_status.get(d["type"], True) for d in disturbances):
                        # 随机决定是否生成新扰动（每3000步有30%概率生成新扰动）
                        if time % 3000 == 0 and np.random.random() > 0.7:
                            # 生成新的扰动
                            new_disturbance_type = np.random.choice(Config.DISTURBANCE_TYPES)
                            new_disturbance = {
                                "time": time + 500,  # 100秒后开始新的扰动
                                "type": new_disturbance_type["type"],
                                "duration": np.random.randint(80, 250),
                                "amplitude": np.random.uniform(1.2, 4.0),
                                "description": new_disturbance_type["description"],
                                "updated": False
                            }
                            disturbances.append(new_disturbance)
                            print(f"🔄 生成新扰动：{new_disturbance['description']}，将在{new_disturbance['time']}s开始")
                            recovery_status[new_disturbance["type"]] = False
                            # 在图上添加新的扰动区域
                            ax2.axvspan(new_disturbance["time"], new_disturbance["time"] + new_disturbance["duration"],
                                        color=plot_data['colors'][new_disturbance["type"]], alpha=0.2)

                # 定期打印状态（每50步）
                if step % 50 == 0:
                    stable_status = "已稳态" if stabilization_time else "暂稳态"
                    if not using_json_data:
                        recovery_text = ", ".join(
                            [f"{d['description']}:{'已恢复' if recovery_status.get(d['type'], True) else '恢复中'}"
                             for d in disturbances])
                    else:
                        recovery_text = "使用JSON数据，无预定义扰动"
                    tuning_phase_status = "PID整定中" if in_pid_tuning_phase else "正常运行"

                    # ========== 使用示例：定期进行稳定性评估（每500步评估一次） ==========
                    if step % 500 == 0 and len(temp_data) >= 30 and stabilization_time is not None:
                        # 定期评估稳定性，用于监控系统长期稳定性
                        stability_result = state_analyzer.evaluate_stability_comprehensive(
                            temp_data=temp_data,
                            setpoint=setpoint,
                            valve_data=valve_data,
                            time_data=time_data,
                            pid_params={'kp': 100.0/pid.pb if pid.pb > 0 else 0, 'ki': 100.0/(pid.pb*pid.ti) if pid.pb*pid.ti > 0 else 0, 'kd': 100.0*pid.td/pid.pb if pid.pb > 0 else 0}
                        )
                        
                        # 只在稳定性下降时打印警告
                        if stability_result['overall_stability']['score'] < 60:
                            print(f"\n⚠️ 稳定性警告（时间: {time:.0f}s）: 综合评分 {stability_result['overall_stability']['score']:.1f}/100 ({stability_result['overall_stability']['level']})")
                            if stability_result['recommendations']:
                                high_priority_recs = [r for r in stability_result['recommendations'] if r['priority'] == 'high']
                                if high_priority_recs:
                                    print(f"   主要问题: {high_priority_recs[0]['issue']} - {high_priority_recs[0]['suggestion']}")
                            self.logger.warning(f"稳定性下降 - 评分: {stability_result['overall_stability']['score']:.1f}, 等级: {stability_result['overall_stability']['level']}")

                    # 获取性能指标
                    iae, ise, control_effort = pid.get_performance_metrics()
                    print(
                        f"时间: {time:.0f}s | 系统模式: {Config.MODES[system_mode]} | PID模式: {Config.PID_MODES[pid_mode]} | 整定方法: {Config.TUNING_METHODS[tuning_method]} | 数据源: {'JSON' if using_json_data else '仿真'} | 实际响应: {current_var:.1f}℃ | 无PID控制: {no_pid_current_var:.1f}℃ | 误差: {error:.2f}℃ | "
                        f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {params_update_count}次 | {tuning_phase_status} | 扰动状态: {recovery_text} | IAE: {iae:.3f} | ISE: {ise:.3f} | 控制努力: {control_effort:.3f}")

                # 批量更新绘图
                if step % Config.PLOT_REFRESH_INTERVAL == 0:
                    self.plot_manager.update_plots(time_data, temp_data, valve_data, error_data,
                                                   pb_data_list, ti_data_list, td_data_list, update_lines,
                                                   new_pid_time_data, new_pid_temp_data, no_pid_temp_data)

                # 更新时间
                time += 1
                step += 1

                # 如果原始输入信号不够长，扩展它（仅在仿真模式下）
                if not using_json_data and step >= len(u):
                    # 扩展输入信号
                    new_time = np.arange(len(u), len(u) + 1000, 1)
                    if system_mode == Mode.FLOW_CONTROL:
                        new_u = system.generate_flow_input(new_time)
                    else:
                        new_u = system.generate_non_step_input(new_time)
                    u = np.append(u, new_u)

                # 定期保存数据，避免内存溢出
                if step % 10000 == 0:
                    # 保存当前数据
                    real_time_data = np.column_stack(
                        (time_data[-10000:], temp_data[-10000:],
                         valve_data[-10000:], error_data[-10000:]))
                    # save_path = os.path.join(Config.DATA_SAVE_DIR, f"real_time_control_data_{step // 10000}.csv")
                    # np.savetxt(
                    #     save_path,
                    #     real_time_data,
                    #     delimiter=",",
                    #     header="时间(s),实际响应温度(℃),阀门开度(%),误差(℃)",
                    #     comments=""
                    # )
                    # self.logger.info(f"数据已保存至：{save_path}")

        except KeyboardInterrupt:
            # 中断时保存数据
            end_time = datetime.now()
            duration = end_time - start_time
            if len(time_data) > 0:
                # 保存最后的数据
                real_time_data = np.column_stack(
                    (time_data, temp_data, valve_data, error_data))
                # self.data_handler.save_data(real_time_data,
                #                             ["时间(s)", "实际响应温度(℃)", "阀门开度(%)", "误差(℃)"],
                #                             "real_time_control_data_interrupted.csv")

                # 如果是仿真模式，保存仿真数据为JSON格式
                if not using_json_data:
                    # 计算Kp, Ki, Kd值
                    kp_data = [100 / pb if pb != 0 else 5 for pb in pb_data_list]
                    ki_data = [(100 / pb) / (ti * 10) if pb != 0 and ti != 0 else 0.25 for pb, ti in
                               zip(pb_data_list, ti_data_list)]
                    kd_data = [td / 2 if td != 0 else 0 for td in td_data_list]

                    json_save_path = self.data_handler.save_simulation_to_json(
                        time_data, temp_data, valve_data, setpoint,
                        pb_data_list, [ti * 10 for ti in ti_data_list], [td / 2 for td in td_data_list],
                        kp_data, ki_data, kd_data, start_time, end_time
                    )
                    print(f"✅ 仿真数据已保存为JSON格式：{json_save_path}")

            print("\n" + "=" * 50)
            print(
                f"系统运行模式: {Config.MODES[system_mode]} | PID控制模式: {Config.PID_MODES[pid_mode]} | 整定方法: {Config.TUNING_METHODS[tuning_method]}")
            print(f"数据源: {'JSON数据' if using_json_data else '仿真数据'}")
            print("监控手动终止")
            print(
                f"当前实际响应: {current_var:.1f}℃ | 无PID控制: {no_pid_current_var:.1f}℃ | 误差：{error:.2f}℃")
            print(f"初始有效参数 → 当前参数：")
            print(f"Pb: {initial_valid_params[0]:.2f}% → {pid.pb:.2f}%")
            print(f"Ti: {initial_valid_params[1]:.1f}s → {pid.ti:.1f}s")
            print(f"Td: {initial_valid_params[2]:.1f}s → {pid.td:.1f}s")
            print(f"总更新次数：{params_update_count}次")
            print(f"运行时间: {duration}")
            if not using_json_data:
                print(f"扰动总数: {len(disturbances)}")
            print("=" * 50)

            # 记录中断日志
            self.logger.info(f"控制监控系统被手动中断 - 时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"中断时运行时间: {duration}")
            self.logger.info(f"中断时温度: {current_var:.1f}℃, 误差: {error:.2f}℃, 更新次数: {params_update_count}")
            self.logger.info(f"中断时PID参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")
            self.logger.info(
                f"系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]}")

            plt.ioff()
            plt.close(fig)

    def _get_updated_params(self, K, T, L, lambda_val, tuning_method, system_mode, scenario=None):
        """根据整定方法获取更新后的PID参数 - 支持场景自适应"""
        if system_mode == Mode.FLOW_CONTROL:
            # 流量控制模式统一使用Lambda方法
            return self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)
        
        # 根据场景选择整定方法
        if scenario is None:
            # 如果没有提供场景，根据T和L推断（简单启发式）
            if T > 50:  # 大时间常数，可能是温控
                scenario = 'temperature'
            else:
                scenario = 'level'  # 默认液位
        
        if tuning_method == TuningMethod.LAMBDA:
            if scenario == 'temperature':
                # 温控场景：使用温控专用整定方法
                return self.identifier.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode=system_mode)
            elif scenario == 'level':
                # 液位场景：使用液位专用整定方法
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            # Cohen-Coon方法主要用于FOPDT模型（温控场景）
            if scenario == 'level':
                # 液位场景如果使用积分-延迟模型，不适合Cohen-Coon，改用液位专用方法
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.cohen_coon_tuning(K, T, L)
        else:
            # 默认使用Lambda方法
            if scenario == 'temperature':
                return self.identifier.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode=system_mode)
            elif scenario == 'level':
                return self.identifier.lambda_tuning_for_level_control(K, T, L, mode=system_mode)
            else:
                return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)
    
    def _update_pid_params_for_disturbance(self, time, time_data, temp_data, valve_data,
                                          system_mode, identified_params, lambda_slider,
                                          tuning_method, current_disturbance=None):
        """
        统一的PID参数更新逻辑（优化：消除重复代码，支持场景自适应）
        
        Args:
            time: 当前时间
            time_data: 时间数据列表
            temp_data: 温度数据列表
            valve_data: 阀门数据列表
            system_mode: 系统模式
            identified_params: 已辨识的参数字典（可能包含scenario字段）
            lambda_slider: Lambda滑块对象
            tuning_method: 整定方法
            current_disturbance: 当前扰动（可选）
            
        Returns:
            Tuple: (new_pb, new_ti, new_td, new_K, new_T, new_L)
        """
        # 提取窗口数据
        window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)
        window_t = np.array(time_data[window_start:]) - time_data[window_start]
        window_u = np.array(valve_data[window_start:])
        window_y = np.array(temp_data[window_start:])
        
        # ========== 自动场景检测 ==========
        detected_scenario = self.identifier.detect_control_scenario(window_t, window_y, window_u)
        print(f"🔍 扰动后重新检测场景类型: {detected_scenario}")
        
        # 根据场景选择预处理
        if detected_scenario == 'temperature':
            try:
                window_t, window_y, window_u = self.identifier.preprocess_temperature_data(window_t, window_y, window_u)
            except:
                pass
        elif detected_scenario == 'level':
            try:
                window_t, window_y, window_u = self.identifier.preprocess_level_data(window_t, window_y, window_u, noise_reduction='medium')
            except:
                pass
        
        # 重新辨识系统参数（根据场景选择模型）
        if system_mode == Mode.FLOW_CONTROL:
            new_K, new_T = self.identifier.identify_first_order(window_t, window_y, window_u)
            new_L = 0.0
        elif detected_scenario == 'level':
            params = self.identifier.identify_level_control_model(window_t, window_y, window_u)
            if len(params) == 2:  # 积分-延迟模型
                new_K, new_L = params
                new_T = 100  # 大时间常数表示积分特性
            elif len(params) == 3:  # FOPDT模型
                new_K, new_T, new_L = params
            else:  # 一阶模型
                new_K, new_T = params
                new_L = 0.0
        else:
            # 温控场景：检测热损失并选择模型
            has_heat_loss = False
            ambient_temp = np.min(window_y) if len(window_y) > 0 else 0.0
            
            if len(window_y) > 200:
                steady_segment = window_y[-100:]
                if np.std(steady_segment) < 0.5:
                    x = np.arange(len(steady_segment))
                    coeffs = np.polyfit(x, steady_segment, 1)
                    if coeffs[0] < -0.01:
                        has_heat_loss = True
                        print(f"🔍 扰动后检测到热损失趋势，使用带热损失的FOPDT模型")
            
            if has_heat_loss:
                new_K, new_T, new_L, alpha = self.identifier.identify_fopdt_with_heat_loss(window_t, window_y, window_u, ambient_temp)
                print(f"🔍 带热损失FOPDT辨识结果: K={new_K:.3f}, τ={new_T:.3f}, L={new_L:.3f}, α={alpha:.4f}")
            else:
                new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
        
        identified_params.update({'K': new_K, 'T': new_T, 'L': new_L, 'scenario': detected_scenario})
        K, T, L = new_K, new_T, new_L
        
        # 获取新PID参数（传入场景信息）
        lambda_val = lambda_slider.val
        new_pb, new_ti, new_td = self._get_updated_params(K, T, L, lambda_val, tuning_method, system_mode, scenario=detected_scenario)
        
        # 按扰动类型优化参数（如果有）
        if current_disturbance:
            new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(
                current_disturbance["type"], new_pb, new_ti, new_td)
        
        return new_pb, new_ti, new_td, new_K, new_T, new_L

    def _process_single_step(self, using_json_data, step, response_data, u, pid, system, 
                            setpoint, time, disturbances, no_pid_system, no_pid_input_signal,
                            system_mode, current_var):
        """
        处理单步仿真逻辑（优化：拆分主循环中的单步处理）
        
        Args:
            current_var: 当前变量值（温度或流量）
        
        Returns:
            Tuple: (current_var, valve_opening, no_pid_current_var, error) 或 None（如果数据已读完）
        """
        if using_json_data:
            if step < len(response_data):
                current_var = response_data[step]
                valve_opening = u[step] if step < len(u) else 50.0
            else:
                return None  # 数据已读完
        else:
            valve_opening = pid.compute(setpoint, current_var)
            current_var = system.update(valve_opening, time, disturbances=disturbances)
        
        # 计算无PID控制的温度变化
        if using_json_data:
            no_pid_input_signal = u[step] if step < len(u) else no_pid_input_signal
        else:
            no_pid_input_signal = u[step] if step < len(u) else 50.0
        
        no_pid_current_var = no_pid_system.update(no_pid_input_signal, time, disturbances=disturbances)
        error = setpoint - current_var
        
        return current_var, valve_opening, no_pid_current_var, error

    def _check_and_update_params_for_disturbance(self, time, time_data, temp_data, valve_data,
                                                  is_disturbance, should_retune, current_disturbance,
                                                  using_json_data, manual_param_adjusted, manual_adjust_time,
                                                  system_mode, identified_params, lambda_slider,
                                                  tuning_method, pid, pb_slider, ti_slider, td_slider,
                                                  ax2, update_lines, params_text, initial_valid_params,
                                                  pid_mode, params_update_count, current_var):
        """
        检查扰动并更新PID参数（优化：拆分主循环中的扰动处理逻辑）
        
        Returns:
            Tuple: (updated, new_pid_simulated, new_pid_time_data, new_pid_temp_data, 
                   in_pid_tuning_phase, tuning_start_time, params_update_count, manual_param_adjusted)
        """
        if not is_disturbance or not should_retune:
            return False, False, [], [], False, None, params_update_count, manual_param_adjusted
        
        # 窗口数据提取
        window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)
        window_t = np.array(time_data[window_start:]) - time_data[window_start]
        window_u = np.array(valve_data[window_start:])
        window_y = np.array(temp_data[window_start:])
        
        # ========== 自动场景检测 ==========
        detected_scenario = self.identifier.detect_control_scenario(window_t, window_y, window_u)
        print(f"🔍 扰动后重新检测场景类型: {detected_scenario}")
        
        # 根据场景选择预处理
        if detected_scenario == 'temperature':
            try:
                window_t, window_y, window_u = self.identifier.preprocess_temperature_data(window_t, window_y, window_u)
            except:
                pass
        elif detected_scenario == 'level':
            try:
                window_t, window_y, window_u = self.identifier.preprocess_level_data(window_t, window_y, window_u, noise_reduction='medium')
            except:
                pass
        
        # 重新辨识与整定（根据场景选择模型）
        if system_mode == Mode.FLOW_CONTROL:
            new_K, new_T = self.identifier.identify_first_order(window_t, window_y, window_u)
            new_L = 0.0
            identified_params.update({'K': new_K, 'T': new_T, 'L': new_L, 'scenario': detected_scenario})
            lambda_val = lambda_slider.val
            new_pb, new_ti, new_td = self.identifier.lambda_tuning_for_flow(new_K, new_T, mode=system_mode)
        else:
            if detected_scenario == 'level':
                params = self.identifier.identify_level_control_model(window_t, window_y, window_u)
                if len(params) == 2:  # 积分-延迟模型
                    new_K, new_L = params
                    new_T = 100  # 大时间常数表示积分特性
                elif len(params) == 3:  # FOPDT模型
                    new_K, new_T, new_L = params
                else:  # 一阶模型
                    new_K, new_T = params
                    new_L = 0.0
            else:
                new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
            identified_params.update({'K': new_K, 'T': new_T, 'L': new_L, 'scenario': detected_scenario})
            lambda_val = lambda_slider.val
            new_pb, new_ti, new_td = self._get_updated_params(new_K, new_T, new_L, lambda_val, 
                                                              tuning_method, system_mode, scenario=detected_scenario)
        
        # 按扰动类型优化参数
        if current_disturbance:
            new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(
                current_disturbance["type"], new_pb, new_ti, new_td)
        
        # 执行参数更新
        pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
        
        # 同步更新滑块值
        if manual_param_adjusted:
            pb_slider.set_val(new_pb)
            ti_slider.set_val(new_ti)
            td_slider.set_val(new_td)
            manual_param_adjusted = False
            print(f"🔄 已更新PID滑块值以匹配重新整定的参数")
        
        update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
        update_lines.append(update_line)
        params_update_count += 1
        
        if current_disturbance:
            current_disturbance['updated'] = True
        
        # 记录日志
        self.logger.info(f"参数更新 {params_update_count} 次 - 时间: {time:.0f}s")
        if current_disturbance:
            self.logger.info(f"扰动类型: {current_disturbance['type']} - {current_disturbance['description']}")
        self.logger.info(f"新参数: Pb={new_pb:.2f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
        self.logger.info(f"旧参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")
        
        # 打印参数变化
        print(f"参数更新 {params_update_count} 次：")
        print(f"Pb: {pid.pb:.2f}% → {new_pb:.2f}%")
        print(f"Ti: {pid.ti:.1f}s → {new_ti:.1f}s")
        print(f"Td: {pid.td:.1f}s → {new_td:.1f}s\n")
        
        self.plot_manager.update_params_text(params_text, identified_params,
                                             {'Pb': new_pb, 'Ti': new_ti, 'Td': new_td},
                                             lambda_val, params_update_count,
                                             initial_valid_params, pid_mode, system_mode, tuning_method)
        
        # 开始基于新PID参数的仿真
        new_pid_simulated = True
        new_pid_time_data = [time]
        new_pid_temp_data = [current_var]
        
        # 进入PID整定阶段
        in_pid_tuning_phase = True
        tuning_start_time = time
        
        return True, new_pid_simulated, new_pid_time_data, new_pid_temp_data, \
               in_pid_tuning_phase, tuning_start_time, params_update_count, manual_param_adjusted

    def _adjust_pid_for_disturbance(self, disturbance_type, pb, ti, td):
        """
        根据扰动类型调整PID参数（优化：使用配置字典替代if-elif链）
        
        Args:
            disturbance_type: 扰动类型
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            
        Returns:
            Tuple[float, float, float]: 调整后的 (pb, ti, td)
        """
        # 从配置字典获取调整策略
        if disturbance_type not in Config.DISTURBANCE_ADJUSTMENT_STRATEGIES:
            self.logger.warning(f"未知的扰动类型: {disturbance_type}，不进行调整")
            return pb, ti, td
        
        strategy = Config.DISTURBANCE_ADJUSTMENT_STRATEGIES[disturbance_type]
        original_pb, original_ti, original_td = pb, ti, td
        
        # 应用调整因子
        pb *= strategy['pb']
        ti *= strategy['ti']
        td = strategy['td'] if strategy['td'] == 0.0 else td * strategy['td']  # 特殊处理：td=0.0表示关闭微分
        
        # 应用全局参数边界保护
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)
        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)
        
        # 记录调整信息
        changes = []
        if abs(pb - original_pb) > 0.01:
            changes.append(f"Pb: {original_pb:.2f}% → {pb:.2f}%")
        if abs(ti - original_ti) > 0.01:
            changes.append(f"Ti: {original_ti:.1f}s → {ti:.1f}s")
        if abs(td - original_td) > 0.01:
            changes.append(f"Td: {original_td:.1f}s → {td:.1f}s")
        
        if changes:
            change_text = ", ".join(changes)
            print(f"🔧 {strategy['description']}：{change_text}")
            self.logger.info(f"{strategy['description']} - {change_text}")
        
        return pb, ti, td


if __name__ == "__main__":
    monitor = ControlMonitor()
    monitor.run()