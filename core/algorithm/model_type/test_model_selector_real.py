import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Dict
import pandas as pd

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
from core.algorithm.model_type.model_selector import ModelSelector


# ============================================================
# 数据获取
# ============================================================

def get_history_data(start_time: int, end_time: int, loop_uri: str = None) -> List[Dict]:
    """获取历史数据"""
    if loop_uri is None:
        loop_uri = '/pid_zd/0b521c82a96d4107a564e4c2678bdeca'
    
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

def test_model_selector(data: List[Dict], tuning_input: Dict, verbose: bool = True) -> Dict:
    """
    测试 ModelSelector
    
    Args:
        data: 原始历史数据
        tuning_input: 整定输入（来自 StabilityDetector）
        verbose: 是否输出详细日志
        
    Returns:
        整定结果
    """
    print("\n" + "=" * 60)
    print("ModelSelector 整定测试")
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
        
        if quality_report['warnings']:
            print("   ⚠️  警告:")
            for w in quality_report['warnings']:
                print(f"      - {w}")
    
    # 打印输入信息
    print(f"\n📥 输入参数:")
    print(f"   start_time: {tuning_input.get('start_time')}")
    print(f"   end_time: {tuning_input.get('end_time')}")
    print(f"   total_windows: {tuning_input.get('total_windows')}")
    
    tuning_windows = tuning_input.get('tuning_window', [])
    print(f"   tuning_window ({len(tuning_windows)} 个扰动段):")
    for i, w in enumerate(tuning_windows):
        start_str = w.get('start_time_str', w.get('start_time'))
        end_str = w.get('end_time_str', w.get('end_time'))
        print(f"      [{i+1}] {start_str} ~ {end_str}")
    
    # 调用 ModelSelector
    selector = ModelSelector(verbose=verbose)
    result = selector.fit(
        tuning_input=tuning_input,
        raw_data=data,
        lambda_factor=0.8
    )
    
    # 打印输出结果
    print(f"\n📤 输出结果:")
    print(f"   model_type: {result.get('model_type')}")
    print(f"   model_rating: {result.get('model_rating')}")
    print(f"   start_time: {result.get('start_time')}")
    print(f"   end_time: {result.get('end_time')}")
    
    model_params = result.get('model_parameters', {})
    print(f"\n   model_parameters:")
    print(f"      K  = {model_params.get('K')}")
    print(f"      T1 = {model_params.get('T1')}")
    print(f"      T2 = {model_params.get('T2')}")
    print(f"      L  = {model_params.get('L')}")
    
    pid_params = result.get('pid_parameters', {})
    print(f"\n   pid_parameters:")
    print(f"      Kp = {pid_params.get('Kp')}")
    print(f"      Ki = {pid_params.get('Ki')}")
    print(f"      Kd = {pid_params.get('Kd')}")
    
    fitting = result.get('fitting_result', {})
    r2 = fitting.get('r_squared', 0)
    print(f"\n   fitting_result:")
    print(f"      r_squared = {r2}")
    print(f"      rmse = {fitting.get('rmse')}")
    print(f"      数据点数 = {len(fitting.get('pv', []))}")
    
    # 新增: fusion_info
    fusion_info = result.get('fusion_info', {})
    print(f"\n   fusion_info:")
    print(f"      method = {fusion_info.get('method')}")
    print(f"      n_segments = {fusion_info.get('n_segments')}")
    print(f"      consistency_score = {fusion_info.get('consistency_score')}")
    print(f"      K_std = {fusion_info.get('K_std')}")
    print(f"      T1_std = {fusion_info.get('T1_std')}")
    
    # 新增: rating_details (综合评分详情)
    rating_details = result.get('rating_details', {})
    print(f"\n   rating_details (综合评分):")
    print(f"      r2_score = {rating_details.get('r2_score')} (权重40%)")
    print(f"      consistency_score = {rating_details.get('consistency_score')} (权重25%)")
    print(f"      validity_score = {rating_details.get('validity_score')} (权重20%)")
    print(f"      coverage_score = {rating_details.get('coverage_score')} (权重15%)")
    
    # 拟合质量评估
    if r2 >= 0.9:
        quality = "优秀 ✅"
    elif r2 >= 0.8:
        quality = "良好 ✅"
    elif r2 >= 0.7:
        quality = "可接受 ⚠️"
    elif r2 >= 0.5:
        quality = "较差 ⚠️"
    else:
        quality = "不可用 ❌"
    print(f"\n   拟合质量: {quality}")
    
    return result


