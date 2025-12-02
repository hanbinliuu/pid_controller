"""
整定段选取模块
整合滑动窗口方差分析和core中的整定段选取逻辑
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Union, Any


def find_high_variability_periods(
    data: pd.Series,
    window_size: int = 3600,
    step_size: int = 600,
    variability_threshold: float = 0.8,
    analyst_column: Optional[str] = None,
    window_sec: Optional[int] = None,
    is_filter: bool = False
) -> Dict[str, Any]:
    """
    使用滑动窗口方差分析寻找高波动时间段

    参数:
    - data: 时间序列数据, Pandas Series with datetime index
    - window_size: 分析窗口大小（样本点数，通常对应秒）
    - step_size: 滑动步长（样本点数，通常对应秒）
    - variability_threshold: 波动性阈值(0-1之间的分位数)
    - analyst_column: 分析的列名（默认为"pv"）
    - window_sec: 窗口秒数（可选，用于时间转换）
    - is_filter: 是否过滤低波动窗口

    返回:
    - dict: 包含以下字段
        - table: 所有窗口的统计信息DataFrame
        - start_time: 整定段开始时间
        - end_time: 整定段结束时间
        - params: 使用的参数
        - total_windows: 总窗口数
        - std_max_window: 标准差最大的窗口信息
    """
    try:
        # 数据预处理
        data_resampled = data.copy()
        
        # 存储窗口统计信息
        windows_data = []
        variances = []
        
        # 滑动窗口计算方差
        for start in range(0, len(data_resampled) - window_size, step_size):
            end = start + window_size
            window_data = data_resampled.iloc[start:end]
            
            # 计算窗口内的方差（排除NaN值）
            if len(window_data.dropna()) > window_size * 0.8:  # 至少80%有效数据
                clean_vals = window_data.dropna().to_numpy(dtype=float)
                
                # 方差
                window_var = float(np.var(clean_vals))
                # 窗口标准差
                window_std = float(np.std(clean_vals))
                # 均值
                window_mean = float(np.mean(clean_vals))
                # 差分标准差
                diffs = np.diff(clean_vals) if len(clean_vals) > 1 else np.array([], dtype=float)
                step_deg = float(np.std(diffs)) if len(diffs) > 1 else 0.0
                # 极差
                window_range = float(np.max(clean_vals) - np.min(clean_vals))
                
                window_start_time = data_resampled.index[start]
                window_end_time = data_resampled.index[min(end - 1, len(data_resampled) - 1)]
                
                windows_data.append({
                    "window_idx": len(windows_data),
                    "start_idx": start,
                    "end_idx": end,
                    "start_time": window_start_time,
                    "end_time": window_end_time,
                    "variance": window_var,
                    "std": window_std,
                    "mean": window_mean,
                    "step_degree": step_deg,
                    "range": window_range,
                    "valid_points": len(clean_vals)
                })
                variances.append(window_var)
        
        # 如果没有有效窗口
        if not windows_data:
            return {
                "table": pd.DataFrame(),
                "start_time": None,
                "end_time": None,
                "params": {
                    "window_size": window_size,
                    "step_size": step_size,
                    "variability_threshold": variability_threshold,
                    "analyst_column": analyst_column or "pv",
                    "window_sec": window_sec,
                    "is_filter": is_filter
                },
                "total_windows": 0,
                "std_max_window": None
            }
        
        # 创建统计表
        table = pd.DataFrame(windows_data)
        
        # 设置阈值（使用分位数）
        threshold = np.quantile(variances, variability_threshold)
        
        # 标记高波动窗口
        table["is_high_variability"] = table["variance"] >= threshold
        
        # 如果需要过滤，只保留高波动窗口
        if is_filter:
            windows_out = table[table["is_high_variability"]].copy()
        else:
            windows_out = table.copy()
        
        # 找到标准差最大的窗口
        if len(windows_out) > 0:
            std_max_idx = windows_out["std"].idxmax()
            std_max_window = windows_out.loc[std_max_idx].to_dict()
        else:
            std_max_window = None
        
        # 确定整定段的起止时间
        if std_max_window is not None:
            start_time = std_max_window["start_time"]
            end_time = std_max_window["end_time"]
        else:
            start_time = data_resampled.index[0] if len(data_resampled) > 0 else None
            end_time = data_resampled.index[-1] if len(data_resampled) > 0 else None
        
        return {
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "variability_threshold": variability_threshold,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": len(windows_out),
            "std_max_window": std_max_window
        }
    
    except Exception as e:
        return {
            "table": pd.DataFrame(),
            "start_time": None,
            "end_time": None,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "variability_threshold": variability_threshold,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": 0,
            "std_max_window": None,
            "error": str(e)
        }


class TuningSegmentSelector:
    """
    整定段选取器
    整合core中的整定段选取逻辑（DataAnalyzer、StabilityDetector）
    与滑动窗口方差分析方法
    """
    
    def __init__(
        self,
        tol: float = 0.5,
        std_tol: float = 0.2,
        min_len: int = 10,
        window_size: int = 3600,
        step_size: int = 600,
        variability_threshold: float = 0.8
    ):
        """
        初始化整定段选取器
        
        Args:
            tol: 容差（PV与设定值的允许偏差）
            std_tol: 标准差阈值
            min_len: 最小数据长度
            window_size: 分析窗口大小（样本点数）
            step_size: 滑动步长（样本点数）
            variability_threshold: 波动性阈值(0-1之间的分位数)
        """
        self.tol = tol
        self.std_tol = std_tol
        self.min_len = min_len
        self.window_size = window_size
        self.step_size = step_size
        self.variability_threshold = variability_threshold
    
    # ==================== 稳态检测方法（来自StabilityDetector）====================
    
    def is_steady_state(self, pv_data: np.ndarray, setpoint: float, 
                        tol: Optional[float] = None, std_tol: Optional[float] = None,
                        min_len: Optional[int] = None) -> bool:
        """
        判断一段数据是否处于稳态
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
            tol: 容差（默认使用实例设置）
            std_tol: 标准差阈值（默认使用实例设置）
            min_len: 最小数据长度（默认使用实例设置）
            
        Returns:
            bool: True表示稳态，False表示非稳态
        """
        tol = tol if tol is not None else self.tol
        std_tol = std_tol if std_tol is not None else self.std_tol
        min_len = min_len if min_len is not None else self.min_len
        
        if len(pv_data) < min_len:
            return False
        
        pv_data = np.array(pv_data)
        n = len(pv_data)
        
        # 基本统计量
        mean_val = np.mean(pv_data)
        std_val = np.std(pv_data)
        mean_dev = abs(mean_val - setpoint)
        
        # 1. 均值偏差检查
        if mean_dev > tol * 1.2:
            return False
        
        # 2. 标准差检查
        if std_val > std_tol:
            return False
        
        # 3. 百分比阈值检查：至少95%的点在容差范围内
        in_band_ratio = np.sum(np.abs(pv_data - setpoint) <= tol) / n
        if in_band_ratio < 0.95:
            return False
        
        # 4. 趋势检测
        if n > 10:
            try:
                x = np.arange(n)
                coeffs = np.polyfit(x, pv_data, 1)
                slope = coeffs[0]
                max_slope = std_tol / n * 2
                if abs(slope) > max_slope:
                    return False
            except:
                pass
        
        # 5. 振荡幅度检测
        if n > 10:
            data_range = np.max(pv_data) - np.min(pv_data)
            if data_range > tol * 4:
                return False
            if setpoint > 0 and data_range > abs(setpoint) * 0.3:
                return False
        
        return True
    
    def find_disturbance_start(self, pv_data: np.ndarray, setpoint: float, 
                                steady_head_len: int, threshold: float = 1.0) -> Optional[int]:
        """
        定位扰动起始点（非稳态开始位置）
        
        Args:
            pv_data: 过程值数据
            setpoint: 设定值
            steady_head_len: 稳态段长度（用于建立基准）
            threshold: 偏差阈值
            
        Returns:
            int: 扰动起始点索引，如果未找到返回None
        """
        n = len(pv_data)
        if n < steady_head_len + 10:
            return None
        
        # 计算稳态段的统计量作为基准
        steady_segment = pv_data[:steady_head_len]
        steady_mean = np.mean(steady_segment)
        steady_std = np.std(steady_segment)
        
        detected_start = None
        
        # 偏差突变检测
        for i in range(steady_head_len, n - 5):
            if abs(pv_data[i] - setpoint) > threshold * 0.6:
                window = min(5, n - i)
                if window > 0:
                    window_data = pv_data[i:i+window]
                    if np.mean(np.abs(window_data - setpoint)) > threshold * 0.5:
                        detected_start = i
                        break
        
        # 向前回溯找到真正的起始位置
        if detected_start is not None and detected_start > steady_head_len:
            lookback = min(20, detected_start - steady_head_len)
            for i in range(detected_start - 1, detected_start - lookback - 1, -1):
                if abs(pv_data[i] - steady_mean) > steady_std * 2:
                    detected_start = i
                else:
                    break
        
        return detected_start
    
    def detect_setpoint_changes(self, sv_array: np.ndarray, 
                                 min_change: float = 0.5, 
                                 min_stable_points: int = 20) -> List[Tuple[int, int, float]]:
        """
        检测设定值变化点，将数据分段
        
        Args:
            sv_array: 设定值数组
            min_change: 设定值变化的最小阈值
            min_stable_points: 每个设定值段的最小稳定点数
            
        Returns:
            list: 设定值段列表，每个元素为 (start_idx, end_idx, setpoint_value)
        """
        if sv_array is None or len(sv_array) < min_stable_points:
            return [(0, len(sv_array), np.mean(sv_array) if len(sv_array) > 0 else 0.0)]
        
        sv_array = np.array(sv_array)
        segments = []
        n = len(sv_array)
        
        # 使用滑动窗口检测设定值变化
        window_size = min(5, n // 10)
        window_size = max(1, window_size)
        
        change_points = []
        for i in range(window_size, n - window_size):
            prev_window = sv_array[i - window_size:i]
            next_window = sv_array[i:i + window_size]
            prev_mean = np.mean(prev_window)
            next_mean = np.mean(next_window)
            
            if abs(next_mean - prev_mean) > min_change:
                if i + window_size < n:
                    check_window = sv_array[i:min(i + window_size * 2, n)]
                    check_mean = np.mean(check_window)
                    if abs(check_mean - next_mean) < min_change * 0.3:
                        if len(change_points) == 0 or i - change_points[-1] > window_size * 2:
                            change_points.append(i)
        
        # 构建分段列表
        if len(change_points) == 0:
            segments.append((0, n, np.mean(sv_array)))
        else:
            start_idx = 0
            for change_idx in change_points:
                if change_idx > start_idx + min_stable_points:
                    seg_sv = np.mean(sv_array[start_idx:change_idx])
                    segments.append((start_idx, change_idx, seg_sv))
                    start_idx = change_idx
            
            # 添加最后一段
            if start_idx < n:
                seg_sv = np.mean(sv_array[start_idx:n])
                segments.append((start_idx, n, seg_sv))
        
        return segments
    
    # ==================== CASE分类方法（来自DataAnalyzer）====================
    
    def classify_case(self, temp_data: np.ndarray, setpoint: float, 
                      sv_array: Optional[np.ndarray] = None) -> str:
        """
        判断数据属于哪种情形
        
        分类结果：
        - CASE_1: 冷启动，一开始就是非稳态
        - CASE_2: SV会手动调整，调整时的变化不属于非稳态
        - CASE_3: 旧的PID参数下稳态，但后面出现非稳态
        - ALREADY_STABLE: 全程稳态
        - UNKNOWN: 无法判断
        
        Args:
            temp_data: PV数据
            setpoint: 设定值
            sv_array: SV数据（可选）
            
        Returns:
            str: CASE类型
        """
        n = len(temp_data)
        if n < 30:
            return "UNKNOWN"

        temp_data = np.array(temp_data)
        
        # 使用严格阈值
        strict_tol = 0.5
        strict_std_tol = 0.3
        
        # 基本统计
        data_range = np.max(temp_data) - np.min(temp_data)
        data_std = np.std(temp_data)
        data_mean = np.mean(temp_data)
        
        # 绝对振荡检测
        if data_range > 2.0:
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"
            else:
                return "CASE_3"
        
        # 相对振荡检测
        if setpoint > 0 and data_range > abs(setpoint) * 0.15:
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"
            else:
                return "CASE_3"
        
        # 标准差检测
        if data_std > 0.8:
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"
            else:
                return "CASE_3"
        
        # 平均偏差检测
        mean_dev = abs(data_mean - setpoint)
        if mean_dev > 1.5:
            return "CASE_1"
        
        # 前段稳态检测
        head_len = max(20, min(50, n // 3))
        head_steady = self.is_steady_state(temp_data[:head_len], setpoint, strict_tol, strict_std_tol)

        # 尾段稳态检测
        tail_len = max(20, min(30, n // 4))
        tail_steady = self.is_steady_state(temp_data[-tail_len:], setpoint, strict_tol, strict_std_tol)

        # 初始偏差检测
        initial_dev = abs(temp_data[0] - setpoint)
        is_cold_start = initial_dev > strict_tol * 3

        # 扰动检测
        has_disturbance = False
        if head_steady:
            disturbance_start = self.find_disturbance_start(temp_data, setpoint, head_len, threshold=strict_tol * 2)
            has_disturbance = disturbance_start is not None

        # 设定值变化检测
        has_setpoint_change = False
        if sv_array is not None and len(sv_array) == len(temp_data):
            sv_segments = self.detect_setpoint_changes(sv_array, min_change=0.5, min_stable_points=20)
            has_setpoint_change = len(sv_segments) > 1
        
        # 分类逻辑
        if head_steady and tail_steady and not has_disturbance:
            return "ALREADY_STABLE"
        
        if has_setpoint_change and head_steady:
            return "CASE_2"
        
        if head_steady and has_disturbance and not has_setpoint_change:
            return "CASE_3"
        
        if is_cold_start and not tail_steady:
            return "CASE_1"
        
        if not head_steady:
            return "CASE_1"
        
        return "CASE_3" if has_disturbance else "CASE_1"
    
    # ==================== 整定段提取方法（来自DataAnalyzer）====================
    
    def extract_tuning_segment(
        self, 
        case: str, 
        t: np.ndarray, 
        temp_data: np.ndarray, 
        setpoint: float,
        u_data: Optional[np.ndarray] = None,
        sv_array: Optional[np.ndarray] = None,
        segment_indices: Optional[Tuple[int, int]] = None
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        根据情形提取有效整定段
        
        Args:
            case: 数据情形（CASE_1/CASE_2/CASE_3等）
            t: 时间数组
            temp_data: 温度/PV数据
            setpoint: 设定值
            u_data: 输入/MV数据（可选）
            sv_array: 设定值数组（可选）
            segment_indices: 分段索引 (start_idx, end_idx)（可选）
            
        Returns:
            Tuple: (t_seg, pv_seg, u_seg) 整定段数据
        """
        # 如果提供了分段索引，直接使用
        if segment_indices is not None:
            start_idx, end_idx = segment_indices
            if u_data is not None:
                return t[start_idx:end_idx], temp_data[start_idx:end_idx], u_data[start_idx:end_idx]
            return t[start_idx:end_idx], temp_data[start_idx:end_idx], None
        
        if case == "CASE_1":
            # 全程非稳态，检查尾部
            if len(temp_data) >= 50:
                tail_len = max(30, len(temp_data) // 4)
                tail_segment = temp_data[-tail_len:]
                is_tail_steady = self.is_steady_state(tail_segment, setpoint, tol=0.5, std_tol=0.2)
                
                if is_tail_steady:
                    return None, None, None
            
            # 使用整段
            if u_data is not None:
                return t, temp_data, u_data
            return t, temp_data, None
            
        elif case == "CASE_2":
            # SV调整场景，找扰动起始点
            head_len = min(50, len(temp_data) // 3)
            start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
            if start_idx is not None:
                if u_data is not None:
                    return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                return t[start_idx:], temp_data[start_idx:], None
            else:
                mid = len(t) // 2
                if u_data is not None:
                    return t[mid:], temp_data[mid:], u_data[mid:]
                return t[mid:], temp_data[mid:], None
                
        elif case in ["CASE_3", "CASE_3_FALLBACK"]:
            # 前段稳态后出现非稳态
            head_len = max(50, len(temp_data) // 3)
            head_len = min(head_len, len(temp_data) - 50)
            
            head_steady = self.is_steady_state(temp_data[:head_len], setpoint, tol=0.5, std_tol=0.2)
            
            if head_steady:
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len, threshold=0.5)
                
                if start_idx is not None:
                    if u_data is not None:
                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                    return t[start_idx:], temp_data[start_idx:], None
                else:
                    # 滑动窗口检测非稳态开始
                    window_size = min(30, len(temp_data) // 10)
                    for i in range(head_len, len(temp_data) - window_size, window_size // 2):
                        window_data = temp_data[i:i+window_size]
                        if not self.is_steady_state(window_data, setpoint, tol=0.5, std_tol=0.2):
                            start_idx = i
                            if u_data is not None:
                                return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                            return t[start_idx:], temp_data[start_idx:], None
                    
                    mid = len(t) // 2
                    if u_data is not None:
                        return t[mid:], temp_data[mid:], u_data[mid:]
                    return t[mid:], temp_data[mid:], None
            else:
                # 前段不稳态，按CASE_2处理
                head_len = min(50, len(temp_data) // 3)
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
                if start_idx is not None:
                    if u_data is not None:
                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                    return t[start_idx:], temp_data[start_idx:], None
                else:
                    mid = len(t) // 2
                    if u_data is not None:
                        return t[mid:], temp_data[mid:], u_data[mid:]
                    return t[mid:], temp_data[mid:], None
        else:
            return None, None, None
    
    # ==================== 主方法：选取整定段 ====================
    
    def select_tuning_segment(
        self,
        data: Union[pd.Series, np.ndarray],
        setpoint: float,
        sv_array: Optional[np.ndarray] = None,
        t: Optional[np.ndarray] = None,
        u_data: Optional[np.ndarray] = None,
        analyst_column: Optional[str] = None,
        window_sec: Optional[int] = None,
        is_filter: bool = False,
        use_variability_method: bool = True
    ) -> Dict[str, Any]:
        """
        选取整定段（主方法）
        整合滑动窗口方差分析和CASE分类方法
        
        Args:
            data: PV数据（Pandas Series或numpy数组）
            setpoint: 设定值
            sv_array: SV数据（可选）
            t: 时间数组（可选，如果data是Series则使用其index）
            u_data: MV数据（可选）
            analyst_column: 分析的列名
            window_sec: 窗口秒数
            is_filter: 是否过滤低波动窗口
            use_variability_method: 是否同时使用滑动窗口方差分析
            
        Returns:
            dict: 整定段选取结果
        """
        # 数据预处理
        if isinstance(data, pd.Series):
            pv_data = data.values
            if t is None:
                t = np.arange(len(pv_data))
        else:
            pv_data = np.array(data)
            if t is None:
                t = np.arange(len(pv_data))
        
        # 1. CASE分类
        case = self.classify_case(pv_data, setpoint, sv_array)
        
        # 2. 提取整定段
        t_seg, pv_seg, u_seg = self.extract_tuning_segment(
            case, t, pv_data, setpoint, u_data, sv_array
        )
        
        # 计算整定段索引
        if t_seg is not None and len(t_seg) > 0:
            start_idx = np.argmin(np.abs(t - t_seg[0]))
            end_idx = np.argmin(np.abs(t - t_seg[-1]))
            segment_indices = (int(start_idx), int(end_idx))
            
            # 转换为时间（如果data是Series）
            if isinstance(data, pd.Series):
                start_time = data.index[start_idx]
                end_time = data.index[end_idx]
            else:
                start_time = t_seg[0]
                end_time = t_seg[-1]
        else:
            segment_indices = None
            start_time = None
            end_time = None
        
        # 3. 滑动窗口方差分析（可选）
        variability_result = None
        if use_variability_method and isinstance(data, pd.Series):
            variability_result = find_high_variability_periods(
                data=data,
                window_size=self.window_size,
                step_size=self.step_size,
                variability_threshold=self.variability_threshold,
                analyst_column=analyst_column,
                window_sec=window_sec,
                is_filter=is_filter
            )
        
        # 构建返回结果
        result = {
            "table": variability_result["table"] if variability_result else pd.DataFrame(),
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": self.window_size,
                "step_size": self.step_size,
                "variability_threshold": self.variability_threshold,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": variability_result["total_windows"] if variability_result else 0,
            "std_max_window": variability_result["std_max_window"] if variability_result else None,
            # 额外信息
            "case": case,
            "segment_indices": segment_indices,
            "tuning_needed": case not in ["ALREADY_STABLE", "UNKNOWN"],
            "t_seg": t_seg,
            "pv_seg": pv_seg,
            "u_seg": u_seg
        }
        
        return result

