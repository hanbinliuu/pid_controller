#!/usr/bin/env python3
"""
DAO层 - 回路评估数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from sqlmodel import Session, select, func, desc

from api.bean.loop_evaluation import LoopEvaluation
from api.bean.loop_info import LoopInfo
from api.response.loop_evaluation_detail_response import LoopEvaluationDetailResponse

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
        if 'assessment_time' in data and data['assessment_time']:
            assessment_time = data['assessment_time']
            if isinstance(assessment_time, str):
                # 字符串转datetime
                try:
                    assessment_time = datetime.strptime(assessment_time.split()[0], "%Y-%m-%d")
                except ValueError:
                    logger.warning(f"整定时间格式错误: {assessment_time}，使用当前日期")
                    assessment_time = datetime.now()
            elif isinstance(assessment_time, date) and not isinstance(assessment_time, datetime):
                # date转datetime
                assessment_time = datetime.combine(assessment_time, datetime.min.time())
            elif isinstance(assessment_time, datetime):
                # datetime规范化为当天00:00:00
                assessment_time = datetime.combine(assessment_time.date(), datetime.min.time())
            
            data['assessment_time'] = assessment_time
        
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
    def get_by_id(db: Session, evaluation_id: str) -> Optional[LoopEvaluation]:
        """
        根据ID查询评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
        
        Returns:
            Optional[LoopEvaluation]: 评估对象，不存在则返回None
        """
        # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
        statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
        return db.exec(statement).first()
    
    @staticmethod
    def query_list(
        db: Session,
        loop_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        loop_uri: Optional[str] = None,
        loop_type: Optional[str] = None,
        status: Optional[str] = None,
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
            loop_name: 回路名称筛选（来自回路信息表）
            device_uri: 装置uri，根据loop_path过滤
            loop_uri: 节点uri
            status: 状态筛选
            start_time: 开始时间
            end_time: 结束时间
            min_performance_score: 最小性能评分
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:

            # 构建select语句，左连接LoopInfo表以获取回路信息表中的名称
            statement = select(
                LoopEvaluation.id,
                LoopEvaluation.loop_uri,
                LoopInfo.loop_name.label('loop_name'),
                LoopInfo.loop_type,
                LoopInfo.description,
                LoopEvaluation.loop_name.label('eval_loop_name'),
                LoopEvaluation.status,
                LoopEvaluation.assessment_time,
                LoopEvaluation.performance_score,
                LoopEvaluation.auto_control_rate,
                LoopEvaluation.stability_rate,
                LoopEvaluation.auto_control_time,
                LoopEvaluation.stable_time,
                LoopEvaluation.total_time,
                LoopEvaluation.pt_count,
                LoopEvaluation.pv_sum_value,
                LoopEvaluation.pv_sum_squares,
                LoopEvaluation.mv_sum_value,
                LoopEvaluation.mv_sum_squares,
                LoopEvaluation.pb,
                LoopEvaluation.ti,
                LoopEvaluation.td,
                LoopEvaluation.created_time,
                LoopEvaluation.updated_time
            ).join(LoopInfo, LoopEvaluation.loop_uri == LoopInfo.loop_uri, isouter=True)
            
            # 如果提供了device_uri，则需要根据loop_path进行过滤
            if device_uri is not None:
                statement = statement.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
            
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            # 回路URI筛选（精确匹配）
            if loop_uri:
                statement = statement.where(LoopEvaluation.loop_uri == loop_uri)
            if loop_type:
                statement = statement.where(LoopInfo.loop_type == loop_type)
            # 整定方法筛选（精确匹配）
            if status:
                statement = statement.where(LoopEvaluation.status == status)
            
            # 时间范围筛选
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    statement = statement.where(LoopEvaluation.assessment_time >= start_dt)
                except ValueError:
                    logger.warning(f"开始时间格式错误: {start_time}")
            
            if end_time:
                try:
                    # 结束时间包含当天的23:59:59
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    statement = statement.where(LoopEvaluation.assessment_time <= end_dt)
                except ValueError:
                    logger.warning(f"结束时间格式错误: {end_time}")
            
            # 最小性能评分筛选
            if min_performance_score is not None:
                statement = statement.where(LoopEvaluation.performance_score >= min_performance_score)
            
            # 按整定时间倒序排列
            statement = statement.order_by(desc(LoopEvaluation.assessment_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(LoopEvaluation).join(LoopInfo, LoopEvaluation.loop_uri == LoopInfo.loop_uri, isouter=True)
            
            # 如果提供了device_uri，则需要根据loop_path进行过滤
            if device_uri is not None:
                count_statement = count_statement.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
            
            # 应用相同的筛选条件到计数查询
            if loop_name:
                count_statement = count_statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            if loop_uri:
                count_statement = count_statement.where(LoopEvaluation.loop_uri == loop_uri)
            if loop_type:
                count_statement = count_statement.where(LoopInfo.loop_type == loop_type)
            if status:
                count_statement = count_statement.where(LoopEvaluation.status == status)
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    count_statement = count_statement.where(LoopEvaluation.assessment_time >= start_dt)
                except ValueError:
                    pass
            if end_time:
                try:
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    count_statement = count_statement.where(LoopEvaluation.assessment_time <= end_dt)
                except ValueError:
                    pass
            if min_performance_score is not None:
                count_statement = count_statement.where(LoopEvaluation.performance_score >= min_performance_score)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            evaluation_rows = db.exec(statement).all()
            
            # 将Row对象转换为LoopEvaluation对象
            evaluations = []
            for row in evaluation_rows:
                # 创建一个新的LoopEvaluation对象
                # 如果LoopInfo中没有对应的回路名称，则使用评估记录中的名称作为备选
                loop_name = row.loop_name if row.loop_name is not None else row.eval_loop_name
                # 将LoopEvaluationDetailResponse转换为Dict[str, Any]
                evaluation = {
                    "id": row.id,
                    "loop_uri": row.loop_uri,
                    "loop_name": loop_name,
                    "status": row.status,
                    "loop_type": row.loop_type,
                    "description":row.description,
                    "assessment_time": row.assessment_time,
                    "performance_score": row.performance_score,
                    "auto_control_rate": row.auto_control_rate,
                    "stability_rate": row.stability_rate,
                    "auto_control_time": row.auto_control_time,
                    "stable_time": row.stable_time,
                    "total_time": row.total_time,
                    "pt_count": row.pt_count,
                    "pv_sum_value": row.pv_sum_value,
                    "pv_sum_squares": row.pv_sum_squares,
                    "mv_sum_value": row.mv_sum_value,
                    "mv_sum_squares": row.mv_sum_squares,
                    "pb": row.pb,
                    "ti": row.ti,
                    "td": row.td,
                    "created_time": row.created_time,
                    "updated_time": row.updated_time
                }
                evaluations.append(evaluation)
            
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
    def update(db: Session, evaluation_id: str, update_data: Dict[str, Any]) -> Optional[LoopEvaluation]:
        """
        更新评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
            update_data: 更新数据字典
        
        Returns:
            Optional[LoopEvaluation]: 更新后的评估对象
        """
        try:
            # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
            statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
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
            
            logger.info(f"更新回路评估记录成功: ID={evaluation_id}")
            return evaluation
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, evaluation_id: str) -> bool:
        """
        删除评估记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
        
        Returns:
            bool: 是否删除成功
        """
        try:
            # 直接使用字符串ID进行查询，因为数据库中存储的是VARCHAR类型
            statement = select(LoopEvaluation).where(LoopEvaluation.id == evaluation_id)
            evaluation = db.exec(statement).first()
            
            if not evaluation:
                logger.warning(f"未找到ID为 {evaluation_id} 的评估记录")
                return False
            
            db.delete(evaluation)
            db.commit()
            
            logger.info(f"删除回路评估记录成功: ID={evaluation_id}, loop_uri={evaluation.loop_uri}")
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
            desc(LoopEvaluation.assessment_time)
        ).limit(limit)
        
        return db.exec(statement).all()
    
    @staticmethod
    def get_by_loop_uri_and_date(db: Session, loop_uri: str, assessment_date: date) -> Optional[LoopEvaluation]:
        """
        根据loop_uri和整定日期查询评估记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            assessment_date: 评估日期(只包含年月日)
        
        Returns:
            Optional[LoopEvaluation]: 评估对象，不存在则返回None
        """
        # 转换日期为datetime(当天00:00:00)
        start_datetime = datetime.combine(assessment_date, datetime.min.time())
        end_datetime = datetime.combine(assessment_date, datetime.max.time())
        
        statement = select(LoopEvaluation).where(
            LoopEvaluation.loop_uri == loop_uri,
            LoopEvaluation.assessment_time >= start_datetime,
            LoopEvaluation.assessment_time <= end_datetime
        )
        return db.exec(statement).first()
    
    @staticmethod
    def upsert_by_loop_uri_and_date(
        db: Session,
        loop_uri: str,
        assessment_date: date,
        evaluation_data: Dict[str, Any]
    ) -> LoopEvaluation:
        """
        按回路URI和整定日期进行更新插入(upsert)
        如果记录已存在则更新，否则创建新记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            assessment_date: 评估日期(只包含年月日)
            evaluation_data: 评估数据字典
        
        Returns:
            LoopEvaluation: 创建或更新的评估对象
        """
        try:
            # 强制设置关键字段
            evaluation_data['loop_uri'] = loop_uri
            evaluation_data['assessment_time'] = assessment_date
            
            # 查找是否存在记录
            existing = LoopEvaluationDAO.get_by_loop_uri_and_date(
                db, loop_uri, assessment_date
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
                    f"date={assessment_date}, id={existing.id}, loop_name={existing.loop_name}"
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
                    f"date={assessment_date}, id={evaluation.id}, loop_name={evaluation.loop_name}"
                )
                return evaluation
                
        except Exception as e:
            db.rollback()
            logger.error(
                f"Upsert回路评估记录失败: loop_uri={loop_uri}, "
                f"date={assessment_date}, 错误: {str(e)}"
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
            upsert_data_list: upsert数据列表，每项需包含loop_uri, tuning_date和其他评估数据
        
        Returns:
            List[LoopEvaluation]: 创建或更新的评估对象列表
        """
        try:
            results = []
            for upsert_data in upsert_data_list:
                loop_uri = upsert_data.get('loop_uri')
                tuning_date = upsert_data.get('tuning_date') or upsert_data.get('assessment_time')
                
                if not loop_uri or not tuning_date:
                    logger.warning(f"批量upsert数据缺少必要字段: {upsert_data}")
                    continue
                
                # 转换tuning_date为date类型
                if isinstance(tuning_date, str):
                    tuning_date = datetime.strptime(tuning_date.split()[0], "%Y-%m-%d").date()
                elif isinstance(tuning_date, datetime):
                    tuning_date = tuning_date.date()
                
                result = LoopEvaluationDAO.upsert_by_loop_uri_and_date(
                    db, loop_uri, tuning_date, upsert_data
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
                "status_statistics": {item[0]: item[1] for item in status_stats},
                "avg_performance_score": float(avg_performance_score)
            }
            
        except Exception as e:
            logger.error(f"获取评估统计信息失败: {str(e)}")
            raise
    
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
        try:
            # 构建select语句
            statement = select(LoopEvaluation)
            
            # URI筛选（如果提供了URI列表）
            if uris:
                statement = statement.where(
                    LoopEvaluation.loop_uri.in_(uris)
                )
            
            # 按整定时间倒序排列
            statement = statement.order_by(desc(LoopEvaluation.assessment_time))
            
            # 时间范围筛选
            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%Y-%m-%d")
                    statement = statement.where(LoopEvaluation.assessment_time >= start_dt)
                except ValueError:
                    pass
            
            if end_time:
                try:
                    end_dt = datetime.strptime(end_time + " 23:59:59", "%Y-%m-%d %H:%M:%S")
                    statement = statement.where(LoopEvaluation.assessment_time <= end_dt)
                except ValueError:
                    pass
            
            evaluations = db.exec(statement).all()

            logger.info(f"根据URI列表查询回路评估记录成功，共 {len(evaluations)} 条")
            return evaluations
            
        except Exception as e:
            logger.error(f"根据URI列表查询回路评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_uris_and_date(
        db: Session,
        uris: List[str],
        assessment_date: date
    ) -> List[LoopEvaluation]:
        """
        根据URI列表和评估日期批量查询回路评估记录
        
        Args:
            db: 数据库会话
            uris: 回路URI列表
            assessment_date: 评估日期(只包含年月日)
        
        Returns:
            List[LoopEvaluation]: 评估记录列表
        """
        try:
            if not uris:
                return []
            
            # 转换日期为datetime范围
            start_datetime = datetime.combine(assessment_date, datetime.min.time())
            end_datetime = datetime.combine(assessment_date, datetime.max.time())
            
            # 构建select语句
            statement = select(LoopEvaluation).where(
                LoopEvaluation.loop_uri.in_(uris),
                LoopEvaluation.assessment_time >= start_datetime,
                LoopEvaluation.assessment_time <= end_datetime
            )
            
            evaluations = db.exec(statement).all()
            
            logger.debug(f"根据URI列表和日期查询回路评估记录成功，共 {len(evaluations)} 条")
            return evaluations
            
        except Exception as e:
            logger.error(f"根据URI列表和日期查询回路评估记录失败: {str(e)}")
            raise