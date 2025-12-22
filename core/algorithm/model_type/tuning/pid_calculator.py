"""
PID参数计算模块 (PID Calculator Module)
=======================================

本模块基于辨识的模型参数计算最优PID整定参数。

核心功能
--------
1. **多种整定方法**: Lambda/IMC法、Cohen-Coon法、Ziegler-Nichols临界法
2. **自适应保守调整**: 根据数据质量自动调整保守程度
3. **振荡分析整定**: 对高振荡数据使用临界法整定
4. **闭环稳定性验证**: 仿真验证PID参数的闭环性能

整定方法说明
------------
- **lambda**: Lambda/IMC法，适用于所有模型，平衡响应速度和稳定性
- **cohen_coon**: Cohen-Coon法，适用于FOPDT，当L/T较大时使用
- **imc_aggressive**: IMC激进模式，响应更快但可能振荡

闭环性能指标
------------
- settling_time: 调节时间 (进入±2%误差带)
- overshoot: 超调量 (%)
- rise_time: 上升时间 (10%到90%)
- steady_state_error: 稳态误差
- oscillation_count: 振荡次数
- decay_ratio: 衰减比
"""

import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

from ..config import Config, ModelType
from ..data_models import FusionResult


@dataclass
class ClosedLoopMetrics:
    """闭环价统性能指标"""
    is_stable: bool              # 是否稳定
    settling_time: float         # 调节时间（进入±2%误差带）
    overshoot: float             # 超调量 (%)
    rise_time: float             # 上升时间（10%到90%）
    steady_state_error: float    # 稳态误差
    oscillation_count: int       # 振荡次数
    decay_ratio: float           # 衰减比
    pv_history: np.ndarray       # PV响应历史
    mv_history: np.ndarray       # MV输出历史


@dataclass
class DataQualityInfo:
    """数据质量信息，用于自适应保守调整"""
    quality_score: float = 0.5      # 质量评分 (0~1)
    oscillation_ratio: float = 0.0  # 振荡比 (0~1)
    r_squared: float = 0.5          # 拟合R² (0~1)
    is_noisy: bool = False          # 是否高噪声
    consistency_score: float = 0.5  # 参数一致性 (0~1)


EPSILON = Config.EPSILON


