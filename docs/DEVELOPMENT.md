# PID Agent MVP 开发与部署指南

## 1. 环境配置

### 1.1 基础依赖
- **Python**: 3.10+
- **数据库**: PostgreSQL 12+ (核心业务数据)
- **缓存**: Redis 6+ (任务队列与缓存)

### 1.2 本地开发环境搭建
1. 创建并激活虚拟环境：
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
2. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
3. 配置文件：
   - 复制 `.env.example` 为 `.env`
   - 修改数据库连接字符串 (`DATABASE_URL`) 和外部 API 地址。

## 2. 数据库迁移 (Alembic)
本项目使用 Alembic 管理 Schema 变更。
- **生成迁移脚本**: `alembic revision --autogenerate -m "description"`
- **执行迁移**: `alembic upgrade head`

## 3. 测试指南
测试代码位于 `test/` 目录。
- **运行单元测试**: `pytest`
- **运行覆盖率测试**: `pytest --cov=api --cov=core`

## 4. 部署方案

### 4.1 Docker 部署 (推荐)
使用项目根目录下的 `docker-compose.yml` 快速启动：
```bash
docker-compose up -d --build
```

### 4.2 生产环境优化
- **多 Worker 运行**:
  ```bash
  export WORKERS=4
  python run_server.py
  ```
- **日志管理**: 日志默认输出到标准输出，建议通过 Docker Logging Driver 或 ELK 收集。

## 5. CI/CD 流程
项目包含多个 `Jenkinsfile`，支持：
- **SonarQube**: 自动化代码质量扫描。
- **构建镜像**: 自动构建并推送到私有镜像仓库。
- **部署**: 支持多环境（Dev/Test/Prod）自动化部署。
