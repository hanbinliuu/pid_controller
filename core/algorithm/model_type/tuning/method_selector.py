"""
整定方法选择器 (Tuning Method Selector)
======================================

自动分析数据特征，选择最优整定方法：
1. 模型辨识法 (Model-based): 阶跃响应数据 → FOPDT/SOPDT → Lambda/SIMC整定
2. 继电反馈法 (Relay Feedback): 振荡数据 → Ku/Pu → ZN/TL整定
3. 混合方法 (Hybrid): 结合两种方法的优势

选择逻辑
--------
- 数据有明显阶跃响应特征 → 模型辨识法
- 数据有持续振荡特征 → 继电反馈法
- 两种特征都有 → 混合方法（交叉验证）
- 特征不明显 → 保守fallback

稳定性验证
----------
所有整定结果都通过 StabilityAnalyzer 验证增益裕度和相位裕度
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

from ..config import Config
from ..data_models import HistoricalData, SegmentResult
from ..logger import LoggerMixin
from ..fitting.relay_identifier import RelayIdentifier
from .verification.stability_analyzer import StabilityAnalyzer, StabilityMargins


class TuningMethod(Enum):
    """整定方法枚举"""
    MODEL_BASED = "model_based"        # 模型辨识法 (Lambda/SIMC)
    RELAY_FEEDBACK = "relay_feedback"  # 继电反馈法 (ZN/TL)
    HYBRID = "hybrid"                  # 混合方法
    CONSERVATIVE = "conservative"      # 保守fallback


@dataclass
class DataCharacteristics:
    """数据特征分析结果"""
    has_step_response: bool = False
    has_oscillation: bool = False
    step_quality: float = 0.0
    oscillation_quality: float = 0.0
    oscillation_regularity: float = 0.0
    n_cycles: int = 0
    data_points: int = 0
    noise_level: float = 0.0
    recommended_method: TuningMethod = TuningMethod.CONSERVATIVE


@dataclass
class TuningMethodResult:
    """整定方法选择结果"""
    method: TuningMethod
    confidence: float
    pid_params: Dict[str, float]
    model_params: Optional[Dict] = None
    critical_params: Optional[Dict] = None
    stability_margins: Optional[StabilityMargins] = None
    reasoning: str = ""
    warnings: List[str] = field(default_factory=list)


class TuningMethodSelector(LoggerMixin):
    """整定方法选择器 - 自动分析数据特征，选择最优整定方法"""
    
    STEP_QUALITY_THRESHOLD = 0.5
    OSC_REGULARITY_THRESHOLD = 0.4
    MIN_CYCLES_FOR_RELAY = 2
    MIN_GAIN_MARGIN = 2.0
    MIN_PHASE_MARGIN = 45.0
    
    def __init__(self, pid_calculator, simulator, verbose: bool = False):
        self._init_logger(verbose)
        self._pid_calculator = pid_calculator
        self._simulator = simulator
        self._epsilon = Config.EPSILON
    
    def analyze_data_characteristics(self, pv: np.ndarray, mv: np.ndarray, 
                                      dt: float = 1.0) -> DataCharacteristics:
        """分析数据特征，判断适合哪种整定方法"""
        chars = DataCharacteristics(data_points=len(pv))
        if len(pv) < 20:
            return chars
        
        chars.step_quality = self._analyze_step_response(pv, mv)
        chars.has_step_response = chars.step_quality > self.STEP_QUALITY_THRESHOLD
        
        limit_cycle = RelayIdentifier.detect_limit_cycle(pv, dt)
        if limit_cycle is not None:
            chars.has_oscillation = True
            chars.oscillation_regularity = limit_cycle.regularity
            chars.n_cycles = limit_cycle.n_cycles
            chars.oscillation_quality = 0.7 * limit_cycle.regularity + 0.3 * min(1.0, limit_cycle.n_cycles / 4)
        
        chars.noise_level = self._estimate_noise_level(pv)
        chars.recommended_method = self._recommend_method(chars)
        return chars

    
    def _analyze_step_response(self, pv: np.ndarray, mv: np.ndarray) -> float:
        """分析阶跃响应质量"""
        if len(pv) < 10 or len(mv) < 10:
            return 0.0
        mv_diff = np.abs(np.diff(mv))
        mv_threshold = np.std(mv) * 2 if np.std(mv) > self._epsilon else 0.1
        step_indices = np.where(mv_diff > mv_threshold)[0]
        if len(step_indices) == 0:
            return 0.0
        
        quality_scores = []
        for step_idx in step_indices[:3]:
            if step_idx + 20 > len(pv):
                continue
            pv_after = pv[step_idx:min(len(pv), step_idx+50)]
            if len(pv_after) < 10:
                continue
            pv_change = np.abs(pv_after[-1] - pv_after[0])
            pv_range = np.ptp(pv_after)
            monotonicity = pv_change / pv_range if pv_range > self._epsilon else 0.0
            if len(pv_after) > 20:
                var_first = np.var(pv_after[:len(pv_after)//2])
                var_second = np.var(pv_after[len(pv_after)//2:])
                settling = 1.0 - min(var_second / var_first, 1.0) if var_first > self._epsilon else 0.5
            else:
                settling = 0.5
            quality_scores.append(0.6 * monotonicity + 0.4 * settling)
        return np.mean(quality_scores) if quality_scores else 0.0
    
    def _estimate_noise_level(self, pv: np.ndarray) -> float:
        """估计噪声水平"""
        if len(pv) < 10:
            return 0.0
        pv_diff = np.diff(pv)
        noise_std = np.std(pv_diff) / np.sqrt(2)
        signal_std = np.std(pv)
        return float(np.clip(noise_std / signal_std, 0, 1)) if signal_std > self._epsilon else 0.0
    
    def _recommend_method(self, chars: DataCharacteristics) -> TuningMethod:
        """根据数据特征推荐整定方法"""
        has_good_step = chars.has_step_response and chars.step_quality > 0.6
        has_good_osc = (chars.has_oscillation and 
                        chars.oscillation_regularity > self.OSC_REGULARITY_THRESHOLD and
                        chars.n_cycles >= self.MIN_CYCLES_FOR_RELAY)
        if has_good_step and has_good_osc:
            return TuningMethod.HYBRID
        elif has_good_step:
            return TuningMethod.MODEL_BASED
        elif has_good_osc:
            return TuningMethod.RELAY_FEEDBACK
        elif chars.has_step_response or chars.has_oscillation:
            return TuningMethod.HYBRID
        return TuningMethod.CONSERVATIVE

    
    def select_and_tune(self, segments: List[HistoricalData],
                        segment_results: List[SegmentResult],
                        model_params: Optional[Dict] = None,
                        lambda_factor: float = 0.8,
                        loop_type: str = '') -> TuningMethodResult:
        """
        选择整定方法并执行整定
        
        核心逻辑：基于稳定性裕度(GM>2, PM>45°)选择最优方法
        1. 尝试所有可用方法
        2. 验证每种方法的稳定性裕度
        3. 选择稳定性最好的方法
        """
        if not segments:
            return self._conservative_fallback("无有效数据段", loop_type=loop_type)
        
        all_pv = np.concatenate([seg.pv for seg in segments])
        all_mv = np.concatenate([seg.mv for seg in segments])
        dt = (segments[0].timestamp[1] - segments[0].timestamp[0]) / 1000.0 if len(segments[0].timestamp) > 1 else 1.0
        
        chars = self.analyze_data_characteristics(all_pv, all_mv, dt)
        self.log(f"\n📊 数据特征: 阶跃质量={chars.step_quality:.2f}, 振荡规则性={chars.oscillation_regularity:.2f}")
        
        # 收集所有可用方法的结果
        candidates = []
        
        # 1. 尝试模型辨识法
        if model_params and model_params.get('K', 0) != 0:
            model_result = self._model_based_tuning(segments, model_params, lambda_factor, chars, loop_type=loop_type)
            if model_result.model_params:
                model_result = self._verify_stability(model_result)
                candidates.append(model_result)
        
        # 2. 尝试继电反馈法（如果有振荡特征）
        if chars.has_oscillation and chars.n_cycles >= 1:
            relay_result = self._relay_feedback_tuning(segments, chars, dt, loop_type=loop_type)
            if relay_result.method != TuningMethod.CONSERVATIVE and relay_result.model_params:
                relay_result = self._verify_stability(relay_result)
                candidates.append(relay_result)
        
        if not candidates:
            return self._conservative_fallback("无可用整定方法", loop_type=loop_type)
        
        # 3. 基于稳定性裕度选择最优方法
        best = self._select_best_by_stability(candidates)
        
        # 4. 如果最优方法不稳定，尝试调整
        if best.stability_margins and not best.stability_margins.is_stable:
            best = self._adjust_for_stability(best)
        
        self.log(f"\n🎯 最终选择: {best.method.value}")
        if best.stability_margins:
            self.log(f"   GM={best.stability_margins.gain_margin:.2f}, PM={best.stability_margins.phase_margin:.1f}°")
        
        return best
    
    def _select_best_by_stability(self, candidates: List[TuningMethodResult]) -> TuningMethodResult:
        """基于稳定性裕度选择最优方法（GM+PM 综合评分）"""
        if len(candidates) == 1:
            return candidates[0]
        
        # 过滤掉 Pu 异常的继电反馈候选（Pu 打满上限说明估计不可靠）
        valid_candidates = []
        for c in candidates:
            if c.method == TuningMethod.RELAY_FEEDBACK and c.critical_params:
                Pu = c.critical_params.get('Pu', 0)
                if Pu >= 500:  # Pu >= 500s 视为触达上限，不可靠
                    self.log(f"   ⚠️ 继电反馈法 Pu={Pu:.1f}s 疑似触达上限，排除")
                    continue
            valid_candidates.append(c)
        
        if not valid_candidates:
            valid_candidates = candidates  # 全部被排除时回退
        
        # 分离稳定和不稳定的候选
        stable_candidates = [c for c in valid_candidates if c.stability_margins and c.stability_margins.is_stable]
        
        def _stability_score(c):
            """GM+PM 综合评分：GM 归一化到 [0,10]，PM 归一化到 [0,10]"""
            m = c.stability_margins
            gm_norm = min(10.0, m.gain_margin * 2)      # GM=5 → 10分
            pm_norm = min(10.0, m.phase_margin / 9.0)    # PM=90 → 10分
            return 0.4 * gm_norm + 0.6 * pm_norm
        
        if stable_candidates:
            best = max(stable_candidates, key=_stability_score)
            score = _stability_score(best)
            best.reasoning = (f"GM+PM综合评分最优 "
                            f"(GM={best.stability_margins.gain_margin:.2f}, "
                            f"PM={best.stability_margins.phase_margin:.1f}°, "
                            f"综合={score:.1f})")
        else:
            best = max(valid_candidates, key=lambda c: c.stability_margins.phase_margin if c.stability_margins else 0)
            best.reasoning = "所有方法都不满足稳定性要求，选择相位裕度最大的"
        
        return best

    
    def _model_based_tuning(self, segments: List[HistoricalData], model_params: Optional[Dict],
                            lambda_factor: float, chars: DataCharacteristics,
                            loop_type: str = '') -> TuningMethodResult:
        """模型辨识法整定"""
        self.log("\n🔧 使用模型辨识法整定")
        if model_params is None or model_params.get('K', 0) == 0:
            return self._conservative_fallback("模型参数无效", loop_type=loop_type)
        
        K = model_params.get('K', 1.0)
        T1 = model_params.get('T1', 10.0)
        T2 = model_params.get('T2', 0.0)
        L = model_params.get('L', 1.0)
        
        # [FIX] Level 积分过程校正 — 根据模型类型分级放大 lambda
        # 对近积分过程，FOPDT 拟合会系统性地压缩 T1（600→30）和放大 K（0.01→0.5）
        # 但如果 fusion stage 已经选了自平衡模型（FO/SO），说明数据有自平衡特性
        actual_lambda = lambda_factor
        model_type = model_params.get('model_type', '')
        is_integrator_model = model_type in ('FO_INTEGRATOR', 'SO_INTEGRATOR')
        if loop_type == 'level' and is_integrator_model:
            actual_lambda = max(lambda_factor * 5.0, 4.0)  # 积分器：大幅放大，至少 4.0
            self.log(f"   🧊 Level 积分过程: lambda_factor {lambda_factor:.1f} → {actual_lambda:.1f}")
        elif loop_type == 'level':
            # 自平衡模型但 T1 很大（>200s）→ 近积分过程，需适度保守化
            if T1 > 200:
                actual_lambda = max(lambda_factor * 2.5, 2.0)  # 适度放大（不是 ×5）
                self.log(f"   🧊 Level 近积分自平衡过程({model_type}, T1={T1:.0f}s): lambda_factor {lambda_factor:.1f} → {actual_lambda:.1f}")
            else:
                self.log(f"   🧊 Level 自平衡过程({model_type}): 保持 lambda_factor={lambda_factor:.1f}")
        
        # 使用 PIDCalculator.calculate 方法
        # [FIX] 使用实际模型类型（不是硬编码 FOPDT），并传入 loop_type 以启用 pb_min 保护
        actual_model_type = model_type if model_type else 'FOPDT'
        pid_params = self._pid_calculator.calculate(
            K=K, T1=T1, T2=T2, L=L,
            model_type=actual_model_type, lambda_factor=actual_lambda, method='lambda',
            loop_type=loop_type
        )
        
        # [FIX] Level + FO_INTEGRATOR 的 Ti 下限保护
        # 纯积分器 T1=0 导致 PIDCalculator 的 lambda 公式算出极短的 Ti (18~20s)，
        # 这对液位回路来说完全不合理（行业标准 Ti ≥ 60s）。
        # 强制 Ti 不低于 60s，避免 model_based 路径输出危险的快速积分。
        if loop_type == 'level' and is_integrator_model:
            ti_val = pid_params.get('Ti', 0)
            TI_MIN_LEVEL = 60.0
            if ti_val < TI_MIN_LEVEL:
                self.log(f"   ⚠️ Level积分器 Ti={ti_val:.1f}s < {TI_MIN_LEVEL}s (行业下限)，强制提升")
                pid_params['Ti'] = TI_MIN_LEVEL
                kp_val = pid_params.get('Kp', 1.0)
                pid_params['Ki'] = round(kp_val / TI_MIN_LEVEL, 4)
        
        return TuningMethodResult(
            method=TuningMethod.MODEL_BASED, confidence=chars.step_quality,
            pid_params=pid_params, model_params=model_params,
            reasoning=f"阶跃响应质量={chars.step_quality:.2f}，使用Lambda整定"
        )
    
    def _relay_feedback_tuning(self, segments: List[HistoricalData],
                                chars: DataCharacteristics, dt: float, loop_type: str = '') -> TuningMethodResult:
        """继电反馈法整定"""
        self.log("\n🔧 使用继电反馈法整定")
        all_pv = np.concatenate([seg.pv for seg in segments])
        all_mv = np.concatenate([seg.mv for seg in segments])
        
        relay_result = RelayIdentifier.estimate_critical_params(all_pv, all_mv, dt)
        if relay_result is None:
            return self._conservative_fallback("无法从振荡数据提取临界参数", loop_type=loop_type)
        
        Ku, Pu = relay_result.Ku, relay_result.Pu
        self.log(f"   临界参数: Ku={Ku:.3f}, Pu={Pu:.1f}s")
        
        pid_raw = RelayIdentifier.conservative_from_critical(Ku, Pu, safety_factor=1.5)
        Kp, Ti, Td = pid_raw['Kp'], pid_raw['Ti'], pid_raw['Td']
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        
        formatted_params = {
            'Kp': round(Kp, 4), 'Ki': round(Ki, 4), 'Kd': round(Kp * Td, 4),
            'Ti': round(Ti, 2), 'Td': round(Td, 2),
            'pb': round(100.0 / abs(Kp), 2) if abs(Kp) > self._epsilon else 100.0,
            'method': 'relay_feedback_ZN'
        }
        model_from_relay = RelayIdentifier.identify_from_oscillation(all_pv, all_mv, dt)
        
        return TuningMethodResult(
            method=TuningMethod.RELAY_FEEDBACK, confidence=relay_result.confidence,
            pid_params=formatted_params, model_params=model_from_relay,
            critical_params={'Ku': Ku, 'Pu': Pu},
            reasoning=f"振荡规则性={chars.oscillation_regularity:.2f}，周期数={chars.n_cycles}"
        )



    
    def _verify_stability(self, result: TuningMethodResult) -> TuningMethodResult:
        """使用 StabilityAnalyzer 验证整定结果的稳定性"""
        if not result.model_params or not result.pid_params:
            return result
        
        margins = StabilityAnalyzer.check_stability(result.model_params, result.pid_params)
        result.stability_margins = margins
        self.log(f"   稳定性验证: GM={margins.gain_margin:.2f}, PM={margins.phase_margin:.1f}°, 稳定={margins.is_stable}")
        
        if not margins.is_stable:
            result.warnings.append(f"稳定性裕度不足: GM={margins.gain_margin:.2f}, PM={margins.phase_margin:.1f}°")
        return result
    
    def _adjust_for_stability(self, result: TuningMethodResult) -> TuningMethodResult:
        """调整 PID 参数以满足稳定性要求"""
        if not result.model_params or not result.pid_params:
            return result
        
        K = result.model_params.get('K', 1.0)
        T1 = result.model_params.get('T1', 10.0)
        L = result.model_params.get('L', 1.0)
        Kp = result.pid_params.get('Kp', 1.0)
        Ti = result.pid_params.get('Ti', 10.0)
        Td = result.pid_params.get('Td', 0.0)
        
        adjusted_Kp, margins = StabilityAnalyzer.adjust_kp_for_margins(
            K, T1, L, Kp, Ti, Td, target_gm=self.MIN_GAIN_MARGIN, target_pm=self.MIN_PHASE_MARGIN
        )
        
        if adjusted_Kp != Kp:
            self.log(f"   调整 Kp: {Kp:.4f} → {adjusted_Kp:.4f}")
            result.pid_params['Kp'] = round(adjusted_Kp, 4)
            result.pid_params['Ki'] = round(adjusted_Kp / Ti, 4) if Ti > self._epsilon else 0.0
            result.pid_params['Kd'] = round(adjusted_Kp * Td, 4)
            result.pid_params['pb'] = round(100.0 / abs(adjusted_Kp), 2) if abs(adjusted_Kp) > self._epsilon else 100.0
            result.warnings.append(f"Kp已调整: {Kp:.4f} → {adjusted_Kp:.4f}")
        
        result.stability_margins = margins
        return result
    
    def _conservative_fallback(self, reason: str, loop_type: str = 'flow') -> TuningMethodResult:
        """保守 fallback 整定"""
        self.log(f"   ⚠️ 使用保守fallback: {reason}")
        Kp, Ti, Td = self._pid_calculator._get_fallback_params(loop_type=loop_type)
        Ki = Kp / Ti if Ti > 0 else 0.0
        Kd = Kp * Td
        
        pb = 100.0 / Kp if Kp > 1e-6 else 200.0
        pid_params = {'Kp': Kp, 'Ki': Ki, 'Kd': Kd, 'Ti': Ti, 'Td': Td, 'pb': pb, 'method': 'conservative_fallback'}
        return TuningMethodResult(
            method=TuningMethod.CONSERVATIVE, confidence=0.3, pid_params=pid_params,
            reasoning=f"保守fallback: {reason}", warnings=[reason]
        )
