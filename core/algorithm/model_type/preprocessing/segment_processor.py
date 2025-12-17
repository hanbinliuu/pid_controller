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
