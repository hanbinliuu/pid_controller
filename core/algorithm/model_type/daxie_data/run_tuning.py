"""
统一的大榭现场数据自整定入口脚本
用法: python3 run_tuning.py [loop_name]
示例: python3 run_tuning.py 50104
"""

import sys
import os
import json
import time
import argparse
import numpy as np
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

def run_tuning(loop_id: str):
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
    
    print("🔍 检测扰动窗口 ...")
    from core.algorithm.tuning_segment import stability_detector
    print(f"DEBUG module loaded from: {stability_detector.__file__}")
    detect_res = find_high_variability_periods({"history_data": sliced_data})
    qualified_windows = detect_res.get("qualified_windows", [])
    
    if not qualified_windows:
        print("⚠️ 未检测到突出的扰动段，使用全量数据包作为整定窗口")
        qualified_windows = [{"start_time": sliced_data[0]["timestamp"], "end_time": sliced_data[-1]["timestamp"]}]
            
    input_data = {
        'history_data': sliced_data,
        'params': {
            'model_type': 'FOPDT',
            'turning_type': 'PID',
            'analyst_column': 'pv'
        },
        'qualified_windows': qualified_windows,
        'response_mode': 'balanced'
    }
    
    print("\n🚀 运行 TuningOrchestrator ...")
    t0 = time.time()
    
    orchestrator = TuningOrchestrator(
        verbose=True, 
        process_context={'loop_type': cfg['loop_type'], 'loop_name': device}
    )
    result = orchestrator.run(input_data)
    
    t1 = time.time()
    print(f"\n⏱️ 整定耗时: {t1 - t0:.2f} 秒")
    
    # 保存结果到 output 目录
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_file = OUTPUT_DIR / f"tuning_result_{device}.json"
    with open(out_file, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, cls=NumpyEncoder)
    print(f"\n💾 完整结果已保存到 {out_file.relative_to(SCRIPT_DIR)}")

    # 生成预测可视化图
    print("\n📈 正在生成新参数走势预测图（包括闭环仿真验证）...")
    from core.algorithm.model_type.tests.test_model_selector_real import visualize_fitting_result, CONFIG
    CONFIG['log_dir'] = str(OUTPUT_DIR)  # 保存到 output 目录
    visualize_fitting_result(sliced_data, {'tuning_window': qualified_windows}, result, device)
    
    print(f"📊 图表已保存至 {OUTPUT_DIR.relative_to(SCRIPT_DIR)}")

if __name__ == "__main__":
    # ==========================================
    # ⚙️ 在这里直接修改要跑测的回路和时间段
    # ==========================================    # 测试参数
    TARGET_LOOP = '50104'  # 第一组液位数据（高设定值，强非线性）
    # TARGET_LOOP = '50108'  # 第二组液位数据（振荡为主，稳态）  
    # 也可以临时覆盖字典里的默认时间（如果需要自定义测试片段的话）
    LOOP_CONFIGS[TARGET_LOOP]["start_time"] = "2025-12-15 00:00:00"
    LOOP_CONFIGS[TARGET_LOOP]["end_time"] = "2025-12-16 00:00:00"
    
    print("=" * 60)
    print(f"🔧 开始跑测大榭现场数据 - 回路: {TARGET_LOOP}")
    print("=" * 60)
    
    run_tuning(TARGET_LOOP)
