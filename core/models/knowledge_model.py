from dataclasses import dataclass, field
from typing import Dict, Any, List

@dataclass
class KnowledgeModel:
    """
    知识图谱专家经验 (Knowledge Graph Model)
    --------------------------------------
    存放人类专家对特定设备的“整定策略”、“容错容限”、“安全规则”与历史案例库。
    这也是在引导大模型（LLM）行为时最重要的 Prompt 防线。
    """
    # === PID 特定控制图谱 ===
    td_enable: bool = True               # 经验：是否允许开启微分 (如液位经验一律关闭)
    max_overshoot_percent: float = 10.0  # 安全：最大容忍超调限制
    gain_range: List[float] = field(default_factory=lambda: [0.1, 10.0]) # 限制：算法增益容限
    pb_range: List[float] = field(default_factory=lambda: [10.0, 500.0]) # 现场安全限制：比例带下上界
    
    # === 专家策略倾向 ===
    tuning_strategy: str = "balanced"    # aggresive / balanced / conservative
    
    # === 历史知识与案例参考 ===
    historical_best_kp: float = 0.0
    expert_notes: str = ""               # 经验提示录
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeModel':
        return cls(
            td_enable=data.get('td_enable', True),
            max_overshoot_percent=data.get('max_overshoot_percent', 10.0),
            gain_range=data.get('gain_range', [0.1, 10.0]),
            pb_range=data.get('pb_range', [10.0, 500.0]),
            tuning_strategy=data.get('tuning_strategy', 'balanced'),
            historical_best_kp=data.get('historical_best_kp', 0.0),
            expert_notes=data.get('expert_notes', '')
        )
