import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import pandas as pd
from scipy.optimize import least_squares
from datetime import datetime
import os

INIT_TEMPERATURE = 380
SP = 400
plt.rcParams["font.family"] = ["Heiti TC"]
plt.rcParams['axes.unicode_minus'] = False
data_save_pth = '../data_simulation/ls_validation_ktl_results'

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
        u = np.zeros_like(t, dtype=np.float64)
        u[t >= 50] += 20.0
        u[t >= 150] += 15.0
        u[t >= 250] -= 10.0
        u[t >= 350] += 30.0
        u[t >= 450] -= 25.0
        u += np.random.normal(0, 2, size=len(t))
        return np.clip(u, 0, 100)

    def simulate_with_input(self, t, u):
        temp = np.ones_like(t) * INIT_TEMPERATURE
        self.last_temp = INIT_TEMPERATURE
        self.buffer = np.ones(self.L) * self.last_temp if self.L > 0 else np.array([])

        for i in range(len(t)):
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
    K, T, L = params
    y = np.ones_like(t) * y0
    L_int = int(np.round(L))

    for i in range(len(t)):
        dt = 1 if i == 0 else t[i] - t[i - 1]
        u_delayed = u[0] if i < L_int else u[i - L_int]
        dydt = (K * u_delayed - (y[i - 1] - y0)) / T
        y[i] = y[i - 1] + dydt * dt

    return y


def residuals(params, t, u, y_measured, y0):
    y_predicted = fopdt_model(params, t, u, y0)
    return y_predicted - y_measured


def identify_fopdt_least_squares(t, y, u):
    y0 = np.mean(y[:int(0.1 * len(y))])
    initial_guess = [0.5, 30, 5]
    bounds = ([0.01, 1, 0], [2, 200, 30])

    result = least_squares(
        residuals,
        initial_guess,
        args=(t, u, y, y0),
        bounds=bounds,
        verbose=0
    )

    K, T, L = result.x
    K = max(K, 0.01)
    T = max(T, 1)
    L = max(L, 0)

    # 计算拟合优度R²（评估KTL辨识效果）
    y_pred = fopdt_model([K, T, L], t, u, y0)
    ss_total = np.sum((y - np.mean(y)) ** 2)
    ss_residual = np.sum((y - y_pred) ** 2)
    r2 = 1 - (ss_residual / ss_total) if ss_total != 0 else 0.0

    return K, T, L, r2


def lambda_tuning(K, T, L, lambda_val=None):
    if lambda_val is None:
        lambda_val = T * 0.8
    Kp = (T + L / 2) / (K * (lambda_val + L / 2))
    Ti = T + L / 2
    Td = (T * L) / (2 * T + L) if (2 * T + L) != 0 else 0
    return Kp, Ti, Td


def update_params_text(text_obj, true_params, identified_params, pid_params, lambda_val, r2):
    true_K, true_T, true_L = true_params['K'], true_params['T'], true_params['L']
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    Kp, Ti, Td = pid_params['Kp'], pid_params['Ti'], pid_params['Td']
    text = f"""=== 系统参数对比（KTL） ===
真实参数（参考）:
    增益 K = {true_K:.2f} ℃/%
    时间常数 T = {true_T:.1f} s
    滞后时间 L = {true_L:.1f} s

辨识参数（最小二乘法）:
    增益 K = {K:.2f} ℃/%
    时间常数 T = {T:.1f} s
    滞后时间 L = {L:.1f} s
    拟合优度 R² = {r2:.4f} 

=== Lambda整定PID参数 ===
Lambda值 λ = {lambda_val:.1f} s
    比例增益 Kp = {Kp:.2f}
    积分时间 Ti = {Ti:.1f} s
    微分时间 Td = {Td:.1f} s

全局初始温度: {INIT_TEMPERATURE} ℃ | 目标温度: {SP:.1f} ℃"""  # 新增：显示目标温度
    text_obj.set_text(text)


