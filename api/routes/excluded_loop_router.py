#!/usr/bin/env python3
"""
路由层 - 剔除回路API接口
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel import Session
from pydantic import BaseModel

from core.database.database import get_db
from api.services.excluded_loop_service import ExcludedLoopService
from api.bean.excluded_loop import ExcludedLoop
from api.middleware.exceptions import (
    BusinessException,
    ValidationException,
    DataProcessException,
    NotFoundException
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1")


# 请求体模型
class BatchExcludeRequest(BaseModel):
    """批量剔除请求"""
    uris: List[str]
    reason: Optional[str] = None


@router.post("/excluded-loop/add",
            summary="添加剔除回路",
            operation_id="add_excluded_loop",
            response_model=Dict[str, Any])
async def add_excluded_loop(
    uri: str = Query(..., description="回路/装置URI"),
    reason: Optional[str] = Query(None, description="剔除原因"),
    db: Session = Depends(get_db)
):
    """
    添加剔除回路记录
    
    - 如果URI已存在，则更新记录
    - 否则创建新记录
    """
    try:
        excluded = ExcludedLoopService.add_excluded(
            db, uri, reason
        )
        
        return {
            "code": 0,
            "message": "添加成功",
            "data": {
                "id": excluded.id,
                "uri": excluded.uri,
                "reason": excluded.reason,
                "created_time": excluded.created_time.isoformat() if excluded.created_time else None,
                "updated_time": excluded.updated_time.isoformat() if excluded.updated_time else None
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
            data={"uri": uri}
        )
    except Exception as e:
        logger.error(f"添加剔除回路失败 - URI: {uri}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"添加剔除回路失败: {str(e)}",
            data={"uri": uri}
        )


@router.post("/excluded-loop/remove",
            summary="移除剔除回路",
            operation_id="remove_excluded_loop",
            response_model=Dict[str, Any])
async def remove_excluded_loop(
    uri: str = Query(..., description="回路/装置URI"),
    db: Session = Depends(get_db)
):
    """
    移除剔除回路（删除记录）
    """
    try:
        success = ExcludedLoopService.remove_excluded(db, uri)
        
        if not success:
            raise NotFoundException(
                message=f"未找到URI为 {uri} 的剔除记录",
                data={"uri": uri}
            )
        
        return {
            "code": 0,
            "message": "移除成功",
            "data": {
                "uri": uri
            }
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"移除剔除回路失败 - URI: {uri}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"移除剔除回路失败: {str(e)}",
            data={"uri": uri}
        )


@router.get("/excluded-loop/check",
           summary="检查是否被剔除",
           operation_id="check_excluded_loop",
           response_model=Dict[str, Any])
async def check_excluded_loop(
    uri: str = Query(..., description="回路/装置URI"),
    db: Session = Depends(get_db)
):
    """
    检查URI是否被剔除回路
    """
    try:
        is_excluded = ExcludedLoopService.is_excluded(db, uri)
        excluded = ExcludedLoopService.get_excluded_by_uri(db, uri)
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "uri": uri,
                "is_excluded": is_excluded,
                "reason": excluded.reason if excluded else None
            }
        }
    except Exception as e:
        logger.error(f"检查剔除状态失败 - URI: {uri}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"检查剔除状态失败: {str(e)}",
            data={"uri": uri}
        )


@router.get("/excluded-loop/list",
           summary="分页查询剔除列表",
           operation_id="list_excluded_loops",
           response_model=Dict[str, Any])
async def list_excluded_loops(
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    device_uri: Optional[str] = Query(None, description="装置URI（模糊匹配loop_path路径）"),
    uri: Optional[str] = Query(None, description="回路URI（模糊匹配）"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    分页查询所有剔除回路记录
    
    支持的筛选条件：
    - loop_name: 回路名称模糊查询
    - device_uri: 装置URI筛选，模糊匹配回路的loop_path字段
    - uri: 回路URI模糊查询
    """
    try:
        result = ExcludedLoopService.list_excluded(
            db,
            loop_name=loop_name,
            device_uri=device_uri,
            uri=uri,
            page_no=page_no,
            page_size=page_size
        )
        
        excluded_loops = result["excluded_loops"]
        pagination = result["pagination"]
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "excluded_loops": [
                    {
                        "id": e["id"] if isinstance(e, dict) else e.id,
                        "uri": e["uri"] if isinstance(e, dict) else e.uri,
                        "loop_name": e.get("loop_name") if isinstance(e, dict) else None,
                        "reason": e["reason"] if isinstance(e, dict) else e.reason,
                        "created_time": e["created_time"].isoformat() if isinstance(e, dict) and e.get("created_time") else (e.created_time.isoformat() if hasattr(e, 'created_time') and e.created_time else None),
                        "updated_time": e["updated_time"].isoformat() if isinstance(e, dict) and e.get("updated_time") else (e.updated_time.isoformat() if hasattr(e, 'updated_time') and e.updated_time else None)
                    }
                    for e in excluded_loops
                ],
                "pagination": pagination
            }
        }
    except Exception as e:
        logger.error(f"查询剔除回路列表失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询剔除回路列表失败: {str(e)}",
            data={"uri": uri}
        )


