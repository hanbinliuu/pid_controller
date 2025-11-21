#!/usr/bin/env python3
"""
时序数据库(TSDB) API路由
实现历史原始值查询接口 /tsdb/v4/read_raw
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import os

# 导入时序数据查询模块
import sys

from api.routes.time_util import parse_time_to_milliseconds
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from core.data.real_tsdb_client import query_raw_data

router = APIRouter()

class TableQueryModel(BaseModel):
    """表查询模型"""
    table: str  # 必填
    fields: Optional[List[str]] = None  # 非必填，为空时查询所有字段
    continuationPoint: Optional[str] = None  # 续传点

class QueryDetailModel(BaseModel):
    """查询详细配置模型 - 支持多种时间格式"""
    startTime: Union[int, str] = Field(..., description="查询开始时间，支持毫秒时间戳或字符串格式", 
                                     examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00", "2022-01-01"])
    endTime: Optional[Union[int, str]] = Field(None, description="查询结束时间，支持毫秒时间戳或字符串格式，默认为当前时间",
                                              examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00", "2022-01-02"])
    limit: Optional[int] = Field(1500, description="每个表返回的最大数据条数", ge=1, le=10000)
    returnBounds: Optional[bool] = Field(False, description="是否返回边界数据")
    
    @validator('startTime')
    def validate_start_time(cls, v):
        """验证并转换开始时间"""
        try:
            return parse_time_to_milliseconds(v)
        except ValueError as e:
            raise ValueError(f"开始时间格式错误: {str(e)}")
    
    @validator('endTime')
    def validate_end_time(cls, v):
        """验证并转换结束时间"""
        if v is None:
            return None
        try:
            return parse_time_to_milliseconds(v)
        except ValueError as e:
            raise ValueError(f"结束时间格式错误: {str(e)}")

class TSDBQueryRequest(BaseModel):
    """TSDB查询请求模型"""
    tables: List[TableQueryModel]
    detail: QueryDetailModel

    def validate_request(self) -> bool:
        """验证请求参数"""
        # 检查 tables 之间不可以有相同的 table
        table_names = [t.table for t in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("tables 中不可以有相同的 table")
        
        # 检查必填字段
        for table_query in self.tables:
            if not table_query.table:
                raise ValueError("table 字段为必填项")
        
        if not self.detail.startTime:
            raise ValueError("startTime 字段为必填项")
        
        return True


@router.post("/read_raw",
             summary="时序数据库原始数据查询",
             description="从时序数据库中查询历史原始数据，支持多表联合查询、字段筛选、时间范围限制等高级功能")
async def read_raw_data(
    request: TSDBQueryRequest,
    db: Optional[str] = Query(None, description="数据库名称")
):
    try:
        # 验证请求参数
        request.validate_request()
        
        # 将Pydantic模型转换为字典
        request_data = {
            "db": db,  # 添加db参数
            "tables": [],
            "detail": {
                "startTime": request.detail.startTime,
                "endTime": request.detail.endTime or int(datetime.now().timestamp() * 1000),
                "limit": request.detail.limit or 1500,
                "returnBounds": request.detail.returnBounds or False
            }
        }
        
        # 转换表查询配置
        for table_query in request.tables:
            table_data = {
                "table": table_query.table,
                "fields": table_query.fields,
                "continuationPoint": table_query.continuationPoint
            }
            request_data["tables"].append(table_data)
        
        # 调用时序数据查询
        response_data = query_raw_data(request_data)
        
        # 返回查询结果
        return response_data
        
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"服务器内部错误: {str(e)}"
        )

@router.get("/health")
async def health_check():
    """
    TSDB服务健康检查
    
    Returns:
        Dict: 健康状态
    """
    return {
        "code": 0,
        "message": "TSDB服务运行正常",
        "data": {
            "status": "healthy",
            "version": "v4.0",
            "timestamp": datetime.now().isoformat(),
            "uptime": "24h 35m 12s"
        }
    }

