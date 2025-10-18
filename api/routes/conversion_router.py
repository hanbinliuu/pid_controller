#!/usr/bin/env python3
"""
PID参数转换API路由
提供PID参数与比例带转换的RESTful API接口
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Union
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from core.utils.pid_converter import PIDConverter

router = APIRouter()

# 请求模型
class PIDParameters(BaseModel):
    """PID标准参数模型"""
    kp: float = Field(..., ge=0, description="比例增益")
    ki: float = Field(..., ge=0, description="积分增益")
    kd: float = Field(..., ge=0, description="微分增益")

class ClassicalParameters(BaseModel):
    """经典控制参数模型"""
    proportional_band: float = Field(..., gt=0, description="比例带百分比 (%)")
    integral_time: Optional[float] = Field(None, gt=0, description="积分时间 (秒)")
    derivative_time: Optional[float] = Field(None, ge=0, description="微分时间 (秒)")

# 响应模型
class PIDResponse(BaseModel):
    """PID参数响应模型"""
    kp: float
    ki: float
    kd: float

class ClassicalResponse(BaseModel):
    """经典控制参数响应模型"""
    proportional_band: Optional[float]
    integral_time: Optional[float] 
    derivative_time: float

class ConversionResponse(BaseModel):
    """转换结果响应模型"""
    success: bool
    message: str
    data: Dict[str, Union[float, Dict[str, float]]]

class ValidationResponse(BaseModel):
    """参数验证响应模型"""
    kp_valid: bool
    ki_valid: bool
    kd_valid: bool
    stable: bool
    message: str


@router.post("/pid-to-classical", 
             response_model=ConversionResponse,
             operation_id="PID标准参数转换为经典控制参数",
             summary="PID标准参数转换为经典控制参数",
             description="将PID控制器的标准参数(Kp, Ki, Kd)转换为经典控制理论中的参数形式(比例带PB%, 积分时间Ti, 微分时间Td)")
async def convert_pid_to_classical(params: PIDParameters):
    """
    **PID标准参数转换为经典控制参数**
    
    将现代PID控制器的标准参数格式转换为传统工业控制中常用的经典控制参数格式。
    
    **转换公式：**
    - 比例带 PB(%) = 100 / Kp
    - 积分时间 Ti(s) = Kp / Ki  
    - 微分时间 Td(s) = Kd / Kp
    
    **参数说明：**
    - Kp: 比例增益，控制系统的比例响应强度
    - Ki: 积分增益，控制系统消除稳态误差的能力
    - Kd: 微分增益，控制系统对变化趋势的预测能力
    
    **应用场景：**
    - 工业控制系统参数配置
    - 控制器参数标准化转换
    - 不同控制系统之间的参数对接
    
    **返回数据：**
    包含原始PID参数和转换后的经典控制参数，便于对比验证
    """
    try:
        classical = PIDConverter.pid_to_classical(params.kp, params.ki, params.kd)
        
        response_data = {
            "standard": {
                "kp": params.kp,
                "ki": params.ki, 
                "kd": params.kd
            },
            "classical": classical
        }
        
        return ConversionResponse(
            success=True,
            message="PID参数转换为经典控制参数成功",
            data=response_data
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"转换失败: {str(e)}")


@router.post("/classical-to-pid", 
             response_model=ConversionResponse,
             operation_id="经典控制参数转换为PID标准参数",
             summary="经典控制参数转换为PID标准参数",
             description="将传统工业控制中的经典参数(比例带PB%, 积分时间Ti, 微分时间Td)转换为现代PID控制器的标准参数格式")
async def convert_classical_to_pid(params: ClassicalParameters):
    """
    **经典控制参数转换为PID标准参数**
    
    将传统工业控制理论中的经典参数格式转换为现代PID控制器的标准参数格式。
    
    **转换公式：**
    - 比例增益 Kp = 100 / PB(%)
    - 积分增益 Ki = Kp / Ti(s)
    - 微分增益 Kd = Td(s) × Kp
    
    **参数说明：**
    - PB: 比例带(%)，表示输出100%变化对应的过程变量变化百分比
    - Ti: 积分时间(秒)，积分作用达到比例作用同样效果所需时间
    - Td: 微分时间(秒)，微分作用提前预测的时间量
    
    **注意事项：**
    - 积分时间为0或None时，Ki设置为0(纯P或PD控制)
    - 微分时间为None时，Kd设置为0(P或PI控制)
    - 比例带必须大于0
    
    **应用场景：**
    - 传统控制系统现代化改造
    - 控制器参数标准化转换
    - 不同品牌控制器之间的参数迁移
    """
    try:
        pid = PIDConverter.classical_to_pid(
            params.proportional_band,
            params.integral_time,
            params.derivative_time
        )
        
        response_data = {
            "classical": {
                "proportional_band": params.proportional_band,
                "integral_time": params.integral_time,
                "derivative_time": params.derivative_time
            },
            "standard": pid
        }
        
        return ConversionResponse(
            success=True,
            message="经典控制参数转换为PID参数成功",
            data=response_data
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"转换失败: {str(e)}")


@router.post("/format-parameters", 
             response_model=ConversionResponse,
             summary="PID参数格式化与双重表示",
             operation_id="PID参数格式化与双重表示",

             description="将PID参数进行格式化处理，同时提供标准形式和经典控制形式的双重表示，便于不同应用场景使用")
async def format_pid_parameters(params: PIDParameters):
    """
    **PID参数格式化与双重表示**
    
    对输入的PID参数进行标准化格式处理，同时提供现代标准格式和经典控制格式的双重表示。
    
    **功能特性：**
    - 数值精度标准化（小数点后6位）
    - 同时输出标准PID和经典控制两种格式
    - 自动处理特殊值（无穷大、零值等）
    - 参数有效性初步检查
    
    **输出格式：**
    - standard: {kp, ki, kd} - 现代PID控制器标准格式
    - classical: {proportional_band, integral_time, derivative_time} - 传统工业控制格式
    
    **应用场景：**
    - 参数标准化处理
    - 多系统兼容性准备
    - 参数文档生成
    - 控制器配置导出
    
    **注意事项：**
    - 对于无穷大值会标记为null
    - 保持原始参数的数学关系
    - 便于参数审核和验证
    """
    try:
        formatted = PIDConverter.format_pid_parameters(
            params.kp, params.ki, params.kd, include_classical=True
        )
        
        return ConversionResponse(
            success=True,
            message="参数格式化成功",
            data=formatted
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"格式化失败: {str(e)}")


@router.post("/validate-parameters", 
             response_model=ValidationResponse,
             summary="PID参数有效性验证",
             operation_id="PID参数有效性验证",

             description="对PID控制器参数进行全面的有效性检查，包括数值范围、稳定性分析等，确保参数的可用性和安全性")
async def validate_pid_parameters(params: PIDParameters):
    """
    **PID参数有效性验证**
    
    对PID控制器参数进行全面的有效性和稳定性检查，确保参数符合控制理论要求。
    
    **验证内容：**
    - **数值有效性**: 检查参数是否为有限数值
    - **范围检查**: 验证参数是否在合理范围内
    - **稳定性分析**: 基本稳定性判断（Kp > 0）
    - **组合合理性**: 参数组合的合理性评估
    
    **验证规则：**
    - Kp ≥ 0 且为有限值
    - Ki ≥ 0 且为有限值
    - Kd ≥ 0 且为有限值
    - 系统稳定性要求 Kp > 0
    
    **返回信息：**
    - 各参数的独立验证结果
    - 系统整体稳定性评估
    - 详细的问题描述和建议
    
    **应用场景：**
    - 参数配置前的安全检查
    - 控制系统调试
    - 参数优化过程验证
    - 系统安全性评估
    """
    try:
        validation = PIDConverter.validate_pid_parameters(
            params.kp, params.ki, params.kd
        )
        
        # 生成验证消息
        issues = []
        if not validation['kp_valid']:
            issues.append("Kp参数无效")
        if not validation['ki_valid']:
            issues.append("Ki参数无效")
        if not validation['kd_valid']:
            issues.append("Kd参数无效")
        if not validation['stable']:
            issues.append("系统可能不稳定 (Kp <= 0)")
            
        message = "所有参数有效" if not issues else f"发现问题: {', '.join(issues)}"
        
        return ValidationResponse(
            **validation,
            message=message
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"验证失败: {str(e)}")


@router.get("/conversion-formulas",
            summary="获取PID参数转换公式",
            operation_id="获取PID参数转换公式",
            description="获取PID标准参数与经典控制参数之间转换的数学公式和详细说明，包含理论基础和注意事项")
async def get_conversion_formulas():
    """
    **获取PID参数转换公式详解**
    
    提供PID控制器参数转换的完整数学公式、理论基础和使用注意事项。
    
    **转换公式组：**
    
    **1. PID → 经典控制：**
    - 比例带: PB(%) = 100 / Kp
    - 积分时间: Ti(s) = Kp / Ki
    - 微分时间: Td(s) = Kd / Kp
    
    **2. 经典控制 → PID：**
    - 比例增益: Kp = 100 / PB(%)
    - 积分增益: Ki = Kp / Ti(s)
    - 微分增益: Kd = Td(s) × Kp
    
    **理论说明：**
    - 比例带反映控制器的放大倍数
    - 积分时间决定消除稳态误差的速度
    - 微分时间影响系统的动态响应特性
    
    **应用价值：**
    - 控制系统设计参考
    - 参数调试理论指导
    - 不同控制器间的参数转换
    - 控制理论教学和培训
    """
    formulas = {
        "pid_to_classical": {
            "proportional_band": "PB(%) = 100 / Kp",
            "integral_time": "Ti(s) = Kp / Ki",
            "derivative_time": "Td(s) = Kd / Kp"
        },
        "classical_to_pid": {
            "kp": "Kp = 100 / PB(%)",
            "ki": "Ki = Kp / Ti(s)",
            "kd": "Kd = Td(s) * Kp"
        },
        "notes": [
            "比例带PB表示控制器输出100%变化时对应的过程变量变化百分比",
            "积分时间Ti表示积分作用达到比例作用同样效果所需的时间",
            "微分时间Td表示微分作用提前的时间量",
            "当Ki=0时，积分时间为无穷大(纯比例或PD控制)",
            "当Kp=0时，系统通常不稳定"
        ]
    }
    
    return {
        "success": True,
        "message": "转换公式获取成功",
        "data": formulas
    }


@router.get("/examples",
            summary="获取PID参数转换示例",
            operation_id="获取PID参数转换示例",

            description="获取典型PID控制场景的参数转换示例，包含常见控制器配置和应用说明，便于理解和参考")
async def get_conversion_examples():
    """
    **获取PID参数转换典型示例**
    
    提供工业控制中常见的PID控制器配置示例，包含参数转换前后的对比和应用场景说明。
    
    **示例类型：**
    
    **1. 典型PI控制器**
    - 应用: 温度、压力等过程控制
    - 特点: 无微分作用，避免噪声干扰
    - 适用: 响应要求不高但稳定性要求高的场合
    
    **2. 完整PID控制器** 
    - 应用: 位置、速度等伺服控制
    - 特点: 响应快速，精度高
    - 适用: 需要快速响应和高精度的系统
    
    **3. 纯比例控制器**
    - 应用: 简单的开关控制
    - 特点: 结构简单，调试容易
    - 适用: 稳态精度要求不高的场合
    
    **4. PD控制器**
    - 应用: 防止积分饱和的场合
    - 特点: 响应快但有稳态误差
    - 适用: 积分饱和严重的系统
    
    **价值说明：**
    - 为控制器选型提供参考
    - 快速了解不同控制策略
    - 参数配置的起始点
    - 控制系统设计指导
    """
    examples = [
        {
            "name": "典型PI控制器",
            "pid": {"kp": 2.0, "ki": 0.5, "kd": 0.0},
            "classical": {"proportional_band": 50.0, "integral_time": 4.0, "derivative_time": 0.0},
            "description": "适用于过程控制，无微分作用避免噪声影响"
        },
        {
            "name": "PID控制器",
            "pid": {"kp": 1.5, "ki": 0.3, "kd": 0.08},
            "classical": {"proportional_band": 66.67, "integral_time": 5.0, "derivative_time": 0.053},
            "description": "完整PID控制，适用于需要快速响应的系统"
        },
        {
            "name": "纯比例控制",
            "pid": {"kp": 4.0, "ki": 0.0, "kd": 0.0},
            "classical": {"proportional_band": 25.0, "integral_time": None, "derivative_time": 0.0},
            "description": "最简单的控制方式，适用于稳态精度要求不高的场合"
        },
        {
            "name": "PD控制器",
            "pid": {"kp": 1.0, "ki": 0.0, "kd": 0.1},
            "classical": {"proportional_band": 100.0, "integral_time": None, "derivative_time": 0.1},
            "description": "适用于积分饱和严重的系统"
        }
    ]
    
    return {
        "success": True,
        "message": "转换示例获取成功",
        "data": examples
    }