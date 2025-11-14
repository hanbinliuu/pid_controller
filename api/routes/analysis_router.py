from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Union
from datetime import datetime
import json
import os
import logging

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool, detect_and_visualize
from core.algorithm.ls_pid_autotune_v5 import ModelType
from core.data.real_tsdb_client import query_raw_data
from core.data.real_tsdb_client import query_read_interpolated
from api.routes.util import parse_time_to_milliseconds
from core.utils import pid_converter
from core.utils.pid_converter import process_lists_optimized

import pandas as pd
from core.algorithm.find_high_variability_periods import find_high_variability_periods
from core.algorithm.ktl_simulator import KTLSimulator
import numpy as np

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
            operation_id="IOTDA历史数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data(
        table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        fields: Optional[List[str]] = Query(..., description="测点名", example=[
            "ns=100;s=FIC101A_MV.In_Channel0",  # 控制输出值
            "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值
            "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
    ]),
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
):
    try:
        # 参数验证
        if not table or not table.strip():
            raise HTTPException(
                status_code=400,
                detail="表名参数不能为空"
            )
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 30000  # 1小时前（30秒 * 1000毫秒）
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
        # 兼容可空fields
        required_fields = (list(fields) + ["time"]) if fields is not None else ["time"]
        # 使用新的查询方法
        history_data = _query_tsdb_data(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
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


@router.get("/history-data-zhongkong-raw-data",
            summary="历史数据查询_中控",
            operation_id="历史数据_PID数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data_zhongkong(
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1761357384979, "2025-01-01 12:00:00", "2025-01-01T12:00:00",
                                                      "2025-01-01"]),
        end_time: Union[int, str] = Query(None,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1761457384979, "2025-01-02 12:00:00", "2025-01-02T12:00:00",
                                                    "2025-01-02"])
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
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 30000  # 1小时前（30秒 * 1000毫秒）
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
        required_fields.append("time")
        # 使用新的查询方法
        history_data = _query_tsdb_data(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms
        )
        print(history_data)
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

@router.get("/history-data-zhongkong",
            summary="历史插值数据查询_中控",
            operation_id="历史插值数据查询_中控",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_zhongkong_interpolated(
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1761357384979, "2025-01-01 12:00:00", "2025-01-01T12:00:00",
                                                      "2025-01-01"]),
        end_time: Union[int, str] = Query(None,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1761457384979, "2025-01-02 12:00:00", "2025-01-02T12:00:00",
                                                    "2025-01-02"]),
        is_filter: bool = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[True]),
):
    if end_time is None:
        end_time = int(datetime.now().timestamp() * 1000)

    if start_time is None:
        start_time = end_time - 30000  # 1小时前（30秒 * 1000毫秒）
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
            end_time=end_time_ms,
            is_filter=is_filter
        )
        # print(history_data)
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
            summary="仿真系统原始点位数据查询",
            operation_id="仿真系统原始点位数据查询",
            description="查询指定设备在指定时间范围内的仿真系统原始数据，支持多种时间格式")
