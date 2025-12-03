from dataclasses import dataclass
from enum import Enum
from typing import List, Dict


class ModelType(Enum):
    """模型类型枚举"""
    FOPDT = 'FOPDT'  # 一阶加纯滞后模型（First Order Plus Dead Time）
    FO = 'FO'  # 纯一阶模型
    SOPDT = 'SOPDT'  # 二阶加纯滞后模型（向后兼容，带L参数）
    SO = 'SO'  # 纯二阶模型（无滞后）
    FOPI = 'FO_INTEGRATOR'  # 一阶积分模型（First Order Plus Integrator）
    SOPI = 'SO_INTEGRATOR'  # 二阶积分模型（Second Order Integrator）


    @classmethod
    def from_string(cls, value: str) -> 'ModelType':
        """从字符串创建枚举"""
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"不支持的模型类型: {value}，支持的类型: {[e.value for e in cls]}")

    @classmethod
    def get_model_type(cls) -> List[str]:
        return [e.value for e in ModelType]


    @property
    def display_name(self) -> str:
        """获取模型显示名称"""
        return MODEL_CONFIG[self].name

    @property
    def description(self) -> str:
        """获取模型描述"""
        return MODEL_CONFIG[self].description

    @property
    def param_count(self) -> int:
        """获取参数数量"""
        return MODEL_CONFIG[self].param_count

    @property
    def param_names(self) -> List[str]:
        """获取参数名称列表"""
        return MODEL_CONFIG[self].param_names


@dataclass
class ModelConfig:
    """模型配置数据类"""
    name: str  # 模型名称
    description: str  # 模型描述
    param_count: int  # 参数数量
    param_names: List[str]  # 参数名称列表
    transfer_function: str  # 传递函数表达式
    use_cases: List[str]  # 适用场景


# 模型配置映射
MODEL_CONFIG = {
    ModelType.FOPDT: ModelConfig(
        name="一阶加纯滞后模型",
        description="FOPDT (First Order Plus Dead Time)",
        param_count=3,
        param_names=['K', 'T', 'L'],
        transfer_function="G(s) = K / (T*s + 1) * e^(-L*s)",
        use_cases=["通用工业过程", "温度控制", "压力控制", "流量控制"]
    ),
    ModelType.FO: ModelConfig(
        name="纯一阶模型",
        description="First Order (无滞后)",
        param_count=2,
        param_names=['K', 'T'],
        transfer_function="G(s) = K / (T*s + 1)",
        use_cases=["无滞后系统", "快速响应过程"]
    ),
    ModelType.SOPDT: ModelConfig(
        name="二阶加纯滞后模型",
        description="SOPDT (Second Order Plus Dead Time)",
        param_count=4,
        param_names=['K', 'T1', 'T2', 'L'],
        transfer_function="G(s) = K / ((T1*s + 1)(T2*s + 1)) * e^(-L*s)",
        use_cases=["温度过程", "化学反应", "复杂热力系统", "有超调特性的系统", "多惯性环节串联"]
    ),
    ModelType.SO: ModelConfig(
        name="纯二阶模型",
        description="SO (Second Order, 无滞后)",
        param_count=3,
        param_names=['K', 'T1', 'T2'],
        transfer_function="G(s) = K / ((T1*s + 1)(T2*s + 1))",
        use_cases=["快速响应二阶系统", "无明显滞后的超调过程", "机械振动系统"]
    ),
    ModelType.FOPI: ModelConfig(
        name="一阶积分模型",
        description="FOPI (First Order Plus Integrator)",
        param_count=2,
        param_names=['K', 'T'],
        transfer_function="G(s) = K / (s(T*s + 1))",
        use_cases=["液位控制", "流量累积", "储罐系统", "积分特性过程"]
    ),
    ModelType.SOPI: ModelConfig(
        name="二阶积分模型",
        description="SOPI (Second Order Integrator)",
        param_count=3,
        param_names=['K', 'T1', 'T2'],
        transfer_function="G(s) = K / (s^2 * (T1*s + 1)(T2*s + 1))",
        use_cases=["双积分过程", "位置控制", "复杂液位系统", "多储罐串联"]
    )
}
