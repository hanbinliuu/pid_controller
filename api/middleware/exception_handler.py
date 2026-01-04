# encoding: utf-8
"""
全局异常处理器
"""
import logging
import traceback
from typing import Callable
from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError, HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware

from .exceptions import BusinessException
from .response_model import error_response

logger = logging.getLogger(__name__)


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """
    异常处理中间件 - 捕获所有异常并统一处理
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        拦截并处理异常
        
        Args:
            request: 请求对象
            call_next: 下一个处理函数
            
        Returns:
            处理后的响应
        """
        try:
            response = await call_next(request)
            return response
        except BusinessException as exc:
            # 业务异常处理
            logger.warning(
                f"业务异常 - Path: {request.url.path}, Code: {exc.code}, Message: {exc.message}"
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=exc.code,
                    message=exc.message,
                    data=exc.data
                )
            )
        except HTTPException as exc:
            # HTTP异常处理
            logger.warning(
                f"HTTP异常 - Path: {request.url.path}, Status: {exc.status_code}, Detail: {exc.detail}"
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=exc.status_code,
                    message=str(exc.detail) if exc.detail else "请求处理失败",
                    data=None
                )
            )
        except RequestValidationError as exc:
            # 请求参数验证异常处理
            logger.warning(
                f"参数验证失败 - Path: {request.url.path}, Errors: {exc.errors()}"
            )
            
            # 格式化验证错误信息
            error_details = []
            for error in exc.errors():
                field = '.'.join(str(loc) for loc in error['loc'][1:])  # 跳过'body'
                error_details.append({
                    "field": field or "unknown",
                    "message": error['msg'],
                    "type": error['type']
                })
            
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=400,
                    message="请求参数验证失败",
                    data={"errors": error_details}
                )
            )
        except ValidationError as exc:
            # Pydantic验证异常处理
            logger.warning(
                f"数据验证失败 - Path: {request.url.path}, Errors: {exc.errors()}"
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=400,
                    message="数据验证失败",
                    data={"errors": exc.errors()}
                )
            )
        except ValueError as exc:
            # 值错误异常处理
            logger.warning(
                f"值错误 - Path: {request.url.path}, Error: {str(exc)}"
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=400,
                    message=str(exc) or "参数值错误",
                    data=None
                )
            )
        except Exception as exc:
            # 通用异常处理 - 兜底处理所有未捕获的异常
            error_trace = traceback.format_exc()
            logger.error(
                f"通用异常 - Path: {request.url.path}, Error: {str(exc)}\nTraceback: {error_trace}"
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content=error_response(
                    code=500,
                    message="服务器内部错误",
                    data={
                        "error": str(exc),
                        "type": type(exc).__name__
                    } if logger.level == logging.DEBUG else None
                )
            )


def register_exception_handlers(app: FastAPI):
    """
    注册全局异常处理器（兼容性方法，仍然注册handler以处理框架级别的异常）
    
    Args:
        app: FastAPI应用实例
    """
    
    # 注册HTTPException处理器 - 这是关键！
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        logger.warning(
            f"HTTP异常 - Path: {request.url.path}, Status: {exc.status_code}, Detail: {exc.detail}"
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=error_response(
                code=exc.status_code,
                message=str(exc.detail) if exc.detail else "请求处理失败",
                data=None
            )
        )
    
    # 注册异常处理器(用于处理框架级别的异常)
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning(
            f"参数验证失败 - Path: {request.url.path}, Errors: {exc.errors()}"
        )
        error_details = []
        for error in exc.errors():
            field = '.'.join(str(loc) for loc in error['loc'][1:])
            error_details.append({
                "field": field or "unknown",
                "message": error['msg'],
                "type": error['type']
            })
        
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=error_response(
                code=400,
                message="请求参数验证失败",
                data={"errors": error_details}
            )
        )
    
    # logger.info("全局异常处理器注册完成")
