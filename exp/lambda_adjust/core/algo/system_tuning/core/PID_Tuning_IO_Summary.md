# PID整定算法 - 输入输出汇总表

## 概览

| 步骤 | 模块 | 主要函数 | 输入 | 输出 |
|-----|------|---------|------|------|
| 0 | DataQualityChecker | assess_data_quality() | pv[], mv[], t[] | quality_report |
| 1 | DataAnalyzer | detect_setpoint_changes() | sv[], threshold | segments[] |
| 2 | SystemTuningLogic | check_segment_steady_state() | segment_data | is_steady, info |
| 3 | DataPreprocessor | detect_control_scenario() | pv[], mv[], t[] | scenario |
| 4 | DataPreprocessor | preprocess_xxx_data() | t[], pv[], mv[] | t_proc[], pv_proc[], mv_proc[] |
| 5 | DataPreprocessor | detect_model_type() | t[], pv[], mv[], scenario | model_type |
| 6 | ModelIdentifier | identify_xxx() | t[], pv[], mv[], sv[], current_pid | K, T, L |
| 7 | DataPreprocessor | detect_control_mode() | pv[], mv[], noise_level | mode |
| 8 | PIDTuner | lambda_tuning() | K, T, L, mode, scenario | pb, ti, td |
| 9 | ParameterValidator | validate_pid_params() | pb, ti, td, model, scenario | validation_result |
| 10 | PIDEvaluator | evaluate() | t[], pv[], sv[], mv[], pid | evaluation_result |

---

## 详细说明

### Step 0: 数据质量检查

**模块**: `utils/data_quality.py` - `DataQualityChecker`

**函数**: `assess_data_quality(pv, mv, t, min_length=50)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | pv | np.array | 过程变量数组 |
| 输入 | mv | np.array | 操作变量数组 |
| 输入 | t | np.array | 时间数组 |
| 输入 | min_length | int | 最小数据长度(默认50) |
| **输出** | is_acceptable | bool | 数据是否可接受 |
| **输出** | score | float | 质量评分(0-100) |
| **输出** | issues | list[str] | 严重问题列表 |
| **输出** | warnings | list[str] | 警告列表 |

**检查项**:
1. 数据长度 >= min_length
2. PV有变化 (std > 0.001)
3. MV有变化 (std > 0.001)
4. 无NaN值
5. 无Inf值
6. 信噪比合理
7. 采样间隔一致
8. 数据范围合理

---

### Step 1: 设定值变化检测

**模块**: `data/analyzer.py` - `DataAnalyzer`

**函数**: `detect_setpoint_changes(sv_array, threshold=0.5)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | sv_array | np.array | 设定值数组 |
| 输入 | threshold | float | 变化检测阈值 |
| **输出** | change_indices | list[int] | 变化点索引列表 |
| **输出** | segments | list[tuple] | 分段列表 [(start, end, sv_value), ...] |

---

### Step 2: 稳态检查

**模块**: `tuning/logic.py` - `SystemTuningLogic`

**函数**: `check_segment_steady_state(segment_data, threshold)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | segment_data | dict | 段数据 {t, pv, mv, sv} |
| 输入 | threshold | float | 稳态判断阈值 |
| **输出** | is_steady | bool | 是否稳态 |
| **输出** | mean | float | PV均值 |
| **输出** | std | float | PV标准差 |
| **输出** | cv | float | 变异系数 |
| **输出** | oscillation_count | int | 振荡次数 |
| **输出** | non_steady_segments | list | 非稳态段列表 |

**内部调用**:
- `DataAnalyzer.is_setpoint_changing()`
- `DataAnalyzer.is_steady_state()`
- `StabilityDetector.is_steady_state()`
- `_check_oscillation()`

---

### Step 3: 控制场景检测

**模块**: `data/preprocessor.py` - `DataPreprocessor`

**函数**: `detect_control_scenario(pv, mv, t)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | pv | np.array | 过程变量数组 |
| 输入 | mv | np.array | 操作变量数组 |
| 输入 | t | np.array | 时间数组 |
| **输出** | scenario | str | 场景类型: "temperature" / "level" / "flow" |

**判断依据**:
- **temperature**: 响应慢(T > 30s)，PV范围大
- **level**: 积分特性明显，PV波动适中
- **flow**: 响应快(T < 10s)，PV跟随MV紧密

---

### Step 4: 数据预处理

**模块**: `data/preprocessor.py` - `DataPreprocessor`

