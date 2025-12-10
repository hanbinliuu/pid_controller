"""统一日志模块 - 提供模块级日志功能"""

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


class LoggerMixin:
    """
    日志混入类 - 为类提供统一的日志方法
    
    使用方式：
        class MyClass(LoggerMixin):
            def __init__(self, verbose=False):
                self._init_logger(verbose)
            
            def some_method(self):
                self.log("信息消息")
                self.log_debug("调试消息")
                self.log_warning("警告消息")
    """
    
    _logger: Optional[logging.Logger] = None
    _verbose: bool = False
    
    def _init_logger(self, verbose: bool = False):
        """初始化日志器"""
        self._verbose = verbose
        self._logger = get_logger(self.__class__.__name__, verbose)
    
    def log(self, msg: str):
        """输出信息日志（verbose模式下显示）"""
        if self._verbose and self._logger:
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
