from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, validator
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
import json
import re
import os
import logging

from torch.optim.optimizer import required

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool
from core.data.mock_tsdb_client import query_raw_data
from core.data.real_tsdb_client import query_read_interpolated
from api.routes.util import parse_time_to_milliseconds
from core.utils import pid_converter
from core.utils.pid_converter import process_lists_optimized

router = APIRouter()
logger = logging.getLogger(__name__)


def get_default_database() -> str:
    """
    获取默认数据库名称，优先从环境变量读取
    
    Returns:
        str: 数据库名称
    """
    return os.getenv('DEFAULT_TSDB_DATABASE', 'platform')


"""
**获取设备历史数据 - HistoryDataTool**

从时序数据库(TSDB)中获取指定设备在特定时间范围内的历史数据。

**时间格式支持：**
- 毫秒时间戳: 1640995200000
- 秒时间戳: 1640995200
- 标准格式: '2022-01-01 12:00:00'
- ISO 8601格式: '2022-01-01T12:00:00'
- 日期格式: '2022-01-01'

**参数验证：**
- kp > 0 (比例系数必须为正数)
- ki >= 0 (积分系数不能为负数)
- kd >= 0 (微分系数不能为负数)

**返回数据：**
- timestamp: 时间戳（毫秒）
- temperature: 实际温度值
- target_temp: 目标温度设定值
- kp, ki, kd: PID控制参数
- control_period: 控制周期
- max_duty: 最大占空比
"""


@router.get("/history-data",
            summary="历史数据查询",
            operation_id="历史数据+PID数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data(
        table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        field: str = Query(..., description="测点名", example="ns=100;s=FI15001.In_Channel0"),
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        kp: float = Query(..., description="比例系数", example=1.5, gt=0),
        ki: float = Query(..., description="积分系数", example=0.05, ge=0),
        kd: float = Query(..., description="微分系数", example=0.08, ge=0),
        target_temp: float = Query(..., description="目标温度", example=30)
):
    try:
        # 参数验证
        if not table or not table.strip():
            raise HTTPException(
                status_code=400,
                detail="表名参数不能为空"
            )

        # 时间格式转换和验证
        try:
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"时间格式错误: {str(e)}"
            )

        # 验证时间范围
        if start_time_ms >= end_time_ms:
            raise HTTPException(
                status_code=400,
                detail="开始时间必须小于结束时间"
            )

        # 验证PID参数
        if kp <= 0:
            raise HTTPException(
                status_code=400,
                detail="比例系数kp必须大于0"
            )

        if ki < 0:
            raise HTTPException(
                status_code=400,
                detail="积分系数ki不能为负数"
            )

        if kd < 0:
            raise HTTPException(
                status_code=400,
                detail="微分系数kd不能为负数"
            )

        # 定义需要查询的字段
        # required_fields = [
        #     "temperature",
        #     "control_period",
        #     "max_duty"
        # ]

        # 使用环境变量中的数据库名
        db = get_default_database()

        # 使用新的查询方法
        history_data = _query_tsdb_data(
            db=db,
            table_name=table,
            required_fields=[field],
            start_time=start_time_ms,
            end_time=end_time_ms,
            kp=kp,
            ki=ki,
            kd=kd,
            target_temp=target_temp
        )

        # 格式化响应数据
        response_data = {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(history_data),
            "data": history_data
        }

        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


"""
**获取设备历史数据 - HistoryDataTool**

从时序数据库(TSDB)中获取指定设备在特定时间范围内的历史数据。

**时间格式支持：**
- 毫秒时间戳: 1640995200000
- 秒时间戳: 1640995200
- 标准格式: '2022-01-01 12:00:00'
- ISO 8601格式: '2022-01-01T12:00:00'
- 日期格式: '2022-01-01'

**参数验证：**
- kp > 0 (比例系数必须为正数)
- ki >= 0 (积分系数不能为负数)
- kd >= 0 (微分系数不能为负数)

**返回数据：**
- timestamp: 时间戳（毫秒）
- temperature: 实际温度值
- target_temp: 目标温度设定值
- kp, ki, kd: PID控制参数
- control_period: 控制周期
- max_duty: 最大占空比
"""


