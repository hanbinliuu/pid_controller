# encoding: utf-8
"""
自定义业务异常类
"""


class BusinessException(Exception):
    """
    业务异常基类
    
    Attributes:
        code: 错误码
        message: 错误消息
        data: 额外的错误数据
    """
    
    def __init__(self, message: str = "业务错误", code: int = -1, data: any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(self.message)


class ValidationException(BusinessException):
    """参数验证异常"""
    
    def __init__(self, message: str = "参数验证失败", data: any = None):
        super().__init__(message=message, code=-1, data=data)


class NotFoundException(BusinessException):
    """资源不存在异常"""
    
    def __init__(self, message: str = "资源不存在", data: any = None):
        super().__init__(message=message, code=404, data=data)


class UnauthorizedException(BusinessException):
    """未授权异常"""
    
    def __init__(self, message: str = "未授权访问", data: any = None):
        super().__init__(message=message, code=401, data=data)


class ForbiddenException(BusinessException):
    """禁止访问异常"""
    
    def __init__(self, message: str = "禁止访问", data: any = None):
        super().__init__(message=message, code=403, data=data)


class DataProcessException(BusinessException):
    """数据处理异常"""
    
    def __init__(self, message: str = "数据处理失败", data: any = None):
        super().__init__(message=message, code=500, data=data)


class RuntimeException(BusinessException):
    """程序执行异常"""

    def __init__(self, message: str = "程序执行异常", data: any = None):
        super().__init__(message=message, code=-1, data=data)

class ExternalServiceException(BusinessException):
    """外部服务调用异常"""
    
    def __init__(self, message: str = "外部服务调用失败", data: any = None):
        super().__init__(message=message, code=503, data=data)
