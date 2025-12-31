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
from typing import List, Dict, Any, Optional, Tuple

from .types import ValveIssues, ConservativePIDParams

from ..config import Config, ModelType
from ..data_models import SegmentResult, HistoricalData, FusionResult
from ..utils import calculate_r2, calculate_rmse
from ..logger import LoggerMixin
from .loop_type_strategies import get_loop_strategy, LoopTypeStrategy


class OscillationTuner(LoggerMixin):
    """
    振荡数据整定器
    
    当常规模型拟合失败且检测到高振荡时，使用临界法进行PID整定。
    
    LLM 增强：
    - 支持使用大模型决策保守参数
    - 只在临界法整定时使用 LLM，正常整定不需要
    """
    
    def __init__(self, pid_calculator, simulator, verbose: bool = False, 
                 llm_client=None, loop_type: str = "", loop_name: str = ""):
        """
        Args:
            pid_calculator: PIDCalculator 实例
            simulator: ModelSimulator 实例
            verbose: 是否输出详细日志
            llm_client: LLM 客户端（可选），用于决策保守参数
            loop_type: 回路类型 (flow/temperature/pressure/level)
            loop_name: 回路名称
        """
        self._init_logger(verbose)
        self._pid_calculator = pid_calculator
        self._simulator = simulator
        self._epsilon = Config.EPSILON
        
        # LLM 相关
        self._llm_client = llm_client
        self._llm_advisor = None
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        
        if llm_client is not None:
            self._init_llm_advisor(llm_client)
    
    def set_llm_client(self, llm_client, loop_type: str = "", loop_name: str = ""):
        """
        设置 LLM 客户端，启用 LLM 决策保守参数
        
        Args:
            llm_client: LLM 客户端
            loop_type: 回路类型
            loop_name: 回路名称
        """
        self._llm_client = llm_client
        self._loop_type = loop_type
        self._loop_name = loop_name
        self._strategy = get_loop_strategy(loop_type)
        self._init_llm_advisor(llm_client)
    
    def _init_llm_advisor(self, llm_client):
        """初始化 LLM 顾问"""
        try:
            from .llm_conservative_advisor import LLMOscillationTuningAdvisor
            self._llm_advisor = LLMOscillationTuningAdvisor(
                llm_client=llm_client,
                verbose=self._verbose
            )
        except ImportError:
            self._llm_advisor = None
    
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
    
    def _calculate_envelope_ratio(self, pv: np.ndarray) -> float:
        """
        计算振荡包络比（振荡幅度相对于数据范围的比例）
        
        Args:
            pv: 过程变量数组
        
        Returns:
            envelope_ratio: 包络比 [0, 1]，越大表示振荡幅度越大
        """
        if len(pv) < 20:
            return 0.0
        
        pv_range = np.ptp(pv)
        if pv_range < self._epsilon:
            return 0.0
        
        # 计算上下包络线
        window = max(5, len(pv) // 20)
        y_upper = np.array([np.max(pv[max(0,i-window):min(len(pv),i+window+1)]) for i in range(len(pv))])
        y_lower = np.array([np.min(pv[max(0,i-window):min(len(pv),i+window+1)]) for i in range(len(pv))])
        envelope_width = np.median(y_upper - y_lower)
        envelope_ratio = envelope_width / pv_range
        
        return float(np.clip(envelope_ratio, 0.0, 1.0))
    
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
            # 改进：计算 envelope_ratio 来检测大幅度振荡
            # envelope_ratio 高说明振荡幅度大，即使 oscillation_ratio 低也应该触发
            envelope_ratio = self._calculate_envelope_ratio(seg.pv)
            
            # 综合判断是否为振荡数据：
            # 1. oscillation_ratio > threshold (高频振荡)
            # 2. envelope_ratio > 0.5 (大幅度振荡)
            # 3. 两者综合得分 > 0.3
            osc_score = 0.4 * result.oscillation_ratio + 0.6 * envelope_ratio
            is_oscillating = (result.oscillation_ratio > osc_ratio_threshold or 
                             envelope_ratio > 0.5 or 
                             osc_score > 0.3)
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
            # ========== 通用fallback机制 ==========
            # 当振荡分析失败时，使用基于数据特征的保守参数
            if oscillating_segments:
                self.log(f"   🔄 {self._loop_type}回路fallback: 使用数据特征估算参数")
                return self._generic_fallback(oscillating_segments, segments, segment_results)
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
        
        # 获取 Ku/Pu 估计的置信度（用于动态调整 pb_max）
        confidence = best_analysis['osc_info'].get('confidence', 0.5)
        
        pid_params = self._get_conservative_pid_params(
            Pu, Ku, 
            K_approx=apparent_gain,
            reason=reason,
            oscillation_ratio=oscillation_ratio,
            data_quality=data_quality,
            nonlinearity=nonlinearity,
            valve_issues=valve_issues,
            confidence=confidence
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
    
    # ========== 辅助方法：拆分自 _get_conservative_pid_params ==========
    
    def _get_llm_strategy(self, Pu: float, Ku: float, K_approx: float,
                          oscillation_ratio: float, data_quality: float,
                          nonlinearity: float, valve_issues: Dict,
                          confidence: float) -> Tuple[Any, Optional[Dict]]:
        """
        获取 LLM 策略参数（如果启用且适用）
        
        Returns:
            (llm_strategy, llm_decision_info) 元组
        """
        osc_config = Config.OSCILLATION_TUNING
        enable_llm = osc_config.get('enable_llm', True)
        
        if not enable_llm or self._llm_advisor is None:
            return None, None
        
        # 判断是否为困难场景
        has_valve_issues = valve_issues.get('has_deadband', False) or valve_issues.get('has_stiction', False)
        should_use_llm = (
            has_valve_issues or 
            data_quality < 0.5 or 
            nonlinearity > 0.5 or 
            confidence < 0.5 or
            oscillation_ratio > 0.7
        )
        
        if not should_use_llm:
            self.log(f"   📊 场景简单（质量={data_quality:.2f}, 置信={confidence:.2f}），跳过LLM，使用规则引擎")
            return None, None
        
        self.log(f"   🤖 困难场景（阀门={has_valve_issues}, 质量={data_quality:.2f}, 置信={confidence:.2f}），启用LLM")
        try:
            llm_strategy = self._llm_advisor.decide_conservative_strategy(
                Pu=Pu, Ku=Ku, K_approx=K_approx,
                oscillation_ratio=oscillation_ratio,
                data_quality=data_quality,
                nonlinearity=nonlinearity,
                valve_issues=valve_issues,
                confidence=confidence,
                loop_type=self._loop_type,
                loop_name=self._loop_name
            )
            
            if llm_strategy is not None:
                llm_decision_info = {
                    'strategy_params': {
                        'safety_factor': llm_strategy.safety_factor,
                        'pb_extra_factor': llm_strategy.pb_extra_factor,
                        'ti_multiplier': llm_strategy.ti_multiplier,
                        'enable_derivative': llm_strategy.enable_derivative,
                        'td_factor': llm_strategy.td_factor,
                    },
                    'reasoning': llm_strategy.reasoning,
                    'confidence': llm_strategy.confidence,
                    'risk_factors': llm_strategy.risk_factors,
                    'recommendations': llm_strategy.recommendations
                }
                return llm_strategy, llm_decision_info
        except Exception as e:
            self.log(f"   ⚠️ LLM 策略决策失败: {e}，使用规则引擎默认参数")
        
        return None, None
    
    def _calculate_base_pb(self, Ku: float, K_approx: float, Pu: float) -> Tuple[float, float, float, float]:
        """
        计算基础 pb 值
        
        Returns:
            (pb_base, pb_from_K, pb_from_Ku, slow_factor) 元组
        """
        osc_config = Config.OSCILLATION_TUNING
        
        # 1. 基于过程增益的 pb
        pb_from_k_factor = osc_config.get('pb_from_k_factor', 1.5)
        if K_approx > 0.01:
            pb_from_K = 100.0 * K_approx * pb_from_k_factor
        else:
            pb_from_K = 80.0
        
        # 2. 基于临界参数的 pb
        kp_from_ku_factor = osc_config.get('kp_from_ku_factor', 0.2)
        if Ku > 0.1:
            Kp_from_Ku = kp_from_ku_factor * Ku
            pb_from_Ku = 100.0 / max(Kp_from_Ku, 0.1)
        else:
            pb_from_Ku = 100.0
        
        # 3. 慢系统调整因子
        pu_thresholds = osc_config.get('slow_system_pu_thresholds', [30.0, 15.0])
        slow_factors = osc_config.get('slow_system_factors', [1.3, 1.15, 1.0])
        slow_factor = slow_factors[-1]
        for i, threshold in enumerate(pu_thresholds):
            if Pu > threshold:
                slow_factor = slow_factors[i]
                break
        
        # 4. 综合计算
        pb_base = max(pb_from_K, pb_from_Ku) * slow_factor
        
        return pb_base, pb_from_K, pb_from_Ku, slow_factor
    
    def _apply_quality_factors(self, pb_base: float, reason: str,
                               data_quality: float, nonlinearity: float,
                               valve_issues: Dict) -> float:
        """
        应用数据质量、非线性、阀门问题等因子
        
        Returns:
            调整后的 pb 值
        """
        osc_config = Config.OSCILLATION_TUNING
        
        # 1. 原因微调
        if reason == 'high_gain':
            high_gain_factor = osc_config.get('high_gain_extra_factor', 1.1)
            pb_base *= high_gain_factor
        
        # 2. 数据质量因子
        quality_threshold = osc_config.get('quality_adjustment_threshold', 0.5)
        quality_adj_factor = osc_config.get('quality_adjustment_factor', 0.6)
        if data_quality < quality_threshold:
            quality_factor = 1.0 + (quality_threshold - data_quality) * quality_adj_factor
            pb_base *= quality_factor
            self.log(f"   📊 数据质量调整: 质量={data_quality:.2f}, 因子=×{quality_factor:.2f}")
        
        # 3. 非线性因子
        nonlin_threshold = osc_config.get('nonlinearity_threshold', 0.5)
        nonlin_adj_factor = osc_config.get('nonlinearity_factor', 0.4)
        if nonlinearity > nonlin_threshold:
            nonlin_factor = 1.0 + (nonlinearity - nonlin_threshold) * nonlin_adj_factor
            pb_base *= nonlin_factor
            self.log(f"   📊 非线性调整: 非线性={nonlinearity:.2f}, 因子=×{nonlin_factor:.2f}")
        
        # 4. 阀门问题因子
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
        
        return pb_base
    
    def _apply_extreme_factors(self, pb_base: float, K_approx: float, 
                               Pu: float, oscillation_ratio: float) -> Tuple[float, float]:
        """
        应用极端场景因子（高增益、大滞后、极端振荡）
        
        Returns:
            (调整后的 pb, delay_ratio) 元组
        """
        # 1. 极高增益因子
        if K_approx > 4.0:
            if K_approx > 6.0:
                extreme_gain_factor = 1.0 + (K_approx - 4.0) * 0.25
                extreme_gain_factor = min(extreme_gain_factor, 3.0)
            else:
                extreme_gain_factor = 1.0 + (K_approx - 4.0) * 0.15
                extreme_gain_factor = min(extreme_gain_factor, 2.0)
            pb_base *= extreme_gain_factor
            self.log(f"   ⚠️ 极高增益场景(K={K_approx:.1f}): 保守因子 ×{extreme_gain_factor:.2f}")
        
        # 2. 回路类型特定调整
        pb_base = self._strategy.adjust_pb_for_extreme(pb_base, K_approx, Pu, log_func=self.log)
        
        # 3. 大滞后比因子
        estimated_L = Pu / 4.0
        T1_approx = Pu * (1.0 + 1.0 / max(K_approx, 0.5)) / 4.0
        delay_ratio = estimated_L / max(T1_approx, 1.0)
        
        if delay_ratio > 0.8:
            delay_factor = 2.5
            self.log(f"   ⚠️ 极大滞后比(L/T1≈{delay_ratio:.2f}): 极端保守 ×{delay_factor:.2f}")
        elif delay_ratio > 0.6:
            delay_factor = 1.6 + (delay_ratio - 0.6) * 4.0
            delay_factor = min(delay_factor, 2.4)
            self.log(f"   ⚠️ 大滞后比(L/T1≈{delay_ratio:.2f}): 显著保守 ×{delay_factor:.2f}")
        elif delay_ratio > 0.4:
            delay_factor = 1.3 + (delay_ratio - 0.4) * 1.5
            self.log(f"   ⚠️ 中等滞后比(L/T1≈{delay_ratio:.2f}): 适度保守 ×{delay_factor:.2f}")
        else:
            delay_factor = 1.0
        pb_base *= delay_factor
        
        # 4. 极端振荡场景
        if oscillation_ratio > 0.85:
            extreme_osc_factor = 1.2 + (oscillation_ratio - 0.85) * 2.0
            extreme_osc_factor = min(extreme_osc_factor, 1.6)
            pb_base *= extreme_osc_factor
            self.log(f"   ⚠️ 极端振荡场景(ratio={oscillation_ratio:.2f}): 保守因子 ×{extreme_osc_factor:.2f}")
        
        return pb_base, delay_ratio
    
    def _apply_oscillation_adjustment(self, pb_base: float, oscillation_ratio: float,
                                      llm_strategy: Any) -> Tuple[float, float]:
        """
        应用振荡比自适应调整（渐进式策略）
        
        Returns:
            (调整后的 pb, safety_factor) 元组
        """
        osc_config = Config.OSCILLATION_TUNING
        
        pb_gradient = osc_config.get('pb_gradient', 2.0)
        pb_osc_start = osc_config.get('pb_oscillation_start', 0.4)
        safety_base = osc_config.get('safety_factor_base', 1.4)
        safety_thresholds = osc_config.get('safety_factor_thresholds', [0.5, 0.7, 0.85])
        safety_slopes = osc_config.get('safety_factor_slopes', [0.5, 1.0, 2.0])
        
        # 计算安全系数
        if llm_strategy is not None:
            safety_factor = llm_strategy.safety_factor
            self.log(f"   🤖 LLM 策略: safety_factor={safety_factor:.2f}, "
                    f"pb_extra={llm_strategy.pb_extra_factor:.2f}, "
                    f"ti_mult={llm_strategy.ti_multiplier:.2f}")
        else:
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
        
        # 计算综合保守乘数
        total_multiplier = safety_factor
        
        if llm_strategy is not None:
            total_multiplier *= llm_strategy.pb_extra_factor
        
        if oscillation_ratio > pb_osc_start:
            effective_osc = oscillation_ratio - pb_osc_start
            osc_multiplier = 1.0 + np.sqrt(effective_osc) * pb_gradient
            total_multiplier *= osc_multiplier
            
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
        
        return pb_base, safety_factor
    
    def _apply_pb_bounds(self, pb_base: float, K_approx: float,
                        confidence: float, reason: str,
                        pb_from_K: float, pb_from_Ku: float,
                        Pu: float, Ku: float, slow_factor: float,
                        delay_ratio: float = 0.0) -> float:
        """
        应用 pb 边界限制（动态调整）
        
        Returns:
            限制后的 pb 值
        """
        osc_config = Config.OSCILLATION_TUNING
        
        pb_min_base = osc_config.get('pb_min', 80.0)
        pb_max_config = osc_config.get('pb_max', 600.0)
        
        # 基于置信度的 pb_max 分级
        if confidence >= 0.8:
            pb_max = min(pb_max_config, 400.0)
            self.log(f"   📊 高置信度({confidence:.2f}): pb_max=400")
        elif confidence >= 0.5:
            pb_max = min(pb_max_config, 600.0)
        else:
            pb_max = min(pb_max_config * 1.3, 800.0)
            self.log(f"   📊 低置信度({confidence:.2f}): pb_max={pb_max:.0f}")
        
        # 动态调整pb下限
        pb_k_factor = osc_config.get('pb_k_adjustment_factor', 0.3)
        if K_approx > 0.01:
            pb_min_dynamic = pb_min_base * (1.0 + pb_k_factor / K_approx)
            pb_min_dynamic = min(pb_min_dynamic, 400.0)
        else:
            pb_min_dynamic = 400.0
        pb_min = max(pb_min_base, pb_min_dynamic)
        
        # low_gain 模式额外处理
        if reason == 'low_gain':
            ku_k_extreme_factor = osc_config.get('ku_k_extreme_pb_factor', 1.5)
            pb_min = pb_min * ku_k_extreme_factor
            pb_min = min(pb_min, 500.0)
            self.log(f"   📊 Ku/K异常模式: pb下限={pb_min:.0f}% (K={K_approx:.3f})")
        else:
            self.log(f"   📊 动态pb下限: {pb_min:.0f}% (K={K_approx:.3f})")
        
        pb_safe = np.clip(pb_base, pb_min, pb_max)
        
        self.log(f"   📊 动态pb计算: K={K_approx:.3f}→pb={pb_from_K:.1f}, "
                f"Ku={Ku:.3f}→pb={pb_from_Ku:.1f}, Pu={Pu:.1f}s(×{slow_factor}), "
                f"最终pb={pb_safe:.1f}")
        
        return pb_safe
    
    def _calculate_conservative_ti_td(self, Pu: float, oscillation_ratio: float,
                                      K_approx: float, llm_strategy: Any) -> Tuple[float, float, float, float]:
        """
        计算保守的 Ti 和 Td 值
        
        Returns:
            (Ti, Td, ti_multiplier, td_multiplier) 元组
        """
        osc_config = Config.OSCILLATION_TUNING
        
        # Ti 计算
        ti_min_base = osc_config.get('ti_min_base', 1.5)
        base_Ti = max(Pu / 2, ti_min_base) if Pu > 0 else 2.0
        
        # 振荡调整因子
        ti_osc_start = osc_config.get('ti_osc_start', 0.6)
        ti_osc_factor = osc_config.get('ti_osc_factor', 0.5)
        if oscillation_ratio > ti_osc_start:
            ti_multiplier = 1.0 + np.sqrt(oscillation_ratio - ti_osc_start) * ti_osc_factor
        else:
            ti_multiplier = 1.0
        
        # 慢系统调整
        ti_slow_thresholds = osc_config.get('ti_slow_pu_thresholds', [20.0, 10.0])
        ti_slow_factors = osc_config.get('ti_slow_factors', [1.1, 1.05, 1.0])
        for i, threshold in enumerate(ti_slow_thresholds):
            if Pu > threshold:
                ti_multiplier *= ti_slow_factors[i]
                break
        
        # 回路类型特定调整
        if llm_strategy is None:
            ti_multiplier = self._strategy.adjust_ti_multiplier(
                ti_multiplier, K_approx, Pu, oscillation_ratio, osc_config, log_func=self.log
            )
        else:
            ti_multiplier *= llm_strategy.ti_multiplier
            self.log(f"   🤖 LLM Ti调整: 基础乘数×LLM乘数={ti_multiplier:.2f}")
        
        conservative_Ti = base_Ti * ti_multiplier
        ti_range = osc_config.get('ti_range', [1.5, 10.0])
        conservative_Ti = np.clip(conservative_Ti, ti_range[0], ti_range[1])
        
        # Td 计算
        conservative_Td = 0.0
        td_multiplier = 0.0
        enable_derivative = osc_config.get('enable_adaptive_derivative', True)
        derivative_threshold = osc_config.get('derivative_oscillation_threshold', 0.5)
        
        if llm_strategy is not None:
            enable_derivative = llm_strategy.enable_derivative
        
        if enable_derivative and (oscillation_ratio > derivative_threshold or (llm_strategy and llm_strategy.enable_derivative)):
            td_base_divisor = osc_config.get('td_base_divisor', 8.0)
            base_Td = Pu / td_base_divisor if Pu > 0 else 0.5
            
            td_mult_factor = osc_config.get('td_multiplier_factor', 1.5)
            effective_osc = max(0, oscillation_ratio - derivative_threshold)
            td_multiplier = 1.0 + np.sqrt(effective_osc) * td_mult_factor
            
            if llm_strategy is not None and llm_strategy.td_factor > 0:
                td_multiplier *= llm_strategy.td_factor
                self.log(f"   🤖 LLM Td调整: td_factor={llm_strategy.td_factor:.2f}")
            
            conservative_Td = base_Td * td_multiplier
            td_range = osc_config.get('td_range', [0.3, 3.0])
            conservative_Td = np.clip(conservative_Td, td_range[0], td_range[1])
            
            self.log(f"   📊 自适应Ti/Td: Ti={conservative_Ti:.2f}s(×{ti_multiplier:.2f}), "
                    f"Td={conservative_Td:.2f}s(×{td_multiplier:.2f})")
        else:
            self.log(f"   📊 自适应Ti: Ti={conservative_Ti:.2f}s(×{ti_multiplier:.2f})")
        
        return conservative_Ti, conservative_Td, ti_multiplier, td_multiplier
    
    def _build_conservative_pid_result(self, pb: float, Ti: float, Td: float,
                                       Pu: float, Ku: float, reason: str,
                                       llm_strategy: Any,
                                       llm_decision_info: Optional[Dict]) -> Dict[str, Any]:
        """构建保守 PID 参数结果"""
        conservative_Kp = 100.0 / pb
        conservative_Ki = conservative_Kp / Ti
        conservative_Kd = conservative_Kp * Td if Td > 0 else 0.0
        
        if Td > 0:
            self.log(f"   📊 添加微分作用: Kd={conservative_Kd:.4f} (Kp×Td，用于抑制振荡)")
        
        result = {
            'Kp': round(conservative_Kp, 2),
            'Ki': round(conservative_Ki, 2),
            'Kd': round(conservative_Kd, 2),
            'Ti': round(Ti, 4),
            'Td': round(Td, 4) if Td > 0 else 0.0,
            'method': f'{reason}_llm' if llm_strategy else f'{reason}_adaptive',
            'Pu': round(Pu, 2),
            'Ku': round(Ku, 2),
            'pb': round(pb, 2)
        }
        
        if llm_decision_info is not None:
            result['llm_decision'] = llm_decision_info
            self.log(f"   🤖 LLM 决策理由: {llm_decision_info['reasoning']}")
            if llm_decision_info.get('risk_factors'):
                self.log(f"      风险: {', '.join(llm_decision_info['risk_factors'])}")
            if llm_decision_info.get('recommendations'):
                self.log(f"      建议: {', '.join(llm_decision_info['recommendations'])}")
        
        return result
    
    # ========== 重构后的主方法 ==========
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, 
                                      K_approx: float = 1.0,
                                      reason: str = 'generic',
                                      oscillation_ratio: float = 0.0,
                                      data_quality: float = 0.5,
                                      nonlinearity: float = 0.0,
                                      valve_issues: Dict = None,
                                      confidence: float = 0.5) -> Dict[str, Any]:
        """
        获取保守PID参数（动态计算pb，借鉴大模型调参经验）
        
        本方法已重构为调用多个辅助方法，提高可读性和可维护性。
        
        Args:
            Pu: 临界周期
            Ku: 临界增益
            K_approx: 估计的过程增益
            reason: 使用保守参数的原因
            oscillation_ratio: 振荡比（用于自适应调整）
            data_quality: 数据质量评分 (0-1)，越低越需要保守
            nonlinearity: 非线性程度 (0-1)
            valve_issues: 阀门问题检测结果
            confidence: Ku/Pu估计的置信度 (0-1)，越高允许更激进
        
        Returns:
            保守PID参数字典
        """
        if valve_issues is None:
            valve_issues = {}
        
        # 1. 获取 LLM 策略（如果启用）
        llm_strategy, llm_decision_info = self._get_llm_strategy(
            Pu, Ku, K_approx, oscillation_ratio, data_quality,
            nonlinearity, valve_issues, confidence
        )
        
        # 2. 计算基础 pb
        pb_base, pb_from_K, pb_from_Ku, slow_factor = self._calculate_base_pb(Ku, K_approx, Pu)
        
        # 3. 应用质量因子（数据质量、非线性、阀门问题）
        pb_base = self._apply_quality_factors(pb_base, reason, data_quality, nonlinearity, valve_issues)
        
        # 4. 应用极端场景因子（高增益、大滞后、极端振荡）
        pb_base, delay_ratio = self._apply_extreme_factors(pb_base, K_approx, Pu, oscillation_ratio)
        
        # 5. 应用振荡比自适应调整
        pb_base, safety_factor = self._apply_oscillation_adjustment(pb_base, oscillation_ratio, llm_strategy)
        
        # 6. 应用 pb 边界限制
        pb_safe = self._apply_pb_bounds(
            pb_base, K_approx, confidence, reason,
            pb_from_K, pb_from_Ku, Pu, Ku, slow_factor, delay_ratio
        )
        
        # 7. 计算 Ti/Td
        Ti, Td, ti_multiplier, td_multiplier = self._calculate_conservative_ti_td(
            Pu, oscillation_ratio, K_approx, llm_strategy
        )
        
        # 8. 构建并返回结果
        return self._build_conservative_pid_result(
            pb_safe, Ti, Td, Pu, Ku, reason, llm_strategy, llm_decision_info
        )
    
    def _calculate_oscillation_rating(self, is_stable: bool, cl_metrics: Any,
                                       pid_params: Dict, osc_info: Dict,
                                       osc_result: Dict) -> Tuple[float, Dict, List[str]]:
        """
        计算振荡整定的综合评分
        
        Args:
            is_stable: 闭环是否稳定
            cl_metrics: 闭环性能指标
            pid_params: PID参数
            osc_info: 振荡信息
            osc_result: 振荡整定结果
            
        Returns:
            (model_rating, rating_details, warnings) 元组
        """
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
            osc_score = 4.5 - (oscillation_ratio - 0.8) * 15
        
        # 原始数据质量因子
        quality_penalty = max(0, (0.4 - raw_data_quality) * 3)
        nonlin_penalty = max(0, (nonlinearity - 0.5) * 2)
        
        data_quality_score = osc_score - quality_penalty - nonlin_penalty
        data_quality_score = max(1.0, min(8.0, data_quality_score))
        
        rating_details['data_quality_score'] = round(data_quality_score, 2)
        rating_details['oscillation_ratio'] = round(oscillation_ratio, 2)
        rating_details['raw_data_quality'] = round(raw_data_quality, 2)
        rating_details['nonlinearity'] = round(nonlinearity, 2)
        
        # 3. 参数边界距离评分 (0-10) - 权重 20%
        pb = pid_params.get('pb', 200)
        pb_min = Config.OSCILLATION_TUNING.get('pb_min', 120.0)
        pb_max = Config.OSCILLATION_TUNING.get('pb_max', 600.0)
        pb_range = pb_max - pb_min
        pb_margin = min(pb - pb_min, pb_max - pb) / (pb_range / 2)
        
        boundary_score = 5.0 + pb_margin * 5.0
        if pb <= pb_min * 1.05 or pb >= pb_max * 0.95:
            boundary_score = 3.0
        
        Ti = pid_params.get('Ti', 2.5)
        if Ti <= 1.6 or Ti >= 9.5:
            boundary_score -= 1.0
        
        boundary_score = min(10.0, max(0.0, boundary_score))
        rating_details['boundary_score'] = round(boundary_score, 2)
        rating_details['pb'] = round(pb, 2)
        
        # 4. 整定方法评分 (0-10) - 权重 20%
        method = pid_params.get('method', 'unknown')
        if 'low_gain' in method or 'high_gain' in method:
            method_score = 5.0
        elif 'oscillation' in method:
            method_score = 6.0
        else:
            method_score = 5.5
        
        if pid_params.get('Kd', 0) > 0:
            method_score += 0.5
        
        rating_details['method_score'] = round(method_score, 2)
        rating_details['method'] = method
        
        # 综合评分
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
            model_rating = min(model_rating, 4.0)
            warnings.append('闭环仿真不稳定')
        
        if oscillation_ratio > 0.9:
            model_rating = min(model_rating, 6.0)
            warnings.append(f'极高振荡({oscillation_ratio:.0%})，建议人工排查根因')
        elif oscillation_ratio > 0.85:
            model_rating = min(model_rating, 6.5)
            warnings.append(f'高振荡({oscillation_ratio:.0%})')
        
        if pb <= pb_min * 1.02 or pb >= pb_max * 0.98:
            model_rating = min(model_rating, 5.5)
            warnings.append('PID参数触达边界')
        
        if raw_data_quality < 0.3:
            model_rating = min(model_rating, 5.5)
            warnings.append(f'数据质量极差({raw_data_quality:.2f})')
        
        if nonlinearity > 0.6:
            model_rating = min(model_rating, 6.0)
            warnings.append(f'高非线性({nonlinearity:.2f})，可能存在阀门问题')
        
        # 阀门问题检测
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
        
        # 综合风险等级
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
        
        return model_rating, rating_details, warnings
    
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
        
        # 如果闭环不稳定，尝试更保守的参数（最多尝试3次）
        max_fallback_attempts = 3
        fallback_attempt = 0
        
        while not is_stable and fallback_attempt < max_fallback_attempts:
            fallback_attempt += 1
            self.log(f"   ⚠️ 闭环不稳定，尝试更保守的参数 (第{fallback_attempt}次)...")
            
            K_approx = pv_range / mv_range if mv_range > 0.1 and pv_range > 0.01 else 1.0
            
            # 获取数据质量、非线性和阀门问题信息（用于保守策略）
            fallback_data_quality = osc_result.get('data_quality', 0.5)
            fallback_nonlinearity = osc_result.get('nonlinearity', 0.0)
            fallback_valve_issues = osc_result.get('valve_issues', {})
            fallback_osc_ratio = osc_info.get('oscillation_ratio', 0.5)
            
            # 每次迭代降低置信度，使参数更保守
            # 第1次: 0.15, 第2次: 0.075, 第3次: 0.0375
            fallback_confidence = osc_info.get('confidence', 0.3) * (0.5 ** fallback_attempt)
            
            # 每次迭代增加振荡比，使参数更保守
            adjusted_osc_ratio = min(0.95, fallback_osc_ratio + 0.15 * fallback_attempt)
            
            fallback_pid = self._get_conservative_pid_params(
                Pu, osc_info['Ku'], K_approx=K_approx, reason='data_range',
                oscillation_ratio=adjusted_osc_ratio,
                data_quality=fallback_data_quality * (0.8 ** fallback_attempt),  # 降低数据质量
                nonlinearity=fallback_nonlinearity,
                valve_issues=fallback_valve_issues,
                confidence=fallback_confidence
            )
            
            self.log(f"   ⚠️ 第{fallback_attempt}次fallback: pb={fallback_pid['pb']:.1f}, "
                    f"Kp={fallback_pid['Kp']:.4f}, Ki={fallback_pid['Ki']:.4f}")
            pid_params = fallback_pid
            
            is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
                temp_fusion, fallback_pid,
                sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
                verbose=self._verbose
            )
            
            if is_stable:
                self.log(f"   ✅ 第{fallback_attempt}次fallback成功，闭环稳定")
                break
        
        # ========== 综合评分策略 ==========
        model_rating, rating_details, warnings = self._calculate_oscillation_rating(
            is_stable=is_stable,
            cl_metrics=cl_metrics,
            pid_params=pid_params,
            osc_info=osc_info,
            osc_result=osc_result
        )
        
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
        
        # 对于慢系统（Pu > 100s），即使内部仿真不稳定，也认为整定成功
        # 因为内部仿真时间可能不够长
        # 但会在 model_rating 中反映不确定性
        tuning_success = is_stable
        if not is_stable and Pu > 100.0:
            # 检查是否在收敛（衰减比 < 1.2）
            if cl_metrics.decay_ratio < 1.2:
                tuning_success = True
                self.log(f"   ℹ️ 慢系统(Pu={Pu:.0f}s)内部仿真未完全收敛，但衰减比={cl_metrics.decay_ratio:.2f}<1.2，认为整定成功")
            elif self._loop_type == 'level':
                # 液位回路特殊处理：即使衰减比较高，也给予成功机会
                tuning_success = True
                model_rating = min(model_rating, 5.0)  # 但降低评分
                warnings.append(f'慢液位系统(Pu={Pu:.0f}s)，内部仿真未收敛，建议人工验证')
                self.log(f"   ⚠️ 慢液位系统(Pu={Pu:.0f}s)内部仿真未收敛，但仍返回参数供人工验证")
        
        result = {
            'success': tuning_success,
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
                'method': pid_params.get('method', 'oscillation_critical'),
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

    def _fallback_tuning(self, oscillating_segments: List, 
                          segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> Optional[Dict]:
        """
        统一的 fallback 整定机制
        
        当振荡分析无法提取有效特征时，使用数据特征和策略模式
        获取回路特定参数进行保守整定。
        
        Args:
            oscillating_segments: 振荡段列表 [(idx, seg, result), ...]
            segments: 原始段数据列表
            segment_results: 段结果列表
        
        Returns:
            fallback整定结果，如果无法估算则返回 None
        """
        osc_config = Config.OSCILLATION_TUNING
        
        # 获取策略参数
        fallback_params = self._strategy.get_fallback_params()
        pb_base = fallback_params['pb_base']
        t1_divisor = fallback_params['t1_divisor']
        t1_min = fallback_params['t1_min']
        ti_multiplier = fallback_params['ti_multiplier']
        
        # 液位回路的最小数据点要求更高
        min_points = 50 if self._loop_type == 'level' else 30
        
        # 选择数据量最大的段进行分析
        best_seg = None
        best_result = None
        max_points = 0
        
        for idx, seg, result in oscillating_segments:
            if len(seg.pv) > max_points:
                max_points = len(seg.pv)
                best_seg = seg
                best_result = result
        
        if best_seg is None or max_points < min_points:
            self.log(f"   ⚠️ {self._loop_type}fallback: 数据量不足({max_points}/{min_points})")
            return None
        
        # 估算过程增益 K
        pv_range = np.ptp(best_seg.pv)
        mv_range = np.ptp(best_seg.mv)
        
        if mv_range < 0.1 or pv_range < 0.01:
            self.log(f"   ⚠️ {self._loop_type}fallback: MV或PV变化范围过小")
            return None
        
        K_approx = pv_range / mv_range
        K_approx = np.clip(K_approx, 0.1, 10.0)
        
        # 估算采样周期
        dt = 1.0
        if len(best_seg.timestamp) > 1:
            dt = (best_seg.timestamp[1] - best_seg.timestamp[0]) / 1000
        
        data_duration = len(best_seg.pv) * dt
        
        # 使用策略参数估算时间常数 T1
        T1_approx = max(data_duration / t1_divisor, t1_min)
        
        # 估算滞后 L（使用交叉相关法更准确估算）
        osc_config = Config.OSCILLATION_TUNING
        large_delay_threshold = osc_config.get('large_delay_absolute_threshold', 15.0)
        
        # 基于 MV-PV 交叉相关估算延迟
        from scipy import signal
        pv_smooth = np.convolve(best_seg.pv, np.ones(5)/5, mode='same')
        mv_smooth = np.convolve(best_seg.mv, np.ones(5)/5, mode='same')
        correlation = signal.correlate(pv_smooth - np.mean(pv_smooth), 
                                       mv_smooth - np.mean(mv_smooth), mode='full')
        lags = signal.correlation_lags(len(pv_smooth), len(mv_smooth), mode='full')
        # 延迟估计：找到最大相关系数对应的滞后
        max_corr_idx = np.argmax(np.abs(correlation))
        estimated_delay_samples = lags[max_corr_idx]
        L_approx = max(abs(estimated_delay_samples) * dt, T1_approx / 5)
        
        # 检测是否为大滞后系统
        delay_ratio = L_approx / max(T1_approx, 1.0)
        is_large_delay = L_approx > large_delay_threshold or delay_ratio > 0.5
        
        if is_large_delay:
            self.log(f"   📊 检测到大滞后: L≈{L_approx:.1f}s, delay_ratio={delay_ratio:.2f}")
            # 大滞后时增加 pb 和 Ti 保守度
            pb_base *= osc_config.get('large_delay_pb_boost', 1.8)
            ti_multiplier *= osc_config.get('large_delay_ti_boost', 1.5)
        
        # 估算临界周期 Pu
        pu_min = 20.0 if self._loop_type == 'level' else 10.0
        Pu_approx = max(4 * L_approx, pu_min)
        
        # 估算临界增益 Ku
        if L_approx > 0.1:
            Ku_approx = 1.2 * T1_approx / (K_approx * L_approx)
        else:
            Ku_approx = 2.0 / K_approx
        Ku_approx = np.clip(Ku_approx, 0.1, 20.0)
        
        self.log(f"   📊 {self._loop_type}fallback估算: K≈{K_approx:.2f}, T1≈{T1_approx:.0f}s, "
                f"L≈{L_approx:.1f}s, Pu≈{Pu_approx:.0f}s, Ku≈{Ku_approx:.2f}")
        
        # 获取数据质量信息
        oscillation_ratio = best_result.oscillation_ratio if best_result else 0.5
        data_quality = best_result.quality_score if best_result else 0.4
        nonlinearity = best_result.nonlinearity_score if best_result else 0.3
        
        # 基于K调整pb
        if K_approx > 2.0:
            k_factor = 0.2 if self._loop_type == 'level' else 0.25
            pb_base *= 1.0 + (K_approx - 2.0) * k_factor
        elif K_approx < 0.5 and self._loop_type != 'level':
            pb_base *= 1.5  # 小增益需要更保守
        
        # 基于T1调整pb
        t1_threshold = 80.0 if self._loop_type == 'level' else 60.0
        if T1_approx > t1_threshold:
            t1_factor = 200.0 if self._loop_type == 'level' else 150.0
            pb_base *= 1.0 + (T1_approx - t1_threshold) / t1_factor
        
        # 限制pb范围
        pb_min = osc_config.get('pb_min', 120.0)
        pb_max = osc_config.get('pb_max', 500.0)
        pb_safe = np.clip(pb_base, pb_min, pb_max)
        
        conservative_Kp = 100.0 / pb_safe
        
        # Ti计算：使用策略参数
        ti_base_min = 10.0 if self._loop_type == 'level' else 5.0
        base_Ti = max(Pu_approx / 2, ti_base_min)
        conservative_Ti = base_Ti * ti_multiplier
        
        # 基于T1进一步调整Ti（液位特有）
        if self._loop_type == 'level' and T1_approx > 100:
            conservative_Ti *= 1.0 + (T1_approx - 100) / 200
        
        # Ti范围限制
        ti_range = osc_config.get('ti_range', [1.5, 25.0])
        conservative_Ti = np.clip(conservative_Ti, ti_range[0], ti_range[1])
        
        conservative_Ki = conservative_Kp / conservative_Ti
        
        # Td计算：根据振荡程度决定是否使用微分
        kd_threshold = 0.6 if self._loop_type == 'level' else 0.5
        if oscillation_ratio > kd_threshold:
            conservative_Td = Pu_approx / 10
            td_range = osc_config.get('td_range', [0.3, 3.0])
            conservative_Td = np.clip(conservative_Td, td_range[0], td_range[1])
            conservative_Kd = conservative_Kp * conservative_Td
        else:
            conservative_Td = 0.0
            conservative_Kd = 0.0
        
        self.log(f"   ✅ {self._loop_type}fallback整定:")
        self.log(f"      PB={pb_safe:.1f}%, Ti={conservative_Ti:.1f}s, Td={conservative_Td:.1f}s")
        self.log(f"      Kp={conservative_Kp:.4f}, Ki={conservative_Ki:.4f}, Kd={conservative_Kd:.4f}")
        
        pid_params = {
            'Kp': round(conservative_Kp, 4),
            'Ki': round(conservative_Ki, 4),
            'Kd': round(conservative_Kd, 4),
            'Ti': round(conservative_Ti, 2),
            'Td': round(conservative_Td, 2),
            'method': f'{self._loop_type}_fallback',
            'Pu': round(Pu_approx, 2),
            'Ku': round(Ku_approx, 2),
            'pb': round(pb_safe, 2)
        }
        
        # 构造模拟的振荡信息
        osc_info = {
            'Pu': Pu_approx,
            'Ku': Ku_approx,
            'amplitude': pv_range / 2,
            'mv_amplitude': mv_range / 2,
            'decay_ratio': 1.0,
            'oscillation_type': 'estimated',
            'n_cycles': 1,
            'is_valid': True,
            'confidence': 0.3,
            'oscillation_ratio': oscillation_ratio
        }
        
        return {
            'success': True,
            'pid_params': pid_params,
            'oscillation_info': osc_info,
            'segment_idx': 0,
            'method': f'{self._loop_type}_fallback',
            'data_quality': data_quality,
            'nonlinearity': nonlinearity,
            'valve_issues': {}
        }
    
    # 保留旧方法名作为别名以保持兼容性
    def _level_loop_fallback(self, oscillating_segments: List, 
                              segments: List[HistoricalData],
                              segment_results: List[SegmentResult]) -> Optional[Dict]:
        """液位回路fallback（调用统一方法）"""
        return self._fallback_tuning(oscillating_segments, segments, segment_results)
    
    def _generic_fallback(self, oscillating_segments: List, 
                          segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> Optional[Dict]:
        """通用fallback（调用统一方法）"""
        return self._fallback_tuning(oscillating_segments, segments, segment_results)

