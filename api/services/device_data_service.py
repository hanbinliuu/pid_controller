#!/usr/bin/env python3
"""
设备数据查询业务服务层
封装设备数据查询相关的业务逻辑
"""

import logging
import os
import uuid
from typing import Optional, List, Union, Dict, Any
from datetime import datetime

import httpx
from pydantic import Field, BaseModel

from core.agent.tools import process_query_tsdb_data_interpolated, process_query_tsdb_data_raw
from core.client.bff_model_client import BFFModelClient
from core.client.select_tsdb_client import query_raw_data, get_default_database
from api.commond.time_util import parse_time_to_milliseconds
from api.middleware.exceptions import RuntimeException

logger = logging.getLogger(__name__)

# IOTDA设备指令批量下发基础URL
IOTDA_BASE_URL = os.getenv(
    "IOTDA_BASE_URL",
    "http://data-engine-iotda-infra-system.sit-cloud.ieccloud.hollicube.com"
)


class DeviceCommand(BaseModel):
    """IOTDA设备指令数据模型"""
    request_id: str = str(uuid.uuid4())
    timeout: int = Field(20000, description="单条指令超时时间（ms）", example=20)
    object_device_id: str = Field(..., description="设备ID", example="PID_FEP_Gateway_Device_001")
    service_id: str = Field("default", description="服务ID", example="default")
    command_name: str = Field("set_property", description="命令名称", example="set_property")
    paras: Dict[str, Any] = Field(..., description="命令参数字典", example={"ns=100;s=FIC101A_TD.In_Channel0": 10})


