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



from ...config import Config, ModelType
from ...data_models import SegmentResult, HistoricalData, FusionResult
from ...utils import calculate_r2, calculate_rmse, build_cl_verification
from ...logger import LoggerMixin
from ..strategies.loop_type_strategies import get_loop_strategy
from .conservative_pid import ConservativePIDCalculator



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
                               force: bool = False,
                               tuning_constraints: dict = None) -> Optional[Dict]:
        """尝试使用振荡分析进行临界法整定"""
        tuning_constraints = tuning_constraints or {}
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
            
            osc_threshold = 0.85 if self._loop_type in ['flow', 'pressure'] else 0.7
            if avg_osc_ratio > osc_threshold and len(oscillating_segments) >= total_segments // 2:
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
                
            # [FIX] 全局收口：即使在此刻尝试执行临界法(Critical Tuning)，如果对应的 MV 根本没动
            # (range < 0.1)，PV的所谓"完美规律震荡"也属于纯环境扰动引发的幻象。我们决不能通过单纯
            # 对假模假式的振荡数据取频率来瞎编出一组控制器参数！这种现象必须果断拒绝被解析出特征。
            mv_range = np.ptp(seg.mv) if len(seg.mv) > 0 else 0.0
            if mv_range < 0.1:
                self.log(f"   🚫 数据段被跳过：MV未发生有效变化(range={mv_range:.3f} < 0.1)。无阀门动作支撑的PV波浪，拒绝强扯计算。")
                continue
            
            osc_info = self._pid_calculator.analyze_oscillation(seg.pv, seg.mv, dt)
            if osc_info and osc_info.get('is_valid', False):
                oscillation_analyses.append({'segment_idx': idx, 'osc_info': osc_info, 'data_points': len(seg.pv)})
        
        if not oscillation_analyses:
            self.log("   ⚠️ 无法从振荡数据中提取有效特征")
            if oscillating_segments:
                return self._generic_fallback(oscillating_segments, segments, segment_results, current_pid, tuning_constraints)
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
            nonlinearity=nonlinearity, valve_issues=valve_issues, confidence=confidence,
            tuning_constraints=tuning_constraints
        )
        
        if pid_params is None:
            return None

        # [FIX] 基于 current_pid 的极限增益安全护栏
        # 与 _fallback_tuning 中的同类保护一致：如果当前 PID 已经导致振荡，
        # 说明 current_Kp 已接近系统极限增益 Ku，新参数不应比它更激进。
        if current_pid:
            current_Kp = abs(current_pid.get('Kp', 0.0))
            if current_Kp > 0.01:
                safe_divisor = 6.0 if self._loop_type == 'flow' else 4.0
                min_safe_pb = (100.0 * safe_divisor) / current_Kp
                current_pb = pid_params.get('pb', 100.0)
                if current_pb < min_safe_pb:
                    self.log(f"   ⚠️ [临界法护栏] current_Kp={current_Kp:.2f} 导致振荡，PB {current_pb:.1f}% → {min_safe_pb:.1f}%")
                    new_kp = 100.0 / min_safe_pb
                    pid_params['pb'] = round(min_safe_pb, 2)
                    pid_params['Kp'] = round(new_kp, 6)
                    pid_params['Ki'] = round(new_kp / pid_params['Ti'], 6) if pid_params.get('Ti', 0) > 0 else 0.0
                    pid_params['Kd'] = round(new_kp * pid_params.get('Td', 0), 6) if pid_params.get('Td', 0) > 0 else 0.0

        # [FIX] 符号校正：conservative PID 总是输出正 Kp，需要根据 current_pid 或数据相关性校正
        if current_pid and abs(current_pid.get('Kp', 0)) > 1e-6:
            original_sign = np.sign(current_pid['Kp'])
            if original_sign < 0 and pid_params['Kp'] > 0:
                # 反作用过程：current_pid.Kp 是负的，输出也应该是负的
                pid_params['Kp'] = -abs(pid_params['Kp'])
                pid_params['Ki'] = -abs(pid_params['Ki'])
                if pid_params.get('Kd', 0) != 0:
                    pid_params['Kd'] = -abs(pid_params['Kd'])
                self.log(f"   🔄 反作用符号校正: current_pid.Kp={current_pid['Kp']:.2f} → Kp={pid_params['Kp']:.4f}")
        elif best_seg is not None:
            # 无 current_pid 时使用 MV-PV 相关性推断符号
            try:
                corr = np.corrcoef(best_seg.mv[:len(best_seg.pv)], best_seg.pv)[0, 1]
                if not np.isnan(corr) and corr < -0.3:
                    pid_params['Kp'] = -abs(pid_params['Kp'])
                    pid_params['Ki'] = -abs(pid_params['Ki'])
                    self.log(f"   🔄 相关性符号校正: corr={corr:.2f} → Kp={pid_params['Kp']:.4f}")
            except Exception:
                pass
        
        self.log(f"   ✅ 临界法整定成功: Pu={Pu:.1f}s, Ku={pid_params['Ku']:.3f}")
        self.log(f"      Kp={pid_params['Kp']:.4f}, Ki={pid_params['Ki']:.4f}, Kd={pid_params['Kd']:.4f}")
        
        return {
            'success': True, 'pid_params': pid_params, 'oscillation_info': best_analysis['osc_info'],
            'segment_idx': best_analysis['segment_idx'], 'method': 'oscillation_critical',
            'data_quality': data_quality, 'nonlinearity': nonlinearity, 'valve_issues': valve_issues
        }
    
    def _estimate_L_from_pv_oscillation(self, pv: np.ndarray, dt: float) -> float:
        """
        [NEW] 从 PV 数据的自相关中提取主振荡周期，用 T_osc/4 作为等效延迟估计。
        
        原理：对于液位等积分过程，在闭环控制下 PV 围绕 SV 振荡的周期 T_osc
        与被控对象的纯滞后 L 之间存在经验关系 T_osc ≈ 4L（Ziegler-Nichols 近似）。
        因此 L ≈ T_osc / 4。
        
        当无法提取有效振荡周期时，退化为原来的硬编码默认值。
        
        Args:
            pv: PV 数据数组
            dt: 采样间隔 (秒)
            
        Returns:
            估计的等效延迟 L (秒)
        """
        n = len(pv)
        if n < 100:
            return 15.0 if self._loop_type == 'level' else 10.0
        
        try:
            # 去趋势 + 去均值
            pv_detrended = pv - np.linspace(pv[0], pv[-1], n)
            pv_centered = pv_detrended - np.mean(pv_detrended)
            var = np.var(pv_centered)
            
            if var < 1e-10:
                return 15.0 if self._loop_type == 'level' else 10.0
            
            # 计算自相关函数
            max_lag = min(n // 2, 3000)
            autocorr = np.zeros(max_lag)
            for lag in range(max_lag):
                if lag < n:
                    autocorr[lag] = np.mean(pv_centered[:n-lag] * pv_centered[lag:]) / var
            
            # 寻找自相关函数的第一个显著正峰（跳过 lag=0 附近的衰减区）
            # 第一个正峰对应的滞后 = 振荡半周期，乘以 2 得完整周期
            min_search_lag = max(10, int(5.0 / dt))  # 至少跳过 5 秒
            
            # 先找到自相关首次降到 0 以下的位置（过零点）
            first_zero = min_search_lag
            for lag in range(min_search_lag, max_lag):
                if autocorr[lag] <= 0:
                    first_zero = lag
                    break
            
            # 从过零点之后找第一个正峰
            best_peak_lag = None
            best_peak_val = 0.1  # 峰值至少要0.1才算有效
            
            for lag in range(first_zero, max_lag - 1):
                if autocorr[lag] > best_peak_val and autocorr[lag] > autocorr[lag-1] and autocorr[lag] >= autocorr[lag+1]:
                    best_peak_lag = lag
                    best_peak_val = autocorr[lag]
                    break  # 取第一个显著峰
            
            if best_peak_lag is not None:
                T_osc = best_peak_lag * dt  # 振荡周期（秒）
                # 对于积分过程（液位），振荡周期远大于 4L（因为积分器本身拉长了响应），
                # 经验系数用 T_osc/8 更接近真实死区；其他过程保持经典的 T_osc/4
                if self._loop_type == 'level':
                    L_estimated = T_osc / 8.0
                else:
                    L_estimated = T_osc / 4.0
                
                # 合理性约束
                # 液位的管道+传感器纯死区极少超过 30s
                if self._loop_type == 'level':
                    L_estimated = np.clip(L_estimated, 5.0, 30.0)
                else:
                    L_estimated = np.clip(L_estimated, 2.0, 60.0)
                
                divisor = 8 if self._loop_type == 'level' else 4
                self.log(f"   📊 PV振荡周期估计: T_osc={T_osc:.1f}s (autocorr峰@lag={best_peak_lag}), L≈T/{divisor}={L_estimated:.1f}s")
                return float(L_estimated)
            else:
                # 自相关未找到峰 → 尝试过零点计数法作为备选
                error = pv_centered
                zero_crossings = []
                for i in range(1, len(error)):
                    if error[i-1] * error[i] < 0:
                        zero_crossings.append(i)
                
                if len(zero_crossings) >= 4:
                    # 平均半周期 → 全周期
                    half_periods = np.diff(zero_crossings)
                    avg_half_period = np.mean(half_periods)
                    T_osc_zc = avg_half_period * 2.0 * dt
                    
                    divisor = 8 if self._loop_type == 'level' else 4
                    L_estimated = T_osc_zc / divisor
                    
                    if self._loop_type == 'level':
                        L_estimated = np.clip(L_estimated, 5.0, 30.0)
                    else:
                        L_estimated = np.clip(L_estimated, 2.0, 60.0)
                    
                    self.log(f"   📊 PV过零点估计: T_osc={T_osc_zc:.1f}s ({len(zero_crossings)}个过零点), L≈T/{divisor}={L_estimated:.1f}s")
                    return float(L_estimated)
                else:
                    self.log(f"   📊 PV自相关/过零点均未检测到有效振荡，使用默认 L")
                    return 15.0 if self._loop_type == 'level' else 10.0
                
        except Exception as e:
            self.log(f"   ⚠️ PV振荡周期估计异常({e})，使用默认 L")
            return 15.0 if self._loop_type == 'level' else 10.0
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, K_approx: float = 1.0,
                                      reason: str = 'generic', oscillation_ratio: float = 0.0,
                                      data_quality: float = 0.5, nonlinearity: float = 0.0,
                                      valve_issues: Dict = None, confidence: float = 0.5,
                                      tuning_constraints: dict = None) -> Dict[str, Any]:
        """获取保守PID参数（委托给 ConservativePIDCalculator）"""
        return self._conservative_pid_calculator.calculate(
            Pu=Pu, Ku=Ku, K_approx=K_approx, reason=reason,
            oscillation_ratio=oscillation_ratio, data_quality=data_quality,
            nonlinearity=nonlinearity, valve_issues=valve_issues, confidence=confidence,
            tuning_constraints=tuning_constraints
        )
    

    
    def _generic_fallback(self, oscillating_segments: List, segments: List[HistoricalData],
                          segment_results: List[SegmentResult], current_pid: Dict = None,
                          tuning_constraints: dict = None) -> Optional[Dict]:
        """通用 fallback 整定机制"""
        return self._fallback_tuning(oscillating_segments, segments, segment_results, current_pid, tuning_constraints)

    def _fallback_tuning(self, oscillating_segments: List, segments: List[HistoricalData],
                          segment_results: List[SegmentResult], current_pid: Dict = None,
                          tuning_constraints: dict = None) -> Optional[Dict]:
        """统一的 fallback 整定机制"""
        tuning_constraints = tuning_constraints or {}
        osc_config = Config.OSCILLATION_TUNING
        fallback_params = self._strategy.get_fallback_params()
        pb_base = fallback_params['pb_base']
        t1_divisor = fallback_params['t1_divisor']
        t1_min = fallback_params['t1_min']
        ti_multiplier = fallback_params['ti_multiplier']
        
        min_points = 50 if self._loop_type == 'level' else 20
        best_seg, best_result, max_points = None, None, 0
        best_quality = -1.0
        
        for idx, seg, result in oscillating_segments:
            # [FIX] 选质量最好的段，而不是点数最多的段。
            # 原因：50104 中段1(corr=-0.229, quality=0.58) 和段2(corr=+0.830, quality=0.71)
            # 降采样后点数相同(1000)，按点数选会选到段1导致符号算反 → K_int 取反 → 闭环不稳定。
            seg_quality = getattr(result, 'quality_score', 0.0) if result else 0.0
            # 多段同质量时，优先选相关性更强（信号更清晰）的段
            seg_corr_strength = abs(getattr(result, 'correlation', 0.0)) if result else 0.0
            seg_score = seg_quality + 0.01 * seg_corr_strength  # 质量为主，相关性为辅
            
            if len(seg.pv) >= min_points and (seg_score > best_quality or 
                (abs(seg_score - best_quality) < 1e-6 and len(seg.pv) > max_points)):
                best_quality = seg_score
                max_points = len(seg.pv)
                best_seg = seg
                best_result = result
        
        if best_seg is None or max_points < min_points:
            return None
        
        pv_range = np.ptp(best_seg.pv)
        mv_range = np.ptp(best_seg.mv)
        if pv_range < 0.005:
            return None
        
        # [FIX] 增强数据准入铁律：如果作为自变量的 MV 极度平缓 (变化量 < 0.1)，
        # 则说明 PV 的波动完全不受 MV 控制（属于外部生产条件或不可测量干扰）。
        # 此时尝试辨识或靠猜得出的参数是无根据且危险的。系统直接拒绝出参！
        if mv_range < 0.1:
            self.log(f"   🚫 数据段被否决：阀门(MV)未发生有效动作(range={mv_range:.3f} < 0.1)。无激励源，系统拒绝编造PID参数。")
            return None
            
        # [HOTFIX] 放开荒谬的增益粗切断，允许极小型/巨型物理响应
        # 工业巨型缓冲罐的 K 值通常远小于 0.1，硬截断会导致严重误区
        K_approx = np.clip(pv_range / mv_range, 0.0001, 1000.0)
        dt = (best_seg.timestamp[1] - best_seg.timestamp[0]) / 1000 if len(best_seg.timestamp) > 1 else 1.0
        data_duration = len(best_seg.pv) * dt
        T1_approx = max(data_duration / t1_divisor, t1_min)
        
        # 估算滞后与符号 (v3.9 增强)
        try:
            from scipy import signal
            pv_smooth = np.convolve(best_seg.pv, np.ones(5)/5, mode='same')
            mv_smooth = np.convolve(best_seg.mv, np.ones(5)/5, mode='same')
            
            # 使用简单的相关系数作为基线 (v3.9)
            pv_norm = pv_smooth - np.mean(pv_smooth)
            mv_norm = mv_smooth[:len(pv_smooth)] - np.mean(mv_smooth[:len(pv_smooth)])
            corr = 0.0
            if np.std(pv_norm) > 1e-6 and np.std(mv_norm) > 1e-6:
                corr = np.corrcoef(mv_norm, pv_norm)[0, 1]
            
            # [FIX] 如果 MV 几乎没有发生可信的变化，不要相信 CCF 算出来的垃圾延迟（通常是极其巨大的空窗期）
            original_mv_range = np.ptp(best_seg.mv)
            if original_mv_range < 0.05:
                # [FIX v2] 不再盲目用 L=15.0s 硬编码。
                # 尝试从 PV 的自相关中提取主振荡周期，用 T_osc/4 作为等效延迟估计。
                # 这样下游的 Ti = 4*(λ+L) 会随实际数据变化，而不是永远 260。
                L_approx = self._estimate_L_from_pv_oscillation(best_seg.pv, dt)
                
                # 符号优先从先验中继承，而非由于平缓数据的噪声导致反转
                current_Kp = current_pid.get('Kp', 0.0) if current_pid else 0.0
                if abs(current_Kp) > 1e-6:
                    sign = np.sign(current_Kp)
                else:
                    sign = 1.0
                source = "current_pid (flat MV)"
                self.log(f"   ⚠️ MV无有效行为脉冲，跳过 CCF 错位匹配。基于PV振荡估算滞后 L={L_approx:.1f}s")
            else:
                correlation = signal.correlate(pv_norm, mv_norm, mode='full')
                lags = signal.correlation_lags(len(pv_norm), len(mv_norm), mode='full')
                max_corr_idx = np.argmax(np.abs(correlation))
                estimated_delay_samples = lags[max_corr_idx]
                
                # 保护：错位延迟不能超过样本长度的 15%
                max_allowed_delay = len(pv_norm) * 0.15
                if abs(estimated_delay_samples) > max_allowed_delay:
                    estimated_delay_samples = max_allowed_delay * np.sign(estimated_delay_samples)
                
                if self._loop_type == 'level':
                    # 液位回路（积分过程）无内禀的 T1 时间常数拉扯滞后，只有传感器与管道纯死区
                    L_approx = abs(estimated_delay_samples) * dt
                    # [FIX v2] 如果相关性过差，CCF 的错位计算是不置信的。
                    # 不再盲目截断到 15.0s，而是用 PV 振荡周期来估计更合理的 L。
                    if abs(corr) < 0.3:
                        L_from_osc = self._estimate_L_from_pv_oscillation(best_seg.pv, dt)
                        L_approx = L_from_osc  # 用数据驱动的估计替代硬编码
                    # 绝对物理上限：一个常规级联液位的死区极少超过 30s
                    L_approx = np.clip(L_approx, 2.0, 30.0)
                else:
                    L_approx = max(abs(estimated_delay_samples) * dt, T1_approx / 5)
                
                # 符号逻辑保持不变...
                current_Kp = current_pid.get('Kp', 0.0) if current_pid else 0.0
                if abs(current_Kp) > 1e-6:
                    sign = np.sign(current_Kp)
                    source = "current_pid"
                else:
                    sign = np.sign(corr) if abs(corr) > 0.1 else 1.0
                    source = "correlation"
            
            K_approx = abs(K_approx) * sign
            
            # [FIX] Scene-5: 反向作用保护
            # 如果 current_pid 明确是负的，或者相关系数明确是负的，绝不要因为振荡比高而在后续逻辑中强制取绝对值
            # 这里已经在 K_approx 中应用了符号，downstream consumer 应该尊重 K_approx 的符号
            
            self.log(f"   📊 fallback 符号检测({source}): corr={corr:.2f}, Kp={current_Kp:.2f} -> Sign={sign}")
        except Exception as e:
            # v3.7 兜底方案：使用相关系数判断符号
            try:
                corr = np.corrcoef(best_seg.mv[:len(best_seg.pv)], best_seg.pv)[0, 1]
                if not np.isnan(corr):
                    current_Kp = current_pid.get('Kp', 1.0) if current_pid else 1.0
                    sign = np.sign(corr) * (1.0 if current_Kp > 0 else -1.0)
                    K_approx *= sign
                    self.log(f"   ⚠️ CCF解析失败, 使用相关系数判定符号: corr={corr:.2f}, Sign={sign}")
            except:
                pass
            L_approx = T1_approx / 5
        
        # [NEW] 频域辨识融合 (v4.0)
        try:
            from ...fitting.frequency_domain_identifier import FrequencyDomainIdentifier
            dt_seg = (best_seg.timestamp[1] - best_seg.timestamp[0]) / 1000 if len(best_seg.timestamp) > 1 else 1.0
            t_seg = np.arange(len(best_seg.pv)) * dt_seg
            freq_result = FrequencyDomainIdentifier.identify_fopdt(t_seg, best_seg.pv, best_seg.mv)
            if freq_result and freq_result.get('confidence', 0) > 0.8:
                alpha = 0.15  # 频域权重（保守融合，仅作辅助修正）
                freq_K = freq_result.get('K', K_approx)
                freq_T1 = freq_result.get('T1', T1_approx)
                freq_L = freq_result.get('L', L_approx)
                # 符号保持一致
                if np.sign(freq_K) != np.sign(K_approx) and abs(K_approx) > 0.01:
                    freq_K = abs(freq_K) * np.sign(K_approx)
                K_approx = (1-alpha)*K_approx + alpha*freq_K
                T1_approx = (1-alpha)*T1_approx + alpha*freq_T1
                L_approx = (1-alpha)*L_approx + alpha*freq_L
                self.log(f"   📊 频域辨识融合(α={alpha}): K={K_approx:.3f}, T1={T1_approx:.1f}s, L={L_approx:.1f}s"
                         f" (置信度={freq_result['confidence']:.2f})")
        except Exception:
            pass  # 频域辨识失败不影响主路径
        
        delay_ratio = L_approx / max(T1_approx, 1.0)
        
        # [NEW] 近积分过程专用路径 (level 回路, 或低增益+大时间常数)
        is_integrating = (self._loop_type == 'level') or (T1_approx > 100.0 and abs(K_approx) < 0.3)
        if is_integrating:
            # 积分过程整定：使用 Lambda 规则的积分过程版本
            # G(s) ≈ K_int/s，其中 K_int = K/T1（归一化积分增益），必须保留真实物理符号！
            K_int = K_approx / max(T1_approx, 1.0)  # 积分增益 (%/s/%)
            
            # [FIX] K_int 仿真兜底：极小 K_int 会让闭环仿真中的被控对象变成"死石头"。
            # 这里仅对仿真用的 K_int 设置地板值，不影响整定公式推导。
            K_int_for_sim = K_int
            if abs(K_int_for_sim) < 1e-4:
                self.log(f"   ⚠️ 数据静态致积分增益极小(K_int={K_int:.6f})，仿真用值修正至物理下限 1e-4")
                K_int_for_sim = 1e-4 * sign if sign != 0 else 1e-4
            
            # ================================================================
            # [均值液位控制 (Averaging Level Control) 物理推导]
            # ================================================================
            # 解绑对钳位后的 L_approx 的依赖：均值控制的时间尺度应与罐体
            # 自然振荡周期挂钩，而非被 L_approx 的 30s 安全钳位所限制。
            # 直接从 PV 过零点重新估算未钳位的原始 T_osc。
            # ================================================================
            try:
                pv_centered = best_seg.pv - np.mean(best_seg.pv)
                zc_indices = []
                for i in range(1, len(pv_centered)):
                    if pv_centered[i-1] * pv_centered[i] < 0:
                        zc_indices.append(i)
                
                data_duration = len(pv_centered) * dt
                if len(zc_indices) >= 4:
                    T_osc = float(np.mean(np.diff(zc_indices)) * 2.0 * dt)
                elif len(zc_indices) >= 2:
                    T_osc = float((zc_indices[-1] - zc_indices[0]) / (len(zc_indices)-1) * 2.0 * dt)
                elif len(zc_indices) == 1:
                    # [FIX] 单过零点时 T_osc 估计极不可靠，原先 data_duration*1.5 会导致
                    # T_osc=7500s → Ti=3780s → 触碰 ti_max=3600 边界。
                    # 改用更保守的 data_duration（不乘 1.5），并设上限 1800s
                    T_osc = float(min(data_duration, 1800.0))
                else:
                    # [FIX] 无过零点：数据可能有单向趋势，不是真正的振荡。
                    # 原先取 data_duration 会导致极大 T_osc。改为保守估计。
                    T_osc = float(min(data_duration * 0.5, 1200.0))
                
                # 下限托底
                T_osc = max(T_osc, L_approx * 8.0, 240.0)
                
                # [NEW] 物理上限钳位：液位罐体的自然振荡周期极少超过 1 小时
                T_osc_max = 3600.0
                if T_osc > T_osc_max:
                    self.log(f"   ⚠️ T_osc={T_osc:.0f}s 超出物理合理范围，钳位至 {T_osc_max:.0f}s (过零点={len(zc_indices)}个)")
                    T_osc = T_osc_max
            except Exception:
                T_osc = max(L_approx * 8.0, 240.0)
            
            # Lambda 挂钩振荡周期的 1/4，确保阀门有足够的缓冲吞吐时间
            lambda_c = max(T_osc / 4.0, 60.0)
            
            # 经典积分过程推导: Ti = 2λ + L，允许大罐子自然产出上百甚至上千秒的积分时间
            Ti_level = 2.0 * lambda_c + L_approx
            
            # 从 tuning_constraints 读取统一的 ti_max，通常设为 3600 (一小时作为上限)
            ti_max_limit = tuning_constraints.get('ti_max', 3600.0)
            Ti_level = min(Ti_level, ti_max_limit)
            
            # 2. 从“容忍液位波动空间”原生推导 Kp (取代对极小 K_int 的紧密求解)
            pb_min_limit = tuning_constraints.get('pb_min', 40.0)
            pb_max_limit = tuning_constraints.get('pb_max', 2000.0)
            
            # PV 波动幅度归一化判断（相对于 PV 均值的百分比）
            pv_mean = np.mean(best_seg.pv)
            pv_range_pct = (pv_range / max(abs(pv_mean), 1.0)) * 100
            
            # 【Averaging Heuristic 法则】
            # 对于化工储罐，均值控制的天然 PB 黄金区间通常在 100% ~ 125%。
            # 只有当原始数据中的 pv_range 波动极其剧烈（相对 mv_range）时才收紧它。
            try:
                # 评估单位阀门动作带来的液位波动 (K_approx = pv_range/mv_range)
                gain_magnitude = abs(K_approx) if K_approx is not None and abs(K_approx) > 0.001 else 1.0
                # 以 100% PB 作为基准。若数据表现出增益庞大，PB需拉高以增加柔软度；增益极小，PB适度缩减
                pb_from_physics = 100.0 * max(0.8, min(gain_magnitude * 2.0, 1.5))
            except Exception:
                pb_from_physics = 100.0
            
            if pb_from_physics < pb_min_limit:
                pb_level = pb_min_limit
                self.log(f"   📊 均值物理PB={pb_from_physics:.1f}%过小，钳制到预设下限{pb_min_limit:.0f}%")
            elif pb_from_physics > pb_max_limit:
                pb_level = pb_max_limit
            else:
                pb_level = pb_from_physics
                self.log(f"   📊 均值推导自然演进 PB={pb_level:.1f}%，完美落入安全区间")
            
            # 高频剧烈波动时适度收紧，确保不会完全丧失控制
            if pv_range_pct > 25.0 and pb_level > 120.0:
                pb_level = max(pb_level * 0.7, pb_min_limit)
                self.log(f"   📊 PV波动过于剧烈({pv_range_pct:.1f}%)，适度收紧PB至{pb_level:.1f}%")
            
            Kp_level = 100.0 / pb_level * sign
            
            conservative_Kp = Kp_level
            conservative_Ki = abs(conservative_Kp) / Ti_level
            conservative_Kd = 0.0
            
            # 用仿真专用的 K_int 替换原始值（仅影响下游闭环验证和可视化）
            K_int = K_int_for_sim
            
            self.log(f"   🧊 LEVEL专属整定: 均值控制法 T_osc={T_osc:.0f}s, λ={lambda_c:.0f}s, L={L_approx:.1f}s")
            self.log(f"   ✅ Levelfallback: Ti={Ti_level:.1f}s, PB={pb_level:.1f}% (原生均值推算={pb_from_physics:.1f}%)")
            
            pid_params = {
                'Kp': round(float(conservative_Kp), 8),
                'Ki': round(float(conservative_Ki), 8),
                'Kd': 0.0,
                'Ti': round(float(Ti_level), 2),
                'Td': 0.0,
                'pb': round(float(pb_level), 2),
                'method': 'integrating_fallback',
                'Pu': round(float(T1_approx), 2),
                'Ku': round(float(1.0 / max(abs(K_approx), 0.01)), 2),
                'K_int': round(float(K_int), 8),  # [FIX] 保存真实积分增益，供下游闭环验证/可视化使用
                'L_approx': round(float(L_approx), 2), # 保存推断出的死区时间，供积分仿真器一致性使用
            }
            osc_info = {
                'Pu': T1_approx, 'Ku': 1.0 / max(abs(K_approx), 0.01),
                'amplitude': pv_range / 2, 'mv_amplitude': mv_range / 2,
                'decay_ratio': 1.0, 'oscillation_type': 'integrating',
                'n_cycles': 1, 'is_valid': True,
                'confidence': 0.5, 'oscillation_ratio': 0.3,
                'K_int': round(float(K_int), 8),  # [FIX] 同步保存
            }
            return {
                'success': True, 'pid_params': pid_params, 'oscillation_info': osc_info,
                'segment_idx': 0, 'method': 'integrating_fallback',
                'data_quality': 0.5, 'nonlinearity': 0.0, 'valve_issues': {}
            }

        # ================================================================
        # 以下为非积分过程的通用 fallback 路径 (flow / temperature / pressure)
        # 注意：所有 loop_type=='level' 的回路已在上方 is_integrating 分支中 return，
        #       因此以下 self._loop_type=='level' 的分支仅对 T1>100 & K<0.3 的
        #       非 level 近积分过程才可能触发。
        # ================================================================
        extreme_delay_threshold = osc_config.get('extreme_delay_ratio_threshold', 0.8)
        large_delay_threshold = osc_config.get('large_delay_ratio_threshold', 0.5)
        
        if delay_ratio > extreme_delay_threshold or L_approx > 30.0:
            # 极大滞后：增加保守性以恢复稳定性 (1.8 -> 2.2)
            pb_base *= 2.2
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
        K_abs_approx = abs(K_approx)
        if K_abs_approx > 2.0:
            boost_factor = 0.22
            # 注意: level 回路已经在上方 return，此处仅适用于非 level 过程
            if self._loop_type == 'flow':
                boost_factor = 0.1   # 对高增益更激进 (0.15 -> 0.1)
            elif self._loop_type == 'pressure':
                boost_factor = 0.08  # 回调 (0.1 -> 0.08)
            pb_base *= 1.0 + (K_abs_approx - 2.0) * boost_factor
        elif K_abs_approx < 0.5:
            # 适度恢复低增益补偿以提升稳定性
            low_gain_boost = 1.15 if self._loop_type in ['flow', 'pressure'] else 1.4
            pb_base *= low_gain_boost
        
        # 恢复稳定性: 恢复慢系统调整系数
        t1_threshold = 80.0 if self._loop_type == 'level' else 60.0  # 恢复阈值
        
        # [NEW] 基于当前不稳定 PID 的极限增益保护
        # 如果当前 PID 导致了持续的等幅/发散振荡，说明其 Kp 已经接近或超出了系统的极限增益 Ku。
        # 为了让系统恢复稳定，新计算的 Kp 不应超过原 Kp 的安全比例。
        # 流量回路对增益突变极为敏感，将其视为 K 增加了 6 倍的极端暴增场景来兜底 (1/6.0)，其他采用 1/4.0。
        if current_pid:
            current_Kp = abs(current_pid.get('Kp', 0.0))
            if current_Kp > 0.01:
                safe_divisor = 6.0 if self._loop_type == 'flow' else 4.0
                min_safe_pb = (100.0 * safe_divisor) / current_Kp
                if pb_base < min_safe_pb:
                    self.log(f"   ⚠️ 当前 Kp={current_Kp:.2f} 导致不稳定，强制基于极限增益修正 PB: {pb_base:.1f}% -> {min_safe_pb:.1f}%")
                    pb_base = min_safe_pb
        if T1_approx > t1_threshold:
            # 减缓慢系统 PB 膨胀 (150 -> 300)
            pb_base *= 1.0 + (T1_approx - t1_threshold) / (200.0 if self._loop_type == 'level' else 300.0)
            
        # [NEW] Flow 回路大滞后专杀 (Dead-time Dominant Flow)
        # 如果流量回路测出了明显大于物理常理的滞后时间，直接放弃快响应要求，强制拉开积分时间和比例度。
        if self._loop_type == 'flow' and L_approx > 3.0:
            self.log(f"   ⚠️ 触发 Flow 回路大滞后专杀 (L={L_approx:.1f}s > 3.0s)，放弃快响应强制求稳")
            pb_base *= 1.5
            ti_multiplier *= max(1.5, L_approx / 4.0)
        
        # 应用 Loop Preset 的安全系数和范围限制
        preset = tuning_constraints or {}
        safety_factor = preset.get('safety_factor', 1.05)
        pb_base *= safety_factor
        
        pb_max_limit = preset.get('pb_max', osc_config.get('pb_max', 400.0))
        pb_min_limit = preset.get('pb_min', osc_config.get('pb_min', 60.0))
        
        # 应用 Loop Preset 的 Ti Multiplier
        preset_ti_mult = preset.get('ti_multiplier', 1.0)
        ti_multiplier *= preset_ti_mult
        
        # 严格遵守 PB 限制
        pb_safe = np.clip(pb_base, pb_min_limit, pb_max_limit)
        conservative_Kp = 100.0 / pb_safe
        
        # Ti 基准（level 回路取决于 T1 大小）
        # Ti 基准（level 和 temperature 回路需要特殊下限保护）
        if self._loop_type == 'level' and T1_approx > 100:
            ti_base_min = max(20.0, T1_approx * 0.05)  # T1的5%，至少20s
        elif self._loop_type == 'level':
            ti_base_min = 15.0
        elif self._loop_type == 'temperature':
            ti_base_min = 30.0  # 温度回路热容积大，强制设定安全积分底线
        else:
            ti_base_min = 5.0
        base_Ti = ti_base_min * 1.5
        
        ti_max_limit = preset.get('ti_max', osc_config.get('ti_range', [1.5, 600.0])[1])
        conservative_Ti = np.clip(base_Ti * ti_multiplier, osc_config.get('ti_range', [1.5, 600.0])[0], ti_max_limit)
        conservative_Ki = conservative_Kp / conservative_Ti
        
        # [NEW] 严格遵循 Loop Preset 的 Td 策略
        enable_derivative = preset.get('td_enable', False)
        
        if not enable_derivative:
            conservative_Td = 0.0
            conservative_Kd = 0.0
        else:
            # 允许微分 (Temp/Pressure)
            if 'td_ratio' in preset:
                td_max = preset.get('td_max', 50.0)
                conservative_Td = min(conservative_Ti * preset['td_ratio'], td_max)
                conservative_Kd = conservative_Kp * conservative_Td
            else:
                # 原始逻辑：仅当振荡严重时使用微分
                if self._loop_type == 'temperature':
                    kd_threshold = 0.4
                elif self._loop_type == 'pressure':
                    kd_threshold = 0.8
                else:
                    kd_threshold = 0.6
                
                if oscillation_ratio > kd_threshold:
                    conservative_Td = np.clip(Pu_approx / 10, *osc_config.get('td_range', [0.3, 3.0]))
                    conservative_Kd = conservative_Kp * conservative_Td
                else:
                    conservative_Td, conservative_Kd = 0.0, 0.0
        
        # [NEW] 符号对齐：确保 PID 参数符号与过程增益一致，支持反向作用系统 (Reverse Acting)
        # [NOTE] K_approx 在 L635 已经带上了正确符号 (abs(K) * sign)，
        # 这里从 K_approx 重新提取符号并乘上去，数学上等价于取绝对值后重赋号。
        # 如果将来修改了 K_approx 的符号处理逻辑，务必同步检查此处。
        sign = np.sign(K_approx) if abs(K_approx) > 0.001 else 1.0
        conservative_Kp *= sign
        conservative_Ki *= sign
        conservative_Kd *= sign
        
        self.log(f"   ✅ {self._loop_type}fallback整定: PB={pb_safe:.1f}%, Ti={conservative_Ti:.1f}s, Sign={sign}")
        
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
                                 segments: List = None, segment_results: List = None,
                                 tuning_constraints: dict = None) -> Dict[str, Any]:
        """构建振荡分析整定的输出结果"""
        tuning_constraints = tuning_constraints or {}
        pid_params = osc_result['pid_params']
        osc_info = osc_result['oscillation_info']
        
        valid_mask = hist_data.valid_mask()
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = hist_data.timestamp[valid_mask]
        sv = hist_data.sv[valid_mask]
        
        Pu = osc_info['Pu']
        Ku = pid_params['Ku']  # [FIX] Define Ku early
        pv_range, mv_range = np.ptp(y), np.ptp(u)
        
        if mv_range > 0.1 and pv_range > 0.01:
            K_from_range = pv_range / mv_range
            pv_amplitude = osc_info.get('amplitude', 1.0)
            mv_amplitude = osc_info.get('mv_amplitude', 1.0)
            K_from_osc = pv_amplitude / mv_amplitude if mv_amplitude > 0.01 else K_from_range
            K_est = round(np.clip(max(K_from_range, K_from_osc), 0.1, 10.0), 4)
        else:
            K_est = round(1.0 / Ku if Ku > 0.01 else 1.0, 4)
        
        # [FIX] 使用 pid_params 中的 Kp 符号校正最终 K_est (v3.10)
        # pid_params 的 Sign 是在 _fallback_tuning 中通过 current_pid/corr 确定的
        Kp_sign = np.sign(pid_params['Kp']) if abs(pid_params['Kp']) > 0.001 else 1.0
        K_est *= Kp_sign
        
        # [FIX] 对 integrating_fallback，直接使用真实的 K_int 构建积分器模型，
        # 不再用 _reconstruct_model_from_oscillation 反推出一个假的 FOPDT 参数。
        is_integrating_fb = (osc_result.get('method') == 'integrating_fallback')
        
        if is_integrating_fb:
            # 从 pid_params 中取出真实的 K_int（在 _fallback_tuning 中已保存）
            K_int_real = pid_params.get('K_int', 0.01)
            # 从 pid_params 中取出真实的死区时间
            Ts_val = pid_params.get('Ts', 5.0) or 5.0
            L_est = pid_params.get('L_approx', min(Ts_val * 3.0, 30.0))
            T1_est = 1.0      # 对纯积分器，T1 无物理意义，设为 1.0 避免除零
            K_est_final = K_int_real  # K 直接就是积分增益
            sim_model_type = ModelType.FOPI  # FO_INTEGRATOR
            self.log(f"   🧊 积分器模型构建: K_int={K_int_real:.6f}, L={L_est:.1f}s")
        else:
            T1_est, L_est, K_est_final = self._reconstruct_model_from_oscillation(
                Pu, Ku, K_est, loop_type=self._loop_type
            )
            sim_model_type = ModelType.FOPDT
        
        pv_model = self._simulator.simulate_segmented(
            (K_est_final, T1_est, L_est), 'FOPDT', y, u,
            reset_on_sv_change=True, sv=sv, enable_smooth=True,
            enable_amplitude_calibration=True, enable_offset_correction=True, enable_oscillation_overlay=True
        )
        
        r_squared = calculate_r2(y, pv_model)
        rmse = calculate_rmse(y, pv_model)
        
        temp_fusion = FusionResult(
            model_type=sim_model_type, K=K_est_final, T1=T1_est, T2=0.0, L=L_est,
            global_r2=r_squared, global_rmse=rmse
        )
        
        sv_mean, pv_mean, pv_std = float(np.mean(sv)), float(np.mean(y)), float(np.std(y))
        sp_initial, sp_final = sv_mean, sv_mean + max(pv_std * 2, 1.0)
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            temp_fusion, pid_params, sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_mean, 
            loop_type=self._loop_type, verbose=self._verbose
        )
        
        # [NEW] 置信度驱动的保守策略
        # 如果模型R²很低 (<0.4)，说明模型不可信，闭环验证(跳过)返回的"稳定"也是虚的。
        # 此时应强制进行多轮迭代，使用更保守的参数，而不是在第一轮就退出。
        min_r2_confidence = Config.CLOSED_LOOP.get('min_r2_confidence', 0.4)
        force_conservative = (r_squared < min_r2_confidence)
        
        # 如果已经是物理极限积分兜底参数，连“强制保守迭代”也直接跳过，因为再调只会让它变成一滩死水
        if osc_result.get('method') == 'integrating_fallback':
            # 直接退出保守迭代过程，但保留原始闭环稳定性的诚实评判
            if is_stable:
                self.log("   ✅ integrating_fallback 闭环验证通过！")
            else:
                self.log(f"   ⚠️ integrating_fallback 闭环验证未通过 (超调={cl_metrics.overshoot:.1f}%, 稳态误差={cl_metrics.steady_state_error:.1f}%)")
        else:
            # Fallback 尝试 (非积分过程)
            max_fallback_attempts = 5
            for fallback_attempt in range(1, max_fallback_attempts + 1):
                if (is_stable and not force_conservative) or (fallback_attempt > 1 and is_stable):
                    break
                
                if force_conservative:
                    self.log(f"   ⚠️ 模型置信度低 (R²={r_squared:.2f})，强制进行保守迭代 (第{fallback_attempt}次)...")
                else:
                    self.log(f"   ⚠️ 闭环不稳定，尝试更保守的参数 (第{fallback_attempt}次)...")
                    
                K_approx = pv_range / mv_range if mv_range > 0.1 and pv_range > 0.01 else 1.0
                fallback_confidence = osc_info.get('confidence', 0.3) * (0.5 ** fallback_attempt)
                adjusted_osc_ratio = min(0.95, osc_info.get('oscillation_ratio', 0.5) + 0.15 * fallback_attempt)
                
                pid_params = self._get_conservative_pid_params(
                    Pu, osc_info['Ku'], K_approx=K_approx, reason='data_range',
                    oscillation_ratio=adjusted_osc_ratio,
                    data_quality=osc_result.get('data_quality', 0.5) * (0.8 ** fallback_attempt),
                    nonlinearity=osc_result.get('nonlinearity', 0.0),
                    valve_issues=osc_result.get('valve_issues', {}), confidence=fallback_confidence,
                    tuning_constraints=tuning_constraints
                )
                
                # 无论如何应用符号校正
                pid_params['Kp'] *= Kp_sign
                pid_params['Ki'] *= Kp_sign
                pid_params['Kd'] *= Kp_sign
                pid_params['pb'] = 100.0 / abs(pid_params['Kp']) if abs(pid_params['Kp']) > 1e-6 else 100.0
                pid_params['Ti'] = pid_params['Kp'] / pid_params['Ki'] if abs(pid_params['Ki']) > 1e-6 else 0.0
                pid_params['td'] = pid_params['Kd'] / pid_params['Kp'] if abs(pid_params['Kp']) > 1e-6 else 0.0
                
                is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
                    temp_fusion, pid_params, sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_mean, 
                    loop_type=self._loop_type, verbose=self._verbose
                )
            

        
        # ====== 三层评分 ======
        from ...rating import ModelRating
        import copy
        
        # [FIX] 不再修改原始闭环指标，让评分系统诚实反映真实物理性能。
        # 如果 Level 回路需要更宽容的评分标准，应在 ModelRating 中增加 loop_type 支持。
        cl_metrics_for_rating = cl_metrics

        if osc_result.get('method') == 'integrating_fallback':
            # [FIX] 不再硬编码 8.5 分，使用真实闭环性能评分。
            # 如果参数确实稳定，performance_score 自然会给出高分。
            perf_score, perf_details = ModelRating.performance_score(cl_metrics_for_rating, loop_type=self._loop_type)
            # 方法置信度仍基于工程先验：积分兜底法的方法本身是可靠的
            method_confidence = 0.85
            confidence_details = {'note': 'physics based integrating_fallback'}
            warnings = []
        else:
            # Layer 1: 闭环性能评分
            perf_score, perf_details = ModelRating.performance_score(cl_metrics_for_rating, loop_type=self._loop_type)
            
            # Layer 2: 振荡整定置信度
            from ...config import Config as OscConfig
            osc_config = OscConfig.OSCILLATION_TUNING
            method_confidence, confidence_details, warnings = ModelRating.oscillation_confidence(
                pid_params, osc_info, osc_result, config=osc_config
            )
        
        # Layer 3: 最终综合评分
        model_rating, final_details = ModelRating.final_rating(perf_score, method_confidence)
        
        rating_details = {
            'performance_score': perf_score,
            'performance_details': perf_details,
            'method_confidence': method_confidence,
            'method_confidence_details': confidence_details,
            'final_rating': model_rating,
            'final_details': final_details,
            'warnings': warnings,
        }
        
        closed_loop_info = build_cl_verification(
            cl_metrics, sp_initial, sp_final, pv_mean, is_stable=is_stable
        )
        
        tuning_success = True
        
        tuning_features = {
            'tuning_method': 'oscillation_tuning',
            'Pu': osc_info.get('Pu', 0),
            'Ku': osc_info.get('Ku', 0),
            'amplitude': osc_info.get('amplitude', 0),
            'mv_amplitude': osc_info.get('mv_amplitude', 0),
            'decay_ratio': osc_info.get('decay_ratio', 0),
            'oscillation_type': osc_info.get('oscillation_type', ''),
            'n_cycles': osc_info.get('n_cycles', 0),
            'confidence': osc_info.get('confidence', 0),
            'oscillation_ratio': osc_info.get('oscillation_ratio', 0),
            'K_approx': round(K_est, 4),
            'data_quality': round(osc_result.get('data_quality', 0), 4),
            'nonlinearity': round(osc_result.get('nonlinearity', 0), 4),
            'valve_issues': osc_result.get('valve_issues', {}),
            'method': pid_params.get('method', ''),
            'loop_type': self._loop_type,
        }
        
        # [FIX] integrating_fallback 时输出真实的模型类型和参数
        out_model_type = 'FO_INTEGRATOR' if is_integrating_fb else 'FOPDT'
        out_model_params = {
            'K': K_est_final,  # 对积分器，这里就是 K_int
            'T1': T1_est,
            'T2': 0.0,
            'L': L_est,
        }
        if is_integrating_fb:
            out_model_params['K_int'] = K_est_final  # 显式标记
        
        # 确定整定类型 (P/PI/PID)
        from ...utils import determine_turning_type, get_recommendation
        turning_type = determine_turning_type(
            pid_params['Kp'], pid_params.get('Ti', 0), pid_params.get('Td', 0)
        )
        
        return {
            'success': tuning_success,
            'model_type': out_model_type,
            'model_rating': model_rating,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': out_model_params,
            'pid_parameters': pid_params,
            'turning_type': turning_type,
            'fitting_result': {
                'timestamp': ts.tolist(), 'sv': sv.tolist(), 'pv': y.tolist(), 'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': calculate_r2(y, pv_model),
                'rmse': calculate_rmse(y, pv_model),
                'recommendation': get_recommendation(model_rating)
            },
            'closed_loop_verification': closed_loop_info,
            'tuning_features': tuning_features,
            'rating_details': rating_details
        }
    
    def _reconstruct_model_from_oscillation(self, Pu: float, Ku: float, K_approx: float, loop_type: str) -> Tuple[float, float, float]:
        """
        从振荡参数(Pu, Ku)和稳态增益(K_approx)逆推等效的 FOPDT 模型(T1, L)。
        
        基于 Ziegler-Nichols 频域等效：
        在临界频率 wu = 2pi/Pu 处，开环奈奎斯特曲线必须穿过 (-1, j0)。
        这给出了建立等效模型的增益条件和相位条件。
        """
        import math
        
        # 1. 如果积分特性太强 (比如 Level 回路)，使用纯积分器近似转化
        if loop_type == 'level':
            L = Pu / 4.0
            T1 = max(2.0 * Pu, 100.0)
            # 通过积分增益 K_int 反推模型等效增益 K:
            # Ku 对于积分过程的理论对应关系 K_int ≈ (pi/2) / (Ku * L)
            ku_safe = max(Ku, 0.001)
            k_int = (math.pi / 2.0) / (ku_safe * max(L, 0.1))
            K = k_int * T1
            # 恢复正确的物理过程的正反作用符号
            K *= np.sign(K_approx) if abs(K_approx) > 1e-6 else 1.0
            return round(T1, 4), round(L, 4), round(K, 4)
            
        # 2. 正常自衡过程，使用标准的奈奎斯特反向推导
        try:
            # 稳态增益和临界增益必须有相同的符号（物理意义一致）
            K = K_approx
            Ku_val = Ku * np.sign(K) if K != 0 else Ku
            
            # 理论上要求 |K * Ku| > 1 才能发生持续振荡。
            # 如果不满足，说明 K_approx 从时域估计得太保守，强行提起到 1.05 保证方程有解
            gain_product = abs(K * Ku_val)
            if gain_product <= 1.0:
                # 保持符号，放大 K 使得乘积大于 1
                K = 1.05 / Ku_val
                
            omega_u = 2.0 * math.pi / Pu
            
            # 幅值方程反推时间常数 T1
            inside_sqrt = (K * Ku_val) ** 2 - 1.0
            T1 = math.sqrt(max(0.01, inside_sqrt)) / omega_u
            
            # 相位方程反推滞后时间 L
            phi_t = math.atan(omega_u * T1)
            phase_lag = math.pi - phi_t
            L = phase_lag / omega_u
            
            # 回路约束：防止“幻影慢系统”造成仿真分数暴跌
            if loop_type == 'flow':
                T1 = min(T1, 40.0)
                L = min(L, 15.0)
            elif loop_type == 'pressure':
                T1 = min(T1, 30.0)
                L = min(L, 10.0)
                
            return round(float(T1), 4), round(float(max(L, 0.01)), 4), round(float(K), 4)
            
        except Exception as e:
            self.log(f"   ⚠️ 模型数学逆推失败: {e}，回退到经验比例")
            # 出错时回退到 Yuwana-Seborg 经验公式
            return round(Pu, 4), round(Pu/4.0, 4), round(K_approx, 4)
    
    def _build_segment_info(self, segments: List, segment_results: List) -> List[Dict]:
        """构建段信息用于可视化（委托给 utils.build_segment_info）"""
        from ...utils import build_segment_info
        return build_segment_info(segments, segment_results)
