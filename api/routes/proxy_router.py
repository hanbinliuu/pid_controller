#!/usr/bin/env python3
"""
代理接口路由 - 用于调用外部工作流和API
"""

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import httpx
import logging
import os
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

class WorkflowRequest(BaseModel):
    """工作流请求模型"""
    start_time: str = Field(..., description="开始时间", example="2025-10-08 17:30:37")
    end_time: str = Field(..., description="结束时间", example="2025-10-08 18:00:37")
    Kp: str = Field(..., description="比例系数", example="0.25")
    Ki: str = Field(..., description="积分系数", example="0.025")
    Kd: str = Field(..., description="微分系数", example="0")
    SP: str = Field(..., description="设定值", example="380")
    response_mode: str = Field("blocking", description="响应模式", example="blocking")
    # user: str = Field("admin", description="用户名", example="admin")

class ProxyConfig:
    """代理配置"""
    WORKFLOW_BASE_URL = os.getenv("WORKFLOW_BASE_URL", "http://192.168.202.172")
    WORKFLOW_TOKEN = os.getenv("WORKFLOW_TOKEN", "app-LLQlDBTuWW16F8FZTATS6aJ7")
    WORKFLOW_TIMEOUT = int(os.getenv("WORKFLOW_TIMEOUT", "120"))  # 增加到120秒
    WORKFLOW_CONNECT_TIMEOUT = int(os.getenv("WORKFLOW_CONNECT_TIMEOUT", "30"))  # 连接超时30秒
    WORKFLOW_READ_TIMEOUT = int(os.getenv("WORKFLOW_READ_TIMEOUT", "300"))  # 读取超时300秒
    HEALTH_CHECK_TIMEOUT = int(os.getenv("HEALTH_CHECK_TIMEOUT", "10"))  # 健康检查超时10秒

@router.post("/workflow/run",
            operation_id="pid-agent工作流执行",
            summary="执行工作流",
            description="调用外部工作流API执行PID控制相关任务")
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
    
    **参数说明：**
    - start_time: 开始时间（字符串格式）
    - end_time: 结束时间（字符串格式）
    - Kp: 比例系数（字符串格式）
    - Ki: 积分系数（字符串格式）
    - Kd: 微分系数（字符串格式）
    - SP: 设定值（字符串格式）
    - response_mode: 响应模式（blocking/streaming）
    - user: 执行用户
    
    **返回格式：**
    - 直接返回外部工作流的响应结果
    - 包含执行状态和结果数据
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
                "Kp": request.Kp,
                "Ki": request.Ki,
                "Kd": request.Kd,
                "SP": request.SP
            },
            "response_mode": request.response_mode,
            "user": "pid-agent-api"
        }
        
        logger.info(f"调用工作流API: {workflow_url}")
        logger.debug(f"请求数据: {request_data}")
        
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
                "status": "success",
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
           operation_id="获取PID-AGENT工作流配置",
           description="获取当前工作流代理的配置信息")
async def get_workflow_config():
    """
    **获取工作流配置信息**
    
    返回当前工作流代理的配置参数，用于调试和监控。
    """
    return {
        "status": "success",
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
                "description": "执行工作流"
            },
            {
                "path": "/api/proxy/workflow/config",
                "method": "GET", 
                "description": "获取配置信息"
            }
        ]
    }

@router.get("/health",
           summary="代理服务健康检查",
            operation_id="代理服务健康检查",
            description="检查代理服务和外部工作流服务的连接状态")
async def proxy_health_check():
    """
    **代理服务健康检查**
    
    检查代理服务本身和外部工作流服务的可用性。
    """
    health_info = {
        "proxy_service": "healthy",
        "timestamp": datetime.now().isoformat()
    }
    
    # 检查外部工作流服务连接
    try:
        test_url = f"{ProxyConfig.WORKFLOW_BASE_URL}/health"
        async with httpx.AsyncClient() as client:
            response = await client.get(
                test_url, 
                timeout=ProxyConfig.HEALTH_CHECK_TIMEOUT
            )
            if response.status_code == 200:
                health_info["workflow_service"] = "healthy"
            else:
                health_info["workflow_service"] = "unhealthy"
    except:
        health_info["workflow_service"] = "unreachable"
    
    return {
        "status": "ok",
        "service": "proxy-api",
        "health": health_info
    }