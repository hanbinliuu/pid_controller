#!/usr/bin/env python3
"""
全局配置管理模块
从环境变量读取配置，支持默认值
"""

import os
from typing import Optional


class Config:
    """全局配置类"""
    
    # ==================== 日志配置 ====================
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT: str = os.getenv(
        'LOG_FORMAT',
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # ==================== TSDB配置 ====================
    USE_REAL_TSDB: bool = os.getenv('USE_REAL_TSDB', 'false').lower() == 'true'
    TSDB_BASE_URL: str = os.getenv(
        'TSDB_BASE_URL',
        'http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com'
    )
    TSDB_TIMEOUT: int = int(os.getenv('TSDB_TIMEOUT', '30'))
    TSDB_MAX_RETRIES: int = int(os.getenv('TSDB_MAX_RETRIES', '3'))
    TSDB_AUTH_TOKEN: Optional[str] = os.getenv('TSDB_AUTH_TOKEN', None)
    DEFAULT_TSDB_DATABASE: str = os.getenv('DEFAULT_TSDB_DATABASE', 'platform')
    
    # ==================== 模拟数据配置 ====================
    SIMULATION_DATA_DIR: str = os.getenv('SIMULATION_DATA_DIR', 'data/simulated')
    
    # ==================== 工作流代理配置 ====================
    WORKFLOW_BASE_URL: str = os.getenv('WORKFLOW_BASE_URL', 'http://192.168.202.172')
    WORKFLOW_TOKEN: str = os.getenv('WORKFLOW_TOKEN', 'app-ZJxenSh1D9uFCqnGO7Dt917p')
    WORKFLOW_TIMEOUT: int = int(os.getenv('WORKFLOW_TIMEOUT', '120'))
    WORKFLOW_CONNECT_TIMEOUT: int = int(os.getenv('WORKFLOW_CONNECT_TIMEOUT', '30'))
    WORKFLOW_READ_TIMEOUT: int = int(os.getenv('WORKFLOW_READ_TIMEOUT', '300'))
    HEALTH_CHECK_TIMEOUT: int = int(os.getenv('HEALTH_CHECK_TIMEOUT', '10'))
    
    # ==================== BFF模型查询配置 ====================
    BFF_MODEL_BASE_URL: str = os.getenv(
        'BFF_MODEL_BASE_URL',
        'http://bff-model-product-infra-system.sit-cloud.ieccloud.hollicube.com'
    )
    BFF_MODEL_TIMEOUT: int = int(os.getenv('BFF_MODEL_TIMEOUT', '30'))
    BFF_MODEL_PROJECT_PATH: str = os.getenv(
        'BFF_MODEL_PROJECT_PATH',
        '/pid_zd/ce716ffbade5426e8faf18467d1d5a83'
    )
    BFF_MODEL_POINT_PATH: str = os.getenv(
        'BFF_MODEL_POINT_PATH',
        '/ZTCS'
    )
    
    @classmethod
    def get_bff_model_config(cls) -> dict:
        """
        获取BFF模型查询相关配置
        
        Returns:
            包含BFF配置的字典
        """
        return {
            'base_url': cls.BFF_MODEL_BASE_URL,
            'timeout': cls.BFF_MODEL_TIMEOUT,
            'project_path': cls.BFF_MODEL_PROJECT_PATH
            , 'point_path': cls.BFF_MODEL_POINT_PATH
        }
    
    @classmethod
    def get_tsdb_config(cls) -> dict:
        """
        获取TSDB相关配置
        
        Returns:
            包含TSDB配置的字典
        """
        return {
            'base_url': cls.TSDB_BASE_URL,
            'timeout': cls.TSDB_TIMEOUT,
            'max_retries': cls.TSDB_MAX_RETRIES,
            'auth_token': cls.TSDB_AUTH_TOKEN,
            'database': cls.DEFAULT_TSDB_DATABASE
        }
    
    @classmethod
    def get_workflow_config(cls) -> dict:
        """
        获取工作流相关配置
        
        Returns:
            包含工作流配置的字典
        """
        return {
            'base_url': cls.WORKFLOW_BASE_URL,
            'token': cls.WORKFLOW_TOKEN,
            'timeout': cls.WORKFLOW_TIMEOUT,
            'connect_timeout': cls.WORKFLOW_CONNECT_TIMEOUT,
            'read_timeout': cls.WORKFLOW_READ_TIMEOUT
        }
    
    @classmethod
    def display_config(cls):
        """打印当前配置（隐藏敏感信息）"""
        print("=" * 60)
        print("当前配置:")
        print("=" * 60)
        print(f"LOG_LEVEL: {cls.LOG_LEVEL}")
        print(f"USE_REAL_TSDB: {cls.USE_REAL_TSDB}")
        print(f"TSDB_BASE_URL: {cls.TSDB_BASE_URL}")
        print(f"BFF_MODEL_BASE_URL: {cls.BFF_MODEL_BASE_URL}")
        print(f"BFF_MODEL_PROJECT_PATH: {cls.BFF_MODEL_PROJECT_PATH}")
        print(f"WORKFLOW_BASE_URL: {cls.WORKFLOW_BASE_URL}")
        print("=" * 60)


# 创建全局配置实例
config = Config()


if __name__ == "__main__":
    # 测试配置加载
    Config.display_config()
    
    print("\nBFF模型查询配置:")
    print(Config.get_bff_model_config())
    
    print("\nTSDB配置:")
    print(Config.get_tsdb_config())
    
    print("\n工作流配置:")
    print(Config.get_workflow_config())
