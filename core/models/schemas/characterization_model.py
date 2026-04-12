"""
表征模型 (Characterization Model)
=====================================

OS 层面对于设备运行状况的动态评估数据。
采用“按需计算（On-Demand）”架构设计：当用户在前台触发“一键整定”时，
OS 中台会立即拉取该回路近日波形，实时运行诊断算法并提取相关特征。
它表征了回路的健康状态、非线性特征、干扰频次等即时的客观数据。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any


@dataclass
class SignalCharacteristics:
    """过程信号特征"""
    oscillation_ratio: float = 0.0          # 近期振荡时间占比 (0-1)
    dominant_period_s: float = 0.0          # 主振荡周期 (秒)
    noise_level: float = 0.0                # 高频噪声强度占比 (0-1)
    linearity_index: float = 1.0            # 线性度指标，越接近1越线性


@dataclass
class ValveCharacteristics:
    """阀门执行机构表征 (预测/评估值)"""
    stiction_index_estimated: float = 0.0   # 预测阀门卡涩/粘滞指数 (0-1)
    deadband_estimated: float = 0.0         # 预测阀门死区 (%)
    reversal_error: float = 0.0             # 回程误差


@dataclass
class ControlPerformance:
    """近期控制绩效"""
    performance_score_avg: float = 10.0     # 综合控制评分平均值 (例如 0-10)
    auto_mode_time_ratio: float = 1.0       # 自动模式占比 (0-1)
    intervention_count_daily: int = 0       # 日均人工干预/动作切手动次数
    recent_step_events: int = 0             # 过去 X 小时内的有效台阶状阶跃次数


@dataclass
class CharacterizationModel:
    """
    表征模型 — OS 提供的动态时序特征快照
    """
    device_id: str                          # 设备追踪标识
    timestamp: str                          # 此表征切片的评估生成时间，ISO8601格式
    
    signal: SignalCharacteristics = field(default_factory=SignalCharacteristics)
    valve: ValveCharacteristics = field(default_factory=ValveCharacteristics)
    performance: ControlPerformance = field(default_factory=ControlPerformance)
    
    # [新增] 大模型专属拓展字段插槽
    llm_extra_features: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CharacterizationModel':
        """从字典构建表征模型"""
        return cls(
            device_id=data['device_id'],
            timestamp=data['timestamp'],
            signal=SignalCharacteristics(**data.get('signal', {})),
            valve=ValveCharacteristics(**data.get('valve', {})),
            performance=ControlPerformance(**data.get('performance', {})),
            llm_extra_features=data.get('llm_extra_features', {}),
        )
        
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        from dataclasses import asdict
        return asdict(self)