@router.get("/history-data-zhongkong",
            summary="历史数据查询_中控",
            operation_id="历史数据_PID数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data_zhongkong(
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1761357384979, "2025-01-01 12:00:00", "2025-01-01T12:00:00",
                                                      "2025-01-01"]),
        end_time: Union[int, str] = Query(...,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1761457384979, "2025-01-02 12:00:00", "2025-01-02T12:00:00",
                                                    "2025-01-02"]),
):
    table = "PID_FEP_Gateway_Device_001default"
    required_fields = [
        "ns=100;s=FIC101A_MV.In_Channel0",  # 控制输出值
        "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值
        "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值
        "ns=100;s=FIC101A_PB.In_Channel0",
        "ns=100;s=FIC101A_TI.In_Channel0",
        "ns=100;s=FIC101A_TD.In_Channel0"
    ]
    try:
        # 参数验证
        if not table or not table.strip():
            raise HTTPException(
                status_code=400,
                detail="表名参数不能为空"
            )

        # 时间格式转换和验证
        try:
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"时间格式错误: {str(e)}"
            )

        # 验证时间范围
        if start_time_ms >= end_time_ms:
            raise HTTPException(
                status_code=400,
                detail="开始时间必须小于结束时间"
            )
        # 使用环境变量中的数据库名
        db = get_default_database()

        # 使用新的查询方法
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms
        )

        # 格式化响应数据
        response_data = {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(history_data),
            "data": history_data
        }

        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


@router.get("/point_history_data",
            summary="原始测点仿真系统数据查询",
            operation_id="原始测点仿真系统数据查询",
            description="查询指定设备在指定时间范围内的原始仿真数据，支持多种时间格式")
async def get_point_history_data(
        table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        fields: Optional[List[str]] = Query(...,required=False, description="测点名", example="ns=100;s=FI15001.In_Channel0"),
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        limit: int = Query(..., description="数据条数",
                           examples="1500")
):
    try:
        # # 参数验证
        # if not table or not table.strip():
        #     raise HTTPException(
        #         status_code=400,
        #         detail="表名参数不能为空"
        #     )

        # 时间格式转换和验证
        try:
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"时间格式错误: {str(e)}"
            )

        # 验证时间范围
        if start_time_ms >= end_time_ms:
            raise HTTPException(
                status_code=400,
                detail="开始时间必须小于结束时间"
            )

        # 使用环境变量中的数据库名
        db = get_default_database()

        # 使用新的查询方法
        result = query_raw_data(
            db=db,
            table=table,
            fields=["time", fields],
            start_time=start_time_ms,
            end_time=end_time_ms,
            limit=limit,
            use_real_tsdb=True
        )
        # history_data = json.dumps(result, ensure_ascii=False, indent=2)

        # 格式化响应数据
        response_data = {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(result.values),
            "data": {
                "columns": result.columns,
                "values": result.values,
            }
        }

        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


@router.get("/history-data_mock",
            summary="历史数据查询（模拟）",
            operation_id="历史数据查询_模拟",
            description="查询指定设备在指定时间范围内的历史数据（使用模拟数据源）")
async def get_history_data_mock(
        db: str = Query(..., description="数据库名（库名）", example="platform"),
        table: str = Query(..., description="设备名（表名）", example="ns-01f-001"),
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(...,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
):
    """
    **获取设备历史数据 - HistoryDataTool**

    从时序数据库(TSDB)中获取指定设备在特定时间范围内的历史数据。

    **功能说明：**
    - 基于设备名和时间范围的精确查询
    - 自动获取PID控制所需的所有关键字段
    - 智能缺失值填充，确保数据完整性
    - 高效的数据格式处理和结构化输出

    **数据字段：**
    - timestamp: 时间戳（毫秒）
    - temperature: 实际温度值
    - target_temp: 目标温度设定值
    - kp, ki, kd: PID控制参数
    - control_period: 控制周期
    - max_duty: 最大占空比

    **返回格式：**
    - status: 查询结果状态
    - totalRecords: 数据记录总数
    - data: 完整的历史数据数组

    **应用场景：**
    - PID控制系统分析前的数据准备
    - 历史趋势分析和性能评估
    - 控制算法优化的数据基础
    - 故障诊断和系统调试
    """
    # 时间格式转换和验证
    try:
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"时间格式错误: {str(e)}"
        )
    try:
        # 使用新的查询方法
        history_data = _query_tsdb_data_mock(db=db, table_name=table, start_time=start_time_ms, end_time=end_time_ms)

        # 格式化响应数据
        response_data = {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(history_data),
            "data": history_data
        }

        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


@router.get("/temperature-analysis",
            summary="温度曲线分析",
            operation_id="温度曲线分析",
            description="分析温度曲线的控制性能，包括上升时间、超调量、稳态误差等指标")
