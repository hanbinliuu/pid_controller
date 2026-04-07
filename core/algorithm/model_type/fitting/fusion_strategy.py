"""
参数融合策略模块 (Fusion Strategy Module)
=========================================

本模块实现多扰动段的参数智能融合策略。

核心理念
--------
当存在多个扰动段时，需要将各段的辨识结果融合为一组最优参数。
不同数据质量和一致性情况需要采用不同的融合策略。

融合策略
--------
- **WEIGHTED_FUSION**: R²加权融合，适用于K值一致性好的情况
- **BEST_WINDOW**: 最佳窗口，只使用拟合最好的单个段
- **CONSERVATIVE**: 保守选择，选择K值居中且R²较高的段
- **RECENCY_WEIGHTED**: 时效加权，近期数据权重更高
- **CROSS_VALIDATION**: 交叉验证，综合考虑自身R²和与其他段的一致性
- **ROBUST_FUSION**: 鲁棒融合，对异常值更稳健
- **MEDIAN_FUSION**: 中位数融合，对异常值最稳健
- **QUALITY_WEIGHTED**: 质量加权，高质量段权重更大
- **STABILITY_WEIGHTED**: 稳态加权，稳态段权重更高
- **ADAPTIVE_FUSION**: 自适应融合，综合考虑多因素自动选择

策略选择逻辑
------------
1. 存在高非线性段 → 自适应融合
2. 存在低质量段 → 质量加权融合
3. 存在非稳态段 → 稳态加权融合
4. K值一致性好 → R²加权或鲁棒融合
5. K值差异大 → 中位数融合
"""

import numpy as np
from typing import Dict, List, Optional, Tuple

from ..logger import LoggerMixin
from dataclasses import dataclass
from enum import Enum


class FusionStrategy(Enum):
    """融合策略枚举"""
    WEIGHTED_FUSION = "weighted_fusion"      # R² 加权融合
    BEST_WINDOW = "best_window"              # 最佳窗口
    CONSERVATIVE = "conservative"            # 保守选择
    RECENCY_WEIGHTED = "recency_weighted"    # 时效加权
    CROSS_VALIDATION = "cross_validation"    # 交叉验证
    ROBUST_FUSION = "robust_fusion"          # 鲁棒融合
    MEDIAN_FUSION = "median_fusion"          # 中位数融合
    QUALITY_WEIGHTED = "quality_weighted"    # 质量加权融合
    STABILITY_WEIGHTED = "stability_weighted"  # 稳态加权融合（处理非稳态段）
    ADAPTIVE_FUSION = "adaptive_fusion"      # 自适应融合（综合考虑稳态特征）


@dataclass
class WindowResult:
    """单个窗口的辨识结果"""
    window_idx: int
    K: float
    T1: float
    T2: float
    L: float
    r2: float
    data_points: int
    timestamp: Optional[float] = None
    # 稳态特征（用于非稳态段处理）
    stability_score: float = 1.0      # 稳态评分 (0-1)，1表示完全稳态
    oscillation_ratio: float = 0.0    # 振荡比例
    settling_quality: float = 1.0     # 收敛质量
    is_steady: bool = True            # 是否为稳态段
    # 新增：数据质量指标
    nonlinearity_score: float = 0.0   # 非线性程度 (0-1)
    quality_score: float = 1.0        # 综合质量评分 (0-1)
    
    @property
    def params_dict(self) -> Dict[str, float]:
        return {'K': self.K, 'T1': self.T1, 'T2': self.T2, 'L': self.L}
    
    @property
    def effective_weight(self) -> float:
        """计算有效权重，综合考虑R²、稳态特征和数据质量"""
        # 非线性惩罚
        nonlinear_factor = 1.0 - self.nonlinearity_score * 0.5
        return self.r2 * self.stability_score * self.settling_quality * nonlinear_factor * self.quality_score


@dataclass
class StrategyFusionResult:
    """融合策略结果"""
    K: float
    T1: float
    T2: float
    L: float
    strategy_used: FusionStrategy
    confidence: float
    windows_used: List[int]
    reasoning: str


