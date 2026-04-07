"""
OS 语义层过程模型模块 (Process Model Module)
=============================================

本模块实现架构图中「数据抽象层」的核心语义模型，为上层的常规PID整定
和大模型整定两条路径提供统一的过程知识接口。

模型分为两层：
1. 标准模型 (StandardProcessModel): 按回路类型定义的通用工艺模板
2. 实际模型 (InstanceProcessModel): 某个具体设备回路的实例化参数

通过 ModelProvider 统一获取，当前基于本地JSON文件，后续可替换为OS API。

使用示例::

    from core.models import ModelProvider

    provider = ModelProvider()
    
    # 获取标准模型
    level_model = provider.get_standard_model('level')
    
    # 获取实际模型
    instance = provider.get_instance_model('2216_LIC_50104')
    
    # 获取整定上下文（标准+实际 合并）
    ctx = provider.get_tuning_context('2216_LIC_50104')
"""

from .ontology_model import OntologyModel
from .mechanism_model import MechanismModel
from .knowledge_model import KnowledgeModel
from .characterization_model import CharacterizationModel
from .data_model import DataModel
from .metrics_model import MetricsModel
from .semantic_provider import SemanticProvider

__all__ = [
    'OntologyModel',
    'MechanismModel',
    'KnowledgeModel',
    'CharacterizationModel',
    'DataModel',
    'MetricsModel',
    'SemanticProvider',
]
