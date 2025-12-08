#!/usr/bin/env python3
"""
BFF模型树解析测试脚本
演示如何使用BFF模型树解析和处理模块
"""
import sys
import os
import json

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.client.bff_model_client import (
    BFFModelTreeParser,
    ModelTreeAnalyzer,
    TreeNode,
    ModelTree
)


# BFF响应示例数据
BFF_RESPONSE_EXAMPLE = {
    "code": 200,
    "subCode": None,
    "message": "请求正常",
    "result": {
        "node": {
            "uri": "/pid_zd/053f3c45413b48bbafacec609d142e57",
            "parentUri": "/pid_zd/instance",
            "projectUri": "/pid_zd/root",
            "browseName": "factory",
            "displayName": "某石化工厂",
            "description": "通用文件夹",
            "tags": [],
            "icon": None,
            "order": 0,
            "rootUri": "/pid_zd/053f3c45413b48bbafacec609d142e57",
            "modellingRule": "NONE",
            "creator": "管理员",
            "modifier": "管理员",
            "modelUri": "/system/401",
            "createdTimestamp": 1763709795743,
            "modifyTimestamp": 1763709795743,
            "tableName": None,
            "browseNamePath": "root,pid_zd,instance,factory",
            "displayNamePath": "root,PID参数整定_勿删,PID参数整定_勿删,某石化工厂",
            "uriPath": "/system/root,/pid_zd/root,/pid_zd/instance,/pid_zd/053f3c45413b48bbafacec609d142e57",
            "nodeClass": "FOLDER",
            "label": "FOLDER",
            "extendedAttr": None,
            "tenantId": None,
            "aid": None,
            "typeUri": None
        },
        "children": [
            {
                "node": {
                    "uri": "/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d",
                    "parentUri": "/pid_zd/053f3c45413b48bbafacec609d142e57",
                    "projectUri": "/pid_zd/root",
                    "browseName": "refining_workshop",
                    "displayName": "炼化车间",
                    "description": "通用文件夹",
                    "nodeClass": "FOLDER",
                    "extendedAttr": None
                },
                "children": [
                    {
                        "node": {
                            "uri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
                            "parentUri": "/pid_zd/7a9a36aeca1a4998b0aa44f83ec9709d",
                            "projectUri": "/pid_zd/root",
                            "browseName": "catalytic",
                            "displayName": "催化",
                            "description": "通用文件夹",
                            "nodeClass": "FOLDER",
                            "extendedAttr": None
                        },
                        "children": [
                            {
                                "node": {
                                    "uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca",
                                    "parentUri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
                                    "projectUri": "/pid_zd/root",
                                    "browseName": "flow_loop_model_1",
                                    "displayName": "流量单回路实例_1",
                                    "description": "催化车间-流量回路1",
                                    "nodeClass": "INSTANCE",
                                    "extendedAttr": {
                                        "loop_type": "流量"
                                    }
                                },
                                "children": None
                            },
                            {
                                "node": {
                                    "uri": "/pid_zd/e7fd8af67d3d472ba6c8478eeb692af6",
                                    "parentUri": "/pid_zd/1f59615dc9d44b4388e29829f95a49c6",
                                    "projectUri": "/pid_zd/root",
                                    "browseName": "temperature_loop_model_1",
                                    "displayName": "温度单回路实例_1",
                                    "description": "催化车间-温度回路1",
                                    "nodeClass": "INSTANCE",
                                    "extendedAttr": {
                                        "loop_type": "温度"
                                    }
                                },
                                "children": None
                            }
                        ]
                    }
                ]
            }
        ]
    },
    "timestamp": 1764383933727
}


def test_parse_tree():
    """测试树解析"""
    print("\n" + "="*70)
    print("测试1: BFF模型树解析")
    print("="*70)
    
    try:
        tree = BFFModelTreeParser.parse_tree_response(BFF_RESPONSE_EXAMPLE)
        
        if not tree:
            print("✗ 解析失败")
            return False
        
        print("\n✓ 树解析成功")
        print(f"  - 总节点数: {len(tree.all_nodes)}")
        print(f"  - 文件夹数: {len(tree.get_all_folders())}")
        print(f"  - 实例数: {len(tree.get_all_instances())}")
        print(f"  - 树深度: {tree.get_tree_depth()}")
        
        print("\n树结构:")
        tree.print_tree()
        
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {str(e)}")
        return False


