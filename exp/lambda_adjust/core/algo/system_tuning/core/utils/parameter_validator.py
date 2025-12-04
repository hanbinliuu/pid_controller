"""
PID参数验证模块
用于验证整定结果的合理性
"""
import numpy as np
from typing import Dict, Tuple, List
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config, ParameterValidationError


class ParameterValidator:
    """PID参数验证器"""
    
    def __init__(self, validation_config: Dict = None):
        """
        初始化参数验证器
        
        Args:
            validation_config: 验证配置字典，如果为None则使用默认配置
        """
        self.config = validation_config or Config.PARAMETER_VALIDATION
    
    def validate_pid_params(self, 
                           pb: float, 
                           ti: float, 
                           td: float,
                           model_params: Tuple = None,
                           scenario: str = None) -> Tuple[bool, List[str], Dict]:
        """
        验证PID参数的合理性
        
        Args:
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            model_params: 模型参数（可选，用于更严格的验证）
            scenario: 场景类型（可选）
            
        Returns:
            (is_valid, warnings, adjusted_params):
                - is_valid: 参数是否合理
                - warnings: 警告信息列表
                - adjusted_params: 调整后的参数（如果需要调整）
        """
        warnings = []
        adjusted = {'pb': pb, 'ti': ti, 'td': td}
        is_valid = True
        
        # 1. 基本范围检查
        pb_range = self.config['pb_range']
        ti_range = self.config['ti_range']
        td_range = self.config['td_range']
        
        if not (pb_range[0] <= pb <= pb_range[1]):
            warnings.append(f"Pb超出合理范围: {pb:.2f} ∉ [{pb_range[0]}, {pb_range[1]}]")
            adjusted['pb'] = np.clip(pb, pb_range[0], pb_range[1])
            is_valid = False
        
        if not (ti_range[0] <= ti <= ti_range[1]):
            warnings.append(f"Ti超出合理范围: {ti:.2f} ∉ [{ti_range[0]}, {ti_range[1]}]")
            adjusted['ti'] = np.clip(ti, ti_range[0], ti_range[1])
            is_valid = False
        
        if not (td_range[0] <= td <= td_range[1]):
            warnings.append(f"Td超出合理范围: {td:.2f} ∉ [{td_range[0]}, {td_range[1]}]")
            adjusted['td'] = np.clip(td, td_range[0], td_range[1])
            is_valid = False
        
        # 2. 参数比例关系检查
        if ti > 0:
            pb_ti_ratio = pb / ti
            pb_ti_range = self.config['pb_ti_ratio_range']
            
            if not (pb_ti_range[0] <= pb_ti_ratio <= pb_ti_range[1]):
                warnings.append(
                    f"Pb/Ti比例异常: {pb_ti_ratio:.3f} ∉ [{pb_ti_range[0]}, {pb_ti_range[1]}]"
                )
                # 不调整，只警告
        
        if ti > 0 and td > 0:
            ti_td_ratio = ti / td
            ti_td_range = self.config['ti_td_ratio_range']
            
            if not (ti_td_range[0] <= ti_td_ratio <= ti_td_range[1]):
                warnings.append(
                    f"Ti/Td比例异常: {ti_td_ratio:.3f} ∉ [{ti_td_range[0]}, {ti_td_range[1]}]"
                )
                # 不调整，只警告
        
        # 3. 特殊组合检查
        # 纯P控制（Ti=0, Td=0）但Pb很小
        if ti == 0 and td == 0 and pb < 20:
            warnings.append(f"纯P控制且比例作用很强(Pb={pb:.2f}%)，可能导致振荡")
        
        # 强积分+强微分组合
        if 0 < ti < 10 and td > 20:
            warnings.append(f"强积分(Ti={ti:.2f}s)+强微分(Td={td:.2f}s)组合可能不稳定")
        
        # 4. 场景特定检查
        if scenario == 'level':
            if td > 0:
                warnings.append(f"液位控制通常不使用微分，但Td={td:.2f}s > 0")
        
        if scenario == 'flow':
            if td > 0:
                warnings.append(f"流量控制通常不使用微分，但Td={td:.2f}s > 0")
        
        # 5. 基于模型参数的检查（如果提供）
        if model_params is not None and len(model_params) >= 2:
            K = model_params[0]
            T = model_params[1]
            
            # 检查增益和时间常数的合理性
            if K < 0.01 or K > 10.0:
                warnings.append(f"模型增益异常: K={K:.3f}，整定结果可能不可靠")
            
            if T < 1.0 or T > 500.0:
                warnings.append(f"模型时间常数异常: T={T:.1f}s，整定结果可能不可靠")
            
            # 检查Ti与T的关系
            if ti > 0 and ti < T * 0.3:
                warnings.append(f"Ti({ti:.2f}s)远小于T({T:.1f}s)，积分作用可能过强")
            elif ti > T * 5.0:
                warnings.append(f"Ti({ti:.2f}s)远大于T({T:.1f}s)，积分作用可能过弱")
        
        return is_valid, warnings, adjusted
    
    def raise_if_invalid(self, 
                        pb: float, 
                        ti: float, 
                        td: float,
                        model_params: Tuple = None,
                        scenario: str = None):
        """
        验证PID参数，如果不合理则抛出异常
        
        Args:
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            model_params: 模型参数（可选）
            scenario: 场景类型（可选）
            
        Raises:
            ParameterValidationError: 参数验证失败
        """
        is_valid, warnings, adjusted = self.validate_pid_params(
            pb, ti, td, model_params, scenario
        )
        
        if not is_valid:
            message = f"PID参数验证失败: {'; '.join(warnings)}"
            raise ParameterValidationError(message)
    
    def print_validation_report(self, 
                               pb: float, 
                               ti: float, 
                               td: float,
                               model_params: Tuple = None,
                               scenario: str = None):
        """
        打印参数验证报告
        
        Args:
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            model_params: 模型参数（可选）
            scenario: 场景类型（可选）
        """
        is_valid, warnings, adjusted = self.validate_pid_params(
            pb, ti, td, model_params, scenario
        )
        
        print("\n" + "="*60)
        print("PID参数验证报告")
        print("="*60)
        
        print("\n【原始参数】")
        print(f"  Pb: {pb:.2f}%")
        print(f"  Ti: {ti:.2f}s")
        print(f"  Td: {td:.2f}s")
        
        if model_params:
            print("\n【模型参数】")
            if len(model_params) >= 2:
                print(f"  K: {model_params[0]:.3f}")
                print(f"  T: {model_params[1]:.1f}s")
            if len(model_params) >= 3:
                print(f"  L: {model_params[2]:.1f}s")
        
        print(f"\n【验证结果】")
        print(f"  状态: {'✓ 合格' if is_valid else '⚠ 需要调整'}")
        
        if warnings:
            print("\n【警告信息】")
            for i, warning in enumerate(warnings, 1):
                print(f"  {i}. {warning}")
        
        if not is_valid and adjusted != {'pb': pb, 'ti': ti, 'td': td}:
            print("\n【建议调整】")
            if adjusted['pb'] != pb:
                print(f"  Pb: {pb:.2f}% → {adjusted['pb']:.2f}%")
            if adjusted['ti'] != ti:
                print(f"  Ti: {ti:.2f}s → {adjusted['ti']:.2f}s")
            if adjusted['td'] != td:
                print(f"  Td: {td:.2f}s → {adjusted['td']:.2f}s")
        
        print("="*60 + "\n")
    
    def get_quality_score(self, 
                         pb: float, 
                         ti: float, 
                         td: float,
                         model_params: Tuple = None) -> float:
        """
        计算参数质量评分（0-100）
        
        Args:
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            model_params: 模型参数（可选）
            
        Returns:
            质量评分（0-100）
        """
        score = 100.0
        
        # 基于验证结果扣分
        is_valid, warnings, _ = self.validate_pid_params(pb, ti, td, model_params)
        
        if not is_valid:
            score -= 20  # 基本验证失败扣20分
        
        # 每个警告扣5分
        score -= len(warnings) * 5
        
        # 确保分数在0-100之间
        return max(0.0, min(100.0, score))
