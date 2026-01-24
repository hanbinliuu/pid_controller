"""
模型类型枚举 (Model Type Enumeration)
=====================================

定义支持的模型类型及其关联常量。
"""


class ModelType:
    """模型类型枚举"""
    # 线性模型
    FOPDT = "FOPDT"           # 一阶加纯滞后模型 (First Order Plus Dead Time)
    FO = "FO"                 # 纯一阶模型 (First Order)
    SOPDT = "SOPDT"           # 二阶加纯滞后模型 (Second Order Plus Dead Time)
    SO = "SO"                 # 纯二阶模型 (Second Order, 无滞后)
    FOPI = "FO_INTEGRATOR"    # 一阶积分模型 (First Order Plus Integrator)
    SOPI = "SO_INTEGRATOR"    # 二阶积分模型 (Second Order Integrator)
    
    # 非线性模型
    HAMMERSTEIN = "HAMMERSTEIN"       # Hammerstein模型 (静态非线性 + 线性动态)
    DEADBAND_FOPDT = "DEADBAND_FOPDT" # 死区 + FOPDT模型
    SATURATION_FOPDT = "SAT_FOPDT"    # 饱和 + FOPDT模型
    
    # ============================================================
    # 统一常量定义（避免各模块重复定义）
    # ============================================================
    
    # 候选模型列表（用于多模型拟合）
    CANDIDATE_MODELS = [FOPDT, FO, SO, SOPDT, FOPI]
    
    # 模型参数数量（用于AIC/BIC计算）
    MODEL_PARAM_COUNT = {
        FOPDT: 3,
        FO: 2,
        SO: 3,
        SOPDT: 4,
        FOPI: 2,
    }
    
    @classmethod
    def get_bounds(cls, model_type: str) -> tuple:
        """获取模型参数边界（统一从Config.MODEL_BOUNDS读取）"""
        from . import Config
        bounds_config = Config.MODEL_BOUNDS.get(model_type, {})
        if 'initial' in bounds_config:
            return bounds_config['initial']
        # 默认回退边界
        return ([-10.0, 1.0, 0.0], [10.0, 500.0, 50.0])
