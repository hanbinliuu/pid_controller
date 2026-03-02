"""
振荡整定评分模块 (Oscillation Rating Module)
============================================

本模块封装振荡整定的综合评分逻辑。

从 oscillation_tuner.py 拆分出来，提高可维护性。

核心功能
--------
1. **闭环稳定性评分**: 基于超调量、调节时间、振荡次数等
2. **数据质量评分**: 基于振荡比、原始数据质量、非线性程度
3. **参数边界评分**: 检查PID参数是否触达边界
4. **整定方法评分**: 评估整定方法的可靠性
5. **综合评分**: 加权计算最终评分
"""

from typing import Dict, List, Tuple

from ...config import Config
from ..core.data_classes import ClosedLoopMetrics


class OscillationRatingCalculator:
    """
    振荡整定评分计算器
    
    计算振荡整定的综合评分，评估整定结果的可靠性。
    """
    
    def calculate(self, is_stable: bool, cl_metrics: ClosedLoopMetrics,
                  pid_params: Dict, osc_info: Dict,
                  osc_result: Dict) -> Tuple[float, Dict, List[str]]:
        """
        计算振荡整定的综合评分
        
        Args:
            is_stable: 闭环是否稳定
            cl_metrics: 闭环性能指标
            pid_params: PID参数
            osc_info: 振荡信息
            osc_result: 振荡整定结果
            
        Returns:
            (model_rating, rating_details, warnings) 元组
        """
        rating_details = {}
        
        # 1. 闭环稳定性评分 (0-10) - 权重 35%
        stability_score = self._calculate_stability_score(is_stable, cl_metrics)
        rating_details['stability_score'] = round(stability_score, 2)
        
        # 2. 数据质量评分 (0-10) - 权重 25%
        data_quality_score, quality_details = self._calculate_data_quality_score(
            osc_info, osc_result
        )
        rating_details['data_quality_score'] = round(data_quality_score, 2)
        rating_details.update(quality_details)
        
        # 3. 参数边界评分 (0-10) - 权重 20%
        boundary_score = self._calculate_boundary_score(pid_params)
        rating_details['boundary_score'] = round(boundary_score, 2)
        rating_details['pb'] = round(pid_params.get('pb', 200), 2)
        
        # 4. 整定方法评分 (0-10) - 权重 20%
        method_score = self._calculate_method_score(pid_params)
        rating_details['method_score'] = round(method_score, 2)
        rating_details['method'] = pid_params.get('method', 'unknown')
        
        # 综合评分
        weights = {
            'stability': 0.35,
            'data_quality': 0.25,
            'boundary': 0.20,
            'method': 0.20
        }
        
        model_rating = (
            weights['stability'] * stability_score +
            weights['data_quality'] * data_quality_score +
            weights['boundary'] * boundary_score +
            weights['method'] * method_score
        )
        
        # 特殊情况限制和警告
        model_rating, warnings = self._apply_special_limits(
            model_rating, is_stable, osc_info, osc_result, pid_params
        )
        
        model_rating = round(min(10.0, max(0.0, model_rating)), 1)
        rating_details['weights'] = weights
        rating_details['warnings'] = warnings
        
        return model_rating, rating_details, warnings
    
    def _calculate_stability_score(self, is_stable: bool, 
                                   cl_metrics: ClosedLoopMetrics) -> float:
        """计算闭环稳定性评分"""
        from ..core.performance_rating import calculate_control_performance
        if cl_metrics and hasattr(cl_metrics, 'is_stable'):
            cl_metrics.is_stable = is_stable
        return calculate_control_performance(cl_metrics)
    
    def _calculate_data_quality_score(self, osc_info: Dict, 
                                      osc_result: Dict) -> Tuple[float, Dict]:
        """计算数据质量评分"""
        oscillation_ratio = osc_info.get('oscillation_ratio', 0.5)
        raw_data_quality = osc_result.get('data_quality', 0.5)
        nonlinearity = osc_result.get('nonlinearity', 0.0)
        
        # 基于振荡比的评分
        if oscillation_ratio < 0.4:
            osc_score = 8.0
        elif oscillation_ratio < 0.6:
            osc_score = 7.0 - (oscillation_ratio - 0.4) * 5
        elif oscillation_ratio < 0.8:
            osc_score = 6.0 - (oscillation_ratio - 0.6) * 7.5
        else:
            osc_score = 4.5 - (oscillation_ratio - 0.8) * 15
        
        # 原始数据质量因子
        quality_penalty = max(0, (0.4 - raw_data_quality) * 3)
        nonlin_penalty = max(0, (nonlinearity - 0.5) * 2)
        
        data_quality_score = osc_score - quality_penalty - nonlin_penalty
        data_quality_score = max(1.0, min(8.0, data_quality_score))
        
        details = {
            'oscillation_ratio': round(oscillation_ratio, 2),
            'raw_data_quality': round(raw_data_quality, 2),
            'nonlinearity': round(nonlinearity, 2)
        }
        
        return data_quality_score, details
    
    def _calculate_boundary_score(self, pid_params: Dict) -> float:
        """计算参数边界评分"""
        pb = pid_params.get('pb', 200)
        pb_min = Config.OSCILLATION_TUNING.get('pb_min', 120.0)
        pb_max = Config.OSCILLATION_TUNING.get('pb_max', 600.0)
        pb_range = pb_max - pb_min
        pb_margin = min(pb - pb_min, pb_max - pb) / (pb_range / 2)
        
        boundary_score = 5.0 + pb_margin * 5.0
        if pb <= pb_min * 1.05 or pb >= pb_max * 0.95:
            boundary_score = 3.0
        
        Ti = pid_params.get('Ti', 2.5)
        if Ti <= 1.6 or Ti >= 9.5:
            boundary_score -= 1.0
        
        return min(10.0, max(0.0, boundary_score))
    
    def _calculate_method_score(self, pid_params: Dict) -> float:
        """计算整定方法评分"""
        method = pid_params.get('method', 'unknown')
        
        if 'low_gain' in method or 'high_gain' in method:
            method_score = 5.0
        elif 'oscillation' in method:
            method_score = 6.0
        else:
            method_score = 5.5
        
        if pid_params.get('Kd', 0) > 0:
            method_score += 0.5
        
        return method_score
    
    def _apply_special_limits(self, model_rating: float, is_stable: bool,
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
        
        # 闭环不稳定
        if not is_stable:
            model_rating = min(model_rating, 4.0)
            warnings.append('闭环仿真不稳定')
        
        # 极高振荡
        if oscillation_ratio > 0.9:
            model_rating = min(model_rating, 6.0)
            warnings.append(f'极高振荡({oscillation_ratio:.0%})，建议人工排查根因')
        elif oscillation_ratio > 0.85:
            model_rating = min(model_rating, 6.5)
            warnings.append(f'高振荡({oscillation_ratio:.0%})')
        
        # 参数触达边界
        if pb <= pb_min * 1.02 or pb >= pb_max * 0.98:
            model_rating = min(model_rating, 5.5)
            warnings.append('PID参数触达边界')
        
        # 数据质量极差
        if raw_data_quality < 0.3:
            model_rating = min(model_rating, 5.5)
            warnings.append(f'数据质量极差({raw_data_quality:.2f})')
        
        # 高非线性
        if nonlinearity > 0.6:
            model_rating = min(model_rating, 6.0)
            warnings.append(f'高非线性({nonlinearity:.2f})，可能存在阀门问题')
        
        # 阀门问题
        if valve_issues.get('has_deadband', False):
            model_rating = min(model_rating, 6.0)
            warnings.append(f"检测到阀门死区({valve_issues.get('deadband_size', 0):.0%})")
        if valve_issues.get('has_stiction', False):
            model_rating = min(model_rating, 5.5)
            warnings.append(f"检测到阀门粘滞({valve_issues.get('stiction_severity', 0):.0%})")
        if valve_issues.get('has_saturation', False):
            model_rating = min(model_rating, 6.0)
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
            model_rating = min(model_rating, 5.0)
            warnings.append('❗多重风险因素，强烈建议人工排查')
        
        return model_rating, warnings
