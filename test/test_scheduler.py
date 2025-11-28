#!/usr/bin/env python3
"""
定时任务调度器测试脚本
演示如何使用定时任务功能计算全部回路的性能状态
"""
import sys
import os
import time
import json
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from api.scheduler import (
    LoopPerformanceScheduler,
    ScheduleFrequency,
    SchedulerManager,
    global_scheduler_manager
)


def test_single_scheduler():
    """测试单个调度器"""
    print("\n" + "="*60)
    print("测试1: 单个调度器基本操作")
    print("="*60)
    
    try:
        # 创建调度器（每小时执行一次）
        scheduler = LoopPerformanceScheduler(
            max_workers=5,
            frequency=ScheduleFrequency.HOURLY
        )
        
        print(f"\n✓ 创建调度器成功")
        print(f"  - 调度频率: {scheduler.frequency.value}")
        print(f"  - 最大工作线程: {scheduler.max_workers}")
        
        # 启动调度器
        print("\n启动调度器...")
        scheduler.start()
        print(f"✓ 调度器已启动")
        
        # 查看状态
        status = scheduler.get_status()
        print(f"\n调度器状态:")
        print(f"  - 运行状态: {'运行中' if status['is_running'] else '已停止'}")
        print(f"  - 执行次数: {status['execution_count']}")
        
        # 停止调度器
        print("\n停止调度器...")
        scheduler.stop()
        print(f"✓ 调度器已停止")
        
        print("\n✓ 测试1通过: 单个调度器操作正常")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试1失败: {str(e)}")
        return False


def test_scheduler_manager():
    """测试调度器管理器"""
    print("\n" + "="*60)
    print("测试2: 调度器管理器操作")
    print("="*60)
    
    try:
        manager = SchedulerManager()
        
        # 添加多个调度器
        print("\n添加多个调度器...")
        manager.add_scheduler(
            "scheduler_hourly",
            ScheduleFrequency.HOURLY,
            max_workers=5
        )
        manager.add_scheduler(
            "scheduler_daily",
            ScheduleFrequency.DAILY,
            max_workers=10
        )
        print(f"✓ 成功添加2个调度器")
        
        # 启动所有调度器
        print("\n启动所有调度器...")
        started = manager.start_all()
        print(f"✓ 启动了 {started} 个调度器")
        
        # 获取所有调度器状态
        print("\n查询所有调度器状态:")
        all_status = manager.get_all_status()
        for scheduler_id, status in all_status.items():
            print(f"\n  {scheduler_id}:")
            print(f"    - 运行状态: {'运行中' if status['is_running'] else '已停止'}")
            print(f"    - 调度频率: {status['frequency']}")
            print(f"    - 执行次数: {status['execution_count']}")
        
        # 停止所有调度器
        print("\n停止所有调度器...")
        stopped = manager.stop_all()
        print(f"✓ 停止了 {stopped} 个调度器")
        
        print("\n✓ 测试2通过: 调度器管理器操作正常")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试2失败: {str(e)}")
        return False


def test_global_manager():
    """测试全局调度器管理器"""
    print("\n" + "="*60)
    print("测试3: 全局调度器管理器")
    print("="*60)
    
    try:
        # 添加调度器
        print("\n使用全局管理器添加调度器...")
        global_scheduler_manager.add_scheduler(
            "global_test",
            ScheduleFrequency.DAILY,
            max_workers=5
        )
        print(f"✓ 调度器已添加")
        
        # 启动调度器
        print("\n启动调度器...")
        global_scheduler_manager.start_scheduler("global_test")
        print(f"✓ 调度器已启动")
        
        # 等待一段时间，让调度器执行一次
        print("\n等待调度器执行...")
        time.sleep(2)
        
        # 获取最后的执行结果（如果有的话）
        print("\n查询调度器状态:")
        status = global_scheduler_manager.get_scheduler_status("global_test")
        if status:
            print(f"  - 运行状态: {'运行中' if status['is_running'] else '已停止'}")
            print(f"  - 执行次数: {status['execution_count']}")
            print(f"  - 最后执行时间: {status['last_execution_time']}")
            print(f"  - 下次执行时间: {status['next_execution_time']}")
        
        # 停止调度器
        print("\n停止调度器...")
        global_scheduler_manager.stop_scheduler("global_test")
        print(f"✓ 调度器已停止")
        
        # 删除调度器
        print("\n删除调度器...")
        global_scheduler_manager.remove_scheduler("global_test")
        print(f"✓ 调度器已删除")
        
        print("\n✓ 测试3通过: 全局管理器操作正常")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试3失败: {str(e)}")
        return False


