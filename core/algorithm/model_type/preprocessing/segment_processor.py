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


class SegmentProcessor:
    """段处理器 - 负责段提取、过滤和有效性检查"""
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(verbose=verbose)
        # 从集中化配置获取阈值
        self._seg_config = Config.SEGMENT_PROCESSING
    
    def log(self, msg: str):
        if self._verbose:
            print(msg)
    
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
            
            # 过滤PV=0的点
            valid_mask = seg.pv != 0
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
                               min_step_size: float = 1.0,
                               min_response_time: int = 30,
                               max_response_time: int = 3000
                               ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        基于MV阶跃变化检测整定段（适合模型辨识的数据段）
        
        整定段定义：MV有明显阶跃变化，PV有响应的区间
        
        Args:
            hist_data: 历史数据
            min_step_size: 最小阶跃幅度（MV变化量）
            min_response_time: 最小响应时间（采样点数）
            max_response_time: 最大响应时间（采样点数）
        
        Returns:
            (tuning_segments, segment_results)
        """
        self.log(f"\n{'='*60}")
        self.log("📊 整定段检测（基于MV阶跃变化）")
        self.log('='*60)
        
        mv = hist_data.mv
        pv = hist_data.pv
        sv = hist_data.sv
        timestamp = hist_data.timestamp
        n = len(mv)
        
        if n < min_response_time * 2:
            self.log("   数据长度不足")
            return [], []
        
        # Step 1: 检测MV阶跃变化点
        mv_steps = self._detect_mv_steps(mv, min_step_size)
        self.log(f"   检测到 {len(mv_steps)} 个MV阶跃变化点")
        
        if not mv_steps:
            self.log("   ⚠️ 未检测到MV阶跃变化")
            return [], []
        
        # Step 2: 从每个阶跃点提取整定段
        tuning_segments = []
        segment_results = []
        
        for i, (step_idx, step_size, step_dir) in enumerate(mv_steps):
            # 确定响应区间：从阶跃点开始，到下一个阶跃点或最大响应时间
            start_idx = step_idx
            
            # 找下一个阶跃点
            if i + 1 < len(mv_steps):
                next_step_idx = mv_steps[i + 1][0]
                end_idx = min(next_step_idx, start_idx + max_response_time)
            else:
                end_idx = min(start_idx + max_response_time, n)
            
            # 检查区间长度
            seg_len = end_idx - start_idx
            if seg_len < min_response_time:
                continue
            
            # 提取段数据
            seg = HistoricalData(
                timestamp=timestamp[start_idx:end_idx],
                pv=pv[start_idx:end_idx],
                sv=sv[start_idx:end_idx],
                mv=mv[start_idx:end_idx]
            )
            
            # 评估PV响应质量
            quality_score, is_good_response = self._evaluate_step_response(
                seg.pv, seg.mv, step_size, step_dir
            )
            
            result = SegmentResult(
                segment_idx=len(tuning_segments),
                start_idx=start_idx,
                end_idx=end_idx,
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
            
            if is_good_response:
                dir_str = "↑" if step_dir > 0 else "↓"
                self.log(f"   阶跃@{step_idx}: MV{dir_str}{abs(step_size):.1f}, "
                        f"响应={seg_len}点, 质量={quality_score:.2f} ✓")
                tuning_segments.append(seg)
                segment_results.append(result)
        
        self.log(f"   📊 检测到 {len(tuning_segments)} 个有效整定段")
        return tuning_segments, segment_results
    
    def _detect_mv_steps(self, mv: np.ndarray, min_step_size: float = 1.0,
                         stable_window: int = 10) -> List[Tuple[int, float, int]]:
        """检测MV阶跃变化点"""
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
            
            if abs(step_size) >= min_step_size and before_std < abs(step_size) * 0.5:
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
        n = len(pv)
        if n < 20:
            return 0.0, False
        
        scores = []
        rejection_reasons = []
        
        # ========== 关键检查：PV必须有足够的动态变化 ==========
        pv_range = np.ptp(pv)  # PV变化范围
        pv_std = np.std(pv)    # PV标准差
        mv_range = np.ptp(mv)  # MV变化范围
        
        # 计算PV的动态变化率（相对于MV变化）
        pv_dynamic_ratio = pv_range / (mv_range + self._epsilon) if mv_range > 0.1 else 0
        
        # 如果PV几乎不变化，直接拒绝
        # 阈值设计原则：
        # - 需要有可见的动态响应（PV范围 > 2.0 或 相对于MV的5%）
        # - 标准差也要足够（说明有变化过程）
        min_pv_range = max(2.0, abs(step_size) * 0.05)  # 最小PV变化范围
        min_pv_std = 0.3  # 最小PV标准差
        
        # PV范围和标准差至少有一个要达标
        # 如果都不达标，则认为是稳态区域
        if pv_range < min_pv_range and pv_std < min_pv_std:
            return 0.0, False
        
        # 额外检查：PV动态变化率（相对于MV）应该足够
        # 对于大的MV变化，PV也应该有相应的变化
        # 典型过程增益K一般在0.01-10之间
        if mv_range > 10 and pv_dynamic_ratio < 0.05:
            # MV变化很大但PV几乎不变，说明是稳态区域
            return 0.0, False
        
        # ========== 1. PV变化幅度评分 ==========
        pv_change = pv[-1] - pv[0]  # 净变化
        
        # PV变化应该与MV阶跃成比例
        if abs(pv_change) > abs(step_size) * 0.1:
            scores.append(1.0)
        elif abs(pv_change) > 0.5:
            scores.append(0.7)
        elif pv_range > min_pv_range:
            # 虽然净变化小，但有动态过程
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
        if abs(pv_trend) > pv_range * 0.1:
            scores.append(1.0)
        elif abs(pv_trend) > pv_range * 0.05:
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
            # 但也要确保前期有变化（不是整个都稳定）
            if std_first > self._epsilon:
                settling_ratio = std_last / std_first
                if settling_ratio < 0.5 and std_first > min_pv_std:
                    # 有收敛，且前期有动态
                    scores.append(1.0)
                elif settling_ratio < 1.0:
                    scores.append(0.7)
                else:
                    scores.append(0.4)
            else:
                # 前期标准差太小，可能是稳态
                if std_last < min_pv_std:
                    # 整段都很稳定，不是好的整定段
                    scores.append(0.2)
                else:
                    scores.append(0.5)
        
        # ========== 4. 振荡比 ==========
        pv_diff = np.diff(pv)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        osc_ratio = sign_changes / (n - 2) if n > 2 else 0
        
        if osc_ratio < 0.2:
            scores.append(1.0)
        elif osc_ratio < 0.4:
            scores.append(0.7)
        else:
            scores.append(0.3)
        
        # ========== 5. MV-PV相关性 ==========
        try:
            corr = np.corrcoef(mv, pv)[0, 1]
            if np.isnan(corr):
                corr = 0
            if abs(corr) > 0.5:
                scores.append(1.0)
            elif abs(corr) > 0.2:
                scores.append(0.7)
            else:
                scores.append(0.4)
        except:
            scores.append(0.5)
        
        # ========== 6. 阶跃响应形态检测 ==========
        # 典型阶跃响应：初期变化快，后期趋于稳定
        # 计算前半段和后半段的变化率
        if n > 10:
            first_half_change = abs(pv[n//2] - pv[0])
            second_half_change = abs(pv[-1] - pv[n//2])
            total_change = first_half_change + second_half_change + self._epsilon
            
            # 理想情况：前半段变化占主导
            front_ratio = first_half_change / total_change
            if front_ratio > 0.6:
                scores.append(1.0)
            elif front_ratio > 0.4:
                scores.append(0.7)
            else:
                scores.append(0.5)
        
        # ========== 综合评分 ==========
        quality_score = np.mean(scores) if scores else 0.0
        
        # 判定条件：
        # 1. 质量评分 >= 0.6
        # 2. 振荡比 < 0.5
        # 3. PV动态变化足够（已在前面检查）
        is_good_response = quality_score >= 0.6 and osc_ratio < 0.5
        
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
            valid_mask = seg.pv != 0
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
            is_steady = (oscillation_ratio < 0.3 and 
                        settling_quality > 0.5 and 
                        r2 > 0.4)
            
            self.log(f"      稳态分析: 振荡={oscillation_ratio:.2f}, "
                    f"收敛={settling_quality:.2f}, 评分={stability_score:.2f}, "
                    f"稳态={is_steady}")
            
            return stability_score, oscillation_ratio, settling_quality, is_steady
            
        except Exception as e:
            self.log(f"      稳态分析失败: {e}")
            return 1.0, 0.0, 1.0, True
