"""PID整定模块：负责PID参数的整定计算"""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config, Mode, TuningMethod


class PIDTuner:
    """PID整定器：负责各种场景下的PID参数整定"""
    
    @staticmethod
    def _lambda_tuning_core(K, T, L, lambda_val, mode, scenario='standard', 
                           kp_bounds=(0.5, 6.0), ti_bounds=(8.0, 120.0), 
                           td_bounds=(0.0, 25.0), ti_max_override=None, 
                           td_max_override=None, force_td_zero=False):
        """统一的 Lambda 整定核心方法"""
        denominator = K * (lambda_val + L / 2)
        if denominator < Config.EPSILON:
            return 1.0, 20.0, 1.0 if not force_td_zero else 0.0

        # 计算Kp, Ti, Td（标准 Lambda 公式）
        Kp = (T + L / 2) / denominator
        Ti = T + L / 2
        Td = (T * L) / (2 * T + L) if (2 * T + L) > Config.EPSILON else 0.0

        # 场景特定的调整
        if scenario == 'temperature':
            L_T_ratio = L / T if T > Config.EPSILON else 0.5
            if L_T_ratio > 0.5:
                Kp *= 0.85
                Ti *= 1.15
                Td *= 0.9
            elif L_T_ratio > 0.3:
                Kp *= 0.9
                Ti *= 1.1
        elif scenario == 'level':
            Kp *= 0.7
            Ti *= 1.3
            Td = 0.0
            if T > 50:  # 积分系统
                Kp *= 0.6
                Ti = T * 1.5
        elif scenario == 'flow':
            if mode == Mode.FLOW_CONTROL:
                Kp *= 0.6
                Ti *= 1.5
            Td = 0.0

        # 根据模式调整参数
        if mode == Mode.ANTI_DISTURBANCE:
            Kp *= 0.8
            Ti *= 1.2
            Td *= 0.7
        elif mode == Mode.ANTI_NOISE:
            Kp *= 0.7
            Ti *= 1.3
            Td *= 0.5
        elif mode == Mode.FLOW_CONTROL and scenario != 'flow':
            Kp *= 0.6
            Ti *= 1.5
            Td *= 0.3

        # 强制关闭微分（某些场景）
        if force_td_zero:
            Td = 0.0

        # 参数限幅
        Kp = np.clip(Kp, kp_bounds[0], kp_bounds[1])
        Ti = np.clip(Ti, ti_bounds[0], ti_bounds[1])
        Td = np.clip(Td, td_bounds[0], td_bounds[1])

        # 转换为pb, ti, td
        pb = 100 / Kp if Kp != 0 else 100.0
        ti = Ti
        td = Td

        # 应用全局参数边界保护
        pb = np.clip(pb, Config.PB_MIN, Config.PB_MAX)
        ti_max = ti_max_override if ti_max_override is not None else Config.TI_MAX
        td_max = td_max_override if td_max_override is not None else Config.TD_MAX
        ti = np.clip(ti, Config.TI_MIN, ti_max)
        td = np.clip(td, Config.TD_MIN, td_max)

        return pb, ti, td
    
    @staticmethod
    def lambda_tuning(K, T, L, lambda_val=None, mode=Mode.STANDARD):
        """基于Lambda方法整定PID参数（标准场景）"""
        if lambda_val is None:
            lambda_val = T * 0.8
        print('lambda值是：', lambda_val)
        return PIDTuner._lambda_tuning_core(
            K, T, L, lambda_val, mode, 
            scenario='standard',
            kp_bounds=(0.5, 6.0),
            ti_bounds=(8.0, 120.0),
            td_bounds=(0.0, 25.0)
        )
    
    @staticmethod
    def lambda_tuning_for_temperature_control(K, T, L, lambda_val=None, mode=Mode.STANDARD):
        """针对石油温控的 Lambda 整定方法"""
        if lambda_val is None:
            L_T_ratio = L / T if T > Config.EPSILON else 0.5
            if L_T_ratio > 0.5:
                lambda_val = max(T, 2 * L)
            else:
                lambda_val = T * 0.8
        
        return PIDTuner._lambda_tuning_core(
            K, T, L, lambda_val, mode,
            scenario='temperature',
            kp_bounds=(0.3, 5.0),
            ti_bounds=(10.0, 300.0),
            td_bounds=(0.0, 30.0),
            ti_max_override=300.0,
            td_max_override=30.0
        )
    
    @staticmethod
    def lambda_tuning_for_level_control(K, T, L=0.0, mode=None):
        """针对蒸馏液位控制的 Lambda 整定方法"""
        L = max(L, 0.1)
        lambda_val = T * 0.5
        
        if mode is None:
            mode = Mode.STANDARD
        
        # 🔧 放宽参数限制，适应大时间常数系统
        # Kp: 0.1-10.0 (对应 Pb: 10%-1000%)
        # Ti: 1.0-300.0 (适应大时间常数，如T=150s)
        return PIDTuner._lambda_tuning_core(
            K, T, L, lambda_val, mode,
            scenario='level',
            kp_bounds=(0.1, 10.0),
            ti_bounds=(1.0, 300.0),
            td_bounds=(0.0, 0.0),
            force_td_zero=True
        )
    
    @staticmethod
    def lambda_tuning_for_flow(K, T, L=0.0, mode=None):
        """针对流量控制的 PID 整定"""
        L = 0.05
        lambda_val = 0.8 * T
        
        if mode is None:
            mode = Mode.FLOW_CONTROL
        
        return PIDTuner._lambda_tuning_core(
            K, T, L, lambda_val, mode,
            scenario='flow',
            kp_bounds=(0.2, 3.0),
            ti_bounds=(5.0, 60.0),
            td_bounds=(0.0, 0.0),
            force_td_zero=True
        )
    
    @staticmethod
    def cohen_coon_tuning(K, T, L):
        """Cohen-Coon 整定方法（适用于FOPDT模型）"""
        if L <= 0 or T <= 0 or abs(K) < Config.EPSILON:
            print("⚠️ Cohen-Coon 要求 T > 0 且 L > 0 且 K != 0，返回默认参数")
            return 1.0, 20.0, 1.0

        L_T_ratio = L / T if T > Config.EPSILON else 0.5
        Kc = (1 / K) * (T / L) * (4.0 / 3.0 + L_T_ratio / 4.0)
        Ti_denominator = 13 + 8 * L_T_ratio
        Td_denominator = 11 + 2 * L_T_ratio
        
        if abs(Ti_denominator) < Config.EPSILON:
            Ti = 20.0
        else:
            Ti = L * (32 + 6 * L_T_ratio) / Ti_denominator
        
        if abs(Td_denominator) < Config.EPSILON:
            Td = 1.0
        else:
            Td = (4 * L) / Td_denominator

        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td

        # 参数限幅
        pb = np.clip(pb, 100 / 6.0, 100 / 0.5)
        ti = np.clip(ti, 8.0, 120.0)
        td = np.clip(td, 0.0, 25.0)

        return pb, ti, td
    
    @staticmethod
    def tune_by_scenario(K, T, L, scenario, tuning_method, lambda_val=None, mode=Mode.STANDARD):
        """根据场景和整定方法统一调用整定函数"""
        if tuning_method == TuningMethod.COHEN_COON:
            return PIDTuner.cohen_coon_tuning(K, T, L)
        
        # Lambda 方法
        if scenario == 'temperature':
            return PIDTuner.lambda_tuning_for_temperature_control(K, T, L, lambda_val, mode)
        elif scenario == 'level':
            return PIDTuner.lambda_tuning_for_level_control(K, T, L, mode)
        elif scenario == 'flow' or mode == Mode.FLOW_CONTROL:
            return PIDTuner.lambda_tuning_for_flow(K, T, L, mode)
        else:
            return PIDTuner.lambda_tuning(K, T, L, lambda_val, mode)

