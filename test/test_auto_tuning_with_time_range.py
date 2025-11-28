"""
测试自动整定接口 - 在指定时间范围内自动筛选最佳区间
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8001/api/analysis"


def test_auto_with_custom_time_range():
    """
    测试：在用户指定的时间范围内自动筛选最佳整定区间
    
    这是auto模式的核心功能：
    1. 用户传入一个较大的时间范围（如最近1周）
    2. 系统在该范围内自动扫描所有可能的窗口
    3. 基于阶跃响应检测和置信度评分，选择最佳窗口
    4. 对最佳窗口进行参数辨识和Lambda整定
    """
    print("\n=== 测试：在指定时间范围内自动筛选最佳区间 ===")
    
    # 用户指定分析最近6小时的数据
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 6 * 60 * 60 * 1000  # 6小时前
    
    print(f"指定时间范围: {datetime.fromtimestamp(start_time/1000)} 到 {datetime.fromtimestamp(end_time/1000)}")
    print(f"时间跨度: 6小时")
    
    params = {
        "mode": "auto",                      # 自动筛选模式
        "start_time": start_time,            # 用户指定的起始时间
        "end_time": end_time,                # 用户指定的结束时间
        "model_type": "FO_INTEGRATOR",       # 一阶积分模型
        "is_lambda": True,
        "window_size": 60,                   # 每个窗口60分钟
        "step_size": 15,                     # 每15分钟滑动一次
        "confidence_threshold": 0.4,         # 置信度阈值0.4
        "window_sec": 60,
        "is_filter": False
    }
    
    print(f"\n扫描参数:")
    print(f"  窗口大小: {params['window_size']} 分钟")
    print(f"  滑动步长: {params['step_size']} 分钟")
    print(f"  置信度阈值: {params['confidence_threshold']}")
    
    try:
        print("\n正在分析，请稍候...")
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=120)
        print(f"\n响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"分析状态: {result.get('status')}")
            print(f"模式: {result.get('mode')}")
            
            if result.get('status') == 'success':
                # 显示窗口筛选结果
                window_sel = result.get('window_selection', {})
                print(f"\n✓ 窗口筛选成功:")
                print(f"  检查的窗口总数: {window_sel.get('total_qualified_windows', 'N/A')}")
                
                selected = window_sel.get('selected_window', {})
                print(f"\n  选中的最佳窗口:")
                print(f"    置信度: {selected.get('confidence', 'N/A'):.3f}")
                print(f"    阶跃大小: {selected.get('step_size', 'N/A')}")
                print(f"    响应幅度: {selected.get('response_magnitude', 'N/A')}")
                
                # 显示时间范围
                time_range = result.get('time_range', {})
                selected_start = datetime.fromtimestamp(time_range.get('start_timestamp', 0)/1000)
                selected_end = datetime.fromtimestamp(time_range.get('end_timestamp', 0)/1000)
                print(f"\n  选中窗口的时间范围:")
                print(f"    开始: {selected_start}")
                print(f"    结束: {selected_end}")
                print(f"    时长: {time_range.get('duration_seconds', 0)/60:.1f} 分钟")
                
                # 显示整定结果
                opt_result = result.get('optimization_result', {})
                lambda_params = opt_result.get('tuning_suggestions', {}).get('lambda_suggested_params', {})
                
                if lambda_params:
                    params_dict = lambda_params.get('params', {})
                    model_dict = lambda_params.get('model', {})
                    
                    print(f"\n✓ Lambda整定结果:")
                    print(f"  推荐PID参数:")
                    print(f"    Kp: {params_dict.get('Kp', 'N/A'):.4f}")
                    print(f"    Ti: {params_dict.get('Ti', 'N/A'):.4f}")
                    print(f"    Td: {params_dict.get('Td', 'N/A'):.4f}")
                    
                    print(f"\n  辨识的模型参数:")
                    print(f"    K (增益): {model_dict.get('K', 'N/A'):.6f}")
                    print(f"    T (时间常数): {model_dict.get('T1', 'N/A'):.2f}")
                    print(f"    Lambda: {lambda_params.get('lambda', 'N/A'):.2f}")
                    
                    model_eval = lambda_params.get('model_evaluation', {})
                    print(f"\n  模型质量评估:")
                    print(f"    R²: {model_eval.get('r_squared', 'N/A'):.4f}")
                    print(f"    RMSE: {model_eval.get('rmse', 'N/A'):.4f}")
                    print(f"    质量等级: {model_eval.get('quality', 'N/A')}")
                
            elif result.get('status') == 'warning':
                print(f"\n⚠ {result.get('message')}")
                
                # 显示建议
                suggestion = result.get('suggestion', {})
                if suggestion:
                    print(f"\n建议调整参数:")
                    print(f"  当前置信度阈值: {suggestion.get('current_confidence_threshold')}")
                    print(f"  建议置信度阈值: {suggestion.get('suggested_confidence_threshold')}")
                    print(f"  当前窗口大小: {suggestion.get('current_window_size_minutes')} 分钟")
                    print(f"  建议窗口大小: {suggestion.get('suggested_window_size_minutes')} 分钟")
            else:
                print(f"\n✗ {result.get('message')}")
        else:
            print(f"✗ 请求失败: {response.text}")
    
    except Exception as e:
        print(f"✗ 请求异常: {str(e)}")


def test_auto_different_time_ranges():
    """
    测试不同时间范围的自动筛选效果
    """
    print("\n=== 测试不同时间范围的筛选效果 ===")
    
    test_cases = [
        {"hours": 2, "desc": "最近2小时"},
        {"hours": 6, "desc": "最近6小时"},
        {"hours": 12, "desc": "最近12小时"},
    ]
    
    for case in test_cases:
        print(f"\n--- {case['desc']} ---")
        
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - case['hours'] * 60 * 60 * 1000
        
        params = {
            "mode": "auto",
            "start_time": start_time,
            "end_time": end_time,
            "model_type": "FO_INTEGRATOR",
            "is_lambda": True,
            "window_size": 60,
            "step_size": 20,
            "confidence_threshold": 0.4,
            "window_sec": 60
        }
        
        try:
            response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('status') == 'success':
                    window_sel = result.get('window_selection', {})
                    selected = window_sel.get('selected_window', {})
                    print(f"  ✓ 找到合格窗口，置信度: {selected.get('confidence', 0):.3f}")
                elif result.get('status') == 'warning':
                    print(f"  ⚠ 未找到合格窗口")
            else:
                print(f"  ✗ 请求失败")
        
        except Exception as e:
            print(f"  ✗ 异常: {str(e)}")


def test_auto_with_string_time():
    """
    测试使用字符串时间格式的自动筛选
    """
    print("\n=== 测试字符串时间格式 ===")
    
    # 使用字符串时间格式
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = (datetime.now() - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"开始时间: {start_time}")
    print(f"结束时间: {end_time}")
    
    params = {
        "mode": "auto",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_size": 60,
        "step_size": 20,
        "confidence_threshold": 0.4
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        print(f"响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"状态: {result.get('status')}")
            if result.get('status') == 'success':
                print("✓ 字符串时间格式解析成功")
    
    except Exception as e:
        print(f"✗ 异常: {str(e)}")


if __name__ == "__main__":
    print("=" * 60)
    print("自动整定接口测试 - 在指定时间范围内自动筛选最佳区间")
    print("=" * 60)
    
    # 主要测试
    test_auto_with_custom_time_range()
    
    # 其他测试
    # test_auto_different_time_ranges()
    # test_auto_with_string_time()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
