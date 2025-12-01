#!/usr/bin/env python3
"""
DAO层 - 条件剔除回路数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc, or_

from api.bean.excluded_loop import ExcludedLoop

logger = logging.getLogger(__name__)


class ExcludedLoopDAO:
    """条件剔除回路DAO"""
    
    @staticmethod
    def create(db: Session, excluded_data: Dict[str, Any]) -> ExcludedLoop:
        """
        创建条件剔除记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            excluded_data: 剔除数据字典
        
        Returns:
            ExcludedLoop: 创建的剔除对象
        """
        try:
            # 添加时间戳
            excluded_data['created_time'] = datetime.now()
            excluded_data['updated_time'] = datetime.now()
            
            # SQLModel自动进行数据验证
            excluded = ExcludedLoop(**excluded_data)
            
            db.add(excluded)
            db.commit()
            db.refresh(excluded)
            
            logger.info(f"创建条件剔除记录成功: ID={excluded.id}, URI={excluded.uri}, 类型={excluded.type}")
            return excluded
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, excluded_id: int) -> Optional[ExcludedLoop]:
        """
        根据ID查询剔除记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
        
        Returns:
            Optional[ExcludedLoop]: 剔除对象，不存在则返回None
        """
        statement = select(ExcludedLoop).where(ExcludedLoop.id == excluded_id)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_uri(db: Session, uri: str) -> Optional[ExcludedLoop]:
        """
        根据URI查询剔除记录
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
        
        Returns:
            Optional[ExcludedLoop]: 剔除对象，不存在则返回None
        """
        statement = select(ExcludedLoop).where(ExcludedLoop.uri == uri)
        return db.exec(statement).first()
    
    @staticmethod
    def query_list(
        db: Session,
        name: Optional[str] = None,
        uri: Optional[str] = None,
        type: Optional[str] = None,
        is_excluded: Optional[bool] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询剔除记录列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            name: 名称筛选（模糊匹配）
            uri: URI筛选（模糊匹配）
            type: 类型筛选（回路/装置）
            is_excluded: 是否剔除
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(ExcludedLoop)
            
            # 名称筛选（模糊匹配）
            if name:
                statement = statement.where(ExcludedLoop.name.like(f"%{name}%"))
            
            # URI筛选（模糊匹配）
            if uri:
                statement = statement.where(ExcludedLoop.uri.like(f"%{uri}%"))
            
            # 类型筛选
            if type:
                statement = statement.where(ExcludedLoop.type == type)
            
            # 剔除状态筛选
            if is_excluded is not None:
                statement = statement.where(ExcludedLoop.is_excluded == is_excluded)
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(ExcludedLoop.created_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(ExcludedLoop)
            # 应用相同的筛选条件到计数查询
            if name:
                count_statement = count_statement.where(ExcludedLoop.name.like(f"%{name}%"))
            if uri:
                count_statement = count_statement.where(ExcludedLoop.uri.like(f"%{uri}%"))
            if type:
                count_statement = count_statement.where(ExcludedLoop.type == type)
            if is_excluded is not None:
                count_statement = count_statement.where(ExcludedLoop.is_excluded == is_excluded)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            excluded_loops = db.exec(statement).all()
            
            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询条件剔除记录成功，总数: {total}, 当前页: {page_no}")
            
            return {
                "excluded_loops": excluded_loops,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
            }
            
        except Exception as e:
            logger.error(f"查询条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update(db: Session, excluded_id: int, update_data: Dict[str, Any]) -> Optional[ExcludedLoop]:
        """
        更新剔除记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
            update_data: 更新数据字典
        
        Returns:
            Optional[ExcludedLoop]: 更新后的剔除对象
        """
        try:
            statement = select(ExcludedLoop).where(ExcludedLoop.id == excluded_id)
            excluded = db.exec(statement).first()
            
            if not excluded:
                logger.warning(f"未找到ID为 {excluded_id} 的剔除记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(excluded, key) and key not in ['id', 'created_time']:
                    setattr(excluded, key, value)
            
            # 更新updated_time
            excluded.updated_time = datetime.now()
            
            db.add(excluded)
            db.commit()
            db.refresh(excluded)
            
            logger.info(f"更新条件剔除记录成功: ID={excluded_id}")
            return excluded
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update_by_uri(db: Session, uri: str, update_data: Dict[str, Any]) -> Optional[ExcludedLoop]:
        """
        根据URI更新剔除记录
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
            update_data: 更新数据字典
        
        Returns:
            Optional[ExcludedLoop]: 更新后的剔除对象
        """
        try:
            statement = select(ExcludedLoop).where(ExcludedLoop.uri == uri)
            excluded = db.exec(statement).first()
            
            if not excluded:
                logger.warning(f"未找到URI为 {uri} 的剔除记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(excluded, key) and key not in ['id', 'uri', 'created_time']:
                    setattr(excluded, key, value)
            
            # 更新updated_time
            excluded.updated_time = datetime.now()
            
            db.add(excluded)
            db.commit()
            db.refresh(excluded)
            
            logger.info(f"更新条件剔除记录成功: URI={uri}")
            return excluded
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, excluded_id: int) -> bool:
        """
        删除剔除记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            excluded_id: 剔除记录ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(ExcludedLoop).where(ExcludedLoop.id == excluded_id)
            excluded = db.exec(statement).first()
            
            if not excluded:
                logger.warning(f"未找到ID为 {excluded_id} 的剔除记录")
                return False
            
            db.delete(excluded)
            db.commit()
            
            logger.info(f"删除条件剔除记录成功: ID={excluded_id}, URI={excluded.uri}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除条件剔除记录失败: {str(e)}")
            raise
    
    @staticmethod
    def upsert_by_uri(
        db: Session,
        uri: str,
        excluded_data: Dict[str, Any]
    ) -> ExcludedLoop:
        """
        按URI进行更新插入(upsert)
        如果记录已存在则更新，否则创建新记录
        
        Args:
            db: 数据库会话
            uri: 回路/装置URI
            excluded_data: 剔除数据字典
        
        Returns:
            ExcludedLoop: 创建或更新的剔除对象
        """
        try:
            # 确保URI在数据中
            excluded_data['uri'] = uri
            
            # 查找是否存在记录
            existing = ExcludedLoopDAO.get_by_uri(db, uri)
            
            if existing:
                # 更新现有记录
                for key, value in excluded_data.items():
                    if hasattr(existing, key) and key not in ['id', 'created_time']:
                        setattr(existing, key, value)
                
                existing.updated_time = datetime.now()
                db.add(existing)
                db.commit()
                db.refresh(existing)
                
                logger.info(f"更新条件剔除记录: URI={uri}, ID={existing.id}")
                return existing
            else:
                # 创建新记录
                excluded_data['created_time'] = datetime.now()
                excluded_data['updated_time'] = datetime.now()
                excluded = ExcludedLoop(**excluded_data)
                
                db.add(excluded)
                db.commit()
                db.refresh(excluded)
                
                logger.info(f"创建条件剔除记录: URI={uri}, ID={excluded.id}")
                return excluded
                
        except Exception as e:
            db.rollback()
            logger.error(f"Upsert条件剔除记录失败: {str(e)}")
            raise
