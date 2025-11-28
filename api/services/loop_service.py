#!/usr/bin/env python3
"""
回路管理业务服务层
封装回路相关的业务逻辑
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from core.data.bff_model_client import BFFModelClient
from api.bean.loop_response import LoopListResponse, LoopInstance, LoopStatus, Pagination, LoopInfoResponse

logger = logging.getLogger(__name__)


class LoopService:
    """回路管理业务服务"""

    @staticmethod
    def list_instances_under_tree(
        model_identifier_list: List[str],
        start_identifier_list: List[str],
        page_no: int = 1,
        page_size: int = 10
    ) -> LoopListResponse:
        """
        查询节点下指定模型类型的实例列表
        
        Args:
            model_identifier_list: 模型标识符列表
            start_identifier_list: 起始标识符列表
            page_no: 页码
            page_size: 每页数量
            
        Returns:
            LoopListResponse: 回路列表响应对象
        """
        try:
            # 使用BFF客户端查询回路列表
            with BFFModelClient() as client:
                result = client.list_instances_under_tree(
                    model_identifier_list=model_identifier_list,
                    start_identifier_list=start_identifier_list,
                    contain_sub_model=True,
                    page_no=page_no,
                    page_size=page_size
                )

                logger.info(
                    f"BFF查询成功，模型标识符: {model_identifier_list}, "
                    f"起始标识符: {start_identifier_list}, "
                    f"实例数量: {len(result.get('instances', []))}"
                )
                
                # 获取回路列表
                instances = result.get('instances', [])
                
                if instances:
                    # 构建批量查询配置：查询每个回路的PID参数 (PB, TI, TD)
                    loop_configs = [
                        {
                            'loop_uri': instance['uri'],
                            'point_names': ['PB', 'TI', 'TD','PV','SV','MV']
                        }
                        for instance in instances
                    ]
                    
                    # 一次查询所有回路的PID参数最新值
                    try:
                        loop_values = client.query_multi_loop_current_values(
                            loop_configs=loop_configs
                        )
                        
                        # 将PID参数添加到每个回路实例中
                        for instance in instances:
                            loop_uri = instance['uri']
                            loop_statu_values = loop_values.get(loop_uri, {})
                            instance['pid_params'] = {
                                'PB': loop_statu_values.get('PB'),
                                'TI': loop_statu_values.get('TI'),
                                'TD': loop_statu_values.get('TD'),
                                'PV': loop_statu_values.get('PV'),
                                'SV': loop_statu_values.get('SV'),
                                'MV': loop_statu_values.get('MV')
                            }
                        
                        logger.info(f"成功查询 {len(loop_values)} 个回路的PID参数")
                        
                    except Exception as e:
                        logger.warning(f"查询PID参数失败: {str(e)}, 将返回不包含PID参数的结果")
                        # 如果PID参数查询失败，为每个回路添加空None值
                        for instance in instances:
                            instance['pid_params'] = {
                                'PB': None,
                                'TI': None,
                                'TD': None,
                                'PV': None,
                                'SV': None,
                                'MV': None
                            }

                # 转换为响应模型
                return LoopListResponse(
                    instances=[
                        LoopInstance(
                            uri=instance.get('uri'),
                            browseName=instance.get('browseName'),
                            displayName=instance.get('displayName'),
                            description=instance.get('description'),
                            uriPath=instance.get('uriPath'),
                            extendedAttr=instance.get('extendedAttr', {}),
                            pid_params=LoopStatus(
                                PB=instance.get('pid_params', {}).get('PB'),
                                TI=instance.get('pid_params', {}).get('TI'),
                                TD=instance.get('pid_params', {}).get('TD'),
                                PV=instance.get('pid_params', {}).get('PV'),
                                SV=instance.get('pid_params', {}).get('SV'),
                                MV=instance.get('pid_params', {}).get('MV'),
                                AUTO=instance.get('pid_params', {}).get('AUTO')
                            ) if instance.get('pid_params') else None
                        )
                        for instance in instances
                    ],
                    pagination=Pagination(
                        total=result.get('pagination', {}).get('total', 0),
                        pages=result.get('pagination', {}).get('pages', 0),
                        pageNo=result.get('pagination', {}).get('pageNo', page_no),
                        pageSize=result.get('pagination', {}).get('pageSize', page_size)
                    )
                )

        except Exception as e:
            logger.error(f"查询实例树失败: {str(e)}")
            raise

    @staticmethod
    def query_loop_info(
        loop_uri: Optional[str] = None
    ) -> LoopInfoResponse:
        """
        查询回路详细属性
        
        Args:
            loop_uri: 回路 URI
            
        Returns:
            LoopInfoResponse: 回路信息响应对象
        """
        try:
            # 使用BFF客户端查询回路测点值
            with BFFModelClient(device_uri=loop_uri) as client:
                # 查询回路节点信息
                nodes_result = client.query_nodes_by_uris([loop_uri]).get("nodes")
                # 判断是否获取回路节点信息成功
                if len(nodes_result) == 0:
                    return LoopInfoResponse(
                        uri=loop_uri,
                        browseName=None,
                        displayName=None,
                        description=None,
                        uriPath=None,
                        extendedAttr=None,
                        auto_control_status=None,
                        action_type=None,
                        sv_range_max=None,
                        sv_range_min=None,
                        mv_range_max=None,
                        mv_range_min=None
                    )

                # 从结果中提取第一个节点信息
                loop_info = nodes_result[0] if nodes_result and len(nodes_result) > 0 else {}
                # 定义需要查询的测点名称
                # 根据图片显示的字段，查询相关测点
                point_names = [
                    'AUTO',  # 自控情况
                    'action_type',          # 正反作用
                    'SVH',         # 目标值量程上限
                    'SVL',         # 目标值量程下限
                    'MVH',         # 阀位值量程上限
                    'MVL'          # 阀位值量程下限
                ]
                
                # 查询测点当前值
                point_values = client.query_current_raw_values(point_names)
                
                # 转换为响应模型
                return LoopInfoResponse(
                    uri=loop_uri,
                    browseName=loop_info.get('browseName'),
                    displayName=loop_info.get('displayName'),
                    description=loop_info.get('description'),
                    uriPath=loop_info.get('uriPath'),
                    extendedAttr=loop_info.get('extendedAttr', {}),
                    auto_control_status=point_values.get('AUTO'),
                    action_type=point_values.get('action_type'),
                    sv_range_max=point_values.get('SVH'),
                    sv_range_min=point_values.get('SVL'),
                    mv_range_max=point_values.get('MVH'),
                    mv_range_min=point_values.get('MVL')
                )
        
        except Exception as e:
            logger.error(f"查询回路属性失败: {str(e)}")
            raise

    @staticmethod
    def query_loop_values(
        point_names: List[str],
        loop_uri: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询回路测点当前最新值
        
        Args:
            point_names: 测点名称列表
            loop_uri: 回路 URI
            
        Returns:
            Dict[str, Any]: 测点名称到值的映射
        """
        try:
            # 使用BFF客户端查询
            with BFFModelClient(device_uri=loop_uri) as client:
                result = client.query_current_raw_values(point_names)

                logger.info(f"BFF查询成功，测点数量: {len(result)}")

                return result

        except Exception as e:
            logger.error(f"查询测点当前值失败: {str(e)}")
            raise

    @staticmethod
    def get_next_loop_type(
        identifier: str
    ) -> Dict[str, Any]:
        """
        获取下一级子模型
        
        Args:
            identifier: 模型标识符，URI路径
            
        Returns:
            Dict[str, Any]: 子模型列表
        """
        try:
            # 使用BFF客户端查询
            with BFFModelClient() as client:
                result = client.get_next_level_submodel(identifier)

                logger.info(f"子类型查询成功: {identifier}, 回路类型数量: {result.get('total', 0)}")

                return result

        except Exception as e:
            logger.error(f"回路子类型查询失败: {str(e)}")
            raise