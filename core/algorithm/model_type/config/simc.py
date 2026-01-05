"""
SIMC 整定配置 (Skogestad Internal Model Control)
================================================

SIMC 是工业界广泛认可的整定方法，核心特点：
1. 只有一个调节参数 τc（闭环时间常数）
2. Ti 有上限约束，防止慢系统积分时间过长
3. 统一处理各类过程模型
"""

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
