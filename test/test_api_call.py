#!/usr/bin/env python3
"""
模拟调用历史数据查询接口
测试对CSV文件数据的查询功能
"""

import requests
import json
from datetime import datetime

def test_history_data_api():
    """测试历史数据查询API"""
    
    # API端点
    url = "http://localhost:8001/api/analysis/history-data"
    
    # 请求参数 - 根据项目规范，只包含table、start_time、end_time三个核心参数
    request_data = {
        "table": "fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811",
        "start_time": 1759109290968,  # CSV中的起始时间戳
        "end_time": 1759110280968     # CSV中的结束时间戳
    }
    
    print("🚀 模拟调用历史数据查询接口...")
    print(f"📋 请求URL: {url}")
    print(f"📝 请求参数:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("-" * 50)
    
    try:
        # 发送POST请求
        response = requests.post(url, json=request_data, timeout=10)
        
        print(f"✅ 响应状态码: {response.status_code}")
        print(f"📊 响应数据:")
        
        if response.status_code == 200:
            result = response.json()
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 分析响应结果
            if result.get("status") == "success":
                total_records = result.get("totalRecords", 0)
                print(f"\n📈 查询结果分析:")
                print(f"   - 表名: {result.get('table')}")
                print(f"   - 时间范围: {result.get('start_time')} - {result.get('end_time')}")
                print(f"   - 总记录数: {total_records}")
                
                if total_records > 0:
                    data = result.get("data", [])
                    if data:
                        print(f"   - 首条记录: {json.dumps(data[0], indent=4, ensure_ascii=False)}")
                        print(f"   - 末条记录: {json.dumps(data[-1], indent=4, ensure_ascii=False)}")
                else:
                    print("    未查询到数据，可能原因:")
                    print("      1. 时序数据库中无对应表数据")
                    print("      2. 时间范围无匹配记录")
                    print("      3. 数据源配置问题")
            else:
                print(f"❌ 查询失败: {result.get('message', '未知错误')}")
        else:
            print(f"❌ HTTP错误: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败: {e}")
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}")
    except Exception as e:
        print(f"❌ 其他错误: {e}")

def test_temperature_analysis_api():
    """测试温度分析API"""
    
    # API端点
    url = "http://localhost:8001/api/analysis/temperature-analysis"
    
    # 请求参数
    request_data = {
        "table": "fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811",
        "start_time": 1759109290968,
        "end_time": 1759110280968
    }
    
    print("\n🌡️  模拟调用温度分析接口...")
    print(f"📋 请求URL: {url}")
    print(f"📝 请求参数:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    print("-" * 50)
    
    try:
        response = requests.post(url, json=request_data, timeout=10)
        print(f"✅ 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"📊 响应数据:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"❌ HTTP错误: {response.text}")
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")

if __name__ == "__main__":
    print("🔧 PID Agent API 测试工具")
    print("=" * 60)
    
    # 测试历史数据查询接口
    test_history_data_api()
    
    # 测试温度分析接口
    test_temperature_analysis_api()
    
    print("\n✅ 测试完成!")
