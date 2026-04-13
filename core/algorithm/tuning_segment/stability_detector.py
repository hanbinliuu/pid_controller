"""
稳定性检测器模块 (Stability Detector Module)
============================================

本模块实现非稳态（扰动）段的自动检测算法，用于从历史数据中
识别适合进行模型辨识的扰动时间段。

核心功能
--------
1. **非稳态检测**: 检测数据中的非稳态段（扰动段）
2. **稳态判断**: 判断一段数据是否处于稳态
3. **SV变化检测**: 检测设定值变化点和响应缓冲期
4. **扰动起始定位**: 精确定位扰动的起始点
5. **段合并与分割**: 合并相邻扰动段，分割过长的段

检测逻辑
--------
1. 检测SV变化区间及其响应缓冲期
2. 在SV稳定区间内检测大幅振荡
3. 使用滑动窗口检测非稳态特征
4. 回溯查找真正的扰动起始点
5. 过滤收敛过程（正常响应）
6. 合并相邻的扰动段

阈值配置
--------
- tol: 容差（PV与设定值的允许偏差）
- std_tol: 标准差阈值
- min_len: 最小数据长度

输入输出
--------
输入: pv_data (np.ndarray), sv_array (np.ndarray)
输出: 非稳态段列表 [(start_idx, end_idx, setpoint), ...]

使用示例
--------
>>> detector = StabilityDetector(tol=0.5, std_tol=0.2)
>>> segments = detector.detect_non_steady_segments(pv_data, sv_array)
>>> for start, end, sp in segments:
...     print(f"扰动段: [{start}, {end}], 设定值={sp}")
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
    
    # ============================================================
    # 基础统计方法
    # ============================================================
    
    def _calculate_sign_changes(self, data):
        """计算数据的方向改变次数（用于振荡检测）"""
        if len(data) < 2:
            return 0
        diff = np.diff(data)
        if len(diff) < 2:
            return 0
        return np.sum(np.diff(np.sign(diff)) != 0)
    
    # ============================================================
    # 振荡与稳态检测方法
    # ============================================================
    
    def _check_large_oscillation(self, pv_data, setpoint, include_sign_changes=True, strict=False, during_sv_change=False):
        """
        检查是否存在大幅振荡
        
        Args:
            pv_data: PV数据数组
            setpoint: 设定值
            include_sign_changes: 是否考虑符号变化次数
            strict: 是否使用严格阈值
            during_sv_change: 是否在SV变化期间（使用更高阈值避免误识别）
        
        Returns:
            bool: 是否存在大幅振荡
        """
        if len(pv_data) < 10:
            return False
        
        pv_range = np.max(pv_data) - np.min(pv_data)
        pv_std = np.std(pv_data)
        
        if strict:
            range_ratio, std_ratio = 0.7, 0.4
            abs_range, abs_std = 7.0, 3.5
            sign_ratio, sign_std_ratio = 0.2, 0.25
        elif during_sv_change:
            # SV变化期间使用适度的阈值，避免将正常响应误识别为扰动，但也要能检测明显的异常
            if pv_range > 10.0 or pv_std > 5.0:
                return True
            range_ratio, std_ratio = 0.45, 0.28
            abs_range, abs_std = 3.0, 1.0  # 降低阈值，便于检测小幅度但明显的扰动
            sign_ratio = 0.15 if len(pv_data) > 100 else 0.2
            sign_std_ratio = 0.2
        else:
            if pv_range > 15.0 or pv_std > 8.0:
                return True
            range_ratio, std_ratio = 0.4, 0.25
            # 降低小设定值场景的绝对阈值，使小幅振荡能被检测
            # pv_range > 1.5 或 pv_std > 0.4 即可触发
            abs_range, abs_std = 1.5, 0.4
            sign_ratio = 0.1 if len(pv_data) > 100 else 0.15
            sign_std_ratio = 0.15
        
        if setpoint > 0:
            if pv_range > min(max(setpoint * range_ratio, abs_range), 5.0) or pv_std > min(max(setpoint * std_ratio, abs_std), 2.5):
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
            return pv_range > min(max(setpoint * 0.2, 2.0), 3.0) or pv_std > min(max(setpoint * 0.12, 1.0), 1.5)
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
    
    def _is_normal_sv_response(self, pv_data, sv_data, sv_change_magnitude):
        """
        判断PV是否是SV变化后的正常响应（而不是扰动）
        
        正常响应特征：
        1. PV变化方向与SV变化方向一致
        2. PV最终收敛到新的SV值附近
        3. PV范围相对于SV变化幅度是合理的（PV范围 < SV变化幅度 * 3）
        4. 没有高频振荡
        
        Args:
            pv_data: PV数据
            sv_data: SV数据
            sv_change_magnitude: SV变化幅度
        
        Returns:
            bool: 是否是正常响应
        """
        if len(pv_data) < 10 or len(sv_data) < 10:
            return False
        
        # 1. 检查PV变化方向是否与SV一致
        sv_direction = sv_data[-1] - sv_data[0]  # SV变化方向
        pv_direction = pv_data[-1] - pv_data[0]  # PV变化方向
        
        # 方向一致（同正或同负）
        direction_consistent = (sv_direction * pv_direction >= 0)
        
        # 2. 检查PV是否收敛到新的SV值
        new_sv = sv_data[-1]
        final_error = abs(pv_data[-1] - new_sv)
        initial_error = abs(pv_data[0] - sv_data[0])
        
        # PV最终误差小于SV变化幅度的50%，认为收敛
        is_converging = final_error < sv_change_magnitude * 0.5 or final_error < 2.0
        
        # 3. 检查PV范围是否合理
        pv_range = np.max(pv_data) - np.min(pv_data)
        # PV范围应该在SV变化幅度的3倍以内（允许一定的超调）
        range_reasonable = pv_range < sv_change_magnitude * 3.0 or pv_range < 10.0
        
        # 4. 检查是否有高频振荡
        sign_changes = self._calculate_sign_changes(pv_data)
        # 正常响应不应该有太多的方向变化
        no_high_freq_oscillation = sign_changes < len(pv_data) * 0.25
        
        # 5. 检查PV标准差是否合理
        pv_std = np.std(pv_data)
        std_reasonable = pv_std < sv_change_magnitude * 1.0 or pv_std < 3.0
        
        # 综合判断：需要满足大部分条件
        conditions_met = sum([
            direction_consistent,
            is_converging,
            range_reasonable,
            no_high_freq_oscillation,
            std_reasonable
        ])
        
        return conditions_met >= 4  # 至少满足4个条件
    
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
    
    # ============================================================
    # 稳态判断方法
    # ============================================================
    
    def is_steady_state(self, pv_data, setpoint, for_level=False):
        """
        判断一段数据是否处于稳态
        
        综合考虑以下因素：
        - 均值与设定值的偏差
        - 标准差是否在阈值内
        - 是否存在明显趋势
        - 数据范围是否过大
        - 振荡频率是否过高
        
        Args:
            pv_data: PV数据数组
            setpoint: 设定值
            for_level: 是否用于液位等积分过程（使用不同判据）
        
        Returns:
            bool: 是否处于稳态
        """
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
    
    # ============================================================
    # 设定值变化检测方法
    # ============================================================
    
    def is_setpoint_changing(self, sv_array, start_idx, end_idx, threshold=0.1):
        """
        检测指定区间内设定值是否正在变化
        
        Args:
            sv_array: SV数据数组
            start_idx: 起始索引
            end_idx: 结束索引
            threshold: 变化阈值
        
        Returns:
            bool: 是否正在变化
        """
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
    
    # ============================================================
    # 核心检测方法
    # ============================================================
    
    def detect_non_steady_segments(self, pv_data, sv_array, min_segment_len=30):
        """
        检测数据中的非稳态段（扰动段）
        
        这是本模块的核心方法，综合使用多种策略检测非稳态段：
        1. 检测SV变化区间内的大幅振荡
        2. 在SV稳定区间使用滑动窗口检测
        3. 回溯查找真正的扰动起始点
        4. 过滤正常收敛过程
        5. 合并相邻扰动段
        
        Args:
            pv_data: PV数据数组
            sv_array: SV数据数组
            min_segment_len: 最小段长度（小于此值的段会被过滤）
        
        Returns:
            list: 非稳态段列表 [(start_idx, end_idx, setpoint), ...]
        """
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
                    
                    # 先检查是否是正常的SV跟随响应
                    if self._is_normal_sv_response(change_pv, change_sv, sv_change_magnitude):
                        # 正常响应 → 但仍检查PV是否在跟随SV时有振荡
                        # SV阶跃后PV的超调/回调是有效的整定数据
                        if sv_change_magnitude >= 1.0 and len(change_pv) >= 30:
                            error_signal = change_pv - change_sv
                            # PV跨越SV的次数（error信号过零）
                            sv_crossings = int(np.sum(np.abs(np.diff(np.sign(error_signal))) > 0))
                            # PV方向变化次数
                            pv_diff = np.diff(change_pv)
                            pv_diff_nonzero = pv_diff[pv_diff != 0]
                            direction_changes = 0
                            if len(pv_diff_nonzero) >= 2:
                                direction_changes = int(np.sum(np.abs(np.diff(np.sign(pv_diff_nonzero))) > 0))
                            # PV跨越SV ≥ 2次 或 有方向变化 → 有效振荡数据
                            if sv_crossings >= 2 or direction_changes >= 2:
                                non_steady_segments.append((change_start, change_end, current_sv))
                        continue
                    
                    if sv_change_magnitude < 0.5:
                        # SV变化幅度小时，使用更高阈值检测
                        if self._check_large_oscillation(change_pv, current_sv, during_sv_change=True):
                            non_steady_segments.append((change_start, change_end, current_sv))
                    elif sv_change_magnitude > 5.0:
                        # SV变化幅度大时，检查是否有剧烈振荡（PV范围远大于SV变化）
                        pv_range = np.max(change_pv) - np.min(change_pv)
                        # 只有PV范围远超SV变化幅度（>5倍）或有明显异常振荡才认为是扰动
                        if pv_range > sv_change_magnitude * 5 or \
                           self._check_abnormal_oscillation_during_sv_change(change_pv, change_sv, sv_change_magnitude):
                            non_steady_segments.append((change_start, change_end, current_sv))
                    else:
                        # SV变化幅度中等时，检测异常振荡或大幅振荡
                        if self._check_abnormal_oscillation_during_sv_change(change_pv, change_sv, sv_change_magnitude) or \
                           self._check_large_oscillation(change_pv, current_sv, during_sv_change=True):
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
            window = min(60, (seg_end - seg_start) // 5)
            window = max(10, window)
            
            i = seg_start
            while i < seg_end - window:
                in_sv_change = self.is_in_sv_change_interval(i, sv_change_intervals)
                window_data = pv_data[i:i+window]
                
                if in_sv_change:
                    window_sv = sv_array[i:i+window] if i < len(sv_array) and i+window <= len(sv_array) else None
                    current_sv = np.median(window_sv) if window_sv is not None and len(window_sv) > 0 else seg_setpoint
                    
                    # SV变化期间使用更高阈值，避免将正常响应误识别为扰动
                    if not self._check_large_oscillation(window_data, current_sv, include_sign_changes=False, during_sv_change=True) and \
                       not self._check_rapid_change(window_data):
                        i += window // 3
                        continue
                
                is_steady = self.is_steady_state(window_data, seg_setpoint)
                
                if not is_steady:
                    # 在SV稳定期间使用更高阈值，避免将正常响应误识别为扰动
                    is_large_osc = self._check_large_oscillation(window_data, seg_setpoint, during_sv_change=in_sv_change)
                    
                    # 补充：针对极慢系统（如大榭液位），短窗(60点)内变化极小，会一直continue
                    # 这里引入长窗(300~400点)的慢漂移(Slow Drift)检测
                    is_slow_drift = False
                    if not is_large_osc and not in_sv_change:
                        long_window_len = min(400, seg_end - i)
                        if long_window_len >= 100:
                            long_window_data = pv_data[i: i + long_window_len]
                            long_range = np.max(long_window_data) - np.min(long_window_data)
                            long_dev = abs(np.mean(long_window_data) - seg_setpoint)
                            # 如果长窗内范围>3.0 或 均值偏离>2.0，认为是慢漂移扰动
                            if long_range > 3.0 or long_dev > 2.0:
                                is_slow_drift = True
                    
                    if not is_large_osc and not is_slow_drift:
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
                            
                            # SV变化期间使用更高阈值
                            if self._check_large_oscillation(check_window, check_sv_val, during_sv_change=True) or \
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
                        
                        # 检查是否跨越了SV段边界（SV明显变化）
                        window_sv = sv_array[j:j+window] if j+window <= len(sv_array) else sv_array[j:]
                        if len(window_sv) > 0:
                            window_sv_val = np.median(window_sv)
                            # 如果SV与段起始的设定值差异较大，说明跨越了SV段边界
                            if abs(window_sv_val - seg_setpoint) > 1.0:
                                # 检查该窗口在其自己的设定值下是否稳态
                                if self.is_steady_state(next_window, window_sv_val):
                                    end_idx = j
                                    if end_idx - start_idx >= min_segment_len:
                                        non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                                    i = j
                                    break
                        
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
            # 检查PV和SV是否处于同一水平线
            seg_pv_check = pv_data[seg_start:seg_end]
            seg_sv_check = sv_array[seg_start:min(seg_end, len(sv_array))]
            if len(seg_pv_check) > 0 and len(seg_sv_check) > 0:
                pv_mean = np.mean(seg_pv_check)
                sv_mean = np.mean(seg_sv_check)
                pv_sv_deviation = abs(pv_mean - sv_mean)
                
                # 计算相对偏差和绝对偏差阈值
                sv_range = max(abs(sv_mean), 1.0)  # 避免除零
                relative_deviation = pv_sv_deviation / sv_range
                
                # 如果PV和SV偏差过大（相对偏差>50%或绝对偏差>30），跳过该段
                # 这种情况通常表示系统未收敛到设定值附近
                if relative_deviation > 0.5 and pv_sv_deviation > 30:
                    continue
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
                    # 与SV变化区间重叠时，使用更高阈值
                    if self._check_large_oscillation(seg_pv, seg_setpoint, during_sv_change=True) or self._check_large_deviation(seg_pv, new_sv):
                        filtered_segments.append((seg_start, seg_end, seg_setpoint))
                        continue
            
            is_response_to_sv_change = False
            for change_start, change_end in sv_change_intervals:
                if change_end <= seg_start <= change_end + 50:
                    if change_end < len(sv_array):
                        new_sv = np.median(sv_array[change_end:min(change_end+20, len(sv_array))])
                        if seg_start < len(pv_data) and seg_end <= len(pv_data):
                            seg_pv = pv_data[seg_start:seg_end]
                            # SV变化后的响应检查，使用更高阈值
                            if self._check_large_oscillation(seg_pv, new_sv, during_sv_change=True):
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
            print(f"[DEBUG] filtered_segments is EMPTY. Initial non_steady_segments count: {len(non_steady_segments)}")
            return []
        
        # 合并相邻段
        filtered_segments.sort(key=lambda x: x[0])
        merged_segments = [filtered_segments[0]]
        
        # 调试：打印过滤后的段（正常运行时注释掉）
        print(f"[DEBUG] filtered_segments: {len(filtered_segments)} 段")
        for idx, (s, e, sp) in enumerate(filtered_segments):
             print(f"  段{idx+1}: [{s}, {e}], setpoint={sp:.2f}")
        
        # 合并阈值设置
        MERGE_GAP_DIRECT = 300       # 直接合并的间隔阈值（约5分钟，采样1Hz时）
        MERGE_GAP_CHECK = 600        # 需要检查才合并的间隔阈值（约10分钟）
        MERGE_GAP_MAX = 1200         # 最大合并间隔（约20分钟）
        
        for i in range(1, len(filtered_segments)):
            last_start, last_end, last_sp = merged_segments[-1]
            cur_start, cur_end, cur_sp = filtered_segments[i]
            gap_length = cur_start - last_end
            sp_diff = abs(cur_sp - last_sp)
            
            # 调试：打印合并决策（正常运行时注释掉）
            # print(f"[DEBUG] 检查合并: [{last_start},{last_end}](sp={last_sp:.1f}) vs [{cur_start},{cur_end}](sp={cur_sp:.1f})")
            # print(f"        gap={gap_length}, sp_diff={sp_diff:.2f}")
            
            if cur_start <= last_end:
                # 完全相邻或重叠的段，直接合并
                merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
            elif gap_length <= MERGE_GAP_DIRECT:
                # 较短间隔（≤5分钟）直接合并，不做额外检查
                merged_segments[-1] = (last_start, cur_end, last_sp)
            elif gap_length <= MERGE_GAP_CHECK:
                # 中等间隔（5-10分钟），检查间隔区域是否有明显稳态
                gap_pv = pv_data[last_end:cur_start]
                gap_sv_val = np.median(sv_array[last_end:cur_start]) if last_end < len(sv_array) else last_sp
                
                # 简化稳态判断：只有间隔区域足够长且非常稳定才不合并
                is_gap_clearly_steady = False
                if len(gap_pv) >= 60:  # 至少1分钟的数据
                    pv_std = np.std(gap_pv)
                    pv_range = np.ptp(gap_pv)
                    # 非常稳定：标准差小且范围小
                    if pv_std < 0.5 and pv_range < 2.0:
                        is_gap_clearly_steady = True
                
                if is_gap_clearly_steady and sp_diff < 0.5:
                    # 间隔区域非常稳定且SV相同，不合并
                    merged_segments.append((cur_start, cur_end, cur_sp))
                else:
                    merged_segments[-1] = (last_start, cur_end, last_sp)
            elif gap_length <= MERGE_GAP_MAX:
                # 较长间隔（10-20分钟），更严格检查
                gap_start = last_end
                gap_end = cur_start
                gap_pv = pv_data[gap_start:gap_end]
                gap_sv = sv_array[gap_start:gap_end] if gap_start < len(sv_array) and gap_end <= len(sv_array) else None
                
                # 检查间隔区域是否有明显的稳态特征
                is_gap_stable = False
                if len(gap_pv) >= 120:  # 至少2分钟
                    pv_std = np.std(gap_pv)
                    pv_range = np.ptp(gap_pv)
                    # SV是否稳定
                    sv_stable = gap_sv is None or np.ptp(gap_sv) < 1.0
                    # 非常稳定：标准差小、范围小、SV稳定
                    if pv_std < 1.0 and pv_range < 3.0 and sv_stable:
                        is_gap_stable = True
                
                if is_gap_stable:
                    merged_segments.append((cur_start, cur_end, cur_sp))
                else:
                    merged_segments[-1] = (last_start, cur_end, last_sp)
            else:
                # 超长间隔（>20分钟），不合并
                merged_segments.append((cur_start, cur_end, cur_sp))
        
        # 后处理：分割过长的非稳态段（内部可能包含平稳区域）
        final_segments = self._split_long_segments(merged_segments, pv_data, sv_array, min_segment_len)
        
        # 过滤相对点位数过少的扰动段
        # 如果扰动段点位数相对于总数据长度过少，则过滤掉
        if len(final_segments) > 1:
            # 计算所有段的长度
            seg_lengths = [(seg_end - seg_start, idx) for idx, (seg_start, seg_end, _) in enumerate(final_segments)]
            max_seg_length = max(length for length, _ in seg_lengths)
            
            # 相对过滤：段长度 < 最长段的5% 且 < 总数据长度的1%，则过滤
            min_relative_to_max = max_seg_length * 0.05  # 最长段的5%
            min_relative_to_total = n * 0.01  # 总数据的1%
            min_absolute = 50  # 绝对最小值
            
            # 取这三个阈值中的最大值作为过滤阈值
            min_length_threshold = max(min_relative_to_max, min_relative_to_total, min_absolute)
            
            filtered_final = []
            for seg_start, seg_end, seg_sp in final_segments:
                seg_len = seg_end - seg_start
                if seg_len >= min_length_threshold:
                    filtered_final.append((seg_start, seg_end, seg_sp))
            
            final_segments = filtered_final
        
        print(f"[DEBUG] Final segments count: {len(final_segments)}, before filtering it was {len(merged_segments)}")
        return final_segments
    
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
    
    # ============================================================
    # 段分割与合并方法
    # ============================================================
    
    def _split_long_segments(self, segments, pv_data, sv_array, min_segment_len=30):
        """
        分割过长的非稳态段
        
        对于较长的非稳态段（>30分钟），检查其内部是否存在连续的平稳区域，
        如果存在则将其分割为多个独立的扰动段。
        
        分割阈值:
        - MIN_SPLIT_LENGTH = 1800: 段长度超过1800点才考虑分割
        - MIN_STEADY_LENGTH = 600: 平稳区域至少600点才作为分割点
        - SCAN_WINDOW = 120: 扫描窗口大小
        
        Args:
            segments: 非稳态段列表 [(start, end, setpoint), ...]
            pv_data: PV数据
            sv_array: SV数据
            min_segment_len: 最小段长度
        
        Returns:
            分割后的段列表
        """
        if not segments:
            return segments
        
        result = []
        
        # 阈值配置
        MIN_SPLIT_LENGTH = 1800  # 段长度超过1800点（约30分钟@1s采样）才考虑分割
        MIN_STEADY_LENGTH = 600  # 平稳区域至少600点（约10分钟）才作为分割点
        SCAN_WINDOW = 120        # 扫描窗口大小（约2分钟）
        
        for seg_start, seg_end, seg_setpoint in segments:
            seg_len = seg_end - seg_start
            
            # 短段不分割
            if seg_len < MIN_SPLIT_LENGTH:
                result.append((seg_start, seg_end, seg_setpoint))
                continue
            
            # 扫描段内的平稳区域
            steady_regions = []
            i = seg_start + min_segment_len  # 跳过开头
            
            while i < seg_end - min_segment_len - SCAN_WINDOW:
                window_pv = pv_data[i:i + SCAN_WINDOW]
                window_sv = sv_array[i:i + SCAN_WINDOW] if i + SCAN_WINDOW <= len(sv_array) else None
                
                if window_sv is not None and len(window_sv) > 0:
                    window_setpoint = np.median(window_sv)
                else:
                    window_setpoint = seg_setpoint
                
                # 检查该窗口是否为稳态
                if self._is_window_truly_steady(window_pv, window_setpoint):
                    # 找到平稳区域，向前后扩展
                    steady_start = i
                    steady_end = i + SCAN_WINDOW
                    
                    # 向后扩展
                    j = steady_end
                    while j < seg_end - min_segment_len:
                        ext_window = pv_data[j:min(j + SCAN_WINDOW // 2, seg_end)]
                        ext_sv = sv_array[j:min(j + SCAN_WINDOW // 2, len(sv_array))] if j < len(sv_array) else None
                        ext_setpoint = np.median(ext_sv) if ext_sv is not None and len(ext_sv) > 0 else window_setpoint
                        
                        if self._is_window_truly_steady(ext_window, ext_setpoint):
                            steady_end = min(j + SCAN_WINDOW // 2, seg_end)
                            j += SCAN_WINDOW // 2
                        else:
                            break
                    
                    # 向前扩展
                    k = steady_start - SCAN_WINDOW // 2
                    while k > seg_start + min_segment_len:
                        ext_window = pv_data[k:steady_start]
                        ext_sv = sv_array[k:steady_start] if k >= 0 and steady_start <= len(sv_array) else None
                        ext_setpoint = np.median(ext_sv) if ext_sv is not None and len(ext_sv) > 0 else window_setpoint
                        
                        if self._is_window_truly_steady(ext_window, ext_setpoint):
                            steady_start = k
                            k -= SCAN_WINDOW // 2
                        else:
                            break
                    
                    # 记录平稳区域（如果足够长）
                    steady_len = steady_end - steady_start
                    if steady_len >= MIN_STEADY_LENGTH:
                        steady_regions.append((steady_start, steady_end))
                    
                    # 跳过已检查的区域
                    i = steady_end
                else:
                    i += SCAN_WINDOW // 2
            
            # 根据平稳区域分割段
            if not steady_regions:
                result.append((seg_start, seg_end, seg_setpoint))
            else:
                # 按平稳区域分割
                split_points = []
                for steady_start, steady_end in steady_regions:
                    # 使用平稳区域的中点作为分割点
                    split_point = (steady_start + steady_end) // 2
                    split_points.append((split_point, steady_start, steady_end))
                
                # 生成分割后的段
                prev_end = seg_start
                for split_point, steady_start, steady_end in sorted(split_points):
                    # 前半段（到平稳区域开始）
                    if steady_start - prev_end >= min_segment_len:
                        sub_sv = sv_array[prev_end:steady_start] if prev_end < len(sv_array) else None
                        sub_setpoint = np.median(sub_sv) if sub_sv is not None and len(sub_sv) > 0 else seg_setpoint
                        result.append((prev_end, steady_start, sub_setpoint))
                    prev_end = steady_end
                
                # 最后一段（从最后一个平稳区域结束到段结束）
                if seg_end - prev_end >= min_segment_len:
                    sub_sv = sv_array[prev_end:seg_end] if prev_end < len(sv_array) else None
                    sub_setpoint = np.median(sub_sv) if sub_sv is not None and len(sub_sv) > 0 else seg_setpoint
                    result.append((prev_end, seg_end, sub_setpoint))
        
        return result
    
    def _is_window_truly_steady(self, window_pv, setpoint):
        """
        检查窗口是否真正稳态（用于分割长段时的判断）
        使用比常规稳态检查更严格的标准
        """
        if len(window_pv) < 10:
            return False
        
        pv_std = np.std(window_pv)
        pv_range = np.max(window_pv) - np.min(window_pv)
        pv_mean = np.mean(window_pv)
        
        # 检查是否接近设定值
        mean_error = abs(pv_mean - setpoint)
        
        # 严格的稳态标准
        if setpoint > 0:
            # 相对阈值（截断保护，防止大设定值下阈值过高）
            std_max = min(max(setpoint * 0.08, 0.3), 1.5)
            range_max = min(max(setpoint * 0.15, 0.8), 3.0)
            error_max = min(max(setpoint * 0.1, 0.5), 2.0)
            
            std_ok = pv_std < std_max
            range_ok = pv_range < range_max
            error_ok = mean_error < error_max
        else:
            # 绝对阈值
            std_ok = pv_std < 0.3
            range_ok = pv_range < 0.8
            error_ok = mean_error < 0.5
        
        # 检查无明显趋势
        has_no_trend = True
        if len(window_pv) > 10:
            try:
                coeffs = np.polyfit(np.arange(len(window_pv)), window_pv, 1)
                if abs(coeffs[0]) > 0.03:  # 斜率阈值
                    has_no_trend = False
            except:
                pass
        
        return std_ok and range_ok and error_ok and has_no_trend
    
    # ============================================================
    # 扰动起始点检测方法
    # ============================================================
    
    def detect_all_disturbances(self, pv_data, sv_array, non_steady_segments=None):
        """
        检测所有扰动（非稳态）的起始点
        
        Args:
            pv_data: PV数据数组
            sv_array: SV数据数组
            non_steady_segments: 已检测的非稳态段列表（可选）
        
        Returns:
            list: 扰动起始点列表 [(start_idx, setpoint), ...]
        """
        n = len(pv_data)
        if n < 50:
            return []
        
        disturbance_starts = []
        sv_change_intervals = self.detect_sv_change_intervals(sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=pv_data)
        
        if non_steady_segments is not None and len(non_steady_segments) > 0:
            # 每个非稳态段都生成一个扰动起始点
            for seg_start, seg_end, seg_setpoint in non_steady_segments:
                # 直接使用非稳态段的起始点作为扰动起始点
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


# ============================================================
# 模块级便捷函数
# ============================================================

def find_high_variability_periods(history_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    从历史数据中查找高波动（非稳态）时间段
    
    这是一个便捷函数，封装了StabilityDetector的主要功能，
    接受标准格式的历史数据并返回检测到的扰动窗口。
    
    内部采用三级优选机制：
        Level 1: 整定段 (MV阶跃 → PV响应) → 最高精度
        Level 2: 振荡段 (PV持续振荡)       → 次优精度
        Level 3: 扰动段 (泛泛的非稳态)      → 兜底
    
    Args:
        history_data: 历史数据字典，格式为:
            {
                "history_data": [
                    {"timestamp": ..., "pv": ..., "sv": ..., "mv": ...},
                    ...
                ]
            }
    
    Returns:
        dict: {
            "start_time": 数据起始时间戳,
            "end_time": 数据结束时间戳,
            "qualified_windows": [
                {"start_time": ..., "end_time": ...},
                ...
            ]
        }
    """
    try:
        # 解析输入数据
        data_list = history_data.get("history_data", [])
        if not data_list:
            return {
                "start_time": None,
                "end_time": None,
                "qualified_windows": []
            }
        
        # 提取timestamp, pv, sv, mv数据
        timestamps = []
        pv_values = []
        sv_values = []
        mv_values = []
        has_mv = False
        
        for item in data_list:
            ts = item.get("timestamp")
            pv = item.get("pv")
            sv = item.get("sv")
            mv = item.get("mv")
            
            if ts is not None and pv is not None:
                timestamps.append(ts)
                pv_values.append(float(pv))
                sv_values.append(float(sv) if sv is not None else None)
                mv_values.append(float(mv) if mv is not None else None)
                if mv is not None:
                    has_mv = True
        
        if len(timestamps) < 10:
            return {
                "start_time": timestamps[0] if timestamps else None,
                "end_time": timestamps[-1] if timestamps else None,
                "qualified_windows": []
            }
        
        # 转换为numpy数组
        pv_data = np.array(pv_values, dtype=float)
        
        # 处理sv数据
        if all(sv is not None for sv in sv_values):
            sv_data = np.array(sv_values, dtype=float)
        else:
            sv_data = np.full(len(pv_data), np.mean(pv_data))
        
        # 处理mv数据
        if has_mv and all(mv is not None for mv in mv_values):
            mv_data = np.array(mv_values, dtype=float)
        else:
            mv_data = None
        
        # 获取起止时间（毫秒时间戳）
        start_time = int(timestamps[0])
        end_time = int(timestamps[-1])
        
        # =============================================
        # 三级优选调度（瀑布式 + 质量门槛 + 亚合格回捞）
        # Level 1 质量达标 → 直接返回
        # Level 1 质量亚合格 [0.45, 0.55) → 暂存，等 Level 2
        # Level 2 命中 → 返回 Level 2
        # Level 2 也未命中 → 优先用 Level 1 亚合格段（而非 Level 3 兜底）
        # 全部未命中 → Level 3 兜底
        # =============================================
        
        QUALITY_GATE = 0.55       # Level 1/2 需要最高质量 >= 此值才算有效命中
        SUB_QUALITY_GATE = 0.45   # [NEW] 亚合格门槛：有真实 MV 阶跃但信噪比偏弱
        level1_sub_qualified = None  # 暂存 Level 1 亚合格段

        # Level 1: 整定段检测（MV阶跃 → PV响应）
        if mv_data is not None:
            try:
                from .tuning_segment_detector import TuningSegmentDetector
                tuning_detector = TuningSegmentDetector()
                tuning_segments = tuning_detector.detect(pv_data, sv_data, mv_data)
                
                if tuning_segments:
                    max_q = max(s[3] for s in tuning_segments)
                    if max_q >= QUALITY_GATE:
                        print(f"[SegmentSelector] 🥇 Level 1 命中: {len(tuning_segments)} 个整定段 "
                              f"(最高质量={max_q:.2f})")
                        qualified_windows = _segments_to_windows(tuning_segments, timestamps)
                        return {
                            "start_time": start_time,
                            "end_time": end_time,
                            "qualified_windows": qualified_windows
                        }
                    elif max_q >= SUB_QUALITY_GATE:
                        # [NEW] 亚合格：有真实的 MV 阶跃段，但质量差一点点（常见于液位等慢过程）
                        # 先暂存，如果 Level 2 也没有更好的结果，就用这些段（远比 Level 3 全量兜底好）
                        print(f"[SegmentSelector] Level 1 亚合格 (maxQ={max_q:.2f}, 门槛={QUALITY_GATE})，"
                              f"暂存 {len(tuning_segments)} 个段，继续尝试 Level 2...")
                        level1_sub_qualified = tuning_segments
                    else:
                        print(f"[SegmentSelector] Level 1 质量不达标 (maxQ={max_q:.2f}<{SUB_QUALITY_GATE})，降级...")
                else:
                    print("[SegmentSelector] Level 1 未命中，降级到 Level 2...")
            except Exception as e:
                print(f"[SegmentSelector] Level 1 异常({e})，降级...")
        else:
            print("[SegmentSelector] 无 MV 数据，跳过 Level 1")
        
        # Level 2: 振荡段检测（PV围绕SV持续振荡）
        try:
            from .oscillation_segment_detector import OscillationSegmentDetector
            osc_detector = OscillationSegmentDetector()
            # [NEW] 让 Level 2 也做时间尺度自适应（与 Level 1 一致）
            osc_detector.adapt_to_timescale(pv_data)
            osc_segments = osc_detector.detect(pv_data, sv_data)
            
            if osc_segments:
                max_q = max(s[3] for s in osc_segments)
                if max_q >= QUALITY_GATE:
                    print(f"[SegmentSelector] 🥈 Level 2 命中: {len(osc_segments)} 个振荡段 "
                          f"(最高质量={max_q:.2f})")
                    qualified_windows = _segments_to_windows(osc_segments, timestamps)
                    return {
                        "start_time": start_time,
                        "end_time": end_time,
                        "qualified_windows": qualified_windows
                    }
                else:
                    print(f"[SegmentSelector] Level 2 质量不达标 (maxQ={max_q:.2f}<{QUALITY_GATE})，降级...")
            else:
                print("[SegmentSelector] Level 2 未命中，降级到 Level 3...")
        except Exception as e:
            print(f"[SegmentSelector] Level 2 异常({e})，降级...")
        
        # [NEW] Level 1.5: 如果 Level 1 有亚合格段，优先使用（远优于 Level 3 全量兜底）
        if level1_sub_qualified:
            max_q = max(s[3] for s in level1_sub_qualified)
            print(f"[SegmentSelector] 🥇↩ Level 1 亚合格段回捞: {len(level1_sub_qualified)} 个整定段 "
                  f"(最高质量={max_q:.2f}，优于 Level 3 全量兜底)")
            qualified_windows = _segments_to_windows(level1_sub_qualified, timestamps)
            return {
                "start_time": start_time,
                "end_time": end_time,
                "qualified_windows": qualified_windows
            }
        
        # Level 3: 扰动段检测（兜底）
        print("[SegmentSelector] 🥉 Level 3: 扰动段检测（兜底）...")
        detector = StabilityDetector()
        non_steady_segments = detector.detect_non_steady_segments(pv_data, sv_data)
        
        qualified_windows = []
        for seg_start, seg_end, seg_setpoint in non_steady_segments:
            if seg_start < len(timestamps) and seg_end > 0:
                seg_start_time = int(timestamps[seg_start])
                seg_end_idx = min(seg_end - 1, len(timestamps) - 1)
                seg_end_time = int(timestamps[seg_end_idx])
                qualified_windows.append({
                    "start_time": seg_start_time,
                    "end_time": seg_end_time
                })
        
        return {
            "start_time": start_time,
            "end_time": end_time,
            "qualified_windows": qualified_windows
        }
    
    except Exception as e:
        import traceback
        print(f"[ERROR] find_high_variability_periods 崩溃: {e}")
        traceback.print_exc()
        return {
            "start_time": None,
            "end_time": None,
            "qualified_windows": []
        }


