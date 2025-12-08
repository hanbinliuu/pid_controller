#!/usr/bin/env python3
"""
评估接口响应模型
"""
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime, date


class LoopEvaluationData(BaseModel):
    """回路评估数据模型"""
    id: str = Field(..., description="评估记录ID")
    loop_uri: str = Field(..., description="回路URI")
    loop_name: str = Field(..., description="回路名称")
    description: Optional[str] = Field(None, description="回路描述")
    loop_type: Optional[str] = Field(None, description="回路类型")
    tuning_method: Optional[str] = Field(None, description="整定方法")
    assessment_time: Optional[datetime] = Field(None, description="整定时间")
    performance_score: Optional[float] = Field(None, description="性能得分(0-100)")
    stability_score: Optional[float] = Field(None, description="稳定性得分(0-100)")
    evaluation_date: date = Field(..., description="评估日期")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC-101",
                "description": "流量回路",
                "tuning_method": "大模型整定",
                "tuning_time": "2024-12-03T10:30:00",
                "performance_score": 85.5,
                "stability_score": 90.0,
                "evaluation_date": "2024-12-03"
            }
        }


class DeviceEvaluationData(BaseModel):
    """装置评估数据模型"""
    id: str = Field(..., description="评估记录ID")
    device_uri: str = Field(..., description="装置URI")
    device_name: str = Field(..., description="装置名称")
    total_loops: int = Field(..., description="总回路数")
    auto_control_rate: float = Field(..., description="自控率(%)")
    stability_rate: float = Field(..., description="平稳率(%)")
    avg_performance_score: Optional[float] = Field(None, description="平均性能得分")
    evaluation_date: date = Field(..., description="评估日期")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "device_uri": "/device/xxx",
                "device_name": "装置A",
                "total_loops": 50,
                "auto_control_rate": 85.5,
                "stability_rate": 90.0,
                "avg_performance_score": 88.0,
                "evaluation_date": "2024-12-03"
            }
        }


class ExcludedLoopData(BaseModel):
    """剔除回路数据模型"""
    id: str = Field(..., description="记录ID")
    uri: str = Field(..., description="回路/装置URI")
    reason: Optional[str] = Field(None, description="剔除原因")
    created_at: datetime = Field(..., description="创建时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "reason": "性能不达标",
                "created_at": "2024-12-03T10:30:00"
            }
        }


class BatchExcludeResult(BaseModel):
    """批量剔除结果"""
    uri: str = Field(..., description="URI")
    status: str = Field(..., description="状态(success/failed)")
    id: Optional[str] = Field(None, description="记录ID")
    error: Optional[str] = Field(None, description="错误信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "uri": "/pid_zd/xxx",
                "status": "success",
                "id": 1,
                "error": None
            }
        }


class BatchExcludeResponse(BaseModel):
    """批量剔除响应"""
    success_count: int = Field(..., description="成功数量")
    failed_count: int = Field(..., description="失败数量")
    results: List[BatchExcludeResult] = Field(..., description="详细结果列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success_count": 2,
                "failed_count": 0,
                "results": [
                    {
                        "uri": "/pid_zd/xxx1",
                        "status": "success",
                        "id": 1
                    },
                    {
                        "uri": "/pid_zd/xxx2",
                        "status": "success",
                        "id": 2
                    }
                ]
            }
        }
