#!/usr/bin/env python3
"""
模型核心建模客户端
用于调用模型核心建模相关的接口
"""

import requests
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

from core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class DragToWithAttributesRequest:
    """拖拽到目标位置并设置属性的请求参数"""
    creator: str
    project_uri: str
    source_uri: str
    target_uri: str
    display_name: str
    browse_name: str
    data_source_uri: str = ""
    table_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "creator": self.creator,
            "projectUri": self.project_uri,
            "sourceUri": self.source_uri,
            "targetUri": self.target_uri,
            "displayName": self.display_name,
            "browseName": self.browse_name,
            "dataSourceUri": self.data_source_uri,
            "tableName": self.table_name
        }


@dataclass
class UpdateFolderRequest:
    """更新文件夹的请求参数"""
    modifier: str
    uri: str
    display_name: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "modifier": self.modifier,
            "uri": self.uri,
            "displayName": self.display_name
        }


@dataclass
class GetChildrenRequest:
    """获取子节点的请求参数"""
    current_uri: str
    node_class_list: list = None

    def __post_init__(self):
        """初始化后处理"""
        if self.node_class_list is None:
            self.node_class_list = ["FOLDER", "INSTANCE"]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "currentUri": self.current_uri,
            "nodeClassList": self.node_class_list
        }


