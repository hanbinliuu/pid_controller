# HolliCube OS 数据抽象层 API 接口规格书

> **版本**: v1.0  
> **编写方**: PID 整定 Agent 团队  
> **目标读者**: OS 中台开发团队  
> **目的**: 请中台团队按照本文档建表并开放 REST API，供 PID 整定（常规+大模型）统一调用

---

## 一、背景

根据 HolliCube OS 架构规范，「数据抽象层（核心数据底座）」需要向上层的决策与智能服务层提供 6 类语义化模型数据。目前 PID 整定 Agent 已在本地用 JSON 文件模拟了这 6 类模型的数据结构（见附件 `api_contract_sample.json`），并已跑通常规整定 + 大模型整定双轨流水线。

**我们的需求是：请中台团队将以下 6 张表落库，并提供对应的 REST API。API 上线后，我方仅需将本地 JSON 读取替换为 HTTP 调用即可完成对接，上层算法代码零改动。**

---

## 二、6 张数据表 & 6 个 API 详细规格

---

### 表 1：本体模型 (`os_ontology`)

**职责**: 存储设备的物理硬件属性、回路/设备/工艺之间的本体关系。  
**数据来源**: 设备台账系统、工程设计图纸。  
**更新频率**: 低频（设备改造时才变）。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 |
|:---|:---|:---|:---|:---|
| `device_id` | VARCHAR(64) PK | ✅ | 设备唯一编号 | `2216_LIC_50104` |
| `tag_name` | VARCHAR(64) | ✅ | 位号 | `LIC-50104` |
| `device_type` | VARCHAR(32) | | 设备类型 | `tank` |
| `loop_type` | VARCHAR(32) | ✅ | 回路类型(flow/level/temperature/pressure) | `level` |
| `plant` | VARCHAR(64) | | 所属工厂 | `大榭` |
| `unit` | VARCHAR(64) | | 所属装置 | `2216装置` |
| `tank_volume_m3` | FLOAT | | 容器体积(m³) | `50.0` |
| `tank_cross_section_m2` | FLOAT | | 容器截面积(m²) | `10.0` |
| `valve_cv_max` | FLOAT | | 阀门额定流量系数 | `100.0` |
| `valve_type` | VARCHAR(32) | | 阀门特性(linear/equal_percent) | `linear` |
| `valve_action_type` | VARCHAR(32) | | 阀门动作方式 | `air_to_close` |
| `valve_deadband_percent` | FLOAT | | 阀门死区(%) | `1.0` |
| `pv_range_min` | FLOAT | | PV量程下限 | `0.0` |
| `pv_range_max` | FLOAT | | PV量程上限 | `100.0` |
| `engineering_unit` | VARCHAR(16) | | 工程单位 | `%` |

#### API

```
GET /api/v1/ontology/{device_id}

响应示例:
{
  "device_id": "2216_LIC_50104",
  "tag_name": "LIC-50104",
  "device_type": "tank",
  "loop_type": "level",
  "plant": "大榭",
  "unit": "2216装置",
  "tank_volume_m3": 50.0,
  "tank_cross_section_m2": 10.0,
  "valve_cv_max": 100.0,
  "valve_type": "linear",
  "valve_action_type": "air_to_close",
  "valve_deadband_percent": 1.0,
  "pv_range_min": 0.0,
  "pv_range_max": 100.0,
  "engineering_unit": "%"
}
```

---

### 表 2：机理模型 (`os_mechanism`)

**职责**: 按回路类型归纳的物理机理定性（积分/自衡特性、首选仿真模型结构）。  
**数据来源**: 控制工程专家录入。  
**更新频率**: 极低频（工艺设计变更时才改）。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 (level) |
|:---|:---|:---|:---|:---|
| `loop_type` | VARCHAR(32) PK | ✅ | 回路类型 | `level` |
| `process_nature` | VARCHAR(32) | ✅ | 过程特性(self_regulating/integrating) | `integrating` |
| `dead_time_dominant` | BOOLEAN | | 是否大纯滞后系统 | `false` |
| `preferred_simulation_model` | VARCHAR(32) | | 首选仿真模型结构 | `FO_INTEGRATOR` |
| `fallback_models` | JSON | | 备选模型列表 | `["FOPDT","SO"]` |
| `process_gain_sign` | INT | | 固有正反作用(+1/-1) | `1` |
| `response_speed` | VARCHAR(16) | | 响应速度(fast/medium/slow) | `slow` |

#### API

