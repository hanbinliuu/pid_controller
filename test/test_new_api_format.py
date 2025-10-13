#!/usr/bin/env python3
"""
测试修改后的Analysis Router API接口
验证新的入参格式：设备名（table）+ start_time + end_time
"""

import requests
import json
from datetime import datetime, timedelta

# API基础URL
BASE_URL = "http://localhost:8001/api/analysis"

def test_new_api_format():
    """测试新的API接口格式"""
    
    # 计算时间戳（毫秒）
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = int((datetime.now() - timedelta(hours=24)).timestamp() * 1000)
    
    print("=== 测试新的API接口格式 ===")
    print(f"开始时间: {datetime.fromtimestamp(start_time/1000)}")
    print(f"结束时间: {datetime.fromtimestamp(end_time/1000)}")
    print()
    
    # 1. 测试历史数据接口
    print("1. 测试历史数据接口 /history-data")
    history_request = {
        "table": "test-device-001",
        "start_time": start_time,
        "end_time": end_time,
        "tags": {
            "location": "workshop-01",
            "channel": "channel-01"
        }
    }
    
    print(f"请求参数: {json.dumps(history_request, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/history-data",
            json=history_request,
            headers={"Content-Type": "application/json"}
        )
        print(f"响应状态码: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"响应结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"错误响应: {response.text}")
    except Exception as e:
        print(f"请求失败: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # 2. 测试温度分析接口
    print("2. 测试温度分析接口 /temperature-analysis")
    analysis_request = {
        "table": "test-device-001",
        "start_time": start_time,
        "end_time": end_time,
        "tags": {
            "location": "workshop-01"
        }
    }
    
    print(f"请求参数: {json.dumps(analysis_request, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/temperature-analysis",
            json=analysis_request,
            headers={"Content-Type": "application/json"}
        )
        print(f"响应状态码: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"响应结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"错误响应: {response.text}")
    except Exception as e:
        print(f"请求失败: {e}")
    
    print("\n" + "="*50 + "\n")
    
    # 3. 测试PID优化接口
    print("3. 测试PID优化接口 /pid-optimization")
    optimization_request = {
        "table": "test-device-001", 
        "start_time": start_time,
        "end_time": end_time,
        "tags": {
            "controller": "pid-controller-01"
        }
    }
    
    print(f"请求参数: {json.dumps(optimization_request, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/pid-optimization",
            json=optimization_request,
            headers={"Content-Type": "application/json"}
        )
        print(f"响应状态码: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"响应结果: {json.dumps(result, indent=2, ensure_ascii=False)}")
        else:
            print(f"错误响应: {response.text}")
    except Exception as e:
        print(f"请求失败: {e}")

if __name__ == "__main__":
    print("Analysis Router API 接口测试")
    print("新格式：设备名（table）+ start_time + end_time")
    print()
    
    # 启动测试
    test_new_api_format()