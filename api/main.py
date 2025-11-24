from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# 导入所有路由
from api.routes.analysis_router import router as analysis_router
from api.routes.conversion_router import router as conversion_router
from api.routes.device_data_route import router as iotda_router
from api.routes.bff_route import router as bff_router
from api.routes.expert_tuning_route import router as expert_tuning_router

# 导入中间件
from api.middleware import register_exception_handlers, ExceptionHandlerMiddleware, ResponseMiddleware

from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
)
app = FastAPI(
    title='PID 整定 API',
    description='PID控制系统智能分析与自动化调优服务',
    version='1.0.0',
    docs_url=None,  # 禁用默认的docs路由
    redoc_url=None  # 禁用默认的redoc路由
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册全局异常处理器(用于处理框架级别的异常)
register_exception_handlers(app)

# 添加全局异常处理中间件(用于捕获所有未被框架处理的异常)
app.add_middleware(ExceptionHandlerMiddleware)

# 添加全局响应拦截中间件
app.add_middleware(ResponseMiddleware)

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
app.include_router(iotda_router, prefix='/api/data_query', tags=['数据查询接口'])
app.include_router(bff_router, prefix='/api/bff', tags=['BFF模型'])



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