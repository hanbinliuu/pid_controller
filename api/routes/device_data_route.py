import logging
import os
from datetime import datetime
from typing import Optional, List, Union, Dict, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import Field,BaseModel

from api.routes.time_util import parse_time_to_milliseconds
from core.agent.tools import process_query_tsdb_data_interpolated, process_query_tsdb_data_raw
from core.data.bff_model_client import BFFModelClient
from core.data.real_tsdb_client import query_raw_data, get_default_database

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
# IOTDA设备指令批量下发基础URL
IOTDA_BASE_URL = os.getenv(
    "IOTDA_BASE_URL",
    "http://data-engine-iotda-infra-system.sit-cloud.ieccloud.hollicube.com"
)

@router.get("/point_history_data_tsdb",
            summary="时序测点数据查询接口",
            operation_id="时序测点数据查询接口",
            description="查询指定设备在指定时间范围内的测点原始数据，支持多种时间格式")
async def get_point_history_data_tsdb(
        table_name: str = Query(..., description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        fields: Optional[List[str]] = Query(..., description="测点名", example=[
            "ns=100;s=FIC101A_MV.In_Channel0",
            "ns=100;s=FIC101A_PV.In_Channel0",
            "ns=100;s=FIC101A_SV.In_Channel0",
            "ns=100;s=FIC101A_PB.In_Channel0",
            "ns=100;s=FIC101A_TI.In_Channel0",
            "ns=100;s=FIC101A_TD.In_Channel0"
        ]),
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(None, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        limit: int = Query(1500, description="数据条数",
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
            start_time = end_time - 60 * 60 * 1000  # 默认1小时
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
            table=table_name,
            fields=(["time"] + (fields or [])),
            start_time=start_time_ms,
            end_time=end_time_ms,
            limit=limit
        )
        # history_data = json.dumps(result, ensure_ascii=False, indent=2)

        # 格式化响应数据
        response_data = {
            "table": table_name,
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
@router.post("/history-data-raw",
            summary="回路测点数据查询",
            # operation_id="测点数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data_raw(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                              examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1761357384979, "2025-01-01 12:00:00", "2025-01-01T12:00:00",
                                                      "2025-01-01"]),
        end_time: Union[int, str] = Query(None,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1761457384979, "2025-01-02 12:00:00", "2025-01-02T12:00:00",
                                                    "2025-01-02"])

):

    # table = "PID_FEP_Gateway_Device_001default"
    # if not fields:
    #     required_fields = DEFAULT_FIELD_MAPPING
    # else:
    #     required_fields = fields
    # required_fields = DEFAULT_FIELD_MAPPING

    try:
        # 时间默认值：最近2小时
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 2 * 60 * 60 * 1000  # 默认2小时
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
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # 使用新的查询方法
        history_data = process_query_tsdb_data_raw(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms
        )
        logger.info(history_data)
        # 格式化响应数据
        response_data = {
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

@router.get("/history-data-interpolated",
            summary="历史插值数据查询",
            operation_id="历史插值数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_zhongkong_interpolated(
        table: str = Query('PID_FEP_Gateway_Device_001default', description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),

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
        start_time = end_time - 60 * 60 * 1000  # 默认1小时
    table_name="PID_FEP_Gateway_Device_001default"
    if table:
        table_name = table
    required_fields = DEFAULT_FIELD_MAPPING
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
        history_data = process_query_tsdb_data_interpolated(
            db=db,
            table_name=table_name,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=is_filter
        )
        # logger.info(history_data)
        # 格式化响应数据
        response_data = {
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

class DeviceCommand(BaseModel):
    """IOTDA设备指令数据模型"""
    timeout: int = Field(..., description="单条指令超时时间（秒）", example=20)
    object_device_id: str = Field(..., description="设备ID", example="PID_FEP_Gateway_Device_001")
    service_id: str = Field(..., description="服务ID", example="default")
    command_name: str = Field(..., description="命令名称", example="set_property")
    paras: Dict[str, Any] = Field(..., description="命令参数字典", example={"ns=100;s=FIC101A_TD.In_Channel0": 10})

@router.post(
    "/iotda/command/batch",
    operation_id="iotda设备指令批量下发",
    summary="批量下发设备指令（代理透传）",
    description="透传调用 IOTDA 设备指令批量下发接口: POST /iotda-data-engine/device/command/batch"
)
async def send_device_command_batch(
        commands: List[DeviceCommand],
        retryNum: int = 0,
        timeout: int = 20000,
        authorization: Optional[str] = Header(None, description="IOTDA鉴权令牌（可选）")
):
    """
    代理下发设备指令到 IOTDA 系统（批量）。

    Query参数：
    - retryNum: 重试次数（默认0）
    - timeout: 请求整体超时（毫秒，默认20000）

    请求体：设备指令数组
    """
    try:
        url = f"{IOTDA_BASE_URL}/iotda-data-engine/device/command/batch"

        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization

        # 序列化请求体
        payload = [cmd.model_dump() for cmd in commands]

        logger.info(f"调用IOTDA设备指令批量接口: {url} params={{'retryNum': {retryNum}, 'timeout': {timeout}}}")
        logger.debug(f"请求体: {payload}")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                params={"retryNum": retryNum, "timeout": timeout},
                json=payload,
                headers=headers
            )

        logger.info(f"IOTDA接口响应状态: {response.status_code}")

        if response.status_code == 200:
            result = response.json()
            return {
                "message": "指令批量下发成功",
                "data": result
            }
        else:
            logger.error(f"IOTDA接口调用失败: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"IOTDA调用失败: {response.text}"
            )

    except httpx.TimeoutException:
        logger.error("IOTDA接口调用超时")
        raise HTTPException(status_code=408, detail="IOTDA接口调用超时")
    except httpx.ConnectError:
        logger.error("无法连接到IOTDA接口")
        raise HTTPException(status_code=503, detail="无法连接到IOTDA服务")
    except Exception as e:
        logger.error(f"设备指令代理错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"代理服务内部错误: {str(e)}")




