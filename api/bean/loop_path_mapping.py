#!/usr/bin/env python3
"""
loop_uri 与 loop_path 映射关系表Bean类
用于管理回路URI与回路路径的对应关系
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class LoopPathMapping(SQLModel, table=True):
    """
    回路URI与路径映射表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: loop_path_mapping
    用途: 存储loop_uri与loop_path的映射关系，用于快速查询和转换
    """
    __tablename__ = "loop_path_mapping"  # 数据库表名
    __table_args__ = {"comment": "回路URI与路径映射表"}

    # 主键
    id: Optional[int] = Field(
        default=None,
        primary_key=True,
        index=True,
        description="映射记录ID"
    )

    # 映射关系
    loop_uri: str = Field(
        max_length=500,
        index=True,
        unique=True,
        description="回路URI，唯一标识一个回路"
    )
    
    loop_path: str = Field(
        max_length=500,
        index=True,
        description="回路路径"
    )
    
    loop_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="回路名称"
    )
    #
    point_path: Optional[str] = Field(
        default=None,
        max_length=500,
        description="测点相对路径"
    )
    # 测点路径映射（JSON格式存储多个测点）
    pv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="PV（过程变量）字段名"
    )
    
    sv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="SV（设定值）字段名"
    )
    
    mv_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="MV（操纵变量）字段名"
    )

    # 状态字段
    auto_status_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="自动/手动状态字段名"
    )
    
    # PID 参数字段映射
    pb_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="PB（比例带）字段名"
    )
    
    ti_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="TI（积分时间常数）字段名"
    )
    
    td_field: Optional[str] = Field(
        default=None,
        max_length=200,
        description="TD（微分时间常数）字段名"
    )

    # 备注
    description: Optional[str] = Field(
        default=None,
        max_length=500,
        description="描述或备注"
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
    
    is_active: bool = Field(
        default=True,
        description="是否激活"
    )


    class Config:
        """
        Pydantic配置
        SQLModel会自动处理大部分配置
        """
        json_schema_extra = {
            "example": {
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_path": "/设备/反应器/温度控制回路",
                "loop_name": "FIC101A流量控制回路",
                "point_path":"/loop_state_parameters",
                "pv_field": "FIC101A_PV",
                "sv_field": "FIC101A_SV",
                "mv_field": "FIC101A_MV",
                "op_field": "FIC101A_OP",
                "auto_status_field": "FIC101A_AUTO",
                "pb_field": "FIC101A_PB",
                "ti_field": "FIC101A_TI",
                "td_field": "FIC101A_TD",
                "is_active": True
            }
        }

    def __repr__(self) -> str:
        return f"<LoopPathMapping(id={self.id}, loop_uri={self.loop_uri}, loop_path={self.loop_path})>"
