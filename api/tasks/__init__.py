#!/usr/bin/env python3
"""
应用启动时初始化定时任务
"""
import logging

from api.tasks.calculate_loop_performance import calculate_loop_performance
from api.tasks.cron_tasks import task_manager
from api.services.loop_monitoring_service import LoopMonitoringService

logger = logging.getLogger(__name__)




def init_cron_tasks():
    """
    初始化定时任务
    可通过环境变量配置任务
    """
    import os
    
    logger.info("初始化定时任务...")
    
    try:
        # 从环境变量读取配置
        enable_loop_performance = os.getenv('ENABLE_LOOP_PERFORMANCE_TASK', 'true').lower() == 'true'
        loop_performance_cron = os.getenv('LOOP_PERFORMANCE_CRON', '0 * * * *')  # 默认每小时
        max_workers = int(os.getenv('TASK_MAX_WORKERS', '5'))
        
        if enable_loop_performance:
            logger.info(f"注册回路性能计算任务, Cron: {loop_performance_cron}")
            
            success = task_manager.register_task(
                task_id='calculate_loop_performance',
                cron_expression=loop_performance_cron,
                task_func=calculate_loop_performance,
                task_args={'max_workers': max_workers}
            )
            
            if success:
                # 自动启动任务
                task_manager.start_task('calculate_loop_performance')
                logger.info("✓ 回路性能计算任务已启动")
            else:
                logger.warning("回路性能计算任务注册失败")
        
        logger.info(f"定时任务初始化完成，共注册 {len(task_manager.tasks)} 个任务")
        
    except Exception as e:
        logger.error(f"初始化定时任务失败: {str(e)}")
        logger.warning("应用将继续启动，但定时任务功能可能不可用")


def shutdown_cron_tasks():
    """应用关闭时停止所有定时任务"""
    try:
        logger.info("关闭所有定时任务...")
        task_manager.stop_all()
        logger.info("✓ 所有定时任务已停止")
    except Exception as e:
        logger.error(f"关闭定时任务失败: {str(e)}")
