# 🐳 Docker 部署指南

PID 参数整定系统的 Docker 部署完整指南。

---

## 📋 前置要求

- Docker Desktop 已安装并运行
- 确保端口 8000、8080、4840 未被占用

---

## 🚀 快速部署（3 步完成）

### 步骤 1: 拉取基础镜像

```bash
# 拉取 Python 基础镜像
docker pull python:3.12-slim

# 拉取 Nginx 镜像
docker pull nginx:alpine
```

**如果网络问题导致拉取失败**，请先拉取 Debian 镜像：
```bash
docker pull debian:bookworm-slim
```
然后 Docker 会自动使用它来拉取 Python 镜像。

### 步骤 2: 构建应用镜像

```bash
# 使用 Makefile（推荐）
make docker-build

# 或使用 docker-compose
docker-compose -f docker/docker-compose.yml build
```

### 步骤 3: 启动服务

```bash
# 启动所有服务（包含 OPC UA）
make docker-up-full

# 或使用 docker-compose
docker-compose -f docker/docker-compose.yml --profile with-opcua up -d
```

---

## 🌐 访问服务

启动成功后，访问以下地址：

| 服务 | 地址 | 说明 |
|------|------|------|
| **前端界面** | http://localhost:8080/frontend/index.html | Web 界面 |
| **后端 API** | http://localhost:8000 | API 服务 |
| **API 文档** | http://localhost:8000/docs | Swagger 文档 |
| **OPC UA** | `opc.tcp://pid-tuning-opcua:4840/freeopcua/server/` | OPC UA 服务器 |

**重要提示**：在前端连接 OPC UA 时，使用容器名称 `pid-tuning-opcua` 而不是 `localhost`。

---

## 🛠️ 常用命令

### 查看服务状态
```bash
docker-compose -f docker/docker-compose.yml ps
```

### 查看日志
```bash
# 所有服务
make docker-logs

# 特定服务
docker-compose -f docker/docker-compose.yml logs -f backend
docker-compose -f docker/docker-compose.yml logs -f opcua-server
```

### 停止服务
```bash
make docker-down
```

### 重启服务
```bash
make docker-restart
```

---

## 🔧 故障排查

### 问题 1: 无法拉取镜像

**症状**：`failed to solve: python:3.12-slim: failed to resolve source metadata`

**解决方案**：
```bash
# 先拉取 Debian 基础镜像
docker pull debian:bookworm-slim

# 然后再拉取 Python 镜像
docker pull python:3.12-slim
```

### 问题 2: 端口被占用

**症状**：`port is already allocated`

**解决方案**：
```bash
# 检查端口占用
lsof -i :8000
lsof -i :8080
lsof -i :4840

# 停止占用端口的进程
kill -9 <PID>
```

### 问题 3: OPC UA 连接失败

**症状**：`[Errno 111] Connection refused`

**解决方案**：
- ✅ 使用容器名称：`opc.tcp://pid-tuning-opcua:4840/freeopcua/server/`
- ❌ 不要使用：`opc.tcp://localhost:4840/freeopcua/server/`

**检查 OPC UA 容器**：
```bash
# 查看容器状态
docker ps | grep opcua

# 查看日志
docker logs pid-tuning-opcua

# 重启容器
docker-compose -f docker/docker-compose.yml restart opcua-server
```

### 问题 4: 容器无法启动

**解决方案**：
```bash
# 查看详细日志
docker logs <容器名>

# 清理并重新构建
make docker-down
docker builder prune -f
make docker-build
make docker-up-full
```

---

## 🔄 更新应用

### 代码更新后重新部署

```bash
# 1. 停止服务
make docker-down

# 2. 重新构建
make docker-build

# 3. 启动服务
make docker-up-full
```

---

## 📊 Makefile 命令参考

```bash
make help              # 查看所有可用命令
make docker-build      # 构建 Docker 镜像
make docker-up         # 启动服务（不含 OPC UA）
make docker-up-full    # 启动服务（包含 OPC UA）
make docker-down       # 停止服务
make docker-restart    # 重启服务
make docker-logs       # 查看日志
```

---

## 📁 Docker 文件结构

```
web_tuning/
├── docker/                      # Docker 配置目录
│   ├── Dockerfile              # 主 Dockerfile
│   ├── docker-compose.yml      # Docker Compose 配置
│   ├── nginx/                  # Nginx 配置
│   │   └── nginx.conf         # Nginx 反向代理配置
│   └── README.md               # Docker 配置说明
├── Makefile                    # 构建和部署命令
└── DOCKER_DEPLOYMENT.md        # 本文件
```

---

## 🎯 完整部署流程示例

```bash
# 1. 进入项目目录
cd /Users/lhb/Documents/pycharmProject/pid-agent-mvp/exp/lambda_adjust/web_tuning

# 2. 拉取基础镜像
docker pull python:3.12-slim
docker pull nginx:alpine

# 3. 构建应用镜像
make docker-build

# 4. 启动所有服务
make docker-up-full

# 5. 验证服务状态
docker-compose -f docker/docker-compose.yml ps

# 6. 查看日志（可选）
make docker-logs

# 7. 访问前端
open http://localhost:8080/frontend/index.html
```

---

## ✅ 部署成功检查清单

- [ ] 基础镜像拉取成功：`docker images | grep python`
- [ ] 应用镜像构建成功：`docker images | grep docker-backend`
- [ ] 容器全部运行：`docker-compose -f docker/docker-compose.yml ps`
- [ ] 前端可访问：`curl http://localhost:8080/frontend/index.html`
- [ ] 后端可访问：`curl http://localhost:8000/health`
- [ ] OPC UA 可连接：在前端测试连接

---

## 🔗 相关文档

- [README.md](README.md) - 项目说明
- [docker/README.md](docker/README.md) - Docker 配置详情
- [Makefile](Makefile) - 构建命令定义

---

## 💡 最佳实践

### 开发环境
- 使用 `make docker-up-full` 启动所有服务
- 使用 `make docker-logs` 实时查看日志
- 代码修改后使用 `make docker-restart` 快速重启

### 生产环境
- 使用 `docker-compose.yml` 配置已包含自动重启策略
- 定期备份 `data/` 和 `logs/` 目录
- 监控容器资源使用：`docker stats`

### 调试技巧
```bash
# 进入容器内部
docker exec -it pid-tuning-backend bash

# 查看容器资源使用
docker stats

# 查看容器详细信息
docker inspect <容器名>
```

---

## 🆘 获取帮助

如果遇到问题：

1. 查看本文档的"故障排查"部分
2. 检查容器日志：`make docker-logs`
3. 验证容器状态：`docker-compose -f docker/docker-compose.yml ps`
4. 查看 [docker/README.md](docker/README.md) 了解配置详情

---

**最后更新**: 2025-11-27  
**版本**: v1.0
