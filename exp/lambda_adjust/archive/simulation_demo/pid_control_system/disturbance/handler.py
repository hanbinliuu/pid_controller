import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode, DisturbanceType
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode, DisturbanceType
    from config.settings import Config


class DisturbanceHandler:

    """扰动处理模块：管理各种系统扰动"""



    def __init__(self, mode=Mode.STANDARD):

        self.mode = mode

        self.disturbance_functions = {

            DisturbanceType.OVERSHOOT: self._apply_overshoot,

            DisturbanceType.STEADY_ERROR: self._apply_steady_error,

            DisturbanceType.SLOW_RECOVERY: self._apply_slow_recovery,

            DisturbanceType.VALVE_STICTION: self._apply_valve_stiction,

            DisturbanceType.SENSOR_DRIFT: self._apply_sensor_drift,

            DisturbanceType.HEAT_LOSS: self._apply_heat_loss,

            DisturbanceType.CONTROL_VALVE_WEAR: self._apply_control_valve_wear,

            DisturbanceType.THERMAL_INERTIA: self._apply_thermal_inertia,

            DisturbanceType.FLOW_NOISE: self._apply_flow_noise,  # 新增

            DisturbanceType.FLOW_STICTION: self._apply_flow_stiction  # 新增

        }



    def apply_disturbance(self, disturbance_type, time, current_var, valve_opening,

                          amplitude, duration, start_time, system_state):

        """应用扰动对变量的影响"""

        if disturbance_type in self.disturbance_functions:

            return self.disturbance_functions[disturbance_type](

                time, current_var, valve_opening, amplitude, duration, start_time, system_state

            )

        return current_var



    # 温控相关

    def _apply_overshoot(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        decay = 1 - (time - start_time) / duration

        # 根据模式调整扰动强度（优化：使用配置字典）

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.OVERSHOOT)

        return current_temp + amplitude * (1.2 - decay) * mode_factor + np.random.normal(0, 1.2)



    def _apply_steady_error(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.STEADY_ERROR)

        turbulent = np.sin((time - start_time) * 0.1) * amplitude * 0.3

        return current_temp + amplitude * mode_factor + turbulent + np.random.normal(0, 0.9)



    def _apply_slow_recovery(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.SLOW_RECOVERY)

        fluctuation = np.sin((time - start_time) * 0.2) * amplitude * 0.8

        return current_temp + fluctuation * mode_factor + np.random.normal(0, 1.3)



    def _apply_valve_stiction(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        system_state['valve_stiction_level'] = amplitude * 0.1

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.VALVE_STICTION)

        return current_temp + np.random.normal(0, amplitude * 0.3 * mode_factor)



    def _apply_sensor_drift(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        sensor_drift = amplitude * np.sin((time - start_time) * 0.01)

        system_state['sensor_drift'] = sensor_drift

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.SENSOR_DRIFT)

        return current_temp + sensor_drift + np.random.normal(0, 0.5 * mode_factor)



    def _apply_heat_loss(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        loss_factor = 1 - amplitude * 0.001 * (time - start_time) / duration

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.HEAT_LOSS)

        return current_temp * loss_factor + np.random.normal(0, 0.8 * mode_factor)



    def _apply_control_valve_wear(self, time, current_temp, valve_opening, amplitude, duration, start_time,

                                  system_state):

        wear_factor = 1 - amplitude * 0.0005 * (time - start_time) / duration

        system_state['K'] = system_state['initial_K'] * wear_factor

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.CONTROL_VALVE_WEAR)

        return current_temp + np.random.normal(0, 0.6 * mode_factor)



    def _apply_thermal_inertia(self, time, current_temp, valve_opening, amplitude, duration, start_time, system_state):

        inertia_factor = 1 + amplitude * 0.001 * (time - start_time) / duration

        system_state['T'] = system_state['initial_T'] * inertia_factor

        mode_factor = Config.get_mode_factor(self.mode, DisturbanceType.THERMAL_INERTIA)

        return current_temp + np.random.normal(0, 0.7 * mode_factor)



    # 新增：流量相关扰动

    def _apply_flow_noise(self, time, current_flow, valve_opening, amplitude, duration, start_time, system_state):

        """流量噪声扰动"""

        noise_level = amplitude * 0.2

        return current_flow + np.random.normal(0, noise_level)



    def _apply_flow_stiction(self, time, current_flow, valve_opening, amplitude, duration, start_time, system_state):

        """流量阀门卡涩扰动"""

        stiction_level = amplitude * 0.1

        # 模拟阀门响应不灵敏

        effective_flow = current_flow * (1 - stiction_level) + system_state.get('last_flow',

                                                                                current_flow) * stiction_level

        system_state['last_flow'] = current_flow

        return effective_flow




