#!/usr/bin/env python3
"""
业务逻辑层 - 装置评估服务
"""
import logging
from typing import List, Optional, Dict, Any, Sequence
from datetime import datetime, date
from sqlmodel import Session

from api.dao.device_evaluation_dao import DeviceEvaluationDAO
from api.bean.device_evaluation import DeviceEvaluation
from api.bean.loop_info import LoopInfo
from sqlmodel import select

logger = logging.getLogger(__name__)


class DeviceEvaluationService:
    """装置评估业务逻辑服务"""
    
    @staticmethod
    def get_evaluation_by_id(db: Session, evaluation_id: int) -> Optional[DeviceEvaluation]:
        """
        根据ID获取评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象
        """
        return DeviceEvaluationDAO.get_by_id(db, evaluation_id)
    
    @staticmethod
    def get_evaluation_by_device_uri_now(db: Session, device_uri: str) -> Optional[DeviceEvaluation]:
        """
        根据device_uri获取评估记录
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象
        """
        return DeviceEvaluationDAO.get_by_device_uri(db, device_uri)

    @staticmethod
    def get_evaluation_by_parent_device_uri_now(db: Session, device_uri: str) -> Sequence[DeviceEvaluation]:
        """
        根据device_uri获取子装置评估记录

        Args:
            db: 数据库会话
            device_uri: 装置URI

        Returns:
            Optional[DeviceEvaluation]: 评估对象
        """
        return DeviceEvaluationDAO.get_by_parent_device_uri(db, device_uri)

    @staticmethod
    def list_evaluations(
        db: Session,
        device_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询评估记录列表
        
        Args:
            db: 数据库会话
            device_name: 装置名称
            device_uri: 装置URI
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含评估列表和分页信息
        """
        return DeviceEvaluationDAO.query_list(
            db,
            device_name=device_name,
            device_uri=device_uri,
            page_no=page_no,
            page_size=page_size
        )
    
    @staticmethod
    def get_evaluations_by_date_range(
        db: Session,
        device_uri: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[DeviceEvaluation]:
        """
        根据装置URI和时间范围查询评估记录（不分页）
        
        Args:
            db: 数据库会话
            device_uri: 装置URI（可选，为空则查询所有装置）
            start_date: 开始日期（可选，包含该日期）
            end_date: 结束日期（可选，包含该日期）
        
        Returns:
            List[DeviceEvaluation]: 评估记录列表，按统计时间倒序排列
        """
        return DeviceEvaluationDAO.get_by_device_uri_and_date_range(
            db,
            device_uri=device_uri,
            start_date=start_date,
            end_date=end_date
        )
    
    @staticmethod
    def get_device_loops(
        db: Session,
        device_uri: str
    ) -> List[LoopInfo]:
        """
        获取装置下的回路列表
        
        通过回路loop_uri模糊匹配装置URI来查找装置下的所有回路
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
        Returns:
            Dict: 包含回路列表和统计信息
        """
        try:
            # 构建SQL查询
            statement = select(LoopInfo).where(
                LoopInfo.loop_path.like(f"%{device_uri}%") # loop_path包含装置URI
            )

            
            # 按创建时间排序
            statement = statement.order_by(LoopInfo.created_time.desc())
            statement = statement.where(LoopInfo.is_active == True)

            loops = db.exec(statement).all()
            
            # 转换为返回格式
            loop_list = []
            for loop in loops:
                loop_list.append(loop)

            return loop_list
            
        except Exception as e:
            logger.error(f"获取装置回路列表失败: {str(e)}")
            raise