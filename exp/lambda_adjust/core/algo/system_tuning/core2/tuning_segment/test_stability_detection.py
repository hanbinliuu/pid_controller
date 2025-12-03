"""
稳定性检测测试

测试 find_high_variability_periods 函数和 StabilityDetector 类
保持与原detector.py相同的处理逻辑，只是输入输出格式改变
"""

import json
import os
import sys
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from stability_detector import (
    find_high_variability_periods,
    StabilityDetector,
    merge_adjacent_periods
)


def load_json_data(json_file_path):
    """
    从JSON文件加载数据，返回Pandas Series with datetime index
    
    Args:
        json_file_path: JSON文件路径
        
    Returns:
        pv_series: 过程值时间序列 (Pandas Series with datetime index)
        sv_series: 设定值时间序列 (Pandas Series with datetime index)
        mv_series: 控制输出时间序列 (Pandas Series with datetime index, 可能为None)
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    if 'data' not in json_data:
        raise ValueError("JSON数据必须包含'data'字段")
    
    data_list = json_data['data']
    
    # 提取数据
    timestamps, pv_list, mv_list, sv_list = [], [], [], []
    
    for item in data_list:
        if 'timestamp' in item:
            timestamps.append(item['timestamp'])
        if 'pv' in item:
            pv_list.append(item['pv'])
        if 'mv' in item:
            mv_list.append(item['mv'])
        if 'sv' in item:
            sv_list.append(item['sv'])
    
    # 确保数据长度一致
    min_len = min(len(timestamps), len(pv_list))
    timestamps = np.array(timestamps[:min_len])
    pv = np.array(pv_list[:min_len])
    mv = np.array(mv_list[:min_len]) if mv_list else None
    sv = np.array(sv_list[:min_len]) if sv_list else None
    
    # 转换时间戳为datetime
    if timestamps[0] > 1e10:  # 毫秒时间戳
        timestamps = timestamps / 1000.0
    
    # 创建datetime index
    datetime_index = pd.to_datetime(timestamps, unit='s')
    
    # 创建Series
    pv_series = pd.Series(pv, index=datetime_index, name='pv')
    sv_series = pd.Series(sv, index=datetime_index, name='sv') if sv is not None else None
    mv_series = pd.Series(mv, index=datetime_index, name='mv') if mv is not None else None
    
    return pv_series, sv_series, mv_series


def visualize_detection_result(pv_series, sv_series, mv_series, result, save_path=None):
    """
    可视化检测结果
    
    Args:
        pv_series: PV时间序列
        sv_series: SV时间序列
        mv_series: MV时间序列（可选）
        result: find_high_variability_periods的返回结果
        save_path: 保存路径（可选）
    """
    # 设置中文字体
    plt.rcParams["font.family"] = ["Heiti TC"]
    plt.rcParams['font.sans-serif'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('稳定性检测结果：高波动时间段检测', fontsize=16, fontweight='bold')
    
    # 子图1: PV和SV对比
    ax1 = axes[0]
    ax1.plot(pv_series.index, pv_series.values, 'b-', linewidth=2, label='过程值PV', alpha=0.7, zorder=1)
    if sv_series is not None:
        ax1.plot(sv_series.index, sv_series.values, 'r--', linewidth=2.5, label='设定值SV', alpha=0.9, zorder=2)
    
    # 标注高波动时间段
    table = result.get("table", [])
    for seg_idx, segment in enumerate(table):
        start_time = segment.get("start_time")
        end_time = segment.get("end_time")
        
        if start_time is not None and end_time is not None:
            # 添加背景色块
            ax1.axvspan(start_time, end_time, alpha=0.2, color='red', 
                       label='高波动时间段' if seg_idx == 0 else None, zorder=0)
            
            # 添加文本标注
            mid_time = start_time + (end_time - start_time) / 2
            y_pos = ax1.get_ylim()[1] * 0.95
            ax1.text(mid_time, y_pos, 
                    f'高波动段{seg_idx+1}\nstd={segment.get("std", 0):.2f}',
                    ha='center', va='top', fontsize=9, 
                    bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    ax1.set_xlabel('时间', fontsize=12)
    ax1.set_ylabel('过程值 (PV)', fontsize=12)
    ax1.set_title('过程值对比：PV vs SV（标注高波动时间段）', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=10)
    
    # 子图2: MV（如果有）
    ax2 = axes[1]
    if mv_series is not None:
        ax2.plot(mv_series.index, mv_series.values, 'g-', linewidth=2, label='控制输出MV', alpha=0.7)
        
        # 标注高波动时间段
        for segment in table:
            start_time = segment.get("start_time")
            end_time = segment.get("end_time")
            if start_time is not None and end_time is not None:
                ax2.axvspan(start_time, end_time, alpha=0.2, color='red', zorder=0)
    else:
        ax2.text(0.5, 0.5, '无MV数据', ha='center', va='center', 
                transform=ax2.transAxes, fontsize=14)
    
    ax2.set_xlabel('时间', fontsize=12)
    ax2.set_ylabel('控制输出 (MV)', fontsize=12)
    ax2.set_title('控制输出（标注高波动时间段）', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    if mv_series is not None:
        ax2.legend(loc='best', fontsize=10)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"✅ 图形已保存至: {save_path}")
    
    return fig


def process_single_file(json_file_path, output_dir=None, window_size=300, step_size=60, 
                       variability_threshold=0.8, verbose=True):
    """
    处理单个JSON文件：执行稳定性检测和可视化
    
    Args:
        json_file_path: JSON数据文件路径
        output_dir: 输出目录（用于保存图形）
        window_size: 窗口大小
        step_size: 步长
        variability_threshold: 波动性阈值
        verbose: 是否打印详细信息
        
    Returns:
        dict: 包含处理结果的字典，如果失败返回None
    """
    result_info = {
        'file': os.path.basename(json_file_path),
        'file_path': json_file_path,
        'success': False,
        'result': None,
        'output_path': None,
        'error': None
    }
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"处理文件: {result_info['file']}")
        print(f"{'='*80}")
    
    # 1. 加载数据
    if verbose:
        print(f"\n📂 加载数据...")
    try:
        pv_series, sv_series, mv_series = load_json_data(json_file_path)
        if verbose:
            print(f"✅ 数据加载成功: {len(pv_series)} 个数据点")
            print(f"   - 时间范围: {pv_series.index[0]} ~ {pv_series.index[-1]}")
            print(f"   - PV范围: [{pv_series.min():.2f}, {pv_series.max():.2f}]")
            if mv_series is not None:
                print(f"   - MV范围: [{mv_series.min():.2f}, {mv_series.max():.2f}]")
            if sv_series is not None:
                print(f"   - SV范围: [{sv_series.min():.2f}, {sv_series.max():.2f}]")
    except Exception as e:
        error_msg = f"数据加载失败: {e}"
        result_info['error'] = error_msg
        if verbose:
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
        return result_info
    
    # 2. 执行检测
    if verbose:
        print(f"\n🔍 开始检测非稳态段（使用原detector.py逻辑）...")
        print(f"   参数: tol=0.5, std_tol=0.2, min_len=10, min_segment_len=20")
    
    try:
        result = find_high_variability_periods(
            pv_series=pv_series,
            sv_series=sv_series,
            tol=0.5,
            std_tol=0.2,
            min_len=10,
            min_segment_len=20,
            analyst_column="pv"
        )
        result_info['result'] = result
        
        if verbose:
            table = result.get("table", [])
            print(f"📊 检测到 {len(table)} 个非稳态段:")
            for seg_idx, segment in enumerate(table):
                print(f"   时间段 {seg_idx + 1}: "
                      f"{segment.get('start_time')} ~ {segment.get('end_time')}, "
                      f"std={segment.get('std', 0):.2f}, "
                      f"setpoint={segment.get('setpoint', 0):.2f}")
            
            print(f"\n📈 统计信息:")
            print(f"   - 非稳态段数: {result.get('total_windows', 0)}")
            std_max = result.get('std_max_window')
            if std_max:
                print(f"   - 最大标准差窗口: std={std_max.get('std', 0):.2f}, "
                      f"时间={std_max.get('start_time')}")
            
            # 显示扰动起始点
            disturbance_starts = result.get('disturbance_starts', [])
            if disturbance_starts:
                print(f"\n📍 扰动起始点: {len(disturbance_starts)} 个")
                for dist_info in disturbance_starts:
                    print(f"   - 索引={dist_info.get('start_idx')}, "
                          f"时间={dist_info.get('start_time')}, "
                          f"设定值={dist_info.get('setpoint', 0):.2f}")
    except Exception as e:
        error_msg = f"检测失败: {e}"
        result_info['error'] = error_msg
        if verbose:
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
        return result_info
    
    # 3. 可视化
    if verbose:
        print(f"\n🎨 开始可视化...")
    save_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(json_file_path))[0]
        save_path = os.path.join(output_dir, f"{base_name}_stability_detection.png")
        result_info['output_path'] = save_path
    
    try:
        fig = visualize_detection_result(pv_series, sv_series, mv_series, result, 
                                        save_path=save_path)
        plt.close(fig)
        if verbose:
            print(f"✅ 可视化完成!")
            if save_path:
                print(f"   - 图片已保存: {save_path}")
        result_info['success'] = True
    except Exception as e:
        error_msg = f"可视化失败: {e}"
        result_info['error'] = error_msg
        if verbose:
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
        return result_info
    
    return result_info


def batch_process_folder(folder_path, output_dir=None, window_size=300, step_size=60,
                        variability_threshold=0.8, verbose=True):
    """
    批量处理文件夹中的所有JSON文件
    
    Args:
        folder_path: 包含JSON文件的文件夹路径
        output_dir: 输出目录（用于保存图形和汇总报告）
        window_size: 窗口大小
        step_size: 步长
        variability_threshold: 波动性阈值
        verbose: 是否打印详细信息
        
    Returns:
        list: 所有文件的处理结果列表
    """
    print("=" * 80)
    print("批量稳定性检测测试（简化版）")
    print("=" * 80)
    
    # 查找所有JSON文件
    if not os.path.isdir(folder_path):
        print(f"❌ 错误: 文件夹不存在: {folder_path}")
        return []
    
    json_files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    json_files.sort()
    
    if len(json_files) == 0:
        print(f"❌ 错误: 文件夹中没有找到JSON文件: {folder_path}")
        return []
    
    print(f"\n📁 找到 {len(json_files)} 个JSON文件:")
    for i, f in enumerate(json_files, 1):
        print(f"   {i}. {f}")
    
    # 创建输出目录
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    
    # 批量处理
    results = []
    success_count = 0
    fail_count = 0
    
    print(f"\n{'='*80}")
    print(f"开始批量处理...")
    print(f"{'='*80}")
    
    for idx, json_file in enumerate(json_files, 1):
        json_path = os.path.join(folder_path, json_file)
        print(f"\n[{idx}/{len(json_files)}] 处理: {json_file}")
        
        result = process_single_file(
            json_path, 
            output_dir=output_dir, 
            window_size=window_size,
            step_size=step_size,
            variability_threshold=variability_threshold,
            verbose=verbose
        )
        results.append(result)
        
        if result['success']:
            success_count += 1
            if not verbose:
                table = result.get('result', {}).get('table', [])
                print(f"   ✅ 成功: 检测到 {len(table)} 个高波动时间段")
        else:
            fail_count += 1
            if not verbose:
                print(f"   ❌ 失败: {result['error']}")
    
    # 生成汇总报告
    print(f"\n{'='*80}")
    print(f"批量处理完成")
    print(f"{'='*80}")
    print(f"✅ 成功: {success_count} 个文件")
    print(f"❌ 失败: {fail_count} 个文件")
    print(f"📊 总计: {len(json_files)} 个文件")
    
    # 保存汇总报告
    summary_path = os.path.join(output_dir, "batch_summary.txt")
    try:
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("批量稳定性检测汇总报告（简化版）\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"输入文件夹: {folder_path}\n")
            f.write(f"输出文件夹: {output_dir}\n")
            f.write(f"参数: window_size={window_size}, step_size={step_size}, "
                   f"variability_threshold={variability_threshold}\n\n")
            f.write(f"总计: {len(json_files)} 个文件\n")
            f.write(f"成功: {success_count} 个文件\n")
            f.write(f"失败: {fail_count} 个文件\n\n")
            f.write("-" * 80 + "\n")
            f.write("详细结果:\n")
            f.write("-" * 80 + "\n\n")
            
            for result in results:
                f.write(f"文件: {result['file']}\n")
                if result['success']:
                    f.write(f"  状态: ✅ 成功\n")
                    table = result.get('result', {}).get('table', [])
                    f.write(f"  高波动时间段数量: {len(table)}\n")
                    if result['output_path']:
                        f.write(f"  输出文件: {os.path.basename(result['output_path'])}\n")
                else:
                    f.write(f"  状态: ❌ 失败\n")
                    f.write(f"  错误: {result['error']}\n")
                f.write("\n")
        
        print(f"\n📄 汇总报告已保存: {summary_path}")
    except Exception as e:
        print(f"⚠️  保存汇总报告失败: {e}")
    
    return results


def test_with_synthetic_data():
    """使用合成数据测试"""
    print("=" * 80)
    print("使用合成数据测试 StabilityDetector")
    print("=" * 80)
    
    # 创建合成数据
    np.random.seed(42)
    n_points = 5000
    
    # 创建时间索引
    start_time = datetime(2024, 1, 1, 0, 0, 0)
    time_index = pd.date_range(start=start_time, periods=n_points, freq='1s')
    
    # 创建PV数据：包含稳态和高波动段
    pv = np.zeros(n_points)
    setpoint = 50.0
    
    # 稳态段1 (0-1000): 低波动
    pv[0:1000] = setpoint + np.random.normal(0, 0.5, 1000)
    
    # 高波动段1 (1000-1500): 大幅振荡
    pv[1000:1500] = setpoint + 10 * np.sin(np.linspace(0, 10*np.pi, 500)) + np.random.normal(0, 2, 500)
    
    # 稳态段2 (1500-2500): 低波动
    pv[1500:2500] = setpoint + np.random.normal(0, 0.3, 1000)
    
    # 高波动段2 (2500-3000): 阶跃扰动
    pv[2500:3000] = setpoint + 15 + np.random.normal(0, 3, 500)
    
    # 稳态段3 (3000-4000): 低波动
    pv[3000:4000] = setpoint + np.random.normal(0, 0.4, 1000)
    
    # 高波动段3 (4000-4500): 快速变化
    pv[4000:4500] = setpoint + np.linspace(0, 20, 500) + np.random.normal(0, 2, 500)
    
    # 稳态段4 (4500-5000): 低波动
    pv[4500:5000] = setpoint + 20 + np.random.normal(0, 0.5, 500)
    
    # 创建Series
    pv_series = pd.Series(pv, index=time_index, name='pv')
    sv_series = pd.Series(np.full(n_points, setpoint), index=time_index, name='sv')
    
    print(f"\n📊 合成数据信息:")
    print(f"   - 数据点数: {n_points}")
    print(f"   - 时间范围: {time_index[0]} ~ {time_index[-1]}")
    print(f"   - 设定值: {setpoint}")
    print(f"   - 预期高波动段: 3个 (1000-1500, 2500-3000, 4000-4500)")
    
    # 使用函数接口测试
    print(f"\n🔍 使用 find_high_variability_periods 函数进行检测...")
    result = find_high_variability_periods(
        pv_series=pv_series,
        sv_series=sv_series,
        tol=0.5,
        std_tol=0.2,
        min_len=10,
        min_segment_len=20
    )
    
    print(f"\n📈 检测结果:")
    print(f"   - 非稳态段数: {result.get('total_windows', 0)}")
    
    table = result.get("table", [])
    for seg_idx, segment in enumerate(table):
        print(f"\n   非稳态段 {seg_idx + 1}:")
        print(f"      - 时间: {segment.get('start_time')} ~ {segment.get('end_time')}")
        print(f"      - 索引: {segment.get('start_idx')} ~ {segment.get('end_idx')}")
        print(f"      - 标准差: {segment.get('std', 0):.2f}")
        print(f"      - 设定值: {segment.get('setpoint', 0):.2f}")
    
    # 显示扰动起始点
    disturbance_starts = result.get('disturbance_starts', [])
    if disturbance_starts:
        print(f"\n📍 扰动起始点: {len(disturbance_starts)} 个")
        for dist_info in disturbance_starts:
            print(f"   - 索引={dist_info.get('start_idx')}, "
                  f"时间={dist_info.get('start_time')}")
    
    # 合并相邻段
    merged = merge_adjacent_periods(table, max_gap=100)
    print(f"\n🔗 合并后的时间段数: {len(merged)}")
    
    # 可视化
    print(f"\n🎨 生成可视化...")
    output_dir = os.path.join(current_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    save_path = os.path.join(output_dir, "synthetic_data_test.png")
    
    fig = visualize_detection_result(pv_series, sv_series, None, result, save_path=save_path)
    plt.close(fig)
    
    print(f"\n✅ 测试完成!")
    return result


def main(input_path=None, output_dir=None, window_size=300, step_size=60, 
         variability_threshold=0.8):
    """
    主函数
    
    Args:
        input_path: 输入路径（文件或文件夹），如果为None则使用合成数据测试
        output_dir: 输出目录
        window_size: 窗口大小
        step_size: 步长
        variability_threshold: 波动性阈值
    """
    if input_path is None:
        # 使用合成数据测试
        return test_with_synthetic_data()
    elif os.path.isdir(input_path):
        # 批量处理模式
        return batch_process_folder(
            input_path, 
            output_dir=output_dir,
            window_size=window_size,
            step_size=step_size,
            variability_threshold=variability_threshold,
            verbose=True
        )
    else:
        # 单文件处理模式
        result = process_single_file(
            input_path, 
            output_dir=output_dir,
            window_size=window_size,
            step_size=step_size,
            variability_threshold=variability_threshold,
            verbose=True
        )
        return result


if __name__ == "__main__":
    # 默认使用真实数据测试
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(BASE_DIR, "output")
    
    # 真实数据路径
    real_data_folder = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/data_simulation/zhongkong'
    
    if os.path.exists(real_data_folder):
        # 使用真实数据测试
        print("=" * 80)
        print("使用真实数据测试 StabilityDetector")
        print("=" * 80)
        main(real_data_folder, output_dir=output_dir)
    else:
        # 如果没有真实数据，使用合成数据测试
        print("=" * 80)
        print("未找到真实数据，使用合成数据测试")
        print("=" * 80)
        result = main(output_dir=output_dir)
