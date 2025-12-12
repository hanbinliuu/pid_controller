#!/usr/bin/env python3
"""
整定记录业务逻辑层 - Service层
将路由层的业务逻辑封装到这里
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session

from api.dao.tuning_record_dao import TuningRecordDAO
from api.bean.tuning_record import TuningRecord
from core.database.database import get_db_session

logger = logging.getLogger(__name__)


class TuningRecordService:
    """整定记录业务服务"""
    
    @staticmethod
    def create_record(
        loop_uri: str,
        loop_status: str,
        tuning_method: str,
        operator: str,
        before_params: str,
        after_params: str,
        operator_id: Optional[str] = None,
        description: Optional[str] = None,
        status: str = "成功",
        remark: Optional[str] = None,
        tuning_details: str = None
    ) -> TuningRecord:
        """
        创建整定记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            loop_name: 回路名称
            tuning_method: 整定方法
            operator: 操作人员
            before_params: 整定前参数
            after_params: 整定后参数
            operator_id: 操作人ID
            description: 描述
            status: 状态
            remark: 备注
            tuning_details: 整定详情
        
        Returns:
            TuningRecord: 创建的记录对象
        """
        try:
            with get_db_session() as db:
                # 创建记录对象
                record = TuningRecord(
                    loop_uri=loop_uri,
                    loop_status=loop_status,
                    description=description,
                    tuning_method=tuning_method,
                    tuning_time=datetime.now(),
                    operator=operator,
                    operator_id=operator_id,
                    before_params=before_params,
                    after_params=after_params,
                    status=status,
                    remark=remark,
                    tuning_details=tuning_details,
                    created_time=datetime.now(),
                    updated_time=datetime.now()
                )

                # 保存到数据库
                db.add(record)
                db.commit()
                db.refresh(record)
            
                logger.info(f"创建整定下发记录成功: ID={record.id}, 回路={record.loop_uri}")
                return record
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def query_records(
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
        查询整定记录列表
        
        Args:
            db: 数据库会话
            loop_type: 回路类型
            loop_name: 回路名称筛选
            tuning_method: 整定方法筛选
            start_time: 开始时间
            end_time: 结束时间
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息
        """
        try:
            # 使用DAO查询
            result = TuningRecordDAO.query_list(
                db=db,
                device_uri=device_uri,
                loop_type=loop_type,
                loop_name=loop_name,
                tuning_method=tuning_method,
                start_time=start_time,
                end_time=end_time,
                page_no=page_no,
                page_size=page_size
            )
            
            return result
            
        except Exception as e:
            logger.error(f"查询整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_record_by_id(db: Session, record_id: str) -> Optional[TuningRecord]:
        """
        根据ID查询记录详情
        
        Args:
            db: 数据库会话
            record_id: 记录ID
        
        Returns:
            Optional[TuningRecord]: 记录对象，不存在则返回None
        """
        try:
            record = TuningRecordDAO.get_by_id(db, record_id)
            
            if record:
                logger.info(f"查询整定记录详情成功: ID={record_id}")
            else:
                logger.warning(f"未找到ID为 {record_id} 的整定记录")
            
            return record
            
        except Exception as e:
            logger.error(f"查询整定记录详情失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_record(db: Session, record_id: str) -> bool:
        """
        删除整定记录
        
        Args:
            db: 数据库会话
            record_id: 记录ID (UUID字符串)
        
        Returns:
            bool: 是否删除成功
        """
        try:
            success = TuningRecordDAO.delete(db, record_id)
            
            if success:
                logger.info(f"删除整定记录成功: ID={record_id}")
            else:
                logger.warning(f"未找到ID为 {record_id} 的整定记录")
            
            return success
            
        except Exception as e:
            logger.error(f"删除整定记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update_record(
        db: Session,
        record_id: str,
        update_data: Dict[str, Any]
    ) -> Optional[TuningRecord]:
        """
        更新整定记录
        
        Args:
            db: 数据库会话
            record_id: 记录ID (UUID字符串)
            update_data: 更新数据字典
        
        Returns:
            Optional[TuningRecord]: 更新后的记录对象
        """
        try:
            record = TuningRecordDAO.update(db, record_id, update_data)
            
            if record:
                logger.info(f"更新整定记录成功: ID={record_id}")
            else:
                logger.warning(f"未找到ID为 {record_id} 的整定记录")
            
            return record
            
        except Exception as e:
            logger.error(f"更新整定记录失败: {str(e)}")
            raise
