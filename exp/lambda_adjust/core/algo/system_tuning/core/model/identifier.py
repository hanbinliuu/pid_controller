"""模型辨识模块：负责系统模型的辨识和参数估计"""
import numpy as np
from scipy.optimize import least_squares
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config


class ModelIdentifier:
    """模型辨识器：负责各种系统模型的参数辨识"""
    
    @staticmethod
    def _compute_sampling_info(t):
        """计算采样间隔信息"""
        if len(t) > 1:
            dt_avg = np.mean(np.diff(t))
            dt_array = np.diff(t)
            dt_array = np.concatenate([[dt_avg], dt_array])
        else:
            dt_avg = 1.0
            dt_array = np.array([1.0])
        return dt_avg, dt_array
    
    @staticmethod
    def _lag_to_samples(L, dt_avg):
        """将滞后时间转换为采样点数"""
        return int(np.round(L / dt_avg)) if dt_avg > Config.EPSILON else 0
    
    @staticmethod
    def fopdt_model(params, t, u, y0):
        """一阶加纯滞后（FOPDT）模型"""
        K, T, L = params
        T = max(T, Config.EPSILON)
        y = np.ones_like(t) * y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            y[i] = y[i - 1] + (K * u_delay - (y[i - 1] - y0)) / T * dt_step
        return y
    
    @staticmethod
    def fopdt_with_heat_loss(params, t, u, y0, ambient_temp=0.0):
        """带热损失的 FOPDT 模型（适用于石油温控）"""
        K, T, L, alpha = params
        T = max(T, Config.EPSILON)
        y = np.ones_like(t) * y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            y[i] = y[i-1] + (K * u_delay - (y[i-1] - y0)) / T * dt_step
            heat_loss = alpha * (y[i] - ambient_temp) * dt_step / T
            y[i] -= heat_loss
        return y
    
    @staticmethod
    def second_order_model(params, t, u, y0):
        """二阶模型（两个一阶环节串联）"""
        K, T1, T2 = params
        T1 = max(T1, Config.EPSILON)
        T2 = max(T2, Config.EPSILON)
        y = np.ones_like(t) * y0
        x1 = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_eff = K * u[i]
            dx1_dt = (u_eff - x1) / T1
            x1 = x1 + dx1_dt * dt_step
            dy_dt = (x1 - y[i - 1]) / T2
            y[i] = y[i - 1] + dy_dt * dt_step
        return y
    
    @staticmethod
    def integral_delay_model(params, t, u, y0):
        """积分-延迟模型（适用于液位控制）"""
        K, L = params
        y = np.ones_like(t) * y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            y[i] = y[i-1] + K * u_delay * dt_step
        return y
    
    @staticmethod
    def residuals(params, t, u, y_measured, y0, model_type='fopdt', **kwargs):
        """统一的残差函数，支持所有模型类型"""
        if model_type == 'second_order':
            y_predicted = ModelIdentifier.second_order_model(params, t, u, y0)
        elif model_type == 'fopdt_with_heat_loss':
            ambient_temp = kwargs.get('ambient_temp', 0.0)
            y_predicted = ModelIdentifier.fopdt_with_heat_loss(params, t, u, y0, ambient_temp)
        elif model_type == 'integral_delay':
            y_predicted = ModelIdentifier.integral_delay_model(params, t, u, y0)
        else:  # 'fopdt'
            y_predicted = ModelIdentifier.fopdt_model(params, t, u, y0)
        return y_predicted - y_measured
    
    @staticmethod
    def _estimate_lag_from_correlation(u, y, dt):
        """使用互相关分析估计滞后时间"""
        # 检查输入数据的有效性
        if len(u) < 2 or len(y) < 2:
            return 0.0
        
        # 检查数据是否有变化
        u_std = np.std(u)
        y_std = np.std(y)
        
        if u_std < Config.EPSILON or y_std < Config.EPSILON:
            # 数据太平坦，无法估计滞后
            # print(f"⚠️ 数据标准差过小 (u_std={u_std:.6f}, y_std={y_std:.6f})，滞后设为0")
            return 0.0
        
        try:
            u_centered = u - np.mean(u)
            y_centered = y - np.mean(y)
            correlation = np.correlate(y_centered, u_centered, mode='full')
            
            # 检查correlation是否包含NaN
            if np.any(np.isnan(correlation)) or np.all(correlation == 0):
                return 0.0
            
            lags = np.arange(-len(u)+1, len(y))
            max_corr_idx = np.argmax(np.abs(correlation))
            lag_samples = lags[max_corr_idx]
            L_est = abs(lag_samples) * dt
            
            # 检查结果是否有效
            if np.isnan(L_est) or np.isinf(L_est):
                return 0.0
            
            return np.clip(L_est, 0.0, 30.0)
        except Exception as e:
            print(f"⚠️ 滞后估计失败: {e}，使用默认值0.0")
            return 0.0
    
    @staticmethod
    def _estimate_gain_from_correlation(u, y, y0):
        """使用输入输出变化的相关性估计增益"""
        du = np.diff(u)
        dy = np.diff(y)
        valid_mask = np.abs(du) > Config.EPSILON
        if np.sum(valid_mask) < 5:
            if np.std(u) > Config.EPSILON:
                return (np.max(y) - np.min(y)) / (np.max(u) - np.min(u)) if (np.max(u) - np.min(u)) > Config.EPSILON else 0.5
            return 0.5
        
        gains = dy[valid_mask] / du[valid_mask]
        Q1 = np.percentile(gains, 25)
        Q3 = np.percentile(gains, 75)
        IQR = Q3 - Q1
        valid_gains = gains[(gains >= Q1 - 1.5*IQR) & (gains <= Q3 + 1.5*IQR)]
        
        if len(valid_gains) > 0:
            K_est = np.median(valid_gains)
        else:
            if np.std(u) > Config.EPSILON:
                K_est = (np.max(y) - np.min(y)) / (np.max(u) - np.min(u)) if (np.max(u) - np.min(u)) > Config.EPSILON else 0.5
            else:
                K_est = 0.5
        return np.clip(K_est, 0.05, 1.5)
    
    @staticmethod
    def _estimate_time_constant_from_response_speed(t, y, u, L_est):
        """从响应速度估计时间常数"""
        n = len(y)
        if n < 20:
            return 30.0
        
        # 检查L_est是否有效
        if L_est is None or np.isnan(L_est) or np.isinf(L_est):
            L_est = 0.0  # 使用默认值
        
        dy_dt = np.gradient(y, t)
        
        # 安全计算L_samples
        if len(t) > 1:
            dt = t[1] - t[0]
            if dt > 0 and not np.isnan(dt):
                L_samples = int(np.round(L_est / dt))
            else:
                L_samples = 0
        else:
            L_samples = 0
        u_delayed = np.roll(u, L_samples)
        du = np.abs(np.diff(u_delayed))
        significant_change_mask = du > np.percentile(du, 75)
        
        if np.sum(significant_change_mask) < 3:
            max_dy_dt = np.max(np.abs(dy_dt))
            y_range = np.max(y) - np.min(y)
            T_est = y_range / max_dy_dt if max_dy_dt > Config.EPSILON else 30.0
        else:
            significant_dy_dt = dy_dt[1:][significant_change_mask]
            significant_y = y[1:][significant_change_mask]
            if len(significant_dy_dt) > 0 and np.max(np.abs(significant_dy_dt)) > Config.EPSILON:
                avg_response_speed = np.mean(np.abs(significant_dy_dt))
                y_range = np.max(significant_y) - np.min(significant_y)
                T_est = y_range / avg_response_speed if avg_response_speed > Config.EPSILON else 30.0
            else:
                T_est = 30.0
        return np.clip(T_est, 5.0, 300.0)
    
    @staticmethod
    def estimate_initial_guess_from_operational_data(t, y, u, y0, sv=None, current_pid_params=None, use_closed_loop=True):
        """从正常运行数据估计 FOPDT 参数初始值
        
        Args:
            t: 时间数组
            y: 输出数据（PV）
            u: 输入数据（MV）
            y0: 初始值
            sv: 设定值数组（可选，用于闭环辨识）
            current_pid_params: 当前PID参数（可选，用于闭环辨识）
            use_closed_loop: 是否使用闭环辨识增强（默认True）
        """
        n = len(t)
        if n < 20:
            return {'K': 0.5, 'T': 30.0, 'L': 5.0}
        
        # 方法1: 原有的开环辨识方法（基础方法）
        dt = t[1] - t[0] if n > 1 else 1.0
        L_est_basic = ModelIdentifier._estimate_lag_from_correlation(u, y, dt)
        K_est_basic = ModelIdentifier._estimate_gain_from_correlation(u, y, y0)
        T_est_basic = ModelIdentifier._estimate_time_constant_from_response_speed(t, y, u, L_est_basic)
        
        # 如果提供了SV和PID参数，且启用闭环辨识，使用增强方法
        if use_closed_loop and sv is not None and current_pid_params is not None:
            try:
                from .operational_identifier import OperationalDataIdentifier
                
                # 方法2: 闭环辨识增强
                K_cl, T_cl, L_cl = OperationalDataIdentifier.identify_from_closed_loop_data(
                    t, y, u, sv, current_pid_params
                )
                
                # 融合两种方法的结果（闭环方法权重更高）
                # 🔧 严格验证闭环辨识结果的合理性
                is_valid = (
                    K_cl > 0 and T_cl > 0 and  # 基本条件
                    not np.isnan(K_cl) and not np.isnan(T_cl) and not np.isnan(L_cl) and  # 不是NaN
                    not np.isinf(K_cl) and not np.isinf(T_cl) and not np.isinf(L_cl) and  # 不是无穷
                    K_cl < 10.0 and T_cl < 1000.0 and L_cl < 100.0  # 在合理范围内
                )
                
                if is_valid:  # 闭环辨识成功且结果合理
                    K_est = K_cl * 0.7 + K_est_basic * 0.3
                    T_est = T_cl * 0.7 + T_est_basic * 0.3
                    L_est = L_cl * 0.7 + L_est_basic * 0.3
                    print(f"✅ 使用闭环辨识增强: K={K_est:.3f}, T={T_est:.1f}, L={L_est:.1f}")
                else:
                    K_est, T_est, L_est = K_est_basic, T_est_basic, L_est_basic
                    if not (K_cl > 0 and T_cl > 0):
                        print(f"⚠️ 闭环辨识失败（参数为0或负数），使用基础方法")
                    else:
                        print(f"⚠️ 闭环辨识结果异常（K={K_cl:.3f}, T={T_cl:.1f}, L={L_cl:.1f}），使用基础方法")
            except Exception as e:
                print(f"⚠️ 闭环辨识模块加载失败: {e}，使用基础方法")
                K_est, T_est, L_est = K_est_basic, T_est_basic, L_est_basic
        else:
            K_est, T_est, L_est = K_est_basic, T_est_basic, L_est_basic
        
        return {
            'K': np.clip(K_est, 0.05, 1.5),
            'T': np.clip(T_est, 5.0, 300.0),
            'L': np.clip(L_est, 0.0, 30.0)
        }
    
    @staticmethod
    def _clip_params(params, model_type):
        """根据模型类型对参数进行限幅"""
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['fopdt'])
        clip_bounds = model_config['clip']
        clipped_params = [np.clip(params[i], clip_bounds[i][0], clip_bounds[i][1]) 
                         for i in range(len(params))]
        return tuple(clipped_params)
    
    @staticmethod
    def _identify_model_unified(t, y, u, model_type='fopdt', **kwargs):
        """统一的模型辨识方法，支持所有模型类型"""
        y0 = y[0] if len(y) > 0 else 0.0
        
        # 提取闭环辨识相关参数
        sv = kwargs.get('sv', None)
        current_pid_params = kwargs.get('current_pid_params', None)
        use_closed_loop = kwargs.get('use_closed_loop', True)
        
        # 获取初始猜测值（支持闭环辨识增强）
        if model_type == 'fopdt_with_heat_loss':
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
                t, y, u, y0, sv=sv, current_pid_params=current_pid_params, use_closed_loop=use_closed_loop
            )
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'], 
                           initial_guess_dict['L'], 0.01]  # alpha初始值
        elif model_type == 'second_order':
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
                t, y, u, y0, sv=sv, current_pid_params=current_pid_params, use_closed_loop=use_closed_loop
            )
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'] / 2, 
                           initial_guess_dict['T'] / 2]
        elif model_type == 'integral_delay':
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
                t, y, u, y0, sv=sv, current_pid_params=current_pid_params, use_closed_loop=use_closed_loop
            )
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['L']]
        else:  # 'fopdt'
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
                t, y, u, y0, sv=sv, current_pid_params=current_pid_params, use_closed_loop=use_closed_loop
            )
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'], initial_guess_dict['L']]
        
        # 获取边界
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['fopdt'])
        bounds = model_config['initial']
        
        try:
            result = least_squares(
                ModelIdentifier.residuals,
                initial_guess,
                args=(t, u, y, y0, model_type),
                kwargs=kwargs,
                bounds=bounds,
                method='trf',
                ftol=1e-4,
                xtol=1e-4,
                max_nfev=500,
                verbose=0
            )
            params = result.x if result.success else initial_guess
        except Exception as e:
            print(f"⚠️ {model_type}模型辨识失败：{e}，使用初始猜测值")
            params = initial_guess
        
        return ModelIdentifier._clip_params(params, model_type)
    
    @staticmethod
    def identify_fopdt(t, y, u, sv=None, current_pid_params=None):
        """辨识FOPDT模型参数
        
        Args:
            t: 时间数组
            y: 输出数据（PV）
            u: 输入数据（MV）
            sv: 设定值数组（可选，用于闭环辨识增强）
            current_pid_params: 当前PID参数（可选，用于闭环辨识增强）
        """
        return ModelIdentifier._identify_model_unified(
            t, y, u, 'fopdt', 
            sv=sv, 
            current_pid_params=current_pid_params
        )
    
    @staticmethod
    def identify_fopdt_with_heat_loss(t, y, u, ambient_temp=0.0):
        """辨识带热损失的 FOPDT 模型"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'fopdt_with_heat_loss', ambient_temp=ambient_temp)
    
    @staticmethod
    def identify_first_order(t, y, u):
        """辨识一阶模型参数（使用 fopdt 且强制 L=0）"""
        result = ModelIdentifier._identify_model_unified(t, y, u, 'fopdt')
        K, T, L = result
        return (K, T)
    
    @staticmethod
    def identify_second_order(t, y, u):
        """辨识二阶模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'second_order')
    
    @staticmethod
    def identify_integral_delay(t, y, u):
        """辨识积分-延迟模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'integral_delay')

