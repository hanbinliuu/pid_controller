"""ModelSelector 整定测试脚本

使用方法:
    1. 修改 CONFIG 配置区域的参数
    2. 运行: python test_model_selector_real.py (在 tests 目录下)
    3. 或者: python -m core.algorithm.model_type.tests.test_model_selector_real (在项目根目录)
"""
import sys
import os

# 获取项目根目录（从 tests 目录往上 4 层）
# tests -> model_type -> algorithm -> core -> 项目根目录
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_current_dir))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import time
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.select_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
from core.algorithm.model_type.model_selector import ModelSelector

# ============================================================
# 配置区域 - 修改这里的参数进行测试
# ============================================================

CONFIG = {
    # 回路 URI
    # 'loop_uri': "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951", 
    # 'loop_uri': "/pid_zd/7d3298f025b84c46a2ed898f66dcfa3f",  #101
    # 'loop_uri': "/pid_zd/b352328ec0cd4a9c958b32815e67a96a", #029a
    'loop_uri': "/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582" , # FIC005A1
    # "loop_uri": "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951", # FIC002A
    
    # 测试场景列表 (可添加多个场景)
    'scenarios': [
        # {'start_time': '2025-12-23 00:00:00', 'end_time': '2025-12-23 23:00:00'},
        # {'start_time': '2026-03-11 04:09:30', 'end_time': '2026-03-11 10:09:30'},

        {'start_time': '2026-01-05 00:39:41', 'end_time': '2026-01-05 13:39:41'},
    ],
    
    # 响应模式: 'fast' | 'balanced' | 'conservative'
    'response_mode': 'conservative',
    
    # 是否输出详细日志
    'verbose': True,
    
    # 日志保存目录
    'log_dir': '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test',
}


# ============================================================
# 数据获取
# ============================================================

def get_history_data(start_time: int, end_time: int, loop_uri: str = None) -> List[Dict]:
    """获取历史数据"""
    loop_uri = loop_uri or CONFIG['loop_uri']
    
    table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
    db = get_default_database()
    
    history_data: List[Dict] = process_query_tsdb_data_interpolated(
        db=db,
        table_name=table,
        required_fields=required_fields,
        start_time=start_time,
        end_time=end_time,
        is_filter=False
    )
    
    if not history_data:
        print("❌ 未获取到历史数据")
        return []
    print(f"✅ 获取到历史数据：{len(history_data)} 条")
    return history_data


def convert_to_arrays(data: List[Dict]) -> tuple:
    """将数据转换为numpy数组"""
    pv_array = np.array([d.get('pv', 0.0) for d in data], dtype=np.float64)
    sv_array = np.array([d.get('sv', 0.0) for d in data], dtype=np.float64)
    mv_array = np.array([d.get('mv', 0.0) for d in data], dtype=np.float64)
    timestamps = np.array([d.get('timestamp', 0) for d in data], dtype=np.int64)
    return pv_array, sv_array, mv_array, timestamps


# ============================================================
# 扰动段检测（获取 tuning_input）
# ============================================================