async def analyze_temperature(
        # table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        # field:  str =Query(..., description="测点名", example="ns=100;s=FI15001.In_Channel0"),
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(...,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
):
    """
    **温度曲线智能分析 - TemperatureAnalysisTool**
    
    使用先进的控制理论算法，对PID控制系统的温度响应特性进行全面、精确的定量分析。
    
    **分析指标：**
    
    **1. 动态响应特性：**
    - 上升时间(Rise Time): 达到90%目标值的时间
    - 调节时间(Settling Time): 稳定在误差带内的时间
    - 峰值时间(Peak Time): 首次达到最大值的时间
    
    **2. 稳态性能评估：**
    - 超调量(Overshoot): 超出目标值的百分比
    - 稳态误差(Steady State Error): 最终稳态值与目标值的偏差
    - 温度波动: 稳态状态下的温度波动程度
    
    **3. 控制质量评估：**
    - 控制精度: 长期稳定性和精度评估
    - 系统鲁棒性: 对干扰和参数变化的适应性
    - 能耗效率: 控制动作的经济性分析
    
    **输出格式：**
    - 定量化的性能指标数值
    - 直观的性能评级和建议
    - 问题诊断和改进方向
    
    **应用价值：**
    - PID参数优化的科学依据
    - 控制系统性能监控和评估
    - 生产过程优化和效率提升
    - 设备维护和故障预测
    """
    table = "PID_FEP_Gateway_Device_001default"
    required_fields = [
        "ns=100;s=FIC101A_MV.In_Channel0",  # 控制输出值
        "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值
        "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值
        "ns=100;s=FIC101A_PB.In_Channel0",
        "ns=100;s=FIC101A_TI.In_Channel0",
        "ns=100;s=FIC101A_TD.In_Channel0"
    ]
    try:
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"时间格式错误: {str(e)}"
        )
    try:
        # 使用新的查询方法获取数据
        # 使用环境变量中的数据库名
        db = get_default_database()

        # 使用新的查询方法
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms
        )
        if not history_data:
            return {
                "status": "error",
                "table": table,
                "message": "指定时间范围内无数据"
            }

        # 创建温度分析工具实例
        analysis_tool = TemperatureAnalysisTool()

        # 执行分析（传入历史数据列表）
        analysis_result = analysis_tool._run(json.dumps(history_data))

        # 解析分析结果
        try:
            result_data = json.loads(analysis_result)
            return {
                "status": "success",
                "table": table,
                "start_time": start_time,
                "end_time": end_time,
                "analysis_result": result_data
            }
        except json.JSONDecodeError:
            # 如果返回的不是JSON格式（可能是错误信息）
            return {
                "status": "error",
                "table": table,
                "message": analysis_result
            }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"温度分析失败: {str(e)}"
        )


@router.get("/pid-optimization",
            summary="PID参数优化建议",
            operation_id="PID参数优化建议",
            description="基于历史数据分析结果，提供PID参数调整建议")
async def optimize_pid(
        # table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        # field:  str =Query(..., description="测点名", example="ns=100;s=FI15001.In_Channel0"),
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
        #     ,
        # kp: float = Query(..., description="比例系数", example=1.5, gt=0),
        # ki: float = Query(..., description="积分系数", example=0.05, ge=0),
        # kd: float = Query(..., description="微分系数", example=0.08, ge=0),
        # target_temp: float = Query(..., description="目标温度", example=30)
):
    """
    **PID参数智能优化 - PIDOptimizationTool**
    
    运用先进的控制理论和机器学习算法，对PID控制器参数进行智能化优化分析。
    
    **优化策略：**
    
    **1. 数据驱动分析：**
    - 基于历史数据的性能评估
    - 控制效果量化分析
    - 系统特性识别和建模
    
    **2. 参数优化算法：**
    - Ziegler-Nichols经典调试法
    - Cohen-Coon改进算法
    - 现代启发式优化算法
    - 机器学习自适应优化
    
    **3. 多目标优化：**
    - 响应速度与稳定性平衡
    - 控制精度与能耗优化
    - 鲁棒性与性能综合考量

    """
    table = "PID_FEP_Gateway_Device_001default"
    required_fields = [
        "ns=100;s=FIC101A_MV.In_Channel0",  # 控制输出值
        "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值
        "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值
        "ns=100;s=FIC101A_PB.In_Channel0",
        "ns=100;s=FIC101A_TI.In_Channel0",
        "ns=100;s=FIC101A_TD.In_Channel0"
    ]
    try:
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"时间格式错误: {str(e)}"
        )
    try:
        # 使用新的查询方法获取数据
        # 使用环境变量中的数据库名
        db = get_default_database()

        # 使用新的查询方法
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms
        )
        if not history_data:
            return {
                "status": "error",
                "table": table,
                "message": "指定时间范围内无数据"
            }

        # 创建PID优化工具实例
        optimization_tool = PIDOptimizationTool()

        # 执行优化分析（传入历史数据列表）
        optimization_result = optimization_tool._run(json.dumps(history_data))

        # 解析优化结果
        try:
            result_data = json.loads(optimization_result)
            return {
                "status": "success",
                "table": table,
                "start_time": start_time,
                "end_time": end_time,
                "optimization_result": result_data
            }
        except json.JSONDecodeError:
            # 如果返回的不是JSON格式（可能是错误信息）
            return {
                "status": "error",
                "table": table,
                "message": optimization_result
            }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PID优化失败: {str(e)}"
        )


