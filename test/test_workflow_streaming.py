#!/usr/bin/env python3
"""
测试 run_workflow 流式调用功能
"""

import requests
import json
import time


def test_workflow_blocking():
    """测试阻塞模式的 workflow 调用"""
    print("=" * 70)
    print("测试 1: 阻塞模式 (blocking)")
    print("=" * 70)
    
    base_url = "http://localhost:8001"
    
    test_data = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "loop_type": "temperature_control",
        "response_mode": "blocking"
    }
    
    print(f"📋 请求数据:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print("-" * 70)
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            timeout=180
        )
        elapsed = time.time() - start_time
        
        print(f"⏱️  响应时间: {elapsed:.2f}秒")
        print(f"📊 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✅ 阻塞模式调用成功!")
            print(f"响应数据:")
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
    
    print()


def test_workflow_streaming():
    """测试流式模式的 workflow 调用"""
    print("=" * 70)
    print("测试 2: 流式模式 (streaming)")
    print("=" * 70)
    
    base_url = "http://localhost:8001"
    
    test_data = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "loop_type": "temperature_control",
        "response_mode": "streaming"
    }
    
    print(f"📋 请求数据:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print("-" * 70)
    print("🔄 开始接收流式数据...\n")
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            stream=True,
            timeout=180
        )
        
        print(f"📊 状态码: {response.status_code}")
        print(f"📦 Content-Type: {response.headers.get('Content-Type')}")
        print("-" * 70)
        
        if response.status_code == 200:
            print("✅ 开始接收流式响应:\n")
            
            event_count = 0
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    print(f"📨 [{event_count}] {decoded_line}")
                    
                    # 尝试解析 SSE 数据
                    if decoded_line.startswith('data: '):
                        try:
                            data_content = decoded_line[6:]  # 去掉 'data: ' 前缀
                            json_data = json.loads(data_content)
                            print(f"   └─ 解析数据: {json.dumps(json_data, indent=6, ensure_ascii=False)}")
                        except json.JSONDecodeError:
                            print(f"   └─ 非JSON数据: {data_content}")
                    
                    event_count += 1
                    print()
            
            elapsed = time.time() - start_time
            print("-" * 70)
            print(f"✅ 流式响应完成!")
            print(f"⏱️  总耗时: {elapsed:.2f}秒")
            print(f"📊 接收事件数: {event_count}")
        else:
            print(f"❌ 请求失败: {response.status_code}")
            print(f"错误信息: {response.text}")
            
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
    except requests.exceptions.ConnectionError:
        print("❌ 连接失败，请确保服务器正在运行")
    except Exception as e:
        print(f"❌ 异常: {str(e)}")
    
    print()


def test_workflow_streaming_with_custom_auth():
    """测试带自定义授权的流式调用"""
    print("=" * 70)
    print("测试 3: 流式模式 + 自定义授权")
    print("=" * 70)
    
    base_url = "http://localhost:8001"
    
    test_data = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "loop_type": "temperature_control",
        "response_mode": "streaming"
    }
    
    headers = {
        "Authorization": "Bearer custom-token-for-testing"
    }
    
    print(f"📋 请求数据:")
    print(json.dumps(test_data, indent=2, ensure_ascii=False))
    print(f"🔑 授权令牌: custom-token-for-testing")
    print("-" * 70)
    
    try:
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            headers=headers,
            stream=True,
            timeout=180
        )
        
        print(f"📊 状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("✅ 流式响应成功（尽管外部服务可能拒绝自定义令牌）")
            
            for line in response.iter_lines():
                if line:
                    print(f"📨 {line.decode('utf-8')}")
        else:
            print(f"⚠️  请求失败（这是预期的，外部服务可能拒绝测试令牌）")
            print(f"状态码: {response.status_code}")
            print(f"响应: {response.text}")
            
    except Exception as e:
        print(f"❌ 异常: {str(e)}")
    
    print()


def compare_modes():
    """比较阻塞模式和流式模式的性能"""
    print("=" * 70)
    print("测试 4: 性能对比")
    print("=" * 70)
    
    base_url = "http://localhost:8001"
    
    test_data_base = {
        "start_time": "2025-10-08 17:30:37",
        "end_time": "2025-10-08 18:00:37",
        "loop_type": "temperature_control"
    }
    
    results = {}
    
    # 测试阻塞模式
    print("📊 测试阻塞模式性能...")
    test_data = {**test_data_base, "response_mode": "blocking"}
    try:
        start = time.time()
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            timeout=180
        )
        elapsed = time.time() - start
        results['blocking'] = {
            'time': elapsed,
            'status': response.status_code,
            'success': response.status_code == 200
        }
        print(f"   └─ 耗时: {elapsed:.2f}秒, 状态: {response.status_code}")
    except Exception as e:
        results['blocking'] = {'error': str(e)}
        print(f"   └─ 错误: {str(e)}")
    
    # 测试流式模式
    print("📊 测试流式模式性能...")
    test_data = {**test_data_base, "response_mode": "streaming"}
    try:
        start = time.time()
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            stream=True,
            timeout=180
        )
        
        # 记录首字节时间
        first_byte_time = None
        event_count = 0
        
        for line in response.iter_lines():
            if line and first_byte_time is None:
                first_byte_time = time.time() - start
            if line:
                event_count += 1
        
        elapsed = time.time() - start
        results['streaming'] = {
            'time': elapsed,
            'first_byte_time': first_byte_time,
            'event_count': event_count,
            'status': response.status_code,
            'success': response.status_code == 200
        }
        print(f"   └─ 总耗时: {elapsed:.2f}秒, 首字节: {first_byte_time:.2f}秒, 事件数: {event_count}")
    except Exception as e:
        results['streaming'] = {'error': str(e)}
        print(f"   └─ 错误: {str(e)}")
    
    print("\n" + "=" * 70)
    print("📈 性能对比结果:")
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print("=" * 70)


if __name__ == "__main__":
    print("\n🔧 run_workflow 流式调用测试工具")
    print("=" * 70)
    print("⚠️  注意：确保API服务已启动在 http://localhost:8001")
    print("=" * 70)
    print()
    
    # 运行所有测试
    test_workflow_blocking()
    test_workflow_streaming()
    test_workflow_streaming_with_custom_auth()
    compare_modes()
    
    print("\n" + "=" * 70)
    print("🎯 测试完成!")
    print("=" * 70)
    print("\n功能总结:")
    print("✅ 1. 阻塞模式调用 (blocking)")
    print("✅ 2. 流式模式调用 (streaming)")
    print("✅ 3. 自定义授权支持")
    print("✅ 4. 性能对比分析")
    print("✅ 5. SSE 事件流处理")
    print("✅ 6. 错误处理和超时控制")
    print()
