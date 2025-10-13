#!/usr/bin/env python3
"""
PID参数转换工具测试脚本
"""

import sys
import os

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.utils.pid_converter import PIDConverter, convert_pid_to_pb, convert_pb_to_pid


def test_pid_converter():
    """测试PID参数转换功能"""
    print("=" * 60)
    print("PID参数转换工具测试")
    print("=" * 60)
    
    # 测试案例1: 标准PID参数转换
    print("\n1. PID参数转换为经典控制参数:")
    kp, ki, kd = 2.0, 0.5, 0.1
    print(f"输入PID参数: Kp={kp}, Ki={ki}, Kd={kd}")
    
    classical = convert_pid_to_pb(kp, ki, kd)
    print(f"转换结果:")
    print(f"  比例带 PB = {classical['proportional_band']:.2f}%")
    print(f"  积分时间 Ti = {classical['integral_time']:.2f}秒")
    print(f"  微分时间 Td = {classical['derivative_time']:.4f}秒")
    
    # 测试案例2: 经典控制参数转换为PID
    print("\n2. 经典控制参数转换为PID参数:")
    pb, ti, td = 50.0, 4.0, 0.05
    print(f"输入经典参数: PB={pb}%, Ti={ti}秒, Td={td}秒")
    
    pid = convert_pb_to_pid(pb, ti, td)
    print(f"转换结果:")
    print(f"  比例增益 Kp = {pid['kp']:.4f}")
    print(f"  积分增益 Ki = {pid['ki']:.4f}")
    print(f"  微分增益 Kd = {pid['kd']:.4f}")
    
    # 测试案例3: 双向转换验证
    print("\n3. 双向转换验证:")
    original_kp, original_ki, original_kd = 1.5, 0.3, 0.08
    print(f"原始PID: Kp={original_kp}, Ki={original_ki}, Kd={original_kd}")
    
    # PID -> 经典控制
    classical_params = convert_pid_to_pb(original_kp, original_ki, original_kd)
    print(f"转换为经典控制: PB={classical_params['proportional_band']:.2f}%, "
          f"Ti={classical_params['integral_time']:.2f}s, "
          f"Td={classical_params['derivative_time']:.4f}s")
    
    # 经典控制 -> PID
    recovered_pid = convert_pb_to_pid(
        classical_params['proportional_band'],
        classical_params['integral_time'],
        classical_params['derivative_time']
    )
    print(f"恢复的PID: Kp={recovered_pid['kp']:.4f}, "
          f"Ki={recovered_pid['ki']:.4f}, "
          f"Kd={recovered_pid['kd']:.4f}")
    
    # 验证误差
    kp_error = abs(original_kp - recovered_pid['kp'])
    ki_error = abs(original_ki - recovered_pid['ki'])
    kd_error = abs(original_kd - recovered_pid['kd'])
    print(f"转换误差: ΔKp={kp_error:.6f}, ΔKi={ki_error:.6f}, ΔKd={kd_error:.6f}")
    
    # 测试案例4: 格式化参数
    print("\n4. 参数格式化:")
    formatted = PIDConverter.format_pid_parameters(kp, ki, kd)
    print(f"格式化结果:")
    print(f"  标准PID: {formatted['standard']}")
    print(f"  经典控制: {formatted['classical']}")
    
    # 测试案例5: 参数验证
    print("\n5. 参数验证:")
    validation = PIDConverter.validate_pid_parameters(kp, ki, kd)
    print(f"验证结果: {validation}")
    
    # 测试案例6: 特殊情况
    print("\n6. 特殊情况测试:")
    
    # 只有比例控制 (P控制)
    print("  P控制 (Ki=0, Kd=0):")
    p_params = convert_pid_to_pb(2.0, 0.0, 0.0)
    print(f"    PB={p_params['proportional_band']:.2f}%, Ti=∞, Td={p_params['derivative_time']:.4f}s")
    
    # PI控制
    print("  PI控制 (Kd=0):")
    pi_params = convert_pid_to_pb(1.0, 0.2, 0.0)
    print(f"    PB={pi_params['proportional_band']:.2f}%, "
          f"Ti={pi_params['integral_time']:.2f}s, Td={pi_params['derivative_time']:.4f}s")
    
    # PD控制
    print("  PD控制 (Ki=0):")
    pd_params = convert_pid_to_pb(1.5, 0.0, 0.1)
    print(f"    PB={pd_params['proportional_band']:.2f}%, Ti=∞, "
          f"Td={pd_params['derivative_time']:.4f}s")
    
    print("\n" + "=" * 60)
    print("测试完成!")


if __name__ == "__main__":
    test_pid_converter()