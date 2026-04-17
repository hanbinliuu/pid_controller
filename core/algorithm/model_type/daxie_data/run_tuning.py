"""
统一的大榭现场数据自整定入口脚本 (PID Agent 寻优与评估)

【最常用用法（兼容旧数据 + 新原始数据）】

1) 旧流程（2216 回路，兼容 data/数据1.csv + data/数据2.csv）
   python core/algorithm/model_type/daxie_data/run_tuning.py 50104
   说明：
   - 优先读取 data/2216_LIC_50104.json
   - 若 JSON 不存在且 data 目录下有 数据1.csv/数据2.csv，会自动转换后再整定

2) 新流程（直接用 20260416.csv 原始数据）
   先看位号：
   python core/algorithm/model_type/daxie_data/run_tuning.py --list-devices --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv

   - 5203_FIC_21005
   - 5203_LIC_11502
   - 5203_PIC_11201
   - 5203_PIC_11501 ---已经稳态    --ok
   - 5203_PIC_21901 ---已经稳态
   - 5203_TIC_11303  
   - 5203_TIC_20201   --ok

   再整定（示例：5203_LIC_11502）：
   python core/algorithm/model_type/daxie_data/run_tuning.py 5203_PIC_11501 --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv --parse-raw
   默认时间窗（未显式传参时）: 2026-04-15 00:00:00 ~ 2026-04-16 00:00:00

    测试已经稳定的回路
    python core/algorithm/model_type/daxie_data/run_tuning.py 5203_PIC_21901 \
  --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv \
  --parse-raw \
  --mode benchmark \
  --blind-validate \
  --seed 42

  
3) 模式切换
   - 默认: auto_pipeline（滑窗寻优）
   - 可选: --mode benchmark（扰动段探测）

输出目录：
   - output/tuning_grid_search_[device].csv
   - output/tuning_result_[device]_compact.json
   - output/model_selector_[device].png
"""


import sys
import os
import json
import time
import argparse
import numpy as np
import pandas as pd
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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
DEFAULT_RAW_CSV = DATA_DIR / "20260416.csv"
DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
RAW_DEFAULT_START_TIME = "2026-04-15 00:00:00"
RAW_DEFAULT_END_TIME = "2026-04-16 00:00:00"

# 注册回路参数字典
LOOP_CONFIGS = {
    "50104": {
        "device": "2216_LIC_50104",
        "loop_type": "level",
        "current_pid": {"pb": 500.0, "ti": 250.0, "td": 0.0},
        "start_time": "2026-03-13 00:00:00",
        "end_time": "2025-11-23 00:00:00"
    },
    "50108": {
        "device": "2216_LIC_50108",
        "loop_type": "level",
        "start_time": "2026-03-13 00:00:00",
        "end_time": "2025-11-28 00:00:00"
    }
}

def infer_loop_type(device: str) -> str:
    if "_LIC_" in device:
        return "level"
    if "_FIC_" in device:
        return "flow"
    if "_TIC_" in device:
        return "temperature"
    if "_PIC_" in device:
        return "pressure"
    return "level"


def list_devices_from_raw_csv(raw_csv_path: Path) -> List[str]:
    df = pd.read_csv(raw_csv_path, nrows=0, skiprows=[1], index_col=False, engine="c")
    return sorted([col[:-3] for col in df.columns if col.endswith(".PV")])


