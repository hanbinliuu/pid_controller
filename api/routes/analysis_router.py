import asyncio
import os
import httpx
from fastapi import APIRouter, HTTPException, Query, Header
from fastapi.responses import StreamingResponse
from typing import Dict, List, Optional, Union, AsyncGenerator
from datetime import datetime
import json
import logging

from pydantic import Field, BaseModel

# 更新导入语句，移除直接的工具类导入，改为导入AnalysisService
from api.services.analysis_service import AnalysisService
from core.utils.model_type import ModelType

router = APIRouter()
logger = logging.getLogger(__name__)

"""
**获取设备历史数据 - HistoryDataTool**

从时序数据库(TSDB)中获取指定设备在特定时间范围内的历史数据。

**时间格式支持：**
- 毫秒时间戳: 1640995200000
- 秒时间戳: 1640995200
- 标准格式: '2022-01-01 12:00:00'
- ISO 8601格式: '2022-01-01T12:00:00'
- 日期格式: '2022-01-01'

**参数验证：**
- kp > 0 (比例系数必须为正数)
- ki >= 0 (积分系数不能为负数)
- kd >= 0 (微分系数不能为负数)

**返回数据：**
- timestamp: 时间戳（毫秒）
- temperature: 实际温度值
- target_temp: 目标温度设定值
- kp, ki, kd: PID控制参数
- control_period: 控制周期
- max_duty: 最大占空比
"""

@router.get("/temperature-analysis",
            summary="大模型整定-曲线分析",
            operation_id="大模型整定-回路状态曲线分析",
            description="大模型整定-分析曲线的控制性能，包括上升时间、超调量、稳态误差等指标")
