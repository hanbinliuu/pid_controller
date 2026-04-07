"""
实际过程模型 (Instance Process Model)
=====================================

某个具体设备回路的实例化参数。
包含物理参数、阀门特性、DCS配置、运行约束等实际工程数据。
未来这些数据将通过 OS 本体模型/台账 API 获取。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class PhysicalParams:
    """工艺物理参数"""
    tank_volume_m3: Optional[float] = None          # 罐体有效容积 (仅液位有效)
    tank_cross_section_m2: Optional[float] = None   # 罐体横截面积 (仅液位有效)
    pv_range_min: float = 0.0                       # 量程下限 (工程单位)
    pv_range_max: float = 100.0                     # 量程上限 (工程单位)
    engineering_unit: str = '%'                     # 工程单位
    nominal_flow_rate: Optional[float] = None       # 额定流量


@dataclass
class ValveParams:
    """执行机构(阀门/泵)特性"""
    cv_max: Optional[float] = None                  # 最大流量系数
    characteristic: str = 'linear'                  # 'linear' | 'equal_percent' | 'quick_open'
    action_type: str = 'air_to_close'               # 'air_to_close' (气关/FO) | 'air_to_open' (气开/FC)
    deadband_percent: float = 0.0                   # 阀门死区 (%)
    time_constant_s: float = 1.0                    # 执行机构时间常数 (秒)


@dataclass
class DCSConfig:
    """DCS 控制器配置参数"""
    control_mode: str = 'PID'                       # 控制模式
    scan_interval_ms: int = 1000                    # 扫描/控制周期 (毫秒)
    action: str = 'reverse'                         # PID正反作用: 'direct' | 'reverse'
    
    # 当前在用 PID 参数
    current_kp: Optional[float] = None
    current_ti: Optional[float] = None
    current_td: Optional[float] = None
    current_pb: Optional[float] = None
    
    # DCS 配置的物理界限
    pb_min_limit: float = 10.0
    pb_max_limit: float = 999.0
    ti_min_limit: float = 0.1
    ti_max_limit: float = 9999.0


@dataclass
class OperatingConstraints:
    """工艺运行边界/安全约束"""
    max_overshoot_percent: Optional[float] = None   # 强制最大超调限制
    max_settling_time_s: Optional[float] = None     # 强制最大调节时间限制
    
    # 报警/联锁值 (工程单位)
    alarm_high: Optional[float] = None
    alarm_high_high: Optional[float] = None
    alarm_low: Optional[float] = None
    alarm_low_low: Optional[float] = None


@dataclass
class IdentificationHistory:
    """历史辨识记录 (Agent 侧维护)"""
    tuning_count: int = 0                           # 历史整定次数
    last_tuning_time: Optional[str] = None          # 格式: 'YYYY-MM-DDTHH:MM:SS'
    best_model_type: Optional[str] = None           # 历史上最成功的模型
    best_score: float = 0.0
    
    # 历史上最佳的 PID 参数
    best_kp: Optional[float] = None
    best_ti: Optional[float] = None
    best_td: Optional[float] = None
    best_pb: Optional[float] = None


@dataclass
class InstanceProcessModel:
    """
    实际过程模型 — 某个具体回路的实例参数集
    """
    device_id: str                          # 唯一标识，如 '2216_LIC_50104'
    tag_name: str                           # 点名，如 'LIC-50104'
    standard_model_ref: str                 # 关联的标准模型类型，如 'level'
    
    plant: str = ''                         # 厂区 (如 '大榭')
    unit: str = ''                          # 装置 (如 '2216装置')
    
    physical_params: PhysicalParams = field(default_factory=PhysicalParams)
    valve_params: ValveParams = field(default_factory=ValveParams)
    dcs_config: DCSConfig = field(default_factory=DCSConfig)
    operating_constraints: OperatingConstraints = field(default_factory=OperatingConstraints)
    history: IdentificationHistory = field(default_factory=IdentificationHistory)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstanceProcessModel':
        """从字典构建实例模型"""
        return cls(
            device_id=data['device_id'],
            tag_name=data['tag_name'],
            standard_model_ref=data['standard_model_ref'],
            plant=data.get('plant', ''),
            unit=data.get('unit', ''),
            physical_params=PhysicalParams(**data.get('physical_params', {})),
            valve_params=ValveParams(**data.get('valve_params', {})),
            dcs_config=DCSConfig(**data.get('dcs_config', {})),
            operating_constraints=OperatingConstraints(**data.get('operating_constraints', {})),
            history=IdentificationHistory(**data.get('history', {})),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        from dataclasses import asdict
        return asdict(self)
