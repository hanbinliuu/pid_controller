# --------------
# PID数据文件管理 API 接口
# --------------
from fastapi import APIRouter, Depends, UploadFile, File, Path, Query, Request, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session
from datetime import datetime
import os

from api.pid_data_mgr.block_util import BlockUtil
from api.pid_data_mgr.file_meta_dao import FileMetaService
from api.pid_data_mgr.file_system_service import FileSystemService
from api.pid_data_mgr.file_store_service import FileStoreService
from api.pid_data_mgr.file_db_models import FileStatus
from core.config import Config as config
from core.database.database import get_db
from api.pid_data_mgr.file_api_schemas import *
from api.pid_data_mgr.file_settings import settings


# 设置存储目录
settings.storage_dir = config.PID_DATA_FILE_DIR

pid_data_file_router = APIRouter(prefix="/api/v1/history/data")

@pid_data_file_router.post("/files", summary="创建文件", response_model=CreateFileResponse)
async def create_file(request: CreateFileRequest, session: Session = Depends(get_db)):
    """
    创建文件上传任务
    """
    try:
        f = FileSystemService.create_file(session, request)
        
        # 返回响应
        return CreateFileResponse(
            upload_id=f.upload_id,
            block_size=f.block_size,
            block_list=BlockUtil.build_block_list(f.total_size, f.block_size)
        )
    except Exception as e:
        # 数据库操作失败，返回错误响应
        raise HTTPException(status_code=500, detail=f"创建文件失败: {str(e)}")


@pid_data_file_router.put("/files", summary="上传文件块", response_model=UploadFileChunkResponse)
async def upload_file_chunk(
        request: Request,
        upload_id: str = Query(..., description="上传编号"),
        block_id: int = Query(..., description="文件块编号"),
        md5: str = Query(..., description="文件块 MD5"),
        session: Session = Depends(get_db)):
    # 验证上传编号
    upload_id = upload_id.strip()
    if len(upload_id) != settings.upload_id_length:
        raise HTTPException(status_code=400, detail="上传编号错误, 上传编号长度错误")

    # 验证文件块编号
    if block_id < 0:
        raise HTTPException(status_code=400, detail="文件块编号错误, 必须大于等于0!")

    # 验证 MD5
    md5 = md5.strip()
    if not md5:
        raise HTTPException(status_code=400, detail="MD5校验码不能为空")

    if len(md5) != settings.md5_sum_length:
        raise HTTPException(status_code=400, detail=f"MD5校验码长度错误, 必须为{settings.md5_sum_length}个字节!")

    # 从请求体读取字节数据
    file_chunk = await request.body()

    # 创建 UploadFileRequest 对象
    upload_request = UploadFileChunkRequest(
        md5=md5,
        block_id=block_id,
        upload_id=upload_id,
        data=file_chunk
    )

    code, block_list, message = FileSystemService.upload_file_chunk(session, upload_request)
    if code != 0:
        raise HTTPException(status_code=500, detail=f"上传文件块失败: {message}")

    return UploadFileChunkResponse(
        upload_id=upload_id,
        block_size=settings.chunk_size,
        block_list=block_list
    )


