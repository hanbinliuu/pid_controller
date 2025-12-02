import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares

INIT_TEMPERATURE = 380
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
            t = np.arange(0, 600, 1)
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
    def __init__(self, K=0.5, T=20, L=5, noise_level=0.3):
        self.K = K
        self.T = T
        self.L = L
        self.noise_level = noise_level
        self.last_temp_initial = INIT_TEMPERATURE
        self.last_temp = self.last_temp_initial
        self.buffer = np.ones(L) * self.last_temp if L > 0 else np.array([])

    def generate_non_step_input(self, t):
        """生成非阶跃的控制输入信号"""
        u = np.zeros_like(t, dtype=np.float64)  # 明确指定为浮点类型
        # 混合信号：包含多个不同幅度的阶跃和斜坡
        u[t >= 50] += 20.0
        u[t >= 150] += 15.0
        u[t >= 250] -= 10.0
        u[t >= 350] += 30.0
        u[t >= 450] -= 25.0

        # 添加小幅随机扰动
        u += np.random.normal(0, 2, size=len(t))
        return np.clip(u, 0, 100)  # 确保在0-100范围内

    def simulate_with_input(self, t, u):
        """使用给定的输入信号仿真系统响应"""
        temp = np.ones_like(t) * INIT_TEMPERATURE
        self.last_temp = INIT_TEMPERATURE
        self.buffer = np.ones(self.L) * self.last_temp if self.L > 0 else np.array([])

        for i in range(len(t)):
            # 计算当前温度
            steady_state_temp = INIT_TEMPERATURE + u[i] * self.K
            dt = t[i] - t[i - 1] if i > 0 else 1
            dtemp = (steady_state_temp - self.last_temp) / self.T * dt
            new_temp = self.last_temp + dtemp

            # 处理延迟
            if self.L > 0:
                self.buffer = np.roll(self.buffer, 1)
                self.buffer[0] = new_temp
                output_temp = self.buffer[-1]
            else:
                output_temp = new_temp

            # 添加噪声
            output_temp += np.random.normal(0, self.noise_level)
            temp[i] = output_temp
            self.last_temp = new_temp

        return temp

    def update(self, valve_opening, dt=1):
        steady_state_temp = INIT_TEMPERATURE + valve_opening * self.K
        dtemp = (steady_state_temp - self.last_temp) / self.T * dt
        new_temp = self.last_temp + dtemp
        if self.L > 0:
            self.buffer = np.roll(self.buffer, 1)
            self.buffer[0] = new_temp
            output_temp = self.buffer[-1]
        else:
            output_temp = new_temp
        output_temp += np.random.normal(0, self.noise_level)
        self.last_temp = new_temp
        return output_temp


class PIDController:
    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100):
        self.Kp = Kp
        self.Ti = Ti
        self.Td = Td
        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max
        self.last_error = 0
        self.integral = 0
        self.derivative = 0

    def compute(self, setpoint, process_var):
        error = setpoint - process_var
        proportional = self.Kp * error

        if self.Ti != 0:
            temp_output = proportional + self.integral + (self.Kp * self.Td / (self.Td + 0.1 * self.dt)) * \
                          ((error - self.last_error) / self.dt + self.derivative * 0.1 * self.dt / (
                                  self.Td + 0.1 * self.dt))
            if not (temp_output <= self.u_min or temp_output >= self.u_max):
                self.integral += (self.Kp / self.Ti) * error * self.dt

        if self.Td != 0:
            self.derivative = (self.Kp * self.Td / (self.Td + 0.1 * self.dt)) * \
                              ((error - self.last_error) / self.dt + self.derivative * 0.1 * self.dt / (
                                      self.Td + 0.1 * self.dt))

        output = proportional + self.integral + self.derivative
        output = np.clip(output, self.u_min, self.u_max)
        self.last_error = error
        return output

    def reset(self):
        self.last_error = 0
        self.integral = 0
        self.derivative = 0


def fopdt_model(params, t, u, y0):
    """FOPDT模型：用于最小二乘估计"""
    K, T, L = params
    y = np.ones_like(t) * y0
    L_int = int(np.round(L))  # 将延迟转换为整数索引

    for i in range(len(t)):
        if i == 0:
            dt = 1
        else:
            dt = t[i] - t[i - 1]

        # 处理延迟
        if i < L_int:
            u_delayed = u[0]
        else:
            u_delayed = u[i - L_int]

        # 一阶系统响应
        dydt = (K * u_delayed - (y[i - 1] - y0)) / T
        y[i] = y[i - 1] + dydt * dt

    return y


def residuals(params, t, u, y_measured, y0):
    """残差函数：用于最小二乘优化"""
    y_predicted = fopdt_model(params, t, u, y0)
    return y_predicted - y_measured


