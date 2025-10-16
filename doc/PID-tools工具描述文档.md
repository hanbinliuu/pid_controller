# Tools.py 模块文档

## 概述

`tools.py` 模块是 PID Agent 系统的核心工具集，提供了用于温度曲线分析和 PID 参数优化的专业工具类。该模块为 Agent 提供了智能分析和优化建议的能力。

**文件路径**: `core/agent/tools.py`

**模块版本**: v1.0

## 目录

- [功能概述](#功能概述)
- [工具类详解](#工具类详解)
  - [TemperatureAnalysisTool](#1-temperatureanalysistool)
  - [PIDOptimizationTool](#2-pidoptimizationtool)
- [使用示例](#使用示例)
- [数据格式规范](#数据格式规范)
- [常见问题](#常见问题)

---

## 功能概述

`tools.py` 模块提供了以下核心功能：

1. **温度曲线分析**: 分析 PID 控制系统的温度曲线特性，计算关键性能指标
2. **PID 参数优化**: 基于历史数据分析，提供智能化的 PID 参数调优建议
3. **性能评估**: 对控制系统的响应速度、稳定性和精度进行综合评估

---

## 工具类详解
### TemperatureAnalysisTool 分析指标
- `current_temp`: 当前温度
- `target_temp`: 目标温度
- `max_temp`: 最高温度
- `min_temp`: 最低温度
- `avg_temp`: 平均温度
- `temp_std`: 温度标准差(波动程度)
- `steady_state`: 稳态温度
- `steady_error`: 稳态误差
- `overshoot`: 超调量(%)
- `rise_time`: 上升时间

### PIDOptimizationTool 分析结果
- `current_params`: 当前PID参数
- `performance`: 性能指标
  - `steady_error`: 稳态误差
  - `stability`: 稳定性
  - `data_points`: 数据点数
- `status`: 系统状态评估
  - `response_speed`: 响应速度
  - `stability`: 稳定性
  - `accuracy`: 精度
- `tuning_suggestions`: 调参建议

### 1. TemperatureAnalysisTool

温度曲线分析工具，用于分析 PID 控制系统的温度特性和性能指标。

#### 基本信息

- **工具名称**: `temperature_curve_analysis`
- **主要功能**: 分析温度曲线，计算上升时间、超调量、稳态误差、温度波动等指标
- **适用场景**: PID 控制系统性能评估、温度控制效果分析

#### 输入参数

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `history_data` | `str` 或 `List[Dict]` | ✓ | PID 历史数据，支持 JSON 字符串或列表格式 |

**历史数据格式**:
```json
[
  {
    "temperature": 25.5,
    "target_temp": 30.0,
    "timestamp": "2025-10-15 10:00:00"
  },
  ...
]
```

#### 输出参数

工具返回 JSON 格式的分析结果，包含以下指标：

| 指标名称 | 类型 | 说明 |
|----------|------|------|
| `current_temp` | `float` | 当前温度值（℃） |
| `target_temp` | `float` | 目标温度值（℃） |
| `max_temp` | `float` | 最高温度值（℃） |
| `min_temp` | `float` | 最低温度值（℃） |
| `avg_temp` | `float` | 平均温度值（℃） |
| `temp_std` | `float` | 温度标准差，反映温度波动程度 |
| `steady_state` | `float` | 稳态温度（最后 5 个数据点的平均值） |
| `steady_error` | `float` | 稳态误差（目标温度 - 稳态温度） |
| `overshoot` | `float` | 超调量（%） |
| `rise_time` | `int` 或 `null` | 上升时间（达到 90% 温度范围的时间点索引） |
| `data_points` | `int` | 数据点总数 |

#### 分析算法

1. **基本统计**: 计算温度的最大值、最小值、平均值、当前值
2. **波动分析**: 通过标准差计算温度波动程度
3. **稳态分析**: 使用最后 5 个数据点计算稳态温度和稳态误差
4. **超调分析**: 计算超调量百分比 = `((最高温度 - 目标温度) / 目标温度) × 100%`
5. **上升时间**: 计算从最低温度到 90% 温度范围所需的时间点数

#### 示例输出

```json
{
  "current_temp": 29.8,
  "target_temp": 30.0,
  "max_temp": 31.2,
  "min_temp": 25.0,
  "avg_temp": 28.5,
  "temp_std": 1.2,
  "steady_state": 29.85,
  "steady_error": 0.15,
  "overshoot": 4.0,
  "rise_time": 15,
  "data_points": 100
}
```

---

### 2. PIDOptimizationTool

PID 参数优化工具，基于温度曲线分析结果提供智能化的 PID 参数调优建议。

#### 基本信息

- **工具名称**: `pid_parameter_optimization`
- **主要功能**: 分析 PID 控制效果，提供参数优化建议
- **适用场景**: PID 参数调优、控制系统优化

#### 输入参数

| 参数名 | 类型 | 必需 | 说明 |
|--------|------|------|------|
| `history_data` | `str` 或 `List[Dict]` | ✓ | 包含 PID 参数的历史数据 |

**历史数据格式**:
```json
[
  {
    "temperature": 25.5,
    "target_temp": 30.0,
    "kp": 1.0,
    "ki": 0.1,
    "kd": 0.05,
    "timestamp": "2025-10-15 10:00:00"
  },
  ...
]
```

#### 输出参数

工具返回 JSON 格式的优化分析结果：

**1. 当前参数 (`current_params`)**

| 字段 | 类型 | 说明 |
|------|------|------|
| `kp` | `float` | 比例系数 |
| `ki` | `float` | 积分系数 |
| `kd` | `float` | 微分系数 |
| `target_temp` | `float` | 目标温度 |

**2. 性能指标 (`performance`)**

| 字段 | 类型 | 说明 |
|------|------|------|
| `steady_error` | `float` | 稳态误差（℃） |
| `stability` | `float` | 稳定性（温度标准差） |
| `steady_state_temp` | `float` | 稳态温度（℃） |
| `data_points` | `int` | 数据点数量 |

**3. 系统状态 (`status`)**

| 字段 | 类型 | 可能值 | 说明 |
|------|------|--------|------|
| `response_speed` | `string` | `fast` / `slow` | 响应速度评估 |
| `stability` | `string` | `stable` / `unstable` | 稳定性评估 |
| `accuracy` | `string` | `good` / `poor` | 精度评估 |

**4. 调优建议 (`tuning_suggestions`)**

| 字段 | 类型 | 说明 |
|------|------|------|
| `recommendations` | `List[str]` | 文字建议列表 |
| `suggested_params` | `Dict` | 建议的 PID 参数值 |
| `priority` | `string` | 优先级 (`high` / `medium`) |

#### 优化策略

该工具基于以下规则生成优化建议：

**1. 稳态误差处理**
- 误差 > 1.0℃ 且温度低于目标: 增加 Kp (×1.1) 或 Ki (×1.05)
- 误差 > 1.0℃ 且温度高于目标: 减小 Kp (×0.9) 或 Ki (×0.95)

**2. 稳定性优化**
- 系统不稳定（标准差 ≥ 0.5）: 减小 Kp (×0.8)，增加 Kd (×1.2)

**3. 响应速度优化**
- 响应慢（未达到目标温度的 90%）: 适度增加 Kp

**4. 参数安全范围**
- Kp: 0.1 ~ 10.0
- Ki: 0.01 ~ 1.0
- Kd: 保持在合理范围内

#### 示例输出

```json
{
  "current_params": {
    "kp": 1.0,
    "ki": 0.1,
    "kd": 0.05,
    "target_temp": 30.0
  },
  "performance": {
    "steady_error": 0.15,
    "stability": 1.2,
    "steady_state_temp": 29.85,
    "data_points": 100
  },
  "status": {
    "response_speed": "fast",
    "stability": "unstable",
    "accuracy": "good"
  },
  "tuning_suggestions": {
    "recommendations": [
      "系统振荡，建议减小Kp参数或增加Kd参数"
    ],
    "suggested_params": {
      "kp": 0.8,
      "ki": 0.1,
      "kd": 0.06,
      "target_temp": 30.0
    },
    "priority": "medium"
  }
}
```

---

## 使用示例

### 方式一：直接调用工具

```python
from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool
import json

# 准备历史数据
history_data = [
    {
        "temperature": 25.0,
        "target_temp": 30.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "timestamp": "2025-10-15 10:00:00"
    },
    {
        "temperature": 28.5,
        "target_temp": 30.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "timestamp": "2025-10-15 10:01:00"
    }
]

# 温度曲线分析
temp_tool = TemperatureAnalysisTool()
analysis_result = temp_tool._run(json.dumps(history_data))
print(json.loads(analysis_result))

# PID 参数优化
pid_tool = PIDOptimizationTool()
optimization_result = pid_tool._run(json.dumps(history_data))
print(json.loads(optimization_result))
```

### 方式二：通过 get_tools() 获取工具列表

```python
from core.agent.tools import get_tools

# 获取所有工具
tools = get_tools()

# 查看工具信息
for tool in tools:
    print(f"工具名称: {tool.name}")
    print(f"工具描述: {tool.description}")
    print("-" * 50)
```

### 方式三：在 Agent 中使用

```python
# Agent 会自动调用这些工具
# 工具会被注册到 Agent 的工具库中
# Agent 根据用户查询自动选择合适的工具执行
```

---

## 数据格式规范

### 输入数据格式

#### JSON 字符串格式
```json
"[{\"temperature\": 25.0, \"target_temp\": 30.0, \"kp\": 1.0, \"ki\": 0.1, \"kd\": 0.05}]"
```

#### 列表格式
```python
[
    {
        "temperature": 25.0,
        "target_temp": 30.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05
    }
]
```

#### 字典包裹的数据格式
```json
{
  "data": [
    {
      "temperature": 25.0,
      "target_temp": 30.0
    }
  ]
}
```

### 必需字段

**TemperatureAnalysisTool 必需字段**:
- `temperature`: 当前温度值
- `target_temp`: 目标温度值

**PIDOptimizationTool 必需字段**:
- `temperature`: 当前温度值
- `target_temp`: 目标温度值
- `kp`: 比例系数
- `ki`: 积分系数
- `kd`: 微分系数

---

## 错误处理

### 常见错误及处理

| 错误类型 | 错误信息 | 原因 | 解决方案 |
|----------|----------|------|----------|
| 格式错误 | `无效的JSON数据格式` | 输入数据不是有效的 JSON | 确保数据是正确的 JSON 格式 |
| 格式错误 | `无效的历史数据格式` | JSON 解析失败 | 检查 JSON 格式是否正确 |
| 数据错误 | `无历史数据可分析` | 数据列表为空 | 确保提供了有效的历史数据 |
| 字段缺失 | `数据缺少必要字段` | 缺少必需的数据字段 | 补充缺失的必需字段 |
| 分析失败 | `分析失败: {错误信息}` | 计算过程中出现异常 | 检查数据格式和值的有效性 |

### 错误响应格式

```json
{
  "error": "错误描述信息"
}
```

---

## 常见问题

### Q1: 如何判断 PID 系统是否需要优化？

**A**: 查看 `PIDOptimizationTool` 返回的性能指标：
- 稳态误差 > 1.0℃: 需要调整参数提高精度
- 稳定性标准差 ≥ 0.5: 系统不稳定，需要优化
- 优先级为 `high`: 强烈建议立即优化

### Q2: 工具支持的数据格式有哪些？

**A**: 工具支持三种数据格式：
1. JSON 字符串格式
2. Python 列表格式
3. 带 `data` 字段的字典格式

### Q3: 上升时间为 null 是什么意思？

**A**: 表示温度范围为 0（最高温度 = 最低温度）或者没有达到 90% 的温度范围点，可能数据异常或系统未正常工作。

### Q4: 如何解读超调量？

**A**: 
- 超调量 = 0: 无超调，可能响应较慢
- 0 < 超调量 ≤ 10%: 正常范围，控制效果良好
- 超调量 > 10%: 超调过大，建议减小 Kp 或增加 Kd

### Q5: 工具是否会自动应用优化建议？

**A**: 否，工具仅提供优化建议（`suggested_params`），不会自动修改 PID 参数。需要手动应用建议的参数值。

### Q6: 建议需要多少个数据点才能获得准确的分析结果？

**A**: 建议至少 20-50 个数据点。数据点越多，分析结果越准确。少于 10 个数据点可能导致分析结果不准确。

---

## 技术细节

### 标准差计算

```python
def _calculate_std(self, data_list):
    """计算标准差"""
    if len(data_list) <= 1:
        return 0.0
    mean = sum(data_list) / len(data_list)
    variance = sum((x - mean) ** 2 for x in data_list) / len(data_list)
    return variance ** 0.5
```


## 依赖项

```python
import json
import traceback
import sys
import os
from typing import Optional, Dict, List
```

---




