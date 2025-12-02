"""
非稳态扰动检测模块

该模块提供了数据非稳态扰动检测功能，可以检测多种类型的系统扰动：
- 超调量大
- 稳态误差
- 系统振荡
- 阀门过度动作
- 趋势性变化
- 阀门振荡
- 温度模式变化
- 预测异常
- 自相关异常
- 系统参数漂移

使用示例：
    from core.utils.disturbance_detector import DisturbanceDetector, DetectionMode
    
    # 创建检测器
    detector = DisturbanceDetector(mode=DetectionMode.STANDARD)
    
    # 检测扰动
    is_disturbance, disturbance_type = detector.detect(
        data=temp_data,
        setpoint=target_temp,
        control_signal=valve_data,
        time=time_data
    )
    
    if is_disturbance:
        print(f"检测到扰动: {disturbance_type}")
"""

from collections import deque
from enum import Enum
from typing import List, Tuple, Optional, Union
import numpy as np
import warnings


class DetectionMode(str, Enum):
    """检测模式枚举"""
    STANDARD = "standard"  # 标准模式
    ANTI_DISTURBANCE = "anti_disturbance"  # 抗扰动模式（降低检测灵敏度）
    ANTI_NOISE = "anti_noise"  # 抗噪声模式（降低检测灵敏度）
    FLOW_CONTROL = "flow_control"  # 流量控制模式（提高检测灵敏度）


class DisturbanceDetectorConfig:
    """扰动检测配置参数"""
    # 扰动检测相关参数
    DETECTION_WINDOW = 60    # 扰动检测窗口大小
    ERROR_THRESHOLD = 1.5    # 误差阈值
    STD_THRESHOLD = 1.2      # 标准差阈值
    SLOPE_THRESHOLD = 0.05   # 温度变化率阈值
    VALVE_CHANGE_THRESHOLD = 25  # 阀门变化阈值
    
    # 自适应检测参数
    ADAPTIVE_DETECTION_ENABLED = True  # 是否启用自适应检测
    MIN_DETECTION_WINDOW = 30          # 最小检测窗口
    MAX_DETECTION_WINDOW = 120         # 最大检测窗口
    DETECTION_SENSITIVITY = 0.8       # 检测敏感度（0-1，越小越敏感）
    
    # 稳态判断参数
    STABILIZATION_THRESHOLD = 0.8  # 温度波动允许阈值
    STABILIZATION_WINDOW = 50  # 稳态判断窗口大小


