"""
模型评分模块 (Model Rating Module)
=================================

计算综合模型评分，评估模型质量和PID整定可靠性。

评分维度：
- 拟合质量 (R²)
- 参数一致性
- 参数物理合理性
- 数据覆盖度
- 闭环稳定性
"""

from typing import Dict, Tuple

from ...data_models import FusionResult
from ..core.data_classes import ClosedLoopMetrics


class ModelRatingMixin:
    """
    模型评分Mixin类
    
    提供综合模型评分方法。
    需要宿主类提供 _epsilon 属性。
    """
    
    def calculate_model_rating(self, fusion: FusionResult, 
                                total_data_points: int,
                                cl_metrics: ClosedLoopMetrics = None,
                                verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算综合模型评分 (0-10分)
        
        综合考虑以下维度：
        1. 拟合质量 (R²)        - 30%
        2. 参数一致性            - 20%
        3. 参数物理合理性        - 15%
        4. 数据覆盖度            - 10%
        5. 闭环稳定性            - 25%
        """
        score_details = {}
        
        # 1. 拟合质量评分 (0-10) - 权重 30%
        r2 = fusion.global_r2
        if r2 >= 0.95:
            r2_score = 10.0
        elif r2 >= 0.9:
            r2_score = 9.0 + (r2 - 0.9) * 20
        elif r2 >= 0.8:
            r2_score = 7.5 + (r2 - 0.8) * 15
        elif r2 >= 0.6:
            r2_score = 5.0 + (r2 - 0.6) * 12.5
        elif r2 >= 0.4:
            r2_score = 3.0 + (r2 - 0.4) * 10
        elif r2 >= 0.2:
            r2_score = 1.0 + (r2 - 0.2) * 10
        else:
            r2_score = r2 * 5
        score_details['r2_score'] = round(r2_score, 2)
        
        # 2. 参数一致性评分 (0-10) - 权重 20%
        consistency_score = 10.0
        
        if fusion.n_segments_used > 1:
            k_mean = abs(fusion.K) + self._epsilon
            k_cv = fusion.K_std / k_mean
            t1_mean = abs(fusion.T1) + self._epsilon
            t1_cv = fusion.T1_std / t1_mean
            
            k_consistency = max(0, 10 - k_cv * 15)
            t1_consistency = max(0, 10 - t1_cv * 15)
            consistency_score = 0.6 * k_consistency + 0.4 * t1_consistency
            
            if fusion.consistency_score > 0:
                consistency_score = 0.7 * consistency_score + 0.3 * (fusion.consistency_score * 10)
        else:
            if fusion.consistency_score > 0:
                consistency_score = fusion.consistency_score * 10
            else:
                consistency_score = 6.0
        
        consistency_score = min(10.0, max(0.0, consistency_score))
        score_details['consistency_score'] = round(consistency_score, 2)
        
        # 3. 参数物理合理性评分 (0-10) - 权重 15%
        validity_score = 10.0
        penalties = []
        
        K = fusion.K
        if abs(K) < 0.001:
            penalties.append(('K接近零', 4.0))
        elif abs(K) > 50:
            penalties.append(('K过大', 2.0))
        elif abs(K) < 0.01:
            penalties.append(('K过小', 1.0))
        
        T1 = fusion.T1
        if T1 <= 0:
            penalties.append(('T1非正', 5.0))
        elif T1 < 0.1:
            penalties.append(('T1过小', 2.0))
        elif T1 > 500:
            penalties.append(('T1过大', 1.5))
        
        L = fusion.L
        if L < 0:
            penalties.append(('L为负', 3.0))
        elif L > T1 * 2 and T1 > 0:
            penalties.append(('L过大', 1.0))
        
        T2 = fusion.T2
        if T2 < 0:
            penalties.append(('T2为负', 2.0))
        
        for reason, penalty in penalties:
            validity_score -= penalty
            if verbose:
                print(f"   参数检查: {reason}, 扣{penalty}分")
        
        validity_score = max(0.0, validity_score)
        score_details['validity_score'] = round(validity_score, 2)
        
        # 4. 数据覆盖度评分 (0-10) - 权重 10%
        n_segments = fusion.n_segments_used
        
        if n_segments >= 4:
            segment_score = 9.0 + min(1.0, (n_segments - 4) * 0.25)
        elif n_segments == 3:
            segment_score = 8.5
        elif n_segments == 2:
            segment_score = 7.0
        elif n_segments == 1:
            segment_score = 5.0
        else:
            segment_score = 0.0
        
        if total_data_points >= 500:
            data_score = 10.0
        elif total_data_points >= 200:
            data_score = 7.0 + (total_data_points - 200) / 100
        elif total_data_points >= 100:
            data_score = 5.0 + (total_data_points - 100) / 50
        elif total_data_points >= 50:
            data_score = 3.0 + (total_data_points - 50) / 25
        else:
            data_score = total_data_points / 50 * 3
        
        coverage_score = 0.6 * segment_score + 0.4 * data_score
        coverage_score = min(10.0, coverage_score)
        score_details['coverage_score'] = round(coverage_score, 2)
        score_details['n_segments'] = n_segments
        score_details['total_data_points'] = total_data_points
        
        # 5. 闭环稳定性评分 (0-10) - 权重 25%
        stability_score = 5.0
        
        if cl_metrics is not None:
            if cl_metrics.is_stable:
                stability_score = 6.0
            else:
                stability_score = 1.0
            
            overshoot = cl_metrics.overshoot
            if overshoot <= 5:
                stability_score += 1.5
            elif overshoot <= 15:
                stability_score += 1.0
            elif overshoot <= 30:
                stability_score += 0.5
            elif overshoot <= 50:
                stability_score -= 0.5
            else:
                stability_score -= 1.5
            
            rise_time = cl_metrics.rise_time
            if rise_time < float('inf'):
                if 1.0 <= rise_time <= 10.0:
                    stability_score += 1.0
                elif 0.5 <= rise_time < 1.0 or 10.0 < rise_time <= 20.0:
                    stability_score += 0.5
                elif rise_time < 0.5:
                    stability_score -= 0.5
                else:
                    stability_score -= 0.5
            
            sse = cl_metrics.steady_state_error
            if sse <= 1:
                stability_score += 1.0
            elif sse <= 2:
                stability_score += 0.5
            elif sse <= 5:
                pass
            elif sse <= 10:
                stability_score -= 0.5
            else:
                stability_score -= 1.0
            
            osc_count = cl_metrics.oscillation_count
            if osc_count == 0:
                stability_score += 0.5
            elif osc_count <= 2:
                stability_score += 1.0
            elif osc_count <= 4:
                stability_score += 0.5
            elif osc_count <= 6:
                stability_score -= 0.5
            else:
                stability_score -= 1.0
            
            decay_ratio = cl_metrics.decay_ratio
            if decay_ratio <= 0.25:
                stability_score += 1.0
            elif decay_ratio <= 0.5:
                stability_score += 0.5
            elif decay_ratio <= 1.0:
                pass
            else:
                stability_score -= 1.0
            
            stability_score = min(10.0, max(0.0, stability_score))
        
        score_details['stability_score'] = round(stability_score, 2)
        
        # 综合评分
        weights = {
            'r2': 0.30,
            'consistency': 0.20,
            'validity': 0.15,
            'coverage': 0.10,
            'stability': 0.25
        }
        
        final_score = (
            weights['r2'] * r2_score +
            weights['consistency'] * consistency_score +
            weights['validity'] * validity_score +
            weights['coverage'] * coverage_score +
            weights['stability'] * stability_score
        )
        
        if r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        if cl_metrics is not None and not cl_metrics.is_stable:
            final_score = min(final_score, 5.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        score_details['weights'] = weights
        
        return final_score, score_details
