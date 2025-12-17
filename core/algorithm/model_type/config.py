"""
模型配置模块 (Model Configuration Module)
=========================================

本模块定义了模型辨识所需的全局配置参数，包括：

1. **模型类型枚举**: 支持的过程模型类型定义
2. **参数边界**: 各模型参数的优化边界和约束
3. **阈值配置**: 数据质量、拟合评估等阈值参数
4. **整定配置**: 振荡整定、闭环验证等配置

配置分组
--------
- OSCILLATION_TUNING: 振荡整定相关配置
- DATA_QUALITY: 数据质量评估阈值
- MODEL_FITTING: 模型拟合质量阈值
- CLOSED_LOOP: 闭环稳定性验证配置
- SEGMENT_PROCESSING: 扰动段处理配置
- OPTIMIZATION: 优化算法配置
- PARAMETER_CONSTRAINTS: 参数约束配置
- MODEL_BOUNDS: 各模型的参数边界
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


class Config:
    """系统配置类：包含模型辨识相关的配置参数"""
    EPSILON = 1e-9
    
    # ============================================================
    # 振荡整定配置
    # ============================================================
    OSCILLATION_TUNING = {
        # 触发振荡整定的条件
        'oscillation_ratio_threshold': 0.1,  # 振荡比阈值，超过此值认为是高振荡数据
        'r2_failure_threshold': 0.3,         # R² 阈值，低于此值认为模型拟合失败
        
        # 振荡周期检测
        'period_min': 1.0,                   # 最小周期（秒）
        'period_max': 120.0,                 # 最大周期（秒）
        
        # 闭环仿真参数
        'sp_initial': 50.0,                  # 设定值初始值
        'sp_final': 60.0,                    # 设定值最终值
        'pv_initial': 50.0,                  # 过程值初始值
        
        # ========== 自适应整定参数（渐进式策略，更通用） ==========
        # 渐进式pb调整：pb_final = pb_base * (1 + oscillation_ratio * pb_gradient)
        # 例如：振荡比=0.68 → pb乘以 1 + 0.68*3 = 3.04
        'pb_gradient': 3.0,                   # pb渐进系数，振荡比每增加0.1，pb增加30%
        'pb_oscillation_start': 0.3,          # 开始应用渐进调整的振荡比阈值
        
        # 自适应微分作用
        'enable_adaptive_derivative': True,   # 是否启用自适应微分
        'derivative_factor': 0.4,             # Kd = Kp * Pu * derivative_factor (增大以更好抑制振荡)
        'derivative_oscillation_threshold': 0.3,  # 振荡比超过此值才加微分（降低阈值）
        
        # pb范围扩展（更保守）
        'pb_min': 80.0,                       # pb下限（提高以确保保守）
        'pb_max': 500.0,                      # pb上限（允许更保守）
        
        # 额外保守因子（针对临界法整定）
        'critical_method_safety_factor': 1.5, # 临界法额外安全系数
    }
    
    # ============================================================
    # 数据质量配置
    # ============================================================
    DATA_QUALITY = {
        'noise_threshold': 0.1,              # 噪声比阈值
        'correlation_threshold': 0.3,        # 相关性阈值
        'nonlinearity_threshold': 0.5,       # 非线性阈值
        'oscillation_warning_threshold': 0.3,  # 振荡警告阈值
        'min_data_points': 30,               # 最小数据点数
    }
    
    # ============================================================
    # 模型拟合配置
    # ============================================================
    MODEL_FITTING = {
        'r2_good_threshold': 0.8,            # R² 良好阈值
        'r2_acceptable_threshold': 0.5,      # R² 可接受阈值
        'r2_poor_threshold': 0.3,            # R² 较差阈值
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
        'min_pv_range': 0.5,             # 最小PV变化范围
        'min_mv_range': 0.1,             # 最小MV变化范围
        'correlation_threshold': 0.1,    # 相关性阈值（阶跃响应检测）
        'severe_nonlinearity': 0.7,      # 严重非线性阈值
        'severe_oscillation': 0.75,      # 严重振荡阈值
        'low_quality_threshold': 0.25,   # 低质量分阈值
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
        'filter_window': 5,                  # 滤波窗口大小
        'noise_threshold': 0.02,             # 噪声阈值
        'min_correlation': 0.15,             # 最小相关系数
        'outlier_factor': 2.0,               # 异常值因子（IQR倍数）
        'change_point_threshold': 0.1,       # MV变化点检测阈值
        
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