class PIDFusionStrategy(LoggerMixin):
    """多扰动段 PID 参数融合策略"""
    
    # 策略阈值
    CV_THRESHOLD_CONSISTENT = 0.2
    CV_THRESHOLD_ACCEPTABLE = 0.5
    MIN_R2_THRESHOLD = 0.5
    K_OUTLIER_FACTOR = 3.0
    EPSILON = 1e-8
    
    def __init__(self, verbose: bool = False):
        self._init_logger(verbose)
    
    def _safe_cv(self, values: List[float]) -> float:
        """安全计算变异系数"""
        arr = np.array(values)
        mean_abs = np.abs(np.mean(arr))
        if mean_abs < self.EPSILON:
            return 0.0
        return float(np.std(arr) / mean_abs)
    
    def _weighted_average_params(self, windows: List[WindowResult], 
                                   weights: List[float]) -> Tuple[float, float, float, float]:
        """加权平均计算参数"""
        total_weight = sum(weights)
        if total_weight < self.EPSILON:
            total_weight = 1.0
        
        K = sum(w.K * wt for w, wt in zip(windows, weights)) / total_weight
        T1 = sum(w.T1 * wt for w, wt in zip(windows, weights)) / total_weight
        T2 = sum(w.T2 * wt for w, wt in zip(windows, weights)) / total_weight
        L = sum(w.L * wt for w, wt in zip(windows, weights)) / total_weight
        
        return K, T1, T2, L
    
    def fuse(self, window_results: List[WindowResult], 
             force_strategy: Optional[FusionStrategy] = None) -> StrategyFusionResult:
        """融合多窗口参数"""
        if not window_results:
            raise ValueError("没有有效的窗口结果")
        
        if len(window_results) == 1:
            w = window_results[0]
            return StrategyFusionResult(
                K=w.K, T1=w.T1, T2=w.T2, L=w.L,
                strategy_used=FusionStrategy.BEST_WINDOW,
                confidence=min(w.r2, 1.0),
                windows_used=[w.window_idx],
                reasoning="单窗口，直接使用"
            )
        
        valid_windows = self._filter_windows(window_results)
        
        if not valid_windows:
            self.log("⚠️ 过滤后无有效窗口，使用全部窗口")
            valid_windows = window_results
        
        if force_strategy:
            strategy = force_strategy
            reasoning = f"强制使用策略: {strategy.value}"
        else:
            strategy, reasoning = self._determine_strategy(valid_windows)
        
        self.log(f"📋 选择策略: {strategy.value} - {reasoning}")
        
        strategy_methods = {
            FusionStrategy.WEIGHTED_FUSION: self._weighted_fusion,
            FusionStrategy.BEST_WINDOW: self._best_window,
            FusionStrategy.CONSERVATIVE: self._conservative_selection,
            FusionStrategy.RECENCY_WEIGHTED: self._recency_weighted,
            FusionStrategy.CROSS_VALIDATION: self._cross_validation,
            FusionStrategy.ROBUST_FUSION: self._robust_fusion,
            FusionStrategy.MEDIAN_FUSION: self._median_fusion,
            FusionStrategy.QUALITY_WEIGHTED: self._quality_weighted_fusion,
            FusionStrategy.STABILITY_WEIGHTED: self._stability_weighted_fusion,
            FusionStrategy.ADAPTIVE_FUSION: self._adaptive_fusion,
        }
        
        method = strategy_methods.get(strategy, self._weighted_fusion)
        return method(valid_windows, reasoning)
    
    def _filter_windows(self, windows: List[WindowResult]) -> List[WindowResult]:
        """
        过滤异常窗口
        
        使用更严格的异常值检测：
        1. 基于四分位距(IQR)检测K值异常
        2. 过滤R²过低的窗口
        3. 过滤K值符号不一致的窗口
        """
        if len(windows) <= 1:
            return windows
        
        K_values = np.array([w.K for w in windows])
        
        # 使用IQR方法检测K值异常
        K_median = np.median(K_values)
        K_q1, K_q3 = np.percentile(K_values, [25, 75])
        K_iqr = K_q3 - K_q1
        
        # IQR边界（更严格：1.5倍IQR）
        if K_iqr > self.EPSILON:
            K_lower = K_q1 - 1.5 * K_iqr
            K_upper = K_q3 + 1.5 * K_iqr
        else:
            # IQR太小，使用中位数的2倍范围
            K_median_abs = abs(K_median) + self.EPSILON
            K_lower = K_median - 2 * K_median_abs
            K_upper = K_median + 2 * K_median_abs
        
        self.log(f"   K值过滤: 中位数={K_median:.4f}, IQR范围=[{K_lower:.4f}, {K_upper:.4f}]")
        
        valid = []
        for w in windows:
            # 检查K值是否在IQR范围内
            if w.K < K_lower or w.K > K_upper:
                self.log(f"   窗口{w.window_idx+1}: K={w.K:.4f} 超出IQR范围，过滤")
                continue
            
            # 检查K值符号一致性
            if np.sign(w.K) != np.sign(K_median) and abs(w.K) > self.EPSILON and abs(K_median) > self.EPSILON:
                self.log(f"   窗口{w.window_idx+1}: K符号不一致，过滤")
                continue
            
            # R²阈值检查
            if w.r2 < self.MIN_R2_THRESHOLD:
                self.log(f"   窗口{w.window_idx+1}: R²={w.r2:.3f} < {self.MIN_R2_THRESHOLD}，过滤")
                continue
            
            valid.append(w)
        
        self.log(f"   过滤后保留 {len(valid)}/{len(windows)} 个窗口")
        return valid
    
    def _determine_strategy(self, windows: List[WindowResult]) -> Tuple[FusionStrategy, str]:
        """确定最优融合策略（增强版 - 考虑非线性和数据质量）"""
        K_values = [w.K for w in windows]
        K_cv = self._safe_cv(K_values)
        
        r2_values = [w.r2 for w in windows]
        r2_mean = np.mean(r2_values)
        r2_std = np.std(r2_values)
        
        data_points = [w.data_points for w in windows]
        data_cv = np.std(data_points) / np.mean(data_points) if np.mean(data_points) > 0 else 0
        
        # 检查是否存在非稳态段
        has_unsteady = any(not w.is_steady or w.stability_score < 0.7 for w in windows)
        avg_stability = np.mean([w.stability_score for w in windows])
        avg_oscillation = np.mean([w.oscillation_ratio for w in windows])
        
        # 新增: 检查非线性情况
        avg_nonlinearity = np.mean([getattr(w, 'nonlinearity_score', 0) for w in windows])
        has_high_nonlinearity = any(getattr(w, 'nonlinearity_score', 0) > 0.5 for w in windows)
        
        # 新增: 检查数据质量
        avg_quality = np.mean([getattr(w, 'quality_score', 1.0) for w in windows])
        has_low_quality = any(getattr(w, 'quality_score', 1.0) < 0.4 for w in windows)
        
        # 策略选择优先级（从高到低）：
        
        # 0. 如果存在高非线性段，优先使用自适应融合（会过滤掉非线性段）
        if has_high_nonlinearity:
            return FusionStrategy.ADAPTIVE_FUSION, f"存在高非线性段(平均={avg_nonlinearity:.2f})，自适应融合"
        
        # 1. 如果存在低质量段且质量差异大，使用质量加权
        if has_low_quality and avg_quality < 0.6:
            return FusionStrategy.QUALITY_WEIGHTED, f"存在低质量段(平均质量={avg_quality:.2f})，质量加权融合"
        
        # 2. 如果存在非稳态段，优先使用稳态加权融合
        if has_unsteady or avg_oscillation > 0.3:
            return FusionStrategy.STABILITY_WEIGHTED, f"存在非稳态段(稳态={avg_stability:.2f})，稳态加权融合"
        
        # 3. 如果稳态评分差异大，使用自适应融合
        stability_std = np.std([w.stability_score for w in windows])
        if stability_std > 0.2:
            return FusionStrategy.ADAPTIVE_FUSION, f"稳态差异大(std={stability_std:.2f})，自适应融合"
        
        # 4. 如果R²方差大，说明各段拟合质量差异大，使用质量加权
        if r2_std > 0.2 and r2_mean < 0.7:
            return FusionStrategy.QUALITY_WEIGHTED, f"R²方差大({r2_std:.2f})，质量加权融合"
        
        # 5. 根据 K 的一致性选择策略
        if K_cv < self.CV_THRESHOLD_CONSISTENT:
            # K一致性好
            if data_cv > 0.5 and len(windows) >= 2:
                return FusionStrategy.ROBUST_FUSION, f"K一致(CV={K_cv:.1%})，鲁棒融合"
            elif r2_mean >= 0.7:
                return FusionStrategy.WEIGHTED_FUSION, f"K一致(CV={K_cv:.1%})，R²加权融合"
            else:
                return FusionStrategy.MEDIAN_FUSION, f"K一致(CV={K_cv:.1%})，中位数融合"
        elif K_cv < self.CV_THRESHOLD_ACCEPTABLE:
            if len(windows) >= 3:
                return FusionStrategy.CROSS_VALIDATION, f"K有差异(CV={K_cv:.1%})，交叉验证"
            else:
                return FusionStrategy.MEDIAN_FUSION, f"K有差异(CV={K_cv:.1%})，中位数融合"
        else:
            # K差异大，使用中位数更稳健
            return FusionStrategy.MEDIAN_FUSION, f"K差异大(CV={K_cv:.1%})，中位数融合"
    
    def _weighted_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """R² 加权融合"""
        weights = [max(w.r2, 0.01) for w in windows]
        K, T1, T2, L = self._weighted_average_params(windows, weights)
        
        r2_mean = np.mean([w.r2 for w in windows])
        K_cv = self._safe_cv([w.K for w in windows])
        confidence = r2_mean * (1 - min(K_cv, 0.5))
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.WEIGHTED_FUSION,
            confidence=min(confidence, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
    
    def _best_window(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """选择最佳窗口"""
        best = max(windows, key=lambda w: w.r2)
        return StrategyFusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.BEST_WINDOW,
            confidence=min(best.r2, 1.0),
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _conservative_selection(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """保守选择"""
        sorted_by_k = sorted(windows, key=lambda w: w.K)
        mid_idx = len(sorted_by_k) // 2
        
        start = max(0, mid_idx - len(windows) // 3)
        end = min(len(windows), mid_idx + len(windows) // 3 + 1)
        candidates = sorted_by_k[start:end] or sorted_by_k
        
        best = max(candidates, key=lambda w: w.r2)
        
        return StrategyFusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.CONSERVATIVE,
            confidence=min(best.r2 * 0.9, 1.0),
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _recency_weighted(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """时效加权"""
        sorted_windows = sorted(windows, key=lambda w: w.window_idx)
        n = len(sorted_windows)
        decay = 0.7
        time_weights = [decay ** (n - 1 - i) for i in range(n)]
        
        weights = [tw * max(w.r2, 0.01) for tw, w in zip(time_weights, sorted_windows)]
        K, T1, T2, L = self._weighted_average_params(sorted_windows, weights)
        
        r2_mean = np.mean([w.r2 for w in sorted_windows])
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.RECENCY_WEIGHTED,
            confidence=min(r2_mean, 1.0),
            windows_used=[w.window_idx for w in sorted_windows],
            reasoning=reasoning
        )
    
    def _cross_validation(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """
        交叉验证策略
        
        改进：使用得分加权平均，而非只选最佳窗口
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 计算每个窗口的交叉验证得分
        scores = []
        for i, w_i in enumerate(windows):
            self_r2 = w_i.r2
            
            similarities = []
            for j, w_j in enumerate(windows):
                if i == j:
                    continue
                k_max = max(abs(w_i.K), abs(w_j.K), self.EPSILON)
                k_sim = 1 - min(abs(w_i.K - w_j.K) / k_max, 1)
                t1_max_val = max(w_i.T1, w_j.T1)
                t1_max = max(t1_max_val, 1.0) if t1_max_val < 0.1 else t1_max_val
                t1_sim = 1 - min(abs(w_i.T1 - w_j.T1) / t1_max, 1)
                sim = (k_sim * 0.6 + t1_sim * 0.4) * w_j.r2
                similarities.append(sim)
            
            avg_sim = np.mean(similarities) if similarities else 0
            score = self_r2 * 0.6 + avg_sim * 0.4
            scores.append(score)
        
        # 使用得分作为权重进行加权平均
        total_score = sum(scores)
        if total_score < self.EPSILON:
            return self._best_window(windows, reasoning)
        
        # 归一化权重
        weights = [s / total_score for s in scores]
        
        K, T1, T2, L = self._weighted_average_params(windows, weights)
        
        # 计算置信度
        confidence = sum(w.r2 * wt for w, wt in zip(windows, weights))
        
        # 记录主要贡献的窗口（权重>15%）
        windows_used = [w.window_idx for w, wt in zip(windows, weights) if wt > 0.15]
        if not windows_used:
            windows_used = [max(zip(windows, weights), key=lambda x: x[1])[0].window_idx]
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.CROSS_VALIDATION,
            confidence=min(confidence, 1.0),
            windows_used=windows_used,
            reasoning=reasoning
        )
    
    def _robust_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """鲁棒融合策略"""
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        K_median = np.median([w.K for w in windows])
        K_median_abs = max(abs(K_median), self.EPSILON)
        T1_median = np.median([w.T1 for w in windows])
        T1_median_safe = max(T1_median, 1.0) if T1_median < 0.1 else T1_median
        
        robust_weights = []
        for w in windows:
            k_consistency = 1 - min(abs(w.K - K_median) / K_median_abs, 1)
            t1_consistency = 1 - min(abs(w.T1 - T1_median) / T1_median_safe, 1)
            consistency = k_consistency * 0.7 + t1_consistency * 0.3
            
            data_factor = np.sqrt(w.data_points / 50)
            weight = max(w.r2, 0.01) * consistency * min(data_factor, 2.0)
            robust_weights.append(weight)
        
        K, T1, T2, L = self._weighted_average_params(windows, robust_weights)
        
        total_weight = sum(robust_weights) if sum(robust_weights) > self.EPSILON else 1.0
        r2_weighted = sum(w.r2 * wt for w, wt in zip(windows, robust_weights)) / total_weight
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.ROBUST_FUSION,
            confidence=min(r2_weighted, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
    
    def _median_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """
        中位数融合策略
        
        使用中位数而非均值，对异常值更鲁棒
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        K = float(np.median([w.K for w in windows]))
        T1 = float(np.median([w.T1 for w in windows]))
        T2 = float(np.median([w.T2 for w in windows]))
        L = float(np.median([w.L for w in windows]))
        
        r2_median = float(np.median([w.r2 for w in windows]))
        K_cv = self._safe_cv([w.K for w in windows])
        confidence = r2_median * (1 - min(K_cv, 0.5))
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.MEDIAN_FUSION,
            confidence=min(confidence, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
    
    def _quality_weighted_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """
        质量加权融合策略
        
        根据拟合质量(R²)进行更激进的加权，高质量段权重更大
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 使用R²的平方作为权重，让高质量段占主导
        weights = [(w.r2 ** 2) * w.data_points for w in windows]
        total_weight = sum(weights)
        
        if total_weight < self.EPSILON:
            # 所有权重都很小，回退到中位数
            return self._median_fusion(windows, reasoning)
        
        K = sum(w.K * wt for w, wt in zip(windows, weights)) / total_weight
        T1 = sum(w.T1 * wt for w, wt in zip(windows, weights)) / total_weight
        T2 = sum(w.T2 * wt for w, wt in zip(windows, weights)) / total_weight
        L = sum(w.L * wt for w, wt in zip(windows, weights)) / total_weight
        
        # 计算置信度
        r2_weighted = sum(w.r2 * wt for w, wt in zip(windows, weights)) / total_weight
        
        # 找出主要贡献的窗口（权重占比>10%）
        windows_used = [w.window_idx for w, wt in zip(windows, weights) 
                       if wt / total_weight > 0.1]
        if not windows_used:
            windows_used = [max(zip(windows, weights), key=lambda x: x[1])[0].window_idx]
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.QUALITY_WEIGHTED,
            confidence=min(r2_weighted, 1.0),
            windows_used=windows_used,
            reasoning=reasoning
        )
    
    def _stability_weighted_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """
        稳态加权融合策略
        
        专门处理存在非稳态扰动段的情况：
        1. 稳态段给予更高权重
        2. 非稳态段根据收敛质量给予适当权重
        3. 振荡段权重降低
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 计算每个窗口的稳态权重
        stability_weights = []
        for w in windows:
            # 基础权重 = R² × 稳态评分 × 收敛质量
            base_weight = w.r2 * w.stability_score * w.settling_quality
            
            # 振荡惩罚：振荡比例越高，权重越低
            oscillation_penalty = 1.0 - 0.5 * w.oscillation_ratio
            
            # 数据量因子（较大的数据集更可靠）
            data_factor = np.sqrt(w.data_points / 100) if w.data_points > 0 else 0.1
            data_factor = min(data_factor, 2.0)  # 上限
            
            # 最终权重
            weight = base_weight * oscillation_penalty * data_factor
            stability_weights.append(max(weight, 0.01))
            
            self.log(f"   窗口{w.window_idx+1}: R²={w.r2:.3f}, 稳态={w.stability_score:.2f}, "
                    f"收敛={w.settling_quality:.2f}, 振荡={w.oscillation_ratio:.2f} → 权重={weight:.4f}")
        
        total_weight = sum(stability_weights)
        if total_weight < self.EPSILON:
            return self._median_fusion(windows, reasoning)
        
        # 加权平均
        K = sum(w.K * wt for w, wt in zip(windows, stability_weights)) / total_weight
        T1 = sum(w.T1 * wt for w, wt in zip(windows, stability_weights)) / total_weight
        T2 = sum(w.T2 * wt for w, wt in zip(windows, stability_weights)) / total_weight
        L = sum(w.L * wt for w, wt in zip(windows, stability_weights)) / total_weight
        
        # 置信度：考虑稳态质量
        avg_stability = np.mean([w.stability_score for w in windows])
        r2_weighted = sum(w.r2 * wt for w, wt in zip(windows, stability_weights)) / total_weight
        confidence = r2_weighted * avg_stability
        
        # 找出主要贡献的窗口
        windows_used = [w.window_idx for w, wt in zip(windows, stability_weights) 
                       if wt / total_weight > 0.1]
        if not windows_used:
            windows_used = [max(zip(windows, stability_weights), key=lambda x: x[1])[0].window_idx]
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.STABILITY_WEIGHTED,
            confidence=min(confidence, 1.0),
            windows_used=windows_used,
            reasoning=reasoning
        )
    
    def _adaptive_fusion(self, windows: List[WindowResult], reasoning: str) -> StrategyFusionResult:
        """
        自适应融合策略（增强版 - 处理非线性和低质量段）
        
        综合考虑多个因素自动选择最优融合方式：
        1. 分离稳态段和非稳态段
        2. 过滤掉高非线性段
        3. 优先使用高质量稳态段的参数
        4. 非稳态段用于验证和微调
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 首先过滤掉高非线性段
        linear_windows = [w for w in windows if getattr(w, 'nonlinearity_score', 0) < 0.6]
        if not linear_windows:
            # 如果所有段都是非线性的，使用原始数据但记录警告
            self.log("   ⚠️ 所有段都具有高非线性，使用鲁棒融合")
            linear_windows = windows
        elif len(linear_windows) < len(windows):
            filtered_count = len(windows) - len(linear_windows)
            self.log(f"   过滤掉 {filtered_count} 个高非线性段")
        
        # 分离稳态段和非稳态段（同时考虑质量分）
        steady_windows = [w for w in linear_windows 
                         if w.is_steady and w.stability_score >= 0.7 
                         and getattr(w, 'quality_score', 1.0) >= 0.5]
        unsteady_windows = [w for w in linear_windows 
                           if not w.is_steady or w.stability_score < 0.7 
                           or getattr(w, 'quality_score', 1.0) < 0.5]
        
        self.log(f"   稳态段: {len(steady_windows)}, 非稳态段: {len(unsteady_windows)}")
        
        # 情况1：有足够的稳态段，主要使用稳态段
        if len(steady_windows) >= 2:
            self.log("   → 使用稳态段进行融合")
            # 对稳态段使用质量加权
            weights = [(w.r2 ** 2) * w.data_points * w.stability_score for w in steady_windows]
            total_weight = sum(weights)
            
            if total_weight > self.EPSILON:
                K = sum(w.K * wt for w, wt in zip(steady_windows, weights)) / total_weight
                T1 = sum(w.T1 * wt for w, wt in zip(steady_windows, weights)) / total_weight
                T2 = sum(w.T2 * wt for w, wt in zip(steady_windows, weights)) / total_weight
                L = sum(w.L * wt for w, wt in zip(steady_windows, weights)) / total_weight
                
                r2_weighted = sum(w.r2 * wt for w, wt in zip(steady_windows, weights)) / total_weight
                windows_used = [w.window_idx for w in steady_windows]
                
                return StrategyFusionResult(
                    K=K, T1=T1, T2=T2, L=L,
                    strategy_used=FusionStrategy.ADAPTIVE_FUSION,
                    confidence=min(r2_weighted, 1.0),
                    windows_used=windows_used,
                    reasoning=reasoning + " (稳态段主导)"
                )
        
        # 情况2：只有一个稳态段，以稳态段为主，非稳态段辅助
        if len(steady_windows) == 1:
            self.log("   → 以唯一稳态段为主")
            w_steady = steady_windows[0]
            
            # 基础参数来自稳态段
            K, T1, T2, L = w_steady.K, w_steady.T1, w_steady.T2, w_steady.L
            
            # 如果有非稳态段且K值一致，做微调
            if unsteady_windows:
                K_values = [w.K for w in unsteady_windows]
                K_median = np.median(K_values)
                
                # 如果非稳态段的K与稳态段接近，做加权平均
                if abs(K_median - K) / (abs(K) + self.EPSILON) < 0.3:
                    # 稳态段权重70%，非稳态段权重30%
                    unsteady_K = np.mean([w.K for w in unsteady_windows])
                    K = 0.7 * K + 0.3 * unsteady_K
                    self.log(f"   微调K: 稳态={w_steady.K:.4f}, 非稳态均值={unsteady_K:.4f} → {K:.4f}")
            
            return StrategyFusionResult(
                K=K, T1=T1, T2=T2, L=L,
                strategy_used=FusionStrategy.ADAPTIVE_FUSION,
                confidence=min(w_steady.r2 * w_steady.stability_score, 1.0),
                windows_used=[w_steady.window_idx],
                reasoning=reasoning + " (稳态段+非稳态微调)"
            )
        
        # 情况3：没有稳态段，从非稳态段中提取最可靠的参数
        self.log("   → 无稳态段，从非稳态段提取参数")
        
        # 按 effective_weight 排序，选择最可靠的
        sorted_windows = sorted(windows, key=lambda w: w.effective_weight, reverse=True)
        
        # 使用收敛质量最好的段为主
        best_window = sorted_windows[0]
        
        # 计算所有非稳态段的中位数作为参考
        K_median = np.median([w.K for w in windows])
        T1_median = np.median([w.T1 for w in windows])
        
        # 如果最佳段与中位数差异不大，使用最佳段
        if abs(best_window.K - K_median) / (abs(K_median) + self.EPSILON) < 0.5:
            K, T1, T2, L = best_window.K, best_window.T1, best_window.T2, best_window.L
            windows_used = [best_window.window_idx]
        else:
            # 差异大，使用鲁棒的中位数
            K = K_median
            T1 = T1_median
            T2 = float(np.median([w.T2 for w in windows]))
            L = float(np.median([w.L for w in windows]))
            windows_used = [w.window_idx for w in windows]
        
        # 置信度降低（因为没有稳态段）
        confidence = max([w.effective_weight for w in windows]) * 0.8
        
        return StrategyFusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.ADAPTIVE_FUSION,
            confidence=min(confidence, 1.0),
            windows_used=windows_used,
            reasoning=reasoning + " (非稳态段鲁棒融合)"
        )
