from core.algorithm.model_type.data_models import FusionResult
from core.algorithm.model_type.pipeline.context import TuningContext
from core.algorithm.model_type.pipeline.stages.base_stage import PipelineStage


class FusionStage(PipelineStage):
    """
    模型融合阶段:
    1. 选择最佳模型类型 (FOPDT/SOPDT等)
    2. 参数融合
    3. 闭环修正 (如果数据来源于SV阶跃)
    4. 自动回路类型精准推理
    """
    def __init__(self, unified_selector, param_fusion, orchestrator_ref, logger_mixin=None):
        super().__init__(logger_mixin)
        self._unified_selector = unified_selector
        self._param_fusion = param_fusion
        self._orchestrator_ref = orchestrator_ref # To access some methods held on orchestrator if needed

    def execute(self, context: TuningContext) -> TuningContext:
        """执行参数融合与选择"""
        if context.is_fallback_triggered or context.final_result is not None:
            return context
            
        # 1. 基于AIC/RSS/形状特征选择最优模型结构
        # _select_best_model_type wraps _unified_selector
        best_model_type = self._orchestrator_ref._select_best_model_type(
            context.segment_results_fitted, context.hist_data
        )
        self.log(f"🎯 选择模型类型: {best_model_type}")
        context.best_model_type = best_model_type

        # 2. 融合各段参数
        fusion_result = self._param_fusion.fuse(
            context.segment_results_fitted, best_model_type, context.segments_for_fitting
        )
        
        # 同步回路类型
        fusion_result.loop_type = context.loop_type
        
        # 3. 闭环数据修正（如果来源于SV阶跃）
        corrected_T1 = None
        corrected_K = None
        if context.from_sv_step:
            fusion_result = self._orchestrator_ref._apply_closed_loop_correction(
                fusion_result, context.current_pid, context.sv_step_segs
            )
            corrected_T1 = fusion_result.T1
            corrected_K = fusion_result.K
            
        # 4. 回路类型精确推断
        self._orchestrator_ref._auto_infer_loop_type(
            fusion_result, best_model_type, context.segment_results_fitted
        )
        
        # Update context
        if fusion_result.loop_type != context.loop_type:
            context.loop_type = fusion_result.loop_type
            
        context.fusion_result = fusion_result
        context.corrected_T1 = corrected_T1
        context.corrected_K = corrected_K
        
        return context
