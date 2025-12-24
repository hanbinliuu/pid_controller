"""ModelSelector 整定测试脚本

使用方法:
    1. 修改 CONFIG 配置区域的参数
    2. 运行: python test_model_selector_real.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
from core.algorithm.model_type.model_selector import ModelSelector
 

# ============================================================
# 配置区域 - 修改这里的参数进行测试
# ============================================================

CONFIG = {
    # 回路 URI
    # 'loop_uri': "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951",
    # 'loop_uri': "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",  #101
    'loop_uri': "/pid_zd/b352328ec0cd4a9c958b32815e67a96a", #029a
    # 'loop_uri': "/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582" , # FIC005A1
    # "loop_uri": "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951", # FIC002A
    
    # 测试场景列表 (可添加多个场景)
    'scenarios': [
        # {'start_time': '2025-12-17 00:31:36', 'end_time': '2025-12-17 23:31:36'},
         {'start_time': '2025-12-23 00:32:15', 'end_time': '2025-12-23 23:30:15'},
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
    result = selector.run(input_data)
    
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
    
    # 创建图表：如果有闭环数据则4个子图，否则3个
    n_plots = 4 if has_closed_loop else 3
    fig = plt.figure(figsize=(16, 4 * n_plots))
    
    model_type = fitting_result.get('model_type', 'Unknown')
    r2 = fit_data.get('r_squared', 0)
    rmse = fit_data.get('rmse', 0)
    fusion_info = fitting_result.get('fusion_info', {})
    
    # 闭环状态
    cl_status = ""
    if has_closed_loop:
        is_stable = closed_loop_info.get('is_stable', False)
        cl_status = f" | 闭环: {'✅稳定' if is_stable else '❌不稳定'}"
    
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
    
    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 拟合误差 ==========
    ax3 = fig.add_subplot(n_plots, 1, 3, sharex=ax1)
    # 判断是否为振荡整定模式
    is_oscillation_tuning = fusion_info.get('method') == 'oscillation_critical'
    if is_oscillation_tuning:
        # 振荡整定没有模型拟合，显示提示信息
        ax3.text(0.5, 0.5, '振荡整定模式\n无模型拟合（使用临界法）', 
                transform=ax3.transAxes, ha='center', va='center',
                fontsize=14, color='gray', style='italic')
        ax3.set_title('拟合误差 - 振荡整定模式')
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
        from core.algorithm.model_type.tuning.pid_calculator import PIDCalculator
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
        T_min = min(T_ref, T2_val)
        dt = min(0.1, T_min / 10)
        dt = max(0.01, dt)
        T_max = max(T_ref, T2_val)
        sim_time = max(200, T_max * 25)  # 增加仿真时间确保看到稳态
        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 10000)  # 增加最大步数
        
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
        status_text = '✅ 稳定' if is_stable else '❌ 不稳定'
        
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
    
    output = {
        'success': result.get('success'),
        'model_type': result.get('model_type'),
        'turning_type': result.get('turning_type'),
        'model_rating': result.get('model_rating'),
        'start_time': str(result.get('start_time')),
        'end_time': str(result.get('end_time')),
        'model_parameters': model_params_formatted,
        'pid_parameters': pid_params_formatted,
        'fitting_result': {
            'r_squared': round(fitting_result.get('r_squared', 0), 4),
            'rmse': round(fitting_result.get('rmse', 0), 4),
            'data_points': len(fitting_result.get('pv', [])),
            'recommendation': fitting_result.get('recommendation')
        }
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
        
        # Step 1: 获取历史数据
        data = get_history_data(start_ts, end_ts)
        if not data:
            continue
        
        # Step 2: 检测扰动段
        tuning_input = detect_tuning_windows(data)
        qualified_windows = tuning_input.get('qualified_windows', [])
        if not qualified_windows:
            print("⚠️ 未检测到扰动段")
            # 即使没有扰动段，也可视化原始数据
            scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
            visualize_raw_data(data, scenario_name)
            continue
        
        # Step 3: 执行模型拟合
        result = run_model_selector(data, qualified_windows, verbose=verbose, response_mode=response_mode)
        
        # Step 4: 打印 JSON 格式
        print_result_json(result)
        
        # Step 5: 可视化
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_fitting_result(data, tuning_input, result, scenario_name)
    
    # 关闭日志
    print(f"\n{'='*60}")
    print(f"✅ 测试完成，日志已保存至: {log_filename}")
    print(f"{'='*60}")
    sys.stdout = tee.terminal
    tee.close()