def detect_tuning_windows(data: List[Dict]) -> Dict:
    """
    检测扰动段，返回 tuning_input 格式
    """
    # 调用 StabilityDetector 获取整定窗口（新格式：直接传入 history_data）
    result = find_high_variability_periods({"history_data": data})
    
    # 转换为旧格式兼容（qualified_windows -> tuning_window）
    if result.get('qualified_windows'):
        converted_windows = []
        for w in result['qualified_windows']:
            start_ms = w['start_time']
            end_ms = w['end_time']
            
            # 转换时间戳为可读字符串
            start_str = datetime.fromtimestamp(start_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            end_str = datetime.fromtimestamp(end_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            converted_windows.append({
                'start_time': start_ms,
                'end_time': end_ms,
                'start_time_str': start_str,
                'end_time_str': end_str
            })
        result['tuning_window'] = converted_windows
    else:
        result['tuning_window'] = []
    
    return result


# ============================================================
# 数据质量分析
# ============================================================

def analyze_data_quality(data: List[Dict]) -> Dict:
    """分析数据质量，给出预处理建议"""
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    
    # 过滤 PV=0
    valid_mask = pv_array != 0
    pv = pv_array[valid_mask]
    mv = mv_array[valid_mask]
    
    if len(pv) < 20:
        return {'quality': 'insufficient_data', 'warnings': ['数据点过少']}
    
    report = {
        'quality': 'unknown',
        'warnings': [],
        'recommendations': [],
        'stats': {}
    }
    
    # 噪声分析
    pv_diff = np.abs(np.diff(pv))
    pv_range = np.max(pv) - np.min(pv)
    if pv_range > 1e-6:
        noise_ratio = np.median(pv_diff) / pv_range
        report['stats']['pv_noise_ratio'] = round(noise_ratio, 4)
        
        if noise_ratio > 0.15:
            report['quality'] = 'very_noisy'
            report['warnings'].append(f'PV噪声极高 (ratio={noise_ratio:.4f})')
        elif noise_ratio > 0.05:
            report['quality'] = 'noisy'
            report['warnings'].append(f'PV噪声较大 (ratio={noise_ratio:.4f})')
        else:
            report['quality'] = 'good'
    
    # 高频振荡检测
    if len(pv) > 10:
        sign_changes = np.sum(np.diff(np.sign(np.diff(pv))) != 0)
        oscillation_ratio = sign_changes / len(pv)
        report['stats']['oscillation_ratio'] = round(oscillation_ratio, 4)
        
        if oscillation_ratio > 0.3:
            report['warnings'].append(f'高频振荡严重 (ratio={oscillation_ratio:.4f})')
    
    # MV 离散性检测
    mv_unique = np.unique(mv)
    report['stats']['mv_unique_values'] = len(mv_unique)
    
    if len(mv_unique) <= 3:
        report['warnings'].append(f'MV离散值过少 ({len(mv_unique)}个)，可能为ON-OFF控制')
    
    return report


# ============================================================
# ModelSelector 测试
# ============================================================

def run_model_selector(data: List[Dict], qualified_windows: List[Dict], 
                       verbose: bool = True, response_mode: str = 'conservative') -> Dict:
    """
    测试 ModelSelector 新接口（run 方法）
    
    Args:
        data: 原始历史数据
        qualified_windows: 扰动窗口列表
        verbose: 是否输出详细日志
        
    Returns:
        整定结果（新格式）
    """
    print("\n" + "=" * 60)
    print("ModelSelector 整定测试（新格式）")
    print("=" * 60)
    
    # 数据质量分析
    if verbose:
        print("\n📊 数据质量分析:")
        quality_report = analyze_data_quality(data)
        print(f"   质量评级: {quality_report['quality']}")
        
        if quality_report['stats']:
            print("   统计信息:")
            for k, v in quality_report['stats'].items():
                print(f"      {k}: {v}")
    

    # 构造新格式输入
    # response_mode: 'fast' (快速响应，允许超调), 'balanced' (默认), 'conservative' (保守，无超调)
    input_data = {
        'history_data': data,
        'params': {
            'model_type': None,
            'turning_type': None,
            'analyst_column': 'pv'
        },
        'qualified_windows': qualified_windows,
        'response_mode': response_mode
    }
    
    print(f"\n📥 输入参数:")
    print(f"   history_data: {len(data)} 条")
    print(f"   qualified_windows: {len(qualified_windows)} 个扰动段")
    for i, w in enumerate(qualified_windows):
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        start_str = datetime.fromtimestamp(start_ts / 1000).strftime('%Y-%m-%d %H:%M:%S') if start_ts else 'N/A'
        end_str = datetime.fromtimestamp(end_ts / 1000).strftime('%Y-%m-%d %H:%M:%S') if end_ts else 'N/A'
        print(f"      [{i+1}] {start_str} ~ {end_str}")
    
    # 调用新的 run 方法
    selector = ModelSelector(verbose=verbose)
    
    start_time = time.time()
    result = selector.run(input_data)
    elapsed_time = time.time() - start_time
    
    print(f"\n⏱️ 整定耗时: {elapsed_time:.2f} 秒")
    result['tuning_elapsed_time'] = elapsed_time
    
    return result


# ============================================================
# 可视化
# ============================================================

def visualize_raw_data(data: List[Dict], scenario_name: str = None):
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
    if scenario_name:
        filepath = f"{CONFIG['log_dir']}/raw_data_{scenario_name}.png"
    else:
        filepath = f"{CONFIG['log_dir']}/raw_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 原始数据图表已保存至: {filepath}")
    plt.close()


def visualize_fitting_result(data: List[Dict], tuning_input: Dict, 
                              fitting_result: Dict, scenario_name: str = None):
    """可视化模型拟合结果（含闭环验证）"""
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
    
    # 创建图表：如果有闭环数据则5个子图（含新PID仿真），否则3个
    n_plots = 5 if has_closed_loop else 3
    fig = plt.figure(figsize=(16, 4 * n_plots))
    
    model_type = fitting_result.get('model_type', 'Unknown')
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
                # 整定段 - 绿色边框
                ax1.axvspan(start_dt, end_dt, alpha=0.3, color='green', 
                           label='整定段' if tuning_count == 0 else None)
                tuning_count += 1
            else:
                # 振荡段 - 红色边框（较淡）
                ax1.axvspan(start_dt, end_dt, alpha=0.1, color='red', 
                           label='振荡段' if osc_count == 0 else None)
                osc_count += 1
    
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值与模型拟合对比')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 在子图1和子图2上追加新PID仿真预测 ==========
    pid_params = fitting_result.get('pid_parameters', {})
    model_params = fitting_result.get('model_parameters', {})
    if pid_params.get('kp') and fitting_result.get('success'):
        K_sim = model_params.get('K', 1.0)
        T1_sim = model_params.get('T1', 10.0)
        T2_sim = model_params.get('T2', 0.0)
        L_sim = model_params.get('L', 0.0)
        Kp_sim = pid_params.get('kp', 1.0)
        Ki_sim = pid_params.get('ki', 0.0)
        Kd_sim = pid_params.get('kd', 0.0)
        
        # 采样间隔
        if len(timestamps) > 1:
            dt_sim = (timestamps[1] - timestamps[0]) / 1000.0
        else:
            dt_sim = 1.0
        
        # 仿真时长：显示足够长的未来
        sim_duration = max(T1_sim * 40, 3600)
        sim_duration = min(sim_duration, 36000)
        n_sim_steps = int(sim_duration / dt_sim)
        n_sim_steps = max(2000, min(n_sim_steps, 50000))
        
        # 初始条件
        pv_init = pv_array[-1]
        mv_init = mv_array[-1]
        sv_target = sv_array[-1]
        
        # MV饱和处理
        mv_saturated = (mv_init > 95) or (mv_init < 5)
        if mv_saturated:
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
        x1_s, x2_s = 0.0, 0.0
        integral_s = 0.0
        prev_error_s = sv_target - pv_init
        delay_steps = max(1, int(L_sim / dt_sim)) if L_sim > 0 else 1
        mv_history_sim = [mv_init] * delay_steps
        pv_current_s = pv_init
        
        for i in range(n_sim_steps):
            error_s = sv_target - pv_current_s
            integral_s += error_s * dt_sim
            derivative_s = (error_s - prev_error_s) / dt_sim if dt_sim > 0 else 0.0
            prev_error_s = error_s
            integral_s = np.clip(integral_s, -100 / (abs(Ki_sim) + 1e-10), 100 / (abs(Ki_sim) + 1e-10))
            mv_out = mv_init + Kp_sim * error_s + Ki_sim * integral_s + Kd_sim * derivative_s
            mv_out = np.clip(mv_out, 0.0, 100.0)
            mv_sim[i] = mv_out
            mv_history_sim.append(mv_out)
            mv_delayed = mv_history_sim.pop(0)
            delta_mv = mv_delayed - mv_init
            T1_eff = max(T1_sim, 0.01)
            # 使用指数欧拉法防止刚性方程(大时间步、小时间常数)的数值发散
            # 原本的显式欧拉: dx1 = (K_sim * delta_mv - x1_s) / T1_eff * dt_sim 
            # 当 dt_sim > 2*T1_eff 时，原方程会数值爆炸，产生 -4^n 从而剧烈震荡。
            alpha = 1.0 - np.exp(-dt_sim / T1_eff)

            if model_type in ['SOPDT', 'SO', 'SECOND_ORDER'] and T2_sim > 0:
                T2_eff = max(T2_sim, 0.01)
                alpha2 = 1.0 - np.exp(-dt_sim / T2_eff)
                x1_next = x1_s + alpha * (K_sim * delta_mv - x1_s)
                x2_next = x2_s + alpha2 * (x1_s - x2_s)
                x1_s, x2_s = x1_next, x2_next
                delta_pv = x2_s
            else:
                x1_next = x1_s + alpha * (K_sim * delta_mv - x1_s)
                x1_s = x1_next
                delta_pv = x1_s
            pv_current_s = pv_init + delta_pv
            pv_sim[i] = pv_current_s
        
        # 在子图1上绘制仿真PV
        ax1.plot(future_time_array, pv_sim, color='#00AA00', linestyle='-', 
                 label='新参数PV (仿真)', linewidth=2.0, alpha=0.9)
        ax1.plot(future_time_array, np.full(n_sim_steps, sv_target), 'r--', linewidth=1.0)
        ax1.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, 
                    label='仿真起点', alpha=0.7)
        ax1.axvspan(time_array[-1], future_time_array[-1], alpha=0.05, color='green')
        ax1.legend(loc='upper right')  # 更新legend
    
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
    try:
        ax2.plot(future_time_array, mv_sim, color='#00AA00', linestyle='-',
                 label='新参数MV (仿真)', linewidth=2.0, alpha=0.9)
        ax2.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, alpha=0.7)
        ax2.axvspan(time_array[-1], future_time_array[-1], alpha=0.05, color='green')
    except NameError:
        pass  # 仿真变量未定义时跳过
    
    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 拟合误差 或 振荡整定信息 ==========
    ax3 = fig.add_subplot(n_plots, 1, 3, sharex=ax1)
    # 判断是否为振荡整定模式（包括 oscillation_critical, oscillation_adaptive, oscillation_llm）
    fusion_method = fusion_info.get('method', '')
    is_oscillation_tuning = 'oscillation' in fusion_method
    
    if is_oscillation_tuning:
        # 振荡整定模式，显示整定信息而不是拟合误差
        pid_params = fitting_result.get('pid_parameters', {})
        model_params = fitting_result.get('model_parameters', {})
        
        info_text = f"振荡整定模式 ({fusion_method})\n\n"
        info_text += f"临界参数:\n"
        info_text += f"  Pu (临界周期) = {model_params.get('T1', 0):.2f} s\n"
        info_text += f"  K (过程增益) = {model_params.get('K', 0):.3f}\n\n"
        info_text += f"PID 参数:\n"
        info_text += f"  pb = {pid_params.get('pb', 0):.1f}%\n"
        info_text += f"  Ti = {pid_params.get('ti', 0):.2f} s\n"
        info_text += f"  Td = {pid_params.get('td', 0):.2f} s"
        
        # 如果有 LLM 决策信息，也显示
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
        
        # 重新进行闭环仿真以获取曲线数据
        from core.algorithm.model_type.tuning.core.pid_calculator import PIDCalculator
        from core.algorithm.model_type.data_models import FusionResult
        
        model_params = fitting_result.get('model_parameters', {})
        pid_params = fitting_result.get('pid_parameters', {})
        
        # 创建 FusionResult
        fusion = FusionResult(
            model_type=model_type,
            K=model_params.get('K', 0),
            T1=model_params.get('T1', 0),
            T2=model_params.get('T2', 0),
            L=model_params.get('L', 0)
        )
        
        # 进行闭环仿真（使用实际数据的初值）
        calculator = PIDCalculator()
        
        # 优先使用 closed_loop_info 中保存的仿真参数（确保与验证时一致）
        sp_initial = closed_loop_info.get('sp_initial')
        sp_final = closed_loop_info.get('sp_final')
        pv_initial = closed_loop_info.get('pv_initial')
        
        # 如果没有保存的参数，则从 fit_data 获取
        if sp_initial is None or sp_final is None:
            sv_data = fit_data.get('sv', [])
            pv_data = fit_data.get('pv', [])
            
            sp_initial = sv_data[0] if sv_data else 50.0
            sp_final = sv_data[-1] if sv_data else 60.0
            pv_initial = pv_data[0] if pv_data else sp_initial
            
            # 确保有足够的阶跃幅度，并且初值合理
            sp_change = abs(sp_final - sp_initial)
            pv_sp_diff = abs(pv_initial - sp_initial)
            
            # 如果 SP 阶跃幅度太小，或者 PV 初值与 SP 初值差距太大，使用默认阶跃测试
            if sp_change < 5.0 or pv_sp_diff > sp_change * 2:
                sp_initial = 50.0
                sp_final = 60.0
                pv_initial = 50.0  # 假设稳态开始
        
        sp_change = abs(sp_final - sp_initial)
        
        # 自适应仿真参数
        # 对于振荡整定，使用临界周期 Pu 作为参考
        if is_oscillation_tuning:
            Pu = model_params.get('T1', 10.0)  # 振荡整定时 T1 = Pu
            T_ref = Pu
        else:
            T_ref = fusion.T1 if fusion.T1 > 0 else 10.0
        
        T_min = T_ref
        T2_val = fusion.T2 if fusion.T2 > 0 else T_ref
        T_min = min(T_ref, T2_val) if min(T_ref, T2_val) > 0 else T_ref
        T_max = max(T_ref, T2_val)
        
        # 真实步长：利用真实数据的间隔，避免高频平滑掩盖了真实采样场景下的离散发散现象
        if len(timestamps) > 1:
            dt = (timestamps[1] - timestamps[0]) / 1000.0
        else:
            dt = T_max / 100
        dt = max(0.5, dt)
        
        sim_time = max(300, T_max * 40)  # 加长仿真时间确保看到完整稳态过程
        sim_time = min(sim_time, 50000)  # 封顶约14小时
        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 50000)  # 允许更多步数以展示长时间行为
        
        # 直接使用 fusion 中的模型参数（振荡整定已经估算了合理的参数）
        K_est = fusion.K
        T1_est = fusion.T1
        sim_model_type = fusion.model_type
        
        metrics = calculator.simulate_closed_loop(
            K=K_est, T1=T1_est, T2=fusion.T2, L=fusion.L,
            model_type=sim_model_type,
            Kp=pid_params.get('kp', 1), Ki=pid_params.get('ki', 0), Kd=pid_params.get('kd', 0),
            sp_initial=sp_initial,
            sp_final=sp_final,
            pv_initial=pv_initial,
            n_steps=n_steps,
            dt=dt
        )
        
        # 时间轴
        t_sim = np.arange(len(metrics.pv_history)) * dt
        
        # SP曲线
        sp_sim = np.zeros_like(metrics.pv_history)
        sp_sim[:10] = sp_initial
        sp_sim[10:] = sp_final
        
        # 绘制闭环响应
        ax4.plot(t_sim, metrics.pv_history, 'b-', label='PV (闭环响应)', linewidth=1.5)
        ax4.plot(t_sim, sp_sim, 'r--', label='SP (设定值)', linewidth=1.2)
        
        # 标记性能指标
        is_stable = closed_loop_info.get('is_stable', False)
        settling_time = closed_loop_info.get('settling_time', -1)
        overshoot = closed_loop_info.get('overshoot', 0)
        rise_time = closed_loop_info.get('rise_time', -1)
        sse = closed_loop_info.get('steady_state_error', 0)
        
        status_color = 'green' if is_stable else 'red'
        status_text = '稳定' if is_stable else '不稳定'
        
        # 添加性能指标文本框
        textstr = f'{status_text}\n'
        textstr += f'调节时间: {settling_time:.1f}s\n' if settling_time >= 0 else '调节时间: N/A\n'
        textstr += f'超调量: {overshoot:.1f}%\n'
        textstr += f'上升时间: {rise_time:.1f}s\n' if rise_time >= 0 else '上升时间: N/A\n'
        textstr += f'稳态误差: {sse:.2f}%'
        
        props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
        ax4.text(0.98, 0.95, textstr, transform=ax4.transAxes, fontsize=10,
                verticalalignment='top', horizontalalignment='right', bbox=props)
        
        # ±2%误差带（基于实际 sp_final）
        error_band = sp_change * 0.02  # 2% 的阶跃幅度
        ax4.axhline(y=sp_final + error_band, color='gray', linestyle=':', alpha=0.5, label='±2%误差带')
        ax4.axhline(y=sp_final - error_band, color='gray', linestyle=':', alpha=0.5)
        ax4.fill_between(t_sim, sp_final - error_band, sp_final + error_band, 
                        alpha=0.1, color='green')
        
        # 如果有有效的调节时间，画垂直线标注
        if settling_time >= 0 and settling_time < t_sim[-1]:
            ax4.axvline(x=settling_time, color='purple', linestyle='--', linewidth=1.5, 
                       label=f'调节时间 ({settling_time:.1f}s)')
            # 在调节时间点添加标注
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
        
        # 调整 x 轴范围：确保能看到完整的稳态过程
        # 检查 PV 是否已经达到稳态（在 ±2% 误差带内）
        pv_final = metrics.pv_history[-1]
        error_band = abs(sp_final - sp_initial) * 0.02  # 2% 误差带
        is_converged = abs(pv_final - sp_final) <= error_band
        
        if is_converged and settling_time >= 0 and settling_time < t_sim[-1]:
            # 已收敛，显示到调节时间的1.3倍
            x_max = min(t_sim[-1], max(80, settling_time * 1.3))
        elif not is_converged:
            # 还在收敛中，显示到仿真结束或找到稳态点
            # 找到首次进入误差带的时间
            for i in range(len(metrics.pv_history) - 1, -1, -1):
                if abs(metrics.pv_history[i] - sp_final) > error_band:
                    # 从这个点开始还没稳定，显示到后面一点
                    converge_time = (i + 1) * dt
                    x_max = min(t_sim[-1], converge_time * 1.2)
                    break
            else:
                x_max = t_sim[-1]  # 整个过程都在收敛
        else:
            x_max = t_sim[-1]  # 默认显示完整仿真
        ax4.set_xlim([0, x_max])
        
        # 调整 y 轴范围：确保能显示完整的 PV 响应（包括超调峰值）
        pv_min = min(np.min(metrics.pv_history), sp_initial, sp_final)
        pv_max = max(np.max(metrics.pv_history), sp_initial, sp_final)
        y_margin = (pv_max - pv_min) * 0.1  # 10% 边距
        ax4.set_ylim([pv_min - y_margin, pv_max + y_margin])
        
        # 如果有超调，标注峰值
        if overshoot > 0:
            peak_idx = np.argmax(metrics.pv_history) if sp_change > 0 else np.argmin(metrics.pv_history)
            peak_val = metrics.pv_history[peak_idx]
            peak_time = peak_idx * dt
            if peak_time <= x_max:  # 只在显示范围内标注
                ax4.plot(peak_time, peak_val, 'ro', markersize=6)
                ax4.annotate(f'峰值: {peak_val:.1f}\n超调: {overshoot:.1f}%', 
                            xy=(peak_time, peak_val), 
                            xytext=(peak_time + 5, peak_val),
                            fontsize=8, color='red',
                            arrowprops=dict(arrowstyle='->', color='red', lw=0.8))
    
    # ========== 子图5: 新PID仿真预测（使用真实过程模型） ==========
    if has_closed_loop:
        ax5 = fig.add_subplot(n_plots, 1, 5)
        
        # 获取模型参数
        model_params = fitting_result.get('model_parameters', {})
        pid_params = fitting_result.get('pid_parameters', {})
        
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        T2 = model_params.get('T2', 0.0)
        L = model_params.get('L', 0.0)
        
        Kp = pid_params.get('kp', 1.0)
        Ki = pid_params.get('ki', 0.0)
        Kd = pid_params.get('kd', 0.0)
        
        # 采样间隔
        if len(timestamps) > 1:
            dt_sim = (timestamps[1] - timestamps[0]) / 1000.0
        else:
            dt_sim = 1.0
        
        # 仿真时长 - 拉长以观察稳态收敛
        sim_duration = max(T1 * 40, 1000)  # 至少 40 倍时间常数或 1000 秒
        n_sim_steps = min(int(sim_duration / dt_sim), 20000)
        
        # 初始条件
        pv_init = pv_array[-1]
        mv_init = mv_array[-1]
        sv_target = sv_array[-1]
        
        # 如果初始偏差太小，引入阶跃
        initial_error = abs(sv_target - pv_init)
        if initial_error < 2.0:
            # 根据过程增益和MV可用范围计算最大可达阶跃
            # 负增益系统: MV下降→PV上升, 可用下降空间 = mv_init - 0
            # 正增益系统: MV上升→PV上升, 可用上升空间 = 100 - mv_init
            if K < 0:
                mv_margin = mv_init * 0.8  # 留20%余量
            else:
                mv_margin = (100 - mv_init) * 0.8
            max_achievable_step = abs(K) * mv_margin
            desired_step = max(np.ptp(sv_array) * 0.1, 1.0)
            step = min(desired_step, max_achievable_step)
            sv_target = sv_target + step
        
        # 状态初始化
        pv_sim = np.zeros(n_sim_steps)
        mv_sim = np.zeros(n_sim_steps)
        sv_sim = np.full(n_sim_steps, sv_target)
        
        x1, x2 = 0.0, 0.0
        integral = 0.0
        prev_error = sv_target - pv_init
        delay_steps = max(1, int(L / dt_sim)) if L > 0 else 1
        mv_history = [mv_init] * delay_steps
        pv_current = pv_init
        pv_base = pv_init
        mv_base = mv_init
        
        for i in range(n_sim_steps):
            error = sv_target - pv_current
            integral += error * dt_sim
            derivative = (error - prev_error) / dt_sim if dt_sim > 0 else 0.0
            prev_error = error
            
            # 积分限幅
            integral = np.clip(integral, -100/(abs(Ki)+1e-10), 100/(abs(Ki)+1e-10))
            
            # PID 输出（先算原始值）
            mv_raw = mv_base + Kp * error + Ki * integral + Kd * derivative
            mv_out = np.clip(mv_raw, 0, 100)
            
            # Anti-windup: 如果MV被饱和截断，回退积分以防止windup
            if mv_raw != mv_out and abs(Ki) > 1e-10:
                integral = (mv_out - mv_base - Kp * error - Kd * derivative) / Ki
            
            mv_sim[i] = mv_out
            
            mv_history.append(mv_out)
            mv_delayed = mv_history.pop(0)
            delta_mv = mv_delayed - mv_base
            
            T1_eff = max(T1, 0.01)
            alpha = 1.0 - np.exp(-dt_sim / T1_eff)
            x1_next = x1 + alpha * (K * delta_mv - x1)
            x1 = x1_next
            pv_current = pv_base + x1
            pv_sim[i] = pv_current
        
        t_sim = np.arange(n_sim_steps) * dt_sim
        
        # 绘制
        ax5.plot(t_sim, pv_sim, 'b-', label='PV (预测)', linewidth=1.5)
        ax5.axhline(y=sv_target, color='r', linestyle='--', label=f'SV={sv_target:.1f}', linewidth=1.2)
        ax5.fill_between(t_sim, sv_target * 0.95, sv_target * 1.05, alpha=0.2, color='green', label='±5%误差带')
        ax5.axhline(y=pv_init, color='gray', linestyle=':', alpha=0.5, label=f'初始PV={pv_init:.1f}')
        
        # 稳态判定
        error_band = abs(sv_target) * 0.05
        in_band = np.abs(pv_sim[-100:] - sv_target) < error_band if len(pv_sim) >= 100 else False
        is_stable_predict = np.all(in_band) if isinstance(in_band, np.ndarray) else False
        stable_status = '预测稳态' if is_stable_predict else '预测不稳态'
        
        ax5.set_xlabel('仿真时间 (s)')
        ax5.set_ylabel('PV')
        ax5.set_title(f'新PID参数仿真预测（基于估算模型）- {stable_status}')
        ax5.legend(loc='upper right')
        ax5.grid(True, alpha=0.3)
        ax5.set_xlim([0, t_sim[-1]])
    
    plt.tight_layout()
    
    # 保存图表
    if scenario_name:
        filename = f'model_selector_{scenario_name}.png'
    else:
        filename = 'model_selector_result.png'
    
    filepath = f'/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test/{filename}'
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 图表已保存至: test/{filename}")
    plt.close()