def parse_raw_csv_to_history(raw_csv_path: Path, device: str, save_json: bool = True) -> List[Dict[str, Any]]:
    print(f"📂 解析原始 CSV: {raw_csv_path.name} | 设备: {device}")
    df = pd.read_csv(raw_csv_path, skiprows=[1], index_col=False, engine="c")
    df = df.loc[:, ~df.columns.str.startswith("Unnamed")]

    if "Test" not in df.columns:
        raise ValueError(f"原始 CSV 缺少时间列 'Test'，文件: {raw_csv_path}")

    pv_col = f"{device}.PV"
    sv_col = f"{device}.SV"
    mv_col = f"{device}.MV"
    for col in (pv_col, sv_col, mv_col):
        if col not in df.columns:
            raise ValueError(f"原始 CSV 缺少列: {col}")

    df["datetime"] = pd.to_datetime(df["Test"], errors="coerce")
    df = df[df["datetime"].notna()].copy()
    df.sort_values("datetime", inplace=True)
    df.drop_duplicates(subset="datetime", keep="first", inplace=True)

    timestamps = (df["datetime"].astype("int64") // 10**6).astype(np.int64).values
    pvs = df[pv_col].fillna(0.0).astype(np.float64).values
    svs = df[sv_col].fillna(0.0).astype(np.float64).values
    mvs = df[mv_col].fillna(0.0).astype(np.float64).values

    history_data = [
        {
            "timestamp": int(timestamps[i]),
            "pv": round(float(pvs[i]), 6),
            "sv": round(float(svs[i]), 6),
            "mv": round(float(mvs[i]), 6),
        }
        for i in range(len(timestamps))
    ]

    if save_json:
        os.makedirs(DATA_DIR, exist_ok=True)
        if len(timestamps) > 1:
            sample_sec = int(round(float(np.median(np.diff(timestamps)) / 1000.0)))
        else:
            sample_sec = 0
        output = {
            "metadata": {
                "device": device,
                "description": device,
                "loop_type": infer_loop_type(device),
                "data_source": f"raw_csv:{raw_csv_path.name}",
                "time_range": {
                    "start": str(df['datetime'].iloc[0]),
                    "end": str(df['datetime'].iloc[-1]),
                },
                "sampling_interval_sec": sample_sec,
                "total_points": len(history_data),
            },
            "data_points": len(history_data),
            "columns": ["timestamp", "pv", "sv", "mv"],
            "history_data": history_data,
        }
        output_path = DATA_DIR / f"{device}.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
        print(f"💾 原始数据解析完成并保存: {output_path.relative_to(SCRIPT_DIR)}")

    return history_data

def extract_current_pid_from_raw_csv(raw_csv_path: Path, device: str) -> Optional[Dict[str, float]]:
    """
    从原始 CSV 提取设备当前 PID（优先取末尾有效值）。
    读取列: [device].PB / [device].TI / [device].TD
    返回: {"pb": float, "ti": float, "td": float} 或 None
    """
    pb_col = f"{device}.PB"
    ti_col = f"{device}.TI"
    td_col = f"{device}.TD"

    try:
        df = pd.read_csv(raw_csv_path, skiprows=[1], index_col=False, engine="c")
    except Exception as e:
        print(f"⚠️ 读取原始 CSV 提取 current_pid 失败: {e}")
        return None

    missing = [c for c in (pb_col, ti_col, td_col) if c not in df.columns]
    if missing:
        return None

    def _last_valid_number(series: pd.Series) -> Optional[float]:
        s = pd.to_numeric(series, errors="coerce").dropna()
        if s.empty:
            return None
        return float(s.iloc[-1])

    pb = _last_valid_number(df[pb_col])
    ti = _last_valid_number(df[ti_col])
    td = _last_valid_number(df[td_col])

    if pb is None and ti is None and td is None:
        return None

    return {
        "pb": pb if pb is not None else 0.0,
        "ti": ti if ti is not None else 0.0,
        "td": td if td is not None else 0.0,
    }


def maybe_build_legacy_json_from_data12(device: str) -> bool:
    """
    兼容旧流程: 当 2216_*.json 缺失，但 data/数据1.csv 或 data/数据2.csv 存在时，
    自动执行一次转换并生成对应 JSON。
    """
    legacy_1 = DATA_DIR / "数据1.csv"
    legacy_2 = DATA_DIR / "数据2.csv"
    if not (legacy_1.exists() or legacy_2.exists()):
        return False

    try:
        from core.algorithm.model_type.daxie_data.convert_daxie_data import (
            load_and_merge_csv,
            extract_and_save,
        )
        merged = load_and_merge_csv()
        if f"{device}.PV" not in merged.columns:
            print(f"⚠️ 旧数据文件中未找到 {device}.PV，跳过自动转换")
            return False
        extract_and_save(merged, device, device)
        return True
    except Exception as e:
        print(f"⚠️ 自动转换旧数据失败: {e}")
        return False


def resolve_loop_config(loop_id: str, raw_csv_path: Optional[Path]) -> Dict[str, Any]:
    if loop_id in LOOP_CONFIGS:
        return dict(LOOP_CONFIGS[loop_id])

    if not raw_csv_path or not raw_csv_path.exists():
        print(f"❌ 未知回路 '{loop_id}'，支持的固定回路: {list(LOOP_CONFIGS.keys())}")
        print("   如需使用原始 CSV，请添加: --raw-csv <path> (或确保 data/20260416.csv 存在)")
        sys.exit(1)

    devices = list_devices_from_raw_csv(raw_csv_path)
    matched = [d for d in devices if d == loop_id]
    if not matched:
        matched = [d for d in devices if d.endswith(f"_{loop_id}")]

    if len(matched) != 1:
        print(f"❌ 在原始 CSV 中无法唯一定位回路 '{loop_id}'。")
        print(f"   可选设备: {devices}")
        sys.exit(1)

    device = matched[0]
    return {
        "device": device,
        "loop_type": infer_loop_type(device),
        "start_time": RAW_DEFAULT_START_TIME,
        "end_time": RAW_DEFAULT_END_TIME,
    }


def maybe_load_history_data(
    cfg: Dict[str, Any],
    raw_csv_path: Optional[Path],
    force_parse_raw: bool = False,
) -> List[Dict[str, Any]]:
    device = cfg["device"]
    json_path = DATA_DIR / f"{device}.json"
    can_parse_raw = raw_csv_path is not None and raw_csv_path.exists()

    if force_parse_raw:
        if not can_parse_raw:
            print(f"❌ 指定了 --parse-raw，但找不到原始 CSV: {raw_csv_path}")
            sys.exit(1)
        return parse_raw_csv_to_history(raw_csv_path, device, save_json=True)

    if json_path.exists():
        print(f"📂 读取 {json_path.name} ...")
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        return data["history_data"]

    if can_parse_raw:
        return parse_raw_csv_to_history(raw_csv_path, device, save_json=True)

    if device.startswith("2216_"):
        print("ℹ️ 未找到 JSON，尝试从旧文件 数据1.csv/数据2.csv 自动转换...")
        if maybe_build_legacy_json_from_data12(device) and json_path.exists():
            print(f"📂 读取 {json_path.name} ...")
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            return data["history_data"]

    print(f"❌ 找不到数据文件: {json_path}")
    if raw_csv_path:
        print(f"   且原始 CSV 不可用: {raw_csv_path}")
    sys.exit(1)


def to_epoch_ms(dt_str: str) -> int:
    """统一时间戳口径: 与 CSV 解析中的 pandas Timestamp 一致，避免环境时区差异。"""
    return int(pd.Timestamp(dt_str).value // 10**6)

def _normalize_pid_dict(pid: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """统一 PID 显示键，兼容大小写与 Pb/Kp 换算。"""
    if not pid:
        return {}
    p = dict(pid)
    kp = p.get("kp", p.get("Kp"))
    pb = p.get("pb", p.get("Pb"))
    ti = p.get("ti", p.get("Ti"))
    td = p.get("td", p.get("Td"))
    ki = p.get("ki", p.get("Ki"))
    kd = p.get("kd", p.get("Kd"))

    def _to_float(v):
        try:
            return float(v)
        except Exception:
            return None

    kp = _to_float(kp)
    pb = _to_float(pb)
    ti = _to_float(ti)
    td = _to_float(td)
    ki = _to_float(ki)
    kd = _to_float(kd)

    if (kp is None or abs(kp) < 1e-12) and pb is not None and abs(pb) > 1e-12:
        kp = 100.0 / pb
    if (pb is None or abs(pb) < 1e-12) and kp is not None and abs(kp) > 1e-12:
        pb = 100.0 / kp

    return {
        "kp": kp if kp is not None else 0.0,
        "pb": pb if pb is not None else 0.0,
        "ti": ti if ti is not None else 0.0,
        "td": td if td is not None else 0.0,
        "ki": ki if ki is not None else 0.0,
        "kd": kd if kd is not None else 0.0,
    }


def run_tuning(
    loop_id: str,
    enable_grid_search: bool = False,
    window_h: float = 4.0,
    step_h: float = 1.0,
    raw_csv: Optional[str] = None,
    force_parse_raw: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    raw_csv_path: Optional[Path] = None
    if raw_csv:
        raw_csv_path = Path(raw_csv)
    elif DEFAULT_RAW_CSV.exists():
        raw_csv_path = DEFAULT_RAW_CSV

    cfg = resolve_loop_config(loop_id, raw_csv_path)
    device = cfg["device"]
    current_pid_cfg = cfg.get("current_pid")
    history_data = maybe_load_history_data(cfg, raw_csv_path=raw_csv_path, force_parse_raw=force_parse_raw)

    # 对新原始 CSV 设备：若未显式配置 current_pid，则自动从 PB/TI/TD 列提取
    if not current_pid_cfg and raw_csv_path and raw_csv_path.exists():
        auto_pid = extract_current_pid_from_raw_csv(raw_csv_path, device)
        if auto_pid:
            current_pid_cfg = auto_pid
            print(f"🧭 自动读取当前PID: Pb={auto_pid.get('pb', 0.0):.1f}%, Ti={auto_pid.get('ti', 0.0):.1f}s, Td={auto_pid.get('td', 0.0):.1f}s")

    start_time = start_time or cfg.get("start_time")
    end_time = end_time or cfg.get("end_time")
    if start_time and end_time:
        start_ts = to_epoch_ms(start_time)
        end_ts = to_epoch_ms(end_time)
        if start_ts > end_ts:
            print(f"⚠️ 检测到起止时间倒置，自动交换: {start_time} > {end_time}")
            start_ts, end_ts = end_ts, start_ts
        sliced_data = [d for d in history_data if start_ts <= d["timestamp"] <= end_ts]
        print(f"✂️ 截取数据: {len(sliced_data)} 点 ({start_time} ~ {end_time})")
    else:
        sliced_data = history_data
        if sliced_data:
            st = datetime.fromtimestamp(sliced_data[0]["timestamp"] / 1000).strftime(DATETIME_FMT)
            et = datetime.fromtimestamp(sliced_data[-1]["timestamp"] / 1000).strftime(DATETIME_FMT)
            print(f"✂️ 使用全量数据: {len(sliced_data)} 点 ({st} ~ {et})")

    if not sliced_data:
        print("❌ 截取结果为空，请检查起止时间是否落在数据时间范围内")
        return
    
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
                'response_mode': 'balanced',
                'current_pid': current_pid_cfg
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
            
            # 取 Top N 高分片段用于多窗口融合（提升参数鲁棒性）
            top_n = 3
            min_score_ratio = 0.85
            best_score = csv_records[0]['score']
            score_threshold = best_score * min_score_ratio
            top_records = [r for r in csv_records[:top_n] if r['score'] >= score_threshold]
            final_run_windows = [search_windows[int(r["segment_idx"]) - 1] for r in top_records]
            scores_str = ", ".join(f"{r['score']:.2f}" for r in top_records)
            
            # 保存 Top-1 信息用于质量门控（如果多段融合效果更差则退化为 Top-1）
            best_single_score = best_score
            best_single_window = [search_windows[int(csv_records[0]["segment_idx"]) - 1]]
            
            if len(top_records) > 1:
                print(f"\n🚀 正在提取 Top {len(top_records)} 最优测试段 (得分: {scores_str}) 进行多窗口融合...")
            else:
                print(f"\n🚀 正在提取最优测试段 (得分: {scores_str}) 生成最终分析大图与报告...")
            
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
        'response_mode': 'balanced',
        'current_pid': current_pid_cfg
    }
    
    t0 = time.time()
    
    # [NEW] 使用 SemanticProvider 获取完整的 OS 领域原子模型
    from core.models import SemanticProvider
    provider = SemanticProvider()
    tuning_context = provider.get_tuning_context(device)
    tuning_context['exact_window'] = enable_grid_search  # 补充运行时的控制标志

    baseline_pid = _normalize_pid_dict(current_pid_cfg or tuning_context.get("current_pid"))
    
    orchestrator_final = TuningOrchestrator(
        verbose=True, 
        process_context=tuning_context
    )
    result = orchestrator_final.run(input_data_final)
    t1 = time.time()
    
    print(f"\n⏱️ 最终模式执行耗时: {t1 - t0:.2f} 秒")
    
    final_score = result.get('model_rating', 0.0)
    final_pid = result.get('pid_parameters', {})
    
    # ==========================================
    # 质量门控 (Quality Gate): 多段融合 vs Top-1
    # ==========================================
    # 如果多段融合评分低于网格搜索阶段的最高单段评分，
    # 自动退化为 Top-1 单段重跑，确保多段融合不会劣化结果
    if enable_grid_search and len(final_run_windows) > 1 and csv_records:
        if final_score < best_single_score:
            print(f"\n⚠️ [质量门控] 多段融合评分 {final_score:.2f} < 最佳单段评分 {best_single_score:.2f}")
            print(f"   → 自动退化为 Top-1 最优单段重跑...")
            
            final_run_windows = best_single_window
            input_data_final['qualified_windows'] = final_run_windows
            
            t0 = time.time()
            orchestrator_final = TuningOrchestrator(verbose=True, process_context=tuning_context)
            result = orchestrator_final.run(input_data_final)
            t1 = time.time()
            
            print(f"\n⏱️ Top-1 重跑耗时: {t1 - t0:.2f} 秒")
            final_score = result.get('model_rating', 0.0)
            final_pid = result.get('pid_parameters', {})
            print(f"   ✅ Top-1 重跑评分: {final_score:.2f} (原多段: {best_single_score:.2f})")
        else:
            print(f"\n✅ [质量门控] 多段融合评分 {final_score:.2f} ≥ 最佳单段评分 {best_single_score:.2f}，保持融合结果")
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
    
    if baseline_pid:
        print(f"   🧭 当前PID(基线)  : Kp={baseline_pid.get('kp', 0.0):.4f}, Pb={baseline_pid.get('pb', 0.0):.1f}%, Ti={baseline_pid.get('ti', 0.0):.1f}s, Td={baseline_pid.get('td', 0.0):.1f}s")
    else:
        print("   🧭 当前PID(基线)  : N/A (未提供)")

    print(f"   🏆 综合性能评分 : {final_score:.2f} 分")
    print(f"      ├─ 闭环性能评分 : {perf_score:.2f} / 10")
    print(f"      └─ 方法置信度   : {conf_score:.2f} (权重)")
    print(f"   ⚙️  最终采取方法 : {final_method}")
    print(f"   📊 最终理论参数 : Kp={final_Kp:.4f}, Ti={final_Ti:.1f}s, Td={final_Td:.1f}s")
    print(f"   (对应工控机配置) : Pb={final_pb:.1f}%, Ti={final_Ti:.1f}s")
    if baseline_pid and abs(baseline_pid.get("pb", 0.0)) > 1e-12:
        d_pb = final_pb - baseline_pid.get("pb", 0.0)
        d_ti = final_Ti - baseline_pid.get("ti", 0.0)
        d_td = final_Td - baseline_pid.get("td", 0.0)
        print(f"   🔁 参数变化对比   : ΔPb={d_pb:+.1f}%, ΔTi={d_ti:+.1f}s, ΔTd={d_td:+.1f}s")
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
    compact_result["baseline_pid"] = baseline_pid or {}
    
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
    parser.add_argument("--raw-csv", default=None, help="原始CSV路径(首行列名、第二行为中文描述)。示例: data/20260416.csv")
    parser.add_argument("--parse-raw", action="store_true", help="强制从原始CSV重新解析并覆盖对应的 [device].json")
    parser.add_argument("--list-devices", action="store_true", help="仅列出原始CSV中可用设备位号后退出")
    parser.add_argument("--start-time", default=None, help="可选，覆盖截取起始时间。格式: YYYY-mm-dd HH:MM:SS")
    parser.add_argument("--end-time", default=None, help="可选，覆盖截取结束时间。格式: YYYY-mm-dd HH:MM:SS")
    parser.add_argument("--mode", choices=["benchmark", "auto_pipeline"], default="benchmark",
                        help="运行模式: 'benchmark' 为多线程并发测分压测仪，'auto_pipeline' 为模拟真实后端全自动智能流转。")
    parser.add_argument("--window", type=float, default=6.0, help="滑窗寻优模式下的满窗长度(小时), 默认 4.0")
    parser.add_argument("--step", type=float, default=2.0, help="滑窗寻优模式下每次移动的步长(小时), 改大可提速, 默认 2.0")
    args = parser.parse_args()

    TARGET_LOOP = args.loop_id
    ENABLE_GRID_SEARCH = (args.mode == "auto_pipeline")
    raw_csv_path = Path(args.raw_csv) if args.raw_csv else DEFAULT_RAW_CSV

    if args.list_devices:
        if not raw_csv_path.exists():
            print(f"❌ 找不到原始 CSV: {raw_csv_path}")
            sys.exit(1)
        devices = list_devices_from_raw_csv(raw_csv_path)
        print(f"🔍 {raw_csv_path.name} 中可用设备({len(devices)}):")
        for d in devices:
            print(f"   - {d}")
        sys.exit(0)
    
    print("=" * 60)
    print(f"🔧 开始跑测大榭现场数据 - 回路: {TARGET_LOOP}")
    print(f"🌍 运行模式: {'[Auto Pipeline (滑窗寻优)]' if ENABLE_GRID_SEARCH else '[Benchmark (扰动段探测)]'}")
    print("=" * 60)
    
    run_tuning(
        TARGET_LOOP,
        enable_grid_search=ENABLE_GRID_SEARCH,
        window_h=args.window,
        step_h=args.step,
        raw_csv=args.raw_csv,
        force_parse_raw=args.parse_raw,
        start_time=args.start_time,
        end_time=args.end_time,
    )
