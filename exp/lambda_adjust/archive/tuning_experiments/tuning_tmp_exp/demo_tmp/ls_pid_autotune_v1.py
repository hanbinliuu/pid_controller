import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares

# 配置参数 - 优化触发条件
INIT_TEMPERATURE = 380
TARGET_TEMPERATURE = 400
STABILIZATION_THRESHOLD = 1.5  # 放宽稳态判断阈值(℃)
STABILIZATION_WINDOW = 30      # 减少稳态判断窗口大小
# 多个不同类型的扰动点
DISTURBANCES = [
    {"time": 300, "type": "overshoot", "duration": 50, "amplitude": 8, "description": "超调量大"},
    {"time": 800, "type": "steady_error", "duration": 40, "amplitude": 4, "description": "稳态误差变大"},
    {"time": 1200, "type": "slow_recovery", "duration": 100, "amplitude": 6, "description": "恢复时间延长"}
]

AGING_START_TIME = 150  # 老化开始时间
IDENTIFY_WINDOW = 150   # 辨识窗口大小
PARAM_UPDATE_SMOOTH_FACTOR = 0.3  # 参数平滑因子

# 确保中文显示正常
plt.rcParams["font.family"] = ["Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False


def read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)"):
    try:
        df = pd.read_csv(file_path)
        if time_col not in df.columns or data_col not in df.columns:
            raise ValueError(f"CSV需包含'{time_col}'和'{data_col}'列")
        df = df.dropna(subset=[time_col, data_col])
        t = df[time_col].values
        data = df[data_col].values
        if not np.all(np.diff(t) >= 0):
            raise ValueError("时间序列不递增，请检查数据顺序")
        print(f"✅ 成功读取：{file_path}")
        print(f"📊 数据范围：{t.min():.0f}s ~ {t.max():.0f}s，共{len(t)}个点")
        return t, data
    except FileNotFoundError:
        print(f"❌ 未找到文件：{file_path}")
        exit()
    except Exception as e:
        print(f"❌ 读取失败：{str(e)}")
        exit()


def choose_data_source(data_type="dynamic_response"):
    print(f"\n=== 选择{data_type}数据来源 ===")
    print("1. 自动生成非阶跃仿真数据")
    print("2. 读取外部CSV数据")
    while True:
        choice = input("请输入选择（1/2）：")
        if choice == "1":
            t = np.arange(0, 2000, 1)  # 仿真时间
            return t, None
        elif choice == "2":
            file_path = input(f"请输入{data_type}CSV路径（如'./my_data.csv'）：")
            if data_type == "dynamic_response":
                return read_csv_data(file_path, time_col="时间(s)", data_col="动态响应温度(℃)")
            else:
                return read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)")
        else:
            print("❌ 输入错误，请选1或2！")


