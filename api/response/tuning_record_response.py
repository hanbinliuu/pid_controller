#!/usr/bin/env python3
"""
整定记录接口响应模型
"""
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class TuningRecordData(BaseModel):
    """整定记录数据模型"""
    id: str = Field(..., description="记录ID")
    loop_uri: str = Field(..., description="回路URI")
    loop_name: str = Field(..., description="回路名称")
    tuning_method: str = Field(..., description="整定方法")
    operator: str = Field(..., description="操作人员")
    before_params: str = Field(..., description="整定前参数(JSON字符串)")
    after_params: str = Field(..., description="整定后参数(JSON字符串)")
    description: Optional[str] = Field(None, description="描述")
    status: str = Field(..., description="状态")
    remark: Optional[str] = Field(None, description="备注")
    tuning_details: Optional[Dict[str, Any]] = Field(None, description="整定详情")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 1,
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC-101",
                "tuning_method": "大模型整定",
                "operator": "admin",
                "before_params": "{\"kp\":1.0,\"ki\":0.2,\"kd\":0.05}",
                "after_params": "{\"kp\":1.5,\"ki\":0.3,\"kd\":0.1}",
                "description": "整定说明",
                "status": "成功",
                "remark": "备注信息",
                "tuning_details": {},
                "created_at": "2024-12-03T10:30:00",
                "updated_at": "2024-12-03T10:30:00"
            }
        }
