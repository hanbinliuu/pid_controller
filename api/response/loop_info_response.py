#!/usr/bin/env python3
"""
回路信息响应Bean类
用于API接口返回的回路信息数据结构
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class LoopInfoResponse(BaseModel):
    """
    回路信息响应模型
    
    用于API接口返回单个回路的详细信息，包含回路的所有属性。
    该模型是对LoopInfo数据库模型的封装，用于对外提供标准化的数据结构。
    """
    id: str = Field(
        default=None,
        description="记录ID(UUID)",
        example="66e79166-da9b-4dd6-8a81-baa635dc54ac"
    )
    
    loop_uri: str = Field(
        default=None,
        description="回路URI，唯一标识一个回路",
        example="/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582"
    )
    
    loop_path: Optional[str] = Field(
        default=None,
        description="PID相关参数的相对路径",
        example="/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d44b4388e29829f95a49c6,/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582"
    )
    
    loop_name: Optional[str] = Field(
        default=None,
        description="回路名称",
        example="液位_FIC005A1"
    )
    
    loop_type: Optional[str] = Field(
        default=None,
        description="回路类型",
        example="液位控制"
    )
    
    description: Optional[str] = Field(
        default=None,
        description="回路描述信息",
        example="液位控制回路"
    )
    
    point_path: Optional[str] = Field(
        default=None,
        description="测点相对路径",
        example="/loop_state_parameters"
    )
    
    pv_field: Optional[str] = Field(
        default=None,
        description="PV(过程值)字段名",
        example="FIC005A1_PV"
    )
    
    sv_field: Optional[str] = Field(
        default=None,
        description="SV(设定值)字段名",
        example="FIC005A1_SV"
    )
    
    mv_field: Optional[str] = Field(
        default=None,
        description="MV(阀位值)字段名",
        example="FIC005A1_MV"
    )
    
    auto_status_field: Optional[str] = Field(
        default=None,
        description="自动状态字段名",
        example="FIC005A1_AUTO"
    )
    
    pb_field: Optional[str] = Field(
        default=None,
        description="PB(比例带)字段名",
        example="FIC005A1_PB"
    )
    
    ti_field: Optional[str] = Field(
        default=None,
        description="TI(积分时间常数)字段名",
        example="FIC005A1_TI"
    )
    
    td_field: Optional[str] = Field(
        default=None,
        description="TD(微分时间常数)字段名",
        example="FIC005A1_TD"
    )
    
    is_active: bool = Field(
        default=True,
        description="是否激活状态"
    )
    
    created_time: Optional[str] = Field(
        default=None,
        description="记录创建时间",
        example="2023-12-20T10:30:00"
    )
    
    updated_time: Optional[str] = Field(
        default=None,
        description="记录更新时间",
        example="2023-12-20T10:30:00"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "66e79166-da9b-4dd6-8a81-baa635dc54ac",
                "loop_uri": "/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582",
                "loop_path": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d44b4388e29829f95a49c6,/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582",
                "loop_name": "液位_FIC005A1",
                "loop_type": "液位控制",
                "description": "液位控制回路",
                "point_path": "/loop_state_parameters",
                "pv_field": "FIC005A1_PV",
                "sv_field": "FIC005A1_SV",
                "mv_field": "FIC005A1_MV",
                "auto_status_field": "FIC005A1_AUTO",
                "pb_field": "FIC005A1_PB",
                "ti_field": "FIC005A1_TI",
                "td_field": "FIC005A1_TD",
                "is_active": True,
                "created_time": "2023-12-20T10:30:00",
                "updated_time": "2023-12-20T10:30:00"
            }
        }


class UpdateLoopInfoResponse(BaseModel):
    """
    更新回路信息响应模型
    
    用于API接口返回更新回路信息操作的结果，仅包含关键字段。
    该模型是LoopInfoResponse的简化版本，只包含更新操作后需要返回的核心信息。
    """
    id: str = Field(
        default=None,
        description="记录ID(UUID)",
        example="66e79166-da9b-4dd6-8a81-baa635dc54ac"
    )
    
    loop_uri: str = Field(
        default=None,
        description="回路URI，唯一标识一个回路",
        example="/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582"
    )
    
    loop_path: Optional[str] = Field(
        default=None,
        description="PID相关参数的相对路径",
        example="/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d44b4388e29829f95a49c6,/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582"
    )
    
    loop_name: Optional[str] = Field(
        default=None,
        description="回路名称",
        example="液位_FIC005A1"
    )
    
    updated_time: Optional[str] = Field(
        default=None,
        description="记录更新时间",
        example="2023-12-20T10:30:00"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "66e79166-da9b-4dd6-8a81-baa635dc54ac",
                "loop_uri": "/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582",
                "loop_path": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d44b4388e29829f95a49c6,/pid_zd/806e69336a3e49c7b4fb1ba0a3a66582",
                "loop_name": "液位_FIC005A1",
                "updated_time": "2023-12-20T10:30:00"
            }
        }