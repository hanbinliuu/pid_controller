# encoding: utf-8
"""
测试BFF接口响应格式
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)


def test_bff_point_paths():
    """测试BFF测点路径接口响应格式"""
    print("\n测试: BFF测点路径接口")
    
    # 注意:这个测试需要实际的BFF服务,这里只是验证响应格式
    response = client.get(
        "/api/bff/point-paths",
        params={"project_path": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca"}
    )
    
    print(f"状态码: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"响应数据结构:")
        print(f"  - 顶层键: {list(data.keys())}")
        
        # 验证是否被包装为统一格式
        if "code" in data and "message" in data and "success" in data:
            print(f"\n✓ 已被包装为统一格式")
            print(f"  - code: {data.get('code')}")
            print(f"  - success: {data.get('success')}")
            print(f"  - message: {data.get('message')}")
            
            # 检查data字段
            if "data" in data:
                inner_data = data.get("data")
                if isinstance(inner_data, dict):
                    print(f"  - data字段包含: {list(inner_data.keys())}")
                    
                    # 验证原始响应是否在data中
                    if "status" in inner_data:
                        print(f"  - 原始status字段保留在data中: {inner_data.get('status')}")
        else:
            print(f"\n⚠ 未被包装,原始响应:")
            print(f"  - {list(data.keys())}")
    else:
        print(f"请求失败: {response.text}")


def test_bff_config():
    """测试BFF配置接口响应格式"""
    print("\n测试: BFF配置接口")
    
    response = client.get("/api/bff/config")
    print(f"状态码: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"响应数据结构:")
        print(f"  - 顶层键: {list(data.keys())}")
        
        if "code" in data and "message" in data and "success" in data:
            print(f"\n✓ 已被包装为统一格式")
            print(f"  - code: {data.get('code')}")
            print(f"  - success: {data.get('success')}")
        else:
            print(f"\n⚠ 未被包装")


if __name__ == "__main__":
    print("=" * 60)
    print("BFF接口响应格式测试")
    print("=" * 60)
    
    try:
        test_bff_point_paths()
        test_bff_config()
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试错误: {e}")
        import traceback
        traceback.print_exc()
