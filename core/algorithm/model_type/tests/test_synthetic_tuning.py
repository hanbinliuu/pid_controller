"""合成数据整定验证测试

支持两种场景：
1. 振荡场景：稳态 → 系统变化 → 振荡 → 重新整定 → 稳态
   - 支持 LLM vs 规则引擎对比（通过 Config.OSCILLATION_TUNING['enable_llm'] 控制）
2. 正常扰动场景：稳态 → SV阶跃 → 正常响应（非振荡）→ 整定

使用方法:
    python -m core.algorithm.model_type.tests.test_synthetic_tuning
    python -m core.algorithm.model_type.tests.test_synthetic_tuning batch
    
    修改 SCENARIO 变量选择场景:
    - 'oscillation': 振荡场景（会对比 LLM vs 规则引擎）
    - 'normal_disturbance': 正常扰动场景
"""
import sys
import os
# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))))

import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import requests

from core.algorithm.model_type.model_selector import ModelSelector
from core.algorithm.model_type.config import Config

# 导入测试场景
from core.algorithm.model_type.tests.test_scenarios import TEST_SCENARIOS


# ============================================================
# Ollama 客户端
# ============================================================
class OllamaClient:
    """Ollama 本地模型客户端"""
    
    def __init__(self, model: str = "qwen:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
    
    def chat(self, prompt: str) -> str:
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 256,
                    }
                },
                timeout=120
            )
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError("无法连接到 Ollama，请确保已运行 'ollama serve'")
        except Exception as e:
            raise RuntimeError(f"Ollama 调用失败: {e}")


# ============================================================
# 测试模式选择（直接修改此变量即可切换测试模式）
# ============================================================
# 
# TEST_MODE 可选值 (对应4个验证目标):
#
#   'stability'   : 目标1 - 振荡场景稳态验证
#                   验证现有算法和LLM+算法能否在不同生产振荡场景中让控制器达到稳态
#
#   'llm_compare' : 目标2 - LLM 优化效果对比
#                   对比振荡场景下 LLM 参数 vs 纯规则引擎参数，验证LLM是否能优化参数
#
#   'amplitude'   : 目标3 - 振荡幅度阈值估计
#                   固定振荡场景，测试不同幅度，找出能回稳态/不能回稳态的边界
#
#   'lambda'      : 目标4 - Lambda 整定验证
#                   常规扰动下用模型辨识+Lambda整定在不同生产场景下验证能否回稳态
#
#   'all'         : 运行所有测试并生成汇总报告
#
# 向后兼容的旧模式（不推荐使用）:
#   'default', 'batch', 'model_id'
#
TEST_MODE = 'stability'

# SCENARIO 用于 default 模式时选择场景类型（向后兼容）
SCENARIO = 'oscillation'  # 'oscillation' 或 'normal_disturbance'


# ============================================================
# 配置
# ============================================================
CONFIG = {
    # Ollama 配置
    'ollama_model': 'qwen3-vl:8b',
    'ollama_base_url': 'http://localhost:11434',
    'skip_llm_test': False,  # 设为 True 可跳过 LLM 测试，只运行规则引擎
    
    # 原始过程模型参数（稳态时）
    'process_original': {
        'K': 1.0,           # 过程增益
        'T1': 30.0,         # 时间常数 (秒)
        'L': 2.0,           # 纯滞后 (秒) 
    },
    
    # 变化后的过程模型参数（导致振荡）
    # 增益变大3倍 + 滞后变大 -> 必然振荡
    'process_changed': {
        'K': 3.0,           # 增益变大3倍 -> 容易振荡
        'T1': 15.0,         # 时间常数变小 -> 响应更快
        'L': 8.0,           # 滞后变大4倍 -> 更容易振荡
    },
    
    # 原始PID参数（针对原始过程整定的，比较激进）
    'original_pid': {
        'Kp': 1.5,          # 较大的Kp
        'Ki': 0.08,         # 较大的Ki
        'Kd': 0.0,
    },

    # 数据生成参数
    'dt': 1.0,              # 采样周期 (秒)
    'noise_std': 0.2,       # 测量噪声标准差
    
    # 场景时长 (秒)
    'steady_duration': 300,      # 稳态段时长
    'oscillation_duration': 500, # 振荡段时长（系统变化后）
    'new_pid_duration': 300,     # 新PID运行时长
    
    # 设定值
    'sv': 50.0,
    'sv_step': 65.0,        # 阶跃后的SV（用于step_response场景）
    
    # 输出目录（相对于项目根目录）
    'output_dir': 'core/algorithm/model_type/tests/results',
}


# ============================================================
# 过程模型仿真
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
        """动态修改过程参数（模拟系统特性变化）"""
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
        """动态修改PID参数"""
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
# 数据生成：稳态 -> 振荡 -> 新PID稳态（振荡场景）
# ============================================================
def generate_oscillation_data() -> Tuple[List[Dict], Dict, Dict]:
    """
    生成振荡场景数据：稳态 → 系统变化导致振荡 → 新PID恢复稳态
    """
    cfg = CONFIG
    dt = cfg['dt']
    sv = cfg['sv']
    
    process = FOPDTProcess(
        K=cfg['process_original']['K'],
        T1=cfg['process_original']['T1'],
        L=cfg['process_original']['L'],
        dt=dt
    )
    
    controller = PIDController(
        Kp=cfg['original_pid']['Kp'],
        Ki=cfg['original_pid']['Ki'],
        Kd=cfg['original_pid']['Kd'],
        dt=dt
    )

    mv_ss = sv / cfg['process_original']['K']
    process.reset(pv_initial=sv)
    controller.reset(mv_initial=mv_ss)
    controller.integral = mv_ss / cfg['original_pid']['Ki'] if cfg['original_pid']['Ki'] > 0 else 0
    
    steady_steps = int(cfg['steady_duration'] / dt)
    osc_steps = int(cfg['oscillation_duration'] / dt)
    total_steps = steady_steps + osc_steps
    
    start_time = datetime.now() - timedelta(seconds=total_steps * dt)
    history_data = []
    change_time = None
    pv = sv
    
    for step in range(total_steps):
        current_time = start_time + timedelta(seconds=step * dt)
        timestamp = int(current_time.timestamp() * 1000)
        
        if step < steady_steps:
            phase = 'steady'
        else:
            phase = 'oscillation'
            if step == steady_steps:
                change_time = timestamp
                process.set_params(
                    K=cfg['process_changed']['K'],
                    T1=cfg['process_changed']['T1'],
                    L=cfg['process_changed']['L']
                )
                print(f"   ⚠️ System changed: K={cfg['process_changed']['K']}, T1={cfg['process_changed']['T1']}")
        
        mv = controller.compute(sv, pv)
        pv = process.step(mv)
        pv_noisy = pv + np.random.normal(0, cfg['noise_std'])
        
        history_data.append({
            'timestamp': timestamp,
            'pv': round(pv_noisy, 2),
            'sv': round(sv, 2),
            'mv': round(mv, 2),
            'phase': phase,
        })
    
    metadata = {
        'process_original': cfg['process_original'],
        'process_changed': cfg['process_changed'],
        'original_pid': cfg['original_pid'],
        'change_time': change_time,
        'sv': sv,
        'scenario': 'oscillation',
    }
    
    return history_data, metadata, None


# ============================================================
# 数据生成：稳态 -> 正常扰动 -> 恢复稳态（正常扰动场景）
# ============================================================
def generate_step_response_data() -> Tuple[List[Dict], Dict, Dict]:
    """
    生成正常扰动数据：稳态 → MV阶跃扰动 → 正常响应（非振荡）→ 恢复稳态
    
    场景说明：
    - 系统本身没问题，老参数也能恢复稳态
    - 但老参数可能响应慢、超调大
    - 整定目的是优化响应速度和超调量
    """
    cfg = CONFIG
    dt = cfg['dt']
    sv = cfg['sv']
    
    K = cfg['process_original']['K']
    T1 = cfg['process_original']['T1']
    L = cfg['process_original']['L']
    
    process = FOPDTProcess(K=K, T1=T1, L=L, dt=dt)
    
    # 使用较保守的PID参数（响应慢，但稳定）
    conservative_pid = {
        'Kp': 0.3,   # 较小的Kp -> 响应慢
        'Ki': 0.01,  # 较小的Ki -> 消除稳态误差慢
        'Kd': 0.0,
    }
    
    controller = PIDController(
        Kp=conservative_pid['Kp'],
        Ki=conservative_pid['Ki'],
        Kd=conservative_pid['Kd'],
        dt=dt
    )
    
    mv_ss = sv / K
    process.reset(pv_initial=sv)
    controller.reset(mv_initial=mv_ss)
    controller.integral = mv_ss / conservative_pid['Ki'] if conservative_pid['Ki'] > 0 else 0
    
    steady_steps = int(cfg['steady_duration'] / dt)
    response_steps = int(cfg['oscillation_duration'] / dt)
    total_steps = steady_steps + response_steps
    
    start_time = datetime.now() - timedelta(seconds=total_steps * dt)
    history_data = []
    disturbance_time = None
    pv = sv
    
    mv_step_size = 15.0
    mv_step_duration = 80
    
    for step in range(total_steps):
        current_time = start_time + timedelta(seconds=step * dt)
        timestamp = int(current_time.timestamp() * 1000)
        
        if step < steady_steps:
            phase = 'steady'
            mv = controller.compute(sv, pv)
        elif step < steady_steps + mv_step_duration:
            phase = 'disturbance'
            if step == steady_steps:
                disturbance_time = timestamp
                print(f"   📈 MV step disturbance: +{mv_step_size} for {mv_step_duration}s")
            mv_pid = controller.compute(sv, pv)
            mv = mv_pid + mv_step_size
            mv = np.clip(mv, 0, 100)
        else:
            phase = 'recovery'
            mv = controller.compute(sv, pv)
        
        pv = process.step(mv)
        pv_noisy = pv + np.random.normal(0, cfg['noise_std'])
        
        history_data.append({
            'timestamp': timestamp,
            'pv': round(pv_noisy, 2),
            'sv': round(sv, 2),
            'mv': round(mv, 2),
            'phase': phase,
        })
    
    metadata = {
        'process_original': cfg['process_original'],
        'process_changed': cfg['process_original'],
        'original_pid': conservative_pid,
        'change_time': disturbance_time,
        'sv': sv,
        'scenario': 'normal_disturbance',
    }
    
    return history_data, metadata, None


def generate_synthetic_data() -> Tuple[List[Dict], Dict, Dict]:
    """根据 SCENARIO 选择生成数据"""
    if SCENARIO == 'oscillation':
        return generate_oscillation_data()
    else:
        return generate_step_response_data()


def simulate_with_new_pid(process_params: Dict, pid_params: Dict,
                          sv: float, duration: float = 300, dt: float = 1.0,
                          error_band_pct: float = 0.05, seed: int = None) -> Dict:
    """用PID参数仿真，计算性能指标
    
    Args:
        process_params: 过程参数 {K, T1, L}
        pid_params: PID参数 {kp/Kp, ki/Ki, kd/Kd}
        sv: 设定值
        duration: 仿真时长（秒）
        dt: 采样周期（秒）
        error_band_pct: 误差带百分比（默认5%）
        seed: 随机种子，确保可重复性
    """
    # 固定随机种子确保可重复性
    if seed is not None:
        np.random.seed(seed)
    process = FOPDTProcess(
        K=process_params['K'],
        T1=process_params['T1'],
        L=process_params['L'],
        dt=dt
    )
    
    controller = PIDController(
        Kp=pid_params.get('kp', pid_params.get('Kp', 1.0)),
        Ki=pid_params.get('ki', pid_params.get('Ki', 0.1)),
        Kd=pid_params.get('kd', pid_params.get('Kd', 0.0)),
        dt=dt
    )
    
    # 从偏离状态开始
    pv_initial = sv * 0.8  # 初始偏离20%
    mv_ss = sv / process_params['K'] if process_params['K'] != 0 else sv
    process.reset(pv_initial=pv_initial)
    controller.reset(mv_initial=abs(mv_ss) * 0.8)
    
    steps = int(duration / dt)
    t_history, pv_history, sv_history, mv_history = [], [], [], []
    pv = pv_initial
    
    for step in range(steps):
        t = step * dt
        mv = controller.compute(sv, pv)
        pv = process.step(mv)
        t_history.append(t)
        pv_history.append(pv)
        sv_history.append(sv)
        mv_history.append(mv)
    
    pv_array = np.array(pv_history)
    
    # 稳态误差（最后50个点的平均偏差）
    steady_error = abs(np.mean(pv_array[-50:]) - sv) / sv * 100
    
    # 振荡程度（最后100个点的标准差）
    oscillation = np.std(pv_array[-100:])
    
    # 是否稳定（使用可配置的误差带）
    error_band = sv * error_band_pct
    is_stable = np.all(np.abs(pv_array[-100:] - sv) < error_band)
    
    # 如果不稳定，检查是否在收敛（趋势向好）
    is_converging = False
    if not is_stable:
        # 比较前半段和后半段的振荡程度
        first_half_std = np.std(pv_array[50:150])
        second_half_std = np.std(pv_array[-100:])
        is_converging = second_half_std < first_half_std * 0.8
    
    # 调节时间（进入误差带的时间）
    settling_time = duration
    for i in range(len(pv_array) - 1, 0, -1):
        if abs(pv_array[i] - sv) > error_band:
            settling_time = (i + 1) * dt
            break
    if settling_time == duration and abs(pv_array[0] - sv) <= error_band:
        settling_time = 0
    
    # 超调量
    overshoot = 0
    if pv_initial < sv:
        peak = np.max(pv_array)
        if peak > sv:
            overshoot = (peak - sv) / (sv - pv_initial) * 100
    else:
        trough = np.min(pv_array)
        if trough < sv:
            overshoot = (sv - trough) / (pv_initial - sv) * 100
    
    # IAE (Integral Absolute Error) - 积分绝对误差
    iae = np.sum(np.abs(pv_array - sv)) * dt
    
    return {
        't': t_history,
        'pv': pv_history,
        'sv': sv_history,
        'mv': mv_history,
        'steady_error': steady_error,
        'oscillation': oscillation,
        'is_stable': is_stable,
        'is_converging': is_converging,
        'settling_time': settling_time,
        'overshoot': overshoot,
        'iae': iae,
    }


def detect_disturbance_windows(data: List[Dict]) -> List[Dict]:
    """检测扰动窗口（支持振荡和正常扰动两种场景）"""
    if len(data) < 100:
        return []
    
    timestamps = [d['timestamp'] for d in data]
    pv_array = np.array([d['pv'] for d in data])
    sv_array = np.array([d['sv'] for d in data])
    
    # 方法1: 检测SV变化
    sv_diff = np.abs(np.diff(sv_array))
    sv_change_indices = np.where(sv_diff > 1.0)[0]
    
    if len(sv_change_indices) > 0:
        start_idx = max(0, sv_change_indices[0] - 20)
        return [{
            'start_time': timestamps[start_idx],
            'end_time': timestamps[-1],
            'start_idx': start_idx,
            'end_idx': len(data) - 1,
        }]
    
    # 方法2: 检测PV偏离SV（正常扰动场景）
    error = np.abs(pv_array - sv_array)
    error_threshold = 2.0  # PV偏离SV超过2就认为有扰动
    
    for i in range(50, len(error)):
        if error[i] > error_threshold:
            start_idx = max(0, i - 30)
            return [{
                'start_time': timestamps[start_idx],
                'end_time': timestamps[-1],
                'start_idx': start_idx,
                'end_idx': len(data) - 1,
            }]
    
    # 方法3: 检测PV振荡（振荡场景）
    window_size = 50
    std_threshold = 1.0
    
    for i in range(window_size, len(pv_array)):
        window_std = np.std(pv_array[i-window_size:i])
        if window_std > std_threshold:
            start_idx = max(0, i - window_size - 20)
            return [{
                'start_time': timestamps[start_idx],
                'end_time': timestamps[-1],
                'start_idx': start_idx,
                'end_idx': len(data) - 1,
            }]
    
    return []


