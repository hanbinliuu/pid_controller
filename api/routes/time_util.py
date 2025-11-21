from datetime import datetime
import re
from typing import Union

def parse_time_to_milliseconds(time_input: Union[int, str]) -> int:
    """
    将时间参数转换为毫秒时间戳

    支持格式：
    - 毫秒时间戳 (int): 1640995200000
    - 秒时间戳 (int): 1640995200 (自动检测并转换)
    - ISO格式字符串: "2022-01-01T12:00:00"
    - 标准格式字符串: "2022-01-01 12:00:00"
    - 日期格式字符串: "2022-01-01"

    Args:
        time_input: 时间输入，支持int或str格式

    Returns:
        int: 毫秒时间戳

    Raises:
        ValueError: 时间格式不支持或解析失败
    """
    if isinstance(time_input, int):
        # 如果是整数，检查是秒还是毫秒
        if time_input < 10000000000:  # 小于10位数，认为是秒时间戳
            return time_input * 1000
        else:  # 大于等于10位数，认为是毫秒时间戳
            return time_input

    elif isinstance(time_input, str):
        # 字符串格式的时间解析
        time_patterns = [
            # ISO 8601格式
            (r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$', '%Y-%m-%dT%H:%M:%S'),
            # 标准格式
            (r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', '%Y-%m-%d %H:%M:%S'),
            # 日期格式（默认00:00:00）
            (r'^\d{4}-\d{2}-\d{2}$', '%Y-%m-%d'),
            # 带毫秒的格式
            (r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+$', '%Y-%m-%d %H:%M:%S.%f'),
        ]

        for pattern, fmt in time_patterns:
            if re.match(pattern, time_input.strip()):
                try:
                    # 处理ISO格式中的时区信息
                    clean_time = time_input.strip()
                    if 'T' in clean_time and (
                            clean_time.endswith('Z') or '+' in clean_time[-6:] or clean_time[-6:].count('-') == 1):
                        # 移除时区信息进行简单解析
                        if clean_time.endswith('Z'):
                            clean_time = clean_time[:-1]
                        elif '+' in clean_time[-6:]:
                            clean_time = clean_time.split('+')[0]
                        elif clean_time[-6:].count('-') == 1:
                            clean_time = clean_time.rsplit('-', 1)[0]

                    dt = datetime.strptime(clean_time, fmt)
                    return int(dt.timestamp() * 1000)
                except ValueError:
                    continue

        # 如果所有格式都不匹配，尝试解析为时间戳字符串
        try:
            timestamp = int(time_input)
            return parse_time_to_milliseconds(timestamp)
        except ValueError:
            pass

        raise ValueError(
            f"不支持的时间格式: {time_input}. 支持的格式包括: 毫秒时间戳、'YYYY-MM-DD'、'YYYY-MM-DD HH:MM:SS'、'YYYY-MM-DDTHH:MM:SS'")

    else:
        raise ValueError(f"时间参数类型错误: {type(time_input)}. 期望 int 或 str 类型")


def format_time_to_string(time_input: Union[int, str], fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    将时间输入转换为指定格式的字符串（默认 'YYYY-MM-DD HH:MM:SS'）

    支持输入：
    - 毫秒/秒时间戳（int）
    - 已支持的字符串时间格式（将先转为毫秒时间戳再格式化）
    """
    ms = parse_time_to_milliseconds(time_input)
    dt = datetime.fromtimestamp(ms / 1000.0)
    return dt.strftime(fmt)

def format_time_to_iso(time_input: Union[int, str], with_ms: bool = False) -> str:
    """
    将时间输入转换为 ISO 格式字符串（默认无毫秒）
    示例：'2025-01-01T12:00:00' 或 '2025-01-01T12:00:00.123'

    参数：
    - with_ms: 是否包含毫秒
    """
    ms = parse_time_to_milliseconds(time_input)
    dt = datetime.fromtimestamp(ms / 1000.0)
    return dt.isoformat(timespec='milliseconds' if with_ms else 'seconds')
