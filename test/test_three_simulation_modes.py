"""
测试三种仿真模式：拟合、闭环、阶跃响应
"""
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8001/api/analysis"


def test_three_simulation_modes():
    """
    测试返回的三种仿真模式数据
    1. simulation (拟合模式) - 模型拟合实际数据
    2. simulation_closed_loop (闭环模式) - 使用推荐PID参数的闭环仿真
    3. simulation_step_response (阶跃响应模式) - 系统阶跃响应曲线
    """
    print("\n=== 测试三种仿真模式 ===\n")
    
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
    
    try:
        response = requests.post(f"{BASE_URL}/auto-tuning", params=params, timeout=60)
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get('status') == 'success':
                opt_result = result.get('optimization_result', {})
                lambda_params = opt_result.get('tuning_suggestions', {}).get('lambda_suggested_params', {})
                
                # 显示推荐的PID参数
                pid_params = lambda_params.get('params', {})
                print("=" * 60)
                print("推荐的PID参数:")
                print(f"  Kp: {pid_params.get('Kp', 'N/A'):.4f}")
                print(f"  Ti: {pid_params.get('Ti', 'N/A'):.4f}")
                print(f"  Td: {pid_params.get('Td', 'N/A'):.4f}")
                print("=" * 60)
                
                # 1. 测试拟合模式
                print("\n【模式1：拟合模式 (simulation)】")
                print("-" * 60)
                simulation_fit = lambda_params.get('simulation', {})
                if simulation_fit:
                    print(f"模式标识: {simulation_fit.get('mode')}")
                    print(f"数据点数: {len(simulation_fit.get('time', []))}")
                    print(f"包含字段: {list(simulation_fit.keys())}")
                    
                    # 验证必要字段
                    required_fields = ['time', 'pv_actual', 'pv_model', 'mv', 'sv']
                    missing = [f for f in required_fields if f not in simulation_fit]
                    if missing:
                        print(f"✗ 缺少字段: {missing}")
                    else:
                        print(f"✓ 包含所有必要字段")
                        
                        fit_metrics = simulation_fit.get('fit_metrics', {})
                        print(f"\n拟合指标:")
                        print(f"  R²: {fit_metrics.get('r_squared', 0):.4f}")
                        print(f"  RMSE: {fit_metrics.get('rmse', 0):.4f}")
                else:
                    print("✗ 未找到拟合模式数据")
                
                # 2. 测试闭环模式
                print("\n【模式2：闭环仿真 (simulation_closed_loop)】")
                print("-" * 60)
                simulation_closed = lambda_params.get('simulation_closed_loop', {})
                if simulation_closed:
                    print(f"模式标识: {simulation_closed.get('mode')}")
                    print(f"描述: {simulation_closed.get('description')}")
                    print(f"数据点数: {len(simulation_closed.get('time', []))}")
                    
                    pv_data = simulation_closed.get('pv', [])
                    mv_data = simulation_closed.get('mv', [])
                    
                    if len(pv_data) > 0 and len(mv_data) > 0:
                        print(f"✓ 闭环仿真数据生成成功")
                        print(f"  PV范围: {min(pv_data):.2f} ~ {max(pv_data):.2f}")
                        print(f"  MV范围: {min(mv_data):.2f} ~ {max(mv_data):.2f}")
                    else:
                        print(f"✗ 闭环仿真数据为空")
                else:
                    print("✗ 未找到闭环仿真数据")
                
                # 3. 测试阶跃响应模式
                print("\n【模式3：阶跃响应 (simulation_step_response)】")
                print("-" * 60)
                simulation_step = lambda_params.get('simulation_step_response', {})
                if simulation_step:
                    print(f"模式标识: {simulation_step.get('mode')}")
                    print(f"描述: {simulation_step.get('description')}")
                    print(f"数据点数: {len(simulation_step.get('time', []))}")
                    
                    pv_step = simulation_step.get('pv', [])
                    mv_step = simulation_step.get('mv', [])
                    
                    if len(pv_step) > 0 and len(mv_step) > 0:
                        print(f"✓ 阶跃响应数据生成成功")
                        print(f"  时间范围: {simulation_step.get('time', [None, None])[0]:.0f}s ~ {simulation_step.get('time', [None, None])[-1]:.0f}s")
                        print(f"  PV范围: {min(pv_step):.2f} ~ {max(pv_step):.2f}")
                        print(f"  MV阶跃: 0 → {max(mv_step):.0f}")
                    else:
                        print(f"✗ 阶跃响应数据为空")
                else:
                    print("✗ 未找到阶跃响应数据")
                
                # 总结
                print("\n" + "=" * 60)
                print("三种仿真模式对比:")
                print("=" * 60)
                print(f"{'模式':<20} {'数据点':<10} {'状态'}")
                print("-" * 60)
                
                fit_count = len(simulation_fit.get('time', [])) if simulation_fit else 0
                closed_count = len(simulation_closed.get('time', [])) if simulation_closed else 0
                step_count = len(simulation_step.get('time', [])) if simulation_step else 0
                
                print(f"{'拟合模式':<20} {fit_count:<10} {'✓' if fit_count > 0 else '✗'}")
                print(f"{'闭环仿真':<20} {closed_count:<10} {'✓' if closed_count > 0 else '✗'}")
                print(f"{'阶跃响应':<20} {step_count:<10} {'✓' if step_count > 0 else '✗'}")
                
                # 数据结构示例
                print("\n" + "=" * 60)
                print("前端调用示例:")
                print("=" * 60)
                print("""
// 获取拟合模式数据
const fitData = response.optimization_result.tuning_suggestions
    .lambda_suggested_params.simulation;

// 获取闭环仿真数据
const closedLoopData = response.optimization_result.tuning_suggestions
    .lambda_suggested_params.simulation_closed_loop;

// 获取阶跃响应数据
const stepResponseData = response.optimization_result.tuning_suggestions
    .lambda_suggested_params.simulation_step_response;

// 绘制三条曲线对比
drawChart({
    fit: { time: fitData.time, pv: fitData.pv_model },
    closedLoop: { time: closedLoopData.time, pv: closedLoopData.pv },
    stepResponse: { time: stepResponseData.time, pv: stepResponseData.pv }
});
                """)
                
            else:
                print(f"\n✗ {result.get('message')}")
        else:
            print(f"✗ 请求失败: {response.text}")
    
    except Exception as e:
        print(f"✗ 请求异常: {str(e)}")


if __name__ == "__main__":
    print("=" * 60)
    print("三种仿真模式测试")
    print("=" * 60)
    
    test_three_simulation_modes()
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
