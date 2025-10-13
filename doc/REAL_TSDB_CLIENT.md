# 实际时序数据库客户端使用文档

## 概述

实际时序数据库客户端（`RealTSDBDataSource`）提供了与真实时序数据库服务的HTTP连接功能，与现有的模拟数据源（`MockTSDBDataSource`）形成了完整的数据查询解决方案。

## 核心文件

```
├── core/data/real_tsdb_client.py      # 实际TSDB客户端实现
├── core/data/tsdb_api.py              # 统一接口和模拟数据源
├── .env.example                       # 配置示例文件
└── test/test_real_tsdb_client.py      # 功能测试脚本
```

## 功能特性

### 1. 灵活的配置管理

支持多种配置方式：

- **环境变量配置**：从系统环境变量读取配置
- **代码配置**：通过 `TSDBConfig` 类直接配置
- **默认配置**：提供合理的默认值

### 2. 完整的HTTP客户端功能

- **连接测试**：验证TSDB服务的可用性
- **重试机制**：自动重试失败的请求
- **超时控制**：可配置的请求超时时间
- **认证支持**：支持Token认证

### 3. 与现有系统的无缝集成

- **统一接口**：实现相同的 `TSDBDataSource` 接口
- **工厂模式**：通过工厂类灵活选择数据源
- **向下兼容**：不影响现有的模拟数据功能

## 配置说明

### 环境变量配置

创建 `.env` 文件或设置系统环境变量：

```bash
# 时序数据库服务地址
TSDB_BASE_URL=http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com

# 连接超时时间（秒）
TSDB_TIMEOUT=30

# 最大重试次数
TSDB_MAX_RETRIES=3

# 认证令牌（可选）
TSDB_AUTH_TOKEN=your_auth_token_here

# 是否使用真实TSDB（true/false）
USE_REAL_TSDB=true

# 调试模式（true/false）
TSDB_DEBUG=false
```

### 代码配置

```python
from core.data.real_tsdb_client import TSDBConfig, RealTSDBDataSource

# 创建配置
config = TSDBConfig(
    base_url="http://your-tsdb-server.com",
    timeout=60,
    max_retries=5,
    auth_token="your_token"
)

# 创建客户端
client = RealTSDBDataSource(config)
```

## 使用方法

### 1. 工厂方式创建（推荐）

```python
from core.data.real_tsdb_client import TSDBClientFactory

# 自动根据环境变量选择数据源
client = TSDBClientFactory.create_client()

# 明确指定使用真实TSDB
real_client = TSDBClientFactory.create_client(use_real_tsdb=True)

# 明确指定使用模拟数据
mock_client = TSDBClientFactory.create_client(use_real_tsdb=False)
```

### 2. 直接创建实际客户端

```python
from core.data.real_tsdb_client import TSDBClientFactory

# 使用默认配置
client = TSDBClientFactory.create_real_client()

# 指定自定义URL
client = TSDBClientFactory.create_real_client(
    base_url="http://custom-tsdb.example.com",
    timeout=60,
    auth_token="token"
)
```

### 3. 与现有API集成

```python
from core.data.mock_tsdb_api import get_query_engine, query_raw_data

# 获取查询引擎（自动选择数据源）
engine = get_query_engine()

# 明确指定使用真实TSDB
real_engine = get_query_engine(use_real_tsdb=True)

# 使用便捷查询函数
request_data = {
    "tables": [{"table": "cpu", "fields": ["time", "f1", "f2"]}],
    "detail": {"startTime": 1657257600000, "limit": 100}
}

result = query_raw_data(request_data)
```

## API接口

### 核心方法

#### `query_raw_data(table, fields=None, tags=None, start_time=None, end_time=None, limit=1500, continuation_point=None)`

查询原始时序数据

**参数：**
- `table`: 表名（必需）
- `fields`: 字段列表（可选）
- `tags`: 标签过滤（可选）
- `start_time`: 开始时间戳（毫秒，可选）
- `end_time`: 结束时间戳（毫秒，可选）
- `limit`: 返回记录数限制（默认1500）
- `continuation_point`: 分页续传点（可选）

**返回：** `DataPoint` 对象，包含 `tags`、`columns`、`values`

#### `test_connection()`

测试与TSDB服务的连接