def identify_fopdt_least_squares(t, y, u):
    """使用最小二乘法从非阶跃数据中估计K、T、L"""
    y0 = np.mean(y[:int(0.1 * len(y))])  # 初始值

    # 参数初始猜测值和边界
    initial_guess = [0.5, 30, 5]  # [K, T, L]
    bounds = ([0.01, 1, 0], [2, 200, 30])  # 参数上下界

    # 使用最小二乘法优化
    result = least_squares(
        residuals,
        initial_guess,
        args=(t, u, y, y0),
        bounds=bounds,
        verbose=0
    )

    K, T, L = result.x
    # 确保参数合理
    K = max(K, 0.01)
    T = max(T, 1)
    L = max(L, 0)

    return K, T, L


def lambda_tuning(K, T, L, lambda_val=None):
    if lambda_val is None:
        lambda_val = T * 0.8
    Kp = (T + L / 2) / (K * (lambda_val + L / 2))
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) != 0 else 0
    return Kp, Ti, Td


def update_params_text(text_obj, system_params, pid_params, lambda_val):
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    Kp, Ti, Td = pid_params['Kp'], pid_params['Ti'], pid_params['Td']
    text = f"""系统辨识参数（最小二乘法）:
    增益 K = {K:.2f} ℃/%
    时间常数 T = {T:.1f} s
    滞后时间 L = {L:.1f} s

    Lambda整定PID参数 (λ={lambda_val:.1f}):
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

    全局初始温度: {INIT_TEMPERATURE} ℃"""
    text_obj.set_text(text)


def init_real_time_fig(t, u, setpoint, system_params, pid_params, response_data):
    fig = plt.figure(figsize=(14, 10))
    gs = gridspec.GridSpec(4, 2)

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
    # 用辨识出的K、T、L重建模型曲线
    identified_y = fopdt_model([K, T, L], t, u, y0)
    ax1.plot(t, response_data, 'b-', label='实际响应数据')
    ax1.plot(t, identified_y, 'r--', label='辨识模型（最小二乘）')
    ax1.set_title('系统响应与辨识模型对比')
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True)

    # 3. 温度控制曲线
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_xlim(0, t[-1] * 1.5)
    ax2.set_ylim(INIT_TEMPERATURE - 3, setpoint + 10)
    ax2.axhline(setpoint, color='r', linestyle='--', label='设定值')
    ax2.axhline(INIT_TEMPERATURE, color='orange', linestyle='-.', label=f'初始温度 {INIT_TEMPERATURE}℃')
    ax2.set_title('温度控制曲线（实时）')
    ax2.set_xlabel('时间 (s)')
    ax2.set_ylabel('温度 (℃)')
    ax2.legend()
    ax2.grid(True)
    temp_line, = ax2.plot([], [], 'b-', label='实际温度')
    ax2.legend()

    # 4. 阀门开度曲线
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_xlim(0, t[-1] * 1.5)
    ax3.set_ylim(0, 100)
    ax3.set_title('阀门开度变化（实时）')
    ax3.set_xlabel('时间 (s)')
    ax3.set_ylabel('开度 (%)')
    ax3.grid(True)
    valve_line, = ax3.plot([], [], 'g-', label='阀门开度')
    ax3.legend()

    # 5. 控制误差曲线
    ax4 = fig.add_subplot(gs[2, 1])
    ax4.set_xlim(0, t[-1] * 1.5)
    ax4.set_ylim(-(setpoint - INIT_TEMPERATURE), setpoint - INIT_TEMPERATURE)
    ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
    ax4.set_title('控制误差曲线（实时）')
    ax4.set_xlabel('时间 (s)')
    ax4.set_ylabel('误差 (℃)')
    ax4.grid(True)
    error_line, = ax4.plot([], [], 'r-', label='控制误差')
    ax4.legend()

    # 6. 参数显示
    ax5 = fig.add_subplot(gs[3, :])
    ax5.axis('off')
    params_text = ax5.text(0.1, 0.5, "", fontsize=10,
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
        valinit=system_params['T'] * 0.8
    )

    plt.ion()
    plt.tight_layout(rect=[0, 0.1, 1, 1])
    plt.show(block=False)

    return fig, {
        'ax2': ax2, 'ax3': ax3, 'ax4': ax4, 'ax5': ax5,
        'temp_line': temp_line, 'valve_line': valve_line, 'error_line': error_line,
        'params_text': params_text, 'lambda_slider': lambda_slider
    }


