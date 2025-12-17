# encoding: utf-8
"""
测试API响应格式统一包装
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from run_server import app

client = TestClient(app)


def test_root_endpoint():
    """测试根路径响应格式"""
    print("\n测试1: 根路径响应格式")
    response = client.get("/")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    # 验证统一格式
    assert response.status_code == 200
    assert "code" in data
    assert "message" in data
    assert "data" in data
    assert "success" in data
    assert data["code"] == 0
    assert data["success"] is True
    print("✓ 根路径响应格式正确")


def test_health_check_excluded():
    """测试健康检查端点不被包装"""
    print("\n测试2: 健康检查端点不被包装")
    response = client.get("/health")
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    # 健康检查应该不被包装
    assert response.status_code == 200
    assert "status" in data
    assert data["status"] == "ok"
    # 不应该有统一格式的字段
    print("✓ 健康检查端点正确排除包装")


def test_conversion_api_format():
    """测试参数转换API响应格式"""
    print("\n测试3: 参数转换API响应格式")
    
    # 测试数据
    test_params = {
        "kp": 1.0,
        "ki": 0.5,
        "kd": 0.1
    }
    
    response = client.post("/api/conversion/pid-to-classical", json=test_params)
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    # 验证统一格式
    assert response.status_code == 200
    assert "code" in data
    assert "message" in data
    assert "data" in data
    assert "success" in data
    assert data["code"] == 0
    assert data["success"] is True
    print("✓ 参数转换API响应格式正确")


def test_validation_error_format():
    """测试参数验证错误响应格式"""
    print("\n测试4: 参数验证错误响应格式")
    
    # 发送无效数据
    invalid_params = {
        "kp": "invalid"  # 应该是数字
    }
    
    response = client.post("/api/conversion/pid-to-classical", json=invalid_params)
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"响应数据: {data}")
    
    # 验证错误格式
    assert response.status_code == 200  # 统一返回200
    assert "code" in data
    assert "message" in data
    assert "success" in data
    assert data["code"] == 400
    assert data["success"] is False
    print("✓ 参数验证错误响应格式正确")


def test_docs_excluded():
    """测试文档端点不被包装"""
    print("\n测试5: API文档端点不被包装")
    response = client.get("/docs")
    print(f"状态码: {response.status_code}")
    
    # 文档端点应该返回HTML
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    print("✓ API文档端点正确排除包装")


if __name__ == "__main__":
    print("=" * 60)
    print("API响应格式统一包装测试")
    print("=" * 60)
    
    try:
        test_root_endpoint()
        test_health_check_excluded()
        test_conversion_api_format()
        test_validation_error_format()
        test_docs_excluded()
        
        print("\n" + "=" * 60)
        print("✓ 所有测试通过! API响应已统一包装为标准格式")
        print("=" * 60)
        print("\n标准响应格式:")
        print("成功响应: {")
        print('  "code": 0,')
        print('  "message": "success",')
        print('  "data": {...},')
        print('  "success": true')
        print("}")
        print("\n错误响应: {")
        print('  "code": 错误码,')
        print('  "message": "错误信息",')
        print('  "data": {...},')
        print('  "success": false')
        print("}")
        
    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ 测试错误: {e}")
        import traceback
        traceback.print_exc()
