"""
振荡整定配置 (Oscillation Tuning Configuration)
===============================================

振荡整定相关的所有配置参数。

🔥 核心参数（重点关注）
---------------------
- pb_min/pb_max: 比例带范围(%)，控制整定的保守程度
- ti_range: 积分时间范围(秒)

按场景调整
---------
1. 液位回路效果差 → 增大 level_ti_multiplier (2.2→2.5)
2. 温度回路仿真不收敛 → 增大 temperature_sim_duration_factor (8→10)
3. 振荡压制不足 → 增大 safety_factor_base (1.2→1.4)
4. 大滞后系统失败 → 增大 large_delay_pb_boost (1.8→2.2)
"""

OSCILLATION_TUNING = {
    # 触发振荡整定的条件
    'oscillation_ratio_threshold': 0.08, # 振荡比阈值，降低以检测弱振荡（从0.1降到0.08）
    'r2_failure_threshold': 0.35,        # R² 阈值，略微提高以更早触发振荡整定（从0.3提到0.35）
    
    # ========== 弱振荡检测增强配置 ==========
    'weak_oscillation_detection': True,  # 启用弱振荡检测
    'weak_osc_fft_threshold': 0.15,      # FFT主频能量占比阈值（低于此值认为无明显振荡）
    'weak_osc_envelope_threshold': 0.3,  # 包络比阈值（低于此值认为振荡幅度小）
    'weak_osc_combined_threshold': 0.2,  # 综合振荡得分阈值（osc_ratio*0.4 + envelope*0.6）
    
    # 振荡周期检测
    'period_min': 1.0,                   # 最小周期（秒）
    'period_max': 300.0,                 # 最大周期（秒）- 增大以支持极慢系统（从200增到300）
    
    # 闭环仿真参数
    'sp_initial': 50.0,                  # 设定值初始值
    'sp_final': 60.0,                    # 设定值最终值
    'pv_initial': 50.0,                  # 过程值初始值
    
    # ========== 通用保守策略（基于相对指标，提高普适性） ==========
    # 使用 Ku/K 比值代替绝对Ku阈值，适用于不同量程的回路
    'ku_k_ratio_high': 20.0,             # Ku/K > 此值认为临界增益相对过大
    'ku_k_ratio_low': 0.5,               # Ku/K < 此值认为临界增益相对过小
    
    # 保留绝对阈值作为兜底（极端情况）
    'low_gain_threshold': 0.05,          # 低增益系统绝对阈值（极低增益）
    'ku_high_threshold': 50.0,           # Ku绝对上限（极端情况）
    'ku_low_threshold': 0.1,             # Ku绝对下限（极端情况）
    
    # ========== 基础pb计算参数 ==========
    'pb_from_k_factor': 1.0,             # 基于K计算pb的系数 [降低：1.5→1.0，避免基础PB就过高]
    'kp_from_ku_factor': 0.45,           # 基于Ku计算Kp的系数（ZN法是0.45）[优化: 0.40→0.45，提升增益]
    
    # ========== 慢系统调整 ==========
    'slow_system_pu_thresholds': [30.0, 15.0],  # Pu阈值
    'slow_system_factors': [1.15, 1.05, 1.0],   # 对应因子 [降低：1.3/1.15→1.15/1.05，避免与oscillation_adjustment叠加]
    
    # ========== 原因微调因子 ==========
    'high_gain_extra_factor': 1.05,      # Ku过大时的额外保守系数 [优化: 1.1→1.05]
    
    # ========== 数据质量调整 ==========
    'quality_adjustment_threshold': 0.5, # 数据质量低于此值开始调整
    'quality_adjustment_factor': 0.6,    # 质量调整系数（最多增加30%）
    
    # ========== 非线性调整 ==========
    'nonlinearity_threshold': 0.5,       # 非线性超过此值开始调整
    'nonlinearity_factor': 0.4,          # 非线性调整系数（最多增加20%）
    
    # ========== 阀门问题调整因子 ==========
    'valve_deadband_factor': 1.15,       # 死区调整因子
    'valve_stiction_factor': 1.2,        # 粘滞调整因子
    'valve_saturation_factor': 1.1,      # 饱和调整因子
    
    # ========== 振荡比自适应安全系数 ==========
    'safety_factor_base': 1.0,           # 基础安全系数 (osc < 0.5) [降低：1.1→1.0，中性基准]
    'safety_factor_thresholds': [0.5, 0.7, 0.85],  # 振荡比阈值
    'safety_factor_slopes': [0.2, 0.4, 0.8],       # 各区间斜率 [降低：0.4/0.8/1.5→0.2/0.4/0.8，减少PB膨胀]
    
    # ========== 总乘数上限 ==========
    'max_multiplier_normal': 1.6,        # 正常振荡时的乘数上限 [降低：2.0→1.6]
    'max_multiplier_high_osc': 2.0,      # 高振荡(>0.85)时的乘数上限 [降低：2.5→2.0]
    
    # ========== 自适应整定参数（渐进式策略，动态pb调整） ==========
    'pb_gradient': 0.6,                  # pb渐进系数 [降低：1.0→0.6，减少振荡对PB的影响]
    'pb_oscillation_start': 0.4,         # 开始应用渐进调整的振荡比阈值
    
    # ========== 自适应微分作用 ==========
    'enable_adaptive_derivative': True,  # 是否启用自适应微分
    'derivative_factor': 0.25,           # Kd = Kp * Pu * derivative_factor
    'derivative_oscillation_threshold': 0.5,  # 振荡比超过此值才加微分
    'td_base_divisor': 12.0,              # Td基础计算: Pu / td_base_divisor
    'td_multiplier_factor': 1.5,         # Td乘数系数
    'td_range': [0.3, 3.0],              # Td范围限制
    
    # ========== 自适应Ti参数 ==========
    'ti_osc_start': 0.5,                 # Ti振荡调整开始阈值（提前开始）
    'ti_osc_factor': 0.8,                # Ti振荡调整系数（增大，补偿pb减小）
    'ti_slow_pu_thresholds': [30.0, 15.0],  # Ti慢系统Pu阈值（增大以更早识别慢系统）
    'ti_slow_factors': [1.25, 1.12, 1.0],   # Ti慢系统乘数（增大）
    'ti_range': [1.5, 600.0],             # Ti范围限制（增大上限以支持慢温控/液位回路）
    'ti_min_base': 1.5,                  # Ti基础最小值
    
    # ========== 液位回路专用配置（积分过程特性）==========
    # 液位回路特点：积分特性、大时间常数、对滞后敏感
    'level_ti_multiplier': 2.2,          # 液位回路Ti基础乘数（从2.0提高到2.2）
    'level_integrating_ti_max': 3.5,     # 积分过程Ti乘数上限（从3.0提高到3.5）
    'level_integrating_t1_threshold': 50.0,  # 积分过程T1阈值（从60降低到50，更早识别）
    'level_gain_threshold': 1.2,         # 液位高增益阈值（从1.5降低到1.2）
    'level_very_high_gain_threshold': 2.5,  # 液位极高增益阈值（从3.0降低到2.5）
    'level_slow_system_pu': 50.0,        # 液位慢系统Pu阈值（从60降低到50）
    'level_mid_gain_range': [1.0, 2.2],  # 液位中等增益范围（扩大范围）
    'level_mid_gain_factor': 0.18,       # 中等增益pb调整系数（从0.15提高到0.18）
    'level_large_t1_threshold': 40.0,    # 大时间常数阈值（从50降低到40）
    'level_large_t1_factor': 100.0,      # 大T1 pb调整除数（从120降低到100）
    'level_pb_boost_factor': 1.4,        # 液位回路pb额外保守因子（从1.3提高到1.4）
    'level_kd_enable_threshold': 0.6,    # 液位回路启用微分的振荡阈值（从0.7降低到0.6）
    'level_fallback_pb': 250.0,          # 液位回路fallback时的默认pb（新增）
    'level_fallback_ti_factor': 2.5,     # 液位回路fallback时的Ti乘数（新增）
    
    # ========== pb范围 (恢复稳定性) ==========
    'pb_min': 60.0,                      # pb下限 [优化: 80→60, 适应流量回路快速响应]
    'pb_max': 450.0,                     # pb上限 (恢复: 350→450)
    'pb_max_large_delay': 600.0,         # 大滞后系统pb上限 (恢复: 500→600)
    
    # ========== 大滞后系统专用配置（L/T1 > 0.5）(恢复稳定性) ==========
    'large_delay_ratio_threshold': 0.5,  # 大滞后比阈值
    'large_delay_lambda_factor': 2.5,    # 大滞后时Lambda因子 (恢复)
    'large_delay_pb_boost': 1.5,         # 大滞后时pb额外增益 [优化: 1.8→1.5, 石化大滞后常见]
    'large_delay_ti_boost': 1.5,         # 大滞后时Ti额外增益 (恢复: 1.4→1.5)
    'extreme_delay_ratio_threshold': 0.8, # 极大滞后比阈值
    'extreme_delay_pb_boost': 2.0,       # 极大滞后时pb额外增益 [优化: 2.5→2.0]
    'large_delay_absolute_threshold': 15.0, # 绝对滞后阈值（秒）
    
    # ========== 极慢系统配置（T1 > 100s 或 Pu > 100s）==========
    'very_slow_system_t1_threshold': 100.0,  # 极慢系统T1阈值
    'very_slow_system_pu_threshold': 100.0,  # 极慢系统Pu阈值
    'very_slow_sim_duration_factor': 12.0,   # 极慢系统仿真时长因子（增大到12倍）
    'very_slow_max_sim_duration': 3600.0,    # 极慢系统最大仿真时长（增大到3600秒）
    
    # ========== 回路类型仿真时长因子（新增）==========
    'level_sim_duration_factor': 10.0,       # 液位回路仿真时长因子
    'temperature_sim_duration_factor': 8.0,  # 温度回路仿真时长因子
    'default_sim_duration_factor': 6.0,      # 默认回路仿真时长因子
    
    # ========== 时变特性处理（新增）==========
    'time_varying_detection': True,          # 是否启用时变特性检测
    'high_gain_gradient_threshold': 3.0,     # 高增益梯度阈值（K变化超过此值认为时变）
    'high_gain_gradient_pb_factor': 1.3,     # 高增益梯度时pb额外保守因子
    'time_varying_ti_boost': 1.2,            # 时变系统Ti增益
    
    # ========== 动态pb边界（基于过程增益K） ==========
    'pb_k_adjustment_factor': 0.3,       # pb下限动态调整系数: pb_min *= (1 + factor/K)
    'ku_k_extreme_pb_factor': 1.5,       # Ku/K异常时的pb下限乘数
    
    # ========== 额外保守因子 ==========
    'critical_method_safety_factor': 1.2,  # 临界法额外安全系数
    
    # ========== 负K值自动校正（剧烈震荡导致的相位偏移） ==========
    # 当检测到高振荡且K为负时，很可能是相位偏移导致的误判
    # 真正的反向作用系统（制冷、减压）通常不会有剧烈震荡
    'negative_k_oscillation_threshold': 0.3,  # 中等震荡阈值，超过此值开始检查负K
    'negative_k_severe_threshold': 0.5,       # 剧烈震荡阈值，超过此值直接取abs(K)
}
