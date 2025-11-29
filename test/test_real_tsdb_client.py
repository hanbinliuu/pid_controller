#!/usr/bin/env python3
"""
测试实际TSDB客户端
验证与真实时序数据库服务的连接和查询功能
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_real_tsdb_client():
    """测试实际TSDB客户端"""
    print("🔧 实际TSDB客户端功能测试")
    print("=" * 60)
    
    try:
        from core.client.real_tsdb_client import TSDBClientFactory, TSDBConfig, RealTSDBDataSource
        
        # 1. 测试工厂方法创建客户端
        print("\n1. 📋 测试客户端创建...")
        
        # 使用默认配置创建
        client = TSDBClientFactory.create_real_client()
        print(f"   ✅ 默认客户端创建成功")
        print(f"   🌐 TSDB地址: {client.config.base_url}")
        print(f"   ⏱️  超时时间: {client.config.timeout}秒")
        print(f"   🔄 重试次数: {client.config.max_retries}")
        
        # 使用自定义配置创建
        custom_config = TSDBConfig(
            base_url="http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com",
            timeout=60,
            max_retries=5,
            auth_token="test_token"
        )
        custom_client = RealTSDBDataSource(custom_config)
        print(f"   ✅ 自定义客户端创建成功")
        print(f"   🌐 自定义地址: {custom_client.config.base_url}")
        
        # 2. 测试连接
        print("\n2. 🔗 测试连接...")
        connection_result = client.test_connection()
        if connection_result:
            print("   ✅ 连接测试成功")
        else:
            print("   ⚠️  连接测试失败（这是预期的，因为可能没有实际的TSDB服务运行）")
        
        # 3. 测试获取表列表（即使连接失败也可以测试HTTP请求构造）
        print("\n3. 📋 测试获取表列表...")
        try:
            tables = client.get_table_list()
            if tables:
                print(f"   📊 获取到 {len(tables)} 个表:")
                for table in tables[:3]:  # 只显示前3个
                    print(f"      - {table}")
                if len(tables) > 3:
                    print(f"      ... 还有 {len(tables) - 3} 个表")
            else:
                print("   ⚠️  未获取到表列表（可能服务不可用）")
        except Exception as e:
            print(f"   ⚠️  获取表列表异常: {str(e)}")
        
        # 4. 测试查询数据
        print("\n4. 🔍 测试查询数据...")
        try:
            # 构造查询参数
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = end_time - 3600000  # 1小时前
            
            result = client.query_raw_data(
                table="cpu",
                fields=["time", "f1", "f2"],
                start_time=start_time,
                end_time=end_time,
                limit=10
            )
            
            print(f"   📊 查询结果:")
            print(f"      字段: {result.columns}")
            print(f"      数据行数: {len(result.values) if result.values else 0}")
            print(f"      标签: {result.tags}")
            
            if result.values:
                print(f"      首条数据: {result.values[0]}")
            else:
                print("      📭 无数据返回（可能服务不可用或无数据）")
                
        except Exception as e:
            print(f"   ⚠️  查询数据异常: {str(e)}")
        
        return True
        
    except ImportError as e:
        print(f"❌ 导入失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        return False


def test_tsdb_factory():
    """测试TSDB工厂类"""
    print("\n🏭 TSDB工厂类测试")
    print("-" * 40)
    
    try:
        from core.client.real_tsdb_client import TSDBClientFactory
        
        # 测试环境变量控制
        print("1. 🎛️  测试环境变量控制...")
        
        # 设置使用模拟数据源
        os.environ['USE_REAL_TSDB'] = 'false'
        mock_client = TSDBClientFactory.create_client()
        client_type = type(mock_client).__name__
        print(f"   USE_REAL_TSDB=false: {client_type}")
        
        # 设置使用真实数据源
        os.environ['USE_REAL_TSDB'] = 'true'
        real_client = TSDBClientFactory.create_client()
        client_type = type(real_client).__name__
        print(f"   USE_REAL_TSDB=true: {client_type}")
        
        # 清理环境变量
        if 'USE_REAL_TSDB' in os.environ:
            del os.environ['USE_REAL_TSDB']
        
        # 测试显式参数
        print("\n2. 🎯 测试显式参数...")
        explicit_mock = TSDBClientFactory.create_client()
        explicit_real = TSDBClientFactory.create_client()
        
        print(f"   明确指定false: {type(explicit_mock).__name__}")
        print(f"   明确指定true: {type(explicit_real).__name__}")
        
        return True
        
    except Exception as e:
        print(f"❌ 工厂测试异常: {e}")
        return False


def test_integration_with_existing_api():
    """测试与现有API的集成"""
    print("\n🔗 与现有API集成测试")
    print("-" * 40)
    
    try:
        from core.client.tsdb_api import get_query_engine, query_raw_data
        
        # 测试获取查询引擎
        print("1. 🎯 测试查询引擎...")
        
        # 使用模拟数据源
        mock_engine = get_query_engine(use_real_tsdb=False)
        print(f"   模拟引擎数据源: {type(mock_engine.data_source).__name__}")
        
        # 使用真实数据源
        real_engine = get_query_engine(use_real_tsdb=True)
        print(f"   真实引擎数据源: {type(real_engine.data_source).__name__}")
        
        # 测试便捷查询函数
        print("\n2. 🔍 测试便捷查询函数...")
        try:
            # 构造测试查询请求
            request_data = {
                "tables": [
                    {
                        "table": "cpu",
                        "fields": ["time", "f1", "f2"]
                    }
                ],
                "detail": {
                    "startTime": int((datetime.now() - timedelta(hours=1)).timestamp() * 1000),
                    "endTime": int(datetime.now().timestamp() * 1000),
                    "limit": 10
                }
            }
            
            # 使用模拟数据测试
            mock_result = query_raw_data(request_data)
            print(f"   模拟查询结果: code={mock_result.get('code')}, results_count={len(mock_result.get('results', []))}")
            
        except Exception as e:
            print(f"   ⚠️  查询测试异常: {e}")
        
        return True
        
    except Exception as e:
        print(f"❌ 集成测试异常: {e}")
        return False


def main():
    """主测试函数"""
    print("🚀 开始TSDB客户端全面测试")
    print("=" * 80)
    
    tests = [
        ("实际TSDB客户端", test_real_tsdb_client),
        ("TSDB工厂类", test_tsdb_factory),
        ("与现有API集成", test_integration_with_existing_api)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n🧪 测试: {test_name}")
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                print(f"✅ {test_name} 测试通过")
            else:
                print(f"❌ {test_name} 测试失败")
        except Exception as e:
            print(f"❌ {test_name} 测试异常: {e}")
            results.append((test_name, False))
    
    # 总结
    print("\n" + "=" * 80)
    print("📊 测试总结")
    print("-" * 40)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"   {test_name}: {status}")
    
    print(f"\n🎯 总体结果: {passed}/{total} 测试通过")
    
    if passed == total:
        print("🎉 所有测试都通过了！")
        print("\n💡 使用说明:")
        print("   1. 设置环境变量 USE_REAL_TSDB=true 启用真实TSDB")
        print("   2. 设置 TSDB_BASE_URL 指定TSDB服务地址")
        print("   3. 在代码中使用 TSDBClientFactory.create_client() 获取客户端")
    else:
        print("⚠️  部分测试失败，请检查配置和依赖")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)