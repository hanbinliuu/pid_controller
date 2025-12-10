#!/usr/bin/env python3
"""
整定记录接口响应模型
"""
from typing import Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field
from datetime import datetime


class TuningRecordRequest(BaseModel):
    """整定记录数据模型"""
    loop_uri: str = Field(..., description="回路URI")
    tuning_method: str = Field(..., description="整定方法")
    auto_status: datetime = Field(..., description="自控情况")
    before_params: str = Field(..., description="整定前参数(JSON字符串)")
    after_params: str = Field(..., description="整定后参数(JSON字符串)")
    status: str = Field(..., description="状态")
    remark: Optional[str] = Field(None, description="备注")
    tuning_details: Optional[str] = Field(None, description="整定详情")

    class Config:
        json_schema_extra = {
            "example": {
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "tuning_method": "大模型整定",
                "loop_type": "液位",
                "description": "回路描述",
                "before_params": {"kp": 1.25, "kd": 0.0, "ki": 0.01, "pb": 79.99, "ti": 120.0, "td": 0.0},
                "after_params": {"kp": 1.25, "kd": 0.0, "ki": 0.01, "pb": 79.99, "ti": 120.0, "td": 0.0},
                "status": "成功",
                "remark": "参数下发完成",
                "tuning_details": ""
            }
        }
