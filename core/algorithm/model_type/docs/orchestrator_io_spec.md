# PID Agent 算法端主入口 I/O 规范 (API Specification)

本文档定义了 PID Agent 微服务化/OS 平台化后，算法端主入口（`TuningOrchestrator.run()`）的标准输入与输出 JSON 数据结构。这套接口彻底与底层算法细节（常规数学计算/大语言模型）解耦，旨在将 Python 端打造成一个无状态的纯粹计算节点。

---

## 1. 入口定义

**类名**: `TuningOrchestrator`
**方法**: `run(input_data: Dict) -> Dict`
**功能摘要**: 接收原始工控时序数据及 OS 中台打包下发的语义模型约束，根据配置触发相应的底层模型识别与 PID 计算流程，最终返回识别到的设备模型属性及安全的 PID 整定建议。

---

## 2. 标准输入 (Input Payload)

传入 `run()` 函数的 `input_data` 是一个庞大的聚合字典，包含运行时所需的历史数据切片、模型配置以及由 OS 中台接管的“工艺/语义约束（Semantic Context）”。

```json
{
  // 1. 系统历史位号时序数据 (必填项)
  // 由中台抽取并下发，时间须为连续或包含有效控制行为的时间段。
  "history_data": [
    {
      "timestamp": "2026-01-10 12:00:00",
      "sv": 45.0,
      "pv": 45.1,
      "mv": 60.5
    },
    // ... 更多时序点
  ],
  
  // 2. 当前运行的 PID 参数 (选填项，用于参考与 fallback 符号识别)
  "current_pid": {
    "Kp": 2.0,
    "Ti": 10.0,
    "Td": 0.0
  },
  
  // 3. 算法高级配置开关 (选填项)
  "params": {
    "turning_type": "PI",         // 期望目标控制器类型 (P/PI/PID)
    "model_type": null,           // 期望强制采用的模型类型，通常由算法自适应，可留空
    "sliding_window": true        // 是否触发并发滑动窗口寻优引擎
  },
  
  // 4. 扰动/整定窗口切片 (选填项)
  // 主要来源: core/algorithm/tuning_segment/stability_detector.py 中的
  //   find_high_variability_periods() 自动检测出来的扰动段（auto_detect 模式）
  // 其他来源: 
  //   - 滑动窗口寻优引擎 (grid_search 模式) 自动切片
  //   - 前端人工框选
  //   - OS 中台事件驱动投喂
  // 如果不传（空列表）：
  //   - 若开启了 sliding_window=true，算法引擎会自己滑窗搜索
  //   - 否则会直接返回空结果（无扰动窗口即跳过整定）
  "qualified_windows": [
    {
      "start_time": "2026-01-10 13:00:00",
      "end_time": "2026-01-10 14:00:00"
    }
  ],

  // =========================================================
  // 5. [核心] 语义大包 (OS 中台下发) (process_context)
  // =========================================================
  // 此时算法库已不存储硬机理字典，所有物理定律和专家红线完全由 OS 中台下放
  "process_context": {
      "mechanism_model": {
          "typical_time_constant_range_s": [10.0, 300.0], // 反应时间下限与上限
          "typical_dead_time_range_s": [2.0, 30.0],       // 物理传输延迟限度
          "process_gain_sign": 1                          // 设备预期方向 (1:正作用, -1:反作用)
      },
      "characterization_model": {                         // OS中台对回路当前环境的动态诊断
          "loop_type": "level",                           // 流量库/液位库/压力库...
          "noise_level": "low"
      },
      "knowledge_model": {                                // 资深工控专家的兜底红线
          "pb_range": [100.0, 500.0]                      // 该回路切不可越过 PB < 100 的激进危险区
      }
  }
}
```

---

## 3. 标准输出 (Output Record)

`run()` 返回的最终 JSON 数据囊括了辨识结果、算法评级、图表可视化支撑数据、及最终推荐参数。
**强烈建议 OS 中台拿到此 JSON 后，提取其中的 `model_parameters` 与 `pid_parameters`，根据中台层的语义规则库实施最后的联合审批。**

```json
{
  // ================= 核心结算区 =================
  "success": true,                        // 整定是否触发成功（无论何种fallback，只要得出 PID 就为 true）
  "model_type": "FO_INTEGRATOR",          // 最终决定采纳的模型形态
  "turning_type": "PI",                   // 分配的控制器制式
  
  // 综合评估置信度（供 OS 参考是否要提示给人工确认）
  "model_rating": 7.8,                    // 最终性能与稳定性综合评价 (满分10分)
  "method_confidence": 0.85,              // 对该整定手法的统计学信心指数
  
  // ================= 机理审查依赖区 =================
  // 【OS 拦截参考指南】：拿这部分模型特征去跟语义大字典对照验证物理幻觉！
  "model_parameters": {          
    "K": 0.311,                           // 过程增益模型
    "T1": 1.0,                            // 响应速度 
    "T2": 0.0,
    "L": 5.0                              // 发现的延迟死区
  },
  
  // 【OS 安全兜底指南】：拿这个 PID 节点特别是 "pb" 验证能否下放工控机！
  "pid_parameters": {            
    "Kp": 3.125,
    "Ki": 0.013,
    "Kd": 0.0,
    "pb": 32.0,                           // 决定动作激进程度的核心：100/Kp
    "ti": 240.0,
    "td": 0.0,
    "Ts": 1.0                             // 数据分析提取出的系统控制离散采样周期
  },
  
  // ================= 诊断与可视化扩展支持区 =================
  // 该部分用于提供给前端大屏展示闭环曲线
  "fitting_result": {      
    "timestamp": [1761667200000, 1761667201000, "..."],
    "sv": [45.0, 45.0, "..."], 
    "pv": [45.0, 45.1, "..."], 
    "mv": [60.5, 60.5, "..."],
    "pv_model": [45.0, 45.1, "..."],      // 该预测模型还原的无噪声平滑曲线，用于做前端对比
    "r_squared": 0.8288,                  // 模型拟合绝对精度
    "recommendation": "常规整定闭环稳定，可以直接下发" 
  },
  
  // 这部分显示了如果是仿真，这套 PID 会导致怎样的超调与稳定性结果
  "closed_loop_verification": {  
    "is_stable": true,
    "settling_time": 3359.0,              // 完全回到稳态所需秒数
    "overshoot_percent": 0.0,             // 有无超调（爆管危险提示）
    "steady_state_error_percent": 0.62    // 预计稳态偏差
  }
}
```

## 4. 架构整合启示

依托此精简和内聚的 I/O 模型，这套 Python 代码仓库已脱离“重度机理绑定”，成为单纯的**领域函数 (Domain Function)**。
- 若未来新增了大语言模型（LLM Agent）整定流，输入和输出的数据边界无需变化，大模型同样在内部接纳 `process_context` 获取指引。
- OS 服务层将完全接手 `model_parameters` -> 物理模型幻觉验证的拦截。
- OS 服务层将完全接手 `pid_parameters` -> 安全平稳运行极限的拦截。
