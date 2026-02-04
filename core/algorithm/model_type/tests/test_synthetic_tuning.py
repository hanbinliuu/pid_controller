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
from core.algorithm.model_type.tests.test_scenarios import TEST_SCENARIOS, REALISTIC_SCENARIOS


# ============================================================
# 场景难度计算
# ============================================================
def calculate_scenario_difficulty(scenario: Dict) -> Tuple[float, str, List[str]]:
    """
    计算场景难度评分
    
    Returns:
        (score, level, reasons)
        - score: 难度分数 (1-10)
        - level: 难度等级 (EASY/MEDIUM/HARD/EXTREME)
        - reasons: 难度原因列表
    """
    score = 1.0
    reasons = []
    
    po = scenario['process_original']
    pc = scenario['process_changed']
    
    # 1. 滞后特性 (Delay Characteristics)
    delay_ratio_changed = pc['L'] / pc['T1'] if pc['T1'] > 0 else 0
    
    if delay_ratio_changed > 2.0:
        score += 3.0
        reasons.append(f"极大滞后(L/T={delay_ratio_changed:.1f})")
    elif delay_ratio_changed > 1.0:
        score += 2.0
        reasons.append(f"大滞后(L/T={delay_ratio_changed:.1f})")
    elif delay_ratio_changed > 0.5:
        score += 1.0
        reasons.append(f"中等滞后")
        
    # 2. 增益变化 (Gain Change)
    if po['K'] != 0:
        gain_ratio = abs(pc['K'] / po['K'])
        if gain_ratio > 10.0:
            score += 3.0
            reasons.append(f"增益剧变(x{gain_ratio:.0f})")
        elif gain_ratio > 5.0:
            score += 2.0
            reasons.append(f"增益大变(x{gain_ratio:.0f})")
        elif gain_ratio > 2.0:
            score += 1.0
            reasons.append(f"增益变化")
            
    # 3. 噪声水平 (Noise Level)
    noise = scenario.get('noise_std', 0.2)
    if noise >= 1.5:
        score += 3.0
        reasons.append(f"极高噪声")
    elif noise >= 0.8:
        score += 2.0
        reasons.append(f"高噪声")
    elif noise >= 0.4:
        score += 1.0
        reasons.append(f"中噪声")
        
    # 4. 特殊过程特性 (Special Characteristics)
    if pc['K'] < 0:
        if po['K'] > 0:
            score += 4.0
            reasons.append("反向突变")
        else:
            score += 1.0
            reasons.append("反向系统")
            
    if pc['T1'] > 100:
        score += 2.0
        reasons.append(f"积分/慢系统")
        
    if pc['T1'] < 5:
        score += 1.0
        reasons.append(f"快系统")
    
    # 确定难度等级
    if score >= 7:
        level = "EXTREME"
    elif score >= 5:
        level = "HARD"
    elif score >= 3:
        level = "MEDIUM"
    else:
        level = "EASY"
    
    return score, level, reasons




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
    'ollama_model': 'qwen:7b',
    'ollama_base_url': 'http://localhost:11434',
    'skip_llm_test': True,  # 设为 True 可跳过 LLM 测试，只运行规则引擎
    
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
    """一阶加纯滞后过程模型
    
    支持阀门非线性特性:
    - deadband: 死区 (MV小幅变化不响应)
    - stiction: 粘滞 (MV反向时需克服阻力)
    - mv_min/mv_max: MV饱和限制
    """
    
    def __init__(self, K: float, T1: float, L: float, dt: float = 1.0,
                 deadband: float = 0.0, stiction: float = 0.0,
                 mv_min: float = 0.0, mv_max: float = 100.0):
        self.K = K
        self.T1 = T1
        self.L = L
        self.dt = dt
        self.delay_steps = max(1, int(L / dt))
        self.mv_buffer = []
        self.pv = 0.0
        
        # 阀门非线性参数
        self.deadband = deadband  # 死区百分比
        self.stiction = stiction  # 粘滞百分比
        self.mv_min = mv_min      # MV下限
        self.mv_max = mv_max      # MV上限
        
        # 阀门状态
        self.last_mv_actual = 0.0  # 上次实际阀门位置
        self.last_mv_direction = 0  # 上次移动方向 (-1, 0, 1)
        self.stuck = False         # 是否粘住
    
    def reset(self, pv_initial: float = 0.0):
        self.pv = pv_initial
        self.mv_buffer = [pv_initial / self.K if self.K != 0 else 0] * self.delay_steps
        self.last_mv_actual = pv_initial / self.K if self.K != 0 else 0
        self.last_mv_direction = 0
        self.stuck = False
    
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
    
    def set_valve_params(self, deadband: float = 0.0, stiction: float = 0.0,
                         mv_min: float = 0.0, mv_max: float = 100.0):
        """设置阀门非线性参数"""
        self.deadband = deadband
        self.stiction = stiction
        self.mv_min = mv_min
        self.mv_max = mv_max
    
    def _apply_valve_nonlinearity(self, mv_command: float) -> float:
        """应用阀门非线性特性，返回实际阀门位置"""
        # 1. 应用饱和限制
        mv_saturated = max(self.mv_min, min(self.mv_max, mv_command))
        
        # 2. 计算移动量和方向
        mv_change = mv_saturated - self.last_mv_actual
        direction = 1 if mv_change > 0 else (-1 if mv_change < 0 else 0)
        
        # 3. 应用粘滞 (反向时需要克服粘滞力)
        if self.stiction > 0 and direction != 0:
            direction_changed = (direction != self.last_mv_direction and self.last_mv_direction != 0)
            if direction_changed:
                # 反向，需要克服粘滞
                if abs(mv_change) < self.stiction:
                    # 变化量小于粘滞力，阀门不动
                    self.stuck = True
                    return self.last_mv_actual
                else:
                    # 克服了粘滞，但实际移动量减少
                    self.stuck = False
                    mv_actual = self.last_mv_actual + (mv_change - direction * self.stiction)
            else:
                # 同方向，正常移动
                self.stuck = False
                mv_actual = mv_saturated
        else:
            mv_actual = mv_saturated
        
        # 4. 应用死区 (小幅变化不响应)
        if self.deadband > 0:
            if abs(mv_actual - self.last_mv_actual) < self.deadband:
                # 变化量在死区内，阀门不动
                return self.last_mv_actual
        
        # 5. 更新状态
        self.last_mv_direction = direction if direction != 0 else self.last_mv_direction
        self.last_mv_actual = mv_actual
        
        return mv_actual
    
    def step(self, mv: float) -> float:
        # 应用阀门非线性
        mv_actual = self._apply_valve_nonlinearity(mv)
        
        # 延迟缓冲
        self.mv_buffer.append(mv_actual)
        mv_delayed = self.mv_buffer.pop(0)
        
        # FOPDT 响应
        alpha = self.dt / (self.T1 + self.dt)
        pv_ss = self.K * mv_delayed
        self.pv = self.pv + alpha * (pv_ss - self.pv)
        return self.pv


class IntegratingProcess:
    """积分过程模型 - 适用于液位控制
    
    液位回路特点：
    - PV 是 MV 的积分：dPV/dt = K * MV
    - 没有自稳定趋势，需要控制器维持平衡
    """
    
    def __init__(self, K: float, L: float, dt: float = 1.0,
                 deadband: float = 0.0, stiction: float = 0.0,
                 mv_min: float = 0.0, mv_max: float = 100.0):
        self.K = K  # 积分增益 (单位变化率 / %MV)
        self.L = L
        self.dt = dt
        self.delay_steps = max(1, int(L / dt))
        self.mv_buffer = []
        self.pv = 0.0
        
        # 复用 FOPDT 的阀门非线性
        self.deadband = deadband
        self.stiction = stiction
        self.mv_min = mv_min
        self.mv_max = mv_max
        self.last_mv_actual = 0.0
        self.last_mv_direction = 0
        self.stuck = False
        
        # 平衡点 MV (使 dPV/dt = 0)
        self.mv_balance = 50.0  # 假设 50% 时流入=流出
    
    def reset(self, pv_initial: float = 0.0, mv_balance: float = 50.0):
        self.pv = pv_initial
        self.mv_balance = mv_balance
        self.mv_buffer = [mv_balance] * self.delay_steps
        self.last_mv_actual = mv_balance
        self.last_mv_direction = 0
        self.stuck = False
    
    def _apply_valve_nonlinearity(self, mv_command: float) -> float:
        """复用 FOPDT 的阀门非线性逻辑"""
        mv_saturated = max(self.mv_min, min(self.mv_max, mv_command))
        mv_change = mv_saturated - self.last_mv_actual
        direction = 1 if mv_change > 0 else (-1 if mv_change < 0 else 0)
        
        if self.stiction > 0 and direction != 0:
            direction_changed = (direction != self.last_mv_direction and self.last_mv_direction != 0)
            if direction_changed and abs(mv_change) < self.stiction:
                self.stuck = True
                return self.last_mv_actual
            self.stuck = False
        
        if self.deadband > 0 and abs(mv_change) < self.deadband:
            return self.last_mv_actual
        
        self.last_mv_direction = direction if direction != 0 else self.last_mv_direction
        self.last_mv_actual = mv_saturated
        return mv_saturated
    
    def step(self, mv: float) -> float:
        mv_actual = self._apply_valve_nonlinearity(mv)
        
        self.mv_buffer.append(mv_actual)
        mv_delayed = self.mv_buffer.pop(0)
        
        # 积分响应：dPV/dt = K * (MV - MV_balance)
        # MV > balance: 液位上升; MV < balance: 液位下降
        dpv = self.K * (mv_delayed - self.mv_balance) * self.dt
        self.pv = self.pv + dpv
        return self.pv


