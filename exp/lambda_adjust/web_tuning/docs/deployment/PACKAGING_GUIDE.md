# 📦 PID 参数整定系统 - 打包部署指南

本文档介绍如何将 `web_tuning` 项目打包成可分发的形式。

---

## 🎯 打包方式概览

| 方式 | 适用场景 | 优点 | 缺点 |
|------|---------|------|------|
| **Docker** | 生产环境、云部署 | 环境一致、易部署 | 需要 Docker |
| **可执行文件** | 桌面应用、离线环境 | 独立运行、无需 Python | 文件较大 |
| **压缩包** | 源码分发、开发环境 | 灵活、可定制 | 需要配置环境 |

---

## 🐳 方式一：Docker 打包（推荐）

### 特点
- ✅ 环境隔离，无依赖冲突
- ✅ 一键部署，跨平台运行
- ✅ 适合生产环境和云部署

### 快速开始

```bash
# 使用 Makefile（推荐）
make docker-build    # 构建镜像
make docker-up       # 启动服务

# 或使用 docker-compose
docker-compose build
docker-compose up -d
```

### 访问系统

- **前端界面**: http://localhost:8080/frontend/index.html
- **后端 API**: http://localhost:8000
- **API 文档**: http://localhost:8000/docs

### 高级用法

```bash
# 启动完整服务（包含 OPC UA）
make docker-up-full
# 或
docker-compose --profile with-opcua up -d

# 查看日志
make docker-logs
# 或
docker-compose logs -f

# 停止服务
make docker-down
# 或
docker-compose down

# 重启服务
make docker-restart
```

### 自定义配置

编辑 `docker-compose.yml` 修改：
- 端口映射
- 环境变量
- 数据卷挂载

### 镜像分发

```bash
# 导出镜像
docker save -o pid-tuning-system.tar pid-tuning-backend:latest

# 在其他机器导入
docker load -i pid-tuning-system.tar

# 推送到 Docker Hub（可选）
docker tag pid-tuning-backend:latest username/pid-tuning:latest
docker push username/pid-tuning:latest
```

---

## 💻 方式二：可执行文件打包

### 特点
- ✅ 独立运行，无需安装 Python
- ✅ 适合桌面应用和离线环境
- ⚠️ 文件较大（~100MB+）

### 打包步骤

```bash
# 1. 安装 PyInstaller
pip install pyinstaller

# 2. 执行打包
python scripts/build_executable.py

# 或使用 Makefile
make build-exe
```

### 输出结果

```
dist/
└── pid-tuning-system/
    ├── pid-tuning-system(.exe)  # 主程序
    ├── frontend/                 # 前端文件
    ├── data/                     # 数据文件
    ├── _internal/                # 依赖库
    └── README.txt                # 使用说明
```

### 使用方法

**Windows:**
```batch
双击运行 pid-tuning-system.exe
```

**macOS/Linux:**
```bash
chmod +x pid-tuning-system
./pid-tuning-system
```

### 分发

将整个 `dist/pid-tuning-system/` 目录打包成 zip 分发给用户。

---

## 📦 方式三：压缩包打包

### 特点
- ✅ 源码分发，完全可定制
- ✅ 文件小，适合开发环境
- ⚠️ 需要手动配置环境

### 打包步骤

```bash
# 执行打包脚本
./scripts/build_package.sh

# 或使用 Makefile
make build-package
```

### 输出结果

```
dist/
├── pid-tuning-system_20250101_120000/     # 源文件目录
├── pid-tuning-system_20250101_120000.tar.gz  # Linux/macOS 压缩包
└── pid-tuning-system_20250101_120000.zip     # Windows 压缩包
```

### 包含内容

- ✅ 完整源代码
- ✅ 安装脚本（install.sh / install.bat）
- ✅ 启动脚本（start.sh / start.bat）
- ✅ 配置文件（.env）
- ✅ 使用文档

### 用户安装步骤

**Linux/macOS:**
```bash
# 1. 解压
tar -xzf pid-tuning-system_*.tar.gz
cd pid-tuning-system_*

# 2. 安装
./install.sh

# 3. 启动
./start.sh
```

**Windows:**
```batch
# 1. 解压 zip 文件

# 2. 运行安装
install.bat

# 3. 启动系统
start.bat
```

---

## 🛠️ Makefile 命令速查

### 开发相关
```bash
make install      # 安装依赖
make dev          # 启动开发环境
make test         # 运行测试
```

### Docker 相关
```bash
make docker-build    # 构建镜像
make docker-up       # 启动服务
make docker-down     # 停止服务
make docker-logs     # 查看日志
make deploy          # 快速部署
```

### 打包相关
```bash
make build-exe       # 打包可执行文件
make build-package   # 打包压缩包
make build-all       # 执行所有打包
```

### 清理相关
```bash
make clean           # 清理构建产物
make clean-all       # 深度清理
```

### 工具命令
```bash
make status          # 查看项目状态
make freeze          # 生成依赖文件
make format          # 格式化代码
make lint            # 代码检查
```

---

## 📋 打包前检查清单

### 必须检查
- [ ] 更新 `.env.example` 配置示例
- [ ] 确认 `backend/requirements.txt` 完整
- [ ] 测试所有核心功能正常
- [ ] 清理临时文件和日志

### 建议检查
- [ ] 更新版本号和更新日志
- [ ] 优化前端资源（压缩 JS/CSS）
- [ ] 检查文档是否最新
- [ ] 准备用户使用说明

---

## 🚀 部署建议

### 开发环境
```bash
# 本地开发
./scripts/start.sh
```

### 测试环境
```bash
# Docker 部署
make deploy
```

### 生产环境
```bash
# 使用 Docker Compose
docker-compose -f docker-compose.yml up -d

# 或使用 Makefile
make deploy-prod
```

### 离线环境
```bash
# 使用可执行文件
make build-exe
# 分发 dist/pid-tuning-system/
```

---

## 🔧 常见问题

### Q1: Docker 构建失败？
```bash
# 清理缓存重新构建
docker-compose build --no-cache
```

### Q2: PyInstaller 打包报错？
```bash
# 确保安装了所有依赖
pip install -r backend/requirements.txt
pip install pyinstaller

# 清理后重新打包
make clean
make build-exe
```

### Q3: 压缩包太大？
```bash
# 检查是否包含了不必要的文件
# 编辑 scripts/build_package.sh 排除更多文件
```

### Q4: 如何修改端口？
```bash
# Docker: 编辑 docker-compose.yml
# 源码: 编辑 .env 文件
# 可执行文件: 编辑打包后的 .env 文件
```

---

## 📞 技术支持

- 📖 详细文档: [README.md](README.md)
- 🚀 快速开始: [docs/QUICK_START.md](docs/QUICK_START.md)
- 🐛 问题反馈: GitHub Issues

---

## 📝 更新日志

### v1.0.0 (2025-11-27)
- ✅ 添加 Docker 打包支持
- ✅ 添加 PyInstaller 可执行文件打包
- ✅ 添加压缩包打包脚本
- ✅ 创建 Makefile 简化流程
- ✅ 完善打包文档

---

## 📄 许可证

MIT License
