#!/bin/bash

# 开发环境启动脚本
# 用于启动仿真模式的 Web Tuning 系统

echo "🧪 启动 Web Tuning 系统 - 开发环境（仿真模式）"
echo "========================================================"

# 设置环境变量
export WEB_TUNING_ENV=development

# 检查仿真服务器是否运行
echo ""
echo "📋 检查仿真 OPC UA Server..."
if ! lsof -i:4840 > /dev/null 2>&1; then
    echo "⚠️  仿真 OPC UA Server 未运行"
    echo "   请在另一个终端运行: cd ../servers && python opcua_realistic_server.py"
    echo ""
    read -p "是否继续启动？(y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "✅ 仿真 OPC UA Server 正在运行"
fi

echo ""
echo "🚀 启动 Web Tuning 后端..."
echo "========================================================"

# 启动应用
python app.py

# 如果启动失败
if [ $? -ne 0 ]; then
    echo ""
    echo "❌ 启动失败！"
    echo "   请检查错误信息并修复问题"
    exit 1
fi
