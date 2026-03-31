"""
Rating 驱动自优化阶段 (Rating-Guided Self-Optimization Stage)
=============================================================

对 **所有整定路径** 的 PID 参数执行自优化（包括振荡整定/fallback）。

Phase 1 — Lambda 粗搜 (仅正常路径):
    生成多组 lambda_factor 候选 → 每个候选算 PID → 闭环仿真 → 三层评分 → 选最优 λ

Phase 2 — PB/TI/TD 微调 (所有路径):
    以当前最优 PID 为基线，按坐标轴逐一扰动 PB/TI/TD →
    每次扰动后闭环仿真 → 三层评分 → 贪心选取最优组合

设计说明:
    - Phase 2 不会将 PI 控制器升级为 PID (Kd=0 时不尝试加入 D 项)。
      这是有意设计: 控制器类型的选择应在更上层（整定方法选择阶段）完成，
      微调阶段仅对已确定类型的参数做小范围优化。

定位: 所有前置阶段之后、OutputVerificationStage 之前
"""

from typing import Dict, List, Tuple, Optional
import numpy as np

from ..context import TuningContext
from .base_stage import PipelineStage
from ...rating import ModelRating
from ...config import Config
from ...data_models import FusionResult
from ...config.loop_presets import get_loop_preset
from ...utils import normalize_pid_keys as _normalize_pid_keys, pid_to_full_dict

# 默认配置（可被 Config.SELF_OPTIMIZE 覆盖）
_DEFAULT_CONFIG = {
    'enabled': True,
    'lambda_multipliers': [0.6, 0.8, 1.0, 1.2, 1.5, 2.0],
    'min_score_improvement': 0.3,
    'fine_tune_enabled': True,
    'fine_tune_ratios': [0.5, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0],
    'fine_tune_max_rounds': 3,  # 增加一轮微调机会
    'fine_tune_min_improvement': 0.1,
}


def _normalize_pid_keys_fn(pid_params: Dict) -> Dict[str, float]:
    """兼容性包装 — 委托给 utils.normalize_pid_keys"""
    return _normalize_pid_keys(pid_params)


