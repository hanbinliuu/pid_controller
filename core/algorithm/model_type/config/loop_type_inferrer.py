"""
回路类型自动推断模块 (Loop Type Auto Inferrer)
================================================

提供两种推断方式：
1. infer_loop_type_from_data(): 早期推断，基于原始PV/MV时间序列特征
2. infer_loop_type(): 精确推断，基于模型参数(K, T1, L)和模型类型

推断规则（早期推断）：
- 长振荡周期(>60s) 或 PV变化极慢 → temperature（温度）
- 短振荡周期(<15s) 或 PV变化快速 → flow（流量）
- PV持续漂移/积分特征 → level（液位）
- 其余 → pressure（压力）

推断规则（精确推断）：
- 积分过程（FO_INTEGRATOR）→ level（液位）
- T1 > 30s 且有明显死区时间 → temperature（温度）
- T1 < 10s 且无积分特征 → flow（流量）
- 其余中速系统 → pressure（压力）

使用方式:
```python
from core.algorithm.model_type.config.loop_type_inferrer import infer_loop_type, infer_loop_type_from_data

# 早期推断（Step 0.5，基于原始数据）
loop_type, confidence, reason = infer_loop_type_from_data(pv, mv, timestamps)

# 精确推断（Step 4.6，基于模型参数）
loop_type, confidence, reason = infer_loop_type(
    model_params={'K': 0.63, 'T1': 8.9, 'T2': 0, 'L': 0},
    model_type='FO'
)
```
"""

import numpy as np
from typing import Tuple, Dict, Any, Optional


