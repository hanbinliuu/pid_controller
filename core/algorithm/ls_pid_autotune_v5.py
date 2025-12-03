import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares
from scipy import signal
import logging
from datetime import datetime
import threading
from logging.handlers import TimedRotatingFileHandler
from enum import Enum
from dataclasses import dataclass
from typing import Tuple, List, Optional, Dict
import random

from core.utils.model_type import ModelType


#  固定长度仿真+自识别扰动段
#  by LiuHanBin

##### 更新：
#            1. 加入日志模块
#            2. 加入低通滤波，降噪强度选择
#            3. pid控制模块加入不同参数更新模式
#            4. 加入模式选择（标准模式、抗扰动模式、抗噪声模式）
#            5. 封装模型类型为对象

# ==============================
# 1. 配置模块
# ==============================
class Config:
    """系统配置参数集中管理"""
    # 温度参数
    INIT_TEMPERATURE = 380.0
    TARGET_TEMPERATURE = 400.0

    # 稳态判断参数
    STABILIZATION_THRESHOLD = 0.8  # 温度波动允许阈值(℃)
    STABILIZATION_WINDOW = 50  # 稳态判断窗口大小

    # 扰动配置 - 增加更多失效场景
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

    # 系统老化与辨识参数
    AGING_START_TIME = 300  # 老化开始时间(s)
    IDENTIFY_WINDOW = 200  # 参数辨识窗口大小(点数)
    PARAM_UPDATE_SMOOTH_FACTOR = 0.2  # 参数更新平滑因子

    # 扰动检测相关参数
    DETECTION_WINDOW = 60  # 扰动检测窗口大小
    ERROR_THRESHOLD = 1.5  # 误差阈值
    STD_THRESHOLD = 1.2  # 标准差阈值
    SLOPE_THRESHOLD = 0.05  # 温度变化率阈值
    VALVE_CHANGE_THRESHOLD = 25  # 阀门变化阈值
    CORRELATION_THRESHOLD = 0.3  # 相关性阈值

    # 仿真与存储参数
    SIMULATION_DURATION = 10000  # 仿真总时长(s)
    DATA_SAVE_DIR = "../../data/data_generation"  # 数据保存目录
    PLOT_REFRESH_INTERVAL = 20  # 绘图刷新间隔(步)

    # 模式配置
    MODES = {
        "standard": "标准模式",
        "anti_disturbance": "抗扰动模式",
        "anti_noise": "抗噪声模式"
    }

    # 低通滤波参数
    FILTER_ORDER = 3  # 滤波器阶数
    FILTER_CUTOFF_FREQ = 0.05  # 截止频率（相对于采样频率的比例）
    FILTER_APPLY_TO_INPUT = True  # 是否对输入信号也应用滤波
    NOISE_REDUCTION_LEVELS = {
        "low": {"cutoff_freq": 0.08, "order": 2},  # 低强度降噪
        "medium": {"cutoff_freq": 0.05, "order": 3},  # 中等强度降噪
        "high": {"cutoff_freq": 0.03, "order": 4}  # 高强度降噪
    }

    # PID模式选择
    PID_MODES = {
        "standard": "标准PID模式",
        "derivative_on_measurement": "微分先行模式",
        "proportional_derivative_on_measurement": "比例微分先行模式"
    }

    @classmethod
    def ensure_data_dir(cls):
        """确保数据目录存在"""
        os.makedirs(cls.DATA_SAVE_DIR, exist_ok=True)


# ==============================
# 2. 日志配置模块
# ==============================
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


# ==============================
# 3. 数据处理模块
# ==============================
class DataHandler:
    """数据处理工具：读取、生成、选择数据源"""

    def __init__(self):
        self.logger = LoggerSetup.setup_logger()
        self.noise_reduction_level = "medium"  # 默认降噪强度

    def apply_low_pass_filter(self, data, fs=1.0, cutoff_freq=None, order=None):
        """
        应用低通滤波器
        :param data: 输入数据数组
        :param fs: 采样频率 (默认为1Hz)
        :param cutoff_freq: 截止频率 (相对于采样频率的比例)
        :param order: 滤波器阶数
        :return: 滤波后的数据
        """
        if cutoff_freq is None:
            cutoff_freq = Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]["cutoff_freq"]
        if order is None:
            order = Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]["order"]

        # 计算归一化截止频率
        nyquist_freq = 0.5 * fs
        normalized_cutoff = cutoff_freq / nyquist_freq

        # 确保截止频率在合理范围内
        normalized_cutoff = min(normalized_cutoff, 0.99)  # 不能超过奈奎斯特频率

        # 设计Butterworth低通滤波器
        b, a = signal.butter(order, normalized_cutoff, btype='low', analog=False)

        # 应用滤波器 (使用filtfilt避免相位延迟)
        filtered_data = signal.filtfilt(b, a, data)

        return filtered_data

    def read_csv_data(self, file_path):
        """读取CSV格式的温度数据 - 与自动生成数据格式相同"""
        try:
            df = pd.read_csv(file_path)
            required_cols = ["时间(s)", "动态响应温度(℃)"]
            if not all(col in df.columns for col in required_cols):
                raise ValueError(f"CSV文件必须包含列：{required_cols}")

            df = df.dropna(subset=required_cols)
            t = df["时间(s)"].values
            temp_data = df["动态响应温度(℃)"].values

            # 如果CSV包含输入信号列，也读取它
            u = None
            if "输入信号(%)" in df.columns:
                u = df["输入信号(%)"].values
            else:
                # 如果没有输入信号列，生成默认的输入信号
                u = self._generate_default_input_signal(t)

            if not np.all(np.diff(t) >= 0):
                raise ValueError("时间序列必须单调递增，请检查数据")

            # 应用低通滤波到温度数据
            temp_data = self.apply_low_pass_filter(temp_data)
            self.logger.info(
                f"对温度数据应用了低通滤波 (降噪强度: {self.noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]['cutoff_freq']})")

            # 如果有输入信号，也可以应用滤波
            if u is not None and Config.FILTER_APPLY_TO_INPUT:
                u = self.apply_low_pass_filter(u)
                self.logger.info(
                    f"对输入信号应用了低通滤波 (降噪强度: {self.noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[self.noise_reduction_level]['cutoff_freq']})")

            self.logger.info(f"成功读取数据：{file_path}")
            self.logger.info(f"数据范围：{t.min():.0f}s ~ {t.max():.0f}s，共{len(t)}个点")
            return t, temp_data, u

        except FileNotFoundError:
            self.logger.error(f"未找到文件 '{file_path}'")
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
        return np.clip(u, 0, 100)

    def choose_data_source(self, data_type="dynamic_response"):
        """选择数据来源（仿真生成或读取CSV）"""
        print(f"\n=== 选择{data_type}数据来源 ===")
        print("1. 自动生成非阶跃仿真数据（默认）")
        print("2. 读取外部CSV数据")

        while True:
            choice = input("请输入选择（1/2，直接回车选1）：").strip() or "1"
            if choice == "1":
                t = np.arange(0, Config.SIMULATION_DURATION, 1)  # 1s间隔的时间序列
                return t, None, None
            elif choice == "2":
                file_path = input(f"请输入{data_type}CSV路径（如'./data.csv'）：").strip()
                if not file_path:
                    print("❌ 路径不能为空，请重新输入")
                    continue
                t, temp_data, u = self.read_csv_data(file_path)
                return t, temp_data, u
            else:
                print("❌ 输入错误，请选择1或2")

    def choose_mode(self):
        """选择运行模式"""
        print(f"\n=== 选择运行模式 ===")
        for i, (key, desc) in enumerate(Config.MODES.items(), 1):
            print(f"{i}. {desc} ({key})")

        while True:
            choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"
            if choice == "1":
                return "standard"
            elif choice == "2":
                return "anti_disturbance"
            elif choice == "3":
                return "anti_noise"
            else:
                print("❌ 输入错误，请选择1-3")

    def choose_noise_reduction_level(self):
        """选择降噪强度"""
        print(f"\n=== 选择降噪强度 ===")
        print("1. 低强度降噪 (截止频率较高，保留更多细节)")
        print("2. 中等强度降噪 (平衡降噪效果和细节保留)")
        print("3. 高强度降噪 (截止频率较低，降噪效果显著)")

        while True:
            choice = input("请选择降噪强度（1-3，直接回车选2）：").strip() or "2"
            if choice == "1":
                self.noise_reduction_level = "low"
                return "low"
            elif choice == "2":
                self.noise_reduction_level = "medium"
                return "medium"
            elif choice == "3":
                self.noise_reduction_level = "high"
                return "high"
            else:
                print("❌ 输入错误，请选择1-3")

    def choose_pid_mode(self):
        """选择PID控制模式"""
        print(f"\n=== 选择PID控制模式 ===")
        for i, (key, desc) in enumerate(Config.PID_MODES.items(), 1):
            print(f"{i}. {desc} ({key})")

        while True:
            choice = input("请选择PID模式（1-3，直接回车选1）：").strip() or "1"
            if choice == "1":
                return "standard"
            elif choice == "2":
                return "derivative_on_measurement"
            elif choice == "3":
                return "proportional_derivative_on_measurement"
            else:
                print("❌ 输入错误，请选择1-3")

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


