"""
阶跃响应辨识模块 (Step Response Identifier)
==========================================

基于阶跃响应的模型参数辨识方法。

方法说明
--------
1. **63%法**: 响应达到稳态值63.2%处的时间 = 时间常数T1
2. **面积法**: 归一化响应曲线下面积 = T1（对噪声不敏感）
3. **两点法**: 28.3%和63.2%处时间比 → 分离T1/T2（可辨识二阶系统）

适用场景
--------
- 有明显阶跃输入的数据段
- step_response_score > 0.5
"""

import numpy as np
from typing import Dict, Optional


class StepResponseIdentifier:
    """阶跃响应辨识器"""
    
    EPSILON = 1e-9
    
    @staticmethod
    def detect_step_input(u: np.ndarray, threshold: float = 0.1) -> Optional[Dict]:
        """
        检测MV中的阶跃输入
        
        Returns:
            dict: {step_idx, step_size, direction, quality} 或 None
        """
        if len(u) < 20:
            return None
        
        u_range = np.ptp(u)
        if u_range < threshold:
            return None
        
        # 寻找最大变化点
        u_diff = np.diff(u)
        step_idx = int(np.argmax(np.abs(u_diff)))
        step_size = u_diff[step_idx]
        
        # 质量评估：阶跃前后是否稳定
        pre_std = np.std(u[:max(5, step_idx)]) if step_idx > 5 else np.std(u[:step_idx+1])
        post_std = np.std(u[step_idx+1:min(step_idx+20, len(u))]) if step_idx+20 < len(u) else np.std(u[step_idx+1:])
        
        # 阶跃幅度相对于噪声的信噪比
        avg_std = (pre_std + post_std) / 2 + StepResponseIdentifier.EPSILON
        snr = abs(step_size) / avg_std
        
        quality = min(1.0, snr / 5.0)  # SNR >= 5 认为是高质量阶跃
        
        if quality < 0.3:  # 阶跃不够明显
            return None
        
        return {
            'step_idx': step_idx,
            'step_size': step_size,
            'direction': 1 if step_size > 0 else -1,
            'quality': quality,
            'u_before': np.mean(u[:step_idx+1]),
            'u_after': np.mean(u[step_idx+1:])
        }
    
    @classmethod
    def identify_by_63_percent(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                                step_info: Optional[Dict] = None) -> Optional[Dict]:
        """
        63%法辨识FOPDT参数
        
        原理：一阶系统阶跃响应在 t=T1 时达到稳态值的63.2%
        
        Returns:
            dict: {K, T1, L, method, confidence}
        """
        if step_info is None:
            step_info = cls.detect_step_input(u)
        
        if step_info is None:
            return None
        
        step_idx = step_info['step_idx']
        u_change = step_info['u_after'] - step_info['u_before']
        
        if abs(u_change) < cls.EPSILON:
            return None
        
        # 提取阶跃响应部分
        y_response = y[step_idx:]
        t_response = t[step_idx:] - t[step_idx]
        
        if len(y_response) < 10:
            return None
        
        # 计算稳态增益K
        y_initial = np.mean(y[:step_idx+1]) if step_idx > 0 else y[0]
        y_final = np.mean(y[-min(20, len(y)//5):])  # 取最后部分作为稳态
        y_change = y_final - y_initial
        K = y_change / u_change
        
        # 归一化响应
        if abs(y_change) < cls.EPSILON:
            return None
        
        y_normalized = (y_response - y_initial) / y_change
        
        # 寻找63.2%点
        target_63 = 0.632
        crossing_idx = None
        for i in range(len(y_normalized) - 1):
            if (y_normalized[i] - target_63) * (y_normalized[i+1] - target_63) <= 0:
                # 线性插值
                if abs(y_normalized[i+1] - y_normalized[i]) > cls.EPSILON:
                    alpha = (target_63 - y_normalized[i]) / (y_normalized[i+1] - y_normalized[i])
                    crossing_idx = i + alpha
                else:
                    crossing_idx = i
                break
        
        if crossing_idx is None:
            # 未达到63%，可能还在上升
            return None
        
        # 估计滞后时间L：响应开始明显变化的时间
        L = cls._estimate_delay(t_response, y_normalized)
        
        # 时间常数 = 63%时间 - 滞后
        dt = (t_response[-1] - t_response[0]) / (len(t_response) - 1) if len(t_response) > 1 else 1.0
        T1 = crossing_idx * dt - L
        T1 = max(T1, 1.0)  # 确保T1 > 0
        
        # 置信度基于阶跃质量
        confidence = step_info['quality'] * 0.8
        
        return {
            'K': float(K),
            'T1': float(T1),
            'L': float(max(L, 0)),
            'method': 'step_63_percent',
            'confidence': float(confidence)
        }
    
    @classmethod
    def identify_by_area(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                          step_info: Optional[Dict] = None) -> Optional[Dict]:
        """
        面积法辨识FOPDT参数
        
        原理：归一化阶跃响应曲线与最终稳态之间的面积等于时间常数T1
        
        优点：对噪声不敏感，使用积分平滑噪声
        """
        if step_info is None:
            step_info = cls.detect_step_input(u)
        
        if step_info is None:
            return None
        
        step_idx = step_info['step_idx']
        u_change = step_info['u_after'] - step_info['u_before']
        
        if abs(u_change) < cls.EPSILON:
            return None
        
        # 提取响应
        y_response = y[step_idx:]
        t_response = t[step_idx:] - t[step_idx]
        
        if len(y_response) < 10:
            return None
        
        # 计算K
        y_initial = np.mean(y[:step_idx+1]) if step_idx > 0 else y[0]
        y_final = np.mean(y[-min(20, len(y)//5):])
        y_change = y_final - y_initial
        K = y_change / u_change
        
        if abs(y_change) < cls.EPSILON:
            return None
        
        # 归一化响应
        y_normalized = (y_response - y_initial) / y_change
        
        # 面积法：T1 = ∫(1 - y_norm)dt
        # 这是响应曲线与稳态线之间的面积
        area = np.trapz(1 - y_normalized, t_response)
        
        # 估计滞后
        L = cls._estimate_delay(t_response, y_normalized)
        
        # T1 = 面积 - L（面积包含了滞后部分）
        T1 = area - L
        T1 = max(T1, 1.0)
        
        # 置信度
        confidence = step_info['quality'] * 0.85  # 面积法略优于63%法
        
        return {
            'K': float(K),
            'T1': float(T1),
            'L': float(max(L, 0)),
            'method': 'step_area',
            'confidence': float(confidence)
        }
    
    @classmethod
    def identify_by_two_point(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                               step_info: Optional[Dict] = None) -> Optional[Dict]:
        """
        两点法辨识SOPDT参数
        
        原理：利用响应曲线上28.3%和63.2%两点的时间，可分离两个时间常数
        
        对于二阶系统 G(s) = K/((T1s+1)(T2s+1))*e^(-Ls)：
        - t_28 ≈ 0.357*T1 + 0.357*T2 + L
        - t_63 ≈ T1 + 0.357*T2 + L
        
        由此可解出 T1 和 T2
        """
        if step_info is None:
            step_info = cls.detect_step_input(u)
        
        if step_info is None:
            return None
        
        step_idx = step_info['step_idx']
        u_change = step_info['u_after'] - step_info['u_before']
        
        if abs(u_change) < cls.EPSILON:
            return None
        
        y_response = y[step_idx:]
        t_response = t[step_idx:] - t[step_idx]
        
        if len(y_response) < 20:
            return None
        
        # 计算K
        y_initial = np.mean(y[:step_idx+1]) if step_idx > 0 else y[0]
        y_final = np.mean(y[-min(20, len(y)//5):])
        y_change = y_final - y_initial
        K = y_change / u_change
        
        if abs(y_change) < cls.EPSILON:
            return None
        
        y_normalized = (y_response - y_initial) / y_change
        
        # 找28.3%和63.2%点
        t_28 = cls._find_crossing_time(t_response, y_normalized, 0.283)
        t_63 = cls._find_crossing_time(t_response, y_normalized, 0.632)
        
        if t_28 is None or t_63 is None:
            return None
        
        # 估计滞后
        L = cls._estimate_delay(t_response, y_normalized)
        
        # 两点法公式
        # t_28 - L ≈ 0.357*(T1 + T2)
        # t_63 - L ≈ T1 + 0.357*T2
        # 解方程组
        sum_T = (t_28 - L) / 0.357
        
        # 假设 T1 >= T2，则 T1 ≈ t_63 - L - 0.357*T2
        # 代入得 T1 + T2 = sum_T
        # T1 = (t_63 - L) - 0.357*T2
        # T1 + T2 = sum_T => (t_63 - L) - 0.357*T2 + T2 = sum_T
        # 0.643*T2 = sum_T - (t_63 - L)
        T2 = (sum_T - (t_63 - L)) / 0.643
        T1 = sum_T - T2
        
        # 确保 T1 >= T2 > 0
        T1, T2 = max(abs(T1), 1.0), max(abs(T2), 0.5)
        if T1 < T2:
            T1, T2 = T2, T1
        
        confidence = step_info['quality'] * 0.7  # 两点法对噪声敏感
        
        return {
            'K': float(K),
            'T1': float(T1),
            'T2': float(T2),
            'L': float(max(L, 0)),
            'method': 'step_two_point',
            'confidence': float(confidence)
        }
    
    @staticmethod 
    def _estimate_delay(t: np.ndarray, y_norm: np.ndarray, threshold: float = 0.05) -> float:
        """估计纯滞后时间"""
        # 找到响应开始明显变化的点
        for i in range(len(y_norm)):
            if abs(y_norm[i]) > threshold:
                # 线性外推到0
                if i > 0 and abs(y_norm[i] - y_norm[i-1]) > 1e-9:
                    L = t[i-1] + (0 - y_norm[i-1]) / (y_norm[i] - y_norm[i-1]) * (t[i] - t[i-1])
                    return max(L, 0)
                return t[i]
        return 0.0
    
    @staticmethod
    def _find_crossing_time(t: np.ndarray, y_norm: np.ndarray, target: float) -> Optional[float]:
        """找到归一化响应达到目标值的时间"""
        for i in range(len(y_norm) - 1):
            if (y_norm[i] - target) * (y_norm[i+1] - target) <= 0:
                if abs(y_norm[i+1] - y_norm[i]) > 1e-9:
                    alpha = (target - y_norm[i]) / (y_norm[i+1] - y_norm[i])
                    return t[i] + alpha * (t[i+1] - t[i])
                return t[i]
        return None
    
    @classmethod
    def identify_fopdt(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> Optional[Dict]:
        """
        综合使用多种阶跃响应法辨识FOPDT，取最可信结果
        """
        step_info = cls.detect_step_input(u)
        if step_info is None:
            return None
        
        results = []
        
        # 尝试63%法
        r63 = cls.identify_by_63_percent(t, y, u, step_info)
        if r63:
            results.append(r63)
        
        # 尝试面积法
        r_area = cls.identify_by_area(t, y, u, step_info)
        if r_area:
            results.append(r_area)
        
        if not results:
            return None
        
        # 选择置信度最高的
        best = max(results, key=lambda x: x['confidence'])
        return best
    
    @classmethod
    def identify_sopdt(cls, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> Optional[Dict]:
        """
        使用两点法辨识SOPDT
        """
        return cls.identify_by_two_point(t, y, u)