async def get_point_history_data(
        table: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        fields: Optional[List[str]] = Query(..., description="测点名", example=[
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]),
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        limit: int = Query(..., description="数据条数",
                           examples=[1500])
):
    try:
        # # 参数验证
        # if not table or not table.strip():
        #     raise HTTPException(
        #         status_code=400,
        #         detail="表名参数不能为空"
        #     )
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 30000  # 1小时前（30秒 * 1000毫秒）
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
            fields=(["time"] + (fields or [])),
            start_time=start_time_ms,
            end_time=end_time_ms,
            limit=limit
        )
        # history_data = json.dumps(result, ensure_ascii=False, indent=2)

        # 格式化响应数据
        response_data = {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(result.values or []),
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


@router.get("/temperature-analysis",
            summary="温度曲线分析",
            operation_id="温度曲线分析",
            description="分析温度曲线的控制性能，包括上升时间、超调量、稳态误差等指标")
async def analyze_temperature(
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
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        is_filter: bool = Query(True, description="是否过滤数据",
                                examples=[True]),
        is_lambda: bool = Query(False, description="是否增加lambda整定建议",
                                      examples=[False]),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=["FOPDT","FO","SOPDT","SO","FO_INTEGRATOR","SO_INTEGRATOR"])
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
            end_time=end_time_ms,
            is_filter=is_filter
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
        optimization_result = optimization_tool._run(json.dumps(history_data),is_lambda,model_type)

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

@router.get("/tuning-windows",
            summary="常规整定自动筛选时间区间",
            operation_id="常规整定自动筛选时间区间",
            description="自动识别温度曲线中高波动时段，输出适合经典整定分析的时间窗口列表")
async def get_tuning_windows(
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[30, 60]),
        variability_threshold: float = Query(0.8, description="波动性阈值分位数(0-1)", examples=[0.8]),
        analyst_column: Optional[str] = Query("pv", description="用于波动判断的列名", examples=["pv", "mv", "sv"]),
        window_sec: int = Query(60, description="插值采样间隔（分钟）", examples=[1, 60]),
        is_filter: bool = Query(False, description="是否对历史数据进行优化过滤（按最新参数）", examples=[False])
):
    """
    根据历史数据自动筛选适合常规整定的分析时间区间：
    - 计算温度(PV)在滑动窗口内的方差，识别高波动区间
    - 每个窗口附带 group_key = "{pb}_{ti}_{td}_{sv}", 用于后续分组分析
    """
    try:
        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24*60*60*1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段（与现有分析接口保持一致）
        table = "PID_FEP_Gateway_Device_001default"
        required_fields = [
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]

        # 查询历史插值数据（数据访问层负责分页与解析）
        db = get_default_database()
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=is_filter,
            window = window_sec
        )
        if not history_data:
            return {
                "status": "success",
                "table": table,
                "start_time": start_time,
                "end_time": end_time,
                "total_windows": 0,
                "windows": []
            }

        # 构建DataFrame用于窗口筛选与分组键计算
        df = pd.DataFrame(history_data)
        column = analyst_column or "pv"
        if "timestamp" not in df.columns or column not in df.columns:
            raise HTTPException(status_code=500, detail=f"历史数据缺少必要字段: timestamp 或 {column}")

        # 构建分析序列（索引为datetime）
        ts_index = pd.to_datetime(df["timestamp"], unit="ms")
        series = pd.Series(df[column].values, index=ts_index)

        # 高波动窗口识别
        high_windows = find_high_variability_periods(
            series,
            window_size=window_size,
            step_size=step_size,
            variability_threshold=variability_threshold
        )

        # 生成窗口输出，附加group_key（取窗口内最后一条记录的参数值）
        windows_out = []
        for win in high_windows:
            start_dt = win.get("start_time")
            end_dt = win.get("end_time")
            start_ms = int(start_dt.timestamp() * 1000) if start_dt is not None else None
            end_ms = int(end_dt.timestamp() * 1000) if end_dt is not None else None

            win_df = df[(df["timestamp"] >= start_ms) & (df["timestamp"] <= end_ms)] if start_ms is not None and end_ms is not None else df
            if len(win_df) > 0:
                last = win_df.iloc[-1]
                pb = last.get("pb")
                ti = last.get("ti")
                td = last.get("td")
                sv = last.get("sv")
                group_key = f"{pb}_{ti}_{td}_{sv}"
                kp = last.get("kp")
                ki = last.get("ki")
                kd = last.get("kd")
            else:
                group_key = None
                kp = ki = kd = None

            var = float(win.get("variance", 0.0))
            std_val = float(win.get("std", 0.0))
            # step_deg = float(win.get("step_degree", 0.0))
            windows_out.append({
                "start_timestamp": start_ms,
                "end_timestamp": end_ms,
                "variance": var,
                "std": std_val,
                # "step_degree": step_deg,
                "group_key": group_key,
                "last_pid": {"kp": kp, "ki": ki, "kd": kd}
            })

        # 选取标准差最大的窗口
        std_max_window = None
        if windows_out:
            try:
                std_max_window = max(windows_out, key=lambda w: w.get("std", 0.0))
            except Exception:
                std_max_window = windows_out[0]

        return {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "variability_threshold": variability_threshold,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": len(windows_out),
            "std_max_window": std_max_window
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时间区间筛选失败: {str(e)}")


@router.get("/step-response-windows",
            summary="阶跃响应时间窗口获取",
            operation_id="获取含有阶跃响应的时间窗口",
            description="基于阶跃响应检测自动识别并筛选高质量参数辨识窗口，专用于FOPDT模型参数辨识")
async def get_step_response_windows(
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[10, 30]),
        step_threshold: float = Query(0.05, description="阶跃检测阈值（占输入范围的百分比）", ge=0.01, le=0.5),
        min_response_ratio: float = Query(0.1, description="最小响应比例（响应幅值/输入变化）", ge=0.05, le=1.0),
        confidence_min: float = Query(0.5, description="最小置信度要求（0-1）", ge=0, le=1),
        analyst_column: Optional[str] = Query("pv", description="用于分析的列名", examples=["pv", "mv", "sv"]),
        window_sec: int = Query(60, description="插值采样间隔（分钟）", examples=[1, 60]),
        is_filter: bool = Query(False, description="是否对历史数据进行优化过滤", examples=[False])
):
    """
    基于阶跃响应检测的专用时间窗口获取接口
    
    **功能说明:**
    - 在历史数据中识别含有明显阶跃响应的时间窗口
    - 通过置信度过滤确保数据质量
    - 返回的每个窗口都包含完整的阶跃响应特征信息
    - 特别适用于FOPDT等模型的参数辨识
    
    **返回窗口信息:**
    - start_time / end_time: 窗口时间范围（毫秒）
    - step_detected: 是否检测到阶跃
    - confidence: 置信度评分（0-1）
    - response_magnitude: 响应幅值
    - response_ratio: 响应比例
    - rise_time: 上升时间（秒）
    - settling_time: 稳定时间（秒）
    - group_key: 参数分组键
    - last_pid: 窗口内最后的PID参数
    - recommendation: 推荐等级（优秀/良好/可接受/不推荐）
    """
    try:
        from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier
        
        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24*60*60*1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        table = "PID_FEP_Gateway_Device_001default"
        required_fields = [
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]

        # 查询历史数据
        db = get_default_database()
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=is_filter,
            window=window_sec
        )
        if not history_data or len(history_data) < 20:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行阶跃响应检测"
            )

        # 构建DataFrame
        df = pd.DataFrame(history_data)
        column = analyst_column or "pv"
        if "timestamp" not in df.columns or column not in df.columns:
            raise HTTPException(status_code=500, detail=f"历史数据缺少必要字段: timestamp 或 {column}")

        if "mv" not in df.columns:
            raise HTTPException(status_code=500, detail="历史数据缺少MV字段")

        # 生成滑动窗口
        timestamps = np.array(df["timestamp"].values, dtype=float)
        t_sec = (timestamps - timestamps[0]) / 1000.0  # 转换为相对秒数
        
        window_size_sec = window_size * 60
        step_size_sec = step_size * 60
        dt = float(t_sec[1] - t_sec[0]) if len(t_sec) > 1 else 1.0
        
        window_size_points = int(window_size_sec / dt) if dt > 0 else 120
        step_size_points = int(step_size_sec / dt) if dt > 0 else 10
        
        windows = []
        for i in range(0, len(t_sec) - window_size_points, max(1, step_size_points)):
            window_end_idx = min(i + window_size_points, len(t_sec) - 1)
            if window_end_idx - i < 20:
                continue
            
            windows.append({
                'start_idx': i,
                'end_idx': window_end_idx,
                'start_time': int(timestamps[i]),
                'end_time': int(timestamps[window_end_idx])
            })
        
        # 对每个窗口进行阶跃检测
        qualified_windows = []
        for win in windows:
            start_idx = win['start_idx']
            end_idx = win['end_idx']
            
            t_win = t_sec[start_idx:end_idx+1]
            y_win = np.array(df[column].values[start_idx:end_idx+1], dtype=float)
            u_win = np.array(df["mv"].values[start_idx:end_idx+1], dtype=float)
            
            # 检测阶跃响应
            step_result = SystemIdentifier.detect_step_response_in_window(
                t_window=t_win,
                y_window=y_win,
                u_window=u_win,
                step_threshold=step_threshold,
                response_ratio=min_response_ratio
            )
            
            if step_result['has_step'] and step_result['confidence'] >= confidence_min:
                confidence = step_result['confidence']
                if confidence >= 0.85:
                    recommendation = "优秀"
                elif confidence >= 0.70:
                    recommendation = "良好"
                elif confidence >= 0.50:
                    recommendation = "可接受"
                else:
                    recommendation = "不推荐"
                
                # 获取窗口内的PID参数
                win_df = df.iloc[start_idx:end_idx+1]
                if len(win_df) > 0:
                    last = win_df.iloc[-1]
                    pb = last.get("pb")
                    ti = last.get("ti")
                    td = last.get("td")
                    sv = last.get("sv")
                    group_key = f"{pb}_{ti}_{td}_{sv}"
                    kp = last.get("kp")
                    ki = last.get("ki")
                    kd = last.get("kd")
                else:
                    group_key = None
                    kp = ki = kd = None
                
                qualified_window = {
                    'start_time': win['start_time'],
                    'end_time': win['end_time'],
                    'step_detected': step_result['has_step'],
                    'step_idx': int(step_result['step_idx']),
                    'response_magnitude': float(step_result['response_magnitude']),
                    'response_ratio': float(step_result['response_ratio']),
                    'rise_time': float(step_result['rise_time']),
                    'settling_time': float(step_result['settling_time']),
                    'confidence': float(step_result['confidence']),
                    'recommendation': recommendation,
                    'group_key': group_key,
                    'last_pid': {"kp": kp, "ki": ki, "kd": kd}
                }
                qualified_windows.append(qualified_window)
        
        # 选择最优窗口
        optimal_window = None
        if qualified_windows:
            optimal_window = max(qualified_windows, key=lambda x: x['confidence'])
        
        return {
            "status": "success",
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "step_threshold": step_threshold,
                "min_response_ratio": min_response_ratio,
                "confidence_min": confidence_min,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": len(windows),
            "qualified_windows": qualified_windows,
            "analysis_summary": {
                "total_examined": len(windows),
                "with_step_response": len(qualified_windows),
                "optimal_window": optimal_window
            }
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"阶跃响应窗口获取失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"阶跃响应窗口获取失败: {str(e)}")


@router.get("/auto-select-windows",
            summary="自动筛选参数辨识时间区间",
            operation_id="自动筛选时间窗口",
            description="智能识别含有阶跃响应的高质量时间窗口，适用于FOPDT参数辨识")
async def auto_select_time_windows(
    start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
    end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
    window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
    step_size: int = Query(10, description="滑动步长（分钟）", examples=[10, 30]),
    min_confidence: float = Query(0.5, description="最小置信度要求（0-1）", ge=0, le=1),
    step_threshold: float = Query(0.05, description="阶跃检测阈值（0-1）", ge=0, le=1),
    min_response_ratio: float = Query(0.1, description="最小响应比例（0-1）", ge=0, le=1)
):
    """
    自动筛选适合参数辨识的时间区间
    
    **功能说明:**
    - 自动识别含有明显阶跃响应的时间窗口
    - 综合评估输入信号、输出响应、响应特征
    - 返回评分最高的最优窗口
    
    **返回窗口信息:**
    - start_time / end_time: 窗口时间范围（毫秒）
    - step_detected: 是否检测到阶跃
    - confidence: 置信度评分（0-1）
    - response_magnitude: 响应幅值
    - response_ratio: 响应比例
    - rise_time: 上升时间（秒）
    - settling_time: 稳定时间（秒）
    - recommendation: 推荐等级（优秀/良好/可接受/不推荐）
    """
    try:
        from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier
        
        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24 * 60 * 60 * 1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        table = "PID_FEP_Gateway_Device_001default"
        required_fields = [
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]

        # 查询历史数据
        db = get_default_database()
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=False,
            window=1
        )
        if not history_data or len(history_data) < 10:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行时间窗口筛选"
            )

        # 调用自动筛选方法
        result = SystemIdentifier.auto_select_time_windows(
            history_data=history_data,
            window_size=window_size,
            step_size=step_size,
            min_response_ratio=min_response_ratio,
            step_threshold=step_threshold,
            confidence_min=min_confidence
        )
        
        # 提取筛选结果中的最优窗口
        optimal_window = result.get("analysis_summary", {}).get("optimal_window") if result.get("status") == "success" else None
        
        if not optimal_window:
            raise HTTPException(
                status_code=404,
                detail="未找到符条件的时间窗口。请检查时间范围、上基门槛或参数配置是否合理。"
            )
        
        return {
            "status": "success",
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "step_threshold": step_threshold,
                "min_response_ratio": min_response_ratio,
                "min_confidence": min_confidence
            },
            "total_windows": result.get("total_windows", 0),
            "qualified_windows_count": len(result.get("qualified_windows", [])),
            "optimal_window": optimal_window,
            "analysis_summary": result.get("analysis_summary", {})
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动筛选时间窗口失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"自动筛选时间窗口失败: {str(e)}")


