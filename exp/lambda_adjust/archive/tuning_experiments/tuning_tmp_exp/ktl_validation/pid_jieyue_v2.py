import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd

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


def choose_data_source(data_type="step_response"):
    print(f"\n=== 选择{data_type}数据来源 ===")
    print("1. 自动生成仿真数据")
    print("2. 读取外部CSV数据")
    while True:
        choice = input("请输入选择（1/2）：")
        if choice == "1":
            t = np.arange(0, 1500, 1)
            return t, None
        elif choice == "2":
            file_path = input(f"请输入{data_type}CSV路径（如'./my_data.csv'）：")
            if data_type == "step_response":
                return read_csv_data(file_path, time_col="时间(s)", data_col="阶跃响应温度(℃)")
            else:
                return read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)")
        else:
            print("❌ 输入错误，请选1或2！")


class TemperatureSystem:
    def __init__(self, K=0.5, T=20, L=5, noise_level=0.3,
                 random_disturb_amp=0.5,  # 随机小幅扰动
                 tufa_disturb_prob=0.002,  # 突发概率
                 tufa_disturb_amp=3.0):  # 突发幅度从
        self.K = K
        self.T = T
        self.L = L
        self.noise_level = noise_level
        self.last_temp_initial = INIT_TEMPERATURE
        self.last_temp = self.last_temp_initial
        self.buffer = np.ones(L) * self.last_temp if L > 0 else np.array([])

        # 扰动参数
        self.random_disturb_amp = random_disturb_amp
        self.tufa_disturb_prob = tufa_disturb_prob
        self.tufa_disturb_amp = tufa_disturb_amp

    def step_response(self, t, step_magnitude=50):
        temp = np.ones_like(t) * INIT_TEMPERATURE
        for i in range(len(t)):
            if t[i] <= self.L:
                current_temp = INIT_TEMPERATURE
            else:
                current_temp = INIT_TEMPERATURE + step_magnitude * self.K * (
                        1 - np.exp(-(t[i] - self.L) / self.T)
                )
            current_temp += np.random.normal(0, self.noise_level)
            temp[i] = current_temp
        return temp

    def update(self, valve_opening, dt=1, time=None):
        # 系统动态计算
        steady_state_temp = INIT_TEMPERATURE + valve_opening * self.K
        dtemp = (steady_state_temp - self.last_temp) / self.T * dt
        new_temp = self.last_temp + dtemp

        # 随机小幅扰动（已降低强度）
        random_disturb = np.random.uniform(-self.random_disturb_amp, self.random_disturb_amp)
        new_temp += random_disturb

        # 突发大幅扰动（已降低频率和幅度）
        if np.random.random() < self.tufa_disturb_prob:
            tufa_disturb = np.random.uniform(-self.tufa_disturb_amp, self.tufa_disturb_amp)
            new_temp += tufa_disturb
            if time is not None:
                print(f"⚠️  时间 {time:.0f}s 发生突发扰动：{tufa_disturb:.1f}℃ | 温度变为：{new_temp:.1f}℃")

        # 延迟和测量噪声处理
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
    def __init__(self, Kp=0, Ti=0, Td=0, dt=1, u_min=0, u_max=100,
                 integral_threshold=5.0):  # 新增：积分分离阈值
        self.Kp = Kp
        self.Ti = Ti
        self.Td = Td
        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max
        self.last_error = 0
        self.integral = 0
        self.derivative = 0
        self.integral_threshold = integral_threshold  # 误差小于该值才积分

    def compute(self, setpoint, process_var):
        error = setpoint - process_var
        proportional = self.Kp * error

        # 优化：强化积分分离，误差大时不积分（避免超调）
        if self.Ti != 0 and abs(error) < self.integral_threshold:
            temp_output = proportional + self.integral + (self.Kp * self.Td / (self.Td + 0.1 * self.dt)) * \
                          ((error - self.last_error) / self.dt + self.derivative * 0.1 * self.dt / (
                                  self.Td + 0.1 * self.dt))
            if not (temp_output <= self.u_min or temp_output >= self.u_max):
                self.integral += (self.Kp / self.Ti) * error * self.dt
        else:
            # 误差超过阈值时，仅用比例+微分（避免积分饱和）
            temp_output = proportional + self.derivative

        # 微分计算
        if self.Td != 0:
            self.derivative = (self.Kp * self.Td / (self.Td + 0.1 * self.dt)) * \
                              ((error - self.last_error) / self.dt + self.derivative * 0.1 * self.dt / (
                                      self.Td + 0.1 * self.dt))

        # 输出限幅
        output = proportional + self.integral + self.derivative
        output = np.clip(output, self.u_min, self.u_max)
        self.last_error = error
        return output

    def reset(self):
        self.last_error = 0
        self.integral = 0
        self.derivative = 0


