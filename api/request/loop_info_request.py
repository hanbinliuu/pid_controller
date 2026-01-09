#!/usr/bin/env python3
"""
回路信息请求模型
"""
from typing import List, Optional
from pydantic import BaseModel, Field

class LoopInfoItem(BaseModel):
    """单条回路信息项"""
    loop_uri: str = Field(..., description="回路URI，唯一标识一个回路")
    loop_path: Optional[str] = Field(None, description="PID相关参数的相对路径")
    loop_name: Optional[str] = Field(None, description="回路名称")
    loop_type: Optional[str] = Field(None, description="回路类型")
    point_path: Optional[str] = Field(None, description="测点相对路径")
    pv_field: Optional[str] = Field(None, description="PV字段名")
    sv_field: Optional[str] = Field(None, description="SV字段名")
    mv_field: Optional[str] = Field(None, description="MV字段名")
    auto_status_field: Optional[str] = Field(None, description="自动/手动状态字段名")
    pb_field: Optional[str] = Field(None, description="PB字段名")
    ti_field: Optional[str] = Field(None, description="TI字段名")
    td_field: Optional[str] = Field(None, description="TD字段名")
    description: Optional[str] = Field(None, description="描述或备注")
    is_active: bool = Field(True, description="是否激活")

class BatchCreateLoopInfoRequest(BaseModel):
    """批量创建回路信息请求"""
    loops: List[LoopInfoItem] = Field(..., description="回路信息列表")
