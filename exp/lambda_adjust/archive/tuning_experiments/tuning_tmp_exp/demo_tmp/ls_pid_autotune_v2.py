import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares


class Config:
    """系统配置参数集中管理"""
    # 温度参数
    INIT_TEMPERATURE = 380.0
    TARGET_TEMPERATURE = 400.0

    # 稳态判断参数
    STABILIZATION_THRESHOLD = 1     # 温度波动允许阈值(℃)
    STABILIZATION_WINDOW = 30       # 稳态判断窗口大小

    # 扰动配置
    DISTURBANCES = [
        {"time": 400, "type": "overshoot", "duration": 70, "amplitude": 2, "description": "超调量大"},
        {"time": 1000, "type": "steady_error", "duration": 150, "amplitude": 5, "description": "稳态误差变大"},
        {"time": 1800, "type": "slow_recovery", "duration": 100, "amplitude": 6, "description": "恢复时间延长"},
        {"time": 2600, "type": "steady_error", "duration": 60, "amplitude": 3, "description": "稳态误差变大"}

    ]

    # 系统老化与辨识参数
    AGING_START_TIME = 150  # 老化开始时间(s)
    IDENTIFY_WINDOW = 150  # 参数辨识窗口大小(点数)
    PARAM_UPDATE_SMOOTH_FACTOR = 0.3 # 参数平滑更新因子

    # 仿真与存储参数
    SIMULATION_DURATION = 3000  # 仿真总时长(s)
    DATA_SAVE_DIR = "../data_generation"  # 数据保存目录
    PLOT_REFRESH_INTERVAL = 10  # 绘图刷新间隔(步)，减少刷新频率提升性能


# 确保中文显示正常
plt.rcParams["font.family"] = ["Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False

# 确保数据保存目录存在
os.makedirs(Config.DATA_SAVE_DIR, exist_ok=True)


def read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)"):
    """
    读取CSV格式的温度数据

    参数:
        file_path: CSV文件路径
        time_col: 时间列名
        data_col: 温度数据列名

    返回:
        t: 时间序列数组
        data: 温度数据数组
    """
    try:
        df = pd.read_csv(file_path)
        # 检查必要列
        if time_col not in df.columns or data_col not in df.columns:
            raise ValueError(f"CSV文件必须包含列：'{time_col}' 和 '{data_col}'")
        # 去除空值
        df = df.dropna(subset=[time_col, data_col])
        t = df[time_col].values
        data = df[data_col].values
        # 检查时间序列单调性
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


def choose_data_source(data_type="dynamic_response"):
    """
    选择数据来源（仿真生成或读取CSV）

    参数:
        data_type: 数据类型标识

    返回:
        t: 时间序列
        response_data: 温度响应数据（None表示需要生成）
    """
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
                return read_csv_data(file_path, time_col="时间(s)", data_col="动态响应温度(℃)")
            else:
                return read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)")
        else:
            print("❌ 输入错误，请选择1或2")