async def analyze_temperature(
        start_time: Union[int, str] = Query(None,required=False, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(None,required=False, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"] ),
):
    """
    **温度曲线智能分析 - TemperatureAnalysisTool**

    使用先进的控制理论算法，对PID控制系统的温度响应特性进行全面、精确的定量分析。

    **分析指标：**

    **1. 动态响应特性：**
    - 上升时间(Rise Time): 达到90%目标值的时间
    - 调节时间(Settling Time): 稳定在误差带内的时间
    - 峰值时间(Peak Time): 首次达到最大值的时间

    **2. 稳态性能评估：**
    - 超调量(Overshoot): 超出目标值的百分比
    - 稳态误差(Steady State Error): 最终稳态值与目标值的偏差
    - 温度波动: 稳态状态下的温度波动程度

    **3. 控制质量评估：**
    - 控制精度: 长期稳定性和精度评估
    - 系统鲁棒性: 对干扰和参数变化的适应性
    - 能耗效率: 控制动作的经济性分析

    **输出格式：**
    - 定量化的性能指标数值
    - 直观的性能评级和建议
    - 问题诊断和改进方向

    **应用价值：**
    - PID参数优化的科学依据
    - 控制系统性能监控和评估
    - 生产过程优化和效率提升
    - 设备维护和故障预测
    """
    try:
        # 调用Service层进行温度曲线分析
        result = AnalysisService.analyze_temperature_curve(
            start_time=start_time,
            end_time=end_time,
            loop_uri=loop_uri
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"曲线分析失败: {str(e)}"
        )

@router.get("/pid-optimization",
            summary="大模型整定-PID参数优化建议",
            operation_id="大模型整定-PID参数优化建议",
            description="基于历史数据分析结果，提供PID参数调整建议")
async def optimize_pid(
        start_time: Union[int, str] = Query(None, description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(None, description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"]),
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/935cf045bd254867bdfeb113c31467da"] ),
        is_filter: bool = Query(True, description="是否过滤数据",
                                examples=[True]),
        is_lambda: bool = Query(False, description="是否增加lambda整定建议",
                                      examples=[False]),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=ModelType.get_model_type())
):
    """
    **PID参数智能优化 - PIDOptimizationTool**

    运用先进的控制理论和机器学习算法，对PID控制器参数进行智能化优化分析。

    **优化策略：**

    **1. 数据驱动分析：**
    - 基于历史数据的性能评估
    - 控制效果量化分析
    - 系统特性识别和建模

    **2. 参数优化算法：**
    - Ziegler-Nichols经典调试法
    - Cohen-Coon改进算法
    - 现代启发式优化算法
    - 机器学习自适应优化

    **3. 多目标优化：**
    - 响应速度与稳定性平衡
    - 控制精度与能耗优化
    - 鲁棒性与性能综合考量

    """
    try:
        # 调用Service层进行PID参数优化
        result = AnalysisService.optimize_pid_parameters(
            start_time=start_time,
            end_time=end_time,
            loop_uri=loop_uri,
            is_filter=is_filter,
            is_lambda=is_lambda,
            model_type=model_type
        )
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PID优化失败: {str(e)}"
        )

class WorkflowRequest(BaseModel):
    """工作流请求模型"""
    start_time: str = Field(..., description="开始时间", examples=["2025-10-08 17:30:37"])
    end_time: str = Field(..., description="结束时间", examples=["2025-10-08 18:00:37"])
    loop_type: str = Field(..., description="回路类型", examples=["流量"])
    loop_uri: str = Field(None, description="回路 URI", examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"])
    response_mode: str = Field("blocking", description="响应模式（流式/直连）", examples=[["blocking", "streaming"]])
    # user: str = Field("admin", description="用户名", example="admin")
    
    class Config:
        json_schema_extra = {
            "example": {
                "start_time": "2025-10-08 17:30:37",
                "end_time": "2025-10-08 18:00:37",
                "loop_type": "流量",
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                "response_mode": "blocking"
            }
        }

class ProxyConfig:
    """代理配置"""
    WORKFLOW_BASE_URL = os.getenv("WORKFLOW_BASE_URL", "http://192.168.202.172")
    WORKFLOW_TOKEN = os.getenv("WORKFLOW_TOKEN", "app-LLQlDBTuWW16F8FZTATS6aJ7")
    WORKFLOW_TIMEOUT = int(os.getenv("WORKFLOW_TIMEOUT", "120"))  # 增加到120秒
    WORKFLOW_CONNECT_TIMEOUT = int(os.getenv("WORKFLOW_CONNECT_TIMEOUT", "30"))  # 连接超时30秒
    WORKFLOW_READ_TIMEOUT = int(os.getenv("WORKFLOW_READ_TIMEOUT", "300"))  # 读取超时300秒
    HEALTH_CHECK_TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))  # 健康检查超时10秒

@router.post("/workflow/run",
             operation_id="pid_agent整定分析",
             summary="执行大模型整定分析",
             description="调用外部工作流API执行PID整定分析")
async def run_workflow(
        request: WorkflowRequest,
        authorization: Optional[str] = Header(None, description="授权令牌")
):
    """
    **执行外部工作流 - Workflow Proxy**

    通过代理方式调用外部工作流服务，支持PID控制参数的处理和分析。

    **功能说明：**
    - 转发请求到外部工作流API
    - 自动处理授权认证
    - 统一的错误处理和日志记录
    - 支持超时控制和重试机制
    - 支持流式(streaming)和阻塞(blocking)两种响应模式

    **参数说明：**
    - start_time: 开始时间（字符串格式）
    - end_time: 结束时间（字符串格式）
    - loop_type: 回路类型（字符串格式）
    - response_mode: 响应模式（blocking/streaming）
    - user: 执行用户

    **返回格式：**
    - blocking模式: 直接返回外部工作流的响应结果
    - streaming模式: 返回SSE流式响应，实时推送工作流执行进度
    """
    try:
        # 构建请求URL
        workflow_url = f"{ProxyConfig.WORKFLOW_BASE_URL}/v1/workflows/run"

        # 准备请求头
        headers = {
            "Content-Type": "application/json"
        }

        # 使用传入的授权令牌或默认令牌
        if authorization:
            headers["Authorization"] = authorization
        else:
            headers["Authorization"] = f"Bearer {ProxyConfig.WORKFLOW_TOKEN}"

        # 准备请求数据
        request_data = {
            "inputs": {
                "start_time": request.start_time,
                "end_time": request.end_time,
                "loop_type": request.loop_type,
                "loop_uri": request.loop_uri
            },
            "response_mode": request.response_mode,
            "user": "pid-agent-api"
        }

        logger.info(f"调用工作流API: {workflow_url}")
        logger.debug(f"请求数据: {request_data}")

        # 如果是流式模式，返回流式响应
        if request.response_mode == "streaming":
            async def stream_generator() -> AsyncGenerator[str, None]:
                """流式响应生成器"""
                try:
                    async with httpx.AsyncClient() as client:
                        async with client.stream(
                            "POST",
                            workflow_url,
                            json=request_data,
                            headers=headers,
                            timeout=httpx.Timeout(
                                connect=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT,
                                read=ProxyConfig.WORKFLOW_READ_TIMEOUT,
                                write=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT,
                                pool=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT
                            )
                        ) as response:
                            logger.info(f"工作流API流式响应状态: {response.status_code}")
                            
                            if response.status_code != 200:
                                error_text = await response.aread()
                                logger.error(f"工作流API调用失败: {response.status_code} - {error_text.decode()}")
                                yield f"data: {{\"error\": \"工作流执行失败: {error_text.decode()}\", \"status_code\": {response.status_code}}}\n\n"
                                return
                            
                            # 逐块读取流式响应（使用原始字节流确保真正的流式传输）
                            async for chunk in response.aiter_raw():
                                if chunk:
                                    # 直接转发原始字节数据块，确保立即传输
                                    decoded_chunk = chunk.decode('utf-8')
                                    #回路暂停
                                    await asyncio.sleep(0.08)
                                    yield decoded_chunk
                                    logger.debug(f"流式数据块大小: {len(decoded_chunk)} bytes")
                            
                            logger.info("工作流流式执行完成")
                            
                except httpx.TimeoutException:
                    logger.error("工作流API调用超时")
                    yield f"data: {{\"error\": \"工作流执行超时，请稍后重试\", \"status_code\": 408}}\n\n"
                except httpx.ConnectError:
                    logger.error("无法连接到工作流API")
                    yield f"data: {{\"error\": \"无法连接到工作流服务，请检查网络连接\", \"status_code\": 503}}\n\n"
                except Exception as e:
                    logger.error(f"工作流代理错误: {str(e)}")
                    yield f"data: {{\"error\": \"代理服务内部错误: {str(e)}\", \"status_code\": 500}}\n\n"
            
            return StreamingResponse(
                stream_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no"  # 禁用nginx缓冲
                }
            )
        
        # 阻塞模式：等待完整响应
        else:
            # 使用异步HTTP客户端发送请求
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    workflow_url,
                    json=request_data,
                    headers=headers,
                    timeout=httpx.Timeout(
                        connect=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT,
                        read=ProxyConfig.WORKFLOW_READ_TIMEOUT,
                        write=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT,
                        pool=ProxyConfig.WORKFLOW_CONNECT_TIMEOUT
                    )
                )

            # 记录响应状态
            logger.info(f"工作流API响应状态: {response.status_code}")

            if response.status_code == 200:
                result = response.json()
                logger.info("工作流执行成功")
                return {
                    "message": "工作流执行成功",
                    "data": result,
                    "execution_time": datetime.now().isoformat()
                }
            else:
                logger.error(f"工作流API调用失败: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"工作流执行失败: {response.text}"
                )

    except httpx.TimeoutException:
        logger.error("工作流API调用超时")
        raise HTTPException(
            status_code=408,
            detail="工作流执行超时，请稍后重试"
        )
    except httpx.ConnectError:
        logger.error("无法连接到工作流API")
        raise HTTPException(
            status_code=503,
            detail="无法连接到工作流服务，请检查网络连接"
        )
    except Exception as e:
        logger.error(f"工作流代理错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"代理服务内部错误: {str(e)}"
        )