class DeviceDataService:
    """设备数据查询业务服务"""

    @staticmethod
    def query_point_history_data_tsdb(
        table_name: str,
        fields: Optional[List[str]] = None,
        start_time: Union[int, str] = None,
        end_time: Union[int, str] = None,
        limit: int = 1500
    ) -> Dict[str, Any]:
        """
        查询指定设备在指定时间范围内的测点原始数据
        
        Args:
            table_name: 设备名（表名）
            fields: 测点名列表
            start_time: 开始时间，支持毫秒时间戳或字符串格式
            end_time: 结束时间，支持毫秒时间戳或字符串格式
            limit: 数据条数
            
        Returns:
            Dict[str, Any]: 查询结果
        """
        try:
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)

            if start_time is None:
                start_time = end_time - 60 * 60 * 1000  # 默认1小时
            
            # 时间格式转换和验证
            try:
                start_time_ms = parse_time_to_milliseconds(start_time)
                end_time_ms = parse_time_to_milliseconds(end_time)
            except ValueError as e:
                raise ValueError(f"时间格式错误: {str(e)}")

            # 验证时间范围
            if start_time_ms >= end_time_ms:
                raise ValueError("开始时间必须小于结束时间")

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
            logger.error(f"获取历史数据失败: {str(e)}")
            raise

    @staticmethod
    def query_history_data_raw(
        loop_uri: str = None,
        start_time: Union[int, str] = None,
        end_time: Union[int, str] = None
    ) -> Dict[str, Any]:
        """
        查询指定设备在指定时间范围内的历史数据
        
        Args:
            loop_uri: 回路URI
            start_time: 开始时间，支持毫秒时间戳或字符串格式
            end_time: 结束时间，支持毫秒时间戳或字符串格式
            
        Returns:
            Dict[str, Any]: 查询结果
        """
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
                raise ValueError(f"时间格式错误: {str(e)}")

            # 验证时间范围
            if start_time_ms >= end_time_ms:
                raise ValueError("开始时间必须小于结束时间")
            
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
            
            logger.info(f"查询到 {len(history_data)} 条历史数据")

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
            logger.error(f"获取历史数据失败: {str(e)}")
            raise

    @staticmethod
    def query_history_data_interpolated(
        loop_uri: str = None,
        start_time: Union[int, str] = None,
        end_time: Union[int, str] = None,
        window: int = 1,
        is_filter: bool = None
    ) -> Dict[str, Any]:
        """
        查询指定设备在指定时间范围内的历史插值数据
        
        Args:
            loop_uri: 回路URI
            start_time: 开始时间，支持毫秒时间戳或字符串格式
            end_time: 结束时间，支持毫秒时间戳或字符串格式
            is_filter: 是否过滤，获取最新一组pid值数据
            
        Returns:
            Dict[str, Any]: 查询结果
        """
        try:
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)

            if start_time is None:
                start_time = end_time - 60 * 60 * 1000  # 默认1小时

            # 将字段列表转换为字段映射map
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
            
            # 参数验证
            if not table or not table.strip():
                raise ValueError("表名参数不能为空")

            # 时间格式转换和验证
            try:
                start_time_ms = parse_time_to_milliseconds(start_time)
                end_time_ms = parse_time_to_milliseconds(end_time)
            except ValueError as e:
                raise ValueError(f"时间格式错误: {str(e)}")

            # 验证时间范围
            if start_time_ms >= end_time_ms:
                raise ValueError("开始时间必须小于结束时间")
            
            # 使用环境变量中的数据库名
            db = get_default_database()

            # 使用新的查询方法
            history_data = process_query_tsdb_data_interpolated(
                db=db,
                table_name=table,
                required_fields=required_fields,
                start_time=start_time_ms,
                end_time=end_time_ms,
                window=window,
                is_filter=is_filter
            )
            
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
            logger.error(f"获取历史数据失败: {str(e)}")
            raise

    @staticmethod
    async def send_device_command_batch(
        commands: List[DeviceCommand],
        retryNum: int = 0,
        timeout: int = 20000,
        authorization: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        代理下发设备指令到 IOTDA 系统（批量）。

        Args:
            commands: 设备指令数组
            retryNum: 重试次数（默认0）
            timeout: 请求整体超时（毫秒，默认20000）
            authorization: IOTDA鉴权令牌（可选）

        Returns:
            Dict[str, Any]: 返回响应结果
        """
        try:
            url = f"{IOTDA_BASE_URL}/iotda-data-engine/device/command/batch"

            headers = {"Content-Type": "application/json"}
            if authorization:
                headers["Authorization"] = authorization

            # 序列化请求体
            payload = []
            command = commands[0]
            for k in command.paras.keys():
                cmd = DeviceCommand(
                    timeout=timeout,
                    object_device_id=command.object_device_id,
                    service_id=command.service_id,
                    command_name=command.command_name,
                    paras={k: command.paras[k]}
                )
                payload.append(cmd.model_dump())

            logger.info(f"调用IOTDA设备指令批量接口: {url} params={{'retryNum': {retryNum}, 'timeout': {timeout}}}")
            logger.debug(f"请求体: {payload}")

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    params={"retryNum": retryNum, "timeout": 10000},
                    json=payload,
                    headers=headers
                )

            logger.info(f"IOTDA接口响应状态: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                logger.debug(f"响应体: {result}")
                if result.get("result_code") == 0:
                    logger.info(f"IOTDA接口调用成功: {result.get('message')}")
                    return {
                        "message": "指令批量下发成功",
                        "data": {"message": result.get("message")}
                    }
                else:
                    logger.error(f"IOTDA接口调用失败: {response.status_code} - {response.text}")
                    raise RuntimeException(
                        message=f"IOTDA指令下发失败: {result.get('message')}",
                        data=result.get("data")
                    )
            else:
                logger.error(f"IOTDA接口调用失败: {response.status_code} - {response.text}")
                raise Exception(
                    f"IOTDA调用失败: {response.text}"
                )

        except httpx.TimeoutException:
            logger.error("IOTDA接口调用超时")
            raise Exception("IOTDA接口调用超时")
        except httpx.ConnectError:
            logger.error("无法连接到IOTDA接口")
            raise Exception("无法连接到IOTDA服务")
        except Exception as e:
            logger.error(f"设备指令代理错误: {str(e)}")
            raise
