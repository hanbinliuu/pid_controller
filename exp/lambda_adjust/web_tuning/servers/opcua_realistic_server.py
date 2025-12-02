"""
OPC UA 真实场景模拟服务器
模拟真实的PID控制循环：稳态 → 非稳态 → 触发重整定 → 新参数下重回稳态 → 循环
"""

from asyncua import Server, ua
import asyncio
import random
import math
import numpy as np
from datetime import datetime
from typing import Dict, Tuple
import sys
from pathlib import Path

# 添加backend路径以使用日志工具
backend_path = Path(__file__).parent.parent / 'backend'
sys.path.insert(0, str(backend_path))

try:
    from utils.logger import info, debug, warning, error, success, section
except ImportError:
    # 如果日志工具不可用，使用print（确保输出到stdout并立即刷新）
    def info(msg): print(f"ℹ️  {msg}", flush=True)
    def debug(msg): print(f"🔍 {msg}", flush=True)
    def warning(msg): print(f"⚠️  {msg}", flush=True)
    def error(msg): print(f"❌ {msg}", flush=True)
    def success(msg): print(f"✅ {msg}", flush=True)
    def section(msg): print(f"\n{'='*70}\n{msg}\n{'='*70}", flush=True)


class PIDController:
    """PID控制器"""
    
    def __init__(self, pb: float = 100.0, ti: float = 50.0, td: float = 0.0):
        self.pb = pb  # 比例带
        self.ti = ti  # 积分时间
        self.td = td  # 微分时间
        
        self.integral = 0.0
        self.last_pv = 0.0
        self.last_error = 0.0
        
    def update_params(self, pb: float, ti: float, td: float):
        """更新PID参数"""
        self.pb = pb
        self.ti = ti
        self.td = td
        info(f"🔧 PID参数已更新: Pb={pb:.1f}%, Ti={ti:.1f}s, Td={td:.1f}s")
        # 重置积分项，避免积分饱和
        self.integral = 0.0
        
    def compute(self, pv: float, sp: float, dt: float = 1.0) -> float:
        """计算PID输出"""
        error = sp - pv
        
        # 比例项
        P = 100.0 / self.pb if self.pb > 0 else 1.0
        p_term = P * error
        
        # 积分项
        if self.ti > 0:
            self.integral += error * dt
            i_term = self.integral / self.ti
        else:
            i_term = 0.0
        
        # 微分项
        if self.td > 0:
            d_term = self.td * (pv - self.last_pv) / dt
        else:
            d_term = 0.0
        
        # PID输出
        mv = 50.0 + p_term + i_term - d_term
        mv = max(0, min(100, mv))  # 限制在0-100
        
        self.last_pv = pv
        self.last_error = error
        
        return mv
    
    def reset(self):
        """重置控制器状态"""
        self.integral = 0.0
        self.last_pv = 0.0
        self.last_error = 0.0