class SelfOptimizeStage(PipelineStage):
    """
    Rating 驱动自优化阶段 — 对所有整定路径的结果做评分驱动优化。

    正常路径 (fusion_result 存在, final_result 未设):
        Phase 1 → Phase 2

    振荡/fallback 路径 (final_result 已设, fusion_result 可能不存在):
        从 final_result 提取 PID + 模型参数 → 仅 Phase 2
    """

    def __init__(self, pid_calculator, verbose: bool = False, logger_mixin=None):
        super().__init__(logger_mixin)
        self._pid_calculator = pid_calculator
        self._verbose = verbose
        self._config = getattr(Config, 'SELF_OPTIMIZE', _DEFAULT_CONFIG)

    # ------------------------------------------------------------------
    # 评估: 给定 lambda 计算 PID 并评分
    # ------------------------------------------------------------------
    def _evaluate_candidate(self, fusion, lambda_factor, sp_initial, sp_final, pv_initial, loop_type):
        pid_params = self._pid_calculator.calculate_from_fusion(
            fusion, lambda_factor, loop_type=loop_type
        )
        # Fix #1: 确保 key 统一为大写
        pid_params = _normalize_pid_keys(pid_params)
        return self._evaluate_pid(fusion, pid_params, sp_initial, sp_final, pv_initial, loop_type,
                                  extra={'lambda_factor': lambda_factor, 'dt_data': getattr(self._context, 'dt_data', 1.0)})

    # ------------------------------------------------------------------
    # 评估: 直接评估一组 PID 参数
    # ------------------------------------------------------------------
    def _evaluate_pid(self, fusion, pid_params, sp_initial, sp_final, pv_initial, loop_type, extra=None):
        # Fix #1: 规范化输入 key
        pid_params = _normalize_pid_keys(pid_params)
        
        # [NEW] 将真实数据采样周期传给内部闭环仿真器
        if hasattr(self, '_context') and hasattr(self._context, 'dt_data'):
            pid_params['Ts'] = self._context.dt_data
        elif extra and 'dt_data' in extra:
            pid_params['Ts'] = extra['dt_data']

        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            fusion, pid_params,
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            loop_type=loop_type, verbose=False
        )

        perf_score, _ = ModelRating.performance_score(cl_metrics)
        method_conf, _ = ModelRating.model_id_confidence(fusion)
        final_score, _ = ModelRating.final_rating(perf_score, method_conf)

        eps = 1e-10
        Kp = pid_params['Kp']
        Ki = pid_params['Ki']
        Kd = pid_params['Kd']
        pb = 100.0 / abs(Kp) if abs(Kp) > eps else 999.0
        ti = abs(Kp / Ki) if abs(Ki) > eps else 0.0
        td = abs(Kd / Kp) if abs(Kp) > eps else 0.0

        detail = {
            'pid_params': pid_params, 'pb': pb, 'ti': ti, 'td': td,
            'is_stable': is_stable, 'performance_score': perf_score,
            'method_confidence': method_conf, 'final_score': final_score,
            'overshoot': cl_metrics.overshoot,
            'settling_time': cl_metrics.settling_time,
            'steady_state_error': cl_metrics.steady_state_error,
            'cl_metrics': cl_metrics,  # Fix #3: 保存 cl_metrics 供后续更新 closed_loop_verification
        }
        if extra:
            detail.update(extra)
        return final_score, detail

    # ------------------------------------------------------------------
    # Phase 2: PB/TI/TD 坐标轮换微调
    # ------------------------------------------------------------------
    def _fine_tune_pid(self, fusion, baseline_pid, baseline_score,
                       sp_initial, sp_final, pv_initial, loop_type):
        ratios = self._config.get('fine_tune_ratios', _DEFAULT_CONFIG['fine_tune_ratios'])
        max_rounds = self._config.get('fine_tune_max_rounds', _DEFAULT_CONFIG['fine_tune_max_rounds'])
        min_improv = self._config.get('fine_tune_min_improvement', _DEFAULT_CONFIG['fine_tune_min_improvement'])
        eps = 1e-10

        best_pid = _normalize_pid_keys(baseline_pid)
        best_score = baseline_score
        best_detail = None
        search_log: List[Dict] = []
        Kp_sign = 1 if best_pid['Kp'] >= 0 else -1

        for round_idx in range(max_rounds):
            improved = False

            # --- PB (调 |Kp|, 联动 Ki/Kd 保持 TI/TD) ---
            base_kp = abs(best_pid['Kp'])
            for ratio in ratios:
                if abs(ratio - 1.0) < 1e-6:
                    continue
                new_kp = base_kp / ratio
                if new_kp < 0.01:
                    continue
                c = dict(best_pid)
                c['Kp'] = Kp_sign * new_kp
                if abs(best_pid['Kp']) > eps:
                    c['Ki'] = c['Kp'] * (best_pid['Ki'] / best_pid['Kp'])
                    c['Kd'] = c['Kp'] * (best_pid['Kd'] / best_pid['Kp']) if abs(best_pid['Kd']) > eps else 0.0
                try:
                    score, detail = self._evaluate_pid(
                        fusion, c, sp_initial, sp_final, pv_initial, loop_type,
                        extra={'param': 'PB', 'ratio': ratio, 'round': round_idx + 1})
                    search_log.append(detail)
                    if score > best_score + min_improv:
                        best_score, best_pid, best_detail, improved = score, c, detail, True
                except Exception:
                    pass

            # --- TI (调 Ki，保持 Kp) ---
            if abs(best_pid['Ki']) > eps:
                base_ti = abs(best_pid['Kp'] / best_pid['Ki'])
                preset = get_loop_preset(loop_type) if loop_type else {}
                ti_max_limit = preset.get('ti_max', 300.0)
                
                for ratio in ratios:
                    if abs(ratio - 1.0) < 1e-6:
                        continue
                    new_ti = base_ti * ratio
                    if new_ti < 0.1:
                        continue
                        
                    # 应用上位机/DCS的最大限制
                    new_ti = min(new_ti, ti_max_limit)
                    
                    c = dict(best_pid)
                    c['Ki'] = c['Kp'] / new_ti
                    try:
                        score, detail = self._evaluate_pid(
                            fusion, c, sp_initial, sp_final, pv_initial, loop_type,
                            extra={'param': 'TI', 'ratio': ratio, 'round': round_idx + 1})
                        search_log.append(detail)
                        if score > best_score + min_improv:
                            best_score, best_pid, best_detail, improved = score, c, detail, True
                    except Exception:
                        pass

            # --- TD (调 Kd，保持 Kp) ---
            # 设计说明 (Fix #5): 仅当原始参数已包含 D 项 (Kd≠0) 时才微调 TD。
            # PI 控制器不会在微调阶段被升级为 PID，这是有意设计。
            if abs(best_pid.get('Kd', 0.0)) > eps:
                base_td = abs(best_pid['Kd'] / best_pid['Kp']) if abs(best_pid['Kp']) > eps else 0
                if base_td > eps:
                    for ratio in ratios:
                        if abs(ratio - 1.0) < 1e-6:
                            continue
                        c = dict(best_pid)
                        c['Kd'] = c['Kp'] * base_td * ratio
                        try:
                            score, detail = self._evaluate_pid(
                                fusion, c, sp_initial, sp_final, pv_initial, loop_type,
                                extra={'param': 'TD', 'ratio': ratio, 'round': round_idx + 1})
                            search_log.append(detail)
                            if score > best_score + min_improv:
                                best_score, best_pid, best_detail, improved = score, c, detail, True
                        except Exception:
                            pass

            if not improved:
                break

        return best_pid, best_score, best_detail, search_log

    # ------------------------------------------------------------------
    # 辅助: 从 final_result 提取信息用于 Phase 2
    # ------------------------------------------------------------------
    def _extract_from_final_result(self, final_result: Dict, context: TuningContext):
        """
        从已有的 final_result (振荡/fallback 路径) 提取:
        - fusion: FusionResult (用于仿真)
        - pid_params: dict (用于微调基线)
        - sim_params: (sp_initial, sp_final, pv_initial)
        - loop_type: str
        """
        # Fix #2: 对 model_parameters 做防御性类型转换
        mp = final_result.get('model_parameters', {})
        try:
            K = float(mp.get('K', 1.0))
            T1 = float(mp.get('T1', 10.0))
            T2 = float(mp.get('T2', 0.0))
            L = float(mp.get('L', 0.0))
        except (ValueError, TypeError) as e:
            self.log(f"   ⚠️ model_parameters 类型异常: {e}，使用默认值")
            K, T1, T2, L = 1.0, 10.0, 0.0, 0.0

        model_type = final_result.get('model_type', 'FOPDT')

        fusion = FusionResult(
            model_type=model_type, K=K, T1=T1, T2=T2, L=L,
            global_r2=final_result.get('fitting_result', {}).get('r_squared', 0.5),
            global_rmse=final_result.get('fitting_result', {}).get('rmse', 1.0),
        )

        # Fix #1 + #2: 规范化 PID 参数 key + 防御性类型转换
        pp = final_result.get('pid_parameters', {})
        pid_params = _normalize_pid_keys(pp)

        # 仿真参数
        cl_info = final_result.get('closed_loop_verification', {})
        sp_initial = cl_info.get('sp_initial', 50.0)
        sp_final = cl_info.get('sp_final', 60.0)
        pv_initial = cl_info.get('pv_initial', sp_initial)

        # 回路类型
        tf = final_result.get('tuning_features', {})
        loop_type = tf.get('loop_type', '') or context.loop_type or 'flow'

        return fusion, pid_params, sp_initial, sp_final, pv_initial, loop_type

    # ------------------------------------------------------------------
    # 辅助: 准备仿真参数 (正常路径)
    # ------------------------------------------------------------------
    def _prepare_sim_params(self, context: TuningContext):
        hist_data = context.hist_data
        if hist_data is None:
            return None

        valid_mask = hist_data.valid_mask()
        y = hist_data.pv[valid_mask]
        sv = hist_data.sv[valid_mask]
        ms_cfg = Config.MODEL_SELECTOR

        if len(y) == 0 or len(sv) == 0:
            return None

        sp_initial = float(sv[0])
        sp_final = float(sv[-1])
        pv_initial = float(y[0])

        sp_change = abs(sp_final - sp_initial)
        pv_sp_diff = abs(pv_initial - sp_initial)
        if sp_change < ms_cfg['min_sp_change'] or pv_sp_diff > sp_change * 2:
            sp_initial = ms_cfg['default_sp_initial']
            sp_final = ms_cfg['default_sp_final']
            pv_initial = ms_cfg['default_pv_initial']

        return sp_initial, sp_final, pv_initial

    # ------------------------------------------------------------------
    # 辅助: 构建 closed_loop_verification dict (Fix #3)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_cl_verification(cl_metrics, sp_initial, sp_final, pv_initial, is_stable=None) -> Dict:
        """从 cl_metrics 构建 closed_loop_verification 字典, 确保与微调后参数匹配。
        
        Args:
            is_stable: 由 verify_pid_stability 返回的稳定性判定（综合判定）。
                       如为 None，则降级为简单的 settling_time 判定（不推荐）。
        """
        if is_stable is None:
            is_stable = cl_metrics.settling_time < float('inf')
        return {
            'is_stable': is_stable,
            'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot,
            'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error,
            'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio,
            'sp_initial': sp_initial,
            'sp_final': sp_final,
            'pv_initial': pv_initial,
        }

    # ------------------------------------------------------------------
    # 辅助: Phase 2 搜索日志 (Fix #4)
    # ------------------------------------------------------------------
    def _log_phase2_summary(self, search_log: List[Dict], baseline_score: float):
        """输出 Phase 2 搜索过程的关键候选对比表。"""
        if not search_log:
            return

        # 筛选出改善的候选 + 最差的候选，避免过长日志
        improved = [d for d in search_log if d['final_score'] > baseline_score]
        worst = min(search_log, key=lambda d: d['final_score'])

        self.log(f"\n   📊 Phase 2 搜索摘要 ({len(search_log)} 个候选):")
        self.log(f"   {'参数':>4s} | {'倍率':>4s} | {'评分':>6s} | {'性能分':>6s} | {'超调%':>6s} | {'调节时间':>8s} | {'稳态误差%':>8s} | {'稳定':>4s}")
        self.log(f"   {'-'*4}-+-{'-'*4}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*4}")

        shown = set()
        for d in sorted(improved + [worst], key=lambda x: x['final_score'], reverse=True):
            key = (d.get('param', '?'), d.get('ratio', 0))
            if key in shown:
                continue
            shown.add(key)
            st = d['settling_time']
            st_s = f"{st:.1f}s" if st < float('inf') else "∞"
            marker = " ✓" if d['final_score'] > baseline_score else ""
            self.log(
                f"   {d.get('param', '?'):>4s} | {d.get('ratio', 0):4.1f} | {d['final_score']:6.2f} | "
                f"{d['performance_score']:6.2f} | {d['overshoot']:6.1f} | {st_s:>8s} | "
                f"{d['steady_state_error']:8.2f} | {'✅' if d['is_stable'] else '❌'}{marker}"
            )

    # ------------------------------------------------------------------
    # Stage 入口
    # ------------------------------------------------------------------
    def execute(self, context: TuningContext) -> TuningContext:
        if not self._config.get('enabled', True):
            return context
            
        self._context = context

        self.log(f"\n{'='*60}")
        self.log("🔄 Step 5b: Rating 驱动自优化")
        self.log('='*60)

        # ====================================================================
        # 路径判定: final_result 已存在? → 振荡/fallback 路径
        # ====================================================================
        if context.final_result is not None:
            return self._optimize_existing_result(context)

        # ====================================================================
        # 正常路径: fusion_result 存在，走 Phase 1 + Phase 2
        # ====================================================================
        # [NEW] 提取真实历史数据的采样周期 dt_data
        hist_data = context.hist_data
        dt_data = 1.0
        if hist_data and hasattr(hist_data, 'timestamp') and len(hist_data.timestamp) > 1:
            ts = np.array(hist_data.timestamp, dtype=np.int64)
            ts_diff = np.diff(ts[ts > 0]) / 1000.0
            if len(ts_diff) > 0:
                dt_data = float(np.median(ts_diff))
        # 将真实采样周期放入 context 中，方便 _evaluate_pid 使用
        if not hasattr(context, 'dt_data'):
            context.dt_data = dt_data

        self.log(f"\n{'='*60}")
        self.log("🔄 Step 5b: Rating 驱动自优化")
        self.log('='*60)

        # ====================================================================
        # 路径判定: final_result 已存在? → 振荡/fallback 路径
        # ====================================================================
        if context.final_result is not None:
            return self._optimize_existing_result(context)

        # ====================================================================
        # 正常路径: fusion_result 存在，走 Phase 1 + Phase 2
        # ====================================================================
        fusion = context.fusion_result
        if fusion is None:
            self.log("   ⚠️ 无 fusion_result，跳过自优化")
            return context

        sim = self._prepare_sim_params(context)
        if sim is None:
            self.log("   ⚠️ 无有效仿真数据，跳过自优化")
            return context
        sp_initial, sp_final, pv_initial = sim
        loop_type = context.loop_type or 'flow'

        # ── Phase 1: Lambda 粗搜 ──
        self.log(f"\n   ── Phase 1: Lambda 粗搜 ──")
        base_lambda = context.lambda_factor
        multipliers = self._config.get('lambda_multipliers', _DEFAULT_CONFIG['lambda_multipliers'])
        min_improvement = self._config.get('min_score_improvement', _DEFAULT_CONFIG['min_score_improvement'])

        candidates: List[Tuple[float, Dict]] = []
        for mult in multipliers:
            lf = round(base_lambda * mult, 4)
            try:
                score, detail = self._evaluate_candidate(fusion, lf, sp_initial, sp_final, pv_initial, loop_type)
                candidates.append((score, detail))
            except Exception as e:
                self.log(f"   ⚠️ λ={lf:.2f} 评估失败: {e}")

        if not candidates:
            self.log("   ⚠️ 所有候选评估失败，保持原始 lambda")
            return context

        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_detail = candidates[0]

        original_score = best_score
        for score, detail in candidates:
            if abs(detail.get('lambda_factor', -1) - base_lambda) < 1e-6:
                original_score = score
                break

        self._log_lambda_table(candidates, best_detail, base_lambda)

        improvement_p1 = best_score - original_score
        best_lf = best_detail.get('lambda_factor', base_lambda)
        if abs(best_lf - base_lambda) < 1e-6:
            self.log(f"\n   Phase 1 结果: 原始 λ={base_lambda:.3f} 已是最优 (评分={original_score:.2f})")
        elif improvement_p1 >= min_improvement:
            self.log(f"\n   Phase 1 结果: λ={best_lf:.3f} (评分 {original_score:.2f} → {best_score:.2f}, 提升 +{improvement_p1:.2f})")
            context.lambda_factor = best_lf
        else:
            self.log(f"\n   Phase 1 结果: λ 提升不足 (+{improvement_p1:.2f})，保持 λ={base_lambda:.3f}")

        # ── Phase 2: PB/TI/TD 微调 ──
        if self._config.get('fine_tune_enabled', True):
            self._run_phase2(fusion, best_detail['pid_params'], best_score,
                            sp_initial, sp_final, pv_initial, loop_type,
                            context, original_score)

        return context

    # ------------------------------------------------------------------
    # 振荡/fallback 路径: 仅 Phase 2 网格搜索
    # ------------------------------------------------------------------
    def _optimize_existing_result(self, context: TuningContext) -> TuningContext:
        if not self._config.get('fine_tune_enabled', True):
            self.log("   ℹ️ Phase 2 禁用，跳过")
            return context

        final_result = context.final_result
        self.log(f"   ℹ️ 已有整定结果 (来自 {final_result.get('tuning_features', {}).get('tuning_method', 'fallback')})，执行 Phase 2 微调")

        fusion, pid_params, sp_initial, sp_final, pv_initial, loop_type = \
            self._extract_from_final_result(final_result, context)

        # 评估基线
        try:
            baseline_score, baseline_detail = self._evaluate_pid(
                fusion, pid_params, sp_initial, sp_final, pv_initial, loop_type)
        except Exception as e:
            self.log(f"   ⚠️ 基线评估失败: {e}，跳过微调")
            return context

        self.log(f"\n   ── Phase 2: PB/TI/TD 微调 (fallback 路径) ──")

        eps = 1e-10
        base_pb = 100.0 / abs(pid_params['Kp']) if abs(pid_params['Kp']) > eps else 999.0
        base_ti = abs(pid_params['Kp'] / pid_params['Ki']) if abs(pid_params['Ki']) > eps else 0.0
        base_td = abs(pid_params.get('Kd', 0) / pid_params['Kp']) if abs(pid_params['Kp']) > eps else 0.0

        self.log(f"   基线: PB={base_pb:.2f}% TI={base_ti:.2f}s TD={base_td:.2f}s (评分={baseline_score:.2f})")

        tuned_pid, tuned_score, tuned_detail, search_log = self._fine_tune_pid(
            fusion, pid_params, baseline_score,
            sp_initial, sp_final, pv_initial, loop_type)

        # Fix #4: 输出 Phase 2 搜索详情
        self._log_phase2_summary(search_log, baseline_score)

        improvement = tuned_score - baseline_score
        min_improv = self._config.get('fine_tune_min_improvement', _DEFAULT_CONFIG['fine_tune_min_improvement'])

        if improvement >= min_improv:
            tuned_Kp = tuned_pid['Kp']
            tuned_Ki = tuned_pid['Ki']
            tuned_Kd = tuned_pid.get('Kd', 0.0)
            tuned_pb = 100.0 / abs(tuned_Kp) if abs(tuned_Kp) > eps else 999.0
            tuned_ti = abs(tuned_Kp / tuned_Ki) if abs(tuned_Ki) > eps else 0.0
            tuned_td = abs(tuned_Kd / tuned_Kp) if abs(tuned_Kp) > eps else 0.0

            self.log(
                f"\n   🎯 微调优化: PB={base_pb:.2f}→{tuned_pb:.2f}% "
                f"TI={base_ti:.2f}→{tuned_ti:.2f}s TD={base_td:.2f}→{tuned_td:.2f}s"
            )
            self.log(f"   评分 {baseline_score:.2f} → {tuned_score:.2f} (提升 +{improvement:.2f})")

            # 使用统一工具函数生成完整 PID 参数字典
            context.final_result['pid_parameters'] = pid_to_full_dict(
                tuned_Kp, tuned_Ki, tuned_Kd
            )
            context.final_result['model_rating'] = round(tuned_score, 2)

            # Fix #3: 同步更新 closed_loop_verification, 使其与微调后的参数匹配
            if tuned_detail and 'cl_metrics' in tuned_detail:
                context.final_result['closed_loop_verification'] = self._build_cl_verification(
                    tuned_detail['cl_metrics'], sp_initial, sp_final, pv_initial,
                    is_stable=tuned_detail.get('is_stable')
                )
        else:
            self.log(f"\n   ✅ Phase 2: 微调提升不足 (+{improvement:.2f})，保持原始参数")

        self.log(f"\n   📊 自优化总结: 评分 {baseline_score:.2f} → {max(tuned_score, baseline_score):.2f}")
        return context

    # ------------------------------------------------------------------
    # Phase 2 通用执行 (正常路径调用)
    # ------------------------------------------------------------------
    def _run_phase2(self, fusion, baseline_pid, baseline_score,
                    sp_initial, sp_final, pv_initial, loop_type,
                    context, original_score):
        self.log(f"\n   ── Phase 2: PB/TI/TD 微调 ──")

        eps = 1e-10
        baseline_pid = _normalize_pid_keys(baseline_pid)
        Kp = baseline_pid['Kp']
        Ki = baseline_pid['Ki']
        Kd = baseline_pid['Kd']
        base_pb = 100.0 / abs(Kp) if abs(Kp) > eps else 999.0
        base_ti = abs(Kp / Ki) if abs(Ki) > eps else 0.0
        base_td = abs(Kd / Kp) if abs(Kp) > eps else 0.0

        self.log(f"   基线: PB={base_pb:.2f}% TI={base_ti:.2f}s TD={base_td:.2f}s (评分={baseline_score:.2f})")

        tuned_pid, tuned_score, tuned_detail, search_log = self._fine_tune_pid(
            fusion, baseline_pid, baseline_score,
            sp_initial, sp_final, pv_initial, loop_type)

        # Fix #4: 输出 Phase 2 搜索详情
        self._log_phase2_summary(search_log, baseline_score)

        improvement = tuned_score - baseline_score
        min_improv = self._config.get('fine_tune_min_improvement', _DEFAULT_CONFIG['fine_tune_min_improvement'])

        if improvement >= min_improv:
            t_Kp = tuned_pid['Kp']
            t_Ki = tuned_pid['Ki']
            t_Kd = tuned_pid.get('Kd', 0.0)
            t_pb = 100.0 / abs(t_Kp) if abs(t_Kp) > eps else 999.0
            t_ti = abs(t_Kp / t_Ki) if abs(t_Ki) > eps else 0.0
            t_td = abs(t_Kd / t_Kp) if abs(t_Kp) > eps else 0.0

            self.log(f"\n   🎯 微调优化: PB={base_pb:.2f}→{t_pb:.2f}% TI={base_ti:.2f}→{t_ti:.2f}s TD={base_td:.2f}→{t_td:.2f}s")
            self.log(f"   评分 {baseline_score:.2f} → {tuned_score:.2f} (提升 +{improvement:.2f})")
            context.optimized_pid = tuned_pid
        else:
            self.log(f"\n   ✅ Phase 2: 微调提升不足 (+{improvement:.2f})，保持 Phase 1 结果")

        self.log(f"\n   📊 自优化总结: 评分 {original_score:.2f} → {max(tuned_score, baseline_score):.2f}")

    # ------------------------------------------------------------------
    # 辅助: 日志表格
    # ------------------------------------------------------------------
    def _log_lambda_table(self, candidates, best_detail, original_lf):
        self.log(f"\n   {'λ':>8s} | {'评分':>6s} | {'性能分':>6s} | {'超调%':>6s} | {'调节时间':>8s} | {'稳态误差%':>8s} | {'稳定':>4s}")
        self.log(f"   {'-'*8}-+-{'-'*6}-+-{'-'*6}-+-{'-'*6}-+-{'-'*8}-+-{'-'*8}-+-{'-'*4}")
        for score, detail in candidates:
            lf = detail.get('lambda_factor', 0)
            m1 = " ◀ 最优" if abs(lf - best_detail.get('lambda_factor', 0)) < 1e-6 else ""
            m2 = " (原始)" if abs(lf - original_lf) < 1e-6 else ""
            st = detail['settling_time']
            st_s = f"{st:.1f}s" if st < float('inf') else "∞"
            self.log(
                f"   {lf:8.3f} | {score:6.2f} | {detail['performance_score']:6.2f} | "
                f"{detail['overshoot']:6.1f} | {st_s:>8s} | {detail['steady_state_error']:8.2f} | "
                f"{'✅' if detail['is_stable'] else '❌'}{m1}{m2}"
            )