def identify_fopdt(t, y, step_magnitude=50):
    """从阶跃响应数据中科学计算K、T、L"""
    y_ss = np.mean(y[-int(0.1 * len(y)):])  # 稳态值（最后10%数据平均）
    y0 = np.mean(y[:int(0.1 * len(y))])  # 初始值（前10%数据平均）

    K = (y_ss - y0) / step_magnitude
    K = max(K, 0.01)

    y_63 = y0 + 0.632 * (y_ss - y0)  # 63.2%稳态值（一阶系统特征）
    L_idx = np.argmax(y >= y_63)
    L = t[L_idx] if L_idx < len(t) else 0
    L = max(L, 0)

    dy = np.diff(y)  # 温度变化率
    max_slope_idx = np.argmax(dy) + 1
    if len(t) > 1:
        dt = t[1] - t[0]
        m = dy[max_slope_idx - 1] / dt  # 最大斜率
    else:
        m = 0
    t0 = t[max_slope_idx]
    y0_tangent = y[max_slope_idx]

    if m != 0:
        t_ss_tangent = t0 + (y_ss - y0_tangent) / m
        T = t_ss_tangent - L
    else:
        T = 20
    T = max(T, 1)

    return K, T, L


def lambda_tuning(K, T, L, lambda_val=None):
    # lamda 增大可增加稳定性
    if lambda_val is None:
        lambda_val = T * 0.6  # 更大的Lambda→更平稳的响应
    Kp = (T + L / 2) / (K * (lambda_val + L / 2))
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) != 0 else 0
    return Kp, Ti, Td


def update_params_text(text_obj, system_params, pid_params, lambda_val):
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    Kp, Ti, Td = pid_params['Kp'], pid_params['Ti'], pid_params['Td']
    text = f"""系统辨识参数:
    增益 K = {K:.2f} ℃/%
    时间常数 T = {T:.1f} s
    滞后时间 L = {L:.1f} s

    Lambda整定PID参数 (λ={lambda_val:.1f}):
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

    初始温度: {INIT_TEMPERATURE} ℃
    扰动配置: 随机±0.5℃，突发±3℃
    控制优化: 温度滤波+积分分离"""  # 标注优化措施
    text_obj.set_text(text)