def test_api_integration():
    """测试API集成示例"""
    print("\n" + "="*60)
    print("测试4: API集成示例")
    print("="*60)
    
    try:
        print("\n✓ 以下是可用的API端点:")
        print("\n1. 创建定时任务:")
        print("   POST /api/scheduler/create-scheduler")
        print("   参数: scheduler_id, frequency, max_workers, auto_start")
        
        print("\n2. 启动定时任务:")
        print("   POST /api/scheduler/start-scheduler")
        print("   参数: scheduler_id")
        
        print("\n3. 停止定时任务:")
        print("   POST /api/scheduler/stop-scheduler")
        print("   参数: scheduler_id")
        
        print("\n4. 删除定时任务:")
        print("   DELETE /api/scheduler/remove-scheduler")
        print("   参数: scheduler_id")
        
        print("\n5. 查询定时任务状态:")
        print("   GET /api/scheduler/scheduler-status")
        print("   参数: scheduler_id (可选，为空时查询所有)")
        
        print("\n6. 查询最后执行结果:")
        print("   GET /api/scheduler/scheduler-result")
        print("   参数: scheduler_id")
        
        print("\n7. 启动所有定时任务:")
        print("   POST /api/scheduler/start-all-schedulers")
        
        print("\n8. 停止所有定时任务:")
        print("   POST /api/scheduler/stop-all-schedulers")
        
        print("\n✓ 测试4通过: API端点列表已显示")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试4失败: {str(e)}")
        return False


def test_usage_examples():
    """使用示例"""
    print("\n" + "="*60)
    print("使用示例")
    print("="*60)
    
    print("\n【示例1】使用API创建并启动每小时的定时任务:")
    print("""
curl -X POST "http://localhost:8001/api/scheduler/create-scheduler" \\
  -H "Content-Type: application/json" \\
  -d '{
    "scheduler_id": "scheduler_hourly",
    "frequency": "hourly",
    "max_workers": 5,
    "auto_start": true
  }'
    """)
    
    print("\n【示例2】查询所有定时任务状态:")
    print("""
curl -X GET "http://localhost:8001/api/scheduler/scheduler-status"
    """)
    
    print("\n【示例3】查询特定定时任务的最后执行结果:")
    print("""
curl -X GET "http://localhost:8001/api/scheduler/scheduler-result?scheduler_id=scheduler_hourly"
    """)
    
    print("\n【示例4】停止特定定时任务:")
    print("""
curl -X POST "http://localhost:8001/api/scheduler/stop-scheduler?scheduler_id=scheduler_hourly"
    """)
    
    print("\n【示例5】Python代码集成:")
    print("""
from api.scheduler import global_scheduler_manager, ScheduleFrequency

# 创建每日定时任务
global_scheduler_manager.add_scheduler(
    scheduler_id='my_daily_task',
    frequency=ScheduleFrequency.DAILY,
    max_workers=10
)

# 启动任务
global_scheduler_manager.start_scheduler('my_daily_task')

# 查询状态
status = global_scheduler_manager.get_scheduler_status('my_daily_task')
print(f"任务运行状态: {status['is_running']}")

# 获取最后的执行结果
result = global_scheduler_manager.get_last_result('my_daily_task')
print(f"执行结果: {result}")
    """)


def main():
    """执行所有测试"""
    print("\n" + "="*60)
    print("定时任务调度器测试套件")
    print("="*60)
    
    results = []
    
    # 执行所有测试
    results.append(("单个调度器基本操作", test_single_scheduler()))
    results.append(("调度器管理器操作", test_scheduler_manager()))
    results.append(("全局管理器", test_global_manager()))
    results.append(("API集成示例", test_api_integration()))
    
    # 输出测试总结
    print("\n" + "="*60)
    print("测试总结")
    print("="*60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status}: {test_name}")
    
    print(f"\n总体: {passed}/{total} 个测试通过")
    
    # 显示使用示例
    if passed == total:
        test_usage_examples()
        print("\n🎉 所有测试通过！定时任务功能正常运行")
        print("\n📚 更多信息请参考 API 文档: http://localhost:8001/docs")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
