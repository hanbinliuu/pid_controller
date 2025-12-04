"""
稳定性检测器
优化后的非稳态（扰动）检测算法
"""

import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))


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
        """
        计算数据的方向改变次数
        
        Args:
            data: 数据数组
            
        Returns:
            int: 方向改变次数
        """
        if len(data) < 2:
            return 0
        diff = np.diff(data)
        if len(diff) < 2:
            return 0
        return np.sum(np.diff(np.sign(diff)) != 0)
    
    def _check_large_oscillation(self, pv_data, setpoint, include_sign_changes=True, strict=False):
        """
        检查是否存在大幅振荡
        
        Args:
            pv_data: 过程值数据
            setpoint: 设定值
            include_sign_changes: 是否包含波动次数检测
            strict: 是否使用更严格的阈值（用于收敛过程判断）
            
        Returns:
            bool: 如果存在大幅振荡返回True
        """
        if len(pv_data) < 10:
            return False
        
        pv_range = np.max(pv_data) - np.min(pv_data)
        pv_std = np.std(pv_data)
        
        # 根据strict参数选择阈值
        if strict:
            # 严格模式：更高的阈值
            range_ratio, std_ratio = 0.7, 0.4
            abs_range, abs_std = 7.0, 3.5
            sign_ratio, sign_std_ratio = 0.2, 0.25
        else:
            # 普通模式：包含绝对阈值检测
            if pv_range > 15.0 or pv_std > 8.0:
                return True
            range_ratio, std_ratio = 0.4, 0.25
            abs_range, abs_std = 4.0, 2.0
            sign_ratio = 0.1 if len(pv_data) > 100 else 0.15
            sign_std_ratio = 0.15
        
        # 相对阈值检测
        if setpoint > 0:
            if pv_range > max(setpoint * range_ratio, abs_range) or pv_std > max(setpoint * std_ratio, abs_std):
                return True
        else:
            if pv_range > abs_range or pv_std > abs_std:
                return True
        
        # 波动次数检测
        if include_sign_changes and len(pv_data) >= 20:
            sign_changes = self._calculate_sign_changes(pv_data)
            std_threshold = max(setpoint * sign_std_ratio, 1.5 if not strict else 2.5) if setpoint > 0 else (1.5 if not strict else 2.5)
            
            if sign_changes > len(pv_data) * sign_ratio and pv_std > std_threshold:
                return True
        
        return False
    
    def _is_window_unstable(self, pv_window, setpoint):
        """
        检查窗口数据是否不稳定
        
        Args:
            pv_window: 窗口数据
            setpoint: 设定值
            
        Returns:
            bool: 如果不稳定返回True
        """
        pv_range = np.max(pv_window) - np.min(pv_window)
        pv_std = np.std(pv_window)
        
        if setpoint > 0:
            return pv_range > max(setpoint * 0.2, 2.0) or pv_std > max(setpoint * 0.12, 1.0)
        else:
            return pv_range > 2.0 or pv_std > 1.0
    
    def _backtrack_to_true_start(self, pv_data, detected_idx, seg_start, setpoint, max_lookback=80):
        """
        从检测到的起始点向前回溯，找到真正的起始位置
        
        Args:
            pv_data: 过程值数据
            detected_idx: 检测到的起始索引
            seg_start: 段起始位置（回溯不能超过此位置）
            setpoint: 设定值
            max_lookback: 最大回溯点数
            
        Returns:
            int: 回溯后的起始索引
        """
        if detected_idx <= seg_start:
            return detected_idx
        
        start_idx = detected_idx
        lookback_range = min(max_lookback, detected_idx - seg_start)
        
        # 单点检查回溯
        for i in range(detected_idx - 1, max(seg_start, detected_idx - lookback_range), -1):
            deviation_threshold = max(setpoint * 0.12, 0.6) if setpoint > 0 else 0.6
            if abs(pv_data[i] - setpoint) > deviation_threshold:
                start_idx = i
            else:
                break
        
        return start_idx
    
    def _find_oscillation_start(self, pv_data, start_idx, end_idx, setpoint, window_size=30, step_size=5):
        """
        查找大幅振荡开始的位置
        
        Args:
            pv_data: 过程值数据
            start_idx: 搜索起始索引
            end_idx: 搜索结束索引
            setpoint: 设定值
            window_size: 窗口大小
            step_size: 步长
            
        Returns:
            int or None: 振荡开始位置，如果未找到返回None
        """
        detected_start = None
        
        # 第一阶段：使用标准窗口找到大致位置
        for check_start in range(start_idx, end_idx - window_size, step_size):
            window_pv = pv_data[check_start:check_start + window_size]
            if len(window_pv) < window_size:
                break
            
            if self._check_large_oscillation(window_pv, setpoint):
                detected_start = check_start
                break
        
        # 第二阶段：如果找到了，向前回溯找到更精确的起始位置
        if detected_start is not None and detected_start > start_idx:
            # 计算前段的基准统计量
            lookback_start = max(start_idx, detected_start - 50)
            if lookback_start < detected_start:
                baseline_pv = pv_data[lookback_start:detected_start]
                if len(baseline_pv) > 10:
                    baseline_mean = np.mean(baseline_pv)
                    baseline_std = np.std(baseline_pv)
                    
                    # 向前回溯，找到偏离基准的起始点
                    for i in range(detected_start - 1, lookback_start, -1):
                        # 检查是否仍然偏离基准
                        if abs(pv_data[i] - baseline_mean) > baseline_std * 2.5:
                            detected_start = i
                        else:
                            # 找到了稳定点，停止回溯
                            break
        
        return detected_start
    
    def _check_rapid_change(self, pv_data, threshold=0.05):
        """
        检查是否存在快速变化
        
        Args:
            pv_data: 过程值数据
            threshold: 斜率阈值
            
        Returns:
            bool: 如果存在快速变化返回True
        """
        if len(pv_data) < 10:
            return False
        
        # 方法1: 检查斜率
        try:
            x = np.arange(len(pv_data))
            coeffs = np.polyfit(x, pv_data, 1)
            slope = abs(coeffs[0])
            if slope > threshold:
                return True
        except:
            pass
        
        # 方法2: 检查首尾变化幅度
        window_change = abs(pv_data[-1] - pv_data[0])
        if window_change > 2.0:
            return True
        
        return False
    
    def _check_large_deviation(self, pv_data, setpoint):
        """
        检查是否存在大幅偏离设定值
        
        Args:
            pv_data: 过程值数据
            setpoint: 设定值
            
        Returns:
            bool: 如果存在大幅偏离返回True
        """
        if len(pv_data) == 0:
            return False
        
        mean_error = np.mean(np.abs(pv_data - setpoint))
        
        if setpoint > 0:
            if mean_error > setpoint * 0.5:
                return True
        else:
            if mean_error > 3.0:
                return True
        
        # 检查快速变化
        if self._check_rapid_change(pv_data):
            return True
        
        return False
    
    def _check_abnormal_oscillation_during_sv_change(self, pv_data, sv_data, sv_change_magnitude):
        """
        检查SV变化期间是否有异常振荡
        
        Args:
            pv_data: 过程值数据
            sv_data: 设定值数据
            sv_change_magnitude: SV变化幅度
            
        Returns:
            bool: 如果有异常振荡返回True
        """
        pv_diff = np.diff(pv_data)
        sv_diff = np.diff(sv_data)
        
        # 统计PV和SV变化方向不一致的次数
        direction_mismatch = 0
        for i in range(min(len(pv_diff), len(sv_diff))):
            if abs(sv_diff[i]) > 0.1:
                if pv_diff[i] * sv_diff[i] < 0:
                    direction_mismatch += 1
        
        mismatch_ratio = direction_mismatch / max(1, len(sv_diff))
        
        # 检查PV波动是否超出预期
        expected_pv_range = sv_change_magnitude * 1.5
        actual_pv_range = np.max(pv_data) - np.min(pv_data)
        
        # 检查高频振荡
        sign_changes = self._calculate_sign_changes(pv_data)
        high_freq_oscillation = sign_changes > len(pv_data) * 0.3
        
        # 满足多个异常条件才认为是扰动
        return (
            mismatch_ratio > 0.4 and
            actual_pv_range > expected_pv_range and
            high_freq_oscillation
        )
    
    def _adjust_response_buffer(self, pv_data, sv_stable_end, new_sv, dynamic_buffer, n):
        """
        根据PV的收敛和振荡情况动态调整响应缓冲期
        
        Args:
            pv_data: 过程值数据
            sv_stable_end: SV稳定结束位置
            new_sv: 新的设定值
            dynamic_buffer: 当前动态缓冲期
            n: 数据总长度
            
        Returns:
            int: 调整后的缓冲期长度
        """
        max_check_len = min(1500, n - sv_stable_end)
        check_end = min(sv_stable_end + max_check_len, len(pv_data))
        
        if check_end <= sv_stable_end + 100:
            return dynamic_buffer
        
        # 检查收敛情况
        window_size = 50
        step_size = 20
        convergence_found = False
        convergence_end = sv_stable_end
        has_large_deviation = False
        
        for check_start in range(sv_stable_end, min(sv_stable_end + 500, check_end - window_size), step_size):
            window_pv = pv_data[check_start:check_start + window_size]
            if len(window_pv) < window_size:
                break
            
            # 检查是否有大幅偏离
            if self._check_large_deviation(window_pv, new_sv):
                has_large_deviation = True
            
            # 检查误差是否在减小（收敛）
            if check_start + window_size * 2 <= check_end:
                next_window_pv = pv_data[check_start + window_size:check_start + window_size * 2]
                window_mean_error = np.mean(np.abs(window_pv - new_sv))
                next_window_mean_error = np.mean(np.abs(next_window_pv - new_sv))
                
                if next_window_mean_error < window_mean_error * 0.9:
                    convergence_found = True
                    convergence_end = check_start + window_size * 2
            
            # 检查是否出现大幅振荡
            if self._check_large_oscillation(window_pv, new_sv, include_sign_changes=False):
                break
        
        # 根据收敛情况调整缓冲期
        if convergence_found:
            if has_large_deviation:
                additional_buffer = min(100, convergence_end - sv_stable_end)
                dynamic_buffer = min(dynamic_buffer, additional_buffer)
            else:
                additional_buffer = min(300, convergence_end - sv_stable_end)
                dynamic_buffer = max(dynamic_buffer, additional_buffer)
        
        # 查找大幅振荡开始位置
        osc_window = 40
        osc_step = 10
        
        for osc_start in range(sv_stable_end, check_end - osc_window, osc_step):
            osc_pv = pv_data[osc_start:osc_start + osc_window]
            if len(osc_pv) < osc_window:
                break
            
            if self._check_large_oscillation(osc_pv, new_sv):
                # 找到振荡，限制缓冲期到振荡之前
                max_buffer = osc_start - sv_stable_end
                dynamic_buffer = min(dynamic_buffer, max_buffer)
                dynamic_buffer = max(30, dynamic_buffer)
                return dynamic_buffer
        
        # 没有找到振荡，限制最大缓冲期
        return min(dynamic_buffer, 200)
    
    def is_steady_state(self, pv_data, setpoint, for_level=False):
        """
        判断一段数据是否处于稳态
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
            for_level: 是否为液位控制（使用更宽松的判断）
            
        Returns:
            bool: True表示稳态，False表示非稳态
        """
        if len(pv_data) < self.min_len:
            return False
        
        pv_data = np.array(pv_data)
        n = len(pv_data)
        
        # 基本统计量
        mean_val = np.mean(pv_data)
        std_val = np.std(pv_data)
        mean_dev = abs(mean_val - setpoint)
        
        if for_level:
            # 液位控制：使用更宽松的判断
            if mean_dev > self.tol or std_val > self.std_tol:
                return False
            
            # 趋势检测
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
            # 标准判断：使用多指标综合判断
            # 1. 均值偏差检查
            if mean_dev > self.tol * 1.2:
                return False
            
            # 2. 标准差检查
            if std_val > self.std_tol:
                return False
            
            # 3. 百分比阈值检查：至少95%的点在容差范围内
            in_band_ratio = np.sum(np.abs(pv_data - setpoint) <= self.tol) / n
            if in_band_ratio < 0.95:
                return False
            
            # 4. 趋势检测
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
            
            # 5. 振荡幅度检测
            if n > 10:
                data_range = np.max(pv_data) - np.min(pv_data)
                if data_range > self.tol * 4:
                    return False
                if setpoint > 0 and data_range > abs(setpoint) * 0.3:
                    return False
            
            # 6. 振荡检测
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
        """
        检测指定区间内设定值是否正在变化
        
        关键：SV调整时PV的变化不属于非稳态，属于正常变化
        
        Args:
            sv_array: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            threshold: 变化阈值
            
        Returns:
            bool: 如果设定值正在变化返回True
        """
        if sv_array is None or len(sv_array) == 0:
            return False
        
        if end_idx - start_idx < 3:
            return False
        
        segment_sv = sv_array[start_idx:end_idx]
        seg_len = len(segment_sv)
        
        # 计算基础阈值
        if threshold is None:
            # 使用自适应阈值
            sv_mean = np.mean(segment_sv)
            base_threshold = max(0.5, sv_mean * 0.05)  # 至少0.5或均值的5%
        else:
            # 确保threshold是标量
            base_threshold = float(np.mean(threshold)) if hasattr(threshold, '__len__') else float(threshold)
        
        # 对于长段，使用更严格的判断标准
        # 长段通常意味着SV已经稳定，微小波动不应该被认为是"正在变化"
        # 关键：长段内即使有一些SV变化，只要大部分时间SV是稳定的，就不应该认为"正在变化"
        if seg_len > 2000:
            # 对于超过2000个点的长段，使用非常严格的阈值
            effective_threshold = base_threshold * 5.0
        elif seg_len > 1000:
            # 对于超过1000个点的长段，使用更严格的阈值
            effective_threshold = base_threshold * 2.0
        else:
            effective_threshold = base_threshold
        
        # 检查设定值的变化范围
        sv_range = np.max(segment_sv) - np.min(segment_sv)
        if sv_range > effective_threshold:
            return True
        
        # 检查设定值的标准差
        sv_std = np.std(segment_sv)
        if sv_std > effective_threshold * 0.5:
            return True
        
        # 检查是否有明显的趋势性变化
        if seg_len > 5:
            x = np.arange(seg_len)
            try:
                coeffs = np.polyfit(x, segment_sv, 1)
                slope = abs(coeffs[0])
                # 对于长段，斜率阈值应该更严格
                slope_threshold = effective_threshold / seg_len
                if slope > slope_threshold:
                    return True
            except:
                pass
        
        # 检查首尾差值
        if seg_len > 1:
            if abs(segment_sv[-1] - segment_sv[0]) > effective_threshold:
                return True
        
        return False
    
    def detect_setpoint_segments(self, sv_array, min_change=0.5, min_stable_points=20):
        """
        检测设定值变化点，将数据分段
        
        Args:
            sv_array: 设定值数组
            min_change: 设定值变化的最小阈值
            min_stable_points: 每个设定值段的最小稳定点数
            
        Returns:
            list: 设定值段列表，每个元素为 (start_idx, end_idx, setpoint_value)
        """
        if sv_array is None or len(sv_array) < min_stable_points:
            return [(0, len(sv_array), np.mean(sv_array) if len(sv_array) > 0 else 0.0)]
        
        sv_array = np.array(sv_array)
        segments = []
        n = len(sv_array)
        
        # 使用滑动窗口检测设定值变化
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
        
        # 如果没有检测到变化点，使用单点检测
        if len(change_points) == 0:
            for i in range(1, n):
                if abs(sv_array[i] - sv_array[i-1]) > min_change:
                    if i + 3 < n:
                        next_avg = np.mean(sv_array[i:min(i+3, n)])
                        if abs(next_avg - sv_array[i]) < min_change * 0.5:
                            change_points.append(i)
                            break
        
        # 构建分段列表
        if len(change_points) == 0:
            segments.append((0, n, np.mean(sv_array)))
        else:
            start_idx = 0
            for change_idx in change_points:
                if change_idx > start_idx + min_stable_points:
                    seg_sv = np.mean(sv_array[start_idx:change_idx])
                    segments.append((start_idx, change_idx, seg_sv))
                    start_idx = change_idx
            
            # 添加最后一段
            if start_idx < n:
                seg_sv = np.mean(sv_array[start_idx:n])
                segments.append((start_idx, n, seg_sv))
        
        return segments
    
    def find_disturbance_start(self, pv_data, setpoint, steady_head_len, threshold=1.0):
        """
        定位扰动起始点（非稳态开始位置）
        
        Args:
            pv_data: 过程值数据
            setpoint: 设定值
            steady_head_len: 稳态段长度（用于建立基准）
            threshold: 偏差阈值
            
        Returns:
            int: 扰动起始点索引，如果未找到返回None
        """
        n = len(pv_data)
        if n < steady_head_len + 10:
            return None
        
        # 计算稳态段的统计量作为基准
        steady_segment = pv_data[:steady_head_len]
        steady_mean = np.mean(steady_segment)
        steady_std = np.std(steady_segment)
        
        detected_start = None
        
        # 方法1：偏差突变检测（降低阈值，更敏感）
        for i in range(steady_head_len, n - 5):
            if abs(pv_data[i] - setpoint) > threshold * 0.6:  # 降低阈值到60%
                window = min(5, n - i)
                if window > 0:
                    window_data = pv_data[i:i+window]
                    if np.mean(np.abs(window_data - setpoint)) > threshold * 0.5:
                        detected_start = i
                        break
        
        # 方法2：斜率突变检测（更敏感）
        if detected_start is None and n > steady_head_len + 20:
            dy = np.diff(pv_data)
            steady_dy = dy[:steady_head_len-1] if steady_head_len > 1 else dy[:min(10, len(dy))]
            steady_slope_mean = np.mean(np.abs(steady_dy))
            steady_slope_std = np.std(np.abs(steady_dy))
            
            for i in range(steady_head_len, len(dy) - 5):
                local_slope = np.abs(dy[i])
                if local_slope > steady_slope_mean + 1.5 * steady_slope_std:  # 降低到1.5倍标准差
                    window = min(5, len(dy) - i)
                    if window > 0:
                        window_slopes = np.abs(dy[i:i+window])
                        if np.mean(window_slopes) > steady_slope_mean + 0.8 * steady_slope_std:
                            detected_start = i + 1
                            break
        
        # 方法3：二阶差分（加速度）突变检测
        if detected_start is None and n > steady_head_len + 30:
            d2y = np.diff(np.diff(pv_data))
            if len(d2y) > steady_head_len:
                steady_d2y = d2y[:steady_head_len-2] if steady_head_len > 2 else d2y[:min(10, len(d2y))]
                steady_acc_mean = np.mean(np.abs(steady_d2y))
                steady_acc_std = np.std(np.abs(steady_d2y))
                
                for i in range(steady_head_len - 2, len(d2y) - 5):
                    local_acc = np.abs(d2y[i])
                    if local_acc > steady_acc_mean + 2.5 * steady_acc_std:  # 降低到2.5倍
                        window = min(5, len(d2y) - i)
                        if window > 0:
                            window_acc = np.abs(d2y[i:i+window])
                            if np.mean(window_acc) > steady_acc_mean + 1.5 * steady_acc_std:
                                detected_start = i + 2
                                break
        
        # 如果检测到起始点，向前回溯找到真正的起始位置
        if detected_start is not None and detected_start > steady_head_len:
            # 向前回溯最多20个点
            lookback = min(20, detected_start - steady_head_len)
            for i in range(detected_start - 1, detected_start - lookback - 1, -1):
                # 检查是否仍然偏离稳态
                if abs(pv_data[i] - steady_mean) > steady_std * 2:
                    detected_start = i
                else:
                    break
        
        return detected_start
    
    def detect_sv_change_intervals(self, sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=None):
        """
        检测SV变化的所有区间（包括变化后的响应缓冲期）
        
        Args:
            sv_array: 设定值数组
            threshold: 变化阈值
            min_stable_points: 稳定点的最小数量
            response_buffer: SV变化后的响应缓冲期长度（数据点数），用于排除响应过程
            pv_data: 过程值数据（可选），如果提供，会根据PV的收敛情况动态调整响应缓冲期
            
        Returns:
            list: SV变化区间列表，每个元素为 (start_idx, end_idx)，包含响应缓冲期
        """
        if sv_array is None or len(sv_array) < min_stable_points * 2:
            return []
        
        change_intervals = []
        n = len(sv_array)
        
        # 使用滑动窗口检测SV变化
        window_size = min(10, n // 20)
        window_size = max(3, window_size)
        
        i = 0
        while i < n - window_size:
            # 检查当前窗口内SV是否在变化
            window_sv = sv_array[i:i+window_size]
            is_changing = self.is_setpoint_changing(window_sv, 0, len(window_sv), threshold=threshold)
            
            if is_changing:
                # 找到SV变化段的开始
                change_start = i
                # 记录变化前的SV值
                prev_sv = np.median(sv_array[max(0, i-window_size):i]) if i > 0 else sv_array[i]
                
                # 继续查找变化段的结束
                j = i + window_size
                while j < n - window_size:
                    next_window_sv = sv_array[j:j+window_size]
                    is_still_changing = self.is_setpoint_changing(next_window_sv, 0, len(next_window_sv), threshold=threshold)
                    
                    if not is_still_changing:
                        # 找到稳定点，但需要确认后续几个窗口也稳定
                        stable_count = 0
                        for k in range(j, min(j + window_size * 3, n - window_size), window_size):
                            check_window = sv_array[k:k+window_size]
                            if not self.is_setpoint_changing(check_window, 0, len(check_window), threshold=threshold):
                                stable_count += 1
                            else:
                                break
                        
                        if stable_count >= 2:
                            # SV变化段结束，记录新的SV值
                            new_sv = np.median(next_window_sv)
                            sv_change_magnitude = abs(new_sv - prev_sv)
                            
                            # SV变化段结束位置
                            sv_stable_end = j
                            
                            # 计算响应缓冲期：根据SV变化幅度动态调整
                            # 变化幅度越大，响应时间可能越长
                            dynamic_buffer = min(response_buffer, int(response_buffer * (1 + sv_change_magnitude / 5.0)))
                            dynamic_buffer = max(30, dynamic_buffer)  # 至少30个点
                            dynamic_buffer = min(dynamic_buffer, 250)  # 最多250个点，避免过长
                            
                            # 如果提供了PV数据，根据PV的收敛情况和振荡情况动态调整响应缓冲期
                            if pv_data is not None and sv_stable_end < len(pv_data):
                                dynamic_buffer = self._adjust_response_buffer(
                                    pv_data, sv_stable_end, new_sv, dynamic_buffer, n
                                )
                            
                            # 扩展区间到响应缓冲期结束
                            change_end = min(sv_stable_end + dynamic_buffer, n)
                            
                            if change_end - change_start >= min_stable_points:
                                change_intervals.append((change_start, change_end))
                            i = change_end
                            break
                    j += window_size // 2
                else:
                    # 到达数据末尾，变化段一直持续到末尾
                    change_end = n
                    if change_end - change_start >= min_stable_points:
                        change_intervals.append((change_start, change_end))
                    break
            else:
                i += window_size // 2
        
        return change_intervals
    
    def is_in_sv_change_interval(self, idx, sv_change_intervals):
        """
        检查索引是否在SV变化区间内
        
        Args:
            idx: 索引
            sv_change_intervals: SV变化区间列表
            
        Returns:
            bool: 如果在SV变化区间内返回True
        """
        for change_start, change_end in sv_change_intervals:
            if change_start <= idx < change_end:
                return True
        return False
    
    def is_converging_to_setpoint(self, pv_data, sv_array, start_idx, end_idx, setpoint):
        """
        判断PV是否正在向设定值收敛（正常响应过程，不是扰动）
        
        Args:
            pv_data: 过程值数据
            sv_array: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            setpoint: 设定值
            
        Returns:
            bool: 如果正在收敛返回True
        """
        if end_idx - start_idx < 20:
            return False
        
        seg_pv = pv_data[start_idx:end_idx]
        seg_sv = sv_array[start_idx:end_idx] if start_idx < len(sv_array) else None
        
        # 获取设定值
        if seg_sv is not None and len(seg_sv) > 0:
            current_sv = np.median(seg_sv)
        else:
            current_sv = setpoint
        
        # 检查PV是否正在向设定值靠近
        # 方法1：检查误差是否在减小
        initial_error = abs(seg_pv[0] - current_sv)
        final_error = abs(seg_pv[-1] - current_sv)
        
        # 如果最终误差明显小于初始误差（至少减少30%），认为正在收敛
        if initial_error > 1.0 and final_error < initial_error * 0.7:
            # 进一步检查：中间过程是否持续向设定值靠近
            # 将段分成3部分，检查每部分的平均误差
            seg_len = len(seg_pv)
            part1 = seg_pv[:seg_len//3]
            part2 = seg_pv[seg_len//3:2*seg_len//3]
            part3 = seg_pv[2*seg_len//3:]
            
            error1 = np.mean(np.abs(part1 - current_sv))
            error2 = np.mean(np.abs(part2 - current_sv))
            error3 = np.mean(np.abs(part3 - current_sv))
            
            # 如果误差持续减小，认为是收敛过程
            # 但需要检查是否有大幅振荡，如果有大幅振荡，即使在收敛也应该识别为非稳态
            if error1 > error2 and error2 > error3:
                # 使用更严格的振荡阈值
                if not self._check_large_oscillation(seg_pv, current_sv, strict=True):
                    return True
        
        # 方法2：检查是否有明显的趋势向设定值靠近
        if len(seg_pv) > 10:
            # 计算PV与设定值的误差序列
            errors = np.abs(seg_pv - current_sv)
            # 使用线性拟合检查误差是否在减小
            x = np.arange(len(errors))
            try:
                coeffs = np.polyfit(x, errors, 1)
                slope = coeffs[0]
                # 如果斜率为负（误差在减小），且初始误差较大，认为是收敛过程
                if slope < -0.01 and initial_error > 5.0:
                    return True
            except:
                pass
        
        return False
    
    def detect_non_steady_segments(self, pv_data, sv_array, min_segment_len=20):
        """
        检测数据中的非稳态段（扰动段）
        
        关键：排除SV调整时的正常变化，只检测真正的扰动
        
        Args:
            pv_data: 过程值数据
            sv_array: 设定值数组
            min_segment_len: 最小非稳态段长度
            
        Returns:
            list: 非稳态段列表，每个元素为 (start_idx, end_idx, setpoint)
        """
        n = len(pv_data)
        if n < min_segment_len * 2:
            return []
        
        non_steady_segments = []
        
        # 首先检测所有SV变化区间（包括响应缓冲期）
        # 传入PV数据，以便根据PV的收敛情况动态调整响应缓冲期
        sv_change_intervals = self.detect_sv_change_intervals(sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=pv_data)
        
        
        
        # 在SV变化区间内检测大幅振荡（即使是在SV变化期间，大幅振荡也应该识别为扰动）
        for change_start, change_end in sv_change_intervals:
            if change_end - change_start >= min_segment_len:
                change_pv = pv_data[change_start:change_end]
                change_sv = sv_array[change_start:change_end]
                
                if len(change_pv) >= min_segment_len:
                    sv_start = change_sv[0] if len(change_sv) > 0 else 0
                    sv_end = change_sv[-1] if len(change_sv) > 0 else sv_start
                    sv_change_magnitude = abs(sv_end - sv_start)
                    current_sv = np.median(change_sv)
                    
                    # SV变化很小，直接检查振荡
                    if sv_change_magnitude < 0.5:
                        if self._check_large_oscillation(change_pv, current_sv):
                            non_steady_segments.append((change_start, change_end, current_sv))
                    else:
                        # SV有明显变化，检查是否有异常振荡
                        if self._check_abnormal_oscillation_during_sv_change(
                            change_pv, change_sv, sv_change_magnitude
                        ):
                            non_steady_segments.append((change_start, change_end, current_sv))
        
        # 检测设定值分段
        sv_segments = self.detect_setpoint_segments(sv_array, min_change=0.5, min_stable_points=20)
        
        # 对每个设定值段进行检测
        for seg_start, seg_end, seg_setpoint in sv_segments:
            if seg_end - seg_start < min_segment_len:
                continue
            
            # 检查该段是否完全在SV变化区间内
            seg_in_change = False
            change_interval_for_seg = None
            for change_start, change_end in sv_change_intervals:
                if change_start <= seg_start and seg_end <= change_end:
                    # 整个段都在SV变化区间内
                    seg_in_change = True
                    change_interval_for_seg = (change_start, change_end)
                    break
            
            if seg_in_change:
                # 整个段都在SV变化期间，需要仔细检查
                # 1. 如果响应缓冲期设置正确，前面的部分应该是正常响应，不应该标记
                # 2. 只有出现真正的大幅振荡时，才应该标记，且应该从振荡开始的位置标记
                seg_pv = pv_data[seg_start:seg_end]
                seg_sv = sv_array[seg_start:seg_end]
                
                if len(seg_pv) >= min_segment_len:
                    # 获取设定值
                    if len(seg_sv) > 0:
                        current_sv = np.median(seg_sv)
                    else:
                        current_sv = seg_setpoint
                    
                    # 查找大幅振荡开始位置
                    osc_start_idx = self._find_oscillation_start(pv_data, seg_start, seg_end, current_sv)
                    
                    if osc_start_idx is not None:
                        non_steady_segments.append((osc_start_idx, seg_end, current_sv))
                
                # 无论是否有大幅振荡，都跳过后续的常规检测
                continue
            
            # 检查该段内设定值是否在变化（更严格的检查）
            # 关键优化：对于长段，不要简单判断整个段的SV是否在变化
            # 而是应该在滑动窗口检测时局部判断
            is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
            seg_len = seg_end - seg_start
            
            # 关键改进：检查段内是否存在大幅振荡（绝对阈值）
            # 如果存在，即使SV正在变化，也应该进入常规检测
            has_large_oscillation_in_seg = False
            if is_sv_changing and seg_len < 1000:
                # 快速扫描整个段，检查是否有大幅振荡
                seg_pv_check = pv_data[seg_start:seg_end]
                if len(seg_pv_check) > 0:
                    seg_pv_range = np.max(seg_pv_check) - np.min(seg_pv_check)
                    seg_pv_std = np.std(seg_pv_check)
                    # 使用绝对阈值检查
                    if seg_pv_range > 15.0 or seg_pv_std > 8.0:
                        has_large_oscillation_in_seg = True
            
            # 对于长段（>1000个点），即使整体SV有变化，也应该进入滑动窗口检测
            # 因为长段内可能只有开头在变化，后面大部分时间SV是稳定的
            # 如果后面出现振荡，那肯定是非稳态
            # 关键改进：如果检测到大幅振荡，也进入常规检测
            if is_sv_changing and seg_len < 1000 and not has_large_oscillation_in_seg:
                # SV正在变化，这是正常的过渡过程，不属于非稳态
                # 但需要检查变化后是否最终稳态
                # 如果变化后最终稳态，整个段都不算非稳态
                # 如果变化后未稳态，则变化后的非稳态部分需要标记（但排除SV变化区间）
                tail_len = max(30, (seg_end - seg_start) // 4)
                if tail_len > 0 and seg_end - tail_len >= seg_start:
                    # 找到SV稳定后的新设定值
                    stable_sv_part = sv_array[seg_end - tail_len:seg_end]
                    stable_sv = np.median(stable_sv_part) if len(stable_sv_part) > 0 else seg_setpoint
                    
                    tail_segment = pv_data[seg_end - tail_len:seg_end]
                    is_tail_steady = self.is_steady_state(tail_segment, stable_sv)
                    if not is_tail_steady:
                        # SV变化后未稳态，需要找到真正的大幅振荡开始位置
                        # 找到SV稳定后的起始位置（排除SV变化区间）
                        stable_sv_start = None
                        for i in range(seg_end - tail_len, seg_start, -10):
                            if i < seg_start:
                                break
                            # 检查是否在SV变化区间内
                            if self.is_in_sv_change_interval(i, sv_change_intervals):
                                continue
                            sv_check = sv_array[i:seg_end] if i < len(sv_array) else []
                            if len(sv_check) > 0 and not self.is_setpoint_changing(sv_check, 0, len(sv_check), threshold=0.1):
                                stable_sv_start = i
                                break
                        
                        if stable_sv_start is not None:
                            # 查找大幅振荡开始位置
                            osc_start_idx = self._find_oscillation_start(pv_data, stable_sv_start, seg_end, stable_sv)
                            
                            if osc_start_idx is not None:
                                # 确保非稳态段的结束不在SV变化区间内
                                non_steady_end = seg_end
                                for change_start, change_end in sv_change_intervals:
                                    if change_start < non_steady_end <= change_end:
                                        non_steady_end = change_start
                                        break
                                
                                if non_steady_end > osc_start_idx and non_steady_end - osc_start_idx >= min_segment_len:
                                    non_steady_segments.append((osc_start_idx, non_steady_end, stable_sv))
                # SV变化期间的数据不算非稳态，跳过
                continue
            
            # SV未变化（或长段），检测该段内的非稳态（但要排除SV变化区间，除非有大幅振荡）
            seg_pv = pv_data[seg_start:seg_end]
            
            # 使用滑动窗口检测非稳态段
            window = min(30, (seg_end - seg_start) // 5)
            window = max(10, window)
            
            i = seg_start
            while i < seg_end - window:
                # 检查当前窗口是否在SV变化区间内
                in_sv_change = self.is_in_sv_change_interval(i, sv_change_intervals)
                
                window_data = pv_data[i:i+window]
                
                
                if in_sv_change:
                    # 在SV变化区间内，检查是否有大幅振荡或快速变化
                    window_sv = sv_array[i:i+window] if i < len(sv_array) and i+window <= len(sv_array) else None
                    current_sv = np.median(window_sv) if window_sv is not None and len(window_sv) > 0 else seg_setpoint
                    
                    # 如果没有大幅振荡或快速变化，跳过（认为是正常的SV响应）
                    if not self._check_large_oscillation(window_data, current_sv, include_sign_changes=False) and \
                       not self._check_rapid_change(window_data):
                        i += window // 3  # 减小步长，提高精度
                        continue
                
                is_steady = self.is_steady_state(window_data, seg_setpoint)
                
                
                if not is_steady:
                    # 检查是否真的出现了大幅振荡
                    if not self._check_large_oscillation(window_data, seg_setpoint):
                        i += window // 3  # 减小步长，提高精度
                        continue
                    
                    # 找到非稳态段的开始，向前回溯一段，使起点更接近PV首次偏离SV的位置
                    start_idx = i
                    
                    # 改进的回溯算法：更大的回溯范围和更敏感的判断
                    max_backtrack = min(1000, i - seg_start)  # 最多回溯1000个点或到段起始点
                    back_step = 10  # 每次回溯10个点，提高精度
                    
                    for back_offset in range(back_step, max_backtrack + back_step, back_step):
                        if start_idx - back_offset < seg_start:
                            break
                            
                        # 检查回溯位置的窗口
                        back_start = start_idx - back_offset
                        back_end = min(back_start + window, start_idx)
                        back_window = pv_data[back_start:back_end]
                        
                        if len(back_window) < window // 2:
                            break
                        
                        # 检查回溯位置是否已经不稳定
                        if self._is_window_unstable(back_window, seg_setpoint):
                            # 如果回溯位置已经不稳定，继续往前回溯
                            start_idx = back_start
                        else:
                            # 找到稳定的位置，停止回溯
                            break
                    
                    # 精细化调整：向前回溯找到真正的起始点
                    start_idx = self._backtrack_to_true_start(pv_data, start_idx, seg_start, seg_setpoint, max_lookback=80)
                    
                    # 继续查找非稳态段的结束
                    j = i + window
                    while j < seg_end - window:
                        # 检查是否进入SV变化区间
                        in_sv_change = self.is_in_sv_change_interval(j, sv_change_intervals)
                        
                        if in_sv_change:
                            # 在SV变化区间内，检查是否有大幅振荡或大幅偏离
                            check_window = pv_data[j:j+window]
                            check_sv = sv_array[j:j+window] if j < len(sv_array) else None
                            check_sv_val = np.median(check_sv) if check_sv is not None and len(check_sv) > 0 else seg_setpoint
                            
                            # 如果有大幅振荡或大幅偏离，继续检测（不结束段）
                            if self._check_large_oscillation(check_window, check_sv_val) or \
                               self._check_large_deviation(check_window, check_sv_val):
                                j += window // 2
                                continue
                            else:
                                # 没有大幅振荡或大幅偏离，遇到SV变化区间，非稳态段结束
                                end_idx = j
                                if end_idx - start_idx >= min_segment_len:
                                    non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                                # 跳过SV变化区间
                                for change_start, change_end in sv_change_intervals:
                                    if change_start <= j < change_end:
                                        i = change_end
                                        break
                                else:
                                    i = j
                                break
                        
                        next_window = pv_data[j:j+window]
                        if self.is_steady_state(next_window, seg_setpoint):
                            # 找到稳态，非稳态段结束
                            end_idx = j
                            if end_idx - start_idx >= min_segment_len:
                                non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                            i = j
                            break
                        j += window // 2
                    else:
                        # 到达段末尾，但需要排除SV变化区间
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
        
        # 最后过滤：确保所有非稳态段都不与SV变化区间重叠，且不是SV变化后的响应过程
        # 过滤掉可能是SV变化响应的非稳态段
        
        filtered_segments = []
        for seg_start, seg_end, seg_setpoint in non_steady_segments:
            # 检查段是否与SV变化区间重叠
            has_overlap = False
            overlapping_change = None
            for change_start, change_end in sv_change_intervals:
                # 检查是否有重叠
                if not (seg_end <= change_start or seg_start >= change_end):
                    has_overlap = True
                    overlapping_change = (change_start, change_end)
                    break
            
            if has_overlap:
                # 即使有重叠，也要检查是否有大幅振荡或大幅偏离
                seg_pv = pv_data[seg_start:seg_end]
                if len(seg_pv) >= min_segment_len:
                    # 获取SV变化后的新设定值
                    overlap_sv = sv_array[seg_start:min(seg_end, len(sv_array))]
                    new_sv = np.median(overlap_sv) if len(overlap_sv) > 0 else seg_setpoint
                    
                    # 如果有大幅振荡或大幅偏离，保留该段
                    if self._check_large_oscillation(seg_pv, seg_setpoint) or \
                       self._check_large_deviation(seg_pv, new_sv):
                        filtered_segments.append((seg_start, seg_end, seg_setpoint))
                        continue
            
            # 如果没有重叠，继续后续检查
            
            # 检查是否紧跟在SV变化之后（可能是响应过程）
            is_response_to_sv_change = False
            for change_start, change_end in sv_change_intervals:
                # 如果非稳态段紧跟在SV变化区间之后（在50个点内）
                if change_end <= seg_start <= change_end + 50:
                    # 获取SV变化后的新设定值
                    if change_end < len(sv_array):
                        new_sv = np.median(sv_array[change_end:min(change_end+20, len(sv_array))])
                        # 检查非稳态段内的PV数据
                        if seg_start < len(pv_data) and seg_end <= len(pv_data):
                            seg_pv = pv_data[seg_start:seg_end]
                            
                            # 如果有大幅振荡，认为是扰动，不是响应过程
                            if self._check_large_oscillation(seg_pv, new_sv):
                                is_response_to_sv_change = False
                                break
                            
                            # 检查PV是否正在向新SV收敛
                            pv_start = seg_pv[0] if len(seg_pv) > 0 else pv_data[seg_start]
                            pv_end = seg_pv[-1] if len(seg_pv) > 0 else pv_data[min(seg_end-1, len(pv_data)-1)]
                            error_start = abs(pv_start - new_sv)
                            error_end = abs(pv_end - new_sv)
                            
                            # 如果PV正在收敛，认为是响应过程
                            if error_end < error_start * 1.2:
                                is_response_to_sv_change = True
                                break
            
            if not is_response_to_sv_change:
                # 进一步检查：是否是PV向设定值收敛的正常过程（不是扰动）
                is_converging = self.is_converging_to_setpoint(pv_data, sv_array, seg_start, seg_end, seg_setpoint)
                if not is_converging:
                    filtered_segments.append((seg_start, seg_end, seg_setpoint))
        
        # 合并相邻或重叠的非稳态段（含扩展后的结果）
        if not filtered_segments:
            return []

        # 先按起点排序
        filtered_segments.sort(key=lambda x: x[0])
        merged_segments = [filtered_segments[0]]
        

        for i in range(1, len(filtered_segments)):
            last_start, last_end, last_sp = merged_segments[-1]
            cur_start, cur_end, cur_sp = filtered_segments[i]

            gap_length = cur_start - last_end
            sp_diff = abs(cur_sp - last_sp)
            
            # 如果两个段重叠，直接合并
            if cur_start <= last_end:
                if sp_diff < 0.5:
                    merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
                else:
                    merged_segments.append((cur_start, cur_end, cur_sp))
            # 如果两个段距离非常近，根据设定值差异决定是否合并
            elif gap_length < 15 or (gap_length < 100 and sp_diff < 0.5) or (gap_length <= 50 and sp_diff < 3.0) or (gap_length < 30 and sp_diff < 5.0):
                merged_segments[-1] = (last_start, cur_end, last_sp)
            # 如果两个段间隔较小，检查中间是否有明显的稳态区域
            elif gap_length < min_segment_len * 10:  # 检查范围到200个点
                gap_start = last_end
                gap_end = cur_start
                gap_sv = sv_array[gap_start:gap_end] if gap_start < len(sv_array) and gap_end <= len(sv_array) else None
                
                # 检查间隔区域是否为稳态（考虑SV变化情况）
                is_gap_steady = self._check_gap_steady_state(pv_data, sv_array, gap_start, gap_end, gap_sv, last_sp)
                
                # 检查间隔区域是否有明显的非稳态特征
                has_non_steady_features = self._has_non_steady_features(pv_data[gap_start:gap_end]) if gap_end > gap_start else False
                
                # 合并条件：间隔区域明确不稳定且有非稳态特征，且设定值差异小
                should_merge = (not is_gap_steady and has_non_steady_features and sp_diff < 15.0)
                
                if should_merge:
                    merged_segments[-1] = (min(last_start, cur_start), max(last_end, cur_end), last_sp)
                else:
                    merged_segments.append((cur_start, cur_end, cur_sp))
            else:
                merged_segments.append((cur_start, cur_end, cur_sp))
        
        return merged_segments
    
    def _check_gap_steady_state(self, pv_data, sv_array, gap_start, gap_end, gap_sv, fallback_sp):
        """
        检查间隔区域是否为稳态，特殊处理SV变化情况
        
        Args:
            pv_data: 过程值数据
            sv_array: 设定值数组
            gap_start: 间隔起始索引
            gap_end: 间隔结束索引
            gap_sv: 间隔区域的SV数组
            fallback_sp: 备用设定值
            
        Returns:
            bool: 如果是稳态返回True
        """
        if gap_sv is None or len(gap_sv) == 0:
            gap_setpoint = fallback_sp
            return self._is_region_steady(pv_data, sv_array, gap_start, gap_end, gap_setpoint)
        
        sv_range = np.max(gap_sv) - np.min(gap_sv)
        
        # 如果SV有明显变化，检查SV稳定后的部分
        if sv_range > 1.0:
            # 从后往前找到SV稳定的起始点
            stable_start_offset = 0
            for j in range(len(gap_sv) - 1, 0, -1):
                if abs(gap_sv[j] - gap_sv[-1]) > 0.5:
                    stable_start_offset = j + 1
                    break
            
            stable_length = len(gap_sv) - stable_start_offset
            # 稳定段足够长才检查
            if stable_length >= 50:
                stable_region_start = gap_start + stable_start_offset
                stable_sv = np.median(gap_sv[stable_start_offset:])
                return self._is_region_steady(pv_data, sv_array, stable_region_start, gap_end, stable_sv)
            return False
        
        # SV无明显变化，检查整个区域
        gap_setpoint = np.median(gap_sv)
        return self._is_region_steady(pv_data, sv_array, gap_start, gap_end, gap_setpoint)
    
    def _has_non_steady_features(self, gap_pv):
        """
        检查区域是否有明显的非稳态特征
        
        Args:
            gap_pv: 间隔区域的PV数据
            
        Returns:
            bool: 如果有非稳态特征返回True
        """
        if len(gap_pv) <= 10:
            return False
        
        # 检查整体变化幅度
        if abs(gap_pv[-1] - gap_pv[0]) > 3.0:
            return True
        
        # 检查斜率
        try:
            x = np.arange(len(gap_pv))
            coeffs = np.polyfit(x, gap_pv, 1)
            if abs(coeffs[0]) > 0.08:
                return True
        except:
            pass
        
        return False
    
    def _is_region_steady(self, pv_data, sv_array, start_idx, end_idx, setpoint):
        """
        检查指定区域是否为稳态
        
        Args:
            pv_data: 过程值数据
            sv_array: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            setpoint: 设定值
            
        Returns:
            bool: 如果是稳态返回True
        """
        if end_idx - start_idx < 10:
            return False
        
        # 确保索引有效
        start_idx = max(0, start_idx)
        end_idx = min(len(pv_data), end_idx)
        
        if start_idx >= end_idx:
            return False
        
        region_pv = pv_data[start_idx:end_idx]
        region_sv = sv_array[start_idx:end_idx] if start_idx < len(sv_array) and end_idx <= len(sv_array) else None
        
        # 检查SV是否有变化
        if region_sv is not None and len(region_sv) > 0:
            sv_range = np.max(region_sv) - np.min(region_sv)
            sv_std = np.std(region_sv)
            # 如果SV有明显变化，直接判定为非稳态
            if sv_range > 1.0 or sv_std > 0.5:
                return False
            current_sv = np.median(region_sv)
        else:
            current_sv = setpoint
        
        # 计算PV统计量
        pv_std = np.std(region_pv)
        pv_range = np.max(region_pv) - np.min(region_pv)
        pv_mean = np.mean(region_pv)
        
        # 特殊处理：PV全部为0或接近0，判定为非稳态
        if pv_range == 0 and pv_mean < 0.1:
            return False
        
        # 稳态判断标准：PV波动小 且 无明显趋势
        
        # 标准1：波动性检查
        is_low_variation = (
            (pv_std < current_sv * 0.15 and pv_range < current_sv * 0.3) if current_sv > 0
            else (pv_std < 1.5 and pv_range < 3.0)
        )
        
        # 标准2：趋势检查
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
        """
        检测所有扰动（非稳态）的起始点
        
        关键：只检测SV未变化时的扰动，排除SV调整时的正常变化
        
        Args:
            pv_data: 过程值数据
            sv_array: 设定值数组
            non_steady_segments: 已检测到的非稳态段列表（可选），如果提供，会从中提取扰动起始点
            
        Returns:
            list: 扰动起始点列表，每个元素为 (start_idx, setpoint)
        """
        n = len(pv_data)
        if n < 50:
            return []
        
        disturbance_starts = []
        
        # 检测所有SV变化区间（包括响应缓冲期）
        # 传入PV数据，以便根据PV的收敛情况动态调整响应缓冲期
        sv_change_intervals = self.detect_sv_change_intervals(sv_array, threshold=0.1, min_stable_points=10, response_buffer=100, pv_data=pv_data)
        
        # 方法1：从非稳态段中提取扰动起始点（如果提供了非稳态段）
        if non_steady_segments is not None and len(non_steady_segments) > 0:
            for seg_start, seg_end, seg_setpoint in non_steady_segments:
                # 检查该段是否有大幅振荡（即使与SV变化区间重叠，大幅振荡也应该识别）
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
                
                # 如果不在SV变化区间内，或者有大幅振荡，继续处理
                in_sv_change = self.is_in_sv_change_interval(seg_start, sv_change_intervals)
                if in_sv_change and not has_large_oscillation:
                    # 在SV变化区间内且没有大幅振荡，跳过
                    continue
                
                # 检查该段内设定值是否在变化（如果没有大幅振荡）
                if not has_large_oscillation:
                    is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
                    if is_sv_changing:
                        # SV正在变化，跳过
                        continue
                
                # 尝试找到该段内的扰动起始点
                # 检查前段是否稳态
                head_len = min(50, (seg_end - seg_start) // 3)
                if head_len >= 20:
                    head_segment = pv_data[seg_start:seg_start + head_len]
                    is_head_steady = self.is_steady_state(head_segment, seg_setpoint)
                    
                    if is_head_steady:
                        # 前段稳态，查找扰动起始点
                        disturbance_start = self.find_disturbance_start(
                            pv_data[seg_start:seg_end], seg_setpoint, head_len, threshold=0.5
                        )
                        if disturbance_start is not None:
                            disturbance_starts.append((seg_start + disturbance_start, seg_setpoint))
                        else:
                            # 如果找不到明确的扰动起始点，使用非稳态段的起始点
                            disturbance_starts.append((seg_start, seg_setpoint))
                    else:
                        # 前段不是稳态（可能是冷启动），使用非稳态段的起始点作为扰动起始点
                        disturbance_starts.append((seg_start, seg_setpoint))
                else:
                    # 段太短，直接使用起始点
                    disturbance_starts.append((seg_start, seg_setpoint))
        
        # 方法2：如果没有提供非稳态段，使用原来的方法
        if non_steady_segments is None or len(non_steady_segments) == 0:
            # 检测设定值分段
            sv_segments = self.detect_setpoint_segments(sv_array, min_change=0.5, min_stable_points=20)
            
            for seg_start, seg_end, seg_setpoint in sv_segments:
                if seg_end - seg_start < 50:
                    continue
                
                # 检查该段内设定值是否在变化
                is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
                if is_sv_changing:
                    # SV正在变化，这是正常变化，不属于扰动，跳过
                    continue
                
                # 检查前段是否稳态
                head_len = min(50, (seg_end - seg_start) // 3)
                if head_len >= 20:
                    head_segment = pv_data[seg_start:seg_start + head_len]
                    is_head_steady = self.is_steady_state(head_segment, seg_setpoint)
                    
                    if is_head_steady:
                        # 前段稳态，查找扰动起始点
                        disturbance_start = self.find_disturbance_start(
                            pv_data[seg_start:seg_end], seg_setpoint, head_len, threshold=0.5
                        )
                        if disturbance_start is not None:
                            disturbance_starts.append((seg_start + disturbance_start, seg_setpoint))
        
        # 去重：如果同一个位置有多个扰动起始点，只保留一个
        if len(disturbance_starts) > 1:
            # 按索引排序
            disturbance_starts.sort(key=lambda x: x[0])
            # 去重：如果两个起始点距离太近（小于10个点），只保留第一个
            unique_starts = []
            for start_idx, setpoint in disturbance_starts:
                if len(unique_starts) == 0 or start_idx - unique_starts[-1][0] >= 10:
                    unique_starts.append((start_idx, setpoint))
            disturbance_starts = unique_starts
        
        return disturbance_starts

