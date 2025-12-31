# --------------
# PID数据文件管理 API 接口
# --------------
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session
import uuid

from core.database.database import get_db
from api.pid_data_mgr.pid_data_file_request import *


pid_data_file_router = APIRouter(tags=["PID文件上传"])

@pid_data_file_router.post("/files", summary="创建文件", response_model=CreateFileResponse)
async def create_file(request: CreateFileRequest, session: Session = Depends(get_db)):
    """
    创建文件上传任务
    """
    file_name = request.file_name.strip()
    request.file_name = file_name

    try:
        # 生成 upload_id
        upload_id = str(uuid.uuid4())

        # 计算分块信息
        block_size = 4194304  # 4MB
        total_blocks = (request.file_size + block_size - 1) // block_size
        block_list = list(range(total_blocks))

        # 返回响应
        return CreateFileResponse(
            code=0,
            message="ok",
            upload_id=upload_id,
            block_size=block_size,
            block_list=block_list
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"创建文件失败: {str(e)}"
        )