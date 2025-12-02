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

        # 校验必要列
        if time_col not in df.columns or data_col not in df.columns:
            raise ValueError(f"CSV需包含'{time_col}'和'{data_col}'列")

        # 数据清洗：去空值、转numpy
        df = df.dropna(subset=[time_col, data_col])
        t = df[time_col].values
        data = df[data_col].values

        # 校验时间递增
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
    """用户选择数据来源：仿真生成 / 读取CSV"""
    print(f"\n=== 选择{data_type}数据来源 ===")
    print("1. 自动生成仿真数据")
    print("2. 读取外部CSV数据")

    while True:
        choice = input("请输入选择（1/2）：")
        if choice == "1":
            t = np.arange(0, 1200, 1)
            return t, None
        elif choice == "2":
            file_path = input(f"请输入{data_type}CSV路径（如'./my_data.csv'）：")
            if data_type == "step_response":
                return read_csv_data(file_path, time_col="时间(s)", data_col="阶跃响应温度(℃)")
            else:
                return read_csv_data(file_path, time_col="时间(s)", data_col="温度(℃)")
        else:
            print("❌ 输入错误，请选1或2！")


# -------------------------- 温度系统与PID控制器类 --------------------------
class TemperatureSystem:
    """温度控制系统模型（一阶加纯滞后过程）"""

    def __init__(self, K=0.5, T=20, L=5, noise_level=0.3):
        self.K = K
        self.T = T
        self.L = L
        self.noise_level = noise_level
        self.last_temp_initial = INIT_TEMPERATURE
        self.last_temp = self.last_temp_initial
        self.buffer = np.ones(L) * self.last_temp if L > 0 else np.array([])

    def step_response(self, t, step_magnitude=50):
        """生成阶跃响应数据"""
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

    def update(self, valve_opening, dt=1):
        """实时更新温度"""
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

    """PID控制器（离散实现）"""

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


# -------------------------- 模型辨识与PID整定 --------------------------
def identify_fopdt(t, y, step_magnitude=50):
    """从阶跃响应辨识FOPDT参数"""
    y_ss = np.mean(y[-int(0.1 * len(y)):])
    y0 = np.mean(y[:int(0.1 * len(y))])
    K = (y_ss - y0) / step_magnitude

    y_63 = y0 + 0.632 * (y_ss - y0)
    L_idx = np.argmax(y >= y_63)
    L = t[L_idx] if L_idx < len(t) else 0

    dy = np.diff(y)
    max_slope_idx = np.argmax(dy) + 1
    m = dy[max_slope_idx - 1] / (t[1] - t[0]) if len(t) > 1 else 0
    t0 = t[max_slope_idx]
    y0_tangent = y[max_slope_idx]

    if m != 0:
        t_ss_tangent = t0 + (y_ss - y0_tangent) / m
        T = t_ss_tangent - L
    else:
        T = 20

    return max(K, 0.01), max(T, 1), max(L, 0)


def lambda_tuning(K, T, L, lambda_val=None):
    """Lambda整定PID参数"""
    if lambda_val is None:
        lambda_val = T * 0.8
    Kp = (T + L / 2) / (K * (lambda_val + L / 2))
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) != 0 else 0
    return Kp, Ti, Td