class DisturbanceDetector:
    """
    非稳态扰动检测器
    
    用于检测控制系统中的各种非稳态扰动，包括超调、振荡、稳态误差等。
    支持多种检测模式，可根据不同应用场景调整检测灵敏度。
    """
    
    def __init__(self, mode: DetectionMode = DetectionMode.STANDARD, config: Optional[DisturbanceDetectorConfig] = None):
        """
        初始化扰动检测器
        
        Args:
            mode: 检测模式，默认为标准模式
            config: 配置参数，如果为None则使用默认配置
        """
        self.mode = mode
        self.config = config or DisturbanceDetectorConfig()
        
        # 用于检测异常模式的滑动窗口
        self.temp_window = deque(maxlen=self.config.DETECTION_WINDOW)
        self.error_window = deque(maxlen=self.config.DETECTION_WINDOW)
        self.valve_window = deque(maxlen=self.config.DETECTION_WINDOW)
        self.time_window = deque(maxlen=self.config.DETECTION_WINDOW)
        
        # 自适应窗口大小
        self.current_window_size = self.config.DETECTION_WINDOW
        self.window_growth_factor = 1.05  # 窗口增长因子
        
        # 性能指标跟踪
        self.performance_history = deque(maxlen=100)
        self.disturbance_count = 0
        self.last_disturbance_time = 0
        
        # 优化：缓存统计结果，减少重复计算
        self._cached_stats = {}
        self._cache_valid = False
        self._last_data_hash = None
    
    def is_stable(self, data: Union[List, np.ndarray], setpoint: float) -> bool:
        """
        判断系统是否稳定在目标值附近
        
        Args:
            data: 数据数组（温度、流量等）
            setpoint: 目标值
            
        Returns:
            bool: 如果系统稳定返回True，否则返回False
        """
        if len(data) < self.config.STABILIZATION_WINDOW:
            return False
        
        recent_data = np.array(data[-self.config.STABILIZATION_WINDOW:])
        
        # 根据模式调整稳定阈值
        if self.mode == DetectionMode.ANTI_DISTURBANCE:
            threshold = self.config.STABILIZATION_THRESHOLD * 1.2  # 放宽稳定阈值
        elif self.mode == DetectionMode.ANTI_NOISE:
            threshold = self.config.STABILIZATION_THRESHOLD * 1.1  # 略微放宽稳定阈值
        elif self.mode == DetectionMode.FLOW_CONTROL:
            threshold = self.config.STABILIZATION_THRESHOLD * 0.8  # 流量控制更严格
        else:
            threshold = self.config.STABILIZATION_THRESHOLD
        
        # 均值需接近目标值（±0.5）
        mean_value = np.mean(recent_data)
        if not (setpoint - 0.5 <= mean_value <= setpoint + 0.5):
            return False
        
        # 波动判断
        deviations = np.abs(recent_data - setpoint)
        return (np.all(deviations < threshold) and
                np.std(deviations) < threshold / 2)
    
    def _update_cached_stats(self, data: Union[List, np.ndarray], 
                            control_signal: Union[List, np.ndarray], 
                            setpoint: float, 
                            window_size: int):
        """
        更新缓存的统计信息（优化：减少重复计算）
        
        Args:
            data: 数据数组
            control_signal: 控制信号数组（如阀门开度）
            setpoint: 目标值
            window_size: 窗口大小
        """
        # 计算数据哈希，判断是否需要更新缓存
        data_hash = hash((len(data), window_size, setpoint))
        if self._cache_valid and self._last_data_hash == data_hash:
            return  # 缓存有效，无需更新
        
        # 获取窗口数据
        recent_data = np.array(data[-window_size:])
        recent_control = np.array(control_signal[-window_size:])
        errors = recent_data - setpoint
        
        # 计算并缓存统计量
        self._cached_stats = {
            'mean_error': np.mean(errors),
            'std_error': np.std(errors),
            'max_error': np.max(np.abs(errors)),
            'data_std': np.std(recent_data),
            'recent_data': recent_data,
            'recent_control': recent_control,
            'errors': errors,
        }
        
        # 数据变化率
        if len(recent_data) > 1:
            data_deriv = np.diff(recent_data)
            self._cached_stats['mean_abs_deriv'] = np.mean(np.abs(data_deriv))
            self._cached_stats['data_deriv'] = data_deriv
        else:
            self._cached_stats['mean_abs_deriv'] = 0
            self._cached_stats['data_deriv'] = np.array([0])
        
        # 控制信号动作
        if len(recent_control) > 1:
            control_changes = np.diff(recent_control)
            self._cached_stats['control_activity'] = np.sum(np.abs(control_changes))
            self._cached_stats['control_changes'] = control_changes
        else:
            self._cached_stats['control_activity'] = 0
            self._cached_stats['control_changes'] = np.array([0])
        
        # 趋势斜率
        if len(recent_data) > 20:
            x = np.arange(len(recent_data))
            coeffs = np.polyfit(x, recent_data, 1)
            self._cached_stats['trend_slope'] = abs(coeffs[0])
        else:
            self._cached_stats['trend_slope'] = 0
        
        # 控制信号振荡
        if len(recent_control) > 10:
            control_changes_abs = np.abs(np.diff(recent_control))
            self._cached_stats['control_oscillation'] = np.mean(control_changes_abs)
        else:
            self._cached_stats['control_oscillation'] = 0
        
        # 数据模式变化
        if len(recent_data) > 30:
            first_half = recent_data[:len(recent_data) // 2]
            second_half = recent_data[len(recent_data) // 2:]
            self._cached_stats['pattern_change'] = abs(np.std(second_half) - np.std(first_half))
        else:
            self._cached_stats['pattern_change'] = 0
        
        # 预测残差
        if len(recent_data) > 40:
            mid_point = len(recent_data) // 2
            first_half = recent_data[:mid_point]
            second_half = recent_data[mid_point:mid_point + len(first_half)]
            predicted_second_half = np.full_like(second_half, np.mean(first_half))
            self._cached_stats['prediction_residual'] = np.mean(np.abs(second_half - predicted_second_half))
        else:
            self._cached_stats['prediction_residual'] = 0
        
        # 自相关性
        if len(recent_data) > 20 and len(recent_data) > 1:
            # 检查数据是否有变化（避免除以零警告）
            data_std = np.std(recent_data)
            if data_std > 1e-10:  # 如果标准差足够大
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    try:
                        autocorr = np.corrcoef(recent_data[:-1], recent_data[1:])[0, 1]
                        self._cached_stats['autocorr_strength'] = abs(autocorr) if not np.isnan(autocorr) else 0
                    except (ValueError, TypeError):
                        self._cached_stats['autocorr_strength'] = 0
            else:
                self._cached_stats['autocorr_strength'] = 0
        else:
            self._cached_stats['autocorr_strength'] = 0
        
        # 更新缓存状态
        self._cache_valid = True
        self._last_data_hash = data_hash
    
    def detect(self, 
               data: Union[List, np.ndarray], 
               setpoint: float, 
               control_signal: Union[List, np.ndarray], 
               time: Optional[Union[List, np.ndarray]] = None) -> Tuple[bool, str]:
        """
        检测非稳态扰动
        
        Args:
            data: 数据数组（温度、流量等被控变量）
            setpoint: 目标值
            control_signal: 控制信号数组（如阀门开度、执行器输出等）
            time: 时间数组（可选），用于自适应窗口调整
            
        Returns:
            Tuple[bool, str]: (是否检测到扰动, 扰动类型描述)
                - 如果检测到扰动，返回 (True, "扰动类型描述")
                - 如果未检测到扰动，返回 (False, "")
        
        示例:
            >>> detector = DisturbanceDetector()
            >>> is_disturbance, disturbance_type = detector.detect(
            ...     data=[20.1, 20.2, 20.5, 21.0, 21.5, 22.0],
            ...     setpoint=20.0,
            ...     control_signal=[50, 52, 55, 58, 60, 62],
            ...     time=[0, 1, 2, 3, 4, 5]
            ... )
            >>> if is_disturbance:
            ...     print(f"检测到扰动: {disturbance_type}")
        """
        if len(data) < self.config.MIN_DETECTION_WINDOW:
            return False, ""
        
        # 确保输入为列表或数组
        if not isinstance(data, np.ndarray):
            data = np.array(data)
        if not isinstance(control_signal, np.ndarray):
            control_signal = np.array(control_signal)
        if time is not None and not isinstance(time, np.ndarray):
            time = np.array(time)
        
        # 获取当前窗口的数据 - 使用自适应窗口大小
        window_size = min(len(data), self.current_window_size)
        window_size = int(window_size)
        
        # 更新缓存统计信息（仅在需要时计算）
        self._update_cached_stats(data, control_signal, setpoint, window_size)
        
        # 从缓存中获取统计量（优化：避免重复计算）
        mean_error = self._cached_stats['mean_error']
        std_error = self._cached_stats['std_error']
        max_error = self._cached_stats['max_error']
        mean_abs_deriv = self._cached_stats['mean_abs_deriv']
        control_activity = self._cached_stats['control_activity']
        trend_slope = self._cached_stats['trend_slope']
        control_oscillation = self._cached_stats['control_oscillation']
        pattern_change = self._cached_stats['pattern_change']
        prediction_residual = self._cached_stats['prediction_residual']
        autocorr_strength = self._cached_stats['autocorr_strength']
        
        # 基于模式的自适应阈值调整
        error_threshold = self.config.ERROR_THRESHOLD
        std_threshold = self.config.STD_THRESHOLD
        slope_threshold = self.config.SLOPE_THRESHOLD
        control_change_threshold = self.config.VALVE_CHANGE_THRESHOLD
        
        if self.mode == DetectionMode.ANTI_DISTURBANCE:
            # 抗扰动模式：降低检测灵敏度，避免误判
            error_threshold *= 1.5
            std_threshold *= 1.4
            slope_threshold *= 1.3
            control_change_threshold *= 1.5
        elif self.mode == DetectionMode.ANTI_NOISE:
            # 抗噪声模式：降低检测灵敏度，避免噪声误判
            error_threshold *= 1.8
            std_threshold *= 1.6
            slope_threshold *= 1.5
            control_change_threshold *= 1.8
        elif self.mode == DetectionMode.FLOW_CONTROL:
            # 流量控制模式：提高检测灵敏度，因为响应快
            error_threshold *= 0.7
            std_threshold *= 0.8
            slope_threshold *= 0.6
            control_change_threshold *= 0.9
        
        # 综合判断 - 使用加权评分机制
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
        
        # 控制信号过度动作检测
        control_score = control_activity / control_change_threshold * std_error / 0.5
        if control_score > 1.0:
            scores['control'] = control_score
        
        # 趋势性变化检测
        trend_score = trend_slope / slope_threshold * std_error / 0.4
        if trend_score > 1.0:
            scores['trend'] = trend_score
        
        # 控制信号振荡检测
        control_oscillation_score = control_oscillation / 2.0 * std_error / 0.3
        if control_oscillation_score > 1.0:
            scores['control_oscillation'] = control_oscillation_score
        
        # 数据模式变化检测
        pattern_score = pattern_change / 0.5
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
        drift_score = std_error / 0.4 * control_oscillation / 1.5
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
            detection_threshold = 1.0 * (2.0 - self.config.DETECTION_SENSITIVITY)  # 敏感度越高，阈值越低
            
            if max_score > detection_threshold:
                is_disturbance = True
                if max_score_type == 'overshoot':
                    disturbance_type = f"超调量大({max_error:.1f})"
                elif max_score_type == 'steady_error':
                    disturbance_type = f"稳态误差({mean_error:.1f})"
                elif max_score_type == 'oscillation':
                    disturbance_type = f"系统振荡(σ={std_error:.2f})"
                elif max_score_type == 'control':
                    disturbance_type = f"控制不稳定(控制信号动作={control_activity:.1f})"
                elif max_score_type == 'trend':
                    disturbance_type = f"趋势性偏离(斜率={trend_slope:.3f})"
                elif max_score_type == 'control_oscillation':
                    disturbance_type = f"控制信号振荡({control_oscillation:.2f})"
                elif max_score_type == 'pattern':
                    disturbance_type = f"数据模式变化({pattern_change:.2f})"
                elif max_score_type == 'prediction':
                    disturbance_type = f"预测异常({prediction_residual:.2f})"
                elif max_score_type == 'autocorr':
                    disturbance_type = f"自相关异常({autocorr_strength:.2f})"
                elif max_score_type == 'drift':
                    disturbance_type = f"系统参数漂移(σ={std_error:.2f}, 控制信号={control_oscillation:.2f})"
                else:
                    disturbance_type = max_score_type
        
        # 自适应窗口调整
        if self.config.ADAPTIVE_DETECTION_ENABLED:
            if is_disturbance:
                # 扰动时增大窗口以获得更稳定的检测结果
                self.current_window_size = min(self.current_window_size * self.window_growth_factor,
                                               self.config.MAX_DETECTION_WINDOW)
                self.disturbance_count += 1
                if time is not None and len(time) > 0:
                    self.last_disturbance_time = time[-1]
        
        # 标记缓存失效，以便下次调用时重新计算（优化：确保数据一致性）
        self._cache_valid = False
        
        return is_disturbance, disturbance_type
    
    def get_statistics(self) -> dict:
        """
        获取检测器统计信息
        
        Returns:
            dict: 包含扰动计数、最后扰动时间等统计信息
        """
        return {
            'disturbance_count': self.disturbance_count,
            'last_disturbance_time': self.last_disturbance_time,
            'current_window_size': self.current_window_size,
            'mode': self.mode.value
        }
    
    def reset(self):
        """重置检测器状态"""
        self.temp_window.clear()
        self.error_window.clear()
        self.valve_window.clear()
        self.time_window.clear()
        self.current_window_size = self.config.DETECTION_WINDOW
        self.disturbance_count = 0
        self.last_disturbance_time = 0
        self._cached_stats = {}
        self._cache_valid = False
        self._last_data_hash = None