@router.get("/excluded-loop/uris",
           summary="获取所有剔除URI列表",
           operation_id="get_all_excluded_uris",
           response_model=Dict[str, Any])
async def get_all_excluded_uris(
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    device_uri: Optional[str] = Query(None, description="装置URI（模糊匹配loop_path路径）"),
    uri: Optional[str] = Query(None, description="回路URI（模糊匹配）"),
    db: Session = Depends(get_db)
):
    """
    获取所有剔除回路URI列表（不分页）
    
    支持的筛选条件：
    - loop_name: 回路名称模糊查询
    - device_uri: 装置URI筛选，模糊匹配回路的loop_path字段
    - uri: 回路URI模糊查询
    
    返回所有被剔除的回路URI，用于快速判断和过滤
    """
    try:
        uris = ExcludedLoopService.get_all_excluded_uris(
            db,
            loop_name=loop_name,
            device_uri=device_uri,
            uri=uri
        )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "uris": uris,
                "total": len(uris)
            }
        }
    except Exception as e:
        logger.error(f"获取剔除URI列表失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"获取剔除URI列表失败: {str(e)}"
        )


@router.get("/excluded-loop/{excluded_id}",
           summary="根据ID查询剔除记录",
           operation_id="get_excluded_loop_by_id",
           response_model=Dict[str, Any])
async def get_excluded_loop_by_id(
    excluded_id: int,
    db: Session = Depends(get_db)
):
    """
    根据ID查询剔除回路记录
    """
    try:
        excluded = ExcludedLoopService.get_excluded_by_id(db, excluded_id)
        
        if not excluded:
            raise NotFoundException(
                message=f"未找到ID为 {excluded_id} 的剔除记录",
                data={"excluded_id": excluded_id}
            )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": {
                "id": excluded.id,
                "uri": excluded.uri,
                "reason": excluded.reason,
                "created_time": excluded.created_time.isoformat() if excluded.created_time else None,
                "updated_time": excluded.updated_time.isoformat() if excluded.updated_time else None
            }
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询剔除回路失败 - ID: {excluded_id}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询剔除回路失败: {str(e)}",
            data={"excluded_id": excluded_id}
        )


@router.put("/excluded-loop/{excluded_id}",
           summary="更新剔除记录",
           operation_id="update_excluded_loop",
           response_model=Dict[str, Any])
