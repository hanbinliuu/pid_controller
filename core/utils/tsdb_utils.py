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


def convert_to_timestamp(time_input: Union[int, str, datetime]) -> int:
    """
        将不同格式的时间转换为毫秒时间戳
        time_input: 时间输入（时间戳、字符串或datetime对象）
    """
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


def ensure_required_fields(record: Dict[str, Any]) -> None:
    """
        确保记录包含所有必需字段，缺失的用默认值填充

        Args:
            record: 数据记录字典
    """
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


def format_pid_data_for_analysis(history_data: List[Dict[str, Any]]) -> Dict[str, List]:
    """
        将PID历史数据格式化为分析工具可用的格式
        history_data: PID历史数据列表
    """
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