@router.get("/detect_and_visualize",
            summary="数据状态识别",
            operation_id="数据状态识别",
            description="智能识别时间区间数据状态（稳态、非稳态）")
async def auto_detect_and_visualize(
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式")
):
    try:
        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24 * 60 * 60 * 1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        table = "PID_FEP_Gateway_Device_001default"
        required_fields = [
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]

        # 查询历史数据
        db = get_default_database()
        history_data = _query_tsdb_data_zhongkong(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=False,
            window=1
        )
        if not history_data or len(history_data) < 10:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行时间窗口筛选"
            )

        # 调用自动筛选方法
        result = detect_and_visualize(history_data)

        return {
            "status": "success",
            "start_time": start_time,
            "end_time": end_time,
            "result": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")

@router.get("/ktl-simulation",
            summary="基于KTL参数生成仿真模型曲线",
            operation_id="KTL仿真曲线生成",
            description="根据K(增益)、T(时间常数)、L(纯滞后)参数生成一阶惯性加纯滞后(FOPDT)模型的阶跃响应曲线")
async def generate_ktl_simulation(
        K: float = Query(..., description="系统增益", examples=[1.0, 2.5]),
        T: float = Query(..., description="时间常数(秒)", examples=[30.0, 60.0]),
        L: float = Query(0.0, description="纯滞后时间(秒)", examples=[0.0, 5.0]),
        step_value: float = Query(1.0, description="阶跃输入幅值", examples=[1.0, 10.0]),
        duration: float = Query(600.0, description="仿真时长(秒)", examples=[300.0, 600.0]),
        dt: float = Query(1.0, description="采样时间间隔(秒)", examples=[0.1, 1.0]),
        initial_output: float = Query(0.0, description="初始输出值", examples=[0.0]),
        with_pid: bool = Query(False, description="是否生成PID闭环响应", examples=[False]),
        Kp: Optional[float] = Query(None, description="PID比例系数", examples=[1.0]),
        Ki: Optional[float] = Query(None, description="PID积分系数", examples=[0.1]),
        Kd: Optional[float] = Query(None, description="PID微分系数", examples=[0.01]),
        setpoint: Optional[float] = Query(None, description="PID设定值", examples=[100.0]),
        save_plot: bool = Query(True, description="是否保存图片", examples=[True])
):
    """
    基于KTL参数生成FOPDT模型仿真曲线
    
    **功能说明:**
    - 生成一阶惯性加纯滞后(FOPDT)模型的阶跃响应曲线
    - 支持开环阶跃响应和PID闭环响应
    - 自动计算性能指标（上升时间、调节时间、超调量等）
    
    **FOPDT模型:**
    传递函数: G(s) = K * exp(-L*s) / (T*s + 1)
    - K: 系统增益（输出变化/输入变化）
    - T: 时间常数（系统响应速度）
    - L: 纯滞后时间（输入到输出的延迟）
    """
    try:
        plot_path = None
        
        if with_pid:
            # 生成PID闭环响应
            if Kp is None or Ki is None or Kd is None or setpoint is None:
                raise HTTPException(
                    status_code=400,
                    detail="生成PID闭环响应时必须提供Kp, Ki, Kd和setpoint参数"
                )
            
            result = KTLSimulator.generate_pid_response(
                K=K,
                T=T,
                L=L,
                Kp=Kp,
                Ki=Ki,
                Kd=Kd,
                setpoint=setpoint,
                duration=duration,
                dt=dt
            )
            
            # 保存图片
            if save_plot:
                plot_path = KTLSimulator.save_plot(
                    data=result,
                    simulation_type="closed_loop"
                )
            
            return {
                "status": "success",
                "simulation_type": "pid_closed_loop",
                "data": result,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path
            }
        else:
            # 生成开环阶跃响应
            result = KTLSimulator.generate_fopdt_response(
                K=K,
                T=T,
                L=L,
                step_value=step_value,
                duration=duration,
                dt=dt,
                initial_output=initial_output
            )
            
            # 计算性能指标
            metrics = KTLSimulator.calculate_performance_metrics(
                t=result["time"],
                y=result["output"],
                step_value=step_value,
                K=K
            )
            
            # 保存图片
            if save_plot:
                plot_path = KTLSimulator.save_plot(
                    data=result,
                    simulation_type="open_loop"
                )
            
            return {
                "status": "success",
                "simulation_type": "open_loop_step",
                "data": result,
                "performance_metrics": metrics,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path
            }
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KTL仿真生成失败: {str(e)}")

@router.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": "analysis-tools",
        "timestamp": datetime.now().isoformat()
    }

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


