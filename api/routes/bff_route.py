#!/usr/bin/env python3
"""
BFF模型查询路由
提供BFF模型相关的API接口
"""

import logging
from typing import Optional, Dict, Any
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
