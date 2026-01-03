# PID 整定算法调试指南

## 🔍 Step 1: 看日志判断问题阶段

运行时设置 `verbose=True`：
```python
selector = ModelSelector(verbose=True)
```

| 日志关键词 | 问题阶段 | 解决方向 |
|-----------|---------|---------|
| `R²<0.4` | 模型拟合 | 数据质量差，检查输入数据 |
| `临界法整定失败` | 振荡检测 | 振荡不明显，调低振荡阈值 |
| `闭环不稳定` | 闭环验证 | 参数过激，增大 pb 或 Ti |
| `整定失败` | 最终输出 | 需要调整 fallback 参数 |

---

## 🎯 Step 2: 按回路类型定位

| 回路类型 | 调整方向 | 相关参数前缀 |
|---------|---------|-------------|
| Flow | 一般无需调 | - |
| Level | 增大积分时间 | `level_*` |
| Temperature | 增大仿真时长 | `ti_slow_*`, `*_sim_*` |
| Pressure | 一般无需调 | - |

---

## 🔧 Step 3: 核心参数（只需关注这 5 个）

| 参数 | 默认 | 何时调整 | 调整方向 |
|-----|------|---------|---------|
| `pb_max` | 600 | 日志显示 pb 达上限仍不稳定 | ↑ 增大到 800 |
| `safety_factor_base` | 1.2 | 振荡压制不足 | ↑ 增大到 1.4 |
| `level_ti_multiplier` | 2.2 | 液位回路不稳定 | ↑ 增大到 2.5 |
| `temperature_sim_duration_factor` | 8 | 温度回路仿真超时 | ↑ 增大到 10 |
| `very_slow_max_sim_duration` | 3600 | 极慢系统超时 | ↑ 增大到 5000 |

### 修改示例
```python
from core.algorithm.model_type.config import Config

# 临时修改（运行时）
Config.OSCILLATION_TUNING['pb_max'] = 800
Config.OSCILLATION_TUNING['safety_factor_base'] = 1.4
```

---

## ⚠️ 其他参数（一般不动）

以下 100+ 参数已调优，除非有明确需求否则不建议修改：
- `ku_k_ratio_*`: 增益比值判断
- `quality_adjustment_*`: 数据质量调整
- `valve_*_factor`: 阀门问题因子
- `pb_gradient`, `derivative_*`: 渐进调整

---

## 🧪 验证修改效果

```bash
# 运行单场景测试
python -c "
from core.algorithm.model_type.config import Config
Config.OSCILLATION_TUNING['pb_max'] = 800  # 你的修改

from core.algorithm.model_type.tests.run_failed_scenarios import run_and_collect_failed
run_and_collect_failed()
"
```
