#!/usr/bin/env python3
"""
BFF模型查询业务服务层
封装BFF相关的业务逻辑
"""

import logging
from typing import List, Dict, Any, Optional

from core.client.bff_model_client import BFFModelClient
from core.config import Config

logger = logging.getLogger(__name__)


class BFFService:
    """BFF模型查询服务"""

    @staticmethod
    def get_point_paths(project_path: Optional[str] = None) -> Dict[str, Any]:
        """
        查询项目路径下的测点路径
        
        Args:
            project_path: 项目路径，None时使用默认配置
            
        Returns:
            项目路径、字段映射信息
        """
        try:
            with BFFModelClient(loop_uri=project_path) as client:
                table,field_mapping = client.query_table_and_points_by_loop_uri(loop_uri=project_path)
                
                return {
                    "project_path": client.deafult_device_uri,
                    "point_path": client.deafult_point_path,
                    "table":table,
                    "field_mapping": field_mapping
                }
        except Exception as e:
            logger.error(f"查询BFF测点路径失败: {str(e)}")
            raise

    @staticmethod
    def get_point_values(
            point_names: List[str],
            loop_uri: Optional[str] = None,
            point_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询测点当前原始值
        
        Args:
            point_names: 测点名称列表
            loop_uri: 回路URI，None时使用默认配置
            point_path: 测点路径，None时使用默认配置
            
        Returns:
            测点名称到值的映射
        """
        try:
            with BFFModelClient(loop_uri=loop_uri, point_path=point_path) as client:
                result = client.query_current_raw_values(point_names)
                
                logger.info(f"查询BFF测点当前值成功，测点数量: {len(result)}")
                
                return result
        except Exception as e:
            logger.error(f"查询BFF测点当前值失败: {str(e)}")
            raise

    @staticmethod
    def get_table_and_points(
            project_path: Optional[str] = None,
            point_path: Optional[str] = 'loop_state_parameters'
    ) -> Dict[str, Any]:
        """
        查询表名和测点列表
        
        Args:
            project_path: 项目路径，None时使用默认配置
            point_path: 测点路径，默认为 'loop_state_parameters'
            
        Returns:
            项目路径、表名、测点列表等信息
        """
        try:
            with BFFModelClient(loop_uri=project_path, point_path=point_path) as client:
                query_result = client.query_common_fields()
                
                table_and_points = BFFModelClient.extract_table_and_points_from_paths(query_result)
                
                table_name = table_and_points.get('table_name')
                points = table_and_points.get('points', [])
                
                if not table_name:
                    logger.warning("未能从路径中解析出table名称")
                    return {
                        "project_path": client.deafult_device_uri,
                        "point_path": client.deafult_point_path,
                        "message": "未解析到table名称",
                        "points": points,
                        "total_points": len(points)
                    }
                
                logger.info(f"查询表名和测点列表成功，表名: {table_name}, 测点数: {len(points)}")
                
                return {
                    "project_path": client.deafult_device_uri,
                    "point_path": client.deafult_point_path,
                    "table_name": table_name,
                    "points": points,
                    "total_points": len(points)
                }
        except Exception as e:
            logger.error(f"查询表名和测点列表失败: {str(e)}")
            raise

    @staticmethod
    def get_next_level_submodel(identifier: str) -> Dict[str, Any]:
        """
        获取下一级子模型
        
        Args:
            identifier: 模型标识符
            
        Returns:
            子模型列表
        """
        try:
            with BFFModelClient() as client:
                result = client.get_next_level_submodel(identifier)
                return result
        except Exception as e:
            logger.error(f"查询子模型列表失败: {str(e)}")
            raise

    @staticmethod
    def list_instances_under_tree(
            model_identifier_list: List[str],
            start_identifier_list: List[str],
            contain_sub_model: bool = True,
            page_no: int = 1,
            page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询节点下指定模型类型的实例列表
        
        Args:
            model_identifier_list: 模型标识符列表
            start_identifier_list: 起始标识符列表
            contain_sub_model: 是否包含子模型类型实例
            page_no: 页码
            page_size: 每页数量
            
        Returns:
            实例列表和分页信息
        """
        try:
            with BFFModelClient() as client:
                result = client.list_instances_under_tree(
                    model_identifier_list=model_identifier_list,
                    start_identifier_list=start_identifier_list,
                    contain_sub_model=contain_sub_model,
                    page_no=page_no,
                    page_size=page_size
                )
                
                logger.info(
                    f"查询实例树成功，模型标识符: {model_identifier_list}, "
                    f"起始标识符: {start_identifier_list}, "
                    f"实例数量: {len(result.get('instances', []))}"
                )
                
                return result
        except Exception as e:
            logger.error(f"查询实例树失败: {str(e)}")
            raise

    @staticmethod
    def query_nodes_by_uris(uris: List[str]) -> Dict[str, Any]:
        """
        根据URI列表查询节点详细信息
        
        Args:
            uris: URI列表
            
        Returns:
            节点详细信息列表
        """
        try:
            with BFFModelClient() as client:
                result = client.query_nodes_by_uris(uris)
                
                logger.info(f"查询节点详细信息成功，节点数量: {result.get('total', 0)}")
                
                return result
        except Exception as e:
            logger.error(f"查询节点详细信息失败: {str(e)}")
            raise

    @staticmethod
    def query_instance_tree(
            start_uri: str,
            model_uri_list: Optional[List[str]] = None,
            include_sub_type: bool = True
    ) -> Dict[str, Any]:
        """
        查询实例树（树形结构）
        
        Args:
            start_uri: 起始搜索URI
            model_uri_list: 模型URI列表，可选
            include_sub_type: 是否包含子类型
            
        Returns:
            树形结构数据，包含根节点和所有子节点
        """
        try:
            with BFFModelClient() as client:
                result = client.query_instance_tree(
                    start_uri=start_uri,
                    model_uri_list=model_uri_list,
                    include_sub_type=include_sub_type
                )
                
                logger.info(f"查询实例树成功，起始URI: {start_uri}")
                
                return result
        except Exception as e:
            logger.error(f"查询实例树失败: {str(e)}")
            raise
    
    @staticmethod
    def get_all_devices() -> List[Dict[str, Any]]:
        """
        获取所有装置列表
        
        使用内置参数：
        - model_identifier_list: /system/401 (装置模型URI)
        - start_identifier_list: /pid_zd/instance (根节点URI)
        - 自动分页获取全部装置
        
        Returns:
            装置列表，每个装置包含: uri, browseName, displayName, parentUri 等字段
        """
        try:
            all_devices = []
            page_no = 1
            page_size = 100  # 每页100条
            
            # 内置参数
            model_identifier_list = [Config.BFF_MODEL_DEVICE_MODEL_URI]  # /system/401
            start_identifier_list = [Config.BFF_MODEL_ROOT_URI]  # /pid_zd/instance
            
            logger.info(
                f"开始获取装置列表 - "
                f"模型标识符: {model_identifier_list}, "
                f"起始标识符: {start_identifier_list}"
            )
            
            with BFFModelClient() as client:
                while True:
                    # 分页查询
                    result = client.list_instances_under_tree(
                        model_identifier_list=model_identifier_list,
                        start_identifier_list=start_identifier_list,
                        contain_sub_model=True,
                        page_no=page_no,
                        page_size=page_size
                    )
                    
                    instances = result.get('instances', [])
                    if not instances:
                        break
                    
                    all_devices.extend(instances)
                    
                    # 检查是否还有更多页
                    pagination = result.get('pagination', {})
                    total_pages = pagination.get('pages', 0)
                    
                    logger.debug(
                        f"已加载第 {page_no}/{total_pages} 页，"
                        f"当前总数: {len(all_devices)}"
                    )
                    
                    if page_no >= total_pages:
                        break
                    
                    page_no += 1
            
            logger.info(f"获取装置列表成功，总数: {len(all_devices)}")
            return all_devices
            
        except Exception as e:
            logger.error(f"获取装置列表失败: {str(e)}")
            raise
