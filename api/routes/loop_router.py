#!/usr/bin/env python3
"""
回路管理路由
回路管理相关的API接口
"""


import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Query

from core.data.bff_model_client import BFFModelClient
from api.bean.loop_response import LoopListResponse, LoopInstance, PIDParams, Pagination, LoopInfoResponse

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
                        'point_names': ['PB', 'TI', 'TD']
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
                        pid_values = loop_values.get(loop_uri, {})
                        instance['pid_params'] = {
                            'PB': pid_values.get('PB'),
                            'TI': pid_values.get('TI'),
                            'TD': pid_values.get('TD')
                        }
                    
                    logger.info(f"成功查询 {len(loop_values)} 个回路的PID参数")
                    
                except Exception as e:
                    logger.warning(f"查询PID参数失败: {str(e)}, 将返回不包含PID参数的结果")
                    # 如果PID参数查询失败，为每个回路添加空None值
                    for instance in instances:
                        instance['pid_params'] = {
                            'PB': None,
                            'TI': None,
                            'TD': None
                        }

            # 转换为响应模型
            return LoopListResponse(
                instances=[
                    LoopInstance(
                        uri=instance.get('uri'),
                        browseName=instance.get('browseName'),
                        displayName=instance.get('displayName'),
                        description=instance.get('description'),
                        extendedAttr=instance.get('extendedAttr', {}),
                        pid_params=PIDParams(
                            PB=instance.get('pid_params', {}).get('PB'),
                            TI=instance.get('pid_params', {}).get('TI'),
                            TD=instance.get('pid_params', {}).get('TD')
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
            description="回路 URI，默认从环境变量 BFF_MODEL_PROJECT_PATH 读取",
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
        # 使用BFF客户端查询回路测点值
        with BFFModelClient(device_uri=loop_uri) as client:
            # 查询回路节点信息
            nodes_result = client.query_nodes_by_uris([loop_uri]).get("nodes")
            # 判断是否获取回路节点信息成功
            if len(nodes_result)==0:
                return LoopInfoResponse(
                    uri=loop_uri,
                    browseName=None,
                    displayName=None,
                    description=None,
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
                'auto_control_status',  # 自控情况
                'action_type',          # 正反作用
                'sv_range_max',         # 目标值量程上限
                'sv_range_min',         # 目标值量程下限
                'mv_range_max',         # 阀位值量程上限
                'mv_range_min'          # 阀位值量程下限
            ]
            
            # 查询测点当前值
            point_values = client.query_current_raw_values(point_names)
            
            # 转换为响应模型
            return LoopInfoResponse(
                uri=loop_uri,
                browseName=loop_info.get('browseName'),
                displayName=loop_info.get('displayName'),
                description=loop_info.get('description'),
                extendedAttr=loop_info.get('extendedAttr', {}),
                auto_control_status=point_values.get('auto_control_status'),
                action_type=point_values.get('action_type'),
                sv_range_max=point_values.get('sv_range_max'),
                sv_range_min=point_values.get('sv_range_min'),
                mv_range_max=point_values.get('mv_range_max'),
                mv_range_min=point_values.get('mv_range_min')
            )
    
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
            description="回路 URI，默认从环境变量 BFF_MODEL_PROJECT_PATH 读取",
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
        # 使用BFF客户端查询
        with BFFModelClient(device_uri=loop_uri) as client:
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