def visualize_new_pid_simulation(data: List[Dict], fitting_result: Dict, scenario_name: str = None):
    """
    可视化新整定参数从原始数据最后一个点开始的未来仿真走势
    
    从原始数据的最后一个点开始，使用新的PID参数进行闭环仿真，
    展示新参数下的预期控制轨迹，与原始数据合并在一张图中。
    
    Args:
        data: 原始历史数据
        fitting_result: ModelSelector 的整定结果
        scenario_name: 场景名称（用于文件命名）
    """
    # 获取原始数据
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    
    # 获取模型和PID参数
    model_params = fitting_result.get('model_parameters', {})
    pid_params = fitting_result.get('pid_parameters', {})
    model_type = fitting_result.get('model_type', 'FOPDT')
    
    K = model_params.get('K', 1.0)
    T1 = model_params.get('T1', 10.0)
    T2 = model_params.get('T2', 0.0)
    L = model_params.get('L', 0.0)
    
    Kp = pid_params.get('kp', 1.0)
    Ki = pid_params.get('ki', 0.0)
    Kd = pid_params.get('kd', 0.0)
    
    # 计算采样间隔 (秒)
    if len(timestamps) > 1:
        dt = (timestamps[1] - timestamps[0]) / 1000.0  # ms -> s
    else:
        dt = 1.0
    
    # ========== 从最后一个点开始仿真未来轨迹 ==========
    # 仿真时间：足够长以展示新PID参数的控制效果
    # 使用 max(50*T1, 3600秒) 确保能看到完整的调节过程
    original_duration = (timestamps[-1] - timestamps[0]) / 1000.0  # 秒
    T1_based_duration = max(T1 * 50, 3600)  # 至少 50 倍时间常数或 1 小时
    sim_duration = min(T1_based_duration, 36000)  # 上限 36000 秒（10小时）
    n_sim_steps = int(sim_duration / dt)
    n_sim_steps = max(2000, min(n_sim_steps, 50000))  # 限制在 2000~50000 步
    
    # 初始条件：原始数据的最后一个点
    pv_init = pv_array[-1]
    mv_init = mv_array[-1]
    sv_target = sv_array[-1]  # 使用最后一个设定值作为目标
    
    # 检测 MV 饱和情况 - 如果 MV 接近 0% 或 100%，则无法正常调节
    mv_saturated = (mv_init > 95) or (mv_init < 5)
    
    if mv_saturated:
        # MV 饱和时，使用标准阶跃测试工作点（与闭环验证一致）
        pv_range = np.ptp(pv_array)
        pv_mean = np.mean(pv_array)
        
        # 使用 PV 中间值作为初始点，产生 10% 阶跃
        pv_init = pv_mean
        mv_init = 50.0  # 中间位置
        sv_target = pv_mean + pv_range * 0.1
        print(f"   ⚠️ MV 饱和，切换到标准阶跃测试: PV={pv_init:.1f} → SV={sv_target:.1f}")
    else:
        # 如果初始偏差太小（PV已接近SV），人为引入10%阶跃扰动以展示调节效果
        initial_error = abs(sv_target - pv_init)
        sv_range = max(np.ptp(sv_array), 1.0)  # SV变化范围
        if initial_error < sv_range * 0.05:  # 偏差小于5%范围
            # 将SV提升10%以产生明显阶跃
            sv_step = sv_range * 0.1
            sv_target = sv_target + sv_step
            print(f"   📊 初始偏差较小，引入阶跃扰动: SV += {sv_step:.2f}")
    
    # 生成未来时间序列
    last_timestamp = timestamps[-1]
    dt_ms = int(dt * 1000)
    future_timestamps = [last_timestamp + i * dt_ms for i in range(1, n_sim_steps + 1)]
    future_time_array = [datetime.fromtimestamp(ts / 1000) for ts in future_timestamps]
    
    # 状态变量初始化
    pv_sim = np.zeros(n_sim_steps)
    mv_sim = np.zeros(n_sim_steps)
    sv_sim = np.full(n_sim_steps, sv_target)
    
    # 过程模型状态 (增量模型)
    x1 = 0.0
    x2 = 0.0
    
    # PID控制器状态 - 从当前偏差开始
    integral = 0.0
    prev_error = sv_target - pv_init
    
    # 延迟缓冲区
    delay_steps = max(1, int(L / dt)) if L > 0 else 1
    mv_history = [mv_init] * delay_steps
    
    # MV 限幅
    mv_min, mv_max = 0.0, 100.0
    
    # 基准点 (从最后一个点开始)
    pv_base = pv_init
    mv_base = mv_init
    
    pv_current = pv_init
    
    for i in range(n_sim_steps):
        sp = sv_target
        
        # PID 控制器计算
        error = sp - pv_current
        integral += error * dt
        derivative = (error - prev_error) / dt if dt > 0 else 0.0
        prev_error = error
        
        # 积分限幅
        integral = np.clip(integral, -100 / (abs(Ki) + 1e-10), 100 / (abs(Ki) + 1e-10))
        
        # PID 输出
        mv_out = mv_base + Kp * error + Ki * integral + Kd * derivative
        mv_out = np.clip(mv_out, mv_min, mv_max)
        mv_sim[i] = mv_out
        
        # 延迟处理
        mv_history.append(mv_out)
        mv_delayed = mv_history.pop(0)
        
        # 增量 MV
        delta_mv = mv_delayed - mv_base
        
        # 过程模型更新
        if model_type in ['SOPDT', 'SECOND_ORDER']:
            T1_eff = max(T1, dt)
            T2_eff = max(T2, dt) if T2 > 0 else T1_eff
            dx1 = (K * delta_mv - x1) / T1_eff
            dx2 = (x1 - x2) / T2_eff
            x1 += dx1 * dt
            x2 += dx2 * dt
            delta_pv = x2
        else:
            T1_eff = max(T1, dt)
            dx1 = (K * delta_mv - x1) / T1_eff
            x1 += dx1 * dt
            delta_pv = x1
        
        pv_current = pv_base + delta_pv
        pv_sim[i] = pv_current
    
    # ========== 创建合并图表 ==========
    fig = plt.figure(figsize=(18, 8))
    
    pb = pid_params.get('pb', Kp * 100 if Kp > 0 else 100)
    ti = pid_params.get('ti', 0)
    td = pid_params.get('td', 0)
    
    fig.suptitle(f'原始数据 + 新参数未来仿真 (pb={pb:.1f}%, Ti={ti:.1f}s, Td={td:.2f}s)\n'
                 f'模型: {model_type}, K={K:.3f}, T1={T1:.1f}s, L={L:.1f}s', 
                 fontsize=12, fontweight='bold')
    
    # ========== 子图1: PV/SV ==========
    ax1 = fig.add_subplot(2, 1, 1)
    
    # 只显示最后2小时的历史数据，避免仿真部分被挤压
    show_history_seconds = 7200  # 显示最后2小时的历史数据
    show_history_points = int(show_history_seconds / dt)
    hist_start = max(0, len(time_array) - show_history_points)
    
    # 原始数据（仅最后部分）
    ax1.plot(time_array[hist_start:], pv_array[hist_start:], 'b-', label='原始PV (实测)', linewidth=0.8, alpha=0.8)
    ax1.plot(time_array[hist_start:], sv_array[hist_start:], 'r--', label='SV (设定值)', linewidth=1.0)
    
    # 未来仿真轨迹 (绿色，加粗)
    ax1.plot(future_time_array, pv_sim, 'g-', label='新参数PV (仿真预测)', linewidth=2.0)
    ax1.plot(future_time_array, sv_sim, 'r--', linewidth=1.0)  # 延续 SV
    
    # 分界线
    ax1.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, 
                label='仿真起点', alpha=0.8)
    
    # 仿真区域背景
    ax1.axvspan(time_array[-1], future_time_array[-1], alpha=0.1, color='green')
    
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值：原始数据 + 新参数仿真预测')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    
    # 原始数据（仅最后部分）
    ax2.plot(time_array[hist_start:], mv_array[hist_start:], 'b-', label='原始MV (实测)', linewidth=0.8, alpha=0.8)
    
    # 未来仿真轨迹
    ax2.plot(future_time_array, mv_sim, 'g-', label='新参数MV (仿真预测)', linewidth=2.0)
    
    # 分界线
    ax2.axvline(x=time_array[-1], color='purple', linestyle='--', linewidth=1.5, alpha=0.8)
    
    # 仿真区域背景
    ax2.axvspan(time_array[-1], future_time_array[-1], alpha=0.1, color='green')
    
    ax2.set_ylabel('MV')
    ax2.set_xlabel('时间')
    ax2.set_title('操作值：原始数据 + 新参数仿真预测')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # 保存图表
    if scenario_name:
        filename = f'new_pid_simulation_{scenario_name}.png'
    else:
        filename = f'new_pid_simulation_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    
    filepath = f"{CONFIG['log_dir']}/{filename}"
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 新参数仿真图表已保存至: {filepath}")
    plt.close()


