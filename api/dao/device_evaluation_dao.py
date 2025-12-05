#!/usr/bin/env python3
"""
DAO层 - 装置评估数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any, Sequence
from datetime import datetime, date
from sqlmodel import Session, select, func, desc

from api.bean.device_evaluation import DeviceEvaluation

logger = logging.getLogger(__name__)


class DeviceEvaluationDAO:
    """装置评估DAO"""

    
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
        statement = select(DeviceEvaluation).where(DeviceEvaluation.device_uri == device_uri,
                                                   DeviceEvaluation.statistics_time==datetime.now().date()
                                                   ).order_by(desc(DeviceEvaluation.created_time))
        return db.exec(statement).first()

    @staticmethod
    def get_by_parent_device_uri(db: Session, device_uri: str) -> Sequence[DeviceEvaluation]:
        """
        根据父类device_uri查询评估记录

        Args:
            db: 数据库会话
            device_uri: 装置URI

        Returns:
            Optional[DeviceEvaluation]: 评估对象，不存在则返回None
        """
        statement = select(DeviceEvaluation).where(DeviceEvaluation.parent_device_uri == device_uri,
                                                   DeviceEvaluation.statistics_time==datetime.now().date()
                                                   ).order_by(desc(DeviceEvaluation.created_time))
        return db.exec(statement).all()
    @staticmethod
    def get_by_device_uri_and_date(db: Session, device_uri: str, statistics_date: date) -> Optional[DeviceEvaluation]:
        """
        根据device_uri和统计日期查询评估记录
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
            statistics_date: 统计日期(只包含年月日)
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象，不存在则返回None
        """
        # 转换日期为datetime(当天00:00:00)
        start_datetime = datetime.combine(statistics_date, datetime.min.time())
        end_datetime = datetime.combine(statistics_date, datetime.max.time())
        
        statement = select(DeviceEvaluation).where(
            DeviceEvaluation.device_uri == device_uri,
            DeviceEvaluation.statistics_time >= start_datetime,
            DeviceEvaluation.statistics_time <= end_datetime
        )
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_device_uri_and_date_range(
        db: Session,
        device_uri: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[DeviceEvaluation]:
        """
        根据装置URI及下级URI和时间范围查询评估记录（不分页）
        
        Args:
            db: 数据库会话
            device_uri: 装置URI（可选，为空则查询所有装置）
            start_date: 开始日期（可选，包含该日期）
            end_date: 结束日期（可选，包含该日期）
        
        Returns:
            List[DeviceEvaluation]: 评估记录列表，按统计时间倒序排列
        """
        try:
            # 构建查询语句
            statement = select(DeviceEvaluation)
            
            # 装置URI筛选
            if device_uri:
                statement = statement.where((DeviceEvaluation.device_uri == device_uri))
            
            # 时间范围筛选
            if start_date:
                start_datetime = datetime.combine(start_date, datetime.min.time())
                statement = statement.where(DeviceEvaluation.statistics_time >= start_datetime)
            
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                statement = statement.where(DeviceEvaluation.statistics_time <= end_datetime)
            
            # 按统计时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.statistics_time))
            
            results = db.exec(statement).all()
            
            logger.info(
                f"查询装置评估记录成功 - device_uri: {device_uri or '全部'}, "
                f"start_date: {start_date}, end_date: {end_date}, 结果数: {len(results)}"
            )
            
            return list(results)
            
        except Exception as e:
            logger.error(
                f"查询装置评估记录失败 - device_uri: {device_uri}, "
                f"start_date: {start_date}, end_date: {end_date}, 错误: {str(e)}"
            )
            raise

    @staticmethod
    def get_this_and_child_by_device_uri_and_date_range(
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
        try:
            # 构建查询语句
            statement = select(DeviceEvaluation)

            # 装置URI筛选
            if device_uri:
                statement = statement.where((DeviceEvaluation.device_uri == device_uri)|(DeviceEvaluation.parent_device_uri == device_uri))

            # 时间范围筛选
            if start_date:
                start_datetime = datetime.combine(start_date, datetime.min.time())
                statement = statement.where(DeviceEvaluation.statistics_time >= start_datetime)

            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                statement = statement.where(DeviceEvaluation.statistics_time <= end_datetime)

            # 按统计时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.statistics_time))

            results = db.exec(statement).all()

            logger.info(
                f"查询装置评估记录成功 - device_uri: {device_uri or '全部'}, "
                f"start_date: {start_date}, end_date: {end_date}, 结果数: {len(results)}"
            )

            return list(results)

        except Exception as e:
            logger.error(
                f"查询装置评估记录失败 - device_uri: {device_uri}, "
                f"start_date: {start_date}, end_date: {end_date}, 错误: {str(e)}"
            )
            raise
    @staticmethod
    def upsert_by_device_uri_and_date(
        db: Session,
        device_uri: str,
        statistics_date: date,
        evaluation_data: Dict[str, Any]
    ) -> DeviceEvaluation:
        """
        按装置URI和统计日期进行更新插入(upsert)
        如果记录已存在则更新，否则创建新记录
        
        Args:
            db: 数据库会话
            device_uri: 装置URI
            statistics_date: 统计日期(只包含年月日)
            evaluation_data: 评估数据字典
        
        Returns:
            DeviceEvaluation: 创建或更新的评估对象
        """
        try:
            # 确保统计时间为当天00:00:00
            statistics_datetime = datetime.combine(statistics_date, datetime.min.time())
            evaluation_data['statistics_time'] = statistics_datetime
            evaluation_data['device_uri'] = device_uri
            
            # 查找是否存在记录
            existing = DeviceEvaluationDAO.get_by_device_uri_and_date(
                db, device_uri, statistics_date
            )
            
            if existing:
                # 更新现有记录
                for key, value in evaluation_data.items():
                    if hasattr(existing, key) and key not in ['id', 'statistics_time']:
                        setattr(existing, key, value)
                
                existing.updated_time = datetime.now()
                db.add(existing)
                db.commit()
                db.refresh(existing)
                
                logger.info(
                    f"更新装置评估记录: device_uri={device_uri}, "
                    f"date={statistics_date}, id={existing.id}"
                )
                return existing
            else:
                # 创建新记录
                evaluation_data['created_time'] = datetime.now()
                evaluation_data['updated_time'] = datetime.now()
                evaluation = DeviceEvaluation(**evaluation_data)
                
                db.add(evaluation)
                db.commit()
                db.refresh(evaluation)
                
                logger.info(
                    f"创建装置评估记录: device_uri={device_uri}, "
                    f"date={statistics_date}, id={evaluation.id}"
                )
                return evaluation
                
        except Exception as e:
            db.rollback()
            logger.error(f"Upsert装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def batch_upsert_by_device_uri_and_date(
        db: Session,
        upsert_data_list: List[Dict[str, Any]]
    ) -> List[DeviceEvaluation]:
        """
        批量按装置URI和统计日期进行更新插入(upsert)
        
        Args:
            db: 数据库会话
            upsert_data_list: upsert数据列表，每项需包含device_uri, statistics_date和其他评估数据
        
        Returns:
            List[DeviceEvaluation]: 创建或更新的评估对象列表
        """
        try:
            results = []
            for upsert_data in upsert_data_list:
                device_uri = upsert_data.get('device_uri')
                statistics_date = upsert_data.get('statistics_date')
                
                if not device_uri or not statistics_date:
                    logger.warning(f"批量upsert数据缺少必要字段: {upsert_data}")
                    continue
                
                # 转换statistics_date为date类型
                if isinstance(statistics_date, str):
                    statistics_date = datetime.strptime(statistics_date.split()[0], "%Y-%m-%d").date()
                elif isinstance(statistics_date, datetime):
                    statistics_date = statistics_date.date()
                
                result = DeviceEvaluationDAO.upsert_by_device_uri_and_date(
                    db, device_uri, statistics_date, upsert_data
                )
                results.append(result)
            
            logger.info(f"批量upsert装置评估记录成功，共处理 {len(results)} 条")
            return results
            
        except Exception as e:
            db.rollback()
            logger.error(f"批量upsert装置评估记录失败: {str(e)}")
            raise
    
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