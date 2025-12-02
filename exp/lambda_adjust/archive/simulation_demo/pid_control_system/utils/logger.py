import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import sys

# 支持作为脚本直接运行和作为包导入
try:
    from ..config.settings import Config
except ImportError:
    # 相对导入失败时，使用绝对导入
    import os as _os
    _current_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _current_dir not in sys.path:
        sys.path.insert(0, _current_dir)
    from config.settings import Config

class LoggerSetup:

    """日志配置工具 - 按日期分割日志文件"""



    @staticmethod

    def setup_logger():

        # 创建日志目录

        log_dir = os.path.join(Config.DATA_SAVE_DIR, 'logs')

        os.makedirs(log_dir, exist_ok=True)



        # 创建logger实例

        logger = logging.getLogger('control_system')

        logger.setLevel(logging.INFO)



        # 清除已有的处理器，避免重复

        if logger.handlers:

            logger.handlers.clear()



        # 控制台处理器

        console_handler = logging.StreamHandler()

        console_handler.setLevel(logging.INFO)

        console_formatter = logging.Formatter(

            '%(asctime)s - %(levelname)s - %(message)s'

        )

        console_handler.setFormatter(console_formatter)

        logger.addHandler(console_handler)



        # 按日期分割的日志文件处理器

        log_file_path = os.path.join(log_dir, 'control_system.log')

        file_handler = TimedRotatingFileHandler(

            filename=log_file_path,

            when='midnight',  # 每天午夜分割

            interval=1,  # 每1天分割一次

            backupCount=30,  # 保留最近30天的日志

            encoding='utf-8'

        )

        file_handler.setLevel(logging.INFO)

        file_formatter = logging.Formatter(

            '%(asctime)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'

        )

        file_handler.setFormatter(file_formatter)

        logger.addHandler(file_handler)



        # 添加日志轮转信息

        logger.info(f"日志系统已启动，日志将按日期分割保存到: {log_dir}")

        logger.info(f"当前日期: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")



        return logger




