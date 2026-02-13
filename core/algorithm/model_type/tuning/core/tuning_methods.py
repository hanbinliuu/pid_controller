"""
PID整定方法模块 (Tuning Methods Module)
======================================

包含各种PID整定公式的实现：
- Lambda/IMC法
- Cohen-Coon法
- 积分过程整定
- 非线性模型整定
"""

from typing import Tuple
from ...config import Config, ModelType
from ...config.loop_presets import get_loop_preset


class TuningMethodsMixin:
    """
    整定方法Mixin类
    
    提供各种模型类型的PID参数整定公式。
    需要宿主类提供 _epsilon, _pid_constraints, _get_fallback_params, _get_max_kp 属性/方法。
    """
    
    def _should_use_simc(self, loop_type: str = None) -> bool:
        """根据回路类型决定是否使用 SIMC（混合策略）"""
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        
        # 如果全局禁用 SIMC，直接返回 False
        if not simc_cfg.get('enable', True):
            return False
        
        # 如果有 loop_type，按配置选择
        if loop_type:
            loop_methods = simc_cfg.get('loop_type_method', {})
            loop_type_lower = loop_type.lower()
            return loop_methods.get(loop_type_lower, loop_methods.get('default', True))
        
        # 无 loop_type 时使用全局设置
        return simc_cfg.get('enable', True)
    
    def _tune_fo(self, K: float, T1: float, lambda_factor: float, 
                 method: str, conservative_level: float = 4.0,
                 pb_min: float = 60.0, loop_type: str = None) -> Tuple[float, float, float]:
        """一阶无滞后系统整定（根据回路类型选择 SIMC 或 Lambda）"""
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        use_simc = self._should_use_simc(loop_type)
        
        # 获取回路预设参数
        preset = get_loop_preset(loop_type)
        preset_tau_c_factor = preset.get('tau_c_factor', None)
        preset_ti_multiplier = preset.get('ti_multiplier', 1.0)
        
        if use_simc:
            tau_c_factor = preset_tau_c_factor if preset_tau_c_factor else simc_cfg.get('tau_c_factor', 1.0)
            # 对于流量和压力回路，响应时间应与过程惯性 T1 无关，采用固定比例或考虑滞后
            base_tau = T1
            if loop_type in ['flow', 'pressure']:
                base_tau = max(1.0, T1 / 5.0) # 无滞后情况下，以 T1 的一部分作为基准
            
            tau_c = base_tau * lambda_factor * tau_c_factor * (conservative_level / baseline)
            denom = K * tau_c
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            Kp = T1 / denom
            ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
            
            # Ti 限幅逻辑优化：对于积分过程或慢速回路（multiplier > 1），允许 Ti > T1
            if preset_ti_multiplier > 1.0:
                Ti = min(T1 * preset_ti_multiplier, ti_limit_factor * tau_c)
            else:
                Ti = min(T1, ti_limit_factor * tau_c)
        else:
            # Lambda 整定法: 也需要应用回路预设的 tau_c_factor
            tau_c_factor = preset_tau_c_factor if preset_tau_c_factor else 1.0
            lambda_val = T1 * lambda_factor * tau_c_factor * conservative_level
            denom = K * lambda_val
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            Kp = T1 / denom
            Ti = T1
        
        # 应用回路预设的Ti乘数
        Ti *= preset_ti_multiplier
        
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        # 应用回路预设的Td
        Td = 0.0
        if preset.get('td_enable', False):
            td_ratio = preset.get('td_ratio', 0.15)
            td_max = preset.get('td_max', 999.0)
            Td = min(Ti * td_ratio, td_max)
        
        return Kp, Ti, Td
    
    def _tune_fopdt(self, K: float, T1: float, L: float, 
                    lambda_factor: float, method: str,
                    conservative_level: float = 4.0,
                    pb_min: float = 60.0, loop_type: str = None) -> Tuple[float, float, float]:
        """一阶加纯滞后系统整定（根据回路类型选择 SIMC 或 Lambda）"""
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        
        # 获取回路预设参数
        preset = get_loop_preset(loop_type)
        preset_tau_c_factor = preset.get('tau_c_factor', None)
        preset_ti_multiplier = preset.get('ti_multiplier', 1.0)
        
        if method == 'cohen_coon' and L > self._epsilon:
            cc_factor = self._pid_constraints.get('cohen_coon_conservative_factor', 0.85)
            Kp = cc_factor * (1.35 / K) * (T1 / L + 0.185)
            Ti = 2.5 * L * (T1 + 0.185 * L) / (T1 + 0.611 * L)
            Td = 0.37 * L * T1 / (T1 + 0.185 * L)
        elif method == 'imc_aggressive':
            tau_c = max(L, T1 * 0.1)
            denom = K * (tau_c + L)
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            Kp = T1 / denom
            Ti = min(T1, 4 * (tau_c + L))
            Td = 0.0
        else:
            use_simc = self._should_use_simc(loop_type)
            if use_simc:
                tau_c_factor = preset_tau_c_factor if preset_tau_c_factor else simc_cfg.get('tau_c_factor', 1.0)
                # 对于快过程，tau_c 应与滞后 L 相关，而非大惯性 T1 (解决 PB 膨胀)
                base_tau = T1
                if loop_type in ['flow', 'pressure']:
                    base_tau = max(L, T1 / 10.0) if L > 0.01 else T1 / 5.0
                
                tau_c = base_tau * lambda_factor * tau_c_factor * (conservative_level / baseline)
                tau_c_min_factor = simc_cfg.get('tau_c_min_factor', 0.5)
                tau_c = max(tau_c, L * tau_c_min_factor)
                denom = K * (tau_c + L)
                if denom < self._epsilon:
                    return self._get_fallback_params(Ti_override=T1)
                Kp = T1 / denom
                ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
                
                # Ti 限幅逻辑优化
                if preset_ti_multiplier > 1.0:
                    Ti = min(T1 * preset_ti_multiplier, ti_limit_factor * (tau_c + L))
                else:
                    Ti = min(T1, ti_limit_factor * (tau_c + L))
                Td = 0.0
            else:
                # Lambda 整定法: 同样修正基准时间
                tau_c_factor = preset_tau_c_factor if preset_tau_c_factor else 1.0
                base_tau = T1
                if loop_type in ['flow', 'pressure']:
                    base_tau = max(L, T1 / 10.0) if L > 0.01 else T1 / 5.0
                
                lambda_val = base_tau * lambda_factor * tau_c_factor * (conservative_level / baseline)
                denom = K * (lambda_val + L / 2)
                if denom < self._epsilon:
                    return self._get_fallback_params(Ti_override=T1 + L / 2)
                Kp = (T1 + L / 2) / denom
                Ti = T1 + L / 2
                Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        # 应用回路预设的Ti乘数
        Ti *= preset_ti_multiplier
        
        # 应用回路预设的Td（如果当前Td=0且预设启用微分）
        if Td == 0.0 and preset.get('td_enable', False):
            td_ratio = preset.get('td_ratio', 0.15)
            Td = Ti * td_ratio
        # 应用 Td 绝对上限
        td_max = preset.get('td_max', 999.0)
        Td = min(Td, td_max)
        
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        return Kp, Ti, Td
    
    def _tune_sopdt(self, K: float, T1: float, T2: float, L: float,
                    lambda_factor: float, conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """二阶系统整定（SIMC 半规则）"""
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        use_half_rule = simc_cfg.get('use_half_rule', True)
        
        if use_half_rule and T2 > 0:
            T_eff = T1 + T2 / 2
            L_eff = L + T2 / 2
        else:
            T_eff = T1 + T2 if T2 > 0 else T1
            L_eff = L
        
        tau_c_factor = simc_cfg.get('tau_c_factor', 1.0)
        tau_c = T_eff * lambda_factor * tau_c_factor * (conservative_level / baseline)
        denom = K * (tau_c + L_eff)
        if denom < self._epsilon:
            return self._get_fallback_params(Ti_override=T_eff)
        
        Kp = T_eff / denom
        ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
        Ti = min(T_eff, ti_limit_factor * (tau_c + L_eff))
        Td = 0.0
        
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        return Kp, Ti, Td
    
    def _tune_integrator(self, K: float, T1: float, 
                         lambda_factor: float, conservative_level: float = 4.0,
                         pb_min: float = 60.0) -> Tuple[float, float, float]:
        """积分过程整定（SIMC 方法）"""
        if abs(K) < self._epsilon:
            return self._get_fallback_params()
        
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        int_tau_c_factor = simc_cfg.get('integrating_tau_c_factor', 4.0)
        tau_c = T1 * int_tau_c_factor * lambda_factor * (conservative_level / baseline)
        tau_c = max(tau_c, 0.2)
        
        denom = K * (tau_c + T1) if T1 > 0 else K * tau_c
        Kp = 1.0 / denom if denom > self._epsilon else self._get_max_kp(pb_min)
        ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
        Ti = ti_limit_factor * (tau_c + T1) if T1 > 0 else ti_limit_factor * tau_c
        Td = 0.0
        
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        return Kp, Ti, Td
    
    def _tune_nonlinear(self, K: float, T1: float, L: float,
                        lambda_factor: float, method: str,
                        conservative_level: float, pb_min: float,
                        model_type: str) -> Tuple[float, float, float]:
        """非线性模型整定（使用等效线性化参数）"""
        nl_factors = self._pid_constraints.get('nonlinear_factors', {})
        nonlinear_factor = nl_factors.get('default', 1.3)
        
        if model_type == ModelType.HAMMERSTEIN:
            nonlinear_factor = nl_factors.get('HAMMERSTEIN', 1.4)
        elif model_type == ModelType.DEADBAND_FOPDT:
            nonlinear_factor = nl_factors.get('DEADBAND_FOPDT', 1.5)
        elif model_type == ModelType.SATURATION_FOPDT:
            nonlinear_factor = nl_factors.get('SAT_FOPDT', 1.3)
        
        adjusted_conservative = conservative_level * nonlinear_factor
        adjusted_pb_min = pb_min * nonlinear_factor
        Kp, Ti, Td = self._tune_fopdt(K, T1, L, lambda_factor, method,
                                       adjusted_conservative, adjusted_pb_min)
        Td = Td * 0.5
        
        if model_type == ModelType.DEADBAND_FOPDT:
            db_comp = self._pid_constraints.get('deadband_compensation', {})
            if db_comp.get('enable', True):
                ti_factor = db_comp.get('ti_reduction_factor', 0.7)
                Ti = Ti * ti_factor
        return Kp, Ti, Td
    
    def _apply_constraints(self, Kp: float, Ti: float, Td: float,
                           K_sign: int) -> Tuple[float, float, float]:
        """应用参数合理性约束"""
        cfg = self._pid_constraints
        kp_min = cfg.get('kp_min', 0.01)
        if abs(Kp) < kp_min:
            Kp = kp_min * K_sign
        
        ti_min = cfg.get('ti_min', 0.1)
        ti_max = cfg.get('ti_max', 120.0)
        Ti = max(ti_min, min(Ti, ti_max))
        
        td_max_ratio = cfg.get('td_max_ratio', 0.25)
        Td = max(0.0, min(Td, Ti * td_max_ratio))
        return Kp, Ti, Td
