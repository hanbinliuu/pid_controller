#!/usr/bin/env python3
"""
数据库模型定义 - 使用SQLModel
SQLModel = SQLAlchemy + Pydantic
自动具备数据验证和API响应序列化功能
"""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field, Column, JSON
from sqlalchemy import Text


class TuningRecord(SQLModel, table=True):
    """
    整定记录表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    """
    __tablename__ = "tuning_records"
    __table_args__ = {"comment": "整定记录表"}

    # 主键
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        index=True,
        sa_column_kwargs={"comment": "记录ID"}
    )
    
    # 回路信息
    loop_uri: Optional[str] = Field(
        default=None,
        max_length=500,
        index=True,
        sa_column_kwargs={"comment": "回路URI"}
    )
    loop_status: Optional[str] = Field(
        default=None,
        max_length=50,
        index=True,
        sa_column_kwargs={"comment": "回路状态"}
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "描述"}
    )
    
    # 整定信息
    tuning_method: Optional[str] = Field(
        default=None,
        max_length=50,
        index=True,
        sa_column_kwargs={"comment": "整定方法"}
    )
    tuning_time: Optional[datetime] = Field(
        default=None,
        index=True,
        sa_column_kwargs={"comment": "整定时间"}
    )
    operator: Optional[str] = Field(
        default=None,
        max_length=100,
        sa_column_kwargs={"comment": "操作人员"}
    )
    operator_id: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        sa_column_kwargs={"comment": "操作人ID"}
    )
    
    # 参数信息
    before_params: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "整定前参数"}
    )
    after_params: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "整定后参数"}
    )
    
    # 状态和备注
    status: Optional[str] = Field(
        default=None,
        max_length=50,
        sa_column_kwargs={"comment": "状态"}
    )
    remark: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, comment="备注")
    )
    
    # 详细数据（JSON格式）
    tuning_details: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON, comment="整定详情")
    )
    
    # 时间戳
    created_time: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"comment": "创建时间"}
    )
    updated_time: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"comment": "更新时间"}
    )
    
    class Config:
        """
        Pydantic配置
        SQLModel会自动处理大部分配置
        """
        json_schema_extra = {
            "example": {
                "loop_uri": "/pid_zd/loop_001",
                "loop_status": "自动",
                "loop_name": "FIC101A",
                "description": "Flow Control Loop",
                "tuning_method": "PID",
                "operator": "admin",
                "operator_id": "user_001",
                "before_params": "{\"pb\": 18.5443, \"ti\": 1.0431, \"td\": 0.0, \"kp\": 5.3925, \"ki\": 5.1699, \"kd\": 0.0}",
                "after_params": "{\"pb\": 18.5443, \"ti\": 1.0431, \"td\": 0.0, \"kp\": 5.3925, \"ki\": 5.1699, \"kd\": 0.0}",
                "status": "成功",
                "remark": "整定效果良好"
            }
        }
    
    def __repr__(self) -> str:
        return f"<TuningRecord(id={self.id}, loop_name={self.loop_name}, method={self.tuning_method})>"