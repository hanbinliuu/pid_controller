#!/usr/bin/env python3
"""
回路管理路由
回路管理相关的API接口
"""


import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from core.data.bff_model_client import BFFModelClient

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/list-loop",
    summary="查询对应节点下的回路列表",
    operation_id="查询对应节点下的回路列表",
    description="根据回路类型URI和起始节点URI查询节点下的回路列表，支持分页"
)
async def list_instances_under_tree(
        model_identifier_list: List[str] = Query(
            ...,
            description="回路类型URI",
            example=["/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"]
        ),
        start_identifier_list: List[str] = Query(
            ...,
            description="起始节点URI",
            example=["/pid_zd/053f3c45413b48bbafacec609d142e57"]
        ),
        contain_sub_model: bool = Query(
            True,
            description="是否包含子类型"
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
    summary="查询回路测点当前最新值",
    operation_id="查询回路测点当前最新值",
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

@router.get(
    "/next-loop-type",
    summary="获取子回路类型",
    operation_id="获取子回路类型",
    description="根据模型标识符获取其下一级的子回路列表"
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
        # 使用BFF客户端查询
        with BFFModelClient() as client:
            result = client.get_next_level_submodel(identifier)

            logger.info(f"子类型查询成功: {identifier}, 回路类型数量: {result.get('total', 0)}")

            return result

    except Exception as e:
        logger.error(f"回路子类型查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路子类型失败: {str(e)}"
        )
