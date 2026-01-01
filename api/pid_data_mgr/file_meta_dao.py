import uuid
from datetime import datetime

from typing import Optional, List, Tuple

from sqlmodel import Session, select, func, update

from api.pid_data_mgr.file_db_models import PIDDataFile, PIDDataFileBlock, FileStatus
from api.pid_data_mgr.file_api_schemas import CreateFileRequest
from api.pid_data_mgr.file_settings import settings

class FileMetaService:

    @staticmethod
    def create_file(session: Session, request: CreateFileRequest) -> PIDDataFile:
        # 生成上传ID
        upload_id = str(uuid.uuid4())

        f = PIDDataFile(
            # 必填字段
            upload_id=upload_id,
            name=request.file_name,
            inner_name=request.file_name,
            total_size=request.file_size,
            block_size=settings.chunk_size,
            description=request.desc or "",

            # 设置默认值
            status=FileStatus.UPLOADING,
            create_time=datetime.now(),  # 创建时间
            failed_reason="",
            file_type="csv",
            host_port=None,
            version = 0,
        )

        # 添加到会话并提交
        session.add(f)
        session.commit()
        session.refresh(f)

        return f

    @staticmethod
    def get_file(session: Session, upload_id: str) -> PIDDataFile:
        """
        根据上传编号获取文件信息
        """
        stmt = select(PIDDataFile).where(PIDDataFile.upload_id == upload_id)
        return session.exec(stmt).first()

    @staticmethod
    def get_block(session: Session, fid: int, block_id: int) -> Optional[PIDDataFileBlock]:
        """
        检查文件块是否已经上传
        
        Args:
            session: 数据库会话
            fid: 文件编号
            block_id: 块编号
            
        Returns:
            Optional[PIDDataFileBlocks]: 如果块已存在返回块对象，否则返回None
        """
        stmt = select(PIDDataFileBlock).where(
            PIDDataFileBlock.fid == fid,
            PIDDataFileBlock.block_id == block_id
        )
        return session.exec(stmt).first()

    @staticmethod
    def get_blocks(session: Session, fid: int) -> List[PIDDataFileBlock]:
        """
        获取文件已上传的块列表
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            List[PIDDataFileBlocks]: 已上传的块对象列表
        """
        stmt = select(PIDDataFileBlock).where(PIDDataFileBlock.fid == fid)
        return list(session.exec(stmt).all())

    @staticmethod
    def write_block_meta(session: Session, fid: int, block_id: int, block_name: str) -> None:
        """
        保存块记录到数据库
        
        Args:
            session: 数据库会话
            fid: 文件编号
            block_id: 块编号
            block_name: 块存储名称
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        block_record = PIDDataFileBlock(
            fid=fid,
            block_id=block_id,
            block_name=block_name
        )
        session.add(block_record)
        session.commit()

    @staticmethod
    def mark_as(session: Session, fid: int, status: FileStatus) -> None:
        """
        更新文件状态
        
        Args:
            session: 数据库会话
            fid: 文件编号
            status: 新的文件状态
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        stmt = update(PIDDataFile).where(PIDDataFile.fid == fid).values(status=status)
        session.exec(stmt)
        session.commit()

    @staticmethod
    def get_file_by_fid(session: Session, fid: int) -> Optional[PIDDataFile]:
        """
        根据文件编号获取文件信息
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            Optional[PIDDataFile]: 文件对象，如果不存在返回None
        """
        stmt = select(PIDDataFile).where(PIDDataFile.fid == fid)
        return session.exec(stmt).first()

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
            file_name: 文件名过滤（模糊查询）
            start_time: 开始时间
            end_time: 结束时间
            page_num: 页码，从1开始
            page_size: 每页大小
            
        Returns:
            Tuple[int, List[PIDDataFile]]: (总数, 文件列表)
        """
        # 构建查询
        stmt = select(PIDDataFile)
        
        # 添加过滤条件
        if file_name:
            stmt = stmt.where(PIDDataFile.name.like(f"%{file_name}%"))
        
        if start_time:
            stmt = stmt.where(PIDDataFile.create_time >= start_time)
        
        if end_time:
            stmt = stmt.where(PIDDataFile.create_time <= end_time)
        
        # 查询总数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.exec(count_stmt).one()
        
        # 按创建时间降序排序
        stmt = stmt.order_by(PIDDataFile.create_time.desc())
        
        # 分页
        offset = (page_num - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        
        # 执行查询
        files = list(session.exec(stmt).all())
        
        return total, files