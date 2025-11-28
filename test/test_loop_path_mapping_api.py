#!/usr/bin/env python3
"""
API 快速测试脚本 - 回路路径映射关系管理

使用此脚本可以快速测试回路路径映射的各个 API 接口
"""

import httpx
import json
from typing import Dict, Any

# API 基础 URL
BASE_URL = "http://localhost:8001/api/v1"

# 测试数据
test_mappings = [
    {
        "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
        "loop_path": "/设备/反应器/温度控制",
        "loop_name": "FIC101A流量控制",
        "pv_field": "FIC101A_PV",
        "sv_field": "FIC101A_SV",
        "mv_field": "FIC101A_MV",
        "op_field": "FIC101A_OP"
    },
    {
        "loop_uri": "/pid_zd/xyz789",
        "loop_path": "/设备/冷凝器/温度控制",
        "loop_name": "TIC202温度控制",
        "pv_field": "TIC202_PV",
        "sv_field": "TIC202_SV"
    }
]


def test_create_mapping():
    """测试创建单个映射"""
    print("\n=== 测试创建映射 ===")
    
    with httpx.Client() as client:
        for mapping in test_mappings:
            response = client.post(
                f"{BASE_URL}/loop-path-mapping",
                params=mapping
            )
            print(f"状态码: {response.status_code}")
            print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_get_by_uri():
    """根据 URI 查询映射"""
    print("\n=== 测试根据 URI 查询 ===")
    
    uri = "/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    
    with httpx.Client() as client:
        response = client.get(
            f"{BASE_URL}/loop-path-mapping/by-uri",
            params={"loop_uri": uri}
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_get_by_path():
    """根据路径查询映射"""
    print("\n=== 测试根据路径查询 ===")
    
    path = "/设备/反应器/温度控制"
    
    with httpx.Client() as client:
        response = client.get(
            f"{BASE_URL}/loop-path-mapping/by-path",
            params={"loop_path": path}
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_list_mappings():
    """分页查询映射列表"""
    print("\n=== 测试分页查询映射列表 ===")
    
    with httpx.Client() as client:
        response = client.get(
            f"{BASE_URL}/loop-path-mapping/list",
            params={
                "page_no": 1,
                "page_size": 10
            }
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_get_uri_to_path_map():
    """获取 URI 到路径的映射字典"""
    print("\n=== 测试获取 URI 到路径映射字典 ===")
    
    with httpx.Client() as client:
        response = client.get(
            f"{BASE_URL}/loop-path-mapping/maps/uri-to-path"
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_get_path_to_uri_map():
    """获取路径到 URI 的映射字典"""
    print("\n=== 测试获取路径到 URI 映射字典 ===")
    
    with httpx.Client() as client:
        response = client.get(
            f"{BASE_URL}/loop-path-mapping/maps/path-to-uri"
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_update_mapping():
    """更新映射"""
    print("\n=== 测试更新映射 ===")
    
    uri = "/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    
    with httpx.Client() as client:
        response = client.put(
            f"{BASE_URL}/loop-path-mapping",
            params={
                "loop_uri": uri,
                "loop_name": "FIC101A流量控制(已优化)",
                "pv_field": "FIC101A_PV_NEW"
            }
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_batch_create():
    """批量创建映射"""
    print("\n=== 测试批量创建映射 ===")
    
    batch_data = [
        {
            "loop_uri": "/pid_zd/batch001",
            "loop_path": "/设备/批处理回路1",
            "loop_name": "批处理回路1"
        },
        {
            "loop_uri": "/pid_zd/batch002",
            "loop_path": "/设备/批处理回路2",
            "loop_name": "批处理回路2"
        }
    ]
    
    with httpx.Client() as client:
        response = client.post(
            f"{BASE_URL}/loop-path-mapping/batch",
            json=batch_data
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def test_delete_mapping():
    """删除映射"""
    print("\n=== 测试删除映射 ===")
    
    uri = "/pid_zd/batch001"
    
    with httpx.Client() as client:
        response = client.delete(
            f"{BASE_URL}/loop-path-mapping",
            params={"loop_uri": uri}
        )
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}\n")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("回路路径映射 API 快速测试")
    print("=" * 60)
    
    try:
        test_create_mapping()
        test_get_by_uri()
        test_get_by_path()
        test_list_mappings()
        test_get_uri_to_path_map()
        test_get_path_to_uri_map()
        test_update_mapping()
        test_batch_create()
        test_delete_mapping()
        
        print("\n" + "=" * 60)
        print("✓ 所有测试完成！")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")


if __name__ == "__main__":
    run_all_tests()
