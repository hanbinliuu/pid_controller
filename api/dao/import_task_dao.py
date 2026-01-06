 #!/usr/bin/env python3
"""
导入任务DAO
处理导入任务的数据库操作
"""

import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlmodel import Session, select

from api.bean.import_task import ImportTask
from api.bean.import_status import ImportStatus
from core.database.database import get_db_session

logger = logging.getLogger(__name__)


class ImportTaskDAO:
    """导入任务数据访问对象"""

    @staticmethod
    def create_task(task_id: str, total_count: int, file_name: str = "", file_size: int = 0, file_hash: str = "") -> bool:
        """
        创建新任务
        
        Args:
            task_id: 任务ID
            total_count: 总数量
            file_name: 文件名称
            file_size: 文件大小（字节）
            file_hash: 文件MD5哈希值
            
        Returns:
            bool: 是否创建成功
        """
        with get_db_session() as session:
            task = ImportTask(
                task_id=task_id,
                status=ImportStatus.PENDING.value,
                total_count=total_count,
                success_count=0,
                failed_count=0,
                current_index=0,
                error_messages="[]",
                file_name=file_name,
                file_size=file_size,
                file_hash=file_hash,
                start_time=None,
                end_time=None
            )
            
            session.add(task)
            session.commit()
            
            logger.info(f"创建导入任务: {task_id}, 总数: {total_count}, 文件: {file_name} ({file_size} bytes)")
            return True

    @staticmethod
    def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
        """
        根据任务ID获取任务（返回字典格式）
        
        Args:
            task_id: 任务ID
            
        Returns:
            Optional[Dict]: 任务字典，不存在返回None
        """
        with get_db_session() as session:
            statement = select(ImportTask).where(ImportTask.task_id == task_id)
            task = session.exec(statement).first()
            if not task:
                return None
            # 在会话内部直接转换为字典，避免会话关闭后对象分离
            return ImportTaskDAO.task_to_dict(task)

    @staticmethod
    def update_task_status(task_id: str, status: str, **kwargs) -> bool:
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            **kwargs: 其他要更新的字段
            
        Returns:
            bool: 是否更新成功
        """
        with get_db_session() as session:
            statement = select(ImportTask).where(ImportTask.task_id == task_id)
            task = session.exec(statement).first()
            
            if not task:
                logger.warning(f"任务不存在: {task_id}")
                return False
            
            # 更新状态
            task.status = status
            task.updated_at = datetime.now()
            
            # 更新其他字段
            for key, value in kwargs.items():
                if hasattr(task, key):
                    setattr(task, key, value)
            
            session.add(task)
            session.commit()
            
            logger.debug(f"更新任务状态: {task_id}, status={status}")
            return True

    @staticmethod
    def increment_progress(task_id: str, success: bool, error_msg: Optional[Dict[str, Any]] = None) -> bool:
        """
        增加任务进度
        
        Args:
            task_id: 任务ID
            success: 是否成功
            error_msg: 错误信息（失败时提供）
            
        Returns:
            bool: 是否更新成功
        """
        with get_db_session() as session:
            statement = select(ImportTask).where(ImportTask.task_id == task_id)
            task = session.exec(statement).first()
            
            if not task:
                logger.warning(f"任务不存在: {task_id}")
                return False
            
            # 更新计数
            task.current_index += 1
            if success:
                task.success_count += 1
            else:
                task.failed_count += 1
                
                # 添加错误信息（只保留最近50条）
                if error_msg:
                    try:
                        error_list = json.loads(task.error_messages) if task.error_messages else []
                        error_list.append(error_msg)
                        # 只保留最近50条错误
                        task.error_messages = json.dumps(error_list[-50:], ensure_ascii=False)
                    except json.JSONDecodeError:
                        task.error_messages = json.dumps([error_msg], ensure_ascii=False)
            
            task.updated_at = datetime.now()
            
            session.add(task)
            session.commit()
            
            return True

    @staticmethod
    def get_all_tasks(limit: int = 100) -> List[Dict[str, Any]]:
        """
        获取所有任务（最近的N条，返回字典格式）
        
        Args:
            limit: 返回数量限制
            
        Returns:
            List[Dict]: 任务列表
        """
        with get_db_session() as session:
            statement = select(ImportTask).order_by(ImportTask.created_at.desc()).limit(limit)
            tasks = session.exec(statement).all()
            # 在会话内部直接转换为字典列表，避免会话关闭后对象分离
            return [ImportTaskDAO.task_to_dict(task) for task in tasks]

    @staticmethod
    def delete_old_tasks(keep_days: int = 7) -> int:
        """
        删除旧任务
        
        Args:
            keep_days: 保留天数
            
        Returns:
            int: 删除的任务数量
        """
        from datetime import timedelta
        
        with get_db_session() as session:
            cutoff_date = datetime.now() - timedelta(days=keep_days)
            
            statement = select(ImportTask).where(
                ImportTask.created_at < cutoff_date,
                ImportTask.status.in_([ImportStatus.COMPLETED.value, ImportStatus.FAILED.value])
            )
            old_tasks = session.exec(statement).all()
            
            count = len(old_tasks)
            for task in old_tasks:
                session.delete(task)
            
            session.commit()
            
            logger.info(f"删除 {count} 个旧任务（{keep_days}天前）")
            return count

    @staticmethod
    def task_to_dict(task: ImportTask) -> Dict[str, Any]:
        """
        将任务对象转换为字典
        
        Args:
            task: 任务对象
            
        Returns:
            Dict: 任务字典
        """
        try:
            error_messages = json.loads(task.error_messages) if task.error_messages else []
            # 只返回最近10条错误
            error_messages = error_messages[-10:]
        except json.JSONDecodeError:
            error_messages = []
        
        progress_percentage = round(
            (task.current_index / task.total_count * 100) if task.total_count > 0 else 0,
            2
        )
        
        return {
            "task_id": task.task_id,
            "status": task.status,
            "total_count": task.total_count,
            "success_count": task.success_count,
            "failed_count": task.failed_count,
            "current_index": task.current_index,
            "progress_percentage": progress_percentage,
            "error_messages": error_messages,
            # 文件信息
            "file_info": {
                "file_name": task.file_name,
                "file_size": task.file_size,
                "file_hash": task.file_hash
            },
            "start_time": task.start_time.isoformat() if task.start_time else None,
            "end_time": task.end_time.isoformat() if task.end_time else None,
            "created_at": task.created_at.isoformat() if task.created_at else None
        }
