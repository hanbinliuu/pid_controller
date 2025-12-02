import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
from scipy.optimize import least_squares
from scipy import signal
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
import json
from enum import Enum
from collections import deque
import threading
import time


# 流数据仿真+自识别扰动段+cohencoon整定法可选


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
#                    情况 3：已有可用 PID，从初始温升到目标温，之后可能扰动



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
    TARGET_TEMPERATURE = 3

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

    # 扰动检测相关参数 - 优化后
    DETECTION_WINDOW = 60  # 扰动检测窗口大小
    ERROR_THRESHOLD = 1.5  # 误差阈值
    STD_THRESHOLD = 1.2  # 标准差阈值
    SLOPE_THRESHOLD = 0.05  # 温度变化率阈值
    VALVE_CHANGE_THRESHOLD = 25  # 阀门变化阈值
    CORRELATION_THRESHOLD = 0.3  # 相关性阈值

    # 新增：自适应检测参数
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

    def choose_mode(self):
        """选择运行模式"""
        print(f"\n=== 选择运行模式 ===")
        for i, (key, desc) in enumerate(Config.MODES.items(), 1):
            print(f"{i}. {desc} ({key})")

        while True:
            choice = input("请选择运行模式（1-3，直接回车选1）：").strip() or "1"
            if choice in ["1", "2", "3"]:
                return list(Config.MODES.keys())[int(choice) - 1]
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

        # 新增：性能指标跟踪
        self.error_history = deque(maxlen=200)
        self.control_effort_history = deque(maxlen=200)

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
        # 检查是否存在“稳态 → 偏离 → 恢复”模式
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
            if self.is_steady_state(temp_data[i-window+1:i+1], setpoint, tol, std_tol):
                return i - window + 1  # 返回稳态开始索引
        return None

    def find_disturbance_start(self, temp_data, setpoint, steady_head_len, threshold=1.0):
        """定位扰动起始点"""
        for i in range(steady_head_len, len(temp_data)):
            if abs(temp_data[i] - setpoint) > threshold:
                # 可加斜率突变判断：|dT/dt| 突增
                return i
        return None

    def extract_tuning_segment(self, case, t, temp_data, setpoint):
        """根据情形提取有效整定段"""
        if case == "CASE_1":
            # 全程非稳态，整段作为整定段
            return t, temp_data
        elif case == "CASE_2":
            # 扰动后恢复段
            head_len = min(50, len(temp_data) // 3)
            start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
            if start_idx is not None:
                return t[start_idx:], temp_data[start_idx:]
            else:
                # 如果没找到扰动点，可能数据有问题，返回后半段
                mid = len(t) // 2
                return t[mid:], temp_data[mid:]
        elif case in ["CASE_3", "CASE_3_FALLBACK"]:
            # 首次升温段
            steady_idx = self.find_first_steady_entry(temp_data, setpoint)
            if steady_idx:
                # 多取一点包含超调或稳定过程
                end_idx = min(steady_idx + 20, len(t))
                return t[:end_idx], temp_data[:end_idx]
            else:
                # 退化为 CASE_2
                head_len = min(50, len(temp_data) // 3)
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
                if start_idx is not None:
                    return t[start_idx:], temp_data[start_idx:]
                else:
                    # 如果都找不到，返回前半段
                    mid = len(t) // 2
                    return t[:mid], temp_data[:mid]
        else:
            # UNKNOWN 或 ALREADY_STABLE，返回 None
            return None, None

    def auto_tune_from_json(self, t, temp_data, setpoint, tuning_method, mode=Mode.STANDARD):
        """根据JSON数据自动整定PID参数"""
        case = self.classify_case(temp_data, setpoint)
        print(f"📊 JSON数据情形: {case}")

        if case == "ALREADY_STABLE":
            print("✅ 数据已稳定，无需整定")
            return None

        t_seg, y_seg = self.extract_tuning_segment(case, t, temp_data, setpoint)

        if t_seg is None or len(t_seg) < 20:
            print("⚠️ 无法提取有效整定段，数据不足")
            return None

        print(f"📈 提取整定段: {len(t_seg)} 个点")
        # 重置时间轴为从0开始
        t_seg_rel = t_seg - t_seg[0]

        # 拟合FOPDT模型
        try:
            K, tau, L = self.identify_fopdt(t_seg_rel, y_seg, setpoint)
            print(f"🔍 FOPDT辨识结果: K={K:.3f}, τ={tau:.3f}, L={L:.3f}")
        except Exception as e:
            print(f"❌ FOPDT拟合失败: {e}")
            return None

        # Lambda整定
        lambda_val = tau  # 可配置
        if tuning_method == TuningMethod.LAMBDA:
            pb, ti, td = self.lambda_tuning(K, tau, L, lambda_val, mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            pb, ti, td = self.cohen_coon_tuning(K, tau, L)
        else:
            pb, ti, td = self.lambda_tuning(K, tau, L, lambda_val, mode)

        print(f"🎯 计算PID参数: Pb={pb:.2f}%, Ti={ti:.2f}s, Td={td:.2f}s")
        return {"pb": pb, "ti": ti, "td": td, "case": case}


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
        if len(temp_data) < Config.MIN_DETECTION_WINDOW:
            return False, ""

        # 获取当前窗口的数据 - 使用自适应窗口大小
        window_size = min(len(temp_data), self.current_window_size)
        # 修复：确保window_size是整数
        window_size = int(window_size)
        recent_temps = np.array(temp_data[-window_size:])
        recent_valves = np.array(valve_data[-window_size:])
        recent_times = np.array(time_data[-window_size:])

        # 计算误差
        errors = recent_temps - setpoint

        # 1. 误差统计特征
        mean_error = np.mean(errors)
        std_error = np.std(errors)
        max_error = np.max(np.abs(errors))

        # 2. 温度变化率检测
        if len(recent_temps) > 1:
            temp_deriv = np.diff(recent_temps)
            mean_abs_deriv = np.mean(np.abs(temp_deriv))
        else:
            temp_deriv = np.array([0])
            mean_abs_deriv = 0

        # 3. 阀门动作检测
        if len(recent_valves) > 1:
            valve_changes = np.diff(recent_valves)
            valve_activity = np.sum(np.abs(valve_changes))
        else:
            valve_changes = np.array([0])
            valve_activity = 0

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
            if len(recent_temps) > 1:
                autocorr = np.corrcoef(recent_temps[:-1], recent_temps[1:])[0, 1]
                autocorr_strength = abs(autocorr) if not np.isnan(autocorr) else 0
            else:
                autocorr_strength = 0

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
            else:
                # 无扰动时逐渐减小窗口以提高响应速度
                decay_factor = 0.99
                self.current_window_size = max(self.current_window_size * decay_factor, Config.MIN_DETECTION_WINDOW)

        return is_disturbance, disturbance_type


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
            DisturbanceType.THERMAL_INERTIA: "cyan"
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
            'lines': (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line),
            'text': params_text,
            'slider': lambda_slider,
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

目标温度: {Config.TARGET_TEMPERATURE}℃ | 初始温度: {Config.INIT_TEMPERATURE}℃"""
        text_obj.set_text(text)

    def update_plots(self, time_data, temp_data, valve_data, error_data, pb_data, ti_data, td_data,
                     update_lines, new_pid_time_data=None, new_pid_temp_data=None, no_pid_temp_data=None):
        """实时更新绘图数据"""
        (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line) = self.plot_data[
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


class DisturbanceGenerator:
    """扰动生成器：生成各种系统扰动"""

    def __init__(self, mode=Mode.STANDARD):
        self.mode = mode

    @staticmethod
    def generate_random_disturbances():
        """生成随机扰动配置 - 考虑更多失效场景，每次最多4种"""
        # 随机选择扰动数量 (2-4个)
        num_disturbances = min(3, 8)  # 最多4种失效场景

        disturbances = []
        used_time_slots = []

        # 从所有可用的扰动类型中选择num_disturbances种
        available_types = Config.DISTURBANCE_TYPES.copy()
        selected_types = np.random.choice(available_types, size=num_disturbances, replace=False)

        for i in range(num_disturbances):
            disturbance_type = selected_types[i]

            # 随机选择扰动时间（避开初始稳定期和结束期）
            time_start = np.random.randint(500, 5000)  # 限制在前5000秒内，因为SIMULATION_DURATION是无穷

            # 避免时间重叠 - 确保扰动之间有足够距离以恢复稳态
            min_separation = 800  # 最小间隔600秒，确保恢复稳态
            while any(abs(time_start - used_start) < min_separation for used_start in used_time_slots):
                time_start = np.random.randint(500, 5000)

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

        # 选择运行模式
        system_mode = self.data_handler.choose_mode()
        self.logger.info(f"选择系统运行模式: {Config.MODES[system_mode]}")

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

        # 选择数据来源
        t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.data_handler.choose_data_source(
            data_type="dynamic_response")

        # 初始化系统与输入
        initial_true_params = {'K': 0.3, 'T': 20, 'L': 4, 'noise_level': 0.3}
        temp_system = TemperatureSystem(**initial_true_params, mode=system_mode)

        # 标记是否使用JSON数据
        using_json_data = pv_data is not None

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
                # 新增：基于JSON数据的智能整定
                new_params = self.identifier.auto_tune_from_json(t, response_data, setpoint, tuning_method, system_mode)
                if new_params:
                    init_pb, init_ti, init_td = new_params['pb'], new_params['ti'], new_params['td']
                    print(f"✅ 基于JSON数据自动整定PID参数: Pb={init_pb:.2f}%, Ti={init_ti:.2f}s, Td={init_td:.2f}s")
                else:
                    K, T, L = self.identifier.identify_fopdt(t, response_data, u)
                    init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)
        else:
            # 生成仿真数据（如未提供）
            initial_time = np.arange(0, 1000, 1)  # 初始生成1000个点
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

            # 从仿真数据中获取初始PID参数
            K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)
            init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

        # 初始参数辨识
        print(f"\n全局初始温度：{Config.INIT_TEMPERATURE}℃ | 目标温度：{Config.TARGET_TEMPERATURE}℃")
        print("正在辨识系统初始参数（K, T, L）...")
        if using_json_data:
            # 使用JSON数据进行初始参数辨识
            K, T, L = self.identifier.identify_fopdt(t, response_data, u)
        else:
            # 使用仿真数据进行初始参数辨识
            K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)
        identified_params = {'K': K, 'T': T, 'L': L}

        # 启动实时监控
        print(
            f"\n启动温度控制监控 (系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]})...")
        self._run_real_time_monitor(u, setpoint=Config.TARGET_TEMPERATURE, true_params=initial_true_params,
                                    identified_params=identified_params, response_data=response_data,
                                    disturbances=disturbances, start_time=start_time, pid_mode=pid_mode,
                                    system_mode=system_mode, state_analyzer=state_analyzer,
                                    using_json_data=using_json_data,
                                    pb_data=pb_data, ti_data=ti_data, td_data=td_data, tuning_method=tuning_method)

    def _get_initial_params(self, K, T, L, tuning_method, system_mode):
        """根据整定方法获取初始PID参数"""
        if tuning_method == TuningMethod.LAMBDA:
            return self.identifier.lambda_tuning(K, T, L, mode=system_mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            return self.identifier.cohen_coon_tuning(K, T, L)
        else:
            # 默认使用Lambda方法
            return self.identifier.lambda_tuning(K, T, L, mode=system_mode)

    def _run_real_time_monitor(self, u, setpoint, true_params, identified_params, response_data, disturbances,
                               start_time, pid_mode, system_mode, state_analyzer, using_json_data, pb_data, ti_data,
                               td_data, tuning_method):
        """实时监控主循环 - 无限运行版本"""
        # 创建初始时间数组
        initial_time = np.arange(len(response_data)) if len(response_data) > 0 else np.arange(len(u))

        # 初始化图表
        fig, plot_data = self.plot_manager.init_real_time_fig(initial_time, u, setpoint, identified_params,
                                                              {'Pb': 0, 'Ti': 0, 'Td': 0}, response_data, true_params,
                                                              disturbances, pid_mode, system_mode, tuning_method)
        (ax2, _, _, _) = plot_data['axes']
        params_text = plot_data['text']
        lambda_slider = plot_data['slider']
        stabilization_line, update_lines, _ = plot_data['markers']
        temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line = plot_data[
            'lines']

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

        # 根据是否使用JSON数据来初始化PID参数
        if using_json_data:
            # 使用JSON中的PID参数作为初始参数（如果存在且有效）
            if pb_data is not None and ti_data is not None and td_data is not None and len(pb_data) > 0 and len(
                    ti_data) > 0 and len(td_data) > 0:
                init_pb = pb_data[0] if pb_data[0] != 0 else 100
                init_ti = ti_data[0] if ti_data[0] != 0 else 20
                init_td = td_data[0] if td_data[0] != 0 else 0
            else:
                # 如果JSON中没有PID参数，使用辨识结果
                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)
        else:
            # 使用辨识得到的参数
            init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

        system = TemperatureSystem(**true_params, mode=system_mode)
        pid = PIDController(pb=init_pb, ti=init_ti, td=init_td, dt=1, mode=pid_mode, system_mode=system_mode)

        # 初始化当前温度
        if using_json_data:
            current_temp = response_data[0] if len(response_data) > 0 else Config.INIT_TEMPERATURE
        else:
            current_temp = Config.INIT_TEMPERATURE

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
        print(f"静态增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s")
        print(f"初始PID参数：Pb={init_pb:.2f}%, Ti={init_ti:.1f}s, Td={init_td:.1f}s")
        if not using_json_data:
            print("\n随机扰动计划：")
            for d in disturbances:
                print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s，幅值{d['amplitude']:.1f}℃）")
        else:
            print("\n使用JSON数据（不包含额外随机扰动）")
        print("=" * 50 + "\n")

        # Lambda滑块回调
        def on_slider_change(val):
            nonlocal K, T, L
            new_pb, new_ti, new_td = self.identifier.lambda_tuning(K, T, L, val, mode=system_mode)
            pid.set_target_params(new_pb, new_ti, new_td)
            self.plot_manager.update_params_text(params_text, identified_params,
                                                 {'Pb': pid.target_pb, 'Ti': pid.target_ti, 'Td': pid.target_td},
                                                 val, params_update_count, initial_valid_params, pid_mode, system_mode,
                                                 tuning_method)

        lambda_slider.on_changed(on_slider_change)

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
            print(f"📊 仿真模式：从初始温度 {Config.INIT_TEMPERATURE}℃ 上升到目标温度 {setpoint}℃")

        # 为可视化新PID参数下的仿真轨迹，我们创建一个数组来存储仿真数据
        new_pid_time_data = []
        new_pid_temp_data = []
        new_pid_simulated = False  # 标记是否已开始新PID参数下的仿真

        # 初始化无PID控制的温度系统（用于对比）
        no_pid_system = TemperatureSystem(**true_params, mode=system_mode)
        # 记录初始温度
        no_pid_current_temp = current_temp
        # 使用初始输入信号模拟无PID控制的温度变化
        no_pid_input_signal = u[0] if len(u) > 0 else 25

        try:
            while True:  # 无限运行主循环
                # 如果使用JSON数据，则直接从数据中获取当前温度
                if using_json_data:
                    # 检查是否还有JSON数据可读取
                    if step < len(response_data):
                        # 从JSON数据中获取当前温度
                        current_temp = response_data[step]
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
                    valve_opening = pid.compute(setpoint, current_temp)
                    current_temp = system.update(valve_opening, time, disturbances=disturbances)

                # 计算无PID控制的温度变化（修正：使用固定输入信号）
                if using_json_data:
                    # 如果使用JSON数据，无PID控制的温度应该跟随输入信号
                    # 但为了与PID控制形成对比，我们使用一个固定输入信号
                    no_pid_input_signal = u[step] if step < len(u) else no_pid_input_signal
                else:
                    # 在仿真模式下，使用当前输入信号
                    no_pid_input_signal = u[step] if step < len(u) else 50.0

                # 使用相同输入信号但无PID控制更新无PID温度
                no_pid_current_temp = no_pid_system.update(no_pid_input_signal, time, disturbances=disturbances)
                no_pid_temp_data.append(no_pid_current_temp)

                error = setpoint - current_temp

                # 记录数据
                time_data.append(time)
                temp_data.append(current_temp)
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

                # 自动扰动检测逻辑（仅在未处于PID整定阶段时执行）
                if not in_pid_tuning_phase:  # 移除了 tuning_enabled 条件
                    # 使用优化的扰动检测算法
                    is_disturbance, disturbance_desc = state_analyzer.detect_instability_optimized(
                        temp_data, setpoint, valve_data, time_data
                    )

                    if is_disturbance:
                        # 检查当前时间是否在任何手动定义的扰动区间内（仅在仿真模式下）
                        current_disturbance = None
                        if not using_json_data:
                            current_disturbance = next((d for d in disturbances
                                                        if d["time"] <= time < d["time"] + d["duration"]), None)

                        if current_disturbance:
                            # 扰动开始后20s内强制更新参数（避免初期波动误判）
                            if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:
                                print(f"\n⚠️ 检测到[{current_disturbance['description']}]，自动重新整定参数...")
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
                                new_pb, new_ti, new_td = self._get_updated_params(K, T, L, lambda_val, tuning_method,
                                                                                  system_mode)

                                # 按扰动类型优化参数
                                new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(
                                    current_disturbance["type"], new_pb, new_ti, new_td)

                                # 执行参数更新（带平滑）
                                pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
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

                                # 开始基于新PID参数的仿真
                                new_pid_simulated = True
                                new_pid_time_data = [time]
                                new_pid_temp_data = [current_temp]

                        # 对于JSON数据，直接检测扰动并更新参数（不依赖预定义的扰动）
                        elif using_json_data:
                            print(f"\n⚠️ 检测到系统扰动，自动重新整定参数...")
                            self.logger.warning(f"检测到系统扰动，开始自动重新整定参数...")

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
                            new_pb, new_ti, new_td = self._get_updated_params(K, T, L, lambda_val, tuning_method,
                                                                              system_mode)

                            # 执行参数更新（带平滑）
                            pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)
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

                            # 开始基于新PID参数的仿真
                            new_pid_simulated = True
                            new_pid_time_data = [time]
                            new_pid_temp_data = [current_temp]

                # 在参数更新后，模拟新PID参数下的温度响应
                if new_pid_simulated and len(time_data) > len(new_pid_time_data):
                    # 使用新PID参数计算控制输出
                    new_pid_controller = PIDController(pb=pid.pb, ti=pid.ti, td=pid.td, dt=1, mode=pid_mode,
                                                       system_mode=system_mode)
                    new_valve_opening = new_pid_controller.compute(setpoint, new_pid_temp_data[-1])
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
                            print(f"🎉 {d['description']}已恢复稳定（{time:.0f}s），当前温度: {current_temp:.1f}℃")
                            self.logger.info(
                                f"扰动 {d['description']} 已恢复稳定 - 时间: {time:.0f}s, 温度: {current_temp:.1f}℃")

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

                    # 获取性能指标
                    iae, ise, control_effort = pid.get_performance_metrics()
                    print(
                        f"时间: {time:.0f}s | 系统模式: {Config.MODES[system_mode]} | PID模式: {Config.PID_MODES[pid_mode]} | 整定方法: {Config.TUNING_METHODS[tuning_method]} | 数据源: {'JSON' if using_json_data else '仿真'} | 实际响应温度: {current_temp:.1f}℃ | 无PID控制温度: {no_pid_current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
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
                f"当前实际响应温度：{current_temp:.1f}℃ | 无PID控制温度: {no_pid_current_temp:.1f}℃ | 误差：{error:.2f}℃")
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
            self.logger.info(f"中断时温度: {current_temp:.1f}℃, 误差: {error:.2f}℃, 更新次数: {params_update_count}")
            self.logger.info(f"中断时PID参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")
            self.logger.info(
                f"系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]}")

            plt.ioff()
            plt.close(fig)

    def _get_updated_params(self, K, T, L, lambda_val, tuning_method, system_mode):
        """根据整定方法获取更新后的PID参数"""
        if tuning_method == TuningMethod.LAMBDA:
            return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)
        elif tuning_method == TuningMethod.COHEN_COON:
            return self.identifier.cohen_coon_tuning(K, T, L)
        else:
            # 默认使用Lambda方法
            return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)

    def _adjust_pid_for_disturbance(self, disturbance_type, pb, ti, td):
        """根据扰动类型调整PID参数"""
        original_pb, original_ti, original_td = pb, ti, td

        if disturbance_type == DisturbanceType.OVERSHOOT:
            pb *= 1.1  # 增加比例带抑制超调
            print(f"🔧 超调优化：Pb提高10% → {pb:.2f}%")
        elif disturbance_type == DisturbanceType.STEADY_ERROR:
            ti *= 0.8  # 减小积分时间加速消除稳态误差
            print(f"🔧 稳态误差优化：Ti降低20% → {ti:.1f}s")
        elif disturbance_type == DisturbanceType.SLOW_RECOVERY:
            pb *= 0.9  # 减少比例带加速响应
            td *= 1.1  # 增加微分增益抑制震荡
            print(f"🔧 恢复优化：Pb降低10%，Td提高10% → {pb:.2f}%, {td:.1f}s")
        elif disturbance_type == DisturbanceType.VALVE_STICTION:
            pb *= 1.15  # 增加比例带减少阀门频繁动作
            ti *= 1.2  # 增加积分时间适应卡涩
            print(f"🔧 阀门卡涩优化：Pb提高15%，Ti提高20% → {pb:.2f}%, {ti:.1f}s")
        elif disturbance_type == DisturbanceType.SENSOR_DRIFT:
            td *= 1.3  # 增加微分作用补偿漂移
            print(f"🔧 传感器漂移优化：Td提高30% → {td:.1f}s")
        elif disturbance_type == DisturbanceType.HEAT_LOSS:
            pb *= 0.85  # 降低比例带补偿热损失
            ti *= 0.85  # 减少积分时间加快响应
            print(f"🔧 热损失优化：Pb降低15%，Ti降低15% → {pb:.2f}%, {ti:.1f}s")
        elif disturbance_type == DisturbanceType.CONTROL_VALVE_WEAR:
            pb *= 1.2  # 增加比例带适应磨损
            td *= 0.9  # 微调微分
            print(f"🔧 控制阀磨损优化：Pb提高20%，Td降低10% → {pb:.2f}%, {td:.1f}s")
        elif disturbance_type == DisturbanceType.THERMAL_INERTIA:
            ti *= 1.2  # 增加积分时间适应惯性
            td *= 1.2  # 增加微分时间
            print(f"🔧 热惯性优化：Ti/Td提高20% → {ti:.1f}s, {td:.1f}s")

        # 应用全局参数边界保护
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)
        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)

        return pb, ti, td


if __name__ == "__main__":
    monitor = ControlMonitor()
    monitor.run()



