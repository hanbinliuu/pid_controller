# encoding: utf-8
"""
统一响应模型
"""
from typing import Any, Optional, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar('T')


class ApiResponse(BaseModel, Generic[T]):
    """
    统一API响应格式
    
    Attributes:
        code: 状态码 (0表示成功, 非0表示失败)
        message: 响应消息
        data: 响应数据
        success: 是否成功 (True/False)
    """
    code: int = 0
    message: str = "success"
    data: Optional[T] = None
    success: bool = True

    class Config:
        json_schema_extra = {
            "example": {
                "code": 0,
                "message": "success",
                "data": {"result": "example"},
                "success": True
            }
        }


def success_response(data: Any = None, message: str = "success") -> dict:
    """
    成功响应
    
    Args:
        data: 响应数据
        message: 响应消息
        
    Returns:
        标准化的成功响应字典
    """
    return {
        "code": 0,
        "message": message,
        "data": data,
        "success": True
    }


def error_response(code: int = 500, message: str = "error", data: Any = None) -> dict:
    """
    错误响应
    
    Args:
        code: 错误码
        message: 错误消息
        data: 错误详情数据
        
    Returns:
        标准化的错误响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data,
        "success": False
    }