def real_time_monitor(t, u, setpoint, true_params, identified_params, dt=0.1, real_temp_data=None, response_data=None):
    fig, plot_elements = init_real_time_fig(t, u, setpoint, identified_params, {'Kp': 0, 'Ti': 0, 'Td': 0},
                                            response_data)
    ax2, ax3, ax4 = plot_elements['ax2'], plot_elements['ax3'], plot_elements['ax4']
    temp_line, valve_line, error_line = plot_elements['temp_line'], plot_elements['valve_line'], plot_elements[
        'error_line']
    params_text, lambda_slider = plot_elements['params_text'], plot_elements['lambda_slider']

    time_data = []
    temp_data = []
    valve_data = []
    error_data = []

    # 用辨识出的K、T、L计算PID参数
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L)
    # 系统仍用真实参数，PID基于辨识结果
    system = TemperatureSystem(**true_params)
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
    current_temp = system.last_temp_initial

    # 打印辨识结果与初始PID参数
    print("\n" + "=" * 50)
    print("最小二乘法辨识的系统参数（K、T、L）：")
    print(f"静态增益 K = {K:.2f} ℃/%")
    print(f"时间常数 T = {T:.1f} s")
    print(f"纯延迟时间 L = {L:.1f} s")
    print("\n基于辨识结果的初始PID参数：")
    print(f"Kp = {init_Kp:.2f}, Ti = {init_Ti:.1f} s, Td = {init_Td:.1f} s")
    print("=" * 50 + "\n")

    def on_slider_change(val):
        nonlocal pid
        lambda_val = val
        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, lambda_val)
        pid = PIDController(Kp=new_Kp, Ti=new_Ti, Td=new_Td, dt=1)
        nonlocal time_data, temp_data, valve_data, error_data
        time_data = []
        temp_data = []
        valve_data = []
        error_data = []
        update_params_text(params_text, identified_params, {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td}, lambda_val)
        print(f"\nLambda调整为{lambda_val:.1f}，新PID参数：Kp={new_Kp:.2f}, Ti={new_Ti:.1f}, Td={new_Td:.1f}")

    lambda_slider.on_changed(on_slider_change)

    try:
        for i, time in enumerate(t):
            if real_temp_data is not None and i < len(real_temp_data):
                current_temp = real_temp_data[i]
                valve_opening = pid.compute(setpoint, current_temp)
            else:
                valve_opening = pid.compute(setpoint, current_temp)
                current_temp = system.update(valve_opening, dt=1)

            error = setpoint - current_temp
            if i % 50 == 0:  # 每50步打印一次，避免输出过多
                print(f"时间: {time:.0f}s | 误差: {error:.2f}℃ | 阀门开度: {valve_opening:.1f}%")

            time_data.append(time)
            temp_data.append(current_temp)
            valve_data.append(valve_opening)
            error_data.append(error)

            temp_line.set_data(time_data, temp_data)
            valve_line.set_data(time_data, valve_data)
            error_line.set_data(time_data, error_data)

            fig.canvas.draw_idle()
            plt.pause(dt)

        real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
        np.savetxt(
            "../../../data_generation/real_time_control_data.csv",
            real_time_data,
            delimiter=",",
            header="时间(s),温度(℃),阀门开度(%),误差(℃)",
            comments=""
        )
        print("\n" + "=" * 50)
        print("仿真正常结束！")
        print(f"实时数据已保存：real_time_control_data.csv")
        print(f"初始温度：{INIT_TEMPERATURE}℃ | 目标温度：{setpoint}℃")
        print(f"最终PID参数（基于最小二乘辨识）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
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
        print(f"当前PID参数（基于最小二乘辨识）：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.close(fig)


def main():
    t, response_data = choose_data_source(data_type="dynamic_response")

    # 生成仿真数据时，使用非阶跃输入
    initial_true_params = {'K': 0.5, 'T': 30, 'L': 4, 'noise_level': 0.3}  # 真实系统参数
    temp_system = TemperatureSystem(**initial_true_params)

    if response_data is None:
        # 生成非阶跃输入信号
        u = temp_system.generate_non_step_input(t)
        # 仿真系统响应
        response_data = temp_system.simulate_with_input(t, u)

        data_df = pd.DataFrame({
            "时间(s)": t,
            "输入信号(%)": u,
            "动态响应温度(℃)": response_data
        })
        data_df.to_csv("./data_generation/dynamic_response_data.csv", index=False)
        print(f"\n非阶跃动态响应数据已保存：dynamic_response_data.csv")
    else:
        # 如果是从文件读取，这里简化处理，实际应用中应同时读取输入信号
        u = temp_system.generate_non_step_input(t)

    # 使用最小二乘法辨识系统参数
    print(f"\n全局初始温度：{INIT_TEMPERATURE}℃")
    print("正在使用最小二乘法从非阶跃数据中估计K、T、L...")
    K, T, L = identify_fopdt_least_squares(t, response_data, u)
    identified_params = {'K': K, 'T': T, 'L': L}

    # 目标温度校验
    max_temp = INIT_TEMPERATURE + K * 100  # 基于辨识的K计算最大温度
    setpoint = 400
    if setpoint > max_temp:
        print(f"⚠️  目标温度{setpoint}℃超出系统上限（{max_temp:.0f}℃），自动调整为{max_temp - 5:.0f}℃")
        setpoint = max_temp - 5

    # 启动监控
    print(f"\n目标温度：{setpoint}℃，启动监控...")
    real_time_monitor(t, u, setpoint, initial_true_params, identified_params, dt=0.05, response_data=response_data)


if __name__ == "__main__":
    main()