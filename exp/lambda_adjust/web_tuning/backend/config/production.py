"""
生产环境配置
用于实际工业现场，连接到真实的 OPC UA Server（如西门子、施耐德等）
"""

# OPC UA 配置
OPCUA_CONFIG = {
    # 运行模式
    "mode": "production",  # 生产模式
    
    # 服务器地址（真实工业 OPC UA Server）
    # 示例：西门子 PLC 的 OPC UA Server
    "endpoint_url": "opc.tcp://192.168.1.100:4840",
    
    # 认证信息（根据实际情况配置）
    "username": "admin",  # 实际使用时从环境变量或密钥管理系统获取
    "password": "password",  # 实际使用时从环境变量或密钥管理系统获取
    
    # 描述
    "description": "生产环境 - 连接到真实工业 OPC UA Server",
    "environment": "production"
}

# 回路配置示例（生产环境 - 西门子 PLC）
LOOP_CONFIG_EXAMPLE_SIEMENS = {
    "loop_id": "reactor_temp_001",
    "name": "反应釜温度控制",
    "description": "1号反应釜温度控制回路",
    
    # OPC UA 节点配置（西门子 S7-1500 示例）
    "opcua_config": {
        "pv_node_id": "ns=3;s=DB100.Temperature.PV",      # 温度传感器
        "sv_node_id": "ns=3;s=DB100.Temperature.SP",      # 设定值
        "mv_node_id": "ns=3;s=DB100.Temperature.MV",      # 控制阀门开度
        "pid_pb_node_id": "ns=3;s=DB100.PID.Pb",          # PID 比例带
        "pid_ti_node_id": "ns=3;s=DB100.PID.Ti",          # PID 积分时间
        "pid_td_node_id": "ns=3;s=DB100.PID.Td"           # PID 微分时间
    },
    
    # 采样配置
    "sampling_interval": 2.0,  # 采样间隔（秒）
    
    # 自动整定配置
    "auto_tuning_enabled": True,
    "tuning_method": "lambda"
}

# 回路配置示例（生产环境 - 施耐德 DCS）
LOOP_CONFIG_EXAMPLE_SCHNEIDER = {
    "loop_id": "column_pressure_001",
    "name": "精馏塔压力控制",
    "description": "1号精馏塔压力控制回路",
    
    # OPC UA 节点配置（施耐德 Modicon 示例）
    "opcua_config": {
        "pv_node_id": "ns=2;i=1001",      # 压力传感器
        "sv_node_id": "ns=2;i=1002",      # 设定值
        "mv_node_id": "ns=2;i=1003",      # 控制阀门
        "pid_pb_node_id": "ns=2;i=2001",  # PID 比例带
        "pid_ti_node_id": "ns=2;i=2002",  # PID 积分时间
        "pid_td_node_id": "ns=2;i=2003"   # PID 微分时间
    },
    
    # 采样配置
    "sampling_interval": 2.0,
    
    # 自动整定配置
    "auto_tuning_enabled": True,
    "tuning_method": "lambda"
}

# 日志配置
LOGGING_CONFIG = {
    "level": "INFO",  # 生产环境使用 INFO 级别
    "format": "%(asctime)s - [PROD] - %(name)s - %(levelname)s - %(message)s",
    "file": "/var/log/web_tuning/app.log"  # 生产环境记录到文件
}

# 数据库配置（如果需要）
DATABASE_CONFIG = {
    "type": "postgresql",  # 生产环境使用 PostgreSQL
    "host": "localhost",
    "port": 5432,
    "database": "web_tuning",
    "username": "web_tuning_user",
    "password": "secure_password"  # 实际使用时从环境变量获取
}

# 安全配置
SECURITY_CONFIG = {
    # OPC UA 安全策略
    "opcua_security_policy": "Basic256Sha256",  # 生产环境使用加密
    "opcua_security_mode": "SignAndEncrypt",
    
    # 证书路径
    "client_certificate": "/etc/web_tuning/certs/client_cert.pem",
    "client_private_key": "/etc/web_tuning/certs/client_key.pem",
    "server_certificate": "/etc/web_tuning/certs/server_cert.pem"
}

# 其他生产配置
DEBUG = False
TESTING = False

# 告警配置
ALARM_CONFIG = {
    "enabled": True,
    "email_notifications": True,
    "sms_notifications": False
}

# 备份配置
BACKUP_CONFIG = {
    "enabled": True,
    "interval": 3600,  # 每小时备份一次
    "retention_days": 30
}
