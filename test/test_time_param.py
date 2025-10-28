#!/usr/bin/env python3
"""
测试 time_param.py 历史原始值查询功能
"""

import json
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.data.mock_tsdb_client import (
    query_raw_data, 
    TimeParamQueryEngine, 
    MockTSDBDataSource,
    timestamp_to_datetime_str,
    datetime_str_to_timestamp
)


def test_basic_query():
    """测试基本查询功能"""
    print("=== 测试基本查询功能 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
                "fields": ["f1", "f2"],
                "tags": {
                    "host": "node1"
                },
                "continuationPoint": ""
            },
            {
                "table": "ns-01f-001",
                "continuationPoint": ""
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "endTime": 1657361200000,
            "limit": 2,
            "returnBounds": False
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_field_filtering():
    """测试字段过滤"""
    print("=== 测试字段过滤 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
                "fields": ["f1"],  # 只查询 f1 字段
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "limit": 5
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（仅查询f1字段）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_all_fields_query():
    """测试查询所有字段"""
    print("=== 测试查询所有字段 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
                # fields 为空，查询所有字段
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "limit": 5
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（查询所有字段）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_tag_filtering():
    """测试标签过滤"""
    print("=== 测试标签过滤 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
                "tags": {
                    "host": "node1"  # 只查询 host=node1 的数据
                }
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "limit": 10
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（过滤 host=node1）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_limit_functionality():
    """测试限制条数功能"""
    print("=== 测试限制条数功能 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "limit": 1  # 只返回1条数据
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（限制1条数据）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_multiple_tables():
    """测试多表查询"""
    print("=== 测试多表查询 ===")
    
    request_data = {
        "tables": [
            {
                "table": "cpu",
                "fields": ["f1"]
            },
            {
                "table": "ns-01f-001",
                "fields": ["s", "v"]
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "limit": 5
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（多表查询）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_invalid_request():
    """测试无效请求处理"""
    print("=== 测试无效请求处理 ===")
    
    # 测试重复表名
    request_data = {
        "tables": [
            {
                "table": "cpu",
            },
            {
                "table": "cpu",  # 重复的表名
            }
        ],
        "detail": {
            "startTime": 1657257600000,
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（重复表名）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_nonexistent_table():
    """测试不存在的表"""
    print("=== 测试不存在的表 ===")
    
    request_data = {
        "tables": [
            {
                "table": "nonexistent_table",
            }
        ],
        "detail": {
            "startTime": 1657257600000,
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（不存在的表）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def test_time_utils():
    """测试时间工具函数"""
    print("=== 测试时间工具函数 ===")
    
    # 测试时间戳转换
    timestamp = 1657258564523
    datetime_str = timestamp_to_datetime_str(timestamp)
    print(f"时间戳 {timestamp} 转换为: {datetime_str}")
    
    # 测试日期字符串转换
    back_timestamp = datetime_str_to_timestamp(datetime_str)
    print(f"日期字符串 {datetime_str} 转换为: {back_timestamp}")
    print(f"转换一致性: {timestamp == back_timestamp}")
    print()


def test_advanced_scenarios():
    """测试高级场景"""
    print("=== 测试高级场景 ===")
    
    # 模拟实际的PID控制系统数据查询
    request_data = {
        "tables": [
            {
                "table": "pid_control",
                "fields": ["temperature", "target_temp", "kp", "ki", "kd"],
                "tags": {
                    "channel": "0"
                }
            }
        ],
        "detail": {
            "startTime": 1657257600000,
            "endTime": 1657344000000,
            "limit": 100,
            "returnBounds": True
        }
    }
    
    response = query_raw_data(request_data)
    print("请求数据（PID控制系统查询）:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("\n响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    print()


def main():
    """主测试函数"""
    print("开始测试 time_param.py 历史原始值查询功能")
    print("=" * 60)
    
    try:
        test_basic_query()
        test_field_filtering()
        test_all_fields_query()
        test_tag_filtering()
        test_limit_functionality()
        test_multiple_tables()
        test_invalid_request()
        test_nonexistent_table()
        test_time_utils()
        test_advanced_scenarios()
        
        print("所有测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {str(e)}")
        import traceback
        print(f"错误堆栈: {traceback.format_exc()}")


if __name__ == "__main__":
    main()