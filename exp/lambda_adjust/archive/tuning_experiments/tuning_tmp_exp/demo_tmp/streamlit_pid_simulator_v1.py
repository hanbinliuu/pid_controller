import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from scipy.optimize import least_squares
from scipy import signal
import logging
import threading
import time
from datetime import datetime
import os

## 用streamlit run 跑demo(和v5功能差不多，固定长度仿真数据)


# 设置中文字体
plt.rcParams['font.sans-serif'] = ["Heiti TC"]  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号


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
    SIMULATION_DURATION = 5000  # 仿真总时长(s)
    DATA_SAVE_DIR = "data_simulation/data_generation"  # 数据保存目录
    PLOT_REFRESH_INTERVAL = 5  # 绘图刷新间隔(步)

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
# 2. 扰动处理模块
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
# 3. 系统模型模块
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
# 4. 控制器模块
# ==============================
class PIDController:
    """PID控制器：实现PID控制与参数平滑更新"""

    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100, mode="standard", system_mode="standard"):
        self.Kp = Kp
        self.Ti = Ti
        self.Td = Td
        self.target_Kp = Kp  # 目标参数（用于平滑更新）
        self.target_Ti = Ti
        self.target_Td = Td

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
        error = setpoint - process_var
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
# 5. 辨识与整定模块
# ==============================
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
    def lambda_tuning(K, T, L, lambda_val=None, mode="standard"):
        """基于Lambda方法整定PID参数，根据模式调整参数"""
        if lambda_val is None:
            lambda_val = T * 0.3

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

        # 参数限幅
        Kp = np.clip(Kp, 0.5, 6.0)
        Ti = np.clip(Ti, 8.0, 120.0)
        Td = np.clip(Td, 0.0, 25.0)
        return Kp, Ti, Td


# ==============================
# 6. 状态分析模块
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

        # 4. 温度波动性检测
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
# 7. 扰动生成模块
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
        selected_types = np.random.choice(available_types, size=num_disturbances, replace=False)

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


