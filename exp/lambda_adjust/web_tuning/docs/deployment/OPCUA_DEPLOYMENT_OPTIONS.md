# 🔌 OPC UA 部署选项

根据你的使用场景选择合适的部署方式。

---

## 📊 场景对比

| 场景 | 启动命令 | OPC UA Server | 用途 |
|------|---------|---------------|------|
| **测试/演示** | `make docker-up-full` | ✅ 启动内置模拟服务器 | 本地测试、功能演示 |
| **生产环境** | `make docker-up` | ❌ 不启动 | 连接现场 PLC/DCS |

---

## 🎯 场景 1: 测试/演示环境

### 使用内置 OPC UA 模拟服务器

**适用于**：
- ✅ 本地开发测试
- ✅ 功能演示
- ✅ 学习系统功能
- ✅ 没有真实 OPC UA 设备

### 启动方式

```bash
# 启动所有服务（包含 OPC UA 模拟服务器）
make docker-up-full

# 或使用 docker-compose
docker-compose -f docker/docker-compose.yml --profile with-opcua up -d
```

### 连接地址

在前端"实时监控"页面输入：
```
opc.tcp://pid-tuning-opcua:4840/freeopcua/server/
```

### 特点

- ✅ 自动生成模拟数据
- ✅ 模拟真实 PID 控制场景
- ✅ 支持参数调整和重整定
- ✅ 无需外部设备

---

## 🏭 场景 2: 生产环境

### 连接外部 OPC UA 数据源

**适用于**：
- ✅ 连接现场 PLC（西门子、AB、欧姆龙等）
- ✅ 连接 DCS 系统
- ✅ 连接 SCADA 系统
- ✅ 连接 KEPServerEX 等 OPC 网关

### 启动方式

```bash
# 只启动必要服务（不启动 OPC UA 模拟服务器）
make docker-up

# 或使用 docker-compose
docker-compose -f docker/docker-compose.yml up -d
```

### 连接地址

在前端"实时监控"页面输入外部服务器地址，例如：

```bash
# 西门子 PLC
opc.tcp://192.168.1.10:4840

# KEPServerEX
opc.tcp://192.168.1.20:49320

# Ignition
opc.tcp://192.168.1.30:62541/discovery

# 自定义服务器
opc.tcp://your-server-ip:port/path
```

### 认证配置

如果外部服务器需要认证，在前端输入：
- **用户名**：（根据实际配置）
- **密码**：（根据实际配置）

---

## 🔄 切换场景

### 从测试环境切换到生产环境

```bash
# 1. 停止所有服务
make docker-down

# 2. 只启动必要服务
make docker-up

# 3. 在前端连接外部 OPC UA 服务器
```

### 从生产环境切换到测试环境

```bash
# 1. 停止服务
make docker-down

# 2. 启动所有服务（包含模拟服务器）
make docker-up-full

# 3. 在前端连接内置模拟服务器
# 地址: opc.tcp://pid-tuning-opcua:4840/freeopcua/server/
```

---

## 🛠️ 高级操作

### 单独管理 OPC UA 容器

```bash
# 停止 OPC UA 模拟服务器
docker stop pid-tuning-opcua

# 启动 OPC UA 模拟服务器
docker start pid-tuning-opcua

# 删除 OPC UA 模拟服务器
docker rm -f pid-tuning-opcua

# 重新创建 OPC UA 模拟服务器
docker-compose -f docker/docker-compose.yml --profile with-opcua up -d opcua-server
```

### 查看 OPC UA 日志

```bash
# 查看模拟服务器日志
docker logs -f pid-tuning-opcua

# 查看后端 OPC UA 客户端日志
docker logs -f pid-tuning-backend | grep -i opcua
```

---

## 📋 端口使用

| 服务 | 端口 | 说明 |
|------|------|------|
| 后端 API | 8000 | 必需 |
| 前端界面 | 8080 | 必需 |
| OPC UA 模拟服务器 | 4840 | 仅测试环境需要 |

**生产环境部署时**：
- ✅ 端口 8000、8080 必须可用
- ❌ 端口 4840 不需要（不启动模拟服务器）

---

## 🔍 常见问题

### Q1: 如何判断是否需要启动 OPC UA 模拟服务器？

**A**: 
- 如果你有真实的 OPC UA 设备/服务器 → 使用 `make docker-up`
- 如果只是测试系统功能 → 使用 `make docker-up-full`

### Q2: 可以同时连接内置和外部 OPC UA 吗？

**A**: 
不建议。选择其中一种方式：
- 使用内置模拟服务器进行测试
- 连接外部真实设备进行生产

### Q3: 外部 OPC UA 连接失败怎么办？

**A**: 检查以下项目：
1. 网络连通性：`ping <OPC UA 服务器 IP>`
2. 端口开放：`telnet <IP> <端口>`
3. 防火墙设置
4. OPC UA 服务器是否运行
5. 认证信息是否正确

### Q4: 如何测试外部 OPC UA 连接？

**A**: 
```bash
# 在后端容器内测试
docker exec -it pid-tuning-backend python -c "
from asyncua import Client
import asyncio

async def test():
    client = Client('opc.tcp://192.168.1.100:4840')
    try:
        await client.connect()
        print('✅ 连接成功')
        await client.disconnect()
    except Exception as e:
        print(f'❌ 连接失败: {e}')

asyncio.run(test())
"
```

---

## 💡 最佳实践

### 开发/测试阶段
```bash
make docker-up-full  # 使用模拟服务器
```

### 部署到客户现场
```bash
make docker-up  # 不启动模拟服务器，连接现场设备
```

### 演示/培训
```bash
make docker-up-full  # 使用模拟服务器，数据稳定可控
```

---

## 📚 相关文档

- [Docker 部署指南](docker/DOCKER_DEPLOYMENT.md)
- [OPC UA 快速开始](docs/OPCUA_QUICK_START.md)
- [远程部署指南](REMOTE_DEPLOYMENT.md)

---

**快速决策**：
- 有真实设备 → `make docker-up`
- 只是测试 → `make docker-up-full`
