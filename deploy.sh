#!/bin/bash

# PID Agent API 部署脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 配置
SERVICE_NAME="pid-agent-api"
COMPOSE_FILE="docker-compose.yml"
ENV=${1:-development}

echo -e "${GREEN}🚀 部署 PID Agent API 服务${NC}"
echo "================================================"

# 检查 docker-compose 是否安装
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ docker-compose 未安装${NC}"
    exit 1
fi

echo -e "${YELLOW}📋 部署配置:${NC}"
echo "   - 环境: ${ENV}"
echo "   - 服务名: ${SERVICE_NAME}"
echo "   - 配置文件: ${COMPOSE_FILE}"
echo ""

# 创建必要的目录
echo -e "${YELLOW}📁 创建目录结构...${NC}"
mkdir -p logs
mkdir -p data/simulated
mkdir -p nginx/logs

# 停止现有服务
echo -e "${YELLOW}⏹️  停止现有服务...${NC}"
docker-compose down 2>/dev/null || true

# 拉取最新镜像（如果使用外部镜像）
# echo -e "${YELLOW}📥 拉取最新镜像...${NC}"
# docker-compose pull

# 构建并启动服务
echo -e "${YELLOW}🔨 构建并启动服务...${NC}"
if [ "${ENV}" = "production" ]; then
    # 生产环境：启用 Nginx
    docker-compose --profile production up -d --build
else
    # 开发环境：仅启动 API 服务
    docker-compose up -d --build pid-agent-api
fi

# 等待服务启动
echo -e "${YELLOW}⏳ 等待服务启动...${NC}"
sleep 10

# 检查服务状态
echo -e "${YELLOW}🔍 检查服务状态...${NC}"
docker-compose ps

# 健康检查
echo ""
echo -e "${YELLOW}🏥 执行健康检查...${NC}"
HEALTH_URL="http://localhost:8001/health"

for i in {1..10}; do
    if curl -f -s "$HEALTH_URL" > /dev/null; then
        echo -e "${GREEN}✅ 服务健康检查通过${NC}"
        break
    else
        echo -e "${YELLOW}⏳ 等待服务启动... (${i}/10)${NC}"
        sleep 5
    fi
    
    if [ $i -eq 10 ]; then
        echo -e "${RED}❌ 健康检查失败，请检查服务日志${NC}"
        echo ""
        echo -e "${YELLOW}📋 服务日志:${NC}"
        docker-compose logs --tail=20 pid-agent-api
        exit 1
    fi
done

echo ""
echo -e "${GREEN}🎉 部署成功！${NC}"
echo ""
echo -e "${BLUE}📱 服务访问信息:${NC}"
if [ "${ENV}" = "production" ]; then
    echo "   - API 服务: http://localhost"
    echo "   - API 文档: http://localhost/docs"
    echo "   - 健康检查: http://localhost/health"
else
    echo "   - API 服务: http://localhost:8001"
    echo "   - API 文档: http://localhost:8001/docs"
    echo "   - 健康检查: http://localhost:8001/health"
fi
echo ""
echo -e "${BLUE}🔧 管理命令:${NC}"
echo "   - 查看日志: docker-compose logs -f"
echo "   - 停止服务: docker-compose down"
echo "   - 重启服务: docker-compose restart"
echo "   - 查看状态: docker-compose ps"