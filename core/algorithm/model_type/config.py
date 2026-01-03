"""
模型配置模块 (Model Configuration Module)
=========================================

本模块定义了模型辨识所需的全局配置参数。

🔥 核心参数（重点关注）
---------------------
OSCILLATION_TUNING:
    pb_min/pb_max: 比例带范围(%)，控制整定的保守程度
    ti_range: 积分时间范围(秒)
    enable_llm: 是否启用LLM辅助整定
    
按场景调整
---------
1. 液位回路效果差 → 增大 level_ti_multiplier (2.2→2.5)
2. 温度回路仿真不收敛 → 增大 temperature_sim_duration_factor (8→10)
3. 振荡压制不足 → 增大 safety_factor_base (1.2→1.4)
4. 大滞后系统失败 → 增大 large_delay_pb_boost (1.8→2.2)

一般无需修改的参数
-----------------
ku_k_ratio_*, quality_adjustment_*, valve_*_factor,
pb_gradient, derivative_* 等（已经过调优）

配置分组
--------
- OSCILLATION_TUNING: 振荡整定相关配置
- MODEL_FITTING: 模型拟合质量阈值
- CLOSED_LOOP: 闭环稳定性验证配置
- SEGMENT_PROCESSING: 扰动段处理配置
- TUNING_SEGMENT: 整定段检测配置
- PID_CONSTRAINTS: PID参数约束配置
- OPTIMIZATION: 优化算法配置
- MODEL_BOUNDS: 各模型的参数边界
- NONLINEAR_FITTING: 非线性模型配置
- PREPROCESSING: 数据预处理配置
"""


class ModelType:
    """模型类型枚举"""
    # 线性模型
    FOPDT = "FOPDT"           # 一阶加纯滞后模型 (First Order Plus Dead Time)
    FO = "FO"                 # 纯一阶模型 (First Order)
    SOPDT = "SOPDT"           # 二阶加纯滞后模型 (Second Order Plus Dead Time)
    SO = "SO"                 # 纯二阶模型 (Second Order, 无滞后)
    FOPI = "FO_INTEGRATOR"    # 一阶积分模型 (First Order Plus Integrator)
    SOPI = "SO_INTEGRATOR"    # 二阶积分模型 (Second Order Integrator)
    
    # 非线性模型
    HAMMERSTEIN = "HAMMERSTEIN"       # Hammerstein模型 (静态非线性 + 线性动态)
    DEADBAND_FOPDT = "DEADBAND_FOPDT" # 死区 + FOPDT模型
    SATURATION_FOPDT = "SAT_FOPDT"    # 饱和 + FOPDT模型
    
    # ============================================================
    # 统一常量定义（避免各模块重复定义）
    # ============================================================
    
    # 候选模型列表（用于多模型拟合）
    CANDIDATE_MODELS = [FOPDT, FO, SO, SOPDT, FOPI]
    
    # 模型参数数量（用于AIC/BIC计算）
    MODEL_PARAM_COUNT = {
        FOPDT: 3,
        FO: 2,
        SO: 3,
        SOPDT: 4,
        FOPI: 2,
    }
    
    @classmethod
    def get_bounds(cls, model_type: str) -> tuple:
        """获取模型参数边界（统一从Config.MODEL_BOUNDS读取）"""
        from .config import Config
        bounds_config = Config.MODEL_BOUNDS.get(model_type, {})
        if 'initial' in bounds_config:
            return bounds_config['initial']
        # 默认回退边界
        return ([-10.0, 1.0, 0.0], [10.0, 500.0, 50.0])


