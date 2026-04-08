from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class MetricsModel:
    """
    指标模型 (Metrics Model)
    -----------------------
    基于时序曲线客观运算出的 KPI 绩效指标。
    """
    device_id: str
    auto_control_rate: float = 0.0           # 自控率 (0-1)
    steady_state_rate: float = 0.0           # 稳态率 (0-1)
    
    mse_score: float = 0.0                   # 近期闭环跟踪均方误差
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MetricsModel':
        return cls(
            device_id=data.get('device_id', 'unknown'),
            auto_control_rate=data.get('auto_control_rate', 0.0),
            steady_state_rate=data.get('steady_state_rate', 0.0),
            mse_score=data.get('mse_score', 0.0)
        )
