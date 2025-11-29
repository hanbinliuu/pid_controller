#!/usr/bin/env python3
"""
测试字典格式的路径解析功能
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.client.bff_model_client import BFFModelClient


def test_dict_format_extraction():
    """测试字典格式输入的路径解析"""
    print("\n" + "="*80)
    print("测试：字典格式路径解析")
    print("="*80)
    
    # 字典格式输入（用户提供的示例）
    path_dict = {
        'MV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0',
        'PB': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PB.In_Channel0',
        'PV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0',
        'SV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_SV.In_Channel0',
        'TD': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TD.In_Channel0',
        'TI': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TI.In_Channel0'
    }
    
    print("\n输入字典:")
    for key, value in path_dict.items():
        print(f"  {key}: {value}")
    
    # 调用解析方法
    result = BFFModelClient.extract_table_and_points_from_paths(path_dict)
    
    print(f"\n解析结果:")
    print(f"表名: {result.get('table_name')}")
    print(f"测点数量: {len(result.get('points', {}))}")
    print(f"\n测点映射（小写键名）:")
    points = result.get('points', {})
    for key, value in points.items():
        print(f"  {key}: {value}")
    
    # 验证结果
    assert result.get('table_name') == 'PID_FEP_Gateway_Device_001default', "表名解析错误"
    assert len(points) == 6, f"测点数量错误，期望6个，实际{len(points)}个"
    assert 'mv' in points, "缺少mv字段"
    assert 'pv' in points, "缺少pv字段"
    assert 'sv' in points, "缺少sv字段"
    assert 'pb' in points, "缺少pb字段"
    assert 'ti' in points, "缺少ti字段"
    assert 'td' in points, "缺少td字段"
    
    # 验证测点名称提取正确（不包含表名）
    assert points['mv'] == 'ns=100;s=FIC101A_MV.In_Channel0', "mv测点名称解析错误"
    assert points['pv'] == 'ns=100;s=FIC101A_PV.In_Channel0', "pv测点名称解析错误"
    
    print("\n✅ 字典格式解析测试通过！")


def test_partial_dict():
    """测试部分字段的字典输入"""
    print("\n" + "="*80)
    print("测试：部分字段字典")
    print("="*80)
    
    path_dict = {
        'MV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0',
        'PV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0',
        'SV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_SV.In_Channel0'
    }
    
    result = BFFModelClient.extract_table_and_points_from_paths(path_dict)
    
    print(f"\n表名: {result.get('table_name')}")
    print(f"测点数量: {len(result.get('points', {}))}")
    print(f"测点映射:")
    for key, value in result.get('points', {}).items():
        print(f"  {key}: {value}")
    
    assert result.get('table_name') == 'PID_FEP_Gateway_Device_001default'
    assert len(result.get('points', {})) == 3
    
    print("\n✅ 部分字段测试通过！")


def test_list_format_backward_compatibility():
    """测试列表格式的向后兼容性"""
    print("\n" + "="*80)
    print("测试：列表格式向后兼容性")
    print("="*80)
    
    query_paths = [
        "/project/MV",
        "/project/PV",
        "/project/SV"
    ]
    
    result_paths = [
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0",
        "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_SV.In_Channel0"
    ]
    
    result = BFFModelClient.extract_table_and_points_from_paths(query_paths, result_paths)
    
    print(f"\n表名: {result.get('table_name')}")
    print(f"测点数量: {len(result.get('points', {}))}")
    print(f"测点映射:")
    for key, value in result.get('points', {}).items():
        print(f"  {key}: {value}")
    
    assert result.get('table_name') == 'PID_FEP_Gateway_Device_001default'
    assert len(result.get('points', {})) == 3
    
    print("\n✅ 列表格式向后兼容性测试通过！")


def test_edge_cases():
    """测试边界情况"""
    print("\n" + "="*80)
    print("测试：边界情况")
    print("="*80)
    
    # 空字典
    print("\n1. 空字典:")
    result = BFFModelClient.extract_table_and_points_from_paths({})
    print(f"   表名: {result.get('table_name')}")
    print(f"   测点数量: {len(result.get('points', {}))}")
    assert result.get('table_name') is None
    assert len(result.get('points', {})) == 0
    
    # 包含None值的字典
    print("\n2. 包含None值:")
    path_dict = {
        'MV': '/table/point_mv',
        'PV': None,
        'SV': ''
    }
    result = BFFModelClient.extract_table_and_points_from_paths(path_dict)
    print(f"   表名: {result.get('table_name')}")
    print(f"   测点数量: {len(result.get('points', {}))}")
    assert 'mv' in result.get('points', {})
    assert 'pv' not in result.get('points', {})  # None值应该被跳过
    
    # 不规范的路径（没有/）
    print("\n3. 不规范路径:")
    path_dict = {
        'MV': 'ns=100;s=FIC101A_MV.In_Channel0',
        'PV': 'ns=100;s=FIC101A_PV.In_Channel0'
    }
    result = BFFModelClient.extract_table_and_points_from_paths(path_dict)
    print(f"   表名: {result.get('table_name')}")
    print(f"   测点映射: {result.get('points', {})}")
    assert result.get('table_name') is None  # 没有table名称
    assert len(result.get('points', {})) == 2  # 但测点名称应该存在
    
    print("\n✅ 边界情况测试通过！")


if __name__ == "__main__":
    try:
        test_dict_format_extraction()
        test_partial_dict()
        test_list_format_backward_compatibility()
        test_edge_cases()
        
        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80)
        
    except AssertionError as e:
        print(f"\n❌ 断言失败: {str(e)}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