class TemperatureSystem:
    """温度系统模型（基于一阶加纯滞后FOPDT模型）"""

    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3):
        """
        初始化温度系统参数

        参数:
            K: 静态增益 (℃/%)
            T: 时间常数 (s)
            L: 滞后时间 (s)
            noise_level: 噪声水平
        """

        self.initial_K = K
        self.initial_T = T
        self.initial_L = L
        self.K = K  # 当前增益
        self.T = T  # 当前时间常数
        self.L = L  # 当前滞后时间
        self.noise_level = noise_level

        # 状态变量
        self.last_temp = Config.INIT_TEMPERATURE  # 上一时刻温度
        self.buffer = np.ones(int(np.ceil(L))) * self.last_temp  # 滞后缓冲器

    def apply_aging(self, time):
        """随时间应用设备老化效应，修改系统参数"""
        if time < Config.AGING_START_TIME:
            return

        # 老化因子（最大变化50%）
        aging_factor = min(0.0012 * (time - Config.AGING_START_TIME), 0.5)
        self.K = self.initial_K * (1 - aging_factor * 0.25)  # 增益降低
        self.T = self.initial_T * (1 + aging_factor * 0.5)  # 时间常数增大
        self.L = self.initial_L * (1 + aging_factor * 0.6)  # 滞后时间增加

        # 动态调整滞后缓冲器大小（滞后时间变化时）
        new_buffer_size = int(np.ceil(self.L))
        if len(self.buffer) != new_buffer_size:
            self.buffer = np.ones(new_buffer_size) * self.last_temp

    def add_disturbance(self, time, current_temp):
        """
        为当前温度添加扰动

        参数:
            time: 当前时间
            current_temp: 无扰动时的温度

        返回:
            带扰动的温度
        """
        for disturbance in Config.DISTURBANCES:
            start = disturbance["time"]
            end = disturbance["time"] + disturbance["duration"]
            if start <= time < end:
                if disturbance["type"] == "overshoot":
                    # 超调扰动：随时间衰减
                    decay = 1 - (time - start) / disturbance["duration"]
                    return current_temp + disturbance["amplitude"] * decay + np.random.normal(0, 1)
                elif disturbance["type"] == "steady_error":
                    # 稳态误差：持续偏移
                    return current_temp + disturbance["amplitude"] + np.random.normal(0, 0.8)
                elif disturbance["type"] == "slow_recovery":
                    # 恢复缓慢：正弦波动
                    fluctuation = np.sin((time - start) * 0.3) * disturbance["amplitude"] * 0.7
                    return current_temp + fluctuation + np.random.normal(0, 1.2)
        return current_temp

    def generate_non_step_input(self, t):
        """生成非阶跃输入信号（阀门开度，0-100%）"""
        u = np.zeros_like(t, dtype=np.float64)
        # 分段阶梯输入
        u[t >= 50] += 30.0
        u[t >= 150] += 20.0
        u[t >= 250] -= 10.0
        u[t >= 350] += 30.0
        u[t >= 450] -= 25.0
        # 添加随机噪声并限制范围
        u += np.random.normal(0, 2, size=len(t))
        return np.clip(u, 0, 100)

    def simulate_with_input(self, t, u):
        """
        基于输入信号仿真温度响应

        参数:
            t: 时间序列
            u: 输入信号（阀门开度）

        返回:
            温度响应序列
        """
        temp = np.ones_like(t) * Config.INIT_TEMPERATURE
        self.last_temp = Config.INIT_TEMPERATURE
        self.buffer = np.ones(int(np.ceil(self.L))) * self.last_temp

        for i in range(len(t)):
            self.apply_aging(t[i])
            dt = t[i] - t[i - 1] if i > 0 else 1  # 时间步长
            steady_state = Config.INIT_TEMPERATURE + u[i] * self.K  # 稳态目标
            self.last_temp += (steady_state - self.last_temp) / self.T * dt  # 温度变化

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
        """
        实时更新系统温度

        参数:
            valve_opening: 当前阀门开度
            time: 当前时间
            dt: 时间步长

        返回:
            当前温度
        """
        self.apply_aging(time)
        steady_state = Config.INIT_TEMPERATURE + valve_opening * self.K
        self.last_temp += (steady_state - self.last_temp) / self.T * dt  # 温度变化

        # 处理滞后
        self.buffer = np.roll(self.buffer, 1)
        self.buffer[0] = self.last_temp
        output_temp = self.buffer[-1] if len(self.buffer) > 0 else self.last_temp

        # 添加扰动和噪声
        output_temp = self.add_disturbance(time, output_temp)
        output_temp += np.random.normal(0, self.noise_level)
        return output_temp


class PIDController:
    """PID控制器（带参数平滑更新和抗积分饱和）"""

    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100):
        """
        初始化PID控制器

        参数:
            Kp: 比例增益
            Ti: 积分时间 (s)
            Td: 微分时间 (s)
            dt: 控制周期 (s)
            u_min/u_max: 输出上下限
        """
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
        self.smoothing_factor = Config.PARAM_UPDATE_SMOOTH_FACTOR  # 参数平滑因子

    def compute(self, setpoint, process_var):
        """
        计算PID输出

        参数:
            setpoint: 目标值
            process_var: 过程变量（当前温度）

        返回:
            控制输出（阀门开度）
        """
        error = setpoint - process_var
        proportional = self.Kp * error

        # 积分项（抗积分饱和：输出饱和时停止积分）
        if self.Ti > 1e-6:  # 避免除零
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

        # 平滑更新参数（渐进式调整）
        self._smooth_update()
        return output

    def _smooth_update(self):
        """平滑更新PID参数，避免突变"""
        self.Kp += self.smoothing_factor * (self.target_Kp - self.Kp)
        self.Ti += self.smoothing_factor * (self.target_Ti - self.Ti)
        self.Td += self.smoothing_factor * (self.target_Td - self.Td)

    def set_target_params(self, Kp, Ti, Td, reset_integral=False):
        """设置目标参数（用于后续平滑更新）"""
        self.target_Kp = Kp
        self.target_Ti = Ti
        self.target_Td = Td
        if reset_integral:
            self.integral = 0.0  # 参数更新时重置积分项，避免累积误差

    def reset(self):
        """重置控制器状态"""
        self.last_error = 0.0
        self.integral = 0.0
        self.derivative = 0.0