class Config:
    """系统配置类：包含模型辨识相关的配置参数"""
    EPSILON = 1e-9
    
    # ============================================================
    # 振荡整定配置
    # ============================================================
    OSCILLATION_TUNING = {
        # ========== LLM 辅助决策开关 ==========
        'enable_llm': False,                  # 是否启用 LLM 辅助决策保守策略
        
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
        'pb_from_k_factor': 1.5,             # 基于K计算pb的保守系数
        'kp_from_ku_factor': 0.35,           # 基于Ku计算Kp的系数（ZN法是0.45，保守用0.35）
        
        # ========== 慢系统调整 ==========
        'slow_system_pu_thresholds': [30.0, 15.0],  # Pu阈值
        'slow_system_factors': [1.3, 1.15, 1.0],    # 对应因子
        
        # ========== 原因微调因子 ==========
        'high_gain_extra_factor': 1.1,       # Ku过大时的额外保守系数
        
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
        'safety_factor_base': 1.2,           # 基础安全系数 (osc < 0.5)
        'safety_factor_thresholds': [0.5, 0.7, 0.85],  # 振荡比阈值
        'safety_factor_slopes': [0.4, 0.8, 1.5],       # 各区间斜率（降低，转移到Ti）
        
        # ========== 总乘数上限 ==========
        'max_multiplier_normal': 2.0,        # 正常振荡时的乘数上限
        'max_multiplier_high_osc': 2.5,      # 高振荡(>0.85)时的乘数上限
        
        # ========== 自适应整定参数（渐进式策略，动态pb调整） ==========
        'pb_gradient': 1.0,                  # pb渐进系数
        'pb_oscillation_start': 0.4,         # 开始应用渐进调整的振荡比阈值
        
        # ========== 自适应微分作用 ==========
        'enable_adaptive_derivative': True,  # 是否启用自适应微分
        'derivative_factor': 0.25,           # Kd = Kp * Pu * derivative_factor
        'derivative_oscillation_threshold': 0.5,  # 振荡比超过此值才加微分
        'td_base_divisor': 8.0,              # Td基础计算: Pu / td_base_divisor
        'td_multiplier_factor': 1.5,         # Td乘数系数
        'td_range': [0.3, 3.0],              # Td范围限制
        
        # ========== 自适应Ti参数 ==========
        'ti_osc_start': 0.5,                 # Ti振荡调整开始阈值（提前开始）
        'ti_osc_factor': 0.8,                # Ti振荡调整系数（增大，补偿pb减小）
        'ti_slow_pu_thresholds': [30.0, 15.0],  # Ti慢系统Pu阈值（增大以更早识别慢系统）
        'ti_slow_factors': [1.25, 1.12, 1.0],   # Ti慢系统乘数（增大）
        'ti_range': [1.5, 25.0],             # Ti范围限制（增大上限以支持慢液位回路）
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
        
        # ========== pb范围 ==========
        'pb_min': 120.0,                     # pb下限
        'pb_max': 600.0,                     # pb上限（增大到600）
        'pb_max_large_delay': 900.0,         # 大滞后系统pb上限（新增）
        
        # ========== 大滞后系统专用配置（L/T1 > 0.5）==========
        'large_delay_ratio_threshold': 0.5,  # 大滞后比阈值
        'large_delay_lambda_factor': 2.5,    # 大滞后时Lambda因子（增大到2.5）
        'large_delay_pb_boost': 1.8,         # 大滞后时pb额外增益（增大到1.8）
        'large_delay_ti_boost': 1.5,         # 大滞后时Ti额外增益（增大到1.5）
        'extreme_delay_ratio_threshold': 0.8, # 极大滞后比阈值
        'extreme_delay_pb_boost': 2.5,       # 极大滞后时pb额外增益（增大到2.5）
        'large_delay_absolute_threshold': 15.0, # 绝对滞后阈值（秒）- 新增
        
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
    
    # ============================================================
    # SIMC 整定配置 (Skogestad Internal Model Control)
    # ============================================================
    # SIMC 是工业界广泛认可的整定方法，核心特点：
    # 1. 只有一个调节参数 τc（闭环时间常数）
    # 2. Ti 有上限约束，防止慢系统积分时间过长
    # 3. 统一处理各类过程模型
    SIMC_TUNING = {
        'enable': True,                       # 启用 SIMC 整定
        'tau_c_factor': 2.0,                  # 最优值：τc = T1 * 2.0（保守）
        'tau_c_min_factor': 2.0,              # τc 最小值：τc >= L * 2.0
        'integrating_tau_c_factor': 4.0,      # 积分过程 τc = L * 4.0
        'ti_limit_factor': 10.0,              # Ti 上限：Ti <= 10 * (τc + L)
        'use_half_rule': True,                # 二阶系统使用 SIMC 半规则
        
        # 按回路类型选择整定方法（混合策略）
        # True = SIMC, False = Lambda
        'loop_type_method': {
            'flow': True,         # Flow 用 SIMC（快速/积分过程）
            'level': True,        # Level 用 SIMC（积分过程）
            'pressure': False,    # Pressure 用 Lambda（需要微分）
            'temperature': False, # Temperature 用 Lambda（慢速系统）
            'default': True,      # 未知类型默认用 SIMC
        },
    }
    
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
        'max_settling_time': 300.0,          # 最大调节时间（秒）
        'overshoot_good': 10.0,              # 良好超调量（%）
        'overshoot_acceptable': 30.0,        # 可接受超调量（%）
        'rise_time_min': 1.0,                # 理想上升时间下限（秒）
        'rise_time_max': 10.0,               # 理想上升时间上限（秒）
        'oscillation_count_ideal': 4,        # 理想振荡次数上限
    }
    
    # ============================================================
    # 段处理配置
    # ============================================================
    SEGMENT_PROCESSING = {
        'min_data_points': 30,           # 最小数据点数（小于30点的扰动段会被过滤）
        'min_fusion_points': 50,         # 融合最小数据点数（降低阈值，允许更短的高质量段）
        'min_fusion_points_high_quality': 30,  # 高质量段(R²>0.8)的最小点数
        'min_pv_range': 0.5,             # 最小PV变化范围
        'min_mv_range': 0.1,             # 最小MV变化范围
        'correlation_threshold': 0.1,    # 相关性阈值（阶跃响应检测）
        'severe_nonlinearity': 0.7,      # 严重非线性阈值
        'severe_oscillation': 0.75,      # 严重振荡阈值
        'low_quality_threshold': 0.25,   # 低质量分阈值
        
        # ========== 整定段合并配置 ==========
        'merge_gap_threshold': 300000,   # 合并间隔阈值（毫秒），5分钟=300000ms
        'merge_expansion_max': 5.0,      # 最大扩展比，超过此值不扩展
        'merge_expansion_allow': 2.0,    # 允许合并的扩展比上限
        'merge_quality_diff': 0.3,       # 质量差异阈值，超过此值不合并
        'merge_osc_diff': 0.4,           # 振荡差异阈值，超过此值不合并
    }
    
    # ============================================================
    # 整定段检测配置（基于MV阶跃变化）
    # ============================================================
    TUNING_SEGMENT = {
        # MV阶跃检测参数
        'min_step_size': 1.0,            # 最小MV阶跃幅度
        'stable_window': 10,             # 稳定窗口大小（采样点数）
        'step_std_ratio': 0.5,           # 阶跃前标准差与阶跃幅度的比值上限
        
        # 响应区间参数
        'min_response_time': 30,         # 最小响应时间（采样点数）
        'max_response_time': 3000,       # 最大响应时间（采样点数）
        
        # PV响应质量评估参数
        'min_pv_range': 2.0,             # PV最小变化范围
        'min_pv_std': 0.3,               # PV最小标准差
        'min_pv_change_ratio': 0.05,     # PV最小变化比例（相对于MV阶跃）
        'mv_range_threshold': 0.1,       # MV变化范围阈值
        'large_mv_range': 10.0,          # 大MV变化范围阈值
        'pv_dynamic_ratio_min': 0.05,    # PV动态变化率下限
        
        # 评分阈值
        'pv_change_ratio_good': 0.1,     # PV变化比例良好阈值
        'pv_change_abs_good': 0.5,       # PV变化绝对值良好阈值
        'trend_ratio_good': 0.1,         # 趋势比例良好阈值
        'trend_ratio_acceptable': 0.05,  # 趋势比例可接受阈值
        'settling_ratio_good': 0.5,      # 收敛比良好阈值
        'osc_ratio_good': 0.2,           # 振荡比良好阈值
        'osc_ratio_acceptable': 0.4,     # 振荡比可接受阈值
        'corr_good': 0.5,                # 相关性良好阈值
        'corr_acceptable': 0.2,          # 相关性可接受阈值
        'front_ratio_good': 0.6,         # 前半段变化比例良好阈值
        'front_ratio_acceptable': 0.4,   # 前半段变化比例可接受阈值
        
        # 综合判定阈值
        'quality_pass_threshold': 0.6,   # 质量评分通过阈值
        'osc_ratio_pass': 0.5,           # 振荡比通过阈值
        
        # 稳态分析阈值
        'steady_osc_ratio': 0.3,         # 稳态振荡比阈值
        'steady_settling_quality': 0.5,  # 稳态收敛质量阈值
        'steady_r2': 0.4,                # 稳态R²阈值
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
        'ti_max': 120.0,                 # Ti最大值（秒）
        
        # Td约束
        'td_max_ratio': 0.25,            # Td最大比例（相对于Ti）
        
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
    # 模型参数边界配置
    # 注意：K 允许负值以支持反向作用系统（如制冷、减压等）
    # ============================================================
    MODEL_BOUNDS = {
        # FOPDT: K/(Ts+1)*e^(-Ls) - 一阶加纯滞后
        'FOPDT': {
            'initial': ([-10.0, 1.0, 0.0], [10.0, 500.0, 50.0]),
            'retry': ([-20.0, 0.5, 0.0], [20.0, 1000.0, 100.0]),
            'clip': [(-10.0, 10.0), (1.0, 500.0), (0.0, 50.0)]
        },
        # FO: K/(Ts+1) - 纯一阶模型（无滞后）
        'FO': {
            'initial': ([-10.0, 1.0], [10.0, 500.0]),
            'retry': ([-20.0, 0.5], [20.0, 1000.0]),
            'clip': [(-10.0, 10.0), (1.0, 500.0)]
        },
        # SO: K/((T1s+1)(T2s+1)) - 纯二阶模型（无滞后）
        'SO': {
            'initial': ([-10.0, 0.5, 0.5], [10.0, 500.0, 500.0]),
            'retry': ([-20.0, 0.1, 0.1], [20.0, 1000.0, 1000.0]),
            'clip': [(-10.0, 10.0), (0.5, 500.0), (0.5, 500.0)]
        },
        # SOPDT: K/((T1s+1)(T2s+1))*e^(-Ls) - 二阶加纯滞后
        'SOPDT': {
            'initial': ([-10.0, 0.5, 0.5, 0.0], [10.0, 500.0, 500.0, 50.0]),
            'retry': ([-20.0, 0.1, 0.1, 0.0], [20.0, 1000.0, 1000.0, 100.0]),
            'clip': [(-10.0, 10.0), (0.5, 500.0), (0.5, 500.0), (0.0, 50.0)]
        },
        # FOPI: K/s * 1/(Ts+1) - 一阶积分模型
        'FO_INTEGRATOR': {
            'initial': ([-10.0, 0.0], [10.0, 50.0]),
            'retry': ([-20.0, 0.0], [20.0, 100.0]),
            'clip': [(-10.0, 10.0), (0.0, 50.0)]
        },
        # SOPI: K/s * 1/((T1s+1)(T2s+1)) - 二阶积分模型
        'SO_INTEGRATOR': {
            'initial': ([-10.0, 0.5, 0.5], [10.0, 500.0, 500.0]),
            'retry': ([-20.0, 0.1, 0.1], [20.0, 1000.0, 1000.0]),
            'clip': [(-10.0, 10.0), (0.5, 500.0), (0.5, 500.0)]
        },
        # HAMMERSTEIN: f(u) -> FOPDT - Hammerstein模型（多项式非线性）
        # 参数: [K, T1, L, a1, a2, a3] 其中 f(u) = a1*u + a2*u^2 + a3*u^3
        'HAMMERSTEIN': {
            'initial': ([-10.0, 1.0, 0.0, 0.5, -0.5, 0.0], [10.0, 500.0, 50.0, 2.0, 0.5, 0.5]),
            'retry': ([-20.0, 0.5, 0.0, 0.1, -1.0, -0.5], [20.0, 1000.0, 100.0, 5.0, 1.0, 1.0]),
            'clip': [(-10.0, 10.0), (1.0, 500.0), (0.0, 50.0), (0.1, 5.0), (-1.0, 1.0), (-0.5, 0.5)]
        },
        # DEADBAND_FOPDT: 死区 + FOPDT
        # 参数: [K, T1, L, deadband] 其中 deadband 是死区宽度
        'DEADBAND_FOPDT': {
            'initial': ([-10.0, 1.0, 0.0, 0.5], [10.0, 500.0, 50.0, 20.0]),
            'retry': ([-20.0, 0.5, 0.0, 0.1], [20.0, 1000.0, 100.0, 50.0]),
            'clip': [(-10.0, 10.0), (1.0, 500.0), (0.0, 50.0), (0.1, 50.0)]
        },
        # SAT_FOPDT: 饱和 + FOPDT
        # 参数: [K, T1, L, sat_low, sat_high] 其中 sat_low/sat_high 是饱和限幅
        'SAT_FOPDT': {
            'initial': ([-10.0, 1.0, 0.0, 0.0, 100.0], [10.0, 500.0, 50.0, 50.0, 100.0]),
            'retry': ([-20.0, 0.5, 0.0, 0.0, 50.0], [20.0, 1000.0, 100.0, 100.0, 150.0]),
            'clip': [(-10.0, 10.0), (1.0, 500.0), (0.0, 50.0), (0.0, 100.0), (0.0, 150.0)]
        }
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
    }
    
    # ============================================================
    # 数据预处理配置
    # ============================================================
    PREPROCESSING = {
        'filter_window': 5,                  # 滤波窗口大小（默认）
        'noise_threshold': 0.02,             # 噪声阈值
        'min_correlation': 0.15,             # 最小相关系数
        'outlier_factor': 2.0,               # 异常值因子（IQR倍数）
        'change_point_threshold': 0.1,       # MV变化点检测阈值
        
        # ========== 自适应滤波配置 ==========
        'adaptive_filter': {
            'enabled': True,                 # 是否启用自适应滤波
            # 滤波窗口范围
            'window_min': 3,                 # 最小窗口（低噪声/低振荡）
            'window_max': 15,                # 最大窗口（高噪声/高振荡）
            'window_default': 5,             # 默认窗口
            # 振荡程度阈值
            'oscillation_low': 0.3,          # 低振荡阈值
            'oscillation_high': 0.7,         # 高振荡阈值
            # 噪声程度阈值
            'noise_low': 0.05,               # 低噪声阈值
            'noise_high': 0.15,              # 高噪声阈值
            # 滤波方法选择
            'method_by_oscillation': {
                'low': 'moving_average',     # 低振荡用移动平均
                'medium': 'moving_average',  # 中振荡用移动平均
                'high': 'median',            # 高振荡用中值滤波（抗脉冲）
            },
            # 保护阶跃响应的配置
            'preserve_step': True,           # 是否保护阶跃边缘
            'step_detection_threshold': 0.1, # 阶跃检测阈值（相对MV范围）
        },
        
        # 质量评分权重
        'quality_weights': {
            'correlation': 0.25,             # 相关性权重
            'noise': 0.20,                   # 噪声权重
            'trend': 0.20,                   # 趋势一致性权重
            'nonlinearity': 0.20,            # 非线性惩罚权重
            'step_response': 0.15,           # 阶跃响应奖励权重
        },
        
        # 质量等级阈值
        'quality_good_threshold': 0.7,       # 良好质量阈值
        'quality_medium_threshold': 0.4,     # 中等质量阈值
        
        # 复杂度乘数
        'complexity_multipliers': {
            'many_sv_changes': 1.3,          # SV变化次数>5
            'some_sv_changes': 1.1,          # SV变化次数>2
            'high_oscillation': 1.4,         # 高振荡
            'medium_oscillation': 1.2,       # 中振荡
            'high_extrema': 1.3,             # 高峰谷密度
            'medium_extrema': 1.1,           # 中峰谷密度
        },
    }
