"""共享可视化工具模块
==============================

从 test_model_selector_real.py 提取的可视化核心代码，
供 test_model_selector_real.py、test_synthetic_tuning.py、daxie_data/run_tuning.py 共同调用。

核心工具函数：
- resolve_process_model_type: 统一过程模型类型判断（FO_INTEGRATOR 等）
- normalize_pid_params: PID 参数标准化 (大小写、Ki/Kd 推算)
- convert_to_arrays: 历史数据转 numpy 数组
- simulate_pid_prediction: 统一的新 PID 闭环仿真引擎

可视化函数：
- visualize_fitting_result: 主可视化（含闭环验证）
- visualize_new_pid_simulation: 新 PID 参数仿真预测图
- visualize_raw_data: 原始数据可视化
"""

import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from core.algorithm.model_type.utils import normalize_pid_keys


# ============================================================
# 全局字体配置（解决中文字符 missing glyph 警告）
# ============================================================
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


# ============================================================
# 通用工具函数
# ============================================================

def convert_to_arrays(data: List[Dict]) -> tuple:
    """将历史数据转换为 numpy 数组"""
    pv_array = np.array([d.get('pv', 0.0) for d in data], dtype=np.float64)
    sv_array = np.array([d.get('sv', 0.0) for d in data], dtype=np.float64)
    mv_array = np.array([d.get('mv', 0.0) for d in data], dtype=np.float64)
    timestamps = np.array([d.get('timestamp', 0) for d in data], dtype=np.int64)
    return pv_array, sv_array, mv_array, timestamps


def resolve_process_model_type(fitting_result: Dict) -> Dict:
    """统一过程模型类型判断

    将散落在各子图中的积分过程判定逻辑集中到一处。

    Args:
        fitting_result: ModelSelector / TuningOrchestrator 的完整输出

    Returns:
        dict 包含:
            model_type: str — 修正后的模型类型 (e.g. 'FO_INTEGRATOR')
            is_integrating: bool — 是否为积分过程
            K: float — 过程增益 (积分过程时可能已被修正为 K_int)
            K_int: float — 积分增益 (仅积分过程有效, 否则 0.0)
            T1, T2, L: float — 模型参数
    """
    model_type = fitting_result.get('model_type', 'FOPDT')
    model_params = fitting_result.get('model_parameters', {}).copy()
    pid_params = fitting_result.get('pid_parameters', {})

    K = model_params.get('K', 1.0)
    T1 = model_params.get('T1', 10.0)
    T2 = model_params.get('T2', 0.0)
    L = model_params.get('L', 0.0)

    # 判断是否为积分过程
    is_integrating = (
        model_type in ['FO_INTEGRATOR', 'SO_INTEGRATOR', 'FOPI', 'SOPI', 'INTEGRATOR']
        or pid_params.get('method') == 'integrating_fallback'
        or 'K_int' in pid_params
    )

    K_int = 0.0
    if is_integrating:
        # 统一修正 model_type
        if model_type not in ['FO_INTEGRATOR', 'SO_INTEGRATOR', 'FOPI', 'SOPI', 'INTEGRATOR']:
            model_type = 'FO_INTEGRATOR'

        # 计算 K_int: 优先取 pid_params、model_params 中的显式值
        K_int = pid_params.get('K_int', model_params.get('K_int', 0.0))
        if K_int < 1e-9:
            # fallback: K_int = K / T1
            K_int = K / max(T1, 1.0) if T1 > 0 else K

        # integrating_fallback 时修正存储的 K 为 K_int
        if pid_params.get('method') == 'integrating_fallback':
            K = K_int

    return {
        'model_type': model_type,
        'is_integrating': is_integrating,
        'K': K,
        'K_int': K_int,
        'T1': T1,
        'T2': T2,
        'L': L,
    }


def normalize_pid_params(pid_params: Dict) -> Dict:
    """PID 参数标准化

    统一大小写键名，自动从 Ti/Td 推算 ki/kd。

    Args:
        pid_params: 原始 PID 参数字典

    Returns:
        标准化后的 PID 参数（小写键名 kp/ki/kd/ti/td/pb/method 等）
    """
    # 复用生产代码中的统一规范化逻辑，避免测试侧与主链路漂移
    p = normalize_pid_keys(pid_params)
    p['kp'] = float(p.get('Kp', p.get('kp', 1.0)))
    p['ki'] = float(p.get('Ki', p.get('ki', 0.0)))
    p['kd'] = float(p.get('Kd', p.get('kd', 0.0)))
    p['ti'] = float(p.get('Ti', p.get('ti', 0.0)))
    p['td'] = float(p.get('Td', p.get('td', 0.0)))
    return p