def fopdt_model(params, t, u, y0):
    """
    一阶加纯滞后（FOPDT）模型：dy/dt = (K*u_delay - (y - y0)) / T

    参数:
        params: (K, T, L) 增益、时间常数、滞后时间
        t: 时间序列
        u: 输入序列
        y0: 初始值

    返回:
        模型预测的输出序列
    """
    K, T, L = params
    y = np.ones_like(t) * y0
    L_int = int(np.round(L))  # 滞后时间（整数化）

    # 向量化计算（替代循环，提升性能）
    for i in range(len(t)):
        dt = t[i] - t[i - 1] if i > 0 else 1
        u_delay = u[max(0, i - L_int)]  # 滞后输入
        y[i] = y[i - 1] + (K * u_delay - (y[i - 1] - y0)) / T * dt

    return y


def residuals(params, t, u, y_measured, y0):
    """最小二乘优化的残差函数（预测值 - 测量值）"""
    y_predicted = fopdt_model(params, t, u, y0)
    return y_predicted - y_measured


def identify_fopdt_least_squares(t, y, u):
    """
    用最小二乘法辨识FOPDT模型参数 (K, T, L)

    参数:
        t: 时间序列
        y: 测量输出（温度）
        u: 输入（阀门开度）

    返回:
        K, T, L: 辨识的模型参数
    """
    # 初始值估计
    y0 = np.mean(y[-20:]) if len(y) > 20 else np.mean(y)  # 稳态初始值
    max_u = np.max(u)
    max_y = np.max(y)
    gain_guess = (max_y - y0) / max_u if max_u > 1e-6 else 0.5  # 增益估计

    # 初始猜测与参数边界
    initial_guess = [
        max(gain_guess, 0.1),  # K（确保最小值）
        30.0,  # T
        5.0  # L
    ]
    bounds = ([0.05, 5.0, 0.0], [1.5, 150.0, 20.0])  # 参数上下限

    try:
        # 最小二乘优化
        result = least_squares(
            residuals,
            initial_guess,
            args=(t, u, y, y0),
            bounds=bounds,
            verbose=0
        )
        K, T, L = result.x
    except Exception as e:
        print(f"⚠️ 参数辨识失败：{e}，使用初始猜测值")
        K, T, L = initial_guess  # 失败时使用初始猜测

    # 确保参数在合理范围
    K = np.clip(K, 0.05, 1.5)
    T = np.clip(T, 5.0, 150.0)
    L = np.clip(L, 0.0, 20.0)
    return K, T, L


def lambda_tuning(K, T, L, lambda_val=None):
    """
    基于Lambda方法整定PID参数

    参数:
        K, T, L: FOPDT模型参数
        lambda_val: 闭环时间常数（影响响应速度）

    返回:
        Kp, Ti, Td: PID参数
    """
    if lambda_val is None:
        lambda_val = T * 0.3

    # 避免除零
    denominator = K * (lambda_val + L / 2)
    if denominator < 1e-6:
        return 1.0, 20.0, 1.0  # 异常时返回默认安全值

    Kp = (T + L / 2) / denominator
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) > 1e-6 else 0.0

    # 参数限幅
    Kp = np.clip(Kp, 0.5, 5.0)
    Ti = np.clip(Ti, 10.0, 100.0)
    Td = np.clip(Td, 0.0, 20.0)
    return Kp, Ti, Td


def is_stable(temp_data, setpoint):
    """判断系统是否达到稳态"""
    if len(temp_data) < Config.STABILIZATION_WINDOW:
        return False
    recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])
    deviations = np.abs(recent_temps - setpoint)
    return (np.all(deviations < Config.STABILIZATION_THRESHOLD) and
            np.std(deviations) < Config.STABILIZATION_THRESHOLD / 2)


