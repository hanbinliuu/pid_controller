#!/usr/bin/env python3
"""
基于Cron表达式的定时任务
直接使用croniter定时执行任务，无需复杂的调度器框架
"""
import logging
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List

from croniter import croniter

logger = logging.getLogger(__name__)


class CronTask:
    """
    单个定时任务 - 基于Cron表达式执行
    
    使用示例：
        task = CronTask(
            task_id='calculate_loop_performance',
            cron_expression='0 * * * *',  # 每小时执行一次
            task_func=calculate_loop_performance,
            task_args={'max_workers': 5}
        )
        task.start()
    
    Cron表达式格式（5字段）：
        分(0-59) 小时(0-23) 天(1-31) 月(1-12) 周(0-6)
    
    常用示例：
        '0 * * * *'        - 每小时的第0分钟执行
        '0 0 * * *'        - 每天的00:00执行
        '0 2 * * *'        - 每天的02:00执行
        '*/30 * * * *'      - 每30分钟执行一次
        '0 0,12 * * *'      - 每天的00:00和12:00执行
        '0 0 * * 0'        - 每周日的00:00执行
        '0 0 1 * *'        - 每月1号的00:00执行
    """
    
    def __init__(self,
                 task_id: str,
                 cron_expression: str,
                 task_func: Callable,
                 task_args: Optional[Dict[str, Any]] = None):
        """
        初始化定时任务
        
        Args:
            task_id: 任务ID（唯一标识）
            cron_expression: Cron表达式
            task_func: 要执行的函数
            task_args: 函数参数字典
            
        Raises:
            ValueError: 如果Cron表达式无效
        """
        # 验证Cron表达式
        try:
            croniter(cron_expression)
        except Exception as e:
            raise ValueError(f"无效的Cron表达式: {cron_expression}, 错误: {str(e)}")
        
        self.task_id = task_id
        self.cron_expression = cron_expression
        self.task_func = task_func
        self.task_args = task_args or {}
        
        self.is_running = False
        self.thread = None
        self.last_execution_time = None
        self.last_execution_result = None
        self.last_error = None
        self.execution_count = 0
        self.next_execution_time = None
    
    def _calculate_next_run_time(self) -> datetime:
        """计算下次执行时间"""
        try:
            cron = croniter(self.cron_expression, datetime.now())
            return cron.get_next(datetime)
        except Exception as e:
            logger.error(f"计算下次执行时间失败: {str(e)}")
            return None
    
    def _run_task(self):
        """执行任务的主函数"""
        logger.info(f"定时任务启动 [{self.task_id}] - Cron: {self.cron_expression}")
        
        while self.is_running:
            try:
                # 计算下次执行时间
                self.next_execution_time = self._calculate_next_run_time()
                
                if not self.next_execution_time:
                    logger.error(f"任务 [{self.task_id}] 无法计算下次执行时间")
                    if self.is_running:
                        time.sleep(60)
                    continue
                
                # 计算等待时间
                wait_seconds = (self.next_execution_time - datetime.now()).total_seconds()
                
                if wait_seconds > 0:
                    logger.debug(f"任务 [{self.task_id}] 将在 {wait_seconds:.1f} 秒后执行")
                    
                    # 使用小步长睡眠，以便能及时响应停止信号
                    steps = int(wait_seconds)
                    remaining = wait_seconds - steps
                    
                    for _ in range(steps):
                        if not self.is_running:
                            break
                        time.sleep(1)
                    
                    if remaining > 0 and self.is_running:
                        time.sleep(remaining)
                
                # 执行任务
                if self.is_running:
                    try:
                        logger.info(f"执行定时任务 [{self.task_id}]")
                        start_time = time.time()
                        
                        # 执行任务函数
                        result = self.task_func(**self.task_args)
                        
                        elapsed_time = time.time() - start_time
                        
                        # 更新执行状态
                        self.execution_count += 1
                        self.last_execution_time = datetime.now()
                        self.last_execution_result = result
                        self.last_error = None
                        
                        logger.info(f"定时任务完成 [{self.task_id}], 耗时: {elapsed_time:.2f}秒, "
                                  f"执行次数: {self.execution_count}")
                        
                    except Exception as e:
                        logger.error(f"定时任务执行失败 [{self.task_id}]: {str(e)}")
                        self.execution_count += 1
                        self.last_execution_time = datetime.now()
                        self.last_error = str(e)
                        self.last_execution_result = None
                
            except Exception as e:
                logger.error(f"定时任务循环异常 [{self.task_id}]: {str(e)}")
                self.last_error = str(e)
                
                if self.is_running:
                    time.sleep(60)  # 异常后等待60秒重试
    
    def start(self) -> bool:
        """启动定时任务"""
        if self.is_running:
            logger.warning(f"定时任务已在运行 [{self.task_id}]")
            return False
        
        self.is_running = True
        self.thread = threading.Thread(
            target=self._run_task,
            daemon=True,
            name=f"CronTask-{self.task_id}"
        )
        self.thread.start()
        
        logger.info(f"定时任务已启动 [{self.task_id}]")
        return True
    
    def stop(self) -> bool:
        """停止定时任务"""
        if not self.is_running:
            logger.warning(f"定时任务未在运行 [{self.task_id}]")
            return False
        
        self.is_running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info(f"定时任务已停止 [{self.task_id}]")
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """获取任务状态"""
        return {
            "task_id": self.task_id,
            "cron_expression": self.cron_expression,
            "is_running": self.is_running,
            "execution_count": self.execution_count,
            "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
            "next_execution_time": self.next_execution_time.isoformat() if self.next_execution_time else None,
            "last_error": self.last_error,
            "last_execution_result": self.last_execution_result
        }


