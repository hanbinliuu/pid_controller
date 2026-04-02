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
from datetime import datetime
from typing import List, Dict

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.select_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
from core.algorithm.model_type.model_selector import ModelSelector

# 从共享可视化模块导入
from core.algorithm.model_type.tests.visualization_utils import (
    convert_to_arrays,
    resolve_process_model_type,
    normalize_pid_params,
    simulate_pid_prediction,
    visualize_fitting_result,
    visualize_new_pid_simulation,
    visualize_raw_data,
)

# ============================================================
# 配置区域 - 修改这里的参数进行测试
# ============================================================

CONFIG = {
    # 回路 URI
    # 'loop_uri': "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951", 
    'loop_uri': "/pid_zd/7d3298f025b84c46a2ed898f66dcfa3f",  #101
    # 'loop_uri': "/pid_zd/b352328ec0cd4a9c958b32815e67a96a", #029a
    # 'loop_uri': "/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582" , # FIC005A1
    # "loop_uri": "/pid_zd/effb57ab51cf4f6cad3f40d38f8c0951", # FIC002A
    
    # 测试场景列表 (可添加多个场景)
    'scenarios': [
        # {'start_time': '2025-12-23 00:00:00', 'end_time': '2025-12-23 23:00:00'},
        # {'start_time': '2026-03-11 04:09:30', 'end_time': '2026-03-11 10:09:30'},

        # {'start_time': '2026-03-11 04:09:30', 'end_time': '2026-03-11 10:09:30'},
        {'start_time': '2025-12-23 00:00:00', 'end_time': '2025-12-23 23:00:00'},
        
    ],
    
    # 响应模式: 'fast' | 'balanced' | 'conservative'
    'response_mode': 'conservative',
    
    # 搜索模式: 'auto_detect' | 'grid_search'
    'search_mode': 'grid_search',
    
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


# convert_to_arrays 已移至 visualization_utils.py，通过顶部 import 导入


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
# 可视化 (已移至 visualization_utils.py，通过顶部 import 导入)
# visualize_raw_data, visualize_fitting_result,
# visualize_new_pid_simulation 均从 visualization_utils 导入
# ============================================================



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
        
        # Step 2 & 3: 检测扰动段并执行模型拟合
        search_mode = CONFIG.get('search_mode', 'auto_detect')
        tuning_elapsed = 0
        tuning_input = {}
        
        if search_mode == 'grid_search':
            print("\n🔍 启动滑窗暴力搜索模式 (Grid Search)")
            step2_start = time.time()
            
            # 使用 6 小时窗，2小时步长进行滑窗
            window_size_ms = 6 * 3600 * 1000
            step_ms = 2 * 3600 * 1000
            
            best_score = -1.0
            best_result = None
            best_window = None
            
            current_start = start_ts
            total_windows = int((end_ts - start_ts) / step_ms)
            window_idx = 1
            
            while current_start + window_size_ms <= end_ts:
                current_end = current_start + window_size_ms
                window_data = [d for d in data if current_start <= d.get('timestamp', d.get('ts', 0)) <= current_end]
                
                if len(window_data) > 100:
                    print(f"   🎬 评估滑窗 {window_idx}/{total_windows}: {datetime.fromtimestamp(current_start/1000).strftime('%m-%d %H:%M')} ~ {datetime.fromtimestamp(current_end/1000).strftime('%m-%d %H:%M')}")
                    
                    window_config = [{'start_time': current_start, 'end_time': current_end}]
                    temp_result = run_model_selector(window_data, window_config, verbose=False, response_mode=response_mode)
                    
                    if temp_result.get('success'):
                        score = temp_result.get('model_rating', 0.0)
                        if score > best_score:
                            best_score = score
                            best_result = temp_result
                            best_window = window_config
                
                current_start += step_ms
                window_idx += 1
                
            step2_elapsed = time.time() - step2_start
            
            if best_result:
                print(f"✅ 滑窗搜索完毕！最优评分: {best_score:.2f}")
                result = best_result
                tuning_input = {'qualified_windows': best_window}
            else:
                print("⚠️ 所有滑窗均未能产出有效结果")
                continue
                
        else:
            print("\n🔍 启动自动探测模式 (Auto Detect)")
            step2_start = time.time()
            tuning_input = detect_tuning_windows(data)
            step2_elapsed = time.time() - step2_start
            
            qualified_windows = tuning_input.get('qualified_windows', [])
            if not qualified_windows:
                print("⚠️ 未检测到扰动段，无需整定，跳过")
                continue
            
            # 执行模型拟合
            step3_start = time.time()
            result = run_model_selector(data, qualified_windows, verbose=verbose, response_mode=response_mode)
            tuning_elapsed = time.time() - step3_start
        
        # Step 4: 打印 JSON 格式
        print_result_json(result)
        
        # Step 5: 可视化
        step5_start = time.time()
        scenario_name = start_time_str.replace(' ', '_').replace(':', '-')
        visualize_fitting_result(data, tuning_input, result, scenario_name, output_dir=CONFIG['log_dir'])
        
        # Step 5.1: 新参数仿真图
        if result.get('success'):
            visualize_new_pid_simulation(data, result, scenario_name, output_dir=CONFIG['log_dir'])
        
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
