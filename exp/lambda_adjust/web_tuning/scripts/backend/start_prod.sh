#!/bin/bash

# 生产环境启动脚本
# 用于启动连接真实 OPC UA Server 的 Web Tuning 系统

echo "🏭 启动 Web Tuning 系统 - 生产环境"
echo "========================================================"

# 设置环境变量
export WEB_TUNING_ENV=production

# 安全检查
echo ""
echo "⚠️  警告: 即将连接到真实工业 OPC UA Server"
echo "   请确认以下配置正确："
echo ""
echo "   - OPC UA Server 地址"
echo "   - 认证信息"
echo "   - 网络连接"
echo "   - 节点 ID 配置"
echo ""
read -p "确认配置无误，继续启动？(yes/no) " -r
echo

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "❌ 已取消启动"
    exit 1
fi

echo ""
echo "🔒 生产环境检查..."
echo "========================================================"

# 检查配置文件
if [ ! -f "config/production.py" ]; then
    echo "❌ 缺少生产环境配置文件: config/production.py"
    exit 1
fi
echo "✅ 配置文件存在"

# 检查日志目录
LOG_DIR="/var/log/web_tuning"
if [ ! -d "$LOG_DIR" ]; then
    echo "⚠️  日志目录不存在，创建: $LOG_DIR"
    sudo mkdir -p "$LOG_DIR"
    sudo chown $USER:$USER "$LOG_DIR"
fi
echo "✅ 日志目录就绪"

echo ""
echo "🚀 启动 Web Tuning 后端..."
echo "========================================================"

# 启动应用（生产环境使用 nohup 后台运行）
nohup python app.py > "$LOG_DIR/app.log" 2>&1 &
PID=$!

echo "✅ 应用已启动"
echo "   进程 ID: $PID"
echo "   日志文件: $LOG_DIR/app.log"
echo ""
echo "📊 查看日志: tail -f $LOG_DIR/app.log"
echo "🛑 停止服务: kill $PID"
echo ""

# 等待几秒检查是否启动成功
sleep 3
if ps -p $PID > /dev/null; then
    echo "✅ 服务运行正常"
else
    echo "❌ 服务启动失败，请查看日志"
    cat "$LOG_DIR/app.log"
    exit 1
fi
