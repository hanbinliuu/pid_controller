#!/usr/bin/env python3
"""
全局配置管理模块
从 application.properties 文件读取配置，支持环境变量覆盖
"""

import os
from typing import Optional, Dict, Any
from pathlib import Path


class PropertiesLoader:
    """配置文件加载器"""
    
    @staticmethod
    def load_properties(file_path: str) -> Dict[str, str]:
        """
        加载 properties 文件
        
        Args:
            file_path: 配置文件路径
            
        Returns:
            配置字典
        """
        properties = {}
        
        if not os.path.exists(file_path):
            return properties
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # 跳过注释和空行
                    if not line or line.startswith('#'):
                        continue
                    
                    # 解析 key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        properties[key.strip()] = value.strip()
        except Exception as e:
            print(f"警告: 加载配置文件失败 {file_path}: {e}")
        
        return properties


# 加载配置文件（模块级别）
_project_root = Path(__file__).parent.parent

# 优先从 /app/config 目录加载配置（Docker环境），其次从项目config目录加载
_config_paths = [
    Path('/app/config/application.properties'),  # Docker环境配置路径
    _project_root / 'config' / 'application.properties'  # 本地开发环境配置路径
]

_properties = {}
for _config_file in _config_paths:
    if _config_file.exists():
        _properties = PropertiesLoader.load_properties(str(_config_file))
        # print(f"成功加载配置文件: {_config_file}")
        break
else:
    print("警告: 未找到配置文件，将使用默认配置")


def _get_config(key: str, default: Any = None, value_type: type = str) -> Any:
    """
    获取配置值，优先从环境变量读取，其次从 properties 文件读取
    
    Args:
        key: 配置键
        default: 默认值
        value_type: 值类型（str, int, bool）
        
    Returns:
        配置值
    """
    # 1. 优先从环境变量获取
    env_key = key.upper().replace('.', '_')
    env_value = os.getenv(env_key)
    
    if env_value is not None:
        value = env_value
    else:
        # 2. 从 properties 文件获取
        value = _properties.get(key, default)
    
    # 类型转换
    if value is None:
        return default
    
    if value_type == bool:
        return str(value).lower() in ('true', '1', 'yes')
    elif value_type == int:
        return int(value)
    elif value_type == float:
        return float(value)
    else:
        return str(value)


