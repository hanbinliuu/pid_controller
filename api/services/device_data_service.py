#!/usr/bin/env python3
"""
设备数据查询业务服务层
封装设备数据查询相关的业务逻辑
"""

import logging
from typing import Optional, List, Union, Dict, Any
from datetime import datetime

from core.agent.tools import process_query_tsdb_data_interpolated, process_query_tsdb_data_raw
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import query_raw_data, get_default_database
from api.routes.time_util import parse_time_to_milliseconds

logger = logging.getLogger(__name__)


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
        window: int = None,
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