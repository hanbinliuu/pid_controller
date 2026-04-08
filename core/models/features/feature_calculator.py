"""
特征计算工具包 (Feature Calculator)
=====================================

本模块将 PID Agent 内部的表征特征计算逻辑**抽离**为独立工具包，
供 OS 中台团队参考实现 `GET /api/v1/characterization/{device_id}` 接口。

设计原则
--------
- **零依赖**: 仅依赖 numpy / scipy，无任何 PID Agent 内部模块引用
- **纯函数**: 所有函数均为无副作用的纯函数，输入 ndarray 输出 float/dict
- **按需计算**: 整定触发时调用，计算最近 1-2 天历史数据
- **直接映射**: 每个函数对应 CharacterizationModel 中的一个字段

使用方式
--------
OS 中台收到整定触发请求后：

    from feature_calculator import calculate_characterization

    result = calculate_characterization(
        device_id="2216_LIC_50104",
        pv=pv_array,
        mv=mv_array,
        timestamps=ts_array,    # Unix 时间戳数组（秒）
        sample_interval_s=5.0   # 采样周期（秒），若为 None 则自动估算
    )
    # result 是 CharacterizationModel 实例，可直接用 result.to_dict() 序列化

对应关系（算法源码 → 本文件）
------------------------------
| CharacterizationModel 字段         | 原始来源                                          |
|------------------------------------|---------------------------------------------------|
| signal.oscillation_ratio           | DataPreprocessor._calculate_oscillation_ratio     |
| signal.noise_level                 | DataPreprocessor._calculate_noise_ratio           |
| signal.linearity_index             | 1 - DataPreprocessor._calculate_nonlinearity      |
| signal.dominant_period_s           | 新实现（自相关法估算主振荡周期）                  |
| valve.stiction_index_estimated     | 综合 trend_consistency + correlation 推算         |
| valve.deadband_estimated           | MV 微小变化但 PV 无响应区间占比                   |
| valve.reversal_error               | MV 反向切换时 PV 响应滞后估算                     |
| performance.recent_step_events     | SegmentProcessor._detect_mv_steps 计数逻辑        |
| performance.auto_mode_time_ratio   | 需由 OS 中台从 DCS 历史库统计（本文件不计算）     |
| performance.performance_score_avg  | 综合质量评分（noise/oscillation/linearity）        |
"""

from __future__ import annotations

import datetime
import numpy as np
from typing import Optional, Tuple, Dict, Any

# 仅在本模块顶层引用，OS 中台可直接复制此文件并去除该 import
# 改为直接返回 dict，避免依赖 CharacterizationModel dataclass
try:
    from ..schemas.characterization_model import (
        CharacterizationModel,
        SignalCharacteristics,
        ValveCharacteristics,
        ControlPerformance,
    )
    _HAS_MODEL = True
except ImportError:
    _HAS_MODEL = False

_EPSILON = 1e-9


# ============================================================
# 1. 振荡比例
# ============================================================

def calculate_oscillation_ratio(pv: np.ndarray) -> float:
    """
    计算 PV 振荡比例（0-1）。

    定义：PV 时序导数符号反转次数占总采样点比例，
    反映回路的振荡剧烈程度。0 表示单调无振荡，1 表示完全振荡。

    原始来源: DataPreprocessor._calculate_oscillation_ratio (data_preprocessor.py:675)

    Args:
        pv: PV 数据一维数组

    Returns:
        振荡比例 in [0, 1]
    """
    if len(pv) < 5:
        return 0.0
    try:
        pv_diff = np.diff(pv)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        ratio = sign_changes / (len(pv) - 2) if len(pv) > 2 else 0.0
        return float(min(ratio, 1.0))
    except Exception:
        return 0.0


# ============================================================
# 2. 噪声水平
# ============================================================

def calculate_noise_level(pv: np.ndarray) -> float:
    """
    计算 PV 高频噪声强度（0-1）。

    定义：移动平均平滑后的残差标准差 / PV 量程，
    量化高频测量噪声占信号量程的比例。

    原始来源: DataPreprocessor._calculate_noise_ratio (data_preprocessor.py:428)

    Args:
        pv: PV 数据一维数组

    Returns:
        噪声水平 in [0, 1)
    """
    if len(pv) < 5:
        return 0.0
    try:
        window = min(5, len(pv))
        # 移动平均（等价于 uniform_filter1d）
        kernel = np.ones(window) / window
        pv_smooth = np.convolve(pv, kernel, mode='same')
        noise_std = float(np.std(pv - pv_smooth))
        pv_range = float(np.ptp(pv))
        if pv_range < _EPSILON:
            return 0.0
        return float(min(noise_std / pv_range, 1.0))
    except Exception:
        return 0.0


