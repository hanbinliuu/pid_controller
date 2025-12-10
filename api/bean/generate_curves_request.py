#!/usr/bin/env python3
"""
generate_all_curves 接口请求体 (Request Body)
使用 Pydantic 模型定义请求体参数
"""

from typing import Optional
from pydantic import BaseModel, Field, validator
from core.utils.model_type import ModelType


class GenerateCurvesRequest(BaseModel):
    """generate_all_curves 接口请求体"""
    
    # 时间参数
    start_time: Optional[int] = Field(None, description="开始时间(毫秒时间戳)")
    end_time: Optional[int] = Field(None, description="结束时间(毫秒时间戳)")
    
    # 模型参数
    K: float = Field(..., description="系统增益", examples=[1.0, 1.5, 2.0])
    T1: float = Field(..., description="时间常数(秒)", examples=[30.0, 45.0, 60.0])
    T2: Optional[float] = Field(None, description="二阶时间常数(秒)",  examples=[20.0, 30.0])
    L: float = Field(0.0, description="滞后时间(秒)", examples=[0.0, 1.0, 2.0])
    model_type: ModelType = Field(ModelType.FOPDT, description="模型类型")
    
    # PID参数
    Kp: Optional[float] = Field(None, description="PID比例系数", examples=[1.0, 1.2, 1.5])
    Ki: Optional[float] = Field(None, description="PID积分系数", examples=[0.05, 0.1, 0.15])
    Kd: Optional[float] = Field(None, description="PID微分系数", examples=[0.0, 0.1, 0.2])
    
    # 仿真参数
    step_value: float = Field(1.0, description="阶跃输入幅值", examples=[1.0, 2.0, 5.0])
    duration: float = Field(500, description="仿真时长(秒)", gt=0, examples=[300.0, 600.0, 1200.0])
    dt: float = Field(1.0, description="采样时间间隔(秒)", gt=0, examples=[0.1, 0.5, 1.0])
    initial_output: float = Field(0.0, description="初始输出值", examples=[0.0, 5.0, 10.0])
    setpoint: Optional[float] = Field(10, description="设定值(闭环仿真目标值)", examples=[50.0, 100.0, 150.0])
    
    @validator('T2')
    def validate_t2(cls, v, values):
        """验证二阶模型必须有T2参数"""
        if 'model_type' in values:
            model_type = values['model_type']
            if model_type in [ModelType.SOPDT, ModelType.SO, ModelType.SOPI]:
                if v is None or v <= 0:
                    raise ValueError(f"模型类型 {model_type.value} 必须指定正数 T2")
        return v
    
    @validator('start_time', 'end_time')
    def validate_time_range(cls, v, values):
        """验证时间范围"""
        if v is not None and 'start_time' in values and values['start_time'] is not None:
            if values['start_time'] >= v:
                raise ValueError("开始时间必须小于结束时间")
        return v
    
    class Config:
        """Pydantic 配置"""
        json_schema_extra = {
            "example": {
                "K": 1.5,
                "T1": 45.0,
                "L": 2.0,
                "model_type": "FOPDT",
                "Kp": 1.0,
                "Ki": 0.1,
                "Kd": 0.0,
                "step_value": 1.0,
                "duration": 600.0,
                "dt": 1.0,
                "initial_output": 0.0,
                "setpoint": 100.0
            }
        }
    
    def to_dict(self):
        """转换为字典，用于传递给内部函数"""
        return self.model_dump(exclude_none=True)


