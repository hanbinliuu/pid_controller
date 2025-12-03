import numpy as np
from scipy.optimize import least_squares

try:
    from .config import Config
except ImportError:
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
    def first_order_model(params, t, u, y0):
        """纯一阶惯性模型（无滞后）: G(s) = K/(Ts+1)
        
        适用场景：压力控制等快速响应系统（占比约10%）
        """
        K, T = params
        T = max(T, Config.EPSILON)
        y = np.ones_like(t) * y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            y[i] = y[i - 1] + (K * u[i] - (y[i - 1] - y0)) / T * dt_step
        return y
    
    @staticmethod
    def second_order_model(params, t, u, y0):
        """二阶模型（两个一阶环节串联，无滞后）"""
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
    def sopdt_model(params, t, u, y0):
        """二阶滞后模型 (SOPDT): G(s) = K/((T1s+1)(T2s+1)) * e^(-Ls)
        
        适用场景：具有二阶惯性和滞后的系统（占比约15%）
        整定建议：PID + 微分先行（抑制二阶惯性）
        """
        K, T1, T2, L = params
        T1 = max(T1, Config.EPSILON)
        T2 = max(T2, Config.EPSILON)
        y = np.ones_like(t) * y0
        x1 = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            u_eff = K * u_delay
            dx1_dt = (u_eff - x1) / T1
            x1 = x1 + dx1_dt * dt_step
            dy_dt = (x1 - y[i - 1]) / T2
            y[i] = y[i - 1] + dy_dt * dt_step
        return y
    
    @staticmethod
    def so_dt_model(params, t, u, y0):
        """二阶振荡+滞后模型 (SO+DT): G(s) = K/(T²s²+2ζTs+1) * e^(-Ls)
        
        适用场景：具有振荡特性的二阶系统（占比约15%）
        整定建议：阻尼PID（增大Kd抑制振荡）
        
        参数: K, T, zeta(ζ阻尼比), L
        - ζ < 1: 欠阻尼（振荡）
        - ζ = 1: 临界阻尼
        - ζ > 1: 过阻尼
        """
        K, T, zeta, L = params
        T = max(T, Config.EPSILON)
        zeta = max(zeta, 0.01)  # 防止除零
        y = np.ones_like(t) * y0
        dy = 0.0  # 导数状态
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        # 二阶系统的状态空间表示
        # T²*y'' + 2ζT*y' + y = K*u
        # 转换为: y'' = (K*u - y - 2ζT*y') / T²
        omega_n = 1.0 / T  # 自然频率
        
        for i in range(len(t)):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            
            # 二阶微分方程的数值积分
            d2y = omega_n**2 * (K * u_delay - (y[i-1] - y0)) - 2 * zeta * omega_n * dy
            dy = dy + d2y * dt_step
            y[i] = y[i - 1] + dy * dt_step
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
    def residuals(params, t, u, y_measured, y0, model_type='FOPDT', **kwargs):
        """统一的残差函数，支持所有模型类型"""
        if model_type == 'FO':
            y_predicted = ModelIdentifier.first_order_model(params, t, u, y0)
        elif model_type == 'SO':
            y_predicted = ModelIdentifier.second_order_model(params, t, u, y0)
        elif model_type == 'SOPDT':
            y_predicted = ModelIdentifier.sopdt_model(params, t, u, y0)
        elif model_type == 'FO_INTEGRATOR':
            y_predicted = ModelIdentifier.integral_delay_model(params, t, u, y0)
        elif model_type == 'SO_INTEGRATOR':
            y_predicted = ModelIdentifier.second_order_model(params, t, u, y0)  # 简化处理
        else:  # 'FOPDT'
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
    def estimate_initial_guess_from_operational_data(t, y, u, y0, sv=None, current_pid_params=None, use_closed_loop=False):
        """从正常运行数据估计 FOPDT 参数初始值
        
        Args:
            t: 时间数组
            y: 输出数据（PV）
            u: 输入数据（MV）
            y0: 初始值
            sv: 设定值数组（可选，用于闭环辨识）
            current_pid_params: 当前PID参数（可选，用于闭环辨识）
            use_closed_loop: 是否使用闭环辨识增强（默认False，本地版本不支持）
        """
        n = len(t)
        if n < 20:
            return {'K': 0.5, 'T': 30.0, 'L': 5.0}
        
        # 使用开环辨识方法
        dt = t[1] - t[0] if n > 1 else 1.0
        L_est = ModelIdentifier._estimate_lag_from_correlation(u, y, dt)
        K_est = ModelIdentifier._estimate_gain_from_correlation(u, y, y0)
        T_est = ModelIdentifier._estimate_time_constant_from_response_speed(t, y, u, L_est)
        
        return {
            'K': np.clip(K_est, 0.05, 1.5),
            'T': np.clip(T_est, 5.0, 300.0),
            'L': np.clip(L_est, 0.0, 30.0)
        }
    
    @staticmethod
    def _clip_params(params, model_type):
        """根据模型类型对参数进行限幅"""
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['FOPDT'])
        clip_bounds = model_config['clip']
        clipped_params = [np.clip(params[i], clip_bounds[i][0], clip_bounds[i][1]) 
                         for i in range(len(params))]
        return tuple(clipped_params)
    
    @staticmethod
    def _identify_model_unified(t, y, u, model_type='FOPDT', **kwargs):
        """统一的模型辨识方法，支持所有模型类型"""
        y0 = y[0] if len(y) > 0 else 0.0
        
        # 获取初始猜测值
        initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
            t, y, u, y0
        )
        
        if model_type == 'FO':
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T']]
        elif model_type == 'SO':
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'] / 2, 
                           initial_guess_dict['T'] / 2]
        elif model_type == 'SOPDT':
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'] / 2, 
                           initial_guess_dict['T'] / 2, initial_guess_dict['L']]
        elif model_type == 'FO_INTEGRATOR':
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['L']]
        elif model_type == 'SO_INTEGRATOR':
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'] / 2, 
                           initial_guess_dict['T'] / 2]
        else:  # 'FOPDT'
            initial_guess = [initial_guess_dict['K'], initial_guess_dict['T'], initial_guess_dict['L']]
        
        # 获取边界
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['FOPDT'])
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
        """辨识FOPDT模型参数 (一阶加纯滞后)"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FOPDT')
    
    @staticmethod
    def identify_first_order(t, y, u):
        """辨识FO模型参数 (纯一阶): G(s) = K/(Ts+1)"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FO')
    
    @staticmethod
    def identify_second_order(t, y, u):
        """辨识SO模型参数 (纯二阶，无滞后)"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'SO')
    
    @staticmethod
    def identify_sopdt(t, y, u):
        """辨识SOPDT模型参数 (二阶加纯滞后)"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'SOPDT')
    
    @staticmethod
    def identify_integral_delay(t, y, u):
        """辨识FOPI模型参数 (一阶积分)"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FO_INTEGRATOR')