class SOPDTProcess:
    """二阶加纯滞后过程模型 - 适用于欠阻尼温度回路
    
    特点：
    - 二阶响应可以产生振荡
    - 阻尼比 zeta < 1 时为欠阻尼，会有超调
    """
    
    def __init__(self, K: float, T1: float, T2: float, L: float, 
                 zeta: float = 0.5, dt: float = 1.0,
                 deadband: float = 0.0, stiction: float = 0.0,
                 mv_min: float = 0.0, mv_max: float = 100.0):
        self.K = K
        self.T1 = T1  # 主时间常数
        self.T2 = T2  # 二阶时间常数
        self.L = L
        self.zeta = zeta  # 阻尼比
        self.dt = dt
        self.delay_steps = max(1, int(L / dt))
        self.mv_buffer = []
        
        # 状态变量 (二阶系统需要两个状态)
        self.pv = 0.0
        self.dpv = 0.0  # PV 的导数
        
        # 阀门非线性
        self.deadband = deadband
        self.stiction = stiction
        self.mv_min = mv_min
        self.mv_max = mv_max
        self.last_mv_actual = 0.0
        self.last_mv_direction = 0
    
    def reset(self, pv_initial: float = 0.0):
        self.pv = pv_initial
        self.dpv = 0.0
        self.mv_buffer = [pv_initial / self.K if self.K != 0 else 0] * self.delay_steps
        self.last_mv_actual = pv_initial / self.K if self.K != 0 else 0
        self.last_mv_direction = 0
    
    def _apply_valve_nonlinearity(self, mv_command: float) -> float:
        mv_saturated = max(self.mv_min, min(self.mv_max, mv_command))
        mv_change = mv_saturated - self.last_mv_actual
        direction = 1 if mv_change > 0 else (-1 if mv_change < 0 else 0)
        
        if self.stiction > 0 and direction != 0:
            if direction != self.last_mv_direction and self.last_mv_direction != 0:
                if abs(mv_change) < self.stiction:
                    return self.last_mv_actual
        
        if self.deadband > 0 and abs(mv_change) < self.deadband:
            return self.last_mv_actual
        
        self.last_mv_direction = direction if direction != 0 else self.last_mv_direction
        self.last_mv_actual = mv_saturated
        return mv_saturated
    
    def step(self, mv: float) -> float:
        mv_actual = self._apply_valve_nonlinearity(mv)
        
        self.mv_buffer.append(mv_actual)
        mv_delayed = self.mv_buffer.pop(0)
        
        # 二阶系统状态空间方程
        # T1*T2 * d²pv/dt² + (T1+T2)*dpv/dt + pv = K*u
        # 转换为状态空间形式用欧拉法积分
        pv_ss = self.K * mv_delayed
        
        omega_n = 1.0 / np.sqrt(self.T1 * max(self.T2, 0.1))  # 自然频率
        
        # 二阶系统微分方程
        d2pv = omega_n**2 * (pv_ss - self.pv) - 2 * self.zeta * omega_n * self.dpv
        
        # 欧拉积分
        self.dpv = self.dpv + d2pv * self.dt
        self.pv = self.pv + self.dpv * self.dt
        
        return self.pv


class InverseResponseProcess:
    """反向响应过程模型 - 适用于锅炉汽包水位
    
    特点：
    - MV 增加时，PV 先下降后上升（或相反）
    - 物理原因：锅炉加水时，冷水进入导致汽泡破裂，水位先降后升
    """
    
    def __init__(self, K: float, T1: float, L: float,
                 K_inv: float = 0.3, T_inv: float = 5.0, dt: float = 1.0,
                 deadband: float = 0.0, stiction: float = 0.0,
                 mv_min: float = 0.0, mv_max: float = 100.0):
        self.K = K  # 主增益（最终稳态）
        self.T1 = T1
        self.L = L
        self.K_inv = K_inv  # 反向增益（初始反向幅度）
        self.T_inv = T_inv  # 反向时间常数
        self.dt = dt
        self.delay_steps = max(1, int(L / dt))
        self.mv_buffer = []
        
        # 两个并联的一阶系统
        self.pv_main = 0.0  # 主响应
        self.pv_inv = 0.0   # 反向响应
        
        # 阀门非线性
        self.deadband = deadband
        self.stiction = stiction
        self.mv_min = mv_min
        self.mv_max = mv_max
        self.last_mv_actual = 0.0
        self.last_mv_direction = 0
    
    def reset(self, pv_initial: float = 0.0):
        self.pv_main = pv_initial
        self.pv_inv = 0.0
        mv_init = pv_initial / self.K if self.K != 0 else 0
        self.mv_buffer = [mv_init] * self.delay_steps
        self.last_mv_actual = mv_init
        self.last_mv_direction = 0
    
    def _apply_valve_nonlinearity(self, mv_command: float) -> float:
        mv_saturated = max(self.mv_min, min(self.mv_max, mv_command))
        mv_change = mv_saturated - self.last_mv_actual
        direction = 1 if mv_change > 0 else (-1 if mv_change < 0 else 0)
        
        if self.stiction > 0 and direction != 0:
            if direction != self.last_mv_direction and self.last_mv_direction != 0:
                if abs(mv_change) < self.stiction:
                    return self.last_mv_actual
        
        if self.deadband > 0 and abs(mv_change) < self.deadband:
            return self.last_mv_actual
        
        self.last_mv_direction = direction if direction != 0 else self.last_mv_direction
        self.last_mv_actual = mv_saturated
        return mv_saturated
    
    @property
    def pv(self):
        return self.pv_main - self.pv_inv
    
    def step(self, mv: float) -> float:
        mv_actual = self._apply_valve_nonlinearity(mv)
        
        self.mv_buffer.append(mv_actual)
        mv_delayed = self.mv_buffer.pop(0)
        
        # 主响应 (慢)
        alpha_main = self.dt / (self.T1 + self.dt)
        pv_ss_main = self.K * mv_delayed
        self.pv_main = self.pv_main + alpha_main * (pv_ss_main - self.pv_main)
        
        # 反向响应 (快，负增益效果)
        alpha_inv = self.dt / (self.T_inv + self.dt)
        pv_ss_inv = self.K_inv * mv_delayed
        self.pv_inv = self.pv_inv + alpha_inv * (pv_ss_inv - self.pv_inv)
        
        return self.pv_main - self.pv_inv


