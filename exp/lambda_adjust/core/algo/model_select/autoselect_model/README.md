# PID模型自动选择功能模块

该模块实现了基于最小二乘法的PID模型自动选择功能，能够自动识别数据属于一阶、一阶加纯滞后（FOPDT）还是二阶模型。

## 核心功能

- **模型检测**：基于最小二乘法检测数据属于哪个模型类型
- **数据生成**：生成各模型类型的测试数据，用于算法调整
- **准确率评估**：评估模型检测的准确率，生成混淆矩阵
- **可视化**：可视化检测结果和拟合效果

## 快速使用

### 方法1：使用 detect_model.py（推荐）

直接修改 `detect_model.py` 文件中的 `test_json_file` 变量，然后运行：

```bash
python detect_model.py
```

### 方法2：在代码中使用

```python
from autoselect_model import ModelDetector, Visualizer

# 检测模型类型
detector = ModelDetector()
result = detector.detect_from_json("data.json")

print(f"检测到的模型: {result.detected_model.value}")
print(f"置信度: {result.confidence:.4f}")
print(f"R²: {result.r2:.4f}")
print(f"参数: {result.parameters}")

# 可视化
visualizer = Visualizer()
visualizer.visualize_detection(json_data, result, "output.png")
```

## 模型类型说明

### 1. 一阶模型 (first_order)
- 传递函数: `G(s) = K / (T*s + 1)`
- 参数: `K` (增益), `T` (时间常数)

### 2. 一阶加纯滞后模型 (fopdt)
- 传递函数: `G(s) = K * e^(-L*s) / (T*s + 1)`
- 参数: `K` (增益), `T` (时间常数), `L` (滞后时间)

### 3. 二阶模型 (second_order)
- 传递函数: `G(s) = K / ((T1*s + 1) * (T2*s + 1))`
- 参数: `K` (增益), `T1` (第一个时间常数), `T2` (第二个时间常数)

## JSON数据格式要求

```json
{
  "status": "success",
  "data": [
    {
      "timestamp": 1761642000000,
      "pv": 5,
      "mv": 13.025042
    },
    ...
  ]
}
```

必需字段：
- `status`: 必须为 `"success"`
- `data`: 数据数组
  - `timestamp`: 时间戳（毫秒）
  - `pv`: 过程值
  - `mv`: 控制输出

## 检测原理

1. **最小二乘法拟合**：对每种模型类型使用最小二乘法进行参数估计
2. **拟合度评估**：计算每种模型的R²、RMSE、BIC等指标
3. **模型选择**：综合考虑R²、BIC和模型复杂度，选择最佳模型
4. **置信度计算**：基于R²和与其他模型的差异计算置信度

## 数据生成和评估

### 生成测试数据

```python
from autoselect_model import DataGenerator

generator = DataGenerator()

# 生成单个测试数据
data = generator.generate_test_data(
    model_type="fopdt",
    params={"K": 0.6, "T": 25.0, "L": 5.0},
    duration=300.0,
    dt=0.5,
    noise_level=0.01
)

# 保存为JSON
import json
with open("test_data.json", "w", encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

# 批量生成测试数据
generated_files = generator.generate_batch(
    output_dir="test_data",
    num_samples_per_model=10,
    duration=300.0,
    dt=0.5,
    noise_level=0.01
)
```

### 评估检测准确率

```python
from autoselect_model import AccuracyEvaluator

evaluator = AccuracyEvaluator()

# 评估测试数据目录
result = evaluator.evaluate("test_data/")

# 打印报告
evaluator.print_evaluation_report(result)

# 保存报告
evaluator.save_evaluation_report(result, "output/evaluation_report.json")
```

## 模块结构

```
autoselect_model/
├── __init__.py              # 模块初始化
├── model_detector.py        # 模型检测器（核心）
├── data_generator.py        # 测试数据生成器
├── accuracy_evaluator.py    # 准确率评估器
├── visualizer.py            # 可视化工具
├── detect_model.py          # 简单使用脚本
└── README.md                # 说明文档
```

## 依赖库

- numpy
- scipy
- matplotlib
- json (标准库)
