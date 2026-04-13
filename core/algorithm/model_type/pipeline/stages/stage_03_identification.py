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
                context.segments_for_fitting, context.results_for_fitting, context.get_current_pid(), force=True
            )
            if oscillation_result is not None:
                context.final_result = self._oscillation_tuner.build_oscillation_output(
                    oscillation_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                    context.original_segments, context.original_results
                )
            else:
                context.is_fallback_triggered = True
            return context

        # [FIX] 路由优先级修正：如果有高振荡段且质量优于正常段，优先用全量段做振荡整定
        # 这是 Auto Detect 三级选段的核心 Bug：高质量的高振荡段 (quality=0.80) 被预检踢出后，
        # 系统只用 poor quality 的正常段做模型辨识，导致辨识出垃圾参数 (如 Pb=10.7% 的致命激进值)
        # 而 Grid Search 碰到同样的振荡段时，直接走振荡整定，反而得到了 Pb=85.8% 的合理参数。
        all_segs = fitting_segs + osc_segs
        all_results = fitting_results + osc_results
        
        if osc_segs:
            # 计算高振荡段的最高质量 vs 正常段的最高质量
            osc_best_quality = max(getattr(r, 'quality_score', 0.0) for r in osc_results)
            fit_best_quality = max((getattr(r, 'quality_score', 0.0) for r in fitting_results), default=0.0)
            
            if osc_best_quality >= fit_best_quality:
                self.log(f"   🔄 高振荡段质量({osc_best_quality:.2f}) ≥ 正常段({fit_best_quality:.2f})，优先用纯振荡段做振荡整定")
                # [FIX-v2] 只传高振荡段！不要掺入 poor quality 的正常段。
                # 原因：混入弱信号段会导致 (1) 振荡整定器内部走不同分支 (2) 相关性互相抵消导致符号校正失败
                # Grid Search 之所以得分更高，正是因为它只用了一个纯净的窗口。
                oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
                    osc_segs, osc_results, context.get_current_pid(), force=True,
                    tuning_constraints=context.export_tuning_constraints()
                )
                if oscillation_result is not None and oscillation_result.get('success', False):
                    context.final_result = self._oscillation_tuner.build_oscillation_output(
                        oscillation_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                        context.original_segments, context.original_results,
                        tuning_constraints=context.export_tuning_constraints()
                    )
                    return context
                else:
                    self.log(f"   ⚠️ 纯振荡段整定未成功，降级到正常段模型拟合")
        
        # 3. 对正常段尝试模型拟合
        segment_results_fitted = self._segment_fitter.fit_all_segments(
            fitting_segs, fitting_results, controller_sign=context.current_kp_sign, loop_type=context.loop_type
        )
        
        # 4. 如果正常段拟合效果差，尝试振荡整定 (柔性fallback)
        # [FIX] 使用全量段（含高振荡段）做振荡整定，而非仅用质量差的正常段
        oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
            all_segs, all_results + segment_results_fitted if osc_segs else segment_results_fitted,
            context.get_current_pid()
        )
        if oscillation_result is not None:
            context.final_result = self._oscillation_tuner.build_oscillation_output(
                oscillation_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                context.original_segments, context.original_results,
                tuning_constraints=context.export_tuning_constraints()
            )
            return context

        # 5. 检查是否所有的时域拟合都彻底失败了
        if self._check_all_fitting_failed(segment_results_fitted):
            # [FIX] 最终兜底也使用全量段（包含被预检跳过的高振荡段）
            self.log("🔄 整定段拟合失败，使用全量段（含高振荡段）强制临界法整定")
            fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                all_segs if osc_segs else (context.valid_segments or all_segs),
                all_results if osc_segs else (context.segment_results or all_results),
                context.get_current_pid(), force=True,
                tuning_constraints=context.export_tuning_constraints()
            )
            if fallback_result is not None:
                context.final_result = self._oscillation_tuner.build_oscillation_output(
                    fallback_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                    context.original_segments, context.original_results,
                    tuning_constraints=context.export_tuning_constraints()
                )
                return context
            
            self.log("❌ 所有模型拟合和振荡检测均失败，无法整定")
            context.is_fallback_triggered = True
            return context

        # 保存结果供下个阶段使用
        context.segment_results_fitted = segment_results_fitted
        context.segments_for_fitting = fitting_segs # update to only the ones actually sent to fitting
        return context
