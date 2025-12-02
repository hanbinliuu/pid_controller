# 📁 项目文件结构

PID 参数整定系统的完整文件结构说明。

---

## 🎯 目录结构

```
web_tuning/
├── 📄 README.md                    # 项目总览和快速开始
├── 📄 Makefile                     # 构建和部署命令
├── 📄 .env                         # 环境配置（API密钥等）
├── 📄 .env.example                 # 环境配置示例
├── 📄 .gitignore                   # Git忽略规则
│
├── 🌐 frontend/                    # 前端应用
│   ├── index.html                  # 主界面
│   ├── css/                        # 样式文件
│   ├── js/                         # JavaScript模块
│   ├── utils/                      # 前端工具库
│   └── assets/                     # 静态资源
│
├── 🔧 backend/                     # 后端服务
│   ├── app.py                      # FastAPI主程序
│   ├── requirements.txt            # Python依赖
│   ├── modules/                    # 功能模块
│   ├── utils/                      # 后端工具库
│   └── config/                     # 配置文件
│
├── 🐳 docker/                      # Docker配置
│   ├── Dockerfile                  # 镜像构建文件
│   ├── docker-compose.yml          # 服务编排
│   ├── .dockerignore               # Docker忽略规则
│   ├── nginx/                      # Nginx配置
│   │   └── nginx.conf              # 反向代理配置
│   └── DOCKER_DEPLOYMENT.md        # Docker部署指南
│
├── 🖥️ servers/                     # 模拟服务器
│   └── opcua_realistic_server.py   # OPC UA模拟服务器
│
├── 📜 scripts/                     # 脚本工具
│   ├── start.sh                    # 一键启动脚本
│   ├── deploy-to-remote.sh         # 远程部署脚本
│   └── run_desktop.py              # 桌面应用启动
│
├── 📚 docs/                        # 文档中心
│   ├── README.md                   # 文档索引
│   ├── guides/                     # 使用指南
│   │   ├── HOW_TO_USE.md           # 系统使用指南
│   │   └── OPCUA_QUICK_START.md    # OPC UA快速开始
│   ├── deployment/                 # 部署文档
│   │   ├── REMOTE_DEPLOYMENT.md    # 远程部署指南
│   │   ├── OPCUA_DEPLOYMENT_OPTIONS.md # OPC UA部署选项
│   │   └── PACKAGING_GUIDE.md      # 打包指南
│   └── archived/                   # 历史文档归档
│
├── 📊 data/                        # 数据存储
│   └── loops_data.json             # 回路数据
│
├── 📝 logs/                        # 日志文件
│   ├── backend.log                 # 后端日志
│   └── opcua.log                   # OPC UA日志
│
└── 🗂️ electron/                    # Electron桌面应用
    └── main.js                     # 主进程
```

---

## 📋 核心文件说明

### 根目录

| 文件 | 说明 |
|------|------|
| `README.md` | 项目总览、快速开始、功能介绍 |
| `Makefile` | Docker构建、启动、停止等命令 |
| `.env` | 环境变量配置（不提交到Git） |
| `.env.example` | 环境变量示例 |

### 前端 (frontend/)

| 目录/文件 | 说明 |
|-----------|------|
| `index.html` | 主界面HTML |
| `css/` | 样式文件（styles.css等） |
| `js/` | JavaScript模块（app.js, loops_manager.js等） |
| `utils/` | 工具库（apiClient.js, chartUtils.js等） |
| `assets/` | 静态资源（图标、图片等） |

### 后端 (backend/)

| 目录/文件 | 说明 |
|-----------|------|
| `app.py` | FastAPI主程序，所有API接口 |
| `requirements.txt` | Python依赖包列表 |
| `modules/` | 功能模块（comparison, monitoring等） |
| `utils/` | 工具库（logger.py等） |
| `config/` | 配置文件 |

### Docker (docker/)

| 文件 | 说明 |
|------|------|
| `Dockerfile` | 多阶段构建配置 |
| `docker-compose.yml` | 服务编排（backend, frontend, opcua） |
| `nginx/nginx.conf` | Nginx反向代理配置 |
| `DOCKER_DEPLOYMENT.md` | Docker部署完整指南 |

