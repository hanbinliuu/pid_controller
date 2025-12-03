#!/usr/bin/env python3
"""
条件剔除回路对象Bean类
"""

from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field


class ExcludedLoop(SQLModel, table=True):
    """
    条件剔除回路表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: excluded_loop
    用途: 存储被条件剔除的回路或装置信息
    """
    __tablename__ = "excluded_loop"  # 数据库表名
    __table_args__ = {"comment": "条件剔除回路表"}

    # 主键
    id: Optional[UUID] = Field(
        default_factory=uuid4,
        primary_key=True,
        index=True,
        sa_column_kwargs={"comment": "记录ID(UUID)"}
    )

    # 回路/装置信息
    uri: str = Field(
        max_length=500,
        index=True,
        sa_column_kwargs={"comment": "回路/装置URI"}
    )
    
    # 剔除原因
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "剔除原因"}
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
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "reason": "数据质量差"
            }
        }

    def __repr__(self) -> str:
        return f"<ExcludedLoop(id={self.id}, uri={self.uri}, reason={self.reason})>"