def init_real_time_fig(t, u, setpoint, true_params, identified_params, pid_params, response_data, r2):
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
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    y0 = INIT_TEMPERATURE
    identified_y = fopdt_model([K, T, L], t, u, y0)
    ax1.plot(t, response_data, 'b-', label='实际响应数据')
    ax1.plot(t, identified_y, 'r--', label='辨识模型（最小二乘）')
    ax1.set_title('系统响应与辨识模型对比（R²={:.4f}）'.format(r2))  # 新增：标题显示R²
    ax1.set_xlabel('时间 (s)')
    ax1.set_ylabel('温度 (℃)')
    ax1.legend()
    ax1.grid(True)

    # 3. 温度控制曲线
    ax2 = fig.add_subplot(gs[1, :])
    ax2.set_xlim(0, t[-1] * 1.5)
    ax2.set_ylim(INIT_TEMPERATURE - 3, setpoint + 10)
    ax2.axhline(setpoint, color='r', linestyle='--', label=f'设定值 {setpoint:.1f}℃')
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
    params_text = ax5.text(0.05, 0.5, "", fontsize=10,
                           verticalalignment='center', bbox=dict(facecolor='white', alpha=0.8))
    init_lambda = identified_params['T'] * 0.8
    update_params_text(params_text, true_params, identified_params, pid_params, init_lambda, r2)

    # Lambda滑块
    plt.subplots_adjust(bottom=0.15)
    ax_slider = plt.axes([0.2, 0.05, 0.65, 0.03])
    lambda_slider = Slider(
        ax=ax_slider,
        label='Lambda 参数（减小→响应更快）',
        valmin=0.3 * identified_params['T'],
        valmax=2 * identified_params['T'],
        valinit=init_lambda
    )

    plt.ion()
    plt.tight_layout(rect=[0, 0.1, 1, 1])
    plt.show(block=False)

    return fig, {
        'ax2': ax2, 'ax3': ax3, 'ax4': ax4, 'ax5': ax5,
        'temp_line': temp_line, 'valve_line': valve_line, 'error_line': error_line,
        'params_text': params_text, 'lambda_slider': lambda_slider,
        'init_lambda': init_lambda
    }


def save_ktl_params(true_params, identified_params, r2, pid_params, lambda_val, setpoint, save_dir=data_save_pth):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # 生成时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = os.path.join(save_dir, f"ktl_params_{timestamp}.csv")

    # 整理参数数据
    params_data = {
        "参数类型": [
            "真实系统参数", "真实系统参数", "真实系统参数",
            "辨识系统参数", "辨识系统参数", "辨识系统参数", "辨识系统参数",
            "PID参数", "PID参数", "PID参数",
            "控制配置", "控制配置"
        ],
        "参数名称": [
            "K（增益）", "T（时间常数）", "L（滞后时间）",
            "K（增益）", "T（时间常数）", "L（滞后时间）", "R²（拟合优度）",
            "Kp（比例增益）", "Ti（积分时间）", "Td（微分时间）",
            "Lambda值", "目标温度"
        ],
        "数值": [
            true_params['K'], true_params['T'], true_params['L'],
            identified_params['K'], identified_params['T'], identified_params['L'], r2,
            pid_params['Kp'], pid_params['Ti'], pid_params['Td'],
            lambda_val, setpoint
        ],
        "单位": [
            "℃/%", "s", "s",
            "℃/%", "s", "s", "无",
            "无", "s", "s",
            "s", "℃"
        ],
        "备注": [
            "系统真实值（参考）", "系统真实值（参考）", "系统真实值（参考）",
            "最小二乘法辨识结果", "最小二乘法辨识结果", "最小二乘法辨识结果", "辨识模型拟合精度",
            "Lambda整定结果", "Lambda整定结果", "Lambda整定结果",
            "PID参数整定系数", "控制目标温度"
        ]
    }

    df = pd.DataFrame(params_data)
    df.to_csv(file_path, index=False, encoding="utf-8-sig")
    print(f"\n✅ KTL参数已保存到：{file_path}")
    return file_path


