#!/usr/bin/env python3
"""
集团、装置评估对象Bean类
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import UniqueConstraint, func
from sqlmodel import SQLModel, Field


class DeviceEvaluation(SQLModel, table=True):
    """
    装置评估表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: device_evaluation
    用途: 存储装置级别的评估数据，包括回路数、自动回路数、自控率等关键指标
    """
    __tablename__ = "device_evaluation"  # 数据库表名
    __table_args__ = (
        UniqueConstraint('device_uri', 'statistics_time', name='uq_device_date'),
        {"comment": "装置评估表"}
    )
    # 主键
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        index=True,
        sa_column_kwargs={"comment": "记录ID(UUID)"}
    )

    # 装置信息
    device_uri: Optional[str] = Field(
        default=None,
        max_length=500,
        index=True,
        sa_column_kwargs={"comment": "装置URI"}
    )
    
    # 父类装置URI
    parent_device_uri: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "父类装置URI"}
    )
    
    device_name: Optional[str] = Field(
        default=None,
        max_length=200,
        index=True,
        sa_column_kwargs={"comment": "装置名称"}
    )

    # 统计时间(按天统计)
    statistics_time: Optional[datetime] = Field(
        default=None,
        index=True,
        sa_column_kwargs={"comment": "统计时间(按天)"}
    )

    # 评估指标
    loop_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "回路数"}
    )
    
    open_loop_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "开环回路数"}
    )
    
    auto_loop_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "自动回路数"}
    )
    
    auto_control_rate: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "自控率"}
    )
    
    stable_loop_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "平稳回路数"}
    )
    
    stability_rate: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "平稳率"}
    )
    
    conditional_excluded_loop_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "条件剔除回路数"}
    )

    # 时间戳
    created_time: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={"server_default": func.now(), "comment": "创建时间"}
    )
    
    updated_time: Optional[datetime] = Field(
        default=None,
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
            "comment": "更新时间"
        }
    )

    class Config:
        """
        Pydantic配置
        SQLModel会自动处理大部分配置
        """
        json_schema_extra = {
            "example": {
                "device_uri": "/plant/0b521c82a96d4107a564e4c2678bdeca",
                "parent_device_uri": "/plant/parent_uri_example",
                "device_name": "常减压装置",
                "statistics_time": "2023-10-01",
                "loop_count": 45,
                "open_loop_count": 5,
                "auto_loop_count": 38,
                "auto_control_rate": 0.844,
                "stable_loop_count": 40,
                "stability_rate": 0.889,
                "conditional_excluded_loop_count": 2
            },
            "description": "装置评估记录,按天和装置URI唯一索引,自动更新已存在记录"
        }

    def __repr__(self) -> str:
        return f"<DeviceEvaluation(id={self.id}, device_name={self.device_name}, statistics_time={self.statistics_time})>"