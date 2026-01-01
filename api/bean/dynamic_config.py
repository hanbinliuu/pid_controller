#!/usr/bin/env python3
"""
动态配置参数表Bean类
用于管理系统中的动态配置参数
"""
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4

from sqlalchemy import func, Text
from sqlmodel import SQLModel, Field, Column, JSON

class DynamicConfig(SQLModel, table=True):
    """
    动态配置参数表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: dynamic_config
    用途: 存储系统中的动态配置参数，支持键值对配置
    """
    __tablename__ = "dynamic_config"  # 数据库表名
    __table_args__ = {"comment": "动态配置参数表"}

    # 主键
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        index=True,
        sa_column_kwargs={"comment": "配置ID(UUID)"}
    )

    # 配置键（唯一）
    config_key: str = Field(
        max_length=200,
        index=True,
        unique=True,
        sa_column_kwargs={"comment": "配置键，唯一标识一个配置项"}
    )
    
    # 配置值（支持JSON格式）
    config_value: Optional[str] = Field(
        default=None,
        sa_column=Column(Text,comment="配置值，可以是字符串或JSON格式")
    )
    
    # 配置类型
    config_type: Optional[str] = Field(
        default="string",
        max_length=50,
        index=True,
        sa_column_kwargs={"comment": "配置类型：string, number, boolean, json等"}
    )
    
    # 配置分组
    config_group: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        sa_column_kwargs={"comment": "配置分组，用于分类管理"}
    )
    
    # 配置描述
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "配置描述"}
    )
    
    # 是否启用
    is_enabled: Optional[bool] = Field(
        default=True,
        index=True,
        sa_column_kwargs={"comment": "是否启用该配置"}
    )
    
    # 创建者
    created_by: Optional[str] = Field(
        default=None,
        max_length=100,
        sa_column_kwargs={"comment": "创建者"}
    )
    
    # 更新者
    updated_by: Optional[str] = Field(
        default=None,
        max_length=100,
        sa_column_kwargs={"comment": "更新者"}
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
                "config_key": "max_workers",
                "config_value": "10",
                "config_type": "number",
                "config_group": "performance",
                "description": "最大工作线程数",
                "is_enabled": True,
                "created_by": "admin"
            }
        }

    def __repr__(self) -> str:
        return f"<DynamicConfig(id={self.id}, config_key={self.config_key}, config_group={self.config_group})>"

