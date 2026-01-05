"""
继电反馈辨识器 (Relay Feedback Identifier)
==========================================

从振荡数据（极限环）中自动辨识过程的临界参数。

原理
----
当系统在继电控制下产生极限环振荡时：
    Ku = 4 * d / (π * a)
    Pu = 振荡周期

其中：
- d: 继电器输出幅度
- a: 输出振荡幅度  
- Pu: 极限环周期

应用场景
--------
1. 从闭环振荡数据辨识过程参数
2. 当开环测试不可用时的替代方法
3. 在线自动整定

参考
----
Åström, K. J., & Hägglund, T. (1984). Automatic tuning of simple regulators.
"""

import numpy as np
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from scipy import signal


@dataclass
class RelayResult:
    """继电反馈辨识结果"""
    Ku: float  # 临界增益
    Pu: float  # 临界周期
    amplitude: float  # 振荡幅度
    confidence: float  # 置信度
    method: str = "relay_feedback"
    

@dataclass
class LimitCycleInfo:
    """极限环信息"""
    period: float  # 周期
    amplitude: float  # 幅度
    frequency: float  # 频率
    n_cycles: int  # 周期数
    regularity: float  # 规则性 (0-1)
    

class RelayIdentifier:
    """
    继电反馈辨识器
    
    从振荡数据中识别极限环，估计临界参数 Ku 和 Pu
    """
    
    EPSILON = 1e-9
    
    @classmethod
    def detect_limit_cycle(cls, y: np.ndarray, dt: float = 1.0,
                           min_periods: int = 2) -> Optional[LimitCycleInfo]:
        """
        检测信号中的极限环振荡
        
        Args:
            y: 输出信号 (PV)
            dt: 采样周期
            min_periods: 最少需要的完整周期数
            
        Returns:
            LimitCycleInfo 或 None
        """
        if len(y) < 20:
            return None
        
        # 去趋势
        y_detrend = signal.detrend(y)
        
        # 使用 FFT 寻找主频
        n = len(y_detrend)
        fft_result = np.fft.fft(y_detrend)
        freqs = np.fft.fftfreq(n, dt)
        
        # 只考虑正频率
        positive_mask = freqs > 0
        positive_freqs = freqs[positive_mask]
        magnitude = np.abs(fft_result[positive_mask])
        
        if len(positive_freqs) < 3:
            return None
        
        # 找主频
        peak_idx = np.argmax(magnitude)
        dominant_freq = positive_freqs[peak_idx]
        
        if dominant_freq < cls.EPSILON:
            return None
        
        period = 1.0 / dominant_freq
        
        # 计算周期数
        total_time = len(y) * dt
        n_cycles = int(total_time / period)
        
        if n_cycles < min_periods:
            return None
        
        # 计算振荡幅度（使用包络线）
        y_upper = cls._upper_envelope(y_detrend)
        y_lower = cls._lower_envelope(y_detrend)
        amplitude = (np.median(y_upper) - np.median(y_lower)) / 2
        
        # 规则性评估：主频能量占比
        total_energy = np.sum(magnitude**2)
        peak_energy = magnitude[peak_idx]**2
        
        # 考虑邻近频率
        if peak_idx > 0:
            peak_energy += magnitude[peak_idx - 1]**2
        if peak_idx < len(magnitude) - 1:
            peak_energy += magnitude[peak_idx + 1]**2
        
        regularity = peak_energy / (total_energy + cls.EPSILON)
        
        return LimitCycleInfo(
            period=float(period),
            amplitude=float(amplitude),
            frequency=float(dominant_freq),
            n_cycles=n_cycles,
            regularity=float(np.clip(regularity, 0, 1))
        )
    
    @classmethod
    def estimate_critical_params(cls, pv: np.ndarray, mv: np.ndarray,
                                  dt: float = 1.0) -> Optional[RelayResult]:
        """
        从极限环数据估计临界参数 Ku 和 Pu
        
        Args:
            pv: 过程输出 (PV)
            mv: 控制器输出 (MV)
            dt: 采样周期
            
        Returns:
            RelayResult 或 None
        """
        # 检测 PV 中的极限环
        limit_cycle = cls.detect_limit_cycle(pv, dt)
        
        if limit_cycle is None:
            return None
        
        if limit_cycle.regularity < 0.3:
            # 振荡不够规则
            return None
        
        # 获取 MV 振荡幅度
        mv_detrend = signal.detrend(mv)
        mv_amplitude = (np.max(mv_detrend) - np.min(mv_detrend)) / 2
        
        if mv_amplitude < cls.EPSILON:
            return None
        
        # 继电反馈公式: Ku = 4 * d / (π * a)
        # d = MV 幅度, a = PV 幅度
        Ku = 4 * mv_amplitude / (np.pi * limit_cycle.amplitude + cls.EPSILON)
        Pu = limit_cycle.period
        
        # 置信度基于规则性和周期数
        confidence = limit_cycle.regularity * min(1.0, limit_cycle.n_cycles / 3)
        
        return RelayResult(
            Ku=float(Ku),
            Pu=float(Pu),
            amplitude=float(limit_cycle.amplitude),
            confidence=float(confidence),
            method="relay_feedback"
        )
    
    @classmethod
    def identify_from_oscillation(cls, pv: np.ndarray, mv: np.ndarray,
                                   dt: float = 1.0) -> Optional[Dict]:
        """
        从振荡数据辨识 FOPDT 模型参数
        
        使用 Ziegler-Nichols 频率响应方法：
            Ku, Pu → K, T1, L
        """
        result = cls.estimate_critical_params(pv, mv, dt)
        
        if result is None:
            return None
        
        Ku = result.Ku
        Pu = result.Pu
        
        if Ku < cls.EPSILON or Pu < cls.EPSILON:
            return None
        
        # 从临界参数估计 FOPDT 参数 (Ziegler-Nichols 近似)
        # ωu = 2π/Pu (临界频率)
        omega_u = 2 * np.pi / Pu
        
        # 对于 FOPDT: G(jωu) = K*e^(-jωuL) / (1 + jωuT1)
        # 在穿越频率处相位 = -180°，增益 = 1/Ku
        
        # 假设 L/T1 ≈ 0.5 (中等滞后系统)
        # 相位条件: -atan(ωuT1) - ωuL = -π
        # 近似: T1 ≈ Pu / (2π) * 2 = Pu / π
        T1 = Pu / np.pi
        
        # 从相位条件估计 L
        # -atan(ωu*T1) - ωu*L = -π
        # L = (π - atan(ωu*T1)) / ωu
        L = (np.pi - np.arctan(omega_u * T1)) / omega_u
        L = max(L, 0.1)
        
        # 增益条件: K = sqrt(1 + (ωuT1)^2) / Ku
        K = np.sqrt(1 + (omega_u * T1)**2) / Ku
        
        return {
            'K': float(K),
            'T1': float(T1),
            'L': float(L),
            'Ku': float(Ku),
            'Pu': float(Pu),
            'confidence': float(result.confidence),
            'method': 'relay_feedback'
        }
    
    @classmethod
    def zn_from_critical(cls, Ku: float, Pu: float,
                          controller_type: str = 'PID') -> Dict:
        """
        从临界参数使用 Ziegler-Nichols 法计算 PID 参数
        
        Args:
            Ku: 临界增益
            Pu: 临界周期
            controller_type: 'P', 'PI', 或 'PID'
            
        Returns:
            {Kp, Ti, Td}
        """
        if controller_type == 'P':
            Kp = 0.5 * Ku
            Ti = float('inf')
            Td = 0.0
        elif controller_type == 'PI':
            Kp = 0.45 * Ku
            Ti = Pu / 1.2
            Td = 0.0
        else:  # PID
            Kp = 0.6 * Ku
            Ti = Pu / 2
            Td = Pu / 8
        
        return {
            'Kp': float(Kp),
            'Ti': float(max(Ti, 0.5)),
            'Td': float(Td),
            'method': f'ZN_{controller_type}'
        }
    
    @classmethod
    def conservative_from_critical(cls, Ku: float, Pu: float,
                                    safety_factor: float = 1.5) -> Dict:
        """
        保守版 ZN 法（用于工业应用）
        
        比标准 ZN 法更保守，减少超调
        """
        # 保守 PID: 降低 Kp, 增大 Ti
        Kp = 0.6 * Ku / safety_factor
        Ti = Pu / 2 * safety_factor
        Td = Pu / 8
        
        return {
            'Kp': float(Kp),
            'Ti': float(max(Ti, 0.5)),
            'Td': float(Td),
            'method': 'conservative_ZN'
        }
    
    @staticmethod
    def _upper_envelope(y: np.ndarray) -> np.ndarray:
        """计算上包络线"""
        from scipy.ndimage import maximum_filter1d
        window = max(5, len(y) // 20)
        return maximum_filter1d(y, size=window)
    
    @staticmethod
    def _lower_envelope(y: np.ndarray) -> np.ndarray:
        """计算下包络线"""
        from scipy.ndimage import minimum_filter1d
        window = max(5, len(y) // 20)
        return minimum_filter1d(y, size=window)
