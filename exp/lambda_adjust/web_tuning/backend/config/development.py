"""
开发环境配置
用于本地开发和测试，连接到仿真 OPC UA Server
"""

# OPC UA 配置
OPCUA_CONFIG = {
    # 运行模式
    "mode": "simulation",  # 仿真模式
    
    # 服务器地址（本地仿真服务器）
    "endpoint_url": "opc.tcp://localhost:4840",
    
    # 认证信息（仿真服务器通常不需要）
    "username": None,
    "password": None,
    
    # 描述
    "description": "开发环境 - 连接到本地仿真 OPC UA Server",
    "environment": "development"
}

# 回路配置示例（仿真环境）
LOOP_CONFIG_EXAMPLE = {
    "loop_id": "sim_loop_001",
    "name": "仿真温度控制回路",
    "description": "用于测试的仿真回路",
    
    # OPC UA 节点配置
    "opcua_config": {
        "pv_node_id": "ns=2;s=Temperature.PV",      # 过程变量
        "sv_node_id": "ns=2;s=Temperature.SP",      # 设定值
        "mv_node_id": "ns=2;s=Temperature.MV",      # 控制输出
        "pid_pb_node_id": "ns=2;s=PID.Pb",          # PID 比例带
        "pid_ti_node_id": "ns=2;s=PID.Ti",          # PID 积分时间
        "pid_td_node_id": "ns=2;s=PID.Td"           # PID 微分时间
    },
    
    # 采样配置
    "sampling_interval": 2.0,  # 采样间隔（秒）
    
    # 自动整定配置
    "auto_tuning_enabled": True,
    "tuning_method": "lambda"
}

# 日志配置
LOGGING_CONFIG = {
    "level": "DEBUG",  # 开发环境使用 DEBUG 级别
    "format": "%(asctime)s - [DEV] - %(name)s - %(levelname)s - %(message)s"
}

# 数据库配置（如果需要）
DATABASE_CONFIG = {
    "type": "sqlite",
    "path": "./data/dev_database.db"
}

# 其他开发配置
DEBUG = True
TESTING = True
