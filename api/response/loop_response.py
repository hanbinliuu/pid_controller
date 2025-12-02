#!/usr/bin/env python3
"""
回路查询响应模型定义
使用Pydantic BaseModel定义类型安全的响应对象
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class LoopStatus(BaseModel):
    """回路状态"""
    PB: Optional[float] = Field(None, description="比例带 (%)")
    TI: Optional[float] = Field(None, description="积分时间 (秒)")
    TD: Optional[float] = Field(None, description="微分时间 (秒)")
    PV: Optional[float] = Field(None, description="过程量")
    MV: Optional[float] = Field(None, description="阀位量")
    SV: Optional[float] = Field(None, description="目标量")
    AUTO: Optional[str] = Field(None, description="自动控制状态")


class LoopInstance(BaseModel):
    """回路实例模型"""
    uri: str = Field(..., description="回路URI")
    browseName: str = Field(..., description="浏览名称")
    displayName: str = Field(..., description="显示名称")
    description: Optional[str] = Field(None, description="描述")
    uriPath: str = Field(None, description="回路uriPath")
    extendedAttr: Dict[str, Any] = Field(default_factory=dict, description="扩展属性")
    loop_status: Optional[LoopStatus] = Field(None, description="回路最新状态参数")

    class Config:
        json_schema_extra = {
            "example": {
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "browseName": "flow_loop_model_1",
                "displayName": "流量单回路实例_1",
                "description": "创建根节点，用于组织模型结构",
                "uriPath": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d4464388e29829f95a49c6,pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "extendedAttr": {"loop_type": "流量"},
                "loop_status": {
                    "PB": 71.43,
                    "TI": 3.11,
                    "TD": 2.0,
                    "PV": 0.0,
                    "MV": 0.0,
                    "SV": 0.0,
                    "AUTO": "自动"
                }
            }
        }


class Pagination(BaseModel):
    """分页信息模型"""
    total: int = Field(..., description="总记录数")
    pages: int = Field(..., description="总页数")
    pageNo: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")

    class Config:
        json_schema_extra = {
            "example": {
                "total": 2,
                "pages": 1,
                "pageNo": 1,
                "pageSize": 10
            }
        }


class LoopListResponse(BaseModel):
    """回路列表查询响应模型"""
    instances: List[LoopInstance] = Field(default_factory=list, description="回路实例列表")
    pagination: Pagination = Field(..., description="分页信息")

    class Config:
        json_schema_extra = {
            "example": {
                "instances": [
                    {
                        "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                        "browseName": "flow_loop_model_1",
                        "displayName": "流量单回路实例_1",
                        "description": "创建根节点，用于组织模型结构",
                        "uriPath": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d4464388e29829f95a49c6,pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                        "extendedAttr": {"loop_type": "流量"},
                        "loop_status": {
                            "PB": 71.43,
                            "TI": 3.11,
                            "TD": 2.0,
                            "PV": 0.0,
                            "MV": 0.0,
                            "SV": 0.0,
                            "AUTO": "自动"
                        }
                    }
                ],
                "pagination": {
                    "total": 2,
                    "pages": 1,
                    "pageNo": 1,
                    "pageSize": 10
                }
            }
        }


class LoopInfoResponse(BaseModel):
    """回路属性查询响应模型"""
    uri: str = Field(None, description="回路URI")
    browseName: str = Field(None, description="回路浏览名称")
    displayName: str = Field(None, description="回路显示名称")
    uriPath: str = Field(None, description="回路uriPath")
    description: Optional[str] = Field(None, description="回路描述")
    extendedAttr: Dict[str, Any] = Field(default_factory=dict, description="回路扩展属性")
    auto_control_status: Optional[Any] = Field(None, description="自控情况")
    action_type: Optional[Any] = Field(None, description="正反作用")
    sv_range_max: Optional[float] = Field(None, description="目标值量程上限")
    sv_range_min: Optional[float] = Field(None, description="目标值量程下限")
    mv_range_max: Optional[float] = Field(None, description="阀位值量程上限")
    mv_range_min: Optional[float] = Field(None, description="阀位值量程下限")

    class Config:
        json_schema_extra = {
            "example": {
                "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "browseName": "flow_loop_model_1",
                "displayName": "流量单回路实例_1",
                "description": "创建根节点，用于组织模型结构",
                "uriPath": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57,pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d,/pid_zd/1f59615dc9d4464388e29829f95a49c6,pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "extendedAttr": {"loop_type": "流量"},
                "auto_control_status": "自动",
                "action_type": "未知",
                "sv_range_max": 100,
                "sv_range_min": 0,
                "mv_range_max": 100,
                "mv_range_min": 0
            }
        }


class OptimizableLoop(BaseModel):
    """可优化回路模型"""
    loop_name: str = Field(None, description="回路名称")
    loop_desc: str = Field(None, description="回路描述")
    loop_type: str = Field(None, description="回路类型")
    performance_score: float = Field(None, description="性能得分")
    current_pid: str = Field(None, description="当前PID参数")
    pass