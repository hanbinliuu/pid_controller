#!/usr/bin/env python3
"""
启动PID Agent API服务器的脚本
"""

import sys
import os
import logging

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

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
    logger.info(f"日志级别设置为: {log_level}")
    return logger

# 设置日志
logger = setup_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)

# 创建FastAPI应用
app = FastAPI(
    title="PID Agent API",
    description="PID控制系统代理API",
    version="1.0.0",
    docs_url=None,  # 禁用默认的docs路由
    redoc_url=None,  # 禁用默认的redoc路由
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="api/static"), name="static")

# 导入路由
try:
    from api.routes.analysis_router import router as analysis_router
    app.include_router(analysis_router, prefix='/api/analysis', tags=['pid数据分析'])
    logger.info("成功加载分析路由")
except Exception as e:
    logger.error(f"加载分析路由失败: {e}")

try:
    from api.routes.conversion_router import router as conversion_router
    app.include_router(conversion_router, prefix='/api/conversion', tags=['PID参数转换'])
    logger.info("成功加载PID转换路由")
except Exception as e:
    logger.error(f"加载PID转换路由失败: {e}")

try:
    from api.routes.proxy_router import router as proxy_router
    app.include_router(proxy_router, prefix='/api/proxy', tags=['代理服务'])
    logger.info("成功加载代理路由")
except Exception as e:
    logger.error(f"加载代理路由失败: {e}")


@app.get('/health')
async def health_check():
    return {'status': 'ok'}

@app.get("/")
async def root():
    return {"message": "PID Agent API"}

# 自定义Swagger UI路由，使用本地静态资源
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
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@latest/bundles/redoc.standalone.js",
    )

if __name__ == "__main__":
    import uvicorn
    
    # 获取日志级别并转换为uvicorn格式
    log_level = os.getenv('LOG_LEVEL', 'INFO').lower()
    
    logger.info("启动PID Agent API服务器...")
    logger.info("API文档地址: http://localhost:8001/docs")
    logger.info(f"Uvicorn日志级别: {log_level}")
    
    uvicorn.run(
        "run_server:app", 
        host="0.0.0.0", 
        port=8001, 
        reload=True,
        log_level=log_level
    )
