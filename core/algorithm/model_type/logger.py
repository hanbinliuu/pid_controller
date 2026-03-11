"""
统一日志模块 (Unified Logging Module)
=====================================

本模块提供模型辨识过程中的统一日志功能。

主要组件
--------
- **get_logger**: 获取配置好的日志器实例
- **Logger**: 独立日志类，推荐通过组合方式使用（消除基类耦合）
- **LoggerMixin**: 日志混入类（已弃用，保留向后兼容）

使用方式
--------
1. 推荐方式 - 组合::

    class MyClass:
        def __init__(self, verbose=False):
            self._logger = Logger(verbose, name=self.__class__.__name__)
        
        def process(self):
            self._logger.log("开始处理")
            self._logger.log_debug("调试信息")

2. 旧方式 - 混入（向后兼容，不推荐新代码使用）::

    class MyClass(LoggerMixin):
        def __init__(self, verbose=False):
            self._init_logger(verbose)
"""

import logging
import sys
from typing import Optional


def get_logger(name: str, verbose: bool = False) -> logging.Logger:
    """
    获取模块日志器
    
    Args:
        name: 日志器名称（通常使用 __name__）
        verbose: 是否开启详细日志
    
    Returns:
        配置好的日志器实例
    """
    logger = logging.getLogger(name)
    
    # 避免重复添加处理器
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            '%(message)s'  # 简洁格式，与原有输出风格一致
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    
    # 根据 verbose 设置级别
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    
    return logger


class Logger:
    """
    独立日志类 - 推荐通过组合方式使用
    
    使用方式：
        class MyClass:
            def __init__(self, verbose=False):
                self._logger = Logger(verbose, name=self.__class__.__name__)
            
            def some_method(self):
                self._logger.log("信息消息")
                self._logger.log_debug("调试消息")
                self._logger.log_warning("警告消息")
    """
    
    def __init__(self, verbose: bool = False, name: str = None):
        """
        初始化日志器
        
        Args:
            verbose: 是否开启详细日志
            name: 日志器名称（默认使用 'Logger'）
        """
        self.verbose = verbose
        self._logger = get_logger(name or 'Logger', verbose)
    
    def log(self, msg: str):
        """输出信息日志（verbose模式下显示）"""
        if self.verbose and self._logger:
            self._logger.info(msg)
    
    def log_debug(self, msg: str):
        """输出调试日志"""
        if self._logger:
            self._logger.debug(msg)
    
    def log_warning(self, msg: str):
        """输出警告日志（始终显示）"""
        if self._logger:
            self._logger.warning(msg)
    
    def log_error(self, msg: str):
        """输出错误日志（始终显示）"""
        if self._logger:
            self._logger.error(msg)


class LoggerMixin:
    """
    日志混入类 - 向后兼容包装器
    
    ⚠️ 不推荐新代码使用。请改用 Logger 通过组合方式。
    
    内部委托给 Logger 实例，保持接口不变。
    """
    
    def _init_logger(self, verbose: bool = False):
        """初始化日志器"""
        self._verbose = verbose
        self.__logger_inst = Logger(verbose, name=self.__class__.__name__)
        self._logger = self.__logger_inst._logger
    
    def log(self, msg: str):
        """输出信息日志（verbose模式下显示）"""
        self.__logger_inst.log(msg)
    
    def log_debug(self, msg: str):
        """输出调试日志"""
        self.__logger_inst.log_debug(msg)
    
    def log_warning(self, msg: str):
        """输出警告日志（始终显示）"""
        self.__logger_inst.log_warning(msg)
    
    def log_error(self, msg: str):
        """输出错误日志（始终显示）"""
        self.__logger_inst.log_error(msg)
