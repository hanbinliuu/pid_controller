#!/usr/bin/env python3
"""
模拟历史数据查询 - 直接从CSV文件读取数据
模拟真实的API调用效果
"""

import pandas as pd
import json
from datetime import datetime
import os

def simulate_history_data_query():
    """模拟历史数据查询接口调用"""
    
    # 模拟的API请求参数
    request_params = {
        "table": "fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811",
        "start_time": 1759109290968,
        "end_time": 1759110280968
    }
    
    print("🚀 模拟调用历史数据查询接口")
    print("=" * 60)
    print(f"📋 请求参数:")
    print(json.dumps(request_params, indent=2, ensure_ascii=False))
    print("-" * 60)
    
    # CSV文件路径
    csv_file = f"/Users/dingzhenying/project/pythonProject/pid-agent-mvp/data/simulated/{request_params['table']}.csv"
    
    try:
        # 读取CSV文件
        print(f"📂 读取CSV文件: {csv_file}")
        df = pd.read_csv(csv_file)
        print(f"✅ 成功读取CSV文件，共 {len(df)} 条记录")
        
        # 过滤时间范围
        start_time = request_params['start_time']
        end_time = request_params['end_time']
        
        filtered_df = df[
            (df['timestamp'] >= start_time) & 
            (df['timestamp'] <= end_time)
        ]
        
        print(f"🔍 时间范围过滤: {start_time} - {end_time}")
        print(f"📊 过滤后记录数: {len(filtered_df)}")
        
        # 转换为API响应格式
        data_records = []
        for _, row in filtered_df.head(10).iterrows():  # 只显示前10条
            record = {
                "timestamp": int(row['timestamp']),
                "temperature": float(row['temperature']),
                "target_temp": float(row['target_temp']),
                "kp": float(row['kp']),
                "ki": float(row['ki']),
                "kd": float(row['kd']),
                "control_period": int(row['control_period']),
                "max_duty": int(row['max_duty']),
                "pid_output": float(row['pid_output']),
                "error": float(row['error']),
                "integral_error": float(row['integral_error']),
                "derivative_error": float(row['derivative_error']),
                "heat_input": float(row['heat_input']),
                "heat_loss": float(row['heat_loss'])
            }
            data_records.append(record)
        
        # 模拟API响应
        api_response = {
            "status": "success",
            "table": request_params['table'],
            "start_time": request_params['start_time'],
            "end_time": request_params['end_time'],
            "totalRecords": len(filtered_df),
            "data": data_records
        }
        
        print("\n📋 模拟API响应:")
        print(json.dumps(api_response, indent=2, ensure_ascii=False))
        
        # 数据分析
        print("\n📈 数据分析结果:")
        print(f"   - PID参数: Kp={df['kp'].iloc[0]}, Ki={df['ki'].iloc[0]}, Kd={df['kd'].iloc[0]}")
        print(f"   - 目标温度: {df['target_temp'].iloc[0]}°C")
        print(f"   - 温度范围: {df['temperature'].min():.2f}°C - {df['temperature'].max():.2f}°C")
        print(f"   - 平均温度: {df['temperature'].mean():.2f}°C")
        print(f"   - PID输出范围: {df['pid_output'].min():.2f} - {df['pid_output'].max():.2f}")
        print(f"   - 平均误差: {df['error'].mean():.2f}")
        
        return api_response
        
    except FileNotFoundError:
        error_response = {
            "status": "error",
            "table": request_params['table'],
            "message": f"CSV文件未找到: {csv_file}"
        }
        print(f"❌ 文件未找到: {csv_file}")
        print(json.dumps(error_response, indent=2, ensure_ascii=False))
        return error_response
        
    except Exception as e:
        error_response = {
            "status": "error", 
            "table": request_params['table'],
            "message": f"读取CSV文件失败: {str(e)}"
        }
        print(f"❌ 读取失败: {e}")
        print(json.dumps(error_response, indent=2, ensure_ascii=False))
        return error_response

