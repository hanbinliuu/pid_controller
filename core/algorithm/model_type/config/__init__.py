"""
模型配置模块 (Model Configuration Module)
=========================================

本模块定义了模型辨识所需的全局配置参数。

🔥 核心参数（重点关注）
---------------------
OSCILLATION_TUNING:
    pb_min/pb_max: 比例带范围(%)，控制整定的保守程度
    ti_range: 积分时间范围(秒)
    
按场景调整
---------
1. 液位回路效果差 → 增大 level_ti_multiplier (2.2→2.5)
2. 温度回路仿真不收敛 → 增大 temperature_sim_duration_factor (8→10)
3. 振荡压制不足 → 增大 safety_factor_base (1.2→1.4)
4. 大滞后系统失败 → 增大 large_delay_pb_boost (1.8→2.2)

配置模块结构
-----------
- types.py: ModelType 枚举
- oscillation.py: 振荡整定配置
- simc.py: SIMC 整定配置
- model_bounds.py: 模型参数边界
- tuning.py: PID约束、模型拟合等
- preprocessing.py: 预处理配置
"""

# 导入类型
from .types import ModelType

# 导入配置字典
from .oscillation import OSCILLATION_TUNING
from .simc import SIMC_TUNING
from .model_bounds import MODEL_BOUNDS
from .tuning import (
    MODEL_FITTING,
    CLOSED_LOOP,
    LOOP_SPECIFIC_VERIFICATION,
    PID_CONSTRAINTS,
    OPTIMIZATION,
    PARAMETER_CONSTRAINTS,
    NONLINEAR_FITTING,
    TUNING_DEFAULTS,
    MODEL_SELECTOR,
    ROBUST_TUNING,
    SELF_OPTIMIZE,
    SLIDING_WINDOW,
)
from .preprocessing import (
    SEGMENT_PROCESSING,
    TUNING_SEGMENT,
    PREPROCESSING,
)
from .loop_presets import (
    LOOP_TYPE_PRESETS,
    get_loop_preset,
    get_adjusted_pb_range,
    get_adjusted_safety_factor,
)
from .loop_type_inferrer import infer_loop_type, infer_loop_type_from_data, format_inference_log


class Config:
    """系统配置类：包含模型辨识相关的配置参数"""
    EPSILON = 1e-9
    
    # 聚合所有配置
    OSCILLATION_TUNING = OSCILLATION_TUNING
    SIMC_TUNING = SIMC_TUNING
    MODEL_FITTING = MODEL_FITTING
    CLOSED_LOOP = CLOSED_LOOP
    LOOP_SPECIFIC_VERIFICATION = LOOP_SPECIFIC_VERIFICATION
    SEGMENT_PROCESSING = SEGMENT_PROCESSING
    TUNING_SEGMENT = TUNING_SEGMENT
    PID_CONSTRAINTS = PID_CONSTRAINTS
    OPTIMIZATION = OPTIMIZATION
    PARAMETER_CONSTRAINTS = PARAMETER_CONSTRAINTS
    MODEL_BOUNDS = MODEL_BOUNDS
    NONLINEAR_FITTING = NONLINEAR_FITTING
    TUNING_DEFAULTS = TUNING_DEFAULTS
    MODEL_SELECTOR = MODEL_SELECTOR
    PREPROCESSING = PREPROCESSING
    LOOP_TYPE_PRESETS = LOOP_TYPE_PRESETS
    ROBUST_TUNING = ROBUST_TUNING
    SELF_OPTIMIZE = SELF_OPTIMIZE
    SLIDING_WINDOW = SLIDING_WINDOW


# 导出
__all__ = ['Config', 'ModelType', 'get_loop_preset', 'get_adjusted_pb_range', 'get_adjusted_safety_factor',
           'infer_loop_type', 'format_inference_log']