def print_result_json(result: Dict):
    """打印完整的结果 JSON 格式"""
    import json
    
    fitting_result = result.get('fitting_result', {})
    
    # 格式化 pid_parameters 保留4位小数
    pid_params = result.get('pid_parameters', {})
    pid_params_formatted = {
        k: f"{v:.4f}" if isinstance(v, (int, float)) else v 
        for k, v in pid_params.items()
    }
    
    # 格式化 model_parameters 保留4位小数
    model_params = result.get('model_parameters', {})
    model_params_formatted = {
        k: f"{v:.4f}" if isinstance(v, (int, float)) else v 
        for k, v in model_params.items()
    }
    
    # 格式化 tuning_features
    tuning_features = result.get('tuning_features', {})
    tuning_features_formatted = {}
    for k, v in tuning_features.items():
        if isinstance(v, float):
            tuning_features_formatted[k] = round(v, 4)
        elif isinstance(v, (bool, int, str, list, dict)):
            tuning_features_formatted[k] = v
        else:
            tuning_features_formatted[k] = str(v)
    
    output = {
        'success': bool(result.get('success')),  # 转换 numpy.bool_ 为 Python bool
        'model_type': result.get('model_type'),
        'turning_type': result.get('turning_type'),
        'model_rating': float(result.get('model_rating', 0)),
        'start_time': str(result.get('start_time')),
        'end_time': str(result.get('end_time')),
        'model_parameters': model_params_formatted,
        'pid_parameters': pid_params_formatted,
        'fitting_result': {
            'r_squared': round(fitting_result.get('r_squared', 0), 4),
            'rmse': round(fitting_result.get('rmse', 0), 4),
            'data_points': len(fitting_result.get('pv', [])),
            'recommendation': fitting_result.get('recommendation')
        },
        'tuning_features': tuning_features_formatted
    }
    
    print("\n" + "=" * 60)
    print("输出 JSON 格式验证")
    print("=" * 60)
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ============================================================
# 日志保存类
# ============================================================

