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


@router.get("/loop-evaluation/now/page",
            summary="分页查询装置下当天回路评估列表",
            operation_id="分页查询装置下当天回路评估列表",
            response_model=Dict[str, Any])
async def list_loop_evaluations_now(
        loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
        device_uri: Optional[str] = Query(None, description="装置uri"),
        loop_uri: Optional[str] = Query(None, description="回路uri"),
        loop_type: Optional[str] = Query(None, description="回路类型"),
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
            device_uri=device_uri,
            loop_uri=loop_uri,
            loop_type=loop_type,
            start_time=str(date.today()),
            end_time=str(date.today()),
            min_performance_score=None,
            page_no=page_no,
            page_size=page_size
        )

        return result
    except Exception as e:
        logger.error(f"查询回路评估列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估列表失败: {str(e)}"
        )
@router.get("/loop-evaluation/page",
           summary="分页查询装置下历史回路评估列表",
           operation_id="分页查询装置下历史回路评估列表",
           response_model=Dict[str, Any])
async def list_loop_evaluations(
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    device_uri: Optional[str] = Query(None, description="装置uri"),
    loop_uri: Optional[str] = Query(None, description="回路uri"),
    loop_type: Optional[str] = Query(None, description="回路类型"),
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
            device_uri=device_uri,
            loop_uri=loop_uri,
            loop_type=loop_type,
            start_time=start_time,
            end_time=end_time,
            min_performance_score=min_performance_score,
            page_no=page_no,
            page_size=page_size
        )
        return result
    except Exception as e:
        logger.error(f"查询回路评估列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估列表失败: {str(e)}"
        )

@router.get("/loop-evaluation/by-uri",
            summary="根据回路URI查询评估历史",
            operation_id="根据回路URI查询评估历史",
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
    except Exception as e:
        logger.error(f"查询回路评估历史失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路评估历史失败: {str(e)}"
        )
