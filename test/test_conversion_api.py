#!/usr/bin/env python3
"""
PID参数转换API测试脚本
"""

import requests
import json


def test_conversion_api():
    """测试PID转换API接口"""
    base_url = "http://localhost:8001"
    
    print("=" * 60)
    print("PID参数转换API测试")
    print("=" * 60)
    
    # 测试1: PID转经典控制
    print("\n1. 测试PID参数转换为经典控制参数:")
    pid_data = {
        "kp": 2.0,
        "ki": 0.5,
        "kd": 0.1
    }
    
    try:
        response = requests.post(f"{base_url}/api/conversion/pid-to-classical", json=pid_data)
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 转换成功")
            print(f"  输入PID: {result['data']['standard']}")
            print(f"  输出经典控制: {result['data']['classical']}")
        else:
            print(f"✗ 转换失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试2: 经典控制转PID
    print("\n2. 测试经典控制参数转换为PID参数:")
    classical_data = {
        "proportional_band": 50.0,
        "integral_time": 4.0,
        "derivative_time": 0.05
    }
    
    try:
        response = requests.post(f"{base_url}/api/conversion/classical-to-pid", json=classical_data)
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 转换成功")
            print(f"  输入经典控制: {result['data']['classical']}")
            print(f"  输出PID: {result['data']['standard']}")
        else:
            print(f"✗ 转换失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试3: 参数格式化
    print("\n3. 测试参数格式化:")
    try:
        response = requests.post(f"{base_url}/api/conversion/format-parameters", json=pid_data)
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 格式化成功")
            print(f"  标准PID: {result['data']['standard']}")
            print(f"  经典控制: {result['data']['classical']}")
        else:
            print(f"✗ 格式化失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试4: 参数验证
    print("\n4. 测试参数验证:")
    try:
        response = requests.post(f"{base_url}/api/conversion/validate-parameters", json=pid_data)
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 验证成功")
            print(f"  验证结果: {result}")
        else:
            print(f"✗ 验证失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试5: 获取转换公式
    print("\n5. 测试获取转换公式:")
    try:
        response = requests.get(f"{base_url}/api/conversion/conversion-formulas")
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 获取成功")
            print(f"  PID转经典控制公式:")
            for key, formula in result['data']['pid_to_classical'].items():
                print(f"    {key}: {formula}")
        else:
            print(f"✗ 获取失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试6: 获取转换示例
    print("\n6. 测试获取转换示例:")
    try:
        response = requests.get(f"{base_url}/api/conversion/examples")
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 获取成功")
            print(f"  示例数量: {len(result['data'])}")
            for example in result['data'][:2]:  # 只显示前两个示例
                print(f"    {example['name']}: {example['description']}")
        else:
            print(f"✗ 获取失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    # 测试7: 异常情况
    print("\n7. 测试异常情况:")
    invalid_data = {
        "kp": -1.0,  # 无效的负数
        "ki": 0.5,
        "kd": 0.1
    }
    
    try:
        response = requests.post(f"{base_url}/api/conversion/validate-parameters", json=invalid_data)
        if response.status_code == 200:
            result = response.json()
            print(f"✓ 异常处理正确")
            print(f"  验证消息: {result['message']}")
        else:
            print(f"✗ 异常处理失败: {response.text}")
    except Exception as e:
        print(f"✗ 请求失败: {e}")
    
    print("\n" + "=" * 60)
    print("API测试完成!")


if __name__ == "__main__":
    print("请确保API服务器已启动 (http://localhost:8001)")
    input("按Enter键开始测试...")
    test_conversion_api()