#!/usr/bin/env python3
"""
应用启动时初始化定时任务
"""
import logging

from api.tasks.loop_perf_stats_task import calc_loop_performance
from api.tasks.load_loop_info import load_loop_list_and_sync
from api.tasks.calc_device_stats_task import calc_device_statistics
from api.tasks.cron_tasks import task_manager
from api.services.loop_monitoring_service import LoopMonitoringService

logger = logging.getLogger(__name__)




def init_cron_tasks():
    """
    初始化定时任务
    从配置文件加载任务配置
    """
    from core.config import Config
    
    logger.info("初始化定时任务...")
    
    try:
        # 注册模型树加载任务
        if Config.TASK_LOAD_MODEL_TREE_ENABLE:
            logger.info(f"注册模型树加载任务, Cron: {Config.TASK_LOAD_MODEL_TREE_CRON}")
            
            success = task_manager.register_task(
                task_id='load_model_tree',
                cron_expression=Config.TASK_LOAD_MODEL_TREE_CRON,
                task_func=load_loop_list_and_sync,
                task_args={}
            )
            
            if success:
                # 自动启动任务
                task_manager.start_task('load_model_tree')
                logger.info("✓ 模型树加载任务已启动")
            else:
                logger.warning("模型树加载任务注册失败")
        
        # 注册回路性能计算任务
        if Config.TASK_LOOP_PERFORMANCE_ENABLE:
            logger.info(f"注册回路性能计算任务, Cron: {Config.TASK_LOOP_PERFORMANCE_CRON}")
            
            success = task_manager.register_task(
                task_id='calculate_loop_performance',
                cron_expression=Config.TASK_LOOP_PERFORMANCE_CRON,
                task_func=calc_loop_performance,
                task_args={'max_workers': Config.TASK_LOOP_PERFORMANCE_MAX_WORKERS}
            )
            
            if success:
                # 自动启动任务
                task_manager.start_task('calculate_loop_performance')
                logger.info("✓ 回路性能计算任务已启动")
            else:
                logger.warning("回路性能计算任务注册失败")
        
        # 注册装置性能统计任务
        if Config.TASK_DEVICE_STATS_ENABLE:
            logger.info(f"注册装置性能统计任务, Cron: {Config.TASK_DEVICE_STATS_CRON}")
            
            success = task_manager.register_task(
                task_id='calc_device_statistics',
                cron_expression=Config.TASK_DEVICE_STATS_CRON,
                task_func=calc_device_statistics,
                task_args={}
            )
            
            if success:
                # 自动启动任务
                task_manager.start_task('calc_device_statistics')
                logger.info("✓ 装置性能统计任务已启动")
            else:
                logger.warning("装置性能统计任务注册失败")
        
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
