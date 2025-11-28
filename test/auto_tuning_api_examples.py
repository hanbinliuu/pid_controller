"""
自动整定API接口使用示例

接口路径: POST /api/analysis/auto-tuning

支持两种模式：
1. auto - 自动筛选最佳时间窗口并整定
2. manual - 手动指定时间范围整定
"""

import requests
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8001/api/analysis"


# ========================================
# 示例1: 自动筛选整定（推荐使用）
# ========================================
def example_auto_tuning():
    """
    自动模式会：
    1. 扫描指定时间范围内的历史数据
    2. 自动识别包含阶跃响应的高质量窗口
    3. 选择置信度最高的窗口进行参数辨识
    4. 返回Lambda整定的PID参数建议
    """
    # 分析最近1天的数据
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 24 * 60 * 60 * 1000  # 24小时前
    
    params = {
        "mode": "auto",                      # 自动模式
        "start_time": start_time,            # 数据查询起始时间
        "end_time": end_time,                # 数据查询结束时间
        "model_type": "FO_INTEGRATOR",       # 一阶积分模型（适合流量/液位）
        "is_lambda": True,                   # 启用Lambda整定
        "window_size": 120,                  # 窗口大小（分钟）
        "step_size": 30,                     # 滑动步长（分钟）
        "confidence_threshold": 0.5,         # 置信度阈值（0-1）
        "window_sec": 60,                    # 数据采样间隔（秒）
        "is_filter": False                   # 是否过滤历史数据
    }
    
    response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=120)
    
    if response.status_code == 200:
        result = response.json()
        
        if result['status'] == 'success':
            print("✓ 自动整定成功")
            print(f"  选中窗口: {result['time_range']['start_timestamp']} - {result['time_range']['end_timestamp']}")
            print(f"  置信度: {result['window_selection']['selected_window']['confidence']:.2f}")
            print(f"  推荐PID参数: {result['optimization_result']['tuning_suggestions']['lambda_suggested_params']['params']}")
        elif result['status'] == 'warning':
            print(f"⚠ {result['message']}")
            print("  建议：降低confidence_threshold或增加window_size")
    else:
        print(f"✗ 请求失败: {response.text}")


# ========================================
# 示例2: 手动指定时间范围整定
# ========================================
def example_manual_tuning():
    """
    手动模式适用于：
    1. 已知某个时间段数据质量较好
    2. 需要对特定工况进行参数整定
    3. 对比不同时间段的整定结果
    """
    # 指定具体时间范围（最近2小时）
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 2 * 60 * 60 * 1000  # 2小时前
    
    params = {
        "mode": "manual",                    # 手动模式
        "start_time": start_time,            # 必填：起始时间
        "end_time": end_time,                # 必填：结束时间
        "model_type": "FO_INTEGRATOR",       # 模型类型
        "is_lambda": True,                   # 启用Lambda整定
        "window_sec": 60                     # 数据采样间隔
    }
    
    response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
    
    if response.status_code == 200:
        result = response.json()
        
        if result['status'] == 'success':
            print("✓ 手动整定成功")
            print(f"  分析时长: {result['time_range']['duration_seconds']}秒")
            print(f"  当前PID: {result['optimization_result']['current_params']}")
            print(f"  建议PID: {result['optimization_result']['tuning_suggestions']['lambda_suggested_params']['params']}")
    else:
        print(f"✗ 请求失败: {response.text}")


# ========================================
# 示例3: 使用字符串时间格式
# ========================================
def example_string_time():
    """
    支持多种时间格式：
    - 毫秒时间戳: 1640995200000
    - 字符串格式: "2025-01-01 12:00:00"
    - ISO格式: "2025-01-01T12:00:00"
    """
    params = {
        "mode": "manual",
        "start_time": "2025-01-15 10:00:00",  # 字符串格式
        "end_time": "2025-01-15 12:00:00",
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True
    }
    
    response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
    print(f"状态: {response.status_code}")


# ========================================
# 示例4: 不同模型类型的整定
# ========================================
def example_different_models():
    """
    支持的模型类型：
    - FOPDT: 一阶加纯滞后（通用工业过程）
    - FO: 纯一阶模型（无滞后系统）
    - SOPDT: 二阶加纯滞后（温度、化学反应）
    - SO: 纯二阶模型（无滞后）
    - FO_INTEGRATOR: 一阶积分模型（流量、液位）
    - SO_INTEGRATOR: 二阶积分模型（双积分过程）
    """
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 3600000  # 1小时
    
    # 一阶积分模型（适合流量控制）
    params_integrator = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",  # 一阶积分
        "is_lambda": True
    }
    
    # FOPDT模型（适合温度控制）
    params_fopdt = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FOPDT",          # 一阶加滞后
        "is_lambda": True
    }
    
    print("不同模型类型整定示例")
    print("- 流量控制建议使用: FO_INTEGRATOR")
    print("- 温度控制建议使用: FOPDT 或 SOPDT")
    print("- 液位控制建议使用: FO_INTEGRATOR")


# ========================================
# 示例5: Lambda参数调节
# ========================================
def example_lambda_parameter():
    """
    Lambda参数影响控制响应特性：
    - λ越小：响应越快，但更敏感
    - λ越大：响应越慢，但更稳健
    - 默认值：自动根据模型时间常数计算
    """
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 3600000
    
    # 快速响应（激进）
    params_fast = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "lambda_val": 10.0  # 较小的lambda
    }
    
    # 稳健响应（保守）
    params_robust = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "lambda_val": 100.0  # 较大的lambda
    }
    
    print("Lambda参数调节示例")
    print("- 追求快速响应: lambda_val = 10-50")
    print("- 追求稳定性: lambda_val = 80-200")
    print("- 自动优化: 不指定lambda_val参数")


# ========================================
# 返回数据结构说明
# ========================================
def response_structure_example():
    """
    成功响应结构：
    {
        "status": "success",
        "mode": "auto" 或 "manual",
        "table": "数据表名",
        "time_range": {
            "start_timestamp": 开始时间戳,
            "end_timestamp": 结束时间戳,
            "duration_seconds": 时长（秒）
        },
        "model_type": "模型类型",
        "lambda_tuning_enabled": true/false,
        "optimization_result": {
            "current_params": {当前PID参数},
            "performance": {性能指标},
            "status": {控制状态评估},
            "tuning_suggestions": {
                "lambda_suggested_params": {
                    "params": {推荐的PID参数},
                    "model": {辨识的模型参数},
                    "model_evaluation": {模型拟合质量}
                }
            }
        },
        "window_selection": {  # 仅auto模式
            "total_qualified_windows": 合格窗口数,
            "selected_window": {
                "confidence": 置信度,
                "step_size": 阶跃大小,
                "response_magnitude": 响应幅度
            },
            "selection_params": {筛选参数}
        }
    }
    """
    pass


if __name__ == "__main__":
    print("=== 自动整定API使用示例 ===\n")
    
    print("运行示例1: 自动筛选整定")
    # example_auto_tuning()
    
    print("\n运行示例2: 手动指定时间范围整定")
    example_manual_tuning()
    
    print("\n其他示例请参考代码注释")
