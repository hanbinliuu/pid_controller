from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api.routes.analysis_router import router as analysis_router
from core.utils.tsdb_utils import get_pid_history_data, get_recent_pid_data, format_pid_data_for_analysis
from datetime import datetime, timedelta
from typing import Optional
app = FastAPI(title='PID Agent API')

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# 注册路由
app.include_router(analysis_router, prefix='/api/analysis', tags=['analysis'])

@app.get('/health')
async def health_check():
    return {'status': 'ok'}

@app.get("/")
async def root():
    return {"message": "PID Agent API"}
