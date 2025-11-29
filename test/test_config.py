#!/usr/bin/env python3
"""
配置测试和演示脚本
展示如何使用环境变量配置BFF客户端
"""

import os
import sys

# 模拟设置环境变量（仅用于演示）
# 实际使用时应该在 .env 文件中配置
os.environ['BFF_MODEL_BASE_URL'] = 'http://bff-model-product-infra-system.sit-cloud.ieccloud.hollicube.com'
os.environ['BFF_MODEL_TIMEOUT'] = '30'
os.environ['BFF_MODEL_PROJECT_PATH'] = '/pid_zd/ce716ffbade5426e8faf18467d1d5a83'

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.config import Config
from core.client.bean.bff_model_client import BFFModelClient, query_pid_values


def test_config_loading():
    """测试配置加载"""
    print("=" * 70)
    print("测试1: 配置加载")
    print("=" * 70)
    
    Config.display_config()
    
    print("\n获取BFF模型配置:")
    bff_config = Config.get_bff_model_config()
    for key, value in bff_config.items():
        print(f"  {key}: {value}")


def test_default_client():
    """测试使用默认配置创建客户端"""
    print("\n" + "=" * 70)
    print("测试2: 使用默认配置（从环境变量）")
    print("=" * 70)
    
    client = BFFModelClient()
    
    print(f"\n客户端配置:")
    print(f"  Base URL: {client.base_url}")
    print(f"  Project Path: {client.device_uri}")
    print(f"  Timeout: {client.timeout}s")
    
    # 生成几个示例路径
    print(f"\n生成的路径示例:")
    for key in ['mv', 'pv', 'sv']:
        if key in client.DEFAULT_PID_POINT_MAP:
            full_path = client.device_uri + client.DEFAULT_PID_POINT_MAP[key]
            print(f"  {key.upper()}: {full_path}")


def test_custom_client():
    """测试使用自定义配置创建客户端"""
    print("\n" + "=" * 70)
    print("测试3: 使用自定义配置（覆盖环境变量）")
    print("=" * 70)
    
    custom_project_path = "/pid_zd/custom_project_12345"
    client = BFFModelClient(
        device_uri=custom_project_path,
        timeout=60
    )
    
    print(f"\n客户端配置:")
    print(f"  Base URL: {client.base_url} (默认)")
    print(f"  Project Path: {client.device_uri} (自定义)")
    print(f"  Timeout: {client.timeout}s (自定义)")
    
    # 生成几个示例路径
    print(f"\n生成的路径示例:")
    mv_path = client.device_uri + client.DEFAULT_PID_POINT_MAP['mv']
    print(f"  MV: {mv_path}")


def test_environment_variable_override():
    """测试环境变量优先级"""
    print("\n" + "=" * 70)
    print("测试4: 环境变量优先级测试")
    print("=" * 70)
    
    # 保存原始环境变量
    original_project_path = os.environ.get('BFF_MODEL_PROJECT_PATH')
    
    # 临时修改环境变量
    new_path = "/pid_zd/test_override_path"
    os.environ['BFF_MODEL_PROJECT_PATH'] = new_path
    
    # 重新导入配置（在实际应用中不需要这样做，因为配置在启动时加载一次）
    from core.config import Config as ConfigReload
    
    print(f"\n环境变量 BFF_MODEL_PROJECT_PATH: {new_path}")
    print(f"Config.BFF_MODEL_PROJECT_PATH: {ConfigReload.BFF_MODEL_PROJECT_PATH}")
    
    # 恢复原始环境变量
    if original_project_path:
        os.environ['BFF_MODEL_PROJECT_PATH'] = original_project_path
    
    print("\n注意: 在实际应用中，配置在程序启动时加载一次")
    print("      运行时修改环境变量不会影响已加载的配置")


def show_usage_examples():
    """显示使用示例"""
    print("\n" + "=" * 70)
    print("使用示例代码")
    print("=" * 70)
    
    example_code = '''
# 方式1: 使用默认配置（从环境变量）
from core.client.bff_model_client import BFFModelClient

client = BFFModelClient()
response = client.query_common_fields()

# 方式2: 覆盖部分配置
client = BFFModelClient(
    project_path="/pid_zd/custom_project_id",
    timeout=60
)

# 方式3: 使用便捷函数（推荐）
from core.client.bff_model_client import query_pid_values

# 使用默认配置
values = query_pid_values()

# 覆盖项目路径
values = query_pid_values(project_path="/pid_zd/another_project")

# 方式4: 配置环境变量（推荐用于生产环境）
# 在 .env 文件中设置:
# BFF_MODEL_BASE_URL=http://your-bff-server.com
# BFF_MODEL_TIMEOUT=30
# BFF_MODEL_PROJECT_PATH=/pid_zd/your_project_id
'''
    
    print(example_code)


def show_env_file_template():
    """显示 .env 文件模板"""
    print("\n" + "=" * 70)
    print(".env 文件配置模板")
    print("=" * 70)
    
    env_template = '''
# 创建 .env 文件并添加以下配置:

# BFF模型查询配置
BFF_MODEL_BASE_URL=http://bff-model-product-infra-system.sit-cloud.ieccloud.hollicube.com
BFF_MODEL_TIMEOUT=30
BFF_MODEL_PROJECT_PATH=/pid_zd/ce716ffbade5426e8faf18467d1d5a83

# 注意:
# 1. .env 文件不应该提交到 Git（已在 .gitignore 中）
# 2. 可以参考 .env.example 文件
# 3. 不同环境可以使用不同的 .env 文件
'''
    
    print(env_template)


if __name__ == "__main__":
    print("\n" + "🚀 " * 25)
    print("BFF模型查询客户端 - 配置管理演示")
    print("🚀 " * 25 + "\n")
    
    # 运行所有测试
    test_config_loading()
    test_default_client()
    test_custom_client()
    test_environment_variable_override()
    show_usage_examples()
    show_env_file_template()
    
    print("\n" + "=" * 70)
    print("✅ 所有测试完成!")
    print("=" * 70 + "\n")