def infer_loop_type_from_data(
    pv: np.ndarray,
    mv: np.ndarray,
    timestamps: np.ndarray,
) -> Tuple[str, float, str]:
    """
    基于原始 PV/MV 时间序列特征推断回路类型（早期推断）

    适用于模型拟合之前，用数据特征做粗略分类。
    置信度通常低于基于模型参数的精确推断。

    Args:
        pv: PV 时间序列
        mv: MV 时间序列
        timestamps: 时间戳数组（毫秒）

    Returns:
        (loop_type, confidence, reason)
    """
    n = len(pv)
    if n < 20:
        return 'pressure', 0.3, '数据量不足，默认压力'

    # 计算采样间隔（秒）
    dt = np.median(np.diff(timestamps)) / 1000.0
    if dt <= 0:
        dt = 1.0

    # === 特征 1: PV 自相关衰减速率（估计响应速度） ===
    pv_centered = pv - np.mean(pv)
    pv_var = np.var(pv_centered)
    if pv_var > 1e-10:
        # 计算归一化自相关，找到衰减到 0.37 (1/e) 的时间
        max_lag = min(n // 2, int(600 / dt))  # 扩大搜索范围到600秒
        autocorr_decay_time = _estimate_autocorr_decay(pv_centered, max_lag, dt)
    else:
        autocorr_decay_time = 30.0  # PV 几乎不变，默认中速

    # === 特征 2: 主振荡周期 ===
    dominant_period = _estimate_dominant_period(pv_centered, dt, n)

    # === 特征 3: 积分特征检测 ===
    # 积分过程：PV 持续单方向漂移，与 MV 均值偏移方向一致
    has_integrating = _check_integrating_behavior(pv, mv, n)

    # === 特征 4: MV→PV 响应延迟 ===
    response_delay = _estimate_response_delay(pv_centered, mv - np.mean(mv), dt)

    # === 特征 5: PV 相对变化幅度（温度回路通常变化范围相对均值很小）===
    pv_mean = np.mean(pv)
    pv_range = np.max(pv) - np.min(pv)
    pv_relative_range = pv_range / (abs(pv_mean) + 1e-6) if abs(pv_mean) > 1e-6 else pv_range

    # === 推断逻辑 ===

    # 积分特征 → 液位 (优先判定)
    if has_integrating:
        confidence = 0.7  # 提高置信度
        reason = f'PV呈积分漂移特征(衰减时间={autocorr_decay_time:.0f}s)'
        return 'level', confidence, reason

    # 慢速系统 → 温度
    # 只要衰减慢或周期长，大概率是温度
    if autocorr_decay_time > 100 or dominant_period > 100:
        confidence = 0.75
        reason = f'慢速系统(自相关衰减={autocorr_decay_time:.0f}s'
        if dominant_period > 0:
            reason += f', 主周期={dominant_period:.0f}s'
        reason += ')'
        return 'temperature', confidence, reason

    if autocorr_decay_time > 50:
        if response_delay > 5:
            confidence = 0.7
            reason = f'中慢速+响应延迟(衰减={autocorr_decay_time:.0f}s, 延迟={response_delay:.0f}s)'
            return 'temperature', confidence, reason
    
    # [NEW] 中速但PV变化范围窄 → 可能是温度
    # 温度回路（如200°C）的PV波动通常只有几度，相对幅度<5%
    if autocorr_decay_time > 30 and pv_relative_range < 0.05 and response_delay > 2:
        confidence = 0.6
        reason = (f'中速窄幅变化(衰减={autocorr_decay_time:.0f}s, '
                  f'PV相对幅度={pv_relative_range:.1%}, 延迟={response_delay:.1f}s)')
        return 'temperature', confidence, reason

    # 快速系统 → 流量
    # 放宽流量判定：衰减快或周期短
    if autocorr_decay_time < 20 or (dominant_period > 0 and dominant_period < 20):
        confidence = 0.65
        reason = f'快速响应系统(衰减={autocorr_decay_time:.0f}s'
        if dominant_period > 0:
            reason += f', 周期={dominant_period:.0f}s'
        reason += ')'
        return 'flow', confidence, reason

    # 中速系统 → 压力 (默认)
    confidence = 0.4
    reason = f'中速系统(衰减={autocorr_decay_time:.0f}s'
    if dominant_period > 0:
        reason += f', 周期={dominant_period:.0f}s'
    reason += ')'
    if response_delay > 2:
        confidence += 0.1
        reason += f', 有延迟({response_delay:.1f}s)'

    return 'pressure', confidence, reason


def _estimate_autocorr_decay(signal: np.ndarray, max_lag: int, dt: float) -> float:
    """估计自相关衰减到 1/e 的时间"""
    n = len(signal)
    var = np.var(signal)
    if var < 1e-10:
        return 30.0

    threshold = np.exp(-1)  # 1/e ≈ 0.37
    for lag in range(1, min(max_lag, n)):
        if lag >= n:
            break
        autocorr = np.mean(signal[:n - lag] * signal[lag:]) / var
        if autocorr < threshold:
            return lag * dt

    return max_lag * dt  # 如果一直没衰减


def _estimate_dominant_period(signal: np.ndarray, dt: float, n: int) -> float:
    """估计主振荡周期（基于 FFT）"""
    if n < 64:
        return 30.0  # 数据太短

    # 去趋势
    detrended = signal - np.linspace(signal[0], signal[-1], n)

    # FFT
    fft_vals = np.abs(np.fft.rfft(detrended))
    freqs = np.fft.rfftfreq(n, d=dt)

    # 忽略直流分量和极低频
    min_freq = 1.0 / (n * dt * 0.5)  # 至少能看到半个周期
    valid = freqs > min_freq
    if not np.any(valid):
        return 30.0

    fft_valid = fft_vals[valid]
    freqs_valid = freqs[valid]

    # 找最大幅值对应的频率
    peak_idx = np.argmax(fft_valid)
    peak_freq = freqs_valid[peak_idx]

    if peak_freq > 1e-10:
        return 1.0 / peak_freq
    return 30.0


def _check_integrating_behavior(pv: np.ndarray, mv: np.ndarray, n: int) -> bool:
    """检测积分过程特征：PV 持续漂移"""
    if n < 100:
        return False

    # 把数据分成4段，看PV是否持续朝一个方向漂移
    quarter = n // 4
    means = [np.mean(pv[i * quarter:(i + 1) * quarter]) for i in range(4)]
    diffs = [means[i + 1] - means[i] for i in range(3)]

    # 全部同方向且幅度递增 → 疑似积分
    all_positive = all(d > 0 for d in diffs)
    all_negative = all(d < 0 for d in diffs)

    if not (all_positive or all_negative):
        return False

    # 漂移幅度要足够大（相对于PV范围）
    total_drift = abs(means[-1] - means[0])
    pv_range = np.max(pv) - np.min(pv)
    if pv_range > 1e-10 and total_drift / pv_range > 0.3:
        return True

    return False


def _estimate_response_delay(pv: np.ndarray, mv: np.ndarray, dt: float) -> float:
    """估计 MV→PV 的响应延迟（基于互相关）"""
    n = len(pv)
    max_lag = min(n // 4, int(120 / dt))  # 最多看120秒

    if max_lag < 2:
        return 0.0

    pv_std = np.std(pv)
    mv_std = np.std(mv)
    if pv_std < 1e-10 or mv_std < 1e-10:
        return 0.0

    # 计算互相关，找峰值位置
    best_corr = 0.0
    best_lag = 0
    for lag in range(0, max_lag, max(1, max_lag // 50)):
        if lag >= n:
            break
        corr = abs(np.mean(mv[:n - lag] * pv[lag:])) / (pv_std * mv_std)
        if corr > best_corr:
            best_corr = corr
            best_lag = lag

    return best_lag * dt


def infer_loop_type(
    model_params: Dict[str, float],
    model_type: str
) -> Tuple[str, float, str]:
    """
    根据模型参数和类型推断回路类型（精确推断）

    Args:
        model_params: 辨识出的模型参数
            - K: 过程增益
            - T1: 主时间常数
            - T2: 二阶时间常数（可选）
            - L: 纯滞后时间
        model_type: 辨识出的模型类型
            ('FO', 'FOPDT', 'SO', 'SOPDT', 'FO_INTEGRATOR' 等)

    Returns:
        (loop_type, confidence, reason) 三元组
        - loop_type: 推断的回路类型 ('flow', 'temperature', 'level', 'pressure')
        - confidence: 推断置信度 (0.0 ~ 1.0)
        - reason: 推断原因说明
    """
    K = abs(model_params.get('K', 0.0))
    T1 = model_params.get('T1', 0.0)
    T2 = model_params.get('T2', 0.0)
    L = model_params.get('L', 0.0)

    model_type_upper = model_type.upper() if model_type else ''

    # ========== 规则 1: 积分过程 → 液位 ==========
    # FO_INTEGRATOR 模型是积分过程的标志性特征
    if 'INTEGRATOR' in model_type_upper:
        confidence = 0.85
        reason = f'积分过程模型({model_type}), K={K:.4f}'
        return 'level', confidence, reason

    # 极小增益 + 持续漂移也暗示积分特征
    if K < 0.01 and T1 > 50:
        confidence = 0.6
        reason = f'疑似积分过程(K={K:.4f}, T1={T1:.1f}s)'
        return 'level', confidence, reason

    # ========== 规则 2: 大时间常数 → 温度 ==========
    # 温度回路特征：响应慢（T1>30s），常有死区时间
    if T1 > 60:
        confidence = 0.8
        reason = f'大时间常数系统(T1={T1:.1f}s)'
        if L > 5:
            confidence = 0.9
            reason += f', 明显滞后(L={L:.1f}s)'
        return 'temperature', confidence, reason

    if T1 > 30:
        if L > 3:
            confidence = 0.75
            reason = f'慢速+滞后系统(T1={T1:.1f}s, L={L:.1f}s)'
            return 'temperature', confidence, reason
        # T1在30~60之间但无明显滞后，可能是温度也可能是压力
        # 用二阶特征辅助判断（温度系统更可能表现为二阶）
        if T2 > 5 or 'SO' in model_type_upper:
            confidence = 0.65
            reason = f'中慢速二阶系统(T1={T1:.1f}s, T2={T2:.1f}s)'
            return 'temperature', confidence, reason

    # [NEW] T1 > 20s 且增益较小 → 倾向温度
    # 温度回路闭环辨识后 T1 通常在 10~30s（开环更长），增益通常 < 1.0
    if T1 > 20 and K < 1.0:
        confidence = 0.6
        reason = f'中慢速低增益系统(T1={T1:.1f}s, K={K:.3f})'
        if L > 1:
            confidence = 0.65
            reason += f', 有滞后(L={L:.1f}s)'
        return 'temperature', confidence, reason

    # ========== 规则 3: 快速响应 → 流量 ==========
    # 流量回路特征：响应快（T1<10s），通常无积分特征
    if T1 < 5:
        confidence = 0.8
        reason = f'快速响应系统(T1={T1:.1f}s)'
        if L < 1:
            confidence = 0.85
            reason += ', 几乎无滞后'
        return 'flow', confidence, reason

    if T1 < 10:
        confidence = 0.7
        reason = f'较快响应系统(T1={T1:.1f}s)'
        # 如果有明显滞后，可能是压力而非流量
        if L > 3:
            confidence = 0.5
            reason = f'快速但有滞后(T1={T1:.1f}s, L={L:.1f}s)'
            return 'pressure', confidence, reason
        return 'flow', confidence, reason

    # ========== 规则 4: 中速系统 → 压力 ==========
    # T1 在 10~30s 之间的中速系统，默认归为压力
    confidence = 0.5
    reason = f'中速系统(T1={T1:.1f}s)'

    # 根据 L/T1 比值微调
    if T1 > 0 and L / T1 > 0.3:
        confidence = 0.55
        reason += f', 较大滞后比(L/T1={L/T1:.2f})'

    return 'pressure', confidence, reason


def format_inference_log(loop_type: str, confidence: float, reason: str) -> str:
    """格式化推断结果日志"""
    type_names = {
        'flow': '流量',
        'temperature': '温度',
        'level': '液位',
        'pressure': '压力',
    }
    type_cn = type_names.get(loop_type, loop_type)
    confidence_label = '高' if confidence >= 0.8 else '中' if confidence >= 0.6 else '低'
    return (
        f"🔍 回路类型推断: {type_cn}({loop_type}) "
        f"[置信度: {confidence:.0%} ({confidence_label})]\n"
        f"   原因: {reason}"
    )