def simulate_pid_prediction(
    timestamps: np.ndarray,
    pv_array: np.ndarray,
    mv_array: np.ndarray,
    sv_array: np.ndarray,
    model_info: Dict,
    pid_params: Dict,
) -> Dict:
    """统一的新 PID 闭环仿真引擎

    从原始数据末尾出发，使用新 PID 参数和估算过程模型进行闭环仿真预测。

    Args:
        timestamps: 原始时间戳数组
        pv_array, mv_array, sv_array: 原始数据数组
        model_info: resolve_process_model_type() 的输出
        pid_params: normalize_pid_params() 的输出

    Returns:
        dict 包含:
            pv_sim, mv_sim: 仿真数组
            future_timestamps: 未来时间戳
            future_time_array: 未来 datetime 数组
            sv_target: 仿真目标 SV
            dt_sim: 仿真步长 (s)
            n_sim_steps: 仿真步数
    """
    model_type = model_info['model_type']
    is_integrating = model_info['is_integrating']
    K = model_info['K']
    K_int = model_info['K_int']
    T1 = model_info['T1']
    T2 = model_info['T2']
    L = model_info['L']

    Kp = pid_params.get('kp', 1.0)
    Ki = pid_params.get('ki', 0.0)
    Kd = pid_params.get('kd', 0.0)

    # 采样间隔
    if len(timestamps) > 1:
        dt_est = (timestamps[1] - timestamps[0]) / 1000.0
    else:
        dt_est = 1.0
        
    # [FIX] 强制控制欧拉积分步长，防止大步长导致预测振荡
    dt_sim = min(1.0, max(0.1, dt_est))

    # 仿真时长
    Ti_param = pid_params.get('ti', 0.0)
    sim_duration = max(T1 * 40, 3600, Ti_param * 6)

    # 积分过程需根据闭环时间常数动态扩展
    if is_integrating and K_int > 1e-9:
        Kp_actual = max(abs(Kp), 0.01)
        cl_tau = 1.0 / (Kp_actual * K_int)
        sim_duration = max(sim_duration, cl_tau * 8.0)

    sim_duration = min(sim_duration, 200000)

    # 防止爆内存
    if sim_duration / dt_sim > 50000:
        dt_sim = sim_duration / 50000.0

    n_sim_steps = int(sim_duration / dt_sim)
    n_sim_steps = max(2000, min(n_sim_steps, 50000))

    # 初始条件
    pv_init = pv_array[-1]
    mv_init = mv_array[-1]
    sv_target = sv_array[-1]

    # MV 饱和处理
    mv_saturated = (mv_init > 95) or (mv_init < 5)
    if is_integrating and mv_saturated:
        mv_init = 50.0

    if mv_saturated and not is_integrating:
        pv_init = np.mean(pv_array)
        mv_init = 50.0
        sv_target = pv_init + np.ptp(pv_array) * 0.1
    else:
        initial_error = abs(sv_target - pv_init)
        sv_range = max(np.ptp(sv_array), 1.0)
        if initial_error < sv_range * 0.05:
            sv_target = sv_target + sv_range * 0.1

    # 未来时间序列
    last_timestamp = timestamps[-1]
    dt_ms = int(dt_sim * 1000)
    future_timestamps = [last_timestamp + i * dt_ms for i in range(1, n_sim_steps + 1)]
    future_time_array = [datetime.fromtimestamp(ts / 1000) for ts in future_timestamps]

    # 仿真状态初始化
    pv_sim = np.zeros(n_sim_steps)
    mv_sim = np.zeros(n_sim_steps)
    x1, x2 = 0.0, 0.0
    integral = 0.0
    prev_error = sv_target - pv_init
    delay_steps = max(1, int(L / dt_sim)) if L > 0 else 1
    mv_history = [mv_init] * delay_steps
    pv_current = pv_init

    for i in range(n_sim_steps):
        error = sv_target - pv_current
        integral += error * dt_sim
        derivative = (error - prev_error) / dt_sim if dt_sim > 0 else 0.0
        prev_error = error

        # Anti-windup: MV 饱和时停止积分累加
        integral_limit = (100.0) / (abs(Ki) + 1e-10) * 2.0
        integral = np.clip(integral, -integral_limit, integral_limit)

        mv_out = mv_init + Kp * error + Ki * integral + Kd * derivative
        mv_out = np.clip(mv_out, 0.0, 100.0)
        mv_sim[i] = mv_out
        mv_history.append(mv_out)
        mv_delayed = mv_history.pop(0)
        delta_mv = mv_delayed - mv_init

        # 根据模型类型选择正确的过程仿真方程
        if is_integrating:
            x1 += K_int * delta_mv * dt_sim
            delta_pv = x1
        elif model_type in ['SOPDT', 'SO', 'SECOND_ORDER'] and T2 > 0:
            T1_eff = max(T1, 0.01)
            T2_eff = max(T2, 0.01)
            alpha = 1.0 - np.exp(-dt_sim / T1_eff)
            alpha2 = 1.0 - np.exp(-dt_sim / T2_eff)
            x1_next = x1 + alpha * (K * delta_mv - x1)
            x2_next = x2 + alpha2 * (x1 - x2)
            x1, x2 = x1_next, x2_next
            delta_pv = x2
        else:
            # FOPDT / FO: 一阶惯性环节
            T1_eff = max(T1, 0.01)
            alpha = 1.0 - np.exp(-dt_sim / T1_eff)
            x1_next = x1 + alpha * (K * delta_mv - x1)
            x1 = x1_next
            delta_pv = x1

        pv_current = pv_init + delta_pv
        pv_sim[i] = pv_current

    return {
        'pv_sim': pv_sim,
        'mv_sim': mv_sim,
        'future_timestamps': future_timestamps,
        'future_time_array': future_time_array,
        'sv_target': sv_target,
        'dt_sim': dt_sim,
        'n_sim_steps': n_sim_steps,
        'pv_init': pv_init,
        'mv_init': mv_init,
    }


# ============================================================
# 可视化函数
# ============================================================

def visualize_raw_data(data: List[Dict], scenario_name: str = None,
                       output_dir: str = None):
    """可视化原始数据（无扰动段时使用）"""
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]

    # 计算一些基本统计信息
    pv_range = np.ptp(pv_array)
    mv_range = np.ptp(mv_array)
    pv_std = np.std(pv_array)
    mv_std = np.std(mv_array)

    # 创建3个子图
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(f'原始数据可视化（未检测到扰动段）\n'
                 f'PV范围={pv_range:.2f}, PV标准差={pv_std:.2f} | '
                 f'MV范围={mv_range:.2f}, MV标准差={mv_std:.2f}',
                 fontsize=12, fontweight='bold')

    # ========== 子图1: PV/SV ==========
    ax1 = fig.add_subplot(3, 1, 1)
    ax1.plot(time_array, pv_array, 'b-', label='PV (过程值)', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV (设定值)', linewidth=1.2)
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值与设定值')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(3, 1, 2, sharex=ax1)
    ax2.plot(time_array, mv_array, 'g-', label='MV (操作值)', linewidth=0.8)
    ax2.set_ylabel('MV')
    ax2.set_title('操作值')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    # ========== 子图3: PV-SV 偏差 ==========
    ax3 = fig.add_subplot(3, 1, 3, sharex=ax1)
    error = np.array(pv_array) - np.array(sv_array)
    ax3.plot(time_array, error, 'purple', label='PV-SV 偏差', linewidth=0.8)
    ax3.axhline(y=0, color='k', linestyle='--', alpha=0.5)
    ax3.set_ylabel('偏差')
    ax3.set_xlabel('时间')
    ax3.set_title(f'偏差 (均值={np.mean(error):.2f}, 标准差={np.std(error):.2f})')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()

    # 保存图片
    if output_dir is None:
        output_dir = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test'
    os.makedirs(output_dir, exist_ok=True)

    if scenario_name:
        filepath = f"{output_dir}/raw_data_{scenario_name}.png"
    else:
        filepath = f"{output_dir}/raw_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 原始数据图表已保存至: {filepath}")
    plt.close()


