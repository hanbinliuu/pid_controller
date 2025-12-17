# encoding: utf-8
"""
请求日志中间件 - 记录所有API请求和响应信息
"""
import logging
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求日志中间件
    
    功能:
    1. 记录每个API请求的基本信息(方法、路径、客户端IP)
    2. 记录请求处理时间
    3. 记录响应状态码
    4. 跳过静态文件和健康检查等特殊端点
    """
    
    # 不需要记录日志的路径前缀
    EXCLUDE_PATHS = {
        '/docs',
        '/redoc',
        '/openapi.json',
        '/static',
        '/health'
    }
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        拦截并记录请求日志
        
        Args:
            request: 请求对象
            call_next: 下一个处理函数
            
        Returns:
            处理后的响应
        """
        # 判断是否需要跳过日志记录
        if self._should_skip(request):
            return await call_next(request)
        
        # 记录请求开始
        start_time = time.time()
        client_ip = self._get_client_ip(request)
        
        # 记录请求信息
        logger.info(
            f"🔵 请求开始 - {request.method} {request.url.path} "
            f"| 客户端: {client_ip}"
        )
        
        # 如果有查询参数,也记录下来
        if request.query_params:
            logger.info(f"   参数: {dict(request.query_params)}")
        
        # 调用下一个处理器
        try:
            response = await call_next(request)
            
            # 计算处理时间
            process_time = time.time() - start_time
            
            # 记录响应信息
            status_emoji = "✅" if 200 <= response.status_code < 300 else "❌"
            logger.info(
                f"{status_emoji} 请求完成 - {request.method} {request.url.path} "
                f"| 状态码: {response.status_code} "
                f"| 耗时: {process_time:.3f}s"
            )
            
            return response
            
        except Exception as exc:
            # 记录异常
            process_time = time.time() - start_time
            logger.error(
                f"❌ 请求异常 - {request.method} {request.url.path} "
                f"| 错误: {str(exc)} "
                f"| 耗时: {process_time:.3f}s"
            )
            # 重新抛出异常，让上层处理
            raise
    
    def _should_skip(self, request: Request) -> bool:
        """
        判断是否应该跳过日志记录
        
        Args:
            request: 请求对象
            
        Returns:
            是否跳过
        """
        path = request.url.path
        
        # 跳过特定路径
        for exclude_path in self.EXCLUDE_PATHS:
            if path.startswith(exclude_path):
                return True
        
        return False
    
    def _get_client_ip(self, request: Request) -> str:
        """
        获取客户端真实IP地址
        
        Args:
            request: 请求对象
            
        Returns:
            客户端IP地址
        """
        # 尝试从代理头中获取真实IP
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For 可能包含多个IP,取第一个
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        
        # 回退到客户端地址
        if request.client:
            return request.client.host
        
        return "unknown"