def real_time_monitor(t, u, setpoint, true_params, identified_params, r2, dt=0.1, response_data=None):
    # 初始化PID参数
    K, T, L = identified_params['K'], identified_params['T'], identified_params['L']
    init_lambda = T * 0.8
    init_Kp, init_Ti, init_Td = lambda_tuning(K, T, L, init_lambda)
    init_pid_params = {'Kp': init_Kp, 'Ti': init_Ti, 'Td': init_Td}

    fig, plot_elements = init_real_time_fig(
        t, u, setpoint, true_params, identified_params, init_pid_params, response_data, r2
    )
    ax2, ax3, ax4 = plot_elements['ax2'], plot_elements['ax3'], plot_elements['ax4']
    temp_line, valve_line, error_line = plot_elements['temp_line'], plot_elements['valve_line'], plot_elements[
        'error_line']
    params_text, lambda_slider = plot_elements['params_text'], plot_elements['lambda_slider']
    init_lambda = plot_elements['init_lambda']

    time_data = []
    temp_data = []
    valve_data = []
    error_data = []

    # 初始化系统和PID
    system = TemperatureSystem(**true_params)
    pid = PIDController(Kp=init_Kp, Ti=init_Ti, Td=init_Td, dt=1)
    current_temp = system.last_temp_initial

    print("\n" + "=" * 60)
    print("                    系统KTL参数辨识结果汇总")
    print("=" * 60)
    print(f"{'参数类型':<12} {'参数':<8} {'真实值':<10} {'辨识值':<10} {'单位':<6}")
    print("-" * 60)
    print(f"{'真实系统参数':<12} K      {true_params['K']:<10.2f} -          ℃/%")
    print(f"{'真实系统参数':<12} T      {true_params['T']:<10.1f} -          s")
    print(f"{'真实系统参数':<12} L      {true_params['L']:<10.1f} -          s")
    print(f"{'辨识系统参数':<12} K      -          {K:<10.2f} ℃/%")
    print(f"{'辨识系统参数':<12} T      -          {T:<10.1f} s")
    print(f"{'辨识系统参数':<12} L      -          {L:<10.1f} s")
    print(f"{'辨识评估':<12} R²     -          {r2:<10.4f} 无")
    print("=" * 60)
    print(f"初始PID参数（Lambda={init_lambda:.1f}）：")
    print(f"Kp={init_Kp:.2f}, Ti={init_Ti:.1f}s, Td={init_Td:.1f}s")
    print("=" * 60 + "\n")

    def on_slider_change(val):
        nonlocal pid, current_temp, time_data, temp_data, valve_data, error_data
        lambda_val = val
        new_Kp, new_Ti, new_Td = lambda_tuning(K, T, L, lambda_val)
        pid = PIDController(Kp=new_Kp, Ti=new_Ti, Td=new_Td, dt=1)
        current_temp = system.last_temp_initial  # 重置温度
        time_data = []
        temp_data = []
        valve_data = []
        error_data = []
        update_params_text(params_text, true_params, identified_params,
                           {'Kp': new_Kp, 'Ti': new_Ti, 'Td': new_Td}, lambda_val, r2)
        print(f"\n🔄 Lambda调整为{lambda_val:.1f}，新PID参数：Kp={new_Kp:.2f}, Ti={new_Ti:.1f}, Td={new_Td:.1f}")

    lambda_slider.on_changed(on_slider_change)

    try:
        for i, time in enumerate(t):
            valve_opening = pid.compute(setpoint, current_temp)
            current_temp = system.update(valve_opening, dt=1)
            error = setpoint - current_temp

            if i % 50 == 0:
                print(f"⏱️  时间: {time:.0f}s | 🌡️  温度: {current_temp:.2f}℃ | "
                      f"⚙️  阀门: {valve_opening:.1f}% | ❌ 误差: {error:.2f}℃ | "
                      f"参考KTL: K={K:.2f}, T={T:.1f}, L={L:.1f}")

            time_data.append(time)
            temp_data.append(current_temp)
            valve_data.append(valve_opening)
            error_data.append(error)

            temp_line.set_data(time_data, temp_data)
            valve_line.set_data(time_data, valve_data)
            error_line.set_data(time_data, error_data)

            fig.canvas.draw_idle()
            plt.pause(dt)

        # 保存实时控制数据
        real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
        np.savetxt(
            os.path.join(data_save_pth, "real_time_control_data.csv"),
            real_time_data,
            delimiter=",",
            header="时间(s),温度(℃),阀门开度(%),误差(℃)",
            comments=""
        )

        # 仿真结束时再次保存KTL参数（最终状态）
        final_lambda = lambda_slider.val
        final_Kp, final_Ti, final_Td = lambda_tuning(K, T, L, final_lambda)
        final_pid_params = {'Kp': final_Kp, 'Ti': final_Ti, 'Td': final_Td}
        save_ktl_params(true_params, identified_params, r2, final_pid_params, final_lambda, setpoint)

        print("\n" + "=" * 60)
        print("                    仿真结束 - KTL参数总结")
        print("=" * 60)
        print(f"最终辨识KTL参数：K={K:.2f}℃/%，T={T:.1f}s，L={L:.1f}s，R²={r2:.4f}")
        print(f"最终PID参数（Lambda={final_lambda:.1f}）：Kp={final_Kp:.2f}，Ti={final_Ti:.1f}s，Td={final_Td:.1f}s")
        print("=" * 60)

        plt.ioff()
        plt.show()

    except KeyboardInterrupt:
        if len(time_data) > 0:
            real_time_data = np.column_stack((time_data, temp_data, valve_data, error_data))
            np.savetxt(
                os.path.join(data_save_pth, "real_time_control_data_interrupted.csv"),
                real_time_data,
                delimiter=",",
                header="时间(s),温度(℃),阀门开度(%),误差(℃)",
                comments=""
            )

        # 保存中断时的KTL参数
        current_lambda = lambda_slider.val
        current_Kp, current_Ti, current_Td = lambda_tuning(K, T, L, current_lambda)
        current_pid_params = {'Kp': current_Kp, 'Ti': current_Ti, 'Td': current_Td}
        save_ktl_params(true_params, identified_params, r2, current_pid_params, current_lambda, setpoint)

        print("\n" + "=" * 60)
        print("                    监控手动终止 - KTL参数总结")
        print("=" * 60)
        print(f"辨识KTL参数：K={K:.2f}℃/%，T={T:.1f}s，L={L:.1f}s，R²={r2:.4f}")
        print(f"当前PID参数（Lambda={current_lambda:.1f}）：Kp={current_Kp:.2f}，Ti={current_Ti:.1f}s，Td={current_Td:.1f}s")
        print("=" * 60)

        plt.ioff()
        plt.close(fig)


