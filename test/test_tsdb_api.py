#!/usr/bin/env python3
"""
测试TSDB API接口
"""

import requests
import json
import time

# API基础URL
BASE_URL = "http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com"

def test_read_raw_api():
    """测试历史原始值查询API"""
    print("=== 测试 /tsdb/v4/read_raw 接口 ===")
    
    url = f"{BASE_URL}/tsdb/v4/read_raw?db=test_db"
    payload = {
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
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print(f"请求URL: {url}")
        print("请求数据:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\n响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_tables_api():
    """测试获取表列表API"""
    print("=== 测试 /tsdb/v4/tables 接口 ===")
    
    url = f"{BASE_URL}/tsdb/v4/tables?db=test_db"
    
    try:
        response = requests.get(url)
        print(f"状态码: {response.status_code}")
        print(f"请求URL: {url}")
        print("响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_table_schema_api():
    """测试获取表结构API"""
    print("=== 测试 /tsdb/v4/tables/{table_name}/schema 接口 ===")
    
    table_name = "cpu"
    url = f"{BASE_URL}/tsdb/v4/tables/{table_name}/schema?db=test_db"
    
    try:
        response = requests.get(url)
        print(f"状态码: {response.status_code}")
        print(f"请求URL: {url}")
        print("响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_query_api():
    """测试自定义查询API"""
    print("=== 测试 /tsdb/v4/query 接口 ===")
    
    url = f"{BASE_URL}/tsdb/v4/query?db=test_db"
    query = "SELECT time, temperature FROM pid_control WHERE channel='0' LIMIT 10"
    
    try:
        response = requests.post(url, params={"query": query})
        print(f"状态码: {response.status_code}")
        print(f"请求URL: {url}")
        print(f"查询语句: {query}")
        print("响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_health_api():
    """测试健康检查API"""
    print("=== 测试 /tsdb/v4/health 接口 ===")
    
    url = f"{BASE_URL}/tsdb/v4/health"
    
    try:
        response = requests.get(url)
        print(f"状态码: {response.status_code}")
        print(f"请求URL: {url}")
        print("响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_invalid_request():
    """测试无效请求"""
    print("=== 测试无效请求处理 ===")
    
    url = f"{BASE_URL}/tsdb/v4/read_raw"
    payload = {
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
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print("请求数据（重复表名）:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\n响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_pid_control_scenario():
    """测试PID控制场景"""
    print("=== 测试PID控制数据查询场景 ===")
    
    url = f"{BASE_URL}/tsdb/v4/read_raw?db=pid_system"
    payload = {
        "tables": [
            {
                "table": "pid_control",
                "fields": ["temperature", "target_temp", "kp", "ki", "kd", "output"],
                "tags": {
                    "channel": "0",
                    "controller": "main"
                }
            }
        ],
        "detail": {
            "startTime": int(time.time() * 1000) - 3600000,  # 1小时前
            "endTime": int(time.time() * 1000),  # 现在
            "limit": 100,
            "returnBounds": True
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print("请求数据（PID控制场景）:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("\n响应数据:")
        print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def main():
    """主测试函数"""
    print("开始测试TSDB API接口...")
    print("注意：确保API服务已启动在 http://localhost:8001")
    print("=" * 60)
    
    try:
        # 测试健康检查
        test_health_api()
        
        # 测试表列表
        test_tables_api()
        
        # 测试表结构
        test_table_schema_api()
        
        # 测试历史原始值查询
        test_read_raw_api()
        
        # 测试自定义查询
        test_query_api()
        
        # 测试无效请求
        test_invalid_request()
        
        # 测试PID控制场景
        test_pid_control_scenario()
        
        print("测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {str(e)}")

if __name__ == "__main__":
    main()