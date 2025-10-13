#!/usr/bin/env python3
"""
测试分析API接口的示例脚本
演示如何使用三个HTTP接口：
1. /api/analysis/history-data - 历史数据工具
2. /api/analysis/temperature-analysis - 温度分析工具
3. /api/analysis/pid-optimization - PID优化工具
"""

import requests
import json
import time

# API基础URL
# BASE_URL = "http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com"
BASE_URL = "http://localhost:8001"

def test_history_data_api():
    """测试历史数据API"""
    print("=== 测试历史数据API ===")
    
    url = f"{BASE_URL}/api/analysis/history-data"
    payload = {
        "dataRange": "1",  # 最近1小时
        "point": "channel_0"  # 可选，指定通道0
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print(f"响应数据: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_temperature_analysis_api():
    """测试温度分析API"""
    print("=== 测试温度分析API ===")
    
    url = f"{BASE_URL}/api/analysis/temperature-analysis"
    payload = {
        "histData": {
            "channel_id": 0,
            "hours": 1.0
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print(f"响应数据: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_pid_optimization_api():
    """测试PID优化API"""
    print("=== 测试PID优化API ===")
    
    url = f"{BASE_URL}/api/analysis/pid-optimization"
    payload = {
        "histData": {
            "channel_id": 0,
            "hours": 1.0
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        print(f"状态码: {response.status_code}")
        print(f"响应数据: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def test_health_check():
    """测试健康检查接口"""
    print("=== 测试健康检查API ===")
    
    url = f"{BASE_URL}/api/analysis/health"
    
    try:
        response = requests.get(url)
        print(f"状态码: {response.status_code}")
        print(f"响应数据: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"请求失败: {str(e)}")
    print()

def main():
    """主测试函数"""
    print("开始测试分析API接口...")
    print("注意：确保API服务已启动在 http://localhost:8000")
    print("=" * 50)
    
    # 测试健康检查
    test_health_check()
    
    # 测试历史数据API
    test_history_data_api()
    
    # 测试温度分析API
    test_temperature_analysis_api()
    
    # 测试PID优化API
    test_pid_optimization_api()
    
    print("测试完成！")

if __name__ == "__main__":
    main()