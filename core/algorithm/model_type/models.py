"""数据模型定义模块"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class SegmentResult:
    """单个扰动段的拟合结果"""
    segment_idx: int                    # 段索引
    start_idx: int                      # 起始索引
    end_idx: int                        # 结束索引
    data_points: int                    # 数据点数
    is_valid: bool                      # 是否有效
    invalid_reason: str = ""            # 无效原因
    
    # 各模型的拟合结果
    model_results: Dict[str, Dict] = field(default_factory=dict)
    # 格式: {model_type: {K, T1, T2, L, r2, rss, aic, bic, params_raw}}
    
    # 最佳模型（该段）
    best_model: str = ""
    best_r2: float = 0.0
    best_aic: float = float('inf')
    
    # 数据质量指标
    quality_score: float = 0.0          # 综合质量评分
    nonlinearity_score: float = 0.0     # 非线性程度
    step_response_score: float = 0.0    # 阶跃响应特征评分
    oscillation_ratio: float = 0.0      # 振荡比例
    is_nonlinear: bool = False          # 是否为非线性


@dataclass
class FusionResult:
    """参数融合结果"""
    model_type: str                     # 最终模型类型
    K: float = 0.0
    T1: float = 0.0
    T2: float = 0.0
    L: float = 0.0
    
    # 融合统计
    fusion_method: str = ""             # 融合方法
    n_segments_used: int = 0            # 使用的段数
    segment_weights: List[float] = field(default_factory=list)
    
    # 一致性评估
    K_std: float = 0.0                  # K的标准差
    T1_std: float = 0.0                 # T1的标准差
    consistency_score: float = 0.0      # 一致性评分 (0-1)
    
    # 验证结果（基于扰动段）
    global_r2: float = 0.0              # 扰动段综合R²（用于评分和输出）
    global_rmse: float = 0.0            # 扰动段综合RMSE
    full_data_r2: float = 0.0           # 全量数据R²（仅供参考）


@dataclass
class TuningWindow:
    """整定窗口"""
    start_time: Any
    end_time: Any


@dataclass
class TuningInput:
    """整定输入"""
    start_time: Any
    end_time: Any
    tuning_window: Optional[List[TuningWindow]] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TuningInput':
        windows = data.get('tuning_window', [])
        tuning_window = [
            TuningWindow(start_time=w.get('start_time'), end_time=w.get('end_time'))
            for w in windows
        ] if windows else None
        return cls(
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            tuning_window=tuning_window
        )


@dataclass
class HistoricalData:
    """历史数据"""
    timestamp: np.ndarray
    pv: np.ndarray
    sv: np.ndarray
    mv: np.ndarray
    
    @classmethod
    def from_json(cls, data: List[Dict]) -> 'HistoricalData':
        if not data:
            raise ValueError("输入数据为空")
        timestamps = np.array([item.get('timestamp', 0) for item in data], dtype=np.float64)
        pvs = np.array([item.get('pv', 0.0) for item in data], dtype=np.float64)
        svs = np.array([item.get('sv', 0.0) for item in data], dtype=np.float64)
        mvs = np.array([item.get('mv', 0.0) for item in data], dtype=np.float64)
        return cls(timestamp=timestamps, pv=pvs, sv=svs, mv=mvs)
    
    def __len__(self) -> int:
        return len(self.pv)
