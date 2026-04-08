# core/models — OS 语义层对接说明

---

## 1. 目录结构

```
core/models/
├── schemas/          ← 📐 6 大原子语义模型（定义"OS 需要存哪些字段"）
├── provider/         ← 🔌 数据读取网关（算法侧，OS 只需关注接口形态）
├── features/         ← 🧮 特征计算代码（OS 中台实现 characterization 接口时的参考实现）
├── contracts/        ← 📄 API 规格文档和接口契约示例（OS 中台建表建接口的权威参考）
└── data/             ← 🗂️ 本地模拟数据（当前用于替代 OS API 的 JSON 存根，联调后废弃）
```

---

## 2. OS 中台的核心交付物

OS 中台需要建设以下 **6 张表 + 6 个 REST API**，详见 [`contracts/os_api_spec.md`](contracts/os_api_spec.md)。

| 表名 | 对应模型文件 | 存什么 | 更新频率 |
|:---|:---|:---|:---|
| `os_ontology` | `schemas/ontology_model.py` | 设备物理信息（罐体体积、阀门型号等） | 静态 |
| `os_mechanism` | `schemas/mechanism_model.py` | 过程机理（自衡/积分、守恒约束等） | 静态 |
| `os_knowledge` | `schemas/knowledge_model.py` | 专家整定约束（PB 范围、最大超调等） | 静态 |
| `os_characterization` | `schemas/characterization_model.py` | 动态特征（振荡比、噪声、阀门状态等） | **按需计算**（整定触发时） |
| `os_data_mapping` | `schemas/data_model.py` | DCS 点位映射（PV/MV/SV 的 Tag 名） | 静态 |
| `os_metrics` | `schemas/metrics_model.py` | 控制绩效 KPI（自控率、综合评分等） | 按需/定期 |

---

## 3. 每个模型文件的字段解读

### 3.1 本体模型 `schemas/ontology_model.py`
描述**设备的物理实体**，类比 ERP 的设备台账。

主要字段：
- `device_id`：设备唯一标识（对应 DCS Tag 前缀，如 `2216_LIC_50104`）
- `loop_type`：回路类型（`level` / `flow` / `pressure` / `temperature`）
- `tank_volume_m3`：储罐体积（液位回路专属）
- `valve_cv_max`：阀门最大流量系数
- `valve_type`：阀门特性（`linear` / `equal_percentage`）

> **OS 中台操作**：从 ERP/设备台账系统同步，建 `os_ontology` 表并暴露 `GET /ontology/{device_id}` 接口。

---

### 3.2 机理模型 `schemas/mechanism_model.py`
描述**过程的物理规律**，决定算法选用哪种仿真模型。

三大维度：

#### 一、物理规则
- `process_nature`：`self_regulating`（自衡）或 `integrating`（积分，如液位）
- `process_gain_sign`：`+1` 正作用 / `-1` 反作用
- `dead_time_dominant`：是否为大纯滞后系统（温度回路通常为 `True`）
- `coupling_risk`：与其他回路的耦合程度（`none` / `low` / `medium` / `high`）
- `nonlinearity_type`：非线性类型（`valve_saturation` / `valve_nonlinear` / `process_nonlinear`）

#### 二、仿真模拟
- `preferred_simulation_model`：首选模型结构（`FOPDT` / `SOPDT` / `FO_INTEGRATOR`）
- `allowed_simulation_models`：允许的备选模型列表
- `typical_time_constant_range_s`：该回路典型时间常数范围（秒），用于辨识结果合理性校验
- `typical_dead_time_range_s`：典型纯滞后范围（秒）

#### 三、对象/约束建模
- `mass_balance_constrained`：是否受质量守恒约束（液位/流量/压力为 `True`）
- `energy_balance_constrained`：是否受能量守恒约束（温度为 `True`）
- `output_physical_bounds`：PV 的物理边界（不可超出的硬约束）
- `integrator_gain_range`：积分增益范围（液位回路专属）

四大回路标准机理摘要：

| 回路 | process_nature | 守恒约束 | dead_time_dominant | 首选模型 |
|:---|:---|:---|:---|:---|
| 液位 | integrating | 质量守恒 | ❌ | FO_INTEGRATOR |
| 流量 | self_regulating | 质量守恒 | ❌ | FOPDT |
| 压力 | self_regulating | 质量守恒 | ❌ | FOPDT |
| 温度 | self_regulating | 能量守恒 | ✅ | FOPDT/SOPDT |

> **OS 中台操作**：OS 按回路类型维护机理配置表，可从 `MechanismModel.for_loop_type()` 工厂方法直接导出初始数据。

---

### 3.3 知识图谱模型 `schemas/knowledge_model.py`
描述**专家整定约束**（人类工程师经验的结构化表达）。

- `pb_range`：允许的比例带范围 `[PB_min, PB_max]`（DCS 工程单位）
- `gain_range`：过程增益合理范围
- `td_enable`：是否允许使用微分项
- `max_overshoot_percent`：最大允许超调量（%）
- `tuning_strategy`：整定策略（`conservative` / `aggressive`）
- `historical_best_kp`：历史最佳 Kp（供算法初始化参考）

> **OS 中台操作**：由工艺工程师在 OS 知识管理模块维护，建 `os_knowledge` 表。

---

### 3.4 表征模型 `schemas/characterization_model.py`
描述**设备近期的动态运行状态**，是四个模型中**唯一需要实时计算的**。

