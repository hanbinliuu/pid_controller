#!/usr/bin/env python3
"""
路由层 - 装置评估API接口
"""
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

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


@router.post("/device-evaluation/upsert",
            summary="按天和装置URI创建或更新评估",
            operation_id="upsert_device_evaluation",
            response_model=Dict[str, Any])
async def upsert_device_evaluation(
    device_uri: str = Query(..., description="装置 URI"),
    device_name: str = Query(..., description="装置名称"),
    statistics_date: str = Query(..., description="统计日期(格式: YYYY-MM-DD)"),
    loop_count: int = Query(..., description="回路数"),
    auto_loop_count: int = Query(..., description="自动回路数"),
    auto_control_rate: float = Query(..., description="自控率"),
    stable_loop_count: int = Query(..., description="平稳回路数"),
    stability_rate: float = Query(..., description="平稳率"),
    conditional_excluded_loop_count: int = Query(..., description="条件剔除回路数"),
    parent_device_uri: Optional[str] = Query(None, description="父类装置URI"),
    db: Session = Depends(get_db)
):
    """
    按天和装置URI创建或更新装置评估记录
    
    - 如果同一天同一装置已存在记录，则更新
    - 否则创建新记录
    - statistics_date 只保留日期部分，时间为00:00:00
    """
    try:
        # 解析日期字符串
        try:
            stats_date = datetime.strptime(statistics_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"日期格式错误，应为 YYYY-MM-DD 格式，得到: {statistics_date}"
            )
        
        evaluation = DeviceEvaluationService.create_or_update_evaluation(
            db,
            device_uri=device_uri,
            device_name=device_name,
            statistics_date=stats_date,
            loop_count=loop_count,
            auto_loop_count=auto_loop_count,
            auto_control_rate=auto_control_rate,
            stable_loop_count=stable_loop_count,
            stability_rate=stability_rate,
            conditional_excluded_loop_count=conditional_excluded_loop_count,
            parent_device_uri=parent_device_uri
        )
        
        return {
            "code": 0,
            "message": "操作成功",
            "data": {
                "id": evaluation.id,
                "device_uri": evaluation.device_uri,
                "device_name": evaluation.device_name,
                "parent_device_uri": evaluation.parent_device_uri,
                "statistics_time": evaluation.statistics_time.date().isoformat(),
                "loop_count": evaluation.loop_count,
                "auto_loop_count": evaluation.auto_loop_count,
                "auto_control_rate": evaluation.auto_control_rate,
                "stable_loop_count": evaluation.stable_loop_count,
                "stability_rate": evaluation.stability_rate,
                "conditional_excluded_loop_count": evaluation.conditional_excluded_loop_count,
                "created_time": evaluation.created_time.isoformat(),
                "updated_time": evaluation.updated_time.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建/更新装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"创建/更新装置评估失败: {str(e)}"
        )


@router.post("/device-evaluation",
            summary="创建装置评估",
            operation_id="create_device_evaluation",
            response_model=Dict[str, Any])
async def create_device_evaluation(
    device_uri: str = Query(..., description="装置 URI"),
    device_name: str = Query(..., description="装置名称"),
    statistics_time: str = Query(..., description="统计时间"),
    loop_count: int = Query(..., description="回路数"),
    auto_loop_count: int = Query(..., description="自动回路数"),
    auto_control_rate: float = Query(..., description="自控率"),
    stable_loop_count: int = Query(..., description="平稳回路数"),
    stability_rate: float = Query(..., description="平稳率"),
    conditional_excluded_loop_count: int = Query(..., description="条件剔除回路数"),
    parent_device_uri: Optional[str] = Query(None, description="父类装置URI"),
    db: Session = Depends(get_db)
):
    """
    创建装置评估记录
    
    创建成功时返回创建的评估对象
    """
    try:
        evaluation = DeviceEvaluationService.create_evaluation(
            db,
            device_uri=device_uri,
            device_name=device_name,
            statistics_time=statistics_time,
            loop_count=loop_count,
            auto_loop_count=auto_loop_count,
            auto_control_rate=auto_control_rate,
            stable_loop_count=stable_loop_count,
            stability_rate=stability_rate,
            conditional_excluded_loop_count=conditional_excluded_loop_count,
            parent_device_uri=parent_device_uri
        )
        
        return {
            "code": 0,
            "message": "创建成功",
            "data": {
                "id": evaluation.id,
                "device_uri": evaluation.device_uri,
                "device_name": evaluation.device_name,
                "statistics_time": evaluation.statistics_time.isoformat(),
                "created_time": evaluation.created_time.isoformat()
            }
        }
    except Exception as e:
        logger.error(f"创建装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"创建装置评估失败: {str(e)}"
        )


@router.get("/device-evaluation/{evaluation_id}",
           summary="根据ID查询评估",
           operation_id="get_evaluation_by_id",
           response_model=Dict[str, Any])
async def get_evaluation_by_id(
    evaluation_id: int,
    db: Session = Depends(get_db)
):
    """
    根据ID查询装置评估记录
    """
    try:
        evaluation = DeviceEvaluationService.get_evaluation_by_id(db, evaluation_id)
        
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {evaluation_id} 的评估记录"
            )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "id": evaluation.id,
                "device_uri": evaluation.device_uri,
                "device_name": evaluation.device_name,
                "parent_device_uri": evaluation.parent_device_uri,
                "statistics_time": evaluation.statistics_time.isoformat(),
                "loop_count": evaluation.loop_count,
                "auto_loop_count": evaluation.auto_loop_count,
                "auto_control_rate": evaluation.auto_control_rate,
                "stable_loop_count": evaluation.stable_loop_count,
                "stability_rate": evaluation.stability_rate,
                "conditional_excluded_loop_count": evaluation.conditional_excluded_loop_count,
                "created_time": evaluation.created_time.isoformat(),
                "updated_time": evaluation.updated_time.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置评估失败: {str(e)}"
        )


