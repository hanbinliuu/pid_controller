#!/usr/bin/env python3
"""
参数转换接口响应模型
定义PID参数转换相关API的请求和响应模型
"""
from typing import Optional, Dict
from pydantic import BaseModel, Field


class PIDParametersModel(BaseModel):
    """PID标准参数模型"""
    kp: float = Field(..., ge=0, description="比例增益 Kp，必须>=0")
    ki: float = Field(..., ge=0, description="积分增益 Ki，必须>=0")
    kd: float = Field(..., ge=0, description="微分增益 Kd，必须>=0")
    
    class Config:
        json_schema_extra = {
            "example": {
                "kp": 1.5,
                "ki": 0.3,
                "kd": 0.1
            }
        }


class ClassicalParametersModel(BaseModel):
    """经典控制参数模型"""
    proportional_band: float = Field(..., gt=0, description="比例带 PB (%)，必须>0")
    integral_time: Optional[float] = Field(None, gt=0, description="积分时间 Ti (秒)，必须>0或为空")
    derivative_time: Optional[float] = Field(None, ge=0, description="微分时间 Td (秒)，必须>=0或为空")
    
    class Config:
        json_schema_extra = {
            "example": {
                "proportional_band": 66.67,
                "integral_time": 5.0,
                "derivative_time": 0.067
            }
        }


class PIDConversionResult(BaseModel):
    """PID参数转换结果"""
    kp: float = Field(..., description="比例增益")
    ki: float = Field(..., description="积分增益")
    kd: float = Field(..., description="微分增益")
    
    class Config:
        json_schema_extra = {
            "example": {
                "kp": 1.5,
                "ki": 0.3,
                "kd": 0.1
            }
        }


class ClassicalConversionResult(BaseModel):
    """经典控制参数转换结果"""
    proportional_band: Optional[float] = Field(None, description="比例带 PB (%)")
    integral_time: Optional[float] = Field(None, description="积分时间 Ti (秒)")
    derivative_time: float = Field(..., description="微分时间 Td (秒)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "proportional_band": 66.67,
                "integral_time": 5.0,
                "derivative_time": 0.067
            }
        }


class ConversionResponseData(BaseModel):
    """
    参数转换响应数据模型
    
    包含原始参数和转换后的参数
    """
    original: Dict = Field(..., description="原始参数")
    converted: Dict = Field(..., description="转换后的参数")
    
    class Config:
        json_schema_extra = {
            "example": {
                "original": {
                    "kp": 1.5,
                    "ki": 0.3,
                    "kd": 0.1
                },
                "converted": {
                    "proportional_band": 66.67,
                    "integral_time": 5.0,
                    "derivative_time": 0.067
                }
            }
        }


class FormatParametersData(BaseModel):
    """
    格式化参数数据模型
    
    同时包含标准格式和经典格式
    """
    standard: PIDConversionResult = Field(..., description="标准PID参数格式")
    classical: ClassicalConversionResult = Field(..., description="经典控制参数格式")
    
    class Config:
        json_schema_extra = {
            "example": {
                "standard": {
                    "kp": 1.5,
                    "ki": 0.3,
                    "kd": 0.1
                },
                "classical": {
                    "proportional_band": 66.67,
                    "integral_time": 5.0,
                    "derivative_time": 0.067
                }
            }
        }


class ParameterValidationResult(BaseModel):
    """
    参数验证结果模型
    
    返回各参数的有效性检查结果
    """
    kp_valid: bool = Field(..., description="Kp参数是否有效")
    ki_valid: bool = Field(..., description="Ki参数是否有效")
    kd_valid: bool = Field(..., description="Kd参数是否有效")
    stable: bool = Field(..., description="系统是否稳定")
    message: str = Field(..., description="验证结果说明")
    details: Optional[Dict] = Field(None, description="详细验证信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "kp_valid": True,
                "ki_valid": True,
                "kd_valid": True,
                "stable": True,
                "message": "所有参数有效，系统稳定",
                "details": {
                    "kp_range": [0, 10],
                    "ki_range": [0, 1],
                    "kd_range": [0, 1]
                }
            }
        }
