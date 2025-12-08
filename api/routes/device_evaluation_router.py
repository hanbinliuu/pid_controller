#!/usr/bin/env python3
"""
路由层 - 装置评估API接口
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from api.services.home_page_service import HomePageService
from core.config import Config
from core.database.database import get_db
from api.services.device_evaluation_service import DeviceEvaluationService
from api.services.bff_service import BFFService
from api.bean.device_evaluation import DeviceEvaluation
from api.middleware.exceptions import (
    BusinessException,
    ValidationException,
    DataProcessException,
    ExternalServiceException,
    NotFoundException
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1")


@router.get("/device-evaluation/real-time",
            summary="装置实时统计",
            operation_id="get_evaluation_by_device_uri",
            response_model=Dict[str, Any])
async def get_evaluation_by_device_uri(
        device_uri: Optional[str] = Query(None, description="装置URI"),
        db: Session = Depends(get_db)
):
    # 获取最新的装置评估数据
    try:
        if device_uri is None:
            device_uri = Config.BFF_MODEL_ROOT_URI
        parient_result = DeviceEvaluationService.get_evaluation_by_device_uri_now(db, device_uri)
        child_result = DeviceEvaluationService.get_evaluation_by_parent_device_uri_now(db, device_uri)
        return {
            "device_evaluation": parient_result,
            "child_device_evaluation": child_result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置评估失败: {str(e)}"
        )
@router.get("/device-and-child-evaluation/real-time-list",
            summary="本级及下级装置实时统计列表",
            operation_id="get_this_child_evaluation_now_by_device_uri",
            response_model=List[Any])
async def get_this_child_evaluation_now_by_device_uri(
        device_uri: Optional[str] = Query(None, description="装置URI"),
        db: Session = Depends(get_db)
):
    # 获取最新的装置评估数据
    if device_uri is None:
        device_uri = Config.BFF_MODEL_ROOT_URI
    results = DeviceEvaluationService.get_this_child_by_device_uri_and_date_now(db, device_uri)
    return results

@router.get("/device-evaluation/history-data",
            summary="装置历史统计",
            operation_id="get_history_evaluation_by_device_uri",
            response_model=Dict[str, Any])
async def get_history_evaluation_by_device_uri(
        device_uri: Optional[str] = Query(None, description="装置URI"),
        start_time: Optional[datetime] = Query(None, description="开始时间"),
        end_time: Optional[datetime] = Query(None, description="结束时间"),
        db: Session = Depends(get_db)
):
    # 获取最新的装置评估数据
    try:
        if device_uri is None:
            device_uri = Config.BFF_MODEL_ROOT_URI

        evaluations_result = DeviceEvaluationService.get_evaluations_by_date_range(db, device_uri, start_time, end_time)
        return {
            "evaluations": evaluations_result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置评估失败: {str(e)}"
        )
@router.get("/device-evaluation/page",
            summary="分页查询所有装置评估记录",
            operation_id="list_device_evaluations",
            response_model=Dict[str, Any])
async def list_device_evaluations(
        db: Session = Depends(get_db),
        device_name: Optional[str] = Query(None, description="装置名称"),
        device_uri: Optional[str] = Query(None, description="装置URI"),
        start_time: Optional[datetime] = Query(None, description="开始时间"),
        end_time: Optional[datetime] = Query(None, description="结束时间"),
        is_child: bool = Query(False, description="是否查询下级装置"),
        page_no: int = Query(1, description="页码，从1开始"),
        page_size: int = Query(10, description="每页数量")
):
    """
    分页查询所有装置评估记录
    """

    try:
        if device_uri is None:
            device_uri = Config.BFF_MODEL_ROOT_URI
        result = DeviceEvaluationService.get_evaluations_by_date_range_page(
            db,
            device_name=device_name,
            device_uri=device_uri,
            start_date=start_time,
            end_date=end_time,
            is_child=is_child,
            page_no=page_no,
            page_size=page_size
        )

        evaluations = result["evaluations"]
        pagination = result["pagination"]

        return {
            "evaluations": [
                {
                    "id": e.id,
                    "device_uri": e.device_uri,
                    "device_name": e.device_name,
                    "parent_device_uri": e.parent_device_uri,
                    "statistics_time": e.statistics_time.isoformat(),
                    "loop_count": e.loop_count,
                    "open_loop_count": e.open_loop_count,
                    "auto_loop_count": e.auto_loop_count,
                    "auto_control_rate": e.auto_control_rate,
                    "stable_loop_count": e.stable_loop_count,
                    "stability_rate": e.stability_rate,
                    "conditional_excluded_loop_count": e.conditional_excluded_loop_count,
                    "created_time": e.created_time.isoformat(),
                    "updated_time": e.updated_time.isoformat()
                }
                for e in evaluations
            ],
            "pagination": pagination
        }
    except Exception as e:
        logger.error(f"查询装置评估列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置评估列表失败: {str(e)}"
        )


@router.get("/device-evaluation/history-data",
            summary="装置历史统计",
            operation_id="get_device_evaluations_by_date_range",
            response_model=Dict[str, Any])
async def get_device_evaluations_by_date_range(
        device_uri: Optional[str] = Query(None, description="装置URI，为空则查询所有装置"),
        start_date: Optional[date] = Query(None, description="开始日期（格式：YYYY-MM-DD）"),
        end_date: Optional[date] = Query(None, description="结束日期（格式：YYYY-MM-DD）"),
        db: Session = Depends(get_db)
):
    """
    根据装置URI和时间范围查询装置评估记录（不分页）
    
    参数说明：
    - device_uri: 装置URI（可选，为空则查询所有装置）
    - start_date: 开始日期（可选，包含该日期）
    - end_date: 结束日期（可选，包含该日期）
    
    返回结果按统计时间倒序排列
    """
    try:
        logger.info(
            f"查询装置评估记录 - device_uri: {device_uri or '全部'}, "
            f"start_date: {start_date}, end_date: {end_date}"
        )
        
        evaluations = DeviceEvaluationService.get_evaluations_by_date_range(
            db,
            device_uri=device_uri,
            start_date=start_date,
            end_date=end_date
        )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "evaluations": [
                    {
                        "id": e.id,
                        "device_uri": e.device_uri,
                        "device_name": e.device_name,
                        "parent_device_uri": e.parent_device_uri,
                        "statistics_time": e.statistics_time.isoformat() if e.statistics_time else None,
                        "loop_count": e.loop_count,
                        "auto_loop_count": e.auto_loop_count,
                        "auto_control_rate": e.auto_control_rate,
                        "stable_loop_count": e.stable_loop_count,
                        "stability_rate": e.stability_rate,
                        "conditional_excluded_loop_count": e.conditional_excluded_loop_count,
                        "created_time": e.created_time.isoformat() if e.created_time else None,
                        "updated_time": e.updated_time.isoformat() if e.updated_time else None
                    }
                    for e in evaluations
                ],
                "total": len(evaluations)
            }
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"查询装置评估记录失败 - device_uri: {device_uri}, "
            f"start_date: {start_date}, end_date: {end_date}: {str(e)}",
            exc_info=True
        )
        raise DataProcessException(
            message=f"查询装置评估记录失败: {str(e)}",
            data={
                "device_uri": device_uri,
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None
            }
        )


# ==================== 装置管理接口 ====================

@router.get("/devices/list",
            summary="获取所有装置列表",
            operation_id="get_all_devices",
            response_model=Dict[str, Any])
async def get_all_devices():
    """
    从BFF获取所有装置列表
    
    - 自动分页获取全部装置
    - 使用内置参数：model_identifier_list=/system/401, start_identifier_list=/pid_zd/instance
    
    返回装置列表，包含：
    - uri: 装置URI
    - browseName: 浏览名称
    - displayName: 显示名称
    - parentUri: 父节点URI
    - description: 描述
    - extendedAttr: 扩展属性
    """
    try:
        logger.info("开始获取装置列表")

        devices = BFFService.get_all_devices()

        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "devices": devices,
                "total": len(devices)
            }
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取装置列表失败: {str(e)}", exc_info=True)
        raise ExternalServiceException(
            message=f"获取装置列表失败: {str(e)}",
            data={"error": str(e)}
        )


@router.get("/devices/info/{device_uri:path}",
            summary="根据URI查询装置详情",
            operation_id="get_device_by_uri",
            response_model=Dict[str, Any])
async def get_device_by_uri(device_uri: str):
    """
    根据装置URI查询装置详细信息
    
    Args:
        device_uri: 装置URI（路径参数）
    """
    try:
        logger.info(f"查询装置详情 - URI: {device_uri}")

        # 调用BFF查询单个节点信息
        result = BFFService.query_nodes_by_uris([device_uri])
        nodes = result.get('nodes', [])

        if not nodes:
            raise NotFoundException(
                message=f"未找到URI为 {device_uri} 的装置",
                data={"device_uri": device_uri}
            )

        device = nodes[0]

        return {
            "code": 0,
            "message": "查询成功",
            "data": device
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询装置详情失败 - URI: {device_uri}: {str(e)}", exc_info=True)
        raise ExternalServiceException(
            message=f"查询装置详情失败: {str(e)}",
            data={"device_uri": device_uri}
        )


@router.get("/devices/page",
            summary="装置分页查询",
            operation_id="search_devices",
            response_model=Dict[str, Any])
async def search_devices(
        keyword: Optional[str] = Query(None, description="搜索关键词（匹配URI或名称）"),
        parent_uri: Optional[str] = Query(None, description="父节点URI"),
        page_no: int = Query(1, description="页码，从1开始", ge=1),
        page_size: int = Query(10, description="每页数量", ge=1, le=100)
):
    """
    搜索装置列表
    
    - 支持按关键词搜索（匹配URI或displayName）
    - 支持按父节点URI筛选
    - 支持分页
    """
    try:
        logger.info(f"搜索装置 - 关键词: {keyword}, 父节点: {parent_uri}")

        # 获取所有装置
        all_devices = BFFService.get_all_devices()

        # 过滤装置
        filtered_devices = all_devices

        if keyword:
            filtered_devices = [
                d for d in filtered_devices
                if keyword.lower() in d.get('uri', '').lower()
                   or keyword.lower() in d.get('displayName', '').lower()
                   or keyword.lower() in d.get('browseName', '').lower()
            ]

        if parent_uri:
            filtered_devices = [
                d for d in filtered_devices
                if d.get('parentUri') == parent_uri
            ]

        # 分页
        total = len(filtered_devices)
        start = (page_no - 1) * page_size
        end = start + page_size
        page_devices = filtered_devices[start:end]

        pages = (total + page_size - 1) // page_size if total > 0 else 0

        return {
            "devices": page_devices,
            "pagination": {
                "total": total,
                "pages": pages,
                "pageNo": page_no,
                "pageSize": page_size
            }
        }

    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"搜索装置失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"搜索装置失败: {str(e)}",
            data={"keyword": keyword, "parent_uri": parent_uri}
        )


@router.post("/devices/batch-query",
             summary="批量查询装置详情",
             operation_id="batch_query_devices",
             response_model=Dict[str, Any])
async def batch_query_devices(
        uris: List[str] = Query(..., description="装置URI列表")
):
    """
    批量查询装置详细信息
    
    Args:
        uris: 装置URI列表
    """
    try:
        if not uris:
            raise ValidationException(
                message="URI列表不能为空",
                data={"uris": uris}
            )

        logger.info(f"批量查询装置 - 数量: {len(uris)}")

        result = BFFService.query_nodes_by_uris(uris)
        nodes = result.get('nodes', [])

        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "devices": nodes,
                "total": len(nodes)
            }
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"参数验证失败: {str(e)}", exc_info=True)
        raise ValidationException(
            message=f"参数验证失败: {str(e)}",
            data={"uris": uris}
        )
    except Exception as e:
        logger.error(f"批量查询装置失败: {str(e)}", exc_info=True)
        raise ExternalServiceException(
            message=f"批量查询装置失败: {str(e)}",
            data={"uri_count": len(uris)}
        )


@router.get("/devices/loops-list",
            summary="获取装置下的回路列表",
            operation_id="get_device_loops",
            response_model=Dict[str, Any])
async def get_device_loops(
        device_uri: Optional[str] = Query(..., description="装置URI（模糊匹配）"),
        db: Session = Depends(get_db)
):
    """
    获取装置下的回路列表
    
    通过回路loop_uri模糊匹配装置URI来查找装置下的所有回路
    
    Args:
        device_uri: 装置URI（路径参数）
        include_inactive: 是否包含非激活的回路，默认为False（只返回激活回路）
    
    Returns:
        回路列表
    """
    try:
        logger.info(f"获取装置回路列表 - 装置URI: {device_uri}")

        # 调用Service层方法
        result = DeviceEvaluationService.get_device_loops(
            db,
            device_uri=device_uri
        )

        return {
            "count": len(result),
            "loops": result
        }

    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取装置回路列表失败 - 装置URI: {device_uri}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"获取装置回路列表失败: {str(e)}",
            data={"device_uri": device_uri}
        )
