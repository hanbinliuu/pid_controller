#!/usr/bin/env python3
"""
回路管理业务服务层
封装回路相关的业务逻辑
"""

import logging
from typing import Optional, Dict, Any, List

from sqlmodel import Session

from api.middleware.exceptions import RuntimeException
from api.middleware.response_model import error_response, success_response
from api.services.bff_service import BFFService
from api.services.dynamic_config_service import DynamicConfigService
from core.client import ModelCoreClient, IoTDAClient, ModelDataSourceClient
from core.client.bff_model_client import BFFModelClient
from api.response.loop_response import LoopListResponse, LoopInstance, LoopStatus, Pagination, LoopInfoResponse
from core.config import Config
from core.database.database import get_db_session
from core.utils.model_util import ModelUtil

logger = logging.getLogger(__name__)


class LoopService:
    """回路管理业务服务"""

    def __init__(self):
        """初始化服务"""
        self.model_core_client = ModelCoreClient()
        self.iotda_client = IoTDAClient()
        self.model_data_source_client = ModelDataSourceClient()
        self.bff_client = BFFModelClient()
        # 回路类型加载
        self.loop_type_map = ModelUtil.get_loop_types()

    @staticmethod
    def list_instances_by_node(
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
                            'point_names': ['PB', 'TI', 'TD', 'PV', 'SV', 'MV', 'AUTO']
                        }
                        for instance in instances
                    ]

                    # 一次查询所有回路的PID参数最新值
                    try:
                        loop_values = client.query_multi_loop_current_values(
                            loop_configs=loop_configs,
                            point_path=Config.BFF_MODEL_POINT_PATH
                        )

                        # 将PID参数添加到每个回路实例中
                        for instance in instances:
                            loop_uri = instance['uri']
                            loop_statu_values = loop_values.get(loop_uri, {})
                            auto_control_status = 1 if loop_statu_values.get('AUTO') in ["auto", 1, 255, "true",
                                                                                         "自动"] else 0
                            instance['pid_params'] = {
                                'PB': loop_statu_values.get('PB'),
                                'TI': loop_statu_values.get('TI'),
                                'TD': loop_statu_values.get('TD'),
                                'PV': loop_statu_values.get('PV'),
                                'SV': loop_statu_values.get('SV'),
                                'MV': loop_statu_values.get('MV'),
                                'AUTO': auto_control_status
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
                                'MV': None,
                                'AUTO': None
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
                            loop_status=LoopStatus(
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
            with BFFModelClient(loop_uri=loop_uri) as client:
                # 查询回路节点信息
                nodes_result = client.query_nodes_by_uris([loop_uri]).get("nodes")
                # 判断是否获取回路节点信息成功
                if len(nodes_result) == 0:
                    return LoopInfoResponse(
                        uri=None,
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
                    'PB',  # 比例参数
                    'TI',  # 积分参数
                    'TD',  # Differential参数
                    'PV',  # 测点值
                    'SV',  # 目标值
                    'MV',  # 阀位值
                    'action_type',  # 正反作用
                    'SVH',  # 目标值量程上限
                    'SVL',  # 目标值量程下限
                    'MVH',  # 阀位值量程上限
                    'MVL'  # 阀位值量程下限
                ]

                # 查询测点当前值
                point_values = client.query_current_raw_values(point_names)
                auto_control_status = 1 if point_values.get('AUTO') in ["auto", 1, 255, "true", "自动"] else 0
                action_type = "未知" if point_values.get('action_type') is None else point_values.get('action_type')

                # 转换为响应模型
                return LoopInfoResponse(
                    uri=loop_uri,
                    browseName=loop_info.get('browseName'),
                    displayName=loop_info.get('displayName'),
                    description=loop_info.get('description'),
                    uriPath=loop_info.get('uriPath'),
                    extendedAttr=loop_info.get('extendedAttr', {}),
                    auto_control_status=auto_control_status,
                    action_type=action_type,
                    pv=point_values.get('PV'),
                    sv=point_values.get('SV'),
                    mv=point_values.get('MV'),
                    pb=point_values.get('PB'),
                    ti=point_values.get('TI'),
                    td=point_values.get('TD'),
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
            with BFFModelClient(loop_uri=loop_uri) as client:
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

    #  回路实例化
    def instantiate_loop(
            self,
            loop_type: str,
            loop_displayName: str,
            loop_browseName: str,
            parent_uri: str,
    ) -> Dict[str, Any]:
        """
        实例化回路

        Args:
            loop_type: 回路类型
            loop_displayName: 回路显示名称
            loop_browseName: 回路标识
            parent_uri: 装置uri

        Returns:
            Dict[str, Any]: 回路信息
        """
        # 获取回路类型uri
        loop_type_uri = self.loop_type_map.get(loop_type)
        # 获取工程URI
        project_uri = Config.MODEL_DEFULT_PROJECT_URI

        loop_uri = None
        device_id = None
        loop_point_uri = None
        # todo 创建回路节点-回路实例化
        # 调用模型核心客户端创建装置
        # with ModelCoreClient() as model_core_client:
        loop_info_result = self.model_core_client.drag_to_with_attributes(
            creator="导入",
            project_uri=project_uri,
            source_uri=loop_type_uri,
            target_uri=parent_uri,
            display_name=loop_displayName,
            browse_name=loop_browseName
        )
        if loop_info_result.get("success"):
            loop_uri = loop_info_result.get("result", {}).get("uri")
            logger.info(f"模型回路实例化成功: {loop_displayName}, URI: {loop_uri}")
        else:
            logger.error(f"模型回路实例化失败: {loop_info_result.get('message')}")
            # todo 删除实例

            return error_response(
                code=-1,
                message=f"模型回路实例化失败: {loop_info_result.get('message')}",

            )
            # raise RuntimeException("模型回路实例化失败："+loop_info_result.get("message"))

        # 获取回路属性信息节点uri
        if loop_uri is not None:
            # with BFFModelClient as bff_client:
            loop_uris = self.bff_client.identifier_to_uri(identifiers=[loop_uri + "/loop_state_parameters"])
            if len(loop_uris) > 0:
                loop_point_uri = loop_uris[0]
                logger.info(f"回路属性信息节点uri: {loop_point_uri}")

        # return loop_info_result
        # todo 创建IOTDA设备实例
        dynamic_config: Dict[str, str] = {}
        with get_db_session() as db:
            # 获取动态配置参数
            dynamic_config = DynamicConfigService.get_all_configs_map(db)
        # 虚拟网关设备ID
        virtual_gateway_device_id = dynamic_config.get("virtual_gateway_device_id")
        # 资源空间 ID
        default_resource_space = dynamic_config.get("default_resource_space")
        # 产品(网关子设备模型)ID
        product_model_id = dynamic_config.get("product_model_id")
        device_id = loop_browseName

        # with IoTDAClient() as iotda_client:
        iotda_init_result = self.iotda_client.create_sub_device(
            name=loop_browseName, #显示名称
            identification=loop_browseName, #设备标识
            device_id=loop_browseName, # 设备ID
            resource_space_id=default_resource_space, # 资源空间ID
            product_id=product_model_id, # 产品（设备模型）ID
            gateway_id=virtual_gateway_device_id, # 网关设备ID
            description=loop_displayName,
        )
        if iotda_init_result.get("code") == 0:
            device_id = loop_browseName
            logger.info(f"回路网关设备实例化成功: {loop_displayName}, 设备ID: {device_id}")
        else:
            logger.error(f"回路网关设备实例化失败: {iotda_init_result.get('message')}")
            # todo 删除实例、设备
            self.model_core_client.delete_tree(uri=loop_uri)
            return error_response(
                code=-1,
                message="回路网关设备实例化异常：" + iotda_init_result.get("message")
            )
            raise RuntimeException("回路网关设备实例化失败：" + iotda_init_result.get("message"))

        # todo 回路-网关设备测点绑定
        if loop_point_uri and device_id and product_model_id:
            # 测点绑定
            with ModelDataSourceClient() as model_data_source_client:
                bind_result = model_data_source_client.bind_single_device(
                    uri=loop_point_uri,
                    device_id=device_id,
                    product_id=product_model_id,
                    operator="管理员"
                )
                if bind_result.get("success"):
                    logger.info(f"回路-测点批量绑定成功: {loop_displayName}, 设备ID: {device_id}")

                else:
                    logger.error(f"回路-测点批量绑定失败: {bind_result.get('message')}")
                    raise RuntimeException("回路-测点批量绑定失败：" + bind_result.get("message"))
                return success_response(
                        data={
                            "loop_uri": loop_uri,
                            "loop_type": loop_type,
                            "loop_displayName": loop_displayName,
                            "loop_browseName": loop_browseName,
                            "loop_point_uri": loop_point_uri,
                            "device_id": device_id,
                            "product_model_id": product_model_id
                        }
                    )
        else:
            logger.error(
                f"回路-网关设备测点绑定异常: 回路属性信息节点uri: {loop_point_uri}, 设备ID: {device_id}, 产品(网关子设备模型)ID: {product_model_id}")
            # todo 回路列表加载任务执行
            return error_response(
                code=-1,
                message=f"回路-网关设备测点绑定异常: 回路属性信息节点uri: {loop_point_uri}, 设备ID: {device_id}, 产品(网关子设备模型)ID: {product_model_id}",
            )
