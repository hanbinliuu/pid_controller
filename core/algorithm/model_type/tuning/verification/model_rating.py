"""
模型评分模块 (Model Rating Module)
=================================

计算综合模型评分，评估PID整定可靠性。

评分维度（按权重）：
1. 闭环阶跃稳定性 (35%) — 标准阶跃仿真的控制品质
2. 预测仿真稳定性 (30%) — 从实际工作点的仿真预测
3. 拟合质量 R²     (15%) — 模型对历史数据的拟合度
4. 参数一致性      (10%) — 多段辨识参数的一致性
5. 参数合理性      (10%) — 参数物理范围检查
"""

from typing import Dict, Tuple, Optional

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
                                prediction_metrics: ClosedLoopMetrics = None,
                                verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算综合模型评分 (0-10分)
        
        综合考虑以下维度：
        1. 闭环阶跃稳定性        - 35%
        2. 预测仿真稳定性        - 30%
        3. 拟合质量 (R²)         - 15%
        4. 参数一致性             - 10%
        5. 参数合理性             - 10%
        """
        score_details = {}
        
        # 1. 闭环阶跃稳定性评分 (0-10) - 权重 35%
        stability_score = self._score_closed_loop_metrics(cl_metrics)
        score_details['stability_score'] = round(stability_score, 2)
        
        # 2. 预测仿真稳定性评分 (0-10) - 权重 30%
        prediction_score = self._score_closed_loop_metrics(prediction_metrics)
        score_details['prediction_score'] = round(prediction_score, 2)
        
        # 3. 拟合质量评分 (0-10) - 权重 15%
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
        
        # 4. 参数一致性评分 (0-10) - 权重 10%
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
        
        # 5. 参数合理性评分 (0-10) - 权重 10%
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
        
        # 综合评分（以闭环稳定性为主）
        weights = {
            'stability': 0.35,     # 闭环阶跃稳定性
            'prediction': 0.30,    # 预测仿真稳定性
            'r2': 0.15,            # 拟合质量
            'consistency': 0.10,   # 参数一致性
            'validity': 0.10,      # 参数合理性
        }
        
        final_score = (
            weights['stability'] * stability_score +
            weights['prediction'] * prediction_score +
            weights['r2'] * r2_score +
            weights['consistency'] * consistency_score +
            weights['validity'] * validity_score
        )
        
        # 硬约束：R²太低时封顶
        if r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        # 硬约束：闭环不稳定时封顶
        if cl_metrics is not None and not cl_metrics.is_stable:
            final_score = min(final_score, 5.0)
        
        # 硬约束：预测仿真不稳定时封顶
        if prediction_metrics is not None and not prediction_metrics.is_stable:
            final_score = min(final_score, 6.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        score_details['weights'] = weights
        
        return final_score, score_details
    
    def _score_closed_loop_metrics(self, metrics: Optional[ClosedLoopMetrics]) -> float:
        """
        根据闭环仿真指标计算评分 (0-10)
        
        复用于闭环阶跃仿真和预测仿真。
        通过统一的 performance_rating 计算获取分数，保证评估标尺单一化。
        """
        from ..core.performance_rating import calculate_control_performance
        return calculate_control_performance(metrics)
