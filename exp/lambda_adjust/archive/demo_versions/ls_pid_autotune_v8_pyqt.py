import sys
import os
import numpy as np
import matplotlib
from matplotlib import pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.gridspec as gridspec
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QPushButton,
                             QComboBox, QSlider, QGroupBox, QFrame, QFileDialog, QMessageBox)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from scipy.optimize import least_squares
from scipy import signal
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
import json
from enum import Enum
matplotlib.use('Qt5Agg')


##### 更新：
#            1. 加入日志模块
#            2. 加入低通滤波，降噪强度选择
#            3. pid控制模块加入不同参数更新模式
#            4. 加入模式选择（标准模式、抗扰动模式、抗噪声模式）
#            5. 修改仿真数据为数据流形式
#            6. json读取数据+自动识别扰动段+更新新pid参数后的仿真段
#            7. 可视化加入不带pid整定的温度变化
#            8. 加入Cohen-Coon整定法,整定法可选
#            9. 优化扰动可视化与速度调节
#            10. 修改扰动生成逻辑为不定时随机发生，无次数限制
#            11. 新增PID参数滑动时实时仿真功能
#            12. 修复JSON模式下的扰动检测算法
#            13. 修复JSON模式下的参数整定与新参数轨迹预测
#            14. 优化JSON模式扰动检测逻辑 - 整定后等待再次稳态
#            15. 优化仿真模式下的实时参数仿真功能
#            16. 优化扰动检测算法 - 使用多特征组合判断
#            17. 优化参数整定策略 - 自适应阈值调整
#            18. 改进稳态判断逻辑 - 多维度评估
#            19. 增加更详细的扰动类型识别
#            20. 优化仿真模式下手动滑动PID参数时的扰动检测
#            21. 增加手动调整PID参数后的参数矫正功能
#            22. 增加手动滑动PID参数200步后自动开始整定功能


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