class CronTaskManager:
    """
    定时任务管理器
    管理多个定时任务的生命周期
    """
    
    def __init__(self):
        """初始化任务管理器"""
        self.tasks: Dict[str, CronTask] = {}
        self.lock = threading.Lock()
    
    def register_task(self,
                     task_id: str,
                     cron_expression: str,
                     task_func: Callable,
                     task_args: Optional[Dict[str, Any]] = None) -> bool:
        """
        注册一个定时任务
        
        Args:
            task_id: 任务ID
            cron_expression: Cron表达式
            task_func: 要执行的函数
            task_args: 函数参数
            
        Returns:
            是否注册成功
        """
        with self.lock:
            if task_id in self.tasks:
                logger.warning(f"定时任务已存在 [{task_id}]")
                return False
            
            try:
                task = CronTask(task_id, cron_expression, task_func, task_args)
                self.tasks[task_id] = task
                logger.info(f"定时任务已注册 [{task_id}], Cron: {cron_expression}")
                return True
            except ValueError as e:
                logger.error(f"注册任务失败 [{task_id}]: {str(e)}")
                return False
    
    def unregister_task(self, task_id: str) -> bool:
        """注销一个定时任务"""
        with self.lock:
            if task_id not in self.tasks:
                logger.warning(f"定时任务不存在 [{task_id}]")
                return False
            
            task = self.tasks[task_id]
            task.stop()
            del self.tasks[task_id]
            
            logger.info(f"定时任务已注销 [{task_id}]")
            return True
    
    def start_task(self, task_id: str) -> bool:
        """启动特定的定时任务"""
        with self.lock:
            if task_id not in self.tasks:
                logger.warning(f"定时任务不存在 [{task_id}]")
                return False
            
            return self.tasks[task_id].start()
    
    def stop_task(self, task_id: str) -> bool:
        """停止特定的定时任务"""
        with self.lock:
            if task_id not in self.tasks:
                logger.warning(f"定时任务不存在 [{task_id}]")
                return False
            
            return self.tasks[task_id].stop()
    
    def start_all(self) -> int:
        """启动所有定时任务"""
        with self.lock:
            count = 0
            for task in self.tasks.values():
                if task.start():
                    count += 1
            
            logger.info(f"已启动 {count} 个定时任务")
            return count
    
    def stop_all(self) -> int:
        """停止所有定时任务"""
        with self.lock:
            count = 0
            for task in self.tasks.values():
                if task.stop():
                    count += 1
            
            logger.info(f"已停止 {count} 个定时任务")
            return count
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取指定任务的状态"""
        with self.lock:
            if task_id not in self.tasks:
                return None
            
            return self.tasks[task_id].get_status()
    
    def get_all_status(self) -> Dict[str, Dict[str, Any]]:
        """获取所有任务的状态"""
        with self.lock:
            return {
                task_id: task.get_status()
                for task_id, task in self.tasks.items()
            }
    
    def get_last_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务的最后执行结果"""
        with self.lock:
            if task_id not in self.tasks:
                return None
            
            return self.tasks[task_id].last_execution_result


# 全局任务管理器实例
task_manager = CronTaskManager()
