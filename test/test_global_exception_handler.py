# encoding: utf-8
"""
测试全局异常处理和响应包装功能
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.middleware import register_exception_handlers, ExceptionHandlerMiddleware, ResponseMiddleware
from api.middleware.exceptions import (
    BusinessException,
    ValidationException,
    NotFoundException,
    DataProcessException
)


# 创建测试应用
app = FastAPI()

# 注册全局异常处理器
register_exception_handlers(app)

# 添加异常处理中间件
app.add_middleware(ExceptionHandlerMiddleware)

# 添加响应中间件
app.add_middleware(ResponseMiddleware)


# 测试路由
@app.get("/test/success")
async def test_success():
    """测试正常响应"""
    return {"result": "success", "value": 123}


@app.get("/test/business-error")
async def test_business_error():
    """测试业务异常"""
    raise BusinessException(message="这是一个业务异常", code=400)


@app.get("/test/not-found")
async def test_not_found():
    """测试资源不存在异常"""
    raise NotFoundException(message="资源未找到")


@app.get("/test/validation-error")
async def test_validation_error():
    """测试参数验证异常"""
    raise ValidationException(
        message="参数验证失败",
        data={"field": "name", "error": "必填项"}
    )


@app.get("/test/data-process-error")
async def test_data_process_error():
    """测试数据处理异常"""
    raise DataProcessException(
        message="数据处理失败",
        data={"reason": "格式错误"}
    )


@app.get("/test/value-error")
async def test_value_error():
    """测试值错误"""
    raise ValueError("参数值不合法")


@app.get("/test/general-error")
async def test_general_error():
    """测试通用异常"""
    raise Exception("未知错误")


@app.get("/test/division-error")
async def test_division_error():
    """测试除零错误"""
    result = 1 / 0
    return {"result": result}


@app.get("/test/standard-format")
async def test_standard_format():
    """测试已经是标准格式的响应(不应重复包装)"""
    return {
        "code": 0,
        "message": "success",
        "data": {"value": 999},
        "success": True
    }


# 创建测试客户端
client = TestClient(app)


def test_normal_response_wrapping():
    """测试正常响应自动包装"""
    print("\n测试1: 正常响应自动包装")
    response = client.get("/test/success")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 0
    assert data["success"] is True
    assert data["message"] == "success"
    assert "data" in data
    print("✓ 正常响应包装成功")


def test_business_exception_handling():
    """测试业务异常处理"""
    print("\n测试2: 业务异常处理")
    response = client.get("/test/business-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 400
    assert data["success"] is False
    assert "业务异常" in data["message"]
    print("✓ 业务异常处理成功")


def test_not_found_exception():
    """测试资源不存在异常"""
    print("\n测试3: 资源不存在异常")
    response = client.get("/test/not-found")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 404
    assert data["success"] is False
    assert "未找到" in data["message"]
    print("✓ 资源不存在异常处理成功")


def test_validation_exception():
    """测试参数验证异常"""
    print("\n测试4: 参数验证异常")
    response = client.get("/test/validation-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 400
    assert data["success"] is False
    assert "验证失败" in data["message"]
    assert data["data"] is not None
    print("✓ 参数验证异常处理成功")


def test_data_process_exception():
    """测试数据处理异常"""
    print("\n测试5: 数据处理异常")
    response = client.get("/test/data-process-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 500
    assert data["success"] is False
    assert "数据处理" in data["message"]
    print("✓ 数据处理异常处理成功")


def test_value_error_handling():
    """测试值错误处理"""
    print("\n测试6: 值错误处理")
    response = client.get("/test/value-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 400
    assert data["success"] is False
    assert "不合法" in data["message"]
    print("✓ 值错误处理成功")


def test_general_exception_handling():
    """测试通用异常处理"""
    print("\n测试7: 通用异常处理")
    response = client.get("/test/general-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 500
    assert data["success"] is False
    assert "服务器内部错误" in data["message"]
    print("✓ 通用异常处理成功")


def test_division_error_handling():
    """测试除零错误处理"""
    print("\n测试8: 除零错误处理")
    response = client.get("/test/division-error")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 500
    assert data["success"] is False
    print("✓ 除零错误处理成功")


def test_standard_format_no_rewrap():
    """测试标准格式响应不重复包装"""
    print("\n测试9: 标准格式响应不重复包装")
    response = client.get("/test/standard-format")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    assert data["code"] == 0
    assert data["success"] is True
    assert data["data"]["value"] == 999
    # 确保没有嵌套的data字段
    assert "data" not in data.get("data", {})
    print("✓ 标准格式不重复包装成功")


def test_health_check_excluded():
    """测试健康检查端点不被包装"""
    print("\n测试10: 健康检查端点排除")
    
    @app.get("/health")
    async def health():
        return {"status": "ok"}
    
    response = client.get("/health")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    assert response.status_code == 200
    # 健康检查端点应该不被包装
    assert "status" in data
    print("✓ 健康检查端点排除成功")


if __name__ == "__main__":
    print("=" * 60)
    print("全局异常处理和响应包装功能测试")
    print("=" * 60)
    
    try:
        test_normal_response_wrapping()
        test_business_exception_handling()
        test_not_found_exception()
        test_validation_exception()
        test_data_process_exception()
        test_value_error_handling()
        test_general_exception_handling()
        test_division_error_handling()
        test_standard_format_no_rewrap()
        test_health_check_excluded()
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试错误: {e}")
        import traceback
        traceback.print_exc()
