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

    表名: dynamic_config
    用途: 存储系统中的动态配置参数，支持键值对配置
    """
    __tablename__ = "dynamic_config"  # 数据库表名
    __table_args__ = {"comment": "动态配置参数表"}

    # 配置键（唯一）
    config_key: str = Field(
        max_length=200,
        primary_key=True,
        index=True,
        unique=True,
        sa_column_kwargs={"comment": "配置键"}
    )
    
    # 配置值（支持JSON格式）
    config_value: Optional[Any] = Field(
        default=None,
        sa_column=Column(Text,comment="配置值")
    )
    
    # 配置分组
    config_group: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        sa_column_kwargs={"comment": "配置分组，用于分类管理"}
    )
    
    # 配置名称
    config_name: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "配置名称"}
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
                "config_name": "最大工作线程数"
            }
        }

    def __repr__(self) -> str:
        return f"<DynamicConfig( config_key={self.config_key}, config_group={self.config_group})>"


