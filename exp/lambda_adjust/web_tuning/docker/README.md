# 🐳 Docker 配置文件

本目录包含所有 Docker 相关的配置文件。

## 📁 文件说明

```
docker/
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── .dockerignore          # Docker 构建忽略规则
├── nginx/                 # Nginx 配置
│   └── nginx.conf         # Nginx 反向代理配置
└── README.md              # 本文件
```

## 🚀 快速使用

### 从项目根目录使用 Makefile（推荐）

```bash
# 在 web_tuning 目录下执行
make docker-build    # 构建镜像
make docker-up       # 启动服务
make docker-down     # 停止服务
make docker-logs     # 查看日志
```

### 直接使用 docker-compose

```bash
# 在 web_tuning 目录下执行
docker-compose -f docker/docker-compose.yml build
docker-compose -f docker/docker-compose.yml up -d
docker-compose -f docker/docker-compose.yml down
```

### 在 docker 目录内执行

```bash
# 进入 docker 目录
cd docker

# 执行命令
docker-compose build
docker-compose up -d
docker-compose down
```

## 📦 服务说明

### Backend (后端服务)
- **端口**: 8000
- **容器名**: pid-tuning-backend
- **功能**: FastAPI 后端服务

### Frontend (前端服务)
- **端口**: 8080
- **容器名**: pid-tuning-frontend
- **功能**: Nginx 静态文件服务

### OPC UA Server (可选)
- **端口**: 4840
- **容器名**: pid-tuning-opcua
- **启动**: `docker-compose --profile with-opcua up -d`

## 🔧 配置说明

### Dockerfile
- 多阶段构建，优化镜像大小
- 使用国内镜像源加速构建
- 包含所有必要的依赖

### docker-compose.yml
- 定义了三个服务：backend, frontend, opcua-server
- 配置了健康检查和自动重启
- 使用数据卷持久化数据

### nginx.conf
- 反向代理配置
- 支持 WebSocket
- 启用 Gzip 压缩

## 📝 注意事项

1. **构建上下文**: 构建上下文设置为 `../..`（lambda_adjust 目录），以便访问 `core` 依赖
2. **卷挂载**: 所有路径都使用相对路径 `../` 指向 web_tuning 目录
3. **网络**: 所有服务在同一个 Docker 网络 `pid-network` 中

## 🔗 相关文档

- [PACKAGING_GUIDE.md](../PACKAGING_GUIDE.md) - 完整打包指南
- [README.md](../README.md) - 项目说明
