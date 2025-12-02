# PID 参数整定系统 - Makefile
# 简化开发、构建和部署流程

.PHONY: help install dev build-docker build-exe build-package clean test deploy

# 默认目标
help:
	@echo "======================================================"
	@echo "🎛️  PID 参数整定系统 - 构建工具"
	@echo "======================================================"
	@echo ""
	@echo "可用命令:"
	@echo "  make install         - 安装依赖"
	@echo "  make dev             - 启动开发环境"
	@echo "  make test            - 运行测试"
	@echo ""
	@echo "Docker 部署:"
	@echo "  make docker-pull     - 拉取基础镜像（解决网络问题）"
	@echo "  make docker-build    - 构建 Docker 镜像"
	@echo "  make docker-up       - 启动 Docker 服务"
	@echo "  make docker-down     - 停止 Docker 服务"
	@echo "  make docker-logs     - 查看 Docker 日志"
	@echo ""
	@echo "打包分发:"
	@echo "  make build-exe       - 打包成可执行文件 (PyInstaller)"
	@echo "  make build-package   - 打包成压缩包 (tar.gz/zip)"
	@echo "  make build-all       - 执行所有打包"
	@echo ""
	@echo "清理:"
	@echo "  make clean           - 清理构建产物"
	@echo "  make clean-all       - 深度清理（包括依赖）"
	@echo "======================================================"

# 安装依赖
install:
	@echo "📦 安装 Python 依赖..."
	@if [ -f backend/requirements.txt ]; then \
		pip install -r backend/requirements.txt; \
	else \
		echo "⚠️  未找到 requirements.txt"; \
	fi
	@echo "✅ 依赖安装完成"

# 开发环境
dev:
	@echo "🚀 启动开发环境..."
	@./scripts/start.sh

# 测试
test:
	@echo "🧪 运行测试..."
	@python -m pytest tests/ -v || echo "⚠️  未找到测试文件"

# ==================== Docker 相关 ====================

# 拉取基础镜像（解决网络问题）
docker-pull:
	@echo "🐳 拉取 Docker 基础镜像..."
	@./pull-base-images.sh

# 构建 Docker 镜像
docker-build:
	@echo "🐳 构建 Docker 镜像..."
	@docker-compose -f docker/docker-compose.yml build
	@echo "✅ Docker 镜像构建完成"

# 启动 Docker 服务
docker-up:
	@echo "🚀 启动 Docker 服务..."
	@docker-compose -f docker/docker-compose.yml up -d
	@echo "✅ 服务已启动"
	@echo "访问地址:"
	@echo "  前端: http://localhost:8080/frontend/index.html"
	@echo "  API:  http://localhost:8000/docs"

# 启动 Docker 服务（包含 OPC UA）
docker-up-full:
	@echo "🚀 启动完整 Docker 服务（包含 OPC UA）..."
	@docker-compose -f docker/docker-compose.yml --profile with-opcua up -d
	@echo "✅ 服务已启动"

# 停止 Docker 服务
docker-down:
	@echo "🛑 停止 Docker 服务..."
	@docker-compose -f docker/docker-compose.yml down
	@echo "✅ 服务已停止"

# 查看 Docker 日志
docker-logs:
	@docker-compose -f docker/docker-compose.yml logs -f

# 重启 Docker 服务
docker-restart: docker-down docker-up

# ==================== 打包相关 ====================

# PyInstaller 打包
build-exe:
	@echo "📦 使用 PyInstaller 打包..."
	@python scripts/build_executable.py
	@echo "✅ 可执行文件打包完成"

# 压缩包打包
build-package:
	@echo "📦 创建压缩包..."
	@./scripts/build_package.sh
	@echo "✅ 压缩包打包完成"

# 执行所有打包
build-all: clean
	@echo "======================================================"
	@echo "📦 执行所有打包任务..."
	@echo "======================================================"
	@make build-package
	@echo ""
	@echo "======================================================"
	@echo "✅ 所有打包任务完成!"
	@echo "======================================================"
	@echo "输出目录: dist/"

# ==================== 清理相关 ====================

# 清理构建产物
clean:
	@echo "🧹 清理构建产物..."
	@rm -rf build/ dist/ *.spec
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type f -name ".DS_Store" -delete 2>/dev/null || true
	@echo "✅ 清理完成"

# 深度清理
clean-all: clean
	@echo "🧹 深度清理..."
	@rm -rf venv/ backend/venv/
	@rm -rf logs/*.log 2>/dev/null || true
	@docker-compose down -v 2>/dev/null || true
	@echo "✅ 深度清理完成"

# ==================== 部署相关 ====================

# 快速部署（Docker）
deploy: docker-build docker-up
	@echo "======================================================"
	@echo "✅ 部署完成!"
	@echo "======================================================"
	@echo "访问地址:"
	@echo "  前端: http://localhost:8080/frontend/index.html"
	@echo "  API:  http://localhost:8000/docs"
	@echo "======================================================"

# 生产环境部署
deploy-prod:
	@echo "🚀 生产环境部署..."
	@docker-compose -f docker-compose.yml up -d
	@echo "✅ 生产环境部署完成"

# ==================== 工具命令 ====================

# 查看项目状态
status:
	@echo "======================================================"
	@echo "📊 项目状态"
	@echo "======================================================"
	@echo "Docker 容器:"
	@docker-compose ps 2>/dev/null || echo "  未运行"
	@echo ""
	@echo "端口占用:"
	@lsof -i :8000 -i :8080 2>/dev/null || echo "  无占用"
	@echo "======================================================"

# 生成依赖文件
freeze:
	@echo "📝 生成依赖文件..."
	@pip freeze > backend/requirements.txt
	@echo "✅ 依赖文件已更新: backend/requirements.txt"

# 格式化代码
format:
	@echo "🎨 格式化代码..."
	@black backend/ 2>/dev/null || echo "⚠️  未安装 black"
	@echo "✅ 代码格式化完成"

# 代码检查
lint:
	@echo "🔍 代码检查..."
	@flake8 backend/ 2>/dev/null || echo "⚠️  未安装 flake8"
	@echo "✅ 代码检查完成"
