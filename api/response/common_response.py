#!/usr/bin/env python3
"""
通用响应模型定义
为所有API接口提供统一的响应格式说明
"""
from typing import Generic, TypeVar, Optional, Any, List, Dict
from pydantic import BaseModel, Field

T = TypeVar('T')


class ApiResponse(BaseModel, Generic[T]):
    """
    统一API响应格式
    
    所有API接口都会被包装成此格式（通过ResponseMiddleware中间件）
    
    字段说明:
        - code: 状态码，0表示成功，非0表示失败
        - message: 响应消息，描述操作结果
        - data: 响应数据，具体的业务数据
        - success: 操作是否成功的布尔值
    """
    code: int = Field(0, description="状态码，0表示成功，非0表示失败")
    message: str = Field("success", description="响应消息")
    data: Optional[T] = Field(None, description="响应数据")
    success: bool = Field(True, description="操作是否成功")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "success",
                "data": {
                    "result": "示例数据"
                },
                "success": True
            }
        }


class PaginationInfo(BaseModel):
    """分页信息"""
    total: int = Field(..., description="总记录数")
    pages: int = Field(..., description="总页数")
    pageNo: int = Field(..., description="当前页码，从1开始")
    pageSize: int = Field(..., description="每页数量")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 100,
                "pages": 10,
                "pageNo": 1,
                "pageSize": 10
            }
        }


class PagedResponse(BaseModel, Generic[T]):
    """
    分页数据响应
    
    用于返回分页列表数据
    """
    items: List[T] = Field(default_factory=list, description="数据列表")
    pagination: PaginationInfo = Field(..., description="分页信息")

    class Config:
        json_schema_extra = {
            "example": {
                "items": [],
                "pagination": {
                    "total": 100,
                    "pages": 10,
                    "pageNo": 1,
                    "pageSize": 10
                }
            }
        }


class ErrorDetail(BaseModel):
    """错误详情"""
    field: Optional[str] = Field(None, description="错误字段名")
    message: str = Field(..., description="错误消息")
    code: Optional[str] = Field(None, description="错误代码")

    class Config:
        json_schema_extra = {
            "example": {
                "field": "loop_uri",
                "message": "回路URI不能为空",
                "code": "VALIDATION_ERROR"
            }
        }


class ErrorResponse(BaseModel):
    """
    错误响应格式
    
    当接口发生错误时的统一响应格式
    """
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误消息")
    data: Optional[Any] = Field(None, description="错误详情")
    success: bool = Field(False, description="操作失败")

    class Config:
        json_schema_extra = {
            "example": {
                "code": 400,
                "message": "参数验证失败",
                "data": {
                    "field": "loop_uri",
                    "error": "回路URI格式不正确"
                },
                "success": False
            }
        }


def format_response_doc(
    description: str,
    success_example: Dict[str, Any],
    error_example: Optional[Dict[str, Any]] = None
) -> str:
    """
    格式化响应文档
    
    Args:
        description: 接口描述
        success_example: 成功响应示例
        error_example: 错误响应示例（可选）
    
    Returns:
        格式化的文档字符串
    """
    doc = f"""
{description}

## 成功响应格式
```json
{{
  "code": 0,
  "message": "success",
  "data": {success_example},
  "success": true
}}
```
"""
    
    if error_example:
        doc += f"""
## 错误响应格式
```json
{{
  "code": 400,
  "message": "错误消息",
  "data": {error_example},
  "success": false
}}
```
"""
    
    return doc
