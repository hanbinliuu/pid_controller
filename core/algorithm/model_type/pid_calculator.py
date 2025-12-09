"""PID参数计算模块"""

import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

from .config import Config, ModelType
from .models import FusionResult


@dataclass
class ClosedLoopMetrics:
    """闭环价统性能指标"""
    is_stable: bool              # 是否稳定
    settling_time: float         # 调节时间（进入±2%误差带）
    overshoot: float             # 超调量 (%)
    rise_time: float             # 上升时间（10%到90%）
    steady_state_error: float    # 稳态误差
    oscillation_count: int       # 振荡次数
    decay_ratio: float           # 衰减比
    pv_history: np.ndarray       # PV响应历史
    mv_history: np.ndarray       # MV输出历史


EPSILON = Config.EPSILON


class PIDCalculator:
    """PID参数计算器"""
    
    def __init__(self):
        self._epsilon = EPSILON
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float) -> Dict[str, float]:
        """
        计算PID参数（Lambda方法）
        
        Args:
            K: 增益（可为负，表示反向作用系统）
            T1: 时间常数1
            T2: 时间常数2
            L: 滞后时间
            model_type: 模型类型
            lambda_factor: Lambda整定系数
        
        Returns:
            PID参数字典 {Kp, Ki, Kd}，Kp符号与K一致
        """
        # 保留K的符号信息（反向作用系统K为负）
        K_sign = 1 if K >= 0 else -1
        K_abs = max(abs(K), self._epsilon)
        
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        lambda_val = T_eq * lambda_factor
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            denom = K_abs * (lambda_val + L / 2)
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = (T1 + L / 2) / denom
                Ti = T1 + L / 2
                Td = (T1 * L) / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            denom = K_abs * (lambda_val + L / 2) if L > 0 else K_abs * lambda_val
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = T_eq / denom
                Ti = T_eq
                Td = (T1 * T2) / T_eq if T_eq > self._epsilon else 0.0
        
        elif model_type == ModelType.FOPI:
            if K_abs < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                lv = max(T1 * 0.8, 0.2) if T1 > 0 else 0.2
                Kp = T1 / (K_abs * lv) if T1 > 0 else 1.0 / (K_abs * lv)
                Ti, Td = max(T1, 1.0), 0.0
        else:
            Kp, Ti, Td = 1.0, 20.0, 0.0
        
        # 应用K的符号到Kp（反向作用系统Kp为负）
        Kp = Kp * K_sign
        
        # 参数合理性约束
        # 1. 限制Kp的绝对值下限，但保留符号
        if abs(Kp) < 0.01:
            Kp = 0.01 * K_sign
        
        # 2. 限制Ti的上限（避免积分作用过弱导致响应过慢）
        Ti_max = 60.0  # 最大积分时间60秒
        Ti = max(0.1, min(Ti, Ti_max))
        
        # 3. 限制Td的上下限
        Td = max(0.0, min(Td, Ti / 4))  # Td 不超过 Ti/4
        
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        # 4. 确保Ki有足够的积分作用（避免响应过慢）
        Ki_min = abs(Kp) * 0.01  # Ki 至少是 |Kp| 的 1%
        if abs(Ki) < Ki_min:
            Ki = Ki_min * K_sign
        
        return {
            'Kp': round(float(Kp), 4),
            'Ki': round(float(Ki), 4),
            'Kd': round(float(Kd), 4)
        }
    
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float) -> Dict[str, float]:
        """从FusionResult计算PID参数"""
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor
        )
    
    def analyze_oscillation(self, pv: np.ndarray, mv: np.ndarray, 
                            dt: float = 1.0) -> Optional[Dict]:
        """
        分析振荡数据，提取临界振荡特征
        
        Args:
            pv: 过程变量数组
            mv: 操作变量数组
            dt: 采样周期（秒）
        
        Returns:
            振荡特征字典，如果无法分析则返回 None
        """
        if len(pv) < 10:
            return None
        
        # 去趋势
        pv_detrend = pv - np.mean(pv)
        
        # 1. 检测过零点，计算振荡周期
        zero_crossings = np.where(np.diff(np.sign(pv_detrend)))[0]
        
        if len(zero_crossings) < 4:
            return None  # 至少需要2个完整周期
        
        # 计算半周期，然后转换为全周期
        half_periods = np.diff(zero_crossings) * dt
        full_periods = []
        for i in range(0, len(half_periods) - 1, 2):
            full_periods.append(half_periods[i] + half_periods[i + 1])
        
        if len(full_periods) == 0:
            return None
        
        Pu = np.median(full_periods)  # 临界周期
        
        # 2. 计算振荡幅度
        peaks = []
        valleys = []
        for i in range(1, len(pv) - 1):
            if pv[i] > pv[i-1] and pv[i] > pv[i+1]:
                peaks.append(pv[i])
            elif pv[i] < pv[i-1] and pv[i] < pv[i+1]:
                valleys.append(pv[i])
        
        if len(peaks) < 2 or len(valleys) < 2:
            return None
        
        amplitude = (np.mean(peaks) - np.mean(valleys)) / 2  # 振荡幅度
        
        # 3. 计算衰减比（判断是否为临界振荡）
        if len(peaks) >= 3:
            decay_ratios = []
            for i in range(len(peaks) - 1):
                if peaks[i] != 0:
                    decay_ratios.append(peaks[i + 1] / peaks[i])
            avg_decay = np.mean(decay_ratios) if decay_ratios else 1.0
        else:
            avg_decay = 1.0
        
        # 4. 估算MV的等效继电器幅度
        mv_amplitude = (np.max(mv) - np.min(mv)) / 2
        
        # 5. 使用继电器反馈法估算临界增益
        # Ku = 4d / (π × a)，其中 d 是继电器幅度，a 是振荡幅度
        if amplitude > self._epsilon:
            Ku_estimate = 4 * mv_amplitude / (np.pi * amplitude)
        else:
            Ku_estimate = 1.0
        
        # 6. 判断振荡类型
        if avg_decay > 1.1:
            osc_type = 'diverging'  # 发散振荡
        elif avg_decay < 0.9:
            osc_type = 'converging'  # 收敛振荡
        else:
            osc_type = 'sustained'  # 持续振荡（临界状态）
        
        return {
            'Pu': round(Pu, 2),              # 临界周期
            'Ku': round(Ku_estimate, 4),     # 临界增益估计
            'amplitude': round(amplitude, 2), # 振荡幅度
            'mv_amplitude': round(mv_amplitude, 2),  # MV幅度
            'decay_ratio': round(avg_decay, 3),      # 衰减比
            'oscillation_type': osc_type,    # 振荡类型
            'n_cycles': len(full_periods),   # 完整振荡周期数
            'is_valid': len(full_periods) >= 2 and osc_type != 'diverging'
        }
    
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
            'Kp': round(float(Kp), 4),
            'Ki': round(float(Ki), 4),
            'Kd': round(float(Kd), 4),
            'method': f'oscillation_{method}',
            'Pu': Pu,
            'Ku': round(Ku, 4)
        }
    
    def calculate_model_rating(self, fusion: FusionResult, 
                                total_data_points: int,
                                cl_metrics: 'ClosedLoopMetrics' = None,
                                verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算综合模型评分 (0-10分)
        
        综合考虑以下维度：
        1. 拟合质量 (R²)        - 30%
        2. 参数一致性            - 20%
        3. 参数物理合理性        - 15%
        4. 数据覆盖度            - 10%
        5. 闭环稳定性            - 25%
        
        Returns:
            (model_rating, score_details)
        """
        score_details = {}
        
        # 1. 拟合质量评分 (0-10) - 权重 40%
        r2 = fusion.global_r2
        if r2 >= 0.95:
            r2_score = 10.0
        elif r2 >= 0.9:
            r2_score = 9.0 + (r2 - 0.9) * 20
        elif r2 >= 0.8:
            r2_score = 7.5 + (r2 - 0.8) * 15
        elif r2 >= 0.6:
            r2_score = 5.0 + (r2 - 0.6) * 12.5
        elif r2 >= 0.4:
            r2_score = 3.0 + (r2 - 0.4) * 10
        elif r2 >= 0.2:
            r2_score = 1.0 + (r2 - 0.2) * 10
        else:
            r2_score = r2 * 5
        score_details['r2_score'] = round(r2_score, 2)
        
        # 2. 参数一致性评分 (0-10) - 权重 25%
        consistency_score = 10.0
        
        if fusion.n_segments_used > 1:
            k_mean = abs(fusion.K) + self._epsilon
            k_cv = fusion.K_std / k_mean
            
            t1_mean = abs(fusion.T1) + self._epsilon
            t1_cv = fusion.T1_std / t1_mean
            
            k_consistency = max(0, 10 - k_cv * 15)
            t1_consistency = max(0, 10 - t1_cv * 15)
            
            consistency_score = 0.6 * k_consistency + 0.4 * t1_consistency
            
            if fusion.consistency_score > 0:
                consistency_score = 0.7 * consistency_score + 0.3 * (fusion.consistency_score * 10)
        else:
            if fusion.consistency_score > 0:
                consistency_score = fusion.consistency_score * 10
            else:
                consistency_score = 6.0
        
        consistency_score = min(10.0, max(0.0, consistency_score))
        score_details['consistency_score'] = round(consistency_score, 2)
        
        # 3. 参数物理合理性评分 (0-10) - 权重 20%
        validity_score = 10.0
        penalties = []
        
        K = fusion.K
        if abs(K) < 0.001:
            penalties.append(('K接近零', 4.0))
        elif abs(K) > 50:
            penalties.append(('K过大', 2.0))
        elif abs(K) < 0.01:
            penalties.append(('K过小', 1.0))
        
        T1 = fusion.T1
        if T1 <= 0:
            penalties.append(('T1非正', 5.0))
        elif T1 < 0.1:
            penalties.append(('T1过小', 2.0))
        elif T1 > 500:
            penalties.append(('T1过大', 1.5))
        
        L = fusion.L
        if L < 0:
            penalties.append(('L为负', 3.0))
        elif L > T1 * 2 and T1 > 0:
            penalties.append(('L过大', 1.0))
        
        T2 = fusion.T2
        if T2 < 0:
            penalties.append(('T2为负', 2.0))
        
        for reason, penalty in penalties:
            validity_score -= penalty
            if verbose:
                print(f"   参数检查: {reason}, 扣{penalty}分")
        
        validity_score = max(0.0, validity_score)
        score_details['validity_score'] = round(validity_score, 2)
        
        # 4. 数据覆盖度评分 (0-10) - 权重 15%
        n_segments = fusion.n_segments_used
        
        if n_segments >= 4:
            segment_score = 9.0 + min(1.0, (n_segments - 4) * 0.25)
        elif n_segments == 3:
            segment_score = 8.5
        elif n_segments == 2:
            segment_score = 7.0
        elif n_segments == 1:
            segment_score = 5.0
        else:
            segment_score = 0.0
        
        if total_data_points >= 500:
            data_score = 10.0
        elif total_data_points >= 200:
            data_score = 7.0 + (total_data_points - 200) / 100
        elif total_data_points >= 100:
            data_score = 5.0 + (total_data_points - 100) / 50
        elif total_data_points >= 50:
            data_score = 3.0 + (total_data_points - 50) / 25
        else:
            data_score = total_data_points / 50 * 3
        
        coverage_score = 0.6 * segment_score + 0.4 * data_score
        coverage_score = min(10.0, coverage_score)
        score_details['coverage_score'] = round(coverage_score, 2)
        score_details['n_segments'] = n_segments
        score_details['total_data_points'] = total_data_points
        
        # 5. 闭环稳定性评分 (0-10) - 权重 25%
        # 综合评估：overshoot, rise_time, steady_state_error, oscillation_count, decay_ratio
        stability_score = 5.0  # 默认中等分数
        
        if cl_metrics is not None:
            # 基础分：是否稳定
            if cl_metrics.is_stable:
                stability_score = 6.0
            else:
                stability_score = 1.0
            
            # 1. 超调量评分（越小越好，权重最高）
            overshoot = cl_metrics.overshoot
            if overshoot <= 5:
                stability_score += 1.5  # 优秀
            elif overshoot <= 15:
                stability_score += 1.0  # 良好
            elif overshoot <= 30:
                stability_score += 0.5  # 可接受
            elif overshoot <= 50:
                stability_score -= 0.5  # 较差
            else:
                stability_score -= 1.5  # 严重超调
            
            # 2. 上升时间评分（适中为好，太快太慢都不好）
            rise_time = cl_metrics.rise_time
            if rise_time < float('inf'):
                if 1.0 <= rise_time <= 10.0:
                    stability_score += 1.0  # 理想范围
                elif 0.5 <= rise_time < 1.0 or 10.0 < rise_time <= 20.0:
                    stability_score += 0.5  # 可接受
                elif rise_time < 0.5:
                    stability_score -= 0.5  # 太快，可能不稳定
                else:
                    stability_score -= 0.5  # 太慢
            
            # 3. 稳态误差评分（越小越好）
            sse = cl_metrics.steady_state_error
            if sse <= 1:
                stability_score += 1.0  # 优秀
            elif sse <= 2:
                stability_score += 0.5  # 良好
            elif sse <= 5:
                pass  # 可接受
            elif sse <= 10:
                stability_score -= 0.5  # 较差
            else:
                stability_score -= 1.0  # 严重偏差
            
            # 4. 振荡次数评分（越少越好）
            osc_count = cl_metrics.oscillation_count
            if osc_count == 0:
                stability_score += 0.5  # 无振荡，可能过阻尼
            elif osc_count <= 2:
                stability_score += 1.0  # 理想，轻微振荡后收敛
            elif osc_count <= 4:
                stability_score += 0.5  # 可接受
            elif osc_count <= 6:
                stability_score -= 0.5  # 振荡较多
            else:
                stability_score -= 1.0  # 持续振荡
            
            # 5. 衰减比评分（0.25左右为理想，越接近0越好）
            decay_ratio = cl_metrics.decay_ratio
            if decay_ratio <= 0.25:
                stability_score += 1.0  # 快速衰减，理想
            elif decay_ratio <= 0.5:
                stability_score += 0.5  # 良好衰减
            elif decay_ratio <= 1.0:
                pass  # 临界阻尼
            else:
                stability_score -= 1.0  # 发散或不收敛
            
            stability_score = min(10.0, max(0.0, stability_score))
        
        score_details['stability_score'] = round(stability_score, 2)
        
        # 综合评分（新权重）
        weights = {
            'r2': 0.30,           # 拟合质量
            'consistency': 0.20,  # 参数一致性
            'validity': 0.15,     # 参数物理合理性
            'coverage': 0.10,     # 数据覆盖度
            'stability': 0.25     # 闭环稳定性
        }
        
        final_score = (
            weights['r2'] * r2_score +
            weights['consistency'] * consistency_score +
            weights['validity'] * validity_score +
            weights['coverage'] * coverage_score +
            weights['stability'] * stability_score
        )
        
        if r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        # 如果闭环不稳定，限制最高分
        if cl_metrics is not None and not cl_metrics.is_stable:
            final_score = min(final_score, 5.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        score_details['weights'] = weights
        
        return final_score, score_details
    
    # ============================================================
    # 闭环稳定性验证
    # ============================================================
    
    def simulate_closed_loop(self, K: float, T1: float, T2: float, L: float,
                              model_type: str, Kp: float, Ki: float, Kd: float,
                              sp_initial: float, sp_final: float,
                              pv_initial: float = None,
                              n_steps: int = 500,
                              dt: float = 1.0,
                              mv_min: float = 0.0,
                              mv_max: float = 100.0) -> ClosedLoopMetrics:
        """
        闭环仿真：验证PID参数在给定模型下是否能达到稳态
        
        使用增量模型：ΔPV = K × ΔMV（围绕工作点的线性化模型）
        
        Args:
            K, T1, T2, L: 模型参数（增量模型参数）
            model_type: 模型类型
            Kp, Ki, Kd: PID参数
            sp_initial: 初始设定值
            sp_final: 目标设定值（阶跃后）
            pv_initial: 初始PV值，默认等于sp_initial
            n_steps: 仿真步数
            dt: 时间步长
            mv_min, mv_max: MV输出限制
        
        Returns:
            ClosedLoopMetrics: 闭环性能指标
        """
        if pv_initial is None:
            pv_initial = sp_initial
        
        # 初始化
        pv_history = np.zeros(n_steps)
        mv_history = np.zeros(n_steps)
        sp_history = np.zeros(n_steps)
        
        # 工作点：初始稳态
        pv0 = pv_initial  # 初始PV工作点
        mv0 = 50.0        # 初始MV工作点（假设在MV范围中点）
        
        # 增量状态变量
        delta_pv = 0.0    # ΔPV = PV - PV0
        delta_x2 = 0.0    # 二阶模型的第二状态增量
        
        integral = 0.0
        prev_error = 0.0
        
        # 滞后缓冲区（存储ΔMV）
        delay_steps = max(0, int(L / dt))
        delta_mv_buffer = [0.0] * (delay_steps + 1)
        
        # SP阶跃：在第10步发生
        step_time = 10
        
        for t in range(n_steps):
            # 设定值
            sp = sp_initial if t < step_time else sp_final
            sp_history[t] = sp
            
            # 当前PV = PV0 + ΔPV
            pv = pv0 + delta_pv
            pv_history[t] = pv
            
            # PID计算
            error = sp - pv
            integral += error * dt
            
            # 积分限幅（防止积分饱和）
            integral_limit = (mv_max - mv_min) / (abs(Ki) + self._epsilon)
            integral = np.clip(integral, -integral_limit, integral_limit)
            
            derivative = (error - prev_error) / dt if t > 0 else 0.0
            
            # PID输出的是增量MV（相对于工作点）
            delta_mv_pid = Kp * error + Ki * integral + Kd * derivative
            
            # 实际MV = MV0 + ΔMV，需要限幅
            mv = mv0 + delta_mv_pid
            mv = np.clip(mv, mv_min, mv_max)
            delta_mv = mv - mv0  # 实际的ΔMV（考虑限幅后）
            
            mv_history[t] = mv
            prev_error = error
            
            # 滞后处理
            delta_mv_buffer.append(delta_mv)
            delta_mv_delayed = delta_mv_buffer.pop(0)
            
            # 增量模型更新
            delta_pv, delta_x2 = self._model_step_incremental(
                K, T1, T2, model_type, delta_pv, delta_x2, delta_mv_delayed, dt
            )
        
        # 计算性能指标
        return self._calculate_metrics(pv_history, sp_history, mv_history, 
                                        sp_final, step_time, dt)
    
    def _model_step_incremental(self, K: float, T1: float, T2: float, model_type: str,
                                 delta_x1: float, delta_x2: float, 
                                 delta_mv: float, dt: float) -> Tuple[float, float]:
        """
        增量模型单步更新（欧拉离散化）
        
        模型：ΔPV(s) / ΔMV(s) = K / (T1*s + 1) 或更复杂形式
        """
        T1 = max(T1, self._epsilon)
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            # 一阶增量模型: T1 * d(ΔPV)/dt + ΔPV = K * ΔMV
            # 离散化: ΔPV_new = ΔPV + (dt/T1) * (K * ΔMV - ΔPV)
            alpha = dt / T1
            delta_x1_new = delta_x1 + alpha * (K * delta_mv - delta_x1)
            return delta_x1_new, 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            # 二阶增量模型：两个一阶串联
            T2_eff = max(T2, T1 * 0.1)
            alpha1 = dt / T1
            alpha2 = dt / T2_eff
            # 第一阶段输出
            delta_x1_new = delta_x1 + alpha1 * (K * delta_mv - delta_x1)
            # 第二阶段输出（最终ΔPV）
            delta_x2_new = delta_x2 + alpha2 * (delta_x1_new - delta_x2)
            return delta_x2_new, delta_x1_new
        
        elif model_type == ModelType.FOPI:
            # 积分模型: d(ΔPV)/dt = K * ΔMV
            delta_x1_new = delta_x1 + dt * K * delta_mv
            return delta_x1_new, 0.0
        
        return delta_x1, delta_x2
    
    def _calculate_metrics(self, pv: np.ndarray, sp: np.ndarray, mv: np.ndarray,
                           sp_final: float, step_time: int, dt: float) -> ClosedLoopMetrics:
        """计算闭环性能指标"""
        n = len(pv)
        sp_change = sp_final - sp[0]
        
        # 只分析阶跃后的响应
        pv_response = pv[step_time:]
        sp_response = sp[step_time:]
        
        if len(pv_response) < 10 or abs(sp_change) < self._epsilon:
            return ClosedLoopMetrics(
                is_stable=False, settling_time=float('inf'), overshoot=0.0,
                rise_time=float('inf'), steady_state_error=100.0,
                oscillation_count=0, decay_ratio=1.0,
                pv_history=pv, mv_history=mv
            )
        
        # 1. 稳态误差（最后10%的平均值）
        final_portion = pv_response[-max(10, len(pv_response)//10):]
        steady_state_error = abs(np.mean(final_portion) - sp_final) / (abs(sp_change) + self._epsilon) * 100
        
        # 2. 超调量
        if sp_change > 0:
            peak = np.max(pv_response)
            overshoot = max(0, (peak - sp_final) / sp_change * 100)
        else:
            trough = np.min(pv_response)
            overshoot = max(0, (sp_final - trough) / abs(sp_change) * 100)
        
        # 3. 上升时间（10% 到 90%）
        target_10 = sp[0] + 0.1 * sp_change
        target_90 = sp[0] + 0.9 * sp_change
        rise_start = rise_end = None
        
        for i, p in enumerate(pv_response):
            if sp_change > 0:
                if rise_start is None and p >= target_10:
                    rise_start = i
                if rise_end is None and p >= target_90:
                    rise_end = i
                    break
            else:
                if rise_start is None and p <= target_10:
                    rise_start = i
                if rise_end is None and p <= target_90:
                    rise_end = i
                    break
        
        if rise_start is not None and rise_end is not None:
            rise_time = (rise_end - rise_start) * dt
        else:
            rise_time = float('inf')
        
        # 4. 调节时间（进入±2%误差带）
        tolerance = 0.02 * abs(sp_change)
        settling_time = float('inf')
        
        for i in range(len(pv_response) - 1, -1, -1):
            if abs(pv_response[i] - sp_final) > tolerance:
                if i < len(pv_response) - 1:
                    settling_time = (i + 1) * dt
                break
        else:
            settling_time = 0.0  # 始终在误差带内
        
        # 5. 振荡计数和衰减比
        error_signal = pv_response - sp_final
        zero_crossings = np.where(np.diff(np.signbit(error_signal)))[0]
        oscillation_count = len(zero_crossings) // 2
        
        # 衰减比：第二个峰与第一个峰的比值
        peaks = []
        for i in range(1, len(error_signal) - 1):
            if error_signal[i] > error_signal[i-1] and error_signal[i] > error_signal[i+1]:
                peaks.append(abs(error_signal[i]))
            if len(peaks) >= 2:
                break
        
        if len(peaks) >= 2 and peaks[0] > self._epsilon:
            decay_ratio = peaks[1] / peaks[0]
        else:
            decay_ratio = 0.0 if len(peaks) <= 1 else 1.0
        
        # 6. 稳定性判定
        is_stable = (
            settling_time < float('inf') and
            steady_state_error < 5.0 and  # 稳态误差<5%
            overshoot < 50.0 and          # 超调<50%
            decay_ratio < 0.5             # 衰减比<0.5
        )
        
        return ClosedLoopMetrics(
            is_stable=is_stable,
            settling_time=settling_time,
            overshoot=round(overshoot, 2),
            rise_time=round(rise_time, 2),
            steady_state_error=round(steady_state_error, 2),
            oscillation_count=oscillation_count,
            decay_ratio=round(decay_ratio, 3),
            pv_history=pv,
            mv_history=mv
        )
    
    def verify_pid_stability(self, fusion: Optional[FusionResult], 
                              pid_params: Dict[str, float],
                              sp_initial: float = 50.0,
                              sp_final: float = 60.0,
                              pv_initial: float = None,
                              verbose: bool = False) -> Tuple[bool, ClosedLoopMetrics]:
        """
        验证PID参数的闭环稳定性
        
        Args:
            fusion: 模型参数（可以为 None，用于振荡整定场景）
            pid_params: PID参数 {Kp, Ki, Kd}
            sp_initial: SP初始值（来自实际数据）
            sp_final: SP目标值（来自实际数据）
            pv_initial: PV初始值（来自实际数据）
            verbose: 是否打印详细信息
        
        Returns:
            (is_stable, metrics)
        """
        if pv_initial is None:
            pv_initial = sp_initial
        
        # 如果 fusion 为 None（振荡整定），使用默认模型参数
        if fusion is None:
            # 根据 PID 参数估算过程特性
            Kp = abs(pid_params.get('Kp', 1.0))
            # 假设一个典型的一阶过程
            K = 1.0 / Kp if Kp > self._epsilon else 1.0  # 反推过程增益
            T1 = pid_params.get('Pu', 10.0) if 'Pu' in pid_params else 10.0  # 使用临界周期作为参考
            T2 = 0.0
            L = 0.0
            model_type = ModelType.FO
        else:
            K = fusion.K
            T1 = fusion.T1
            T2 = fusion.T2
            L = fusion.L
            model_type = fusion.model_type
        
        # 自适应仿真参数：确保数值稳定性
        T_min = min(T1, T2 if T2 > 0 else T1)
        dt = min(0.1, T_min / 10)  # 步长不超过最小时间常数的1/10
        dt = max(0.01, dt)         # 但也不要太小
        
        # 仿真时长：至少10倍最大时间常数
        T_max = max(T1, T2 if T2 > 0 else T1)
        sim_time = max(100, T_max * 20)
        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 5000)  # 限制最大步数
        
        metrics = self.simulate_closed_loop(
            K=K, T1=T1, T2=T2, L=L,
            model_type=model_type,
            Kp=pid_params['Kp'], Ki=pid_params['Ki'], Kd=pid_params['Kd'],
            sp_initial=sp_initial,
            sp_final=sp_final,
            pv_initial=pv_initial,
            n_steps=n_steps,
            dt=dt
        )
        
        if verbose:
            status = "✅ 稳定" if metrics.is_stable else "❌ 不稳定"
            print(f"\n🔄 闭环稳定性验证: {status}")
            print(f"   调节时间: {metrics.settling_time:.1f}s")
            print(f"   超调量: {metrics.overshoot:.1f}%")
            print(f"   上升时间: {metrics.rise_time:.1f}s")
            print(f"   稳态误差: {metrics.steady_state_error:.2f}%")
            print(f"   振荡次数: {metrics.oscillation_count}")
            print(f"   衰减比: {metrics.decay_ratio:.3f}")
        
        return metrics.is_stable, metrics
