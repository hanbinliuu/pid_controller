from abc import ABC, abstractmethod
from typing import Optional

from ..context import TuningContext

class PipelineStage(ABC):
    """
    整定流水线阶段基类
    """
    
    def __init__(self, logger_mixin=None):
        """
        初始化
        :param logger_mixin: 传入带有 `log()` 方法的对象 (通常是 orchestrator 本身)
        """
        self.logger = logger_mixin

    def log(self, message: str):
        """转发日志到宿主"""
        if self.logger and hasattr(self.logger, 'log'):
            self.logger.log(message)

    @abstractmethod
    def execute(self, context: TuningContext) -> TuningContext:
        """
        执行本阶段逻辑
        
        Args:
            context: 整定上下文
            
        Returns:
            更新后的 context
            如果在此阶段直接生成了 final_result，则可以标记 context.final_result 后直接返回，
            orchestrator 发现 final_result 非空会提前终止流水线。
        """
        pass
