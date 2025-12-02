"""
稳定性检测配置
可以根据实际工况调整这些阈值
"""

# 非稳态检测阈值配置
STABILITY_THRESHOLDS = {
    # 振荡检测：误差标准差阈值
    # 如果误差的标准差超过此值，认为系统在振荡
    # 建议值：1.5-3.0（根据工艺要求调整）
    # 调整为0.8以检测OPC UA服务器的周期性扰动（幅度3.0）
    'oscillation_std': 0.8,
    
    # 偏差检测：平均误差阈值
    # 如果平均误差（|PV-SV|）超过此值，认为系统偏离设定值
    # 建议值：2.0-5.0（根据控制精度要求调整）
    # 液位控制允许较大误差，调整为3.0
    'offset_mean': 3.0,
    
    # SV变化检测：SV变化范围阈值
    # 如果SV在检测窗口内变化超过此值，认为设定值频繁变化
    # 建议值：5.0-10.0（根据工艺特点调整）
    'sv_change_range': 5.0,
    
    # 检测窗口大小（数据点数）
    # 用于计算统计指标的数据点数量
    # 建议值：20-60（采样间隔1秒时，相当于20-60秒的数据）
    'window_size': 20,
}

# 稳定性监控配置
MONITORING_CONFIG = {
    # 监控间隔（秒）
    'check_interval': 5,
    
    # 最小数据点数
    # 少于此数量的数据点不进行稳定性检测
    'min_data_points': 20,
    
    # 是否启用调试日志
    'debug_logging': True,  # 启用调试日志以观察检测过程
}


def get_threshold(key: str, default=None):
    """获取阈值配置"""
    return STABILITY_THRESHOLDS.get(key, default)


def update_threshold(key: str, value: float):
    """更新阈值配置"""
    if key in STABILITY_THRESHOLDS:
        STABILITY_THRESHOLDS[key] = value
        return True
    return False


def get_all_thresholds():
    """获取所有阈值配置"""
    return STABILITY_THRESHOLDS.copy()


# 不同工况的预设配置
PRESET_CONFIGS = {
    'strict': {
        'oscillation_std': 0.5,
        'offset_mean': 1.0,
        'sv_change_range': 2.0,
        'description': '严格模式：适用于高精度控制要求'
    },
    'normal': {
        'oscillation_std': 1.5,
        'offset_mean': 3.0,
        'sv_change_range': 5.0,
        'description': '正常模式：适用于一般工业控制'
    },
    'loose': {
        'oscillation_std': 3.0,
        'offset_mean': 5.0,
        'sv_change_range': 10.0,
        'description': '宽松模式：适用于大惯性、慢响应系统'
    }
}


def apply_preset(preset_name: str):
    """应用预设配置"""
    if preset_name in PRESET_CONFIGS:
        preset = PRESET_CONFIGS[preset_name]
        STABILITY_THRESHOLDS['oscillation_std'] = preset['oscillation_std']
        STABILITY_THRESHOLDS['offset_mean'] = preset['offset_mean']
        STABILITY_THRESHOLDS['sv_change_range'] = preset['sv_change_range']
        return True
    return False
