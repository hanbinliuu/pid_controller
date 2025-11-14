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
        
        # 检查设定值的变化范围
        sv_range = np.max(segment_sv) - np.min(segment_sv)
        if sv_range > threshold:
            return True
        
        # 检查设定值的标准差
        sv_std = np.std(segment_sv)
        if sv_std > threshold * 0.5:
            return True
        
        # 检查是否有明显的趋势性变化
        if len(segment_sv) > 5:
            x = np.arange(len(segment_sv))
            try:
                coeffs = np.polyfit(x, segment_sv, 1)
                slope = abs(coeffs[0])
                if slope > threshold / len(segment_sv):
                    return True
            except:
                pass
        
        # 检查首尾差值
        if len(segment_sv) > 1:
            if abs(segment_sv[-1] - segment_sv[0]) > threshold:
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
        
        # 方法1：偏差突变检测
        for i in range(steady_head_len, n - 5):
            if abs(pv_data[i] - setpoint) > threshold:
                window = min(5, n - i)
                if window > 0:
                    window_data = pv_data[i:i+window]
                    if np.mean(np.abs(window_data - setpoint)) > threshold * 0.8:
                        return i
        
        # 方法2：斜率突变检测
        if n > steady_head_len + 20:
            dy = np.diff(pv_data)
            steady_dy = dy[:steady_head_len-1] if steady_head_len > 1 else dy[:min(10, len(dy))]
            steady_slope_mean = np.mean(np.abs(steady_dy))
            steady_slope_std = np.std(np.abs(steady_dy))
            
            for i in range(steady_head_len, len(dy) - 5):
                local_slope = np.abs(dy[i])
                if local_slope > steady_slope_mean + 2 * steady_slope_std:
                    window = min(5, len(dy) - i)
                    if window > 0:
                        window_slopes = np.abs(dy[i:i+window])
                        if np.mean(window_slopes) > steady_slope_mean + steady_slope_std:
                            return i + 1
        
        # 方法3：二阶差分（加速度）突变检测
        if n > steady_head_len + 30:
            d2y = np.diff(np.diff(pv_data))
            if len(d2y) > steady_head_len:
                steady_d2y = d2y[:steady_head_len-2] if steady_head_len > 2 else d2y[:min(10, len(d2y))]
                steady_acc_mean = np.mean(np.abs(steady_d2y))
                steady_acc_std = np.std(np.abs(steady_d2y))
                
                for i in range(steady_head_len - 2, len(d2y) - 5):
                    local_acc = np.abs(d2y[i])
                    if local_acc > steady_acc_mean + 3 * steady_acc_std:
                        window = min(5, len(d2y) - i)
                        if window > 0:
                            window_acc = np.abs(d2y[i:i+window])
                            if np.mean(window_acc) > steady_acc_mean + 2 * steady_acc_std:
                                return i + 2
        
        return None
    
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
                            
                            # 如果提供了PV数据，根据PV的收敛情况和振荡情况动态调整响应缓冲期
                            if pv_data is not None and sv_stable_end < len(pv_data):
                                # 检查更长的范围，以便找到真正的振荡开始位置
                                max_check_len = min(1000, n - sv_stable_end)  # 最多检查1000个点
                                check_end = min(sv_stable_end + max_check_len, len(pv_data))
                                
                                if check_end > sv_stable_end + 100:
                                    # 使用滑动窗口分段检查：先检查收敛，再检查振荡
                                    window_size = 50
                                    step_size = 20
                                    
                                    # 第一阶段：检查前面的数据是否在收敛
                                    convergence_found = False
                                    convergence_end = sv_stable_end
                                    
                                    for check_start in range(sv_stable_end, min(sv_stable_end + 500, check_end - window_size), step_size):
                                        window_pv = pv_data[check_start:check_start + window_size]
                                        if len(window_pv) < window_size:
                                            break
                                        
                                        window_errors = np.abs(window_pv - new_sv)
                                        window_mean_error = np.mean(window_errors)
                                        
                                        # 检查误差是否在减小（收敛）
                                        if check_start + window_size * 2 <= check_end:
                                            next_window_pv = pv_data[check_start + window_size:check_start + window_size * 2]
                                            next_window_errors = np.abs(next_window_pv - new_sv)
                                            next_window_mean_error = np.mean(next_window_errors)
                                            
                                            if next_window_mean_error < window_mean_error * 0.9:
                                                # 误差在减小，说明正在收敛
                                                convergence_found = True
                                                convergence_end = check_start + window_size * 2
                                        
                                        # 同时检查是否出现大幅振荡
                                        pv_range = np.max(window_pv) - np.min(window_pv)
                                        pv_std = np.std(window_pv)
                                        
                                        if new_sv > 0:
                                            is_osc = pv_range > max(new_sv * 1.0, 10.0) or pv_std > max(new_sv * 0.6, 4.0)
                                        else:
                                            is_osc = pv_range > 10.0 or pv_std > 4.0
                                        
                                        if is_osc:
                                            # 找到大幅振荡，停止检查收敛
                                            break
                                    
                                    # 如果前面在收敛，延长响应缓冲期
                                    if convergence_found:
                                        additional_buffer = min(300, convergence_end - sv_stable_end)
                                        dynamic_buffer = max(dynamic_buffer, additional_buffer)
                                    
                                    # 第二阶段：找到大幅振荡开始的位置
                                    # 使用更严格的阈值来检测真正的非稳态振荡
                                    osc_window = 40
                                    osc_start_found = None
                                    
                                    for osc_start in range(sv_stable_end, check_end - osc_window, step_size):
                                        osc_pv = pv_data[osc_start:osc_start + osc_window]
                                        if len(osc_pv) < osc_window:
                                            break
                                        
                                        osc_range = np.max(osc_pv) - np.min(osc_pv)
                                        osc_std = np.std(osc_pv)
                                        osc_mean = np.mean(osc_pv)
                                        
                                        # 使用更严格的阈值：大幅振荡应该是非常明显的
                                        if new_sv > 0:
                                            # 振荡范围应该超过设定值的100%或超过10个单位
                                            # 标准差应该超过设定值的60%或超过4个单位
                                            is_large_osc = (osc_range > max(new_sv * 1.0, 10.0) or 
                                                          osc_std > max(new_sv * 0.6, 4.0))
                                            # 或者振荡幅度相对于设定值很大
                                            if osc_range > max(new_sv * 2.0, 15.0):
                                                is_large_osc = True
                                        else:
                                            is_large_osc = osc_range > 10.0 or osc_std > 4.0
                                        
                                        if is_large_osc:
                                            # 找到大幅振荡开始的位置
                                            osc_start_found = osc_start
                                            break
                                    
                                    # 如果找到振荡开始位置，将响应缓冲期限制到该位置之前
                                    if osc_start_found is not None:
                                        # 响应缓冲期应该到振荡开始之前
                                        max_buffer = osc_start_found - sv_stable_end
                                        dynamic_buffer = min(dynamic_buffer, max_buffer)
                                        # 但至少保留一些缓冲期（至少50个点）
                                        dynamic_buffer = max(50, dynamic_buffer)
                            
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
            if error1 > error2 and error2 > error3:
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
                    # 获取设定值
                    if len(change_sv) > 0:
                        current_sv = np.median(change_sv)
                    else:
                        current_sv = np.median(sv_array[max(0, change_start-10):change_start]) if change_start > 0 else np.mean(sv_array)
                    
                    # 检查是否有大幅振荡
                    pv_range = np.max(change_pv) - np.min(change_pv)
                    pv_std = np.std(change_pv)
                    
                    is_large_oscillation = False
                    if current_sv > 0:
                        if pv_range > max(current_sv * 0.5, 5.0) or pv_std > max(current_sv * 0.3, 2.0):
                            is_large_oscillation = True
                    else:
                        if pv_range > 5.0 or pv_std > 2.0:
                            is_large_oscillation = True
                    
                    # 如果有大幅振荡，识别为扰动段
                    if is_large_oscillation:
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
                    
                    # 使用滑动窗口找到真正的大幅振荡开始位置
                    window_size = 40
                    step_size = 20
                    osc_start_idx = None
                    
                    # 从段开始位置向后扫描，找到第一个出现大幅振荡的位置
                    for check_start in range(seg_start, seg_end - window_size, step_size):
                        window_pv = pv_data[check_start:check_start + window_size]
                        if len(window_pv) < window_size:
                            break
                        
                        pv_range = np.max(window_pv) - np.min(window_pv)
                        pv_std = np.std(window_pv)
                        
                        # 使用更严格的阈值：大幅振荡应该是非常明显的
                        is_large_oscillation = False
                        if current_sv > 0:
                            # 振荡范围应该超过设定值的100%或超过10个单位
                            # 标准差应该超过设定值的60%或超过4个单位
                            if pv_range > max(current_sv * 1.0, 10.0) or pv_std > max(current_sv * 0.6, 4.0):
                                is_large_oscillation = True
                            # 或者振荡幅度相对于设定值很大（超过200%）
                            if pv_range > max(current_sv * 2.0, 15.0):
                                is_large_oscillation = True
                        else:
                            if pv_range > 10.0 or pv_std > 4.0:
                                is_large_oscillation = True
                        
                        if is_large_oscillation:
                            # 找到大幅振荡开始的位置
                            osc_start_idx = check_start
                            break
                    
                    # 如果找到大幅振荡，从振荡开始位置标记非稳态段
                    if osc_start_idx is not None:
                        # 找到振荡结束的位置（或者到段结束）
                        osc_end_idx = seg_end
                        # 可以进一步优化：找到振荡结束的位置
                        # 但为了简化，暂时使用段结束位置
                        non_steady_segments.append((osc_start_idx, osc_end_idx, current_sv))
                
                # 无论是否有大幅振荡，都跳过后续的常规检测
                continue
            
            # 检查该段内设定值是否在变化（更严格的检查）
            is_sv_changing = self.is_setpoint_changing(sv_array, seg_start, seg_end, threshold=0.1)
            
            if is_sv_changing:
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
                            # 使用滑动窗口找到真正的大幅振荡开始位置
                            window_size = 40
                            step_size = 20
                            osc_start_idx = None
                            
                            # 从SV稳定后开始扫描，找到第一个出现大幅振荡的位置
                            for check_start in range(stable_sv_start, seg_end - window_size, step_size):
                                window_pv = pv_data[check_start:check_start + window_size]
                                if len(window_pv) < window_size:
                                    break
                                
                                pv_range = np.max(window_pv) - np.min(window_pv)
                                pv_std = np.std(window_pv)
                                
                                # 使用更严格的阈值：大幅振荡应该是非常明显的
                                is_large_oscillation = False
                                if stable_sv > 0:
                                    # 振荡范围应该超过设定值的100%或超过10个单位
                                    # 标准差应该超过设定值的60%或超过4个单位
                                    if pv_range > max(stable_sv * 1.0, 10.0) or pv_std > max(stable_sv * 0.6, 4.0):
                                        is_large_oscillation = True
                                    # 或者振荡幅度相对于设定值很大（超过200%）
                                    if pv_range > max(stable_sv * 2.0, 15.0):
                                        is_large_oscillation = True
                                else:
                                    if pv_range > 10.0 or pv_std > 4.0:
                                        is_large_oscillation = True
                                
                                if is_large_oscillation:
                                    # 找到大幅振荡开始的位置
                                    osc_start_idx = check_start
                                    break
                            
                            # 如果找到大幅振荡，从振荡开始位置标记非稳态段
                            if osc_start_idx is not None:
                                # 确保非稳态段的结束不在SV变化区间内
                                non_steady_end = seg_end
                                for change_start, change_end in sv_change_intervals:
                                    if change_start < non_steady_end <= change_end:
                                        non_steady_end = change_start
                                        break
                                
                                if non_steady_end > osc_start_idx and non_steady_end - osc_start_idx >= min_segment_len:
                                    non_steady_segments.append((osc_start_idx, non_steady_end, stable_sv))
                            # 如果没有找到大幅振荡，但确实未稳态，可能是小幅波动，暂时不标记
                            # 或者可以根据需要标记，但使用更宽松的条件
                # SV变化期间的数据不算非稳态，跳过
                continue
            
            # SV未变化，检测该段内的非稳态（但要排除SV变化区间，除非有大幅振荡）
            seg_pv = pv_data[seg_start:seg_end]
            
            # 使用滑动窗口检测非稳态段
            window = min(30, (seg_end - seg_start) // 5)
            window = max(10, window)
            
            i = seg_start
            while i < seg_end - window:
                # 检查当前窗口是否在SV变化区间内
                in_sv_change = self.is_in_sv_change_interval(i, sv_change_intervals)
                
                if in_sv_change:
                    # 在SV变化区间内，但需要检查是否有大幅振荡
                    # 如果有大幅振荡，仍然应该识别为扰动
                    window_data = pv_data[i:i+window]
                    window_sv = sv_array[i:i+window] if i < len(sv_array) else None
                    
                    # 获取当前窗口的设定值
                    if window_sv is not None and len(window_sv) > 0:
                        current_sv = np.median(window_sv)
                    else:
                        current_sv = seg_setpoint
                    
                    # 检查是否有大幅振荡（使用更严格的阈值）
                    pv_range = np.max(window_data) - np.min(window_data)
                    pv_std = np.std(window_data)
                    
                    is_large_oscillation = False
                    if current_sv > 0:
                        # 更严格的阈值：只有当振荡幅度很大时才认为是非稳态
                        if pv_range > max(current_sv * 0.8, 8.0) or pv_std > max(current_sv * 0.5, 3.0):
                            is_large_oscillation = True
                    else:
                        if pv_range > 8.0 or pv_std > 3.0:
                            is_large_oscillation = True
                    
                    # 如果有大幅振荡，继续检测（不跳过）
                    if not is_large_oscillation:
                        i += window // 2
                        continue
                
                window_data = pv_data[i:i+window]
                is_steady = self.is_steady_state(window_data, seg_setpoint)
                
                if not is_steady:
                    # 进一步检查：是否真的出现了大幅振荡，而不仅仅是偏离设定值
                    pv_range = np.max(window_data) - np.min(window_data)
                    pv_std = np.std(window_data)
                    
                    # 使用更严格的阈值来判断是否为真正的非稳态
                    is_real_non_steady = False
                    if seg_setpoint > 0:
                        # 只有当振荡幅度很大时才认为是非稳态
                        if pv_range > max(seg_setpoint * 0.8, 8.0) or pv_std > max(seg_setpoint * 0.5, 3.0):
                            is_real_non_steady = True
                    else:
                        if pv_range > 8.0 or pv_std > 3.0:
                            is_real_non_steady = True
                    
                    # 如果只是偏离设定值但没有大幅振荡，跳过
                    if not is_real_non_steady:
                        i += window // 2
                        continue
                    
                    # 找到非稳态段的开始
                    start_idx = i
                    # 继续查找非稳态段的结束
                    j = i + window
                    while j < seg_end - window:
                        # 检查是否进入SV变化区间
                        in_sv_change = self.is_in_sv_change_interval(j, sv_change_intervals)
                        
                        if in_sv_change:
                            # 在SV变化区间内，检查是否有大幅振荡
                            check_window = pv_data[j:j+window]
                            check_sv = sv_array[j:j+window] if j < len(sv_array) else None
                            
                            if check_sv is not None and len(check_sv) > 0:
                                check_sv_val = np.median(check_sv)
                            else:
                                check_sv_val = seg_setpoint
                            
                            pv_range = np.max(check_window) - np.min(check_window)
                            pv_std = np.std(check_window)
                            
                            is_large_oscillation = False
                            if check_sv_val > 0:
                                if pv_range > max(check_sv_val * 0.5, 5.0) or pv_std > max(check_sv_val * 0.3, 2.0):
                                    is_large_oscillation = True
                            else:
                                if pv_range > 5.0 or pv_std > 2.0:
                                    is_large_oscillation = True
                            
                            # 如果有大幅振荡，继续检测（不结束段）
                            if is_large_oscillation:
                                j += window // 2
                                continue
                            else:
                                # 没有大幅振荡，遇到SV变化区间，非稳态段结束
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
        # 但如果非稳态段有大幅振荡，即使与SV变化区间重叠，也应该保留
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
                # 即使有重叠，也要检查是否有大幅振荡
                seg_pv = pv_data[seg_start:seg_end]
                if len(seg_pv) >= min_segment_len:
                    pv_range = np.max(seg_pv) - np.min(seg_pv)
                    pv_std = np.std(seg_pv)
                    
                    is_large_oscillation = False
                    if seg_setpoint > 0:
                        if pv_range > max(seg_setpoint * 0.5, 5.0) or pv_std > max(seg_setpoint * 0.3, 2.0):
                            is_large_oscillation = True
                    else:
                        if pv_range > 5.0 or pv_std > 2.0:
                            is_large_oscillation = True
                    
                    # 如果有大幅振荡，保留该段（即使与SV变化区间重叠）
                    if is_large_oscillation:
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
                            
                            # 关键判断：检查是否有大幅振荡
                            # 如果振荡幅度很大，即使是在SV变化后，也认为是扰动
                            pv_range = np.max(seg_pv) - np.min(seg_pv)
                            pv_std = np.std(seg_pv)
                            pv_mean = np.mean(seg_pv)
                            
                            # 判断是否为大幅振荡：
                            # 1. 数据范围超过设定值的50%或超过5个单位
                            # 2. 标准差很大
                            is_large_oscillation = False
                            if new_sv > 0:
                                if pv_range > max(new_sv * 0.5, 5.0) or pv_std > max(new_sv * 0.3, 2.0):
                                    is_large_oscillation = True
                            else:
                                if pv_range > 5.0 or pv_std > 2.0:
                                    is_large_oscillation = True
                            
                            # 如果有大幅振荡，认为是扰动，不是响应过程
                            if is_large_oscillation:
                                is_response_to_sv_change = False
                                break
                            
                            # 如果没有大幅振荡，检查PV是否正在向新SV收敛
                            pv_start = seg_pv[0] if len(seg_pv) > 0 else pv_data[seg_start]
                            pv_end = seg_pv[-1] if len(seg_pv) > 0 else pv_data[min(seg_end-1, len(pv_data)-1)]
                            error_start = abs(pv_start - new_sv)
                            error_end = abs(pv_end - new_sv)
                            
                            # 如果PV正在收敛（误差减小），且没有大幅振荡，认为是响应过程
                            if error_end < error_start * 1.2 and not is_large_oscillation:
                                is_response_to_sv_change = True
                                break
            
            if not is_response_to_sv_change:
                # 进一步检查：是否是PV向设定值收敛的正常过程（不是扰动）
                is_converging = self.is_converging_to_setpoint(pv_data, sv_array, seg_start, seg_end, seg_setpoint)
                if not is_converging:
                    filtered_segments.append((seg_start, seg_end, seg_setpoint))
        
        # 合并重叠或相邻的非稳态段
        if len(filtered_segments) > 1:
            # 按起始索引排序
            filtered_segments.sort(key=lambda x: x[0])
            merged_segments = []
            current_start, current_end, current_sv = filtered_segments[0]
            
            for seg_start, seg_end, seg_setpoint in filtered_segments[1:]:
                # 如果当前段与下一个段重叠或相邻（间隔小于20个点），合并它们
                if seg_start <= current_end + 20:
                    # 合并：扩展结束位置，使用较大的设定值
                    current_end = max(current_end, seg_end)
                    current_sv = max(current_sv, seg_setpoint)
                else:
                    # 不重叠，保存当前段，开始新段
                    merged_segments.append((current_start, current_end, current_sv))
                    current_start, current_end, current_sv = seg_start, seg_end, seg_setpoint
            
            # 添加最后一段
            merged_segments.append((current_start, current_end, current_sv))
            filtered_segments = merged_segments
        
        return filtered_segments
    
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

