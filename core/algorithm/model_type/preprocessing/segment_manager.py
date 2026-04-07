"""
段管理模块 (Segment Manager Module)
===================================

本模块负责扰动段的管理和处理逻辑。

核心功能
--------
1. **段合并**: 整定段与扰动段的时间窗口合并
2. **段分类**: 区分整定段和振荡段
3. **智能降采样**: 对大数据量段进行降采样
4. **MV变化检查**: 检测MV是否有变化
5. **拟合失败检查**: 检查是否所有模型拟合都失败

从 model_selector.py 拆分出来，提高可维护性。
"""

import numpy as np
from typing import List, Tuple, Optional

from ..config import Config
from ..data_models import SegmentResult, HistoricalData
from ..logger import LoggerMixin


class SegmentManager(LoggerMixin):
    """
    段管理器
    
    职责：
    1. 整定段与扰动段合并
    2. 段分类（整定段/振荡段）
    3. 智能降采样
    4. MV变化检查
    5. 拟合失败检查
    """
    
    def __init__(self, preprocessor, verbose: bool = False):
        """
        Args:
            preprocessor: DataPreprocessor 实例
            verbose: 是否输出详细日志
        """
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._preprocessor = preprocessor
    
    def apply_smart_downsample(self, segments: List[HistoricalData], 
                               target_points: int = 1000) -> List[HistoricalData]:
        """
        对每个扰动段应用智能降采样
        
        Args:
            segments: 有效扰动段列表
            target_points: 每段目标点数
        
        Returns:
            降采样后的扰动段列表
        """
        downsampled = []
        total_original = 0
        total_downsampled = 0
        
        for i, seg in enumerate(segments):
            n = len(seg.pv)
            total_original += n
            
            # 自动估计目标点数（根据数据特征自适应）
            auto_target = self._preprocessor.estimate_optimal_target_points(
                n, pv=seg.pv, sv=seg.sv
            )
            actual_target = min(target_points, auto_target)
            
            if n <= actual_target:
                # 数据量小，不需要降采样
                downsampled.append(seg)
                total_downsampled += n
            else:
                # 执行智能降采样
                result = self._preprocessor.smart_downsample(
                    seg.pv, seg.mv, seg.sv, seg.timestamp,
                    target_points=actual_target,
                    min_points=100,
                    preserve_features=True
                )
                
                pv_down, mv_down, sv_down, ts_down = result
                
                # 创建新的 HistoricalData
                new_seg = HistoricalData(
                    timestamp=ts_down,
                    pv=pv_down,
                    sv=sv_down,
                    mv=mv_down
                )
                downsampled.append(new_seg)
                total_downsampled += len(pv_down)
                
                self.log(f"   📉 段{i+1}: {n} → {len(pv_down)} 点 (降采样率 {len(pv_down)/n*100:.1f}%)")
        
        if total_original > total_downsampled:
            reduction = (1 - total_downsampled / total_original) * 100
            self.log(f"📉 智能降采样: {total_original} → {total_downsampled} 点 (减少 {reduction:.1f}%)")
        
        return downsampled
    
    def check_mv_no_change(self, valid_segments: List[HistoricalData]) -> bool:
        """
        检查MV是否无变化（无变化无法进行模型辨识）
        
        Args:
            valid_segments: 有效扰动段列表
            
        Returns:
            True 如果所有段MV都无变化
        """
        for seg in valid_segments:
            mv = seg.mv
            if len(mv) < 2:
                continue
            mv_range = np.max(mv) - np.min(mv)
            # MV变化范围小于1%认为无变化
            mv_mean = np.mean(np.abs(mv)) if np.mean(np.abs(mv)) > 0 else 1.0
            if mv_range > mv_mean * 0.01 or mv_range > 1.0:
                return False  # 有变化
        return True  # 所有段MV都无变化
    
    def check_all_fitting_failed(self, segment_results: List[SegmentResult]) -> bool:
        """
        检查是否所有模型拟合都失败
        
        Args:
            segment_results: 段拟合结果列表
            
        Returns:
            True 如果所有拟合都失败
        """
        for result in segment_results:
            if result is None:
                continue
            # 检查是否有任何模型拟合成功（R² >= 0.3 且 K 值合理）
            model_results = getattr(result, 'model_results', {}) or {}
            for model_type, params in model_results.items():
                if params is None:
                    continue
                r2 = params.get('r2', 0)
                K = params.get('K', 0)
                # R² >= 0.3 且 K 值在合理范围内认为拟合成功
                if r2 >= 0.3 and 0.01 < abs(K) < 100:
                    return False  # 有成功的拟合
            
            # 检查非线性模型结果
            nonlinear = getattr(result, 'nonlinear_result', None)
            if nonlinear is not None:
                nl_r2 = nonlinear.get('r2', 0)
                nl_K = nonlinear.get('params', {}).get('K', 0) if nonlinear.get('params') else 0
                if nl_r2 >= 0.3 and 0.01 < abs(nl_K) < 100:
                    return False  # 非线性模型拟合成功
        return True  # 所有拟合都失败
    
    def classify_and_prioritize_segments(
        self, 
        valid_segments: List[HistoricalData], 
        segment_results: List[SegmentResult]
    ) -> Tuple[List[HistoricalData], List[SegmentResult], List[HistoricalData], List[SegmentResult]]:
        """
        将扰动段分类为整定段和振荡段，优先使用整定段
        
        整定段：阶跃特征好（step_response_score >= 0.5）且振荡不严重（oscillation_ratio < 0.5）
        振荡段：振荡比例高（oscillation_ratio >= 0.5）
        
        Args:
            valid_segments: 有效扰动段列表
            segment_results: 段结果列表
            
        Returns:
            (tuning_segments, tuning_results, oscillation_segments, oscillation_results)
        """
        tuning_segments = []      # 整定段（优先用于模型辨识）
        tuning_results = []
        oscillation_segments = [] # 振荡段（备用，用于临界法）
        oscillation_results = []
        
        # 阈值配置
        step_threshold = 0.5      # 阶跃特征阈值
        osc_threshold = 0.5       # 振荡比例阈值
        
        for seg, result in zip(valid_segments, segment_results):
            step_score = result.step_response_score
            osc_ratio = result.oscillation_ratio
            
            # 额外检查：段内PV是否仍在振荡
            pv_array = np.array(seg.pv)
            pv_std = np.std(pv_array)
            sv_mean = np.mean(seg.sv) if len(seg.sv) > 0 else 50.0
            
            # 相对振荡度：PV标准差 / SV均值
            relative_oscillation = pv_std / sv_mean if sv_mean > 0 else 0
            
            # 如果相对振荡度 > 5%，认为仍在振荡
            still_oscillating = relative_oscillation > 0.05
            
            # 分类：阶跃特征好且振荡不严重且段内不振荡 → 整定段
            if step_score >= step_threshold and osc_ratio < osc_threshold and not still_oscillating:
                tuning_segments.append(seg)
                tuning_results.append(result)
            else:
                oscillation_segments.append(seg)
                oscillation_results.append(result)
                if still_oscillating and step_score >= step_threshold:
                    self.log(f"   ⚠️ 段内仍在振荡 (PV_std/SV={relative_oscillation:.1%})，归类为振荡段")
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1.8: 整定段/振荡段分类")
        self.log('='*60)
        self.log(f"   整定段（阶跃特征好）: {len(tuning_segments)} 个")
        self.log(f"   振荡段（振荡为主）: {len(oscillation_segments)} 个")
        
        # 详细信息
        for i, (seg, result) in enumerate(zip(valid_segments, segment_results)):
            step_score = result.step_response_score
            osc_ratio = result.oscillation_ratio
            seg_type = "整定段" if (step_score >= step_threshold and osc_ratio < osc_threshold) else "振荡段"
            self.log(f"   段{i+1}: {seg_type} (阶跃={step_score:.2f}, 振荡={osc_ratio:.2f})")
        
        return tuning_segments, tuning_results, oscillation_segments, oscillation_results
    
    def merge_tuning_and_disturbance(
        self,
        tuning_segs: List[HistoricalData],
        tuning_results: List[SegmentResult],
        disturbance_segs: List[HistoricalData],
        disturbance_results: List[SegmentResult],
        hist_data: HistoricalData
    ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        合并整定段和扰动段的时间窗口
        
        逻辑：
        1. 优先使用整定段（MV阶跃检测到的）
        2. 如果整定段和扰动段有时间重叠，合并时间窗口并重新提取数据
        3. 不重叠的扰动段作为备用（振荡整定）
        
        Args:
            tuning_segs: 基于MV阶跃检测的整定段
            tuning_results: 整定段结果
            disturbance_segs: 基于扰动窗口提取的扰动段
            disturbance_results: 扰动段结果
            hist_data: 原始历史数据（用于重新提取合并段）
        
        Returns:
            (merged_segments, merged_results)
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1.6: 整定段与扰动段合并")
        self.log('='*60)
        self.log(f"   整定段（MV阶跃检测）: {len(tuning_segs)} 个")
        self.log(f"   扰动段（扰动窗口）: {len(disturbance_segs)} 个")
        
        # 从配置读取合并参数
        seg_config = Config.SEGMENT_PROCESSING
        gap_threshold = seg_config.get('merge_gap_threshold', 300000)
        expansion_max = seg_config.get('merge_expansion_max', 5.0)
        expansion_allow = seg_config.get('merge_expansion_allow', 2.0)
        quality_diff_threshold = seg_config.get('merge_quality_diff', 0.3)
        osc_diff_threshold = seg_config.get('merge_osc_diff', 0.4)
        
        merged_segments = []
        merged_results = []
        used_disturbance_indices = set()
        
        # 处理每个整定段
        for i, (tuning_seg, tuning_result) in enumerate(zip(tuning_segs, tuning_results)):
            tuning_start = tuning_seg.timestamp[0] if len(tuning_seg.timestamp) > 0 else 0
            tuning_end = tuning_seg.timestamp[-1] if len(tuning_seg.timestamp) > 0 else 0
            
            # 检查是否与某个扰动段重叠
            merged_with_disturbance = False
            for j, (dist_seg, dist_result) in enumerate(zip(disturbance_segs, disturbance_results)):
                if j in used_disturbance_indices:
                    continue
                    
                dist_start = dist_seg.timestamp[0] if len(dist_seg.timestamp) > 0 else 0
                dist_end = dist_seg.timestamp[-1] if len(dist_seg.timestamp) > 0 else 0
                
                # 检查时间是否有重叠或相近
                has_overlap = not (tuning_end + gap_threshold < dist_start or 
                                   dist_end + gap_threshold < tuning_start)
                
                if has_overlap:
                    merged_seg, merged_result = self._handle_overlap(
                        i, j, tuning_seg, tuning_result, dist_seg, dist_result,
                        hist_data, expansion_max, expansion_allow,
                        quality_diff_threshold, osc_diff_threshold
                    )
                    merged_segments.append(merged_seg)
                    merged_result.segment_idx = len(merged_segments) - 1
                    merged_results.append(merged_result)
                    used_disturbance_indices.add(j)
                    merged_with_disturbance = True
                    break
            
            if not merged_with_disturbance:
                # 整定段独立存在
                if len(disturbance_segs) > 0:
                    self.log(f"   - 舍弃 整定段{i+1}: 位于给定扰动窗口之外（严格遵循外部窗口输入）")
                else:
                    merged_segments.append(tuning_seg)
                    tuning_result.segment_idx = len(merged_segments) - 1
                    merged_results.append(tuning_result)
                    self.log(f"   + 整定段{i+1}: {len(tuning_seg.pv)}点, "
                            f"阶跃={tuning_result.step_response_score:.2f}, "
                            f"振荡={tuning_result.oscillation_ratio:.2f}")
        
        # 处理未合并的扰动段
        unused_indices = set(range(len(disturbance_segs))) - used_disturbance_indices
        for j in unused_indices:
            dist_seg = disturbance_segs[j]
            dist_result = disturbance_results[j]
            merged_segments.append(dist_seg)
            dist_result.segment_idx = len(merged_segments) - 1
            merged_results.append(dist_result)
            self.log(f"   + 保留 扰动段{j+1}: 未匹配到MV阶跃，原样保留({len(dist_seg.pv)}点, "
                    f"阶跃={dist_result.step_response_score:.2f})")
        
        self.log(f"   📊 合并后共 {len(merged_segments)} 个有效段")
        return merged_segments, merged_results
    
    def _handle_overlap(
        self, i: int, j: int,
        tuning_seg: HistoricalData, tuning_result: SegmentResult,
        dist_seg: HistoricalData, dist_result: SegmentResult,
        hist_data: HistoricalData,
        expansion_max: float, expansion_allow: float,
        quality_diff_threshold: float, osc_diff_threshold: float
    ) -> Tuple[HistoricalData, SegmentResult]:
        """处理重叠的整定段和扰动段"""
        tuning_start = tuning_seg.timestamp[0]
        tuning_end = tuning_seg.timestamp[-1]
        dist_start = dist_seg.timestamp[0]
        dist_end = dist_seg.timestamp[-1]
        
        # 判断包含关系
        tuning_is_subset = (tuning_start >= dist_start and tuning_end <= dist_end)
        dist_is_subset = (dist_start >= tuning_start and dist_end <= tuning_end)
        
        # 计算扩展比例
        tuning_duration = tuning_end - tuning_start
        dist_duration = dist_end - dist_start
        expansion_ratio = max(tuning_duration, dist_duration) / max(min(tuning_duration, dist_duration), 1)
        
        # 计算质量差异
        tuning_quality = tuning_result.step_response_score
        dist_quality = dist_result.step_response_score
        quality_diff = tuning_quality - dist_quality
        
        # 检查振荡差异
        tuning_osc = tuning_result.oscillation_ratio
        dist_osc = dist_result.oscillation_ratio
        osc_diff = dist_osc - tuning_osc
        
        if tuning_is_subset and expansion_ratio > expansion_max:
            # 整定段是扰动段的子集，且扩展比例太大，保留原整定段
            self.log(f"   + 整定段{i+1} ⊂ 扰动段{j+1}: 扩展比={expansion_ratio:.1f}x，保留原整定段")
            return tuning_seg, tuning_result
            
        elif dist_is_subset:
            # 扰动段是整定段的子集，使用整定段
            self.log(f"   + 扰动段{j+1} ⊂ 整定段{i+1}: 使用整定段")
            return tuning_seg, tuning_result
            
        elif quality_diff > quality_diff_threshold or osc_diff > osc_diff_threshold:
            # 质量差异大，不合并
            self.log(f"   + 整定段{i+1} 与 扰动段{j+1}: 质量差异大，保留原整定段")
            return tuning_seg, tuning_result
            
        elif expansion_ratio <= expansion_allow:
            # 扩展比例较小，可以合并
            merged_start = min(tuning_start, dist_start)
            merged_end = max(tuning_end, dist_end)
            merged_seg = self._extract_segment_by_time(hist_data, merged_start, merged_end)
            
            if merged_seg is not None and len(merged_seg.pv) > 0:
                tuning_result.data_points = len(merged_seg.pv)
                self.log(f"   + 整定段{i+1} ∩ 扰动段{j+1}: 合并（扩展比={expansion_ratio:.1f}x）")
                return merged_seg, tuning_result
            else:
                self.log(f"   + 整定段{i+1} 与 扰动段{j+1}: 合并失败，使用整定段")
                return tuning_seg, tuning_result
        else:
            # 扩展比例过大，只使用整定段
            self.log(f"   + 整定段{i+1} 与 扰动段{j+1}: 扩展比={expansion_ratio:.1f}x过大，保留原整定段")
            return tuning_seg, tuning_result
    
    def _extract_segment_by_time(self, hist_data: HistoricalData, 
                                  start_time: int, end_time: int) -> Optional[HistoricalData]:
        """根据时间范围从历史数据中提取段"""
        try:
            mask = (hist_data.timestamp >= start_time) & (hist_data.timestamp <= end_time)
            indices = np.where(mask)[0]
            
            if len(indices) < 10:
                return None
            
            return HistoricalData(
                timestamp=hist_data.timestamp[indices],
                pv=hist_data.pv[indices],
                sv=hist_data.sv[indices],
                mv=hist_data.mv[indices]
            )
        except Exception as e:
            self.log(f"   提取段失败: {e}")
            return None