class AdvancedFOPDTProcess(FOPDTProcess):
    """增强的 FOPDT 过程模型
    
    新增特性：
    - measurement_lag: 测量滞后（热电偶套管延迟）
    - stick_slip: 间歇粘滞跳动
    - valve_curve: 阀门特性曲线 (linear/equal_pct/quick_open)
    - time_varying_delay: 时变滞后
    """
    
    def __init__(self, K: float, T1: float, L: float, dt: float = 1.0,
                 deadband: float = 0.0, stiction: float = 0.0,
                 mv_min: float = 0.0, mv_max: float = 100.0,
                 measurement_lag: float = 0.0,
                 stick_slip_period: int = 0,
                 valve_curve: str = 'linear',
                 delay_variation: float = 0.0):
        super().__init__(K, T1, L, dt, deadband, stiction, mv_min, mv_max)
        
        # 测量滞后 (一阶滤波器)
        self.measurement_lag = measurement_lag
        self.pv_measured = 0.0
        
        # 间歇粘滞跳动
        self.stick_slip_period = stick_slip_period  # 多少步后强制跳动
        self.stick_slip_counter = 0
        self.stick_slip_accumulated = 0.0
        
        # 阀门特性曲线
        self.valve_curve = valve_curve  # 'linear', 'equal_pct', 'quick_open'
        
        # 时变滞后
        self.delay_variation = delay_variation  # 滞后变化幅度 (±%)
        self.base_delay_steps = self.delay_steps
    
    def reset(self, pv_initial: float = 0.0):
        super().reset(pv_initial)
        self.pv_measured = pv_initial
        self.stick_slip_counter = 0
        self.stick_slip_accumulated = 0.0
    
    def _apply_valve_curve(self, mv: float) -> float:
        """应用阀门特性曲线"""
        # 归一化到 0-1
        mv_norm = (mv - self.mv_min) / (self.mv_max - self.mv_min + 1e-6)
        mv_norm = max(0, min(1, mv_norm))
        
        if self.valve_curve == 'equal_pct':
            # 等百分比特性: flow = R^(x-1), R 通常为 50
            R = 50.0
            if mv_norm > 0:
                flow_norm = R ** (mv_norm - 1)
            else:
                flow_norm = 0
        elif self.valve_curve == 'quick_open':
            # 快开特性: flow = sqrt(x)
            flow_norm = np.sqrt(mv_norm)
        else:
            # 线性特性
            flow_norm = mv_norm
        
        # 转换回 MV 范围
        return self.mv_min + flow_norm * (self.mv_max - self.mv_min)
    
    def _apply_stick_slip(self, mv_actual: float) -> float:
        """应用间歇粘滞跳动"""
        if self.stick_slip_period <= 0:
            return mv_actual
        
        if self.stuck:
            # 累积被阻止的变化量
            self.stick_slip_accumulated += mv_actual - self.last_mv_actual
            self.stick_slip_counter += 1
            
            # 周期性强制释放
            if self.stick_slip_counter >= self.stick_slip_period:
                self.stick_slip_counter = 0
                # 突然跳动：释放累积量
                mv_jump = self.last_mv_actual + self.stick_slip_accumulated
                self.stick_slip_accumulated = 0.0
                self.stuck = False
                return mv_jump
        else:
            self.stick_slip_counter = 0
            self.stick_slip_accumulated = 0.0
        
        return mv_actual
    
    def _update_time_varying_delay(self, mv: float):
        """更新时变滞后"""
        if self.delay_variation > 0:
            # 滞后随 MV 变化（负荷相关）
            variation = 1 + self.delay_variation * (mv - 50) / 50
            variation = max(0.5, min(2.0, variation))
            new_delay = int(self.base_delay_steps * variation)
            
            if new_delay != self.delay_steps:
                if new_delay > len(self.mv_buffer):
                    self.mv_buffer = [self.mv_buffer[-1] if self.mv_buffer else mv] * (new_delay - len(self.mv_buffer)) + self.mv_buffer
                elif new_delay < len(self.mv_buffer):
                    self.mv_buffer = self.mv_buffer[-new_delay:]
                self.delay_steps = new_delay
    
    def step(self, mv: float) -> float:
        # 1. 应用阀门特性曲线
        mv_curved = self._apply_valve_curve(mv)
        
        # 2. 应用基本阀门非线性
        mv_actual = self._apply_valve_nonlinearity(mv_curved)
        
        # 3. 应用间歇粘滞跳动
        mv_actual = self._apply_stick_slip(mv_actual)
        
        # 4. 更新时变滞后
        self._update_time_varying_delay(mv_actual)
        
        # 5. 延迟缓冲
        self.mv_buffer.append(mv_actual)
        mv_delayed = self.mv_buffer.pop(0)
        
        # 6. FOPDT 响应
        alpha = self.dt / (self.T1 + self.dt)
        pv_ss = self.K * mv_delayed
        self.pv = self.pv + alpha * (pv_ss - self.pv)
        
        # 7. 测量滞后（一阶滤波）
        if self.measurement_lag > 0:
            alpha_m = self.dt / (self.measurement_lag + self.dt)
            self.pv_measured = self.pv_measured + alpha_m * (self.pv - self.pv_measured)
            return self.pv_measured
        
        return self.pv


class RealisticEnvironment:
    """真实环境模拟器 - 添加各种工业现场噪声和扰动
    
    包含：
    - 随机负荷扰动
    - 周期性扰动（泵脉动等）
    - 有色噪声（比白噪声更真实）
    - 传感器漂移
    - 传感器故障/跳变
    - 阀门定位器动态
    - 气动延迟
    - 采样量化
    - 通信延迟
    """
    
    def __init__(self, dt: float = 1.0,
                 # 负荷扰动
                 load_disturbance_amplitude: float = 0.0,
                 load_disturbance_frequency: float = 0.01,  # Hz
                 # 周期性扰动
                 periodic_disturbance_amplitude: float = 0.0,
                 periodic_disturbance_period: float = 10.0,  # 秒
                 # 噪声特性
                 noise_std: float = 0.1,
                 colored_noise_tau: float = 0.0,  # 有色噪声时间常数
                 # 传感器
                 sensor_drift_rate: float = 0.0,  # 单位/小时
                 sensor_fault_probability: float = 0.0,
                 sensor_fault_magnitude: float = 5.0,
                 # 阀门定位器
                 positioner_time_constant: float = 0.0,
                 positioner_deadband: float = 0.0,
                 # 气动延迟
                 pneumatic_delay: float = 0.0,
                 # 数字效应
                 quantization_bits: int = 0,  # 0 表示无量化
                 communication_delay: float = 0.0):
        
        self.dt = dt
        self.step_count = 0
        
        # 负荷扰动
        self.load_disturbance_amplitude = load_disturbance_amplitude
        self.load_disturbance_frequency = load_disturbance_frequency
        self.load_disturbance_phase = np.random.uniform(0, 2 * np.pi)
        
        # 周期性扰动
        self.periodic_disturbance_amplitude = periodic_disturbance_amplitude
        self.periodic_disturbance_period = periodic_disturbance_period
        
        # 噪声
        self.noise_std = noise_std
        self.colored_noise_tau = colored_noise_tau
        self.colored_noise_state = 0.0
        
        # 传感器
        self.sensor_drift_rate = sensor_drift_rate
        self.sensor_drift_accumulated = 0.0
        self.sensor_fault_probability = sensor_fault_probability
        self.sensor_fault_magnitude = sensor_fault_magnitude
        self.sensor_fault_active = False
        self.sensor_fault_duration = 0
        
        # 阀门定位器
        self.positioner_time_constant = positioner_time_constant
        self.positioner_deadband = positioner_deadband
        self.positioner_state = 0.0
        
        # 气动延迟
        self.pneumatic_delay = pneumatic_delay
        self.pneumatic_delay_steps = max(0, int(pneumatic_delay / dt))
        self.pneumatic_buffer = []
        
        # 数字效应
        self.quantization_bits = quantization_bits
        self.communication_delay = communication_delay
        self.communication_delay_steps = max(0, int(communication_delay / dt))
        self.pv_buffer = []
        self.mv_buffer = []
    
    def reset(self):
        """重置环境状态"""
        self.step_count = 0
        self.colored_noise_state = 0.0
        self.sensor_drift_accumulated = 0.0
        self.sensor_fault_active = False
        self.sensor_fault_duration = 0
        self.positioner_state = 0.0
        self.pneumatic_buffer = []
        self.pv_buffer = []
        self.mv_buffer = []
        self.load_disturbance_phase = np.random.uniform(0, 2 * np.pi)
    
    def get_load_disturbance(self) -> float:
        """获取随机负荷扰动"""
        if self.load_disturbance_amplitude <= 0:
            return 0.0
        
        t = self.step_count * self.dt
        # 低频正弦 + 随机扰动
        sine_component = np.sin(2 * np.pi * self.load_disturbance_frequency * t + self.load_disturbance_phase)
        random_component = np.random.normal(0, 0.3)
        
        return self.load_disturbance_amplitude * (0.7 * sine_component + 0.3 * random_component)
    
    def get_periodic_disturbance(self) -> float:
        """获取周期性扰动（如泵脉动）"""
        if self.periodic_disturbance_amplitude <= 0:
            return 0.0
        
        t = self.step_count * self.dt
        # 快速正弦波模拟泵脉动
        return self.periodic_disturbance_amplitude * np.sin(2 * np.pi * t / self.periodic_disturbance_period)
    
    def get_colored_noise(self) -> float:
        """生成有色噪声（低通滤波白噪声）"""
        if self.noise_std <= 0:
            return 0.0
        
        white_noise = np.random.normal(0, self.noise_std)
        
        if self.colored_noise_tau > 0:
            # 一阶低通滤波器
            alpha = self.dt / (self.colored_noise_tau + self.dt)
            self.colored_noise_state = (1 - alpha) * self.colored_noise_state + alpha * white_noise
            return self.colored_noise_state
        else:
            return white_noise
    
    def apply_sensor_effects(self, pv_true: float) -> float:
        """应用传感器效应：漂移、故障、量化"""
        pv = pv_true
        
        # 1. 传感器漂移
        if self.sensor_drift_rate > 0:
            self.sensor_drift_accumulated += self.sensor_drift_rate * self.dt / 3600
            pv += self.sensor_drift_accumulated
        
        # 2. 传感器故障（随机跳变）
        if self.sensor_fault_probability > 0:
            if self.sensor_fault_active:
                self.sensor_fault_duration -= 1
                if self.sensor_fault_duration <= 0:
                    self.sensor_fault_active = False
                else:
                    pv += self.sensor_fault_magnitude * (1 if np.random.random() > 0.5 else -1)
            elif np.random.random() < self.sensor_fault_probability:
                self.sensor_fault_active = True
                self.sensor_fault_duration = np.random.randint(1, 10)
        
        # 3. 添加测量噪声（有色噪声）
        pv += self.get_colored_noise()
        
        # 4. 添加扰动
        pv += self.get_load_disturbance()
        pv += self.get_periodic_disturbance()
        
        # 5. 量化效应
        if self.quantization_bits > 0:
            pv_range = 100.0  # 假设 0-100 范围
            resolution = pv_range / (2 ** self.quantization_bits)
            pv = np.round(pv / resolution) * resolution
        
        # 6. 通信延迟
        if self.communication_delay_steps > 0:
            self.pv_buffer.append(pv)
            if len(self.pv_buffer) > self.communication_delay_steps:
                pv = self.pv_buffer.pop(0)
            else:
                pv = self.pv_buffer[0]  # 初始填充
        
        return pv
    
    def apply_actuator_effects(self, mv_command: float) -> float:
        """应用执行器效应：定位器动态、气动延迟"""
        mv = mv_command
        
        # 1. 阀门定位器动态
        if self.positioner_time_constant > 0:
            alpha = self.dt / (self.positioner_time_constant + self.dt)
            self.positioner_state = self.positioner_state + alpha * (mv - self.positioner_state)
            mv = self.positioner_state
        
        # 2. 定位器死区
        if self.positioner_deadband > 0:
            if abs(mv - self.positioner_state) < self.positioner_deadband:
                mv = self.positioner_state
        
        # 3. 气动延迟
        if self.pneumatic_delay_steps > 0:
            self.pneumatic_buffer.append(mv)
            if len(self.pneumatic_buffer) > self.pneumatic_delay_steps:
                mv = self.pneumatic_buffer.pop(0)
            else:
                mv = self.pneumatic_buffer[0]
        
        return mv
    
    def step(self):
        """前进一个时间步"""
        self.step_count += 1


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
def create_process(params: dict, cfg: dict, dt: float = 1.0):
    """工厂函数：根据配置创建适当的过程模型"""
    process_type = cfg.get('process_type', 'fopdt')
    
    # 阀门非线性参数
    deadband = cfg.get('valve_deadband', 0.0)
    stiction = cfg.get('valve_stiction', 0.0)
    mv_sat = cfg.get('mv_saturation', [0, 100])
    mv_min = mv_sat[0] if isinstance(mv_sat, list) else 0.0
    mv_max = mv_sat[1] if isinstance(mv_sat, list) else 100.0
    
    # 高级特性参数
    measurement_lag = cfg.get('measurement_lag', 0.0)
    stick_slip_period = cfg.get('stick_slip_period', 0)
    valve_curve = cfg.get('valve_curve', 'linear')
    delay_variation = cfg.get('delay_variation', 0.0)
    
    if process_type == 'integrating':
        # 积分过程 (液位)
        return IntegratingProcess(
            K=params.get('K', 0.05),
            L=params.get('L', 3.0),
            dt=dt,
            deadband=deadband,
            stiction=stiction,
            mv_min=mv_min,
            mv_max=mv_max
        )
    
    elif process_type == 'sopdt':
        # 二阶过程 (欠阻尼温度)
        return SOPDTProcess(
            K=params.get('K', 1.0),
            T1=params.get('T1', 30.0),
            T2=params.get('T2', 10.0),
            L=params.get('L', 5.0),
            zeta=params.get('zeta', 0.5),
            dt=dt,
            deadband=deadband,
            stiction=stiction,
            mv_min=mv_min,
            mv_max=mv_max
        )
    
    elif process_type == 'inverse_response':
        # 反向响应过程 (锅炉水位)
        return InverseResponseProcess(
            K=params.get('K', 1.0),
            T1=params.get('T1', 60.0),
            L=params.get('L', 5.0),
            K_inv=params.get('K_inv', 0.3),
            T_inv=params.get('T_inv', 5.0),
            dt=dt,
            deadband=deadband,
            stiction=stiction,
            mv_min=mv_min,
            mv_max=mv_max
        )
    
    elif measurement_lag > 0 or stick_slip_period > 0 or valve_curve != 'linear' or delay_variation > 0:
        # 高级 FOPDT (有测量滞后/粘滞跳动/非线性阀门/时变滞后)
        return AdvancedFOPDTProcess(
            K=params.get('K', 1.0),
            T1=params.get('T1', 30.0),
            L=params.get('L', 5.0),
            dt=dt,
            deadband=deadband,
            stiction=stiction,
            mv_min=mv_min,
            mv_max=mv_max,
            measurement_lag=measurement_lag,
            stick_slip_period=stick_slip_period,
            valve_curve=valve_curve,
            delay_variation=delay_variation
        )
    
    else:
        # 标准 FOPDT
        return FOPDTProcess(
            K=params.get('K', 1.0),
            T1=params.get('T1', 30.0),
            L=params.get('L', 5.0),
            dt=dt,
            deadband=deadband,
            stiction=stiction,
            mv_min=mv_min,
            mv_max=mv_max
        )


