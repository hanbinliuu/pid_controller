"""
测试整定段选取模块 - 带可视化
支持合成数据和真实模拟数据
"""
import numpy as np
import pandas as pd
import sys
import os
import json
import glob
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

# 添加当前目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tuning_segment_selector import TuningSegmentSelector, find_high_variability_periods

# 真实数据目录
# 路径: exp/lambda_adjust/data_simulation/zhongkong
_current_dir = os.path.dirname(os.path.abspath(__file__))  # tuning_segment
_core2_dir = os.path.dirname(_current_dir)  # core2
_system_tuning_dir = os.path.dirname(_core2_dir)  # system_tuning
_algo_dir = os.path.dirname(_system_tuning_dir)  # algo
_core_dir = os.path.dirname(_algo_dir)  # core
_lambda_adjust_dir = os.path.dirname(_core_dir)  # lambda_adjust
DATA_DIR = os.path.join(_lambda_adjust_dir, "data_simulation", "zhongkong")


def generate_test_data():
    """生成测试数据，模拟不同CASE场景"""
    np.random.seed(42)
    
    # 场景1: CASE_3 - 前段稳态，后段出现扰动
    print("\n" + "="*60)
    print("场景1: CASE_3 - 前段稳态，后段扰动")
    print("="*60)
    
    n = 500
    t = np.arange(n)
    setpoint = 5.0
    
    # 前200点稳态
    pv1 = setpoint + np.random.normal(0, 0.1, 200)
    # 后300点有扰动
    pv2 = setpoint + np.sin(np.linspace(0, 4*np.pi, 300)) * 2 + np.random.normal(0, 0.2, 300)
    pv = np.concatenate([pv1, pv2])
    
    sv = np.full(n, setpoint)
    
    # 创建带时间索引的Series
    time_index = pd.date_range('2024-01-01', periods=n, freq='1s')
    pv_series = pd.Series(pv, index=time_index)
    
    return t, pv, sv, setpoint, pv_series, "CASE_3"


def generate_case1_data():
    """生成CASE_1数据 - 冷启动"""
    print("\n" + "="*60)
    print("场景2: CASE_1 - 冷启动，全程非稳态")
    print("="*60)
    
    n = 300
    t = np.arange(n)
    setpoint = 10.0
    
    # 从0开始逐渐上升到设定值附近
    pv = 2 + (setpoint - 2) * (1 - np.exp(-t / 80)) + np.random.normal(0, 0.3, n)
    sv = np.full(n, setpoint)
    
    time_index = pd.date_range('2024-01-01', periods=n, freq='1s')
    pv_series = pd.Series(pv, index=time_index)
    
    return t, pv, sv, setpoint, pv_series, "CASE_1"


def generate_case2_data():
    """生成CASE_2数据 - SV变化"""
    print("\n" + "="*60)
    print("场景3: CASE_2 - SV变化")
    print("="*60)
    
    n = 400
    t = np.arange(n)
    
    # SV从5变到8
    sv = np.concatenate([np.full(150, 5.0), np.full(250, 8.0)])
    
    # PV跟随SV变化
    pv1 = 5.0 + np.random.normal(0, 0.1, 150)
    pv2 = 5.0 + (8.0 - 5.0) * (1 - np.exp(-np.arange(250) / 30)) + np.random.normal(0, 0.2, 250)
    pv = np.concatenate([pv1, pv2])
    
    setpoint = 8.0  # 最终设定值
    
    time_index = pd.date_range('2024-01-01', periods=n, freq='1s')
    pv_series = pd.Series(pv, index=time_index)
    
    return t, pv, sv, setpoint, pv_series, "CASE_2"


def test_selector(t, pv, sv, setpoint, pv_series, expected_case):
    """测试整定段选取器"""
    selector = TuningSegmentSelector(
        tol=0.5,
        std_tol=0.2,
        min_len=10,
        window_size=50,  # 使用较小的窗口以适应测试数据
        step_size=10,
        variability_threshold=0.7
    )
    
    # 测试select_tuning_segment主方法
    result = selector.select_tuning_segment(
        data=pv_series,
        setpoint=setpoint,
        sv_array=sv,
        t=t,
        analyst_column="pv",
        is_filter=False,
        use_variability_method=True
    )
    
    print(f"\n📊 分类结果: {result['case']} (期望: {expected_case})")
    print(f"   是否需要整定: {result['tuning_needed']}")
    print(f"   整定段索引: {result['segment_indices']}")
    print(f"   开始时间: {result['start_time']}")
    print(f"   结束时间: {result['end_time']}")
    print(f"   滑动窗口数: {result['total_windows']}")
    
    if result['std_max_window']:
        print(f"   最大std窗口: idx={result['std_max_window'].get('start_idx')}-{result['std_max_window'].get('end_idx')}, std={result['std_max_window'].get('std', 0):.4f}")
    
    if result['t_seg'] is not None:
        print(f"   整定段长度: {len(result['t_seg'])} 点")
    
    # 验证分类是否正确
    if result['case'] == expected_case:
        print(f"   ✅ 分类正确!")
    else:
        print(f"   ⚠️  分类可能不同（实际场景可能与预期不完全匹配）")
    
    return result


