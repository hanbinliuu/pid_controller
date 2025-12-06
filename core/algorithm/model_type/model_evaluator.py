"""模型评估模块 - 模型评分和质量验证"""

import numpy as np
from typing import Dict, Tuple, Optional, List
from dataclasses import dataclass

from .config import Config


@dataclass
class RatingDetails:
    """评分详情"""
    r2_score: float = 0.0
    consistency_score: float = 0.0
    validity_score: float = 0.0
    coverage_score: float = 0.0
    n_segments: int = 0
    total_data_points: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'r2_score': round(self.r2_score, 2),
            'consistency_score': round(self.consistency_score, 2),
            'validity_score': round(self.validity_score, 2),
            'coverage_score': round(self.coverage_score, 2),
            'n_segments': self.n_segments,
            'total_data_points': self.total_data_points,
            'weights': Config.RATING_WEIGHTS
        }


class ModelEvaluator:
    """
    模型评估器
    
    综合评估维度：
    1. 拟合质量 (R²)        - 40%
    2. 参数一致性            - 25%
    3. 参数物理合理性        - 20%
    4. 数据覆盖度            - 15%
    """
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
    
    def log(self, msg: str):
        if self._verbose:
            print(msg)
    
    def calculate_rating(self, global_r2: float, n_segments: int,
                          total_data_points: int, K: float, T1: float,
                          T2: float, L: float, K_std: float = 0.0,
                          T1_std: float = 0.0, 
                          consistency_score: float = 0.0) -> Tuple[float, RatingDetails]:
        """
        计算综合模型评分 (0-10分)
        
        Args:
            global_r2: 全局R²
            n_segments: 使用的段数
            total_data_points: 总数据点数
            K, T1, T2, L: 模型参数
            K_std, T1_std: 参数标准差
            consistency_score: 融合一致性评分
        
        Returns:
            (model_rating, rating_details)
        """
        details = RatingDetails(
            n_segments=n_segments,
            total_data_points=total_data_points
        )
        
        # 1. 拟合质量评分
        details.r2_score = self._calculate_r2_score(global_r2)
        
        # 2. 参数一致性评分
        details.consistency_score = self._calculate_consistency_score(
            n_segments, K, K_std, T1, T1_std, consistency_score
        )
        
        # 3. 参数物理合理性评分
        details.validity_score = self._calculate_validity_score(K, T1, T2, L)
        
        # 4. 数据覆盖度评分
        details.coverage_score = self._calculate_coverage_score(
            n_segments, total_data_points
        )
        
        # 综合评分
        weights = Config.RATING_WEIGHTS
        final_score = (
            weights['r2'] * details.r2_score +
            weights['consistency'] * details.consistency_score +
            weights['validity'] * details.validity_score +
            weights['coverage'] * details.coverage_score
        )
        
        # R²太低时限制总分
        if global_r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif global_r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        
        self._log_rating(details, global_r2, final_score, weights)
        
        return final_score, details
    
    def _calculate_r2_score(self, r2: float) -> float:
        """
        计算R²评分 (0-10)
        
        使用非线性映射，R²<0.5快速下降，R²>0.8缓慢上升
        """
        if r2 >= 0.95:
            return 10.0
        elif r2 >= 0.9:
            return 9.0 + (r2 - 0.9) * 20
        elif r2 >= 0.8:
            return 7.5 + (r2 - 0.8) * 15
        elif r2 >= 0.6:
            return 5.0 + (r2 - 0.6) * 12.5
        elif r2 >= 0.4:
            return 3.0 + (r2 - 0.4) * 10
        elif r2 >= 0.2:
            return 1.0 + (r2 - 0.2) * 10
        else:
            return r2 * 5
    
    def _calculate_consistency_score(self, n_segments: int, K: float,
                                       K_std: float, T1: float, T1_std: float,
                                       fusion_consistency: float) -> float:
        """计算参数一致性评分 (0-10)"""
        if n_segments > 1:
            # K的变异系数
            k_mean = abs(K) + self._epsilon
            k_cv = K_std / k_mean
            
            # T1的变异系数
            t1_mean = abs(T1) + self._epsilon
            t1_cv = T1_std / t1_mean
            
            # CV < 0.1 优秀, CV > 0.5 较差
            k_consistency = max(0, 10 - k_cv * 15)
            t1_consistency = max(0, 10 - t1_cv * 15)
            
            # 加权平均，K权重略高
            score = 0.6 * k_consistency + 0.4 * t1_consistency
            
            # 如果有融合一致性评分，融合使用
            if fusion_consistency > 0:
                score = 0.7 * score + 0.3 * (fusion_consistency * 10)
        else:
            # 单段情况
            if fusion_consistency > 0:
                score = fusion_consistency * 10
            else:
                score = 6.0  # 单段默认中等分数
        
        return min(10.0, max(0.0, score))
    
    def _calculate_validity_score(self, K: float, T1: float, 
                                    T2: float, L: float) -> float:
        """计算参数物理合理性评分 (0-10)"""
        score = 10.0
        penalties = []
        
        # K检查
        if abs(K) < 0.001:
            penalties.append(('K接近零', 4.0))
        elif abs(K) > 50:
            penalties.append(('K过大', 2.0))
        elif abs(K) < 0.01:
            penalties.append(('K过小', 1.0))
        
        # T1检查
        if T1 <= 0:
            penalties.append(('T1非正', 5.0))
        elif T1 < 0.1:
            penalties.append(('T1过小', 2.0))
        elif T1 > 500:
            penalties.append(('T1过大', 1.5))
        
        # L检查
        if L < 0:
            penalties.append(('L为负', 3.0))
        elif L > T1 * 2 and T1 > 0:
            penalties.append(('L过大', 1.0))
        
        # T2检查
        if T2 < 0:
            penalties.append(('T2为负', 2.0))
        
        # 应用惩罚
        for reason, penalty in penalties:
            score -= penalty
            self.log(f"   参数检查: {reason}, 扣{penalty}分")
        
        return max(0.0, score)
    
    def _calculate_coverage_score(self, n_segments: int, 
                                    total_data_points: int) -> float:
        """计算数据覆盖度评分 (0-10)"""
        # 段数评分
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
        
        # 数据点数评分
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
        
        return min(10.0, 0.6 * segment_score + 0.4 * data_score)
    
    def _log_rating(self, details: RatingDetails, r2: float, 
                    final_score: float, weights: Dict):
        """输出评分日志"""
        self.log(f"\n   📊 评分详情:")
        self.log(f"      拟合质量 (R²={r2:.3f}): {details.r2_score:.1f}/10 × {weights['r2']:.0%}")
        self.log(f"      参数一致性: {details.consistency_score:.1f}/10 × {weights['consistency']:.0%}")
        self.log(f"      参数合理性: {details.validity_score:.1f}/10 × {weights['validity']:.0%}")
        self.log(f"      数据覆盖度 ({details.n_segments}段/{details.total_data_points}点): "
                f"{details.coverage_score:.1f}/10 × {weights['coverage']:.0%}")
        self.log(f"      → 综合评分: {final_score}/10")
    
    def get_recommendation(self, model_rating: float) -> str:
        """根据评分获取推荐等级"""
        for level, (threshold, label) in Config.RATING_THRESHOLDS.items():
            if model_rating >= threshold:
                return label
        return '不可用'
    
    def get_quality_label(self, r2: float) -> str:
        """根据R²获取质量标签"""
        if r2 >= 0.9:
            return "优秀"
        elif r2 >= 0.7:
            return "良好"
        elif r2 >= 0.5:
            return "一般"
        else:
            return "较差"
