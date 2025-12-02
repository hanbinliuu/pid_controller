import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode
    from ..disturbance.handler import DisturbanceHandler
    from ..data.handler import DataHandler
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode
    from disturbance.handler import DisturbanceHandler
    from data.handler import DataHandler
    from config.settings import Config


class FlowSystem:

    """水阀流量系统模型：模拟流量动态响应"""



    def __init__(self, K=1.0, T=1.0, noise_level=0.5, mode=Mode.FLOW_CONTROL):

        self.mode = mode

        self.K = K  # 增益

        self.T = T  # 时间常数（流量系统通常很小）

        self.noise_level = noise_level

        self.disturbance_handler = DisturbanceHandler(mode=mode)



        # 状态变量

        self.last_flow = 0.0

        self.buffer = np.ones(1) * self.last_flow



        # 新增：流量控制平滑参数

        self.flow_smooth_factor = 0.1  # 流量变化平滑因子



    def add_disturbance(self, time, current_flow, valve_opening, disturbances):

        """添加扰动对流量的影响"""

        system_state = {

            'K': self.K,

            'T': self.T,

            'initial_K': self.K,

            'initial_T': self.T,

            'last_flow': self.last_flow

        }



        for disturbance in disturbances:

            start = disturbance["time"]

            end = disturbance["time"] + disturbance["duration"]

            if start <= time < end:

                current_flow = self.disturbance_handler.apply_disturbance(

                    disturbance["type"], time, current_flow, valve_opening,

                    disturbance["amplitude"], disturbance["duration"], start, system_state

                )



        # 更新系统状态

        self.K = system_state['K']

        self.T = system_state['T']

        self.last_flow = system_state['last_flow']



        return current_flow



    def generate_flow_input(self, t):

        """生成流量控制的输入信号（阀门开度，0-100%）"""

        data_handler = DataHandler()

        return data_handler._generate_flow_input_signal(t)



    def simulate_with_input(self, t, u, disturbances):

        """基于输入信号仿真流量响应"""

        flow = np.ones_like(t) * 0.0

        self.last_flow = 0.0



        for i in range(len(t)):

            dt = t[i] - t[i - 1] if i > 0 else 1

            steady_state = u[i] * self.K



            # 流量控制平滑算法

            new_flow = self.last_flow + (steady_state - self.last_flow) / self.T * dt

            # 应用平滑因子，使流量变化更平滑

            self.last_flow = self.last_flow * (1 - self.flow_smooth_factor) + new_flow * self.flow_smooth_factor



            # 添加扰动和噪声

            output_flow = self.add_disturbance(t[i], self.last_flow, u[i], disturbances)



            # 根据模式调整噪声水平

            if self.mode == Mode.ANTI_NOISE:

                # 抗噪声模式下降低噪声

                noise = np.random.normal(0, self.noise_level * 0.6)

            elif self.mode == Mode.FLOW_CONTROL:

                # 流量控制模式下可能噪声更大

                noise = np.random.normal(0, self.noise_level * 1.5)

            else:

                noise = np.random.normal(0, self.noise_level)



            output_flow += noise

            flow[i] = output_flow



        return flow



    def update(self, valve_opening, time, dt=1, disturbances=None):

        """实时更新系统流量"""

        if disturbances is None:

            disturbances = []



        steady_state = valve_opening * self.K



        # 流量控制平滑算法

        new_flow = self.last_flow + (steady_state - self.last_flow) / self.T * dt

        # 应用平滑因子，使流量变化更平滑

        self.last_flow = self.last_flow * (1 - self.flow_smooth_factor) + new_flow * self.flow_smooth_factor



        # 添加扰动和噪声

        output_flow = self.add_disturbance(time, self.last_flow, valve_opening, disturbances)



        # 根据模式调整噪声水平

        if self.mode == Mode.ANTI_NOISE:

            # 抗噪声模式下降低噪声

            noise = np.random.normal(0, self.noise_level * 0.6)

        elif self.mode == Mode.FLOW_CONTROL:

            # 流量控制模式下可能噪声更大

            noise = np.random.normal(0, self.noise_level * 1.5)

        else:

            noise = np.random.normal(0, self.noise_level)



        output_flow += noise



        return output_flow




