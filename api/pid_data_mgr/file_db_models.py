from enum import Enum
from typing import Optional
from datetime import datetime

from sqlmodel import SQLModel, Field
from sqlalchemy import Index, text


class FileStatus(str, Enum):
    """文件状态枚举"""
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    MERGED = "MERGED"
    CLEANED = "CLEANED"
    IMPORTED = "IMPORTED"
    MERGE_FAILED = "MERGE_FAILED"
    IMPORT_FAILED = "IMPORT_FAILED"
    DELETED = "DELETED"


class PIDDataFile(SQLModel, table=True):
    """
    回路数据文件表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能

    表名: pid_data_files
    """
    __tablename__ = "pid_data_files"  # 数据库表名
    # 表配置
    __table_args__ = (
        # 索引
        Index("idx_pid_data_files_upload_id", "upload_id"),
        Index("idx_pid_data_files_name", "name"),
        Index("idx_pid_data_files_create_time", "create_time"),

        # 表注释
        {"comment": "文件表"},
    )

    # 主键字段
    fid: Optional[int] = Field(
        default=None,
        primary_key=True,
        description="文件编号",
        sa_column_kwargs={"comment": "文件编号"}
    )

    # 必须字段
    upload_id: str = Field(
        description="文件上传编号(uuid)",
        max_length=36,
        nullable=False,
        sa_column_kwargs={
            "comment": "文件上传编号(uuid)",
            "nullable": False
        }
    )

    name: str = Field(
        description="文件名",
        max_length=255,
        nullable=False,
        sa_column_kwargs={
            "comment": "文件名",
            "nullable": False
        }
    )

    inner_name: str = Field(
        description="内部文件名(重命名)",
        max_length=255,
        nullable=False,
        sa_column_kwargs={
            "comment": "内部文件名(重命名)",
            "nullable": False
        }
    )

    total_size: int = Field(
        description="文件大小",
        nullable=False,
        sa_column_kwargs={
            "comment": "文件大小",
            "nullable": False
        }
    )

    block_size: int = Field(
        description="文件块大小",
        nullable=False,
        sa_column_kwargs={
            "comment": "文件块大小",
            "nullable": False
        }
    )

    # 可选字段
    file_type: Optional[str] = Field(
        default=None,
        description="文件类型",
        max_length=16,
        sa_column_kwargs={
            "comment": "文件类型",
            "nullable": True
        }
    )

    description: str = Field(
        default="",
        description="文件说明",
        max_length=255,
        sa_column_kwargs={
            "comment": "文件说明",
            "nullable": True,
            "server_default": text("''")
        }
    )

    imported_records: int = Field(
        default=0,
        description="导入记录数",
        nullable=False,
        sa_column_kwargs={
            "comment": "导入记录数",
            "nullable": False,
            "server_default": text("0")
        }
    )

    total_records: int = Field(
        default=0,
        description="总记录数",
        nullable=False,
        sa_column_kwargs={
            "comment": "总记录数",
            "nullable": False,
            "server_default": text("0")
        }
    )

    status: FileStatus = Field(
        default=FileStatus.UPLOADING,
        description="文件状态",
        sa_column_kwargs={
            "comment": "文件状态",
            "nullable": True,
            "server_default": text("'UPLOADING'")
        }
    )

    failed_reason: str = Field(
        default="",
        description="失败原因",
        max_length=512,
        sa_column_kwargs={
            "comment": "失败原因",
            "nullable": True,
            "server_default": text("''")
        }
    )

    create_time: datetime = Field(
        default_factory=datetime.now,
        description="创建时间",
        sa_column_kwargs={
            "comment": "创建时间",
            "nullable": False,
            "server_default": text("CURRENT_TIMESTAMP")
        }
    )

    host_port: Optional[str] = Field(
        default=None,
        description="执行者服务地址",
        max_length=36,
        sa_column_kwargs={
            "comment": "执行者服务地址",
            "nullable": True
        }
    )

    version: int = Field(
        default=0,
        description="执行者控制",
        sa_column_kwargs={
            "comment": "执行者控制",
            "nullable": False,
            "server_default": text("0")
        }
    )

    class Config:
        # 配置枚举值的JSON序列化
        json_encoders = {
            datetime: lambda v: v.isoformat() if v else None,
            FileStatus: lambda v: v.value if v else None,
        }


class PIDDataFileBlock(SQLModel, table=True):
    """
    回路数据文件块表模型 - SQLModel方式
    结合了Pydantic的数据验证和SQLAlchemy的ORM功能

    表名: pid_data_file_blocks
    """
    __tablename__ = "pid_data_file_blocks"  # 数据库表名
    __table_args__ =  {"comment": "PID文件块表"}

    fid: int = Field(
        primary_key=True,
        description="文件编号",
        sa_column_kwargs={"comment": "文件编号"}
    )

    block_id: int = Field(
        primary_key=True,
        description="文件块编号",
        sa_column_kwargs={"comment": "文件块编号"}
    )

    block_name: Optional[str] = Field(
        default=None,
        max_length=36,
        description="文件块名称(uuid)",
        sa_column_kwargs={"comment": "文件块名称(uuid)"}
    )
