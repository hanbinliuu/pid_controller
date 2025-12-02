#!/bin/bash

# 🧹 完全清理并重新部署 Docker 环境

set -e  # 遇到错误立即退出

echo "🧹 开始清理 Docker 环境..."
echo ""

# 1. 停止并删除所有容器
echo "📦 停止并删除容器..."
docker-compose -f docker/docker-compose.yml down -v 2>/dev/null || true

# 2. 删除相关镜像
echo "🗑️  删除旧镜像..."
docker images --format "{{.Repository}}:{{.Tag}}" | grep -E "(docker-backend|docker-opcua|python|nginx)" | xargs -I {} docker rmi -f {} 2>/dev/null || true

# 3. 清理构建缓存
echo "🧽 清理构建缓存..."
docker builder prune -af

# 4. 验证清理
echo ""
echo "✅ 清理完成！"
echo ""
echo "📊 当前 Docker 状态："
echo "镜像数量: $(docker images -q | wc -l | tr -d ' ')"
echo "容器数量: $(docker ps -aq | wc -l | tr -d ' ')"
echo ""

# 5. 开始重新部署
echo "🚀 开始重新部署..."
echo ""

# 6. 拉取基础镜像
echo "📥 拉取基础镜像..."
docker pull python:3.12-slim
docker pull nginx:alpine

echo ""
echo "✅ 基础镜像拉取成功！"
echo ""

# 7. 构建应用镜像
echo "🔨 构建应用镜像..."
make docker-build

echo ""
echo "✅ 应用镜像构建成功！"
echo ""

# 8. 启动服务
echo "🚀 启动所有服务（包含 OPC UA）..."
make docker-up-full

echo ""
echo "⏳ 等待服务启动..."
sleep 5

# 9. 验证服务
echo ""
echo "🔍 验证服务状态..."
docker-compose -f docker/docker-compose.yml ps

echo ""
echo "✅ 部署完成！"
echo ""
echo "🌐 访问地址："
echo "  - 前端: http://localhost:8080/frontend/index.html"
echo "  - 后端: http://localhost:8000"
echo "  - API 文档: http://localhost:8000/docs"
echo "  - OPC UA: opc.tcp://pid-tuning-opcua:4840/freeopcua/server/"
echo ""
echo "📋 查看日志: make docker-logs"
echo ""
