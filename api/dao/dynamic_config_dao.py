#!/usr/bin/env python3
"""
DAO层 - 动态配置参数数据访问对象 - 使用SQLModel
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlmodel import Session, select, func, desc

from api.bean.dynamic_config import DynamicConfig

logger = logging.getLogger(__name__)


class DynamicConfigDAO:
    """动态配置参数DAO"""
    
    @staticmethod
    def create(db: Session, config_data: Dict[str, Any]) -> DynamicConfig:
        """
        创建配置参数 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_data: 配置数据字典
        
        Returns:
            DynamicConfig: 创建的配置对象
        """
        try:
            # SQLModel自动进行数据验证
            config = DynamicConfig(**config_data)

            db.add(config)
            db.commit()
            db.refresh(config)
            
            logger.info(f"创建配置参数成功: ID={config.id}, key={config.config_key}")
            return config
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def get_by_id(db: Session, config_id: str) -> Optional[DynamicConfig]:
        """
        根据ID查询配置 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_id: 配置ID
        
        Returns:
            Optional[DynamicConfig]: 配置对象，不存在则返回None
        """
        statement = select(DynamicConfig).where(DynamicConfig.id == config_id)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_key(db: Session, config_key: str) -> Optional[DynamicConfig]:
        """
        根据配置键查询配置
        
        Args:
            db: 数据库会话
            config_key: 配置键
        
        Returns:
            Optional[DynamicConfig]: 配置对象，不存在则返回None
        """
        statement = select(DynamicConfig).where(DynamicConfig.config_key == config_key)
        return db.exec(statement).first()
    
    @staticmethod
    def get_by_group(db: Session, config_group: str, include_disabled: bool = False) -> List[DynamicConfig]:
        """
        根据配置分组查询配置列表
        
        Args:
            db: 数据库会话
            config_group: 配置分组
            include_disabled: 是否包含已禁用的配置，默认False
        
        Returns:
            List[DynamicConfig]: 配置对象列表
        """
        statement = select(DynamicConfig).where(DynamicConfig.config_group == config_group)
        if not include_disabled:
            statement = statement.where(DynamicConfig.is_enabled == True)
        statement = statement.order_by(DynamicConfig.config_key)
        return db.exec(statement).all()
    
    @staticmethod
    def get_all_enabled(db: Session) -> List[DynamicConfig]:
        """
        查询所有启用的配置
        
        Args:
            db: 数据库会话
        
        Returns:
            List[DynamicConfig]: 启用的配置列表
        """
        statement = select(DynamicConfig).where(
            DynamicConfig.is_enabled == True
        ).order_by(DynamicConfig.config_group, DynamicConfig.config_key)
        return db.exec(statement).all()
    
    @staticmethod
    def query_list(
        db: Session,
        config_key: Optional[str] = None,
        config_group: Optional[str] = None,
        config_type: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询配置列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_key: 配置键筛选（模糊匹配）
            config_group: 配置分组筛选
            config_type: 配置类型筛选
            is_enabled: 是否启用筛选
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含配置列表和分页信息的字典
        """
        try:
            # 构建select语句
            statement = select(DynamicConfig)
            
            # 配置键筛选（模糊匹配）
            if config_key:
                statement = statement.where(DynamicConfig.config_key.like(f"%{config_key}%"))
            
            # 配置分组筛选
            if config_group:
                statement = statement.where(DynamicConfig.config_group == config_group)
            
            # 配置类型筛选
            if config_type:
                statement = statement.where(DynamicConfig.config_type == config_type)
            
            # 启用状态筛选
            if is_enabled is not None:
                statement = statement.where(DynamicConfig.is_enabled == is_enabled)
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(DynamicConfig.created_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(DynamicConfig)
            # 应用相同的筛选条件到计数查询
            if config_key:
                count_statement = count_statement.where(DynamicConfig.config_key.like(f"%{config_key}%"))
            if config_group:
                count_statement = count_statement.where(DynamicConfig.config_group == config_group)
            if config_type:
                count_statement = count_statement.where(DynamicConfig.config_type == config_type)
            if is_enabled is not None:
                count_statement = count_statement.where(DynamicConfig.is_enabled == is_enabled)
            
            total = db.exec(count_statement).one()
            
            # 分页
            offset = (page_no - 1) * page_size
            statement = statement.offset(offset).limit(page_size)
            configs = db.exec(statement).all()
            
            # 计算总页数
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            
            logger.info(f"查询配置参数列表成功，总数: {total}, 当前页: {page_no}")
            
            return {
                "configs": configs,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
            }
            
        except Exception as e:
            logger.error(f"查询配置参数列表失败: {str(e)}")
            raise

    @staticmethod
    def update(db: Session, config_id: str, update_data: Dict[str, Any]) -> Optional[DynamicConfig]:
        """
        更新配置 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_id: 配置ID
            update_data: 更新数据字典
        
        Returns:
            Optional[DynamicConfig]: 更新后的配置对象
        """
        try:
            statement = select(DynamicConfig).where(DynamicConfig.id == config_id)
            config = db.exec(statement).first()
            
            if not config:
                logger.warning(f"未找到ID为 {config_id} 的配置")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            # 更新updated_time
            config.updated_time = datetime.now()
            
            db.add(config)
            db.commit()
            db.refresh(config)
            
            logger.info(f"更新配置参数成功: ID={config_id}, key={config.config_key}")
            return config
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def update_by_key(db: Session, config_key: str, update_data: Dict[str, Any]) -> Optional[DynamicConfig]:
        """
        根据配置键更新配置
        
        Args:
            db: 数据库会话
            config_key: 配置键
            update_data: 更新数据字典
        
        Returns:
            Optional[DynamicConfig]: 更新后的配置对象
        """
        try:
            statement = select(DynamicConfig).where(DynamicConfig.config_key == config_key)
            config = db.exec(statement).first()
            
            if not config:
                logger.warning(f"未找到key为 {config_key} 的配置")
                return None
            
            # 更新字段
            for key, value in update_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            
            # 更新updated_time
            config.updated_time = datetime.now()
            
            db.add(config)
            db.commit()
            db.refresh(config)
            
            logger.info(f"更新配置参数成功: key={config_key}")
            return config
            
        except Exception as e:
            db.rollback()
            logger.error(f"更新配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def delete(db: Session, config_id: str) -> bool:
        """
        删除配置 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_id: 配置ID
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(DynamicConfig).where(DynamicConfig.id == config_id)
            config = db.exec(statement).first()
            
            if not config:
                logger.warning(f"未找到ID为 {config_id} 的配置")
                return False
            
            db.delete(config)
            db.commit()
            
            logger.info(f"删除配置参数成功: ID={config_id}, key={config.config_key}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_by_key(db: Session, config_key: str) -> bool:
        """
        根据配置键删除配置
        
        Args:
            db: 数据库会话
            config_key: 配置键
        
        Returns:
            bool: 是否删除成功
        """
        try:
            statement = select(DynamicConfig).where(DynamicConfig.config_key == config_key)
            config = db.exec(statement).first()
            
            if not config:
                logger.warning(f"未找到key为 {config_key} 的配置")
                return False
            
            db.delete(config)
            db.commit()
            
            logger.info(f"删除配置参数成功: key={config_key}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"删除配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def batch_create(db: Session, config_list: List[Dict[str, Any]]) -> List[DynamicConfig]:
        """
        批量创建配置
        
        Args:
            db: 数据库会话
            config_list: 配置数据列表
        
        Returns:
            List[DynamicConfig]: 创建的配置对象列表
        """
        try:
            created_configs = []
            for config_data in config_list:
                config = DynamicConfig(**config_data)
                db.add(config)
                created_configs.append(config)
            
            db.commit()
            for config in created_configs:
                db.refresh(config)
            
            logger.info(f"批量创建配置参数成功，共创建 {len(created_configs)} 条记录")
            return created_configs
            
        except Exception as e:
            db.rollback()
            logger.error(f"批量创建配置参数失败: {str(e)}")
            raise

