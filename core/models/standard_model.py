"""
标准过程模型 (Standard Process Model)
=====================================

按回路类型定义的通用工艺模板，将当前散落在 config/ 目录下多个文件中的
硬编码工艺知识统一抽象为结构化的标准模型。

每种回路类型（液位、流量、温度、压力）对应一个标准模型 JSON 文件，
包含该类型回路的：
- 机理模型结构偏好与约束
- PID 参数允许范围
- 整定策略参数
- 数据质量与性能评判标准
- 仿真配置
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ModelStructure:
    """机理模型结构偏好"""
    preferred: str                          # 优选模型类型，如 'FO_INTEGRATOR'
    fallback: List[str] = field(default_factory=list)  # 备选模型类型
    tuning_method_priority: List[str] = field(default_factory=list)  # 整定方法优先级
    force_model: bool = False               # 是否强制使用优选模型（如液位强制积分器）


@dataclass
class GainRange:
    """过程增益合理范围"""
    K_min: float = 0.01
    K_max: float = 200.0
    K_int_min: float = 0.0001              # 积分增益下限（仅积分过程）
    K_int_max: float = 1.0                 # 积分增益上限


@dataclass
class TimeConstants:
    """时间常数特征"""
    T1_range: List[float] = field(default_factory=lambda: [1.0, 500.0])
    L_range: List[float] = field(default_factory=lambda: [0.0, 50.0])
    response_speed: str = 'medium'         # 'fast' | 'medium' | 'slow'


@dataclass
class PIDConstraints:
    """PID 参数约束"""
    pb_min: float = 40.0
    pb_max: float = 300.0
    ti_max: float = 600.0
    td_enable: bool = False
    td_ratio: float = 0.0                 # Td = Ti * td_ratio
    td_max: float = 0.0
    aggressive: bool = False


@dataclass
class TuningStrategy:
    """整定策略参数"""
    tau_c_factor: float = 1.5              # Lambda / 闭环时间常数系数
    safety_factor: float = 1.0             # 安全系数
    ti_multiplier: float = 1.0             # Ti 放大系数
    integrating_mode: bool = False         # 是否按积分过程整定
    lambda_default: float = 50.0           # 默认 Lambda 值（秒）


@dataclass
class QualityThresholds:
    """性能评判标准"""
    max_overshoot: float = 35.0            # 允许最大超调 (%)
    settling_time_factor: float = 1.0      # 调节时间评判放宽倍数
    overshoot_discount: float = 1.0        # 超调折算系数（发给评分模块前先缩放）
    oscillation_tolerance: float = 0.3     # 振荡比容忍度
    min_data_quality: float = 0.4          # 最低数据质量要求


@dataclass
class SimulationConfig:
    """仿真参数配置"""
    sim_duration_factor: float = 6.0       # 仿真时长 = 因子 × T1
    max_sim_duration: float = 1200.0       # 最大仿真时长（秒）
    sp_step: float = 10.0                  # 设定值阶跃幅度


@dataclass
class StandardProcessModel:
    """
    标准过程模型 — 某一类回路的通用工艺模板
    
    汇聚了当前散落在以下配置文件中的知识:
    - config/loop_presets.py      → pid_constraints, tuning_strategy
    - config/oscillation.py      → tuning_strategy, simulation
    - config/model_bounds.py     → gain_range, time_constants
    - config/loop_type_inferrer.py → model_structure
    - oscillation_tuner.py       → quality_thresholds
    """
    # 基本信息
    loop_type: str                         # 'level' | 'flow' | 'temperature' | 'pressure'
    process_nature: str                    # 'integrating' | 'self_regulating'
    description: str = ''
    
    # 各维度约束
    model_structure: ModelStructure = field(default_factory=ModelStructure)
    gain_range: GainRange = field(default_factory=GainRange)
    time_constants: TimeConstants = field(default_factory=TimeConstants)
    pid_constraints: PIDConstraints = field(default_factory=PIDConstraints)
    tuning_strategy: TuningStrategy = field(default_factory=TuningStrategy)
    quality_thresholds: QualityThresholds = field(default_factory=QualityThresholds)
    simulation: SimulationConfig = field(default_factory=SimulationConfig)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StandardProcessModel':
        """从字典（JSON 解析结果）构建标准模型"""
        return cls(
            loop_type=data['loop_type'],
            process_nature=data['process_nature'],
            description=data.get('description', ''),
            model_structure=ModelStructure(**data.get('model_structure', {})),
            gain_range=GainRange(**data.get('gain_range', {})),
            time_constants=TimeConstants(**data.get('time_constants', {})),
            pid_constraints=PIDConstraints(**data.get('pid_constraints', {})),
            tuning_strategy=TuningStrategy(**data.get('tuning_strategy', {})),
            quality_thresholds=QualityThresholds(**data.get('quality_thresholds', {})),
            simulation=SimulationConfig(**data.get('simulation', {})),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        from dataclasses import asdict
        return asdict(self)
    
    def get_pb_range(self) -> tuple:
        """获取 PB 范围"""
        return (self.pid_constraints.pb_min, self.pid_constraints.pb_max)
    
    def is_integrating(self) -> bool:
        """是否为积分过程"""
        return self.process_nature == 'integrating'