def test_find_instances():
    """测试查找实例"""
    print("\n" + "="*70)
    print("测试2: 实例查询")
    print("="*70)
    
    try:
        tree = BFFModelTreeParser.parse_tree_response(BFF_RESPONSE_EXAMPLE)
        
        # 获取所有实例
        all_instances = tree.get_all_instances()
        print(f"\n所有实例数: {len(all_instances)}")
        
        for instance in all_instances:
            breadcrumb = tree.get_breadcrumb_path(instance.uri)
            print(f"\n  📌 {instance.display_name}")
            print(f"     URI: {instance.uri}")
            print(f"     类型: {instance.get_loop_type()}")
            print(f"     路径: {breadcrumb}")
            print(f"     描述: {instance.description}")
        
        # 按回路类型查询
        print("\n按回路类型查询:")
        flow_instances = tree.get_instances_by_type("流量")
        temp_instances = tree.get_instances_by_type("温度")
        
        print(f"  流量回路: {len(flow_instances)}个")
        for inst in flow_instances:
            print(f"    - {inst.display_name}")
        
        print(f"  温度回路: {len(temp_instances)}个")
        for inst in temp_instances:
            print(f"    - {inst.display_name}")
        
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {str(e)}")
        return False


def test_tree_traversal():
    """测试树遍历"""
    print("\n" + "="*70)
    print("测试3: 树遍历")
    print("="*70)
    
    try:
        tree = BFFModelTreeParser.parse_tree_response(BFF_RESPONSE_EXAMPLE)
        
        print("\n深度优先遍历 (DFS):")
        dfs_nodes = []
        tree.traverse_dfs(callback=lambda node: dfs_nodes.append(node.display_name))
        for i, name in enumerate(dfs_nodes, 1):
            print(f"  {i}. {name}")
        
        print("\n广度优先遍历 (BFS):")
        bfs_nodes = tree.traverse_bfs()
        for i, node in enumerate(bfs_nodes, 1):
            print(f"  {i}. {node.display_name}")
        
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {str(e)}")
        return False


def test_tree_analyzer():
    """测试树分析"""
    print("\n" + "="*70)
    print("测试4: 树分析")
    print("="*70)
    
    try:
        tree = BFFModelTreeParser.parse_tree_response(BFF_RESPONSE_EXAMPLE)
        analyzer = ModelTreeAnalyzer(tree)
        
        # 获取统计信息
        stats = analyzer.get_statistics()
        print("\n树统计信息:")
        print(f"  - 总节点数: {stats['total_nodes']}")
        print(f"  - 实例总数: {stats['total_instances']}")
        print(f"  - 文件夹总数: {stats['total_folders']}")
        print(f"  - 树深度: {stats['tree_depth']}")
        print(f"  - 回路类型分布:")
        for type_name, count in stats['instance_types'].items():
            print(f"      {type_name}: {count}个")
        
        # 导出实例列表
        print("\n实例列表导出:")
        instance_list = analyzer.export_instance_list()
        for inst in instance_list:
            print(f"\n  📌 {inst['display_name']}")
            print(f"     浏览名: {inst['browse_name']}")
            print(f"     类型: {inst['loop_type']}")
            print(f"     路径: {inst['breadcrumb_path']}")
            print(f"     深度: {inst['depth']}")
        
        # 获取文件夹层级
        print("\n文件夹层级结构:")
        hierarchy = analyzer.get_folder_hierarchy()
        for folder, children in hierarchy.items():
            print(f"  📁 {folder}")
            for child in children:
                print(f"     - {child}")
        
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {str(e)}")
        return False


