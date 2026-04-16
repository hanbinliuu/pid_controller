"""
PID 护栏服务 (PID Guard Service)
===============================

集中管理与 PID 护栏相关的共享逻辑，避免在多个模块重复实现：
1. PID 参数提取 (兼容 Kp/kp 与 pb 推导)
2. 相对 current_pid 变更惩罚
3. current_pid 存在时的单次调参护栏
4. current_pid 缺失时的风险自适应护栏
"""

from typing import Dict, Optional, Tuple, Callable, Any

import numpy as np


class PidGuardService:
    """共享 PID 护栏逻辑。"""

    @staticmethod
    def extract_pid_triplet(pid: Optional[Dict], eps: float) -> Tuple[float, float, float]:
        """从任意 PID 字典中提取 Kp/Ti/Td，兼容 kp/Kp、ti/Ti、pb/Pb。"""
        if not pid:
            return 0.0, 0.0, 0.0
        kp = pid.get('Kp', pid.get('kp', 0.0))
        ti = pid.get('Ti', pid.get('ti', 0.0))
        td = pid.get('Td', pid.get('td', 0.0))
        if abs(kp) < eps:
            pb = pid.get('pb', pid.get('Pb', 0.0))
            if pb and abs(pb) > eps:
                kp = 100.0 / float(pb)
        return float(kp), float(ti), float(td)

    @staticmethod
    def compute_move_penalty(current_pid: Optional[Dict], candidate_pid: Dict,
                             cfg: Dict[str, Any], eps: float) -> Tuple[float, Dict[str, float]]:
        """
        计算相对当前 PID 的变更惩罚（0~1）。
        使用对数倍率度量，避免靠人工“试凑”保守度。
        """
        if not current_pid or not candidate_pid:
            return 0.0, {
                'enabled': 0.0,
                'penalty': 0.0,
                'kp_move': 0.0,
                'ti_move': 0.0,
                'sign_flip': 0.0,
            }

        ratio_kp = max(1.01, float(cfg.get('method_select_move_ratio_kp', 4.0)))
        ratio_ti = max(1.01, float(cfg.get('method_select_move_ratio_ti', 4.0)))
        w_kp = float(cfg.get('method_select_move_kp_weight', 0.6))
        w_ti = float(cfg.get('method_select_move_ti_weight', 0.4))
        sign_flip_penalty = float(cfg.get('method_select_sign_flip_penalty', 0.7))

        kp_old, ti_old, _ = PidGuardService.extract_pid_triplet(current_pid, eps)
        kp_new, ti_new, _ = PidGuardService.extract_pid_triplet(candidate_pid, eps)

        kp_move = 0.0
        if abs(kp_old) > eps and abs(kp_new) > eps:
            kp_move = min(1.0, abs(np.log(abs(kp_new) / abs(kp_old))) / np.log(ratio_kp))

        ti_move = 0.0
        if ti_old > eps and ti_new > eps:
            ti_move = min(1.0, abs(np.log(ti_new / ti_old)) / np.log(ratio_ti))

        sign_flip = 0.0
        if abs(kp_old) > eps and abs(kp_new) > eps and kp_old * kp_new < 0:
            sign_flip = 1.0

        penalty = min(1.0, w_kp * kp_move + w_ti * ti_move + sign_flip_penalty * sign_flip)
        return penalty, {
            'enabled': 1.0,
            'penalty': float(penalty),
            'kp_move': float(kp_move),
            'ti_move': float(ti_move),
            'sign_flip': float(sign_flip),
        }

    @staticmethod
    def apply_current_pid_guard(pid_params: Dict[str, float],
                                current_pid: Optional[Dict],
                                data_confidence: float,
                                cfg: Dict[str, Any],
                                eps: float,
                                log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, float]:
        """相对 current_pid 的单次调参护栏。"""
        if not cfg.get('model_based_use_current_pid_guard', True):
            return pid_params
        if not current_pid:
            return pid_params

        kp_old, ti_old, _ = PidGuardService.extract_pid_triplet(current_pid, eps)
        if abs(kp_old) < eps and ti_old <= eps:
            return pid_params

        q = float(np.clip(data_confidence, 0.0, 1.0))
        kp_expand = float(cfg.get('model_based_kp_max_expand_base', 2.0)) + float(cfg.get('model_based_kp_max_expand_gain', 2.0)) * q
        kp_shrink = float(cfg.get('model_based_kp_max_shrink_base', 2.0)) + float(cfg.get('model_based_kp_max_shrink_gain', 2.0)) * q
        ti_expand = float(cfg.get('model_based_ti_max_expand_base', 1.8)) + float(cfg.get('model_based_ti_max_expand_gain', 1.2)) * q
        ti_shrink = float(cfg.get('model_based_ti_max_shrink_base', 2.2)) + float(cfg.get('model_based_ti_max_shrink_gain', 1.8)) * q

        adjusted = dict(pid_params)
        changed = False

        kp_new = float(adjusted.get('Kp', 0.0))
        if abs(kp_old) > eps and abs(kp_new) > eps:
            kp_abs = abs(kp_new)
            kp_lower = abs(kp_old) / max(1.01, kp_shrink)
            kp_upper = abs(kp_old) * max(1.01, kp_expand)
            kp_abs_capped = float(np.clip(kp_abs, kp_lower, kp_upper))
            kp_sign = 1.0 if kp_old >= 0 else -1.0
            kp_capped = kp_sign * kp_abs_capped
            if abs(kp_capped - kp_new) > 1e-9:
                changed = True
                adjusted['Kp'] = round(kp_capped, 4)

        ti_new = float(adjusted.get('Ti', 0.0))
        if ti_old > eps and ti_new > eps:
            ti_lower = ti_old / max(1.01, ti_shrink)
            ti_upper = ti_old * max(1.01, ti_expand)
            ti_capped = float(np.clip(ti_new, ti_lower, ti_upper))
            if abs(ti_capped - ti_new) > 1e-9:
                changed = True
                adjusted['Ti'] = round(ti_capped, 2)

        if changed:
            kp_val = float(adjusted.get('Kp', 0.0))
            ti_val = float(adjusted.get('Ti', 0.0))
            td_val = float(adjusted.get('Td', 0.0))
            adjusted['Ki'] = round(kp_val / ti_val, 4) if ti_val > eps else 0.0
            adjusted['Kd'] = round(kp_val * td_val, 4)
            adjusted['pb'] = round(100.0 / abs(kp_val), 2) if abs(kp_val) > eps else adjusted.get('pb', 100.0)
            if log_fn:
                log_fn(
                    f"   🔒 current_pid护栏生效: Kp→{adjusted.get('Kp', 0.0):.4f}, "
                    f"Ti→{adjusted.get('Ti', 0.0):.2f}s (q={q:.2f})"
                )

        return adjusted

    @staticmethod
    def apply_no_current_pid_guard(pid_params: Dict[str, float],
                                   quality_info: Any,
                                   loop_type: str,
                                   tuning_constraints: Dict,
                                   model_params: Optional[Dict[str, float]],
                                   pid_constraints: Dict[str, Any],
                                   robust_cfg: Dict[str, Any],
                                   cfg: Dict[str, Any],
                                   eps: float,
                                   log_fn: Optional[Callable[[str], None]] = None) -> Dict[str, float]:
        """current_pid 缺失时，基于数据风险自适应约束 PID。"""
        if not cfg.get('no_current_pid_guard_enabled', True):
            return pid_params

        tuning_constraints = tuning_constraints or {}
        model_params = model_params or {}
        adjusted = dict(pid_params)

        q = float(np.clip(getattr(quality_info, 'quality_score', 0.5), 0.0, 1.0))
        r2 = float(np.clip(getattr(quality_info, 'r_squared', 0.5), 0.0, 1.0))
        consistency = float(np.clip(getattr(quality_info, 'consistency_score', 0.5), 0.0, 1.0))
        osc = float(np.clip(getattr(quality_info, 'oscillation_ratio', 0.0), 0.0, 1.0))
        risk = float(np.clip(1.0 - (0.40 * q + 0.35 * r2 + 0.15 * consistency + 0.10 * (1.0 - osc)), 0.0, 1.0))

        pb_floor_factor = float(cfg.get('no_current_pid_pb_floor_factor', 0.8))
        pb_risk_gain = float(cfg.get('no_current_pid_pb_risk_gain', 1.0))
        ti_risk_gain = float(cfg.get('no_current_pid_ti_floor_risk_gain', 1.2))

        pb_min = float(tuning_constraints.get('pb_min', 0.0) or 0.0)
        if pb_min <= 0.0:
            if loop_type in ['flow', 'pressure']:
                pb_min = float(robust_cfg.get('min_pb_flow', 50.0))
            elif loop_type in ['temperature', 'level']:
                pb_min = float(robust_cfg.get('min_pb_temp', 100.0))
            else:
                pb_min = 35.0
        pb_floor = pb_min * max(0.2, pb_floor_factor + pb_risk_gain * risk)

        kp = float(adjusted.get('Kp', 0.0))
        if abs(kp) > eps:
            pb_now = 100.0 / abs(kp)
            if pb_now + 1e-9 < pb_floor:
                kp_sign = 1.0 if kp >= 0 else -1.0
                kp = kp_sign * (100.0 / pb_floor)
                adjusted['Kp'] = round(kp, 4)

        T1 = max(float(model_params.get('T1', 0.0)), eps)
        L = max(float(model_params.get('L', 0.0)), 0.0)
        ti_min_cfg = float(pid_constraints.get('ti_min', 0.1))
        if loop_type == 'level':
            ti_base = 60.0 * (1.0 + pid_constraints.get('ti_lower_buffer_ratio', 0.08))
        elif loop_type == 'temperature':
            ti_base = 5.0
        else:
            ti_base = max(ti_min_cfg, 0.25 * T1, 1.5 * L)
        ti_floor = ti_base * (1.0 + ti_risk_gain * risk)

        ti = float(adjusted.get('Ti', 0.0))
        if ti + 1e-9 < ti_floor:
            adjusted['Ti'] = round(ti_floor, 2)

        kp_val = float(adjusted.get('Kp', 0.0))
        ti_val = float(adjusted.get('Ti', 0.0))
        td_val = float(adjusted.get('Td', 0.0))
        adjusted['Ki'] = round(kp_val / ti_val, 4) if ti_val > eps else 0.0
        adjusted['Kd'] = round(kp_val * td_val, 4)
        adjusted['pb'] = round(100.0 / abs(kp_val), 2) if abs(kp_val) > eps else adjusted.get('pb', 100.0)
        if log_fn:
            log_fn(
                f"   🔒 no-current_pid护栏生效: 风险={risk:.2f}, PB={adjusted.get('pb', 0.0):.2f}%, "
                f"Ti={adjusted.get('Ti', 0.0):.2f}s"
            )
        return adjusted