def visualize_fitting_result(data: List[Dict], tuning_input: Dict,
                              fitting_result: Dict, scenario_name: str = None,
                              output_dir: str = None):
    """可视化模型拟合结果（含闭环验证）

    Args:
        data: 原始历史数据
        tuning_input: 包含 tuning_window / qualified_windows 的字典
        fitting_result: ModelSelector / TuningOrchestrator 的完整输出
        scenario_name: 场景名称（用于文件命名）
        output_dir: 输出目录路径（None 时使用默认路径）
    """
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]

    # 从 fitting_result 提取拟合数据
    fit_data = fitting_result.get('fitting_result', {})
    fit_timestamps = fit_data.get('timestamp', [])
    fit_pv = fit_data.get('pv', [])
    fit_pv_model = fit_data.get('pv_model', [])
    fit_time_array = [datetime.fromtimestamp(ts / 1000) for ts in fit_timestamps] if fit_timestamps else []

    # 获取闭环验证数据
    closed_loop_info = fitting_result.get('closed_loop_verification', {})
    has_closed_loop = closed_loop_info and closed_loop_info.get('is_stable') is not None

    # 统一解析模型参数
    model_info = resolve_process_model_type(fitting_result)
    model_type = model_info['model_type']
    is_integrating = model_info['is_integrating']

    # 标准化 PID
    pid_params = normalize_pid_params(fitting_result.get('pid_parameters', {}))

    # 创建图表：如果有闭环数据则5个子图（含新PID仿真），否则3个
    n_plots = 5 if has_closed_loop else 3
    fig = plt.figure(figsize=(16, 4 * n_plots))

    r2 = fit_data.get('r_squared', 0)
    rmse = fit_data.get('rmse', 0)
    fusion_info = fitting_result.get('fusion_info', {})

    # 闭环状态
    cl_status = ""
    if has_closed_loop:
        is_stable = closed_loop_info.get('is_stable', False)
        cl_status = f" | 闭环: {'稳定' if is_stable else '不稳定'}"

    fig.suptitle(f'ModelSelector 拟合结果 - {model_type} (R²={r2:.4f}, RMSE={rmse:.4f}){cl_status}\n'
                 f'融合方法: {fusion_info.get("method", "N/A")}, 使用段数: {fusion_info.get("n_segments", 0)}, '
                 f'一致性: {fusion_info.get("consistency_score", 0):.2f}',
                 fontsize=12, fontweight='bold')

    # ========== 子图1: PV/SV + 拟合曲线 ==========
    ax1 = fig.add_subplot(n_plots, 1, 1)
    ax1.plot(time_array, pv_array, 'b-', label='PV (实测)', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV (设定值)', linewidth=1.2)

    if fit_time_array and fit_pv_model:
        ax1.plot(fit_time_array, fit_pv_model, 'g-', label='PV_model (拟合)', linewidth=1.5, alpha=0.9)

    # 标记 tuning_window（扰动段）- 橙色
    tuning_windows = tuning_input.get('tuning_window', [])
    for i, w in enumerate(tuning_windows):
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        if start_ts and end_ts:
            if isinstance(start_ts, (int, float)):
                start_dt = datetime.fromtimestamp(start_ts / 1000)
                end_dt = datetime.fromtimestamp(end_ts / 1000)
            else:
                start_dt = start_ts
                end_dt = end_ts
            ax1.axvspan(start_dt, end_dt, alpha=0.15, color='orange',
                       label='扰动段' if i == 0 else None)

    # 标记整定段（基于MV阶跃检测）- 绿色/红色区分整定段和振荡段
    segment_info = fitting_result.get('segment_info', [])
    tuning_count = 0
    osc_count = 0
    for seg in segment_info:
        start_ts = seg.get('start_time')
        end_ts = seg.get('end_time')
        seg_type = seg.get('type', 'oscillation')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            if seg_type == 'tuning':
                ax1.axvspan(start_dt, end_dt, alpha=0.3, color='green',
                           label='整定段' if tuning_count == 0 else None)
                tuning_count += 1
            else:
                ax1.axvspan(start_dt, end_dt, alpha=0.1, color='red',
                           label='振荡段' if osc_count == 0 else None)
                osc_count += 1

    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值与模型拟合对比')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    # ========== 在子图1上追加新PID仿真预测 ==========
    # 诊断口径：即便 fitting_result.success=False（如“拟合完全失败”），
    # 只要模型参数仍可模拟，也尝试画出预测曲线，便于排查。
    model_simulatable = (
        (is_integrating and model_info.get('K_int', 0.0) > 1e-12) or
        ((not is_integrating) and model_info.get('T1', 0.0) > 0 and abs(model_info.get('K', 0.0)) > 1e-12)
    )
    if pid_params.get('kp') and model_simulatable:
        try:
            sim_result = simulate_pid_prediction(
                timestamps, pv_array, mv_array, sv_array,
                model_info, pid_params
            )

            future_time_array = sim_result['future_time_array']
            pv_sim = sim_result['pv_sim']
            mv_sim = sim_result['mv_sim']
            n_sim_steps = sim_result['n_sim_steps']
            sv_target = sim_result['sv_target']

            # 在子图1上绘制仿真PV
            ax1.plot(future_time_array, pv_sim, color='#00AA00', linestyle='-',
                     label='新参数PV (仿真)', linewidth=2.0, alpha=0.9)
            ax1.plot(future_time_array, np.full(n_sim_steps, sv_target), 'r--', linewidth=1.0)
            ax1.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5,
                        label='仿真起点', alpha=0.7)
            ax1.axvspan(time_array[-1], future_time_array[-1], alpha=0.05, color='green')
            ax1.legend(loc='upper right')
        except Exception:
            sim_result = None
            mv_sim = None
    else:
        sim_result = None  # 无仿真数据
        mv_sim = None

    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(n_plots, 1, 2, sharex=ax1)
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)

    # 扰动段 - 橙色
    for i, w in enumerate(tuning_windows):
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        if start_ts and end_ts:
            if isinstance(start_ts, (int, float)):
                start_dt = datetime.fromtimestamp(start_ts / 1000)
                end_dt = datetime.fromtimestamp(end_ts / 1000)
            else:
                start_dt = start_ts
                end_dt = end_ts
            ax2.axvspan(start_dt, end_dt, alpha=0.15, color='orange')

    # 整定段/振荡段
    for seg in segment_info:
        start_ts = seg.get('start_time')
        end_ts = seg.get('end_time')
        seg_type = seg.get('type', 'oscillation')
        if start_ts and end_ts:
            start_dt = datetime.fromtimestamp(start_ts / 1000)
            end_dt = datetime.fromtimestamp(end_ts / 1000)
            color = 'green' if seg_type == 'tuning' else 'red'
            alpha = 0.3 if seg_type == 'tuning' else 0.1
            ax2.axvspan(start_dt, end_dt, alpha=alpha, color=color)

    # 在子图2上追加仿真MV
    if sim_result is not None and mv_sim is not None:
        ax2.plot(future_time_array, mv_sim, color='#00AA00', linestyle='-',
                 label='新参数MV (仿真)', linewidth=2.0, alpha=0.9)
        ax2.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, alpha=0.7)
        ax2.axvspan(time_array[-1], future_time_array[-1], alpha=0.05, color='green')

    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    # ========== 子图3: 拟合误差 或 振荡整定信息 ==========
    ax3 = fig.add_subplot(n_plots, 1, 3, sharex=ax1)
    fusion_method = fusion_info.get('method', '')
    is_oscillation_tuning = 'oscillation' in fusion_method

    if is_oscillation_tuning:
        model_params = fitting_result.get('model_parameters', {})
        info_text = f"振荡整定模式 ({fusion_method})\n\n"
        info_text += f"临界参数:\n"
        info_text += f"  Pu (临界周期) = {model_params.get('T1', 0):.2f} s\n"
        info_text += f"  K (过程增益) = {model_params.get('K', 0):.3f}\n\n"
        info_text += f"PID 参数:\n"
        info_text += f"  pb = {pid_params.get('pb', 0):.1f}%\n"
        info_text += f"  Ti = {pid_params.get('ti', 0):.2f} s\n"
        info_text += f"  Td = {pid_params.get('td', 0):.2f} s"

        llm_decision = pid_params.get('llm_decision', {})
        if llm_decision:
            strategy = llm_decision.get('strategy_params', {})
            info_text += f"\n\nLLM 策略:\n"
            info_text += f"  safety_factor = {strategy.get('safety_factor', 'N/A')}\n"
            info_text += f"  ti_multiplier = {strategy.get('ti_multiplier', 'N/A')}"

        ax3.text(0.5, 0.5, info_text,
                transform=ax3.transAxes, ha='center', va='center',
                fontsize=11, color='darkblue',
                bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
        ax3.set_title('振荡整定信息')
        ax3.set_xticks([])
        ax3.set_yticks([])
    elif fit_time_array and fit_pv and fit_pv_model:
        error = np.array(fit_pv) - np.array(fit_pv_model)
        ax3.plot(fit_time_array, error, 'r-', label='误差 (PV - PV_model)', linewidth=0.8)
        ax3.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
        ax3.fill_between(fit_time_array, error, 0, alpha=0.3, color='red')
        ax3.set_title('拟合误差')
    else:
        ax3.set_title('拟合误差')

    ax3.set_ylabel('误差')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)

    # ========== 子图4: 闭环稳定性验证 ==========
    if has_closed_loop:
        ax4 = fig.add_subplot(n_plots, 1, 4)

        from core.algorithm.model_type.tuning.core.pid_calculator import PIDCalculator
        from core.algorithm.model_type.data_models import FusionResult

        # 使用统一解析的模型参数（积分过程已修正）
        sim_model_type = model_info['model_type']
        sim_K = model_info['K']
        sim_T1 = model_info['T1']

        if model_info['is_integrating'] and fitting_result.get('pid_parameters', {}).get('method') == 'integrating_fallback':
            print(f"   🔄 可视化引擎已重定向至物理积分模型 FO_INTEGRATOR (K_int={sim_K:.6f})")

        fusion = FusionResult(
            model_type=sim_model_type,
            K=sim_K,
            T1=sim_T1,
            T2=model_info['T2'],
            L=model_info['L']
        )

        calculator = PIDCalculator()

        # 优先使用 closed_loop_info 中保存的仿真参数
        sp_initial = closed_loop_info.get('sp_initial')
        sp_final = closed_loop_info.get('sp_final')
        pv_initial = closed_loop_info.get('pv_initial')

        if sp_initial is None or sp_final is None:
            sv_data = fit_data.get('sv', [])
            pv_data = fit_data.get('pv', [])

            sp_initial = sv_data[0] if sv_data else 50.0
            sp_final = sv_data[-1] if sv_data else 60.0
            pv_initial = pv_data[0] if pv_data else sp_initial

            sp_change = abs(sp_final - sp_initial)
            pv_sp_diff = abs(pv_initial - sp_initial)

            if sp_change < 5.0 or pv_sp_diff > sp_change * 2:
                sp_initial = 50.0
                sp_final = 60.0
                pv_initial = 50.0

        sp_change = abs(sp_final - sp_initial)

        # 自适应仿真参数
        if is_oscillation_tuning:
            model_params_raw = fitting_result.get('model_parameters', {})
            Pu = model_params_raw.get('T1', 10.0)
            T_ref = Pu
        else:
            T_ref = fusion.T1 if fusion.T1 > 0 else 10.0

        T2_val = fusion.T2 if fusion.T2 > 0 else T_ref
        T_max = max(T_ref, T2_val, 10.0)
        Ti_param = pid_params.get('Ti', pid_params.get('ti', 0.0))

        # [FIX] 无论原始数据多粗糙，理论闭环验证使用小步长，避免积分发散
        dt = max(0.1, min(T_max, Ti_param) / 100.0)
        dt = min(1.0, max(0.1, dt))

        sim_time = max(300, T_max * 40, Ti_param * 6)

        if sim_model_type in ['FOPI', 'SOPI', 'FO_INTEGRATOR'] or pid_params.get('method') == 'integrating_fallback':
            k_int = getattr(fusion, 'K_int', getattr(fusion, 'K', 1.0))
            if k_int > 1e-9:
                Kp_actual = max(abs(pid_params.get('Kp', pid_params.get('kp', 1.0))), 0.01)
                cl_tau = 1.0 / (Kp_actual * k_int)
                sim_time = max(sim_time, cl_tau * 8.0)

        sim_time = min(sim_time, 200000)

        if sim_time / dt > 50000:
            dt = sim_time / 50000.0

        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 50000)

        K_est = fusion.K
        T1_est = fusion.T1
        sim_model_type = fusion.model_type
        loop_type = fitting_result.get('tuning_features', {}).get('loop_type', 'flow')

        metrics = calculator.simulate_closed_loop(
            K=K_est, T1=T1_est, T2=fusion.T2, L=fusion.L,
            model_type=sim_model_type,
            Kp=pid_params.get('kp', 1), Ki=pid_params.get('ki', 0), Kd=pid_params.get('kd', 0),
            sp_initial=sp_initial,
            sp_final=sp_final,
            pv_initial=pv_initial,
            n_steps=n_steps,
            dt=dt,
            loop_type=loop_type
        )

        t_sim = np.arange(len(metrics.pv_history)) * dt

        sp_sim = np.zeros_like(metrics.pv_history)
        sp_sim[:10] = sp_initial
        sp_sim[10:] = sp_final

        ax4.plot(t_sim, metrics.pv_history, 'b-', label='PV (闭环响应)', linewidth=1.5)
        ax4.plot(t_sim, sp_sim, 'r--', label='SP (设定值)', linewidth=1.2)

        is_stable = closed_loop_info.get('is_stable', False)
        settling_time = closed_loop_info.get('settling_time', -1)
        overshoot = closed_loop_info.get('overshoot', 0)
        rise_time = closed_loop_info.get('rise_time', -1)
        sse = closed_loop_info.get('steady_state_error', 0)

        status_text = '稳定' if is_stable else '不稳定'

        textstr = f'{status_text}\n'
        textstr += f'调节时间: {settling_time:.1f}s\n' if settling_time >= 0 else '调节时间: N/A\n'
        textstr += f'超调量: {overshoot:.1f}%\n'
        textstr += f'上升时间: {rise_time:.1f}s\n' if rise_time >= 0 else '上升时间: N/A\n'
        textstr += f'稳态误差: {sse:.2f}%'

        props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        ax4.text(0.98, 0.95, textstr, transform=ax4.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='right', bbox=props)

        error_band = sp_change * 0.02
        ax4.axhline(y=sp_final + error_band, color='gray', linestyle=':', alpha=0.5, label='±2%误差带')
        ax4.axhline(y=sp_final - error_band, color='gray', linestyle=':', alpha=0.5)
        ax4.fill_between(t_sim, sp_final - error_band, sp_final + error_band,
                        alpha=0.1, color='green')

        if settling_time >= 0 and settling_time < t_sim[-1]:
            ax4.axvline(x=settling_time, color='purple', linestyle='--', linewidth=1.5,
                       label=f'调节时间 ({settling_time:.1f}s)')
            ax4.annotate(f'{settling_time:.1f}s',
                        xy=(settling_time, sp_final),
                        xytext=(settling_time + 2, sp_final + error_band * 2),
                        fontsize=9, color='purple',
                        arrowprops=dict(arrowstyle='->', color='purple', lw=1))

        ax4.set_xlabel('时间 (s)')
        ax4.set_ylabel('PV / SP')
        ax4.set_title(f'闭环稳定性验证 (Kp={pid_params.get("kp", 0):.3f}, Ki={pid_params.get("ki", 0):.3f}, Kd={pid_params.get("kd", 0):.3f})')
        ax4.legend(loc='lower right')
        ax4.grid(True, alpha=0.3)

        # 调整 x 轴范围
        pv_final = metrics.pv_history[-1]
        error_band_check = abs(sp_final - sp_initial) * 0.02
        is_converged = abs(pv_final - sp_final) <= error_band_check

        if is_converged and settling_time >= 0 and settling_time < t_sim[-1]:
            x_max = min(t_sim[-1], max(80, settling_time * 1.3))
        elif not is_converged:
            for ii in range(len(metrics.pv_history) - 1, -1, -1):
                if abs(metrics.pv_history[ii] - sp_final) > error_band_check:
                    converge_time = (ii + 1) * dt
                    x_max = min(t_sim[-1], converge_time * 1.2)
                    break
            else:
                x_max = t_sim[-1]
        else:
            x_max = t_sim[-1]
        ax4.set_xlim([0, x_max])

        # 调整 y 轴范围
        pv_min = min(np.min(metrics.pv_history), sp_initial, sp_final)
        pv_max = max(np.max(metrics.pv_history), sp_initial, sp_final)
        y_margin = (pv_max - pv_min) * 0.1
        ax4.set_ylim([pv_min - y_margin, pv_max + y_margin])

        if overshoot > 0:
            peak_idx = np.argmax(metrics.pv_history) if sp_change > 0 else np.argmin(metrics.pv_history)
            peak_val = metrics.pv_history[peak_idx]
            peak_time = peak_idx * dt
            if peak_time <= x_max:
                ax4.plot(peak_time, peak_val, 'ro', markersize=6)
                ax4.annotate(f'峰值: {peak_val:.1f}\n超调: {overshoot:.1f}%',
                            xy=(peak_time, peak_val),
                            xytext=(peak_time + 5, peak_val),
                            fontsize=8, color='red',
                            arrowprops=dict(arrowstyle='->', color='red', lw=0.8))

    # ========== 子图5: 新PID仿真预测（复用统一仿真引擎，保证口径一致） ==========
    if has_closed_loop:
        ax5 = fig.add_subplot(n_plots, 1, 5)

        if sim_result is None and pid_params.get('kp') and model_simulatable:
            try:
                sim_result = simulate_pid_prediction(
                    timestamps, pv_array, mv_array, sv_array, model_info, pid_params
                )
            except Exception:
                sim_result = None

        if sim_result is not None:
            pv_sim5 = sim_result['pv_sim']
            sv_target5 = sim_result['sv_target']
            pv_init5 = sim_result['pv_init']
            dt_sim5 = sim_result['dt_sim']
            t_sim5 = np.arange(len(pv_sim5)) * dt_sim5

            ax5.plot(t_sim5, pv_sim5, 'b-', label='PV (预测)', linewidth=1.5)
            ax5.axhline(y=sv_target5, color='r', linestyle='--', label=f'SV={sv_target5:.1f}', linewidth=1.2)
            ax5.fill_between(
                t_sim5,
                sv_target5 * 0.95,
                sv_target5 * 1.05,
                alpha=0.2,
                color='green',
                label='±5%误差带'
            )
            ax5.axhline(y=pv_init5, color='gray', linestyle=':', alpha=0.5, label=f'初始PV={pv_init5:.1f}')

            # 与主图一致：稳定判据采用末段是否持续落在误差带内
            error_band5 = max(abs(sv_target5) * 0.05, 0.3)
            tail = pv_sim5[-100:] if len(pv_sim5) >= 100 else pv_sim5
            in_band = np.abs(tail - sv_target5) < error_band5 if len(tail) > 0 else np.array([False])
            is_stable_predict = bool(np.all(in_band))
            stable_status = '预测稳态' if is_stable_predict else '预测不稳态'

            ax5.set_xlim([0, t_sim5[-1]])
            ax5.set_title(f'新PID参数仿真预测（统一引擎）- {stable_status}')
        else:
            ax5.text(
                0.5, 0.5, '无可用仿真结果',
                transform=ax5.transAxes, ha='center', va='center', fontsize=11
            )
            ax5.set_title('新PID参数仿真预测（统一引擎）')

        ax5.set_xlabel('仿真时间 (s)')
        ax5.set_ylabel('PV')
        handles, labels = ax5.get_legend_handles_labels()
        if handles:
            ax5.legend(loc='upper right')
        ax5.grid(True, alpha=0.3)

    plt.tight_layout()

    # 保存图表
    if output_dir is None:
        output_dir = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test'
    os.makedirs(output_dir, exist_ok=True)

    if scenario_name:
        filename = f'model_selector_{scenario_name}.png'
    else:
        filename = 'model_selector_result.png'

    filepath = f'{output_dir}/{filename}'
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 图表已保存至: {filepath}")
    plt.close()


