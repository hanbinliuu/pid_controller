import numpy as np
from typing import Tuple
from scipy.signal import savgol_filter, butter, filtfilt, iirnotch

try:
    from .config import Config
except ImportError:
    from config import Config


class DataPreprocessor:
    """数据预处理器：负责数据预处理和场景检测"""
    
    def __init__(self, epsilon: float = None):
        self._epsilon = epsilon if epsilon is not None else Config.EPSILON
    
    def preprocess(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                   scenario: str = 'auto') -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        对数据进行预处理，提高模型辨识精度
        
        Args:
            t: 时间数组
            y: 输出数据 (PV)
            u: 输入数据 (MV)
            scenario: 场景类型 ('auto', 'temperature', 'level', 'general')
        
        Returns:
            预处理后的 (t, y, u)
        """
        if len(y) < 20:
            return t, y, u
        
        # 第一步：过滤异常值（PV=0 或跳变过大）
        t, y, u = self.filter_anomalies(t, y, u)
        
        if len(y) < 20:
            return t, y, u
        
        # 自动检测场景
        if scenario == 'auto':
            scenario = self.detect_scenario(t, y, u)
        
        if scenario == 'temperature':
            return self.preprocess_temperature(t, y, u)
        elif scenario == 'level':
            return self.preprocess_level(t, y, u)
        else:
            return self.preprocess_general(t, y, u)
    
    def filter_anomalies(self, t: np.ndarray, y: np.ndarray, u: np.ndarray
                         ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        过滤异常数据点
        - PV=0 的异常值（传感器故障）
        - 跳变过大的值（数据采集错误）
        """
        if len(y) < 10:
            return t, y, u
        
        valid_mask = np.ones(len(y), dtype=bool)
        
        # 1. 过滤 PV=0 异常值（传感器故障导致的 0 值）
        zero_count = np.sum(y == 0)
        non_zero_count = len(y) - zero_count
        
        # 如果存在非零值且零值不占绝大多数，则过滤零值
        if non_zero_count >= 20:
            # 计算非零值的中位数，判断 0 是否是异常
            y_nonzero = y[y != 0]
            y_median_nonzero = np.median(y_nonzero)
            
            # 如果非零值的中位数远离 0，说明 0 是异常
            if abs(y_median_nonzero) > 0.5:  # 中位数大于 0.5，则认为 0 是异常
                valid_mask &= (y != 0)
        
        # 2. 在过滤 0 后，重新计算统计特征
        y_filtered = y[valid_mask]
        if len(y_filtered) < 20:
            return t, y, u
        
        y_std = np.std(y_filtered)
        
        # 3. 检测跳变异常（相邻点差异超过 5 倍标准差）
        if y_std > self._epsilon:
            # 需要在原始索引上操作
            valid_indices = np.where(valid_mask)[0]
            y_valid = y[valid_mask]
            y_diff = np.abs(np.diff(y_valid))
            diff_threshold = max(5 * y_std, np.percentile(y_diff, 95) * 2)
            jump_indices = np.where(y_diff > diff_threshold)[0]
            
            for idx in jump_indices:
                # 标记跳变点及其后一个点
                if idx < len(valid_indices):
                    valid_mask[valid_indices[idx]] = False
                if idx + 1 < len(valid_indices):
                    valid_mask[valid_indices[idx + 1]] = False
        
        # 4. 检测极端异常值（IQR 方法）
        y_for_iqr = y[valid_mask]
        if len(y_for_iqr) >= 20:
            Q1 = np.percentile(y_for_iqr, 25)
            Q3 = np.percentile(y_for_iqr, 75)
            IQR = Q3 - Q1
            if IQR > self._epsilon:
                lower_bound = Q1 - 3 * IQR
                upper_bound = Q3 + 3 * IQR
                outlier_mask = (y < lower_bound) | (y > upper_bound)
                valid_mask &= ~outlier_mask
        
        # 5. 应用过滤
        if np.sum(valid_mask) >= 20:
            t = t[valid_mask]
            y = y[valid_mask]
            u = u[valid_mask] if u is not None else None
        
        return t, y, u
    
    def detect_scenario(self, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> str:
        """
        自动检测控制场景类型
        
        Returns:
            'temperature' | 'level'
        """
        if len(y) < 20:
            return 'temperature'
        
        dy_dt = np.gradient(y, t)
        avg_response_speed = np.mean(np.abs(dy_dt))
        max_response_speed = np.max(np.abs(dy_dt))
        
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > self._epsilon else 100
        
        y_range = np.max(y) - np.min(y)
        estimated_T = y_range / max_response_speed if max_response_speed > self._epsilon else 30.0
        
        # 检测积分特性
        correlation_with_integral = 0
        if len(u) == len(y):
            dt = t[1] - t[0] if len(t) > 1 else 1.0
            u_integral = np.cumsum(u) * dt
            try:
                correlation_with_integral = np.corrcoef(y, u_integral)[0, 1]
                if np.isnan(correlation_with_integral):
                    correlation_with_integral = 0
            except:
                correlation_with_integral = 0
        
        # 判断场景
        if estimated_T > 20 and snr > 10 and avg_response_speed < 0.5:
            return 'temperature'
        elif estimated_T < 10 and (snr < 8 or correlation_with_integral > 0.7):
            return 'level'
        elif estimated_T < 10:
            return 'level'
        else:
            return 'temperature'
    
    def preprocess_temperature(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                               min_data_points: int = 100
                               ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        温控场景预处理：去除初始瞬态、Savitzky-Golay 平滑滤波
        """
        y_backup = y.copy()
        u_backup = u.copy() if u is not None else None
        t_backup = t.copy()
        
        try:
            # 1. 去除初始瞬态（前10%数据）
            if len(y) > min_data_points:
                transient_len = len(y) // 10
                t = t[transient_len:]
                y = y[transient_len:]
                u = u[transient_len:] if u is not None else None
            
            # 2. Savitzky-Golay 平滑滤波
            if len(y) > 21:
                window_length = min(21, len(y) // 2 * 2 - 1)
                if window_length >= 5:
                    polyorder = min(3, window_length - 2)
                    y_filtered = savgol_filter(y, window_length, polyorder)
                    if not np.any(np.isnan(y_filtered)):
                        y = y_filtered
            
            # 安全检查
            if np.any(np.isnan(y)) or np.any(np.isinf(y)):
                return t_backup, y_backup, u_backup
            
            return t, y, u
            
        except Exception:
            return t_backup, y_backup, u_backup
    
    def preprocess_level(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                         noise_reduction: str = 'medium'
                         ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        液位场景预处理：异常值处理、噪声滤波、周期性波动去除
        """
        y_backup = y.copy()
        u_backup = u.copy() if u is not None else None
        
        try:
            # 1. 异常值检测和移除（IQR 方法）
            if len(y) > 10:
                Q1 = np.percentile(y, 25)
                Q3 = np.percentile(y, 75)
                IQR = Q3 - Q1
                if IQR > self._epsilon:
                    lower_bound = Q1 - 2.5 * IQR
                    upper_bound = Q3 + 2.5 * IQR
                    outlier_mask = (y < lower_bound) | (y > upper_bound)
                    if np.any(outlier_mask):
                        valid_indices = np.where(~outlier_mask)[0]
                        if len(valid_indices) > 0:
                            outlier_indices = np.where(outlier_mask)[0]
                            y_interp = np.interp(outlier_indices, valid_indices, y[valid_indices])
                            y[outlier_mask] = y_interp
            
            # 2. 噪声滤波
            y_original = y.copy()
            if noise_reduction == 'high':
                if len(y) > 31:
                    window_length = min(31, len(y) // 2 * 2 - 1)
                    if window_length >= 5:
                        y_filtered = savgol_filter(y, window_length, min(3, window_length - 2))
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
                if len(y) > 10:
                    try:
                        b, a = butter(3, 0.1, 'low')
                        y_filtered = filtfilt(b, a, y)
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
                    except:
                        pass
            elif noise_reduction == 'medium':
                if len(y) > 15:
                    window_length = min(15, len(y) // 2 * 2 - 1)
                    if window_length >= 5:
                        polyorder = min(3, window_length - 2)
                        y_filtered = savgol_filter(y, window_length, polyorder)
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
            else:  # low
                if len(y) > 7:
                    window_length = min(7, len(y) // 2 * 2 - 1)
                    if window_length >= 5:
                        polyorder = min(3, window_length - 2)
                        y_filtered = savgol_filter(y, window_length, polyorder)
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
            
            # 如果滤波产生 NaN，恢复
            if np.any(np.isnan(y)):
                y = y_original
            
            # 3. 检测并去除周期性波动
            if len(y) > 50 and len(t) > 1:
                try:
                    y_before_fft = y.copy()
                    fft_y = np.fft.fft(y - np.mean(y))
                    dt = t[1] - t[0]
                    freqs = np.fft.fftfreq(len(y), dt)
                    power = np.abs(fft_y)
                    
                    positive_freq_idx = np.where(freqs > 0)[0]
                    if len(positive_freq_idx) > 0:
                        dominant_freq_idx = positive_freq_idx[np.argmax(power[positive_freq_idx])]
                        dominant_freq = abs(freqs[dominant_freq_idx])
                        
                        if dominant_freq > 0 and 1/dominant_freq < (t[-1] - t[0]) / 5:
                            fs = 1 / dt if dt > 0 else 1
                            if fs > 2 * dominant_freq:
                                Q = 30
                                b, a = iirnotch(dominant_freq, Q, fs)
                                y_filtered = filtfilt(b, a, y)
                                if not np.any(np.isnan(y_filtered)):
                                    y = y_filtered
                except:
                    pass
            
            # 4. 输入信号平滑
            if u is not None and len(u) > 15:
                try:
                    window_length = min(15, len(u) // 2 * 2 - 1)
                    if window_length >= 5:
                        polyorder = min(3, window_length - 2)
                        u_filtered = savgol_filter(u, window_length, polyorder)
                        if not np.any(np.isnan(u_filtered)):
                            u = u_filtered
                except:
                    pass
            
            # 安全检查
            if np.any(np.isnan(y)) or np.any(np.isinf(y)):
                y = y_backup
            if u is not None and (np.any(np.isnan(u)) or np.any(np.isinf(u))):
                u = u_backup
            
            return t, y, u
            
        except Exception:
            return t, y_backup, u_backup
    
    def preprocess_general(self, t: np.ndarray, y: np.ndarray, u: np.ndarray
                           ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        通用预处理：轻度 Savitzky-Golay 平滑
        """
        y_backup = y.copy()
        
        try:
            if len(y) > 11:
                window_length = min(11, len(y) // 2 * 2 - 1)
                if window_length >= 5:
                    polyorder = min(3, window_length - 2)
                    y_filtered = savgol_filter(y, window_length, polyorder)
                    if not np.any(np.isnan(y_filtered)):
                        y = y_filtered
            
            if np.any(np.isnan(y)):
                y = y_backup
            
            return t, y, u
            
        except:
            return t, y_backup, u


# 便捷函数
def preprocess_data(t: np.ndarray, y: np.ndarray, u: np.ndarray,
                    scenario: str = 'auto') -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """便捷函数：数据预处理"""
    return DataPreprocessor().preprocess(t, y, u, scenario)


def detect_scenario(t: np.ndarray, y: np.ndarray, u: np.ndarray) -> str:
    """便捷函数：场景检测"""
    return DataPreprocessor().detect_scenario(t, y, u)