class ProcessSimulator:
    """过程模拟器（一阶惯性+延迟）- 优化版
    
    🔧 关键改进：
    1. 支持动态调整过程参数（K, T, L）
    2. 根据扰动类型改变系统特性
    3. 产生更丰富的动态响应，让整定算法能计算出不同的参数
    """
    
    def __init__(self, K: float = 1.0, T: float = 10.0, L: float = 2.0):
        # 基础过程参数
        self.base_K = K  # 基础增益
        self.base_T = T  # 基础时间常数
        self.base_L = L  # 基础延迟
        
        # 当前过程参数（可动态调整）
        self.K = K
        self.T = T
        self.L = L
        
        self.pv = 25.0
        self.delay_buffer = []
        self.disturbance = 0.0
        
        # 🔧 新增：过程特性变化标志
        self.process_changed = False
        
    def set_process_params(self, K: float = None, T: float = None, L: float = None):
        """动态设置过程参数
        
        Args:
            K: 过程增益（影响系统响应幅度）
            T: 时间常数（影响系统响应速度）
            L: 延迟时间（影响系统滞后）
        """
        if K is not None:
            self.K = K
            info(f"🔧 过程增益变化: {self.base_K:.2f} → {K:.2f}")
        if T is not None:
            self.T = T
            info(f"🔧 时间常数变化: {self.base_T:.1f}s → {T:.1f}s")
        if L is not None:
            self.L = L
            # 调整延迟缓冲区大小
            target_size = int(self.L)
            while len(self.delay_buffer) > target_size:
                self.delay_buffer.pop(0)
            info(f"🔧 延迟时间变化: {self.base_L:.1f}s → {L:.1f}s")
        
        self.process_changed = True
        
    def reset_process_params(self):
        """重置到基础参数"""
        self.K = self.base_K
        self.T = self.base_T
        self.L = self.base_L
        self.process_changed = False
        
    def add_disturbance(self, value: float):
        """添加扰动"""
        self.disturbance = value
        
    def step(self, mv: float, sp: float, dt: float = 1.0, noise: float = 0.1) -> float:
        """模拟一步
        
        🔧 改进的过程模型：
        - 更真实的一阶惯性+延迟响应
        - 考虑MV对PV的影响
        - 动态噪声水平
        """
        # 延迟处理
        self.delay_buffer.append(mv)
        delay_steps = max(1, int(self.L / dt))
        if len(self.delay_buffer) > delay_steps:
            delayed_mv = self.delay_buffer.pop(0)
        else:
            delayed_mv = 50.0  # 初始值
        
        # 🔧 改进的一阶惯性响应
        # PV的目标值 = SP + 扰动 + MV的影响
        # MV影响：(MV - 50) * K，其中50是MV的中点
        mv_effect = (delayed_mv - 50.0) * self.K * 0.15  # 增加MV的影响系数
        target = sp + self.disturbance + mv_effect
        
        # 一阶惯性：dPV/dt = (target - PV) / T
        dpv = (target - self.pv) / self.T * dt
        self.pv += dpv
        
        # 🔧 动态噪声：过程变化时噪声增大
        noise_level = noise * (1.5 if self.process_changed else 1.0)
        self.pv += random.gauss(0, noise_level)
        
        return self.pv


