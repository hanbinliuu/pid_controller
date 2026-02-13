"""
回路类型参数预设 (Loop Type Presets)
====================================

针对石化行业不同回路类型的差异化参数预设。

回路特性说明：
- Flow (流量): 快速响应要求，积分特性，允许激进整定
- Temperature (温度): 慢速系统，大滞后，需要保守整定
- Level (液位): 积分过程，需要平滑控制，避免MV频繁动作
- Pressure (压力): 快速响应要求，可能需要微分

使用方法：
在整定逻辑中通过 loop_type 获取对应预设，覆盖默认参数。
"""

LOOP_TYPE_PRESETS = {
    # ========== 流量回路 ==========
    # 特点：快速响应、积分特性强、允许较激进整定
    'flow': {
        'pb_min': 60.0,           # 流量需要快速响应，从50.0调高到60.0以增加稳定性
        'pb_max': 300.0,          # 上限提高 [从200提高到300，应对大滞后流量回路]
        'tau_c_factor': 1.2,      # τc较小，快速响应
        'safety_factor': 1.0,     # 核心公式已修，恢复标准系数 (0.95 -> 1.0)
        'ti_multiplier': 1.0,     # Ti恢复标准 (1.15 -> 1.0)
        'td_enable': False,       # 流量严禁微分 [行业铁律]
        'aggressive': True,       # 允许激进整定
        'description': '流量回路：快速响应，积分特性',
    },
    
    # ========== 温度回路 ==========
    # 特点：慢速系统、大滞后、热容量大
    'temperature': {
        'pb_min': 80.0,           # 温度系统较慢，PB可以稍大
        'pb_max': 300.0,          # 允许较大PB应对大滞后 [从450降低到300，增加增益]
        'tau_c_factor': 2.0,      # τc较大，避免振荡 [保持保守]
        'safety_factor': 1.1,     # 保守整定 [降低：1.2→1.1，避免PB叠加过大]
        'ti_multiplier': 1.5,     # Ti适度增大 [降低：2.2→1.5，避免响应过慢]
        'td_enable': True,        # 温度回路可用微分改善响应
        'td_ratio': 0.25,         # Td = Ti * 0.25 [增强微分作用]
        'td_max': 15.0,           # Td绝对上限15s [工业温度回路标准]
        'aggressive': False,      # 保守整定
        'description': '温度回路：慢速系统，大热容量',
    },
    
    # ========== 液位回路 ==========
    # 特点：积分过程、需平滑控制、避免MV频繁动作
    'level': {
        'pb_min': 100.0,          # 液位积分过程，需要较大PB
        'pb_max': 300.0,          # 允许略微激进 [400 -> 300，避免超时]
        'tau_c_factor': 2.0,      # τc加快 [3.0 -> 2.0，加速响应，减少超时]
        'safety_factor': 1.0,     # 安全系数降低 [1.1 -> 1.0，避免过于保守]
        'ti_multiplier': 1.5,     # Ti适度增大 [2.0 -> 1.5，加快积分作用]
        'td_enable': False,       # 液位一般不用微分
        'aggressive': False,      # 保守整定 [True -> False, 激进整定导致不稳定]
        'integrating_mode': True, # 标记为积分过程
        'description': '液位回路：积分过程，平滑控制',
    },
    
    # ========== 压力回路 ==========
    # 特点：快速响应、可能有压缩性
    'pressure': {
        'pb_min': 80.0,           # 压力需要快速响应，从70.0提高到80.0以增强抗噪性
        'pb_max': 300.0,          # 上限提高 [从200提高到300，应对高增益压力回路]
        'tau_c_factor': 1.5,      # τc加大 [从1.2提高到1.5，增加阻尼，应对高增益敏感]
        'safety_factor': 1.0,     # 恢复标准 (1.03 -> 1.0)
        'ti_multiplier': 1.05,    # Ti标准 (1.1 -> 1.05)
        'td_enable': True,        # 可用微分改善响应
        'td_ratio': 0.15,         # Td = Ti * 0.15
        'td_max': 10.0,           # Td绝对上限10s [工业压力回路标准]
        'aggressive': False,      # 不过于激进 [从true改为false]
        'description': '压力回路：快速响应，需及时调节',
    },
    
    # ========== 默认/未知回路 ==========
    'default': {
        'pb_min': 60.0,           # 默认使用优化后的全局值
        'pb_max': 300.0,          # 中等范围
        'tau_c_factor': 1.5,      # 中等响应速度
        'safety_factor': 1.05,    # 略微保守
        'ti_multiplier': 1.0,     # 标准Ti
        'td_enable': False,       # 默认不用微分
        'aggressive': False,      # 默认不激进
        'description': '默认配置',
    },
}


def get_loop_preset(loop_type: str) -> dict:
    """
    获取指定回路类型的参数预设
    
    Args:
        loop_type: 回路类型 ('flow', 'temperature', 'level', 'pressure')
    
    Returns:
        dict: 参数预设字典
    """
    loop_type_lower = loop_type.lower() if loop_type else 'default'
    return LOOP_TYPE_PRESETS.get(loop_type_lower, LOOP_TYPE_PRESETS['default'])


def get_adjusted_pb_range(loop_type: str, base_pb_min: float, base_pb_max: float) -> tuple:
    """
    根据回路类型调整PB范围
    
    Args:
        loop_type: 回路类型
        base_pb_min: 基础PB下限
        base_pb_max: 基础PB上限
    
    Returns:
        tuple: (调整后的pb_min, 调整后的pb_max)
    """
    preset = get_loop_preset(loop_type)
    # 使用回路预设的范围，但不低于基础范围的一半
    adjusted_min = max(preset['pb_min'], base_pb_min * 0.5)
    adjusted_max = min(preset['pb_max'], base_pb_max * 1.2)
    return adjusted_min, adjusted_max


def get_adjusted_safety_factor(loop_type: str, base_safety_factor: float) -> float:
    """
    根据回路类型调整安全系数
    
    Args:
        loop_type: 回路类型
        base_safety_factor: 基础安全系数
    
    Returns:
        float: 调整后的安全系数
    """
    preset = get_loop_preset(loop_type)
    # 预设的safety_factor作为乘数
    return base_safety_factor * preset['safety_factor']
