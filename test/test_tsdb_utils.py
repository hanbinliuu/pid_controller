#!/usr/bin/env python3
"""
测试 TSDB 工具方法
"""

import json
import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.utils.tsdb_utils import (
    get_pid_history_data,
    get_temperature_history,
    get_recent_pid_data,
    format_pid_data_for_analysis,
    convert_to_timestamp
)


def test_time_conversion():
    """测试时间转换功能"""
    print("=== 测试时间转换功能 ===")
    
    # 测试时间戳转换
    timestamp_ms = 1657258564523
    result = convert_to_timestamp(timestamp_ms)
    print(f"毫秒时间戳 {timestamp_ms} -> {result}")
    
    # 测试秒级时间戳转换
    timestamp_s = 1657258564
    result = convert_to_timestamp(timestamp_s)
    print(f"秒级时间戳 {timestamp_s} -> {result}")
    
    # 测试字符串转换
    time_str = "2022-07-08 13:36:04"
    result = convert_to_timestamp(time_str)
    print(f"时间字符串 '{time_str}' -> {result}")
    
    # 测试datetime对象转换
    dt = datetime.now()
    result = convert_to_timestamp(dt)
    print(f"datetime对象 {dt} -> {result}")
    print()


def test_get_pid_history_data():
    """测试获取PID历史数据"""
    print("=== 测试获取PID历史数据 ===")
    
    # 使用时间戳
    start_time = 1657257600000
    end_time = 1657344000000
    
    data = get_pid_history_data(
        table_name="cpu",  # 使用模拟数据中存在的表
        start_time=start_time,
        end_time=end_time,
        limit=10
    )
    
    print(f"查询表: cpu")
    print(f"时间范围: {start_time} - {end_time}")
    print(f"返回数据条数: {len(data)}")
    
    if data:
        print("返回数据示例:")
        for i, record in enumerate(data[:2]):  # 只显示前2条
            print(f"  记录 {i+1}: {json.dumps(record, indent=4, ensure_ascii=False)}")
    else:
        print("未返回数据")
    print()


def test_get_pid_history_with_string_time():
    """测试使用字符串时间获取数据"""
    print("=== 测试使用字符串时间获取数据 ===")
    
    data = get_pid_history_data(
        table_name="ns-01f-001",
        start_time="2022-07-01 00:00:00",
        end_time="2022-07-02 00:00:00",
        limit=5
    )
    
    print(f"查询表: ns-01f-001")
    print(f"时间范围: 2022-07-01 00:00:00 - 2022-07-02 00:00:00")
    print(f"返回数据条数: {len(data)}")
    
    if data:
        print("返回数据示例:")
        for i, record in enumerate(data):
            print(f"  记录 {i+1}: {json.dumps(record, indent=4, ensure_ascii=False)}")
    print()


def test_get_temperature_history():
    """测试获取温度历史数据"""
    print("=== 测试获取温度历史数据 ===")
    
    data = get_temperature_history(
        table_name="cpu",
        start_time="2022-07-08 00:00:00",
        end_time="2022-07-09 00:00:00",
        limit=5,
        channel="0"
    )
    
    print(f"查询表: cpu (channel=0)")
    print(f"返回数据条数: {len(data)}")
    
    if data:
        print("返回数据示例:")
        for i, record in enumerate(data):
            print(f"  记录 {i+1}: {json.dumps(record, indent=4, ensure_ascii=False)}")
    print()


def test_get_recent_pid_data():
    """测试获取最近的PID数据"""
    print("=== 测试获取最近的PID数据 ===")
    
    data = get_recent_pid_data(
        table_name="cpu",
        hours=24,
        limit=5
    )
    
    print(f"查询表: cpu (最近24小时)")
    print(f"返回数据条数: {len(data)}")
    
    if data:
        print("返回数据示例:")
        for i, record in enumerate(data):
            print(f"  记录 {i+1}: {json.dumps(record, indent=4, ensure_ascii=False)}")
    print()


def test_format_pid_data():
    """测试数据格式化功能"""
    print("=== 测试数据格式化功能 ===")
    
    # 创建测试数据
    test_data = [
        {
            "timestamp": "2022-07-08 13:36:02.523",
            "temperature": 25.5,
            "kp": 1.2,
            "ki": 0.15,
            "kd": 0.08,
            "target_temp": 30.0,
            "control_period": 100,
            "max_duty": 80
        },
        {
            "timestamp": "2022-07-08 13:36:03.523",
            "temperature": 26.0,
            "kp": 1.2,
            "ki": 0.15,
            "kd": 0.08,
            "target_temp": 30.0,
            "control_period": 100,
            "max_duty": 80
        }
    ]
    
    formatted_data = format_pid_data_for_analysis(test_data)
    
    print("原始数据:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    
    print("\n格式化后的数据:")
    print(json.dumps(formatted_data, indent=2, ensure_ascii=False))
    print()


def test_error_handling():
    """测试错误处理"""
    print("=== 测试错误处理 ===")
    
    # 测试不存在的表
    data = get_pid_history_data(
        table_name="nonexistent_table",
        start_time=1657257600000,
        end_time=1657344000000
    )
    
    print(f"查询不存在的表 'nonexistent_table':")
    print(f"返回数据条数: {len(data)}")
    
    # 测试无效时间格式
    try:
        result = convert_to_timestamp("invalid_time_format")
        print(f"无效时间格式处理结果: {result}")
    except ValueError as e:
        print(f"无效时间格式错误处理: {str(e)}")
    
    print()


def test_comprehensive_scenario():
    """测试综合场景"""
    print("=== 测试综合场景 - PID控制系统数据获取 ===")
    
    # 模拟真实的PID控制系统数据查询场景
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=1)  # 最近1小时
    
    print(f"查询时间范围: {start_time} 到 {end_time}")
    
    # 获取PID控制数据
    pid_data = get_pid_history_data(
        table_name="cpu",  # 使用现有的测试表
        start_time=start_time,
        end_time=end_time,
        limit=100,
        tags={"host": "node1"}  # 过滤特定主机
    )
    
    print(f"PID控制数据条数: {len(pid_data)}")
    
    if pid_data:
        # 分析数据
        formatted_data = format_pid_data_for_analysis(pid_data)
        
        print("数据分析结果:")
        print(f"  温度数据点数: {len(formatted_data.get('temperatures', []))}")
        print(f"  温度范围: {min(formatted_data.get('temperatures', [0]))} - {max(formatted_data.get('temperatures', [0]))}")
        print(f"  KP参数范围: {min(formatted_data.get('kp_values', [0]))} - {max(formatted_data.get('kp_values', [0]))}")
        
        print("\n最新的3条记录:")
        for i, record in enumerate(pid_data[-3:]):
            print(f"  记录 {i+1}: {json.dumps(record, indent=4, ensure_ascii=False)}")
    
    print()


def main():
    """主测试函数"""
    print("开始测试 TSDB 工具方法...")
    print("=" * 60)
    
    try:
        test_time_conversion()
        test_get_pid_history_data()
        test_get_pid_history_with_string_time()
        test_get_temperature_history()
        test_get_recent_pid_data()
        test_format_pid_data()
        test_error_handling()
        test_comprehensive_scenario()
        
        print("所有测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {str(e)}")
        import traceback
        print(f"错误堆栈: {traceback.format_exc()}")


if __name__ == "__main__":
    main()