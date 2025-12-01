#!/usr/bin/env python3
"""
DAO层 - 回路评估数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from sqlmodel import Session, select, func, desc

from api.bean.loop_evaluation import LoopEvaluation

logger = logging.getLogger(__name__)


class LoopEvaluationDAO:
    """回路评估DAO"""
    
    @staticmethod
    def _prepare_evaluation_data(evaluation_data: Dict[str, Any], is_update: bool = False) -> Dict[str, Any]:
        """
        预处理评估数据，统一数据格式和时间处理
        
        Args:
            evaluation_data: 原始评估数据字典
            is_update: 是否为更新操作
        
        Returns:
            Dict[str, Any]: 处理后的数据字典
        """
        data = evaluation_data.copy()
        
        # 处理整定时间：确保为datetime类型，并规范化为当天00:00:00
        if 'assessmen_time' in data and data['assessmen_time']:
            assessmen_time = data['assessmen_time']
            if isinstance(assessmen_time, str):
                # 字符串转datetime
                try:
                    assessmen_time = datetime.strptime(assessmen_time.split()[0], "%Y-%m-%d")
                except ValueError:
                    logger.warning(f"整定时间格式错误: {assessmen_time}，使用当前日期")
                    assessmen_time = datetime.now()
            elif isinstance(assessmen_time, date) and not isinstance(assessmen_time, datetime):
                # date转datetime
                assessmen_time = datetime.combine(assessmen_time, datetime.min.time())
            elif isinstance(assessmen_time, datetime):
                # datetime规范化为当天00:00:00
                assessmen_time = datetime.combine(assessmen_time.date(), datetime.min.time())
            
            data['assessmen_time'] = assessmen_time
        
        # 设置时间戳
        now = datetime.now()
        if not is_update:
            data.setdefault('created_time', now)
        data['updated_time'] = now
        
        return data
    
    @staticmethod
    def create(db: Session, evaluation_data: Dict[str, Any]) -> LoopEvaluation:
        """
        创建回路评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_data: 评估数据字典
        
        Returns:
            LoopEvaluation: 创建的评估对象
        """
        try:
            # 预处理数据
            processed_data = LoopEvaluationDAO._prepare_evaluation_data(evaluation_data, is_update=False)
            
            # SQLModel自动进行数据验证
            evaluation = LoopEvaluation(**processed_data)
            
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            
            logger.info(
                f"创建回路评估记录成功: ID={evaluation.id}, "
                f"回路={evaluation.loop_name}, URI={evaluation.loop_uri}"
            )
            return evaluation
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建回路评估记录失败: {str(e)}, 数据: {evaluation_data}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, evaluation_id: int) -> Optional[LoopEvaluation]:
        """
        根据ID查询评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            Optional[LoopEvaluation]: 评估对象，不存在则返回None
        """
        statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
        return db.exec(statement).first()
    
    @staticmethod
    def query_list(
        db: Session,
        loop_name: Optional[str] = None,
        loop_uri: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        min_performance_score: Optional[float] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询回路评估记录列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选
            loop_uri: 节点uri
            start_time: 开始时间
            end_time: 结束时间
            min_performance_score: 最小性能评分
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(LoopEvaluation)
            
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopEvaluation.loop_name.like(f"%{loop_name}%"))
            # 回路名称筛选（模糊匹配）
            if loop_uri:
                statement = statement.where(LoopEvaluation.loop_uri.like(f"%{loop_uri}%"))
            
            # 时间范围筛选
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    statement = statement.where(LoopEvaluation.assessmen_time >= start_dt)
                except ValueError:
                    logger.warning(f"开始时间格式错误: {start_time}")
            
            if end_time:
                try:
                    # 结束时间包含当天的23:59:59
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    statement = statement.where(LoopEvaluation.assessmen_time <= end_dt)
                except ValueError:
                    logger.warning(f"结束时间格式错误: {end_time}")
            
            # 最小性能评分筛选
            if min_performance_score is not None:
                statement = statement.where(LoopEvaluation.performance_score >= min_performance_score)
            
            # 按整定时间倒序排列
            statement = statement.order_by(desc(LoopEvaluation.assessmen_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(LoopEvaluation)
            # 应用相同的筛选条件到计数查询
            if loop_name:
                count_statement = count_statement.where(LoopEvaluation.loop_name.like(f"%{loop_name}%"))
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    count_statement = count_statement.where(LoopEvaluation.assessmen_time >= start_dt)
                except ValueError:
                    pass
            if end_time:
                try:
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    count_statement = count_statement.where(LoopEvaluation.assessmen_time <= end_dt)
                except ValueError:
                    pass
            if min_performance_score is not None:
                count_statement = count_statement.where(LoopEvaluation.performance_score >= min_performance_score)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            evaluations = db.exec(statement).all()
            
            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询回路评估记录成功，总数: {total}, 当前页: {page_no}")
            
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
            logger.error(f"查询回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update(db: Session, evaluation_id: int, update_data: Dict[str, Any]) -> Optional[LoopEvaluation]:
        """
        更新回路评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
            update_data: 更新数据字典
        
        Returns:
            Optional[LoopEvaluation]: 更新后的评估对象
        """
        try:
            statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
            evaluation = db.exec(statement).first()
            
            if not evaluation:
                logger.warning(f"未找到ID为 {evaluation_id} 的评估记录")
                return None
            
            # 预处理更新数据
            processed_data = LoopEvaluationDAO._prepare_evaluation_data(update_data, is_update=True)
            
            # 更新字段（排除不应更新的字段）
            excluded_fields = {'id', 'created_time'}
            for key, value in processed_data.items():
                if key not in excluded_fields and hasattr(evaluation, key):
                    setattr(evaluation, key, value)
            
            db.add(evaluation)
            db.commit()
            db.refresh(evaluation)
            
            logger.info(
                f"更新回路评估记录成功: ID={evaluation_id}, "
                f"回路={evaluation.loop_name}, URI={evaluation.loop_uri}"
            )
            return evaluation
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新回路评估记录失败: ID={evaluation_id}, 错误: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, evaluation_id: int) -> bool:
        """
        删除回路评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
            evaluation = db.exec(statement).first()
            
            if not evaluation:
                logger.warning(f"未找到ID为 {evaluation_id} 的评估记录")
                return False
            
            db.delete(evaluation)
            db.commit()
            
            logger.info(f"删除回路评估记录成功: ID={evaluation_id}, 回路={evaluation.loop_name}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_loop_uri(db: Session, loop_uri: str, limit: int = 10) -> List[LoopEvaluation]:
        """
        根据回路URI查询历史评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            limit: 返回记录数量限制
        
        Returns:
            List[LoopEvaluation]: 评估记录列表
        """
        statement = select(LoopEvaluation).where(
            LoopEvaluation.loop_uri == loop_uri
        ).order_by(
            desc(LoopEvaluation.assessmen_time)
        ).limit(limit)
        
        return db.exec(statement).all()
    
    @staticmethod
    def get_by_loop_uri_and_date(db: Session, loop_uri: str, assessmen_time: date) -> Optional[LoopEvaluation]:
        """
        根据loop_uri和整定日期查询评估记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            assessmen_time: 整定日期(只包含年月日)
        
        Returns:
            Optional[LoopEvaluation]: 评估对象，不存在则返回None
        """
        # 转换日期为datetime(当天00:00:00)
        start_datetime = datetime.combine(assessmen_time, datetime.min.time())
        end_datetime = datetime.combine(assessmen_time, datetime.max.time())
        
        statement = select(LoopEvaluation).where(
            LoopEvaluation.loop_uri == loop_uri,
            LoopEvaluation.assessmen_time >= start_datetime,
            LoopEvaluation.assessmen_time <= end_datetime
        )
        return db.exec(statement).first()
    
    @staticmethod
    def upsert_by_loop_uri_and_date(
        db: Session,
        loop_uri: str,
        assessmen_time: date,
        evaluation_data: Dict[str, Any]
    ) -> LoopEvaluation:
        """
        按回路URI和整定日期进行更新插入(upsert)
        如果记录已存在则更新，否则创建新记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            assessmen_time: 整定日期(只包含年月日)
            evaluation_data: 评估数据字典
        
        Returns:
            LoopEvaluation: 创建或更新的评估对象
        """
        try:
            # 强制设置关键字段
            evaluation_data['loop_uri'] = loop_uri
            evaluation_data['assessmen_time'] = assessmen_time
            
            # 查找是否存在记录
            existing = LoopEvaluationDAO.get_by_loop_uri_and_date(
                db, loop_uri, assessmen_time
            )
            
            if existing:
                # 更新现有记录
                processed_data = LoopEvaluationDAO._prepare_evaluation_data(evaluation_data, is_update=True)
                
                excluded_fields = {'id', 'created_time'}
                for key, value in processed_data.items():
                    if key not in excluded_fields and hasattr(existing, key):
                        setattr(existing, key, value)
                
                db.add(existing)
                db.commit()
                db.refresh(existing)
                
                logger.info(
                    f"更新回路评估记录: loop_uri={loop_uri}, "
                    f"date={assessmen_time}, id={existing.id}, loop_name={existing.loop_name}"
                )
                return existing
            else:
                # 创建新记录
                processed_data = LoopEvaluationDAO._prepare_evaluation_data(evaluation_data, is_update=False)
                evaluation = LoopEvaluation(**processed_data)
                
                db.add(evaluation)
                db.commit()
                db.refresh(evaluation)
                
                logger.info(
                    f"创建回路评估记录: loop_uri={loop_uri}, "
                    f"date={assessmen_time}, id={evaluation.id}, loop_name={evaluation.loop_name}"
                )
                return evaluation
                
        except Exception as e:
            db.rollback()
            logger.error(
                f"Upsert回路评估记录失败: loop_uri={loop_uri}, "
                f"date={assessmen_time}, 错误: {str(e)}"
            )
            raise
    
    @staticmethod
    def batch_create(db: Session, evaluations_data: List[Dict[str, Any]]) -> List[LoopEvaluation]:
        """
        批量创建回路评估记录
        
        Args:
            db: 数据库会话
            evaluations_data: 评估数据字典列表
        
        Returns:
            List[LoopEvaluation]: 创建的评估对象列表
        """
        try:
            evaluations = []
            for evaluation_data in evaluations_data:
                processed_data = LoopEvaluationDAO._prepare_evaluation_data(evaluation_data, is_update=False)
                evaluation = LoopEvaluation(**processed_data)
                evaluations.append(evaluation)
            
            db.add_all(evaluations)
            db.commit()
            
            for evaluation in evaluations:
                db.refresh(evaluation)
            
            logger.info(f"批量创建回路评估记录成功，共 {len(evaluations)} 条")
            return evaluations
            
        except Exception as e:
            db.rollback()
            logger.error(f"批量创建回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def batch_upsert_by_loop_uri_and_date(
        db: Session,
        upsert_data_list: List[Dict[str, Any]]
    ) -> List[LoopEvaluation]:
        """
        批量按回路URI和整定日期进行更新插入(upsert)
        
        Args:
            db: 数据库会话
            upsert_data_list: upsert数据列表，每项需包含loop_uri, assessmen_time和其他评估数据
        
        Returns:
            List[LoopEvaluation]: 创建或更新的评估对象列表
        """
        try:
            results = []
            for upsert_data in upsert_data_list:
                loop_uri = upsert_data.get('loop_uri')
                assessmen_time = upsert_data.get('assessmen_time') or upsert_data.get('assessmen_time')
                
                if not loop_uri or not assessmen_time:
                    logger.warning(f"批量upsert数据缺少必要字段: {upsert_data}")
                    continue
                
                # 转换assessmen_time为date类型
                if isinstance(assessmen_time, str):
                    assessmen_time = datetime.strptime(assessmen_time.split()[0], "%Y-%m-%d").date()
                elif isinstance(assessmen_time, datetime):
                    assessmen_time = assessmen_time.date()
                
                result = LoopEvaluationDAO.upsert_by_loop_uri_and_date(
                    db, loop_uri, assessmen_time, upsert_data
                )
                results.append(result)
            
            logger.info(f"批量upsert回路评估记录成功，共处理 {len(results)} 条")
            return results
            
        except Exception as e:
            db.rollback()
            logger.error(f"批量upsert回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_statistics(db: Session) -> Dict[str, Any]:
        """
        获取评估统计信息 - SQLModel方式
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict: 统计信息
        """
        try:
            # 总记录数
            total_count = db.exec(select(func.count()).select_from(LoopEvaluation)).one()
            
            # 按整定方法统计
            method_statement = select(
                LoopEvaluation.tuning_method,
                func.count(LoopEvaluation.id).label('count')
            ).group_by(LoopEvaluation.tuning_method)
            method_stats = db.exec(method_statement).all()
            
            # 按状态统计
            status_statement = select(
                LoopEvaluation.status,
                func.count(LoopEvaluation.id).label('count')
            ).group_by(LoopEvaluation.status)
            status_stats = db.exec(status_statement).all()
            
            # 性能评分分布统计
            avg_performance_score = db.exec(
                select(func.avg(LoopEvaluation.performance_score))
            ).one() or 0.0
            
            return {
                "total_count": total_count,
                "method_statistics": {item[0]: item[1] for item in method_stats},
                "status_statistics": {item[0]: item[1] for item in status_stats},
                "avg_performance_score": float(avg_performance_score)
            }
            
        except Exception as e:
            logger.error(f"获取评估统计信息失败: {str(e)}")
            raise