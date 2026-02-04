"""PID 自适应整定连续演示

生成一组连续数据展示：
1. 扰动工况下 PV/SV/MV 走势（老PID参数，振荡/不稳定）
2. 使用 core/algorithm/model_type 自适应整定算法计算新参数
3. 应用新参数后系统变稳定（PV 跟随 SV）

使用方法:
    python -m core.algorithm.model_type.tests.test_continuous_tuning
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import matplotlib.dates as mdates

# 导入整定算法
from core.algorithm.model_type.model_selector import ModelSelector


# ============================================================
# 过程模型和控制器
# ============================================================
class FOPDTProcess:
    """一阶加纯滞后过程模型"""
    
    def __init__(self, K: float, T1: float, L: float, dt: float = 1.0):
        self.K = K
        self.T1 = T1
        self.L = L
        self.dt = dt
        self.delay_steps = max(1, int(L / dt))
        self.mv_buffer = []
        self.pv = 0.0
    
    def reset(self, pv_initial: float = 0.0):
        self.pv = pv_initial
        self.mv_buffer = [pv_initial / self.K if self.K != 0 else 0] * self.delay_steps
    
    def set_params(self, K: float, T1: float, L: float):
        self.K = K
        self.T1 = T1
        new_delay_steps = max(1, int(L / self.dt))
        if new_delay_steps > len(self.mv_buffer):
            self.mv_buffer = [self.mv_buffer[-1]] * (new_delay_steps - len(self.mv_buffer)) + self.mv_buffer
        elif new_delay_steps < len(self.mv_buffer):
            self.mv_buffer = self.mv_buffer[-new_delay_steps:]
        self.L = L
        self.delay_steps = new_delay_steps
    
    def step(self, mv: float) -> float:
        self.mv_buffer.append(mv)
        mv_delayed = self.mv_buffer.pop(0)
        alpha = self.dt / (self.T1 + self.dt)
        pv_ss = self.K * mv_delayed
        self.pv = self.pv + alpha * (pv_ss - self.pv)
        return self.pv


class PIDController:
    """PID控制器"""
    
    def __init__(self, Kp: float, Ki: float, Kd: float, dt: float = 1.0,
                 mv_min: float = 0.0, mv_max: float = 100.0):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.dt = dt
        self.mv_min = mv_min
        self.mv_max = mv_max
        self.integral = 0.0
        self.prev_error = 0.0
        self.mv = 0.0
    
    def reset(self, mv_initial: float = 0.0):
        self.integral = 0.0
        self.prev_error = 0.0
        self.mv = mv_initial
    
    def set_params(self, Kp: float, Ki: float, Kd: float):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
    
    def compute(self, sv: float, pv: float) -> float:
        error = sv - pv
        P = self.Kp * error
        self.integral += error * self.dt
        I = self.Ki * self.integral
        derivative = (error - self.prev_error) / self.dt if self.dt > 0 else 0
        D = self.Kd * derivative
        self.prev_error = error
        mv = P + I + D
        mv = np.clip(mv, self.mv_min, self.mv_max)
        if mv >= self.mv_max or mv <= self.mv_min:
            self.integral -= error * self.dt
        self.mv = mv
        return mv


# ============================================================
# 配置
# ============================================================
CONFIG = {
    # 过程模型参数
    'process_original': {
        'K': 1.0,
        'T1': 30.0,
        'L': 5.0,
    },
    # 扰动后过程参数变化（导致持续振荡）
    'process_changed': {
        'K': 2.0,        # 增益翻倍
        'T1': 14.0,      # 时间常数减小
        'L': 10.0,       # 滞后增加
    },
    
    # 老 PID 参数（变化后导致持续振荡）
    'pid_old': {
        'Kp': 1.2,       # 激进的 Kp
        'Ki': 0.08,      # 较大的 Ki
        'Kd': 0.0,
    },
    
    # 仿真参数
    'dt': 1.0,
    'noise_std': 0.15,   # 基础噪声
    
    # 场景时长
    'steady_duration': 600,        # 初始稳态 10分钟
    'disturbance_duration': 1800,  # 扰动/振荡 30分钟
    'tuned_duration': 1200,        # 整定后稳定 20分钟
    
    # 设定值
    'sv': 48.0,
    
    # 量程缩放
    'scale': 1000.0,   # 48 * 1000 = 48000
    
    # MV 显示范围
    'mv_display_min': 15.0,
    'mv_display_max': 35.0,
    
    # 随机扰动参数（使振荡不规则）
    'random_disturbance_interval': (80, 200),  # 扰动间隔（秒）
    'random_disturbance_magnitude': 0.15,      # 扰动幅度（相对于SV）
    
    # 输出目录
    'output_dir': 'core/algorithm/model_type/tests/results',
}


def generate_continuous_scenario() -> Tuple[List[Dict], Dict, int, int]:
    """
    生成连续场景数据：稳态 → 扰动(振荡) → 整定 → 稳定
    
    Returns:
        history_data: 完整历史数据
        tuning_result: 整定结果
        disturbance_step: 扰动开始的步骤
        tuning_step: 整定应用的步骤
    """
    cfg = CONFIG
    dt = cfg['dt']
    sv = cfg['sv']
    scale = cfg['scale']
    
    # 创建过程和控制器
    process = FOPDTProcess(
        K=cfg['process_original']['K'],
        T1=cfg['process_original']['T1'],
        L=cfg['process_original']['L'],
        dt=dt
    )
    
    controller = PIDController(
        Kp=cfg['pid_old']['Kp'],
        Ki=cfg['pid_old']['Ki'],
        Kd=cfg['pid_old']['Kd'],
        dt=dt
    )
    
    # 初始化
    mv_ss = sv / cfg['process_original']['K']
    process.reset(pv_initial=sv)
    controller.reset(mv_initial=mv_ss)
    controller.integral = mv_ss / cfg['pid_old']['Ki'] if cfg['pid_old']['Ki'] > 0 else 0
    
    # 计算步数
    steady_steps = int(cfg['steady_duration'] / dt)
    disturbance_steps = int(cfg['disturbance_duration'] / dt)
    tuned_steps = int(cfg['tuned_duration'] / dt)
    total_steps = steady_steps + disturbance_steps + tuned_steps
    
    disturbance_step = steady_steps
    tuning_step = steady_steps + disturbance_steps
    
    start_time = datetime(2018, 1, 16, 8, 0, 0)
    
    history_data = []
    pv = sv
    tuning_result = None
    new_pid = None
    next_gain_change = steady_steps + 100  # 初始化动态增益变化时间点
    
    print(f"📊 生成连续场景数据...")
    print(f"   阶段1: 稳态 ({cfg['steady_duration']}s)")
    print(f"   阶段2: 扰动/振荡 ({cfg['disturbance_duration']}s)")
    print(f"   阶段3: 整定后稳定 ({cfg['tuned_duration']}s)")
    
    for step in range(total_steps):
        current_time = start_time + timedelta(seconds=step * dt)
        timestamp = int(current_time.timestamp() * 1000)
        
        # 阶段判断
        if step < steady_steps:
            phase = 'steady'
        elif step < tuning_step:
            phase = 'disturbance'
            # 系统参数变化（模拟扰动导致的系统特性改变）
            if step == disturbance_step:
                print(f"   ⚡ Step {step}: 系统扰动开始，过程参数改变")
                process.set_params(
                    K=cfg['process_changed']['K'],
                    T1=cfg['process_changed']['T1'],
                    L=cfg['process_changed']['L']
                )
                next_gain_change = step + np.random.randint(*cfg['random_disturbance_interval'])
            
            # 动态调整过程增益（使振荡幅度变化）
            if step >= disturbance_step and step == next_gain_change:
                k_variation = np.random.uniform(0.75, 1.25)  # ±25% 变化
                t1_variation = np.random.uniform(0.9, 1.1)   # ±10% 时间常数变化
                new_K = cfg['process_changed']['K'] * k_variation
                new_T1 = cfg['process_changed']['T1'] * t1_variation
                process.set_params(
                    K=new_K,
                    T1=new_T1,
                    L=cfg['process_changed']['L']
                )
                next_gain_change = step + np.random.randint(50, 150)  # 更频繁变化
        else:
            phase = 'tuned'
            # 应用整定后的参数
            if step == tuning_step:
                # 在这里进行整定（使用扰动阶段的数据）
                print(f"   🔧 Step {step}: 运行整定算法...")
                tuning_result = run_tuning(history_data, disturbance_step)
                
                if tuning_result and tuning_result.get('success'):
                    new_pid = tuning_result.get('pid_parameters', {})
                    controller.set_params(
                        Kp=new_pid.get('kp', cfg['pid_old']['Kp']),
                        Ki=new_pid.get('ki', cfg['pid_old']['Ki']),
                        Kd=new_pid.get('kd', cfg['pid_old']['Kd'])
                    )
                    # 重置积分项避免突变
                    controller.integral = controller.mv / new_pid.get('ki', 0.01) if new_pid.get('ki', 0) > 0 else 0
                    print(f"   ✅ 应用新参数: Kp={new_pid.get('kp'):.4f}, Ki={new_pid.get('ki'):.4f}")
        
        # 控制计算
        mv = controller.compute(sv, pv)
        pv_true = process.step(mv)
        
        # 添加基础噪声
        noise = np.random.normal(0, cfg['noise_std'])
        
        # 在振荡阶段添加随机扰动（使振荡不规则）
        if phase == 'disturbance':
            # 随机时刻添加额外扰动
            if np.random.random() < 0.03:  # 3% 概率
                noise += np.random.uniform(-1, 1) * cfg['random_disturbance_magnitude'] * sv
            # 添加变化的噪声幅度
            noise *= np.random.uniform(0.6, 1.4)
        
        pv = pv_true + noise
        
        # 记录数据（缩放到工业量程）
        history_data.append({
            'timestamp': timestamp,
            'pv': pv * scale,
            'sv': sv * scale,
            'mv': cfg['mv_display_min'] + (mv / 100) * (cfg['mv_display_max'] - cfg['mv_display_min']),
            'phase': phase,
        })
    
    print(f"   总数据点: {len(history_data)}")
    
    return history_data, tuning_result, disturbance_step, tuning_step


def run_tuning(history_data: List[Dict], start_idx: int) -> Dict:
    """使用 ModelSelector 进行整定"""
    
    # 只使用扰动阶段的数据进行整定
    tuning_data = history_data[start_idx:]
    
    # 构建扰动窗口
    n = len(tuning_data)
    windows = [{
        'start_time': tuning_data[n//4]['timestamp'],
        'end_time': tuning_data[-1]['timestamp'],
        'start_idx': n // 4,
        'end_idx': n - 1,
    }]
    
    input_data = {
        'history_data': tuning_data,
        'params': {'model_type': None, 'turning_type': None, 'analyst_column': 'pv'},
        'qualified_windows': windows,
    }
    
    selector = ModelSelector(verbose=False)
    result = selector.run(input_data)
    
    return result


def visualize_continuous_scenario(history_data: List[Dict], tuning_result: Dict,
                                   disturbance_step: int, tuning_step: int):
    """可视化连续场景 - 两个子图（上: PV/SV, 下: MV）"""
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 提取数据
    timestamps = [datetime.fromtimestamp(d['timestamp'] / 1000) for d in history_data]
    pv = [d['pv'] for d in history_data]
    sv = [d['sv'] for d in history_data]
    mv = [d['mv'] for d in history_data]
    
    # 创建两个子图
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True, 
                                    gridspec_kw={'height_ratios': [2, 1]})
    
    # 采样绘图
    sample_step = max(1, len(timestamps) // 3000)
    t = timestamps[::sample_step]
    pv_s = pv[::sample_step]
    sv_s = sv[::sample_step]
    mv_s = mv[::sample_step]
    
    # 标记阶段分界
    disturbance_time = timestamps[disturbance_step]
    tuning_time = timestamps[tuning_step]
    
    # ========== 上图: PV/SV ==========
    # 背景色区分阶段
    ax1.axvspan(timestamps[0], disturbance_time, alpha=0.15, color='green')
    ax1.axvspan(disturbance_time, tuning_time, alpha=0.15, color='red')
    ax1.axvspan(tuning_time, timestamps[-1], alpha=0.15, color='blue')
    
    ax1.plot(t, sv_s, 'r-', label='SV (设定值)', linewidth=2)
    ax1.plot(t, pv_s, 'b-', label='PV (过程值)', linewidth=1, alpha=0.8)
    
    ax1.axvline(x=disturbance_time, color='orange', linestyle='--', linewidth=2)
    ax1.axvline(x=tuning_time, color='purple', linestyle='--', linewidth=2)
    
    ax1.set_ylabel('PV / SV', fontsize=11)
    ax1.legend(loc='upper right', fontsize=10)
    ax1.grid(True, alpha=0.3)
    
    # 添加整定结果标注
    if tuning_result and tuning_result.get('success'):
        pid = tuning_result.get('pid_parameters', {})
        old_pid = CONFIG['pid_old']
        info_text = (
            f"Old: Kp={old_pid['Kp']}, Ki={old_pid['Ki']}\n"
            f"New: Kp={pid.get('kp', 0):.3f}, Ki={pid.get('ki', 0):.4f}\n"
            f"PB={pid.get('pb', 0):.1f}%"
        )
        ax1.text(0.02, 0.98, info_text, transform=ax1.transAxes, fontsize=9,
                 verticalalignment='top', fontfamily='monospace',
                 bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.9))
    
    # 添加阶段标注
    ax1.text(0.08, 0.92, '稳态', transform=ax1.transAxes, fontsize=10, 
             color='darkgreen', fontweight='bold')
    ax1.text(0.4, 0.92, '扰动/振荡', transform=ax1.transAxes, fontsize=10, 
             color='darkred', fontweight='bold')
    ax1.text(0.82, 0.92, '整定后稳定', transform=ax1.transAxes, fontsize=10, 
             color='darkblue', fontweight='bold')
    
    # 设置标题
    ax1.set_title('PID 自适应整定效果演示: 扰动 → 振荡 → 整定 → 稳定跟踪', 
                  fontsize=14, fontweight='bold')
    
    # ========== 下图: MV ==========
    ax2.axvspan(timestamps[0], disturbance_time, alpha=0.15, color='green')
    ax2.axvspan(disturbance_time, tuning_time, alpha=0.15, color='red')
    ax2.axvspan(tuning_time, timestamps[-1], alpha=0.15, color='blue')
    
    ax2.plot(t, mv_s, 'g-', label='MV (控制输出)', linewidth=1)
    ax2.axvline(x=disturbance_time, color='orange', linestyle='--', linewidth=2)
    ax2.axvline(x=tuning_time, color='purple', linestyle='--', linewidth=2)
    
    ax2.set_xlabel('时间', fontsize=11)
    ax2.set_ylabel('MV (%)', fontsize=11)
    ax2.legend(loc='upper right', fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    
    plt.tight_layout()
    
    # 保存
    os.makedirs(CONFIG['output_dir'], exist_ok=True)
    filename = f'continuous_tuning_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    filepath = os.path.join(CONFIG['output_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white')
    print(f"\n📊 图表已保存: {filepath}")
    plt.close()
    
    return filepath


def calculate_phase_errors(history_data: List[Dict], disturbance_step: int, tuning_step: int) -> Dict:
    """计算各阶段的控制偏差"""
    sv = np.array([d['sv'] for d in history_data])
    pv = np.array([d['pv'] for d in history_data])
    
    # 稳态阶段
    steady_error = np.mean(np.abs(pv[:disturbance_step] - sv[:disturbance_step]) / sv[:disturbance_step]) * 100
    
    # 振荡阶段
    disturbance_error = np.mean(np.abs(pv[disturbance_step:tuning_step] - sv[disturbance_step:tuning_step]) / sv[disturbance_step:tuning_step]) * 100
    
    # 整定后阶段（取后半段）
    tuned_start = tuning_step + (len(history_data) - tuning_step) // 2
    tuned_error = np.mean(np.abs(pv[tuned_start:] - sv[tuned_start:]) / sv[tuned_start:]) * 100
    
    return {
        'steady': steady_error,
        'disturbance': disturbance_error,
        'tuned': tuned_error,
    }


def main():
    print("=" * 70)
    print("PID 自适应整定连续演示")
    print("场景: 稳态 → 扰动(振荡) → 自适应整定 → PV跟随SV")
    print("=" * 70)
    
    # 生成连续场景数据
    history_data, tuning_result, disturbance_step, tuning_step = generate_continuous_scenario()
    
    # 计算各阶段偏差
    errors = calculate_phase_errors(history_data, disturbance_step, tuning_step)
    
    # 可视化
    print("\n📈 生成可视化图表...")
    filepath = visualize_continuous_scenario(history_data, tuning_result, disturbance_step, tuning_step)
    
    # 输出结果
    print("\n" + "=" * 70)
    print("结果汇总")
    print("=" * 70)
    
    print(f"\n各阶段控制偏差:")
    print(f"   稳态阶段:       {errors['steady']:.2f}%")
    print(f"   扰动/振荡阶段:  {errors['disturbance']:.2f}%")
    print(f"   整定后阶段:     {errors['tuned']:.2f}%")
    
    if tuning_result and tuning_result.get('success'):
        pid = tuning_result.get('pid_parameters', {})
        print(f"\n整定参数:")
        print(f"   老参数: Kp={CONFIG['pid_old']['Kp']}, Ki={CONFIG['pid_old']['Ki']}, Kd={CONFIG['pid_old']['Kd']}")
        print(f"   新参数: Kp={pid.get('kp', 0):.4f}, Ki={pid.get('ki', 0):.4f}, Kd={pid.get('kd', 0):.4f}")
        print(f"   比例带: {pid.get('pb', 0):.1f}%")
    
    if errors['disturbance'] > 0:
        improvement = (errors['disturbance'] - errors['tuned']) / errors['disturbance'] * 100
        print(f"\n✅ 偏差改善: {improvement:.1f}%")
    
    print("\n✅ 测试完成!")
    
    return history_data, tuning_result


if __name__ == "__main__":
    main()
