"""数据预处理模块 - 滤波、去噪、质量分析"""

import numpy as np
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from scipy.ndimage import uniform_filter1d


@dataclass
class DataQuality:
    """数据质量评估结果"""
    noise_ratio: float          # 噪声比例
    correlation: float          # PV-MV相关系数
    lag_estimate: int           # 延迟估计（采样点数）
    trend_consistency: float    # 趋势一致性
    is_noisy: bool              # 是否有噪声
    is_correlated: bool         # 是否有相关性
    is_valid: bool              # 是否有效（可用于辨识）
    
    @property
    def quality_score(self) -> float:
        """综合质量评分 (0-1)"""
        score = 0.0
        if self.is_correlated:
            score += 0.4 * min(self.correlation, 1.0)
        if not self.is_noisy:
            score += 0.3 * (1 - min(self.noise_ratio, 1.0))
        score += 0.3 * self.trend_consistency
        return score
    
    @property
    def quality_level(self) -> str:
        """质量等级"""
        score = self.quality_score
        if score >= 0.7:
            return 'good'
        elif score >= 0.4:
            return 'medium'
        else:
            return 'poor'


class DataPreprocessor:
    """
    数据预处理器
    
    功能：
    1. 滤波去噪 - 移动平均、中值滤波
    2. 异常值处理 - IQR方法
    3. 数据质量分析 - 噪声、相关性、趋势
    4. 数据归一化/标准化
    
    使用方法：
        preprocessor = DataPreprocessor()
        y_clean, u_clean = preprocessor.filter(y, u)
        quality = preprocessor.analyze_quality(y, u)
    """
    
    # 默认配置
    DEFAULT_FILTER_WINDOW = 5       # 滤波窗口大小
    DEFAULT_NOISE_THRESHOLD = 0.02  # 噪声阈值
    DEFAULT_MIN_CORRELATION = 0.15  # 最小相关系数
    DEFAULT_OUTLIER_FACTOR = 2.0    # 异常值因子（IQR倍数）
    
    def __init__(self, 
                 filter_window: int = DEFAULT_FILTER_WINDOW,
                 noise_threshold: float = DEFAULT_NOISE_THRESHOLD,
                 min_correlation: float = DEFAULT_MIN_CORRELATION,
                 outlier_factor: float = DEFAULT_OUTLIER_FACTOR,
                 verbose: bool = False):
        """
        Args:
            filter_window: 滤波窗口大小
            noise_threshold: 噪声阈值（相对于数据范围）
            min_correlation: 最小相关系数阈值
            outlier_factor: IQR异常值因子
            verbose: 是否输出日志
        """
        self.filter_window = filter_window
        self.noise_threshold = noise_threshold
        self.min_correlation = min_correlation
        self.outlier_factor = outlier_factor
        self.verbose = verbose
        self._epsilon = 1e-9
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    # ============================================================
    # 滤波方法
    # ============================================================
    
    def filter(self, y: np.ndarray, u: np.ndarray, 
               method: str = 'moving_average') -> Tuple[np.ndarray, np.ndarray]:
        """
        对数据进行滤波处理
        
        Args:
            y: PV数据
            u: MV数据
            method: 滤波方法 ('moving_average', 'median', 'none')
        
        Returns:
            (y_filtered, u_filtered)
        """
        if method == 'none' or len(y) < self.filter_window:
            return y.copy(), u.copy()
        
        if method == 'moving_average':
            y_filtered = uniform_filter1d(y, size=self.filter_window, mode='nearest')
            u_filtered = uniform_filter1d(u, size=self.filter_window, mode='nearest')
        elif method == 'median':
            y_filtered = self._median_filter(y, self.filter_window)
            u_filtered = self._median_filter(u, self.filter_window)
        else:
            y_filtered, u_filtered = y.copy(), u.copy()
        
        return y_filtered, u_filtered
    
    def _median_filter(self, data: np.ndarray, window: int) -> np.ndarray:
        """中值滤波"""
        result = np.zeros_like(data)
        half = window // 2
        for i in range(len(data)):
            start = max(0, i - half)
            end = min(len(data), i + half + 1)
            result[i] = np.median(data[start:end])
        return result
    
    def remove_outliers(self, y: np.ndarray, u: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        移除异常值（IQR方法）
        
        Returns:
            (y_cleaned, u_cleaned)
        """
        y_clean = y.copy()
        u_clean = u.copy()
        
        for arr in [y_clean, u_clean]:
            Q1, Q3 = np.percentile(arr, [25, 75])
            IQR = Q3 - Q1
            lower = Q1 - self.outlier_factor * IQR
            upper = Q3 + self.outlier_factor * IQR
            arr[arr < lower] = lower
            arr[arr > upper] = upper
        
        return y_clean, u_clean
    
    def preprocess(self, y: np.ndarray, u: np.ndarray, 
                   filter_method: str = 'moving_average',
                   remove_outlier: bool = True) -> Tuple[np.ndarray, np.ndarray]:
        """
        完整预处理流程：滤波 + 异常值处理
        
        Args:
            y: PV数据
            u: MV数据
            filter_method: 滤波方法
            remove_outlier: 是否移除异常值
        
        Returns:
            (y_processed, u_processed)
        """
        # 1. 滤波
        y_proc, u_proc = self.filter(y, u, method=filter_method)
        
        # 2. 异常值处理
        if remove_outlier:
            y_proc, u_proc = self.remove_outliers(y_proc, u_proc)
        
        return y_proc, u_proc
    
    # ============================================================
    # 质量分析
    # ============================================================
    
    def analyze_quality(self, y: np.ndarray, u: np.ndarray) -> DataQuality:
        """
        分析数据质量
        
        Args:
            y: PV数据
            u: MV数据
        
        Returns:
            DataQuality: 质量评估结果
        """
        # 1. 计算噪声比例
        noise_ratio = self._calculate_noise_ratio(y)
        
        # 2. 计算相关性
        correlation = self._calculate_correlation(y, u)
        
        # 3. 计算延迟估计
        lag_estimate = self._estimate_lag(y, u)
        
        # 4. 计算趋势一致性
        trend_consistency = self._calculate_trend_consistency(y, u)
        
        # 5. 判断质量标志
        is_noisy = noise_ratio > self.noise_threshold
        is_correlated = abs(correlation) > self.min_correlation
        
        # 综合判断是否有效
        is_valid = is_correlated or self._check_integral_response(y, u)
        
        quality = DataQuality(
            noise_ratio=noise_ratio,
            correlation=correlation,
            lag_estimate=lag_estimate,
            trend_consistency=trend_consistency,
            is_noisy=is_noisy,
            is_correlated=is_correlated,
            is_valid=is_valid
        )
        
        self.log(f"📊 数据质量: {quality.quality_level} (score={quality.quality_score:.2f})")
        self.log(f"   噪声比={noise_ratio:.3f}, 相关性={correlation:.3f}, 延迟={lag_estimate}")
        
        return quality
    
    def _calculate_noise_ratio(self, y: np.ndarray) -> float:
        """计算噪声比例"""
        if len(y) < 5:
            return 0.0
        
        y_smooth = uniform_filter1d(y, size=5, mode='nearest')
        noise_std = np.std(y - y_smooth)
        y_range = np.ptp(y)
        
        if y_range < self._epsilon:
            return 0.0
        
        return noise_std / y_range
    
    def _calculate_correlation(self, y: np.ndarray, u: np.ndarray) -> float:
        """计算PV-MV相关系数"""
        if len(y) < 3:
            return 0.0
        
        try:
            corr = np.corrcoef(u, y)[0, 1]
            if np.isnan(corr):
                return 0.0
            return float(corr)
        except:
            return 0.0
    
    def _estimate_lag(self, y: np.ndarray, u: np.ndarray) -> int:
        """估计响应延迟（采样点数）"""
        if len(y) < 10:
            return 0
        
        try:
            y_centered = y - np.mean(y)
            u_centered = u - np.mean(u)
            cross_corr = np.correlate(y_centered, u_centered, mode='full')
            lag = np.argmax(np.abs(cross_corr)) - len(y) + 1
            return int(lag)
        except:
            return 0
    
    def _calculate_trend_consistency(self, y: np.ndarray, u: np.ndarray) -> float:
        """计算趋势一致性（同向变化的比例）"""
        if len(y) < 2:
            return 0.0
        
        dy = np.diff(y)
        du = np.diff(u)
        
        # 忽略变化很小的点
        threshold = 0.01 * max(np.ptp(y), self._epsilon)
        valid_mask = np.abs(dy) > threshold
        
        if np.sum(valid_mask) < 3:
            return 0.5  # 无法判断
        
        dy_valid = dy[valid_mask]
        du_valid = du[valid_mask]
        
        # 同向比例（考虑正/反作用）
        same_sign = np.sum(np.sign(dy_valid) == np.sign(du_valid))
        opposite_sign = np.sum(np.sign(dy_valid) == -np.sign(du_valid))
        
        return max(same_sign, opposite_sign) / len(dy_valid)
    
    def _check_integral_response(self, y: np.ndarray, u: np.ndarray) -> bool:
        """检查是否为积分响应（液位等）"""
        if len(y) < 20:
            return False
        
        try:
            # 积分响应：y 与 cumsum(u) 相关
            u_cumsum = np.cumsum(u - np.mean(u))
            corr_cumsum = np.corrcoef(y, u_cumsum)[0, 1]
            
            if np.isnan(corr_cumsum):
                return False
            
            return abs(corr_cumsum) > 0.3
        except:
            return False
    
    # ============================================================
    # 数据变换
    # ============================================================
    
    def normalize(self, data: np.ndarray) -> Tuple[np.ndarray, float, float]:
        """
        归一化到 [0, 1]
        
        Returns:
            (normalized_data, min_val, range_val)
        """
        min_val = np.min(data)
        range_val = np.ptp(data)
        
        if range_val < self._epsilon:
            return np.zeros_like(data), min_val, 1.0
        
        normalized = (data - min_val) / range_val
        return normalized, min_val, range_val
    
    def denormalize(self, data: np.ndarray, min_val: float, range_val: float) -> np.ndarray:
        """反归一化"""
        return data * range_val + min_val
    
    def standardize(self, data: np.ndarray) -> Tuple[np.ndarray, float, float]:
        """
        标准化（均值0，标准差1）
        
        Returns:
            (standardized_data, mean, std)
        """
        mean = np.mean(data)
        std = np.std(data)
        
        if std < self._epsilon:
            return np.zeros_like(data), mean, 1.0
        
        standardized = (data - mean) / std
        return standardized, mean, std
    
    def destandardize(self, data: np.ndarray, mean: float, std: float) -> np.ndarray:
        """反标准化"""
        return data * std + mean
    
    # ============================================================
    # 数据分段
    # ============================================================
    
    def detect_change_points(self, u: np.ndarray, 
                              threshold: float = 0.1) -> np.ndarray:
        """
        检测MV变化点
        
        Args:
            u: MV数据
            threshold: 变化阈值（相对于范围）
        
        Returns:
            变化点索引数组
        """
        u_range = np.ptp(u)
        if u_range < self._epsilon:
            return np.array([])
        
        du = np.abs(np.diff(u))
        change_threshold = threshold * u_range
        
        change_points = np.where(du > change_threshold)[0] + 1
        return change_points
    
    def segment_by_changes(self, y: np.ndarray, u: np.ndarray,
                           min_segment_length: int = 20) -> list:
        """
        根据MV变化点分段
        
        Returns:
            list of (y_segment, u_segment, start_idx, end_idx)
        """
        change_points = self.detect_change_points(u)
        
        if len(change_points) == 0:
            return [(y, u, 0, len(y))]
        
        segments = []
        start = 0
        
        for cp in change_points:
            if cp - start >= min_segment_length:
                segments.append((y[start:cp], u[start:cp], start, cp))
            start = cp
        
        # 最后一段
        if len(y) - start >= min_segment_length:
            segments.append((y[start:], u[start:], start, len(y)))
        
        return segments
