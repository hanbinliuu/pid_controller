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
from ..logger import LoggerMixin


class OscillationTuner(LoggerMixin):
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
        self._init_logger(verbose)
        self._pid_calculator = pid_calculator
        self._simulator = simulator
        self._epsilon = Config.EPSILON
    
    def detect_valve_issues(self, mv: np.ndarray, pv: np.ndarray, dt: float = 1.0) -> Dict[str, Any]:
        """
        检测阀门问题（死区、粘滞、饱和）
        
        Args:
            mv: 操作变量数组
            pv: 过程变量数组
            dt: 采样周期
        
        Returns:
            阀门问题检测结果字典
        """
        result = {
            'has_deadband': False,
            'has_stiction': False,
            'has_saturation': False,
            'deadband_size': 0.0,
            'stiction_severity': 0.0,
            'saturation_ratio': 0.0,
            'issues_detected': []
        }
        
        if len(mv) < 20 or len(pv) < 20:
            return result
        
        try:
            mv_diff = np.diff(mv)
            pv_diff = np.diff(pv)
            
            # 1. 死区检测：MV变化但PV无响应
            mv_moving = np.abs(mv_diff) > 0.1 * np.std(mv_diff)
            pv_response = np.abs(pv_diff) > 0.05 * np.std(pv_diff)
            
            if np.sum(mv_moving) > 10:
                # 计算MV变化时PV无响应的比例
                no_response_ratio = np.sum(mv_moving & ~pv_response) / np.sum(mv_moving)
                if no_response_ratio > 0.3:
                    result['has_deadband'] = True
                    result['deadband_size'] = no_response_ratio
                    result['issues_detected'].append(f'死区({no_response_ratio:.0%})')
            
            # 2. 粘滞检测：MV方向改变时PV响应延迟或卡顿
            mv_sign_changes = np.where(np.diff(np.sign(mv_diff)) != 0)[0]
            if len(mv_sign_changes) > 3:
                stiction_count = 0
                for idx in mv_sign_changes[:-1]:
                    if idx + 5 < len(pv_diff):
                        # 检查方向改变后5个点内PV是否有响应
                        pv_response_window = np.abs(pv_diff[idx:idx+5])
                        if np.max(pv_response_window) < 0.1 * np.std(pv_diff):
                            stiction_count += 1
                
                stiction_ratio = stiction_count / len(mv_sign_changes)
                if stiction_ratio > 0.4:
                    result['has_stiction'] = True
                    result['stiction_severity'] = stiction_ratio
                    result['issues_detected'].append(f'粘滞({stiction_ratio:.0%})')
            
            # 3. 饱和检测：MV在极值附近但PV不再响应
            mv_range = np.ptp(mv)
            if mv_range > 0.1:
                mv_normalized = (mv - np.min(mv)) / mv_range
                # 检测MV在0-5%或95-100%范围的时间比例
                at_limits = (mv_normalized < 0.05) | (mv_normalized > 0.95)
                saturation_ratio = np.sum(at_limits) / len(mv)
                
                if saturation_ratio > 0.15:
                    # 进一步检查饱和时PV是否失去响应
                    # 确保数组长度匹配
                    at_limits_diff = at_limits[:-1]  # 与pv_diff长度匹配
                    if np.sum(at_limits_diff) > 10 and len(pv_diff) == len(at_limits_diff):
                        pv_at_limits = pv_diff[at_limits_diff]
                        pv_normal = pv_diff[~at_limits_diff]
                        if len(pv_normal) > 0 and np.std(pv_normal) > self._epsilon:
                            response_reduction = np.std(pv_at_limits) / np.std(pv_normal)
                            if response_reduction < 0.5:
                                result['has_saturation'] = True
                                result['saturation_ratio'] = saturation_ratio
                                result['issues_detected'].append(f'饱和({saturation_ratio:.0%})')
            
        except Exception as e:
            self.log(f"   ⚠️ 阀门问题检测失败: {e}")
        
        return result
    
    def try_oscillation_tuning(self, segments: List[HistoricalData], 
                               segment_results: List[SegmentResult],
                               current_pid: Dict = None,
                               force: bool = False) -> Optional[Dict]:
        """
        尝试使用振荡分析进行临界法整定
        
        当检测到高振荡数据且常规模型拟合失败时，使用振荡特征进行PID整定
        
        Args:
            segments: 扰动段数据列表
            segment_results: 各段拟合结果
            current_pid: 当前PID参数（用于校正Ku估计）
            force: 是否强制使用振荡整定（闭环不稳定时使用）
        
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
                    # 如果最佳模型T1过小，检查是否有其他模型T1合理
                    # 优先检查简单模型（FOPDT, FO）
                    has_valid_alternative = False
                    for alt_model in ['FOPDT', 'FO']:
                        if alt_model in result.model_results:
                            alt_params = result.model_results[alt_model]
                            alt_T1 = alt_params.get('T1', None)
                            alt_r2 = alt_params.get('r2', 0)  # 注意：键名是r2不是r_squared
                            # 如果简单模型T1合理（>0.8s）且R²可接受，认为拟合有效
                            # 简单模型允许更小的T1，因为它们更稳健
                            if alt_T1 is not None and alt_T1 >= 0.8 and alt_r2 >= r2_failure_threshold:
                                has_valid_alternative = True
                                self.log(f"   ℹ️ 段{i+1}: {result.best_model}的T1={T1:.2f}s过小，"
                                        f"但{alt_model}的T1={alt_T1:.2f}s(R²={alt_r2:.2f})有效")
                                break
                    
                    if not has_valid_alternative:
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
            
            # 条件2: 成功段数据量太小且拟合质量不够好
            # 如果R²足够高（>0.6），即使数据点较少也可信任
            best_success_r2 = max(r.best_r2 for _, _, r in successful_segments) if successful_segments else 0
            min_points_threshold = 300 if best_success_r2 >= 0.6 else 500  # 高R²时降低点数要求
            if success_total_points < min_points_threshold:
                force_oscillation_tuning = True
                force_reason = f"成功段数据量仅{success_total_points}点<{min_points_threshold}"
            
            # 条件3: 平均振荡比过高且有多个失败段
            if avg_osc_ratio > 0.7 and failed_segments >= total_segments // 2:
                force_oscillation_tuning = True
                force_reason = f"平均振荡比{avg_osc_ratio:.2f}>0.7且{failed_segments}/{total_segments}段失败"
        
        # 如果有成功拟合的段且不需要强制临界法，使用常规流程
        # 但如果 force=True（闭环不稳定时的fallback），跳过此检查
        if successful_segments and not force_oscillation_tuning and not force:
            self.log(f"\n📊 有 {len(successful_segments)} 个段拟合成功，使用常规模型融合流程")
            return None
        
        if force:
            self.log(f"\n🔄 强制使用振荡整定（闭环验证不稳定）")
        
        if force_oscillation_tuning:
            self.log(f"\n⚠️ 强制使用临界法整定: {force_reason}")
        
        # 如果 force=True，即使没有"振荡失败段"也尝试分析所有段
        if not oscillating_segments:
            if force and segments:
                # 强制模式：分析所有段
                self.log(f"\n🔄 强制模式：分析所有 {len(segments)} 个段")
                oscillating_segments = [(i, seg, result) for i, (seg, result) 
                                       in enumerate(zip(segments, segment_results))]
            else:
                return None  # 没有符合条件的振荡段
        else:
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
                
                # 从配置读取阈值（通用相对指标）
                osc_cfg = Config.OSCILLATION_TUNING
                ku_k_ratio_high = osc_cfg.get('ku_k_ratio_high', 20.0)
                ku_k_ratio_low = osc_cfg.get('ku_k_ratio_low', 0.5)
                low_gain_th = osc_cfg.get('low_gain_threshold', 0.05)
                ku_high_th = osc_cfg.get('ku_high_threshold', 50.0)
                ku_low_th = osc_cfg.get('ku_low_threshold', 0.1)
                
                # 计算Ku/K比值（相对指标，更通用）
                ku_k_ratio = Ku / apparent_gain if apparent_gain > 0.01 else float('inf')
                self.log(f"   📊 增益检查: K={apparent_gain:.4f}, Ku={Ku:.3f}, Ku/K={ku_k_ratio:.2f}")
                
                # 使用相对指标判断（优先）
                # 条件1: Ku/K比值过大（临界增益相对于过程增益过大）
                if ku_k_ratio > ku_k_ratio_high:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku/K={ku_k_ratio:.1f}>{ku_k_ratio_high}(临界增益相对过大)，使用保守参数")
                    # 诊断：Ku估计可能不可靠，系统可能已在振荡边缘
                    if ku_k_ratio > 50:
                        self.log(f"   💡 诊断: Ku估计可能不可靠，建议先手动降低Kp至当前值的50%后再整定")
                # 条件2: Ku/K比值过小（临界增益估计可能不可靠）
                elif ku_k_ratio < ku_k_ratio_low:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku/K={ku_k_ratio:.2f}<{ku_k_ratio_low}(临界增益相对过小)，使用保守参数")
                # 兜底：绝对阈值检查（极端情况）
                elif apparent_gain < low_gain_th:
                    use_conservative = True
                    self.log(f"   ⚠️ K={apparent_gain:.4f}<{low_gain_th}(极低增益)，使用保守参数")
                elif Ku > ku_high_th:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku={Ku:.1f}>{ku_high_th}(极高临界增益)，使用保守参数")
                elif Ku < ku_low_th:
                    use_conservative = True
                    self.log(f"   ⚠️ Ku={Ku:.3f}<{ku_low_th}(极低临界增益)，使用保守参数")
        
        # 获取最佳段的振荡比和数据质量（用于自适应调整）
        best_seg_idx = best_analysis['segment_idx']
        best_seg_result = segment_results[best_seg_idx] if best_seg_idx < len(segment_results) else None
        oscillation_ratio = best_seg_result.oscillation_ratio if best_seg_result else 0.0
        data_quality = best_seg_result.quality_score if best_seg_result else 0.5
        nonlinearity = best_seg_result.nonlinearity_score if best_seg_result else 0.0
        
        # 阀门问题检测
        valve_issues = {}
        if best_seg is not None:
            valve_issues = self.detect_valve_issues(best_seg.mv, best_seg.pv)
            if valve_issues['issues_detected']:
                self.log(f"   ⚠️ 阀门问题检测: {', '.join(valve_issues['issues_detected'])}")
        
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
            oscillation_ratio=oscillation_ratio,
            data_quality=data_quality,
            nonlinearity=nonlinearity,
            valve_issues=valve_issues
        )
        
        if pid_params is None:
            self.log("   ⚠️ 临界法整定失败")
            return None
        
        self.log(f"   ✅ 临界法整定成功:")
        self.log(f"      Pu={best_analysis['osc_info']['Pu']:.1f}s, Ku={pid_params['Ku']:.3f}")
        self.log(f"      Kp={pid_params['Kp']:.4f}, Ki={pid_params['Ki']:.4f}, Kd={pid_params['Kd']:.4f}")
        self.log(f"      方法: {pid_params['method']}")
        
        return {
            'success': True,  # 振荡整定成功标志
            'pid_params': pid_params,
            'oscillation_info': best_analysis['osc_info'],
            'segment_idx': best_analysis['segment_idx'],
            'method': 'oscillation_critical',
            'data_quality': data_quality,
            'nonlinearity': nonlinearity,
            'valve_issues': valve_issues
        }
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, 
                                      K_approx: float = 1.0,
                                      reason: str = 'generic',
                                      oscillation_ratio: float = 0.0,
                                      data_quality: float = 0.5,
                                      nonlinearity: float = 0.0,
                                      valve_issues: Dict = None) -> Dict[str, Any]:
        """
        获取保守PID参数（动态计算pb，借鉴大模型调参经验）
        
        改进点（基于大模型调参经验）：
        1. 严重振荡时使用更保守的pb
        2. 自适应添加微分作用抑制振荡
        3. pb范围扩展，允许更保守的参数
        4. 数据质量越差，参数越保守
        5. 考虑阀门问题（死区、粘滞、卡涩）
        
        Args:
            Pu: 临界周期
            Ku: 临界增益
            K_approx: 估计的过程增益
            reason: 使用保守参数的原因
            oscillation_ratio: 振荡比（用于自适应调整）
            data_quality: 数据质量评分 (0-1)，越低越需要保守
            nonlinearity: 非线性程度 (0-1)
            valve_issues: 阀门问题检测结果
        
        Returns:
            保守PID参数字典
        """
        if valve_issues is None:
            valve_issues = {}
        osc_config = Config.OSCILLATION_TUNING
        
        # ========== 动态计算 pb（渐进式策略，更通用） ==========
        # 1. 基于过程增益的基础 pb
        pb_from_k_factor = osc_config.get('pb_from_k_factor', 1.5)
        if K_approx > 0.01:
            pb_from_K = 100.0 * K_approx * pb_from_k_factor
        else:
            pb_from_K = 80.0  # 增益过小时的默认值
        
        # 2. 基于临界参数的 pb（Ziegler-Nichols 变体）
        kp_from_ku_factor = osc_config.get('kp_from_ku_factor', 0.2)
        if Ku > 0.1:
            Kp_from_Ku = kp_from_ku_factor * Ku
            pb_from_Ku = 100.0 / max(Kp_from_Ku, 0.1)
        else:
            pb_from_Ku = 100.0  # Ku 不可靠时的默认值
        
        # 3. 基于临界周期的调整因子（从配置读取）
        pu_thresholds = osc_config.get('slow_system_pu_thresholds', [30.0, 15.0])
        slow_factors = osc_config.get('slow_system_factors', [1.3, 1.15, 1.0])
        slow_factor = slow_factors[-1]  # 默认值
        for i, threshold in enumerate(pu_thresholds):
            if Pu > threshold:
                slow_factor = slow_factors[i]
                break
        
        # 4. 综合计算：取较大值（更保守）并应用慢系统因子
        pb_base = max(pb_from_K, pb_from_Ku) * slow_factor
        
        # 5. 根据原因微调（从配置读取）
        high_gain_factor = osc_config.get('high_gain_extra_factor', 1.1)
        if reason == 'high_gain':
            pb_base *= high_gain_factor
        
        # 6. 数据质量因子（从配置读取阈值）
        quality_threshold = osc_config.get('quality_adjustment_threshold', 0.5)
        quality_adj_factor = osc_config.get('quality_adjustment_factor', 0.6)
        if data_quality < quality_threshold:
            quality_factor = 1.0 + (quality_threshold - data_quality) * quality_adj_factor
            pb_base *= quality_factor
            self.log(f"   📊 数据质量调整: 质量={data_quality:.2f}, 因子=×{quality_factor:.2f}")
        
        # 7. 非线性因子（从配置读取阈值）
        nonlin_threshold = osc_config.get('nonlinearity_threshold', 0.5)
        nonlin_adj_factor = osc_config.get('nonlinearity_factor', 0.4)
        if nonlinearity > nonlin_threshold:
            nonlin_factor = 1.0 + (nonlinearity - nonlin_threshold) * nonlin_adj_factor
            pb_base *= nonlin_factor
            self.log(f"   📊 非线性调整: 非线性={nonlinearity:.2f}, 因子=×{nonlin_factor:.2f}")
        
        # 8. 阀门问题因子（从配置读取）
        valve_deadband_f = osc_config.get('valve_deadband_factor', 1.15)
        valve_stiction_f = osc_config.get('valve_stiction_factor', 1.2)
        valve_saturation_f = osc_config.get('valve_saturation_factor', 1.1)
        valve_factor = 1.0
        if valve_issues.get('has_deadband', False):
            valve_factor *= valve_deadband_f
            self.log(f"   ⚠️ 检测到阀门死区，增加保守度 ×{valve_deadband_f}")
        if valve_issues.get('has_stiction', False):
            valve_factor *= valve_stiction_f
            self.log(f"   ⚠️ 检测到阀门粘滞，增加保守度 ×{valve_stiction_f}")
        if valve_issues.get('has_saturation', False):
            valve_factor *= valve_saturation_f
            self.log(f"   ⚠️ 检测到阀门饱和，增加保守度 ×{valve_saturation_f}")
        pb_base *= valve_factor
        
        # ========== 渐进式振荡保守调整（核心改进，使用渐近函数） ==========
        # 使用渐近函数避免高振荡时pb线性爆炸
        # pb_multiplier = 1 + k * sqrt(osc - start)，增长放缓
        pb_gradient = osc_config.get('pb_gradient', 2.0)
        pb_osc_start = osc_config.get('pb_oscillation_start', 0.4)
        base_safety_factor = osc_config.get('critical_method_safety_factor', 1.4)
        
        # 自适应安全系数（从配置读取阈值和斜率）
        safety_base = osc_config.get('safety_factor_base', 1.4)
        safety_thresholds = osc_config.get('safety_factor_thresholds', [0.5, 0.7, 0.85])
        safety_slopes = osc_config.get('safety_factor_slopes', [0.5, 1.0, 2.0])
        
        if oscillation_ratio < safety_thresholds[0]:
            safety_factor = safety_base
        elif oscillation_ratio < safety_thresholds[1]:
            safety_factor = safety_base + (oscillation_ratio - safety_thresholds[0]) * safety_slopes[0]
        elif oscillation_ratio < safety_thresholds[2]:
            prev_value = safety_base + (safety_thresholds[1] - safety_thresholds[0]) * safety_slopes[0]
            safety_factor = prev_value + (oscillation_ratio - safety_thresholds[1]) * safety_slopes[1]
        else:
            prev_value = safety_base + (safety_thresholds[1] - safety_thresholds[0]) * safety_slopes[0]
            prev_value += (safety_thresholds[2] - safety_thresholds[1]) * safety_slopes[1]
            safety_factor = prev_value + (oscillation_ratio - safety_thresholds[2]) * safety_slopes[2]
        
        # 计算综合保守乘数（将安全系数合并，避免多重乘数叠加）
        total_multiplier = safety_factor  # 自适应安全系数
        
        if oscillation_ratio > pb_osc_start:
            # 使用平方根函数，高振荡时增长放缓
            # effective_osc ∈ [0, 0.6]（振荡比最高1.0）
            effective_osc = oscillation_ratio - pb_osc_start
            # sqrt(0.6) ≈ 0.77，乘以gradient=1.0 → 0.77
            osc_multiplier = 1.0 + np.sqrt(effective_osc) * pb_gradient
            total_multiplier *= osc_multiplier
            
            # 限制总乘数上限（从配置读取）
            max_mult_normal = osc_config.get('max_multiplier_normal', 2.5)
            max_mult_high = osc_config.get('max_multiplier_high_osc', 3.0)
            if oscillation_ratio > safety_thresholds[2]:
                max_multiplier = max_mult_high
            else:
                max_multiplier = max_mult_normal
            if total_multiplier > max_multiplier:
                self.log(f"   ⚠️ 总乘数{total_multiplier:.2f}超限，限制为{max_multiplier}")
                total_multiplier = max_multiplier
            
            self.log(f"   📊 渐进式保守调整: 振荡比={oscillation_ratio:.2f}, "
                    f"安全系数={safety_factor:.2f}, osc乘数={osc_multiplier:.2f}, 总乘数={total_multiplier:.2f}")
        else:
            self.log(f"   📊 基础安全系数: ×{safety_factor:.2f}")
        
        pb_base *= total_multiplier
        
        # 6. 限制在合理范围（动态调整边界）
        pb_min_base = osc_config.get('pb_min', 80.0)
        pb_max = osc_config.get('pb_max', 600.0)
        
        # 动态调整pb边界（基于过程增益K）
        # 小增益系统需要更高的pb下限，大增益系统可以更激进
        # pb_min = pb_min_base * (1 + factor/K), K越小pb下限越高
        pb_k_factor = osc_config.get('pb_k_adjustment_factor', 0.3)
        if K_approx > 0.01:
            pb_min_dynamic = pb_min_base * (1.0 + pb_k_factor / K_approx)
            pb_min_dynamic = min(pb_min_dynamic, 400.0)  # 绝对上限400%
        else:
            pb_min_dynamic = 400.0
        pb_min = max(pb_min_base, pb_min_dynamic)
        
        # 优化：当reason为low_gain时（Ku/K比值过大），进一步提高pb下限
        # 这种情况说明系统可能已经在振荡边缘，需要更保守的参数
        if reason == 'low_gain':
            ku_k_extreme_factor = osc_config.get('ku_k_extreme_pb_factor', 1.5)
            pb_min = pb_min * ku_k_extreme_factor
            pb_min = min(pb_min, 500.0)  # 绝对上限500%
            self.log(f"   📊 Ku/K异常模式: pb下限={pb_min:.0f}% (K={K_approx:.3f})")
        else:
            self.log(f"   📊 动态pb下限: {pb_min:.0f}% (K={K_approx:.3f})")
        
        pb_safe = np.clip(pb_base, pb_min, pb_max)
        
        self.log(f"   📊 动态pb计算: K={K_approx:.3f}→pb={pb_from_K:.1f}, "
                f"Ku={Ku:.3f}→pb={pb_from_Ku:.1f}, Pu={Pu:.1f}s(×{slow_factor}), "
                f"最终pb={pb_safe:.1f}")
        
        conservative_Kp = 100.0 / pb_safe
        
        # ========== 自适应 Ti 计算（从配置读取参数） ==========
        ti_min_base = osc_config.get('ti_min_base', 1.5)
        base_Ti = max(Pu / 2, ti_min_base) if Pu > 0 else 2.0
        
        # 振荡调整因子（从配置读取）
        ti_osc_start = osc_config.get('ti_osc_start', 0.6)
        ti_osc_factor = osc_config.get('ti_osc_factor', 0.5)
        if oscillation_ratio > ti_osc_start:
            ti_multiplier = 1.0 + np.sqrt(oscillation_ratio - ti_osc_start) * ti_osc_factor
        else:
            ti_multiplier = 1.0
        
        # 慢系统调整（从配置读取）
        ti_slow_thresholds = osc_config.get('ti_slow_pu_thresholds', [20.0, 10.0])
        ti_slow_factors = osc_config.get('ti_slow_factors', [1.1, 1.05, 1.0])
        for i, threshold in enumerate(ti_slow_thresholds):
            if Pu > threshold:
                ti_multiplier *= ti_slow_factors[i]
                break
        
        conservative_Ti = base_Ti * ti_multiplier
        # Ti范围限制（从配置读取）
        ti_range = osc_config.get('ti_range', [1.5, 10.0])
        conservative_Ti = np.clip(conservative_Ti, ti_range[0], ti_range[1])
        conservative_Ki = conservative_Kp / conservative_Ti
        
        # ========== 自适应 Td 计算（基于Pu和振荡比） ==========
        conservative_Kd = 0.0
        conservative_Td = 0.0
        enable_derivative = osc_config.get('enable_adaptive_derivative', True)
        derivative_threshold = osc_config.get('derivative_oscillation_threshold', 0.5)
        
        if enable_derivative and oscillation_ratio > derivative_threshold:
            # 基础Td（从配置读取）
            td_base_divisor = osc_config.get('td_base_divisor', 8.0)
            base_Td = Pu / td_base_divisor if Pu > 0 else 0.5
            
            # Td乘数（从配置读取）
            td_mult_factor = osc_config.get('td_multiplier_factor', 1.5)
            effective_osc = oscillation_ratio - derivative_threshold
            td_multiplier = 1.0 + np.sqrt(effective_osc) * td_mult_factor
            
            conservative_Td = base_Td * td_multiplier
            # Td范围限制（从配置读取）
            td_range = osc_config.get('td_range', [0.3, 3.0])
            conservative_Td = np.clip(conservative_Td, td_range[0], td_range[1])
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
                                 time_range: Dict, tuning_windows: List,
                                 segments: List = None, segment_results: List = None) -> Dict[str, Any]:
        """
        构建振荡分析整定的输出结果
        
        Args:
            osc_result: try_oscillation_tuning 的返回结果
            hist_data: 历史数据
            time_range: 时间范围
            tuning_windows: 整定窗口列表
            segments: 段数据列表（用于可视化）
            segment_results: 段结果列表（用于可视化）
        
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
            
            # 获取数据质量、非线性和阀门问题信息（用于保守策略）
            fallback_data_quality = osc_result.get('data_quality', 0.5)
            fallback_nonlinearity = osc_result.get('nonlinearity', 0.0)
            fallback_valve_issues = osc_result.get('valve_issues', {})
            fallback_osc_ratio = osc_info.get('oscillation_ratio', 0.5)
            
            fallback_pid = self._get_conservative_pid_params(
                Pu, osc_info['Ku'], K_approx=K_approx, reason='data_range',
                oscillation_ratio=fallback_osc_ratio,
                data_quality=fallback_data_quality,
                nonlinearity=fallback_nonlinearity,
                valve_issues=fallback_valve_issues
            )
            
            self.log(f"   ⚠️ 数据质量差，使用保守参数: pb={fallback_pid['pb']:.1f}, "
                    f"Kp={fallback_pid['Kp']:.4f}, Ki={fallback_pid['Ki']:.4f}")
            pid_params = fallback_pid
            
            is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
                temp_fusion, fallback_pid,
                sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
                verbose=self._verbose
            )
        
        # ========== 综合评分策略（更精确反映参数可用性） ==========
        rating_details = {}
        
        # 1. 闭环稳定性评分 (0-10) - 权重 35%
        stability_score = 6.0 if is_stable else 2.0
        if is_stable:
            # 超调量评分
            if cl_metrics.overshoot <= 5:
                stability_score += 1.5
            elif cl_metrics.overshoot <= 15:
                stability_score += 1.0
            elif cl_metrics.overshoot <= 30:
                stability_score += 0.5
            elif cl_metrics.overshoot > 50:
                stability_score -= 1.0
            
            # 调节时间评分
            if cl_metrics.settling_time < float('inf'):
                if cl_metrics.settling_time <= 30:
                    stability_score += 1.0
                elif cl_metrics.settling_time <= 60:
                    stability_score += 0.5
                elif cl_metrics.settling_time > 120:
                    stability_score -= 0.5
            
            # 振荡次数
            if cl_metrics.oscillation_count <= 2:
                stability_score += 0.5
            elif cl_metrics.oscillation_count > 5:
                stability_score -= 0.5
        
        stability_score = min(10.0, max(0.0, stability_score))
        rating_details['stability_score'] = round(stability_score, 2)
        
        # 2. 数据质量评分 (0-10) - 权重 25%
        # 综合考虑振荡比、原始数据质量、非线性
        oscillation_ratio = osc_info.get('oscillation_ratio', 0.5)
        raw_data_quality = osc_result.get('data_quality', 0.5)
        nonlinearity = osc_result.get('nonlinearity', 0.0)
        
        # 基于振荡比的评分
        if oscillation_ratio < 0.4:
            osc_score = 8.0
        elif oscillation_ratio < 0.6:
            osc_score = 7.0 - (oscillation_ratio - 0.4) * 5
        elif oscillation_ratio < 0.8:
            osc_score = 6.0 - (oscillation_ratio - 0.6) * 7.5
        else:
            # 极高振荡(>0.8)，数据质量较差
            osc_score = 4.5 - (oscillation_ratio - 0.8) * 15  # 加大惩罚
        
        # 原始数据质量因子（quality_score < 0.4 时开始扣分）
        quality_penalty = max(0, (0.4 - raw_data_quality) * 3)  # 最多扣1.2分
        
        # 非线性因子（nonlinearity > 0.5 时开始扣分）
        nonlin_penalty = max(0, (nonlinearity - 0.5) * 2)  # 最多扣1分
        
        data_quality_score = osc_score - quality_penalty - nonlin_penalty
        data_quality_score = max(1.0, min(8.0, data_quality_score))  # 上限为8，下限为1
        
        rating_details['data_quality_score'] = round(data_quality_score, 2)
        rating_details['oscillation_ratio'] = round(oscillation_ratio, 2)
        rating_details['raw_data_quality'] = round(raw_data_quality, 2)
        rating_details['nonlinearity'] = round(nonlinearity, 2)
        
        # 3. 参数边界距离评分 (0-10) - 权重 20%
        # pb距离边界越近，得分越低
        pb = pid_params.get('pb', 200)
        pb_min = Config.OSCILLATION_TUNING.get('pb_min', 120.0)
        pb_max = Config.OSCILLATION_TUNING.get('pb_max', 600.0)
        pb_range = pb_max - pb_min
        pb_margin = min(pb - pb_min, pb_max - pb) / (pb_range / 2)  # 0~1，离中间越近越好
        
        boundary_score = 5.0 + pb_margin * 5.0  # 5~10分
        if pb <= pb_min * 1.05 or pb >= pb_max * 0.95:
            boundary_score = 3.0  # 触边界扣分
        
        # Ti边界检查
        Ti = pid_params.get('Ti', 2.5)
        if Ti <= 1.6 or Ti >= 9.5:  # 接近[1.5, 10.0]边界
            boundary_score -= 1.0
        
        boundary_score = min(10.0, max(0.0, boundary_score))
        rating_details['boundary_score'] = round(boundary_score, 2)
        rating_details['pb'] = round(pb, 2)
        
        # 4. 整定方法评分 (0-10) - 权重 20%
        # 临界法本身是fallback方法，基础分较低
        method = pid_params.get('method', 'unknown')
        if 'low_gain' in method or 'high_gain' in method:
            method_score = 5.0  # 极端增益场景
        elif 'oscillation' in method:
            method_score = 6.0  # 正常振荡整定
        else:
            method_score = 5.5
        
        # 有微分作用时加分（有助于抑制振荡）
        if pid_params.get('Kd', 0) > 0:
            method_score += 0.5
        
        rating_details['method_score'] = round(method_score, 2)
        rating_details['method'] = method
        
        # ========== 综合评分 ==========
        weights = {
            'stability': 0.35,
            'data_quality': 0.25,
            'boundary': 0.20,
            'method': 0.20
        }
        
        model_rating = (
            weights['stability'] * stability_score +
            weights['data_quality'] * data_quality_score +
            weights['boundary'] * boundary_score +
            weights['method'] * method_score
        )
        
        # 特殊情况限制
        warnings = []
        
        if not is_stable:
            model_rating = min(model_rating, 4.0)  # 不稳定最高4分
            warnings.append('闭环仿真不稳定')
        
        if oscillation_ratio > 0.9:
            model_rating = min(model_rating, 6.0)  # 极高振荡最高6分（从6.5降低）
            warnings.append(f'极高振荡({oscillation_ratio:.0%})，建议人工排查根因')
        elif oscillation_ratio > 0.85:
            model_rating = min(model_rating, 6.5)
            warnings.append(f'高振荡({oscillation_ratio:.0%})')
        
        if pb <= pb_min * 1.02 or pb >= pb_max * 0.98:
            model_rating = min(model_rating, 5.5)  # 触边界最高5.5分
            warnings.append('PID参数触达边界')
        
        # 数据质量极差时进一步限制
        if raw_data_quality < 0.3:
            model_rating = min(model_rating, 5.5)
            warnings.append(f'数据质量极差({raw_data_quality:.2f})')
        
        # 非线性过高时限制
        if nonlinearity > 0.6:
            model_rating = min(model_rating, 6.0)
            warnings.append(f'高非线性({nonlinearity:.2f})，可能存在阀门问题')
        
        # 阀门问题检测影响评分
        valve_issues = osc_result.get('valve_issues', {})
        if valve_issues.get('has_deadband', False):
            model_rating = min(model_rating, 6.0)
            warnings.append(f"检测到阀门死区({valve_issues.get('deadband_size', 0):.0%})")
        if valve_issues.get('has_stiction', False):
            model_rating = min(model_rating, 5.5)
            warnings.append(f"检测到阀门粘滞({valve_issues.get('stiction_severity', 0):.0%})")
        if valve_issues.get('has_saturation', False):
            model_rating = min(model_rating, 6.0)
            warnings.append(f"检测到阀门饱和({valve_issues.get('saturation_ratio', 0):.0%})")
        
        # 综合风险等级（极高振荡+低质量+阀门问题）
        risk_factors = 0
        if oscillation_ratio > 0.85:
            risk_factors += 1
        if raw_data_quality < 0.35:
            risk_factors += 1
        if valve_issues.get('has_stiction', False) or valve_issues.get('has_deadband', False):
            risk_factors += 1
        
        if risk_factors >= 2:
            model_rating = min(model_rating, 5.0)
            warnings.append('❗多重风险因素，强烈建议人工排查')
        
        model_rating = round(min(10.0, max(0.0, model_rating)), 1)
        rating_details['weights'] = weights
        rating_details['warnings'] = warnings
        rating_details['risk_factors'] = risk_factors
        rating_details['valve_issues'] = valve_issues
        
        closed_loop_info = {
            'is_stable': is_stable,
            'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot,
            'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error,
            'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio,
            # 保存仿真参数，供可视化使用
            'sp_initial': sp_initial,
            'sp_final': sp_final,
            'pv_initial': pv_initial
        }
        
        result = {
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
            'rating_details': rating_details,
            'segment_info': self._build_segment_info(segments, segment_results) if segments else []
        }
        return result
    
    def _build_segment_info(self, segments: List, segment_results: List) -> List[Dict]:
        """构建段信息用于可视化"""
        segment_info = []
        if not segments or not segment_results:
            return segment_info
        for i, (seg, result) in enumerate(zip(segments, segment_results)):
            if len(seg.timestamp) > 0:
                # 获取属性值，兼容对象和字典
                if hasattr(result, 'step_response_score'):
                    step_score = result.step_response_score
                    osc_ratio = result.oscillation_ratio
                else:
                    step_score = result.get('step_response_score', 0.5)
                    osc_ratio = result.get('oscillation_ratio', 0.5)
                
                is_tuning = (step_score >= 0.5 and osc_ratio < 0.5)
                segment_info.append({
                    'index': i,
                    'start_time': int(seg.timestamp[0]),
                    'end_time': int(seg.timestamp[-1]),
                    'data_points': len(seg.pv),
                    'step_response_score': round(step_score, 2),
                    'oscillation_ratio': round(osc_ratio, 2),
                    'type': 'tuning' if is_tuning else 'oscillation'
                })
        return segment_info
