"""
基于正常运行数据的系统辨识模块
专门针对化工企业无法进行阶跃测试的场景

核心思路：
1. 利用闭环运行数据（PID已在工作）
2. 从小扰动和设定值变化中提取系统信息
3. 使用多种方法交叉验证，提高鲁棒性
"""
import numpy as np
from scipy.optimize import least_squares, differential_evolution
from scipy.signal import correlate, find_peaks, welch
from scipy.fft import fft, fftfreq
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config


class OperationalDataIdentifier:
    """基于正常运行数据的系统辨识器"""
    
    @staticmethod
    def identify_from_closed_loop_data(t, pv, mv, sv, current_pid_params):
        """
        从闭环运行数据辨识系统模型
        
        核心方法：闭环辨识 + 多信息源融合
        
        Args:
            t: 时间数组
            pv: 过程变量（输出）
            mv: 操纵变量（控制器输出）
            sv: 设定值
            current_pid_params: 当前PID参数 {'pb': xx, 'ti': xx, 'td': xx}
            
        Returns:
            (K, T, L): FOPDT模型参数
        """
        print("🔍 使用闭环运行数据进行系统辨识...")
        
        # 方法1: 基于设定值变化的辨识（如果有SV变化）
        K1, T1, L1, confidence1 = OperationalDataIdentifier._identify_from_setpoint_changes(
            t, pv, mv, sv
        )
        
        # 方法2: 基于扰动响应的辨识
        K2, T2, L2, confidence2 = OperationalDataIdentifier._identify_from_disturbances(
            t, pv, mv, sv
        )
        
        # 方法3: 基于频域分析的辨识
        K3, T3, L3, confidence3 = OperationalDataIdentifier._identify_from_frequency_domain(
            t, pv, mv, sv
        )
        
        # 方法4: 基于闭环传递函数的辨识
        K4, T4, L4, confidence4 = OperationalDataIdentifier._identify_from_closed_loop_tf(
            t, pv, mv, sv, current_pid_params
        )
        
        # 加权融合多种方法的结果
        methods = [
            (K1, T1, L1, confidence1, "设定值变化法"),
            (K2, T2, L2, confidence2, "扰动响应法"),
            (K3, T3, L3, confidence3, "频域分析法"),
            (K4, T4, L4, confidence4, "闭环传递函数法")
        ]
        
        # 过滤掉置信度为0的方法
        valid_methods = [(K, T, L, conf, name) for K, T, L, conf, name in methods if conf > 0]
        
        if not valid_methods:
            print("⚠️ 所有辨识方法都失败，使用默认值")
            return 0.5, 30.0, 5.0
        
        # 打印各方法结果
        print("\n各辨识方法结果:")
        for K, T, L, conf, name in valid_methods:
            print(f"  {name}: K={K:.3f}, T={T:.1f}, L={L:.1f}, 置信度={conf:.2f}")
        
        # 加权平均
        total_confidence = sum(conf for _, _, _, conf, _ in valid_methods)
        K_final = sum(K * conf for K, _, _, conf, _ in valid_methods) / total_confidence
        T_final = sum(T * conf for _, T, _, conf, _ in valid_methods) / total_confidence
        L_final = sum(L * conf for _, _, L, conf, _ in valid_methods) / total_confidence
        
        print(f"\n✅ 融合结果: K={K_final:.3f}, T={T_final:.1f}, L={L_final:.1f}")
        
        return K_final, T_final, L_final
    
    @staticmethod
    def _identify_from_setpoint_changes(t, pv, mv, sv):
        """
        方法1: 从设定值变化中辨识系统参数
        
        原理：当SV变化时，即使在闭环下，PV的响应也能反映系统特性
        """
        # 检测SV变化点
        sv_diff = np.abs(np.diff(sv))
        change_threshold = np.std(sv) * 0.5 if np.std(sv) > 0.01 else 0.5
        change_indices = np.where(sv_diff > change_threshold)[0]
        
        if len(change_indices) == 0:
            return 0, 0, 0, 0.0  # 没有SV变化
        
        # 选择最明显的变化
        largest_change_idx = change_indices[np.argmax(sv_diff[change_indices])]
        
        # 提取变化前后的数据段
        window_before = 20
        window_after = min(100, len(t) - largest_change_idx - 1)
        
        if largest_change_idx < window_before or window_after < 30:
            return 0, 0, 0, 0.0
        
        # 变化前后的稳态值
        sv_before = np.mean(sv[max(0, largest_change_idx - window_before):largest_change_idx])
        sv_after = np.mean(sv[largest_change_idx + 10:min(largest_change_idx + 30, len(sv))])
        delta_sv = sv_after - sv_before
        
        if abs(delta_sv) < 0.1:
            return 0, 0, 0, 0.0
        
        # PV响应
        pv_before = np.mean(pv[max(0, largest_change_idx - window_before):largest_change_idx])
        pv_response = pv[largest_change_idx:largest_change_idx + window_after]
        t_response = t[largest_change_idx:largest_change_idx + window_after] - t[largest_change_idx]
        
        # 估计增益（闭环下的表观增益）
        pv_final = np.mean(pv_response[-20:]) if len(pv_response) >= 20 else pv_response[-1]
        delta_pv = pv_final - pv_before
        K_apparent = delta_pv / delta_sv if abs(delta_sv) > 0.01 else 0.5
        
        # 估计时间常数：63.2%响应时间
        target_pv = pv_before + 0.632 * delta_pv
        T_est = 30.0
        for i, pv_val in enumerate(pv_response):
            if (delta_pv > 0 and pv_val >= target_pv) or (delta_pv < 0 and pv_val <= target_pv):
                T_est = t_response[i]
                break
        
        # 估计滞后：找到PV开始明显变化的时间
        pv_diff = np.abs(np.diff(pv_response))
        if len(pv_diff) > 0:
            threshold = np.mean(pv_diff) + np.std(pv_diff)
            for i, diff_val in enumerate(pv_diff):
                if diff_val > threshold:
                    L_est = t_response[i] if i < len(t_response) else 0
                    break
            else:
                L_est = 0.0
        else:
            L_est = 0.0
        
        # 置信度评估
        confidence = 0.8 if abs(delta_sv) > 1.0 else 0.5
        
        return abs(K_apparent), max(T_est, 5.0), max(L_est, 0.0), confidence
    
    @staticmethod
    def _identify_from_disturbances(t, pv, mv, sv):
        """
        方法2: 从扰动响应中辨识
        
        原理：即使在稳态运行，也会有小扰动，从扰动恢复过程可以估计参数
        """
        # 寻找扰动事件（PV偏离SV较大的时刻）
        error = pv - sv
        error_std = np.std(error)
        
        if error_std < 0.1:
            return 0, 0, 0, 0.0  # 数据太平稳
        
        # 找到误差峰值
        peaks, properties = find_peaks(np.abs(error), height=error_std * 1.5, distance=20)
        
        if len(peaks) == 0:
            return 0, 0, 0, 0.0
        
        # 选择最大的扰动
        largest_peak_idx = peaks[np.argmax(properties['peak_heights'])]
        
        # 提取扰动后的恢复过程
        recovery_window = min(80, len(t) - largest_peak_idx - 1)
        if recovery_window < 20:
            return 0, 0, 0, 0.0
        
        error_recovery = error[largest_peak_idx:largest_peak_idx + recovery_window]
        t_recovery = t[largest_peak_idx:largest_peak_idx + recovery_window] - t[largest_peak_idx]
        
        # 拟合指数衰减：e(t) = e0 * exp(-t/T)
        e0 = error_recovery[0]
        if abs(e0) < 0.1:
            return 0, 0, 0, 0.0
        
        # 估计时间常数
        try:
            # 找到误差衰减到初始值的37%的时间
            target_error = e0 * 0.37
            T_est = 30.0
            for i, e_val in enumerate(error_recovery):
                if abs(e_val) <= abs(target_error):
                    T_est = t_recovery[i]
                    break
        except:
            T_est = 30.0
        
        # 从MV变化估计增益
        mv_at_peak = mv[largest_peak_idx] if largest_peak_idx < len(mv) else mv[-1]
        mv_before = np.mean(mv[max(0, largest_peak_idx - 10):largest_peak_idx])
        delta_mv = mv_at_peak - mv_before
        
        if abs(delta_mv) > 0.1:
            K_est = abs(e0 / delta_mv)
        else:
            K_est = 0.5
        
        # 滞后估计（简化）
        L_est = 0.0
        
        confidence = 0.6
        
        return K_est, max(T_est, 5.0), L_est, confidence
    
    @staticmethod
    def _identify_from_frequency_domain(t, pv, mv, sv):
        """
        方法3: 频域辨识
        
        原理：通过功率谱密度分析系统的频率特性
        """
        if len(pv) < 100:
            return 0, 0, 0, 0.0
        
        dt = np.mean(np.diff(t)) if len(t) > 1 else 1.0
        fs = 1.0 / dt if dt > 0 else 1.0
        
        # 计算PV和MV的功率谱
        try:
            freqs_pv, psd_pv = welch(pv - np.mean(pv), fs=fs, nperseg=min(256, len(pv)//4))
            freqs_mv, psd_mv = welch(mv - np.mean(mv), fs=fs, nperseg=min(256, len(mv)//4))
            
            # 找到主频率
            if len(psd_pv) > 0 and len(psd_mv) > 0:
                # 跳过DC分量
                dominant_freq_idx = np.argmax(psd_pv[1:]) + 1
                dominant_freq = freqs_pv[dominant_freq_idx]
                
                if dominant_freq > 0:
                    # 时间常数与主频率的关系：T ≈ 1/(2πf)
                    T_est = 1.0 / (2 * np.pi * dominant_freq)
                    
                    # 增益估计：从功率谱比
                    if psd_mv[dominant_freq_idx] > 0:
                        gain_ratio = np.sqrt(psd_pv[dominant_freq_idx] / psd_mv[dominant_freq_idx])
                        K_est = np.clip(gain_ratio, 0.1, 2.0)
                    else:
                        K_est = 0.5
                    
                    L_est = 0.0
                    confidence = 0.5
                    
                    return K_est, max(T_est, 5.0), L_est, confidence
        except Exception as e:
            print(f"  频域分析失败: {e}")
        
        return 0, 0, 0, 0.0
    
    @staticmethod
    def _identify_from_closed_loop_tf(t, pv, mv, sv, current_pid_params):
        """
        方法4: 基于闭环传递函数的辨识
        
        原理：已知PID参数，从闭环响应反推开环系统参数
        闭环传递函数：Y/R = GcGp / (1 + GcGp)
        其中 Gc 是已知的PID控制器，Gp 是待辨识的系统
        """
        if current_pid_params is None:
            return 0, 0, 0, 0.0
        
        pb = current_pid_params.get('pb', 100.0)
        ti = current_pid_params.get('ti', 20.0)
        td = current_pid_params.get('td', 0.0)
        
        # 转换为标准PID参数
        Kp = 100.0 / pb if pb > 0 else 1.0
        Ki = Kp / ti if ti > 0 else 0.0
        Kd = Kp * td
        
        # 计算闭环系统的阶跃响应特征
        error = sv - pv
        
        # 寻找SV阶跃
        sv_diff = np.abs(np.diff(sv))
        if len(sv_diff) == 0 or np.max(sv_diff) < 0.1:
            return 0, 0, 0, 0.0
        
        step_idx = np.argmax(sv_diff)
        if step_idx < 10 or step_idx > len(t) - 50:
            return 0, 0, 0, 0.0
        
        # 提取闭环响应
        response_window = min(100, len(t) - step_idx - 1)
        pv_response = pv[step_idx:step_idx + response_window]
        sv_response = sv[step_idx:step_idx + response_window]
        t_response = t[step_idx:step_idx + response_window] - t[step_idx]
        
        # 闭环响应特征
        sv_step = sv_response[-1] - sv_response[0] if len(sv_response) > 0 else 1.0
        if abs(sv_step) < 0.1:
            return 0, 0, 0, 0.0
        
        pv_final = np.mean(pv_response[-10:]) if len(pv_response) >= 10 else pv_response[-1]
        pv_initial = pv_response[0]
        
        # 稳态增益（闭环）
        K_cl = (pv_final - pv_initial) / sv_step if abs(sv_step) > 0.01 else 1.0
        
        # 从闭环增益反推开环增益
        # K_cl = K_ol / (1 + K_ol * Kp)
        # 求解：K_ol = K_cl / (1 - K_cl * Kp)
        denominator = 1 - K_cl * Kp
        if abs(denominator) > 0.1:
            K_ol = K_cl / denominator
        else:
            K_ol = 0.5
        
        # 时间常数估计（从闭环上升时间）
        rise_time = 0
        target_pv = pv_initial + 0.9 * (pv_final - pv_initial)
        for i, pv_val in enumerate(pv_response):
            if pv_val >= target_pv:
                rise_time = t_response[i]
                break
        
        # 闭环时间常数与开环时间常数的关系
        # T_cl ≈ T_ol / (1 + K_ol * Kp)
        T_cl = rise_time / 2.2 if rise_time > 0 else 10.0
        T_ol = T_cl * (1 + abs(K_ol) * Kp)
        
        L_est = 0.0
        confidence = 0.7
        
        return abs(K_ol), max(T_ol, 5.0), L_est, confidence
    
    @staticmethod
    def enhance_excitation_analysis(t, pv, mv, sv):
        """
        增强激励分析：评估数据的信息量
        
        返回数据质量评分，用于判断是否需要更多数据或主动激励
        """
        quality_score = {
            'mv_variation': 0,  # MV变化程度
            'sv_changes': 0,    # SV变化次数
            'disturbances': 0,  # 扰动事件数
            'data_length': 0,   # 数据长度
            'snr': 0,           # 信噪比
            'overall': 0        # 综合评分
        }
        
        # 1. MV变化程度
        mv_std = np.std(mv)
        mv_range = np.max(mv) - np.min(mv)
        if mv_range > 5.0:
            quality_score['mv_variation'] = 1.0
        elif mv_range > 2.0:
            quality_score['mv_variation'] = 0.7
        elif mv_range > 1.0:
            quality_score['mv_variation'] = 0.4
        else:
            quality_score['mv_variation'] = 0.2
        
        # 2. SV变化次数
        sv_diff = np.abs(np.diff(sv))
        sv_changes = np.sum(sv_diff > 0.5)
        if sv_changes >= 3:
            quality_score['sv_changes'] = 1.0
        elif sv_changes >= 1:
            quality_score['sv_changes'] = 0.7
        else:
            quality_score['sv_changes'] = 0.3
        
        # 3. 扰动事件
        error = pv - sv
        error_std = np.std(error)
        if error_std > 0.1:
            peaks, _ = find_peaks(np.abs(error), height=error_std * 1.5, distance=20)
            disturbance_count = len(peaks)
            if disturbance_count >= 3:
                quality_score['disturbances'] = 1.0
            elif disturbance_count >= 1:
                quality_score['disturbances'] = 0.6
            else:
                quality_score['disturbances'] = 0.3
        else:
            quality_score['disturbances'] = 0.2
        
        # 4. 数据长度
        if len(t) >= 500:
            quality_score['data_length'] = 1.0
        elif len(t) >= 200:
            quality_score['data_length'] = 0.8
        elif len(t) >= 100:
            quality_score['data_length'] = 0.6
        else:
            quality_score['data_length'] = 0.4
        
        # 5. 信噪比
        signal_power = np.var(pv - np.mean(pv))
        noise_power = np.var(np.diff(pv))
        snr = signal_power / noise_power if noise_power > 0 else 10
        if snr > 10:
            quality_score['snr'] = 1.0
        elif snr > 5:
            quality_score['snr'] = 0.8
        elif snr > 2:
            quality_score['snr'] = 0.6
        else:
            quality_score['snr'] = 0.4
        
        # 综合评分
        quality_score['overall'] = (
            quality_score['mv_variation'] * 0.3 +
            quality_score['sv_changes'] * 0.25 +
            quality_score['disturbances'] * 0.2 +
            quality_score['data_length'] * 0.15 +
            quality_score['snr'] * 0.1
        )
        
        return quality_score
    
    @staticmethod
    def suggest_data_collection_strategy(quality_score):
        """
        根据数据质量建议数据采集策略
        """
        suggestions = []
        
        if quality_score['overall'] < 0.5:
            suggestions.append("⚠️ 数据信息量不足，建议：")
            
            if quality_score['sv_changes'] < 0.5:
                suggestions.append("  1. 在安全范围内进行小幅度设定值变化（±1-2°C）")
            
            if quality_score['mv_variation'] < 0.5:
                suggestions.append("  2. 收集更长时间的数据，捕捉自然扰动")
            
            if quality_score['data_length'] < 0.6:
                suggestions.append("  3. 延长数据采集时间至少到200个采样点")
            
            suggestions.append("  4. 或者考虑在夜间/低负荷时段进行小幅度测试")
        else:
            suggestions.append("✅ 数据质量良好，可以进行辨识")
        
        return suggestions
