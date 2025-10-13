#!/usr/bin/env python3
"""
测试修改后的历史数据查询接口
验证字符串时间格式支持和参数验证功能
"""

import requests
import json
from datetime import datetime, timedelta

def test_string_time_formats():
    """测试字符串时间格式支持"""
    
    # API基础URL
    base_url = "http://localhost:8001"
    
    print("🕐 测试历史数据查询接口的字符串时间格式支持")
    print("=" * 60)
    
    # 测试用例：不同时间格式
    test_cases = [
        {
            "name": "毫秒时间戳格式",
            "params": {
                "table": "temperature_sensor",
                "start_time": 1640995200000,
                "end_time": 1641081600000,
                "kp": 1.5,
                "ki": 0.05,
                "kd": 0.08,
                "target_temp": 30.0
            }
        },
        {
            "name": "标准时间字符串格式",
            "params": {
                "table": "temperature_sensor", 
                "start_time": "2022-01-01 12:00:00",
                "end_time": "2022-01-02 12:00:00",
                "kp": 2.0,
                "ki": 0.1,
                "kd": 0.05,
                "target_temp": 25.0
            }
        },
        {
            "name": "ISO 8601格式",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01T12:00:00",
                "end_time": "2022-01-02T12:00:00",
                "kp": 1.8,
                "ki": 0.08,
                "kd": 0.06,
                "target_temp": 35.0
            }
        },
        {
            "name": "日期格式（自动补零时分秒）",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 2.5,
                "ki": 0.12,
                "kd": 0.04,
                "target_temp": 40.0
            }
        },
        {
            "name": "混合格式（毫秒 + 字符串）",
            "params": {
                "table": "temperature_sensor",
                "start_time": 1640995200000,  # 毫秒时间戳
                "end_time": "2022-01-02 12:00:00",  # 字符串格式
                "kp": 1.2,
                "ki": 0.03,
                "kd": 0.07,
                "target_temp": 28.0
            }
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n测试 {i}: {test_case['name']}")
        print(f"参数: {json.dumps(test_case['params'], indent=2)}")
        
        try:
            response = requests.get(
                f"{base_url}/analysis/history-data",
                params=test_case['params'],
                timeout=10
            )
            
            print(f"📡 状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 成功: {result.get('status', '查询成功')}")
                print(f"📊 数据记录数: {result.get('totalRecords', 0)}")
                
                # 验证返回的PID参数
                data = result.get('data', [])
                if data:
                    first_record = data[0]
                    expected_params = test_case['params']
                    print(f"🔍 PID参数验证:")
                    print(f"   Kp: {first_record.get('kp')} (期望: {expected_params['kp']})")
                    print(f"   Ki: {first_record.get('ki')} (期望: {expected_params['ki']})")
                    print(f"   Kd: {first_record.get('kd')} (期望: {expected_params['kd']})")
                    print(f"   目标温度: {first_record.get('target_temp')} (期望: {expected_params['target_temp']})")
                    
                    # 检查参数是否匹配
                    params_match = (
                        first_record.get('kp') == expected_params['kp'] and
                        first_record.get('ki') == expected_params['ki'] and
                        first_record.get('kd') == expected_params['kd'] and
                        first_record.get('target_temp') == expected_params['target_temp']
                    )
                    
                    if params_match:
                        print("   ✅ PID参数匹配正确")
                    else:
                        print("   ❌ PID参数不匹配")
                        
            elif response.status_code == 400:
                error_detail = response.json().get('detail', '未知错误')
                print(f"❌ 参数错误: {error_detail}")
                
            else:
                print(f"❌ 请求失败: {response.status_code}")
                print(f"   错误信息: {response.text}")
                
        except Exception as e:
            print(f"❌ 异常: {str(e)}")

def test_parameter_validation():
    """测试参数验证功能"""
    
    print(f"\n{'='*60}")
    print("🚫 测试参数验证功能")
    print("=" * 60)
    
    base_url = "http://localhost:8001"
    
    validation_cases = [
        {
            "name": "无效kp值（负数）",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": -1.0,  # 无效：负数
                "ki": 0.05,
                "kd": 0.08,
                "target_temp": 30.0
            },
            "expected_error": "比例系数kp必须大于0"
        },
        {
            "name": "无效ki值（负数）",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 1.5,
                "ki": -0.05,  # 无效：负数
                "kd": 0.08,
                "target_temp": 30.0
            },
            "expected_error": "积分系数ki不能为负数"
        },
        {
            "name": "无效kd值（负数）",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 1.5,
                "ki": 0.05,
                "kd": -0.08,  # 无效：负数
                "target_temp": 30.0
            },
            "expected_error": "微分系数kd不能为负数"
        },
        {
            "name": "无效时间格式",
            "params": {
                "table": "temperature_sensor",
                "start_time": "invalid_time",  # 无效时间格式
                "end_time": "2022-01-02",
                "kp": 1.5,
                "ki": 0.05,
                "kd": 0.08,
                "target_temp": 30.0
            },
            "expected_error": "时间格式错误"
        },
        {
            "name": "开始时间大于结束时间",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-02",  # 开始时间晚于结束时间
                "end_time": "2022-01-01",
                "kp": 1.5,
                "ki": 0.05,
                "kd": 0.08,
                "target_temp": 30.0
            },
            "expected_error": "开始时间必须小于结束时间"
        },
        {
            "name": "空表名",
            "params": {
                "table": "",  # 空表名
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 1.5,
                "ki": 0.05,
                "kd": 0.08,
                "target_temp": 30.0
            },
            "expected_error": "表名参数不能为空"
        }
    ]
    
    for i, case in enumerate(validation_cases, 1):
        print(f"\n测试 {i}: {case['name']}")
        print(f"参数: {json.dumps(case['params'], indent=2)}")
        
        try:
            response = requests.get(
                f"{base_url}/analysis/history-data",
                params=case['params'],
                timeout=10
            )
            
            if response.status_code == 400:
                error_detail = response.json().get('detail', '未知错误')
                print(f"✅ 正确识别错误: {error_detail}")
                
                # 检查错误信息是否包含期望的关键词
                if case['expected_error'] in error_detail:
                    print(f"✅ 错误信息匹配期望")
                else:
                    print(f"⚠️  错误信息不完全匹配，期望包含: {case['expected_error']}")
                    
            else:
                print(f"❌ 未能正确识别错误，状态码: {response.status_code}")
                if response.status_code == 200:
                    print("   接口应该返回400错误，但返回了成功状态")
                
        except Exception as e:
            print(f"❌ 异常: {str(e)}")

