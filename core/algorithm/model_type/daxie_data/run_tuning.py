"""
统一的大榭现场数据自整定入口脚本 (PID Agent 寻优与评估)

【最常用用法（兼容旧数据 + 新原始数据）】

1) 旧流程（2216 回路，兼容 data/数据1.csv + data/数据2.csv）
 python core/algorithm/model_type/daxie_data/run_tuning.py 50104 \
  --legacy-refresh \
  --start-time "2026-03-13 00:00:00" \
  --end-time "2026-03-14 00:00:00"

2) 新流程（直接用 20260416.csv 原始数据）
   先看位号：
   python core/algorithm/model_type/daxie_data/run_tuning.py --list-devices --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv

   当前验证状态（截至 2026-04-17）：
   - 5203_FIC_21005  --ok
   - 5203_LIC_11502  --ok
   - 5203_PIC_11201  --no
   - 5203_PIC_11501  --已经稳态 --ok
   - 5203_PIC_21901  --已经稳态 --no
   - 5203_TIC_11303  --ok
   - 5203_TIC_20201  --ok

   再整定（示例）：
   python core/algorithm/model_type/daxie_data/run_tuning.py 5203_PIC_11501 --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv --parse-raw
   默认时间窗（未显式传参时）: 2026-04-15 00:00:00 ~ 2026-04-16 00:00:00

3) 两类目标（推荐直接用 --scenario）
   A. 非稳态回路“先调稳”：
   python core/algorithm/model_type/daxie_data/run_tuning.py 5203_FIC_21005  \
     --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv \
     --parse-raw \
     --mode benchmark \
     --scenario unstable \
     --seed 42

   说明：
   - 等价于旧参数 `--blind-validate`
   - 整定过程不依赖 current PID（仅用于结果对比）

   B. 已稳态回路“求进步”：
   python core/algorithm/model_type/daxie_data/run_tuning.py 5203_PIC_11501 \
     --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv \
     --parse-raw \
     --mode benchmark \
     --scenario stable_evolve \
     --seed 42
   说明：
   - 等价于旧参数 `--stable-evolve`
   - 允许参考 current PID，且仅当可证明更优才放行新参数
   - 可调进步阈值: `--stable-margin 0.5 --stable-max-delta 0.5`

   python core/algorithm/model_type/daxie_data/run_tuning.py \
    --batch \
    --batch-quiet \
    --raw-csv core/algorithm/model_type/daxie_data/data/20260416.csv \
    --parse-raw \
    --mode benchmark \
    --batch-scenario auto \
    --seed 42 \
    --report-name tuning_batch_full

   

4) 模式切换
   - 默认: benchmark（扰动段探测）
   - 可选: --mode auto_pipeline（滑窗寻优）

5) 兼容旧参数
   - `--blind-validate` 与 `--stable-evolve` 仍可使用
   - 若与 `--scenario` 同时指定，以 `--scenario` 为准

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
import random
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


def _baseline_to_pid_params(baseline_pid: Dict[str, float]) -> Dict[str, float]:
    """将 baseline_pid 映射成输出格式的 pid_parameters（含大小写兼容字段）。"""
    kp = float(baseline_pid.get("kp", 0.0) or 0.0)
    ti = float(baseline_pid.get("ti", 0.0) or 0.0)
    td = float(baseline_pid.get("td", 0.0) or 0.0)
    pb = float(baseline_pid.get("pb", (100.0 / kp if abs(kp) > 1e-12 else 0.0)) or 0.0)
    ki = kp / ti if ti > 1e-12 else 0.0
    kd = kp * td
    return {
        "kp": kp, "Kp": kp,
        "ki": ki, "Ki": ki,
        "kd": kd, "Kd": kd,
        "ti": ti, "Ti": ti,
        "td": td, "Td": td,
        "pb": pb, "Pb": pb,
        "method": "keep_current_not_identifiable",
    }


def _is_valid_model_for_rating(result: Dict[str, Any]) -> bool:
    """判断最终模型是否足以作为 current/new PID 的同口径仿真考场。"""
    if not result or not result.get("success", True):
        return False
    model_params = result.get("model_parameters", {}) or {}
    model_type = str(result.get("model_type", "") or "").upper()
    k = float(model_params.get("K", 0.0) or 0.0)
    t1 = float(model_params.get("T1", 0.0) or 0.0)
    if abs(k) < 1e-9:
        return False
    if model_type == "FO_INTEGRATOR":
        return True
    return t1 > 1e-9


def _evaluate_pid_against_result_model(
    result: Dict[str, Any],
    pid: Dict[str, float],
    loop_type: str,
    confidence: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """用同一个辨识模型给某组 PID 打分；模型不可辨识时返回 None。"""
    if not pid or not _is_valid_model_for_rating(result):
        return None
    try:
        from core.algorithm.model_type.rating import ModelRating
        model_params = dict(result.get("model_parameters", {}) or {})
        pid_params = _baseline_to_pid_params(pid)
        method_conf = confidence
        if method_conf is None:
            method_conf = float((result.get("rating_details", {}) or {}).get("method_confidence", 0.0) or 0.0)
        return ModelRating.evaluate(
            model_params,
            pid_params,
            method="current_pid_baseline",
            method_confidence=method_conf,
            method_confidence_details={"method": "current_pid_baseline", "note": "same identified model"},
            loop_type=loop_type,
        )
    except Exception as e:
        return {"error": str(e)}


def _evaluate_historical_operating_score(history_data: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """
    现场历史实绩评分：不依赖模型，只回答“这段数据在当前 PID 下实际稳不稳”。
    它不证明新参数更好，但能作为稳定回路的保护基准。
    """
    if not history_data:
        return None
    pv = np.array([float(d.get("pv", 0.0) or 0.0) for d in history_data], dtype=float)
    sv = np.array([float(d.get("sv", 0.0) or 0.0) for d in history_data], dtype=float)
    mv = np.array([float(d.get("mv", 0.0) or 0.0) for d in history_data], dtype=float)
    if len(pv) < 20:
        return None

    finite = np.isfinite(pv) & np.isfinite(sv) & np.isfinite(mv)
    pv, sv, mv = pv[finite], sv[finite], mv[finite]
    if len(pv) < 20:
        return None

    scale = max(abs(float(np.nanmedian(sv))), float(np.nanpercentile(pv, 95) - np.nanpercentile(pv, 5)), 1e-6)
    err_pct = np.abs(pv - sv) / scale * 100.0
    mae_pct = float(np.nanmean(err_pct))
    p95_pct = float(np.nanpercentile(err_pct, 95))
    pv_std_pct = float(np.nanstd(pv) / scale * 100.0)
    mv_scale = max(abs(float(np.nanmedian(mv))), float(np.nanpercentile(mv, 95) - np.nanpercentile(mv, 5)), 1.0)
    mv_jitter_pct = float(np.nanstd(np.diff(mv)) / mv_scale * 100.0) if len(mv) > 1 else 0.0

    mae_score = float(np.interp(mae_pct, [0, 0.2, 0.5, 1.0, 2.0, 5.0], [10, 9.5, 8.5, 7.0, 4.0, 0.0]))
    p95_score = float(np.interp(p95_pct, [0, 0.5, 1.0, 2.0, 5.0, 10.0], [10, 9.5, 8.0, 6.0, 3.0, 0.0]))
    pv_score = float(np.interp(pv_std_pct, [0, 0.2, 0.5, 1.0, 3.0, 8.0], [10, 9.5, 8.5, 7.0, 4.0, 0.0]))
    mv_score = float(np.interp(mv_jitter_pct, [0, 0.2, 0.5, 1.0, 3.0, 8.0], [10, 9.0, 8.0, 6.0, 3.0, 0.0]))
    score = 0.35 * mae_score + 0.25 * p95_score + 0.25 * pv_score + 0.15 * mv_score

    return {
        "score": round(float(np.clip(score, 0.0, 10.0)), 2),
        "mae_pct": round(mae_pct, 3),
        "p95_pct": round(p95_pct, 3),
        "pv_std_pct": round(pv_std_pct, 3),
        "mv_jitter_pct": round(mv_jitter_pct, 3),
    }


def _synthesize_baseline_reference_score(
    historical_score: Optional[Dict[str, float]],
    baseline_model_rating: Optional[Dict[str, Any]],
    method_confidence: float,
) -> Optional[Dict[str, float]]:
    """
    生成“当前PID综合参考分”：
    - 历史实绩分：反映真实运行
    - 同口径模型分：反映在同一辨识模型上的可比性
    """
    hist = None
    model = None
    if historical_score:
        hist = float(historical_score.get("score", 0.0) or 0.0)
    if baseline_model_rating and not baseline_model_rating.get("error"):
        model = float(baseline_model_rating.get("final_rating", baseline_model_rating.get("performance_score", 0.0)) or 0.0)

    if hist is None and model is None:
        return None
    if hist is None:
        return {"score": round(model, 2), "w_hist": 0.0, "w_model": 1.0}
    if model is None:
        return {"score": round(hist, 2), "w_hist": 1.0, "w_model": 0.0}

    # 置信度越低，越依赖历史实绩；置信度越高，同口径模型权重略提高。
    w_model = float(np.clip(method_confidence, 0.2, 0.5))
    w_hist = 1.0 - w_model
    score = w_hist * hist + w_model * model
    return {
        "score": round(float(np.clip(score, 0.0, 10.0)), 2),
        "w_hist": round(w_hist, 2),
        "w_model": round(w_model, 2),
    }


def _build_pid_comparison_conclusion(
    *,
    baseline_pid: Dict[str, float],
    final_pid: Dict[str, Any],
    historical_score: Optional[Dict[str, float]],
    baseline_rating: Optional[Dict[str, Any]],
    baseline_reference_score: Optional[Dict[str, float]],
    final_score: Optional[float],
    final_confidence: float,
    kept_current_due_to_unidentifiable: bool,
    stable_margin: float = 0.5,
    stable_max_delta: float = 0.5,
) -> Dict[str, str]:
    """给现场验证脚本一个明确的下发/保持结论。"""
    if not baseline_pid:
        return {"decision": "无基线PID", "reason": "未读取到 current PID，只能输出新参数候选。"}
    if kept_current_due_to_unidentifiable:
        return {"decision": "建议保持当前PID", "reason": "本次模型不可辨识，已保护性回退为 current PID。"}

    hist = float((historical_score or {}).get("score", 0.0) or 0.0)
    baseline_final = None
    if baseline_rating and not baseline_rating.get("error"):
        baseline_final = float(baseline_rating.get("final_rating", baseline_rating.get("performance_score", 0.0)) or 0.0)
    baseline_ref = None
    if baseline_reference_score:
        baseline_ref = float(baseline_reference_score.get("score", 0.0) or 0.0)

    final_pb = float(final_pid.get("pb", final_pid.get("Pb", 0.0)) or 0.0)
    final_ti = float(final_pid.get("ti", final_pid.get("Ti", 0.0)) or 0.0)
    final_td = float(final_pid.get("td", final_pid.get("Td", 0.0)) or 0.0)
    old_pb = float(baseline_pid.get("pb", 0.0) or 0.0)
    old_ti = float(baseline_pid.get("ti", 0.0) or 0.0)
    old_td = float(baseline_pid.get("td", 0.0) or 0.0)

    def _rel_change(new_v: float, old_v: float) -> float:
        if abs(old_v) <= 1e-9:
            return 0.0 if abs(new_v) <= 1e-9 else float("inf")
        return abs(new_v - old_v) / abs(old_v)

    pb_rel_change = _rel_change(final_pb, old_pb)
    ti_rel_change = _rel_change(final_ti, old_ti)
    td_rel_change = _rel_change(final_td, old_td)

    # 已经稳态的回路：必须有高可信模型和足够收益，才允许说“新参数更好”。
    if hist >= 8.0:
        if final_confidence < 0.55:
            return {
                "decision": "建议保持当前PID",
                "reason": f"历史实绩已稳定({hist:.2f}/10)，但辨识/方法置信度仅 {final_confidence:.2f}，新参数不能证明优于 current PID。",
            }
        if pb_rel_change > stable_max_delta or ti_rel_change > stable_max_delta:
            return {
                "decision": "建议保持当前PID",
                "reason": (
                    f"历史实绩已稳定({hist:.2f}/10)，新参数相对 current PID 变化过大"
                    f"(ΔPb={pb_rel_change*100:.1f}%, ΔTi={ti_rel_change*100:.1f}%, 阈值={stable_max_delta*100:.1f}%)，"
                    "不满足稳态进化约束。"
                ),
            }
        cmp_baseline = baseline_final if baseline_final is not None else baseline_ref
        if cmp_baseline is not None and final_score is not None and final_score < cmp_baseline + stable_margin:
            return {
                "decision": "建议保持当前PID",
                "reason": (
                    f"新参数提升不足(baseline={cmp_baseline:.2f}, new={final_score:.2f}, "
                    f"要求提升≥{stable_margin:.2f})，不建议替换已稳定参数。"
                ),
            }
        return {
            "decision": "新参数可作为候选",
            "reason": (
                f"历史实绩稳定且满足进步判据(提升≥{stable_margin:.2f}, "
                f"ΔPb={pb_rel_change*100:.1f}%, ΔTi={ti_rel_change*100:.1f}%, ΔTd={td_rel_change*100:.1f}%)。"
            ),
        }

    # 非稳态回路：历史实绩差时，更关注新参数是否能把闭环评分拉起来。
    if final_score is not None and final_score >= 6.0 and final_confidence >= 0.45:
        return {"decision": "新参数可作为候选", "reason": "历史实绩不佳或一般，新参数模型评分达到可用区间。"}
    return {"decision": "不建议下发", "reason": "历史实绩不佳，但新参数模型评分/置信度仍不足。"}


def run_tuning(
    loop_id: str,
    enable_grid_search: bool = False,
    window_h: float = 4.0,
    step_h: float = 1.0,
    raw_csv: Optional[str] = None,
    force_parse_raw: bool = False,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    blind_validate: bool = False,
    stable_evolve: bool = False,
    seed: Optional[int] = None,
    stable_margin: float = 0.5,
    stable_max_delta: float = 0.5,
):
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
        print(f"🎲 固定随机种子: {seed}")

    raw_csv_path: Optional[Path] = None
    if raw_csv:
        raw_csv_path = Path(raw_csv)
    elif DEFAULT_RAW_CSV.exists():
        raw_csv_path = DEFAULT_RAW_CSV

    cfg = resolve_loop_config(loop_id, raw_csv_path)
    device = cfg["device"]
    loop_type_from_tag = cfg.get("loop_type") or infer_loop_type(device)
    print(f"🧭 DCS位号识别: {device} -> loop_type={loop_type_from_tag}")
    current_pid_cfg = cfg.get("current_pid")
    history_data = maybe_load_history_data(cfg, raw_csv_path=raw_csv_path, force_parse_raw=force_parse_raw)

    # 对新原始 CSV 设备：若未显式配置 current_pid，则自动从 PB/TI/TD 列提取
    if not current_pid_cfg and raw_csv_path and raw_csv_path.exists():
        auto_pid = extract_current_pid_from_raw_csv(raw_csv_path, device)
        if auto_pid:
            current_pid_cfg = auto_pid
            print(f"🧭 自动读取当前PID: Pb={auto_pid.get('pb', 0.0):.1f}%, Ti={auto_pid.get('ti', 0.0):.1f}s, Td={auto_pid.get('td', 0.0):.1f}s")
    if blind_validate and stable_evolve:
        print("⚠️ 同时指定了 --blind-validate 与 --stable-evolve，已自动采用 --stable-evolve（稳态进化必须依赖 current PID 作为基线）。")
    use_current_pid_in_tuning = stable_evolve or (not blind_validate)
    if blind_validate and not stable_evolve:
        print("🧪 盲整定验证模式: 整定过程不使用 current_pid，仅用于结果对比")
    if stable_evolve:
        print("🧬 稳态进化模式: 以 current PID 为基线做保守优化，仅当可证明更优才放行")
        print(f"   ↳ 进步判据: 评分提升≥{stable_margin:.2f}, 且 ΔPb/ΔTi ≤ {stable_max_delta*100:.1f}%")
    effective_current_pid_cfg = current_pid_cfg if use_current_pid_in_tuning else None

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
                'current_pid': effective_current_pid_cfg
            }
            # 使用统一的 tuning_context
            from core.models import SemanticProvider
            provider = SemanticProvider()
            tuning_context = provider.get_tuning_context(device)
            tuning_context['exact_window'] = enable_grid_search
            if not use_current_pid_in_tuning:
                tuning_context['disable_current_pid_in_tuning'] = True
                tuning_context.pop('current_pid', None)
            
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
        detect_res = find_high_variability_periods({
            "history_data": sliced_data,
            "params": {"loop_type": loop_type_from_tag},
        })
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
        'current_pid': effective_current_pid_cfg
    }
    
    t0 = time.time()
    
    # [NEW] 使用 SemanticProvider 获取完整的 OS 领域原子模型
    from core.models import SemanticProvider
    provider = SemanticProvider()
    tuning_context = provider.get_tuning_context(device)
    tuning_context['loop_type'] = loop_type_from_tag
    tuning_context['loop_type_source'] = 'dcs_tag'
    tuning_context['exact_window'] = enable_grid_search  # 补充运行时的控制标志
    if not use_current_pid_in_tuning:
        tuning_context['disable_current_pid_in_tuning'] = True
        tuning_context.pop('current_pid', None)

    baseline_pid = _normalize_pid_dict(current_pid_cfg or tuning_context.get("current_pid"))
    
    orchestrator_final = TuningOrchestrator(
        verbose=True, 
        process_context=tuning_context
    )
    result = orchestrator_final.run(input_data_final)
    t1 = time.time()
    
    print(f"\n⏱️ 最终模式执行耗时: {t1 - t0:.2f} 秒")

    # 可辨识性失败保护：避免输出默认兜底参数(Kp=1/Ti=20)误导现场
    kept_current_due_to_unidentifiable = False
    if not result.get("success", True) and baseline_pid:
        print("⚠️ 可辨识性不足：本次未得到有效模型参数，最终参数回退为当前PID（保护输出）")
        result["pid_parameters"] = _baseline_to_pid_params(baseline_pid)
        result.setdefault("tuning_features", {})
        result["tuning_features"]["tuning_method"] = "keep_current_not_identifiable"
        kept_current_due_to_unidentifiable = True
    
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
    historical_score = _evaluate_historical_operating_score(sliced_data)
    baseline_model_rating = _evaluate_pid_against_result_model(
        result,
        baseline_pid,
        loop_type_from_tag,
        confidence=float(conf_score or 0.0) if not kept_current_due_to_unidentifiable else None,
    )
    baseline_reference_score = _synthesize_baseline_reference_score(
        historical_score=historical_score,
        baseline_model_rating=baseline_model_rating,
        method_confidence=float(conf_score or 0.0),
    )
    comparison_conclusion = _build_pid_comparison_conclusion(
        baseline_pid=baseline_pid,
        final_pid=final_pid,
        historical_score=historical_score,
        baseline_rating=baseline_model_rating,
        baseline_reference_score=baseline_reference_score,
        final_score=None if kept_current_due_to_unidentifiable else float(final_score or 0.0),
        final_confidence=float(conf_score or 0.0),
        kept_current_due_to_unidentifiable=kept_current_due_to_unidentifiable,
        stable_margin=float(stable_margin),
        stable_max_delta=float(stable_max_delta),
    )

    kept_current_due_to_stable_evolve_guard = False
    if stable_evolve and baseline_pid and not kept_current_due_to_unidentifiable:
        allow_new = comparison_conclusion.get("decision") == "新参数可作为候选"
        if not allow_new:
            kept_current_due_to_stable_evolve_guard = True
            print("⚠️ 稳态进化护栏：新参数未通过“优于 current PID”判据，最终回退为当前PID。")
            result["pid_parameters"] = _baseline_to_pid_params(baseline_pid)
            result["pid_parameters"]["method"] = "keep_current_stable_guard"
            result.setdefault("tuning_features", {})
            result["tuning_features"]["tuning_method"] = "keep_current_stable_guard"
            final_pid = result["pid_parameters"]
            if baseline_model_rating and not baseline_model_rating.get("error"):
                result["model_rating"] = float(baseline_model_rating.get("final_rating", result.get("model_rating", 0.0)) or 0.0)
                result["rating_details"] = {
                    "performance_score": float(baseline_model_rating.get("performance_score", 0.0) or 0.0),
                    "method_confidence": float(baseline_model_rating.get("method_confidence", conf_score or 0.0) or 0.0),
                    "final_rating": float(baseline_model_rating.get("final_rating", 0.0) or 0.0),
                }
                final_score = result["model_rating"]
            comparison_conclusion = {
                "decision": "建议保持当前PID",
                "reason": "稳态进化护栏生效：本次未能可靠证明新参数优于当前稳态参数。",
            }

    # 护栏可能重写了 rating_details，这里统一刷新，避免榜单数字不一致。
    rating_details = result.get('rating_details', {})
    perf_score = float(rating_details.get('performance_score', perf_score) or 0.0)
    conf_score = float(rating_details.get('method_confidence', conf_score) or 0.0)
    
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
        if baseline_model_rating and not baseline_model_rating.get("error"):
            print(
                f"   🧭 当前PID模型评分: {baseline_model_rating.get('final_rating', 0.0):.2f} "
                f"(性能={baseline_model_rating.get('performance_score', 0.0):.2f}, "
                f"置信={baseline_model_rating.get('method_confidence', 0.0):.2f})"
            )
        else:
            print("   🧭 当前PID模型评分: N/A（模型不可辨识，无法同口径仿真评分）")
        if baseline_reference_score:
            print(
                f"   🧭 当前PID综合参考: {baseline_reference_score.get('score', 0.0):.2f} / 10 "
                f"(历史{baseline_reference_score.get('w_hist', 0.0):.2f} + 同口径{baseline_reference_score.get('w_model', 0.0):.2f})"
            )
    else:
        print("   🧭 当前PID(基线)  : N/A (未提供)")
    if historical_score:
        print(
            f"   📈 历史实绩评分  : {historical_score['score']:.2f} / 10 "
            f"(MAE={historical_score['mae_pct']:.3f}%, P95={historical_score['p95_pct']:.3f}%, "
            f"PV波动={historical_score['pv_std_pct']:.3f}%, MV抖动={historical_score['mv_jitter_pct']:.3f}%)"
        )

    if kept_current_due_to_unidentifiable:
        print("   🏆 综合性能评分 : N/A（可辨识性不足，未评分）")
        print("      ├─ 闭环性能评分 : N/A")
        print("      └─ 方法置信度   : N/A")
    else:
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
    if comparison_conclusion:
        print(f"   🧾 对比结论       : {comparison_conclusion.get('decision', '')}")
        print(f"      原因           : {comparison_conclusion.get('reason', '')}")
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
    compact_result["rating_status"] = (
        "not_identifiable_unscored" if kept_current_due_to_unidentifiable else "scored"
    )
    compact_result["baseline_pid"] = baseline_pid or {}
    compact_result["baseline_pid_model_rating"] = baseline_model_rating or {}
    compact_result["baseline_reference_score"] = baseline_reference_score or {}
    compact_result["historical_operating_score"] = historical_score or {}
    compact_result["comparison_conclusion"] = comparison_conclusion or {}
    compact_result["stable_evolve_guard_applied"] = bool(kept_current_due_to_stable_evolve_guard)
    compact_result["stable_evolve_policy"] = {
        "stable_margin": float(stable_margin),
        "stable_max_delta": float(stable_max_delta),
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
    parser.add_argument("--raw-csv", default=None, help="原始CSV路径(首行列名、第二行为中文描述)。示例: data/20260416.csv")
    parser.add_argument("--parse-raw", action="store_true", help="强制从原始CSV重新解析并覆盖对应的 [device].json")
    parser.add_argument("--list-devices", action="store_true", help="仅列出原始CSV中可用设备位号后退出")
    parser.add_argument("--start-time", default=None, help="可选，覆盖截取起始时间。格式: YYYY-mm-dd HH:MM:SS")
    parser.add_argument("--end-time", default=None, help="可选，覆盖截取结束时间。格式: YYYY-mm-dd HH:MM:SS")
    parser.add_argument("--mode", choices=["benchmark", "auto_pipeline"], default="benchmark",
                        help="运行模式: 'benchmark' 为多线程并发测分压测仪，'auto_pipeline' 为模拟真实后端全自动智能流转。")
    parser.add_argument("--window", type=float, default=6.0, help="滑窗寻优模式下的满窗长度(小时), 默认 6.0")
    parser.add_argument("--step", type=float, default=2.0, help="滑窗寻优模式下每次移动的步长(小时), 改大可提速, 默认 2.0")
    parser.add_argument(
        "--scenario",
        choices=["unstable", "stable_evolve"],
        default=None,
        help="业务目标场景：unstable=非稳态调稳(盲整定)；stable_evolve=已稳态进化(参考current_pid且需证明更优)",
    )
    parser.add_argument("--blind-validate", action="store_true", help="盲整定验证：整定过程不使用 current_pid，仅用于结果对比")
    parser.add_argument("--stable-evolve", action="store_true", help="稳态进化验证：以 current PID 为基线保守优化，仅当可证明更优才放行")
    parser.add_argument("--stable-margin", type=float, default=0.5, help="稳态进化最低提升分数阈值(默认 0.5)")
    parser.add_argument("--stable-max-delta", type=float, default=0.5, help="稳态进化时 Pb/Ti 最大允许相对变化(默认 0.5=50%%)")
    parser.add_argument("--seed", type=int, default=None, help="固定随机种子，保证复现性（例如: 42）")
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

    blind_validate = args.blind_validate
    stable_evolve = args.stable_evolve
    if args.scenario is not None:
        if args.scenario == "unstable":
            blind_validate, stable_evolve = True, False
            print("🎯 场景目标: 非稳态调稳 (scenario=unstable)")
        elif args.scenario == "stable_evolve":
            blind_validate, stable_evolve = False, True
            print("🎯 场景目标: 已稳态进化 (scenario=stable_evolve)")
    
    run_tuning(
        TARGET_LOOP,
        enable_grid_search=ENABLE_GRID_SEARCH,
        window_h=args.window,
        step_h=args.step,
        raw_csv=args.raw_csv,
        force_parse_raw=args.parse_raw,
        start_time=args.start_time,
        end_time=args.end_time,
        blind_validate=blind_validate,
        stable_evolve=stable_evolve,
        seed=args.seed,
        stable_margin=max(0.0, float(args.stable_margin)),
        stable_max_delta=max(0.0, float(args.stable_max_delta)),
    )
