"""模型辨识器模块 - 各种系统模型的参数辨识"""

import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import uniform_filter1d

from .config import Config


class ModelIdentifier:
    """模型辨识器：负责各种系统模型的参数辨识"""
    
    # 模型仿真方法映射
    MODEL_SIMULATORS = {}
    INITIAL_GUESS_FORMATS = {
        'FO': lambda g: [g['K'], g['T']],
        'SO': lambda g: [g['K'], g['T'] / 2, g['T'] / 2],
        'SOPDT': lambda g: [g['K'], g['T'] / 2, g['T'] / 2, g['L']],
        'FO_INTEGRATOR': lambda g: [g['K'], g['L']],
        'SO_INTEGRATOR': lambda g: [g['K'], g['T'] / 2, g['T'] / 2],
        'FOPDT': lambda g: [g['K'], g['T'], g['L']],
    }
    
    # ============================================================
    # 高振荡数据检测与预处理
    # ============================================================
    
    @staticmethod
    def detect_high_oscillation(y: np.ndarray, u: np.ndarray) -> dict:
        """
        检测是否为高振荡开环数据
        
        Returns:
            dict: {is_oscillating, oscillation_ratio, amplitude_ratio, recommended_filter_size}
        """
        if len(y) < 20:
            return {'is_oscillating': False, 'oscillation_ratio': 0.0}
        
        # 计算PV符号变化比例
        pv_diff = np.diff(y)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        oscillation_ratio = sign_changes / (len(y) - 2)
        
        # 计算振荡幅度与总范围的比例
        pv_range = np.ptp(y)
        if pv_range > Config.EPSILON:
            # 使用中位数振幅估计振荡大小
            median_amplitude = np.median(np.abs(pv_diff))
            amplitude_ratio = median_amplitude / pv_range
        else:
            amplitude_ratio = 0.0
        
        # 判断是否为高振荡数据
        is_oscillating = oscillation_ratio > 0.25 or amplitude_ratio > 0.1
        
        # 推荐滤波窗口大小
        if oscillation_ratio > 0.4:
            recommended_filter = 9
        elif oscillation_ratio > 0.3:
            recommended_filter = 7
        elif oscillation_ratio > 0.2:
            recommended_filter = 5
        else:
            recommended_filter = 3
        
        return {
            'is_oscillating': is_oscillating,
            'oscillation_ratio': oscillation_ratio,
            'amplitude_ratio': amplitude_ratio,
            'recommended_filter_size': recommended_filter
        }
    
    @staticmethod
    def preprocess_oscillating_data(y: np.ndarray, u: np.ndarray, filter_size: int = 5) -> tuple:
        """
        预处理高振荡数据 - 使用自适应滤波
        
        Returns:
            (y_filtered, u_filtered)
        """
        if len(y) < filter_size:
            return y.copy(), u.copy()
        
        # 使用均值滤波平滑数据
        y_filtered = uniform_filter1d(y, size=filter_size, mode='nearest')
        u_filtered = uniform_filter1d(u, size=filter_size, mode='nearest')
        
        return y_filtered, u_filtered
    
    @staticmethod
    def estimate_gain_from_oscillating_data(y: np.ndarray, u: np.ndarray) -> float:
        """
        从高振荡数据中估计增益K
        使用包络线法而非直接计算
        """
        if len(y) < 20:
            return ModelIdentifier._estimate_gain_from_correlation(u, y, y[0])
        
        # 计算PV的上下包络线
        window = min(10, len(y) // 5)
        y_upper = np.zeros_like(y)
        y_lower = np.zeros_like(y)
        
        for i in range(len(y)):
            start = max(0, i - window)
            end = min(len(y), i + window + 1)
            y_upper[i] = np.max(y[start:end])
            y_lower[i] = np.min(y[start:end])
        
        # 使用包络线中线作为趋势
        y_trend = (y_upper + y_lower) / 2
        
        # 计算趋势增益
        y_trend_range = np.max(y_trend) - np.min(y_trend)
        u_range = np.max(u) - np.min(u)
        
        if u_range < Config.EPSILON:
            return 0.5
        
        K_magnitude = y_trend_range / u_range
        
        # 确定符号
        corr = np.corrcoef(u, y_trend)[0, 1] if len(u) > 2 else 0
        K_sign = 1.0 if np.isnan(corr) or corr >= 0 else -1.0
        
        return np.clip(K_magnitude * K_sign, -5.0, 5.0)
    
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
        """一阶加纯滞后（FOPDT）模型 - 增量形式"""
        K, T, L = params
        T = max(T, Config.EPSILON)
        n = len(t)
        y = np.zeros(n)
        y[0] = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        u_ref = u[0] if L_int == 0 else np.mean(u[:max(1, L_int)])
        y_ref = y0
        
        for i in range(1, n):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            y_target = y_ref + K * (u_delay - u_ref)
            alpha = min(dt_step / T, 1.0)
            y[i] = y[i-1] + alpha * (y_target - y[i-1])
        return y
    
    @staticmethod
    def first_order_model(params, t, u, y0):
        """纯一阶惯性模型（无滞后）- 增量形式"""
        K, T = params
        T = max(T, Config.EPSILON)
        n = len(t)
        y = np.zeros(n)
        y[0] = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        
        # 使用增量形式：模型响应MV的实时变化
        # 稳态目标基于当前MV相对于初始值的偏差
        u_ref = u[0]  # 参考MV
        y_ref = y0    # 参考PV
        
        for i in range(1, n):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            # 稳态目标: y_target = y_ref + K * (u[i] - u_ref)
            y_target = y_ref + K * (u[i] - u_ref)
            # 一阶响应
            alpha = dt_step / T
            alpha = min(alpha, 1.0)  # 防止超调
            y[i] = y[i-1] + alpha * (y_target - y[i-1])
        return y
    
    @staticmethod
    def second_order_model(params, t, u, y0):
        """二阶模型（两个一阶环节串联，无滞后）- 增量形式"""
        K, T1, T2 = params
        T1 = max(T1, Config.EPSILON)
        T2 = max(T2, Config.EPSILON)
        n = len(t)
        y = np.zeros(n)
        y[0] = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        u_ref = u[0]  # 参考MV
        y_ref = y0    # 参考PV
        x1 = y0       # 中间状态
        
        for i in range(1, n):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            # 稳态目标
            x1_target = y_ref + K * (u[i] - u_ref)
            # 第一阶响应
            alpha1 = min(dt_step / T1, 1.0)
            x1 = x1 + alpha1 * (x1_target - x1)
            # 第二阶响应
            alpha2 = min(dt_step / T2, 1.0)
            y[i] = y[i-1] + alpha2 * (x1 - y[i-1])
        return y
    
    @staticmethod
    def sopdt_model(params, t, u, y0):
        """二阶滞后模型 (SOPDT) - 增量形式"""
        K, T1, T2, L = params
        T1 = max(T1, Config.EPSILON)
        T2 = max(T2, Config.EPSILON)
        n = len(t)
        y = np.zeros(n)
        y[0] = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        u_ref = u[0] if L_int == 0 else np.mean(u[:max(1, L_int)])
        y_ref = y0
        x1 = y0
        
        for i in range(1, n):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            x1_target = y_ref + K * (u_delay - u_ref)
            alpha1 = min(dt_step / T1, 1.0)
            x1 = x1 + alpha1 * (x1_target - x1)
            alpha2 = min(dt_step / T2, 1.0)
            y[i] = y[i-1] + alpha2 * (x1 - y[i-1])
        return y
    
    @staticmethod
    def integral_delay_model(params, t, u, y0):
        """积分-延迟模型"""
        K, L = params
        n = len(t)
        y = np.zeros(n)
        y[0] = y0
        
        dt_avg, dt_array = ModelIdentifier._compute_sampling_info(t)
        L_int = ModelIdentifier._lag_to_samples(L, dt_avg)
        
        u0 = u[0] if L_int == 0 else np.mean(u[:max(1, L_int)])
        
        for i in range(1, n):
            dt_step = dt_array[i] if i < len(dt_array) else dt_avg
            u_delay = u[max(0, i - L_int)]
            y[i] = y[i-1] + K * (u_delay - u0) * dt_step
        return y
    
    @staticmethod
    def residuals(params, t, u, y_measured, y0, model_type='FOPDT', **kwargs):
        """统一的残差函数"""
        simulator = ModelIdentifier.MODEL_SIMULATORS.get(
            model_type, ModelIdentifier.fopdt_model
        )
        y_predicted = simulator(params, t, u, y0)
        return y_predicted - y_measured
    
    @staticmethod
    def _estimate_lag_from_correlation(u, y, dt):
        """使用互相关分析估计滞后时间"""
        if len(u) < 2 or len(y) < 2:
            return 0.0
        
        u_std, y_std = np.std(u), np.std(y)
        if u_std < Config.EPSILON or y_std < Config.EPSILON:
            return 0.0
        
        try:
            u_centered = u - np.mean(u)
            y_centered = y - np.mean(y)
            correlation = np.correlate(y_centered, u_centered, mode='full')
            
            if np.any(np.isnan(correlation)) or np.all(correlation == 0):
                return 0.0
            
            lags = np.arange(-len(u)+1, len(y))
            max_corr_idx = np.argmax(np.abs(correlation))
            lag_samples = lags[max_corr_idx]
            L_est = abs(lag_samples) * dt
            
            if np.isnan(L_est) or np.isinf(L_est):
                return 0.0
            
            return np.clip(L_est, 0.0, 30.0)
        except Exception:
            return 0.0
    
    @staticmethod
    def _estimate_gain_from_correlation(u, y, y0):
        """使用输入输出变化的相关性估计增益"""
        corr = np.corrcoef(u, y)[0, 1] if len(u) > 2 else 0
        u_range = np.max(u) - np.min(u)
        y_range = np.max(y) - np.min(y)
        
        if u_range < Config.EPSILON:
            return 0.5 if corr >= 0 else -0.5
        
        K_magnitude = y_range / u_range if u_range > Config.EPSILON else 0.5
        K_sign = 1.0 if corr >= 0 else -1.0
        K_est = K_magnitude * K_sign
        
        return np.clip(K_est, -5.0, 5.0)
    
    @staticmethod
    def _estimate_time_constant_from_response_speed(t, y, u, L_est):
        """从响应速度估计时间常数"""
        n = len(y)
        if n < 20:
            return 30.0
        
        if L_est is None or np.isnan(L_est) or np.isinf(L_est):
            L_est = 0.0
        
        dy_dt = np.gradient(y, t)
        max_dy_dt = np.max(np.abs(dy_dt))
        y_range = np.max(y) - np.min(y)
        T_est = y_range / max_dy_dt if max_dy_dt > Config.EPSILON else 30.0
        
        return np.clip(T_est, 5.0, 300.0)
    
    @staticmethod
    def estimate_initial_guess_from_operational_data(t, y, u, y0, sv=None, current_pid_params=None, use_closed_loop=False):
        """从正常运行数据估计 FOPDT 参数初始值"""
        n = len(t)
        if n < 20:
            return {'K': 0.5, 'T': 30.0, 'L': 5.0}
        
        dt = t[1] - t[0] if n > 1 else 1.0
        L_est = ModelIdentifier._estimate_lag_from_correlation(u, y, dt)
        K_est = ModelIdentifier._estimate_gain_from_correlation(u, y, y0)
        T_est = ModelIdentifier._estimate_time_constant_from_response_speed(t, y, u, L_est)
        
        return {
            'K': np.clip(K_est, -5.0, 5.0),
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
        """
        统一的模型辨识方法
        
        增强：自动检测高振荡数据并进行预处理
        """
        y0 = y[0] if len(y) > 0 else 0.0
        
        # 检测是否为高振荡数据
        oscillation_info = ModelIdentifier.detect_high_oscillation(y, u)
        
        if oscillation_info['is_oscillating']:
            # 对高振荡数据进行预处理
            filter_size = oscillation_info['recommended_filter_size']
            y_proc, u_proc = ModelIdentifier.preprocess_oscillating_data(y, u, filter_size)
            
            # 使用包络线法估计增益
            K_est = ModelIdentifier.estimate_gain_from_oscillating_data(y, u)
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(t, y_proc, u_proc, y0)
            initial_guess_dict['K'] = K_est
        else:
            y_proc, u_proc = y, u
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y0)
        
        formatter = ModelIdentifier.INITIAL_GUESS_FORMATS.get(
            model_type, ModelIdentifier.INITIAL_GUESS_FORMATS['FOPDT']
        )
        initial_guess = formatter(initial_guess_dict)
        
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['FOPDT'])
        bounds = model_config['initial']
        
        # 第一次优化：使用预处理后的数据
        try:
            result = least_squares(
                ModelIdentifier.residuals,
                initial_guess,
                args=(t, u_proc, y_proc, y0, model_type),
                kwargs=kwargs,
                bounds=bounds,
                method='trf',
                ftol=1e-4,
                xtol=1e-4,
                max_nfev=500,
                verbose=0
            )
            params = result.x if result.success else initial_guess
        except Exception:
            params = initial_guess
        
        # 如果是高振荡数据，进行二次验证和校正
        if oscillation_info['is_oscillating']:
            # 使用原始数据验证结果
            y_pred = ModelIdentifier.MODEL_SIMULATORS.get(
                model_type, ModelIdentifier.fopdt_model
            )(params, t, u, y0)
            
            # 计算幅度比例
            pred_range = np.ptp(y_pred)
            actual_range = np.ptp(y)
            
            if pred_range > Config.EPSILON and actual_range > Config.EPSILON:
                amplitude_ratio = pred_range / actual_range
                
                # 如果幅度比例不合理（>1.5或<0.5），调整K值
                if amplitude_ratio > 1.5 or amplitude_ratio < 0.5:
                    K_correction = actual_range / pred_range
                    params = list(params)
                    params[0] = params[0] * K_correction  # 校正K值
                    params = tuple(params)
        
        return ModelIdentifier._clip_params(params, model_type)
    
    @staticmethod
    def identify_fopdt(t, y, u, sv=None, current_pid_params=None):
        """辨识FOPDT模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FOPDT')
    
    @staticmethod
    def identify_first_order(t, y, u):
        """辨识FO模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FO')
    
    @staticmethod
    def identify_second_order(t, y, u):
        """辨识SO模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'SO')
    
    @staticmethod
    def identify_sopdt(t, y, u):
        """辨识SOPDT模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'SOPDT')
    
    @staticmethod
    def identify_integral_delay(t, y, u):
        """辨识FOPI模型参数"""
        return ModelIdentifier._identify_model_unified(t, y, u, 'FO_INTEGRATOR')


# 初始化模型仿真方法映射
ModelIdentifier.MODEL_SIMULATORS = {
    'FOPDT': ModelIdentifier.fopdt_model,
    'FO': ModelIdentifier.first_order_model,
    'SO': ModelIdentifier.second_order_model,
    'SOPDT': ModelIdentifier.sopdt_model,
    'FO_INTEGRATOR': ModelIdentifier.integral_delay_model,
    'SO_INTEGRATOR': ModelIdentifier.second_order_model,
}
