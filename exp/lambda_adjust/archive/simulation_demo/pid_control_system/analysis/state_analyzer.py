from collections import deque
import numpy as np
import sys
import os

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.enums import Mode
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    _current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.enums import Mode
    from config.settings import Config


class StateAnalyzer:

    """系统状态分析工具：判断稳定性与扰动"""



    def __init__(self, mode=Mode.STANDARD):

        self.mode = mode

        # 用于检测异常模式的滑动窗口

        self.temp_window = deque(maxlen=Config.DETECTION_WINDOW)

        self.error_window = deque(maxlen=Config.DETECTION_WINDOW)

        self.valve_window = deque(maxlen=Config.DETECTION_WINDOW)

        self.time_window = deque(maxlen=Config.DETECTION_WINDOW)



        # 新增：自适应窗口大小

        self.current_window_size = Config.DETECTION_WINDOW

        self.window_growth_factor = 1.05  # 窗口增长因子



        # 新增：性能指标跟踪

        self.performance_history = deque(maxlen=100)

        self.disturbance_count = 0

        self.last_disturbance_time = 0

        

        # 优化：缓存统计结果，减少重复计算

        self._cached_stats = {}

        self._cache_valid = False

        self._last_data_hash = None



    def is_stable(self, temp_data, setpoint):

        """判断系统是否稳定在目标温度附近"""

        if len(temp_data) < Config.STABILIZATION_WINDOW:

            return False

        recent_temps = np.array(temp_data[-Config.STABILIZATION_WINDOW:])



        # 根据模式调整稳定阈值

        if self.mode == Mode.ANTI_DISTURBANCE:

            threshold = Config.STABILIZATION_THRESHOLD * 1.2  # 放宽稳定阈值

        elif self.mode == Mode.ANTI_NOISE:

            threshold = Config.STABILIZATION_THRESHOLD * 1.1  # 略微放宽稳定阈值

        elif self.mode == Mode.FLOW_CONTROL:

            threshold = Config.STABILIZATION_THRESHOLD * 0.8  # 流量控制更严格

        else:

            threshold = Config.STABILIZATION_THRESHOLD



        # 均值需接近目标温度（±0.5℃）

        mean_temp = np.mean(recent_temps)

        if not (setpoint - 0.5 <= mean_temp <= setpoint + 0.5):

            return False

        # 波动判断

        deviations = np.abs(recent_temps - setpoint)

        return (np.all(deviations < threshold) and

                np.std(deviations) < threshold / 2)



    def _update_cached_stats(self, temp_data, valve_data, setpoint, window_size):

        """

        更新缓存的统计信息（优化：减少重复计算）

        

        Args:

            temp_data: 温度数据数组

            valve_data: 阀门数据数组

            setpoint: 目标温度

            window_size: 窗口大小

        """

        # 计算数据哈希，判断是否需要更新缓存

        data_hash = hash((len(temp_data), window_size, setpoint))

        if self._cache_valid and self._last_data_hash == data_hash:

            return  # 缓存有效，无需更新

        

        # 获取窗口数据

        recent_temps = np.array(temp_data[-window_size:])

        recent_valves = np.array(valve_data[-window_size:])

        errors = recent_temps - setpoint

        

        # 计算并缓存统计量

        self._cached_stats = {

            'mean_error': np.mean(errors),

            'std_error': np.std(errors),

            'max_error': np.max(np.abs(errors)),

            'temp_std': np.std(recent_temps),

            'recent_temps': recent_temps,

            'recent_valves': recent_valves,

            'errors': errors,

        }

        

        # 温度变化率

        if len(recent_temps) > 1:

            temp_deriv = np.diff(recent_temps)

            self._cached_stats['mean_abs_deriv'] = np.mean(np.abs(temp_deriv))

            self._cached_stats['temp_deriv'] = temp_deriv

        else:

            self._cached_stats['mean_abs_deriv'] = 0

            self._cached_stats['temp_deriv'] = np.array([0])

        

        # 阀门动作

        if len(recent_valves) > 1:

            valve_changes = np.diff(recent_valves)

            self._cached_stats['valve_activity'] = np.sum(np.abs(valve_changes))

            self._cached_stats['valve_changes'] = valve_changes

        else:

            self._cached_stats['valve_activity'] = 0

            self._cached_stats['valve_changes'] = np.array([0])

        

        # 趋势斜率

        if len(recent_temps) > 20:

            x = np.arange(len(recent_temps))

            coeffs = np.polyfit(x, recent_temps, 1)

            self._cached_stats['trend_slope'] = abs(coeffs[0])

        else:

            self._cached_stats['trend_slope'] = 0

        

        # 阀门振荡

        if len(recent_valves) > 10:

            valve_changes_abs = np.abs(np.diff(recent_valves))

            self._cached_stats['valve_oscillation'] = np.mean(valve_changes_abs)

        else:

            self._cached_stats['valve_oscillation'] = 0

        

        # 温度模式变化

        if len(recent_temps) > 30:

            first_half = recent_temps[:len(recent_temps) // 2]

            second_half = recent_temps[len(recent_temps) // 2:]

            self._cached_stats['temp_pattern_change'] = abs(np.std(second_half) - np.std(first_half))

        else:

            self._cached_stats['temp_pattern_change'] = 0

        

        # 预测残差

        if len(recent_temps) > 40:

            mid_point = len(recent_temps) // 2

            first_half = recent_temps[:mid_point]

            second_half = recent_temps[mid_point:mid_point + len(first_half)]

            predicted_second_half = np.full_like(second_half, np.mean(first_half))

            self._cached_stats['prediction_residual'] = np.mean(np.abs(second_half - predicted_second_half))

        else:

            self._cached_stats['prediction_residual'] = 0

        

        # 自相关性

        if len(recent_temps) > 20 and len(recent_temps) > 1:

            autocorr = np.corrcoef(recent_temps[:-1], recent_temps[1:])[0, 1]

            self._cached_stats['autocorr_strength'] = abs(autocorr) if not np.isnan(autocorr) else 0

        else:

            self._cached_stats['autocorr_strength'] = 0

        

        # 更新缓存状态

        self._cache_valid = True

        self._last_data_hash = data_hash



    def detect_instability_optimized(self, temp_data, setpoint, valve_data, time_data):

        """

        优化的扰动检测算法 - 增强对轻微扰动的检测能力（优化：使用缓存减少重复计算）

        """

        if len(temp_data) < Config.MIN_DETECTION_WINDOW:

            return False, ""



        # 获取当前窗口的数据 - 使用自适应窗口大小

        window_size = min(len(temp_data), self.current_window_size)

        window_size = int(window_size)

        

        # 更新缓存统计信息（仅在需要时计算）

        self._update_cached_stats(temp_data, valve_data, setpoint, window_size)

        

        # 从缓存中获取统计量（优化：避免重复计算）

        mean_error = self._cached_stats['mean_error']

        std_error = self._cached_stats['std_error']

        max_error = self._cached_stats['max_error']

        temp_std = self._cached_stats['temp_std']

        mean_abs_deriv = self._cached_stats['mean_abs_deriv']

        valve_activity = self._cached_stats['valve_activity']

        trend_slope = self._cached_stats['trend_slope']

        valve_oscillation = self._cached_stats['valve_oscillation']

        temp_pattern_change = self._cached_stats['temp_pattern_change']

        prediction_residual = self._cached_stats['prediction_residual']

        autocorr_strength = self._cached_stats['autocorr_strength']



        # 10. 基于模式的自适应阈值调整

        error_threshold = Config.ERROR_THRESHOLD

        std_threshold = Config.STD_THRESHOLD

        slope_threshold = Config.SLOPE_THRESHOLD

        valve_change_threshold = Config.VALVE_CHANGE_THRESHOLD



        if self.mode == Mode.ANTI_DISTURBANCE:

            # 抗扰动模式：降低检测灵敏度，避免误判

            error_threshold *= 1.5

            std_threshold *= 1.4

            slope_threshold *= 1.3

            valve_change_threshold *= 1.5

        elif self.mode == Mode.ANTI_NOISE:

            # 抗噪声模式：降低检测灵敏度，避免噪声误判

            error_threshold *= 1.8

            std_threshold *= 1.6

            slope_threshold *= 1.5

            valve_change_threshold *= 1.8

        elif self.mode == Mode.FLOW_CONTROL:

            # 流量控制模式：提高检测灵敏度，因为响应快

            error_threshold *= 0.7

            std_threshold *= 0.8

            slope_threshold *= 0.6

            valve_change_threshold *= 0.9



        # 11. 综合判断 - 使用加权评分机制

        scores = {}



        # 超调检测

        overshoot_score = (max_error / (error_threshold * 0.7)) * (mean_error / 0.8) * (std_error / 0.4)

        if overshoot_score > 1.0:

            scores['overshoot'] = overshoot_score



        # 稳态误差检测

        steady_error_score = abs(mean_error) / 1.0 * std_error / 0.8

        if steady_error_score > 1.0 and std_error < 0.8:

            scores['steady_error'] = steady_error_score



        # 系统振荡检测

        oscillation_score = std_error / std_threshold * mean_abs_deriv / slope_threshold

        if oscillation_score > 1.0:

            scores['oscillation'] = oscillation_score



        # 阀门过度动作检测

        valve_score = valve_activity / valve_change_threshold * std_error / 0.5

        if valve_score > 1.0:

            scores['valve'] = valve_score



        # 趋势性变化检测

        trend_score = trend_slope / slope_threshold * std_error / 0.4

        if trend_score > 1.0:

            scores['trend'] = trend_score



        # 阀门振荡检测

        valve_oscillation_score = valve_oscillation / 2.0 * std_error / 0.3

        if valve_oscillation_score > 1.0:

            scores['valve_oscillation'] = valve_oscillation_score



        # 温度模式变化检测

        pattern_score = temp_pattern_change / 0.5

        if pattern_score > 1.0:

            scores['pattern'] = pattern_score



        # 预测模型异常检测

        prediction_score = prediction_residual / 0.6 * std_error / 0.4

        if prediction_score > 1.0:

            scores['prediction'] = prediction_score



        # 自相关性异常检测

        autocorr_score = autocorr_strength / 0.8 * std_error / 0.5

        if autocorr_score > 1.0:

            scores['autocorr'] = autocorr_score



        # 传感器漂移或控制阀磨损等轻微扰动的检测

        drift_score = std_error / 0.4 * valve_oscillation / 1.5

        if drift_score > 1.0:

            scores['drift'] = drift_score



        # 判断是否为扰动

        is_disturbance = False

        disturbance_type = ""



        if scores:

            # 选择最高分的扰动类型

            max_score_type = max(scores.keys(), key=lambda k: scores[k])

            max_score = scores[max_score_type]



            # 根据检测敏感度调整阈值

            detection_threshold = 1.0 * (2.0 - Config.DETECTION_SENSITIVITY)  # 敏感度越高，阈值越低



            if max_score > detection_threshold:

                is_disturbance = True

                if max_score_type == 'overshoot':

                    disturbance_type = f"超调量大({max_error:.1f}℃)"

                elif max_score_type == 'steady_error':

                    disturbance_type = f"稳态误差({mean_error:.1f}℃)"

                elif max_score_type == 'oscillation':

                    disturbance_type = f"系统振荡(σ={std_error:.2f})"

                elif max_score_type == 'valve':

                    disturbance_type = f"控制不稳定(阀门动作={valve_activity:.1f})"

                elif max_score_type == 'trend':

                    disturbance_type = f"趋势性偏离(斜率={trend_slope:.3f})"

                elif max_score_type == 'valve_oscillation':

                    disturbance_type = f"阀门振荡({valve_oscillation:.2f})"

                elif max_score_type == 'pattern':

                    disturbance_type = f"温度模式变化({temp_pattern_change:.2f})"

                elif max_score_type == 'prediction':

                    disturbance_type = f"预测异常({prediction_residual:.2f})"

                elif max_score_type == 'autocorr':

                    disturbance_type = f"自相关异常({autocorr_strength:.2f})"

                elif max_score_type == 'drift':

                    disturbance_type = f"系统参数漂移(σ={std_error:.2f}, 阀门={valve_oscillation:.2f})"

                else:

                    disturbance_type = max_score_type



        # 12. 自适应窗口调整

        if Config.ADAPTIVE_DETECTION_ENABLED:

            if is_disturbance:

                # 扰动时增大窗口以获得更稳定的检测结果

                self.current_window_size = min(self.current_window_size * self.window_growth_factor,

                                               Config.MAX_DETECTION_WINDOW)

                self.disturbance_count += 1

                self.last_disturbance_time = time_data[-1] if time_data else 0

        

        # 标记缓存失效，以便下次调用时重新计算（优化：确保数据一致性）

        self._cache_valid = False



        return is_disturbance, disturbance_type