def _segments_to_windows(segments: List[Tuple], timestamps: List) -> List[Dict]:
    """
    将 (start_idx, end_idx, setpoint, quality_score) 格式的段列表
    转换为 {"start_time": ..., "end_time": ...} 格式的窗口列表
    """
    windows = []
    for seg in segments:
        seg_start, seg_end = seg[0], seg[1]
        if seg_start < len(timestamps) and seg_end > 0:
            seg_start_time = int(timestamps[seg_start])
            seg_end_idx = min(seg_end - 1, len(timestamps) - 1)
            seg_end_time = int(timestamps[seg_end_idx])
            windows.append({
                "start_time": seg_start_time,
                "end_time": seg_end_time
            })
    return windows


def merge_adjacent_periods(
    periods: List[Dict[str, Any]],
    max_gap: int = 100
) -> List[Dict[str, Any]]:
    """
    合并相邻的高波动时间段
    
    当两个高波动时间段之间的间隔小于max_gap时，将它们合并为一个。

    Args:
        periods: 高波动时间段列表，每个元素包含:
            - start_time: 起始时间
            - end_time: 结束时间
            - start_idx: 起始索引
            - end_idx: 结束索引
            - setpoint: 设定值
            - variance/std/mean/range: 统计指标
        max_gap: 最大允许的间隔（索引点数），默认100

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
