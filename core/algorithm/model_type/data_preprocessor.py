"""数据预处理模块 - 滤波、去噪、质量分析"""

import numpy as np
from typing import Dict, Any, Tuple, Optional
from dataclasses import dataclass
from scipy.ndimage import uniform_filter1d
from scipy.stats import linregress


@dataclass
class NonlinearityAnalysis:
    """非线性分析结果"""
    is_nonlinear: bool              # 是否为非线性系统
    nonlinearity_score: float       # 非线性程度 (0-1)
    gain_variation: float           # 增益变化程度
    saturation_detected: bool       # 是否检测到饱和
    deadzone_detected: bool         # 是否检测到死区
    hysteresis_score: float         # 迟滞程度
    recommended_model: str          # 推荐模型类型
    segment_count: int              # 建议分段数
    
    @property
    def description(self) -> str:
        """非线性类型描述"""
        if not self.is_nonlinear:
            return "线性系统"
        issues = []
        if self.gain_variation > 0.3:
            issues.append("变增益")
        if self.saturation_detected:
            issues.append("饱和")
        if self.deadzone_detected:
            issues.append("死区")
        if self.hysteresis_score > 0.2:
            issues.append("迟滞")
        return "非线性系统: " + ", ".join(issues) if issues else "轻度非线性"


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
    nonlinearity: NonlinearityAnalysis = None  # 非线性分析结果
    
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
    
    # ============================================================
    # 非线性检测
    # ============================================================
    
    def analyze_nonlinearity(self, y: np.ndarray, u: np.ndarray) -> NonlinearityAnalysis:
        """
        分析数据的非线性特征
        
        检测以下非线性类型：
        1. 变增益 - 增益随工作点变化
        2. 饱和 - 输出受限
        3. 死区 - 小输入无响应
        4. 迟滞 - 上升下降路径不同
        
        Args:
            y: PV数据
            u: MV数据
        
        Returns:
            NonlinearityAnalysis: 非线性分析结果
        """
        if len(y) < 30:
            return NonlinearityAnalysis(
                is_nonlinear=False, nonlinearity_score=0.0, gain_variation=0.0,
                saturation_detected=False, deadzone_detected=False,
                hysteresis_score=0.0, recommended_model='FOPDT', segment_count=1
            )
        
        # 1. 检测增益变化
        gain_variation, segment_gains = self._analyze_gain_variation(y, u)
        
        # 2. 检测饱和
        saturation_detected = self._detect_saturation(y, u)
        
        # 3. 检测死区
        deadzone_detected = self._detect_deadzone(y, u)
        
        # 4. 检测迟滞
        hysteresis_score = self._analyze_hysteresis(y, u)
        
        # 5. 检测振荡
        oscillation_score = self._detect_oscillation(y)
        
        # 计算综合非线性评分
        nonlinearity_score = self._calculate_nonlinearity_score(
            gain_variation, saturation_detected, deadzone_detected, hysteresis_score, oscillation_score
        )
        
        # 判断是否为非线性
        is_nonlinear = nonlinearity_score > 0.25
        
        # 推荐模型和分段数
        recommended_model, segment_count = self._recommend_model(
            is_nonlinear, gain_variation, len(segment_gains)
        )
        
        result = NonlinearityAnalysis(
            is_nonlinear=is_nonlinear,
            nonlinearity_score=nonlinearity_score,
            gain_variation=gain_variation,
            saturation_detected=saturation_detected,
            deadzone_detected=deadzone_detected,
            hysteresis_score=hysteresis_score,
            recommended_model=recommended_model,
            segment_count=segment_count
        )
        
        self.log(f"📊 非线性分析: {result.description}")
        self.log(f"   非线性评分={nonlinearity_score:.3f}, 增益变化={gain_variation:.3f}")
        self.log(f"   推荐模型={recommended_model}, 建议分段={segment_count}")
        
        return result
    
    def _analyze_gain_variation(self, y: np.ndarray, u: np.ndarray) -> tuple:
        """
        分析增益随工作点的变化
        
        将数据按MV范围分成多段，计算每段的局部增益，
        如果增益变化大，说明系统是非线性的。
        
        Returns:
            (gain_variation_coefficient, segment_gains)
        """
        # 将数据按MV值分成若干段
        n_segments = min(5, max(2, len(y) // 50))
        
        # 按MV值排序
        sorted_indices = np.argsort(u)
        segment_size = len(y) // n_segments
        
        segment_gains = []
        
        for i in range(n_segments):
            start = i * segment_size
            end = (i + 1) * segment_size if i < n_segments - 1 else len(y)
            indices = sorted_indices[start:end]
            
            if len(indices) < 10:
                continue
            
            y_seg = y[indices]
            u_seg = u[indices]
            
            # 计算局部增益（线性回归斜率）
            u_range = np.ptp(u_seg)
            y_range = np.ptp(y_seg)
            
            if u_range > self._epsilon:
                # 使用线性回归计算增益
                try:
                    slope, _, r_value, _, _ = linregress(u_seg, y_seg)
                    if not np.isnan(slope) and abs(r_value) > 0.1:
                        segment_gains.append(abs(slope))
                except:
                    pass
        
        if len(segment_gains) < 2:
            return 0.0, segment_gains
        
        # 计算增益的变异系数 (CV = std / mean)
        mean_gain = np.mean(segment_gains)
        if mean_gain < self._epsilon:
            return 0.0, segment_gains
        
        gain_cv = np.std(segment_gains) / mean_gain
        
        return min(gain_cv, 2.0), segment_gains  # 限制最大值为2.0
    
    def _detect_saturation(self, y: np.ndarray, u: np.ndarray) -> bool:
        """
        检测饱和特性
        
        饱和特征：当MV变化时，PV保持在极值附近不变
        """
        y_max, y_min = np.max(y), np.min(y)
        y_range = y_max - y_min
        
        if y_range < self._epsilon:
            return False
        
        # 检查PV在极值附近的时间比例
        threshold = 0.05 * y_range
        at_max = np.sum(y > y_max - threshold)
        at_min = np.sum(y < y_min + threshold)
        
        saturation_ratio = (at_max + at_min) / len(y)
        
        # 如果超过20%的时间在极值附近，且MV在变化，可能是饱和
        if saturation_ratio > 0.2:
            # 检查对应时刻MV是否在变化
            high_indices = y > y_max - threshold
            low_indices = y < y_min + threshold
            
            if np.sum(high_indices) > 10:
                u_at_high = u[high_indices]
                if np.ptp(u_at_high) > 0.1 * np.ptp(u):
                    return True
            
            if np.sum(low_indices) > 10:
                u_at_low = u[low_indices]
                if np.ptp(u_at_low) > 0.1 * np.ptp(u):
                    return True
        
        return False
    
    def _detect_deadzone(self, y: np.ndarray, u: np.ndarray) -> bool:
        """
        检测死区特性
        
        死区特征：MV有变化，但PV几乎不变
        """
        if len(y) < 20:
            return False
        
        # 计算MV和PV的变化
        du = np.abs(np.diff(u))
        dy = np.abs(np.diff(y))
        
        # 找出MV变化显著但PV变化很小的区域
        u_threshold = 0.05 * np.ptp(u)
        y_threshold = 0.02 * np.ptp(y)
        
        mv_changing = du > u_threshold
        pv_static = dy < y_threshold
        
        # 如果有超过15%的点在MV变化时PV不变，可能存在死区
        deadzone_ratio = np.sum(mv_changing & pv_static) / max(np.sum(mv_changing), 1)
        
        return deadzone_ratio > 0.15
    
    def _analyze_hysteresis(self, y: np.ndarray, u: np.ndarray) -> float:
        """
        分析迟滞特性
        
        迟滞特征：上升和下降路径不同
        
        Returns:
            hysteresis_score: 迟滞程度 (0-1)
        """
        if len(y) < 50:
            return 0.0
        
        # 找出MV的上升和下降段
        du = np.diff(u)
        rising_mask = np.concatenate([[False], du > 0])
        falling_mask = np.concatenate([[False], du < 0])
        
        if np.sum(rising_mask) < 10 or np.sum(falling_mask) < 10:
            return 0.0
        
        # 对比相同MV值时，上升和下降过程中的PV值
        # 使用分箱方法
        u_min, u_max = np.min(u), np.max(u)
        n_bins = 10
        bin_edges = np.linspace(u_min, u_max, n_bins + 1)
        
        differences = []
        for i in range(n_bins):
            mask_bin = (u >= bin_edges[i]) & (u < bin_edges[i + 1])
            
            rising_in_bin = mask_bin & rising_mask
            falling_in_bin = mask_bin & falling_mask
            
            if np.sum(rising_in_bin) > 2 and np.sum(falling_in_bin) > 2:
                y_rising = np.mean(y[rising_in_bin])
                y_falling = np.mean(y[falling_in_bin])
                differences.append(abs(y_rising - y_falling))
        
        if not differences:
            return 0.0
        
        # 归一化迟滞程度
        y_range = np.ptp(y)
        if y_range < self._epsilon:
            return 0.0
        
        hysteresis = np.mean(differences) / y_range
        return min(hysteresis, 1.0)
    
    def _detect_oscillation(self, y: np.ndarray) -> float:
        """
        检测PV振荡程度
        
        通过计算零交叉（变化方向改变）的频率来评估振荡
        
        Returns:
            oscillation_score: 振荡评分 (0-1)
        """
        if len(y) < 10:
            return 0.0
        
        # 计算PV的差分
        dy = np.diff(y)
        
        # 去除接近零的变化（噪声）
        y_range = np.ptp(y)
        if y_range < self._epsilon:
            return 0.0
        
        threshold = y_range * 0.01  # 1%的变化范围作为阈值
        dy[np.abs(dy) < threshold] = 0
        
        # 计算符号变化（零交叉）次数
        sign_changes = np.sum(np.diff(np.sign(dy)) != 0)
        
        # 归一化：振荡频率 = 零交叉次数 / 数据长度
        oscillation_freq = sign_changes / len(y)
        
        # 高频振荡（频率>0.3）得分高
        if oscillation_freq > 0.5:
            return 1.0
        elif oscillation_freq > 0.3:
            return 0.7
        elif oscillation_freq > 0.15:
            return 0.4
        elif oscillation_freq > 0.05:
            return 0.2
        else:
            return 0.0
    
    def _calculate_nonlinearity_score(self, gain_variation: float, 
                                        saturation: bool, deadzone: bool,
                                        hysteresis: float, oscillation: float = 0.0) -> float:
        """
        计算综合非线性评分
        
        Returns:
            score: 非线性程度 (0-1)
        """
        score = 0.0
        
        # 增益变化贡献 (最大0.3)
        score += min(gain_variation * 0.4, 0.3)
        
        # 饱和贡献 (0.15)
        if saturation:
            score += 0.15
        
        # 死区贡献 (0.15)
        if deadzone:
            score += 0.15
        
        # 迟滞贡献 (最大0.15)
        score += min(hysteresis * 0.3, 0.15)
        
        # 振荡贡献 (最大0.25) - 新增
        score += min(oscillation * 0.35, 0.25)
        
        return min(score, 1.0)
    
    def _recommend_model(self, is_nonlinear: bool, gain_variation: float,
                          n_gain_segments: int) -> tuple:
        """
        根据非线性分析推荐模型类型
        
        Returns:
            (recommended_model, segment_count)
        """
        if not is_nonlinear:
            return 'FOPDT', 1
        
        # 根据增益变化程度推荐分段数
        if gain_variation > 0.8:
            # 高度非线性，需要多段拟合
            segment_count = min(5, max(3, n_gain_segments))
            return 'PIECEWISE_LINEAR', segment_count
        elif gain_variation > 0.4:
            # 中度非线性
            segment_count = min(3, max(2, n_gain_segments))
            return 'PIECEWISE_LINEAR', segment_count
        else:
            # 轻度非线性，可尝试线性模型
            return 'FOPDT', 1
    
    def segment_for_nonlinear(self, y: np.ndarray, u: np.ndarray,
                               n_segments: int = 3) -> list:
        """
        为非线性系统进行工作点分段
        
        优化策略：
        1. 先尝试基于增益变化的自适应分段
        2. 如果增益变化不明显，回退到按PV值分段
        3. 保持时间连续性，避免打乱时序
        
        Args:
            y: PV数据
            u: MV数据
            n_segments: 分段数
        
        Returns:
            list of (y_seg, u_seg, pv_center, indices)
        """
        n = len(y)
        if n < 60:  # 数据太少，不分段
            return [(y, u, np.mean(y), np.arange(n))]
        
        # 方法1：基于增益(K=ΔPV/ΔMV)变化的自适应分段
        segments_adaptive = self._segment_by_gain_variation(y, u, n_segments)
        
        # 如果自适应分段成功，使用它
        if len(segments_adaptive) >= 2:
            return segments_adaptive
        
        # 方法2：按PV值分段（保留原有逻辑）
        y_min, y_max = np.min(y), np.max(y)
        segment_boundaries = np.linspace(y_min, y_max, n_segments + 1)
        
        segments = []
        for i in range(n_segments):
            lower = segment_boundaries[i]
            upper = segment_boundaries[i + 1]
            
            # 稍微扩展边界，避免边缘效应
            if i == 0:
                lower -= 0.01 * (y_max - y_min)
            if i == n_segments - 1:
                upper += 0.01 * (y_max - y_min)
            
            mask = (y >= lower) & (y <= upper)
            indices = np.where(mask)[0]
            
            if len(indices) < 20:
                continue
            
            y_seg = y[indices]
            u_seg = u[indices]
            pv_center = (lower + upper) / 2
            
            segments.append((y_seg, u_seg, pv_center, indices))
        
        return segments
    
    def _segment_by_gain_variation(self, y: np.ndarray, u: np.ndarray,
                                    n_segments: int = 3) -> list:
        """
        基于增益变化的自适应分段
        
        通过滑动窗口计算局部增益，在增益变化大的地方分段
        """
        n = len(y)
        window_size = max(20, n // (n_segments * 2))  # 滑动窗口大小
        
        # 计算局部增益
        local_gains = []
        for i in range(0, n - window_size, window_size // 2):
            y_win = y[i:i+window_size]
            u_win = u[i:i+window_size]
            
            dy = np.ptp(y_win)  # PV变化范围
            du = np.ptp(u_win)  # MV变化范围
            
            if du > 0.1:
                gain = dy / du
            else:
                gain = 0.0
            
            local_gains.append((i + window_size // 2, gain))  # (中心位置, 增益)
        
        if len(local_gains) < 3:
            return []  # 数据不足
        
        # 检测增益变化点
        gains = np.array([g[1] for g in local_gains])
        gain_std = np.std(gains)
        
        if gain_std < 0.1:  # 增益变化不明显，不适合分段
            return []
        
        # 找到增益变化最大的几个点作为分段边界
        gain_diff = np.abs(np.diff(gains))
        
        # 找到n_segments-1个分界点
        if len(gain_diff) >= n_segments - 1:
            boundary_indices = np.argsort(gain_diff)[-(n_segments-1):]
            boundary_indices = np.sort(boundary_indices)
        else:
            return []  # 不足以分段
        
        # 构建分段
        segments = []
        segment_starts = [0] + [local_gains[i][0] for i in boundary_indices] + [n]
        
        for i in range(len(segment_starts) - 1):
            start_idx = segment_starts[i]
            end_idx = segment_starts[i + 1]
            
            if end_idx - start_idx < 20:
                continue
            
            indices = np.arange(start_idx, end_idx)
            y_seg = y[indices]
            u_seg = u[indices]
            pv_center = np.mean(y_seg)
            
            segments.append((y_seg, u_seg, pv_center, indices))
        
        return segments
