"""
参数融合模块 (Parameter Fusion Module)
======================================

从 model_selector.py 提取的参数融合逻辑。

核心功能：
- 从多个扰动段的拟合结果中融合出统一的模型参数 (K, T1, T2, L)
- 支持多级阈值筛选
- 支持质量加权融合

使用方法：
    fusion = ParameterFusion(segment_processor, verbose=True)
    result = fusion.fuse(segment_results, model_type, segments)
"""

import numpy as np
from typing import List, Optional

from ..config import Config
from ..data_models import SegmentResult, FusionResult, HistoricalData
from ..logger import LoggerMixin
from .fusion_strategy import PIDFusionStrategy, WindowResult as FusionWindowResult


class ParameterFusion(LoggerMixin):
    """
    参数融合器 - 从多段拟合结果中融合最终模型参数
    
    职责：
    1. 按质量阈值筛选有效段
    2. 评估段稳态质量
    3. 调用 PIDFusionStrategy 进行加权融合
    4. 应用参数约束
    """
    
    # 验证阈值常量 (从配置读取)
    MIN_R2_FOR_VOTE = Config.MODEL_SELECTOR['min_r2_for_vote']
    MIN_R2_FOR_QUALITY = Config.MODEL_SELECTOR['min_r2_for_quality']
    R2_THRESHOLDS = Config.MODEL_SELECTOR['r2_thresholds']
    
    def __init__(self, segment_processor, verbose: bool = False):
        """
        Args:
            segment_processor: SegmentProcessor 实例，用于分析段稳态质量
            verbose: 是否输出详细日志
        """
        self._init_logger(verbose)
        self._segment_processor = segment_processor
    
    def fuse(self, segment_results: List[SegmentResult],
             model_type: str,
             segments: List[HistoricalData] = None) -> FusionResult:
        """
        融合各段参数
        
        Args:
            segment_results: 各段拟合结果
            model_type: 目标模型类型
            segments: 原始段数据（用于稳态分析）
            
        Returns:
            FusionResult: 融合后的参数
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 4: 参数融合")
        self.log('='*60)
        
        fusion = FusionResult(model_type=model_type)
        
        # 收集有效窗口
        window_results = self._collect_valid_windows(segment_results, model_type, segments)
        
        if not window_results:
            self.log("   ⚠️ 无有效参数，使用默认值")
            return fusion
        
        # 打印收集结果
        steady_count = sum(1 for w in window_results if w.is_steady)
        avg_stability = np.mean([w.stability_score for w in window_results])
        
        self.log(f"   收集到 {len(window_results)} 个有效段 (稳态段: {steady_count}, 平均稳态评分: {avg_stability:.2f}):")
        for w in window_results:
            steady_flag = "✓稳态" if w.is_steady else "⚠非稳态"
            self.log(f"      段{w.window_idx+1}: K={w.K:.4f}, T1={w.T1:.2f}, R²={w.r2:.3f}, "
                    f"稳态={w.stability_score:.2f} {steady_flag}")
        
        # 执行融合
        fusion = self._execute_fusion(window_results, fusion, model_type)
        
        # 应用参数约束
        fusion = self._apply_constraints(fusion)
        
        # 打印最终结果
        self.log(f"\n   融合结果 ({fusion.fusion_method}, {fusion.n_segments_used}段):")
        self.log(f"   K  = {fusion.K:.4f} ± {fusion.K_std:.4f}")
        self.log(f"   T1 = {fusion.T1:.2f} ± {fusion.T1_std:.2f}")
        self.log(f"   T2 = {fusion.T2:.2f}")
        self.log(f"   L  = {fusion.L:.2f}")
        self.log(f"   一致性评分: {fusion.consistency_score:.2f}")
        
        return fusion
    
    def _collect_valid_windows(self, segment_results: List[SegmentResult],
                               model_type: str,
                               segments: List[HistoricalData] = None) -> List[FusionWindowResult]:
        """按多级阈值收集有效窗口"""
        window_results = []
        added_indices = set()
        
        for threshold in self.R2_THRESHOLDS:
            valid_segment_idx = 0
            for result in segment_results:
                if not result.is_valid:
                    continue
                
                if result.segment_idx in added_indices:
                    valid_segment_idx += 1
                    continue
                
                fit_result = result.model_results.get(model_type)
                if fit_result is None:
                    valid_segment_idx += 1
                    continue
                
                r2 = fit_result.get('r2', 0)
                if r2 < threshold:
                    valid_segment_idx += 1
                    continue
                
                K, T1 = fit_result.get('K', 0), fit_result.get('T1', 0)
                if K == 0 and T1 == 0:
                    valid_segment_idx += 1
                    continue
                
                # 跳过K值不合理的段
                k_reasonable = fit_result.get('k_reasonable', True)
                if not k_reasonable:
                    self.log(f"      段{result.segment_idx+1}: K={K:.4f} 超出合理范围，跳过融合")
                    valid_segment_idx += 1
                    continue
                
                # 跳过数据点数太少的段
                min_fusion_points = Config.SEGMENT_PROCESSING.get('min_fusion_points', 50)
                min_fusion_points_hq = Config.SEGMENT_PROCESSING.get('min_fusion_points_high_quality', 30)
                
                if r2 > 0.8 and result.data_points >= min_fusion_points_hq:
                    pass  # 高质量段，允许使用
                elif result.data_points < min_fusion_points:
                    self.log(f"      段{result.segment_idx+1}: 数据点数={result.data_points} < {min_fusion_points}，跳过融合")
                    valid_segment_idx += 1
                    continue
                
                # 分析段稳态质量
                stability_score, oscillation_ratio, settling_quality, is_steady = 1.0, 0.0, 1.0, True
                if segments is not None and valid_segment_idx < len(segments):
                    seg = segments[valid_segment_idx]
                    stability_score, oscillation_ratio, settling_quality, is_steady = \
                        self._segment_processor.analyze_segment_stability(seg, fit_result)
                
                # 质量调整
                quality_adjusted_stability = stability_score
                if result.nonlinearity_score > 0.3:
                    quality_adjusted_stability *= (1 - result.nonlinearity_score * 0.5)
                if result.quality_score < 0.5:
                    quality_adjusted_stability *= (0.5 + result.quality_score)
                
                if result.oscillation_ratio > 0:
                    oscillation_ratio = result.oscillation_ratio
                
                window_results.append(FusionWindowResult(
                    window_idx=result.segment_idx,
                    K=K, T1=T1, 
                    T2=fit_result.get('T2', 0), 
                    L=fit_result.get('L', 0),
                    r2=r2,
                    data_points=result.data_points,
                    stability_score=quality_adjusted_stability,
                    oscillation_ratio=oscillation_ratio,
                    settling_quality=settling_quality,
                    is_steady=is_steady and not result.is_nonlinear,
                    nonlinearity_score=result.nonlinearity_score,
                    quality_score=result.quality_score
                ))
                added_indices.add(result.segment_idx)
                valid_segment_idx += 1
            
            if window_results:
                if threshold < self.R2_THRESHOLDS[0]:
                    self.log(f"   ⚠️ 使用阈值 R²≥{threshold} 收集到 {len(window_results)} 个有效段")
                break
        
        return window_results
    
    def _execute_fusion(self, window_results: List[FusionWindowResult], 
                        fusion: FusionResult, model_type: str) -> FusionResult:
        """执行参数融合"""
        try:
            fusion_strategy = PIDFusionStrategy(verbose=self._verbose)
            fusion_result = fusion_strategy.fuse(window_results)
            
            fusion.K = fusion_result.K
            fusion.T1 = fusion_result.T1
            fusion.T2 = fusion_result.T2
            fusion.L = fusion_result.L
            fusion.fusion_method = fusion_result.strategy_used.value
            fusion.consistency_score = fusion_result.confidence
            fusion.n_segments_used = len(fusion_result.windows_used)
            
            if len(window_results) > 1:
                fusion.K_std = float(np.std([w.K for w in window_results]))
                fusion.T1_std = float(np.std([w.T1 for w in window_results]))
            else:
                fusion.K_std = 0.0
                fusion.T1_std = 0.0
            
            self.log(f"\n   融合策略: {fusion.fusion_method}")
            self.log(f"   决策原因: {fusion_result.reasoning}")
            self.log(f"   使用窗口: {[i+1 for i in fusion_result.windows_used]}")
            
        except Exception as e:
            self.log(f"   ⚠️ PIDFusionStrategy 失败: {e}，使用备用逻辑")
            best_window = max(window_results, key=lambda w: w.r2)
            fusion.K = best_window.K
            fusion.T1 = best_window.T1
            fusion.T2 = best_window.T2
            fusion.L = best_window.L
            fusion.fusion_method = "best_window_fallback"
            fusion.consistency_score = best_window.r2
            fusion.n_segments_used = 1
        
        return fusion
    
    def _apply_constraints(self, fusion: FusionResult) -> FusionResult:
        """应用模型参数合理性约束"""
        param_constraints = Config.PARAMETER_CONSTRAINTS
        T1_max = param_constraints['T1_max']
        L_max = param_constraints['L_max']
        
        if fusion.T1 > T1_max:
            self.log(f"   ⚠️ T1={fusion.T1:.2f}s 过大，限制为 {T1_max}s")
            fusion.T1 = T1_max
        if fusion.L > L_max:
            self.log(f"   ⚠️ L={fusion.L:.2f}s 过大，限制为 {L_max}s")
            fusion.L = L_max
        
        return fusion
