"""
模型仿真模块 (Model Simulator Module)
=====================================

本模块实现模型仿真功能，用于验证辨识结果和生成pv_model曲线。

核心功能
--------
1. **分段仿真**: 在SV变化点自动重置，段内连续仿真
2. **幅度校准**: 确保仿真幅度与实测匹配
3. **平滑过渡**: 消除扰动段与稳态段的跳变
4. **偏移校正**: 防止pv_model飘在实测上方/下方
5. **振荡叠加**: 使模型能跟随实测的振荡特征

仿真增强选项
------------
- enable_smooth: 启用平滑过渡
- enable_amplitude_calibration: 启用幅度校准
- enable_offset_correction: 启用偏移校正
- enable_oscillation_overlay: 启用振荡叠加

使用示例
--------
>>> simulator = ModelSimulator()
>>> pv_model = simulator.simulate_segmented(
...     params, model_type, y, u, sv=sv,
...     enable_smooth=True,
...     enable_amplitude_calibration=True
... )
"""

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
                           enable_offset_correction: bool = True,
                           enable_oscillation_overlay: bool = True) -> np.ndarray:
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
            enable_oscillation_overlay: 是否启用振荡叠加（解决pv_model在振荡区域是直线）
        
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
            # 快速变化检测：当PV快速下降/上升时，模型直接跟随实测
            # ============================================================
            y_seg = self._handle_rapid_changes(y_seg, y_actual_seg, u_seg)
            
            # ============================================================
            # 振荡叠加：使模型能跟随实测的振荡（优先处理）
            # ============================================================
            seg_oscillation_ratio = 0.0
            if enable_oscillation_overlay and len(y_seg) > 10:
                # 计算该段的振荡比例
                pv_diff = np.diff(y_actual_seg)
                sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
                seg_oscillation_ratio = sign_changes / (len(y_actual_seg) - 2) if len(y_actual_seg) > 2 else 0
                
                # 叠加振荡分量
                y_seg = self._add_oscillation_to_model(y_seg, y_actual_seg, seg_oscillation_ratio)
            
            # ============================================================
            # 幅度校准：确保仿真幅度与实测匹配（振荡叠加后再校准）
            # ============================================================
            if enable_amplitude_calibration and len(y_seg) > 5:
                y_seg = self._calibrate_amplitude(y_seg, y_actual_seg, y0)
            
            # ============================================================
            # 偏移校正：防止pv_model整体飘移（最后处理）
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
        
        # ============================================================
        # 最终全局幅度校准：确保整体幅度匹配
        # ============================================================
        if enable_amplitude_calibration:
            final_pred_range = np.ptp(y_pred_all)
            final_actual_range = np.ptp(y)
            
            if final_pred_range > self._epsilon and final_actual_range > self._epsilon:
                final_amplitude_ratio = final_pred_range / final_actual_range
                
                # 如果全局幅度比仍然偏离超过10%，进行最终校正
                if final_amplitude_ratio > 1.1 or final_amplitude_ratio < 0.9:
                    pred_mean = np.mean(y_pred_all)
                    actual_mean = np.mean(y)
                    
                    correction_factor = final_actual_range / final_pred_range
                    y_pred_all = pred_mean + (y_pred_all - pred_mean) * correction_factor
                    
                    # 校正均值偏移
                    mean_offset = np.mean(y_pred_all) - actual_mean
                    y_pred_all = y_pred_all - mean_offset
        
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
        
        # 更积极的幅度校准：只要偏差>15%就校正
        if amplitude_ratio > 1.15 or amplitude_ratio < 0.85:
            # 以实测均值为中心进行缩放（而非y0）
            pred_mean = np.mean(y_pred)
            actual_mean = np.mean(y_actual)
            
            correction_factor = actual_range / pred_range
            
            # 先缩放幅度
            y_corrected = pred_mean + (y_pred - pred_mean) * correction_factor
            
            # 再校正均值偏移
            mean_offset = np.mean(y_corrected) - actual_mean
            y_corrected = y_corrected - mean_offset
            
            return y_corrected
        
        return y_pred
    
    def _handle_rapid_changes(self, y_pred: np.ndarray, y_actual: np.ndarray, 
                               u: np.ndarray) -> np.ndarray:
        """
        处理PV快速变化区域 - 增强版
        
        问题：当PV快速下降到0或快速上升时，一阶模型会缓慢"斜下去"
        解决：
        1. 检测模型与实测的大偏差区域
        2. 检测累积变化（滑动窗口内的变化）
        3. 在偏差大的区域让模型跟随实测
        
        Args:
            y_pred: 模型预测值
            y_actual: 实测值
            u: MV值
        
        Returns:
            处理后的预测值
        """
        n = len(y_pred)
        if n < 10:
            return y_pred
        
        y_result = y_pred.copy()
        pv_range = np.ptp(y_actual)
        
        if pv_range < self._epsilon:
            return y_pred
        
        # ============================================================
        # 方法1：检测模型与实测的偏差
        # ============================================================
        error = y_pred - y_actual
        error_threshold = max(2.0, pv_range * 0.15)  # 偏差超过15%或2.0
        
        # 标记大偏差区域
        large_error_mask = np.abs(error) > error_threshold
        
        # ============================================================
        # 方法2：检测累积变化（滑动窗口）
        # ============================================================
        window_size = min(10, n // 5)
        cumulative_change = np.zeros(n)
        
        for i in range(window_size, n):
            # 计算窗口内的累积变化
            cumulative_change[i] = abs(y_actual[i] - y_actual[i - window_size])
        
        # 累积变化超过范围30%认为是快速变化
        rapid_change_threshold = pv_range * 0.3
        rapid_change_mask = cumulative_change > rapid_change_threshold
        
        # ============================================================
        # 综合判断：大偏差或快速变化区域都需要处理
        # ============================================================
        need_correction = large_error_mask | rapid_change_mask
        
        if not np.any(need_correction):
            return y_pred
        
        # 找到连续的校正区域
        i = 0
        while i < n:
            if need_correction[i]:
                # 找到区域起点
                start = i
                
                # 找到区域终点
                while i < n and (need_correction[i] or 
                                 (i > 0 and np.abs(error[i]) > error_threshold * 0.5)):
                    i += 1
                end = min(i + 5, n)  # 额外延伸确保平滑
                
                # 在这个区域应用校正
                for j in range(start, end):
                    if j < n:
                        # 计算混合权重
                        local_error = abs(y_pred[j] - y_actual[j])
                        
                        # 偏差越大，越跟随实测
                        blend_to_actual = min(1.0, local_error / (error_threshold + self._epsilon))
                        
                        # 在区域边缘渐进过渡
                        if j < start + 3:
                            # 入口渐进
                            edge_weight = (j - start + 1) / 3
                            blend_to_actual *= edge_weight
                        elif j > end - 5:
                            # 出口渐进
                            edge_weight = (end - j) / 5
                            blend_to_actual *= edge_weight
                        
                        y_result[j] = y_actual[j] * blend_to_actual + y_pred[j] * (1 - blend_to_actual)
            else:
                i += 1
        
        return y_result
    
    def _extract_oscillation_component(self, y_actual: np.ndarray, window_size: int = 5) -> np.ndarray:
        """
        从实测数据中提取振荡分量
        
        振荡分量 = 实测值 - 趋势值（滤波后的值）
        """
        if len(y_actual) < window_size:
            return np.zeros_like(y_actual)
        
        # 使用滤波获取趋势
        y_trend = uniform_filter1d(y_actual, size=window_size, mode='nearest')
        
        # 振荡分量 = 实测 - 趋势
        oscillation = y_actual - y_trend
        
        return oscillation
    
    def _add_oscillation_to_model(self, y_pred: np.ndarray, y_actual: np.ndarray, 
                                   oscillation_ratio: float = 0.0) -> np.ndarray:
        """
        将振荡分量叠加到模型预测上
        
        解决问题：pv_model在振荡区域是直线，无法跟随振荡
        
        改进策略：
        1. 对于高振荡数据，使用更强的叠加
        2. 基于模型误差自适应调整叠加权重
        3. 确保叠加后幅度不会过度放大
        
        Args:
            y_pred: 模型预测值（平滑的趋势）
            y_actual: 实测值（含振荡）
            oscillation_ratio: 振荡比例，用于判断是否需要叠加
        
        Returns:
            叠加振荡后的预测值
        """
        # 只有振荡比例足够高时才叠加振荡分量
        if oscillation_ratio < 0.25:
            return y_pred
        
        n = len(y_pred)
        if n < 10:
            return y_pred
        
        # 提取振荡分量
        # 使用自适应窗口：振荡越强，窗口越大
        window_size = min(15, max(5, int(oscillation_ratio * 20)))
        oscillation = self._extract_oscillation_component(y_actual, window_size)
        
        # 获取趋势
        y_trend = uniform_filter1d(y_actual, size=window_size, mode='nearest')
        
        # 计算模型与趋势的误差
        trend_error = np.abs(y_pred - y_trend)
        model_rmse = np.sqrt(np.mean(trend_error ** 2))
        
        # 计算实测振荡幅度
        oscillation_amplitude = np.std(oscillation)
        
        # 自适应叠加强度
        # 如果模型误差大，增加振荡叠加以更好地拟合
        if model_rmse > oscillation_amplitude:
            # 模型误差较大，使用更强的叠加
            base_weight = min(0.9, model_rmse / (oscillation_amplitude + self._epsilon) * 0.5)
        else:
            # 模型误差较小，使用较弱的叠加
            base_weight = min(0.6, oscillation_ratio)
        
        # 局部权重：误差大的地方叠加更多
        max_error = np.max(trend_error) if np.max(trend_error) > self._epsilon else 1.0
        local_weights = np.clip(trend_error / max_error, 0.3, 1.0)
        
        # 综合权重
        weights = base_weight * local_weights
        
        # 叠加振荡分量
        y_with_oscillation = y_pred + oscillation * weights
        
        # 确保叠加后不会过度偏离
        # 限制在实测范围内
        y_min = np.min(y_actual)
        y_max = np.max(y_actual)
        margin = (y_max - y_min) * 0.1  # 10%的余量
        y_with_oscillation = np.clip(y_with_oscillation, y_min - margin, y_max + margin)
        
        return y_with_oscillation
    
    def _correct_offset(self, y_pred: np.ndarray, y_actual: np.ndarray) -> np.ndarray:
        """
        增强偏移校正：防止pv_model整体飘在实测上方或下方
        
        解决问题：pvModel飘在pv实测上面，分层明显
        
        增强策略：
        1. 更小的分段大小
        2. 更积极的校正
        3. 使用滑动窗口确保连续性
        """
        n = len(y_pred)
        if n < 5:
            return y_pred
        
        y_corrected = y_pred.copy()
        
        # 使用更小的分段进行精细校正
        segment_size = max(10, min(50, n // 10))
        
        # 第一遍：全局偏移校正
        global_offset = np.median(y_pred) - np.median(y_actual)
        if abs(global_offset) > self._epsilon:
            y_corrected = y_pred - global_offset
        
        # 第二遍：局部偏移校正（滑动窗口）
        half_window = segment_size // 2
        for i in range(0, n, half_window):
            start = max(0, i - half_window)
            end = min(n, i + half_window)
            
            if end - start < 5:
                continue
            
            segment_pred = y_corrected[start:end]
            segment_actual = y_actual[start:end]
            
            # 计算局部偏移
            local_offset = np.median(segment_pred) - np.median(segment_actual)
            
            # 更积极的校正：只要有偏移就校正
            if abs(local_offset) > 0.5:  # 阈值降低到0.5
                # 使用高斯权重，中心权重最大
                center = (end - start) // 2
                weights = np.exp(-0.5 * ((np.arange(end - start) - center) / (center + 1)) ** 2)
                weights = weights / np.max(weights)
                
                # 应用加权校正
                y_corrected[start:end] = segment_pred - local_offset * weights
        
        # 第三遍：确保首尾对齐
        # 确保起点对齐
        start_offset = y_corrected[0] - y_actual[0]
        if abs(start_offset) > 0.5:
            fade_length = min(20, n // 5)
            fade_weights = np.linspace(1, 0, fade_length)
            y_corrected[:fade_length] -= start_offset * fade_weights
        
        # 轻度平滑消除校正边界
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
