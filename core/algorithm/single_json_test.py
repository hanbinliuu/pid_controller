import json
import os
import sys
from typing import Dict, List

import matplotlib.pyplot as plt
import numpy as np

from core.algorithm.detector import StabilityDetector

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def load_json(data_list: List[Dict]):
    """
    从JSON文件加载数据
    
    Returns:
        t: 相对时间数组（秒）
        t_original: 原始时间戳数组（毫秒或秒）
        pv: 过程值数组
        mv: 控制输出数组
        sv: 设定值数组
    """

    
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
    t_original = np.array(timestamps[:min_len])  # 原始时间戳
    pv = np.array(pv_list[:min_len])
    mv = np.array(mv_list[:min_len]) if mv_list else None
    sv = np.array(sv_list[:min_len]) if sv_list else None
    
    # 转换时间戳为相对时间（秒）
    t = t_original.copy()
    if t[0] > 1e10:  # 毫秒时间戳
        t = t / 1000.0
    t = t - t[0]  # 相对时间
    
    # 如果没有SV，使用PV的平均值
    if sv is None:
        sv = np.full_like(pv, np.mean(pv))
    
    return t, t_original, pv, mv, sv


def detect_and_visualize(json_file_path, output_path=None, tol=0.5, std_tol=0.2):
    """
    检测非稳态段并可视化
    
    Args:
        json_file_path: JSON文件路径
        output_path: 输出图片路径（如果为None，自动生成）
        tol: 容差
        std_tol: 标准差阈值
    
    Returns:
        dict: 包含检测结果的字典
            - non_steady_segments: 非稳态段列表（包含原始时间戳）
            - disturbance_starts: 扰动起始点列表（包含原始时间戳）
            - disturbance_ends: 扰动结束点列表（包含原始时间戳）
    """
    # 加载数据
    print(f"📂 加载数据: {os.path.basename(json_file_path)}")
    with open(json_file_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)

    if 'data' not in json_data:
        raise ValueError("JSON数据必须包含'data'字段")

    data_list = json_data['data']
    t, t_original, pv, mv, sv = load_json(data_list)
    print(f"✅ 数据加载成功: {len(t)} 个数据点")
    
    # 创建检测器
    detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=10)
    
    # 检测非稳态段
    print(f"\n🔍 检测非稳态段...")
    non_steady_segments = detector.detect_non_steady_segments(pv, sv, min_segment_len=20)
    print(f"📊 检测到 {len(non_steady_segments)} 个非稳态段")
    
    # 检测扰动起始点
    print(f"\n🔍 检测扰动起始点...")
    disturbance_starts = detector.detect_all_disturbances(pv, sv, non_steady_segments=non_steady_segments)
    print(f"📊 检测到 {len(disturbance_starts)} 个扰动起始点")
    
    # 提取扰动结束点（从非稳态段中提取）
    disturbance_ends = []
    for start_idx, end_idx, setpoint in non_steady_segments:
        # 结束点就是非稳态段的结束索引
        if end_idx < len(t_original):
            end_timestamp = t_original[end_idx]
        else:
            end_timestamp = t_original[-1]
        disturbance_ends.append((end_idx, end_timestamp, setpoint))
    
    # 将起始点和结束点转换为原始时间戳
    starts_with_timestamp = []
    for start_idx, setpoint in disturbance_starts:
        if start_idx < len(t_original):
            start_timestamp = t_original[start_idx]
        else:
            start_timestamp = t_original[0]
        starts_with_timestamp.append((start_idx, start_timestamp, setpoint))
    
    # 将非稳态段转换为原始时间戳
    segments_with_timestamp = []
    for start_idx, end_idx, setpoint in non_steady_segments:
        start_timestamp = t_original[start_idx] if start_idx < len(t_original) else t_original[0]
        end_timestamp = t_original[end_idx] if end_idx < len(t_original) else t_original[-1]
        segments_with_timestamp.append((start_idx, end_idx, start_timestamp, end_timestamp, setpoint))
    
    # 打印结果（使用原始时间戳）
    print(f"\n📋 检测结果（原始时间戳）:")
    for idx, (start_idx, end_idx, start_ts, end_ts, setpoint) in enumerate(segments_with_timestamp, 1):
        print(f"   非稳态段 {idx}:")
        print(f"     索引: [{start_idx}, {end_idx}]")
        print(f"     时间戳: [{start_ts:.0f}, {end_ts:.0f}]")
        print(f"     相对时间: [{t[start_idx]:.1f}s, {t[min(end_idx, len(t)-1)]:.1f}s]")
        print(f"     设定值: {setpoint:.2f}")
    
    for idx, (start_idx, start_ts, setpoint) in enumerate(starts_with_timestamp, 1):
        print(f"   扰动起始点 {idx}:")
        print(f"     索引: {start_idx}")
        print(f"     时间戳: {start_ts:.0f}")
        print(f"     相对时间: {t[start_idx]:.1f}s")
        print(f"     设定值: {setpoint:.2f}")
    
    for idx, (end_idx, end_ts, setpoint) in enumerate(disturbance_ends, 1):
        print(f"   扰动结束点 {idx}:")
        print(f"     索引: {end_idx}")
        print(f"     时间戳: {end_ts:.0f}")
        print(f"     相对时间: {t[min(end_idx, len(t)-1)]:.1f}s")
        print(f"     设定值: {setpoint:.2f}")
    
    # 可视化（使用相对时间）
    print(f"\n🎨 生成可视化...")
    plt.rcParams["font.family"] = ["Heiti TC"]
    plt.rcParams['font.sans-serif'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams['axes.unicode_minus'] = False
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('稳定性检测结果', fontsize=16, fontweight='bold')
    
    # PV和SV
    ax1 = axes[0]
    ax1.plot(t, pv, 'b-', linewidth=2, label='过程值PV', alpha=0.7)
    ax1.plot(t, sv, 'r--', linewidth=2.5, label='设定值SV', alpha=0.9)
    
    # 标注非稳态段
    for idx, (start_idx, end_idx, _, _, _) in enumerate(segments_with_timestamp):
        start_time = t[start_idx]
        end_time = t[min(end_idx, len(t)-1)]
        ax1.axvspan(start_time, end_time, alpha=0.2, color='red', 
                   label='非稳态段' if idx == 0 else None, zorder=0)
        ax1.text((start_time + end_time) / 2, ax1.get_ylim()[1] * 0.95,
                f'段{idx+1}\n{start_time:.1f}s-{end_time:.1f}s',
                ha='center', va='top', fontsize=9,
                bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))
    
    # 标注扰动起始点
    for idx, (start_idx, _, _) in enumerate(starts_with_timestamp):
        if start_idx < len(t):
            start_time = t[start_idx]
            ax1.axvline(start_time, color='orange', linestyle='--', linewidth=2, alpha=0.8)
            ax1.text(start_time, ax1.get_ylim()[1] * 0.85,
                    f'起始{idx+1}\n{start_time:.1f}s',
                    ha='center', va='top', fontsize=9,
                    bbox=dict(boxstyle='round', facecolor='orange', alpha=0.7))
    
    # 标注扰动结束点
    for idx, (end_idx, _, _) in enumerate(disturbance_ends):
        if end_idx < len(t):
            end_time = t[end_idx]
            ax1.axvline(end_time, color='green', linestyle='--', linewidth=2, alpha=0.8)
            ax1.text(end_time, ax1.get_ylim()[1] * 0.75,
                    f'结束{idx+1}\n{end_time:.1f}s',
                    ha='center', va='top', fontsize=9,
                    bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7))
    
    ax1.set_xlabel('时间 (s)', fontsize=12)
    ax1.set_ylabel('过程值 (PV)', fontsize=12)
    ax1.set_title('过程值对比：PV vs SV', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=10)
    
    # MV
    ax2 = axes[1]
    if mv is not None:
        ax2.plot(t, mv, 'g-', linewidth=2, label='控制输出MV', alpha=0.7)
        # 标注非稳态段和起始点、结束点
        for start_idx, end_idx, _, _, _ in segments_with_timestamp:
            ax2.axvspan(t[start_idx], t[min(end_idx, len(t)-1)], 
                       alpha=0.2, color='red', zorder=0)
        for start_idx, _, _ in starts_with_timestamp:
            if start_idx < len(t):
                ax2.axvline(t[start_idx], color='orange', linestyle='--', linewidth=2, alpha=0.8)
        for end_idx, _, _ in disturbance_ends:
            if end_idx < len(t):
                ax2.axvline(t[end_idx], color='green', linestyle='--', linewidth=2, alpha=0.8)
        ax2.legend(loc='best', fontsize=10)
    else:
        ax2.text(0.5, 0.5, '无MV数据', ha='center', va='center', 
                transform=ax2.transAxes, fontsize=14)
    
    ax2.set_xlabel('时间 (s)', fontsize=12)
    ax2.set_ylabel('控制输出 (MV)', fontsize=12)
    ax2.set_title('控制输出', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    if output_path is None:
        base_name = os.path.splitext(os.path.basename(json_file_path))[0]
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{base_name}_stability_detection.png")
    
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"✅ 图片已保存: {output_path}")
    
    return {
        'non_steady_segments': segments_with_timestamp,  # (start_idx, end_idx, start_timestamp, end_timestamp, setpoint)
        'disturbance_starts': starts_with_timestamp,      # (start_idx, start_timestamp, setpoint)
        'disturbance_ends': disturbance_ends              # (end_idx, end_timestamp, setpoint)
    }