class TemperatureSystem:
    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3):
        self.initial_K = K
        self.initial_T = T
        self.initial_L = L
        self.K = K
        self.T = T
        self.L = L
        self.noise_level = noise_level
        self.last_temp_initial = INIT_TEMPERATURE
        self.last_temp = self.last_temp_initial
        self.buffer = np.ones(L) * self.last_temp if L > 0 else np.array([])
        self.disturbance_active = {d["type"]: False for d in DISTURBANCES}

    def apply_aging(self, time):
        """随时间应用设备老化效应，改变系统参数"""
        if time < AGING_START_TIME:
            return

        # 调整老化因子，让参数变化更合理
        aging_factor = min(0.0012 * (time - AGING_START_TIME), 0.5)  # 最大变化50%
        self.K = self.initial_K * (1 - aging_factor * 0.25)  # 增益降低
        self.T = self.initial_T * (1 + aging_factor * 0.5)  # 时间常数增大
        self.L = self.initial_L * (1 + aging_factor * 0.6)  # 滞后时间增加

    def add_disturbance(self, time, current_temp):
        """根据不同扰动类型添加特定特性的扰动"""
        for disturbance in DISTURBANCES:
            start = disturbance["time"]
            end = disturbance["time"] + disturbance["duration"]
            if start <= time < end:
                # 超调型扰动：短期大幅度上升
                if disturbance["type"] == "overshoot":
                    decay = 1 - (time - start) / disturbance["duration"]
                    return current_temp + disturbance["amplitude"] * decay + np.random.normal(0, 1)

                # 稳态误差型扰动：持续的偏移
                elif disturbance["type"] == "steady_error":
                    return current_temp + disturbance["amplitude"] + np.random.normal(0, 0.8)

                # 恢复缓慢型扰动：持续波动且恢复慢
                elif disturbance["type"] == "slow_recovery":
                    fluctuation = np.sin((time - start) * 0.3) * disturbance["amplitude"] * 0.7
                    return current_temp + fluctuation + np.random.normal(0, 1.2)

        return current_temp

    def generate_non_step_input(self, t):
        """生成非阶跃输入信号（阀门开度）"""
        u = np.zeros_like(t, dtype=np.float64)
        u[t >= 50] += 30.0
        u[t >= 150] += 20.0
        u[t >= 250] -= 10.0
        u[t >= 350] += 30.0
        u[t >= 450] -= 25.0
        u += np.random.normal(0, 2, size=len(t))  # 添加随机噪声
        return np.clip(u, 0, 100)  # 限制阀门开度在0-100%之间

    def simulate_with_input(self, t, u):
        temp = np.ones_like(t) * INIT_TEMPERATURE
        self.last_temp = INIT_TEMPERATURE
        self.buffer = np.ones(self.L) * self.last_temp if self.L > 0 else np.array([])

        for i in range(len(t)):
            self.apply_aging(t[i])
            steady_state_temp = INIT_TEMPERATURE + u[i] * self.K
            dt = t[i] - t[i - 1] if i > 0 else 1
            dtemp = (steady_state_temp - self.last_temp) / self.T * dt
            new_temp = self.last_temp + dtemp

            if self.L > 0:
                self.buffer = np.roll(self.buffer, 1)
                self.buffer[0] = new_temp
                output_temp = self.buffer[-1]
            else:
                output_temp = new_temp

            output_temp = self.add_disturbance(t[i], output_temp)
            output_temp += np.random.normal(0, self.noise_level)
            temp[i] = output_temp
            self.last_temp = new_temp

        return temp

    def update(self, valve_opening, time, dt=1):
        self.apply_aging(time)
        steady_state_temp = INIT_TEMPERATURE + valve_opening * self.K
        dtemp = (steady_state_temp - self.last_temp) / self.T * dt
        new_temp = self.last_temp + dtemp

        if self.L > 0:
            self.buffer = np.roll(self.buffer, 1)
            self.buffer[0] = new_temp
            output_temp = self.buffer[-1]
        else:
            output_temp = new_temp

        output_temp = self.add_disturbance(time, output_temp)
        output_temp += np.random.normal(0, self.noise_level)
        self.last_temp = new_temp
        return output_temp


class PIDController:
    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100):
        self.Kp = Kp
        self.Ti = Ti
        self.Td = Td
        self.target_Kp = Kp
        self.target_Ti = Ti
        self.target_Td = Td
        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max
        self.last_error = 0
        self.integral = 0
        self.derivative = 0
        self.smoothing_factor = PARAM_UPDATE_SMOOTH_FACTOR

    def compute(self, setpoint, process_var):
        error = setpoint - process_var
        proportional = self.Kp * error

        # 优化积分项处理
        if self.Ti != 0:
            if abs(error) < 5.0:  # 误差较小时累积积分
                self.integral += (self.Kp / self.Ti) * error * self.dt
            self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)

        # 优化微分项
        if self.Td != 0 and self.last_error != 0:
            self.derivative = 0.7 * self.derivative + 0.3 * (self.Kp * self.Td) * (error - self.last_error) / self.dt

        output = proportional + self.integral + self.derivative
        output = np.clip(output, self.u_min, self.u_max)
        self.last_error = error

        # 平滑更新参数
        self._smooth_update()
        return output

    def _smooth_update(self):
        self.Kp += self.smoothing_factor * (self.target_Kp - self.Kp)
        self.Ti += self.smoothing_factor * (self.target_Ti - self.Ti)
        self.Td += self.smoothing_factor * (self.target_Td - self.Td)

    def set_target_params(self, Kp, Ti, Td, reset_integral=False):
        self.target_Kp = Kp
        self.target_Ti = Ti
        self.target_Td = Td
        if reset_integral:
            self.integral = 0  # 参数更新时重置积分项

    def reset(self):
        self.last_error = 0
        self.integral = 0
        self.derivative = 0


