import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode, PIDMode, TuningMethod, DisturbanceType
    from ..config.settings import Config
    from ..control.system_identifier import SystemIdentifier
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode, PIDMode, TuningMethod, DisturbanceType
    from config.settings import Config
    from control.system_identifier import SystemIdentifier


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

            DisturbanceType.THERMAL_INERTIA: "cyan",

            DisturbanceType.FLOW_NOISE: "yellow",  # 新增

            DisturbanceType.FLOW_STICTION: "darkgreen"  # 新增

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



        # Lambda参数滑块和PID参数滑块

        plt.subplots_adjust(bottom=0.25)

        

        # Lambda滑块

        ax_lambda_slider = plt.axes([0.2, 0.15, 0.65, 0.03])

        lambda_slider = Slider(

            ax=ax_lambda_slider,

            label='Lambda 参数（减小→响应更快）',

            valmin=0.3 * system_params['T'],

            valmax=2 * system_params['T'],

            valinit=system_params['T'] * 0.6

        )

        

        # PID参数滑块

        ax_pb_slider = plt.axes([0.2, 0.11, 0.65, 0.03])

        pb_slider = Slider(

            ax=ax_pb_slider,

            label='Pb (比例带)',

            valmin=Config.PB_MIN,

            valmax=Config.PB_MAX,

            valinit=pid_params['Pb']

        )

        

        ax_ti_slider = plt.axes([0.2, 0.07, 0.65, 0.03])

        ti_slider = Slider(

            ax=ax_ti_slider,

            label='Ti (积分时间)',

            valmin=Config.TI_MIN,

            valmax=Config.TI_MAX,

            valinit=pid_params['Ti']

        )

        

        ax_td_slider = plt.axes([0.2, 0.03, 0.65, 0.03])

        td_slider = Slider(

            ax=ax_td_slider,

            label='Td (微分时间)',

            valmin=Config.TD_MIN,

            valmax=Config.TD_MAX,

            valinit=pid_params['Td']

        )

        

        # 添加预览轨迹线（用虚线表示）

        preview_line, = ax2.plot([], [], 'c--', label='PID参数预览轨迹', linewidth=2, alpha=0.8)



        plt.ion()

        plt.tight_layout(rect=[0, 0.1, 1, 1])

        plt.show(block=False)



        self.plot_data = {

            'axes': (ax2, ax3, ax4, ax5),

            'lines': (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line),

            'text': params_text,

            'slider': lambda_slider,

            'pid_sliders': (pb_slider, ti_slider, td_slider),

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



目标温度: {Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW}℃ | 初始温度: {Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0}℃"""

        text_obj.set_text(text)



    def update_plots(self, time_data, temp_data, valve_data, error_data, pb_data, ti_data, td_data,

                     update_lines, new_pid_time_data=None, new_pid_temp_data=None, no_pid_temp_data=None):

        """实时更新绘图数据"""

        (temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line) = self.plot_data[

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




