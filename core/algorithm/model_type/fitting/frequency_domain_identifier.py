"""
频域辨识模块 (Frequency Domain Identifier)
=========================================

基于频域分析的模型参数辨识方法。

方法说明
--------
1. **互相关法**: 利用输入输出互相关函数峰值位置估计滞后L
2. **FFT法**: 利用频谱分析估计系统参数

适用场景
--------
- 振荡数据 (oscillation_ratio > 0.3)
- 多频激励信号
- 闭环运行数据
"""

import numpy as np
from typing import Dict, Optional, Tuple
from scipy import signal
from scipy.fft import fft, fftfreq


class FrequencyDomainIdentifier:
    """频域辨识器"""
    
    EPSILON = 1e-9
    
    @classmethod
    def estimate_delay_by_correlation(cls, y: np.ndarray, u: np.ndarray, 
                                       dt: float = 1.0) -> Dict:
        """
        使用互相关法估计纯滞后时间
        
        原理：输入输出互相关函数的峰值位置对应系统滞后
        
        Args:
            y: 输出信号 (PV)
            u: 输入信号 (MV)
            dt: 采样周期
            
        Returns:
            dict: {L, confidence, correlation_peak}
        """
        if len(y) < 20 or len(u) < 20:
            return {'L': 0.0, 'confidence': 0.0, 'correlation_peak': 0.0}
        
        # 去均值
        y_centered = y - np.mean(y)
        u_centered = u - np.mean(u)
        
        # 归一化
        y_std = np.std(y_centered)
        u_std = np.std(u_centered)
        
        if y_std < cls.EPSILON or u_std < cls.EPSILON:
            return {'L': 0.0, 'confidence': 0.0, 'correlation_peak': 0.0}
        
        y_norm = y_centered / y_std
        u_norm = u_centered / u_std
        
        # 互相关
        correlation = signal.correlate(y_norm, u_norm, mode='full')
        lags = signal.correlation_lags(len(y_norm), len(u_norm), mode='full')
        
        # 归一化相关系数
        correlation = correlation / len(y_norm)
        
        # 只考虑非负滞后（因果系统）
        non_negative_mask = lags >= 0
        positive_lags = lags[non_negative_mask]
        positive_corr = correlation[non_negative_mask]
        
        if len(positive_corr) == 0:
            return {'L': 0.0, 'confidence': 0.0, 'correlation_peak': 0.0}
        
        # 找峰值
        peak_idx = np.argmax(np.abs(positive_corr))
        L_samples = positive_lags[peak_idx]
        L = L_samples * dt
        
        # 置信度基于峰值高度
        peak_value = abs(positive_corr[peak_idx])
        confidence = min(1.0, peak_value)
        
        return {
            'L': float(L),
            'confidence': float(confidence),
            'correlation_peak': float(peak_value)
        }
    
    @classmethod
    def estimate_gain_by_spectrum(cls, y: np.ndarray, u: np.ndarray,
                                   dt: float = 1.0) -> Dict:
        """
        使用频谱分析估计系统增益
        
        原理：在低频段，系统增益 K ≈ |Y(jω)| / |U(jω)|
        """
        if len(y) < 20 or len(u) < 20:
            return {'K': 1.0, 'confidence': 0.0}
        
        # FFT
        n = len(y)
        y_fft = fft(y - np.mean(y))
        u_fft = fft(u - np.mean(u))
        freqs = fftfreq(n, dt)
        
        # 只取正频率的低频部分（前10%）
        positive_mask = freqs > 0
        positive_freqs = freqs[positive_mask]
        y_fft_pos = y_fft[positive_mask]
        u_fft_pos = u_fft[positive_mask]
        
        if len(positive_freqs) < 5:
            return {'K': 1.0, 'confidence': 0.0}
        
        # 取低频部分（低于5%奈奎斯特频率）
        nyquist = 0.5 / dt
        low_freq_mask = positive_freqs < 0.05 * nyquist
        
        if np.sum(low_freq_mask) < 3:
            # 数据太短，取前几个频率点
            low_freq_mask = np.zeros_like(positive_freqs, dtype=bool)
            low_freq_mask[:min(5, len(positive_freqs))] = True
        
        y_low = y_fft_pos[low_freq_mask]
        u_low = u_fft_pos[low_freq_mask]
        
        # 过滤掉输入幅度太小的频率
        u_mag = np.abs(u_low)
        valid_mask = u_mag > np.max(u_mag) * 0.1
        
        if np.sum(valid_mask) < 1:
            return {'K': 1.0, 'confidence': 0.0}
        
        # 增益 = |Y| / |U|
        y_valid = y_low[valid_mask]
        u_valid = u_low[valid_mask]
        
        gains = np.abs(y_valid) / (np.abs(u_valid) + cls.EPSILON)
        K = float(np.median(gains))
        
        # 置信度基于增益估计的一致性
        if len(gains) > 1:
            cv = np.std(gains) / (np.mean(gains) + cls.EPSILON)
            confidence = max(0, 1 - cv)
        else:
            confidence = 0.5
        
        return {
            'K': K,
            'confidence': float(confidence)
        }
    
    @classmethod
    def estimate_time_constant_by_bandwidth(cls, y: np.ndarray, u: np.ndarray,
                                             dt: float = 1.0) -> Dict:
        """
        使用带宽法估计时间常数
        
        原理：一阶系统的带宽 ω_bw = 1/T1，对应幅度衰减到0.707(-3dB)
        """
        if len(y) < 20 or len(u) < 20:
            return {'T1': 10.0, 'confidence': 0.0}
        
        n = len(y)
        y_fft = fft(y - np.mean(y))
        u_fft = fft(u - np.mean(u))
        freqs = fftfreq(n, dt)
        
        # 正频率
        positive_mask = freqs > 0
        positive_freqs = freqs[positive_mask]
        y_fft_pos = y_fft[positive_mask]
        u_fft_pos = u_fft[positive_mask]
        
        if len(positive_freqs) < 5:
            return {'T1': 10.0, 'confidence': 0.0}
        
        # 计算频率响应（传递函数估计）
        u_mag = np.abs(u_fft_pos)
        valid_mask = u_mag > np.max(u_mag) * 0.05
        
        if np.sum(valid_mask) < 3:
            return {'T1': 10.0, 'confidence': 0.0}
        
        H_mag = np.abs(y_fft_pos[valid_mask]) / (u_mag[valid_mask] + cls.EPSILON)
        valid_freqs = positive_freqs[valid_mask]
        
        # DC增益（低频增益）
        dc_gain = np.mean(H_mag[:max(1, len(H_mag)//10)])
        
        if dc_gain < cls.EPSILON:
            return {'T1': 10.0, 'confidence': 0.0}
        
        # 归一化后找-3dB点
        H_norm = H_mag / dc_gain
        
        # 寻找H降到0.707的频率
        for i in range(len(H_norm) - 1):
            if H_norm[i] >= 0.707 and H_norm[i+1] < 0.707:
                # 插值
                alpha = (0.707 - H_norm[i]) / (H_norm[i+1] - H_norm[i] + cls.EPSILON)
                omega_bw = 2 * np.pi * (valid_freqs[i] + alpha * (valid_freqs[i+1] - valid_freqs[i]))
                T1 = 1.0 / (omega_bw + cls.EPSILON)
                return {
                    'T1': float(max(T1, 1.0)),
                    'confidence': 0.7
                }
        
        # 未找到-3dB点，使用响应速度估计
        return {'T1': 10.0, 'confidence': 0.3}
    
    @classmethod
    def identify_fopdt(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> Optional[Dict]:
        """
        综合使用频域方法辨识FOPDT参数
        """
        if len(t) < 20:
            return None
        
        dt = (t[-1] - t[0]) / (len(t) - 1) if len(t) > 1 else 1.0
        
        # 估计各参数
        delay_result = cls.estimate_delay_by_correlation(y, u, dt)
        gain_result = cls.estimate_gain_by_spectrum(y, u, dt)
        tc_result = cls.estimate_time_constant_by_bandwidth(y, u, dt)
        
        # 综合置信度
        confidence = (delay_result['confidence'] * 0.4 + 
                     gain_result['confidence'] * 0.3 + 
                     tc_result['confidence'] * 0.3)
        
        return {
            'K': gain_result['K'],
            'T1': tc_result['T1'],
            'L': delay_result['L'],
            'method': 'frequency_domain',
            'confidence': float(confidence)
        }
    
    @classmethod
    def estimate_oscillation_frequency(cls, y: np.ndarray, dt: float = 1.0) -> Optional[Dict]:
        """
        估计主振荡频率
        
        用于临界法整定时获取Pu
        """
        if len(y) < 20:
            return None
        
        # 去趋势
        y_detrend = y - np.linspace(y[0], y[-1], len(y))
        
        # FFT
        n = len(y_detrend)
        y_fft = fft(y_detrend)
        freqs = fftfreq(n, dt)
        
        # 正频率部分
        positive_mask = freqs > 0
        positive_freqs = freqs[positive_mask]
        magnitude = np.abs(y_fft[positive_mask])
        
        if len(positive_freqs) < 3:
            return None
        
        # 找主频
        peak_idx = np.argmax(magnitude)
        dominant_freq = positive_freqs[peak_idx]
        
        if dominant_freq < cls.EPSILON:
            return None
        
        Pu = 1.0 / dominant_freq  # 临界周期
        
        # 置信度：主频能量占比
        total_energy = np.sum(magnitude**2)
        peak_energy = magnitude[peak_idx]**2
        confidence = peak_energy / (total_energy + cls.EPSILON)
        
        return {
            'Pu': float(Pu),
            'frequency': float(dominant_freq),
            'confidence': float(min(1.0, confidence * 2))  # 放大置信度
        }
