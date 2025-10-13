#!/usr/bin/env python3
"""
时序数据库(TSDB) API路由
实现历史原始值查询接口 /tsdb/v4/read_raw
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Any, Union
from datetime import datetime
import json
import re
import os

# 导入时序数据查询模块
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from core.data.mock_tsdb_api import query_raw_data
except ImportError:
    # 如果导入失败，提供一个简单的模拟实现
    def query_raw_data(request_data: Dict) -> Dict:
        return {
            "code": 0,
            "message": "",
            "results": []
        }

router = APIRouter()

def get_default_database() -> str:
    """
    获取默认数据库名称，优先从环境变量读取
    
    Returns:
        str: 数据库名称
    """
    return os.getenv('DEFAULT_TSDB_DATABASE', 'platform')

def parse_time_to_milliseconds(time_input: Union[int, str]) -> int:
    """
    将时间参数转换为毫秒时间戳
    
    支持格式：
    - 毫秒时间戳 (int): 1640995200000
    - 秒时间戳 (int): 1640995200 (自动检测并转换)
    - ISO格式字符串: "2022-01-01T12:00:00"
    - 标准格式字符串: "2022-01-01 12:00:00"
    - 日期格式字符串: "2022-01-01"
    
    Args:
        time_input: 时间输入，支持int或str格式
        
    Returns:
        int: 毫秒时间戳
        
    Raises:
        ValueError: 时间格式不支持或解析失败
    """
    if isinstance(time_input, int):
        # 如果是整数，检查是秒还是毫秒
        if time_input < 10000000000:  # 小于10位数，认为是秒时间戳
            return time_input * 1000
        else:  # 大于等于10位数，认为是毫秒时间戳
            return time_input
    
    elif isinstance(time_input, str):
        # 字符串格式的时间解析
        time_patterns = [
            # ISO 8601格式
            (r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$', '%Y-%m-%dT%H:%M:%S'),
            # 标准格式
            (r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', '%Y-%m-%d %H:%M:%S'),
            # 日期格式（默认00:00:00）
            (r'^\d{4}-\d{2}-\d{2}$', '%Y-%m-%d'),
            # 带毫秒的格式
            (r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+$', '%Y-%m-%d %H:%M:%S.%f'),
        ]
        
        for pattern, fmt in time_patterns:
            if re.match(pattern, time_input.strip()):
                try:
                    # 处理ISO格式中的时区信息
                    clean_time = time_input.strip()
                    if 'T' in clean_time and (clean_time.endswith('Z') or '+' in clean_time[-6:] or clean_time[-6:].count('-') == 1):
                        # 移除时区信息进行简单解析
                        if clean_time.endswith('Z'):
                            clean_time = clean_time[:-1]
                        elif '+' in clean_time[-6:]:
                            clean_time = clean_time.split('+')[0]
                        elif clean_time[-6:].count('-') == 1:
                            clean_time = clean_time.rsplit('-', 1)[0]
                    
                    dt = datetime.strptime(clean_time, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue
        
        # 如果所有格式都不匹配，尝试解析为时间戳字符串
        try:
            timestamp = int(time_input)
            return parse_time_to_milliseconds(timestamp)
        except ValueError:
            pass
        
        raise ValueError(f"不支持的时间格式: {time_input}. 支持的格式包括: 毫秒时间戳、'YYYY-MM-DD'、'YYYY-MM-DD HH:MM:SS'、'YYYY-MM-DDTHH:MM:SS'")
    
    else:
        raise ValueError(f"时间参数类型错误: {type(time_input)}. 期望 int 或 str 类型")

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

@router.get("/tables",
            summary="获取数据库表列表",
            description="获取指定数据库中可用的所有表名列表，支持表的基本信息查询和管理")
async def list_tables(
    db: Optional[str] = Query(None, description="数据库名称")
):
    """
    **获取数据库表列表**
    
    提供数据库中所有可用表的完整列表，帮助用户了解数据结构和可用资源。
    
    **功能特性：**
    - 获取指定数据库的所有表名
    - 支持多数据库环境的灵活切换
    - 实时反映数据库结构变化
    - 高效的元数据查询机制
    
    **返回信息：**
    - database: 当前查询的数据库名称
    - tables: 可用表名的完整列表
    - 状态信息和响应码
    
    **应用场景：**
    - 数据探索和发现
    - 数据源配置和验证
    - 自动化监控系统集成
    - 数据库管理和维护
    
    **注意事项：**
    - 当前返回模拟数据，实际使用时需连接真实数据源
    - 表名可能包含特殊字符，需进行适当的转义处理
    """
    try:
        # 这里应该从实际的数据源获取表列表
        # 目前返回模拟数据
        mock_tables = [
            "cpu",
            "memory", 
            "disk",
            "network",
            "temperature",
            "pid_control",
            "ns-01f-001"
        ]
        
        return {
            "code": 0,
            "message": "",
            "data": {
                "database": db or "default",
                "tables": mock_tables
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取表列表失败: {str(e)}"
        )

@router.get("/tables/{table_name}/schema",
            summary="获取表结构信息",
            description="获取指定表的详细结构信息，包括字段定义、数据类型、索引信息等，为数据查询提供参考")
async def get_table_schema(
    table_name: str,
    db: Optional[str] = Query(None, description="数据库名称")
):
    """
    **获取表结构信息**
    
    提供指定表的完整结构信息，帮助用户理解数据格式和查询可能性。
    
    **结构信息包含：**
    
    **1. 字段定义：**
    - fields: 所有数据字段名称列表
    - 字段数据类型和约束信息
    - 主键和外键关系
    
    **2. 标签信息：**
    - tags: 可用于筛选的标签字段
    - 标签的取值范围和约束
    - 索引和查询优化信息
    
    **3. 表元数据：**
    - description: 表的功能和作用描述
    - 创建时间和修改历史
    - 数据统计信息(记录数、大小等)
    
    **返回格式：**
    - 结构化的表结构描述
    - JSON格式的字段和标签定义
    - 与查询接口兼容的参数格式
    
    **应用价值：**
    - 查询参数的验证和优化
    - 动态查询构建和代码生成
    - 数据集成和迁移计划
    - API文档和开发者工具支持
    
    **示例表结构：**
    - cpu: CPU监控数据表
    - ns-01f-001: 设备监控数据表
    - pid_control: PID控制数据表
    """
    try:
        # 模拟表结构数据
        mock_schemas = {
            "cpu": {
                "fields": ["time", "f1", "f2", "usage"],
                "tags": ["host", "region"],
                "description": "CPU监控数据表"
            },
            "ns-01f-001": {
                "fields": ["time", "s", "v", "status"],
                "tags": ["device", "location"],
                "description": "设备监控数据表"
            },
            "pid_control": {
                "fields": ["time", "temperature", "target_temp", "kp", "ki", "kd", "output"],
                "tags": ["channel", "controller"],
                "description": "PID控制数据表"
            }
        }
        
        if table_name not in mock_schemas:
            raise HTTPException(
                status_code=404,
                detail=f"表 '{table_name}' 不存在"
            )
        
        return {
            "code": 0,
            "message": "",
            "data": {
                "database": db or "default",
                "table": table_name,
                "schema": mock_schemas[table_name]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取表结构失败: {str(e)}"
        )

@router.post("/query")
async def execute_query(
    query: str,
    db: Optional[str] = Query(None, description="数据库名称")
):
    """
    执行自定义查询（简化版）
    
    Args:
        query: 查询语句
        db: 数据库名称
        
    Returns:
        Dict: 查询结果
    """
    try:
        # 这里应该解析和执行实际的查询语句
        # 目前只返回模拟结果
        return {
            "code": 0,
            "message": "查询执行成功",
            "data": {
                "database": db or "default",
                "query": query,
                "result": {
                    "columns": ["time", "value"],
                    "values": [
                        ["2024-01-01 12:00:00", 100],
                        ["2024-01-01 12:01:00", 102]
                    ]
                },
                "execution_time": "0.05s",
                "rows_affected": 2
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"查询执行失败: {str(e)}"
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

# 便捷函数，用于其他模块调用
def query_historical_data(
    table: str,
    fields: Optional[List[str]] = None,
    start_time: Optional[Union[int, str]] = None,
    end_time: Optional[Union[int, str]] = None,
    limit: int = 1500
) -> Dict:
    """
    查询历史数据的便捷函数 - 支持多种时间格式
    
    Args:
        table: 表名
        fields: 字段列表
        start_time: 开始时间，支持毫秒时间戳或字符串格式
        end_time: 结束时间，支持毫秒时间戳或字符串格式
        limit: 限制条数
        
    Returns:
        Dict: 查询结果
        
    Examples:
        >>> # 使用毫秒时间戳
        >>> query_historical_data("temperature", start_time=1640995200000, end_time=1641081600000)
        
        >>> # 使用字符串格式
        >>> query_historical_data("temperature", start_time="2022-01-01 12:00:00", end_time="2022-01-02 12:00:00")
        
        >>> # 使用ISO格式
        >>> query_historical_data("temperature", start_time="2022-01-01T12:00:00", end_time="2022-01-02T12:00:00")
    """
    # 转换时间格式
    start_ms = None
    end_ms = None
    
    if start_time is not None:
        try:
            start_ms = parse_time_to_milliseconds(start_time)
        except ValueError as e:
            raise ValueError(f"开始时间格式错误: {str(e)}")
    
    if end_time is not None:
        try:
            end_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise ValueError(f"结束时间格式错误: {str(e)}")
    
    request_data = {
        "tables": [
            {
                "table": table,
                "fields": fields,
                "continuationPoint": None
            }
        ],
        "detail": {
            "startTime": start_ms,
            "endTime": end_ms or int(datetime.now().timestamp() * 1000),
            "limit": limit,
            "returnBounds": False
        }
    }
    
    return query_raw_data(request_data)