class TeeOutput:
    """同时输出到控制台和文件"""
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


# ============================================================
# 主测试入口
# ============================================================

if __name__ == "__main__":
    
    # 从 CONFIG 读取配置
    log_dir = CONFIG['log_dir']
    verbose = CONFIG['verbose']
    response_mode = CONFIG['response_mode']
    scenarios = CONFIG['scenarios']
    
    # 设置日志文件
    os.makedirs(log_dir, exist_ok=True)
    log_filename = os.path.join(log_dir, f'model_selector_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    
    # 启用日志保存
    tee = TeeOutput(log_filename)
    sys.stdout = tee
    print(f"📝 日志保存至: {log_filename}\n")
    
    for idx, scenario in enumerate(scenarios, 1):
        start_time_str = scenario['start_time']
        end_time_str = scenario['end_time']
        
        # 转换为时间戳
        start_ts = int(datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        
        print(f"\n{'='*60}")
        print(f"场景 {idx}: {start_time_str} ~ {end_time_str}")
        print(f"{'='*60}")
        
        scenario_total_start = time.time()
        
        # Step 1: 获取历史数据
        step1_start = time.time()
        data = get_history_data(start_ts, end_ts)
        step1_elapsed = time.time() - step1_start
        if not data:
            continue
        
        # Step 2: 检测扰动段
        step2_start = time.time()
        tuning_input = detect_tuning_windows(data)
        step2_elapsed = time.time() - step2_start
        qualified_windows = tuning_input.get('qualified_windows', [])
        if not qualified_windows:
            print("⚠️ 未检测到扰动段，无需整定，跳过")
            continue
        
        # Step 3: 执行模型拟合
        result = run_model_selector(data, qualified_windows, verbose=verbose, response_mode=response_mode)
        
        # Step 4: 打印 JSON 格式
        print_result_json(result)
        
        # Step 5: 可视化
        step5_start = time.time()
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_fitting_result(data, tuning_input, result, scenario_name)
        
        # Step 5.1: 新参数仿真图
        if result.get('success'):
            visualize_new_pid_simulation(data, result, scenario_name)
        
        step5_elapsed = time.time() - step5_start
        
        # 汇总耗时统计
        scenario_total_elapsed = time.time() - scenario_total_start
        tuning_elapsed = result.get('tuning_elapsed_time', 0)
        
        print(f"\n📊 场景 {idx} 耗时统计:")
        print(f"   ‣ 数据获取: {step1_elapsed:.2f} 秒")
        print(f"   ‣ 扰动检测: {step2_elapsed:.2f} 秒")
        print(f"   ‣ 模型整定: {tuning_elapsed:.2f} 秒")
        print(f"   ‣ 可视化:   {step5_elapsed:.2f} 秒")
        print(f"   ━━━━━━━━━━━━━━━━━━━━")
        print(f"   ‣ 总耗时:     {scenario_total_elapsed:.2f} 秒")
    
    # 关闭日志
    print(f"\n{'='*60}")
    print(f"✅ 测试完成，日志已保存至: {log_filename}")
    print(f"{'='*60}")
    sys.stdout = tee.terminal
    tee.close()
