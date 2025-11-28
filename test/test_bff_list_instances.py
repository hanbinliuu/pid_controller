#!/usr/bin/env python3
"""
测试BFF实例列表查询功能
"""

import sys
import os
import json

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.data.bff_model_client import BFFModelClient, list_instances


def test_list_instances_with_client():
    """测试使用BFFModelClient直接查询"""
    print("\n" + "="*80)
    print("测试1：使用BFFModelClient直接查询实例列表")
    print("="*80)
    
    try:
        with BFFModelClient() as client:
            result = client.list_instances_under_tree(
                model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
                start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde'],
                page_no=1,
                page_size=10
            )
            
            print(f"\n查询结果:")
            print(f"总数: {result['pagination']['total']}")
            print(f"总页数: {result['pagination']['pages']}")
            print(f"当前页: {result['pagination']['pageNo']}")
            print(f"每页数量: {result['pagination']['pageSize']}")
            print(f"\n实例列表 ({len(result['instances'])} 个):")
            
            for i, instance in enumerate(result['instances'], 1):
                print(f"\n  实例 {i}:")
                print(f"    URI: {instance['uri']}")
                print(f"    浏览名称: {instance['browseName']}")
                print(f"    显示名称: {instance['displayName']}")
                print(f"    描述: {instance['description']}")
                print(f"    扩展属性: {json.dumps(instance['extendedAttr'], ensure_ascii=False)}")
    
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


def test_list_instances_with_convenience_function():
    """测试使用便捷函数查询"""
    print("\n" + "="*80)
    print("测试2：使用便捷函数查询实例列表")
    print("="*80)
    
    try:
        result = list_instances(
            model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
            start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde'],
            contain_sub_model=True,
            page_no=1,
            page_size=5
        )
        
        print(f"\n查询结果:")
        print(f"总数: {result['pagination']['total']}")
        print(f"实例数量: {len(result['instances'])}")
        
        if result['instances']:
            print(f"\n第一个实例:")
            first_instance = result['instances'][0]
            print(f"  URI: {first_instance['uri']}")
            print(f"  显示名称: {first_instance['displayName']}")
            print(f"  扩展属性: {json.dumps(first_instance['extendedAttr'], ensure_ascii=False)}")
    
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


def test_pagination():
    """测试分页功能"""
    print("\n" + "="*80)
    print("测试3：测试分页功能")
    print("="*80)
    
    try:
        # 第1页
        page1 = list_instances(
            model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
            start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde'],
            page_no=1,
            page_size=1
        )
        
        print(f"\n第1页:")
        print(f"  总数: {page1['pagination']['total']}")
        print(f"  总页数: {page1['pagination']['pages']}")
        print(f"  当前页实例数: {len(page1['instances'])}")
        
        if page1['pagination']['pages'] > 1:
            # 第2页
            page2 = list_instances(
                model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
                start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde'],
                page_no=2,
                page_size=1
            )
            
            print(f"\n第2页:")
            print(f"  当前页实例数: {len(page2['instances'])}")
            
            # 验证两页数据不同
            if page1['instances'] and page2['instances']:
                if page1['instances'][0]['uri'] != page2['instances'][0]['uri']:
                    print(f"\n✅ 分页功能正常，两页数据不同")
                else:
                    print(f"\n⚠️ 警告：两页数据相同")
    
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    try:
        test_list_instances_with_client()
        test_list_instances_with_convenience_function()
        test_pagination()
        
        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
