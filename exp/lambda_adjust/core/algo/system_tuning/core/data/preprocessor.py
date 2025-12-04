"""数据预处理模块：负责数据预处理和场景检测"""
import numpy as np
from scipy.signal import savgol_filter, butter, filtfilt, iirnotch
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config, Mode
from core.model.identifier import ModelIdentifier


class DataPreprocessor:
    """数据预处理器：负责数据预处理、场景检测和模型类型检测"""
    
    @staticmethod
    def preprocess_temperature_data(t, y, u, min_data_points=100):
        """针对石油温控的数据预处理"""
        # 去除初始瞬态（前10%数据）
        if len(y) > min_data_points:
            transient_len = len(y) // 10
            t = t[transient_len:]
            y = y[transient_len:]
            u = u[transient_len:] if u is not None else None
        
        # 平滑滤波
        if len(y) > 21:
            window_length = min(21, len(y) // 2 * 2 - 1)
            y = savgol_filter(y, window_length, 3)
        
        return t, y, u
    
    @staticmethod
    def preprocess_level_data(t, y, u, noise_reduction='medium'):
        """针对蒸馏液位的数据预处理"""
        # 保存原始数据副本
        y_backup = y.copy()
        u_backup = u.copy()
        
        # 1. 异常值检测和移除
        if len(y) > 10:
            try:
                Q1 = np.percentile(y, 25)
                Q3 = np.percentile(y, 75)
                IQR = Q3 - Q1
                if IQR > Config.EPSILON:
                    lower_bound = Q1 - 2.5 * IQR
                    upper_bound = Q3 + 2.5 * IQR
                    outlier_mask = (y < lower_bound) | (y > upper_bound)
                    if np.any(outlier_mask):
                        valid_indices = np.where(~outlier_mask)[0]
                        if len(valid_indices) > 0:
                            outlier_indices = np.where(outlier_mask)[0]
                            y_interp = np.interp(outlier_indices, valid_indices, y[valid_indices])
                            y[outlier_mask] = y_interp
                            
                            # 检查是否产生NaN
                            if np.any(np.isnan(y)):
                                print(f"⚠️ 异常值处理产生NaN，恢复原始数据")
                                y = y_backup.copy()
            except Exception as e:
                print(f"⚠️ 异常值处理失败: {e}，使用原始数据")
                y = y_backup.copy()
        
        # 2. 噪声滤波（添加NaN检查）
        y_original = y.copy()  # 保存原始数据以防滤波失败
        
        try:
            if noise_reduction == 'high':
                if len(y) > 31:
                    window_length = min(31, len(y) // 2 * 2 - 1)
                    if window_length >= 5:  # 确保窗口长度足够
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
                    if window_length >= 5:  # 确保窗口长度足够
                        polyorder = min(3, window_length - 2)  # 多项式阶数不能超过窗口长度-1
                        y_filtered = savgol_filter(y, window_length, polyorder)
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
            else:
                if len(y) > 7:
                    window_length = min(7, len(y) // 2 * 2 - 1)
                    if window_length >= 5:  # 确保窗口长度足够
                        polyorder = min(3, window_length - 2)
                        y_filtered = savgol_filter(y, window_length, polyorder)
                        if not np.any(np.isnan(y_filtered)):
                            y = y_filtered
        except Exception as e:
            # 如果滤波失败，恢复原始数据
            y = y_original
            print(f"⚠️ 液位预处理滤波失败: {e}，使用原始数据")
        
        # 最终检查：如果y中有NaN，恢复原始数据
        if np.any(np.isnan(y)):
            y = y_original
            print(f"⚠️ 液位预处理产生NaN，已恢复原始数据")
        
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
                            
                            # 检查是否产生NaN
                            if not np.any(np.isnan(y_filtered)):
                                y = y_filtered
                            else:
                                print(f"⚠️ 周期性波动去除产生NaN，保持原数据")
                                y = y_before_fft
            except Exception as e:
                print(f"⚠️ 周期性波动去除失败: {e}，保持原数据")
        
        # 4. 输入信号平滑（添加NaN检查）
        if len(u) > 15:
            try:
                window_length = min(15, len(u) // 2 * 2 - 1)
                if window_length >= 5:
                    polyorder = min(3, window_length - 2)
                    u_filtered = savgol_filter(u, window_length, polyorder)
                    if not np.any(np.isnan(u_filtered)):
                        u = u_filtered
            except Exception as e:
                print(f"⚠️ 输入信号平滑失败: {e}，使用原始数据")
        
        # 最终安全检查：确保返回的数据中没有NaN
        if np.any(np.isnan(y)):
            print(f"⚠️ 警告：预处理后y包含NaN，恢复为原始数据")
            y = y_backup
        if np.any(np.isnan(u)):
            print(f"⚠️ 警告：预处理后u包含NaN，恢复为原始数据")
            u = u_backup
        if np.any(np.isnan(t)):
            print(f"⚠️ 警告：预处理后t包含NaN（这不应该发生！）")
        
        return t, y, u
    
    @staticmethod
    def detect_control_scenario(t, y, u):
        """自动检测控制场景类型"""
        if len(y) < 20:
            return 'temperature'
        
        dy_dt = np.gradient(y, t)
        avg_response_speed = np.mean(np.abs(dy_dt))
        max_response_speed = np.max(np.abs(dy_dt))
        
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > Config.EPSILON else 100
        
        y_range = np.max(y) - np.min(y)
        estimated_T = y_range / max_response_speed if max_response_speed > Config.EPSILON else 30.0
        
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
        
        if estimated_T > 20 and snr > 10 and avg_response_speed < 0.5:
            return 'temperature'
        elif estimated_T < 10 and (snr < 8 or correlation_with_integral > 0.7):
            return 'level'
        elif estimated_T < 10:
            return 'level'
        else:
            return 'temperature'
    
    @staticmethod
    def detect_model_type(t, y, u, scenario=None):
        """自动检测最适合的模型类型"""
        if len(y) < 20:
            return 'fopdt'
        
        if scenario is None:
            scenario = DataPreprocessor.detect_control_scenario(t, y, u)
        
        dt = t[1] - t[0] if len(t) > 1 else 1.0
        L_est = ModelIdentifier._estimate_lag_from_correlation(u, y, dt)
        
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > Config.EPSILON else 100
        
        dy_dt = np.gradient(y, t)
        max_response_speed = np.max(np.abs(dy_dt))
        y_range = np.max(y) - np.min(y)
        estimated_T = y_range / max_response_speed if max_response_speed > Config.EPSILON else 30.0
        
        # 检测积分特性
        correlation_with_integral = 0
        if len(u) == len(y):
            u_integral = np.cumsum(u) * dt
            try:
                correlation_with_integral = np.corrcoef(y, u_integral)[0, 1]
                if np.isnan(correlation_with_integral):
                    correlation_with_integral = 0
            except:
                correlation_with_integral = 0
        
        # 检测热损失
        has_heat_loss = False
        if scenario == 'temperature' and len(y) > 200:
            steady_segment = y[-100:]
            if np.std(steady_segment) < 0.5:
                x = np.arange(len(steady_segment))
                coeffs = np.polyfit(x, steady_segment, 1)
                if coeffs[0] < -0.01:
                    has_heat_loss = True
        
        # 检测是否适合二阶模型
        is_second_order_candidate = False
        if len(y) > 30:
            y_max = np.max(y)
            y_final = np.mean(y[-10:])
            has_overshoot = y_max > y_final * 1.05
            
            d2y = np.diff(np.diff(y))
            if len(d2y) > 0:
                sign_changes = np.sum(np.diff(np.sign(d2y)) != 0)
                if sign_changes > len(d2y) * 0.1:
                    is_second_order_candidate = True
            
            if has_overshoot or is_second_order_candidate:
                if L_est < 1.0 and 5.0 < estimated_T < 100.0:
                    is_second_order_candidate = True
        
        # 判断模型类型
        if scenario == 'level':
            if snr < 5 and L_est < 2:
                return 'integral_delay'
            elif L_est > 1:
                return 'fopdt'
            else:
                return 'first_order'
        elif scenario == 'temperature':
            if has_heat_loss:
                return 'fopdt_with_heat_loss'
            elif is_second_order_candidate and L_est < 0.5:
                return 'second_order'
            elif L_est < 0.5 and estimated_T < 10:
                return 'first_order'
            else:
                return 'fopdt'
        else:
            if is_second_order_candidate and L_est < 0.5:
                return 'second_order'
            elif L_est < 0.5:
                return 'first_order'
            else:
                return 'fopdt'
    
    @staticmethod
    def detect_control_mode(t, y, u, setpoint=None):
        """自动检测最适合的控制模式"""
        if len(y) < 20:
            return Mode.STANDARD
        
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > Config.EPSILON else 100
        
        dy = np.diff(y)
        d2y = np.diff(dy)
        max_acceleration = np.max(np.abs(d2y))
        avg_acceleration = np.mean(np.abs(d2y))
        has_disturbance = max_acceleration > 3 * avg_acceleration if avg_acceleration > Config.EPSILON else False
        
        has_error_fluctuation = False
        if setpoint is not None:
            error = y - setpoint
            error_std = np.std(error)
            error_mean = np.abs(np.mean(error))
            if error_std > 0.5 and error_mean < error_std:
                has_error_fluctuation = True
        
        has_periodic_noise = False
        if len(y) > 50 and len(t) > 1:
            try:
                dt = t[1] - t[0]
                fft_y = np.fft.fft(y - np.mean(y))
                freqs = np.fft.fftfreq(len(y), dt)
                power = np.abs(fft_y)
                
                if dt > 0:
                    high_freq_mask = np.abs(freqs) > 0.1
                    if np.any(high_freq_mask):
                        high_freq_power = np.sum(power[high_freq_mask])
                        total_power = np.sum(power[power > 0])
                        if total_power > Config.EPSILON and high_freq_power / total_power > 0.3:
                            has_periodic_noise = True
            except:
                pass
        
        if snr < 5 or has_periodic_noise:
            return Mode.ANTI_NOISE
        elif has_disturbance or has_error_fluctuation:
            return Mode.ANTI_DISTURBANCE
        else:
            return Mode.STANDARD