class ModelCoreClient:
    """模型核心建模客户端"""

    # 默认配置（从Config类读取）
    DEFAULT_BASE_URL = Config.MODEL_CORE_BASE_URL
    DEFAULT_TIMEOUT = Config.MODEL_CORE_TIMEOUT
    # 接口路径（固定路径，不需要配置）
    #装置创建
    DRAG_TO_WITH_ATTRIBUTES_PATH = "/model/modelling/drag/dragToWithAttributes"
    #文件夹更新
    FOLDER_UPDATE_PATH = "/model/modelling/folder/update"
    #节点删除
    TREE_DELETE_PATH = "/model/modelling/tree/delete"
    #工程列表
    PROJECT_LIST_PATH = "/model/modelling/project/list"
    #获取子节点
    TREE_GET_CHILDREN_PATH = "/model/modelling/tree/getChildren"

    def __init__(self, base_url: Optional[str] = None, timeout: int = None):
        """
        初始化模型核心建模客户端
        
        Args:
            base_url: 服务基础URL，如果为None则从配置文件读取
            timeout: 请求超时时间（秒），如果为None则从配置文件读取
        """
        self.base_url = base_url if base_url is not None else self.DEFAULT_BASE_URL
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.session = requests.Session()
        
        # 设置默认请求头
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'PID-Agent-ModelCore-Client/1.0'
        })
        
        logger.info(f"初始化模型核心客户端，连接到: {self.base_url}")

    def drag_to_with_attributes(
            self,
            creator: str,
            project_uri: str,
            source_uri: str,
            target_uri: str,
            display_name: str,
            browse_name: str,
            data_source_uri: str = "",
            table_name: str = ""
    ) -> Dict[str, Any]:
        """
        拖拽到目标位置并设置属性(创建对象)
        
        Args:
            creator: 创建者
            project_uri: 项目URI，如 "/pid_zd/root"
            source_uri: 源URI，如 "/system/401"
            target_uri: 目标URI，如 "/pid_zd/053f3c45413b48bbafacec609d142e57"
            display_name: 显示名称，如 "文件夹_1"
            browse_name: 浏览名称，如 "Folder_1"
            data_source_uri: 数据源URI，默认为空字符串
            table_name: 表名，默认为空字符串
            
        Returns:
            接口响应结果:
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
            requests.exceptions.RequestException: 请求失败时抛出
            
        Example:
            >>> client = ModelCoreClient()
            >>> result = client.drag_to_with_attributes(
            ...     creator="管理员",
            ...     project_uri="/pid_zd/root",
            ...     source_uri="/system/401",
            ...     target_uri="/pid_zd/053f3c45413b48bbafacec609d142e57",
            ...     display_name="文件夹_1",
            ...     browse_name="Folder_1"
            ... )
        """
        url = f"{self.base_url}{self.DRAG_TO_WITH_ATTRIBUTES_PATH}"
        
        # 构建请求体
        payload = {
            "creator": creator,
            "projectUri": project_uri,
            "sourceUri": source_uri,
            "targetUri": target_uri,
            "displayName": display_name,
            "browseName": browse_name,
            "dataSourceUri": data_source_uri,
            "tableName": table_name
        }
        
        try:
            # logger.info(f"调用拖拽接口，目标URI: {target_uri}")
            # logger.debug(f"请求URL: {url}")
            # logger.debug(f"请求体: {payload}")
            
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型核心接口调用失败: {str(e)}")
            raise

    def update_folder(
            self,
            modifier: str,
            uri: str,
            display_name: str
    ) -> Dict[str, Any]:
        """
        更新文件夹显示名称

        Args:
            modifier: 修改者
            uri: 文件夹URI
            display_name: 新显示名称

        Returns:
            接口响应结果
        """
        url = f"{self.base_url}{self.FOLDER_UPDATE_PATH}"
        payload = {
            "modifier": modifier,
            "uri": uri,
            "displayName": display_name
        }

        try:
            logger.info(f"调用文件夹更新接口，目标URI: {uri}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求体: {payload}")

            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型核心接口调用失败: {str(e)}")
            raise

    def update_folder_by_request(
            self,
            request: UpdateFolderRequest
    ) -> Dict[str, Any]:
        """
        使用请求对象调用文件夹更新接口

        Args:
            request: 文件夹更新请求对象

        Returns:
            接口响应结果
        """
        return self.update_folder(
            modifier=request.modifier,
            uri=request.uri,
            display_name=request.display_name
        )

    def delete_tree(
            self,
            uri: str,
            modifier: str=""
    ) -> Dict[str, Any]:
        """
        删除节点

        Args:
            uri: 节点URI
            modifier: 修改者

        Returns:
            接口响应结果
        """
        url = f"{self.base_url}{self.TREE_DELETE_PATH}"
        params = {
            "uri": uri,
            "modifier": modifier
        }

        try:
            logger.info(f"调用树删除接口，目标URI: {uri}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求参数: {params}")

            response = self.session.delete(
                url,
                params=params,
                timeout=self.timeout
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型核心接口调用失败: {str(e)}")
            raise

    def list_projects(self) -> Dict[str, Any]:
        """
        查询模型工程列表

        Returns:
            接口响应结果
        """
        url = f"{self.base_url}{self.PROJECT_LIST_PATH}"

        try:
            logger.info("调用工程列表查询接口")
            logger.debug(f"请求URL: {url}")

            response = self.session.get(
                url,
                timeout=self.timeout
            )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型核心接口调用失败: {str(e)}")
            raise

    def get_children(
            self,
            current_uri: str,
            node_class_list: list = None
    ) -> Dict[str, Any]:
        """
        获取节点的子节点
        
        Args:
            current_uri: 当前节点URI，如 "/pid_zd/053f3c45413b48bbafacec609d142e57"
            node_class_list: 节点类型列表，如 ["FOLDER", "INSTANCE"]，默认为 None
        
        Returns:
            接口响应结果，包含子节点列表
            {
                "success": true,
                "message": "成功",
                "result": {
                    "children": [
                        {
                            "uri": "/pid_zd/xxx",
                            "nodeClass": "FOLDER",
                            "displayName": "子节点名称"
                        }
                    ]
                },
                "code": 0
            }
        
        Raises:
            requests.exceptions.RequestException: 请求失败时抖出
        
        Example:
            >>> client = ModelCoreClient()
            >>> result = client.get_children(
            ...     current_uri="/pid_zd/053f3c45413b48bbafacec609d142e57",
            ...     node_class_list=["FOLDER", "INSTANCE"]
            ... )
        """
        url = f"{self.base_url}{self.TREE_GET_CHILDREN_PATH}"
        
        # 如果没有指定节点类型，使用默认值
        if node_class_list is None:
            node_class_list = ["FOLDER", "INSTANCE"]
        
        # 构建请求体
        payload = {
            "currentUri": current_uri,
            "nodeClassList": node_class_list
        }
        
        try:
            logger.info(f"调用获取子节点接口，当前 URI: {current_uri}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求体: {payload}")
            
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型核心接口调用失败: {str(e)}")
            raise

    def drag_to_with_attributes_by_request(
            self,
            request: DragToWithAttributesRequest
    ) -> Dict[str, Any]:
        """
        使用请求对象调用拖拽接口
        
        Args:
            request: 拖拽请求对象
            
        Returns:
            接口响应结果
            
        Example:
            >>> request = DragToWithAttributesRequest(
            ...     creator="管理员",
            ...     project_uri="/pid_zd/root",
            ...     source_uri="/system/401",
            ...     target_uri="/pid_zd/053f3c45413b48bbafacec609d142e57",
            ...     display_name="文件夹_1",
            ...     browse_name="Folder_1"
            ... )
            >>> client = ModelCoreClient()
            >>> result = client.drag_to_with_attributes_by_request(request)
        """
        return self.drag_to_with_attributes(
            creator=request.creator,
            project_uri=request.project_uri,
            source_uri=request.source_uri,
            target_uri=request.target_uri,
            display_name=request.display_name,
            browse_name=request.browse_name,
            data_source_uri=request.data_source_uri,
            table_name=request.table_name
        )

    def close(self):
        """关闭会话"""
        if self.session:
            self.session.close()

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
#

# 便捷函数
def drag_to_with_attributes(
        creator: str,
        project_uri: str,
        source_uri: str,
        target_uri: str,
        display_name: str,
        browse_name: str,
        data_source_uri: str = "",
        table_name: str = "",
        base_url: Optional[str] = None,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：拖拽到目标位置并设置属性
    
    Args:
        creator: 创建者
        project_uri: 项目URI
        source_uri: 源URI
        target_uri: 目标URI
        display_name: 显示名称
        browse_name: 浏览名称
        data_source_uri: 数据源URI，默认为空字符串
        table_name: 表名，默认为空字符串
        base_url: 服务基础URL，可选
        timeout: 请求超时时间，可选
        
    Returns:
        接口响应结果
        
    Example:
        >>> result = drag_to_with_attributes(
        ...     creator="管理员",
        ...     project_uri="/pid_zd/root",
        ...     source_uri="/system/401",
        ...     target_uri="/pid_zd/053f3c45413b48bbafacec609d142e57",
        ...     display_name="文件夹_1",
        ...     browse_name="Folder_1"
        ... )
    """
    with ModelCoreClient(base_url=base_url, timeout=timeout) as client:
        return client.drag_to_with_attributes(
            creator=creator,
            project_uri=project_uri,
            source_uri=source_uri,
            target_uri=target_uri,
            display_name=display_name,
            browse_name=browse_name,
            data_source_uri=data_source_uri,
            table_name=table_name
        )


def update_folder(
        modifier: str,
        uri: str,
        display_name: str,
        base_url: Optional[str] = None,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：更新文件夹显示名称
    """
    with ModelCoreClient(base_url=base_url, timeout=timeout) as client:
        return client.update_folder(
            modifier=modifier,
            uri=uri,
            display_name=display_name
        )


def delete_tree(
        uri: str,
        modifier: str,
        base_url: Optional[str] = None,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：删除树节点
    """
    with ModelCoreClient(base_url=base_url, timeout=timeout) as client:
        return client.delete_tree(
            uri=uri,
            modifier=modifier
        )


def list_projects(
        base_url: Optional[str] = None,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：查询模型工程列表
    """
    with ModelCoreClient(base_url=base_url, timeout=timeout) as client:
        return client.list_projects()


def get_children(
        current_uri: str,
        node_class_list: list = None,
        base_url: Optional[str] = None,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：获取节点的子节点
    
    Args:
        current_uri: 当前节点URI
        node_class_list: 节点类型列表，默认为 None
        base_url: 服务基础URL，可选
        timeout: 请求超时时间，可选
    
    Returns:
        接口响应结果
    
    Example:
        >>> result = get_children(
        ...     current_uri="/pid_zd/053f3c45413b48bbafacec609d142e57",
        ...     node_class_list=["FOLDER", "INSTANCE"]
        ... )
    """
    with ModelCoreClient(base_url=base_url, timeout=timeout) as client:
        return client.get_children(
            current_uri=current_uri,
            node_class_list=node_class_list
        )