# ==============================
# 4. 扰动处理模块
# ==============================
class DisturbanceHandler:
    """扰动处理模块：管理各种系统扰动"""

    def __init__(self, mode="standard"):
        self.mode = mode
        self.disturbance_functions = {
            "overshoot": self._apply_overshoot,
            "steady_error": self._apply_steady_error,
            "slow_recovery": self._apply_slow_recovery,
            "valve_stiction": self._apply_valve_stiction,
            "sensor_drift": self._apply_sensor_drift,
            "heat_loss": self._apply_heat_loss,
            "control_valve_wear": self._apply_control_valve_wear,
            "thermal_inertia": self._apply_thermal_inertia
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
        if self.mode == "anti_disturbance":
            # 抗扰动模式下扰动幅度减小
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            # 抗噪声模式下扰动幅度减小
            amplitude *= 0.8
        return current_temp + amplitude * (1.2 - decay) + np.random.normal(0, 1.2)

    def _apply_steady_error(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            amplitude *= 0.8
        turbulent = np.sin((time - start_time) * 0.1) * amplitude * 0.3
        return current_temp + amplitude + turbulent + np.random.normal(0, 0.9)

    def _apply_slow_recovery(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.6
        elif self.mode == "anti_noise":
            amplitude *= 0.7
        fluctuation = np.sin((time - start_time) * 0.2) * amplitude * 0.8
        return current_temp + fluctuation + np.random.normal(0, 1.3)

    def _apply_valve_stiction(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 阀门卡涩：降低阀门响应灵敏度
        system_state['valve_stiction_level'] = amplitude * 0.1
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.6
        elif self.mode == "anti_noise":
            amplitude *= 0.7
        # 阀门响应延迟
        return current_temp + np.random.normal(0, amplitude * 0.3)

    def _apply_sensor_drift(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 传感器漂移：温度测量偏差
        sensor_drift = amplitude * np.sin((time - start_time) * 0.01)
        system_state['sensor_drift'] = sensor_drift
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            amplitude *= 0.8
        return current_temp + sensor_drift + np.random.normal(0, 0.5)

    def _apply_heat_loss(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 热损失增加：温度下降
        loss_factor = 1 - amplitude * 0.001 * (time - start_time) / duration
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            amplitude *= 0.8
        return current_temp * loss_factor + np.random.normal(0, 0.8)

    def _apply_control_valve_wear(self, time, current_temp, valve_opening, amplitude, duration, start_time,
                                  system_state):
        # 控制阀磨损：增益下降
        wear_factor = 1 - amplitude * 0.0005 * (time - start_time) / duration
        system_state['K'] = system_state['initial_K'] * wear_factor
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            amplitude *= 0.8
        return current_temp + np.random.normal(0, 0.6)

    def _apply_thermal_inertia(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):
        # 热惯性变化：时间常数增大
        inertia_factor = 1 + amplitude * 0.001 * (time - start_time) / duration
        system_state['T'] = system_state['initial_T'] * inertia_factor
        # 根据模式调整扰动强度
        if self.mode == "anti_disturbance":
            amplitude *= 0.7
        elif self.mode == "anti_noise":
            amplitude *= 0.8
        return current_temp + np.random.normal(0, 0.7)


# ==============================
# 5. 系统模型模块
# ==============================
class TemperatureSystem:
    """温度系统模型：模拟温度动态响应、老化和扰动"""

    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3, mode="standard"):
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
        if self.mode == "anti_disturbance":
            aging_factor *= 0.8  # 减缓老化
        elif self.mode == "anti_noise":
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
            if self.mode == "anti_noise":
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
        if self.mode == "anti_noise":
            # 抗噪声模式下降低噪声
            noise = np.random.normal(0, self.noise_level * 0.6)
        else:
            noise = np.random.normal(0, self.noise_level)

        output_temp += noise

        # 返回真实温度（不包含传感器漂移）
        return output_temp - self.sensor_drift


# ==============================
# 6. 控制器模块
# ==============================
class PIDController:
    """PID控制器：实现PID控制与参数平滑更新"""

    def __init__(self, Kp=0.0, Ti=0.0, Td=0.0, dt=1.0, u_min=0, u_max=100, mode="standard", system_mode="standard"):
        self.Kp = float(Kp)
        self.Ti = float(Ti)
        self.Td = float(Td)
        self.target_Kp = float(Kp)  # 目标参数（用于平滑更新）
        self.target_Ti = float(Ti)
        self.target_Td = float(Td)

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

    def compute(self, setpoint, process_var):
        """计算PID输出（含抗积分饱和）"""
        error = setpoint - process_var #过程差
        self.setpoint = setpoint  # 记录设定值

        # 根据系统模式调整控制策略
        if self.system_mode == "anti_disturbance":
            # 抗扰动模式：降低微分增益，减少对扰动的敏感性
            adjusted_Td = self.Td * 0.7
        elif self.system_mode == "anti_noise":
            # 抗噪声模式：降低微分增益，减少对噪声的敏感性
            adjusted_Td = self.Td * 0.5
        else:
            adjusted_Td = self.Td

        # 根据不同模式计算输出
        proportional = 0.0  # 初始化，避免未绑定
        if self.mode == "standard":
            # 标准PID: u(t) = Kp * e(t) + Ki * ∫e(t)dt + Kd * de(t)/dt
            proportional = self.Kp * error

            # 积分项（抗积分饱和）
            integral_term = 0.0
            if self.Ti > 1e-6:
                integral_term = (self.Kp / self.Ti) * error * self.dt
                # 预计算输出，判断是否饱和
                temp_output = proportional + self.integral + integral_term + self.derivative
                if not (self.u_min <= temp_output <= self.u_max):
                    integral_term = 0  # 输出饱和时不累积积分
                self.integral += integral_term
                # 积分限幅
                self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

            # 微分项（指数平滑减少噪声）
            if adjusted_Td > 1e-6 and self.last_error != 0:
                self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * adjusted_Td) * (
                        error - self.last_error) / self.dt

        elif self.mode == "derivative_on_measurement":
            # 微分先行: u(t) = Kp * e(t) + Ki * ∫e(t)dt - Kd * dy(t)/dt
            proportional = self.Kp * error

            # 积分项（抗积分饱和）
            integral_term = 0.0
            if self.Ti > 1e-6:
                integral_term = (self.Kp / self.Ti) * error * self.dt
                # 预计算输出，判断是否饱和
                temp_output = proportional + self.integral + integral_term - self.derivative
                if not (self.u_min <= temp_output <= self.u_max):
                    integral_term = 0  # 输出饱和时不累积积分
                self.integral += integral_term
                # 积分限幅
                self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

            # 微分项（基于测量值，避免设定值突变引起的冲击）
            if adjusted_Td > 1e-6 and self.last_process_var != 0:
                self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * adjusted_Td) * (
                        self.last_process_var - process_var) / self.dt

        elif self.mode == "proportional_derivative_on_measurement":
            # 比例微分先行: u(t) = Ki * ∫e(t)dt + Kp * (setpoint - y(t)) - Kd * dy(t)/dt
            # 修复：比例项基于设定值与测量值的差，微分项基于测量值变化
            proportional = self.Kp * (setpoint - process_var)  # 比例项基于设定值与测量值的差

            # 积分项（抗积分饱和）
            integral_term = 0.0
            if self.Ti > 1e-6:
                integral_term = (self.Kp / self.Ti) * error * self.dt
                # 预计算输出，判断是否饱和
                temp_output = integral_term + proportional - self.derivative
                if not (self.u_min <= temp_output <= self.u_max):
                    integral_term = 0  # 输出饱和时不累积积分
                self.integral += integral_term
                # 积分限幅
                self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

            # 微分项（基于测量值变化，避免设定值突变引起的冲击）
            if adjusted_Td > 1e-6 and self.last_process_var != 0:
                self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * adjusted_Td) * (
                        self.last_process_var - process_var) / self.dt
        else:
            # 其他模式：使用标准PID
            proportional = self.Kp * error
            integral_term = 0.0
            if self.Ti > 1e-6:
                integral_term = (self.Kp / self.Ti) * error * self.dt
                temp_output = proportional + self.integral + integral_term + self.derivative
                if not (self.u_min <= temp_output <= self.u_max):
                    integral_term = 0
                self.integral += integral_term
                self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)
            if adjusted_Td > 1e-6 and self.last_error != 0:
                self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * adjusted_Td) * (
                        error - self.last_error) / self.dt

        # 总输出与限幅
        if self.mode == "proportional_derivative_on_measurement":
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
        self.Kp = self.Kp * (1 - self.smoothing_factor) + self.target_Kp * self.smoothing_factor
        self.Ti = self.Ti * (1 - self.smoothing_factor) + self.target_Ti * self.smoothing_factor
        self.Td = self.Td * (1 - self.smoothing_factor) + self.target_Td * self.smoothing_factor

    def set_target_params(self, Kp, Ti, Td, reset_integral=False):
        """设置目标参数（用于平滑更新）"""
        self.target_Kp = Kp
        self.target_Ti = Ti
        self.target_Td = Td
        if reset_integral:
            self.integral = 0.0  # 参数更新时重置积分项

    def reset(self):
        """重置控制器状态"""
        self.last_error = 0.0
        self.integral = 0.0
        self.derivative = 0.0
        self.last_process_var = 0.0


