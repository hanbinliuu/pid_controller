#!/usr/bin/env python3
"""
业务逻辑层 - 装置评估服务
"""
import logging
from typing import List, Optional, Dict, Any
from sqlmodel import Session

from api.dao.device_evaluation_dao import DeviceEvaluationDAO
from api.bean.device_evaluation import DeviceEvaluation

logger = logging.getLogger(__name__)


class DeviceEvaluationService:
    """装置评估业务逻辑服务"""
    
    @staticmethod
    def create_evaluation(
        db: Session,
        device_uri: str,
        device_name: str,
        statistics_time: str,
        loop_count: int,
        auto_loop_count: int,
        auto_control_rate: float,
        stable_loop_count: int,
        stability_rate: float,
        conditional_excluded_loop_count: int,
        parent_device_uri: Optional[str] = None
    ) -> DeviceEvaluation:
        """
        创建新的装置评估记录
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
            device_name: 装置名称
            statistics_time: 统计时间
            loop_count: 回路数
            auto_loop_count: 自动回路数
            auto_control_rate: 自控率
            stable_loop_count: 平稳回路数
            stability_rate: 平稳率
            conditional_excluded_loop_count: 条件剔除回路数
            parent_device_uri: 父类装置URI
        
        Returns:
            DeviceEvaluation: 创建的评估对象
        """
        try:
            evaluation_data = {
                "device_uri": device_uri,
                "device_name": device_name,
                "statistics_time": statistics_time,
                "loop_count": loop_count,
                "auto_loop_count": auto_loop_count,
                "auto_control_rate": auto_control_rate,
                "stable_loop_count": stable_loop_count,
                "stability_rate": stability_rate,
                "conditional_excluded_loop_count": conditional_excluded_loop_count,
                "parent_device_uri": parent_device_uri
            }
            
            return DeviceEvaluationDAO.create(db, evaluation_data)
            
        except Exception as e:
            logger.error(f"创建装置评估记录失败: {str(e)}")
            raise
    
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
    def get_evaluation_by_device_uri(db: Session, device_uri: str) -> Optional[DeviceEvaluation]:
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
    def update_evaluation(
        db: Session,
        evaluation_id: int,
        device_uri: Optional[str] = None,
        device_name: Optional[str] = None,
        statistics_time: Optional[str] = None,
        loop_count: Optional[int] = None,
        auto_loop_count: Optional[int] = None,
        auto_control_rate: Optional[float] = None,
        stable_loop_count: Optional[int] = None,
        stability_rate: Optional[float] = None,
        conditional_excluded_loop_count: Optional[int] = None,
        parent_device_uri: Optional[str] = None
    ) -> Optional[DeviceEvaluation]:
        """
        更新评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
            device_uri: 新的装置URI
            device_name: 新的装置名称
            statistics_time: 新的统计时间
            loop_count: 新的回路数
            auto_loop_count: 新的自动回路数
            auto_control_rate: 新的自控率
            stable_loop_count: 新的平稳回路数
            stability_rate: 新的平稳率
            conditional_excluded_loop_count: 新的条件剔除回路数
            parent_device_uri: 新的父类装置URI
        
        Returns:
            Optional[DeviceEvaluation]: 更新后的评估对象
        """
        try:
            update_data = {}
            if device_uri is not None:
                update_data["device_uri"] = device_uri
            if device_name is not None:
                update_data["device_name"] = device_name
            if statistics_time is not None:
                update_data["statistics_time"] = statistics_time
            if loop_count is not None:
                update_data["loop_count"] = loop_count
            if auto_loop_count is not None:
                update_data["auto_loop_count"] = auto_loop_count
            if auto_control_rate is not None:
                update_data["auto_control_rate"] = auto_control_rate
            if stable_loop_count is not None:
                update_data["stable_loop_count"] = stable_loop_count
            if stability_rate is not None:
                update_data["stability_rate"] = stability_rate
            if conditional_excluded_loop_count is not None:
                update_data["conditional_excluded_loop_count"] = conditional_excluded_loop_count
            if parent_device_uri is not None:
                update_data["parent_device_uri"] = parent_device_uri
            
            return DeviceEvaluationDAO.update(db, evaluation_id, update_data)
            
        except Exception as e:
            logger.error(f"更新装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_evaluation(db: Session, evaluation_id: int) -> bool:
        """
        删除评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            bool: 是否删除成功
        """
        return DeviceEvaluationDAO.delete(db, evaluation_id)