def visualize_new_pid_simulation(data: List[Dict], fitting_result: Dict,
                                  scenario_name: str = None,
                                  output_dir: str = None):
    """可视化新整定参数从原始数据最后一个点开始的未来仿真走势

    Args:
        data: 原始历史数据
        fitting_result: ModelSelector 的整定结果
        scenario_name: 场景名称
        output_dir: 输出目录路径
    """
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]

    # 统一解析模型参数和 PID 参数
    model_info = resolve_process_model_type(fitting_result)
    pid_params = normalize_pid_params(fitting_result.get('pid_parameters', {}))

    # 使用统一仿真引擎
    sim_result = simulate_pid_prediction(
        timestamps, pv_array, mv_array, sv_array,
        model_info, pid_params
    )

    pv_sim = sim_result['pv_sim']
    mv_sim = sim_result['mv_sim']
    future_time_array = sim_result['future_time_array']
    sv_target = sim_result['sv_target']

    model_type = model_info['model_type']
    K = model_info['K']
    T1 = model_info['T1']
    L = model_info['L']

    # ========== 创建合并图表 ==========
    fig = plt.figure(figsize=(18, 8))

    pb = pid_params.get('pb', pid_params.get('kp', 1.0) * 100 if pid_params.get('kp', 0) > 0 else 100)
    ti = pid_params.get('ti', 0)
    td = pid_params.get('td', 0)

    fig.suptitle(f'原始数据 + 新参数未来仿真 (pb={pb:.1f}%, Ti={ti:.1f}s, Td={td:.2f}s)\n'
                 f'模型: {model_type}, K={K:.3f}, T1={T1:.1f}s, L={L:.1f}s',
                 fontsize=12, fontweight='bold')

    # 只显示最后2小时的历史数据
    dt_est = (timestamps[1] - timestamps[0]) / 1000.0 if len(timestamps) > 1 else 1.0
    show_history_seconds = 7200
    show_history_points = int(show_history_seconds / dt_est)
    hist_start = max(0, len(time_array) - show_history_points)

    n_sim_steps = sim_result['n_sim_steps']
    sv_sim = np.full(n_sim_steps, sv_target)

    # ========== 子图1: PV/SV ==========
    ax1 = fig.add_subplot(2, 1, 1)
    ax1.plot(time_array[hist_start:], pv_array[hist_start:], 'b-', label='原始PV (实测)', linewidth=0.8, alpha=0.8)
    ax1.plot(time_array[hist_start:], sv_array[hist_start:], 'r--', label='SV (设定值)', linewidth=1.0)
    ax1.plot(future_time_array, pv_sim, 'g-', label='新参数PV (仿真预测)', linewidth=2.0)
    ax1.plot(future_time_array, sv_sim, 'r--', linewidth=1.0)
    ax1.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5,
                label='仿真起点', alpha=0.8)
    ax1.axvspan(time_array[-1], future_time_array[-1], alpha=0.1, color='green')
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值：原始数据 + 新参数仿真预测')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))

    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    ax2.plot(time_array[hist_start:], mv_array[hist_start:], 'b-', label='原始MV (实测)', linewidth=0.8, alpha=0.8)
    ax2.plot(future_time_array, mv_sim, 'g-', label='新参数MV (仿真预测)', linewidth=2.0)
    ax2.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, alpha=0.8)
    ax2.axvspan(time_array[-1], future_time_array[-1], alpha=0.1, color='green')
    ax2.set_ylabel('MV')
    ax2.set_xlabel('时间')
    ax2.set_title('操作值：原始数据 + 新参数仿真预测')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # 保存图表
    if output_dir is None:
        output_dir = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test'
    os.makedirs(output_dir, exist_ok=True)

    if scenario_name:
        filename = f'new_pid_simulation_{scenario_name}.png'
    else:
        filename = f'new_pid_simulation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'

    filepath = f"{output_dir}/{filename}"
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 新参数仿真图表已保存至: {filepath}")
    plt.close()