if __name__ == "__main__":

    JSON_FILE_PATH = '/Users/dingzhenying/project/pythonProject/pid-agent-mvp/data/response_1762241923959.json'
    OUTPUT_PATH = None
    
    TOL = 0.5      # 容差
    STD_TOL = 0.2  # 标准差阈值

    result = detect_and_visualize(
        JSON_FILE_PATH, 
        OUTPUT_PATH,
        tol=TOL,
        std_tol=STD_TOL
    )

    print(f"   - 非稳态段数量: {len(result['non_steady_segments'])}")
    print(f"   - 扰动起始点数量: {len(result['disturbance_starts'])}")
    print(f"   - 扰动结束点数量: {len(result['disturbance_ends'])}")

    if result['disturbance_starts']:
        for idx, (start_idx, start_timestamp, setpoint) in enumerate(result['disturbance_starts'], 1):
            print(f"   起始点 {idx}: 索引={start_idx}, 时间戳={start_timestamp:.0f}, 设定值={setpoint:.2f}")
    
    if result['disturbance_ends']:
        for idx, (end_idx, end_timestamp, setpoint) in enumerate(result['disturbance_ends'], 1):
            print(f"   结束点 {idx}: 索引={end_idx}, 时间戳={end_timestamp:.0f}, 设定值={setpoint:.2f}")
