"""
统一的日志工具模块
提供分级日志输出，方便调试和生产环境切换
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

class ColoredFormatter(logging.Formatter):
    """带颜色的日志格式化器"""
    
    # ANSI颜色代码
    COLORS = {
        'DEBUG': '\033[36m',    # 青色
        'INFO': '\033[32m',     # 绿色
        'WARNING': '\033[33m',  # 黄色
        'ERROR': '\033[31m',    # 红色
        'CRITICAL': '\033[35m', # 紫色
    }
    RESET = '\033[0m'
    
    # Emoji图标
    ICONS = {
        'DEBUG': '🔍',
        'INFO': 'ℹ️',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🔥',
    }
    
    def format(self, record):
        # 添加颜色和图标
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{self.ICONS[levelname]} {levelname}{self.RESET}"
        return super().format(record)


class Logger:
    """统一的日志管理器"""
    
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._logger is None:
            self._setup_logger()
    
    def _setup_logger(self):
        """设置日志器"""
        self._logger = logging.getLogger('web_tuning')
        self._logger.setLevel(logging.DEBUG)
        
        # 清除现有的处理器
        self._logger.handlers.clear()
        
        # 控制台处理器
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        
        # 使用带颜色的格式化器
        formatter = ColoredFormatter(
            '%(levelname)s [%(asctime)s] %(message)s',
            datefmt='%H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        self._logger.addHandler(console_handler)
        
        # 文件处理器（可选）
        # log_file = Path(__file__).parent.parent / 'logs' / f'app_{datetime.now():%Y%m%d}.log'
        # log_file.parent.mkdir(exist_ok=True)
        # file_handler = logging.FileHandler(log_file, encoding='utf-8')
        # file_handler.setLevel(logging.INFO)
        # file_handler.setFormatter(logging.Formatter(
        #     '%(levelname)s [%(asctime)s] %(message)s',
        #     datefmt='%Y-%m-%d %H:%M:%S'
        # ))
        # self._logger.addHandler(file_handler)
    
    def debug(self, message, *args, **kwargs):
        """DEBUG级别日志"""
        self._logger.debug(message, *args, **kwargs)
    
    def info(self, message, *args, **kwargs):
        """INFO级别日志"""
        self._logger.info(message, *args, **kwargs)
    
    def warning(self, message, *args, **kwargs):
        """WARNING级别日志"""
        self._logger.warning(message, *args, **kwargs)
    
    def error(self, message, *args, **kwargs):
        """ERROR级别日志"""
        self._logger.error(message, *args, **kwargs)
    
    def critical(self, message, *args, **kwargs):
        """CRITICAL级别日志"""
        self._logger.critical(message, *args, **kwargs)
    
    def success(self, message, *args, **kwargs):
        """成功信息（使用INFO级别）"""
        self._logger.info(f"✅ {message}", *args, **kwargs)
    
    def section(self, title, width=70):
        """打印分隔线标题"""
        self._logger.info("=" * width)
        self._logger.info(title)
        self._logger.info("=" * width)
    
    def subsection(self, title):
        """打印子标题"""
        self._logger.info(f"\n{title}")
    
    def set_level(self, level):
        """设置日志级别"""
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self._logger.setLevel(level)
        for handler in self._logger.handlers:
            handler.setLevel(level)


# 创建全局日志实例
logger = Logger()

# 便捷函数
def debug(message, *args, **kwargs):
    logger.debug(message, *args, **kwargs)

def info(message, *args, **kwargs):
    logger.info(message, *args, **kwargs)

def warning(message, *args, **kwargs):
    logger.warning(message, *args, **kwargs)

def error(message, *args, **kwargs):
    logger.error(message, *args, **kwargs)

def success(message, *args, **kwargs):
    logger.success(message, *args, **kwargs)

def section(title, width=70):
    logger.section(title, width)

def subsection(title):
    logger.subsection(title)
