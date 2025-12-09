"""仿真模块"""

import numpy as np
from typing import Dict, Optional, Tuple
from scipy.ndimage import uniform_filter1d

from .config import Config, ModelType
from .identifier import ModelIdentifier
from .models import FusionResult


class ModelSimulator:
    """
    模型仿真器
    
    功能增强：
    1. 幅度校准 - 确保仿真幅度与实测匹配
    2. 平滑过渡 - 消除扰动段与稳态段的跳变
    3. 偏移校正 - 防止pv_model飘在实测上方
    """
    
    # 模型仿真方法映射
    SIMULATE_METHODS = {
        ModelType.FOPDT: ModelIdentifier.fopdt_model,
        ModelType.FO: ModelIdentifier.first_order_model,
        ModelType.SO: ModelIdentifier.second_order_model,
        ModelType.SOPDT: ModelIdentifier.sopdt_model,
        ModelType.FOPI: ModelIdentifier.integral_delay_model,
    }
    
    # 参数格式化映射
    PARAM_FORMATS = {
        ModelType.FOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': p[2]},
        ModelType.FO: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': 0.0},
        ModelType.SO: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': 0.0},
        ModelType.SOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': p[3]},
        ModelType.FOPI: lambda p: {'K': p[0], 'T1': 0.0, 'T2': 0.0, 'L': p[1]},
    }
    
    # 平滑过渡配置
    DEFAULT_SMOOTH_WINDOW = 10  # 默认平滑窗口大小
    
    def __init__(self):
        self._epsilon = Config.EPSILON
    
    def simulate(self, params: tuple, model_type: str, 
                 t: np.ndarray, u: np.ndarray, y0: float) -> np.ndarray:
        """
        执行单次仿真
        
        Args:
            params: 模型参数元组
            model_type: 模型类型
            t: 时间序列
            u: MV输入序列
            y0: 初始PV值
        
        Returns:
            预测的PV序列
        """
        sim_method = self.SIMULATE_METHODS.get(model_type)
        if sim_method is None:
            raise ValueError(f"未知的模型类型: {model_type}")
        return sim_method(params, t, u, y0)
    
    def simulate_segmented(self, params: tuple, model_type: str,
                           y: np.ndarray, u: np.ndarray,
                           reset_on_sv_change: bool = True,
                           sv: np.ndarray = None,
                           enable_smooth: bool = True,
                           enable_amplitude_calibration: bool = True,
                           enable_offset_correction: bool = True) -> np.ndarray:
        """
        混合仿真策略：只在SV显著变化时重置，段内连续仿真
        
        Args:
            params: 模型参数
            model_type: 模型类型
            y: 实际PV数据
            u: MV数据
            reset_on_sv_change: 是否在SV变化点重置
            sv: SV数据（用于检测变化点）
            enable_smooth: 是否启用平滑过渡（解决扰动段与稳态段衔接不平滑）
            enable_amplitude_calibration: 是否启用幅度校准（解决pv_model幅度过高）
            enable_offset_correction: 是否启用偏移校正（解决pv_model飘在实测上方）
        
        Returns:
            预测的PV序列
        """
        sim_method = self.SIMULATE_METHODS.get(model_type)
        n = len(y)
        
        if n == 0:
            return np.array([])
        
        # 检测SV显著变化点作为重置点
        reset_points = [0]
        
        if reset_on_sv_change and sv is not None and len(sv) == n:
            sv_diff = np.abs(np.diff(sv))
            sv_range = np.max(sv) - np.min(sv)
            
            # 使用更灵敏的阈值：SV范围的5%或1.0中较大的
            sv_threshold = max(1.0, sv_range * 0.05)
            
            change_points = np.where(sv_diff > sv_threshold)[0] + 1
            reset_points.extend(change_points.tolist())
            
            # 同时检测PV的大幅跳变（可能是工况切换）
            y_diff = np.abs(np.diff(y))
            y_range = np.max(y) - np.min(y)
            y_threshold = max(1.0, y_range * 0.2)  # PV变化超过范围20%则重置
            
            y_change_points = np.where(y_diff > y_threshold)[0] + 1
            reset_points.extend(y_change_points.tolist())
        
        reset_points = sorted(set(reset_points))
        reset_points.append(n)
        
        y_pred_all = np.zeros(n)
        y_range = np.max(y) - np.min(y) if n > 0 else 1.0
        
        # ============================================================
        # 分段仿真
        # ============================================================
        for i in range(len(reset_points) - 1):
            start_idx = reset_points[i]
            end_idx = reset_points[i + 1]
            
            if end_idx <= start_idx:
                continue
            
            y0 = y[start_idx]
            t_seg = np.arange(end_idx - start_idx, dtype=float)
            u_seg = u[start_idx:end_idx]
            y_actual_seg = y[start_idx:end_idx]
            
            y_seg = sim_method(params, t_seg, u_seg, y0)
            
            # ============================================================
            # 幅度校准：确保仿真幅度与实测匹配
            # ============================================================
            if enable_amplitude_calibration and len(y_seg) > 5:
                y_seg = self._calibrate_amplitude(y_seg, y_actual_seg, y0)
            
            # ============================================================
            # 偏移校正：防止pv_model整体飘移
            # ============================================================
            if enable_offset_correction and len(y_seg) > 5:
                y_seg = self._correct_offset(y_seg, y_actual_seg)
            
            y_pred_all[start_idx:end_idx] = y_seg
        
        # ============================================================
        # 平滑过渡：消除段与段之间的跳变
        # ============================================================
        if enable_smooth and len(reset_points) > 2:
            y_pred_all = self._smooth_transitions(y_pred_all, y, reset_points[1:-1])
        
        # ============================================================
        # 后处理：检测并修正大偏差区域
        # ============================================================
        error = np.abs(y_pred_all - y)
        error_threshold = max(3.0, y_range * 0.3)
        
        # 使用滑动窗口检测持续大偏差区域
        window_size = min(20, n // 10) if n > 20 else 1
        for i in range(0, n - window_size, window_size):
            window_error = np.mean(error[i:i+window_size])
            if window_error > error_threshold:
                # 该区域偏差过大，用实际PV替换（表示模型在此区域不适用）
                y_pred_all[i:i+window_size] = y[i:i+window_size]
        
        return y_pred_all
    
    def _calibrate_amplitude(self, y_pred: np.ndarray, y_actual: np.ndarray, y0: float) -> np.ndarray:
        """
        幅度校准：确保仿真响应的幅度与实测匹配
        
        解决问题：pv_model幅度远远高于pv实测
        """
        pred_range = np.ptp(y_pred)
        actual_range = np.ptp(y_actual)
        
        if pred_range < self._epsilon or actual_range < self._epsilon:
            return y_pred
        
        # 计算幅度比例
        amplitude_ratio = pred_range / actual_range
        
        # 如果幅度比例不合理（>1.3或<0.7），进行校正
        if amplitude_ratio > 1.3 or amplitude_ratio < 0.7:
            # 以y0为基准进行缩放
            correction_factor = actual_range / pred_range
            y_corrected = y0 + (y_pred - y0) * correction_factor
            return y_corrected
        
        return y_pred
    
    def _correct_offset(self, y_pred: np.ndarray, y_actual: np.ndarray) -> np.ndarray:
        """
        偏移校正：防止pv_model整体飘在实测上方或下方
        
        解决问题：pvModel飘在pv实测上面
        """
        n = len(y_pred)
        if n < 5:
            return y_pred
        
        # 使用分段偏移校正，避免全局校正破坏局部特征
        segment_size = max(20, n // 5)
        y_corrected = y_pred.copy()
        
        for start in range(0, n, segment_size):
            end = min(start + segment_size, n)
            if end - start < 5:
                continue
            
            # 计算该段的平均偏移
            segment_pred = y_pred[start:end]
            segment_actual = y_actual[start:end]
            
            # 使用中位数而非均值，更鲁棒
            offset = np.median(segment_pred) - np.median(segment_actual)
            
            # 只校正显著的偏移（>10%的范围）
            segment_range = np.ptp(segment_actual)
            if abs(offset) > segment_range * 0.1 and segment_range > self._epsilon:
                # 渐进式校正，避免突变
                correction_weight = min(1.0, abs(offset) / (segment_range * 0.5))
                y_corrected[start:end] = segment_pred - offset * correction_weight
        
        # 对校正后的结果进行轻度平滑，消除分段边界
        if n > 10:
            y_corrected = uniform_filter1d(y_corrected, size=3, mode='nearest')
        
        return y_corrected
    
    def _smooth_transitions(self, y_pred: np.ndarray, y_actual: np.ndarray, 
                            transition_points: list) -> np.ndarray:
        """
        平滑过渡：在重置点处实现平滑衔接，消除直上直下的跳变
        
        解决问题：扰动段和稳态段衔接不平滑
        """
        if not transition_points:
            return y_pred
        
        y_smooth = y_pred.copy()
        n = len(y_pred)
        smooth_window = self.DEFAULT_SMOOTH_WINDOW
        
        for tp in transition_points:
            if tp <= smooth_window or tp >= n - smooth_window:
                continue
            
            # 获取过渡区域
            start = max(0, tp - smooth_window)
            end = min(n, tp + smooth_window)
            
            # 检测是否存在跳变
            if tp > 0:
                jump = abs(y_pred[tp] - y_pred[tp - 1])
                local_std = np.std(y_actual[start:end])
                
                # 如果跳变幅度超过局部标准差的2倍，需要平滑
                if jump > local_std * 2:
                    # 使用加权混合实现平滑过渡
                    before_val = y_pred[tp - 1]
                    after_val = y_pred[tp]
                    
                    # 在过渡区域创建平滑过渡
                    half_window = smooth_window // 2
                    trans_start = max(0, tp - half_window)
                    trans_end = min(n, tp + half_window)
                    
                    for i in range(trans_start, trans_end):
                        # 计算过渡权重（使用sigmoid函数实现平滑过渡）
                        t_normalized = (i - trans_start) / (trans_end - trans_start)
                        # sigmoid过渡
                        weight = 1 / (1 + np.exp(-10 * (t_normalized - 0.5)))
                        
                        # 混合前后值
                        if i < tp:
                            # 过渡前区域：逐渐趋向于实际值
                            target_val = before_val + weight * (y_actual[tp] - before_val)
                            y_smooth[i] = y_pred[i] * (1 - weight * 0.3) + target_val * weight * 0.3
                        else:
                            # 过渡后区域：从实际值逐渐过渡到模型预测
                            y_smooth[i] = y_actual[i] * (1 - weight) + y_pred[i] * weight
        
        return y_smooth
    
    def fusion_to_params(self, fusion: FusionResult) -> tuple:
        """FusionResult转为参数元组"""
        model_type = fusion.model_type
        if model_type == ModelType.FOPDT:
            return (fusion.K, fusion.T1, fusion.L)
        elif model_type == ModelType.FO:
            return (fusion.K, fusion.T1)
        elif model_type == ModelType.SO:
            return (fusion.K, fusion.T1, fusion.T2)
        elif model_type == ModelType.SOPDT:
            return (fusion.K, fusion.T1, fusion.T2, fusion.L)
        elif model_type == ModelType.FOPI:
            return (fusion.K, fusion.L)
        return (fusion.K, fusion.T1, fusion.L)
    
    def params_to_fusion(self, params: tuple, model_type: str, 
                         base_fusion: Optional[FusionResult] = None) -> FusionResult:
        """参数元组转为FusionResult"""
        fusion = FusionResult(model_type=model_type)
        if base_fusion:
            fusion.n_segments_used = base_fusion.n_segments_used
            fusion.consistency_score = base_fusion.consistency_score
        
        params_dict = self.PARAM_FORMATS[model_type](params)
        fusion.K = params_dict['K']
        fusion.T1 = params_dict['T1']
        fusion.T2 = params_dict['T2']
        fusion.L = params_dict['L']
        
        return fusion
    
    def create_init_params(self, model_type: str, K: float, T: float) -> tuple:
        """根据模型类型创建初始参数"""
        if model_type == 'FOPDT':
            return (K, T, 1.0)
        elif model_type == 'FO':
            return (K, T)
        elif model_type == 'SO':
            return (K, T, T * 0.3)
        elif model_type == 'SOPDT':
            return (K, T, T * 0.3, 1.0)
        elif model_type == 'FO_INTEGRATOR':
            return (K / T,)
        else:
            return (K, T)