# ============================================================
# 3. 线性度指标
# ============================================================

def calculate_linearity_index(pv: np.ndarray, mv: np.ndarray) -> float:
    """
    计算回路线性度指标（0-1），越接近 1 越线性。

    定义：1 - 非线性程度。非线性程度通过分段增益一致性 + 线性拟合残差相关性综合评估。

    原始来源: 1 - DataPreprocessor._calculate_nonlinearity (data_preprocessor.py:510)

    Args:
        pv: PV 数据一维数组
        mv: MV 数据一维数组

    Returns:
        线性度指标 in [0, 1]，1 = 完全线性
    """
    if len(pv) < 30 or len(mv) < 30:
        return 1.0  # 数据不足，保守返回线性
    try:
        n = len(pv)
        scores = []

        # 方法1：分段增益一致性
        n_segments = min(4, n // 20)
        if n_segments >= 2:
            segment_size = n // n_segments
            gains = []
            for i in range(n_segments):
                start = i * segment_size
                end = start + segment_size if i < n_segments - 1 else n
                dy = pv[end - 1] - pv[start]
                du = mv[end - 1] - mv[start]
                if abs(du) > _EPSILON:
                    gains.append(dy / du)
            if len(gains) >= 2:
                gains_mean = float(np.mean(gains))
                gains_std = float(np.std(gains))
                if abs(gains_mean) > _EPSILON:
                    gain_cv = abs(gains_std / gains_mean)
                    scores.append(min(gain_cv, 1.0))

        # 方法2：线性拟合残差与 MV 的相关性
        try:
            A = np.vstack([mv, np.ones(len(mv))]).T
            coeffs, _, _, _ = np.linalg.lstsq(A, pv, rcond=None)
            pv_linear = mv * coeffs[0] + coeffs[1]
            residual = pv - pv_linear
            if len(residual) > 5:
                corr = np.corrcoef(residual, mv)[0, 1]
                if not np.isnan(corr):
                    scores.append(min(abs(corr), 1.0))
        except Exception:
            pass

        nonlinearity = float(np.mean(scores)) if scores else 0.0
        return float(max(0.0, 1.0 - nonlinearity))
    except Exception:
        return 1.0


# ============================================================
# 4. 主振荡周期
# ============================================================

def calculate_dominant_period_s(
    pv: np.ndarray,
    timestamps: np.ndarray,
) -> float:
    """
    估计 PV 主振荡周期（秒）。

    方法：对去趋势后的 PV 做自相关，找第一个正峰值对应的 lag，
    换算为以秒为单位的周期。若无明显振荡则返回 0.0。

    原始来源: 新实现（算法内部未有独立函数）

    Args:
        pv:         PV 数据一维数组（等间距采样）
        timestamps: 对应 Unix 时间戳数组（秒）

    Returns:
        主振荡周期（秒），0.0 表示无明显振荡
    """
    if len(pv) < 20 or len(timestamps) < 2:
        return 0.0
    try:
        # 估算采样间隔
        dt = float(np.median(np.diff(timestamps)))
        if dt <= 0:
            return 0.0

        # 去趋势
        pv_detrended = pv - np.linspace(pv[0], pv[-1], len(pv))

        # 自相关
        auto_corr = np.correlate(pv_detrended, pv_detrended, mode='full')
        auto_corr = auto_corr[len(auto_corr) // 2:]  # 取正 lag 部分
        auto_corr /= auto_corr[0] + _EPSILON  # 归一化

        # 在 lag=1 之后找第一个正峰值
        min_lag = max(3, int(5 / dt))    # 至少 5 秒
        max_lag = min(len(auto_corr) - 1, int(len(pv) * 0.5))

        if min_lag >= max_lag:
            return 0.0

        segment = auto_corr[min_lag:max_lag]
        if len(segment) < 3:
            return 0.0

        # 找局部极大值
        peaks = []
        for i in range(1, len(segment) - 1):
            if segment[i] > segment[i - 1] and segment[i] > segment[i + 1] and segment[i] > 0.1:
                peaks.append((i + min_lag, segment[i]))

        if not peaks:
            return 0.0

        # 取第一个正峰值
        first_peak_lag = peaks[0][0]
        period_s = first_peak_lag * dt
        return float(period_s)
    except Exception:
        return 0.0


# ============================================================
# 5. 阀门卡涩指数
# ============================================================

def calculate_stiction_index(pv: np.ndarray, mv: np.ndarray) -> float:
    """
    估计阀门卡涩/粘滞指数（0-1）。

    方法：检测 MV 发生微小连续变化但 PV 无响应的区间占比，
    结合 MV-PV 趋势一致性综合判断。

    原始来源:
        综合 DataPreprocessor._calculate_trend_consistency (data_preprocessor.py:469)
        + DataPreprocessor._calculate_correlation (data_preprocessor.py:442)

    Args:
        pv: PV 数据一维数组
        mv: MV 数据一维数组

    Returns:
        卡涩指数 in [0, 1]，0 = 顺滑，1 = 严重卡涩
    """
    if len(pv) < 20 or len(mv) < 20:
        return 0.0
    try:
        scores = []

        # 指标1：趋势一致性（同向运动）
        dy = np.diff(pv)
        du = np.diff(mv)
        threshold = 0.01 * max(float(np.ptp(pv)), _EPSILON)
        valid_mask = np.abs(dy) > threshold
        if np.sum(valid_mask) >= 3:
            dy_v = dy[valid_mask]
            du_v = du[valid_mask]
            same_sign = np.sum(np.sign(dy_v) == np.sign(du_v))
            opp_sign = np.sum(np.sign(dy_v) == -np.sign(du_v))
            consistency = float(max(same_sign, opp_sign)) / len(dy_v)
            # 一致性低（< 0.6）意味着 MV 动、PV 不动或乱动 → 卡涩
            stiction_from_consistency = max(0.0, 1.0 - consistency / 0.6) if consistency < 0.6 else 0.0
            scores.append(stiction_from_consistency)

        # 指标2：MV 有变化但 PV 无响应的窗口比例
        window = max(10, len(pv) // 20)
        stiction_windows = 0
        total_windows = 0
        for i in range(0, len(pv) - window, window // 2):
            mv_seg = mv[i:i + window]
            pv_seg = pv[i:i + window]
            mv_range = float(np.ptp(mv_seg))
            pv_range = float(np.ptp(pv_seg))
            if mv_range > 1.0:  # MV 有明显变化（> 1%量程）
                total_windows += 1
                if pv_range < 0.2 * mv_range:  # PV 几乎不动
                    stiction_windows += 1
        if total_windows > 0:
            scores.append(stiction_windows / total_windows)

        return float(np.mean(scores)) if scores else 0.0
    except Exception:
        return 0.0


# ============================================================
# 6. 阀门死区估计
# ============================================================

def calculate_deadband_estimated(mv: np.ndarray, pv: np.ndarray) -> float:
    """
    估计阀门死区（%）。

    方法：检测 MV 反向切换时，需要多大的反向幅度才能让 PV 开始响应，
    取所有反向切换事件的中位数作为死区估计。

    Args:
        mv: MV 数据一维数组
        pv: PV 数据一维数组

    Returns:
        死区估计（%，相对于 MV 量程），-1 表示无法估计
    """
    if len(mv) < 40 or len(pv) < 40:
        return 0.0
    try:
        mv_range = float(np.ptp(mv))
        if mv_range < _EPSILON:
            return 0.0

        du = np.diff(mv)
        # 找方向反转点
        direction_changes = []
        prev_dir = 0
        for i, d in enumerate(du):
            if abs(d) < mv_range * 0.005:  # 忽略微小变化
                continue
            cur_dir = 1 if d > 0 else -1
            if prev_dir != 0 and cur_dir != prev_dir:
                direction_changes.append(i + 1)
            prev_dir = cur_dir

        if not direction_changes:
            return 0.0

        # 对每个反转点估计死区
        deadbands = []
        pv_range = float(np.ptp(pv))
        for idx in direction_changes:
            # 找此反转后 PV 开始响应的点
            look_ahead = min(30, len(pv) - idx - 1)
            if look_ahead <= 0:
                continue
            pv_before = pv[max(0, idx - 5):idx]
            pv_base = float(np.mean(pv_before)) if len(pv_before) > 0 else pv[idx]
            mv_at_reversal = mv[idx]
            moved = False
            for j in range(idx, idx + look_ahead):
                if abs(pv[j] - pv_base) > pv_range * 0.01:  # PV 开始动了
                    # 死区 = MV 从反转点到 PV 响应时，MV 走过的距离
                    db = abs(mv[j] - mv_at_reversal) / mv_range * 100
                    deadbands.append(db)
                    moved = True
                    break
            if not moved:
                deadbands.append(look_ahead / len(mv) * mv_range)

        if not deadbands:
            return 0.0
        return float(np.median(deadbands))
    except Exception:
        return 0.0


# ============================================================
# 7. 回程误差
# ============================================================

def calculate_reversal_error(mv: np.ndarray, pv: np.ndarray) -> float:
    """
    计算回程误差（Hysteresis）估计值（0-1，相对于 PV 量程）。

    方法：在 MV 正向和负向变化段，分别统计 PV 的平均响应增益，
    回程误差 = |正向增益 - 负向增益| / max(|正向增益|, |负向增益|)。

    Args:
        mv: MV 数据一维数组
        pv: PV 数据一维数组

    Returns:
        回程误差 in [0, 1]
    """
    if len(mv) < 30 or len(pv) < 30:
        return 0.0
    try:
        du = np.diff(mv)
        dp = np.diff(pv)

        pos_gains = []
        neg_gains = []
        for d_u, d_p in zip(du, dp):
            if abs(d_u) < _EPSILON:
                continue
            g = d_p / d_u
            if d_u > 0:
                pos_gains.append(g)
            else:
                neg_gains.append(g)

        if not pos_gains or not neg_gains:
            return 0.0

        g_pos = float(np.median(pos_gains))
        g_neg = float(np.median(neg_gains))
        denom = max(abs(g_pos), abs(g_neg))
        if denom < _EPSILON:
            return 0.0
        return float(min(abs(g_pos - g_neg) / denom, 1.0))
    except Exception:
        return 0.0


# ============================================================
# 8. 近期阶跃事件数
# ============================================================

def calculate_recent_step_events(
    mv: np.ndarray,
    timestamps: np.ndarray,
    min_step_pct: float = 0.05,
) -> int:
    """
    统计近期有效 MV 阶跃事件次数。

    定义：MV 在稳定窗口后发生 >= min_step_pct * MV量程 的一次性变化，
    记为一次有效阶跃事件。

    原始来源: SegmentProcessor._detect_mv_steps (segment_processor.py:679)

    Args:
        mv:             MV 数据一维数组
        timestamps:     对应 Unix 时间戳数组（秒）
        min_step_pct:   最小阶跃幅度（相对 MV 量程，默认 5%）

    Returns:
        有效阶跃事件次数
    """
    if len(mv) < 20:
        return 0
    try:
        mv_range = float(np.ptp(mv))
        if mv_range < _EPSILON:
            return 0
        min_step = min_step_pct * mv_range
        stable_window = max(10, len(mv) // 50)

        n = len(mv)
        steps = []
        i = stable_window

        while i < n - stable_window:
            before = mv[max(0, i - stable_window):i]
            after = mv[i:min(n, i + stable_window)]
            before_std = float(np.std(before))
            step_size = float(np.mean(after) - np.mean(before))
            if abs(step_size) >= min_step and before_std < abs(step_size) * 0.3:
                steps.append(i)
                i += stable_window * 2
            else:
                i += 1

        return len(steps)
    except Exception:
        return 0


# ============================================================
# 9. 综合控制性能评分
# ============================================================

def calculate_performance_score(
    pv: np.ndarray,
    mv: np.ndarray,
) -> float:
    """
    计算综合控制性能评分（0-10）。

    加权公式（与 DataQuality.quality_score property 对齐）：
        score = 10 × (
            0.25 × |correlation|
          + 0.20 × (1 - noise_level)
          + 0.20 × linearity_index
          + 0.20 × (1 - oscillation_ratio)
          + 0.15 × step_response_score
        )

    其中 step_response_score 用收敛性近似：后 1/3 标准差 / 前 1/2 标准差的反比。

    Args:
        pv: PV 数据一维数组
        mv: MV 数据一维数组

    Returns:
        性能评分 in [0, 10]
    """
    if len(pv) < 10:
        return 5.0
    try:
        # correlation
        corr = 0.0
        try:
            c = np.corrcoef(mv, pv)[0, 1]
            corr = 0.0 if np.isnan(c) else float(abs(c))
        except Exception:
            pass

        noise = calculate_noise_level(pv)
        osc = calculate_oscillation_ratio(pv)
        linearity = calculate_linearity_index(pv, mv)

        # 收敛性
        n = len(pv)
        step_score = 0.5
        last_third = pv[int(n * 2 / 3):]
        first_half = pv[:int(n * 0.5)]
        if len(last_third) > 5 and len(first_half) > 5:
            std_last = float(np.std(last_third))
            std_first = float(np.std(first_half))
            if std_first > _EPSILON:
                ratio = std_last / std_first
                step_score = 1.0 if ratio < 0.5 else (0.7 if ratio < 1.0 else 0.3)

        raw = (
            0.25 * corr
            + 0.20 * (1 - noise)
            + 0.20 * linearity
            + 0.20 * (1 - osc)
            + 0.15 * step_score
        )
        return float(min(max(raw * 10, 0.0), 10.0))
    except Exception:
        return 5.0


# ============================================================
# 10. 主入口：计算完整 CharacterizationModel
# ============================================================

def calculate_characterization(
    device_id: str,
    pv: np.ndarray,
    mv: np.ndarray,
    timestamps: np.ndarray,
    sample_interval_s: Optional[float] = None,
) -> "CharacterizationModel":
    """
    基于最近 1-2 天历史数据，按需计算完整 CharacterizationModel。

    这是交付给 OS 中台的**核心入口函数**。
    OS 中台在收到 `GET /api/v1/characterization/{device_id}?hours=48` 请求后：
    1. 从历史库拉取 device_id 最近 48h 的 pv/mv/timestamps 数据
    2. 调用本函数计算
    3. 将结果序列化为 JSON 返回

    Args:
        device_id:          设备标识符
        pv:                 PV 数据一维数组（时序顺序）
        mv:                 MV 数据一维数组（时序顺序）
        timestamps:         对应 Unix 时间戳数组（秒）
        sample_interval_s:  采样周期（秒），传 None 则自动从 timestamps 估算

    Returns:
        CharacterizationModel 实例（若未安装 characterization_model 模块则返回 dict）
    """
    pv = np.asarray(pv, dtype=float)
    mv = np.asarray(mv, dtype=float)
    timestamps = np.asarray(timestamps, dtype=float)

    # 过滤 NaN/Inf
    valid = np.isfinite(pv) & np.isfinite(mv)
    pv, mv, timestamps = pv[valid], mv[valid], timestamps[valid]

    now_iso = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    # --- 信号表征 ---
    osc_ratio = calculate_oscillation_ratio(pv)
    noise = calculate_noise_level(pv)
    linearity = calculate_linearity_index(pv, mv)
    dominant_period = calculate_dominant_period_s(pv, timestamps)

    # --- 阀门表征 ---
    stiction = calculate_stiction_index(pv, mv)
    deadband = calculate_deadband_estimated(mv, pv)
    reversal = calculate_reversal_error(mv, pv)

    # --- 控制绩效 ---
    perf_score = calculate_performance_score(pv, mv)
    step_events = calculate_recent_step_events(mv, timestamps)

    result_dict: Dict[str, Any] = {
        'device_id': device_id,
        'timestamp': now_iso,
        'signal': {
            'oscillation_ratio': round(osc_ratio, 4),
            'dominant_period_s': round(dominant_period, 2),
            'noise_level': round(noise, 4),
            'linearity_index': round(linearity, 4),
        },
        'valve': {
            'stiction_index_estimated': round(stiction, 4),
            'deadband_estimated': round(deadband, 4),
            'reversal_error': round(reversal, 4),
        },
        'performance': {
            'performance_score_avg': round(perf_score, 2),
            'auto_mode_time_ratio': 1.0,    # OS 中台从 DCS 历史库统计
            'intervention_count_daily': 0,   # OS 中台从操作日志统计
            'recent_step_events': step_events,
        },
        'llm_extra_features': {},
    }

    if _HAS_MODEL:
        return CharacterizationModel.from_dict(result_dict)
    return result_dict  # type: ignore[return-value]


def calculate_characterization_as_dict(
    device_id: str,
    pv: np.ndarray,
    mv: np.ndarray,
    timestamps: np.ndarray,
    sample_interval_s: Optional[float] = None,
) -> Dict[str, Any]:
    """
    与 calculate_characterization 相同，但始终返回 dict（供 OS 中台 REST 接口直接序列化）。
    """
    result = calculate_characterization(device_id, pv, mv, timestamps, sample_interval_s)
    if isinstance(result, dict):
        return result
    return result.to_dict()  # type: ignore[union-attr]
