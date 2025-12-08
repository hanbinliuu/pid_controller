"""段处理模块 - 段提取、过滤和有效性检查"""

import numpy as np
from typing import List, Tuple

from .config import Config
from .models import SegmentResult, HistoricalData, TuningWindow
from .data_preprocessor import DataPreprocessor
from .utils import parse_timestamp


class SegmentProcessor:
    """段处理器 - 负责段提取、过滤和有效性检查"""
    
    # 验证阈值常量
    MIN_DATA_POINTS = 20          # 最小数据点数
    MIN_PV_RANGE = 0.5            # 最小PV变化范围
    MIN_MV_RANGE = 0.1            # 最小MV变化范围
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(verbose=verbose)
    
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
            
            # 检查1: 数据点数
            if len(seg) < self.MIN_DATA_POINTS:
                self._mark_invalid(result, f"数据点不足({len(seg)}<{self.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            # 过滤PV=0的点
            valid_mask = seg.pv != 0
            valid_count = np.sum(valid_mask)
            
            if valid_count < self.MIN_DATA_POINTS:
                self._mark_invalid(result, f"有效点不足({valid_count}<{self.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            y, u = seg.pv[valid_mask], seg.mv[valid_mask]
            pv_range, mv_range = np.ptp(y), np.ptp(u)
            
            # 检查2: PV变化
            if pv_range < self.MIN_PV_RANGE and np.std(y) < 0.1:
                self._mark_invalid(result, f"PV无变化(range={pv_range:.2f})", i, segment_results)
                continue
            
            # 检查3: MV变化
            if mv_range < self.MIN_MV_RANGE:
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
            if quality.nonlinearity_score > 0.7 and quality.step_response_score < 0.3:
                self._mark_invalid(result, f"严重非线性(非线性={quality.nonlinearity_score:.2f}, 阶跃特征={quality.step_response_score:.2f})", i, segment_results)
                continue
            
            # 检查7: 严重振荡过滤（放宽阈值：振荡>0.75 且 质量分<0.25）
            if quality.oscillation_ratio > 0.75 and quality.quality_score < 0.25:
                self._mark_invalid(result, f"严重振荡(振荡={quality.oscillation_ratio:.2f}, 质量分={quality.quality_score:.2f})", i, segment_results)
                continue
            
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
        
        Returns:
            (is_valid, reason)
        """
        n = len(y)
        if n < 20:
            return False, "数据太短"
        
        # 计算相关系数
        try:
            corr = np.corrcoef(u, y)[0, 1]
            if np.isnan(corr):
                corr = 0.0
        except:
            corr = 0.0
        
        # 允许正相关或负相关（正向/反向作用系统）
        if abs(corr) < 0.1:
            # 检查是否是积分过程（累积效应）
            y_cumsum = np.cumsum(u - np.mean(u))
            try:
                corr_cumsum = np.corrcoef(y_cumsum, y)[0, 1]
                if np.isnan(corr_cumsum):
                    corr_cumsum = 0.0
            except:
                corr_cumsum = 0.0
            
            if abs(corr_cumsum) < 0.2:
                return False, f"无明显响应(corr={corr:.2f})"
        
        return True, ""
    
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