class RealisticScenarioManager:
    """真实场景管理器 - 优化版
    
    核心逻辑：
    1. 稳态期间系统正常运行
    2. 发生扰动后，如果PID参数不适配，系统会持续振荡
    3. 必须更新PID参数并下发，系统才能恢复稳态
    4. 新参数应用后进入稳定期，然后回到稳态
    """
    
    def __init__(self):
        # 场景状态
        self.state = "STABLE"  # STABLE, DISTURBANCE, TUNING, STABILIZING
        self.time_in_state = 0
        self.cycle_count = 0
        
        # 配置
        self.STABLE_MIN_DURATION = 120  # 稳态最少持续120秒
        self.STABLE_MAX_DURATION = 180  # 稳态最多持续180秒
        self.STABILIZING_DURATION = 90  # 新参数稳定期90秒
        
        # 🔧 关键改进：扰动不会自动结束，必须更新参数才能恢复
        self.DISTURBANCE_WARNING_INTERVAL = 30  # 每30秒提示一次需要整定
        self.last_warning_time = 0
        
        # 当前周期的稳态持续时间（随机）
        self.current_stable_duration = random.randint(
            self.STABLE_MIN_DURATION, 
            self.STABLE_MAX_DURATION
        )
        
        # 🔧 扰动类型和强度（增强版）
        # 每种扰动会改变过程特性，导致需要不同的PID参数
        self.disturbance_types = [
            {
                "type": "load_change", 
                "severity": "high", 
                "desc": "负载突变",
                "process_params": {"K": 1.5, "T": 12.0, "L": 3.0}  # 增益增大，响应变慢
            },
            {
                "type": "setpoint_drift", 
                "severity": "medium", 
                "desc": "设定值漂移",
                "process_params": {"K": 0.8, "T": 15.0, "L": 2.5}  # 增益减小，惯性增大
            },
            {
                "type": "process_gain_change", 
                "severity": "high", 
                "desc": "过程增益变化",
                "process_params": {"K": 2.0, "T": 8.0, "L": 1.5}  # 增益大幅增加，响应变快
            },
            {
                "type": "periodic_oscillation", 
                "severity": "medium", 
                "desc": "周期性振荡",
                "process_params": {"K": 1.2, "T": 20.0, "L": 4.0}  # 惯性很大，延迟增加
            }
        ]
        self.current_disturbance = None
        self.disturbance_start_time = 0
        
        # 重整定标志
        self.retuning_triggered = False
        self.new_params_applied = False
        
        # 🔧 记录旧参数，用于判断是否真的更新了
        self.last_pid_params = None
        
    def update(self, dt: float = 1.0) -> Tuple[str, Dict]:
        """更新状态机"""
        self.time_in_state += dt
        info_dict = {}
        
        # 状态转换逻辑
        if self.state == "STABLE":
            if self.time_in_state >= self.current_stable_duration:
                # 稳态结束，进入扰动阶段
                self.state = "DISTURBANCE"
                self.time_in_state = 0
                self.last_warning_time = 0  # 重置警告时间
                self.current_disturbance = random.choice(self.disturbance_types)
                self.retuning_triggered = False
                
                section(f"🚨 周期 {self.cycle_count}: 进入扰动阶段")
                disturbance_desc = self.current_disturbance.get("desc", "未知")
                disturbance_severity = self.current_disturbance.get("severity", "medium")
                info(f"   扰动类型: {disturbance_desc}")
                info(f"   严重程度: {disturbance_severity}")
                warning(f"   ⚠️  扰动会持续存在，直到更新PID参数！")
                
                info_dict = {
                    "state_changed": True,
                    "new_state": "DISTURBANCE",
                    "disturbance_type": self.current_disturbance
                }
        
        elif self.state == "DISTURBANCE":
            # 🔧 关键改进：扰动状态下，系统会持续振荡，不会自动恢复
            # 只有当新参数应用后，才能转到TUNING状态
            
            # 定期提示需要整定（避免日志刷屏）
            if self.time_in_state - self.last_warning_time >= self.DISTURBANCE_WARNING_INTERVAL:
                self.last_warning_time = self.time_in_state
                if not self.retuning_triggered:
                    warning(f"⚡ 检测到持续非稳态！应触发重整定！(已持续 {int(self.time_in_state)}秒)")
                    info_dict["should_retune"] = True
                else:
                    warning(f"⏳ 等待新PID参数应用... (已持续 {int(self.time_in_state)}秒)")
            
            # 标记已触发重整定（用于前端显示）
            if self.time_in_state >= 30 and not self.retuning_triggered:
                self.retuning_triggered = True
            
            # 🔧 不再有固定的扰动结束时间
            # 扰动会一直持续，直到新参数应用
            # 这里不做任何状态转换，让系统持续振荡
        
        elif self.state == "TUNING":
            # 🔧 TUNING状态：新参数已应用，系统正在整定中
            # 扰动逐渐减弱，让新参数发挥作用
            if self.time_in_state >= 30:  # 整定30秒后转到稳定期
                self.state = "STABILIZING"
                self.time_in_state = 0
                
                section(f"🔄 周期 {self.cycle_count}: 新参数稳定期")
                info(f"   持续时间: {self.STABILIZING_DURATION}秒")
                
                info_dict = {
                    "state_changed": True,
                    "new_state": "STABILIZING"
                }
        
        elif self.state == "STABILIZING":
            if self.time_in_state >= self.STABILIZING_DURATION:
                # 稳定期结束，进入新的稳态周期
                self.state = "STABLE"
                self.time_in_state = 0
                self.cycle_count += 1
                self.new_params_applied = False
                
                # 随机下一个稳态持续时间
                self.current_stable_duration = random.randint(
                    self.STABLE_MIN_DURATION,
                    self.STABLE_MAX_DURATION
                )
                
                section(f"✅ 周期 {self.cycle_count}: 进入稳态阶段")
                info(f"   预计持续: {self.current_stable_duration}秒")
                
                info_dict = {
                    "state_changed": True,
                    "new_state": "STABLE",
                    "cycle_count": self.cycle_count
                }
        
        return self.state, info_dict
    
    def get_disturbance_value(self, time_in_state: float) -> float:
        """根据扰动类型生成扰动值
        
        🔧 关键改进：
        - DISTURBANCE状态：扰动持续存在，不会自动消失
        - TUNING状态：扰动逐渐减弱（新参数开始发挥作用）
        - STABILIZING/STABLE状态：无扰动
        """
        if self.state == "STABLE" or self.state == "STABILIZING":
            return 0.0
        
        # 计算衰减系数
        decay_factor = 1.0
        if self.state == "TUNING":
            # 在TUNING状态下，扰动逐渐衰减（30秒内从100%衰减到0%）
            decay_factor = max(0.0, 1.0 - time_in_state / 30.0)
        
        if self.state != "DISTURBANCE" and self.state != "TUNING":
            return 0.0
        
        if not self.current_disturbance:
            return 0.0
        
        disturbance_type = self.current_disturbance.get("type", "")
        
        # 根据扰动类型计算基础扰动值
        base_disturbance = 0.0
        
        if disturbance_type == "load_change":
            # 🔧 持续的负载变化（增强版）
            # 更大的偏差 + 更慢的振荡，确保持续非稳态
            base_offset = 5.0  # 增加基础偏差
            oscillation = 2.0 * math.sin(time_in_state * 0.08)  # 降低频率，增加幅度
            base_disturbance = base_offset + oscillation
        
        elif disturbance_type == "setpoint_drift":
            # 🔧 持续的设定值漂移（增强版）
            # 更快的累积 + 更大的振荡
            drift = min(5.0, time_in_state * 0.08)  # 更快累积，更大漂移
            oscillation = 1.5 * math.sin(time_in_state * 0.08)
            base_disturbance = drift + oscillation
        
        elif disturbance_type == "process_gain_change":
            # 🔧 过程增益突变后的持续振荡（增强版）
            # 更大的振幅，确保明显的非稳态
            amplitude = 6.0  # 增加振幅
            frequency = 0.08  # 降低频率，让振荡更持久
            base_disturbance = amplitude * math.sin(time_in_state * frequency)
        
        elif disturbance_type == "periodic_oscillation":
            # 🔧 多频率叠加的持续振荡（增强版）
            # 更大的振幅，更慢的频率
            osc1 = 4.0 * math.sin(time_in_state * 0.15)
            osc2 = 2.5 * math.sin(time_in_state * 0.25)
            osc3 = 1.5 * math.sin(time_in_state * 0.4)
            base_disturbance = osc1 + osc2 + osc3
        
        # 应用衰减系数
        return base_disturbance * decay_factor
    
    def apply_new_params(self, pb: float = None, ti: float = None, td: float = None):
        """标记新参数已应用
        
        Args:
            pb, ti, td: 新的PID参数（用于判断是否真的更新了）
        """
        current_params = (pb, ti, td) if pb is not None else None
        
        # 🔧 检查参数是否真的变化了
        if current_params and self.last_pid_params:
            params_changed = current_params != self.last_pid_params
            if not params_changed:
                warning("⚠️  PID参数未变化，但仍标记为已应用（可能参数已最优）")
        
        self.new_params_applied = True
        self.last_pid_params = current_params
        success(f"✅ 新PID参数已应用: Pb={pb}, Ti={ti}, Td={td}")


