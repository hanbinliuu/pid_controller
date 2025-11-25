#!/usr/bin/env python3
"""
BFF模型查询业务服务层
封装BFF相关的业务逻辑
"""

import logging
from typing import List, Dict, Any, Optional

from core.data.bff_model_client import BFFModelClient

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
            项目路径、测点路径、字段映射信息
        """
        try:
            with BFFModelClient(device_uri=project_path) as client:
                common_field_map = client.query_common_fields()
                
                logger.info(f"查询BFF测点路径成功，项目路径: {client.device_uri}")
                
                return {
                    "project_path": client.device_uri,
                    "point_path": client.point_path,
                    "model_point_map": common_field_map
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
            with BFFModelClient(device_uri=loop_uri, point_path=point_path) as client:
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
            with BFFModelClient(device_uri=project_path, point_path=point_path) as client:
                query_result = client.query_common_fields()
                
                table_and_points = BFFModelClient.extract_table_and_points_from_paths(query_result)
                
                table_name = table_and_points.get('table_name')
                points = table_and_points.get('points', [])
                
                if not table_name:
                    logger.warning("未能从路径中解析出table名称")
                    return {
                        "project_path": client.device_uri,
                        "point_path": client.point_path,
                        "message": "未解析到table名称",
                        "points": points,
                        "total_points": len(points)
                    }
                
                logger.info(f"查询表名和测点列表成功，表名: {table_name}, 测点数: {len(points)}")
                
                return {
                    "project_path": client.device_uri,
                    "point_path": client.point_path,
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
                
                logger.info(f"查询下一级子模型成功，标识符: {identifier}, 数量: {result.get('total', 0)}")
                
                return result
        except Exception as e:
            logger.error(f"查询下一级子模型失败: {str(e)}")
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
            contain_sub_model: 是否包含子模型
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