class FOPDTRequest(BaseModel):
    """一阶加纯滞后模型(FOPDT)请求体"""
    
    K: float = Field(..., description="系统增益", gt=0, examples=[1.0, 1.5, 2.0])
    T1: float = Field(..., description="时间常数(秒)", gt=0, examples=[30.0, 45.0, 60.0])
    L: float = Field(0.0, description="滞后时间(秒)", ge=0, examples=[0.0, 1.0, 2.0])
    Kp: Optional[float] = Field(None, description="PID比例系数", examples=[1.0, 1.2, 1.5])
    Ki: Optional[float] = Field(None, description="PID积分系数", ge=0, examples=[0.05, 0.1, 0.15])
    Kd: Optional[float] = Field(None, description="PID微分系数", ge=0, examples=[0.0, 0.1, 0.2])
    step_value: float = Field(1.0, description="阶跃输入幅值", examples=[1.0, 2.0, 5.0])
    duration: float = Field(600.0, description="仿真时长(秒)", gt=0, examples=[300.0, 600.0, 1200.0])
    dt: float = Field(1.0, description="采样时间间隔(秒)", gt=0, examples=[0.1, 0.5, 1.0])
    initial_output: float = Field(0.0, description="初始输出值", examples=[0.0, 5.0, 10.0])
    setpoint: Optional[float] = Field(None, description="设定值", examples=[50.0, 100.0, 150.0])
    start_time: Optional[int] = Field(None, description="开始时间(毫秒时间戳)")
    end_time: Optional[int] = Field(None, description="结束时间(毫秒时间戳)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "K": 1.5,
                "T1": 45.0,
                "L": 2.0,
                "Kp": 1.0,
                "Ki": 0.1,
                "Kd": 0.0,
                "step_value": 1.0,
                "duration": 600.0,
                "dt": 1.0,
                "setpoint": 100.0
            }
        }
    
    def to_generate_curves_request(self) -> GenerateCurvesRequest:
        """转换为 GenerateCurvesRequest"""
        return GenerateCurvesRequest(
            start_time=self.start_time,
            end_time=self.end_time,
            K=self.K,
            T1=self.T1,
            L=self.L,
            model_type=ModelType.FOPDT,
            Kp=self.Kp,
            Ki=self.Ki,
            Kd=self.Kd,
            step_value=self.step_value,
            duration=self.duration,
            dt=self.dt,
            initial_output=self.initial_output,
            setpoint=self.setpoint
        )


class SOPDTRequest(BaseModel):
    """二阶加纯滞后模型(SOPDT)请求体"""
    
    K: float = Field(..., description="系统增益", gt=0, examples=[1.0, 1.5, 2.0])
    T1: float = Field(..., description="第一时间常数(秒)", gt=0, examples=[30.0, 45.0, 60.0])
    T2: float = Field(..., description="第二时间常数(秒)", gt=0, examples=[20.0, 30.0, 40.0])
    L: float = Field(0.0, description="滞后时间(秒)", ge=0, examples=[0.0, 1.0, 2.0])
    Kp: Optional[float] = Field(None, description="PID比例系数", examples=[1.0, 1.2, 1.5])
    Ki: Optional[float] = Field(None, description="PID积分系数", ge=0, examples=[0.05, 0.1, 0.15])
    Kd: Optional[float] = Field(None, description="PID微分系数", ge=0, examples=[0.0, 0.1, 0.2])
    step_value: float = Field(1.0, description="阶跃输入幅值", examples=[1.0, 2.0, 5.0])
    duration: float = Field(600.0, description="仿真时长(秒)", gt=0, examples=[300.0, 600.0, 1200.0])
    dt: float = Field(1.0, description="采样时间间隔(秒)", gt=0, examples=[0.1, 0.5, 1.0])
    initial_output: float = Field(0.0, description="初始输出值", examples=[0.0, 5.0, 10.0])
    setpoint: Optional[float] = Field(None, description="设定值", examples=[50.0, 100.0, 150.0])
    start_time: Optional[int] = Field(None, description="开始时间(毫秒时间戳)")
    end_time: Optional[int] = Field(None, description="结束时间(毫秒时间戳)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "K": 1.2,
                "T1": 40.0,
                "T2": 20.0,
                "L": 2.0,
                "Kp": 1.0,
                "Ki": 0.1,
                "Kd": 0.0,
                "step_value": 1.0,
                "duration": 600.0,
                "dt": 1.0,
                "setpoint": 100.0
            }
        }
    
    def to_generate_curves_request(self) -> GenerateCurvesRequest:
        """转换为 GenerateCurvesRequest"""
        return GenerateCurvesRequest(
            start_time=self.start_time,
            end_time=self.end_time,
            K=self.K,
            T1=self.T1,
            T2=self.T2,
            L=self.L,
            model_type=ModelType.SOPDT,
            Kp=self.Kp,
            Ki=self.Ki,
            Kd=self.Kd,
            step_value=self.step_value,
            duration=self.duration,
            dt=self.dt,
            initial_output=self.initial_output,
            setpoint=self.setpoint
        )
