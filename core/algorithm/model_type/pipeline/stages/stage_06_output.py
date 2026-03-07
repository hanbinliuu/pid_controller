from core.algorithm.model_type.pipeline.context import TuningContext
from core.algorithm.model_type.pipeline.stages.base_stage import PipelineStage


class OutputVerificationStage(PipelineStage):
    """
    终审输出阶段:
    1. 构建数据质量信息
    2. 触发最终模型的全量验证、评级、和字典输出结构的封装
    """
    def __init__(self, orchestrator_ref, logger_mixin=None):
        super().__init__(logger_mixin)
        self._orchestrator_ref = orchestrator_ref

    def execute(self, context: TuningContext) -> TuningContext:
        if context.is_fallback_triggered or context.final_result is not None:
            return context
            
        # 1. 构建数据质量信息，用于自适应保守PID整定
        quality_info = self._orchestrator_ref._build_quality_info(
            context.segments_for_fitting, context.segment_results_fitted, 
            context.fusion_result, controller_sign=context.current_kp_sign
        )
        
        # 2. 调用原先的 _build_output 生成最终大字典
        # 将原始数据(original)送入以便画图
        context.final_result = self._orchestrator_ref._build_output(
            context.fusion_result, context.hist_data, context.time_range, context.lambda_factor, 
            context.input_data.tuning_window, quality_info,
            context.original_results, context.original_segments
        )
        
        return context
