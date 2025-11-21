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
        example="/pid_zd/935cf045bd254867bdfeb113c31467da"
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
        with BFFModelClient(project_path=project_path) as client:
            # 查询常用字段
            query_result = client.query_common_fields()
            
            logger.info(f"BFF查询成功，项目路径: {client.project_path}")
            
            # 提取原始响应和浏览路径
            raw_response = query_result.get('raw_response', {})
            browse_paths = query_result.get('browse_paths', [])
            
            logger.debug(f"BFF响应数据: {raw_response}")
            logger.debug(f"浏览路径: {browse_paths}")
            
            # 提取result字段
            result_paths = raw_response.get('result', [])
            if not result_paths:
                logger.warning("响应中未找到result字段")
                return {
                    "status": "warning",
                    "project_path": client.project_path,
                    "message": "查询成功但未解析到测点路径",
                    "raw_response": raw_response
                }
            
            # 按顺序映射浏览路径到测点路径
            path_mapping = BFFModelClient.map_browse_paths_to_result(
                browse_paths=browse_paths,
                result_paths=result_paths
            )
            
            # 生成字段映射（根据MV/PV/SV等标识）
            # field_mapping = BFFModelClient.parse_path_list_to_field_mapping(result_paths)
            
            return {
                "status": "success",
                "project_path": client.project_path,
                "path_mapping": path_mapping,
                # "field_mapping": field_mapping,
                "total_fields": len(path_mapping)
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
        example="/pid_zd/935cf045bd254867bdfeb113c31467da"
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
        with BFFModelClient(project_path=project_path) as client:
            # 查询常用字段
            query_result = client.query_common_fields()
            raw_response = query_result.get('raw_response', {})
            
            logger.info(f"BFF查询成功，项目路径: {client.project_path}")
            
            # 解析测点uri
            values = client.parse_response(raw_response)
            
            if not values:
                logger.warning("未能解析出有效的测点值")
                return {
                    "status": "warning",
                    "project_path": client.project_path,
                    "message": "查询成功但未解析到测点值",
                    "raw_response": raw_response
                }
            
            return {
                "status": "success",
                "project_path": client.project_path,
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
            "status": "success",
            "config": config
        }
    
    except Exception as e:
        logger.error(f"获取BFF配置失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取配置失败: {str(e)}"
        )
