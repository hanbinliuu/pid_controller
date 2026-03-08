import numpy as np
from typing import List, Dict, Any

from core.algorithm.model_type.data_models import FusionResult, SegmentResult, HistoricalData
from core.algorithm.model_type.fitting.type_selector import SegmentModelFit
from core.algorithm.model_type.pipeline.context import TuningContext
from core.algorithm.model_type.pipeline.stages.base_stage import PipelineStage
from core.algorithm.model_type.config import ModelType
from core.algorithm.model_type.utils import calculate_r2
from core.algorithm.model_type.fitting.segment_fitter import SegmentFitter
from core.algorithm.model_type.config.loop_type_inferrer import infer_loop_type, format_inference_log


class FusionStage(PipelineStage):
    """
    模型融合阶段:
    1. 选择最佳模型类型 (FOPDT/SOPDT等)
    2. 参数融合
    3. 闭环修正 (如果数据来源于SV阶跃)
    4. 自动回路类型精准推理
    """
    def __init__(self, unified_selector, param_fusion, simulator, segment_processor, oscillation_tuner, logger_mixin=None):
        super().__init__(logger_mixin)
        self._unified_selector = unified_selector
        self._param_fusion = param_fusion
        self._simulator = simulator
        self._segment_processor = segment_processor
        self._oscillation_tuner = oscillation_tuner
        self._epsilon = 1e-6

    def _convert_to_segment_fits(self, segment_results: List[SegmentResult]) -> List[SegmentModelFit]:
        """将SegmentResult转换为SegmentModelFit格式"""
        segment_fits = []
        for result in segment_results:
            if not result.is_valid or not result.model_results:
                continue
            fit = SegmentModelFit(
                segment_idx=result.segment_idx,
                data_points=result.data_points,
                quality_score=result.quality_score,
                nonlinearity_score=result.nonlinearity_score,
                is_nonlinear=result.is_nonlinear,
                model_fits=result.model_results
            )
            segment_fits.append(fit)
        return segment_fits

    def _validate_model_type_with_fulldata(self, current_model: str, hist_data: HistoricalData) -> str:
        """使用全量数据验证/选择模型类型"""
        self.log("\\n   📊 全量数据模型验证:")
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        
        if len(y) < 50:
            self.log("      数据点数不足，保持原选择")
            return current_model
        
        t = np.arange(len(y))
        y0 = y[0]
        model_r2s = {}
        
        for model_type in ModelType.CANDIDATE_MODELS:
            try:
                method = SegmentFitter.IDENTIFY_METHODS.get(model_type)
                if method is None:
                    continue
                
                params_raw = method(t, y, u)
                y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                r2 = calculate_r2(y, y_pred)
                
                # 应用复杂度惩罚
                penalty = self._unified_selector.COMPLEXITY_PENALTY.get(model_type, 0)
                adjusted_r2 = r2 - penalty
                
                model_r2s[model_type] = {
                    'r2': r2,
                    'adjusted_r2': adjusted_r2
                }
                self.log(f"      {model_type}: R²={r2:.4f}, 调整R²={adjusted_r2:.4f}")
            except Exception as e:
                self.log(f"      {model_type}: 拟合失败 - {e}")
        
        if not model_r2s:
            return current_model
        
        best_fulldata_model = max(model_r2s.keys(), key=lambda m: model_r2s[m]['adjusted_r2'])
        best_r2 = model_r2s[best_fulldata_model]['adjusted_r2']
        current_r2 = model_r2s.get(current_model, {}).get('adjusted_r2', 0)
        
        if best_r2 > current_r2 + 0.05:
            self.log(f"      → 全量数据选择: {best_fulldata_model} (R²提升: {best_r2 - current_r2:.4f})")
            return best_fulldata_model
        else:
            self.log(f"      → 保持原选择: {current_model}")
            return current_model

    def _select_best_model_type(self, segment_results: List[SegmentResult], hist_data: HistoricalData = None) -> str:
        """选择最优模型结构"""
        segment_fits = self._convert_to_segment_fits(segment_results)
        if not segment_fits:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        best_model, reasoning, need_fulldata = self._unified_selector.select_unified_model_type(segment_fits)
        
        diagnosis = self._unified_selector.handle_inconsistent_segments(segment_fits)
        if diagnosis['has_inconsistency']:
            self.log("\\n   ⚠️ 检测到段间不一致:")
            for issue in diagnosis['issues']:
                self.log(f"      - {issue}")
            if diagnosis['recommendations']:
                self.log("   💡 建议:")
                for rec in diagnosis['recommendations']:
                    self.log(f"      - {rec}")
        
        self.log(f"\\n🎯 统一模型选择: {best_model}")
        
        if need_fulldata and hist_data is not None:
            fulldata_model = self._validate_model_type_with_fulldata(best_model, hist_data)
            if fulldata_model != best_model:
                self.log(f"   📊 全量数据验证: {best_model} → {fulldata_model}")
                best_model = fulldata_model
        
        return best_model

    def _apply_closed_loop_correction(self, fusion: FusionResult, current_pid: dict = None, sv_step_segments: list = None) -> FusionResult:
        """闭环数据修正（v4.0 CLHM+YS 升级版）"""
        from core.algorithm.model_type.fitting.closed_loop_identifier import ClosedLoopIdentifier
        
        cfg = self._segment_processor._tuning_config
        fallback_factor = cfg.get('sv_closed_loop_t1_factor', 3.0)

        self.log(f"\\n{'='*60}")
        self.log("📊 Step 4.5: 闭环数据修正（CLHM+YS 三层辨识）")
        self.log('='*60)

        T1_original = fusion.T1
        K_original = fusion.K

        if current_pid and sv_step_segments and len(sv_step_segments) > 0:
            try:
                identifier = ClosedLoopIdentifier(log_func=self.log)
                seg = sv_step_segments[0]
                result = identifier.identify(
                    pv=seg.pv,
                    sv=seg.sv,
                    mv=seg.mv,
                    timestamp=seg.timestamp,
                    current_pid=current_pid,
                    fitted_K_cl=fusion.K,
                    fitted_T1_cl=fusion.T1,
                    fitted_L_cl=fusion.L
                )
                
                fusion.T1 = result.T1_ol
                fusion.K = result.K_ol
                if result.L_ol > 0.1:
                    fusion.L = result.L_ol
                
                self.log(f"   修正方法: {result.method} (置信度={result.confidence:.2f})")
                self.log(f"   K: {K_original:.4f} → {fusion.K:.4f}")
                self.log(f"   T1: {T1_original:.2f}s → {fusion.T1:.2f}s")
                self.log(f"   L: {fusion.L:.2f}s")
                
                return fusion
            except Exception as e:
                self.log(f"   ⚠️ 三层辨识失败({e})，回退到传统修正")

        adaptive_factor = None
        factor_source = 'config_fallback'

        if current_pid and abs(fusion.K) > self._epsilon:
            kp_raw = current_pid.get('Kp', current_pid.get('kp', None))
            if kp_raw is None and 'pb' in current_pid:
                pb = current_pid['pb']
                kp_raw = 100.0 / max(abs(pb), 1.0)
            if kp_raw is not None:
                Kp_val = abs(float(kp_raw))
                K_abs = abs(fusion.K)
                raw_factor = 1.0 + K_abs * Kp_val
                adaptive_factor = float(np.clip(raw_factor, 1.5, 15.0))
                factor_source = f'adaptive(K={K_abs:.3f}×Kp={Kp_val:.3f})'

        t1_factor = adaptive_factor if adaptive_factor is not None else fallback_factor
        T1_corrected = fusion.T1 * t1_factor

        self.log(f"   修正因子来源: {factor_source} → ×{t1_factor:.2f}")
        self.log(f"   闭环T1 = {T1_original:.2f}s → 开环T1(估) = {T1_corrected:.2f}s")
        self.log(f"   K = {fusion.K:.4f} (保持不变 - 传统模式)")

        fusion.T1 = T1_corrected
        return fusion

    def _auto_infer_loop_type(self, context: TuningContext, fusion_result: FusionResult, model_type: str, segment_results: List[SegmentResult] = None):
        """Step 4.6: 回路类型精确推断（基于模型参数）"""
        process_context = context.process_context or {}
        if process_context:
            loop_type_source = process_context.get('loop_type_source', '')
            current_loop_type = process_context.get('loop_type', '')
            if current_loop_type and loop_type_source not in ('early_data', ''):
                self.log(f"   📊 Step 4.6: 回路类型（外部指定: {current_loop_type}）")
                return
        
        if abs(fusion_result.K) < 1e-6 or fusion_result.T1 < 1e-6:
            self.log(f"   ⚠️ 模型参数无效(K={fusion_result.K:.4f}, T1={fusion_result.T1:.2f})，跳过模型推断")
            return
        
        model_params = {
            'K': fusion_result.K,
            'T1': fusion_result.T1,
            'T2': fusion_result.T2,
            'L': fusion_result.L,
        }
        
        loop_type, confidence, reason = infer_loop_type(model_params, model_type)
        
        early_confidence = process_context.get('loop_type_confidence', 0)
        early_loop_type = process_context.get('loop_type', '')
        
        self.log(f"\\n{'='*60}")
        self.log("📊 Step 4.6: 回路类型精确推断（基于模型参数）")
        self.log('='*60)
        self.log(f"   {format_inference_log(loop_type, confidence, reason)}")
        
        if early_loop_type and early_loop_type != loop_type:
            is_oscillating = False
            max_osc_ratio = 0.0
            if segment_results:
                max_osc_ratio = max((r.oscillation_ratio for r in segment_results if hasattr(r, 'oscillation_ratio')), default=0.0)
                if max_osc_ratio > 0.15:
                    is_oscillating = True
            
            if is_oscillating:
                self.log(f"   ⚠️ 检测到振荡(ratio={max_osc_ratio:.2f})，禁止模型推断覆盖早期推断")
                self.log(f"   → 保持早期推断: {early_loop_type}(置信度{early_confidence:.0%})，防止模型参数失真误判")
                return

            if confidence > early_confidence:
                self.log(f"   ↑ 覆盖早期推断: {early_loop_type}(置信度{early_confidence:.0%}) → {loop_type}(置信度{confidence:.0%})")
            else:
                self.log(f"   → 保持早期推断: {early_loop_type}(置信度{early_confidence:.0%})，模型推断置信度不足")
                return
        elif early_loop_type == loop_type:
            self.log(f"   ✓ 与早期推断一致: {loop_type}")
        
        context.process_context['loop_type'] = loop_type
        context.process_context['loop_type_inferred'] = True
        context.process_context['loop_type_confidence'] = confidence
        context.process_context['loop_type_source'] = 'model_params'
        
        loop_name = context.process_context.get('loop_name', '')
        # update oscillation tuner loop_type explicitly
        self._oscillation_tuner.set_llm_client(self._oscillation_tuner._llm_client, loop_type, loop_name)
        
        fusion_result.loop_type = loop_type

    def execute(self, context: TuningContext) -> TuningContext:
        """执行参数融合与选择"""
        if context.is_fallback_triggered or context.final_result is not None:
            return context
            
        # 1. 基于AIC/RSS/形状特征选择最优模型结构
        best_model_type = self._select_best_model_type(context.segment_results_fitted, context.hist_data)
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
            fusion_result = self._apply_closed_loop_correction(
                fusion_result, context.current_pid, context.sv_step_segs
            )
            corrected_T1 = fusion_result.T1
            corrected_K = fusion_result.K
            
        # 4. 回路类型精确推断
        self._auto_infer_loop_type(
            context, fusion_result, best_model_type, context.segment_results_fitted
        )
        
        # Update context
        if fusion_result.loop_type != context.loop_type:
            context.loop_type = fusion_result.loop_type
            
        context.fusion_result = fusion_result
        context.corrected_T1 = corrected_T1
        context.corrected_K = corrected_K
        
        return context
