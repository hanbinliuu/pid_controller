"""
模型辨识置信度模块 (Model Identification Confidence Module)
=========================================================

计算模型辨识方法的置信度评分 (0-1)。

仅评估模型辨识方法自身的可靠性，不包含闭环控制品质评分（那是 Layer 1 model_rating 的职责）。

评分维度（按权重）：
1. 拟合质量 R²     (40%) — 模型对历史数据的拟合度
2. 参数一致性      (30%) — 多段辨识参数的一致性
3. 参数合理性      (30%) — 参数物理范围检查
"""

from typing import Dict, Tuple, Optional

from ...data_models import FusionResult


class ModelRatingMixin:
    """
    模型辨识置信度 Mixin 类
    
    提供模型辨识方法的置信度计算。
    需要宿主类提供 _epsilon 属性。
    """
    
    def calculate_method_confidence(self, fusion: FusionResult,
                                     verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算模型辨识的方法置信度 (0-1)
        
        仅评估模型辨识自身可信程度：
        1. R² 拟合质量    - 40%
        2. 参数一致性      - 30%
        3. 参数合理性      - 30%
        
        Returns:
            (confidence, details) — confidence 范围 0.0~1.0
        """
        details = {'method': 'model_identification'}
        
        # 1. R² 拟合质量 (0-1)
        r2 = fusion.global_r2
        if r2 >= 0.95:
            r2_quality = 1.0
        elif r2 >= 0.9:
            r2_quality = 0.9 + (r2 - 0.9) * 2
        elif r2 >= 0.8:
            r2_quality = 0.75 + (r2 - 0.8) * 1.5
        elif r2 >= 0.6:
            r2_quality = 0.5 + (r2 - 0.6) * 1.25
        elif r2 >= 0.4:
            r2_quality = 0.3 + (r2 - 0.4) * 1.0
        elif r2 >= 0.2:
            r2_quality = 0.1 + (r2 - 0.2) * 1.0
        else:
            r2_quality = max(0.0, r2 * 0.5)
        details['r2_quality'] = round(r2_quality, 4)
        
        # 2. 参数一致性 (0-1)
        consistency = 1.0
        
        if fusion.n_segments_used > 1:
            k_mean = abs(fusion.K) + self._epsilon
            k_cv = fusion.K_std / k_mean
            t1_mean = abs(fusion.T1) + self._epsilon
            t1_cv = fusion.T1_std / t1_mean
            
            k_consistency = max(0, 1.0 - k_cv * 1.5)
            t1_consistency = max(0, 1.0 - t1_cv * 1.5)
            consistency = 0.6 * k_consistency + 0.4 * t1_consistency
            
            if fusion.consistency_score > 0:
                consistency = 0.7 * consistency + 0.3 * fusion.consistency_score
        else:
            if fusion.consistency_score > 0:
                consistency = fusion.consistency_score
            else:
                consistency = 0.6  # 单段无法评估一致性
        
        consistency = min(1.0, max(0.0, consistency))
        details['param_consistency'] = round(consistency, 4)
        
        # 3. 参数合理性 (0-1)
        validity = 1.0
        penalties = []
        
        K = fusion.K
        if abs(K) < 0.001:
            penalties.append(('K接近零', 0.4))
        elif abs(K) > 50:
            penalties.append(('K过大', 0.2))
        elif abs(K) < 0.01:
            penalties.append(('K过小', 0.1))
        
        T1 = fusion.T1
        if T1 <= 0:
            penalties.append(('T1非正', 0.5))
        elif T1 < 0.1:
            penalties.append(('T1过小', 0.2))
        elif T1 > 500:
            penalties.append(('T1过大', 0.15))
        
        L = fusion.L
        if L < 0:
            penalties.append(('L为负', 0.3))
        elif L > T1 * 2 and T1 > 0:
            penalties.append(('L过大', 0.1))
        
        T2 = fusion.T2
        if T2 < 0:
            penalties.append(('T2为负', 0.2))
        
        for reason, penalty in penalties:
            validity -= penalty
            if verbose:
                print(f"   参数检查: {reason}, 扣{penalty:.1%}")
        
        validity = max(0.0, validity)
        details['param_validity'] = round(validity, 4)
        
        # 综合置信度
        weights = {'r2': 0.4, 'consistency': 0.3, 'validity': 0.3}
        confidence = (
            weights['r2'] * r2_quality +
            weights['consistency'] * consistency +
            weights['validity'] * validity
        )
        
        # 硬约束：R²太低时封顶
        if r2 < 0.3:
            confidence = min(confidence, 0.3)
        elif r2 < 0.5:
            confidence = min(confidence, 0.5)
        
        confidence = round(min(1.0, max(0.0, confidence)), 4)
        details['confidence_weights'] = weights
        
        return confidence, details
    
    # 保留旧接口兼容性
    def calculate_model_rating(self, fusion: FusionResult, 
                                total_data_points: int,
                                cl_metrics=None,
                                prediction_metrics=None,
                                verbose: bool = False):
        """
        兼容旧接口：返回 (model_rating, score_details)
        
        model_rating 现在统一使用闭环性能评分 (Layer 1)
        """
        from ..core.performance_rating import calculate_control_performance
        
        # Layer 1: 统一闭环性能评分
        model_rating = calculate_control_performance(cl_metrics)
        
        # Layer 2: 方法置信度（仅模型辨识维度）
        confidence, confidence_details = self.calculate_method_confidence(fusion, verbose=verbose)
        
        score_details = {
            'model_rating': model_rating,
            'method_confidence': confidence,
            'method_confidence_details': confidence_details,
        }
        
        return model_rating, score_details
