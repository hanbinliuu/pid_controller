#!/usr/bin/env python3
"""
应用启动时初始化定时任务
"""
import logging
import os
import fcntl
import threading

from api.tasks.loop_perf_stats_task import calc_loop_performance
from api.tasks.load_loop_info import load_loop_list_and_sync
from api.tasks.calc_device_stats_task import calc_device_statistics
from api.tasks.cron_tasks import task_manager
from api.services.loop_monitoring_service import LoopMonitoringService

logger = logging.getLogger(__name__)

# 定时任务初始化的文件锁(用于扩展为分布式锁或仅在一个worker中执行)
_INIT_LOCK_FILE = "./lock/cron_tasks_init.lock"
_init_lock_fd = None
_init_lock = threading.Lock()


def _acquire_init_lock() -> bool:
    """
    获取初始化锁
    确保在多 worker 环境下，只有一个 worker 执行初始化
    使用文件锁确保跨进程安全
    """
    global _init_lock_fd
    
    try:
        # 创建锁文件目录
        lock_dir = "./lock"
        if not os.path.exists(lock_dir):
            os.makedirs(lock_dir, exist_ok=True)
        
        # 打开锁文件
        _init_lock_fd = open(_INIT_LOCK_FILE, 'w')
        
        # 尝试获取文件锁（非阻塞）
        fcntl.flock(_init_lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # 写入进程 ID
        _init_lock_fd.truncate(0)
        _init_lock_fd.write(str(os.getpid()))
        _init_lock_fd.flush()
        
        logger.debug(f"成功获取定时任务初始化锁 (PID: {os.getpid()})")
        return True
        
    except IOError:
        # 无法获取锁，読仁老其他 worker 正在执行初始化
        if _init_lock_fd:
            _init_lock_fd.close()
            _init_lock_fd = None
        logger.debug(f"无法获取定时任务初始化锁，不执行初始化 (PID: {os.getpid()})")
        return False
    except Exception as e:
        logger.warning(f"获取定时任务初始化锁時發生異常: {str(e)}")
        if _init_lock_fd:
            _init_lock_fd.close()
            _init_lock_fd = None
        return False


def _release_init_lock():
    """
    释放初始化锁
    """
    global _init_lock_fd
    
    if not _init_lock_fd:
        return
    
    try:
        fcntl.flock(_init_lock_fd.fileno(), fcntl.LOCK_UN)
        _init_lock_fd.close()
        _init_lock_fd = None
        logger.debug(f"成功释放定时任务初始化锁 (PID: {os.getpid()})")
    except Exception as e:
        logger.warning(f"释放定时任务初始化锁時發生異常: {str(e)}")


def init_cron_tasks():
    """
    初始化定时任务
    仅在获取初始化锁的 worker 中执行
    其他 worker 会与待，需要下次启动时重新尝试
    """
    from core.config import Config
    
    # 尝试获取初始化锁
    if not _acquire_init_lock():
        # 没有获取锁，読仁老其他 worker 应该已经进行初始化
        logger.info("不是第一个获取锁的 worker，不执行定时任务初始化")
        return
    
    try:
        # 检查是否已经初始化（防止重複初始化）
        if len(task_manager.tasks) > 0:
            logger.info("定时任务已经初始化过，跳过")
            return
        
        logger.info(f"初始化定时任务... (不是单进程，使用了决策锁)")
        
        try:
            # 注册模型树加载任务
            if Config.TASK_LOAD_MODEL_TREE_ENABLE:
                logger.info(f"注册模型树加载任务, Cron: {Config.TASK_LOAD_MODEL_TREE_CRON}")
                
                success = task_manager.register_task(
                    task_id='load_model_tree',
                    cron_expression=Config.TASK_LOAD_MODEL_TREE_CRON,
                    task_func=load_loop_list_and_sync,
                    task_args={},
                    enable_multi_worker=True
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
                    task_args={'max_workers': Config.TASK_LOOP_PERFORMANCE_MAX_WORKERS},
                    enable_multi_worker=True
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
                    task_args={},
                    enable_multi_worker=True
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
    finally:
        # 释放初始化锁
        _release_init_lock()


def shutdown_cron_tasks():
    """
    应用关闭时停止所有定时任务
    所有worker都可以参与关闭
    """
    try:
        logger.info("关闭所有定时任务...")
        task_manager.stop_all()
        logger.info("✓ 所有定时任务已停止")
    except Exception as e:
        logger.error(f"关闭定时任务失败: {str(e)}")