@pid_data_file_router.get("/files", summary="获取文件列表", response_model=FileListData)
async def get_file_list(
        file_name: Optional[str] = Query(None, description="文件名过滤"),
        start_time: Optional[str] = Query(None, description="开始时间，格式: 2023-02-07T10:03:00"),
        end_time: Optional[str] = Query(None, description="结束时间，格式: 2023-02-07T14:03:00"),
        page_num: int = Query(1, ge=1, description="页码，从1开始"),
        page_size: int = Query(10, ge=1, le=100, description="每页大小，最大1，最大100"),
        session: Session = Depends(get_db)):
    """
    获取文件列表
    
    查询参数：
    - file_name: 文件名过滤（模糊查询）
    - start_time: 开始时间
    - end_time: 结束时间
    - page_num: 页码，默认1
    - page_size: 每页大小，默认10
    """
    try:
        # 转换时间字符串为 datetime 对象
        start_dt = None
        end_dt = None
        
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time)
            except ValueError:
                raise HTTPException(status_code=400, detail="开始时间格式错误，请使用 ISO 8601 格式，如: 2023-02-07T10:03:00")
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time)
            except ValueError:
                raise HTTPException(status_code=400, detail="结束时间格式错误，请使用 ISO 8601 格式，如: 2023-02-07T14:03:00")
        
        # 验证时间范围：start_time 必须小于 end_time
        if start_dt and end_dt and start_dt >= end_dt:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")
        
        # 调用服务层获取文件列表
        total, files = FileSystemService.get_file_list(
            session=session,
            file_name=file_name,
            start_time=start_dt,
            end_time=end_dt,
            page_num=page_num,
            page_size=page_size
        )
        
        # 转换为响应模型
        file_items = [
            FileItem(
                fid=f.fid,
                name=f.name,
                size=f.total_size,
                imported_records=f.imported_records,
                total_records=f.total_records,
                status=FileStatus(f.status).name,
                failed_reason=f.failed_reason or "",
                create_time=f.create_time.strftime("%Y-%m-%d %H:%M:%S"),
                description=f.description or ""
            )
            for f in files
        ]

        return FileListData(
            total=total,
            files=file_items
        )
    except Exception as e:
        # 异常处理
        raise HTTPException(status_code=500, detail=f"查询文件列表失败: {str(e)}")


@pid_data_file_router.delete("/files/{fid}", summary="删除文件", response_model=str)
async def delete_file(
        fid: int = Path(..., description="文件编号"),
        session: Session = Depends(get_db)):
    """
    删除文件（逻辑删除，仅标记为DELETED状态）
    
    参数：
    - fid: 文件编号
    """
    code, message = FileSystemService.delete_file(session, fid)
    if code != 0:
        raise HTTPException(status_code=500, detail=f"删除文件失败: {message}")

    return "删除文件成功"


@pid_data_file_router.get("/files/{fid}", summary="下载文件")
async def download_file(
        fid: int = Path(..., description="文件编号"),
        session: Session = Depends(get_db)):
    """
    下载文件，支持HTTP Range请求
    
    参数：
    - fid: 文件编号
    
    限制：
    - 只支持已合并文件下载
    - 不支持UPLOADING和DELETED状态的文件下载
    """
    # 获取文件信息
    file = FileSystemService.get_file(session, fid)
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    # 检查文件状态
    if file.status == FileStatus.UPLOADING:
        raise HTTPException(status_code=400, detail="文件正在上传中，暂不支持下载")
    
    if file.status == FileStatus.DELETED:
        raise HTTPException(status_code=410, detail="文件已被删除")
    
    if file.status == FileStatus.UPLOADED:
        raise HTTPException(status_code=400, detail="只支持已合并的文件下载")
    
    # 获取合并后的文件路径
    merged_file_path = FileStoreService.get_block_file_path(fid, file.upload_id)
    
    # 检查文件是否存在
    if not os.path.exists(merged_file_path):
        raise HTTPException(status_code=404, detail="合并文件不存在")
    
    # 使用 FileResponse 自动支持 HTTP Range
    return FileResponse(
        path=merged_file_path,
        filename=file.name,
        media_type="application/octet-stream",
        headers={
            "Accept-Ranges": "bytes"
        }
    )

@pid_data_file_router.get("/reimport/files/{fid}", summary="重新导入文件")
async def reimport_file(
        fid: int = Path(..., description="文件编号"),
        session: Session = Depends(get_db)):
    """
    重新导入文件, 将文件从 IMPORT_FAILED 状态设置为 CLEANED 状态

    参数：
    - fid: 文件编号
    """
    # 获取文件信息
    file = FileSystemService.get_file(session, fid)
    if not file:
        raise HTTPException(status_code=404, detail="文件不存在")

    if file.status != FileStatus.IMPORT_FAILED:
        raise HTTPException(status_code=400, detail="文件状态不是 IMPORT_FAILED，无法重新导入")

    FileMetaService.mark_as(session, fid, FileStatus.CLEANED)

    return "完成文件状态设置"