#### 温控预处理
**函数**: `preprocess_temperature_data(t, pv, mv)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | t | np.array | 时间数组 |
| 输入 | pv | np.array | 过程变量数组 |
| 输入 | mv | np.array | 操作变量数组 |
| **输出** | t_proc | np.array | 处理后时间 |
| **输出** | pv_proc | np.array | 处理后PV |
| **输出** | mv_proc | np.array | 处理后MV |

**处理步骤**: 去瞬态、移动平均平滑

#### 液位预处理
**函数**: `preprocess_level_data(t, pv, mv)`

**处理步骤**: 去异常值、低通滤波、去周期波动

---

### Step 5: 模型类型检测

**模块**: `data/preprocessor.py` - `DataPreprocessor`

**函数**: `detect_model_type(t, pv, mv, scenario)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | t | np.array | 时间数组(预处理后) |
| 输入 | pv | np.array | 过程变量(预处理后) |
| 输入 | mv | np.array | 操作变量(预处理后) |
| 输入 | scenario | str | 控制场景 |
| **输出** | model_type | str | 模型类型 |

**模型类型**:
| 类型 | 说明 | 传递函数 |
|-----|------|---------|
| fopdt | 一阶加纯滞后 | G(s) = K·e^(-Ls)/(Ts+1) |
| first_order | 一阶系统 | G(s) = K/(Ts+1) |
| second_order | 二阶系统 | G(s) = K·e^(-Ls)/[(T1s+1)(T2s+1)] |
| integral_delay | 积分加延迟 | G(s) = K·e^(-Ls)/s |
| fopdt_with_heat_loss | 带热损失FOPDT | 含热损失修正项 |

---

### Step 6: 模型参数辨识

**模块**: `model/identifier.py` - `ModelIdentifier`

**函数**: `identify_fopdt(t, pv, mv, sv=None, current_pid=None)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | t | np.array | 时间数组 |
| 输入 | pv | np.array | 过程变量数组 |
| 输入 | mv | np.array | 操作变量数组 |
| 输入 | sv | np.array/float | 设定值(可选,用于闭环辨识) |
| 输入 | current_pid | dict | 当前PID参数(可选) |
| **输出** | K | float | 系统增益 |
| **输出** | T | float | 时间常数(秒) |
| **输出** | L | float | 纯滞后时间(秒) |
| **输出** | fit_error | float | 拟合误差 |

**辨识流程**:
1. `estimate_initial_guess_from_operational_data()` - 初始估计
   - `_estimate_lag_from_correlation()` - 互相关估计滞后
   - `_estimate_gain_from_correlation()` - 增益估计
   - `_estimate_time_constant_from_response_speed()` - 时间常数估计
2. `scipy.optimize.least_squares()` - 非线性优化
3. 参数边界约束

**其他辨识函数**:
- `identify_second_order()` → {K, T1, T2, L}
- `identify_integral_delay()` → {K, L}
- `identify_fopdt_with_heat_loss()` → {K, T, L, heat_loss}

---

### Step 7: 控制模式检测

**模块**: `data/preprocessor.py` - `DataPreprocessor`

**函数**: `detect_control_mode(pv, mv, noise_level=None, disturbance_freq=None)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | pv | np.array | 过程变量数组 |
| 输入 | mv | np.array | 操作变量数组 |
| 输入 | noise_level | float | 噪声水平(可选) |
| 输入 | disturbance_freq | float | 扰动频率(可选) |
| **输出** | mode | Mode | 控制模式枚举 |

**控制模式**:
| 模式 | 说明 | 特征 |
|-----|------|------|
| STANDARD | 标准模式 | 噪声低，扰动少 |
| ANTI_NOISE | 抗噪声模式 | 高频噪声明显 |
| ANTI_DISTURBANCE | 抗扰动模式 | 频繁外部扰动 |

---

### Step 8: PID参数整定

**模块**: `pid/tuner.py` - `PIDTuner`

