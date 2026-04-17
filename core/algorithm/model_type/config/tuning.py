"""
整定相关配置 (Tuning Configuration)
===================================

包含模型拟合、闭环稳定性、PID约束等整定相关配置。
"""

# ============================================================
# 模型拟合配置
# ============================================================
MODEL_FITTING = {
    'r2_good_threshold': 0.8,            # R² 良好阈值
    'r2_acceptable_threshold': 0.5,      # R² 可接受阈值
    'r2_poor_threshold': 0.3,            # R² 较差阈值（与OSCILLATION_TUNING.r2_failure_threshold一致）
    'k_min': 0.001,                      # K 最小有效值
    'k_max': 50.0,                       # K 最大合理值
}

# ============================================================
# 闭环稳定性配置
# ============================================================
CLOSED_LOOP = {
    'settling_threshold': 0.02,          # 稳态误差带（2%）
    'max_settling_time': 900.0,          # 最大调节时间（秒）
    'overshoot_good': 10.0,              # 良好超调量（%）
    'overshoot_acceptable': 60.0,        # [FIX] 允许的最大超调量 (%) - 工业标准适度放宽
    'rise_time_min': 1.0,                # 理想上升时间下限（秒）
    'rise_time_max': 10.0,               # 理想上升时间上限（秒）
    'oscillation_count_ideal': 4,        # 理想振荡次数上限
    'min_r2_confidence': 0.6,            # 最低R²置信度阈值
}

# ============================================================
# 回路类型特定验证配置 (Loop-Specific Verification)
# ============================================================
LOOP_SPECIFIC_VERIFICATION = {
    'temperature': {
        'max_settling_time_factor': 25.0,    # 温度回路：大惯性，允许更长的调节时间 (25x T)
        'overshoot_acceptable': 65.0,        # [FIX] 温度回路：工业标准允许适度超调
        'steady_state_error': 10.0,          # [FIX] 温度回路：放宽稳态误差（传感器精度+大迟滞）
    },
    'level': {
        'max_settling_time_factor': 25.0,    # 液位回路：积分特性，需要更长时间验证
        'overshoot_acceptable': 80.0,        # 液位回路：允许较大超调
        'steady_state_error': 15.0,          # 液位回路：允许较大的稳态误差 (非自衡)
    },
    'flow': {
        'max_settling_time_factor': 15.0,    # 流量回路：放宽到 15x
        'overshoot_acceptable': 70.0,        # [FIX] 流量回路：放宽至70%（快回路+阀门非线性常导致大超调）
        'steady_state_error': 10.0,          # [FIX] 流量回路：放宽稳态误差
    },
    'pressure': {
        'max_settling_time_factor': 15.0,    # 压力回路：放宽到 15x
        'overshoot_acceptable': 60.0,        # [FIX] 压力回路：适度放宽
        'steady_state_error': 8.0,           # [FIX] 压力回路：放宽稳态误差
    },
}

# ============================================================
# PID参数约束配置
# ============================================================
PID_CONSTRAINTS = {
    # Kp约束
    'kp_min': 0.01,                  # Kp最小绝对值
    'kp_max_from_pb': 100.0,         # Kp上限计算: 100 / pb_min
    
    # Ti约束
    'ti_min': 0.1,                   # Ti最小值（秒）
    'ti_max': 300.0,                 # Ti最大值（秒）[从120s提高到300s，解锁大积分时间]
    
    # Td约束
    'td_max_ratio': 0.25,            # Td最大比例（相对于Ti）

    # 贴边缓冲（避免参数长期命中边界）
    'edge_buffer_enabled': True,
    'edge_near_ratio': 0.02,         # 距离边界 2% 以内判定为“贴边”
    'kp_upper_buffer_ratio': 0.95,   # Kp 触顶后回退到上限的 95%
    'ti_lower_buffer_ratio': 0.08,   # Ti 贴下边界时抬高 8%
    'ti_upper_buffer_ratio': 0.08,   # Ti 贴上边界时回退 8%
    
    # 默认回退参数（当整定失败时使用）
    'fallback_kp': 1.0,
    'fallback_ti': 20.0,
    'fallback_td': 0.0,
    
    # 保守等级基准值（用于 tuning_methods.py 中的标准化计算）
    'conservative_level_baseline': 4.0,
    
    # Cohen-Coon 法保守因子（降低 Kp）
    'cohen_coon_conservative_factor': 0.85,
    
    # 非线性模型补偿因子
    'nonlinear_factors': {
        'default': 1.3,              # 默认非线性补偿
        'HAMMERSTEIN': 1.4,          # Hammerstein模型
        'DEADBAND_FOPDT': 1.3,       # 死区模型（降低Kp补偿，避免振荡）
        'SAT_FOPDT': 1.3,            # 饱和模型
    },
    
    # 死区专用补偿：增强积分作用以消除稳态误差
    'deadband_compensation': {
        'ti_reduction_factor': 0.7,  # Ti缩减系数（减小Ti加快积分）
        'ki_boost_factor': 1.3,      # Ki增强系数
        'enable': True,              # 是否启用死区补偿
    },
    
    # 阀门补偿参数
    'valve_compensation': {
        'osc_threshold_high': 0.5,   # 高振荡阈值
        'osc_threshold_med': 0.6,    # 中振荡阈值
        'r2_threshold': 0.85,        # R²阈值
        'factor_high_base': 1.3,     # 高振荡+低R²基础因子
        'factor_high_slope': 0.6,    # 高振荡+低R²斜率
        'factor_med_base': 1.2,      # 中振荡基础因子
        'factor_med_slope': 0.5,     # 中振荡斜率
    },
}

