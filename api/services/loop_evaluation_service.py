#!/usr/bin/env python3
"""
业务逻辑层 - 回路评估服务
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from sqlmodel import Session

from api.dao.loop_evaluation_dao import LoopEvaluationDAO
from api.bean.loop_evaluation import LoopEvaluation

logger = logging.getLogger(__name__)


class LoopEvaluationService:
    """回路评估业务逻辑服务"""
    
    @staticmethod
    def create_or_update_evaluation(
        db: Session,
        loop_uri: str,
        tuning_date: date,
        loop_name: Optional[str] = None,
        description: Optional[str] = None,
        operator: Optional[str] = None,
        before_params: Optional[str] = None,
        after_params: Optional[str] = None,
        status: Optional[str] = None,
        remark: Optional[str] = None,
        tuning_details: Optional[Dict[str, Any]] = None,
        performance_score: Optional[float] = None,
        auto_control_rate: Optional[float] = None,
        stability_rate: Optional[float] = None,
        auto_control_time: Optional[int] = None,
        stable_time: Optional[int] = None,
        total_time: Optional[int] = None,
        pt_count: Optional[int] = None,
        pv_sum_value: Optional[int] = None,
        pv_sum_squares: Optional[int] = None,
        mv_sum_value: Optional[int] = None,
        mv_sum_squares: Optional[int] = None
    ) -> LoopEvaluation:
        """
        按天和回路URI创建或更新评估记录
        如果同一天同一回路已存在记录，则更新；否则创建新记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            tuning_date: 整定日期(只包含年月日)
            loop_name: 回路名称
            description: 描述
            operator: 操作人员
            before_params: 整定前参数
            after_params: 整定后参数
            status: 状态
            remark: 备注
            tuning_details: 整定详情
            performance_score: 综合性能评分
            auto_control_rate: 自动控制率
            stability_rate: 稳定性评分
            auto_control_time: 自动控制时间
            stable_time: 稳定时间
            total_time: 总时间
            pt_count: 数据点数量
            pv_sum_value: 过程变量和
            pv_sum_squares: 过程变量平方和
            mv_sum_value: 操纵变量和
            mv_sum_squares: 操纵变量平方和
        
        Returns:
            LoopEvaluation: 创建或更新的评估对象
        """
        try:
            evaluation_data = {}
            
            if loop_name is not None:
                evaluation_data["loop_name"] = loop_name
            if description is not None:
                evaluation_data["description"] = description
            if operator is not None:
                evaluation_data["operator"] = operator
            if before_params is not None:
                evaluation_data["before_params"] = before_params
            if after_params is not None:
                evaluation_data["after_params"] = after_params
            if status is not None:
                evaluation_data["status"] = status
            if remark is not None:
                evaluation_data["remark"] = remark
            if tuning_details is not None:
                evaluation_data["tuning_details"] = tuning_details
            if performance_score is not None:
                evaluation_data["performance_score"] = performance_score
            if auto_control_rate is not None:
                evaluation_data["auto_control_rate"] = auto_control_rate
            if stability_rate is not None:
                evaluation_data["stability_rate"] = stability_rate
            if auto_control_time is not None:
                evaluation_data["auto_control_time"] = auto_control_time
            if stable_time is not None:
                evaluation_data["stable_time"] = stable_time
            if total_time is not None:
                evaluation_data["total_time"] = total_time
            if pt_count is not None:
                evaluation_data["pt_count"] = pt_count
            if pv_sum_value is not None:
                evaluation_data["pv_sum_value"] = pv_sum_value
            if pv_sum_squares is not None:
                evaluation_data["pv_sum_squares"] = pv_sum_squares
            if mv_sum_value is not None:
                evaluation_data["mv_sum_value"] = mv_sum_value
            if mv_sum_squares is not None:
                evaluation_data["mv_sum_squares"] = mv_sum_squares
            
            return LoopEvaluationDAO.upsert_by_loop_uri_and_date(
                db, loop_uri, tuning_date, evaluation_data
            )
            
        except Exception as e:
            logger.error(f"创建/更新回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_evaluation_by_id(db: Session, evaluation_id: str) -> Optional[LoopEvaluation]:
        """
        根据ID获取评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
        
        Returns:
            Optional[LoopEvaluation]: 评估对象
        """
        return LoopEvaluationDAO.get_by_id(db, evaluation_id)
    
    @staticmethod
    def get_evaluations_by_loop_uri(
        db: Session, 
        loop_uri: str, 
        limit: int = 10
    ) -> List[LoopEvaluation]:
        """
        根据回路URI获取历史评估记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            limit: 返回记录数量限制
        
        Returns:
            List[LoopEvaluation]: 评估记录列表
        """
        return LoopEvaluationDAO.get_by_loop_uri(db, loop_uri, limit)
    
    @staticmethod
    def list_evaluations(
        db: Session,
        loop_name: Optional[str] = None,
        loop_uri: Optional[str] = None,
        status: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        min_performance_score: Optional[float] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询评估记录列表
        
        Args:
            db: 数据库会话
            loop_name: 回路名称
            loop_uri: 回路URI
            status: 状态
            start_time: 开始时间
            end_time: 结束时间
            min_performance_score: 最小性能评分
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含评估列表和分页信息
        """
        return LoopEvaluationDAO.query_list(
            db,
            loop_name=loop_name,
            loop_uri=loop_uri,
            status=status,
            start_time=start_time,
            end_time=end_time,
            min_performance_score=min_performance_score,
            page_no=page_no,
            page_size=page_size
        )
    
    @staticmethod
    def delete_evaluation(db: Session, evaluation_id: str) -> bool:
        """
        删除评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
        
        Returns:
            bool: 是否删除成功
        """
        return LoopEvaluationDAO.delete(db, evaluation_id)
    
    @staticmethod
    def get_statistics(db: Session) -> Dict[str, Any]:
        """
        获取评估统计信息
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict: 统计信息
        """
        return LoopEvaluationDAO.get_statistics(db)
    
    @staticmethod
    def get_evaluations_by_uris(
        db: Session,
        uris: List[str],
        start_time: Optional[str] = None,
        end_time: Optional[str] = None
    ) -> List[LoopEvaluation]:
        """
        根据URI列表批量查询回路评估记录
        
        Args:
            db: 数据库会话
            uris: 回路URI列表
            start_time: 开始时间(yyyy-mm-dd)
            end_time: 结束时间(yyyy-mm-dd)
        
        Returns:
            List[LoopEvaluation]: 评估记录列表
        """
        return LoopEvaluationDAO.get_evaluations_by_uris(db, uris, start_time, end_time)
