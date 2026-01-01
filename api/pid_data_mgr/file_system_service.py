import hashlib
import uuid
from typing import Set, Tuple, List, Optional
from datetime import datetime

from sqlmodel import Session

from api.pid_data_mgr.block_util import BlockUtil
from api.pid_data_mgr.file_meta_dao import FileMetaService
from api.pid_data_mgr.file_store_service import FileStoreService
from api.pid_data_mgr.file_db_models import *
from api.pid_data_mgr.file_api_schemas import *


class FileSystemService:

    @staticmethod
    def create_file(session: Session, request: CreateFileRequest) -> PIDDataFile:
        return FileMetaService.create_file(session, request)

    @staticmethod
    def upload_file_chunk(session: Session, request: UploadFileChunkRequest) -> Tuple[int, Set[int], str]:
        f = FileMetaService.get_file(session, request.upload_id)
        if not f:
            return 400, set(), f"上传编号{request.upload_id}不存在!"

        # 文件已经传输完成
        if f.status != FileStatus.UPLOADING:
            return 0, set(), f"文件{request.upload_id}已上传完成!"

        # 检查块编号
        blocks_count = BlockUtil.calc_blocks_count(f.total_size, f.block_size)
        if request.block_id >= blocks_count:
            return 400, set(), f"块编号{request.block_id}超出范围!"

        # 检查块大小
        expected_size = f.block_size
        # 最后一个块的大小可能不同
        if request.block_id == blocks_count - 1:
            expected_size = BlockUtil.calc_last_block_size(f.total_size, f.block_size)
        
        actual_size = len(request.data)
        if actual_size != expected_size:
            return 400, set(), f"块大小不匹配! 期望: {expected_size}, 实际: {actual_size}"

        # 校验MD5
        md5_hash = hashlib.md5(request.data).hexdigest()
        if md5_hash != request.md5:
            return 400, set(), f"MD5校验失败! 期望: {request.md5}, 实际: {md5_hash}"

        # 检查该块是否已经上传
        existing_block = FileMetaService.get_block(session, f.fid, request.block_id)
        
        if existing_block:
            # 块已存在，返回剩余块列表
            remaining_blocks = FileSystemService._get_remaining_blocks(session, f)
            return 0, remaining_blocks, "该块已上传!"

        # 保存文件块到磁盘
        try:
            block_name = str(uuid.uuid4())
            FileStoreService.write_block(f.fid, block_name, request.data)
        except Exception as e:
            return 500, set(), f"保存文件块失败: {str(e)}"

        # 保存块记录到数据库
        try:
            FileMetaService.write_block_meta(session, f.fid, request.block_id, block_name)
        except Exception as e:
            # 如果数据库保存失败，删除已保存的文件块
            FileStoreService.delete_block(f.fid, block_name)
            return 500, set(), f"保存块记录失败: {str(e)}"

        # 获取剩余未上传的块列表
        remaining_blocks = FileSystemService._get_remaining_blocks(session, f)

        # 如果所有块都已上传，更新文件状态
        if len(remaining_blocks) == 0:
            FileMetaService.mark_as(session, f.fid, FileStatus.UPLOADED)
            return 0, remaining_blocks, "所有块上传完成!"

        return 0, remaining_blocks, "块上传成功!"

    @staticmethod
    def _get_remaining_blocks(session: Session, file: PIDDataFile) -> Set[int]:
        """
        获取剩余未上传的块列表
        
        Args:
            session: 数据库会话
            file: 文件对象
            
        Returns:
            Set[int]: 剩余未上传的块编号集合
        """
        # 获取总块数
        total_block_ids = BlockUtil.build_block_list(file.total_size, file.block_size)
        
        # 获取已上传的块
        uploaded_block_objects = FileMetaService.get_blocks(session, file.fid)
        uploaded_block_ids = {block.block_id for block in uploaded_block_objects}
        
        # 返回未上传的块
        return total_block_ids - uploaded_block_ids

    @staticmethod
    def get_file_list(
        session: Session,
        file_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page_num: int = 1,
        page_size: int = 10
    ) -> Tuple[int, List[PIDDataFile]]:
        """
        获取文件列表
        
        Args:
            session: 数据库会话
            file_name: 文件名过滤
            start_time: 开始时间
            end_time: 结束时间
            page_num: 页码
            page_size: 每页大小
            
        Returns:
            Tuple[int, List[PIDDataFile]]: (总数, 文件列表)
        """
        return FileMetaService.get_file_list(
            session, file_name, start_time, end_time, page_num, page_size
        )

    @staticmethod
    def delete_file(session: Session, fid: int) -> Tuple[int, str]:
        """
        删除文件（逻辑删除，仅标记为DELETED状态）
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            Tuple[int, str]: (状态码, 消息)
        """
        # 检查文件是否存在
        file = FileMetaService.get_file_by_fid(session, fid)
        if not file:
            return 404, f"文件{fid}不存在!"
        
        # 检查文件是否已经被删除
        # TODO: 是否还要检查其他状态是否支持逻辑删除
        if file.status == FileStatus.DELETED:
            return 0, "ok"
        
        try:
            # 将文件状态标记为DELETED
            FileMetaService.mark_as(session, fid, FileStatus.DELETED)
            return 0, "ok"
        except Exception as e:
            return 500, f"删除文件失败: {str(e)}"