def create_environment(cfg: dict, dt: float = 1.0) -> RealisticEnvironment:
    """工厂函数：根据配置创建真实环境模拟器"""
    return RealisticEnvironment(
        dt=dt,
        # 负荷扰动
        load_disturbance_amplitude=cfg.get('load_disturbance', 0.0),
        load_disturbance_frequency=cfg.get('load_disturbance_freq', 0.01),
        # 周期性扰动
        periodic_disturbance_amplitude=cfg.get('periodic_disturbance', 0.0),
        periodic_disturbance_period=cfg.get('periodic_disturbance_period', 10.0),
        # 噪声
        noise_std=cfg.get('noise_std', 0.1),
        colored_noise_tau=cfg.get('colored_noise_tau', 0.0),
        # 传感器
        sensor_drift_rate=cfg.get('sensor_drift', 0.0),
        sensor_fault_probability=cfg.get('sensor_fault_prob', 0.0),
        sensor_fault_magnitude=cfg.get('sensor_fault_mag', 5.0),
        # 阀门定位器
        positioner_time_constant=cfg.get('positioner_tc', 0.0),
        positioner_deadband=cfg.get('positioner_db', 0.0),
        # 气动延迟
        pneumatic_delay=cfg.get('pneumatic_delay', 0.0),
        # 数字效应
        quantization_bits=cfg.get('quantization_bits', 0),
        communication_delay=cfg.get('communication_delay', 0.0)
    )

