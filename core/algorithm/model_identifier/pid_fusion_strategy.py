import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum


class FusionStrategy(Enum):
    """融合策略枚举"""
    WEIGHTED_FUSION = "weighted_fusion"      # R² 加权融合
    BEST_WINDOW = "best_window"              # 最佳窗口
    CONSERVATIVE = "conservative"            # 保守选择
    RECENCY_WEIGHTED = "recency_weighted"    # 时效加权
    CROSS_VALIDATION = "cross_validation"    # 交叉验证（选泛化最好的）
    ROBUST_FUSION = "robust_fusion"          # 鲁棒融合（综合考虑一致性+R²）


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
    timestamp: Optional[float] = None  # 窗口时间戳（用于时效加权）
    
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
    confidence: float  # 置信度 0-1
    windows_used: List[int]  # 使用的窗口索引
    reasoning: str  # 决策原因


class PIDFusionStrategy:
    """
    多扰动段 PID 参数融合策略
    
    使用方法：
        fusion = PIDFusionStrategy(verbose=True)
        result = fusion.fuse(window_results)
    """
    
    # 策略阈值
    CV_THRESHOLD_CONSISTENT = 0.2   # K 变异系数 <20% 认为一致
    CV_THRESHOLD_ACCEPTABLE = 0.5   # K 变异系数 <50% 认为可接受
    MIN_R2_THRESHOLD = 0.5          # R² 阈值
    K_OUTLIER_FACTOR = 3.0          # K 异常值倍数
    EPSILON = 1e-8                  # 防止除零
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    def _safe_cv(self, values: List[float]) -> float:
        """安全计算变异系数（支持负值）"""
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
        """
        融合多窗口参数
        
        Args:
            window_results: 各窗口的辨识结果
            force_strategy: 强制使用指定策略（可选）
        
        Returns:
            FusionResult: 融合结果
        """
        if not window_results:
            raise ValueError("没有有效的窗口结果")
        
        # 单窗口直接返回
        if len(window_results) == 1:
            w = window_results[0]
            return FusionResult(
                K=w.K, T1=w.T1, T2=w.T2, L=w.L,
                strategy_used=FusionStrategy.BEST_WINDOW,
                confidence=min(w.r2, 1.0),
                windows_used=[w.window_idx],
                reasoning="单窗口，直接使用"
            )
        
        # Step 1: 过滤异常窗口
        valid_windows = self._filter_windows(window_results)
        
        if not valid_windows:
            self.log("⚠️ 过滤后无有效窗口，使用全部窗口")
            valid_windows = window_results
        
        # Step 2: 确定策略
        if force_strategy:
            strategy = force_strategy
            reasoning = f"强制使用策略: {strategy.value}"
        else:
            strategy, reasoning = self._determine_strategy(valid_windows)
        
        self.log(f"📋 选择策略: {strategy.value} - {reasoning}")
        
        # Step 3: 执行融合
        if strategy == FusionStrategy.WEIGHTED_FUSION:
            return self._weighted_fusion(valid_windows, reasoning)
        elif strategy == FusionStrategy.BEST_WINDOW:
            return self._best_window(valid_windows, reasoning)
        elif strategy == FusionStrategy.CONSERVATIVE:
            return self._conservative_selection(valid_windows, reasoning)
        elif strategy == FusionStrategy.RECENCY_WEIGHTED:
            return self._recency_weighted(valid_windows, reasoning)
        elif strategy == FusionStrategy.CROSS_VALIDATION:
            return self._cross_validation(valid_windows, reasoning)
        elif strategy == FusionStrategy.ROBUST_FUSION:
            return self._robust_fusion(valid_windows, reasoning)
        else:
            return self._weighted_fusion(valid_windows, reasoning)
    
    def _filter_windows(self, windows: List[WindowResult]) -> List[WindowResult]:
        """
        过滤异常窗口
        
        过滤条件：
        1. K 值偏离中位数超过 3 倍（支持负值）
        2. R² < 0.5
        """
        if len(windows) <= 1:
            return windows
        
        # Step 1: K 值异常过滤（使用绝对值处理反向作用系统）
        K_values = [w.K for w in windows]
        K_median = np.median(K_values)
        K_median_abs = abs(K_median)
        
        valid = []
        for w in windows:
            # K 异常检查（使用绝对值比较，支持负 K）
            if K_median_abs > self.EPSILON:
                k_ratio = abs(w.K) / K_median_abs
                # 同时检查符号一致性（同一过程 K 应同号）
                sign_mismatch = np.sign(w.K) != np.sign(K_median) and abs(w.K) > self.EPSILON
                if k_ratio < 1/self.K_OUTLIER_FACTOR or k_ratio > self.K_OUTLIER_FACTOR or sign_mismatch:
                    reason = "符号不一致" if sign_mismatch else f"偏离中位数 {K_median:.4f}"
                    self.log(f"   ⚠️ 剔除窗口{w.window_idx}: K={w.K:.4f} {reason}")
                    continue
            
            # R² 检查
            if w.r2 < self.MIN_R2_THRESHOLD:
                self.log(f"   ⚠️ 剔除窗口{w.window_idx}: R²={w.r2:.4f} < {self.MIN_R2_THRESHOLD}")
                continue
            
            valid.append(w)
        
        return valid
    
    def _determine_strategy(self, windows: List[WindowResult]) -> Tuple[FusionStrategy, str]:
        """
        根据数据特征自动确定最优融合策略
        
        决策树：
        1. K 一致性好 (CV<20%):
           - 数据量差异大 → robust_fusion (综合R²+一致性+数据量)
           - 数据量相近 → weighted_fusion (简单R²加权)
        2. K 有差异 (20%≤CV<50%):
           - 多窗口 → cross_validation (选泛化最好的)
           - 单窗口 → best_window
        3. K 差异大 (CV≥50%):
           - conservative (保守选择)
        """
        K_values = [w.K for w in windows]
        K_cv = self._safe_cv(K_values)  # 使用安全的变异系数计算
        
        r2_values = [w.r2 for w in windows]
        r2_mean = np.mean(r2_values)
        r2_min = np.min(r2_values)
        
        # 数据量统计
        data_points = [w.data_points for w in windows]
        data_cv = np.std(data_points) / np.mean(data_points) if np.mean(data_points) > 0 else 0
        
        self.log(f"📊 K 统计: mean={np.mean(K_values):.4f}, std={np.std(K_values):.4f}, CV={K_cv:.2%}")
        self.log(f"📊 R² 统计: mean={r2_mean:.4f}, min={r2_min:.4f}")
        self.log(f"📊 数据量: {data_points}, CV={data_cv:.1%}")
        
        # 决策逻辑
        if K_cv < self.CV_THRESHOLD_CONSISTENT:
            # K 一致性好
            if data_cv > 0.5 and len(windows) >= 2:
                # 数据量差异大，用鲁棒融合（考虑数据量权重）
                return FusionStrategy.ROBUST_FUSION, f"K一致(CV={K_cv:.1%})，数据量差异大，鲁棒融合"
            else:
                # 数据量相近，简单加权
                return FusionStrategy.WEIGHTED_FUSION, f"K一致(CV={K_cv:.1%})，R²加权融合"
        
        elif K_cv < self.CV_THRESHOLD_ACCEPTABLE:
            # K 有差异但可接受
            if len(windows) >= 3:
                # 多窗口，用交叉验证选泛化最好的
                return FusionStrategy.CROSS_VALIDATION, f"K有差异(CV={K_cv:.1%})，交叉验证选最优"
            else:
                # 窗口少，用最佳窗口
                return FusionStrategy.BEST_WINDOW, f"K有差异(CV={K_cv:.1%})，使用最佳窗口"
        
        else:
            # K 差异大，保守选择
            return FusionStrategy.CONSERVATIVE, f"K差异大(CV={K_cv:.1%}>50%)，保守选择"
    
    def _weighted_fusion(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        R² 加权融合
        """
        # 使用 R² 作为权重
        weights = [max(w.r2, 0.01) for w in windows]
        K, T1, T2, L = self._weighted_average_params(windows, weights)
        
        # 置信度：基于 R² 均值和一致性
        r2_mean = np.mean([w.r2 for w in windows])
        K_cv = self._safe_cv([w.K for w in windows])
        confidence = r2_mean * (1 - min(K_cv, 0.5))  # 一致性越高，置信度越高
        
        self.log(f"✅ R²加权融合: K={K:.4f}, T1={T1:.4f}, T2={T2:.4f}, L={L:.4f}")
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.WEIGHTED_FUSION,
            confidence=min(confidence, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )
    
    def _best_window(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        选择最佳窗口（R² 最高）
        """
        best = max(windows, key=lambda w: w.r2)
        
        self.log(f"✅ 最佳窗口{best.window_idx}: K={best.K:.4f}, T1={best.T1:.4f}, R²={best.r2:.4f}")
        
        return FusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.BEST_WINDOW,
            confidence=min(best.r2, 1.0),
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _conservative_selection(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        保守选择：选 K 较小的窗口（更安全的 PID）
        
        K 小 → PID 的 Kp 大 → 但整体响应更保守
        这里选择 K 值在中位数附近且 R² 较高的窗口
        """
        # 按 K 排序，选中位数附近的
        sorted_by_k = sorted(windows, key=lambda w: w.K)
        mid_idx = len(sorted_by_k) // 2
        
        # 在中间 1/3 的窗口中选 R² 最高的
        start = max(0, mid_idx - len(windows) // 3)
        end = min(len(windows), mid_idx + len(windows) // 3 + 1)
        candidates = sorted_by_k[start:end]
        
        if not candidates:
            candidates = sorted_by_k
        
        best = max(candidates, key=lambda w: w.r2)
        
        self.log(f"✅ 保守选择窗口{best.window_idx}: K={best.K:.4f} (中位数附近), R²={best.r2:.4f}")
        
        return FusionResult(
            K=best.K, T1=best.T1, T2=best.T2, L=best.L,
            strategy_used=FusionStrategy.CONSERVATIVE,
            confidence=min(best.r2 * 0.9, 1.0),  # 略降低置信度
            windows_used=[best.window_idx],
            reasoning=reasoning
        )
    
    def _recency_weighted(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        时效加权：近期窗口权重更高
        """
        # 按时间排序（假设 window_idx 越大越近期）
        sorted_windows = sorted(windows, key=lambda w: w.window_idx)
        
        # 时效权重：指数衰减
        n = len(sorted_windows)
        decay = 0.7  # 衰减因子
        time_weights = [decay ** (n - 1 - i) for i in range(n)]
        
        # 结合 R² 权重
        weights = [tw * max(w.r2, 0.01) for tw, w in zip(time_weights, sorted_windows)]
        K, T1, T2, L = self._weighted_average_params(sorted_windows, weights)
        
        # 置信度
        r2_mean = np.mean([w.r2 for w in sorted_windows])
        
        self.log(f"✅ 时效加权: K={K:.4f}, T1={T1:.4f}, T2={T2:.4f}, L={L:.4f}")
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.RECENCY_WEIGHTED,
            confidence=min(r2_mean, 1.0),
            windows_used=[w.window_idx for w in sorted_windows],
            reasoning=reasoning
        )
    
    def _cross_validation(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        交叉验证策略：选择泛化能力最强的窗口参数
        
        思路：
        - 用窗口 A 的参数，计算在其他窗口上的"预期 R²"
        - 选择在其他窗口上表现也好的参数（泛化能力强）
        
        评分 = 自身 R² × 0.5 + 其他窗口平均"相似度" × 0.5
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 计算每个窗口的泛化评分
        scores = []
        for i, w_i in enumerate(windows):
            # 自身 R²
            self_r2 = w_i.r2
            
            # 与其他窗口参数的相似度（基于 K 和 T1）
            similarities = []
            for j, w_j in enumerate(windows):
                if i == j:
                    continue
                # 参数相似度：使用绝对值处理负 K
                k_max = max(abs(w_i.K), abs(w_j.K), self.EPSILON)
                k_sim = 1 - min(abs(w_i.K - w_j.K) / k_max, 1)
                t1_max = max(w_i.T1, w_j.T1, self.EPSILON)
                t1_sim = 1 - min(abs(w_i.T1 - w_j.T1) / t1_max, 1)
                # 考虑对方窗口的 R²（对方 R² 高，参考价值大）
                sim = (k_sim * 0.6 + t1_sim * 0.4) * w_j.r2
                similarities.append(sim)
            
            avg_sim = np.mean(similarities) if similarities else 0
            
            # 综合评分 = 自身 R² + 泛化相似度
            score = self_r2 * 0.6 + avg_sim * 0.4
            scores.append((w_i, score))
            
            self.log(f"   窗口{w_i.window_idx}: 自身R²={self_r2:.3f}, 泛化分={avg_sim:.3f}, 总分={score:.3f}")
        
        # 选择评分最高的窗口
        best_window, best_score = max(scores, key=lambda x: x[1])
        
        self.log(f"✅ 交叉验证选择窗口{best_window.window_idx}: K={best_window.K:.4f}, 综合分={best_score:.3f}")
        
        return FusionResult(
            K=best_window.K, T1=best_window.T1, T2=best_window.T2, L=best_window.L,
            strategy_used=FusionStrategy.CROSS_VALIDATION,
            confidence=min(best_score, 1.0),
            windows_used=[best_window.window_idx],
            reasoning=reasoning
        )
    
    def _robust_fusion(self, windows: List[WindowResult], reasoning: str) -> FusionResult:
        """
        鲁棒融合策略：综合考虑 R²、一致性、数据量
        
        权重 = R² × 一致性得分 × sqrt(数据量)
        
        一致性得分：该窗口的参数与其他窗口中位数的接近程度
        """
        if len(windows) < 2:
            return self._best_window(windows, reasoning)
        
        # 计算中位数作为参考（使用绝对值处理负 K）
        K_median = np.median([w.K for w in windows])
        K_median_abs = max(abs(K_median), self.EPSILON)
        T1_median = np.median([w.T1 for w in windows])
        T1_median_safe = max(T1_median, self.EPSILON)
        
        # 计算每个窗口的鲁棒权重
        robust_weights = []
        for w in windows:
            # 一致性得分（与中位数的接近程度，支持负 K）
            k_consistency = 1 - min(abs(w.K - K_median) / K_median_abs, 1)
            t1_consistency = 1 - min(abs(w.T1 - T1_median) / T1_median_safe, 1)
            consistency = k_consistency * 0.7 + t1_consistency * 0.3
            
            # 数据量因子
            data_factor = np.sqrt(w.data_points / 50)  # 归一化到 50 点
            
            # 综合权重
            weight = max(w.r2, 0.01) * consistency * min(data_factor, 2.0)
            robust_weights.append(weight)
            
            self.log(f"   窗口{w.window_idx}: R²={w.r2:.3f}, 一致性={consistency:.3f}, "
                     f"数据={w.data_points}点, 权重={weight:.3f}")
        
        # 加权平均
        K, T1, T2, L = self._weighted_average_params(windows, robust_weights)
        
        # 置信度
        total_weight = sum(robust_weights) if sum(robust_weights) > self.EPSILON else 1.0
        r2_weighted = sum(w.r2 * wt for w, wt in zip(windows, robust_weights)) / total_weight
        
        self.log(f"✅ 鲁棒融合: K={K:.4f}, T1={T1:.4f}, 置信度={r2_weighted:.3f}")
        
        return FusionResult(
            K=K, T1=T1, T2=T2, L=L,
            strategy_used=FusionStrategy.ROBUST_FUSION,
            confidence=min(r2_weighted, 1.0),
            windows_used=[w.window_idx for w in windows],
            reasoning=reasoning
        )