def detect_instability(temp_data, setpoint, valve_data, window=80):
    """检测系统不稳定性（超调、稳态误差、恢复缓慢）"""
    if len(temp_data) < window:
        return False, ""

    recent_temps = np.array(temp_data[-window:])
    deviations = recent_temps - setpoint

    # 超调检测
    overshoot = np.max(deviations)
    if overshoot > 2.0:
        return True, f"超调过大({overshoot:.1f}℃)"

    # 稳态误差检测
    steady_error = np.abs(np.mean(deviations))
    if steady_error > 2.0:
        return True, f"稳态误差过大({steady_error:.1f}℃)"

    # 恢复缓慢检测（阀门频繁调整但误差未减小）
    recent_valves = np.array(valve_data[-window:])
    valve_changes = np.sum(np.abs(np.diff(recent_valves)))
    if valve_changes > 150 and steady_error > 1.5:
        return True, "恢复时间过长"

    return False, ""


def update_params_text(text_obj, system_params, pid_params, lambda_val, update_count=0):
    """更新参数显示文本"""
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    Kp, Ti, Td = pid_params['Kp'], pid_params['Ti'], pid_params['Td']
    status = f"（已更新{update_count}次）" if update_count > 0 else ""

    text = f"""系统辨识参数（最小二乘法）:
    增益 K = {K:.2f} ℃/%
    时间常数 T = {T:.1f} s
    滞后时间 L = {L:.1f} s

    Lambda整定PID参数 {status}(λ={lambda_val:.1f}):
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

    初始温度: {Config.INIT_TEMPERATURE}℃ | 目标温度: {Config.TARGET_TEMPERATURE}℃"""
    text_obj.set_text(text)


