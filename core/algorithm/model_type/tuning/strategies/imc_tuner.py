"""
IMC 整定器 (Internal Model Control Tuner)
=========================================

基于内模控制原理的 PID 参数整定方法。

原理
----
IMC 将控制器设计转化为滤波器设计问题：
    C(s) = G^(-1)(s) · F(s)
    其中 F(s) = 1 / (λ·s + 1) 是低通滤波器

对于 FOPDT 模型 G(s) = K·e^(-Ls) / (T1·s + 1)：
    Kp = T1 / (K · (λ + L))
    Ti = T1
    Td = 0 (一阶模型无微分)

对于 SOPDT 模型：
    Kp = (T1 + T2) / (K · (λ + L))
    Ti = T1 + T2
    Td = T1·T2 / (T1 + T2)

优点
----
1. 只有一个调节参数 λ（闭环时间常数）
2. λ 越大越保守，越小响应越快
3. 对模型失配有一定鲁棒性

参考
----
Skogestad, S. (2003). Simple analytic rules for model reduction and PID controller tuning.
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass


@dataclass
class IMCResult:
    """IMC 整定结果"""
    Kp: float
    Ti: float
    Td: float
    lambda_: float  # 滤波器时间常数
    method: str = "IMC"
    

class IMCTuner:
    """
    IMC 整定器
    
    使用方法:
        tuner = IMCTuner()
        result = tuner.tune_fopdt(K=1.0, T1=10.0, L=2.0)
        # result.Kp, result.Ti, result.Td
    """
    
    # 默认参数
    DEFAULT_LAMBDA_FACTOR = 1.5  # λ = L * factor (Skogestad建议)
    MIN_LAMBDA = 0.5  # 最小 λ 值
    MAX_LAMBDA = 100.0  # 最大 λ 值
    
    @classmethod
    def tune_fopdt(cls, K: float, T1: float, L: float,
                   lambda_factor: float = None,
                   aggressive: bool = False) -> IMCResult:
        """
        FOPDT 模型的 IMC-PID 整定
        
        Args:
            K: 过程增益
            T1: 时间常数
            L: 纯滞后
            lambda_factor: λ 因子 (λ = max(L, T1) * factor)
            aggressive: 是否使用激进参数
            
        Returns:
            IMCResult: 整定结果
        """
        if abs(K) < 1e-9:
            K = 0.5 if K >= 0 else -0.5
        
        # 计算 λ
        if lambda_factor is None:
            lambda_factor = 1.0 if aggressive else cls.DEFAULT_LAMBDA_FACTOR
        
        # Skogestad 规则: λ >= L
        lambda_ = max(L * lambda_factor, T1 * 0.5)
        lambda_ = np.clip(lambda_, cls.MIN_LAMBDA, cls.MAX_LAMBDA)
        
        # IMC-PID 公式
        lambda_plus_L = lambda_ + L
        if lambda_plus_L < 1e-9:
            lambda_plus_L = 1.0
        
        Kp = T1 / (abs(K) * lambda_plus_L)
        Ti = T1
        Td = 0.0  # 一阶模型不需要微分
        
        # 如果 K 为负，Kp 也为负
        if K < 0:
            Kp = -Kp
        
        return IMCResult(
            Kp=float(Kp),
            Ti=float(max(Ti, 0.5)),
            Td=float(Td),
            lambda_=float(lambda_),
            method="IMC-PI"
        )
    
    @classmethod
    def tune_sopdt(cls, K: float, T1: float, T2: float, L: float,
                   lambda_factor: float = None) -> IMCResult:
        """
        SOPDT 模型的 IMC-PID 整定
        
        对于二阶系统，可以产生微分作用
        """
        if abs(K) < 1e-9:
            K = 0.5 if K >= 0 else -0.5
        
        if lambda_factor is None:
            lambda_factor = cls.DEFAULT_LAMBDA_FACTOR
        
        # λ 计算
        T_dom = max(T1, T2)  # 主导时间常数
        lambda_ = max(L * lambda_factor, T_dom * 0.5)
        lambda_ = np.clip(lambda_, cls.MIN_LAMBDA, cls.MAX_LAMBDA)
        
        lambda_plus_L = lambda_ + L
        if lambda_plus_L < 1e-9:
            lambda_plus_L = 1.0
        
        # 二阶 IMC-PID 公式
        T_sum = T1 + T2
        if T_sum < 1e-9:
            T_sum = T1 + 1.0
        
        Kp = T_sum / (abs(K) * lambda_plus_L)
        Ti = T_sum
        Td = (T1 * T2) / T_sum  # 二阶系统有微分
        
        if K < 0:
            Kp = -Kp
        
        return IMCResult(
            Kp=float(Kp),
            Ti=float(max(Ti, 0.5)),
            Td=float(max(Td, 0.0)),
            lambda_=float(lambda_),
            method="IMC-PID"
        )
    
    @classmethod
    def tune_integrating(cls, K: float, L: float,
                         lambda_factor: float = None) -> IMCResult:
        """
        积分过程的 IMC-PI 整定
        
        对于 G(s) = K/s * e^(-Ls)
        """
        if abs(K) < 1e-9:
            K = 0.5 if K >= 0 else -0.5
        
        if lambda_factor is None:
            lambda_factor = 2.0  # 积分过程更保守
        
        lambda_ = L * lambda_factor
        lambda_ = np.clip(lambda_, cls.MIN_LAMBDA, cls.MAX_LAMBDA)
        
        # 积分过程 IMC 公式 (Skogestad SIMC)
        tau_c = lambda_
        Kp = 1 / (abs(K) * (tau_c + L))
        Ti = 4 * (tau_c + L)  # SIMC 规则
        Td = 0.0
        
        if K < 0:
            Kp = -Kp
        
        return IMCResult(
            Kp=float(Kp),
            Ti=float(max(Ti, 1.0)),
            Td=float(Td),
            lambda_=float(lambda_),
            method="IMC-PI (integrating)"
        )
    
    @classmethod
    def adjust_lambda_for_robustness(cls, lambda_: float, 
                                      model_uncertainty: float = 0.0) -> float:
        """
        根据模型不确定性调整 λ
        
        Args:
            lambda_: 当前 λ 值
            model_uncertainty: 模型不确定性 (0-1)
            
        Returns:
            调整后的 λ
        """
        # 不确定性越大，λ 越大（更保守）
        adjustment = 1.0 + model_uncertainty
        return lambda_ * adjustment
    
    @classmethod
    def tune_auto(cls, model_type: str, params: Dict,
                  aggressive: bool = False) -> IMCResult:
        """
        根据模型类型自动选择整定方法
        
        Args:
            model_type: 模型类型 ('FOPDT', 'SOPDT', 'FO_INTEGRATOR' 等)
            params: 模型参数字典 {K, T1, T2, L}
            aggressive: 是否使用激进参数
        """
        K = params.get('K', 1.0)
        T1 = params.get('T1', 10.0)
        T2 = params.get('T2', 0.0)
        L = params.get('L', 1.0)
        
        lambda_factor = 1.0 if aggressive else cls.DEFAULT_LAMBDA_FACTOR
        
        if model_type in ['FO_INTEGRATOR', 'SO_INTEGRATOR']:
            return cls.tune_integrating(K, L, lambda_factor)
        elif model_type in ['SOPDT', 'SO']:
            return cls.tune_sopdt(K, T1, T2, L, lambda_factor)
        else:
            # FOPDT 或 FO
            return cls.tune_fopdt(K, T1, L, lambda_factor, aggressive)
