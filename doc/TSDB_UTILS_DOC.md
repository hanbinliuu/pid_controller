# TSDB 工具方法使用文档

## 概述

创建了一个便捷的时序数据库工具模块 `core/utils/tsdb_utils.py`，用于获取PID控制系统的历史数据。该工具封装了时序接口调用，专门用于获取包含温度、PID参数和时间戳的历史数据。

## 核心功能

### 主要工具方法

#### 1. `get_pid_history_data()` - 获取PID历史数据

```python
def get_pid_history_data(
    table_name: str,
    start_time: Union[int, str, datetime],
    end_time: Optional[Union[int, str, datetime]] = None,
    limit: int = 1500,
    tags: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]
```

**功能说明：**
- 根据时间范围和表名获取PID控制历史数据
- 自动获取指定的字段：`temperature`, `kp`, `ki`, `kd`, `target_temp`, `control_period`, `max_duty`, `timestamp`
- 支持多种时间格式输入
- 返回标准化的数据列表

**参数说明：**
- `table_name`: 表名
- `start_time`: 开始时间（支持毫秒时间戳、时间字符串或datetime对象）
- `end_time`: 结束时间（可选，默认为当前时间）
- `limit`: 限制返回的数据条数（默认1500）
- `tags`: 标签过滤条件（可选）

**返回格式：**
```json
[
    {
        "timestamp": "2022-07-08 13:36:02.523",
        "temperature": 25.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "target_temp": 25.0,
        "control_period": 100,
        "max_duty": 100
    }
]
```

#### 2. `get_recent_pid_data()` - 获取最近的PID数据

```python
def get_recent_pid_data(
    table_name: str,
    hours: int = 24,
    limit: int = 1500,
    tags: Optional[Dict[str, str]] = None
) -> List[Dict[str, Any]]
```

**功能说明：**
- 获取最近N小时的PID控制数据
- 便捷方法，自动计算时间范围

#### 3. `get_temperature_history()` - 获取温度历史数据

```python
def get_temperature_history(
    table_name: str,
    start_time: Union[int, str, datetime],
    end_time: Optional[Union[int, str, datetime]] = None,
    limit: int = 1500,
    channel: Optional[str] = None
) -> List[Dict[str, Any]]
```

**功能说明：**
- 获取温度历史数据的便捷方法
- 支持按通道过滤

#### 4. `format_pid_data_for_analysis()` - 数据格式化

```python
def format_pid_data_for_analysis(history_data: List[Dict[str, Any]]) -> Dict[str, List]
```

**功能说明：**
- 将PID历史数据格式化为分析工具可用的格式
- 按字段分组数据，便于后续分析

**返回格式：**
```json
{
    "timestamps": ["2022-07-08 13:36:02.523", "..."],
    "temperatures": [25.0, 26.0, "..."],
    "target_temps": [25.0, 25.0, "..."],
    "kp_values": [1.0, 1.0, "..."],
    "ki_values": [0.1, 0.1, "..."],
    "kd_values": [0.05, 0.05, "..."],
    "control_periods": [100, 100, "..."],
    "max_duties": [100, 100, "..."]
}
```

## 使用示例

### 1. 基本使用 - 获取指定时间范围的数据

```python
from core.utils.tsdb_utils import get_pid_history_data

# 使用毫秒时间戳
data = get_pid_history_data(
    table_name="pid_control",
    start_time=1657257600000,
    end_time=1657344000000,
    limit=100
)

print(f"获取到 {len(data)} 条记录")
for record in data[:3]:  # 显示前3条
    print(record)
```

### 2. 使用字符串时间格式

```python
# 使用时间字符串
data = get_pid_history_data(
    table_name="pid_control",
    start_time="2022-07-08 00:00:00",
    end_time="2022-07-09 00:00:00",
    limit=200
)
```

### 3. 使用datetime对象

```python
from datetime import datetime, timedelta

# 使用datetime对象
end_time = datetime.now()
start_time = end_time - timedelta(hours=24)

data = get_pid_history_data(
    table_name="pid_control",
    start_time=start_time,
    end_time=end_time
)
```

### 4. 获取最近的数据

```python
from core.utils.tsdb_utils import get_recent_pid_data

# 获取最近24小时的数据
recent_data = get_recent_pid_data(
    table_name="pid_control",
    hours=24,
    limit=500
)
```

### 5. 带标签过滤的查询

```python
# 查询特定通道的数据
data = get_pid_history_data(
    table_name="pid_control",
    start_time="2022-07-08 00:00:00",
    limit=100,
    tags={"channel": "0", "controller": "main"}
)
```

### 6. 数据格式化用于分析

```python
from core.utils.tsdb_utils import get_pid_history_data, format_pid_data_for_analysis

# 获取原始数据
raw_data = get_pid_history_data(
    table_name="pid_control",
    start_time="2022-07-08 00:00:00",
    limit=100
)

# 格式化数据
formatted_data = format_pid_data_for_analysis(raw_data)

# 使用格式化后的数据进行分析
temperatures = formatted_data["temperatures"]
avg_temp = sum(temperatures) / len(temperatures)
print(f"平均温度: {avg_temp}")
```

