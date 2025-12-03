"""
稳定性检测器
优化后的非稳态（扰动）检测算法

输入：Pandas Series with datetime index (pv_series, sv_series)
输出：包含table, start_time, end_time, params, total_windows, std_max_window的字典
"""

import numpy as np
import pandas as pd
from typing import Optional, Dict, List, Any, Tuple, Union


class StabilityDetector:
    """
    稳定性检测器：检测数据中的非稳态段（扰动）和稳态段
    
    关键特性：
    1. 能够区分SV调整时的正常变化和真正的扰动（非稳态）
    2. 检测扰动起始点
    3. 识别非稳态段
    """
    
    def __init__(self, tol=0.5, std_tol=0.2, min_len=10):
        """
        初始化稳定性检测器
        
        Args:
            tol: 容差（PV与设定值的允许偏差）
            std_tol: 标准差阈值
            min_len: 最小数据长度
        """
        self.tol = tol
        self.std_tol = std_tol
        self.min_len = min_len
    
    def _calculate_sign_changes(self, data):
        """计算数据的方向改变次数"""
        if len(data) < 2:
            return 0
        diff = np.diff(data)
        if len(diff) < 2:
            return 0
        return np.sum(np.diff(np.sign(diff)) != 0)
    
    def _check_large_oscillation(self, pv_data, setpoint, include_sign_changes=True, strict=False):
        """检查是否存在大幅振荡"""
        if len(pv_data) < 10:
            return False
        
        pv_range = np.max(pv_data) - np.min(pv_data)
        pv_std = np.std(pv_data)
        
        if strict:
            range_ratio, std_ratio = 0.7, 0.4
            abs_range, abs_std = 7.0, 3.5
            sign_ratio, sign_std_ratio = 0.2, 0.25
        else:
            if pv_range > 15.0 or pv_std > 8.0:
                return True
            range_ratio, std_ratio = 0.4, 0.25
            abs_range, abs_std = 4.0, 2.0
            sign_ratio = 0.1 if len(pv_data) > 100 else 0.15
            sign_std_ratio = 0.15
        
        if setpoint > 0:
            if pv_range > max(setpoint * range_ratio, abs_range) or pv_std > max(setpoint * std_ratio, abs_std):
                return True
        else:
            if pv_range > abs_range or pv_std > abs_std:
                return True
        
        if include_sign_changes and len(pv_data) >= 20:
            sign_changes = self._calculate_sign_changes(pv_data)
            std_threshold = max(setpoint * sign_std_ratio, 1.5 if not strict else 2.5) if setpoint > 0 else (1.5 if not strict else 2.5)
            if sign_changes > len(pv_data) * sign_ratio and pv_std > std_threshold:
                return True
        
        return False
    
    def _is_window_unstable(self, pv_window, setpoint):
        """检查窗口数据是否不稳定"""
        pv_range = np.max(pv_window) - np.min(pv_window)
        pv_std = np.std(pv_window)
        
        if setpoint > 0:
            return pv_range > max(setpoint * 0.2, 2.0) or pv_std > max(setpoint * 0.12, 1.0)
        else:
            return pv_range > 2.0 or pv_std > 1.0
    
    def _backtrack_to_true_start(self, pv_data, detected_idx, seg_start, setpoint, max_lookback=80):
        """从检测到的起始点向前回溯，找到真正的起始位置"""
        if detected_idx <= seg_start:
            return detected_idx
        
        start_idx = detected_idx
        lookback_range = min(max_lookback, detected_idx - seg_start)
        
        for i in range(detected_idx - 1, max(seg_start, detected_idx - lookback_range), -1):
            deviation_threshold = max(setpoint * 0.12, 0.6) if setpoint > 0 else 0.6
            if abs(pv_data[i] - setpoint) > deviation_threshold:
                start_idx = i
            else:
                break
        
        return start_idx
    
    def _find_oscillation_start(self, pv_data, start_idx, end_idx, setpoint, window_size=30, step_size=5):
        """查找大幅振荡开始的位置"""
        detected_start = None
        
        for check_start in range(start_idx, end_idx - window_size, step_size):
            window_pv = pv_data[check_start:check_start + window_size]
            if len(window_pv) < window_size:
                break
            
            if self._check_large_oscillation(window_pv, setpoint):
                detected_start = check_start
                break
        
        if detected_start is not None and detected_start > start_idx:
            lookback_start = max(start_idx, detected_start - 50)
            if lookback_start < detected_start:
                baseline_pv = pv_data[lookback_start:detected_start]
                if len(baseline_pv) > 10:
                    baseline_mean = np.mean(baseline_pv)
                    baseline_std = np.std(baseline_pv)
                    
                    for i in range(detected_start - 1, lookback_start, -1):
                        if abs(pv_data[i] - baseline_mean) > baseline_std * 2.5:
                            detected_start = i
                        else:
                            break
        
        return detected_start
    
    def _check_rapid_change(self, pv_data, threshold=0.05):
        """检查是否存在快速变化"""
        if len(pv_data) < 10:
            return False
        
        try:
            x = np.arange(len(pv_data))
            coeffs = np.polyfit(x, pv_data, 1)
            slope = abs(coeffs[0])
            if slope > threshold:
                return True
        except:
            pass
        
        window_change = abs(pv_data[-1] - pv_data[0])
        if window_change > 2.0:
            return True
        
        return False
    
    def _check_large_deviation(self, pv_data, setpoint):
        """检查是否存在大幅偏离设定值"""
        if len(pv_data) == 0:
            return False
        
        mean_error = np.mean(np.abs(pv_data - setpoint))
        
        if setpoint > 0:
            if mean_error > setpoint * 0.5:
                return True
        else:
            if mean_error > 3.0:
                return True
        
        if self._check_rapid_change(pv_data):
            return True
        
        return False
    
    def _check_abnormal_oscillation_during_sv_change(self, pv_data, sv_data, sv_change_magnitude):
        """检查SV变化期间是否有异常振荡"""
        pv_diff = np.diff(pv_data)
        sv_diff = np.diff(sv_data)
        
        direction_mismatch = 0
        for i in range(min(len(pv_diff), len(sv_diff))):
            if abs(sv_diff[i]) > 0.1:
                if pv_diff[i] * sv_diff[i] < 0:
                    direction_mismatch += 1
        
        mismatch_ratio = direction_mismatch / max(1, len(sv_diff))
        expected_pv_range = sv_change_magnitude * 1.5
        actual_pv_range = np.max(pv_data) - np.min(pv_data)
        sign_changes = self._calculate_sign_changes(pv_data)
        high_freq_oscillation = sign_changes > len(pv_data) * 0.3
        
        return (
            mismatch_ratio > 0.4 and
            actual_pv_range > expected_pv_range and
            high_freq_oscillation
        )
    
    def _adjust_response_buffer(self, pv_data, sv_stable_end, new_sv, dynamic_buffer, n):
        """根据PV的收敛和振荡情况动态调整响应缓冲期"""
        max_check_len = min(1500, n - sv_stable_end)
        check_end = min(sv_stable_end + max_check_len, len(pv_data))
        
        if check_end <= sv_stable_end + 100:
            return dynamic_buffer
        
        window_size = 50
        step_size = 20
        convergence_found = False
        convergence_end = sv_stable_end
        has_large_deviation = False
        
        for check_start in range(sv_stable_end, min(sv_stable_end + 500, check_end - window_size), step_size):
            window_pv = pv_data[check_start:check_start + window_size]
            if len(window_pv) < window_size:
                break
            
            if self._check_large_deviation(window_pv, new_sv):
                has_large_deviation = True
            
            if check_start + window_size * 2 <= check_end:
                next_window_pv = pv_data[check_start + window_size:check_start + window_size * 2]
                window_mean_error = np.mean(np.abs(window_pv - new_sv))
                next_window_mean_error = np.mean(np.abs(next_window_pv - new_sv))
                
                if next_window_mean_error < window_mean_error * 0.9:
                    convergence_found = True
                    convergence_end = check_start + window_size * 2
            
            if self._check_large_oscillation(window_pv, new_sv, include_sign_changes=False):
                break
        
        if convergence_found:
            if has_large_deviation:
                additional_buffer = min(100, convergence_end - sv_stable_end)
                dynamic_buffer = min(dynamic_buffer, additional_buffer)
            else:
                additional_buffer = min(300, convergence_end - sv_stable_end)
                dynamic_buffer = max(dynamic_buffer, additional_buffer)
        
        osc_window = 40
        osc_step = 10
        
        for osc_start in range(sv_stable_end, check_end - osc_window, osc_step):
            osc_pv = pv_data[osc_start:osc_start + osc_window]
            if len(osc_pv) < osc_window:
                break
            
            if self._check_large_oscillation(osc_pv, new_sv):
                max_buffer = osc_start - sv_stable_end
                dynamic_buffer = min(dynamic_buffer, max_buffer)
                dynamic_buffer = max(30, dynamic_buffer)
                return dynamic_buffer
        
        return min(dynamic_buffer, 200)
    
    def is_steady_state(self, pv_data, setpoint, for_level=False):
        """判断一段数据是否处于稳态"""
        if len(pv_data) < self.min_len:
            return False
        
        pv_data = np.array(pv_data)
        n = len(pv_data)
        
        mean_val = np.mean(pv_data)
        std_val = np.std(pv_data)
        mean_dev = abs(mean_val - setpoint)
        
        if for_level:
            if mean_dev > self.tol or std_val > self.std_tol:
                return False
            if n > 10:
                try:
                    x = np.arange(n)
                    coeffs = np.polyfit(x, pv_data, 1)
                    slope = coeffs[0]
                    if abs(slope) > self.std_tol / n:
                        return False
                except:
                    pass
            return True
        else:
            if mean_dev > self.tol * 1.2:
                return False
            if std_val > self.std_tol:
                return False
            in_band_ratio = np.sum(np.abs(pv_data - setpoint) <= self.tol) / n
            if in_band_ratio < 0.95:
                return False
            if n > 10:
                try:
                    x = np.arange(n)
                    coeffs = np.polyfit(x, pv_data, 1)
                    slope = coeffs[0]
                    max_slope = self.std_tol / n * 2
                    if abs(slope) > max_slope:
                        return False
                except:
                    pass
            if n > 10:
                data_range = np.max(pv_data) - np.min(pv_data)
                if data_range > self.tol * 4:
                    return False
                if setpoint > 0 and data_range > abs(setpoint) * 0.3:
                    return False
            if n > 20:
                dy = np.diff(pv_data)
                d2y = np.diff(dy)
                if len(d2y) > 0:
                    d2y_std = np.std(d2y)
                    if d2y_std > self.std_tol * 2:
                        return False
                    dy_sign_changes = np.sum(np.diff(np.sign(dy)) != 0)
                    if dy_sign_changes > n * 0.3 and std_val > self.std_tol * 0.8:
                        return False
                    max_relative_dev = np.max(np.abs(pv_data - mean_val))
                    if max_relative_dev > self.tol * 2:
                        return False
            return True
    
    def is_setpoint_changing(self, sv_array, start_idx, end_idx, threshold=0.1):
        """检测指定区间内设定值是否正在变化"""
        if sv_array is None or len(sv_array) == 0:
            return False
        if end_idx - start_idx < 3:
            return False
        
        segment_sv = sv_array[start_idx:end_idx]
        seg_len = len(segment_sv)
        
        if threshold is None:
            sv_mean = np.mean(segment_sv)
            base_threshold = max(0.5, sv_mean * 0.05)
        else:
            base_threshold = float(np.mean(threshold)) if hasattr(threshold, '__len__') else float(threshold)
        
        if seg_len > 2000:
            effective_threshold = base_threshold * 5.0
        elif seg_len > 1000:
            effective_threshold = base_threshold * 2.0
        else:
            effective_threshold = base_threshold
        
        sv_range = np.max(segment_sv) - np.min(segment_sv)
        if sv_range > effective_threshold:
            return True
        
        sv_std = np.std(segment_sv)
        if sv_std > effective_threshold * 0.5:
            return True
        
        if seg_len > 5:
            x = np.arange(seg_len)
            try:
                coeffs = np.polyfit(x, segment_sv, 1)
                slope = abs(coeffs[0])
                slope_threshold = effective_threshold / seg_len
                if slope > slope_threshold:
                    return True
            except:
                pass
        
        if seg_len > 1:
            if abs(segment_sv[-1] - segment_sv[0]) > effective_threshold:
                return True
        
        return False
    
    def detect_setpoint_segments(self, sv_array, min_change=0.5, min_stable_points=20):
        """检测设定值变化点，将数据分段"""
        if sv_array is None or len(sv_array) < min_stable_points:
            return [(0, len(sv_array), np.mean(sv_array) if len(sv_array) > 0 else 0.0)]
        
        sv_array = np.array(sv_array)
        segments = []
        n = len(sv_array)
        
        window_size = min(5, n // 10)
        window_size = max(1, window_size)
        
        change_points = []
        for i in range(window_size, n - window_size):
            prev_window = sv_array[i - window_size:i]
            next_window = sv_array[i:i + window_size]
            prev_mean = np.mean(prev_window)
            next_mean = np.mean(next_window)
            
            if abs(next_mean - prev_mean) > min_change:
                if i + window_size < n:
                    check_window = sv_array[i:min(i + window_size * 2, n)]
                    check_mean = np.mean(check_window)
                    if abs(check_mean - next_mean) < min_change * 0.3:
                        if len(change_points) == 0 or i - change_points[-1] > window_size * 2:
                            change_points.append(i)
        
        if len(change_points) == 0:
            for i in range(1, n):
                if abs(sv_array[i] - sv_array[i-1]) > min_change:
                    if i + 3 < n:
                        next_avg = np.mean(sv_array[i:min(i+3, n)])
                        if abs(next_avg - sv_array[i]) < min_change * 0.5:
                            change_points.append(i)
                            break
        
        if len(change_points) == 0:
            segments.append((0, n, np.mean(sv_array)))
        else:
            start_idx = 0
            for change_idx in change_points:
                if change_idx > start_idx + min_stable_points:
                    seg_sv = np.mean(sv_array[start_idx:change_idx])
                    segments.append((start_idx, change_idx, seg_sv))
                    start_idx = change_idx
            if start_idx < n:
                seg_sv = np.mean(sv_array[start_idx:n])
                segments.append((start_idx, n, seg_sv))
        
        return segments
    
    def find_disturbance_start(self, pv_data, setpoint, steady_head_len, threshold=1.0):
        """定位扰动起始点（非稳态开始位置）"""
        n = len(pv_data)
        if n < steady_head_len + 10:
            return None
        
        steady_segment = pv_data[:steady_head_len]
        steady_mean = np.mean(steady_segment)
        steady_std = np.std(steady_segment)
        
        detected_start = None
        
        for i in range(steady_head_len, n - 5):
            if abs(pv_data[i] - setpoint) > threshold * 0.6:
                window = min(5, n - i)
                if window > 0:
                    window_data = pv_data[i:i+window]
                    if np.mean(np.abs(window_data - setpoint)) > threshold * 0.5:
                        detected_start = i
                        break
        
        if detected_start is None and n > steady_head_len + 20:
            dy = np.diff(pv_data)
            steady_dy = dy[:steady_head_len-1] if steady_head_len > 1 else dy[:min(10, len(dy))]
            steady_slope_mean = np.mean(np.abs(steady_dy))
            steady_slope_std = np.std(np.abs(steady_dy))
            
            for i in range(steady_head_len, len(dy) - 5):
                local_slope = np.abs(dy[i])
                if local_slope > steady_slope_mean + 1.5 * steady_slope_std:
                    window = min(5, len(dy) - i)
                    if window > 0:
                        window_slopes = np.abs(dy[i:i+window])
                        if np.mean(window_slopes) > steady_slope_mean + 0.8 * steady_slope_std:
                            detected_start = i + 1
                            break
        
        if detected_start is None and n > steady_head_len + 30:
            d2y = np.diff(np.diff(pv_data))
            if len(d2y) > steady_head_len:
                steady_d2y = d2y[:steady_head_len-2] if steady_head_len > 2 else d2y[:min(10, len(d2y))]
                steady_acc_mean = np.mean(np.abs(steady_d2y))
                steady_acc_std = np.std(np.abs(steady_d2y))
                
                for i in range(steady_head_len - 2, len(d2y) - 5):
                    local_acc = np.abs(d2y[i])
                    if local_acc > steady_acc_mean + 2.5 * steady_acc_std:
                        window = min(5, len(d2y) - i)
                        if window > 0:
                            window_acc = np.abs(d2y[i:i+window])
                            if np.mean(window_acc) > steady_acc_mean + 1.5 * steady_acc_std:
                                detected_start = i + 2
                                break
        
        if detected_start is not None and detected_start > steady_head_len:
            lookback = min(20, detected_start - steady_head_len)
            for i in range(detected_start - 1, detected_start - lookback - 1, -1):
                if abs(pv_data[i] - steady_mean) > steady_std * 2:
                    detected_start = i
                else:
                    break
        
        return detected_start
    
    def detect_sv_change_intervals(self, sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=None):
        """检测SV变化的所有区间（包括变化后的响应缓冲期）"""
        if sv_array is None or len(sv_array) < min_stable_points * 2:
            return []
        
        change_intervals = []
        n = len(sv_array)
        
        window_size = min(10, n // 20)
        window_size = max(3, window_size)
        
        i = 0
        while i < n - window_size:
            window_sv = sv_array[i:i+window_size]
            is_changing = self.is_setpoint_changing(window_sv, 0, len(window_sv), threshold=threshold)
            
            if is_changing:
                change_start = i
                prev_sv = np.median(sv_array[max(0, i-window_size):i]) if i > 0 else sv_array[i]
                
                j = i + window_size
                while j < n - window_size:
                    next_window_sv = sv_array[j:j+window_size]
                    is_still_changing = self.is_setpoint_changing(next_window_sv, 0, len(next_window_sv), threshold=threshold)
                    
                    if not is_still_changing:
                        stable_count = 0
                        for k in range(j, min(j + window_size * 3, n - window_size), window_size):
                            check_window = sv_array[k:k+window_size]
                            if not self.is_setpoint_changing(check_window, 0, len(check_window), threshold=threshold):
                                stable_count += 1
                            else:
                                break
                        
                        if stable_count >= 2:
                            new_sv = np.median(next_window_sv)
                            sv_change_magnitude = abs(new_sv - prev_sv)
                            sv_stable_end = j
                            
                            dynamic_buffer = min(response_buffer, int(response_buffer * (1 + sv_change_magnitude / 5.0)))
                            dynamic_buffer = max(30, dynamic_buffer)
                            dynamic_buffer = min(dynamic_buffer, 250)
                            
                            if pv_data is not None and sv_stable_end < len(pv_data):
                                dynamic_buffer = self._adjust_response_buffer(
                                    pv_data, sv_stable_end, new_sv, dynamic_buffer, n
                                )
                            
                            change_end = min(sv_stable_end + dynamic_buffer, n)
                            
                            if change_end - change_start >= min_stable_points:
                                change_intervals.append((change_start, change_end))
                            i = change_end
                            break
                    j += window_size // 2
                else:
                    change_end = n
                    if change_end - change_start >= min_stable_points:
                        change_intervals.append((change_start, change_end))
                    break
            else:
                i += window_size // 2
        
        return change_intervals
    
    def is_in_sv_change_interval(self, idx, sv_change_intervals):
        """检查索引是否在SV变化区间内"""
        for change_start, change_end in sv_change_intervals:
            if change_start <= idx < change_end:
                return True
        return False
    
    def is_converging_to_setpoint(self, pv_data, sv_array, start_idx, end_idx, setpoint):
        """判断PV是否正在向设定值收敛"""
        if end_idx - start_idx < 20:
            return False
        
        seg_pv = pv_data[start_idx:end_idx]
        seg_sv = sv_array[start_idx:end_idx] if start_idx < len(sv_array) else None
        
        if seg_sv is not None and len(seg_sv) > 0:
            current_sv = np.median(seg_sv)
        else:
            current_sv = setpoint
        
        initial_error = abs(seg_pv[0] - current_sv)
        final_error = abs(seg_pv[-1] - current_sv)
        
        if initial_error > 1.0 and final_error < initial_error * 0.7:
            seg_len = len(seg_pv)
            part1 = seg_pv[:seg_len//3]
            part2 = seg_pv[seg_len//3:2*seg_len//3]
            part3 = seg_pv[2*seg_len//3:]
            
            error1 = np.mean(np.abs(part1 - current_sv))
            error2 = np.mean(np.abs(part2 - current_sv))
            error3 = np.mean(np.abs(part3 - current_sv))
            
            if error1 > error2 and error2 > error3:
                if not self._check_large_oscillation(seg_pv, current_sv, strict=True):
                    return True
        
        if len(seg_pv) > 10:
            errors = np.abs(seg_pv - current_sv)
            x = np.arange(len(errors))
            try:
                coeffs = np.polyfit(x, errors, 1)
                slope = coeffs[0]
                if slope < -0.01 and initial_error > 5.0:
                    return True
            except:
                pass
        
        return False
    
    def detect_non_steady_segments(self, pv_data, sv_array, min_segment_len=20):
        """检测数据中的非稳态段（扰动段）"""
        n = len(pv_data)
        if n < min_segment_len * 2:
            return []
        
        non_steady_segments = []
        sv_change_intervals = self.detect_sv_change_intervals(sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=pv_data)
        
        # 在SV变化区间内检测大幅振荡
        for change_start, change_end in sv_change_intervals:
            if change_end - change_start >= min_segment_len:
                change_pv = pv_data[change_start:change_end]
                change_sv = sv_array[change_start:change_end]
                
                if len(change_pv) >= min_segment_len:
                    sv_start = change_sv[0] if len(change_sv) > 0 else 0
                    sv_end = change_sv[-1] if len(change_sv) > 0 else sv_start
                    sv_change_magnitude = abs(sv_end - sv_start)
                    current_sv = np.median(change_sv)
                    
                    if sv_change_magnitude < 0.5:
                        if self._check_large_oscillation(change_pv, current_sv):
                            non_steady_segments.append((change_start, change_end, current_sv))
                    else:
                        if self._check_abnormal_oscillation_during_sv_change(change_pv, change_sv, sv_change_magnitude):
                            non_steady_segments.append((change_start, change_end, current_sv))
        
        sv_segments = self.detect_setpoint_segments(sv_array, min_change=0.5, min_stable_points=20)
        
        for seg_start, seg_end, seg_setpoint in sv_segments:
            if seg_end - seg_start < min_segment_len:
                continue
            
            seg_in_change = False
            for change_start, change_end in sv_change_intervals:
                if change_start <= seg_start and seg_end <= change_end:
                    seg_in_change = True
                    break
            
            if seg_in_change:
                seg_pv = pv_data[seg_start:seg_end]
                seg_sv = sv_array[seg_start:seg_end]
                
                if len(seg_pv) >= min_segment_len:
                    current_sv = np.median(seg_sv) if len(seg_sv) > 0 else seg_setpoint
                    osc_start_idx = self._find_oscillation_start(pv_data, seg_start, seg_end, current_sv)
                    if osc_start_idx is not None:
                        non_steady_segments.append((osc_start_idx, seg_end, current_sv))
                continue
            
            is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
            seg_len = seg_end - seg_start
            
            has_large_oscillation_in_seg = False
            if is_sv_changing and seg_len < 1000:
                seg_pv_check = pv_data[seg_start:seg_end]
                if len(seg_pv_check) > 0:
                    seg_pv_range = np.max(seg_pv_check) - np.min(seg_pv_check)
                    seg_pv_std = np.std(seg_pv_check)
                    if seg_pv_range > 15.0 or seg_pv_std > 8.0:
                        has_large_oscillation_in_seg = True
            
            if is_sv_changing and seg_len < 1000 and not has_large_oscillation_in_seg:
                tail_len = max(30, (seg_end - seg_start) // 4)
                if tail_len > 0 and seg_end - tail_len >= seg_start:
                    stable_sv_part = sv_array[seg_end - tail_len:seg_end]
                    stable_sv = np.median(stable_sv_part) if len(stable_sv_part) > 0 else seg_setpoint
                    
                    tail_segment = pv_data[seg_end - tail_len:seg_end]
                    is_tail_steady = self.is_steady_state(tail_segment, stable_sv)
                    if not is_tail_steady:
                        stable_sv_start = None
                        for i in range(seg_end - tail_len, seg_start, -10):
                            if i < seg_start:
                                break
                            if self.is_in_sv_change_interval(i, sv_change_intervals):
                                continue
                            sv_check = sv_array[i:seg_end] if i < len(sv_array) else []
                            if len(sv_check) > 0 and not self.is_setpoint_changing(sv_check, 0, len(sv_check), threshold=0.1):
                                stable_sv_start = i
                                break
                        
                        if stable_sv_start is not None:
                            osc_start_idx = self._find_oscillation_start(pv_data, stable_sv_start, seg_end, stable_sv)
                            if osc_start_idx is not None:
                                non_steady_end = seg_end
                                for change_start, change_end in sv_change_intervals:
                                    if change_start < non_steady_end <= change_end:
                                        non_steady_end = change_start
                                        break
                                if non_steady_end > osc_start_idx and non_steady_end - osc_start_idx >= min_segment_len:
                                    non_steady_segments.append((osc_start_idx, non_steady_end, stable_sv))
                continue
            
            seg_pv = pv_data[seg_start:seg_end]
            window = min(30, (seg_end - seg_start) // 5)
            window = max(10, window)
            
            i = seg_start
            while i < seg_end - window:
                in_sv_change = self.is_in_sv_change_interval(i, sv_change_intervals)
                window_data = pv_data[i:i+window]
                
                if in_sv_change:
                    window_sv = sv_array[i:i+window] if i < len(sv_array) and i+window <= len(sv_array) else None
                    current_sv = np.median(window_sv) if window_sv is not None and len(window_sv) > 0 else seg_setpoint
                    
                    if not self._check_large_oscillation(window_data, current_sv, include_sign_changes=False) and \
                       not self._check_rapid_change(window_data):
                        i += window // 3
                        continue
                
                is_steady = self.is_steady_state(window_data, seg_setpoint)
                
                if not is_steady:
                    if not self._check_large_oscillation(window_data, seg_setpoint):
                        i += window // 3
                        continue
                    
                    start_idx = i
                    max_backtrack = min(1000, i - seg_start)
                    back_step = 10
                    
                    for back_offset in range(back_step, max_backtrack + back_step, back_step):
                        if start_idx - back_offset < seg_start:
                            break
                        back_start = start_idx - back_offset
                        back_end = min(back_start + window, start_idx)
                        back_window = pv_data[back_start:back_end]
                        
                        if len(back_window) < window // 2:
                            break
                        
                        if self._is_window_unstable(back_window, seg_setpoint):
                            start_idx = back_start
                        else:
                            break
                    
                    start_idx = self._backtrack_to_true_start(pv_data, start_idx, seg_start, seg_setpoint, max_lookback=80)
                    
                    j = i + window
                    while j < seg_end - window:
                        in_sv_change = self.is_in_sv_change_interval(j, sv_change_intervals)
                        
                        if in_sv_change:
                            check_window = pv_data[j:j+window]
                            check_sv = sv_array[j:j+window] if j < len(sv_array) else None
                            check_sv_val = np.median(check_sv) if check_sv is not None and len(check_sv) > 0 else seg_setpoint
                            
                            if self._check_large_oscillation(check_window, check_sv_val) or \
                               self._check_large_deviation(check_window, check_sv_val):
                                j += window // 2
                                continue
                            else:
                                end_idx = j
                                if end_idx - start_idx >= min_segment_len:
                                    non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                                for change_start, change_end in sv_change_intervals:
                                    if change_start <= j < change_end:
                                        i = change_end
                                        break
                                else:
                                    i = j
                                break
                        
                        next_window = pv_data[j:j+window]
                        if self.is_steady_state(next_window, seg_setpoint):
                            end_idx = j
                            if end_idx - start_idx >= min_segment_len:
                                non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                            i = j
                            break
                        j += window // 2
                    else:
                        end_idx = seg_end
                        for change_start, change_end in sv_change_intervals:
                            if change_start < end_idx <= change_end:
                                end_idx = change_start
                                break
                        if end_idx - start_idx >= min_segment_len:
                            non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                        break
                else:
                    i += window // 2
        
        # 过滤和合并
        filtered_segments = []
        for seg_start, seg_end, seg_setpoint in non_steady_segments:
            has_overlap = False
            for change_start, change_end in sv_change_intervals:
                if not (seg_end <= change_start or seg_start >= change_end):
                    has_overlap = True
                    break
            
            if has_overlap:
                seg_pv = pv_data[seg_start:seg_end]
                if len(seg_pv) >= min_segment_len:
                    overlap_sv = sv_array[seg_start:min(seg_end, len(sv_array))]
                    new_sv = np.median(overlap_sv) if len(overlap_sv) > 0 else seg_setpoint
                    if self._check_large_oscillation(seg_pv, seg_setpoint) or self._check_large_deviation(seg_pv, new_sv):
                        filtered_segments.append((seg_start, seg_end, seg_setpoint))
                        continue
            
            is_response_to_sv_change = False
            for change_start, change_end in sv_change_intervals:
                if change_end <= seg_start <= change_end + 50:
                    if change_end < len(sv_array):
                        new_sv = np.median(sv_array[change_end:min(change_end+20, len(sv_array))])
                        if seg_start < len(pv_data) and seg_end <= len(pv_data):
                            seg_pv = pv_data[seg_start:seg_end]
                            if self._check_large_oscillation(seg_pv, new_sv):
                                is_response_to_sv_change = False
                                break
                            pv_start = seg_pv[0] if len(seg_pv) > 0 else pv_data[seg_start]
                            pv_end = seg_pv[-1] if len(seg_pv) > 0 else pv_data[min(seg_end-1, len(pv_data)-1)]
                            error_start = abs(pv_start - new_sv)
                            error_end = abs(pv_end - new_sv)
                            if error_end < error_start * 1.2:
                                is_response_to_sv_change = True
                                break
            
            if not is_response_to_sv_change:
                is_converging = self.is_converging_to_setpoint(pv_data, sv_array, seg_start, seg_end, seg_setpoint)
                if not is_converging:
                    filtered_segments.append((seg_start, seg_end, seg_setpoint))
        
        if not filtered_segments:
            return []
        
        # 合并相邻段
        filtered_segments.sort(key=lambda x: x[0])
        merged_segments = [filtered_segments[0]]
        
        for i in range(1, len(filtered_segments)):
            last_start, last_end, last_sp = merged_segments[-1]
            cur_start, cur_end, cur_sp = filtered_segments[i]
            gap_length = cur_start - last_end
            sp_diff = abs(cur_sp - last_sp)
            
            if cur_start <= last_end:
                if sp_diff < 0.5:
                    merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
                else:
                    merged_segments.append((cur_start, cur_end, cur_sp))
            elif gap_length < 15 or (gap_length < 100 and sp_diff < 0.5) or (gap_length <= 50 and sp_diff < 3.0) or (gap_length < 30 and sp_diff < 5.0):
                merged_segments[-1] = (last_start, cur_end, last_sp)
            else:
                # 对于任意长度的间隔，检查是否应该合并
                gap_start = last_end
                gap_end = cur_start
                gap_sv = sv_array[gap_start:gap_end] if gap_start < len(sv_array) and gap_end <= len(sv_array) else None
                
                # 检查间隔区域的特征
                has_non_steady_features = self._has_non_steady_features(pv_data[gap_start:gap_end], last_sp) if gap_end > gap_start else False
                
                # 如果间隔区域也有非稳态特征且设定值相同，则合并
                if has_non_steady_features and sp_diff < 0.5:
                    merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
                elif gap_length < min_segment_len * 10:
                    # 较短间隔额外检查稳态
                    is_gap_steady = self._check_gap_steady_state(pv_data, sv_array, gap_start, gap_end, gap_sv, last_sp)
                    should_merge = (not is_gap_steady and has_non_steady_features and sp_diff < 15.0)
                    if should_merge:
                        merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
                    else:
                        merged_segments.append((cur_start, cur_end, cur_sp))
                else:
                    merged_segments.append((cur_start, cur_end, cur_sp))
        
        return merged_segments
    
    def _check_gap_steady_state(self, pv_data, sv_array, gap_start, gap_end, gap_sv, fallback_sp):
        """检查间隔区域是否为稳态"""
        if gap_sv is None or len(gap_sv) == 0:
            gap_setpoint = fallback_sp
            return self._is_region_steady(pv_data, sv_array, gap_start, gap_end, gap_setpoint)
        
        sv_range = np.max(gap_sv) - np.min(gap_sv)
        
        if sv_range > 1.0:
            stable_start_offset = 0
            for j in range(len(gap_sv) - 1, 0, -1):
                if abs(gap_sv[j] - gap_sv[-1]) > 0.5:
                    stable_start_offset = j + 1
                    break
            
            stable_length = len(gap_sv) - stable_start_offset
            if stable_length >= 50:
                stable_region_start = gap_start + stable_start_offset
                stable_sv = np.median(gap_sv[stable_start_offset:])
                return self._is_region_steady(pv_data, sv_array, stable_region_start, gap_end, stable_sv)
            return False
        
        gap_setpoint = np.median(gap_sv)
        return self._is_region_steady(pv_data, sv_array, gap_start, gap_end, gap_setpoint)
    
    def _has_non_steady_features(self, gap_pv, setpoint=None):
        """检查区域是否有明显的非稳态特征"""
        if len(gap_pv) <= 10:
            return False
        
        # 检查首尾差值
        if abs(gap_pv[-1] - gap_pv[0]) > 3.0:
            return True
        
        # 检查PV范围和标准差（相对于设定值）
        pv_range = np.max(gap_pv) - np.min(gap_pv)
        pv_std = np.std(gap_pv)
        
        # 如果PV范围较大，认为有非稳态特征
        if setpoint is not None and setpoint > 0:
            # PV范围超过设定值的50%，或标准差超过20%
            if pv_range > setpoint * 0.5 or pv_std > setpoint * 0.2:
                return True
        else:
            # 绝对值判断
            if pv_range > 2.5 or pv_std > 0.5:
                return True
        
        # 检查趋势
        try:
            x = np.arange(len(gap_pv))
            coeffs = np.polyfit(x, gap_pv, 1)
            if abs(coeffs[0]) > 0.08:
                return True
        except:
            pass
        
        return False
    
    def _is_region_steady(self, pv_data, sv_array, start_idx, end_idx, setpoint):
        """检查指定区域是否为稳态"""
        if end_idx - start_idx < 10:
            return False
        
        start_idx = max(0, start_idx)
        end_idx = min(len(pv_data), end_idx)
        
        if start_idx >= end_idx:
            return False
        
        region_pv = pv_data[start_idx:end_idx]
        region_sv = sv_array[start_idx:end_idx] if start_idx < len(sv_array) and end_idx <= len(sv_array) else None
        
        if region_sv is not None and len(region_sv) > 0:
            sv_range = np.max(region_sv) - np.min(region_sv)
            sv_std = np.std(region_sv)
            if sv_range > 1.0 or sv_std > 0.5:
                return False
            current_sv = np.median(region_sv)
        else:
            current_sv = setpoint
        
        pv_std = np.std(region_pv)
        pv_range = np.max(region_pv) - np.min(region_pv)
        pv_mean = np.mean(region_pv)
        
        if pv_range == 0 and pv_mean < 0.1:
            return False
        
        # 判断低变化：PV标准差和范围都要小
        # 增加绝对值判断，避免设定值较小时阈值过低
        if current_sv > 0:
            std_threshold = max(current_sv * 0.12, 0.3)  # 至少0.3
            range_threshold = max(current_sv * 0.25, 0.8)  # 至少0.8
            is_low_variation = (pv_std < std_threshold and pv_range < range_threshold)
        else:
            is_low_variation = (pv_std < 0.5 and pv_range < 1.5)
        
        has_no_trend = True
        if len(region_pv) > 10:
            try:
                coeffs = np.polyfit(np.arange(len(region_pv)), region_pv, 1)
                if abs(coeffs[0]) > 0.05:
                    has_no_trend = False
            except:
                pass
        
        return is_low_variation and has_no_trend
    
    def detect_all_disturbances(self, pv_data, sv_array, non_steady_segments=None):
        """检测所有扰动（非稳态）的起始点"""
        n = len(pv_data)
        if n < 50:
            return []
        
        disturbance_starts = []
        sv_change_intervals = self.detect_sv_change_intervals(sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=pv_data)
        
        if non_steady_segments is not None and len(non_steady_segments) > 0:
            for seg_start, seg_end, seg_setpoint in non_steady_segments:
                seg_pv = pv_data[seg_start:min(seg_end, len(pv_data))]
                has_large_oscillation = False
                if len(seg_pv) >= 20:
                    pv_range = np.max(seg_pv) - np.min(seg_pv)
                    pv_std = np.std(seg_pv)
                    if seg_setpoint > 0:
                        if pv_range > max(seg_setpoint * 0.5, 5.0) or pv_std > max(seg_setpoint * 0.3, 2.0):
                            has_large_oscillation = True
                    else:
                        if pv_range > 5.0 or pv_std > 2.0:
                            has_large_oscillation = True
                
                in_sv_change = self.is_in_sv_change_interval(seg_start, sv_change_intervals)
                if in_sv_change and not has_large_oscillation:
                    continue
                
                if not has_large_oscillation:
                    is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
                    if is_sv_changing:
                        continue
                
                head_len = min(50, (seg_end - seg_start) // 3)
                if head_len >= 20:
                    head_segment = pv_data[seg_start:seg_start + head_len]
                    is_head_steady = self.is_steady_state(head_segment, seg_setpoint)
                    
                    if is_head_steady:
                        disturbance_start = self.find_disturbance_start(
                            pv_data[seg_start:seg_end], seg_setpoint, head_len, threshold=0.5
                        )
                        if disturbance_start is not None:
                            disturbance_starts.append((seg_start + disturbance_start, seg_setpoint))
                        else:
                            disturbance_starts.append((seg_start, seg_setpoint))
                    else:
                        disturbance_starts.append((seg_start, seg_setpoint))
                else:
                    disturbance_starts.append((seg_start, seg_setpoint))
        
        if non_steady_segments is None or len(non_steady_segments) == 0:
            sv_segments = self.detect_setpoint_segments(sv_array, min_change=0.5, min_stable_points=20)
            
            for seg_start, seg_end, seg_setpoint in sv_segments:
                if seg_end - seg_start < 50:
                    continue
                
                is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
                if is_sv_changing:
                    continue
                
                head_len = min(50, (seg_end - seg_start) // 3)
                if head_len >= 20:
                    head_segment = pv_data[seg_start:seg_start + head_len]
                    is_head_steady = self.is_steady_state(head_segment, seg_setpoint)
                    
                    if is_head_steady:
                        disturbance_start = self.find_disturbance_start(
                            pv_data[seg_start:seg_end], seg_setpoint, head_len, threshold=0.5
                        )
                        if disturbance_start is not None:
                            disturbance_starts.append((seg_start + disturbance_start, seg_setpoint))
        
        if len(disturbance_starts) > 1:
            disturbance_starts.sort(key=lambda x: x[0])
            unique_starts = []
            for start_idx, setpoint in disturbance_starts:
                if len(unique_starts) == 0 or start_idx - unique_starts[-1][0] >= 10:
                    unique_starts.append((start_idx, setpoint))
            disturbance_starts = unique_starts
        
        return disturbance_starts


def find_high_variability_periods(
    pv_series: pd.Series,
    sv_series: Optional[pd.Series] = None,
    tol: float = 0.5,
    std_tol: float = 0.2,
    min_len: int = 10,
    min_segment_len: int = 20,
    analyst_column: Optional[str] = None,
    window_sec: Optional[int] = None,
    is_filter: bool = False
) -> Dict[str, Any]:
    """
    使用StabilityDetector检测高波动时间段
    
    参数:
    - pv_series: 过程值时间序列, Pandas Series with datetime index
    - sv_series: 设定值时间序列, Pandas Series with datetime index (可选)
    - tol: 容差（PV与设定值的允许偏差）
    - std_tol: 标准差阈值
    - min_len: 最小数据长度
    - min_segment_len: 最小非稳态段长度
    - analyst_column: 分析的列名（用于记录）
    - window_sec: 窗口秒数（用于时间转换）
    - is_filter: 是否进行滤波处理

    返回:
    - dict: 包含以下字段的字典:
        - table: 高波动时间段表格数据
        - start_time: 数据起始时间
        - end_time: 数据结束时间
        - params: 参数字典
        - total_windows: 总窗口数（这里表示检测到的非稳态段数）
        - std_max_window: 最大标准差的窗口
    """
    try:
        # 确保pv_series是Pandas Series
        if not isinstance(pv_series, pd.Series):
            raise ValueError("pv_series必须是Pandas Series类型")
        
        # 确保有datetime index
        if not isinstance(pv_series.index, pd.DatetimeIndex):
            try:
                pv_series.index = pd.to_datetime(pv_series.index)
            except Exception:
                raise ValueError("pv_series的index必须是datetime类型或可转换为datetime")
        
        # 数据预处理
        pv_processed = pv_series.copy()
        if is_filter:
            pv_processed = pv_processed.rolling(window=5, min_periods=1, center=True).mean()
        
        # 获取起止时间
        start_time = pv_processed.index[0]
        end_time = pv_processed.index[-1]
        
        # 转换为numpy数组
        pv_data = pv_processed.values.astype(float)
        
        # 处理sv_series
        if sv_series is not None:
            if not isinstance(sv_series, pd.Series):
                raise ValueError("sv_series必须是Pandas Series类型")
            if not isinstance(sv_series.index, pd.DatetimeIndex):
                try:
                    sv_series.index = pd.to_datetime(sv_series.index)
                except Exception:
                    raise ValueError("sv_series的index必须是datetime类型或可转换为datetime")
            sv_data = sv_series.values.astype(float)
        else:
            # 如果没有提供sv_series，使用pv的均值作为设定值
            sv_data = np.full(len(pv_data), np.mean(pv_data))
        
        # 确保pv和sv长度一致
        min_len_data = min(len(pv_data), len(sv_data))
        pv_data = pv_data[:min_len_data]
        sv_data = sv_data[:min_len_data]
        
        # 创建检测器并执行检测
        detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=min_len)
        
        # 检测非稳态段
        non_steady_segments = detector.detect_non_steady_segments(pv_data, sv_data, min_segment_len=min_segment_len)
        
        # 检测扰动起始点
        disturbance_starts = detector.detect_all_disturbances(pv_data, sv_data, non_steady_segments)
        
        # 构建输出表格
        table = []
        std_max_window = None
        max_std = 0.0
        
        for seg_start, seg_end, seg_setpoint in non_steady_segments:
            seg_pv = pv_data[seg_start:seg_end]
            
            # 计算统计量
            seg_std = float(np.std(seg_pv))
            seg_var = float(np.var(seg_pv))
            seg_mean = float(np.mean(seg_pv))
            seg_min = float(np.min(seg_pv))
            seg_max = float(np.max(seg_pv))
            seg_range = seg_max - seg_min
            
            # 计算步长变化度
            diffs = np.diff(seg_pv) if len(seg_pv) > 1 else np.array([], dtype=float)
            step_degree = float(np.std(diffs)) if len(diffs) > 1 else 0.0
            
            # 获取时间
            seg_start_time = pv_processed.index[seg_start] if seg_start < len(pv_processed) else None
            seg_end_time = pv_processed.index[min(seg_end - 1, len(pv_processed) - 1)] if seg_end > 0 else None
            
            table.append({
                "start_time": seg_start_time,
                "end_time": seg_end_time,
                "start_idx": seg_start,
                "end_idx": seg_end,
                "setpoint": seg_setpoint,
                "variance": seg_var,
                "std": seg_std,
                "mean": seg_mean,
                "min": seg_min,
                "max": seg_max,
                "range": seg_range,
                "step_degree": step_degree
            })
            
            # 记录最大标准差的窗口
            if seg_std > max_std:
                max_std = seg_std
                std_max_window = {
                    "start_time": seg_start_time,
                    "end_time": seg_end_time,
                    "start_idx": seg_start,
                    "end_idx": seg_end,
                    "std": seg_std,
                    "variance": seg_var
                }
        
        # 构建 tuning_window：每个扰动段的开始和结束时间
        tuning_window = []
        for seg_start, seg_end, seg_setpoint in non_steady_segments:
            seg_start_time = pv_processed.index[seg_start] if seg_start < len(pv_processed) else None
            seg_end_time = pv_processed.index[min(seg_end - 1, len(pv_processed) - 1)] if seg_end > 0 else None
            tuning_window.append({
                "start_time": seg_start_time,
                "end_time": seg_end_time
            })
        
        return {
            "table": [],
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": min_segment_len,
                "step_size": min_len,
                "variability_threshold": std_tol,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": len(non_steady_segments),
            "tuning_window": tuning_window
        }
    
    except Exception as e:
        return {
            "table": [],
            "start_time": None,
            "end_time": None,
            "params": {
                "window_size": min_segment_len,
                "step_size": min_len,
                "variability_threshold": std_tol,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": 0,
            "tuning_window": [],
            "error": str(e)
        }


def merge_adjacent_periods(
    periods: List[Dict[str, Any]],
    max_gap: int = 100
) -> List[Dict[str, Any]]:
    """
    合并相邻的高波动时间段

    Args:
        periods: 高波动时间段列表
        max_gap: 最大允许的间隔（索引点数）

    Returns:
        list: 合并后的时间段列表
    """
    if not periods:
        return []
    
    # 按起始索引排序
    sorted_periods = sorted(periods, key=lambda x: x.get("start_idx", 0))
    
    merged = [sorted_periods[0].copy()]
    
    for current in sorted_periods[1:]:
        last = merged[-1]
        
        # 检查是否可以合并
        gap = current.get("start_idx", 0) - last.get("end_idx", 0)
        
        if gap <= max_gap:
            # 合并
            merged[-1] = {
                "start_time": last.get("start_time"),
                "end_time": current.get("end_time"),
                "start_idx": last.get("start_idx"),
                "end_idx": current.get("end_idx"),
                "setpoint": last.get("setpoint"),
                "variance": max(last.get("variance", 0), current.get("variance", 0)),
                "std": max(last.get("std", 0), current.get("std", 0)),
                "mean": (last.get("mean", 0) + current.get("mean", 0)) / 2,
                "range": max(last.get("range", 0), current.get("range", 0)),
                "step_degree": max(last.get("step_degree", 0), current.get("step_degree", 0))
            }
        else:
            merged.append(current.copy())
    
    return merged


# 兼容性别名
HighVariabilityDetector = StabilityDetector
