#!/bin/bash

# 🚀 远程部署脚本
# 用于将 web_tuning 部署到其他电脑

set -e

echo "🚀 PID 参数整定系统 - 远程部署脚本"
echo ""

# 检查参数
if [ "$1" == "export" ]; then
    echo "📦 导出模式：创建部署包"
    echo ""
    
    # 1. 构建镜像
    echo "🔨 构建 Docker 镜像..."
    make docker-build
    
    # 2. 导出镜像
    echo "📤 导出 Docker 镜像..."
    docker save docker-backend:latest -o docker-backend.tar
    docker save docker-opcua-server:latest -o docker-opcua-server.tar
    docker save nginx:alpine -o nginx-alpine.tar
    
    # 3. 创建部署包
    echo "📦 创建部署包..."
    mkdir -p deploy-package
    cp docker-backend.tar deploy-package/
    cp docker-opcua-server.tar deploy-package/
    cp nginx-alpine.tar deploy-package/
    cp -r docker deploy-package/
    cp Makefile deploy-package/
    
    # 创建部署说明
    cat > deploy-package/DEPLOY.md << 'EOF'
# 🚀 部署说明

## 前置要求
- Docker Desktop 已安装
- 端口 8000、8080、4840 未被占用

## 部署步骤

### 1. 导入镜像
```bash
docker load -i docker-backend.tar
docker load -i docker-opcua-server.tar
docker load -i nginx-alpine.tar
```

### 2. 验证镜像
```bash
docker images
```

应该看到：
- docker-backend:latest
- docker-opcua-server:latest
- nginx:alpine

### 3. 启动服务
```bash
docker-compose -f docker/docker-compose.yml --profile with-opcua up -d
```

### 4. 查看状态
```bash
docker-compose -f docker/docker-compose.yml ps
```

### 5. 访问系统
- 前端: http://localhost:8080/frontend/index.html
- 后端: http://localhost:8000
- API 文档: http://localhost:8000/docs

## 常用命令

```bash
# 查看日志
docker-compose -f docker/docker-compose.yml logs -f

# 停止服务
docker-compose -f docker/docker-compose.yml down

# 重启服务
docker-compose -f docker/docker-compose.yml restart
```

## 故障排查

### 问题 1: 端口被占用
```bash
# 检查端口
lsof -i :8000
lsof -i :8080
lsof -i :4840

# 停止占用端口的进程
kill -9 <PID>
```

### 问题 2: 容器无法启动
```bash
# 查看详细日志
docker logs <容器名>

# 重新启动
docker-compose -f docker/docker-compose.yml restart
```

## OPC UA 连接

在前端连接 OPC UA 时，使用以下地址：
```
opc.tcp://pid-tuning-opcua:4840/freeopcua/server/
```

**注意**：不要使用 `localhost`，要使用容器名称 `pid-tuning-opcua`。
EOF
    
    # 打包
    echo "🗜️  压缩部署包..."
    tar -czf web_tuning-deploy-$(date +%Y%m%d-%H%M%S).tar.gz deploy-package/
    
    # 清理临时文件
    rm -rf deploy-package/
    rm docker-backend.tar docker-opcua-server.tar nginx-alpine.tar
    
    echo ""
    echo "✅ 部署包创建完成！"
    echo ""
    echo "📦 文件: web_tuning-deploy-*.tar.gz"
    echo ""
    echo "📋 下一步："
    echo "1. 将 .tar.gz 文件传输到目标电脑"
    echo "2. 在目标电脑解压: tar -xzf web_tuning-deploy-*.tar.gz"
    echo "3. 进入目录: cd deploy-package"
    echo "4. 按照 DEPLOY.md 说明部署"
    echo ""

elif [ "$1" == "source" ]; then
    echo "📁 源码模式：创建源码包"
    echo ""
    
    # 创建源码包（排除不必要的文件）
    echo "📦 打包源码..."
    tar -czf web_tuning-source-$(date +%Y%m%d-%H%M%S).tar.gz \
        --exclude='*.pyc' \
        --exclude='__pycache__' \
        --exclude='.git' \
        --exclude='logs/*' \
        --exclude='data/loops_data.json' \
        --exclude='*.tar.gz' \
        --exclude='node_modules' \
        --exclude='.DS_Store' \
        .
    
    echo ""
    echo "✅ 源码包创建完成！"
    echo ""
    echo "📦 文件: web_tuning-source-*.tar.gz"
    echo ""
    echo "📋 下一步："
    echo "1. 将 .tar.gz 文件传输到目标电脑"
    echo "2. 在目标电脑解压: tar -xzf web_tuning-source-*.tar.gz"
    echo "3. 进入目录: cd web_tuning"
    echo "4. 运行部署: make docker-build && make docker-up-full"
    echo ""

else
    echo "用法:"
    echo "  $0 export   - 导出 Docker 镜像（适合离线部署）"
    echo "  $0 source   - 打包源码（适合在线部署）"
    echo ""
    echo "示例:"
    echo "  $0 export   # 创建包含 Docker 镜像的部署包"
    echo "  $0 source   # 创建源码压缩包"
    echo ""
    exit 1
fi
