"""
统一的大榭现场数据自整定入口脚本 (PID Agent 寻优与评估)

【核心模式与用法说明】
这套脚本支持两种模式的完全隔离测试，最终输出统一精简版结果以防冗余。

1. [默认开启] 滑窗寻优提分模式 (Grid Search Mode)
   通过在连续的数据流上像滑动切片一样扫过，找出评分最高的黄金参数组合。
   命令：/opt/anaconda3/bin/python core/algorithm/model_type/daxie_data/run_tuning.py 50104
   附加参数：
     --window 4.0: 定义切片的窗口时长，默认 4.0 小时。
     --step 2.0:   定义每次向前跨越的步长，默认 2.0 小时 (可以通过增大步长提速)。

2. 传统算法探测段模式 (Auto Detect Mode)
   还原原始版本逻辑，直接依靠算法检测波动段，快速合并出图。
   命令：/opt/anaconda3/bin/python core/algorithm/model_type/daxie_data/run_tuning.py 50104 --mode auto_detect

输出档案位置：
   - 最优测算 CSV 排行榜 (仅限滑窗模式)：output/tuning_grid_search_[device].csv
   - 提取的极限 PID 纯净参数：output/tuning_result_[device]_compact.json
   - 闭环评估走势图：output/model_selector_[device].png
"""


import sys
import os
import json
import time
import argparse
import numpy as np
import concurrent.futures
from datetime import datetime
from pathlib import Path

# 获取项目根目录
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_current_dir))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        elif isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return super(NumpyEncoder, self).default(obj)

from core.algorithm.model_type.pipeline.orchestrator import TuningOrchestrator
from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods

SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_DIR = SCRIPT_DIR / "output"

# 注册回路参数字典
LOOP_CONFIGS = {
    "50104": {
        "device": "2216_LIC_50104",
        "loop_type": "level",
        "start_time": "2025-11-20 00:00:00",
        "end_time": "2025-11-23 00:00:00"
    },
    "50108": {
        "device": "2216_LIC_50108",
        "loop_type": "level",
        "start_time": "2025-11-25 00:00:00",
        "end_time": "2025-11-28 00:00:00"
    }
}