## API接口演示

### 1. 获取最近PID数据接口

```http
GET /api/utils/pid-history?table=cpu&hours=24&limit=100
```

**响应示例：**
```json
{
    "status": "success",
    "message": "获取到 3 条PID历史数据",
    "data": {
        "raw_data": [
            {
                "timestamp": "2022-07-08 13:36:02.523",
                "temperature": 25.0,
                "kp": 1.0,
                "ki": 0.1,
                "kd": 0.05,
                "target_temp": 25.0,
                "control_period": 100,
                "max_duty": 100
            }
        ],
        "formatted_data": {
            "timestamps": ["2022-07-08 13:36:02.523"],
            "temperatures": [25.0],
            "kp_values": [1.0],
            "ki_values": [0.1],
            "kd_values": [0.05]
        },
        "summary": {
            "total_records": 3,
            "time_range_hours": 24,
            "table_name": "cpu",
            "fields": ["timestamp", "temperature", "kp", "ki", "kd", "target_temp", "control_period", "max_duty"]
        }
    }
}
```

### 2. 指定时间范围查询接口

```http
GET /api/utils/pid-range?table=cpu&start_time=2022-07-08 00:00:00&end_time=2022-07-09 00:00:00&limit=100
```

## 支持的时间格式

工具方法支持多种时间格式输入：

### 1. 毫秒时间戳
```python
start_time = 1657257600000  # 毫秒时间戳
```

### 2. 秒级时间戳
```python
start_time = 1657257600  # 秒级时间戳（自动转换为毫秒）
```

### 3. 时间字符串格式
```python
start_time = "2022-07-08 13:36:04"      # 标准格式
start_time = "2022-07-08 13:36:04.523"  # 带毫秒
start_time = "2022-07-08"               # 仅日期
start_time = "2022/07/08 13:36:04"      # 斜杠分隔
```

### 4. datetime对象
```python
from datetime import datetime
start_time = datetime(2022, 7, 8, 13, 36, 4)
```

## 错误处理

工具方法包含完善的错误处理机制：

### 1. 无效时间格式
```python
try:
    data = get_pid_history_data("table", "invalid_time")
except ValueError as e:
    print(f"时间格式错误: {e}")
```

### 2. 不存在的表
```python
# 查询不存在的表会返回空列表，不会抛出异常
data = get_pid_history_data("nonexistent_table", start_time)
# data = []
```

### 3. 网络或服务错误
```python
# 服务异常时返回空列表，并打印错误信息
data = get_pid_history_data("table", start_time)
# 如果查询失败，data = []，同时控制台会输出错误信息
```

## 数据字段说明

返回的每条记录包含以下字段：

| 字段名 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `timestamp` | string | 时间戳 | None |
| `temperature` | float | 当前温度 | 25.0 |
| `kp` | float | 比例系数 | 1.0 |
| `ki` | float | 积分系数 | 0.1 |
| `kd` | float | 微分系数 | 0.05 |
| `target_temp` | float | 目标温度 | 25.0 |
| `control_period` | int | 控制周期(ms) | 100 |
| `max_duty` | int | 最大占空比(%) | 100 |

**注意：** 如果查询结果中某个字段缺失，会自动填充默认值。

## 性能特点

### 1. 灵活的时间处理
- 支持多种时间格式自动转换
- 智能识别时间戳精度（秒/毫秒）

### 2. 数据标准化
- 自动确保返回数据包含所有必需字段
- 缺失字段自动填充默认值

### 3. 错误容错
- 网络错误不会导致程序崩溃
- 提供详细的错误信息

### 4. 内存效率
- 支持数据条数限制
- 按需查询指定字段

## 集成建议

### 1. 与分析工具集成
```python
from core.utils.tsdb_utils import get_pid_history_data, format_pid_data_for_analysis
from core.agent.tools import TemperatureAnalysisTool

# 获取历史数据
history_data = get_pid_history_data("pid_control", start_time, end_time)

# 格式化数据
formatted_data = format_pid_data_for_analysis(history_data)

# 用于分析工具
analysis_tool = TemperatureAnalysisTool()
result = analysis_tool._run(json.dumps({"data": history_data}))
```

### 2. 与API接口集成
```python
from fastapi import FastAPI
from core.utils.tsdb_utils import get_recent_pid_data

app = FastAPI()

@app.get("/api/pid-data")
async def get_pid_data(table: str, hours: int = 24):
    data = get_recent_pid_data(table, hours)
    return {"data": data, "count": len(data)}
```

## 总结

TSDB工具方法提供了：

1. **便捷的API** - 简单易用的函数接口
2. **灵活的时间处理** - 支持多种时间格式
3. **标准化数据** - 统一的返回格式
4. **完善的错误处理** - 稳定可靠的运行
5. **高度可扩展** - 易于集成和定制

该工具专门为PID控制系统设计，可以轻松获取包含温度、PID参数和时间戳的历史数据，满足控制系统分析和监控的需求。