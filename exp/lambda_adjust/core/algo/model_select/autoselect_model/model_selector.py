"""
模型选择器

负责从多个拟合结果中选择最佳模型。
"""

import numpy as np
from typing import Dict, Tuple, Optional
import sys
import os

from .model_types import ModelType
from .config import ModelSelectionConfig, default_config


class ModelSelector:
    """模型选择器"""
    
    def __init__(self, config: Optional[ModelSelectionConfig] = None):
        """
        初始化选择器
        
        Args:
            config: 配置对象，如果为None则使用默认配置
        """
        self.config = config or default_config
    
    def validate_second_order_params(self, params: Dict[str, float]) -> bool:
        """
        验证二阶模型参数的合理性
        
        Args:
            params: 参数字典
            
        Returns:
            是否合理
        """
        t1 = params.get("T1", 0)
        t2 = params.get("T2", 0)
        k = params.get("K", 0)
        
        if t1 <= 0 or t2 <= 0 or k <= 0:
            return False
        if min(t1, t2) < self.config.second_order_min_time_constant:
            return False
        if max(t1, t2) > self.config.second_order_max_time_constant:
            return False
        return True
    
    def calculate_t1_t2_ratio(self, params: Dict[str, float]) -> float:
        """计算T1/T2比值"""
        t1 = params.get("T1", 0)
        t2 = params.get("T2", 0)
        if max(t1, t2) > 0:
            return min(t1, t2) / max(t1, t2)
        return 1.0
    
    def is_valid_second_order(self, params: Dict[str, float]) -> bool:
        """
        判断是否为有效的二阶模型
        
        注意：如果 T1 和 T2 非常接近（比值 > 0.9），说明数据可能是一阶模型，
        不应该被识别为二阶模型。
        """
        if not self.validate_second_order_params(params):
            return False
        ratio = self.calculate_t1_t2_ratio(params)
        t1 = params.get("T1", 0)
        t2 = params.get("T2", 0)
        
        # 如果 T1 和 T2 太接近（比值 > 0.9），不是真正的二阶模型
        # 这种情况通常表示数据实际上是一阶模型或FOPDT模型
        if ratio > 0.9:
            return False
        
        return (ratio < self.config.second_order_t1_t2_ratio_threshold and 
                min(t1, t2) > self.config.second_order_min_time_constant)
    
    def is_fopdt_l_significant(self, l_value: float) -> bool:
        """
        判断FOPDT的L参数是否显著
        
        注意：如果 L 非常小（< 0.3），说明数据可能是一阶模型，
        不应该被识别为FOPDT模型。
        """
        # L 必须大于阈值才认为是显著的
        if l_value < 0.3:
            return False
        return l_value > self.config.fopdt_l_significant_threshold
    
    def should_degrade_model(self, model_type: ModelType, params: Dict[str, float]) -> Optional[ModelType]:
        """
        检查模型是否应该降级为更简单的模型
        
        当复杂模型拟合得到简单模型的参数特征时，应该降级：
        - 二阶模型：如果 T1 ≈ T2，降级为一阶或FOPDT
        - FOPDT模型：如果 L ≈ 0，降级为一阶
        
        Args:
            model_type: 当前模型类型
            params: 模型参数
            
        Returns:
            应该降级到的模型类型，如果不需要降级则返回None
        """
        if model_type == ModelType.SECOND_ORDER:
            t1_t2_ratio = self.calculate_t1_t2_ratio(params)
            # 如果 T1 和 T2 非常接近（比值 > 0.9），降级为一阶模型
            if t1_t2_ratio > 0.9:
                return ModelType.FIRST_ORDER
            # 如果 T1 和 T2 比较接近（比值 > 0.85），可能是FOPDT
            elif t1_t2_ratio > 0.85:
                return ModelType.FOPDT
        
        if model_type == ModelType.FOPDT:
            l_value = params.get("L", 0)
            # 如果 L 非常小（< 0.3），降级为一阶模型
            if l_value < 0.3:
                return ModelType.FIRST_ORDER
        
        return None
    
    def get_thresholds_for_transition(self, 
                                     from_model: ModelType,
                                     to_model: ModelType,
                                     from_params: Dict[str, float],
                                     to_params: Dict[str, float],
                                     bic_diff: float) -> Tuple[float, float]:
        """
        获取模型转换的阈值
        
        Args:
            from_model: 源模型类型
            to_model: 目标模型类型
            from_params: 源模型参数
            to_params: 目标模型参数
            bic_diff: BIC差异
            
        Returns:
            (bic_threshold, r2_threshold)
        """
        # First Order -> FOPDT
        if from_model == ModelType.FIRST_ORDER and to_model == ModelType.FOPDT:
            return (self.config.first_to_fopdt_bic_threshold,
                    self.config.first_to_fopdt_r2_threshold)
        
        # FOPDT -> Second Order
        if from_model == ModelType.FOPDT and to_model == ModelType.SECOND_ORDER:
            fopdt_l = from_params.get("L", 0)
            if self.is_valid_second_order(to_params):
                return self.config.get_fopdt_to_second_thresholds(fopdt_l, bic_diff)
            else:
                # 无效的二阶模型，使用严格阈值
                if bic_diff > 200.0:
                    return 200.0, 0.012
                else:
                    return 60.0, 0.015
        
        # First Order -> Second Order
        if from_model == ModelType.FIRST_ORDER and to_model == ModelType.SECOND_ORDER:
            if self.is_valid_second_order(to_params):
                if bic_diff > self.config.first_to_second_bic_threshold_large:
                    return (self.config.first_to_second_bic_threshold_large,
                            self.config.first_to_second_r2_threshold_large)
                elif bic_diff > self.config.first_to_second_bic_threshold_medium:
                    return (self.config.first_to_second_bic_threshold_medium,
                            self.config.first_to_second_r2_threshold_medium)
                else:
                    return (self.config.first_to_second_bic_threshold_small,
                            self.config.first_to_second_r2_threshold_small)
            else:
                if bic_diff > 200.0:
                    return 200.0, 0.012
                else:
                    return 40.0, 0.015
        
        # 默认阈值
        return (self.config.default_bic_threshold,
                self.config.default_r2_threshold)
    
    def check_fopdt_condition(self,
                             fopdt_info: Dict,
                             current_best_info: Dict,
                             bic_diff: float,
                             r2_diff: float) -> bool:
        """
        检查FOPDT是否应该被选中
        
        Args:
            fopdt_info: FOPDT模型信息
            current_best_info: 当前最佳模型信息
            bic_diff: BIC差异（current_best - fopdt，如果fopdt更好则为正）
            r2_diff: R²差异（fopdt - current_best，如果fopdt更好则为正）
            
        Returns:
            是否应该选择FOPDT
        """
        l_value = fopdt_info["result"]["parameters"].get("L", 0)
        l_significant = self.is_fopdt_l_significant(l_value)
        
        if not l_significant:
            return False
        
        # 如果当前最佳是second_order，检查其T1/T2比值
        current_model_type = current_best_info.get("model_type")
        if current_model_type == ModelType.SECOND_ORDER:
            t1_other = current_best_info["result"]["parameters"].get("T1", 0)
            t2_other = current_best_info["result"]["parameters"].get("T2", 0)
            t1_t2_ratio_other = min(t1_other, t2_other) / max(t1_other, t2_other) if max(t1_other, t2_other) > 0 else 1.0
            
            # 如果second_order的T1/T2比值很大（接近1），且fopdt的L显著，选择fopdt
            if t1_t2_ratio_other > 0.75 and l_value > 1.5:
                if bic_diff > -80.0 or r2_diff > -0.004:
                    return True
        
        # L显著时的选择条件
        if bic_diff > -100.0 and r2_diff > 0.0005:
            return True
        elif bic_diff > 3.0 and r2_diff > 0.0003:
            return True
        elif abs(bic_diff) < 30.0 and r2_diff >= -0.0005:
            return True
        elif l_value > self.config.fopdt_l_large_threshold and bic_diff > -120.0 and r2_diff > -0.003:
            return True
        
        return False
    
    def check_second_order_condition(self,
                                    second_order_info: Dict,
                                    current_best_info: Dict,
                                    bic_diff: float,
                                    r2_diff: float) -> bool:
        """
        检查Second Order是否应该被选中
        
        Args:
            second_order_info: Second Order模型信息
            current_best_info: 当前最佳模型信息
            bic_diff: BIC差异
            r2_diff: R²差异
            
        Returns:
            是否应该选择Second Order
        """
        if not self.validate_second_order_params(second_order_info["result"]["parameters"]):
            return False
        
        t1_t2_ratio = self.calculate_t1_t2_ratio(second_order_info["result"]["parameters"])
        current_model_type = current_best_info.get("model_type")
        
        # 如果当前最佳是FOPDT，检查其L参数
        if current_model_type == ModelType.FOPDT:
            fopdt_l = current_best_info["result"]["parameters"].get("L", 0)
            
            if t1_t2_ratio < 0.7:
                if fopdt_l >= self.config.fopdt_l_significant_threshold:
                    if fopdt_l > self.config.fopdt_l_large_threshold:
                        return bic_diff > 45.0 and r2_diff > 0.007
                    else:
                        return bic_diff > 25.0 and r2_diff > 0.005
                else:
                    return (bic_diff > 12.0 and r2_diff > 0.003) or \
                           (bic_diff > 6.0 and r2_diff > 0.005)
            
            if t1_t2_ratio < 0.5:
                if fopdt_l < self.config.fopdt_l_significant_threshold:
                    return bic_diff > 8.0 or r2_diff > 0.004
                else:
                    return bic_diff > 18.0 or r2_diff > 0.005
            
            if 0.7 <= t1_t2_ratio < 0.8 and fopdt_l < 1.0:
                return bic_diff > 20.0 and r2_diff > 0.006
        
        return False
    
    def should_select_model(self,
                           candidate_info: Dict,
                           current_best_info: Dict,
                           bic_diff: float,
                           r2_diff: float) -> bool:
        """
        判断是否应该选择候选模型
        
        Args:
            candidate_info: 候选模型信息（包含model_type, result等）
            current_best_info: 当前最佳模型信息
            bic_diff: BIC差异（current_best - candidate，如果candidate更好则为正）
            r2_diff: R²差异（candidate - current_best，如果candidate更好则为正）
            
        Returns:
            是否应该选择候选模型
        """
        candidate_type = candidate_info.get("model_type")
        current_type = current_best_info.get("model_type")
        
        # 获取阈值
        bic_threshold, r2_threshold = self.get_thresholds_for_transition(
            current_type, candidate_type,
            current_best_info["result"]["parameters"],
            candidate_info["result"]["parameters"],
            bic_diff
        )
        
        # 基本条件：BIC和R²都满足阈值
        basic_condition = (bic_diff > bic_threshold and r2_diff > r2_threshold)
        
        # FOPDT特殊条件
        if candidate_type == ModelType.FOPDT:
            fopdt_condition = self.check_fopdt_condition(
                candidate_info, current_best_info, bic_diff, r2_diff
            )
            if fopdt_condition:
                return True
        
        # Second Order特殊条件
        if candidate_type == ModelType.SECOND_ORDER:
            # 参数验证
            if not self.validate_second_order_params(candidate_info["result"]["parameters"]):
                return False
            
            # 如果当前最佳是FOPDT，需要特殊处理
            if current_type == ModelType.FOPDT:
                fopdt_l = current_best_info["result"]["parameters"].get("L", 0)
                t1_t2_ratio = self.calculate_t1_t2_ratio(candidate_info["result"]["parameters"])
                
                # BIC差异非常大，直接选择
                if bic_diff > self.config.bic_diff_large:
                    return True
                
                # 根据T1/T2比值和fopdt的L参数判断
                if fopdt_l > 1.5:
                    if t1_t2_ratio < 0.75:
                        return basic_condition or (bic_diff > 40.0 and r2_diff > 0.006)
                    elif t1_t2_ratio > 0.85:
                        return False
                    elif t1_t2_ratio > 0.8:
                        return bic_diff > 200.0 or (bic_diff > 100.0 and r2_diff > 0.007)
                    else:
                        return bic_diff > 80.0 and r2_diff > 0.006
                elif fopdt_l > 0.8:
                    if t1_t2_ratio < 0.6:
                        return basic_condition or (bic_diff > 20.0 and r2_diff > 0.004) or \
                               self.check_second_order_condition(candidate_info, current_best_info, bic_diff, r2_diff)
                    else:
                        return basic_condition or self.check_second_order_condition(candidate_info, current_best_info, bic_diff, r2_diff)
                else:
                    if t1_t2_ratio < 0.7:
                        return basic_condition or (bic_diff > 15.0 and r2_diff > 0.003) or \
                               self.check_second_order_condition(candidate_info, current_best_info, bic_diff, r2_diff)
                    else:
                        return basic_condition or self.check_second_order_condition(candidate_info, current_best_info, bic_diff, r2_diff)
            
            # Second Order特殊条件
            second_order_condition = self.check_second_order_condition(
                candidate_info, current_best_info, bic_diff, r2_diff
            )
            if second_order_condition:
                return True
        
        # 默认：基本条件满足即可
        return basic_condition

