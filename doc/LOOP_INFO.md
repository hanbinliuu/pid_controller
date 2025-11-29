# 回路 URI 与 loop_path 映射关系表

## 概述

为了管理回路 URI 与其对应的路径（loop_path）之间的映射关系，系统新增了 `loop_path_mapping` 表。该表用于快速转换和查询回路的两种标识方式。

## 表结构

### loop_path_mapping 表

| 字段名 | 类型 | 说明 | 索引 |
|--------|------|------|------|
| id | INTEGER | 主键，自增 | 是 |
| loop_uri | VARCHAR(500) | 回路 URI，唯一标识 | 是（唯一） |
| loop_path | VARCHAR(500) | 回路路径 | 是 |
| loop_name | VARCHAR(200) | 回路名称 | 否 |
| pv_field | VARCHAR(200) | PV（过程变量）字段名 | 否 |
| sv_field | VARCHAR(200) | SV（设定值）字段名 | 否 |
| mv_field | VARCHAR(200) | MV（操纵变量）字段名 | 否 |
| op_field | VARCHAR(200) | OP（控制器输出）字段名 | 否 |
| auto_status_field | VARCHAR(200) | 自动/手动状态字段名 | 否 |
| description | VARCHAR(500) | 描述或备注 | 否 |
| created_time | DATETIME | 创建时间 | 否 |
| updated_time | DATETIME | 更新时间 | 否 |
| is_active | BOOLEAN | 是否激活 | 否 |

## 模块结构

### 1. Bean 模型（api/bean/loop_path_mapping.py）

定义了 `LoopPathMapping` SQLModel 类，继承自 SQLModel 和 BaseModel，既可用于 ORM 操作，也可用于 API 数据验证。

### 2. DAO 层（api/dao/loop_path_mapping_dao.py）

提供数据访问对象，包含以下主要方法：

- `create()` - 创建新的映射记录
- `get_by_id()` - 根据 ID 查询
- `get_by_loop_uri()` - 根据 loop_uri 查询
- `get_by_loop_path()` - 根据 loop_path 查询
- `get_all_active()` - 获取所有激活的记录
- `query_list()` - 分页查询
- `update()` - 根据 ID 更新
- `update_by_loop_uri()` - 根据 loop_uri 更新
- `delete()` - 根据 ID 删除
- `delete_by_loop_uri()` - 根据 loop_uri 删除
- `get_uri_to_path_map()` - 获取 uri->path 映射字典（高效查询）
- `get_path_to_uri_map()` - 获取 path->uri 映射字典（高效查询）

### 3. Service 层（api/services/loop_path_mapping_service.py）

提供业务逻辑，包装 DAO 层的功能，提供更高层的接口：

- `create_mapping()` - 创建映射
- `get_mapping_by_uri()` - 根据 URI 获取映射
- `get_mapping_by_path()` - 根据路径获取映射
- `get_all_mappings()` - 获取所有映射
- `list_mappings()` - 分页列表
- `update_mapping()` - 更新映射
- `delete_mapping()` - 删除映射
- `get_uri_to_path_map()` - 获取映射字典
- `get_path_to_uri_map()` - 获取反向映射字典
- `batch_create_mappings()` - 批量创建

### 4. 路由层（api/routes/loop_path_mapping_router.py）

提供 REST API 接口：

```
POST   /api/v1/loop-path-mapping              创建映射
GET    /api/v1/loop-path-mapping/by-uri       根据 URI 查询映射
GET    /api/v1/loop-path-mapping/by-path      根据路径查询映射
GET    /api/v1/loop-path-mapping/list         分页查询映射列表
PUT    /api/v1/loop-path-mapping              更新映射
DELETE /api/v1/loop-path-mapping              删除映射
GET    /api/v1/loop-path-mapping/maps/uri-to-path     获取 URI->Path 映射字典
GET    /api/v1/loop-path-mapping/maps/path-to-uri     获取 Path->URI 映射字典
POST   /api/v1/loop-path-mapping/batch        批量创建映射
```

## API 使用示例

### 1. 创建单个映射

