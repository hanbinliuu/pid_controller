#!/usr/bin/env python3
"""
DAO层 - 回路信息数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc

from api.bean.loop_info import LoopInfo

logger = logging.getLogger(__name__)


class LoopInfoDAO:
    """回路信息DAO"""
    
    @staticmethod
    def create(db: Session, mapping_data: Dict[str, Any]) -> LoopInfo:
        """
        创建回路信息记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            mapping_data: 映射数据字典
        
        Returns:
            LoopInfo: 创建的映射对象
        """
        try:
            # SQLModel自动进行数据验证
            mapping = LoopInfo(**mapping_data)
            
            db.add(mapping)
            db.commit()
            db.refresh(mapping)
            
            logger.info(f"创建回路信息记录成功: ID={mapping.id}, loop_uri={mapping.loop_uri}")
            return mapping
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, mapping_id: int) -> Optional[LoopInfo]:
        """
        根据ID查询映射记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            mapping_id: 映射记录ID
        
        Returns:
            Optional[LoopInfo]: 映射对象，不存在则返回None
        """
        statement = select(LoopInfo).where(LoopInfo.id == mapping_id)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_loop_uri(db: Session, loop_uri: str, include_inactive: bool = False) -> Optional[LoopInfo]:
        """
        根据loop_uri查询映射记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            include_inactive: 是否包含已逻辑删除的回路，默认False
        
        Returns:
            Optional[LoopInfo]: 映射对象，不存在或已逻辑删除则返回None
        """
        statement = select(LoopInfo).where(LoopInfo.loop_uri == loop_uri)
        if not include_inactive:
            statement = statement.where(LoopInfo.is_active == True)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_loop_path(db: Session, loop_path: str, include_inactive: bool = False) -> List[LoopInfo]:
        """
        根据loop_path查询映射记录
        
        Args:
            db: 数据库会话
            loop_path: 回路路径
            include_inactive: 是否包含已逻辑删除的回路，默认False
        
        Returns:
            Optional[LoopInfo]: 映射对象，不存在或已逻辑删除则返回None
        """
        statement = select(LoopInfo).where(LoopInfo.loop_path.like(f"%{loop_path}%"))
        if not include_inactive:
            statement = statement.where(LoopInfo.is_active == True)
        return db.exec(statement).all()
    
    @staticmethod
    def get_active_loops(db: Session) -> List[LoopInfo]:
        """
        查询所有激活的回路记录
        
        Args:
            db: 数据库会话
        
        Returns:
            List[LoopInfo]: 激活的回路记录列表
        """
        statement = select(LoopInfo).where(
            LoopInfo.is_active == True
        ).order_by(LoopInfo.created_time.desc())
        return db.exec(statement).all()
    
    @staticmethod
    def query_list(
        db: Session,
        loop_name: Optional[str] = None,
        loop_uri: Optional[str] = None,
        loop_path: Optional[str] = None,
        is_active: Optional[bool] = True,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询映射记录列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选（模糊匹配）
            loop_uri: 回路URI筛选（模糊匹配）
            loop_path: 回路路径筛选（模糊匹配）
            is_active: 是否激活
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(LoopInfo)
            
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            
            # 回路URI筛选（模糊匹配）
            if loop_uri:
                statement = statement.where(LoopInfo.loop_uri.like(f"%{loop_uri}%"))
            
            # 回路路径筛选（模糊匹配）
            if loop_path:
                statement = statement.where(LoopInfo.loop_path.like(f"%{loop_path}%"))
            
            # 激活状态筛选
            if is_active is not None:
                statement = statement.where(LoopInfo.is_active == is_active)
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(LoopInfo.created_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(LoopInfo)
            # 应用相同的筛选条件到计数查询
            if loop_name:
                count_statement = count_statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            if loop_uri:
                count_statement = count_statement.where(LoopInfo.loop_uri.like(f"%{loop_uri}%"))
            if loop_path:
                count_statement = count_statement.where(LoopInfo.loop_path.like(f"%{loop_path}%"))
            if is_active is not None:
                count_statement = count_statement.where(LoopInfo.is_active == is_active)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            mappings = db.exec(statement).all()
            
            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询回路信息记录成功，总数: {total}, 当前页: {page_no}")
            
            return {
                "mappings": mappings,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
            }
            
        except Exception as e:
            logger.error(f"查询回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update(db: Session, mapping_id: int, update_data: Dict[str, Any]) -> Optional[LoopInfo]:
        """
        更新映射记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            mapping_id: 映射记录ID
            update_data: 更新数据字典
        
        Returns:
            Optional[LoopInfo]: 更新后的映射对象
        """
        try:
            statement = select(LoopInfo).where(LoopInfo.id == mapping_id)
            mapping = db.exec(statement).first()
            
            if not mapping:
                logger.warning(f"未找到ID为 {mapping_id} 的映射记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(mapping, key):
                    setattr(mapping, key, value)
            
            # 更新updated_time
            mapping.updated_time = datetime.now()
            
            db.add(mapping)
            db.commit()
            db.refresh(mapping)
            
            logger.info(f"更新回路信息记录成功: ID={mapping_id}")
            return mapping
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def update_by_loop_uri(db: Session, loop_uri: str, update_data: Dict[str, Any]) -> Optional[LoopInfo]:
        """
        根据loop_uri更新映射记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
            update_data: 更新数据字典
        
        Returns:
            Optional[LoopInfo]: 更新后的映射对象
        """
        try:
            statement = select(LoopInfo).where(LoopInfo.loop_uri == loop_uri)
            mapping = db.exec(statement).first()
            
            if not mapping:
                logger.warning(f"未找到loop_uri为 {loop_uri} 的映射记录")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(mapping, key):
                    setattr(mapping, key, value)
            
            # 更新updated_time
            mapping.updated_time = datetime.now()
            
            db.add(mapping)
            db.commit()
            db.refresh(mapping)
            
            logger.info(f"更新回路信息记录成功: loop_uri={loop_uri}")
            return mapping
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, mapping_id: int) -> bool:
        """
        删除映射记录 - SQLModel方式
        
        Args:
            db: 数据库会话
            mapping_id: 映射记录ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(LoopInfo).where(LoopInfo.id == mapping_id)
            mapping = db.exec(statement).first()
            
            if not mapping:
                logger.warning(f"未找到ID为 {mapping_id} 的映射记录")
                return False
            
            db.delete(mapping)
            db.commit()
            
            logger.info(f"删除回路信息记录成功: ID={mapping_id}, loop_uri={mapping.loop_uri}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_by_loop_uri(db: Session, loop_uri: str) -> bool:
        """
        根据loop_uri删除映射记录
        
        Args:
            db: 数据库会话
            loop_uri: 回路URI
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(LoopInfo).where(LoopInfo.loop_uri == loop_uri)
            mapping = db.exec(statement).first()
            
            if not mapping:
                logger.warning(f"未找到loop_uri为 {loop_uri} 的映射记录")
                return False
            
            db.delete(mapping)
            db.commit()
            
            logger.info(f"删除回路信息记录成功: loop_uri={loop_uri}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除回路信息记录失败: {str(e)}")
            raise
    
    @staticmethod
    def get_uri_to_path_map(db: Session) -> Dict[str, str]:
        """
        获取loop_uri到loop_path的映射字典
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict[str, str]: uri到path的映射字典
        """
        try:
            statement = select(LoopInfo).where(
                LoopInfo.is_active == True
            )
            mappings = db.exec(statement).all()
            
            uri_to_path_map = {m.loop_uri: m.loop_path for m in mappings}
            return uri_to_path_map
            
        except Exception as e:
            logger.error(f"获取URI到路径映射字典失败: {str(e)}")
            raise
    
    @staticmethod
    def get_path_to_uri_map(db: Session) -> Dict[str, str]:
        """
        获取loop_path到loop_uri的映射字典
        
        Args:
            db: 数据库会话
        
        Returns:
            Dict[str, str]: path到uri的映射字典
        """
        try:
            statement = select(LoopInfo).where(
                LoopInfo.is_active == True
            )
            mappings = db.exec(statement).all()
            
            path_to_uri_map = {m.loop_path: m.loop_uri for m in mappings}
            return path_to_uri_map
            
        except Exception as e:
            logger.error(f"获取路径到URI映射字典失败: {str(e)}")
            raise