def main():
    global SP
    t, response_data = choose_data_source(data_type="dynamic_response")

    # 真实系统参数
    initial_true_params = {'K': 0.5, 'T': 30, 'L': 4, 'noise_level': 0.3}
    temp_system = TemperatureSystem(**initial_true_params)

    # 生成/读取数据
    if response_data is None:
        u = temp_system.generate_non_step_input(t)
        response_data = temp_system.simulate_with_input(t, u)
        # 保存生成的动态响应数据
        data_df = pd.DataFrame({
            "时间(s)": t,
            "输入信号(%)": u,
            "动态响应温度(℃)": response_data
        })
        data_df.to_csv(
            os.path.join(data_save_pth, "dynamic_response_data.csv"),  # 用全局变量拼接路径
            index=False,
            encoding="utf-8-sig"
        )
        save_path = os.path.join(data_save_pth, "dynamic_response_data.csv")
        print(f"\n✅ 非阶跃数据已保存：{save_path}")
    else:
        u = temp_system.generate_non_step_input(t)

    # 系统辨识
    print(f"\n🌡️  全局初始温度：{INIT_TEMPERATURE}℃")
    print("🔍 正在用最小二乘法辨识K、T、L参数...")
    K, T, L, r2 = identify_fopdt_least_squares(t, response_data, u)  # 接收R²
    identified_params = {'K': K, 'T': T, 'L': L}

    # 目标温度校验
    max_temp = INIT_TEMPERATURE + K * 100
    if SP > max_temp:
        SP = max_temp - 5
        print(f"⚠️  目标温度超出系统上限，自动调整为：{SP:.1f}℃")
    else:
        print(f"🎯 目标温度：{SP:.1f}℃")

    # 启动实时监控
    print(f"\n🚀 启动实时控制监控，辨识KTL参数：K={K:.2f}, T={T:.1f}, L={L:.1f}, R²={r2:.4f}")
    real_time_monitor(t, u, SP, initial_true_params, identified_params, r2, dt=0.05, response_data=response_data)


if __name__ == "__main__":
    main()