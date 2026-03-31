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

from ...config import Config, ModelType
from ...data_models import FusionResult
from ..core.data_classes import ClosedLoopMetrics


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
                              mv_max: float = 100.0,
                              max_settling_time: float = None,
                              loop_type: str = 'flow') -> ClosedLoopMetrics:
        """
        闭环仿真：验证PID参数在给定模型下是否能达到稳态
        
        使用增量模型：ΔPV = K × ΔMV（围绕工作点的线性化模型）
        """
        if pv_initial is None:
            pv_initial = sp_initial
        
        # 初始化
        pv_history = np.zeros(n_steps)
        mv_history = np.zeros(n_steps)
        sp_history = np.zeros(n_steps)
        
        pv0 = pv_initial
        sp_change = sp_final - sp_initial
        mv_mid = (mv_min + mv_max) / 2
        mv_range = mv_max - mv_min
        
        if abs(K) > self._epsilon:
            delta_mv_needed = sp_change / K
            mv_offset = np.clip(-delta_mv_needed * 0.3, -mv_range * 0.25, mv_range * 0.25)
            mv0 = np.clip(mv_mid + mv_offset, mv_min + 5, mv_max - 5)
        else:
            mv0 = mv_mid
        
        delta_pv = 0.0
        delta_x2 = 0.0
        integral = 0.0
        prev_error = 0.0
        
        delay_steps = max(0, int(L / dt))
        delta_mv_buffer = [0.0] * (delay_steps + 1)
        step_time = 10
        
        for t in range(n_steps):
            sp = sp_initial if t < step_time else sp_final
            sp_history[t] = sp
            pv = pv0 + delta_pv
            pv_history[t] = pv
            
            error = sp - pv
            integral += error * dt
            integral_limit = (mv_max - mv_min) / (abs(Ki) + self._epsilon)
            integral = np.clip(integral, -integral_limit, integral_limit)
            derivative = (error - prev_error) / dt if t > 0 else 0.0
            
            delta_mv_pid = Kp * error + Ki * integral + Kd * derivative
            mv = mv0 + delta_mv_pid
            mv = np.clip(mv, mv_min, mv_max)
            delta_mv = mv - mv0
            
            mv_history[t] = mv
            prev_error = error
            
            delta_mv_buffer.append(delta_mv)
            delta_mv_delayed = delta_mv_buffer.pop(0)
            
            delta_pv, delta_x2 = self._model_step_incremental(
                K, T1, T2, model_type, delta_pv, delta_x2, delta_mv_delayed, dt
            )
        
        return self._calculate_metrics(pv_history, sp_history, mv_history, sp_final, step_time, dt, max_settling_time, loop_type)
    
    def _model_step_incremental(self, K: float, T1: float, T2: float, model_type: str,
                                 delta_x1: float, delta_x2: float, 
                                 delta_mv: float, dt: float) -> Tuple[float, float]:
        """增量模型单步更新 (采用指数积分 ZOH 避免刚性数值爆炸)"""
        T1 = max(T1, self._epsilon)
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            # 指数欧拉避免大步长(dt>2*T1)下的数值发散
            alpha = 1.0 - np.exp(-dt / T1)
            delta_x1_new = delta_x1 + alpha * (K * delta_mv - delta_x1)
            return delta_x1_new, 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            T2_eff = max(T2, T1 * 0.1)
            alpha1 = 1.0 - np.exp(-dt / T1)
            alpha2 = 1.0 - np.exp(-dt / T2_eff)
            delta_x1_new = delta_x1 + alpha1 * (K * delta_mv - delta_x1)
            delta_x2_new = delta_x2 + alpha2 * (delta_x1_new - delta_x2)
            return delta_x2_new, delta_x1_new
        
        elif model_type == ModelType.FOPI:
            delta_x1_new = delta_x1 + dt * K * delta_mv
            return delta_x1_new, 0.0
        
        return delta_x1, delta_x2
    
    def _calculate_metrics(self, pv: np.ndarray, sp: np.ndarray, mv: np.ndarray,
                           sp_final: float, step_time: int, dt: float,
                           max_settling_time: float = None,
                           loop_type: str = 'flow') -> ClosedLoopMetrics:
        """计算闭环性能指标"""
        n = len(pv)
        sp_change = sp_final - sp[0]
        pv_response = pv[step_time:]
        sp_response = sp[step_time:]
        
        if len(pv_response) < 10 or abs(sp_change) < self._epsilon:
            return ClosedLoopMetrics(
                is_stable=False, settling_time=float('inf'), overshoot=0.0,
                rise_time=float('inf'), steady_state_error=100.0,
                oscillation_count=0, decay_ratio=1.0,
                pv_history=pv, mv_history=mv
            )
        
        # 稳态误差
        final_portion = pv_response[-max(10, len(pv_response)//10):]
        steady_state_error = abs(np.mean(final_portion) - sp_final) / (abs(sp_change) + self._epsilon) * 100
        
        # 超调量
        if sp_change > 0:
            peak = np.max(pv_response)
            overshoot = max(0, (peak - sp_final) / sp_change * 100)
        else:
            trough = np.min(pv_response)
            overshoot = max(0, (sp_final - trough) / abs(sp_change) * 100)
        
        # 上升时间
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
        
        rise_time = (rise_end - rise_start) * dt if rise_start is not None and rise_end is not None else float('inf')
        
        # 调节时间
        tolerance = 0.02 * abs(sp_change)
        settling_time = float('inf')
        
        for i in range(len(pv_response) - 1, -1, -1):
            if abs(pv_response[i] - sp_final) > tolerance:
                if i < len(pv_response) - 1:
                    settling_time = (i + 1) * dt
                break
        else:
            settling_time = 0.0
        
        # 振荡计数和衰减比
        error_signal = pv_response - sp_final
        zero_crossings = np.where(np.diff(np.signbit(error_signal)))[0]
        oscillation_count = len(zero_crossings) // 2
        
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
        
        # 从配置读取判定阈值
        limits = Config.CLOSED_LOOP
        loop_config = Config.LOOP_SPECIFIC_VERIFICATION.get(loop_type, Config.LOOP_SPECIFIC_VERIFICATION['flow']) if loop_type else Config.LOOP_SPECIFIC_VERIFICATION['flow']
        
        if max_settling_time is not None:
            max_settling = max_settling_time
        else:
            max_settling = limits.get('max_settling_time', 600.0)
        
        max_overshoot = loop_config.get('overshoot_acceptable', limits.get('overshoot_acceptable', 30.0))
        max_steady_error = loop_config.get('steady_state_error', limits.get('settling_threshold', 0.02) * 100)
        
        # [NEW] 衰减比优秀时放宽超调量限制
        # 如果衰减比很好(<=0.6)，说明虽然超调大但收敛快，这是工业允许的
        if decay_ratio <= 0.6:
            max_overshoot = max(max_overshoot, 65.0)
        
        # 判定稳定性（放宽衰减比从 0.5 → 0.8，工业实际中 decay_ratio < 1.0 即收敛）
        is_settled = settling_time < max_settling
        is_accurate = steady_state_error < max_steady_error
        is_smooth = overshoot < max_overshoot
        is_decaying = decay_ratio < 0.8
        
        is_stable = is_settled and is_accurate and is_smooth and is_decaying
        
        # [NEW] 边界容忍：仅一项指标微弱超标时仍判定为稳定（工业实用性）
        if not is_stable and is_settled:
            fail_count = sum([not is_accurate, not is_smooth, not is_decaying])
            if fail_count == 1:
                # 仅一项超标，检查是否只是微弱超标
                marginal = False
                if not is_accurate and steady_state_error < max_steady_error * 1.5:
                    marginal = True  # 稳态误差超标 < 50%
                if not is_smooth and overshoot < max_overshoot * 1.3:
                    marginal = True  # 超调超标 < 30%
                if not is_decaying and decay_ratio < 1.0:
                    marginal = True  # 衰减比 < 1.0 说明仍在收敛
                if marginal:
                    is_stable = True
        
        if not is_stable and max_settling_time is not None and hasattr(self, 'log'):
             self.log(f"   ⚠️ Metrics Fail: Settled={is_settled}({settling_time:.1f}/{max_settling:.1f}), "
                   f"Accurate={is_accurate}({steady_state_error:.2f}/{max_steady_error:.2f}), "
                   f"Smooth={is_smooth}({overshoot:.2f}/{max_overshoot:.2f}), "
                   f"Decaying={is_decaying}({decay_ratio:.2f})")
        
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
                              loop_type: Optional[str] = None,
                              verbose: bool = False) -> Tuple[bool, ClosedLoopMetrics]:
        """验证PID参数的闭环稳定性"""
        if pv_initial is None:
            pv_initial = sp_initial
        

        # 确定实际仿真时间步长 (模拟DCS真实控制周期)
        dt_val = pid_params.get('Ts', 0.0)
        if dt_val is None or dt_val <= 0:
            # 强制引入真实DCS常见下限 (1.0s) 作为保底基准。防止未指定周期时无限微观化。
            dt_base = 1.0
        else:
            dt_base = dt_val

        if fusion is None:
            Kp = abs(pid_params.get('Kp', 1.0))
            K = 1.0 / Kp if Kp > self._epsilon else 1.0
            T1 = pid_params.get('Pu', 10.0) if 'Pu' in pid_params else 10.0
            T2 = 0.0
            L = 0.0
            model_type = ModelType.FO
        else:
            K = fusion.K
            T1 = fusion.T1
            T2 = fusion.T2
            L = fusion.L
            model_type = fusion.model_type

        # 核心修复：由于底层物理模型已升级为无条件稳定的纯指数 ZOH 积分(1-exp(-dt/T))，
        # 常微分方程本身已不再受大步长发散威胁。因此我们必须**直接采用真实的 DCS 采样控制周期**。
        # 不再使用 T_min / 5 刻意缩小 dt，否则高频响应的数学错觉会掩盖极速参数在真实慢频系统中的振荡发散性！
        dt = max(0.5, dt_base)
        
        osc_config = Config.OSCILLATION_TUNING
        very_slow_t1_threshold = osc_config.get('very_slow_system_t1_threshold', 100.0)
        very_slow_pu_threshold = osc_config.get('very_slow_system_pu_threshold', 100.0)
        very_slow_sim_factor = osc_config.get('very_slow_sim_duration_factor', 10.0)
        T_max = max(T1, T2 if T2 > 0 else T1)
        # 动态计算极大慢系统的最大允许时长
        very_slow_max_duration = max(30000.0, (T_max + L) * 15.0)
        
        T_max = max(T1, T2 if T2 > 0 else T1)
        Pu = pid_params.get('Pu', T_max)
        is_very_slow = T_max > very_slow_t1_threshold or Pu > very_slow_pu_threshold
        
        # 确保仿真时长足够覆盖允许的最大调节时间
        ensure_duration = Config.CLOSED_LOOP.get('max_settling_time', 600.0) * 1.5
        
        if is_very_slow:
            sim_time = min((T_max + L) * very_slow_sim_factor, very_slow_max_duration)
            sim_time = max(sim_time, ensure_duration)
        else:
            sim_time = max(100, T_max * 20, ensure_duration)
        
        # [FIX] 优先使用函数参数传入的 loop_type，其次使用 fusion 属性
        if not loop_type:
            loop_type = getattr(fusion, 'loop_type', 'flow') if fusion else 'flow'
        if not loop_type:
            loop_type = 'flow'
        loop_config = Config.LOOP_SPECIFIC_VERIFICATION.get(loop_type, Config.LOOP_SPECIFIC_VERIFICATION['flow'])
        settling_time_factor = loop_config.get('max_settling_time_factor', 10.0)
        
        default_max_settling = Config.CLOSED_LOOP.get('max_settling_time', 600.0)
        dynamic_max_settling = max(default_max_settling, settling_time_factor * (T_max + L))
        
        n_steps = int(sim_time / dt)
        
        if is_very_slow:
            max_steps = min(500000, int(sim_time / dt + 1000))
        elif T_max > 50:
            max_steps = min(100000, int(sim_time / dt + 1000))
        else:
            max_steps = 10000
        
        n_steps = min(n_steps, max_steps)
        
        metrics = self.simulate_closed_loop(
            K=K, T1=T1, T2=T2, L=L,
            model_type=model_type,
            Kp=pid_params['Kp'], Ki=pid_params['Ki'], Kd=pid_params['Kd'],
            sp_initial=sp_initial,
            sp_final=sp_final,
            pv_initial=pv_initial,
            n_steps=n_steps,
            dt=dt,
            max_settling_time=dynamic_max_settling,
            loop_type=loop_type
        )

        if not metrics.is_stable and verbose and hasattr(self, 'log'):
            r2_val = getattr(fusion, 'global_r2', 0.0) if fusion else 0.0
            self.log(f"   ⚠️ Failed verification with R2={r2_val:.4f}, Model=K{K:.2f}/T{T1:.2f}/L{L:.2f}")
        
        return metrics.is_stable, metrics
    
    def simulate_prediction(self, fusion: FusionResult,
                             pid_params: Dict[str, float],
                             hist_data = None,
                             sim_duration_factor: float = 30.0,
                             verbose: bool = False) -> Tuple[bool, ClosedLoopMetrics]:
        """
        预测仿真：从历史数据最后一个点开始，使用新PID参数预测未来走势
        
        与 verify_pid_stability (标准阶跃仿真) 不同：
        - 从真实工作点出发（实际PV、MV、SV）
        - 模拟实际控制场景（可能PV已接近SV，需引入小阶跃检验）
        
        Args:
            fusion: 融合后的模型参数
            pid_params: PID参数
            hist_data: 历史数据（用于获取最后工作点）
            sim_duration_factor: 仿真时长倍数（相对T1）
            
        Returns:
            (is_stable, metrics)
        """
        K = fusion.K
        T1 = fusion.T1
        T2 = fusion.T2
        L = fusion.L
        model_type = fusion.model_type
        
        # 获取最后工作点
        if hist_data is not None and len(hist_data.pv) > 0:
            pv_init = float(hist_data.pv[-1])
            sv_target = float(hist_data.sv[-1])
            mv_init = float(hist_data.mv[-1])
        else:
            # 无历史数据时使用标准阶跃
            return self.verify_pid_stability(fusion, pid_params, verbose=verbose)
        
        # 如果PV已接近SV，引入小阶跃扰动（10% SV范围）
        sv_range = max(float(np.ptp(hist_data.sv)), 1.0)
        initial_error = abs(sv_target - pv_init)
        
        if initial_error < sv_range * 0.05:
            sv_target = sv_target + sv_range * 0.1
        
        # 仿真参数
        # 统一使用真实的 DCS 采样周期 dt，与验证引擎保持绝对一致，避免产生高频数学错觉
        dt_base = pid_params.get('Ts', 1.0)
        dt = float(dt_base)
        if dt < 0.1:
            dt = 1.0  # 若没有合法 Ts 预设，默认使用 1s（典型 DCS 控制周期）
            
        # 限制单循环频率极高导致长系统崩溃的问题
        dt = max(0.5, dt)
        
        sim_time = max(200, T1 * sim_duration_factor)
        sim_time = min(sim_time, 5000)
        n_steps = min(int(sim_time / dt), 30000)
        
        # 运行闭环仿真（从真实工作点）
        metrics = self.simulate_closed_loop(
            K=K, T1=T1, T2=T2, L=L,
            model_type=model_type,
            Kp=pid_params['Kp'], Ki=pid_params['Ki'], Kd=pid_params['Kd'],
            sp_initial=pv_init,   # 从真实PV出发
            sp_final=sv_target,    # 到目标SV
            pv_initial=pv_init,
            n_steps=n_steps,
            dt=dt
        )
        
        return metrics.is_stable, metrics

