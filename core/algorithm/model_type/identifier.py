"""
模型辨识器模块 (Model Identifier Module)
========================================

本模块实现各种过程模型的参数辨识算法。

支持的模型类型
--------------
- **FOPDT**: 一阶加纯滞后模型 G(s) = K/(Ts+1)*e^(-Ls)
- **FO**: 纯一阶模型 G(s) = K/(Ts+1)
- **SO**: 纯二阶模型 G(s) = K/((T1s+1)(T2s+1))
- **SOPDT**: 二阶加纯滞后模型 G(s) = K/((T1s+1)(T2s+1))*e^(-Ls)
- **FOPI**: 一阶积分模型 G(s) = K/s * 1/(Ts+1)

核心功能
--------
1. **高振荡数据处理**: 检测振荡严重程度，使用包络线法估计参数
2. **稳健KTL估计**: 综合首尾稳态法、包络线法、分段中位数法
3. **增量形式仿真**: 所有模型使用增量形式，适应实际工况数据
4. **参数边界约束**: 基于Config配置的参数边界进行优化

主要方法
--------
- detect_high_oscillation: 检测高振荡数据
- estimate_ktl_robust: 稳健的KTL参数估计
- identify_fopdt/identify_first_order/...: 各模型的辨识方法
"""

import numpy as np
from scipy.optimize import least_squares
from scipy.ndimage import uniform_filter1d

