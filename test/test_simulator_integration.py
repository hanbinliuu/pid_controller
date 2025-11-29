#!/usr/bin/env python3
"""
测试PID数据模拟器与分析工具的集成
"""

import json
import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.client.pid_data_simulator import PIDDataSimulator, quick_generate_data
from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool

def test_simulator_with_analysis_tools():
    """测试模拟器数据与分析工具的集成"""
    
    print("🧪 开始集成测试...")
    
    # 1. 生成测试数据
    print("\n📊 生成测试数据...")
    simulator = PIDDataSimulator()
    test_data = simulator.generate_historical_data(
        duration_hours=2, 
        sample_interval=10.0, 
        scenario="normal"
    )
    
    print(f"✅ 生成了 {len(test_data)} 条测试数据")
    
    # 2. 测试温度分析工具
    print("\n🌡️ 测试温度分析工具...")
    temp_analyzer = TemperatureAnalysisTool()
    
    try:
        # 将数据转换为JSON格式传递给分析工具
        analysis_result = temp_analyzer._run(json.dumps(test_data))
        analysis_data = json.loads(analysis_result)
        
        print("✅ 温度分析成功!")
        print(f"   当前温度: {analysis_data.get('current_temp', 'N/A')}°C")
        print(f"   目标温度: {analysis_data.get('target_temp', 'N/A')}°C")
        print(f"   温度范围: {analysis_data.get('min_temp', 'N/A')} - {analysis_data.get('max_temp', 'N/A')}°C")
        print(f"   稳态误差: {analysis_data.get('steady_error', 'N/A')}°C")
        
    except Exception as e:
        print(f"❌ 温度分析失败: {str(e)}")
        return False
    
    # 3. 测试PID优化工具
    print("\n⚙️ 测试PID优化工具...")
    pid_optimizer = PIDOptimizationTool()
    
    try:
        # 将数据传递给PID优化工具
        optimization_result = pid_optimizer._run(json.dumps(test_data))
        optimization_data = json.loads(optimization_result)
        
        print("✅ PID优化分析成功!")
        current_params = optimization_data.get('current_params', {})
        print(f"   当前PID参数: Kp={current_params.get('kp', 'N/A')}, "
              f"Ki={current_params.get('ki', 'N/A')}, Kd={current_params.get('kd', 'N/A')}")
        
        performance = optimization_data.get('performance', {})
        print(f"   控制性能: 稳态误差={performance.get('steady_error', 'N/A')}°C, "
              f"稳定性={performance.get('stability', 'N/A')}")
        
        suggestions = optimization_data.get('tuning_suggestions', {})
        recommendations = suggestions.get('recommendations', [])
        if recommendations:
            print(f"   优化建议: {', '.join(recommendations[:2])}")
        
    except Exception as e:
        print(f"❌ PID优化分析失败: {str(e)}")
        return False
    
    # 4. 测试TSDB格式数据
    print("\n🗄️ 测试TSDB格式数据...")
    try:
        # 保存为TSDB格式
        tsdb_file = simulator.save_as_tsdb_format(
            test_data, 
            "test_integration", 
            "integration_test.json"
        )
        
        # 读取TSDB格式文件
        with open(tsdb_file, 'r') as f:
            tsdb_data = json.load(f)
        
        # 验证TSDB格式
        assert tsdb_data.get("code") == 0, "TSDB响应码应该为0"
        assert len(tsdb_data.get("results", [])) > 0, "应该有查询结果"
        
        result = tsdb_data["results"][0]
        data_points = result.get("data", [])
        assert len(data_points) > 0, "应该有数据点"
        
        first_point = data_points[0]
        columns = first_point.get("columns", [])
        values = first_point.get("values", [])
        
        print(f"✅ TSDB格式验证成功!")
        print(f"   表名: {result.get('table')}")
        print(f"   字段数: {len(columns)}")
        print(f"   数据行数: {len(values)}")
        
    except Exception as e:
        print(f"❌ TSDB格式测试失败: {str(e)}")
        return False
    
    print("\n🎉 所有集成测试通过!")
    return True

def test_data_formats():
    """测试不同数据格式的一致性"""
    
    print("\n🔄 测试数据格式一致性...")
    
    # 生成小量数据
    files = quick_generate_data(0.5, 30.0, "normal", ["json", "csv", "tsdb"])
    
    try:
        # 读取JSON数据
        with open(files['json'], 'r') as f:
            json_data = json.load(f)
        
        # 读取TSDB数据
        with open(files['tsdb'], 'r') as f:
            tsdb_data = json.load(f)
        
        # 验证数据一致性
        tsdb_values = tsdb_data["results"][0]["data"][0]["values"]
        
        print(f"✅ 格式一致性验证:")
        print(f"   JSON记录数: {len(json_data)}")
        print(f"   TSDB记录数: {len(tsdb_values)}")
        print(f"   数据一致: {len(json_data) == len(tsdb_values)}")
        
        # 检查字段完整性
        required_fields = ["temperature", "kp", "ki", "kd", "target_temp"]
        first_record = json_data[0]
        missing_fields = [f for f in required_fields if f not in first_record]
        
        if not missing_fields:
            print(f"   ✅ 所有必需字段都存在")
        else:
            print(f"   ❌ 缺少字段: {missing_fields}")
            return False
            
    except Exception as e:
        print(f"❌ 格式一致性测试失败: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    print("🚀 PID模拟器集成测试")
    print("=" * 50)
    
    success = True
    
    # 运行集成测试
    if not test_simulator_with_analysis_tools():
        success = False
    
    # 运行格式测试
    if not test_data_formats():
        success = False
    
    if success:
        print("\n🎊 所有测试通过! 模拟器集成成功!")
        print("\n📋 使用说明:")
        print("1. 使用 python pid_data_simulator.py 交互式生成数据")
        print("2. 使用 quick_generate_data() 函数编程生成数据")
        print("3. 生成的数据可直接用于温度分析和PID优化工具")
        print("4. 支持JSON、CSV、TSDB三种格式输出")
    else:
        print("\n❌ 部分测试失败，请检查问题")
        sys.exit(1)