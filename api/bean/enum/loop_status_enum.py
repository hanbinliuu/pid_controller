#!/usr/bin/env python3
"""
Loop Status Enum Class
Defines various status values for loop performance evaluation
"""
from enum import Enum


class PerformanceStatus(str, Enum):
    """
    Performance Status Enum
    """
    # Performance levels
    EXCELLENT = "优"
    GOOD = "良"
    AVERAGE = "中"
    POOR = "差"
    
    # Special statuses
    OPEN = "开环"        # Open loop control status
    CONDITIONAL_EXCLUDED = "条件剔除"  # Conditionally excluded status
    UNKNOWN = "未知"          # Unknown status (exception or calculation failure)
    
    @classmethod
    def get_all_status(cls) -> list:
        """Get all status values"""
        return [member.value for member in cls]
    
    @classmethod
    def is_valid_status(cls, status: str) -> bool:
        """Check if status value is valid"""
        return status in cls.get_all_status()
    
    @classmethod
    def get_performance_status(cls) -> list:
        """Get performance level statuses (Excellent, Good, Average, Poor)"""
        return [cls.EXCELLENT.value, cls.GOOD.value, cls.AVERAGE.value, cls.POOR.value]
    
    @classmethod
    def get_special_status(cls) -> list:
        """Get special statuses (Open Loop, Conditionally Excluded, Unknown)"""
        return [cls.OPEN.value, cls.CONDITIONAL_EXCLUDED.value, cls.UNKNOWN.value]