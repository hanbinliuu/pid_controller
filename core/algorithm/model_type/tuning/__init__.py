"""
整定子模块 (Tuning Submodule)
=============================

负责PID参数计算、振荡整定和闭环验证。

模块结构（按功能分组）
--------------------

### 核心PID计算 (core/)
- data_classes.py: 数据类 (ClosedLoopMetrics, DataQualityInfo)
- tuning_methods.py: 整定公式 (TuningMethodsMixin) - Lambda/IMC/Cohen-Coon
- pid_calculator.py: 主计算器 (PIDCalculator)

### 振荡整定 (oscillation/)
- oscillation_tuner.py: 振荡整定器 (OscillationTuner) - 临界法整定主入口
- oscillation_analysis.py: 振荡分析 (OscillationAnalysisMixin) - 周期/增益检测
- oscillation_rating.py: 振荡整定评分 (OscillationRatingCalculator)
- conservative_pid.py: 保守PID计算 (ConservativePIDCalculator)

### 验证与评分 (verification/)
- closed_loop_sim.py: 闭环仿真 (ClosedLoopSimMixin) - 稳定性验证
- model_rating.py: 模型评分 (ModelRatingMixin) - 综合评分计算

### 策略 (strategies/)
- loop_type_strategies.py: 回路类型策略 (LoopTypeStrategy) - 流量/温度/压力/液位
- llm_conservative_advisor.py: LLM保守策略顾问 (LLMOscillationTuningAdvisor)

### 类型定义 (根目录)
- types.py: 类型提示 (ValveIssues, ConservativePIDParams)
"""

# ============================================================
# 核心PID计算 (从 core/ 子文件夹导入)
# ============================================================
from .core.data_classes import ClosedLoopMetrics, DataQualityInfo
from .core.pid_calculator import PIDCalculator

# ============================================================
# 振荡整定 (从 oscillation/ 子文件夹导入)
# ============================================================
from .oscillation.oscillation_tuner import OscillationTuner
from .oscillation.conservative_pid import ConservativePIDCalculator
from .oscillation.oscillation_rating import OscillationRatingCalculator

# ============================================================
# 策略 (从 strategies/ 子文件夹导入)
# ============================================================
from .strategies.loop_type_strategies import get_loop_strategy, LoopTypeStrategy

# ============================================================
# 方法选择器 (自动选择整定方法)
# ============================================================
from .method_selector import TuningMethodSelector, TuningMethod, DataCharacteristics, TuningMethodResult

# ============================================================
# 验证 (稳定性分析)
# ============================================================
from .verification.stability_analyzer import StabilityAnalyzer, StabilityMargins

__all__ = [
    # 核心
    'PIDCalculator', 
    'DataQualityInfo', 
    'ClosedLoopMetrics',
    # 振荡整定
    'OscillationTuner',
    'ConservativePIDCalculator',
    'OscillationRatingCalculator',
    # 策略
    'get_loop_strategy',
    'LoopTypeStrategy',
    # 方法选择器
    'TuningMethodSelector',
    'TuningMethod',
    'DataCharacteristics',
    'TuningMethodResult',
    # 验证
    'StabilityAnalyzer',
    'StabilityMargins',
]
