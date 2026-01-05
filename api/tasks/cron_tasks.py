#!/usr/bin/env python3
"""
基于Cron表达式的定时任务
直接使用croniter定时执行任务，无需复杂的调度器框架
支持多worker环境下的任务去重执行
"""
import asyncio
import logging
import threading
import time
import os
# import fcntl
import portalocker
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
                 task_args: Optional[Dict[str, Any]] = None,
                 enable_multi_worker: bool = True):
        """
        初始化定时任务
        
        Args:
            task_id: 任务ID（唯一标识）
            cron_expression: Cron表达式
            task_func: 要执行的函数
            task_args: 函数参数字典
            enable_multi_worker: 是否在多worker环境下启用任务执行（启用多进程锁）
            
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
        self.enable_multi_worker = enable_multi_worker
        
        self.is_running = False
        self.thread = None
        self.last_execution_time = None
        self.last_execution_result = None
        self.last_error = None
        self.execution_count = 0
        self.next_execution_time = None
        # 添加线程锁以确保线程安全
        self._lock = threading.Lock()
        # 获取当前进程ID
        self.process_id = os.getpid()
        # 多进程文件锁（用于多worker环境）
        self._lock_fd = None
    
    def _acquire_multiprocess_lock(self) -> bool:
        """
        在多worker环境下获取分布式文件锁
        
        Returns:
            bool: 是否成功获取锁
        """
        if not self.enable_multi_worker:
            return True
        
        try:
            # 创建锁文件目录
            lock_dir = os.path.abspath("./lock")
            if not os.path.exists(lock_dir):
                os.makedirs(lock_dir, exist_ok=True)
                        
            # 创建锁文件路径
            lock_file_path = os.path.join(lock_dir, f"cron_task_{self.task_id}.lock")
            
            # 打开锁文件
            self._lock_fd = open(lock_file_path, 'w')
            
            # 尝试获取文件锁（非阻塞）
            # fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            portalocker.lock(self._lock_fd, portalocker.LOCK_EX | portalocker.LOCK_NB)

            # 写入进程ID
            self._lock_fd.truncate(0)
            self._lock_fd.write(str(self.process_id))
            self._lock_fd.flush()
            
            logger.debug(f"任务 [{self.task_id}] 成功获取分布式锁 (PID: {self.process_id})")
            return True
            
        except IOError:
            # 无法获取锁，说明其他进程正在执行此任务
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            logger.debug(f"任务 [{self.task_id}] 无法获取分布式锁，跳过执行 (PID: {self.process_id})")
            return False
        except Exception as e:
            # 其他异常，记录日志并释放可能打开的文件
            if self._lock_fd:
                try:
                    self._lock_fd.close()
                except:
                    pass
                self._lock_fd = None
            logger.warning(f"任务 [{self.task_id}] 获取分布式锁时发生异常: {str(e)}")
            return False  # 出现异常时不应执行任务，确保锁机制有效
    
    def _release_multiprocess_lock(self):
        """
        释放分布式文件锁
        """
        if not self.enable_multi_worker or not self._lock_fd:
            return
        
        try:
            # 释放文件锁
            # fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            portalocker.unlock(self._lock_fd)
            # 关闭文件
            self._lock_fd.close()
            self._lock_fd = None
            logger.debug(f"任务 [{self.task_id}] 成功释放分布式锁 (PID: {self.process_id})")
        except Exception as e:
            logger.warning(f"任务 [{self.task_id}] 释放分布式锁时发生异常: {str(e)}")
            # 确保在任何异常情况下都清除文件描述符
            self._lock_fd = None
    
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
        import asyncio
        import sys
        import inspect
        
        # 检查任务函数是否是异步的
        if inspect.iscoroutinefunction(self.task_func):
            # 异步任务函数，需要在事件循环中运行
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                # 如果没有事件循环，创建一个新的
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 运行异步任务
            loop.run_until_complete(self._run_task_async_wrapper())
        else:
            # 同步任务函数，使用原始实现
            self._run_task_sync()
    
    async def _run_task_async_wrapper(self):
        """异步任务的包装器"""
        try:
            await self._run_task_async()
        except Exception as e:
            logger.error(f"异步任务执行异常 [{self.task_id}]: {str(e)} (PID: {self.process_id})")
    
    async def _run_task_async(self):
        """异步执行任务的主函数"""
        logger.info(f"定时任务启动 [{self.task_id}] - Cron: {self.cron_expression} (PID: {self.process_id})")
        
        while self.is_running:
            try:
                # 计算下次执行时间
                self.next_execution_time = self._calculate_next_run_time()
                
                if not self.next_execution_time:
                    logger.error(f"任务 [{self.task_id}] 无法计算下次执行时间")
                    if self.is_running:
                        await asyncio.sleep(60)
                    continue
                
                # 计算等待时间
                wait_seconds = (self.next_execution_time - datetime.now()).total_seconds()
                
                if wait_seconds > 0:
                    logger.debug(f"任务 [{self.task_id}] 将在 {wait_seconds:.1f} 秒后执行 (PID: {self.process_id})")
                    
                    # 使用小步长睡眠，以便能及时响应停止信号
                    steps = int(wait_seconds)
                    remaining = wait_seconds - steps
                    
                    for _ in range(steps):
                        if not self.is_running:
                            break
                        await asyncio.sleep(1)
                    
                    if remaining > 0 and self.is_running:
                        await asyncio.sleep(remaining)
                
                # 执行任务
                if self.is_running:
                    # 在多worker环境下尝试获取分布式锁
                    if not self._acquire_multiprocess_lock():
                        logger.info(f"任务 [{self.task_id}] 未获取分布式锁 (PID: {self.process_id})，跳过执行")
                        continue  # 无法获取锁，跳过本次执行
                    
                    try:
                        logger.info(f"执行定时任务 [{self.task_id}] (PID: {self.process_id})")
                        start_time = time.time()
                        
                        # 执行任务函数
                        result = await self.task_func(**self.task_args)
                        
                        elapsed_time = time.time() - start_time
                        
                        # 更新执行状态（使用锁保护）
                        with self._lock:
                            self.execution_count += 1
                            self.last_execution_time = datetime.now()
                            self.last_execution_result = result
                            self.last_error = None
                        
                        logger.info(f"定时任务完成 [{self.task_id}], 耗时: {elapsed_time:.2f}秒, "
                                  f"执行次数: {self.execution_count} (PID: {self.process_id})")
                        
                    except Exception as e:
                        logger.error(f"定时任务执行失败 [{self.task_id}]: {str(e)} (PID: {self.process_id})")
                        # 更新错误状态（使用锁保护）
                        with self._lock:
                            self.execution_count += 1
                            self.last_execution_time = datetime.now()
                            self.last_error = str(e)
                            self.last_execution_result = None
                    finally:
                        # 释放分布式锁
                        self._release_multiprocess_lock()
                
            except Exception as e:
                logger.error(f"定时任务循环异常 [{self.task_id}]: {str(e)} (PID: {self.process_id})")
                # 更新错误状态（使用锁保护）
                with self._lock:
                    self.last_error = str(e)
                
                if self.is_running:
                    await asyncio.sleep(60)  # 异常后等待60秒重试
    
    def _run_task_sync(self):
        """同步执行任务的主函数"""
        logger.info(f"定时任务启动 [{self.task_id}] - Cron: {self.cron_expression} (PID: {self.process_id})")
        
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
                    logger.debug(f"任务 [{self.task_id}] 将在 {wait_seconds:.1f} 秒后执行 (PID: {self.process_id})")
                    
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
                    # 在多worker环境下尝试获取分布式锁
                    if not self._acquire_multiprocess_lock():
                        continue  # 无法获取锁，跳过本次执行
                    
                    try:
                        logger.info(f"执行定时任务 [{self.task_id}] (PID: {self.process_id})")
                        start_time = time.time()
                        
                        # 执行任务函数
                        result = self.task_func(**self.task_args)
                        
                        elapsed_time = time.time() - start_time
                        
                        # 更新执行状态（使用锁保护）
                        with self._lock:
                            self.execution_count += 1
                            self.last_execution_time = datetime.now()
                            self.last_execution_result = result
                            self.last_error = None
                        
                        logger.info(f"定时任务完成 [{self.task_id}], 耗时: {elapsed_time:.2f}秒, "
                                  f"执行次数: {self.execution_count} (PID: {self.process_id})")
                        
                    except Exception as e:
                        logger.error(f"定时任务执行失败 [{self.task_id}]: {str(e)} (PID: {self.process_id})")
                        # 更新错误状态（使用锁保护）
                        with self._lock:
                            self.execution_count += 1
                            self.last_execution_time = datetime.now()
                            self.last_error = str(e)
                            self.last_execution_result = None
                    finally:
                        # 释放分布式锁
                        self._release_multiprocess_lock()
                
            except Exception as e:
                logger.error(f"定时任务循环异常 [{self.task_id}]: {str(e)} (PID: {self.process_id})")
                # 更新错误状态（使用锁保护）
                with self._lock:
                    self.last_error = str(e)
                
                if self.is_running:
                    time.sleep(60)  # 异常后等待60秒重试
    
    def start(self) -> bool:
        """启动定时任务"""
        # 使用锁保护状态检查和更新
        with self._lock:
            if self.is_running:
                logger.warning(f"定时任务已在运行 [{self.task_id}] (PID: {self.process_id})")
                return False
            
            self.is_running = True
        
        self.thread = threading.Thread(
            target=self._run_task,
            daemon=True,
            name=f"CronTask-{self.task_id}-{self.process_id}"
        )
        self.thread.start()
        
        logger.info(f"定时任务已启动 [{self.task_id}] (PID: {self.process_id})")
        return True
    
    def stop(self) -> bool:
        """停止定时任务"""
        # 使用锁保护状态检查和更新
        with self._lock:
            if not self.is_running:
                logger.warning(f"定时任务未在运行 [{self.task_id}] (PID: {self.process_id})")
                return False
            
            self.is_running = False
        
        if self.thread:
            self.thread.join(timeout=5)
        
        logger.info(f"定时任务已停止 [{self.task_id}] (PID: {self.process_id})")
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """获取任务状态"""
        # 使用锁保护状态读取
        with self._lock:
            return {
                "task_id": self.task_id,
                "cron_expression": self.cron_expression,
                "is_running": self.is_running,
                "execution_count": self.execution_count,
                "last_execution_time": self.last_execution_time.isoformat() if self.last_execution_time else None,
                "next_execution_time": self.next_execution_time.isoformat() if self.next_execution_time else None,
                "last_error": self.last_error,
                "last_execution_result": self.last_execution_result,
                "process_id": self.process_id,
                "enable_multi_worker": self.enable_multi_worker
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
                     task_args: Optional[Dict[str, Any]] = None,
                     enable_multi_worker: bool = True) -> bool:
        """
        注册一个定时任务
        
        Args:
            task_id: 任务ID
            cron_expression: Cron表达式
            task_func: 要执行的函数
            task_args: 函数参数
            enable_multi_worker: 是否在多worker环境下启用任务执行
            
        Returns:
            是否注册成功
        """
        with self.lock:
            if task_id in self.tasks:
                logger.warning(f"定时任务已存在 [{task_id}]")
                return False
            
            try:
                task = CronTask(task_id, cron_expression, task_func, task_args, enable_multi_worker)
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