# ============================================================
# 优化配置
# ============================================================
OPTIMIZATION = {
    'r2_threshold': 0.85,            # 触发优化的R²阈值
    'min_segment_r2': 0.3,           # 最小段R²阈值
    'segment_r2_std_max': 0.25,      # 段R²标准差上限
    'k_magnitude_ratio_max': 3.0,    # K值变化幅度上限（倍）- 防止优化后K值偏离过大
    'k_sign_check': True,            # 是否检查K值符号反转
    'amplitude_ratio_min': 0.3,      # 幅度比下限
    'amplitude_ratio_max': 3.0,      # 幅度比上限
}

# ============================================================
# 参数约束配置
# ============================================================
PARAMETER_CONSTRAINTS = {
    'T1_max': 30.0,                  # T1最大值
    'L_max': 10.0,                   # L最大值
    'k_reasonable_min': 0.01,        # K合理性检查下限
}

# ============================================================
# 非线性模型配置
# ============================================================
NONLINEAR_FITTING = {
    'enable': True,                      # 是否启用非线性模型拟合
    'nonlinearity_threshold': 0.4,       # 非线性度阈值，超过此值尝试非线性模型
    'r2_improvement_threshold': 0.1,     # R²提升阈值，非线性模型需比线性提升这么多才选用
    'deadband_detection_threshold': 0.3, # 死区检测阈值
    'saturation_detection_threshold': 0.2, # 饱和检测阈值
    'max_polynomial_order': 3,           # Hammerstein多项式最高阶数
}

# ============================================================
# 整定默认参数配置
# ============================================================
TUNING_DEFAULTS = {
    'lambda_factor': 0.8,                # Lambda整定系数
    'enable_downsample': True,           # 是否启用智能降采样
    'downsample_target': 1000,           # 降采样目标点数
}

# ============================================================
# 模型选择器配置
# ============================================================
MODEL_SELECTOR = {
    # R²阈值
    'min_r2_for_vote': 0.3,              # 模型投票最低R²
    'min_r2_for_quality': 0.4,           # 质量筛选最低R²
    'r2_thresholds': [0.5, 0.3, 0.15, 0.0],  # R²分级阈值
    
    # 仿真质量判断阈值
    'sim_r2_poor_threshold': 0.5,        # 仿真R²较差阈值
    'sim_r2_fail_threshold': 0.1,        # 仿真R²失败阈值
    'oscillation_poor_threshold': 0.4,   # 振荡较差阈值
    'amplitude_ratio_min': 0.5,          # 幅度比下限（较差）
    'amplitude_ratio_max': 2.0,          # 幅度比上限（较差）
    'amplitude_ratio_fail_min': 0.3,     # 幅度比下限（失败）
    'amplitude_ratio_fail_max': 3.0,     # 幅度比上限（失败）
    
    # 闭环验证默认参数
    'default_sp_initial': 50.0,          # 默认SP初始值
    'default_sp_final': 60.0,            # 默认SP终值
    'default_pv_initial': 50.0,          # 默认PV初始值
    'min_sp_change': 5.0,                # 最小SP变化量
    
    # 评分质量分级
    'quality_excellent_r2': 0.85,        # 优秀R²阈值
    'quality_good_r2': 0.7,              # 良好R²阈值
    'quality_acceptable_r2': 0.5,        # 一般R²阈值

    # 方法竞争目标函数（自动计算，不依赖人工试凑）
    'method_select_weight_stability': 0.75,       # 稳定性评分权重
    'method_select_weight_confidence': 0.25,      # 方法置信度权重
    'method_select_weight_move_penalty': 0.85,    # 相对 current_pid 变更惩罚权重
    'method_select_move_ratio_kp': 4.0,           # Kp 允许相对变化倍率（对数尺度）
    'method_select_move_ratio_ti': 4.0,           # Ti 允许相对变化倍率（对数尺度）
    'method_select_move_kp_weight': 0.6,          # 变更惩罚中 Kp 权重
    'method_select_move_ti_weight': 0.4,          # 变更惩罚中 Ti 权重
    'method_select_sign_flip_penalty': 0.7,       # Kp 符号翻转惩罚（0~1）

    # 模型辨识参数输出护栏（相对 current_pid 的单次调参幅度限制）
    'model_based_use_current_pid_guard': True,
    'model_based_kp_max_expand_base': 2.0,        # 低置信度时 Kp 最大放大倍数
    'model_based_kp_max_expand_gain': 2.0,        # 高置信度额外放大倍数
    'model_based_kp_max_shrink_base': 2.0,        # 低置信度时 Kp 最大缩小倍数
    'model_based_kp_max_shrink_gain': 2.0,        # 高置信度额外缩小倍数
    'model_based_ti_max_expand_base': 1.8,        # 低置信度时 Ti 最大放大倍数
    'model_based_ti_max_expand_gain': 1.2,        # 高置信度额外放大倍数
    'model_based_ti_max_shrink_base': 2.2,        # 低置信度时 Ti 最大缩小倍数
    'model_based_ti_max_shrink_gain': 1.8,        # 高置信度额外缩小倍数

    # 无 current_pid 时的自判断护栏（基于数据质量与模型可信度）
    'no_current_pid_guard_enabled': True,
    'no_current_pid_pb_floor_factor': 0.8,        # 最低 PB 底线因子（乘以回路 pb_min）
    'no_current_pid_pb_risk_gain': 1.0,           # 风险越高，PB 底线越高
    'no_current_pid_ti_floor_risk_gain': 1.2,     # 风险越高，Ti 下限越高
}

