#!/usr/bin/env python3
"""
测试修改后的时序数据接口
验证PID参数能正确返回到接口中，而不依赖查询结果
"""

import requests
import json
from datetime import datetime, timedelta

def test_history_data_with_pid_params():
    """测试带PID参数的历史数据接口"""
    
    # API基础URL
    base_url = "http://localhost:8001"
    
    # 测试参数
    test_params = {
        "db": "platform",
        "table": "test-device-001",
        "start_time": int((datetime.now() - timedelta(hours=1)).timestamp() * 1000),
        "end_time": int(datetime.now().timestamp() * 1000),
        "kp": 2.5,
        "ki": 0.15,
        "kd": 0.08,
        "target_temp": 35.0
    }
    
    print("🔧 测试修改后的时序数据接口")
    print("=" * 50)
    print(f"测试参数: {json.dumps(test_params, indent=2)}")
    print()
    
    try:
        # 发送请求到修改后的历史数据接口
        response = requests.get(f"{base_url}/analysis/history-data", params=test_params, timeout=10)
        
        print(f"📡 请求状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 请求成功!")
            print(f"📊 响应状态: {result.get('status')}")
            print(f"📋 数据记录数: {result.get('totalRecords', 0)}")
            
            # 检查返回的数据是否包含正确的PID参数
            data = result.get('data', [])
            if data:
                first_record = data[0]
                print("\n🔍 验证PID参数:")
                print(f"   Kp: {first_record.get('kp')} (期望: {test_params['kp']})")
                print(f"   Ki: {first_record.get('ki')} (期望: {test_params['ki']})")
                print(f"   Kd: {first_record.get('kd')} (期望: {test_params['kd']})")
                print(f"   目标温度: {first_record.get('target_temp')} (期望: {test_params['target_temp']})")
                
                # 验证参数是否匹配
                params_match = (
                    first_record.get('kp') == test_params['kp'] and
                    first_record.get('ki') == test_params['ki'] and
                    first_record.get('kd') == test_params['kd'] and
                    first_record.get('target_temp') == test_params['target_temp']
                )
                
                if params_match:
                    print("\n🎉 SUCCESS: PID参数正确返回!")
                else:
                    print("\n❌ FAILURE: PID参数不匹配!")
                    
                print(f"\n📄 完整第一条记录: {json.dumps(first_record, indent=2)}")
            else:
                print("\n⚠️  警告: 没有返回数据记录")
                
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"❌ 测试异常: {str(e)}")

def test_different_pid_values():
    """测试不同的PID参数值"""
    
    print("\n" + "=" * 50)
    print("🔄 测试不同PID参数值")
    print("=" * 50)
    
    test_cases = [
        {"kp": 1.0, "ki": 0.1, "kd": 0.05, "target_temp": 25.0},
        {"kp": 3.5, "ki": 0.25, "kd": 0.12, "target_temp": 40.0},
        {"kp": 0.8, "ki": 0.05, "kd": 0.02, "target_temp": 20.0}
    ]
    
    base_url = "http://localhost:8001"
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n测试用例 {i}: {case}")
        
        params = {
            "db": "platform",
            "table": "test-device-001",
            "start_time": int((datetime.now() - timedelta(hours=1)).timestamp() * 1000),
            "end_time": int(datetime.now().timestamp() * 1000),
            **case
        }
        
        try:
            response = requests.get(f"{base_url}/analysis/history-data", params=params, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                data = result.get('data', [])
                
                if data:
                    first_record = data[0]
                    actual_values = {
                        "kp": first_record.get('kp'),
                        "ki": first_record.get('ki'),
                        "kd": first_record.get('kd'),
                        "target_temp": first_record.get('target_temp')
                    }
                    
                    if actual_values == case:
                        print(f"   ✅ 通过: {actual_values}")
                    else:
                        print(f"   ❌ 失败: 期望 {case}, 实际 {actual_values}")
                else:
                    print("   ⚠️  无数据")
            else:
                print(f"   ❌ 请求失败: {response.status_code}")
                
        except Exception as e:
            print(f"   ❌ 异常: {str(e)}")

if __name__ == "__main__":
    # 运行测试
    test_history_data_with_pid_params()
    test_different_pid_values()
    
    print("\n🎯 测试完成!")