# --------------
# PID数据文件管理 请求模型
# --------------
from typing import Set, Optional, List

from pydantic import BaseModel, Field, field_validator
from file_settings import settings


class CreateFileRequest(BaseModel):
    """创建文件请求模型"""
    file_name: str = Field(
        ...,
        description="文件名",
        min_length=5,
        max_length=255,
        examples=["test.csv"]
    )

    file_size: int = Field(
        ...,
        description="文件大小（字节）",
        gt=0,
    )

    desc: str = Field(
        default="",
        description="文件描述",
        max_length=255,
    )

    @field_validator('file_name')
    def validate_filename(cls, v):
        """验证文件名有效性"""
        # 去除首尾空格
        v = v.strip()
        
        if not v:
            raise ValueError('文件名不能为空')

        # 检查文件扩展名必须是 .csv
        if not v.endswith('.csv'):
            raise ValueError('文件名扩展名必须为 .csv')

        return v

    @field_validator('file_size')
    def validate_file_size(cls, v):
        """验证文件大小"""
        if v <= 0:
            raise ValueError('文件大小必须大于0')

        # 可选: 限制最大文件大小
        max_size = settings.max_file_size
        if v > max_size:
            raise ValueError(f'文件大小不能超过 {max_size / (1024 ** 3):.1f} GB')

        return v

    class Config:
        # 配置示例
        schema_extra = {
            "example": {
                "file_name": "test.csv",
                "file_size": 100,
                "desc": "Pipeline as Code"
            }
        }


class CreateFileResponse(BaseModel):
    """创建文件响应模型"""
    code: int = Field(..., description="返回码，0表示成功")
    message: str = Field(..., description="错误消息")
    upload_id: str = Field(..., description="UUID，用于标识一个文件")
    block_size: int = Field(..., description="每次上传文件块大小（字节）")
    block_list: Set[int] = Field(..., description="文件的块编号列表")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "ok",
                "upload_id": "4dc26094-d775-4025-bd18-79e341d1346d",
                "block_size": 4194304,
                "block_list": [0, 1, 2, 3, 4]
            }
        }


class UploadFileChunkRequest(BaseModel):
    """文件块上传请求模型"""

    # 数据块 MD5
    md5: str

    # 数据块编号
    block_id: int  # Python中用int，对应Java的long

    # 上传编号
    upload_id: str

    # 数据块内容 - 可选，因为FastAPI中文件通常通过UploadFile处理
    data: Optional[bytes] = None


class UploadFileChunkResponse(CreateFileResponse):
    pass


class FileItemResponse(BaseModel):
    """文件列表项响应模型"""
    fid: int = Field(..., description="文件编号")
    name: str = Field(..., description="文件名")
    type: str = Field(..., description="文件类型")
    size: int = Field(..., description="文件大小（字节）")
    create_time: str = Field(..., description="创建时间")
    description: str = Field(..., description="文件描述")

    class Config:
        json_schema_extra = {
            "example": {
                "fid": 10010,
                "name": "hello.csv",
                "type": "csv",
                "size": 102400,
                "create_time": "2023-02-07 15:20:49",
                "description": ""
            }
        }


class FileListData(BaseModel):
    """文件列表数据模型"""
    total: int = Field(..., description="总数")
    files: List[FileItemResponse] = Field(..., description="文件列表")


class FileListResponse(BaseModel):
    """文件列表响应模型"""
    code: int = Field(..., description="返回码，0表示成功")
    message: str = Field(..., description="消息")
    data: FileListData = Field(..., description="响应数据")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "ok",
                "data": {
                    "total": 100,
                    "files": [
                        {
                            "fid": 10010,
                            "name": "hello.csv",
                            "type": "csv",
                            "size": 102400,
                            "create_time": "2023-02-07 15:20:49",
                            "description": ""
                        }
                    ]
                }
            }
        }


class DeleteFileResponse(BaseModel):
    """删除文件响应模型"""
    code: int = Field(..., description="返回码，0表示成功")
    message: str = Field(..., description="消息")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "ok"
            }
        }