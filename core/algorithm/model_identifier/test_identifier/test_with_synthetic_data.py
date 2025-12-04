"""
使用数学方法生成模拟数据测试 model_type_detector.py
生成多个扰动段（阶跃响应），验证：
1. 逐窗口计算 KTL，取中位数
2. 用中位数 KTL 在全量数据上评分
"""
import sys
import os
# test_identifier -> model_identifier -> algorithm -> core -> pid-agent-mvp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict
from datetime import datetime, timedelta

from core.algorithm.model_identifier.model_type_detector import (
    ModelTypeDetector, ModelFitter, HistoricalData
)
from core.algorithm.model_identifier.config import ModelType

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'STHeiti']
plt.rcParams['axes.unicode_minus'] = False


def generate_fopdt_response(K: float, T: float, L: float, 
                             t: np.ndarray, u: np.ndarray, y0: float = 0) -> np.ndarray:
    """生成 FOPDT 模型响应
    
    G(s) = K / (Ts + 1) * e^(-Ls)
    """
    dt = t[1] - t[0] if len(t) > 1 else 1.0
    y = np.zeros(len(t))
    y[0] = y0
    
    for i in range(1, len(t)):
        # 滞后处理
        delayed_idx = max(0, i - int(L / dt))
        u_delayed = u[delayed_idx]
        # 一阶响应
        y[i] = y[i-1] + (dt / T) * (K * u_delayed - y[i-1])
    
    return y


def generate_multi_disturbance_data(
    K: float = 1.5, T: float = 30.0, L: float = 5.0,
    num_disturbances: int = 3,
    disturbance_duration: float = 200,  # 每个扰动段持续时间（秒）
    steady_duration: float = 100,       # 稳态段持续时间（秒）
    dt: float = 1.0,                    # 采样间隔（秒）
    noise_std: float = 0.05,            # 噪声标准差
    mv_base: float = 50.0,              # MV 基准值
    mv_step: float = 10.0               # MV 阶跃幅度
) -> tuple:
    """
    生成包含多个扰动段的模拟数据
    
    Returns:
        (data_list, tuning_windows, true_params)
    """
    # 计算总时间
    total_duration = num_disturbances * (disturbance_duration + steady_duration)
    t = np.arange(0, total_duration, dt)
    n = len(t)
    
    # 生成 MV 信号（多个阶跃）
    mv = np.ones(n) * mv_base
    sv = np.ones(n) * 3.0  # 设定值
    
    tuning_windows = []
    base_ts = int(datetime.now().timestamp() * 1000)  # 基准时间戳
    
    for i in range(num_disturbances):
        # 计算扰动段的起止时间
        start_idx = int((i * (disturbance_duration + steady_duration) + steady_duration / 2) / dt)
        end_idx = int((i * (disturbance_duration + steady_duration) + steady_duration / 2 + disturbance_duration) / dt)
        
        # 阶跃方向交替
        step_direction = 1 if i % 2 == 0 else -1
        mv[start_idx:end_idx] = mv_base + step_direction * mv_step
        
        # 记录 tuning_window
        tuning_windows.append({
            'start_time': base_ts + int(start_idx * dt * 1000),
            'end_time': base_ts + int(end_idx * dt * 1000)
        })
    
    # 生成 PV 响应
    pv = generate_fopdt_response(K, T, L, t, mv, y0=K * mv_base)
    
    # 添加噪声
    pv += np.random.normal(0, noise_std, n)
    
    # 转换为数据格式
    data = []
    for i in range(n):
        data.append({
            'timestamp': base_ts + int(t[i] * 1000),
            'pv': float(pv[i]),
            'sv': float(sv[i]),
            'mv': float(mv[i])
        })
    
    true_params = {'K': K, 'T1': T, 'T2': 0.0, 'L': L}
    
    return data, tuning_windows, true_params, t, pv, mv


