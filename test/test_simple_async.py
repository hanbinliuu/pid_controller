#!/usr/bin/env python3
"""
测试异步代理接口不阻塞其他接口
"""

import requests
import threading
import time
import json
from datetime import datetime

def test_other_endpoints():
    """测试其他接口的可访问性"""
    base_url = "http://localhost:8001"
    
    endpoints = [
        "/health",
        "/api/proxy/workflow/config", 
        "/api/proxy/health"
    ]
    
    results = []
    
    print("🔍 开始测试其他接口的可访问性...")
    
    for endpoint in endpoints:
        start_time = time.time()
        try:
            response = requests.get(f"{base_url}{endpoint}", timeout=10)
            end_time = time.time()
            
            status_icon = "✅" if response.status_code == 200 else "❌"
            print(f"   {status_icon} {endpoint} - 状态: {response.status_code}, 响应时间: {round(end_time - start_time, 3)}秒")
            
            results.append({
                "endpoint": endpoint,
                "status": response.status_code,
                "response_time": round(end_time - start_time, 3),
                "accessible": response.status_code == 200
            })
        except Exception as e:
            end_time = time.time()
            print(f"   ❌ {endpoint} - 错误: {str(e)}, 响应时间: {round(end_time - start_time, 3)}秒")
            results.append({
                "endpoint": endpoint,
                "status": "error",
                "response_time": round(end_time - start_time, 3),
                "accessible": False,
                "error": str(e)
            })
    
    return results

def test_workflow_proxy():
    """测试工作流代理接口"""
    base_url = "http://localhost:8001"
    
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
    
    print("📡 开始测试代理接口...")
    start_time = time.time()
    
    try:
        response = requests.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            timeout=180
        )
        end_time = time.time()
        
        if response.status_code == 200:
            print(f"✅ 代理接口调用成功！响应时间: {round(end_time - start_time, 3)}秒")
            return {
                "status": response.status_code,
                "response_time": round(end_time - start_time, 3),
                "success": True
            }
        else:
            print(f"❌ 代理接口调用失败，状态码: {response.status_code}")
            return {
                "status": response.status_code,
                "response_time": round(end_time - start_time, 3),
                "success": False,
                "error": response.text
            }
    except requests.exceptions.Timeout:
        end_time = time.time()
        print(f"❌ 代理接口调用超时，响应时间: {round(end_time - start_time, 3)}秒")
        return {
            "status": "timeout",
            "response_time": round(end_time - start_time, 3),
            "success": False,
            "error": "请求超时"
        }
    except Exception as e:
        end_time = time.time()
        print(f"❌ 代理接口调用异常: {str(e)}")
        return {
            "status": "error",
            "response_time": round(end_time - start_time, 3),
            "success": False,
            "error": str(e)
        }

def concurrent_test():
    """并发测试：同时测试代理接口和其他接口"""
    print("🔄 开始并发测试：检查代理接口是否阻塞其他接口")
    print("=" * 70)
    
    # 用于存储测试结果
    results = {}
    
    # 启动代理接口测试线程
    def proxy_test():
        results['proxy'] = test_workflow_proxy()
    
    # 启动其他接口测试线程
    def other_endpoints_test():
        # 等待1秒，确保代理接口开始执行
        time.sleep(1)
        results['others'] = test_other_endpoints()
    
    # 创建并启动线程
    proxy_thread = threading.Thread(target=proxy_test)
    other_thread = threading.Thread(target=other_endpoints_test)
    
    start_time = time.time()
    
    proxy_thread.start()
    other_thread.start()
    
    # 等待所有线程完成
    proxy_thread.join()
    other_thread.join()
    
    total_time = time.time() - start_time
    
    print(f"\n总测试时间: {round(total_time, 3)}秒")
    
    return results

def main():
    """主测试函数"""
    print("🧪 异步代理接口非阻塞测试")
    print("=" * 70)
    print("目标：验证代理接口调用不会阻塞其他接口的访问")
    print("=" * 70)
    
    # 执行并发测试
    test_results = concurrent_test()
    
    print("\n" + "=" * 70)
    print("📊 测试结果分析")
    print("=" * 70)
    
    # 分析代理接口结果
    proxy_result = test_results.get("proxy", {})
    print(f"🔗 代理接口结果:")
    print(f"   状态: {proxy_result.get('status', 'unknown')}")
    print(f"   响应时间: {proxy_result.get('response_time', 'unknown')}秒")
    print(f"   成功: {'✅' if proxy_result.get('success') else '❌'}")
    
    if proxy_result.get('error'):
        print(f"   错误: {proxy_result['error']}")
    
    # 分析其他接口结果
    other_results = test_results.get("others", [])
    print(f"\n🔍 其他接口可访问性测试:")
    
    accessible_count = 0
    total_count = len(other_results)
    
    for result in other_results:
        if result.get('accessible'):
            accessible_count += 1
    
    # 总结
    print(f"\n🎯 测试总结:")
    print(f"   其他接口可访问性: {accessible_count}/{total_count}")
    
    if accessible_count == total_count:
        print("   ✅ 异步代理接口实现成功！其他接口在代理调用期间仍可正常访问")
        non_blocking = True
    else:
        print("   ❌ 存在阻塞问题，部分接口在代理调用期间无法访问")
        non_blocking = False
    
    print(f"   代理接口性能: {'正常' if proxy_result.get('success') else '异常'}")
    
    return non_blocking and proxy_result.get('success')

if __name__ == "__main__":
    print("开始测试异步代理接口...")
    
    try:
        # 运行测试
        success = main()
        
        print("\n" + "=" * 70)
        if success:
            print("🎉 测试通过！异步代理接口工作正常，不会阻塞其他接口")
        else:
            print("⚠️  测试发现问题，请检查相关配置")
        print("=" * 70)
        
    except KeyboardInterrupt:
        print("\n❌ 测试被用户中断")
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")