def init_real_time_fig(t, u, setpoint, system_params, pid_params, response_data):
    """初始化实时监控图表"""
    fig = plt.figure(figsize=(14, 12))
    gs = gridspec.GridSpec(5, 2)

    # 1. 输入信号曲线
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.plot(t, u, 'b-')
    ax0.set_title('系统输入信号（非阶跃）')
    ax0.set_xlabel('时间 (s)')
    ax0.set_ylabel('阀门开度 (%)')
    ax0.grid(True, alpha=0.3)

    # 2. 系统响应与辨识模型对比
    ax1 = fig.add_subplot(gs[0, 1])
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    identified_y = fopdt_model([K, T, L], t, u, Config.INIT_TEMPERATURE)
    ax1.plot(t, response_data, 'b-', label='实际响应', linewidth=1.5)
    ax1.plot(t, identified_y, 'r--', label='辨识模型', linewidth=1.5)
    ax1.set_title('系统响应与辨识模型对比')
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 3. 温度控制曲线（含扰动标记）
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_xlim(0, t[-1] * 1.2)
    ax2.set_ylim(Config.INIT_TEMPERATURE - 10, setpoint + 20)
    ax2.axhline(setpoint, color='r', linestyle='--', label='设定值', linewidth=1.5)
    ax2.axhline(Config.INIT_TEMPERATURE, color='orange', linestyle='-.',
                label=f'初始温度 {Config.INIT_TEMPERATURE}℃', linewidth=1.5)

    # 扰动标记
    disturbance_colors = {"overshoot": "red", "steady_error": "orange", "slow_recovery": "brown"}
    for d in Config.DISTURBANCES:
        ax2.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':',
                    alpha=0.7, label=f'{d["description"]} ({d["time"]}s)')

    ax2.set_title('温度控制曲线（多扰动场景）')
    ax2.set_xlabel('时间 (s)')
    ax2.set_ylabel('温度 (℃)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    temp_line, = ax2.plot([], [], 'b-', label='实际温度', linewidth=1.5)
    stabilization_line = ax2.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
    update_lines = []  # 参数更新标记线

    # 4. 阀门开度曲线
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_xlim(0, t[-1] * 1.2)
    ax3.set_ylim(0, 100)
    for d in Config.DISTURBANCES:
        ax3.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax3.set_title('阀门开度变化')
    ax3.set_xlabel('时间 (s)')
    ax3.set_ylabel('开度 (%)')
    ax3.grid(True, alpha=0.3)
    valve_line, = ax3.plot([], [], 'g-', label='阀门开度', linewidth=1.5)
    ax3.legend()

    # 5. 控制误差曲线
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_xlim(0, t[-1] * 1.2)
    ax4.set_ylim(-20, 20)
    ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
    for d in Config.DISTURBANCES:
        ax4.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax4.set_title('控制误差曲线')
    ax4.set_xlabel('时间 (s)')
    ax4.set_ylabel('误差 (℃)')
    ax4.grid(True, alpha=0.3)
    error_line, = ax4.plot([], [], 'r-', label='控制误差', linewidth=1.5)
    ax4.legend()

    # 6. PID参数变化曲线
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_xlim(0, t[-1] * 1.2)
    ax5.set_ylim(0, 5)
    for d in Config.DISTURBANCES:
        ax5.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax5.set_title('PID参数变化')
    ax5.set_xlabel('时间 (s)')
    ax5.set_ylabel('参数值（Ti/10，Td*2）')
    ax5.grid(True, alpha=0.3)
    kp_line, = ax5.plot([], [], 'r-', label='Kp', linewidth=1.5)
    ti_line, = ax5.plot([], [], 'g-', label='Ti/10', linewidth=1.5)
    td_line, = ax5.plot([], [], 'b-', label='Td*2', linewidth=1.5)
    ax5.legend()

    # 7. 参数文本显示
    ax6 = fig.add_subplot(gs[4, :])
    ax6.axis('off')
    params_text = ax6.text(0.1, 0.5, "", fontsize=10,
                           verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
    update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'])

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

    return fig, {
        'axes': (ax2, ax3, ax4, ax5),
        'lines': (temp_line, valve_line, error_line, kp_line, ti_line, td_line),
        'text': params_text,
        'slider': lambda_slider,
        'markers': (stabilization_line, update_lines),
        'colors': disturbance_colors
    }


def run_real_time_monitor(t, u, setpoint, true_params, identified_params, response_data):
    """运行实时监控主循环"""
    # 初始化图表
    fig, plot_data = init_real_time_fig(t, u, setpoint, identified_params,
                                        {'Kp': 0, 'Ti': 0, 'Td': 0}, response_data)
    (ax2, ax3, ax4, ax5) = plot_data['axes']
    (temp_line, valve_line, error_line, kp_line, ti_line, td_line) = plot_data['lines']
    params_text = plot_data['text']
    lambda_slider = plot_data['slider']
    stabilization_line, update_lines = plot_data['markers']

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
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L)
    system = TemperatureSystem(**true_params)
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
    current_temp = Config.INIT_TEMPERATURE

    # 状态变量
    stabilization_time = None
    tuning_enabled = False
    params_update_count = 0
    last_identify_time = 0
    last_params = (init_Kp, init_Ti, init_Td)
    recovery_status = {d["type"]: False for d in Config.DISTURBANCES}

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
        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, val)
        pid.set_target_params(new_Kp, new_Ti, new_Td)
        update_params_text(params_text, identified_params,
                           {'Kp': pid.target_Kp, 'Ti': pid.target_Ti, 'Td': pid.target_Td},
                           val, params_update_count)

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

            # 检测初始稳态
            if stabilization_time is None and is_stable(temp_data, setpoint):
                stabilization_time = time
                stabilization_line.set_xdata([time])
                tuning_enabled = True
                print(f"✅ 系统达到初始稳态（{time:.0f}s），开启自整定")

            # 检测扰动后恢复状态
            for d in Config.DISTURBANCES:
                if (not recovery_status[d["type"]] and
                        time > d["time"] + d["duration"] + 60 and
                        is_stable(temp_data, setpoint)):
                    recovery_status[d["type"]] = True
                    print(f"🎉 {d['description']}已恢复（{time:.0f}s），当前温度: {current_temp:.1f}℃")

            # 扰动期间/后自适应调整参数
            if tuning_enabled and time > last_identify_time + 30:
                in_disturbance = any(d["time"] <= time < d["time"] + d["duration"]
                                     for d in Config.DISTURBANCES)
                after_disturbance = any(time > d["time"] + d["duration"] and not recovery_status[d["type"]]
                                        for d in Config.DISTURBANCES)

                if in_disturbance or after_disturbance:
                    is_unstable, reason = detect_instability(temp_data, setpoint, valve_data)
                    if is_unstable and (time - last_identify_time) > Config.IDENTIFY_WINDOW / 2:
                        print(f"⚠️ 检测到不稳定：{reason}，重新辨识参数...")

                        # 窗口数据提取
                        window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)
                        window_t = np.array(time_data[window_start:]) - time_data[window_start]
                        window_u = np.array(valve_data[window_start:])
                        window_y = np.array(temp_data[window_start:])

                        # 重新辨识与整定
                        new_K, new_T, new_L = identify_fopdt_least_squares(window_t, window_y, window_u)
                        identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})
                        K, T, L = new_K, new_T, new_L

                        lambda_val = lambda_slider.val
                        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, lambda_val)

                        # 按扰动类型调整参数
                        current_disturbance = next((d for d in Config.DISTURBANCES
                                                    if d["time"] <= time < d["time"] + d["duration"]), None)
                        if current_disturbance:
                            if current_disturbance["type"] == "overshoot":
                                new_Kp *= 0.9
                                print(f"🔧 超调调整：Kp={new_Kp:.2f}")
                            elif current_disturbance["type"] == "steady_error":
                                new_Ti *= 0.8
                                print(f"🔧 稳态误差调整：Ti={new_Ti:.1f}s")
                            elif current_disturbance["type"] == "slow_recovery":
                                new_Kp *= 1.1
                                new_Td *= 1.1
                                print(f"🔧 恢复慢调整：Kp={new_Kp:.2f}, Td={new_Td:.1f}s")

                        # 更新PID参数
                        pid.set_target_params(new_Kp, new_Ti, new_Td, reset_integral=True)
                        update_lines.append(ax2.axvline(time, color='blue', linestyle='--', alpha=0.5))
                        params_update_count += 1
                        last_identify_time = time

                        # 打印参数变化
                        print(f"\n第{params_update_count}次更新：")
                        print(f"旧Kp={last_params[0]:.2f} → 新Kp={new_Kp:.2f}")
                        print(f"旧Ti={last_params[1]:.1f}s → 新Ti={new_Ti:.1f}s")
                        print(f"旧Td={last_params[2]:.1f}s → 新Td={new_Td:.1f}s\n")
                        update_params_text(params_text, identified_params,
                                           {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td},
                                           lambda_val, params_update_count)
                        last_params = (new_Kp, new_Ti, new_Td)

            # 定期打印状态（每50步）
            if i % 50 == 0:
                stable_status = "已稳态" if stabilization_time else "暂稳态"
                recovery_text = ", ".join([f"{d['description']}:{'已恢复' if recovery_status[d['type']] else '恢复中'}"
                                           for d in Config.DISTURBANCES])
                print(f"时间: {time:.0f}s | 温度: {current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                      f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新: {params_update_count}次")

            # 批量更新绘图（减少刷新频率）
            if i % Config.PLOT_REFRESH_INTERVAL == 0:
                temp_line.set_data(time_data, temp_data)
                valve_line.set_data(time_data, valve_data)
                error_line.set_data(time_data, error_data)
                kp_line.set_data(time_data, kp_data)
                ti_line.set_data(time_data, ti_data)
                td_line.set_data(time_data, td_data)
                ax2.set_title(f'温度控制曲线（当前时间：{time:.0f}s）')
                fig.canvas.draw_idle()
                plt.pause(0.01)

        # 保存数据
        save_path = os.path.join(Config.DATA_SAVE_DIR, "real_time_control_data.csv")
        real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data,
                                          kp_data, ti_data, td_data))
        np.savetxt(
            save_path,
            real_time_data,
            delimiter=",",
            header="时间(s),温度(℃),阀门开度(%),误差(℃),Kp,Ti/10,Td*2",
            comments=""
        )

        # 结束信息
        print("\n" + "=" * 50)
        print(f"仿真完成！数据保存至：{save_path}")
        print(f"初始温度：{Config.INIT_TEMPERATURE}℃ | 目标：{setpoint}℃")
        print(f"最终温度：{current_temp:.1f}℃ | 最终误差：{error:.2f}℃")
        print(f"PID参数（更新{params_update_count}次）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.show()

    except KeyboardInterrupt:
        # 中断时保存数据
        if len(time_data) > 0:
            save_path = os.path.join(Config.DATA_SAVE_DIR, "real_time_control_data_interrupted.csv")
            real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
            np.savetxt(
                save_path,
                real_time_data,
                delimiter=",",
                header="时间(s),温度(℃),阀门开度(%),误差(℃)",
                comments=""
            )
            print(f"\n已保存中断数据至：{save_path}")

        print("\n" + "=" * 50)
        print("监控手动终止")
        print(f"当前温度：{current_temp:.1f}℃ | 误差：{error:.2f}℃")
        print(f"PID参数（更新{params_update_count}次）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)
        plt.ioff()
        plt.close(fig)


def main():
    """主函数：初始化并启动仿真"""
    # 选择数据来源
    t, response_data = choose_data_source(data_type="dynamic_response")

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
    K, T, L = identify_fopdt_least_squares(t, response_data, u)
    identified_params = {'K': K, 'T': T, 'L': L}

    # 启动实时监控
    print("\n启动温度控制监控...")
    run_real_time_monitor(t, u, Config.TARGET_TEMPERATURE, initial_true_params,
                          identified_params, response_data)


if __name__ == "__main__":
    main()