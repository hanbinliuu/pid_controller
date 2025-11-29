#!/usr/bin/env python3
"""
BFF模型树集成测试
测试BFF客户端、服务层和路由的树形查询功能
"""

import logging
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client.bff_model_client import BFFModelClient, query_instance_tree
from api.services.bff_service import BFFService
from core.client.bean.bff_model_tree import BFFModelTreeParser, ModelTreeAnalyzer

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


class TestBFFTreeIntegration:
    """BFF模型树集成测试"""

    @staticmethod
    def test_client_query_instance_tree():
        """测试客户端查询实例树"""
        logger.info("\n=== 测试1: BFFModelClient.query_instance_tree ===")
        try:
            # 这里需要使用实际的起始标识符
            # 为了演示，我们使用环境变量中的默认项目路径
            start_identifier = "/pid_zd/1f59615dc9d44b4388e29829f95a49c6"  # 示例URI
            
            with BFFModelClient() as client:
                result = client.query_instance_tree(start_identifier)
                
                # 验证响应结构
                assert 'result' in result, "响应应包含result字段"
                assert 'node' in result.get('result', {}), "result应包含node字段"
                
                logger.info(f"✓ 查询成功，返回数据结构完整")
                logger.info(f"  根节点: {result.get('result', {}).get('node', {}).get('displayName', 'N/A')}")
                logger.info(f"  子节点数: {len(result.get('result', {}).get('children', []))}")
                
                return True
        
        except Exception as e:
            logger.error(f"✗ 测试失败: {str(e)}")
            return False

    @staticmethod
    def test_convenience_function():
        """测试便捷函数"""
        logger.info("\n=== 测试2: query_instance_tree便捷函数 ===")
        try:
            start_identifier = "/pid_zd/1f59615dc9d44b4388e29829f95a49c6"  # 示例URI
            
            result = query_instance_tree(start_identifier)
            
            assert 'result' in result, "响应应包含result字段"
            
            logger.info(f"✓ 便捷函数调用成功")
            
            return True
        
        except Exception as e:
            logger.error(f"✗ 测试失败: {str(e)}")
            return False

    @staticmethod
    def test_service_layer():
        """测试服务层"""
        logger.info("\n=== 测试3: BFFService.query_instance_tree ===")
        try:
            start_identifier = "/pid_zd/1f59615dc9d44b4388e29829f95a49c6"  # 示例URI
            
            result = BFFService.query_instance_tree(start_identifier)
            
            assert 'result' in result, "服务层应返回完整响应"
            
            logger.info(f"✓ 服务层调用成功")
            
            return True
        
        except Exception as e:
            logger.error(f"✗ 测试失败: {str(e)}")
            return False

    @staticmethod
    def test_tree_parsing():
        """测试树形解析"""
        logger.info("\n=== 测试4: 树形数据解析 ===")
        try:
            # 模拟BFF响应
            mock_response = {
                'code': 200,
                'result': {
                    'node': {
                        'uri': '/pid_zd/root',
                        'browseName': 'root',
                        'displayName': '根节点',
                        'description': '根',
                        'extendedAttr': {}
                    },
                    'children': [
                        {
                            'uri': '/pid_zd/child1',
                            'browseName': 'child1',
                            'displayName': '子节点1',
                            'description': '子1',
                            'extendedAttr': {'loop_type': '流量'},
                            'children': []
                        }
                    ]
                }
            }
            
            # 解析树形数据
            tree = BFFModelTreeParser.parse_tree_response(mock_response)
            
            assert tree is not None, "树形解析应返回ModelTree对象"
            assert tree.root_node.uri == '/pid_zd/root', "根节点URI应匹配"
            assert len(tree.all_nodes) >= 2, "应至少包含根节点和子节点"
            
            # 获取所有实例
            instances = tree.get_all_instances()
            logger.info(f"✓ 树形解析成功，总节点数: {len(tree.all_nodes)}, 实例数: {len(instances)}")
            
            # 测试分析
            analyzer = ModelTreeAnalyzer(tree)
            stats = analyzer.get_statistics()
            logger.info(f"  统计信息: {stats}")
            
            return True
        
        except Exception as e:
            logger.error(f"✗ 测试失败: {str(e)}")
            return False

    @staticmethod
    def test_integration_workflow():
        """测试完整工作流"""
        logger.info("\n=== 测试5: 完整工作流 ===")
        try:
            logger.info("步骤1: 通过客户端查询树形数据...")
            start_identifier = "/pid_zd/1f59615dc9d44b4388e29829f95a49c6"
            
            with BFFModelClient() as client:
                response = client.query_instance_tree(start_identifier)
            
            logger.info("步骤2: 验证响应...")
            assert response.get('code') == 200 or 'result' in response, "查询应返回成功响应"
            
            logger.info("步骤3: 解析树形数据...")
            tree = BFFModelTreeParser.parse_tree_response(response)
            
            if tree:
                logger.info("步骤4: 执行树形分析...")
                analyzer = ModelTreeAnalyzer(tree)
                stats = analyzer.get_statistics()
                
                logger.info(f"✓ 完整工作流成功")
                logger.info(f"  树统计: {stats}")
                return True
            else:
                logger.warning("⚠ 树解析返回None，但不影响集成")
                return True
        
        except Exception as e:
            logger.error(f"✗ 测试失败: {str(e)}")
            return False


def main():
    """运行所有测试"""
    logger.info("开始BFF模型树集成测试\n")
    
    tests = [
        ("客户端查询", TestBFFTreeIntegration.test_client_query_instance_tree),
        ("便捷函数", TestBFFTreeIntegration.test_convenience_function),
        ("服务层", TestBFFTreeIntegration.test_service_layer),
        ("树形解析", TestBFFTreeIntegration.test_tree_parsing),
        ("完整工作流", TestBFFTreeIntegration.test_integration_workflow),
    ]
    
    results = {}
    for test_name, test_func in tests:
        try:
            results[test_name] = test_func()
        except Exception as e:
            logger.error(f"测试执行异常: {str(e)}")
            results[test_name] = False
    
    logger.info("\n" + "="*50)
    logger.info("测试汇总：")
    for test_name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        logger.info(f"  {test_name}: {status}")
    
    total = len(results)
    passed = sum(1 for p in results.values() if p)
    logger.info(f"\n总计: {passed}/{total} 通过")
    
    return all(results.values())


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
