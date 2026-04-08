"""
OS 语义层过程模型模块 (Process Model Module)
=============================================

本模块实现架构图中「数据抽象层」的核心语义模型，为上层的常规PID整定
和大模型整定两条路径提供统一的过程知识接口。

目录结构
--------
- schemas/      6 大原子语义模型 dataclass（数据结构定义）
- provider/     SemanticProvider（从 JSON/API 读取并聚合模型）
- features/     特征计算工具包（供 OS 中台参考实现 characterization API）
- contracts/    对外 API 契约文档（os_api_spec.md / api_contract_sample.json）
- data/         本地 JSON 模拟数据（instance_models / standard_models）

对外接口（完全向后兼容，外部代码无需任何改动）
----------------------------------------------
    from core.models import SemanticProvider
    from core.models import OntologyModel, CharacterizationModel
    from core.models import calculate_characterization
"""

# ── 6 大原子语义模型 ──────────────────────────────────────────────────
from .schemas import (
    OntologyModel,
    MechanismModel,
    KnowledgeModel,
    CharacterizationModel,
    SignalCharacteristics,
    ValveCharacteristics,
    ControlPerformance,
    DataModel,
    MetricsModel,
)

# ── 数据读取与聚合 ────────────────────────────────────────────────────
from .provider import SemanticProvider

# ── 特征计算工具包（供 OS 中台参考实现）──────────────────────────────
from .features import (
    calculate_characterization,
    calculate_characterization_as_dict,
    calculate_oscillation_ratio,
    calculate_noise_level,
    calculate_linearity_index,
    calculate_dominant_period_s,
    calculate_stiction_index,
    calculate_deadband_estimated,
    calculate_reversal_error,
    calculate_recent_step_events,
    calculate_performance_score,
)

__all__ = [
    # schemas
    'OntologyModel',
    'MechanismModel',
    'KnowledgeModel',
    'CharacterizationModel',
    'SignalCharacteristics',
    'ValveCharacteristics',
    'ControlPerformance',
    'DataModel',
    'MetricsModel',
    # provider
    'SemanticProvider',
    # features
    'calculate_characterization',
    'calculate_characterization_as_dict',
    'calculate_oscillation_ratio',
    'calculate_noise_level',
    'calculate_linearity_index',
    'calculate_dominant_period_s',
    'calculate_stiction_index',
    'calculate_deadband_estimated',
    'calculate_reversal_error',
    'calculate_recent_step_events',
    'calculate_performance_score',
]
