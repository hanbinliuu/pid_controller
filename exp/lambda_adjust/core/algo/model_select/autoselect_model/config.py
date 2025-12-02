"""
模型检测配置

集中管理所有阈值和配置参数。
"""

from dataclasses import dataclass


@dataclass
class ModelSelectionConfig:
    """模型选择配置"""
    # FOPDT 相关阈值
    fopdt_l_significant_threshold: float = 0.8  # L参数显著阈值
    fopdt_l_large_threshold: float = 2.0  # L参数很大阈值
    
    # Second Order 相关阈值
    second_order_t1_t2_ratio_threshold: float = 0.75  # T1/T2比值阈值（小于此值认为差异明显）
    second_order_t1_t2_ratio_very_different: float = 0.6  # T1/T2差异非常明显
    second_order_t1_t2_ratio_similar: float = 0.85  # T1/T2相似（接近1）
    second_order_min_time_constant: float = 0.5  # 最小时间常数
    second_order_max_time_constant: float = 1000.0  # 最大时间常数
    
    # BIC 差异阈值
    bic_diff_large: float = 1000.0  # BIC差异很大（直接选择）
    bic_diff_medium: float = 500.0  # BIC差异中等
    bic_diff_small: float = 30.0  # BIC差异小
    
    # R² 差异阈值
    r2_diff_large: float = 0.008  # R²差异很大
    r2_diff_medium: float = 0.005  # R²差异中等
    r2_diff_small: float = 0.003  # R²差异小
    
    # First Order -> FOPDT 阈值
    first_to_fopdt_bic_threshold: float = 10.0
    first_to_fopdt_r2_threshold: float = 0.005
    
    # FOPDT -> Second Order 阈值（根据fopdt的L参数动态调整）
    fopdt_to_second_bic_thresholds: dict = None  # 根据L参数动态设置
    fopdt_to_second_r2_thresholds: dict = None
    
    # First Order -> Second Order 阈值
    first_to_second_bic_threshold_large: float = 70.0
    first_to_second_bic_threshold_medium: float = 35.0
    first_to_second_bic_threshold_small: float = 10.0
    first_to_second_r2_threshold_large: float = 0.003
    first_to_second_r2_threshold_medium: float = 0.005
    first_to_second_r2_threshold_small: float = 0.007
    
    # 默认阈值
    default_bic_threshold: float = 25.0
    default_r2_threshold: float = 0.015
    
    def __post_init__(self):
        """初始化动态阈值"""
        if self.fopdt_to_second_bic_thresholds is None:
            self.fopdt_to_second_bic_thresholds = {
                'small_l': (30.0, 15.0, 8.0),  # L < 1.0: (large, medium, small)
                'medium_l': (40.0, 20.0, 12.0),  # 1.0 <= L < 2.0
                'large_l': (50.0, 25.0, 15.0)  # L >= 2.0
            }
        
        if self.fopdt_to_second_r2_thresholds is None:
            self.fopdt_to_second_r2_thresholds = {
                'small_l': (0.004, 0.006, 0.008),
                'medium_l': (0.005, 0.007, 0.009),
                'large_l': (0.006, 0.008, 0.010)
            }
    
    def get_fopdt_to_second_thresholds(self, fopdt_l: float, bic_diff: float):
        """根据fopdt的L参数和BIC差异获取阈值"""
        if fopdt_l < 1.0:
            thresholds = self.fopdt_to_second_bic_thresholds['small_l']
            r2_thresholds = self.fopdt_to_second_r2_thresholds['small_l']
        elif fopdt_l < 2.0:
            thresholds = self.fopdt_to_second_bic_thresholds['medium_l']
            r2_thresholds = self.fopdt_to_second_r2_thresholds['medium_l']
        else:
            thresholds = self.fopdt_to_second_bic_thresholds['large_l']
            r2_thresholds = self.fopdt_to_second_r2_thresholds['large_l']
        
        if bic_diff > thresholds[0]:
            return thresholds[0], r2_thresholds[0]
        elif bic_diff > thresholds[1]:
            return thresholds[1], r2_thresholds[1]
        else:
            return thresholds[2], r2_thresholds[2]


# 全局配置实例
default_config = ModelSelectionConfig()

