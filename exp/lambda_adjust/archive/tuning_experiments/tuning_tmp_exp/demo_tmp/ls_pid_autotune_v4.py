import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares


# ==============================
# 1. 配置模块
# ==============================
class Config:
    """系统配置参数集中管理"""
    # 温度参数
    INIT_TEMPERATURE = 380.0
    TARGET_TEMPERATURE = 400.0

    # 稳态判断参数
    STABILIZATION_THRESHOLD = 0.8       # 温度波动允许阈值(℃)
    STABILIZATION_WINDOW = 50           # 稳态判断窗口大小

    # 扰动配置
    DISTURBANCES = [
        {"time": 350, "type": "overshoot", "duration": 70, "amplitude": 2, "description": "超调量大"},
        {"time": 1200, "type": "steady_error", "duration": 180, "amplitude": 2, "description": "稳态误差变大"},
        {"time": 2000, "type": "slow_recovery", "duration": 120, "amplitude": 1, "description": "恢复时间延长"},
        {"time": 2700, "type": "steady_error", "duration": 90, "amplitude": 1, "description": "稳态误差变大"}
    ]

    # 系统老化与辨识参数
    AGING_START_TIME = 300          # 老化开始时间(s)
    IDENTIFY_WINDOW = 200           # 参数辨识窗口大小(点数)
    PARAM_UPDATE_SMOOTH_FACTOR = 0.2  # 参数更新平滑因子

    # 仿真与存储参数
    SIMULATION_DURATION = 3200  # 仿真总时长(s)
    DATA_SAVE_DIR = "../../data_simulation/data_generation"  # 数据保存目录
    PLOT_REFRESH_INTERVAL = 8  # 绘图刷新间隔(步)

    @classmethod
    def ensure_data_dir(cls):
        """确保数据目录存在"""
        os.makedirs(cls.DATA_SAVE_DIR, exist_ok=True)


# ==============================
# 2. 数据处理模块（数据读写与生成）
# ==============================
class DataHandler:
    """数据处理工具：读取、生成、选择数据源"""

    @staticmethod
    def read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)"):
        """读取CSV格式的温度数据"""
        try:
            df = pd.read_csv(file_path)
            if time_col not in df.columns or data_col not in df.columns:
                raise ValueError(f"CSV文件必须包含列：'{time_col}' 和 '{data_col}'")
            df = df.dropna(subset=[time_col, data_col])
            t = df[time_col].values
            data = df[data_col].values
            if not np.all(np.diff(t) >= 0):
                raise ValueError("时间序列必须单调递增，请检查数据")

            print(f"✅ 成功读取数据：{file_path}")
            print(f"📊 数据范围：{t.min():.0f}s ~ {t.max():.0f}s，共{len(t)}个点")
            return t, data

        except FileNotFoundError:
            print(f"❌ 错误：未找到文件 '{file_path}'")
            exit(1)
        except Exception as e:
            print(f"❌ 读取失败：{str(e)}")
            exit(1)

    @staticmethod
    def choose_data_source(data_type="dynamic_response"):
        """选择数据来源（仿真生成或读取CSV）"""
        print(f"\n=== 选择{data_type}数据来源 ===")
        print("1. 自动生成非阶跃仿真数据（默认）")
        print("2. 读取外部CSV数据")

        while True:
            choice = input("请输入选择（1/2，直接回车选1）：").strip() or "1"
            if choice == "1":
                t = np.arange(0, Config.SIMULATION_DURATION, 1)  # 1s间隔的时间序列
                return t, None
            elif choice == "2":
                file_path = input(f"请输入{data_type}CSV路径（如'./data.csv'）：").strip()
                if not file_path:
                    print("❌ 路径不能为空，请重新输入")
                    continue
                if data_type == "dynamic_response":
                    return DataHandler.read_csv_data(file_path, time_col="时间(s)", data_col="动态响应温度(℃)")
                else:
                    return DataHandler.read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)")
            else:
                print("❌ 输入错误，请选择1或2")

    @staticmethod
    def save_data(data, columns, filename):
        """保存数据到CSV"""
        save_path = os.path.join(Config.DATA_SAVE_DIR, filename)
        np.savetxt(
            save_path,
            data,
            delimiter=",",
            header=",".join(columns),
            comments=""
        )
        print(f"数据已保存至：{save_path}")
        return save_path


