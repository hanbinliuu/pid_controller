#!/usr/bin/env python3
"""
测试异步代理接口不阻塞其他接口
"""

import asyncio
import aiohttp
import time
import json
from datetime import datetime

async def test_other_endpoints(session):
    """测试其他接口的可访问性"""
    base_url = "http://localhost:8001"
    
    endpoints = [
        "/health",
        "/api/proxy/workflow/config",
        "/api/proxy/health",
        "/api/analysis/history_data?fields=temperature&start_time=1759915921659&end_time=1759917071978"
    ]
    
    results = []
    
    for endpoint in endpoints:
        start_time = time.time()
        try:
            async with session.get(f"{base_url}{endpoint}") as response:
                end_time = time.time()
                results.append({
                    "endpoint": endpoint,
                    "status": response.status,
                    "response_time": round(end_time - start_time, 3),
                    "accessible": response.status == 200
                })
        except Exception as e:
            end_time = time.time()
            results.append({
                "endpoint": endpoint,
                "status": "error",
                "response_time": round(end_time - start_time, 3),
                "accessible": False,
                "error": str(e)
            })
    
    return results

async def test_workflow_proxy(session):
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
    
    start_time = time.time()
    try:
        async with session.post(
            f"{base_url}/api/proxy/workflow/run",
            json=test_data,
            timeout=aiohttp.ClientTimeout(total=180)
        ) as response:
            end_time = time.time()
            result = await response.json()
            return {
                "status": response.status,
                "response_time": round(end_time - start_time, 3),
                "success": response.status == 200,
                "data": result if response.status == 200 else None
            }
    except asyncio.TimeoutError:
        end_time = time.time()
        return {
            "status": "timeout",
            "response_time": round(end_time - start_time, 3),
            "success": False,
            "error": "请求超时"
        }
    except Exception as e:
        end_time = time.time()
        return {
            "status": "error",
            "response_time": round(end_time - start_time, 3),
            "success": False,
            "error": str(e)
        }

async def concurrent_test():
    """并发测试：同时测试代理接口和其他接口"""
    print("🔄 开始并发测试：检查代理接口是否阻塞其他接口")
    print("=" * 70)
    
    async with aiohttp.ClientSession() as session:
        # 创建任务列表
        tasks = []
        
        # 启动代理接口调用（可能耗时较长）
        print("📡 启动代理接口调用...")
        proxy_task = asyncio.create_task(test_workflow_proxy(session))
        tasks.append(("workflow_proxy", proxy_task))
        
        # 等待一小段时间，确保代理接口开始执行
        await asyncio.sleep(1)
        
        # 在代理接口执行期间，测试其他接口
        print("🔍 在代理接口执行期间，测试其他接口的可访问性...")
        other_endpoints_task = asyncio.create_task(test_other_endpoints(session))
        tasks.append(("other_endpoints", other_endpoints_task))
        
        # 等待所有任务完成
        results = {}
        for name, task in tasks:
            try:
                results[name] = await task
            except Exception as e:
                results[name] = {"error": str(e)}
        
        return results

async def main():
    """主测试函数"""
    print("🧪 异步代理接口非阻塞测试")
    print("=" * 70)
    print("目标：验证代理接口调用不会阻塞其他接口的访问")
    print("=" * 70)
    
    # 执行并发测试
    test_results = await concurrent_test()
    
    print("\n" + "=" * 70)
    print("📊 测试结果分析")
    print("=" * 70)
    
    # 分析代理接口结果
    proxy_result = test_results.get("workflow_proxy", {})
    print(f"🔗 代理接口结果:")
    print(f"   状态: {proxy_result.get('status', 'unknown')}")
    print(f"   响应时间: {proxy_result.get('response_time', 'unknown')}秒")
    print(f"   成功: {'✅' if proxy_result.get('success') else '❌'}")
    
    if proxy_result.get('error'):
        print(f"   错误: {proxy_result['error']}")
    
    # 分析其他接口结果
    other_results = test_results.get("other_endpoints", [])
    print(f"\n🔍 其他接口可访问性测试:")
    
    accessible_count = 0
    total_count = len(other_results)
    
    for result in other_results:
        status_icon = "✅" if result.get('accessible') else "❌"
        print(f"   {status_icon} {result['endpoint']}")
        print(f"      状态: {result['status']}, 响应时间: {result['response_time']}秒")
        
        if result.get('accessible'):
            accessible_count += 1
        
        if result.get('error'):
            print(f"      错误: {result['error']}")
    
    # 总结
    print(f"\n🎯 测试总结:")
    print(f"   其他接口可访问性: {accessible_count}/{total_count}")
    
    if accessible_count == total_count:
        print("   ✅ 异步代理接口实现成功！其他接口在代理调用期间仍可正常访问")
    else:
        print("   ❌ 存在阻塞问题，部分接口在代理调用期间无法访问")
    
    print(f"   代理接口性能: {'正常' if proxy_result.get('success') else '异常'}")
    
    return accessible_count == total_count and proxy_result.get('success')

if __name__ == "__main__":
    print("开始测试异步代理接口...")
    
    try:
        # 运行异步测试
        success = asyncio.run(main())
        
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