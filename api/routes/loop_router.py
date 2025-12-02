#!/usr/bin/env python3
"""
回路管理路由
回路管理相关的API接口
"""


import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from api.response.loop_response import LoopListResponse, LoopInfoResponse
from api.services.loop_service import LoopService
from core.config import Config

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/list-loop",
    summary="查询对应节点下的回路列表",
    operation_id="查询对应节点下的回路列表",
    description="根据回路类型URI和起始节点URI查询节点下的回路列表，支持分页"
)
async def list_instances_by_uri(
        node_uri: List[str] = Query(
            None,
            description="起始节点URI",
            example=[Config.BFF_MODEL_ROOT_URI]
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
) -> LoopListResponse:
    """
    查询实例树下的实例列表

    功能说明：
    - 根据模型标识符和起始标识符查询实例树
    - 支持分页查询
    - 返回简化后的实例信息
    - 自动查询每个回路的PID参数最新值 (PB, TI, TD)

    返回格式：参考 LoopListResponse 模型
    """
    try:
        if node_uri is None:
            node_uri = [Config.BFF_MODEL_ROOT_URI]
        # 调用Service层查询回路列表
        result = LoopService.list_instances_by_node(
            model_identifier_list=[Config.BFF_MODEL_LOOP_MODEL_URI],
            start_identifier_list=node_uri,
            page_no=page_no,
            page_size=page_size
        )

        return result

    except Exception as e:
        logger.error(f"查询实例树失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询实例树失败: {str(e)}"
        )

@router.post(
    "/loop-info",
    summary="查询回路属性",
    operation_id="查询回路属性",
    description="根据回路URI查询回路的详细属性信息，包括回路名称、类型、自控情况、正反作用等"
)
async def query_loop_info(
        loop_uri: Optional[str] = Query(
            None,
            description="回路 URI，默认从 BFF_MODEL_LOOP_URI 读取",
            example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
        )
) -> LoopInfoResponse:
    """
    查询回路详细属性
    
    功能说明：
    - 查询回路的基本信息（名称、类型、描述等）
    - 查询回路的控制参数（自控情况、正反作用）
    - 查询回路的量程信息（目标值量程、阀位值量程）
    
    返回格式：参考 LoopInfoResponse 模型
    """
    try:
        # 调用Service层查询回路信息
        result = LoopService.query_loop_info(loop_uri=loop_uri)
        
        return result
    
    except Exception as e:
        logger.error(f"查询回路属性失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路属性失败: {str(e)}"
        )

@router.post(
    "/loop-values",
    summary="查询回路测点当前最新值",
    operation_id="查询回路测点当前最新值",
    description="根据回路 URI 和测点名称查询测点的当前最新值"
)
async def query_loop_values(
        point_names: List[str],
        loop_uri: Optional[str] = Query(
            None,
            description="回路 URI，默认从 BFF_MODEL_LOOP_URI 读取",
            example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
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
        # 调用Service层查询回路测点值
        result = LoopService.query_loop_values(
            point_names=point_names,
            loop_uri=loop_uri
        )

        logger.info(f"查询成功，测点数量: {len(result)}")

        return result

    except Exception as e:
        logger.error(f"查询测点当前值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点当前值失败: {str(e)}"
        )

@router.get(
    "/next-loop-type",
    summary="获取回路类型",
    operation_id="获取回路类型",
    description="根据模型标识符获取子回路列表"
)
async def get_next_loop_type(
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
        # 调用Service层获取下一级子模型
        result = LoopService.get_next_loop_type(identifier=identifier)

        logger.info(f"子类型查询成功: {identifier}, 回路类型数量: {result.get('total', 0)}")

        return result

    except Exception as e:
        logger.error(f"回路子类型查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路子类型失败: {str(e)}"
        )