def generate_oscillation_data() -> Tuple[List[Dict], Dict, Dict]:
    """
    生成振荡场景数据：稳态 → 系统变化导致振荡 → 新PID恢复稳态
    """
    cfg = CONFIG
    dt = cfg['dt']
    sv = cfg['sv']
    
    # 使用工厂函数创建过程模型
    process = create_process(cfg['process_original'], cfg, dt)
    
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
    
    # 创建真实环境模拟器
    env = create_environment(cfg, dt)
    
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
        
        # 应用执行器效应
        mv_actual = env.apply_actuator_effects(controller.compute(sv, pv))
        pv_true = process.step(mv_actual)
        
        # 应用传感器效应（包括噪声、扰动）
        pv_measured = env.apply_sensor_effects(pv_true)
        
        # 更新控制器使用测量值
        pv = pv_measured
        
        # 环境步进
        env.step()
        
        history_data.append({
            'timestamp': timestamp,
            'pv': round(pv_measured, 2),
            'sv': round(sv, 2),
            'mv': round(mv_actual, 2),
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
                          error_band_pct: float = 0.05, seed: int = None,
                          valve_params: Dict = None,
                          disturbance_std: float = 0.0) -> Dict:
    """用PID参数仿真，计算性能指标
    
    Args:
        process_params: 过程参数 {K, T1, L}
        pid_params: PID参数 {kp/Kp, ki/Ki, kd/Kd}
        sv: 设定值
        duration: 仿真时长（秒）
        dt: 采样周期（秒）
        error_band_pct: 误差带百分比（默认5%）
        seed: 随机种子，确保可重复性
        valve_params: 阀门参数 {deadband, stiction, mv_saturation}
        disturbance_std: 持续扰动标准差（占SV的比例），模拟真实工业环境
    """
    # 固定随机种子确保可重复性
    if seed is not None:
        np.random.seed(seed)
    
    # 解析阀门参数
    vp = valve_params or {}
    mv_sat = vp.get('mv_saturation', [0, 100])
    
    process = FOPDTProcess(
        K=process_params['K'],
        T1=process_params['T1'],
        L=process_params['L'],
        dt=dt,
        deadband=vp.get('deadband', vp.get('valve_deadband', 0.0)),
        stiction=vp.get('stiction', vp.get('valve_stiction', 0.0)),
        mv_min=mv_sat[0] if isinstance(mv_sat, list) else 0.0,
        mv_max=mv_sat[1] if isinstance(mv_sat, list) else 100.0
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
    
    # 计算扰动参数
    disturbance_amplitude = sv * disturbance_std if disturbance_std > 0 else 0
    # 振荡周期：基于过程时间常数估算典型振荡周期（约为 4-6 倍时间常数）
    T1 = process_params.get('T1', 30)
    oscillation_period = T1 * 5  # 振荡周期约为时间常数的 2 倍（更慢更真实）
    
    for step in range(steps):
        t = step * dt
        mv = controller.compute(sv, pv)
        pv = process.step(mv)
        
        # 添加不规则周期性扰动（模拟真实工业振荡环境）
        if disturbance_amplitude > 0:
            # 1. 振幅调制：振幅随时间变化（0.5~1.5倍）
            amplitude_mod = 0.5 + np.random.random()
            # 2. 频率抖动：周期在 80%~120% 范围内随机变化
            freq_mod = 0.8 + 0.4 * np.random.random()
            current_period = oscillation_period * freq_mod
            # 3. 主振荡 + 随机噪声
            periodic_disturbance = disturbance_amplitude * amplitude_mod * np.sin(2 * np.pi * t / current_period)
            random_noise = np.random.normal(0, disturbance_amplitude * 0.5)
            pv += periodic_disturbance + random_noise
        
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
    
    # 方法3: 检测PV振荡（振荡场景）- 使用自适应阈值
    window_size = 50
    
    # 自适应阈值：基于前100点"平静期"噪声水平
    baseline_samples = min(100, len(pv_array) // 4)
    baseline_noise = np.std(pv_array[:baseline_samples])
    
    # 自适应阈值 = max(固定最小值, k倍噪声水平)
    # k=3 表示需要超过3倍噪声才认为是真实振荡
    std_threshold = max(0.3, 3.0 * baseline_noise)
    
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
    
    # 方法4: 低信噪比场景 - 使用更敏感的检测
    # 检查全局PV变化趋势（即使噪声较大也能检测到系统变化）
    pv_smooth = np.convolve(pv_array, np.ones(10)/10, mode='same')  # 平滑
    pv_diff = np.abs(np.diff(pv_smooth))
    
    # 寻找突变点（平滑后的趋势变化）
    for i in range(50, len(pv_diff)):
        # 检测趋势变化：当前段vs前一段的均值差异
        prev_mean = np.mean(pv_smooth[i-50:i-25])
        curr_mean = np.mean(pv_smooth[i-25:i])
        if abs(curr_mean - prev_mean) > max(0.5, 2.0 * baseline_noise):
            start_idx = max(0, i - 50)
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
    """为单个场景生成可视化对比图（简化版：移除 LLM 对比）
    
    Args:
        scenario: 场景配置
        metadata: 元数据
        data: 原始历史数据（稳态+振荡）
        sim_old/sim_rule: 仿真结果（sim_llm 保留参数兼容但不使用）
        pid_rule: PID参数（pid_llm 保留参数兼容但不使用）
        result: 对比结果
        scenario_idx: 场景索引
        tuning_method: 整定方法
    """
    # 现代配色方案
    COLORS = {
        'pv': '#1E88E5',        # 深蓝
        'sv': '#E53935',        # 橙红
        'mv': '#43A047',        # 翠绿
        'old_pid': '#7E57C2',   # 紫色
        'rule': '#FF9800',      # 橙色
        'band': '#4CAF50',      # 绿色
        'grid': '#E0E0E0',      # 浅灰
    }
    
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams['axes.facecolor'] = '#FAFAFA'
    plt.rcParams['figure.facecolor'] = '#FFFFFF'
    
    fig = plt.figure(figsize=(16, 10))
    
    # 标题（移除 LLM 相关标识）
    rule_stable = sim_rule['is_stable']
    status_text = 'STABLE' if rule_stable else 'UNSTABLE'
    status_color = '#4CAF50' if rule_stable else '#F44336'
    method_str = 'Critical Method' if 'oscillation' in tuning_method else 'Model Fitting'
    
    fig.suptitle(f"Scenario {scenario_idx}: {scenario['name']}\n"
                 f"{scenario['description']} | Method: {method_str}", 
                 fontsize=14, fontweight='bold', color='#333333')
    
    sv = metadata['sv']
    pid_old = scenario['original_pid']
    
    # 提取原始数据
    timestamps = [d['timestamp'] for d in data]
    time_seconds = [(ts - timestamps[0]) / 1000 for ts in timestamps]
    pv_array = np.array([d['pv'] for d in data])
    sv_array = np.array([d['sv'] for d in data])
    mv_array = np.array([d['mv'] for d in data])
    
    # 找到系统变化时间点
    change_idx = 300
    if metadata.get('change_time'):
        for i, ts in enumerate(timestamps):
            if ts >= metadata['change_time']:
                change_idx = i
                break
    
    # ========== 2x3 布局 ==========
    
    # ========== 子图1: 原始数据 PV/SV + MV（双Y轴）==========
    ax1 = fig.add_subplot(2, 3, 1)
    ax1.plot(time_seconds, pv_array, color=COLORS['pv'], label='PV', linewidth=1.2, alpha=0.9)
    ax1.plot(time_seconds, sv_array, color=COLORS['sv'], linestyle='--', label='SV', linewidth=1.5)
    ax1.axvline(x=time_seconds[change_idx], color='#FF5722', linestyle='--', linewidth=2, alpha=0.8, label='Change')
    ax1.fill_between(time_seconds, sv * 0.95, sv * 1.05, alpha=0.12, color=COLORS['band'])
    ax1.set_ylabel('PV / SV', fontweight='bold', color=COLORS['pv'])
    ax1.set_xlabel('Time (s)')
    ax1.set_title('Original Data: PV, SV & MV', fontweight='bold', fontsize=11)
    ax1.tick_params(axis='y', labelcolor=COLORS['pv'])
    ax1.grid(True, alpha=0.4, color=COLORS['grid'])
    ax1.set_xlim([0, time_seconds[-1]])
    
    # 添加 MV 到右侧 Y 轴
    ax1_mv = ax1.twinx()
    ax1_mv.plot(time_seconds, mv_array, color=COLORS['mv'], label='MV', linewidth=1.0, alpha=0.7)
    ax1_mv.set_ylabel('MV (%)', fontweight='bold', color=COLORS['mv'])
    ax1_mv.tick_params(axis='y', labelcolor=COLORS['mv'])
    
    # 合并图例
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax1_mv.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=7, framealpha=0.9)
    
    # ========== 子图2: 振荡段放大（PV/SV + MV）==========
    ax2 = fig.add_subplot(2, 3, 2)
    osc_start = max(0, change_idx - 20)
    ax2.plot(time_seconds[osc_start:], pv_array[osc_start:], color=COLORS['pv'], label='PV', linewidth=1.2)
    ax2.plot(time_seconds[osc_start:], sv_array[osc_start:], color=COLORS['sv'], linestyle='--', label='SV', linewidth=1.5)
    ax2.axhline(y=sv * 1.05, color='#9E9E9E', linestyle=':', alpha=0.7)
    ax2.axhline(y=sv * 0.95, color='#9E9E9E', linestyle=':', alpha=0.7)
    ax2.fill_between(time_seconds[osc_start:], sv * 0.95, sv * 1.05, alpha=0.12, color=COLORS['band'])
    ax2.set_ylabel('PV / SV', fontweight='bold', color=COLORS['pv'])
    ax2.set_xlabel('Time (s)')
    ax2.set_title('Oscillation Segment (Zoomed)', fontweight='bold', fontsize=11)
    ax2.tick_params(axis='y', labelcolor=COLORS['pv'])
    ax2.grid(True, alpha=0.4, color=COLORS['grid'])
    
    # 添加 MV 到右侧 Y 轴
    ax2_mv = ax2.twinx()
    ax2_mv.plot(time_seconds[osc_start:], mv_array[osc_start:], color=COLORS['mv'], label='MV', linewidth=1.0, alpha=0.7)
    ax2_mv.set_ylabel('MV (%)', fontweight='bold', color=COLORS['mv'])
    ax2_mv.tick_params(axis='y', labelcolor=COLORS['mv'])
    
    lines1, labels1 = ax2.get_legend_handles_labels()
    lines2, labels2 = ax2_mv.get_legend_handles_labels()
    ax2.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=7, framealpha=0.9)
    
    # ========== 子图3: Old PID vs New PID 对比（含 MV）==========
    ax3 = fig.add_subplot(2, 3, 3)
    ax3.plot(sim_old['t'], sim_old['pv'], color=COLORS['old_pid'], linestyle='--', label='Old PV', linewidth=1.5, alpha=0.8)
    ax3.plot(sim_rule['t'], sim_rule['pv'], color=COLORS['rule'], label='Tuned PV', linewidth=2)
    ax3.plot(sim_old['t'], sim_old['sv'], color=COLORS['sv'], linestyle='--', label='SV', linewidth=1.2, alpha=0.7)
    ax3.fill_between(sim_old['t'], sv * 0.95, sv * 1.05, alpha=0.12, color=COLORS['band'])
    old_status = 'Stable' if sim_old['is_stable'] else 'Oscillating'
    new_status = 'STABLE' if sim_rule['is_stable'] else 'Oscillating'
    ax3.set_title(f"Old ({old_status}) vs Tuned ({new_status})", fontweight='bold', fontsize=11)
    ax3.set_ylabel('PV', fontweight='bold', color=COLORS['pv'])
    ax3.set_xlabel('Time (s)')
    ax3.tick_params(axis='y', labelcolor=COLORS['pv'])
    ax3.grid(True, alpha=0.4, color=COLORS['grid'])
    
    # 添加 MV 到右侧 Y 轴
    ax3_mv = ax3.twinx()
    ax3_mv.plot(sim_old['t'], sim_old['mv'], color=COLORS['old_pid'], linestyle=':', label='Old MV', linewidth=1.0, alpha=0.5)
    ax3_mv.plot(sim_rule['t'], sim_rule['mv'], color=COLORS['rule'], linestyle=':', label='Tuned MV', linewidth=1.0, alpha=0.6)
    ax3_mv.set_ylabel('MV (%)', fontweight='bold', color=COLORS['mv'])
    ax3_mv.tick_params(axis='y', labelcolor=COLORS['mv'])
    
    # 合并图例
    lines1, labels1 = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3_mv.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labels1 + labels2, loc='lower right', fontsize=6, framealpha=0.9, ncol=2)

    
    # ========== 子图4: 性能指标柱状图 ==========
    ax4 = fig.add_subplot(2, 3, 4)
    metrics = ['Settling\nTime (s)', 'Overshoot\n(%)', 'IAE\n(×100)']
    old_vals = [min(sim_old['settling_time'], 300), sim_old['overshoot'], sim_old.get('iae', 0) / 100]
    rule_vals = [min(sim_rule['settling_time'], 300), sim_rule['overshoot'], sim_rule.get('iae', 0) / 100]
    
    x = np.arange(len(metrics))
    width = 0.35
    bars1 = ax4.bar(x - width/2, old_vals, width, label='Old PID', color=COLORS['old_pid'], alpha=0.8)
    bars2 = ax4.bar(x + width/2, rule_vals, width, label='Tuned PID', color=COLORS['rule'], alpha=0.8)
    
    # 标记不稳定的
    if not sim_old['is_stable']:
        bars1[0].set_hatch('//')
        bars1[0].set_edgecolor('#333333')
    if not sim_rule['is_stable']:
        bars2[0].set_hatch('//')
        bars2[0].set_edgecolor('#333333')
    
    # 添加数值标签
    for bar, val in zip(bars1, old_vals):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
                f'{val:.1f}', ha='center', va='bottom', fontsize=8, color='#555555')
    for bar, val in zip(bars2, rule_vals):
        ax4.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 2, 
                f'{val:.1f}', ha='center', va='bottom', fontsize=8, color='#555555')
    
    ax4.set_ylabel('Value', fontweight='bold')
    ax4.set_title('Performance Metrics', fontweight='bold', fontsize=11)
    ax4.set_xticks(x)
    ax4.set_xticklabels(metrics, fontsize=9)
    ax4.legend(fontsize=9, framealpha=0.9)
    ax4.grid(True, alpha=0.4, axis='y', color=COLORS['grid'])
    
    # ========== 子图5: 参数信息卡片 ==========
    ax5 = fig.add_subplot(2, 3, 5)
    ax5.axis('off')
    
    # 构建简洁的信息卡片
    info_lines = [
        ("PROCESS PARAMETERS", None),
        ("─" * 35, None),
        (f"Original: K={scenario['process_original']['K']:.2f}, T1={scenario['process_original']['T1']:.1f}s", None),
        (f"Changed:  K={scenario['process_changed']['K']:.2f}, T1={scenario['process_changed']['T1']:.1f}s, L={scenario['process_changed']['L']:.1f}s", None),
        ("", None),
        ("PID PARAMETERS", None),
        ("─" * 35, None),
        (f"{'Parameter':<12} {'Old PID':<12} {'Tuned PID':<12}", None),
        (f"{'PB (%)':<12} {100/pid_old['Kp'] if pid_old.get('Kp', 0) != 0 else '-':<12.1f} {pid_rule.get('pb', 100):<12.1f}", None),
        (f"{'Ti (s)':<12} {pid_old['Kp']/pid_old['Ki'] if pid_old.get('Ki', 0) != 0 else '-':<12.1f} {pid_rule.get('ti', 0):<12.1f}", None),
        (f"{'Td (s)':<12} {pid_old['Kd']/pid_old['Kp'] if pid_old.get('Kp', 0) != 0 and pid_old.get('Kd', 0) != 0 else 0:<12.1f} {pid_rule.get('td', 0):<12.1f}", None),
        ("", None),
        ("TUNING RESULT", None),
        ("─" * 35, None),
    ]
    
    # 状态行
    if sim_rule['is_stable']:
        info_lines.append((f"Status: STABLE (Ts={sim_rule['settling_time']:.0f}s)", '#4CAF50'))
    else:
        info_lines.append((f"Status: UNSTABLE (not settled)", '#F44336'))
    
    info_lines.append((f"Method: {method_str}", None))
    info_lines.append((f"Loop Type: {scenario.get('loop_type', 'unknown')}", None))
    
    # 绘制信息
    y_pos = 0.95
    for text, color in info_lines:
        text_color = color if color else '#333333'
        fontweight = 'bold' if text.isupper() or 'Status' in text else 'normal'
        ax5.text(0.05, y_pos, text, transform=ax5.transAxes, fontsize=10,
                 verticalalignment='top', fontfamily='monospace',
                 color=text_color, fontweight=fontweight)
        y_pos -= 0.055
    
    # 添加背景框
    from matplotlib.patches import FancyBboxPatch
    bbox = FancyBboxPatch((0.02, 0.02), 0.96, 0.96, 
                          boxstyle="round,pad=0.02,rounding_size=0.02",
                          facecolor='#F5F5F5', edgecolor='#BDBDBD',
                          transform=ax5.transAxes, zorder=-1)
    ax5.add_patch(bbox)
    
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    
    # 保存图片
    stability_dir = os.path.join(CONFIG['output_dir'], 'stability')
    os.makedirs(stability_dir, exist_ok=True)
    safe_name = scenario['name'].replace(' ', '_').replace('/', '_')
    filename = f'scenario_{scenario_idx:02d}_{safe_name}.png'  # 固定文件名，覆盖旧图
    filepath = os.path.join(stability_dir, filename)
    plt.savefig(filepath, dpi=150, bbox_inches='tight', facecolor='white', edgecolor='none')
    print(f"   Chart saved: {filepath}")
    plt.close()



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
    rule_stable_cl_count = 0  # 闭环验证稳态计数（用估算模型参数）
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
            
            # 动态仿真时长：根据回路类型调整乘数
            T1_changed = process_changed.get('T1', 30)
            L_changed = process_changed.get('L', 5)
            loop_type = scenario.get('loop_type', 'flow')
            
            # 【优化】根据回路类型使用不同的仿真时长乘数
            if loop_type == 'level':
                # 液位回路：积分特性，需要更长时间验证稳定性
                sim_factor = 10.0
                min_duration = 600
            elif loop_type == 'temperature':
                # 温度回路：大时间常数，需要较长时间
                sim_factor = 8.0
                min_duration = 500
            else:
                # 流量/压力回路：响应较快
                sim_factor = 6.0
                min_duration = 400
            
            # 极慢系统(T1>100s)特殊处理
            if T1_changed > 100:
                sim_factor = max(sim_factor, 12.0)
                min_duration = max(min_duration, 1200)
            
            sim_duration = max(min_duration, int((T1_changed + L_changed) * sim_factor))
            
            # ===== 规则引擎整定 =====
            print("   🔧 规则引擎整定...")
            # 重置种子确保 ModelSelector 内部的 scipy.optimize 也可重复
            np.random.seed(scenario_seed + 100)
            Config.OSCILLATION_TUNING['enable_llm'] = False
            loop_type = scenario.get('loop_type', 'flow')
            selector_rule = ModelSelector(
                verbose=True,
                process_context={'loop_type': loop_type, 'loop_name': scenario['name']}
            )
            result_rule = selector_rule.run(input_data)
            pid_rule = result_rule.get('pid_parameters', {})
            
            # 重置种子用于仿真
            np.random.seed(scenario_seed + 200)
            
            # 仿真规则引擎参数（使用固定种子确保可重复）
            sim_seed = scenario_seed + 300  # 使用 scenario_seed 而非 hash()
            sim_rule = simulate_with_new_pid(process_changed, pid_rule, sv, duration=sim_duration, seed=sim_seed)
            
            # 只有整定成功且仿真稳定才算"稳态达成"
            tuning_success = result_rule.get('success', False)
            rule_stable = tuning_success and sim_rule['is_stable']
            if rule_stable:
                rule_stable_count += 1
            
            if not tuning_success:
                print(f"      稳态(真实参数): ❌ 否 (整定失败，无有效参数)")
            else:
                print(f"      稳态(真实参数): {'✅ 是' if sim_rule['is_stable'] else '❌ 否'} (Ts={sim_rule['settling_time']:.0f}s)")
            
            # ===== 闭环验证（用估算模型参数）=====
            model_params = result_rule.get('model_parameters', {})
            estimated_process = {
                'K': model_params.get('K', 1.0),
                'T1': model_params.get('T1', 30.0),
                'L': model_params.get('L', model_params.get('delay', 5.0))
            }
            sim_rule_cl = simulate_with_new_pid(estimated_process, pid_rule, sv, duration=sim_duration, seed=sim_seed+10)
            rule_stable_cl = tuning_success and sim_rule_cl['is_stable']
            if rule_stable_cl:
                rule_stable_cl_count += 1
            
            if tuning_success:
                print(f"      稳态(闭环验证): {'✅ 是' if sim_rule_cl['is_stable'] else '❌ 否'} (Ts={sim_rule_cl['settling_time']:.0f}s)")
            
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
                
                # 只有整定成功且仿真稳定才算"稳态达成"
                llm_tuning_success = result_llm.get('success', False)
                llm_stable = llm_tuning_success and sim_llm['is_stable']
                if llm_stable:
                    llm_stable_count += 1
                
                if not llm_tuning_success:
                    print(f"      稳态: ❌ 否 (整定失败，无有效参数)")
                else:
                    print(f"      稳态: {'✅ 是' if sim_llm['is_stable'] else '❌ 否'} (Ts={sim_llm['settling_time']:.0f}s)")
            
            results.append({
                'scenario': scenario,  # 完整场景对象用于难度计算
                'scenario_name': scenario['name'],
                'loop_type': scenario.get('loop_type', 'unknown'),
                'rule_stable': rule_stable,
                'rule_ts': sim_rule['settling_time'],
                'rule_overshoot': sim_rule.get('overshoot', 0),
                'pb_value': pid_rule.get('pb', 100.0),  # 记录PB值
                'ti_value': pid_rule.get('ti', 10.0),   # 记录Ti值
                'td_value': pid_rule.get('td', 0.0),    # 记录Td值
                'llm_stable': llm_stable,
                'llm_ts': sim_llm['settling_time'] if sim_llm else None,
                'llm_overshoot': sim_llm.get('overshoot', 0) if sim_llm else None,
            })
            
            # ===== 生成可视化图表 =====
            print("   📊 生成可视化图表...")
            
            # 仿真老PID参数（在变化后的系统上，添加持续扰动模拟真实环境）
            pid_old = scenario['original_pid']
            sim_old = simulate_with_new_pid(process_changed, pid_old, sv, duration=sim_duration,
                                           disturbance_std=0.02)  # 2% 持续扰动
            
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
    rule_rate = rule_stable_count/total*100 if total > 0 else 0
    cl_rate = rule_stable_cl_count/total*100 if total > 0 else 0
    print(f"║    规则(真实参数): {rule_stable_count}/{total} ({rule_rate:.1f}%)" + " " * 47 + "║")
    print(f"║    规则(闭环验证): {rule_stable_cl_count}/{total} ({cl_rate:.1f}%)" + " " * 47 + "║")
    if llm_available:
        print(f"║    LLM+规则引擎:   {llm_stable_count}/{total} ({llm_stable_count/total*100:.1f}%)" + " " * 45 + "║")
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
    
    # 按难度等级统计
    print("\n【按难度等级统计】")
    print(f"{'难度等级':<10} {'场景数':<8} {'规则稳态':<12} {'通过率':<10}")
    print("-" * 45)
    
    # 计算每个场景的难度
    difficulty_stats = {'EASY': {'total': 0, 'stable': 0}, 
                       'MEDIUM': {'total': 0, 'stable': 0},
                       'HARD': {'total': 0, 'stable': 0},
                       'EXTREME': {'total': 0, 'stable': 0}}
    
    for r in valid_results:
        scenario = r.get('scenario')
        if scenario:
            _, level, _ = calculate_scenario_difficulty(scenario)
            difficulty_stats[level]['total'] += 1
            if r.get('rule_stable'):
                difficulty_stats[level]['stable'] += 1
    
    level_order = ['EASY', 'MEDIUM', 'HARD', 'EXTREME']
    level_emoji = {'EASY': '🟢', 'MEDIUM': '🟡', 'HARD': '🟠', 'EXTREME': '🔴'}
    
    for level in level_order:
        stats = difficulty_stats[level]
        if stats['total'] > 0:
            rate = stats['stable'] / stats['total'] * 100
            print(f"{level_emoji[level]} {level:<8} {stats['total']:<8} {stats['stable']}/{stats['total']:<10} {rate:.1f}%")
    
    # ===== PB分布统计（检查是否符合真实场景）=====
    print("\n【PB分布统计】")
    pb_values = [r.get('pb_value', 100.0) for r in valid_results if r.get('pb_value')]
    if pb_values:
        pb_mean = np.mean(pb_values)
        pb_median = np.median(pb_values)
        pb_min = np.min(pb_values)
        pb_max = np.max(pb_values)
        
        # 统计各区间分布
        pb_ranges = [
            ('50-150%', 50, 150, '🟢 理想'),
            ('150-300%', 150, 300, '🟡 正常'),
            ('300-500%', 300, 500, '🟠 偏高'),
            ('500%+', 500, float('inf'), '🔴 过高')
        ]
        
        print(f"   平均PB: {pb_mean:.1f}%  |  中位PB: {pb_median:.1f}%  |  范围: {pb_min:.0f}%-{pb_max:.0f}%")
        print(f"   {'PB范围':<15} {'场景数':<10} {'占比':<10} {'评价':<10}")
        print("   " + "-" * 50)
        
        for label, low, high, rating in pb_ranges:
            count = sum(1 for pb in pb_values if low <= pb < high)
            pct = count / len(pb_values) * 100 if pb_values else 0
            print(f"   {label:<15} {count:<10} {pct:.1f}%{' ':5}{rating}")
        
        # 判断是否符合真实场景
        normal_count = sum(1 for pb in pb_values if 50 <= pb < 300)
        normal_rate = normal_count / len(pb_values) * 100
        
        if normal_rate >= 70:
            print(f"\n   ✅ PB分布符合工业标准 ({normal_rate:.0f}%在正常范围)")
        elif normal_rate >= 50:
            print(f"\n   ⚠️ PB分布偏高 ({normal_rate:.0f}%在正常范围，建议优化)")
        else:
            print(f"\n   ❌ PB分布过高 (仅{normal_rate:.0f}%在正常范围，需要优化)")
    
    # ===== Ti/Td 分布统计 =====
    print("\n【Ti/Td 分布统计】")
    ti_values = [r.get('ti_value', 10.0) for r in valid_results if r.get('ti_value')]
    td_values = [r.get('td_value', 0.0) for r in valid_results if r.get('td_value') is not None]
    
    if ti_values:
        ti_mean = np.mean(ti_values)
        ti_median = np.median(ti_values)
        ti_min = np.min(ti_values)
        ti_max = np.max(ti_values)
        print(f"   Ti: 平均={ti_mean:.1f}s  中位={ti_median:.1f}s  范围={ti_min:.1f}-{ti_max:.1f}s")
        
        # Ti分布
        ti_ranges = [('0-5s', 0, 5), ('5-15s', 5, 15), ('15-30s', 15, 30), ('30s+', 30, float('inf'))]
        ti_dist = []
        for label, low, high in ti_ranges:
            count = sum(1 for ti in ti_values if low <= ti < high)
            pct = count / len(ti_values) * 100
            ti_dist.append(f"{label}:{count}({pct:.0f}%)")
        print(f"   分布: {' | '.join(ti_dist)}")
    
    if td_values:
        td_nonzero = [td for td in td_values if td > 0]
        td_used = len(td_nonzero)
        td_pct = td_used / len(td_values) * 100
        if td_nonzero:
            td_mean = np.mean(td_nonzero)
            print(f"   Td: 使用率={td_pct:.0f}% ({td_used}/{len(td_values)})  平均={td_mean:.2f}s (仅非零)")
        else:
            print(f"   Td: 使用率=0% (全部为纯PI控制)")
    
    # ===== 按回路类型分析 PB/Ti/Td =====
    print("\n【按回路类型 PB/Ti/Td 分析】")
    
    # 石化行业标准范围
    INDUSTRY_STANDARDS = {
        'flow': {'pb_range': (50, 150), 'ti_range': (2, 10), 'td_usage': 'low'},
        'pressure': {'pb_range': (80, 200), 'ti_range': (5, 30), 'td_usage': 'low'},
        'temperature': {'pb_range': (100, 400), 'ti_range': (30, 180), 'td_usage': 'high'},
        'level': {'pb_range': (100, 400), 'ti_range': (30, 120), 'td_usage': 'none'},
    }
    
    loop_types = sorted(set(r.get('loop_type', 'unknown') for r in valid_results))
    
    print(f"   {'回路类型':<12} {'PB范围':<18} {'Ti范围':<15} {'Td使用':<12} {'符合度':<10}")
    print("   " + "-" * 70)
    
    for lt in loop_types:
        lt_results = [r for r in valid_results if r.get('loop_type') == lt]
        if not lt_results:
            continue
        
        # 获取该类型的 PB/Ti/Td 值
        lt_pb = [r.get('pb_value', 100.0) for r in lt_results if r.get('pb_value')]
        lt_ti = [r.get('ti_value', 10.0) for r in lt_results if r.get('ti_value')]
        lt_td = [r.get('td_value', 0.0) for r in lt_results if r.get('td_value') is not None]
        
        if lt_pb:
            pb_min, pb_max = min(lt_pb), max(lt_pb)
            pb_median = np.median(lt_pb)
            pb_str = f"{pb_min:.0f}-{pb_max:.0f}% (中位{pb_median:.0f}%)"
        else:
            pb_str = "N/A"
        
        if lt_ti:
            ti_min, ti_max = min(lt_ti), max(lt_ti)
            ti_median = np.median(lt_ti)
            ti_str = f"{ti_min:.1f}-{ti_max:.1f}s"
        else:
            ti_str = "N/A"
        
        if lt_td:
            td_used = sum(1 for td in lt_td if td > 0)
            td_pct = td_used / len(lt_td) * 100
            td_str = f"{td_pct:.0f}% ({td_used}/{len(lt_td)})"
        else:
            td_str = "N/A"
        
        # 计算符合度（改进版：考虑中位数和稳态率）
        std = INDUSTRY_STANDARDS.get(lt, {'pb_range': (100, 300), 'ti_range': (5, 30), 'td_usage': 'medium'})
        conformity = []
        
        if lt_pb:
            pb_median = np.median(lt_pb)
            pb_std_min, pb_std_max = std['pb_range']
            
            # 检查中位数是否在标准范围的1.5倍内
            if pb_std_min <= pb_median <= pb_std_max:
                conformity.append('✅')  # 中位数在标准范围内
            elif pb_median <= pb_std_max * 1.5:
                conformity.append('⚠️')  # 中位数在1.5倍标准范围内
            else:
                conformity.append('❌')  # 超出1.5倍标准范围
        
        conformity_str = ''.join(conformity) if conformity else '-'
        
        print(f"   {lt:<12} {pb_str:<18} {ti_str:<15} {td_str:<12} {conformity_str}")
    
    # 打印石化标准参考
    print("\n   【石化行业标准参考】")
    print(f"   {'回路类型':<12} {'PB典型范围':<15} {'Ti典型范围':<15} {'Td使用':<10}")
    print("   " + "-" * 55)
    for lt, std in INDUSTRY_STANDARDS.items():
        pb_range = f"{std['pb_range'][0]}-{std['pb_range'][1]}%"
        ti_range = f"{std['ti_range'][0]}-{std['ti_range'][1]}s"
        td_usage = {'low': '少用', 'high': '多用', 'none': '不用', 'medium': '适中'}[std['td_usage']]
        print(f"   {lt:<12} {pb_range:<15} {ti_range:<15} {td_usage}")
    
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
    stable_count_cl = 0  # 闭环验证稳态计数
    
    # 按回路类型统计
    by_loop_type = {}
    by_loop_type_cl = {}  # 闭环验证统计
    
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
            
            # 仿真验证 - 动态调整仿真时长
            # 对于慢系统(液位/温度)或大T1系统,延长仿真时间
            loop_type = scenario.get('loop_type', 'unknown')
            process_T1 = scenario['process']['T1']
            
            if loop_type == 'level' or process_T1 > 40:
                # 液位或慢系统: 仿真时长 = 10 * T1, 最少 600s
                sim_duration = max(600, int(10 * process_T1))
            elif loop_type == 'temperature' or process_T1 > 30:
                # 温度回路: 仿真时长 = 8 * T1
                sim_duration = max(500, int(8 * process_T1))
            else:
                # 流量/压力等快速回路
                sim_duration = 400
            
            # ===== 方法1: 使用真实过程参数仿真 =====
            sim = simulate_with_new_pid(scenario['process'], pid_new, metadata['sv'], duration=sim_duration)
            is_stable_true = sim['is_stable']
            
            # 对于慢系统，如果未稳态但在收敛，也认为成功
            if not is_stable_true and (loop_type == 'level' or process_T1 > 40):
                if sim['is_converging'] and sim['steady_error'] < 10:
                    is_stable_true = True
            
            # ===== 方法2: 使用估算模型参数仿真（闭环验证） =====
            estimated_process = {
                'K': model_params.get('K', 1.0),
                'T1': model_params.get('T1', 30.0),
                'L': model_params.get('L', model_params.get('delay', 5.0))
            }
            sim_cl = simulate_with_new_pid(estimated_process, pid_new, metadata['sv'], duration=sim_duration)
            is_stable_cl = sim_cl['is_stable']
            
            # 对于慢系统的宽松判定
            if not is_stable_cl and (loop_type == 'level' or estimated_process['T1'] > 40):
                if sim_cl['is_converging'] and sim_cl['steady_error'] < 15:
                    is_stable_cl = True
            
            if is_stable_true:
                stable_count += 1
            
            print(f"   真实参数仿真: {'✅' if is_stable_true else '❌'} (Ts={sim['settling_time']:.0f}s)")
            print(f"   闭环验证:     {'✅' if is_stable_cl else '❌'} (Ts={sim_cl['settling_time']:.0f}s, 用估算模型)")
            
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
            status = '✅ 稳态' if is_stable_true else '❌ 未稳态'
            ax2.set_title(f"新PID仿真响应 - {status} (Ts={sim['settling_time']:.0f}s)")
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
            if loop_type not in by_loop_type_cl:
                by_loop_type_cl[loop_type] = {'total': 0, 'stable': 0}
            
            by_loop_type[loop_type]['total'] += 1
            by_loop_type_cl[loop_type]['total'] += 1
            
            if is_stable_true:
                by_loop_type[loop_type]['stable'] += 1
            if is_stable_cl:
                by_loop_type_cl[loop_type]['stable'] += 1
                stable_count_cl += 1
            
            results.append({
                'scenario': scenario['name'],
                'loop_type': loop_type,
                'tuning_method': tuning_method,
                'K_error': K_error,
                'T1_error': T1_error,
                'L_error': L_error,
                'is_stable_true': is_stable_true,
                'is_stable_cl': is_stable_cl,
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
        print(f"║ 稳态达成率对比:                                                          ║")
        print(f"║                      真实参数仿真    闭环验证(估算模型)                  ║")
        print(f"║{'─'*78}║")
        for lt in sorted(by_loop_type.keys()):
            stats_true = by_loop_type[lt]
            stats_cl = by_loop_type_cl.get(lt, {'total': 0, 'stable': 0})
            rate_true = stats_true['stable'] / stats_true['total'] * 100 if stats_true['total'] > 0 else 0
            rate_cl = stats_cl['stable'] / stats_cl['total'] * 100 if stats_cl['total'] > 0 else 0
            print(f"║   {lt:<12}:    {stats_true['stable']}/{stats_true['total']} ({rate_true:>3.0f}%)           {stats_cl['stable']}/{stats_cl['total']} ({rate_cl:>3.0f}%)                       ║")
        rate_true_total = stable_count/total*100 if total > 0 else 0
        rate_cl_total = stable_count_cl/total*100 if total > 0 else 0
        print(f"║{'─'*78}║")
        print(f"║   总体:           {stable_count}/{total} ({rate_true_total:>3.0f}%)           {stable_count_cl}/{total} ({rate_cl_total:>3.0f}%)                       ║")
    print("╚" + "═" * 78 + "╝")
    
    print("\n✅ Lambda 整定验证测试完成!")
    return results


# ============================================================
# 运行所有测试
# ============================================================
def run_all_tests():
    """运行所有三个验证目标的测试并生成汇总报告"""
    print("=" * 80)
    print("运行所有验证目标测试")
    print("=" * 80)
    
    all_results = {}
    
    print("\n" + "▶" * 40)
    print("开始目标1: 振荡场景稳态验证 (含LLM优化效果对比)")
    print("▶" * 40)
    all_results['stability'] = run_stability_test()
    
    print("\n" + "▶" * 40)
    print("开始目标2: 振荡幅度阈值估计")
    print("▶" * 40)
    all_results['amplitude'] = run_amplitude_threshold_test()
    
    print("\n" + "▶" * 40)
    print("开始目标3: Lambda 整定验证")
    print("▶" * 40)
    all_results['lambda'] = run_lambda_tuning_test()
    
    # 汇总报告
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + "全部测试完成 - 汇总报告".center(70) + "║")
    print("╠" + "═" * 78 + "╣")
    print("║ 目标1 (振荡稳态验证+LLM效果): 完成                                        ║")
    print("║ 目标2 (幅度阈值估计): 完成                                              ║")
    print("║ 目标3 (Lambda整定): 完成                                                ║")
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
    else:
        # default 模式
        main()