# ==============================
# 7. 辨识与整定模块
# ==============================
class SystemIdentifier:
    """系统辨识与PID整定工具：基于FOPDT模型和Lambda方法"""

    @staticmethod
    def estimate_initial_guess(t, y, u, model_type='FOPDT', transient_mode=False):
        """统一的初始猜测值估算方法

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列
            model_type: 模型类型（'FOPDT', 'FO', 'SOPDT', 'SO', 'FO_INTEGRATOR', 'SO_INTEGRATOR'）
            transient_mode: 是否使用瞬态模式

        Returns:
            tuple: (initial_guess, bounds) - 初始猜测和参数边界
        """
        # 基本参数计算
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])
        u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
        u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])

        # 计算增益 K
        if transient_mode:
            u_range = np.ptp(u)
            y_range = np.ptp(y)
            gain_guess = y_range / u_range if u_range > 1e-6 else 0.5
        else:
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = delta_y / delta_u if delta_u > 1e-6 else 0.5

        gain_guess = max(gain_guess, 0.01)

        # 计算滞后时间 L
        dy = np.abs(np.diff(y))
        L_guess = 0.01
        if len(dy) > 0 and np.max(dy) > 1e-6:
            response_threshold = 0.05 * np.max(dy)
            for i in range(len(dy)):
                if dy[i] > response_threshold:
                    L_guess = max(t[i] - t[0], 0.01)
                    break

        # 计算时间常数 T
        T_guess = 10.0
        if len(y) > 1 and len(t) > 1:
            y_max = np.max(y)
            threshold_63 = y0 + 0.632 * (y_final - y0)
            response_start_idx = max(0, int(L_guess / (t[1] - t[0]) if (t[1] - t[0]) > 0 else 0))
            for i in range(response_start_idx, len(y)):
                if y[i] >= threshold_63:
                    rise_time = t[i] - t[response_start_idx] if response_start_idx < len(t) else 0
                    T_guess = max(rise_time, 1.0)
                    break

        # 根据模型类型返回对应的初始猜测和边界
        if model_type == 'FOPDT':
            initial_guess = [gain_guess, T_guess, L_guess]
            bounds = ([0.001, 0.1, 0.01], [10.0, 500.0, 100.0])
        elif model_type == 'FO':
            initial_guess = [gain_guess, T_guess]
            bounds = ([0.001, 0.1], [10.0, 500.0])
        elif model_type in ['SOPDT', 'SO']:
            # 对于二阶模型，需要估算 T1 和 T2
            du = np.abs(np.diff(u))
            step_idx = np.argmax(du) if len(du) > 0 and np.max(du) > 0 else 0

            T1_guess, T2_guess = 10.0, 5.0
            if step_idx < len(y) - 10:
                peak_idx = np.argmax(y[step_idx:]) + step_idx
                t_peak = t[peak_idx] - t[step_idx] if step_idx < len(t) else 0
                T_eq_guess = max(t_peak * 0.6, 2.0)
                T1_guess = T_eq_guess * 0.6
                T2_guess = T_eq_guess * 0.4

            if model_type == 'SOPDT':
                initial_guess = [gain_guess, T1_guess, T2_guess, L_guess]
                bounds = ([0.001, 0.1, 0.1, 0.01], [10.0, 500.0, 500.0, 100.0])
            else:  # SO
                initial_guess = [gain_guess, T1_guess, T2_guess]
                bounds = ([0.001, 0.1, 0.1], [10.0, 500.0, 500.0])
        elif model_type == 'FO_INTEGRATOR':
            dy = np.diff(y)
            dt_arr = np.diff(t)
            dy_dt = dy / dt_arr if len(dt_arr) > 0 else np.zeros_like(dy)
            mid_start, mid_end = len(y) // 3, 2 * len(y) // 3
            u_mid = np.mean(u[mid_start:mid_end])
            dy_dt_mid = np.mean(dy_dt[mid_start:mid_end]) if len(dy_dt) > mid_end else 0.0
            K_guess = abs(dy_dt_mid * 10.0 / u_mid) if abs(u_mid) > 1e-6 else 0.1
            K_guess = max(K_guess, 0.01)
            initial_guess = [K_guess, 10.0]
            bounds = ([0.001, 0.1], [10.0, 500.0])
        elif model_type == 'SO_INTEGRATOR':
            dy = np.diff(y)
            dt_arr = np.diff(t)
            dy_dt = dy / dt_arr if len(dt_arr) > 0 else np.zeros_like(dy)
            mid_start, mid_end = len(y) // 3, 2 * len(y) // 3
            u_mid = np.mean(u[mid_start:mid_end])
            dy_dt_mid = np.mean(dy_dt[mid_start:mid_end]) if len(dy_dt) > mid_end else 0.0
            K_guess = abs(dy_dt_mid * 20.0 / u_mid) if abs(u_mid) > 1e-6 else 0.1
            K_guess = max(K_guess, 0.01)
            initial_guess = [K_guess, 15.0, 10.0]
            bounds = ([0.001, 0.1, 0.1], [10.0, 500.0, 500.0])
        else:
            raise ValueError(f"不支持的模型类型: {model_type}")

        return initial_guess, bounds

    @staticmethod
    def fopdt_model(params, t, u, y0):
        """一阶加纯滞后（FOPDT）模型

        微分方程: dy/dt = (y0 + K*u_delayed - y) / T
        离散化: y[i] = y[i-1] + (y0 + K*u_delayed - y[i-1]) / T * dt
        """
        K, T, L = params
        y = np.ones_like(t) * y0
        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1

            # 计算纯滞后对应的采样点数（基于实际时间间隔）
            delay_steps = int(np.round(L / dt)) if dt > 0 else 0

            # 考虑纯滞后：使用delay_steps前的输入
            if i > delay_steps:
                u_delayed = u[i - delay_steps]
            else:
                u_delayed = u[i]  # 滞后期间输入为0

            # 一阶惯性微分方程: dy/dt = (y0 + K*u - y) / T
            # 离散化: y[i] = y[i-1] + (y0 + K*u_delayed - y[i-1]) / T * dt
            steady_state = y0 + K * u_delayed
            y[i] = y[i - 1] + (steady_state - y[i - 1]) / T * dt

        return y

    @staticmethod
    def first_order_model(params, t, u, y0):
        """一阶模型（无滞后）

        微分方程: dy/dt = (y0 + K*u - y) / T
        离散化: y[i] = y[i-1] + (y0 + K*u[i] - y[i-1]) / T * dt
        """
        K, T = params
        y = np.ones_like(t) * y0

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            # 一阶模型：稳态值 = y0 + K*u
            steady_state = y0 + K * u[i]
            y[i] = y[i - 1] + (steady_state - y[i - 1]) / T * dt

        return y

    @staticmethod
    def second_order_model(params, t, u, y0):
        """二阶模型（二阶加纯滞后 SOPDT）

        传递函数: G(s) = K / ((T1*s + 1)(T2*s + 1)) * e^(-L*s)
        微分方程: T1*T2*d2y/dt2 + (T1+T2)*dy/dt + y = K*u_delayed + y0
        状态空间形式：
            x1' = x2
            x2' = (K*u_delayed + y0 - x1 - (T1+T2)*x2) / (T1*T2)
            y = x1
        """
        K, T1, T2, L = params
        y = np.ones_like(t) * y0
        x1 = y0  # 状态变量1（输出）
        x2 = 0.0  # 状态变量2（一阶导数）

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1

            # 计算纯滞后对应的采样点数
            delay_steps = int(np.round(L / dt)) if dt > 0 else 0

            # 考虑纯滞后
            if i > delay_steps:
                u_delayed = u[i - delay_steps]
            else:
                u_delayed = 0.0

            # 二阶系统状态方程
            # x1' = x2
            # x2' = (K*u_delayed + y0 - x1 - (T1+T2)*x2) / (T1*T2)
            dx1 = x2
            dx2 = (K * u_delayed + y0 - x1 - (T1 + T2) * x2) / (T1 * T2) if (T1 * T2) > 1e-6 else 0.0

            x1 = x1 + dx1 * dt
            x2 = x2 + dx2 * dt
            y[i] = x1

        return y

    @staticmethod
    def second_order_no_delay_model(params, t, u, y0):
        """纯二阶模型（Second Order, 无滞后）

        传递函数: G(s) = K / ((T1*s + 1)(T2*s + 1))
        状态空间形式：
            x1' = x2
            x2' = (K*u + y0 - x1 - (T1+T2)*x2) / (T1*T2)
            y = x1
        """
        K, T1, T2 = params
        y = np.ones_like(t) * y0
        x1 = 0.0  # 状态1
        x2 = 0.0  # 状态2

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1

            # 二阶系统状态方程（无滞后）
            dx1 = x2
            dx2 = (K * u[i] + y0 - x1 - (T1 + T2) * x2) / (T1 * T2) if (T1 * T2) > 1e-6 else 0.0

            x1 = x1 + dx1 * dt
            x2 = x2 + dx2 * dt
            y[i] = x1

        return y

    @staticmethod
    def first_order_integrator_model(params, t, u, y0):
        """一阶积分模型（First Order Plus Integrator, FOPI）

        传递函数: G(s) = K / (s(Ts + 1))
        微分方程: T*dy/dt + y = K*integral(u*dt) + y0
        状态空间形式：
            x1' = K*u  (积分项)
            x2' = (x1 - x2) / T  (一阶惯性)
            y = x2 + y0
        """
        K, T = params
        # 确保参数在安全范围内
        K = np.clip(K, 0.001, 100.0)
        T = np.clip(T, 0.1, 1000.0)

        y = np.ones_like(t) * y0
        x1 = 0.0  # 积分状态
        x2 = 0.0  # 一阶惯性状态

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            dt = np.clip(dt, 0.01, 100.0)  # 限制时间步长

            # 积分项更新
            dx1 = K * u[i]
            x1 = x1 + dx1 * dt

            # 一阶惯性更新
            dx2 = (x1 - x2) / T if T > 1e-6 else x1
            x2 = x2 + dx2 * dt

            # 防止数值溢出
            x1 = np.clip(x1, -1e6, 1e6)
            x2 = np.clip(x2, -1e6, 1e6)

            y[i] = x2 + y0

            # 检查并修正无效值
            if not np.isfinite(y[i]):
                y[i] = y[i-1] if i > 0 else y0

        return y

    @staticmethod
    def second_order_integrator_model(params, t, u, y0):
        """二阶积分模型（Second Order Integrator, SOPI）

        传递函数: G(s) = K / (s^2 * (T1*s + 1)(T2*s + 1))
        状态空间形式：
            x1' = K*u  (第一次积分)
            x2' = x1  (第二次积分)
            x3' = (x2 - x3) / T1  (第一个一阶惯性)
            x4' = (x3 - x4) / T2  (第二个一阶惯性)
            y = x4 + y0
        """
        K, T1, T2 = params
        # 确保参数在安全范围内
        K = np.clip(K, 0.001, 100.0)
        T1 = np.clip(T1, 0.1, 1000.0)
        T2 = np.clip(T2, 0.1, 1000.0)

        y = np.ones_like(t) * y0
        x1 = 0.0  # 第一次积分状态
        x2 = 0.0  # 第二次积分状态
        x3 = 0.0  # 第一个一阶惯性状态
        x4 = 0.0  # 第二个一阶惯性状态

        for i in range(len(t)):
            dt = t[i] - t[i - 1] if i > 0 else 1
            dt = np.clip(dt, 0.01, 100.0)  # 限制时间步长

            # 第一次积分更新
            dx1 = K * u[i]
            x1 = x1 + dx1 * dt

            # 第二次积分更新
            dx2 = x1
            x2 = x2 + dx2 * dt

            # 第一个一阶惯性更新
            dx3 = (x2 - x3) / T1 if T1 > 1e-6 else x2
            x3 = x3 + dx3 * dt

            # 第二个一阶惯性更新
            dx4 = (x3 - x4) / T2 if T2 > 1e-6 else x3
            x4 = x4 + dx4 * dt

            # 防止数值溢出
            x1 = np.clip(x1, -1e6, 1e6)
            x2 = np.clip(x2, -1e6, 1e6)
            x3 = np.clip(x3, -1e6, 1e6)
            x4 = np.clip(x4, -1e6, 1e6)

            y[i] = x4 + y0

            # 检查并修正无效值
            if not np.isfinite(y[i]):
                y[i] = y[i-1] if i > 0 else y0

        return y

    @staticmethod
    def residuals(params, t, u, y_measured, y0, model_type='FOPDT'):
        """最小二乘优化的残差函数（带权重优化）"""
        if model_type == 'FO':
            y_predicted = SystemIdentifier.first_order_model(params, t, u, y0)
        elif model_type == 'SOPDT':
            y_predicted = SystemIdentifier.second_order_model(params, t, u, y0)
        elif model_type == 'SO':
            y_predicted = SystemIdentifier.second_order_no_delay_model(params, t, u, y0)
        elif model_type == 'FO_INTEGRATOR':
            y_predicted = SystemIdentifier.first_order_integrator_model(params, t, u, y0)
        elif model_type == 'SO_INTEGRATOR':
            y_predicted = SystemIdentifier.second_order_integrator_model(params, t, u, y0)
        else:  # FOPDT
            y_predicted = SystemIdentifier.fopdt_model(params, t, u, y0)

        residual = y_predicted - y_measured

        # 对于二阶模型，对峰值区域增加权重以改善峰值拟合
        if model_type in ['SOPDT', 'SO']:
            weights = np.ones_like(y_measured)
            # 找到峰值位置
            peak_idx = np.argmax(y_measured)
            # 对峰值附近±15个点增加2倍权重
            start_idx = max(0, peak_idx - 15)
            end_idx = min(len(y_measured), peak_idx + 15)
            weights[start_idx:end_idx] = 2.0
            # 对峰值附近±5个点增加3倍权重
            start_idx2 = max(0, peak_idx - 5)
            end_idx2 = min(len(y_measured), peak_idx + 5)
            weights[start_idx2:end_idx2] = 3.0
            residual = residual * weights

        return residual

    @staticmethod
    def identify_fopdt(t, y, u, transient_mode=False):
        """用最小二乘法辨识FOPDT模型参数（K, T, L）

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列
            transient_mode: 是否使用瞬态模式（默认False，使用稳态模式）
                          - False: 稳态模式，适合末段已稳定的数据
                          - True: 瞬态模式，适合MV有激励但未达稳态的异常段数据
        """
        # y0：使用该段起始的均值（而非末尾），以便正确计算初值偏移
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])

        # 基于稳态变化量估算增益K
        u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
        u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
        delta_u = abs(u_final - u_initial)
        delta_y = abs(y_final - y0)
        gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5
        gain_guess = max(gain_guess, 0.01)

        # 改进：基于阶跃点检测动态估算 T 和 L 的初值
        du = np.abs(np.diff(u))
        u_range = np.max(u) - np.min(u)
        step_threshold_abs = u_range * 0.05 if u_range > 1e-6 else 0.05

        T_guess = 30.0  # 默认值
        L_guess = 5.0   # 默认值

        if np.max(du) >= step_threshold_abs:
            step_idx = int(np.argmax(du))  # 找最大输入变化点

            # 基于 20% 响应阈值估算 L（纯滞后时间）
            y_range_full = y_final - y0
            response_threshold = y0 + 0.2 * y_range_full if abs(y_range_full) > 1e-6 else y0 + 0.1
            response_indices = np.where(y[step_idx:] >= response_threshold)[0]
            if len(response_indices) > 0:
                L_guess = max(t[step_idx + response_indices[0]] - t[step_idx], 0.0)
            else:
                L_guess = 0.0

            # 基于 63.2% 响应阈值估算 T（时间常数）
            if abs(y_range_full) > 1e-6:
                threshold_63 = y0 + 0.632 * y_range_full
                rise_indices = np.where(y[step_idx:] >= threshold_63)[0]
                if len(rise_indices) > 0:
                    T_calculated = t[step_idx + rise_indices[0]] - t[step_idx]
                    T_guess = np.clip(T_calculated, 1.0, 500.0)
                else:
                    # 降级策略：如果找不到 63.2% 点，使用最大响应点
                    closest_idx = np.argmax(y[step_idx:])
                    if closest_idx >= 0:
                        T_calculated = t[step_idx + closest_idx] - t[step_idx]
                        T_guess = np.clip(T_calculated, 1.0, 500.0)

        # 初始猜测与参数边界
        initial_guess = [gain_guess, T_guess, L_guess]  # K, T, L
        bounds = ([0.001, 1.0, 0.0], [10.0, 500.0, 100.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'FOPDT'),
                bounds=bounds,
                verbose=0,
                max_nfev=3000,  # 进一步增加最大迭代次数
                ftol=1e-10,     # 更严格的函数收敛容差
                xtol=1e-10,     # 更严格的参数收敛容差
                loss='soft_l1'  # 使用鲁棒损失函数，对异常点不敏感
            )
            K, T, L = result.x
        except Exception as e:
            print(f"参数辨识失败：{e}，使用初始猜测值")
            K, T, L = initial_guess

        # 确保参数为正值
        K = np.clip(K, 0.05, 1.5)
        T = np.clip(T, 5.0, 150.0)
        L = np.clip(L, 0.0, 20.0)
        return K, T, L

    @staticmethod
    def identify_first_order_integrator(t, y, u, transient_mode=False):
        """用最小二乘法辨识一阶积分模型参数（K, T）"""
        y0 = np.mean(y[:10]) if len(y) > 10 else np.mean(y)  # 初始值估计
        # y0：使用该段起始的均值
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])

        # 改进：针对有超调的系统，使用峰值估算增益
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])
        y_max = np.max(y)
        # 判断是否有超调（峰值明显高于稳态值）
        has_overshoot = (y_max - y0) > 1.2 * (y_final - y0) and (y_max - y_final) > 0.1 * (y_final - y0)

        if has_overshoot:
            # 有超调：使用稳态值估算增益，而非峰值
            print(f"检测到超调：y_max={y_max:.2f}, y_final={y_final:.2f}, y0={y0:.2f}")
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5
        elif transient_mode:
            # 瞄态模式：使用峰峰值估算增益
            u_range = np.ptp(u)
            y_range = np.ptp(y)
            gain_guess = (y_range / u_range) if u_range > 1e-6 else 0.5
        else:
            # 稳态模式：使用稳态变化量估算增益
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])

            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5

        gain_guess = max(gain_guess, 0.01)
        # # K 估算：基于输出变化率
        # dy = np.diff(y)
        # dt_arr = np.diff(t)
        # dy_dt = dy / dt_arr if len(dt_arr) > 0 else np.zeros_like(dy)
        # mid_start, mid_end = len(y) // 3, 2 * len(y) // 3
        # u_mid = np.mean(u[mid_start:mid_end]) if mid_end <= len(u) else np.mean(u)
        # dy_dt_mid = np.mean(dy_dt[mid_start:mid_end]) if len(dy_dt) > mid_end else 0.0
        # K_guess = abs(dy_dt_mid * 10.0 / u_mid) if abs(u_mid) > 1e-6 else 0.1
        # K_guess = max(K_guess, 0.01)

        # 初始猜测与参数边界
        initial_guess = [gain_guess, 10.0]  # K, T
        bounds = ([0.001, 0.1], [10.0, 500.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'FO_INTEGRATOR'),
                bounds=bounds,
                verbose=0
            )
            K, T = result.x
        except Exception as e:
            print(f"一阶积分模型参数辨识失败：{e}，使用初始猜测值")
            K, T = initial_guess

        # 确保参数为正值
        K = np.clip(K, 0.05, 1.5)
        T = np.clip(T, 5.0, 150.0)

        return K, T

    @staticmethod
    def identify_first_order(t, y, u, transient_mode=False):
        """用最小二乘法辨识一阶模型参数（K, T）"""
        # y0：使用该段起始的均值
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])

        # 改进：针对有超调的系统，使用峰值估算增益
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])
        y_max = np.max(y)
        # 判断是否有超调（峰值明显高于稳态值）
        has_overshoot = (y_max - y0) > 1.2 * (y_final - y0) and (y_max - y_final) > 0.1 * (y_final - y0)

        if has_overshoot:
            # 有超调：使用稳态值估算增益，而非峰值
            print(f"检测到超调：y_max={y_max:.2f}, y_final={y_final:.2f}, y0={y0:.2f}")
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5
        elif transient_mode:
            # 瞄态模式：使用峰峰值估算增益
            u_range = np.ptp(u)
            y_range = np.ptp(y)
            gain_guess = (y_range / u_range) if u_range > 1e-6 else 0.5
        else:
            # 稳态模式：使用稳态变化量估算增益
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])

            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5

        gain_guess = max(gain_guess, 0.01)
        # gain_guess = (max_y - y0) / max_u if max_u > 1e-6 else 0.5

        # 初始猜测与参数边界
        initial_guess = [max(gain_guess, 0.1), 1.0]  # K, T
        # bounds = ([0.05, 0.1], [2.0, 10.0])
        bounds = ([0.001, 0.1], [10.0, 500.0])  # 大幅放宽边界

        try:
            # result = least_squares(
            #     SystemIdentifier.residuals,
            #     initial_guess,
            #     args=(t, u, y, y0, 'FO'),
            #     bounds=bounds,
            #     verbose=0
            # )
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'FO'),
                bounds=bounds,
                verbose=0,
                max_nfev=3000,  # 进一步增加最大迭代次数
                ftol=1e-10,     # 更严格的函数收敛容差
                xtol=1e-10,     # 更严格的参数收敛容差
                loss='soft_l1'  # 使用鲁棒损失函数，对异常点不敏感
            )
            K, T = result.x
        except Exception as e:
            print(f"一阶模型参数辨识失败：{e}，使用初始猜测值")
            K, T = initial_guess

        # 确保参数在合理范围
        K = np.clip(K, 0.05, 2.0)
        T = np.clip(T, 0.1, 10.0)
        return K, T

    @staticmethod
    def identify_second_order(t, y, u, transient_mode=False):
        """用最小二乘法辨识二阶模型参数（K, T1, T2, L）

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列
            transient_mode: 是否使用瞄态模式

        Returns:
            tuple: (K, T1, T2, L) 四个参数
        """
        # y0：使用该段起始的均值
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])

        # 改进：针对有超调的系统，使用峰值估算增益
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])
        y_max = np.max(y)

        # 判断是否有超调（峰值明显高于稳态值）
        has_overshoot = (y_max - y0) > 1.2 * (y_final - y0) and (y_max - y_final) > 0.1 * (y_final - y0)

        if has_overshoot:
            # 有超调：使用稳态值估算增益，而非峰值
            print(f"检测到超调：y_max={y_max:.2f}, y_final={y_final:.2f}, y0={y0:.2f}")
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5
        elif transient_mode:
            # 瞄态模式：使用峰峰值估算增益
            u_range = np.ptp(u)
            y_range = np.ptp(y)
            gain_guess = (y_range / u_range) if u_range > 1e-6 else 0.5
        else:
            # 稳态模式：使用稳态变化量估算增益
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])

            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5

        gain_guess = max(gain_guess, 0.01)

        # 改进：智能估算T1、T2和L
        # 找到输入阶跃的时刻
        du = np.abs(np.diff(u))
        if len(du) > 0 and np.max(du) > 0:
            step_idx = np.argmax(du)
        else:
            step_idx = 0

        # 估算上升时间和峰值时间
        if step_idx < len(y) - 10:
            # 找到峰值时刻
            peak_idx = np.argmax(y[step_idx:]) + step_idx
            t_peak = t[peak_idx] - t[step_idx]

            # 找到响应开始的时刻（估算L）
            dy = np.abs(np.diff(y))
            response_start_idx = step_idx
            for i in range(step_idx, min(step_idx + 50, len(dy))):
                if dy[i] > 0.01 * np.max(dy):
                    response_start_idx = i
                    break
            L_guess = max(t[response_start_idx] - t[step_idx], 0.0)

            # 估算T1和T2（基于峰值时间）
            # 对于二阶欠阻尼系统，峰值时间约为 T_eq = T1 + T2
            T_eq_guess = max(t_peak * 0.6, 2.0)  # 经验公式
            T1_guess = T_eq_guess * 0.6  # T1 通常较大
            T2_guess = T_eq_guess * 0.4
        else:
            T1_guess = 20.0
            T2_guess = 10.0
            L_guess = 3.0

        # 初始猜测与参数边界
        initial_guess = [gain_guess, T1_guess, T2_guess, L_guess]  # K, T1, T2, L
        bounds = ([0.001, 0.1, 0.1, 0.0], [10.0, 500.0, 500.0, 100.0])

        print(f"二阶模型初始猜测: K={gain_guess:.3f}, T1={T1_guess:.2f}, T2={T2_guess:.2f}, L={L_guess:.2f}")

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'SOPDT'),
                bounds=bounds,
                verbose=0,
                max_nfev=3000,  # 进一步增加最大迭代次数
                ftol=1e-10,     # 更严格的函数收敛容差
                xtol=1e-10,     # 更严格的参数收敛容差
                loss='soft_l1'  # 使用鲁棒损失函数，对异常点不敏感
            )
            K, T1, T2, L = result.x
            print(f"二阶模型辨识结果: K={K:.3f}, T1={T1:.2f}, T2={T2:.2f}, L={L:.2f}")
            print(f"优化迭代次数: {result.nfev}, 优化成功: {result.success}, 最终残差: {result.cost:.6f}")
        except Exception as e:
            print(f"二阶模型参数辨识失败：{e}，使用初始猜测值")
            K, T1, T2, L = initial_guess

        # 确保参数为正值
        # K = max(K, 0.001)
        # T1 = max(T1, 0.1)
        # T2 = max(T2, 0.1)
        # L = max(L, 0.0)
        K = np.clip(K, 0.05, 1.5)
        T1 = np.clip(T1, 5.0, 150.0)
        T2 = np.clip(T2, 5.0, 150.0)
        L = np.clip(L, 0.0, 20.0)
        return K, T1, T2, L

    @staticmethod
    def identify_second_order_no_delay(t, y, u, transient_mode=False):
        """用最小二乘法辨识纯二阶模型参数（K, T1, T2）（无滞后）

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列
            transient_mode: 是否使用瘴态模式

        Returns:
            tuple: (K, T1, T2) 三个参数
        """
        # 复用二阶模型的逻辑，但只返回 K, T1, T2（不包含L）
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])
        y_final = np.mean(y[-30:]) if len(y) > 30 else np.mean(y[-min(10, len(y)):])
        y_max = np.max(y)

        has_overshoot = (y_max - y0) > 1.2 * (y_final - y0) and (y_max - y_final) > 0.1 * (y_final - y0)

        if has_overshoot:
            print(f"检测到超调：y_max={y_max:.2f}, y_final={y_final:.2f}, y0={y0:.2f}")
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5
        elif transient_mode:
            u_range = np.ptp(u)
            y_range = np.ptp(y)
            gain_guess = (y_range / u_range) if u_range > 1e-6 else 0.5
        else:
            u_initial = np.mean(u[:30]) if len(u) > 30 else np.mean(u[:min(10, len(u))])
            u_final = np.mean(u[-30:]) if len(u) > 30 else np.mean(u[-min(10, len(u)):])
            delta_u = abs(u_final - u_initial)
            delta_y = abs(y_final - y0)
            gain_guess = (delta_y / delta_u) if delta_u > 1e-6 else 0.5

        gain_guess = max(gain_guess, 0.01)

        du = np.abs(np.diff(u))
        if len(du) > 0 and np.max(du) > 0:
            step_idx = np.argmax(du)
        else:
            step_idx = 0

        if step_idx < len(y) - 10:
            peak_idx = np.argmax(y[step_idx:]) + step_idx
            t_peak = t[peak_idx] - t[step_idx]
            T_eq_guess = max(t_peak * 0.6, 2.0)
            T1_guess = T_eq_guess * 0.6
            T2_guess = T_eq_guess * 0.4
        else:
            T1_guess = 20.0
            T2_guess = 10.0

        initial_guess = [gain_guess, T1_guess, T2_guess]
        bounds = ([0.001, 0.1, 0.1], [10.0, 500.0, 500.0])

        print(f"纯二阶模型初始猜测: K={gain_guess:.3f}, T1={T1_guess:.2f}, T2={T2_guess:.2f}")

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'SO'),
                bounds=bounds,
                verbose=0,
                max_nfev=3000,
                ftol=1e-10,
                xtol=1e-10,
                loss='soft_l1'
            )
            K, T1, T2 = result.x
            print(f"纯二阶模型辨识结果: K={K:.3f}, T1={T1:.2f}, T2={T2:.2f}")
            print(f"优化迭代次数: {result.nfev}, 优化成功: {result.success}, 最终残差: {result.cost:.6f}")
        except Exception as e:
            print(f"纯二阶模型参数辨识失败：{e}，使用初始猜测值")
            K, T1, T2 = initial_guess

        # K = max(K, 0.001)
        # T1 = max(T1, 0.1)
        # T2 = max(T2, 0.1)
        K = np.clip(K, 0.05, 1.5)
        T1 = np.clip(T1, 5.0, 150.0)
        T2 = np.clip(T2, 5.0, 150.0)
        return K, T1, T2

    @staticmethod
    def identify_second_order_integrator(t, y, u):
        """用最小二乘法辨识二阶积分模型参数（K, T1, T2）

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列

        Returns:
            tuple: (K, T1, T2) 三个参数
        """
        # y0：使用该段起始的均值
        y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])

        # 二阶积分模型特征：输出随时间二次积分增长
        # 估算增益：基于输出的二阶导数
        dy = np.diff(y)
        dt_arr = np.diff(t)
        dy_dt = dy / dt_arr if len(dt_arr) > 0 else np.zeros_like(dy)

        # 使用中间段数据估算参数
        mid_start = len(y) // 3
        mid_end = 2 * len(y) // 3
        u_mid = np.mean(u[mid_start:mid_end])
        dy_dt_mid = np.mean(dy_dt[mid_start:mid_end]) if len(dy_dt) > mid_end else 0.0

        # K 估算：基于输出变化率
        if abs(u_mid) > 1e-6:
            K_guess = abs(dy_dt_mid * 20.0 / u_mid)  # 二阶积分需要更大的系数
        else:
            K_guess = 0.1

        K_guess = max(K_guess, 0.01)

        # 初始猜测与参数边界
        initial_guess = [K_guess, 15.0, 10.0]  # K, T1, T2
        bounds = ([0.001, 0.1, 0.1], [10.0, 500.0, 500.0])

        try:
            result = least_squares(
                SystemIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, 'SO_INTEGRATOR'),
                bounds=bounds,
                verbose=0
            )
            K, T1, T2 = result.x
        except Exception as e:
            print(f"二阶积分模型参数辨识失败：{e}，使用初始猜测值")
            K, T1, T2 = initial_guess

        # 确保参数为正值
        K = np.clip(K, 0.05, 1.5)
        T1 = np.clip(T1, 5.0, 150.0)
        T2 = np.clip(T2, 5.0, 150.0)

        return K, T1, T2

    @staticmethod
    def identify(t, y, u, model_type='FOPDT', transient_mode=False):
        """
        统一的系统辨识接口，根据模型类型自动调用相应的辨识方法

        Args:
            t: 时间序列
            y: 输出响应序列
            u: 输入信号序列
            model_type: 模型类型，可以是ModelType枚举或字符串
            transient_mode: 是否使用瞬态模式（仅对FOPDT有效）
                          - False: 稳态模式，适合末段已稳定的数据
                          - True: 瞬态模式，适合MV有激励但未达稳态的异常段数据

        Returns:
            tuple: 根据模型类型返回不同数量的参数
        """
        # 如果是枚举类型，转换为字符串值
        if isinstance(model_type, ModelType):
            model_type = model_type.value
        K,T1,T2,L=0.0,0.0,0.0,0.0
        if model_type == 'FOPDT':
            # FOPDT模型辨识：返回 K, T, L
            K, T1, L = SystemIdentifier.identify_fopdt(t, y, u, transient_mode=transient_mode)
            return K,T1,T2,L
        elif model_type == 'FO':
            # 一阶模型辨识：返回 K, T，并将 L 设为 0.0
            K, T1 = SystemIdentifier.identify_first_order(t, y, u)
            return K,T1,T2,L
        elif model_type == 'SOPDT':
            # 二阶模型辨识：返回 K, T1, T2, L
            K, T1, T2, L = SystemIdentifier.identify_second_order(t, y, u, transient_mode=transient_mode)
            return K, T1, T2, L
        elif model_type == 'SO':
            # 纯二阶模型辨识（无滞后）：返回 K, T1, T2
            K, T1, T2 = SystemIdentifier.identify_second_order_no_delay(t, y, u, transient_mode=transient_mode)
            return K,T1,T2,L
        elif model_type == 'FO_INTEGRATOR':
            # 积分模型辨识：返回 K, T
            K, T1 = SystemIdentifier.identify_first_order_integrator(t, y, u)
            return K,T1,T2,L
        elif model_type == 'SO_INTEGRATOR':
            # 二阶积分模型辨识：返回 K, T1, T2
            K, T1, T2 = SystemIdentifier.identify_second_order_integrator(t, y, u)
            return K,T1,T2,L
        else:
            raise ValueError(f"不支持的模型类型: {model_type}，请使用 'FOPDT'、'FO'、'SOPDT'、'SO'、'FO_INTEGRATOR' 或 'SO_INTEGRATOR'")

    @staticmethod
    def lambda_tuning(K, T, L, lambda_val=None, mode="standard"):
        """基于Lambda方法整定PID参数，根据模式调整参数"""
        if lambda_val is None:
            lambda_val = T * 0.8

        denominator = K * (lambda_val + L / 2)
        if denominator < 1e-6:
            return 1.0, 20.0, 1.0  # 异常时返回默认安全值

        # pid参数计算
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > 1e-6 else 0.0

        # 根据模式调整参数
        if mode == "anti_disturbance":
            # 抗扰动模式：降低比例增益和微分增益，增加积分时间
            Kp *= 0.8
            Ti *= 1.2
            Td *= 0.7
        elif mode == "anti_noise":
            # 抗噪声模式：降低比例增益和微分增益，增加积分时间
            Kp *= 0.7
            Ti *= 1.3
            Td *= 0.5
        elif mode == "flow_control":
            # 流量控制模式：降低比例增益，增加积分时间，关闭微分
            Kp *= 0.6
            Ti *= 1.5
            Td = 0.0

        # 仅确保参数为正值，不做严格限制
        Kp = max(Kp, 0.01)
        Ti = max(Ti, 0.1)
        Td = max(Td, 0.0)
        return Kp, Ti, Td

    @staticmethod
    def lambda_tuning_for_flow(*params, model_type='FOPDT', lambda_val=None, mode=None):
        """
        针对流量控制的 PID 整定，支持多种模型类型

        Args:
            *params: 模型参数，根据model_type不同而不同
                - FOPDT: K, T, L
                - FO: K, T, L (L可为0)
                - SOPDT: K, T1, T2, L
                - SO: K, T1, T2
                - FO_INTEGRATOR: K, T
                - SO_INTEGRATOR: K, T1, T2
            model_type: 模型类型，可以是ModelType枚举或字符串
            lambda_val: Lambda参数，默认为 None 时自动计算
            mode: 控制模式，'flow_control' 为流量控制模式

        Returns:
            tuple: (Kp, Ti, Td) PID参数
        """
        # 如果是枚举类型，转换为字符串值
        if isinstance(model_type, ModelType):
            model_type = model_type.value

        # 根据模型类型解析参数
        if model_type == 'FOPDT' or model_type == 'FO':
            # FOPDT 或一阶模型: K, T, L
            if len(params) >= 3:
                K, T, L = params[0], params[1], params[2]
            elif len(params) == 2:
                K, T = params[0], params[1]
                L = 0.0
            else:
                raise ValueError(f"{model_type}模型需要至少传入2个参数 (K, T)")

            # 流量系统通常 L 很小，强制设为 0 避免过度保守
            # L = 0.0

            if lambda_val is None:
                # Lambda 选择：快响应，取较小值（如 T/3 ~ T/2）
                lambda_val = max(T * 0.4, 0.1)

            # 分母保护
            denominator = K * (lambda_val + L / 2)
            if denominator < 1e-6:
                return 1.0, 20.0, 0.0

            # 标准 Lambda 公式
            Kp = (T + L / 2) / denominator
            Ti = T + L / 2
            Td = (T * L) / (2 * T + L) if (2 * T + L) > 1e-6 else 0.0

        elif model_type == 'SOPDT' or model_type == 'SO':
            # 二阶模型: SOPDT(K, T1, T2, L) 或 SO(K, T1, T2)
            if model_type == 'SOPDT':
                if len(params) >= 4:
                    K, T1, T2, L = params[0], params[1], params[2], params[3]
                else:
                    raise ValueError(f"SOPDT模型需要传入4个参数 (K, T1, T2, L)")
            else:
                if len(params) >= 3:
                    K, T1, T2 = params[0], params[1], params[2]
                    L = 0.0
                else:
                    raise ValueError(f"SO模型需要传入3个参数 (K, T1, T2)")

            # 流量系统强制设 L = 0
            L = 0.0

            # 二阶系统的等效时间常数
            T_eq = T1 + T2

            if lambda_val is None:
                lambda_val = max(T_eq * 0.4, 0.1)

            # 分母保护
            denominator = K * lambda_val
            if denominator < 1e-6:
                return 1.0, 20.0, 0.0

            # 二阶系统 Lambda 公式
            Kp = T_eq / denominator
            Ti = T_eq
            Td = (T1 * T2) / T_eq if T_eq > 1e-6 else 0.0

        elif model_type == 'FO_INTEGRATOR':
            # 积分模型: K, T
            if len(params) >= 2:
                K, T = params[0], params[1]
            else:
                raise ValueError(f"FO_INTEGRATOR模型需要传入2个参数 (K, T)")

            if lambda_val is None:
                # 积分系统建议使用较大的 lambda
                lambda_val = max(T * 0.8, 0.2)

            # 分母保护
            if K < 1e-6:
                return 1.0, 20.0, 0.0

            # 积分系统的 Lambda 公式
            # 对于 G(s) = K/(s(Ts+1))，PI控制器
            Kp = T / (K * lambda_val)
            Ti = T
            Td = 0.0  # 积分系统不使用微分

        elif model_type == 'SO_INTEGRATOR':
            # 二阶积分模型: K, T1, T2
            if len(params) >= 3:
                K, T1, T2 = params[0], params[1], params[2]
            else:
                raise ValueError(f"SO_INTEGRATOR模型需要传入3个参数 (K, T1, T2)")

            if lambda_val is None:
                # 二阶积分系统需要更大的 lambda
                T_eq = T1 + T2
                lambda_val = max(T_eq * 1.0, 0.5)

            # 分母保护
            if K < 1e-6:
                return 1.0, 20.0, 0.0

            # 二阶积分系统的 Lambda 公式
            # 对于 G(s) = K/(s^2(T1*s+1)(T2*s+1))，PI控制器
            T_eq = T1 + T2
            Kp = T_eq / (K * lambda_val)
            Ti = T_eq
            Td = 0.0  # 积分系统不使用微分

        else:
            raise ValueError(f"不支持的模型类型: {model_type}")

        # 针对流量的特殊调整
        if mode == "flow_control":
            # 1. 降低 Kp 避免超调（流量易振荡）
            Kp *= 0.6
            # 2. 增大 Ti（减弱积分，防阀门频繁动作）
            Ti *= 1.5
            # 3. 微分通常关闭或极小（流量噪声大）
            Td = 0.0

        # 确保参数为正值
        # Kp = max(Kp, 0.01)
        # Ti = max(Ti, 0.1)
        # Td = max(Td, 0.0)
        Kp = np.clip(Kp, 0.5, 6.0)
        Ti = np.clip(Ti, 8.0, 120.0)
        Td = np.clip(Td, 0.0, 25.0)
        return Kp, Ti, Td

    @staticmethod
    def detect_step_response_in_window(t_window: np.ndarray,
                                      y_window: np.ndarray,
                                      u_window: np.ndarray,
                                      step_threshold: float = 0.05,
                                      response_ratio: float = 0.1) -> Dict:
        """
        在时间窗口内检测阶跃响应

        Args:
            t_window: 时间数组（秒）
            y_window: 输出响应数组
            u_window: 输入信号数组
            step_threshold: 阶跃检测阈值（占输入范围的百分比）
            response_ratio: 最小响应比例（响应幅值 / 输入变化）

        Returns:
            {
                'has_step': bool,              # 是否检测到阶跃
                'step_idx': int,               # 阶跃点索引
                'step_size': float,            # 阶跃大小
                'response_magnitude': float,   # 响应幅值
                'response_ratio': float,       # 响应比例
                'rise_time': float,            # 上升时间（秒）
                'settling_time': float,        # 稳定时间（秒）
                'confidence': float            # 置信度 0-1
            }
        """
        result = {
            'has_step': False,
            'step_idx': 0,
            'step_size': 0.0,
            'response_magnitude': 0.0,
            'response_ratio': 0.0,
            'rise_time': 0.0,
            'settling_time': 0.0,
            'confidence': 0.0
        }

        if len(t_window) < 10 or len(u_window) < 10 or len(y_window) < 10:
            return result

        # 1. 检测输入阶跃点
        du = np.abs(np.diff(u_window))
        u_range = np.max(u_window) - np.min(u_window)
        step_threshold_abs = u_range * step_threshold if u_range > 1e-6 else 0.05

        if np.max(du) < step_threshold_abs:
            return result  # 无明显阶跃

        step_idx = int(np.argmax(du))
        step_size = du[step_idx]
        result['step_idx'] = step_idx
        result['step_size'] = float(step_size)

        # 2. 计算响应幅值
        y_before = np.mean(y_window[:max(1, step_idx)])
        y_after = np.mean(y_window[step_idx:])
        response_magnitude = abs(y_after - y_before)
        result['response_magnitude'] = float(response_magnitude)

        # 3. 计算响应比例
        if step_size > 1e-6:
            response_ratio_calc = response_magnitude / step_size
        else:
            response_ratio_calc = 0.0
        result['response_ratio'] = float(response_ratio_calc)

        # 4. 判断响应幅值是否合理
        if response_magnitude < 1e-6 or response_ratio_calc < response_ratio:
            return result  # 响应不足

        result['has_step'] = True

        # 5. 计算上升时间（10% - 90%）
        response_start = y_before
        response_end = y_after
        response_range = response_end - response_start

        # 避免0除错误
        if abs(response_range) < 1e-6:
            rise_time = 0.0
        else:
            threshold_10 = response_start + 0.1 * response_range
            threshold_90 = response_start + 0.9 * response_range

            indices_10 = np.where(np.abs(y_window[step_idx:] - threshold_10) < abs(response_range) * 0.05)[0]
            indices_90 = np.where(np.abs(y_window[step_idx:] - threshold_90) < abs(response_range) * 0.05)[0]

            if len(indices_10) > 0 and len(indices_90) > 0:
                t_10_idx = step_idx + indices_10[0]
                t_90_idx = step_idx + indices_90[-1]
                rise_time = float(t_window[t_90_idx] - t_window[t_10_idx])
            else:
                rise_time = float(t_window[-1] - t_window[step_idx])
        result['rise_time'] = rise_time

        # 6. 计算稳定时间（进入并保持在稳态值±2%）
        steady_threshold = abs(response_range) * 0.02 if abs(response_range) > 1e-6 else 1e-6
        steady_region = np.where(np.abs(y_window[step_idx:] - response_end) < steady_threshold)[0]

        if len(steady_region) > 0:
            # 找到第一个进入稳态的点
            settling_idx = step_idx + steady_region[0]
            settling_time = float(t_window[settling_idx] - t_window[step_idx])
        else:
            settling_time = float(t_window[-1] - t_window[step_idx])
        result['settling_time'] = settling_time

        # 7. 计算置信度评分
        confidence = 0.5  # 基础分

        # 响应充分性（最高+0.2）
        if response_ratio_calc >= response_ratio * 5:
            confidence += 0.2
        elif response_ratio_calc >= response_ratio * 2:
            confidence += 0.15
        elif response_ratio_calc >= response_ratio:
            confidence += 0.1

        # 响应平滑性（最高+0.15）
        y_post_step = y_window[step_idx:]
        if len(y_post_step) > 2:
            d2y = np.diff(np.diff(y_post_step))
            smoothness = 1.0 / (1.0 + np.std(d2y) / (np.std(y_post_step) + 1e-6))
            confidence += min(0.15, smoothness * 0.15)

        # 稳定速度（最高+0.15）
        if settling_time > 0:
            time_ratio = settling_time / (t_window[-1] - t_window[step_idx])
            if time_ratio < 0.3:
                confidence += 0.15
            elif time_ratio < 0.5:
                confidence += 0.1
            elif time_ratio < 0.7:
                confidence += 0.05

        result['confidence'] = min(1.0, confidence)

        return result

    @staticmethod
    def auto_select_time_windows(history_data: List[Dict],
                                window_size: int = 120,  # 分钟
                                step_size: int = 10,      # 分钟
                                min_response_ratio: float = 0.1,
                                step_threshold: float = 0.05,
                                confidence_min: float = 0.5) -> Dict:
        """
        自动筛选适合参数辨识的时间区间

        综合判断：
        1. 输入信号有明显变化（阶跃）
        2. 输出响应幅值合理
        3. 响应曲线特征完整（上升+稳定）
        4. 置信度达到要求

        Args:
            history_data: 历史数据列表，每条记录包含 timestamp, pv, mv, sv
            window_size: 窗口大小（分钟）
            step_size: 滑动步长（分钟）
            min_response_ratio: 最小响应比例（响应幅值 / 输入变化）
            step_threshold: 阶跃检测阈值（占输入范围的百分比）
            confidence_min: 最小置信度要求

        Returns:
            {
                'status': 'success',
                'total_windows': int,
                'qualified_windows': List[{
                    'start_time': int,          # 毫秒时间戳
                    'end_time': int,
                    'start_idx': int,
                    'end_idx': int,
                    'step_detected': bool,
                    'step_idx': int,
                    'response_magnitude': float,
                    'response_ratio': float,
                    'rise_time': float,
                    'settling_time': float,
                    'confidence': float,
                    'recommendation': str      # "优秀" / "良好" / "可接受" / "不推荐"
                }],
                'analysis_summary': {
                    'total_examined': int,
                    'with_step_response': int,
                    'high_confidence': int,
                    'optimal_window': Dict   # 最优推荐窗口
                }
            }
        """

        if not history_data or len(history_data) < 10:
            return {
                'status': 'error',
                'message': '数据不足，至少需要10条记录',
                'total_windows': 0,
                'qualified_windows': []
            }

        # 1. 数据预处理
        try:
            timestamps = np.array([r.get('timestamp', 0) for r in history_data])
            pv_data = np.array([r.get('pv', 0) for r in history_data])
            mv_data = np.array([r.get('mv', 0) for r in history_data])
            sv_data = np.array([r.get('sv', 0) for r in history_data])

            # 转换时间为秒
            t_sec = (timestamps - timestamps[0]) / 1000.0

        except Exception as e:
            return {
                'status': 'error',
                'message': f'数据解析失败: {str(e)}',
                'total_windows': 0,
                'qualified_windows': []
            }

        # 2. 生成窗口索引
        window_size_sec = window_size * 60
        step_size_sec = step_size * 60

        # 计算采样间隔
        dt = 1.0
        if len(t_sec) > 1:
            dt = t_sec[1] - t_sec[0]

        windows = []
        window_size_points = int(window_size_sec / dt) if dt > 0 else 120
        step_size_points = int(step_size_sec / dt) if dt > 0 else 10

        for i in range(0, len(t_sec) - window_size_points, max(1, step_size_points)):
            window_end_idx = min(i + window_size_points, len(t_sec) - 1)
            if window_end_idx - i < 20:  # 窗口太小跳过
                continue

            windows.append({
                'start_idx': i,
                'end_idx': window_end_idx,
                'start_time': int(timestamps[i]),
                'end_time': int(timestamps[window_end_idx])
            })

        # 3. 逐窗口分析
        qualified_windows = []
        step_response_count = 0
        high_conf_count = 0

        for win in windows:
            start_idx = win['start_idx']
            end_idx = win['end_idx']

            t_win = t_sec[start_idx:end_idx+1]
            y_win = pv_data[start_idx:end_idx+1]
            u_win = mv_data[start_idx:end_idx+1]

            # 4. 检测阶跃响应
            step_result = SystemIdentifier.detect_step_response_in_window(
                t_window=t_win,
                y_window=y_win,
                u_window=u_win,
                step_threshold=step_threshold,
                response_ratio=min_response_ratio
            )

            if step_result['has_step'] and step_result['confidence'] >= confidence_min:
                step_response_count += 1

                # 5. 生成推荐等级
                confidence = step_result['confidence']
                if confidence >= 0.85:
                    recommendation = "优秀"
                elif confidence >= 0.70:
                    recommendation = "良好"
                elif confidence >= 0.50:
                    recommendation = "可接受"
                else:
                    recommendation = "不推荐"

                if confidence >= 0.70:
                    high_conf_count += 1

                qualified_window = {
                    **win,
                    'step_detected': step_result['has_step'],
                    'step_idx': step_result['step_idx'],
                    'response_magnitude': step_result['response_magnitude'],
                    'response_ratio': step_result['response_ratio'],
                    'rise_time': step_result['rise_time'],
                    'settling_time': step_result['settling_time'],
                    'confidence': step_result['confidence'],
                    'recommendation': recommendation
                }

                qualified_windows.append(qualified_window)

        # 6. 选择最优窗口（置信度最高）
        optimal_window = None
        if qualified_windows:
            optimal_window = max(qualified_windows, key=lambda x: x['confidence'])

        return {
            'status': 'success',
            'total_windows': len(windows),
            'qualified_windows': qualified_windows,
            'analysis_summary': {
                'total_examined': len(windows),
                'with_step_response': step_response_count,
                'high_confidence': high_conf_count,
                'optimal_window': optimal_window
            }
        }