def visualize_scenario_comparison(
    scenario: Dict,
    metadata: Dict,
    data: List[Dict],
    sim_old: Dict,
    sim_rule: Dict,
    pid_rule: Dict,
    result: Dict,
    scenario_idx: int,
    tuning_method: str = "unknown",
    output_dir: str = None,
):
    """稳定性测试专用可视化（Old PID vs Tuned PID）"""
    colors = {
        "pv": "#1E88E5",
        "sv": "#E53935",
        "mv": "#43A047",
        "old_pid": "#7E57C2",
        "rule": "#FF9800",
        "band": "#4CAF50",
        "grid": "#E0E0E0",
    }

    plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["axes.facecolor"] = "#FAFAFA"
    plt.rcParams["figure.facecolor"] = "#FFFFFF"

    fig = plt.figure(figsize=(16, 10))

    method_str = "Critical Method" if "oscillation" in tuning_method else "Model Fitting"
    fig.suptitle(
        f"Scenario {scenario_idx}: {scenario['name']}\n{scenario['description']} | Method: {method_str}",
        fontsize=14,
        fontweight="bold",
        color="#333333",
    )

    sv = metadata["sv"]
    pid_old = scenario["original_pid"]

    timestamps = [d["timestamp"] for d in data]
    time_seconds = [(ts - timestamps[0]) / 1000 for ts in timestamps]
    pv_array = np.array([d["pv"] for d in data])
    sv_array = np.array([d["sv"] for d in data])
    mv_array = np.array([d["mv"] for d in data])

    change_idx = 300
    if metadata.get("change_time"):
        for i, ts in enumerate(timestamps):
            if ts >= metadata["change_time"]:
                change_idx = i
                break

    ax1 = fig.add_subplot(2, 3, 1)
    ax1.plot(time_seconds, pv_array, color=colors["pv"], label="PV", linewidth=1.2, alpha=0.9)
    ax1.plot(time_seconds, sv_array, color=colors["sv"], linestyle="--", label="SV", linewidth=1.5)
    ax1.axvline(x=time_seconds[change_idx], color="#FF5722", linestyle="--", linewidth=2, alpha=0.8, label="Change")
    ax1.fill_between(time_seconds, sv * 0.95, sv * 1.05, alpha=0.12, color=colors["band"])
    ax1.set_ylabel("PV / SV", fontweight="bold", color=colors["pv"])
    ax1.set_xlabel("Time (s)")
    ax1.set_title("Original Data: PV, SV & MV", fontweight="bold", fontsize=11)
    ax1.tick_params(axis="y", labelcolor=colors["pv"])
    ax1.grid(True, alpha=0.4, color=colors["grid"])
    ax1.set_xlim([0, time_seconds[-1]])

    ax1_mv = ax1.twinx()
    ax1_mv.plot(time_seconds, mv_array, color=colors["mv"], label="MV", linewidth=1.0, alpha=0.7)
    ax1_mv.set_ylabel("MV (%)", fontweight="bold", color=colors["mv"])
    ax1_mv.tick_params(axis="y", labelcolor=colors["mv"])
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax1_mv.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=7, framealpha=0.9)

    ax2 = fig.add_subplot(2, 3, 2)
    osc_start = max(0, change_idx - 20)
    ax2.plot(time_seconds[osc_start:], pv_array[osc_start:], color=colors["pv"], label="PV", linewidth=1.2)
    ax2.plot(time_seconds[osc_start:], sv_array[osc_start:], color=colors["sv"], linestyle="--", label="SV", linewidth=1.5)
    ax2.axhline(y=sv * 1.05, color="#9E9E9E", linestyle=":", alpha=0.7)
    ax2.axhline(y=sv * 0.95, color="#9E9E9E", linestyle=":", alpha=0.7)
    ax2.fill_between(time_seconds[osc_start:], sv * 0.95, sv * 1.05, alpha=0.12, color=colors["band"])
    ax2.set_ylabel("PV / SV", fontweight="bold", color=colors["pv"])
    ax2.set_xlabel("Time (s)")
    ax2.set_title("Oscillation Segment (Zoomed)", fontweight="bold", fontsize=11)
    ax2.tick_params(axis="y", labelcolor=colors["pv"])
    ax2.grid(True, alpha=0.4, color=colors["grid"])

    ax2_mv = ax2.twinx()
    ax2_mv.plot(time_seconds[osc_start:], mv_array[osc_start:], color=colors["mv"], label="MV", linewidth=1.0, alpha=0.7)
    ax2_mv.set_ylabel("MV (%)", fontweight="bold", color=colors["mv"])
    ax2_mv.tick_params(axis="y", labelcolor=colors["mv"])
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_mv.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc="upper right", fontsize=7, framealpha=0.9)

    ax3 = fig.add_subplot(2, 3, 3)
    ax3.plot(sim_old["t"], sim_old["pv"], color=colors["old_pid"], linestyle="--", label="Old PV", linewidth=1.5, alpha=0.8)
    ax3.plot(sim_rule["t"], sim_rule["pv"], color=colors["rule"], label="Tuned PV", linewidth=2)
    ax3.plot(sim_old["t"], sim_old["sv"], color=colors["sv"], linestyle="--", label="SV", linewidth=1.2, alpha=0.7)
    ax3.fill_between(sim_old["t"], sv * 0.95, sv * 1.05, alpha=0.12, color=colors["band"])
    old_status = "Stable" if sim_old["is_stable"] else "Oscillating"
    new_status = "STABLE" if sim_rule["is_stable"] else "Oscillating"
    ax3.set_title(f"Old ({old_status}) vs Tuned ({new_status})", fontweight="bold", fontsize=11)
    ax3.set_ylabel("PV", fontweight="bold", color=colors["pv"])
    ax3.set_xlabel("Time (s)")
    ax3.tick_params(axis="y", labelcolor=colors["pv"])
    ax3.grid(True, alpha=0.4, color=colors["grid"])

    ax3_mv = ax3.twinx()
    ax3_mv.plot(sim_old["t"], sim_old["mv"], color=colors["old_pid"], linestyle=":", label="Old MV", linewidth=1.0, alpha=0.5)
    ax3_mv.plot(sim_rule["t"], sim_rule["mv"], color=colors["rule"], linestyle=":", label="Tuned MV", linewidth=1.0, alpha=0.6)
    ax3_mv.set_ylabel("MV (%)", fontweight="bold", color=colors["mv"])
    ax3_mv.tick_params(axis="y", labelcolor=colors["mv"])
    lines1, labels1 = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3_mv.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=6, framealpha=0.9, ncol=2)

    ax4 = fig.add_subplot(2, 3, 4)
    metrics = ["Settling\nTime (s)", "Overshoot\n(%)", "IAE\n(×100)"]
    old_vals = [min(sim_old["settling_time"], 300), sim_old["overshoot"], sim_old.get("iae", 0) / 100]
    rule_vals = [min(sim_rule["settling_time"], 300), sim_rule["overshoot"], sim_rule.get("iae", 0) / 100]
    x = np.arange(len(metrics))
    width = 0.35
    bars1 = ax4.bar(x - width / 2, old_vals, width, label="Old PID", color=colors["old_pid"], alpha=0.8)
    bars2 = ax4.bar(x + width / 2, rule_vals, width, label="Tuned PID", color=colors["rule"], alpha=0.8)
    if not sim_old["is_stable"]:
        bars1[0].set_hatch("//")
        bars1[0].set_edgecolor("#333333")
    if not sim_rule["is_stable"]:
        bars2[0].set_hatch("//")
        bars2[0].set_edgecolor("#333333")
    for bar, val in zip(bars1, old_vals):
        ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2, f"{val:.1f}", ha="center", va="bottom", fontsize=8, color="#555555")
    for bar, val in zip(bars2, rule_vals):
        ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 2, f"{val:.1f}", ha="center", va="bottom", fontsize=8, color="#555555")
    ax4.set_ylabel("Value", fontweight="bold")
    ax4.set_title("Performance Metrics", fontweight="bold", fontsize=11)
    ax4.set_xticks(x)
    ax4.set_xticklabels(metrics, fontsize=9)
    ax4.legend(fontsize=9, framealpha=0.9)
    ax4.grid(True, alpha=0.4, axis="y", color=colors["grid"])

    ax5 = fig.add_subplot(2, 3, 5)
    ax5.axis("off")
    info_lines = [
        ("PROCESS PARAMETERS", None),
        ("─" * 35, None),
        (f"Original: K={scenario['process_original']['K']:.2f}, T1={scenario['process_original']['T1']:.1f}s", None),
        (f"Changed:  K={scenario['process_changed']['K']:.2f}, T1={scenario['process_changed']['T1']:.1f}s, L={scenario['process_changed']['L']:.1f}s", None),
        ("", None),
        ("PID PARAMETERS", None),
        ("─" * 35, None),
        (f"{'Parameter':<12} {'Old PID':<12} {'Tuned PID':<12}", None),
        (f"{'PB (%)':<12} {100/pid_old['Kp'] if pid_old.get('Kp', 0) != 0 else '-':<12.1f} {pid_rule.get('pb', 100):<12.1f}", None),
        (f"{'Ti (s)':<12} {pid_old['Kp']/pid_old['Ki'] if pid_old.get('Ki', 0) != 0 else '-':<12.1f} {pid_rule.get('ti', 0):<12.1f}", None),
        (f"{'Td (s)':<12} {pid_old['Kd']/pid_old['Kp'] if pid_old.get('Kp', 0) != 0 and pid_old.get('Kd', 0) != 0 else 0:<12.1f} {pid_rule.get('td', 0):<12.1f}", None),
        ("", None),
        ("TUNING RESULT", None),
        ("─" * 35, None),
    ]
    if sim_rule["is_stable"]:
        info_lines.append((f"Status: STABLE (Ts={sim_rule['settling_time']:.0f}s)", "#4CAF50"))
    else:
        info_lines.append((f"Status: UNSTABLE (not settled)", "#F44336"))
    info_lines.append((f"Method: {method_str}", None))
    info_lines.append((f"Loop Type: {scenario.get('loop_type', 'unknown')}", None))

    y_pos = 0.95
    for text, color in info_lines:
        text_color = color if color else "#333333"
        fontweight = "bold" if text.isupper() or "Status" in text else "normal"
        ax5.text(
            0.05,
            y_pos,
            text,
            transform=ax5.transAxes,
            fontsize=10,
            verticalalignment="top",
            fontfamily="monospace",
            color=text_color,
            fontweight=fontweight,
        )
        y_pos -= 0.055

    from matplotlib.patches import FancyBboxPatch

    bbox = FancyBboxPatch(
        (0.02, 0.02),
        0.96,
        0.96,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        facecolor="#F5F5F5",
        edgecolor="#BDBDBD",
        transform=ax5.transAxes,
        zorder=-1,
    )
    ax5.add_patch(bbox)

    plt.tight_layout(rect=[0, 0, 1, 0.95])

    if output_dir is None:
        output_dir = "core/algorithm/model_type/tests/results/stability"
    os.makedirs(output_dir, exist_ok=True)
    safe_name = scenario["name"].replace(" ", "_").replace("/", "_")
    filename = f"scenario_{scenario_idx:02d}_{safe_name}.png"
    filepath = os.path.join(output_dir, filename)
    plt.savefig(filepath, dpi=150, bbox_inches="tight", facecolor="white", edgecolor="none")
    print(f"   Chart saved: {filepath}")
    plt.close()