class NoiseReductionLevel(str, Enum):
    """降噪强度枚举"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TuningMethod(str, Enum):
    """PID整定方法枚举"""
    LAMBDA = "lambda"
    COHEN_COON = "cohen-coon"


class Config:
    """系统配置参数集中管理"""
    # 温度参数
    INIT_TEMPERATURE = 0
    TARGET_TEMPERATURE = 5

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
        {"type": DisturbanceType.THERMAL_INERTIA, "description": "热惯性变化"}
    ]

    # 系统老化与辨识参数
    AGING_START_TIME = 300  # 老化开始时间(s)
    IDENTIFY_WINDOW = 200  # 参数辨识窗口大小(点数)
    PARAM_UPDATE_SMOOTH_FACTOR = 0.3  # 参数更新平滑因子

    # 扰动检测相关参数
    DETECTION_WINDOW = 60  # 扰动检测窗口大小
    ERROR_THRESHOLD = 1.5  # 误差阈值
    STD_THRESHOLD = 1.2  # 标准差阈值
    SLOPE_THRESHOLD = 0.05  # 温度变化率阈值
    VALVE_CHANGE_THRESHOLD = 25  # 阀门变化阈值
    CORRELATION_THRESHOLD = 0.3  # 相关性阈值

    # JSON模式专用参数
    JSON_DISTURBANCE_DETECTION_WINDOW = 60  # JSON模式下检测窗口
    JSON_ERROR_THRESHOLD = 1.5  # JSON模式误差阈值
    JSON_STD_THRESHOLD = 1.0  # JSON模式标准差阈值
    JSON_SLOPE_THRESHOLD = 0.05  # JSON模式变化率阈值
    JSON_VALVE_CHANGE_THRESHOLD = 20  # JSON模式阀门变化阈值

    # 仿真与存储参数
    DATA_SAVE_DIR = "../../data_simulation/data_generation"  # 数据保存目录
    PLOT_REFRESH_INTERVAL = 20  # 绘图刷新间隔(步)

    # 模式配置
    MODES = {
        Mode.STANDARD: "标准模式",
        Mode.ANTI_DISTURBANCE: "抗扰动模式",
        Mode.ANTI_NOISE: "抗噪声模式"
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

    # 新增：随机扰动参数
    DISTURBANCE_PROBABILITY = 0.005  # 每个时间步发生扰动的概率
    MIN_DISTURBANCE_INTERVAL = 1500  # 最小扰动间隔时间(秒)
    MAX_DISTURBANCE_DURATION = 200  # 最大扰动持续时间(秒)
    MAX_DISTURBANCE_AMPLITUDE = 4.0  # 最大扰动幅度(℃)

    # 新增：仿真预测参数
    SIMULATION_PREVIEW_STEPS = 200  # 预测仿真步数
    SIMULATION_PREVIEW_DT = 1.0  # 预测仿真时间步长

    # 新增：扰动检测增强参数
    ENHANCED_DETECTION = True  # 启用增强检测
    TUNING_THRESHOLD_ADAPTIVE = True  # 启用自适应阈值
    MIN_TUNING_INTERVAL = 100  # 最小参数更新间隔
    MAX_TUNING_COUNT = 10  # 最大参数更新次数

    # 新增：手动滑动PID参数后自动整定参数
    MANUAL_TUNING_DELAY = 200  # 手动滑动参数后自动整定的步数延迟

    @classmethod
    def ensure_data_dir(cls):
        """确保数据目录存在"""
        os.makedirs(cls.DATA_SAVE_DIR, exist_ok=True)


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

    def choose_mode(self):
        """选择运行模式"""
        return Mode.STANDARD  # 默认返回标准模式，交互版本中由界面控制

    def choose_noise_reduction_level(self):
        """选择降噪强度"""
        return NoiseReductionLevel.MEDIUM  # 默认返回中等强度，交互版本中由界面控制

    def choose_pid_mode(self):
        """选择PID控制模式"""
        return PIDMode.STANDARD  # 默认返回标准PID，交互版本中由界面控制

    def choose_tuning_method(self):
        """选择PID整定方法"""
        return TuningMethod.LAMBDA  # 默认返回Lambda方法，交互版本中由界面控制


Config.TUNING_METHODS = {
    TuningMethod.LAMBDA: "Lambda整定法",
    TuningMethod.COHEN_COON: "Cohen-Coon整定法"
}


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
            DisturbanceType.THERMAL_INERTIA: self._apply_thermal_inertia
        }

    def apply_disturbance(self, disturbance_type, time, current_temp, valve_opening,
                          amplitude, duration, start_time, system_state):
        """应用扰动对温度的影响"""
        if disturbance_type in self.disturbance_functions:
            return self.disturbance_functions[disturbance_type](
                time, current_temp, valve_opening, amplitude, duration, start_time, system_state
            )
        return current_temp

    def _apply_overshoot(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        decay = 1 - (time - start_time) / duration
        # 根据模式调整扰动强度
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        return current_temp + amplitude * (1.2 - decay) * mode_factor + np.random.normal(0, 1.2)

    def _apply_steady_error(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        turbulent = np.sin((time - start_time) * 0.1) * amplitude * 0.3
        return current_temp + amplitude * mode_factor + turbulent + np.random.normal(0, 0.9)

    def _apply_slow_recovery(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.6
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.7
        fluctuation = np.sin((time - start_time) * 0.2) * amplitude * 0.8
        return current_temp + fluctuation * mode_factor + np.random.normal(0, 1.3)

    def _apply_valve_stiction(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        system_state['valve_stiction_level'] = amplitude * 0.1
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.6
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.7
        return current_temp + np.random.normal(0, amplitude * 0.3 * mode_factor)

    def _apply_sensor_drift(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        sensor_drift = amplitude * np.sin((time - start_time) * 0.01)
        system_state['sensor_drift'] = sensor_drift
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        return current_temp + sensor_drift + np.random.normal(0, 0.5 * mode_factor)

    def _apply_heat_loss(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        loss_factor = 1 - amplitude * 0.001 * (time - start_time) / duration
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        return current_temp * loss_factor + np.random.normal(0, 0.8 * mode_factor)

    def _apply_control_valve_wear(self, time, current_temp, valve_opening, amplitude, duration, start_time,
                                  system_state):
        wear_factor = 1 - amplitude * 0.0005 * (time - start_time) / duration
        system_state['K'] = system_state['initial_K'] * wear_factor
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        return current_temp + np.random.normal(0, 0.6 * mode_factor)

    def _apply_thermal_inertia(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        inertia_factor = 1 + amplitude * 0.001 * (time - start_time) / duration
        system_state['T'] = system_state['initial_T'] * inertia_factor
        mode_factor = 1.0
        if self.mode == Mode.ANTI_DISTURBANCE:
            mode_factor = 0.7
        elif self.mode == Mode.ANTI_NOISE:
            mode_factor = 0.8
        return current_temp + np.random.normal(0, 0.7 * mode_factor)


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
        if self.Ti > 1e-6:
            integral_term = (self.Kp / self.Ti) * error * self.dt
            # 预计算输出，判断是否饱和
            if not (self.u_min <= temp_output <= self.u_max):
                integral_term = 0  # 输出饱和时不累积积分
            self.integral += integral_term
            # 积分限幅
            self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

    def _update_derivative(self, value_diff, alpha=0.3):
        """通用微分更新逻辑，支持平滑系数"""
        if self.Td > 1e-6:
            derivative_term = (self.Kp * self.Td) * value_diff / self.dt
            self.derivative = (1 - alpha) * self.derivative + alpha * derivative_term

    def compute(self, setpoint, process_var):
        """计算PID输出（含抗积分饱和）"""
        error = setpoint - process_var
        self.setpoint = setpoint  # 记录设定值

        # 根据系统模式调整控制策略
        if self.system_mode == Mode.ANTI_DISTURBANCE:
            # 抗扰动模式：降低微分增益，减少对扰动的敏感性
            adjusted_Td = self.Td * 0.7
        elif self.system_mode == Mode.ANTI_NOISE:
            # 抗噪声模式：降低微分增益，减少对噪声的敏感性
            adjusted_Td = self.Td * 0.5
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
            if adjusted_Td > 1e-6:
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
            if adjusted_Td > 1e-6:
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
            if adjusted_Td > 1e-6:
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
        else:
            # 默认调整
            self.set_target_params(pb=self.pb * 0.95, ti=self.ti * 1.05, td=self.td * 1.05)

        print(f"🔧 扰动类型: {disturbance_type}")
        print(f"   参数调整: Pb: {original_pb:.2f} → {self.pb:.2f}%, "
              f"Ti: {original_ti:.1f}s → {self.ti:.1f}s, "
              f"Td: {original_td:.1f}s → {self.td:.1f}s")


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
    def residuals(params, t, u, y_measured, y0):
        """最小二乘优化的残差函数"""
        y_predicted = SystemIdentifier.fopdt_model(params, t, u, y0)
        return y_predicted - y_measured

    @staticmethod
    def identify_fopdt(t, y, u):
        """用最小二乘法辨识FOPDT模型参数（K, T, L）"""
        y0 = np.mean(y[-30:]) if len(y) > 30 else np.mean(y)  # 初始值估计
        max_u = np.max(u)
        max_y = np.max(y)
        gain_guess = (max_y - y0) / max_u if max_u > 1e-6 else 0.5

        # 初始猜测与参数边界
        initial_guess = [max(gain_guess, 0.1), 30.0, 5.0]  # K, T, L
        bounds = ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0),
                bounds=bounds,
                verbose=0
            )
            K, T, L = result.x
        except Exception as e:
            print(f"⚠️ 参数辨识失败：{e}，使用初始猜测值")
            K, T, L = initial_guess

        # 确保参数在合理范围
        K = np.clip(K, 0.05, 1.5)
        T = np.clip(T, 5.0, 150.0)
        L = np.clip(L, 0.0, 20.0)
        return K, T, L

    @staticmethod
    def lambda_tuning(K, T, L, lambda_val=None, mode=Mode.STANDARD):
        """基于Lambda方法整定PID参数，根据模式调整参数"""
        if lambda_val is None:
            lambda_val = T * 0.8

        denominator = K * (lambda_val + L / 2)
        if denominator < 1e-6:
            return 1.0, 20.0, 1.0  # 异常时返回默认安全值

        # 计算Kp, Ti, Td
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > 1e-6 else 0.0

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


class StateAnalyzer:
    """系统状态分析工具：判断稳定性与扰动"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode
        # 用于检测异常模式的滑动窗口
        self.temp_window = []
        self.error_window = []
        self.valve_window = []
        self.time_window = []

        # 添加自适应阈值
        self.adaptive_error_threshold = Config.ERROR_THRESHOLD
        self.adaptive_std_threshold = Config.STD_THRESHOLD
        self.adaptive_slope_threshold = Config.SLOPE_THRESHOLD

    def is_stable(self, temp_data, setpoint):
        """判断系统是否稳定在目标温度附近 - 多维度评估"""
        if len(temp_data) < Config.STABILIZATION_WINDOW:
            return False

        recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])

        # 根据模式调整稳定阈值
        if self.mode == Mode.ANTI_DISTURBANCE:
            threshold = Config.STABILIZATION_THRESHOLD * 1.2  # 放宽稳定阈值
        elif self.mode == Mode.ANTI_NOISE:
            threshold = Config.STABILIZATION_THRESHOLD * 1.1  # 略微放宽稳定阈值
        else:
            threshold = Config.STABILIZATION_THRESHOLD

        # 均值需接近目标温度（±0.5℃）
        mean_temp = np.mean(recent_temps)
        if not (setpoint - 0.5 <= mean_temp <= setpoint + 0.5):
            return False

        # 波动判断
        deviations = np.abs(recent_temps - setpoint)

        # 检查是否满足波动要求
        max_deviation = np.max(deviations)
        std_deviation = np.std(deviations)

        # 增加趋势检查
        if len(recent_temps) > 20:
            x = np.arange(len(recent_temps))
            coeffs = np.polyfit(x, recent_temps, 1)
            trend_slope = abs(coeffs[0])
            if trend_slope > 0.01:  # 如果有明显的趋势变化，则认为不稳定
                return False

        return (max_deviation < threshold and
                std_deviation < threshold / 2)

    def detect_instability_optimized(self, temp_data, setpoint, valve_data, time_data, data_source="simulation"):
        """优化的扰动检测算法 - 增强对轻微扰动的检测能力"""
        # 根据数据源选择不同的检测参数
        if data_source == "json":
            detection_window = Config.JSON_DISTURBANCE_DETECTION_WINDOW
            error_threshold = Config.JSON_ERROR_THRESHOLD
            std_threshold = Config.JSON_STD_THRESHOLD
            slope_threshold = Config.JSON_SLOPE_THRESHOLD
            valve_change_threshold = Config.JSON_VALVE_CHANGE_THRESHOLD
        else:
            detection_window = Config.DETECTION_WINDOW
            error_threshold = Config.ERROR_THRESHOLD
            std_threshold = Config.STD_THRESHOLD
            slope_threshold = Config.SLOPE_THRESHOLD
            valve_change_threshold = Config.VALVE_CHANGE_THRESHOLD

        if len(temp_data) < detection_window:
            return False, ""

        # 获取当前窗口的数据
        recent_temps = np.array(temp_data[-detection_window:])
        recent_valves = np.array(valve_data[-detection_window:])
        recent_times = np.array(time_data[-detection_window:])

        # 计算误差
        errors = recent_temps - setpoint

        # 1. 误差统计特征
        mean_error = np.mean(errors)
        std_error = np.std(errors)
        max_error = np.max(np.abs(errors))
        error_var = np.var(errors)

        # 2. 温度变化率检测
        temp_deriv = np.diff(recent_temps)
        mean_abs_deriv = np.mean(np.abs(temp_deriv))
        max_deriv = np.max(np.abs(temp_deriv))

        # 3. 阀门动作检测
        valve_changes = np.diff(recent_valves)
        valve_activity = np.sum(np.abs(valve_changes))
        mean_valve_change = np.mean(np.abs(valve_changes))

        # 4. 温度波动性检测
        temp_std = np.std(recent_temps)
        temp_range = np.max(recent_temps) - np.min(recent_temps)

        # 5. 增强检测：系统参数漂移检测
        # 检查温度均值是否有趋势性变化
        trend_slope = 0
        if len(recent_temps) > 20:
            x = np.arange(len(recent_temps))
            coeffs = np.polyfit(x, recent_temps, 1)
            trend_slope = abs(coeffs[0])

        # 6. 阀门振荡检测（轻微扰动常导致阀门频繁动作）
        valve_oscillation = 0
        if len(recent_temps) > 10:
            valve_changes_abs = np.abs(np.diff(recent_valves))
            valve_oscillation = np.mean(valve_changes_abs)

        # 7. 温度变化模式检测
        temp_pattern_change = 0
        if len(recent_temps) > 30:
            first_half = recent_temps[:len(recent_temps) // 2]
            second_half = recent_temps[len(recent_temps) // 2:]
            temp_pattern_change = abs(np.std(second_half) - np.std(first_half))

        # 8. 预测模型残差检测（新增）
        # 使用前一半数据预测后一半，计算残差
        prediction_residual = 0
        if len(recent_temps) > 40:
            mid_point = len(recent_temps) // 2
            first_half = recent_temps[:mid_point]
            second_half = recent_temps[mid_point:mid_point + len(first_half)]
            # 简单的线性预测（用前一半的均值预测后一半）
            predicted_second_half = np.full_like(second_half, np.mean(first_half))
            prediction_residual = np.mean(np.abs(second_half - predicted_second_half))

        # 9. 基于自相关性的异常检测（新增）
        autocorr_strength = 0
        if len(recent_temps) > 20:
            # 计算滞后1的自相关系数
            autocorr = np.corrcoef(recent_temps[:-1], recent_temps[1:])[0, 1]
            autocorr_strength = abs(autocorr)

        # 10. 基于频率分析的异常检测（新增）
        freq_anomaly = 0
        if len(recent_temps) > 30:
            # 计算频域特征
            fft_vals = np.fft.fft(recent_temps - np.mean(recent_temps))
            freq_magnitude = np.abs(fft_vals[:len(fft_vals) // 2])
            # 计算高频能量占比
            low_freq_energy = np.sum(freq_magnitude[:10])
            high_freq_energy = np.sum(freq_magnitude[10:20])
            if low_freq_energy > 0:
                freq_anomaly = high_freq_energy / low_freq_energy

        # 11. 根据模式调整检测阈值
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

        # 12. 综合判断
        is_disturbance = False
        disturbance_type = ""

        # 组合多个指标的加权评分
        score = 0
        score_details = []

        # 超调检测
        overshoot_score = max(0, (max_error - error_threshold * 0.5) / error_threshold) * 0.3
        if overshoot_score > 0.1:
            score += overshoot_score
            score_details.append(f"超调: {overshoot_score:.2f}")

        # 稳态误差检测
        steady_error_score = max(0, (abs(mean_error) - 0.5) / 1.0) * 0.2
        if steady_error_score > 0.1:
            score += steady_error_score
            score_details.append(f"稳态误差: {steady_error_score:.2f}")

        # 系统振荡检测
        oscillation_score = max(0, (std_error - std_threshold * 0.5) / std_threshold) * 0.2
        if oscillation_score > 0.1:
            score += oscillation_score
            score_details.append(f"振荡: {oscillation_score:.2f}")

        # 阀门过度动作检测
        valve_score = max(0, (valve_activity - valve_change_threshold * 0.5) / valve_change_threshold) * 0.15
        if valve_score > 0.1:
            score += valve_score
            score_details.append(f"阀门动作: {valve_score:.2f}")

        # 趋势性变化检测
        trend_score = max(0, (trend_slope - slope_threshold * 0.5) / slope_threshold) * 0.15
        if trend_score > 0.1:
            score += trend_score
            score_details.append(f"趋势变化: {trend_score:.2f}")

        # 阀门振荡检测（针对轻微扰动）
        valve_osc_score = max(0, (valve_oscillation - 1.0) / 2.0) * 0.1
        if valve_osc_score > 0.1:
            score += valve_osc_score
            score_details.append(f"阀门振荡: {valve_osc_score:.2f}")

        # 预测模型异常检测
        pred_score = max(0, (prediction_residual - 0.3) / 0.5) * 0.1
        if pred_score > 0.1:
            score += pred_score
            score_details.append(f"预测异常: {pred_score:.2f}")

        # 自相关性异常检测
        auto_score = max(0, (autocorr_strength - 0.7) / 0.3) * 0.1
        if auto_score > 0.1:
            score += auto_score
            score_details.append(f"自相关: {auto_score:.2f}")

        # 频率异常检测
        freq_score = max(0, (freq_anomaly - 0.5) / 0.5) * 0.1
        if freq_score > 0.1:
            score += freq_score
            score_details.append(f"频率异常: {freq_score:.2f}")

        # 设置综合阈值
        total_threshold = 0.3
        if score > total_threshold:
            is_disturbance = True
            # 根据得分最高的指标确定扰动类型
            max_score_idx = np.argmax([overshoot_score, steady_error_score, oscillation_score,
                                       valve_score, trend_score, valve_osc_score, pred_score,
                                       auto_score, freq_score])
            disturbance_types = ["超调", "稳态误差", "系统振荡", "控制不稳定",
                                 "趋势性偏离", "阀门振荡", "预测异常", "自相关异常", "频率异常"]
            disturbance_type = f"{disturbance_types[max_score_idx]} (综合得分: {score:.2f})"

        return is_disturbance, disturbance_type


class DisturbanceGenerator:
    """扰动生成器：生成随机扰动，无次数限制"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode
        self.active_disturbances = []  # 当前正在发生的扰动
        self.last_disturbance_time = 0  # 上一次扰动发生的时间

    def generate_random_disturbance(self, current_time):
        """生成一个随机扰动"""
        # 检查是否满足最小间隔
        if current_time - self.last_disturbance_time < Config.MIN_DISTURBANCE_INTERVAL:
            return None

        # 随机决定是否发生扰动
        if np.random.random() < Config.DISTURBANCE_PROBABILITY:
            # 随机选择扰动类型
            disturbance_type = np.random.choice(Config.DISTURBANCE_TYPES)

            # 随机生成扰动参数
            duration = np.random.randint(50, Config.MAX_DISTURBANCE_DURATION)  # 持续时间
            amplitude = np.random.uniform(1.0, Config.MAX_DISTURBANCE_AMPLITUDE)  # 幅值

            disturbance = {
                "time": current_time,
                "type": disturbance_type["type"],
                "duration": duration,
                "amplitude": amplitude,
                "description": disturbance_type["description"]
            }

            self.last_disturbance_time = current_time
            return disturbance

        return None

    def check_and_add_disturbance(self, current_time):
        """检查是否需要添加新的扰动，并更新活跃扰动列表"""
        # 生成新的扰动
        new_disturbance = self.generate_random_disturbance(current_time)
        if new_disturbance:
            self.active_disturbances.append(new_disturbance)
            print(
                f"🎲 在 {current_time}s 随机生成扰动: {new_disturbance['description']} (持续{new_disturbance['duration']}s, 幅值{new_disturbance['amplitude']:.1f}℃)")

        # 移除已结束的扰动
        self.active_disturbances = [
            d for d in self.active_disturbances
            if current_time < d["time"] + d["duration"]
        ]

        return self.active_disturbances


class ControlMonitorGUI(QMainWindow):
    """交互式温度控制系统GUI主类"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("温度控制系统交互界面")
        self.setGeometry(100, 100, 1400, 900)

        # 初始化核心组件
        self.data_handler = DataHandler()
        self.identifier = SystemIdentifier()
        self.disturbance_generator = DisturbanceGenerator()
        self.logger = LoggerSetup.setup_logger()

        # 系统状态变量
        self.system_mode = Mode.STANDARD
        self.pid_mode = PIDMode.STANDARD
        self.tuning_method = TuningMethod.LAMBDA
        self.noise_reduction_level = NoiseReductionLevel.MEDIUM
        self.state_analyzer = StateAnalyzer(mode=self.system_mode)

        # 控制变量
        self.is_running = False
        self.is_paused = False
        self.current_time = 0
        self.step = 0
        self.speed_factor = 1  # 速度因子

        # 数据存储
        self.time_data = []
        self.temp_data = []
        self.valve_data = []
        self.error_data = []
        self.pb_data_list = []
        self.ti_data_list = []
        self.td_data_list = []
        self.no_pid_temp_data = []

        # 数据源控制
        self.data_source = "simulation"  # "simulation" or "json"
        self.json_data = None
        self.json_step = 0

        # 用于新PID参数仿真
        self.new_pid_sim_time = []
        self.new_pid_sim_temp = []
        self.new_pid_sim_valve = []

        # 🔥 新增：JSON模式扰动检测状态管理
        self.in_tuning_phase = False  # 是否在参数整定阶段
        self.post_tuning_stable_start_time = None  # 整定后稳态开始时间
        self.last_tuning_time = 0  # 上次整定时间
        self.tuning_count = 0  # 参数更新次数计数器

        # 🔥 新增：手动滑动PID参数时的扰动检测状态
        self.manual_pid_adjustment_start_time = None  # 手动调整开始时间
        self.is_manual_adjusting = False  # 是否在手动调整PID参数
        self.manual_adjustment_start_params = None  # 手动调整前的PID参数
        self.manual_adjustment_step_count = 0  # 手动调整后的步数计数器
        self.is_manual_tuning_delayed = False  # 是否在手动调整后延迟整定

        # 初始化系统和控制器
        self.init_system()

        # 创建UI
        self.init_ui()

        # 初始化定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_system)
        self.timer.setInterval(50)  # 50ms更新一次

    def init_system(self):
        """初始化系统和控制器"""
        # 初始化温度系统
        initial_true_params = {'K': 0.3, 'T': 20, 'L': 4, 'noise_level': 0.3}
        self.temp_system = TemperatureSystem(**initial_true_params, mode=self.system_mode)
        # 为无PID控制的系统创建独立实例
        self.no_pid_system = TemperatureSystem(**initial_true_params, mode=self.system_mode)

        # 初始化PID控制器
        K, T, L = 0.3, 20, 4  # 初始参数
        init_pb, init_ti, init_td = self.identifier.lambda_tuning(K, T, L, mode=self.system_mode)
        self.pid = PIDController(pb=init_pb, ti=init_ti, td=init_td, dt=1, mode=self.pid_mode,
                                 system_mode=self.system_mode)

        # 初始化当前温度
        self.current_temp = Config.INIT_TEMPERATURE
        self.no_pid_current_temp = Config.INIT_TEMPERATURE

        # 初始化扰动 - 现在使用随机生成器
        self.disturbances = []
        self.recovery_status = {}

        # 状态变量
        self.stabilization_time = None
        self.tuning_enabled = False
        self.params_update_count = 0
        self.initial_valid_params = None
        self.in_pid_tuning_phase = False
        self.tuning_start_time = None
        self.tuning_duration = 200

    def init_ui(self):
        """初始化用户界面"""
        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # 左侧控制面板
        control_panel = self.create_control_panel()
        main_layout.addWidget(control_panel)

        # 右侧图表区域
        chart_area = self.create_chart_area()
        main_layout.addWidget(chart_area, 3)

    def create_control_panel(self):
        """创建控制面板"""
        panel = QWidget()
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)

        # 数据源选择组
        data_group = QGroupBox("数据源选择")
        data_layout = QVBoxLayout(data_group)

        self.data_source_combo = QComboBox()
        self.data_source_combo.addItems(["仿真数据", "JSON数据"])
        self.data_source_combo.currentTextChanged.connect(self.on_data_source_changed)
        data_layout.addWidget(QLabel("数据源:"))
        data_layout.addWidget(self.data_source_combo)

        self.load_json_button = QPushButton("加载JSON文件")
        self.load_json_button.clicked.connect(self.load_json_file)
        self.load_json_button.setEnabled(False)
        data_layout.addWidget(self.load_json_button)

        layout.addWidget(data_group)

        # 模式选择组
        mode_group = QGroupBox("运行模式")
        mode_layout = QGridLayout(mode_group)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["标准模式", "抗扰动模式", "抗噪声模式"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(QLabel("系统模式:"), 0, 0)
        mode_layout.addWidget(self.mode_combo, 0, 1)

        self.pid_mode_combo = QComboBox()
        self.pid_mode_combo.addItems(["标准PID模式", "微分先行模式", "比例微分先行模式"])
        self.pid_mode_combo.currentTextChanged.connect(self.on_pid_mode_changed)
        mode_layout.addWidget(QLabel("PID模式:"), 1, 0)
        mode_layout.addWidget(self.pid_mode_combo, 1, 1)

        self.tuning_method_combo = QComboBox()
        self.tuning_method_combo.addItems(["Lambda整定法", "Cohen-Coon整定法"])
        self.tuning_method_combo.currentTextChanged.connect(self.on_tuning_method_changed)
        mode_layout.addWidget(QLabel("整定方法:"), 2, 0)
        mode_layout.addWidget(self.tuning_method_combo, 2, 1)

        layout.addWidget(mode_group)

        # 降噪设置组
        noise_group = QGroupBox("降噪设置")
        noise_layout = QVBoxLayout(noise_group)

        self.noise_level_combo = QComboBox()
        self.noise_level_combo.addItems(["低强度", "中等强度", "高强度"])
        self.noise_level_combo.currentTextChanged.connect(self.on_noise_level_changed)
        noise_layout.addWidget(QLabel("降噪强度:"))
        noise_layout.addWidget(self.noise_level_combo)

        layout.addWidget(noise_group)

        # 速度设置组
        speed_group = QGroupBox("仿真速度")
        speed_layout = QVBoxLayout(speed_group)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 10)
        self.speed_slider.setValue(1)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)
        speed_layout.addWidget(QLabel("速度调节:"))
        speed_layout.addWidget(self.speed_slider)
        self.speed_label = QLabel(f"速度: {self.speed_factor}x")
        speed_layout.addWidget(self.speed_label)

        layout.addWidget(speed_group)

        # 温度参数组
        temp_group = QGroupBox("温度参数")
        temp_layout = QGridLayout(temp_group)

        self.target_temp_label = QLabel(f"目标温度: {Config.TARGET_TEMPERATURE}℃")
        self.init_temp_label = QLabel(f"初始温度: {Config.INIT_TEMPERATURE}℃")
        temp_layout.addWidget(self.target_temp_label, 0, 0)
        temp_layout.addWidget(self.init_temp_label, 1, 0)

        layout.addWidget(temp_group)

        # PID参数组
        pid_group = QGroupBox("PID参数调节")
        pid_layout = QGridLayout(pid_group)

        # Pb参数
        pid_layout.addWidget(QLabel("Pb (比例带):"), 0, 0)
        self.pb_slider = QSlider(Qt.Horizontal)
        self.pb_slider.setRange(int(Config.PB_MIN), int(Config.PB_MAX))
        self.pb_slider.setValue(int(self.pid.pb))
        self.pb_slider.valueChanged.connect(self.on_pb_changed)
        pid_layout.addWidget(self.pb_slider, 0, 1)
        self.pb_value_label = QLabel(f"{self.pid.pb:.2f}")
        pid_layout.addWidget(self.pb_value_label, 0, 2)

        # Ti参数
        pid_layout.addWidget(QLabel("Ti (积分时间):"), 1, 0)
        self.ti_slider = QSlider(Qt.Horizontal)
        self.ti_slider.setRange(int(Config.TI_MIN), int(Config.TI_MAX))
        self.ti_slider.setValue(int(self.pid.ti))
        self.ti_slider.valueChanged.connect(self.on_ti_changed)
        pid_layout.addWidget(self.ti_slider, 1, 1)
        self.ti_value_label = QLabel(f"{self.pid.ti:.2f}")
        pid_layout.addWidget(self.ti_value_label, 1, 2)

        # Td参数
        pid_layout.addWidget(QLabel("Td (微分时间):"), 2, 0)
        self.td_slider = QSlider(Qt.Horizontal)
        self.td_slider.setRange(int(Config.TD_MIN), int(Config.TD_MAX))
        self.td_slider.setValue(int(self.pid.td))
        self.td_slider.valueChanged.connect(self.on_td_changed)
        pid_layout.addWidget(self.td_slider, 2, 1)
        self.td_value_label = QLabel(f"{self.pid.td:.2f}")
        pid_layout.addWidget(self.td_value_label, 2, 2)

        layout.addWidget(pid_group)

        # 控制按钮组
        button_group = QGroupBox("控制按钮")
        button_layout = QVBoxLayout(button_group)

        self.start_button = QPushButton("开始")
        self.start_button.clicked.connect(self.start_system)
        button_layout.addWidget(self.start_button)

        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self.pause_system)
        self.pause_button.setEnabled(False)
        button_layout.addWidget(self.pause_button)

        self.reset_button = QPushButton("重置")
        self.reset_button.clicked.connect(self.reset_system)
        button_layout.addWidget(self.reset_button)

        layout.addWidget(button_group)

        # 状态信息组
        status_group = QGroupBox("系统状态")
        status_layout = QVBoxLayout(status_group)

        self.status_label = QLabel("状态: 停止")
        self.temp_status_label = QLabel(f"当前温度: {self.current_temp:.2f}℃")
        self.error_status_label = QLabel(f"误差: {Config.TARGET_TEMPERATURE - self.current_temp:.2f}℃")
        self.valve_status_label = QLabel(f"阀门开度: 0.00%")
        self.update_count_label = QLabel(f"参数更新次数: {self.params_update_count}")
        self.active_disturbances_label = QLabel("当前活跃扰动: 0")

        # 🔥 新增：JSON模式状态标签
        self.json_mode_status_label = QLabel("JSON模式状态: 等待数据")

        # 🔥 新增：手动调整状态标签
        self.manual_adjust_status_label = QLabel("手动调整状态: 未调整")

        status_layout.addWidget(self.status_label)
        status_layout.addWidget(self.temp_status_label)
        status_layout.addWidget(self.error_status_label)
        status_layout.addWidget(self.valve_status_label)
        status_layout.addWidget(self.update_count_label)
        status_layout.addWidget(self.active_disturbances_label)
        status_layout.addWidget(self.json_mode_status_label)
        status_layout.addWidget(self.manual_adjust_status_label)

        layout.addWidget(status_group)

        # 添加弹性空间
        layout.addStretch()

        return panel

    def create_chart_area(self):
        """创建图表区域"""
        chart_widget = QWidget()
        chart_layout = QVBoxLayout(chart_widget)

        # 创建matplotlib图表
        self.figure = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        chart_layout.addWidget(self.canvas)

        # 初始化图表
        self.init_plots()

        return chart_widget

    def init_plots(self):
        """初始化图表"""
        plt.rcParams["font.family"] = ["Heiti TC"]

        self.figure.clear()
        gs = gridspec.GridSpec(6, 2, figure=self.figure)

        # 1. 温度控制曲线
        self.ax_temp = self.figure.add_subplot(gs[0:3, :])
        self.ax_temp.set_xlim(0, 10000)
        self.ax_temp.set_ylim(Config.INIT_TEMPERATURE - 15, Config.TARGET_TEMPERATURE + 25)
        self.ax_temp.axhline(Config.TARGET_TEMPERATURE, color='r', linestyle='--', label='设定值', linewidth=1.5)
        self.ax_temp.axhline(Config.INIT_TEMPERATURE, color='orange', linestyle='-.',
                             label=f'初始温度 {Config.INIT_TEMPERATURE}℃', linewidth=1.5)

        # 扰动标记
        disturbance_colors = {
            DisturbanceType.OVERSHOOT: "red",
            DisturbanceType.STEADY_ERROR: "orange",
            DisturbanceType.SLOW_RECOVERY: "brown",
            DisturbanceType.VALVE_STICTION: "purple",
            DisturbanceType.SENSOR_DRIFT: "pink",
            DisturbanceType.HEAT_LOSS: "gray",
            DisturbanceType.CONTROL_VALVE_WEAR: "olive",
            DisturbanceType.THERMAL_INERTIA: "cyan"
        }

        # 为每种扰动类型添加图例
        legend_handles = []
        legend_labels = []
        for i, dist_type in enumerate(Config.DISTURBANCE_TYPES):
            color = disturbance_colors[dist_type["type"]]
            legend_handles.append(plt.Rectangle((0, 0), 1, 1, color=color, alpha=0.2))
            legend_labels.append(f'{dist_type["description"]} ({dist_type["type"]})')

        self.ax_temp.set_title(
            f'温度控制曲线（PID模式: {Config.PID_MODES[self.pid_mode]}, 系统模式: {Config.MODES[self.system_mode]}, 整定方法: {Config.TUNING_METHODS[self.tuning_method]}）')
        self.ax_temp.set_xlabel('时间 (s)')
        self.ax_temp.set_ylabel('温度 (℃)')
        self.ax_temp.legend(legend_handles, legend_labels, loc='upper right', fontsize=8)
        self.ax_temp.grid(True, alpha=0.3)

        # 绘制实际响应温度曲线
        self.temp_line, = self.ax_temp.plot([], [], 'b-', label='实际响应温度', linewidth=1.5)
        # 添加无PID控制的温度曲线
        self.no_pid_temp_line, = self.ax_temp.plot([], [], 'm--', label='无PID控制温度', linewidth=1.5, alpha=0.7)
        self.stabilization_line = self.ax_temp.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
        self.update_lines = []  # 参数更新线
        self.update_marker, = self.ax_temp.plot([], [], 'bo', markersize=6, label='参数更新点')

        # 新PID参数下的仿真曲线 (用于JSON模式扰动检测后的参数整定效果预测)
        self.new_pid_line, = self.ax_temp.plot([], [], 'g--', label='新PID参数仿真', linewidth=1.5, alpha=0.7)

        # 手动调整PID参数时的扰动标记线
        self.manual_adjust_line = self.ax_temp.axvline(0, color='yellow', linestyle=':', alpha=0.5, label='手动调整',
                                                       visible=False)

        # 2. 阀门开度曲线
        self.ax_valve = self.figure.add_subplot(gs[3, 0])
        self.ax_valve.set_xlim(0, 10000)
        self.ax_valve.set_ylim(0, 100)
        self.ax_valve.set_title('阀门开度变化')
        self.ax_valve.set_xlabel('时间 (s)')
        self.ax_valve.set_ylabel('开度 (%)')
        self.ax_valve.grid(True, alpha=0.3)
        self.valve_line, = self.ax_valve.plot([], [], 'g-', label='阀门开度', linewidth=1.5)
        self.ax_valve.legend()

        # 3. 控制误差曲线
        self.ax_error = self.figure.add_subplot(gs[3, 1])
        self.ax_error.set_xlim(0, 10000)
        self.ax_error.set_ylim(-15, 15)
        self.ax_error.axhline(0, color='k', linestyle='-', alpha=0.3)
        self.ax_error.set_title('控制误差曲线')
        self.ax_error.set_xlabel('时间 (s)')
        self.ax_error.set_ylabel('误差 (℃)')
        self.ax_error.grid(True, alpha=0.3)
        self.error_line, = self.ax_error.plot([], [], 'r-', label='控制误差', linewidth=1.5)
        self.ax_error.legend()

        # 4. PID参数变化曲线
        self.ax_pid = self.figure.add_subplot(gs[4, :])
        self.ax_pid.set_xlim(0, 10000)
        self.ax_pid.set_ylim(0, 6)
        self.ax_pid.set_title(
            f'PID参数变化趋势 (PID模式: {Config.PID_MODES[self.pid_mode]}, 系统模式: {Config.MODES[self.system_mode]}, 整定方法: {Config.TUNING_METHODS[self.tuning_method]})')
        self.ax_pid.set_xlabel('时间 (s)')
        self.ax_pid.set_ylabel('参数值（Ti/10，Td*2）')
        self.ax_pid.grid(True, alpha=0.3)
        self.pb_line, = self.ax_pid.plot([], [], 'r-', label='Pb', linewidth=1.5)
        self.ti_line, = self.ax_pid.plot([], [], 'g-', label='Ti/10', linewidth=1.5)
        self.td_line, = self.ax_pid.plot([], [], 'b-', label='Td*2', linewidth=1.5)
        self.ax_pid.legend()

        # 5. 参数文本显示
        self.ax_text = self.figure.add_subplot(gs[5, :])
        self.ax_text.axis('off')
        self.params_text = self.ax_text.text(0.05, 0.5, "", fontsize=10,
                                             verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))

        # 更新参数显示
        self.update_params_text()

        self.figure.tight_layout()
        self.canvas.draw()

    def update_params_text(self):
        """更新参数显示文本"""
        # 获取当前系统参数（这里简化处理，实际应用中应根据系统状态更新）
        K, T, L = 0.3, 20, 4  # 示例参数
        Pb, Ti, Td = self.pid.pb, self.pid.ti, self.pid.td
        status = f"（已更新{self.params_update_count}次）" if self.params_update_count > 0 else ""

        # 初始参数对比
        initial_text = ""
        if self.initial_valid_params and self.params_update_count > 0:
            init_Pb, init_Ti, init_Td = self.initial_valid_params
            initial_text = f"""初始有效参数:
    Pb = {init_Pb:.2f}, Ti = {init_Ti:.1f}s, Td = {init_Td:.1f}s
    """

        text = f"""系统辨识参数:
    增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s

{initial_text}当前PID参数 {status}(PID模式:{Config.PID_MODES[self.pid_mode]}, 系统模式:{Config.MODES[self.system_mode]}, 整定方法:{Config.TUNING_METHODS[self.tuning_method]}):
    比例带 Pb = {Pb:.2f}%
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

目标温度: {Config.TARGET_TEMPERATURE}℃ | 初始温度: {Config.INIT_TEMPERATURE}℃"""
        self.params_text.set_text(text)

    def on_data_source_changed(self, text):
        """数据源变化处理"""
        if text == "仿真数据":
            self.data_source = "simulation"
            self.load_json_button.setEnabled(False)
        else:  # JSON数据
            self.data_source = "json"
            self.load_json_button.setEnabled(True)

    def load_json_file(self):
        """加载JSON文件"""
        file_path, _ = QFileDialog.getOpenFileName(self, "选择JSON文件", "", "JSON Files (*.json)")
        if file_path:
            try:
                t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.data_handler.read_json_data(
                    file_path)
                self.json_data = {
                    't': t,
                    'pv_data': pv_data,
                    'mv_data': mv_data,
                    'sv_data': sv_data,
                    'kp_data': kp_data,
                    'ki_data': ki_data,
                    'kd_data': kd_data,
                    'pb_data': pb_data,
                    'ti_data': ti_data,
                    'td_data': td_data
                }
                self.json_step = 0
                QMessageBox.information(self, "成功", f"成功加载JSON文件，共{len(pv_data)}个数据点")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"加载JSON文件失败：{str(e)}")

    def on_mode_changed(self, text):
        """系统模式变化处理"""
        if text == "标准模式":
            self.system_mode = Mode.STANDARD
        elif text == "抗扰动模式":
            self.system_mode = Mode.ANTI_DISTURBANCE
        elif text == "抗噪声模式":
            self.system_mode = Mode.ANTI_NOISE
        self.state_analyzer = StateAnalyzer(mode=self.system_mode)
        self.pid.system_mode = self.system_mode
        self.temp_system.mode = self.system_mode
        self.no_pid_system.mode = self.system_mode
        self.disturbance_generator = DisturbanceGenerator(mode=self.system_mode)

    def on_pid_mode_changed(self, text):
        """PID模式变化处理"""
        if text == "标准PID模式":
            self.pid_mode = PIDMode.STANDARD
        elif text == "微分先行模式":
            self.pid_mode = PIDMode.DERIVATIVE_ON_MEASUREMENT
        elif text == "比例微分先行模式":
            self.pid_mode = PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT
        self.pid.mode = self.pid_mode

    def on_tuning_method_changed(self, text):
        """整定方法变化处理"""
        if text == "Lambda整定法":
            self.tuning_method = TuningMethod.LAMBDA
        elif text == "Cohen-Coon整定法":
            self.tuning_method = TuningMethod.COHEN_COON

    def on_noise_level_changed(self, text):
        """降噪强度变化处理"""
        if text == "低强度":
            self.noise_reduction_level = NoiseReductionLevel.LOW
        elif text == "中等强度":
            self.noise_reduction_level = NoiseReductionLevel.MEDIUM
        elif text == "高强度":
            self.noise_reduction_level = NoiseReductionLevel.HIGH

    def on_speed_changed(self, value):
        """速度变化处理"""
        self.speed_factor = value
        self.speed_label.setText(f"速度: {self.speed_factor}x")
        # 根据速度因子调整定时器间隔
        interval = max(10, 50 // self.speed_factor)  # 最小间隔10ms
        self.timer.setInterval(interval)

    def on_pb_changed(self, value):
        """Pb参数变化处理"""
        # 保存调整前的参数
        if not self.is_manual_adjusting:
            self.manual_adjustment_start_params = (self.pid.pb, self.pid.ti, self.pid.td)

        self.pid.set_target_params(value, self.pid.ti, self.pid.td)
        self.pb_value_label.setText(f"{value:.2f}")
        # 🔥 触发实时仿真预览（无论数据源是什么）
        self.simulate_new_params()
        # 🔥 手动调整PID参数时的扰动检测
        self.on_manual_pid_adjustment()

    def on_ti_changed(self, value):
        """Ti参数变化处理"""
        # 保存调整前的参数
        if not self.is_manual_adjusting:
            self.manual_adjustment_start_params = (self.pid.pb, self.pid.ti, self.pid.td)

        self.pid.set_target_params(self.pid.pb, value, self.pid.td)
        self.ti_value_label.setText(f"{value:.2f}")
        # 🔥 触发实时仿真预览（无论数据源是什么）
        self.simulate_new_params()
        # 🔥 手动调整PID参数时的扰动检测
        self.on_manual_pid_adjustment()

    def on_td_changed(self, value):
        """Td参数变化处理"""
        # 保存调整前的参数
        if not self.is_manual_adjusting:
            self.manual_adjustment_start_params = (self.pid.pb, self.pid.ti, self.pid.td)

        self.pid.set_target_params(self.pid.pb, self.pid.ti, value)
        self.td_value_label.setText(f"{value:.2f}")
        # 🔥 触发实时仿真预览（无论数据源是什么）
        self.simulate_new_params()
        # 🔥 手动调整PID参数时的扰动检测
        self.on_manual_pid_adjustment()

    def on_manual_pid_adjustment(self):
        """处理手动调整PID参数的情况"""
        # 标记当前正在手动调整
        self.is_manual_adjusting = True
        self.is_manual_tuning_delayed = True
        self.manual_pid_adjustment_start_time = self.current_time
        self.manual_adjustment_step_count = 0  # 重置步数计数器

        # 更新状态标签
        self.manual_adjust_status_label.setText(f"手动调整状态: 正在调整 (时间: {self.current_time}s)")

        # 在图表上标记手动调整
        self.manual_adjust_line.set_xdata([self.current_time])
        self.manual_adjust_line.set_visible(True)
        self.canvas.draw()

    def start_system(self):
        """开始系统运行"""
        if not self.is_running:
            # 检查是否需要加载JSON数据
            if self.data_source == "json" and self.json_data is None:
                QMessageBox.warning(self, "警告", "请先加载JSON文件")
                return

            # 重置系统
            self.reset_system_data()

            self.is_running = True
            self.is_paused = False
            self.start_button.setText("运行中...")
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.status_label.setText("状态: 运行中")

            # 启动定时器
            self.timer.start()

    def pause_system(self):
        """暂停系统运行"""
        if self.is_running and not self.is_paused:
            self.is_paused = True
            self.timer.stop()
            self.pause_button.setText("继续")
            self.status_label.setText("状态: 暂停")
        elif self.is_running and self.is_paused:
            self.is_paused = False
            self.timer.start()
            self.pause_button.setText("暂停")
            self.status_label.setText("状态: 运行中")

    def reset_system(self):
        """重置系统"""
        self.timer.stop()
        self.is_running = False
        self.is_paused = False
        self.current_time = 0
        self.step = 0
        self.start_button.setText("开始")
        self.start_button.setEnabled(True)
        self.pause_button.setText("暂停")
        self.pause_button.setEnabled(False)
        self.status_label.setText("状态: 停止")

        # 重置系统
        self.reset_system_data()

        # 重置图表
        self.init_plots()

    def reset_system_data(self):
        """重置系统数据"""
        # 重置数据列表
        self.time_data = []
        self.temp_data = []
        self.valve_data = []
        self.error_data = []
        self.pb_data_list = []
        self.ti_data_list = []
        self.td_data_list = []
        self.no_pid_temp_data = []

        # 重置新PID仿真数据
        self.new_pid_sim_time = []
        self.new_pid_sim_temp = []
        self.new_pid_sim_valve = []

        # 🔥 重置JSON模式状态
        self.in_tuning_phase = False
        self.post_tuning_stable_start_time = None
        self.last_tuning_time = 0
        self.tuning_count = 0

        # 🔥 重置手动调整状态
        self.manual_pid_adjustment_start_time = None
        self.is_manual_adjusting = False
        self.manual_adjustment_start_params = None
        self.manual_adjustment_step_count = 0
        self.is_manual_tuning_delayed = False

        # 重置系统状态
        self.stabilization_time = None
        self.tuning_enabled = False
        self.params_update_count = 0
        self.initial_valid_params = None
        self.in_pid_tuning_phase = False
        self.tuning_start_time = None

        # 重置扰动生成器
        self.disturbance_generator = DisturbanceGenerator(mode=self.system_mode)
        self.disturbances = []

        # 重置控制器
        self.pid.reset()

        # 重置温度
        self.current_temp = Config.INIT_TEMPERATURE
        self.no_pid_current_temp = Config.INIT_TEMPERATURE

        # 重置JSON步数
        self.json_step = 0

        # 更新状态标签
        self.temp_status_label.setText(f"当前温度: {self.current_temp:.2f}℃")
        self.error_status_label.setText(f"误差: {Config.TARGET_TEMPERATURE - self.current_temp:.2f}℃")
        self.valve_status_label.setText(f"阀门开度: 0.00%")
        self.update_count_label.setText(f"参数更新次数: {self.params_update_count}")
        self.active_disturbances_label.setText("当前活跃扰动: 0")
        self.json_mode_status_label.setText("JSON模式状态: 等待数据")
        self.manual_adjust_status_label.setText("手动调整状态: 未调整")

        # 隐藏手动调整标记线
        self.manual_adjust_line.set_visible(False)

    def simulate_new_params(self):
        """根据当前滑块值仿真新参数下的系统响应"""
        # 🔥 无论是否在运行，只要当前有数据就可以仿真
        if len(self.temp_data) == 0:
            return

        # 获取当前滑块参数
        pb_new = self.pb_slider.value()
        ti_new = self.ti_slider.value()
        td_new = self.td_slider.value()

        # 使用当前PID模式和系统模式
        pid_mode = self.pid.mode
        system_mode = self.pid.system_mode

        # 创建一个临时的PID控制器用于仿真
        temp_pid = PIDController(pb=pb_new, ti=ti_new, td=td_new, dt=Config.SIMULATION_PREVIEW_DT,
                                 mode=pid_mode, system_mode=system_mode)

        # 创建一个临时的温度系统用于仿真
        temp_system = TemperatureSystem(K=self.temp_system.K, T=self.temp_system.T, L=self.temp_system.L,
                                        noise_level=0, mode=system_mode)  # 仿真时不加噪声

        # 从当前状态开始仿真
        current_temp = self.current_temp
        current_time = self.current_time
        valve_opening = self.pid.compute(Config.TARGET_TEMPERATURE, current_temp)  # 使用当前温度计算初始阀门开度

        # 生成仿真时间轴
        t_sim = np.arange(current_time, current_time + Config.SIMULATION_PREVIEW_STEPS * Config.SIMULATION_PREVIEW_DT,
                          Config.SIMULATION_PREVIEW_DT)
        t_sim = t_sim[:Config.SIMULATION_PREVIEW_STEPS]  # 确保长度

        temp_sim = []
        valve_sim = []

        for t in t_sim:
            # 计算新阀门开度
            valve_opening = temp_pid.compute(Config.TARGET_TEMPERATURE, current_temp)
            # 更新温度
            current_temp = temp_system.update(valve_opening, t, dt=Config.SIMULATION_PREVIEW_DT,
                                              disturbances=self.disturbances)

            temp_sim.append(current_temp)
            valve_sim.append(valve_opening)

        # 更新预览线
        self.new_pid_line.set_data(t_sim, temp_sim)
        self.canvas.draw()

    def update_system(self):
        """更新系统状态"""
        if not self.is_running or self.is_paused:
            return

        # 🔥 检查是否在手动调整PID参数后需要进行扰动检测和参数矫正
        if self.is_manual_adjusting:
            # 增加手动调整后的步数计数器
            self.manual_adjustment_step_count += 1

            # 检查是否已经过去了一段时间，可以评估调整效果
            if self.manual_adjustment_step_count >= Config.MANUAL_TUNING_DELAY:  # 200步后自动整定
                # 使用优化的扰动检测算法检测手动调整后是否引起系统不稳定
                if len(self.temp_data) >= Config.DETECTION_WINDOW:
                    is_disturbance, disturbance_desc = self.state_analyzer.detect_instability_optimized(
                        self.temp_data, Config.TARGET_TEMPERATURE, self.valve_data, self.time_data
                    )

                    if is_disturbance:
                        print(f"🔍 检测到手动调整PID参数后引起的扰动: {disturbance_desc}")
                        # 在图表上标记扰动
                        update_line = self.ax_temp.axvline(self.current_time, color='orange', linestyle='--',
                                                           alpha=0.5, label='手动调整扰动')
                        self.update_lines.append(update_line)

                        # 执行参数矫正
                        self.perform_manual_adjustment_correction()
                    else:
                        print(f"✅ 手动调整PID参数后系统保持稳定，无需矫正")

                # 重置手动调整标志
                self.is_manual_adjusting = False
                self.is_manual_tuning_delayed = False
                self.manual_adjustment_step_count = 0
                self.manual_adjust_status_label.setText("手动调整状态: 已评估")

                # 隐藏手动调整标记线
                self.manual_adjust_line.set_visible(False)

        # 根据数据源更新系统
        if self.data_source == "json":
            # JSON数据模式
            if self.json_data is None or self.json_step >= len(self.json_data['pv_data']):
                # JSON数据已读完，停止仿真
                self.pause_system()
                QMessageBox.information(self, "信息", f"JSON数据已读取完毕，共{len(self.json_data['pv_data'])}个数据点")
                return

            # 从JSON数据中获取当前温度和阀门开度
            self.current_temp = self.json_data['pv_data'][self.json_step]
            valve_opening = self.json_data['mv_data'][self.json_step] if self.json_step < len(
                self.json_data['mv_data']) else 50.0

            # 计算无PID控制的温度变化（使用相同的输入信号）
            no_pid_input_signal = valve_opening
            self.no_pid_current_temp = self.no_pid_system.update(no_pid_input_signal, self.current_time)

            # 计算误差
            error = Config.TARGET_TEMPERATURE - self.current_temp

            # 记录数据
            self.time_data.append(self.current_time)
            self.temp_data.append(self.current_temp)
            self.valve_data.append(valve_opening)
            self.error_data.append(error)
            self.pb_data_list.append(self.pid.pb)
            self.ti_data_list.append(self.pid.ti / 10)  # 缩放显示
            self.td_data_list.append(self.pid.td * 2)  # 缩放显示
            self.no_pid_temp_data.append(self.no_pid_current_temp)

            # 🔥 JSON模式：启用调谐功能（如果数据点足够多）
            if not self.tuning_enabled and len(self.temp_data) >= Config.JSON_DISTURBANCE_DETECTION_WINDOW:
                self.tuning_enabled = True
                print(f"✅ JSON模式：启用扰动检测功能（{self.current_time:.0f}s）")
                self.json_mode_status_label.setText("JSON模式状态: 检测中")

            # 🔥 JSON模式：进行扰动检测（优化版：整定后等待稳态）
            if self.tuning_enabled and len(self.temp_data) >= Config.JSON_DISTURBANCE_DETECTION_WINDOW:
                # 检查是否在整定阶段
                if self.in_tuning_phase:
                    # 在整定阶段，检查是否恢复稳态
                    if self.state_analyzer.is_stable(self.temp_data, Config.TARGET_TEMPERATURE):
                        if self.post_tuning_stable_start_time is None:
                            # 开始记录稳态时间
                            self.post_tuning_stable_start_time = self.current_time
                            print(f"✅ 参数整定后开始恢复稳态（{self.current_time:.0f}s）")
                        else:
                            # 已经开始记录稳态时间，继续等待
                            if self.current_time - self.post_tuning_stable_start_time >= Config.STABILIZATION_WINDOW:
                                # 稳态维持时间足够，退出整定阶段
                                self.in_tuning_phase = False
                                self.post_tuning_stable_start_time = None
                                print(f"✅ 参数整定后稳态恢复完成（{self.current_time:.0f}s），退出整定阶段")
                                self.json_mode_status_label.setText("JSON模式状态: 稳态恢复")
                    else:
                        # 不在稳态，重置稳态开始时间
                        self.post_tuning_stable_start_time = None
                else:
                    # 检查是否已达到最大更新次数
                    if self.tuning_count >= Config.MAX_TUNING_COUNT:
                        print(f"⚠️ 已达到最大参数更新次数({Config.MAX_TUNING_COUNT})，停止自动整定")
                        self.json_mode_status_label.setText("JSON模式状态: 已达最大更新次数")
                    else:
                        # 不在整定阶段，正常检测扰动
                        is_disturbance, disturbance_desc = self.state_analyzer.detect_instability_optimized(
                            self.temp_data, Config.TARGET_TEMPERATURE, self.valve_data, self.time_data, "json"
                        )
                        if is_disturbance:
                            print(f"🔍 JSON模式检测到扰动: {disturbance_desc}")
                            # 在图表上标记扰动
                            update_line = self.ax_temp.axvline(self.current_time, color='purple', linestyle='--',
                                                               alpha=0.5, label='JSON扰动')
                            self.update_lines.append(update_line)

                            # 🔥 进行参数整定
                            self.perform_pid_tuning()

                            # 设置整定状态
                            self.in_tuning_phase = True
                            self.post_tuning_stable_start_time = None
                            self.last_tuning_time = self.current_time
                            self.params_update_count += 1
                            self.tuning_count += 1
                            self.update_count_label.setText(f"参数更新次数: {self.params_update_count}")
                            self.json_mode_status_label.setText("JSON模式状态: 参数整定中")

            # 更新JSON步数
            self.json_step += 1
        else:
            # 仿真模式
            # 检查并添加新的随机扰动
            self.disturbances = self.disturbance_generator.check_and_add_disturbance(self.current_time)

            # 更新活跃扰动显示
            self.active_disturbances_label.setText(f"当前活跃扰动: {len(self.disturbances)}")

            # 计算控制输出与当前温度
            valve_opening = self.pid.compute(Config.TARGET_TEMPERATURE, self.current_temp)
            self.current_temp = self.temp_system.update(valve_opening, self.current_time,
                                                        disturbances=self.disturbances)

            # 计算无PID控制的温度变化 - 使用固定输入信号，模拟无控制的情况
            no_pid_input_signal = 50.0  # 使用50%的固定输入作为无控制对比
            self.no_pid_current_temp = self.no_pid_system.update(no_pid_input_signal, self.current_time,
                                                                 disturbances=self.disturbances)
            self.no_pid_temp_data.append(self.no_pid_current_temp)

            error = Config.TARGET_TEMPERATURE - self.current_temp

            # 记录数据
            self.time_data.append(self.current_time)
            self.temp_data.append(self.current_temp)
            self.valve_data.append(valve_opening)
            self.error_data.append(error)
            self.pb_data_list.append(self.pid.pb)
            self.ti_data_list.append(self.pid.ti / 10)  # 缩放显示
            self.td_data_list.append(self.pid.td * 2)  # 缩放显示

            # 检测初始稳态（达到目标温度后开启整定）
            if self.stabilization_time is None and self.state_analyzer.is_stable(self.temp_data,
                                                                                 Config.TARGET_TEMPERATURE):
                self.stabilization_time = self.current_time
                self.stabilization_line.set_xdata([self.current_time])
                self.tuning_enabled = True
                self.initial_valid_params = (self.pid.pb, self.pid.ti, self.pid.td)  # 记录初始有效参数
                print(f"✅ 系统达到初始稳态（{self.current_time:.0f}s），开启自整定功能")
                print(
                    f"初始有效PID参数：Pb={self.initial_valid_params[0]:.2f}%, Ti={self.initial_valid_params[1]:.1f}s, Td={self.initial_valid_params[2]:.1f}s")

            # 自动扰动检测逻辑（仅在未处于PID整定阶段时执行）
            if self.tuning_enabled and not self.in_pid_tuning_phase:
                # 使用优化的扰动检测算法
                is_disturbance, disturbance_desc = self.state_analyzer.detect_instability_optimized(
                    self.temp_data, Config.TARGET_TEMPERATURE, self.valve_data, self.time_data
                )

                if is_disturbance:
                    # 检查当前时间是否在任何当前扰动区间内
                    current_disturbance = next((d for d in self.disturbances
                                                if d["time"] <= self.current_time < d["time"] + d["duration"]), None)

                    if current_disturbance:
                        # 扰动开始后20s内强制更新参数（避免初期波动误判）
                        if not current_disturbance.get('updated', False) and (
                                self.current_time - current_disturbance["time"]) > 50:
                            print(f"\n⚠️ 检测到[{current_disturbance['description']}]，自动重新整定参数...")

                            # 进入PID整定阶段，设置标志和时间
                            self.in_pid_tuning_phase = True
                            self.tuning_start_time = self.current_time

                            # 窗口数据提取
                            window_start = max(0, len(self.time_data) - Config.IDENTIFY_WINDOW)
                            window_t = np.array(self.time_data[window_start:]) - self.time_data[window_start]
                            window_u = np.array(self.valve_data[window_start:])
                            window_y = np.array(self.temp_data[window_start:])

                            # 重新辨识与整定
                            new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
                            lambda_val = new_T * 0.6  # 默认Lambda值

                            if self.tuning_method == TuningMethod.LAMBDA:
                                new_pb, new_ti, new_td = self.identifier.lambda_tuning(new_K, new_T, new_L, lambda_val,
                                                                                       mode=self.system_mode)
                            else:  # Cohen-Coon
                                new_pb, new_ti, new_td = self.identifier.cohen_coon_tuning(new_K, new_T, new_L)

                            # 按扰动类型优化参数
                            new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(
                                current_disturbance["type"], new_pb, new_ti, new_td)

                            # 执行参数更新（带平滑）
                            self.pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
                            update_line = self.ax_temp.axvline(self.current_time, color='blue', linestyle='--',
                                                               alpha=0.5)
                            self.update_lines.append(update_line)
                            self.params_update_count += 1
                            current_disturbance['updated'] = True  # 标记已更新

                            # 记录参数更新日志
                            print(f"参数更新 {self.params_update_count} 次：")
                            print(f"Pb: {self.pid.pb:.2f}% → {new_pb:.2f}%")
                            print(f"Ti: {self.pid.ti:.1f}s → {new_ti:.1f}s")
                            print(f"Td: {self.pid.td:.1f}s → {new_td:.1f}s\n")

                            # 更新参数显示
                            self.update_params_text()
                            self.update_count_label.setText(f"参数更新次数: {self.params_update_count}")

            # 检查是否退出PID整定阶段
            if self.in_pid_tuning_phase:
                if self.current_time - self.tuning_start_time >= self.tuning_duration:
                    self.in_pid_tuning_phase = False
                    self.tuning_start_time = None
                    print(f"✅ PID整定阶段结束，退出避免重复检测模式（{self.current_time:.0f}s）")

        # 定期打印状态（每50步）
        if self.step % 50 == 0:
            if self.data_source == "json":
                stable_status = "已稳态" if self.stabilization_time else "暂稳态"
                recovery_text = "使用JSON数据，无预定义扰动"
                tuning_phase_status = "整定后稳态恢复中" if self.in_tuning_phase else "正常运行"

                # JSON模式下的扰动检测
                if len(self.temp_data) >= Config.JSON_DISTURBANCE_DETECTION_WINDOW:
                    is_disturbance, disturbance_desc = self.state_analyzer.detect_instability_optimized(
                        self.temp_data, Config.TARGET_TEMPERATURE, self.valve_data, self.time_data, "json"
                    )
                    if is_disturbance and not self.in_tuning_phase:
                        recovery_text = f"检测到异常扰动: {disturbance_desc}"
                        print(f"🔍 JSON模式检测到扰动: {disturbance_desc}")

                print(
                    f"时间: {self.current_time:.0f}s | 系统模式: {Config.MODES[self.system_mode]} | PID模式: {Config.PID_MODES[self.pid_mode]} | 整定方法: {Config.TUNING_METHODS[self.tuning_method]} | 实际响应温度: {self.current_temp:.1f}℃ | 无PID控制温度: {self.no_pid_current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                    f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {self.params_update_count}次 | {tuning_phase_status} | 扰动状态: {recovery_text}")
            else:
                stable_status = "已稳态" if self.stabilization_time else "暂稳态"
                recovery_text = f"当前活跃扰动: {len(self.disturbances)} | 最后扰动: {self.disturbance_generator.last_disturbance_time}s"
                tuning_phase_status = "PID整定中" if self.in_pid_tuning_phase else "正常运行"
                print(
                    f"时间: {self.current_time:.0f}s | 系统模式: {Config.MODES[self.system_mode]} | PID模式: {Config.PID_MODES[self.pid_mode]} | 整定方法: {Config.TUNING_METHODS[self.tuning_method]} | 实际响应温度: {self.current_temp:.1f}℃ | 无PID控制温度: {self.no_pid_current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                    f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {self.params_update_count}次 | {tuning_phase_status} | 扰动状态: {recovery_text}")

        # 批量更新绘图（每20步）
        if self.step % Config.PLOT_REFRESH_INTERVAL == 0:
            self.update_plots()

        # 更新状态标签
        self.temp_status_label.setText(f"当前温度: {self.current_temp:.2f}℃")
        self.error_status_label.setText(f"误差: {error:.2f}℃")
        self.valve_status_label.setText(f"阀门开度: {valve_opening:.2f}%")

        # 更新时间
        self.current_time += 1
        self.step += 1

    def perform_manual_adjustment_correction(self):
        """执行手动调整PID参数后的参数矫正"""
        print(f"🔄 手动调整PID参数后检测到扰动，开始参数矫正...")

        # 获取调整前的参数
        if self.manual_adjustment_start_params:
            prev_pb, prev_ti, prev_td = self.manual_adjustment_start_params
            print(f"调整前参数: Pb={prev_pb:.2f}%, Ti={prev_ti:.1f}s, Td={prev_td:.1f}s")

        # 使用当前数据窗口进行系统辨识
        window_start = max(0, len(self.time_data) - Config.IDENTIFY_WINDOW)
        window_t = np.array(self.time_data[window_start:]) - self.time_data[window_start]
        window_u = np.array(self.valve_data[window_start:])
        window_y = np.array(self.temp_data[window_start:])

        # 重新辨识系统参数
        new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
        lambda_val = new_T * 0.6  # 默认Lambda值

        # 根据选择的整定方法计算新参数
        if self.tuning_method == TuningMethod.LAMBDA:
            new_pb, new_ti, new_td = self.identifier.lambda_tuning(new_K, new_T, new_L, lambda_val,
                                                                   mode=self.system_mode)
        else:  # Cohen-Coon
            new_pb, new_ti, new_td = self.identifier.cohen_coon_tuning(new_K, new_T, new_L)

        # 执行参数更新（带平滑）
        self.pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)

        # 记录参数更新
        print(f"参数矫正 {self.params_update_count + 1} 次：")
        print(f"Pb: {self.pid.pb:.2f}% → {new_pb:.2f}%")
        print(f"Ti: {self.pid.ti:.1f}s → {new_ti:.1f}s")
        print(f"Td: {self.pid.td:.1f}s → {new_td:.1f}s")
        print(f"系统辨识参数: K={new_K:.3f}, T={new_T:.1f}s, L={new_L:.1f}s")

        # 更新参数显示
        self.update_params_text()
        self.params_update_count += 1
        self.update_count_label.setText(f"参数更新次数: {self.params_update_count}")

        # 🔥 生成新PID参数下的仿真轨迹
        self.simulate_new_pid_trajectory()

    def perform_pid_tuning(self):
        """在JSON模式下进行PID参数整定"""
        print(f"🔄 JSON模式：检测到扰动，开始重新整定PID参数...")

        # 使用当前数据窗口进行系统辨识
        window_start = max(0, len(self.time_data) - Config.IDENTIFY_WINDOW)
        window_t = np.array(self.time_data[window_start:]) - self.time_data[window_start]
        window_u = np.array(self.valve_data[window_start:])
        window_y = np.array(self.temp_data[window_start:])

        # 重新辨识系统参数
        new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
        lambda_val = new_T * 0.6  # 默认Lambda值

        # 根据选择的整定方法计算新参数
        if self.tuning_method == TuningMethod.LAMBDA:
            new_pb, new_ti, new_td = self.identifier.lambda_tuning(new_K, new_T, new_L, lambda_val,
                                                                   mode=self.system_mode)
        else:  # Cohen-Coon
            new_pb, new_ti, new_td = self.identifier.cohen_coon_tuning(new_K, new_T, new_L)

        # 执行参数更新（带平滑）
        self.pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)

        # 记录参数更新
        print(f"参数更新 {self.params_update_count + 1} 次：")
        print(f"Pb: {self.pid.pb:.2f}% → {new_pb:.2f}%")
        print(f"Ti: {self.pid.ti:.1f}s → {new_ti:.1f}s")
        print(f"Td: {self.pid.td:.1f}s → {new_td:.1f}s")
        print(f"系统辨识参数: K={new_K:.3f}, T={new_T:.1f}s, L={new_L:.1f}s")

        # 更新参数显示
        self.update_params_text()

        # 🔥 生成新PID参数下的仿真轨迹
        self.simulate_new_pid_trajectory()

    def simulate_new_pid_trajectory(self):
        """模拟新PID参数下的系统轨迹，以验证新参数是否能恢复稳态"""
        print(f"📈 模拟新PID参数下的系统轨迹...")

        # 获取当前时间点的状态
        if len(self.temp_data) == 0:
            return

        current_time = self.current_time
        current_temp = self.temp_data[-1]  # 当前温度
        current_valve = self.valve_data[-1] if len(self.valve_data) > 0 else 50.0  # 当前阀门开度

        # 创建临时PID控制器，使用新参数
        temp_pid = PIDController(
            pb=self.pid.target_pb,  # 使用目标参数（即新参数）
            ti=self.pid.target_ti,
            td=self.pid.target_td,
            dt=1,
            mode=self.pid_mode,
            system_mode=self.system_mode
        )

        # 创建临时温度系统（使用当前系统参数）
        temp_system = TemperatureSystem(
            K=self.temp_system.K,
            T=self.temp_system.T,
            L=self.temp_system.L,
            noise_level=0,  # 不加噪声以获得清晰的响应
            mode=self.system_mode
        )

        # 生成仿真轨迹
        sim_duration = 200  # 仿真200个时间步
        sim_times = []
        sim_temps = []
        sim_valves = []

        temp = current_temp
        valve_opening = current_valve

        for i in range(sim_duration):
            # 计算新的阀门开度
            valve_opening = temp_pid.compute(Config.TARGET_TEMPERATURE, temp)
            # 更新温度
            temp = temp_system.update(valve_opening, current_time + i, dt=1, disturbances=[])

            sim_times.append(current_time + i)
            sim_temps.append(temp)
            sim_valves.append(valve_opening)

        # 保存仿真数据
        self.new_pid_sim_time = sim_times
        self.new_pid_sim_temp = sim_temps
        self.new_pid_sim_valve = sim_valves

        # 更新图表显示
        self.new_pid_line.set_data(sim_times, sim_temps)
        print(f"✅ 新PID参数轨迹仿真完成，预测{sim_duration}步的系统响应")

        # 检查新参数是否能恢复稳态
        if len(sim_temps) >= Config.STABILIZATION_WINDOW:
            recent_temps = np.array(sim_temps[-Config.STABILIZATION_WINDOW:])
            mean_temp = np.mean(recent_temps)
            std_temp = np.std(recent_temps)

            # 检查是否接近目标温度且波动较小
            target_reached = abs(mean_temp - Config.TARGET_TEMPERATURE) <= Config.STABILIZATION_THRESHOLD
            stable = std_temp <= Config.STABILIZATION_THRESHOLD / 2

            if target_reached and stable:
                print(f"✅ 新PID参数预测：系统将恢复稳态，平均温度={mean_temp:.2f}℃, 波动={std_temp:.2f}℃")
            else:
                print(f"⚠️ 新PID参数预测：系统可能无法恢复稳态，平均温度={mean_temp:.2f}℃, 波动={std_temp:.2f}℃")

    def update_plots(self):
        """更新图表"""
        # 更新曲线数据
        self.temp_line.set_data(self.time_data, self.temp_data)
        self.valve_line.set_data(self.time_data, self.valve_data)
        self.error_line.set_data(self.time_data, self.error_data)
        self.pb_line.set_data(self.time_data, self.pb_data_list)
        self.ti_line.set_data(self.time_data, self.ti_data_list)
        self.td_line.set_data(self.time_data, self.td_data_list)
        self.no_pid_temp_line.set_data(self.time_data, self.no_pid_temp_data)

        # 更新新PID参数仿真线（如果存在）
        if len(self.new_pid_sim_time) > 0:
            self.new_pid_line.set_data(self.new_pid_sim_time, self.new_pid_sim_temp)

        # 更新x轴范围（动态扩展）
        if self.time_data:
            current_max_time = max(self.time_data)
            self.ax_temp.set_xlim(0, current_max_time * 1.1)
            self.ax_valve.set_xlim(0, current_max_time * 1.1)
            self.ax_error.set_xlim(0, current_max_time * 1.1)
            self.ax_pid.set_xlim(0, current_max_time * 1.1)

        # 更新参数更新标记
        update_times = [line.get_xdata()[0] for line in self.update_lines]
        self.update_marker.set_data(update_times, [Config.TARGET_TEMPERATURE + 8] * len(update_times))

        # 更新标题
        self.ax_temp.set_title(f'温度控制曲线（当前时间：{self.current_time:.0f}s）')

        # 刷新画布
        self.canvas.draw()

    def _adjust_pid_for_disturbance(self, disturbance_type, pb, ti, td):
        """根据扰动类型调整PID参数"""
        original_pb, original_ti, original_td = pb, ti, td

        if disturbance_type == DisturbanceType.OVERSHOOT:
            pb *= 1.1  # 增加比例带抑制超调
        elif disturbance_type == DisturbanceType.STEADY_ERROR:
            ti *= 0.8  # 减小积分时间加速消除稳态误差
        elif disturbance_type == DisturbanceType.SLOW_RECOVERY:
            pb *= 0.9  # 减少比例带加速响应
            td *= 1.1  # 增加微分增益抑制震荡
        elif disturbance_type == DisturbanceType.VALVE_STICTION:
            pb *= 1.15  # 增加比例带减少阀门频繁动作
            ti *= 1.2  # 增加积分时间适应卡涩
        elif disturbance_type == DisturbanceType.SENSOR_DRIFT:
            td *= 1.3  # 增加微分作用补偿漂移
        elif disturbance_type == DisturbanceType.HEAT_LOSS:
            pb *= 0.85  # 降低比例带补偿热损失
            ti *= 0.85  # 减少积分时间加快响应
        elif disturbance_type == DisturbanceType.CONTROL_VALVE_WEAR:
            pb *= 1.2  # 增加比例带适应磨损
            td *= 0.9  # 微调微分
        elif disturbance_type == DisturbanceType.THERMAL_INERTIA:
            ti *= 1.2  # 增加积分时间适应惯性
            td *= 1.2  # 增加微分时间

        # 应用全局参数边界保护
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)
        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)

        return pb, ti, td


def main():
    app = QApplication(sys.argv)
    window = ControlMonitorGUI()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()



