from ..context import TuningContext
from .base_stage import PipelineStage


class IdentificationStage(PipelineStage):
    """
    模型辨识阶段:
    1. 预检高振荡段，如果全是高振荡直接走 Oscillation Fallback
    2. 对正常段调用 SegmentFitter.fit_all_segments
    3. 检查拟合是否全失败，如果全失败且有兜底段，走 Oscillation Fallback
    """
    def __init__(self, segment_fitter, oscillation_tuner, logger_mixin=None):
        super().__init__(logger_mixin)
        self._segment_fitter = segment_fitter
        self._oscillation_tuner = oscillation_tuner

    def _precheck_oscillation(self, context: TuningContext) -> tuple:
        """预检过滤高振荡段"""
        fitting_segs, fitting_results = [], []
        osc_segs, osc_results = [], []
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1.95: 振荡预检（跳过高振荡段的模型拟合）")
        self.log('='*60)
        
        # 回路类型自适应阈值
        adapted_threshold = 0.7
        if context.loop_type in ['flow', 'pressure', 'pressure_liquid']:
            adapted_threshold = 0.85
            
        for seg, res in zip(context.segments_for_fitting, context.results_for_fitting):
            osc_ratio = getattr(res, 'oscillation_ratio', 0.0)
            if osc_ratio > adapted_threshold:
                self.log(f"   段{res.segment_idx+1}: 振荡比={osc_ratio:.2f} > {adapted_threshold}，跳过拟合")
                osc_segs.append(seg)
                osc_results.append(res)
            else:
                fitting_segs.append(seg)
                fitting_results.append(res)
                
        self.log(f"   📊 预检结果: {len(fitting_segs)} 个正常段, {len(osc_segs)} 个高振荡段")
        return fitting_segs, fitting_results, osc_segs, osc_results

    def _check_all_fitting_failed(self, segment_results) -> bool:
        """检查是否所有段的模型拟合都失败了"""
        for result in segment_results:
            if result.is_valid and result.model_results:
                return False
        return True

    def execute(self, context: TuningContext) -> TuningContext:
        """执行辨识阶段"""
        if context.is_fallback_triggered or context.final_result is not None:
            return context
            
        # 1. 振荡预检
        fitting_segs, fitting_results, osc_segs, osc_results = self._precheck_oscillation(context)
        
        # 2. 如果全都是高振荡段，直接强行走振荡整定
        if not fitting_segs:
            self.log("⚠️ 所有段均为高振荡，直接启用振荡整定")
            force_fallback = True
        else:
            force_fallback = False

        if force_fallback:
            oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
                context.segments_for_fitting, context.results_for_fitting, context.current_pid, force=True
            )
            if oscillation_result is not None:
                context.final_result = self._oscillation_tuner.build_oscillation_output(
                    oscillation_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                    context.original_segments, context.original_results
                )
            else:
                context.is_fallback_triggered = True
            return context

        # 3. 对正常段尝试模型拟合
        segment_results_fitted = self._segment_fitter.fit_all_segments(
            fitting_segs, fitting_results, controller_sign=context.current_kp_sign, loop_type=context.loop_type
        )
        
        # 4. 如果正常段拟合效果差，尝试振荡整定 (柔性fallback)
        oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
            fitting_segs, segment_results_fitted, context.current_pid
        )
        if oscillation_result is not None:
            context.final_result = self._oscillation_tuner.build_oscillation_output(
                oscillation_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                context.original_segments, context.original_results
            )
            return context

        # 5. 检查是否所有的时域拟合都彻底失败了
        if self._check_all_fitting_failed(segment_results_fitted):
            # 如果拟合失败，且一开始没有用原始 disturbance_segs，尝试对 disturbance 强行临界整定
            if context.valid_segments: # which is disturbance_segs mapped earlier
                self.log("🔄 整定段拟合失败，回退使用扰动段尝试临界法整定")
                fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                    context.valid_segments, context.segment_results, context.current_pid, force=True
                )
                if fallback_result is not None:
                    context.final_result = self._oscillation_tuner.build_oscillation_output(
                        fallback_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                        context.valid_segments, context.segment_results
                    )
                    return context
            
            self.log("❌ 所有模型拟合和振荡检测均失败，无法整定")
            context.is_fallback_triggered = True
            return context

        # 保存结果供下个阶段使用
        context.segment_results_fitted = segment_results_fitted
        context.segments_for_fitting = fitting_segs # update to only the ones actually sent to fitting
        return context
