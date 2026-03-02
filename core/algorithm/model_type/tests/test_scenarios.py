"""
测试场景定义模块

包含 PID 整定算法测试的场景配置。每个场景定义了：
- process_original: 原始过程参数 {K, T1, L}
- process_changed: 变化后的过程参数（导致振荡）
- original_pid: 原始 PID 参数 {Kp, Ki, Kd}
- loop_type: 回路类型 ('flow', 'temperature', 'pressure', 'level')
- noise_std: 可选，噪声标准差

设计原则：Old PID 必须在变化后的系统上振荡，算法需要重新整定。
"""

# ============================================================
# 多场景批量测试
# ============================================================

# 定义多种测试场景（设计原则：Old PID 必须在变化后的系统上振荡）
TEST_SCENARIOS = [
    # ========== 典型振荡场景（Old PID 必须振荡）==========
    {
        'name': 'Severe Gain Increase',
        'description': '增益大幅增加（K: 1→4）- Old PID 必振荡',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 4.00, 'T1': 2.5, 'L': 1.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Aggressive PID + Gain Up',
        'description': '激进PID + 增益翻倍 - 典型振荡',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 2.20, 'T1': 3.7, 'L': 1.2},  # 稍微减小变化
        'original_pid': {'Kp': 1.10, 'Ki': 0.0600, 'Kd': 0.0},  # 稍微减小激进程度
        'loop_type': 'flow',
    },
    {
        'name': 'Large Delay Increase',
        'description': '滞后大幅增加（L: 2→12）- 滞后敏感',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 8.0},
        'process_changed': {'K': 1.50, 'T1': 100.0, 'L': 12.0},
        'original_pid': {'Kp': 0.70, 'Ki': 0.0280, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    # ========== 不同回路类型 ==========
    {
        'name': 'Temperature Loop Oscillation',
        'description': '温度回路振荡（增益+滞后同时增加）',
        'process_original': {'K': 0.80, 'T1': 60.0, 'L': 20.0},
        'process_changed': {'K': 2.50, 'T1': 140.0, 'L': 12.0},  # 更大的变化
        'original_pid': {'Kp': 0.70, 'Ki': 0.0280, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'temperature',
    },
    {
        'name': 'Pressure Loop Oscillation',
        'description': '压力回路振荡（快速+高增益）',
        'process_original': {'K': 1.20, 'T1': 20.0, 'L': 1.0},
        'process_changed': {'K': 3.00, 'T1': 15.0, 'L': 5.0},
        'original_pid': {'Kp': 1.50, 'Ki': 2.250, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Level Loop Oscillation',
        'description': '液位回路振荡（积分特性+增益增加）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 6.0},
        'process_changed': {'K': 0.30, 'T1': 80.0, 'L': 8.0},  # 更大的增益变化
        'original_pid': {'Kp': 1.50, 'Ki': 0.750, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'level',
    },
    # ========== 数据质量挑战 ==========
    {
        'name': 'High Noise Oscillation',
        'description': '高噪声环境下的振荡',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 3.00, 'T1': 3.0, 'L': 1.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'noise_std': 1.0,
        'loop_type': 'flow',
    },
    {
        'name': 'Moderate Oscillation',
        'description': '中等振荡（适中的系统变化）',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 2.50, 'T1': 3.0, 'L': 1.5},  # 更大的变化
        'original_pid': {'Kp': 1.10, 'Ki': 0.0500, 'Kd': 0.0},  # 更激进的PID
        'noise_std': 0.3,
        'loop_type': 'flow',
    },
    # ========== 边界情况 ==========
    {
        'name': 'Fast System Oscillation',
        'description': '快速系统振荡（T1小+高增益）',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 3.50, 'T1': 2.0, 'L': 1.2},  # 适中的快速系统
        'original_pid': {'Kp': 1.10, 'Ki': 0.0600, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Slow System Oscillation',
        'description': '慢速系统振荡（大滞后+激进PID）',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 8.0},
        'process_changed': {'K': 2.50, 'T1': 200.0, 'L': 12.0},
        'original_pid': {'Kp': 0.70, 'Ki': 0.0280, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    # ========== 新增场景：更多边界情况 ==========
    {
        'name': 'Very High Gain',
        'description': '极高增益（K: 1→5）- 极端振荡',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 5.00, 'T1': 2.0, 'L': 1.5},  # 更激进的变化
        'original_pid': {'Kp': 1.25, 'Ki': 0.0600, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'flow',
    },
    {
        'name': 'Small Gain Change',
        'description': '小幅增益变化（K: 1→1.8）- 轻微振荡',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 1.80, 'T1': 4.2, 'L': 1.0},
        'original_pid': {'Kp': 1.10, 'Ki': 0.0600, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Delay Dominant',
        'description': '滞后主导（L/T1 > 0.5）',
        'process_original': {'K': 1.00, 'T1': 80.0, 'L': 8.0},
        'process_changed': {'K': 2.00, 'T1': 60.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.525, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Time Constant Dominant',
        'description': '时间常数主导（L/T1 < 0.1）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 4.0},
        'process_changed': {'K': 0.36, 'T1': 80.0, 'L': 6.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.600, 'Kd': 0.0},
        'loop_type': 'level',
    },
    # ========== 新增场景：工业常见情况 ==========
    {
        'name': 'Catalyst Deactivation',
        'description': '催化剂失活后恢复（增益突增）',
        'process_original': {'K': 0.50, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 2.50, 'T1': 100.0, 'L': 32.0},  # 更大的增益变化
        'original_pid': {'Kp': 1.22, 'Ki': 0.0420, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'temperature',
    },
    {
        'name': 'Valve Aging',
        'description': '阀门老化（滞后增加+增益变化）',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.0},
        'process_changed': {'K': 1.80, 'T1': 5.0, 'L': 2.5},  # 更大的滞后
        'original_pid': {'Kp': 1.40, 'Ki': 0.0750, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'flow',
    },
    {
        'name': 'Heat Exchanger Fouling',
        'description': '换热器结垢（增益+滞后增加）',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 20.0},
        'process_changed': {'K': 2.00, 'T1': 180.0, 'L': 12.0},  # 增益增加+滞后增加
        'original_pid': {'Kp': 0.70, 'Ki': 0.0350, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'temperature',
    },
    {
        'name': 'Product Grade Change',
        'description': '产品牌号切换（系统特性突变）',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.5},
        'process_changed': {'K': 2.80, 'T1': 3.7, 'L': 1.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Compressor Surge',
        'description': '压缩机喘振（压力回路快速振荡）',
        'process_original': {'K': 1.50, 'T1': 15.0, 'L': 1.0},
        'process_changed': {'K': 4.00, 'T1': 8.0, 'L': 3.0},  # 更快的系统
        'original_pid': {'Kp': 1.50, 'Ki': 2.250, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'pressure',
    },
    {
        'name': 'Tank Level Sloshing',
        'description': '储罐液位晃动（液位回路振荡）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 0.70, 'T1': 80.0, 'L': 10.0},  # 更大的变化
        'original_pid': {'Kp': 1.50, 'Ki': 0.450, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'level',
    },
    # ========== 新增：更多实际工业场景 ==========
    {
        'name': 'Gain Ratio Change',
        'description': '增益比变化（小增益变大增益）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 6.0},  # 小增益
        'process_changed': {'K': 0.70, 'T1': 80.0, 'L': 6.0},   # 增益变大约3倍
        'original_pid': {'Kp': 1.50, 'Ki': 0.540, 'Kd': 0.0},    # 针对小增益整定的PID
        'loop_type': 'level',
    },
    {
        'name': 'Load Disturbance',
        'description': '负荷扰动（进料流量突变）',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.5},
        'process_changed': {'K': 2.50, 'T1': 3.3, 'L': 1.2},
        'original_pid': {'Kp': 1.26, 'Ki': 0.0560, 'Kd': 0.0},
        'noise_std': 0.5,  # 中等噪声
        'loop_type': 'flow',
    },
    {
        'name': 'Sensor Drift',
        'description': '传感器漂移（测量偏差）',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 8.0},
        'process_changed': {'K': 1.30, 'T1': 112.0, 'L': 16.0},  # 小幅变化
        'original_pid': {'Kp': 0.88, 'Ki': 0.0420, 'Kd': 0.0},  # 激进PID
        'loop_type': 'temperature',
    },
    {
        'name': 'Cascade Inner Loop',
        'description': '串级内环（快速响应要求）',
        'process_original': {'K': 1.50, 'T1': 10.0, 'L': 0.5},
        'process_changed': {'K': 3.00, 'T1': 8.0, 'L': 1.0},
        'original_pid': {'Kp': 1.40, 'Ki': 0.1400, 'Kd': 0.0},  # 快速响应
        'loop_type': 'flow',
    },
    {
        'name': 'Batch Process Transition',
        'description': '间歇过程切换（反应阶段变化）',
        'process_original': {'K': 0.80, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 2.20, 'T1': 100.0, 'L': 32.0},
        'original_pid': {'Kp': 0.88, 'Ki': 0.0350, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Startup Condition',
        'description': '开车工况（冷态到热态）',
        'process_original': {'K': 0.50, 'T1': 60.0, 'L': 10.0},  # 冷态：慢
        'process_changed': {'K': 1.80, 'T1': 120.0, 'L': 20.0},   # 热态：快
        'original_pid': {'Kp': 1.05, 'Ki': 0.0280, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Nonlinear Valve',
        'description': '非线性阀门特性（等百分比阀）',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.0},
        'process_changed': {'K': 2.00, 'T1': 3.7, 'L': 1.2},  # 适中的变化
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Interacting Loops',
        'description': '耦合回路（温度-压力耦合）',
        'process_original': {'K': 1.00, 'T1': 140.0, 'L': 16.0},
        'process_changed': {'K': 1.80, 'T1': 112.0, 'L': 28.0},
        'original_pid': {'Kp': 0.70, 'Ki': 0.0350, 'Kd': 0.0},
        'noise_std': 0.4,  # 耦合带来的扰动
        'loop_type': 'temperature',
    },
    # ========== 新增场景：特殊系统类型 ==========
    {
        'name': 'Reverse Action Cooling',
        'description': '反向作用系统（制冷回路，MV增→PV减）',
        # 反向作用：K为负，MV增加导致PV减少（如制冷阀开大→温度下降）
        # 对于 K < 0 的系统，需要 Kp < 0 才能形成负反馈
        'process_original': {'K': -1.00, 'T1': 120.0, 'L': 12.0},
        'process_changed': {'K': -2.50, 'T1': 72.0, 'L': 24.0},  # 增益变大+滞后增加
        'original_pid': {'Kp': -0.75, 'Ki': 0.0400, 'Kd': 0.0},  # 负Kp/Ki（反向作用PID）
        'loop_type': 'temperature',
    },
    {
        'name': 'Integrating Process',
        'description': '积分过程（液位控制，增益大幅变化）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 6.0},
        'process_changed': {'K': 0.70, 'T1': 80.0, 'L': 6.0},  # 增益变化3倍+，确保振荡
        'original_pid': {'Kp': 1.50, 'Ki': 0.450, 'Kd': 0.0},  # 更激进的PID
        'loop_type': 'level',
    },
    {
        'name': 'Underdamped System',
        'description': '欠阻尼二阶系统（自带振荡特性）',
        'process_original': {'K': 1.00, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 2.50, 'T1': 12.0, 'L': 4.0},  # 更快+更高增益
        'original_pid': {'Kp': 1.80, 'Ki': 0.1000, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    # ========== 新增场景：极端条件 ==========
    {
        'name': 'Extreme Delay',
        'description': '大滞后系统（L/T1 接近 1）',
        'process_original': {'K': 1.00, 'T1': 80.0, 'L': 20.0},
        'process_changed': {'K': 1.80, 'T1': 60.0, 'L': 12.0},  # L/T1 = 0.8，更合理
        'original_pid': {'Kp': 1.50, 'Ki': 0.315, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Very Small Gain',
        'description': '小增益系统（K < 0.5）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 8.0},  # 增大K使其更可辨识
        'process_changed': {'K': 0.30, 'T1': 80.0, 'L': 7.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.900, 'Kd': 0.0},  # 适中的高Kp
        'loop_type': 'level',
    },
    {
        'name': 'Very Large Gain',
        'description': '极大增益系统（K > 5）',
        'process_original': {'K': 3.00, 'T1': 3.3, 'L': 1.0},
        'process_changed': {'K': 8.00, 'T1': 2.0, 'L': 1.0},
        'original_pid': {'Kp': 0.56, 'Ki': 0.0350, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Multi-mode Extreme',
        'description': '多模态极端变化（参数变化>5倍）',
        'process_original': {'K': 0.50, 'T1': 60.0, 'L': 32.0},
        'process_changed': {'K': 3.50, 'T1': 48.0, 'L': 12.0},  # 极端变化
        'original_pid': {'Kp': 1.22, 'Ki': 0.0350, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    # ========== 新增场景：噪声与扰动 ==========
    {
        'name': 'Very High Noise',
        'description': '极高噪声环境（noise_std=1.5）',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.5},
        'process_changed': {'K': 2.50, 'T1': 3.3, 'L': 1.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'noise_std': 1.5,
        'loop_type': 'flow',
    },
    {
        'name': 'Low Noise Precision',
        'description': '低噪声精密控制（noise_std=0.05）',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 8.0},
        'process_changed': {'K': 2.20, 'T1': 72.0, 'L': 20.0},
        'original_pid': {'Kp': 0.88, 'Ki': 0.0420, 'Kd': 0.0},
        'noise_std': 0.05,
        'loop_type': 'temperature',
    },
    # ========== 新增场景：工业特殊情况 ==========
    {
        'name': 'Reactor Runaway',
        'description': '反应器飞温（增益大幅增加）',
        'process_original': {'K': 1.00, 'T1': 140.0, 'L': 16.0},
        'process_changed': {'K': 4.00, 'T1': 72.0, 'L': 24.0},  # 增益变化4倍，更合理
        'original_pid': {'Kp': 0.70, 'Ki': 0.0280, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Distillation Column',
        'description': '精馏塔温度控制（大滞后+耦合）',
        'process_original': {'K': 0.80, 'T1': 200.0, 'L': 10.0},
        'process_changed': {'K': 1.80, 'T1': 140.0, 'L': 15.0},
        'original_pid': {'Kp': 0.70, 'Ki': 0.0210, 'Kd': 0.0},
        'noise_std': 0.3,
        'loop_type': 'temperature',
    },
    {
        'name': 'Furnace Temperature',
        'description': '加热炉温度（慢响应+滞后）',
        'process_original': {'K': 0.80, 'T1': 200.0, 'L': 32.0},  # 减小T1和L
        'process_changed': {'K': 1.80, 'T1': 140.0, 'L': 12.0},
        'original_pid': {'Kp': 0.88, 'Ki': 0.0210, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'pH Control',
        'description': 'pH控制（高度非线性+快速）',
        'process_original': {'K': 2.00, 'T1': 10.0, 'L': 0.5},
        'process_changed': {'K': 5.00, 'T1': 8.0, 'L': 1.0},  # pH曲线陡峭区
        'original_pid': {'Kp': 0.70, 'Ki': 0.1050, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Steam Header Pressure',
        'description': '蒸汽母管压力（多源扰动）',
        'process_original': {'K': 1.50, 'T1': 15.0, 'L': 2.0},
        'process_changed': {'K': 3.00, 'T1': 10.0, 'L': 4.0},
        'original_pid': {'Kp': 2.00, 'Ki': 0.1500, 'Kd': 0.0},
        'noise_std': 0.6,
        'loop_type': 'pressure',
    },
    {
        'name': 'Blending Control',
        'description': '调合控制（多组分混合）',
        'process_original': {'K': 1.20, 'T1': 3.3, 'L': 1.5},
        'process_changed': {'K': 2.50, 'T1': 2.5, 'L': 1.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    
    # ========== 极端挑战场景（测试算法鲁棒性边界）==========
    {
        'name': 'Ultra Fast Flow',
        'description': '超快流量回路 - 极小时间常数',
        'process_original': {'K': 1.00, 'T1': 3.0, 'L': 0.3},
        'process_changed': {'K': 2.00, 'T1': 2.0, 'L': 0.8},
        'original_pid': {'Kp': 4.00, 'Ki': 0.2500, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Very Slow Temperature',
        'description': '极慢温度回路 - 大时间常数',
        'process_original': {'K': 0.60, 'T1': 200.0, 'L': 30.0},
        'process_changed': {'K': 1.00, 'T1': 180.0, 'L': 50.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0025, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'High Noise Flow',
        'description': '高噪声流量回路 - 测噪声鲁棒性',
        'process_original': {'K': 1.00, 'T1': 3.3, 'L': 1.5},
        'process_changed': {'K': 1.80, 'T1': 3.0, 'L': 1.5},
        'original_pid': {'Kp': 1.50, 'Ki': 0.0500, 'Kd': 0.0},
        'noise_std': 0.8,
        'loop_type': 'flow',
    },
    {
        'name': 'Extreme Gain Change',
        'description': '极高增益变化 - K从1变到6',
        'process_original': {'K': 1.00, 'T1': 5.0, 'L': 1.5},
        'process_changed': {'K': 6.00, 'T1': 4.2, 'L': 2.0},
        'original_pid': {'Kp': 1.25, 'Ki': 0.0400, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Very Large Delay',
        'description': '极大滞后 - L/T1 接近1',
        'process_original': {'K': 1.00, 'T1': 80.0, 'L': 20.0},
        'process_changed': {'K': 1.20, 'T1': 72.0, 'L': 15.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.263, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Integrating Level',
        'description': '积分液位回路 - 大时间常数模拟积分',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 0.40, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Reverse Acting Flow',
        'description': '反向作用流量 - 负增益系统',
        'process_original': {'K': -1.00, 'T1': 4.2, 'L': 1.0},
        'process_changed': {'K': -2.00, 'T1': 3.3, 'L': 1.2},
        'original_pid': {'Kp': -1.50, 'Ki': 0.0500, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Fast Pressure Disturbance',
        'description': '快速压力扰动 - 小时间常数',
        'process_original': {'K': 1.20, 'T1': 8.0, 'L': 1.0},
        'process_changed': {'K': 2.50, 'T1': 6.0, 'L': 3.0},
        'original_pid': {'Kp': 5.00, 'Ki': 0.3000, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Coupled Temperature',
        'description': '强耦合温度回路 - 增益和滞后同时变化',
        'process_original': {'K': 1.00, 'T1': 60.0, 'L': 32.0},
        'process_changed': {'K': 3.00, 'T1': 160.0, 'L': 20.0},
        'original_pid': {'Kp': 0.60, 'Ki': 0.0075, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Low Gain System',
        'description': '小增益系统 - K < 0.5',
        'process_original': {'K': 0.30, 'T1': 6.7, 'L': 1.2},
        'process_changed': {'K': 0.60, 'T1': 5.8, 'L': 2.5},
        'original_pid': {'Kp': 5.00, 'Ki': 0.1000, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'High Gain Temperature',
        'description': '高增益温度系统 - K > 3',
        'process_original': {'K': 3.00, 'T1': 200.0, 'L': 20.0},
        'process_changed': {'K': 5.00, 'T1': 180.0, 'L': 12.0},
        'original_pid': {'Kp': 0.25, 'Ki': 0.0040, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Minimal Delay',
        'description': '极小滞后 - L接近0',
        'process_original': {'K': 1.00, 'T1': 3.3, 'L': 0.3},
        'process_changed': {'K': 2.00, 'T1': 3.0, 'L': 1.0},
        'original_pid': {'Kp': 2.00, 'Ki': 0.0750, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    
    # ========== 增益梯度测试 (Gain Gradient) ==========
    {
        'name': 'Gain Gradient K=2 Flow',
        'description': '增益梯度测试 - K=2 流量回路',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 2.00, 'T1': 3.7, 'L': 1.2},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Gain Gradient K=3 Flow',
        'description': '增益梯度测试 - K=3 流量回路',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 3.00, 'T1': 3.7, 'L': 1.2},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Gain Gradient K=4 Flow',
        'description': '增益梯度测试 - K=4 流量回路',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 4.00, 'T1': 3.7, 'L': 1.2},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Gain Gradient K=5 Flow',
        'description': '增益梯度测试 - K=5 流量回路',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 5.00, 'T1': 3.7, 'L': 1.2},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Gain Gradient K=7 Flow',
        'description': '增益梯度测试 - K=7 极高增益流量',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 7.00, 'T1': 3.7, 'L': 1.2},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Gain Gradient K=3 Temp',
        'description': '增益梯度测试 - K=3 温度回路',
        'process_original': {'K': 1.00, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 3.00, 'T1': 140.0, 'L': 10.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0250, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Gain Gradient K=4 Temp',
        'description': '增益梯度测试 - K=4 温度回路',
        'process_original': {'K': 1.00, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 4.00, 'T1': 140.0, 'L': 10.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0250, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Gain Gradient K=6 Temp',
        'description': '增益梯度测试 - K=6 高增益温度',
        'process_original': {'K': 1.00, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 6.00, 'T1': 140.0, 'L': 10.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0250, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    
    # ========== 时间常数梯度测试 (Time Constant Gradient) ==========
    {
        'name': 'T1 Gradient T1=30 Flow',
        'description': '时间常数梯度 - T1=30s 流量',
        'process_original': {'K': 1.00, 'T1': 2.5, 'L': 1.0},
        'process_changed': {'K': 2.00, 'T1': 5.0, 'L': 1.2},
        'original_pid': {'Kp': 1.25, 'Ki': 0.0600, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'T1 Gradient T1=60 Temp',
        'description': '时间常数梯度 - T1=60s 温度',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 12.0},
        'process_changed': {'K': 2.00, 'T1': 60.0, 'L': 10.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0250, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'T1 Gradient T1=100 Temp',
        'description': '时间常数梯度 - T1=100s 慢温度',
        'process_original': {'K': 1.00, 'T1': 160.0, 'L': 20.0},
        'process_changed': {'K': 1.50, 'T1': 100.0, 'L': 20.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'T1 Gradient T1=80 Level',
        'description': '时间常数梯度 - T1=80s 液位',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 0.50, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.225, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'T1 Gradient T1=120 Level',
        'description': '时间常数梯度 - T1=120s 极慢液位',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 8.0},
        'process_changed': {'K': 0.40, 'T1': 120.0, 'L': 12.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    
    # ========== 滞后梯度测试 (Delay Gradient) ==========
    {
        'name': 'Delay Gradient L=8 Flow',
        'description': '滞后梯度 - L=8s 流量',
        'process_original': {'K': 1.00, 'T1': 3.3, 'L': 1.0},
        'process_changed': {'K': 2.00, 'T1': 3.0, 'L': 2.0},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Delay Gradient L=15 Temp',
        'description': '滞后梯度 - L=15s 温度',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 12.0},
        'process_changed': {'K': 1.80, 'T1': 112.0, 'L': 15.0},
        'original_pid': {'Kp': 0.75, 'Ki': 0.0250, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Delay Gradient L=20 Temp',
        'description': '滞后梯度 - L=20s 大滞后温度',
        'process_original': {'K': 1.00, 'T1': 140.0, 'L': 20.0},
        'process_changed': {'K': 1.50, 'T1': 128.0, 'L': 20.0},
        'original_pid': {'Kp': 0.60, 'Ki': 0.0150, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Delay Gradient L=25 Temp',
        'description': '滞后梯度 - L=25s 极大滞后',
        'process_original': {'K': 1.00, 'T1': 160.0, 'L': 32.0},
        'process_changed': {'K': 1.30, 'T1': 152.0, 'L': 25.0},
        'original_pid': {'Kp': 0.50, 'Ki': 0.0100, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    
    # ========== 组合变化梯度 (Combined Changes) ==========
    {
        'name': 'Combined K=3 L=10 Flow',
        'description': '组合变化 - K=3 L=10 流量',
        'process_original': {'K': 1.00, 'T1': 4.2, 'L': 1.5},
        'process_changed': {'K': 3.00, 'T1': 3.7, 'L': 2.5},
        'original_pid': {'Kp': 1.40, 'Ki': 0.0700, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Combined K=4 T1=50 Temp',
        'description': '组合变化 - K=4 T1=50 温度',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 20.0},
        'process_changed': {'K': 4.00, 'T1': 200.0, 'L': 12.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.375, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Combined K=2.5 T1=70 Level',
        'description': '组合变化 - K=2.5 T1=70 液位',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 0.80, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.225, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Combined K=3 T1=40 Pressure',
        'description': '组合变化 - K=3 T1=40 压力',
        'process_original': {'K': 1.50, 'T1': 15.0, 'L': 3.0},
        'process_changed': {'K': 3.00, 'T1': 40.0, 'L': 8.0},
        'original_pid': {'Kp': 1.80, 'Ki': 0.0800, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    
    # ========== 边界条件测试 (Boundary Conditions) ==========
    {
        'name': 'Boundary Small K=0.5',
        'description': '边界测试 - 极小增益 K=0.5',
        'process_original': {'K': 0.30, 'T1': 3.3, 'L': 1.5},
        'process_changed': {'K': 0.50, 'T1': 4.2, 'L': 1.2},
        'original_pid': {'Kp': 2.50, 'Ki': 0.1000, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Boundary Large K=10',
        'description': '边界测试 - 超大增益 K=10',
        'process_original': {'K': 2.00, 'T1': 2.5, 'L': 1.5},
        'process_changed': {'K': 10.00, 'T1': 2.0, 'L': 1.2},
        'original_pid': {'Kp': 0.70, 'Ki': 0.0350, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Boundary Very Fast T1=5',
        'description': '边界测试 - 极快系统 T1=5s',
        'process_original': {'K': 1.00, 'T1': 3.0, 'L': 1.0},
        'process_changed': {'K': 2.50, 'T1': 5.0, 'L': 2.0},
        'original_pid': {'Kp': 3.00, 'Ki': 0.3000, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Boundary Very Slow T1=250',
        'description': '边界测试 - 极慢系统 T1=250s',
        'process_original': {'K': 0.80, 'T1': 120.0, 'L': 20.0},
        'process_changed': {'K': 1.00, 'T1': 250.0, 'L': 60.0},
        'original_pid': {'Kp': 0.25, 'Ki': 0.0025, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    # ========== 鲁棒性极限测试 (Robustness Limit) ==========
    {
        'name': 'Robustness - Dominant Delay',
        'description': '鲁棒性测试 - 极度滞后主导 (L/T=10)',
        'process_original': {'K': 1.00, 'T1': 20.0, 'L': 20.0},
        'process_changed': {'K': 1.50, 'T1': 20.0, 'L': 50.0},
        'original_pid': {'Kp': 0.25, 'Ki': 0.0100, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Robustness - Massive Gain Jump',
        'description': '鲁棒性测试 - 增益巨幅跳变 (20倍)',
        'process_original': {'K': 1.00, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 20.00, 'T1': 15.0, 'L': 5.0},
        'original_pid': {'Kp': 2.00, 'Ki': 0.1000, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Robustness - High Noise Delay',
        'description': '鲁棒性测试 - 高噪声 + 大滞后',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 10.0},
        'process_changed': {'K': 2.00, 'T1': 100.0, 'L': 20.0},
        'original_pid': {'Kp': 0.50, 'Ki': 0.0250, 'Kd': 0.0},
        'noise_std': 2.0,
        'loop_type': 'temperature',
    },
    {
        'name': 'Robustness - Inverse High Gain',
        'description': '鲁棒性测试 - 反向高增益',
        'process_original': {'K': -1.00, 'T1': 3.3, 'L': 1.0},
        'process_changed': {'K': -5.00, 'T1': 2.5, 'L': 1.2},
        'original_pid': {'Kp': -1.50, 'Ki': 0.525, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Robustness - Near Integrating',
        'description': '鲁棒性测试 - 近似积分过程 (大K大T)',
        'process_original': {'K': 1.67, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 3.33, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Robustness - Low SNR',
        'description': '鲁棒性测试 - 低信噪比 (小增益+大噪声)',
        'process_original': {'K': 0.30, 'T1': 3.3, 'L': 1.5},
        'process_changed': {'K': 0.60, 'T1': 2.5, 'L': 1.5},  # 增加增益使其更易振荡
        'original_pid': {'Kp': 4.00, 'Ki': 0.1500, 'Kd': 0.0},  # 更激进的PID导致振荡
        'noise_std': 0.4,  # 稍微降低噪声以保证可辨识性
        'loop_type': 'flow',
    },
    # ========== 更多常见工业扰动场景 (More Common Industrial Disturbances) ==========
    {
        'name': 'Industry - Boiler Swell/Shrink',
        'description': '工业场景 - 锅炉虚假水位 (反向响应)',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': -1.50, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.375, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Industry - Filter Clogging',
        'description': '工业场景 - 过滤器堵塞 (阻力增加，响应变慢)',
        'process_original': {'K': 1.00, 'T1': 10.0, 'L': 0.5},
        'process_changed': {'K': 0.80, 'T1': 5.0, 'L': 1.5},
        'original_pid': {'Kp': 1.50, 'Ki': 0.1500, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Industry - Thermowell Lag',
        'description': '工业场景 - 套管结垢导致测量滞后',
        'process_original': {'K': 1.00, 'T1': 120.0, 'L': 20.0},
        'process_changed': {'K': 1.00, 'T1': 60.0, 'L': 15.0},
        'original_pid': {'Kp': 0.88, 'Ki': 0.0280, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Industry - Multi-Pump Startup',
        'description': '工业场景 - 多泵并联启动 (增益倍增)',
        'process_original': {'K': 0.80, 'T1': 15.0, 'L': 2.0},
        'process_changed': {'K': 2.00, 'T1': 12.0, 'L': 3.0},
        'original_pid': {'Kp': 2.50, 'Ki': 0.1500, 'Kd': 0.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Industry - pH Buffer Loss',
        'description': '工业场景 - pH缓冲能力丧失 (高非线性，高增益)',
        'process_original': {'K': 1.00, 'T1': 3.3, 'L': 1.2},
        'process_changed': {'K': 8.00, 'T1': 10.0, 'L': 1.2},
        'original_pid': {'Kp': 1.05, 'Ki': 0.0350, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Industry - HEX Bypass Open',
        'description': '工业场景 - 换热器旁路打开 (控制效能下降)',
        'process_original': {'K': 2.00, 'T1': 160.0, 'L': 32.0},
        'process_changed': {'K': 0.60, 'T1': 200.0, 'L': 10.0},
        'original_pid': {'Kp': 0.25, 'Ki': 0.0100, 'Kd': 0.0},
        'loop_type': 'temperature',
    },
    
    # ========== 极端场景 (EXTREME Scenarios) ==========
    # 组合多个高风险因素，测试算法极限能力
    {
        'name': 'Extreme - Triple Challenge',
        'description': '极端场景 - 大滞后(L/T=2.0) + 增益x10 + 高噪声',
        'process_original': {'K': 0.3, 'T1': 20.0, 'L': 25.0},
        'process_changed': {'K': 3.0, 'T1': 15.0, 'L': 30.0},
        'original_pid': {'Kp': 4.0, 'Ki': 0.1, 'Kd': 0.0},
        'noise_std': 1.2,
        'loop_type': 'temperature',
    },
    {
        'name': 'Extreme - Slow Delay Gain',
        'description': '极端场景 - 极慢T1=200s + 大滞后 + 增益x8',
        'process_original': {'K': 0.50, 'T1': 80.0, 'L': 40.0},
        'process_changed': {'K': 4.00, 'T1': 80.0, 'L': 80.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'noise_std': 0.6,
        'loop_type': 'level',
    },
    {
        'name': 'Extreme - Inverse Noisy',
        'description': '极端场景 - 反向响应(K变负) + 高噪声 + 增益x5',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 8.0},
        'process_changed': {'K': -5.00, 'T1': 100.0, 'L': 15.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.750, 'Kd': 0.0},
        'noise_std': 1.5,
        'loop_type': 'level',
    },
    {
        'name': 'Extreme - Dominant Delay Slow',
        'description': '极端场景 - 滞后主导(L/T=2.0) + 极慢T1=150s',
        'process_original': {'K': 0.8, 'T1': 80.0, 'L': 50.0},
        'process_changed': {'K': 1.5, 'T1': 150.0, 'L': 300.0},
        'original_pid': {'Kp': 1.0, 'Ki': 0.01, 'Kd': 0.0},
        'noise_std': 0.8,
        'loop_type': 'temperature',
    },
    
    # ========== 阀门特性问题场景 (Valve Characteristics) ==========
    {
        'name': 'Valve Deadband Flow',
        'description': '阀门死区 - MV小幅变化时PV不响应',
        # 死区会导致控制器持续积分，最终大幅动作后振荡
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 2.0, 'T1': 18.0, 'L': 5.0},
        'original_pid': {'Kp': 3.0, 'Ki': 0.15, 'Kd': 0.0},  # 高积分试图克服死区
        'loop_type': 'flow',
        'valve_deadband': 5.0,  # 5% 死区
    },
    {
        'name': 'Valve Stiction Flow',
        'description': '阀门粘滞 - MV反向时PV滞后',
        # 粘滞会导致周期性振荡（阀门卡住后突然移动）
        'process_original': {'K': 1.0, 'T1': 25.0, 'L': 3.0},
        'process_changed': {'K': 1.8, 'T1': 22.0, 'L': 6.0},
        'original_pid': {'Kp': 2.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
        'valve_stiction': 3.0,  # 3% 粘滞
    },
    {
        'name': 'MV Saturation High',
        'description': 'MV饱和 - 阀门全开/全关',
        # 饱和会导致积分饱和（windup），解除后过冲振荡
        'process_original': {'K': 0.8, 'T1': 30.0, 'L': 3.0},
        'process_changed': {'K': 2.5, 'T1': 25.0, 'L': 8.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'temperature',
        'mv_saturation': [0, 100],  # MV 限制在 0-100%
    },
    {
        'name': 'Valve Deadband + Stiction',
        'description': '阀门死区+粘滞组合 - 严重非线性',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 1.5, 'T1': 18.0, 'L': 4.0},
        'original_pid': {'Kp': 3.5, 'Ki': 0.2, 'Kd': 0.0},  # 激进 PID 应对非线性
        'loop_type': 'flow',
        'valve_deadband': 3.0,
        'valve_stiction': 2.0,
    },
    
    # ========== 正常阶跃响应基准 (Normal Step Response Baseline) ==========
    {
        'name': 'Normal Step Flow',
        'description': '正常阶跃响应 - 流量回路基准（无振荡）',
        # 系统变化小，PID 仍然适用，不应振荡
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 1.2, 'T1': 22.0, 'L': 3.0},  # 小幅变化
        'original_pid': {'Kp': 1.5, 'Ki': 0.06, 'Kd': 0.0},  # 保守 PID
        'loop_type': 'flow',
        'expected_stable': True,  # 预期稳定
    },
    {
        'name': 'Normal Step Temperature',
        'description': '正常阶跃响应 - 温度回路基准（无振荡）',
        'process_original': {'K': 0.8, 'T1': 50.0, 'L': 5.0},
        'process_changed': {'K': 1.0, 'T1': 55.0, 'L': 6.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.450, 'Kd': 0.0},
        'loop_type': 'temperature',
        'expected_stable': True,
    },
    {
        'name': 'Normal Step Level',
        'description': '正常阶跃响应 - 液位回路基准（无振荡）',
        'process_original': {'K': 0.50, 'T1': 100.0, 'L': 5.0},
        'process_changed': {'K': 0.60, 'T1': 100.0, 'L': 7.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.225, 'Kd': 0.0},
        'loop_type': 'level',
        'expected_stable': True,
    },
    {
        'name': 'Normal Step Pressure',
        'description': '正常阶跃响应 - 压力回路基准（无振荡）',
        'process_original': {'K': 1.2, 'T1': 15.0, 'L': 1.0},
        'process_changed': {'K': 1.4, 'T1': 16.0, 'L': 2.0},
        'original_pid': {'Kp': 1.2, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'pressure',
        'expected_stable': True,
    },
    
    # ========== 高级过程模型场景 (Advanced Process Models) ==========
    {
        'name': 'Integrating Level True',
        'description': '真实积分液位过程 - 无自稳定',
        'process_original': {'K': 0.50, 'T1': 100.0, 'L': 3.0},  # K 是积分增益
        'process_changed': {'K': 0.80, 'T1': 100.0, 'L': 5.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
        'process_type': 'integrating',  # 使用 IntegratingProcess
    },
    {
        'name': 'Underdamped Temperature',
        'description': '欠阻尼温度回路 - 自然振荡',
        'process_original': {'K': 1.0, 'T1': 40.0, 'L': 5.0, 'T2': 20.0, 'zeta': 0.3},
        'process_changed': {'K': 2.0, 'T1': 35.0, 'L': 8.0, 'T2': 18.0, 'zeta': 0.25},
        'original_pid': {'Kp': 1.50, 'Ki': 0.750, 'Kd': 0.0},
        'loop_type': 'temperature',
        'process_type': 'sopdt',  # 使用 SOPDTProcess
    },
    {
        'name': 'Boiler Swell Shrink',
        'description': '锅炉虚假水位 - 反向响应',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 5.0, 'K_inv': 0.3, 'T_inv': 8.0},
        'process_changed': {'K': 1.50, 'T1': 100.0, 'L': 8.0, 'K_inv': 0.4, 'T_inv': 6.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.450, 'Kd': 0.5},
        'loop_type': 'level',
        'process_type': 'inverse_response',  # 使用 InverseResponseProcess
    },
    {
        'name': 'Thermowell Measurement Lag',
        'description': '温度套管测量滞后',
        'process_original': {'K': 0.8, 'T1': 50.0, 'L': 5.0},
        'process_changed': {'K': 1.5, 'T1': 40.0, 'L': 8.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.06, 'Kd': 0.0},
        'loop_type': 'temperature',
        'measurement_lag': 10.0,  # 10s 测量滞后
    },
    {
        'name': 'Stick Slip Valve',
        'description': '阀门粘滞跳动 - 周期性跳跃',
        'process_original': {'K': 1.0, 'T1': 25.0, 'L': 3.0},
        'process_changed': {'K': 1.8, 'T1': 22.0, 'L': 5.0},
        'original_pid': {'Kp': 2.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
        'valve_stiction': 3.0,
        'stick_slip_period': 20,  # 每20步跳动一次
    },
    {
        'name': 'Equal Percentage Valve',
        'description': '等百分比阀门特性',
        'process_original': {'K': 1.0, 'T1': 30.0, 'L': 3.0},
        'process_changed': {'K': 2.0, 'T1': 25.0, 'L': 6.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'valve_curve': 'equal_pct',  # 等百分比特性
    },
    {
        'name': 'Time Varying Delay',
        'description': '时变滞后 - 负荷相关延迟',
        'process_original': {'K': 1.0, 'T1': 40.0, 'L': 10.0},
        'process_changed': {'K': 1.5, 'T1': 35.0, 'L': 15.0},
        'original_pid': {'Kp': 1.5, 'Ki': 0.05, 'Kd': 0.0},
        'loop_type': 'temperature',
        'delay_variation': 0.3,  # ±30% 滞后变化
    },
    {
        'name': 'Combined Advanced Flow',
        'description': '组合高级特性 - 死区+粘滞+等百分比',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 1.8, 'T1': 18.0, 'L': 4.0},
        'original_pid': {'Kp': 3.0, 'Ki': 0.15, 'Kd': 0.0},
        'loop_type': 'flow',
        'valve_deadband': 3.0,
        'valve_stiction': 2.0,
        'valve_curve': 'equal_pct',
    },
    
    # ========== 真实环境扰动场景 (Realistic Environment Disturbances) ==========
    {
        'name': 'Load Disturbance Random',
        'description': '随机负荷扰动 - 进料流量波动',
        'process_original': {'K': 1.0, 'T1': 30.0, 'L': 3.0},
        'process_changed': {'K': 1.8, 'T1': 25.0, 'L': 5.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'load_disturbance': 2.0,  # ±2 单位负荷扰动
        'load_disturbance_freq': 0.005,  # 0.005Hz (周期200s)
    },
    {
        'name': 'Pump Pulsation',
        'description': '泵脉动周期性扰动',
        'process_original': {'K': 1.2, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 2.0, 'T1': 18.0, 'L': 4.0},
        'original_pid': {'Kp': 2.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'pressure',
        'periodic_disturbance': 0.5,  # ±0.5 单位
        'periodic_disturbance_period': 5.0,  # 5s 周期
    },
    {
        'name': 'Colored Noise Sensor',
        'description': '有色噪声 - 更真实的传感器噪声',
        'process_original': {'K': 1.0, 'T1': 35.0, 'L': 4.0},
        'process_changed': {'K': 2.2, 'T1': 28.0, 'L': 7.0},
        'original_pid': {'Kp': 1.8, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'temperature',
        'noise_std': 0.3,
        'colored_noise_tau': 5.0,  # 5s 滤波时间常数
    },
    {
        'name': 'Sensor Drift Temperature',
        'description': '传感器漂移 - 温度传感器老化',
        'process_original': {'K': 0.8, 'T1': 50.0, 'L': 8.0},
        'process_changed': {'K': 1.5, 'T1': 40.0, 'L': 12.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.05, 'Kd': 0.0},
        'loop_type': 'temperature',
        'sensor_drift': 0.5,  # 0.5 单位/小时漂移
    },
    {
        'name': 'Sensor Fault Spike',
        'description': '传感器故障 - 间歇性跳变',
        'process_original': {'K': 1.0, 'T1': 25.0, 'L': 3.0},
        'process_changed': {'K': 1.5, 'T1': 22.0, 'L': 5.0},
        'original_pid': {'Kp': 2.2, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'sensor_fault_prob': 0.001,  # 0.1% 故障概率
        'sensor_fault_mag': 3.0,  # ±3 单位跳变
    },
    {
        'name': 'Positioner Dynamics',
        'description': '阀门定位器动态 - 响应滞后',
        'process_original': {'K': 1.0, 'T1': 20.0, 'L': 2.0},
        'process_changed': {'K': 2.0, 'T1': 18.0, 'L': 4.0},
        'original_pid': {'Kp': 2.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
        'positioner_tc': 3.0,  # 3s 定位器时间常数
        'positioner_db': 0.5,  # 0.5% 定位器死区
    },
    {
        'name': 'Pneumatic Delay',
        'description': '气动延迟 - 长管线',
        'process_original': {'K': 1.0, 'T1': 30.0, 'L': 5.0},
        'process_changed': {'K': 1.8, 'T1': 28.0, 'L': 8.0},
        'original_pid': {'Kp': 1.8, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'flow',
        'pneumatic_delay': 2.0,  # 2s 气动延迟
    },
    {
        'name': 'Digital Quantization',
        'description': '数字效应 - 低分辨率采集',
        'process_original': {'K': 1.0, 'T1': 25.0, 'L': 3.0},
        'process_changed': {'K': 2.0, 'T1': 22.0, 'L': 5.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        'quantization_bits': 10,  # 10位分辨率
        'communication_delay': 1.0,  # 1s 通信延迟
    },
    {
        'name': 'Full Industrial Environment',
        'description': '完整工业环境 - 所有真实效应组合',
        'process_original': {'K': 1.0, 'T1': 30.0, 'L': 3.0},
        'process_changed': {'K': 2.0, 'T1': 25.0, 'L': 6.0},
        'original_pid': {'Kp': 2.0, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
        # 负荷扰动
        'load_disturbance': 1.0,
        'periodic_disturbance': 0.3,
        # 传感器效应
        'noise_std': 0.2,
        'colored_noise_tau': 3.0,
        'sensor_drift': 0.2,
        # 执行器效应
        'valve_deadband': 2.0,
        'valve_stiction': 1.5,
        'positioner_tc': 2.0,
        'pneumatic_delay': 1.0,
        # 数字效应
        'quantization_bits': 12,
        'communication_delay': 0.5,
    },
]

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
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 5.0},
        'process_changed': {'K': 1.50, 'T1': 100.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 1.800, 'Kd': 0.0},
        'loop_type': 'level',
        'amplitude_factors': [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
    },
    {
        'name': 'Level - Outflow Change',
        'description': '液位回路 - 出口流量变化（下游负荷）',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 4.0},
        'process_changed': {'K': 1.40, 'T1': 100.0, 'L': 9.0},
        'original_pid': {'Kp': 1.50, 'Ki': 1.800, 'Kd': 0.0},
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
        'process_original': {'K': 0.80, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 1.20, 'T1': 80.0, 'L': 10.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
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
    
    # ========== 极端场景 (EXTREME Scenarios) ==========
    # 这些场景组合了多个高风险因素，用于测试算法的极限能力
    # 预期：大部分会失败，用于评估改进空间
    
    # 1. 极端组合 - 大滞后 + 高增益变化 + 高噪声
    {
        'name': 'Extreme - Triple Challenge',
        'description': '极端场景 - 大滞后(L/T=1.5) + 增益x10 + 高噪声',
        'process_original': {'K': 0.3, 'T1': 20.0, 'L': 25.0},   # L/T=1.25 → +3
        'process_changed': {'K': 3.0, 'T1': 15.0, 'L': 30.0},    # K变化x10 → +3
        'original_pid': {'Kp': 4.0, 'Ki': 0.1, 'Kd': 0.0},
        'noise_std': 1.2,                                         # 高噪声 → +3
        'loop_type': 'temperature',
    },
    
    # 2. 极端组合 - 极慢系统 + 大滞后 + 增益跳变
    {
        'name': 'Extreme - Slow Delay Gain',
        'description': '极端场景 - 极慢T1=200s + 大滞后 + 增益x8',
        'process_original': {'K': 0.50, 'T1': 80.0, 'L': 40.0},  # T1>100 → +2, L/T=0.2
        'process_changed': {'K': 4.00, 'T1': 80.0, 'L': 80.0},   # K变化x8 → +3, L/T=0.53 → +2
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'noise_std': 0.6,                                         # 中等噪声 → +2
        'loop_type': 'level',
    },
    
    # 3. 极端组合 - 反向响应 + 高噪声 + 增益变化
    {
        'name': 'Extreme - Inverse Noisy',
        'description': '极端场景 - 反向响应(K变负) + 高噪声 + 增益x5',
        'process_original': {'K': 1.00, 'T1': 100.0, 'L': 8.0},
        'process_changed': {'K': -5.00, 'T1': 100.0, 'L': 15.0},   # 反向响应 → +3, K变化x5 → +3
        'original_pid': {'Kp': 1.50, 'Ki': 0.750, 'Kd': 0.0},
        'noise_std': 1.5,                                         # 极高噪声 → +3
        'loop_type': 'level',
    },
    
    # 4. 极端组合 - 极大滞后比 + 极慢系统
    {
        'name': 'Extreme - Dominant Delay Slow',
        'description': '极端场景 - 滞后主导(L/T=2.0) + 极慢T1=150s',
        'process_original': {'K': 0.8, 'T1': 80.0, 'L': 50.0},   # L/T=0.625 → +2
        'process_changed': {'K': 1.5, 'T1': 150.0, 'L': 300.0},  # L/T=2.0 → +3, T1>100 → +2
        'original_pid': {'Kp': 1.0, 'Ki': 0.01, 'Kd': 0.0},
        'noise_std': 0.8,                                         # 高噪声 → +2
        'loop_type': 'temperature',
    },
    
    # ========================================================
    # 真实工厂场景 (REALISTIC Industrial Scenarios)
    # ========================================================
    # 以下场景参数取自真实工厂典型值，覆盖之前缺失的关键情况
    
    # --- A. 近积分液位过程 (K极小, T1极大) ---
    {
        'name': 'Realistic - Level Tank Large',
        'description': '大储罐液位（近积分，T1=2000s）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'process_changed': {'K': 0.30, 'T1': 80.0, 'L': 8.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Realistic - Level Column Base',
        'description': '塔底液位（近积分，T1=800s，较快）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 3.0},
        'process_changed': {'K': 0.50, 'T1': 80.0, 'L': 5.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    {
        'name': 'Realistic - Level Drum',
        'description': '分液罐液位（近积分，受上游扰动大）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 4.0},
        'process_changed': {'K': 0.30, 'T1': 80.0, 'L': 6.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'noise_std': 0.8,
        'loop_type': 'level',
    },
    {
        'name': 'Realistic - Level Overflow Risk',
        'description': '液位溢出风险（高液位运行，变化敏感）',
        'process_original': {'K': 0.30, 'T1': 80.0, 'L': 3.0},
        'process_changed': {'K': 0.30, 'T1': 80.0, 'L': 5.0},
        'original_pid': {'Kp': 1.50, 'Ki': 0.300, 'Kd': 0.0},
        'loop_type': 'level',
    },
    
    # --- B. 真实流量回路（快速, T1=2~8s） ---
    {
        'name': 'Realistic - Flow FCV Fast',
        'description': '快速流量调节阀（T1=3s, L=0.5s）',
        'process_original': {'K': 1.2, 'T1': 3.0, 'L': 0.5},
        'process_changed': {'K': 2.5, 'T1': 2.0, 'L': 1.0},
        'original_pid': {'Kp': 0.8, 'Ki': 0.15, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Realistic - Flow Long Pipe',
        'description': '长管线流量（传输延迟较大, L=3s）',
        'process_original': {'K': 1.0, 'T1': 5.0, 'L': 3.0},
        'process_changed': {'K': 2.0, 'T1': 4.0, 'L': 5.0},
        'original_pid': {'Kp': 0.6, 'Ki': 0.08, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Realistic - Flow Compressor Recycle',
        'description': '压缩机回流（快速+高增益，K=3）',
        'process_original': {'K': 2.0, 'T1': 2.0, 'L': 0.3},
        'process_changed': {'K': 4.0, 'T1': 1.5, 'L': 0.8},
        'original_pid': {'Kp': 0.5, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    
    # --- C. 真实温度回路（慢速, T1=100~300s） ---
    {
        'name': 'Realistic - Temp Reactor',
        'description': '反应器温度（T1=200s, L=30s, 典型化工）',
        'process_original': {'K': 0.8, 'T1': 200.0, 'L': 30.0},
        'process_changed': {'K': 1.5, 'T1': 150.0, 'L': 45.0},
        'original_pid': {'Kp': 0.5, 'Ki': 0.003, 'Kd': 5.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Realistic - Temp Heat Exchanger',
        'description': '换热器出口温度（T1=120s, L=15s）',
        'process_original': {'K': 1.0, 'T1': 120.0, 'L': 15.0},
        'process_changed': {'K': 2.0, 'T1': 90.0, 'L': 25.0},
        'original_pid': {'Kp': 0.4, 'Ki': 0.004, 'Kd': 3.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Realistic - Temp Distillation',
        'description': '精馏塔灵敏板温度（T1=300s, L=60s, 大延迟）',
        'process_original': {'K': 0.6, 'T1': 300.0, 'L': 60.0},
        'process_changed': {'K': 1.2, 'T1': 250.0, 'L': 80.0},
        'original_pid': {'Kp': 0.3, 'Ki': 0.001, 'Kd': 10.0},
        'loop_type': 'temperature',
    },
    {
        'name': 'Realistic - Temp Furnace',
        'description': '加热炉出口温度（T1=180s, L=20s, 高增益）',
        'process_original': {'K': 2.0, 'T1': 180.0, 'L': 20.0},
        'process_changed': {'K': 3.5, 'T1': 140.0, 'L': 35.0},
        'original_pid': {'Kp': 0.3, 'Ki': 0.002, 'Kd': 5.0},
        'loop_type': 'temperature',
    },
    
    # --- D. 压力回路（中速） ---
    {
        'name': 'Realistic - Pressure Vessel',
        'description': '容器压力（T1=15s, 保压控制）',
        'process_original': {'K': 1.5, 'T1': 15.0, 'L': 2.0},
        'process_changed': {'K': 3.0, 'T1': 10.0, 'L': 4.0},
        'original_pid': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 1.0},
        'loop_type': 'pressure',
    },
    {
        'name': 'Realistic - Pressure Column Top',
        'description': '塔顶压力（T1=25s, 与温度耦合）',
        'process_original': {'K': 0.8, 'T1': 25.0, 'L': 3.0},
        'process_changed': {'K': 1.8, 'T1': 20.0, 'L': 5.0},
        'original_pid': {'Kp': 0.8, 'Ki': 0.03, 'Kd': 2.0},
        'noise_std': 0.3,
        'loop_type': 'pressure',
    },
    
    # --- E. 阀门问题场景 ---
    {
        'name': 'Realistic - Valve Deadband',
        'description': '阀门死区3%（最常见振荡原因）',
        'process_original': {'K': 1.0, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 1.5, 'T1': 4.0, 'L': 2.0},
        'original_pid': {'Kp': 1.2, 'Ki': 0.1, 'Kd': 0.0},
        'noise_std': 0.5,  # 死区效果近似为噪声
        'loop_type': 'flow',
    },
    {
        'name': 'Realistic - Valve Stiction',
        'description': '阀门粘滞（MV 突跳+滞后）',
        'process_original': {'K': 1.0, 'T1': 5.0, 'L': 1.0},
        'process_changed': {'K': 2.0, 'T1': 3.0, 'L': 2.5},
        'original_pid': {'Kp': 1.0, 'Ki': 0.08, 'Kd': 0.0},
        'noise_std': 0.8,
        'loop_type': 'flow',
    },
    
    # --- F. 多工作点/负荷变化 ---
    {
        'name': 'Realistic - Low Load Operation',
        'description': '低负荷运行（增益降低，响应变慢）',
        'process_original': {'K': 0.5, 'T1': 8.0, 'L': 2.0},
        'process_changed': {'K': 1.0, 'T1': 6.0, 'L': 3.0},
        'original_pid': {'Kp': 1.5, 'Ki': 0.12, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Realistic - High Load Operation',
        'description': '高负荷运行（增益增加，非线性明显）',
        'process_original': {'K': 1.5, 'T1': 4.0, 'L': 0.8},
        'process_changed': {'K': 3.5, 'T1': 3.0, 'L': 1.5},
        'original_pid': {'Kp': 0.7, 'Ki': 0.1, 'Kd': 0.0},
        'loop_type': 'flow',
    },
    {
        'name': 'Realistic - Startup Transition',
        'description': '开车过渡（冷→热，K和T1都在变）',
        'process_original': {'K': 0.3, 'T1': 300.0, 'L': 40.0},
        'process_changed': {'K': 1.0, 'T1': 150.0, 'L': 20.0},
        'original_pid': {'Kp': 0.5, 'Ki': 0.002, 'Kd': 5.0},
        'loop_type': 'temperature',
    },
]


