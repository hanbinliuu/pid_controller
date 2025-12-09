#!/usr/bin/env python3
"""
PID参数与比例带转换工具类

提供PID控制器参数（Kp, Ki, Kd）与比例带（Proportional Band, PB）、
积分时间（Integral Time, Ti）、微分时间（Derivative Time, Td）之间的转换功能。

转换关系：
- 比例带 PB(%) = 100 / Kp
- Kp = 100 / PB(%)
- 积分时间 Ti = Kp / Ki
- Ki = Kp / Ti
- 微分时间 Td = Kd / Kp
- Kd = Td * Kp
"""
import logging
from typing import Dict, Optional, Union
import math



class PIDConverter:
    """PID参数与比例带转换工具类"""
    
    @staticmethod
    def kp_to_proportional_band(kp: float) -> float:
        """
        将比例增益Kp转换为比例带PB
        
        Args:
            kp: 比例增益
            
        Returns:
            比例带百分比 (%)
            
        Raises:
            ValueError: 当Kp为0或负数时
        """
        if kp <= 0:
            raise ValueError("比例增益Kp必须大于0")
        return 100.0 / kp
    
    @staticmethod
    def proportional_band_to_kp(pb: float) -> float:
        """
        将比例带PB转换为比例增益Kp
        
        Args:
            pb: 比例带百分比 (%)
            
        Returns:
            比例增益
            
        Raises:
            ValueError: 当PB为0或负数时
        """
        if pb <= 0:
            logging.warning("比例带必须大于0%，使用默认值 pb=100")
            pb = 100.0  # 默认比例带 100%，对应 Kp=1
        return 100.0 / pb
    
    @staticmethod
    def ki_to_integral_time(kp: float, ki: float) -> float:
        """
        将积分增益Ki转换为积分时间Ti
        
        Args:
            kp: 比例增益
            ki: 积分增益
            
        Returns:
            积分时间 (秒)
            
        Raises:
            ValueError: 当Ki为0时
        """
        if ki == 0:
            raise ValueError("积分增益Ki不能为0")
        return kp / ki
    
    @staticmethod
    def integral_time_to_ki(kp: float, ti: float) -> float:
        """
        将积分时间Ti转换为积分增益Ki
        
        Args:
            kp: 比例增益
            ti: 积分时间 (秒)
            
        Returns:
            积分增益
            
        Raises:
            ValueError: 当Ti为0时
        """
        if ti == 0:
            raise ValueError("积分时间Ti不能为0")
        return kp / ti
    
    @staticmethod
    def kd_to_derivative_time(kp: float, kd: float) -> float:
        """
        将微分增益Kd转换为微分时间Td
        
        Args:
            kp: 比例增益
            kd: 微分增益
            
        Returns:
            微分时间 (秒)
            
        Raises:
            ValueError: 当Kp为0时
        """
        if kp == 0:
            raise ValueError("比例增益Kp不能为0")
        return kd / kp
    
    @staticmethod
    def derivative_time_to_kd(kp: float, td: float) -> float:
        """
        将微分时间Td转换为微分增益Kd
        
        Args:
            kp: 比例增益
            td: 微分时间 (秒)
            
        Returns:
            微分增益
        """
        return td * kp
    
    @staticmethod
    def pid_to_classical(kp: float, ki: float, kd: float) -> Dict[str, float]:
        """
        将PID参数转换为经典控制表示法
        
        Args:
            kp: 比例增益
            ki: 积分增益
            kd: 微分增益
            
        Returns:
            包含经典参数的字典：
            - proportional_band: 比例带 (%)
            - integral_time: 积分时间 (秒)
            - derivative_time: 微分时间 (秒)
        """
        result = {}
        
        # 比例带转换
        if kp > 0:
            result['proportional_band'] = PIDConverter.kp_to_proportional_band(kp)
        else:
            result['proportional_band'] = float('inf')
        
        # 积分时间转换
        if ki != 0 and kp > 0:
            result['integral_time'] = PIDConverter.ki_to_integral_time(kp, ki)
        else:
            result['integral_time'] = float('inf') if ki == 0 else 0
        
        # 微分时间转换
        if kp > 0:
            result['derivative_time'] = PIDConverter.kd_to_derivative_time(kp, kd)
        else:
            result['derivative_time'] = 0
        
        return result
    
    @staticmethod
    def classical_to_pid(proportional_band: float, 
                        integral_time: Optional[float] = None,
                        derivative_time: Optional[float] = None) -> Dict[str, float]:
        """
        将经典控制参数转换为PID参数
        
        Args:
            proportional_band: 比例带 (%)
            integral_time: 积分时间 (秒)，可选
            derivative_time: 微分时间 (秒)，可选
            
        Returns:
            包含PID参数的字典：
            - kp: 比例增益
            - ki: 积分增益
            - kd: 微分增益
        """
        result = {}
        
        # 比例增益转换
        result['kp'] = PIDConverter.proportional_band_to_kp(proportional_band)
        
        # 积分增益转换
        if integral_time is not None and integral_time > 0:
            result['ki'] = PIDConverter.integral_time_to_ki(result['kp'], integral_time)
        else:
            result['ki'] = 0.0
        
        # 微分增益转换
        if derivative_time is not None:
            result['kd'] = PIDConverter.derivative_time_to_kd(result['kp'], derivative_time)
        else:
            result['kd'] = 0.0
        
        return result
    
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
        result = {
            'standard': {
                'kp': round(kp, 6),
                'ki': round(ki, 6),
                'kd': round(kd, 6)
            }
        }
        
        if include_classical:
            classical = PIDConverter.pid_to_classical(kp, ki, kd)
            result['classical'] = {
                'proportional_band': round(classical['proportional_band'], 2) if math.isfinite(classical['proportional_band']) else None,
                'integral_time': round(classical['integral_time'], 2) if math.isfinite(classical['integral_time']) else None,
                'derivative_time': round(classical['derivative_time'], 4)
            }
        
        return result
    
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
        return {
            'kp_valid': kp >= 0 and math.isfinite(kp),
            'ki_valid': ki >= 0 and math.isfinite(ki),
            'kd_valid': kd >= 0 and math.isfinite(kd),
            'stable': kp > 0  # 简单的稳定性检查
        }


