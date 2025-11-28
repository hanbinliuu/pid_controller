"""
测试仿真曲线参数返回
"""
import requests
import json
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import numpy as np

BASE_URL = "http://localhost:8001/api/analysis"


def test_simulation_curve_data():
    """
    测试返回的仿真曲线数据
    验证返回结果中包含：
    - time: 时间序列
    - pv_actual: 实际PV曲线
    - pv_model: 模型仿真PV曲线
    - mv: MV操纵量曲线
    """
    print("\n=== 测试仿真曲线数据返回 ===")
    
    # 使用手动模式，指定时间范围
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 2 * 60 * 60 * 1000  # 2小时前
    
    params = {
        "mode": "manual",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_sec": 60
    }
    
    print(f"请求参数: {json.dumps(params, indent=2, ensure_ascii=False)}")
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        print(f"\n响应状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('status') == 'success':
                # 提取仿真数据
                opt_result = result.get('optimization_result', {})
                lambda_params = opt_result.get('tuning_suggestions', {}).get('lambda_suggested_params', {})
                simulation = lambda_params.get('simulation', {})
                
                print("\n✓ 获取到仿真曲线数据:")
                print(f"  包含字段: {list(simulation.keys())}")
                
                # 验证必要字段
                required_fields = ['time', 'pv_actual', 'pv_model', 'mv']
                missing_fields = [f for f in required_fields if f not in simulation]
                
                if missing_fields:
                    print(f"  ✗ 缺少字段: {missing_fields}")
                else:
                    print(f"  ✓ 所有必要字段都存在")
                    
                    # 显示数据统计
                    time_data = simulation.get('time', [])
                    pv_actual = simulation.get('pv_actual', [])
                    pv_model = simulation.get('pv_model', [])
                    mv_data = simulation.get('mv', [])
                    
                    print(f"\n  数据统计:")
                    print(f"    时间点数: {len(time_data)}")
                    print(f"    PV实际值数量: {len(pv_actual)}")
                    print(f"    PV模型值数量: {len(pv_model)}")
                    print(f"    MV数量: {len(mv_data)}")
                    
                    if len(time_data) > 0:
                        print(f"\n    时间范围: {time_data[0]:.2f}s ~ {time_data[-1]:.2f}s")
                        print(f"    PV实际值范围: {min(pv_actual):.2f} ~ {max(pv_actual):.2f}")
                        print(f"    PV模型值范围: {min(pv_model):.2f} ~ {max(pv_model):.2f}")
                        print(f"    MV范围: {min(mv_data):.2f} ~ {max(mv_data):.2f}")
                    
                    # 显示拟合指标
                    fit_metrics = simulation.get('fit_metrics', {})
                    print(f"\n  拟合指标:")
                    print(f"    R²: {fit_metrics.get('r_squared', 'N/A'):.4f}")
                    print(f"    RMSE: {fit_metrics.get('rmse', 'N/A'):.4f}")
                    
                    # 显示模型参数
                    model = lambda_params.get('model', {})
                    print(f"\n  模型参数:")
                    print(f"    K (增益): {model.get('K', 'N/A')}")
                    print(f"    T1 (时间常数): {model.get('T1', 'N/A')}")
                    
                    # 显示推荐PID参数
                    pid_params = lambda_params.get('params', {})
                    print(f"\n  推荐PID参数:")
                    print(f"    Kp: {pid_params.get('Kp', 'N/A'):.4f}")
                    print(f"    Ti: {pid_params.get('Ti', 'N/A'):.4f}")
                    print(f"    Td: {pid_params.get('Td', 'N/A'):.4f}")
                    
                    # 绘制曲线（可选）
                    if len(time_data) > 0:
                        plot_curves(time_data, pv_actual, pv_model, mv_data, fit_metrics)
                
            else:
                print(f"\n✗ {result.get('message')}")
        else:
            print(f"✗ 请求失败: {response.text}")
    
    except Exception as e:
        print(f"✗ 请求异常: {str(e)}")


def plot_curves(time_data, pv_actual, pv_model, mv_data, fit_metrics):
    """
    绘制仿真曲线对比图
    """
    print("\n  正在生成曲线对比图...")
    
    try:
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        # 子图1: PV对比
        ax1.plot(time_data, pv_actual, 'b-', linewidth=2, label='PV实际值', alpha=0.8)
        ax1.plot(time_data, pv_model, 'r--', linewidth=2, label='PV模型预测', alpha=0.8)
        ax1.set_ylabel('PV', fontsize=12)
        ax1.set_xlabel('时间 (秒)', fontsize=12)
        ax1.set_title(f'PV对比 (R²={fit_metrics.get("r_squared", 0):.4f}, RMSE={fit_metrics.get("rmse", 0):.4f})', 
                      fontsize=14, fontweight='bold')
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)
        
        # 子图2: MV
        ax2.plot(time_data, mv_data, 'g-', linewidth=2, label='MV操纵量')
        ax2.set_ylabel('MV (%)', fontsize=12)
        ax2.set_xlabel('时间 (秒)', fontsize=12)
        ax2.set_title('MV操纵量曲线', fontsize=14, fontweight='bold')
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        # 保存图片
        output_path = '/tmp/simulation_curves_test.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        print(f"  ✓ 曲线图已保存: {output_path}")
        
        # 显示图片（如果在本地环境）
        # plt.show()
        
    except Exception as e:
        print(f"  ✗ 绘图失败: {str(e)}")


def test_auto_mode_simulation_data():
    """
    测试自动模式下的仿真曲线数据
    """
    print("\n=== 测试自动模式仿真曲线数据 ===")
    
    end_time = int(datetime.now().timestamp() * 1000)
    start_time = end_time - 6 * 60 * 60 * 1000  # 6小时前
    
    params = {
        "mode": "auto",
        "start_time": start_time,
        "end_time": end_time,
        "model_type": "FO_INTEGRATOR",
        "is_lambda": True,
        "window_size": 60,
        "step_size": 20,
        "confidence_threshold": 0.3,
        "window_sec": 60
    }
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=120)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('status') == 'success':
                simulation = result.get('optimization_result', {}).get('tuning_suggestions', {}).get(
                    'lambda_suggested_params', {}).get('simulation', {})
                
                if 'time' in simulation:
                    print(f"  ✓ 自动模式也包含仿真曲线数据")
                    print(f"    数据点数: {len(simulation.get('time', []))}")
                else:
                    print(f"  ✗ 自动模式缺少仿真曲线数据")
            elif result.get('status') == 'warning':
                print(f"  ⚠ {result.get('message')}")
        
    except Exception as e:
        print(f"  ✗ 异常: {str(e)}")


if __name__ == "__main__":
    print("=" * 60)
    print("仿真曲线参数测试")
    print("=" * 60)
    
    # 测试手动模式
    test_simulation_curve_data()
    
    # 测试自动模式
    # test_auto_mode_simulation_data()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
