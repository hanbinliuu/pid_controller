#!/usr/bin/env python3
"""
路由层 - 回路信息API接口
"""
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from core.database.database import get_db
from api.services.loop_info_service import LoopInfoService
from api.bean.loop_info import LoopInfo

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1")


# @router.post("/loop-info",
#             summary="创建回路信息",
#             operation_id="create_loop_info",
#             response_model=Dict[str, Any])
# async def create_loop_info(
#     loop_uri: str = Query(..., description="回路 URI"),
#     loop_path: Optional[str] = Query(None, description="PID相关参数的相对路径"),
#     loop_name: Optional[str] = Query(None, description="回路名称"),
#     pv_field: Optional[str] = Query(None, description="PV字段名"),
#     sv_field: Optional[str] = Query(None, description="SV字段名"),
#     mv_field: Optional[str] = Query(None, description="MV字段名"),
#     auto_status_field: Optional[str] = Query(None, description="自动状态字段名"),
#     pb_field: Optional[str] = Query(None, description="PB(比例带)字段名"),
#     ti_field: Optional[str] = Query(None, description="TI(积分时间常数)字段名"),
#     td_field: Optional[str] = Query(None, description="TD(微分时间常数)字段名"),
#     description: Optional[str] = Query(None, description="描述"),
#     db: Session = Depends(get_db)
# ):
#     """
#     创建回路信息记录
#
#     创建成功时返回创建的信息对象
#     """
#     try:
#         mapping = LoopInfoService.create_mapping(
#             db,
#             loop_uri=loop_uri,
#             loop_path=loop_path,
#             loop_name=loop_name,
#             pv_field=pv_field,
#             sv_field=sv_field,
#             mv_field=mv_field,
#             auto_status_field=auto_status_field,
#             pb_field=pb_field,
#             ti_field=ti_field,
#             td_field=td_field,
#             description=description
#         )
#
#         return {
#             "code": 0,
#             "message": "创建成功",
#             "data": {
#                 "id": mapping.id,
#                 "loop_uri": mapping.loop_uri,
#                 "loop_path": mapping.loop_path,
#                 "loop_name": mapping.loop_name,
#                 "created_time": mapping.created_time.isoformat()
#             }
#         }
#     except Exception as e:
#         logger.error(f"创建回路信息失败: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"创建回路信息失败: {str(e)}"
#         )


@router.get("/loop-info/by-uri",
           summary="根据loop_uri查询信息",
           operation_id="get_info_by_uri",
           response_model=Dict[str, Any])
async def get_info_by_uri(
    loop_uri: str = Query(..., description="回路URI"),
    db: Session = Depends(get_db)
):
    """
    根据回路URI查询其对应的信息记录
    """
    try:
        mapping = LoopInfoService.get_mapping_by_uri(db, loop_uri)
        
        if not mapping:
            raise HTTPException(
                status_code=404,
                detail=f"未找到loop_uri为 {loop_uri} 的信息记录"
            )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": mapping
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询回路信息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息失败: {str(e)}"
        )


@router.get("/loop-info/by-path",
           summary="根据loop_path查询信息",
           operation_id="get_info_by_path",
           response_model=Dict[str, Any])
async def get_info_by_path(
    loop_path: str = Query(..., description="回路路径"),
    db: Session = Depends(get_db)
):
    """
    根据回路路径查询其对应的信息记录
    """
    try:
        mapping = LoopInfoService.get_mapping_by_path(db, loop_path)
        
        if not mapping:
            raise HTTPException(
                status_code=404,
                detail=f"未找到loop_path为 {loop_path} 的信息记录"
            )
        
        return {
            "code": 0,
            "message": "查询成功",
            "data": mapping
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询回路信息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息失败: {str(e)}"
        )


@router.get("/loop-info/list",
           summary="分页查询回路列表",
           operation_id="list_loop_info",
           response_model=Dict[str, Any])
async def list_loop_info(
    db: Session = Depends(get_db),
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    loop_uri: Optional[str] = Query(None, description="回路URI（模糊匹配）"),
    loop_path: Optional[str] = Query(None, description="回路路径（模糊匹配）"),
    loop_type: Optional[str] = Query(None, description="回路类型"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量")
)-> Dict[str, Any]:
    """
    分页查询所有回路信息记录
    """
    try:
        result = LoopInfoService.list_mappings(
            db,
            loop_name=loop_name,
            loop_uri=loop_uri,
            loop_path=loop_path,
            loop_type=loop_type,
            page_no=page_no,
            page_size=page_size
        )
        
        mappings = result["mappings"]
        pagination = result["pagination"]
        
        return  result
    except Exception as e:
        logger.error(f"查询回路信息列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息列表失败: {str(e)}"
        )


@router.put("/loop-info",
           summary="更新回路信息",
           operation_id="update_loop_info",
           response_model=Dict[str, Any])
async def update_loop_info(
    loop_uri: str = Query(..., description="回路 URI"),
    loop_path: Optional[str] = Query(None, description="新的PID相关参数相对路径"),
    loop_name: Optional[str] = Query(None, description="新的回路名称"),
    pv_field: Optional[str] = Query(None, description="新的PV字段名"),
    sv_field: Optional[str] = Query(None, description="新的SV字段名"),
    mv_field: Optional[str] = Query(None, description="新的MV字段名"),
    auto_status_field: Optional[str] = Query(None, description="新的自动状态字段名"),
    pb_field: Optional[str] = Query(None, description="新的PB(比例带)字段名"),
    ti_field: Optional[str] = Query(None, description="新的TI(积分时间常数)字段名"),
    td_field: Optional[str] = Query(None, description="新的TD(微分时间常数)字段名"),
    description: Optional[str] = Query(None, description="新的描述"),
    db: Session = Depends(get_db)
):
    """
    更新回路信息记录
    """
    try:
        mapping = LoopInfoService.update_mapping(
            db,
            loop_uri=loop_uri,
            loop_path=loop_path,
            loop_name=loop_name,
            pv_field=pv_field,
            sv_field=sv_field,
            mv_field=mv_field,
            auto_status_field=auto_status_field,
            pb_field=pb_field,
            ti_field=ti_field,
            td_field=td_field,
            description=description
        )
        
        if not mapping:
            raise HTTPException(
                status_code=404,
                detail=f"未找到loop_uri为 {loop_uri} 的信息记录"
            )
        
        return {
                "id": mapping.id,
                "loop_uri": mapping.loop_uri,
                "loop_path": mapping.loop_path,
                "loop_name": mapping.loop_name,
                "updated_time": mapping.updated_time.isoformat()
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新回路信息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"更新回路信息失败: {str(e)}"
        )
