#!/usr/bin/env python3
"""
BFF模型接口响应模型
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class FieldMappingData(BaseModel):
    """字段映射数据"""
    mv: Optional[str] = Field(None, description="阀位值字段")
    pv: Optional[str] = Field(None, description="过程值字段")
    sv: Optional[str] = Field(None, description="设定值字段")
    pb: Optional[str] = Field(None, description="比例带字段")
    ti: Optional[str] = Field(None, description="积分时间字段")
    td: Optional[str] = Field(None, description="微分时间字段")
    auto: Optional[str] = Field(None, description="自动状态字段")
    
    class Config:
        json_schema_extra = {
            "example": {
                "mv": "ns=100;s=FIC101A_MV.In_Channel0",
                "pv": "ns=100;s=FIC101A_PV.In_Channel0",
                "sv": "ns=100;s=FIC101A_SV.In_Channel0",
                "pb": "ns=100;s=FIC101A_PB.In_Channel0",
                "ti": "ns=100;s=FIC101A_TI.In_Channel0",
                "td": "ns=100;s=FIC101A_TD.In_Channel0",
                "auto": "ns=100;s=FIC101A_AUTO.In_Channel0"
            }
        }


class PointPathsResponse(BaseModel):
    """测点路径响应"""
    status: str = Field(..., description="状态")
    project_path: str = Field(..., description="项目路径")
    field_mapping: FieldMappingData = Field(..., description="字段映射")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "project_path": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "field_mapping": {
                    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
                    "pv": "ns=100;s=FIC101A_PV.In_Channel0",
                    "sv": "ns=100;s=FIC101A_SV.In_Channel0"
                }
            }
        }


class SubmodelInfo(BaseModel):
    """子模型信息"""
    uri: str = Field(..., description="模型URI")
    browseName: str = Field(..., description="浏览名称")
    displayName: str = Field(..., description="显示名称")
    extendedAttr: Dict[str, Any] = Field(default_factory=dict, description="扩展属性")
    parentUri: Optional[str] = Field(None, description="父节点URI")
    
    class Config:
        json_schema_extra = {
            "example": {
                "uri": "/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1",
                "browseName": "flow_loop_model",
                "displayName": "流量单回路模型",
                "extendedAttr": {"loop_type": "流量"},
                "parentUri": "/pid_zd/d4d2d8c4906846818c91e4fe06a290a2"
            }
        }


class SubmodelListResponse(BaseModel):
    """子模型列表响应"""
    submodels: List[SubmodelInfo] = Field(default_factory=list, description="子模型列表")
    total: int = Field(..., description="总数量")
    
    class Config:
        json_schema_extra = {
            "example": {
                "submodels": [
                    {
                        "uri": "/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1",
                        "browseName": "flow_loop_model",
                        "displayName": "流量单回路模型",
                        "extendedAttr": {"loop_type": "流量"},
                        "parentUri": "/pid_zd/xxx"
                    }
                ],
                "total": 1
            }
        }


class InstanceTreeNode(BaseModel):
    """实例树节点"""
    uri: str = Field(..., description="节点URI")
    browseName: str = Field(..., description="浏览名称")
    displayName: str = Field(..., description="显示名称")
    description: Optional[str] = Field(None, description="描述")
    extendedAttr: Dict[str, Any] = Field(default_factory=dict, description="扩展属性")
    children: Optional[List['InstanceTreeNode']] = Field(None, description="子节点列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "uri": "/pid_zd/xxx",
                "browseName": "node1",
                "displayName": "节点1",
                "description": "描述",
                "extendedAttr": {},
                "children": []
            }
        }

# 更新前向引用
InstanceTreeNode.model_rebuild()
