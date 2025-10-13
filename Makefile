# PID Agent API Makefile

.PHONY: help build run stop clean logs health test deploy

# 默认目标
.DEFAULT_GOAL := help

# 项目配置
PROJECT_NAME := pid-agent-api
IMAGE_NAME := pid-agent-api
TAG := latest

# 帮助信息
help: ## 显示帮助信息
	@echo "PID Agent API Docker 管理工具"
	@echo "================================"
	@echo ""
	@echo "可用命令:"
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# 构建相关
build: ## 构建 Docker 镜像
	@echo "🔨 构建 Docker 镜像..."
	docker build -t $(IMAGE_NAME):$(TAG) .

build-lite: ## 构建轻量级Docker 镜像
	@echo "🔨 构建轻量级Docker 镜像..."
	docker build -f Dockerfile.lite -t $(IMAGE_NAME):$(TAG)-lite .

build-minimal: ## 构建最小化Docker 镜像
	@echo "🔨 构建最小化Docker 镜像..."
	docker build -f Dockerfile.minimal -t $(IMAGE_NAME):$(TAG)-minimal .

build-no-cache: ## 构建 Docker 镜像（不使用缓存）
	@echo "🔨 构建 Docker 镜像（无缓存）..."
	docker build --no-cache -t $(IMAGE_NAME):$(TAG) .

# 运行相关
run: ## 启动服务（开发模式）
	@echo "🚀 启动服务..."
	docker-compose up -d pid-agent-api

run-prod: ## 启动服务（生产模式，包含 Nginx）
	@echo "🚀 启动生产环境服务..."
	docker-compose --profile production up -d

run-build: ## 构建并启动服务
	@echo "🔨 构建并启动服务..."
	docker-compose up -d --build

# 停止和清理
stop: ## 停止服务
	@echo "⏹️ 停止服务..."
	docker-compose down

clean: ## 清理容器和镜像
	@echo "🧹 清理 Docker 资源..."
	docker-compose down --rmi local --volumes --remove-orphans

clean-all: ## 清理所有相关 Docker 资源
	@echo "🧹 清理所有 Docker 资源..."
	docker-compose down --rmi all --volumes --remove-orphans
	docker image prune -f

# 监控和调试
logs: ## 查看服务日志
	docker-compose logs -f

logs-api: ## 查看 API 服务日志
	docker-compose logs -f pid-agent-api

logs-nginx: ## 查看 Nginx 日志
	docker-compose logs -f nginx

ps: ## 查看容器状态
	docker-compose ps

health: ## 检查服务健康状态
	@echo "🏥 检查服务健康状态..."
	@curl -f http://localhost:8001/health || echo "❌ 服务不健康"

# 开发相关
shell: ## 进入容器 shell
	docker-compose exec pid-agent-api /bin/bash

test: ## 运行测试
	@echo "🧪 运行测试..."
	python -m pytest test/ -v

test-api: ## 测试 API 调用
	@echo "🧪 测试 API..."
	python test_api_call.py

# 部署相关
deploy: ## 部署到开发环境
	@echo "🚀 部署到开发环境..."
	./deploy.sh development

deploy-prod: ## 部署到生产环境
	@echo "🚀 部署到生产环境..."
	./deploy.sh production

# 数据管理
backup-data: ## 备份数据
	@echo "💾 备份数据..."
	tar -czf backup-$(shell date +%Y%m%d_%H%M%S).tar.gz data/

restore-data: ## 恢复数据（需要指定备份文件）
	@echo "📁 恢复数据..."
	@read -p "请输入备份文件名: " backup_file; \
	tar -xzf $$backup_file

# 镜像管理
push: ## 推送镜像到仓库
	@echo "📤 推送镜像..."
	./build.sh $(TAG) push

pull: ## 拉取最新镜像
	@echo "📥 拉取镜像..."
	docker-compose pull

# 快速命令
dev: run ## 快速启动开发环境
prod: run-prod ## 快速启动生产环境
restart: stop run ## 重启服务

# 信息查看
info: ## 显示项目信息
	@echo "项目信息:"
	@echo "  名称: $(PROJECT_NAME)"
	@echo "  镜像: $(IMAGE_NAME):$(TAG)"
	@echo "  服务: http://localhost:8001"
	@echo "  文档: http://localhost:8001/docs"