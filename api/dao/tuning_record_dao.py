#!/usr/bin/env python3
"""
DAO层 - 数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc

from api.bean.loop_info import LoopInfo
from api.bean.tuning_record import TuningRecord

logger = logging.getLogger(__name__)


class TuningRecordDAO:
    """整定记录DAO"""
    
    @staticmethod
    def create(db: Session, record_data: Dict[str, Any]) -> TuningRecord:
        """
        创建整定记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            record_data: 记录数据字典
        
        Returns:
            TuningRecord: 创建的记录对象
        """
        try:
            # SQLModel自动进行数据验证
            record = TuningRecord(**record_data)

            db.add(record)
            db.commit()
            db.refresh(record)
            
            logger.info(f"创建整定记录成功: ID={record.id}")
            return record
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, record_id: str) -> Optional[TuningRecord]:
        """
        根据ID查询记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            record_id: 记录ID
        
        Returns:
            Optional[TuningRecord]: 记录对象，不存在则返回None
        """
        # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
        statement = select(TuningRecord).where(TuningRecord.id == record_id)
        return db.exec(statement).first()
    
    @staticmethod
    def query_list(
        db: Session,
        device_uri: Optional[str] = None,
        loop_type: Optional[str] = None,
        loop_name: Optional[str] = None,
        tuning_method: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询整定记录列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选
            tuning_method: 整定方法筛选
            start_time: 开始时间
            end_time: 结束时间
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(TuningRecord,LoopInfo.loop_name,LoopInfo.loop_type,LoopInfo.description).join(LoopInfo, TuningRecord.loop_uri == LoopInfo.loop_uri, isouter=True)
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            if loop_type:
                statement = statement.where(LoopInfo.loop_type == loop_type)
            if device_uri:
                statement = statement.where(LoopInfo.loop_path .like(f"%{device_uri}%"))
            # 整定方法筛选（精确匹配）
            if tuning_method:
                statement = statement.where(TuningRecord.tuning_method == tuning_method)
            
            # 时间范围筛选
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    statement = statement.where(TuningRecord.tuning_time >= start_dt)
                except ValueError:
                    logger.warning(f"开始时间格式错误: {start_time}")
            
            if end_time:
                try:
                    # 结束时间包含当天的23:59:59
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    statement = statement.where(TuningRecord.tuning_time <= end_dt)
                except ValueError:
                    logger.warning(f"结束时间格式错误: {end_time}")
            
            # 按整定时间倒序排列
            statement = statement.order_by(desc(TuningRecord.tuning_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(TuningRecord).join(LoopInfo, TuningRecord.loop_uri == LoopInfo.loop_uri)
            # 回路名称筛选（模糊匹配）
            if loop_name:
                count_statement = count_statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            if loop_type:
                count_statement = count_statement.where(LoopInfo.loop_type == loop_type)
            if device_uri:
                count_statement = count_statement.where(LoopInfo.loop_path .like(f"%{device_uri}%"))
            if tuning_method:
                count_statement = count_statement.where(TuningRecord.tuning_method == tuning_method)
            # 时间范围筛选
            if start_time and start_time.strip():
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    count_statement = count_statement.where(TuningRecord.tuning_time >= start_dt)
                except ValueError:
                    logger.warning(f"开始时间格式错误: {start_time}")


            if end_time and end_time.strip():
                try:
                    # 结束时间包含当天的23:59:59
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    count_statement = count_statement.where(TuningRecord.tuning_time <= end_dt)
                except ValueError:
                    logger.warning(f"结束时间格式错误: {end_time}")
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            record_rows = db.exec(statement).all()
            records = []
            for row in record_rows:
                record={
                    "id": row.TuningRecord.id,
                    "loop_uri": row.TuningRecord.loop_uri,
                    "loop_name": row.loop_name,
                    "loop_type": row.loop_type,
                    "loop_status": row.TuningRecord.loop_status,
                    "description": row.description,
                    "tuning_method": row.TuningRecord.tuning_method,
                    "tuning_time": row.TuningRecord.tuning_time,
                    "operator": row.TuningRecord.operator,
                    "status": row.TuningRecord.status,
                    "before_params": row.TuningRecord.before_params,
                    "after_params": row.TuningRecord.after_params,
                    "remark": row.TuningRecord.remark,
                    "created_time": row.TuningRecord.created_time,
                    "updated_time": row.TuningRecord.updated_time
                }
                records.append(record)


            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询整定记录成功，总数: {total}, 当前页: {page_no}")
            
            return {
                "records": records,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
            }
            
        except Exception as e:
            logger.error(f"查询整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update(db: Session, record_id: str, update_data: Dict[str, Any]) -> Optional[TuningRecord]:
        """
        更新整定记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            record_id: 记录ID
            update_data: 更新数据字典
        
        Returns:
            Optional[TuningRecord]: 更新后的记录对象
        """
        try:
            # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
            statement = select(TuningRecord).where(TuningRecord.id == record_id)
            record = db.exec(statement).first()
            
            if not record:
                logger.warning(f"未找到ID为 {record_id} 的记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            
            # 更新updated_at
            record.updated_time = datetime.now()
            
            db.add(record)
            db.commit()
            db.refresh(record)
            
            logger.info(f"更新整定记录成功: ID={record_id}")
            return record
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, record_id: str) -> bool:
        """
        删除整定记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            record_id: 记录ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
            statement = select(TuningRecord).where(TuningRecord.id == record_id)
            record = db.exec(statement).first()
            
            if not record:
                logger.warning(f"未找到ID为 {record_id} 的记录")
                return False
            
            db.delete(record)
            db.commit()
            
            logger.info(f"删除整定记录成功: ID={record_id}, 回路={record.loop_uri}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_loop_uri(db: Session, loop_uri: str, limit: int = 10) -> List[TuningRecord]:
        """
        根据回路URI查询历史记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            limit: 返回记录数量限制
        
        Returns:
            List[TuningRecord]: 记录列表
        """
        statement = select(TuningRecord).where(
            TuningRecord.loop_uri == loop_uri
        ).order_by(
            desc(TuningRecord.tuning_time)
        ).limit(limit)
        
        return db.exec(statement).all()
    
    @staticmethod
    def get_statistics(db: Session) -> Dict[str, Any]:
        """
        获取统计信息 - SQLModel方式
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict: 统计信息
        """
        try:
            # 总记录数
            total_count = db.exec(select(func.count()).select_from(TuningRecord)).one()
            
            # 按整定方法统计
            method_statement = select(
                TuningRecord.tuning_method,
                func.count(TuningRecord.id).label('count')
            ).group_by(TuningRecord.tuning_method)
            method_stats = db.exec(method_statement).all()
            
            # 按状态统计
            status_statement = select(
                TuningRecord.status,
                func.count(TuningRecord.id).label('count')
            ).group_by(TuningRecord.status)
            status_stats = db.exec(status_statement).all()
            
            return {
                "total_count": total_count,
                "method_statistics": {item[0]: item[1] for item in method_stats},
                "status_statistics": {item[0]: item[1] for item in status_stats}
            }
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {str(e)}")
            raise
