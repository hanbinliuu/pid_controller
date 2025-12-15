from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class ModelParameters(BaseModel):
    """模型参数"""
    K: float = Field(..., description="增益系数")
    T1: float = Field(..., description="一阶时间常数")
    T2: Optional[float] = Field(None, description="二阶时间常数（仅二阶模型）")
    L: Optional[float] = Field(None, description="滞后时间")

class PIDParameters(BaseModel):
    """PID参数"""
    kp: float = Field(..., description="比例系数")
    ki: float = Field(..., description="积分系数")
    kd: float = Field(..., description="微分系数")
    pb: Optional[float] = Field(None, description="比例带")
    ti: Optional[float] = Field(None, description="积分时间")
    td: Optional[float] = Field(None, description="微分时间")

class FittingResult(BaseModel):
    """拟合效果评估"""
    r_squared: Optional[float] = Field(None, description="R²拟合度（越接近1越好）")
    rmse: Optional[float] = Field(None, description="均方根误差")
    recommendation: Optional[str] = Field(None, description="拟合质量建议")

class AutoTuningResponse(BaseModel):
    """自动整定接口响应模型"""
    success: bool = Field(..., description="整定是否成功")
    message: str = Field(..., description="操作信息")
    model_type: str = Field(..., description="使用的模型类型（FOPDT/FO/SOPDT等）")
    turning_type: str = Field(..., description="整定类型（PID/PI等）")
    model_rating: Optional[float] = Field(None, description="模型评分（0-1）")
    start_time: Optional[int] = Field(None, description="分析的起始时间戳（ms）")
    end_time: Optional[int] = Field(None, description="分析的结束时间戳（ms）")
    model_parameters: Optional[ModelParameters] = Field(None, description="识别的模型参数")
    pid_parameters: Optional[PIDParameters] = Field(None, description="推荐的PID参数")
    fitting_result: Optional[FittingResult] = Field(None, description="模型拟合效果评估")
    execution_time: Optional[float] = Field(None, description="整定耗时（秒）")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "整定成功",
                "model_type": "FOPDT",
                "turning_type": "PID",
                "model_rating": 0.95,
                "start_time": 1670000000000,
                "end_time": 1670003600000,
                "model_parameters": {
                    "K": 1.5,
                    "T1": 30.0,
                    "T2": None,
                    "L": 5.0
                },
                "pid_parameters": {
                    "kp": 0.45,
                    "ki": 0.015,
                    "kd": 5.0,
                    "pb": 100.0,
                    "ti": 30.0,
                    "td": 5.0
                },
                "fitting_result": {
                    "r_squared": 0.98,
                    "rmse": 0.5,
                    "recommendation": "拟合优秀，可以应用"
                },
                "execution_time": 3.25
            }
        }
