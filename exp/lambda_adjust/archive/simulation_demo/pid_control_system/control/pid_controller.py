from collections import deque
import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode, PIDMode, DisturbanceType
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode, PIDMode, DisturbanceType
    from config.settings import Config


class PIDController:

    """PID控制器：实现PID控制与参数平滑更新"""



    def __init__(self, pb=100, ti=0, td=0, dt=1, u_min=Config.MV_MIN, u_max=Config.MV_MAX, mode=PIDMode.STANDARD,

                 system_mode=Mode.STANDARD):

        # 转换参数：pb = 100/Kp，ti = Ti，td = Td

        self.pb = self._clip_pb(pb)  # 比例带

        self.ti = self._clip_ti(ti)  # 积分时间

        self.td = self._clip_td(td)  # 微分时间



        # 从转换参数计算内部使用的Kp, Ti, Td

        self.Kp = 100 / self.pb if self.pb != 0 else 0  # 比例增益

        self.Ti = self.ti  # 积分时间

        self.Td = self.td  # 微分时间



        # 目标参数（用于平滑更新）

        self.target_pb = self.pb

        self.target_ti = self.ti

        self.target_td = self.td

        self.target_Kp = 100 / self.pb if self.pb != 0 else 0

        self.target_Ti = self.ti

        self.target_Td = self.td



        self.dt = dt

        self.u_min = u_min

        self.u_max = u_max



        # 控制状态

        self.last_error = 0.0

        self.integral = 0.0

        self.derivative = 0.0

        self.last_process_var = 0.0  # 用于微分先行

        self.mode = mode  # PID模式选择

        self.system_mode = system_mode  # 系统运行模式（用于调整参数）

        self.smoothing_factor = Config.PARAM_UPDATE_SMOOTH_FACTOR  # 平滑因子

        self.setpoint = 0.0  # 用于比例微分先行模式的设定值

        self.first_call = True  # 标记首次调用



        # 新增：性能指标跟踪

        self.error_history = deque(maxlen=200)

        self.control_effort_history = deque(maxlen=200)



        # 新增：流量控制优化参数

        self.flow_control_smooth_factor = 0.05  # 流量控制输出平滑因子

        self.last_output = 0.0  # 上次输出值，用于平滑



    def _clip_pb(self, pb):

        """限制Pb在合理范围内"""

        return np.clip(pb, Config.PB_MIN, Config.PB_MAX)



    def _clip_ti(self, ti):

        """限制Ti在合理范围内"""

        return np.clip(ti, Config.TI_MIN, Config.TI_MAX)



    def _clip_td(self, td):

        """限制Td在合理范围内"""

        return np.clip(td, Config.TD_MIN, Config.TD_MAX)



    def _update_integral(self, error, temp_output):

        """通用积分更新逻辑"""

        if self.Ti > Config.EPSILON:

            integral_term = (self.Kp / self.Ti) * error * self.dt

            # 预计算输出，判断是否饱和

            if not (self.u_min <= temp_output <= self.u_max):

                integral_term = 0  # 输出饱和时不累积积分

            self.integral += integral_term

            # 积分限幅

            self.integral = np.clip(self.integral, -self.u_max * 1.5, self.u_max * 1.5)



    def _update_derivative(self, value_diff, alpha=0.3):

        """通用微分更新逻辑，支持平滑系数"""

        if self.Td > Config.EPSILON:

            derivative_term = (self.Kp * self.Td) * value_diff / self.dt

            self.derivative = (1 - alpha) * self.derivative + alpha * derivative_term



    def compute(self, setpoint, process_var):

        """计算PID输出（含抗积分饱和）"""

        error = setpoint - process_var

        self.setpoint = setpoint  # 记录设定值



        # 记录误差和控制努力用于性能评估

        self.error_history.append(abs(error))

        self.control_effort_history.append(abs(self.derivative if hasattr(self, 'derivative') else 0))



        # 根据系统模式调整控制策略

        if self.system_mode == Mode.ANTI_DISTURBANCE:

            # 抗扰动模式：降低微分增益，减少对扰动的敏感性

            adjusted_Td = self.Td * 0.7

        elif self.system_mode == Mode.ANTI_NOISE:

            # 抗噪声模式：降低微分增益，减少对噪声的敏感性

            adjusted_Td = self.Td * 0.5

        elif self.system_mode == Mode.FLOW_CONTROL:

            # 流量控制模式：降低微分项，减少噪声影响

            adjusted_Td = self.Td * 0.2

        else:

            adjusted_Td = self.Td



        # 根据不同模式计算输出

        if self.mode == PIDMode.STANDARD:

            # 标准PID: u(t) = Kp * e(t) + Ki * ∫e(t)dt + Kd * de(t)/dt

            proportional = self.Kp * error



            # 预计算输出（不含积分项），用于积分饱和判断

            temp_output = proportional + self.integral + self.derivative



            # 更新积分项

            self._update_integral(error, temp_output)



            # 更新微分项（基于误差）

            if adjusted_Td > Config.EPSILON:

                error_diff = error - self.last_error

                self._update_derivative(error_diff, alpha=0.3)



        elif self.mode == PIDMode.DERIVATIVE_ON_MEASUREMENT:

            # 微分先行: u(t) = Kp * e(t) + Ki * ∫e(t)dt - Kd * dy(t)/dt

            proportional = self.Kp * error



            # 预计算输出（不含微分项），用于积分饱和判断

            temp_output = proportional + self.integral - self.derivative



            # 更新积分项

            self._update_integral(error, temp_output)



            # 更新微分项（基于测量值变化）

            if adjusted_Td > Config.EPSILON:

                process_var_diff = self.last_process_var - process_var

                self._update_derivative(process_var_diff, alpha=0.3)



        elif self.mode == PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT:

            # 比例微分先行: u(t) = Ki * ∫e(t)dt + Kp * (setpoint - y(t)) - Kd * dy(t)/dt

            proportional = self.Kp * (setpoint - process_var)  # 比例项基于设定值与测量值的差



            # 预计算输出（不含积分项），用于积分饱和判断

            temp_output = self.integral + proportional - self.derivative



            # 更新积分项

            self._update_integral(error, temp_output)



            # 更新微分项（基于测量值变化）

            if adjusted_Td > Config.EPSILON:

                process_var_diff = self.last_process_var - process_var

                self._update_derivative(process_var_diff, alpha=0.3)



        # 总输出与限幅

        if self.mode == PIDMode.PROPORTIONAL_DERIVATIVE_ON_MEASUREMENT:

            output = self.integral + proportional - self.derivative

        else:

            output = proportional + self.integral + self.derivative



        output = np.clip(output, self.u_min, self.u_max)

        self.last_error = error

        self.last_process_var = process_var  # 记录当前测量值



        # 平滑更新参数

        self._smooth_update()



        # 流量控制平滑输出

        if self.system_mode == Mode.FLOW_CONTROL:

            # 应用输出平滑，使控制信号变化更平滑

            output = self.last_output * (1 - self.flow_control_smooth_factor) + output * self.flow_control_smooth_factor

            self.last_output = output



        return output



    def _smooth_update(self):

        """平滑更新PID参数，避免突变"""

        self.pb = self.pb * (1 - self.smoothing_factor) + self.target_pb * self.smoothing_factor

        self.ti = self.ti * (1 - self.smoothing_factor) + self.target_ti * self.smoothing_factor

        self.td = self.td * (1 - self.smoothing_factor) + self.target_td * self.smoothing_factor



        # 重新计算内部Kp, Ti, Td

        self.Kp = 100 / self.pb if self.pb != 0 else 0

        self.Ti = self.target_ti

        self.Td = self.target_td



        # 重新限制参数边界

        self.pb = self._clip_pb(self.pb)

        self.ti = self._clip_ti(self.ti)

        self.td = self._clip_td(self.td)



    def set_target_params(self, pb, ti, td, reset_integral=False):

        """设置目标参数（用于平滑更新）"""

        self.target_pb = self._clip_pb(pb)

        self.target_ti = self._clip_ti(ti)

        self.target_td = self._clip_td(td)

        self.target_Kp = 100 / self.target_pb if self.target_pb != 0 else 0

        self.target_Ti = self.target_ti

        self.target_Td = self.target_td



        if reset_integral:

            self.integral = 0.0  # 参数更新时重置积分项



    def reset(self):

        """重置控制器状态"""

        self.last_error = 0.0

        self.integral = 0.0

        self.derivative = 0.0

        self.last_process_var = 0.0

        self.first_call = True



    def adjust_parameters_based_on_disturbance(self, disturbance_type):

        """根据扰动类型调整PID参数"""

        original_pb, original_ti, original_td = self.pb, self.ti, self.td



        if DisturbanceType.OVERSHOOT in disturbance_type:

            self.set_target_params(pb=self.pb * 1.1, ti=self.ti * 0.9, td=self.td * 0.8)

        elif DisturbanceType.STEADY_ERROR in disturbance_type:

            self.set_target_params(pb=self.pb * 0.9, ti=self.ti * 1.1, td=self.td * 1.2)

        elif DisturbanceType.SLOW_RECOVERY in disturbance_type:

            self.set_target_params(pb=self.pb * 0.8, ti=self.ti * 0.9, td=self.td * 1.1)

        elif DisturbanceType.VALVE_STICTION in disturbance_type:

            self.set_target_params(pb=self.pb * 1.2, ti=self.ti * 1.1, td=self.td * 0.9)

        elif DisturbanceType.SENSOR_DRIFT in disturbance_type:

            self.set_target_params(pb=self.pb * 1.0, ti=self.ti * 0.8, td=self.td * 1.3)

        elif DisturbanceType.HEAT_LOSS in disturbance_type:

            self.set_target_params(pb=self.pb * 0.8, ti=self.ti * 1.2, td=self.td * 1.0)

        elif DisturbanceType.CONTROL_VALVE_WEAR in disturbance_type:

            self.set_target_params(pb=self.pb * 1.1, ti=self.ti * 1.0, td=self.td * 0.9)

        elif DisturbanceType.THERMAL_INERTIA in disturbance_type:

            self.set_target_params(pb=self.pb * 0.9, ti=self.ti * 1.2, td=self.td * 1.1)

        elif DisturbanceType.FLOW_NOISE in disturbance_type:

            # 流量噪声：降低微分项

            self.set_target_params(pb=self.pb, ti=self.ti, td=0.0)

        elif DisturbanceType.FLOW_STICTION in disturbance_type:

            # 流量卡涩：降低比例增益，增加积分时间

            self.set_target_params(pb=self.pb * 1.2, ti=self.ti * 1.2, td=0.0)

        else:

            # 默认调整

            self.set_target_params(pb=self.pb * 0.95, ti=self.ti * 1.05, td=self.td * 1.05)



        print(f"🔧 扰动类型: {disturbance_type}")

        print(f"   参数调整: Pb: {original_pb:.2f} → {self.pb:.2f}%, "

              f"Ti: {original_ti:.1f}s → {self.ti:.1f}s, "

              f"Td: {original_td:.1f}s → {self.td:.1f}s")



    def get_performance_metrics(self):

        """获取性能指标"""

        if len(self.error_history) == 0:

            return 0, 0, 0

        error_array = np.array(list(self.error_history))

        control_effort_array = np.array(list(self.control_effort_history))



        # 计算 IAE (Integral Absolute Error)

        iae = np.mean(error_array)

        # 计算 ISE (Integral Square Error)

        ise = np.mean(error_array ** 2)

        # 计算控制努力

        control_effort = np.mean(control_effort_array)



        return iae, ise, control_effort





# ---系统辨识-----
