#!/usr/bin/env python3
"""
业务逻辑层 - 装置管理服务
处理装置的新增、修改、删除等业务逻辑
"""
import logging
from typing import Dict, Any, Optional

from core.client.model_core_client import ModelCoreClient
from core.config import Config

logger = logging.getLogger(__name__)


class DeviceManageService:
    """装置管理业务逻辑服务"""
    
    def __init__(self):
        """初始化服务"""
        self.model_core_client = ModelCoreClient()
    
    def create_device(
        self,
        creator: str,
        target_uri,
        display_name: str,
        browse_name: str
    ) -> Dict[str, Any]:
        """
        创建装置
        
        Args:
            creator: 创建者
            project_uri: 项目URI，如 "/pid_zd/root"
            source_uri: 源URI（装置类型模板），如 "/system/401"
            target_uri: 目标父节点URI
            display_name: 装置显示名称
            browse_name: 装置浏览名称
            data_source_uri: 数据源URI，默认为空字符串
            table_name: 表名，默认为空字符串
            
        Returns:
            Dict[str, Any]: 装置创建结果
            {
                "success": true,
                "message": "操作成功",
                "result": {
                    "browseName": null,
                    "displayName": null,
                    "uri": "/pid_zd/eb65b27e4ff94a4da9a82d577f5cf3d9"
                },
                "code": 0
            }
            
        Raises:
            Exception: 当创建失败时抛出异常
        """
        try:
            logger.info(f"创建装置: {display_name}, 目标URI: {target_uri}")
            # 装置模型类型-文件夹(/system/401)
            source_uri=Config.BFF_MODEL_DEVICE_MODEL_URI
            # 工程URI
            project_uri=Config.MODEL_DEFULT_PROJECT_URI

            # 调用模型核心客户端创建装置
            result = self.model_core_client.drag_to_with_attributes(
                creator=creator,
                project_uri=project_uri,
                source_uri=source_uri,
                target_uri=target_uri,
                display_name=display_name,
                browse_name=browse_name
            )
            
            if result.get("success"):
                device_uri = result.get("result", {}).get("uri")
                logger.info(f"装置创建成功: {display_name}, URI: {device_uri}")
            else:
                logger.error(f"装置创建失败: {result.get('message')}")
            
            return result
            
        except Exception as e:
            logger.error(f"创建装置异常: {str(e)}")
            raise
    
    def update_device(
        self,
        modifier: str,
        device_uri: str,
        display_name: str
    ) -> Dict[str, Any]:
        """
        更新装置信息
        
        Args:
            modifier: 修改者
            device_uri: 装置URI
            display_name: 新的显示名称
            
        Returns:
            Dict[str, Any]: 装置更新结果
            {
                "success": true,
                "message": "操作成功",
                "result": null,
                "code": 0
            }
            
        Raises:
            Exception: 当更新失败时抛出异常
        """
        try:
            logger.info(f"更新装置: {device_uri}, 新名称: {display_name}")
            
            # 调用模型核心客户端更新装置
            result = self.model_core_client.update_folder(
                modifier=modifier,
                uri=device_uri,
                display_name=display_name
            )
            
            if result.get("success"):
                logger.info(f"装置更新成功: {device_uri}")
            else:
                logger.error(f"装置更新失败: {result.get('message')}")
            
            return result
            
        except Exception as e:
            logger.error(f"更新装置异常: {str(e)}")
            raise
    
    def delete_device(
        self,
        modifier: str,
        device_uri: str
    ) -> Dict[str, Any]:
        """
        删除装置
        
        Args:
            modifier: 修改者
            device_uri: 装置URI
            
        Returns:
            Dict[str, Any]: 装置删除结果
            {
                "success": true,
                "message": "操作成功",
                "result": null,
                "code": 0
            }
            
        Raises:
            Exception: 当删除失败时抛出异常
        """
        try:
            logger.info(f"删除装置: {device_uri}")
            
            # 调用模型核心客户端删除装置
            result = self.model_core_client.delete_tree(
                uri=device_uri,
                modifier=modifier
            )
            
            if result.get("success"):
                logger.info(f"装置删除成功: {device_uri}")
            else:
                logger.error(f"装置删除失败: {result.get('message')}")
            
            return result
            
        except Exception as e:
            logger.error(f"删除装置异常: {str(e)}")
            raise
    
    def close(self):
        """关闭服务资源"""
        if self.model_core_client:
            self.model_core_client.close()
    
    def __del__(self):
        """析构函数"""
        try:
            self.close()
        except:
            pass
