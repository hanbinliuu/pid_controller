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
"""

import numpy as np
from typing import List, Dict, Any, Optional, Tuple

from ..types import ValveIssues, ConservativePIDParams

from ...config import Config, ModelType
from ...data_models import SegmentResult, HistoricalData, FusionResult
from ...utils import calculate_r2, calculate_rmse
from ...logger import LoggerMixin
from ..strategies.loop_type_strategies import get_loop_strategy, LoopTypeStrategy
from .conservative_pid import ConservativePIDCalculator
from .oscillation_rating import OscillationRatingCalculator


class OscillationTuner(LoggerMixin):
    """振荡数据整定器"""
    
    def __init__(self, pid_calculator, simulator, verbose: bool = False, 
                 llm_client=None, loop_type: str = "", loop_name: str = ""):
        self._init_logger(verbose)
        self._pid_calculator = pid_calculator
        self._simulator = simulator
        self._epsilon = Config.EPSILON
        
        self._llm_client = llm_client
        self._llm_advisor = None
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        
        self._conservative_pid_calculator = ConservativePIDCalculator(
            verbose=verbose, llm_client=llm_client, 
            loop_type=loop_type, loop_name=loop_name
        )
        self._rating_calculator = OscillationRatingCalculator()
        
        if llm_client is not None:
            self._init_llm_advisor(llm_client)
    
    def set_llm_client(self, llm_client, loop_type: str = "", loop_name: str = ""):
        """设置 LLM 客户端"""
        self._llm_client = llm_client
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        self._init_llm_advisor(llm_client)
        self._conservative_pid_calculator.set_llm_client(llm_client, loop_type, loop_name)
    
    def _init_llm_advisor(self, llm_client):
        """初始化 LLM 顾问"""
        try:
            from ..strategies.llm_conservative_advisor import LLMOscillationTuningAdvisor
            self._llm_advisor = LLMOscillationTuningAdvisor(llm_client=llm_client, verbose=self._verbose)
        except ImportError:
            self._llm_advisor = None

    def detect_valve_issues(self, mv: np.ndarray, pv: np.ndarray, dt: float = 1.0) -> Dict[str, Any]:
        """检测阀门问题（死区、粘滞、饱和）"""
        result = {
            'has_deadband': False, 'has_stiction': False, 'has_saturation': False,
            'deadband_size': 0.0, 'stiction_severity': 0.0, 'saturation_ratio': 0.0,
            'issues_detected': []
        }
        
        if len(mv) < 20 or len(pv) < 20:
            return result
        
        try:
            mv_diff = np.diff(mv)
            pv_diff = np.diff(pv)
            
            # 死区检测
            mv_moving = np.abs(mv_diff) > 0.1 * np.std(mv_diff)
            pv_response = np.abs(pv_diff) > 0.05 * np.std(pv_diff)
            
            if np.sum(mv_moving) > 10:
                no_response_ratio = np.sum(mv_moving & ~pv_response) / np.sum(mv_moving)
                if no_response_ratio > 0.3:
                    result['has_deadband'] = True
                    result['deadband_size'] = no_response_ratio
                    result['issues_detected'].append(f'死区({no_response_ratio:.0%})')
            
            # 粘滞检测
            mv_sign_changes = np.where(np.diff(np.sign(mv_diff)) != 0)[0]
            if len(mv_sign_changes) > 3:
                stiction_count = 0
                for idx in mv_sign_changes[:-1]:
                    if idx + 5 < len(pv_diff):
                        pv_response_window = np.abs(pv_diff[idx:idx+5])
                        if np.max(pv_response_window) < 0.1 * np.std(pv_diff):
                            stiction_count += 1
                stiction_ratio = stiction_count / len(mv_sign_changes)
                if stiction_ratio > 0.4:
                    result['has_stiction'] = True
                    result['stiction_severity'] = stiction_ratio
                    result['issues_detected'].append(f'粘滞({stiction_ratio:.0%})')
            
            # 饱和检测
            mv_range = np.ptp(mv)
            if mv_range > 0.1:
                mv_normalized = (mv - np.min(mv)) / mv_range
                at_limits = (mv_normalized < 0.05) | (mv_normalized > 0.95)
                saturation_ratio = np.sum(at_limits) / len(mv)
                if saturation_ratio > 0.15:
                    at_limits_diff = at_limits[:-1]
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
    
    def _calculate_envelope_ratio(self, pv: np.ndarray) -> float:
        """计算振荡包络比"""
        if len(pv) < 20:
            return 0.0
        pv_range = np.ptp(pv)
        if pv_range < self._epsilon:
            return 0.0
        window = max(5, len(pv) // 20)
        y_upper = np.array([np.max(pv[max(0,i-window):min(len(pv),i+window+1)]) for i in range(len(pv))])
        y_lower = np.array([np.min(pv[max(0,i-window):min(len(pv),i+window+1)]) for i in range(len(pv))])
        envelope_width = np.median(y_upper - y_lower)
        return float(np.clip(envelope_width / pv_range, 0.0, 1.0))
    
    def _fuse_oscillation_features(self, oscillation_analyses: List[Dict]) -> tuple:
        """
        多振荡段特征融合
        
        使用中位数融合多个振荡段的 Pu 和 Ku，提高鲁棒性。
        中位数比平均值更能抵抗单个异常段的影响。
        
        Args:
            oscillation_analyses: 振荡分析结果列表，每个包含 osc_info
            
        Returns:
            (fused_Pu, fused_Ku): 融合后的极限周期和极限增益
        """
        Pu_values = []
        Ku_values = []
        
        for analysis in oscillation_analyses:
            osc_info = analysis.get('osc_info', {})
            Pu = osc_info.get('Pu', 0)
            Ku = osc_info.get('Ku', 0)
            
            # 只收集有效的 Pu/Ku 值
            if Pu > 0.1:  # Pu 至少 0.1s
                Pu_values.append(Pu)
            if Ku > 0.01:  # Ku 至少 0.01
                Ku_values.append(Ku)
        
        # 使用中位数融合
        fused_Pu = float(np.median(Pu_values)) if Pu_values else None
        fused_Ku = float(np.median(Ku_values)) if Ku_values else None
        
        return fused_Pu, fused_Ku

    def try_oscillation_tuning(self, segments: List[HistoricalData], 
                               segment_results: List[SegmentResult],
                               current_pid: Dict = None,
                               force: bool = False) -> Optional[Dict]:
        """尝试使用振荡分析进行临界法整定"""
        osc_config = Config.OSCILLATION_TUNING
        osc_ratio_threshold = osc_config['oscillation_ratio_threshold']
        r2_failure_threshold = osc_config['r2_failure_threshold']
        
        successful_segments = []
        oscillating_segments = []
        
        for i, (seg, result) in enumerate(zip(segments, segment_results)):
            envelope_ratio = self._calculate_envelope_ratio(seg.pv)
            osc_score = 0.4 * result.oscillation_ratio + 0.6 * envelope_ratio
            is_oscillating = (result.oscillation_ratio > osc_ratio_threshold or 
                             envelope_ratio > 0.5 or osc_score > 0.3)
            fit_failed = result.best_r2 < r2_failure_threshold
            
            params_at_boundary = False
            if result.best_model and result.model_results:
                best_params = result.model_results.get(result.best_model, {})
                T1 = best_params.get('T1', None)
                if T1 is not None and T1 <= 1.5:
                    has_valid_alternative = False
                    for alt_model in ['FOPDT', 'FO']:
                        if alt_model in result.model_results:
                            alt_params = result.model_results[alt_model]
                            alt_T1 = alt_params.get('T1', None)
                            alt_r2 = alt_params.get('r2', 0)
                            if alt_T1 is not None and alt_T1 >= 0.8 and alt_r2 >= r2_failure_threshold:
                                has_valid_alternative = True
                                break
                    if not has_valid_alternative:
                        params_at_boundary = True
                        fit_failed = True
            
            if not fit_failed and result.best_r2 >= r2_failure_threshold:
                successful_segments.append((i, seg, result))
            if is_oscillating and fit_failed:
                oscillating_segments.append((i, seg, result))
        
        # 判断是否强制使用临界法
        total_segments = len(segment_results)
        avg_osc_ratio = np.mean([r.oscillation_ratio for r in segment_results]) if segment_results else 0
        
        force_oscillation_tuning = False
        if successful_segments and oscillating_segments:
            success_total_points = sum(len(seg.pv) for _, seg, _ in successful_segments)
            failed_total_points = sum(len(seg.pv) for _, seg, _ in oscillating_segments)
            
            if failed_total_points > 0 and success_total_points > 0:
                failure_ratio = failed_total_points / (success_total_points + failed_total_points)
                if failure_ratio > 0.8:
                    force_oscillation_tuning = True
            
            best_success_r2 = max(r.best_r2 for _, _, r in successful_segments) if successful_segments else 0
            min_points_threshold = 300 if best_success_r2 >= 0.6 else 500
            if success_total_points < min_points_threshold:
                force_oscillation_tuning = True
            
            if avg_osc_ratio > 0.7 and len(oscillating_segments) >= total_segments // 2:
                force_oscillation_tuning = True
        
        if successful_segments and not force_oscillation_tuning and not force:
            self.log(f"\n📊 有 {len(successful_segments)} 个段拟合成功，使用常规模型融合流程")
            return None
        
        if not oscillating_segments:
            if force and segments:
                oscillating_segments = [(i, seg, result) for i, (seg, result) in enumerate(zip(segments, segment_results))]
            else:
                return None
        else:
            self.log(f"\n🔄 检测到 {len(oscillating_segments)} 个高振荡拟合失败段，尝试临界法整定")
        
        # 分析振荡段
        oscillation_analyses = []
        for idx, seg, result in oscillating_segments:
            dt = 1.0
            if len(seg.timestamp) > 1:
                dt = (seg.timestamp[1] - seg.timestamp[0]) / 1000
            
            osc_info = self._pid_calculator.analyze_oscillation(seg.pv, seg.mv, dt)
            if osc_info and osc_info.get('is_valid', False):
                oscillation_analyses.append({'segment_idx': idx, 'osc_info': osc_info, 'data_points': len(seg.pv)})
        
        if not oscillation_analyses:
            self.log("   ⚠️ 无法从振荡数据中提取有效特征")
            if oscillating_segments:
                return self._generic_fallback(oscillating_segments, segments, segment_results)
            return None
        
        # 选择最佳分析结果
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
        
        # Step: 多振荡段特征融合
        # 如果有多个振荡分析结果，使用中位数融合 Pu/Ku 以提高鲁棒性
        if len(oscillation_analyses) > 1:
            fused_Pu, fused_Ku = self._fuse_oscillation_features(oscillation_analyses)
            if fused_Pu is not None and fused_Ku is not None:
                self.log(f"   📊 多振荡段融合: {len(oscillation_analyses)} 个段 → Pu={fused_Pu:.1f}s, Ku={fused_Ku:.3f}")
                # 用融合后的值替换 best_analysis 中的值
                best_analysis['osc_info'] = best_analysis['osc_info'].copy()
                best_analysis['osc_info']['Pu'] = fused_Pu
                best_analysis['osc_info']['Ku'] = fused_Ku
        
        # 检查是否需要保守参数
        use_conservative = False
        Ku = best_analysis['osc_info']['Ku']
        apparent_gain = 1.0
        
        if best_seg is not None:
            pv_range = np.ptp(best_seg.pv)
            mv_range = np.ptp(best_seg.mv)
            if mv_range > 0.1:
                apparent_gain = pv_range / mv_range
                osc_cfg = Config.OSCILLATION_TUNING
                ku_k_ratio = Ku / apparent_gain if apparent_gain > 0.01 else float('inf')
                
                if ku_k_ratio > osc_cfg.get('ku_k_ratio_high', 20.0):
                    use_conservative = True
                elif ku_k_ratio < osc_cfg.get('ku_k_ratio_low', 0.5):
                    use_conservative = True
                elif apparent_gain < osc_cfg.get('low_gain_threshold', 0.05):
                    use_conservative = True
                elif Ku > osc_cfg.get('ku_high_threshold', 50.0):
                    use_conservative = True
                elif Ku < osc_cfg.get('ku_low_threshold', 0.1):
                    use_conservative = True
        
        # 获取数据质量信息
        best_seg_idx = best_analysis['segment_idx']
        best_seg_result = segment_results[best_seg_idx] if best_seg_idx < len(segment_results) else None
        oscillation_ratio = best_seg_result.oscillation_ratio if best_seg_result else 0.0
        data_quality = best_seg_result.quality_score if best_seg_result else 0.5
        nonlinearity = best_seg_result.nonlinearity_score if best_seg_result else 0.0
        
        valve_issues = {}
        if best_seg is not None:
            valve_issues = self.detect_valve_issues(best_seg.mv, best_seg.pv)
        
        Pu = best_analysis['osc_info']['Pu']
        confidence = best_analysis['osc_info'].get('confidence', 0.5)
        reason = 'low_gain' if use_conservative else 'oscillation'
        
        pid_params = self._get_conservative_pid_params(
            Pu, Ku, K_approx=apparent_gain, reason=reason,
            oscillation_ratio=oscillation_ratio, data_quality=data_quality,
            nonlinearity=nonlinearity, valve_issues=valve_issues, confidence=confidence
        )
        
        if pid_params is None:
            return None
        
        self.log(f"   ✅ 临界法整定成功: Pu={Pu:.1f}s, Ku={pid_params['Ku']:.3f}")
        self.log(f"      Kp={pid_params['Kp']:.4f}, Ki={pid_params['Ki']:.4f}, Kd={pid_params['Kd']:.4f}")
        
        return {
            'success': True, 'pid_params': pid_params, 'oscillation_info': best_analysis['osc_info'],
            'segment_idx': best_analysis['segment_idx'], 'method': 'oscillation_critical',
            'data_quality': data_quality, 'nonlinearity': nonlinearity, 'valve_issues': valve_issues
        }
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, K_approx: float = 1.0,
                                      reason: str = 'generic', oscillation_ratio: float = 0.0,
                                      data_quality: float = 0.5, nonlinearity: float = 0.0,
                                      valve_issues: Dict = None, confidence: float = 0.5) -> Dict[str, Any]:
        """获取保守PID参数（委托给 ConservativePIDCalculator）"""
        return self._conservative_pid_calculator.calculate(
            Pu=Pu, Ku=Ku, K_approx=K_approx, reason=reason,
            oscillation_ratio=oscillation_ratio, data_quality=data_quality,
            nonlinearity=nonlinearity, valve_issues=valve_issues, confidence=confidence
        )
    
    def _calculate_oscillation_rating(self, is_stable: bool, cl_metrics: Any,
                                       pid_params: Dict, osc_info: Dict,
                                       osc_result: Dict) -> Tuple[float, Dict, List[str]]:
        """计算振荡整定的综合评分（委托给 OscillationRatingCalculator）"""
        return self._rating_calculator.calculate(is_stable, cl_metrics, pid_params, osc_info, osc_result)
    
    def _generic_fallback(self, oscillating_segments: List, segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> Optional[Dict]:
        """通用 fallback 整定机制"""
        return self._fallback_tuning(oscillating_segments, segments, segment_results)

    def _fallback_tuning(self, oscillating_segments: List, segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> Optional[Dict]:
        """统一的 fallback 整定机制"""
        osc_config = Config.OSCILLATION_TUNING
        fallback_params = self._strategy.get_fallback_params()
        pb_base = fallback_params['pb_base']
        t1_divisor = fallback_params['t1_divisor']
        t1_min = fallback_params['t1_min']
        ti_multiplier = fallback_params['ti_multiplier']
        
        min_points = 50 if self._loop_type == 'level' else 30
        best_seg, best_result, max_points = None, None, 0
        
        for idx, seg, result in oscillating_segments:
            if len(seg.pv) > max_points:
                max_points = len(seg.pv)
                best_seg = seg
                best_result = result
        
        if best_seg is None or max_points < min_points:
            return None
        
        pv_range = np.ptp(best_seg.pv)
        mv_range = np.ptp(best_seg.mv)
        if mv_range < 0.1 or pv_range < 0.01:
            return None
        
        K_approx = np.clip(pv_range / mv_range, 0.1, 10.0)
        dt = (best_seg.timestamp[1] - best_seg.timestamp[0]) / 1000 if len(best_seg.timestamp) > 1 else 1.0
        data_duration = len(best_seg.pv) * dt
        T1_approx = max(data_duration / t1_divisor, t1_min)
        
        # 估算滞后
        try:
            from scipy import signal
            pv_smooth = np.convolve(best_seg.pv, np.ones(5)/5, mode='same')
            mv_smooth = np.convolve(best_seg.mv, np.ones(5)/5, mode='same')
            correlation = signal.correlate(pv_smooth - np.mean(pv_smooth), mv_smooth - np.mean(mv_smooth), mode='full')
            lags = signal.correlation_lags(len(pv_smooth), len(mv_smooth), mode='full')
            max_corr_idx = np.argmax(np.abs(correlation))
            estimated_delay_samples = lags[max_corr_idx]
            L_approx = max(abs(estimated_delay_samples) * dt, T1_approx / 5)
        except:
            L_approx = T1_approx / 5
        
        delay_ratio = L_approx / max(T1_approx, 1.0)
        
        # 大滞后系统处理（分级）
        extreme_delay_threshold = osc_config.get('extreme_delay_ratio_threshold', 0.8)
        large_delay_threshold = osc_config.get('large_delay_ratio_threshold', 0.5)
        
        if delay_ratio > extreme_delay_threshold or L_approx > 30.0:
            # 极大滞后：应用保守的pb增益 (优化: 降低上限 2.5→1.8)
            pb_base *= osc_config.get('extreme_delay_pb_boost', 1.8)  # 原: 2.5
            ti_multiplier *= osc_config.get('large_delay_ti_boost', 1.4) * 1.1  # 原: 1.5 * 1.2
            self.log(f"   ⚠️ 检测到极大滞后系统 (L/T={delay_ratio:.2f})")
        elif delay_ratio > large_delay_threshold or L_approx > osc_config.get('large_delay_absolute_threshold', 15.0):
            # 大滞后：标准保守 (优化: 降低 1.8→1.4)
            pb_base *= osc_config.get('large_delay_pb_boost', 1.4)  # 原: 1.8
            ti_multiplier *= osc_config.get('large_delay_ti_boost', 1.3)  # 原: 1.5
        
        pu_min = 20.0 if self._loop_type == 'level' else 10.0
        Pu_approx = max(4 * L_approx, pu_min)
        Ku_approx = np.clip(1.2 * T1_approx / (K_approx * L_approx) if L_approx > 0.1 else 2.0 / K_approx, 0.1, 20.0)
        
        oscillation_ratio = best_result.oscillation_ratio if best_result else 0.5
        data_quality = best_result.quality_score if best_result else 0.4
        
        # 恢复稳定性: 恢复增益调整系数
        if K_approx > 2.0:
            pb_base *= 1.0 + (K_approx - 2.0) * (0.18 if self._loop_type == 'level' else 0.22)  # 恢复
        elif K_approx < 0.5 and self._loop_type != 'level':
            pb_base *= 1.4  # 恢复
        
        # 恢复稳定性: 恢复慢系统调整系数
        t1_threshold = 80.0 if self._loop_type == 'level' else 60.0  # 恢复阈值
        if T1_approx > t1_threshold:
            pb_base *= 1.0 + (T1_approx - t1_threshold) / (200.0 if self._loop_type == 'level' else 150.0)  # 恢复
        
        # 按回路类型设置不同pb_max上限 (适度放宽以提高稳态率)
        if self._loop_type == 'flow':
            pb_max_limit = 220.0  # 流量: 放宽 180→220
        elif self._loop_type == 'pressure':
            pb_max_limit = 280.0  # 压力: 放宽 250→280
        elif self._loop_type in ['temperature', 'level']:
            pb_max_limit = osc_config.get('pb_max', 450.0)  # 温度/液位: 放宽至450
        else:
            pb_max_limit = osc_config.get('pb_max', 400.0)
        
        pb_safe = np.clip(pb_base, osc_config.get('pb_min', 80.0), pb_max_limit)
        conservative_Kp = 100.0 / pb_safe
        
        ti_base_min = 10.0 if self._loop_type == 'level' else 5.0
        # 简化 Ti 计算：使用较小的 Ti 加快响应，上限 25s
        conservative_Ti = np.clip(ti_base_min * 1.5, *osc_config.get('ti_range', [1.5, 25.0]))
        conservative_Ki = conservative_Kp / conservative_Ti
        
        # 石化优化: 按回路类型差异化Td使用阈值
        # 流量/压力: 少用Td (阈值0.8), 温度: 多用Td (阈值0.4), 液位: 不用Td
        if self._loop_type == 'level':
            kd_threshold = 0.9  # 液位基本不用Td
        elif self._loop_type == 'temperature':
            kd_threshold = 0.4  # 温度多用Td
        elif self._loop_type in ['flow', 'pressure']:
            kd_threshold = 0.8  # 流量/压力少用Td
        else:
            kd_threshold = 0.6
        
        if oscillation_ratio > kd_threshold:
            conservative_Td = np.clip(Pu_approx / 10, *osc_config.get('td_range', [0.3, 3.0]))
            conservative_Kd = conservative_Kp * conservative_Td
        else:
            conservative_Td, conservative_Kd = 0.0, 0.0
        
        self.log(f"   ✅ {self._loop_type}fallback整定: PB={pb_safe:.1f}%, Ti={conservative_Ti:.1f}s")
        
        pid_params = {
            'Kp': round(conservative_Kp, 4), 'Ki': round(conservative_Ki, 4), 'Kd': round(conservative_Kd, 4),
            'Ti': round(conservative_Ti, 2), 'Td': round(conservative_Td, 2),
            'method': f'{self._loop_type}_fallback', 'Pu': round(Pu_approx, 2), 'Ku': round(Ku_approx, 2), 'pb': round(pb_safe, 2)
        }
        
        osc_info = {
            'Pu': Pu_approx, 'Ku': Ku_approx, 'amplitude': pv_range / 2, 'mv_amplitude': mv_range / 2,
            'decay_ratio': 1.0, 'oscillation_type': 'estimated', 'n_cycles': 1, 'is_valid': True,
            'confidence': 0.3, 'oscillation_ratio': oscillation_ratio
        }
        
        return {
            'success': True, 'pid_params': pid_params, 'oscillation_info': osc_info,
            'segment_idx': 0, 'method': f'{self._loop_type}_fallback',
            'data_quality': data_quality, 'nonlinearity': best_result.nonlinearity_score if best_result else 0.0, 'valve_issues': {}
        }

    def build_oscillation_output(self, osc_result: Dict, hist_data: HistoricalData,
                                 time_range: Dict, tuning_windows: List,
                                 segments: List = None, segment_results: List = None) -> Dict[str, Any]:
        """构建振荡分析整定的输出结果"""
        pid_params = osc_result['pid_params']
        osc_info = osc_result['oscillation_info']
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = hist_data.timestamp[valid_mask]
        sv = hist_data.sv[valid_mask]
        
        Pu = osc_info['Pu']
        pv_range, mv_range = np.ptp(y), np.ptp(u)
        
        if mv_range > 0.1 and pv_range > 0.01:
            K_from_range = pv_range / mv_range
            pv_amplitude = osc_info.get('amplitude', 1.0)
            mv_amplitude = osc_info.get('mv_amplitude', 1.0)
            K_from_osc = pv_amplitude / mv_amplitude if mv_amplitude > 0.01 else K_from_range
            K_est = round(np.clip(max(K_from_range, K_from_osc), 0.1, 10.0), 4)
        else:
            Ku = pid_params['Ku']
            K_est = round(1.0 / Ku if Ku > 0.01 else 1.0, 4)
        
        T1_est, L_est = round(Pu, 4), round(Pu / 4, 4)
        
        pv_model = self._simulator.simulate_segmented(
            (K_est, T1_est, L_est), 'FOPDT', y, u,
            reset_on_sv_change=True, sv=sv, enable_smooth=True,
            enable_amplitude_calibration=True, enable_offset_correction=True, enable_oscillation_overlay=True
        )
        
        temp_fusion = FusionResult(model_type=ModelType.FOPDT, K=K_est, T1=T1_est, T2=0.0, L=L_est)
        
        sv_mean, pv_mean, pv_std = float(np.mean(sv)), float(np.mean(y)), float(np.std(y))
        sp_initial, sp_final = sv_mean, sv_mean + max(pv_std * 2, 1.0)
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            temp_fusion, pid_params, sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_mean, verbose=self._verbose
        )
        
        # Fallback 尝试
        max_fallback_attempts = 3
        for fallback_attempt in range(1, max_fallback_attempts + 1):
            if is_stable:
                break
            self.log(f"   ⚠️ 闭环不稳定，尝试更保守的参数 (第{fallback_attempt}次)...")
            K_approx = pv_range / mv_range if mv_range > 0.1 and pv_range > 0.01 else 1.0
            fallback_confidence = osc_info.get('confidence', 0.3) * (0.5 ** fallback_attempt)
            adjusted_osc_ratio = min(0.95, osc_info.get('oscillation_ratio', 0.5) + 0.15 * fallback_attempt)
            
            pid_params = self._get_conservative_pid_params(
                Pu, osc_info['Ku'], K_approx=K_approx, reason='data_range',
                oscillation_ratio=adjusted_osc_ratio,
                data_quality=osc_result.get('data_quality', 0.5) * (0.8 ** fallback_attempt),
                nonlinearity=osc_result.get('nonlinearity', 0.0),
                valve_issues=osc_result.get('valve_issues', {}), confidence=fallback_confidence
            )
            is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
                temp_fusion, pid_params, sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_mean, verbose=self._verbose
            )
        
        model_rating, rating_details, warnings = self._calculate_oscillation_rating(
            is_stable=is_stable, cl_metrics=cl_metrics, pid_params=pid_params, osc_info=osc_info, osc_result=osc_result
        )
        
        closed_loop_info = {
            'is_stable': is_stable, 'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot, 'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error, 'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio, 'sp_initial': sp_initial, 'sp_final': sp_final, 'pv_initial': pv_mean
        }
        
        tuning_success = is_stable
        if not is_stable and Pu > 100.0:
            if cl_metrics.decay_ratio < 1.2:
                tuning_success = True
            elif self._loop_type == 'level':
                tuning_success = True
                model_rating = min(model_rating, 5.0)
                warnings.append(f'慢液位系统(Pu={Pu:.0f}s)，内部仿真未收敛，建议人工验证')
        
        return {
            'success': tuning_success, 'model_type': 'FOPDT', 'model_rating': model_rating,
            'start_time': time_range.get('start_time'), 'end_time': time_range.get('end_time'),
            'model_parameters': {'K': K_est, 'T1': T1_est, 'T2': 0.0, 'L': L_est},
            'pid_parameters': pid_params,
            'fitting_result': {
                'timestamp': ts.tolist(), 'sv': sv.tolist(), 'pv': y.tolist(), 'mv': u.tolist(),
                'pv_model': pv_model.tolist(), 'r_squared': calculate_r2(y, pv_model), 'rmse': calculate_rmse(y, pv_model)
            },
            'fusion_info': {
                'method': pid_params.get('method', 'oscillation_critical'), 'n_segments': 1, 'consistency_score': 0.0,
                'oscillation_type': osc_info['oscillation_type'], 'oscillation_amplitude': osc_info['amplitude']
            },
            'closed_loop_verification': closed_loop_info, 'rating_details': rating_details,
            'segment_info': self._build_segment_info(segments, segment_results) if segments else []
        }
    
    def _build_segment_info(self, segments: List, segment_results: List) -> List[Dict]:
        """构建段信息用于可视化"""
        segment_info = []
        if not segments or not segment_results:
            return segment_info
        for i, (seg, result) in enumerate(zip(segments, segment_results)):
            if len(seg.timestamp) > 0:
                step_score = result.step_response_score if hasattr(result, 'step_response_score') else result.get('step_response_score', 0.5)
                osc_ratio = result.oscillation_ratio if hasattr(result, 'oscillation_ratio') else result.get('oscillation_ratio', 0.5)
                is_tuning = (step_score >= 0.5 and osc_ratio < 0.5)
                segment_info.append({
                    'index': i, 'start_time': int(seg.timestamp[0]), 'end_time': int(seg.timestamp[-1]),
                    'data_points': len(seg.pv), 'step_response_score': round(step_score, 2),
                    'oscillation_ratio': round(osc_ratio, 2), 'type': 'tuning' if is_tuning else 'oscillation'
                })
        return segment_info
