import uuid
from datetime import datetime

from typing import Optional, List, Tuple

from sqlmodel import Session, select, func, update, delete

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
        stmt = select(PIDDataFileBlock).where(PIDDataFileBlock.fid == fid).order_by(PIDDataFileBlock.block_id)
        return list(session.exec(stmt).all())

    @staticmethod
    def count_blocks(session: Session, fid: int) -> int:
        """
        根据文件编号查询已上传的块数量
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            int: 已上传的块数量
        """
        stmt = select(func.count()).where(PIDDataFileBlock.fid == fid)
        return session.exec(stmt).one()

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
    def mark_as(session: Session, fid: int, status: FileStatus, reason: str = "") -> None:
        """
        更新文件状态
        
        Args:
            session: 数据库会话
            fid: 文件编号
            status: 新的文件状态
            reason: 失败原因
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        stmt = update(PIDDataFile).where(PIDDataFile.fid == fid).values(status=status, failed_reason=reason)
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
        
        # 过滤掉UPLOADING和DELETED状态的文件
        stmt = stmt.where(
            PIDDataFile.status != FileStatus.UPLOADING,
            PIDDataFile.status != FileStatus.DELETED
        )
        
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

    @staticmethod
    def delete_file_blocks(session: Session, fid: int):
        """
        删除文件的所有块记录
        
        Args:
            session: 数据库会话
            fid: 文件编号

        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        # 直接使用DELETE语句删除所有块记录
        stmt = delete(PIDDataFileBlock).where(PIDDataFileBlock.fid == fid)
        session.exec(stmt)
        session.commit()

    @staticmethod
    def delete_file(session: Session, fid: int) -> bool:
        """
        删除文件记录（标记为已删除状态）
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            bool: 删除成功返回True，文件不存在返回False
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        # 先查询文件是否存在
        file = FileMetaService.get_file_by_fid(session, fid)
        if not file:
            return False

        # 物理删除文件记录
        session.delete(file)
        session.commit()
        return True

    @staticmethod
    def delete_file_completely(session: Session, fid: int) -> bool:
        """
        完全删除文件及其所有块记录（物理删除）
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            bool: 删除成功返回True，文件不存在返回False
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        # 先查询文件是否存在
        file = FileMetaService.get_file_by_fid(session, fid)
        if not file:
            return False
        
        # 先删除所有块记录
        FileMetaService.delete_file_blocks(session, fid)
        
        # 再删除文件记录
        session.delete(file)
        session.commit()
        return True

    @staticmethod
    def set_host_port(session: Session, fid: int, host_port: str) -> bool:
        """
        设置文件的操作实例IP端口，并递增版本号
        用于记录当前执行操作的实例信息
        使用版本号进行乐观锁控制，防止并发冲突
        
        Args:
            session: 数据库会话
            fid: 文件编号
            host_port: 实例的IP端口，格式如 "192.168.1.100:8001"
            
        Returns:
            bool: 设置成功返回True，文件不存在或版本冲突返回False
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        # 先查询文件是否存在并获取当前version
        file = FileMetaService.get_file_by_fid(session, fid)
        if not file:
            return False
        
        current_version = file.version
        
        # 更新host_port并递增version，同时检查version是否匹配（乐观锁）
        stmt = update(PIDDataFile).where(
            PIDDataFile.fid == fid,
            PIDDataFile.version == current_version
        ).values(
            host_port=host_port,
            version=current_version + 1
        )
        result = session.exec(stmt)
        session.commit()
        
        # 检查是否有行被更新，如果没有则说明版本冲突
        return result.rowcount > 0

    @staticmethod
    def reset_host_port(session: Session, fid: int) -> bool:
        """
        清除文件的操作实例IP端口和版本号
        用于释放文件的实例绑定
        
        Args:
            session: 数据库会话
            fid: 文件编号
            
        Returns:
            bool: 清除成功返回True，文件不存在返回False
            
        Raises:
            Exception: 数据库操作失败时抛出异常
        """
        # 先查询文件是否存在
        file = FileMetaService.get_file_by_fid(session, fid)
        if not file:
            return False
        
        # 清除host_port并重置version为0
        stmt = update(PIDDataFile).where(PIDDataFile.fid == fid).values(
            host_port=None
        )
        session.exec(stmt)
        session.commit()
        return True

    @staticmethod
    def get_files_by_status(session: Session, status: FileStatus) -> List[PIDDataFile]:
        """
        根据文件状态查询所有文件
        
        Args:
            session: 数据库会话
            status: 文件状态
            
        Returns:
            List[PIDDataFile]: 文件列表
        """
        stmt = select(PIDDataFile).where(PIDDataFile.status == status)
        return list(session.exec(stmt).all())

    @staticmethod
    def select_expired_uploading_files(session: Session) -> List[PIDDataFile]:
        """
        查询过期的上传中文件
        过期时间由 settings.retention_hours 配置（默认7天）
        
        Args:
            session: 数据库会话
            
        Returns:
            List[PIDDataFile]: 过期的上传中文件列表
        """
        from datetime import timedelta
        
        # 计算最早的允许时间（当前时间 - 保留时长）
        earliest_time = datetime.now() - timedelta(hours=settings.retention_hours)
        
        # 查询状态为UPLOADING且创建时间早于最早允许时间的文件
        stmt = select(PIDDataFile).where(
            PIDDataFile.status == FileStatus.UPLOADING,
            PIDDataFile.create_time < earliest_time
        )
        
        return list(session.exec(stmt).all())

    @staticmethod
    def count_files_by_status(session: Session, statuses: List[FileStatus]) -> int:
        """
        查询满足指定状态的文件记录数量
        多个状态之间是或的关系
        
        Args:
            session: 数据库会话
            statuses: 文件状态列表
            
        Returns:
            int: 满足条件的文件记录数量
        """
        if not statuses:
            return 0
        
        # 使用 in_ 操作符查询多个状态
        stmt = select(func.count()).where(PIDDataFile.status.in_(statuses))
        return session.exec(stmt).one()

    @staticmethod
    def set_import_progress(session: Session, fid: int, imported_records: int, total_records: int) -> bool:
        """
        设置文件导入进度

        Args:
            session: 数据库会话
            fid: 文件编号
            imported_records: 已导入记录数
            total_records: 总记录数

        Returns:
            bool: 更新成功返回True，文件不存在返回False
        """
        try:
            # 更新导入进度字段
            stmt = update(PIDDataFile).where(PIDDataFile.fid == fid).values(
                imported_records=imported_records,
                total_records=total_records
            )
            result = session.exec(stmt)
            session.commit()
            return result.rowcount > 0
        except Exception:
            return False
