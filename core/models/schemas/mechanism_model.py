"""
机理模型 (Mechanism Model)
==========================

根据设备的物理机理，推导出控制回路三层核心属性：
  1. 物理规则  —— 过程的定性物理特征（自衡/积分，增益符号，耦合风险）
  2. 仿真模拟  —— 适合的数学模型结构及参数量程约束
  3. 对象/约束建模 —— 物理边界与守恒定律约束

这是对客观物理世界的仿真抽象，绝不包含"人类控制经验"。
人类控制经验（整定约束、策略偏好）属于 KnowledgeModel 的职责。

四大回路的机理摘要
------------------
| 回路   | 过程性质   | 典型非线性    | 主要守恒   | 推荐模型       |
|--------|------------|--------------|------------|----------------|
| 液位   | 积分       | 阀门饱和     | 质量守恒   | FO_INTEGRATOR  |
| 流量   | 自衡（快）  | 阀门非线性   | 质量守恒   | FOPDT          |
| 压力   | 自衡/积分  | 管道耦合     | 质量守恒   | FOPDT          |
| 温度   | 自衡（慢）  | 过程非线性   | 能量守恒   | FOPDT/SOPDT    |
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class MechanismModel:
    """
    机理模型 — OS 提供的过程物理机理知识
    """

    # ================================================================
    # 一、物理规则 (Physical Rules)
    # ================================================================

    process_nature: str = "self_regulating"
    """过程性质
    - self_regulating: 自衡过程（阶跃响应后 PV 稳定在新稳态）
    - integrating:     积分过程（阶跃后 PV 持续变化，如液位）
    - unstable:        开环不稳定过程（罕见，如反应热失控）
    """

    process_gain_sign: int = 1
    """固有增益符号
    - +1: 正作用（MV↑ → PV↑，如大多数液位、温度回路）
    - -1: 反作用（MV↑ → PV↓，如冷却水温控）
    """

    dead_time_dominant: bool = False
    """是否为大纯滞后系统（Td >> T1）
    大纯滞后系统对控制器增益极为敏感，整定需格外保守。
    """

    coupling_risk: str = "none"
    """与其他回路的物理耦合风险
    - none:   无明显耦合
    - low:    弱耦合（可忽略）
    - medium: 中等耦合（需注意解耦）
    - high:   强耦合（需多变量控制或严格顺序控制）
    例：同一容器的液位与出料流量之间存在 high 耦合。
    """

    nonlinearity_type: str = "none"
    """主要的过程非线性类型
    - none:              基本线性
    - valve_saturation:  阀门饱和（高开度或低开度时增益大幅变化）
    - valve_nonlinear:   阀门固有非线性特性（等百分比阀）
    - process_nonlinear: 过程本身非线性（如反应釜浓度效应）
    - hysteresis:         迟滞（阀门卡涩 / 机械间隙）
    """

    # ================================================================
    # 二、仿真模拟 (Simulation)
    # ================================================================

    preferred_simulation_model: str = "FOPDT"
    """首选仿真结构
    - FOPDT:          一阶惯性+纯滞后（大多数回路）
    - SOPDT:          二阶惯性+纯滞后（温度、大惯性系统）
    - FO_INTEGRATOR:  一阶积分+纯滞后（液位）
    - INTEGRATOR:     纯积分（理想液位，无自衡项）
    """

    allowed_simulation_models: List[str] = field(default_factory=list)
    """允许使用的仿真模型备选列表（按优先级排序）
    若首选模型拟合质量差（R² < 0.6），算法从备选列表中依次尝试。
    """

    max_model_order: int = 2
    """允许建立的最大模型阶数
    - 流量/压力：1（快过程，高阶无必要）
    - 液位：    1（积分模型）
    - 温度：    2（允许二阶）
    """

    typical_time_constant_range_s: List[float] = field(default_factory=lambda: [0.0, 9999.0])
    """该类型回路的典型时间常数范围（秒）[T1_min, T1_max]
    用于辨识结果的合理性校验，超出此范围的辨识结果视为异常。
    """

    typical_dead_time_range_s: List[float] = field(default_factory=lambda: [0.0, 9999.0])
    """典型纯滞后范围（秒）[Td_min, Td_max]"""

    natural_frequency_s: float = 0.0
    """系统的自然振荡周期预估（秒），0 表示无先验估计"""

    # ================================================================
    # 三、对象/约束建模 (Object & Constraint Modeling)
    # ================================================================

    state_variables: List[str] = field(default_factory=list)
    """过程状态变量名称（物理量）
    例：液位 → ["liquid_level"]
         温度 → ["jacket_temp", "reactor_temp"]
    """

    mass_balance_constrained: bool = False
    """是否受质量/物料守恒约束
    液位、流量、压力回路通常为 True：
    进料 = 出料 + 储量变化，不可违反。
    """

    energy_balance_constrained: bool = False
    """是否受能量守恒约束
    温度回路为 True：
    加热量 = 散热量 + 物料升温变化能量，约束控制目标上限。
    """

    output_physical_bounds: List[float] = field(default_factory=lambda: [0.0, 100.0])
    """PV 的物理边界 [下限, 上限]（工程单位）
    - 液位：[0, 罐体高度] 或 [0.0, 100.0]（百分比）
    - 温度：[室温, 材料耐受上限]
    超出此边界代表物理不可达或触发安全联锁。
    """

    integrator_gain_range: Optional[List[float]] = None
    """积分过程的积分增益范围 [Ki_min, Ki_max]（单位：PV%/MV%/s）
    仅 process_nature == 'integrating' 时有意义。
    """

    extra_constraints: Dict[str, Any] = field(default_factory=dict)
    """其他机理约束（扩展槽）
    例：{"min_fill_ratio": 0.05, "max_fill_ratio": 0.95}
    """

    # ================================================================
    # 序列化
    # ================================================================

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MechanismModel':
        return cls(
            process_nature=data.get('process_nature', 'self_regulating'),
            process_gain_sign=data.get('process_gain_sign', 1),
            dead_time_dominant=data.get('dead_time_dominant', False),
            coupling_risk=data.get('coupling_risk', 'none'),
            nonlinearity_type=data.get('nonlinearity_type', 'none'),
            preferred_simulation_model=data.get('preferred_simulation_model', 'FOPDT'),
            allowed_simulation_models=data.get('allowed_simulation_models', []),
            max_model_order=data.get('max_model_order', 2),
            typical_time_constant_range_s=data.get('typical_time_constant_range_s', [0.0, 9999.0]),
            typical_dead_time_range_s=data.get('typical_dead_time_range_s', [0.0, 9999.0]),
            natural_frequency_s=data.get('natural_frequency_s', 0.0),
            state_variables=data.get('state_variables', []),
            mass_balance_constrained=data.get('mass_balance_constrained', False),
            energy_balance_constrained=data.get('energy_balance_constrained', False),
            output_physical_bounds=data.get('output_physical_bounds', [0.0, 100.0]),
            integrator_gain_range=data.get('integrator_gain_range'),
            extra_constraints=data.get('extra_constraints', {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    # ================================================================
    # 工厂方法：四大回路标准机理配置
    # ================================================================

    @classmethod
    def for_level(cls) -> 'MechanismModel':
        """
        液位回路机理
        - 积分过程：进料与出料差导致液位持续积分变化
        - 质量守恒：液位不可超出罐体边界
        - 阀门饱和：近全开/全关时增益剧变
        - 首选 FO_INTEGRATOR 模型
        """
        return cls(
            process_nature='integrating',
            process_gain_sign=1,
            dead_time_dominant=False,
            coupling_risk='medium',         # 液位与出料流量强关联
            nonlinearity_type='valve_saturation',
            preferred_simulation_model='FO_INTEGRATOR',
            allowed_simulation_models=['FO_INTEGRATOR', 'INTEGRATOR', 'FOPDT'],
            max_model_order=1,
            typical_time_constant_range_s=[10.0, 3600.0],   # 10s ~ 1小时
            typical_dead_time_range_s=[0.0, 120.0],
            state_variables=['liquid_level'],
            mass_balance_constrained=True,
            energy_balance_constrained=False,
            output_physical_bounds=[0.0, 100.0],
            integrator_gain_range=[0.001, 0.5],              # Ki ≈ (流量/容积)
            extra_constraints={
                'min_safe_level_pct': 5.0,   # 最低安全液位（%）
                'max_safe_level_pct': 95.0,  # 最高安全液位（%）
            }
        )

    @classmethod
    def for_flow(cls) -> 'MechanismModel':
        """
        流量回路机理
        - 自衡快过程：时间常数极小（秒级），对控制器响应极快
        - 阀门固有非线性：等百分比特性常见
        - 高频测量噪声：流量计信号通常含显著噪声
        - 首选 FOPDT 模型（一阶足够）
        """
        return cls(
            process_nature='self_regulating',
            process_gain_sign=1,
            dead_time_dominant=False,
            coupling_risk='low',
            nonlinearity_type='valve_nonlinear',
            preferred_simulation_model='FOPDT',
            allowed_simulation_models=['FOPDT'],
            max_model_order=1,
            typical_time_constant_range_s=[0.5, 30.0],      # 0.5s ~ 30s
            typical_dead_time_range_s=[0.0, 10.0],
            state_variables=['flow_rate'],
            mass_balance_constrained=True,
            energy_balance_constrained=False,
            output_physical_bounds=[0.0, 100.0],
            extra_constraints={
                'high_noise_expected': True,     # 预期高噪声，需滤波
                'control_action': 'fast',        # 快速控制
            }
        )

    @classmethod
    def for_pressure(cls) -> 'MechanismModel':
        """
        压力回路机理
        - 开放系统（管道）：自衡，时间常数中等
        - 密闭容器：近似积分过程
        - 管道系统：可能与流量回路存在物理耦合
        - 首选 FOPDT 模型
        """
        return cls(
            process_nature='self_regulating',   # 密闭容器时改为 'integrating'
            process_gain_sign=1,
            dead_time_dominant=False,
            coupling_risk='medium',              # 与流量回路耦合
            nonlinearity_type='none',
            preferred_simulation_model='FOPDT',
            allowed_simulation_models=['FOPDT', 'FO_INTEGRATOR'],
            max_model_order=1,
            typical_time_constant_range_s=[2.0, 300.0],     # 2s ~ 5min
            typical_dead_time_range_s=[0.0, 30.0],
            state_variables=['pressure'],
            mass_balance_constrained=True,
            energy_balance_constrained=False,
            output_physical_bounds=[0.0, 100.0],
            extra_constraints={
                'safety_relief_pressure_pct': 95.0,    # 安全阀起跳压力（%量程）
                'may_be_integrating': True,            # 密闭容器时需重判过程性质
            }
        )

    @classmethod
    def for_temperature(cls) -> 'MechanismModel':
        """
        温度回路机理
        - 自衡慢过程：热容大，时间常数分钟~小时级
        - 大纯滞后：传热路径长，滞后显著
        - 能量守恒：加入热量 = 散热 + 升温热容
        - 过程非线性：传热系数随温度变化
        - 可能需要 SOPDT 模型捕捉双容热系统
        """
        return cls(
            process_nature='self_regulating',
            process_gain_sign=1,
            dead_time_dominant=True,            # 大纯滞后系统
            coupling_risk='low',
            nonlinearity_type='process_nonlinear',
            preferred_simulation_model='FOPDT',
            allowed_simulation_models=['FOPDT', 'SOPDT'],
            max_model_order=2,
            typical_time_constant_range_s=[60.0, 7200.0],   # 1分钟 ~ 2小时
            typical_dead_time_range_s=[10.0, 600.0],        # 10s ~ 10分钟
            state_variables=['temperature'],
            mass_balance_constrained=False,
            energy_balance_constrained=True,
            output_physical_bounds=[0.0, 500.0],            # 典型工业温度(°C)
            extra_constraints={
                'conservative_tuning_required': True,       # 大惯性系统必须保守整定
                'max_rate_of_change_per_min': 5.0,          # 最大升温速率（°C/min）
            }
        )

    @classmethod
    def for_loop_type(cls, loop_type: str) -> 'MechanismModel':
        """根据回路类型字符串返回对应标准机理模型"""
        factory_map = {
            'level':       cls.for_level,
            'flow':        cls.for_flow,
            'pressure':    cls.for_pressure,
            'temperature': cls.for_temperature,
        }
        factory = factory_map.get(loop_type)
        if factory is None:
            raise ValueError(f"未知回路类型: {loop_type!r}，支持: {list(factory_map.keys())}")
        return factory()