async def main():
    # 创建服务器
    server = Server()
    await server.init()
    
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    server.set_server_name("PID Realistic Scenario Server")
    
    # 设置安全策略为 None（无加密，适合开发和测试）
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
    
    # 注册命名空间
    uri = "http://pid-tuning-realistic.example.com"
    idx = await server.register_namespace(uri)
    
    objects = server.get_objects_node()
    
    section("📊 创建OPC UA节点")
    
    # 创建节点
    pv_node = await objects.add_variable(ua.NodeId(1001, idx), "PV", 25.0)
    await pv_node.set_writable()
    
    sv_node = await objects.add_variable(ua.NodeId(1005, idx), "SV", 25.0)
    await sv_node.set_writable()
    
    mv_node = await objects.add_variable(ua.NodeId(1006, idx), "MV", 50.0)
    await mv_node.set_writable()
    
    # PID参数节点（初始值与控制器一致）
    pid_pb_node = await objects.add_variable(ua.NodeId(1007, idx), "PID_Pb", 50.0)
    await pid_pb_node.set_writable()
    
    pid_ti_node = await objects.add_variable(ua.NodeId(1008, idx), "PID_Ti", 80.0)
    await pid_ti_node.set_writable()
    
    pid_td_node = await objects.add_variable(ua.NodeId(1009, idx), "PID_Td", 0.0)
    await pid_td_node.set_writable()
    
    # 状态节点（用于实时状态同步）
    # STABLE: 稳态, DISTURBANCE: 非稳态, STABILIZING: 正在稳定
    state_node = await objects.add_variable(ua.NodeId(1010, idx), "State", "STABLE")
    await state_node.set_writable()
    
    info(f"📊 State节点ID: ns={idx};i=1010")
    
    success("✅ OPC UA服务器启动成功")
    info(f"📡 端点: opc.tcp://localhost:4840/freeopcua/server/")
    info(f"🔢 命名空间: {idx}")
    
    # 初始化组件
    # 🔧 使用更强的初始参数，让MV有明显变化，便于系统辨识
    pid_controller = PIDController(pb=50.0, ti=80.0, td=0.0)
    process = ProcessSimulator(K=1.0, T=10.0, L=2.0)
    scenario = RealisticScenarioManager()
    
    section("🔄 开始真实场景模拟")
    info("场景流程: 稳态 → 非稳态 → 重整定 → 新参数稳定 → 循环")
    
    # 启动服务器
    async with server:
        time_step = 0
        last_pid_params = (50.0, 80.0, 0.0)
        
        while True:
            await asyncio.sleep(1)
            time_step += 1
            
            try:
                # 固定SV值
                FIXED_SV = 25.0
                await sv_node.write_value(FIXED_SV)
                
                # ═══════════════════════════════════════════════════════════
                # 读取外部控制信号（PID参数 + 状态节点）
                # ═══════════════════════════════════════════════════════════
                
                # 1. 读取PID参数
                current_pb = await pid_pb_node.get_value()
                current_ti = await pid_ti_node.get_value()
                current_td = await pid_td_node.get_value()
                current_params = (current_pb, current_ti, current_td)
                
                # 2. 读取状态节点
                external_state = await state_node.get_value()
                
                # ═══════════════════════════════════════════════════════════
                # 处理参数变化
                # ═══════════════════════════════════════════════════════════
                params_changed = current_params != last_pid_params
                if params_changed:
                    print(f"📊 检测到PID参数变化: {last_pid_params} → {current_params}")
                    pid_controller.update_params(current_pb, current_ti, current_td)
                    scenario.apply_new_params(current_pb, current_ti, current_td)
                    last_pid_params = current_params
                    
                    # 🔧 关键改进：如果在DISTURBANCE状态下检测到新参数，自动转到TUNING状态
                    if scenario.state == "DISTURBANCE":
                        print(f"   🔄 扰动状态下检测到新参数，转换到TUNING状态")
                        scenario.state = "TUNING"
                        scenario.time_in_state = 0
                        await state_node.write_value("TUNING")
                
                # ═══════════════════════════════════════════════════════════
                # 处理状态变化
                # ═══════════════════════════════════════════════════════════
                state_changed = external_state != scenario.state
                if state_changed:
                    print(f"🔄 检测到外部状态变化: {scenario.state} → {external_state}")
                    old_state = scenario.state
                    scenario.state = external_state
                    scenario.time_in_state = 0  # 重置状态计时
                    
                    # 处理整定相关状态：TUNING或STABILIZING
                    if external_state in ["TUNING", "STABILIZING"]:
                        # 标记参数已应用（无论参数是否实际变化）
                        # 原因：整定可能计算出相同参数（说明当前参数已最优）
                        scenario.new_params_applied = True
                        scenario.retuning_triggered = False
                        print(f"   ✅ 整定状态已确认，标记参数已应用")
                        if not params_changed:
                            print(f"   💡 参数未变化，说明当前参数已接近最优")
                    
                    # 处理从DISTURBANCE的退出
                    elif old_state == "DISTURBANCE":
                        # 确保退出扰动状态时参数标志被正确设置
                        if not scenario.new_params_applied:
                            scenario.new_params_applied = True
                            print(f"   ✅ 退出扰动状态，标记参数已应用")
                
                # 更新场景状态
                state, state_info = scenario.update(dt=1.0)
                
                # 🔧 应用过程参数变化（根据扰动类型）
                if state_info.get("state_changed"):
                    new_state = state_info.get("new_state")
                    
                    if new_state == "DISTURBANCE":
                        # 进入扰动状态：改变过程特性
                        disturbance_type = scenario.current_disturbance
                        if disturbance_type:
                            process_params = disturbance_type.get("process_params", {})
                            process.set_process_params(
                                K=process_params.get("K"),
                                T=process_params.get("T"),
                                L=process_params.get("L")
                            )
                            section(f"🔧 过程特性已改变")
                            info(f"   新的系统特性: K={process.K:.2f}, T={process.T:.1f}s, L={process.L:.1f}s")
                            info(f"   💡 旧的PID参数将不再适配，需要重新整定")
                    
                    elif new_state == "STABLE":
                        # 回到稳态：恢复基础过程参数
                        process.reset_process_params()
                        info(f"🔧 过程特性已恢复到基础值")
                
                # 🔧 只在状态变化时写入状态节点（避免覆盖外部控制）
                if state != external_state:
                    await state_node.write_value(state)
                    print(f"   📡 内部状态变化: {external_state} → {state}")
                
                # 生成扰动
                disturbance = scenario.get_disturbance_value(scenario.time_in_state)
                process.add_disturbance(disturbance)
                
                # PID控制
                current_pv = process.pv
                mv = pid_controller.compute(current_pv, FIXED_SV, dt=1.0)
                # 确保MV是Python原生float类型
                await mv_node.write_value(float(mv))
                
                # 过程响应
                noise_level = 0.3 if state == "DISTURBANCE" else 0.1
                new_pv = process.step(mv, FIXED_SV, dt=1.0, noise=noise_level)
                # 确保PV是Python原生float类型
                await pv_node.write_value(float(new_pv))
                
                # 状态输出（每10秒）
                if time_step % 10 == 0:
                    state_icons = {
                        "STABLE": "✅",
                        "DISTURBANCE": "⚠️",
                        "STABILIZING": "🔄"
                    }
                    icon = state_icons.get(state, "❓")
                    
                    info(f"[{datetime.now().strftime('%H:%M:%S')}] {icon} {state:12s} | "
                         f"PV={new_pv:.2f}, SV={FIXED_SV:.2f}, MV={mv:.1f}% | "
                         f"PID({current_pb:.0f}/{current_ti:.0f}/{current_td:.0f}) | "
                         f"时长={scenario.time_in_state:.0f}s")
                
                # 提示重整定
                if state_info.get("should_retune"):
                    warning("=" * 70)
                    warning("⚡ 系统检测到持续非稳态！")
                    warning("💡 建议: 在web界面中对此回路执行重整定")
                    warning("📊 重整定后，新PID参数将自动应用到OPC UA")
                    warning("=" * 70)
                
            except Exception as e:
                error(f"模拟错误: {str(e)}")
                import traceback
                traceback.print_exc()
                continue


if __name__ == "__main__":
    section("🚀 启动OPC UA真实场景模拟服务器")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n")
        section("⏹️  服务器已停止")
