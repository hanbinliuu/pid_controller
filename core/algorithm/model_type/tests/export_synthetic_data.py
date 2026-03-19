#!/usr/bin/env python3
"""合成数据一键导出工具

将 test_scenarios.py 中定义的所有合成测试场景数据导出为
JSON 和 CSV 格式，方便外部使用（如大模型训练、数据分析等）。

使用方式:
    # 导出所有场景到默认目录
    python export_synthetic_data.py

    # 导出到指定目录
    python export_synthetic_data.py --output /path/to/output

    # 只导出振荡场景
    python export_synthetic_data.py --type oscillation

    # 只导出阶跃响应场景
    python export_synthetic_data.py --type step_response

    # 只导出前 10 个场景
    python export_synthetic_data.py --limit 10

    # 导出为 CSV（默认 JSON）
    python export_synthetic_data.py --format csv

    # 同时导出 JSON 和 CSV
    python export_synthetic_data.py --format both

输出目录结构:
    output/
    ├── index.json                           # 场景索引（所有场景清单）
    ├── oscillation/                         # 振荡场景
    │   ├── 001_Severe_Gain_Increase.json
    │   ├── 001_Severe_Gain_Increase.csv
    │   └── ...
    ├── step_response/                       # 阶跃响应场景
    │   ├── 001_Flow_Step_Response.json
    │   └── ...
    └── realistic/                           # 工业实际场景
        ├── 001_Flow_Valve_Stiction.json
        └── ...
"""

import sys
import os
import json
import csv
import argparse
from datetime import datetime

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_current_dir))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import numpy as np

# 导入场景定义
from core.algorithm.model_type.tests.test_scenarios import (
    TEST_SCENARIOS,
    REALISTIC_SCENARIOS,
)
# 导入数据生成函数和阶跃响应场景
from core.algorithm.model_type.tests.test_synthetic_tuning import (
    generate_scenario_data,
    generate_step_response_scenario_data,
    MODEL_ID_SCENARIOS,
)

# ============================================================
# 常量
# ============================================================

DEFAULT_OUTPUT_DIR = os.path.join(_current_dir, 'exported_data')


def safe_filename(name: str) -> str:
    """场景名 → 安全文件名"""
    return name.replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace('+', '_')


# ============================================================
# 导出函数
# ============================================================