class PIDCalculator:
    """PID参数计算器"""
    
    def __init__(self):
        self._epsilon = EPSILON
    
    def calculate(self, K: float, T1: float, T2: float, L: float,
                  model_type: str, lambda_factor: float,
                  method: str = 'lambda',
                  quality_info: Optional[DataQualityInfo] = None,
                  response_mode: str = 'balanced') -> Dict[str, float]:
        """
        根据模型类型和整定方法计算PID参数
        
        Args:
            K: 增益（可为负，表示反向作用系统）
            T1: 时间常数1
            T2: 时间常数2（二阶模型）
            L: 滞后时间
            model_type: 模型类型 (FOPDT, FO, SOPDT, SO, FOPI)
            lambda_factor: Lambda/IMC 整定系数（闭环时间常数 = T1 * lambda_factor）
            method: 整定方法
                - 'lambda': Lambda/IMC 法（默认，适用于所有模型）
                - 'cohen_coon': Cohen-Coon 法（仅 FOPDT）
                - 'imc_aggressive': IMC 激进模式（更快响应）
            quality_info: 数据质量信息，用于自适应保守调整
            response_mode: 响应模式
                - 'fast': 快速响应（允许10-20%超调，调节时间短）
                - 'balanced': 平衡模式（默认，小超调，较快响应）
                - 'conservative': 保守模式（无超调，响应较慢）
        
        Returns:
            PID参数字典 {Kp, Ki, Kd}，Kp符号与K一致
        """
        # 保留K的符号信息（反向作用系统K为负）
        K_sign = 1 if K >= 0 else -1
        K_abs = max(abs(K), self._epsilon)
        
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T2 = max(T2, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        
        # 计算自适应保守等级（考虑响应模式）
        conservative_level, pb_min = self._calculate_conservative_level(quality_info, response_mode)
        
        # 根据模型类型和方法选择整定公式
        if model_type == ModelType.FO:
            # ========== 一阶无滞后 (FO) ==========
            Kp, Ti, Td = self._tune_fo(K_abs, T1, lambda_factor, method,
                                        conservative_level, pb_min)
            
        elif model_type == ModelType.FOPDT:
            # ========== 一阶加纯滞后 (FOPDT) ==========
            Kp, Ti, Td = self._tune_fopdt(K_abs, T1, L, lambda_factor, method,
                                           conservative_level, pb_min)
            
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            # ========== 二阶系统 (SO/SOPDT) ==========
            Kp, Ti, Td = self._tune_sopdt(K_abs, T1, T2, L, lambda_factor,
                                           conservative_level, pb_min)
            
        elif model_type == ModelType.FOPI:
            # ========== 积分过程 (FOPI) ==========
            Kp, Ti, Td = self._tune_integrator(K_abs, T1, lambda_factor,
                                                conservative_level, pb_min)
        
        elif model_type in [ModelType.HAMMERSTEIN, ModelType.DEADBAND_FOPDT, ModelType.SATURATION_FOPDT]:
            # ========== 非线性模型 ==========
            # 使用等效线性化参数，按FOPDT整定，并增加保守度
            Kp, Ti, Td = self._tune_nonlinear(K_abs, T1, L, lambda_factor, method,
                                               conservative_level, pb_min, model_type)
            
        else:
            # 默认保守参数
            Kp, Ti, Td = 1.0, 20.0, 0.0
        
        # 应用K的符号到Kp（反向作用系统Kp为负）
        Kp = Kp * K_sign
        
        # 参数合理性约束
        Kp, Ti, Td = self._apply_constraints(Kp, Ti, Td, K_sign)
        
        # 转换为 Ki, Kd
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        return {
            'Kp': round(float(Kp), 2),
            'Ki': round(float(Ki), 2),
            'Kd': round(float(Kd), 2)
        }
    
    def _calculate_conservative_level(self, quality_info: Optional[DataQualityInfo],
                                       response_mode: str = 'balanced') -> Tuple[float, float]:
        """
        根据数据质量和响应模式计算自适应保守等级
        
        Args:
            quality_info: 数据质量信息
            response_mode: 响应模式
                - 'fast': 快速响应（允许10-20%超调）
                - 'balanced': 平衡模式（默认）
                - 'conservative': 保守模式（无超调）
        
        Returns:
            (conservative_level, pb_min)
            - conservative_level: 保守因子，越大越保守
            - pb_min: pb最小值
        """
        # 响应模式基准参数
        # fast: 更小的保守因子，更低的pb_min，响应更快但可能有超调
        # balanced: 适中参数
        # conservative: 更大的保守因子，响应慢但稳定
        MODE_PARAMS = {
            'fast': {
                'level_range': (0.8, 1.8),    # 保守因子范围
                'pb_range': (8, 30),          # pb_min范围
                'default_level': 1.2,
                'default_pb': 20,
                'r2_multipliers': {0.95: 0.3, 0.9: 0.4, 0.85: 0.5, 0.8: 0.7}
            },
            'balanced': {
                'level_range': (1.2, 2.5),
                'pb_range': (15, 45),
                'default_level': 1.8,
                'default_pb': 30,
                'r2_multipliers': {0.95: 0.4, 0.9: 0.55, 0.85: 0.7, 0.8: 0.85}
            },
            'conservative': {
                'level_range': (2.0, 4.0),
                'pb_range': (30, 70),
                'default_level': 2.5,
                'default_pb': 45,
                'r2_multipliers': {0.95: 0.6, 0.9: 0.7, 0.85: 0.8, 0.8: 0.9}
            }
        }
        
        params = MODE_PARAMS.get(response_mode, MODE_PARAMS['balanced'])
        level_min, level_max = params['level_range']
        pb_min_range, pb_max_range = params['pb_range']
        
        if quality_info is None:
            return params['default_level'], params['default_pb']
        
        # 计算综合质量得分
        q_score = quality_info.quality_score
        osc_ratio = quality_info.oscillation_ratio
        r2 = quality_info.r_squared
        consistency = quality_info.consistency_score
        
        # 质量因子：越差越保守（降低权重）
        quality_factor = 1.0 - q_score  # 0~1
        
        # 振荡因子：振荡越大越保守（大幅降低权重）
        osc_factor = osc_ratio * 0.5  # 进一步降低振荡的惩罚
        
        # 拟合因子：R²越低越保守
        r2_factor = max(0, 1.0 - r2)  # 0~1
        
        # 一致性因子：一致性越低越保守
        if r2 > 0.85:
            consist_factor = max(0, 1.0 - consistency) * 0.3
        elif r2 > 0.7:
            consist_factor = max(0, 1.0 - consistency) * 0.6
        else:
            consist_factor = max(0, 1.0 - consistency)
        
        # 综合保守度：加权平均
        conservativeness = (
            0.20 * quality_factor +
            0.15 * osc_factor +
            0.45 * r2_factor +
            0.20 * consist_factor
        )
        
        # 根据R²和响应模式调整保守度
        r2_multipliers = params['r2_multipliers']
        if r2 > 0.95:
            conservativeness *= r2_multipliers[0.95]
        elif r2 > 0.9:
            conservativeness *= r2_multipliers[0.9]
        elif r2 > 0.85:
            conservativeness *= r2_multipliers[0.85]
        elif r2 > 0.8:
            conservativeness *= r2_multipliers[0.8]
        
        # 阀门补偿：高振荡+低R²时自动增加保守度（可能存在阀门死区/黏连）
        valve_compensation = 1.0
        if osc_ratio > 0.5 and r2 < 0.85:
            # 典型阀门问题特征：高振荡但模型拟合差
            valve_compensation = 1.3 + (osc_ratio - 0.5) * 0.6  # 1.3~1.6倍补偿
        elif osc_ratio > 0.6:
            # 高振荡本身就需要更保守
            valve_compensation = 1.2 + (osc_ratio - 0.6) * 0.5  # 1.2~1.4倍补偿
        
        # 映射到保守等级和pb_min（应用阀门补偿）
        conservative_level = level_min + conservativeness * (level_max - level_min) * valve_compensation
        pb_min = pb_min_range + conservativeness * (pb_max_range - pb_min_range) * valve_compensation
        
        # 限制在合理范围内
        conservative_level = min(conservative_level, level_max * 1.5)
        pb_min = min(pb_min, pb_max_range * 1.5)
        
        return conservative_level, pb_min
    
    def _tune_fo(self, K: float, T1: float, lambda_factor: float, 
                 method: str, conservative_level: float = 4.0,
                 pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        一阶无滞后系统整定（自适应保守）
        
        Args:
            conservative_level: 保守因子 (3.0~8.0)
            pb_min: pb最小值 (50~100)
        """
        # 使用自适应保守因子
        lambda_val = T1 * lambda_factor * conservative_level
        
        denom = K * lambda_val
        if denom < self._epsilon:
            return 1.0, T1, 0.0
        
        Kp = T1 / denom
        
        # 根据pb_min计算max_Kp: pb = 100/Kp -> Kp = 100/pb
        max_Kp = 100.0 / pb_min
        if Kp > max_Kp:
            Kp = max_Kp
        
        Ti = T1
        Td = 0.0  # 无滞后时不需要微分
        
        return Kp, Ti, Td
    
    def _tune_fopdt(self, K: float, T1: float, L: float, 
                    lambda_factor: float, method: str,
                    conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """一阶加纯滞后系统整定（自适应保守）"""
        
        if method == 'cohen_coon' and L > self._epsilon:
            # Cohen-Coon 法（适合 L/T1 较大的系统）
            tau = L / T1
            Kp = (1.35 / K) * (T1 / L + 0.185)
            Ti = 2.5 * L * (T1 + 0.185 * L) / (T1 + 0.611 * L)
            Td = 0.37 * L * T1 / (T1 + 0.185 * L)
            
        elif method == 'imc_aggressive':
            # IMC 激进模式（lambda = L）
            lambda_val = max(L, T1 * 0.1)
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                return 1.0, T1, 0.0
            Kp = (T1 + L / 2) / denom
            Ti = T1 + L / 2
            Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
            
        else:
            # Lambda/IMC 标准法（使用自适应保守因子）
            lambda_val = T1 * lambda_factor * (conservative_level / 4.0)  # 标准化到基准
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                return 1.0, T1 + L / 2, 0.0
            Kp = (T1 + L / 2) / denom
            Ti = T1 + L / 2
            Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        # 应用pb下限
        max_Kp = 100.0 / pb_min
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_sopdt(self, K: float, T1: float, T2: float, L: float,
                    lambda_factor: float, conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """二阶系统整定（自适应保守）"""
        T_eq = T1 + T2 if T2 > 0 else T1
        # 使用自适应保守因子
        lambda_val = T_eq * lambda_factor * (conservative_level / 4.0)
        
        denom = K * (lambda_val + L / 2) if L > 0 else K * lambda_val
        if denom < self._epsilon:
            return 1.0, T_eq, 0.0
        
        Kp = T_eq / denom
        Ti = T_eq
        # 二阶系统的微分时间：串联时间常数的几何平均
        Td = (T1 * T2) / T_eq if T_eq > self._epsilon and T2 > 0 else 0.0
        
        # 应用pb下限
        max_Kp = 100.0 / pb_min
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_integrator(self, K: float, T1: float, 
                         lambda_factor: float, conservative_level: float = 4.0,
                         pb_min: float = 60.0) -> Tuple[float, float, float]:
        """积分过程整定（自适应保守）"""
        # 积分过程: G(s) = K / (T1*s + 1) / s
        # 使用 SIMC 规则
        if K < self._epsilon:
            return 1.0, 20.0, 0.0
        
        # 使用自适应保守因子
        lambda_val = max(T1 * lambda_factor * (conservative_level / 4.0), 0.2)
        
        # SIMC 积分过程公式
        Kp = T1 / (K * lambda_val) if T1 > 0 else 1.0 / (K * lambda_val)
        Ti = 4 * lambda_val  # 积分时间 = 4 * 闭环时间常数
        Td = 0.0  # 积分过程一般不用微分
        
        # 应用pb下限
        max_Kp = 100.0 / pb_min
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_nonlinear(self, K: float, T1: float, L: float,
                        lambda_factor: float, method: str,
                        conservative_level: float, pb_min: float,
                        model_type: str) -> Tuple[float, float, float]:
        """
        非线性模型整定（使用等效线性化参数）
        
        非线性模型使用等效线性化后的FOPDT参数整定，
        但增加额外的保守度以补偿非线性带来的不确定性。
        
        Args:
            K: 等效线性增益
            T1: 等效时间常数
            L: 等效滞后时间
            lambda_factor: Lambda系数
            method: 整定方法
            conservative_level: 基础保守等级
            pb_min: 基础pb最小值
            model_type: 非线性模型类型
        """
        # 非线性模型需要额外的保守度
        nonlinear_factor = 1.3  # 基础非线性补偿因子
        
        if model_type == ModelType.HAMMERSTEIN:
            # Hammerstein模型：增益随工作点变化
            nonlinear_factor = 1.4
        elif model_type == ModelType.DEADBAND_FOPDT:
            # 死区模型：小信号时控制效果差
            nonlinear_factor = 1.5
        elif model_type == ModelType.SATURATION_FOPDT:
            # 饱和模型：大信号时增益下降
            nonlinear_factor = 1.3
        
        # 应用非线性补偿到保守等级
        adjusted_conservative = conservative_level * nonlinear_factor
        adjusted_pb_min = pb_min * nonlinear_factor
        
        # 使用FOPDT整定公式
        Kp, Ti, Td = self._tune_fopdt(K, T1, L, lambda_factor, method,
                                       adjusted_conservative, adjusted_pb_min)
        
        # 非线性模型一般不使用微分（避免放大噪声）
        Td = Td * 0.5
        
        return Kp, Ti, Td
    
    def _apply_constraints(self, Kp: float, Ti: float, Td: float,
                           K_sign: int) -> Tuple[float, float, float]:
        """应用参数合理性约束"""
        # 1. 限制Kp的绝对值下限
        if abs(Kp) < 0.01:
            Kp = 0.01 * K_sign
        
        # 2. 限制Ti的范围
        Ti_max = 120.0  # 最大积分时间 120 秒
        Ti = max(0.1, min(Ti, Ti_max))
        
        # 3. 限制Td的范围（不超过 Ti/4）
        Td = max(0.0, min(Td, Ti / 4))
        
        return Kp, Ti, Td
    
    def calculate_from_fusion(self, fusion: FusionResult, 
                               lambda_factor: float,
                               quality_info: Optional[DataQualityInfo] = None,
                               response_mode: str = 'balanced') -> Dict[str, float]:
        """
        从FusionResult计算PID参数
        
        Args:
            fusion: 融合结果
            lambda_factor: Lambda系数
            quality_info: 数据质量信息，用于自适应保守调整
            response_mode: 响应模式 ('fast', 'balanced', 'conservative')
        """
        return self.calculate(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor,
            quality_info=quality_info,
            response_mode=response_mode
        )
    
    def analyze_oscillation(self, pv: np.ndarray, mv: np.ndarray, 
                            dt: float = 1.0) -> Optional[Dict]:
        """
        分析振荡数据，提取临界振荡特征
        
        使用多种方法综合检测，提高精度：
        1. 峰值检测法 + 插值精化
        2. FFT 法检测主频
        3. 自相关法验证
        
        Args:
            pv: 过程变量数组
            mv: 操作变量数组
            dt: 采样周期（秒）
        
        Returns:
            振荡特征字典，如果无法分析则返回 None
        """
        if len(pv) < 20:
            return None
        
        # 去趋势（使用线性去趋势更好）
        x = np.arange(len(pv))
        coeffs = np.polyfit(x, pv, 1)
        trend = np.polyval(coeffs, x)
        pv_detrend = pv - trend
        
        # ========== 方法1: 精确峰值检测法 ==========
        Pu_peaks = self._detect_period_from_peaks(pv_detrend, dt)
        
        # ========== 方法2: FFT 法 ==========
        Pu_fft = self._detect_period_from_fft(pv_detrend, dt)
        
        # ========== 方法3: 自相关法 ==========
        Pu_autocorr = self._detect_period_from_autocorr(pv_detrend, dt)
        
        # 综合多种方法的结果（使用配置的周期范围）
        osc_config = Config.OSCILLATION_TUNING
        MIN_PERIOD = osc_config['period_min']
        MAX_PERIOD = osc_config['period_max']
        
        valid_periods = []
        weights = []
        
        if Pu_peaks is not None and MIN_PERIOD < Pu_peaks < MAX_PERIOD:
            valid_periods.append(Pu_peaks)
            weights.append(2.0)  # 峰值法权重更高（更可靠）
        
        if Pu_fft is not None and MIN_PERIOD < Pu_fft < MAX_PERIOD:
            valid_periods.append(Pu_fft)
            weights.append(1.0)
        
        if Pu_autocorr is not None and MIN_PERIOD < Pu_autocorr < MAX_PERIOD:
            valid_periods.append(Pu_autocorr)
            weights.append(1.5)
        
        if not valid_periods:
            return None
        
        # 如果多种方法结果差异太大，使用中位数而不是加权平均
        if len(valid_periods) >= 2:
            period_range = max(valid_periods) / min(valid_periods)
            if period_range > 2.0:
                # 结果差异太大，使用中位数
                Pu = float(np.median(valid_periods))
            else:
                Pu = np.average(valid_periods, weights=weights)
        else:
            Pu = valid_periods[0]
        
        # ========== 计算振荡幅度和衰减比 ==========
        peak_indices, peak_values, valley_indices, valley_values = self._find_peaks_valleys(pv_detrend)
        
        if len(peak_values) < 2 or len(valley_values) < 2:
            return None
        
        amplitude = (np.mean(peak_values) - np.mean(valley_values)) / 2
        
        # 计算衰减比
        if len(peak_values) >= 3:
            # 使用去趋势后的峰值计算衰减比
            peak_amplitudes = np.abs(peak_values - np.mean(pv_detrend))
            decay_ratios = []
            for i in range(len(peak_amplitudes) - 1):
                if peak_amplitudes[i] > self._epsilon:
                    decay_ratios.append(peak_amplitudes[i + 1] / peak_amplitudes[i])
            avg_decay = np.median(decay_ratios) if decay_ratios else 1.0
        else:
            avg_decay = 1.0
        
        # 检查MV是否也在振荡（而不是阶跃）
        # 如果MV是阶跃后的小幅波动，不应该用全范围计算
        mv_diff = np.diff(mv)
        mv_sign_changes = np.sum(np.abs(np.diff(np.sign(mv_diff))) > 0)
        mv_oscillation_ratio = mv_sign_changes / (len(mv) - 2) if len(mv) > 2 else 0
        
        # 计算MV的振荡幅度（排除阶跃影响）
        if mv_oscillation_ratio > 0.2:
            # MV确实在振荡，使用振荡幅度
            mv_amplitude = (np.max(mv) - np.min(mv)) / 2
        else:
            # MV可能是阶跃，使用中位数绝对差分作为振荡幅度
            mv_amplitude = np.median(np.abs(mv_diff)) * 2
        
        # 使用继电器反馈法估算临界增益
        if amplitude > self._epsilon:
            Ku_estimate = 4 * mv_amplitude / (np.pi * amplitude)
            
            # 动态调整Ku边界（基于过程增益K）
            # 先估算过程增益K
            pv_range = np.ptp(pv)
            mv_range = np.ptp(mv)
            K_approx = pv_range / mv_range if mv_range > 0.1 else 1.0
            
            # Ku的合理范围应该与K相关：
            # - 小增益系统(K=0.1): Ku合理范围约[0.5, 10] → Ku/K ∈ [5, 100]
            # - 大增益系统(K=2.0): Ku合理范围约[0.1, 5] → Ku/K ∈ [0.05, 2.5]
            # 使用动态边界: Ku_min = 0.1, Ku_max = max(10, 15/K)
            Ku_min = 0.1
            Ku_max = max(10.0, 15.0 / max(K_approx, 0.1))  # K越大，Ku上限越小
            Ku_max = min(Ku_max, 100.0)  # 绝对上限100
            
            Ku_estimate = np.clip(Ku_estimate, Ku_min, Ku_max)
        else:
            Ku_estimate = 1.0
        
        # 判断振荡类型
        if avg_decay > 1.1:
            osc_type = 'diverging'
        elif avg_decay < 0.9:
            osc_type = 'converging'
        else:
            osc_type = 'sustained'
        
        n_cycles = max(len(peak_indices), len(valley_indices)) - 1
        
        return {
            'Pu': round(Pu, 3),              # 临界周期（提高精度）
            'Ku': round(Ku_estimate, 4),     # 临界增益估计
            'amplitude': round(amplitude, 2), # 振荡幅度
            'mv_amplitude': round(mv_amplitude, 2),  # MV幅度
            'decay_ratio': round(avg_decay, 3),      # 衰减比
            'oscillation_type': osc_type,    # 振荡类型
            'n_cycles': n_cycles,            # 完整振荡周期数
            'is_valid': n_cycles >= 2 and osc_type != 'diverging',
            'detection_methods': {           # 各方法检测结果（调试用）
                'peaks': round(Pu_peaks, 3) if Pu_peaks else None,
                'fft': round(Pu_fft, 3) if Pu_fft else None,
                'autocorr': round(Pu_autocorr, 3) if Pu_autocorr else None
            }
        }
    
    def _detect_period_from_peaks(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用峰值检测法计算周期"""
        peak_indices, peak_values, _, _ = self._find_peaks_valleys(pv)
        
        if len(peak_indices) < 3:
            return None
        
        # 使用抛物线插值精化峰值位置
        refined_indices = []
        for idx in peak_indices:
            if 1 <= idx < len(pv) - 1:
                # 抛物线插值: y = a*x^2 + b*x + c
                # 峰值位置: x_peak = -b / (2a)
                y0, y1, y2 = pv[idx-1], pv[idx], pv[idx+1]
                denom = 2 * (y0 - 2*y1 + y2)
                if abs(denom) > self._epsilon:
                    delta = (y0 - y2) / denom
                    refined_indices.append(idx + delta)
                else:
                    refined_indices.append(float(idx))
            else:
                refined_indices.append(float(idx))
        
        # 计算相邻峰值间的周期
        periods = np.diff(refined_indices) * dt
        
        # 过滤异常值（使用 IQR 方法）
        if len(periods) >= 3:
            q1, q3 = np.percentile(periods, [25, 75])
            iqr = q3 - q1
            valid_periods = periods[(periods >= q1 - 1.5*iqr) & (periods <= q3 + 1.5*iqr)]
            if len(valid_periods) > 0:
                return float(np.median(valid_periods))
        
        return float(np.median(periods)) if len(periods) > 0 else None
    
    def _detect_period_from_fft(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用 FFT 检测主频"""
        n = len(pv)
        if n < 10:
            return None
        
        # 加窗减少频谱泄漏
        window = np.hanning(n)
        pv_windowed = pv * window
        
        # FFT
        fft_result = np.fft.rfft(pv_windowed)
        freqs = np.fft.rfftfreq(n, dt)
        
        # 找到主频（排除直流分量）
        magnitude = np.abs(fft_result)
        
        # 只考虑合理的频率范围（周期在 2*dt 到 n*dt/2 之间）
        min_freq = 2.0 / (n * dt)  # 至少 2 个周期
        max_freq = 1.0 / (2 * dt)   # 奈奎斯特频率
        
        valid_mask = (freqs > min_freq) & (freqs < max_freq)
        if not np.any(valid_mask):
            return None
        
        valid_freqs = freqs[valid_mask]
        valid_magnitude = magnitude[valid_mask]
        
        # 找到最大幅度对应的频率
        peak_idx = np.argmax(valid_magnitude)
        dominant_freq = valid_freqs[peak_idx]
        
        if dominant_freq > self._epsilon:
            return 1.0 / dominant_freq
        return None
    
    def _detect_period_from_autocorr(self, pv: np.ndarray, dt: float) -> Optional[float]:
        """使用自相关法检测周期"""
        n = len(pv)
        if n < 20:
            return None
        
        # 计算自相关
        pv_normalized = pv - np.mean(pv)
        autocorr = np.correlate(pv_normalized, pv_normalized, mode='full')
        autocorr = autocorr[n-1:]  # 只取正延迟部分
        autocorr = autocorr / autocorr[0]  # 归一化
        
        # 找到第一个极大值（排除 lag=0）
        min_lag = max(2, int(1.0 / dt))  # 至少 1 秒
        max_lag = n // 2
        
        for i in range(min_lag, max_lag):
            if autocorr[i] > autocorr[i-1] and autocorr[i] > autocorr[i+1]:
                # 使用抛物线插值精化
                y0, y1, y2 = autocorr[i-1], autocorr[i], autocorr[i+1]
                denom = 2 * (y0 - 2*y1 + y2)
                if abs(denom) > self._epsilon:
                    delta = (y0 - y2) / denom
                    return (i + delta) * dt
                return i * dt
        
        return None
    
    def _find_peaks_valleys(self, pv: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """找到峰值和谷值的位置和值"""
        peak_indices = []
        peak_values = []
        valley_indices = []
        valley_values = []
        
        for i in range(1, len(pv) - 1):
            if pv[i] > pv[i-1] and pv[i] > pv[i+1]:
                peak_indices.append(i)
                peak_values.append(pv[i])
            elif pv[i] < pv[i-1] and pv[i] < pv[i+1]:
                valley_indices.append(i)
                valley_values.append(pv[i])
        
        return (np.array(peak_indices), np.array(peak_values), 
                np.array(valley_indices), np.array(valley_values))
    
    def calculate_from_oscillation(self, osc_info: Dict, 
                                   current_pid: Dict = None,
                                   method: str = 'zn') -> Optional[Dict[str, float]]:
        """
        基于振荡特征计算 PID 参数（Ziegler-Nichols 临界法）
        
        Args:
            osc_info: 振荡分析结果（来自 analyze_oscillation）
            current_pid: 当前 PID 参数 {'Kp': ..., 'Ki': ..., 'Kd': ...}
            method: 整定方法
                - 'zn': Ziegler-Nichols 经典法
                - 'zn_no_overshoot': ZN 无超调法
                - 'zn_some_overshoot': ZN 少超调法
                - 'tyreus_luyben': Tyreus-Luyben 法（更稳定）
        
        Returns:
            PID 参数字典，如果无法计算则返回 None
        """
        if not osc_info or not osc_info.get('is_valid', False):
            return None
        
        Pu = osc_info['Pu']
        Ku = osc_info['Ku']
        
        # 如果有当前 PID 参数，可以用于校正 Ku 估计
        if current_pid and current_pid.get('Kp', 0) != 0:
            current_Kp = abs(current_pid['Kp'])
            # 如果当前系统正在临界振荡，则 Ku ≈ current_Kp
            # 如果是发散振荡，Ku < current_Kp
            # 如果是收敛振荡，Ku > current_Kp
            osc_type = osc_info.get('oscillation_type', 'sustained')
            if osc_type == 'sustained':
                Ku = current_Kp
            elif osc_type == 'diverging':
                Ku = current_Kp * 0.8  # 保守估计
            else:  # converging
                Ku = current_Kp * 1.2
        
        # 根据不同方法计算 PID 参数
        if method == 'zn':
            # Ziegler-Nichols 经典法（可能有较大超调）
            Kp = 0.6 * Ku
            Ti = Pu / 2
            Td = Pu / 8
        elif method == 'zn_no_overshoot':
            # ZN 无超调法
            Kp = 0.2 * Ku
            Ti = Pu / 2
            Td = Pu / 3
        elif method == 'zn_some_overshoot':
            # ZN 少超调法
            Kp = 0.33 * Ku
            Ti = Pu / 2
            Td = Pu / 3
        elif method == 'tyreus_luyben':
            # Tyreus-Luyben 法（更稳定，适合工业应用）
            Kp = 0.45 * Ku
            Ti = 2.2 * Pu
            Td = Pu / 6.3
        else:
            # 默认使用保守的 ZN 法
            Kp = 0.45 * Ku
            Ti = Pu / 1.2
            Td = Pu / 8
        
        # 计算 Ki 和 Kd
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        # 确定符号（如果有当前 PID，保持符号一致）
        if current_pid and current_pid.get('Kp', 0) < 0:
            Kp = -Kp
            Ki = -Ki
            Kd = -Kd
        
        return {
            'Kp': round(float(Kp), 2),
            'Ki': round(float(Ki), 2),
            'Kd': round(float(Kd), 2),
            'method': f'oscillation_{method}',
            'Pu': round(Pu, 2),
            'Ku': round(Ku, 2)
        }
    
    def calculate_model_rating(self, fusion: FusionResult, 
                                total_data_points: int,
                                cl_metrics: 'ClosedLoopMetrics' = None,
                                verbose: bool = False) -> Tuple[float, Dict[str, float]]:
        """
        计算综合模型评分 (0-10分)
        
        综合考虑以下维度：
        1. 拟合质量 (R²)        - 30%
        2. 参数一致性            - 20%
        3. 参数物理合理性        - 15%
        4. 数据覆盖度            - 10%
        5. 闭环稳定性            - 25%
        
        Returns:
            (model_rating, score_details)
        """
        score_details = {}
        
        # 1. 拟合质量评分 (0-10) - 权重 40%
        r2 = fusion.global_r2
        if r2 >= 0.95:
            r2_score = 10.0
        elif r2 >= 0.9:
            r2_score = 9.0 + (r2 - 0.9) * 20
        elif r2 >= 0.8:
            r2_score = 7.5 + (r2 - 0.8) * 15
        elif r2 >= 0.6:
            r2_score = 5.0 + (r2 - 0.6) * 12.5
        elif r2 >= 0.4:
            r2_score = 3.0 + (r2 - 0.4) * 10
        elif r2 >= 0.2:
            r2_score = 1.0 + (r2 - 0.2) * 10
        else:
            r2_score = r2 * 5
        score_details['r2_score'] = round(r2_score, 2)
        
        # 2. 参数一致性评分 (0-10) - 权重 25%
        consistency_score = 10.0
        
        if fusion.n_segments_used > 1:
            k_mean = abs(fusion.K) + self._epsilon
            k_cv = fusion.K_std / k_mean
            
            t1_mean = abs(fusion.T1) + self._epsilon
            t1_cv = fusion.T1_std / t1_mean
            
            k_consistency = max(0, 10 - k_cv * 15)
            t1_consistency = max(0, 10 - t1_cv * 15)
            
            consistency_score = 0.6 * k_consistency + 0.4 * t1_consistency
            
            if fusion.consistency_score > 0:
                consistency_score = 0.7 * consistency_score + 0.3 * (fusion.consistency_score * 10)
        else:
            if fusion.consistency_score > 0:
                consistency_score = fusion.consistency_score * 10
            else:
                consistency_score = 6.0
        
        consistency_score = min(10.0, max(0.0, consistency_score))
        score_details['consistency_score'] = round(consistency_score, 2)
        
        # 3. 参数物理合理性评分 (0-10) - 权重 20%
        validity_score = 10.0
        penalties = []
        
        K = fusion.K
        if abs(K) < 0.001:
            penalties.append(('K接近零', 4.0))
        elif abs(K) > 50:
            penalties.append(('K过大', 2.0))
        elif abs(K) < 0.01:
            penalties.append(('K过小', 1.0))
        
        T1 = fusion.T1
        if T1 <= 0:
            penalties.append(('T1非正', 5.0))
        elif T1 < 0.1:
            penalties.append(('T1过小', 2.0))
        elif T1 > 500:
            penalties.append(('T1过大', 1.5))
        
        L = fusion.L
        if L < 0:
            penalties.append(('L为负', 3.0))
        elif L > T1 * 2 and T1 > 0:
            penalties.append(('L过大', 1.0))
        
        T2 = fusion.T2
        if T2 < 0:
            penalties.append(('T2为负', 2.0))
        
        for reason, penalty in penalties:
            validity_score -= penalty
            if verbose:
                print(f"   参数检查: {reason}, 扣{penalty}分")
        
        validity_score = max(0.0, validity_score)
        score_details['validity_score'] = round(validity_score, 2)
        
        # 4. 数据覆盖度评分 (0-10) - 权重 15%
        n_segments = fusion.n_segments_used
        
        if n_segments >= 4:
            segment_score = 9.0 + min(1.0, (n_segments - 4) * 0.25)
        elif n_segments == 3:
            segment_score = 8.5
        elif n_segments == 2:
            segment_score = 7.0
        elif n_segments == 1:
            segment_score = 5.0
        else:
            segment_score = 0.0
        
        if total_data_points >= 500:
            data_score = 10.0
        elif total_data_points >= 200:
            data_score = 7.0 + (total_data_points - 200) / 100
        elif total_data_points >= 100:
            data_score = 5.0 + (total_data_points - 100) / 50
        elif total_data_points >= 50:
            data_score = 3.0 + (total_data_points - 50) / 25
        else:
            data_score = total_data_points / 50 * 3
        
        coverage_score = 0.6 * segment_score + 0.4 * data_score
        coverage_score = min(10.0, coverage_score)
        score_details['coverage_score'] = round(coverage_score, 2)
        score_details['n_segments'] = n_segments
        score_details['total_data_points'] = total_data_points
        
        # 5. 闭环稳定性评分 (0-10) - 权重 25%
        # 综合评估：overshoot, rise_time, steady_state_error, oscillation_count, decay_ratio
        stability_score = 5.0  # 默认中等分数
        
        if cl_metrics is not None:
            # 基础分：是否稳定
            if cl_metrics.is_stable:
                stability_score = 6.0
            else:
                stability_score = 1.0
            
            # 1. 超调量评分（越小越好，权重最高）
            overshoot = cl_metrics.overshoot
            if overshoot <= 5:
                stability_score += 1.5  # 优秀
            elif overshoot <= 15:
                stability_score += 1.0  # 良好
            elif overshoot <= 30:
                stability_score += 0.5  # 可接受
            elif overshoot <= 50:
                stability_score -= 0.5  # 较差
            else:
                stability_score -= 1.5  # 严重超调
            
            # 2. 上升时间评分（适中为好，太快太慢都不好）
            rise_time = cl_metrics.rise_time
            if rise_time < float('inf'):
                if 1.0 <= rise_time <= 10.0:
                    stability_score += 1.0  # 理想范围
                elif 0.5 <= rise_time < 1.0 or 10.0 < rise_time <= 20.0:
                    stability_score += 0.5  # 可接受
                elif rise_time < 0.5:
                    stability_score -= 0.5  # 太快，可能不稳定
                else:
                    stability_score -= 0.5  # 太慢
            
            # 3. 稳态误差评分（越小越好）
            sse = cl_metrics.steady_state_error
            if sse <= 1:
                stability_score += 1.0  # 优秀
            elif sse <= 2:
                stability_score += 0.5  # 良好
            elif sse <= 5:
                pass  # 可接受
            elif sse <= 10:
                stability_score -= 0.5  # 较差
            else:
                stability_score -= 1.0  # 严重偏差
            
            # 4. 振荡次数评分（越少越好）
            osc_count = cl_metrics.oscillation_count
            if osc_count == 0:
                stability_score += 0.5  # 无振荡，可能过阻尼
            elif osc_count <= 2:
                stability_score += 1.0  # 理想，轻微振荡后收敛
            elif osc_count <= 4:
                stability_score += 0.5  # 可接受
            elif osc_count <= 6:
                stability_score -= 0.5  # 振荡较多
            else:
                stability_score -= 1.0  # 持续振荡
            
            # 5. 衰减比评分（0.25左右为理想，越接近0越好）
            decay_ratio = cl_metrics.decay_ratio
            if decay_ratio <= 0.25:
                stability_score += 1.0  # 快速衰减，理想
            elif decay_ratio <= 0.5:
                stability_score += 0.5  # 良好衰减
            elif decay_ratio <= 1.0:
                pass  # 临界阻尼
            else:
                stability_score -= 1.0  # 发散或不收敛
            
            stability_score = min(10.0, max(0.0, stability_score))
        
        score_details['stability_score'] = round(stability_score, 2)
        
        # 综合评分（新权重）
        weights = {
            'r2': 0.30,           # 拟合质量
            'consistency': 0.20,  # 参数一致性
            'validity': 0.15,     # 参数物理合理性
            'coverage': 0.10,     # 数据覆盖度
            'stability': 0.25     # 闭环稳定性
        }
        
        final_score = (
            weights['r2'] * r2_score +
            weights['consistency'] * consistency_score +
            weights['validity'] * validity_score +
            weights['coverage'] * coverage_score +
            weights['stability'] * stability_score
        )
        
        if r2 < 0.3:
            final_score = min(final_score, 3.0)
        elif r2 < 0.5:
            final_score = min(final_score, 5.0)
        
        # 如果闭环不稳定，限制最高分
        if cl_metrics is not None and not cl_metrics.is_stable:
            final_score = min(final_score, 5.0)
        
        final_score = round(min(10.0, max(0.0, final_score)), 2)
        score_details['weights'] = weights
        
        return final_score, score_details
    
    # ============================================================
    # 闭环稳定性验证
    # ============================================================
    
    def simulate_closed_loop(self, K: float, T1: float, T2: float, L: float,
                              model_type: str, Kp: float, Ki: float, Kd: float,
                              sp_initial: float, sp_final: float,
                              pv_initial: float = None,
                              n_steps: int = 500,
                              dt: float = 1.0,
                              mv_min: float = 0.0,
                              mv_max: float = 100.0) -> ClosedLoopMetrics:
        """
        闭环仿真：验证PID参数在给定模型下是否能达到稳态
        
        使用增量模型：ΔPV = K × ΔMV（围绕工作点的线性化模型）
        
        Args:
            K, T1, T2, L: 模型参数（增量模型参数）
            model_type: 模型类型
            Kp, Ki, Kd: PID参数
            sp_initial: 初始设定值
            sp_final: 目标设定值（阶跃后）
            pv_initial: 初始PV值，默认等于sp_initial
            n_steps: 仿真步数
            dt: 时间步长
            mv_min, mv_max: MV输出限制
        
        Returns:
            ClosedLoopMetrics: 闭环性能指标
        """
        if pv_initial is None:
            pv_initial = sp_initial
        
        # 初始化
        pv_history = np.zeros(n_steps)
        mv_history = np.zeros(n_steps)
        sp_history = np.zeros(n_steps)
        
        # 工作点：初始稳态
        pv0 = pv_initial  # 初始PV工作点
        
        # MV 工作点：根据模型增益和 SP 变化量估算需要的 MV 变化
        # 简化逻辑：从中点开始，确保有足够的调节空间
        sp_change = sp_final - sp_initial
        mv_mid = (mv_min + mv_max) / 2
        mv_range = mv_max - mv_min
        
        if abs(K) > self._epsilon:
            delta_mv_needed = sp_change / K  # 理论需要的 MV 变化量
            # 根据需要的MV变化方向，从中点偏移以留出调节空间
            # 但偏移量不超过范围的25%
            mv_offset = np.clip(-delta_mv_needed * 0.3, -mv_range * 0.25, mv_range * 0.25)
            mv0 = np.clip(mv_mid + mv_offset, mv_min + 5, mv_max - 5)
        else:
            mv0 = mv_mid
        
        # 增量状态变量
        delta_pv = 0.0    # ΔPV = PV - PV0
        delta_x2 = 0.0    # 二阶模型的第二状态增量
        
        integral = 0.0
        prev_error = 0.0
        
        # 滞后缓冲区（存储ΔMV）
        delay_steps = max(0, int(L / dt))
        delta_mv_buffer = [0.0] * (delay_steps + 1)
        
        # SP阶跃：在第10步发生
        step_time = 10
        
        for t in range(n_steps):
            # 设定值
            sp = sp_initial if t < step_time else sp_final
            sp_history[t] = sp
            
            # 当前PV = PV0 + ΔPV
            pv = pv0 + delta_pv
            pv_history[t] = pv
            
            # PID计算
            error = sp - pv
            integral += error * dt
            
            # 积分限幅（防止积分饱和）
            integral_limit = (mv_max - mv_min) / (abs(Ki) + self._epsilon)
            integral = np.clip(integral, -integral_limit, integral_limit)
            
            derivative = (error - prev_error) / dt if t > 0 else 0.0
            
            # PID输出的是增量MV（相对于工作点）
            delta_mv_pid = Kp * error + Ki * integral + Kd * derivative
            
            # 实际MV = MV0 + ΔMV，需要限幅
            mv = mv0 + delta_mv_pid
            mv = np.clip(mv, mv_min, mv_max)
            delta_mv = mv - mv0  # 实际的ΔMV（考虑限幅后）
            
            mv_history[t] = mv
            prev_error = error
            
            # 滞后处理
            delta_mv_buffer.append(delta_mv)
            delta_mv_delayed = delta_mv_buffer.pop(0)
            
            # 增量模型更新
            delta_pv, delta_x2 = self._model_step_incremental(
                K, T1, T2, model_type, delta_pv, delta_x2, delta_mv_delayed, dt
            )
        
        # 计算性能指标
        return self._calculate_metrics(pv_history, sp_history, mv_history, 
                                        sp_final, step_time, dt)
    
    def _model_step_incremental(self, K: float, T1: float, T2: float, model_type: str,
                                 delta_x1: float, delta_x2: float, 
                                 delta_mv: float, dt: float) -> Tuple[float, float]:
        """
        增量模型单步更新（欧拉离散化）
        
        模型：ΔPV(s) / ΔMV(s) = K / (T1*s + 1) 或更复杂形式
        """
        T1 = max(T1, self._epsilon)
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            # 一阶增量模型: T1 * d(ΔPV)/dt + ΔPV = K * ΔMV
            # 离散化: ΔPV_new = ΔPV + (dt/T1) * (K * ΔMV - ΔPV)
            alpha = dt / T1
            delta_x1_new = delta_x1 + alpha * (K * delta_mv - delta_x1)
            return delta_x1_new, 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            # 二阶增量模型：两个一阶串联
            T2_eff = max(T2, T1 * 0.1)
            alpha1 = dt / T1
            alpha2 = dt / T2_eff
            # 第一阶段输出
            delta_x1_new = delta_x1 + alpha1 * (K * delta_mv - delta_x1)
            # 第二阶段输出（最终ΔPV）
            delta_x2_new = delta_x2 + alpha2 * (delta_x1_new - delta_x2)
            return delta_x2_new, delta_x1_new
        
        elif model_type == ModelType.FOPI:
            # 积分模型: d(ΔPV)/dt = K * ΔMV
            delta_x1_new = delta_x1 + dt * K * delta_mv
            return delta_x1_new, 0.0
        
        return delta_x1, delta_x2
    
    def _calculate_metrics(self, pv: np.ndarray, sp: np.ndarray, mv: np.ndarray,
                           sp_final: float, step_time: int, dt: float) -> ClosedLoopMetrics:
        """计算闭环性能指标"""
        n = len(pv)
        sp_change = sp_final - sp[0]
        
        # 只分析阶跃后的响应
        pv_response = pv[step_time:]
        sp_response = sp[step_time:]
        
        if len(pv_response) < 10 or abs(sp_change) < self._epsilon:
            return ClosedLoopMetrics(
                is_stable=False, settling_time=float('inf'), overshoot=0.0,
                rise_time=float('inf'), steady_state_error=100.0,
                oscillation_count=0, decay_ratio=1.0,
                pv_history=pv, mv_history=mv
            )
        
        # 1. 稳态误差（最后10%的平均值）
        final_portion = pv_response[-max(10, len(pv_response)//10):]
        steady_state_error = abs(np.mean(final_portion) - sp_final) / (abs(sp_change) + self._epsilon) * 100
        
        # 2. 超调量
        if sp_change > 0:
            peak = np.max(pv_response)
            overshoot = max(0, (peak - sp_final) / sp_change * 100)
        else:
            trough = np.min(pv_response)
            overshoot = max(0, (sp_final - trough) / abs(sp_change) * 100)
        
        # 3. 上升时间（10% 到 90%）
        target_10 = sp[0] + 0.1 * sp_change
        target_90 = sp[0] + 0.9 * sp_change
        rise_start = rise_end = None
        
        for i, p in enumerate(pv_response):
            if sp_change > 0:
                if rise_start is None and p >= target_10:
                    rise_start = i
                if rise_end is None and p >= target_90:
                    rise_end = i
                    break
            else:
                if rise_start is None and p <= target_10:
                    rise_start = i
                if rise_end is None and p <= target_90:
                    rise_end = i
                    break
        
        if rise_start is not None and rise_end is not None:
            rise_time = (rise_end - rise_start) * dt
        else:
            rise_time = float('inf')
        
        # 4. 调节时间（进入±2%误差带）
        tolerance = 0.02 * abs(sp_change)
        settling_time = float('inf')
        
        for i in range(len(pv_response) - 1, -1, -1):
            if abs(pv_response[i] - sp_final) > tolerance:
                if i < len(pv_response) - 1:
                    settling_time = (i + 1) * dt
                break
        else:
            settling_time = 0.0  # 始终在误差带内
        
        # 5. 振荡计数和衰减比
        error_signal = pv_response - sp_final
        zero_crossings = np.where(np.diff(np.signbit(error_signal)))[0]
        oscillation_count = len(zero_crossings) // 2
        
        # 衰减比：第二个峰与第一个峰的比值
        peaks = []
        for i in range(1, len(error_signal) - 1):
            if error_signal[i] > error_signal[i-1] and error_signal[i] > error_signal[i+1]:
                peaks.append(abs(error_signal[i]))
            if len(peaks) >= 2:
                break
        
        if len(peaks) >= 2 and peaks[0] > self._epsilon:
            decay_ratio = peaks[1] / peaks[0]
        else:
            decay_ratio = 0.0 if len(peaks) <= 1 else 1.0
        
        # 6. 稳定性判定
        is_stable = (
            settling_time < float('inf') and
            steady_state_error < 5.0 and  # 稳态误差<5%
            overshoot < 50.0 and          # 超调<50%
            decay_ratio < 0.5             # 衰减比<0.5
        )
        
        return ClosedLoopMetrics(
            is_stable=is_stable,
            settling_time=settling_time,
            overshoot=round(overshoot, 2),
            rise_time=round(rise_time, 2),
            steady_state_error=round(steady_state_error, 2),
            oscillation_count=oscillation_count,
            decay_ratio=round(decay_ratio, 3),
            pv_history=pv,
            mv_history=mv
        )
    
    def verify_pid_stability(self, fusion: Optional[FusionResult], 
                              pid_params: Dict[str, float],
                              sp_initial: float = 50.0,
                              sp_final: float = 60.0,
                              pv_initial: float = None,
                              verbose: bool = False) -> Tuple[bool, ClosedLoopMetrics]:
        """
        验证PID参数的闭环稳定性
        
        Args:
            fusion: 模型参数（可以为 None，用于振荡整定场景）
            pid_params: PID参数 {Kp, Ki, Kd}
            sp_initial: SP初始值（来自实际数据）
            sp_final: SP目标值（来自实际数据）
            pv_initial: PV初始值（来自实际数据）
            verbose: 是否打印详细信息
        
        Returns:
            (is_stable, metrics)
        """
        if pv_initial is None:
            pv_initial = sp_initial
        
        # 如果 fusion 为 None（振荡整定），使用默认模型参数
        if fusion is None:
            # 根据 PID 参数估算过程特性
            Kp = abs(pid_params.get('Kp', 1.0))
            # 假设一个典型的一阶过程
            K = 1.0 / Kp if Kp > self._epsilon else 1.0  # 反推过程增益
            T1 = pid_params.get('Pu', 10.0) if 'Pu' in pid_params else 10.0  # 使用临界周期作为参考
            T2 = 0.0
            L = 0.0
            model_type = ModelType.FO
        else:
            K = fusion.K
            T1 = fusion.T1
            T2 = fusion.T2
            L = fusion.L
            model_type = fusion.model_type
        
        # 自适应仿真参数：确保数值稳定性
        T_min = min(T1, T2 if T2 > 0 else T1)
        dt = min(0.1, T_min / 10)  # 步长不超过最小时间常数的1/10
        dt = max(0.01, dt)         # 但也不要太小
        
        # 仿真时长：至少10倍最大时间常数
        T_max = max(T1, T2 if T2 > 0 else T1)
        sim_time = max(100, T_max * 20)
        n_steps = int(sim_time / dt)
        n_steps = min(n_steps, 5000)  # 限制最大步数
        
        metrics = self.simulate_closed_loop(
            K=K, T1=T1, T2=T2, L=L,
            model_type=model_type,
            Kp=pid_params['Kp'], Ki=pid_params['Ki'], Kd=pid_params['Kd'],
            sp_initial=sp_initial,
            sp_final=sp_final,
            pv_initial=pv_initial,
            n_steps=n_steps,
            dt=dt
        )
        
        if verbose:
            status = "✅ 稳定" if metrics.is_stable else "❌ 不稳定"
            print(f"\n🔄 闭环稳定性验证: {status}")
            print(f"   调节时间: {metrics.settling_time:.1f}s")
            print(f"   超调量: {metrics.overshoot:.1f}%")
            print(f"   上升时间: {metrics.rise_time:.1f}s")
            print(f"   稳态误差: {metrics.steady_state_error:.2f}%")
            print(f"   振荡次数: {metrics.oscillation_count}")
            print(f"   衰减比: {metrics.decay_ratio:.3f}")
        
        return metrics.is_stable, metrics