@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "analysis-tools",
        "timestamp": datetime.now().isoformat()
    }


# class HistoryDataRequest(BaseModel):
#     """历史数据工具请求 - 精简版"""
#     table: str = Field(..., description="设备名（表名）", example="ns-01f-001")
#     start_time: int = Field(..., description="开始时间戳（毫秒）", example=1640995200000)
#     end_time: int = Field(..., description="结束时间戳（毫秒）", example=1641081600000)
#
#
# class TemperatureAnalysisRequest(BaseModel):
#     """温度分析工具请求 - 精简版"""
#     table: str = Field(..., description="设备名（表名）", example="ns-01f-001")
#     start_time: int = Field(..., description="开始时间戳（毫秒）", example=1640995200000)
#     end_time: int = Field(..., description="结束时间戳（毫秒）", example=1641081600000)
#
#
# class PIDOptimizationRequest(BaseModel):
#     """PID优化工具请求 - 精简版"""
#     table: str = Field(..., description="设备名（表名）", example="ns-01f-001")
#     start_time: int = Field(..., description="开始时间戳（毫秒）", example=1640995200000)
#     end_time: int = Field(..., description="结束时间戳（毫秒）", example=1641081600000)


def _get_default_value(field: str):
    """获取字段默认值"""
    defaults = {
        "temperature": 25.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "target_temp": 25.0,
        "control_period": 100,
        "max_duty": 100
    }
    return defaults.get(field, 0)


def _query_tsdb_data_mock(db: str, table_name: str, start_time: int, end_time: int,
                          tags: Optional[Dict[str, str]] = None) -> List[Dict]:
    """查询模拟数据的公用方法"""
    # 定义需要查询的字段
    required_fields = [
        "temperature",
        "kp",
        "ki",
        "kd",
        "target_temp",
        "control_period",
        "max_duty"
    ]

    # 构造查询请求
    query_request = {
        "tables": [
            {
                "db": db,
                "table": table_name,
                "fields": required_fields,
                "tags": tags,
                "continuationPoint": None
            }
        ],
        "detail": {
            "startTime": start_time,
            "endTime": end_time,
            "limit": 1500,
            "returnBounds": False
        }
    }

    # 调用时序数据查询接口
    response = query_raw_data(query_request)

    # 检查响应状态
    if response.get("code") != 0:
        raise Exception(f"查询失败: {response.get('message', '未知错误')}")

    # 解析查询结果
    results = response.get("results", [])
    history_data = []

    if results:
        for table_result in results:
            data_points = table_result.get("data", [])
            for data_point in data_points:
                columns = data_point.get("columns", [])
                values = data_point.get("values", [])

                # 将数据转换为字典格式
                for value_row in values:
                    record = {}
                    for i, column in enumerate(columns):
                        if i < len(value_row):
                            if column == "time":
                                record["timestamp"] = value_row[i]
                            else:
                                record[column] = value_row[i]
                    # 确保包含所有必需字段
                    for field in required_fields:
                        if field not in record:
                            record[field] = _get_default_value(field)

                    history_data.append(record)

    return history_data