def export_one_scenario_json(history_data, metadata, scenario, filepath):
    """导出单个场景为 JSON"""
    export_obj = {
        'scenario': {
            'name': scenario.get('name', ''),
            'description': scenario.get('description', ''),
            'loop_type': scenario.get('loop_type', 'flow'),
            'noise_std': scenario.get('noise_std', 0.2),
            'process_original': scenario.get('process_original', scenario.get('process', {})),
            'process_changed': scenario.get('process_changed', {}),
            'original_pid': scenario.get('original_pid', scenario.get('pid', {})),
        },
        'metadata': {k: v for k, v in metadata.items()
                     if not isinstance(v, (np.ndarray, np.integer, np.floating))},
        'data_points': len(history_data),
        'columns': ['timestamp', 'pv', 'sv', 'mv'],
        'history_data': history_data,
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(export_obj, f, ensure_ascii=False, indent=2, default=str)


def export_one_scenario_csv(history_data, scenario, filepath):
    """导出单个场景为 CSV"""
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        # 写入场景信息作为注释行
        f.write(f"# scenario: {scenario.get('name', '')}\n")
        f.write(f"# description: {scenario.get('description', '')}\n")
        f.write(f"# loop_type: {scenario.get('loop_type', 'flow')}\n")
        proc_orig = scenario.get('process_original', scenario.get('process', {}))
        proc_chg = scenario.get('process_changed', {})
        pid = scenario.get('original_pid', scenario.get('pid', {}))
        f.write(f"# process_original: K={proc_orig.get('K','')}, T1={proc_orig.get('T1','')}, L={proc_orig.get('L','')}\n")
        if proc_chg:
            f.write(f"# process_changed: K={proc_chg.get('K','')}, T1={proc_chg.get('T1','')}, L={proc_chg.get('L','')}\n")
        f.write(f"# original_pid: Kp={pid.get('Kp','')}, Ki={pid.get('Ki','')}, Kd={pid.get('Kd','')}\n")

        writer = csv.DictWriter(f, fieldnames=['timestamp', 'pv', 'sv', 'mv'])
        writer.writeheader()
        writer.writerows(history_data)


def export_scenarios(scenarios, scenario_type, generate_fn, output_dir, fmt, limit=None):
    """批量导出一类场景

    Args:
        scenarios: 场景列表
        scenario_type: 'oscillation' / 'step_response' / 'realistic'
        generate_fn: 数据生成函数 (scenario) -> (history_data, metadata)
        output_dir: 输出根目录
        fmt: 'json' / 'csv' / 'both'
        limit: 最大导出数量
    """
    subdir = os.path.join(output_dir, scenario_type)
    os.makedirs(subdir, exist_ok=True)

    total = min(len(scenarios), limit) if limit else len(scenarios)
    results = []
    errors = []

    for idx, scenario in enumerate(scenarios[:total], 1):
        name = scenario.get('name', f'scenario_{idx}')
        safe_name = safe_filename(name)
        prefix = f"{idx:03d}_{safe_name}"

        print(f"  [{idx:3d}/{total}] {name} ...", end=' ', flush=True)

        try:
            history_data, metadata = generate_fn(scenario)

            if fmt in ('json', 'both'):
                export_one_scenario_json(
                    history_data, metadata, scenario,
                    os.path.join(subdir, f"{prefix}.json")
                )
            if fmt in ('csv', 'both'):
                export_one_scenario_csv(
                    history_data, scenario,
                    os.path.join(subdir, f"{prefix}.csv")
                )

            results.append({
                'index': idx,
                'name': name,
                'type': scenario_type,
                'loop_type': scenario.get('loop_type', 'flow'),
                'data_points': len(history_data),
                'file': prefix,
            })
            print(f"✅ {len(history_data)} points")

        except Exception as e:
            errors.append({'index': idx, 'name': name, 'error': str(e)})
            print(f"❌ {e}")

    return results, errors


def generate_oscillation_wrapper(scenario):
    """振荡场景数据生成包装器"""
    seed = 42
    return generate_scenario_data(scenario, seed=seed)


def generate_step_response_wrapper(scenario):
    """阶跃响应场景数据生成包装器"""
    np.random.seed(42)
    return generate_step_response_scenario_data(scenario)


# ============================================================
# 主程序
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description='导出 PID 整定合成测试场景数据',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python export_synthetic_data.py                         # 导出全部 → ./exported_data/
  python export_synthetic_data.py --type oscillation      # 仅振荡场景
  python export_synthetic_data.py --format csv            # 仅 CSV
  python export_synthetic_data.py --format both --limit 5 # JSON+CSV, 每类前5个
        """
    )
    parser.add_argument('--output', '-o', default=DEFAULT_OUTPUT_DIR,
                        help=f'输出目录 (默认: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('--type', '-t', choices=['oscillation', 'step_response', 'realistic', 'all'],
                        default='all', help='场景类型 (默认: all)')
    parser.add_argument('--format', '-f', choices=['json', 'csv', 'both'],
                        default='json', help='输出格式 (默认: json)')
    parser.add_argument('--limit', '-n', type=int, default=None,
                        help='每类场景最大导出数量')

    args = parser.parse_args()

    print("=" * 60)
    print("PID 整定合成数据导出工具")
    print("=" * 60)
    print(f"输出目录: {args.output}")
    print(f"场景类型: {args.type}")
    print(f"输出格式: {args.format}")
    if args.limit:
        print(f"每类上限: {args.limit}")
    print()

    os.makedirs(args.output, exist_ok=True)

    all_results = []
    all_errors = []

    # --- 振荡场景 ---
    if args.type in ('oscillation', 'all'):
        print(f"📊 振荡场景 (TEST_SCENARIOS): {len(TEST_SCENARIOS)} 个")
        results, errors = export_scenarios(
            TEST_SCENARIOS, 'oscillation',
            generate_oscillation_wrapper,
            args.output, args.format, args.limit
        )
        all_results.extend(results)
        all_errors.extend(errors)
        print()

    # --- 工业实际场景 ---
    if args.type in ('realistic', 'all'):
        print(f"🏭 工业实际场景 (REALISTIC_SCENARIOS): {len(REALISTIC_SCENARIOS)} 个")
        results, errors = export_scenarios(
            REALISTIC_SCENARIOS, 'realistic',
            generate_oscillation_wrapper,
            args.output, args.format, args.limit
        )
        all_results.extend(results)
        all_errors.extend(errors)
        print()

    # --- 阶跃响应场景 ---
    if args.type in ('step_response', 'all'):
        print(f"📈 阶跃响应场景 (MODEL_ID_SCENARIOS): {len(MODEL_ID_SCENARIOS)} 个")
        results, errors = export_scenarios(
            MODEL_ID_SCENARIOS, 'step_response',
            generate_step_response_wrapper,
            args.output, args.format, args.limit
        )
        all_results.extend(results)
        all_errors.extend(errors)
        print()

    # --- 写入索引文件 ---
    index = {
        'export_time': datetime.now().isoformat(),
        'total_scenarios': len(all_results),
        'total_errors': len(all_errors),
        'format': args.format,
        'summary': {
            'oscillation': sum(1 for r in all_results if r['type'] == 'oscillation'),
            'realistic': sum(1 for r in all_results if r['type'] == 'realistic'),
            'step_response': sum(1 for r in all_results if r['type'] == 'step_response'),
        },
        'loop_types': {
            lt: sum(1 for r in all_results if r['loop_type'] == lt)
            for lt in set(r['loop_type'] for r in all_results)
        },
        'scenarios': all_results,
        'errors': all_errors,
    }
    index_path = os.path.join(args.output, 'index.json')
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    # --- 汇总 ---
    print("=" * 60)
    print(f"✅ 导出完成!")
    print(f"   成功: {len(all_results)} 个场景")
    if all_errors:
        print(f"   失败: {len(all_errors)} 个场景")
    print(f"   索引: {index_path}")
    print(f"   目录: {args.output}")
    print("=" * 60)


if __name__ == '__main__':
    main()
