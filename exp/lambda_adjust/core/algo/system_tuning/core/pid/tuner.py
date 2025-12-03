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
        """Cohen-Coon 整定方法（适用于FOPDT模型，占比40%）
        
        优先用于阶跃响应法辨识的系统
        """
        if L <= 0 or T <= 0 or abs(K) < Config.EPSILON:
            print("⚠️ Cohen-Coon 要求 T > 0 且 L > 0 且 K != 0，返回默认参数")
            return 100.0, 20.0, 1.0

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
    def ziegler_nichols_tuning(K, T, L=0.0):
        """Ziegler-Nichols 整定方法（适用于纯一阶惯性模型，占比10%）
        
        适合压力控制等快速响应系统，无滞后或滞后很小
        传递函数: G(s) = K/(Ts+1)
        """
        if T <= 0 or abs(K) < Config.EPSILON:
            print("⚠️ Ziegler-Nichols 要求 T > 0 且 K != 0，返回默认参数")
            return 100.0, 20.0, 0.0
        
        # 对于纯一阶惯性系统，使用简化的Z-N公式
        # 基于开环响应的经验公式
        if L > 0:
            # 有滞后时使用经典Z-N公式
            Kc = 1.2 * T / (K * L)
            Ti = 2.0 * L
            Td = 0.5 * L
        else:
            # 无滞后时使用简化公式（纯一阶惯性）
            Kc = 0.9 / K
            Ti = 3.33 * T
            Td = 0.0  # 纯一阶系统不需要微分
        
        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td
        
        # 参数限幅
        pb = np.clip(pb, 10.0, 500.0)
        ti = np.clip(ti, 1.0, 200.0)
        td = np.clip(td, 0.0, 50.0)
        
        return pb, ti, td
    
    @staticmethod
    def improved_pi_tuning(K, L):
        """改进型PI算法（适用于积分过程 IDT，占比15%）
        
        用于液位控制等积分过程，弱积分+比例控制
        传递函数: G(s) = K/s * e^(-Ls)
        """
        if abs(K) < Config.EPSILON:
            print("⚠️ 改进型PI 要求 K != 0，返回默认参数")
            return 100.0, 60.0, 0.0
        
        L = max(L, 0.1)  # 确保滞后不为0
        
        # 积分过程的PI整定（Lambda方法变体）
        # 对于积分过程，Kc需要较小以避免振荡
        lambda_val = 3 * L  # 较大的lambda获得更平滑的响应
        
        Kc = 1 / (K * (lambda_val + L))
        Ti = lambda_val + L  # 积分时间等于闭环时间常数
        Td = 0.0  # 积分过程通常不用微分
        
        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td
        
        # 参数限幅（积分过程需要更保守的参数）
        pb = np.clip(pb, 50.0, 800.0)
        ti = np.clip(ti, 5.0, 300.0)
        td = np.clip(td, 0.0, 0.0)
        
        return pb, ti, td
    
    @staticmethod
    def derivative_first_pid_tuning(K, T1, T2, L):
        """PID + 微分先行算法（适用于 SOPDT 二阶滞后系统，占比15%）
        
        用于抑制二阶惯性，微分项作用于PV而非误差
        传递函数: G(s) = K/((T1s+1)(T2s+1)) * e^(-Ls)
        """
        if T1 <= 0 or T2 <= 0 or abs(K) < Config.EPSILON:
            print("⚠️ 微分先行PID 要求 T1, T2 > 0 且 K != 0，返回默认参数")
            return 100.0, 30.0, 5.0
        
        L = max(L, 0.1)
        T_eq = T1 + T2  # 等效时间常数
        
        # Lambda整定变体，考虑二阶特性
        lambda_val = max(T_eq, 2 * L)  # 较保守的lambda
        
        Kc = T_eq / (K * (lambda_val + L / 2))
        Ti = T_eq  # 积分时间等于等效时间常数
        Td = (T1 * T2) / T_eq  # 微分时间基于两个时间常数
        
        # 微分先行补偿：增加Td以抑制二阶惯性
        Td *= 1.2
        
        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td
        
        # 参数限幅
        pb = np.clip(pb, 20.0, 400.0)
        ti = np.clip(ti, 5.0, 200.0)
        td = np.clip(td, 1.0, 50.0)
        
        return pb, ti, td
    
    @staticmethod
    def damping_pid_tuning(K, T, zeta, L):
        """阻尼PID算法（适用于 SO+DT 二阶振荡系统，占比15%）
        
        增大Kd抑制振荡，补偿滞后+振荡
        传递函数: G(s) = K/(T²s²+2ζTs+1) * e^(-Ls)
        
        Args:
            K: 增益
            T: 时间常数
            zeta: 阻尼比 (ζ < 1 表示欠阻尼/振荡)
            L: 滞后时间
        """
        if T <= 0 or abs(K) < Config.EPSILON:
            print("⚠️ 阻尼PID 要求 T > 0 且 K != 0，返回默认参数")
            return 100.0, 30.0, 10.0
        
        L = max(L, 0.1)
        zeta = max(zeta, 0.1)  # 确保阻尼比有效
        
        # 根据阻尼比调整整定策略
        if zeta < 0.5:
            # 严重欠阻尼（强振荡）：非常保守的参数
            lambda_val = 3 * T
            td_factor = 2.0  # 大幅增加微分
        elif zeta < 0.707:
            # 欠阻尼：保守参数
            lambda_val = 2 * T
            td_factor = 1.5
        else:
            # 接近临界阻尼或过阻尼
            lambda_val = T
            td_factor = 1.0
        
        # 二阶系统的等效参数
        omega_n = 1.0 / T  # 自然频率
        
        Kc = (2 * zeta * T) / (K * (lambda_val + L / 2))
        Ti = 2 * zeta * T  # 积分时间与阻尼相关
        Td = T / (2 * zeta) * td_factor  # 微分时间，增强以抑制振荡
        
        pb = 100 / Kc if Kc != 0 else 100.0
        ti = Ti
        td = Td
        
        # 参数限幅（振荡系统需要更大的微分）
        pb = np.clip(pb, 30.0, 500.0)
        ti = np.clip(ti, 5.0, 150.0)
        td = np.clip(td, 2.0, 80.0)
        
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
    
    @staticmethod
    def tune_by_model_type(model_type, model_params, mode=Mode.STANDARD):
        """根据模型类型自动选择最佳整定算法
        
        Args:
            model_type: 模型类型 ('fopdt', 'first_order', 'sopdt', 'so_dt', 'integral_delay')
            model_params: 模型参数（取决于模型类型）
            mode: 控制模式
            
        Returns:
            (pb, ti, td): PID参数
            tuning_info: 整定信息字典
        """
        tuning_info = {
            'model_type': model_type,
            'tuning_method': None,
            'model_params': model_params
        }
        
        if model_type == 'fopdt':
            # FOPDT: 优先使用 Cohen-Coon（占比40%）
            K, T, L = model_params[:3]
            if L > 0:
                pb, ti, td = PIDTuner.cohen_coon_tuning(K, T, L)
                tuning_info['tuning_method'] = 'Cohen-Coon'
            else:
                pb, ti, td = PIDTuner.lambda_tuning(K, T, L, mode=mode)
                tuning_info['tuning_method'] = 'Lambda'
                
        elif model_type == 'first_order':
            # 纯一阶惯性: 使用 Ziegler-Nichols（占比10%）
            K, T = model_params[:2]
            pb, ti, td = PIDTuner.ziegler_nichols_tuning(K, T, L=0.0)
            tuning_info['tuning_method'] = 'Ziegler-Nichols'
            
        elif model_type == 'integral_delay':
            # 积分-延迟: 使用改进型PI（占比15%）
            K, L = model_params[:2]
            pb, ti, td = PIDTuner.improved_pi_tuning(K, L)
            tuning_info['tuning_method'] = 'Improved-PI'
            
        elif model_type == 'sopdt':
            # SOPDT: 使用 PID+微分先行（占比15%）
            K, T1, T2, L = model_params[:4]
            pb, ti, td = PIDTuner.derivative_first_pid_tuning(K, T1, T2, L)
            tuning_info['tuning_method'] = 'Derivative-First-PID'
            
        elif model_type == 'so_dt':
            # SO+DT: 使用阻尼PID（占比15%）
            K, T, zeta, L = model_params[:4]
            pb, ti, td = PIDTuner.damping_pid_tuning(K, T, zeta, L)
            tuning_info['tuning_method'] = 'Damping-PID'
            
        else:
            # 默认使用Lambda方法
            K = model_params[0] if len(model_params) > 0 else 0.5
            T = model_params[1] if len(model_params) > 1 else 30.0
            L = model_params[2] if len(model_params) > 2 else 5.0
            pb, ti, td = PIDTuner.lambda_tuning(K, T, L, mode=mode)
            tuning_info['tuning_method'] = 'Lambda'
        
        print(f"📊 模型类型: {model_type}, 整定算法: {tuning_info['tuning_method']}")
        print(f"   参数: pb={pb:.2f}%, ti={ti:.2f}s, td={td:.2f}s")
        
        return pb, ti, td, tuning_info