def main():
    st.set_page_config(page_title="温度控制系统自适应PID监控平台", layout="wide")
    st.title("🌡️ 温度控制系统自适应PID监控平台")
    st.markdown("---")

    # 侧边栏配置
    st.sidebar.header("🔧 系统配置")

    # 系统运行模式选择
    system_mode = st.sidebar.selectbox(
        "选择系统运行模式",
        options=list(Config.MODES.keys()),
        format_func=lambda x: Config.MODES[x],
        index=0
    )

    # 降噪强度选择
    noise_reduction_level = st.sidebar.selectbox(
        "选择降噪强度",
        options=list(Config.NOISE_REDUCTION_LEVELS.keys()),
        format_func=lambda x: f"{x.title()}强度降噪",
        index=1
    )

    # PID模式选择
    pid_mode = st.sidebar.selectbox(
        "选择PID控制模式",
        options=list(Config.PID_MODES.keys()),
        format_func=lambda x: Config.PID_MODES[x],
        index=0
    )

    # Lambda参数滑块
    lambda_val = st.sidebar.slider(
        "Lambda参数（影响响应速度）",
        min_value=1.0,
        max_value=60.0,
        value=15.0,
        step=0.5,
        help="Lambda值越小，响应越快但可能不稳定；越大越稳定但响应慢"
    )

    # 开始仿真按钮
    start_simulation = st.sidebar.button("🚀 开始仿真", type="primary", use_container_width=True)

    # 显示当前配置
    st.sidebar.subheader("当前配置")
    st.sidebar.write(f"**系统模式**: {Config.MODES[system_mode]}")
    st.sidebar.write(f"**降噪强度**: {noise_reduction_level.title()}")
    st.sidebar.write(f"**PID模式**: {Config.PID_MODES[pid_mode]}")
    st.sidebar.write(f"**Lambda值**: {lambda_val}")
    st.sidebar.write(f"**目标温度**: {Config.TARGET_TEMPERATURE}℃")
    st.sidebar.write(f"**初始温度**: {Config.INIT_TEMPERATURE}℃")

    if start_simulation:
        # 初始化模块
        identifier = SystemIdentifier()
        state_analyzer = StateAnalyzer(mode=system_mode)
        disturbance_generator = DisturbanceGenerator(mode=system_mode)

        # 生成随机扰动
        disturbances = disturbance_generator.generate_random_disturbances()

        # 初始化系统与输入
        initial_true_params = {'K': 0.8, 'T': 30, 'L': 4, 'noise_level': 0.3}
        temp_system = TemperatureSystem(**initial_true_params, mode=system_mode)

        # 生成时间序列
        t = np.arange(0, Config.SIMULATION_DURATION, 1)
        u = temp_system.generate_non_step_input(t)
        response_data = temp_system.simulate_with_input(t, u, disturbances)

        # 应用低通滤波
        cutoff_freq = Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]["cutoff_freq"]
        order = Config.NOISE_REDUCTION_LEVELS[noise_reduction_level]["order"]

        # 对温度数据应用滤波
        nyquist_freq = 0.5 * 1.0  # 采样频率为1Hz
        normalized_cutoff = cutoff_freq / nyquist_freq
        normalized_cutoff = min(normalized_cutoff, 0.99)
        b, a = signal.butter(order, normalized_cutoff, btype='low', analog=False)
        response_data = signal.filtfilt(b, a, response_data)

        # 对输入信号应用滤波
        if Config.FILTER_APPLY_TO_INPUT:
            u = signal.filtfilt(b, a, u)

        # 初始参数辨识
        K, T, L = identifier.identify_fopdt(t, response_data, u)
        identified_params = {'K': K, 'T': T, 'L': L}

        # 初始化图表数据
        time_data = []
        temp_data = []
        true_temp_data = []
        valve_data = []
        error_data = []
        kp_data = []
        ti_data = []
        td_data = []
        update_times = []  # 存储参数更新时间点

        # 初始化系统与控制器
        init_Kp, init_Ti, init_Td = identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)
        system = TemperatureSystem(**initial_true_params, mode=system_mode)
        pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1, mode=pid_mode, system_mode=system_mode)
        current_temp = Config.INIT_TEMPERATURE

        # 初始化真实系统（用于模拟无控制器的自然响应）
        true_system = TemperatureSystem(**initial_true_params, mode=system_mode)
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

        # 新增：用于避免PID整定过程中重复识别扰动的标志
        in_pid_tuning_phase = False  # 标记是否正在PID参数整定阶段
        tuning_start_time = None  # 记录PID整定开始时间
        tuning_duration = 200  # PID整定阶段的持续时间（秒）

        # 显示实时图表
        placeholder = st.empty()

        for i, time in enumerate(t):
            # 计算控制输出与当前温度
            valve_opening = pid.compute(Config.TARGET_TEMPERATURE, current_temp)
            current_temp = system.update(valve_opening, time, disturbances=disturbances)
            error = Config.TARGET_TEMPERATURE - current_temp

            # 计算真实系统温度（无控制器影响）
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
            if stabilization_time is None and state_analyzer.is_stable(temp_data, Config.TARGET_TEMPERATURE):
                stabilization_time = time
                tuning_enabled = True
                initial_valid_params = (pid.Kp, pid.Ti, pid.Td)  # 记录初始有效参数

            # 自动扰动检测逻辑（仅在未处于PID整定阶段时执行）
            if tuning_enabled and not in_pid_tuning_phase:
                # 使用优化的扰动检测算法
                is_disturbance, disturbance_desc = state_analyzer.detect_instability_optimized(
                    temp_data, Config.TARGET_TEMPERATURE, valve_data, time_data
                )

                if is_disturbance:
                    # 检查当前时间是否在任何手动定义的扰动区间内
                    current_disturbance = next((d for d in disturbances
                                                if d["time"] <= time < d["time"] + d["duration"]), None)
                    if current_disturbance:
                        # 扰动开始后20s内强制更新参数（避免初期波动误判）
                        if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:
                            # 进入PID整定阶段，设置标志和时间
                            in_pid_tuning_phase = True
                            tuning_start_time = time

                            # 窗口数据提取
                            window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)
                            window_t = np.array(time_data[window_start:]) - time_data[window_start]
                            window_u = np.array(valve_data[window_start:])
                            window_y = np.array(temp_data[window_start:])

                            # 重新辨识与整定
                            new_K, new_T, new_L = identifier.identify_fopdt(window_t, window_y, window_u)
                            identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})
                            K, T, L = new_K, new_T, new_L

                            new_Kp, new_Ti, new_Td = identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)

                            # 按扰动类型优化参数
                            if current_disturbance["type"] == "overshoot":
                                new_Kp *= 0.9  # 减小比例增益抑制超调
                            elif current_disturbance["type"] == "steady_error":
                                new_Ti *= 0.8  # 减小积分时间加速消除稳态误差
                            elif current_disturbance["type"] == "slow_recovery":
                                new_Kp *= 1.1  # 增加比例增益加速响应
                                new_Td *= 1.1  # 增加微分增益抑制震荡
                            elif current_disturbance["type"] == "valve_stiction":
                                new_Kp *= 0.85  # 降低增益减少阀门频繁动作
                                new_Ti *= 1.2  # 增加积分时间适应卡涩
                            elif current_disturbance["type"] == "sensor_drift":
                                new_Td *= 1.3  # 增加微分作用补偿漂移
                            elif current_disturbance["type"] == "heat_loss":
                                new_Kp *= 1.15  # 提高增益补偿热损失
                                new_Ti *= 0.85  # 减少积分时间加快响应
                            elif current_disturbance["type"] == "control_valve_wear":
                                new_Kp *= 0.8  # 降低增益适应磨损
                                new_Td *= 0.9  # 微调微分
                            elif current_disturbance["type"] == "thermal_inertia":
                                new_Ti *= 1.2  # 增加积分时间适应惯性
                                new_Td *= 1.2  # 增加微分时间

                            # 执行参数更新（带平滑）
                            pid.set_target_params(new_Kp, new_Ti, new_Td, reset_integral=True)
                            params_update_count += 1
                            current_disturbance['updated'] = True  # 标记已更新
                            update_times.append(time)  # 记录更新时间

            # 检查是否退出PID整定阶段
            if in_pid_tuning_phase:
                if time - tuning_start_time >= tuning_duration:
                    in_pid_tuning_phase = False
                    tuning_start_time = None

            # 扰动后恢复判断
            for d in disturbances:
                if (d['updated'] and not recovery_status[d["type"]] and
                        time > d["time"] + d["duration"] + 60):  # 扰动结束后60s判断（增加恢复时间）
                    if state_analyzer.is_stable(temp_data, Config.TARGET_TEMPERATURE):
                        recovery_status[d["type"]] = True

            # 每100步更新一次图表
            if i % 100 == 0 or i == len(t) - 1:
                with placeholder.container():
                    # 显示实时指标
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("当前时间", f"{time}s")
                    with col2:
                        st.metric("当前温度", f"{current_temp:.1f}℃", f"{error:.2f}℃ 误差")
                    with col3:
                        st.metric("阀门开度", f"{valve_opening:.1f}%")
                    with col4:
                        st.metric("参数更新次数", params_update_count)

                    # 绘制温度控制曲线
                    fig, ax = plt.subplots(figsize=(12, 6))

                    ax.plot(time_data, temp_data, label='实际响应温度', linewidth=1.5)
                    ax.plot(time_data, true_temp_data, label='真实仿真温度', linestyle='--', alpha=0.7)
                    ax.axhline(y=Config.TARGET_TEMPERATURE, color='red', linestyle='--', label='目标温度', alpha=0.8)
                    ax.axhline(y=Config.INIT_TEMPERATURE, color='orange', linestyle='-.', label='初始温度', alpha=0.8)

                    # 标记扰动区域
                    for d in disturbances:
                        ax.axvspan(d["time"], d["time"] + d["duration"], alpha=0.1,
                                   color='red')

                    # 标记参数更新点
                    if update_times:
                        for update_time in update_times:
                            ax.axvline(x=update_time, color='blue', linestyle='--', alpha=0.7,
                                       label='参数更新点' if update_time == update_times[0] else "")

                    ax.set_xlabel('时间 (s)')
                    ax.set_ylabel('温度 (℃)')
                    ax.set_title(
                        f'温度控制曲线（含扰动与参数更新 - 模式: {Config.MODES[system_mode]}, 降噪: {noise_reduction_level.title()}）')
                    ax.legend()
                    ax.grid(True, alpha=0.3)
                    st.pyplot(fig)

                    # 显示当前状态信息
                    status_info = f"系统模式: {Config.MODES[system_mode]} | PID模式: {Config.PID_MODES[pid_mode]} | 降噪强度: {noise_reduction_level.title()} | 当前PID参数: Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s"
                    st.info(status_info)

        # 最终结果展示
        st.subheader("📊 仿真完成 - 最终结果")

        # 显示关键指标
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("最终温度", f"{current_temp:.1f}℃", f"{Config.TARGET_TEMPERATURE - current_temp:.2f}℃ 误差")
        with col2:
            st.metric("真实温度", f"{true_current_temp:.1f}℃",
                      f"{true_current_temp - Config.INIT_TEMPERATURE:.1f}℃ 变化")
        with col3:
            st.metric("参数更新次数", params_update_count)
        with col4:
            st.metric("扰动数量", len(disturbances))

        # 绘制最终完整图表
        st.subheader("📈 最终温度控制曲线")
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(time_data, temp_data, label='实际响应温度', linewidth=1.5)
        ax.plot(time_data, true_temp_data, label='真实仿真温度', linestyle='--', alpha=0.7)
        ax.axhline(y=Config.TARGET_TEMPERATURE, color='red', linestyle='--', label='目标温度', alpha=0.8)
        ax.axhline(y=Config.INIT_TEMPERATURE, color='orange', linestyle='-.', label='初始温度', alpha=0.8)

        # 标记扰动区域
        for d in disturbances:
            ax.axvspan(d["time"], d["time"] + d["duration"], alpha=0.1,
                       label=f"{d['description']}" if d == disturbances[0] else "",
                       color='red')

        # 标记参数更新点
        if update_times:
            for update_time in update_times:
                ax.axvline(x=update_time, color='blue', linestyle='--', alpha=0.7,
                           label='参数更新点' if update_time == update_times[0] else "")

        ax.set_xlabel('时间 (s)')
        ax.set_ylabel('温度 (℃)')
        ax.set_title(
            f'温度控制曲线（含扰动与参数更新 - 模式: {Config.MODES[system_mode]}, 降噪: {noise_reduction_level.title()}）')
        ax.legend()
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

        # 阀门开度曲线
        st.subheader("🔧 阀门开度变化")
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(time_data, valve_data, label='阀门开度', color='green', linewidth=1.5)
        ax.set_xlabel('时间 (s)')
        ax.set_ylabel('开度 (%)')
        ax.set_title('阀门开度变化曲线')
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

        # 控制误差曲线
        st.subheader("📉 控制误差曲线")
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(time_data, error_data, label='控制误差', color='red', linewidth=1.5)
        ax.axhline(y=0, color='black', linestyle='-', alpha=0.3)
        ax.set_xlabel('时间 (s)')
        ax.set_ylabel('误差 (℃)')
        ax.set_title('控制误差曲线')
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

        # PID参数变化曲线
        st.subheader("🎛️ PID参数变化趋势")
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(time_data, kp_data, label='Kp', linewidth=1.5)
        ax.plot(time_data, ti_data, label='Ti/10', linewidth=1.5)
        ax.plot(time_data, td_data, label='Td*2', linewidth=1.5)
        ax.set_xlabel('时间 (s)')
        ax.set_ylabel('参数值')
        ax.set_title(f'PID参数变化趋势 (模式: {Config.PID_MODES[pid_mode]}, 系统模式: {Config.MODES[system_mode]})')
        ax.legend()
        ax.grid(True, alpha=0.3)
        st.pyplot(fig)

        # 扰动信息
        st.subheader("⚠️ 扰动信息")
        for i, d in enumerate(disturbances):
            st.write(f"**{i + 1}. {d['description']}**")
            st.write(f"   - 发生时间: {d['time']}s")
            st.write(f"   - 持续时间: {d['duration']}s")
            st.write(f"   - 幅值: {d['amplitude']:.1f}℃")
            st.write(f"   - 是否更新参数: {'是' if d['updated'] else '否'}")

        # 最终PID参数
        st.subheader("🎯 最终PID参数")
        st.write(f"**比例增益 Kp**: {pid.Kp:.2f}")
        st.write(f"**积分时间 Ti**: {pid.Ti:.1f}s")
        st.write(f"**微分时间 Td**: {pid.Td:.1f}s")

    else:
        # 显示欢迎信息
        st.subheader("欢迎使用温度控制系统自适应PID监控平台")
        st.write("这是一个完整的温度控制系统仿真平台，具有以下功能：")

        features = [
            "🔄 自适应PID控制（支持3种模式）",
            "🌡️ 温度系统建模与仿真",
            "⚠️ 8种典型工业扰动模拟",
            "🔍 智能扰动检测与参数自整定",
            "📊 实时数据可视化",
            "📈 系统参数辨识与Lambda整定",
            "🛡️ 三种运行模式：标准/抗扰动/抗噪声",
            "🔊 三种降噪强度：低/中/高"
        ]

        for feature in features:
            st.write(feature)

        st.write(" ")
        st.write("请在左侧边栏配置参数，然后点击'开始仿真'按钮启动系统！")


if __name__ == "__main__":
    main()