# ==============================
# 3. 系统模型模块（温度系统动态特性）
# ==============================
class TemperatureSystem:
    """温度系统模型：模拟温度动态响应、老化和扰动"""

    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3):
        self.initial_K = K
        self.initial_T = T
        self.initial_L = L
        self.K = K  # 当前增益
        self.T = T  # 当前时间常数
        self.L = L  # 当前滞后时间
        self.noise_level = noise_level

        # 状态变量
        self.last_temp = Config.INIT_TEMPERATURE
        self.buffer = np.ones(int(np.ceil(L))) * self.last_temp

    def apply_aging(self, time):
        """应用老化对系统参数的影响"""
        if time < Config.AGING_START_TIME:
            return

        # 老化因子（最大变化80%）
        aging_factor = min(0.002 * (time - Config.AGING_START_TIME), 0.8)
        self.K = self.initial_K * (1 - aging_factor * 0.4)  # 增益降低
        self.T = self.initial_T * (1 + aging_factor * 0.8)  # 时间常数增大
        self.L = self.initial_L * (1 + aging_factor * 0.9)  # 滞后时间增加

        # 动态调整滞后缓冲器大小
        new_buffer_size = int(np.ceil(self.L))
        if len(self.buffer) != new_buffer_size:
            self.buffer = np.ones(new_buffer_size) * self.last_temp

    def add_disturbance(self, time, current_temp):
        """添加扰动对温度的影响"""
        for disturbance in Config.DISTURBANCES:
            start = disturbance["time"]
            end = disturbance["time"] + disturbance["duration"]
            if start <= time < end:
                if disturbance["type"] == "overshoot":
                    decay = 1 - (time - start) / disturbance["duration"]
                    return current_temp + disturbance["amplitude"] * (1.2 - decay) + np.random.normal(0, 1.2)
                elif disturbance["type"] == "steady_error":
                    turbulent = np.sin((time - start) * 0.1) * disturbance["amplitude"] * 0.3
                    return current_temp + disturbance["amplitude"] + turbulent + np.random.normal(0, 0.9)
                elif disturbance["type"] == "slow_recovery":
                    fluctuation = np.sin((time - start) * 0.2) * disturbance["amplitude"] * 0.8
                    return current_temp + fluctuation + np.random.normal(0, 1.3)
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

    def simulate_with_input(self, t, u):
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
            output_temp = self.add_disturbance(t[i], output_temp)
            output_temp += np.random.normal(0, self.noise_level)
            temp[i] = output_temp

        return temp

    def update(self, valve_opening, time, dt=1):
        """实时更新系统温度"""
        self.apply_aging(time)
        steady_state = Config.INIT_TEMPERATURE + valve_opening * self.K
        self.last_temp += (steady_state - self.last_temp) / self.T * dt

        # 处理滞后
        self.buffer = np.roll(self.buffer, 1)
        self.buffer[0] = self.last_temp
        output_temp = self.buffer[-1] if len(self.buffer) > 0 else self.last_temp

        # 添加扰动和噪声
        output_temp = self.add_disturbance(time, output_temp)
        output_temp += np.random.normal(0, self.noise_level)
        return output_temp


# ==============================
# 4. 控制器模块（PID控制逻辑）
# ==============================
class PIDController:
    """PID控制器：实现PID控制与参数平滑更新"""

    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100):
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
        self.smoothing_factor = Config.PARAM_UPDATE_SMOOTH_FACTOR  # 平滑因子

    def compute(self, setpoint, process_var):
        """计算PID输出（含抗积分饱和）"""
        error = setpoint - process_var
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
        if self.Td > 1e-6 and self.last_error != 0:
            self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * self.Td) * (error - self.last_error) / self.dt

        # 总输出与限幅
        output = proportional + self.integral + self.derivative
        output = np.clip(output, self.u_min, self.u_max)
        self.last_error = error

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