def test_edge_cases():
    """测试边界情况"""
    
    print(f"\n{'='*60}")
    print("🎯 测试边界情况")
    print("=" * 60)
    
    base_url = "http://localhost:8001"
    
    edge_cases = [
        {
            "name": "kp最小有效值",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 0.001,  # 很小的正数
                "ki": 0,      # 边界值：0
                "kd": 0,      # 边界值：0
                "target_temp": 30.0
            }
        },
        {
            "name": "很大的PID参数值",
            "params": {
                "table": "temperature_sensor",
                "start_time": "2022-01-01",
                "end_time": "2022-01-02",
                "kp": 999.999,   # 很大的值
                "ki": 100.0,     # 大的积分系数
                "kd": 50.0,      # 大的微分系数
                "target_temp": 100.0
            }
        }
    ]
    
    for i, case in enumerate(edge_cases, 1):
        print(f"\n测试 {i}: {case['name']}")
        print(f"参数: {json.dumps(case['params'], indent=2)}")
        
        try:
            response = requests.get(
                f"{base_url}/analysis/history-data",
                params=case['params'],
                timeout=10
            )
            
            print(f"📡 状态码: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"✅ 边界情况处理正确")
                print(f"📊 数据记录数: {result.get('totalRecords', 0)}")
            else:
                error_detail = response.json().get('detail', '未知错误')
                print(f"❌ 边界情况处理失败: {error_detail}")
                
        except Exception as e:
            print(f"❌ 异常: {str(e)}")

if __name__ == "__main__":
    # 运行所有测试
    test_string_time_formats()
    test_parameter_validation()
    test_edge_cases()
    
    print(f"\n{'='*60}")
    print("🎯 历史数据查询接口测试完成!")
    print("\n功能总结:")
    print("✅ 支持多种时间格式（毫秒时间戳、字符串格式）")
    print("✅ 完整的参数验证（PID参数范围检查）")
    print("✅ 时间范围验证（开始时间 < 结束时间）")
    print("✅ 错误处理和清晰的错误提示")
    print("✅ 遵循GET方法查询规范")
    print("✅ 精简的核心参数（移除tags等非核心参数）")