#!/usr/bin/env python3
"""
启动PID Agent API服务器的脚本
"""

import sys
import os
import logging
import uvicorn

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)
# 从api.main导入已配置好的app(包含全局中间件)
from api.main import app
# 导入数据库初始化函数
from core.database.database import init_database
# 导入定时任务初始化函数
from api.tasks import init_cron_tasks, shutdown_cron_tasks

# 配置日志
def setup_logging():
    """设置日志配置"""
    # 从环境变量获取日志级别，默认为INFO
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # 验证日志级别
    valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
    if log_level not in valid_levels:
        log_level = 'INFO'
    
    # 配置日志格式
    log_format = os.getenv('LOG_FORMAT', '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 基础日志配置
    logging.basicConfig(
        level=getattr(logging, log_level),
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 设置第三方库的日志级别
    logging.getLogger('uvicorn').setLevel(logging.INFO)
    logging.getLogger('fastapi').setLevel(logging.INFO)
    
    # 根据日志级别调整uvicorn的详细程度
    if log_level == 'DEBUG':
        logging.getLogger('uvicorn.access').setLevel(logging.DEBUG)
    else:
        logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    
    logger = logging.getLogger(__name__)
    return logger

# 设置日志
logger = setup_logging()

# 初始化数据库
try:
    init_database()
    logger.info("数据库初始化成功")
except Exception as e:
    logger.error(f"数据库初始化失败: {str(e)}")
    logger.warning("服务将继续启动，但数据库功能可能不可用")

# 初始化定时任务
try:
    init_cron_tasks()
    logger.info("定时任务初始化成功")
except Exception as e:
    logger.error(f"定时任务初始化失败: {str(e)}")
    logger.warning("应用将继续启动，但定时任务功能可能不可用")



# 添加GZip压缩中间件
# app.add_middleware(GZipMiddleware, minimum_size=1000)


# 注意: 路由已在api/main.py中注册,这里不需要重复注册
# 以下注释掉的代码保留用于参考



if __name__ == "__main__":
    # 获取日志级别并转换为uvicorn格式
    log_level = os.getenv('LOG_LEVEL', 'INFO').lower()
    # 是否启用热加载（开发环境可设置为True，生产环境应为False）
    enable_reload = os.getenv('ENABLE_RELOAD', 'True').lower() == 'false'
    
    logger.info("启动PID整定软件 API服务器...")
    logger.info("API文档地址: http://localhost:8001/docs")
    logger.info(f"Uvicorn日志级别: {log_level}")
    logger.info(f"热加载状态: {'启用' if enable_reload else '禁用'}")

    uvicorn.run(
        "run_server:app",
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        log_level=log_level
    )
