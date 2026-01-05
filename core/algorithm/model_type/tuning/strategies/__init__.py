"""
策略子模块 (Strategies Submodule)
================================

回路类型策略和LLM顾问。

模块内容
--------
- loop_type_strategies.py: 回路类型策略 (LoopTypeStrategy, get_loop_strategy)
- llm_conservative_advisor.py: LLM保守策略顾问 (LLMOscillationTuningAdvisor)
"""

from .loop_type_strategies import (
    LoopTypeStrategy,
    get_loop_strategy,
    register_loop_strategy,
    ExtremeScenario,
    detect_extreme_scenario,
    FlowLoopStrategy,
    TemperatureLoopStrategy,
    PressureLoopStrategy,
    LevelLoopStrategy,
    DefaultLoopStrategy,
)
from .llm_conservative_advisor import (
    LLMOscillationTuningAdvisor,
    ConservativeStrategyParams,
    TUNING_STRATEGIES,
)

__all__ = [
    # 策略基类和工厂
    'LoopTypeStrategy',
    'get_loop_strategy',
    'register_loop_strategy',
    # 极端场景检测
    'ExtremeScenario',
    'detect_extreme_scenario',
    # 具体策略
    'FlowLoopStrategy',
    'TemperatureLoopStrategy',
    'PressureLoopStrategy',
    'LevelLoopStrategy',
    'DefaultLoopStrategy',
    # LLM顾问
    'LLMOscillationTuningAdvisor',
    'ConservativeStrategyParams',
    'TUNING_STRATEGIES',
]
