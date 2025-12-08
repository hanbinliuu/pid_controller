"""PID参数计算模块"""

from typing import Dict, Tuple

from .config import Config, ModelType
from .models import FusionResult


EPSILON = Config.EPSILON


class PIDCalculator:
    """PID参数计算器"""
    
    def __init__(self):
        self._epsilon = EPSILON
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float) -> Dict[str, float]:
        """
        计算PID参数（Lambda方法）
        
        Args:
            K: 增益
            T1: 时间常数1
            T2: 时间常数2
            L: 滞后时间
            model_type: 模型类型
            lambda_factor: Lambda整定系数
        
        Returns:
            PID参数字典 {Kp, Ki, Kd}
        """
        K = max(abs(K), self._epsilon)
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        lambda_val = T_eq * lambda_factor
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = (T1 + L / 2) / denom
                Ti = T1 + L / 2
                Td = (T1 * L) / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            denom = K * (lambda_val + L / 2) if L > 0 else K * lambda_val
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = T_eq / denom
                Ti = T_eq
                Td = (T1 * T2) / T_eq if T_eq > self._epsilon else 0.0
        
        elif model_type == ModelType.FOPI:
            if K < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                lv = max(T1 * 0.8, 0.2) if T1 > 0 else 0.2
                Kp = T1 / (K * lv) if T1 > 0 else 1.0 / (K * lv)
                Ti, Td = max(T1, 1.0), 0.0
        else:
            Kp, Ti, Td = 1.0, 20.0, 0.0
        
        Kp, Ti, Td = max(0.01, Kp), max(0.1, Ti), max(0.0, Td)
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        return {
            'Kp': round(float(Kp), 4),
            'Ki': round(float(Ki), 4),
            'Kd': round(float(Kd), 4)
        }
    
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float) -> Dict[str, float]:
        """从FusionResult计算PID参数"""
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor
        )
    
    def calculate_model_rating(self, fusion: FusionResult, 
                                total_data_points: int,
                                verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算综合模型评分 (0-10分)
        
        综合考虑以下维度：
        1. 拟合质量 (R²)        - 40%
        2. 参数一致性            - 25%
        3. 参数物理合理性        - 20%
        4. 数据覆盖度            - 15%
        
        Returns:
            (model_rating, score_details)
        """
        score_details = {}
        
        # 1. 拟合质量评分 (0-10) - 权重 40%
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
        
        # 2. 参数一致性评分 (0-10) - 权重 25%
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
        
        # 3. 参数物理合理性评分 (0-10) - 权重 20%
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
        
        # 4. 数据覆盖度评分 (0-10) - 权重 15%
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
        
        # 综合评分
        weights = {
            'r2': 0.40,
            'consistency': 0.25,
            'validity': 0.20,
            'coverage': 0.15
        }
        
        final_score = (
            weights['r2'] * r2_score +
            weights['consistency'] * consistency_score +
            weights['validity'] * validity_score +
            weights['coverage'] * coverage_score
        )
        
        if r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        score_details['weights'] = weights
        
        return final_score, score_details
