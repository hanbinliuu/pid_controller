#!/usr/bin/env python3
"""
导入任务状态枚举
定义回路导入任务的所有状态类型
"""

from enum import Enum


class ImportStatus(Enum):
    """
    导入任务状态枚举
    """
    # 待处理
    PENDING = "pending"
    # 运行中
    RUNNING = "running"
    # 已完成
    COMPLETED = "completed"
    # 失败
    FAILED = "failed"
    
    def __str__(self) -> str:
        """返回状态值"""
        return self.value
    
    @classmethod
    def is_valid(cls, status: str) -> bool:
        """
        检查状态是否有效
        
        Args:
            status: 状态值
            
        Returns:
            bool: 状态是否有效
        """
        return status in [s.value for s in cls]
    
    @classmethod
    def get_description(cls, status: str) -> str:
        """
        获取状态描述
        
        Args:
            status: 状态值
            
        Returns:
            str: 状态描述
        """
        descriptions = {
            cls.PENDING.value: "待处理",
            cls.RUNNING.value: "运行中",
            cls.COMPLETED.value: "已完成",
            cls.FAILED.value: "失败"
        }
        return descriptions.get(status, "未知状态")
