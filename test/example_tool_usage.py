#!/usr/bin/env python3
"""
展示修改后的TemperatureAnalysisTool和PIDOptimizationTool使用方法的示例
"""

import json
import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool

def create_sample_dataset():
    """创建示例数据集"""
    import numpy as np
    from datetime import datetime, timedelta
    
    # 模拟24小时的温度数据
    hours = 24
    data_points = hours * 60  # 每分钟一个数据点
    
    # 生成时间序列
    start_time = datetime.now() - timedelta(hours=hours)
    timestamps = [start_time + timedelta(minutes=i) for i in range(data_points)]
    
    # 模拟温度曲线：从25度上升到目标温度30度
    target_temp = 30.0
    temperatures = []
    
    for i in range(data_points):
        # 模拟PID控制的温度响应
        if i < 100:  # 初始阶段快速上升
            temp = 25.0 + (target_temp - 25.0) * (1 - np.exp(-i/50))
        elif i < 200:  # 轻微超调
            temp = target_temp + 2.0 * np.exp(-(i-100)/20)
        else:  # 稳态阶段，有轻微波动
            temp = target_temp + np.random.normal(0, 0.3)
        
        temperatures.append(round(temp, 2))
    
    # 创建数据集
    dataset = []
    for i in range(data_points):
        dataset.append({
            "id": i + 1,
            "timestamp": timestamps[i].isoformat(),
            "channel_id": 0,
            "temperature": temperatures[i],
            "target_temp": target_temp,
            "kp": 1.0,
            "ki": 0.1,
            "kd": 0.05,
            "control_period": 100,
            "max_duty": 80,
            "heating": bool(temperatures[i] < target_temp)  # 确保是布尔值
        })
    
    return {"data": dataset}

def test_temperature_analysis_tool():
    """测试温度分析工具"""
    print("=== 测试TemperatureAnalysisTool ===")
    
    # 创建工具实例
    tool = TemperatureAnalysisTool()
    
    # 创建示例数据集
    dataset = create_sample_dataset()
    
    # 将数据集转换为JSON字符串
    dataset_json = json.dumps(dataset, default=str)
    
    # 执行分析
    result = tool._run(dataset_json)
    
    # 输出结果
    print("输入数据集包含数据点数:", len(dataset["data"]))
    print("分析结果:")
    
    try:
        result_data = json.loads(result)
        print(json.dumps(result_data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("结果不是有效的JSON:", result)
    
    print()

def test_pid_optimization_tool():
    """测试PID优化工具"""
    print("=== 测试PIDOptimizationTool ===")
    
    # 创建工具实例
    tool = PIDOptimizationTool()
    
    # 创建示例数据集
    dataset = create_sample_dataset()
    
    # 将数据集转换为JSON字符串
    dataset_json = json.dumps(dataset, default=str)
    
    # 执行优化分析
    result = tool._run(dataset_json)
    
    # 输出结果
    print("输入数据集包含数据点数:", len(dataset["data"]))
    print("优化分析结果:")
    
    try:
        result_data = json.loads(result)
        print(json.dumps(result_data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("结果不是有效的JSON:", result)
    
    print()

def test_with_simple_dataset():
    """使用简单数据集测试"""
    print("=== 使用简单数据集测试 ===")
    
    # 创建简单的数据集
    simple_dataset = {
        "data": [
            {"temperature": 25.0, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 26.5, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 28.2, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 29.8, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 30.2, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 30.1, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 29.9, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05},
            {"temperature": 30.0, "target_temp": 30.0, "kp": 1.0, "ki": 0.1, "kd": 0.05}
        ]
    }
    datasetList=simple_dataset
    # 测试温度分析
    temp_tool = TemperatureAnalysisTool()
    temp_result = temp_tool._run(json.dumps(datasetList))
    
    print("简单数据集温度分析结果:")
    try:
        result_data = json.loads(temp_result)
        print(json.dumps(result_data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("结果不是有效的JSON:", temp_result)
    
    print()
    
    # 测试PID优化
    pid_tool = PIDOptimizationTool()
    pid_result = pid_tool._run(json.dumps(datasetList))
    
    print("简单数据集PID优化结果:")
    try:
        result_data = json.loads(pid_result)
        print(json.dumps(result_data, indent=2, ensure_ascii=False))
    except json.JSONDecodeError:
        print("结果不是有效的JSON:", pid_result)

def main():
    """主函数"""
    print("演示修改后的工具使用方法")
    print("=" * 50)
    
    try:
        # 测试温度分析工具
        test_temperature_analysis_tool()
        
        # 测试PID优化工具  
        test_pid_optimization_tool()
        
        # 使用简单数据集测试
        test_with_simple_dataset()
        
        print("所有测试完成！")
        
    except Exception as e:
        print(f"测试过程中出现错误: {str(e)}")
        import traceback
        print(f"错误堆栈: {traceback.format_exc()}")

if __name__ == "__main__":
    main()