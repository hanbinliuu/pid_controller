"""
段处理模块 (Segment Processor Module)
=====================================

本模块负责扰动段的提取、过滤和有效性检查。

核心功能
--------
1. **段提取**: 根据时间窗口从历史数据中提取扰动段
2. **有效性过滤**: 过滤无效的扰动段（数据点不足、无响应等）
3. **质量检测**: 检测非线性、振荡等数据质量问题
4. **稳态分析**: 分析扰动段的稳态特征

过滤条件
--------
- 数据点过少 (< 30点)
- PV变化过小（无响应）
- MV变化过小（无激励）
- PV=0 异常点过多
- 数据趋势不合理（非阶跃响应特征）
- 严重非线性
- 严重振荡
"""

import numpy as np
from typing import List, Tuple

from ..config import Config
from ..data_models import SegmentResult, HistoricalData, TuningWindow
from .data_preprocessor import DataPreprocessor
from ..utils import parse_timestamp
from ..logger import LoggerMixin


class SegmentProcessor(LoggerMixin):
    """段处理器 - 负责段提取、过滤和有效性检查"""
    
    def __init__(self, verbose: bool = False):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(verbose=verbose)
        # 从集中化配置获取阈值
        self._seg_config = Config.SEGMENT_PROCESSING
        self._tuning_config = Config.TUNING_SEGMENT
    
    def extract_segments(self, hist_data: HistoricalData, 
                         windows: List[TuningWindow]) -> List[HistoricalData]:
        """提取所有扰动段数据"""
        segments = []
        timestamps = hist_data.timestamp
        
        for i, w in enumerate(windows):
            start_ts = parse_timestamp(w.start_time)
            end_ts = parse_timestamp(w.end_time)
            
            if start_ts is None or end_ts is None:
                continue
            
            mask = (timestamps >= start_ts) & (timestamps <= end_ts)
            indices = np.where(mask)[0]
            
            if len(indices) < 10:
                continue
            
            segment = HistoricalData(
                timestamp=hist_data.timestamp[indices],
                pv=hist_data.pv[indices],
                sv=hist_data.sv[indices],
                mv=hist_data.mv[indices]
            )
            segments.append(segment)
        
        return segments
    
    def filter_invalid_segments(self, segments: List[HistoricalData]
                                ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        过滤无效扰动段
        
        无效条件：
        1. 数据点过少 (< 20)
        2. PV变化过小（无响应）
        3. MV变化过小（无激励）
        4. PV=0 异常点过多
        5. 数据趋势不合理（非阶跃响应特征）
        6. 非线性扰动检测
        7. 数据质量检测
        """
        valid_segments = []
        segment_results = []
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1: 扰动段有效性检查（增强版）")
        self.log('='*60)
        
        for i, seg in enumerate(segments):
            result = SegmentResult(
                segment_idx=i,
                start_idx=0,
                end_idx=len(seg),
                data_points=len(seg),
                is_valid=True
            )
            
            # 从配置获取阈值
            min_points = self._seg_config['min_data_points']
            min_pv = self._seg_config['min_pv_range']
            min_mv = self._seg_config['min_mv_range']
            
            # 检查1: 数据点数
            if len(seg) < min_points:
                self._mark_invalid(result, f"数据点不足({len(seg)}<{min_points})", i, segment_results)
                continue
            
            # 过滤无效数据点（NaN/Inf），不再使用 pv != 0 以避免误删合法零值
            valid_mask = np.isfinite(seg.pv) & np.isfinite(seg.mv)
            valid_count = np.sum(valid_mask)
            
            if valid_count < min_points:
                self._mark_invalid(result, f"有效点不足({valid_count}<{min_points})", i, segment_results)
                continue
            
            y, u = seg.pv[valid_mask], seg.mv[valid_mask]
            pv_range, mv_range = np.ptp(y), np.ptp(u)
            
            # 检查2: PV变化
            if pv_range < min_pv and np.std(y) < 0.1:
                self._mark_invalid(result, f"PV无变化(range={pv_range:.2f})", i, segment_results)
                continue
            
            # 检查3: MV变化
            if mv_range < min_mv:
                self._mark_invalid(result, f"MV无变化(range={mv_range:.2f})", i, segment_results)
                continue
            
            # 检查4: 阶跃响应形状特征
            shape_valid, shape_reason = self._check_step_response_shape(y, u)
            if not shape_valid:
                result.is_valid = False
                result.invalid_reason = shape_reason
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
                continue
            
            # 检查5: 数据质量检测（非线性、阶跃特征、振荡）
            quality = self._preprocessor.analyze_quality(y, u)
            result.quality_score = quality.quality_score
            result.nonlinearity_score = quality.nonlinearity_score
            result.step_response_score = quality.step_response_score
            result.oscillation_ratio = quality.oscillation_ratio
            result.is_nonlinear = quality.is_nonlinear
            
            # 检查6: 严重非线性过滤
            severe_nonlin = self._seg_config['severe_nonlinearity']
            if quality.nonlinearity_score > severe_nonlin and quality.step_response_score < 0.3:
                self._mark_invalid(result, f"严重非线性(非线性={quality.nonlinearity_score:.2f}, 阶跃特征={quality.step_response_score:.2f})", i, segment_results)
                continue
            
            # 检查7: 严重振荡 - 不再拒绝，而是标记用于振荡整定
            # 高振荡数据可以使用临界法整定，不应直接拒绝
            severe_osc = self._seg_config['severe_oscillation']
            low_quality = self._seg_config['low_quality_threshold']
            if quality.oscillation_ratio > severe_osc and quality.quality_score < low_quality:
                # 标记为高振荡段，但仍然认为有效，让后续流程尝试振荡整定
                result.is_high_oscillation = True
                self.log(f"   段{i+1}: ⚠️ 高振荡数据(振荡={quality.oscillation_ratio:.2f}, 质量分={quality.quality_score:.2f})，将尝试临界法整定")
            
            # 有效段
            result.is_valid = True
            result.data_points = valid_count
            
            # 根据质量给出细分评价
            quality_flag = ""
            if quality.is_nonlinear:
                quality_flag += " ⚠️非线性"
            if quality.oscillation_ratio > 0.3:
                quality_flag += " ⚠️振荡"
            if quality.quality_score < 0.5:
                quality_flag += " ⚠️低质量"
            
            self.log(f"   段{i+1}: ✓ 有效 ({valid_count}点, PV范围={pv_range:.2f}, MV范围={mv_range:.2f})")
            self.log(f"          质量评分={quality.quality_score:.2f}, 非线性={quality.nonlinearity_score:.2f}, "
                    f"阶跃特征={quality.step_response_score:.2f}, 振荡={quality.oscillation_ratio:.2f}{quality_flag}")
            
            valid_segments.append(seg)
            segment_results.append(result)
        
        return valid_segments, segment_results
    
    def _check_step_response_shape(self, y: np.ndarray, u: np.ndarray) -> Tuple[bool, str]:
        """
        检查是否具有阶跃响应的基本形状特征
        
        增强：支持延迟相关性检查，避免因过程延迟导致的误杀
        
        Returns:
            (is_valid, reason)
        """
        n = len(y)
        if n < 20:
            return False, "数据太短"
        
        corr_threshold = 0.1  # 相关性阈值
        
        def _safe_corr(a: np.ndarray, b: np.ndarray) -> float:
            """安全计算相关系数"""
            try:
                if len(a) < 5 or len(b) < 5:
                    return 0.0
                c = np.corrcoef(a, b)[0, 1]
                return 0.0 if np.isnan(c) else float(c)
            except Exception:
                return 0.0
        
        # 1. 同时刻相关性
        corr = _safe_corr(u, y)
        
        # 允许正相关或负相关（正向/反向作用系统）
        if abs(corr) >= corr_threshold:
            return True, ""
        
        # 2. 延迟相关性检查（考虑过程延迟）
        max_lag = int(min(max(10, n * 0.2), 200))
        max_lag = min(max_lag, n - 5)
        best_corr = corr
        best_lag = 0
        
        for lag in range(1, max_lag + 1):
            c = _safe_corr(u[:-lag], y[lag:])
            if abs(c) > abs(best_corr):
                best_corr = c
                best_lag = lag
        
        if abs(best_corr) >= corr_threshold:
            return True, ""
        
        # 3. 检查是否是积分过程（累积效应）
        y_cumsum = np.cumsum(u - np.mean(u))
        corr_cumsum = _safe_corr(y_cumsum, y)
        
        if abs(corr_cumsum) >= max(0.2, corr_threshold * 2):
            return True, ""
        
        # 所有检查都未通过
        if best_lag > 0 and abs(best_corr) > abs(corr):
            return False, f"无明显响应(corr={corr:.2f}, best_corr={best_corr:.2f}@lag={best_lag})"
        return False, f"无明显响应(corr={corr:.2f})"
    
    def _mark_invalid(self, result: SegmentResult, reason: str, idx: int, 
                      results_list: List[SegmentResult]) -> None:
        """标记段为无效并添加到结果列表"""
        result.is_valid = False
        result.invalid_reason = reason
        self.log(f"   段{idx+1}: ✗ {reason}")
        results_list.append(result)
    
    def detect_tuning_segments(self, hist_data: HistoricalData,
                               min_step_size: float = None,
                               min_response_time: int = None,
                               max_response_time: int = None
                               ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        基于MV阶跃变化检测整定段（适合模型辨识的数据段）
        
        整定段定义：MV有明显阶跃变化，PV有响应的区间
        
        Args:
            hist_data: 历史数据
            min_step_size: 最小阶跃幅度（MV变化量），默认从配置读取
            min_response_time: 最小响应时间（采样点数），默认从配置读取
            max_response_time: 最大响应时间（采样点数），默认从配置读取
        
        Returns:
            (tuning_segments, segment_results)
        """
        # 从配置读取默认值
        cfg = self._tuning_config
        
        self.log(f"\n{'='*60}")
        self.log("📊 整定段检测（基于MV阶跃变化）")
        self.log('='*60)
        
        mv = np.array(hist_data.mv, dtype=float)
        pv = np.array(hist_data.pv, dtype=float)
        sv = np.array(hist_data.sv, dtype=float)
        timestamp = hist_data.timestamp
        n = len(mv)
        
        # 引入最新的 Level 1 检测器
        try:
            # 使用绝对路径导入，避免相对路径的混乱
            from core.algorithm.tuning_segment.tuning_segment_detector import TuningSegmentDetector
        except ImportError:
            try:
                from ....tuning_segment.tuning_segment_detector import TuningSegmentDetector
            except ImportError:
                self.log("   ⚠️ 无法导入 TuningSegmentDetector")
                return [], []
            
        detector = TuningSegmentDetector()
        
        # 借用其内部方法打印自适应信息
        detector._adapt_to_process_timescale(pv)
        
        # 获取底层检测结果
        raw_segments = detector.detect(pv, sv, mv)
        
        if not raw_segments:
            self.log("   📊 检测到 0 个有效整定段")
            return [], []
            
        # 转换为 Orchestrator 需要的数据结构
        tuning_segments = []
        segment_results = []
        
        for idx, (start_idx, end_idx, setpoint, quality) in enumerate(raw_segments):
            # 添加质量过滤（防止低质量毛刺被当做整定段保留）
            if quality < 0.4:
                dir_str = "↑" if mv[min(n-1, start_idx+5)] >= mv[max(0, start_idx-5)] else "↓"
                self.log(f"   阶跃@{start_idx}: MV{dir_str}, 响应={end_idx-start_idx}点, 质量={quality:.2f} ✗ (分数过低已过滤)")
                continue
                
            seg_len = end_idx - start_idx
            
            # 提取段数据
            seg = HistoricalData(
                timestamp=timestamp[start_idx:end_idx],
                pv=hist_data.pv[start_idx:end_idx],
                sv=hist_data.sv[start_idx:end_idx],
                mv=hist_data.mv[start_idx:end_idx]
            )
            
            result = SegmentResult(
                segment_idx=len(tuning_segments),
                start_idx=start_idx,
                end_idx=end_idx,
                data_points=seg_len,
                is_valid=True
            )
            
            # 分析数据质量，使用原有的 analyze_quality 处理一些 Orchestrator 必要的属性
            quality_info = self._preprocessor.analyze_quality(seg.pv, seg.mv)
            result.quality_score = quality_info.quality_score
            result.nonlinearity_score = quality_info.nonlinearity_score
            # step_response_score 使用我们精细计算的 quality，Orchestrator 就靠这个筛选
            result.step_response_score = quality
            result.oscillation_ratio = quality_info.oscillation_ratio
            result.is_nonlinear = quality_info.is_nonlinear
            
            # 由于底层已经做过了评估，这里直接认为是 good_response
            step_size = mv[start_idx + min(5, seg_len - 1)] - np.mean(mv[max(0, start_idx-10):start_idx]) if start_idx > 0 else 0
            dir_str = "↑" if step_size >= 0 else "↓"
            
            self.log(f"   阶跃@{start_idx}: MV{dir_str}{abs(step_size):.1f}, "
                     f"响应={seg_len}点, 质量={quality:.2f} ✓")
                     
            tuning_segments.append(seg)
            segment_results.append(result)
            
        self.log(f"   📊 检测到 {len(tuning_segments)} 个有效整定段")
        return tuning_segments, segment_results
    
    def detect_sv_step_segments(self, hist_data: HistoricalData
                                ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        基于SV阶跃变化检测整定段（适合模型辨识的数据段）
        
        SV阶跃响应段是模型辨识最理想的数据：SV有明显阶跃变化，PV跟随响应。
        优先级高于MV阶跃段和扰动段。
        
        Args:
            hist_data: 历史数据
        
        Returns:
            (sv_step_segments, segment_results)
        """
        cfg = self._tuning_config
        sv_min_step = cfg.get('sv_min_step_size', 0.5)
        sv_stable_window = cfg.get('sv_stable_window', 20)
        sv_pre_step_points = cfg.get('sv_pre_step_points', 30)
        sv_max_response = cfg.get('sv_max_response_time', 3000)
        sv_min_response = cfg.get('sv_min_response_time', 30)
        
        self.log(f"\n{'='*60}")
        self.log("📊 SV阶跃响应段检测")
        self.log('='*60)
        
        sv = hist_data.sv
        pv = hist_data.pv
        mv = hist_data.mv
        timestamp = hist_data.timestamp
        n = len(sv)
        
        if n < sv_min_response * 3:
            self.log("   数据长度不足")
            return [], []
        
        # Step 1: 检测SV阶跃变化点
        sv_steps = self._detect_sv_steps(sv, sv_min_step, sv_stable_window)
        self.log(f"   检测到 {len(sv_steps)} 个SV阶跃变化点")
        
        if not sv_steps:
            self.log("   ⚠️ 未检测到SV阶跃变化")
            return [], []
        
        # Step 2: 确定每个阶跃的响应区间（index范围）
        step_ranges = []  # [(pre_start, end_idx, step_idx, step_size, step_dir), ...]
        
        for i, (step_idx, step_size, step_dir) in enumerate(sv_steps):
            pre_start = max(0, step_idx - sv_pre_step_points)
            
            # 找下一个SV阶跃点
            if i + 1 < len(sv_steps):
                next_step_idx = sv_steps[i + 1][0]
                end_idx = min(next_step_idx, step_idx + sv_max_response)
            else:
                end_idx = min(step_idx + sv_max_response, n)
            
            # 检查响应区间长度
            response_len = end_idx - step_idx
            if response_len < sv_min_response:
                self.log(f"   SV阶跃@{step_idx}: 响应区间太短({response_len}点), 跳过")
                continue
            
            step_ranges.append((pre_start, end_idx, step_idx, step_size, step_dir))
        
        if not step_ranges:
            self.log("   ⚠️ 无有效SV阶跃区间")
            return [], []
        
        # Step 3: 合并相邻/重叠的区间
        # 相邻阈值：两个区间之间的间隔 <= merge_gap 点，则合并
        merge_gap = sv_pre_step_points * 2  # 允许一定间隔
        merged_ranges = []  # [(start, end), ...]
        
        current_start, current_end = step_ranges[0][0], step_ranges[0][1]
        for i in range(1, len(step_ranges)):
            r_start, r_end = step_ranges[i][0], step_ranges[i][1]
            if r_start <= current_end + merge_gap:
                # 重叠或相邻，合并
                current_end = max(current_end, r_end)
            else:
                # 不相邻，保存当前合并段
                merged_ranges.append((current_start, current_end))
                current_start, current_end = r_start, r_end
        merged_ranges.append((current_start, current_end))
        
        self.log(f"   合并后: {len(step_ranges)} 个阶跃区间 → {len(merged_ranges)} 个合并段")
        
        # Step 4: 从合并后的区间提取段数据并评估质量
        sv_step_segments = []
        segment_results = []
        
        for m_start, m_end in merged_ranges:
            seg = HistoricalData(
                timestamp=timestamp[m_start:m_end],
                pv=pv[m_start:m_end],
                sv=sv[m_start:m_end],
                mv=mv[m_start:m_end]
            )
            seg_len = m_end - m_start
            
            # 找到该合并段内的第一个阶跃点作为评估参考
            first_step_in_range = None
            for r in step_ranges:
                if r[0] >= m_start and r[0] < m_end:
                    first_step_in_range = r
                    break
            
            if first_step_in_range is None:
                continue
            
            _, _, step_idx, step_size, step_dir = first_step_in_range
            pre_points = step_idx - m_start
            
            # 评估整个合并段的PV响应质量
            quality_score, is_good_response = self._evaluate_sv_step_response(
                seg.pv, seg.sv, seg.mv, step_size, step_dir,
                pre_points=pre_points
            )
            
            result = SegmentResult(
                segment_idx=len(sv_step_segments),
                start_idx=m_start,
                end_idx=m_end,
                data_points=seg_len,
                is_valid=is_good_response
            )
            
            # 分析数据质量
            quality = self._preprocessor.analyze_quality(seg.pv, seg.mv)
            result.quality_score = quality.quality_score
            result.nonlinearity_score = quality.nonlinearity_score
            result.step_response_score = quality_score
            result.oscillation_ratio = quality.oscillation_ratio
            result.is_nonlinear = quality.is_nonlinear
            
            # 统计该合并段内包含多少个阶跃
            steps_in_range = sum(1 for r in step_ranges if r[0] >= m_start and r[0] < m_end)
            
            if is_good_response:
                self.log(f"   合并段[{m_start}:{m_end}]: {seg_len}点, "
                        f"{steps_in_range}个阶跃, 质量={quality_score:.2f} ✓")
                sv_step_segments.append(seg)
                segment_results.append(result)
            else:
                self.log(f"   合并段[{m_start}:{m_end}]: {seg_len}点, "
                        f"{steps_in_range}个阶跃, 质量={quality_score:.2f} ✗")
        
        self.log(f"   📊 检测到 {len(sv_step_segments)} 个有效SV阶跃响应段")
        return sv_step_segments, segment_results
    
    def _detect_sv_steps(self, sv: np.ndarray, min_step_size: float = 0.5,
                         stable_window: int = 20) -> List[Tuple[int, float, int]]:
        """
        检测SV阶跃变化点
        
        Args:
            sv: SV数据数组
            min_step_size: 最小SV阶跃幅度
            stable_window: 稳定窗口大小
        
        Returns:
            [(step_idx, step_size, step_dir), ...]
        """
        n = len(sv)
        steps = []
        
        if n < stable_window * 3:
            return steps
        
        i = stable_window
        while i < n - stable_window:
            before_window = sv[max(0, i - stable_window):i]
            after_window = sv[i:min(n, i + stable_window)]
            
            before_std = np.std(before_window)
            before_mean = np.mean(before_window)
            after_mean = np.mean(after_window)
            step_size = after_mean - before_mean
            
            # SV阶跃：变化量大且变化前SV稳定
            if abs(step_size) >= min_step_size and before_std < abs(step_size) * 0.3:
                step_dir = 1 if step_size > 0 else -1
                steps.append((i, step_size, step_dir))
                # 跳过阶跃区域
                i += stable_window * 2
            else:
                i += 1
        
        return steps
    
    def _evaluate_sv_step_response(self, pv: np.ndarray, sv: np.ndarray,
                                    mv: np.ndarray, step_size: float,
                                    step_dir: int, pre_points: int = 30
                                    ) -> Tuple[float, bool]:
        """
        评估PV对SV阶跃的响应质量
        
        与MV阶跃评估不同，SV阶跃是闭环响应：
        - PV应该跟随SV变化
        - MV应该有相应的调节动作
        - 响应可以有超调但最终应该收敛
        
        Args:
            pv: PV数据
            sv: SV数据
            mv: MV数据
            step_size: SV阶跃幅度
            step_dir: 阶跃方向
            pre_points: 阶跃前稳态点数
        
        Returns:
            (quality_score, is_good_response)
        """
        n = len(pv)
        if n < 30:
            return 0.0, False
        
        scores = []
        
        # 响应区域（排除前置稳态）
        resp_pv = pv[pre_points:]
        resp_sv = sv[pre_points:]
        resp_mv = mv[pre_points:]
        resp_n = len(resp_pv)
        
        if resp_n < 20:
            return 0.0, False
        
        # ========== 1. PV跟随SV变化 ==========
        # PV应该向SV新值方向变化
        pv_initial = np.mean(pv[max(0, pre_points - 10):pre_points]) if pre_points > 5 else pv[0]
        pv_final = np.mean(resp_pv[-min(20, resp_n):])
        sv_new = np.mean(resp_sv[-min(20, resp_n):])
        
        pv_change = pv_final - pv_initial
        expected_change = sv_new - pv_initial
        
        # 方向一致性
        if abs(expected_change) > 0.1:
            direction_match = (pv_change * expected_change) > 0
            # 计算跟随比例
            follow_ratio = abs(pv_change) / abs(expected_change) if abs(expected_change) > 0 else 0
            
            if direction_match and follow_ratio > 0.5:
                scores.append(1.0)
            elif direction_match and follow_ratio > 0.2:
                scores.append(0.7)
            elif direction_match:
                scores.append(0.5)
            else:
                scores.append(0.2)
        else:
            # SV变化很小，检查PV是否有任何响应
            if np.ptp(resp_pv) > 0.5:
                scores.append(0.5)
            else:
                scores.append(0.3)
        
        # ========== 2. MV有调节动作 ==========
        mv_range = np.ptp(resp_mv)
        mv_initial = np.mean(mv[max(0, pre_points - 10):pre_points]) if pre_points > 5 else mv[0]
        mv_change = abs(np.mean(resp_mv[:min(30, resp_n)]) - mv_initial)
        
        if mv_range > 1.0 or mv_change > 0.5:
            scores.append(1.0)
        elif mv_range > 0.3:
            scores.append(0.7)
        else:
            # MV没有明显变化 — 可能是手动模式或控制器未动
            scores.append(0.3)
        
        # ========== 3. PV收敛性 ==========
        # 后1/3的PV应该比前1/3更接近新SV
        first_third = resp_pv[:resp_n // 3]
        last_third = resp_pv[resp_n * 2 // 3:]
        
        if len(last_third) > 5 and len(first_third) > 5:
            error_first = abs(np.mean(first_third) - sv_new)
            error_last = abs(np.mean(last_third) - sv_new)
            
            if error_last < error_first * 0.5:
                scores.append(1.0)
            elif error_last < error_first:
                scores.append(0.7)
            else:
                # 没有收敛但可能是积分过程或大延迟 — 不完全拒绝
                scores.append(0.4)
        
        # ========== 4. PV有足够的动态变化 ==========
        pv_range = np.ptp(resp_pv)
        if pv_range > abs(step_size) * 0.3:
            scores.append(1.0)
        elif pv_range > abs(step_size) * 0.1:
            scores.append(0.7)
        elif pv_range > 0.5:
            scores.append(0.5)
        else:
            scores.append(0.2)
        
        # ========== 综合评分 ==========
        quality_score = np.mean(scores) if scores else 0.0
        
        # SV阶跃响应段的通过阈值可以比MV阶跃低一些，
        # 因为闭环数据本身就是有价值的
        is_good_response = quality_score >= 0.5
        
        return float(quality_score), is_good_response
    
    def _detect_mv_steps(self, mv: np.ndarray, min_step_size: float = None,
                         stable_window: int = None) -> List[Tuple[int, float, int]]:
        """检测MV阶跃变化点"""
        cfg = self._tuning_config
        if min_step_size is None:
            min_step_size = cfg['min_step_size']
        if stable_window is None:
            stable_window = cfg['stable_window']
        step_std_ratio = cfg['step_std_ratio']
        
        n = len(mv)
        steps = []
        
        if n < stable_window * 3:
            return steps
        
        i = stable_window
        while i < n - stable_window:
            before_window = mv[max(0, i-stable_window):i]
            after_window = mv[i:min(n, i+stable_window)]
            
            before_std = np.std(before_window)
            before_mean = np.mean(before_window)
            after_mean = np.mean(after_window)
            step_size = after_mean - before_mean
            
            if abs(step_size) >= min_step_size and before_std < abs(step_size) * step_std_ratio:
                step_dir = 1 if step_size > 0 else -1
                steps.append((i, step_size, step_dir))
                i += stable_window * 2
            else:
                i += 1
        
        return steps
    
    def _evaluate_step_response(self, pv: np.ndarray, mv: np.ndarray,
                                 step_size: float, step_dir: int) -> Tuple[float, bool]:
        """
        评估PV对MV阶跃的响应质量
        
        关键改进：
        1. 增加PV动态变化检测（排除稳态区域）
        2. 检测PV响应方向与MV阶跃方向的一致性
        3. 检测响应是否有典型的阶跃响应形态
        """
        cfg = self._tuning_config
        n = len(pv)
        if n < 20:
            return 0.0, False
        
        scores = []
        
        # ========== 关键检查：PV必须有足够的动态变化 ==========
        pv_range = np.ptp(pv)  # PV变化范围
        pv_std = np.std(pv)    # PV标准差
        mv_range = np.ptp(mv)  # MV变化范围
        
        # 计算PV的动态变化率（相对于MV变化）
        mv_range_th = cfg['mv_range_threshold']
        pv_dynamic_ratio = pv_range / (mv_range + self._epsilon) if mv_range > mv_range_th else 0
        
        # 如果PV几乎不变化，直接拒绝
        min_pv_range = max(cfg['min_pv_range'], abs(step_size) * cfg['min_pv_change_ratio'])
        min_pv_std = cfg['min_pv_std']
        
        # PV范围和标准差至少有一个要达标
        if pv_range < min_pv_range and pv_std < min_pv_std:
            return 0.0, False
        
        # 额外检查：PV动态变化率（相对于MV）应该足够
        large_mv_range = cfg['large_mv_range']
        pv_dynamic_min = cfg['pv_dynamic_ratio_min']
        if mv_range > large_mv_range and pv_dynamic_ratio < pv_dynamic_min:
            return 0.0, False
        
        # ========== 1. PV变化幅度评分 ==========
        pv_change = pv[-1] - pv[0]  # 净变化
        
        # PV变化应该与MV阶跃成比例
        if abs(pv_change) > abs(step_size) * cfg['pv_change_ratio_good']:
            scores.append(1.0)
        elif abs(pv_change) > cfg['pv_change_abs_good']:
            scores.append(0.7)
        elif pv_range > min_pv_range:
            scores.append(0.5)
        else:
            scores.append(0.2)
        
        # ========== 2. 响应方向一致性 ==========
        # 正常过程：MV↑ → PV↑ 或 MV↑ → PV↓（取决于过程增益正负）
        # 检查PV主要变化方向
        pv_first_half = np.mean(pv[:n//2])
        pv_second_half = np.mean(pv[n//2:])
        pv_trend = pv_second_half - pv_first_half
        
        # 需要有明显的趋势（正或负都可以，但不能接近0）
        if abs(pv_trend) > pv_range * cfg['trend_ratio_good']:
            scores.append(1.0)
        elif abs(pv_trend) > pv_range * cfg['trend_ratio_acceptable']:
            scores.append(0.7)
        else:
            scores.append(0.3)
        
        # ========== 3. 收敛性检测 ==========
        first_third = pv[:int(n/3)]
        last_third = pv[int(n*2/3):]
        
        if len(last_third) > 5 and len(first_third) > 5:
            std_first = np.std(first_third)
            std_last = np.std(last_third)
            
            # 理想的阶跃响应：后期应该趋于稳定
            settling_ratio_th = cfg['settling_ratio_good']
            if std_first > self._epsilon:
                settling_ratio = std_last / std_first
                if settling_ratio < settling_ratio_th and std_first > min_pv_std:
                    scores.append(1.0)
                elif settling_ratio < 1.0:
                    scores.append(0.7)
                else:
                    scores.append(0.4)
            else:
                if std_last < min_pv_std:
                    scores.append(0.2)
                else:
                    scores.append(0.5)
        
        # ========== 4. 振荡比 ==========
        pv_diff = np.diff(pv)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        osc_ratio = sign_changes / (n - 2) if n > 2 else 0
        
        osc_good = cfg['osc_ratio_good']
        osc_acceptable = cfg['osc_ratio_acceptable']
        if osc_ratio < osc_good:
            scores.append(1.0)
        elif osc_ratio < osc_acceptable:
            scores.append(0.7)
        else:
            scores.append(0.3)
        
        # ========== 5. MV-PV相关性 ==========
        corr_good = cfg['corr_good']
        corr_acceptable = cfg['corr_acceptable']
        try:
            corr = np.corrcoef(mv, pv)[0, 1]
            if np.isnan(corr):
                corr = 0
            if abs(corr) > corr_good:
                scores.append(1.0)
            elif abs(corr) > corr_acceptable:
                scores.append(0.7)
            else:
                scores.append(0.4)
        except:
            scores.append(0.5)
        
        # ========== 6. 阶跃响应形态检测 ==========
        front_good = cfg['front_ratio_good']
        front_acceptable = cfg['front_ratio_acceptable']
        if n > 10:
            first_half_change = abs(pv[n//2] - pv[0])
            second_half_change = abs(pv[-1] - pv[n//2])
            total_change = first_half_change + second_half_change + self._epsilon
            
            front_ratio = first_half_change / total_change
            if front_ratio > front_good:
                scores.append(1.0)
            elif front_ratio > front_acceptable:
                scores.append(0.7)
            else:
                scores.append(0.5)
        
        # ========== 综合评分 ==========
        quality_score = np.mean(scores) if scores else 0.0
        
        # 判定条件
        quality_pass = cfg['quality_pass_threshold']
        osc_pass = cfg['osc_ratio_pass']
        is_good_response = quality_score >= quality_pass and osc_ratio < osc_pass
        
        return float(quality_score), is_good_response
    
    def analyze_segment_stability(self, seg: HistoricalData, 
                                   fit_result: dict) -> Tuple[float, float, float, bool]:
        """
        分析扰动段的稳态特征
        
        Args:
            seg: 扰动段数据
            fit_result: 该段的拟合结果
        
        Returns:
            (stability_score, oscillation_ratio, settling_quality, is_steady)
        """
        try:
            valid_mask = seg.valid_mask()
            y = seg.pv[valid_mask]
            u = seg.mv[valid_mask]
            
            if len(y) < 20:
                return 1.0, 0.0, 1.0, True
            
            # 1. 计算振荡比例
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            oscillation_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            oscillation_ratio = min(oscillation_ratio, 1.0)
            
            # 2. 计算收敛质量
            n = len(y)
            last_third = y[int(n * 2/3):]
            if len(last_third) > 5:
                std_last = np.std(last_third)
                std_full = np.std(y)
                if std_full > self._epsilon:
                    settling_quality = 1 - min(std_last / std_full, 1.0)
                else:
                    settling_quality = 1.0
                settling_quality = max(settling_quality, 0.0)
            else:
                settling_quality = 1.0
            
            # 3. 计算稳态评分
            r2 = fit_result.get('r2', 0)
            
            stability_score = (
                0.4 * r2 +
                0.3 * (1 - oscillation_ratio) +
                0.3 * settling_quality
            )
            stability_score = min(max(stability_score, 0.0), 1.0)
            
            # 4. 判断是否为稳态段
            steady_cfg = self._tuning_config
            is_steady = (oscillation_ratio < steady_cfg['steady_osc_ratio'] and 
                        settling_quality > steady_cfg['steady_settling_quality'] and 
                        r2 > steady_cfg['steady_r2'])
            
            self.log(f"      稳态分析: 振荡={oscillation_ratio:.2f}, "
                    f"收敛={settling_quality:.2f}, 评分={stability_score:.2f}, "
                    f"稳态={is_steady}")
            
            return stability_score, oscillation_ratio, settling_quality, is_steady
            
        except Exception as e:
            self.log(f"      稳态分析失败: {e}")
            return 1.0, 0.0, 1.0, True
