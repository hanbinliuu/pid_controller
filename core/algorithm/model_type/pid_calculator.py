"""PID参数计算模块 - Lambda整定方法"""

from typing import Dict
from dataclasses import dataclass

from .config import Config, ModelType


@dataclass
class PIDParameters:
    """PID参数数据类"""
    Kp: float
    Ki: float
    Kd: float
    
    # 可选的替代表示
    Pb: float = 0.0   # 比例带 (%)
    Ti: float = 0.0   # 积分时间
    Td: float = 0.0   # 微分时间
    
    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return {
            'Kp': round(self.Kp, 4),
            'Ki': round(self.Ki, 4),
            'Kd': round(self.Kd, 4),
            'pb': round(self.Pb, 4),
            'ti': round(self.Ti, 4),
            'td': round(self.Td, 4),
        }
    
    def to_standard_dict(self) -> Dict[str, float]:
        """转换为标准字典（仅Kp/Ki/Kd）"""
        return {
            'Kp': round(self.Kp, 4),
            'Ki': round(self.Ki, 4),
            'Kd': round(self.Kd, 4),
        }


class PIDCalculator:
    """
    PID参数计算器 - Lambda整定方法
    
    支持的模型类型：
    - FOPDT: 一阶加纯滞后
    - FO: 纯一阶
    - SO: 二阶
    - SOPDT: 二阶加滞后
    - FOPI: 一阶积分
    - PIECEWISE: 分段线性（按FOPDT处理）
    """
    
    def __init__(self, epsilon: float = Config.EPSILON):
        self._epsilon = epsilon
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float = 0.8) -> PIDParameters:
        """
        计算PID参数
        
        Args:
            K: 增益
            T1: 主时间常数
            T2: 次时间常数（二阶模型）
            L: 纯滞后时间
            model_type: 模型类型
            lambda_factor: Lambda系数 (0.5-1.5，越大响应越慢越稳定)
        
        Returns:
            PIDParameters: 计算得到的PID参数
        """
        # 参数预处理
        K = max(abs(K), self._epsilon)
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1  # 等效时间常数
        lambda_val = T_eq * lambda_factor
        
        # 根据模型类型计算
        if model_type in [ModelType.FOPDT, ModelType.FO, ModelType.PIECEWISE]:
            Kp, Ti, Td = self._calculate_fopdt(K, T1, L, lambda_val)
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            Kp, Ti, Td = self._calculate_sopdt(K, T1, T2, L, T_eq, lambda_val)
        elif model_type == ModelType.FOPI:
            Kp, Ti, Td = self._calculate_fopi(K, T1)
        else:
            Kp, Ti, Td = 1.0, 20.0, 0.0
        
        # 限幅和派生计算
        Kp = max(0.01, Kp)
        Ti = max(0.1, Ti)
        Td = max(0.0, Td)
        
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        Pb = 100.0 / Kp if Kp > self._epsilon else 100.0
        
        return PIDParameters(
            Kp=Kp, Ki=Ki, Kd=Kd,
            Pb=Pb, Ti=Ti, Td=Td
        )
    
    def _calculate_fopdt(self, K: float, T1: float, L: float, 
                          lambda_val: float) -> tuple:
        """FOPDT模型的PID计算"""
        denom = K * (lambda_val + L / 2)
        
        if denom < self._epsilon:
            return 1.0, 20.0, 0.0
        
        Kp = (T1 + L / 2) / denom
        Ti = T1 + L / 2
        Td = (T1 * L) / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        return Kp, Ti, Td
    
    def _calculate_sopdt(self, K: float, T1: float, T2: float, L: float,
                          T_eq: float, lambda_val: float) -> tuple:
        """SOPDT模型的PID计算"""
        denom = K * (lambda_val + L / 2) if L > 0 else K * lambda_val
        
        if denom < self._epsilon:
            return 1.0, 20.0, 0.0
        
        Kp = T_eq / denom
        Ti = T_eq
        Td = (T1 * T2) / T_eq if T_eq > self._epsilon else 0.0
        
        return Kp, Ti, Td
    
    def _calculate_fopi(self, K: float, T1: float) -> tuple:
        """积分模型的PID计算"""
        if K < self._epsilon:
            return 1.0, 20.0, 0.0
        
        lv = max(T1 * 0.8, 0.2) if T1 > 0 else 0.2
        Kp = T1 / (K * lv) if T1 > 0 else 1.0 / (K * lv)
        Ti = max(T1, 1.0)
        Td = 0.0
        
        return Kp, Ti, Td
    
    def determine_tuning_type(self, Kp: float, Ti: float, Td: float) -> str:
        """根据PID参数确定整定类型"""
        if Td > self._epsilon:
            return 'PID'
        elif Ti > self._epsilon:
            return 'PI'
        else:
            return 'P'
