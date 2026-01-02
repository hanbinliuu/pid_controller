#!/usr/bin/env python3
"""
Ping-Pong 接口
用于健康检查和连通性测试
"""
import logging
from fastapi import APIRouter
from typing import Dict, Any

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")


@router.get(
    "/ping",
    summary="Ping测试",
    operation_id="ping_test"
)
async def ping() -> str:
    """
    简单的Ping测试接口
    返回pong表示服务正常
    """
    return "pong"
