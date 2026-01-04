#!/usr/bin/env python3
"""
业务逻辑层 - 动态配置参数服务
"""
import logging
import json
from typing import List, Optional, Dict, Any
from sqlmodel import Session

from api.dao.dynamic_config_dao import DynamicConfigDAO
from api.bean.dynamic_config import DynamicConfig

logger = logging.getLogger(__name__)


class DynamicConfigService:
    """动态配置参数业务逻辑服务"""
    
    @staticmethod
    def create_config(
        db: Session,
        config_key: str,
        config_value: Optional[str] = None,
        config_type: Optional[str] = "string",
        config_group: Optional[str] = None,
        description: Optional[str] = None,
        is_enabled: bool = True,
        created_by: Optional[str] = None
    ) -> DynamicConfig:
        """
        创建新的配置参数
        
        Args:
            db: 数据库会话
            config_key: 配置键（唯一）
            config_value: 配置值
            config_type: 配置类型（string, number, boolean, json等）
            config_group: 配置分组
            description: 配置描述
            is_enabled: 是否启用
            created_by: 创建者
        
        Returns:
            DynamicConfig: 创建的配置对象
        """
        try:
            # 检查配置键是否已存在
            existing = DynamicConfigDAO.get_by_key(db, config_key)
            if existing:
                raise ValueError(f"配置键 '{config_key}' 已存在")
            
            config_data = {
                "config_key": config_key,
                "config_value": config_value,
                "config_type": config_type,
                "config_group": config_group,
                "description": description,
                "is_enabled": is_enabled,
                "created_by": created_by
            }
            
            return DynamicConfigDAO.create(db, config_data)
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"创建配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def get_config_by_key(db: Session, config_key: str) -> Optional[DynamicConfig]:
        """
        根据配置键获取配置
        
        Args:
            db: 数据库会话
            config_key: 配置键
        
        Returns:
            Optional[DynamicConfig]: 配置对象
        """
        return DynamicConfigDAO.get_by_key(db, config_key)
    
    @staticmethod
    def get_config_by_id(db: Session, config_id: str) -> Optional[DynamicConfig]:
        """
        根据ID获取配置
        
        Args:
            db: 数据库会话
            config_id: 配置ID
        
        Returns:
            Optional[DynamicConfig]: 配置对象
        """
        return DynamicConfigDAO.get_by_id(db, config_id)
    
    @staticmethod
    def get_configs_by_group(db: Session, config_group: str, include_disabled: bool = False) -> List[DynamicConfig]:
        """
        根据配置分组获取配置列表
        
        Args:
            db: 数据库会话
            config_group: 配置分组
            include_disabled: 是否包含已禁用的配置
        
        Returns:
            List[DynamicConfig]: 配置列表
        """
        return DynamicConfigDAO.get_by_group(db, config_group, include_disabled)
    
    @staticmethod
    def get_all_enabled_configs(db: Session) -> List[DynamicConfig]:
        """
        获取所有启用的配置
        
        Args:
            db: 数据库会话
        
        Returns:
            List[DynamicConfig]: 启用的配置列表
        """
        return DynamicConfigDAO.get_all_enabled(db)
    
    @staticmethod
    def list_configs(
        db: Session,
        config_key: Optional[str] = None,
        config_group: Optional[str] = None,
        config_type: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询配置列表
        
        Args:
            db: 数据库会话
            config_key: 配置键（模糊匹配）
            config_group: 配置分组
            config_type: 配置类型
            is_enabled: 是否启用
            page_no: 页码
            page_size: 每页数量
        
        Returns:
            Dict: 包含配置列表和分页信息
        """
        result = DynamicConfigDAO.query_list(
            db,
            config_key=config_key,
            config_group=config_group,
            config_type=config_type,
            is_enabled=is_enabled,
            page_no=page_no,
            page_size=page_size
        )

        # 获取配置列表
        configs = result.get('configs', [])
        pagination = result["pagination"]
        config_list = [
            {
                "id": config.id,
                "config_key": config.config_key,
                "config_value": config.config_value,
                "config_type": config.config_type,
                "config_group": config.config_group,
                "description": config.description,
                "is_enabled": config.is_enabled,
                "created_by": config.created_by,
                "updated_by": config.updated_by,
                "created_time": config.created_time.isoformat() if config.created_time else None,
                "updated_time": config.updated_time.isoformat() if config.updated_time else None
            }
            for config in configs
        ]

        return {
            "configs": config_list,
            "pagination": pagination
        }
    
    @staticmethod
    def update_config(
        db: Session,
        config_key: str,
        config_value: Optional[str] = None,
        config_type: Optional[str] = None,
        config_group: Optional[str] = None,
        description: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        updated_by: Optional[str] = None
    ) -> Optional[DynamicConfig]:
        """
        更新配置参数
        
        Args:
            db: 数据库会话
            config_key: 配置键（用于查找要更新的记录）
            config_value: 新的配置值
            config_type: 新的配置类型
            config_group: 新的配置分组
            description: 新的描述
            is_enabled: 是否启用
            updated_by: 更新者
        
        Returns:
            Optional[DynamicConfig]: 更新后的配置对象
        """
        try:
            update_data = {}
            if config_value is not None:
                update_data["config_value"] = config_value
            if config_type is not None:
                update_data["config_type"] = config_type
            if config_group is not None:
                update_data["config_group"] = config_group
            if description is not None:
                update_data["description"] = description
            if is_enabled is not None:
                update_data["is_enabled"] = is_enabled
            if updated_by is not None:
                update_data["updated_by"] = updated_by
            
            return DynamicConfigDAO.update_by_key(db, config_key, update_data)
            
        except Exception as e:
            logger.error(f"更新配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def update_config_by_id(
        db: Session,
        config_id: str,
        config_value: Optional[str] = None,
        config_type: Optional[str] = None,
        config_group: Optional[str] = None,
        description: Optional[str] = None,
        is_enabled: Optional[bool] = None,
        updated_by: Optional[str] = None
    ) -> Optional[DynamicConfig]:
        """
        根据ID更新配置参数
        
        Args:
            db: 数据库会话
            config_id: 配置ID
            config_value: 新的配置值
            config_type: 新的配置类型
            config_group: 新的配置分组
            description: 新的描述
            is_enabled: 是否启用
            updated_by: 更新者
        
        Returns:
            Optional[DynamicConfig]: 更新后的配置对象
        """
        try:
            update_data = {}
            if config_value is not None:
                update_data["config_value"] = config_value
            if config_type is not None:
                update_data["config_type"] = config_type
            if config_group is not None:
                update_data["config_group"] = config_group
            if description is not None:
                update_data["description"] = description
            if is_enabled is not None:
                update_data["is_enabled"] = is_enabled
            if updated_by is not None:
                update_data["updated_by"] = updated_by
            
            return DynamicConfigDAO.update(db, config_id, update_data)
            
        except Exception as e:
            logger.error(f"更新配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def delete_config(db: Session, config_key: str) -> bool:
        """
        删除配置参数
        
        Args:
            db: 数据库会话
            config_key: 配置键
        
        Returns:
            bool: 是否删除成功
        """
        return DynamicConfigDAO.delete_by_key(db, config_key)
    
    @staticmethod
    def delete_config_by_id(db: Session, config_id: str) -> bool:
        """
        根据ID删除配置参数
        
        Args:
            db: 数据库会话
            config_id: 配置ID
        
        Returns:
            bool: 是否删除成功
        """
        return DynamicConfigDAO.delete(db, config_id)
    
    @staticmethod
    def get_config_value(db: Session, config_key: str, default_value: Any = None) -> Any:
        """
        获取配置值（自动类型转换）
        
        Args:
            db: 数据库会话
            config_key: 配置键
            default_value: 默认值（如果配置不存在或未启用）
        
        Returns:
            Any: 配置值（根据config_type自动转换类型）
        """
        config = DynamicConfigDAO.get_by_key(db, config_key)
        
        if not config or not config.is_enabled:
            return default_value
        
        value = config.config_value
        if value is None:
            return default_value
        
        # 根据配置类型进行类型转换
        try:
            if config.config_type == "number":
                # 尝试转换为整数或浮点数
                if '.' in value:
                    return float(value)
                return int(value)
            elif config.config_type == "boolean":
                return value.lower() in ("true", "1", "yes", "on")
            elif config.config_type == "json":
                return json.loads(value)
            else:
                return value
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning(f"配置值类型转换失败: config_key={config_key}, value={value}, type={config.config_type}, error={str(e)}")
            return value  # 转换失败时返回原始字符串
    
    @staticmethod
    def batch_create_configs(
        db: Session,
        config_list: List[Dict[str, Any]]
    ) -> List[DynamicConfig]:
        """
        批量创建配置参数
        
        Args:
            db: 数据库会话
            config_list: 配置数据列表，每个元素包含config_key、config_value等字段
        
        Returns:
            List[DynamicConfig]: 创建的配置对象列表
        """
        try:
            # 检查是否有重复的config_key
            keys = [item.get("config_key") for item in config_list if item.get("config_key")]
            if len(keys) != len(set(keys)):
                raise ValueError("配置列表中存在重复的config_key")
            
            # 检查是否与现有配置冲突
            for item in config_list:
                config_key = item.get("config_key")
                if config_key:
                    existing = DynamicConfigDAO.get_by_key(db, config_key)
                    if existing:
                        raise ValueError(f"配置键 '{config_key}' 已存在")
            
            return DynamicConfigDAO.batch_create(db, config_list)
            
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"批量创建配置参数失败: {str(e)}")
            raise