三大子模型：

#### 信号表征 `SignalCharacteristics`
| 字段 | 含义 | 范围 |
|:---|:---|:---|
| `oscillation_ratio` | PV 振荡比例 | 0-1，越大越振荡 |
| `dominant_period_s` | 主振荡周期（秒） | 0 = 无振荡 |
| `noise_level` | 高频噪声强度 | 0-1 |
| `linearity_index` | 线性度 | 0-1，1 = 完全线性 |

#### 阀门表征 `ValveCharacteristics`
| 字段 | 含义 | 范围 |
|:---|:---|:---|
| `stiction_index_estimated` | 阀门卡涩指数 | 0-1 |
| `deadband_estimated` | 死区估计（%） | 0-100 |
| `reversal_error` | 回程误差 | 0-1 |

#### 控制绩效 `ControlPerformance`
| 字段 | 含义 | 来源 |
|:---|:---|:---|
| `performance_score_avg` | 综合评分 | 0-10，算法计算 |
| `auto_mode_time_ratio` | 自动模式占比 | **OS 从 DCS 历史统计** |
| `intervention_count_daily` | 日均人工干预次数 | **OS 从操作日志统计** |
| `recent_step_events` | 近期有效阶跃次数 | 算法计算 |

> **接口形态**：`GET /api/v1/characterization/{device_id}?hours=48`  
> 整定触发时调用，拉取最近 48 小时的 PV/MV 时序数据，在线计算后返回。  
> 计算逻辑详见 `features/feature_calculator.py`（零依赖纯 numpy 实现，可直接移植）。

---

### 3.5 数据映射模型 `schemas/data_model.py`
描述**DCS 点位到 OS 的数据采集映射**。

- `pv_tag` / `sv_tag` / `out_tag`：DCS 历史库中的 Tag 名称
- `db_source`：数据来源（`os_historian` / `dcs_direct`）
- `sample_interval_s`：采样周期（秒）

> **OS 中台操作**：与 DCS/实时数据库对接，建 `os_data_mapping` 表。

---

### 3.6 指标模型 `schemas/metrics_model.py`
描述**控制绩效 KPI 的计算结果**。

- `auto_mode_ratio`：自控率（%）
- `avg_abs_error`：平均绝对误差（工程单位）
- `performance_index`：综合绩效指数（0-10）

> **OS 中台操作**：由 OS 绩效评估服务定期或按需计算，建 `os_metrics` 表。

---

## 4. 接口调用时序（整定触发时）

```
用户/调度系统 触发整定
       │
       ▼
  PID Agent 启动
       │
       ├─── GET /ontology/{device_id}      → 获取 OntologyModel（设备物理信息）
       ├─── GET /mechanism/{loop_type}     → 获取 MechanismModel（过程机理）
       ├─── GET /knowledge/{loop_type}     → 获取 KnowledgeModel（整定约束）
       ├─── GET /characterization/{device_id}?hours=48  → 获取动态特征（实时计算）
       ├─── GET /data-mapping/{device_id}  → 获取 DCS 点位映射
       └─── GET /metrics/{device_id}       → 获取绩效 KPI（可选）
       │
       ▼
  整定算法运行（消费上述数据）
       │
       ▼
  返回 PID 参数
```

---

## 5. 当前阶段（联调前）

OS 中台接口尚未就绪时，PID Agent 通过 `data/` 目录下的本地 JSON 文件模拟 OS 数据：

```
data/
├── instance_models/    ← 模拟 ontology + data_mapping（按设备 ID 命名）
│   ├── 2216_LIC_50104.json
│   └── 2216_LIC_50108.json
└── standard_models/    ← 模拟 mechanism + knowledge（按回路类型命名）
    ├── level.json
    ├── flow.json
    ├── pressure.json
    └── temperature.json
```

**迁移方式**：OS 中台接口就绪后，只需修改 `provider/semantic_provider.py` 中的  
`_load_instance_json()` / `_load_standard_json()` 两个函数，将文件读取替换为 `requests.get()` 调用，上层算法零改动。

---

## 6. 特征计算交付（characterization 接口实现指南）

`features/feature_calculator.py` 是交付给 OS 中台的**参考实现**：

- 零依赖（仅 numpy），可直接移植到任何 Python 微服务
- 主入口：`calculate_characterization(device_id, pv, mv, timestamps)`
- 各特征函数独立，OS 中台可按需选用

```python
# OS 中台实现 characterization 接口的伪代码
@app.get("/api/v1/characterization/{device_id}")
def get_characterization(device_id: str, hours: int = 48):
    pv, mv, ts = historian.query(device_id, hours=hours)
    result = calculate_characterization(device_id, pv, mv, ts)
    return result.to_dict()  # 或直接用 calculate_characterization_as_dict()
```

---

## 7. 联系方式

| 角色 | 职责 |
|:---|:---|
| PID Agent 侧 | 算法逻辑、模型字段定义、characterization 计算逻辑 |
| OS 中台侧 | 建表、REST API 实现、DCS 历史数据接入、auto_mode_ratio 统计 |

**权威文档**：[`contracts/os_api_spec.md`](contracts/os_api_spec.md)（表结构 + 接口规范）  
**接口契约**：[`contracts/api_contract_sample.json`](contracts/api_contract_sample.json)（请求/响应示例）