**函数**: `lambda_tuning(K, T, L, mode=STANDARD, lambda_factor=0.8)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | K | float | 系统增益 |
| 输入 | T | float | 时间常数 |
| 输入 | L | float | 纯滞后时间 |
| 输入 | mode | Mode | 控制模式 |
| 输入 | lambda_factor | float | λ因子(默认0.8) |
| **输出** | pb | float | 比例带(%) |
| **输出** | ti | float | 积分时间(秒) |
| **输出** | td | float | 微分时间(秒) |

**Lambda整定公式**:
```
λ = lambda_factor × T
Kp = (T + L/2) / (K × (λ + L/2))
Ti = T + L/2
Td = (T × L) / (2T + L)
Pb = 100 / Kp
```

**场景特定整定函数**:
- `lambda_tuning_for_temperature_control()` - 温控专用
- `lambda_tuning_for_level_control()` - 液位专用
- `lambda_tuning_for_flow()` - 流量专用
- `cohen_coon_tuning()` - Cohen-Coon方法

---

### Step 9: 参数验证

**模块**: `utils/parameter_validator.py` - `ParameterValidator`

**函数**: `validate_pid_params(pb, ti, td, model_params=None, scenario=None)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | pb | float | 比例带(%) |
| 输入 | ti | float | 积分时间(秒) |
| 输入 | td | float | 微分时间(秒) |
| 输入 | model_params | dict | 模型参数{K, T, L}(可选) |
| 输入 | scenario | str | 控制场景(可选) |
| **输出** | is_valid | bool | 是否有效 |
| **输出** | quality_score | float | 质量评分(0-100) |
| **输出** | warnings | list[str] | 警告列表 |
| **输出** | suggestions | list[str] | 建议列表 |

**验证层级**:
1. **基本范围检查**: 10 < pb < 500, ti > 0, td >= 0
2. **参数比例关系**: ti > td
3. **特殊组合检查**: td/ti < 0.5
4. **场景特定检查**: 根据场景调整允许范围
5. **模型参数检查**: 与K, T, L的一致性

---

### Step 10: 性能评估

**模块**: `pid/evaluator.py` - `PIDEvaluator`

**函数**: `evaluate(t, pv, sv, mv, pid_params)`

| 参数类型 | 参数名 | 数据类型 | 说明 |
|---------|--------|---------|------|
| 输入 | t | np.array | 时间数组 |
| 输入 | pv | np.array | 实际过程变量 |
| 输入 | sv | np.array/float | 设定值 |
| 输入 | mv | np.array | 控制输出 |
| 输入 | pid_params | dict | PID参数{pb, ti, td} |
| **输出** | iae | float | 积分绝对误差 |
| **输出** | ise | float | 积分平方误差 |
| **输出** | itae | float | 积分时间绝对误差 |
| **输出** | settling_time | float | 稳定时间(秒) |
| **输出** | overshoot | float | 超调量(%) |
| **输出** | oscillation_count | int | 振荡次数 |
| **输出** | steady_state_error | float | 稳态误差 |
| **输出** | control_smoothness | float | 控制平滑度 |
| **输出** | overall_score | float | 综合评分(0-100) |
| **输出** | grade | str | 等级: A/B/C/D/F |

---

## 最终输出结构

```python
{
    # PID参数
    "pb": 121.2,              # 比例带(%)
    "ti": 62.5,               # 积分时间(秒)
    "td": 2.4,                # 微分时间(秒)
    
    # 模型信息
    "model_type": "fopdt",
    "model_params": {
        "K": 1.5,             # 系统增益
        "T": 60.0,            # 时间常数
        "L": 5.0              # 纯滞后时间
    },
    
    # 检测结果
    "scenario": "temperature",
    "mode": "STANDARD",
    "tuning_method": "LAMBDA",
    
    # 验证结果
    "validation": {
        "is_valid": True,
        "quality_score": 92,
        "warnings": [],
        "suggestions": []
    },
    
    # 性能评估
    "evaluation": {
        "iae": 150.3,
        "settling_time": 180,
        "overshoot": 5.2,
        "overall_score": 85,
        "grade": "B"
    },
    
    # 分段信息
    "segment_info": {
        "total_segments": 3,
        "tuned_segments": [1, 2],
        "segment_results": [...]
    },
    
    # 数据质量
    "quality_report": {
        "is_acceptable": True,
        "score": 88,
        "issues": [],
        "warnings": []
    }
}
```

---

## PlantUML图表文件

本目录包含以下PlantUML文件，可在 [PlantUML Online](http://www.plantuml.com/plantuml/uml/) 查看:

1. **PID_Tuning_Flow.puml** - 完整流程活动图(含泳道和输入输出)
2. **PID_Tuning_Components.puml** - 组件交互图
3. **PID_Tuning_Sequence.puml** - 详细时序图

使用方法:
1. 打开 http://www.plantuml.com/plantuml/uml/
2. 复制对应.puml文件内容
3. 粘贴到编辑区即可查看