# ==============================
# 5. 辨识与整定模块（系统建模与参数计算）
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
    def lambda_tuning(K, T, L, lambda_val=None):
        """基于Lambda方法整定PID参数"""
        if lambda_val is None:
            lambda_val = T * 0.8

        denominator = K * (lambda_val + L / 2)
        if denominator < 1e-6:
            return 1.0, 20.0, 1.0  # 异常时返回默认安全值

        # pid参数计算
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > 1e-6 else 0.0

        # 参数限幅
        Kp = np.clip(Kp, 0.5, 6.0)
        Ti = np.clip(Ti, 8.0, 120.0)
        Td = np.clip(Td, 0.0, 25.0)
        return Kp, Ti, Td


# ==============================
# 6. 状态分析模块（系统稳定性与扰动检测）
# ==============================
class StateAnalyzer:
    """系统状态分析工具：判断稳定性与扰动"""

    @staticmethod
    def is_stable(temp_data, setpoint):
        """判断系统是否稳定在目标温度附近"""
        if len(temp_data) < Config.STABILIZATION_WINDOW:
            return False
        recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])
        # 均值需接近目标温度（±0.5℃）
        mean_temp = np.mean(recent_temps)
        if not (setpoint - 0.5 <= mean_temp <= setpoint + 0.5):
            return False
        # 波动判断
        deviations = np.abs(recent_temps - setpoint)
        return (np.all(deviations < Config.STABILIZATION_THRESHOLD) and
                np.std(deviations) < Config.STABILIZATION_THRESHOLD / 2)

    @staticmethod
    def detect_instability(temp_data, setpoint, valve_data, window=80):
        """检测系统不稳定性（超调、稳态误差、恢复缓慢）"""
        if len(temp_data) < window:
            return False, ""

        recent_temps = np.array(temp_data[-window:])
        deviations = recent_temps - setpoint

        # 1. 超调量大检测
        overshoot = np.max(deviations)
        if overshoot > 2.0:
            return True, f"超调量大({overshoot:.1f}℃)"

        # 2. 稳态误差变大检测
        steady_error = np.abs(np.mean(deviations))
        if steady_error > 2.5:
            return True, f"稳态误差变大({steady_error:.1f}℃)"

        # 3. 恢复时间变久检测
        recent_valves = np.array(valve_data[-window:])
        valve_changes = np.sum(np.abs(np.diff(recent_valves)))
        if valve_changes > 180 and steady_error > 2.0:
            return True, "恢复时间延长"

        return False, ""


# ==============================
# 7. 可视化模块（绘图与交互）
# ==============================
class Visualizer:
    """可视化工具：初始化图表、更新绘图与参数显示"""

    def __init__(self):
        # 确保中文显示
        plt.rcParams["font.family"] = ["Heiti TC"]
        plt.rcParams['axes.unicode_minus'] = False
        self.fig = None
        self.plot_data = None

    def init_real_time_fig(self, t, u, setpoint, system_params, pid_params, response_data):
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
        ax1.set_title('系统响应与辨识模型对比')
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
        disturbance_colors = {"overshoot": "red", "steady_error": "orange", "slow_recovery": "brown"}
        for d in Config.DISTURBANCES:
            ax2.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]],
                        alpha=0.2, label=f'{d["description"]} ({d["time"]}s)')

        ax2.set_title('温度控制曲线（含扰动与参数更新）')
        ax2.set_xlabel('时间 (s)')
        ax2.set_ylabel('温度 (℃)')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)
        temp_line, = ax2.plot([], [], 'b-', label='实际温度', linewidth=1.5)
        stabilization_line = ax2.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
        update_lines = []  # 参数更新线
        update_marker, = ax2.plot([], [], 'bo', markersize=6, label='参数更新点')

        # 4. 阀门开度曲线
        ax3 = self.fig.add_subplot(gs[3, 0])
        ax3.set_xlim(0, t[-1] * 1.2)
        ax3.set_ylim(0, 100)
        for d in Config.DISTURBANCES:
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
        for d in Config.DISTURBANCES:
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
        for d in Config.DISTURBANCES:
            ax5.axvspan(d["time"], d["time"] + d["duration"], color=disturbance_colors[d["type"]], alpha=0.2)
        ax5.set_title('PID参数变化趋势')
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
        self.update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'])

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
            'lines': (temp_line, valve_line, error_line, kp_line, ti_line, td_line),
            'text': params_text,
            'slider': lambda_slider,
            'markers': (stabilization_line, update_lines, update_marker),
            'colors': disturbance_colors
        }
        return self.fig, self.plot_data

    @staticmethod
    def update_params_text(text_obj, system_params, pid_params, lambda_val, update_count=0, initial_params=None):
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

