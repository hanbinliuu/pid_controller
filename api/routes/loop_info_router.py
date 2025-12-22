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
from api.response.loop_info_response import LoopInfoResponse, UpdateLoopInfoResponse

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1")

@router.get("/loop-info/by-uri",
           summary="根据loop_uri查询信息",
           operation_id="根据loop_uri查询回路信息",
           response_model=LoopInfoResponse)
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
        
            # 将LoopInfo对象转换为LoopInfoResponse Bean
        return LoopInfoResponse(
            id=mapping.id,
            loop_uri=mapping.loop_uri,
            loop_path=mapping.loop_path,
            loop_name=mapping.loop_name,
            loop_type=mapping.loop_type,
            description=mapping.description,
            point_path=mapping.point_path,
            pv_field=mapping.pv_field,
            sv_field=mapping.sv_field,
            mv_field=mapping.mv_field,
            auto_status_field=mapping.auto_status_field,
            pb_field=mapping.pb_field,
            ti_field=mapping.ti_field,
            td_field=mapping.td_field,
            is_active=mapping.is_active,
            created_time=mapping.created_time.isoformat() if mapping.created_time else None,
            updated_time=mapping.updated_time.isoformat() if mapping.updated_time else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询回路信息失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息失败: {str(e)}"
        )


@router.get("/loop-info/by-path",
           summary="根据loop_path查询回路信息",
           operation_id="根据loop_path回路信息",
           response_model=List[LoopInfoResponse])
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
        
        # 将LoopInfo对象列表转换为LoopInfoResponse Bean列表
        return [
            LoopInfoResponse(
                id=m.id,
                loop_uri=m.loop_uri,
                loop_path=m.loop_path,
                loop_name=m.loop_name,
                loop_type=m.loop_type,
                description=m.description,
                point_path=m.point_path,
                pv_field=m.pv_field,
                sv_field=m.sv_field,
                mv_field=m.mv_field,
                auto_status_field=m.auto_status_field,
                pb_field=m.pb_field,
                ti_field=m.ti_field,
                td_field=m.td_field,
                is_active=m.is_active,
                created_time=m.created_time.isoformat() if m.created_time else None,
                updated_time=m.updated_time.isoformat() if m.updated_time else None
            )
            for m in mapping
        ]
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
           operation_id="分页查询回路列表",
           response_model=Dict[str, Any])
async def list_loop_info(
    db: Session = Depends(get_db),
    loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
    loop_uri: Optional[str] = Query(None, description="回路URI"),
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
        
        return  result
    except Exception as e:
        logger.error(f"查询回路信息列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息列表失败: {str(e)}"
        )


@router.get("/loop-info/list-exclude-excluded",
          summary="分页查询回路列表(排除已剔除)",
          operation_id="分页查询非剔除回路列表",
          response_model=Dict[str, Any])
async def list_loop_info_exclude_excluded(
        db: Session = Depends(get_db),
        loop_name: Optional[str] = Query(None, description="回路名称（模糊匹配）"),
        device_uri: Optional[str] = Query(None, description="设备URI"),
        loop_uri: Optional[str] = Query(None, description="回路URI"),
        loop_type: Optional[str] = Query(None, description="回路类型"),
        page_no: int = Query(1, description="页码，从1开始"),
        page_size: int = Query(10, description="每页数量")
) -> Dict[str, Any]:
    """
    分页查询所有回路信息记录
    """
    try:
        result = LoopInfoService.list_mappings_exclude_excluded(
            db,
            loop_name=loop_name,
            loop_uri=loop_uri,
            device_uri=device_uri,
            loop_type=loop_type,
            page_no=page_no,
            page_size=page_size
        )

        return result
    except Exception as e:
        logger.error(f"查询回路信息列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路信息列表失败: {str(e)}"
        )
