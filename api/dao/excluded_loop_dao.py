#!/usr/bin/env python3
"""
DAO层 - 条件剔除回路数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc, or_

from api.bean.excluded_loop import ExcludedLoop
from api.bean.loop_info import LoopInfo

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
        loop_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        uri: Optional[str] = None,
        loop_type: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询剔除记录列表 - SQLModel方式
        关联loop_info表获取回路名称
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选（模糊匹配）
            device_uri: 装置URI筛选（模糊匹配loop_info.loop_path字段）
            uri: 回路URI筛选（模糊匹配）
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含记录列表和分页信息的字典
        """
        try:
            # 构建select语句，关联loop_info表
            statement = select(
                ExcludedLoop,
                LoopInfo.loop_name,
                LoopInfo.loop_type
            ).join(
                LoopInfo,
                ExcludedLoop.uri == LoopInfo.loop_uri
            )
            
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            
            # 装置URI筛选（模糊匹配loop_path字段）
            if device_uri:
                statement = statement.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
            
            # 回路URI筛选（模糊匹配）
            if uri:
                statement = statement.where(ExcludedLoop.uri.like(f"%{uri}%"))
            
            # 回路类型筛选（模糊匹配）
            if loop_type:
                statement = statement.where(LoopInfo.loop_type==loop_type)
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(ExcludedLoop.created_time))
            
            # 获取总数 - 需要应用相同的筛选条件
            count_statement = select(func.count()).select_from(ExcludedLoop)
            
            # 关联loop_info表（与主查询保持一致，使用join）
            count_statement = count_statement.join(
                LoopInfo,
                ExcludedLoop.uri == LoopInfo.loop_uri
            )
            
            # 回路名称筛选
            if loop_name:
                count_statement = count_statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            
            # 装置URI筛选（模糊匹配loop_path字段）
            if device_uri:
                count_statement = count_statement.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
            
            # 回路URI筛选
            if uri:
                count_statement = count_statement.where(ExcludedLoop.uri.like(f"%{uri}%"))
            
            # 回路类型筛选
            if loop_type:
                count_statement = count_statement.where(LoopInfo.loop_type==loop_type)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            results = db.exec(statement).all()
            
            # 组装结果，添加loop_name和loop_type字段
            excluded_loops = []
            for excluded_loop, loop_name_value, loop_type_value in results:
                # 创建一个字典包含所有字段
                loop_dict = {
                    "id": excluded_loop.id,
                    "uri": excluded_loop.uri,
                    "loop_name": loop_name_value,  # 从loop_info表关联获取
                    "loop_type": loop_type_value,  # 从loop_info表关联获取
                    "reason": excluded_loop.reason,
                    "created_time": excluded_loop.created_time,
                    "updated_time": excluded_loop.updated_time
                }
                excluded_loops.append(loop_dict)
            
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
    def get_all_uris(
        db: Session,
        loop_name: Optional[str] = None,
        device_uri: Optional[str] = None,
        uri: Optional[str] = None,
        loop_type: Optional[str] = None
    ) -> List[str]:
        """
        获取所有剔除回路URI列表（支持筛选）
        
        Args:
            db: 数据库会话
            loop_name: 回路名称筛选（模糊匹配）
            device_uri: 装置URI筛选（模糊匹配loop_path字段）
            uri: 回路URI筛选（模糊匹配）
        
        Returns:
            List[str]: URI列表
        """
        try:
            # 构建select语句
            statement = select(ExcludedLoop.uri)
            
            # 如果有loop_name或device_uri或loop_type筛选，需要关联loop_info表
            if loop_name or device_uri or loop_type:
                statement = statement.join(
                    LoopInfo,
                    ExcludedLoop.uri == LoopInfo.loop_uri
                )
            
            # 回路名称筛选（模糊匹配）
            if loop_name:
                statement = statement.where(LoopInfo.loop_name.like(f"%{loop_name}%"))
            
            # 装置URI筛选（模糊匹配loop_path字段）
            if device_uri:
                statement = statement.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
            
            # 回路URI筛选（模糊匹配）
            if uri:
                statement = statement.where(ExcludedLoop.uri.like(f"%{uri}%"))
            
            # 回路类型筛选（模糊匹配）
            if loop_type:
                statement = statement.where(LoopInfo.loop_type==loop_type)
            
            # 按创建时间排序
            statement = statement.order_by(ExcludedLoop.created_time)
            
            results = db.exec(statement).all()
            
            logger.info(f"获取剔除URI列表成功，总数: {len(results)}")
            return list(results)
            
        except Exception as e:
            logger.error(f"获取剔除URI列表失败: {str(e)}")
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
