#!/usr/bin/env python3
"""
数据库模型定义 - 使用SQLModel
SQLModel = SQLAlchemy + Pydantic
自动具备数据验证和API响应序列化功能
"""
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field, Column, JSON
from sqlalchemy import Text


class TuningRecord(SQLModel, table=True):
    """
    整定记录表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    """
    __tablename__ = "tuning_records"
    
    # 主键
    id: Optional[int] = Field(
        default=None,
        primary_key=True,
        index=True,
        description="记录ID"
    )
    
    # 回路信息
    loop_uri: str = Field(
        max_length=500,
        index=True,
        description="回路URI"
    )
    loop_name: str = Field(
        max_length=200,
        index=True,
        description="回路名称"
    )
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="描述"
    )
    
    # 整定信息
    tuning_method: str = Field(
        max_length=50,
        index=True,
        description="整定方法"
    )
    tuning_time: datetime = Field(
        index=True,
        description="整定时间"
    )
    operator: str = Field(
        max_length=100,
        description="操作人员"
    )
    
    # 参数信息
    before_params: str = Field(
        max_length=200,
        description="整定前参数"
    )
    after_params: str = Field(
        max_length=200,
        description="整定后参数"
    )
    
    # 状态和备注
    status: str = Field(
        default="成功",
        max_length=50,
        description="状态"
    )
    remark: Optional[str] = Field(
        default=None,
        sa_column=Column(Text),
        description="备注"
    )
    
    # 详细数据（JSON格式）
    tuning_details: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="整定详情"
    )
    
    # 时间戳
    created_time: datetime = Field(
        default_factory=datetime.now,
        description="创建时间"
    )
    updated_time: datetime = Field(
        default_factory=datetime.now,
        description="更新时间"
    )
    
    class Config:
        """
        Pydantic配置
        SQLModel会自动处理大部分配置
        """
        json_schema_extra = {
            "example": {
                "loop_uri": "/pid_zd/loop_001",
                "loop_name": "FIC101A",
                "description": "Flow Control Loop",
                "tuning_method": "KTL",
                "operator": "admin",
                "before_params": "PB:100, TI:50, TD:12.5",
                "after_params": "PB:71.43, TI:3.11, TD:2",
                "status": "成功",
                "remark": "整定效果良好"
            }
        }
    
    def __repr__(self) -> str:
        return f"<TuningRecord(id={self.id}, loop_name={self.loop_name}, method={self.tuning_method})>"
