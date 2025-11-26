#!/usr/bin/env python3
"""
参数转换业务服务层
封装PID参数与比例带转换相关的业务逻辑
"""

import logging
from typing import Optional, Dict, Union

from core.utils.pid_converter import PIDConverter

logger = logging.getLogger(__name__)


class ConversionService:
    """参数转换业务服务"""

    @staticmethod
    def convert_pid_to_classical(kp: float, ki: float, kd: float) -> Dict[str, Union[float, Dict[str, float]]]:
        """
        将PID参数转换为经典控制表示法
        
        Args:
            kp: 比例增益
            ki: 积分增益
            kd: 微分增益
            
        Returns:
            包含转换结果的字典
        """
        try:
            classical = PIDConverter.pid_to_classical(kp, ki, kd)
            
            response_data = {
                "standard": {
                    "kp": kp,
                    "ki": ki, 
                    "kd": kd
                },
                "classical": classical
            }
            
            return {
                "success": True,
                "message": "PID参数转换为经典控制参数成功",
                "data": response_data
            }
            
        except Exception as e:
            logger.error(f"PID参数转换失败: {str(e)}")
            raise

    @staticmethod
    def convert_classical_to_pid(proportional_band: float, 
                                integral_time: Optional[float] = None,
                                derivative_time: Optional[float] = None) -> Dict[str, Union[float, Dict[str, float]]]:
        """
        将经典控制参数转换为PID参数
        
        Args:
            proportional_band: 比例带 (%)
            integral_time: 积分时间 (秒)，可选
            derivative_time: 微分时间 (秒)，可选
            
        Returns:
            包含转换结果的字典
        """
        try:
            pid = PIDConverter.classical_to_pid(
                proportional_band,
                integral_time,
                derivative_time
            )
            
            response_data = {
                "classical": {
                    "proportional_band": proportional_band,
                    "integral_time": integral_time,
                    "derivative_time": derivative_time
                },
                "standard": pid
            }
            
            return {
                "success": True,
                "message": "经典控制参数转换为PID参数成功",
                "data": response_data
            }
            
        except Exception as e:
            logger.error(f"经典控制参数转换失败: {str(e)}")
            raise

    @staticmethod
    def format_pid_parameters(kp: float, ki: float, kd: float, 
                             include_classical: bool = True) -> Dict[str, Union[float, Dict[str, float]]]:
        """
        格式化PID参数，同时提供标准和经典表示法
        
        Args:
            kp: 比例增益
            ki: 积分增益 
            kd: 微分增益
            include_classical: 是否包含经典控制参数
            
        Returns:
            格式化的参数字典
        """
        try:
            formatted = PIDConverter.format_pid_parameters(kp, ki, kd, include_classical)
            
            return {
                "success": True,
                "message": "参数格式化成功",
                "data": formatted
            }
            
        except Exception as e:
            logger.error(f"参数格式化失败: {str(e)}")
            raise

    @staticmethod
    def validate_pid_parameters(kp: float, ki: float, kd: float) -> Dict[str, bool]:
        """
        验证PID参数的有效性
        
        Args:
            kp: 比例增益
            ki: 积分增益
            kd: 微分增益
            
        Returns:
            验证结果字典
        """
        try:
            validation = PIDConverter.validate_pid_parameters(kp, ki, kd)
            
            # 生成验证消息
            issues = []
            if not validation['kp_valid']:
                issues.append("Kp参数无效")
            if not validation['ki_valid']:
                issues.append("Ki参数无效")
            if not validation['kd_valid']:
                issues.append("Kd参数无效")
            if not validation['stable']:
                issues.append("系统可能不稳定 (Kp <= 0)")
                
            message = "所有参数有效" if not issues else f"发现问题: {', '.join(issues)}"
            
            return {
                **validation,
                "message": message
            }
            
        except Exception as e:
            logger.error(f"参数验证失败: {str(e)}")
            raise

    @staticmethod
    def get_conversion_formulas() -> Dict[str, Union[bool, str, Dict]]:
        """
        获取PID参数转换公式
        
        Returns:
            包含转换公式的字典
        """
        formulas = {
            "pid_to_classical": {
                "proportional_band": "PB(%) = 100 / Kp",
                "integral_time": "Ti(s) = Kp / Ki",
                "derivative_time": "Td(s) = Kd / Kp"
            },
            "classical_to_pid": {
                "kp": "Kp = 100 / PB(%)",
                "ki": "Ki = Kp / Ti(s)",
                "kd": "Kd = Td(s) * Kp"
            },
            "notes": [
                "比例带PB表示控制器输出100%变化时对应的过程变量变化百分比",
                "积分时间Ti表示积分作用达到比例作用同样效果所需的时间",
                "微分时间Td表示微分作用提前的时间量",
                "当Ki=0时，积分时间为无穷大(纯比例或PD控制)",
                "当Kp=0时，系统通常不稳定"
            ]
        }
        
        return {
            "success": True,
            "message": "转换公式获取成功",
            "data": formulas
        }

    @staticmethod
    def get_conversion_examples() -> Dict[str, Union[bool, str, list]]:
        """
        获取PID参数转换示例
        
        Returns:
            包含转换示例的字典
        """
        examples = [
            {
                "name": "典型PI控制器",
                "pid": {"kp": 2.0, "ki": 0.5, "kd": 0.0},
                "classical": {"proportional_band": 50.0, "integral_time": 4.0, "derivative_time": 0.0},
                "description": "适用于过程控制，无微分作用避免噪声影响"
            },
            {
                "name": "PID控制器",
                "pid": {"kp": 1.5, "ki": 0.3, "kd": 0.08},
                "classical": {"proportional_band": 66.67, "integral_time": 5.0, "derivative_time": 0.053},
                "description": "完整PID控制，适用于需要快速响应的系统"
            },
            {
                "name": "纯比例控制",
                "pid": {"kp": 4.0, "ki": 0.0, "kd": 0.0},
                "classical": {"proportional_band": 25.0, "integral_time": None, "derivative_time": 0.0},
                "description": "最简单的控制方式，适用于稳态精度要求不高的场合"
            },
            {
                "name": "PD控制器",
                "pid": {"kp": 1.0, "ki": 0.0, "kd": 0.1},
                "classical": {"proportional_band": 100.0, "integral_time": None, "derivative_time": 0.1},
                "description": "适用于积分饱和严重的系统"
            }
        ]
        
        return {
            "success": True,
            "message": "转换示例获取成功",
            "data": examples
        }