def simulate_temperature_analysis():
    """模拟温度分析接口调用"""
    
    print("\n\n🌡️  模拟调用温度分析接口")
    print("=" * 60)
    
    # 从历史数据获取分析所需数据
    history_data = simulate_history_data_query()
    
    if history_data['status'] == 'success' and history_data['totalRecords'] > 0:
        data = history_data['data']
        
        # 模拟温度分析计算
        temperatures = [record['temperature'] for record in data]
        target_temp = data[0]['target_temp']
        
        # 简化的分析结果
        analysis_result = {
            "temperature_stats": {
                "min_temp": min(temperatures),
                "max_temp": max(temperatures),
                "avg_temp": sum(temperatures) / len(temperatures),
                "target_temp": target_temp
            },
            "performance_metrics": {
                "steady_state_error": abs(sum(temperatures) / len(temperatures) - target_temp),
                "overshoot": max(0, max(temperatures) - target_temp),
                "temperature_stability": max(temperatures) - min(temperatures)
            },
            "pid_parameters": {
                "kp": data[0]['kp'],
                "ki": data[0]['ki'], 
                "kd": data[0]['kd']
            }
        }
        
        response = {
            "status": "success",
            "table": history_data['table'],
            "start_time": history_data['start_time'],
            "end_time": history_data['end_time'],
            "analysis_result": analysis_result
        }
        
        print("📊 温度分析结果:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        
        return response
    else:
        print("❌ 无法进行温度分析：历史数据获取失败")
        return {"status": "error", "message": "历史数据获取失败"}

def simulate_pid_optimization():
    """模拟PID优化接口调用"""
    
    print("\n\n⚙️  模拟调用PID优化接口")
    print("=" * 60)
    
    # 基于温度分析结果给出PID优化建议
    temp_analysis = simulate_temperature_analysis()
    
    if temp_analysis['status'] == 'success':
        analysis = temp_analysis['analysis_result']
        current_pid = analysis['pid_parameters']
        performance = analysis['performance_metrics']
        
        # 简化的PID优化建议逻辑
        optimization_suggestions = []
        
        if performance['steady_state_error'] > 2.0:
            optimization_suggestions.append({
                "parameter": "ki",
                "current_value": current_pid['ki'],
                "suggested_value": current_pid['ki'] * 1.2,
                "reason": "稳态误差较大，建议增加积分参数"
            })
        
        if performance['overshoot'] > 5.0:
            optimization_suggestions.append({
                "parameter": "kp", 
                "current_value": current_pid['kp'],
                "suggested_value": current_pid['kp'] * 0.8,
                "reason": "超调量过大，建议减少比例参数"
            })
        
        if performance['temperature_stability'] > 10.0:
            optimization_suggestions.append({
                "parameter": "kd",
                "current_value": current_pid['kd'],
                "suggested_value": current_pid['kd'] * 1.1,
                "reason": "温度波动较大，建议增加微分参数"
            })
        
        optimization_result = {
            "current_performance": performance,
            "current_pid_parameters": current_pid,
            "optimization_suggestions": optimization_suggestions,
            "overall_assessment": "系统性能需要优化" if optimization_suggestions else "系统性能良好"
        }
        
        response = {
            "status": "success",
            "table": temp_analysis['table'],
            "start_time": temp_analysis['start_time'],
            "end_time": temp_analysis['end_time'],
            "optimization_result": optimization_result
        }
        
        print("⚙️  PID优化建议:")
        print(json.dumps(response, indent=2, ensure_ascii=False))
        
        return response
    else:
        print("❌ 无法进行PID优化：温度分析失败")
        return {"status": "error", "message": "温度分析失败"}

if __name__ == "__main__":
    print("🔧 PID Agent API 模拟调用工具")
    print("模拟对CSV文件 'fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811.csv' 的查询")
    print("=" * 80)
    
    # 1. 模拟历史数据查询
    simulate_history_data_query()
    
    # 2. 模拟温度分析
    simulate_temperature_analysis()
    
    # 3. 模拟PID优化
    simulate_pid_optimization()
    
    print("\n✅ 所有模拟调用完成!")