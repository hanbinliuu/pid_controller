#!/usr/bin/env python3
"""
DAO层 - 装置评估数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any, Sequence
from datetime import datetime, date
from sqlmodel import Session, select, func, desc, asc
from sqlalchemy.dialects.postgresql import insert

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
    def get_this_child_by_device_uri_and_date_now(
            db: Session,
            device_uri: Optional[str] = None,
    ) -> List[DeviceEvaluation]:
        """
        根据装置URI及下级URI和时间范围查询评估记录（不分页）

        Args:
            db: 数据库会话
            device_uri: 装置URI（可选，为空则查询所有装置）

        Returns:
            List[DeviceEvaluation]: 评估记录列表
        """
        try:
            # 构建查询语句
            statement = select(DeviceEvaluation)

            # 装置URI筛选
            if device_uri:
                statement = statement.where((DeviceEvaluation.device_uri == device_uri)|(DeviceEvaluation.parent_device_uri == device_uri))

            statement = statement.where(DeviceEvaluation.statistics_time == datetime.now().date())

            # 按统计时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.device_uri))

            results = db.exec(statement).all()


            logger.info(
                f"查询装置评估记录成功 - device_uri: {device_uri or '全部'}, "
            )

            return list(results)

        except Exception as e:
            logger.error(
                f"查询装置评估记录失败 - device_uri: {device_uri}, "
            )
            raise
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
            statement = statement.order_by(asc(DeviceEvaluation.statistics_time))
            
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
    def query_by_device_uri_and_date_range_page(
        db: Session,
        device_uri: Optional[str] = None,
        device_name: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        is_child: bool = False,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        根据装置URI和时间范围查询评估记录（分页）

        Args:
            db: 数据库会话
            device_uri: 装置URI（可选，为空则查询所有装置）
            start_date: 开始日期（可选，包含该日期）
            end_date: 结束日期（可选，包含该日期）
            page_no: 页码
            page_size: 每页数量

        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(DeviceEvaluation)

            # 装置URI筛选
            if device_uri:
                statement = statement.where((DeviceEvaluation.device_uri == device_uri))
            if is_child:
                statement = statement.where((DeviceEvaluation.parent_device_uri == device_uri))

            if device_name:
                statement = statement.where((DeviceEvaluation.device_name.like(f"%{device_name}%")))

            # 时间范围筛选
            if start_date:
                start_datetime = datetime.combine(start_date, datetime.min.time())
                statement = statement.where(DeviceEvaluation.statistics_time >= start_datetime)

            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                statement = statement.where(DeviceEvaluation.statistics_time <= end_datetime)

            # if start_date is None and end_date is None:
            #     statement = statement.where(DeviceEvaluation.statistics_time==datetime.now().date())

            # 按统计时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.statistics_time))

            # 获取总数
            count_statement = select(func.count()).select_from(DeviceEvaluation)
            # 应用相同的筛选条件到计数查询
            if device_uri:
                count_statement = count_statement.where((DeviceEvaluation.device_uri == device_uri))
            if is_child:
                count_statement = count_statement.where((DeviceEvaluation.parent_device_uri == device_uri))
            if device_name:
                count_statement = count_statement.where((DeviceEvaluation.device_name.like(f"%{device_name}%")))
            if start_date:
                start_datetime = datetime.combine(start_date, datetime.min.time())
                count_statement = count_statement.where(DeviceEvaluation.statistics_time >= start_datetime)
            if end_date:
                end_datetime = datetime.combine(end_date, datetime.max.time())
                count_statement = count_statement.where(DeviceEvaluation.statistics_time <= end_datetime)
            # if start_date is None and end_date is None:
            #     count_statement = statement.where(DeviceEvaluation.statistics_time==datetime.now().date())

            total = db.exec(count_statement).one()

            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            evaluations = db.exec(statement).all()

            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0

            logger.info(
                f"分页查询装置评估记录成功 - device_uri: {device_uri or '全部'}, "
                f"start_date: {start_date}, end_date: {end_date}, 总数: {total}, 当前页: {page_no}"
            )

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
            logger.error(
                f"分页查询装置评估记录失败 - device_uri: {device_uri}, "
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
            statistics_datetime = datetime.combine(statistics_date, datetime.time())
            evaluation_data['statistics_time'] = statistics_datetime
            evaluation_data['device_uri'] = device_uri
            from sqlalchemy.dialects.postgresql import insert

            stmt = insert(DeviceEvaluation).values(
                device_uri=device_uri,
                statistics_time=statistics_datetime,
                **evaluation_data
            )

            # 假设存在对 device_uri + statistics_date 的唯一约束
            do_update_stmt = stmt.on_conflict_do_update(
                # 依据唯一约束或索引
                index_elements=['device_uri', 'statistics_date'],
                set_={**evaluation_data, 'updated_time': datetime.now()}
            )

            db.execute(do_update_stmt)
            db.commit()
                
        except Exception as e:
            db.rollback()
            logger.error(f"Upsert装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod

    def batch_upsert_by_device_uri_and_date(
        db: Session,
        items: List[Dict[str, Any]]
    ) -> List[DeviceEvaluation]:
        """
        批量按装置URI和统计日期进行更新插入(upsert)
        
        Args:
            db: 数据库会话
            items: upsert数据列表，每项需包含device_uri, statistics_time和其他评估数据
        
        Returns:
            List[DeviceEvaluation]: 创建或更新的评估对象列表
        """
        try:
            # 设置 created/updated 时间
            now = datetime.now()
            for item in items:
                item.setdefault("created_time", now)
                item["updated_time"] = now

            stmt = insert(DeviceEvaluation).values(items)

            update_columns = {
                c.name: getattr(stmt.excluded, c.name)
                for c in DeviceEvaluation.__table__.columns
                if c.name not in ["id", "created_time"]  # created_time 不更新
            }

            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["device_uri", "statistics_time"],
                set_=update_columns
            ).returning(DeviceEvaluation)

            result = db.execute(upsert_stmt)
            db.commit()
            
            # 获取返回的记录
            inserted_records = result.scalars().all()
            
            logger.info(f"批量upsert装置评估记录成功，共处理 {len(inserted_records)} 条记录")
            
            return list(inserted_records)

        except Exception as e:
            db.rollback()
            logger.error(f"批量upsert装置评估记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, evaluation_id: str) -> Optional[DeviceEvaluation]:
        """
        根据ID获取评估记录
        
        Args:
            db: 数据库会话
            evaluation_id: 评估记录ID (UUID字符串)
        
        Returns:
            Optional[DeviceEvaluation]: 评估对象
        """
        statement = select(DeviceEvaluation).where(DeviceEvaluation.id == evaluation_id)
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
                statement = statement.where((DeviceEvaluation.device_uri == device_uri)|(DeviceEvaluation.parent_device_uri == device_uri))
            statement=statement.where(DeviceEvaluation.statistics_time == date.today())
            # 按创建时间倒序排列
            statement = statement.order_by(desc(DeviceEvaluation.statistics_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(DeviceEvaluation)
            # 应用相同的筛选条件到计数查询
            if device_name:
                count_statement = count_statement.where(DeviceEvaluation.device_name.like(f"%{device_name}%"))

            count_statement=count_statement.where(DeviceEvaluation.statistics_time == date.today())

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