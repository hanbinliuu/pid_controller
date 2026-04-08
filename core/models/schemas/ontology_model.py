from dataclasses import dataclass, field
from typing import Dict, Any, Optional

@dataclass
class OntologyModel:
    """
    本体模型 (Ontology Model)
    -----------------------
    定义回路、设备、工艺之间的物理本体关系。
    映射物理世界中的客观实体（容器容量、管道截面积、阀体额定流量等）。
    """
    device_id: str                      # 设备编号 (e.g. 2216_LIC_50104)
    device_type: str = "undefined"      # 对象类型 (e.g. tank, pipe, reactor)
    loop_type: str = "default"          # 回路类型 (flow, level, temperature, pressure)
    
    # === 关键容器/管线本体参数 ===
    tank_volume_m3: Optional[float] = None
    tank_cross_section_m2: Optional[float] = None
    
    # === 执行机构本体 ===
    valve_cv_max: Optional[float] = None
    valve_type: str = "unknown"
    
    # 扩展槽
    extra_attributes: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OntologyModel':
        return cls(
            device_id=data.get('device_id', 'unknown'),
            device_type=data.get('device_type', 'undefined'),
            loop_type=data.get('loop_type', 'default'),
            tank_volume_m3=data.get('tank_volume_m3'),
            tank_cross_section_m2=data.get('tank_cross_section_m2'),
            valve_cv_max=data.get('valve_cv_max'),
            valve_type=data.get('valve_type', 'unknown'),
            extra_attributes=data.get('extra_attributes', {})
        )