def test_tree_navigation():
    """测试树导航"""
    print("\n" + "="*70)
    print("测试5: 树导航")
    print("="*70)
    
    try:
        tree = BFFModelTreeParser.parse_tree_response(BFF_RESPONSE_EXAMPLE)
        
        # 获取第一个实例
        instances = tree.get_all_instances()
        if not instances:
            print("✗ 没有实例可以导航")
            return False
        
        target_instance = instances[0]
        print(f"\n目标实例: {target_instance.display_name} ({target_instance.uri})")
        
        # 获取节点路径
        path = tree.get_node_path(target_instance.uri)
        print(f"\n从根到该实例的路径:")
        if path:
            for i, node in enumerate(path):
                indent = "  " * i
                icon = "📁" if node.is_folder() else "📌"
                print(f"{indent}{icon} {node.display_name}")
        
        # 获取导航路径
        breadcrumb = tree.get_breadcrumb_path(target_instance.uri)
        print(f"\n导航路径: {breadcrumb}")
        
        # 获取父节点
        if target_instance.parent_uri:
            parent = tree.get_node(target_instance.parent_uri)
            if parent:
                print(f"\n父节点: {parent.display_name}")
                siblings = tree.get_children(parent.uri)
                print(f"同级节点: {len(siblings)}个")
                for sibling in siblings:
                    print(f"  - {sibling.display_name}")
        
        return True
        
    except Exception as e:
        print(f"✗ 测试失败: {str(e)}")
        return False


def test_usage_examples():
    """使用示例"""
    print("\n" + "="*70)
    print("使用示例")
    print("="*70)
    
    print("\n【示例1】基本解析:")
    print("""
from core.client.bff_model_tree import BFFModelTreeParser

# 解析BFF响应
tree = BFFModelTreeParser.parse_tree_response(bff_response)

# 获取所有实例
instances = tree.get_all_instances()
for instance in instances:
    print(f"{instance.display_name} - {instance.get_loop_type()}")
    """)
    
    print("\n【示例2】查询实例:")
    print("""
# 按回路类型查询
flow_loops = tree.get_instances_by_type("流量")

# 按名称查询
matching = tree.find_nodes_by_name("温度")

# 获取节点导航路径
breadcrumb = tree.get_breadcrumb_path(instance.uri)
    """)
    
    print("\n【示例3】树遍历:")
    print("""
# 深度优先遍历
tree.traverse_dfs(callback=lambda node: print(node.display_name))

# 广度优先遍历
nodes = tree.traverse_bfs()
    """)
    
    print("\n【示例4】分析树结构:")
    print("""
from core.client.bff_model_tree import ModelTreeAnalyzer

analyzer = ModelTreeAnalyzer(tree)

# 获取统计信息
stats = analyzer.get_statistics()

# 导出实例列表
instance_list = analyzer.export_instance_list()

# 获取文件夹层级
hierarchy = analyzer.get_folder_hierarchy()
    """)


def main():
    """主测试函数"""
    print("\n" + "="*70)
    print("BFF模型树解析和处理模块 - 测试套件")
    print("="*70)
    
    tests = [
        ("BFF模型树解析", test_parse_tree),
        ("实例查询", test_find_instances),
        ("树遍历", test_tree_traversal),
        ("树分析", test_tree_analyzer),
        ("树导航", test_tree_navigation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ {test_name} 执行异常: {str(e)}")
            results.append((test_name, False))
    
    # 显示测试总结
    print("\n" + "="*70)
    print("测试总结")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓" if result else "✗"
        print(f"{status} {test_name}")
    
    print(f"\n总体: {passed}/{total}个测试通过")
    
    if passed == total:
        test_usage_examples()
        print("\n" + "="*70)
        print("🎉 所有测试通过！")
        print("="*70)
        print("\n✨ 模块特点:")
        print("  ✓ 完整的树形结构解析")
        print("  ✓ 灵活的节点查询和导航")
        print("  ✓ 支持多种树遍历方式")
        print("  ✓ 强大的树分析功能")
        print("  ✓ 实例导出和报表生成")
        print()
        return 0
    else:
        print(f"\n⚠️  有{total - passed}个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
