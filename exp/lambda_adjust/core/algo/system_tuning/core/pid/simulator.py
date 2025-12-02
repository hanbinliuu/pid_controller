"""
PID控制器仿真和可视化模块
用于仿真新PID参数下的系统响应，并与原始数据进行对比
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Mode, TuningMethod, Config
from core.model.identifier import ModelIdentifier


class PIDController:
    """
    PID控制器实现
    支持标准PID控制，使用pb（比例带）、ti（积分时间）、td（微分时间）参数
    """
    
    def __init__(self, pb=100.0, ti=0.0, td=0.0, dt=1.0, 
                 output_min=-np.inf, output_max=np.inf):
        """
        初始化PID控制器
        
        Args:
            pb: 比例带（比例带 = 100 / Kp）
            ti: 积分时间（秒）
            td: 微分时间（秒）
            dt: 采样时间（秒）
            output_min: 输出最小值
            output_max: 输出最大值
        """
        self.pb = max(pb, Config.EPSILON)  # 防止除零
        self.ti = max(ti, Config.EPSILON) if ti > 0 else 0.0
        self.td = max(td, 0.0)
        self.dt = dt
        
        # 计算PID增益
        self.Kp = 100.0 / self.pb  # 比例增益
        self.Ki = self.Kp / self.ti if self.ti > 0 else 0.0  # 积分增益
        self.Kd = self.Kp * self.td  # 微分增益
        
        # 输出限制
        self.output_min = output_min
        self.output_max = output_max
        
        # 控制器状态
        self.integral = 0.0
        self.last_error = 0.0
        self.last_output = 0.0
        
    def compute(self, setpoint, process_value):
        """
        计算PID控制器输出
        
        Args:
            setpoint: 设定值
            process_value: 过程值（当前PV）
            
        Returns:
            控制器输出（MV）
        """
        # 计算误差
        error = setpoint - process_value
        
        # 比例项
        proportional = self.Kp * error
        
        # 积分项（带抗饱和）
        if self.ti > 0:
            self.integral += error * self.dt
            # 抗饱和：如果输出饱和，停止积分
            if self.last_output >= self.output_max and error > 0:
                self.integral -= error * self.dt
            elif self.last_output <= self.output_min and error < 0:
                self.integral -= error * self.dt
            integral_term = self.Ki * self.integral
        else:
            integral_term = 0.0
        
        # 微分项（基于误差变化率）
        if self.dt > 0:
            derivative = (error - self.last_error) / self.dt
            derivative_term = self.Kd * derivative
        else:
            derivative_term = 0.0
        
        # PID输出
        output = proportional + integral_term + derivative_term
        
        # 输出限幅
        output = np.clip(output, self.output_min, self.output_max)
        
        # 更新状态
        self.last_error = error
        self.last_output = output
        
        return output
    
    def reset(self):
        """重置控制器状态"""
        self.integral = 0.0
        self.last_error = 0.0
        self.last_output = 0.0


def _calculate_initial_mv(model_params, setpoint, current_pv, initial_mv=None, 
                          system_model=None, pv_reference=None):
    """
    计算工作点MV值（使系统达到设定值所需的MV）
    
    Args:
        model_params: 模型参数
        setpoint: 设定值
        current_pv: 当前过程值（用于估计y0）
        initial_mv: 指定的初始MV（如果提供则直接使用）
        system_model: 系统模型函数（可选，用于更准确的y0估计）
        pv_reference: 参考PV数据（可选，用于更准确的y0估计）
        
    Returns:
        工作点MV值
    """
    if initial_mv is not None:
        return initial_mv
    
    # 从模型参数估计工作点MV
    if len(model_params) < 2:
        return 0.0
    
    K = model_params[0]
    if K <= Config.EPSILON:
        return 0.0
    
    # 估计y0（基准值）
    # 方法1：如果有参考PV数据，使用其初始值作为y0估计（与模型辨识时y0 = y[0]保持一致）
    if pv_reference is not None and len(pv_reference) > 0:
        # 使用参考数据的初始值作为y0（与模型辨识时保持一致）
        y0_est = pv_reference[0]
        # 或者使用最小值（对于温度系统，y0通常接近环境温度或最小值）
        # y0_est = min(np.min(pv_reference), current_pv)
    else:
        # 方法2：使用当前PV作为y0估计（对于大多数系统，y0接近初始PV）
        y0_est = current_pv
    
    # 对于FOPDT模型：pv_ss = y0 + K * mv_ss，所以 mv_ss = (pv_ss - y0) / K
    # 对于一阶模型：pv_ss = K * mv_ss，所以 mv_ss = pv_ss / K
    if system_model == ModelIdentifier.integral_delay_model:
        # 积分-延迟模型：pv的变化率 = K * mv
        # 对于积分系统，稳态时pv不再变化，需要mv=0
        # 但为了达到设定值，需要计算一个工作点MV
        # 注意：积分系统没有真正的稳态，这里使用近似
        # 对于积分系统，工作点MV应该根据误差来估计
        # 使用一个基于误差和K的估计：mv ≈ (setpoint - initial_pv) / (K * T_estimate)
        # 其中T_estimate是一个估计的时间常数（例如30-60秒）
        if K > 0 and initial_pv is not None:
            error = setpoint - initial_pv
            # 使用一个合理的时间常数估计（30-60秒）
            T_estimate = 30.0  # 可以根据实际情况调整
            # 计算需要的MV来驱动系统达到设定值
            mv_estimate = error / (K * T_estimate)
            # 限制在一个合理范围内（避免过大）
            mv_estimate = np.clip(mv_estimate, -100.0, 100.0)
            return mv_estimate
        else:
            return 0.0
    elif len(model_params) == 2:
        # 一阶模型（无y0项）
        return setpoint / K
    else:
        # FOPDT模型（有y0项）
        mv_workpoint = (setpoint - y0_est) / K
        return mv_workpoint


def _simulate_system_step(system_model, model_params, pv_prev, u_current, u_delayed, 
                          y0, dt_step):
    """
    计算系统单步响应（提取为独立函数，避免重复代码）
    
    Args:
        system_model: 系统模型函数
        model_params: 模型参数
        pv_prev: 上一步的过程值
        u_current: 当前输入
        u_delayed: 滞后的输入
        y0: 基准值
        dt_step: 时间步长
        
    Returns:
        新的过程值
    """
    if system_model == ModelIdentifier.fopdt_model:
        K, T, L = model_params[:3]
        T = max(T, Config.EPSILON)
        return pv_prev + (K * u_delayed - (pv_prev - y0)) / T * dt_step
        
    elif system_model == ModelIdentifier.second_order_model:
        K, T1, T2 = model_params[:3]
        T1 = max(T1, Config.EPSILON)
        T2 = max(T2, Config.EPSILON)
        # 二阶模型需要中间状态，这里使用等效一阶近似
        # 注意：完整实现需要维护中间状态变量x1
        T_equiv = T1 + T2
        return pv_prev + (K * u_current - (pv_prev - y0)) / T_equiv * dt_step
        
    elif system_model == ModelIdentifier.integral_delay_model:
        K, L = model_params[:2]
        return pv_prev + K * u_delayed * dt_step
        
    else:
        # 默认使用FOPDT
        K, T, L = model_params[:3] if len(model_params) >= 3 else (
            model_params[0], 
            model_params[1] if len(model_params) > 1 else 30.0, 
            0.0
        )
        T = max(T, Config.EPSILON)
        return pv_prev + (K * u_delayed - (pv_prev - y0)) / T * dt_step


def simulate_system_with_pid(t, system_model, model_params, pid_params, setpoint, 
                             initial_pv=0.0, initial_mv=None, verbose=False, 
                             setpoint_array=None, mv_reference=None, pv_reference=None):
    """
    使用PID控制器仿真系统响应（优化版，支持时变设定值）
    
    Args:
        t: 时间数组
        system_model: 系统模型函数（如 ModelIdentifier.fopdt_model）
        model_params: 系统模型参数（如 (K, T, L) 或 (K, T1, T2)）
        pid_params: PID参数字典 {'pb': pb, 'ti': ti, 'td': td}
        setpoint: 设定值（如果setpoint_array为None则使用此固定值）
        initial_pv: 初始过程值
        initial_mv: 初始控制输出（可选）
        verbose: 是否打印详细信息
        setpoint_array: 时变设定值数组（可选，如果提供则使用此数组）
        mv_reference: 参考MV数组，用于估计MV范围（可选）
        pv_reference: 参考PV数组，用于更准确的y0估计（可选）
        
    Returns:
        pv_simulated: 仿真的过程值数组
        mv_simulated: 仿真的控制输出数组
    """
    n = len(t)
    if n < 2:
        return np.array([initial_pv]), np.array([initial_mv if initial_mv is not None else 0.0])
    
    # 处理设定值：如果提供了setpoint_array，使用它；否则使用固定值
    if setpoint_array is not None and len(setpoint_array) == n:
        sv_array = setpoint_array
        initial_setpoint = sv_array[0]
    else:
        sv_array = np.full(n, setpoint)
        initial_setpoint = setpoint
    
    # 预计算常用值
    dt = np.mean(np.diff(t))
    dt_array = np.diff(t)
    dt_array = np.concatenate([[dt], dt_array])  # 使长度与t一致
    
    # 创建PID控制器
    pb = pid_params.get('pb', 100.0)
    ti = pid_params.get('ti', 0.0)
    td = pid_params.get('td', 0.0)
    
    # 估计MV范围（从参考数据或使用默认值）
    if mv_reference is not None and len(mv_reference) > 0:
        mv_min_ref = np.min(mv_reference)
        mv_max_ref = np.max(mv_reference)
        mv_range = max(abs(mv_min_ref), abs(mv_max_ref)) * 2.0  # 扩大范围
        mv_range = max(mv_range, 50.0)  # 至少50
    else:
        mv_range = 100.0  # 增大默认范围
    
    pid = PIDController(pb=pb, ti=ti, td=td, dt=dt,
                       output_min=-mv_range, output_max=mv_range)
    pid.reset()
    
    # 初始化数组
    pv = np.zeros(n)
    mv = np.zeros(n)
    pv[0] = initial_pv
    
    # 计算初始MV（工作点）- 使用初始设定值
    # 传递pv_reference用于更准确的y0估计
    mv_workpoint = _calculate_initial_mv(model_params, initial_setpoint, initial_pv, initial_mv,
                                        system_model=system_model, pv_reference=pv_reference)
    mv[0] = mv_workpoint
    
    # 准备模型输入和参数
    u = np.zeros(n)
    u[0] = mv[0]
    
    # 更准确地估计y0（使用参考数据的初始值或最小值，与模型辨识时保持一致）
    # 如果提供了参考PV数据，使用其初始值或最小值作为y0（与模型辨识时的y0 = y[0]保持一致）
    if pv_reference is not None and len(pv_reference) > 0:
        # 使用参考数据的初始值作为y0（与模型辨识时y0 = y[0]保持一致）
        y0 = pv_reference[0]
        # 或者使用最小值（对于温度系统，y0通常接近环境温度或最小值）
        # y0 = min(np.min(pv_reference), initial_pv)
    else:
        y0 = initial_pv  # 默认使用初始PV
    
    # 预计算滞后采样点数（如果模型有滞后）
    L_samples = 0
    if system_model == ModelIdentifier.fopdt_model and len(model_params) >= 3:
        L = model_params[2]
        L_samples = int(np.round(L / dt)) if dt > 0 else 0
    elif system_model == ModelIdentifier.integral_delay_model and len(model_params) >= 2:
        L = model_params[1]
        L_samples = int(np.round(L / dt)) if dt > 0 else 0
    
    # 二阶模型需要中间状态变量
    x1 = initial_pv if system_model == ModelIdentifier.second_order_model else None
    
    # 仿真循环
    for i in range(1, n):
        # 获取当前设定值
        current_setpoint = sv_array[i]
        
        # PID计算（返回相对于工作点的增量）
        mv_increment = pid.compute(current_setpoint, pv[i-1])
        
        # 动态更新工作点MV（当设定值变化时，或对于积分系统需要动态调整）
        # 对于积分-延迟模型，工作点MV应该动态调整以帮助系统达到设定值
        if system_model == ModelIdentifier.integral_delay_model:
            # 对于积分系统，稳态时MV应该为0（pv变化率=0）
            # 但在过渡过程中，需要根据误差动态调整工作点
            # 使用一个基于误差的反馈来调整工作点
            error = current_setpoint - pv[i-1]
            K = model_params[0] if len(model_params) > 0 else 1.0
            
            # 对于积分系统，工作点MV应该根据误差和PV变化率来动态调整
            # 使用一个更智能的自适应工作点调整
            if abs(error) > 0.1:  # 误差较大时
                # 计算PV的变化率（用于估计当前状态）
                if i > 1:
                    pv_rate = (pv[i-1] - pv[i-2]) / dt_array[i-1] if i-1 < len(dt_array) else 0.0
                else:
                    pv_rate = 0.0
                
                # 计算需要的PV变化率来消除误差
                # 使用一个自适应的时间常数：误差越大，响应越快
                time_constant = max(5.0, abs(error) * 2.0)  # 至少5秒，误差越大响应越快
                desired_rate = error / time_constant
                
                # 计算需要的MV：dpv/dt = K * mv，所以 mv = (dpv/dt) / K
                # 考虑当前PV变化率，调整工作点MV
                mv_adjustment = (desired_rate - pv_rate * 0.5) / K if K > 0 else 0.0
                # 限制工作点MV的范围，避免过大
                mv_workpoint = np.clip(mv_adjustment, -50.0, 50.0)
            else:
                # 误差较小时，工作点MV应该接近0（稳态）
                # 但保留一个小的调整量来帮助消除残余误差
                mv_workpoint = error / (K * 30.0) if K > 0 else 0.0
                mv_workpoint = np.clip(mv_workpoint, -5.0, 5.0)
        elif i > 0 and abs(sv_array[i] - sv_array[i-1]) > 0.1:
            # 设定值发生变化，更新工作点（非积分系统）
            # 使用固定的y0（与模型辨识时保持一致），而不是当前PV
            # 这样可以确保稳态时PV能准确达到设定值
            mv_workpoint = _calculate_initial_mv(model_params, current_setpoint, y0, None,
                                                 system_model=system_model, pv_reference=pv_reference)
            if verbose and i % 100 == 0:  # 每100个点打印一次
                print(f"   时间 {t[i]:.1f}s: 设定值变化 {sv_array[i-1]:.2f} -> {current_setpoint:.2f}, "
                      f"工作点MV更新为 {mv_workpoint:.2f}")
        
        # 更新MV（工作点 + 增量）
        mv[i] = mv_workpoint + mv_increment
        
        # 限制MV在合理范围内（基于参考数据）
        if mv_reference is not None and len(mv_reference) > 0:
            mv_min = np.min(mv_reference) * 0.5  # 允许超出参考范围
            mv_max = np.max(mv_reference) * 1.5
            mv[i] = np.clip(mv[i], mv_min, mv_max)
        
        u[i] = mv[i]
        
        # 获取滞后的输入
        u_delay = u[max(0, i - L_samples)]
        
        # 计算时间步长
        dt_step = dt_array[i] if i < len(dt_array) else dt
        
        # 使用系统模型计算PV
        if system_model == ModelIdentifier.second_order_model:
            # 二阶模型：需要维护中间状态
            K, T1, T2 = model_params[:3]
            T1 = max(T1, Config.EPSILON)
            T2 = max(T2, Config.EPSILON)
            
            # 第一个一阶环节：u -> x1
            u_eff = K * u[i]
            dx1_dt = (u_eff - x1) / T1
            x1 = x1 + dx1_dt * dt_step
            
            # 第二个一阶环节：x1 -> y
            dy_dt = (x1 - pv[i-1]) / T2
            pv[i] = pv[i-1] + dy_dt * dt_step
        else:
            # 其他模型使用统一函数
            pv[i] = _simulate_system_step(system_model, model_params, pv[i-1], 
                                         u[i], u_delay, y0, dt_step)
    
    if verbose:
        final_setpoint = sv_array[-1]
        print(f"\n🔍 仿真完成:")
        print(f"   - 初始PV: {initial_pv:.3f}, 初始设定值: {initial_setpoint:.3f}")
        print(f"   - 最终PV: {pv[-1]:.3f}, 最终设定值: {final_setpoint:.3f}")
        print(f"   - 最终误差: {abs(pv[-1] - final_setpoint):.3f}")
        print(f"   - MV范围: [{np.min(mv):.3f}, {np.max(mv):.3f}]")
        print(f"   - 工作点MV: {mv_workpoint:.3f}")
        
        # 检查是否达到稳态
        if abs(pv[-1] - final_setpoint) > 1.0:
            print(f"   ⚠️ 警告: 最终PV与设定值差异较大，可能原因：")
            print(f"      1. 模型参数K可能不准确（当前: {model_params[0]:.3f}）")
            print(f"      2. PID参数可能不够激进")
            print(f"      3. 仿真时间可能不够长")
            print(f"      4. MV范围可能受限")
    
    return pv, mv


def _add_tuning_segment_annotation(ax, t_original, tuning_segment_indices, 
                                   add_labels=True, add_text=False, segment_label=None):
    """
    在子图上添加整定段标注（提取为独立函数，避免重复代码）
    
    Args:
        ax: matplotlib轴对象
        t_original: 时间数组
        tuning_segment_indices: 整定段索引 (start_idx, end_idx) 或列表 [(start1, end1), (start2, end2), ...]
        add_labels: 是否添加到图例
        add_text: 是否添加文本标注
        segment_label: 段标签（用于多段标注）
    """
    if tuning_segment_indices is None:
        return
    
    # 支持单个段或多个段的标注
    if isinstance(tuning_segment_indices, tuple) and len(tuning_segment_indices) == 2:
        # 单个段
        segments_list = [tuning_segment_indices]
    elif isinstance(tuning_segment_indices, list):
        # 多个段
        segments_list = tuning_segment_indices
    else:
        return
    
    colors = ['yellow', 'orange', 'lightblue', 'lightgreen', 'lightcoral']
    
    for seg_idx, (start_idx, end_idx) in enumerate(segments_list):
        # end_idx可能是exclusive的（等于数组长度），所以允许end_idx == len(t_original)
        # 确保索引在有效范围内
        start_idx = max(0, min(start_idx, len(t_original) - 1))
        safe_end_idx = max(0, min(end_idx, len(t_original) - 1))
        
        if not (0 <= start_idx < len(t_original) and 0 <= end_idx <= len(t_original)):
            continue
        
        t_start = t_original[start_idx]
        t_end = t_original[safe_end_idx]
        
        # 选择颜色（循环使用）
        color = colors[seg_idx % len(colors)]
        
        # 添加高亮区域
        if seg_idx == 0 and add_labels:
            label = segment_label if segment_label else f'整定段 {seg_idx + 1}'
        else:
            label = segment_label if segment_label and seg_idx == 0 else f'整定段 {seg_idx + 1}'
        
        ax.axvspan(t_start, t_end, alpha=0.15, color=color, 
                  label=label if (add_labels and seg_idx == 0) else None, zorder=0)
        
        # 添加垂直线
        ax.axvline(t_start, color=color, linestyle='--', linewidth=2, alpha=0.8, zorder=4)
        ax.axvline(t_end, color=color, linestyle='--', linewidth=2, alpha=0.8, zorder=4)
        
        # 添加文本标注（显示开始和结束时间）
        if add_text:
            y_max = ax.get_ylim()[1]
            y_min = ax.get_ylim()[0]
            y_range = y_max - y_min
            
            # 格式化时间显示（保留2位小数）
            t_start_str = f'{t_start:.2f}s'
            t_end_str = f'{t_end:.2f}s'
            
            # 每段都在开始位置标注（显示时间）
            if seg_idx == 0:
                # 第一段：标注"段1开始"和时间
                ax.text(t_start, y_max * 0.95, f'段{seg_idx + 1}开始\n{t_start_str}', 
                       rotation=90, verticalalignment='top', fontsize=9,
                       bbox=dict(boxstyle='round', facecolor=color, alpha=0.5))
            else:
                # 后续段：标注"段X开始"和时间
                ax.text(t_start, y_max * 0.90, f'段{seg_idx + 1}开始\n{t_start_str}', 
                       rotation=90, verticalalignment='top', fontsize=8,
                       bbox=dict(boxstyle='round', facecolor=color, alpha=0.4))
            
            # 每段都在结束位置标注（显示时间）
            if seg_idx == len(segments_list) - 1:
                # 最后一段：标注"段X结束"和时间
                ax.text(t_end, y_max * 0.95, f'段{seg_idx + 1}结束\n{t_end_str}', 
                       rotation=90, verticalalignment='top', fontsize=9,
                       bbox=dict(boxstyle='round', facecolor=color, alpha=0.5))
            else:
                # 中间段：标注"段X结束"和时间
                ax.text(t_end, y_max * 0.90, f'段{seg_idx + 1}结束\n{t_end_str}', 
                       rotation=90, verticalalignment='top', fontsize=8,
                       bbox=dict(boxstyle='round', facecolor=color, alpha=0.4))


def _calculate_performance_metrics(pv, sv):
    """
    计算性能指标（提取为独立函数）
    
    Args:
        pv: 过程值数组
        sv: 设定值数组
        
    Returns:
        性能指标字典
    """
    error = pv - sv
    return {
        'MAE': np.mean(np.abs(error)),
        'RMSE': np.sqrt(np.mean(error ** 2)),
        'Max Error': np.max(np.abs(error)),
        'Std Error': np.std(error)
    }


def _format_model_info_text(old_pid_params, new_pid_params, model_info):
    """
    格式化模型信息文本（提取为独立函数）
    
    Args:
        old_pid_params: 旧PID参数
        new_pid_params: 新PID参数
        model_info: 模型信息
        
    Returns:
        格式化的文本字符串
    """
    info_text = "PID参数信息\n" + "=" * 40 + "\n"
    
    if old_pid_params is not None:
        info_text += f"旧参数:\n"
        info_text += f"  Pb = {old_pid_params.get('pb', 'N/A'):.2f}%\n"
        info_text += f"  Ti = {old_pid_params.get('ti', 'N/A'):.2f}s\n"
        info_text += f"  Td = {old_pid_params.get('td', 'N/A'):.2f}s\n\n"
    
    if new_pid_params is not None:
        info_text += f"新参数:\n"
        info_text += f"  Pb = {new_pid_params.get('pb', 'N/A'):.2f}%\n"
        info_text += f"  Ti = {new_pid_params.get('ti', 'N/A'):.2f}s\n"
        info_text += f"  Td = {new_pid_params.get('td', 'N/A'):.2f}s\n\n"
    
    if model_info is not None:
        info_text += f"系统模型:\n"
        info_text += f"  类型: {model_info.get('model_type', 'N/A')}\n"
        if 'params' in model_info:
            params = model_info['params']
            if isinstance(params, tuple):
                if len(params) == 3:
                    info_text += f"  K = {params[0]:.3f}\n"
                    info_text += f"  T = {params[1]:.3f}s\n"
                    info_text += f"  L = {params[2]:.3f}s\n"
                elif len(params) == 2:
                    info_text += f"  K = {params[0]:.3f}\n"
                    info_text += f"  T = {params[1]:.3f}s\n"
    
    return info_text


def visualize_tuning_comparison(t_original, pv_original, mv_original, sv_original,
                                pv_simulated, mv_simulated,
                                tuning_segment_indices=None,
                                old_pid_params=None, new_pid_params=None,
                                model_info=None, save_path=None,
                                all_segments_results=None, 
                                non_steady_segments_for_annotation=None,
                                show_plot=False):
    """
    可视化PID整定结果对比
    
    Args:
        t_original: 原始时间数组
        pv_original: 原始过程值数组
        mv_original: 原始控制输出数组
        sv_original: 原始设定值数组
        pv_simulated: 新PID参数仿真的过程值数组
        mv_simulated: 新PID参数仿真的控制输出数组
        tuning_segment_indices: 整定段索引 (start_idx, end_idx)，可选
        old_pid_params: 旧PID参数字典 {'pb': pb, 'ti': ti, 'td': td}，可选
        new_pid_params: 新PID参数字典 {'pb': pb, 'ti': ti, 'td': td}，可选
        model_info: 模型信息字典，可选
        save_path: 保存路径，如果为None则不保存
        all_segments_results: 所有段的整定结果，可选
        show_plot: 是否显示可视化图形（True显示，False不显示）
    """
    # 设置中文字体（必须在所有绘图操作之前设置，确保所有子图都能正确显示中文）
    plt.rcParams["font.family"] = ["Heiti TC"]
    plt.rcParams['font.sans-serif'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
    
    # 确保monospace字体也能显示中文（用于ax5和ax6的文本显示）
    plt.rcParams['font.monospace'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans Mono"]
    
    # 创建图形
    fig = plt.figure(figsize=(16, 12))
    gs = fig.add_gridspec(4, 2, hspace=0.3, wspace=0.3)
    
    # 主标题
    fig.suptitle('PID参数整定结果对比分析', fontsize=18, fontweight='bold', y=0.98)
    
    # 子图1: PV对比（主要对比图）
    ax1 = fig.add_subplot(gs[0, :])
    
    # 绘制原始数据
    ax1.plot(t_original, pv_original, 'b-', linewidth=2, label='原始PV', alpha=0.7, zorder=1)
    ax1.plot(t_original, sv_original, 'r--', linewidth=2.5, label='设定值SV', alpha=0.9, zorder=2)
    
    # 绘制仿真数据（只在有仿真数据时绘制，即重新整定后才显示）
    if pv_simulated is not None:
        ax1.plot(t_original, pv_simulated, 'g-', linewidth=2.5, label='新PID参数仿真PV', alpha=0.9, zorder=3)
    
    # 标注整定段（支持多段标注）
    if all_segments_results is not None and len(all_segments_results) > 0:
        # 多段整定：标注所有段
        all_segment_indices = [seg_result.get('segment_indices') for seg_result in all_segments_results 
                              if seg_result.get('segment_indices') is not None]
        if len(all_segment_indices) > 0:
            _add_tuning_segment_annotation(ax1, t_original, all_segment_indices, 
                                         add_labels=True, add_text=True)
    elif tuning_segment_indices is not None:
        # 单段整定
        _add_tuning_segment_annotation(ax1, t_original, tuning_segment_indices, 
                                       add_labels=True, add_text=True)
    
    # 标注非稳态段（即使不需要整定也要标注）
    if non_steady_segments_for_annotation is not None and len(non_steady_segments_for_annotation) > 0:
        # 将非稳态段转换为索引列表用于标注
        non_steady_indices = [(seg[0], seg[1]) for seg in non_steady_segments_for_annotation]
        _add_tuning_segment_annotation(ax1, t_original, non_steady_indices, 
                                     add_labels=True, add_text=True, 
                                     segment_label='非稳态段（无需整定）')
    
    ax1.set_xlabel('时间 (s)', fontsize=12)
    ax1.set_ylabel('过程值 (PV)', fontsize=12)
    ax1.set_title('过程值对比：原始数据 vs 新PID参数仿真', fontsize=14, fontweight='bold')
    ax1.legend(loc='best', fontsize=11, framealpha=0.9)
    ax1.grid(True, alpha=0.3)
    
    # 子图2: MV对比
    ax2 = fig.add_subplot(gs[1, :])
    ax2.plot(t_original, mv_original, 'b-', linewidth=2, label='原始MV', alpha=0.7)
    if mv_simulated is not None:
        ax2.plot(t_original, mv_simulated, 'g-', linewidth=2.5, label='新PID参数仿真MV', alpha=0.9)
    
    # 标注整定段（支持多段标注）
    if all_segments_results is not None and len(all_segments_results) > 0:
        all_segment_indices = [seg_result.get('segment_indices') for seg_result in all_segments_results 
                              if seg_result.get('segment_indices') is not None]
        if len(all_segment_indices) > 0:
            _add_tuning_segment_annotation(ax2, t_original, all_segment_indices, 
                                         add_labels=False, add_text=True)  # 改为True，显示文本标注
    elif tuning_segment_indices is not None:
        _add_tuning_segment_annotation(ax2, t_original, tuning_segment_indices, 
                                       add_labels=False, add_text=True)  # 改为True，显示文本标注
    
    # 标注非稳态段（即使不需要整定也要标注）
    if non_steady_segments_for_annotation is not None and len(non_steady_segments_for_annotation) > 0:
        non_steady_indices = [(seg[0], seg[1]) for seg in non_steady_segments_for_annotation]
        _add_tuning_segment_annotation(ax2, t_original, non_steady_indices, 
                                     add_labels=False, add_text=True, 
                                     segment_label='非稳态段（无需整定）')
    
    ax2.set_xlabel('时间 (s)', fontsize=12)
    ax2.set_ylabel('控制输出 (MV)', fontsize=12)
    ax2.set_title('控制输出对比：原始数据 vs 新PID参数仿真', fontsize=14, fontweight='bold')
    ax2.legend(loc='best', fontsize=11, framealpha=0.9)
    ax2.grid(True, alpha=0.3)
    
    # 子图3: 误差对比
    ax3 = fig.add_subplot(gs[2, 0])
    error_original = pv_original - sv_original
    ax3.plot(t_original, error_original, 'b-', linewidth=2, label='原始误差', alpha=0.7)
    if pv_simulated is not None:
        error_simulated = pv_simulated - sv_original
        ax3.plot(t_original, error_simulated, 'g-', linewidth=2.5, label='新PID参数误差', alpha=0.9)
    ax3.axhline(0, color='r', linestyle='--', linewidth=1, alpha=0.5)
    
    # 标注整定段（支持多段标注）
    if all_segments_results is not None and len(all_segments_results) > 0:
        all_segment_indices = [seg_result.get('segment_indices') for seg_result in all_segments_results 
                              if seg_result.get('segment_indices') is not None]
        if len(all_segment_indices) > 0:
            _add_tuning_segment_annotation(ax3, t_original, all_segment_indices, 
                                         add_labels=False, add_text=True)  # 改为True，显示文本标注
    elif tuning_segment_indices is not None:
        _add_tuning_segment_annotation(ax3, t_original, tuning_segment_indices, 
                                       add_labels=False, add_text=True)  # 改为True，显示文本标注
    
    # 标注非稳态段（即使不需要整定也要标注）
    if non_steady_segments_for_annotation is not None and len(non_steady_segments_for_annotation) > 0:
        non_steady_indices = [(seg[0], seg[1]) for seg in non_steady_segments_for_annotation]
        _add_tuning_segment_annotation(ax3, t_original, non_steady_indices, 
                                     add_labels=False, add_text=True, 
                                     segment_label='非稳态段（无需整定）')
    
    ax3.set_xlabel('时间 (s)', fontsize=12)
    ax3.set_ylabel('误差 (PV - SV)', fontsize=12)
    ax3.set_title('误差对比', fontsize=13, fontweight='bold')
    ax3.legend(loc='best', fontsize=10, framealpha=0.9)
    ax3.grid(True, alpha=0.3)
    
    # 子图4: 性能指标对比
    ax4 = fig.add_subplot(gs[2, 1])
    
    # 计算性能指标
    metrics_original = _calculate_performance_metrics(pv_original, sv_original)
    metrics_names = ['MAE', 'RMSE', 'Max Error', 'Std Error']
    original_values = [metrics_original[m] for m in metrics_names]
    
    x = np.arange(len(metrics_names))
    width = 0.35
    ax4.bar(x - width/2, original_values, width, label='原始参数', alpha=0.7, color='blue')
    
    if pv_simulated is not None:
        metrics_simulated = _calculate_performance_metrics(pv_simulated, sv_original)
        simulated_values = [metrics_simulated[m] for m in metrics_names]
        ax4.bar(x + width/2, simulated_values, width, label='新参数', alpha=0.7, color='green')
    
    ax4.set_ylabel('误差值', fontsize=12)
    ax4.set_title('性能指标对比', fontsize=13, fontweight='bold')
    ax4.set_xticks(x)
    ax4.set_xticklabels(metrics_names, rotation=45, ha='right')
    ax4.legend(loc='best', fontsize=10, framealpha=0.9)
    ax4.grid(True, alpha=0.3, axis='y')
    
    # 子图5: PID参数信息（支持多段显示）
    ax5 = fig.add_subplot(gs[3, 0])
    ax5.axis('off')
    if all_segments_results is not None and len(all_segments_results) > 0:
        # 多段整定：显示所有段的参数信息
        info_text = "分段整定结果\n" + "=" * 40 + "\n"
        for seg_result in all_segments_results:
            seg_idx = seg_result.get('segment_index', 0)
            seg_sv = seg_result.get('segment_setpoint', 0.0)
            seg_pb = seg_result.get('pb', 100.0)
            seg_ti = seg_result.get('ti', 0.0)
            seg_td = seg_result.get('td', 0.0)
            seg_model = seg_result.get('model_type', 'N/A')
            used_sim = seg_result.get('used_simulated_data', False)
            
            info_text += f"\n段 {seg_idx} (SV={seg_sv:.2f}):\n"
            info_text += f"  Pb={seg_pb:.2f}%, Ti={seg_ti:.2f}s, Td={seg_td:.2f}s\n"
            info_text += f"  模型: {seg_model}\n"
            if used_sim:
                info_text += f"  (基于前段参数仿真)\n"
        
        # 添加最后一段的详细信息
        if new_pid_params is not None:
            info_text += f"\n最终参数:\n"
            info_text += f"  Pb={new_pid_params.get('pb', 'N/A'):.2f}%\n"
            info_text += f"  Ti={new_pid_params.get('ti', 'N/A'):.2f}s\n"
            info_text += f"  Td={new_pid_params.get('td', 'N/A'):.2f}s\n"
        
        if model_info is not None:
            info_text += f"\n最终模型:\n"
            info_text += f"  类型: {model_info.get('model_type', 'N/A')}\n"
            if 'params' in model_info:
                params = model_info['params']
                if isinstance(params, tuple):
                    if len(params) == 3:
                        info_text += f"  K={params[0]:.3f}, T={params[1]:.3f}s, L={params[2]:.3f}s\n"
                    elif len(params) == 2:
                        info_text += f"  K={params[0]:.3f}, T={params[1]:.3f}s\n"
    else:
        # 单段整定：显示标准信息
        info_text = _format_model_info_text(old_pid_params, new_pid_params, model_info)
    
    ax5.text(0.05, 0.5, info_text, fontsize=10, family='monospace',
            verticalalignment='center', bbox=dict(boxstyle='round', 
            facecolor='wheat', alpha=0.3))
    
    # 子图6: 性能改进统计
    ax6 = fig.add_subplot(gs[3, 1])
    ax6.axis('off')
    
    improvement_text = "性能改进\n" + "=" * 40 + "\n"
    
    if pv_simulated is not None:
        for metric in metrics_names:
            orig_val = metrics_original[metric]
            sim_val = metrics_simulated[metric]
            improvement = ((orig_val - sim_val) / orig_val * 100) if orig_val > 0 else 0
            improvement_text += f"{metric}:\n"
            improvement_text += f"  原始: {orig_val:.3f}\n"
            improvement_text += f"  新参数: {sim_val:.3f}\n"
            improvement_text += f"  改进: {improvement:+.1f}%\n\n"
    else:
        improvement_text += "无需整定，无性能改进数据\n"
        if non_steady_segments_for_annotation is not None and len(non_steady_segments_for_annotation) > 0:
            improvement_text += f"\n检测到 {len(non_steady_segments_for_annotation)} 个非稳态段\n"
            improvement_text += "（已标注，但无需重新整定）\n"
    
    ax6.text(0.1, 0.5, improvement_text, fontsize=11, family='monospace',
            verticalalignment='center', bbox=dict(boxstyle='round', 
            facecolor='lightgreen', alpha=0.3))
    
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    
    # 保存图形
    if save_path is not None:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"\n✅ 图形已保存至: {save_path}")
    
    # 根据show_plot参数决定是否显示图形
    if show_plot:
        plt.show()
    else:
        plt.close(fig)  # 不显示时关闭图形以释放内存
    
    return fig


def simulate_and_visualize(t, pv_original, mv_original, sv_original,
                          tuning_result, tuning_segment_indices=None,
                          old_pid_params=None, save_path=None, verbose=False, show_plot=False):
    """
    完整的仿真和可视化流程
    
    Args:
        t: 时间数组
        pv_original: 原始过程值数组
        mv_original: 原始控制输出数组
        sv_original: 原始设定值数组
        tuning_result: 整定结果字典（来自SystemIdentifier.auto_tune_from_json）
        tuning_segment_indices: 整定段索引 (start_idx, end_idx)，可选
        old_pid_params: 旧PID参数字典，可选
        save_path: 保存路径，可选
        verbose: 是否打印详细信息
        show_plot: 是否显示可视化图形（True显示，False不显示）
        
    Returns:
        fig: matplotlib图形对象
    """
    if tuning_result is None:
        print("⚠️ 整定结果为空，无法进行仿真")
        return None
    
    # 检查是否是不需要整定但需要标注非稳态段的情况
    if tuning_result.get('no_tuning_needed', False):
        # 不需要整定，但需要标注非稳态段
        non_steady_segments = tuning_result.get('non_steady_segments', [])
        if len(non_steady_segments) > 0:
            print(f"📊 检测到 {len(non_steady_segments)} 个非稳态段需要标注（无需整定）")
            # 只进行可视化标注，不进行仿真
            return visualize_tuning_comparison(
                t, pv_original, mv_original, sv_original,
                None, None,  # 不提供仿真数据
                tuning_segment_indices=None,  # 使用非稳态段作为标注
                old_pid_params=old_pid_params,
                new_pid_params=None,  # 没有新参数
                model_info=None,
                save_path=save_path,
                all_segments_results=None,
                non_steady_segments_for_annotation=non_steady_segments,  # 传递非稳态段用于标注
                show_plot=show_plot
            )
        else:
            print("⚠️ 无需整定且无非稳态段需要标注")
            return None
    
    # 提取新PID参数
    new_pid_params = {
        'pb': tuning_result.get('pb', 100.0),
        'ti': tuning_result.get('ti', 0.0),
        'td': tuning_result.get('td', 0.0)
    }
    
    # 提取模型信息
    model_type = tuning_result.get('model_type', 'fopdt')
    model_params = tuning_result.get('params', None)
    
    if model_params is None:
        print("⚠️ 模型参数为空，无法进行仿真")
        return None
    
    # 确定系统模型函数（使用字典映射，更清晰，使用 ModelIdentifier）
    MODEL_TYPE_MAP = {
        'fopdt': ModelIdentifier.fopdt_model,
        'first_order': ModelIdentifier.fopdt_model,  # 一阶合并到FOPDT
        'second_order': ModelIdentifier.second_order_model,
        'integral_delay': ModelIdentifier.integral_delay_model
    }
    
    system_model = MODEL_TYPE_MAP.get(model_type, ModelIdentifier.fopdt_model)
    
    # 处理一阶模型（需要添加L=0）
    if model_type in ['fopdt', 'first_order'] and len(model_params) == 2:
        model_params = (model_params[0], model_params[1], 0.0)
    elif model_type not in MODEL_TYPE_MAP and len(model_params) == 2:
        # 默认使用FOPDT，添加L=0
        model_params = (model_params[0], model_params[1], 0.0)
    
    # 获取设定值（使用平均值作为默认值，但会传递完整的设定值数组）
    setpoint = np.mean(sv_original) if len(sv_original) > 0 else np.mean(pv_original)
    
    # 优化：如果提供了整定段索引，从整定段开始处获取初始值
    # 这样可以确保仿真从整定段开始，而不是从数据开始
    if tuning_segment_indices is not None:
        start_idx, end_idx = tuning_segment_indices
        start_idx = max(0, min(start_idx, len(pv_original) - 1))
        # 从整定段开始处获取初始值
        initial_pv = pv_original[start_idx] if start_idx < len(pv_original) else pv_original[0]
        initial_mv = mv_original[start_idx] if mv_original is not None and start_idx < len(mv_original) else (mv_original[0] if mv_original is not None else None)
        if verbose:
            print(f"   - 使用整定段起始位置（索引 {start_idx}）的初始值: PV={initial_pv:.3f}")
    else:
        # 如果没有整定段信息，使用数据开始处的值
        initial_pv = pv_original[0] if len(pv_original) > 0 else 0.0
        initial_mv = mv_original[0] if len(mv_original) > 0 else None
    
    # 进一步优化：如果使用了分段整定，检查是否有all_segments_results
    # 如果有，使用第一个整定段的起始位置作为初始值
    all_segments_results = tuning_result.get('all_segments_results', None)
    if all_segments_results is not None and len(all_segments_results) > 0:
        # 找到第一个实际进行整定的段（不是跳过的段）
        first_tuning_seg = all_segments_results[0]
        if 'segment_indices' in first_tuning_seg:
            seg_start_idx, _ = first_tuning_seg['segment_indices']
            seg_start_idx = max(0, min(seg_start_idx, len(pv_original) - 1))
            initial_pv = pv_original[seg_start_idx] if seg_start_idx < len(pv_original) else initial_pv
            if mv_original is not None and seg_start_idx < len(mv_original):
                initial_mv = mv_original[seg_start_idx]
            if verbose:
                print(f"   - 使用分段整定第一个段的起始位置（索引 {seg_start_idx}）的初始值: PV={initial_pv:.3f}")
    
    # 检查设定值是否变化
    sv_changes = np.any(np.abs(np.diff(sv_original)) > 0.1) if len(sv_original) > 1 else False
    
    if verbose:
        print(f"\n🔍 开始仿真:")
        print(f"   - 模型类型: {model_type}")
        print(f"   - 模型参数: {model_params}")
        print(f"   - 新PID参数: Pb={new_pid_params['pb']:.2f}%, "
              f"Ti={new_pid_params['ti']:.2f}s, Td={new_pid_params['td']:.2f}s")
        print(f"   - 设定值: {setpoint:.3f} (平均)")
        if sv_changes:
            print(f"   - ⚠️ 检测到设定值变化，将使用时变设定值进行仿真")
            print(f"   - 设定值范围: [{np.min(sv_original):.3f}, {np.max(sv_original):.3f}]")
        print(f"   - 初始PV: {initial_pv:.3f}")
    
    # 优化：如果提供了整定段索引，分段进行仿真
    # 在整定段之前使用原始数据，在整定段使用新PID参数仿真
    if tuning_segment_indices is not None:
        start_idx, end_idx = tuning_segment_indices
        start_idx = max(0, min(start_idx, len(t) - 1))
        end_idx = max(start_idx + 1, min(end_idx, len(t)))
        
        if verbose:
            print(f"   - 使用分段仿真: 索引 [0, {start_idx}) 使用原始数据, "
                  f"[{start_idx}, {end_idx}) 使用新PID参数仿真")
        
        # 初始化仿真结果数组
        # 关键：整定段之前的部分应该设置为NaN，这样可视化时不会显示新参数的仿真轨迹
        # 只有在整定段开始后才显示新参数的仿真轨迹
        pv_simulated = np.full_like(pv_original, np.nan)
        mv_simulated = np.full_like(mv_original, np.nan) if mv_original is not None else None
        
        # 只对整定段进行仿真
        if start_idx < len(t) and end_idx > start_idx:
            # 优化：对于CASE_3（从稳态到非稳态），应该使用整定段开始前的稳态PV值作为初始值
            # 这样新参数才能从稳态开始响应，而不是从已经偏离的状态开始
            if start_idx > 0:
                # 检查整定段开始前是否有稳态段
                lookback_window = min(30, start_idx)  # 向前看最多30个点
                if lookback_window >= 10:
                    prev_segment = pv_original[start_idx - lookback_window:start_idx]
                    prev_sv = sv_original[start_idx - lookback_window:start_idx] if len(sv_original) == len(t) else setpoint
                    prev_sv_mean = np.mean(prev_sv) if isinstance(prev_sv, np.ndarray) else prev_sv
                    
                    # 检查前一段是否稳态
                    try:
                        from ..data.analyzer import DataAnalyzer
                    except ImportError:
                        import sys
                        import os
                        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
                        from core.data.analyzer import DataAnalyzer
                    analyzer = DataAnalyzer()
                    is_prev_steady = analyzer.is_steady_state(prev_segment, prev_sv_mean, tol=0.5, std_tol=0.2, min_len=10)
                    
                    if is_prev_steady:
                        # 使用稳态段的平均值作为初始PV
                        seg_initial_pv = np.mean(prev_segment)
                        if verbose:
                            print(f"   - 检测到整定段前有稳态段，使用稳态PV值作为初始值: {seg_initial_pv:.3f} (设定值: {prev_sv_mean:.3f})")
                    else:
                        # 前一段不稳态，使用整定段开始时的值
                        seg_initial_pv = pv_original[start_idx] if start_idx < len(pv_original) else initial_pv
                else:
                    seg_initial_pv = pv_original[start_idx] if start_idx < len(pv_original) else initial_pv
            else:
                seg_initial_pv = pv_original[start_idx] if start_idx < len(pv_original) else initial_pv
            
            # 延长整定段到数据结束，确保系统有足够时间收敛
            # 但保持标注的整定段不变（只延长仿真段）
            extended_end_idx = len(t)  # 延长到数据结束
            t_seg = t[start_idx:extended_end_idx]
            sv_seg = sv_original[start_idx:extended_end_idx] if len(sv_original) == len(t) else sv_original
            mv_ref_seg = mv_original[start_idx:extended_end_idx] if mv_original is not None else None
            pv_ref_seg = pv_original[start_idx:extended_end_idx]
            
            seg_initial_mv = mv_original[start_idx] if mv_original is not None and start_idx < len(mv_original) else initial_mv
            
            if verbose:
                print(f"   - 整定段仿真: 索引 [{start_idx}, {extended_end_idx}), 初始PV: {seg_initial_pv:.3f}")
                print(f"   - 标注段: [{start_idx}, {end_idx}), 仿真段延长到数据结束以观察收敛")
            
            # 对整定段进行仿真（延长到数据结束）
            pv_seg_sim, mv_seg_sim = simulate_system_with_pid(
                t_seg, system_model, model_params, new_pid_params, setpoint,
                initial_pv=seg_initial_pv, initial_mv=seg_initial_mv, verbose=verbose,
                setpoint_array=sv_seg,
                mv_reference=mv_ref_seg,
                pv_reference=pv_ref_seg
            )
            
            # 将仿真结果替换到对应位置（仿真延伸到数据结束，可以看到新参数在整个剩余时间段的表现）
            seg_len = min(len(pv_seg_sim), extended_end_idx - start_idx)
            pv_simulated[start_idx:start_idx + seg_len] = pv_seg_sim[:seg_len]
            if mv_simulated is not None and mv_seg_sim is not None:
                mv_simulated[start_idx:start_idx + seg_len] = mv_seg_sim[:seg_len]
    elif all_segments_results is not None and len(all_segments_results) > 0:
        # 多段整定：对每个整定段分别进行仿真
        # 关键：每个段都使用该段自己的新参数进行仿真（基于前一段参数整定出的新参数）
        if verbose:
            print(f"   - 使用多段仿真: 共 {len(all_segments_results)} 个整定段")
        
        # 初始化仿真结果数组
        # 关键：整定段之前的部分应该设置为NaN，这样可视化时不会显示新参数的仿真轨迹
        # 只有在整定段开始后才显示新参数的仿真轨迹
        pv_simulated = np.full_like(pv_original, np.nan)
        mv_simulated = np.full_like(mv_original, np.nan) if mv_original is not None else None
        
        # 对每个整定段进行仿真（使用该段自己的新参数）
        # 关键：每个段的仿真都延长到下一个整定段开始，或到数据结束
        prev_seg_end_pv = None
        for seg_idx, seg_result in enumerate(all_segments_results):
            if 'segment_indices' not in seg_result:
                continue
            
            seg_start_idx, seg_end_idx = seg_result['segment_indices']
            seg_start_idx = max(0, min(seg_start_idx, len(t) - 1))
            seg_end_idx = max(seg_start_idx + 1, min(seg_end_idx, len(t)))
            
            # 确定该段的仿真结束位置：
            # 如果是最后一段，延长到数据结束；否则延长到下一个整定段开始
            if seg_idx < len(all_segments_results) - 1:
                # 找到下一个整定段的开始位置
                next_seg_result = all_segments_results[seg_idx + 1]
                if 'segment_indices' in next_seg_result:
                    next_seg_start_idx, _ = next_seg_result['segment_indices']
                    extended_end_idx = min(next_seg_start_idx, len(t))
                else:
                    extended_end_idx = len(t)
            else:
                # 最后一段，延长到数据结束
                extended_end_idx = len(t)
            
            if seg_start_idx < len(t) and extended_end_idx > seg_start_idx:
                t_seg = t[seg_start_idx:extended_end_idx]
                sv_seg = sv_original[seg_start_idx:extended_end_idx] if len(sv_original) == len(t) else sv_original
                mv_ref_seg = mv_original[seg_start_idx:extended_end_idx] if mv_original is not None else None
                pv_ref_seg = pv_original[seg_start_idx:extended_end_idx]
                
                # 获取该段的新PID参数（每个段都有自己的新参数）
                seg_pid_params = {
                    'pb': seg_result.get('pb', new_pid_params['pb']),
                    'ti': seg_result.get('ti', new_pid_params['ti']),
                    'td': seg_result.get('td', new_pid_params['td'])
                }
                
                # 获取该段的模型参数（如果有的话，否则使用全局模型参数）
                seg_model_type = seg_result.get('model_type', model_type)
                seg_model_params = seg_result.get('params', model_params)
                
                # 确定该段的系统模型函数
                seg_system_model = MODEL_TYPE_MAP.get(seg_model_type, system_model)
                
                # 处理一阶模型
                if seg_model_type in ['fopdt', 'first_order'] and len(seg_model_params) == 2:
                    seg_model_params = (seg_model_params[0], seg_model_params[1], 0.0)
                elif seg_model_type not in MODEL_TYPE_MAP and len(seg_model_params) == 2:
                    seg_model_params = (seg_model_params[0], seg_model_params[1], 0.0)
                
                # 从整定段开始处获取初始值
                # 如果是第一段，检查前面是否有稳态段，使用稳态值；否则使用原始数据的初始值
                # 如果不是第一段，使用前一段仿真结束时的PV值
                if seg_idx == 0:
                    # 检查整定段开始前是否有稳态段
                    if seg_start_idx > 0:
                        lookback_window = min(30, seg_start_idx)
                        if lookback_window >= 10:
                            prev_segment = pv_original[seg_start_idx - lookback_window:seg_start_idx]
                            prev_sv = sv_original[seg_start_idx - lookback_window:seg_start_idx] if len(sv_original) == len(t) else setpoint
                            prev_sv_mean = np.mean(prev_sv) if isinstance(prev_sv, np.ndarray) else prev_sv
                            
                            try:
                                from ..data.analyzer import DataAnalyzer
                            except ImportError:
                                import sys
                                import os
                                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
                                from core.data.analyzer import DataAnalyzer
                            analyzer = DataAnalyzer()
                            is_prev_steady = analyzer.is_steady_state(prev_segment, prev_sv_mean, tol=0.5, std_tol=0.2, min_len=10)
                            
                            if is_prev_steady:
                                seg_initial_pv = np.mean(prev_segment)
                                if verbose:
                                    print(f"   - 段 {seg_idx + 1}: 检测到整定段前有稳态段，使用稳态PV值作为初始值: {seg_initial_pv:.3f}")
                            else:
                                seg_initial_pv = pv_original[seg_start_idx] if seg_start_idx < len(pv_original) else initial_pv
                        else:
                            seg_initial_pv = pv_original[seg_start_idx] if seg_start_idx < len(pv_original) else initial_pv
                    else:
                        seg_initial_pv = pv_original[seg_start_idx] if seg_start_idx < len(pv_original) else initial_pv
                else:
                    # 使用前一段仿真结束时的PV值
                    seg_initial_pv = prev_seg_end_pv if prev_seg_end_pv is not None else pv_original[seg_start_idx]
                
                seg_initial_mv = mv_original[seg_start_idx] if mv_original is not None and seg_start_idx < len(mv_original) else initial_mv
                
                if verbose:
                    print(f"   - 段 {seg_idx + 1} 仿真: 索引 [{seg_start_idx}, {extended_end_idx}), 初始PV: {seg_initial_pv:.3f}")
                    print(f"   - 标注段: [{seg_start_idx}, {seg_end_idx}), 仿真段延长到索引 {extended_end_idx}")
                
                # 对该段使用该段的新参数进行仿真（延长到下一个整定段开始或数据结束）
                pv_seg_sim, mv_seg_sim = simulate_system_with_pid(
                    t_seg, seg_system_model, seg_model_params, seg_pid_params,
                    setpoint, initial_pv=seg_initial_pv, initial_mv=seg_initial_mv, verbose=False,
                    setpoint_array=sv_seg,
                    mv_reference=mv_ref_seg,
                    pv_reference=pv_ref_seg
                )
                
                # 将仿真结果替换到对应位置（延长到下一个整定段开始或数据结束）
                seg_len = min(len(pv_seg_sim), extended_end_idx - seg_start_idx)
                pv_simulated[seg_start_idx:seg_start_idx + seg_len] = pv_seg_sim[:seg_len]
                if mv_simulated is not None and mv_seg_sim is not None:
                    mv_simulated[seg_start_idx:seg_start_idx + seg_len] = mv_seg_sim[:seg_len]
                
                # 保存该段仿真结束时的PV值，用于下一段
                prev_seg_end_pv = pv_seg_sim[-1] if len(pv_seg_sim) > 0 else pv_original[min(extended_end_idx - 1, len(pv_original) - 1)]
    else:
        # 如果没有提供整定段信息，说明没有进行整定或整定失败
        # 根据用户要求：不需要一开始就显示新参数下pv的仿真轨迹
        # 只有在检测到扰动点并重新整定出新参数后才显示仿真轨迹
        if verbose:
            print("   - ⚠️ 未提供整定段信息，不进行新参数仿真（保持原始数据）")
        # 不进行仿真，保持原始数据
        pv_simulated = None
        mv_simulated = None
    
    # 准备模型信息
    model_info = {
        'model_type': model_type,
        'params': model_params
    }
    
    # 获取所有段的整定结果（如果存在）
    all_segments_results = tuning_result.get('all_segments_results', None)
    
    # 获取非稳态段信息（如果存在，用于标注）
    non_steady_segments_for_annotation = tuning_result.get('non_steady_segments', None)
    
    # 可视化
    fig = visualize_tuning_comparison(
        t, pv_original, mv_original, sv_original,
        pv_simulated, mv_simulated,
        tuning_segment_indices=tuning_segment_indices,
        old_pid_params=old_pid_params,
        new_pid_params=new_pid_params,
        model_info=model_info,
        save_path=save_path,
        all_segments_results=all_segments_results,  # 传递所有段的整定结果
        non_steady_segments_for_annotation=non_steady_segments_for_annotation,  # 传递非稳态段用于标注
        show_plot=show_plot  # 传递显示控制参数
    )
    
    return fig

