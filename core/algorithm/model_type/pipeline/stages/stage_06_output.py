import numpy as np
from typing import List

from ..context import TuningContext
from .base_stage import PipelineStage
from ...data_models import HistoricalData, SegmentResult, FusionResult
from ...tuning import DataQualityInfo


class OutputVerificationStage(PipelineStage):
    """
    终审输出阶段:
    1. 构建数据质量信息
    2. 触发最终模型的全量验证、评级、和字典输出结构的封装
    """
    def __init__(self, preprocessor, output_builder, logger_mixin=None):
        super().__init__(logger_mixin)
        self._preprocessor = preprocessor
        self._output_builder = output_builder

    def _build_quality_info(self, valid_segments: List[HistoricalData],
                            segment_results: List[SegmentResult],
                            fusion_result: FusionResult,
                            controller_sign: int = 1) -> DataQualityInfo:
        """
        构建数据质量信息，用于自适应保守PID整定
        """
        oscillation_ratios = []
        quality_scores = []
        correlations = []
        is_noisy = False
        
        for seg in valid_segments:
            y = seg.pv
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            osc_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            oscillation_ratios.append(osc_ratio)
            
            # 使用预处理器分析质量
            quality = self._preprocessor.analyze_quality(y, seg.mv)
            quality_scores.append(quality.quality_score if hasattr(quality, 'quality_score') else 0.5)
            
            if hasattr(quality, 'is_noisy') and quality.is_noisy:
                is_noisy = True
            
            if hasattr(quality, 'correlation'):
                correlations.append(quality.correlation)
        
        avg_oscillation = np.mean(oscillation_ratios) if oscillation_ratios else 0.0
        avg_quality = np.mean(quality_scores) if quality_scores else 0.5
        avg_correlation = np.mean(correlations) if correlations else 0.0
        
        quality_info = DataQualityInfo(
            quality_score=avg_quality,
            oscillation_ratio=avg_oscillation,
            r_squared=fusion_result.global_r2,
            is_noisy=is_noisy,
            consistency_score=fusion_result.consistency_score,
            correlation=avg_correlation,
            controller_sign=controller_sign
        )
        
        return quality_info

    def execute(self, context: TuningContext) -> TuningContext:
        if context.is_fallback_triggered or context.final_result is not None:
            return context
            
        # 1. 构建数据质量信息
        quality_info = self._build_quality_info(
            context.segments_for_fitting, context.segment_results_fitted, 
            context.fusion_result, controller_sign=context.current_kp_sign
        )
        
        # 2. 调用 OutputBuilder 生成最终大字典
        context.final_result = self._output_builder.build_full_output(
            context.fusion_result, context.hist_data, context.time_range, context.lambda_factor, 
            context.input_data.tuning_window, quality_info,
            context.original_results, context.original_segments,
            loop_type=context.loop_type,
            optimized_pid=context.optimized_pid
        )
        
        return context
