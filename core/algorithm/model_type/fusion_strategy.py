"""PID参数融合策略模块 - 多扰动段参数智能融合"""

import numpy as np
from typing import Dict, List, Optional, Tuple
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
    
    @property
    def params_dict(self) -> Dict[str, float]:
        return {'K': self.K, 'T1': self.T1, 'T2': self.T2, 'L': self.L}


@dataclass
class FusionResult:
    """融合结果"""
    K: float
    T1: float
    T2: float
    L: float
    strategy_used: FusionStrategy
    confidence: float
    windows_used: List[int]
    reasoning: str


class PIDFusionStrategy:
    """多扰动段 PID 参数融合策略"""
    
    # 策略阈值
    CV_THRESHOLD_CONSISTENT = 0.2
    CV_THRESHOLD_ACCEPTABLE = 0.5
    MIN_R2_THRESHOLD = 0.5
    K_OUTLIER_FACTOR = 3.0
    EPSILON = 1e-8
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
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
             force_strategy: Optional[FusionStrategy] = None) -> FusionResult:
        """融合多窗口参数"""
        if not window_results:
            raise ValueError("没有有效的窗口结果")
        
        if len(window_results) == 1:
            w = window_results[0]
            return FusionResult(
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
        }
        
        method = strategy_methods.get(strategy, self._weighted_fusion)
        return method(valid_windows, reasoning)
    
    def _filter_windows(self, windows: List[WindowResult]) -> List[WindowResult]:
        """过滤异常窗口"""
        if len(windows) <= 1:
            return windows
        
        K_values = [w.K for w in windows]
        K_median = np.median(K_values)
        K_median_abs = abs(K_median)
        
        valid = []
        for w in windows:
            if K_median_abs > self.EPSILON:
                k_ratio = abs(w.K) / K_median_abs
                sign_mismatch = np.sign(w.K) != np.sign(K_median) and abs(w.K) > self.EPSILON
                if k_ratio < 1/self.K_OUTLIER_FACTOR or k_ratio > self.K_OUTLIER_FACTOR or sign_mismatch:
                    continue
            
            if w.r2 < self.MIN_R2_THRESHOLD:
                continue
            
            valid.append(w)
        
        return valid
    
    def _determine_strategy(self, windows: List[WindowResult]) -> Tuple[FusionStrategy, str]:
        """确定最优融合策略"""
        K_values = [w.K for w in windows]
        K_cv = self._safe_cv(K_values)
        
        data_points = [w.data_points for w in windows]
        data_cv = np.std(data_points) / np.mean(data_points) if np.mean(data_points) > 0 else 0
        
        if K_cv < self.CV_THRESHOLD_CONSISTENT:
            if data_cv > 0.5 and len(windows) >= 2:
                return FusionStrategy.ROBUST_FUSION, f"K一致(CV={K_cv:.1%})，鲁棒融合"
            else:
                return FusionStrategy.WEIGHTED_FUSION, f"K一致(CV={K_cv:.1%})，R²加权融合"
        elif K_cv < self.CV_THRESHOLD_ACCEPTABLE:
            if len(windows) >= 3:
                return FusionStrategy.CROSS_VALIDATION, f"K有差异(CV={K_cv:.1%})，交叉验证"
            else:
                return FusionStrategy.BEST_WINDOW, f"K有差异(CV={K_cv:.1%})，最佳窗口"
        else:
            return FusionStrategy.CONSERVATIVE, f"K差异大(CV={K_cv:.1%})，保守选择"
    
    def _weighted_fusion(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """R² 加权融合"""
        weights = [max(w.r2, 0.01) for w in windows]
        K, T1, T2, L = self._weighted_average_params(windows, weights)
        
        r2_mean = np.mean([w.r2 for w in windows])
        K_cv = self._safe_cv([w.K for w in windows])
        confidence = r2_mean * (1 - min(K_cv, 0.5))
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.WEIGHTED_FUSION,
            confidence=min(confidence, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
    
    def _best_window(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """选择最佳窗口"""
        best = max(windows, key=lambda w: w.r2)
        return FusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.BEST_WINDOW,
            confidence=min(best.r2, 1.0),
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _conservative_selection(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """保守选择"""
        sorted_by_k = sorted(windows, key=lambda w: w.K)
        mid_idx = len(sorted_by_k) // 2
        
        start = max(0, mid_idx - len(windows) // 3)
        end = min(len(windows), mid_idx + len(windows) // 3 + 1)
        candidates = sorted_by_k[start:end] or sorted_by_k
        
        best = max(candidates, key=lambda w: w.r2)
        
        return FusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.CONSERVATIVE,
            confidence=min(best.r2 * 0.9, 1.0),
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _recency_weighted(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """时效加权"""
        sorted_windows = sorted(windows, key=lambda w: w.window_idx)
        n = len(sorted_windows)
        decay = 0.7
        time_weights = [decay ** (n - 1 - i) for i in range(n)]
        
        weights = [tw * max(w.r2, 0.01) for tw, w in zip(time_weights, sorted_windows)]
        K, T1, T2, L = self._weighted_average_params(sorted_windows, weights)
        
        r2_mean = np.mean([w.r2 for w in sorted_windows])
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.RECENCY_WEIGHTED,
            confidence=min(r2_mean, 1.0),
            windows_used=[w.window_idx for w in sorted_windows],
            reasoning=reasoning
        )
    
    def _cross_validation(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """交叉验证策略"""
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        scores = []
        for i, w_i in enumerate(windows):
            self_r2 = w_i.r2
            
            similarities = []
            for j, w_j in enumerate(windows):
                if i == j:
                    continue
                k_max = max(abs(w_i.K), abs(w_j.K), self.EPSILON)
                k_sim = 1 - min(abs(w_i.K - w_j.K) / k_max, 1)
                t1_max = max(w_i.T1, w_j.T1, self.EPSILON)
                t1_sim = 1 - min(abs(w_i.T1 - w_j.T1) / t1_max, 1)
                sim = (k_sim * 0.6 + t1_sim * 0.4) * w_j.r2
                similarities.append(sim)
            
            avg_sim = np.mean(similarities) if similarities else 0
            score = self_r2 * 0.6 + avg_sim * 0.4
            scores.append((w_i, score))
        
        best_window, best_score = max(scores, key=lambda x: x[1])
        
        return FusionResult(
            K=best_window.K, T1=best_window.T1, T2=best_window.T2, L=best_window.L,
            strategy_used=FusionStrategy.CROSS_VALIDATION,
            confidence=min(best_score, 1.0),
            windows_used=[best_window.window_idx],
            reasoning=reasoning
        )
    
    def _robust_fusion(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """鲁棒融合策略"""
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        K_median = np.median([w.K for w in windows])
        K_median_abs = max(abs(K_median), self.EPSILON)
        T1_median = np.median([w.T1 for w in windows])
        T1_median_safe = max(T1_median, self.EPSILON)
        
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
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.ROBUST_FUSION,
            confidence=min(r2_weighted, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
