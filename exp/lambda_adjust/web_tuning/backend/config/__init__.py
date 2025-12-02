"""
配置管理模块
根据环境变量自动加载对应的配置
"""

import os
from typing import Dict, Any

# 默认使用生产环境配置
ENV = os.getenv('WEB_TUNING_ENV', 'production')

# 根据环境加载配置
if ENV == 'development' or ENV == 'dev':
    from .development import *
    print("🧪 [配置] 加载开发环境配置 - 仿真模式")
elif ENV == 'production' or ENV == 'prod':
    from .production import *
    print("🏭 [配置] 加载生产环境配置 - 生产模式")
else:
    # 默认使用生产环境
    from .production import *
    print(f"⚠️  [配置] 未知环境 '{ENV}'，使用生产环境配置")


def get_opcua_config() -> Dict[str, Any]:
    """获取 OPC UA 配置"""
    return OPCUA_CONFIG


def get_mode() -> str:
    """获取运行模式"""
    return OPCUA_CONFIG.get('mode', 'production')


def is_simulation() -> bool:
    """是否为仿真模式"""
    return get_mode() == 'simulation'


def is_production() -> bool:
    """是否为生产模式"""
    return get_mode() == 'production'


# 打印当前配置信息
def print_config_info():
    """打印当前配置信息"""
    print("\n" + "="*80)
    print("📋 Web Tuning 系统配置信息")
    print("="*80)
    print(f"环境: {ENV}")
    print(f"模式: {OPCUA_CONFIG.get('mode', 'unknown')}")
    print(f"OPC UA 服务器: {OPCUA_CONFIG.get('endpoint_url', 'unknown')}")
    print(f"描述: {OPCUA_CONFIG.get('description', 'unknown')}")
    
    if is_simulation():
        print("\n⚠️  警告: 当前运行在仿真模式，仅用于开发测试！")
        print("   生产环境请设置环境变量: export WEB_TUNING_ENV=production")
    else:
        print("\n✅ 当前运行在生产模式，连接到真实工业系统")
        print("   如需测试，请设置环境变量: export WEB_TUNING_ENV=development")
    
    print("="*80 + "\n")