# -------------------------- 图表初始化与实时监控 --------------------------
def update_params_text(text_obj, system_params, pid_params, lambda_val):
    """更新参数显示文本"""
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

    全局初始温度: {INIT_TEMPERATURE} ℃"""
    text_obj.set_text(text)


def init_real_time_fig(t, setpoint, system_params, pid_params, step_response):
    """初始化实时监控图表（新增step_response参数）"""
    fig = plt.figure(figsize=(12, 8))
    gs = gridspec.GridSpec(3, 2)

    # 1. 阶跃响应与辨识模型对比（使用传入的step_response）
    ax1 = fig.add_subplot(gs[0, :])
    K, T, L = system_params['K'], system_params['T'], system_params['L']
    y0 = INIT_TEMPERATURE
    identified_y = y0 + 50 * K * (1 - np.exp(-(t - L) / T)) * (t >= L)
    ax1.plot(t, step_response, 'b-', label='实际数据（仿真/外部）')  # 已传入step_response
    ax1.plot(t, identified_y, 'r--', label='辨识模型')
    ax1.axhline(y0 + 50 * K, color='g', linestyle=':', label='稳态值')
    ax1.axvline(L, color='k', linestyle='-.', label=f'滞后时间 L={L:.1f}s')
    ax1.set_title('数据与模型辨识结果（静态）')
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True)
    ax1.set_xlim(0, t[-1] * 1.5)

    # 2. 温度控制曲线
    ax2 = fig.add_subplot(gs[1, 0])
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

    # 3. 阀门开度曲线
    ax3 = fig.add_subplot(gs[1, 1])
    ax3.set_xlim(0, t[-1] * 1.5)
    ax3.set_ylim(0, 100)
    ax3.set_title('阀门开度变化（实时）')
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
    ax4.set_title('控制误差曲线（实时）')
    ax4.set_xlabel('时间 (s)')
    ax4.set_ylabel('误差 (℃)')
    ax4.grid(True)
    error_line, = ax4.plot([], [], 'r-', label='控制误差')
    ax4.legend()

    # 5. PID参数显示
    ax5 = fig.add_subplot(gs[2, 1])
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


def real_time_monitor(t, setpoint, true_params, identified_params, dt=0.1, real_temp_data=None, step_response=None):
    """实时监控主逻辑（新增step_response参数）"""
    # 调用图表初始化函数时传入step_response
    fig, plot_elements = init_real_time_fig(t, setpoint, identified_params, {'Kp': 0, 'Ti': 0, 'Td': 0}, step_response)
    ax2, ax3, ax4 = plot_elements['ax2'], plot_elements['ax3'], plot_elements['ax4']
    temp_line, valve_line, error_line = plot_elements['temp_line'], plot_elements['valve_line'], plot_elements[
        'error_line']
    params_text, lambda_slider = plot_elements['params_text'], plot_elements['lambda_slider']

    time_data = []
    temp_data = []
    valve_data = []
    error_data = []

    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L)
    system = TemperatureSystem(**true_params)
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
    current_temp = system.last_temp_initial  # 初始温度

    # Lambda滑块回调
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

    lambda_slider.on_changed(on_slider_change)

    try:
        for i, time in enumerate(t):
            # 若有外部温度数据，直接读取；否则用仿真生成
            if real_temp_data is not None and i < len(real_temp_data):
                current_temp = real_temp_data[i]
                valve_opening = pid.compute(setpoint, current_temp)
            else:
                # 仿真逻辑：PID计算→更新温度
                valve_opening = pid.compute(setpoint, current_temp)
                current_temp = system.update(valve_opening, dt=1)

            error = setpoint - current_temp
            print(f"时间: {time:.0f}s | 误差: {error:.2f}℃ | 阀门开度: {valve_opening:.1f}%")

            # 存储数据
            time_data.append(time)
            temp_data.append(current_temp)
            valve_data.append(valve_opening)
            error_data.append(error)

            # 更新图表
            temp_line.set_data(time_data, temp_data)
            valve_line.set_data(time_data, valve_data)
            error_line.set_data(time_data, error_data)

            fig.canvas.draw_idle()
            plt.pause(dt)

        # 保存数据
        real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
        np.savetxt(
            "real_time_control_data.csv",
            real_time_data,
            delimiter=",",
            header="时间(s),温度(℃),阀门开度(%),误差(℃)",
            comments=""
        )
        print("\n" + "=" * 50)
        print("仿真正常结束！")
        print(f"实时数据已保存：real_time_control_data.csv")
        print(f"初始温度：{INIT_TEMPERATURE}℃ | 目标温度：{setpoint}℃")
        print("PID参数：Kp={:.2f}, Ti={:.1f}s, Td={:.1f}s".format(pid.Kp, pid.Ti, pid.Td))
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
        print("PID参数：Kp={:.2f}, Ti={:.1f}s, Td={:.1f}s".format(pid.Kp, pid.Ti, pid.Td))
        print("=" * 50)

        plt.ioff()
        plt.close(fig)


# -------------------------- 主函数 --------------------------
def main():
    # 1. 选择阶跃响应数据来源（用于模型辨识）
    t, step_response = choose_data_source(data_type="step_response")

    # 2. 处理阶跃响应数据（生成/读取）
    true_params = {'K': 0.8, 'T': 40, 'L': 5}
    temp_system = TemperatureSystem(**true_params)
    if step_response is None:
        # 生成仿真数据并保存
        step_response = temp_system.step_response(t)
        step_df = pd.DataFrame({
            "时间(s)": t,
            "阶跃响应温度(℃)": step_response
        })
        step_df.to_csv("./data_generation/step_response_data.csv", index=False)
        print(f"\n仿真阶跃数据已保存：step_response_data.csv")

    # 3. 模型辨识与目标温度校验
    print(f"\n全局初始温度：{INIT_TEMPERATURE}℃")
    K, T, L = identify_fopdt(t, step_response)
    identified_params = {'K': K, 'T': T, 'L': L}

    # 目标温度能力校验
    max_temp = INIT_TEMPERATURE + true_params['K'] * 100  # 阀门最大开度100%
    setpoint = 400
    if setpoint > max_temp:
        print(f"⚠️  目标温度{setpoint}℃超出系统上限（{max_temp:.0f}℃），自动调整为{max_temp - 5:.0f}℃")
        setpoint = max_temp - 5

    # 4. 启动实时监控（传入step_response）
    print(f"\n目标温度：{setpoint}℃，启动监控...")
    real_time_monitor(t, setpoint, true_params, identified_params, dt=0.1, step_response=step_response)


if __name__ == "__main__":
    main()