def visualize_result(t, pv, sv, setpoint, result, title, ax=None):
    """可视化整定段选取结果"""
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 5))
    
    # 绘制PV曲线
    ax.plot(t, pv, 'b-', linewidth=1, label='PV', alpha=0.8)
    
    # 绘制SV曲线
    ax.plot(t, sv, 'g--', linewidth=1.5, label='SV', alpha=0.8)
    
    # 绘制设定值水平线
    ax.axhline(y=setpoint, color='r', linestyle=':', linewidth=1, label=f'Setpoint={setpoint}', alpha=0.6)
    
    # 高亮整定段
    if result['segment_indices'] is not None:
        start_idx, end_idx = result['segment_indices']
        ax.axvspan(t[start_idx], t[end_idx], alpha=0.3, color='orange', label=f'Tuning Segment [{start_idx}:{end_idx}]')
        ax.axvline(x=t[start_idx], color='red', linestyle='-', linewidth=2, alpha=0.7)
    
    # 标注分类结果
    case = result['case']
    tuning_needed = result['tuning_needed']
    status = "✓ Need Tuning" if tuning_needed else "✗ No Tuning Needed"
    
    ax.set_title(f'{title}\nCase: {case} | {status}', fontsize=12)
    ax.set_xlabel('Time Index')
    ax.set_ylabel('Value')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)
    
    return ax


def visualize_variability(result, title, ax=None):
    """可视化滑动窗口方差分析结果"""
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 4))
    
    table = result['table']
    if table.empty:
        ax.text(0.5, 0.5, 'No variability data', ha='center', va='center', transform=ax.transAxes)
        return ax
    
    # 绘制std变化
    ax.bar(table['window_idx'], table['std'], color='steelblue', alpha=0.7, label='Window Std')
    
    # 高亮高波动窗口
    high_var = table[table['is_high_variability']]
    if not high_var.empty:
        ax.bar(high_var['window_idx'], high_var['std'], color='red', alpha=0.7, label='High Variability')
    
    # 标记最大std窗口
    if result['std_max_window'] is not None:
        max_idx = result['std_max_window'].get('window_idx', 0)
        max_std = result['std_max_window'].get('std', 0)
        ax.scatter([max_idx], [max_std], color='gold', s=200, marker='*', zorder=5, label=f'Max Std={max_std:.3f}')
    
    ax.set_title(f'{title} - Sliding Window Analysis', fontsize=11)
    ax.set_xlabel('Window Index')
    ax.set_ylabel('Standard Deviation')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.3)
    
    return ax


def load_real_data(json_file: str):
    """
    从JSON文件加载真实模拟数据
    
    Args:
        json_file: JSON文件路径
        
    Returns:
        tuple: (t, pv, sv, setpoint, pv_series, filename)
    """
    print(f"\n📂 加载数据: {os.path.basename(json_file)}")
    
    with open(json_file, 'r') as f:
        response = json.load(f)
    
    data = response.get('data', [])
    if not data:
        raise ValueError("数据为空")
    
    # 提取数据
    timestamps = [d['timestamp'] for d in data]
    pv_values = [d['pv'] for d in data]
    sv_values = [d['sv'] for d in data]
    
    # 转换为numpy数组
    t = np.arange(len(pv_values))
    pv = np.array(pv_values, dtype=float)
    sv = np.array(sv_values, dtype=float)
    
    # 使用最后的SV值作为setpoint（或者使用众数）
    setpoint = float(np.median(sv[-100:]) if len(sv) >= 100 else np.median(sv))
    
    # 创建带时间索引的Series
    time_index = pd.to_datetime(timestamps, unit='ms')
    pv_series = pd.Series(pv, index=time_index)
    
    filename = os.path.basename(json_file)
    
    print(f"   数据点数: {len(pv)}")
    print(f"   时间范围: {response.get('start_time', 'N/A')} ~ {response.get('end_time', 'N/A')}")
    print(f"   PV范围: [{pv.min():.2f}, {pv.max():.2f}]")
    print(f"   SV范围: [{sv.min():.2f}, {sv.max():.2f}]")
    print(f"   Setpoint: {setpoint:.2f}")
    
    return t, pv, sv, setpoint, pv_series, filename


