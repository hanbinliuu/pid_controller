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
        'pb_min': 40.0,           
        'pb_max': 300.0,          
        'tau_c_factor': 1.0,      # [优化] 1.2 -> 1.0：流量需要极快响应，加速比例作用
        'safety_factor': 1.0,     # [优化] 1.05 -> 1.0：解除过度保守限制
        'ti_multiplier': 1.0,     
        'ti_max': 20.0,           
        'td_enable': False,       
        'aggressive': True,       
        'description': '流量回路：快速响应，积分特性',
    },
    
    # ========== 温度回路 ==========
    # 特点：慢速系统、大滞后、热容量大
    'temperature': {
        'pb_min': 60.0,           
        'pb_max': 300.0,          
        'tau_c_factor': 1.5,      # [优化] 2.0 -> 1.5：加速温度回稳，2.0 会导致超长拖尾使得评分跳水
        'safety_factor': 1.1,     
        'ti_multiplier': 1.2,     # [优化] 1.5 -> 1.2：缩小积分时间，加速消除余差
        'td_enable': True,        
        'td_ratio': 0.25,         
        'td_max': 15.0,           
        'aggressive': False,      
        'description': '温度回路：慢速系统，大热容量',
    },
    
    # ========== 液位回路 ==========
    # 特点：积分过程、需平滑控制、避免MV频繁动作
    'level': {
        'pb_min': 40.0,          
        'pb_max': 2000.0,         
        'ti_max': 3600.0,         
        'tau_c_factor': 1.5,      # [优化] 2.0 -> 1.5：稍微收紧液位响应周期，提升稳态恢复得分
        'safety_factor': 1.0,     
        'ti_multiplier': 0.5,     # [优化] 1.2 -> 0.5：适配需要较强积分消除误差的近积分自平衡液位槽
        'td_enable': False,       
        'aggressive': False,      
        'integrating_mode': True, 
        'description': '液位回路：积分过程，平滑控制',
    },
    
    # ========== 压力回路 ==========
    # 特点：快速响应、可能有压缩性
    'pressure': {
        'pb_min': 80.0,           
        'pb_max': 300.0,          
        'tau_c_factor': 1.2,      # [优化] 1.8 -> 1.2：压力回路通常较快，大幅增加系统带宽
        'safety_factor': 1.0,     # [优化] 1.05 -> 1.0
        'ti_multiplier': 1.0,     # [优化] 1.05 -> 1.0
        'ti_max': 50.0,           
        'td_enable': True,        
        'td_ratio': 0.15,         
        'td_max': 10.0,           
        'aggressive': False,      
        'description': '压力回路：快速响应，需及时调节',
    },
    
    # ========== 默认/未知回路 ==========
    'default': {
        'pb_min': 40.0,           # 默认 pb_min 放宽 [60→40，与 flow 对齐]
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
