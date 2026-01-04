#!/usr/bin/env python3
"""
动态配置参数响应模型定义
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime


class DynamicConfigData(BaseModel):
    """动态配置数据模型"""
    config_key: str = Field(..., description="配置键")
    config_value: Optional[str] = Field(None, description="配置值")
    config_group: Optional[str] = Field(None, description="配置分组")
    config_name: Optional[str] = Field(None, description="配置名称")
    created_time: Optional[str] = Field(None, description="创建时间")
    updated_time: Optional[str] = Field(None, description="更新时间")

    class Config:
        json_schema_extra = {
            "example": {
                "config_key": "virtual_gateway_device_id",
                "config_value": "gateway_123",
                "config_group": "device",
                "config_name": "虚拟网关设备ID",
                "created_time": "2024-01-01T00:00:00",
                "updated_time": "2024-01-01T00:00:00"
            }
        }


class InitializeConfigResult(BaseModel):
    """初始化配置结果"""
    config_key: str = Field(..., description="配置键")
    config_value: str = Field(..., description="配置值")
    status: str = Field(..., description="状态: created/skipped/failed")
    message: str = Field(..., description="结果消息")

    class Config:
        json_schema_extra = {
            "example": {
                "config_key": "virtual_gateway_device_id",
                "config_value": "gateway_123",
                "status": "created",
                "message": "创建成功"
            }
        }


class InitializeResponse(BaseModel):
    """初始化配置响应"""
    message: str = Field(..., description="响应消息")
    created_count: int = Field(..., description="创建数量")
    skipped_count: int = Field(..., description="跳过数量")
    configs: List[InitializeConfigResult] = Field(..., description="配置列表")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "初始化成功",
                "created_count": 3,
                "skipped_count": 0,
                "configs": [
                    {
                        "config_key": "virtual_gateway_device_id",
                        "config_value": "gateway_123",
                        "status": "created",
                        "message": "创建成功"
                    }
                ]
            }
        }


class ConfigValueResponse(BaseModel):
    """配置值响应"""
    config_key: str = Field(..., description="配置键")
    value: Any = Field(..., description="配置值")
    value_type: str = Field(..., description="值类型")

    class Config:
        json_schema_extra = {
            "example": {
                "config_key": "virtual_gateway_device_id",
                "value": "gateway_123",
                "value_type": "str"
            }
        }


class PaginationInfo(BaseModel):
    """分页信息"""
    total: int = Field(..., description="总记录数")
    pages: int = Field(..., description="总页数")
    pageNo: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 10,
                "pages": 1,
                "pageNo": 1,
                "pageSize": 10
            }
        }


class ConfigListResponse(BaseModel):
    """配置列表响应"""
    configs: List[DynamicConfigData] = Field(..., description="配置列表")
    pagination: PaginationInfo = Field(..., description="分页信息")

    class Config:
        json_schema_extra = {
            "example": {
                "configs": [
                    {
                        "config_key": "virtual_gateway_device_id",
                        "config_value": "gateway_123",
                        "config_group": "device",
                        "config_name": "虚拟网关设备ID",
                        "created_time": "2024-01-01T00:00:00",
                        "updated_time": "2024-01-01T00:00:00"
                    }
                ],
                "pagination": {
                    "total": 10,
                    "pages": 1,
                    "pageNo": 1,
                    "pageSize": 10
                }
            }
        }


class ConfigGroupResponse(BaseModel):
    """分组配置列表响应"""
    config_group: str = Field(..., description="配置分组")
    configs: List[DynamicConfigData] = Field(..., description="配置列表")

    class Config:
        json_schema_extra = {
            "example": {
                "config_group": "device",
                "configs": [
                    {
                        "config_key": "virtual_gateway_device_id",
                        "config_value": "gateway_123",
                        "config_group": "device",
                        "config_name": "虚拟网关设备ID",
                        "created_time": "2024-01-01T00:00:00",
                        "updated_time": "2024-01-01T00:00:00"
                    }
                ]
            }
        }


class ConfigsResponse(BaseModel):
    """所有配置响应"""
    configs: List[DynamicConfigData] = Field(..., description="配置列表")

    class Config:
        json_schema_extra = {
            "example": {
                "configs": [
                    {
                        "config_key": "virtual_gateway_device_id",
                        "config_value": "gateway_123",
                        "config_group": "device",
                        "config_name": "虚拟网关设备ID",
                        "created_time": "2024-01-01T00:00:00",
                        "updated_time": "2024-01-01T00:00:00"
                    }
                ]
            }
        }


class UpdateConfigResult(BaseModel):
    """单个配置更新结果"""
    config_key: str = Field(..., description="配置键")
    config_value: Optional[str] = Field(None, description="配置值")
    status: str = Field(..., description="状态: success/failed")
    message: str = Field(..., description="结果消息")

    class Config:
        json_schema_extra = {
            "example": {
                "config_key": "virtual_gateway_device_id",
                "config_value": "new_gateway_456",
                "status": "success",
                "message": "更新成功"
            }
        }


class UpdateConfigResponse(BaseModel):
    """单个配置更新响应"""
    message: str = Field(..., description="响应消息")
    config: DynamicConfigData = Field(..., description="更新后的配置数据")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "配置更新成功",
                "config": {
                    "config_key": "virtual_gateway_device_id",
                    "config_value": "new_gateway_456",
                    "config_group": "device",
                    "config_name": "虚拟网关设备ID",
                    "created_time": "2024-01-01T00:00:00",
                    "updated_time": "2024-01-01T12:00:00"
                }
            }
        }


class BatchUpdateResponse(BaseModel):
    """批量更新响应"""
    message: str = Field(..., description="响应消息")
    success_count: int = Field(..., description="成功数量")
    failed_count: int = Field(..., description="失败数量")
    results: List[UpdateConfigResult] = Field(..., description="更新结果列表")

    class Config:
        json_schema_extra = {
            "example": {
                "message": "批量更新完成",
                "success_count": 2,
                "failed_count": 1,
                "results": [
                    {
                        "config_key": "virtual_gateway_device_id",
                        "config_value": "new_gateway_456",
                        "status": "success",
                        "message": "更新成功"
                    },
                    {
                        "config_key": "invalid_key",
                        "status": "failed",
                        "message": "配置键 'invalid_key' 不存在"
                    }
                ]
            }
        }
