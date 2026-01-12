# PID Agent MVP 架构设计文档

## 1. 系统概述
PID Agent MVP 是一个专注于工业控制回路（PID）性能分析与自动调优的智能服务平台。它通过对接工业时序数据库（TSDB），利用先进的辨识算法和专家整定逻辑，为工程师提供闭环性能评估、参数优化建议以及回路运行监控。

## 2. 核心架构设计

系统采用经典的分层架构，确保了算法核心与业务逻辑的解耦：

### 2.1 分层模型
- **API 接口层 (api/routes)**: 基于 FastAPI 实现，提供 RESTful 风格的接口。
- **业务服务层 (api/services)**: 封装核心业务逻辑，协调数据采集、算法调用与结果存储。
- **数据访问层 (api/dao)**: 负责与 PostgreSQL 数据库交互，管理回路元数据与整定记录。
- **算法核心层 (core/algorithm)**: 系统的“大脑”，包含数据预处理、模型辨识、整定计算与闭环仿真。
- **外部集成层 (core/client)**: 负责与 TSDB (如 IoTDA)、BFF 系统进行数据交换。

### 2.2 数据流转
1. **数据采集**: `AnalysisService` 调用 TSDB 客户端，获取指定时间段的 PV（测量值）、SP（设定值）和 MV（输出值）历史数据。
2. **预处理**: `DataPreprocessor` 对原始数据进行插值、去噪、异常值剔除。
3. **辨识与建模**: `ModelSelector` 自动识别系统阶数（一阶、二阶等）并拟合模型参数（增益 K、时间常数 T、滞后 L）。
4. **整定计算**: `PIDCalculator` 根据辨识结果，应用 Lambda、Cohen-Coon 等方法计算最优 PID 参数。
5. **仿真验证**: `ClosedLoopSim` 进行闭环仿真，评估新参数下的超调量、调节时间与稳定性。
6. **结果持久化**: 最终建议与分析报告存入数据库，并通过 API 返回给前端展示。

## 3. 核心组件说明

- **[PIDCalculator](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/core/algorithm/model_type/tuning/pid_calculator.py)**: 集成了多种工业整定公式，支持自适应保守调整。
- **[AnalysisService](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/api/services/analysis_service.py)**: 实现了从原始曲线到分析报告的端到端逻辑。
- **定时任务系统 (api/tasks)**: 基于 `croniter` 实现，负责定期扫描所有回路并计算性能指标。

## 4. 技术选型理由
- **Python 3.10**: 利用成熟的科学计算库（NumPy, SciPy, Pandas）。
- **FastAPI**: 异步特性支持高并发的数据查询请求。
- **SQLModel**: 统一了数据模型与数据库 Schema，提高开发效率。