def run_tuning(loop_id: str, enable_grid_search: bool = False, window_h: float = 4.0, step_h: float = 1.0):
    if loop_id not in LOOP_CONFIGS:
        print(f"❌ 未知回路 '{loop_id}'，支持的回路: {list(LOOP_CONFIGS.keys())}")
        sys.exit(1)
        
    cfg = LOOP_CONFIGS[loop_id]
    device = cfg["device"]
    
    json_path = DATA_DIR / f"{device}.json"
    if not json_path.exists():
        print(f"❌ 找不到数据文件: {json_path}")
        sys.exit(1)
        
    print(f"📂 读取 {json_path.name} ...")
    with open(json_path) as f:
        data = json.load(f)
        
    history_data = data["history_data"]
    
    # 截取对应活跃扰动区间
    start_ts = int(datetime.strptime(cfg["start_time"], "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    end_ts = int(datetime.strptime(cfg["end_time"], "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
    
    sliced_data = [d for d in history_data if start_ts <= d["timestamp"] <= end_ts]
    print(f"✂️ 截取数据: {len(sliced_data)} 点 ({cfg['start_time']} ~ {cfg['end_time']})")
    
    # ==========================================
    # 模式分发 (互相完全解耦)
    # ==========================================
    result = None
    final_run_windows = []

    if enable_grid_search:
        # ---------------------------------------------------------
        # 🎯 模式 A: 自动化滑窗寻优提分模式
        # ---------------------------------------------------------
        print(f"\n🔍 开启自动滑窗寻优模式 (防异常) - 满窗: {window_h}h, 步长: {step_h}h")
        search_windows = []
        w_ms = window_h * 3600 * 1000
        step_ms = step_h * 3600 * 1000
        
        curr_start = sliced_data[0]["timestamp"]
        end_bound = sliced_data[-1]["timestamp"]
        
        while curr_start + w_ms <= end_bound:
            search_windows.append({
                "start_time": int(curr_start),
                "end_time": int(curr_start + w_ms)
            })
            curr_start += step_ms
            
        print(f"📊 基于设定的时间范围，共切分出 {len(search_windows)} 个重叠测试段。")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        print(f"\n🚀 [Grid Search] 正在逐段高速跑测评分并记录参数...")

        csv_records = []
        
        # 提取成独立函数以支持多进程
        def evaluate_window(i, window):
            st_str = datetime.fromtimestamp(window['start_time']/1000).strftime('%m-%d %H:%M')
            et_str = datetime.fromtimestamp(window['end_time']/1000).strftime('%m-%d %H:%M')
            
            input_data_seg = {
                'history_data': sliced_data,
                'params': {'model_type': 'FOPDT', 'turning_type': 'PID', 'analyst_column': 'pv', 'exact_window': True},
                'qualified_windows': [window],
                'response_mode': 'balanced'
            }
            # 使用统一的 tuning_context
            from core.models import SemanticProvider
            provider = SemanticProvider()
            tuning_context = provider.get_tuning_context(device)
            tuning_context['exact_window'] = enable_grid_search
            
            orc_seg = TuningOrchestrator(verbose=False, process_context=tuning_context)
            res_seg = orc_seg.run(input_data_seg)
            
            score = res_seg.get('model_rating', 0.0)
            pid = res_seg.get('pid_parameters', {})
            kp, pb = pid.get('kp', 0.0), pid.get('pb', 0.0)
            
            return {
                "segment_idx": i+1, "start_time": st_str, "end_time": et_str, "score": score,
                "kp": kp, "ki": pid.get('ki', 0.0), "kd": pid.get('kd', 0.0),
                "pb": pb, "ti": pid.get('ti', 0.0), "td": pid.get('td', 0.0)
            }

        print(f"\n🚀 [Grid Search] 正在并行高速跑测 ({os.cpu_count() or 4} 线程预热中)...")
        # 多线程并行跑测 (使用Thread避免ProcessPool的Pickle报错)
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
            futures = {executor.submit(evaluate_window, i, w): i for i, w in enumerate(search_windows)}
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    record = future.result()
                    csv_records.append(record)
                    print(f"✅ 片段 {record['segment_idx']:2d}/{len(search_windows)}: {record['start_time']} ~ {record['end_time']} | 评分: {record['score']:5.2f} | Kp={record['kp']:.4f}, Pb={record['pb']:.1f}%")
                except Exception as e:
                    print(f"❌ 片段 {idx+1} 抛出异常: {e}")

        # 将结果按段序号重新排序
        csv_records.sort(key=lambda x: x["segment_idx"])
            
        if csv_records:
            import csv
            csv_records.sort(key=lambda x: x["score"], reverse=True)
            csv_path = OUTPUT_DIR / f"tuning_grid_search_{device}.csv"
            keys = ["segment_idx", "start_time", "end_time", "score", "kp", "ki", "kd", "pb", "ti", "td"]
            with open(csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(csv_records)
                
            print(f"\n✅ 滑窗寻优记录表已导出至 {csv_path.relative_to(SCRIPT_DIR)}")
            
            # 取最优片段作为正式输出
            best_record = csv_records[0]
            best_idx = int(best_record["segment_idx"]) - 1
            final_run_windows = [search_windows[best_idx]]
            print(f"\n🚀 正在提取 Top 1 最优测试段 (得分 {best_record['score']:.2f}) 重新生成最终分析大图与报告...")
            
    else:
        # ---------------------------------------------------------
        # 🎯 模式 B: 回退到旧版的算法探测模式 (Auto Detect)
        # ---------------------------------------------------------
        print("🔍 检测扰动窗口 ...")
        from core.algorithm.tuning_segment import stability_detector
        detect_res = find_high_variability_periods({"history_data": sliced_data})
        final_run_windows = detect_res.get("qualified_windows", [])
        
        if not final_run_windows:
            print("⚠️ 未检测到突出的扰动段，使用全量数据包作为整定窗口")
            if not sliced_data:
                print("❌ 截取的数据为空，请检查你在 LOOP_CONFIGS 设置的 start_time 和 end_time 是否超出了源数据的范围！")
                return
            final_run_windows = [{"start_time": sliced_data[0]["timestamp"], "end_time": sliced_data[-1]["timestamp"]}]
        
        print("\n🚀 运行 TuningOrchestrator (常规算法探测段评估) ...")

    # ==========================================
    # 共同大结局: 最终跑测并只输出精简结果
    # ==========================================
    input_data_final = {
        'history_data': sliced_data,
        'params': {
            'model_type': 'FOPDT', 
            'turning_type': 'PID', 
            'analyst_column': 'pv',
            'exact_window': enable_grid_search  # 如果是网格搜索模式，严格使用传入的整定段，不再进行内部的阶跃二次裁剪
        },
        'qualified_windows': final_run_windows,
        'response_mode': 'balanced'
    }
    
    t0 = time.time()
    
    # [NEW] 使用 SemanticProvider 获取完整的 OS 领域原子模型
    from core.models import SemanticProvider
    provider = SemanticProvider()
    tuning_context = provider.get_tuning_context(device)
    tuning_context['exact_window'] = enable_grid_search  # 补充运行时的控制标志
    
    orchestrator_final = TuningOrchestrator(
        verbose=True, 
        process_context=tuning_context
    )
    result = orchestrator_final.run(input_data_final)
    t1 = time.time()
    
    print(f"\n⏱️ 最终模式执行耗时: {t1 - t0:.2f} 秒")
    
    final_score = result.get('model_rating', 0.0)
    final_pid = result.get('pid_parameters', {})
    rating_details = result.get('rating_details', {})
    perf_score = rating_details.get('performance_score', 0.0)
    conf_score = rating_details.get('method_confidence', 0.0)
    
    print("\n" + "="*60)
    print("🎉 最终整定参数与总分榜单发布！")
    print("=" * 60)
    # 统一读取（兼容大小写 key）
    final_Kp = final_pid.get('Kp', final_pid.get('kp', 0.0))
    final_Ti = final_pid.get('Ti', final_pid.get('ti', 0.0))
    final_Td = final_pid.get('Td', final_pid.get('td', 0.0))
    final_pb = final_pid.get('pb', final_pid.get('Pb', 0.0))
    final_method = final_pid.get('method') or result.get('tuning_features', {}).get('tuning_method') or result.get('tuning_features', {}).get('method') or 'model_based'
    # 如果 Ti 仍为 0 但 Ki > 0，从 Kp/Ki 反推
    final_Ki = final_pid.get('Ki', final_pid.get('ki', 0.0))
    if final_Ti == 0.0 and abs(final_Ki) > 1e-9 and abs(final_Kp) > 1e-9:
        final_Ti = abs(final_Kp) / abs(final_Ki)
    
    print(f"   🏆 综合性能评分 : {final_score:.2f} 分")
    print(f"      ├─ 闭环性能评分 : {perf_score:.2f} / 10")
    print(f"      └─ 方法置信度   : {conf_score:.2f} (权重)")
    print(f"   ⚙️  最终采取方法 : {final_method}")
    print(f"   📊 最终理论参数 : Kp={final_Kp:.4f}, Ti={final_Ti:.1f}s, Td={final_Td:.1f}s")
    print(f"   (对应工控机配置) : Pb={final_pb:.1f}%, Ti={final_Ti:.1f}s")
    print("=" * 60)
    
    # 💡 瘦身版结果存储：剔除大量 history_data，仅保留 PID、时间、评分
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    compact_result = {
        "device": device,
        "mode_used": "grid_search" if enable_grid_search else "auto_detect",
        "time_information": {
            "used_tuning_windows": final_run_windows
        },
        "model_rating": result.get("model_rating", 0.0),
        "model_type": result.get("model_type", "FOPDT"),
        "model_parameters": result.get("model_parameters", {}).copy(),
        "pid_parameters": result.get("pid_parameters", {})
    }
    
    # [NEW] 输出修正：如果命中了兜底免死金牌，在数据记录上正式修正为纯积分物理模型(FO_INTEGRATOR)
    if final_pid.get('method') == 'integrating_fallback':
        compact_result['model_type'] = 'FO_INTEGRATOR'
        m_params = compact_result['model_parameters']
        if 'K' in m_params and 'T1' in m_params:
            m_params['K'] = m_params['K'] / max(m_params['T1'], 1.0)
            m_params['T1'] = 0.0
            print(f"   🔄 JSON输出修正：当前模型已固化为纯物理积分器(FO_INTEGRATOR), K_int={m_params['K']:.6f}")
    
    out_file = OUTPUT_DIR / f"tuning_result_{device}_compact.json"
    with open(out_file, "w") as f:
        json.dump(compact_result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"\n💾 精简核心参数结果已保存到 {out_file.relative_to(SCRIPT_DIR)}")

    # 生成预测可视化图
    try:
        from core.algorithm.model_type.tests.visualization_utils import (
            visualize_fitting_result, normalize_pid_params
        )
        
        # 使用统一的 PID 参数标准化（自动处理大小写、Ki/Kd 推算）
        if 'pid_parameters' in result:
            result['pid_parameters'] = normalize_pid_params(result['pid_parameters'])

        visualize_fitting_result(
            sliced_data, {'tuning_window': final_run_windows}, result, device,
            output_dir=str(OUTPUT_DIR)
        )
        print(f"📊 闭环预测图表已成功保存至 {OUTPUT_DIR.relative_to(SCRIPT_DIR)}")
    except ImportError:
        print("⚠️ 可视化模块未找到，跳过图表生成")

if __name__ == "__main__":
    # 使用 argparse 来支持行命令运行和参数动态调整
    parser = argparse.ArgumentParser(description="大榭现场数据自整定入口脚本")
    parser.add_argument("loop_id", nargs="?", default="50104", help="指定回路ID进行测试，如: 50104")
    parser.add_argument("--mode", choices=["benchmark", "auto_pipeline"], default="auto_pipeline",
                        help="运行模式: 'benchmark' 为多线程并发测分压测仪，'auto_pipeline' 为模拟真实后端全自动智能流转。")
    parser.add_argument("--window", type=float, default=6.0, help="滑窗寻优模式下的满窗长度(小时), 默认 4.0")
    parser.add_argument("--step", type=float, default=2.0, help="滑窗寻优模式下每次移动的步长(小时), 改大可提速, 默认 2.0")
    args = parser.parse_args()

    TARGET_LOOP = args.loop_id
    ENABLE_GRID_SEARCH = (args.mode == "auto_pipeline")

    # [可选] 也可以在这里临时覆盖字典里的默认起止时间
    LOOP_CONFIGS[TARGET_LOOP]["start_time"] = "2025-11-25 00:00:00"
    LOOP_CONFIGS[TARGET_LOOP]["end_time"] = "2025-11-26 00:00:00"
    
    print("=" * 60)
    print(f"🔧 开始跑测大榭现场数据 - 回路: {TARGET_LOOP}")
    print(f"🌍 运行模式: {'[Benchmark (并发性能压测模式)]' if ENABLE_GRID_SEARCH else '[Auto Pipeline (后端混合演练模式)]'}")
    print("=" * 60)
    
    run_tuning(TARGET_LOOP, enable_grid_search=ENABLE_GRID_SEARCH, window_h=args.window, step_h=args.step)
