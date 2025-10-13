#!/usr/bin/env python3
"""
测试修改后的MockTSDBDataSource是否能正确读取CSV文件
"""

import sys
import os
import json

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from core.data.mock_tsdb_api import MockTSDBDataSource, query_raw_data

def test_csv_reading():
    """测试CSV文件读取功能"""
    print("🔧 测试MockTSDBDataSource读取CSV文件")
    print("=" * 60)
    
    # 创建数据源实例
    data_source = MockTSDBDataSource()
    
    # 测试CSV文件表名
    csv_table = "fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811"
    
    print(f"📋 测试表名: {csv_table}")
    print(f"📂 CSV目录: {data_source.csv_dir}")
    

    # 测试查询数据（无过滤）
    print("\n📊 查询数据（前5条）...")
    result = data_source.query_raw_data(
        table=csv_table,
        limit=5
    )
    
    print(f"📈 查询结果:")
    print(f"   - 字段数: {len(result.columns) if result.columns else 0}")
    print(f"   - 数据行数: {len(result.values) if result.values else 0}")
    if result.columns:
        print(f"   - 字段: {result.columns}")
    if result.values and len(result.values) > 0:
        print(f"   - 首行数据: {result.values[0]}")
    
    # 测试时间范围查询
    print("\n⏰ 测试时间范围查询...")
    time_filtered_result = data_source.query_raw_data(
        table=csv_table,
        fields=["timestamp", "temperature", "target_temp", "kp", "ki", "kd"],
        start_time=1759109290968,
        end_time=1759109350968,
        limit=10
    )
    
    print(f"📈 时间过滤结果:")
    print(f"   - 字段数: {len(time_filtered_result.columns) if time_filtered_result.columns else 0}")
    print(f"   - 数据行数: {len(time_filtered_result.values) if time_filtered_result.values else 0}")
    if time_filtered_result.values and len(time_filtered_result.values) > 0:
        print(f"   - 首行数据: {time_filtered_result.values[0]}")
        print(f"   - 末行数据: {time_filtered_result.values[-1]}")

def test_api_integration():
    """测试API集成"""
    print("\n\n🔌 测试API集成")
    print("=" * 60)
    
    # 构造查询请求
    request_data = {
        "tables": [
            {
                "table": "fixed_pid_kp1_0_ki0_08_kd0_06_20250929_212811",
                "fields": ["timestamp", "temperature", "target_temp", "kp", "ki", "kd", "pid_output"]
            }
        ],
        "detail": {
            "startTime": 1759109290968,
            "endTime": 1759109350968,
            "limit": 5
        }
    }
    
    print(f"📋 请求数据:")
    print(json.dumps(request_data, indent=2, ensure_ascii=False))
    
    # 调用查询接口
    response = query_raw_data(request_data)
    
    print(f"\n📊 响应数据:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    
    # 验证响应
    if response.get("code") == 0:
        results = response.get("results", [])
        if results:
            table_result = results[0]
            data_points = table_result.get("data", [])
            if data_points:
                print(f"\nAPI测试成功!")
                print(f"   - 返回表数: {len(results)}")
                print(f"   - 数据点数: {len(data_points)}")
                if data_points[0].get("values"):
                    print(f"   - 数据行数: {len(data_points[0]['values'])}")
            else:
                print(f"未返回数据点")
        else:
            print(f"未返回查询结果")
    else:
        print(f"API调用失败: {response.get('message')}")

if __name__ == "__main__":
    try:
        test_csv_reading()
        test_api_integration()
        print("\n测试完成!")
    except Exception as e:
        print(f"测试失败: {str(e)}")
        import traceback
        traceback.print_exc()