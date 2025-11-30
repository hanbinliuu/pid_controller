#!/usr/bin/env python3
"""
BFF模型查询路由 - MVC架构的Controller层
使用api.services封装业务逻辑
提供BFF模型相关的API接口
"""

import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.client.bff_model_client import Config
from api.services.bff_service import BFFService


class SearchByModelsRequest(BaseModel):
    """按模型类型查询实例的请求体"""
    includeSubType: bool = True
    modelUriList: List[str]
    startUri: str


class QueryInstanceTreeRequest(BaseModel):
    """查询实例树的请求体"""
    startUri: str
    modelUriList: Optional[List[str]] = None
    includeSubType: bool = True

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
        # 调用Service层查询
        result = BFFService.get_point_paths(project_path)
        
        return result
    
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
async def query_current_raw_values(
        point_names: List[str]=Query(
            None,
            description="测点列表",
            example=["PV","MV","SV","PB","TI","TD","AUTO"]
        ),
        loop_uri: Optional[str] = Query(
            None,
            description="实例 URI，默认从环境变量 BFF_MODEL_PROJECT_PATH 读取",
            example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
        ),
        point_path: Optional[str] = Query(
            None,
            description="测点路径，默认从环境变量 BFF_MODEL_POINT_PATH 读取",
            example="/loop_state_parameters"
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
        # 调用Service层查询
        result = BFFService.get_point_values(point_names, loop_uri, point_path)
        
        return result
    
    except Exception as e:
        logger.error(f"查询测点当前值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点当前值失败: {str(e)}"
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
        # 调用Service层查询
        result = BFFService.get_table_and_points(project_path, point_path)
        
        return result
    
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
        # 调用Service层查询
        result = BFFService.get_next_level_submodel(identifier)
        
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
    summary="查询节点下指定模型类型的实例列表",
    operation_id="查询节点下指定模型类型的实例列表",
    description="根据模型标识符和起始标识符查询指定节点下的实例列表，支持分页"
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
        # 调用Service层查询
        result = BFFService.list_instances_under_tree(
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
    "/nodes-detail",
    summary="根据URI查询节点详细信息",
    operation_id="根据URI查询节点详细信息",
    description="根据URI列表查询节点的详细信息，包括名称、描述、父节点、类型、路径等"
)
async def query_nodes_detail(
        uris: List[str] = Query(
            ...,
            description="节点URI列表",
            example=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]
        )
) -> Dict[str, Any]:
    """
    根据URI列表查询节点详细信息
    
    功能说明：
    - 支持批量查询多个节点的详细信息
    - 返回节点的完整属性（名称、描述、父节点、类型、路径等）
    
    返回格式：
    {
        "nodes": [
            {
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "browseName": "flow_loop_model_1",
                "displayName": "流量单回路实例_1",
                "description": "催化车间-流量回路1",
                "extendedAttr": {"loop_type": "流量"},
                "parentUri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
                "typeUri": "/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1",
                "displayNamePath": "root,PID参数整定_勿删,...",
                "browseNamePath": "root,pid_zd,instance,..."
            }
        ],
        "total": 1
    }
    """
    try:
        # 调用Service层查询
        result = BFFService.query_nodes_by_uris(uris)
        
        logger.info(f"BFF查询成功，节点详细信数量: {result.get('total', 0)}")
        
        return result
    
    except Exception as e:
        logger.error(f"查询节点详细信失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询节点详细信失败: {str(e)}"
        )


@router.post(
    "/instance-tree",
    summary="查询实例树",
    operation_id="查询实例树",
    description="查询从指定节点开始的实例树（树形结构）"
)
async def get_instance_tree(
    request: QueryInstanceTreeRequest
) -> Dict[str, Any]:
    """
    查询实例树（树形结构）
    
    请求体示例：
    {
        "startUri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
        "modelUriList": ["/system/401", "/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"],
        "includeSubType": true
    }
    
    功能说明：
    - 查询从指定节点开始的完整树结构
    - 支持任意深度的嵌套节点
    - 返回根节点和所有子节点信息
    - 可选指定模型URI列表进行过滤
    
    返回格式：
    {
        "result": {
            "node": {
                "uri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
                "browseName": "instance",
                "displayName": "PID参数整定_勿删",
                "description": "创建根节点，用于组织模型结构",
                "extendedAttr": {}
            },
            "children": [
                {
                    "uri": "/pid_zd/xxx",
                    "browseName": "xxx",
                    "displayName": "xxx",
                    "description": "xxx",
                    "extendedAttr": {},
                    "children": [...]
                }
            ]
        }
    }
    """
    try:
        # 调用Service层查询
        result = BFFService.query_instance_tree(
            start_uri=request.startUri,
            model_uri_list=request.modelUriList,
            include_sub_type=request.includeSubType
        )
        
        logger.info(f"BFF查询实例树成功，起始URI: {request.startUri}")
        
        return result
    
    except Exception as e:
        logger.error(f"查询实例树失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询实例树失败: {str(e)}"
        )