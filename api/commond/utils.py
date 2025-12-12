from datetime import date, datetime
from decimal import Decimal

import numpy as np


def result_to_serializable(obj):
    """递归转换对象为可序列化的Python类型"""
    if obj is None:
        return None
    elif isinstance(obj, (str, int, float, bool)):
        return obj
    elif isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.bool_):
        return bool(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {k: result_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [result_to_serializable(item) for item in obj]
    elif isinstance(obj, tuple):
        return tuple(result_to_serializable(item) for item in obj)
    elif hasattr(obj, '__dict__'):
        # 尝试转换为字典
        return result_to_serializable(obj.__dict__)
    else:
        # 其他情况转换为字符串
        return str(obj)