```
GET /api/v1/mechanism/{loop_type}

响应示例:
{
  "loop_type": "level",
  "process_nature": "integrating",
  "dead_time_dominant": false,
  "preferred_simulation_model": "FO_INTEGRATOR",
  "fallback_models": ["FOPDT", "SO"],
  "process_gain_sign": 1,
  "response_speed": "slow"
}
```

---

### 表 3：知识图谱 (`os_knowledge`)

**职责**: 人类专家积累的控制策略、安全规则、PID 参数容限。  
**数据来源**: 控制专家经验 + 现场 DCS 配置限制。  
**更新频率**: 低频（专家经验迭代时更新）。  
**特殊说明**: 该表同时服务于 PID 整定、大模型整定、设备维保等多个 APP。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 (level) |
|:---|:---|:---|:---|:---|
| `loop_type` | VARCHAR(32) PK | ✅ | 回路类型 | `level` |
| `td_enable` | BOOLEAN | ✅ | 是否允许使用微分 | `false` |
| `max_overshoot_percent` | FLOAT | ✅ | 最大容忍超调(%) | `40.0` |
| `pb_min` | FLOAT | ✅ | 比例带下限(%) | `100.0` |
| `pb_max` | FLOAT | ✅ | 比例带上限(%) | `1000.0` |
| `ti_max` | FLOAT | | 积分时间上限(s) | `3600.0` |
| `td_max` | FLOAT | | 微分时间上限(s) | `0.0` |
| `gain_min` | FLOAT | | 增益下限 | `0.01` |
| `gain_max` | FLOAT | | 增益上限 | `200.0` |
| `tuning_strategy` | VARCHAR(32) | | 策略偏好(aggressive/balanced/conservative) | `conservative` |
| `safety_factor` | FLOAT | | 安全系数 | `1.0` |
| `lambda_default` | FLOAT | | 默认λ整定因子 | `50.0` |
| `expert_notes` | TEXT | | 专家备注 | `积分过程，极度排斥衍生项` |

#### API

```
GET /api/v1/knowledge/{loop_type}

响应示例:
{
  "loop_type": "level",
  "td_enable": false,
  "max_overshoot_percent": 40.0,
  "pb_min": 100.0,
  "pb_max": 1000.0,
  "ti_max": 3600.0,
  "td_max": 0.0,
  "gain_min": 0.01,
  "gain_max": 200.0,
  "tuning_strategy": "conservative",
  "safety_factor": 1.0,
  "lambda_default": 50.0,
  "expert_notes": "液位回路：积分过程，平滑控制，极度排斥衍生项"
}
```

---

### 表 4：表征模型 (`os_characterization`)

**职责**: OS 后台批处理/流计算产出的设备近期运行状态动态评估。  
**数据来源**: Cube-IMP 时序分析引擎定时跑批产出。  
**更新频率**: 高频（建议每日或每班次更新一次）。

> ⚠️ **注意**: 该表目前尚未有数据来源。在 Cube-IMP 批处理引擎上线之前，PID Agent 会在整定运行时自行计算这些特征并回填。请中台团队优先建表预留，待批处理引擎就位后再灌入数据。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 |
|:---|:---|:---|:---|:---|
| `device_id` | VARCHAR(64) PK | ✅ | 设备编号 | `2216_LIC_50104` |
| `timestamp` | DATETIME | ✅ | 评估时间 | `2026-04-07T21:00:00` |
| `oscillation_ratio` | FLOAT | | 近期振荡时间占比(0-1) | `0.45` |
| `dominant_period_s` | FLOAT | | 主振荡周期(秒) | `120.0` |
| `noise_level` | FLOAT | | 高频噪声强度(0-1) | `0.12` |
| `linearity_index` | FLOAT | | 线性度(0-1, 越高越线性) | `0.85` |
| `stiction_index` | FLOAT | | 阀门预测卡涩指数(0-1) | `0.30` |
| `deadband_estimated` | FLOAT | | 阀门预测死区(%) | `1.5` |
| `reversal_error` | FLOAT | | 阀门回程误差 | `0.5` |
| `performance_score` | FLOAT | | 综合控制绩效评分(0-10) | `6.5` |
| `auto_mode_ratio` | FLOAT | | 自动模式占比(0-1) | `0.92` |
| `intervention_count` | INT | | 日均人工干预次数 | `3` |
| `llm_extra_features` | JSON | | 大模型专属扩展特征(可为空) | `{"alarms": [...]}` |

#### API

