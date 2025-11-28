#!/usr/bin/env python3
"""
定时任务管理API路由
"""
import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Query

from api.tasks.cron_tasks import task_manager, CronTask

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/register-cron-task",
    summary="注册定时任务",
    operation_id="注册定时任务",
    description="注册一个新的基于Cron表达式的定时任务"
)
async def register_cron_task(
    task_id: str = Query(..., description="任务ID"),
    cron_expression: str = Query(..., description="Cron表达式 (分 小时 天 月 周)", example="0 * * * *"),
    auto_start: bool = Query(True, description="注册后是否自动启动")
) -> Dict[str, Any]:
    """
    注册定时任务
    
    Cron表达式示例：
    - '0 * * * *'      : 每小时的第0分钟
    - '0 0 * * *'      : 每天的00:00
    - '0 2 * * *'      : 每天的02:00
    - '*/30 * * * *'    : 每30分钟
    - '0 0,12 * * *'    : 每天的00:00和12:00
    - '0 0 * * 0'       : 每周日的00:00
    """
    try:
        # 定义任务函数
        from api.tasks import calculate_loop_performance
        
        success = task_manager.register_task(
            task_id=task_id,
            cron_expression=cron_expression,
            task_func=calculate_loop_performance,
            task_args={'max_workers': 5}
        )
        
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"任务注册失败，可能是Cron表达式无效或任务已存在"
            )
        
        # 如果需要自动启动
        if auto_start:
            task_manager.start_task(task_id)
        
        return {
            "status": "success",
            "data": {
                "task_id": task_id,
                "cron_expression": cron_expression,
                "is_running": auto_start,
                "message": f"任务已注册{'并启动' if auto_start else ''}"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注册定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"注册失败: {str(e)}"
        )


@router.post(
    "/start-cron-task",
    summary="启动定时任务",
    operation_id="启动定时任务",
    description="启动指定的定时任务"
)
async def start_cron_task(
    task_id: str = Query(..., description="任务ID")
) -> Dict[str, Any]:
    """启动定时任务"""
    try:
        success = task_manager.start_task(task_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"任务不存在或已在运行"
            )
        
        return {
            "status": "success",
            "data": {
                "task_id": task_id,
                "is_running": True,
                "message": "任务已启动"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"启动定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"启动失败: {str(e)}"
        )


@router.post(
    "/stop-cron-task",
    summary="停止定时任务",
    operation_id="停止定时任务",
    description="停止指定的定时任务"
)
async def stop_cron_task(
    task_id: str = Query(..., description="任务ID")
) -> Dict[str, Any]:
    """停止定时任务"""
    try:
        success = task_manager.stop_task(task_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"任务不存在或未在运行"
            )
        
        return {
            "status": "success",
            "data": {
                "task_id": task_id,
                "is_running": False,
                "message": "任务已停止"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"停止定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"停止失败: {str(e)}"
        )


@router.delete(
    "/unregister-cron-task",
    summary="注销定时任务",
    operation_id="注销定时任务",
    description="删除指定的定时任务"
)
async def unregister_cron_task(
    task_id: str = Query(..., description="任务ID")
) -> Dict[str, Any]:
    """注销定时任务"""
    try:
        success = task_manager.unregister_task(task_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"任务不存在"
            )
        
        return {
            "status": "success",
            "data": {
                "task_id": task_id,
                "message": "任务已删除"
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"注销定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"注销失败: {str(e)}"
        )


@router.get(
    "/cron-task-status",
    summary="查询定时任务状态",
    operation_id="查询定时任务状态",
    description="查询定时任务的状态信息"
)
async def get_cron_task_status(
    task_id: Optional[str] = Query(None, description="任务ID，为空则查询所有任务")
) -> Dict[str, Any]:
    """查询定时任务状态"""
    try:
        if task_id:
            status = task_manager.get_task_status(task_id)
            if status is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"任务不存在"
                )
            
            return {
                "status": "success",
                "data": status
            }
        else:
            all_status = task_manager.get_all_status()
            return {
                "status": "success",
                "data": {
                    "total_tasks": len(all_status),
                    "tasks": all_status
                }
            }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询定时任务状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询失败: {str(e)}"
        )


@router.get(
    "/cron-task-result",
    summary="获取任务执行结果",
    operation_id="获取任务执行结果",
    description="获取定时任务的最后执行结果"
)
async def get_cron_task_result(
    task_id: str = Query(..., description="任务ID")
) -> Dict[str, Any]:
    """获取任务执行结果"""
    try:
        result = task_manager.get_last_result(task_id)
        
        if result is None:
            status = task_manager.get_task_status(task_id)
            if status is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"任务不存在"
                )
            
            if status['execution_count'] == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"任务尚未执行过"
                )
            
            raise HTTPException(
                status_code=500,
                detail=f"无法获取任务执行结果"
            )
        
        return {
            "status": "success",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取任务执行结果失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"获取失败: {str(e)}"
        )


@router.post(
    "/start-all-cron-tasks",
    summary="启动所有定时任务",
    operation_id="启动所有定时任务"
)
async def start_all_cron_tasks() -> Dict[str, Any]:
    """启动所有定时任务"""
    try:
        count = task_manager.start_all()
        total = len(task_manager.tasks)
        
        return {
            "status": "success",
            "data": {
                "started_count": count,
                "total_count": total,
                "message": f"已启动 {count}/{total} 个任务"
            }
        }
        
    except Exception as e:
        logger.error(f"启动所有定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"启动失败: {str(e)}"
        )


@router.post(
    "/stop-all-cron-tasks",
    summary="停止所有定时任务",
    operation_id="停止所有定时任务"
)
async def stop_all_cron_tasks() -> Dict[str, Any]:
    """停止所有定时任务"""
    try:
        count = task_manager.stop_all()
        total = len(task_manager.tasks)
        
        return {
            "status": "success",
            "data": {
                "stopped_count": count,
                "total_count": total,
                "message": f"已停止 {count}/{total} 个任务"
            }
        }
        
    except Exception as e:
        logger.error(f"停止所有定时任务失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"停止失败: {str(e)}"
        )
