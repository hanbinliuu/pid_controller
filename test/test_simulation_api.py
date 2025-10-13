#!/usr/bin/env python3
"""
测试数据模拟API接口
验证所有模拟数据生成接口的功能
"""

import requests
import json
from datetime import datetime, timedelta
import time

def test_simulation_api():
    """测试模拟数据API接口"""
    
    base_url = "http://localhost:8001/api/simulation"
    
    print("🔧 测试数据模拟API接口")
    print("=" * 60)
    
    # 1. 测试健康检查
    print("\n🏥 测试健康检查...")
    try:
        response = requests.get(f"{base_url}/health")
        print(f"✅ 健康检查: {response.status_code}")
        if response.status_code == 200:
            print(f"   响应: {response.json()}")
    except Exception as e:
        print(f"❌ 健康检查失败: {e}")
    
    # 2. 测试获取模拟场景列表
    print("\n📋 测试获取模拟场景列表...")
    try:
        response = requests.get(f"{base_url}/simulation-scenarios")
        print(f"✅ 场景列表: {response.status_code}")
        if response.status_code == 200:
            scenarios = response.json()
            print(f"   支持的场景数: {scenarios['total_scenarios']}")
            for name, info in scenarios['scenarios'].items():
                print(f"   - {name}: {info['name']}")
    except Exception as e:
        print(f"❌ 获取场景列表失败: {e}")
    
    # 3. 测试基于时间范围生成模拟数据
    print("\n📊 测试基于时间范围生成模拟数据...")
    try:
        # 生成最近2小时的数据
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - (2 * 60 * 60 * 1000)  # 2小时前
        
        request_data = {
            "table": "test_simulation_api",
            "start_time": start_time,
            "end_time": end_time
        }
        
        print(f"   请求参数: {json.dumps(request_data, indent=2)}")
        
        response = requests.post(f"{base_url}/generate-simulation-data", json=request_data)
        print(f"✅ 时间范围模拟: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   生成记录数: {result['total_records']}")
            print(f"   时长: {result['duration_hours']:.2f} 小时")
            print(f"   CSV文件: {result['files_generated']['csv']}")
            print(f"   JSON文件: {result['files_generated']['json']}")
        else:
            print(f"   错误: {response.text}")
            
    except Exception as e:
        print(f"❌ 时间范围模拟失败: {e}")
    
    # 4. 测试自定义参数模拟
    print("\n🎛️  测试自定义参数模拟...")
    try:
        request_data = {
            "table": "test_custom_simulation",
            "duration_hours": 1.0,
            "sample_interval": 10.0,
            "scenario": "normal"
        }
        
        print(f"   请求参数: {json.dumps(request_data, indent=2)}")
        
        response = requests.post(f"{base_url}/generate-custom-simulation", json=request_data)
        print(f"✅ 自定义模拟: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   场景: {result['scenario']}")
            print(f"   记录数: {result['total_records']}")
            print(f"   温度统计: {result['temperature_stats']}")
        else:
            print(f"   错误: {response.text}")
            
    except Exception as e:
        print(f"❌ 自定义模拟失败: {e}")
    
    # 5. 测试固定PID参数模拟
    print("\n⚙️  测试固定PID参数模拟...")
    try:
        request_data = {
            "table": "test_fixed_pid",
            "kp": 1.5,
            "ki": 0.1,
            "kd": 0.05,
            "target_temp": 35.0,
            "duration_hours": 0.5,
            "sample_interval": 5.0
        }
        
        print(f"   请求参数: {json.dumps(request_data, indent=2)}")
        
        response = requests.post(f"{base_url}/generate-fixed-pid-simulation", json=request_data)
        print(f"✅ 固定PID模拟: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   PID参数: Kp={result['pid_parameters']['kp']}, Ki={result['pid_parameters']['ki']}, Kd={result['pid_parameters']['kd']}")
            print(f"   记录数: {result['total_records']}")
            print(f"   性能指标: {result['performance_metrics']}")
        else:
            print(f"   错误: {response.text}")
            
    except Exception as e:
        print(f"❌ 固定PID模拟失败: {e}")
    
    # 6. 测试获取生成文件列表
    print("\n📁 测试获取生成文件列表...")
    try:
        response = requests.get(f"{base_url}/simulation-files")
        print(f"✅ 文件列表: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"   文件总数: {result['total_files']}")
            print(f"   数据目录: {result['data_directory']}")
            if result['files']:
                print("   最新文件:")
                for file_info in result['files'][:3]:  # 显示前3个文件
                    print(f"     - {file_info['filename']} ({file_info['size_mb']} MB)")
        else:
            print(f"   错误: {response.text}")
            
    except Exception as e:
        print(f"❌ 获取文件列表失败: {e}")

def test_parameter_validation():
    """测试参数验证"""
    print("\n\n🔍 测试参数验证")
    print("=" * 60)
    
    base_url = "http://localhost:8001/api/simulation"
    
    # 测试无效时间范围
    print("\n❌ 测试无效时间范围...")
    try:
        request_data = {
            "table": "test_invalid",
            "start_time": 1000000000000,  # 很大的时间戳
            "end_time": 999999999999    # 小于start_time
        }
        
        response = requests.post(f"{base_url}/generate-simulation-data", json=request_data)
        print(f"   响应状态: {response.status_code}")
        if response.status_code != 200:
            print(f"   ✅ 正确拒绝了无效参数")
        else:
            print(f"   ⚠️  意外接受了无效参数")
            
    except Exception as e:
        print(f"   测试异常: {e}")
    
    # 测试无效PID参数
    print("\n❌ 测试无效PID参数...")
    try:
        request_data = {
            "table": "test_invalid_pid",
            "kp": -1.0,  # 负值
            "ki": 0.1,
            "kd": 0.05,
            "target_temp": 35.0,
            "duration_hours": 1.0
        }
        
        response = requests.post(f"{base_url}/generate-fixed-pid-simulation", json=request_data)
        print(f"   响应状态: {response.status_code}")
        if response.status_code != 200:
            print(f"   ✅ 正确拒绝了无效PID参数")
        else:
            print(f"   ⚠️  意外接受了无效PID参数")
            
    except Exception as e:
        print(f"   测试异常: {e}")

def test_api_performance():
    """测试API性能"""
    print("\n\n⚡ 测试API性能")
    print("=" * 60)
    
    base_url = "http://localhost:8001/api/simulation"
    
    # 测试小数据量生成速度
    print("\n📊 测试小数据量生成...")
    try:
        start_time = time.time()
        
        request_data = {
            "table": "performance_test_small",
            "duration_hours": 0.1,  # 6分钟
            "sample_interval": 5.0,
            "scenario": "normal"
        }
        
        response = requests.post(f"{base_url}/generate-custom-simulation", json=request_data)
        end_time = time.time()
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ 生成成功")
            print(f"   耗时: {end_time - start_time:.2f} 秒")
            print(f"   记录数: {result['total_records']}")
            print(f"   平均速度: {result['total_records'] / (end_time - start_time):.0f} 记录/秒")
        else:
            print(f"   ❌ 生成失败: {response.text}")
            
    except Exception as e:
        print(f"   测试异常: {e}")

if __name__ == "__main__":
    print("🧪 PID数据模拟API测试工具")
    print("确保API服务器正在运行...")
    
    # 等待服务器启动
    print("等待API服务器响应...")
    time.sleep(2)
    
    try:
        # 基础功能测试
        test_simulation_api()
        
        # 参数验证测试
        test_parameter_validation()
        
        # 性能测试
        test_api_performance()
        
        print("\n\n🎉 所有测试完成!")
        
    except KeyboardInterrupt:
        print("\n\n⏹️  测试被用户中断")
    except Exception as e:
        print(f"\n\n❌ 测试过程中发生错误: {e}")