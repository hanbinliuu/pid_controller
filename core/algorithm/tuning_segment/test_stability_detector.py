import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from typing import List, Dict

from core.agent.tools import process_query_tsdb_data_interpolated
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from core.algorithm.tuning_segment.stability_detector import StabilityDetector, find_high_variability_periods
import pandas as pd


def get_history_data(start_time: int, end_time: int) -> List[Dict]:
    """获取历史数据"""
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
        print("未获取到历史数据")
        return []
    print(f"获取到历史数据：{len(history_data)} 条")
    return history_data


def convert_to_arrays(data: List[Dict]) -> tuple:
    """将数据转换为numpy数组"""
    pv_array = np.array([d.get('pv', 0.0) for d in data], dtype=np.float64)
    sv_array = np.array([d.get('sv', 0.0) for d in data], dtype=np.float64)
    mv_array = np.array([d.get('mv', 0.0) for d in data], dtype=np.float64)
    timestamps = np.array([d.get('timestamp', 0) for d in data], dtype=np.int64)
    return pv_array, sv_array, mv_array, timestamps


def test_stability_detector(data: List[Dict]):
    """测试 StabilityDetector，返回标准格式"""
    # 调用函数获取标准返回格式（新格式：直接传入 history_data）
    result = find_high_variability_periods({"history_data": data})
    
    # 打印标准返回格式
    print("\n" + "=" * 60)
    print("find_high_variability_periods 返回结果")
    print("=" * 60)
    print(f"start_time: {result['start_time']}")
    print(f"end_time: {result['end_time']}")
    print(f"qualified_windows: {result['qualified_windows']}")
    
    # 返回用于可视化的数据
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    detector = StabilityDetector()
    non_steady_segments = detector.detect_non_steady_segments(pv_array, sv_array)
    disturbance_starts = detector.detect_all_disturbances(pv_array, sv_array, non_steady_segments)
    sv_segments = detector.detect_setpoint_segments(sv_array, min_change=0.5, min_stable_points=20)
    sv_change_intervals = detector.detect_sv_change_intervals(sv_array, pv_data=pv_array)
    
    return {
        'sv_segments': sv_segments,
        'sv_change_intervals': sv_change_intervals,
        'non_steady_segments': non_steady_segments,
        'disturbance_starts': disturbance_starts
    }


def visualize_results(data: List[Dict], results: dict, scenario_name: str = None):
    """可视化检测结果
    
    Args:
        data: 历史数据
        results: 检测结果
        scenario_name: 场景名称，用于文件名
    """
    pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
    
    # 将时间戳转换为datetime
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    
    # 创建图表
    fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)
    fig.suptitle('StabilityDetector 检测结果可视化', fontsize=14, fontweight='bold')
    
    # ========== 子图1: PV和SV曲线 + 非稳态段 ==========
    ax1 = axes[0]
    ax1.plot(time_array, pv_array, 'b-', label='PV', linewidth=0.8, alpha=0.8)
    ax1.plot(time_array, sv_array, 'r--', label='SV', linewidth=1.2)
    
    # 标记非稳态段（用浅红色背景）
    non_steady_segments = results.get('non_steady_segments', [])
    for i, (start, end, setpoint) in enumerate(non_steady_segments):
        start_time = time_array[start] if start < len(time_array) else time_array[-1]
        end_time = time_array[min(end, len(time_array)-1)]
        ax1.axvspan(start_time, end_time, alpha=0.3, color='red', 
                   label='非稳态段' if i == 0 else None)
    
    # 标记扰动起始和结束点（每个非稳态段的起止）
    non_steady_for_lines = results.get('non_steady_segments', [])
    for i, (start_idx, end_idx, setpoint) in enumerate(non_steady_for_lines):
        if start_idx < len(time_array):
            ax1.axvline(x=time_array[start_idx], color='green', linestyle='--', 
                       linewidth=1.5, alpha=0.8, label='扰动起始' if i == 0 else None)
        # 确保结束索引在有效范围内
        end_plot_idx = min(end_idx - 1, len(time_array) - 1)
        if end_plot_idx >= 0:
            ax1.axvline(x=time_array[end_plot_idx], color='orange', linestyle='--', 
                       linewidth=1.5, alpha=0.8, label='扰动结束' if i == 0 else None)
    
    ax1.set_ylabel('PV / SV')
    ax1.set_title('过程值(PV)与设定值(SV) - 非稳态段检测')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # ========== 子图2: MV曲线 + SV变化区间 ==========
    ax2 = axes[1]
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    
    # 标记SV变化区间（用浅蓝色背景）
    sv_change_intervals = results.get('sv_change_intervals', [])
    for i, (start, end) in enumerate(sv_change_intervals):
        start_time = time_array[start] if start < len(time_array) else time_array[-1]
        end_time = time_array[min(end, len(time_array)-1)]
        ax2.axvspan(start_time, end_time, alpha=0.3, color='blue', 
                   label='SV变化区间' if i == 0 else None)
    
    ax2.set_ylabel('MV')
    ax2.set_title('操作值(MV) - SV变化区间')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 设定值分段 ==========
    ax3 = axes[2]
    ax3.plot(time_array, sv_array, 'r-', label='SV', linewidth=1.2)
    
    # 用不同颜色标记每个设定值段
    sv_segments = results.get('sv_segments', [])
    colors = plt.cm.Set3(np.linspace(0, 1, max(len(sv_segments), 1)))
    for i, (start, end, setpoint) in enumerate(sv_segments):
        start_time = time_array[start] if start < len(time_array) else time_array[-1]
        end_time = time_array[min(end-1, len(time_array)-1)]
        ax3.axvspan(start_time, end_time, alpha=0.2, color=colors[i])
        # 在段中间标注设定值
        mid_idx = (start + min(end, len(time_array)-1)) // 2
        if mid_idx < len(time_array):
            ax3.annotate(f'SV={setpoint:.1f}', 
                        xy=(time_array[mid_idx], setpoint),
                        xytext=(0, 10), textcoords='offset points',
                        ha='center', fontsize=9, fontweight='bold')
    
    ax3.set_ylabel('SV')
    ax3.set_xlabel('时间')
    ax3.set_title('设定值分段')
    ax3.legend(loc='upper right')
    ax3.grid(True, alpha=0.3)
    
    # 格式化x轴时间
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    
    plt.tight_layout()
    
    # 生成文件名
    if scenario_name:
        filename = f'stability_detector_{scenario_name}.png'
    else:
        filename = 'stability_detector_result.png'
    
    filepath = f'/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test/{filename}'
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n图表已保存至: test/{filename}")
    plt.close()  # 关闭图表，避免内存泄漏


