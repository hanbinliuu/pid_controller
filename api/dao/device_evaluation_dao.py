#!/usr/bin/env python3
"""
DAO层 - 装置评估数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc

from api.bean.device_evaluation import DeviceEvaluation

logger = logging.getLogger(__name__)


class DeviceEvaluationDAO:
    """装置评估DAO"""
    
    @staticmethod
    def create(db: Session, evaluation_data: Dict[str, Any]) -> DeviceEvaluation:
        """
        创建装置评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_data: 评估数据字典
        
        Returns:
            DeviceEvaluation: 创建的评估对象
        """
        try:
            # SQLModel自动进行数据验证
            evaluation = DeviceEvaluation(**evaluation_data)
            
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            
            logger.info(f"创建装置评估记录成功: ID={evaluation.id}, device_uri={evaluation.device_uri}")
            return evaluation
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, evaluation_id: int) -> Optional[DeviceEvaluation]:
        """
        根据ID查询评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象，不存在则返回None
        """
        statement = select(DeviceEvaluation).where(DeviceEvaluation.id == evaluation_id)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_device_uri(db: Session, device_uri: str) -> Optional[DeviceEvaluation]:
        """
        根据device_uri查询评估记录
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象，不存在则返回None
        """
        statement = select(DeviceEvaluation).where(DeviceEvaluation.device_uri == device_uri)
        return db.exec(statement).first()
    
    @staticmethod
    def query_list(
        db: Session,
        device_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询评估记录列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            device_name: 装置名称筛选（模糊匹配）
            device_uri: 装置URI筛选（模糊匹配）
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(DeviceEvaluation)
            
            # 装置名称筛选（模糊匹配）
            if device_name:
                statement = statement.where(DeviceEvaluation.device_name.like(f"%{device_name}%"))
            
            # 装置URI筛选（模糊匹配）
            if device_uri:
                statement = statement.where(DeviceEvaluation.device_uri.like(f"%{device_uri}%"))
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.created_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(DeviceEvaluation)
            # 应用相同的筛选条件到计数查询
            if device_name:
                count_statement = count_statement.where(DeviceEvaluation.device_name.like(f"%{device_name}%"))
            if device_uri:
                count_statement = count_statement.where(DeviceEvaluation.device_uri.like(f"%{device_uri}%"))
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            evaluations = db.exec(statement).all()
            
            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询装置评估记录成功，总数: {total}, 当前页: {page_no}")
            
            return {
                "evaluations": evaluations,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
            }
            
        except Exception as e:
            logger.error(f"查询装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update(db: Session, evaluation_id: int, update_data: Dict[str, Any]) -> Optional[DeviceEvaluation]:
        """
        更新评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
            update_data: 更新数据字典
        
        Returns:
            Optional[DeviceEvaluation]: 更新后的评估对象
        """
        try:
            statement = select(DeviceEvaluation).where(DeviceEvaluation.id == evaluation_id)
            evaluation = db.exec(statement).first()
            
            if not evaluation:
                logger.warning(f"未找到ID为 {evaluation_id} 的评估记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(evaluation, key):
                    setattr(evaluation, key, value)
            
            # 更新updated_time
            evaluation.updated_time = datetime.now()
            
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            
            logger.info(f"更新装置评估记录成功: ID={evaluation_id}")
            return evaluation
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, evaluation_id: int) -> bool:
        """
        删除评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(DeviceEvaluation).where(DeviceEvaluation.id == evaluation_id)
            evaluation = db.exec(statement).first()
            
            if not evaluation:
                logger.warning(f"未找到ID为 {evaluation_id} 的评估记录")
                return False
            
            db.delete(evaluation)
            db.commit()
            
            logger.info(f"删除装置评估记录成功: ID={evaluation_id}, device_uri={evaluation.device_uri}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除装置评估记录失败: {str(e)}")
            raise