**返回：** 布尔值，表示连接是否成功

#### `get_table_list(database=None)`

获取数据库中的表列表

**参数：**
- `database`: 数据库名称（可选）

**返回：** 表名列表

## 实际使用示例

### 1. 基本查询

```python
from core.data.real_tsdb_client import TSDBClientFactory
from datetime import datetime, timedelta

# 创建客户端
client = TSDBClientFactory.create_real_client()

# 测试连接
if client.test_connection():
    print("连接成功")
    
    # 查询最近1小时的数据
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 3600000  # 1小时前
    
    result = client.query_raw_data(
        table="pid_control",
        fields=["time", "temperature", "target_temp", "kp", "ki", "kd"],
        start_time=start_time,
        end_time=end_time,
        limit=100
    )
    
    print(f"查询到 {len(result.values)} 条记录")
    print(f"字段: {result.columns}")
else:
    print("连接失败")
```

### 2. 使用标签过滤

```python
# 查询特定设备的数据
result = client.query_raw_data(
    table="sensor_data",
    fields=["time", "value"],
    tags={"device_id": "sensor_001", "location": "workshop_1"},
    start_time=start_time,
    end_time=end_time
)
```

### 3. 分页查询

```python
# 首次查询
result = client.query_raw_data(
    table="large_table",
    limit=1000,
    start_time=start_time
)

# 如果有续传点，继续查询下一页
if hasattr(result, 'continuation_point') and result.continuation_point:
    next_result = client.query_raw_data(
        table="large_table",
        limit=1000,
        continuation_point=result.continuation_point
    )
```

### 4. 错误处理

```python
try:
    result = client.query_raw_data(table="non_existent_table")
    if result.values:
        print("查询成功")
    else:
        print("无数据返回")
except Exception as e:
    print(f"查询失败: {e}")
```

## 切换数据源

### 通过环境变量切换

```bash
# 使用真实TSDB
export USE_REAL_TSDB=true

# 使用模拟数据
export USE_REAL_TSDB=false
```

### 在代码中动态切换

```python
from core.data.mock_tsdb_api import get_query_engine

# 在开发环境使用模拟数据
dev_engine = get_query_engine(use_real_tsdb=False)

# 在生产环境使用真实TSDB
prod_engine = get_query_engine(use_real_tsdb=True)
```

## 测试验证

运行测试脚本验证功能：

```bash
cd /Users/dingzhenying/project/pythonProject/pid-agent-mvp
python test/test_real_tsdb_client.py
```

测试将验证：
- 客户端创建和配置
- 连接测试
- 数据查询功能
- 工厂模式
- 与现有API的集成

## 故障排查

### 1. 连接失败

**问题：** `test_connection()` 返回 `False`

**排查：**
- 检查 `TSDB_BASE_URL` 是否正确
- 确认TSDB服务是否运行
- 检查网络连接
- 验证防火墙设置

### 2. 认证错误

**问题：** 收到401或403错误

**排查：**
- 检查 `TSDB_AUTH_TOKEN` 是否正确
- 确认Token是否过期
- 验证API权限设置

### 3. 查询无数据

**问题：** 查询返回空结果

**排查：**
- 确认表名是否存在
- 检查时间范围是否正确
- 验证字段名是否有效
- 检查标签过滤条件

### 4. 超时错误

**问题：** 请求超时

**排查：**
- 增加 `TSDB_TIMEOUT` 值
- 减少查询的数据量
- 检查网络延迟
- 考虑使用分页查询

## 性能优化建议

1. **合理设置超时时间**：根据网络条件和查询复杂度设置
2. **使用字段过滤**：只查询需要的字段，减少网络传输
3. **控制查询范围**：避免查询过大的时间范围
4. **利用分页机制**：对大量数据使用续传点分页查询
5. **缓存常用数据**：在应用层缓存频繁查询的数据

## 扩展功能

如需添加新功能，可以：

1. **扩展 `TSDBConfig`**：添加新的配置选项
2. **重写查询方法**：自定义查询逻辑
3. **添加数据转换**：在查询结果后进行数据处理
4. **集成监控**：添加查询性能监控

通过这种设计，系统既保留了模拟数据的便利性，又提供了与真实TSDB服务集成的能力，可以灵活地在不同环境中使用。