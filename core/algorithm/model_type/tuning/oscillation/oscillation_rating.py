"""
振荡整定评分 (薄代理层)
======================

代理到 rating.py 的 ModelRating。
保留 OscillationRatingCalculator 接口供 OscillationTuner 使用。
"""

from typing import Dict, List, Tuple


class OscillationRatingCalculator:
    """
    振荡整定评分计算器 — 代理到 ModelRating
    
    保留 calculate() 旧接口兼容。
    """
    
    def calculate_method_confidence(self, pid_params, osc_info, osc_result):
        """代理到 ModelRating.oscillation_confidence"""
        from ...rating import ModelRating
        from ...config import Config
        return ModelRating.oscillation_confidence(
            pid_params, osc_info, osc_result,
            config=Config.OSCILLATION_TUNING
        )
    
    def calculate(self, is_stable, cl_metrics, pid_params, osc_info, osc_result):
        """
        兼容旧接口：返回 (model_rating, rating_details, warnings)
        
        内部使用 ModelRating 三层评分。
        """
        from ...rating import ModelRating
        from ...config import Config
        
        # Layer 1
        perf_score, perf_details = ModelRating.performance_score(cl_metrics)
        # Layer 2
        confidence, conf_details, warnings = ModelRating.oscillation_confidence(
            pid_params, osc_info, osc_result,
            config=Config.OSCILLATION_TUNING
        )
        # Layer 3
        model_rating, final_details = ModelRating.final_rating(perf_score, confidence)
        
        rating_details = {
            'performance_score': perf_score,
            'performance_details': perf_details,
            'method_confidence': confidence,
            'method_confidence_details': conf_details,
            'final_rating': model_rating,
            'final_details': final_details,
            'warnings': warnings,
        }
        
        return model_rating, rating_details, warnings