# 查询时序数据-中控仿真测点
# 查询时序数据-中控仿真测点
def _query_tsdb_data_zhongkong(db: str,
                               table_name: str,
                               required_fields: List[str],
                               start_time: int,
                               end_time: int,
                               tags: Optional[Dict[str, str]] = None) -> List[Dict]:
    first_time = datetime.now().timestamp()

    """
    查询时序数据，根据最新数据（最后一条）的pb、ti、td、sv进行过滤
    只返回与最新参数值相同的历史数据，优化性能
    """
    # 定义仅查询必要的字段（不包括PID参数）
    query_fields = [field for field in required_fields if field not in [
        "ns=100;s=FIC101A_MV.In_Channel0",  # 控制输出值
        "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值  temperature
        "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值  target_temp
        "ns=100;s=FIC101A_PB.In_Channel0",  # 比例带  pb
        "ns=100;s=FIC101A_TI.In_Channel0",  # 积分参数 ti
        "ns=100;s=FIC101A_TD.In_Channel0"  # 微分参数 td
    ]]
    all_records = []
    response = query_read_interpolated(
        db=db,
        table=table_name,
        fields=required_fields,
        start_time=start_time,
        end_time=end_time,
        tags=tags,
        continuation_point=None
    )

    columns = response.columns or []
    values = response.values
    latest_value = values[-1]
    latest_pb = latest_value[3]
    latest_ti = latest_value[2]
    latest_td = latest_value[5]
    latest_sv = latest_value[1]
    filter_values=process_lists_optimized(values)[0]

    # 解析当前页数据并添加到all_records
    for value_row in filter_values:
        record = {}
        for i, column in enumerate(columns):
            if i < len(value_row):
                if column == "time":
                    record["timestamp"] = value_row[i]
                elif column == "ns=100;s=FIC101A_PV.In_Channel0":
                    record["pv"] = value_row[i]
                elif column == "ns=100;s=FIC101A_SV.In_Channel0":
                    record["sv"] = value_row[i]
                elif column == "ns=100;s=FIC101A_MV.In_Channel0":
                    record["mv"] = value_row[i]
                elif column == "ns=100;s=FIC101A_PB.In_Channel0":
                    record["pb"] = value_row[i]
                elif column == "ns=100;s=FIC101A_TI.In_Channel0":
                    record["ti"] = value_row[i]
                elif column == "ns=100;s=FIC101A_TD.In_Channel0":
                    record["td"] = value_row[i]
                else:
                    record[column] = value_row[i]
        all_records.append(record)
    #     # 数据判断，是否为最新数据
    #     # 过滤数据：只保留参数与最新数据相同的记录
    #     if (record.get("pb") == latest_pb and
    #             record.get("ti") == latest_ti and
    #             record.get("td") == latest_td and
    #             record.get("sv") == latest_sv):
    #         all_records.append(record)
    #     else:
    #         break

    # 解析查询结果
    history_data = []

    # 参数转换
    if all_records:
        for record in all_records:
            # 转换PID参数
            result = pid_converter.convert_pb_to_pid(
                record["pb"],
                record["ti"],
                record["td"]
            )
            # 确保包含查询字段的默认值
            for field in query_fields:
                if field not in record:
                    record[field] = None

            # 添加转换后的PID参数
            record["kp"] = result["kp"]
            record["ki"] = result["ki"]
            record["kd"] = result["kd"]

            history_data.append(record)
        over_time = datetime.now().timestamp()
    logger.info(f"查询耗时：{over_time-first_time}")
    return history_data


# 固定 pid值与目标温度，实时数据查询方法
def _query_tsdb_data(db: str,
                     table_name: str,
                     required_fields: List[str],
                     start_time: int,
                     end_time: int,
                     kp: float,
                     ki: float,
                     kd: float,
                     target_temp: float,
                     tags: Optional[Dict[str, str]] = None) -> List[Dict]:
    """查询时序数据，但使用传入的PID参数覆盖查询结果"""
    # 定义仅查询必要的字段（不包括PID参数）
    query_fields = [field for field in required_fields if field not in ["kp", "ki", "kd", "target_temp"]]
    begin_time = datetime.now().timestamp()

    # 构造查询请求
    query_request = {
        "tables": [
            {
                "db": db,
                "table": table_name,
                "fields": query_fields,
                "tags": tags,
                "continuationPoint": None
            }
        ],
        "detail": {
            "startTime": start_time,
            "endTime": end_time,
            "limit": 1500,
            "returnBounds": False
        }
    }

    # 调用时序数据查询接口
    response = query_read_interpolated(db=db, table=table_name, fields=query_fields, start_time=start_time,
                                       end_time=end_time,
                                       tags=tags)

    # 解析查询结果
    history_data = []

    # 如果查询有结果，处理数据
    if hasattr(response, 'values') and response.values:
        columns = response.columns or []
        values = response.values

        # 将数据转换为字典格式
        for value_row in values:
            record = {}
            for i, column in enumerate(columns):
                if i < len(value_row):
                    if column == "time":
                        record["timestamp"] = value_row[i]
                    else:
                        record[column] = value_row[i]

            # 确保包含查询字段的默认值
            for field in query_fields:
                record["temperature"] = record[field]
                if field not in record:
                    record[field] = None

                    # 使用传入的PID参数覆盖任何查询结果
            record["kp"] = kp
            record["ki"] = ki
            record["kd"] = kd
            record["target_temp"] = target_temp

            history_data.append(record)
    over_time = datetime.now().timestamp()
    logger.info(f"总耗时: {begin_time} - {over_time}")
    return history_data