def visualize_synthetic_data(t, pv, mv, tuning_windows, base_ts, save_path=None):
    """可视化生成的模拟数据"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    
    ax1, ax2 = axes
    
    # PV 曲线
    ax1.plot(t, pv, 'b-', label='PV', linewidth=1)
    ax1.set_ylabel('PV')
    ax1.set_title('模拟数据 - 多扰动段 FOPDT 响应')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # MV 曲线
    ax2.plot(t, mv, 'orange', linewidth=1.5, label='MV')
    ax2.set_ylabel('MV (%)')
    ax2.set_xlabel('时间 (秒)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # 标记 tuning_window
    colors = ['green', 'red', 'purple', 'cyan']
    for i, window in enumerate(tuning_windows):
        start_t = (window['start_time'] - base_ts) / 1000
        end_t = (window['end_time'] - base_ts) / 1000
        color = colors[i % len(colors)]
        for ax in axes:
            ax.axvspan(start_t, end_t, alpha=0.2, color=color, label=f'Window {i+1}' if ax == ax1 else None)
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"图表已保存: {save_path}")
    else:
        plt.show()
    plt.close()


def test_model_fitter_with_synthetic_data():
    """测试 ModelFitter 逻辑"""
    print("="*70)
    print("使用模拟数据测试 ModelFitter")
    print("="*70)
    
    # 真实参数
    true_K, true_T, true_L = 1.5, 30.0, 5.0
    
    # 生成数据
    print(f"\n📌 真实参数: K={true_K}, T={true_T}, L={true_L}")
    print(f"📌 生成 3 个扰动段...")
    
    data, tuning_windows, true_params, t, pv, mv = generate_multi_disturbance_data(
        K=true_K, T=true_T, L=true_L,
        num_disturbances=3,
        disturbance_duration=200,
        steady_duration=100,
        noise_std=0.05
    )
    
    base_ts = data[0]['timestamp']
    
    print(f"📌 数据点数: {len(data)}")
    print(f"📌 Tuning windows: {len(tuning_windows)} 个")
    for i, w in enumerate(tuning_windows):
        duration = (w['end_time'] - w['start_time']) / 1000
        print(f"   Window {i+1}: {duration:.0f} 秒")
    
    # 可视化
    script_dir = os.path.dirname(os.path.abspath(__file__))
    visualize_synthetic_data(t, pv, mv, tuning_windows, base_ts, 
                             os.path.join(script_dir, "synthetic_data.png"))
    
    # 构建 stability_result
    stability_result = {
        'start_time': data[0]['timestamp'],
        'end_time': data[-1]['timestamp'],
        'params': {'window_size': 20, 'step_size': 10},
        'total_windows': len(tuning_windows),
        'tuning_window': tuning_windows
    }
    
    # 测试 ModelFitter
    print("\n" + "="*70)
    print("测试 ModelFitter（预期流程）")
    print("="*70)
    print("1. 对每个模型类型，逐窗口计算 KTL，取中位数")
    print("2. 用各模型的中位数 KTL 在全量数据上评分")
    print("3. 选择 R² 最高的模型作为最终结果")
    print("="*70)
    
    fitter = ModelFitter(verbose=True, enable_preprocess=False)
    result = fitter.fit(stability_result, data, lambda_factor=0.8)
    
    # 打印结果
    print("\n" + "="*70)
    print("测试结果")
    print("="*70)
    print(f"检测到的模型类型: {result['model_type']}")
    print(f"模型评分: {result['model_rating']}")
    print(f"\n模型参数:")
    print(f"  K  = {result['model_parameters']['K']:.4f}  (真实值: {true_K})")
    print(f"  T1 = {result['model_parameters']['T1']:.4f}  (真实值: {true_T})")
    print(f"  T2 = {result['model_parameters']['T2']:.4f}  (真实值: 0.0)")
    print(f"  L  = {result['model_parameters']['L']:.4f}  (真实值: {true_L})")
    
    print(f"\nPID 参数:")
    print(f"  Kp = {result['pid_parameters']['Kp']:.4f}")
    print(f"  Ki = {result['pid_parameters']['Ki']:.4f}")
    print(f"  Kd = {result['pid_parameters']['Kd']:.4f}")
    
    print(f"\n拟合质量:")
    print(f"  R² = {result['fitting_result']['r_squared']:.4f}")
    print(f"  RMSE = {result['fitting_result']['rmse']:.4f}")
    
    # 计算参数误差
    K_error = abs(result['model_parameters']['K'] - true_K) / true_K * 100
    T_error = abs(result['model_parameters']['T1'] - true_T) / true_T * 100
    L_error = abs(result['model_parameters']['L'] - true_L) / max(true_L, 0.1) * 100
    
    print(f"\n参数误差:")
    print(f"  K 误差: {K_error:.1f}%")
    print(f"  T 误差: {T_error:.1f}%")
    print(f"  L 误差: {L_error:.1f}%")
    
    # 可视化拟合结果
    if result['fitting_result']['pv_model']:
        visualize_fit_result(result, true_params, script_dir)
    
    return result


def visualize_fit_result(result, true_params, script_dir):
    """可视化拟合结果"""
    fig, ax = plt.subplots(figsize=(14, 6))
    
    timestamps = np.array(result['fitting_result']['timestamp'])
    t = (timestamps - timestamps[0]) / 1000  # 转换为秒
    pv = result['fitting_result']['pv']
    pv_model = result['fitting_result']['pv_model']
    
    ax.plot(t, pv, 'b-', label='实际 PV', linewidth=1, alpha=0.7)
    ax.plot(t, pv_model, 'r-', label=f"模型预测 ({result['model_type']}, R²={result['fitting_result']['r_squared']:.4f})", linewidth=2)
    
    ax.set_xlabel('时间 (秒)')
    ax.set_ylabel('PV')
    ax.set_title(f"模型拟合结果\n真实参数: K={true_params['K']}, T={true_params['T1']}, L={true_params['L']} | "
                 f"辨识参数: K={result['model_parameters']['K']:.2f}, T={result['model_parameters']['T1']:.2f}, L={result['model_parameters']['L']:.2f}")
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    save_path = os.path.join(script_dir, "synthetic_fit_result.png")
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    print(f"\n拟合图表已保存: {save_path}")
    plt.close()


def test_model_type_detector_with_synthetic_data():
    """测试 ModelTypeDetector"""
    print("\n" + "="*70)
    print("测试 ModelTypeDetector")
    print("="*70)
    
    # 生成 FOPDT 数据
    data, _, true_params, _, _, _ = generate_multi_disturbance_data(
        K=1.5, T=30.0, L=5.0,
        num_disturbances=1,
        disturbance_duration=300,
        steady_duration=50,
        noise_std=0.05
    )
    
    print(f"数据点数: {len(data)}")
    print(f"真实参数: {true_params}")
    
    detector = ModelTypeDetector(verbose=True, enable_preprocess=False)
    result = detector.detect_by_r2(data)
    
    print(f"\n检测结果:")
    print(f"  模型类型: {result['model_type']}")
    print(f"  模型评分: {result['model_rating']}")
    print(f"  R² 评分: {result['r2_scores']}")


if __name__ == "__main__":
    np.random.seed(42)  # 固定随机种子
    
    # 测试 ModelFitter
    test_model_fitter_with_synthetic_data()
    
    # 测试 ModelTypeDetector
    test_model_type_detector_with_synthetic_data()
    
    print("\n" + "="*70)
    print("测试完成!")
    print("="*70)
