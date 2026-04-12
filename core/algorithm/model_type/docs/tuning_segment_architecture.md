# 整定段优选架构设计文档

> **状态**: 待实施  
> **创建日期**: 2026-04-12  
> **核心约束**: 所有外部接口（输入/输出）不可变更  
> **核心问题**: `tuning_segment` 模块目前仅实现了扰动段检测，缺乏"整定段优先 → 振荡段次选 → 扰动段兜底"的分级优选机制

---

## 1. 硬性约束（红线）

> [!CAUTION]
> 以下两个公开接口的签名和返回结构**绝对不可以改动**，所有优化必须在内部透明完成。

### 1.1 `find_high_variability_periods()` 接口冻结

```python
# 入参不变
def find_high_variability_periods(history_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    入参格式:
        {"history_data": [{"timestamp": ..., "pv": ..., "sv": ...}, ...]}

    返回格式 (不变):
        {
            "start_time": int,       # 数据起始时间戳
            "end_time": int,         # 数据结束时间戳
            "qualified_windows": [   # 选出的窗口列表
                {"start_time": int, "end_time": int},
                ...
            ]
        }
    """
```

### 1.2 `TuningOrchestrator.run()` 接口冻结

```python
# input_data 结构不变
input_data = {
    "history_data": [...],
    "qualified_windows": [...],       # 格式不变
    "current_pid": {...},
    "params": {...},
    "process_context": {...}
}
# 返回值结构不变
```

---

## 2. 现状与问题

### 2.1 当前 `find_high_variability_periods()` 内部流程

```python
# 第 1616-1619 行 (stability_detector.py)
detector = StabilityDetector()
non_steady_segments = detector.detect_non_steady_segments(pv_data, sv_data)
#                     ↑ 只做了一件事：找"非稳态段"（扰动段）
```

### 2.2 三类核心缺陷

| 编号 | 缺陷 | 影响 |
|------|------|------|
| D-1 | **无整定段检测能力** | 操作员做了完美的 MV 阶跃实验，但若 PV 响应平稳（非剧烈波动），`StabilityDetector` 不会选出它 |
| D-2 | **无振荡段优先识别** | 系统正在临界振荡（天然的 Z-N 实验条件），被混在泛泛的"扰动"里 |
| D-3 | **无分级降级逻辑** | "找到扰动就用扰动"，不是"先找最好的，找不到再退而求其次" |

---

## 3. 目标架构：三级优选（接口零变更）

### 3.1 核心设计理念

> **所有改动都发生在 `find_high_variability_periods()` 函数体内部。**  
> 对 OS 后端和 Orchestrator 来说，调用方式和返回结果完全无感知。  
> 相当于给这个函数"换了一颗更聪明的大脑"，但"外壳"一模一样。

### 3.2 三级优先级定义

```
┌─────────────────────────────────────────────────────┐
│  Level 1: 整定段 (Tuning Segment)       🥇 最高优先  │
│  特征: MV 发生了清晰的阶跃变化，PV 随之产生可辨识的    │
│       一阶/二阶响应（上升、超调、稳定）                 │
│  适用: 最小二乘模型辨识 (FOPDT/SOPDT)                 │
│  质量: 能直接算出 K, T1, L，精度最高                   │
├─────────────────────────────────────────────────────┤
│  Level 2: 振荡段 (Oscillation Segment)  🥈 次选      │
│  特征: PV 围绕 SV 持续周期性振荡，振荡幅度和频率可提取  │
│  适用: 临界法整定 (Ziegler-Nichols / 继电反馈法)       │
│  质量: 能提取临界增益 Ku 和临界周期 Tu                  │
├─────────────────────────────────────────────────────┤
│  Level 3: 扰动段 (Disturbance Segment)  🥉 兜底      │
│  特征: 泛泛的非稳态区间（噪声、漂移、外部干扰）         │
│  适用: 相关分析法 / 统计估计 / 保守兜底                 │
│  质量: 精度最差，但总比没有强                          │
└─────────────────────────────────────────────────────┘
```

### 3.3 改造后的 `find_high_variability_periods()` 内部伪代码