```bash
curl -X POST "http://localhost:8001/api/v1/loop-path-mapping" \
  -G \
  -d "loop_uri=/pid_zd/0b521c82a96d4107a564e4c2678bdeca" \
  -d "loop_path=/设备/反应器/温度控制回路" \
  -d "loop_name=FIC101A流量控制回路" \
  -d "pv_field=FIC101A_PV" \
  -d "sv_field=FIC101A_SV"
```

### 2. 根据 URI 查询

```bash
curl "http://localhost:8001/api/v1/loop-path-mapping/by-uri?loop_uri=/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
```

### 3. 根据路径查询

```bash
curl "http://localhost:8001/api/v1/loop-path-mapping/by-path?loop_path=/设备/反应器/温度控制回路"
```

### 4. 获取映射字典（高效查询所有映射）

```bash
curl "http://localhost:8001/api/v1/loop-path-mapping/maps/uri-to-path"
```

响应示例：
```json
{
  "code": 0,
  "message": "查询成功",
  "data": {
    "/pid_zd/0b521c82a96d4107a564e4c2678bdeca": "/设备/反应器/温度控制回路",
    "/pid_zd/xyz789": "/设备/冷凝器/温度控制回路"
  }
}
```

### 5. 批量创建映射

```bash
curl -X POST "http://localhost:8001/api/v1/loop-path-mapping/batch" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "loop_uri": "/pid_zd/abc123",
      "loop_path": "/设备/反应器/温度控制",
      "loop_name": "温度控制"
    }
  ]'
```

### 6. 更新映射

```bash
curl -X PUT "http://localhost:8001/api/v1/loop-path-mapping" \
  -G \
  -d "loop_uri=/pid_zd/0b521c82a96d4107a564e4c2678bdeca" \
  -d "loop_name=FIC101A流量控制(已优化)" \
  -d "pv_field=FIC101A_PV_NEW"
```

### 7. 删除映射

```bash
curl -X DELETE "http://localhost:8001/api/v1/loop-path-mapping?loop_uri=/pid_zd/xyz789"
```

## 数据库初始化

数据库初始化文件已更新（core/database/database.py），在启动应用时会自动创建 `loop_path_mapping` 表。

## 测试

### 单元测试
```bash
python test/test_loop_path_mapping.py
```

### API 集成测试
启动应用后运行：
```bash
python test/test_loop_path_mapping_api.py
```

## 集成建议

### 1. 在系统启动时初始化映射

```python
from api.services.loop_path_mapping_service import LoopPathMappingService
from core.database.database import get_db

# 批量导入已知的映射关系
initial_mappings = [
    {
        "loop_uri": "/pid_zd/...",
        "loop_path": "/设备/...",
        "loop_name": "..."
    }
]
db = next(get_db())
LoopPathMappingService.batch_create_mappings(db, initial_mappings)
```

### 2. 在回路查询中使用映射字典

```python
from api.services.loop_path_mapping_service import LoopPathMappingService

# 获取 URI 到路径的映射（一次性获取所有，之后缓存使用）
uri_to_path = LoopPathMappingService.get_uri_to_path_map(db)

# 快速将 URI 转换为 Path
path = uri_to_path.get(loop_uri)
```

### 3. 支持双向查询

系统支持通过 URI 或 Path 快速查询对方的值，无需额外的业务逻辑。

## 性能优化

- `loop_uri` 字段设置为 UNIQUE 索引，确保唯一性和快速查询
- `loop_path` 字段有普通索引，支持高效的路径查询
- 提供 `get_uri_to_path_map()` 和 `get_path_to_uri_map()` 方法用于批量获取映射，降低数据库查询频次

## 注意事项

1. `loop_uri` 必须唯一，不能重复添加相同的 URI
2. `is_active` 字段默认为 True，可用于逻辑删除
3. 时间戳字段自动由数据库维护
4. 测点字段（pv_field、sv_field 等）是可选的，可根据需要填写

## 文件清单

- `api/bean/loop_path_mapping.py` - 数据模型
- `api/dao/loop_path_mapping_dao.py` - 数据访问对象
- `api/services/loop_path_mapping_service.py` - 业务逻辑服务
- `api/routes/loop_path_mapping_router.py` - API 路由
- `test/test_loop_path_mapping.py` - 单元测试
- `test/test_loop_path_mapping_api.py` - API 集成测试
- `core/database/database.py` - 数据库初始化（已更新）
- `api/main.py` - 主应用文件（已更新）