### 脚本 (scripts/)

| 文件 | 说明 |
|------|------|
| `start.sh` | 一键启动脚本（本地开发） |
| `deploy-to-remote.sh` | 远程部署脚本（source/export模式） |
| `run_desktop.py` | Electron桌面应用启动 |

### 文档 (docs/)

| 目录 | 说明 |
|------|------|
| `guides/` | 使用指南（HOW_TO_USE.md, OPCUA_QUICK_START.md） |
| `deployment/` | 部署文档（REMOTE_DEPLOYMENT.md等） |
| `archived/` | 历史文档归档 |

---

## 🔍 文件查找指南

### 我想找...

| 内容 | 位置 |
|------|------|
| 项目介绍 | `README.md` |
| Docker部署 | `docker/DOCKER_DEPLOYMENT.md` |
| 远程部署 | `docs/deployment/REMOTE_DEPLOYMENT.md` |
| 使用说明 | `docs/guides/HOW_TO_USE.md` |
| OPC UA配置 | `docs/guides/OPCUA_QUICK_START.md` |
| 构建命令 | `Makefile` |
| 部署脚本 | `scripts/deploy-to-remote.sh` |
| 后端API | `backend/app.py` |
| 前端界面 | `frontend/index.html` |
| Docker配置 | `docker/docker-compose.yml` |

---

## 📦 重要配置文件

### 环境配置 (.env)

```bash
# AI助手配置
OPENAI_API_KEY=your_api_key
OPENAI_API_BASE=https://api.openai.com/v1

# 环境
ENV=production
```

### Docker配置 (docker-compose.yml)

定义了三个服务：
- `backend` - 后端API（端口8000）
- `frontend` - 前端界面（端口8080）
- `opcua-server` - OPC UA模拟服务器（端口4840）

### Makefile

常用命令：
- `make docker-build` - 构建镜像
- `make docker-up` - 启动服务（不含OPC UA）
- `make docker-up-full` - 启动所有服务（含OPC UA）
- `make docker-down` - 停止服务
- `make docker-logs` - 查看日志

---

## 🧹 文件组织原则

### ✅ 已优化

1. **文档集中管理**
   - 使用指南 → `docs/guides/`
   - 部署文档 → `docs/deployment/`
   - 历史文档 → `docs/archived/`

2. **脚本统一存放**
   - 所有脚本 → `scripts/`

3. **根目录简洁**
   - 只保留 `README.md`、`Makefile`、配置文件

4. **功能模块化**
   - 前端、后端、Docker、文档各自独立

### 📏 命名规范

- **目录名**：小写，用下划线分隔（如 `docs/deployment/`）
- **文件名**：大写，用下划线分隔（如 `HOW_TO_USE.md`）
- **脚本名**：小写，用连字符分隔（如 `deploy-to-remote.sh`）

---

## 🔄 版本历史

### v3.3 (2025-11-27) - 文件结构优化

**优化内容**：
- ✅ 文档重新组织（guides/ + deployment/）
- ✅ 脚本集中管理（scripts/）
- ✅ 根目录简化（只保留核心文件）
- ✅ 删除临时文件（PROJECT_STRUCTURE.txt）

**优化效果**：
- 根目录文件从 6 个减少到 1 个（README.md）
- 文档结构更清晰，易于查找
- 符合项目最佳实践

---

## 💡 最佳实践

### 添加新文档时

1. **使用指南** → 放入 `docs/guides/`
2. **部署文档** → 放入 `docs/deployment/`
3. **开发文档** → 放入 `docs/archived/`（如果是临时的）

### 添加新脚本时

1. 所有脚本放入 `scripts/`
2. 添加执行权限：`chmod +x scripts/your-script.sh`
3. 在 `README.md` 中添加说明

### 修改配置时

1. 修改 `.env.example`（示例）
2. 本地修改 `.env`（不提交）
3. 更新相关文档

---

**最后更新**: 2025-11-27  
**版本**: v3.3
