"""
振荡分析模块 (Oscillation Analysis Module)
=========================================

分析振荡数据，提取临界振荡特征，用于Ziegler-Nichols临界法整定。

主要功能：
- 多种周期检测方法（峰值法、FFT法、自相关法）
- 临界增益估计
- 振荡置信度评估
- 基于振荡的PID参数计算
"""

import numpy as np
from typing import Dict, List, Tuple, Optional

from ..config import Config


class OscillationAnalysisMixin:
    """
    振荡分析Mixin类
    
    提供振荡分析和基于振荡的PID整定方法。
    需要宿主类提供 _epsilon 属性。
    """
    
    def analyze_oscillation(self, pv: np.ndarray, mv: np.ndarray, 
                            dt: float = 1.0) -> Optional[Dict]:
        """
        分析振荡数据，提取临界振荡特征
        
        使用多种方法综合检测，提高精度：
        1. 峰值检测法 + 插值精化
        2. FFT 法检测主频
        3. 自相关法验证
        
        Args:
            pv: 过程变量数组
            mv: 操作变量数组
            dt: 采样周期（秒）
        
        Returns:
            振荡特征字典，如果无法分析则返回 None
        """
        if len(pv) < 20:
            return None
        
        # 去趋势（使用线性去趋势更好）
        x = np.arange(len(pv))
        coeffs = np.polyfit(x, pv, 1)
        trend = np.polyval(coeffs, x)
        pv_detrend = pv - trend
        
        # ========== 方法1: 精确峰值检测法 ==========
        Pu_peaks = self._detect_period_from_peaks(pv_detrend, dt)
        
        # ========== 方法2: FFT 法 ==========
        Pu_fft = self._detect_period_from_fft(pv_detrend, dt)
        
        # ========== 方法3: 自相关法 ==========
        Pu_autocorr = self._detect_period_from_autocorr(pv_detrend, dt)
        
        # 综合多种方法的结果（使用配置的周期范围）
        osc_config = Config.OSCILLATION_TUNING
        MIN_PERIOD = osc_config['period_min']
        MAX_PERIOD = osc_config['period_max']
        
        valid_periods = []
        weights = []
        
        if Pu_peaks is not None and MIN_PERIOD < Pu_peaks < MAX_PERIOD:
            valid_periods.append(Pu_peaks)
            weights.append(2.0)  # 峰值法权重更高（更可靠）
        
        if Pu_fft is not None and MIN_PERIOD < Pu_fft < MAX_PERIOD:
            valid_periods.append(Pu_fft)
            weights.append(1.0)
        
        if Pu_autocorr is not None and MIN_PERIOD < Pu_autocorr < MAX_PERIOD:
            valid_periods.append(Pu_autocorr)
            weights.append(1.5)
        
        if not valid_periods:
            return None
        
        # 如果多种方法结果差异太大，使用中位数而不是加权平均
        if len(valid_periods) >= 2:
            period_range = max(valid_periods) / min(valid_periods)
            if period_range > 2.0:
                # 结果差异太大，使用中位数
                Pu = float(np.median(valid_periods))
            else:
                Pu = np.average(valid_periods, weights=weights)
        else:
            Pu = valid_periods[0]
        
        # ========== 计算振荡幅度和衰减比 ==========
        peak_indices, peak_values, valley_indices, valley_values = self._find_peaks_valleys(pv_detrend)
        
        # 对于慢系统，放宽峰谷数量要求
        min_peaks_required = 2
        if Pu > 60.0:  # 慢系统（周期>60s）
            min_peaks_required = 1
        
        if len(peak_values) < min_peaks_required or len(valley_values) < min_peaks_required:
            # 尝试使用整体数据估算振幅
            if Pu > 60.0 and len(pv_detrend) > 20:
                # 慢系统fallback：使用数据范围估算
                amplitude = np.ptp(pv_detrend) / 2
                avg_decay = 1.0  # 假设持续振荡
                peak_indices = np.array([np.argmax(pv_detrend)])
                valley_indices = np.array([np.argmin(pv_detrend)])
                peak_values = np.array([np.max(pv_detrend)])
                valley_values = np.array([np.min(pv_detrend)])
            else:
                return None
        else:
            amplitude = (np.mean(peak_values) - np.mean(valley_values)) / 2
        
        # 计算衰减比
        if len(peak_values) >= 3:
            # 使用去趋势后的峰值计算衰减比
            peak_amplitudes = np.abs(peak_values - np.mean(pv_detrend))
            decay_ratios = []
            for i in range(len(peak_amplitudes) - 1):
                if peak_amplitudes[i] > self._epsilon:
                    decay_ratios.append(peak_amplitudes[i + 1] / peak_amplitudes[i])
            avg_decay = np.median(decay_ratios) if decay_ratios else 1.0
        else:
            avg_decay = 1.0
        
        # 检查MV是否也在振荡（而不是阶跃）
        mv_diff = np.diff(mv)
        mv_sign_changes = np.sum(np.abs(np.diff(np.sign(mv_diff))) > 0)
        mv_oscillation_ratio = mv_sign_changes / (len(mv) - 2) if len(mv) > 2 else 0
        
        # 计算MV的振荡幅度（排除阶跃影响）
        if mv_oscillation_ratio > 0.2:
            mv_amplitude = (np.max(mv) - np.min(mv)) / 2
        else:
            mv_amplitude = np.median(np.abs(mv_diff)) * 2
        
        # ========== 多周期 Ku 估计（提高鲁棒性）==========
        Ku_estimates = []
        pv_mean = np.mean(pv_detrend)
        
        # 逐周期计算 Ku
        n_peaks = min(len(peak_indices), len(valley_indices))
        for i in range(n_peaks):
            # 每个周期的 PV 振幅
            cycle_pv_amp = abs(peak_values[i] - valley_values[i]) / 2
            
            # 对应周期的 MV 振幅（查找该周期内的 MV 范围）
            start_idx = valley_indices[i] if i == 0 else min(peak_indices[i-1], valley_indices[i])
            end_idx = peak_indices[i] if i < len(peak_indices) else valley_indices[i]
            if start_idx < end_idx and end_idx <= len(mv):
                cycle_mv = mv[start_idx:end_idx]
                cycle_mv_amp = (np.max(cycle_mv) - np.min(cycle_mv)) / 2
                
                if cycle_pv_amp > self._epsilon and cycle_mv_amp > self._epsilon:
                    Ku_cycle = 4 * cycle_mv_amp / (np.pi * cycle_pv_amp)
                    Ku_estimates.append(Ku_cycle)
        
        # 如果多周期估计可用，使用中位数（更鲁棒）
        if len(Ku_estimates) >= 2:
            Ku_estimate = float(np.median(Ku_estimates))
            Ku_std = float(np.std(Ku_estimates))
        elif amplitude > self._epsilon:
            # 回退到整体估计
            Ku_estimate = 4 * mv_amplitude / (np.pi * amplitude)
            Ku_std = Ku_estimate * 0.5  # 假设50%不确定度
        else:
            Ku_estimate = 1.0
            Ku_std = 1.0
        
        # 动态调整 Ku 边界
        pv_range = np.ptp(pv)
        mv_range = np.ptp(mv)
        K_approx = pv_range / mv_range if mv_range > 0.1 else 1.0
        
        Ku_min = 0.1
        Ku_max = max(10.0, 15.0 / max(K_approx, 0.1))
        Ku_max = min(Ku_max, 100.0)
        
        Ku_estimate = np.clip(Ku_estimate, Ku_min, Ku_max)
        
        # 判断振荡类型
        if avg_decay > 1.1:
            osc_type = 'diverging'
        elif avg_decay < 0.9:
            osc_type = 'converging'
        else:
            osc_type = 'sustained'
        
        n_cycles = max(len(peak_indices), len(valley_indices)) - 1
        
        # ========== 置信度评估 ==========
        confidence = self._calculate_oscillation_confidence(
            valid_periods, weights, Ku_estimates, n_cycles, avg_decay, osc_type
        )
        
        # 判断是否有效：
        # - 正常情况需要至少2个周期
        # - 对于慢系统（Pu > 60s），允许1个周期但降低置信度
        # - 发散振荡不可靠
        if osc_type == 'diverging':
            is_valid = False
        elif n_cycles >= 2:
            is_valid = True
        elif n_cycles >= 1 and Pu > 60.0:
            # 慢系统允许1个周期，但降低置信度
            is_valid = True
            confidence = confidence * 0.6  # 降低置信度
        else:
            is_valid = False
        
        return {
            'Pu': round(Pu, 3),              # 临界周期
            'Ku': round(Ku_estimate, 4),     # 临界增益估计
            'amplitude': round(amplitude, 2), # 振荡幅度
            'mv_amplitude': round(mv_amplitude, 2),  # MV幅度
            'decay_ratio': round(avg_decay, 3),      # 衰减比
            'oscillation_type': osc_type,    # 振荡类型
            'n_cycles': n_cycles,            # 完整振荡周期数
            'is_valid': is_valid,
            'confidence': round(confidence, 3),      # 置信度 [0, 1]
            'Ku_std': round(Ku_std, 4) if Ku_std else None,  # Ku 标准差
            'detection_methods': {           # 各方法检测结果（调试用）
                'peaks': round(Pu_peaks, 3) if Pu_peaks else None,
                'fft': round(Pu_fft, 3) if Pu_fft else None,
                'autocorr': round(Pu_autocorr, 3) if Pu_autocorr else None
            }
        }
    
    def _detect_period_from_peaks(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用峰值检测法计算周期"""
        peak_indices, peak_values, _, _ = self._find_peaks_valleys(pv)
        
        if len(peak_indices) < 3:
            return None
        
        # 使用抛物线插值精化峰值位置
        refined_indices = []
        for idx in peak_indices:
            if 1 <= idx < len(pv) - 1:
                # 抛物线插值: y = a*x^2 + b*x + c
                # 峰值位置: x_peak = -b / (2a)
                y0, y1, y2 = pv[idx-1], pv[idx], pv[idx+1]
                denom = 2 * (y0 - 2*y1 + y2)
                if abs(denom) > self._epsilon:
                    delta = (y0 - y2) / denom
                    refined_indices.append(idx + delta)
                else:
                    refined_indices.append(float(idx))
            else:
                refined_indices.append(float(idx))
        
        # 计算相邻峰值间的周期
        periods = np.diff(refined_indices) * dt
        
        # 过滤异常值（使用 IQR 方法）
        if len(periods) >= 3:
            q1, q3 = np.percentile(periods, [25, 75])
            iqr = q3 - q1
            valid_periods = periods[(periods >= q1 - 1.5*iqr) & (periods <= q3 + 1.5*iqr)]
            if len(valid_periods) > 0:
                return float(np.median(valid_periods))
        
        return float(np.median(periods)) if len(periods) > 0 else None
    
    def _detect_period_from_fft(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用 FFT 检测主频（带抛物线插值提高分辨率）"""
        n = len(pv)
        if n < 10:
            return None
        
        # 加窗减少频谱泄漏
        window = np.hanning(n)
        pv_windowed = pv * window
        
        # 零填充提高频率分辨率
        n_fft = max(n * 4, 1024)
        
        # FFT
        fft_result = np.fft.rfft(pv_windowed, n=n_fft)
        freqs = np.fft.rfftfreq(n_fft, dt)
        
        # 找到主频（排除直流分量）
        magnitude = np.abs(fft_result)
        
        # 只考虑合理的频率范围（周期在 2*dt 到 n*dt/2 之间）
        min_freq = 2.0 / (n * dt)  # 至少 2 个周期
        max_freq = 1.0 / (2 * dt)   # 奈奎斯特频率
        
        valid_mask = (freqs > min_freq) & (freqs < max_freq)
        if not np.any(valid_mask):
            return None
        
        # 获取有效范围内的索引
        valid_indices = np.where(valid_mask)[0]
        if len(valid_indices) < 3:
            return None
        
        # 找到最大幅度对应的索引
        peak_idx_in_valid = np.argmax(magnitude[valid_mask])
        peak_idx = valid_indices[peak_idx_in_valid]
        
        # 抛物线插值精化频率（如果峰值不在边界）
        if peak_idx > 0 and peak_idx < len(magnitude) - 1:
            y0, y1, y2 = magnitude[peak_idx-1], magnitude[peak_idx], magnitude[peak_idx+1]
            denom = 2 * (y0 - 2*y1 + y2)
            if abs(denom) > self._epsilon:
                delta = (y0 - y2) / denom
                refined_idx = peak_idx + delta
                dominant_freq = freqs[0] + refined_idx * (freqs[1] - freqs[0])
            else:
                dominant_freq = freqs[peak_idx]
        else:
            dominant_freq = freqs[peak_idx]
        
        if dominant_freq > self._epsilon:
            return 1.0 / dominant_freq
        return None
    
    def _detect_period_from_autocorr(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用自相关法检测周期"""
        n = len(pv)
        if n < 20:
            return None
        
        # 计算自相关
        pv_normalized = pv - np.mean(pv)
        autocorr = np.correlate(pv_normalized, pv_normalized, mode='full')
        autocorr = autocorr[n-1:]  # 只取正延迟部分
        autocorr = autocorr / autocorr[0]  # 归一化
        
        # 找到第一个极大值（排除 lag=0）
        min_lag = max(2, int(1.0 / dt))  # 至少 1 秒
        max_lag = n // 2
        
        for i in range(min_lag, max_lag):
            if autocorr[i] > autocorr[i-1] and autocorr[i] > autocorr[i+1]:
                # 使用抛物线插值精化
                y0, y1, y2 = autocorr[i-1], autocorr[i], autocorr[i+1]
                denom = 2 * (y0 - 2*y1 + y2)
                if abs(denom) > self._epsilon:
                    delta = (y0 - y2) / denom
                    return (i + delta) * dt
                return i * dt
        
        return None
    
    def _find_peaks_valleys(self, pv: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """找到峰值和谷值的位置和值"""
        peak_indices = []
        peak_values = []
        valley_indices = []
        valley_values = []
        
        for i in range(1, len(pv) - 1):
            if pv[i] > pv[i-1] and pv[i] > pv[i+1]:
                peak_indices.append(i)
                peak_values.append(pv[i])
            elif pv[i] < pv[i-1] and pv[i] < pv[i+1]:
                valley_indices.append(i)
                valley_values.append(pv[i])
        
        return (np.array(peak_indices), np.array(peak_values), 
                np.array(valley_indices), np.array(valley_values))
    
    def _calculate_oscillation_confidence(self, valid_periods: List[float], 
                                          weights: List[float],
                                          Ku_estimates: List[float],
                                          n_cycles: int, 
                                          decay_ratio: float,
                                          osc_type: str) -> float:
        """
        计算振荡分析结果的置信度
        
        综合考虑以下因素：
        1. Pu 检测方法的一致性
        2. Ku 多周期估计的一致性
        3. 振荡周期数量
        4. 振荡类型
        
        Returns:
            置信度 [0, 1]
        """
        confidence = 0.0
        
        # 1. Pu 一致性评分 (0-0.4)
        if len(valid_periods) >= 2:
            period_cv = np.std(valid_periods) / np.mean(valid_periods) if np.mean(valid_periods) > 0 else 1.0
            # CV < 0.1 得满分，CV > 0.5 得0分
            pu_score = max(0, 1 - period_cv / 0.5) * 0.4
        elif len(valid_periods) == 1:
            pu_score = 0.2  # 只有一种方法检测到
        else:
            pu_score = 0.0
        confidence += pu_score
        
        # 2. Ku 一致性评分 (0-0.3)
        if len(Ku_estimates) >= 3:
            Ku_cv = np.std(Ku_estimates) / np.mean(Ku_estimates) if np.mean(Ku_estimates) > 0 else 1.0
            # CV < 0.2 得满分，CV > 0.8 得0分
            Ku_score = max(0, 1 - Ku_cv / 0.8) * 0.3
        elif len(Ku_estimates) >= 2:
            Ku_cv = np.std(Ku_estimates) / np.mean(Ku_estimates) if np.mean(Ku_estimates) > 0 else 1.0
            Ku_score = max(0, 1 - Ku_cv / 0.8) * 0.2
        else:
            Ku_score = 0.1  # 只有整体估计
        confidence += Ku_score
        
        # 3. 周期数评分 (0-0.2)
        # 2个周期得0.1，5个以上得满分
        cycle_score = min(n_cycles / 5, 1.0) * 0.2
        confidence += cycle_score
        
        # 4. 振荡类型评分 (0-0.1)
        if osc_type == 'sustained':
            type_score = 0.1  # 持续振荡最可靠
        elif osc_type == 'converging':
            type_score = 0.08  # 收敛振荡也可以
        else:
            type_score = 0.0  # 发散振荡不可靠
        confidence += type_score
        
        return min(confidence, 1.0)
    
    def calculate_from_oscillation(self, osc_info: Dict, 
                                   current_pid: Dict = None,
                                   method: str = 'zn') -> Optional[Dict[str, float]]:
        """
        基于振荡特征计算 PID 参数（Ziegler-Nichols 临界法）
        
        Args:
            osc_info: 振荡分析结果（来自 analyze_oscillation）
            current_pid: 当前 PID 参数 {'Kp': ..., 'Ki': ..., 'Kd': ...}
            method: 整定方法
                - 'zn': Ziegler-Nichols 经典法
                - 'zn_no_overshoot': ZN 无超调法
                - 'zn_some_overshoot': ZN 少超调法
                - 'tyreus_luyben': Tyreus-Luyben 法（更稳定）
        
        Returns:
            PID 参数字典，如果无法计算则返回 None
        """
        if not osc_info or not osc_info.get('is_valid', False):
            return None
        
        Pu = osc_info['Pu']
        Ku = osc_info['Ku']
        
        # 如果有当前 PID 参数，可以用于校正 Ku 估计
        if current_pid and current_pid.get('Kp', 0) != 0:
            current_Kp = abs(current_pid['Kp'])
            # 如果当前系统正在临界振荡，则 Ku ≈ current_Kp
            # 如果是发散振荡，Ku < current_Kp
            # 如果是收敛振荡，Ku > current_Kp
            osc_type = osc_info.get('oscillation_type', 'sustained')
            if osc_type == 'sustained':
                Ku = current_Kp
            elif osc_type == 'diverging':
                Ku = current_Kp * 0.8  # 保守估计
            else:  # converging
                Ku = current_Kp * 1.2
        
        # 根据不同方法计算 PID 参数
        if method == 'zn':
            # Ziegler-Nichols 经典法（可能有较大超调）
            Kp = 0.6 * Ku
            Ti = Pu / 2
            Td = Pu / 8
        elif method == 'zn_no_overshoot':
            # ZN 无超调法
            Kp = 0.2 * Ku
            Ti = Pu / 2
            Td = Pu / 3
        elif method == 'zn_some_overshoot':
            # ZN 少超调法
            Kp = 0.33 * Ku
            Ti = Pu / 2
            Td = Pu / 3
        elif method == 'tyreus_luyben':
            # Tyreus-Luyben 法（更稳定，适合工业应用）
            Kp = 0.45 * Ku
            Ti = 2.2 * Pu
            Td = Pu / 6.3
        else:
            # 默认使用保守的 ZN 法
            Kp = 0.45 * Ku
            Ti = Pu / 1.2
            Td = Pu / 8
        
        # 计算 Ki 和 Kd
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        # 确定符号（如果有当前 PID，保持符号一致）
        if current_pid and current_pid.get('Kp', 0) < 0:
            Kp = -Kp
            Ki = -Ki
            Kd = -Kd
        
        return {
            'Kp': round(float(Kp), 2),
            'Ki': round(float(Ki), 2),
            'Kd': round(float(Kd), 2),
            'method': f'oscillation_{method}',
            'Pu': round(Pu, 2),
            'Ku': round(Ku, 2)
        }
