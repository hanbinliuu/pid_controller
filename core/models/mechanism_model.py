from dataclasses import dataclass, field
from typing import Dict, Any

@dataclass
class MechanismModel:
    """
    机理模型 (Mechanism Model)
    --------------------------
    根据设备的物理机理，推导出的控制回路本质特征与界限。
    它决定了仿真模型的底座定性（例如系统是不是积分器？有没有严重的物料耦合迟滞？）。
    （这是对客观物理世界的仿真抽象，绝不包含“人类控制经验”）
    """
    # 物理机理定性
    process_nature: str = "self_regulating"  # self_regulating (自衡) / integrating (积分)
    dead_time_dominant: bool = False         # 是否为大纯滞后系统
    
    # 机理推导界限
    natural_frequency_s: float = 0.0         # 系统的自然振荡周期预估 (秒)
    process_gain_sign: int = 1               # 固有的正反作用符号 (+1 / -1)
    
    # 仿真模型类型偏好
    preferred_simulation_model: str = "FOPDT" # 适合的机理仿真结构 (FOPDT / FO_INTEGRATOR)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MechanismModel':
        return cls(
            process_nature=data.get('process_nature', 'self_regulating'),
            dead_time_dominant=data.get('dead_time_dominant', False),
            natural_frequency_s=data.get('natural_frequency_s', 0.0),
            process_gain_sign=data.get('process_gain_sign', 1),
            preferred_simulation_model=data.get('preferred_simulation_model', 'FOPDT')
        )
