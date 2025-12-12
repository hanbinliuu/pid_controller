import logging
from typing import Optional, List, Union, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Header

from api.middleware.exceptions import RuntimeException
from api.services.device_data_service import DeviceDataService, DeviceCommand

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

@router.get("/point_history_data_iotda",
            summary="iotda-测点数据查询接口",
            # operation_id="时序测点数据查询接口",
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
        # 调用Service层查询测点历史数据
        result = DeviceDataService.query_point_history_data_tsdb(
            table_name=table_name,
            fields=fields,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )

@router.get("/history-data-raw",
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
    try:
        # 调用Service层查询原始历史数据
        result = DeviceDataService.query_history_data_raw(
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )

@router.get("/history-data-interpolated",
            summary="历史插值数据查询",
            # operation_id="历史插值数据查询",
            description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_zhongkong_interpolated(
        # table: str = Query('PID_FEP_Gateway_Device_001default', description="设备名（表名）", example="PID_FEP_Gateway_Device_001default"),
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                              examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1761357384979, "2025-01-01 12:00:00", "2025-01-01T12:00:00",
                                                      "2025-01-01"]),
        end_time: Union[int, str] = Query(None,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1761457384979, "2025-01-02 12:00:00", "2025-01-02T12:00:00",
                                                    "2025-01-02"]),
        is_filter: bool = Query(None, required=False, description="是否过滤，获取最新一组pid值数据",
                                          examples=[True]),
):
    try:
        # 调用Service层查询插值历史数据
        result = DeviceDataService.query_history_data_interpolated(
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time,
            is_filter=is_filter
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


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
        result = await DeviceDataService.send_device_command_batch(
            commands=commands,
            retryNum=retryNum,
            timeout=timeout,
            authorization=authorization
        )
        return result
    except Exception as e:
        logger.error(f"设备指令代理错误: {str(e)}")
        raise RuntimeException( detail=f"代理服务内部错误: {str(e)}")




