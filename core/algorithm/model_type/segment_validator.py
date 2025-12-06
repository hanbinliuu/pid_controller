"""扰动段验证模块 - 数据段有效性检查和提取"""

import numpy as np
from typing import List, Tuple, Optional, Any
from dataclasses import dataclass

from .config import Config
from .utils import TimestampParser, DataValidator


@dataclass
class HistoricalData:
    """历史数据"""
    timestamp: np.ndarray
    pv: np.ndarray
    sv: np.ndarray
    mv: np.ndarray
    
    @classmethod
    def from_json(cls, data: List[dict]) -> 'HistoricalData':
        """从JSON数据创建"""
        if not data:
            raise ValueError("输入数据为空")
        timestamps = np.array([item.get('timestamp', 0) for item in data], dtype=np.float64)
        pvs = np.array([item.get('pv', 0.0) for item in data], dtype=np.float64)
        svs = np.array([item.get('sv', 0.0) for item in data], dtype=np.float64)
        mvs = np.array([item.get('mv', 0.0) for item in data], dtype=np.float64)
        return cls(timestamp=timestamps, pv=pvs, sv=svs, mv=mvs)
    
    def __len__(self) -> int:
        return len(self.pv)


@dataclass
class TuningWindow:
    """整定窗口"""
    start_time: Any
    end_time: Any


@dataclass 
class SegmentValidation:
    """段验证结果"""
    segment_idx: int
    start_idx: int
    end_idx: int
    data_points: int
    is_valid: bool
    invalid_reason: str = ""
    
    # 有效数据（过滤后）
    y: np.ndarray = None
    u: np.ndarray = None
    t: np.ndarray = None
    y0: float = 0.0


class SegmentValidator:
    """
    扰动段验证器
    
    功能：
    1. 从历史数据中提取扰动段
    2. 验证段的有效性
    3. 过滤无效段
    """
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
    
    def log(self, msg: str):
        if self._verbose:
            print(msg)
    
    def extract_segments(self, hist_data: HistoricalData,
                          windows: List[TuningWindow]) -> List[HistoricalData]:
        """
        从历史数据中提取扰动段
        
        Args:
            hist_data: 完整历史数据
            windows: 整定窗口列表
        
        Returns:
            扰动段数据列表
        """
        segments = []
        timestamps = hist_data.timestamp
        
        for i, w in enumerate(windows):
            start_ts = TimestampParser.parse(w.start_time)
            end_ts = TimestampParser.parse(w.end_time)
            
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
    
    def validate_segments(self, segments: List[HistoricalData]
                          ) -> Tuple[List[HistoricalData], List[SegmentValidation]]:
        """
        验证并过滤无效扰动段
        
        无效条件：
        1. 数据点过少 (< 20)
        2. PV变化过小（无响应）
        3. MV变化过小（无激励）
        4. PV=0 异常点过多
        5. 数据趋势不合理（非阶跃响应特征）
        
        Returns:
            (有效段列表, 验证结果列表)
        """
        self.log(f"\n{'='*60}")
        self.log("📊 扰动段有效性检查")
        self.log('='*60)
        
        valid_segments = []
        validations = []
        
        for i, seg in enumerate(segments):
            validation = self._validate_single_segment(seg, i)
            validations.append(validation)
            
            if validation.is_valid:
                valid_segments.append(seg)
        
        self.log(f"\n   有效段: {len(valid_segments)}/{len(segments)}")
        return valid_segments, validations
    
    def _validate_single_segment(self, seg: HistoricalData, 
                                  idx: int) -> SegmentValidation:
        """验证单个扰动段"""
        result = SegmentValidation(
            segment_idx=idx,
            start_idx=0,
            end_idx=len(seg),
            data_points=len(seg),
            is_valid=True
        )
        
        # 检查1: 数据点数
        if len(seg) < Config.MIN_DATA_POINTS:
            result.is_valid = False
            result.invalid_reason = f"数据点不足({len(seg)}<{Config.MIN_DATA_POINTS})"
            self.log(f"   段{idx+1}: ✗ {result.invalid_reason}")
            return result
        
        # 过滤PV=0的点
        valid_mask = seg.pv != 0
        valid_count = np.sum(valid_mask)
        
        if valid_count < Config.MIN_DATA_POINTS:
            result.is_valid = False
            result.invalid_reason = f"有效点不足({valid_count}<{Config.MIN_DATA_POINTS})"
            self.log(f"   段{idx+1}: ✗ {result.invalid_reason}")
            return result
        
        y, u = seg.pv[valid_mask], seg.mv[valid_mask]
        
        # 检查2&3: 使用DataValidator
        is_valid, reason = DataValidator.check_data_validity(y, u)
        if not is_valid:
            result.is_valid = False
            result.invalid_reason = reason
            self.log(f"   段{idx+1}: ✗ {result.invalid_reason}")
            return result
        
        # 检查4: 阶跃响应形状特征
        is_valid, reason = DataValidator.check_step_response_shape(y, u)
        if not is_valid:
            result.is_valid = False
            result.invalid_reason = reason
            self.log(f"   段{idx+1}: ✗ {result.invalid_reason}")
            return result
        
        # 有效段 - 保存处理后的数据
        result.data_points = valid_count
        result.y = y
        result.u = u
        result.t = np.arange(len(y), dtype=float)
        result.y0 = y[0]
        
        pv_range, mv_range = np.ptp(y), np.ptp(u)
        self.log(f"   段{idx+1}: ✓ 有效 ({valid_count}点, PV范围={pv_range:.2f}, MV范围={mv_range:.2f})")
        
        return result
    
    def get_valid_data(self, seg: HistoricalData) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        获取过滤后的有效数据
        
        Returns:
            (y, u, t) - PV、MV、时间数组
        """
        valid_mask = seg.pv != 0
        y = seg.pv[valid_mask]
        u = seg.mv[valid_mask]
        t = np.arange(len(y), dtype=float)
        return y, u, t