# ==============================
# 8. 状态分析模块
# ==============================
class StateAnalyzer:
    """系统状态分析工具：判断稳定性与扰动"""

    def __init__(self, mode="standard"):
        self.mode = mode

    def is_stable(self, temp_data, setpoint):
        """判断系统是否稳定在目标温度附近"""
        if len(temp_data) < Config.STABILIZATION_WINDOW:
            return False
        recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])

        # 根据模式调整稳定阈值
        if self.mode == "anti_disturbance":
            threshold = Config.STABILIZATION_THRESHOLD * 1.2  # 放宽稳定阈值
        elif self.mode == "anti_noise":
            threshold = Config.STABILIZATION_THRESHOLD * 1.1  # 略微放宽稳定阈值
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

    def detect_instability_optimized(self, temp_data, setpoint, valve_data, time_data):
        """优化的扰动检测算法 - 增强对轻微扰动的检测能力"""
        if len(temp_data) < Config.DETECTION_WINDOW:
            return False, ""

        # 获取当前窗口的数据
        recent_temps = np.array(temp_data[-Config.DETECTION_WINDOW:])
        recent_valves = np.array(valve_data[-Config.DETECTION_WINDOW:])
        recent_times = np.array(time_data[-Config.DETECTION_WINDOW:])

        # 计算误差
        errors = recent_temps - setpoint

        # 1. 误差统计特征
        mean_error = np.mean(errors)
        std_error = np.std(errors)
        max_error = np.max(np.abs(errors))

        # 2. 温度变化率检测
        temp_deriv = np.diff(recent_temps)
        mean_abs_deriv = np.mean(np.abs(temp_deriv))

        # 3. 阀门动作检测
        valve_changes = np.diff(recent_valves)
        valve_activity = np.sum(np.abs(valve_changes))

        # 4. 温度波动性检测(标准差)
        temp_std = np.std(recent_temps)

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

        # 8. 根据模式调整检测阈值
        error_threshold = Config.ERROR_THRESHOLD
        std_threshold = Config.STD_THRESHOLD
        slope_threshold = Config.SLOPE_THRESHOLD
        valve_change_threshold = Config.VALVE_CHANGE_THRESHOLD

        if self.mode == "anti_disturbance":
            # 抗扰动模式：降低检测灵敏度，避免误判
            error_threshold *= 1.5
            std_threshold *= 1.4
            slope_threshold *= 1.3
            valve_change_threshold *= 1.5
        elif self.mode == "anti_noise":
            # 抗噪声模式：降低检测灵敏度，避免噪声误判
            error_threshold *= 1.8
            std_threshold *= 1.6
            slope_threshold *= 1.5
            valve_change_threshold *= 1.8

        # 9. 综合判断
        is_disturbance = False
        disturbance_type = ""

        # 超调检测
        if max_error > error_threshold * 0.7 and mean_error > 0.8 and std_error > 0.4:
            is_disturbance = True
            disturbance_type = f"超调量大({max_error:.1f}℃)"

        # 稳态误差检测
        elif abs(mean_error) > 1.0 and std_error < 0.8:
            is_disturbance = True
            disturbance_type = f"稳态误差({mean_error:.1f}℃)"

        # 系统振荡检测
        elif std_error > std_threshold * 0.8 and mean_abs_deriv > slope_threshold * 0.7:
            is_disturbance = True
            disturbance_type = f"系统振荡(σ={std_error:.2f})"

        # 阀门过度动作检测
        elif valve_activity > valve_change_threshold * 0.6 and std_error > 0.5:
            is_disturbance = True
            disturbance_type = f"控制不稳定(阀门动作={valve_activity:.1f})"

        # 趋势性变化检测
        elif trend_slope > slope_threshold * 0.6 and std_error > 0.4:
            is_disturbance = True
            disturbance_type = f"趋势性偏离(斜率={trend_slope:.3f})"

        # 阀门振荡检测（针对轻微扰动）
        elif valve_oscillation > 2.0 and std_error > 0.3:
            is_disturbance = True
            disturbance_type = f"阀门振荡({valve_oscillation:.2f})"

        # 温度模式变化检测
        elif temp_pattern_change > 0.5:
            is_disturbance = True
            disturbance_type = f"温度模式变化({temp_pattern_change:.2f})"

        # 传感器漂移或控制阀磨损等轻微扰动的检测
        elif std_error > 0.4 and valve_oscillation > 1.5:
            is_disturbance = True
            disturbance_type = f"系统参数漂移(σ={std_error:.2f}, 阀门={valve_oscillation:.2f})"

        return is_disturbance, disturbance_type


