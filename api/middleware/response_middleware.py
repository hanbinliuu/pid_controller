# encoding: utf-8
"""
响应拦截中间件 - 统一包装所有API响应
"""
import json
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, StreamingResponse

from .response_model import success_response

logger = logging.getLogger(__name__)


class ResponseMiddleware(BaseHTTPMiddleware):
    """
    全局响应拦截中间件
    
    功能:
    1. 自动包装所有成功的API响应为统一格式
    2. 跳过静态文件、健康检查等特殊端点
    3. 跳过已经是标准格式的响应(避免重复包装)
    """
    
    # 不需要包装的路径前缀
    EXCLUDE_PATHS = {
        '/docs',
        '/redoc',
        '/openapi.json',
        '/static',
        '/health'
    }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        拦截并处理响应
        
        Args:
            request: 请求对象
            call_next: 下一个处理函数
            
        Returns:
            处理后的响应
        """
        # 调用下一个处理器获取响应
        response = await call_next(request)
        
        # 判断是否需要跳过包装
        if self._should_skip(request, response):
            return response
        
        # 只处理JSON响应
        content_type = response.headers.get('content-type', '')
        if 'application/json' not in content_type:
            return response
        
        # 只处理成功的响应 (2xx状态码)
        if not (200 <= response.status_code < 300):
            return response
        
        try:
            # 读取响应体
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            
            # 解析JSON
            if response_body:
                try:
                    data = json.loads(response_body.decode())
                    
                    # 检查是否已经是全局标准格式(由异常处理器包装过)
                    # 如果包含 {code, message, success} 字段,说明已经被处理过
                    if isinstance(data, dict) and 'code' in data and 'message' in data and 'success' in data:
                        # 已经是标准格式,直接返回,不再包装
                        # 移除原始的Content-Length,让FastAPI自动计算
                        headers = dict(response.headers)
                        headers.pop('content-length', None)
                        return JSONResponse(
                            content=data,
                            status_code=response.status_code,
                            headers=headers
                        )
                    
                    # 普通响应,直接包装
                    wrapped_data = success_response(data=data)
                    
                    # 移除原始的Content-Length,让FastAPI自动计算
                    headers = dict(response.headers)
                    headers.pop('content-length', None)
                    return JSONResponse(
                        content=wrapped_data,
                        status_code=200,
                        headers=headers
                    )
                    
                except json.JSONDecodeError:
                    # JSON解析失败,返回原响应
                    logger.warning(f"响应体JSON解析失败: {request.url.path}")
                    return Response(
                        content=response_body,
                        status_code=response.status_code,
                        headers=dict(response.headers)
                    )
            
            return response
            
        except Exception as e:
            logger.error(f"响应拦截处理失败: {str(e)}, Path: {request.url.path}")
            return response
    
    def _should_skip(self, request: Request, response: Response) -> bool:
        """
        判断是否应该跳过响应包装
        
        Args:
            request: 请求对象
            response: 响应对象
            
        Returns:
            是否跳过
        """
        path = request.url.path
        
        # 跳过特定路径
        for exclude_path in self.EXCLUDE_PATHS:
            if path.startswith(exclude_path):
                return True
        
        # 跳过流式响应
        if isinstance(response, StreamingResponse):
            return True
        
        return False
