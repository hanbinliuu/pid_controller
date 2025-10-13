#!/usr/bin/env python3
"""
时序数据库工具方法
提供便捷的时序数据查询和处理功能
"""

from typing import List, Dict, Optional, Any, Union
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

try:
    from core.data.mock_tsdb_api import query_raw_data
except ImportError:
    # 如果导入失败，提供模拟实现
    def query_raw_data(request_data: Dict) -> Dict:
        return {
            "code": 0,
            "message": "",
            "results": []
        }

    """
    获取PID控制历史数据的工具方法
        table_name: 表名
        start_time: 开始时间（支持毫秒时间戳、时间字符串或datetime对象）
        end_time: 结束时间（可选，默认为当前时间）
        limit: 限制返回的数据条数（默认1500）
        tags: 标签过滤条件（可选）
    """
def get_pid_history_data(
    table_name: str,
    start_time: Union[int, str, datetime],
    end_time: Optional[Union[int, str, datetime]] = None,
    limit: int = 1500,
    tags: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    # 转换时间参数为毫秒时间戳
    start_timestamp = _convert_to_timestamp(start_time)
    end_timestamp = _convert_to_timestamp(end_time) if end_time else int(datetime.now().timestamp() * 1000)

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
    request_data = {
        "tables": [
            {
                "table": table_name,
                "fields": required_fields,  # 指定需要的字段
                "tags": tags,
                "continuationPoint": None
            }
        ],
        "detail": {
            "startTime": start_timestamp,
            "endTime": end_timestamp,
            "limit": limit,
            "returnBounds": False
        }
    }

    try:
        # 调用时序数据查询接口
        response = query_raw_data(request_data)

        # 检查响应状态
        if response.get("code") != 0:
            raise Exception(f"查询失败: {response.get('message', '未知错误')}")

        # 解析查询结果
        results = response.get("results", [])
        if not results:
            return []

        # 获取第一个表的结果（因为只查询了一个表）
        table_result = results[0]
        data_points = table_result.get("data", [])

        if not data_points:
            return []

        # 处理数据点
        history_data = []
        for data_point in data_points:
            columns = data_point.get("columns", [])
            values = data_point.get("values", [])

            # 确保time字段在第一位
            if "time" not in columns:
                columns = ["time"] + columns

            # 处理每一行数据
            for value_row in values:
                record = {}

                # 构建字段映射
                for i, column in enumerate(columns):
                    if i < len(value_row):
                        if column == "time":
                            # 时间字段重命名为timestamp
                            record["timestamp"] = value_row[i]
                        else:
                            record[column] = value_row[i]

                # 确保包含所有必需字段，缺失的用默认值填充
                # _ensure_required_fields(record)

                history_data.append(record)

        return history_data

    except Exception as e:
        print(f"获取PID历史数据失败: {str(e)}")
        return []


def get_temperature_history(
    table_name: str,
    start_time: Union[int, str, datetime],
    end_time: Optional[Union[int, str, datetime]] = None,
    limit: int = 1500,
    channel: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    获取温度历史数据的便捷方法
    
    Args:
        table_name: 表名
        start_time: 开始时间
        end_time: 结束时间（可选）
        limit: 限制条数
        channel: 通道号（可选）
        
    Returns:
        List[Dict]: 温度历史数据列表
    """
    tags = {"channel": channel} if channel else None

    return get_pid_history_data(
        table_name=table_name,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        tags=tags
    )


def get_recent_pid_data(
    table_name: str,
    hours: int = 24,
    limit: int = 1500,
    tags: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]:
    """
    获取最近N小时的PID数据
    
    Args:
        table_name: 表名
        hours: 最近多少小时的数据
        limit: 限制条数
        tags: 标签过滤
        
    Returns:
        List[Dict]: PID历史数据列表
    """
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=hours)

    return get_pid_history_data(
        table_name=table_name,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        tags=tags
    )

"""
    将不同格式的时间转换为毫秒时间戳
    time_input: 时间输入（时间戳、字符串或datetime对象）
"""
def _convert_to_timestamp(time_input: Union[int, str, datetime]) -> int:

    if isinstance(time_input, int):
        # 已经是时间戳，检查是否是秒级时间戳
        if time_input < 10000000000:  # 小于10位数，认为是秒级时间戳
            return time_input * 1000
        return time_input

    elif isinstance(time_input, str):
        # 字符串格式，尝试解析
        try:
            # 尝试解析常见格式
            formats = [
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d"
            ]

            for fmt in formats:
                try:
                    dt = datetime.strptime(time_input, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue

            raise ValueError(f"无法解析时间格式: {time_input}")

        except Exception as e:
            raise ValueError(f"时间字符串解析失败: {str(e)}")

    elif isinstance(time_input, datetime):
        # datetime对象
        return int(time_input.timestamp() * 1000)

    else:
        raise ValueError(f"不支持的时间格式: {type(time_input)}")

"""
    确保记录包含所有必需字段，缺失的用默认值填充

    Args:
        record: 数据记录字典
"""
def _ensure_required_fields(record: Dict[str, Any]) -> None:
    default_values = {
        "timestamp": None,
        "temperature": 25.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "target_temp": 25.0,
        "control_period": 100,
        "max_duty": 100
    }

    for field, default_value in default_values.items():
        if field not in record or record[field] is None:
            record[field] = default_value

"""
    将PID历史数据格式化为分析工具可用的格式
    history_data: PID历史数据列表
"""
def format_pid_data_for_analysis(history_data: List[Dict[str, Any]]) -> Dict[str, List]:

    if not history_data:
        return {}

    formatted_data = {
        "timestamps": [],
        "temperatures": [],
        "target_temps": [],
        "kp_values": [],
        "ki_values": [],
        "kd_values": [],
        "control_periods": [],
        "max_duties": []
    }

    for record in history_data:
        formatted_data["timestamps"].append(record.get("timestamp"))
        formatted_data["temperatures"].append(record.get("temperature", 25.0))
        formatted_data["target_temps"].append(record.get("target_temp", 25.0))
        formatted_data["kp_values"].append(record.get("kp", 1.0))
        formatted_data["ki_values"].append(record.get("ki", 0.1))
        formatted_data["kd_values"].append(record.get("kd", 0.05))
        formatted_data["control_periods"].append(record.get("control_period", 100))
        formatted_data["max_duties"].append(record.get("max_duty", 100))

    return formatted_data


# 便捷别名
get_pid_data = get_pid_history_data
get_temp_data = get_temperature_history