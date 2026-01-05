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
from core.config import Config

logger = logging.getLogger(__name__)


class DynamicConfigService:
    """动态配置参数业务逻辑服务"""
    
    @staticmethod
    def initialize_fixed_configs(db: Session) -> Dict[str, Any]:
        """
        初始化动态参数配置参数
        
        创建以下配置：
        1. virtual_gateway_device_id: 虚拟网关设备ID
        2. product_model_id: 产品（设备模型）ID
        3. default_resource_space: 默认资源空间
        
        如果配置已存在，则跳过创建
        
        Args:
            db: 数据库会话
            
        Returns:
            Dict: 初始化结果，包含创建数量和跳过数量
        """
        # 定义动态参数配置项
        fixed_configs = [
            {
                "config_key": "virtual_gateway_device_id",
                "config_value": Config.DEFAULT_VIRTUAL_GATEWAY_DEVICE_ID,
                "config_group": "iotda",
                "config_name": "虚拟网关设备ID"
            },
            {
                "config_key": "product_model_id",
                "config_value": Config.DEFAULT_PRODUCT_MODEL_ID,
                "config_group": "iotda",
                "config_name": "子设备产品ID"
            },
            {
                "config_key": "default_resource_space",
                "config_value": Config.DEFAULT_RESOURCE_SPACE,
                "config_group": "iotda",
                "config_name": "默认资源空间"
            }
        ]

        created_count = 0
        skipped_count = 0
        configs_result = []

        for config_data in fixed_configs:
            try:
                # 检查配置是否已存在
                existing = DynamicConfigDAO.get_by_key(db, config_data["config_key"])

                if existing:
                    logger.info(f"配置 '{config_data['config_key']}' 已存在，跳过创建")
                    skipped_count += 1
                    configs_result.append({
                        "config_key": existing.config_key,
                        "config_value": existing.config_value,
                        "status": "skipped",
                        "message": "配置已存在"
                    })
                else:
                    # 创建新配置
                    new_config = DynamicConfigDAO.create(db, config_data)
                    created_count += 1
                    configs_result.append({
                        "config_key": new_config.config_key,
                        "config_value": new_config.config_value,
                        "status": "created",
                        "message": "创建成功"
                    })
                    logger.info(f"创建配置 '{config_data['config_key']}' 成功")

            except Exception as e:
                logger.error(f"初始化配置 '{config_data['config_key']}' 失败: {str(e)}")
                configs_result.append({
                    "config_key": config_data["config_key"],
                    "status": "failed",
                    "message": str(e)
                })

        logger.info(f"动态参数配置初始化完成: 创建 {created_count} 个, 跳过 {skipped_count} 个")

        return {
            "created_count": created_count,
            "skipped_count": skipped_count,
            "configs": configs_result
        }

    @staticmethod
    def create_config(
        db: Session,
        config_key: str,
        config_value: Optional[str] = None,
        config_group: Optional[str] = None,
        config_name: Optional[str] = None,
    ) -> DynamicConfig:
        """
        创建新的配置参数

        Args:
            db: 数据库会话
            config_key: 配置键（唯一）
            config_value: 配置值
            config_type: 配置类型（string, number, boolean, json等）
            config_group: 配置分组
            config_name: 配置描述
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
                "config_group": config_group,
                "config_name": config_name,
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
    def get_configs_by_group(db: Session, config_group: str) -> List[DynamicConfig]:
        """
        根据配置分组获取配置列表

        Args:
            db: 数据库会话
            config_group: 配置分组

        Returns:
            List[DynamicConfig]: 配置列表
        """
        return DynamicConfigDAO.get_by_group(db, config_group)

    @staticmethod
    def get_all_configs(db: Session) -> List[DynamicConfig]:
        """
        获取所有配置

        Args:
            db: 数据库会话

        Returns:
            List[DynamicConfig]: 所有配置列表
        """
        return DynamicConfigDAO.get_all(db)
    @staticmethod
    def get_all_configs_map(db: Session) -> Dict[str, str]:
        """
        获取所有配置

        Args:
            db: 数据库会话

        Returns:
            List[DynamicConfig]: 所有配置列表
        """
        configs = DynamicConfigDAO.get_all(db)
        return {config.config_key: config.config_value for config in configs}

    @staticmethod
    def list_configs_page(
        db: Session,
        config_key: Optional[str] = None,
        config_group: Optional[str] = None,
        page_no: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        分页查询配置列表

        Args:
            db: 数据库会话
            config_key: 配置键（模糊匹配）
            config_group: 配置分组
            page_no: 页码
            page_size: 每页数量

        Returns:
            Dict: 包含配置列表和分页信息
        """
        result = DynamicConfigDAO.query_list(
            db,
            config_key=config_key,
            config_group=config_group,
            page_no=page_no,
            page_size=page_size
        )

        # 获取配置列表
        configs = result.get('configs', [])
        pagination = result["pagination"]
        config_list = [
            {
                "config_key": config.config_key,
                "config_value": config.config_value,
                "config_group": config.config_group,
                "config_name": config.config_name,
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
        config_value: str
    ) -> Optional[DynamicConfig]:
        """
        更新配置参数（只更新配置值）
        
        Args:
            db: 数据库会话
            config_key: 配置键（用于查找要更新的记录）
            config_value: 新的配置值
        
        Returns:
            Optional[DynamicConfig]: 更新后的配置对象
        """
        try:
            update_data = {"config_value": config_value}
            return DynamicConfigDAO.update_by_key(db, config_key, update_data)
            
        except Exception as e:
            logger.error(f"更新配置参数失败: {str(e)}")
            raise
    
    @staticmethod
    def batch_update_configs(
        db: Session,
        config_updates: Dict[str, str]
    ) -> Dict[str, Any]:
        """
        批量更新配置参数
        
        Args:
            db: 数据库会话
            config_updates: 配置更新字典，格式为 {config_key: config_value}
        
        Returns:
            Dict: 包含更新结果的字典
        """
        try:
            success_count = 0
            failed_count = 0
            results = []
            
            for config_key, config_value in config_updates.items():
                try:
                    config = DynamicConfigDAO.update_by_key(
                        db, 
                        config_key, 
                        {"config_value": config_value}
                    )
                    
                    if config:
                        success_count += 1
                        results.append({
                            "config_key": config_key,
                            "config_value": config_value,
                            "status": "success",
                            "message": "更新成功"
                        })
                        logger.info(f"更新配置 '{config_key}' 成功")
                    else:
                        failed_count += 1
                        results.append({
                            "config_key": config_key,
                            "status": "failed",
                            "message": f"配置键 '{config_key}' 不存在"
                        })
                        logger.warning(f"配置键 '{config_key}' 不存在")
                        
                except Exception as e:
                    failed_count += 1
                    results.append({
                        "config_key": config_key,
                        "status": "failed",
                        "message": str(e)
                    })
                    logger.error(f"更新配置 '{config_key}' 失败: {str(e)}")
            
            logger.info(f"批量更新配置完成: 成功 {success_count} 个, 失败 {failed_count} 个")
            
            return {
                "success_count": success_count,
                "failed_count": failed_count,
                "results": results
            }
            
        except Exception as e:
            logger.error(f"批量更新配置失败: {str(e)}")
            raise
    
    @staticmethod
    def get_config_value(db: Session, config_key: str, default_value: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            db: 数据库会话
            config_key: 配置键
            default_value: 默认值（如果配置不存在）
        
        Returns:
            Any: 配置值
        """
        config = DynamicConfigDAO.get_by_key(db, config_key)
        
        if not config:
            return default_value
        
        value = config.config_value
        if value is None:
            return default_value
        
        return value





