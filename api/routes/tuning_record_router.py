#!/usr/bin/env python3
"""
整定记录管理路由 - 使用SQLModel
用于保存和查询PID整定记录
"""

import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends
from sqlmodel import Session

from core.database.database import get_db
from api.services.tuning_record_service import TuningRecordService
from api.bean.tuning_record import TuningRecord

router = APIRouter()
logger = logging.getLogger(__name__)


# SQLModel已在models.py中定义TuningRecord，可直接用作请求和响应模型


@router.post(
    "/",
    summary="创建整定记录",
    operation_id="创建整定记录",
    description="保存常规整定或大模型整定的参数结果",
    response_model=TuningRecord
)
async def create_tuning_record(
    loop_uri: str,
    loop_name: str,
    tuning_method: str,
    operator: str,
    before_params: str,
    after_params: str,
    operator_id: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "成功",
    remark: Optional[str] = None,
    tuning_details: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db)
) -> TuningRecord:
    """
    创建整定记录 - SQLModel优化版本
    
    功能说明：
    - 保存整定操作的详细信息
    - 记录整定前后的参数对比
    - 支持常规整定和大模型整定两种方式
    - 使用SQLModel自动验证和序列化
    
    返回格式：直接返回TuningRecord对象（自动序列化为JSON）
    """
    try:
        # 调用Service层创建记录
        record = TuningRecordService.create_record(
            db=db,
            loop_uri=loop_uri,
            loop_name=loop_name,
            tuning_method=tuning_method,
            operator=operator,
            operator_id=operator_id,
            before_params=before_params,
            after_params=after_params,
            description=description,
            status=status,
            remark=remark,
            tuning_details=tuning_details
        )
        
        return record
    
    except Exception as e:
        logger.error(f"创建整定记录失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"创建整定记录失败: {str(e)}"
        )


@router.get(
    "/",
    summary="查询整定记录列表",
    operation_id="查询整定记录列表",
    description="查询整定记录列表，支持筛选和分页"
)
async def query_tuning_records(
    loop_name: Optional[str] = Query(
        None,
        description="回路名称筛选",
        example="流量单回路实例_1"
    ),
    tuning_method: Optional[str] = Query(
        None,
        description="整定方法筛选（全部/常规整定/大模型整定/AI优化/仿真整定）",
        example="常规整定"
    ),
    start_time: Optional[str] = Query(
        None,
        description="开始时间",
        example="2025-01-01"
    ),
    end_time: Optional[str] = Query(
        None,
        description="结束时间",
        example="2025-12-31"
    ),
    page_no: int = Query(
        1,
        description="页码",
        ge=1
    ),
    page_size: int = Query(
        10,
        description="每页数量",
        ge=1,
        le=100
    ),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    查询整定记录列表
    
    功能说明：
    - 查询所有整定记录
    - 支持按回路名称、整定方法、时间范围筛选
    - 支持分页查询
    
    返回格式：
    {
        "records": [
            {
                "sequence": 1,
                "loop_name": "LIC-401",
                "description": "T801流位控制",
                "tuning_method": "常规整定",
                "tuning_time": "2025-01-15 14:38:25",
                "operator": "张三",
                "before_params": "68.00/800.00/5.00",
                "after_params": "46.97/160.00/0.00",
                "status": "成功",
                "remark": "参数已落地CS"
            }
        ],
        "pagination": {
            "total": 5,
            "pages": 1,
            "pageNo": 1,
            "pageSize": 10
        }
    }
    """
    try:
        # 调用Service层查询
        result = TuningRecordService.query_records(
            db=db,
            loop_name=loop_name,
            tuning_method=tuning_method,
            start_time=start_time,
            end_time=end_time,
            page_no=page_no,
            page_size=page_size
        )
        
        return result
    
    except Exception as e:
        logger.error(f"查询整定记录失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询整定记录失败: {str(e)}"
        )


@router.get(
    "/{record_id}",
    summary="查询整定记录详情",
    operation_id="查询整定记录详情",
    description="根据ID查询整定记录的详细信息",
    response_model=TuningRecord
)
async def get_tuning_record(
    record_id: int,
    db: Session = Depends(get_db)
) -> TuningRecord:
    """
    查询整定记录详情
    
    功能说明：
    - 根据记录ID查询详细信息
    - 包含完整的整定过程数据
    
    返回格式：
    {
        "id": 1,
        "loop_name": "LIC-401",
        "tuning_method": "常规整定",
        "tuning_details": { ... },
        ...
    }
    """
    try:
        # 调用Service层查询
        record = TuningRecordService.get_record_by_id(db, record_id)
        
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {record_id} 的整定记录"
            )
        
        return record
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询整定记录详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询整定记录详情失败: {str(e)}"
        )


# @router.delete(
#     "/{record_id}",
#     summary="删除整定记录",
#     operation_id="删除整定记录",
#     description="根据ID删除整定记录"
# )
# async def delete_tuning_record(
#     record_id: int,
#     db: Session = Depends(get_db)
# ) -> Dict[str, Any]:
#     """
#     删除整定记录
#
#     功能说明：
#     - 根据记录ID删除记录
#
#     返回格式：
#     {
#         "message": "整定记录删除成功",
#         "id": 1
#     }
#     """
#     try:
#         # 调用Service层删除
#         success = TuningRecordService.delete_record(db, record_id)
#
#         if not success:
#             raise HTTPException(
#                 status_code=404,
#                 detail=f"未找到ID为 {record_id} 的整定记录"
#             )
#
#         return {
#             "message": "整定记录删除成功",
#             "id": record_id
#         }
#
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"删除整定记录失败: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"删除整定记录失败: {str(e)}"
#         )
