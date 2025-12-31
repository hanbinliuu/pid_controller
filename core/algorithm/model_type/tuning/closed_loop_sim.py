"""
闭环仿真模块 (Closed Loop Simulation Module)
==========================================

闭环仿真验证PID参数的稳定性和性能。

主要功能：
- 闭环阶跃响应仿真
- 性能指标计算（调节时间、超调量、稳态误差等）
- PID参数稳定性验证
"""

import numpy as np
from typing import Dict, Tuple, Optional

from ..config import ModelType
from ..data_models import FusionResult
from .data_classes import ClosedLoopMetrics


class ClosedLoopSimMixin:
    """
    闭环仿真Mixin类
    
    提供闭环仿真和稳定性验证方法。
    需要宿主类提供 _epsilon 属性。
    """
    
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
        
        # MV 工作点：根据模型增益和 SP 变化量估算需要的 MV 变化
        # 简化逻辑：从中点开始，确保有足够的调节空间
        sp_change = sp_final - sp_initial
        mv_mid = (mv_min + mv_max) / 2
        mv_range = mv_max - mv_min
        
        if abs(K) > self._epsilon:
            delta_mv_needed = sp_change / K  # 理论需要的 MV 变化量
            # 根据需要的MV变化方向，从中点偏移以留出调节空间
            # 但偏移量不超过范围的25%
            mv_offset = np.clip(-delta_mv_needed * 0.3, -mv_range * 0.25, mv_range * 0.25)
            mv0 = np.clip(mv_mid + mv_offset, mv_min + 5, mv_max - 5)
        else:
            mv0 = mv_mid
        
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
        # 对于慢系统（T_max > 50s），允许更多步数
        max_steps = 5000 if T_max <= 50 else min(10000, int(T_max * 100))
        n_steps = min(n_steps, max_steps)
        
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
        
        return metrics.is_stable, metrics
