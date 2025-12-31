#!/usr/bin/env python3
"""
回路评估详情响应模型
用于接口返回的回路评估详细信息
"""
from typing import Optional
from datetime import datetime, date
from pydantic import BaseModel, Field


class LoopEvaluationDetailResponse(BaseModel):
    """回路评估详情响应模型"""
    id: str = Field(..., description="评估记录ID")
    loop_uri: str = Field(..., description="回路URI")
    loop_name: str = Field(..., description="回路名称")
    loop_type: Optional[str] = Field(None, description="回路类型")
    description: Optional[str] = Field(None, description="回路描述")
    tuning_method: Optional[str] = Field(None, description="整定方法")
    assessment_time: Optional[datetime] = Field(None, description="整定时间")
    performance_score: Optional[float] = Field(None, description="性能得分(0-100)")
    stability_score: Optional[float] = Field(None, description="稳定性得分(0-100)")
    evaluation_date: date = Field(..., description="评估日期")
    created_time: Optional[datetime] = Field(None, description="创建时间")
    updated_time: Optional[datetime] = Field(None, description="更新时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC101A流量控制回路",
                "description": "流量控制回路",
                "tuning_method": "大模型整定",
                "assessment_time": "2024-12-03T10:30:00",
                "performance_score": 85.5,
                "stability_score": 90.0,
                "evaluation_date": "2024-12-03",
                "created_time": "2024-12-03T10:30:00",
                "updated_time": "2024-12-03T10:30:00"
            }
        }


class LoopEvaluationListItemResponse(BaseModel):
    """回路评估列表项响应模型"""
    id: str = Field(..., description="评估记录ID")
    loop_uri: str = Field(..., description="回路URI")
    loop_name: str = Field(..., description="回路名称")
    assessment_time: Optional[datetime] = Field(None, description="整定时间")
    performance_score: Optional[float] = Field(None, description="性能得分(0-100)")
    stability_score: Optional[float] = Field(None, description="稳定性得分(0-100)")
    created_time: Optional[datetime] = Field(None, description="创建时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC101A流量控制回路",
                "assessment_time": "2024-12-03T10:30:00",
                "performance_score": 85.5,
                "stability_score": 90.0,
                "created_time": "2024-12-03T10:30:00"
            }
        }


class LoopEvaluationListResponse(BaseModel):
    """回路评估列表响应模型"""
    evaluations: list[LoopEvaluationListItemResponse] = Field(..., description="评估记录列表")
    pagination: dict = Field(..., description="分页信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "evaluations": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                        "loop_name": "FIC101A流量控制回路",
                        "assessment_time": "2024-12-03T10:30:00",
                        "performance_score": 85.5,
                        "stability_score": 90.0,
                        "created_time": "2024-12-03T10:30:00"
                    }
                ],
                "pagination": {
                    "total": 1,
                    "pages": 1,
                    "pageNo": 1,
                    "pageSize": 10
                }
            }
        }