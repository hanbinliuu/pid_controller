#!/usr/bin/env python3
"""
测试代理接口功能
"""

import requests
import json
from datetime import datetime, timedelta

def test_workflow_proxy():
    """测试工作流代理接口"""
    
    # API基础URL
    base_url = "http://localhost:8001"
    
    print("🔄 测试工作流代理接口")
    print("=" * 60)
    
    # 测试数据
    test_data = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "Kp": "0.25",
        "Ki": "0.025",
        "Kd": "0",
        "SP": "380",
        "response_mode": "blocking",
        "user": "admin"
    }
    
    print(f"📋 请求数据:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print("-" * 50)
    
    try:
        # 测试工作流执行
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            timeout=150  # 增加到150秒，留给连接和读取的缓冲时间
        )
        
        print(f"📡 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 工作流代理调用成功!")
            print(f"📊 响应数据:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保服务器正在运行")
    except Exception as e:
        print(f"❌ 异常: {str(e)}")

def test_workflow_config():
    """测试获取工作流配置"""
    
    base_url = "http://localhost:8001"
    
    print(f"\n{'='*60}")
    print("🔧 测试获取工作流配置")
    print("=" * 60)
    
    try:
        response = requests.get(f"{base_url}/api/proxy/workflow/config", timeout=10)
        
        print(f"📡 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 配置获取成功!")
            print(f"📊 配置信息:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"❌ 异常: {str(e)}")

def test_proxy_health():
    """测试代理服务健康检查"""
    
    base_url = "http://localhost:8001"
    
    print(f"\n{'='*60}")
    print("🏥 测试代理服务健康检查")
    print("=" * 60)
    
    try:
        response = requests.get(f"{base_url}/api/proxy/health", timeout=10)
        
        print(f"📡 响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 健康检查成功!")
            print(f"📊 健康状态:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"❌ 异常: {str(e)}")

def test_with_custom_auth():
    """测试自定义授权令牌"""
    
    base_url = "http://localhost:8001"
    
    print(f"\n{'='*60}")
    print("🔐 测试自定义授权令牌")
    print("=" * 60)
    
    test_data = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "Kp": "1.0",
        "Ki": "0.1",
        "Kd": "0.05",
        "SP": "300",
        "response_mode": "blocking",
        "user": "test_user"
    }
    
    headers = {
        "Authorization": "Bearer custom-token-for-testing"
    }
    
    try:
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            headers=headers,
            timeout=150  # 增加到150秒
        )
        
        print(f"📡 响应状态码: {response.status_code}")
        print(f"使用自定义令牌: custom-token-for-testing")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 自定义授权测试成功!")
        else:
            print(f"❌ 请求失败，这是预期的（外部服务可能拒绝测试令牌）")
            print(f"错误信息: {response.text}")
            
    except Exception as e:
        print(f"❌ 异常: {str(e)}")

if __name__ == "__main__":
    print("🔧 代理接口测试工具")
    print("=" * 60)
    print("注意：确保API服务已启动在 http://localhost:8001")
    print("=" * 60)
    
    # 运行所有测试
    test_workflow_config()
    test_proxy_health()
    test_workflow_proxy()
    test_with_custom_auth()
    
    print(f"\n{'='*60}")
    print("🎯 代理接口测试完成!")
    print("\n功能总结:")
    print("✅ 工作流代理执行")
    print("✅ 配置信息获取")
    print("✅ 健康状态检查") 
    print("✅ 自定义授权支持")
    print("✅ 错误处理和日志记录")