@router.get("/device-evaluation/list",
           summary="分页查询评估列表",
           operation_id="list_device_evaluations",
           response_model=Dict[str, Any])
async def list_device_evaluations(
    device_name: Optional[str] = Query(None, description="装置名称（模糊匹配）"),
    device_uri: Optional[str] = Query(None, description="装置URI（模糊匹配）"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    分页查询所有装置评估记录
    """
    try:
        result = DeviceEvaluationService.list_evaluations(
            db,
            device_name=device_name,
            device_uri=device_uri,
            page_no=page_no,
            page_size=page_size
        )
        
        evaluations = result["evaluations"]
        pagination = result["pagination"]
        
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
                        "statistics_time": e.statistics_time.isoformat(),
                        "loop_count": e.loop_count,
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
        }
    except Exception as e:
        logger.error(f"查询装置评估列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置评估列表失败: {str(e)}"
        )


@router.put("/device-evaluation/{evaluation_id}",
           summary="更新装置评估",
           operation_id="update_device_evaluation",
           response_model=Dict[str, Any])
async def update_device_evaluation(
    evaluation_id: int,
    device_uri: Optional[str] = Query(None, description="新的装置 URI"),
    device_name: Optional[str] = Query(None, description="新的装置名称"),
    statistics_time: Optional[str] = Query(None, description="新的统计时间"),
    loop_count: Optional[int] = Query(None, description="新的回路数"),
    auto_loop_count: Optional[int] = Query(None, description="新的自动回路数"),
    auto_control_rate: Optional[float] = Query(None, description="新的自控率"),
    stable_loop_count: Optional[int] = Query(None, description="新的平稳回路数"),
    stability_rate: Optional[float] = Query(None, description="新的平稳率"),
    conditional_excluded_loop_count: Optional[int] = Query(None, description="新的条件剔除回路数"),
    parent_device_uri: Optional[str] = Query(None, description="新的父类装置URI"),
    db: Session = Depends(get_db)
):
    """
    更新装置评估记录
    """
    try:
        evaluation = DeviceEvaluationService.update_evaluation(
            db,
            evaluation_id=evaluation_id,
            device_uri=device_uri,
            device_name=device_name,
            statistics_time=statistics_time,
            loop_count=loop_count,
            auto_loop_count=auto_loop_count,
            auto_control_rate=auto_control_rate,
            stable_loop_count=stable_loop_count,
            stability_rate=stability_rate,
            conditional_excluded_loop_count=conditional_excluded_loop_count,
            parent_device_uri=parent_device_uri
        )
        
        if not evaluation:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {evaluation_id} 的评估记录"
            )
        
        return {
            "code": 0,
            "message": "更新成功",
            "data": {
                "id": evaluation.id,
                "device_uri": evaluation.device_uri,
                "device_name": evaluation.device_name,
                "statistics_time": evaluation.statistics_time.isoformat(),
                "updated_time": evaluation.updated_time.isoformat()
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"更新装置评估失败: {str(e)}"
        )


@router.delete("/device-evaluation/{evaluation_id}",
              summary="删除装置评估",
              operation_id="delete_device_evaluation",
              response_model=Dict[str, Any])
async def delete_device_evaluation(
    evaluation_id: int,
    db: Session = Depends(get_db)
):
    """
    删除指定的装置评估记录
    """
    try:
        success = DeviceEvaluationService.delete_evaluation(db, evaluation_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {evaluation_id} 的评估记录"
            )
        
        return {
            "code": 0,
            "message": "删除成功",
            "data": {}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除装置评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"删除装置评估失败: {str(e)}"
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


@router.get("/devices/search",
           summary="搜索装置",
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
            "code": 0,
            "message": "查询成功",
            "data": {
                "devices": page_devices,
                "pagination": {
                    "total": total,
                    "pages": pages,
                    "pageNo": page_no,
                    "pageSize": page_size
                }
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
    device_uri: Optional[str] = Query(None, description="装置URI（模糊匹配）"),
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
            "loop_count": len(result),
            "loop_list": result
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