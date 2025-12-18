"""
振荡数据整定模块 (Oscillation Tuner Module)
==========================================

本模块处理高振荡数据的临界法整定。

核心功能
--------
1. **振荡检测**: 识别高振荡且常规拟合失败的数据段
2. **临界法整定**: 基于Ziegler-Nichols/Tyreus-Luyben法计算PID参数
3. **保守参数**: 对不可靠的临界增益使用保守PID参数
4. **闭环验证**: 验证整定参数的闭环稳定性

触发条件
--------
- oscillation_ratio > 配置阈值 (默认0.1)
- 所有模型 R² < 配置阈值 (默认0.3)
- 无成功拟合的扰动段
"""

import numpy as np
from typing import List, Dict, Any, Optional

from ..config import Config, ModelType
from ..data_models import SegmentResult, HistoricalData, FusionResult
from ..utils import calculate_r2, calculate_rmse


class OscillationTuner:
    """
    振荡数据整定器
    
    当常规模型拟合失败且检测到高振荡时，使用临界法进行PID整定
    """
    
    def __init__(self, pid_calculator, simulator, verbose: bool = False):
        """
        Args:
            pid_calculator: PIDCalculator 实例
            simulator: ModelSimulator 实例
            verbose: 是否输出详细日志
        """
        self._pid_calculator = pid_calculator
        self._simulator = simulator
        self._verbose = verbose
        self._epsilon = Config.EPSILON
    
    def log(self, msg: str) -> None:
        if self._verbose:
            print(msg)
    
    def try_oscillation_tuning(self, segments: List[HistoricalData], 
                               segment_results: List[SegmentResult],
                               current_pid: Dict = None) -> Optional[Dict]:
        """
        尝试使用振荡分析进行临界法整定
        
        当检测到高振荡数据且常规模型拟合失败时，使用振荡特征进行PID整定
        
        Args:
            segments: 扰动段数据列表
            segment_results: 各段拟合结果
            current_pid: 当前PID参数（用于校正Ku估计）
        
        Returns:
            振荡整定结果，如果不适用则返回 None
        """
        # 检查是否有高振荡段且拟合失败（使用配置阈值）
        osc_config = Config.OSCILLATION_TUNING
        osc_ratio_threshold = osc_config['oscillation_ratio_threshold']
        r2_failure_threshold = osc_config['r2_failure_threshold']
        
        # 首先检查是否有任何段拟合成功
        successful_segments = []
        oscillating_segments = []
        for i, (seg, result) in enumerate(zip(segments, segment_results)):
            is_oscillating = result.oscillation_ratio > osc_ratio_threshold
            fit_failed = result.best_r2 < r2_failure_threshold
            
            # 检查是否有模型参数被推到边界（说明拟合不可靠）
            params_at_boundary = False
            if result.best_model and result.model_results:
                best_params = result.model_results.get(result.best_model, {})
                T1 = best_params.get('T1', None)
                # T1 被推到下限（1.0s 或 0.5s）说明拟合可能不可靠
                if T1 is not None and T1 <= 1.5:  # 放宽检测阈值
                    params_at_boundary = True
                    fit_failed = True  # 参数在边界也认为是拟合失败
                    self.log(f"   ⚠️ 段{i+1}: T1={T1:.2f}s 过小，认为拟合不可靠")
            
            if not fit_failed and result.best_r2 >= r2_failure_threshold:
                # 有成功拟合的段（且参数不在边界）
                successful_segments.append((i, seg, result))
            
            if is_oscillating and fit_failed:
                oscillating_segments.append((i, seg, result))
        
        # 判断是否应该强制使用临界法整定
        # 条件1: 成功段太少（失败率>50%）且有振荡段
        # 条件2: 成功段数据量太小（<1000点）
        # 条件3: 平均振荡比过高（>0.7）
        total_segments = len(segment_results)
        failed_segments = len(oscillating_segments)
        avg_osc_ratio = np.mean([r.oscillation_ratio for r in segment_results]) if segment_results else 0
        
        force_oscillation_tuning = False
        force_reason = ""
        
        if successful_segments and oscillating_segments:
            # 计算成功段的总数据量
            success_total_points = sum(len(seg.pv) for _, seg, _ in successful_segments)
            failed_total_points = sum(len(seg.pv) for _, seg, _ in oscillating_segments)
            
            # 条件1: 失败段数据量占比超过80%
            if failed_total_points > 0 and success_total_points > 0:
                failure_ratio = failed_total_points / (success_total_points + failed_total_points)
                if failure_ratio > 0.8:
                    force_oscillation_tuning = True
                    force_reason = f"失败段数据量占比{failure_ratio:.0%}>80%"
            
            # 条件2: 成功段数据量太小（<1000点）
            if success_total_points < 1000:
                force_oscillation_tuning = True
                force_reason = f"成功段数据量仅{success_total_points}点<1000"
            
            # 条件3: 平均振荡比过高且有多个失败段
            if avg_osc_ratio > 0.7 and failed_segments >= total_segments // 2:
                force_oscillation_tuning = True
                force_reason = f"平均振荡比{avg_osc_ratio:.2f}>0.7且{failed_segments}/{total_segments}段失败"
        
        # 如果有成功拟合的段且不需要强制临界法，使用常规流程
        if successful_segments and not force_oscillation_tuning:
            self.log(f"\n📊 有 {len(successful_segments)} 个段拟合成功，使用常规模型融合流程")
            return None
        
        if force_oscillation_tuning:
            self.log(f"\n⚠️ 强制使用临界法整定: {force_reason}")
        
        if not oscillating_segments:
            return None  # 没有符合条件的振荡段
        
        self.log(f"\n🔄 检测到 {len(oscillating_segments)} 个高振荡拟合失败段，尝试临界法整定")
        
        # 分析每个振荡段
        oscillation_analyses = []
        for idx, seg, result in oscillating_segments:
            dt = 1.0  # 假设采样周期为1秒
            if len(seg.timestamp) > 1:
                dt = (seg.timestamp[1] - seg.timestamp[0]) / 1000  # 转换为秒
            
            osc_info = self._pid_calculator.analyze_oscillation(seg.pv, seg.mv, dt)
            
            if osc_info and osc_info.get('is_valid', False):
                oscillation_analyses.append({
                    'segment_idx': idx,
                    'osc_info': osc_info,
                    'data_points': len(seg.pv)
                })
                self.log(f"   段{idx+1}: Pu={osc_info['Pu']:.1f}s, Ku≈{osc_info['Ku']:.3f}, "
                        f"振幅={osc_info['amplitude']:.2f}, 类型={osc_info['oscillation_type']}")
        
        if not oscillation_analyses:
            self.log("   ⚠️ 无法从振荡数据中提取有效特征")
            return None
        
        # 选择最佳振荡分析结果（优先使用持续振荡，数据点数最多的段）
        best_analysis = None
        best_seg = None
        for analysis in oscillation_analyses:
            osc_type = analysis['osc_info']['oscillation_type']
            idx = analysis['segment_idx']
            if best_analysis is None:
                best_analysis = analysis
                best_seg = segments[idx] if idx < len(segments) else None
            elif osc_type == 'sustained' and best_analysis['osc_info']['oscillation_type'] != 'sustained':
                best_analysis = analysis
                best_seg = segments[idx] if idx < len(segments) else None
            elif analysis['data_points'] > best_analysis['data_points']:
                best_analysis = analysis
                best_seg = segments[idx] if idx < len(segments) else None
        
        # 检查是否需要使用保守参数
        use_conservative = False
        Ku = best_analysis['osc_info']['Ku']
        apparent_gain = 1.0
        
        if best_seg is not None:
            pv_range = np.ptp(best_seg.pv)
            mv_range = np.ptp(best_seg.mv)
            if mv_range > 0.1:
                apparent_gain = pv_range / mv_range
                self.log(f"   📊 增益检查: MV范围={mv_range:.2f}, PV范围={pv_range:.2f}, apparent_gain={apparent_gain:.4f}, Ku={Ku:.3f}")
                
                # 条件1: 低增益系统
                if apparent_gain < 0.1:
                    use_conservative = True
                    self.log(f"   ⚠️ 检测到低增益系统，使用保守参数")
                # 条件2: Ku过大（会导致Kp过大）
                elif Ku > 5.0:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku={Ku:.2f}>5.0，临界增益过大，使用保守参数")
                # 条件3: Ku过小（估计不可靠，会导致Kp过小、pb过大）
                elif Ku < 0.5:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku={Ku:.3f}<0.5，临界增益过小，使用保守参数")
        
        # 获取最佳段的振荡比（用于自适应调整）
        best_seg_idx = best_analysis['segment_idx']
        best_seg_result = segment_results[best_seg_idx] if best_seg_idx < len(segment_results) else None
        oscillation_ratio = best_seg_result.oscillation_ratio if best_seg_result else 0.0
        
        # ========== 改进：临界法整定统一使用保守参数（对齐大模型建议） ==========
        # 原因：Tyreus-Luyben等经典方法对于实际振荡系统往往过于激进
        # 大模型建议：PB应在180-220%范围，而非经典法的50%左右
        osc_config = Config.OSCILLATION_TUNING
        
        # 统一使用保守PID参数计算
        Pu = best_analysis['osc_info']['Pu']
        Ku = best_analysis['osc_info']['Ku']
        
        # 根据use_conservative标志选择保守程度
        if use_conservative:
            reason = 'low_gain'
        else:
            reason = 'oscillation'
        
        pid_params = self._get_conservative_pid_params(
            Pu, Ku, 
            K_approx=apparent_gain,
            reason=reason,
            oscillation_ratio=oscillation_ratio
        )
        
        if pid_params is None:
            self.log("   ⚠️ 临界法整定失败")
            return None
        
        self.log(f"   ✅ 临界法整定成功:")
        self.log(f"      Pu={best_analysis['osc_info']['Pu']:.1f}s, Ku={pid_params['Ku']:.3f}")
        self.log(f"      Kp={pid_params['Kp']:.4f}, Ki={pid_params['Ki']:.4f}, Kd={pid_params['Kd']:.4f}")
        self.log(f"      方法: {pid_params['method']}")
        
        return {
            'pid_params': pid_params,
            'oscillation_info': best_analysis['osc_info'],
            'segment_idx': best_analysis['segment_idx'],
            'method': 'oscillation_critical'
        }
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, 
                                      K_approx: float = 1.0,
                                      reason: str = 'generic',
                                      oscillation_ratio: float = 0.0) -> Dict[str, Any]:
        """
        获取保守PID参数（动态计算pb，借鉴大模型调参经验）
        
        改进点（基于大模型调参经验）：
        1. 严重振荡时使用更保守的pb
        2. 自适应添加微分作用抑制振荡
        3. pb范围扩展，允许更保守的参数
        
        Args:
            Pu: 临界周期
            Ku: 临界增益
            K_approx: 估计的过程增益
            reason: 使用保守参数的原因
            oscillation_ratio: 振荡比（用于自适应调整）
        
        Returns:
            保守PID参数字典
        """
        osc_config = Config.OSCILLATION_TUNING
        
        # ========== 动态计算 pb（渐进式策略，更通用） ==========
        # 1. 基于过程增益的基础 pb
        if K_approx > 0.01:
            # pb = 100/Kp, 对于单位反馈系统 Kp ≈ 1/K 时响应较好
            # 加入保守系数 1.5~2.0
            pb_from_K = 100.0 * K_approx * 1.5
        else:
            pb_from_K = 80.0  # 增益过小时的默认值
        
        # 2. 基于临界参数的 pb（Ziegler-Nichols 变体）
        if Ku > 0.1:
            # ZN法: Kp = 0.45*Ku (PI), 但我们更保守: Kp = 0.2*Ku
            Kp_from_Ku = 0.2 * Ku
            pb_from_Ku = 100.0 / max(Kp_from_Ku, 0.1)
        else:
            pb_from_Ku = 100.0  # Ku 不可靠时的默认值
        
        # 3. 基于临界周期的调整因子
        # 慢系统（Pu大）需要更保守
        if Pu > 30:
            slow_factor = 1.3
        elif Pu > 15:
            slow_factor = 1.15
        else:
            slow_factor = 1.0
        
        # 4. 综合计算：取较大值（更保守）并应用慢系统因子
        pb_base = max(pb_from_K, pb_from_Ku) * slow_factor
        
        # 5. 根据原因微调
        if reason == 'high_gain':
            pb_base *= 1.1  # Ku过大，轻微额外保守（降低以避免多重乘数溢出）
        # 注意：低增益场景不再强制设为pb_min，避免与后续乘数叠加导致触边界
        
        # ========== 渐进式振荡保守调整（核心改进，使用渐近函数） ==========
        # 使用渐近函数避免高振荡时pb线性爆炸
        # pb_multiplier = 1 + k * sqrt(osc - start)，增长放缓
        pb_gradient = osc_config.get('pb_gradient', 2.0)
        pb_osc_start = osc_config.get('pb_oscillation_start', 0.4)
        base_safety_factor = osc_config.get('critical_method_safety_factor', 1.4)
        
        # 自适应安全系数：保守优先，极高振荡更保守
        # 振荡比 < 0.5: safety = 1.4 (基础保守)
        # 振荡比 0.5-0.7: safety = 1.4 + (osc-0.5)*0.5 (线性过渡)
        # 振荡比 0.7-0.85: safety = 1.5 + (osc-0.7)*1.0 (加速增长)
        # 振荡比 > 0.85: safety = 1.65 + (osc-0.85)*2.0 (极高振荡，大幅保守)
        if oscillation_ratio < 0.5:
            safety_factor = 1.4  # 基础保守
        elif oscillation_ratio < 0.7:
            # 线性过渡：1.4 → 1.5
            safety_factor = 1.4 + (oscillation_ratio - 0.5) * 0.5
        elif oscillation_ratio < 0.85:
            # 高振荡：1.5 → 1.65
            safety_factor = 1.5 + (oscillation_ratio - 0.7) * 1.0
        else:
            # 极高振荡(>0.85)，大幅保守：1.65 → 1.95+
            safety_factor = 1.65 + (oscillation_ratio - 0.85) * 2.0
        
        # 计算综合保守乘数（将安全系数合并，避免多重乘数叠加）
        total_multiplier = safety_factor  # 自适应安全系数
        
        if oscillation_ratio > pb_osc_start:
            # 使用平方根函数，高振荡时增长放缓
            # effective_osc ∈ [0, 0.6]（振荡比最高1.0）
            effective_osc = oscillation_ratio - pb_osc_start
            # sqrt(0.6) ≈ 0.77，乘以gradient=1.0 → 0.77
            osc_multiplier = 1.0 + np.sqrt(effective_osc) * pb_gradient
            total_multiplier *= osc_multiplier
            
            # 限制总乘数上限，避免高增益+极高振荡导致pb爆炸
            # 极高振荡时允许更大乘数，确保保守
            if oscillation_ratio > 0.85:
                max_multiplier = 3.0  # 极高振荡允许更保守
            else:
                max_multiplier = 2.5
            if total_multiplier > max_multiplier:
                self.log(f"   ⚠️ 总乘数{total_multiplier:.2f}超限，限制为{max_multiplier}")
                total_multiplier = max_multiplier
            
            self.log(f"   📊 渐进式保守调整: 振荡比={oscillation_ratio:.2f}, "
                    f"安全系数={safety_factor:.2f}, osc乘数={osc_multiplier:.2f}, 总乘数={total_multiplier:.2f}")
        else:
            self.log(f"   📊 基础安全系数: ×{safety_factor:.2f}")
        
        pb_base *= total_multiplier
        
        # 6. 限制在合理范围（使用配置的范围）
        pb_min = osc_config.get('pb_min', 80.0)
        pb_max = osc_config.get('pb_max', 500.0)
        pb_safe = np.clip(pb_base, pb_min, pb_max)
        
        self.log(f"   📊 动态pb计算: K={K_approx:.3f}→pb={pb_from_K:.1f}, "
                f"Ku={Ku:.3f}→pb={pb_from_Ku:.1f}, Pu={Pu:.1f}s(×{slow_factor}), "
                f"最终pb={pb_safe:.1f}")
        
        conservative_Kp = 100.0 / pb_safe
        
        # ========== 自适应 Ti 计算（基于Pu和振荡比） ==========
        # 基础Ti = Pu / 2（经典ZN法）
        # 高振荡时增大Ti（减弱积分作用，提高稳定性）
        base_Ti = max(Pu / 2, 1.5) if Pu > 0 else 2.0
        
        # 振荡调整因子：振荡比>0.6时逐渐增大Ti（提高阈值，减少Ti增大）
        ti_osc_start = 0.6
        if oscillation_ratio > ti_osc_start:
            # Ti乘数 = 1 + sqrt(osc - 0.6) * 0.5，最大约1.32倍（降低系数加快响应）
            ti_multiplier = 1.0 + np.sqrt(oscillation_ratio - ti_osc_start) * 0.5
        else:
            ti_multiplier = 1.0
        
        # 慢系统调整：Pu大时Ti也应该更大（降低乘数）
        if Pu > 20:
            ti_multiplier *= 1.1
        elif Pu > 10:
            ti_multiplier *= 1.05
        
        conservative_Ti = base_Ti * ti_multiplier
        # Ti范围限制：[1.5, 10.0]
        conservative_Ti = np.clip(conservative_Ti, 1.5, 10.0)
        conservative_Ki = conservative_Kp / conservative_Ti
        
        # ========== 自适应 Td 计算（基于Pu和振荡比） ==========
        conservative_Kd = 0.0
        conservative_Td = 0.0
        enable_derivative = osc_config.get('enable_adaptive_derivative', True)
        derivative_threshold = osc_config.get('derivative_oscillation_threshold', 0.5)
        
        if enable_derivative and oscillation_ratio > derivative_threshold:
            # 基础Td = Pu / 8（经典ZN法是Pu/8）
            # 高振荡时适度增大Td（增强抑制作用）
            base_Td = Pu / 8 if Pu > 0 else 0.5
            
            # Td乘数：振荡越高，Td越大（抑制振荡）
            effective_osc = oscillation_ratio - derivative_threshold
            td_multiplier = 1.0 + np.sqrt(effective_osc) * 1.5  # 最大约2.06倍
            
            conservative_Td = base_Td * td_multiplier
            # Td范围限制：[0.3, 3.0]
            conservative_Td = np.clip(conservative_Td, 0.3, 3.0)
            conservative_Kd = conservative_Kp * conservative_Td
            
            self.log(f"   📊 自适应Ti/Td: Ti={conservative_Ti:.2f}s(×{ti_multiplier:.2f}), "
                    f"Td={conservative_Td:.2f}s(×{td_multiplier:.2f})")
            self.log(f"   📊 添加微分作用: Kd={conservative_Kd:.4f} (Kp×Td，用于抑制振荡)")
        else:
            self.log(f"   📊 自适应Ti: Ti={conservative_Ti:.2f}s(×{ti_multiplier:.2f})")
        
        return {
            'Kp': round(conservative_Kp, 2),
            'Ki': round(conservative_Ki, 2),
            'Kd': round(conservative_Kd, 2),
            'Ti': round(conservative_Ti, 4),  # 精确的Ti值
            'Td': round(conservative_Td, 4) if conservative_Td > 0 else 0.0,  # 精确的Td值
            'method': f'{reason}_adaptive',
            'Pu': round(Pu, 2),
            'Ku': round(Ku, 2),
            'pb': round(pb_safe, 2)
        }
    
    def build_oscillation_output(self, osc_result: Dict, hist_data: HistoricalData,
                                 time_range: Dict, tuning_windows: List) -> Dict[str, Any]:
        """
        构建振荡分析整定的输出结果
        
        Args:
            osc_result: try_oscillation_tuning 的返回结果
            hist_data: 历史数据
            time_range: 时间范围
            tuning_windows: 整定窗口列表
        
        Returns:
            标准格式的整定输出
        """
        pid_params = osc_result['pid_params']
        osc_info = osc_result['oscillation_info']
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = hist_data.timestamp[valid_mask]
        sv = hist_data.sv[valid_mask]
        
        # 先估算模型参数（用于闭环验证和输出，保持一致）
        Pu = osc_info['Pu']
        Ku = pid_params['Ku']
        
        # 使用数据整体范围估算过程增益 K（而不是振荡幅度）
        pv_range = np.ptp(y)
        mv_range = np.ptp(u)
        
        if mv_range > 0.1 and pv_range > 0.01:
            K_from_range = pv_range / mv_range
            
            pv_amplitude = osc_info.get('amplitude', 1.0)
            mv_amplitude = osc_info.get('mv_amplitude', 1.0)
            if mv_amplitude > 0.01:
                K_from_osc = pv_amplitude / mv_amplitude
            else:
                K_from_osc = K_from_range
            
            K_from_data = max(K_from_range, K_from_osc)
            K_from_data = np.clip(K_from_data, 0.1, 10.0)
        else:
            K_from_data = 1.0 / Ku if Ku > 0.01 else 1.0
        
        K_est = round(K_from_data, 4)
        self.log(f"   📊 K值估计: 范围法={pv_range/mv_range:.4f}, 最终K={K_est}")
        T1_est = round(Pu, 4)
        L_est = round(Pu / 4, 4)
        
        # 使用估算的模型参数生成 pv_model
        temp_params = (K_est, T1_est, L_est)
        pv_model = self._simulator.simulate_segmented(
            temp_params, 'FOPDT', y, u,
            reset_on_sv_change=True, sv=sv,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=True
        )
        
        # 创建 FusionResult 用于闭环验证
        temp_fusion = FusionResult(
            model_type=ModelType.FOPDT,
            K=K_est, T1=T1_est, T2=0.0, L=L_est
        )
        
        # 闭环验证
        cl_config = Config.CLOSED_LOOP
        
        sv_mean = float(np.mean(sv))
        pv_mean = float(np.mean(y))
        pv_std = float(np.std(y))
        
        sp_initial = sv_mean
        sp_step = max(pv_std * 2, 1.0)
        sp_final = sv_mean + sp_step
        pv_initial = pv_mean
        
        self.log(f"   📊 闭环仿真: SP={sp_initial:.2f}→{sp_final:.2f}, PV初值={pv_initial:.2f}")
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            temp_fusion, pid_params,
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            verbose=self._verbose
        )
        
        # 如果闭环不稳定，尝试更保守的参数
        if not is_stable:
            self.log("   ⚠️ 闭环不稳定，尝试更保守的参数...")
            
            K_approx = pv_range / mv_range if mv_range > 0.1 and pv_range > 0.01 else 1.0
            
            fallback_pid = self._get_conservative_pid_params(
                Pu, osc_info['Ku'], K_approx=K_approx, reason='data_range'
            )
            
            self.log(f"   ⚠️ 数据质量差，使用保守参数: pb={fallback_pid['pb']:.1f}, "
                    f"Kp={fallback_pid['Kp']:.4f}, Ki={fallback_pid['Ki']:.4f}")
            pid_params = fallback_pid
            
            is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
                temp_fusion, fallback_pid,
                sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
                verbose=self._verbose
            )
        
        # 计算评分
        stability_score = 10.0 if is_stable else 5.0
        if cl_metrics.overshoot > cl_config['overshoot_acceptable']:
            stability_score -= 2.0
        if cl_metrics.oscillation_count > cl_config['oscillation_count_ideal']:
            stability_score -= 1.0
        
        model_rating = round(min(10.0, max(0.0, stability_score * 0.6 + 2.0)), 2)
        
        closed_loop_info = {
            'is_stable': is_stable,
            'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot,
            'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error,
            'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio
        }
        
        return {
            'success': True,
            'model_type': 'FOPDT',
            'model_rating': model_rating,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {
                'K': K_est,
                'T1': T1_est,
                'T2': 0.0,
                'L': L_est
            },
            'pid_parameters': pid_params,
            'fitting_result': {
                'timestamp': ts.tolist(),
                'sv': sv.tolist(),
                'pv': y.tolist(),
                'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': calculate_r2(y, pv_model),
                'rmse': calculate_rmse(y, pv_model)
            },
            'fusion_info': {
                'method': 'oscillation_critical',
                'n_segments': 1,
                'consistency_score': 0.0,
                'oscillation_type': osc_info['oscillation_type'],
                'oscillation_amplitude': osc_info['amplitude']
            },
            'closed_loop_verification': closed_loop_info,
            'rating_details': {
                'stability_score': stability_score,
                'method': 'oscillation_critical'
            }
        }
