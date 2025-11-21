from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Union
from datetime import datetime
import json
import logging

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool, detect_and_visualize, \
    process_query_tsdb_data_interpolated, process_query_tsdb_data_raw
from core.algorithm.ls_pid_autotune_v5 import ModelType
from core.data.real_tsdb_client import get_default_database
from api.routes.time_util import parse_time_to_milliseconds, format_time_to_string

router = APIRouter()
logger = logging.getLogger(__name__)

# 默认字段映射map
DEFAULT_FIELD_MAPPING = {
    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
    "pv": "ns=100;s=FIC101A_PV.In_Channel0",
    "sv": "ns=100;s=FIC101A_SV.In_Channel0",
    "pb": "ns=100;s=FIC101A_PB.In_Channel0",
    "ti": "ns=100;s=FIC101A_TI.In_Channel0",
    "td": "ns=100;s=FIC101A_TD.In_Channel0"
}


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

@router.get("/temperature-analysis",
            summary="大模型整定-温度曲线分析",
            # operation_id="温度曲线分析",
            description="大模型整定-分析温度曲线的控制性能，包括上升时间、超调量、稳态误差等指标")
async def analyze_temperature(
        start_time: Union[int, str] = Query(...,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(...,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        circuit_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"] ),
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
    # 将map解析为一下关系
    #todo 获取设备历史数据

    table = "PID_FEP_Gateway_Device_001default"
    required_fields = DEFAULT_FIELD_MAPPING
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
        history_data = process_query_tsdb_data_interpolated(
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
            summary="大模型整定-PID参数优化建议",
            operation_id="大模型整定-PID参数优化建议",
            description="基于历史数据分析结果，提供PID参数调整建议")
async def optimize_pid(
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        circuit_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/935cf045bd254867bdfeb113c31467da"] ),
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
    required_fields = DEFAULT_FIELD_MAPPING
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
        history_data: List[Dict] = process_query_tsdb_data_interpolated(
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
        optimization_result = optimization_tool._run(history_data=history_data,is_lambda=is_lambda,model_type=model_type)

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


# @router.get("/history-data",
#             summary="历史数据查询",
#             operation_id="IOTDA历史数据查询",
#             description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data(
        circuit_uri: str = Query(..., required=False, description="回路URI",
                                 examples=["/pid_zd/935cf045bd254867bdfeb113c31467da"]),
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
):
    try:
        # 跟进回路信息查询表和字段信息
        table = "PID_FEP_Gateway_Device_001default"
        fields = DEFAULT_FIELD_MAPPING
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
        # 将字段列表转换为字段映射map
        field_list = (list(fields) + ["time"]) if fields is not None else ["time"]
        # 使用字段名作为key，字段路径作为value
        required_fields = {f"field_{i}": field for i, field in enumerate(field_list)}
        # 使用新的查询方法
        history_data = process_query_tsdb_data_raw(
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



def _get_default_value(field: str):
    """获取PID字段默认值"""
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




def _get_model_recommendations(model_type: str) -> Dict[str, str]:
    """
    获取不同模型类型的应用建议
    """
    recommendations = {
        "FOPDT": "适用于大多数工业过程，具有一定滞后特性。建议用于温度、压力等缓变过程",
        "FO": "适用于无明显滞后的一阶系统。响应较快，适合响应速度要求不高的场景",
        "SOPDT": "适用于复杂工业过程（如温度、化学反应）。具有多惯性和滞后特性",
        "SO": "适用于快速响应的二阶系统。无滞后，可能存在超调，需适当调节Lambda",
        "FO_INTEGRATOR": "适用于流量控制、液位控制等积分特性系统。需要较强的反馈",
        "SO_INTEGRATOR": "适用于复杂的双积分过程。需要更大的Lambda值以保证稳定性"
    }
    return {
        "model_description": recommendations.get(model_type, "未知模型类型"),
        "lambda_selection_tip": "可通过调整lambda_val参数：减小使响应快但波动增加，增大使响应慢但更稳定"
    }
