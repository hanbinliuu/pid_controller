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

@app.get("/api/utils/pid-history")
async def get_pid_history_demo(
    table: str = "cpu",
    hours: int = 24,
    limit: int = 100
):
    """
    演示PID历史数据获取工具方法
    
    Args:
        table: 表名
        hours: 最近多少小时的数据
        limit: 限制条数
        
    Returns:
        Dict: PID历史数据和分析结果
    """
    try:
        # 使用工具方法获取最近的PID数据
        history_data = get_recent_pid_data(
            table_name=table,
            hours=hours,
            limit=limit
        )
        
        # 格式化数据用于分析
        formatted_data = format_pid_data_for_analysis(history_data)
        
        return {
            "status": "success",
            "message": f"获取到 {len(history_data)} 条PID历史数据",
            "data": {
                "raw_data": history_data,
                "formatted_data": formatted_data,
                "summary": {
                    "total_records": len(history_data),
                    "time_range_hours": hours,
                    "table_name": table,
                    "fields": ["timestamp", "temperature", "kp", "ki", "kd", "target_temp", "control_period", "max_duty"]
                }
            }
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取PID历史数据失败: {str(e)}",
            "data": None
        }

@app.get("/api/utils/pid-range")
async def get_pid_range_demo(
    table: str = "cpu",
    start_time: str = "2025-07-08 00:00:00",
    end_time: Optional[str] = "2025-07-18 00:00:00",
    limit: int = 100
):
    """
    演示指定时间范围的PID数据获取
    
    Args:
        table: 表名
        start_time: 开始时间（字符串格式）
        end_time: 结束时间（可选）
        limit: 限制条数
        
    Returns:
        Dict: 指定时间范围的PID数据
    """
    try:
        # 使用工具方法获取指定时间范围的数据
        history_data = get_pid_history_data(
            table_name=table,
            start_time=start_time,
            end_time=end_time,
            limit=limit
        )
        
        return {
            "status": "success",
            "message": f"获取到 {len(history_data)} 条PID历史数据",
            "data": history_data
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"获取PID历史数据失败: {str(e)}",
            "data": None
        }
