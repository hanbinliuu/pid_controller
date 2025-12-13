#!/bin/bash

# PID Agent MVP 启动脚本
# 用于 Docker 容器启动时的初始化和配置加载

set -e

echo "=========================================="
echo "PID Agent MVP Starting..."
echo "=========================================="

# 显示配置文件路径
CONFIG_FILE="/app/config/application.properties"
if [ -f "$CONFIG_FILE" ]; then
    echo "✓ 配置文件已找到: $CONFIG_FILE"
else
    echo "⚠ 配置文件不存在: $CONFIG_FILE"
    echo "  将使用默认配置或环境变量"
fi

# 显示关键环境变量（隐藏敏感信息）
echo ""
echo "环境变量配置："
echo "  PYTHONPATH: ${PYTHONPATH:-未设置}"
echo "  LOG_LEVEL: ${LOG_LEVEL:-INFO}"
echo "  DB_HOST: ${DB_HOST:-未设置}"
echo "  DB_NAME: ${DB_NAME:-未设置}"

# 检查数据目录
DATA_DIR="/app/data/simulated"
if [ ! -d "$DATA_DIR" ]; then
    echo ""
    echo "创建数据目录: $DATA_DIR"
    mkdir -p "$DATA_DIR"
fi

# 等待数据库就绪（可选）
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
    echo ""
    echo "检查数据库连接: ${DB_HOST}:${DB_PORT}"
    
    # 尝试等待数据库可用（最多等待30秒）
    for i in {1..30}; do
        if timeout 1 bash -c "cat < /dev/null > /dev/tcp/${DB_HOST}/${DB_PORT}" 2>/dev/null; then
            echo "✓ 数据库连接成功"
            break
        fi
        
        if [ $i -eq 30 ]; then
            echo "⚠ 数据库连接超时，但服务将继续启动"
        else
            echo "  等待数据库... ($i/30)"
            sleep 1
        fi
    done
fi

echo ""
echo "=========================================="
echo "启动 PID Agent API 服务器..."
echo "=========================================="
echo ""

# 启动应用
exec python run_server.py