# ============================================================
# 鲁棒整定增强配置 (Robust Tuning)
# ============================================================
ROBUST_TUNING = {
    'r2_robust_threshold': 0.6,          # 低于此 R² 触发指数级保守惩罚
    'min_pb_flow': 30.0,                 # 流量回路最低 PB 保护 [50→30，与工业真实下限对齐]
    'min_pb_temp': 80.0,                 # 温度回路最低 PB 保护 [100→80，配合 loop_presets pb_min 同步]
    'sign_mismatch_penalty': 3.0,        # 符号不匹配时的保守等级乘数
}

# ============================================================
# Rating 驱动自优化配置 (Self-Optimization)
# ============================================================
SELF_OPTIMIZE = {
    'enabled': True,                         # 是否启用 Rating 驱动自优化
    'lambda_multipliers': [0.6, 0.8, 1.0, 1.2, 1.5, 2.0],  # lambda 倍数候选
    'min_score_improvement': 0.3,            # 最低评分提升阈值（低于此不替换原参数）
    # Phase 2: PB/TI/TD 微调
    'fine_tune_enabled': True,               # 是否启用 PB/TI/TD 微调
    'fine_tune_ratios': [0.8, 0.9, 1.0, 1.1, 1.2],   # 扰动比例
    'fine_tune_max_rounds': 2,               # 坐标轮换最大轮数
    'fine_tune_min_improvement': 0.02,       # 微调最低提升阈值 (修改为 0.02 以匹配平滑打分)
}

# ============================================================
# 最终评分硬门槛配置 (Final Rating Guardrails)
# ============================================================
RATING_GUARD = {
    # method_confidence 极低时，综合分封顶
    'low_confidence_threshold': 0.2,
    'low_confidence_cap': 6.0,
    # 按 performance_score 分段封顶（从低到高匹配）
    # 格式: (performance_threshold, final_rating_cap)
    'performance_caps': [
        (1.0, 3.0),
        (3.0, 5.0),
        (4.5, 6.2),
        (6.0, 7.5),
    ],
}

# ============================================================
# 滑动窗口寻优配置 (Sliding Window Optimization)
# ============================================================
SLIDING_WINDOW = {
    'enabled': False,                        # 是否启用滑动窗口寻优（默认关闭，保持向后兼容）
    'window_hours': 6.0,                     # 窗口时长（小时）
    'step_hours': 2.0,                       # 步长（小时）
    'min_windows': 2,                        # 最少需要的窗口数（少于此数直接跳过滑窗）
    'max_windows': 20,                       # 最大窗口数限制（防止数据过长导致过多计算）
    'fast_screen_verbose': False,            # 快筛阶段是否输出详细日志
    'top_n': 3,                              # 滑窗寻优返回 Top N 个高分窗口用于多段融合（1=退化为原始单窗口行为）
    'top_n_min_score_ratio': 0.85,           # Top N 窗口的最低评分比率（相对于最高分），低于此的窗口不纳入融合
    # 可辨识性预过滤（防止把算力浪费在“不可整定窗口”）
    'min_identifiability': 0.25,             # 可辨识性最低阈值
    'prefilter_keep_ratio': 0.55,            # 预过滤后保留比例（相对于原候选数）
    # 可辨识性打分参数
    'ident_mv_weight': 0.35,
    'ident_pv_weight': 0.30,
    'ident_corr_weight': 0.25,
    'ident_sv_penalty_weight': 0.15,
    'ident_mv_scale': 0.10,
    'ident_pv_scale': 0.12,
    'ident_sv_scale': 0.15,
    # 在滑窗综合分里的低可辨识性惩罚
    'ident_penalty_center': 0.45,
    'ident_penalty_gain': 0.45,
}
