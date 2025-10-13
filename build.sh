#!/bin/bash

# PID Agent API Docker 构建脚本

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 项目配置
PROJECT_NAME="pid-agent"
IMAGE_NAME="pid-agent-api"
TAG=${1:-latest}
REGISTRY=${DOCKER_REGISTRY:-""}
DOCKERFILE=${2:-Dockerfile}  # 支持指定不同的Dockerfile

echo -e "${GREEN}🚀 开始构建 PID Agent API Docker 镜像${NC}"
echo "================================================"

# 检查 Docker 是否安装
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker 未安装，请先安装 Docker${NC}"
    exit 1
fi

# 检查 Docker 是否运行
if ! docker info &> /dev/null; then
    echo -e "${RED}❌ Docker 未运行，请启动 Docker${NC}"
    exit 1
fi

echo -e "${YELLOW}📦 构建配置:${NC}"
echo "   - 项目名称: ${PROJECT_NAME}"
echo "   - 镜像名称: ${IMAGE_NAME}"
echo "   - 标签: ${TAG}"
echo "   - 仓库: ${REGISTRY}"
echo "   - Dockerfile: ${DOCKERFILE}"
echo ""

# 构建镜像
echo -e "${YELLOW}🔨 构建 Docker 镜像...${NC}"
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}:${TAG}"
else
    FULL_IMAGE_NAME="${IMAGE_NAME}:${TAG}"
fi

docker build -f "${DOCKERFILE}" -t "${FULL_IMAGE_NAME}" .

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ 镜像构建成功: ${FULL_IMAGE_NAME}${NC}"
else
    echo -e "${RED}❌ 镜像构建失败${NC}"
    exit 1
fi

# 显示镜像信息
echo ""
echo -e "${YELLOW}📊 镜像信息:${NC}"
docker images | grep "${IMAGE_NAME}" | head -5

# 可选：推送到仓库
if [ -n "$REGISTRY" ] && [ "$2" = "push" ]; then
    echo ""
    echo -e "${YELLOW}📤 推送镜像到仓库...${NC}"
    docker push "${FULL_IMAGE_NAME}"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ 镜像推送成功${NC}"
    else
        echo -e "${RED}❌ 镜像推送失败${NC}"
        exit 1
    fi
fi

echo ""
echo -e "${GREEN}🎉 构建完成！${NC}"
echo ""
echo -e "${YELLOW}💡 使用说明:${NC}"
echo "   1. 运行容器:"
echo "      docker run -d -p 8001:8001 ${FULL_IMAGE_NAME}"
echo ""
echo "   2. 使用 docker-compose:"
echo "      docker-compose up -d"
echo ""
echo "   3. 查看日志:"
echo "      docker logs -f <container_id>"
echo ""
echo "   4. 使用不同的Dockerfile:"
echo "      ./build.sh latest Dockerfile.lite    # 轻量级版本"
echo "      ./build.sh latest Dockerfile.minimal # 最小化版本"