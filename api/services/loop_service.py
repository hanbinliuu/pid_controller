#!/usr/bin/env python3
"""
回路管理业务服务层
封装回路相关的业务逻辑
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List
from api.middleware.exceptions import RuntimeException
from api.middleware.response_model import error_response, success_response
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
        self.dynamic_config: Dict[str, str] = {}
        with get_db_session() as db:
            # 获取动态配置参数
            self.dynamic_config = DynamicConfigService.get_all_configs_map(db)

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
            gateway_device_id: str=None,
    ) -> Dict[str, Any]:
        """
        实例化回路

        Args:
            loop_type: 回路类型
            loop_displayName: 回路显示名称
            loop_browseName: 回路标识
            parent_uri: 所属装置uri
            gateway_device_id: 网关设备ID

        Returns:
            Dict[str, Any]: 回路信息
        """
        loop_uri = None
        device_id = None
        loop_point_uri = None
        loop_uri = self._create_model_loop_instance(
            loop_type=loop_type,
            loop_displayName=loop_displayName,
            loop_browseName=loop_browseName,
            parent_uri=parent_uri
        )
        loop_point_uri = self._get_loop_point_uri(loop_uri)

        # todo 回路网关设备实例化
        try:
            device_info = self._create_iotda_loop_device(
                device_id=loop_browseName,
                device_name=loop_displayName,
                virtual_gateway_device_id=gateway_device_id,
            )
            device_id = device_info.get("device_id")
            product_model_id = device_info.get("product_model_id")

        except RuntimeException as e:
            # 删除回路
            if loop_uri:
                self.model_core_client.delete_tree(uri=loop_uri)
            return error_response(
                code=-1,
                message=f"回路网关设备实例化失败: {str(e)}",
            )
            # raise

        # todo 回路-网关设备测点绑定
        try:
            if loop_point_uri and device_id:
                self._bind_loop_to_device(loop_point_uri, device_id, product_model_id, loop_uri, loop_displayName)
        except RuntimeException as e:
            logger.error(f"绑定失败: {str(e)}")
            return error_response(
                code=-1,
                message=str(e),
            )

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

    def batch_instantiate_loops(
            self,
            requests: List[Dict[str, Any]],
            parent_uri: str,
            gateway_device_id: str=None,
            max_workers: int = 5
    ) -> Dict[str, Any]:
        """
        批量实例化回路
        
        Args:
            requests: 实例化请求列表，每个元素包含 loop_type, loop_display_name, loop_browse_name
            parent_uri: 父节点URI
            max_workers: 最大工作线程数
            gateway_device_id: 网关设备ID
            
        Returns:
            Dict[str, Any]: 批量处理结果
        """
        def build_result(loop_request_data: Dict[str, Any]) -> Dict[str, Any]:
            loop_type = loop_request_data.get('loop_type')
            loop_display_name = loop_request_data.get('loop_display_name')
            loop_browse_name = loop_request_data.get('loop_browse_name')
            
            try:
                result = self.instantiate_loop(
                    loop_type=loop_type,
                    loop_displayName=loop_display_name,
                    loop_browseName=loop_browse_name,
                    parent_uri=parent_uri,
                    gateway_device_id=gateway_device_id
                )

                if result.get("success"):
                    logger.info(
                        "回路实例化成功: 类型=%s, 名称=%s, URI=%s",
                        loop_type,
                        loop_display_name,
                        result.get('data', {}).get('loop_uri')
                    )
                else:
                    logger.error(
                        "回路实例化失败: 类型=%s, 名称=%s, 原因=%s",
                        loop_type,
                        loop_display_name,
                        result.get('message')
                    )
                return {
                    "loop_type": loop_type,
                    "loop_display_name": loop_display_name,
                    "loop_browse_name": loop_browse_name,
                    "parent_uri": parent_uri,
                    "success": result.get("success", False),
                    "code": result.get("code"),
                    "message": result.get("message"),
                    "data": result.get("data")
                }
            except Exception as exc:
                logger.error(
                    "回路实例化异常: 类型=%s, 名称=%s, 错误=%s",
                    loop_type,
                    loop_display_name,
                    str(exc)
                )
                return {
                    "loop_type": loop_type,
                    "loop_display_name": loop_display_name,
                    "loop_browse_name": loop_browse_name,
                    "parent_uri": parent_uri,
                    "success": False,
                    "code": 500,
                    "message": str(exc),
                    "data": None
                }

        if not requests:
            return {
                "success": False,
                "message": "回路列表不能为空",
                "code": -1
            }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(build_result, requests))

        success_count = sum(1 for item in results if item.get("success"))
        failed_count = len(results) - success_count
        
        return {
            "success": failed_count == 0,
            "message": "批量实例化完成",
            "data": {
                "total": len(results),
                "success_count": success_count,
                "failed_count": failed_count,
                "items": results
            },
            "code": 0 if failed_count == 0 else -1
        }

    def _create_iotda_loop_device(
            self,
            device_id: str,
            device_name: str,
            virtual_gateway_device_id: str = None
    ) -> Dict[str, str]:
        """
        创建IOTDA回路设备的公共方法

        Args:
            device_id: 设备标识
            device_name: 设备显示名称
            virtual_gateway_device_id: 网关设备ID
        Returns:
            Dict[str, str]: 设备信息，包含设备ID和产品ID

        Raises:
            RuntimeException: 设备创建失败时抛出
        """
        # 虚拟网关设备ID
        if virtual_gateway_device_id is None:
            virtual_gateway_device_id = self.dynamic_config.get("virtual_gateway_device_id")
        # 资源空间 ID
        default_resource_space = self.dynamic_config.get("default_resource_space")
        # 产品(网关子设备模型)ID
        product_model_id = self.dynamic_config.get("product_model_id")

        # 调用创建设备方法
        iot_device = None
        # 判断设备是否已创建
        try:
            try:
                iot_device = self.iotda_client.get_device(device_id)
            except Exception as e:
                logger.error(f"IOTDA设备查询异常, {str(e)}")
            # 创建子设备
            if iot_device is None:
                iotda_init_result = self.iotda_client.create_sub_device(
                    name=device_name,  # 显示名称
                    identification=device_id,  # 设备标识
                    device_id=device_id,  # 设备ID
                    resource_space_id=default_resource_space,  # 资源空间ID
                    product_id=product_model_id,  # 产品（设备模型）ID
                    gateway_id=virtual_gateway_device_id,  # 网关设备ID
                    description=device_id,
                )
                if iotda_init_result.get("code") == 0:
                    logger.info(f"IOTDA设备创建成功, {device_name}, 设备ID: {device_id},产品ID: {product_model_id}")
                else:
                    logger.error(f"IOTDA设备创建异常, {iotda_init_result.get('message')}")
                    raise RuntimeException(iotda_init_result.get("message"))
                    # raise RuntimeException("IOTDA设备创建异常," + iotda_init_result.get("message"))
        except Exception as e:
            logger.error(f"IOT网关设备[{device_id}]创建异常, {str(e)}")
            raise RuntimeException(f"IOT网关设备[{device_id}]创建异常, {str(e)}")

        return {
            "device_id": device_id,
            "product_model_id": product_model_id,
            "gateway_device_id": virtual_gateway_device_id,
            "resource_space": default_resource_space
        }

    def _bind_loop_to_device(
            self,
            loop_point_uri: str,
            device_id: str,
            product_model_id: str,
            loop_uri: str,
            loop_displayName: str,
    ) -> bool:
        """
        绑定回路到设备的公共方法

        Args:
            loop_point_uri: 回路属性信息节点URI
            device_id: 设备ID
            product_model_id: 产品(设备模型)ID
            loop_uri: 回路URI
            loop_displayName: 回路显示名称

        Returns:
            bool: 绑定成功返回True

        Raises:
            RuntimeException: 绑定失败时抛出
        """
        if not (loop_point_uri and device_id and product_model_id):
            logger.error(
                f"回路-网关设备测点绑定异常, 回路属性信息节点uri: {loop_point_uri}, 设备ID: {device_id}, 产品(网关子设备模型)ID: {product_model_id}")
            raise RuntimeException(
                f"回路-网关设备测点绑定异常, 回路属性信息节点uri: {loop_point_uri}, 设备ID: {device_id}, 产品(网关子设备模型)ID: {product_model_id}")

        # 测点绑定
        with ModelDataSourceClient() as model_data_source_client:
            bind_result = model_data_source_client.bind_single_device(
                uri=loop_point_uri,
                device_id=device_id,
                product_id=product_model_id,
                operator="管理员"
            )
            if bind_result.get("success"):
                logger.info(f"回路-测点批量绑定成功, {loop_displayName}, 设备ID: {device_id}")
                return True
            else:
                logger.error(
                    f"回路测点批量绑定异常, {loop_displayName}, 设备ID: {device_id}, {bind_result.get('message')}")
                # 绑定失败，删除新创建的回路实例、设备
                if loop_uri:
                    self.model_core_client.delete_tree(uri=loop_uri)
                if device_id:
                    self.iotda_client.delete_device(device_id=device_id)
                raise RuntimeException(
                    f"回路测点批量绑定异常, {loop_displayName}, 设备ID: {device_id}, {bind_result.get('message')}")

    def _create_model_loop_instance(
            self,
            loop_type: str,
            loop_displayName: str,
            loop_browseName: str,
            parent_uri: str,
    ) -> str:
        """
        在模型中创建回路实例

        Args:
            loop_type: 回路类型
            loop_displayName: 回路显示名称
            loop_browseName: 回路标识
            parent_uri: 所属装置URI

        Returns:
            str: 创建成功的回路URI

        Raises:
            RuntimeException: 实例创建失败时抛出
        """
        # 获取回路类型uri
        loop_type_uri = self.loop_type_map.get(loop_type)
        if not loop_type_uri:
            logger.error(f"回路类型不存在: {loop_type}")
            raise RuntimeException(f"回路类型不存在: {loop_type}")
        # 获取工程URI
        project_uri = Config.MODEL_DEFULT_PROJECT_URI

        # 调用模型核心客户端创建回路(拖拽创建)
        loop_info_result = self.model_core_client.drag_to_with_attributes(
            creator="导入",
            project_uri=project_uri,
            source_uri=loop_type_uri,
            target_uri=parent_uri,
            display_name=loop_displayName,
            browse_name=loop_browseName
        )

        if not loop_info_result.get("success"):
            logger.error(f"模型回路实例化失败: {loop_info_result.get('message')}")
            raise RuntimeException("模型回路实例化失败," + loop_info_result.get("message"))

        loop_uri = loop_info_result.get("result", {}).get("uri")
        logger.info(f"模型回路实例化成功: {loop_displayName}, URI: {loop_uri}")
        return loop_uri

    def _get_loop_point_uri(self, loop_uri: str) -> str:
        """
        获取回路测点信息节点URI
        """
        if not loop_uri:
            logger.error("回路属性信息节点uri获取失败")
            raise RuntimeException("回路属性信息节点uri获取失败")

        loop_uris = self.bff_client.identifier_to_uri(
            identifiers=[loop_uri + Config.BFF_MODEL_POINT_PATH]
        )
        if loop_uris:
            loop_point_uri = loop_uris[0]
            logger.info(f"回路属性信息节点uri: {loop_point_uri}")
            return loop_point_uri

        logger.error("回路属性信息节点uri获取失败")
        raise RuntimeException("回路属性信息节点uri获取失败")