async def update_excluded_loop(
    excluded_id: int,
    uri: Optional[str] = Query(None, description="新的URI"),
    reason: Optional[str] = Query(None, description="新的剔除原因"),
    db: Session = Depends(get_db)
):
    """
    更新剔除回路记录
    """
    try:
        excluded = ExcludedLoopService.update_excluded(
            db, excluded_id, uri, reason
        )
        
        if not excluded:
            raise NotFoundException(
                message=f"未找到ID为 {excluded_id} 的剔除记录",
                data={"excluded_id": excluded_id}
            )
        
        return {
            "code": 0,
            "message": "更新成功",
            "data": {
                "id": excluded.id,
                "uri": excluded.uri,
                "reason": excluded.reason,
                "updated_time": excluded.updated_time.isoformat() if excluded.updated_time else None
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
            data={"excluded_id": excluded_id}
        )
    except Exception as e:
        logger.error(f"更新剔除回路失败 - ID: {excluded_id}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"更新剔除回路失败: {str(e)}",
            data={"excluded_id": excluded_id}
        )


@router.delete("/excluded-loop/{excluded_id}",
              summary="删除剔除记录",
              operation_id="delete_excluded_loop",
              response_model=Dict[str, Any])
async def delete_excluded_loop(
    excluded_id: int,
    db: Session = Depends(get_db)
):
    """
    删除剔除回路记录
    """
    try:
        success = ExcludedLoopService.delete_excluded(db, excluded_id)
        
        if not success:
            raise NotFoundException(
                message=f"未找到ID为 {excluded_id} 的剔除记录",
                data={"excluded_id": excluded_id}
            )
        
        return {
            "code": 0,
            "message": "删除成功",
            "data": {"excluded_id": excluded_id}
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除剔除回路失败 - ID: {excluded_id}: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"删除剔除回路失败: {str(e)}",
            data={"excluded_id": excluded_id}
        )


@router.post("/excluded-loop/batch-add",
            summary="批量添加剔除回路",
            operation_id="batch_add_excluded_loops",
            response_model=Dict[str, Any])
async def batch_add_excluded_loops(
    request: BatchExcludeRequest = Body(..., description="批量剔除请求"),
    db: Session = Depends(get_db)
):
    """
    批量添加剔除回路记录
    
    请求体示例：
    ```json
    {
        "uris": ["/pid_zd/loop1", "/pid_zd/loop2"],
        "reason": "数据质量差"
    }
    ```
    """
    try:
        if not request.uris:
            raise ValidationException(
                message="URI列表不能为空",
                data={"uris": request.uris}
            )
        
        result = ExcludedLoopService.batch_add_excluded(
            db, request.uris, request.reason
        )
        
        return {
            "code": 0,
            "message": "批量添加完成",
            "data": result
        }
    except BusinessException:
        raise
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"参数验证失败: {str(e)}", exc_info=True)
        raise ValidationException(
            message=f"参数验证失败: {str(e)}",
            data={"uris": request.uris}
        )
    except Exception as e:
        logger.error(f"批量添加剔除回路失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"批量添加剔除回路失败: {str(e)}",
            data={"uri_count": len(request.uris) if request.uris else 0}
        )


@router.post("/excluded-loop/batch-remove",
            summary="批量移除剔除回路",
            operation_id="batch_remove_excluded_loops",
            response_model=Dict[str, Any])
async def batch_remove_excluded_loops(
    uris: List[str] = Body(..., description="URI列表"),
    db: Session = Depends(get_db)
):
    """
    批量移除剔除回路
    
    请求体示例：
    ```json
    ["/pid_zd/loop1", "/pid_zd/loop2"]
    ```
    """
    try:
        if not uris:
            raise ValidationException(
                message="URI列表不能为空",
                data={"uris": uris}
            )
        
        result = ExcludedLoopService.batch_remove_excluded(db, uris)
        
        return {
            "code": 0,
            "message": "批量移除完成",
            "data": result
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
        logger.error(f"批量移除剔除回路失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"批量移除剔除回路失败: {str(e)}",
            data={"uri_count": len(uris) if uris else 0}
        )
