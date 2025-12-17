# PID Agent MVP

PID控制系统智能分析与自动化调优服务

## 项目概述

PID Agent是一个用于PID控制器智能分析和自动调优的服务平台。该系统能够:

- 自动分析回路性能
- 提供专家级PID参数调优建议
- 监控回路运行状态
- 生成性能报告和调优记录

## 技术架构

### 后端技术栈
- Python 3.8+
- FastAPI (Web框架)
- SQLAlchemy (ORM)
- PostgreSQL (主数据库)
- Redis (缓存)
- Uvicorn (ASGI服务器)

### 核心功能模块
1. **回路管理** - 管理PID控制回路信息
2. **性能分析** - 分析回路运行性能指标
3. **自动调优** - 基于AI算法提供PID参数优化建议
4. **专家调优** - 提供专家系统调优功能
5. **数据转换** - PID参数格式转换工具
6. **时序数据** - 与TSDB集成获取实时数据
7. **定时任务** - 自动化定期任务执行

## 快速开始

### 环境要求
- Python 3.8+
- PostgreSQL 12+
- Redis 6+

### 安装步骤

1. 克隆项目代码
```bash
git clone <repository-url>
cd pid-agent-mvp
```

2. 创建虚拟环境并激活
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows
```

3. 安装依赖
```bash
pip install -r requirements.txt
```

4. 配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件配置数据库和其他参数
```

5. 初始化数据库
```bash
python scripts/init_db.py
```

6. 启动服务
```bash
python run_server.py
```

### 多Worker部署

在生产环境中，可以使用多Worker模式提高性能:

```bash
# 设置Worker数量
export WORKERS=4
python run_server.py
```

定时任务会自动适配多Worker环境，只在主Worker中执行。

## API文档

服务启动后，可通过以下地址访问API文档:

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## 定时任务

系统内置多种定时任务:

1. **回路性能计算任务** - 定期计算所有回路的性能指标
2. **模型树加载任务** - 同步BFF模型树到本地数据库
3. **装置统计任务** - 按天统计装置自控率等指标

可通过环境变量配置任务执行时间和并发数。

## 开发指南

### 代码结构
```
api/              # API接口层
├── routes/       # 路由定义
├── services/     # 业务逻辑层
├── dao/          # 数据访问对象
├── bean/         # 数据传输对象
└── tasks/        # 定时任务

core/             # 核心组件
├── algorithm/    # 算法实现
├── client/       # 外部服务客户端
├── database/     # 数据库配置
└── utils/        # 工具类

test/             # 测试代码
scripts/          # 脚本工具
```

### 添加新API

1. 在 `api/routes/` 创建新的路由文件
2. 在 `api/services/` 实现业务逻辑
3. 在 `api/dao/` 添加数据访问方法
4. 在 `api/main.py` 注册路由

### 添加新定时任务

1. 在 `api/tasks/` 创建任务实现
2. 在 `api/tasks/__init__.py` 的 `init_cron_tasks()` 函数中注册任务
3. 在 `.env` 文件中添加任务配置项

## 测试

运行单元测试:
```bash
python -m pytest test/
```

## 部署

### Docker部署

```bash
docker-compose up -d
```

### Kubernetes部署

TODO: 添加K8s部署说明

## 监控与日志

- 使用标准Python日志模块
- 支持不同日志级别(DEBUG/INFO/WARNING/ERROR)
- 可配置日志输出格式和目标

## 故障排除

常见问题及解决方案:

1. 数据库连接失败 - 检查 `.env` 配置和数据库服务状态
2. API返回500错误 - 查看日志定位具体错误
3. 定时任务未执行 - 检查Cron表达式和任务注册状态

## 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交代码更改
4. 发起Pull Request

## 许可证

TODO: 添加许可证信息