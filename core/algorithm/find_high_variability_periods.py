import numpy as np
import pandas as pd
from scipy import signal
import matplotlib.pyplot as plt


def find_high_variability_periods(data, window_size=3600, step_size=600,
                                  variability_threshold=0.8):
    """
    使用滑动窗口方差分析寻找高波动时间段

    参数:
    - data: 时间序列数据，Pandas Series with datetime index
    - window_size: 分析窗口大小（样本点数，通常对应秒）
    - step_size: 滑动步长（样本点数，通常对应秒）
    - variability_threshold: 波动性阈值(0-1之间的分位数)

    返回:
    - high_var_windows: 高波动时间段列表 [
        {
            "start_time": pd.Timestamp,
            "end_time": pd.Timestamp,
            "variance": float,
            "std": float,
            "step_degree": float
        }, ...
      ]
    """
    # 重采样到固定频率（如1分钟间隔）
    # data_resampled = data.resample('1S').mean().ffill()
    data_resampled = data
    variances = []
    window_starts = []
    window_stats = []

    # 滑动窗口计算方差
    for start in range(0, len(data_resampled) - window_size, step_size):
        end = start + window_size
        window_data = data_resampled.iloc[start:end]

        # 计算窗口内的方差（排除NaN值）
        if len(window_data.dropna()) > window_size * 0.8:  # 至少80%有效数据
            clean_vals = window_data.dropna().to_numpy(dtype=float)
            window_var = float(np.var(clean_vals))
            window_std = float(np.std(clean_vals))
            # diffs = np.diff(clean_vals) if len(clean_vals) > 1 else np.array([], dtype=float)
            # step_deg = float(np.std(diffs)) if len(diffs) > 1 else 0.0
            
            variances.append(window_var)
            window_starts.append(data_resampled.index[start])
            window_stats.append((window_std))

    if not variances:
        return []

    # 设置阈值（使用分位数）
    threshold = np.quantile(variances, variability_threshold)

    # 识别高波动窗口
    high_var_windows = []
    for i, var in enumerate(variances):
        if var >= threshold:
            start_time = window_starts[i]
            end_time = start_time + pd.Timedelta(seconds=window_size*60)
            std_val = window_stats[i]
            high_var_windows.append({
                "start_time": start_time,
                "end_time": end_time,
                "variance": float(var),
                "std": float(std_val),
                # "step_degree": float(step_deg)
            })

    return high_var_windows