#!/usr/bin/env python3
"""
导入任务Bean
存储批量导入任务的状态信息
"""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import SQLModel, Field, Column, JSON
from sqlalchemy import Text, Index
from api.bean.import_status import ImportStatus


class ImportTask(SQLModel, table=True):
    """导入任务表"""
    __tablename__ = "import_task"
    # 表配置
    __table_args__ = (
        # 索引
        Index("idx_task_id", "task_id"),
        # 表注释
        {"comment": "回路导入状态表"},
    )

    id: Optional[str] = Field(default_factory=lambda: str(uuid4()), primary_key=True, description="主键ID")
    task_id: str = Field(index=True, unique=True, max_length=64, description="任务ID（UUID）")
    status: str = Field(default=ImportStatus.PENDING.value, max_length=20, description="任务状态：pending/running/completed/failed（参考ImportStatus枚举）")
    total_count: int = Field(default=0, description="总回路数量")
    success_count: int = Field(default=0, description="成功数量")
    failed_count: int = Field(default=0, description="失败数量")
    current_index: int = Field(default=0, description="当前处理索引")
    error_messages: str = Field(default="[]", sa_column=Column(Text), description="错误信息列表（JSON格式）")
    # 文件信息字段
    file_name: str = Field(default="", max_length=255, description="上传的文件名")
    file_size: int = Field(default=0, description="文件大小（字节）")
    file_hash: str = Field(default="", max_length=64, description="文件MD5哈希值")
    start_time: Optional[datetime] = Field(default=None, description="开始时间")
    end_time: Optional[datetime] = Field(default=None, description="结束时间")
    duration: Optional[float] = Field(default=0.0, description="耗时（秒）")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    updated_at: datetime = Field(default_factory=datetime.now, description="更新时间")

    class Config:
        json_schema_extra = {
            "example": {
                "task_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "running",
                "total_count": 100,
                "success_count": 80,
                "failed_count": 5,
                "current_index": 85,
                "duration": 12.34
            }
        }