def test_model_selector_new_format(data: List[Dict], qualified_windows: List[Dict], verbose: bool = True) -> Dict:
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
    input_data = {
        'history_data': data,
        'params': {
            'model_type': None,
            'turning_type': None,
            'analyst_column': 'pv'
        },
        'qualified_windows': qualified_windows
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
    
    # 打印输出结果（新格式）
    print(f"\n📤 输出结果（新格式）:")
    print(f"   model_type: {result.get('model_type')}")
    print(f"   turning_type: {result.get('turning_type')}")
    print(f"   model_rating: {result.get('model_rating')}")
    print(f"   start_time: {result.get('start_time')}")
    print(f"   end_time: {result.get('end_time')}")
    
    model_params = result.get('model_parameters', {})
    print(f"\n   model_parameters:")
    print(f"      K  = {model_params.get('K')}")
    print(f"      T1 = {model_params.get('T1')}")
    print(f"      T2 = {model_params.get('T2')}")
    print(f"      L  = {model_params.get('L')}")
    
    pid_params = result.get('pid_parameters', {})
    print(f"\n   pid_parameters:")
    print(f"      pb = {pid_params.get('pb')}")
    print(f"      ti = {pid_params.get('ti')}")
    print(f"      td = {pid_params.get('td')}")
    print(f"      kp = {pid_params.get('kp')}")
    print(f"      ki = {pid_params.get('ki')}")
    print(f"      kd = {pid_params.get('kd')}")
    
    fitting = result.get('fitting_result', {})
    print(f"\n   fitting_result:")
    print(f"      r_squared = {fitting.get('r_squared')}")
    print(f"      rmse = {fitting.get('rmse')}")
    print(f"      数据点数 = {len(fitting.get('pv', []))}")
    print(f"      recommendation = {fitting.get('recommendation')}")
    
    return result


# ============================================================
# 可视化
# ============================================================

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
    
    # 标记 tuning_window（扰动段）
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
            ax1.axvspan(start_dt, end_dt, alpha=0.2, color='orange', 
                       label='扰动段' if i == 0 else None)
    
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值与模型拟合对比')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    
    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(n_plots, 1, 2, sharex=ax1)
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    
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
            ax2.axvspan(start_dt, end_dt, alpha=0.2, color='orange')
    
    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 拟合误差 ==========
    ax3 = fig.add_subplot(n_plots, 1, 3, sharex=ax1)
    if fit_time_array and fit_pv and fit_pv_model:
        error = np.array(fit_pv) - np.array(fit_pv_model)
        ax3.plot(fit_time_array, error, 'r-', label='误差 (PV - PV_model)', linewidth=0.8)
        ax3.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
        ax3.fill_between(fit_time_array, error, 0, alpha=0.3, color='red')
    
    ax3.set_ylabel('误差')
    ax3.set_title('拟合误差')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    
    # ========== 子图4: 闭环稳定性验证 ==========
    if has_closed_loop:
        ax4 = fig.add_subplot(n_plots, 1, 4)
        
        # 重新进行闭环仿真以获取曲线数据
        from core.algorithm.model_type.pid_calculator import PIDCalculator
        from core.algorithm.model_type.models import FusionResult
        
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
        
        # 从 fitting_result 获取实际 SV 和 PV
        sv_data = fitting_result.get('sv', [])
        pv_data = fitting_result.get('pv', [])
        
        sp_initial = sv_data[0] if sv_data else 50.0
        sp_final = sv_data[-1] if sv_data else 60.0
        pv_initial = pv_data[0] if pv_data else sp_initial
        
        # 确保有足够的阶跃幅度
        sp_change = abs(sp_final - sp_initial)
        if sp_change < 5.0:
            sp_final = sp_initial + 10.0
            sp_change = 10.0
        
        # 自适应仿真参数
        T_min = min(fusion.T1, fusion.T2 if fusion.T2 > 0 else fusion.T1)
        dt = min(0.1, T_min / 10)
        dt = max(0.01, dt)
        T_max = max(fusion.T1, fusion.T2 if fusion.T2 > 0 else fusion.T1)
        sim_time = max(100, T_max * 20)
        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 5000)
        
        metrics = calculator.simulate_closed_loop(
            K=fusion.K, T1=fusion.T1, T2=fusion.T2, L=fusion.L,
            model_type=fusion.model_type,
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
        
        ax4.set_xlabel('时间 (s)')
        ax4.set_ylabel('PV / SP')
        ax4.set_title(f'闭环稳定性验证 (Kp={pid_params.get("kp", 0):.3f}, Ki={pid_params.get("ki", 0):.3f}, Kd={pid_params.get("kd", 0):.3f})')
        ax4.legend(loc='lower right')
        ax4.grid(True, alpha=0.3)
        ax4.set_xlim([0, min(t_sim[-1], 50)])  # 限制显示范围
    
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
    
    output = {
        'success': result.get('success'),
        'model_type': result.get('model_type'),
        'turning_type': result.get('turning_type'),
        'model_rating': result.get('model_rating'),
        'start_time': str(result.get('start_time')),
        'end_time': str(result.get('end_time')),
        'model_parameters': result.get('model_parameters'),
        'pid_parameters': result.get('pid_parameters'),
        'fitting_result': {
            'r_squared': fitting_result.get('r_squared'),
            'rmse': fitting_result.get('rmse'),
            'data_points': len(fitting_result.get('pv', [])),
            'recommendation': fitting_result.get('recommendation')
        }
    }
    
    print("\n" + "=" * 60)
    print("输出 JSON 格式验证")
    print("=" * 60)
    print(json.dumps(output, indent=2, ensure_ascii=False))


# ============================================================
# 主测试入口
# ============================================================

if __name__ == "__main__":
    
    # 测试场景
    test_scenarios =  [
        {'start_time': '2025-11-06 16:41:58', 'end_time': '2025-11-06 16:48:58'},
        {'start_time': '2025-11-05 10:55:58', 'end_time': '2025-11-05 13:14:58'},
        {'start_time': '2025-11-11 18:50:58', 'end_time': '2025-11-11 20:08:58'},
        {'start_time': '2025-11-10 09:12:58', 'end_time': '2025-11-10 10:25:58'},
        {'start_time': '2025-11-05 09:33:58', 'end_time': '2025-11-05 17:24:58'},
        {'start_time': '2025-11-04 16:58:58', 'end_time': '2025-11-04 18:30:58'},  
        {'start_time': '2025-11-04 17:53:58', 'end_time': '2025-11-04 18:30:58'},
        {'start_time': '2025-11-05 11:05:58', 'end_time': '2025-11-05 15:38:58'},
        {'start_time': '2025-11-07 17:45:58', 'end_time': '2025-11-07 19:42:58'},
        {'start_time': '2025-11-05 09:51:22', 'end_time': '2025-11-05 17:50:58'},
        {'start_time': '2025-12-04 10:00:58', 'end_time': '2025-12-04 12:42:58'}, 
        {'start_time': '2025-12-07 05:00:58', 'end_time': '2025-12-07 12:42:58'},
        {'start_time': '2025-12-01 05:00:58', 'end_time': '2025-12-01 12:42:58'},
        {'start_time': '2025-12-07 21:27:58', 'end_time': '2025-12-08 21:42:58'},
    ]
    
    for idx, scenario in enumerate(test_scenarios, 1):
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
        
        # Step 2: 检测扰动段（获取 tuning_input）
        tuning_input = detect_tuning_windows(data)
        
        qualified_windows = tuning_input.get('qualified_windows', [])
        if len(qualified_windows) == 0:
            print("⚠️ 未检测到扰动段，跳过")
            continue
        
        # Step 3: 执行模型拟合（使用新格式 run 方法）
        result = test_model_selector_new_format(data, qualified_windows, verbose=True)
        
        # Step 4: 打印 JSON 格式验证
        print_result_json(result)
        
        # Step 5: 可视化
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_fitting_result(data, tuning_input, result, scenario_name)