def fopdt_model(params, t, u, y0):
    K, T, L = params
    y = np.ones_like(t) * y0
    L_int = int(np.round(L))

    for i in range(len(t)):
        dt = t[i] - t[i - 1] if i > 0 else 1
        if i < L_int:
            u_delayed = u[0]
        else:
            u_delayed = u[i - L_int]

        dydt = (K * u_delayed - (y[i - 1] - y0)) / T
        y[i] = y[i - 1] + dydt * dt

    return y


def residuals(params, t, u, y_measured, y0):
    y_predicted = fopdt_model(params, t, u, y0)
    return y_predicted - y_measured


def identify_fopdt_least_squares(t, y, u):
    y0 = np.mean(y[-20:]) if len(y) > 20 else np.mean(y)
    max_u = np.max(u)
    max_y = np.max(y)
    gain_guess = (max_y - y0) / max_u if max_u > 0 else 0.5

    initial_guess = [
        max(gain_guess, 0.1),  # K
        30,  # T
        5  # L
    ]

    bounds = ([0.05, 5, 0], [1.5, 150, 20])

    result = least_squares(
        residuals,
        initial_guess,
        args=(t, u, y, y0),
        bounds=bounds,
        verbose=0
    )

    K, T, L = result.x
    K = max(K, 0.05)
    T = max(T, 5)
    L = max(L, 0)
    return K, T, L


def lambda_tuning(K, T, L, lambda_val=None):
    if lambda_val is None:
        lambda_val = T * 0.4
    Kp = (T + L / 2) / (K * (lambda_val + L / 2))
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) != 0 else 0

    Kp = np.clip(Kp, 0.5, 5.0)
    Ti = np.clip(Ti, 10, 100)
    Td = np.clip(Td, 0, 20)
    return Kp, Ti, Td


def is_stable(temp_data, setpoint, window=STABILIZATION_WINDOW, threshold=STABILIZATION_THRESHOLD):
    if len(temp_data) < window:
        return False
    recent_temps = np.array(temp_data[-window:])
    deviations = np.abs(recent_temps - setpoint)
    return np.all(deviations < threshold) and np.std(deviations) < threshold / 2


def detect_instability(temp_data, setpoint, valve_data, window=80):
    """降低阈值，更容易检测到不稳定状态"""
    if len(temp_data) < window:
        return False, ""

    recent_temps = np.array(temp_data[-window:])
    deviations = recent_temps - setpoint

    # 1. 检测超调量（降低阈值）
    overshoot = np.max(deviations)
    if overshoot > 4.0:  # 从6.0降低到4.0
        return True, f"超调过大({overshoot:.1f}℃)"

    # 2. 检测稳态误差（降低阈值）
    steady_state_error = np.abs(np.mean(deviations))
    if steady_state_error > 2.0:  # 从3.0降低到2.0
        return True, f"稳态误差过大({steady_state_error:.1f}℃)"

    # 3. 检测恢复时间（降低阈值）
    recent_valves = np.array(valve_data[-window:])
    valve_changes = np.sum(np.abs(np.diff(recent_valves)))
    if valve_changes > 150 and steady_state_error > 1.5:  # 从200降低到150
        return True, "扰动恢复时间过长"

    return False, ""


