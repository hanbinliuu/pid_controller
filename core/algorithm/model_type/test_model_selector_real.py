"""
ModelSelector 测试案例
基于 model_identifier/test_identifier/test_model_fitter.py 的数据获取方式
"""

import sys
import os
# model_type -> algorithm -> core -> pid-agent-mvp
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
    from core.algorithm.model_type.data_preprocessor import DataPreprocessor
    
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
        'stats': {},
        'nonlinearity': None
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
    
    # 非线性分析
    preprocessor = DataPreprocessor(verbose=False)
    nonlinearity = preprocessor.analyze_nonlinearity(pv, mv)
    report['nonlinearity'] = {
        'is_nonlinear': nonlinearity.is_nonlinear,
        'score': round(nonlinearity.nonlinearity_score, 4),
        'gain_variation': round(nonlinearity.gain_variation, 4),
        'saturation': nonlinearity.saturation_detected,
        'deadzone': nonlinearity.deadzone_detected,
        'hysteresis': round(nonlinearity.hysteresis_score, 4),
        'description': nonlinearity.description,
        'recommended_model': nonlinearity.recommended_model,
        'segment_count': nonlinearity.segment_count
    }
    
    if nonlinearity.is_nonlinear:
        report['warnings'].append(f'检测到非线性: {nonlinearity.description}')
        report['recommendations'].append(f'建议使用{nonlinearity.recommended_model}模型，分{nonlinearity.segment_count}段拟合')
    
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
        
        # 非线性分析结果
        if quality_report.get('nonlinearity'):
            nl = quality_report['nonlinearity']
            print("\n   🔬 非线性分析:")
            print(f"      是否非线性: {'是' if nl['is_nonlinear'] else '否'}")
            print(f"      非线性评分: {nl['score']}")
            print(f"      增益变化: {nl['gain_variation']}")
            print(f"      饱和检测: {'是' if nl['saturation'] else '否'}")
            print(f"      死区检测: {'是' if nl['deadzone'] else '否'}")
            print(f"      迟滞程度: {nl['hysteresis']}")
            print(f"      描述: {nl['description']}")
            if nl['is_nonlinear']:
                print(f"      推荐模型: {nl['recommended_model']}")
                print(f"      建议分段数: {nl['segment_count']}")
        
        if quality_report['warnings']:
            print("\n   ⚠️  警告:")
            for w in quality_report['warnings']:
                print(f"      - {w}")
        
        if quality_report.get('recommendations'):
            print("\n   💡 建议:")
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
    """可视化模型拟合结果"""
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
    fusion_info = fitting_result.get('fusion_info', {})
    
    fig.suptitle(f'ModelSelector 拟合结果 - {model_type} (R²={r2:.4f}, RMSE={rmse:.4f})\n'
                 f'融合方法: {fusion_info.get("method", "N/A")}, 使用段数: {fusion_info.get("n_segments", 0)}, '
                 f'一致性: {fusion_info.get("consistency_score", 0):.2f}', 
                 fontsize=12, fontweight='bold')
    
    # ========== 子图1: PV/SV + 拟合曲线 ==========
    ax1 = axes[0]
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
    
    # ========== 子图2: MV ==========
    ax2 = axes[1]
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
    test_scenarios = [
        {'start_time': '2025-11-05 09:51:22', 'end_time': '2025-11-05 17:50:58'},
        # {'start_time': '2025-11-11 18:50:58', 'end_time': '2025-11-11 20:08:58'},
        # {'start_time': '2025-11-20 11:05:58', 'end_time': '2025-11-20 20:38:58'},
        # {'start_time': '2025-11-06 16:41:58', 'end_time': '2025-11-06 16:48:58'},
        # {'start_time': '2025-11-04 18:36:22', 'end_time': '2025-11-04 19:35:58'},
        # {'start_time': '2025-12-04 10:00:58', 'end_time': '2025-12-04 12:42:58'},
        # {'start_time': '2025-12-03 8:00:58', 'end_time': '2025-12-04 12:42:58'}
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
