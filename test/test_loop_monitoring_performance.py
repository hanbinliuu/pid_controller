#!/usr/bin/env python3
"""
回路监控性能评估方法的测试脚本
测试 calculate_performance_status_last_24h 方法的功能
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
import numpy as np
from api.services.loop_monitoring_service import LoopMonitoringService
from core.algorithm.tmp_algo.stability_rate import PerformanceEvaluator


def test_performance_evaluator_methods():
    """测试 PerformanceEvaluator 的各个方法"""
    print("=" * 60)
    print("测试 PerformanceEvaluator 方法")
    print("=" * 60)
    
    # 生成模拟数据（24小时）
    np.random.seed(42)
    samples = 1440  # 1分钟采样，共1440个点（24小时）
    
    time = np.linspace(0, 24*3600, samples)  # 秒
    sv = np.ones(samples) * 50  # 设定值50
    pv = sv + np.random.normal(0, 1, samples)  # PV在50±1之间波动
    mv = np.linspace(30, 70, samples) + np.random.normal(0, 2, samples)  # MV从30到70
    auto_status = np.ones(samples)  # 全部自动
    
    # 1. 测试自控率计算
    print("\n1. 测试自控率计算（投入度维度）")
    auto_control_result = PerformanceEvaluator.calculate_auto_control_rate(
        time=time.tolist(),
        auto_status=auto_status.tolist()
    )
    print(f"   自控率: {auto_control_result.get('auto_control_rate', 0):.2f}%")
    print(f"   自动时长: {auto_control_result.get('auto_control_time', 0)} 秒")
    print(f"   总时长: {auto_control_result.get('total_time', 0)} 秒")
    
    # 2. 测试平稳率计算
    print("\n2. 测试平稳率计算（稳定性维度）")
    stability_result = PerformanceEvaluator.calculate_stability_rate_auto(
        time=time.tolist(),
        PV=pv.tolist(),
        SV=sv.tolist(),
        auto_status=auto_status.tolist(),
        threshold_percent=2.0
    )
    print(f"   平稳率: {stability_result.get('stability_rate', 0):.2f}%")
    print(f"   平稳时长: {stability_result.get('stable_time', 0)} 秒")
    print(f"   自动运行时长: {stability_result.get('auto_time', 0)} 秒")
    
    # 3. 测试精确性计算
    print("\n3. 测试精确性计算（标准偏差）")
    precision_result = PerformanceEvaluator.calculate_precision_std_auto(
        PV=pv.tolist(),
        SV=sv.tolist(),
        auto_status=auto_status.tolist(),
        use_SV=True
    )
    print(f"   标准差（相对设定值）: {precision_result.get('sigma_sp', 0):.4f}%")
    print(f"   标准差（相对均值）: {precision_result.get('sigma_mean', 0):.4f}")
    
    # 4. 测试高效性计算
    print("\n4. 测试高效性计算（阀门活动度）")
    efficiency_result = PerformanceEvaluator.calculate_valve_activity_auto(
        time=time.tolist(),
        MV=mv.tolist(),
        auto_status=auto_status.tolist()
    )
    print(f"   累计绝对变化 (CAC): {efficiency_result.get('cac', 0):.2f}")
    print(f"   输出标准差: {efficiency_result.get('op_std', 0):.2f}")
    
    # 计算综合评分
    print("\n5. 计算综合评分")
    auto_score = min(100, auto_control_result.get('auto_control_rate', 0))
    stability_score = min(100, stability_result.get('stability_rate', 0))
    
    precision_std = precision_result.get('sigma_sp', 0)
    if precision_std < 0.5:
        precision_score = 100
    elif precision_std > 2.0:
        precision_score = 0
    else:
        precision_score = 100 - (precision_std - 0.5) / (2.0 - 0.5) * 100
    
    valve_cac = efficiency_result.get('cac', 0)
    if valve_cac < 1000:
        efficiency_score = 100
    elif valve_cac > 5000:
        efficiency_score = 0
    else:
        efficiency_score = 100 - (valve_cac - 1000) / (5000 - 1000) * 100
    
    comprehensive_score = (
        auto_score * 0.2 +
        stability_score * 0.4 +
        precision_score * 0.3 +
        efficiency_score * 0.1
    )
    
    print(f"   自控率得分: {auto_score:.2f} (权重20%)")
    print(f"   平稳率得分: {stability_score:.2f} (权重40%)")
    print(f"   精确性得分: {precision_score:.2f} (权重30%)")
    print(f"   高效性得分: {efficiency_score:.2f} (权重10%)")
    print(f"   综合评分: {comprehensive_score:.2f}")
    
    # 判断性能等级
    if comprehensive_score >= 85:
        status = "优秀"
    elif comprehensive_score >= 70:
        status = "良好"
    elif comprehensive_score >= 50:
        status = "一般"
    else:
        status = "差"
    
    print(f"   性能等级: {status}")
    
    print("\n" + "=" * 60)
    print("✓ 所有方法测试完成")
    print("=" * 60)


if __name__ == "__main__":
    try:
        test_performance_evaluator_methods()
    except Exception as e:
        print(f"\n✗ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
