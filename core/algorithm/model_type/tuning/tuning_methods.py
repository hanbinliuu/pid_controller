"""
PID整定方法模块 (Tuning Methods Module)
======================================

包含各种PID整定公式的实现：
- Lambda/IMC法
- Cohen-Coon法
- 积分过程整定
- 非线性模型整定
"""

from typing import Tuple
from ..config import Config, ModelType


class TuningMethodsMixin:
    """
    整定方法Mixin类
    
    提供各种模型类型的PID参数整定公式。
    需要宿主类提供 _epsilon, _pid_constraints, _get_fallback_params, _get_max_kp 属性/方法。
    """
    
    def _tune_fo(self, K: float, T1: float, lambda_factor: float, 
                 method: str, conservative_level: float = 4.0,
                 pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        一阶无滞后系统整定（自适应保守）
        
        Args:
            K: 过程增益
            T1: 时间常数
            lambda_factor: Lambda系数
            method: 整定方法
            conservative_level: 保守因子 (3.0~8.0)
            pb_min: pb最小值 (50~100)
        
        Returns:
            (Kp, Ti, Td) 元组
        """
        # 使用自适应保守因子
        lambda_val = T1 * lambda_factor * conservative_level
        
        denom = K * lambda_val
        if denom < self._epsilon:
            return self._get_fallback_params(Ti_override=T1)
        
        Kp = T1 / denom
        
        # 根据pb_min计算max_Kp
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        Ti = T1
        Td = 0.0  # 无滞后时不需要微分
        
        return Kp, Ti, Td
    
    def _tune_fopdt(self, K: float, T1: float, L: float, 
                    lambda_factor: float, method: str,
                    conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        一阶加纯滞后系统整定（自适应保守）
        
        支持多种整定方法：
        - lambda: Lambda/IMC标准法
        - cohen_coon: Cohen-Coon法（适合L/T1较大）
        - imc_aggressive: IMC激进模式
        """
        # 从配置读取基准值
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        
        if method == 'cohen_coon' and L > self._epsilon:
            # Cohen-Coon 法（适合 L/T1 较大的系统）
            # 应用保守因子以降低激进程度
            cc_factor = self._pid_constraints.get('cohen_coon_conservative_factor', 0.85)
            tau = L / T1
            Kp = cc_factor * (1.35 / K) * (T1 / L + 0.185)
            Ti = 2.5 * L * (T1 + 0.185 * L) / (T1 + 0.611 * L)
            Td = 0.37 * L * T1 / (T1 + 0.185 * L)
            
        elif method == 'imc_aggressive':
            # IMC 激进模式（lambda = L）
            lambda_val = max(L, T1 * 0.1)
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            Kp = (T1 + L / 2) / denom
            Ti = T1 + L / 2
            Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
            
        else:
            # Lambda/IMC 标准法（使用自适应保守因子）
            lambda_val = T1 * lambda_factor * (conservative_level / baseline)  # 标准化到基准
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1 + L / 2)
            Kp = (T1 + L / 2) / denom
            Ti = T1 + L / 2
            Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_sopdt(self, K: float, T1: float, T2: float, L: float,
                    lambda_factor: float, conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """二阶系统整定（自适应保守）"""
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        # 使用自适应保守因子
        lambda_val = T_eq * lambda_factor * (conservative_level / baseline)
        
        denom = K * (lambda_val + L / 2) if L > 0 else K * lambda_val
        if denom < self._epsilon:
            return self._get_fallback_params(Ti_override=T_eq)
        
        Kp = T_eq / denom
        Ti = T_eq
        # 二阶系统的微分时间：串联时间常数的几何平均
        Td = (T1 * T2) / T_eq if T_eq > self._epsilon and T2 > 0 else 0.0
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_integrator(self, K: float, T1: float, 
                         lambda_factor: float, conservative_level: float = 4.0,
                         pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        积分过程整定（自适应保守）
        
        积分过程: G(s) = K / (T1*s + 1) / s
        使用 SIMC 规则
        """
        if K < self._epsilon:
            return self._get_fallback_params()
        
        # 使用自适应保守因子
        lambda_val = max(T1 * lambda_factor * (conservative_level / 4.0), 0.2)
        
        # SIMC 积分过程公式
        Kp = T1 / (K * lambda_val) if T1 > 0 else 1.0 / (K * lambda_val)
        Ti = 4 * lambda_val  # 积分时间 = 4 * 闭环时间常数
        Td = 0.0  # 积分过程一般不用微分
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_nonlinear(self, K: float, T1: float, L: float,
                        lambda_factor: float, method: str,
                        conservative_level: float, pb_min: float,
                        model_type: str) -> Tuple[float, float, float]:
        """
        非线性模型整定（使用等效线性化参数）
        
        非线性模型使用等效线性化后的FOPDT参数整定，
        但增加额外的保守度以补偿非线性带来的不确定性。
        
        Args:
            K: 等效线性增益
            T1: 等效时间常数
            L: 等效滞后时间
            lambda_factor: Lambda系数
            method: 整定方法
            conservative_level: 基础保守等级
            pb_min: 基础pb最小值
            model_type: 非线性模型类型
        """
        # 非线性模型需要额外的保守度（从配置读取）
        nl_factors = self._pid_constraints.get('nonlinear_factors', {})
        nonlinear_factor = nl_factors.get('default', 1.3)
        
        if model_type == ModelType.HAMMERSTEIN:
            nonlinear_factor = nl_factors.get('HAMMERSTEIN', 1.4)
        elif model_type == ModelType.DEADBAND_FOPDT:
            nonlinear_factor = nl_factors.get('DEADBAND_FOPDT', 1.5)
        elif model_type == ModelType.SATURATION_FOPDT:
            nonlinear_factor = nl_factors.get('SAT_FOPDT', 1.3)
        
        # 应用非线性补偿到保守等级
        adjusted_conservative = conservative_level * nonlinear_factor
        adjusted_pb_min = pb_min * nonlinear_factor
        
        # 使用FOPDT整定公式
        Kp, Ti, Td = self._tune_fopdt(K, T1, L, lambda_factor, method,
                                       adjusted_conservative, adjusted_pb_min)
        
        # 非线性模型一般不使用微分（避免放大噪声）
        Td = Td * 0.5
        
        # 死区专用补偿：增强积分作用以消除稳态误差
        if model_type == ModelType.DEADBAND_FOPDT:
            db_comp = self._pid_constraints.get('deadband_compensation', {})
            if db_comp.get('enable', True):
                ti_factor = db_comp.get('ti_reduction_factor', 0.7)
                Ti = Ti * ti_factor  # 减小Ti，加快积分消除稳态误差

        return Kp, Ti, Td
    
    def _apply_constraints(self, Kp: float, Ti: float, Td: float,
                           K_sign: int) -> Tuple[float, float, float]:
        """应用参数合理性约束（从配置读取阈值）"""
        cfg = self._pid_constraints
        
        # 1. 限制Kp的绝对值下限
        kp_min = cfg.get('kp_min', 0.01)
        if abs(Kp) < kp_min:
            Kp = kp_min * K_sign
        
        # 2. 限制Ti的范围
        ti_min = cfg.get('ti_min', 0.1)
        ti_max = cfg.get('ti_max', 120.0)
        Ti = max(ti_min, min(Ti, ti_max))
        
        # 3. 限制Td的范围（不超过 Ti * td_max_ratio）
        td_max_ratio = cfg.get('td_max_ratio', 0.25)
        Td = max(0.0, min(Td, Ti * td_max_ratio))
        
        return Kp, Ti, Td
