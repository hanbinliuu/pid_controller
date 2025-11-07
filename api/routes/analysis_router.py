from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Union
from datetime import datetime
import json
import os
import logging

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool
from core.algorithm.non_steady_state_detector import NonSteadyStateDetector
from core.data.real_tsdb_client import query_raw_data
from core.data.real_tsdb_client import query_read_interpolated
from api.routes.util import parse_time_to_milliseconds
from core.utils import pid_converter
from core.utils.pid_converter import process_lists_optimized

import pandas as pd
from core.algorithm.find_high_variability_periods import find_high_variability_periods
from core.algorithm.ktl_simulator import KTLSimulator

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
        fields: Optional[List[str]] = Query(..., description="测点名", example=[
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
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
@router.get("/point_history_data",
            summary="原始测点仿真系统数据查询",
            operation_id="原始测点仿真系统数据查询",
            description="查询指定设备在指定时间范围内的原始仿真数据，支持多种时间格式")
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
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        is_filter: bool = Query(True, description="是否过滤数据",
                                examples=[True]),
        is_lambda: bool = Query(False, description="是否增加lambda整定建议",
                                      examples=[False])
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
        optimization_result = optimization_tool._run(json.dumps(history_data),is_lambda)

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
@router.get("/non_steady_data",
            summary="非稳态识别",
            operation_id="非稳态识别",
            description="自动识别非稳态数据区间")
async def get_non_steady_data(
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

        detector = NonSteadyStateDetector()

        # 获取非稳态段起点
        starts = detector.get_non_steady_starts(history_data)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时间区间筛选失败: {str(e)}")


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
    response =  query_raw_data(db=db, table=table_name, fields=required_fields, start_time=start_time,
                                       end_time=end_time,
                                       tags=tags)

    # 检查响应状态
    if isinstance(response, dict) and response.get("code") != 0:
        raise Exception(f"查询失败: {response.get('message', '未知错误')}")

    # 解析查询结果
    results = response.get("results", []) if isinstance(response, dict) else []
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