class Config:
    """全局配置类"""
    # ==================== 日志配置 ====================
    LOG_LEVEL: str = _get_config('log.level', 'INFO')
    LOG_FORMAT: str = _get_config(
        'log.format',
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    SERVER_PORT: int = _get_config('server.port', '8001',int)
    
    # ==================== TSDB配置 ====================
    TSDB_BASE_URL: str = _get_config(
        'tsdb.base_url',
        'http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com'
    )
    TSDB_TIMEOUT: int = _get_config('tsdb.timeout', '30', int)
    TSDB_MAX_RETRIES: int = _get_config('tsdb.max_retries', '3', int)
    TSDB_AUTH_TOKEN: Optional[str] = _get_config('tsdb.auth_token', None)
    DEFAULT_TSDB_DATABASE: str = _get_config('tsdb.database', 'platform')


    # ==================== 模拟数据配置 ====================
    SIMULATION_DATA_DIR: str = _get_config('simulation.data_dir', 'data/simulated')
    
    # ==================== 工作流代理配置 ====================
    WORKFLOW_BASE_URL: str = _get_config('workflow.base_url', 'http://192.168.202.172')
    WORKFLOW_TOKEN: str = _get_config('workflow.token', 'app-ZJxenSh1D9uFCqnGO7Dt917p')
    WORKFLOW_TIMEOUT: int = _get_config('workflow.timeout', '120', int)
    WORKFLOW_CONNECT_TIMEOUT: int = _get_config('workflow.connect_timeout', '30', int)
    WORKFLOW_READ_TIMEOUT: int = _get_config('workflow.read_timeout', '300', int)
    HEALTH_CHECK_TIMEOUT: int = _get_config('workflow.health_check_timeout', '10', int)
    
    # ==================== BFF模型查询配置 ====================
    BFF_MODEL_BASE_URL: str = _get_config(
        'bff.model.base_url',
        'http://bff-model-product-infra-system.sit-cloud.ieccloud.hollicube.com'
    )
    BFF_MODEL_TIMEOUT: int = _get_config('bff.model.timeout', '30', int)
    # 默认回路URI
    BFF_MODEL_DEFULT_LOOP_URI: str = _get_config(
        'bff.model.loop_uri',
        '/pid_zd/0b521c82a96d4107a564e4c2678bdeca'
    )
    # 信息模型测点属性路径名称
    BFF_MODEL_POINT_PATH: str = _get_config(
        'bff.model.point_path',
        '/loop_state_parameters'
    )
    # BFF回路模型URI（根节点URI）
    BFF_MODEL_ROOT_URI: str = _get_config(
        'bff.model.root_uri',
        '/pid_zd/053f3c45413b48bbafacec609d142e57'
    )
    # BFF回路模型URI（通用装置类型类型）
    BFF_MODEL_LOOP_MODEL_URI: str = _get_config(
        'bff.model.loop_model_uri',
        '/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243'
    )
    # BFF装置模型URI（通用文件夹类型）
    BFF_MODEL_DEVICE_MODEL_URI: str = _get_config(
        'bff.model.device_model_uri',
        '/system/401'
    )

    # ==================== 模型核心建模配置 ====================
    MODEL_CORE_BASE_URL: str = _get_config(
        'model.core.base_url',
        'http://model-core-modelling-model-product-infra-system.sit-cloud.ieccloud.hollicube.com'
    )
    MODEL_CORE_TIMEOUT: int = _get_config('model.core.timeout', '30', int)
    


    # ==================== PID 数据文件导入配置 ====================
    PID_DATA_FILE_DIR: str = _get_config('pid.data.import.storage.dir', 'data/pid_data')
    PID_DATA_DB_BASE_URL = _get_config('pid.data.import.db.base_url', 'http://tsdb-store-svc:8080')
    PID_DATA_DB_NAME = _get_config('pid.data.import.db.name', 'platform')
    
    # PID控制字段与模型browse_name名称映射关系
    @classmethod
    def get_pid_point_map(cls) -> Dict[str, str]:
        """
        获取PID控制字段映射关系
        
        Returns:
            PID字段映射字典，如 {'mv': 'MV', 'pv': 'PV', ...}
        """
        return {
            'mv': _get_config('bff.model.pid_point.mv', 'MV'),
            'pv': _get_config('bff.model.pid_point.pv', 'PV'),
            'sv': _get_config('bff.model.pid_point.sv', 'SV'),
            'pb': _get_config('bff.model.pid_point.pb', 'PB'),
            'ti': _get_config('bff.model.pid_point.ti', 'TI'),
            'td': _get_config('bff.model.pid_point.td', 'TD'),
            'auto': _get_config('bff.model.pid_point.auto', 'AUTO')
        }
    
    # ==================== 定时任务配置 ====================
    # 回路性能计算任务配置
    TASK_LOOP_PERFORMANCE_ENABLE: bool = _get_config(
        'task.loop_performance.enable',
        True,
        bool
    )
    TASK_LOOP_PERFORMANCE_CRON: str = _get_config(
        'task.loop_performance.cron',
        '0 * * * *'  # 默认每小时执行
    )
    TASK_LOOP_PERFORMANCE_MAX_WORKERS: int = _get_config(
        'task.loop_performance.max_workers',
        5,
        int
    )
    
    # 写入性能评估结果配置
    TASK_LOOP_PERFORMANCE_PERSIST_ENABLE: bool = _get_config(
        'task.loop_performance.persist.enable',
        True,
        bool
    )
    TASK_LOOP_PERFORMANCE_PERSIST_MIN_SCORE: float = _get_config(
        'task.loop_performance.persist.min_score',
        0.0,
        float
    )
    
    # 模型树加载任务配置
    TASK_LOAD_MODEL_TREE_ENABLE: bool = _get_config(
        'task.load_model_tree.enable',
        True,
        bool
    )
    TASK_LOAD_MODEL_TREE_CRON: str = _get_config(
        'task.load_model_tree.cron',
        '*/10 * * * *'  # 默认每天00:00执行
    )
    
    # 装置性能统计任务配置
    TASK_DEVICE_STATS_ENABLE: bool = _get_config(
        'task.device_stats.enable',
        True,
        bool
    )
    TASK_DEVICE_STATS_CRON: str = _get_config(
        'task.device_stats.cron',
        '0 1 * * *'  # 默认每天01:00执行
    )
    TASK_DEVICE_STATS_MAX_WORKERS: int = _get_config(
        'task.device_stats.max_workers',
        3,
        int
    )
    
    # ==================== 数据库配置 ====================
    # 数据库连接配置
    DB_HOST: str = _get_config('db.host', '192.168.201.113')
    DB_PORT: int = _get_config('db.port', '15432', int)
    DB_USER: str = _get_config('db.user', 'postgres')
    DB_PASSWORD: str = _get_config('db.password', 'Postgres#7556')
    DB_NAME: str = _get_config('db.name', 'pid_controller')
    
    # 数据库连接URL格式：
    # PostgreSQL: postgresql://user:password@host:port/dbname
    # SQLite: sqlite:///./database.db
    DATABASE_URL: str = _get_config(
        'db.url',
        f'postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
    )
    # 是否打印SQL语句（调试用）
    SQL_ECHO: bool = _get_config('db.sql.echo', 'False', bool)
    # 数据库连接池大小
    DB_POOL_SIZE: int = _get_config('db.pool_size', '10', int)
    # 数据库连接池最大溢出连接数
    DB_MAX_OVERFLOW: int = _get_config('db.max_overflow', '20', int)
    
    # ==================== 回路优化阈值配置 ====================
    # 性能分数阈值（低于此值认为需要优化）
    LOOP_PERFORMANCE_THRESHOLD: float = _get_config('loop.performance.threshold', '80.0', float)
    # 稳定率阈值（低于此值认为需要优化）
    LOOP_STABILITY_THRESHOLD: float = _get_config('loop.stability.threshold', '90.0', float)
    # 自控率阈值（高于此值认为是自控回路）
    LOOP_AUTO_CONTROL_THRESHOLD: float = _get_config('loop.auto_control.threshold', '0.8', float)
    # 平稳率阈值（高于此值认为是平稳回路）
    LOOP_STABLE_THRESHOLD: float = _get_config('loop.stable.threshold', '0.8', float)

    # ==================== 动态参数配置默认值 ====================
    # 虚拟网关设备ID
    DEFAULT_VIRTUAL_GATEWAY_DEVICE_ID: str = _get_config(
        'default.resource.space',
        ''
    )

    # 产品（设备模型）ID
    DEFAULT_PRODUCT_MODEL_ID: str = _get_config(
        'default.product.model.id',
        ''
    )
    # 默认资源空间
    DEFAULT_RESOURCE_SPACE: str = _get_config(
        'default.resource.space',
        ''
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
            'loop_uri': cls.BFF_MODEL_DEFULT_LOOP_URI,
            'point_path': cls.BFF_MODEL_POINT_PATH
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
    def get_model_core_config(cls) -> dict:
        """
        获取模型核心建模相关配置
        
        Returns:
            包含模型核心配置的字典
        """
        return {
            'base_url': cls.MODEL_CORE_BASE_URL,
            'timeout': cls.MODEL_CORE_TIMEOUT
        }
    
    @classmethod
    def display_config(cls):
        """打印当前配置（隐藏敏感信息）"""
        print("=" * 60)
        print("当前配置:")
        print("=" * 60)
        print(f"LOG_LEVEL: {cls.LOG_LEVEL}")
        print(f"TSDB_BASE_URL: {cls.TSDB_BASE_URL}")
        print(f"BFF_MODEL_BASE_URL: {cls.BFF_MODEL_BASE_URL}")
        print(f"BFF_MODEL_LOOP_URI: {cls.BFF_MODEL_DEFULT_LOOP_URI}")
        print(f"MODEL_CORE_BASE_URL: {cls.MODEL_CORE_BASE_URL}")
        print(f"WORKFLOW_BASE_URL: {cls.WORKFLOW_BASE_URL}")
        print("=" * 60)


# 创建全局配置实例
# config = Config()


if __name__ == "__main__":
    # 测试配置加载
    Config.display_config()
    
    print("\nBFF模型查询配置:")
    print(Config.get_bff_model_config())
    
    print("\nTSDB配置:")
    print(Config.get_tsdb_config())
    
    print("\n工作流配置:")
    print(Config.get_workflow_config())
    
    print("\n模型核心配置:")
    print(Config.get_model_core_config())
