#!/usr/bin/env python3
"""
启动PID Agent API服务器的脚本
"""

import sys
import os
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
)
from fastapi.responses import FileResponse

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 导入所有路由
from api.routes.excluded_loop_router import router as excluded_loop_router
from api.routes.loop_router import router as loop_router
from api.routes.analysis_router import router as analysis_router
from api.routes.conversion_router import router as conversion_router
from api.routes.device_data_route import router as iotda_router
from api.routes.bff_route import router as bff_router
from api.routes.expert_tuning_route import router as expert_tuning_router
from api.routes.tuning_record_router import router as tuning_record_router
from api.routes.loop_monitoring_routing import router as loop_monitoring_router
from api.routes.loop_info_router import router as loop_info_router
from api.routes.device_evaluation_router import router as device_evaluation_router
from api.routes.loop_evaluation_router import router as loop_evaluation_router
from api.routes.cron_task_router import router as cron_task_router
from api.routes.home_page_route import home_page_router
from api.routes.dynamic_config_router import router as dynamic_config_router

# 导入中间件
from api.middleware import register_exception_handlers, ExceptionHandlerMiddleware, ResponseMiddleware,RequestLoggingMiddleware

# 导入数据库初始化函数
from core.database.database import init_database
# 导入定时任务初始化函数
from api.tasks import init_cron_tasks, shutdown_cron_tasks

# ... existing code ...

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

# ========== 定义 Lifespan 上下文管理器 ==========
# 需要在创建 FastAPI 应用之前定义
_cron_tasks_initialized = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 应用的生命周期管理
    支持 startup 和 shutdown 事件
    """
    global _cron_tasks_initialized
    
    # ========== Startup Event ==========
    if not _cron_tasks_initialized:
        try:
            init_cron_tasks()
            logger.info("定时任务初始化成功")
            _cron_tasks_initialized = True
        except Exception as e:
            logger.error(f"定时任务初始化失败: {str(e)}")
            logger.warning("应用将继续运行，但定时任务功能可能不可用")
    
    yield  # 应用主体运行
    
    # ========== Shutdown Event ==========
    try:
        shutdown_cron_tasks()
    except Exception as e:
        logger.error(f"关闭定时任务失败: {str(e)}")

# 创建 FastAPI 应用（使用 lifespan 上下文管理器）
app = FastAPI(
    title='PID 整定 API',
    description='PID控制系统智能分析与自动化调优服务',
    version='1.0.0',
    docs_url=None,  # 禁用默认的docs路由
    redoc_url=None,  # 禁用默认的redoc路由
    lifespan=lifespan  # 使用 lifespan 上下文管理器
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册全局异常处理器(用于处理框架级别的异常)
register_exception_handlers(app)

# 添加全局异常处理中间件(用于捕获所有未被框架处理的异常)
app.add_middleware(ExceptionHandlerMiddleware)

# 添加全局响应拦截中间件
app.add_middleware(ResponseMiddleware)

# 添加请求日志中间件
app.add_middleware(RequestLoggingMiddleware)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


# 注册所有路由
app.include_router(analysis_router, prefix='/api/analysis', tags=['大模型整定'])
app.include_router(expert_tuning_router, prefix='/api/expert', tags=['专家整定'])
app.include_router(conversion_router, prefix='/api/conversion', tags=['参数转换'])
app.include_router(loop_router, prefix='/api/loop', tags=['回路管理'])
app.include_router(tuning_record_router, prefix='/api/tuning-records', tags=['整定记录'])
app.include_router(iotda_router, prefix='/api/data_query', tags=['时序数据查询接口'])
app.include_router(bff_router, prefix='/api/bff', tags=['BFF模型'])
app.include_router(loop_monitoring_router, prefix='/api/monitoring', tags=['回路监控'])
app.include_router(loop_info_router, tags=['回路信息'])
app.include_router(device_evaluation_router, tags=['装置评估'])
app.include_router(loop_evaluation_router, tags=['回路评估'])
app.include_router(excluded_loop_router, tags=['剔除回路管理'])
app.include_router(cron_task_router, prefix='/api/cron', tags=['定时任务'])
app.include_router(home_page_router, prefix='/api/home', tags=['首页'])
app.include_router(dynamic_config_router, tags=['动态配置参数'])


@app.get('/health')
async def health_check():
    """健康检查端点 - 不被全局响应包装"""
    return {'status': 'ok'}


@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "PID 整定 API",
        "version": "1.0.0",
        "docs": "/docs"
    }
    
@app.get("/monitoring")
async def monitoring_page():
    """回路监控页面"""
    return FileResponse("static/monitoring/index.html")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui/swagger-ui.css"
    )

@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=app.title + " - ReDoc",
        # redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js",
        redoc_js_url="/static/swagger-ui/swagger-ui.css"
    )

# 添加GZip压缩中间件
# app.add_middleware(GZipMiddleware, minimum_size=1000)




if __name__ == "__main__":
    # 获取日志级别并转换为uvicorn格式
    log_level = os.getenv('LOG_LEVEL', 'INFO').lower()
    # 是否启用热加载（开发环境可设置为True，生产环境应为False）
    enable_reload = os.getenv('ENABLE_RELOAD', 'False').lower() == 'true'
    # 获取worker数量，默认为1（单进程），在生产环境中可以设置为CPU核心数
    # 注意：在调试器环境中强制使用单worker以避免进程重启问题
    workers_env = os.getenv('WORKERS', '3')
    workers = int(workers_env) if not enable_reload else 1
    
    # 在调试器环境中强制使用单worker
    # if os.getenv('PYCHARM_HOSTED') or os.getenv('VSCODE_PID'):
    #     logger.info("检测到调试器环境，强制使用单worker模式")
    #     workers = 1
    
    logger.info("启动PID整定软件 API服务器...")
    logger.info("API文档地址: http://localhost:8001/docs")
    logger.info(f"Uvicorn日志级别: {log_level}")
    logger.info(f"热加载状态: {'启用' if enable_reload else '禁用'}")
    logger.info(f"Worker数量: {workers}")
    
    # 在多worker环境下，使用分布式锁确保定时任务只被一个worker执行
    
    # 设置anyio的后端选项以提高稳定性
    import anyio
    anyio.BACKEND_OPTIONS = {
        'asyncio': {
            'use_uvloop': False  # 在某些环境下禁用uvloop可以提高稳定性
        }
    }
    
    uvicorn.run(
        "run_server:app",
        host="0.0.0.0", 
        port=8001, 
        reload=enable_reload,
        workers=workers,
        log_level=log_level
    )