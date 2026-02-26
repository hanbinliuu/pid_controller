"""
稳定性分析器 (Stability Analyzer)
=================================

计算闭环系统的增益裕度和相位裕度，确保整定后的 PID 参数满足稳定性约束。

稳定性裕度
----------
- **增益裕度 (GM)**: 开环增益可增加多少倍系统仍稳定
    - 典型要求: GM > 2 (6dB)
- **相位裕度 (PM)**: 开环相位可减少多少度系统仍稳定  
    - 典型要求: PM > 45°

计算方法
--------
对于 FOPDT + PI 控制器，使用解析近似公式 (Åström-Hägglund)

参考
----
Åström, K. J., & Hägglund, T. (2006). Advanced PID Control.
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class StabilityMargins:
    """稳定性裕度结果"""
    gain_margin: float  # 增益裕度 (倍数)
    gain_margin_db: float  # 增益裕度 (dB)
    phase_margin: float  # 相位裕度 (度)
    crossover_freq: float  # 穿越频率 (rad/s)
    is_stable: bool  # 是否满足稳定性要求
    

class StabilityAnalyzer:
    """
    稳定性分析器
    
    计算 PID 控制系统的增益裕度和相位裕度
    """
    
    # 默认稳定性要求
    MIN_GAIN_MARGIN = 2.0  # 最小增益裕度 (倍数)
    MIN_PHASE_MARGIN = 45.0  # 最小相位裕度 (度)
    
    EPSILON = 1e-9
    
    @classmethod
    def calculate_margins_fopdt_pi(cls, K: float, T1: float, L: float,
                                    Kp: float, Ti: float) -> StabilityMargins:
        """
        计算 FOPDT + PI 控制器的稳定性裕度
        
        开环传递函数：
        L(s) = Kp * (1 + 1/(Ti*s)) * K*e^(-L*s) / (T1*s + 1)
        
        使用解析近似公式
        """
        # 穿越频率近似 (相位穿越)
        # 在穿越频率处 |L(jω)| = 1
        # 近似: ωc ≈ 1 / sqrt(Ti * T1)
        if Ti < cls.EPSILON or T1 < cls.EPSILON:
            Ti = max(Ti, 1.0)
            T1 = max(T1, 1.0)
        
        omega_c = 1.0 / np.sqrt(Ti * T1)
        
        # 开环增益
        K_open = abs(Kp * K)
        
        # 增益裕度计算
        # 在相位为 -180° 时的增益
        # 对于 FOPDT + PI，相位 = -90° - atan(ωT1) - ωL
        # 解 -90° - atan(ω_gm * T1) - ω_gm * L * 180/π = -180°
        # 即 atan(ω_gm * T1) + ω_gm * L * 180/π = 90°
        
        # 使用Newton-Raphson求解相位穿越频率
        omega_gm = cls._find_phase_crossover(T1, L, Ti)
        
        if omega_gm > cls.EPSILON:
            # 在相位穿越频率处的开环增益
            mag_gm = K_open * np.sqrt(1 + 1/(omega_gm * Ti)**2) / np.sqrt(1 + (omega_gm * T1)**2)
            gain_margin = 1.0 / (mag_gm + cls.EPSILON)
        else:
            gain_margin = 10.0  # 很大的裕度
        
        # 相位裕度计算
        # 在增益穿越频率处的相位
        omega_gc = cls._find_gain_crossover(K, T1, L, Kp, Ti)
        
        if omega_gc > cls.EPSILON:
            # PI 控制器相位: -90° + atan(ω*Ti)
            phase_pi = -90 + np.degrees(np.arctan(omega_gc * Ti))
            # FOPDT 相位: -atan(ω*T1) - ω*L * 180/π
            phase_fopdt = -np.degrees(np.arctan(omega_gc * T1)) - omega_gc * L * 180 / np.pi
            # 总相位
            total_phase = phase_pi + phase_fopdt
            phase_margin = 180 + total_phase
        else:
            phase_margin = 90.0  # 默认
        
        # 裕度约束检查
        is_stable = (gain_margin >= cls.MIN_GAIN_MARGIN and 
                    phase_margin >= cls.MIN_PHASE_MARGIN)
        
        return StabilityMargins(
            gain_margin=float(max(gain_margin, 0.1)),
            gain_margin_db=float(20 * np.log10(max(gain_margin, 0.1))),
            phase_margin=float(np.clip(phase_margin, -180, 180)),
            crossover_freq=float(omega_gc),
            is_stable=is_stable
        )
    
    @classmethod
    def calculate_margins_fopdt_pid(cls, K: float, T1: float, L: float,
                                     Kp: float, Ti: float, Td: float) -> StabilityMargins:
        """
        计算 FOPDT + PID 控制器的稳定性裕度
        """
        # PID 比 PI 复杂，使用频率响应数值计算
        return cls._calculate_margins_numerical(K, T1, 0, L, Kp, Ti, Td)
    
    @classmethod
    def _find_phase_crossover(cls, T1: float, L: float, Ti: float,
                               max_iter: int = 20) -> float:
        """
        寻找相位穿越频率 (相位 = -180°)
        """
        # 初始猜测
        omega = np.pi / (2 * L) if L > cls.EPSILON else 1.0 / T1
        
        for _ in range(max_iter):
            # 相位函数: φ(ω) = -90 + atan(ω*Ti) - atan(ω*T1) - ω*L*180/π + 180
            # 我们要找 φ(ω) = 0
            phase = (-90 + np.degrees(np.arctan(omega * Ti)) 
                    - np.degrees(np.arctan(omega * T1)) 
                    - omega * L * 180 / np.pi + 180)
            
            if abs(phase) < 0.1:
                return omega
            
            # 梯度下降
            delta = 0.01 * omega
            phase_plus = (-90 + np.degrees(np.arctan((omega + delta) * Ti))
                         - np.degrees(np.arctan((omega + delta) * T1))
                         - (omega + delta) * L * 180 / np.pi + 180)
            
            gradient = (phase_plus - phase) / delta
            if abs(gradient) > cls.EPSILON:
                omega = omega - phase / gradient
                omega = max(omega, cls.EPSILON)
        
        return omega
    
    @classmethod
    def _find_gain_crossover(cls, K: float, T1: float, L: float,
                              Kp: float, Ti: float,
                              max_iter: int = 60) -> float:
        """
        寻找增益穿越频率 (|L(jω)| = 1)

        改用严格二分法：
        1. 先在对数空间扫描 [1e-3, 100] 找到包围 |L|=1 的区间 [ω_lo, ω_hi]
        2. 对该区间做标准二分，确保收敛
        3. 若找不到包围区间（系统在所有频率下增益均 <1 或均 >1），
           返回 0.0 以触发调用方的安全兜底（phase_margin = 90°）
        """
        K_open = abs(Kp * K)

        if K_open < cls.EPSILON:
            return 0.1

        def _mag(w: float) -> float:
            pi_mag = np.sqrt(1.0 + 1.0 / (w * Ti + cls.EPSILON) ** 2)
            fopdt_mag = K / np.sqrt(1.0 + (w * T1) ** 2)
            return abs(Kp) * pi_mag * fopdt_mag

        # --- Step 1: 扫描对数空间，找包围区间 ---
        omega_scan = np.logspace(-3, 2, 200)
        mag_scan = np.array([_mag(w) for w in omega_scan])
        diff_sign = np.diff(np.sign(mag_scan - 1.0))
        crossover_indices = np.where(diff_sign != 0)[0]

        if len(crossover_indices) == 0:
            # 系统在整个频率范围内增益始终 <1 或始终 >1，无穿越频率
            # 返回 0.0，调用方对 omega_gc <= EPSILON 已有兜底（phase_margin = 90°）
            return 0.0

        # 取最低频率的穿越点（通常是主穿越频率）
        idx = crossover_indices[0]
        w_lo, w_hi = float(omega_scan[idx]), float(omega_scan[idx + 1])

        # --- Step 2: 标准二分法收敛 ---
        for _ in range(max_iter):
            w_mid = (w_lo + w_hi) / 2.0
            mag_mid = _mag(w_mid)
            err = mag_mid - 1.0
            if abs(err) < 1e-4:
                return w_mid
            if (mag_scan[idx] - 1.0) * err > 0:
                w_lo = w_mid
            else:
                w_hi = w_mid

        # 二分法理论上必然收敛，此处作为最后防线
        return (w_lo + w_hi) / 2.0
    
    @classmethod
    def _calculate_margins_numerical(cls, K: float, T1: float, T2: float, L: float,
                                      Kp: float, Ti: float, Td: float) -> StabilityMargins:
        """
        数值方法计算稳定性裕度（适用于复杂系统）
        """
        # 频率扫描
        omega_range = np.logspace(-3, 2, 500)
        
        min_gain = float('inf')
        gm_omega = 0.0
        gc_omega = 0.0
        gc_phase = 0.0
        
        for omega in omega_range:
            s = 1j * omega
            
            # PID 控制器: Kp * (1 + 1/(Ti*s) + Td*s)
            if Ti > cls.EPSILON:
                C = Kp * (1 + 1/(Ti * s) + Td * s)
            else:
                C = Kp * (1 + Td * s)
            
            # FOPDT/SOPDT 过程
            if T2 > cls.EPSILON:
                G = K / ((T1 * s + 1) * (T2 * s + 1)) * np.exp(-L * s)
            else:
                G = K / (T1 * s + 1) * np.exp(-L * s)
            
            # 开环传递函数
            L_s = C * G
            
            mag = abs(L_s)
            phase = np.angle(L_s, deg=True)
            
            # 增益穿越频率 (|L| = 1)
            if abs(mag - 1.0) < 0.1:
                gc_omega = omega
                gc_phase = phase
            
            # 相位穿越频率 (phase = -180°)
            if abs(phase + 180) < 10 and mag < min_gain:
                min_gain = mag
                gm_omega = omega
        
        gain_margin = 1.0 / (min_gain + cls.EPSILON) if min_gain < float('inf') else 10.0
        phase_margin = 180 + gc_phase
        
        is_stable = (gain_margin >= cls.MIN_GAIN_MARGIN and 
                    phase_margin >= cls.MIN_PHASE_MARGIN)
        
        return StabilityMargins(
            gain_margin=float(np.clip(gain_margin, 0.1, 100)),
            gain_margin_db=float(20 * np.log10(np.clip(gain_margin, 0.1, 100))),
            phase_margin=float(np.clip(phase_margin, -180, 180)),
            crossover_freq=float(gc_omega),
            is_stable=is_stable
        )
    
    @classmethod
    def adjust_kp_for_margins(cls, K: float, T1: float, L: float,
                               Kp: float, Ti: float, Td: float = 0,
                               target_gm: float = None,
                               target_pm: float = None) -> Tuple[float, StabilityMargins]:
        """
        调整 Kp 使系统满足稳定性裕度要求
        
        Args:
            K, T1, L: 过程模型参数
            Kp, Ti, Td: 当前 PID 参数
            target_gm: 目标增益裕度
            target_pm: 目标相位裕度
            
        Returns:
            (adjusted_Kp, margins)
        """
        if target_gm is None:
            target_gm = cls.MIN_GAIN_MARGIN
        if target_pm is None:
            target_pm = cls.MIN_PHASE_MARGIN
        
        # 计算当前裕度
        if Td > cls.EPSILON:
            margins = cls.calculate_margins_fopdt_pid(K, T1, L, Kp, Ti, Td)
        else:
            margins = cls.calculate_margins_fopdt_pi(K, T1, L, Kp, Ti)
        
        if margins.is_stable:
            return Kp, margins
        
        # 需要调整 Kp
        # 增益裕度不足时，减小 Kp
        adjusted_Kp = Kp
        
        if margins.gain_margin < target_gm:
            # Kp 需要减小 target_gm / current_gm 倍
            reduction_factor = margins.gain_margin / target_gm
            adjusted_Kp *= reduction_factor * 0.9  # 留10%余量
        
        if margins.phase_margin < target_pm:
            # 相位裕度与 Kp 关系复杂，使用迭代调整
            for _ in range(10):
                adjusted_Kp *= 0.9
                if Td > cls.EPSILON:
                    new_margins = cls.calculate_margins_fopdt_pid(K, T1, L, adjusted_Kp, Ti, Td)
                else:
                    new_margins = cls.calculate_margins_fopdt_pi(K, T1, L, adjusted_Kp, Ti)
                
                if new_margins.phase_margin >= target_pm:
                    break
            margins = new_margins
        
        # 不要调整太多，保持至少原来的30%
        adjusted_Kp = max(adjusted_Kp, Kp * 0.3)
        
        return adjusted_Kp, margins
    
    @classmethod
    def check_stability(cls, model_params: Dict, pid_params: Dict) -> StabilityMargins:
        """
        检查 PID 参数的稳定性
        
        Args:
            model_params: {K, T1, T2, L}
            pid_params: {Kp, Ti, Td} 或 {pb, ti, td}
        """
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        T2 = model_params.get('T2', 0.0)
        L = model_params.get('L', 1.0)
        
        # 支持 pb/ti/td 格式
        if 'pb' in pid_params:
            Kp = 100.0 / pid_params['pb'] if pid_params['pb'] > 0 else 1.0
        else:
            Kp = pid_params.get('Kp', 1.0)
        
        Ti = pid_params.get('Ti', pid_params.get('ti', 10.0))
        Td = pid_params.get('Td', pid_params.get('td', 0.0))
        
        if T2 > 0.1:
            return cls._calculate_margins_numerical(K, T1, T2, L, Kp, Ti, Td)
        elif Td > 0.1:
            return cls.calculate_margins_fopdt_pid(K, T1, L, Kp, Ti, Td)
        else:
            return cls.calculate_margins_fopdt_pi(K, T1, L, Kp, Ti)
