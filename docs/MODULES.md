# PID Agent MVP 业务模块文档

## 1. 业务逻辑层 (Services)
业务服务层位于 `api/services/`，是系统功能的核心入口。

- **[AnalysisService](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/api/services/analysis_service.py)**: 负责回路性能分析逻辑。集成 `TemperatureAnalysisTool` 进行曲线特征识别。
- **[LoopService](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/api/services/loop_service.py)**: 管理控制回路的基础信息、关联测点以及所属装置。
- **[TuningRecordService](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/api/services/tuning_record_service.py)**: 记录每一次整定操作的历史、计算出的参数以及用户反馈，用于后续模型优化。
- **[DeviceManageService](file:///Users/dingzhenying/project/pythonProject/pid-agent-mvp/api/services/device_manage_service.py)**: 维护工厂、车间、装置的多级组织架构。

## 2. 数据持久层 (DAO & Models)
系统使用 **SQLModel** 实现模型定义与数据访问的统一。

- **模型定义 (api/bean/)**:
  - `LoopInfo`: 存储回路 URI、名称、控制类型（PID/APC）等。
  - `TuningRecord`: 存储整定时间、旧参数、建议参数、模型拟合度等。
  - `DeviceEvaluation`: 存储按日/月统计的装置运行效率。
- **数据访问 (api/dao/)**:
  - 遵循单一职责原则，每个模型对应一个 DAO 类。
  - 封装了复杂的查询逻辑，如 `LoopInfoDAO.batch_create` 或 `TuningRecordDAO.get_by_uri`。

## 3. 路由层 (Routes)
API 路由定义在 `api/routes/`，遵循 RESTful 规范。

| 模块 | 路由前缀 | 主要功能 |
| :--- | :--- | :--- |
| 回路分析 | `/api/v1/analysis` | 曲线分析、PID 参数优化建议 |
| 回路管理 | `/api/v1/loops` | 增删改查回路、测点绑定 |
| 整定记录 | `/api/v1/tuning-records` | 历史记录查询、参数导出 |
| 定时任务 | `/api/v1/cron` | 手动触发任务、任务状态监控 |

## 4. 定时任务 (Tasks)
系统后台任务由 `api/tasks/` 管理：
- `calc_device_stats_task.py`: 每日凌晨计算装置自控率。
- `loop_perf_stats_task.py`: 实时/准实时计算回路性能指标。
- `load_loop_info.py`: 与上游系统同步模型树。
