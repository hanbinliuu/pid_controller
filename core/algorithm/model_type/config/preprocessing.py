"""
预处理配置 (Preprocessing Configuration)
========================================

数据预处理、扰动段处理、整定段检测相关配置。
"""

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
    
    # ========== SV 阶跃段检测参数 ==========
    'sv_min_step_size': 0.5,         # SV 最小阶跃幅度
    'sv_stable_window': 20,          # SV 稳定窗口大小（采样点数）
    'sv_pre_step_points': 30,        # 阶跃前需要的稳态点数
    'sv_max_response_time': 3000,    # SV 阶跃后最大响应时间（采样点数）
    'sv_min_response_time': 30,      # SV 阶跃后最小响应时间（采样点数）
    'sv_closed_loop_t1_factor': 3.0, # 闭环T1→开环T1修正系数（闭环T1通常为开环的1/2~1/3）
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
