"""
数据预处理模块 (Data Preprocessing Module)
==========================================

本模块提供模型辨识前的数据预处理功能，确保输入数据质量。

核心功能
--------
1. **滤波去噪**: 移动平均滤波、中值滤波
2. **异常值处理**: 基于IQR方法检测和处理异常值
3. **数据质量分析**: 评估噪声、相关性、非线性程度等
4. **数据变换**: 归一化、标准化
5. **变化点检测**: 检测MV变化点，用于数据分段

主要类
------
- **DataQuality**: 数据质量评估结果数据类
- **DataPreprocessor**: 数据预处理器主类

质量指标说明
------------
- noise_ratio: 噪声比例 (噪声标准差/数据范围)
- correlation: PV-MV相关系数
- nonlinearity_score: 非线性程度 (0-1)
- step_response_score: 阶跃响应特征评分 (0-1)
- oscillation_ratio: 振荡比例
"""

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
    # 新增：非线性和扰动质量指标
    nonlinearity_score: float = 0.0     # 非线性程度 (0-1)，越高越非线性
    step_response_score: float = 1.0    # 阶跃响应特征评分 (0-1)
    oscillation_ratio: float = 0.0      # 振荡比例
    is_nonlinear: bool = False          # 是否为非线性扰动
    is_step_response: bool = True       # 是否具有阶跃响应特征
    
    @property
    def quality_score(self) -> float:
        """综合质量评分 (0-1)"""
        score = 0.0
        if self.is_correlated:
            score += 0.25 * min(abs(self.correlation), 1.0)
        if not self.is_noisy:
            score += 0.2 * (1 - min(self.noise_ratio, 1.0))
        score += 0.2 * self.trend_consistency
        # 非线性惩罚
        score += 0.2 * (1 - self.nonlinearity_score)
        # 阶跃响应奖励
        score += 0.15 * self.step_response_score
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
        
        # 5. 计算非线性程度
        nonlinearity_score = self._calculate_nonlinearity(y, u)
        
        # 6. 计算阶跃响应特征评分
        step_response_score = self._calculate_step_response_score(y, u)
        
        # 7. 计算振荡比例
        oscillation_ratio = self._calculate_oscillation_ratio(y)
        
        # 8. 判断质量标志
        is_noisy = noise_ratio > self.noise_threshold
        is_correlated = abs(correlation) > self.min_correlation
        is_nonlinear = nonlinearity_score > 0.5  # 非线性程度>50%认为是非线性
        is_step_response = step_response_score > 0.4
        
        # 综合判断是否有效
        is_valid = (is_correlated or self._check_integral_response(y, u)) and not is_nonlinear
        
        quality = DataQuality(
            noise_ratio=noise_ratio,
            correlation=correlation,
            lag_estimate=lag_estimate,
            trend_consistency=trend_consistency,
            is_noisy=is_noisy,
            is_correlated=is_correlated,
            is_valid=is_valid,
            nonlinearity_score=nonlinearity_score,
            step_response_score=step_response_score,
            oscillation_ratio=oscillation_ratio,
            is_nonlinear=is_nonlinear,
            is_step_response=is_step_response
        )
        
        self.log(f"📊 数据质量: {quality.quality_level} (score={quality.quality_score:.2f})")
        self.log(f"   噪声比={noise_ratio:.3f}, 相关性={correlation:.3f}, 延迟={lag_estimate}")
        self.log(f"   非线性={nonlinearity_score:.3f}, 阶跃特征={step_response_score:.3f}, 振荡={oscillation_ratio:.3f}")
        
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
    
    def _calculate_nonlinearity(self, y: np.ndarray, u: np.ndarray) -> float:
        """
        计算非线性程度 (0-1)
        
        检测方法：
        1. 分段线性度检测 - 将数据分成多段，比较各段增益的一致性
        2. 残差分布检测 - 检查线性拟合残差是否具有系统性偏差
        3. 突变检测 - 检测是否存在突然的线性关系变化
        
        Returns:
            非线性度 (0-1)，0表示完全线性，1表示高度非线性
        """
        if len(y) < 30:
            return 0.0
        
        try:
            n = len(y)
            scores = []
            
            # 方法1：分段增益一致性检测
            n_segments = min(4, n // 20)
            if n_segments >= 2:
                segment_size = n // n_segments
                segment_gains = []
                
                for i in range(n_segments):
                    start = i * segment_size
                    end = start + segment_size if i < n_segments - 1 else n
                    y_seg = y[start:end]
                    u_seg = u[start:end]
                    
                    # 计算该段的增益 (delta_y / delta_u)
                    dy = y_seg[-1] - y_seg[0]
                    du = u_seg[-1] - u_seg[0]
                    
                    if abs(du) > self._epsilon:
                        gain = dy / du
                        segment_gains.append(gain)
                
                if len(segment_gains) >= 2:
                    # 计算增益的变异系数
                    gains_mean = np.mean(segment_gains)
                    gains_std = np.std(segment_gains)
                    if abs(gains_mean) > self._epsilon:
                        gain_cv = abs(gains_std / gains_mean)
                        # CV > 0.5 认为是非线性
                        scores.append(min(gain_cv, 1.0))
            
            # 方法2：线性拟合残差的系统性检测
            try:
                # 简单线性拟合
                A = np.vstack([u, np.ones(len(u))]).T
                coeffs, residuals, _, _ = np.linalg.lstsq(A, y, rcond=None)
                y_linear = u * coeffs[0] + coeffs[1]
                residual = y - y_linear
                
                # 检查残差是否具有系统性偏差（非随机性）
                # 如果残差与 u 仍有相关性，说明存在非线性
                if len(residual) > 5:
                    residual_u_corr = np.corrcoef(residual, u)[0, 1]
                    if not np.isnan(residual_u_corr):
                        scores.append(min(abs(residual_u_corr), 1.0))
            except:
                pass
            
            # 方法3：突变检测 - 检测 PV 的突然变化
            pv_diff = np.abs(np.diff(y))
            pv_range = np.ptp(y)
            if pv_range > self._epsilon:
                # 计算突变的比例
                threshold = pv_range * 0.2  # 20% 的范围作为突变阈值
                sudden_changes = np.sum(pv_diff > threshold)
                sudden_ratio = sudden_changes / (len(y) - 1)
                # 突变比例 > 5% 认为有非线性特征
                if sudden_ratio > 0.05:
                    scores.append(min(sudden_ratio * 5, 1.0))
            
            if scores:
                return float(np.mean(scores))
            return 0.0
            
        except Exception as e:
            self.log(f"   非线性检测失败: {e}")
            return 0.0
    
    def _calculate_step_response_score(self, y: np.ndarray, u: np.ndarray) -> float:
        """
        计算阶跃响应特征评分 (0-1)
        
        阶跃响应应具有以下特征：
        1. MV 有明显的阶跃变化
        2. PV 对 MV 变化有延迟响应
        3. PV 向新稳态值收敛
        
        Returns:
            阶跃响应特征评分 (0-1)
        """
        if len(y) < 20:
            return 0.5  # 数据太短，返回中等分数
        
        try:
            n = len(y)
            scores = []
            
            # 特征1：MV 变化程度
            mv_range = np.ptp(u)
            mv_std = np.std(u)
            if mv_range > 0.1:
                # MV 应该有明显变化但不过于频繁
                mv_changes = np.sum(np.abs(np.diff(u)) > mv_range * 0.1)
                # 理想情况：1-3次显著变化
                if 1 <= mv_changes <= 5:
                    scores.append(1.0)
                elif mv_changes < 1:
                    scores.append(0.3)  # MV 基本不变
                else:
                    scores.append(max(0.3, 1 - mv_changes * 0.05))  # 变化太频繁
            
            # 特征2：响应延迟检测
            lag = self._estimate_lag(y, u)
            if 0 <= lag <= n // 3:  # 延迟在合理范围内
                scores.append(1.0)
            elif lag < 0:  # 负延迟（PV领先于MV，不符合因果关系）
                scores.append(0.3)
            else:
                scores.append(0.5)
            
            # 特征3：收敛特征 - 后1/3数据应该更稳定
            last_third = y[int(n * 2/3):]
            first_half = y[:int(n * 0.5)]
            
            if len(last_third) > 5 and len(first_half) > 5:
                std_last = np.std(last_third)
                std_first = np.std(first_half)
                
                if std_first > self._epsilon:
                    # 后期波动应该小于前期
                    settling_ratio = std_last / std_first
                    if settling_ratio < 0.5:
                        scores.append(1.0)  # 明显收敛
                    elif settling_ratio < 1.0:
                        scores.append(0.7)  # 较好收敛
                    else:
                        scores.append(0.3)  # 未收敛或振荡加剧
            
            # 特征4：单调性检测（理想的阶跃响应应基本单调）
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            sign_change_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            # 符号变化比例 < 0.2 认为是单调的
            if sign_change_ratio < 0.2:
                scores.append(1.0)
            elif sign_change_ratio < 0.4:
                scores.append(0.7)
            else:
                scores.append(0.3)  # 振荡太多
            
            if scores:
                return float(np.mean(scores))
            return 0.5
            
        except Exception as e:
            self.log(f"   阶跃响应检测失败: {e}")
            return 0.5
    
    def _calculate_oscillation_ratio(self, y: np.ndarray) -> float:
        """计算振荡比例"""
        if len(y) < 5:
            return 0.0
        
        try:
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            oscillation_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            return min(oscillation_ratio, 1.0)
        except:
            return 0.0
    
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
    
    # ============================================================
    # 高级质量分析
    # ============================================================
    
    def analyze_segment_quality(self, y: np.ndarray, u: np.ndarray) -> Dict[str, Any]:
        """
        详细分析扰动段的质量，用于决策是否用于整定
        
        Args:
            y: PV数据
            u: MV数据
        
        Returns:
            详细质量报告
        """
        quality = self.analyze_quality(y, u)
        
        report = {
            'quality_score': quality.quality_score,
            'quality_level': quality.quality_level,
            'is_valid_for_tuning': quality.is_valid and quality.is_step_response and not quality.is_nonlinear,
            'metrics': {
                'noise_ratio': quality.noise_ratio,
                'correlation': quality.correlation,
                'nonlinearity': quality.nonlinearity_score,
                'step_response': quality.step_response_score,
                'oscillation': quality.oscillation_ratio
            },
            'flags': {
                'is_noisy': quality.is_noisy,
                'is_correlated': quality.is_correlated,
                'is_nonlinear': quality.is_nonlinear,
                'is_step_response': quality.is_step_response
            },
            'recommendations': []
        }
        
        # 生成建议
        if quality.is_nonlinear:
            report['recommendations'].append('数据显示非线性特征，建议排除该段或使用分段线性化处理')
        if not quality.is_step_response:
            report['recommendations'].append('数据不符合阶跃响应特征，建议检查数据来源')
        if quality.is_noisy:
            report['recommendations'].append('数据噪声较大，建议使用滤波预处理')
        if quality.oscillation_ratio > 0.4:
            report['recommendations'].append('数据振荡严重，可能控制回路不稳定')
        
        return report
