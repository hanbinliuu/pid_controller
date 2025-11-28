#!/usr/bin/env python3
"""
BFF模型查询客户端测试脚本

使用说明：
1. 项目路径前缀（如：/pid_zd/ce716ffbade5426e8faf18467d1d5a83）是动态传入的参数
2. 后面的路径后缀（如：/SBCS/ns_100_s_FIC101A_MV_In_Channel0）是固定写死的
3. 完整路径 = 项目路径前缀 + 路径后缀

配置方式：
1. 环境变量（推荐）：
   - BFF_MODEL_BASE_URL: BFF服务基础URL
   - BFF_MODEL_TIMEOUT: 请求超时时间
   - BFF_MODEL_PROJECT_PATH: 项目路径前缀
   
2. 代码中覆盖：
   client = BFFModelClient(project_path="/pid_zd/custom_id")

示例：
- 默认项目路径：/pid_zd/ce716ffbade5426e8faf18467d1d5a83
- MV路径后缀：/SBCS/ns_100_s_FIC101A_MV_In_Channel0
- 完整路径：/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_MV_In_Channel0
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.data.bff_model_client import BFFModelClient, query_pid_values, query_specific_fields
import json


def test_query_common_fields():
    """测试查询常用字段"""
    print("=" * 60)
    print("测试1: 查询所有常用PID字段")
    print("=" * 60)
    
    try:
        with BFFModelClient() as client:
            # 查询所有常用字段
            response = client.query_common_fields()
            print(f"\n✓ 查询成功")
            print(f"响应数据:\n{json.dumps(response, indent=2, ensure_ascii=False)}")
            
            # 解析响应
            values = client.parse_response(response)
            print(f"\n解析后的值:")
            for key, value in values.items():
                print(f"  {key.upper()}: {value}")
    
    except Exception as e:
        print(f"\n✗ 查询失败: {str(e)}")


def test_query_custom_fields():
    """测试查询自定义字段"""
    print("\n" + "=" * 60)
    print("测试2: 查询指定字段 (MV, PV, SV)")
    print("=" * 60)
    
    try:
        with BFFModelClient() as client:
            # 只查询MV, PV, SV
            response = client.query_custom_fields(['mv', 'pv', 'sv'])
            print(f"\n✓ 查询成功")
            print(f"响应数据:\n{json.dumps(response, indent=2, ensure_ascii=False)}")
            
            # 解析响应
            values = client.parse_response(response)
            print(f"\n解析后的值:")
            for key, value in values.items():
                print(f"  {key.upper()}: {value}")
    
    except Exception as e:
        print(f"\n✗ 查询失败: {str(e)}")


def test_raw_browse_paths():
    """测试使用原始浏览路径"""
    print("\n" + "=" * 60)
    print("测试3: 使用原始浏览路径列表")
    print("=" * 60)
    
    browse_paths = [
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_MV_In_Channel0",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_PV_In_Channel0",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_SV_In_Channel0",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_PB_In_Channel0",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_TI_In_Channel0",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/SBCS/ns_100_s_FIC101A_TD_In_Channel0"
    ]
    
    try:
        with BFFModelClient() as client:
            response = client.query_values_by_browse_path(browse_paths)
            print(f"\n✓ 查询成功")
            print(f"响应数据:\n{json.dumps(response, indent=2, ensure_ascii=False)}")
    
    except Exception as e:
        print(f"\n✗ 查询失败: {str(e)}")


def test_convenience_functions():
    """测试便捷函数"""
    print("\n" + "=" * 60)
    print("测试4: 使用便捷函数")
    print("=" * 60)
    
    try:
        # 方式1: 查询所有PID值
        print("\n方式1: 查询所有PID值")
        values = query_pid_values()
        print("查询结果:")
        for key, value in values.items():
            print(f"  {key.upper()}: {value}")
        
        # 方式2: 查询指定字段
        print("\n方式2: 查询指定字段")
        values = query_specific_fields(['mv', 'pv'])
        print("查询结果:")
        for key, value in values.items():
            print(f"  {key.upper()}: {value}")
    
    except Exception as e:
        print(f"\n✗ 查询失败: {str(e)}")


def test_build_browse_path():
    """测试构建浏览路径"""
    print("\n" + "=" * 60)
    print("测试5: 构建自定义浏览路径")
    print("=" * 60)
    
    # 使用默认项目路径
    client = BFFModelClient()
    path1 = client.build_browse_path('ns_100_s_FIC101A_MV_In_Channel0')
    path2 = client.build_browse_path('ns_100_s_FIC101A_PV_In_Channel0')
    print(f"\n默认项目路径: {client.device_uri}")
    print(f"MV完整路径: {path1}")
    print(f"PV完整路径: {path2}")
    
    # 使用自定义项目路径
    custom_client = BFFModelClient(device_uri="/pid_zd/custom_project_id")
    path3 = custom_client.build_browse_path('ns_100_s_FIC101A_SV_In_Channel0')
    print(f"\n自定义项目路径: {custom_client.device_uri}")
    print(f"SV完整路径: {path3}")
    
    # 测试query_by_custom_suffixes
    print("\n测试自定义后缀查询:")
    custom_suffixes = [
        '/SBCS/ns_100_s_FIC101A_MV_In_Channel0',
        '/SBCS/ns_100_s_FIC101A_PV_In_Channel0'
    ]
    try:
        response = custom_client.query_by_custom_suffixes(custom_suffixes)
        print(f"查询成功，返回数据: {json.dumps(response, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"查询失败: {str(e)}")


if __name__ == "__main__":
    print("\n" + "🚀 " * 20)
    print("BFF模型查询客户端测试")
    print("🚀 " * 20 + "\n")
    
    # 运行所有测试
    test_query_common_fields()
    test_query_custom_fields()
    test_raw_browse_paths()
    test_convenience_functions()
    test_build_browse_path()
    
    print("\n" + "=" * 60)
    print("✅ 所有测试完成!")
    print("=" * 60 + "\n")
