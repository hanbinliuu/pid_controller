#!/usr/bin/env python3
"""
BFF模型查询路由
提供BFF模型相关的API接口
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from core.data.bff_model_client import BFFModelClient
from core.config import Config

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/point-paths",
    summary="查询项目路径下的测点路径",
    operation_id="查询BFF项目测点路径",
    description="查询指定项目路径下的所有PID控制相关测点路径，返回IoT格式的字段映射"
)
async def get_point_paths(
    project_path: Optional[str] = Query(
        None,
        description="项目路径前缀，默认从环境变量BFF_MODEL_PROJECT_PATH读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    )
) -> Dict[str, Any]:
    """
    查询BFF项目路径下的测点路径
    
    功能说明：
    - 查询指定项目下的所有PID控制字段（MV, PV, SV, PB, TI, TD）
    - 返回IoT格式的字段映射关系
    
    返回格式：
    {
        "status": "success",
        "project_path": "/pid_zd/xxx",
        "field_mapping": {
            "mv": "ns=100;s=FIC101A_MV.In_Channel0",
            "pv": "ns=100;s=FIC101A_PV.In_Channel0",
            ...
        }
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient(device_uri=project_path) as client:
            # 查询常用字段
            common_field_map = client.query_common_fields()
            
            logger.info(f"BFF查询成功，项目路径: {client.device_uri}")

            # 生成字段映射（根据MV/PV/SV等标识）
            # field_mapping = BFFModelClient.parse_path_list_to_field_mapping(result_paths)
            
            return {
                "project_path": client.device_uri,
                "point_path": client.point_path,
                "model_point_map":common_field_map
            }
    
    except Exception as e:
        logger.error(f"查询BFF测点路径失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点路径失败: {str(e)}"
        )


@router.get(
    "/point-values",
    summary="查询测点当前值",
    operation_id="查询BFF测点当前值",
    description="查询指定项目路径下所有PID控制测点的当前值"
)
async def get_point_values(
    project_path: Optional[str] = Query(
        None,
        description="项目路径前缀，默认从环境变量BFF_MODEL_PROJECT_PATH读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    )
) -> Dict[str, Any]:
    """
    查询BFF项目路径下测点的当前值
    
    功能说明：
    - 查询所有PID控制字段的实时值
    - 返回字段名和对应的数值
    
    返回格式：
    {
        "status": "success",
        "project_path": "/pid_zd/xxx",
        "values": {
            "mv": 45.2,
            "pv": 23.1,
            "sv": 25.0,
            ...
        }
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient(device_uri=project_path) as client:
            # 查询常用字段
            query_result = client.query_common_fields()
            values = list(query_result.values())
            return {
                "project_path": client.device_uri,
                "values": values,
                "total_points": len(values)
            }
    
    except Exception as e:
        logger.error(f"查询BFF测点值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点值失败: {str(e)}"
        )


@router.get(
    "/table-points",
    summary="查询表名和测点列表",
    operation_id="查询BFF表名和测点列表",
    description="根据项目路径查询表名和测点名称列表"
)
async def get_table_and_points(
    project_path: Optional[str] = Query(
        None,
        description="项目路径前缀，默认从环境变量BFF_MODEL_PROJECT_PATH读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    ),
    point_path: Optional[str] = Query(
        'loop_state_parameters',
        description="测点路径，默认从环境变量BFF_MODEL_POINT_PATH读取",
        example="/loop_state_parameters"
    )
) -> Dict[str, Any]:
    """
    根据项目路径查询表名和测点列表
    
    功能说明：
    - 查询指定项目下的所有PID控制字段
    - 返回table名称和测点名称映射
    
    返回格式：
    {
        "status": "success",
        "project_path": "/pid_zd/xxx",
        "point_path": "/ZTCS",
        "table_name": "PID_FEP_Gateway_Device_001default",
        "points": {
            "mv": "ns=100;s=FIC101A_MV.In_Channel0",
            "pv": "ns=100;s=FIC101A_PV.In_Channel0",
            "sv": "ns=100;s=FIC101A_SV.In_Channel0",
            "pb": "ns=100;s=FIC101A_PB.In_Channel0",
            "ti": "ns=100;s=FIC101A_TI.In_Channel0",
            "td": "ns=100;s=FIC101A_TD.In_Channel0"
        },
        "total_points": 6
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient(device_uri=project_path, point_path=point_path) as client:
            # 查询常用字段
            query_result = client.query_common_fields()
            
            # 提取table名称和测点列表，传入query_paths和result_paths
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
            
            return {
                "project_path": client.device_uri,
                "point_path": client.point_path,
                "table_name": table_name,
                "points": points,
                "total_points": len(points)
            }
    
    except Exception as e:
        logger.error(f"查询表名和测点列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询表名和测点列表失败: {str(e)}"
        )


@router.get(
    "/config",
    summary="获取BFF配置信息",
    operation_id="获取BFF配置",
    description="获取当前BFF模型查询的配置信息"
)
async def get_bff_config() -> Dict[str, Any]:
    """
    获取BFF配置信息
    
    返回当前的BFF服务配置，包括：
    - 基础URL
    - 超时时间
    - 默认项目路径
    """
    try:
        config = Config.get_bff_model_config()
        
        return {
            "config": config
        }
    
    except Exception as e:
        logger.error(f"获取BFF配置失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取配置失败: {str(e)}"
        )


@router.get(
    "/next-level-submodel",
    summary="获取下一级子模型",
    operation_id="获取下一级子模型",
    description="根据模型标识符获取其下一级的子模型列表"
)
async def get_next_level_submodel(
    identifier: str = Query(
        ...,
        description="模型标识符，URI路径",
        example="/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"
    )
) -> Dict[str, Any]:
    """
    获取下一级子模型
    
    功能说明：
    - 查询指定模型标识符下的所有子模型
    - 返回简化后的模型信息
    
    返回格式：
    {
        "submodels": [
            {
                "uri": "/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1",
                "browseName": "flow_loop_model",
                "displayName": "流量单回路模型",
                "extendedAttr": {"loop_type": "流量"},
                "parentUri": "/pid_zd/d4d2d8c4906846818c91e4fe06a290a2"
            }
        ],
        "total": 1
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient() as client:
            result = client.get_next_level_submodel(identifier)
            
            logger.info(f"BFF查询成功，模型标识符: {identifier}, 子模型数量: {result.get('total', 0)}")
            
            return result
    
    except Exception as e:
        logger.error(f"查询下一级子模型失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询子模型失败: {str(e)}"
        )


@router.post(
    "/list-instances",
    summary="查询实例树下的实例列表",
    operation_id="查询实例树下的实例列表",
    description="根据模型标识符和起始标识符查询实例树下的实例列表，支持分页"
)
async def list_instances_under_tree(
    model_identifier_list: List[str] = Query(
        ...,
        description="模型标识符列表",
        example=["/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"]
    ),
    start_identifier_list: List[str] = Query(
        ...,
        description="起始标识符列表",
        example=["/pid_zd/053f3c45413b48bbafacec609d142e57"]
    ),
    contain_sub_model: bool = Query(
        True,
        description="是否包含子模型"
    ),
    page_no: int = Query(
        1,
        description="页码",
        ge=1
    ),
    page_size: int = Query(
        10,
        description="每页数量",
        ge=1,
        le=100
    )
) -> Dict[str, Any]:
    """
    查询实例树下的实例列表
    
    功能说明：
    - 根据模型标识符和起始标识符查询实例树
    - 支持分页查询
    - 返回简化后的实例信息
    
    返回格式：
    {
        "instances": [
            {
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "browseName": "flow_loop_model_1",
                "displayName": "流量单回路实例_1",
                "description": "创建根节点，用于组织模型结构",
                "extendedAttr": {"loop_type": "流量"}
            }
        ],
        "pagination": {
            "total": 2,
            "pages": 1,
            "pageNo": 1,
            "pageSize": 10
        }
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient() as client:
            result = client.list_instances_under_tree(
                model_identifier_list=model_identifier_list,
                start_identifier_list=start_identifier_list,
                contain_sub_model=contain_sub_model,
                page_no=page_no,
                page_size=page_size
            )
            
            logger.info(
                f"BFF查询成功，模型标识符: {model_identifier_list}, "
                f"起始标识符: {start_identifier_list}, "
                f"实例数量: {len(result.get('instances', []))}"
            )
            
            return result
    
    except Exception as e:
        logger.error(f"查询实例树失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询实例树失败: {str(e)}"
        )


@router.post(
    "/current-raw-values",
    summary="查询测点当前最新值",
    operation_id="查询测点当前最新值",
    description="根据回路 URI 和测点名称查询测点的当前最新值"
)
async def query_current_raw_values(
    point_names: List[str],
    loop_uri: Optional[str] = Query(
        None,
        description="回路 URI，默认从环境变量 BFF_MODEL_PROJECT_PATH 读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    ),
    point_path: Optional[str] = Query(
        None,
        description="测点路径，默认从环境变量 BFF_MODEL_POINT_PATH 读取",
        example="loop_state_parameters"
    )
) -> Dict[str, Any]:
    """
    查询测点当前原始值
    
    功能说明：
    - 提供公共的 loop_uri 和 point_path，只需传入测点名称列表
    - 自动拼接完整的浏览路径
    - 返回测点名称到值的映射
    - 只返回v值（数值）
    
    请求体示例：
    [
        "PB",
        "TI",
        "TD",
        "PV",
        "SV",
        "MV"
    ]
    
    返回格式：
    {
        "PB": 71.43,
        "TI": 3.11,
        "TD": 2,
        "PV": 10,
        "SV": 10,
        "MV": 15.979299
    }
    """
    try:
        # 使用BFF客户端查询
        with BFFModelClient(device_uri=loop_uri, point_path=point_path) as client:
            result = client.query_current_raw_values(point_names)
            
            logger.info(f"BFF查询成功，测点数量: {len(result)}")
            
            return result
    
    except Exception as e:
        logger.error(f"查询测点当前值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点当前值失败: {str(e)}"
        )


@router.post(
    "/loop-list",
    summary="查询回路列表",
    operation_id="查询回路列表",
    description="查询回路列表并获取每个回路的PID参数当前值"
)
async def query_loop_list(
    loop_type_uri_list: List[str] = Query(
        ...,
        description="回路类型URI",
        example=["/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"]
    ),
    start_identifier_list: List[str] = Query(
        ...,
        description="实例起始URI",
        example=["/pid_zd/053f3c45413b48bbafacec609d142e57"]
    ),
    loop_name: Optional[str] = Query(
        None,
        description="回路名称筛选",
        example=""
    ),
    # contain_sub_model: bool = Query(
    #     True,
    #     description="是否包含子模型"
    # ),
    # point_path: Optional[str] = Query(
    #     "/loop_state_parameters",
    #     description="测点路径",
    #     example="/loop_state_parameters"
    # ),
    page_no: int = Query(
        1,
        description="页码",
        ge=1
    ),
    page_size: int = Query(
        10,
        description="每页数量",
        ge=1,
        le=100
    )
) -> Dict[str, Any]:
    """
    查询回路列表
    
    功能说明：
    - 查询指定模型下的回路实例列表
    - 获取每个回路的PID参数当前值（PB, TI, TD）
    - 支持按回路类型和名称筛选
    - 支持分页查询
    
    返回格式：
    {
        "loops": [
            {
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "browseName": "FIC01",
                "displayName": "流量单回路实例_1",
                "description": "成品储罐液位控制系统",
                "loopType": "流量",
                "autoStatus": "自动",
                "pidParams": "PB:100, TI:50, TD:23"
            }
        ],
        "pagination": {
            "total": 50,
            "pages": 5,
            "pageNo": 1,
            "pageSize": 10
        }
    }
    """
    try:
        # 使用BFF客户端查询实例列表
        with BFFModelClient() as client:
            instances_result = client.list_instances_under_tree(
                model_identifier_list=loop_type_uri_list,
                start_identifier_list=start_identifier_list,
                contain_sub_model=True,
                page_no=page_no,
                page_size=page_size
            )
            
            instances = instances_result.get('instances', [])
            pagination = instances_result.get('pagination', {})
            
            # 筛选回路（按回路名称）
            filtered_instances = []
            for instance in instances:
                # 按回路名称筛选
                if loop_name:
                    browse_name = instance.get('browseName', '')
                    if loop_name.lower() not in browse_name.lower():
                        continue
                
                filtered_instances.append(instance)
            
            # 构建回路配置列表，准备一次性查询所有回路的PID参数
            loop_configs = [
                {
                    'loop_uri': instance.get('uri'),
                    'point_names': ['PB', 'TI', 'TD']
                }
                for instance in filtered_instances
            ]
            
            # 一次性查询所有回路的PID参数值
            loop_values = {}
            if loop_configs:
                try:
                    loop_values = client.query_multi_loop_current_values(
                        loop_configs=loop_configs
                    )
                except Exception as e:
                    logger.warning(f"批量查询回路 PID参数失败: {str(e)}")
            
            # 构建回路列表
            loops = []
            for instance in filtered_instances:
                loop_uri = instance.get('uri')
                extended_attr = instance.get('extendedAttr', {})
                
                # 从查询结果中获取PID参数值
                pid_values = loop_values.get(loop_uri, {})
                
                # 格式化PID参数字符串
                pb = pid_values.get('PB', '-')
                ti = pid_values.get('TI', '-')
                td = pid_values.get('TD', '-')
                pid_params_str = f"PB:{pb}, TI:{ti}, TD:{td}"
                
                # 构建回路信息
                loop_info = {
                    "uri": loop_uri,
                    "browseName": instance.get('browseName', ''),
                    "displayName": instance.get('displayName', ''),
                    "description": instance.get('description', ''),
                    "loopType": extended_attr.get('loop_type', ''),
                    "autoStatus": extended_attr.get('auto_status', '自动'),  # 默认自动
                    "pidParams": pid_params_str
                }
                loops.append(loop_info)
            
            logger.info(
                f"BFF查询成功，回路类型: {loop_type_uri_list}, "
                f"回路数量: {len(loops)}"
            )
            
            return {
                "loops": loops,
                "pagination": pagination
            }
    
    except Exception as e:
        logger.error(f"查询回路列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路列表失败: {str(e)}"
        )
