"""
测试自动整定接口
"""
import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://localhost:8001/api/analysis"


def test_auto_mode():
    """测试自动筛选整定模式"""
    print("\n=== 测试自动筛选整定模式 ===")
    
    # 使用最近24小时的数据
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 24 * 60 * 60 * 1000
    
    params = {
        "mode": "auto",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_size": 120,
        "step_size": 30,
        "confidence_threshold": 0.5,
        "window_sec": 60,
        "is_filter": False
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"返回状态: {result.get('status')}")
            print(f"模式: {result.get('mode')}")
            
            if result.get('status') == 'success':
                time_range = result.get('time_range', {})
                print(f"\n选中时间窗口:")
                print(f"  开始: {time_range.get('start_timestamp')}")
                print(f"  结束: {time_range.get('end_timestamp')}")
                print(f"  时长: {time_range.get('duration_seconds')} 秒")
                
                window_sel = result.get('window_selection', {})
                print(f"\n窗口筛选信息:")
                print(f"  合格窗口数: {window_sel.get('total_qualified_windows')}")
                selected = window_sel.get('selected_window', {})
                print(f"  置信度: {selected.get('confidence')}")
                print(f"  阶跃大小: {selected.get('step_size')}")
                
                opt_result = result.get('optimization_result', {})
                print(f"\n整定结果:")
                print(json.dumps(opt_result, indent=2, ensure_ascii=False))
            else:
                print(f"消息: {result.get('message')}")
        else:
            print(f"错误: {response.text}")
    
    except Exception as e:
        print(f"请求异常: {str(e)}")


def test_manual_mode():
    """测试手动指定时间范围整定模式"""
    print("\n=== 测试手动指定时间范围整定模式 ===")
    
    # 手动指定最近2小时的数据
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 2 * 60 * 60 * 1000
    
    params = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_sec": 60,
        "is_filter": False
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"返回状态: {result.get('status')}")
            print(f"模式: {result.get('mode')}")
            
            if result.get('status') == 'success':
                time_range = result.get('time_range', {})
                print(f"\n分析时间窗口:")
                print(f"  开始: {time_range.get('start_timestamp')}")
                print(f"  结束: {time_range.get('end_timestamp')}")
                print(f"  时长: {time_range.get('duration_seconds')} 秒")
                
                opt_result = result.get('optimization_result', {})
                print(f"\n整定结果:")
                print(json.dumps(opt_result, indent=2, ensure_ascii=False))
            else:
                print(f"消息: {result.get('message')}")
        else:
            print(f"错误: {response.text}")
    
    except Exception as e:
        print(f"请求异常: {str(e)}")


def test_manual_mode_with_string_time():
    """测试手动模式使用字符串时间格式"""
    print("\n=== 测试手动模式（字符串时间格式）===")
    
    # 使用字符串时间格式
    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    start_time = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    
    params = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_sec": 60
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"返回状态: {result.get('status')}")
            print(f"消息: {result.get('message', 'N/A')}")
            
            if result.get('status') == 'success':
                opt_result = result.get('optimization_result', {})
                print(f"\n整定结果摘要:")
                if isinstance(opt_result, dict):
                    if 'pid_params' in opt_result:
                        print(f"  PID参数: {opt_result.get('pid_params')}")
        else:
            print(f"错误: {response.text}")
    
    except Exception as e:
        print(f"请求异常: {str(e)}")


def test_error_cases():
    """测试错误场景"""
    print("\n=== 测试错误场景 ===")
    
    # 测试1: manual模式缺少时间参数
    print("\n1. manual模式缺少时间参数:")
    params = {
        "mode": "manual",
        "model_type": "FO_INTEGRATOR"
    }
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=10)
        print(f"  状态码: {response.status_code}")
        if response.status_code == 400:
            print(f"  预期错误: {response.json().get('detail')}")
    except Exception as e:
        print(f"  异常: {str(e)}")
    
    # 测试2: 无效的mode参数
    print("\n2. 无效的mode参数:")
    params = {
        "mode": "invalid_mode",
        "start_time": int(datetime.now().timestamp() * 1000),
        "end_time": int(datetime.now().timestamp() * 1000)
    }
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=10)
        print(f"  状态码: {response.status_code}")
        if response.status_code == 400:
            print(f"  预期错误: {response.json().get('detail')}")
    except Exception as e:
        print(f"  异常: {str(e)}")


if __name__ == "__main__":
    print("开始测试自动整定API接口...")
    
    # 运行测试
    test_manual_mode_with_string_time()
    test_manual_mode()
    test_auto_mode()
    test_error_cases()
    
    print("\n所有测试完成!")
