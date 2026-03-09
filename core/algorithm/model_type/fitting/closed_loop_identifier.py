"""
闭环辨识模块 (Closed-Loop Identification Module)
================================================

从闭环运行数据中反推开环过程模型参数 (K, T1, L)。

实现了三层混合辨识架构：
- Layer 1: CLHM 稳态增益反推 (K_ol = ΔSV / ΔMV_ss)
- Layer 2a: Yuwana-Seborg 法 (从超调+峰值时间反推 T1, L)
- Layer 2b: CLHM 解析法 (T1_ol = T1_cl × correction_factor)
- Layer 3: 交叉验证与融合

参考文献:
- Yuwana & Seborg (1982), "A new method for on-line controller tuning"
- Haalman (1966), "Adjusting controllers for a deadtime process"
- Skogestad (2003), "Simple analytic rules for model reduction and PID controller tuning"
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ClosedLoopResult:
    """闭环辨识结果"""
    K_ol: float            # 开环增益
    T1_ol: float           # 开环时间常数
    L_ol: float            # 开环延迟
    method: str            # 使用的方法
    confidence: float      # 置信度 (0~1)
    details: Dict          # 诊断细节


class ClosedLoopIdentifier:
    """
    闭环辨识器
    
    从闭环阶跃响应数据（SV阶跃 → PV/MV响应）+ 已知 PID 参数，
    反推开环 FOPDT 过程模型参数。
    """
    
    EPSILON = 1e-8
    CL_FACTOR_MAX = 15.0   # T1 修正因子上限（从原来的 6.0 放宽）
    CL_FACTOR_MIN = 1.5    # T1 修正因子下限
    
    def __init__(self, log_func=None):
        self._log = log_func or (lambda msg: None)
    
    def identify(self,
                 pv: np.ndarray,
                 sv: np.ndarray,
                 mv: np.ndarray,
                 timestamp: np.ndarray,
                 current_pid: Dict,
                 fitted_T1_cl: float,
                 fitted_L_cl: float) -> ClosedLoopResult:
        """
        主入口：三层闭环辨识
        
        Args:
            pv: 过程值序列
            sv: 设定值序列
            mv: 操作值序列
            timestamp: 时间戳 (ms)
            current_pid: 当前 PID 参数 {'Kp':..., 'Ki':..., 'Kd':...}
            fitted_K_cl: 拟合得到的闭环 K
            fitted_T1_cl: 拟合得到的闭环 T1
            fitted_L_cl: 拟合得到的闭环 L
            
        Returns:
            ClosedLoopResult
        """
        dt = (timestamp[1] - timestamp[0]) / 1000.0 if len(timestamp) > 1 else 1.0
        details = {}
        
        # 提取 PID 参数
        Kp = abs(current_pid.get('Kp', current_pid.get('kp', 0.0)))
        Ki = abs(current_pid.get('Ki', current_pid.get('ki', 0.0)))
        Ti = Kp / Ki if Ki > self.EPSILON else 600.0
        
        # =========================================
        # Layer 1: 稳态增益反推 (CLHM)
        # =========================================
        K_ol_layer1, k_confidence = self._estimate_open_loop_gain(
            pv, sv, mv, dt
        )
        details['layer1_K'] = K_ol_layer1
        details['layer1_confidence'] = k_confidence
        
        # =========================================
        # Layer 2: T1 和 L 修正
        # =========================================
        # 尝试 Yuwana-Seborg（需要超调）
        ys_result = self._yuwana_seborg(pv, sv, dt, K_ol_layer1, Kp, Ti)
        
        # CLHM 解析修正（始终可用）
        clhm_result = self._clhm_correction(
            fitted_T1_cl, fitted_L_cl, K_ol_layer1, Kp
        )
        
        # =========================================
        # Layer 3: 融合
        # =========================================
        K_ol, T1_ol, L_ol, method, confidence = self._fuse_results(
            K_ol_layer1, k_confidence,
            ys_result, clhm_result,
            fitted_T1_cl, fitted_L_cl
        )
        
        details['ys_result'] = ys_result
        details['clhm_result'] = clhm_result
        details['final_method'] = method
        
        self._log(f"   Layer 1 (CLHM增益): K_ol={K_ol_layer1:.4f} (置信={k_confidence:.2f})")
        if ys_result:
            self._log(f"   Layer 2a (YS法): T1={ys_result['T1']:.2f}s, L={ys_result['L']:.2f}s"
                      f" (超调={ys_result['overshoot']:.1%}, t_p={ys_result['t_peak']:.1f}s)")
        self._log(f"   Layer 2b (CLHM修正): T1={clhm_result['T1']:.2f}s"
                  f" (factor={clhm_result['factor']:.2f})")
        self._log(f"   Layer 3 (融合): K={K_ol:.4f}, T1={T1_ol:.2f}s, L={L_ol:.2f}s"
                  f" [{method}]")
        
        return ClosedLoopResult(
            K_ol=K_ol, T1_ol=T1_ol, L_ol=L_ol,
            method=method, confidence=confidence,
            details=details
        )
    
    # =================================================================
    # Layer 1: 稳态增益反推
    # =================================================================
    
    def _estimate_open_loop_gain(self,
                                  pv: np.ndarray,
                                  sv: np.ndarray,
                                  mv: np.ndarray,
                                  dt: float) -> Tuple[float, float]:
        """
        从 SV 阶跃数据中提取开环增益
        
        原理：PI 控制器下稳态 PV=SV，因此 K_ol = ΔSV / ΔMV_ss
        
        Returns:
            (K_ol, confidence)
        """
        n = len(pv)
        if n < 30:
            return 1.0, 0.0
        
        # 找到 SV 的阶跃点
        sv_diff = np.diff(sv)
        step_idx = np.argmax(np.abs(sv_diff))
        
        if abs(sv_diff[step_idx]) < 0.1:
            # 没有明显 SV 阶跃
            return 1.0, 0.0
        
        delta_sv = sv_diff[step_idx]
        
        # 稳态前后的 MV 值
        # 阶跃前: 取阶跃点之前的最后 20% 数据的平均值
        pre_window = max(5, min(step_idx, n // 5))
        mv_before = np.mean(mv[max(0, step_idx - pre_window):step_idx])
        
        # 阶跃后: 取最后 20% 数据的平均值（等待充分稳定）
        post_start = max(step_idx + 1, n - n // 5)
        mv_after = np.mean(mv[post_start:])
        pv_after = np.mean(pv[post_start:])
        
        delta_mv = mv_after - mv_before
        
        if abs(delta_mv) < self.EPSILON:
            # MV 没有变化 → 无法估计 K
            return 1.0, 0.0
        
        K_ol = delta_sv / delta_mv
        
        # 置信度评估：PV 是否真的追上了 SV？
        pv_error_ratio = abs(pv_after - sv[-1]) / (abs(delta_sv) + self.EPSILON)
        if pv_error_ratio < 0.05:
            confidence = 0.95  # PV 精确追踪 SV → 积分作用完全消除偏差
        elif pv_error_ratio < 0.15:
            confidence = 0.75
        elif pv_error_ratio < 0.30:
            confidence = 0.50
        else:
            confidence = 0.25  # PV 远未达到 SV → 可能是积分过程或未稳定
        
        # K 合理性约束
        K_ol = np.clip(K_ol, -20.0, 20.0)
        
        return float(K_ol), float(confidence)
    
    # =================================================================
    # Layer 2a: Yuwana-Seborg 法
    # =================================================================
    
    def _yuwana_seborg(self,
                        pv: np.ndarray,
                        sv: np.ndarray,
                        dt: float,
                        K_ol: float,
                        Kp: float,
                        Ti: float) -> Optional[Dict]:
        """
        Yuwana-Seborg 法：从闭环阶跃响应的超调量和峰值时间反推 T1, L
        
        适用条件：闭环响应有明显超调 (overshoot > 5%)
        
        Returns:
            {'T1': ..., 'L': ..., 'overshoot': ..., 't_peak': ..., 'confidence': ...}
            或 None（无超调时）
        """
        n = len(pv)
        if n < 30:
            return None
        
        # 找 SV 阶跃点
        sv_diff = np.diff(sv)
        step_idx = np.argmax(np.abs(sv_diff))
        delta_sv = sv_diff[step_idx]
        
        if abs(delta_sv) < 0.1:
            return None
        
        step_dir = np.sign(delta_sv)
        
        # 阶跃后的 PV 响应
        resp_pv = pv[step_idx + 1:]
        resp_n = len(resp_pv)
        if resp_n < 20:
            return None
        
        # 稳态值（最后 20% 平均）
        pv_final = np.mean(resp_pv[max(0, resp_n - resp_n // 5):])
        pv_initial = np.mean(pv[max(0, step_idx - 10):step_idx]) if step_idx > 5 else pv[0]
        
        # 寻找第一个峰值
        if step_dir > 0:
            peak_idx = np.argmax(resp_pv[:max(resp_n * 3 // 4, 20)])
            pv_peak = resp_pv[peak_idx]
        else:
            peak_idx = np.argmin(resp_pv[:max(resp_n * 3 // 4, 20)])
            pv_peak = resp_pv[peak_idx]
        
        # 计算超调量（归一化）
        if abs(pv_final - pv_initial) < self.EPSILON:
            return None
        
        overshoot = abs(pv_peak - pv_final) / abs(pv_final - pv_initial)
        
        # YS 法要求明显超调
        if overshoot < 0.05 or overshoot > 0.95:
            return None
        
        # 峰值时间（从阶跃到第一峰值）
        t_peak = peak_idx * dt
        if t_peak < dt * 2:  # 峰值太近 → 不可靠
            return None
        
        # ====== YS 核心公式 ======
        
        # 阻尼比
        ln_os = np.log(max(overshoot, 1e-6))
        zeta = -ln_os / np.sqrt(np.pi**2 + ln_os**2)
        zeta = np.clip(zeta, 0.05, 0.95)
        
        # 阻尼振荡频率和自然频率
        omega_d = np.pi / t_peak
        omega_n = omega_d / np.sqrt(max(1 - zeta**2, 0.01))
        
        # 从闭环特征方程反推 T1 和 L
        # 
        # 近似闭环传函：H(s) ≈ ωn²/(s² + 2ζωn·s + ωn²)
        # 
        # 对于 FOPDT + PI 闭环特征方程（一阶 Padé 近似延迟）:
        # T1·Ti·s³ + (Ti + T1·Ti·s·K·Kp/...)·s² + ... = 0
        #
        # 简化关系（Seborg 近似）:
        # 2ζ/ωn ≈ T1_ol/(1+K·Kp) + L_ol (阻尼时间 ≈ 闭环时间常数 + 延迟)
        # 1/ωn² ≈ T1_ol·L_ol/(1+K·Kp)  (频率平方反比 ≈ 时间常数×延迟的闭环版)
        
        K_abs = abs(K_ol) if abs(K_ol) > self.EPSILON else 1.0
        loop_gain = K_abs * Kp
        cl_factor = 1.0 + loop_gain
        
        # 从阻尼时间关系估计 T1 和 L
        damping_time = 2 * zeta / omega_n
        frequency_product = 1.0 / (omega_n**2)
        
        # T1_cl + L ≈ damping_time
        # T1_cl × L ≈ frequency_product
        # 其中 T1_cl = T1_ol / cl_factor
        # 解二次方程: x² - damping_time·x + frequency_product = 0
        discriminant = damping_time**2 - 4 * frequency_product
        
        if discriminant < 0:
            # 虚根 → 使用 CLHM 代替
            return None
        
        sqrt_disc = np.sqrt(discriminant)
        root1 = (damping_time + sqrt_disc) / 2
        root2 = (damping_time - sqrt_disc) / 2
        
        # 较大的根是 T1_cl，较小的是 L
        T1_cl_ys = max(root1, root2)
        L_ys = min(root1, root2)
        
        # 转换为开环参数
        T1_ol = T1_cl_ys * cl_factor
        L_ol = max(L_ys, 0.1)
        
        # 合理性检查
        T1_ol = np.clip(T1_ol, 0.5, 1000.0)
        L_ol = np.clip(L_ol, 0.0, 500.0)
        
        # 置信度（基于超调特征的清晰度）
        if 0.1 < overshoot < 0.7 and t_peak > dt * 5:
            ys_confidence = 0.85
        elif 0.05 < overshoot < 0.8:
            ys_confidence = 0.60
        else:
            ys_confidence = 0.35
        
        return {
            'T1': float(T1_ol),
            'L': float(L_ol),
            'overshoot': float(overshoot),
            't_peak': float(t_peak),
            'zeta': float(zeta),
            'omega_n': float(omega_n),
            'confidence': float(ys_confidence)
        }
    
    # =================================================================
    # Layer 2b: CLHM 解析修正（改进版）
    # =================================================================
    
    def _clhm_correction(self,
                          fitted_T1_cl: float,
                          fitted_L_cl: float,
                          K_ol: float,
                          Kp: float) -> Dict:
        """
        改进的 CLHM 解析修正
        
        核心公式: T1_ol = T1_cl × (1 + K_ol × Kp)
        改进点:
        - 使用 Layer 1 计算的精确 K_ol（而非拟合的 K_cl）
        - 修正因子上限从 6.0 放宽到 15.0
        """
        K_abs = abs(K_ol) if abs(K_ol) > self.EPSILON else 1.0
        loop_gain = K_abs * Kp
        
        # 修正因子
        factor = 1.0 + loop_gain
        factor = np.clip(factor, self.CL_FACTOR_MIN, self.CL_FACTOR_MAX)
        
        T1_ol = fitted_T1_cl * factor
        L_ol = fitted_L_cl  # L 近似不变
        
        return {
            'T1': float(T1_ol),
            'L': float(L_ol),
            'factor': float(factor),
            'loop_gain': float(loop_gain),
            'confidence': 0.50  # CLHM 是后处理方法，置信度中等
        }
    
    # =================================================================
    # Layer 3: 融合
    # =================================================================
    
    def _fuse_results(self,
                       K_ol: float,
                       k_confidence: float,
                       ys_result: Optional[Dict],
                       clhm_result: Dict,
                       fitted_T1_cl: float,
                       fitted_L_cl: float) -> Tuple[float, float, float, str, float]:
        """
        融合 YS 和 CLHM 结果
        
        Returns:
            (K_ol, T1_ol, L_ol, method, confidence)
        """
        # K 值以 Layer 1 为准（如果置信度足够）
        if k_confidence < 0.25:
            # Layer 1 不可靠 → 使用 CLHM 默认
            K_final = K_ol  # 仍然使用，但降低整体置信度
        else:
            K_final = K_ol
        
        # T1 和 L 的融合
        if ys_result is not None and ys_result['confidence'] > 0.5:
            # YS 可用且置信度高
            if clhm_result['confidence'] > 0.3:
                # 两者都可用 → 交叉验证
                t1_diff_ratio = abs(ys_result['T1'] - clhm_result['T1']) / (
                    max(ys_result['T1'], clhm_result['T1']) + self.EPSILON
                )
                
                if t1_diff_ratio < 0.30:
                    # 一致性好 → 加权平均（YS 权重高）
                    ys_weight = 0.7
                    T1_final = ys_weight * ys_result['T1'] + (1 - ys_weight) * clhm_result['T1']
                    L_final = ys_weight * ys_result['L'] + (1 - ys_weight) * clhm_result['L']
                    method = "YS+CLHM_fused"
                    confidence = 0.85
                else:
                    # 差异大 → 取更保守的（T1 更大的）
                    if ys_result['T1'] > clhm_result['T1']:
                        T1_final = ys_result['T1']
                        L_final = ys_result['L']
                        method = "YS_conservative"
                    else:
                        T1_final = clhm_result['T1']
                        L_final = clhm_result['L']
                        method = "CLHM_conservative"
                    confidence = 0.55
            else:
                # 仅 YS
                T1_final = ys_result['T1']
                L_final = ys_result['L']
                method = "YS_only"
                confidence = ys_result['confidence']
        else:
            # YS 不可用 → 使用 CLHM
            T1_final = clhm_result['T1']
            L_final = clhm_result['L']
            method = "CLHM_only"
            confidence = clhm_result['confidence']
        
        # 综合置信度
        overall_confidence = confidence * (0.5 + 0.5 * k_confidence)
        
        return K_final, T1_final, L_final, method, overall_confidence
