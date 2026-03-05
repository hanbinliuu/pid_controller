"""
模型辨识评分 Mixin (薄代理层)
============================

代理到 rating.py 的 ModelRating。
保留 Mixin 接口供 PIDCalculator 继承使用。
"""

from typing import Dict, Tuple, Optional


class ModelRatingMixin:
    """
    模型辨识评分 Mixin — 代理到 ModelRating
    
    提供 calculate_model_rating() 旧接口兼容。
    """
    
    def calculate_method_confidence(self, fusion, verbose=False):
        """代理到 ModelRating.model_id_confidence"""
        from ...rating import ModelRating
        return ModelRating.model_id_confidence(fusion)
    
    def calculate_model_rating(self, fusion, total_data_points=0,
                                cl_metrics=None, prediction_metrics=None,
                                verbose=False):
        """
        兼容旧接口：返回 (model_rating, score_details)
        
        内部使用 ModelRating 三层评分。
        """
        from ...rating import ModelRating
        
        # Layer 1
        perf_score, perf_details = ModelRating.performance_score(cl_metrics)
        # Layer 2
        confidence, conf_details = ModelRating.model_id_confidence(fusion)
        # Layer 3
        model_rating, final_details = ModelRating.final_rating(perf_score, confidence)
        
        score_details = {
            'performance_score': perf_score,
            'performance_details': perf_details,
            'method_confidence': confidence,
            'method_confidence_details': conf_details,
            'final_rating': model_rating,
            'final_details': final_details,
        }
        
        return model_rating, score_details
