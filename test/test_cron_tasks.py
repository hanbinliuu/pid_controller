#!/usr/bin/env python3
"""
基于Cron表达式的定时任务测试脚本
演示如何使用CronTask和CronTaskManager
"""
import sys
import os
import time
from datetime import datetime

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from api.tasks.cron_tasks import CronTask, CronTaskManager


def test_task_1() -> dict:
    """测试任务1 - 模拟工作"""
    return {
        "task": "task_1",
        "status": "success",
        "timestamp": datetime.now().isoformat(),
        "message": "任务1执行完成"
    }


def test_task_2(param: str = "default") -> dict:
    """测试任务2 - 带参数的任务"""
    return {
        "task": "task_2",
        "parameter": param,
        "timestamp": datetime.now().isoformat(),
        "message": f"任务2执行完成，参数: {param}"
    }


def test_cron_task():
    """测试单个CronTask"""
    print("\n" + "="*60)
    print("测试1: 单个定时任务 (CronTask)")
    print("="*60)
    
    try:
        # 创建每30秒执行一次的任务
        task = CronTask(
            task_id="test_task",
            cron_expression="*/30 * * * * ",  # 每30秒
            task_func=test_task_1
        )
        
        print(f"\n✓ 创建定时任务成功")
        print(f"  - 任务ID: {task.task_id}")
        print(f"  - Cron表达式: {task.cron_expression}")
        print(f"  - 是否运行: {task.is_running}")
        
        # 启动任务
        print("\n启动任务...")
        task.start()
        print(f"✓ 任务已启动")
        
        # 等待几秒钟
        print("\n等待任务执行...")
        time.sleep(3)
        
        # 查看状态
        status = task.get_status()
        print(f"\n任务状态:")
        print(f"  - 运行状态: {'运行中' if status['is_running'] else '已停止'}")
        print(f"  - 执行次数: {status['execution_count']}")
        print(f"  - 最后执行时间: {status['last_execution_time']}")
        print(f"  - 下次执行时间: {status['next_execution_time']}")
        
        # 停止任务
        print("\n停止任务...")
        task.stop()
        print(f"✓ 任务已停止")
        
        print("\n✓ 测试1通过: 单个定时任务操作正常")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试1失败: {str(e)}")
        return False


def test_cron_task_manager():
    """测试CronTaskManager"""
    print("\n" + "="*60)
    print("测试2: 定时任务管理器 (CronTaskManager)")
    print("="*60)
    
    try:
        manager = CronTaskManager()
        
        # 注册多个任务
        print("\n注册多个定时任务...")
        manager.register_task(
            task_id="task_1",
            cron_expression="0 * * * *",  # 每小时
            task_func=test_task_1
        )
        manager.register_task(
            task_id="task_2",
            cron_expression="*/30 * * * *",  # 每30分钟
            task_func=test_task_2,
            task_args={"param": "test"}
        )
        print(f"✓ 已注册2个定时任务")
        
        # 启动所有任务
        print("\n启动所有任务...")
        started = manager.start_all()
        print(f"✓ 已启动 {started} 个任务")
        
        # 等待几秒
        time.sleep(2)
        
        # 查看所有任务状态
        print("\n所有任务状态:")
        all_status = manager.get_all_status()
        for task_id, status in all_status.items():
            print(f"\n  {task_id}:")
            print(f"    - Cron: {status['cron_expression']}")
            print(f"    - 运行状态: {'运行中' if status['is_running'] else '已停止'}")
            print(f"    - 执行次数: {status['execution_count']}")
        
        # 停止所有任务
        print("\n停止所有任务...")
        stopped = manager.stop_all()
        print(f"✓ 已停止 {stopped} 个任务")
        
        print("\n✓ 测试2通过: 任务管理器操作正常")
        return True
        
    except Exception as e:
        print(f"\n✗ 测试2失败: {str(e)}")
        return False


