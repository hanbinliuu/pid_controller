import json
import os
import sys
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np

# 添加路径
current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)  # tests目录
system_tuning_dir = os.path.dirname(tests_dir)  # system_tuning目录
sys.path.insert(0, system_tuning_dir)

from core.model.stability import StabilityDetector


def load_json_data(json_file_path):
    """
    从JSON文件加载数据
    
    Args:
        json_file_path: JSON文件路径
        
    Returns:
        t: 时间数组（秒）
        pv: 过程值数组
        mv: 控制输出数组
        sv: 设定值数组
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
    
    # 转换时间戳为相对时间（秒）
    if timestamps[0] > 1e10:  # 毫秒时间戳
        timestamps = timestamps / 1000.0
    t = timestamps - timestamps[0]
    
    # 如果没有SV，使用PV的平均值作为设定值
    if sv is None:
        sv = np.full_like(pv, np.mean(pv))
    
    return t, pv, mv, sv


def visualize_stability_detection(t, pv, sv, mv, non_steady_segments, disturbance_starts, save_path=None):
    """
    可视化稳定性检测结果
    
    Args:
        t: 时间数组
        pv: 过程值数组
        sv: 设定值数组
        mv: 控制输出数组（可选）
        non_steady_segments: 非稳态段列表 [(start_idx, end_idx, setpoint), ...]
        disturbance_starts: 扰动起始点列表 [(start_idx, setpoint), ...]
        save_path: 保存路径（可选）
    """
    # 设置中文字体
    plt.rcParams["font.family"] = ["Heiti TC"]
    plt.rcParams['font.sans-serif'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('稳定性检测结果：非稳态段（扰动）检测', fontsize=16, fontweight='bold')
    
    # 子图1: PV和SV对比
    ax1 = axes[0]
    ax1.plot(t, pv, 'b-', linewidth=2, label='过程值PV', alpha=0.7, zorder=1)
    ax1.plot(t, sv, 'r--', linewidth=2.5, label='设定值SV', alpha=0.9, zorder=2)
    
    # 标注非稳态段
    for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(non_steady_segments):
        start_time = t[start_idx] if start_idx < len(t) else t[0]
        end_time = t[end_idx] if end_idx < len(t) else t[-1]
        
        # 添加背景色块
        ax1.axvspan(start_time, end_time, alpha=0.2, color='red', 
                   label='非稳态段（扰动）' if seg_idx == 0 else None, zorder=0)
        
        # 添加文本标注
        mid_time = (start_time + end_time) / 2
        ax1.text(mid_time, ax1.get_ylim()[1] * 0.95, 
                f'扰动段{seg_idx+1}\n{start_time:.1f}s - {end_time:.1f}s',
                ha='center', va='top', fontsize=9, 
                bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    # 标注扰动起始点
    for dist_idx, (start_idx, setpoint) in enumerate(disturbance_starts):
        if start_idx < len(t):
            start_time = t[start_idx]
            # 添加垂直线
            ax1.axvline(start_time, color='orange', linestyle='--', linewidth=2, alpha=0.8)
            # 添加文本标注
            ax1.text(start_time, ax1.get_ylim()[1] * 0.85,
                    f'扰动起始{dist_idx+1}\n{start_time:.1f}s',
                    ha='center', va='top', fontsize=9,
                    bbox=dict(boxstyle='round', facecolor='orange', alpha=0.7))
    
    ax1.set_xlabel('时间 (s)', fontsize=12)
    ax1.set_ylabel('过程值 (PV)', fontsize=12)
    ax1.set_title('过程值对比：PV vs SV（标注非稳态段和扰动起始点）', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=10)
    
    # 子图2: MV（如果有）
    ax2 = axes[1]
    if mv is not None:
        ax2.plot(t, mv, 'g-', linewidth=2, label='控制输出MV', alpha=0.7)
        
        # 标注非稳态段
        for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(non_steady_segments):
            start_time = t[start_idx] if start_idx < len(t) else t[0]
            end_time = t[end_idx] if end_idx < len(t) else t[-1]
            ax2.axvspan(start_time, end_time, alpha=0.2, color='red', zorder=0)
        
        # 标注扰动起始点
        for dist_idx, (start_idx, setpoint) in enumerate(disturbance_starts):
            if start_idx < len(t):
                start_time = t[start_idx]
                ax2.axvline(start_time, color='orange', linestyle='--', linewidth=2, alpha=0.8)
    else:
        ax2.text(0.5, 0.5, '无MV数据', ha='center', va='center', 
                transform=ax2.transAxes, fontsize=14)
    
    ax2.set_xlabel('时间 (s)', fontsize=12)
    ax2.set_ylabel('控制输出 (MV)', fontsize=12)
    ax2.set_title('控制输出（标注非稳态段和扰动起始点）', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    if mv is not None:
        ax2.legend(loc='best', fontsize=10)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"✅ 图形已保存至: {save_path}")
    
    return fig


def process_single_file(json_file_path, output_dir=None, tol=0.5, std_tol=0.2, verbose=True):
    """
    处理单个JSON文件：执行稳定性检测和可视化
    
    Args:
        json_file_path: JSON数据文件路径
        output_dir: 输出目录（用于保存图形）
        tol: 容差
        std_tol: 标准差阈值
        verbose: 是否打印详细信息
        
    Returns:
        dict: 包含处理结果的字典，如果失败返回None
    """
    result = {
        'file': os.path.basename(json_file_path),
        'file_path': json_file_path,
        'success': False,
        'non_steady_segments': [],
        'disturbance_starts': [],
        'output_path': None,
        'error': None
    }
    
    if verbose:
        print(f"\n{'='*80}")
        print(f"处理文件: {result['file']}")
        print(f"{'='*80}")
    
    # 1. 加载数据
    if verbose:
        print(f"\n📂 加载数据...")
    try:
        t, pv, mv, sv = load_json_data(json_file_path)
        if verbose:
            print(f"✅ 数据加载成功: {len(t)} 个数据点")
            print(f"   - 时间范围: {t[0]:.1f}s ~ {t[-1]:.1f}s")
            print(f"   - PV范围: [{np.min(pv):.2f}, {np.max(pv):.2f}]")
            if mv is not None:
                print(f"   - MV范围: [{np.min(mv):.2f}, {np.max(mv):.2f}]")
            print(f"   - SV范围: [{np.min(sv):.2f}, {np.max(sv):.2f}]")
    except Exception as e:
        error_msg = f"数据加载失败: {e}"
        result['error'] = error_msg
        if verbose:
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
        return result
    
    # 2. 创建稳定性检测器
    detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=10)
    
    # 3. 检测非稳态段（扰动段）
    if verbose:
        print(f"\n🔍 开始检测非稳态段（扰动）...")
        # 检测SV变化区间（用于调试）
        sv_change_intervals = detector.detect_sv_change_intervals(sv, threshold=0.1, min_stable_points=10)
        if len(sv_change_intervals) > 0:
            print(f"📌 检测到 {len(sv_change_intervals)} 个SV变化区间（将被排除）:")
            for change_idx, (change_start, change_end) in enumerate(sv_change_intervals):
                start_time = t[change_start] if change_start < len(t) else t[0]
                end_time = t[change_end] if change_end < len(t) else t[-1]
                print(f"   SV变化区间 {change_idx + 1}: 索引 [{change_start}, {change_end}], "
                      f"时间 [{start_time:.1f}s, {end_time:.1f}s]")
    
    non_steady_segments = detector.detect_non_steady_segments(pv, sv, min_segment_len=20)
    result['non_steady_segments'] = non_steady_segments
    if verbose:
        print(f"📊 检测到 {len(non_steady_segments)} 个非稳态段（扰动段）:")
        for seg_idx, (start_idx, end_idx, setpoint) in enumerate(non_steady_segments):
            start_time = t[start_idx] if start_idx < len(t) else t[0]
            end_time = t[end_idx] if end_idx < len(t) else t[-1]
            print(f"   扰动段 {seg_idx + 1}: 索引 [{start_idx}, {end_idx}], "
                  f"时间 [{start_time:.1f}s, {end_time:.1f}s], 设定值: {setpoint:.2f}")
    
    # 4. 检测扰动起始点（传入已检测到的非稳态段，以便更好地提取扰动起始点）
    if verbose:
        print(f"\n🔍 开始检测扰动起始点...")
    disturbance_starts = detector.detect_all_disturbances(pv, sv, non_steady_segments=non_steady_segments)
    result['disturbance_starts'] = disturbance_starts
    if verbose:
        print(f"📊 检测到 {len(disturbance_starts)} 个扰动起始点:")
        for dist_idx, (start_idx, setpoint) in enumerate(disturbance_starts):
            start_time = t[start_idx] if start_idx < len(t) else t[0]
            print(f"   扰动起始点 {dist_idx + 1}: 索引 {start_idx}, "
                  f"时间 {start_time:.1f}s, 设定值: {setpoint:.2f}")
    
    # 5. 可视化
    if verbose:
        print(f"\n🎨 开始可视化...")
    save_path = None
    if output_dir is not None:
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(json_file_path))[0]
        save_path = os.path.join(output_dir, f"{base_name}_stability_detection.png")
        result['output_path'] = save_path
    
    try:
        fig = visualize_stability_detection(t, pv, sv, mv, non_steady_segments, 
                                           disturbance_starts, save_path=save_path)
        plt.close(fig)  # 关闭图形以释放内存
        if verbose:
            print(f"✅ 可视化完成!")
            if save_path:
                print(f"   - 图片已保存: {save_path}")
        result['success'] = True
    except Exception as e:
        error_msg = f"可视化失败: {e}"
        result['error'] = error_msg
        if verbose:
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
        return result
    
    return result


def batch_process_folder(folder_path, output_dir=None, tol=0.5, std_tol=0.2, verbose=True):
    """
    批量处理文件夹中的所有JSON文件
    
    Args:
        folder_path: 包含JSON文件的文件夹路径
        output_dir: 输出目录（用于保存图形和汇总报告）
        tol: 容差
        std_tol: 标准差阈值
        verbose: 是否打印详细信息
        
    Returns:
        list: 所有文件的处理结果列表
    """
    print("=" * 80)
    print("批量稳定性检测测试")
    print("=" * 80)
    
    # 查找所有JSON文件
    if not os.path.isdir(folder_path):
        print(f"❌ 错误: 文件夹不存在: {folder_path}")
        return []
    
    json_files = [f for f in os.listdir(folder_path) if f.endswith('.json')]
    json_files.sort()  # 按文件名排序
    
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
        
        result = process_single_file(json_path, output_dir=output_dir, 
                                    tol=tol, std_tol=std_tol, verbose=verbose)
        results.append(result)
        
        if result['success']:
            success_count += 1
            if not verbose:
                print(f"   ✅ 成功: 检测到 {len(result['non_steady_segments'])} 个非稳态段, "
                      f"{len(result['disturbance_starts'])} 个扰动起始点")
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
            f.write("批量稳定性检测汇总报告\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"输入文件夹: {folder_path}\n")
            f.write(f"输出文件夹: {output_dir}\n")
            f.write(f"参数: tol={tol}, std_tol={std_tol}\n\n")
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
                    f.write(f"  非稳态段数量: {len(result['non_steady_segments'])}\n")
                    f.write(f"  扰动起始点数量: {len(result['disturbance_starts'])}\n")
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


def main(json_file_path, output_dir=None, tol=0.5, std_tol=0.2):
    """
    主函数：执行稳定性检测和可视化（单文件模式，保持向后兼容）
    
    Args:
        json_file_path: JSON数据文件路径或文件夹路径
        output_dir: 输出目录（用于保存图形）
        tol: 容差
        std_tol: 标准差阈值
    """
    # 判断是文件还是文件夹
    if os.path.isdir(json_file_path):
        # 批量处理模式
        batch_process_folder(json_file_path, output_dir=output_dir, 
                           tol=tol, std_tol=std_tol, verbose=True)
    else:
        # 单文件处理模式
        result = process_single_file(json_file_path, output_dir=output_dir, 
                                   tol=tol, std_tol=std_tol, verbose=True)
        if result['success']:
            return result['non_steady_segments'], result['disturbance_starts']
        else:
            return None, None


if __name__ == "__main__":
    # 测试数据路径
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    default_folder = '/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/data_simulation/zhongkong'
    output_dir = os.path.join(BASE_DIR, "output")
    main(default_folder, output_dir=output_dir, tol=0.5, std_tol=0.2)

