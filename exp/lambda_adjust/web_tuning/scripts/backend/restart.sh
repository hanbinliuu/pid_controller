#!/bin/bash

echo "🔄 重启后端服务..."

# 杀死旧进程
echo "⏹️  停止旧进程..."
lsof -ti:8000 | xargs kill -9 2>/dev/null
sleep 1

# 启动新进程
echo "🚀 启动新进程..."
cd "$(dirname "$0")"
python app.py
