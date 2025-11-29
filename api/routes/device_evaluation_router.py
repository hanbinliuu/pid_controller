#!/usr/bin/env python3
"""
路由层 - 装置评估API接口
"""
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.database.database import get_db
from api.services.device_evaluation_service import DeviceEvaluationService
from api.bean.device_evaluation import DeviceEvaluation

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1", tags=["装置评估"])


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