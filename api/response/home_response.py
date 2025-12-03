#!/usr/bin/env python3
"""
首页接口响应模型
"""
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class HomeStatsData(BaseModel):
    """首页统计数据模型"""
    total_loops: int = Field(..., description="总回路数")
    auto_control_loops: int = Field(..., description="自控回路数")
    auto_control_rate: float = Field(..., description="自控率(%)")
    avg_stability_rate: float = Field(..., description="平均稳定率(%)")
    optimizable_loops: int = Field(..., description="可优化回路数")
    recent_tuning_count: int = Field(..., description="近期整定次数")
    
    class Config:
        json_schema_extra = {
            "example": {
                "total_loops": 150,
                "auto_control_loops": 120,
                "auto_control_rate": 80.0,
                "avg_stability_rate": 85.5,
                "optimizable_loops": 30,
                "recent_tuning_count": 10
            }
        }


class DeviceStats(BaseModel):
    """装置统计数据"""
    device_uri: str = Field(..., description="装置URI")
    device_name: str = Field(..., description="装置名称")
    loop_count: int = Field(..., description="回路数量")
    auto_control_rate: float = Field(..., description="自控率(%)")
    stability_rate: float = Field(..., description="平稳率(%)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "device_uri": "/device/xxx",
                "device_name": "装置A",
                "loop_count": 50,
                "auto_control_rate": 85.0,
                "stability_rate": 90.0
            }
        }


class RecentTuningRecord(BaseModel):
    """近期整定记录"""
    id: UUID = Field(..., description="记录ID(UUID)")
    loop_name: str = Field(..., description="回路名称")
    tuning_method: str = Field(..., description="整定方法")
    operator: str = Field(..., description="操作人员")
    status: str = Field(..., description="状态")
    created_at: str = Field(..., description="创建时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "loop_name": "FIC-101",
                "tuning_method": "大模型整定",
                "operator": "admin",
                "status": "成功",
                "created_at": "2024-12-03T10:30:00"
            }
        }


class HomePageData(BaseModel):
    """首页数据"""
    stats: HomeStatsData = Field(..., description="统计数据")
    top_devices: Optional[List[DeviceStats]] = Field(None, description="TOP装置列表")
    recent_tunings: Optional[List[RecentTuningRecord]] = Field(None, description="近期整定记录")
    
    class Config:
        json_schema_extra = {
            "example": {
                "stats": {
                    "total_loops": 150,
                    "auto_control_loops": 120,
                    "auto_control_rate": 80.0,
                    "avg_stability_rate": 85.5,
                    "optimizable_loops": 30,
                    "recent_tuning_count": 10
                },
                "top_devices": [],
                "recent_tunings": []
            }
        }
