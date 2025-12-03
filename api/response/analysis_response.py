#!/usr/bin/env python3
"""
分析接口响应模型
定义所有分析相关API的请求和响应模型
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class TemperatureAnalysisData(BaseModel):
    """温度曲线分析结果数据模型"""
    rise_time: Optional[float] = Field(None, description="上升时间(秒) - 达到90%目标值的时间")
    settling_time: Optional[float] = Field(None, description="调节时间(秒) - 稳定在误差带内的时间")
    peak_time: Optional[float] = Field(None, description="峰值时间(秒) - 首次达到最大值的时间")
    overshoot: Optional[float] = Field(None, description="超调量(%) - 超出目标值的百分比")
    steady_state_error: Optional[float] = Field(None, description="稳态误差 - 最终稳态值与目标值的偏差")
    temperature_fluctuation: Optional[float] = Field(None, description="温度波动 - 稳态状态下的温度波动程度")
    control_accuracy: Optional[str] = Field(None, description="控制精度评级")
    performance_rating: Optional[str] = Field(None, description="性能评级 (优秀/良好/一般/较差)")
    recommendations: Optional[List[str]] = Field(default_factory=list, description="优化建议列表")
    
    class Config:
        json_schema_extra = {
            "example": {
                "rise_time": 120.5,
                "settling_time": 300.2,
                "peak_time": 150.0,
                "overshoot": 5.2,
                "steady_state_error": 0.5,
                "temperature_fluctuation": 0.2,
                "control_accuracy": "高",
                "performance_rating": "良好",
                "recommendations": [
                    "可适当减小积分时间以提高响应速度",
                    "当前超调量在可接受范围内"
                ]
            }
        }


class TemperatureAnalysisResponse(BaseModel):
    """温度曲线分析响应模型"""
    analysis_result: TemperatureAnalysisData = Field(..., description="分析结果")
    data_points: int = Field(..., description="分析的数据点数")
    time_range: Dict[str, str] = Field(..., description="分析时间范围")
    
    class Config:
        json_schema_extra = {
            "example": {
                "analysis_result": {
                    "rise_time": 120.5,
                    "settling_time": 300.2,
                    "peak_time": 150.0,
                    "overshoot": 5.2,
                    "steady_state_error": 0.5,
                    "temperature_fluctuation": 0.2,
                    "control_accuracy": "高",
                    "performance_rating": "良好",
                    "recommendations": ["建议1", "建议2"]
                },
                "data_points": 1000,
                "time_range": {
                    "start": "2024-12-01 00:00:00",
                    "end": "2024-12-01 12:00:00"
                }
            }
        }


class PIDParameterSet(BaseModel):
    """PID参数集"""
    kp: float = Field(..., description="比例增益")
    ki: float = Field(..., description="积分增益")
    kd: float = Field(..., description="微分增益")
    pb: Optional[float] = Field(None, description="比例带(%)")
    ti: Optional[float] = Field(None, description="积分时间(秒)")
    td: Optional[float] = Field(None, description="微分时间(秒)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "kp": 1.5,
                "ki": 0.3,
                "kd": 0.1,
                "pb": 66.67,
                "ti": 5.0,
                "td": 0.067
            }
        }


class PIDOptimizationData(BaseModel):
    """PID优化结果数据模型"""
    current_params: PIDParameterSet = Field(..., description="当前PID参数")
    optimized_params: PIDParameterSet = Field(..., description="优化后的PID参数")
    model_type: Optional[str] = Field(None, description="识别的模型类型")
    model_parameters: Optional[Dict[str, float]] = Field(None, description="模型参数")
    performance_improvement: Optional[Dict[str, float]] = Field(None, description="性能改进预估")
    optimization_method: Optional[str] = Field(None, description="优化方法")
    confidence_score: Optional[float] = Field(None, description="置信度分数(0-1)")
    warnings: Optional[List[str]] = Field(default_factory=list, description="警告信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "current_params": {
                    "kp": 1.0,
                    "ki": 0.2,
                    "kd": 0.05,
                    "pb": 100.0,
                    "ti": 5.0,
                    "td": 0.05
                },
                "optimized_params": {
                    "kp": 1.5,
                    "ki": 0.3,
                    "kd": 0.1,
                    "pb": 66.67,
                    "ti": 5.0,
                    "td": 0.067
                },
                "model_type": "FOPDT",
                "model_parameters": {
                    "K": 1.2,
                    "T": 100.0,
                    "L": 10.0
                },
                "performance_improvement": {
                    "overshoot_reduction": 30.0,
                    "settling_time_reduction": 25.0
                },
                "optimization_method": "Ziegler-Nichols",
                "confidence_score": 0.85,
                "warnings": []
            }
        }


class PIDOptimizationResponse(BaseModel):
    """PID优化响应模型"""
    optimization_result: PIDOptimizationData = Field(..., description="优化结果")
    loop_info: Dict[str, Any] = Field(..., description="回路信息")
    analysis_timestamp: str = Field(..., description="分析时间戳")
    
    class Config:
        json_schema_extra = {
            "example": {
                "optimization_result": {
                    "current_params": {"kp": 1.0, "ki": 0.2, "kd": 0.05},
                    "optimized_params": {"kp": 1.5, "ki": 0.3, "kd": 0.1},
                    "model_type": "FOPDT",
                    "confidence_score": 0.85
                },
                "loop_info": {
                    "uri": "/pid_zd/xxx",
                    "name": "FIC-101",
                    "type": "流量"
                },
                "analysis_timestamp": "2024-12-03 10:30:00"
            }
        }


class WorkflowRequestModel(BaseModel):
    """工作流请求模型"""
    start_time: str = Field(..., description="开始时间", example="2025-10-08 17:30:37")
    end_time: str = Field(..., description="结束时间", example="2025-10-08 18:00:37")
    loop_type: str = Field(..., description="回路类型", example="流量")
    loop_uri: Optional[str] = Field(None, description="回路URI", example="/pid_zd/xxx")
    response_mode: str = Field("blocking", description="响应模式（blocking/streaming）", example="blocking")
    
    class Config:
        json_schema_extra = {
            "example": {
                "start_time": "2025-10-08 17:30:37",
                "end_time": "2025-10-08 18:00:37",
                "loop_type": "流量",
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "response_mode": "blocking"
            }
        }


class WorkflowResultData(BaseModel):
    """工作流执行结果数据"""
    workflow_id: Optional[str] = Field(None, description="工作流ID")
    status: str = Field(..., description="执行状态")
    result: Optional[Dict[str, Any]] = Field(None, description="执行结果")
    elapsed_time: Optional[float] = Field(None, description="执行耗时(秒)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "workflow_id": "wf_123456",
                "status": "completed",
                "result": {
                    "analysis": "分析结果",
                    "recommendations": "优化建议"
                },
                "elapsed_time": 15.5
            }
        }


class WorkflowResponse(BaseModel):
    """工作流响应模型"""
    workflow_result: WorkflowResultData = Field(..., description="工作流执行结果")
    request_info: Dict[str, Any] = Field(..., description="请求信息")
    
    class Config:
        json_schema_extra = {
            "example": {
                "workflow_result": {
                    "workflow_id": "wf_123456",
                    "status": "completed",
                    "result": {},
                    "elapsed_time": 15.5
                },
                "request_info": {
                    "loop_uri": "/pid_zd/xxx",
                    "time_range": "2025-10-08 17:30:37 - 2025-10-08 18:00:37"
                }
            }
        }