def update_params_text(text_obj, system_params, pid_params, lambda_val, update_count=0):
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

    初始温度: {INIT_TEMPERATURE}℃ | 目标温度: {TARGET_TEMPERATURE}℃"""
    text_obj.set_text(text)


def init_real_time_fig(t, u, setpoint, system_params, pid_params, response_data):
    fig = plt.figure(figsize=(14, 12))
    gs = gridspec.GridSpec(5, 2)

    # 1. 输入信号
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.plot(t, u, 'b-')
    ax0.set_title('系统输入信号（非阶跃）')
    ax0.set_xlabel('时间 (s)')
    ax0.set_ylabel('阀门开度 (%)')
    ax0.grid(True)

    # 2. 系统响应与辨识模型对比
    ax1 = fig.add_subplot(gs[0, 1])
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    y0 = INIT_TEMPERATURE
    identified_y = fopdt_model([K, T, L], t, u, y0)
    ax1.plot(t, response_data, 'b-', label='实际响应数据')
    ax1.plot(t, identified_y, 'r--', label='辨识模型（最小二乘）')
    ax1.set_title('系统响应与辨识模型对比')
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True)

    # 3. 温度控制曲线（增加多个扰动标记）
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_xlim(0, t[-1] * 1.2)
    ax2.set_ylim(INIT_TEMPERATURE - 10, setpoint + 20)
    ax2.axhline(setpoint, color='r', linestyle='--', label='设定值')
    ax2.axhline(INIT_TEMPERATURE, color='orange', linestyle='-.', label=f'初始温度 {INIT_TEMPERATURE}℃')

    # 为每个扰动点添加标记和图例
    disturbance_colors = {"overshoot": "red", "steady_error": "orange", "slow_recovery": "brown"}
    for d in DISTURBANCES:
        ax2.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':',
                    alpha=0.7, label=f'{d["description"]} ({d["time"]}s)')

    ax2.set_title('温度控制曲线（多扰动场景）')
    ax2.set_xlabel('时间 (s)')
    ax2.set_ylabel('温度 (℃)')
    ax2.legend()
    ax2.grid(True)
    temp_line, = ax2.plot([], [], 'b-', label='实际温度')
    stabilization_line = ax2.axvline(0, color='green', linestyle='--', alpha=0.5, label='达到稳态')
    update_lines = []  # 用于存储多次参数更新的标记线
    ax2.legend()

    # 4. 阀门开度曲线
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_xlim(0, t[-1] * 1.2)
    ax3.set_ylim(0, 100)
    # 标记扰动点
    for d in DISTURBANCES:
        ax3.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax3.set_title('阀门开度变化（实时）')
    ax3.set_xlabel('时间 (s)')
    ax3.set_ylabel('开度 (%)')
    ax3.grid(True)
    valve_line, = ax3.plot([], [], 'g-', label='阀门开度')
    ax3.legend()

    # 5. 控制误差曲线
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_xlim(0, t[-1] * 1.2)
    ax4.set_ylim(-20, 20)
    ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
    # 标记扰动点
    for d in DISTURBANCES:
        ax4.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax4.set_title('控制误差曲线（实时）')
    ax4.set_xlabel('时间 (s)')
    ax4.set_ylabel('误差 (℃)')
    ax4.grid(True)
    error_line, = ax4.plot([], [], 'r-', label='控制误差')
    ax4.legend()

    # 6. PID参数变化曲线
    ax5 = fig.add_subplot(gs[3, :])
    ax5.set_xlim(0, t[-1] * 1.2)
    ax5.set_ylim(0, 5)
    # 标记扰动点
    for d in DISTURBANCES:
        ax5.axvline(d["time"], color=disturbance_colors[d["type"]], linestyle=':', alpha=0.7)
    ax5.set_title('PID参数变化曲线')
    ax5.set_xlabel('时间 (s)')
    ax5.set_ylabel('参数值')
    ax5.grid(True)
    kp_line, = ax5.plot([], [], 'r-', label='Kp')
    ti_line, = ax5.plot([], [], 'g-', label='Ti/10')
    td_line, = ax5.plot([], [], 'b-', label='Td*2')
    ax5.legend()

    # 7. 参数显示
    ax6 = fig.add_subplot(gs[4, :])
    ax6.axis('off')
    params_text = ax6.text(0.1, 0.5, "", fontsize=10,
                           verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
    update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'])

    # Lambda滑块
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
        'ax2': ax2, 'ax3': ax3, 'ax4': ax4, 'ax5': ax5, 'ax6': ax6,
        'temp_line': temp_line, 'valve_line': valve_line, 'error_line': error_line,
        'kp_line': kp_line, 'ti_line': ti_line, 'td_line': td_line,
        'params_text': params_text, 'lambda_slider': lambda_slider,
        'stabilization_line': stabilization_line, 'update_lines': update_lines,
        'disturbance_colors': disturbance_colors
    }


def real_time_monitor(t, u, setpoint, true_params, identified_params, dt=0.1, real_temp_data=None, response_data=None):
    fig, plot_elements = init_real_time_fig(t, u, setpoint, identified_params, {'Kp': 0, 'Ti': 0, 'Td': 0},
                                            response_data)
    ax2, ax3, ax4, ax5 = plot_elements['ax2'], plot_elements['ax3'], plot_elements['ax4'], plot_elements['ax5']
    temp_line, valve_line, error_line = plot_elements['temp_line'], plot_elements['valve_line'], plot_elements[
        'error_line']
    kp_line, ti_line, td_line = plot_elements['kp_line'], plot_elements['ti_line'], plot_elements['td_line']
    params_text, lambda_slider = plot_elements['params_text'], plot_elements['lambda_slider']
    stabilization_line, update_lines = plot_elements['stabilization_line'], plot_elements['update_lines']
    disturbance_colors = plot_elements['disturbance_colors']

    time_data = []
    temp_data = []
    valve_data = []
    error_data = []
    kp_data = []
    ti_data = []
    td_data = []

    # 初始参数辨识与PID整定
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L)
    system = TemperatureSystem(** true_params)
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
    current_temp = system.last_temp_initial

    # 状态变量
    stabilization_time = None
    tuning_enabled = False
    params_update_count = 0  # 记录参数更新次数
    last_identify_time = 0
    last_params = (init_Kp, init_Ti, init_Td)  # 记录上一次参数
    recovery_status = {d["type"]: False for d in DISTURBANCES}  # 各扰动恢复状态

    print("\n" + "=" * 50)
    print("初始系统参数辨识结果（K、T、L）：")
    print(f"静态增益 K = {K:.2f} ℃/%")
    print(f"时间常数 T = {T:.1f} s")
    print(f"纯延迟时间 L = {L:.1f} s")
    print("\n初始PID参数：")
    print(f"Kp = {init_Kp:.2f}, Ti = {init_Ti:.1f} s, Td = {init_Td:.1f} s")
    print("\n扰动计划：")
    for d in DISTURBANCES:
        print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s）")
    print("=" * 50 + "\n")

    def on_slider_change(val):
        nonlocal pid, K, T, L
        lambda_val = val
        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, lambda_val)
        pid.set_target_params(new_Kp, new_Ti, new_Td)
        update_params_text(params_text, identified_params,
                           {'Kp': pid.target_Kp, 'Ti': pid.target_Ti, 'Td': pid.target_Td},
                           lambda_val, params_update_count)

    lambda_slider.on_changed(on_slider_change)

    try:
        for i, time in enumerate(t):
            # 计算控制输出与当前温度
            valve_opening = pid.compute(setpoint, current_temp)
            current_temp = system.update(valve_opening, time, dt=1)
            error = setpoint - current_temp

            # 记录数据
            time_data.append(time)
            temp_data.append(current_temp)
            valve_data.append(valve_opening)
            error_data.append(error)
            kp_data.append(pid.Kp)
            ti_data.append(pid.Ti / 10)
            td_data.append(pid.Td * 2)

            # 检测是否达到初始稳态
            if stabilization_time is None and is_stable(temp_data, setpoint):
                stabilization_time = time
                stabilization_line.set_xdata([time])
                tuning_enabled = True
                print(f"\n✅ 系统已达到初始稳态（{time:.0f}s），开启参数自整定功能")

            # 检查各扰动后的恢复状态 - 延长判断时间到60s
            for d in DISTURBANCES:
                if not recovery_status[d["type"]] and time > d["time"] + d["duration"] + 60:
                    if is_stable(temp_data, setpoint):
                        recovery_status[d["type"]] = True
                        print(f"\n🎉 {d['description']}扰动已恢复稳定（{time:.0f}s），当前温度: {current_temp:.1f}℃")

            # 每次扰动后检测不稳定性并重新整定 - 缩短更新间隔到30s
            if tuning_enabled and time > last_identify_time + 30:
                # 检查是否处于某个扰动期间或之后
                in_disturbance = any(d["time"] <= time < d["time"] + d["duration"] for d in DISTURBANCES)
                after_disturbance = any(time > d["time"] + d["duration"] and not recovery_status[d["type"]]
                                        for d in DISTURBANCES)

                if in_disturbance or after_disturbance:
                    is_unstable, reason = detect_instability(temp_data, setpoint, valve_data)
                    if is_unstable and (time - last_identify_time) > IDENTIFY_WINDOW / 2:
                        print(f"\n⚠️  检测到系统不稳定：{reason}，开始重新辨识参数...")

                        # 使用最近窗口的数据重新辨识
                        window_start = max(0, len(time_data) - IDENTIFY_WINDOW)
                        window_t = np.array(time_data[window_start:]) - time_data[window_start]
                        window_u = np.array(valve_data[window_start:])
                        window_y = np.array(temp_data[window_start:])

                        new_K, new_T, new_L = identify_fopdt_least_squares(window_t, window_y, window_u)
                        identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})
                        K, T, L = new_K, new_T, new_L  # 更新全局变量

                        # 计算新的PID参数
                        lambda_val = lambda_slider.val
                        new_Kp, new_Ti, new_Td = lambda_tuning(new_K, new_T, new_L, lambda_val)

                        # 根据扰动类型调整参数
                        current_disturbance = next((d for d in DISTURBANCES
                                                    if d["time"] <= time < d["time"] + d["duration"]), None)
                        if current_disturbance:
                            if current_disturbance["type"] == "overshoot":
                                new_Kp *= 0.9  # 超调时减小比例增益
                                print(f"🔧 针对超调扰动，调整Kp至{new_Kp:.2f}")
                            elif current_disturbance["type"] == "steady_error":
                                new_Ti *= 0.8  # 稳态误差时减小积分时间
                                print(f"🔧 针对稳态误差，调整Ti至{new_Ti:.1f}s")
                            elif current_disturbance["type"] == "slow_recovery":
                                new_Kp *= 1.1  # 恢复慢时增大比例增益
                                new_Td *= 1.1  # 适当增大微分作用
                                print(f"🔧 针对恢复缓慢，调整Kp至{new_Kp:.2f}, Td至{new_Td:.1f}s")

                        # 设置新参数并重置积分项
                        pid.set_target_params(new_Kp, new_Ti, new_Td, reset_integral=True)

                        # 添加参数更新标记线
                        update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)
                        update_lines.append(update_line)

                        # 更新状态
                        params_update_count += 1
                        last_identify_time = time

                        # 打印参数变化
                        print("\n" + "=" * 50)
                        print(f"第{params_update_count}次参数更新前后对比：")
                        print(f"旧Kp = {last_params[0]:.2f}, 新Kp = {new_Kp:.2f}")
                        print(f"旧Ti = {last_params[1]:.1f}s, 新Ti = {new_Ti:.1f}s")
                        print(f"旧Td = {last_params[2]:.1f}s, 新Td = {new_Td:.1f}s")
                        print("=" * 50 + "\n")
                        update_params_text(params_text, identified_params,
                                           {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td},
                                           lambda_val, params_update_count)

                        # 更新上次参数记录
                        last_params = (new_Kp, new_Ti, new_Td)

            # 每50步打印一次状态
            if i % 50 == 0:
                stable_status = "已稳态" if stabilization_time else "暂未稳态"
                recovery_text = ", ".join([f"{d['description']}:{'已恢复' if recovery_status[d['type']] else '恢复中'}"
                                           for d in DISTURBANCES])
                # 增加调试信息
                in_disturb = any(d["time"] <= time < d["time"] + d["duration"] for d in DISTURBANCES)
                is_unstable, _ = detect_instability(temp_data, setpoint, valve_data)
                print(f"时间: {time:.0f}s | 温度: {current_temp:.1f}℃ | 误差: {error:.2f}℃ | "
                      f"阀门: {valve_opening:.1f}% | 状态: {stable_status} | 更新次数: {params_update_count} | "
                      f"恢复状态: {recovery_text} | 调试: 扰动中={in_disturb}, 不稳定={is_unstable}")

            # 更新绘图
            temp_line.set_data(time_data, temp_data)
            valve_line.set_data(time_data, valve_data)
            error_line.set_data(time_data, error_data)
            kp_line.set_data(time_data, kp_data)
            ti_line.set_data(time_data, ti_data)
            td_line.set_data(time_data, td_data)

            fig.canvas.draw_idle()
            plt.pause(dt)

        # 保存数据
        real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data,
                                          kp_data, ti_data, td_data))
        np.savetxt(
            "../data_generation/real_time_control_data.csv",
            real_time_data,
            delimiter=",",
            header="时间(s),温度(℃),阀门开度(%),误差(℃),Kp,Ti/10,Td*2",
            comments=""
        )
        print("\n" + "=" * 50)
        print("仿真正常结束！")
        print(f"实时数据已保存：real_time_control_data.csv")
        print(f"初始温度：{INIT_TEMPERATURE}℃ | 目标温度：{setpoint}℃")
        print(f"最终温度：{current_temp:.1f}℃ | 最终误差：{error:.2f}℃")
        print(f"最终PID参数（更新{params_update_count}次）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.show()

    except KeyboardInterrupt:
        if len(time_data) > 0:
            real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
            np.savetxt(
                "../../../data_generation/real_time_control_data_interrupted.csv",
                real_time_data,
                delimiter=",",
                header="时间(s),温度(℃),阀门开度(%),误差(℃)",
                comments=""
            )
            print(f"\n已保存中断数据：real_time_control_data_interrupted.csv")

        print("\n" + "=" * 50)
        print("监控手动终止")
        print(f"当前温度：{current_temp:.1f}℃ | 当前误差：{error:.2f}℃")
        print(f"当前PID参数（已更新{params_update_count}次）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.close(fig)


def main():
    t, response_data = choose_data_source(data_type="dynamic_response")

    # 真实系统初始参数
    initial_true_params = {'K': 0.8, 'T': 20, 'L': 4, 'noise_level': 0.3}
    temp_system = TemperatureSystem(**initial_true_params)

    if response_data is None:
        u = temp_system.generate_non_step_input(t)
        response_data = temp_system.simulate_with_input(t, u)
        data_df = pd.DataFrame({
            "时间(s)": t,
            "输入信号(%)": u,
            "动态响应温度(℃)": response_data
        })
        # data_df.to_csv("./data_generation/dynamic_response_data.csv", index=False)
        # print(f"\n非阶跃动态响应数据已保存：dynamic_response_data.csv")
    else:
        u = temp_system.generate_non_step_input(t)

    # 初始系统参数辨识
    print(f"\n全局初始温度：{INIT_TEMPERATURE}℃ | 目标温度：{TARGET_TEMPERATURE}℃")
    print("正在使用最小二乘法从非阶跃数据中估计初始K、T、L...")
    K, T, L = identify_fopdt_least_squares(t, response_data, u)
    identified_params = {'K': K, 'T': T, 'L': L}

    # 启动监控
    print(f"\n启动温度控制监控...")
    real_time_monitor(t, u, TARGET_TEMPERATURE, initial_true_params, identified_params,
                      dt=0.05, response_data=response_data)


if __name__ == "__main__":
    main()