from .config import Config
from scipy.signal import savgol_filter


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
            dict: {is_oscillating, oscillation_ratio, amplitude_ratio, 
                   recommended_filter_size, severity_level}
        """
        if len(y) < 20:
            return {'is_oscillating': False, 'oscillation_ratio': 0.0, 'severity_level': 'none'}
        
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
            
            # 计算包络线振荡比（上下包络线的平均差值与总范围的比值）
            window = max(5, len(y) // 20)
            y_upper = np.array([np.max(y[max(0,i-window):min(len(y),i+window+1)]) for i in range(len(y))])
            y_lower = np.array([np.min(y[max(0,i-window):min(len(y),i+window+1)]) for i in range(len(y))])
            envelope_width = np.median(y_upper - y_lower)
            envelope_ratio = envelope_width / pv_range
        else:
            amplitude_ratio = 0.0
            envelope_ratio = 0.0
        
        # 判断振荡严重程度
        # 综合考虑：振荡频率(oscillation_ratio) + 振荡幅度(envelope_ratio)
        # severe: 高频+大幅 或 极大幅度 → 需要使用包络线趋势拟合
        # moderate: 中等振荡 → 需要使用滤波预处理
        # mild: 轻微振荡 → 正常处理带滤波
        
        # 计算综合振荡得分（同时考虑频率和幅度）
        osc_score = 0.4 * oscillation_ratio + 0.6 * envelope_ratio
        
        if envelope_ratio > 0.7 or (oscillation_ratio > 0.5 and envelope_ratio > 0.5):
            # 大幅度振荡，无论频率高低都用趋势拟合
            severity_level = 'severe'
            is_oscillating = True
        elif osc_score > 0.4 or envelope_ratio > 0.5:
            severity_level = 'moderate'
            is_oscillating = True
        elif oscillation_ratio > 0.25 or amplitude_ratio > 0.08:
            severity_level = 'mild'
            is_oscillating = True
        else:
            severity_level = 'none'
            is_oscillating = False
        
        # 推荐滤波窗口大小
        if severity_level == 'severe':
            recommended_filter = 11
        elif severity_level == 'moderate':
            recommended_filter = 7
        elif severity_level == 'mild':
            recommended_filter = 5
        else:
            recommended_filter = 3
        
        return {
            'is_oscillating': is_oscillating,
            'oscillation_ratio': oscillation_ratio,
            'amplitude_ratio': amplitude_ratio,
            'envelope_ratio': envelope_ratio if pv_range > Config.EPSILON else 0.0,
            'recommended_filter_size': recommended_filter,
            'severity_level': severity_level
        }
    
    @staticmethod
    def preprocess_oscillating_data(y: np.ndarray, u: np.ndarray, filter_size: int = 5, 
                                     severity: str = 'mild') -> tuple:
        """
        预处理高振荡数据 - 根据严重程度选择处理方法
        
        Args:
            y: PV数据
            u: MV数据  
            filter_size: 滤波窗口大小
            severity: 振荡严重程度 ('mild', 'moderate', 'severe')
        
        Returns:
            (y_filtered, u_filtered)
        """
        if len(y) < filter_size:
            return y.copy(), u.copy()
        
        if severity == 'severe':
            # 严重振荡：使用包络线中线作为趋势
            y_filtered = ModelIdentifier._extract_envelope_trend(y, filter_size)
            u_filtered = uniform_filter1d(u, size=filter_size, mode='nearest')
        elif severity == 'moderate':
            # 中等振荡：使用Savitzky-Golay滤波保持趋势
            window = min(filter_size * 2 + 1, len(y) - 2)
            if window % 2 == 0:
                window += 1
            window = max(5, window)
            try:
                y_filtered = savgol_filter(y, window, min(3, window - 2))
                u_filtered = savgol_filter(u, window, min(3, window - 2))
            except Exception:
                y_filtered = uniform_filter1d(y, size=filter_size, mode='nearest')
                u_filtered = uniform_filter1d(u, size=filter_size, mode='nearest')
        else:
            # 轻微振荡：使用均值滤波
            y_filtered = uniform_filter1d(y, size=filter_size, mode='nearest')
            u_filtered = uniform_filter1d(u, size=filter_size, mode='nearest')
        
        return y_filtered, u_filtered
    
    @staticmethod
    def _extract_envelope_trend(y: np.ndarray, window: int = 5) -> np.ndarray:
        """
        提取包络线中线作为趋势
        
        对于高振荡数据，包络线中线比简单滤波更能反映真实趋势
        """
        n = len(y)
        half_w = max(window, n // 20)
        
        y_upper = np.zeros(n)
        y_lower = np.zeros(n)
        
        for i in range(n):
            start = max(0, i - half_w)
            end = min(n, i + half_w + 1)
            y_upper[i] = np.max(y[start:end])
            y_lower[i] = np.min(y[start:end])
        
        # 包络线中线
        y_trend = (y_upper + y_lower) / 2
        
        # 再做一次平滑以消除阶梯效应
        y_trend = uniform_filter1d(y_trend, size=max(3, window // 2), mode='nearest')
        
        return y_trend
    
    @staticmethod
    def estimate_gain_from_oscillating_data(y: np.ndarray, u: np.ndarray, 
                                             return_trend: bool = False) -> float:
        """
        从高振荡数据中估计增益K
        使用包络线趋势法 + 分段验证
        
        Args:
            y: PV数据
            u: MV数据
            return_trend: 是否同时返回趋势数据
        
        Returns:
            K值（如果return_trend=True，返回 (K, y_trend, u_smooth)）
        """
        if len(y) < 20:
            K = ModelIdentifier._estimate_gain_from_correlation(u, y, y[0])
            if return_trend:
                return K, y.copy(), u.copy()
            return K
        
        # 提取包络线趋势
        window = max(5, len(y) // 20)
        y_trend = ModelIdentifier._extract_envelope_trend(y, window)
        u_smooth = uniform_filter1d(u, size=window, mode='nearest')
        
        # 方法1：总体变化量比值法
        y_trend_range = np.max(y_trend) - np.min(y_trend)
        u_range = np.max(u_smooth) - np.min(u_smooth)
        
        if u_range < Config.EPSILON:
            K = 0.5
        else:
            K_total = y_trend_range / u_range
            
            # 方法2：分段增益验证（使用多个子段计算增益，取中位数）
            n_segments = min(4, len(y) // 30)
            segment_gains = []
            
            if n_segments >= 2:
                seg_len = len(y) // n_segments
                for i in range(n_segments):
                    start = i * seg_len
                    end = start + seg_len if i < n_segments - 1 else len(y)
                    
                    dy = y_trend[end-1] - y_trend[start]
                    du = u_smooth[end-1] - u_smooth[start]
                    
                    if abs(du) > Config.EPSILON * 10:
                        segment_gains.append(abs(dy / du))
                
                if segment_gains:
                    K_segments = np.median(segment_gains)
                    # 如果分段结果与总体结果差异不大，使用加权平均
                    if 0.5 <= K_segments / (K_total + Config.EPSILON) <= 2.0:
                        K_magnitude = 0.6 * K_total + 0.4 * K_segments
                    else:
                        # 差异较大，优先使用分段中位数（更稳健）
                        K_magnitude = K_segments
                else:
                    K_magnitude = K_total
            else:
                K_magnitude = K_total
            
            K = K_magnitude
        
        # 确定符号
        corr = np.corrcoef(u_smooth, y_trend)[0, 1] if len(u) > 2 else 0
        K_sign = 1.0 if np.isnan(corr) or corr >= 0 else -1.0
        K = np.clip(K * K_sign, -10.0, 10.0)
        
        if return_trend:
            return K, y_trend, u_smooth
        return K
    
    @staticmethod
    def estimate_ktl_robust(y: np.ndarray, u: np.ndarray, t: np.ndarray) -> dict:
        """
        稳健的KTL参数估计（专门用于高振荡数据）
        
        使用多种方法综合估计，取最稳健的结果：
        1. 首尾稳态法（最可靠）
        2. 包络线趋势法
        3. 分段中位数法
        
        Returns:
            dict: {'K': K, 'T': T, 'L': L, 'confidence': 置信度}
        """
        n = len(y)
        if n < 30:
            initial = ModelIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y[0])
            return {'K': initial['K'], 'T': initial['T'], 'L': initial['L'], 'confidence': 0.5}
        
        # 提取包络线趋势
        window = max(5, n // 20)
        y_trend = ModelIdentifier._extract_envelope_trend(y, window)
        u_smooth = uniform_filter1d(u, size=window, mode='nearest')
        
        # ========== 方法1：首尾稳态法（最可靠） ==========
        # 使用首尾各10%的数据计算稳态值
        head_len = max(10, n // 10)
        tail_len = max(10, n // 10)
        
        # 对于振荡数据，使用包络线中线的首尾值更稳定
        y_head = np.mean(y_trend[:head_len])
        y_tail = np.mean(y_trend[-tail_len:])
        u_head = np.mean(u_smooth[:head_len])
        u_tail = np.mean(u_smooth[-tail_len:])
        
        delta_y = y_tail - y_head
        delta_u = u_tail - u_head
        
        # 同时计算原始数据的首尾差（对于高振荡可能更准确）
        y_head_raw = np.mean(y[:head_len])
        y_tail_raw = np.mean(y[-tail_len:])
        delta_y_raw = y_tail_raw - y_head_raw
        
        if abs(delta_u) > Config.EPSILON * 10:
            K_steady_trend = delta_y / delta_u
            K_steady_raw = delta_y_raw / delta_u
            # 取两者中更接近包络线范围法的那个
            K_envelope_approx = (np.ptp(y_trend)) / (np.ptp(u_smooth) + Config.EPSILON)
            if abs(K_steady_raw - K_envelope_approx) < abs(K_steady_trend - K_envelope_approx):
                K_steady = K_steady_raw
            else:
                K_steady = K_steady_trend
        else:
            K_steady = None
        
        # ========== 方法2：包络线趋势范围法 ==========
        y_trend_range = np.max(y_trend) - np.min(y_trend)
        u_range = np.max(u_smooth) - np.min(u_smooth)
        
        if u_range > Config.EPSILON:
            K_envelope = y_trend_range / u_range
            # 确定符号
            corr = np.corrcoef(u_smooth, y_trend)[0, 1] if n > 2 else 0
            if not np.isnan(corr) and corr < 0:
                K_envelope = -K_envelope
        else:
            K_envelope = None
        
        # ========== 方法3：分段中位数法 ==========
        n_segments = min(4, n // 30)
        segment_gains = []
        if n_segments >= 2:
            seg_len = n // n_segments
            for i in range(n_segments):
                start = i * seg_len
                end = start + seg_len if i < n_segments - 1 else n
                
                dy = y_trend[end-1] - y_trend[start]
                du = u_smooth[end-1] - u_smooth[start]
                
                if abs(du) > Config.EPSILON * 10:
                    segment_gains.append(dy / du)
        
        K_segments = np.median(segment_gains) if segment_gains else None
        
        # ========== 综合选择最可靠的K值 ==========
        # 优先级：首尾稳态法 > 分段中位数法 > 包络线法
        valid_Ks = []
        weights = []
        
        if K_steady is not None and abs(K_steady) > Config.EPSILON:
            valid_Ks.append(K_steady)
            weights.append(3.0)  # 最高权重
        
        if K_segments is not None and abs(K_segments) > Config.EPSILON:
            valid_Ks.append(K_segments)
            weights.append(2.0)
        
        if K_envelope is not None and abs(K_envelope) > Config.EPSILON:
            valid_Ks.append(K_envelope)
            weights.append(1.0)
        
        if not valid_Ks:
            K = 1.0
            confidence = 0.3
        elif len(valid_Ks) == 1:
            K = valid_Ks[0]
            confidence = 0.5
        else:
            # 检查一致性
            K_mean = np.average(valid_Ks, weights=weights)
            K_std = np.std(valid_Ks)
            cv = abs(K_std / K_mean) if abs(K_mean) > Config.EPSILON else 1.0
            
            if cv < 0.3:
                # 结果一致，使用加权平均
                K = K_mean
                confidence = 0.9
            elif cv < 0.5:
                # 中等一致性，优先使用稳态法
                K = valid_Ks[0]  # 权重最高的那个
                confidence = 0.7
            else:
                # 结果差异大，使用中位数
                K = np.median(valid_Ks)
                confidence = 0.5
        
        # 使用趋势数据估计T和L
        initial = ModelIdentifier.estimate_initial_guess_from_operational_data(
            t, y_trend, u_smooth, y_trend[0]
        )
        
        return {
            'K': K,
            'T': initial['T'],
            'L': initial['L'],
            'confidence': confidence,
            'K_steady': K_steady,
            'K_envelope': K_envelope,
            'K_segments': K_segments
        }
    
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
        
        增强：
        1. 根据振荡严重程度选择不同处理策略
        2. 严重振荡使用包络线趋势拟合
        3. 多重验证确保KTL准确性
        """
        y0 = y[0] if len(y) > 0 else 0.0
        
        # 检测是否为高振荡数据
        oscillation_info = ModelIdentifier.detect_high_oscillation(y, u)
        severity = oscillation_info.get('severity_level', 'none')
        
        if oscillation_info['is_oscillating']:
            filter_size = oscillation_info['recommended_filter_size']
            envelope_ratio = oscillation_info.get('envelope_ratio', 0)
            
            # 对于中等及以上振荡，或包络比>0.3，都使用稳健估计
            use_robust = severity in ['severe', 'moderate'] or envelope_ratio > 0.3
            
            if use_robust:
                # 使用稳健的KTL估计方法
                robust_ktl = ModelIdentifier.estimate_ktl_robust(y, u, t)
                K_est = robust_ktl['K']
                
                # 提取趋势用于拟合
                _, y_trend, u_smooth = ModelIdentifier.estimate_gain_from_oscillating_data(
                    y, u, return_trend=True
                )
                y_proc, u_proc = y_trend, u_smooth
                
                initial_guess_dict = {
                    'K': K_est,
                    'T': robust_ktl['T'],
                    'L': robust_ktl['L']
                }
                y0_fit = y_trend[0]
            else:
                # 轻微振荡：使用滤波预处理
                y_proc, u_proc = ModelIdentifier.preprocess_oscillating_data(
                    y, u, filter_size, severity
                )
                K_est = ModelIdentifier.estimate_gain_from_oscillating_data(y, u)
                initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(
                    t, y_proc, u_proc, y0
                )
                initial_guess_dict['K'] = K_est
                y0_fit = y0
        else:
            y_proc, u_proc = y, u
            initial_guess_dict = ModelIdentifier.estimate_initial_guess_from_operational_data(t, y, u, y0)
            y0_fit = y0
        
        formatter = ModelIdentifier.INITIAL_GUESS_FORMATS.get(
            model_type, ModelIdentifier.INITIAL_GUESS_FORMATS['FOPDT']
        )
        initial_guess = formatter(initial_guess_dict)
        
        model_config = Config.MODEL_BOUNDS.get(model_type, Config.MODEL_BOUNDS['FOPDT'])
        bounds = model_config['initial']
        
        # 第一次优化：使用预处理后的数据
        # 对于使用稳健估计的情况，保存稳健K值用于后续校正
        used_robust = oscillation_info['is_oscillating'] and (
            severity in ['severe', 'moderate'] or 
            oscillation_info.get('envelope_ratio', 0) > 0.3
        )
        robust_K = initial_guess_dict.get('K') if used_robust else None
        
        try:
            result = least_squares(
                ModelIdentifier.residuals,
                initial_guess,
                args=(t, u_proc, y_proc, y0_fit, model_type),
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
            # 对于使用稳健估计的情况，优先使用稳健K值
            if used_robust and robust_K is not None:
                # 检查优化后的K与稳健K的差异
                optimized_K = params[0]
                if abs(robust_K) > Config.EPSILON:
                    K_ratio = abs(optimized_K / robust_K)
                    # 如果优化后的K与稳健K差异超过50%，使用稳健K
                    if K_ratio > 1.5 or K_ratio < 0.67:
                        params = list(params)
                        params[0] = robust_K
                        params = tuple(params)
            else:
                # 旧的验证逻辑
                if severity == 'severe':
                    y_target = y_trend if 'y_trend' in dir() else y_proc
                    u_target = u_smooth if 'u_smooth' in dir() else u_proc
                else:
                    y_target = y
                    u_target = u
                
                y_pred = ModelIdentifier.MODEL_SIMULATORS.get(
                    model_type, ModelIdentifier.fopdt_model
                )(params, t, u_target, y0_fit)
                
                pred_range = np.ptp(y_pred)
                target_range = np.ptp(y_target)
                
                if pred_range > Config.EPSILON and target_range > Config.EPSILON:
                    amplitude_ratio = pred_range / target_range
                    if amplitude_ratio > 1.3 or amplitude_ratio < 0.7:
                        K_correction = target_range / pred_range
                        params = list(params)
                        params[0] = params[0] * K_correction
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
