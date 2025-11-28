#!/usr/bin/env python3
"""
回路评估对象Bean类
定义回路性能评估的数据结构
"""
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

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
        default=None,
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

    # 性能评估指标
    performance_score: Optional[float] = Field(
        default=None,
        description="综合性能评分"
    )
    auto_control_rate: Optional[float] = Field(
        default=None,
        description="自动控制率 (%)"
    )
    stability_rate: Optional[float] = Field(
        default=None,
        description="稳定性评分 (%)"
    )
    auto_control_time: Optional[int] = Field(
        default=None,
        description="自动控制时间 (秒)"
    )
    stable_time: Optional[int] = Field(
        default=None,
        description="稳定时间 (秒)"
    )
    total_time: Optional[int] = Field(
        default=None,
        description="总时间 (秒)"
    )
    pt_count: Optional[int] = Field(
        default=None,
        description="数据点数量"
    )
    pv_sum_value: Optional[int] = Field(
        default=None,
        description="过程变量和"
    )
    pv_sum_squares: Optional[int] = Field(
        default=None,
        description="过程变量平方和"
    )
    mv_sum_value: Optional[int] = Field(
        default=None,
        description="操纵变量和"
    )

    mv_sum_squares: Optional[int] = Field(
        default=None,
        description="操纵变量平方和"
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
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "loop_name": "FIC101A流量控制回路",
                "tuning_method": "Lambda整定",
                "performance_score": 85.5,
                "auto_control_rate": 92.3,
                "stability_rate": 88.7,
                "auto_control_time": 78900,
                "stable_time": 75600,
                "total_time": 85400
            }
        }

    def __repr__(self) -> str:
        return f"<LoopEvaluation(id={self.id}, loop_name={self.loop_name}, method={self.tuning_method})>"