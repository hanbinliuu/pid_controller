#!/usr/bin/env python3
"""
测试表名和测点映射查询功能
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.agent.tools import query_table_and_points
from core.data.bff_model_client import BFFModelClient


def test_query_table_and_points_default():
    """测试使用默认配置查询表名和测点列表"""
    print("\n" + "="*80)
    print("测试1：使用默认配置查询表名和测点列表")
    print("="*80)
    
    result = query_table_and_points()
    
    print(f"\n查询状态: {result.get('status')}")
    print(f"消息: {result.get('message')}")
    print(f"项目路径: {result.get('project_path')}")
    print(f"测点路径: {result.get('point_path')}")
    print(f"表名: {result.get('table_name')}")
    print(f"测点数量: {result.get('total_points')}")
    print(f"\n测点映射:")
    points = result.get('points', {})
    for key, value in points.items():
        print(f"  {key}: {value}")


def test_query_table_and_points_custom():
    """测试使用自定义路径查询"""
    print("\n" + "="*80)
    print("测试2：使用自定义路径查询表名和测点列表")
    print("="*80)
    
    # 使用自定义路径（根据实际情况修改）
    custom_project_path = "/pid_zd/ce716ffbade5426e8faf18467d1d5a83"
    custom_point_path = "/ZTCS"
    
    result = query_table_and_points(
        project_path=custom_project_path,
        point_path=custom_point_path
    )
    
    print(f"\n查询状态: {result.get('status')}")
    print(f"消息: {result.get('message')}")
    print(f"项目路径: {result.get('project_path')}")
    print(f"测点路径: {result.get('point_path')}")
    print(f"表名: {result.get('table_name')}")
    print(f"测点数量: {result.get('total_points')}")
    print(f"\n测点映射:")
    points = result.get('points', {})
    for key, value in points.items():
        print(f"  {key}: {value}")


def test_extract_table_and_points_from_paths():
    """测试从路径中提取表名和测点的静态方法"""
    print("\n" + "="*80)
    print("测试3：测试extract_table_and_points_from_paths静态方法")
    print("="*80)
    
    # 模拟query_paths（查询时传入的browse_paths）
    query_paths = [
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/MV",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/PV",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/SV",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/PB",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/TI",
        "/pid_zd/ce716ffbade5426e8faf18467d1d5a83/ZTCS/TD"
    ]
    
    # 模拟BFF返回的路径列表
    result_paths = [
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_SV.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PB.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TI.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TD.In_Channel0"
    ]
    
    print("\n查询路径列表 (query_paths):")
    for path in query_paths:
        print(f"  {path}")
    
    print("\n返回路径列表 (result_paths):")
    for path in result_paths:
        print(f"  {path}")
    
    result = BFFModelClient.extract_table_and_points_from_paths(query_paths, result_paths)
    
    print(f"\n解析结果:")
    print(f"表名: {result.get('table_name')}")
    print(f"测点数量: {len(result.get('points', {}))}")
    print(f"\n测点映射:")
    points = result.get('points', {})
    for key, value in points.items():
        print(f"  {key}: {value}")


def test_edge_cases():
    """测试边界情况"""
    print("\n" + "="*80)
    print("测试4：测试边界情况")
    print("="*80)
    
    # 测试空列表
    print("\n4.1 测试空列表:")
    result = BFFModelClient.extract_table_and_points_from_paths([], [])
    print(f"  表名: {result.get('table_name')}")
    print(f"  测点映射: {result.get('points')}")
    
    # 测试不规范的路径
    print("\n4.2 测试不规范的路径:")
    query_paths = [
        "/project/point/MV",
        "/project/point/PV",
        "/project/point/SV"
    ]
    irregular_paths = [
        "ns=100;s=FIC101A_MV.In_Channel0",  # 没有table部分
        "/table_name/",  # 没有测点部分
        "invalid_path"  # 完全不规范
    ]
    result = BFFModelClient.extract_table_and_points_from_paths(query_paths, irregular_paths)
    print(f"  表名: {result.get('table_name')}")
    print(f"  测点映射: {result.get('points')}")


if __name__ == "__main__":
    try:
        # 运行所有测试
        test_extract_table_and_points_from_paths()
        test_edge_cases()
        test_query_table_and_points_default()
        # test_query_table_and_points_custom()  # 需要实际的BFF服务才能运行
        
        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