# 查询时序数据-中控仿真测点
def _query_tsdb_data_zhongkong(db: str,
                               table_name: str,
                               required_fields: List[str],
                               start_time: int,
                               end_time: int,
                               tags: Optional[Dict[str, str]] = None,
                               window: int = 1,
                               is_filter:Optional[bool]=True
                               ) -> List[Dict]:
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
        window=window,
        continuation_point=None
    )
    # print(response)
    columns = response.columns or []
    values = response.values
    if not values:
        return []
    latest_value = values[-1]
    latest_pb = latest_value[3]
    latest_ti = latest_value[2]
    latest_td = latest_value[5]
    latest_sv = latest_value[1]

    if  (is_filter is None) or is_filter:
        filter_values=process_lists_optimized(values)[0]
    else:
        filter_values=values
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
    over_time = datetime.now().timestamp()
    logger.info(f"查询耗时：{over_time-first_time}")
    return history_data


# 固定 pid值与目标温度，实时数据查询方法
def _query_tsdb_data(db: str,
                     table_name: str,
                     required_fields: List[str],
                     start_time: int,
                     end_time: int,
                     tags: Optional[Dict[str, str]] = None) -> List[Dict]:
    """查询时序数据，但使用传入的PID参数覆盖查询结果"""
    # 定义仅查询必要的字段（不包括PID参数）
    query_fields = [field for field in required_fields if field not in [
        "ns=100;s=FIC101A_MV.In_Channel0",  # mv
        "ns=100;s=FIC101A_PV.In_Channel0",  # 实时值  pv
        "ns=100;s=FIC101A_SV.In_Channel0",  # 设定值  sv
        "ns=100;s=FIC101A_PB.In_Channel0",  # 比例带  pb
        "ns=100;s=FIC101A_TI.In_Channel0",  # 积分参数 ti
        "ns=100;s=FIC101A_TD.In_Channel0"  # 微分参数 td
    ]]
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
    response = query_raw_data(db=db, table=table_name, fields=required_fields, start_time=start_time,
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
                    elif column == "ns=100;s=FIC101A_MV.In_Channel0":
                        record["mv"] = value_row[i]
                    elif column == "ns=100;s=FIC101A_PV.In_Channel0":
                        record["pv"] = value_row[i]
                    elif column == "ns=100;s=FIC101A_SV.In_Channel0":
                        record["sv"] = value_row[i]
                    elif column == "ns=100;s=FIC101A_PB.In_Channel0":
                        record["pb"] = value_row[i]
                    elif column == "ns=100;s=FIC101A_TI.In_Channel0":
                        record["ti"] = value_row[i]
                    elif column == "ns=100;s=FIC101A_TD.In_Channel0":
                        record["td"] = value_row[i]
                    else:
                        record[column] = value_row[i]

            # 确保包含查询字段的默认值
            for field in query_fields:
                # record["temperature"] = record[field]
                if field not in record:
                    record[field] = None

            history_data.append(record)
    over_time = datetime.now().timestamp()
    logger.info(f"总耗时: {begin_time} - {over_time}")
    return history_data


def _plot_history_data(history_data: List[Dict], table_name: str, 
                       start_time: Union[int, str], end_time: Union[int, str]) -> Optional[str]:
    """
    绘制历史数据曲线并保存为图片
    
    Args:
        history_data: 历史数据列表，包含timestamp, pv, mv, sv等字段
        table_name: 设备表名
        start_time: 开始时间
        end_time: 结束时间
        
    Returns:
        保存的图片路径，如果失败则返回None
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # 非交互式后端
        import matplotlib.pyplot as plt
        
        # 配置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        # 提取数据
        timestamps = []
        pv_values = []
        mv_values = []
        sv_values = []
        
        for record in history_data:
            if 'timestamp' in record:
                # 将毫秒时间戳转换为相对秒数
                timestamps.append(record['timestamp'])
                pv_values.append(record.get('pv', 0.0))
                mv_values.append(record.get('mv', 0.0))
                sv_values.append(record.get('sv', 0.0))
        
        if len(timestamps) == 0:
            print("无有效数据点，跳过绘图")
            return None
        
        # 转换时间为相对秒数
        t0 = timestamps[0]
        t_relative = [(t - t0) / 1000.0 for t in timestamps]
        
        # 创建3个子图网格（垂直排列）
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
        
        # 子图1: PV (过程变量)
        ax1.plot(t_relative, pv_values, 'b-', linewidth=2, label='PV (实际值)', alpha=0.8)
        ax1.set_ylabel('PV (过程变量)', fontsize=12, color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper right', fontsize=10)
        ax1.set_title('过程变量 (PV)', fontsize=11, fontweight='bold')
        
        # 子图2: SV (设定值)
        ax2.plot(t_relative, sv_values, 'g-', linewidth=2, label='SV (设定值)', alpha=0.8)
        ax2.set_ylabel('SV (设定值)', fontsize=12, color='green')
        ax2.tick_params(axis='y', labelcolor='green')
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right', fontsize=10)
        ax2.set_title('设定值 (SV)', fontsize=11, fontweight='bold')
        
        # 子图3: MV (操纵量)
        ax3.plot(t_relative, mv_values, 'r-', linewidth=2, label='MV (阀门开度)', alpha=0.8)
        ax3.set_xlabel('时间 (秒)', fontsize=12)
        ax3.set_ylabel('MV (操纵量)', fontsize=12, color='red')
        ax3.tick_params(axis='y', labelcolor='red')
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc='upper right', fontsize=10)
        ax3.set_title('操纵量 (MV)', fontsize=11, fontweight='bold')
        
        # 总标题
        fig.suptitle(f'设备历史数据曲线\n设备: {table_name} | 时间: {start_time} ~ {end_time}', 
                     fontsize=14, fontweight='bold', y=0.995)
        
        plt.tight_layout()
        
        # 保存图片
        plot_dir = os.path.join(os.getcwd(), "data", "plots")
        os.makedirs(plot_dir, exist_ok=True)
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_filename = f"history_data_{timestamp_str}.png"
        plot_path = os.path.join(plot_dir, plot_filename)
        
        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        return plot_path
        
    except Exception as e:
        print(f"❌ 绘图失败: {e}")
        import traceback
        traceback.print_exc()
        return None
