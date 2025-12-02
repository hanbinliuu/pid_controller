# 🎛️ PID 参数整定系统

> 智能 PID 参数优化平台 - 支持多回路管理、AI 智能助手、自动整定、性能评估

[![Docker](https://img.shields.io/badge/Docker-Ready-blue)](docker/)
[![Python](https://img.shields.io/badge/Python-3.12-green)](backend/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

## 🚀 快速开始

### 🐳 Docker 部署（推荐）

```bash
# 1. 拉取基础镜像
docker pull python:3.12-slim

# 2. 构建镜像
make docker-build

# 3. 启动服务

# 包含 OPC UA 模拟服务器（用于测试）
make docker-up-full

# 或只启动必要服务（连接外部 OPC UA 时）
make docker-up
```

**访问地址：**
- 🌐 前端界面: http://localhost:8080/frontend/index.html
- 🔌 后端 API: http://localhost:8000
- 📚 API 文档: http://localhost:8000/docs
- 🏭 OPC UA: `opc.tcp://pid-tuning-opcua:4840/freeopcua/server/`

> 📖 详细文档: [docker/DOCKER_DEPLOYMENT.md](docker/DOCKER_DEPLOYMENT.md)

### 💻 本地开发

```bash
# 一键启动
./scripts/start.sh
```

访问: http://localhost:8080/frontend/index.html

---

## ✨ 核心功能

| 功能 | 说明 |
|------|------|
| 🎯 **参数整定** | 上传数据 → 系统辨识 → 自动整定 → 实时仿真 |
| 🎛️ **多回路管理** | 创建、管理、监控多个 PID 控制回路 |
| 📊 **实时监控** | OPC UA 数据采集、性能跟踪、报警管理 |
| 🤖 **AI 智能助手** | 参数优化建议、问题诊断、知识问答 |
| 📈 **性能评估** | 综合评分、多维度指标分析 |
| 🔄 **自动重整定** | 检测性能下降、自动触发重整定 |
| 📝 **报告生成** | JSON/Markdown 格式导出 |

---

## 📖 文档

- 🐳 [Docker 部署指南](docker/DOCKER_DEPLOYMENT.md) - 本地 Docker 部署
- 🌐 [远程部署指南](docs/deployment/REMOTE_DEPLOYMENT.md) - 部署到其他电脑
- 📘 [使用指南](docs/guides/HOW_TO_USE.md) - 系统功能和使用说明
- 🔌 [OPC UA 快速开始](docs/guides/OPCUA_QUICK_START.md) - OPC UA 数据源配置
- 📚 [文档中心](docs/) - 完整文档索引

---

## 🏗️ 项目结构

```
web_tuning/
├── frontend/              # 前端应用
│   ├── index.html        # 主界面
│   ├── css/              # 样式文件
│   ├── js/               # JavaScript 模块
│   └── utils/            # 前端工具
│
├── backend/              # 后端服务
│   ├── app.py            # FastAPI 主程序
│   ├── modules/          # 功能模块
│   └── requirements.txt  # Python 依赖
│
├── docker/               # Docker 配置
│   ├── Dockerfile        # 镜像构建
│   ├── docker-compose.yml # 服务编排
│   └── nginx/            # Nginx 配置
│
├── servers/              # 模拟服务器
│   └── opcua_realistic_server.py
│
├── scripts/              # 脚本工具
│   ├── start.sh          # 一键启动
│   └── deploy-to-remote.sh # 远程部署脚本
│
├── data/                 # 数据存储
│   └── loops_data.json   # 回路数据
│
├── docs/                 # 文档中心
│   ├── guides/           # 使用指南
│   ├── deployment/       # 部署文档
│   └── archived/         # 历史文档
│
├── logs/                 # 日志文件
├── Makefile              # 构建命令
├── .env                  # 环境配置
└── README.md             # 本文件
```

---

## 🛠️ 技术栈

### 后端
- **FastAPI** - 高性能 Web 框架
- **asyncua** - OPC UA 客户端/服务器
- **NumPy/SciPy** - 科学计算
- **Python 3.12** - 运行环境

### 前端
- **原生 JavaScript** - 无框架依赖
- **Chart.js** - 数据可视化
- **Bootstrap** - UI 组件

### 部署
- **Docker** - 容器化部署
- **Nginx** - 反向代理
- **docker-compose** - 服务编排

## 📋 Makefile 命令

```bash
make help              # 查看所有命令
make docker-build      # 构建 Docker 镜像
make docker-up-full    # 启动所有服务（含 OPC UA）
make docker-down       # 停止服务
make docker-logs       # 查看日志
make docker-restart    # 重启服务
```

---

## 🔄 更新日志

### v3.3 (2025-11-27)
- ✅ Docker 完整支持（Dockerfile + docker-compose）
- ✅ OPC UA 服务器容器化
- ✅ Nginx 反向代理配置
- ✅ 日志输出优化（支持 Docker logs）
- ✅ 文档重构和简化

### v3.2
- ✅ 目录结构优化（前端/后端/服务器分离）
- ✅ 端口自动清理
- ✅ 路径配置统一管理

### v3.1
- ✅ 多回路管理系统
- ✅ 实时监控与性能跟踪
- ✅ OPC UA 数据源支持
- ✅ 自动重整定服务
- ✅ AI 智能助手集成

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

---

**快速开始**: `make docker-build && make docker-up-full` 🚀
