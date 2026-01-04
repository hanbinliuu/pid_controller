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
            
            logger.info(f"创建配置参数成功: key={config.config_key}")
            return config
            
        except Exception as e:
            db.rollback()
            logger.error(f"创建配置参数失败: {str(e)}")
            raise
    
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
    def get_by_group(db: Session, config_group: str) -> List[DynamicConfig]:
        """
        根据配置分组查询配置列表
        
        Args:
            db: 数据库会话
            config_group: 配置分组
        
        Returns:
            List[DynamicConfig]: 配置对象列表
        """
        statement = select(DynamicConfig).where(
            DynamicConfig.config_group == config_group
        ).order_by(DynamicConfig.config_key)
        return db.exec(statement).all()
    
    @staticmethod
    def get_all(db: Session) -> List[DynamicConfig]:
        """
        查询所有配置
        
        Args:
            db: 数据库会话
        
        Returns:
            List[DynamicConfig]: 所有配置列表
        """
        statement = select(DynamicConfig).order_by(
            DynamicConfig.config_group, 
            DynamicConfig.config_key
        )
        return db.exec(statement).all()
    
    @staticmethod
    def query_list(
        db: Session,
        config_key: Optional[str] = None,
        config_group: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询配置列表 - SQLModel方式
        
        Args:
            db: 数据库会话
            config_key: 配置键筛选（模糊匹配）
            config_group: 配置分组筛选
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
            
            # 按创建时间倒序排列
            statement = statement.order_by(desc(DynamicConfig.created_time))
            
            # 获取总数
            count_statement = select(func.count()).select_from(DynamicConfig)
            # 应用相同的筛选条件到计数查询
            if config_key:
                count_statement = count_statement.where(DynamicConfig.config_key.like(f"%{config_key}%"))
            if config_group:
                count_statement = count_statement.where(DynamicConfig.config_group == config_group)
            
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