```
GET /api/v1/characterization/{device_id}?latest=true

响应示例:
{
  "device_id": "2216_LIC_50104",
  "timestamp": "2026-04-07T21:00:00",
  "oscillation_ratio": 0.45,
  "dominant_period_s": 120.0,
  "noise_level": 0.12,
  "linearity_index": 0.85,
  "stiction_index": 0.30,
  "deadband_estimated": 1.5,
  "reversal_error": 0.5,
  "performance_score": 6.5,
  "auto_mode_ratio": 0.92,
  "intervention_count": 3,
  "llm_extra_features": {}
}
```

---

### 表 5：数据模型 (`os_data_mapping`)

**职责**: DCS 系统中测点/点位与业务变量之间的映射关系。  
**数据来源**: DCS 组态配置。  
**更新频率**: 极低频。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 |
|:---|:---|:---|:---|:---|
| `device_id` | VARCHAR(64) PK | ✅ | 设备编号 | `2216_LIC_50104` |
| `pv_tag` | VARCHAR(128) | ✅ | 过程变量点位号 | `LIC-50104.PV` |
| `sv_tag` | VARCHAR(128) | ✅ | 设定值点位号 | `LIC-50104.SV` |
| `out_tag` | VARCHAR(128) | | 输出值点位号 | `LIC-50104.OUT` |
| `scan_interval_ms` | INT | | DCS 扫描周期(ms) | `1000` |
| `control_mode` | VARCHAR(16) | | 控制模式 | `PID` |
| `action` | VARCHAR(16) | | 正反作用 | `reverse` |
| `historical_table_ref` | VARCHAR(128) | | 时序宽表名 | `hist_2216` |
| `db_source` | VARCHAR(64) | | 数据源标识 | `os_historian` |

#### API

```
GET /api/v1/data-mapping/{device_id}

响应示例:
{
  "device_id": "2216_LIC_50104",
  "pv_tag": "LIC-50104.PV",
  "sv_tag": "LIC-50104.SV",
  "out_tag": "LIC-50104.OUT",
  "scan_interval_ms": 1000,
  "control_mode": "PID",
  "action": "reverse",
  "historical_table_ref": "hist_2216",
  "db_source": "os_historian"
}
```

---

### 表 6：指标模型 (`os_metrics`)

**职责**: OS 定期计算并存储的控制回路绩效 KPI。  
**数据来源**: OS 指标计算引擎定时跑批产出。  
**更新频率**: 中频（建议每日更新）。

> ⚠️ **注意**: 该表与表4（表征模型）类似，目前尚无数据来源。请中台团队先建表预留。

#### 表结构

| 字段名 | 类型 | 必填 | 说明 | 示例值 |
|:---|:---|:---|:---|:---|
| `device_id` | VARCHAR(64) PK | ✅ | 设备编号 | `2216_LIC_50104` |
| `timestamp` | DATETIME | ✅ | 评估时间 | `2026-04-07T00:00:00` |
| `auto_control_rate` | FLOAT | | 自控率(0-1) | `0.98` |
| `steady_state_rate` | FLOAT | | 稳态率(0-1) | `0.85` |
| `mse_score` | FLOAT | | 闭环跟踪均方误差 | `0.05` |

#### API

```
GET /api/v1/metrics/{device_id}?latest=true

响应示例:
{
  "device_id": "2216_LIC_50104",
  "timestamp": "2026-04-07T00:00:00",
  "auto_control_rate": 0.98,
  "steady_state_rate": 0.85,
  "mse_score": 0.05
}
```

---

## 三、优先级建议

| 优先级 | 表 | 理由 |
|:---|:---|:---|
| 🔴 P0 立即 | `os_ontology` | 数据已存在于设备台账系统，建表+迁移即可 |
| 🔴 P0 立即 | `os_data_mapping` | 数据已存在于 DCS 组态配置，建表+迁移即可 |
| 🟡 P1 尽快 | `os_knowledge` | 可从我方提供的 JSON 模板（`data/standard_models/*.json`）直接导入 |
| 🟡 P1 尽快 | `os_mechanism` | 同上，可从 JSON 模板直接导入 |
| 🟢 P2 排期 | `os_characterization` | 需 Cube-IMP 批处理引擎支撑，建表后等数据灌入 |
| 🟢 P2 排期 | `os_metrics` | 需指标计算引擎支撑，建表后等数据灌入 |

---

## 四、附件

1. **`api_contract_sample.json`** — 完整的运行时 JSON 输出样本（含 6 大模型实际数据）
2. **`core/models/*.py`** — 可运行的 Python 数据结构原型代码
3. **`data/standard_models/*.json`** — 4 种回路类型的标准模型模板（level/flow/temperature/pressure）
4. **`data/instance_models/*.json`** — 2 个真实设备的实例数据样本（50104/50108）
