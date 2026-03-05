"""
振荡整定置信度模块 (Oscillation Tuning Confidence Module)
=======================================================

计算振荡整定方法的置信度评分 (0-1)。

仅评估振荡整定方法自身的可靠性，不包含闭环控制品质评分（那是 Layer 1 model_rating 的职责）。

评分维度（按权重）：
1. 数据质量   (40%) — 振荡比、原始数据质量、非线性程度
2. 参数边界   (30%) — PID参数是否触达边界
3. 方法可靠性 (30%) — 整定方法的可信程度
"""

from typing import Dict, List, Tuple

from ...config import Config
from ..core.data_classes import ClosedLoopMetrics


class OscillationRatingCalculator:
    """
    振荡整定置信度计算器
    
    计算振荡整定方法的置信度，评估整定结果的可靠性。
    """
    
    def calculate_method_confidence(self, pid_params: Dict, osc_info: Dict,
                                     osc_result: Dict) -> Tuple[float, Dict, List[str]]:
        """
        计算振荡整定的方法置信度 (0-1)
        
        仅评估振荡整定自身可信程度：
        1. 数据质量    - 40%
        2. 参数边界    - 30%
        3. 方法可靠性  - 30%
        
        Returns:
            (confidence, details, warnings) — confidence 范围 0.0~1.0
        """
        details = {'method': 'oscillation_tuning'}
        warnings = []
        
        # 1. 数据质量 (0-1)
        data_quality, quality_details = self._calculate_data_quality(osc_info, osc_result)
        details['data_quality'] = round(data_quality, 4)
        details.update(quality_details)
        
        # 2. 参数边界 (0-1)
        param_boundary = self._calculate_boundary_score(pid_params)
        details['param_boundary'] = round(param_boundary, 4)
        details['pb'] = round(pid_params.get('pb', 200), 2)
        
        # 3. 方法可靠性 (0-1)
        method_reliability = self._calculate_method_score(pid_params)
        details['method_reliability'] = round(method_reliability, 4)
        details['tuning_method'] = pid_params.get('method', 'unknown')
        
        # 综合置信度
        weights = {'data_quality': 0.4, 'param_boundary': 0.3, 'method_reliability': 0.3}
        confidence = (
            weights['data_quality'] * data_quality +
            weights['param_boundary'] * param_boundary +
            weights['method_reliability'] * method_reliability
        )
        
        # 应用特殊限制
        confidence, warnings = self._apply_special_limits(
            confidence, osc_info, osc_result, pid_params
        )
        
        confidence = round(min(1.0, max(0.0, confidence)), 4)
        details['confidence_weights'] = weights
        
        return confidence, details, warnings
    
    # 保留旧接口兼容性
    def calculate(self, is_stable: bool, cl_metrics: ClosedLoopMetrics,
                  pid_params: Dict, osc_info: Dict,
                  osc_result: Dict) -> Tuple[float, Dict, List[str]]:
        """
        兼容旧接口：返回 (model_rating, rating_details, warnings)
        
        model_rating 现在统一使用闭环性能评分 (Layer 1)
        """
        from ..core.performance_rating import calculate_control_performance
        
        # Layer 1: 统一闭环性能评分
        model_rating = calculate_control_performance(cl_metrics)
        
        # Layer 2: 方法置信度
        confidence, confidence_details, warnings = self.calculate_method_confidence(
            pid_params, osc_info, osc_result
        )
        
        rating_details = {
            'model_rating': model_rating,
            'method_confidence': confidence,
            'method_confidence_details': confidence_details,
            'warnings': warnings,
        }
        
        return model_rating, rating_details, warnings
    
    def _calculate_data_quality(self, osc_info: Dict, 
                                osc_result: Dict) -> Tuple[float, Dict]:
        """计算数据质量 (0-1)"""
        oscillation_ratio = osc_info.get('oscillation_ratio', 0.5)
        raw_data_quality = osc_result.get('data_quality', 0.5)
        nonlinearity = osc_result.get('nonlinearity', 0.0)
        
        # 振荡比评分 (越低越好)
        if oscillation_ratio < 0.4:
            osc_score = 0.9
        elif oscillation_ratio < 0.6:
            osc_score = 0.7 - (oscillation_ratio - 0.4) * 1.0
        elif oscillation_ratio < 0.8:
            osc_score = 0.5 - (oscillation_ratio - 0.6) * 1.0
        else:
            osc_score = 0.3 - (oscillation_ratio - 0.8) * 1.5
        
        # 原始数据质量因子
        quality_penalty = max(0, (0.4 - raw_data_quality) * 0.5)
        nonlin_penalty = max(0, (nonlinearity - 0.5) * 0.3)
        
        data_quality = osc_score - quality_penalty - nonlin_penalty
        data_quality = max(0.1, min(0.95, data_quality))
        
        details = {
            'oscillation_ratio': round(oscillation_ratio, 4),
            'raw_data_quality': round(raw_data_quality, 4),
            'nonlinearity': round(nonlinearity, 4)
        }
        
        return data_quality, details
    
    def _calculate_boundary_score(self, pid_params: Dict) -> float:
        """计算参数边界评分 (0-1)"""
        pb = pid_params.get('pb', 200)
        pb_min = Config.OSCILLATION_TUNING.get('pb_min', 120.0)
        pb_max = Config.OSCILLATION_TUNING.get('pb_max', 600.0)
        pb_range = pb_max - pb_min
        pb_margin = min(pb - pb_min, pb_max - pb) / (pb_range / 2) if pb_range > 0 else 0.5
        
        boundary_score = 0.5 + pb_margin * 0.5
        if pb <= pb_min * 1.05 or pb >= pb_max * 0.95:
            boundary_score = 0.3
        
        Ti = pid_params.get('Ti', 2.5)
        if Ti <= 1.6 or Ti >= 9.5:
            boundary_score -= 0.1
        
        return min(1.0, max(0.0, boundary_score))
    
    def _calculate_method_score(self, pid_params: Dict) -> float:
        """计算整定方法评分 (0-1)"""
        method = pid_params.get('method', 'unknown')
        
        if 'low_gain' in method or 'high_gain' in method:
            method_score = 0.5
        elif 'oscillation' in method:
            method_score = 0.6
        elif 'integrating' in method:
            method_score = 0.55
        else:
            method_score = 0.55
        
        if pid_params.get('Kd', 0) > 0:
            method_score += 0.05
        
        return min(1.0, method_score)
    
    def _apply_special_limits(self, confidence: float,
                              osc_info: Dict, osc_result: Dict,
                              pid_params: Dict) -> Tuple[float, List[str]]:
        """应用特殊情况限制"""
        warnings = []
        
        oscillation_ratio = osc_info.get('oscillation_ratio', 0.5)
        raw_data_quality = osc_result.get('data_quality', 0.5)
        nonlinearity = osc_result.get('nonlinearity', 0.0)
        valve_issues = osc_result.get('valve_issues', {})
        pb = pid_params.get('pb', 200)
        pb_min = Config.OSCILLATION_TUNING.get('pb_min', 120.0)
        pb_max = Config.OSCILLATION_TUNING.get('pb_max', 600.0)
        
        # 极高振荡
        if oscillation_ratio > 0.9:
            confidence = min(confidence, 0.5)
            warnings.append(f'极高振荡({oscillation_ratio:.0%})，建议人工排查根因')
        elif oscillation_ratio > 0.85:
            confidence = min(confidence, 0.6)
            warnings.append(f'高振荡({oscillation_ratio:.0%})')
        
        # 参数触达边界
        if pb <= pb_min * 1.02 or pb >= pb_max * 0.98:
            confidence = min(confidence, 0.5)
            warnings.append('PID参数触达边界')
        
        # 数据质量极差
        if raw_data_quality < 0.3:
            confidence = min(confidence, 0.5)
            warnings.append(f'数据质量极差({raw_data_quality:.2f})')
        
        # 高非线性
        if nonlinearity > 0.6:
            confidence = min(confidence, 0.55)
            warnings.append(f'高非线性({nonlinearity:.2f})，可能存在阀门问题')
        
        # 阀门问题
        if valve_issues.get('has_deadband', False):
            confidence = min(confidence, 0.55)
            warnings.append(f"检测到阀门死区({valve_issues.get('deadband_size', 0):.0%})")
        if valve_issues.get('has_stiction', False):
            confidence = min(confidence, 0.5)
            warnings.append(f"检测到阀门粘滞({valve_issues.get('stiction_severity', 0):.0%})")
        if valve_issues.get('has_saturation', False):
            confidence = min(confidence, 0.55)
            warnings.append(f"检测到阀门饱和({valve_issues.get('saturation_ratio', 0):.0%})")
        
        # 综合风险等级
        risk_factors = 0
        if oscillation_ratio > 0.85:
            risk_factors += 1
        if raw_data_quality < 0.35:
            risk_factors += 1
        if valve_issues.get('has_stiction', False) or valve_issues.get('has_deadband', False):
            risk_factors += 1
        
        if risk_factors >= 2:
            confidence = min(confidence, 0.4)
            warnings.append('❗多重风险因素，强烈建议人工排查')
        
        return confidence, warnings
