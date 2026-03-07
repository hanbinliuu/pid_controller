from core.algorithm.model_type.pipeline.context import TuningContext
from core.algorithm.model_type.pipeline.stages.base_stage import PipelineStage


class RefinementStage(PipelineStage):
    """
    模型优化与冗余兜底阶段:
    1. 验证一致性与仿真匹配度 (_orchestrator_ref._validate_and_refine)
    2. 恢复闭环修正T1
    3. 检查融合参数有效性 (尝试 Oscillation Fallback)
    4. 继电反馈法 (Relay Feedback) 的方法竞争如果更优秀则采用其参数
    """
    def __init__(self, orchestrator_ref, oscillation_tuner, method_selector, pid_calculator, logger_mixin=None):
        super().__init__(logger_mixin)
        self._orchestrator_ref = orchestrator_ref
        self._oscillation_tuner = oscillation_tuner
        self._method_selector = method_selector
        self._pid_calculator = pid_calculator
        self._epsilon = 1e-6

    def execute(self, context: TuningContext) -> TuningContext:
        if context.is_fallback_triggered or context.final_result is not None:
            return context

        # 1. 验证一致性与仿真匹配度 (调用外部包裹函数)
        fusion_result = self._orchestrator_ref._validate_and_refine(
            context.fusion_result, context.segments_for_fitting, context.hist_data
        )

        # 2. 恢复闭环修正值
        if context.corrected_T1 is not None:
            if abs(fusion_result.T1 - context.corrected_T1) > 0.01:
                self.log(f"   ⚠️ Step 5优化改变了闭环修正值 (T1: {context.corrected_T1:.2f} → {fusion_result.T1:.2f})")
                self.log(f"   → 恢复闭环修正 T1={context.corrected_T1:.2f}s, K={context.corrected_K:.4f}")
                fusion_result.T1 = context.corrected_T1
                fusion_result.K = context.corrected_K

        # 把改动放回 context
        context.fusion_result = fusion_result

        # 3. 检查融合参数是否有效 (K或T1不能为0)
        if abs(fusion_result.K) < self._epsilon or fusion_result.T1 < self._epsilon:
            self.log("\n   ⚠️ 参数融合失败（K或T1为0），尝试振荡整定fallback...")
            fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                context.segments_for_fitting, context.segment_results_fitted, context.current_pid, force=True
            )
            if fallback_result is not None:
                self.log("   ✅ 振荡整定fallback成功")
                context.final_result = self._oscillation_tuner.build_oscillation_output(
                    fallback_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                    context.original_segments, context.original_results
                )
            else:
                self.log("   ❌ 振荡整定fallback也失败")
                context.is_fallback_triggered = True
            return context

        # 4. 使用方法选择器验证稳定性，必要时使用继电反馈法(Relay Feedback)
        model_params = {
            'K': fusion_result.K, 'T1': fusion_result.T1,
            'T2': fusion_result.T2, 'L': fusion_result.L
        }
        method_result = self._method_selector.select_and_tune(
            context.segments_for_fitting, context.segment_results_fitted,
            model_params=model_params, lambda_factor=context.lambda_factor,
            loop_type=context.loop_type
        )
        
        # 继电反馈法胜利条件判断
        from core.algorithm.model_type.tuning import TuningMethod
        use_relay = False
        if (method_result.method == TuningMethod.RELAY_FEEDBACK and 
            method_result.stability_margins and 
            method_result.stability_margins.is_stable):
            
            relay_pm = method_result.stability_margins.phase_margin
            relay_gm = method_result.stability_margins.gain_margin
            Pu_relay = (method_result.critical_params or {}).get('Pu', 0)
            
            if Pu_relay >= 500:
                self.log(f"\n   ⚠️ 继电反馈法 Pu={Pu_relay:.1f}s 触达上限，放弃使用")
            else:
                from core.algorithm.model_type.tuning.verification.stability_analyzer import StabilityAnalyzer
                model_pid = self._pid_calculator.calculate_from_fusion(fusion_result, context.lambda_factor)
                model_margins = StabilityAnalyzer.check_stability(model_params, model_pid)
                model_pm = model_margins.phase_margin if model_margins else 0
                model_gm = model_margins.gain_margin if model_margins else 0
                
                pm_advantage = relay_pm - model_pm
                gm_ok = (model_gm < 0.01) or (relay_gm >= model_gm * 0.5)
                
                if pm_advantage >= 10 and gm_ok:
                    use_relay = True
                    self.log(f"\n🎯 继电反馈法显著更优 (PM={relay_pm:.1f}° vs {model_pm:.1f}°, "
                            f"GM={relay_gm:.2f} vs {model_gm:.2f})，使用继电反馈法参数")
                else:
                    self.log(f"\n   继电反馈法未显著优于模型辨识法 "
                            f"(PM差={pm_advantage:.1f}°, GM比={relay_gm:.2f}/{model_gm:.2f})，使用模型辨识法")

        if use_relay:
            # 继电反馈法胜出：走 _build_method_selector_output 结束整个流程
            context.final_result = self._orchestrator_ref._build_method_selector_output(
                method_result, fusion_result, context.hist_data, context.time_range,
                context.input_data.tuning_window, context.original_segments, context.original_results
            )
            
        return context
