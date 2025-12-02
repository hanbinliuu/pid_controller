# PID控制系统 - 工程化模块结构

## 项目结构

```
pid_control_system/
├── __init__.py                 # 包初始化文件
├── main.py                     # 主入口文件
├── control_monitor.py          # 控制监控主逻辑
├── config/                     # 配置模块
│   ├── __init__.py
│   ├── enums.py               # 枚举类型定义
│   └── settings.py            # 系统配置参数
├── utils/                      # 工具模块
│   ├── __init__.py
│   └── logger.py              # 日志配置工具
├── disturbance/                # 扰动处理模块
│   ├── __init__.py
│   ├── generator.py           # 扰动生成器
│   └── handler.py             # 扰动处理器
├── data/                       # 数据处理模块
│   ├── __init__.py
│   └── handler.py             # 数据处理器
├── models/                     # 系统模型模块
│   ├── __init__.py
│   ├── flow_system.py         # 流量系统模型
│   └── temperature_system.py # 温度系统模型
├── control/                    # 控制算法模块
│   ├── __init__.py
│   ├── pid_controller.py      # PID控制器
│   └── system_identifier.py   # 系统辨识器
├── analysis/                   # 分析模块
│   ├── __init__.py
│   └── state_analyzer.py      # 状态分析器
└── visualization/             # 可视化模块
    ├── __init__.py
    └── plot_manager.py        # 绘图管理器
```

## 模块说明

### config（配置模块）
- **enums.py**: 定义所有枚举类型（Mode, PIDMode, DisturbanceType等）
- **settings.py**: 集中管理系统配置参数

### utils（工具模块）
- **logger.py**: 日志配置工具，支持按日期分割日志文件

### disturbance（扰动处理模块）
- **generator.py**: 生成各种系统扰动
- **handler.py**: 处理和应用扰动对系统的影响

### data（数据处理模块）
- **handler.py**: 数据读取、生成、滤波和保存功能

### models（系统模型模块）
- **flow_system.py**: 水阀流量系统模型
- **temperature_system.py**: 温度系统模型，支持老化和扰动

### control（控制算法模块）
- **pid_controller.py**: PID控制器实现，支持多种控制模式
- **system_identifier.py**: 系统辨识和PID整定工具

### analysis（分析模块）
- **state_analyzer.py**: 系统状态分析，包括稳态判断和扰动检测

### visualization（可视化模块）
- **plot_manager.py**: 实时绘图和数据可视化管理

### 主模块
- **control_monitor.py**: 控制监控主逻辑，协调各模块运行
- **main.py**: 程序入口

## 使用方法

### 运行程序
```bash
cd pid_control_system
python main.py
```

### 作为模块导入
```python
from pid_control_system import ControlMonitor, Config, Mode

# 创建监控实例
monitor = ControlMonitor()
monitor.run()
```

## 功能特性

1. **多种控制模式**: 标准模式、抗扰动模式、抗噪声模式、流量控制模式
2. **多种PID模式**: 标准PID、微分先行、比例微分先行
3. **多种整定方法**: Lambda整定法、Cohen-Coon整定法
4. **扰动处理**: 支持多种扰动类型，自动检测和响应
5. **数据源支持**: 支持仿真数据生成和JSON数据读取
6. **实时可视化**: 实时绘图显示系统状态和参数变化
7. **日志记录**: 完整的日志系统，支持按日期分割

## 依赖项

- numpy
- scipy
- matplotlib
- 标准库: collections, datetime, enum, json, logging, os

## 更新日志

详见原始文件中的更新说明。