```python
def find_high_variability_periods(history_data: Dict[str, Any]) -> Dict[str, Any]:
    # ... 解析 pv_data, sv_data, mv_data, timestamps（同现有逻辑） ...

    # ========================================
    # Level 1: 先找整定段（MV阶跃 → PV响应）
    # ========================================
    tuning_detector = TuningSegmentDetector()
    tuning_segments = tuning_detector.detect(pv_data, sv_data, mv_data)
    
    if tuning_segments:
        # 🥇 找到了！按质量评分排序，取最优的作为 qualified_windows
        qualified_windows = _segments_to_windows(tuning_segments, timestamps)
        return {"start_time": ..., "end_time": ..., "qualified_windows": qualified_windows}
    
    # ========================================
    # Level 2: 没有整定段，找振荡段
    # ========================================
    oscillation_detector = OscillationSegmentDetector()
    oscillation_segments = oscillation_detector.detect(pv_data, sv_data)
    
    if oscillation_segments:
        # 🥈 找到了！
        qualified_windows = _segments_to_windows(oscillation_segments, timestamps)
        return {"start_time": ..., "end_time": ..., "qualified_windows": qualified_windows}
    
    # ========================================
    # Level 3: 都没有，退化到现有的扰动段检测
    # ========================================
    detector = StabilityDetector()
    non_steady_segments = detector.detect_non_steady_segments(pv_data, sv_data)
    
    # 🥉 兜底
    qualified_windows = _segments_to_windows(non_steady_segments, timestamps)
    return {"start_time": ..., "end_time": ..., "qualified_windows": qualified_windows}
```

> [!TIP]
> `history_data` 中已包含丰富的实时位号字段，Level 1 整定段检测所需的 MV 数据天然可用：
> ```json
> {"timestamp": 1764752401000, "sv": 3, "auto": 255, "ti": 3, "pb": 73.1,
>  "pv": 1.9, "td": 1.5, "mv": 8.742, "kp": 1.367, "ki": 0.455, "kd": 2.051}
> ```
> 除了核心三元组 `(pv, sv, mv)` 外，还可利用 `auto`（自动/手动标志）来辅助判断操作员是否在做手动阶跃实验、`pb/ti/td` 来获知当前控制器参数。

---

## 4. 各级检测器的核心算法

### 4.1 Level 1: 整定段检测器 (TuningSegmentDetector)

**目标**: 找到"MV 做了一个干净的阶跃，PV 产生了可辨识响应"的黄金窗口。

**检测逻辑**:

```
1. 扫描 MV 序列，找到所有"阶跃变化点"
   - MV 在短时间内（< 10个采样点）发生了 > threshold 的突变
   - 阶跃前后 MV 都趋于稳定（不是连续渐变）

2. 对每个 MV 阶跃点，向后截取 PV 响应窗口
   - 窗口长度 = 预估的 3~5 倍时间常数（可根据回路类型粗估）
   - 检查 PV 是否产生了与 MV 方向一致的单调响应

3. 质量评分
   - MV 阶跃的"纯净度"：阶跃前后 MV 是否稳定（无抖动）
   - PV 响应的"可辨识度"：是否有清晰的上升/下降曲线
   - SV 是否在此期间保持不变（排除 SV 变化导致的 PV 响应）
   - 信噪比：PV 响应幅度 vs 背景噪声

4. 筛选与排序
   - 质量评分 > 阈值 的段才算合格
   - 按评分从高到低排序，取 Top-N
```

**关键特征指标**:

| 指标 | 定义 | 合格阈值 |
|------|------|----------|
| MV 阶跃幅度 | `abs(MV_after - MV_before)` | > MV 量程的 2% |
| MV 阶跃纯净度 | `std(MV_before) / step_size` | < 0.1 |
| PV 响应方向一致性 | `sign(ΔPV) == sign(ΔMV)` | True |
| PV 响应信噪比 | `abs(ΔPV) / std(PV_noise)` | > 3.0 |
| SV 稳定性 | `std(SV_during_response)` | < 0.5 |

### 4.2 Level 2: 振荡段检测器 (OscillationSegmentDetector)

**目标**: 找到 PV 围绕 SV 持续来回振荡的区间。

**检测逻辑**:

```
1. 计算误差信号 e(t) = PV(t) - SV(t)

2. 检测过零点（e(t) 从正变负 或 从负变正）
   - 统计每段时间窗口内的过零次数
   - 过零频率 > 阈值 → 候选振荡段

3. 振荡质量评估
   - 振荡周期的一致性（标准差/均值）
   - 振荡幅度是否持续（非衰减）
   - 是否有 >= 3 个完整振荡周期

4. 提取关键参数（为后续临界法整定准备）
   - 振荡周期 Tu (由过零间隔推算)
   - 振荡幅度 a (峰-谷差的均值)
```

### 4.3 Level 3: 扰动段检测器

**即现有的 `StabilityDetector.detect_non_steady_segments()`**，完全不动。

---

## 5. 文件结构（新增文件，不改旧文件）

```
core/algorithm/tuning_segment/
├── stability_detector.py                  # ❄️ 冻结！只改 find_high_variability_periods() 内部逻辑
│   ├── class StabilityDetector            # ❄️ 不动
│   ├── find_high_variability_periods()    # 🔧 内部升级（加入三级调度）
│   └── merge_adjacent_periods()           # ❄️ 不动
│
├── tuning_segment_detector.py             # [新增] Level 1 整定段检测器
├── oscillation_segment_detector.py        # [新增] Level 2 振荡段检测器
└── test_stability_detector.py             # ❄️ 不动（追加新测试用例）
```

> [!NOTE]
> **不新增 `segment_selector.py`**。三级调度逻辑直接写在 `find_high_variability_periods()` 内部。  
> 避免引入新的模块级入口，保持对外接口零变更。

---

## 6. 对 Orchestrator Pipeline 的影响

### 6.1 Orchestrator 主入口：零改动

由于 `qualified_windows` 格式不变，`TuningOrchestrator.run()` 完全不需要修改。
它继续接收 `qualified_windows`，继续走现有的 pipeline 流程。

### 6.2 Pipeline 内部的隐性收益

| 阶段 | 改进前 | 改进后 |
|------|--------|--------|
| Stage 1 | 收到的数据可能是低质量扰动段 | 大概率收到高质量整定段 |
| Stage 1.8 | 费力地在扰动段里重新分类 | 数据本身已经是最优类型 |
| Stage 2 (模型拟合) | R² 经常 < 0.4，频繁 fallback | R² 预期 > 0.7 |
| Stage 5 (振荡整定) | 被迫作为兜底使用 | 只在真正的振荡段才触发 |

---

## 7. 数据字段可用性

### 7.1 `history_data` 中可用的字段

后端下发的 `history_data` 每条记录包含以下字段，三级检测器可直接利用：

| 字段 | 说明 | Level 1 用途 | Level 2 用途 |
|------|------|-------------|-------------|
| `timestamp` | 毫秒时间戳 | ✅ 时间轴 | ✅ 时间轴 |
| `pv` | 过程变量 | ✅ 响应信号 | ✅ 振荡信号 |
| `sv` | 设定值 | ✅ 排除 SV 变化干扰 | ✅ 计算误差信号 |
| `mv` | 操纵变量 | ✅ **核心：检测 MV 阶跃** | - |
| `auto` | 自动/手动标志(255=自动) | ✅ 辨别手动阶跃实验 | - |
| `pb/ti/td` | 当前控制器参数 | ✅ 闭环/开环判断参考 | - |
| `kp/ki/kd` | 当前 PID 参数 | - | - |

---

## 8. 实施优先级

| 阶段 | 任务 | 改动范围 | 预估 |
|------|------|----------|------|
| P0 | 编写 `TuningSegmentDetector` | 新文件 | 2-3 天 |
| P1 | 编写 `OscillationSegmentDetector` | 新文件 | 1-2 天 |
| P2 | 改造 `find_high_variability_periods()` 内部逻辑 | stability_detector.py 第 1615-1638 行 | 0.5 天 |
| P3 | 用大榭现场数据验证 | 无代码改动 | 1-2 天 |

> [!WARNING]
> **P2 是唯一涉及修改现有文件的步骤**，且仅修改 `find_high_variability_periods()` 函数体内部（第 1615-1638 行），不改签名、不改返回结构。