# ==============================
# 9. 可视化模块
# ==============================
class Visualizer:
    """可视化工具：初始化图表、更新绘图与参数显示"""

    def __init__(self):
        # 确保中文显示
        plt.rcParams["font.family"] = ["Heiti TC"]
        plt.rcParams['axes.unicode_minus'] = False
        self.fig = None
        self.plot_data = None

    def init_real_time_fig(self, t, u, setpoint, system_params, pid_params, response_data, true_params, disturbances,
                           pid_mode, system_mode):
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
            f'系统响应与辨识模型对比 (PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]})')
        ax1.set_xlabel('时间 (s)')
        ax1.set_ylabel('温度 (℃)')
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # 3. 温度控制曲线（含扰动标记）
        ax2 = self.fig.add_subplot(gs[1:3, :])
        ax2.set_xlim(0, t[-1] * 1.2)
        ax2.set_ylim(Config.INIT_TEMPERATURE - 15, setpoint + 25)
        ax2.axhline(setpoint, color='r', linestyle='--', label='设定值', linewidth=1.5)
        ax2.axhline(Config.INIT_TEMPERATURE, color='orange', linestyle='-.',
                    label=f'初始温度 {Config.INIT_TEMPERATURE}℃', linewidth=1.5)

        # 扰动标记
        disturbance_colors = {
            "overshoot": "red",
            "steady_error": "orange",
            "slow_recovery": "brown",
            "valve_stiction": "purple",
            "sensor_drift": "pink",
            "heat_loss": "gray",
            "control_valve_wear": "olive",
            "thermal_inertia": "cyan"
        }
        for d in disturbances:
            ax2.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]],
                        alpha=0.2, label=f'{d["description"]} ({d["time"]}s)')

        ax2.set_title(
            f'温度控制曲线（含扰动与参数更新 - PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]}）')
        ax2.set_xlabel('时间 (s)')
        ax2.set_ylabel('温度 (℃)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)

        # 创建真实仿真温度数据（无控制器影响的系统自然响应）
        # 这里使用与实际系统相同的输入信号，但不考虑反馈控制
        true_system = TemperatureSystem(**true_params, mode=system_mode)
        true_temp_data = []
        for i, time in enumerate(t):
            # 使用实际的输入信号来模拟无控制器时的系统响应
            valve = u[i]  # 使用实际的输入信号
            temp = true_system.update(valve, time, disturbances=disturbances)
            true_temp_data.append(temp)
        # print(f"真是仿真温度曲线:{true_temp_data}")
        # 绘制真实仿真温度曲线
        true_temp_line, = ax2.plot(t, true_temp_data, 'c--', label='真实仿真温度（无控制）', linewidth=1.5, alpha=0.7)
        temp_line, = ax2.plot([], [], 'b-', label='实际响应温度（有控制）', linewidth=1.5)
        stabilization_line = ax2.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
        update_lines = []  # 参数更新线
        update_marker, = ax2.plot([], [], 'bo', markersize=6, label='参数更新点')

        # 4. 阀门开度曲线
        ax3 = self.fig.add_subplot(gs[3, 0])
        ax3.set_xlim(0, t[-1] * 1.2)
        ax3.set_ylim(0, 100)
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
        ax4.set_xlim(0, t[-1] * 1.2)
        ax4.set_ylim(-15, 15)
        ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
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
        ax5.set_xlim(0, t[-1] * 1.2)
        ax5.set_ylim(0, 6)
        for d in disturbances:
            ax5.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)
        ax5.set_title(f'PID参数变化趋势 (PID模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]})')
        ax5.set_xlabel('时间 (s)')
        ax5.set_ylabel('参数值（Ti/10，Td*2）')
        ax5.grid(True, alpha=0.3)
        kp_line, = ax5.plot([], [], 'r-', label='Kp', linewidth=1.5)
        ti_line, = ax5.plot([], [], 'g-', label='Ti/10', linewidth=1.5)
        td_line, = ax5.plot([], [], 'b-', label='Td*2', linewidth=1.5)
        ax5.legend()

        # 7. 参数文本显示
        ax6 = self.fig.add_subplot(gs[5, :])
        ax6.axis('off')
        params_text = ax6.text(0.05, 0.5, "", fontsize=10,
                               verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
        self.update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'],
                                pid_mode=pid_mode, system_mode=system_mode)

        # Lambda参数滑块
        plt.subplots_adjust(bottom=0.15)
        ax_slider = plt.axes([0.2, 0.05, 0.65, 0.03])
        lambda_slider = Slider(
            ax=ax_slider,
            label='Lambda 参数（减小→响应更快）',
            valmin=0.3 * system_params['T'],
            valmax=2 * system_params['T'],
            valinit=system_params['T'] * 0.6
        )

        plt.ion()
        plt.tight_layout(rect=[0, 0.1, 1, 1])
        plt.show(block=False)

        self.plot_data = {
            'axes': (ax2, ax3, ax4, ax5),
            'lines': (true_temp_line, temp_line, valve_line, error_line, kp_line, ti_line, td_line),
            'text': params_text,
            'slider': lambda_slider,
            'markers': (stabilization_line, update_lines, update_marker),
            'colors': disturbance_colors
        }
        return self.fig, self.plot_data

    @staticmethod
    def update_params_text(text_obj, system_params, pid_params, lambda_val, update_count=0, initial_params=None,
                           pid_mode="standard", system_mode="standard"):
        """更新参数显示文本"""
        K, T, L = system_params['K'], system_params['T'], system_params['L']
        Kp, Ti, Td = pid_params['Kp'], pid_params['Ti'], pid_params['Td']
        status = f"（已更新{update_count}次）" if update_count > 0 else ""

        # 初始参数对比
        initial_text = ""
        if initial_params and update_count > 0:
            init_Kp, init_Ti, init_Td = initial_params
            initial_text = f"""初始有效参数:
    Kp = {init_Kp:.2f}, Ti = {init_Ti:.1f}s, Td = {init_Td:.1f}s
    """

        text = f"""系统辨识参数:
    增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s

{initial_text}当前PID参数 {status}(λ={lambda_val:.1f}, PID模式:{Config.PID_MODES[pid_mode]}, 系统模式:{Config.MODES[system_mode]}):
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

目标温度: {Config.TARGET_TEMPERATURE}℃ | 初始温度: {Config.INIT_TEMPERATURE}℃"""
        text_obj.set_text(text)

    def update_plots(self, time_data, temp_data, true_temp_data, valve_data, error_data, kp_data, ti_data, td_data,
                     update_lines):
        """实时更新绘图数据"""
        # 类型安全检查：确保 plot_data 已初始化且包含必要的键
        if not isinstance(self.plot_data, dict):
            return

        if 'lines' not in self.plot_data or 'axes' not in self.plot_data or 'markers' not in self.plot_data:
            return

        lines = self.plot_data.get('lines')
        axes = self.plot_data.get('axes')
        markers = self.plot_data.get('markers')

        if lines is None or axes is None or markers is None:
            return

        (true_temp_line, temp_line, valve_line, error_line, kp_line, ti_line, td_line) = lines
        (ax2, _, _, _) = axes
        _, _, update_marker = markers

        # 更新曲线数据
        temp_line.set_data(time_data, temp_data)
        true_temp_line.set_data(time_data, true_temp_data[-len(time_data):])  # 确保数据长度一致
        valve_line.set_data(time_data, valve_data)
        error_line.set_data(time_data, error_data)
        kp_line.set_data(time_data, kp_data)
        ti_line.set_data(time_data, ti_data)
        td_line.set_data(time_data, td_data)

        # 更新参数更新标记
        update_times = [line.get_xdata()[0] for line in update_lines]
        update_marker.set_data(update_times, [Config.TARGET_TEMPERATURE + 8] * len(update_times))

        # 更新标题
        current_time = time_data[-1] if time_data else 0
        ax2.set_title(f'温度控制曲线（当前时间：{current_time:.0f}s）')

        # 刷新画布
        if self.fig is not None and self.fig.canvas is not None:
            self.fig.canvas.draw_idle()
        plt.pause(0.01)


