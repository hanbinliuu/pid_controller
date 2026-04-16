"""运行失败场景测试并保存结果到 results/unsuccess 文件夹

与 test_synthetic_tuning.py 使用完全相同的管线：
  - 使用 find_high_variability_periods 自动选段
  - 传入 current_pid 以支持 fallback 整定
  - 使用回路类型特定的误差带和收敛放松
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime

from core.algorithm.model_type.tests.test_scenarios import TEST_SCENARIOS
from core.algorithm.model_type.model_selector import ModelSelector
from core.algorithm.model_type.config import Config
from core.algorithm.model_type.tests.test_synthetic_tuning import generate_scenario_data, simulate_with_new_pid
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods


def run_and_collect_failed():
    """运行所有场景，收集失败案例"""
    failed_scenarios = []
    all_results = []
    np.random.seed(25)
    
    print(f"总场景数: {len(TEST_SCENARIOS)}")
    print("=" * 60)
    
    for idx, scenario in enumerate(TEST_SCENARIOS, 1):
        scenario_seed = idx * 1000
        np.random.seed(scenario_seed)
        
        try:
            data, metadata = generate_scenario_data(scenario, seed=scenario_seed)
            
            # 使用三级优选引擎自动检测整定段/振荡段/扰动段 (与 test_synthetic_tuning.py 一致)
            detect_res = find_high_variability_periods({"history_data": data})
            qualified_windows = detect_res.get("qualified_windows", [])
            
            # 如果自动检测没找到任何段，退化到手动指定
            if not qualified_windows:
                change_time = metadata['change_time']
                end_time = data[-1]['timestamp']
                qualified_windows = [{'start_time': change_time, 'end_time': end_time}]
            
            input_data = {
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
                'current_pid': scenario['original_pid'],
            }
            
            process_changed = scenario['process_changed']
            sv = metadata['sv']
            T1_changed = process_changed.get('T1', 30)
            L_changed = process_changed.get('L', 5)
            loop_type = scenario.get('loop_type', 'flow')
            
            # 【优化】根据回路类型使用不同的仿真时长乘数 (匹配 test_synthetic_tuning.py)
            if loop_type == 'level':
                sim_factor = 40.0
                min_duration = 3000
            elif loop_type == 'temperature':
                sim_factor = 30.0
                min_duration = 3000
            else:
                sim_factor = 15.0
                min_duration = 1200
            
            # 极慢系统(T1>100s)特殊处理
            if T1_changed > 100:
                sim_factor = max(sim_factor, 12.0)
                min_duration = max(min_duration, 1200)
            
            sim_duration = max(min_duration, int((T1_changed + L_changed) * sim_factor))
            
            np.random.seed(scenario_seed + 100)
            Config.OSCILLATION_TUNING['enable_llm'] = False
            loop_type = scenario.get('loop_type', 'flow')
            selector = ModelSelector(
                verbose=False,
                process_context={'loop_type': loop_type, 'loop_name': scenario['name']}
            )
            result = selector.run(input_data)
            pid_params = result.get('pid_parameters', {})
            
            sim_seed = scenario_seed + 300
            # 慢回路使用更宽松的误差带（石化行业标准：液位/温度10%，流量/压力5%）
            err_band = 0.10 if loop_type in ('level', 'temperature') else 0.05
            sim_result = simulate_with_new_pid(process_changed, pid_params, sv, duration=sim_duration, seed=sim_seed, error_band_pct=err_band)
            
            tuning_success = result.get('success', False)
            rule_stable = tuning_success and sim_result['is_stable']
            
            # 收敛放松：保守整定可能未完全进入误差带，但正在收敛且稳态误差小
            if tuning_success and not sim_result['is_stable']:
                if sim_result.get('is_converging', False) and sim_result.get('steady_error', 100) < 10:
                    rule_stable = True
            
            is_stable = rule_stable
            
            result_info = {
                'idx': idx,
                'name': scenario['name'],
                'loop_type': loop_type,
                'tuning_success': tuning_success,
                'sim_stable': sim_result['is_stable'],
                'is_stable': is_stable,
                'settling_time': sim_result['settling_time'],
                'pid_params': pid_params,
                'scenario': scenario,
                'sim_result': sim_result,
                'metadata': metadata,
                'data': data,
                'process_changed': process_changed,
                'sv': sv,
                'sim_duration': sim_duration,
            }
            all_results.append(result_info)
            
            status = "✅" if is_stable else "❌"
            if not tuning_success:
                detail = "整定失败"
            elif not sim_result['is_stable']:
                detail = f"仿真不稳定(Ts={sim_result['settling_time']:.0f}s)"
            else:
                detail = f"稳定(Ts={sim_result['settling_time']:.0f}s)"
            
            print(f"{status} 场景 {idx:2d}: {scenario['name'][:30]:<30} ({loop_type:<11}) - {detail}")
            
            if not is_stable:
                failed_scenarios.append(result_info)
                
        except Exception as e:
            print(f"❌ 场景 {idx:2d}: {scenario['name'][:30]:<30} - 错误: {e}")
            failed_scenarios.append({
                'idx': idx,
                'name': scenario['name'],
                'loop_type': scenario.get('loop_type', 'unknown'),
                'error': str(e),
            })
    
    return failed_scenarios, all_results


def save_failed_results(failed_scenarios):
    """保存失败场景的可视化结果（优化版）"""
    output_dir = 'core/algorithm/model_type/tests/results/unsuccess'
    os.makedirs(output_dir, exist_ok=True)
    
    # 优化配色方案
    COLORS = {
        'pv': '#2E86AB',      # 深蓝
        'sv': '#E94F37',      # 红
        'mv': '#44AF69',      # 绿
        'band': '#A7C957',    # 浅绿
        'grid': '#CCCCCC',
        'bg': '#FAFAFA',
    }
    
    # 使用 macOS 系统中文字体
    plt.rcParams['font.sans-serif'] = ['PingFang SC', 'Heiti SC', 'STHeiti', 'Microsoft YaHei', 'SimHei', 'Arial']
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['figure.facecolor'] = 'white'
    plt.rcParams['axes.facecolor'] = COLORS['bg']
    plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号
    plt.rcParams['axes.grid'] = True
    
    print(f"\n保存失败场景图表到: {output_dir}")
    print("=" * 60)
    
    for info in failed_scenarios:
        if 'error' in info:
            print(f"跳过场景 {info['idx']}: {info['name']} (有错误)")
            continue
        
        idx = info['idx']
        scenario = info['scenario']
        sim_result = info['sim_result']
        pid_params = info['pid_params']
        process_changed = info['process_changed']
        sv = info['sv']
        
        # 创建图表 - 简化为 1x2 布局
        fig = plt.figure(figsize=(14, 6))
        
        # 使用 GridSpec 创建布局
        gs = fig.add_gridspec(1, 2, wspace=0.25, width_ratios=[1.5, 1])
        
        # ===== 子图1: PV/SV/MV 合并图 =====
        ax1 = fig.add_subplot(gs[0, 0])
        ax1.plot(sim_result['t'], sim_result['pv'], color=COLORS['pv'], 
                 label='PV', linewidth=1.8, zorder=3)
        ax1.plot(sim_result['t'], sim_result['sv'], color=COLORS['sv'], 
                 linestyle='--', label='SV', linewidth=1.5, zorder=2)
        ax1.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.6)
        ax1.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.6)
        ax1.fill_between(sim_result['t'], sv * 0.95, sv * 1.05, 
                         alpha=0.15, color=COLORS['band'], label='±5%误差带')
        ax1.set_xlabel('时间 (s)', fontweight='bold')
        ax1.set_ylabel('PV / SV', fontweight='bold')
        status_text = '整定失败' if not info['tuning_success'] else '仿真不稳定'
        ax1.set_title(f'过程响应 - {status_text}', fontweight='bold', fontsize=12, color='#D32F2F')
        ax1.legend(loc='upper left', fontsize=9, framealpha=0.9)
        ax1.grid(True, alpha=0.4, color=COLORS['grid'])
        
        # 添加 MV 到右侧 Y 轴
        ax1_mv = ax1.twinx()
        ax1_mv.plot(sim_result['t'], sim_result['mv'], color=COLORS['mv'], 
                    label='MV', linewidth=1.2, alpha=0.7, zorder=1)
        ax1_mv.set_ylabel('MV (%)', fontweight='bold', color=COLORS['mv'])
        ax1_mv.tick_params(axis='y', labelcolor=COLORS['mv'])
        ax1_mv.legend(loc='upper right', fontsize=9, framealpha=0.9)
        
        # ===== 子图2: 参数信息卡片 =====
        ax2 = fig.add_subplot(gs[0, 1])
        ax2.axis('off')
        
        # 使用中文显示
        info_lines = [
            ("场景信息", None),
            ("─" * 35, None),
            (f"场景 #{idx}: {scenario['name']}", None),
            (f"回路类型: {info['loop_type']}", None),
            ("", None),
            ("过程参数 (变化后)", None),
            ("─" * 35, None),
            (f"  K  = {process_changed['K']:.3f}", None),
            (f"  T1 = {process_changed['T1']:.1f}s", None),
            (f"  L  = {process_changed['L']:.1f}s", None),
            ("", None),
            ("整定结果", None),
            ("─" * 35, None),
            (f"  整定成功: {'是' if info['tuning_success'] else '否'}", 
             '#4CAF50' if info['tuning_success'] else '#F44336'),
            (f"  仿真稳定: {'是' if info['sim_stable'] else '否'}", 
             '#4CAF50' if info['sim_stable'] else '#F44336'),
            ("", None),
            ("PID 参数", None),
            ("─" * 35, None),
            (f"  PB = {pid_params.get('pb', 'N/A')}%", None),
            (f"  Ti = {pid_params.get('ti', 'N/A')}s", None),
            (f"  Td = {pid_params.get('td', 'N/A')}s", None),
            ("", None),
            ("仿真指标", None),
            ("─" * 35, None),
            (f"  调节时间: {sim_result['settling_time']:.0f}s", None),
            (f"  超调量: {sim_result.get('overshoot', 0):.1f}%", None),
            (f"  稳态误差: {sim_result.get('steady_error', 0):.2f}%", None),
            (f"  振荡程度: {sim_result.get('oscillation', 0):.3f}", None),
        ]
        
        y_pos = 0.98
        for line, color in info_lines:
            if color:
                ax2.text(0.05, y_pos, line, transform=ax2.transAxes, fontsize=10,
                         verticalalignment='top',
                         color=color, fontweight='bold')
            else:
                ax2.text(0.05, y_pos, line, transform=ax2.transAxes, fontsize=10,
                         verticalalignment='top')
            y_pos -= 0.035
        
        # 主标题
        fig.suptitle(f'失败场景 #{idx}: {scenario["name"]} ({info["loop_type"]})', 
                     fontsize=14, fontweight='bold', color='#D32F2F')
        plt.tight_layout(rect=[0, 0, 1, 0.94])
        
        # 保存 - 使用固定文件名覆盖
        safe_name = scenario["name"].replace(" ", "_").replace("/", "_")[:25]
        filename = f'failed_{idx:03d}_{info["loop_type"]}_{safe_name}.png'
        filepath = os.path.join(output_dir, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
        plt.close()
        
        print(f"  已保存: {filename}")
    
    # 保存汇总文件
    summary_path = os.path.join(output_dir, 'summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"失败场景汇总 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"失败场景数: {len(failed_scenarios)}/80\n\n")
        
        # 按回路类型分组
        by_type = {}
        for info in failed_scenarios:
            lt = info.get('loop_type', 'unknown')
            if lt not in by_type:
                by_type[lt] = []
            by_type[lt].append(info)
        
        for lt, items in sorted(by_type.items()):
            f.write(f"\n【{lt}】({len(items)}个)\n")
            for info in items:
                if 'error' in info:
                    f.write(f"  场景 {info['idx']}: {info['name']} - 错误: {info['error']}\n")
                else:
                    status = "整定失败" if not info['tuning_success'] else f"仿真不稳定(Ts={info['settling_time']:.0f}s)"
                    f.write(f"  场景 {info['idx']}: {info['name']} - {status}\n")
    
    print(f"\n汇总文件: {summary_path}")


if __name__ == '__main__':
    print("=" * 60)
    print("运行失败场景测试")
    print("=" * 60)
    
    failed, all_results = run_and_collect_failed()
    
    print("\n" + "=" * 60)
    print(f"测试完成: 成功 {len(all_results) - len(failed)}/80, 失败 {len(failed)}/80")
    print("=" * 60)
    
    if failed:
        save_failed_results(failed)
        print("\n✅ 失败场景结果已保存到 results/unsuccess/")
    else:
        print("\n🎉 所有场景都通过了!")
