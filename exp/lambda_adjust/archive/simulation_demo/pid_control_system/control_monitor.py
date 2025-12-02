from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    # 尝试相对导入（作为包导入时）
    from .config.enums import Mode, PIDMode, TuningMethod
    from .config.settings import Config
    from .utils.logger import LoggerSetup
    from .disturbance.generator import DisturbanceGenerator
    from .disturbance.handler import DisturbanceHandler
    from .data.handler import DataHandler
    from .models.flow_system import FlowSystem
    from .models.temperature_system import TemperatureSystem
    from .control.pid_controller import PIDController
    from .control.system_identifier import SystemIdentifier
    from .analysis.state_analyzer import StateAnalyzer
    from .visualization.plot_manager import PlotManager
except ImportError:
    # 相对导入失败时，使用绝对导入（作为脚本运行时）
    # 添加父目录到路径
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    from config.enums import Mode, PIDMode, TuningMethod
    from config.settings import Config
    from utils.logger import LoggerSetup
    from disturbance.generator import DisturbanceGenerator
    from disturbance.handler import DisturbanceHandler
    from data.handler import DataHandler
    from models.flow_system import FlowSystem
    from models.temperature_system import TemperatureSystem
    from control.pid_controller import PIDController
    from control.system_identifier import SystemIdentifier
    from analysis.state_analyzer import StateAnalyzer
    from visualization.plot_manager import PlotManager

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



        # 选择数据来源

        t, pv_data, mv_data, sv_data, kp_data, ki_data, kd_data, pb_data, ti_data, td_data = self.data_handler.choose_data_source(

            data_type="dynamic_response")



        # 标记是否使用JSON数据

        using_json_data = pv_data is not None



        # 选择控制模式 - 优化：仿真模式下也允许选择流量控制选项

        system_mode = self.data_handler.choose_mode(using_json_data=using_json_data)

        self.logger.info(f"选择系统控制模式: {Config.MODES[system_mode]}")



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



        # 初始化系统与输入

        if system_mode == Mode.FLOW_CONTROL:

            # 流量控制模式使用不同系统

            initial_true_params = {'K': 1.0, 'T': 1.0, 'noise_level': 0.5}

            temp_system = FlowSystem(**initial_true_params, mode=system_mode)

        else:

            initial_true_params = {'K': 0.3, 'T': 20, 'L': 4, 'noise_level': 0.3}

            temp_system = TemperatureSystem(**initial_true_params, mode=system_mode)



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

                new_params = self.identifier.auto_tune_from_json(t, response_data, setpoint, tuning_method, system_mode, u_data=u)

                if new_params:

                    init_pb, init_ti, init_td = new_params['pb'], new_params['ti'], new_params['td']

                    print(f"✅ 基于JSON数据自动整定PID参数: Pb={init_pb:.2f}%, Ti={init_ti:.2f}s, Td={init_td:.2f}s")

                else:

                    if system_mode == Mode.FLOW_CONTROL:

                        K, T = self.identifier.identify_first_order(t, response_data, u)

                        L = 0.0  # 流量控制模式无滞后

                        init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

                    else:

                        K, T, L = self.identifier.identify_fopdt(t, response_data, u)

                        init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

        else:

            # 生成仿真数据（如未提供）

            initial_time = np.arange(0, 1000, 1)  # 初始生成1000个点

            if system_mode == Mode.FLOW_CONTROL:

                u = temp_system.generate_flow_input(initial_time)

            else:

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

            if system_mode == Mode.FLOW_CONTROL:

                K, T = self.identifier.identify_first_order(initial_time, response_data, u)

                L = 0.0  # 流量控制模式无滞后

                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

            else:

                K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)

                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)



        # 初始参数辨识

        print(

            f"\n全局初始值：{Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0}℃ | 目标值：{Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW}")

        print("正在辨识系统初始参数（K, T, L）...")

        if using_json_data:

            # 使用JSON数据进行初始参数辨识

            if system_mode == Mode.FLOW_CONTROL:

                K, T = self.identifier.identify_first_order(t, response_data, u)

                L = 0.0

            else:

                K, T, L = self.identifier.identify_fopdt(t, response_data, u)

        else:

            # 使用仿真数据进行初始参数辨识

            if system_mode == Mode.FLOW_CONTROL:

                K, T = self.identifier.identify_first_order(initial_time, response_data, u)

                L = 0.0

            else:

                K, T, L = self.identifier.identify_fopdt(initial_time, response_data, u)

        identified_params = {'K': K, 'T': T, 'L': L}



        # 启动实时监控

        print(

            f"\n启动控制监控 (系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]})...")

        self._run_real_time_monitor(u,

                                    setpoint=Config.TARGET_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else Config.TARGET_FLOW,

                                    true_params=initial_true_params,

                                    identified_params=identified_params, response_data=response_data,

                                    disturbances=disturbances, start_time=start_time, pid_mode=pid_mode,

                                    system_mode=system_mode, state_analyzer=state_analyzer,

                                    using_json_data=using_json_data,

                                    pb_data=pb_data, ti_data=ti_data, td_data=td_data, tuning_method=tuning_method)



    def _get_initial_params(self, K, T, L, tuning_method, system_mode):

        """

        统一的初始参数获取方法（优化：合并了流量控制和温度控制）

        

        Args:

            K: 静态增益

            T: 时间常数

            L: 滞后时间（流量控制模式下会被忽略）

            tuning_method: 整定方法

            system_mode: 系统模式

            

        Returns:

            Tuple[float, float, float]: (pb, ti, td)

        """

        if system_mode == Mode.FLOW_CONTROL:

            # 流量控制模式：使用专门的流量整定方法

            # 对于流量控制，Cohen-Coon可能不太适用，统一使用Lambda方法

            return self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)

        

        # 温度控制模式

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

                if system_mode == Mode.FLOW_CONTROL:

                    L = 0.0  # 流量控制模式无滞后

                init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)

        else:

            # 使用辨识得到的参数

            if system_mode == Mode.FLOW_CONTROL:

                L = 0.0  # 流量控制模式无滞后

            init_pb, init_ti, init_td = self._get_initial_params(K, T, L, tuning_method, system_mode)



        if system_mode == Mode.FLOW_CONTROL:

            system = FlowSystem(**true_params, mode=system_mode)

        else:

            system = TemperatureSystem(**true_params, mode=system_mode)

        pid = PIDController(pb=init_pb, ti=init_ti, td=init_td, dt=1, mode=pid_mode, system_mode=system_mode)



        # 初始化图表（在PID参数确定后）

        initial_pid_params = {'Pb': init_pb, 'Ti': init_ti, 'Td': init_td}

        fig, plot_data = self.plot_manager.init_real_time_fig(initial_time, u, setpoint, identified_params,

                                                              initial_pid_params, response_data, true_params,

                                                              disturbances, pid_mode, system_mode, tuning_method)

        (ax2, _, _, _) = plot_data['axes']

        params_text = plot_data['text']

        lambda_slider = plot_data['slider']

        pb_slider, ti_slider, td_slider = plot_data['pid_sliders']

        stabilization_line, update_lines, _ = plot_data['markers']

        temp_line, valve_line, error_line, pb_line, ti_line, td_line, new_pid_line, no_pid_temp_line, preview_line = plot_data[

            'lines']



        # 初始化当前温度

        if using_json_data:

            current_var = response_data[0] if len(response_data) > 0 else (

                Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0)

        else:

            current_var = Config.INIT_TEMPERATURE if system_mode != Mode.FLOW_CONTROL else 0.0



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

        print(f"静态增益 K = {K:.2f} | 时间常数 T = {T:.1f} s | 滞后 L = {L:.1f} s")

        print(f"初始PID参数：Pb={init_pb:.2f}%, Ti={init_ti:.1f}s, Td={init_td:.1f}s")

        if not using_json_data:

            print("\n随机扰动计划：")

            for d in disturbances:

                print(f"- {d['time']}s: {d['description']}（持续{d['duration']}s，幅值{d['amplitude']:.1f}℃）")

        else:

            print("\n使用JSON数据（不包含额外随机扰动）")

        print("=" * 50 + "\n")



        # 预览轨迹模拟函数

        def simulate_preview_trajectory(preview_pb, preview_ti, preview_td):

            """使用新的PID参数模拟未来一段时间的响应轨迹"""

            if len(time_data) == 0:

                return [], []

            

            # 从当前状态开始模拟

            preview_start_time = time_data[-1] if time_data else 0

            preview_duration = 300  # 预览未来300秒

            preview_steps = min(int(preview_duration), 300)

            

            # 创建预览用的PID控制器和系统副本

            preview_pid = PIDController(pb=preview_pb, ti=preview_ti, td=preview_td, dt=1, 

                                       mode=pid_mode, system_mode=system_mode)

            # 复制当前PID控制器的状态（积分项等）

            preview_pid.integral = pid.integral

            preview_pid.last_error = pid.last_error

            preview_pid.last_process_var = pid.last_process_var

            

            # 创建系统副本，复制当前状态

            if system_mode == Mode.FLOW_CONTROL:

                preview_system = FlowSystem(K=system.K, T=system.T, noise_level=system.noise_level, mode=system_mode)

                preview_system.last_flow = system.last_flow

            else:

                preview_system = TemperatureSystem(K=system.K, T=system.T, L=system.L, 

                                                   noise_level=system.noise_level, mode=system_mode)

                preview_system.last_temp = system.last_temp

                preview_system.buffer = system.buffer.copy() if hasattr(system, 'buffer') else np.array([])

            

            # 模拟预览轨迹

            preview_time_data = []

            preview_temp_data = []

            preview_current_var = current_var

            preview_time = preview_start_time

            

            # 设置随机种子以确保预览的确定性（可选）

            np.random.seed(42)

            

            for i in range(preview_steps):

                preview_time += 1

                # 计算控制输出

                preview_valve = preview_pid.compute(setpoint, preview_current_var)

                # 更新系统状态

                if system_mode == Mode.FLOW_CONTROL:

                    preview_current_var = preview_system.update(preview_valve, preview_time, disturbances=disturbances)

                else:

                    preview_current_var = preview_system.update(preview_valve, preview_time, disturbances=disturbances)

                

                preview_time_data.append(preview_time)

                preview_temp_data.append(preview_current_var)

            

            # 恢复随机种子

            np.random.seed()

            

            return preview_time_data, preview_temp_data

        

        # Lambda滑块回调

        def on_lambda_slider_change(val):

            nonlocal K, T, L

            if system_mode == Mode.FLOW_CONTROL:

                new_pb, new_ti, new_td = self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)

            else:

                new_pb, new_ti, new_td = self.identifier.lambda_tuning(K, T, L, val, mode=system_mode)

            # 更新PID滑块的值

            pb_slider.set_val(new_pb)

            ti_slider.set_val(new_ti)

            td_slider.set_val(new_td)

            pid.set_target_params(new_pb, new_ti, new_td)

            self.plot_manager.update_params_text(params_text, identified_params,

                                                 {'Pb': pid.target_pb, 'Ti': pid.target_ti, 'Td': pid.target_td},

                                                 val, params_update_count, initial_valid_params, pid_mode, system_mode,

                                                 tuning_method)

            # 更新预览轨迹

            preview_t, preview_y = simulate_preview_trajectory(new_pb, new_ti, new_td)

            preview_line.set_data(preview_t, preview_y)

            fig.canvas.draw_idle()

        

        # 标记是否通过滑块手动调整了参数（用于扰动检测）

        manual_param_adjusted = False

        manual_adjust_time = None

        

        # PID参数滑块回调

        def on_pid_slider_change(val=None):

            """当PID参数滑块改变时，更新预览轨迹并应用参数"""

            nonlocal manual_param_adjusted, manual_adjust_time

            

            preview_pb = pb_slider.val

            preview_ti = ti_slider.val

            preview_td = td_slider.val

            

            # 更新预览轨迹

            preview_t, preview_y = simulate_preview_trajectory(preview_pb, preview_ti, preview_td)

            preview_line.set_data(preview_t, preview_y)

            

            # 实际应用参数到控制器（滑块调整后立即应用）

            pid.set_target_params(preview_pb, preview_ti, preview_td, reset_integral=False)

            

            # 标记手动调整参数的时间和标志

            manual_param_adjusted = True

            manual_adjust_time = time if len(time_data) > 0 else 0

            

            # 更新参数文本显示

            self.plot_manager.update_params_text(params_text, identified_params,

                                                 {'Pb': preview_pb, 'Ti': preview_ti, 'Td': preview_td},

                                                 lambda_slider.val, params_update_count, initial_valid_params, 

                                                 pid_mode, system_mode, tuning_method)

            

            print(f"🔧 手动调整PID参数: Pb={preview_pb:.2f}%, Ti={preview_ti:.1f}s, Td={preview_td:.1f}s")

            self.logger.info(f"手动调整PID参数: Pb={preview_pb:.2f}%, Ti={preview_ti:.1f}s, Td={preview_td:.1f}s (时间: {manual_adjust_time:.0f}s)")

            

            fig.canvas.draw_idle()

        

        lambda_slider.on_changed(on_lambda_slider_change)

        pb_slider.on_changed(on_pid_slider_change)

        ti_slider.on_changed(on_pid_slider_change)

        td_slider.on_changed(on_pid_slider_change)



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

            print(

                f"📊 仿真模式：从初始温度 {'0.0' if system_mode == Mode.FLOW_CONTROL else str(Config.INIT_TEMPERATURE)}℃ 上升到目标温度 {setpoint}℃")



        # 为可视化新PID参数下的仿真轨迹，我们创建一个数组来存储仿真数据

        new_pid_time_data = []

        new_pid_temp_data = []

        new_pid_simulated = False  # 标记是否已开始新PID参数下的仿真



        # 初始化无PID控制的系统（用于对比）

        if system_mode == Mode.FLOW_CONTROL:

            no_pid_system = FlowSystem(**true_params, mode=system_mode)

        else:

            no_pid_system = TemperatureSystem(**true_params, mode=system_mode)

        # 记录初始值

        no_pid_current_var = current_var

        # 使用初始输入信号模拟无PID控制的温度变化

        no_pid_input_signal = u[0] if len(u) > 0 else 25



        try:

            while True:  # 无限运行主循环

                # 如果使用JSON数据，则直接从数据中获取当前温度

                if using_json_data:

                    # 检查是否还有JSON数据可读取

                    if step < len(response_data):

                        # 从JSON数据中获取当前温度

                        current_var = response_data[step]

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

                    valve_opening = pid.compute(setpoint, current_var)

                    current_var = system.update(valve_opening, time, disturbances=disturbances)



                # 计算无PID控制的温度变化（修正：使用固定输入信号）

                if using_json_data:

                    # 如果使用JSON数据，无PID控制的温度应该跟随输入信号

                    # 但为了与PID控制形成对比，我们使用一个固定输入信号

                    no_pid_input_signal = u[step] if step < len(u) else no_pid_input_signal

                else:

                    # 在仿真模式下，使用当前输入信号

                    no_pid_input_signal = u[step] if step < len(u) else 50.0



                # 使用相同输入信号但无PID控制更新无PID温度

                no_pid_current_var = no_pid_system.update(no_pid_input_signal, time, disturbances=disturbances)

                no_pid_temp_data.append(no_pid_current_var)



                error = setpoint - current_var



                # 记录数据

                time_data.append(time)

                temp_data.append(current_var)

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

                # 优化：即使手动调整了参数，如果出现扰动也要重新整定

                if not in_pid_tuning_phase:

                    # 使用优化的扰动检测算法

                    is_disturbance, disturbance_desc = state_analyzer.detect_instability_optimized(

                        temp_data, setpoint, valve_data, time_data

                    )



                    # 如果手动调整参数后出现扰动，需要重新整定

                    # 给手动调整后的参数一些适应时间（比如50秒），如果之后仍不稳定则重新整定

                    should_retune = False

                    if is_disturbance:

                        if manual_param_adjusted and manual_adjust_time is not None:

                            # 手动调整参数后，如果50秒后仍检测到扰动，说明参数不合适，需要重新整定

                            if time - manual_adjust_time > 50:

                                should_retune = True

                                print(f"\n⚠️ 手动调整的参数在扰动下表现不佳，将重新整定参数...")

                                self.logger.warning(f"手动调整的参数在扰动下表现不佳，开始重新整定 (调整时间: {manual_adjust_time:.0f}s, 当前时间: {time:.0f}s)")

                        else:

                            # 非手动调整的情况，正常处理扰动

                            should_retune = True



                    if is_disturbance and should_retune:

                        # 检查当前时间是否在任何手动定义的扰动区间内（仅在仿真模式下）

                        current_disturbance = None

                        if not using_json_data:

                            current_disturbance = next((d for d in disturbances

                                                        if d["time"] <= time < d["time"] + d["duration"]), None)



                        if current_disturbance:

                            # 扰动开始后50s内强制更新参数（避免初期波动误判）

                            if not current_disturbance['updated'] and (time - current_disturbance["time"]) > 50:

                                print(f"\n⚠️ 检测到[{current_disturbance['description']}]，自动重新整定参数...")

                                self.logger.warning(

                                    f"检测到扰动[{current_disturbance['description']}]，开始自动重新整定参数...")



                                # 使用统一的参数更新方法

                                new_pb, new_ti, new_td, new_K, new_T, new_L = self._update_pid_params_for_disturbance(

                                    time, time_data, temp_data, valve_data, system_mode, identified_params,

                                    lambda_slider, tuning_method, current_disturbance)

                                K, T, L = new_K, new_T, new_L

                                lambda_val = lambda_slider.val



                                # 执行参数更新（带平滑）

                                pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)

                                

                                # 同步更新滑块值（如果是手动调整导致的重新整定）

                                if manual_param_adjusted:

                                    pb_slider.set_val(new_pb)

                                    ti_slider.set_val(new_ti)

                                    td_slider.set_val(new_td)

                                    manual_param_adjusted = False  # 重置手动调整标志

                                    print(f"🔄 已更新PID滑块值以匹配重新整定的参数")

                                

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



                                # 进入PID整定阶段，设置标志和时间

                                in_pid_tuning_phase = True

                                tuning_start_time = time



                                # 开始基于新PID参数的仿真

                                new_pid_simulated = True

                                new_pid_time_data = [time]

                                new_pid_temp_data = [current_var]



                        # 对于JSON数据，直接检测扰动并更新参数（不依赖预定义的扰动）

                        # 或者手动调整参数后出现扰动的情况

                        elif using_json_data or (manual_param_adjusted and should_retune):

                            if manual_param_adjusted:

                                print(f"\n⚠️ 手动调整的参数在扰动下表现不佳，自动重新整定参数...")

                                self.logger.warning(f"手动调整的参数在扰动下表现不佳，开始自动重新整定参数...")

                            else:

                                print(f"\n⚠️ 检测到系统扰动，自动重新整定参数...")

                                self.logger.warning(f"检测到系统扰动，开始自动重新整定参数...")



                            # 使用统一的参数更新方法（JSON数据或手动调整后无预定义扰动）

                            new_pb, new_ti, new_td, new_K, new_T, new_L = self._update_pid_params_for_disturbance(

                                time, time_data, temp_data, valve_data, system_mode, identified_params,

                                lambda_slider, tuning_method, current_disturbance=None)

                            K, T, L = new_K, new_T, new_L

                            lambda_val = lambda_slider.val



                            # 执行参数更新（带平滑）

                            pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)

                            

                            # 同步更新滑块值（如果是手动调整导致的重新整定）

                            if manual_param_adjusted:

                                pb_slider.set_val(new_pb)

                                ti_slider.set_val(new_ti)

                                td_slider.set_val(new_td)

                                manual_param_adjusted = False  # 重置手动调整标志

                                print(f"🔄 已更新PID滑块值以匹配重新整定的参数")

                            

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



                            # 进入PID整定阶段，设置标志和时间

                            in_pid_tuning_phase = True

                            tuning_start_time = time



                            # 开始基于新PID参数的仿真

                            new_pid_simulated = True

                            new_pid_time_data = [time]

                            new_pid_temp_data = [current_var]



                # 在参数更新后，模拟新PID参数下的温度响应

                if new_pid_simulated and len(time_data) > len(new_pid_time_data):

                    # 优化：重用PID控制器，只在参数更新时重新创建

                    if not hasattr(self, '_new_pid_controller') or self._new_pid_controller is None:

                        self._new_pid_controller = PIDController(pb=pid.pb, ti=pid.ti, td=pid.td, dt=1, 

                                                                  mode=pid_mode, system_mode=system_mode)

                    else:

                        # 更新参数而不重新创建对象

                        self._new_pid_controller.set_target_params(pid.pb, pid.ti, pid.td)

                    

                    new_valve_opening = self._new_pid_controller.compute(setpoint, new_pid_temp_data[-1])

                    # 优化：消除重复的system.update调用

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

                            print(f"🎉 {d['description']}已恢复稳定（{time:.0f}s），当前温度: {current_var:.1f}℃")

                            self.logger.info(

                                f"扰动 {d['description']} 已恢复稳定 - 时间: {time:.0f}s, 温度: {current_var:.1f}℃")



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

                        f"时间: {time:.0f}s | 系统模式: {Config.MODES[system_mode]} | PID模式: {Config.PID_MODES[pid_mode]} | 整定方法: {Config.TUNING_METHODS[tuning_method]} | 数据源: {'JSON' if using_json_data else '仿真'} | 实际响应: {current_var:.1f}℃ | 无PID控制: {no_pid_current_var:.1f}℃ | 误差: {error:.2f}℃ | "

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

                    if system_mode == Mode.FLOW_CONTROL:

                        new_u = system.generate_flow_input(new_time)

                    else:

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

                f"当前实际响应: {current_var:.1f}℃ | 无PID控制: {no_pid_current_var:.1f}℃ | 误差：{error:.2f}℃")

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

            self.logger.info(f"中断时温度: {current_var:.1f}℃, 误差: {error:.2f}℃, 更新次数: {params_update_count}")

            self.logger.info(f"中断时PID参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")

            self.logger.info(

                f"系统模式: {Config.MODES[system_mode]}, PID模式: {Config.PID_MODES[pid_mode]}, 整定方法: {Config.TUNING_METHODS[tuning_method]}")



            plt.ioff()

            plt.close(fig)



    def _get_updated_params(self, K, T, L, lambda_val, tuning_method, system_mode):

        """根据整定方法获取更新后的PID参数"""

        if system_mode == Mode.FLOW_CONTROL:

            # 流量控制模式统一使用Lambda方法

            return self.identifier.lambda_tuning_for_flow(K, T, mode=system_mode)

        

        # 温度控制模式

        if tuning_method == TuningMethod.LAMBDA:

            return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)

        elif tuning_method == TuningMethod.COHEN_COON:

            return self.identifier.cohen_coon_tuning(K, T, L)

        else:

            # 默认使用Lambda方法

            return self.identifier.lambda_tuning(K, T, L, lambda_val, mode=system_mode)

    

    def _update_pid_params_for_disturbance(self, time, time_data, temp_data, valve_data,

                                          system_mode, identified_params, lambda_slider,

                                          tuning_method, current_disturbance=None):

        """

        统一的PID参数更新逻辑（优化：消除重复代码）

        

        Args:

            time: 当前时间

            time_data: 时间数据列表

            temp_data: 温度数据列表

            valve_data: 阀门数据列表

            system_mode: 系统模式

            identified_params: 已辨识的参数字典

            lambda_slider: Lambda滑块对象

            tuning_method: 整定方法

            current_disturbance: 当前扰动（可选）

            

        Returns:

            Tuple: (new_pb, new_ti, new_td, new_K, new_T, new_L)

        """

        # 提取窗口数据

        window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)

        window_t = np.array(time_data[window_start:]) - time_data[window_start]

        window_u = np.array(valve_data[window_start:])

        window_y = np.array(temp_data[window_start:])

        

        # 重新辨识系统参数

        if system_mode == Mode.FLOW_CONTROL:

            new_K, new_T = self.identifier.identify_first_order(window_t, window_y, window_u)

            new_L = 0.0

        else:

            new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)

        

        identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})

        K, T, L = new_K, new_T, new_L

        

        # 获取新PID参数

        lambda_val = lambda_slider.val

        new_pb, new_ti, new_td = self._get_updated_params(K, T, L, lambda_val, tuning_method, system_mode)

        

        # 按扰动类型优化参数（如果有）

        if current_disturbance:

            new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(

                current_disturbance["type"], new_pb, new_ti, new_td)

        

        return new_pb, new_ti, new_td, new_K, new_T, new_L



    def _process_single_step(self, using_json_data, step, response_data, u, pid, system, 

                            setpoint, time, disturbances, no_pid_system, no_pid_input_signal,

                            system_mode, current_var):

        """

        处理单步仿真逻辑（优化：拆分主循环中的单步处理）

        

        Args:

            current_var: 当前变量值（温度或流量）

        

        Returns:

            Tuple: (current_var, valve_opening, no_pid_current_var, error) 或 None（如果数据已读完）

        """

        if using_json_data:

            if step < len(response_data):

                current_var = response_data[step]

                valve_opening = u[step] if step < len(u) else 50.0

            else:

                return None  # 数据已读完

        else:

            valve_opening = pid.compute(setpoint, current_var)

            current_var = system.update(valve_opening, time, disturbances=disturbances)

        

        # 计算无PID控制的温度变化

        if using_json_data:

            no_pid_input_signal = u[step] if step < len(u) else no_pid_input_signal

        else:

            no_pid_input_signal = u[step] if step < len(u) else 50.0

        

        no_pid_current_var = no_pid_system.update(no_pid_input_signal, time, disturbances=disturbances)

        error = setpoint - current_var

        

        return current_var, valve_opening, no_pid_current_var, error



    def _check_and_update_params_for_disturbance(self, time, time_data, temp_data, valve_data,

                                                  is_disturbance, should_retune, current_disturbance,

                                                  using_json_data, manual_param_adjusted, manual_adjust_time,

                                                  system_mode, identified_params, lambda_slider,

                                                  tuning_method, pid, pb_slider, ti_slider, td_slider,

                                                  ax2, update_lines, params_text, initial_valid_params,

                                                  pid_mode, params_update_count, current_var):

        """

        检查扰动并更新PID参数（优化：拆分主循环中的扰动处理逻辑）

        

        Returns:

            Tuple: (updated, new_pid_simulated, new_pid_time_data, new_pid_temp_data, 

                   in_pid_tuning_phase, tuning_start_time, params_update_count, manual_param_adjusted)

        """

        if not is_disturbance or not should_retune:

            return False, False, [], [], False, None, params_update_count, manual_param_adjusted

        

        # 窗口数据提取

        window_start = max(0, len(time_data) - Config.IDENTIFY_WINDOW)

        window_t = np.array(time_data[window_start:]) - time_data[window_start]

        window_u = np.array(valve_data[window_start:])

        window_y = np.array(temp_data[window_start:])

        

        # 重新辨识与整定

        if system_mode == Mode.FLOW_CONTROL:

            new_K, new_T = self.identifier.identify_first_order(window_t, window_y, window_u)

            new_L = 0.0

            identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})

            lambda_val = lambda_slider.val

            new_pb, new_ti, new_td = self.identifier.lambda_tuning_for_flow(new_K, new_T, mode=system_mode)

        else:

            new_K, new_T, new_L = self.identifier.identify_fopdt(window_t, window_y, window_u)

            identified_params.update({'K': new_K, 'T': new_T, 'L': new_L})

            lambda_val = lambda_slider.val

            new_pb, new_ti, new_td = self._get_updated_params(new_K, new_T, new_L, lambda_val, 

                                                              tuning_method, system_mode)

        

        # 按扰动类型优化参数

        if current_disturbance:

            new_pb, new_ti, new_td = self._adjust_pid_for_disturbance(

                current_disturbance["type"], new_pb, new_ti, new_td)

        

        # 执行参数更新

        pid.set_target_params(new_pb, new_ti, new_td, reset_integral=True)

        

        # 同步更新滑块值

        if manual_param_adjusted:

            pb_slider.set_val(new_pb)

            ti_slider.set_val(new_ti)

            td_slider.set_val(new_td)

            manual_param_adjusted = False

            print(f"🔄 已更新PID滑块值以匹配重新整定的参数")

        

        update_line = ax2.axvline(time, color='blue', linestyle='--', alpha=0.5)

        update_lines.append(update_line)

        params_update_count += 1

        

        if current_disturbance:

            current_disturbance['updated'] = True

        

        # 记录日志

        self.logger.info(f"参数更新 {params_update_count} 次 - 时间: {time:.0f}s")

        if current_disturbance:

            self.logger.info(f"扰动类型: {current_disturbance['type']} - {current_disturbance['description']}")

        self.logger.info(f"新参数: Pb={new_pb:.2f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")

        self.logger.info(f"旧参数: Pb={pid.pb:.2f}%, Ti={pid.ti:.1f}s, Td={pid.td:.1f}s")

        

        # 打印参数变化

        print(f"参数更新 {params_update_count} 次：")

        print(f"Pb: {pid.pb:.2f}% → {new_pb:.2f}%")

        print(f"Ti: {pid.ti:.1f}s → {new_ti:.1f}s")

        print(f"Td: {pid.td:.1f}s → {new_td:.1f}s\n")

        

        self.plot_manager.update_params_text(params_text, identified_params,

                                             {'Pb': new_pb, 'Ti': new_ti, 'Td': new_td},

                                             lambda_val, params_update_count,

                                             initial_valid_params, pid_mode, system_mode, tuning_method)

        

        # 开始基于新PID参数的仿真

        new_pid_simulated = True

        new_pid_time_data = [time]

        new_pid_temp_data = [current_var]

        

        # 进入PID整定阶段

        in_pid_tuning_phase = True

        tuning_start_time = time

        

        return True, new_pid_simulated, new_pid_time_data, new_pid_temp_data, \
            in_pid_tuning_phase, tuning_start_time, params_update_count, manual_param_adjusted



    def _adjust_pid_for_disturbance(self, disturbance_type, pb, ti, td):

        """

        根据扰动类型调整PID参数（优化：使用配置字典替代if-elif链）

        

        Args:

            disturbance_type: 扰动类型

            pb: 比例带

            ti: 积分时间

            td: 微分时间

            

        Returns:

            Tuple[float, float, float]: 调整后的 (pb, ti, td)

        """

        # 从配置字典获取调整策略

        if disturbance_type not in Config.DISTURBANCE_ADJUSTMENT_STRATEGIES:

            self.logger.warning(f"未知的扰动类型: {disturbance_type}，不进行调整")

            return pb, ti, td

        

        strategy = Config.DISTURBANCE_ADJUSTMENT_STRATEGIES[disturbance_type]

        original_pb, original_ti, original_td = pb, ti, td

        

        # 应用调整因子

        pb *= strategy['pb']

        ti *= strategy['ti']

        td = strategy['td'] if strategy['td'] == 0.0 else td * strategy['td']  # 特殊处理：td=0.0表示关闭微分

        

        # 应用全局参数边界保护

        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)

        ti = np.clip(ti, Config.TI_MIN, Config.TI_MAX)

        td = np.clip(td, Config.TD_MIN, Config.TD_MAX)

        

        # 记录调整信息

        changes = []

        if abs(pb - original_pb) > 0.01:

            changes.append(f"Pb: {original_pb:.2f}% → {pb:.2f}%")

        if abs(ti - original_ti) > 0.01:

            changes.append(f"Ti: {original_ti:.1f}s → {ti:.1f}s")

        if abs(td - original_td) > 0.01:

            changes.append(f"Td: {original_td:.1f}s → {td:.1f}s")

        

        if changes:

            change_text = ", ".join(changes)

            print(f"🔧 {strategy['description']}：{change_text}")

            self.logger.info(f"{strategy['description']} - {change_text}")

        

        return pb, ti, td