# ==============================
# 10. 扰动生成模块
# ==============================
class DisturbanceGenerator:
    """扰动生成器：生成各种系统扰动"""

    def __init__(self, mode="standard"):
        self.mode = mode

    @staticmethod
    def generate_random_disturbances():
        """生成随机扰动配置 - 考虑更多失效场景，每次最多4种"""
        # 随机选择扰动数量 (2-4个)
        num_disturbances = min(np.random.randint(3, 6), 4)  # 最多4种失效场景

        disturbances = []
        used_time_slots = []

        # 从所有可用的扰动类型中选择num_disturbances种
        available_types = Config.DISTURBANCE_TYPES.copy()
        selected_types = random.sample(available_types, k=num_disturbances)

        for i in range(num_disturbances):
            disturbance_type = selected_types[i]

            # 随机选择扰动时间（避开初始稳定期和结束期）
            time_start = np.random.randint(300, Config.SIMULATION_DURATION - 300)

            # 避免时间重叠 - 确保扰动之间有足够距离以恢复稳态
            min_separation = 600  # 最小间隔600秒，确保恢复稳态
            while any(abs(time_start - used_start) < min_separation for used_start in used_time_slots):
                time_start = np.random.randint(300, Config.SIMULATION_DURATION - 300)

            used_time_slots.append(time_start)

            # 随机生成扰动参数
            duration = np.random.randint(80, 250)  # 持续时间 80-250s
            amplitude = np.random.uniform(1.2, 4.0)  # 幅值 1.2-4.0℃

            disturbance = {
                "time": time_start,
                "type": disturbance_type["type"],
                "duration": duration,
                "amplitude": amplitude,
                "description": disturbance_type["description"]
            }
            disturbances.append(disturbance)

        # 按时间排序
        disturbances.sort(key=lambda x: x["time"])

        return disturbances


