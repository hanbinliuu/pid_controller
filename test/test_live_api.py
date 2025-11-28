# encoding: utf-8
"""
测试实际运行的API响应格式
"""
import requests
import json

BASE_URL = "http://localhost:8001"


def test_api(endpoint, method="GET", data=None):
    """测试API端点"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n{'='*60}")
    print(f"测试: {method} {endpoint}")
    print(f"{'='*60}")
    
    try:
        if method == "GET":
            response = requests.get(url)
        else:
            response = requests.post(url, json=data)
        
        print(f"状态码: {response.status_code}")
        
        # 尝试解析JSON
        try:
            result = response.json()
            print(f"响应格式:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            
            # 验证统一格式
            if 'code' in result and 'message' in result and 'success' in result:
                print(f"\n✓ 符合统一格式")
                print(f"  - code: {result['code']}")
                print(f"  - success: {result['success']}")
                print(f"  - message: {result['message']}")
            else:
                print(f"\n⚠ 未使用统一格式")
                
        except json.JSONDecodeError:
            print("响应不是JSON格式")
            print(response.text[:200])
    
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器,请确保服务已启动")
    except Exception as e:
        print(f"❌ 错误: {e}")


if __name__ == "__main__":
    print("="*60)
    print("实际API响应格式测试")
    print("="*60)
    
    # 测试根路径
    test_api("/")
    
    # 测试健康检查
    test_api("/health")
    
    # 测试参数转换API
    test_api(
        "/api/conversion/pid-to-classical",
        method="POST",
        data={"kp": 1.0, "ki": 0.5, "kd": 0.1}
    )
    
    # 测试参数验证错误
    test_api(
        "/api/conversion/pid-to-classical",
        method="POST",
        data={"kp": "invalid"}
    )
    
    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")