@router.get("/workflow/config",
            summary="获取工作流配置",
            operation_id="获取PID_AGENT工作流配置",
            description="获取当前工作流代理的配置信息")
async def get_workflow_config():
    """
    **获取工作流配置信息**

    返回当前工作流代理的配置参数，用于调试和监控。
    """
    return {
        "config": {
            "base_url": ProxyConfig.WORKFLOW_BASE_URL,
            "timeout": ProxyConfig.WORKFLOW_TIMEOUT,
            "connect_timeout": ProxyConfig.WORKFLOW_CONNECT_TIMEOUT,
            "read_timeout": ProxyConfig.WORKFLOW_READ_TIMEOUT,
            "health_check_timeout": ProxyConfig.HEALTH_CHECK_TIMEOUT,
            "token_configured": bool(ProxyConfig.WORKFLOW_TOKEN)
        },
        "endpoints": [
            {
                "path": "/api/proxy/workflow/run",
                "method": "POST",
                "description": "执行整定分析"
            },
            {
                "path": "/api/proxy/workflow/config",
                "method": "GET",
                "description": "获取大模型整定配置"
            }
        ]
    }

@router.get("/model-recommendations/{model_type}",
         summary="获取模型推荐信息",
         operation_id="获取模型推荐信息",
         description="根据模型类型获取应用建议和使用说明")
async def get_model_recommendations(model_type: str):
    """
    **获取模型推荐信息**
    
    根据模型类型获取应用建议和使用说明
    """
    try:
        # 调用Service层获取模型推荐信息
        recommendations = AnalysisService.get_model_recommendations(model_type)
        return {
            "model_type": model_type,
            "recommendations": recommendations
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取模型推荐信息失败: {str(e)}"
        )