if __name__ == "__main__":


    test_scenarios = [
        # {'start_time': '2025-11-06 16:41:58', 'end_time': '2025-11-06 16:48:58'},
        # {'start_time': '2025-11-05 10:55:58', 'end_time': '2025-11-05 13:14:58'},
        # {'start_time': '2025-11-11 18:50:58', 'end_time': '2025-11-11 20:08:58'},
        # {'start_time': '2025-11-10 09:12:58', 'end_time': '2025-11-10 10:25:58'},
        # {'start_time': '2025-11-05 09:33:58', 'end_time': '2025-11-05 17:24:58'},
        # {'start_time': '2025-11-04 16:58:58', 'end_time': '2025-11-04 18:30:58'},
        # {'start_time': '2025-11-04 17:53:58', 'end_time': '2025-11-04 18:30:58'},
        # {'start_time': '2025-11-05 11:05:58', 'end_time': '2025-11-05 15:38:58'},
        # {'start_time': '2025-11-07 17:45:58', 'end_time': '2025-11-07 19:42:58'},
        # {'start_time': '2025-11-05 09:51:22', 'end_time': '2025-11-05 17:50:58'},
        # {'start_time': '2025-12-04 10:00:58', 'end_time': '2025-12-04 12:42:58'},
        {'start_time': '2025-12-07 05:00:58', 'end_time': '2025-12-07 12:42:58'},
    ]

    for idx, scenario in enumerate(test_scenarios, 1):
        start_time = scenario['start_time']
        end_time = scenario['end_time']

        start_ts = int(datetime.strptime(start_time, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_time, '%Y-%m-%d %H:%M:%S').timestamp() * 1000)

        print(f"\n{'='*60}")
        print(f"场景 {idx}: {start_time} ~ {end_time}")
        print(f"{'='*60}")

        # 获取历史数据
        data = get_history_data(start_ts, end_ts)

        if data:
            # 测试 StabilityDetector
            results = test_stability_detector(data)
            
            # 生成场景名称（使用日期时间）
            scenario_name = start_time.replace(' ', '_').replace(':', '-')
            
            # 可视化结果
            visualize_results(data, results, scenario_name)


    # # 设置时间范围（最近24小时）
    # end_time = datetime.now()
    # start_time = end_time - timedelta(days=1)
    
    # start_ts = int(start_time.timestamp() * 1000)
    # end_ts = int(end_time.timestamp() * 1000)
    
    # print(f"查询时间范围: {start_time} ~ {end_time}")
    
    # # 获取历史数据
    # data = get_history_data(start_ts, end_ts)
    
    # if data:
    #     print(f"\n数据示例（前3条）:")
    #     for i, row in enumerate(data[:3]):
    #         print(f"  {i+1}: {row}")
        
    #     # 测试 StabilityDetector
    #     results = test_stability_detector(data)
        
    #     # 可视化结果
    #     visualize_results(data, results)