# 便捷函数
def convert_pid_to_pb(kp: float, ki: float, kd: float) -> Dict[str, float]:
    """便捷函数：PID参数转换为比例带形式"""
    return PIDConverter.pid_to_classical(kp, ki, kd)


def convert_pb_to_pid(proportional_band: float, 
                     integral_time: float = None, 
                     derivative_time: float = None) -> Dict[str, float]:
    """便捷函数：比例带形式转换为PID参数"""
    return PIDConverter.classical_to_pid(proportional_band, integral_time, derivative_time)

# 截取最新的一组pid数据
def process_lists_optimized(*lists):
    """
    优化版本，减少循环次数
    """
    if not lists:
        return tuple()

    first_len = len(lists[0])
    for lst in lists:
        if len(lst) != first_len:
            raise ValueError("所有列表长度必须一致")

    if first_len == 0:
        return tuple([] for _ in lists)

    # 直接计算最小连续长度，避免存储所有counts
    min_count = first_len  # 初始化为最大可能值

    for lst in lists:
        if not lst:
            min_count = 0
            break

        last_element = lst[-1]
        latest_pb = last_element[3]
        latest_ti = last_element[2]
        latest_td = last_element[5]
        latest_sv = last_element[1]

        count = 1

        for i in range(len(lst) - 2, -1, -1):
            record=lst[i]
            if (record[3] == latest_pb and
                    record[2] == latest_ti and
                    record[5] == latest_td and
                    record[1] == latest_sv):
                count += 1
            # if lst[i] == last_element:
            #     count += 1
            else:
                break

        if count < min_count:
            min_count = count

    # 截取列表
    if min_count == 0:
        return list(tuple([] for _ in lists))
    else:
        logging.info(f"截取数据：{min_count} 条")
        return tuple(lst[-min_count:] for lst in lists)

if __name__ == "__main__":
    # 示例用法
    print("PID参数转换工具示例:")
    
    # 示例1: PID转经典控制
    kp, ki, kd = 2.0, 0.5, 0.1
    classical = convert_pid_to_pb(kp, ki, kd)
    print(f"PID(Kp={kp}, Ki={ki}, Kd={kd}) -> 经典控制: {classical}")
    
    # 示例2: 经典控制转PID
    pb, ti, td = 400.0, 10.0, 0
    pid = convert_pb_to_pid(pb, ti, td)
    print(f"经典控制(PB={pb}%, Ti={ti}s, Td={td}s) -> PID: {pid}")
    
    # 示例3: 参数格式化
    formatted = PIDConverter.format_pid_parameters(kp, ki, kd)
    print(f"格式化参数: {formatted}")