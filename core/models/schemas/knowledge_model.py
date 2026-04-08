"""
知识图谱专家经验 (Knowledge Graph Model)
========================================

存放人类专家对特定设备/回路类型的 "整定策略"、"容错容限"、"安全规则" 与历史案例库。
这也是在引导大模型（LLM）行为时最重要的 Prompt 防线。

字段来源
--------
- pid_constraints, tuning_strategy, quality_thresholds 三个 JSON 块
- 与 loop_presets.py 的字段一一对应，已验证数值一致

对照表（JSON 字段 → KnowledgeModel 字段 → loop_presets.py 对应项）：

| JSON 路径                       | KnowledgeModel 属性        | loop_presets 键      |
|--------------------------------|---------------------------|---------------------|
| pid_constraints.pb_min         | pb_range[0]              | pb_min              |
| pid_constraints.pb_max         | pb_range[1]              | pb_max              |
| pid_constraints.td_enable      | td_enable                | td_enable           |
| pid_constraints.td_ratio       | td_ratio                 | td_ratio            |
| pid_constraints.td_max         | td_max                   | td_max              |
| pid_constraints.ti_max         | ti_max                   | ti_max              |
| pid_constraints.aggressive     | → tuning_strategy 映射    | aggressive          |
| tuning_strategy.tau_c_factor   | tau_c_factor             | tau_c_factor        |
| tuning_strategy.safety_factor  | safety_factor            | safety_factor       |
| tuning_strategy.ti_multiplier  | ti_multiplier            | ti_multiplier       |
| quality_thresholds.max_overshoot | max_overshoot_percent  | (无直接对应)         |
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List


@dataclass
class KnowledgeModel:
    """
    知识图谱专家经验 — 人类工程师控制经验的结构化表达
    """
    
    # ================================================================
    # PID 参数约束（对应 pid_constraints）
    # ================================================================
    
    td_enable: bool = True
    """是否允许开启微分项（液位回路经验一律关闭）"""
    
    td_ratio: float = 0.0
    """微分时间与积分时间的比例（Td = Ti * td_ratio），0 = 不用微分"""
    
    td_max: float = 0.0
    """微分时间上限（秒），0 = 无限制"""
    
    max_overshoot_percent: float = 10.0
    """最大容忍超调限制（%）"""
    
    gain_range: List[float] = field(default_factory=lambda: [0.1, 10.0])
    """算法增益合理范围 [K_min, K_max]"""
    
    pb_range: List[float] = field(default_factory=lambda: [10.0, 500.0])
    """比例带安全范围 [PB_min, PB_max]（现场 DCS 安全限制）"""
    
    ti_max: float = 60.0
    """积分时间上限（秒），超大积分时间不合理"""
    
    # ================================================================
    # 整定策略参数（对应 tuning_strategy）
    # ================================================================
    
    tuning_strategy: str = "balanced"
    """整定风格：aggressive / balanced / conservative"""
    
    tau_c_factor: float = 1.5
    """λ 调节系数：控制闭环响应速度，越大越保守"""
    
    safety_factor: float = 1.05
    """安全余量系数：对计算得到的 PB 施加的乘数"""
    
    ti_multiplier: float = 1.0
    """积分时间乘数：对计算得到的 Ti 施加的乘数"""
    
    integrating_mode: bool = False
    """是否为积分过程整定模式（液位回路专属）"""
    
    # ================================================================
    # 质量阈值（对应 quality_thresholds）
    # ================================================================
    
    settling_time_factor: float = 3.0
    """整定时间因子：用于评分时对调节时间的加权"""
    
    overshoot_discount: float = 1.0
    """超调折扣：用于评分时对超调的折扣系数（液位回路 2.5，流量 1.0）"""
    
    oscillation_tolerance: float = 0.2
    """振荡容忍度：评估是否"稳定"的振荡阈值"""
    
    # ================================================================
    # 历史知识与案例参考
    # ================================================================
    
    historical_best_kp: float = 0.0
    """历史最佳 Kp（供算法初始化参考）"""
    
    expert_notes: str = ""
    """专家经验提示录（可供大模型 Prompt 使用）"""
    
    # ================================================================
    # 序列化
    # ================================================================
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeModel':
        return cls(
            td_enable=data.get('td_enable', True),
            td_ratio=data.get('td_ratio', 0.0),
            td_max=data.get('td_max', 0.0),
            max_overshoot_percent=data.get('max_overshoot_percent', 10.0),
            gain_range=data.get('gain_range', [0.1, 10.0]),
            pb_range=data.get('pb_range', [10.0, 500.0]),
            ti_max=data.get('ti_max', 60.0),
            tuning_strategy=data.get('tuning_strategy', 'balanced'),
            tau_c_factor=data.get('tau_c_factor', 1.5),
            safety_factor=data.get('safety_factor', 1.05),
            ti_multiplier=data.get('ti_multiplier', 1.0),
            integrating_mode=data.get('integrating_mode', False),
            settling_time_factor=data.get('settling_time_factor', 3.0),
            overshoot_discount=data.get('overshoot_discount', 1.0),
            oscillation_tolerance=data.get('oscillation_tolerance', 0.2),
            historical_best_kp=data.get('historical_best_kp', 0.0),
            expert_notes=data.get('expert_notes', ''),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)