{initial_text}当前PID参数 {status}(λ={lambda_val:.1f}):
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

目标温度: {Config.TARGET_TEMPERATURE}℃ | 初始温度: {Config.INIT_TEMPERATURE}℃"""
        text_obj.set_text(text)

    def update_plots(self, time_data, temp_data, valve_data, error_data, kp_data, ti_data, td_data, update_lines):
        """实时更新绘图数据"""
        (temp_line, valve_line, error_line, kp_line, ti_line, td_line) = self.plot_data['lines']
        (ax2, _, _, _) = self.plot_data['axes']
        _, _, update_marker = self.plot_data['markers']

        # 更新曲线数据
        temp_line.set_data(time_data, temp_data)
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
        self.fig.canvas.draw_idle()
        plt.pause(0.01)


# ==============================
# 8. 主控制模块（协调各模块运行）
# ==============================
class ControlMonitor:

    """控制监控主逻辑：协调系统、控制器、辨识器等模块运行"""

    def __init__(self):
        self.data_handler = DataHandler()
        self.visualizer = Visualizer()
        self.identifier = SystemIdentifier()
        self.state_analyzer = StateAnalyzer()

    def run(self):
        """启动控制监控流程"""
        # 初始化配置
        Config.ensure_data_dir()

        # 选择数据来源
        t, response_data = self.data_handler.choose_data_source(data_type="dynamic_response")

        # 初始化系统与输入
        initial_true_params = {'K': 0.8, 'T': 30, 'L': 4, 'noise_level': 0.3}
        temp_system = TemperatureSystem(**initial_true_params)

        # 生成仿真数据（如未提供）
        if response_data is None:
            u = temp_system.generate_non_step_input(t)
            response_data = temp_system.simulate_with_input(t, u)
            # 保存生成的数据
            save_path = os.path.join(Config.DATA_SAVE_DIR, "dynamic_response_data.csv")
            pd.DataFrame({
                "时间(s)": t,
                "输入信号(%)": u,
                "动态响应温度(℃)": response_data
            }).to_csv(save_path, index=False)
            print(f"\n生成非阶跃数据并保存至：{save_path}")
        else:
            u = temp_system.generate_non_step_input(t)

        # 初始参数辨识
        print(f"\n全局初始温度：{Config.INIT_TEMPERATURE}℃ | 目标温度：{Config.TARGET_TEMPERATURE}℃")
        print("正在辨识系统初始参数（K, T, L）...")
        K, T, L = self.identifier.identify_fopdt(t, response_data, u)
        identified_params = {'K': K, 'T': T, 'L': L}

        # 启动实时监控
        print("\n启动温度控制监控...")
        self._run_real_time_monitor(t, u, Config.TARGET_TEMPERATURE, initial_true_params, identified_params, response_data)

    def _run_real_time_monitor(self, t, u, setpoint, true_params, identified_params, response_data):
        """实时监控主循环"""
        # 初始化图表
        fig, plot_data = self.visualizer.init_real_time_fig(t, u, setpoint, identified_params,
                                                           {'Kp': 0, 'Ti': 0, 'Td': 0}, response_data)
        (ax2, _, _, _) = plot_data['axes']
        params_text = plot_data['text']
        lambda_slider = plot_data['slider']
        stabilization_line, update_lines, _ = plot_data['markers']

        # 数据存储列表
        time_data = []
        temp_data = []
        valve_data = []
        error_data = []
        kp_data = []
        ti_data = []
        td_data = []

        # 初始化系统与控制器
        K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
        init_Kp, init_Ti, init_Td = self.identifier.lambda_tuning(K, T, L)
        system = TemperatureSystem(**true_params)
        pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
        current_temp = Config.INIT_TEMPERATURE

        # 状态变量
        stabilization_time = None
        tuning_enabled = False
        params_update_count = 0
        initial_valid_params = None  # 初始有效参数记录
        recovery_status = {d["type"]: False for d in Config.DISTURBANCES}

        # 为扰动添加更新标记属性
        for d in Config.DISTURBANCES:
            d['updated'] = False  # 标记是否已更新参数

        # 打印初始信息
        print("\n" + "=" * 50)
        print("初始系统参数辨识结果：")
        print(f"静态增益 K = {K:.2f} ℃/% | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s")
        print(f"初始PID参数：Kp={init_Kp:.2f}, Ti={init_Ti:.1f}s, Td={init_Td:.1f}s")
        print("\n扰动计划：")
        for d in Config.DISTURBANCES:
            print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s）")
        print("=" * 50 + "\n")

        # Lambda滑块回调
        def on_slider_change(val):
            nonlocal K, T, L
            new_Kp, new_Ti, new_Td = self.identifier.lambda_tuning(K, T, L, val)
            pid.set_target_params(new_Kp, new_Ti, new_Td)
            self.visualizer.update_params_text(params_text, identified_params,
                                              {'Kp': pid.target_Kp, 'Ti': pid.target_Ti, 'Td': pid.target_Td},
                                              val, params_update_count, initial_valid_params)

        lambda_slider.on_changed(on_slider_change)

        try:
            for i, time in enumerate(t):
                # 计算控制输出与当前温度
                valve_opening = pid.compute(setpoint, current_temp)
                current_temp = system.update(valve_opening, time)
                error = setpoint - current_temp

                # 记录数据
                time_data.append(time)
                temp_data.append(current_temp)
                valve_data.append(valve_opening)
                error_data.append(error)
                kp_data.append(pid.Kp)
                ti_data.append(pid.Ti / 10)  # 缩放显示
                td_data.append(pid.Td * 2)  # 缩放显示

                # 检测初始稳态（达到目标温度后开启整定）
                if stabilization_time is None and self.state_analyzer.is_stable(temp_data, setpoint):
                    stabilization_time = time
                    stabilization_line.set_xdata([time])
                    tuning_enabled = True
                    initial_valid_params = (pid.Kp, pid.Ti, pid.Td)  # 记录初始有效参数
                    print(f"✅ 系统达到初始稳态（{time:.0f}s），开启自整定功能")
                    print(f"初始有效PID参数：Kp={initial_valid_params[0]:.2f}, Ti={initial_valid_params[1]:.1f}s, Td={initial_valid_params[2]:.1f}s")
                    self.visualizer.update_params_text(params_text, identified_params,
                                                      {'Kp': pid.Kp, 'Ti': pid.Ti, 'Td': pid.Td},
                                                      lambda_slider.val, params_update_count, initial_valid_params)

                # 扰动检测与强制更新
                current_disturbance = next((d for d in Config.DISTURBANCES
                                            if d["time"] <= time < d["time"] + d["duration"]), None)
                if current_disturbance and tuning_enabled:
                    # 扰动开始后20s内强制更新参数（避免初期波动误判）
                    if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:
                        print(f"\n⚠️ 检测到[{current_disturbance['description']}]，强制重新整定参数...")

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
                        new_Kp, new_Ti, new_Td = self.identifier.lambda_tuning(K, T, L, lambda_val)

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

                        # 执行参数更新（带平滑）
                        pid.set_target_params(new_Kp, new_Ti, new_Td, reset_integral=True)
                        update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
                        update_lines.append(update_line)
                        params_update_count += 1
                        current_disturbance['updated'] = True  # 标记已更新

                        # 打印参数变化（旧→新）
                        print(f"参数更新 {params_update_count} 次：")
                        print(f"Kp: {pid.Kp:.2f} → {new_Kp:.2f}")
                        print(f"Ti: {pid.Ti:.1f}s → {new_Ti:.1f}s")
                        print(f"Td: {pid.Td:.1f}s → {new_Td:.1f}s\n")
                        self.visualizer.update_params_text(params_text, identified_params,
                                                          {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td},
                                                          lambda_val, params_update_count, initial_valid_params)

                # 扰动后恢复判断
                for d in Config.DISTURBANCES:
                    if (d['updated'] and not recovery_status[d["type"]] and
                            time > d["time"] + d["duration"] + 40):  # 扰动结束后40s判断
                        if self.state_analyzer.is_stable(temp_data, setpoint):
                            recovery_status[d["type"]] = True
                            print(f"🎉 {d['description']}已恢复稳定（{time:.0f}s），当前温度: {current_temp:.1f}℃")

                # 定期打印状态（每50步）
                if i % 50 == 0:
                    stable_status = "已稳态" if stabilization_time else "暂稳态"
                    recovery_text = ", ".join([f"{d['description']}:{'已恢复' if recovery_status[d['type']] else '恢复中'}"
                                               for d in Config.DISTURBANCES])
                    print(f"时间: {time:.0f}s | 温度: {current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                          f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {params_update_count}次")

                # 批量更新绘图
                if i % Config.PLOT_REFRESH_INTERVAL == 0:
                    self.visualizer.update_plots(time_data, temp_data, valve_data, error_data,
                                                kp_data, ti_data, td_data, update_lines)

            # 保存数据
            real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data,
                                              kp_data, ti_data, td_data))
            self.data_handler.save_data(real_time_data,
                                       ["时间(s)", "温度(℃)", "阀门开度(%)", "误差(℃)", "Kp", "Ti/10", "Td*2"],
                                       "real_time_control_data.csv")

            # 结束信息
            print("\n" + "=" * 50)
            print(f"初始温度：{Config.INIT_TEMPERATURE}℃ → 目标：{setpoint}℃")
            print(f"最终温度：{current_temp:.1f}℃ | 最终误差：{error:.2f}℃")
            print(f"初始有效参数 → 最终参数：")
            print(f"Kp: {initial_valid_params[0]:.2f} → {pid.Kp:.2f}")
            print(f"Ti: {initial_valid_params[1]:.1f}s → {pid.Ti:.1f}s")
            print(f"Td: {initial_valid_params[2]:.1f}s → {pid.Td:.1f}s")
            print(f"总更新次数：{params_update_count}次")
            print("=" * 50)

            plt.ioff()
            plt.show()

        except KeyboardInterrupt:
            # 中断时保存数据
            if len(time_data) > 0:
                real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
                self.data_handler.save_data(real_time_data,
                                           ["时间(s)", "温度(℃)", "阀门开度(%)", "误差(℃)"],
                                           "real_time_control_data_interrupted.csv")
            print("\n" + "=" * 50)
            print("监控手动终止")
            print(f"当前温度：{current_temp:.1f}℃ | 误差：{error:.2f}℃")
            print(f"初始有效参数 → 当前参数：")
            print(f"Kp: {initial_valid_params[0]:.2f} → {pid.Kp:.2f}")
            print(f"Ti: {initial_valid_params[1]:.1f}s → {pid.Ti:.1f}s")
            print(f"Td: {initial_valid_params[2]:.1f}s → {pid.Td:.1f}s")
            print(f"总更新次数：{params_update_count}次")
            print("=" * 50)
            plt.ioff()
            plt.close(fig)


if __name__ == "__main__":
    monitor = ControlMonitor()
    monitor.run()