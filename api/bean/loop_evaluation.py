#!/usr/bin/env python3
"""
回路评估对象Bean类
定义回路性能评估的数据结构
"""
from datetime import datetime, date
from typing import Optional, Dict, Any

from sqlalchemy import Text
from sqlmodel import SQLModel, Field, Column, JSON


class LoopEvaluation(SQLModel, table=True):
    """
    回路评估表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能
    
    表名: loop_evaluation
    用途: 存储回路性能评估记录，包括整定前后的参数对比、性能评分等信息
    """
    __tablename__ = "loop_evaluation"  # 数据库表名
    __table_args__ = {"comment": "回路评估明细表"}

    # 主键
    id: Optional[int] = Field(
        default=None,
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

    loop_name: Optional[str] = Field(
        default=None,
        max_length=200,
        index=True,
        sa_column_kwargs={"comment": "回路名称"}
    )


    assessment_time: Optional[datetime] = Field(
        default=None,
        index=True,
        sa_column_kwargs={"comment": "评估时间(按天)"}
    )

    # 性能评估指标
    performance_score: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "综合性能评分"}
    )
    auto_control_rate: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "自控率 (%)"}
    )
    stability_rate: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "平稳率 (%)"}
    )
    auto_control_time: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "自动控制时间 (秒)"}
    )
    stable_time: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "稳定时间 (秒)"}
    )
    total_time: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "总时间 (秒)"}
    )
    pt_count: Optional[int] = Field(
        default=None,
        sa_column_kwargs={"comment": "数据点数量"}
    )
    pv_sum_value: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "过程变量和"}
    )
    pv_sum_squares: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "过程变量平方和"}
    )
    mv_sum_value: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "操纵变量和"}
    )

    mv_sum_squares: Optional[float] = Field(
        default=None,
        sa_column_kwargs={"comment": "操纵变量平方和"}
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
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC101A流量控制回路",
                "assessmen_time": "2025-12-01 00:00:00",
                "performance_score": 85.5,
                "auto_control_rate": 92.3,
                "stability_rate": 88.7,
                "auto_control_time": 79200,
                "stable_time": 75600,
                "total_time": 86400,
                "pt_count": 1440,
                "pv_sum_value": 14400,
                "pv_sum_squares": 144000,
                "mv_sum_value": 43200,
                "mv_sum_squares": 1296000
            },
            "description": "回路评估记录，按天和回路URI进行性能评估，记录自控率、平稳率等关键指标"
        }

    def __repr__(self) -> str:
        return f"<LoopEvaluation(id={self.id}, loop_name={self.loop_name}, score={self.performance_score})>"