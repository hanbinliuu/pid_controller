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
from ..config import Config, ModelType


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
        """
        一阶无滞后系统整定（根据回路类型选择 SIMC 或 Lambda）
        """
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        
        # 根据回路类型选择整定方法
        use_simc = self._should_use_simc(loop_type)
        
        if use_simc:
            # SIMC 模式
            tau_c_factor = simc_cfg.get('tau_c_factor', 1.0)
            tau_c = T1 * lambda_factor * tau_c_factor * (conservative_level / baseline)
            
            denom = K * tau_c
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            
            Kp = T1 / denom
            
            # SIMC Ti 上限约束
            ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
            Ti = min(T1, ti_limit_factor * tau_c)
        else:
            # Lambda 模式
            lambda_val = T1 * lambda_factor * conservative_level
            
            denom = K * lambda_val
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            
            Kp = T1 / denom
            Ti = T1
        
        # 根据pb_min计算max_Kp
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        Td = 0.0
        
        return Kp, Ti, Td
    
    def _tune_fopdt(self, K: float, T1: float, L: float, 
                    lambda_factor: float, method: str,
                    conservative_level: float = 4.0,
                    pb_min: float = 60.0, loop_type: str = None) -> Tuple[float, float, float]:
        """
        一阶加纯滞后系统整定（根据回路类型选择 SIMC 或 Lambda）
        
        支持多种整定方法：
        - lambda/simc: 根据回路类型自动选择
        - cohen_coon: Cohen-Coon法（适合L/T1较大）
        - imc_aggressive: IMC激进模式
        """
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        
        if method == 'cohen_coon' and L > self._epsilon:
            # Cohen-Coon 法
            cc_factor = self._pid_constraints.get('cohen_coon_conservative_factor', 0.85)
            Kp = cc_factor * (1.35 / K) * (T1 / L + 0.185)
            Ti = 2.5 * L * (T1 + 0.185 * L) / (T1 + 0.611 * L)
            Td = 0.37 * L * T1 / (T1 + 0.185 * L)
            
        elif method == 'imc_aggressive':
            # IMC 激进模式
            tau_c = max(L, T1 * 0.1)
            denom = K * (tau_c + L)
            if denom < self._epsilon:
                return self._get_fallback_params(Ti_override=T1)
            Kp = T1 / denom
            Ti = min(T1, 4 * (tau_c + L))
            Td = 0.0
            
        else:
            # 根据回路类型选择整定方法
            use_simc = self._should_use_simc(loop_type)
            
            if use_simc:
                # ========== SIMC 模式 ==========
                tau_c_factor = simc_cfg.get('tau_c_factor', 1.0)
                tau_c = T1 * lambda_factor * tau_c_factor * (conservative_level / baseline)
                
                tau_c_min_factor = simc_cfg.get('tau_c_min_factor', 0.5)
                tau_c = max(tau_c, L * tau_c_min_factor)
                
                denom = K * (tau_c + L)
                if denom < self._epsilon:
                    return self._get_fallback_params(Ti_override=T1)
                
                Kp = T1 / denom
                
                ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
                Ti = min(T1, ti_limit_factor * (tau_c + L))
                Td = 0.0
            else:
                # ========== Lambda 模式 ==========
                lambda_val = T1 * lambda_factor * (conservative_level / baseline)
                denom = K * (lambda_val + L / 2)
                if denom < self._epsilon:
                    return self._get_fallback_params(Ti_override=T1 + L / 2)
                Kp = (T1 + L / 2) / denom
                Ti = T1 + L / 2
                Td = T1 * L / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_sopdt(self, K: float, T1: float, T2: float, L: float,
                    lambda_factor: float, conservative_level: float = 4.0,
                    pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        二阶系统整定（SIMC 半规则）
        
        SIMC 半规则 (Skogestad 2003):
        - T_eff = T1 + T2/2（等效时间常数）
        - L_eff = L + T2/2（等效滞后）
        - τc = T_eff * lambda_factor
        - Kp = T_eff / (K * (τc + L_eff))
        - Ti = min(T_eff, 4 * (τc + L_eff))
        """
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        use_half_rule = simc_cfg.get('use_half_rule', True)
        
        if use_half_rule and T2 > 0:
            # SIMC 半规则：将二阶近似为一阶
            T_eff = T1 + T2 / 2
            L_eff = L + T2 / 2
        else:
            # 传统方法
            T_eff = T1 + T2 if T2 > 0 else T1
            L_eff = L
        
        # 计算闭环时间常数 τc
        tau_c_factor = simc_cfg.get('tau_c_factor', 1.0)
        tau_c = T_eff * lambda_factor * tau_c_factor * (conservative_level / baseline)
        
        # SIMC 公式
        denom = K * (tau_c + L_eff)
        if denom < self._epsilon:
            return self._get_fallback_params(Ti_override=T_eff)
        
        Kp = T_eff / denom
        
        # SIMC Ti 上限约束
        ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
        Ti = min(T_eff, ti_limit_factor * (tau_c + L_eff))
        
        # SIMC 推荐 PI 控制，但二阶系统可选加微分
        Td = 0.0
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
        if Kp > max_Kp:
            Kp = max_Kp
        
        return Kp, Ti, Td
    
    def _tune_integrator(self, K: float, T1: float, 
                         lambda_factor: float, conservative_level: float = 4.0,
                         pb_min: float = 60.0) -> Tuple[float, float, float]:
        """
        积分过程整定（SIMC 方法）
        
        积分过程: G(s) = K' / s（典型液位回路）
        
        SIMC 公式 (Skogestad 2003):
        - τc = 4 * T1（T1 作为等效滞后）
        - Kp = 1 / (K * (τc + T1))
        - Ti = 4 * (τc + T1)
        """
        if abs(K) < self._epsilon:
            return self._get_fallback_params()
        
        simc_cfg = getattr(Config, 'SIMC_TUNING', {})
        baseline = self._pid_constraints.get('conservative_level_baseline', 4.0)
        
        # 积分过程的 τc 计算（T1 作为等效滞后）
        int_tau_c_factor = simc_cfg.get('integrating_tau_c_factor', 4.0)
        tau_c = T1 * int_tau_c_factor * lambda_factor * (conservative_level / baseline)
        tau_c = max(tau_c, 0.2)  # 确保最小值
        
        # SIMC 积分过程公式
        # Kp = 1 / (K * (τc + T1))，这里 T1 作为等效滞后
        denom = K * (tau_c + T1) if T1 > 0 else K * tau_c
        Kp = 1.0 / denom if denom > self._epsilon else self._get_max_kp(pb_min)
        
        # Ti = 4 * (τc + T1)
        ti_limit_factor = simc_cfg.get('ti_limit_factor', 4.0)
        Ti = ti_limit_factor * (tau_c + T1) if T1 > 0 else ti_limit_factor * tau_c
        
        Td = 0.0  # 积分过程不用微分
        
        # 应用pb下限
        max_Kp = self._get_max_kp(pb_min)
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
        # 非线性模型需要额外的保守度（从配置读取）
        nl_factors = self._pid_constraints.get('nonlinear_factors', {})
        nonlinear_factor = nl_factors.get('default', 1.3)
        
        if model_type == ModelType.HAMMERSTEIN:
            nonlinear_factor = nl_factors.get('HAMMERSTEIN', 1.4)
        elif model_type == ModelType.DEADBAND_FOPDT:
            nonlinear_factor = nl_factors.get('DEADBAND_FOPDT', 1.5)
        elif model_type == ModelType.SATURATION_FOPDT:
            nonlinear_factor = nl_factors.get('SAT_FOPDT', 1.3)
        
        # 应用非线性补偿到保守等级
        adjusted_conservative = conservative_level * nonlinear_factor
        adjusted_pb_min = pb_min * nonlinear_factor
        
        # 使用FOPDT整定公式
        Kp, Ti, Td = self._tune_fopdt(K, T1, L, lambda_factor, method,
                                       adjusted_conservative, adjusted_pb_min)
        
        # 非线性模型一般不使用微分（避免放大噪声）
        Td = Td * 0.5
        
        # 死区专用补偿：增强积分作用以消除稳态误差
        if model_type == ModelType.DEADBAND_FOPDT:
            db_comp = self._pid_constraints.get('deadband_compensation', {})
            if db_comp.get('enable', True):
                ti_factor = db_comp.get('ti_reduction_factor', 0.7)
                Ti = Ti * ti_factor  # 减小Ti，加快积分消除稳态误差

        return Kp, Ti, Td
    
    def _apply_constraints(self, Kp: float, Ti: float, Td: float,
                           K_sign: int) -> Tuple[float, float, float]:
        """应用参数合理性约束（从配置读取阈值）"""
        cfg = self._pid_constraints
        
        # 1. 限制Kp的绝对值下限
        kp_min = cfg.get('kp_min', 0.01)
        if abs(Kp) < kp_min:
            Kp = kp_min * K_sign
        
        # 2. 限制Ti的范围
        ti_min = cfg.get('ti_min', 0.1)
        ti_max = cfg.get('ti_max', 120.0)
        Ti = max(ti_min, min(Ti, ti_max))
        
        # 3. 限制Td的范围（不超过 Ti * td_max_ratio）
        td_max_ratio = cfg.get('td_max_ratio', 0.25)
        Td = max(0.0, min(Td, Ti * td_max_ratio))
        
        return Kp, Ti, Td
