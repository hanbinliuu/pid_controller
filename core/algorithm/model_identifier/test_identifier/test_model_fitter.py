"""
ModelFitter 测试案例
基于 tuning_segment/test_stability_detector.py 的数据获取方式
"""

import sys
import os
# test_identifier -> model_identifier -> algorithm -> core -> pid-agent-mvp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

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
from core.algorithm.model_identifier.model_type_detector import ModelFitter, fit_model_from_tuning_input


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
    
    Returns:
        {
            "start_time": datetime,
            "end_time": datetime,
            "params": {...},
            "total_windows": int,
            "tuning_window": [{"start_time": int (ms), "end_time": int (ms)}, ...]
        }
    
    注意：
        tuning_window 中的时间使用毫秒时间戳（与原始数据一致），
        避免 pandas Timestamp 的时区转换问题。
    """
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    
    # 构建 pandas Series（使用原始时间戳作为索引）
    time_index = pd.to_datetime(timestamps, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
    pv_series = pd.Series(pv_array, index=time_index)
    sv_series = pd.Series(sv_array, index=time_index)
    
    # 调用 StabilityDetector 获取整定窗口
    result = find_high_variability_periods(
        pv_series=pv_series,
        sv_series=sv_series,
        std_tol=0.2,
        min_len=10,
        min_segment_len=20
    )
    
    # 转换 tuning_window 时间为毫秒时间戳（与原始数据格式一致）
    # 避免 pandas Timestamp 的时区转换问题
    if result.get('tuning_window'):
        converted_windows = []
        for w in result['tuning_window']:
            start_dt = w['start_time']
            end_dt = w['end_time']
            
            # 将 Timestamp 转换为与原始数据一致的毫秒时间戳
            # 找到最接近的原始时间戳
            start_ms = _find_closest_timestamp(timestamps, time_index, start_dt)
            end_ms = _find_closest_timestamp(timestamps, time_index, end_dt)
            
            converted_windows.append({
                'start_time': start_ms,
                'end_time': end_ms,
                'start_time_str': str(start_dt),  # 保留字符串格式用于显示
                'end_time_str': str(end_dt)
            })
        result['tuning_window'] = converted_windows
    
    return result


def _find_closest_timestamp(timestamps: np.ndarray, time_index: pd.DatetimeIndex, 
                             target_dt: pd.Timestamp) -> int:
    """
    找到最接近目标时间的原始时间戳
    
    Args:
        timestamps: 原始毫秒时间戳数组
        time_index: pandas DatetimeIndex
        target_dt: 目标 Timestamp
    
    Returns:
        对应的原始毫秒时间戳
    """
    # 在 time_index 中找到最接近的索引
    idx = time_index.get_indexer([target_dt], method='nearest')[0]
    if 0 <= idx < len(timestamps):
        return int(timestamps[idx])
    return int(timestamps[0])


# ============================================================
# 模型拟合测试
# ============================================================

def analyze_data_quality(data: List[Dict]) -> Dict:
    """
    分析数据质量，给出预处理建议
    
    Returns:
        数据质量报告
    """
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
            report['recommendations'].append('强烈建议启用数据预处理和滤波')
        elif noise_ratio > 0.05:
            report['quality'] = 'noisy'
            report['warnings'].append(f'PV噪声较大 (ratio={noise_ratio:.4f})')
            report['recommendations'].append('建议启用滤波')
        else:
            report['quality'] = 'good'
    
    # 高频振荡检测
    if len(pv) > 10:
        sign_changes = np.sum(np.diff(np.sign(np.diff(pv))) != 0)
        oscillation_ratio = sign_changes / len(pv)
        report['stats']['oscillation_ratio'] = round(oscillation_ratio, 4)
        
        if oscillation_ratio > 0.3:
            report['warnings'].append(f'高频振荡严重 (ratio={oscillation_ratio:.4f})')
            report['recommendations'].append('需要强力滤波处理')
    
    # MV 离散性检测
    mv_unique = np.unique(mv)
    report['stats']['mv_unique_values'] = len(mv_unique)
    
    if len(mv_unique) <= 3:
        report['warnings'].append(f'MV离散值过少 ({len(mv_unique)}个)，可能为ON-OFF控制')
        report['recommendations'].append('使用强力滤波平滑ON-OFF信号')
    
    return report


def test_model_fitter(data: List[Dict], tuning_input: Dict, verbose: bool = True) -> Dict:
    """
    测试 ModelFitter
    
    Args:
        data: 原始历史数据
        tuning_input: 整定输入（来自 StabilityDetector）
        verbose: 是否输出详细日志
        
    Returns:
        整定结果
    """
    print("\n" + "=" * 60)
    print("ModelFitter 整定测试")
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
        
        if quality_report['recommendations']:
            print("   💡 建议:")
            for r in quality_report['recommendations']:
                print(f"      - {r}")
    
    # 打印输入信息
    print(f"\n📥 输入参数:")
    print(f"   start_time: {tuning_input.get('start_time')}")
    print(f"   end_time: {tuning_input.get('end_time')}")
    print(f"   total_windows: {tuning_input.get('total_windows')}")
    
    tuning_windows = tuning_input.get('tuning_window', [])
    print(f"   tuning_window ({len(tuning_windows)} 个扰动段):")
    for i, w in enumerate(tuning_windows):
        # 优先使用字符串格式显示，否则使用时间戳
        start_str = w.get('start_time_str', w.get('start_time'))
        end_str = w.get('end_time_str', w.get('end_time'))
        print(f"      [{i+1}] {start_str} ~ {end_str}")
    
    # 调用 ModelFitter (注意：内部已启用滤波)
    result = fit_model_from_tuning_input(
        tuning_input=tuning_input,
        raw_data=data,
        verbose=verbose,
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
    
    if r2 < 0.7:
        print("\n   💡 改进建议:")
        if r2 < 0.3:
            print("      1. 数据噪声可能过大，已自动应用强力滤波")
            print("      2. 检查扰动段选择是否合理")
            print("      3. 可能需要更长的响应数据")
        else:
            print("      1. 适当调整扰动段时间范围")
            print("      2. 增加数据采样密度")
    
    return result


# ============================================================
# 可视化
# ============================================================

def visualize_fitting_result(data: List[Dict], tuning_input: Dict, 
                              fitting_result: Dict, scenario_name: str = None):
    """
    可视化模型拟合结果
    
    Args:
        data: 原始历史数据
        tuning_input: 整定输入
        fitting_result: ModelFitter 的输出结果
        scenario_name: 场景名称
    """
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    
    # 从 fitting_result 提取拟合数据
    fit_data = fitting_result.get('fitting_result', {})
    fit_timestamps = fit_data.get('timestamp', [])
    fit_pv = fit_data.get('pv', [])
    fit_pv_model = fit_data.get('pv_model', [])
    fit_time_array = [datetime.fromtimestamp(ts / 1000) for ts in fit_timestamps] if fit_timestamps else []
    
    # 创建图表
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    
    model_type = fitting_result.get('model_type', 'Unknown')
    r2 = fit_data.get('r_squared', 0)
    rmse = fit_data.get('rmse', 0)
    fig.suptitle(f'ModelFitter 拟合结果 - {model_type} (R²={r2:.4f}, RMSE={rmse:.4f})', 
                 fontsize=14, fontweight='bold')
    
    # ========== 子图1: PV/SV + 拟合曲线 ==========
    ax1 = axes[0]
    ax1.plot(time_array, pv_array, 'b-', label='PV (实测)', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV (设定值)', linewidth=1.2)
    
    if fit_time_array and fit_pv_model:
        ax1.plot(fit_time_array, fit_pv_model, 'g-', label='PV_model (拟合)', linewidth=1.5, alpha=0.9)
    
    # 标记 tuning_window（扰动段）
    tuning_windows = tuning_input.get('tuning_window', [])
    for i, w in enumerate(tuning_windows):
        # 处理不同格式的时间：毫秒时间戳或 datetime
        start_ts = w.get('start_time')
        end_ts = w.get('end_time')
        if start_ts and end_ts:
            # 如果是数值（毫秒时间戳），转换为 datetime
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
    
    # ========== 子图2: MV ==========
    ax2 = axes[1]
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    
    # 标记 tuning_window
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
    ax3 = axes[2]
    if fit_time_array and fit_pv and fit_pv_model:
        error = np.array(fit_pv) - np.array(fit_pv_model)
        ax3.plot(fit_time_array, error, 'r-', label='误差 (PV - PV_model)', linewidth=0.8)
        ax3.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
        ax3.fill_between(fit_time_array, error, 0, alpha=0.3, color='red')
    
    ax3.set_ylabel('误差')
    ax3.set_xlabel('时间')
    ax3.set_title('拟合误差')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    
    # 格式化 x 轴
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
    
    plt.tight_layout()
    
    # 保存图表
    if scenario_name:
        filename = f'model_fitter_{scenario_name}.png'
    else:
        filename = 'model_fitter_result.png'
    
    filepath = f'/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test/{filename}'
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 图表已保存至: test/{filename}")
    plt.close()


def print_result_json(result: Dict):
    """打印完整的结果 JSON 格式（用于验证输出格式）"""
    import json
    
    # 创建可序列化的副本
    output = {
        'model_type': result.get('model_type'),
        'model_rating': result.get('model_rating'),
        'start_time': str(result.get('start_time')),
        'end_time': str(result.get('end_time')),
        'model_parameters': result.get('model_parameters'),
        'pid_parameters': result.get('pid_parameters'),
        'fitting_result': {
            'r_squared': result.get('fitting_result', {}).get('r_squared'),
            'rmse': result.get('fitting_result', {}).get('rmse'),
            'data_points': len(result.get('fitting_result', {}).get('pv', []))
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
    test_scenarios = [
        {'start_time': '2025-11-05 09:51:22', 'end_time': '2025-11-05 17:50:58'},  # 5个窗口，测试分级策略
        # {'start_time': '2025-11-03 10:55:58', 'end_time': '2025-11-03 12:14:58'},
        # {'start_time': '2025-11-11 18:50:58', 'end_time': '2025-11-11 20:08:58'},
        # {'start_time': '2025-12-03 11:05:58', 'end_time': '2025-12-03 20:38:58'}
        # {'start_time': '2025-12-04 02:10:22', 'end_time': '2025-12-04 10:35:58'}
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
        
        if tuning_input.get('total_windows', 0) == 0:
            print("⚠️ 未检测到扰动段，跳过")
            continue
        
        # Step 3: 执行模型拟合
        result = test_model_fitter(data, tuning_input, verbose=True)
        
        # Step 4: 打印 JSON 格式验证
        print_result_json(result)
        
        # Step 5: 可视化
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_fitting_result(data, tuning_input, result, scenario_name)