# ==============================
# 11. 主控制模块
# ==============================
class ControlMonitor:
    """控制监控主逻辑：协调系统、控制器、辨识器等模块运行"""

    def __init__(self):
        self.data_handler = DataHandler()
        self.visualizer = Visualizer()
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

        # 选择运行模式
        system_mode = self.data_handler.choose_mode()
        self.logger.info(f"选择系统运行模式: {Config.MODES[system_mode]}")

        # 选择降噪强度
        noise_reduction_level = self.data_handler.choose_noise_reduction_level()
        self.logger.info(f"选择降噪强度: {noise_reduction_level}")

        # 选择PID控制模式
        pid_mode = self.data_handler.choose_pid_mode()
        self.logger.info(f"选择PID控制模式: {Config.PID_MODES[pid_mode]}")

        # 初始化状态分析器
        state_analyzer = StateAnalyzer(mode=system_mode)
        self.disturbance_generator = DisturbanceGenerator(mode=system_mode)

        # 生成随机扰动
        self.logger.info("生成随机扰动配置...")
        disturbances=[]
        # disturbances = self.disturbance_generator.generate_random_disturbances()
        # self.logger.info(f"生成了 {len(disturbances)} 个随机扰动:")
        # for i, d in enumerate(disturbances):
        #     self.logger.info(
        #         f"  {i + 1}. {d['time']}s: {d['description']} (持续{d['duration']}s, 幅值{d['amplitude']:.1f}℃)")
        #     print(f"  {i + 1}. {d['time']}s: {d['description']} (持续{d['duration']}s, 幅值{d['amplitude']:.1f}℃)")

        # 选择数据来源
        t, response_data, u = self.data_handler.choose_data_source(data_type="dynamic_response")

        # 初始化系统与输入
        initial_true_params = {'K': 0.8, 'T': 30, 'L': 4, 'noise_level': 0.3}
        temp_system = TemperatureSystem(**initial_true_params, mode=system_mode)

        # 生成仿真数据（如未提供）
        if response_data is None:
            u = temp_system.generate_non_step_input(t)
            response_data = temp_system.simulate_with_input(t, u, disturbances)
            # 应用低通滤波到仿真生成的数据
            response_data = self.data_handler.apply_low_pass_filter(response_data)
            self.logger.info(
                f"对仿真生成的温度数据应用了低通滤波 (降噪强度: {noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]['cutoff_freq']})")

            # 如果需要对输入信号也应用滤波
            if Config.FILTER_APPLY_TO_INPUT:
                u = self.data_handler.apply_low_pass_filter(u)
                self.logger.info(
                    f"对仿真生成的输入信号应用了低通滤波 (降噪强度: {noise_reduction_level}, 截止频率: {Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]['cutoff_freq']})")

            # 保存生成的数据
            save_path = os.path.join(Config.DATA_SAVE_DIR, "dynamic_response_data.csv")
            pd.DataFrame({
                "时间(s)": t,
                "输入信号(%)": u,
                "动态响应温度(℃)": response_data
            }).to_csv(save_path, index=False)
            self.logger.info(f"生成非阶跃数据并保存至：{save_path}")
        elif u is None:  # 如果读取数据但没有输入信号，则生成默认输入信号
            u = temp_system.generate_non_step_input(t)

        # 初始参数辨识
        print(f"\n全局初始温度：{Config.INIT_TEMPERATURE}℃ | 目标温度：{Config.TARGET_TEMPERATURE}℃")
        print("正在辨识系统初始参数（K, T, L）...")
        K, T, L = self.identifier.identify_fopdt(t, response_data, u)
        identified_params = {'K': K, 'T': T, 'L': L}

        # 启动实时监控
        print(f"\n启动温度控制监控 (系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]})...")
        self._run_real_time_monitor(t, u, setpoint=Config.TARGET_TEMPERATURE, true_params=initial_true_params,
                                    identified_params=identified_params, response_data=response_data,
                                    disturbances=disturbances, start_time=start_time, pid_mode=pid_mode,
                                    system_mode=system_mode, state_analyzer=state_analyzer)

    def _run_real_time_monitor(self, t, u, setpoint, true_params, identified_params, response_data, disturbances,
                               start_time, pid_mode, system_mode, state_analyzer):
        """实时监控主循环"""
        # 初始化图表
        fig, plot_data = self.visualizer.init_real_time_fig(t, u, setpoint, identified_params,
                                                            {'Kp': 0, 'Ti': 0, 'Td': 0}, response_data, true_params,
                                                            disturbances, pid_mode, system_mode)
        (ax2, _, _, _) = plot_data['axes']
        params_text = plot_data['text']
        lambda_slider = plot_data['slider']
        stabilization_line, update_lines, _ = plot_data['markers']
        true_temp_line, temp_line, valve_line, error_line, kp_line, ti_line, td_line = plot_data['lines']

        # 数据存储列表
        time_data = []
        temp_data = []
        true_temp_data = []
        valve_data = []
        error_data = []
        kp_data = []
        ti_data = []
        td_data = []

        # 初始化系统与控制器
        K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
        init_Kp, init_Ti, init_Td = self.identifier.lambda_tuning(K, T, L, mode=system_mode)
        system = TemperatureSystem(**true_params, mode=system_mode)
        pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1, mode=pid_mode, system_mode=system_mode)
        current_temp = Config.INIT_TEMPERATURE

        # 初始化真实系统（用于模拟无控制器的自然响应）
        # 这里我们使用相同的输入信号来模拟无控制时的系统响应
        true_system = TemperatureSystem(**true_params, mode=system_mode)
        true_current_temp = Config.INIT_TEMPERATURE

        # 状态变量
        stabilization_time = None
        tuning_enabled = False
        params_update_count = 0
        initial_valid_params = None  # 初始有效参数记录
        recovery_status = {d["type"]: False for d in disturbances}

        # 为扰动添加更新标记属性
        for d in disturbances:
            d['updated'] = False  # 标记是否已更新参数

        # 打印初始信息
        print(f"\n" + "=" * 50)
        print(f"系统运行模式: {Config.MODES[system_mode]} | PID控制模式: {Config.PID_MODES[pid_mode]}")
        print("初始系统参数辨识结果：")
        print(f"静态增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s")
        print(f"初始PID参数：Kp={init_Kp:.2f}, Ti={init_Ti:.1f}s, Td={init_Td:.1f}s")
        print("\n随机扰动计划：")
        for d in disturbances:
            print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s，幅值{d['amplitude']:.1f}℃）")
        print("=" * 50 + "\n")

        # Lambda滑块回调
        def on_slider_change(val):
            nonlocal K, T, L
            new_Kp, new_Ti, new_Td = self.identifier.lambda_tuning(K, T, L, val, mode=system_mode)
            pid.set_target_params(new_Kp, new_Ti, new_Td)
            self.visualizer.update_params_text(params_text, identified_params,
                                               {'Kp': pid.target_Kp, 'Ti': pid.target_Ti, 'Td': pid.target_Td},
                                               val, params_update_count, initial_valid_params, pid_mode, system_mode)

        lambda_slider.on_changed(on_slider_change)

        # 新增：用于避免PID整定过程中重复识别扰动的标志
        in_pid_tuning_phase = False  # 标记是否正在PID参数整定阶段
        tuning_start_time = None  # 记录PID整定开始时间
        tuning_duration = 200  # PID整定阶段的持续时间（秒），避免在此期间重复检测扰动

        try:
            for i, time in enumerate(t):
                # 计算控制输出与当前温度
                valve_opening = pid.compute(setpoint, current_temp)
                current_temp = system.update(valve_opening, time, disturbances=disturbances)
                error = setpoint - current_temp

                # 计算真实系统温度（无控制器影响）
                # 这里使用实际的阀门信号来模拟无控制器时的系统响应
                true_current_temp = true_system.update(u[i], time, disturbances=disturbances)  # 使用原始输入信号

                # 记录数据
                time_data.append(time)
                temp_data.append(current_temp)
                true_temp_data.append(true_current_temp)
                valve_data.append(valve_opening)
                error_data.append(error)
                kp_data.append(pid.Kp)
                ti_data.append(pid.Ti / 10)  # 缩放显示
                td_data.append(pid.Td * 2)  # 缩放显示

                # 检测初始稳态（达到目标温度后开启整定）
                if stabilization_time is None and state_analyzer.is_stable(temp_data, setpoint):
                    stabilization_time = time
                    stabilization_line.set_xdata([time])
                    tuning_enabled = True
                    initial_valid_params = (pid.Kp, pid.Ti, pid.Td)  # 记录初始有效参数
                    print(f"✅ 系统达到初始稳态（{time:.0f}s），开启自整定功能")
                    print(
                        f"初始有效PID参数：Kp={initial_valid_params[0]:.2f}, Ti={initial_valid_params[1]:.1f}s, Td={initial_valid_params[2]:.1f}s")
                    self.visualizer.update_params_text(params_text, identified_params,
                                                       {'Kp': pid.Kp, 'Ti': pid.Ti, 'Td': pid.Td},
                                                       lambda_slider.val, params_update_count, initial_valid_params,
                                                       pid_mode, system_mode)

                # 自动扰动检测逻辑（仅在未处于PID整定阶段时执行）
                if tuning_enabled and not in_pid_tuning_phase:
                    # 使用优化的扰动检测算法
                    is_disturbance, disturbance_desc = state_analyzer.detect_instability_optimized(
                        temp_data, setpoint, valve_data, time_data
                    )

                    if is_disturbance:
                        # 检查当前时间是否在任何手动定义的扰动区间内
                        current_disturbance = next((d for d in disturbances
                                                    if d["time"] <= time < d["time"] + d["duration"]), None)
                        if current_disturbance:
                            # 扰动开始后20s内强制更新参数（避免初期波动误判）
                            if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:
                                print(f"\n检测到[{current_disturbance['description']}]，自动重新整定参数...")
                                self.logger.warning(
                                    f"检测到扰动[{current_disturbance['description']}]，开始自动重新整定参数...")

                                # 进入PID整定阶段，设置标志和时间
                                in_pid_tuning_phase = True
                                tuning_start_time = time

                                # 窗口数据提取
                                window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)
                                window_t = np.array(time_data[window_start:]) - time_data[window_start]
                                window_u = np.array(valve_data[window_start:])
                                window_y = np.array(temp_data[window_start:])

                                # 重新辨识与整定
                                new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)
                                identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})
                                K, T, L = new_K, new_T, new_L

                                lambda_val = lambda_slider.val
                                new_Kp, new_Ti, new_Td = self.identifier.lambda_tuning(K, T, L, lambda_val,
                                                                                       mode=system_mode)

                                # 按扰动类型优化参数
                                if current_disturbance["type"] == "overshoot":
                                    new_Kp *= 0.9  # 减小比例增益抑制超调
                                    print(f"🔧 超调优化：Kp降低10% → {new_Kp:.2f}")
                                elif current_disturbance["type"] == "steady_error":
                                    new_Ti *= 0.8  # 减小积分时间加速消除稳态误差
                                    print(f"🔧 稳态误差优化：Ti降低20% → {new_Ti:.1f}s")
                                elif current_disturbance["type"] == "slow_recovery":
                                    new_Kp *= 1.1  # 增加比例增益加速响应
                                    new_Td *= 1.1  # 增加微分增益抑制震荡
                                    print(f"🔧 恢复优化：Kp/Td提高10% → {new_Kp:.2f}, {new_Td:.1f}s")
                                elif current_disturbance["type"] == "valve_stiction":
                                    new_Kp *= 0.85  # 降低增益减少阀门频繁动作
                                    new_Ti *= 1.2  # 增加积分时间适应卡涩
                                    print(f"🔧 阀门卡涩优化：Kp降低15%，Ti提高20% → {new_Kp:.2f}, {new_Ti:.1f}s")
                                elif current_disturbance["type"] == "sensor_drift":
                                    new_Td *= 1.3  # 增加微分作用补偿漂移
                                    print(f"🔧 传感器漂移优化：Td提高30% → {new_Td:.1f}s")
                                elif current_disturbance["type"] == "heat_loss":
                                    new_Kp *= 1.15  # 提高增益补偿热损失
                                    new_Ti *= 0.85  # 减少积分时间加快响应
                                    print(f"🔧 热损失优化：Kp提高15%，Ti降低15% → {new_Kp:.2f}, {new_Ti:.1f}s")
                                elif current_disturbance["type"] == "control_valve_wear":
                                    new_Kp *= 0.8  # 降低增益适应磨损
                                    new_Td *= 0.9  # 微调微分
                                    print(f"🔧 控制阀磨损优化：Kp降低20%，Td降低10% → {new_Kp:.2f}, {new_Td:.1f}s")
                                elif current_disturbance["type"] == "thermal_inertia":
                                    new_Ti *= 1.2  # 增加积分时间适应惯性
                                    new_Td *= 1.2  # 增加微分时间
                                    print(f"🔧 热惯性优化：Ti/Td提高20% → {new_Ti:.1f}s, {new_Td:.1f}s")

                                # 执行参数更新（带平滑）
                                pid.set_target_params(new_Kp, new_Ti, new_Td, reset_integral=True)
                                update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
                                update_lines.append(update_line)
                                params_update_count += 1
                                current_disturbance['updated'] = True  # 标记已更新

                                # 记录参数更新日志
                                self.logger.info(f"参数更新 {params_update_count} 次 - 时间: {time:.0f}s")
                                self.logger.info(
                                    f"扰动类型: {current_disturbance['type']} - {current_disturbance['description']}")
                                self.logger.info(f"新参数: Kp={new_Kp:.2f}, Ti={new_Ti:.1f}s, Td={new_Td:.1f}s")
                                self.logger.info(f"旧参数: Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")

                                # 打印参数变化（旧→新）
                                print(f"参数更新 {params_update_count} 次：")
                                print(f"Kp: {pid.Kp:.2f} → {new_Kp:.2f}")
                                print(f"Ti: {pid.Ti:.1f}s → {new_Ti:.1f}s")
                                print(f"Td: {pid.Td:.1f}s → {new_Td:.1f}s\n")
                                self.visualizer.update_params_text(params_text, identified_params,
                                                                   {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td},
                                                                   lambda_val, params_update_count,
                                                                   initial_valid_params, pid_mode, system_mode)

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
                            print(f"🎉 {d['description']}已恢复稳定（{time:.0f}s），当前温度: {current_temp:.1f}℃")
                            self.logger.info(
                                f"扰动 {d['description']} 已恢复稳定 - 时间: {time:.0f}s, 温度: {current_temp:.1f}℃")

                # 定期打印状态（每50步）
                if i % 50 == 0:
                    stable_status = "已稳态" if stabilization_time else "暂稳态"
                    recovery_text = ", ".join(
                        [f"{d['description']}:{'已恢复' if recovery_status[d['type']] else '恢复中'}"
                         for d in disturbances])
                    tuning_phase_status = "PID整定中" if in_pid_tuning_phase else "正常运行"
                    print(
                        f"时间: {time:.0f}s | 系统模式: {Config.MODES[system_mode]} | PID模式: {Config.PID_MODES[pid_mode]} | 实际响应温度: {current_temp:.1f}℃ | 真实仿真温度: {true_current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                        f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {params_update_count}次 | {tuning_phase_status}")

                # 批量更新绘图
                if i % Config.PLOT_REFRESH_INTERVAL == 0:
                    self.visualizer.update_plots(time_data, temp_data, true_temp_data, valve_data, error_data,
                                                 kp_data, ti_data, td_data, update_lines)

            # 保存数据
            real_time_data = np.column_stack(
                (time_data, temp_data, true_temp_data[-len(time_data):], valve_data, error_data,
                 kp_data, ti_data, td_data))
            self.data_handler.save_data(real_time_data,
                                        ["时间(s)", "实际响应温度(℃)", "真实仿真温度(℃)", "阀门开度(%)", "误差(℃)",
                                         "Kp", "Ti/10", "Td*2"],
                                        "real_time_control_data.csv")

            # 结束信息
            end_time = datetime.now()
            duration = end_time - start_time
            print("\n" + "=" * 50)
            print(f"系统运行模式: {Config.MODES[system_mode]} | PID控制模式: {Config.PID_MODES[pid_mode]}")
            print(f"初始温度：{Config.INIT_TEMPERATURE}℃ → 目标：{Config.TARGET_TEMPERATURE}℃")
            print(
                f"最终实际响应温度：{current_temp:.1f}℃ | 最终真实仿真温度：{true_current_temp:.1f}℃ | 最终误差：{error:.2f}℃")
            if initial_valid_params is not None:
                print(f"初始有效参数 → 最终参数：")
                print(f"Kp: {initial_valid_params[0]:.2f} → {pid.Kp:.2f}")
                print(f"Ti: {initial_valid_params[1]:.1f}s → {pid.Ti:.1f}s")
                print(f"Td: {initial_valid_params[2]:.1f}s → {pid.Td:.1f}s")
            else:
                print(f"最终PID参数：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
            print(f"总更新次数：{params_update_count}次")
            print(f"运行时间: {duration}")
            print("=" * 50)

            # 记录结束日志
            self.logger.info(f"控制监控系统结束 - 结束时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"总运行时间: {duration}")
            self.logger.info(f"最终温度: {current_temp:.1f}℃, 误差: {error:.2f}℃, 更新次数: {params_update_count}")
            self.logger.info(f"最终PID参数: Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
            self.logger.info(f"系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}")

            plt.ioff()
            plt.show()

        except KeyboardInterrupt:
            # 中断时保存数据
            end_time = datetime.now()
            duration = end_time - start_time
            if len(time_data) > 0:
                real_time_data = np.column_stack(
                    (time_data, temp_data, true_temp_data[-len(time_data):], valve_data, error_data))
                self.data_handler.save_data(real_time_data,
                                            ["时间(s)", "实际响应温度(℃)", "真实仿真温度(℃)", "阀门开度(%)", "误差(℃)"],
                                            "real_time_control_data_interrupted.csv")
            print("\n" + "=" * 50)
            print(f"系统运行模式: {Config.MODES[system_mode]} | PID控制模式: {Config.PID_MODES[pid_mode]}")
            print("监控手动终止")
            print(
                f"当前实际响应温度：{current_temp:.1f}℃ | 当前真实仿真温度：{true_current_temp:.1f}℃ | 误差：{error:.2f}℃")
            if initial_valid_params is not None:
                print(f"初始有效参数 → 当前参数：")
                print(f"Kp: {initial_valid_params[0]:.2f} → {pid.Kp:.2f}")
                print(f"Ti: {initial_valid_params[1]:.1f}s → {pid.Ti:.1f}s")
                print(f"Td: {initial_valid_params[2]:.1f}s → {pid.Td:.1f}s")
            else:
                print(f"当前PID参数：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
            print(f"总更新次数：{params_update_count}次")
            print(f"运行时间: {duration}")
            print("=" * 50)

            # 记录中断日志
            self.logger.info(f"控制监控系统被手动中断 - 时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"中断时运行时间: {duration}")
            self.logger.info(f"中断时温度: {current_temp:.1f}℃, 误差: {error:.2f}℃, 更新次数: {params_update_count}")
            self.logger.info(f"中断时PID参数: Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
            self.logger.info(f"系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}")

            plt.ioff()
            plt.close(fig)


if __name__ == "__main__":
    monitor = ControlMonitor()
    monitor.run()