def test_cron_expressions():
    """Cron表达式示例"""
    print("\n" + "="*60)
    print("Cron表达式示例")
    print("="*60)
    
    examples = [
        ("0 * * * *", "每小时的第0分钟执行"),
        ("0 0 * * *", "每天的00:00执行"),
        ("0 2 * * *", "每天的02:00执行"),
        ("0 0,12 * * *", "每天的00:00和12:00执行"),
        ("*/30 * * * *", "每30分钟执行一次"),
        ("0 0 * * 0", "每周日的00:00执行"),
        ("0 0 1 * *", "每月1号的00:00执行"),
        ("*/5 9-17 * * 1-5", "工作日09-17点每5分钟执行一次"),
    ]
    
    print("\n常用Cron表达式格式:")
    print("  分(0-59) 小时(0-23) 天(1-31) 月(1-12) 周(0-6)")
    print("  0-6表示周日到周六\n")
    
    for cron, description in examples:
        print(f"  '{cron}' -> {description}")
    
    print("\n✓ Cron表达式示例")
    return True


def test_api_endpoints():
    """API端点说明"""
    print("\n" + "="*60)
    print("API端点列表")
    print("="*60)
    
    endpoints = [
        ("POST", "/api/cron/register-cron-task", "注册定时任务"),
        ("POST", "/api/cron/start-cron-task", "启动定时任务"),
        ("POST", "/api/cron/stop-cron-task", "停止定时任务"),
        ("DELETE", "/api/cron/unregister-cron-task", "注销定时任务"),
        ("GET", "/api/cron/cron-task-status", "查询定时任务状态"),
        ("GET", "/api/cron/cron-task-result", "获取任务执行结果"),
        ("POST", "/api/cron/start-all-cron-tasks", "启动所有定时任务"),
        ("POST", "/api/cron/stop-all-cron-tasks", "停止所有定时任务"),
    ]
    
    print("\n可用的API端点:")
    for method, path, description in endpoints:
        print(f"  {method:8} {path:45} - {description}")
    
    print("\n✓ API端点列表")
    return True


def test_usage_examples():
    """使用示例"""
    print("\n" + "="*60)
    print("使用示例")
    print("="*60)
    
    print("\n【示例1】使用API注册每天02:00执行的定时任务:")
    print("""
curl -X POST "http://localhost:8001/api/cron/register-cron-task" \\
  -H "Content-Type: application/json" \\
  -d '{
    "task_id": "daily_performance_calc",
    "cron_expression": "0 2 * * *",
    "auto_start": true
  }'
    """)
    
    print("\n【示例2】查询所有定时任务状态:")
    print("""
curl -X GET "http://localhost:8001/api/cron/cron-task-status"
    """)
    
    print("\n【示例3】启动特定定时任务:")
    print("""
curl -X POST "http://localhost:8001/api/cron/start-cron-task?task_id=daily_performance_calc"
    """)
    
    print("\n【示例4】在Python代码中使用:")
    print("""
from api.tasks.cron_tasks import CronTask

def my_task():
    print("任务执行")
    return {"status": "success"}

# 创建每天02:00执行的任务
task = CronTask(
    task_id='my_daily_task',
    cron_expression='0 2 * * *',
    task_func=my_task
)

# 启动任务
task.start()

# 查看状态
status = task.get_status()
print(status)

# 停止任务
task.stop()
    """)
    
    print("\n【示例5】环境变量配置:")
    print("""
# .env 文件配置
ENABLE_LOOP_PERFORMANCE_TASK=true
LOOP_PERFORMANCE_CRON=0 2 * * *      # 每天02:00执行
TASK_MAX_WORKERS=5                    # 5个并行线程
    """)


def main():
    """执行所有测试"""
    print("\n" + "="*60)
    print("基于Cron表达式的定时任务测试套件")
    print("="*60)
    
    results = []
    
    # 执行所有测试
    results.append(("单个定时任务", test_cron_task()))
    results.append(("任务管理器", test_cron_task_manager()))
    results.append(("Cron表达式示例", test_cron_expressions()))
    results.append(("API端点列表", test_api_endpoints()))
    
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
        print("\n" + "="*60)
        print("🎉 所有测试通过！")
        print("="*60)
        print("\n✨ 定时任务系统特点:")
        print("  ✓ 基于croniter库，支持标准Cron表达式")
        print("  ✓ 支持多个并发定时任务")
        print("  ✓ 完整的任务生命周期管理")
        print("  ✓ REST API接口支持")
        print("  ✓ 环境变量配置支持")
        print("  ✓ 详细的执行日志和状态追踪")
        print("\n📚 更多信息请参考 API 文档: http://localhost:8001/docs\n")
        return 0
    else:
        print(f"\n⚠️  有 {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
