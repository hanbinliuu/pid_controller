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


class TemperatureSystem:

    """温度系统模型：模拟温度动态响应、老化和扰动"""



    def __init__(self, K=0.8, T=30, L=5, noise_level=0.3, mode=Mode.STANDARD):

        self.mode = mode

        self.initial_K = K

        self.initial_T = T

        self.initial_L = L

        self.K = K  # 当前增益

        self.T = T  # 当前时间常数

        self.L = L  # 当前滞后时间

        self.noise_level = noise_level

        self.disturbance_handler = DisturbanceHandler(mode=mode)



        # 状态变量

        self.last_temp = Config.INIT_TEMPERATURE

        self.buffer = np.ones(int(np.ceil(L))) * self.last_temp

        self.valve_stiction_level = 0  # 阀门卡涩程度

        self.sensor_drift = 0  # 传感器漂移



    def apply_aging(self, time):

        """应用老化对系统参数的影响"""

        if time < Config.AGING_START_TIME:

            return



        # 老化因子（最大变化80%）

        aging_factor = min(0.002 * (time - Config.AGING_START_TIME), 0.8)



        # 根据模式调整老化速度

        if self.mode == Mode.ANTI_DISTURBANCE:

            aging_factor *= 0.8  # 减缓老化

        elif self.mode == Mode.ANTI_NOISE:

            aging_factor *= 0.9  # 减缓老化



        self.K = self.initial_K * (1 - aging_factor * 0.4)  # 增益降低

        self.T = self.initial_T * (1 + aging_factor * 0.8)  # 时间常数增大

        self.L = self.initial_L * (1 + aging_factor * 0.9)  # 滞后时间增加



        # 动态调整滞后缓冲器大小

        new_buffer_size = int(np.ceil(self.L))

        if len(self.buffer) != new_buffer_size:

            self.buffer = np.ones(new_buffer_size) * self.last_temp



    def add_disturbance(self, time, current_temp, valve_opening, disturbances):

        """添加扰动对温度的影响"""

        system_state = {

            'K': self.K,

            'T': self.T,

            'L': self.L,

            'initial_K': self.initial_K,

            'initial_T': self.initial_T,

            'initial_L': self.initial_L,

            'valve_stiction_level': self.valve_stiction_level,

            'sensor_drift': self.sensor_drift

        }



        for disturbance in disturbances:

            start = disturbance["time"]

            end = disturbance["time"] + disturbance["duration"]

            if start <= time < end:

                current_temp = self.disturbance_handler.apply_disturbance(

                    disturbance["type"], time, current_temp, valve_opening,

                    disturbance["amplitude"], disturbance["duration"], start, system_state

                )



        # 更新系统状态

        self.K = system_state['K']

        self.T = system_state['T']

        self.L = system_state['L']

        self.valve_stiction_level = system_state['valve_stiction_level']

        self.sensor_drift = system_state['sensor_drift']



        return current_temp



    def generate_non_step_input(self, t):

        """生成非阶跃输入信号（阀门开度，0-100%）"""

        data_handler = DataHandler()

        return data_handler._generate_default_input_signal(t)



    def simulate_with_input(self, t, u, disturbances):

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

            output_temp = self.add_disturbance(t[i], output_temp, u[i], disturbances)



            # 根据模式调整噪声水平

            if self.mode == Mode.ANTI_NOISE:

                # 抗噪声模式下降低噪声

                noise = np.random.normal(0, self.noise_level * 0.6)

            else:

                noise = np.random.normal(0, self.noise_level)



            output_temp += noise

            temp[i] = output_temp



        return temp



    def update(self, valve_opening, time, dt=1, disturbances=None):

        """实时更新系统温度"""

        if disturbances is None:

            disturbances = []

        self.apply_aging(time)



        # 应用阀门卡涩效应

        effective_valve = valve_opening

        if self.valve_stiction_level > 0:

            # 阀门卡涩：响应变慢

            effective_valve = effective_valve * (

                    1 - self.valve_stiction_level) + self.last_temp * self.valve_stiction_level * 0.1



        steady_state = Config.INIT_TEMPERATURE + effective_valve * self.K

        self.last_temp += (steady_state - self.last_temp) / self.T * dt



        # 处理滞后

        self.buffer = np.roll(self.buffer, 1)

        self.buffer[0] = self.last_temp

        output_temp = self.buffer[-1] if len(self.buffer) > 0 else self.last_temp



        # 添加扰动和噪声

        output_temp = self.add_disturbance(time, output_temp, valve_opening, disturbances)



        # 根据模式调整噪声水平

        if self.mode == Mode.ANTI_NOISE:

            # 抗噪声模式下降低噪声

            noise = np.random.normal(0, self.noise_level * 0.6)

        else:

            noise = np.random.normal(0, self.noise_level)



        output_temp += noise



        # 返回真实温度（不包含传感器漂移）

        return output_temp - self.sensor_drift




