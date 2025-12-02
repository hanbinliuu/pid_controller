# 🌐 远程部署指南

将 PID 参数整定系统部署到其他电脑的完整指南。

---

## 📋 前置要求

### 目标电脑需要：
- ✅ Docker Desktop 已安装并运行
- ✅ 端口 8000、8080、4840 未被占用
- ✅ 至少 2GB 可用内存
- ✅ 至少 5GB 可用磁盘空间

---

## 🚀 方式 1: 源码部署（推荐）

**适用场景**：目标电脑可以联网

### 在当前电脑

```bash
# 创建源码包
./scripts/deploy-to-remote.sh source
```

会生成：`web_tuning-source-YYYYMMDD-HHMMSS.tar.gz`

### 在目标电脑

```bash
# 1. 解压源码包
tar -xzf web_tuning-source-*.tar.gz
cd web_tuning

# 2. 拉取基础镜像
docker pull python:3.12-slim
docker pull nginx:alpine

# 3. 构建镜像
make docker-build

# 4. 启动服务

# 方式 A: 启动所有服务（包含 OPC UA 模拟服务器）
make docker-up-full

# 方式 B: 只启动必要服务（连接外部 OPC UA 时使用）
make docker-up

# 5. 验证
docker-compose -f docker/docker-compose.yml ps
```

### 访问系统

- 🌐 前端: http://localhost:8080/frontend/index.html
- 🔌 后端: http://localhost:8000
- 📚 API 文档: http://localhost:8000/docs

### 🔌 OPC UA 服务器说明

**两种使用场景**：

1. **使用内置 OPC UA 模拟服务器**（用于测试）
   ```bash
   make docker-up-full  # 启动所有服务
   # 连接地址: opc.tcp://pid-tuning-opcua:4840/freeopcua/server/
   ```

2. **连接外部 OPC UA 数据源**（生产环境）
   ```bash
   make docker-up  # 不启动 OPC UA 模拟服务器
   # 在前端输入外部服务器地址，如: opc.tcp://192.168.1.100:4840
   ```

---

## 📦 方式 2: 镜像部署

**适用场景**：目标电脑无法联网或网络较慢

### 在当前电脑

```bash
# 创建部署包（包含 Docker 镜像）
./scripts/deploy-to-remote.sh export
```

会生成：`web_tuning-deploy-YYYYMMDD-HHMMSS.tar.gz`（约 500MB）

### 在目标电脑

```bash
# 1. 解压部署包
tar -xzf web_tuning-deploy-*.tar.gz
cd deploy-package

# 2. 导入镜像
docker load -i docker-backend.tar
docker load -i docker-opcua-server.tar
docker load -i nginx-alpine.tar

# 3. 验证镜像
docker images

# 4. 启动服务
docker-compose -f docker/docker-compose.yml --profile with-opcua up -d

# 5. 查看状态
docker-compose -f docker/docker-compose.yml ps
```

---

## 🔧 常用命令

### 查看服务状态
```bash
docker-compose -f docker/docker-compose.yml ps
```

### 查看日志
```bash
# 所有服务
docker-compose -f docker/docker-compose.yml logs -f

# 特定服务
docker logs -f pid-tuning-backend
docker logs -f pid-tuning-opcua
```

### 停止服务
```bash
docker-compose -f docker/docker-compose.yml down
```

### 重启服务
```bash
docker-compose -f docker/docker-compose.yml restart
```

### 更新服务
```bash
# 1. 停止服务
docker-compose -f docker/docker-compose.yml down

# 2. 重新构建
make docker-build

# 3. 启动服务
make docker-up-full
```

---

## 🐛 故障排查

### 问题 1: 端口被占用

**症状**：`port is already allocated`

**解决方案**：
```bash
# 检查端口占用
lsof -i :8000
lsof -i :8080
lsof -i :4840

# 停止占用端口的进程
kill -9 <PID>

# 或修改 docker-compose.yml 中的端口映射
```

### 问题 2: OPC UA 连接失败

**症状**：`Connection refused`

**解决方案**：
- ✅ 使用容器名称：`opc.tcp://pid-tuning-opcua:4840/freeopcua/server/`
- ❌ 不要使用：`opc.tcp://localhost:4840/freeopcua/server/`

### 问题 3: 容器无法启动

**解决方案**：
```bash
# 查看详细日志
docker logs <容器名>

# 检查容器状态
docker ps -a

# 重新构建
docker-compose -f docker/docker-compose.yml build --no-cache
```

### 问题 4: 镜像拉取失败

**解决方案**：
```bash
# 方法 1: 使用镜像部署（方式 2）
./deploy-to-remote.sh export

# 方法 2: 先拉取 Debian 基础镜像
docker pull debian:bookworm-slim
docker pull python:3.12-slim
```

---

## 📁 文件传输方式

### 方法 1: SCP（Linux/Mac）
```bash
scp web_tuning-*.tar.gz user@target-host:/path/to/destination/
```

### 方法 2: U盘/移动硬盘
直接复制文件到 U 盘，然后在目标电脑上复制出来

### 方法 3: 网盘
上传到百度网盘、阿里云盘等，在目标电脑下载

### 方法 4: Git（如果有仓库）
```bash
# 在目标电脑
git clone <你的仓库地址>
cd web_tuning
make docker-build
make docker-up-full
```

---

## 🔐 安全建议

### 生产环境部署

1. **修改默认端口**
   编辑 `docker/docker-compose.yml`，修改端口映射

2. **配置防火墙**
   ```bash
   # 只允许特定 IP 访问
   sudo ufw allow from <IP地址> to any port 8080
   ```

3. **使用 HTTPS**
   配置 Nginx SSL 证书

4. **设置环境变量**
   编辑 `.env` 文件，配置 API 密钥等敏感信息

---

## 📊 性能优化

### 资源限制

编辑 `docker/docker-compose.yml`，添加资源限制：

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

### 日志管理

```yaml
services:
  backend:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## ✅ 部署检查清单

部署完成后，检查以下项目：

- [ ] 所有容器都在运行：`docker ps`
- [ ] 前端可以访问：http://localhost:8080/frontend/index.html
- [ ] 后端可以访问：http://localhost:8000
- [ ] API 文档可以访问：http://localhost:8000/docs
- [ ] OPC UA 可以连接
- [ ] 日志正常输出：`make docker-logs`

---

## 📞 获取帮助

- 📖 [Docker 部署指南](docker/DOCKER_DEPLOYMENT.md)
- 📘 [使用指南](docs/HOW_TO_USE.md)
- 🔌 [OPC UA 快速开始](docs/OPCUA_QUICK_START.md)

---

**快速部署**: `./deploy-to-remote.sh source` → 传输 → 解压 → `make docker-build && make docker-up-full` 🚀
