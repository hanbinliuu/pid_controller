# 配置参数完整参考手册 (Config Parameters Reference)

本文档详细列出了 `core/algorithm/model_type/config/` 目录下所有配置参数的名称、默认值、含义及调优建议。

所有配置通过统一的 `Config` 类对外暴露，使用方式：`Config.OSCILLATION_TUNING['pb_min']`。

---

## 目录

1. [OSCILLATION_TUNING — 振荡整定配置](#1-oscillation_tuning--振荡整定配置)
2. [SIMC_TUNING — SIMC 整定配置](#2-simc_tuning--simc-整定配置)
3. [MODEL_BOUNDS — 模型参数边界](#3-model_bounds--模型参数边界)
4. [MODEL_FITTING — 模型拟合配置](#4-model_fitting--模型拟合配置)
5. [CLOSED_LOOP — 闭环稳定性配置](#5-closed_loop--闭环稳定性配置)
6. [LOOP_SPECIFIC_VERIFICATION — 回路特定验证配置](#6-loop_specific_verification--回路特定验证配置)
7. [PID_CONSTRAINTS — PID 参数约束](#7-pid_constraints--pid-参数约束)
8. [OPTIMIZATION — 优化配置](#8-optimization--优化配置)
9. [PARAMETER_CONSTRAINTS — 参数约束](#9-parameter_constraints--参数约束)
10. [NONLINEAR_FITTING — 非线性拟合配置](#10-nonlinear_fitting--非线性拟合配置)
11. [TUNING_DEFAULTS — 整定默认参数](#11-tuning_defaults--整定默认参数)
12. [MODEL_SELECTOR — 模型选择器配置](#12-model_selector--模型选择器配置)
13. [ROBUST_TUNING — 鲁棒整定配置](#13-robust_tuning--鲁棒整定配置)
14. [SEGMENT_PROCESSING — 段处理配置](#14-segment_processing--段处理配置)
15. [TUNING_SEGMENT — 整定段检测配置](#15-tuning_segment--整定段检测配置)
16. [PREPROCESSING — 数据预处理配置](#16-preprocessing--数据预处理配置)
17. [LOOP_TYPE_PRESETS — 回路类型预设](#17-loop_type_presets--回路类型预设)
18. [ModelType — 模型类型枚举](#18-modeltype--模型类型枚举)

---

## 1. OSCILLATION_TUNING — 振荡整定配置

> **文件**: `config/oscillation.py`
> **用途**: 控制振荡整定路径的所有行为参数

### 1.1 LLM 与触发条件

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `enable_llm` | `False` | 是否启用 LLM 辅助决策保守策略 |
| `oscillation_ratio_threshold` | `0.08` | 振荡比阈值，超过此值可能触发振荡路径 |
| `r2_failure_threshold` | `0.35` | R² 低于此值判定模型辨识失败 |

### 1.2 弱振荡检测

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `weak_oscillation_detection` | `True` | 启用弱振荡检测 |
| `weak_osc_fft_threshold` | `0.15` | FFT 主频能量占比阈值 |
| `weak_osc_envelope_threshold` | `0.3` | 包络比阈值 |
| `weak_osc_combined_threshold` | `0.2` | 综合振荡得分阈值 |

### 1.3 振荡周期与仿真

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `period_min` | `1.0` | 最小振荡周期（秒） |
| `period_max` | `300.0` | 最大振荡周期（秒） |
| `sp_initial` | `50.0` | 闭环仿真设定值初始值 |
| `sp_final` | `60.0` | 闭环仿真设定值最终值 |
| `pv_initial` | `50.0` | 过程值初始值 |

### 1.4 Ku/K 增益判定

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `ku_k_ratio_high` | `20.0` | Ku/K 超过此值认为临界增益相对过大 |
| `ku_k_ratio_low` | `0.5` | Ku/K 低于此值认为临界增益相对过小 |
| `low_gain_threshold` | `0.05` | 低增益绝对阈值（兜底） |
| `ku_high_threshold` | `50.0` | Ku 绝对上限 |
| `ku_low_threshold` | `0.1` | Ku 绝对下限 |

### 1.5 基础 PB 计算

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `pb_from_k_factor` | `1.0` | 基于 K 计算 PB 的系数 |
| `kp_from_ku_factor` | `0.45` | 基于 Ku 计算 Kp 的系数（Z-N 法标准值） |

### 1.6 慢系统调整

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `slow_system_pu_thresholds` | `[30.0, 15.0]` | Pu（临界周期）阈值分界 |
| `slow_system_factors` | `[1.15, 1.05, 1.0]` | 对应各 Pu 区间的保守因子 |
| `high_gain_extra_factor` | `1.05` | Ku 过大时额外保守系数 |

### 1.7 数据质量 / 非线性调整

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `quality_adjustment_threshold` | `0.5` | 数据质量低于此值开始调整 PB |
| `quality_adjustment_factor` | `0.6` | 质量调整系数 |
| `nonlinearity_threshold` | `0.5` | 非线性超过此值开始调整 PB |
| `nonlinearity_factor` | `0.4` | 非线性调整系数 |

### 1.8 阀门问题补偿

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `valve_deadband_factor` | `1.15` | 检测到死区时 PB 乘以此因子 |
| `valve_stiction_factor` | `1.2` | 检测到粘滞时 PB 乘以此因子 |
| `valve_saturation_factor` | `1.1` | 检测到饱和时 PB 乘以此因子 |

### 1.9 振荡比自适应安全系数

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `safety_factor_base` | `1.0` | 基础安全系数（osc < 0.5 时） |
| `safety_factor_thresholds` | `[0.5, 0.7, 0.85]` | 振荡比分段阈值 |
| `safety_factor_slopes` | `[0.2, 0.4, 0.8]` | 各分段区间的安全系数增长斜率 |
| `max_multiplier_normal` | `1.6` | 正常振荡时总乘数上限 |
| `max_multiplier_high_osc` | `2.0` | 高振荡（>0.85）时总乘数上限 |

### 1.10 自适应整定

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `pb_gradient` | `0.6` | PB 渐进系数 |
| `pb_oscillation_start` | `0.4` | 开始渐进调整的振荡比阈值 |

### 1.11 自适应微分

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `enable_adaptive_derivative` | `True` | 是否启用自适应微分 |
| `derivative_factor` | `0.25` | Kd = Kp × Pu × derivative_factor |
| `derivative_oscillation_threshold` | `0.5` | 振荡比超过此值才加微分 |
| `td_base_divisor` | `12.0` | Td 基础计算: Pu / td_base_divisor |
| `td_multiplier_factor` | `1.5` | Td 乘数系数 |
| `td_range` | `[0.3, 3.0]` | Td 允许范围（秒） |

### 1.12 自适应 Ti

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `ti_osc_start` | `0.5` | Ti 振荡调整开始阈值 |
| `ti_osc_factor` | `0.8` | Ti 振荡调整系数 |
| `ti_slow_pu_thresholds` | `[30.0, 15.0]` | Ti 慢系统 Pu 阈值 |
| `ti_slow_factors` | `[1.25, 1.12, 1.0]` | Ti 慢系统乘数 |
| `ti_range` | `[1.5, 600.0]` | Ti 最终允许范围（秒） |
| `ti_min_base` | `1.5` | Ti 基础最小值 |

### 1.13 液位回路专用配置

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `level_ti_multiplier` | `2.2` | 液位回路 Ti 基础乘数 |
| `level_integrating_ti_max` | `3.5` | 积分过程 Ti 乘数上限 |
| `level_integrating_t1_threshold` | `50.0` | 积分过程 T1 识别阈值 |
| `level_gain_threshold` | `1.2` | 液位高增益阈值 |
| `level_very_high_gain_threshold` | `2.5` | 液位极高增益阈值 |
| `level_slow_system_pu` | `50.0` | 液位慢系统 Pu 阈值 |
| `level_mid_gain_range` | `[1.0, 2.2]` | 液位中等增益范围 |
| `level_mid_gain_factor` | `0.18` | 中等增益 PB 调整系数 |
| `level_large_t1_threshold` | `40.0` | 大时间常数阈值 |
| `level_large_t1_factor` | `100.0` | 大 T1 PB 调整除数 |
| `level_pb_boost_factor` | `1.4` | 液位回路 PB 额外保守因子 |
| `level_kd_enable_threshold` | `0.6` | 液位回路启用微分的振荡阈值 |
| `level_fallback_pb` | `250.0` | 液位回路 fallback 默认 PB |
| `level_fallback_ti_factor` | `2.5` | 液位回路 fallback Ti 乘数 |

### 1.14 PB 范围

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `pb_min` | `60.0` | PB 全局下限 (%) |
| `pb_max` | `450.0` | PB 全局上限 (%) |
| `pb_max_large_delay` | `600.0` | 大滞后系统 PB 上限 (%) |

### 1.15 大滞后系统配置

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `large_delay_ratio_threshold` | `0.5` | L/T1 大滞后判定阈值 |
| `large_delay_lambda_factor` | `2.5` | 大滞后时 Lambda 因子 |
| `large_delay_pb_boost` | `1.5` | 大滞后时 PB 额外增益 |
| `large_delay_ti_boost` | `1.5` | 大滞后时 Ti 额外增益 |
| `extreme_delay_ratio_threshold` | `0.8` | 极大滞后 L/T1 阈值 |
| `extreme_delay_pb_boost` | `2.0` | 极大滞后 PB 增益 |
| `large_delay_absolute_threshold` | `15.0` | 绝对滞后时间阈值（秒） |

### 1.16 极慢系统配置

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `very_slow_system_t1_threshold` | `100.0` | 极慢系统 T1 阈值（秒） |
| `very_slow_system_pu_threshold` | `100.0` | 极慢系统 Pu 阈值（秒） |
| `very_slow_sim_duration_factor` | `12.0` | 极慢系统仿真时长因子 |
| `very_slow_max_sim_duration` | `3600.0` | 极慢系统最大仿真时长（秒） |

### 1.17 回路仿真时长因子

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `level_sim_duration_factor` | `10.0` | 液位回路仿真时长因子 |
| `temperature_sim_duration_factor` | `8.0` | 温度回路仿真时长因子 |
| `default_sim_duration_factor` | `6.0` | 默认仿真时长因子 |

### 1.18 时变特性 / 动态调整 / 负 K 校正

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `time_varying_detection` | `True` | 是否启用时变特性检测 |
| `high_gain_gradient_threshold` | `3.0` | 高增益梯度阈值 |
| `high_gain_gradient_pb_factor` | `1.3` | 高增益梯度时 PB 保守因子 |
| `time_varying_ti_boost` | `1.2` | 时变系统 Ti 增益 |
| `pb_k_adjustment_factor` | `0.3` | PB 下限动态调整系数 |
| `ku_k_extreme_pb_factor` | `1.5` | Ku/K 异常时 PB 下限乘数 |
| `critical_method_safety_factor` | `1.2` | 临界法额外安全系数 |
| `negative_k_oscillation_threshold` | `0.3` | 负 K 检查的中等震荡阈值 |
| `negative_k_severe_threshold` | `0.5` | 负 K 强制取 abs 的震荡阈值 |

---

## 2. SIMC_TUNING — SIMC 整定配置

> **文件**: `config/simc.py`
> **用途**: Skogestad Internal Model Control 整定方法参数

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `enable` | `True` | 启用 SIMC 整定 |
| `tau_c_factor` | `1.8` | 闭环时间常数 τc = T1 × 1.8 |
| `tau_c_min_factor` | `1.8` | τc 下限: τc ≥ L × 1.8 |
| `integrating_tau_c_factor` | `3.0` | 积分过程: τc = L × 3.0 |
| `ti_limit_factor` | `10.0` | Ti 上限: Ti ≤ 10 × (τc + L) |
| `use_half_rule` | `True` | 二阶系统使用 SIMC 半规则 |

### 回路类型→整定方法映射

| 回路类型 | 使用 SIMC? | 说明 |
|----------|-----------|------|
| `flow` | ✅ True | 快速/积分过程 |
| `level` | ✅ True | 积分过程 |
| `pressure` | ❌ False | 需要微分，用 Lambda |
| `temperature` | ❌ False | 慢速系统，用 Lambda |
| `default` | ✅ True | 未知类型默认 SIMC |

---

## 3. MODEL_BOUNDS — 模型参数边界

> **文件**: `config/model_bounds.py`
> **用途**: 各模型参数的搜索范围（initial）、扩展范围（retry）和输出钳制（clip）

| 模型 | 参数 | initial 范围 | clip 范围 |
|------|------|-------------|-----------|
| **FOPDT** | K, T1, L | [-10,10], [1,500], [0,50] | (-10,10), (1,500), (0,50) |
| **FO** | K, T1 | [-10,10], [1,500] | (-10,10), (1,500) |
| **SO** | K, T1, T2 | [-10,10], [0.5,500], [0.5,500] | (-10,10), (0.5,500), (0.5,500) |
| **SOPDT** | K, T1, T2, L | [-10,10], [0.5,500], [0.5,500], [0,50] | (-10,10), (0.5,500), (0.5,500), (0,50) |
| **FO_INTEGRATOR** | K, L | [-10,10], [0,50] | (-10,10), (0,50) |
| **SO_INTEGRATOR** | K, T1, T2 | [-10,10], [0.5,500], [0.5,500] | (-10,10), (0.5,500), (0.5,500) |
| **HAMMERSTEIN** | K,T1,L,a1,a2,a3 | [-10,10],[1,500],[0,50],[0.5,2],[-0.5,0.5],[0,0.5] | 同 initial |
| **DEADBAND_FOPDT** | K,T1,L,deadband | [-10,10],[1,500],[0,50],[0.5,20] | 同 initial |
| **SAT_FOPDT** | K,T1,L,sat_low,sat_high | [-10,10],[1,500],[0,50],[0,50],[100,100] | 同 initial |

> **注意**: K 允许负值以支持反向作用系统（如制冷、减压）。

---

## 4. MODEL_FITTING — 模型拟合配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `r2_good_threshold` | `0.8` | R² 良好阈值 |
| `r2_acceptable_threshold` | `0.5` | R² 可接受阈值 |
| `r2_poor_threshold` | `0.3` | R² 较差阈值 |
| `k_min` | `0.001` | K 最小有效值 |
| `k_max` | `50.0` | K 最大合理值 |

---

## 5. CLOSED_LOOP — 闭环稳定性配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `settling_threshold` | `0.02` | 稳态误差带（2%） |
| `max_settling_time` | `900.0` | 最大调节时间（秒） |
| `overshoot_good` | `10.0` | 良好超调量（%） |
| `overshoot_acceptable` | `50.0` | 最大允许超调量（%） |
| `rise_time_min` | `1.0` | 理想上升时间下限（秒） |
| `rise_time_max` | `10.0` | 理想上升时间上限（秒） |
| `oscillation_count_ideal` | `4` | 理想振荡次数上限 |
| `min_r2_confidence` | `0.6` | 最低 R² 置信度（低于此值跳过严格验证） |

---

## 6. LOOP_SPECIFIC_VERIFICATION — 回路特定验证配置

> **文件**: `config/tuning.py`

| 回路类型 | `max_settling_time_factor` | `overshoot_acceptable` | `steady_state_error` |
|----------|---------------------------|----------------------|---------------------|
| **temperature** | 20.0 × T | 40.0% (防热冲击) | 5.0% |
| **level** | 15.0 × T | 50.0% | 10.0% (积分特性) |
| **flow** | 10.0 × T | 50.0% | 5.0% |
| **pressure** | 10.0 × T | 50.0% | 5.0% |

---

## 7. PID_CONSTRAINTS — PID 参数约束

> **文件**: `config/tuning.py`

### 基础约束

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `kp_min` | `0.01` | Kp 最小绝对值 |
| `kp_max_from_pb` | `100.0` | Kp 上限计算基准 |
| `ti_min` | `0.1` | Ti 最小值（秒） |
| `ti_max` | `300.0` | Ti 最大值（秒） |
| `td_max_ratio` | `0.25` | Td 最大比例（相对 Ti） |

### Fallback 参数

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `fallback_kp` | `1.0` | 整定失败时的默认 Kp |
| `fallback_ti` | `20.0` | 整定失败时的默认 Ti |
| `fallback_td` | `0.0` | 整定失败时的默认 Td |

### 非线性补偿因子

| 模型类型 | 补偿因子 | 说明 |
|----------|---------|------|
| `default` | `1.3` | 默认非线性补偿 |
| `HAMMERSTEIN` | `1.4` | Hammerstein 模型 |
| `DEADBAND_FOPDT` | `1.3` | 死区模型 |
| `SAT_FOPDT` | `1.3` | 饱和模型 |

### 死区补偿

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `ti_reduction_factor` | `0.7` | Ti 缩减系数（加快积分消除稳态偏差） |
| `ki_boost_factor` | `1.3` | Ki 增强系数 |
| `enable` | `True` | 是否启用 |

### 阀门补偿

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `osc_threshold_high` | `0.5` | 高振荡阈值 |
| `osc_threshold_med` | `0.6` | 中振荡阈值 |
| `r2_threshold` | `0.85` | R² 阈值 |
| `factor_high_base` | `1.3` | 高振荡+低R²基础因子 |
| `factor_high_slope` | `0.6` | 高振荡+低R²斜率 |
| `factor_med_base` | `1.2` | 中振荡基础因子 |
| `factor_med_slope` | `0.5` | 中振荡斜率 |

---

## 8. OPTIMIZATION — 优化配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `r2_threshold` | `0.85` | 触发优化的 R² 阈值 |
| `min_segment_r2` | `0.3` | 最小段 R² 阈值 |
| `segment_r2_std_max` | `0.25` | 段 R² 标准差上限 |
| `k_magnitude_ratio_max` | `3.0` | K 值变化幅度上限（倍） |
| `k_sign_check` | `True` | 是否检查 K 值符号反转 |
| `amplitude_ratio_min` | `0.3` | 幅度比下限 |
| `amplitude_ratio_max` | `3.0` | 幅度比上限 |

---

## 9. PARAMETER_CONSTRAINTS — 参数约束

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `T1_max` | `30.0` | T1 最大值限制 |
| `L_max` | `10.0` | L（纯滞后）最大值限制 |
| `k_reasonable_min` | `0.01` | K 合理性检查下限 |

---

## 10. NONLINEAR_FITTING — 非线性拟合配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `enable` | `True` | 是否启用非线性模型拟合 |
| `nonlinearity_threshold` | `0.4` | 非线性度超过此值尝试非线性模型 |
| `r2_improvement_threshold` | `0.1` | R² 提升需达到此值才选用非线性模型 |
| `deadband_detection_threshold` | `0.3` | 死区检测阈值 |
| `saturation_detection_threshold` | `0.2` | 饱和检测阈值 |
| `max_polynomial_order` | `3` | Hammerstein 多项式最高阶数 |

---

## 11. TUNING_DEFAULTS — 整定默认参数

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `lambda_factor` | `0.8` | Lambda 整定系数 |
| `enable_downsample` | `True` | 是否启用智能降采样 |
| `downsample_target` | `1000` | 降采样目标点数 |

---

## 12. MODEL_SELECTOR — 模型选择器配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `min_r2_for_vote` | `0.3` | 模型投票最低 R² |
| `min_r2_for_quality` | `0.4` | 质量筛选最低 R² |
| `r2_thresholds` | `[0.5, 0.3, 0.15, 0.0]` | R² 分级阈值 |
| `sim_r2_poor_threshold` | `0.5` | 仿真 R² 较差阈值 |
| `sim_r2_fail_threshold` | `0.1` | 仿真 R² 失败阈值 |
| `oscillation_poor_threshold` | `0.4` | 振荡较差阈值 |
| `amplitude_ratio_min/max` | `0.5/2.0` | 幅度比较差区间 |
| `amplitude_ratio_fail_min/max` | `0.3/3.0` | 幅度比失败区间 |
| `default_sp_initial` | `50.0` | 默认 SP 初始值 |
| `default_sp_final` | `60.0` | 默认 SP 终值 |
| `min_sp_change` | `5.0` | 最小 SP 变化量 |
| `quality_excellent_r2` | `0.85` | 优秀 R² 阈值 |
| `quality_good_r2` | `0.7` | 良好 R² 阈值 |
| `quality_acceptable_r2` | `0.5` | 一般 R² 阈值 |

---

## 13. ROBUST_TUNING — 鲁棒整定配置

> **文件**: `config/tuning.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `r2_robust_threshold` | `0.6` | 低于此 R² 触发指数级保守惩罚 |
| `min_pb_flow` | `50.0` | 流量回路最低 PB 保护 |
| `min_pb_temp` | `100.0` | 温度回路最低 PB 保护 |
| `sign_mismatch_penalty` | `3.0` | 符号不匹配时保守等级乘数 |

---

## 14. SEGMENT_PROCESSING — 段处理配置

> **文件**: `config/preprocessing.py`

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `min_data_points` | `30` | 最小数据点数（不足则过滤） |
| `min_fusion_points` | `50` | 融合最小数据点数 |
| `min_fusion_points_high_quality` | `30` | 高质量段 (R²>0.8) 最小点数 |
| `min_pv_range` | `0.5` | 最小 PV 变化范围 |
| `min_mv_range` | `0.1` | 最小 MV 变化范围 |
| `correlation_threshold` | `0.1` | 相关性阈值 |
| `severe_nonlinearity` | `0.7` | 严重非线性阈值 |
| `severe_oscillation` | `0.75` | 严重振荡阈值 |
| `low_quality_threshold` | `0.25` | 低质量分阈值 |
| `merge_gap_threshold` | `300000` | 合并间隔阈值（ms），即 5 分钟 |
| `merge_expansion_max` | `5.0` | 最大扩展比上限 |
| `merge_expansion_allow` | `2.0` | 允许合并的扩展比上限 |
| `merge_quality_diff` | `0.3` | 质量差异阈值 |
| `merge_osc_diff` | `0.4` | 振荡差异阈值 |

---

## 15. TUNING_SEGMENT — 整定段检测配置

> **文件**: `config/preprocessing.py`

### MV 阶跃检测

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `min_step_size` | `1.0` | 最小 MV 阶跃幅度 |
| `stable_window` | `10` | 稳定窗口大小（采样点数） |
| `step_std_ratio` | `0.5` | 阶跃前 std 与阶跃幅度的比值上限 |

### 响应区间

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `min_response_time` | `30` | 最小响应时间（点数） |
| `max_response_time` | `3000` | 最大响应时间（点数） |

### PV 响应质量评估

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `min_pv_range` | `2.0` | PV 最小变化范围 |
| `min_pv_std` | `0.3` | PV 最小标准差 |
| `min_pv_change_ratio` | `0.05` | PV 最小变化比例 |
| `pv_change_ratio_good` | `0.1` | PV 变化比例良好阈值 |
| `trend_ratio_good` | `0.1` | 趋势比例良好阈值 |
| `settling_ratio_good` | `0.5` | 收敛比良好阈值 |
| `osc_ratio_good / acceptable` | `0.2 / 0.4` | 振荡比良好/可接受阈值 |
| `corr_good / acceptable` | `0.5 / 0.2` | 相关性良好/可接受阈值 |
| `quality_pass_threshold` | `0.6` | 质量评分通过阈值 |

### SV 阶跃段检测

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `sv_min_step_size` | `0.5` | SV 最小阶跃幅度 |
| `sv_stable_window` | `20` | SV 稳定窗口（点数） |
| `sv_pre_step_points` | `30` | 阶跃前需要的稳态点数 |
| `sv_closed_loop_t1_factor` | `3.0` | 闭环 T1 → 开环 T1 修正系数 |

---

## 16. PREPROCESSING — 数据预处理配置

> **文件**: `config/preprocessing.py`

### 基础参数

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `filter_window` | `5` | 滤波窗口大小 |
| `noise_threshold` | `0.02` | 噪声阈值 |
| `min_correlation` | `0.15` | 最小相关系数 |
| `outlier_factor` | `2.0` | 异常值因子（IQR 倍数） |
| `change_point_threshold` | `0.1` | MV 变化点检测阈值 |

### 自适应滤波

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| `enabled` | `True` | 是否启用自适应滤波 |
| `window_min / max / default` | `3 / 15 / 5` | 滤波窗口范围 |
| `oscillation_low / high` | `0.3 / 0.7` | 振荡程度阈值 |
| `noise_low / high` | `0.05 / 0.15` | 噪声程度阈值 |
| `preserve_step` | `True` | 是否保护阶跃边缘 |

### 滤波方法选择

| 振荡程度 | 滤波方法 |
|----------|---------|
| 低 (< 0.3) | `moving_average` |
| 中 (0.3~0.7) | `moving_average` |
| 高 (> 0.7) | `median`（抗脉冲干扰） |

### 质量评分权重

| 维度 | 权重 |
|------|------|
| 相关性 (correlation) | 0.25 |
| 噪声 (noise) | 0.20 |
| 趋势一致性 (trend) | 0.20 |
| 非线性惩罚 (nonlinearity) | 0.20 |
| 阶跃响应奖励 (step_response) | 0.15 |

### 质量等级

| 等级 | 阈值 |
|------|------|
| 良好 (good) | ≥ 0.7 |
| 中等 (medium) | ≥ 0.4 |
| 差 (poor) | < 0.4 |

---

## 17. LOOP_TYPE_PRESETS — 回路类型预设

> **文件**: `config/loop_presets.py`
> **用途**: 针对石化行业四种回路类型的差异化参数预设

| 参数 | Flow (流量) | Temperature (温度) | Level (液位) | Pressure (压力) | Default |
|------|------------|-------------------|-------------|-----------------|---------|
| `pb_min` | 60.0 | 80.0 | 100.0 | 80.0 | 60.0 |
| `pb_max` | 300.0 | 300.0 | 300.0 | 300.0 | 300.0 |
| `tau_c_factor` | 1.2 | 2.0 | 2.0 | 1.5 | 1.5 |
| `safety_factor` | 1.15 | 1.1 | 1.0 | 1.15 | 1.05 |
| `ti_multiplier` | 1.0 | 1.5 | 1.5 | 1.05 | 1.0 |
| `td_enable` | ❌ | ✅ | ❌ | ✅ | ❌ |
| `td_ratio` | — | 0.25 | — | 0.15 | — |
| `td_max` | — | 15.0s | — | 10.0s | — |
| `aggressive` | ✅ | ❌ | ❌ | ❌ | ❌ |
| `integrating_mode` | — | — | ✅ | — | — |

### 辅助函数

| 函数 | 说明 |
|------|------|
| `get_loop_preset(loop_type)` | 获取指定回路类型的参数预设字典 |
| `get_adjusted_pb_range(loop_type, base_min, base_max)` | 根据回路类型调整 PB 范围 |
| `get_adjusted_safety_factor(loop_type, base_factor)` | 根据回路类型调整安全系数 |

---

## 18. ModelType — 模型类型枚举

> **文件**: `config/types.py`

### 线性模型

| 枚举值 | 常量名 | 参数数 | 传递函数 |
|--------|--------|--------|----------|
| `FOPDT` | `ModelType.FOPDT` | 3 | $K/(T_1 s+1) \cdot e^{-Ls}$ |
| `FO` | `ModelType.FO` | 2 | $K/(T_1 s+1)$ |
| `SO` | `ModelType.SO` | 3 | $K/((T_1 s+1)(T_2 s+1))$ |
| `SOPDT` | `ModelType.SOPDT` | 4 | $K/((T_1 s+1)(T_2 s+1)) \cdot e^{-Ls}$ |
| `FO_INTEGRATOR` | `ModelType.FOPI` | 2 | $K/s \cdot 1/(T_1 s+1)$ |
| `SO_INTEGRATOR` | `ModelType.SOPI` | 3 | $K/s \cdot 1/((T_1 s+1)(T_2 s+1))$ |

### 非线性模型

| 枚举值 | 常量名 | 说明 |
|--------|--------|------|
| `HAMMERSTEIN` | `ModelType.HAMMERSTEIN` | 静态非线性 + 线性动态 |
| `DEADBAND_FOPDT` | `ModelType.DEADBAND_FOPDT` | 死区 + FOPDT |
| `SAT_FOPDT` | `ModelType.SATURATION_FOPDT` | 饱和 + FOPDT |

### 常量

| 常量 | 值 | 说明 |
|------|-----|------|
| `CANDIDATE_MODELS` | `[FOPDT, FO, SO, SOPDT, FOPI]` | 自动拟合时尝试的候选模型列表 |

---

## 调优指南 (Tuning Guide)

面对 200+ 个配置参数，实际需要关注的**核心可调参数只有约 15~20 个**。本指南按照**现场常见问题场景**分类，帮助工程师快速定位应该调整哪个参数。

> **黄金法则**：每次只调整 1~2 个参数，运行测试观察效果，避免多参数联动干扰判断。

---

### 🔴 场景一：整定结果导致现场振荡（PB 偏低 / Kp 偏大）

**症状**：下发 PID 参数后，PV 持续振荡不收敛，或者闭环仿真就已经不稳定。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 | 作用原理 |
|--------|---------|----------------|--------|---------|
| ⭐️1 | `pb_min` | 60 → **80~100** | `OSCILLATION_TUNING` | 直接抬高 PB 地板，防止算出过低的比例带 |
| ⭐️2 | `safety_factor_base` | 1.0 → **1.2~1.4** | `OSCILLATION_TUNING` | 全局安全系数，相当于给所有场景都加了一层保守缓冲 |
| 3 | `tau_c_factor` | 1.8 → **2.0~2.5** | `SIMC_TUNING` | 增大闭环时间常数，降低控制器增益 |
| 4 | 回路预设 `safety_factor` | 按回路类型 | `LOOP_TYPE_PRESETS` | 只针对特定回路加保守度（如 flow: 1.15→1.3） |

---

### 🟡 场景二：闭环仿真频繁判定"不稳定"（假阳性）

**症状**：算法日志显示 `is_stable=False`，但参数看起来合理（PB 已经很大）；或者对于慢系统，仿真时间不够导致未收敛。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 | 作用原理 |
|--------|---------|----------------|--------|---------|
| ⭐️1 | `max_settling_time` | 900 → **1200~1800** | `CLOSED_LOOP` | 放宽最大允许调节时间，解决慢系统"超时=不稳定"的误判 |
| ⭐️2 | `overshoot_acceptable` | 50 → **60~70** | `CLOSED_LOOP` | 放宽超调量限制（工业现场 30~50% 超调通常可接受） |
| 3 | `min_r2_confidence` | 0.6 → **0.4** | `CLOSED_LOOP` | R² 很差时直接跳过严格验证，避免用不可靠的模型做仿真然后报错 |
| 4 | 回路验证 `max_settling_time_factor` | 按回路类型 | `LOOP_SPECIFIC_VERIFICATION` | 如温度 20→30，液位 15→20 |

---

### 🟢 场景三：控制器响应太慢（PB 偏高 / Kp 偏小）

**症状**：参数太保守，PV 需要很长时间才能跟上 SV 变化，或者稳态偏差大。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 | 作用原理 |
|--------|---------|----------------|--------|---------|
| ⭐️1 | `pb_max` | 450 → **300~350** | `OSCILLATION_TUNING` | 降低 PB 天花板，不允许算出极度保守的参数 |
| ⭐️2 | 回路预设 `tau_c_factor` | 按回路类型 | `LOOP_TYPE_PRESETS` | 如 temperature: 2.0→1.5，加快响应 |
| 3 | `quality_adjustment_factor` | 0.6 → **0.3** | `OSCILLATION_TUNING` | 降低数据质量对PB的惩罚力度 |
| 4 | `max_multiplier_normal` | 1.6 → **1.3** | `OSCILLATION_TUNING` | 限制振荡比对PB的累计放大效应 |

---

### 🔵 场景四：特定回路类型效果不佳

#### 4a. 液位回路（Level）— 整定后超调大或收敛极慢

| 调整参数 | 当前值 → 建议值 | 配置块 |
|---------|----------------|--------|
| `level_ti_multiplier` | 2.2 → **2.5~3.0** | `OSCILLATION_TUNING` |
| `level_pb_boost_factor` | 1.4 → **1.6** | `OSCILLATION_TUNING` |
| `level.tau_c_factor` | 2.0 → **2.5** | `LOOP_TYPE_PRESETS` |
| `level.ti_multiplier` | 1.5 → **2.0** | `LOOP_TYPE_PRESETS` |

> **液位回路本质是积分过程**，Ti 不够大会导致积分饱和；PB 不够大会导致 MV 抖动伤阀门。

#### 4b. 温度回路（Temperature）— 仿真不收敛或响应极慢

| 调整参数 | 当前值 → 建议值 | 配置块 |
|---------|----------------|--------|
| `temperature_sim_duration_factor` | 8 → **10~15** | `OSCILLATION_TUNING` |
| `temperature.tau_c_factor` | 2.0 → **1.5**（加快）或 **2.5**（更稳） | `LOOP_TYPE_PRESETS` |
| `temperature.ti_multiplier` | 1.5 → **1.2**（加快响应） | `LOOP_TYPE_PRESETS` |
| `temperature.td_ratio` | 0.25 → **0.3**（增强提前预判） | `LOOP_TYPE_PRESETS` |

> **温度回路的大滞后使仿真需要远超常规的时长**，仿真时间因子不够大是最常见的"伪失败"根因。

#### 4c. 流量回路（Flow）— 整定后仍然抖动

| 调整参数 | 当前值 → 建议值 | 配置块 |
|---------|----------------|--------|
| `flow.pb_min` | 60 → **80** | `LOOP_TYPE_PRESETS` |
| `flow.safety_factor` | 1.15 → **1.3** | `LOOP_TYPE_PRESETS` |
| `flow.tau_c_factor` | 1.2 → **1.5** | `LOOP_TYPE_PRESETS` |

> **流量回路噪声大，严禁微分**（`td_enable=False` 是铁律）。如果仍然抖，主因通常是 PB 太低。

#### 4d. 压力回路（Pressure）— 高增益系统反应过激

| 调整参数 | 当前值 → 建议值 | 配置块 |
|---------|----------------|--------|
| `pressure.safety_factor` | 1.15 → **1.3** | `LOOP_TYPE_PRESETS` |
| `pressure.tau_c_factor` | 1.5 → **2.0** | `LOOP_TYPE_PRESETS` |
| `pressure.pb_min` | 80 → **100** | `LOOP_TYPE_PRESETS` |

---

### 🟣 场景五：大滞后系统整定失败

**症状**：日志显示 `L/T1 > 0.5`，PB 被推到极高值仍不稳定，或 fallback 到振荡路径但 PB 不合理。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 |
|--------|---------|----------------|--------|
| ⭐️1 | `large_delay_pb_boost` | 1.5 → **1.8~2.0** | `OSCILLATION_TUNING` |
| ⭐️2 | `large_delay_lambda_factor` | 2.5 → **3.0** | `OSCILLATION_TUNING` |
| 3 | `extreme_delay_pb_boost` | 2.0 → **2.5** | `OSCILLATION_TUNING` |
| 4 | `pb_max_large_delay` | 600 → **800** | `OSCILLATION_TUNING` |

---

### ⚪ 场景六：数据质量差导致整定不可靠

**症状**：数据噪声大、相关性低、拟合 R² 始终 < 0.4，算法大量 fallback 到振荡路径。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 | 作用原理 |
|--------|---------|----------------|--------|---------|
| ⭐️1 | `r2_failure_threshold` | 0.35 → **0.25** | `OSCILLATION_TUNING` | 降低触发振荡路径的门槛，给模型辨识更多机会 |
| 2 | `noise_threshold` | 0.02 → **0.05** | `PREPROCESSING` | 提高噪声容忍度 |
| 3 | `min_correlation` | 0.15 → **0.10** | `PREPROCESSING` | 降低相关性门槛，允许更弱的 PV-MV 关系 |
| 4 | `quality_adjustment_threshold` | 0.5 → **0.3** | `OSCILLATION_TUNING` | 推迟质量惩罚的介入时机 |

---

### ⚫ 场景七：模型辨识结果参数离谱

**症状**：K 值算出 > 10 或 < 0，T1 极大或极小，L 为 0 或为负。

| 优先级 | 调整参数 | 当前值 → 建议值 | 配置块 | 作用原理 |
|--------|---------|----------------|--------|---------|
| 1 | `k_max` | 50.0 → **20.0** | `MODEL_FITTING` | 收紧 K 值合理范围，提前拒绝离谱模型 |
| 2 | `T1_max` / `L_max` | 30/10 → 按工况调整 | `PARAMETER_CONSTRAINTS` | 限制时间常数和纯滞后的上限 |
| 3 | MODEL_BOUNDS 各模型 | 缩小 initial 范围 | `MODEL_BOUNDS` | 限制优化器的搜索空间 |

---

### 💡 场景八：想启用 LLM 辅助整定

**症状**：对于阀门死区/粘滞极严重的老旧装置，想引入 LLM 进行更智能的保守策略建议。

| 调整参数 | 当前值 → 建议值 | 配置块 |
|---------|----------------|--------|
| `enable_llm` | `False` → **`True`** | `OSCILLATION_TUNING` |

> **注意**：启用后需要配置 LLM API 连接（见 `strategies/llm_conservative_advisor.py`）。LLM 仅在极端场景（阀门问题 + 低质量 + 高非线性）时被调用，不会影响正常场景的性能。

---

### 📊 参数影响力排行榜 (Top 15)

以下是对最终 PID 输出影响最大的 15 个参数，按影响力从高到低排列：

| 排名 | 参数 | 影响范围 | 推荐调整场景 |
|------|------|---------|------------|
| 1 | `pb_min` | 所有场景的 PB 下限 | 整体偏振荡 → 调高；整体偏慢 → 调低 |
| 2 | `pb_max` | 所有场景的 PB 上限 | 响应太慢 → 调低；极端场景不稳定 → 调高 |
| 3 | `safety_factor_base` | 振荡路径全局安全系数 | 一刀切式整体加保守 |
| 4 | `tau_c_factor` (SIMC) | 模型路径闭环时间常数 | 模型路径响应速度的主控旋钮 |
| 5 | 回路预设 `tau_c_factor` | 特定回路的响应速度 | 针对性调整单类回路 |
| 6 | `max_settling_time` | 闭环验证是否通过 | 慢系统误判不稳定 → 调高 |
| 7 | `overshoot_acceptable` | 闭环验证超调门槛 | 超调假阳性 → 调高 |
| 8 | `r2_failure_threshold` | 模型路径 vs 振荡路径的分界线 | 过多 fallback → 调低 |
| 9 | `min_r2_confidence` | 是否跳过闭环验证 | 低质量数据误报 → 调低 |
| 10 | `large_delay_pb_boost` | 大滞后系统 PB 放大倍数 | 大滞后不稳定 → 调高 |
| 11 | 回路预设 `safety_factor` | 特定回路的保守系数 | 单类回路微调 |
| 12 | 回路预设 `ti_multiplier` | 特定回路的积分时间倍率 | 积分饱和或偏差消除太慢 |
| 13 | `level_ti_multiplier` | 液位回路 Ti 专用倍率 | 液位超调大 → 调高 |
| 14 | `kp_from_ku_factor` | 振荡路径的 Kp 计算系数 | 振荡路径全局偏激进/偏保守 |
| 15 | `valve_stiction_factor` | 粘滞阀门的 PB 补偿 | 老旧阀门场景抖动 → 调高 |
