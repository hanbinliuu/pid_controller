"""运行失败场景测试并保存结果到 results/unsuccess 文件夹"""
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
            change_time = metadata['change_time']
            end_time = data[-1]['timestamp']
            qualified_windows = [{'start_time': change_time, 'end_time': end_time}]
            
            input_data = {
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
            }
            
            process_changed = scenario['process_changed']
            sv = metadata['sv']
            T1_changed = process_changed.get('T1', 30)
            L_changed = process_changed.get('L', 5)
            sim_duration = max(400, int((T1_changed + L_changed) * 6))
            
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
            sim_result = simulate_with_new_pid(process_changed, pid_params, sv, duration=sim_duration, seed=sim_seed)
            
            tuning_success = result.get('success', False)
            is_stable = tuning_success and sim_result['is_stable']
            
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
    """保存失败场景的可视化结果"""
    output_dir = 'core/algorithm/model_type/tests/results/unsuccess'
    os.makedirs(output_dir, exist_ok=True)
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
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
        
        # 创建图表
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        
        # 子图1: PV响应
        ax1 = axes[0, 0]
        ax1.plot(sim_result['t'], sim_result['pv'], 'b-', label='PV', linewidth=1.5)
        ax1.plot(sim_result['t'], sim_result['sv'], 'r--', label='SV', linewidth=1.2)
        ax1.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5, label='±5% Band')
        ax1.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
        ax1.fill_between(sim_result['t'], sv * 0.95, sv * 1.05, alpha=0.1, color='green')
        ax1.set_xlabel('Time (s)')
        ax1.set_ylabel('PV')
        ax1.set_title(f'PV Response - {"整定失败" if not info["tuning_success"] else "仿真不稳定"}')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 子图2: MV响应
        ax2 = axes[0, 1]
        ax2.plot(sim_result['t'], sim_result['mv'], 'g-', label='MV', linewidth=1.5)
        ax2.set_xlabel('Time (s)')
        ax2.set_ylabel('MV')
        ax2.set_title('MV Response')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        # 子图3: 最后200点PV细节
        ax3 = axes[1, 0]
        last_n = min(200, len(sim_result['pv']))
        t_last = sim_result['t'][-last_n:]
        pv_last = sim_result['pv'][-last_n:]
        ax3.plot(t_last, pv_last, 'b-', label='PV (last 200)', linewidth=1.5)
        ax3.axhline(y=sv, color='r', linestyle='--', label='SV')
        ax3.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5)
        ax3.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
        ax3.fill_between(t_last, sv * 0.95, sv * 1.05, alpha=0.1, color='green')
        ax3.set_xlabel('Time (s)')
        ax3.set_ylabel('PV')
        ax3.set_title('Last 200 Points Detail')
        ax3.legend()
        ax3.grid(True, alpha=0.3)
        
        # 子图4: 场景信息
        ax4 = axes[1, 1]
        ax4.axis('off')
        
        info_text = f"""
场景 #{idx}: {scenario['name']}
回路类型: {info['loop_type']}
描述: {scenario.get('description', 'N/A')}

【过程参数(变化后)】
  K  = {process_changed['K']:.2f}
  T1 = {process_changed['T1']:.1f}s
  L  = {process_changed['L']:.1f}s

【整定结果】
  整定成功: {'是' if info['tuning_success'] else '否'}
  仿真稳定: {'是' if info['sim_stable'] else '否'}
  
【PID参数】
  Kp = {pid_params.get('kp', 'N/A')}
  Ki = {pid_params.get('ki', 'N/A')}
  Kd = {pid_params.get('kd', 'N/A')}
  PB = {pid_params.get('pb', 'N/A')}%

【仿真指标】
  调节时间: {sim_result['settling_time']:.0f}s
  超调量: {sim_result.get('overshoot', 0):.1f}%
  稳态误差: {sim_result.get('steady_error', 0):.2f}%
  振荡程度: {sim_result.get('oscillation', 0):.3f}
"""
        ax4.text(0.05, 0.95, info_text, transform=ax4.transAxes, fontsize=10,
                 verticalalignment='top', fontfamily='monospace',
                 bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
        
        fig.suptitle(f'失败场景 #{idx}: {scenario["name"]} ({info["loop_type"]})', 
                     fontsize=14, fontweight='bold')
        plt.tight_layout()
        
        # 保存
        filename = f'failed_{idx:02d}_{info["loop_type"]}_{scenario["name"].replace(" ", "_")[:20]}.png'
        filepath = os.path.join(output_dir, filename)
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"  保存: {filename}")
    
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