# ============================================================
# 可视化
# ============================================================
def visualize_results(data: List[Dict], metadata: Dict, tuning_result: Dict, 
                      windows: List[Dict], sim_old: Dict, sim_new: Dict):
    """可视化整定结果"""
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    timestamps = [d['timestamp'] for d in data]
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    pv_array = np.array([d['pv'] for d in data])
    sv_array = np.array([d['sv'] for d in data])
    mv_array = np.array([d['mv'] for d in data])
    
    fig = plt.figure(figsize=(16, 12))
    
    pid_new = tuning_result.get('pid_parameters', {})
    pid_old = metadata['original_pid']
    scenario = metadata.get('scenario', 'oscillation')
    
    if scenario == 'oscillation':
        title = 'Synthetic Data Tuning Test: Steady -> Oscillation -> New PID Steady'
    else:
        title = 'Synthetic Data Tuning Test: Steady -> Normal Disturbance -> Recovery'
    
    fig.suptitle(title, fontsize=14, fontweight='bold')

    # ========== 子图1: 原始数据 PV/SV ==========
    ax1 = fig.add_subplot(3, 2, 1)
    ax1.plot(time_array, pv_array, 'b-', label='PV', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV', linewidth=1.2)
    
    # 标记系统变化时间
    if metadata.get('change_time'):
        change_dt = datetime.fromtimestamp(metadata['change_time'] / 1000)
        ax1.axvline(x=change_dt, color='red', linestyle='--', linewidth=2, label='System Changed')
    
    # 标记扰动窗口
    for w in windows:
        start_dt = datetime.fromtimestamp(w['start_time'] / 1000)
        end_dt = datetime.fromtimestamp(w['end_time'] / 1000)
        ax1.axvspan(start_dt, end_dt, alpha=0.2, color='orange', label='Detected Window')
    
    ax1.set_ylabel('PV / SV')
    phase_title = 'Phase 1-2: Steady -> Oscillation (System Changed)' if scenario == 'oscillation' else 'Phase 1-2: Steady -> Disturbance -> Recovery (SV unchanged)'
    ax1.set_title(phase_title)
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(3, 2, 2)
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    if metadata.get('change_time'):
        change_dt = datetime.fromtimestamp(metadata['change_time'] / 1000)
        ax2.axvline(x=change_dt, color='red', linestyle='--', linewidth=2)
    ax2.set_ylabel('MV')
    ax2.set_title('MV (Control Output)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 原PID响应 ==========
    ax3 = fig.add_subplot(3, 2, 3)
    ax3.plot(sim_old['t'], sim_old['pv'], 'b-', label=f'Old PID (Kp={pid_old["Kp"]}, Ki={pid_old["Ki"]})', linewidth=1.5)
    ax3.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax3.axhline(y=metadata['sv'] * 1.02, color='gray', linestyle=':', alpha=0.5)
    ax3.axhline(y=metadata['sv'] * 0.98, color='gray', linestyle=':', alpha=0.5)
    settling = sim_old.get('settling_time', 0)
    overshoot = sim_old.get('overshoot', 0)
    status = 'Stable' if sim_old['is_stable'] else 'OSCILLATING'
    ax3.set_title(f'Old PID: {status} (Ts={settling:.0f}s, OS={overshoot:.1f}%)')
    ax3.set_ylabel('PV')
    ax3.legend(loc='lower right')
    ax3.grid(True, alpha=0.3)

    # ========== 子图4: 新PID响应 ==========
    ax4 = fig.add_subplot(3, 2, 4)
    ax4.plot(sim_new['t'], sim_new['pv'], 'g-',
             label=f'New PID (Kp={pid_new.get("kp", 0):.3f}, Ki={pid_new.get("ki", 0):.3f})', linewidth=1.5)
    ax4.plot(sim_new['t'], sim_new['sv'], 'r--', label='SV', linewidth=1.2)
    ax4.axhline(y=metadata['sv'] * 1.02, color='gray', linestyle=':', alpha=0.5)
    ax4.axhline(y=metadata['sv'] * 0.98, color='gray', linestyle=':', alpha=0.5)
    ax4.fill_between(sim_new['t'], metadata['sv'] * 0.98, metadata['sv'] * 1.02, alpha=0.1, color='green')
    settling = sim_new.get('settling_time', 0)
    overshoot = sim_new.get('overshoot', 0)
    status = 'STABLE' if sim_new['is_stable'] else 'Oscillating'
    ax4.set_title(f'New PID: {status} (Ts={settling:.0f}s, OS={overshoot:.1f}%)')
    ax4.set_ylabel('PV')
    ax4.set_xlabel('Time (s)')
    ax4.legend(loc='lower right')
    ax4.grid(True, alpha=0.3)
    
    # ========== 子图5: 对比图 ==========
    ax5 = fig.add_subplot(3, 2, 5)
    ax5.plot(sim_old['t'], sim_old['pv'], 'b--', label='Old PID', linewidth=1.2, alpha=0.7)
    ax5.plot(sim_new['t'], sim_new['pv'], 'g-', label='New PID', linewidth=1.5)
    ax5.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax5.fill_between(sim_new['t'], metadata['sv'] * 0.98, metadata['sv'] * 1.02, alpha=0.1, color='green', label='2% Band')
    ax5.set_title('Comparison: Old PID vs New PID')
    ax5.set_ylabel('PV')
    ax5.set_xlabel('Time (s)')
    ax5.legend(loc='upper right')
    ax5.grid(True, alpha=0.3)
    
    # ========== 子图6: 整定信息 ==========
    ax6 = fig.add_subplot(3, 2, 6)
    ax6.axis('off')
    
    model_params = tuning_result.get('model_parameters', {})
    true_params = metadata['process_changed']
    
    info = f"""
TUNING SUMMARY
{'='*40}

[System Change]
  Original: K={metadata['process_original']['K']}, T1={metadata['process_original']['T1']}s
  Changed:  K={true_params['K']}, T1={true_params['T1']}s, L={true_params['L']}s

[Model Identification]
  Identified: K={model_params.get('K', 'N/A')}, T1={model_params.get('T1', 'N/A')}s
  Method: {tuning_result.get('fusion_info', {}).get('method', 'N/A')}
  Rating: {tuning_result.get('model_rating', 'N/A')}/10

[PID Parameters]
  Old: Kp={pid_old['Kp']}, Ki={pid_old['Ki']}, Kd={pid_old['Kd']}
  New: Kp={pid_new.get('kp', 'N/A'):.4f}, Ki={pid_new.get('ki', 'N/A'):.4f}, Kd={pid_new.get('kd', 'N/A'):.4f}
  pb = {pid_new.get('pb', 'N/A')}%

[Performance]
  Old PID: {'OSCILLATING' if not sim_old['is_stable'] else 'Stable'} (std={sim_old['oscillation']:.2f})
  New PID: {'STABLE' if sim_new['is_stable'] else 'Oscillating'} (std={sim_new['oscillation']:.2f})
"""
    ax6.text(0.05, 0.95, info, transform=ax6.transAxes, fontsize=10,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    
    plt.tight_layout()
    
    os.makedirs(CONFIG['output_dir'], exist_ok=True)
    filename = f'synthetic_tuning_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    filepath = os.path.join(CONFIG['output_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 Chart saved: {filepath}")
    plt.close()


# ============================================================
# 三方对比可视化（振荡场景：Old PID vs Rule Engine vs LLM）
# ============================================================
def visualize_llm_comparison(data: List[Dict], metadata: Dict, 
                              result_rule: Dict, result_llm: Dict,
                              sim_old: Dict, sim_rule: Dict, sim_llm: Dict):
    """可视化 LLM vs 规则引擎对比（振荡场景专用）"""
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    timestamps = [d['timestamp'] for d in data]
    time_array = [datetime.fromtimestamp(ts / 1000) for ts in timestamps]
    pv_array = np.array([d['pv'] for d in data])
    sv_array = np.array([d['sv'] for d in data])
    mv_array = np.array([d['mv'] for d in data])
    
    fig = plt.figure(figsize=(18, 14))
    
    pid_old = metadata['original_pid']
    pid_rule = result_rule.get('pid_parameters', {})
    pid_llm = result_llm.get('pid_parameters', {})
    
    fig.suptitle('Oscillation Tuning: Old PID vs Rule Engine vs LLM', fontsize=14, fontweight='bold')
    
    # ========== 子图1: 原始数据 PV/SV ==========
    ax1 = fig.add_subplot(3, 2, 1)
    ax1.plot(time_array, pv_array, 'b-', label='PV', linewidth=0.8, alpha=0.7)
    ax1.plot(time_array, sv_array, 'r--', label='SV', linewidth=1.2)
    if metadata.get('change_time'):
        change_dt = datetime.fromtimestamp(metadata['change_time'] / 1000)
        ax1.axvline(x=change_dt, color='red', linestyle='--', linewidth=2, label='System Changed')
    ax1.set_ylabel('PV / SV')
    ax1.set_title('Original Data: Steady -> Oscillation')
    ax1.legend(loc='upper right')
    ax1.grid(True, alpha=0.3)
    
    # ========== 子图2: MV ==========
    ax2 = fig.add_subplot(3, 2, 2)
    ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
    if metadata.get('change_time'):
        change_dt = datetime.fromtimestamp(metadata['change_time'] / 1000)
        ax2.axvline(x=change_dt, color='red', linestyle='--', linewidth=2)
    ax2.set_ylabel('MV')
    ax2.set_title('MV (Control Output)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: Old PID 响应 ==========
    ax3 = fig.add_subplot(3, 2, 3)
    ax3.plot(sim_old['t'], sim_old['pv'], 'b-', label='Old PID', linewidth=1.5)
    ax3.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax3.axhline(y=metadata['sv'] * 1.02, color='gray', linestyle=':', alpha=0.5)
    ax3.axhline(y=metadata['sv'] * 0.98, color='gray', linestyle=':', alpha=0.5)
    status = 'Stable' if sim_old['is_stable'] else 'OSCILLATING'
    ax3.set_title(f'Old PID: {status} (Kp={pid_old["Kp"]}, Ki={pid_old["Ki"]})')
    ax3.set_ylabel('PV')
    ax3.legend(loc='lower right')
    ax3.grid(True, alpha=0.3)
    
    # ========== 子图4: 三方对比 ==========
    ax4 = fig.add_subplot(3, 2, 4)
    ax4.plot(sim_old['t'], sim_old['pv'], 'b--', label='Old PID', linewidth=1.2, alpha=0.6)
    ax4.plot(sim_rule['t'], sim_rule['pv'], 'orange', label='Rule Engine', linewidth=1.5)
    ax4.plot(sim_llm['t'], sim_llm['pv'], 'g-', label='LLM', linewidth=1.5)
    ax4.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax4.fill_between(sim_old['t'], metadata['sv'] * 0.98, metadata['sv'] * 1.02, 
                     alpha=0.1, color='green', label='2% Band')
    ax4.set_title('Comparison: Old PID vs Rule Engine vs LLM')
    ax4.set_ylabel('PV')
    ax4.set_xlabel('Time (s)')
    ax4.legend(loc='upper right')
    ax4.grid(True, alpha=0.3)
    
    # ========== 子图5: Rule Engine vs LLM 详细对比 ==========
    ax5 = fig.add_subplot(3, 2, 5)
    ax5.plot(sim_rule['t'], sim_rule['pv'], 'orange', label='Rule Engine', linewidth=1.5)
    ax5.plot(sim_llm['t'], sim_llm['pv'], 'g-', label='LLM', linewidth=1.5)
    ax5.plot(sim_rule['t'], sim_rule['sv'], 'r--', label='SV', linewidth=1.2)
    ax5.fill_between(sim_rule['t'], metadata['sv'] * 0.98, metadata['sv'] * 1.02, 
                     alpha=0.1, color='green')
    ts_rule = sim_rule.get('settling_time', 0)
    ts_llm = sim_llm.get('settling_time', 0)
    ax5.set_title(f'Rule Engine (Ts={ts_rule:.0f}s) vs LLM (Ts={ts_llm:.0f}s)')
    ax5.set_ylabel('PV')
    ax5.set_xlabel('Time (s)')
    ax5.legend(loc='lower right')
    ax5.grid(True, alpha=0.3)
    
    # ========== 子图6: 对比信息表 ==========
    ax6 = fig.add_subplot(3, 2, 6)
    ax6.axis('off')
    
    llm_decision = pid_llm.get('llm_decision', {})
    strategy_params = llm_decision.get('strategy_params', {}) if llm_decision else {}
    
    info = f"""
COMPARISON SUMMARY
{'='*50}

[PID Parameters]
                    Old PID      Rule Engine    LLM
  Kp:               {pid_old['Kp']:<12} {pid_rule.get('kp', 0):<14.4f} {pid_llm.get('kp', 0):.4f}
  Ki:               {pid_old['Ki']:<12} {pid_rule.get('ki', 0):<14.4f} {pid_llm.get('ki', 0):.4f}
  Kd:               {pid_old['Kd']:<12} {pid_rule.get('kd', 0):<14.4f} {pid_llm.get('kd', 0):.4f}
  pb:               -            {str(pid_rule.get('pb', 'N/A'))+'%':<14} {str(pid_llm.get('pb', 'N/A'))+'%'}

[Performance]
                    Old PID      Rule Engine    LLM
  Stable:           {'No' if not sim_old['is_stable'] else 'Yes':<12} {'Yes' if sim_rule['is_stable'] else 'No':<14} {'Yes' if sim_llm['is_stable'] else 'No'}
  Settling Time:    {sim_old['settling_time']:.0f}s{'':<10} {sim_rule['settling_time']:.0f}s{'':<12} {sim_llm['settling_time']:.0f}s
  Overshoot:        {sim_old['overshoot']:.1f}%{'':<9} {sim_rule['overshoot']:.1f}%{'':<11} {sim_llm['overshoot']:.1f}%

[LLM Strategy Decision]
  safety_factor:    {strategy_params.get('safety_factor', 'N/A')}
  pb_extra_factor:  {strategy_params.get('pb_extra_factor', 'N/A')}
  ti_multiplier:    {strategy_params.get('ti_multiplier', 'N/A')}
  enable_derivative:{strategy_params.get('enable_derivative', 'N/A')}
  Reasoning:        {(llm_decision.get('reasoning', 'N/A')[:50] + '...') if llm_decision else 'N/A'}
"""
    ax6.text(0.02, 0.98, info, transform=ax6.transAxes, fontsize=9,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    
    plt.tight_layout()
    
    os.makedirs(CONFIG['output_dir'], exist_ok=True)
    filename = f'synthetic_llm_comparison_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    filepath = os.path.join(CONFIG['output_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 LLM Comparison chart saved: {filepath}")
    plt.close()


# ============================================================
# 主测试函数
# ============================================================
def main():
    print("=" * 70)
    print("Synthetic Data Tuning Test")
    if SCENARIO == 'oscillation':
        print("Scenario: Steady -> System Change -> Oscillation -> Re-tune -> Stable")
        print("Mode: LLM vs Rule Engine Comparison")
    else:
        print("Scenario: Steady -> Normal Disturbance (SV unchanged) -> Recovery -> Tuning")
    print("=" * 70)
    
    # 1. 生成合成数据
    print("\n📊 Generating synthetic data...")
    print(f"   Phase 1: Steady state ({CONFIG['steady_duration']}s)")
    if SCENARIO == 'oscillation':
        print(f"   Phase 2: System changes, oscillation starts ({CONFIG['oscillation_duration']}s)")
    else:
        print(f"   Phase 2: External disturbance (SV={CONFIG['sv']} unchanged), normal response ({CONFIG['oscillation_duration']}s)")
    data, metadata, _ = generate_synthetic_data()
    print(f"   Total data points: {len(data)}")
    
    # 2. 检测扰动窗口
    print("\n🔍 Detecting oscillation window...")
    windows = detect_disturbance_windows(data)
    if windows:
        for i, w in enumerate(windows):
            start_str = datetime.fromtimestamp(w['start_time'] / 1000).strftime('%H:%M:%S')
            end_str = datetime.fromtimestamp(w['end_time'] / 1000).strftime('%H:%M:%S')
            print(f"   Window {i+1}: {start_str} ~ {end_str}")
    else:
        print("   ⚠️ No oscillation window detected")
        return
    
    clean_data = [{k: v for k, v in d.items() if k != 'phase'} for d in data]
    input_data = {
        'history_data': clean_data,
        'params': {'model_type': None, 'turning_type': None, 'analyst_column': 'pv'},
        'qualified_windows': windows,
    }
    
    # ============================================================
    # 振荡场景：LLM vs 规则引擎对比
    # ============================================================
    if SCENARIO == 'oscillation':
        # 检查 Ollama 连接
        print("\n📡 Checking Ollama connection...")
        llm_client = None
        try:
            llm_client = OllamaClient(
                model=CONFIG['ollama_model'],
                base_url=CONFIG['ollama_base_url']
            )
            llm_client.chat("OK")
            print(f"   ✅ Ollama connected (model: {CONFIG['ollama_model']})")
        except Exception as e:
            print(f"   ❌ Ollama connection failed: {e}")
            print("   Will only run Rule Engine tuning")
            llm_client = None
        
        # 保存原始配置
        original_enable_llm = Config.OSCILLATION_TUNING.get('enable_llm', True)
        
        # ========== 1. 规则引擎整定 (enable_llm=False) ==========
        print("\n🔧 [1/2] Rule Engine tuning (enable_llm=False)...")
        Config.OSCILLATION_TUNING['enable_llm'] = False
        selector_rule = ModelSelector(verbose=False)
        result_rule = selector_rule.run(input_data)
        
        # ========== 2. LLM 整定 (enable_llm=True) ==========
        result_llm = None
        if llm_client:
            print(f"\n🤖 [2/2] LLM tuning (enable_llm=True)...")
            Config.OSCILLATION_TUNING['enable_llm'] = True
            selector_llm = ModelSelector(
                verbose=False,
                llm_client=llm_client,
                process_context={'loop_type': 'flow', 'loop_name': 'Synthetic Loop'}
            )
            result_llm = selector_llm.run(input_data)
        
        # 恢复原始配置
        Config.OSCILLATION_TUNING['enable_llm'] = original_enable_llm
        
        # ========== 3. 仿真对比 ==========
        print("\n📈 Simulating Old PID vs Rule Engine vs LLM...")
        
        # Old PID
        sim_old = simulate_with_new_pid(
            metadata['process_changed'],
            metadata['original_pid'],
            metadata['sv'],
            duration=200
        )
        print(f"   Old PID:      Ts={sim_old['settling_time']:.0f}s, OS={sim_old['overshoot']:.1f}%, Stable={sim_old['is_stable']}")
        
        # Rule Engine PID
        pid_rule = result_rule.get('pid_parameters', {})
        sim_rule = simulate_with_new_pid(
            metadata['process_changed'],
            pid_rule,
            metadata['sv'],
            duration=200
        )
        print(f"   Rule Engine:  Ts={sim_rule['settling_time']:.0f}s, OS={sim_rule['overshoot']:.1f}%, Stable={sim_rule['is_stable']}")
        
        # LLM PID
        sim_llm = None
        pid_llm = {}
        if result_llm:
            pid_llm = result_llm.get('pid_parameters', {})
            sim_llm = simulate_with_new_pid(
                metadata['process_changed'],
                pid_llm,
                metadata['sv'],
                duration=200
            )
            print(f"   LLM:          Ts={sim_llm['settling_time']:.0f}s, OS={sim_llm['overshoot']:.1f}%, Stable={sim_llm['is_stable']}")
        
        # ========== 4. 输出对比结果 ==========
        print("\n" + "=" * 70)
        print("COMPARISON RESULT: Rule Engine vs LLM")
        print("=" * 70)
        
        pid_old = metadata['original_pid']
        print(f"\n{'Metric':<20} {'Old PID':<15} {'Rule Engine':<15} {'LLM':<15}")
        print("-" * 65)
        print(f"{'Kp':<20} {pid_old['Kp']:<15} {pid_rule.get('kp', 0):<15.4f} {pid_llm.get('kp', 'N/A') if result_llm else 'N/A'}")
        print(f"{'Ki':<20} {pid_old['Ki']:<15} {pid_rule.get('ki', 0):<15.4f} {pid_llm.get('ki', 'N/A') if result_llm else 'N/A'}")
        print(f"{'Kd':<20} {pid_old['Kd']:<15} {pid_rule.get('kd', 0):<15.4f} {pid_llm.get('kd', 'N/A') if result_llm else 'N/A'}")
        print(f"{'pb (%)':<20} {'-':<15} {pid_rule.get('pb', 'N/A'):<15} {pid_llm.get('pb', 'N/A') if result_llm else 'N/A'}")
        print("-" * 65)
        print(f"{'Stable':<20} {'No' if not sim_old['is_stable'] else 'Yes':<15} {'Yes' if sim_rule['is_stable'] else 'No':<15} {'Yes' if sim_llm and sim_llm['is_stable'] else 'No' if sim_llm else 'N/A'}")
        print(f"{'Settling Time (s)':<20} {sim_old['settling_time']:<15.0f} {sim_rule['settling_time']:<15.0f} {sim_llm['settling_time'] if sim_llm else 'N/A'}")
        print(f"{'Overshoot (%)':<20} {sim_old['overshoot']:<15.1f} {sim_rule['overshoot']:<15.1f} {sim_llm['overshoot'] if sim_llm else 'N/A'}")
        
        # LLM 决策详情
        if result_llm:
            llm_decision = pid_llm.get('llm_decision', {})
            if llm_decision:
                print(f"\n🤖 LLM Strategy Decision:")
                strategy = llm_decision.get('strategy_params', {})
                if strategy:
                    print(f"   safety_factor:     {strategy.get('safety_factor', 'N/A')}")
                    print(f"   pb_extra_factor:   {strategy.get('pb_extra_factor', 'N/A')}")
                    print(f"   ti_multiplier:     {strategy.get('ti_multiplier', 'N/A')}")
                    print(f"   enable_derivative: {strategy.get('enable_derivative', 'N/A')}")
                    print(f"   td_factor:         {strategy.get('td_factor', 'N/A')}")
                print(f"   Reasoning: {llm_decision.get('reasoning', 'N/A')}")
        
        # ========== 5. 可视化 ==========
        print("\n📈 Generating comparison visualization...")
        if result_llm and sim_llm:
            visualize_llm_comparison(data, metadata, result_rule, result_llm, 
                                     sim_old, sim_rule, sim_llm)
        else:
            visualize_results(data, metadata, result_rule, windows, sim_old, sim_rule)
        
        # ========== 6. 结论 ==========
        print("\n" + "=" * 70)
        print("CONCLUSION")
        print("=" * 70)
        
        if not sim_old['is_stable']:
            print("✅ Old PID is OSCILLATING (as expected)")
        
        if sim_rule['is_stable']:
            print(f"✅ Rule Engine PID is STABLE (Ts={sim_rule['settling_time']:.0f}s)")
        else:
            print("⚠️ Rule Engine PID is still oscillating")
        
        if sim_llm:
            if sim_llm['is_stable']:
                print(f"✅ LLM PID is STABLE (Ts={sim_llm['settling_time']:.0f}s)")
                if sim_rule['is_stable'] and sim_llm['settling_time'] < sim_rule['settling_time']:
                    improvement = (sim_rule['settling_time'] - sim_llm['settling_time']) / sim_rule['settling_time'] * 100
                    print(f"   🎯 LLM improved settling time by {improvement:.0f}% vs Rule Engine")
            else:
                print("⚠️ LLM PID is still oscillating")
    
    # ============================================================
    # 正常扰动场景：只用规则引擎
    # ============================================================
    else:
        print("\n🔧 Running model identification and PID tuning...")
        selector = ModelSelector(verbose=True)
        result = selector.run(input_data)
        
        print("\n📈 Simulating Old PID vs New PID...")
        
        sim_old = simulate_with_new_pid(
            metadata['process_changed'],
            metadata['original_pid'],
            metadata['sv'],
            duration=200
        )
        print(f"   Old PID: Ts={sim_old['settling_time']:.0f}s, OS={sim_old['overshoot']:.1f}%, Stable={sim_old['is_stable']}")
        
        pid_new = result.get('pid_parameters', {})
        sim_new = simulate_with_new_pid(
            metadata['process_changed'],
            pid_new,
            metadata['sv'],
            duration=200
        )
        print(f"   New PID: Ts={sim_new['settling_time']:.0f}s, OS={sim_new['overshoot']:.1f}%, Stable={sim_new['is_stable']}")
        
        print("\n" + "=" * 70)
        print("TUNING RESULT")
        print("=" * 70)
        
        print(f"\nSuccess: {result.get('success', False)}")
        print(f"Model Type: {result.get('model_type', 'N/A')}")
        print(f"Method: {result.get('fusion_info', {}).get('method', 'N/A')}")
        
        print(f"\nPID Parameters:")
        print(f"  Old: Kp={metadata['original_pid']['Kp']}, Ki={metadata['original_pid']['Ki']}")
        print(f"  New: Kp={pid_new.get('kp', 'N/A')}, Ki={pid_new.get('ki', 'N/A')}, Kd={pid_new.get('kd', 'N/A')}")
        
        print("\n📈 Generating visualization...")
        visualize_results(data, metadata, result, windows, sim_old, sim_new)
        
        print("\n" + "=" * 70)
        print("CONCLUSION")
        print("=" * 70)
        
        ts_old = sim_old.get('settling_time', 0)
        ts_new = sim_new.get('settling_time', 0)
        
        if ts_new < ts_old * 0.8:
            improvement = (ts_old - ts_new) / ts_old * 100
            print(f"✅ SUCCESS: Settling time improved by {improvement:.0f}%")
        elif sim_new['is_stable'] and sim_old['is_stable']:
            print("✅ Both PIDs are stable.")
        else:
            print("⚠️ Performance comparison inconclusive.")
    
    print("\n✅ Test completed!")


# ============================================================
# 多场景批量测试
# ============================================================

# 幅度变化场景生成器
# ============================================================

def generate_amplitude_variations(base_scenario: Dict, 
                                   amplitude_factors: List[float] = None) -> List[Dict]:
    """
    基于一个基础场景生成不同幅度变化的场景变体
    
    Args:
        base_scenario: 基础场景配置
        amplitude_factors: 幅度因子列表，如 [0.5, 1.0, 1.5, 2.0]
                          1.0 表示原始变化幅度
                          0.5 表示变化幅度减半
                          2.0 表示变化幅度翻倍
    
    Returns:
        场景变体列表
    """
    if amplitude_factors is None:
        amplitude_factors = [0.5, 0.75, 1.0, 1.25, 1.5]
    
    variations = []
    orig = base_scenario['process_original']
    changed = base_scenario['process_changed']
    
    # 计算原始变化量
    delta_K = changed['K'] - orig['K']
    delta_T1 = changed['T1'] - orig['T1']
    delta_L = changed['L'] - orig['L']
    
    for factor in amplitude_factors:
        # 生成新的变化后参数
        new_changed = {
            'K': orig['K'] + delta_K * factor,
            'T1': max(5.0, orig['T1'] + delta_T1 * factor),  # T1 最小 5s
            'L': max(1.0, orig['L'] + delta_L * factor),     # L 最小 1s
        }
        
        # 确保 K 不为 0 或负数（除非原本就是反向作用）
        if orig['K'] > 0 and new_changed['K'] <= 0:
            new_changed['K'] = 0.1
        
        variation = {
            'name': f"{base_scenario['name']} (×{factor})",
            'description': f"{base_scenario['description']} - 幅度×{factor}",
            'process_original': orig.copy(),
            'process_changed': new_changed,
            'original_pid': base_scenario['original_pid'].copy(),
            'loop_type': base_scenario.get('loop_type', 'flow'),
            'noise_std': base_scenario.get('noise_std', 0.2),
            'amplitude_factor': factor,
        }
        variations.append(variation)
    
    return variations


def generate_all_amplitude_scenarios(base_scenarios: List[Dict] = None,
                                      selected_names: List[str] = None,
                                      amplitude_factors: List[float] = None) -> List[Dict]:
    """
    为选定的基础场景生成所有幅度变体
    
    Args:
        base_scenarios: 基础场景列表，默认使用 TEST_SCENARIOS
        selected_names: 要生成变体的场景名称列表，None 表示全部
        amplitude_factors: 幅度因子列表
    
    Returns:
        所有场景变体的列表
    """
    if base_scenarios is None:
        base_scenarios = TEST_SCENARIOS
    
    if amplitude_factors is None:
        amplitude_factors = [0.5, 0.75, 1.0, 1.25, 1.5]
    
    all_variations = []
    
    for scenario in base_scenarios:
        if selected_names is None or scenario['name'] in selected_names:
            variations = generate_amplitude_variations(scenario, amplitude_factors)
            all_variations.extend(variations)
    
    return all_variations


# 预定义的幅度测试场景（选择几个典型场景）
# ============================================================
# 工业实际场景测试配置
# ============================================================
# 设计原则：
# 1. 基于实际工业场景的系统变化特点
# 2. Old PID 参数是针对原系统合理整定的（不是故意激进）
# 3. 系统变化后 Old PID 会振荡，需要重新整定
# 4. 幅度变化模拟实际工况波动（如负荷变化、季节变化等）

# 实际工业场景
REALISTIC_SCENARIOS = [
    # ========== 流量回路 ==========
    # 特点：响应快，滞后小，但阀门特性会随时间变化
    {
        'name': 'Flow - Valve Stiction',
        'description': '流量回路 - 阀门粘滞（增益非线性+滞后增加）',
        'process_original': {'K': 1.0, 'T1': 25.0, 'L': 2.0},
        'process_changed': {'K': 1.6, 'T1': 22.0, 'L': 8.0},
        'original_pid': {'Kp': 3.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
        # 扩展幅度范围：0.7 ~ 1.4
        'amplitude_factors': [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4],
    },
    {
        'name': 'Flow - Pump Cavitation',
        'description': '流量回路 - 泵气蚀（增益下降+响应变慢）',
        'process_original': {'K': 1.2, 'T1': 20.0, 'L': 1.5},
        'process_changed': {'K': 1.6, 'T1': 18.0, 'L': 5.0},
        'original_pid': {'Kp': 3.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
    },
    
    # ========== 温度回路 ==========
    # 特点：响应慢，滞后大，受换热效率影响
    {
        'name': 'Temp - Heat Exchanger Fouling',
        'description': '温度回路 - 换热器结垢（传热系数下降）',
        'process_original': {'K': 0.8, 'T1': 50.0, 'L': 10.0},
        'process_changed': {'K': 1.3, 'T1': 55.0, 'L': 18.0},
        'original_pid': {'Kp': 4.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2],
    },
    {
        'name': 'Temp - Ambient Change',
        'description': '温度回路 - 环境温度变化（季节性）',
        'process_original': {'K': 0.9, 'T1': 45.0, 'L': 8.0},
        'process_changed': {'K': 1.3, 'T1': 40.0, 'L': 12.0},
        'original_pid': {'Kp': 4.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [0.7, 0.8, 0.85, 0.9, 0.95, 1.0, 1.1, 1.2, 1.3],
    },
    
    # ========== 压力回路 ==========
    # 特点：响应快，对增益变化敏感
    {
        'name': 'Press - Compressor Surge',
        'description': '压力回路 - 压缩机喘振边界变化',
        'process_original': {'K': 1.0, 'T1': 15.0, 'L': 1.0},
        'process_changed': {'K': 1.6, 'T1': 12.0, 'L': 4.0},
        'original_pid': {'Kp': 4.0, 'Ki': 0.2, 'Kd': 0.0},
        'loop_type': 'pressure',
        'amplitude_factors': [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4],
    },
    {
        'name': 'Press - Upstream Disturbance',
        'description': '压力回路 - 上游压力波动',
        'process_original': {'K': 1.2, 'T1': 18.0, 'L': 2.0},
        'process_changed': {'K': 1.5, 'T1': 15.0, 'L': 5.0},
        'original_pid': {'Kp': 3.5, 'Ki': 0.15, 'Kd': 0.0},
        'loop_type': 'pressure',
        'amplitude_factors': [0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2],
    },
    
    # ========== 液位回路 ==========
    # 特点：积分特性，对滞后敏感
    {
        'name': 'Level - Tank Geometry',
        'description': '液位回路 - 储罐液面形状变化（锥形底）',
        'process_original': {'K': 1.0, 'T1': 40.0, 'L': 5.0},
        'process_changed': {'K': 1.5, 'T1': 35.0, 'L': 10.0},
        'original_pid': {'Kp': 4.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'level',
        'amplitude_factors': [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
    },
    {
        'name': 'Level - Outflow Change',
        'description': '液位回路 - 出口流量变化（下游负荷）',
        'process_original': {'K': 1.0, 'T1': 35.0, 'L': 4.0},
        'process_changed': {'K': 1.4, 'T1': 38.0, 'L': 9.0},
        'original_pid': {'Kp': 4.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'level',
        'amplitude_factors': [0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2],
    },
    
    # ========== 极端挑战场景 ==========
    # 专门测试算法鲁棒性的边界情况
    
    # 1. 极快系统（响应时间 < 5s）
    {
        'name': 'Ultra Fast Flow',
        'description': '超快流量回路 - 极小时间常数',
        'process_original': {'K': 1.0, 'T1': 3.0, 'L': 0.5},
        'process_changed': {'K': 2.0, 'T1': 2.0, 'L': 1.5},
        'original_pid': {'Kp': 8.0, 'Ki': 0.5, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [1.0],
    },
    
    # 2. 极慢系统（响应时间 > 200s）
    {
        'name': 'Very Slow Temperature',
        'description': '极慢温度回路 - 大时间常数',
        'process_original': {'K': 0.6, 'T1': 200.0, 'L': 30.0},
        'process_changed': {'K': 1.0, 'T1': 180.0, 'L': 50.0},
        'original_pid': {'Kp': 1.5, 'Ki': 0.005, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [1.0],
    },
    
    # 3. 高噪声环境
    {
        'name': 'High Noise Flow',
        'description': '高噪声流量回路 - 测噪声鲁棒性',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 3.0},
        'process_changed': {'K': 1.8, 'T1': 18.0, 'L': 6.0},
        'original_pid': {'Kp': 3.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'noise_std': 0.8,  # 高噪声
        'amplitude_factors': [1.0],
    },
    
    # 4. 极高增益变化（5倍以上）
    {
        'name': 'Extreme Gain Change',
        'description': '极高增益变化 - K从1变到6',
        'process_original': {'K': 1.0, 'T1': 30.0, 'L': 3.0},
        'process_changed': {'K': 6.0, 'T1': 25.0, 'L': 8.0},
        'original_pid': {'Kp': 2.5, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [1.0],
    },
    
    # 5. 极大滞后（L/T1 > 0.5）
    {
        'name': 'Very Large Delay',
        'description': '极大滞后 - L/T1 接近1',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 5.0},
        'process_changed': {'K': 1.2, 'T1': 18.0, 'L': 15.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.05, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [1.0],
    },
    
    # 6. 积分过程（液位）
    {
        'name': 'Integrating Level',
        'description': '积分液位回路 - 大时间常数模拟积分',
        'process_original': {'K': 0.8, 'T1': 150.0, 'L': 5.0},
        'process_changed': {'K': 1.2, 'T1': 140.0, 'L': 10.0},
        'original_pid': {'Kp': 1.0, 'Ki': 0.003, 'Kd': 0.0},
        'loop_type': 'level',
        'amplitude_factors': [1.0],
    },
    
    # 7. 反向作用（负增益）
    {
        'name': 'Reverse Acting Flow',
        'description': '反向作用流量 - 负增益系统',
        'process_original': {'K': -1.0, 'T1': 25.0, 'L': 2.0},
        'process_changed': {'K': -2.0, 'T1': 20.0, 'L': 5.0},
        'original_pid': {'Kp': -3.0, 'Ki': -0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [1.0],
    },
    
    # 8. 压力回路 - 快速扰动
    {
        'name': 'Fast Pressure Disturbance',
        'description': '快速压力扰动 - 小时间常数',
        'process_original': {'K': 1.2, 'T1': 8.0, 'L': 1.0},
        'process_changed': {'K': 2.5, 'T1': 6.0, 'L': 3.0},
        'original_pid': {'Kp': 5.0, 'Ki': 0.3, 'Kd': 0.0},
        'loop_type': 'pressure',
        'amplitude_factors': [1.0],
    },
    
    # 9. 温度回路 - 强耦合
    {
        'name': 'Coupled Temperature',
        'description': '强耦合温度回路 - 增益和滞后同时变化',
        'process_original': {'K': 1.0, 'T1': 60.0, 'L': 8.0},
        'process_changed': {'K': 3.0, 'T1': 40.0, 'L': 20.0},
        'original_pid': {'Kp': 1.2, 'Ki': 0.015, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [1.0],
    },
    
    # 10. 小增益系统
    {
        'name': 'Low Gain System',
        'description': '小增益系统 - K < 0.5',
        'process_original': {'K': 0.3, 'T1': 40.0, 'L': 5.0},
        'process_changed': {'K': 0.6, 'T1': 35.0, 'L': 10.0},
        'original_pid': {'Kp': 10.0, 'Ki': 0.2, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [1.0],
    },
    
    # 11. 高增益系统
    {
        'name': 'High Gain Temperature',
        'description': '高增益温度系统 - K > 3',
        'process_original': {'K': 3.0, 'T1': 50.0, 'L': 5.0},
        'process_changed': {'K': 5.0, 'T1': 45.0, 'L': 12.0},
        'original_pid': {'Kp': 0.5, 'Ki': 0.008, 'Kd': 0.0},
        'loop_type': 'temperature',
        'amplitude_factors': [1.0],
    },
    
    # 12. 边界条件 - 极小滞后
    {
        'name': 'Minimal Delay',
        'description': '极小滞后 - L接近0',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 0.5},
        'process_changed': {'K': 2.0, 'T1': 18.0, 'L': 2.0},
        'original_pid': {'Kp': 4.0, 'Ki': 0.15, 'Kd': 0.0},
        'loop_type': 'flow',
        'amplitude_factors': [1.0],
    },
]


def generate_realistic_amplitude_scenarios() -> List[Dict]:
    """
    生成贴合实际的幅度变化场景
    每个场景使用自己定义的幅度因子范围
    """
    all_scenarios = []
    
    for base in REALISTIC_SCENARIOS:
        factors = base.get('amplitude_factors', [0.9, 1.0, 1.1])
        
        for factor in factors:
            # 计算变化后的参数
            orig = base['process_original']
            changed = base['process_changed']
            
            # 幅度因子作用于变化量
            delta_K = changed['K'] - orig['K']
            delta_T1 = changed['T1'] - orig['T1']
            delta_L = changed['L'] - orig['L']
            
            new_changed = {
                'K': orig['K'] + delta_K * factor,
                'T1': orig['T1'] + delta_T1 * factor,
                'L': orig['L'] + delta_L * factor,
            }
            
            # 确保参数合理
            new_changed['K'] = max(0.1, new_changed['K'])
            new_changed['T1'] = max(5.0, new_changed['T1'])
            new_changed['L'] = max(0.5, new_changed['L'])
            
            scenario = {
                'name': f"{base['name']} (×{factor})",
                'description': f"{base['description']} - 幅度×{factor}",
                'process_original': orig.copy(),
                'process_changed': new_changed,
                'original_pid': base['original_pid'].copy(),
                'loop_type': base.get('loop_type', 'flow'),
                'noise_std': base.get('noise_std', 0.2),
                'amplitude_factor': factor,
            }
            all_scenarios.append(scenario)
    
    return all_scenarios


# 使用新的生成函数
AMPLITUDE_TEST_SCENARIOS = generate_realistic_amplitude_scenarios()


# ============================================================
# 模型辨识测试场景（非振荡，MV阶跃响应）
# ============================================================
# 设计原则：
# 1. 系统有MV阶跃变化，PV有响应但不振荡
# 2. 适合用模型辨识（FOPDT拟合）进行整定
# 3. 测试Lambda整定的效果

MODEL_ID_SCENARIOS = [
    # ========== 流量回路 ==========
    {
        'name': 'Flow - Step Response',
        'description': '流量回路 - MV阶跃响应测试',
        'process': {'K': 1.0, 'T1': 25.0, 'L': 3.0},
        'pid': {'Kp': 0.8, 'Ki': 0.03, 'Kd': 0.0},  # 保守PID，不会振荡
        'mv_step': 10.0,  # MV阶跃幅度
        'loop_type': 'flow',
    },
    {
        'name': 'Flow - Large Step',
        'description': '流量回路 - 大幅MV阶跃',
        'process': {'K': 1.2, 'T1': 20.0, 'L': 2.0},
        'pid': {'Kp': 0.6, 'Ki': 0.02, 'Kd': 0.0},
        'mv_step': 20.0,
        'loop_type': 'flow',
    },
    
    # ========== 温度回路 ==========
    {
        'name': 'Temp - Slow Response',
        'description': '温度回路 - 慢速阶跃响应',
        'process': {'K': 0.8, 'T1': 60.0, 'L': 10.0},
        'pid': {'Kp': 0.5, 'Ki': 0.01, 'Kd': 0.0},
        'mv_step': 15.0,
        'loop_type': 'temperature',
    },
    {
        'name': 'Temp - High Gain',
        'description': '温度回路 - 高增益系统',
        'process': {'K': 1.5, 'T1': 50.0, 'L': 8.0},
        'pid': {'Kp': 0.4, 'Ki': 0.01, 'Kd': 0.0},
        'mv_step': 10.0,
        'loop_type': 'temperature',
    },
    
    # ========== 压力回路 ==========
    {
        'name': 'Press - Fast Response',
        'description': '压力回路 - 快速阶跃响应',
        'process': {'K': 1.0, 'T1': 15.0, 'L': 1.5},
        'pid': {'Kp': 0.8, 'Ki': 0.04, 'Kd': 0.0},
        'mv_step': 12.0,
        'loop_type': 'pressure',
    },
    {
        'name': 'Press - Large Delay',
        'description': '压力回路 - 大滞后系统',
        'process': {'K': 1.0, 'T1': 18.0, 'L': 5.0},
        'pid': {'Kp': 0.5, 'Ki': 0.02, 'Kd': 0.0},
        'mv_step': 15.0,
        'loop_type': 'pressure',
    },
    
    # ========== 液位回路 ==========
    {
        'name': 'Level - Normal Response',
        'description': '液位回路 - 正常阶跃响应',
        'process': {'K': 1.0, 'T1': 40.0, 'L': 5.0},
        'pid': {'Kp': 0.6, 'Ki': 0.02, 'Kd': 0.0},
        'mv_step': 12.0,
        'loop_type': 'level',
    },
    {
        'name': 'Level - Integrating',
        'description': '液位回路 - 积分特性',
        'process': {'K': 0.8, 'T1': 50.0, 'L': 4.0},
        'pid': {'Kp': 0.5, 'Ki': 0.015, 'Kd': 0.0},
        'mv_step': 10.0,
        'loop_type': 'level',
    },
]


def generate_step_response_scenario_data(scenario: Dict) -> Tuple[List[Dict], Dict]:
    """
    生成MV阶跃响应数据（用于模型辨识测试）
    
    数据结构：稳态 → MV阶跃（开环）→ PV响应 → 保持
    
    关键：这是开环阶跃测试，MV直接变化，不经过PID控制
    这样PV响应是纯粹的过程响应，没有振荡，适合模型辨识
    """
    dt = 1.0
    sv = 50.0
    noise_std = scenario.get('noise_std', 0.1)  # 降低噪声
    
    process_params = scenario['process']
    mv_step = scenario.get('mv_step', 10.0)
    
    process = FOPDTProcess(
        K=process_params['K'],
        T1=process_params['T1'],
        L=process_params['L'],
        dt=dt
    )
    
    # 计算稳态MV（使PV=SV）
    K = process_params['K']
    mv_ss = sv / K if abs(K) > 0.001 else sv
    
    # 初始化过程
    process.reset(pv_initial=sv)
    
    # 时间配置
    steady_steps = 100       # 稳态段（较短）
    step_duration = 200      # MV阶跃持续时间（开环）
    hold_steps = 300         # 保持段（观察响应）
    total_steps = steady_steps + step_duration + hold_steps
    
    start_time = datetime.now() - timedelta(seconds=total_steps * dt)
    history_data = []
    step_time = None
    pv = sv
    
    for step in range(total_steps):
        current_time = start_time + timedelta(seconds=step * dt)
        timestamp = int(current_time.timestamp() * 1000)
        
        if step < steady_steps:
            # 稳态段：MV保持稳态值
            mv = mv_ss
        elif step < steady_steps + step_duration:
            # MV阶跃段：开环，MV直接增加
            if step == steady_steps:
                step_time = timestamp
            mv = mv_ss + mv_step
        else:
            # 保持段：MV保持阶跃后的值
            mv = mv_ss + mv_step
        
        # 限制MV范围
        mv = np.clip(mv, 0, 100)
        
        # 过程响应
        pv = process.step(mv)
        pv_noisy = pv + np.random.normal(0, noise_std)
        
        history_data.append({
            'timestamp': timestamp,
            'pv': round(pv_noisy, 2),
            'sv': round(sv, 2),
            'mv': round(mv, 2),
        })
    
    metadata = {
        'process': process_params,
        'pid': scenario.get('pid', {}),
        'change_time': step_time,
        'sv': sv,
        'scenario_type': 'model_identification',
        'mv_step': mv_step,
    }
    
    return history_data, metadata


def generate_scenario_data(scenario: Dict, seed: int = None) -> Tuple[List[Dict], Dict]:
    # 固定随机种子，确保每次运行结果一致
    # 注意：不使用 hash()，因为 Python 3.3+ 默认每次运行 hash 结果不同
    if seed is not None:
        np.random.seed(seed)
    else:
        np.random.seed(42)  # 默认种子
    
    dt = 1.0
    sv = 50.0
    noise_std = scenario.get('noise_std', 0.2)
    
    # 获取原始过程参数
    K_original = scenario['process_original']['K']
    is_reverse_action = K_original < 0  # 反向作用系统
    
    process = FOPDTProcess(
        K=scenario['process_original']['K'],
        T1=scenario['process_original']['T1'],
        L=scenario['process_original']['L'],
        dt=dt
    )
    
    controller = PIDController(
        Kp=scenario['original_pid']['Kp'],
        Ki=scenario['original_pid']['Ki'],
        Kd=scenario['original_pid'].get('Kd', 0.0),
        dt=dt
    )
    
    # 计算稳态MV（考虑负增益）
    mv_ss = sv / abs(K_original) if abs(K_original) > 0.001 else sv
    process.reset(pv_initial=sv)
    controller.reset(mv_initial=mv_ss)
    
    # 初始化积分项（考虑Ki的符号）
    Ki = scenario['original_pid']['Ki']
    if abs(Ki) > 0.001:
        controller.integral = mv_ss / Ki
    
    steady_steps = 300
    osc_steps = 500
    total_steps = steady_steps + osc_steps
    
    # 使用固定的基准时间确保可重复性（不使用 datetime.now()）
    start_time = datetime(2024, 1, 1, 0, 0, 0) - timedelta(seconds=total_steps * dt)
    history_data = []
    change_time = None
    pv = sv
    
    for step in range(total_steps):
        current_time = start_time + timedelta(seconds=step * dt)
        timestamp = int(current_time.timestamp() * 1000)
        
        if step == steady_steps:
            change_time = timestamp
            process.set_params(
                K=scenario['process_changed']['K'],
                T1=scenario['process_changed']['T1'],
                L=scenario['process_changed']['L']
            )
        
        mv = controller.compute(sv, pv)
        pv = process.step(mv)
        pv_noisy = pv + np.random.normal(0, noise_std)
        
        history_data.append({
            'timestamp': timestamp,
            'pv': round(pv_noisy, 2),
            'sv': round(sv, 2),
            'mv': round(mv, 2),
        })
    
    metadata = {
        'process_original': scenario['process_original'],
        'process_changed': scenario['process_changed'],
        'original_pid': scenario['original_pid'],
        'change_time': change_time,
        'sv': sv,
        'scenario': 'oscillation',
        'scenario_name': scenario['name'],
    }
    
    return history_data, metadata


def visualize_scenario_comparison(scenario: Dict, metadata: Dict, data: List[Dict],
                                   sim_old: Dict, sim_rule: Dict, sim_llm: Dict,
                                   pid_rule: Dict, pid_llm: Dict,
                                   result: Dict, scenario_idx: int,
                                   tuning_method: str = 'unknown'):
    """为单个场景生成可视化对比图（包含原始数据：稳态+振荡）
    
    Args:
        scenario: 场景配置
        metadata: 元数据
        data: 原始历史数据（稳态+振荡）
        sim_old/sim_rule/sim_llm: 仿真结果
        pid_rule/pid_llm: PID参数
        result: 对比结果
        scenario_idx: 场景索引
        tuning_method: 整定方法（oscillation_critical/model_fitting等）
    """
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    fig = plt.figure(figsize=(18, 12))
    
    # 标题
    winner_emoji = {'LLM': '🤖', 'Rule': '📏', 'Tie': '🤝', 'Both Failed': '❌'}.get(result['winner'], '?')
    method_str = 'Critical Method (临界法)' if 'oscillation' in tuning_method else 'Model Fitting (模型辨识)'
    fig.suptitle(f"Scenario {scenario_idx}: {scenario['name']} - {scenario['description']}\n"
                 f"Tuning Method: {method_str} | Winner: {winner_emoji} {result['winner']}", 
                 fontsize=12, fontweight='bold')
    
    sv = metadata['sv']
    pid_old = scenario['original_pid']
    
    # 提取原始数据
    timestamps = [d['timestamp'] for d in data]
    time_seconds = [(ts - timestamps[0]) / 1000 for ts in timestamps]  # 转换为秒
    pv_array = np.array([d['pv'] for d in data])
    sv_array = np.array([d['sv'] for d in data])
    mv_array = np.array([d['mv'] for d in data])
    
    # 找到系统变化时间点
    change_idx = 300  # 默认稳态300秒
    if metadata.get('change_time'):
        for i, ts in enumerate(timestamps):
            if ts >= metadata['change_time']:
                change_idx = i
                break
    
    # ========== 子图1: 原始数据 PV/SV（稳态+振荡）==========
    ax1 = fig.add_subplot(3, 3, 1)
    ax1.plot(time_seconds, pv_array, 'b-', label='PV', linewidth=0.8, alpha=0.8)
    ax1.plot(time_seconds, sv_array, 'r--', label='SV', linewidth=1.2)
    ax1.axvline(x=time_seconds[change_idx], color='red', linestyle='--', linewidth=2, alpha=0.7, label='System Changed')
    ax1.fill_between(time_seconds[:change_idx], sv * 0.95, sv * 1.05, alpha=0.1, color='blue', label='Steady State')
    ax1.fill_between(time_seconds[change_idx:], sv * 0.95, sv * 1.05, alpha=0.1, color='orange', label='Oscillation')
    ax1.set_ylabel('PV / SV')
    ax1.set_xlabel('Time (s)')
    ax1.set_title('Original Data: Steady State → Oscillation')
    ax1.legend(loc='upper right', fontsize=7)
    ax1.grid(True, alpha=0.3)
    
    # ========== 子图2: 原始数据 MV ==========
    ax2 = fig.add_subplot(3, 3, 2)
    ax2.plot(time_seconds, mv_array, 'g-', label='MV', linewidth=0.8)
    ax2.axvline(x=time_seconds[change_idx], color='red', linestyle='--', linewidth=2, alpha=0.7)
    ax2.set_ylabel('MV')
    ax2.set_xlabel('Time (s)')
    ax2.set_title('MV (Control Output)')
    ax2.legend(loc='upper right', fontsize=8)
    ax2.grid(True, alpha=0.3)
    
    # ========== 子图3: 振荡段放大 ==========
    ax3 = fig.add_subplot(3, 3, 3)
    osc_start = max(0, change_idx - 20)
    ax3.plot(time_seconds[osc_start:], pv_array[osc_start:], 'b-', label='PV', linewidth=1.0)
    ax3.plot(time_seconds[osc_start:], sv_array[osc_start:], 'r--', label='SV', linewidth=1.2)
    ax3.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5)
    ax3.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
    ax3.set_ylabel('PV / SV')
    ax3.set_xlabel('Time (s)')
    ax3.set_title('Oscillation Segment (Zoomed)')
    ax3.legend(loc='upper right', fontsize=8)
    ax3.grid(True, alpha=0.3)
    
    # ========== 子图4: Old PID 响应（新系统）==========
    ax4 = fig.add_subplot(3, 3, 4)
    ax4.plot(sim_old['t'], sim_old['pv'], 'b-', label='PV', linewidth=1.5)
    ax4.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax4.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5)
    ax4.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
    ax4.fill_between(sim_old['t'], sv * 0.95, sv * 1.05, alpha=0.1, color='green')
    status = 'Stable' if sim_old['is_stable'] else 'OSCILLATING'
    ax4.set_title(f"Old PID on Changed System: {status}\nKp={pid_old['Kp']}, Ki={pid_old['Ki']}")
    ax4.set_ylabel('PV')
    ax4.set_xlabel('Time (s)')
    ax4.legend(loc='lower right', fontsize=8)
    ax4.grid(True, alpha=0.3)
    
    # ========== 子图5: Rule Engine 响应 ==========
    ax5 = fig.add_subplot(3, 3, 5)
    ax5.plot(sim_rule['t'], sim_rule['pv'], 'orange', label='PV', linewidth=1.5)
    ax5.plot(sim_rule['t'], sim_rule['sv'], 'r--', label='SV', linewidth=1.2)
    ax5.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5)
    ax5.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
    ax5.fill_between(sim_rule['t'], sv * 0.95, sv * 1.05, alpha=0.1, color='green')
    status = 'STABLE' if sim_rule['is_stable'] else 'Oscillating'
    ax5.set_title(f"Rule Engine: {status}\npb={pid_rule.get('pb', 'N/A')}%, Kp={pid_rule.get('kp', 0):.3f}")
    ax5.set_ylabel('PV')
    ax5.set_xlabel('Time (s)')
    ax5.legend(loc='lower right', fontsize=8)
    ax5.grid(True, alpha=0.3)
    
    # ========== 子图6: LLM 响应 ==========
    ax6 = fig.add_subplot(3, 3, 6)
    ax6.plot(sim_llm['t'], sim_llm['pv'], 'g-', label='PV', linewidth=1.5)
    ax6.plot(sim_llm['t'], sim_llm['sv'], 'r--', label='SV', linewidth=1.2)
    ax6.axhline(y=sv * 1.05, color='gray', linestyle=':', alpha=0.5)
    ax6.axhline(y=sv * 0.95, color='gray', linestyle=':', alpha=0.5)
    ax6.fill_between(sim_llm['t'], sv * 0.95, sv * 1.05, alpha=0.1, color='green')
    status = 'STABLE' if sim_llm['is_stable'] else 'Oscillating'
    ax6.set_title(f"LLM: {status}\npb={pid_llm.get('pb', 'N/A')}%, Kp={pid_llm.get('kp', 0):.3f}")
    ax6.set_ylabel('PV')
    ax6.set_xlabel('Time (s)')
    ax6.legend(loc='lower right', fontsize=8)
    ax6.grid(True, alpha=0.3)
    
    # ========== 子图7: 三方对比 ==========
    ax7 = fig.add_subplot(3, 3, 7)
    ax7.plot(sim_old['t'], sim_old['pv'], 'b--', label='Old PID', linewidth=1.2, alpha=0.7)
    ax7.plot(sim_rule['t'], sim_rule['pv'], 'orange', label='Rule Engine', linewidth=1.5)
    ax7.plot(sim_llm['t'], sim_llm['pv'], 'g-', label='LLM', linewidth=1.5)
    ax7.plot(sim_old['t'], sim_old['sv'], 'r--', label='SV', linewidth=1.2)
    ax7.fill_between(sim_old['t'], sv * 0.95, sv * 1.05, alpha=0.1, color='green', label='5% Band')
    ax7.set_title('Comparison: Old PID vs Rule Engine vs LLM')
    ax7.set_ylabel('PV')
    ax7.set_xlabel('Time (s)')
    ax7.legend(loc='upper right', fontsize=8)
    ax7.grid(True, alpha=0.3)
    
    # ========== 子图8: 性能指标柱状图 ==========
    ax8 = fig.add_subplot(3, 3, 8)
    metrics = ['Settling Time (s)', 'Overshoot (%)', 'IAE/100']
    old_vals = [min(sim_old['settling_time'], 300), sim_old['overshoot'], sim_old.get('iae', 0) / 100]
    rule_vals = [min(sim_rule['settling_time'], 300), sim_rule['overshoot'], sim_rule.get('iae', 0) / 100]
    llm_vals = [min(sim_llm['settling_time'], 300), sim_llm['overshoot'], sim_llm.get('iae', 0) / 100]
    
    x = np.arange(len(metrics))
    width = 0.25
    bars1 = ax8.bar(x - width, old_vals, width, label='Old PID', color='blue', alpha=0.7)
    bars2 = ax8.bar(x, rule_vals, width, label='Rule Engine', color='orange', alpha=0.7)
    bars3 = ax8.bar(x + width, llm_vals, width, label='LLM', color='green', alpha=0.7)
    
    # 标记不稳定的
    if not sim_old['is_stable']:
        bars1[0].set_hatch('//')
    if not sim_rule['is_stable']:
        bars2[0].set_hatch('//')
    if not sim_llm['is_stable']:
        bars3[0].set_hatch('//')
    
    ax8.set_ylabel('Value')
    ax8.set_title('Performance Metrics (hatched = unstable)')
    ax8.set_xticks(x)
    ax8.set_xticklabels(metrics)
    ax8.legend(fontsize=8)
    ax8.grid(True, alpha=0.3)
    
    # ========== 子图9: 详细信息 ==========
    ax9 = fig.add_subplot(3, 3, 9)
    ax9.axis('off')
    
    llm_decision = pid_llm.get('llm_decision', {})
    strategy = llm_decision.get('strategy_params', {}) if llm_decision else {}
    
    info = f"""
SCENARIO INFO
{'='*50}
Process Original: K={scenario['process_original']['K']}, T1={scenario['process_original']['T1']}s
Process Changed:  K={scenario['process_changed']['K']}, T1={scenario['process_changed']['T1']}s, L={scenario['process_changed']['L']}s
Loop Type: {scenario.get('loop_type', 'flow')}
Tuning Method: {tuning_method}

PERFORMANCE COMPARISON
{'='*50}
                Old PID    Rule       LLM
Stable:         {'Yes' if sim_old['is_stable'] else 'No':<10} {'Yes' if sim_rule['is_stable'] else 'No':<10} {'Yes' if sim_llm['is_stable'] else 'No'}
Settling (s):   {sim_old['settling_time']:<10.0f} {sim_rule['settling_time']:<10.0f} {sim_llm['settling_time']:.0f}
Overshoot (%):  {sim_old['overshoot']:<10.1f} {sim_rule['overshoot']:<10.1f} {sim_llm['overshoot']:.1f}
IAE:            {sim_old.get('iae', 0):<10.0f} {sim_rule.get('iae', 0):<10.0f} {sim_llm.get('iae', 0):.0f}

PID PARAMETERS
{'='*50}
                Old PID    Rule       LLM
Kp:             {pid_old['Kp']:<10} {pid_rule.get('kp', 0):<10.4f} {pid_llm.get('kp', 0):.4f}
Ki:             {pid_old['Ki']:<10} {pid_rule.get('ki', 0):<10.4f} {pid_llm.get('ki', 0):.4f}
pb (%):         -          {str(pid_rule.get('pb', 'N/A')):<10} {pid_llm.get('pb', 'N/A')}

LLM STRATEGY (if used)
{'='*50}
safety_factor:    {strategy.get('safety_factor', 'N/A')}
pb_extra_factor:  {strategy.get('pb_extra_factor', 'N/A')}
ti_multiplier:    {strategy.get('ti_multiplier', 'N/A')}
"""
    ax9.text(0.02, 0.98, info, transform=ax9.transAxes, fontsize=8,
             verticalalignment='top', fontfamily='monospace',
             bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    
    plt.tight_layout()
    
    # 保存图片到 stability 子目录
    stability_dir = os.path.join(CONFIG['output_dir'], 'stability')
    os.makedirs(stability_dir, exist_ok=True)
    safe_name = scenario['name'].replace(' ', '_').replace('/', '_')
    filename = f'scenario_{scenario_idx:02d}_{safe_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    filepath = os.path.join(stability_dir, filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"   📊 Scenario chart saved: {filepath}")
    plt.close()


def run_batch_test():
    """批量测试多个场景，对比 LLM vs 规则引擎"""
    print("=" * 80)
    print("BATCH TEST: LLM vs Rule Engine across Multiple Scenarios")
    print("=" * 80)
    
    # 检查 Ollama 连接
    print("\n📡 Checking Ollama connection...")
    llm_client = None
    try:
        llm_client = OllamaClient(
            model=CONFIG['ollama_model'],
            base_url=CONFIG['ollama_base_url']
        )
        llm_client.chat("OK")
        print(f"   ✅ Ollama connected (model: {CONFIG['ollama_model']})")
    except Exception as e:
        print(f"   ❌ Ollama connection failed: {e}")
        print("   Cannot run batch comparison without LLM")
        return
    
    results = []
    
    for idx, scenario in enumerate(TEST_SCENARIOS, 1):
        print(f"\n{'='*80}")
        print(f"Scenario {idx}/{len(TEST_SCENARIOS)}: {scenario['name']}")
        print(f"Description: {scenario['description']}")
        print(f"Process: K={scenario['process_changed']['K']}, T1={scenario['process_changed']['T1']}, L={scenario['process_changed']['L']}")
        print("=" * 80)
        
        # 生成数据
        data, metadata = generate_scenario_data(scenario)
        
        # 检测扰动窗口
        windows = detect_disturbance_windows(data)
        if not windows:
            print("   ⚠️ No oscillation detected, skipping...")
            results.append({
                'scenario': scenario['name'],
                'status': 'skipped',
                'reason': 'no oscillation detected'
            })
            continue
        
        input_data = {
            'history_data': data,
            'params': {'model_type': None, 'turning_type': None, 'analyst_column': 'pv'},
            'qualified_windows': windows,
        }
        
        # 保存原始配置
        original_enable_llm = Config.OSCILLATION_TUNING.get('enable_llm', True)
        
        try:
            # 规则引擎整定
            print("   🔧 Rule Engine tuning...")
            Config.OSCILLATION_TUNING['enable_llm'] = False
            selector_rule = ModelSelector(verbose=False)
            result_rule = selector_rule.run(input_data)
            
            # 检查整定方法
            fusion_method = result_rule.get('fusion_info', {}).get('method', 'unknown')
            print(f"   📋 Method: {fusion_method}")
            
            # LLM 整定
            print("   🤖 LLM tuning...")
            Config.OSCILLATION_TUNING['enable_llm'] = True
            loop_type = scenario.get('loop_type', 'flow')
            selector_llm = ModelSelector(
                verbose=False,
                llm_client=llm_client,
                process_context={'loop_type': loop_type, 'loop_name': scenario['name']}
            )
            result_llm = selector_llm.run(input_data)
            
        finally:
            Config.OSCILLATION_TUNING['enable_llm'] = original_enable_llm
        
        # 仿真对比（使用更长时间和5%误差带）
        sim_duration = 300
        error_band = 0.05  # 5% 误差带
        
        sim_old = simulate_with_new_pid(
            scenario['process_changed'],
            scenario['original_pid'],
            metadata['sv'],
            duration=sim_duration,
            error_band_pct=error_band
        )
        
        pid_rule = result_rule.get('pid_parameters', {})
        sim_rule = simulate_with_new_pid(
            scenario['process_changed'],
            pid_rule,
            metadata['sv'],
            duration=sim_duration,
            error_band_pct=error_band
        )
        
        pid_llm = result_llm.get('pid_parameters', {})
        sim_llm = simulate_with_new_pid(
            scenario['process_changed'],
            pid_llm,
            metadata['sv'],
            duration=sim_duration,
            error_band_pct=error_band
        )
        
        # 记录结果
        llm_decision = pid_llm.get('llm_decision', {})
        llm_actually_used = bool(llm_decision and llm_decision.get('strategy_params'))
        
        result = {
            'scenario': scenario['name'],
            'description': scenario['description'],
            'loop_type': scenario.get('loop_type', 'flow'),
            'old_stable': sim_old['is_stable'],
            'old_ts': sim_old['settling_time'],
            'old_os': sim_old['overshoot'],
            'old_iae': sim_old.get('iae', 0),
            'rule_stable': sim_rule['is_stable'],
            'rule_ts': sim_rule['settling_time'],
            'rule_os': sim_rule['overshoot'],
            'rule_pb': pid_rule.get('pb', 'N/A'),
            'rule_iae': sim_rule.get('iae', 0),
            'llm_stable': sim_llm['is_stable'],
            'llm_ts': sim_llm['settling_time'],
            'llm_os': sim_llm['overshoot'],
            'llm_pb': pid_llm.get('pb', 'N/A'),
            'llm_iae': sim_llm.get('iae', 0),
            'llm_decision': pid_llm.get('llm_decision', {}),
            'llm_actually_used': llm_actually_used,
        }
        
        # 判断谁更好
        # 判断谁更好（综合考虑稳定性、调节时间、IAE）
        if sim_rule['is_stable'] and sim_llm['is_stable']:
            # 两者都稳定，比较 IAE（更全面的指标）
            rule_iae = sim_rule.get('iae', float('inf'))
            llm_iae = sim_llm.get('iae', float('inf'))
            
            # IAE 改进超过 10% 才算赢
            if llm_iae < rule_iae * 0.9:
                result['winner'] = 'LLM'
                result['improvement'] = (rule_iae - llm_iae) / rule_iae * 100
            elif rule_iae < llm_iae * 0.9:
                result['winner'] = 'Rule'
                result['improvement'] = (llm_iae - rule_iae) / llm_iae * 100
            else:
                # IAE 相近，比较调节时间
                if sim_llm['settling_time'] < sim_rule['settling_time'] * 0.85:
                    result['winner'] = 'LLM'
                    result['improvement'] = (sim_rule['settling_time'] - sim_llm['settling_time']) / sim_rule['settling_time'] * 100
                elif sim_rule['settling_time'] < sim_llm['settling_time'] * 0.85:
                    result['winner'] = 'Rule'
                    result['improvement'] = (sim_llm['settling_time'] - sim_rule['settling_time']) / sim_llm['settling_time'] * 100
                else:
                    result['winner'] = 'Tie'
                    result['improvement'] = 0
        elif sim_llm['is_stable'] and not sim_rule['is_stable']:
            result['winner'] = 'LLM'
            result['improvement'] = 100
        elif sim_rule['is_stable'] and not sim_llm['is_stable']:
            result['winner'] = 'Rule'
            result['improvement'] = 100
        elif sim_llm.get('is_converging') and not sim_rule.get('is_converging'):
            # 都不稳定，但 LLM 在收敛
            result['winner'] = 'LLM'
            result['improvement'] = 50
        elif sim_rule.get('is_converging') and not sim_llm.get('is_converging'):
            result['winner'] = 'Rule'
            result['improvement'] = 50
        else:
            result['winner'] = 'Both Failed'
            result['improvement'] = 0
        
        results.append(result)
        
        # 分析失败原因
        failure_reason = ""
        if result['winner'] == 'Both Failed':
            if sim_old['is_stable']:
                failure_reason = "Old PID already stable (bad test case)"
            elif pid_rule.get('pb') == 100.0:
                failure_reason = "Model identification failed (pb=100%)"
            elif pid_rule.get('pb', 0) >= 500:
                failure_reason = "Too conservative (pb>=500%)"
            else:
                failure_reason = "Unknown"
        result['failure_reason'] = failure_reason
        
        print(f"   Old PID:     Stable={sim_old['is_stable']}, Ts={sim_old['settling_time']:.0f}s, IAE={sim_old.get('iae', 0):.0f}")
        print(f"   Rule Engine: Stable={sim_rule['is_stable']}, Ts={sim_rule['settling_time']:.0f}s, IAE={sim_rule.get('iae', 0):.0f}, pb={pid_rule.get('pb', 'N/A')}%")
        print(f"   LLM:         Stable={sim_llm['is_stable']}, Ts={sim_llm['settling_time']:.0f}s, IAE={sim_llm.get('iae', 0):.0f}, pb={pid_llm.get('pb', 'N/A')}%")
        print(f"   LLM Actually Used: {llm_actually_used}")
        if llm_decision:
            strategy = llm_decision.get('strategy_params', {})
            print(f"   LLM Strategy: safety={strategy.get('safety_factor')}, pb_extra={strategy.get('pb_extra_factor')}, ti_mult={strategy.get('ti_multiplier')}")
        print(f"   Winner: {result['winner']}")
        if failure_reason:
            print(f"   ⚠️ Failure Reason: {failure_reason}")
        
        # 获取整定方法
        tuning_method = result_rule.get('fusion_info', {}).get('method', 'unknown')
        result['tuning_method'] = tuning_method
        
        # 为每个场景生成可视化（包含原始数据）
        visualize_scenario_comparison(
            scenario=scenario,
            metadata=metadata,
            data=data,  # 传递原始数据
            sim_old=sim_old,
            sim_rule=sim_rule,
            sim_llm=sim_llm,
            pid_rule=pid_rule,
            pid_llm=pid_llm,
            result=result,
            scenario_idx=idx,
            tuning_method=tuning_method  # 传递整定方法
        )
    
    # 汇总结果
    print("\n" + "=" * 100)
    print("BATCH TEST SUMMARY")
    print("=" * 100)
    
    # 过滤有效结果
    valid_results = [r for r in results if r.get('status') != 'skipped']
    
    print(f"\n{'Scenario':<20} {'Old':<10} {'Rule':<15} {'LLM':<15} {'Winner':<12} {'Improvement':<12}")
    print("-" * 100)
    
    llm_wins = 0
    rule_wins = 0
    ties = 0
    both_failed = 0
    
    for r in results:
        if r.get('status') == 'skipped':
            print(f"{r['scenario']:<20} {'SKIPPED':<10}")
            continue
        
        old_str = f"{'✓' if r['old_stable'] else '✗'} {r['old_ts']:.0f}s"
        rule_str = f"{'✓' if r['rule_stable'] else '✗'} {r['rule_ts']:.0f}s"
        llm_str = f"{'✓' if r['llm_stable'] else '✗'} {r['llm_ts']:.0f}s"
        
        winner = r['winner']
        if winner == 'LLM':
            llm_wins += 1
            winner_str = '🤖 LLM'
        elif winner == 'Rule':
            rule_wins += 1
            winner_str = '📏 Rule'
        elif winner == 'Tie':
            ties += 1
            winner_str = '🤝 Tie'
        else:
            both_failed += 1
            winner_str = '❌ Both'
        
        improvement = f"{r['improvement']:.0f}%" if r['improvement'] > 0 else '-'
        
        print(f"{r['scenario']:<20} {old_str:<10} {rule_str:<15} {llm_str:<15} {winner_str:<12} {improvement:<12}")
    
    print("-" * 100)
    print(f"\nTotal Scenarios: {len(results)}")
    print(f"LLM Wins:        {llm_wins} ({llm_wins/len(results)*100:.0f}%)")
    print(f"Rule Wins:       {rule_wins} ({rule_wins/len(results)*100:.0f}%)")
    print(f"Ties:            {ties} ({ties/len(results)*100:.0f}%)")
    print(f"Both Failed:     {both_failed} ({both_failed/len(results)*100:.0f}%)")
    
    # 失败原因分析
    if both_failed > 0:
        print(f"\n⚠️ Failure Analysis:")
        failure_reasons = {}
        for r in valid_results:
            if r.get('winner') == 'Both Failed':
                reason = r.get('failure_reason', 'Unknown')
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
        for reason, count in failure_reasons.items():
            print(f"   - {reason}: {count} scenarios")
    
    # LLM 实际使用率
    llm_used_count = sum(1 for r in valid_results if r.get('llm_actually_used', False))
    print(f"\nLLM Actually Called: {llm_used_count}/{len(valid_results)} scenarios")
    if llm_used_count < len(valid_results):
        print("   ⚠️ LLM was NOT called in some scenarios - check if oscillation tuning was triggered")
    
    # 生成汇总图表
    visualize_batch_results(results)
    
    print("\n✅ Batch test completed!")
    return results


def visualize_batch_results(results: List[Dict]):
    """可视化批量测试结果"""
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    # 过滤有效结果
    valid_results = [r for r in results if r.get('status') != 'skipped']
    if not valid_results:
        return
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle('Batch Test: LLM vs Rule Engine Comparison', fontsize=14, fontweight='bold')
    
    scenarios = [r['scenario'][:15] for r in valid_results]
    rule_ts = [r['rule_ts'] if r['rule_stable'] else 200 for r in valid_results]
    llm_ts = [r['llm_ts'] if r['llm_stable'] else 200 for r in valid_results]
    rule_stable = [r['rule_stable'] for r in valid_results]
    llm_stable = [r['llm_stable'] for r in valid_results]
    
    # 子图1: 调节时间对比
    ax1 = axes[0, 0]
    x = np.arange(len(scenarios))
    width = 0.35
    bars1 = ax1.bar(x - width/2, rule_ts, width, label='Rule Engine', color='orange', alpha=0.8)
    bars2 = ax1.bar(x + width/2, llm_ts, width, label='LLM', color='green', alpha=0.8)
    
    # 标记不稳定的
    for i, (rs, ls) in enumerate(zip(rule_stable, llm_stable)):
        if not rs:
            bars1[i].set_hatch('//')
            bars1[i].set_edgecolor('red')
        if not ls:
            bars2[i].set_hatch('//')
            bars2[i].set_edgecolor('red')
    
    ax1.set_ylabel('Settling Time (s)')
    ax1.set_title('Settling Time Comparison (hatched = unstable)')
    ax1.set_xticks(x)
    ax1.set_xticklabels(scenarios, rotation=45, ha='right')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 子图2: 稳定性对比
    ax2 = axes[0, 1]
    rule_stable_count = sum(rule_stable)
    llm_stable_count = sum(llm_stable)
    categories = ['Rule Engine', 'LLM']
    stable_counts = [rule_stable_count, llm_stable_count]
    unstable_counts = [len(valid_results) - rule_stable_count, len(valid_results) - llm_stable_count]
    
    ax2.bar(categories, stable_counts, label='Stable', color='green', alpha=0.8)
    ax2.bar(categories, unstable_counts, bottom=stable_counts, label='Unstable', color='red', alpha=0.8)
    ax2.set_ylabel('Count')
    ax2.set_title('Stability Comparison')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 子图3: 胜负统计
    ax3 = axes[1, 0]
    winners = [r['winner'] for r in valid_results]
    winner_counts = {
        'LLM': winners.count('LLM'),
        'Rule': winners.count('Rule'),
        'Tie': winners.count('Tie'),
        'Both Failed': winners.count('Both Failed'),
    }
    colors = ['green', 'orange', 'gray', 'red']
    ax3.pie(winner_counts.values(), labels=winner_counts.keys(), autopct='%1.0f%%', 
            colors=colors, startangle=90)
    ax3.set_title('Winner Distribution')
    
    # 子图4: 详细结果表
    ax4 = axes[1, 1]
    ax4.axis('off')
    
    table_data = []
    for r in valid_results:
        row = [
            r['scenario'][:12],
            f"{'✓' if r['rule_stable'] else '✗'} {r['rule_ts']:.0f}s",
            f"{'✓' if r['llm_stable'] else '✗'} {r['llm_ts']:.0f}s",
            r['winner'],
        ]
        table_data.append(row)
    
    table = ax4.table(
        cellText=table_data,
        colLabels=['Scenario', 'Rule Engine', 'LLM', 'Winner'],
        loc='center',
        cellLoc='center',
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.5)
    ax4.set_title('Detailed Results')
    
    plt.tight_layout()
    
    os.makedirs(CONFIG['output_dir'], exist_ok=True)
    filename = f'batch_test_results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
    filepath = os.path.join(CONFIG['output_dir'], filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight')
    print(f"\n📊 Batch results chart saved: {filepath}")
    plt.close()


def run_amplitude_test():
    """运行幅度变化测试"""
    print("=" * 70)
    print("AMPLITUDE VARIATION TEST")
    print("Testing same scenarios with different change magnitudes")
    print("=" * 70)
    
    # 使用预定义的幅度测试场景
    scenarios = AMPLITUDE_TEST_SCENARIOS
    print(f"\n📊 Total scenarios: {len(scenarios)}")
    
    # 按基础场景分组显示
    base_names = set()
    for s in scenarios:
        # 提取基础场景名（去掉幅度后缀）
        base_name = s['name'].rsplit(' (×', 1)[0]
        base_names.add(base_name)
    
    print(f"📊 Base scenarios: {len(base_names)}")
    for name in sorted(base_names):
        print(f"   - {name}")
    
    # 运行测试（复用 batch test 逻辑）
    results = []
    
    # 检查 Ollama
    try:
        ollama_client = OllamaClient(
            model=CONFIG['ollama_model'],
            base_url=CONFIG['ollama_base_url']
        )
        ollama_client.chat("test")
        print(f"\n📡 Ollama connected (model: {CONFIG['ollama_model']})")
    except Exception as e:
        print(f"\n⚠️ Ollama not available: {e}")
        print("   Running Rule Engine only mode")
        ollama_client = None
    
    for i, scenario in enumerate(scenarios):
        print(f"\n{'='*70}")
        print(f"Scenario {i+1}/{len(scenarios)}: {scenario['name']}")
        print(f"Description: {scenario['description']}")
        print(f"Process: K={scenario['process_changed']['K']}, "
              f"T1={scenario['process_changed']['T1']}, L={scenario['process_changed']['L']}")
        print("=" * 70)
        
        try:
            # 生成数据
            data, metadata = generate_scenario_data(scenario)
            
            # 检测扰动窗口
            change_time = metadata['change_time']
            end_time = data[-1]['timestamp']
            qualified_windows = [{'start_time': change_time, 'end_time': end_time}]
            
            # Rule Engine 整定
            print("   🔧 Rule Engine tuning...")
            Config.OSCILLATION_TUNING['enable_llm'] = False
            selector_rule = ModelSelector(verbose=False)
            result_rule = selector_rule.run({
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
            })
            pid_rule = result_rule.get('pid_parameters', {})
            
            # LLM 整定
            if ollama_client:
                print("   🤖 LLM tuning...")
                Config.OSCILLATION_TUNING['enable_llm'] = True
                selector_llm = ModelSelector(
                    verbose=False,
                    llm_client=ollama_client,
                    process_context={'loop_type': scenario.get('loop_type', 'flow')}
                )
                result_llm = selector_llm.run({
                    'history_data': data,
                    'params': {},
                    'qualified_windows': qualified_windows,
                })
                pid_llm = result_llm.get('pid_parameters', {})
            else:
                pid_llm = pid_rule
            
            # 根据回路类型选择仿真时长（慢系统需要更长时间）
            loop_type = scenario.get('loop_type', 'flow')
            if loop_type == 'temperature':
                sim_duration = 600  # 温度回路：600s
            elif loop_type == 'level':
                sim_duration = 500  # 液位回路：500s
            else:
                sim_duration = 300  # 流量/压力回路：300s
            
            # 仿真对比
            sim_old = simulate_with_new_pid(
                scenario['process_changed'],
                scenario['original_pid'],
                metadata['sv'],
                duration=sim_duration
            )
            sim_rule = simulate_with_new_pid(
                scenario['process_changed'],
                {'Kp': pid_rule.get('kp', 1), 'Ki': pid_rule.get('ki', 0), 'Kd': pid_rule.get('kd', 0)},
                metadata['sv'],
                duration=sim_duration
            )
            sim_llm = simulate_with_new_pid(
                scenario['process_changed'],
                {'Kp': pid_llm.get('kp', 1), 'Ki': pid_llm.get('ki', 0), 'Kd': pid_llm.get('kd', 0)},
                metadata['sv'],
                duration=sim_duration
            )
            
            # 记录结果
            results.append({
                'scenario': scenario['name'],
                'base_scenario': scenario['name'].rsplit(' (×', 1)[0],
                'amplitude_factor': scenario.get('amplitude_factor', 1.0),
                'old_stable': sim_old['is_stable'],
                'old_ts': sim_old['settling_time'],
                'rule_stable': sim_rule['is_stable'],
                'rule_ts': sim_rule['settling_time'],
                'rule_pb': pid_rule.get('pb', 0),
                'llm_stable': sim_llm['is_stable'],
                'llm_ts': sim_llm['settling_time'],
                'llm_pb': pid_llm.get('pb', 0),
            })
            
            status_old = "✓" if sim_old['is_stable'] else "✗"
            status_rule = "✓" if sim_rule['is_stable'] else "✗"
            status_llm = "✓" if sim_llm['is_stable'] else "✗"
            
            print(f"   Old PID:     {status_old} Ts={sim_old['settling_time']:.0f}s")
            print(f"   Rule Engine: {status_rule} Ts={sim_rule['settling_time']:.0f}s, pb={pid_rule.get('pb', 0):.1f}%")
            print(f"   LLM:         {status_llm} Ts={sim_llm['settling_time']:.0f}s, pb={pid_llm.get('pb', 0):.1f}%")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
    
    # 打印汇总
    print("\n" + "=" * 90)
    print("AMPLITUDE TEST SUMMARY")
    print("=" * 90)
    
    # 按基础场景分组统计
    from collections import defaultdict
    grouped = defaultdict(list)
    for r in results:
        grouped[r['base_scenario']].append(r)
    
    print(f"\n{'Base Scenario':<30} {'Factor':<8} {'Old':<8} {'Rule':<12} {'LLM':<12}")
    print("-" * 90)
    
    for base_name in sorted(grouped.keys()):
        group = sorted(grouped[base_name], key=lambda x: x['amplitude_factor'])
        for r in group:
            old_status = "✓" if r['old_stable'] else "✗"
            rule_status = f"✓ {r['rule_ts']:.0f}s" if r['rule_stable'] else "✗"
            llm_status = f"✓ {r['llm_ts']:.0f}s" if r['llm_stable'] else "✗"
            
            print(f"{r['base_scenario']:<30} ×{r['amplitude_factor']:<6.2f} "
                  f"{old_status:<8} {rule_status:<12} {llm_status:<12}")
    
    # 统计成功率
    total = len(results)
    rule_success = sum(1 for r in results if r['rule_stable'])
    llm_success = sum(1 for r in results if r['llm_stable'])
    
    print("-" * 90)
    print(f"\nSuccess Rate:")
    print(f"   Rule Engine: {rule_success}/{total} ({rule_success/total*100:.1f}%)")
    print(f"   LLM:         {llm_success}/{total} ({llm_success/total*100:.1f}%)")
    
    print("\n✅ Amplitude test completed!")


def run_model_id_test():
    """运行模型辨识测试（非振荡场景，MV阶跃响应）
    
    测试场景：系统有MV阶跃变化，PV有响应但不振荡
    整定方法：应该使用模型辨识（FOPDT拟合）+ Lambda整定
    """
    print("=" * 70)
    print("MODEL IDENTIFICATION TEST")
    print("Testing step response scenarios (non-oscillating)")
    print("Expected: Lambda tuning (模型辨识整定), NOT critical method (临界法)")
    print("=" * 70)
    
    scenarios = MODEL_ID_SCENARIOS
    print(f"\n📊 Total scenarios: {len(scenarios)}")
    
    results = []
    
    for i, scenario in enumerate(scenarios):
        print(f"\n{'='*70}")
        print(f"Scenario {i+1}/{len(scenarios)}: {scenario['name']}")
        print(f"Description: {scenario['description']}")
        print(f"Process: K={scenario['process']['K']}, T1={scenario['process']['T1']}, L={scenario['process']['L']}")
        print(f"MV Step: {scenario.get('mv_step', 10.0)}")
        print("=" * 70)
        
        try:
            # 生成阶跃响应数据
            data, metadata = generate_step_response_scenario_data(scenario)
            
            # 设置扰动窗口：从阶跃前50点开始，包含完整的阶跃变化
            change_time = metadata['change_time']
            start_time = data[0]['timestamp']  # 从数据开始
            end_time = data[-1]['timestamp']
            
            # 窗口需要包含MV阶跃变化，所以从阶跃前开始
            # 阶跃发生在第100点，窗口从第50点开始
            window_start_idx = 50
            window_start_time = data[window_start_idx]['timestamp']
            qualified_windows = [{'start_time': window_start_time, 'end_time': end_time}]
            
            # 运行整定（不启用LLM，因为LLM只用于临界法）
            print("   🔧 Running model identification tuning...")
            Config.OSCILLATION_TUNING['enable_llm'] = False
            selector = ModelSelector(verbose=True)
            result = selector.run({
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
            })
            
            # 获取整定结果
            pid_new = result.get('pid_parameters', {})
            model_params = result.get('model_parameters', {})
            fusion_info = result.get('fusion_info', {})
            tuning_method = fusion_info.get('method', 'unknown')
            
            # 检查是否使用了正确的整定方法
            # Lambda整定 = 模型辨识 + Lambda公式，方法名通常是 best_window, weighted_average 等
            # 临界法整定 = 振荡数据 + Z-N公式，方法名包含 oscillation
            is_oscillation_tuning = 'oscillation' in tuning_method.lower() or 'critical' in tuning_method.lower()
            is_model_based_tuning = not is_oscillation_tuning  # 非临界法就是模型辨识法
            
            print(f"\n   📋 Tuning Method: {tuning_method}")
            if is_model_based_tuning:
                print(f"   ✅ Correct: Using Model-based tuning (Lambda)")
            else:
                print(f"   ⚠️ Warning: Using oscillation/critical tuning (should be Model-based)")
            
            # 模型辨识精度
            true_K = scenario['process']['K']
            true_T1 = scenario['process']['T1']
            true_L = scenario['process']['L']
            
            id_K = model_params.get('K', 0)
            id_T1 = model_params.get('T1', 0)
            id_L = model_params.get('L', model_params.get('delay', 0))
            
            K_error = abs(id_K - true_K) / true_K * 100 if true_K != 0 else 0
            T1_error = abs(id_T1 - true_T1) / true_T1 * 100 if true_T1 != 0 else 0
            L_error = abs(id_L - true_L) / true_L * 100 if true_L != 0 else 0
            
            print(f"\n   📊 Model Identification Accuracy:")
            print(f"      K:  True={true_K:.2f}, Identified={id_K:.2f}, Error={K_error:.1f}%")
            print(f"      T1: True={true_T1:.1f}s, Identified={id_T1:.1f}s, Error={T1_error:.1f}%")
            print(f"      L:  True={true_L:.1f}s, Identified={id_L:.1f}s, Error={L_error:.1f}%")
            
            # 仿真验证
            sim_duration = 400
            if scenario.get('loop_type') == 'temperature':
                sim_duration = 600
            elif scenario.get('loop_type') == 'level':
                sim_duration = 500
            
            # Old PID 仿真
            sim_old = simulate_with_new_pid(
                scenario['process'],
                scenario['pid'],
                metadata['sv'],
                duration=sim_duration
            )
            
            # New PID 仿真
            sim_new = simulate_with_new_pid(
                scenario['process'],
                {'Kp': pid_new.get('kp', 1), 'Ki': pid_new.get('ki', 0), 'Kd': pid_new.get('kd', 0)},
                metadata['sv'],
                duration=sim_duration
            )
            
            print(f"\n   📈 Simulation Results:")
            print(f"      Old PID: Stable={sim_old['is_stable']}, Ts={sim_old['settling_time']:.0f}s, OS={sim_old['overshoot']:.1f}%")
            print(f"      New PID: Stable={sim_new['is_stable']}, Ts={sim_new['settling_time']:.0f}s, OS={sim_new['overshoot']:.1f}%")
            print(f"      New PID params: pb={pid_new.get('pb', 'N/A')}%, Kp={pid_new.get('kp', 0):.4f}, Ki={pid_new.get('ki', 0):.4f}")
            
            # 判断是否改进
            improved = False
            if sim_new['is_stable'] and sim_old['is_stable']:
                if sim_new['settling_time'] < sim_old['settling_time'] * 0.9:
                    improved = True
                    print(f"   ✅ Improved: Settling time reduced by {(sim_old['settling_time'] - sim_new['settling_time']) / sim_old['settling_time'] * 100:.0f}%")
                elif sim_new['settling_time'] <= sim_old['settling_time'] * 1.1:
                    improved = True
                    print(f"   ✅ Similar performance (within 10%)")
                else:
                    print(f"   ⚠️ Performance degraded")
            elif sim_new['is_stable'] and not sim_old['is_stable']:
                improved = True
                print(f"   ✅ Improved: New PID stabilized the system")
            elif not sim_new['is_stable']:
                print(f"   ❌ Failed: New PID is unstable")
            
            results.append({
                'scenario': scenario['name'],
                'loop_type': scenario.get('loop_type', 'flow'),
                'tuning_method': tuning_method,
                'is_model_based': is_model_based_tuning,
                'K_error': K_error,
                'T1_error': T1_error,
                'L_error': L_error,
                'old_stable': sim_old['is_stable'],
                'old_ts': sim_old['settling_time'],
                'new_stable': sim_new['is_stable'],
                'new_ts': sim_new['settling_time'],
                'new_pb': pid_new.get('pb', 0),
                'improved': improved,
            })
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'scenario': scenario['name'],
                'error': str(e),
            })
    
    # 打印汇总
    print("\n" + "=" * 100)
    print("MODEL IDENTIFICATION TEST SUMMARY")
    print("=" * 100)
    
    print(f"\n{'Scenario':<25} {'Method':<20} {'K Err':<8} {'T1 Err':<8} {'L Err':<8} {'Old Ts':<8} {'New Ts':<8} {'Result':<10}")
    print("-" * 100)
    
    model_based_count = 0
    success_count = 0
    total_valid = 0
    
    for r in results:
        if 'error' in r:
            print(f"{r['scenario']:<25} ERROR: {r['error']}")
            continue
        
        total_valid += 1
        if r['is_model_based']:
            model_based_count += 1
        if r['improved']:
            success_count += 1
        
        method_short = r['tuning_method'][:18] if len(r['tuning_method']) > 18 else r['tuning_method']
        result_str = "✅ OK" if r['improved'] else "❌ Fail"
        
        print(f"{r['scenario']:<25} {method_short:<20} {r['K_error']:<8.1f} {r['T1_error']:<8.1f} {r['L_error']:<8.1f} "
              f"{r['old_ts']:<8.0f} {r['new_ts']:<8.0f} {result_str:<10}")
    
    print("-" * 100)
    print(f"\nSummary:")
    print(f"   Total scenarios: {len(results)}")
    print(f"   Model-based tuning (Lambda): {model_based_count}/{total_valid} ({model_based_count/total_valid*100:.0f}%)" if total_valid > 0 else "   No valid results")
    print(f"   Oscillation tuning (Critical): {total_valid - model_based_count}/{total_valid} ({(total_valid - model_based_count)/total_valid*100:.0f}%)" if total_valid > 0 else "")
    print(f"   Success rate: {success_count}/{total_valid} ({success_count/total_valid*100:.0f}%)" if total_valid > 0 else "")
    
    # 模型辨识精度统计
    if total_valid > 0:
        avg_K_err = np.mean([r['K_error'] for r in results if 'K_error' in r])
        avg_T1_err = np.mean([r['T1_error'] for r in results if 'T1_error' in r])
        avg_L_err = np.mean([r['L_error'] for r in results if 'L_error' in r])
        print(f"\n   Average Model ID Error:")
        print(f"      K:  {avg_K_err:.1f}%")
        print(f"      T1: {avg_T1_err:.1f}%")
        print(f"      L:  {avg_L_err:.1f}%")
    
    print("\n✅ Model identification test completed!")
    return results


# ============================================================
# 目标1: 振荡场景稳态验证 (run_stability_test)
# ============================================================
def run_stability_test():
    """目标1: 振荡场景稳态验证
    
    验证现有算法和LLM+算法能否在不同生产振荡场景中让控制器达到稳态
    """
    # 全局随机种子重置，确保可重复性
    np.random.seed(25)
    
    print("=" * 80)
    print("目标1: 振荡场景稳态验证")
    print("验证现有算法和LLM+算法能否在不同生产振荡场景中让控制器达到稳态")
    print("=" * 80)
    
    # 检查 LLM 连接
    print("\n📡 检查 Ollama 连接...")
    llm_available = False
    
    # 如果配置中明确跳过 LLM 测试
    if CONFIG.get('skip_llm_test', False):
        print("   ⚠️ 配置中已设置 skip_llm_test=True，跳过 LLM 测试")
        print("   将只测试规则引擎模式")
    else:
        try:
            llm_client = OllamaClient(
                model=CONFIG['ollama_model'],
                base_url=CONFIG['ollama_base_url']
            )
            llm_client.chat("test")
            print(f"   ✅ Ollama 连接成功 (模型: {CONFIG['ollama_model']})")
            llm_available = True
        except Exception as e:
            print(f"   ⚠️ Ollama 连接失败: {e}")
            print("   将只测试规则引擎模式")
    
    # 使用振荡场景
    scenarios = TEST_SCENARIOS
    print(f"\n📊 测试场景总数: {len(scenarios)}")
    
    results = []
    rule_stable_count = 0
    llm_stable_count = 0
    
    for idx, scenario in enumerate(scenarios, 1):
        # 每个场景使用固定种子确保可重复性
        # 注意：不使用 hash()，因为 Python 3.3+ 默认每次运行 hash 结果不同
        scenario_seed = idx * 1000  # 使用场景索引作为种子基础
        np.random.seed(scenario_seed)
        
        print(f"\n{'─'*70}")
        print(f"场景 {idx}/{len(scenarios)}: {scenario['name']}")
        print(f"描述: {scenario['description']}")
        print("─" * 70)
        
        try:
            # 生成振荡数据，传入固定种子
            data, metadata = generate_scenario_data(scenario, seed=scenario_seed)
            
            # 检测扰动窗口
            change_time = metadata['change_time']
            end_time = data[-1]['timestamp']
            qualified_windows = [{'start_time': change_time, 'end_time': end_time}]
            
            input_data = {
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
            }
            
            # 获取变化后的过程参数用于仿真
            process_changed = scenario['process_changed']
            sv = metadata['sv']
            
            # 动态仿真时长：极慢系统需要更长时间
            T1_changed = process_changed.get('T1', 30)
            L_changed = process_changed.get('L', 5)
            # 使用 5 倍时间常数确保极慢系统有足够时间稳定
            sim_duration = max(400, int((T1_changed + L_changed) * 5))
            
            # ===== 规则引擎整定 =====
            print("   🔧 规则引擎整定...")
            # 重置种子确保 ModelSelector 内部的 scipy.optimize 也可重复
            np.random.seed(scenario_seed + 100)
            Config.OSCILLATION_TUNING['enable_llm'] = False
            selector_rule = ModelSelector(verbose=False)
            result_rule = selector_rule.run(input_data)
            pid_rule = result_rule.get('pid_parameters', {})
            
            # 重置种子用于仿真
            np.random.seed(scenario_seed + 200)
            
            # 仿真规则引擎参数（使用固定种子确保可重复）
            sim_seed = scenario_seed + 300  # 使用 scenario_seed 而非 hash()
            sim_rule = simulate_with_new_pid(process_changed, pid_rule, sv, duration=sim_duration, seed=sim_seed)
            rule_stable = sim_rule['is_stable']
            if rule_stable:
                rule_stable_count += 1
            print(f"      稳态: {'✅ 是' if rule_stable else '❌ 否'} (Ts={sim_rule['settling_time']:.0f}s)")
            
            # ===== LLM + 规则引擎整定 =====
            llm_stable = None
            sim_llm = None
            pid_llm = None
            if llm_available:
                print("   🤖 LLM + 规则引擎整定...")
                Config.OSCILLATION_TUNING['enable_llm'] = True
                loop_type = scenario.get('loop_type', 'flow')
                # 重要：必须传入 llm_client 才能真正使用 LLM
                selector_llm = ModelSelector(
                    verbose=False,
                    llm_client=llm_client,
                    process_context={'loop_type': loop_type, 'loop_name': scenario['name']}
                )
                result_llm = selector_llm.run(input_data)
                pid_llm = result_llm.get('pid_parameters', {})
                
                sim_llm = simulate_with_new_pid(process_changed, pid_llm, sv, duration=sim_duration, seed=sim_seed+1)  # +1 区分LLM
                llm_stable = sim_llm['is_stable']
                if llm_stable:
                    llm_stable_count += 1
                print(f"      稳态: {'✅ 是' if llm_stable else '❌ 否'} (Ts={sim_llm['settling_time']:.0f}s)")
            
            results.append({
                'scenario': scenario['name'],
                'loop_type': scenario.get('loop_type', 'unknown'),
                'rule_stable': rule_stable,
                'rule_ts': sim_rule['settling_time'],
                'rule_overshoot': sim_rule.get('overshoot', 0),
                'llm_stable': llm_stable,
                'llm_ts': sim_llm['settling_time'] if sim_llm else None,
                'llm_overshoot': sim_llm.get('overshoot', 0) if sim_llm else None,
            })
            
            # ===== 生成可视化图表 =====
            print("   📊 生成可视化图表...")
            
            # 仿真老PID参数（在变化后的系统上）
            pid_old = scenario['original_pid']
            sim_old = simulate_with_new_pid(process_changed, pid_old, sv, duration=300)
            
            # 如果没有LLM结果，用规则引擎结果替代
            if sim_llm is None:
                sim_llm = sim_rule
                pid_llm = pid_rule
            
            # 确定获胜者
            rule_better = sim_rule['settling_time'] < sim_llm['settling_time'] if sim_llm else True
            if rule_stable and (not llm_stable if llm_stable is not None else False):
                winner = 'Rule'
            elif llm_stable and not rule_stable:
                winner = 'LLM'
            elif rule_stable and llm_stable:
                winner = 'Rule' if rule_better else 'LLM'
            else:
                winner = 'Both Failed'
            
            comparison_result = {
                'winner': winner,
                'rule_stable': rule_stable,
                'llm_stable': llm_stable,
                'rule_ts': sim_rule['settling_time'],
                'llm_ts': sim_llm['settling_time'],
            }
            
            # 获取整定方法
            tuning_method = result_rule.get('fusion_info', {}).get('method', 'unknown')
            
            # 调用可视化函数
            visualize_scenario_comparison(
                scenario=scenario,
                metadata=metadata,
                data=data,
                sim_old=sim_old,
                sim_rule=sim_rule,
                sim_llm=sim_llm,
                pid_rule=pid_rule,
                pid_llm=pid_llm,
                result=comparison_result,
                scenario_idx=idx,
                tuning_method=tuning_method
            )
            print(f"   ✅ 图表已保存")
            
        except Exception as e:
            print(f"   ❌ 错误: {e}")
            import traceback
            traceback.print_exc()
            results.append({
                'scenario': scenario['name'],
                'error': str(e),
            })
    
    # 打印汇总报告
    valid_results = [r for r in results if 'error' not in r]
    total = len(valid_results)
    
    if total == 0:
        print("\n❌ 没有有效结果")
        return results
    
    # 计算 LLM 价值指标
    llm_wins = 0
    rule_wins = 0
    ties = 0
    both_stable = 0
    llm_only_stable = 0
    rule_only_stable = 0
    both_failed = 0
    
    for r in valid_results:
        rule_s = r.get('rule_stable', False)
        llm_s = r.get('llm_stable', False)
        rule_ts = r.get('rule_ts', 9999)
        llm_ts = r.get('llm_ts', 9999)
        
        if rule_s and llm_s:
            both_stable += 1
            if llm_ts < rule_ts * 0.95:
                llm_wins += 1
            elif rule_ts < llm_ts * 0.95:
                rule_wins += 1
            else:
                ties += 1
        elif llm_s and not rule_s:
            llm_only_stable += 1
            llm_wins += 1
        elif rule_s and not llm_s:
            rule_only_stable += 1
            rule_wins += 1
        else:
            both_failed += 1
            ties += 1
    
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + "振荡场景稳态验证 + LLM价值分析报告".center(66) + "║")
    print("╠" + "═" * 78 + "╣")
    print(f"║  场景总数: {total:<65}║")
    print("╠" + "═" * 78 + "╣")
    print("║  【稳态达成率】" + " " * 62 + "║")
    print(f"║    规则引擎:     {rule_stable_count}/{total} ({rule_stable_count/total*100:.1f}%)" + " " * 49 + "║")
    if llm_available:
        print(f"║    LLM+规则引擎: {llm_stable_count}/{total} ({llm_stable_count/total*100:.1f}%)" + " " * 47 + "║")
    print("╠" + "═" * 78 + "╣")
    if llm_available:
        print("║  【LLM价值分析】" + " " * 61 + "║")
        print(f"║    双方均稳态:   {both_stable}场 → LLM调节更快: {llm_wins}场, 规则更快: {rule_wins}场, 平局: {ties}场" + " " * 10 + "║")
        print(f"║    仅LLM稳态:    {llm_only_stable}场" + " " * 59 + "║")
        print(f"║    仅规则稳态:   {rule_only_stable}场" + " " * 59 + "║")
        print(f"║    双方均失败:   {both_failed}场" + " " * 59 + "║")
        llm_win_rate = llm_wins / total * 100 if total > 0 else 0
        print(f"║    LLM综合胜率:  {llm_win_rate:.1f}%" + " " * 59 + "║")
    print("╚" + "═" * 78 + "╝")
    
    # 按回路类型统计
    print("\n【按回路类型统计】")
    print(f"{'回路类型':<15} {'规则稳态':<12} {'LLM稳态':<12} {'LLM胜场':<10}")
    print("-" * 50)
    loop_types = set(r.get('loop_type', 'unknown') for r in valid_results)
    for lt in sorted(loop_types):
        lt_results = [r for r in valid_results if r.get('loop_type') == lt]
        lt_rule_stable = sum(1 for r in lt_results if r.get('rule_stable'))
        lt_llm_stable = sum(1 for r in lt_results if r.get('llm_stable'))
        lt_llm_wins = sum(1 for r in lt_results 
                         if r.get('llm_stable') and r.get('llm_ts', 9999) < r.get('rule_ts', 9999) * 0.95)
        print(f"{lt:<15} {lt_rule_stable}/{len(lt_results):<10} {lt_llm_stable}/{len(lt_results):<10} {lt_llm_wins}/{len(lt_results)}")
    
    print("\n✅ 稳态验证测试完成!")
    return results



# ============================================================
def run_amplitude_threshold_test():
    """目标3: 振荡幅度阈值估计
    
    固定振荡场景，测试不同幅度，找出能回稳态/不能回稳态的边界
    """
    print("=" * 80)
    print("目标3: 振荡幅度阈值估计")
    print("固定振荡场景，测试不同幅度，找出能回稳态/不能回稳态的边界")
    print("=" * 80)
    
    # 选取代表性场景进行细粒度测试
    representative_scenarios = [
        s for s in TEST_SCENARIOS 
        if s['name'] in ['Severe Gain Increase', 'Large Delay Increase', 
                         'Temperature Loop Oscillation', 'Pressure Loop Oscillation',
                         'Moderate Oscillation']
    ]
    
    if not representative_scenarios:
        representative_scenarios = TEST_SCENARIOS[:5]
    
    # 细粒度幅度因子
    amplitude_factors = [0.3, 0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.5, 1.8, 2.0, 2.5]
    
    print(f"\n📊 代表性场景: {len(representative_scenarios)}")
    print(f"📊 幅度因子范围: {amplitude_factors}")
    
    threshold_results = []
    
    for scenario in representative_scenarios:
        print(f"\n{'='*70}")
        print(f"场景: {scenario['name']}")
        print("=" * 70)
        
        stable_factors = []
        unstable_factors = []
        
        for factor in amplitude_factors:
            # 根据幅度因子生成变化后的参数
            orig = scenario['process_original']
            changed = scenario['process_changed']
            
            delta_K = changed['K'] - orig['K']
            delta_T1 = changed['T1'] - orig['T1']
            delta_L = changed['L'] - orig['L']
            
            new_changed = {
                'K': max(0.1, orig['K'] + delta_K * factor),
                'T1': max(5.0, orig['T1'] + delta_T1 * factor),
                'L': max(0.5, orig['L'] + delta_L * factor),
            }
            
            # 创建变体场景
            variant_scenario = scenario.copy()
            variant_scenario['process_changed'] = new_changed
            
            try:
                data, metadata = generate_scenario_data(variant_scenario)
                change_time = metadata['change_time']
                end_time = data[-1]['timestamp']
                qualified_windows = [{'start_time': change_time, 'end_time': end_time}]
                
                input_data = {
                    'history_data': data,
                    'params': {},
                    'qualified_windows': qualified_windows,
                }
                
                # 整定
                Config.OSCILLATION_TUNING['enable_llm'] = False
                selector = ModelSelector(verbose=False)
                result = selector.run(input_data)
                pid_new = result.get('pid_parameters', {})
                
                # 仿真
                sim = simulate_with_new_pid(new_changed, pid_new, metadata['sv'], duration=400)
                is_stable = sim['is_stable']
                
                if is_stable:
                    stable_factors.append(factor)
                    status = "✅"
                else:
                    unstable_factors.append(factor)
                    status = "❌"
                
                print(f"   幅度×{factor}: {status} (Ts={sim['settling_time']:.0f}s)")
                
            except Exception as e:
                print(f"   幅度×{factor}: ⚠️ 错误 - {e}")
                unstable_factors.append(factor)
        
        # 估计阈值
        max_stable = max(stable_factors) if stable_factors else 0
        min_unstable = min(unstable_factors) if unstable_factors else float('inf')
        threshold = (max_stable + min_unstable) / 2 if stable_factors and unstable_factors else None
        
        threshold_results.append({
            'scenario': scenario['name'],
            'max_stable': max_stable,
            'min_unstable': min_unstable if min_unstable != float('inf') else None,
            'threshold': threshold,
            'stable_factors': stable_factors,
            'unstable_factors': unstable_factors,
        })
    
    # 打印汇总报告
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + "振荡幅度阈值估计报告".center(70) + "║")
    print("╠" + "═" * 32 + "╦" + "═" * 14 + "╦" + "═" * 14 + "╦" + "═" * 14 + "╣")
    print("║ 场景                           ║ 可恢复幅度   ║ 不可恢复幅度 ║ 估计阈值     ║")
    print("╠" + "═" * 32 + "╬" + "═" * 14 + "╬" + "═" * 14 + "╬" + "═" * 14 + "╣")
    
    for r in threshold_results:
        name = r['scenario'][:30]
        max_s = f"≤{r['max_stable']}" if r['max_stable'] else "N/A"
        min_u = f"≥{r['min_unstable']}" if r['min_unstable'] else "N/A"
        thresh = f"~{r['threshold']:.2f}" if r['threshold'] else "N/A"
        print(f"║ {name:<30} ║ {max_s:>12} ║ {min_u:>12} ║ {thresh:>12} ║")
    
    print("╚" + "═" * 32 + "╩" + "═" * 14 + "╩" + "═" * 14 + "╩" + "═" * 14 + "╝")
    
    print("\n✅ 振荡幅度阈值估计测试完成!")
    return threshold_results


# ============================================================
# 目标4: Lambda 整定验证 (run_lambda_tuning_test)
# ============================================================
def run_lambda_tuning_test():
    """目标4: Lambda 整定验证
    
    常规扰动下用模型辨识+Lambda整定在不同生产场景下验证能否回稳态
    """
    print("=" * 80)
    print("目标4: Lambda 整定验证")
    print("常规扰动下用模型辨识+Lambda整定在不同生产场景下验证能否回稳态")
    print("=" * 80)
    
    scenarios = MODEL_ID_SCENARIOS
    print(f"\n📊 测试场景总数: {len(scenarios)}")
    
    results = []
    stable_count = 0
    
    # 按回路类型统计
    by_loop_type = {}
    
    for i, scenario in enumerate(scenarios, 1):
        print(f"\n{'─'*70}")
        print(f"场景 {i}/{len(scenarios)}: {scenario['name']}")
        print(f"描述: {scenario['description']}")
        print(f"过程: K={scenario['process']['K']}, T1={scenario['process']['T1']}, L={scenario['process']['L']}")
        print("─" * 70)
        
        try:
            # 生成阶跃响应数据
            data, metadata = generate_step_response_scenario_data(scenario)
            
            change_time = metadata['change_time']
            start_time = data[0]['timestamp']
            end_time = data[-1]['timestamp']
            
            window_start_idx = 50
            window_start_time = data[window_start_idx]['timestamp']
            qualified_windows = [{'start_time': window_start_time, 'end_time': end_time}]
            
            # 运行整定
            Config.OSCILLATION_TUNING['enable_llm'] = False
            selector = ModelSelector(verbose=False)
            result = selector.run({
                'history_data': data,
                'params': {},
                'qualified_windows': qualified_windows,
            })
            
            pid_new = result.get('pid_parameters', {})
            model_params = result.get('model_parameters', {})
            fusion_info = result.get('fusion_info', {})
            tuning_method = fusion_info.get('method', 'unknown')
            
            # 模型辨识精度
            true_K = scenario['process']['K']
            true_T1 = scenario['process']['T1']
            true_L = scenario['process']['L']
            
            id_K = model_params.get('K', 0)
            id_T1 = model_params.get('T1', 0)
            id_L = model_params.get('L', model_params.get('delay', 0))
            
            K_error = abs(id_K - true_K) / true_K * 100 if true_K != 0 else 0
            T1_error = abs(id_T1 - true_T1) / true_T1 * 100 if true_T1 != 0 else 0
            L_error = abs(id_L - true_L) / true_L * 100 if true_L != 0 else 0
            
            print(f"   整定方法: {tuning_method}")
            print(f"   模型辨识: K误差={K_error:.1f}%, T1误差={T1_error:.1f}%, L误差={L_error:.1f}%")
            
            # 仿真验证
            sim = simulate_with_new_pid(scenario['process'], pid_new, metadata['sv'], duration=400)
            is_stable = sim['is_stable']
            
            if is_stable:
                stable_count += 1
            
            print(f"   稳态验证: {'✅ 是' if is_stable else '❌ 否'} (Ts={sim['settling_time']:.0f}s)")
            
            # ===== 生成可视化图表 =====
            print("   📊 生成可视化图表...")
            fig, axes = plt.subplots(2, 1, figsize=(12, 8))
            
            # 上图：原始数据
            ax1 = axes[0]
            pv_data = [d['pv'] for d in data]
            mv_data = [d['mv'] for d in data]
            sv_data = [d['sv'] for d in data]
            time_data = np.arange(len(pv_data))
            
            ax1.plot(time_data, pv_data, 'b-', label='PV', alpha=0.8)
            ax1.plot(time_data, sv_data, 'g--', label='SV', alpha=0.8)
            ax1.set_ylabel('PV / SV')
            ax1.legend(loc='upper left')
            ax1.set_title(f'{scenario["name"]} - 原始阶跃响应数据')
            ax1.grid(True, alpha=0.3)
            
            ax1_mv = ax1.twinx()
            ax1_mv.plot(time_data, mv_data, 'r-', label='MV', alpha=0.5)
            ax1_mv.set_ylabel('MV', color='r')
            ax1_mv.legend(loc='upper right')
            
            # 下图：新 PID 仿真响应
            ax2 = axes[1]
            ax2.plot(sim['t'], sim['pv'], 'b-', label='PV (新PID)', linewidth=2)
            ax2.axhline(y=metadata['sv'], color='g', linestyle='--', label='SV', alpha=0.8)
            ax2.fill_between(sim['t'], 
                           metadata['sv'] * 0.95, metadata['sv'] * 1.05, 
                           alpha=0.2, color='green', label='±5%误差带')
            ax2.set_xlabel('Time (s)')
            ax2.set_ylabel('PV')
            status = '✅ 稳态' if is_stable else '❌ 未稳态'
            ax2.set_title(f'新PID仿真响应 - {status} (Ts={sim["settling_time"]:.0f}s)')
            ax2.legend()
            ax2.grid(True, alpha=0.3)
            
            # 添加信息文字
            info_text = f"PID: Kp={pid_new.get('Kp', 0):.4f}, Ki={pid_new.get('Ki', 0):.4f}, Kd={pid_new.get('Kd', 0):.4f}\n"
            info_text += f"模型: K={id_K:.3f}(误差{K_error:.1f}%), T1={id_T1:.1f}(误差{T1_error:.1f}%), L={id_L:.1f}(误差{L_error:.1f}%)\n"
            info_text += f"方法: {tuning_method}"
            ax2.text(0.02, 0.98, info_text, transform=ax2.transAxes, fontsize=9,
                    verticalalignment='top', fontfamily='monospace',
                    bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
            
            plt.tight_layout()
            
            # 保存图片到 lambda 子目录
            lambda_dir = os.path.join(CONFIG['output_dir'], 'lambda')
            os.makedirs(lambda_dir, exist_ok=True)
            safe_name = scenario['name'].replace(' ', '_').replace('/', '_')
            filename = f'lambda_{i:02d}_{safe_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png'
            filepath = os.path.join(lambda_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            print(f"   ✅ 图表已保存: {filepath}")
            plt.close()
            
            # 按回路类型统计
            loop_type = scenario.get('loop_type', 'unknown')
            if loop_type not in by_loop_type:
                by_loop_type[loop_type] = {'total': 0, 'stable': 0}
            by_loop_type[loop_type]['total'] += 1
            if is_stable:
                by_loop_type[loop_type]['stable'] += 1
            
            results.append({
                'scenario': scenario['name'],
                'loop_type': loop_type,
                'tuning_method': tuning_method,
                'K_error': K_error,
                'T1_error': T1_error,
                'L_error': L_error,
                'is_stable': is_stable,
                'settling_time': sim['settling_time'],
            })
            
        except Exception as e:
            print(f"   ❌ 错误: {e}")
            results.append({'scenario': scenario['name'], 'error': str(e)})
    
    # 计算统计
    valid_results = [r for r in results if 'error' not in r]
    total = len(valid_results)
    
    if total > 0:
        avg_K_err = np.mean([r['K_error'] for r in valid_results])
        avg_T1_err = np.mean([r['T1_error'] for r in valid_results])
        avg_L_err = np.mean([r['L_error'] for r in valid_results])
    
    # 打印汇总报告
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + "Lambda 整定验证报告".center(70) + "║")
    print("╠" + "═" * 78 + "╣")
    if total > 0:
        print(f"║ 模型辨识精度:                                                            ║")
        print(f"║   K 平均误差:  {avg_K_err:>6.1f}%                                                    ║")
        print(f"║   T1 平均误差: {avg_T1_err:>6.1f}%                                                    ║")
        print(f"║   L 平均误差:  {avg_L_err:>6.1f}%                                                    ║")
        print("╠" + "═" * 78 + "╣")
        print(f"║ 稳态达成率 (按回路类型):                                                  ║")
        for lt, stats in sorted(by_loop_type.items()):
            rate = stats['stable'] / stats['total'] * 100 if stats['total'] > 0 else 0
            print(f"║   {lt:<12}: {stats['stable']}/{stats['total']} ({rate:.0f}%)                                               ║")
        print(f"║   总体:        {stable_count}/{total} ({stable_count/total*100:.0f}%)                                               ║")
    print("╚" + "═" * 78 + "╝")
    
    print("\n✅ Lambda 整定验证测试完成!")
    return results


# ============================================================
# 运行所有测试
# ============================================================
def run_all_tests():
    """运行所有四个验证目标的测试并生成汇总报告"""
    print("=" * 80)
    print("运行所有验证目标测试")
    print("=" * 80)
    
    all_results = {}
    
    print("\n" + "▶" * 40)
    print("开始目标1: 振荡场景稳态验证")
    print("▶" * 40)
    all_results['stability'] = run_stability_test()
    
    print("\n" + "▶" * 40)
    print("开始目标2: LLM 优化效果对比")
    print("▶" * 40)
    all_results['llm_compare'] = run_llm_comparison_test()
    
    print("\n" + "▶" * 40)
    print("开始目标3: 振荡幅度阈值估计")
    print("▶" * 40)
    all_results['amplitude'] = run_amplitude_threshold_test()
    
    print("\n" + "▶" * 40)
    print("开始目标4: Lambda 整定验证")
    print("▶" * 40)
    all_results['lambda'] = run_lambda_tuning_test()
    
    # 汇总报告
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + "全部测试完成 - 汇总报告".center(70) + "║")
    print("╠" + "═" * 78 + "╣")
    print("║ 目标1 (振荡稳态验证): 完成                                              ║")
    print("║ 目标2 (LLM优化效果): 完成                                               ║")
    print("║ 目标3 (幅度阈值估计): 完成                                              ║")
    print("║ 目标4 (Lambda整定): 完成                                                ║")
    print("╚" + "═" * 78 + "╝")
    
    return all_results


if __name__ == "__main__":
    import sys
    
    # 优先使用文件内的 TEST_MODE 变量
    # 如果命令行有参数，则命令行参数优先
    mode = 'stability'
    if len(sys.argv) > 1:
        mode = sys.argv[1]
    
    # 新的三个验证目标 (llm_compare 已合并到 stability)
    if mode == 'stability':
        run_stability_test()
    elif mode == 'amplitude':
        run_amplitude_threshold_test()
    elif mode == 'lambda':
        run_lambda_tuning_test()
    elif mode == 'all':
        run_all_tests()
    # 向后兼容旧模式
    elif mode == 'batch':
        run_batch_test()
    elif mode == 'model_id':
        run_model_id_test()
    else:
        # default 模式
        main()
