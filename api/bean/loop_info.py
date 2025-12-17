#!/usr/bin/env python3
"""
回路信息表Bean类
用于管理回路的基本信息
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import func, UniqueConstraint
from sqlmodel import SQLModel, Field


class LoopInfo(SQLModel, table=True):
    """
    回路信息表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: loop_info
    用途: 存储回路的基本信息，包括路径、名称、测点映射等
    """
    __tablename__ = "loop_info"  # 数据库表名
    __table_args__ = (
        UniqueConstraint('loop_uri', 'loop_path', name='uq_uri_path'),

        {"comment": "回路信息表"}
    )

    # 主键
    id: Optional[str] = Field(
        default_factory=lambda: str(uuid4()),
        primary_key=True,
        index=True,
        sa_column_kwargs={"comment": "记录ID(UUID)"}
    )

    # 回路信息
    loop_uri: Optional[str] = Field(
        default=None,
        max_length=500,
        index=True,
        unique=True,
        sa_column_kwargs={"comment": "回路URI，唯一标识一个回路"}
    )
    
    loop_path: Optional[str] = Field(
        default=None,
        index=True,
        unique=True,
        max_length=500,
        sa_column_kwargs={"comment": "PID相关参数的相对路径"}
    )
    
    loop_name: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "回路名称"}
    )
    
    loop_type: Optional[str] = Field(
        default=None,
        max_length=100,
        sa_column_kwargs={"comment": "回路类型"}
    )
    
    point_path: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "测点相对路径"}
    )
    # 测点路径映射（JSON格式存储多个测点）
    pv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "PV（过程变量）字段名"}
    )
    
    sv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "SV（设定值）字段名"}
    )
    
    mv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "MV（操纵变量）字段名"}
    )

    # 状态字段
    auto_status_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "自动/手动状态字段名"}
    )
    
    # PID 参数字段映射
    pb_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "PB（比例带）字段名"}
    )
    
    ti_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "TI（积分时间常数）字段名"}
    )
    
    td_field: Optional[str] = Field(
        default=None,
        max_length=200,
        sa_column_kwargs={"comment": "TD（微分时间常数）字段名"}
    )

    # 备注
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        sa_column_kwargs={"comment": "描述或备注"}
    )

    # 时间戳
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
    
    is_active: Optional[bool] = Field(
        default=None,
        sa_column_kwargs={"comment": "是否激活"}
    )


    class Config:
        """
        Pydantic配置
        SQLModel会自动处理大部分配置
        """
        json_schema_extra = {
            "example": {
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_path": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d44b4388e29829f95a49c6,/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC101A流量控制回路",
                "loop_type": "流量控制",
                "point_path":"/loop_state_parameters",
                "pv_field": "FIC101A_PV",
                "sv_field": "FIC101A_SV",
                "mv_field": "FIC101A_MV",
                "auto_status_field": "FIC101A_AUTO",
                "pb_field": "FIC101A_PB",
                "ti_field": "FIC101A_TI",
                "td_field": "FIC101A_TD",
                "is_active": True
            }
        }

    def __repr__(self) -> str:
        return f"<LoopInfo(id={self.id}, loop_uri={self.loop_uri}, loop_name={self.loop_name})>"