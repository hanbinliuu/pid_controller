#!/usr/bin/env python3
"""
路由层 - 回路评估API接口
"""
import logging
from typing import Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.database.database import get_db
from api.services.loop_evaluation_service import LoopEvaluationService
from api.bean.loop_evaluation import LoopEvaluation

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1")


@router.get("/loop-evaluation/list",
           summary="分页查询评估列表",
           operation_id="list_loop_evaluations",
           response_model=Dict[str, Any])
async def list_loop_evaluations(
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    loop_uri: Optional[str] = Query(None, description="回路URI（模糊匹配）"),
    start_time: Optional[str] = Query(None, description="开始时间(YYYY-MM-DD)"),
    end_time: Optional[str] = Query(None, description="结束时间(YYYY-MM-DD)"),
    min_performance_score: Optional[float] = Query(None, description="最小性能评分"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    分页查询所有回路评估记录
    """
    try:
        result = LoopEvaluationService.list_evaluations(
            db,
            loop_name=loop_name,
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time,
            min_performance_score=min_performance_score,
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
                        "loop_uri": e.loop_uri,
                        "loop_name": e.loop_name,
                        "assessment_time": e.assessment_time.isoformat() if e.assessment_time else None,
                        "performance_score": e.performance_score,
                        "status": e.status,
                        "auto_control_rate": e.auto_control_rate,
                        "stability_rate": e.stability_rate,
                        "auto_control_time": e.auto_control_time,
                        "stable_time": e.stable_time,
                        "total_time": e.total_time,
                        "created_time": e.created_time.isoformat() if e.created_time else None,
                        "updated_time": e.updated_time.isoformat() if e.updated_time else None
                    }
                    for e in evaluations
                ],
                "pagination": pagination
            }
        }
    except Exception as e:
        logger.error(f"查询回路评估列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估列表失败: {str(e)}"
        )




@router.get("/loop-evaluation/statistics",
           summary="获取评估统计信息",
           operation_id="get_loop_evaluation_statistics",
           response_model=Dict[str, Any])
async def get_loop_evaluation_statistics(
    db: Session = Depends(get_db)
):
    """
    获取回路评估统计信息
    """
    try:
        stats = LoopEvaluationService.get_statistics(db)
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": stats
        }
    except Exception as e:
        logger.error(f"获取评估统计信息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取评估统计信息失败: {str(e)}"
        )
@router.get("/loop-evaluation/by-uri",
            summary="根据回路URI查询评估历史",
            operation_id="get_loop_evaluation_by_uri",
            response_model=Dict[str, Any])
async def get_loop_evaluation_by_uri(
        loop_uri: Optional[str] = Query(None, description="回路URI"),
        limit: int = Query(10, description="返回记录数量", ge=1, le=100),
        db: Session = Depends(get_db)
):
    """
    根据回路URI查询历史评估记录
    """
    try:
        evaluations = LoopEvaluationService.get_evaluations_by_loop_uri(
            db, loop_uri, limit
        )

        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "evaluations": [
                    {
                        "id": e.id,
                        "loop_uri": e.loop_uri,
                        "loop_name": e.loop_name,
                        "assessment_time": e.assessment_time.isoformat() if e.assessment_time else None,
                        "performance_score": e.performance_score,
                        "auto_control_rate": e.auto_control_rate,
                        "stability_rate": e.stability_rate,
                        "created_time": e.created_time.isoformat() if e.created_time else None
                    }
                    for e in evaluations
                ],
                "total": len(evaluations)
            }
        }
    except Exception as e:
        logger.error(f"查询回路评估历史失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估历史失败: {str(e)}"
        )

@router.get("/loop-evaluation/{evaluation_id}",
            summary="根据ID查询评估",
            operation_id="get_loop_evaluation_by_id",
            response_model=Dict[str, Any])
async def get_loop_evaluation_by_id(
        evaluation_id: int,
        db: Session = Depends(get_db)
):
    """
    根据ID查询回路评估记录
    """
    try:
        evaluation = LoopEvaluationService.get_evaluation_by_id(db, evaluation_id)

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
                "loop_uri": evaluation.loop_uri,
                "loop_name": evaluation.loop_name,
                "description": evaluation.description,
                "assessment_time": evaluation.assessment_time.isoformat() if evaluation.assessment_time else None,
                "operator": evaluation.operator,
                "before_params": evaluation.before_params,
                "after_params": evaluation.after_params,
                "status": evaluation.status,
                "remark": evaluation.remark,
                "tuning_details": evaluation.tuning_details,
                "performance_score": evaluation.performance_score,
                "auto_control_rate": evaluation.auto_control_rate,
                "stability_rate": evaluation.stability_rate,
                "auto_control_time": evaluation.auto_control_time,
                "stable_time": evaluation.stable_time,
                "total_time": evaluation.total_time,
                "pt_count": evaluation.pt_count,
                "pv_sum_value": evaluation.pv_sum_value,
                "pv_sum_squares": evaluation.pv_sum_squares,
                "mv_sum_value": evaluation.mv_sum_value,
                "mv_sum_squares": evaluation.mv_sum_squares,
                "created_time": evaluation.created_time.isoformat() if evaluation.created_time else None,
                "updated_time": evaluation.updated_time.isoformat() if evaluation.updated_time else None
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询回路评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估失败: {str(e)}"
        )
@router.delete("/loop-evaluation/{evaluation_id}",
               summary="删除评估记录",
               operation_id="delete_loop_evaluation",
               response_model=Dict[str, Any])
async def delete_loop_evaluation(
        evaluation_id: int,
        db: Session = Depends(get_db)
):
    """
    删除回路评估记录
    """
    try:
        success = LoopEvaluationService.delete_evaluation(db, evaluation_id)

        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {evaluation_id} 的评估记录"
            )

        return {
            "code": 0,
            "message": "删除成功",
            "data": {"evaluation_id": evaluation_id}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除回路评估失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"删除回路评估失败: {str(e)}"
        )