def init_real_time_fig(t, setpoint, system_params, pid_params, step_response):
    fig = plt.figure(figsize=(12, 8))
    gs = gridspec.GridSpec(3, 2)

    # 1. 阶跃响应与辨识模型对比
    ax1 = fig.add_subplot(gs[0, :])
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    y0 = INIT_TEMPERATURE
    identified_y = y0 + 50 * K * (1 - np.exp(-(t - L) / T)) * (t >= L)
    ax1.plot(t, step_response, 'b-', label='仿真阶跃数据')
    ax1.plot(t, identified_y, 'r--', label='辨识模型')
    ax1.axhline(y0 + 50 * K, color='g', linestyle=':', label='稳态值')
    ax1.axvline(L, color='k', linestyle='-.', label=f'滞后时间 L={L:.1f}s')
    ax1.set_title('阶跃数据与辨识模型对比')
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True)
    ax1.set_xlim(0, t[-1] * 1.5)

    # 2. 温度控制曲线（优化后更平稳）
    ax2 = fig.add_subplot(gs[1, 0])
    ax2.set_xlim(0, t[-1] * 1.5)
    ax2.set_ylim(INIT_TEMPERATURE - 3, setpoint + 10)
    ax2.axhline(setpoint, color='r', linestyle='--', label='设定值')
    ax2.axhline(INIT_TEMPERATURE, color='orange', linestyle='-.', label=f'初始温度 {INIT_TEMPERATURE}℃')
    ax2.set_title('温度控制曲线（优化后）')
    ax2.set_xlabel('时间 (s)')
    ax2.set_ylabel('温度 (℃)')
    ax2.legend()
    ax2.grid(True)
    temp_line, = ax2.plot([], [], 'b-', label='实际温度')
    filtered_temp_line, = ax2.plot([], [], 'c--', label='滤波后温度')  # 新增：显示滤波后温度
    ax2.legend()

    # 3. 阀门开度曲线（优化后跳动减小）
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.set_xlim(0, t[-1] * 1.5)
    ax3.set_ylim(0, 100)
    ax3.set_title('阀门开度变化（优化后）')
    ax3.set_xlabel('时间 (s)')
    ax3.set_ylabel('开度 (%)')
    ax3.grid(True)
    valve_line, = ax3.plot([], [], 'g-', label='阀门开度')
    ax3.legend()

    # 4. 控制误差曲线
    ax4 = fig.add_subplot(gs[2, 0])
    ax4.set_xlim(0, t[-1] * 1.5)
    ax4.set_ylim(-(setpoint - INIT_TEMPERATURE), setpoint - INIT_TEMPERATURE)
    ax4.axhline(0, color='k', linestyle='-', alpha=0.3)
    ax4.set_title('控制误差曲线')
    ax4.set_xlabel('时间 (s)')
    ax4.set_ylabel('误差 (℃)')
    ax4.grid(True)
    error_line, = ax4.plot([], [], 'r-', label='控制误差')
    ax4.legend()

    # 5. 参数显示（含优化说明）
    ax5 = fig.add_subplot(gs[2, 1])
    ax5.axis('off')
    params_text = ax5.text(0.1, 0.5, "", fontsize=10,
                           verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
    update_params_text(params_text, system_params, pid_params, lambda_val=system_params['T'])

    # Lambda滑块（标注稳定性调节）
    plt.subplots_adjust(bottom=0.15)
    ax_slider = plt.axes([0.2, 0.05, 0.65, 0.03])
    lambda_slider = Slider(
        ax=ax_slider,
        label='Lambda参数（增大→更稳定，减小→响应更快）',
        valmin=0.3 * system_params['T'],
        valmax=2 * system_params['T'],
        valinit=system_params['T'] * 1.2  # 初始值增大，优先保证稳定
    )

    plt.ion()
    plt.tight_layout(rect=[0, 0.1, 1, 1])
    plt.show(block=False)

    return fig, {
        'ax2': ax2, 'ax3': ax3, 'ax4': ax4, 'ax5': ax5,
        'temp_line': temp_line, 'filtered_temp_line': filtered_temp_line,  # 新增滤波曲线
        'valve_line': valve_line, 'error_line': error_line,
        'params_text': params_text, 'lambda_slider': lambda_slider
    }


def real_time_monitor(t, setpoint, true_params, identified_params, dt=0.1, real_temp_data=None, step_response=None):
    fig, plot_elements = init_real_time_fig(t, setpoint, identified_params, {'Kp': 0, 'Ti': 0, 'Td': 0}, step_response)
    ax2, ax3, ax4 = plot_elements['ax2'], plot_elements['ax3'], plot_elements['ax4']
    temp_line = plot_elements['temp_line']
    filtered_temp_line = plot_elements['filtered_temp_line']  # 新增滤波曲线
    valve_line, error_line = plot_elements['valve_line'], plot_elements['error_line']
    params_text, lambda_slider = plot_elements['params_text'], plot_elements['lambda_slider']

    time_data = []
    temp_data = []
    filtered_temp_data = []  # 存储滤波后温度
    valve_data = []
    error_data = []

    # 新增：温度滤波缓存（滑动平均）
    filter_buffer = []
    filter_window = 3  # 3步滑动平均，平滑高频扰动

    # 系统参数与PID初始化
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L)
    system = TemperatureSystem(** true_params)
    # 新增：设置积分分离阈值（误差>5℃时不积分）
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1, integral_threshold=5.0)
    current_temp = system.last_temp_initial

    # 打印参数信息
    print("\n" + "=" * 50)
    print("系统参数：")
    print(f"K={K:.2f}℃/% | T={T:.1f}s | L={L:.1f}s")
    print("\n扰动配置（优化后）：")
    print(f"随机小幅扰动：±{true_params['random_disturb_amp']}℃")
    print(f"突发扰动：概率{true_params['tufa_disturb_prob'] * 100}%，幅度±{true_params['tufa_disturb_amp']}℃")
    print("\nPID参数（优化后）：")
    print(f"Kp={init_Kp:.2f} | Ti={init_Ti:.1f}s | Td={init_Td:.1f}s | 积分阈值=5℃")
    print("=" * 50 + "\n")

    def on_slider_change(val):
        nonlocal pid
        lambda_val = val
        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, lambda_val)
        pid = PIDController(Kp=new_Kp, Ti=new_Ti, Td=new_Td, dt=1, integral_threshold=5.0)
        nonlocal time_data, temp_data, filtered_temp_data, valve_data, error_data, filter_buffer
        time_data = []
        temp_data = []
        filtered_temp_data = []
        valve_data = []
        error_data = []
        filter_buffer = []
        update_params_text(params_text, identified_params, {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td}, lambda_val)
        print(f"\nLambda调整为{lambda_val:.1f}，新PID参数：Kp={new_Kp:.2f}, Ti={new_Ti:.1f}, Td={new_Td:.1f}")

    lambda_slider.on_changed(on_slider_change)

    try:
        for i, time in enumerate(t):
            if real_temp_data is not None and i < len(real_temp_data):
                current_temp = real_temp_data[i]
            else:
                # 计算阀门开度（基于滤波后温度）
                valve_opening = pid.compute(setpoint,
                                            filtered_temp_data[-1] if filtered_temp_data else current_temp)
                # 更新系统温度（含扰动）
                current_temp = system.update(valve_opening, dt=1, time=time)

            # 新增：滑动平均滤波（平滑扰动导致的跳变）
            filter_buffer.append(current_temp)
            if len(filter_buffer) > filter_window:
                filter_buffer.pop(0)
            filtered_temp = np.mean(filter_buffer)  # 滤波后温度用于PID计算

            # 计算误差（基于滤波后温度，避免扰动误判）
            error = setpoint - filtered_temp
            print(f"时间: {time:.0f}s | 误差: {error:.2f}℃ | 阀门开度: {valve_opening:.1f}%")

            # 存储数据
            time_data.append(time)
            temp_data.append(current_temp)
            filtered_temp_data.append(filtered_temp)
            valve_data.append(valve_opening)
            error_data.append(error)

            # 更新图表
            temp_line.set_data(time_data, temp_data)
            filtered_temp_line.set_data(time_data, filtered_temp_data)  # 显示滤波曲线
            valve_line.set_data(time_data, valve_data)
            error_line.set_data(time_data, error_data)

            fig.canvas.draw_idle()
            plt.pause(dt)

        # 保存数据
        real_time_data = np.column_stack((time_data, temp_data, filtered_temp_data, valve_data, error_data))
        np.savetxt(
            "./data_generation/real_time_control_data.csv",
            real_time_data,
            delimiter=",",
            header="时间(s),实际温度(℃),滤波后温度(℃),阀门开度(%),误差(℃)",
            comments=""
        )
        print("\n" + "=" * 50)
        print("仿真正常结束！数据已保存（含滤波后温度）")
        print(f"初始温度：{INIT_TEMPERATURE}℃ | 目标温度：{setpoint}℃")
        print(f"最终PID参数：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.show()

    except KeyboardInterrupt:
        if len(time_data) > 0:
            real_time_data = np.column_stack((time_data, temp_data, filtered_temp_data, valve_data, error_data))
            np.savetxt(
                "../../../data_generation/real_time_control_data_interrupted.csv",
                real_time_data,
                delimiter=",",
                header="时间(s),实际温度(℃),滤波后温度(℃),阀门开度(%),误差(℃)",
                comments=""
            )
            print(f"\n已保存中断数据：real_time_control_data_interrupted.csv")

        print("\n" + "=" * 50)
        print("监控手动终止")
        print(f"当前PID参数：Kp={pid.Kp:.2f}, Ti={pid.Ti:.1f}s, Td={pid.Td:.1f}s")
        print("=" * 50)

        plt.ioff()
        plt.close(fig)


def main():
    t, step_response = choose_data_source(data_type="step_response")

    # 系统参数
    initial_true_params = {
        'K': 0.8, 'T': 50, 'L': 3,
        'noise_level': 0.3,
        'random_disturb_amp': 0.2,  # 小幅扰动±0.5℃
        'tufa_disturb_prob': 0.002,  # 突发概率0.2%
        'tufa_disturb_amp': 2.0  # 突发幅度±3℃
    }
    temp_system = TemperatureSystem(**initial_true_params)
    if step_response is None:
        step_response = temp_system.step_response(t)
        step_df = pd.DataFrame({
            "时间(s)": t,
            "阶跃响应温度(℃)": step_response
        })
        step_df.to_csv("./data_generation/step_response_data.csv", index=False)
        print(f"\n仿真阶跃数据已保存：step_response_data.csv")

    # 辨识系统参数
    print(f"\n全局初始温度：{INIT_TEMPERATURE}℃")
    print("正在计算系统参数K、T、L...")
    K, T, L = identify_fopdt(t, step_response)
    identified_params = {'K': K, 'T': T, 'L': L}

    # 目标温度校验
    max_temp = INIT_TEMPERATURE + K * 100
    setpoint = 400
    if setpoint > max_temp:
        print(f"⚠️  目标温度{setpoint}℃超出系统上限（{max_temp:.0f}℃），自动调整为{max_temp - 5:.0f}℃")
        setpoint = max_temp - 5

    # 启动优化后的监控
    print(f"\n目标温度：{setpoint}℃，启动优化后的实时监控...")
    real_time_monitor(t, setpoint, initial_true_params, identified_params, dt=0.1, step_response=step_response)


if __name__ == "__main__":
    main()