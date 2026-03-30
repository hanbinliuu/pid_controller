import numpy as np
from ...data_models import HistoricalData, SegmentResult
from ..context import TuningContext
from .base_stage import PipelineStage

class SegmentationStage(PipelineStage):
    """
    数据分段与筛选阶段:
    1. 提取基础扰动段，检查无MV变化或存粹PV振荡
    2. 优先检测 SV 阶跃响应段
    3. 提取 MV 阶跃整定段并与扰动合并
    4. 智能降采样
    5. 分类为整定段和振荡段
    """
    def __init__(self, segment_processor, segment_manager, oscillation_tuner, logger_mixin=None):
        super().__init__(logger_mixin)
        self._segment_processor = segment_processor
        self._segment_manager = segment_manager
        self._oscillation_tuner = oscillation_tuner

    def _check_mv_no_change(self, segments: list) -> bool:
        """检查MV是否基本无变化"""
        total_mv_range = 0
        for seg in segments:
            if len(seg.mv) > 0:
                total_mv_range += np.ptp(seg.mv)
        return total_mv_range < 0.1

    def execute(self, context: TuningContext) -> TuningContext:
        """执行段提取和筛选"""
        
        # 1. 提取来自 tuning_segment 的扰动段
        raw_segs = self._segment_processor.extract_segments(context.hist_data, context.input_data.tuning_window)
        disturbance_segs, disturbance_results = self._segment_processor.filter_invalid_segments(raw_segs)
        
        self.log(f"📊 扰动段: {len(disturbance_segs)} 个有效")
        
        # 处理完全无扰动段的特殊情况 (液位纯PV震荡)
        if not disturbance_segs:
            pv_range = np.ptp(context.hist_data.pv)
            pv_mean = np.mean(np.abs(context.hist_data.pv)) + 1e-9
            has_pv_oscillation = pv_range > pv_mean * 0.01  # PV波动超过1%
            
            if has_pv_oscillation and len(raw_segs) > 0:
                self.log(f"⚠️ 无有效扰动段(MV无变化)，但PV存在振荡(range={pv_range:.2f})，尝试振荡整定fallback")
                dummy_results = [
                    SegmentResult(segment_idx=i, start_idx=0, end_idx=len(seg.pv)-1,
                                  data_points=len(seg.pv), is_valid=True)
                    for i, seg in enumerate(raw_segs)
                ]
                osc_result = self._oscillation_tuner.try_oscillation_tuning(
                    raw_segs, dummy_results, context.current_pid, force=True
                )
                if osc_result and osc_result.get('success'):
                    self.log(f"✅ 振荡整定fallback成功")
                    context.final_result = self._oscillation_tuner.build_oscillation_output(
                        osc_result, context.hist_data, context.time_range, tuning_windows=None
                    )
                    return context
            
            self.log("⚠️ 无有效扰动段，跳过整定")
            context.is_fallback_triggered = True # Mark failure path
            return context
            
        # 2. 尝试寻找 SV阶跃 和 MV阶跃段
        sv_step_segs, sv_step_results = self._segment_processor.detect_sv_step_segments(context.hist_data)
        
        if sv_step_segs:
            self.log(f"✅ 找到 {len(sv_step_segs)} 个 SV 阶跃响应段（优先使用）")
            valid_segments = sv_step_segs
            segment_results = sv_step_results
            context.from_sv_step = True
        else:
            self.log(f"📊 无SV阶跃段，使用 {len(disturbance_segs)} 个扰动段")
            tuning_segs_mv, tuning_results_mv = self._segment_processor.detect_tuning_segments(context.hist_data)
            
            if tuning_segs_mv:
                self.log(f"✅ 找到 {len(tuning_segs_mv)} 个整定段")
                valid_segments, segment_results = self._segment_manager.merge_tuning_and_disturbance(
                    tuning_segs_mv, tuning_results_mv, disturbance_segs, disturbance_results, context.hist_data
                )
            else:
                self.log(f"⚠️ 未找到整定段，使用 {len(disturbance_segs)} 个扰动段")
                valid_segments = disturbance_segs
                segment_results = disturbance_results
        
        # 3. 备份原始段数据（降采样前）
        context.original_segments = [
            HistoricalData(
                timestamp=seg.timestamp.copy(), pv=seg.pv.copy(),
                sv=seg.sv.copy(), mv=seg.mv.copy()
            ) for seg in valid_segments
        ]
        context.original_results = [
            SegmentResult(
                segment_idx=r.segment_idx, start_idx=r.start_idx, end_idx=r.end_idx,
                data_points=r.data_points, is_valid=r.is_valid, invalid_reason=r.invalid_reason,
                quality_score=r.quality_score, nonlinearity_score=r.nonlinearity_score,
                step_response_score=r.step_response_score, oscillation_ratio=r.oscillation_ratio,
                is_nonlinear=r.is_nonlinear
            ) for r in segment_results
        ]
        
        # 4. 降采样
        if context.enable_downsample and valid_segments:
            valid_segments = self._segment_manager.apply_smart_downsample(valid_segments, context.downsample_target)
            
        if not valid_segments:
            self.log("⚠️ 无有效段(降采样后被清空)")
            context.is_fallback_triggered = True
            return context
            
        if self._check_mv_no_change(valid_segments):
            self.log("❌ MV无变化，无法进行模型辨识")
            context.is_fallback_triggered = True
            return context
            
        self.log(f"📊 最终有效段: {len(valid_segments)} 个")
        
        # 5. 分类为整定段与振荡段
        tuning_segs, tuning_results, osc_segs, osc_results = self._segment_manager.classify_and_prioritize_segments(
            valid_segments, segment_results
        )
        
        if tuning_segs:
            self.log(f"✅ 使用 {len(tuning_segs)} 个整定段进行模型辨识")
            context.segments_for_fitting = tuning_segs
            context.results_for_fitting = tuning_results
        else:
            use_disturbance = False
            if osc_segs and len(osc_segs) > 0:
                total_osc_points = sum(len(seg.pv) for seg in osc_segs)
                if total_osc_points < 100 and disturbance_segs:
                    self.log(f"⚠️ 振荡段太短({total_osc_points}点)，使用原始扰动段({sum(len(s.pv) for s in disturbance_segs)}点)")
                    context.segments_for_fitting = disturbance_segs
                    context.results_for_fitting = disturbance_results
                    use_disturbance = True
            if not use_disturbance:
                self.log(f"⚠️ 无整定段，使用全部 {len(valid_segments)} 个段")
                context.segments_for_fitting = valid_segments
                context.results_for_fitting = segment_results
                
        # 存下 disturbance 备用 (如果全拟合失败时会作为 fallback)
        context.valid_segments = disturbance_segs
        context.segment_results = disturbance_results
        
        return context