def list_available_data():
    """列出可用的真实数据文件"""
    if not os.path.exists(DATA_DIR):
        print(f"⚠️  数据目录不存在: {DATA_DIR}")
        return []
    
    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    files.sort(key=os.path.getsize, reverse=True)  # 按文件大小排序
    
    print(f"\n📁 可用数据文件 ({DATA_DIR}):")
    for i, f in enumerate(files):
        size_kb = os.path.getsize(f) / 1024
        print(f"   [{i}] {os.path.basename(f)} ({size_kb:.1f} KB)")
    
    return files


def test_with_real_data(num_files: int = 3):
    """使用真实数据进行测试"""
    print("\n" + "="*60)
    print("  使用真实模拟数据测试")
    print("="*60)
    
    files = list_available_data()
    if not files:
        print("没有找到数据文件")
        return
    
    # 选择前几个文件进行测试
    test_files = files[:min(num_files, len(files))]
    
    # 创建图形
    n_files = len(test_files)
    fig, axes = plt.subplots(n_files, 2, figsize=(16, 4 * n_files))
    if n_files == 1:
        axes = axes.reshape(1, -1)
    
    results = []
    for i, json_file in enumerate(test_files):
        try:
            t, pv, sv, setpoint, pv_series, filename = load_real_data(json_file)
            result = test_selector(t, pv, sv, setpoint, pv_series, "UNKNOWN")
            results.append(result)
            
            # 可视化
            visualize_result(t, pv, sv, setpoint, result, 
                           f'Real Data: {filename}\nDetected: {result["case"]}', 
                           axes[i, 0])
            visualize_variability(result, filename[:20], axes[i, 1])
            
        except Exception as e:
            print(f"❌ 加载失败: {json_file}, 错误: {e}")
    
    plt.tight_layout()
    plt.savefig('real_data_visualization.png', dpi=150, bbox_inches='tight')
    print("\n📊 真实数据可视化结果已保存: real_data_visualization.png")
    plt.show()
    
    return results


def main(use_real_data: bool = False):
    print("\n" + "="*60)
    print("  整定段选取模块测试")
    print("="*60)
    
    if use_real_data:
        # 使用真实数据测试
        test_with_real_data(num_files=4)
    else:
        # 使用合成数据测试
        # 创建图形
        fig, axes = plt.subplots(3, 2, figsize=(16, 12))
        
        # 测试场景1: CASE_3
        t, pv, sv, setpoint, pv_series, expected = generate_test_data()
        result1 = test_selector(t, pv, sv, setpoint, pv_series, expected)
        visualize_result(t, pv, sv, setpoint, result1, f'Scenario 1: CASE_3 (Expected: {expected})', axes[0, 0])
        visualize_variability(result1, 'Scenario 1', axes[0, 1])
        
        # 测试场景2: CASE_1
        t, pv, sv, setpoint, pv_series, expected = generate_case1_data()
        result2 = test_selector(t, pv, sv, setpoint, pv_series, expected)
        visualize_result(t, pv, sv, setpoint, result2, f'Scenario 2: CASE_1 (Expected: {expected})', axes[1, 0])
        visualize_variability(result2, 'Scenario 2', axes[1, 1])
        
        # 测试场景3: CASE_2
        t, pv, sv, setpoint, pv_series, expected = generate_case2_data()
        result3 = test_selector(t, pv, sv, setpoint, pv_series, expected)
        visualize_result(t, pv, sv, setpoint, result3, f'Scenario 3: CASE_2 (Expected: {expected})', axes[2, 0])
        visualize_variability(result3, 'Scenario 3', axes[2, 1])
        
        plt.tight_layout()
        plt.savefig('tuning_segment_visualization.png', dpi=150, bbox_inches='tight')
        print("\n📊 可视化结果已保存: tuning_segment_visualization.png")
        plt.show()
    
    print("\n" + "="*60)
    print("  测试完成")
    print("="*60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='测试整定段选取模块')
    parser.add_argument('--real', '-r', action='store_true', help='使用真实模拟数据测试')
    parser.add_argument('--num', '-n', type=int, default=4, help='测试的数据文件数量')
    args = parser.parse_args()
    
    if args.real:
        test_with_real_data(num_files=args.num)
    else:
        main(use_real_data=False)
