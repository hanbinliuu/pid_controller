"""
非线性模型拟合模块 (Nonlinear Model Fitter Module)
=================================================

本模块实现非线性过程模型的参数辨识算法。

支持的非线性模型
----------------
1. **Hammerstein**: 静态非线性 + 线性动态
   - 结构: f(u) -> FOPDT
   - f(u) = a1*u + a2*u^2 + a3*u^3 (多项式非线性)
   
2. **死区+FOPDT**: 阀门死区非线性
   - 结构: deadband(u) -> FOPDT
   - deadband(u) = 0 if |u-u0| < d else u-u0-sign(u-u0)*d
   
3. **饱和+FOPDT**: 阀门饱和非线性
   - 结构: saturation(u) -> FOPDT
   - saturation(u) = clip(u, low, high)

核心功能
--------
1. **非线性特征检测**: 分析数据判断是否存在死区、饱和等非线性
2. **非线性模型拟合**: 使用优化算法辨识非线性模型参数
3. **模型选择**: 比较线性与非线性模型，选择最优模型
4. **等效线性化**: 将非线性模型在工作点附近线性化用于PID整定
"""

import numpy as np
from scipy.optimize import least_squares
from typing import Dict, Tuple, Optional, List, Any
from dataclasses import dataclass

from ..config import Config, ModelType
from ..logger import LoggerMixin
from ..utils import calculate_r2, calculate_rmse


@dataclass
class NonlinearDetectionResult:
    """非线性检测结果"""
    has_deadband: bool = False          # 是否存在死区
    deadband_size: float = 0.0          # 死区大小估计
    has_saturation: bool = False        # 是否存在饱和
    saturation_low: float = 0.0         # 下饱和限
    saturation_high: float = 100.0      # 上饱和限
    nonlinearity_score: float = 0.0     # 非线性程度 (0~1)
    recommended_model: str = ""         # 推荐的非线性模型类型
    hysteresis_detected: bool = False   # 是否检测到滞回（黏滞）


@dataclass
class NonlinearFitResult:
    """非线性模型拟合结果"""
    model_type: str                     # 模型类型
    params: Dict[str, float]            # 模型参数
    r2: float                           # 决定系数
    rmse: float                         # 均方根误差
    linear_equivalent: Dict[str, float] # 等效线性模型参数 (K, T1, L)
    improvement_over_linear: float      # 相对线性模型的R²提升
    is_recommended: bool                # 是否推荐使用此模型


class NonlinearFitter(LoggerMixin):
    """
    非线性模型拟合器
    
    职责：
    1. 检测数据中的非线性特征（死区、饱和、滞回）
    2. 拟合非线性模型（Hammerstein、死区+FOPDT、饱和+FOPDT）
    3. 与线性模型比较，选择最优模型
    4. 提供等效线性化参数用于PID整定
    """
    
    def __init__(self, verbose: bool = False):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._config = Config.NONLINEAR_FITTING
    
    # ============================================================
    # 非线性特征检测
    # ============================================================
    
    def detect_nonlinearity(self, y: np.ndarray, u: np.ndarray) -> NonlinearDetectionResult:
        """
        检测数据中的非线性特征
        
        Args:
            y: PV数据 (过程变量)
            u: MV数据 (操纵变量)
        
        Returns:
            NonlinearDetectionResult: 非线性检测结果
        """
        result = NonlinearDetectionResult()
        
        if len(y) < 50 or len(u) < 50:
            return result
        
        # 1. 检测死区
        result.has_deadband, result.deadband_size = self._detect_deadband(y, u)
        
        # 2. 检测饱和
        result.has_saturation, result.saturation_low, result.saturation_high = \
            self._detect_saturation(y, u)
        
        # 3. 检测滞回（阀门黏滞）
        result.hysteresis_detected = self._detect_hysteresis(y, u)
        
        # 4. 计算整体非线性程度
        result.nonlinearity_score = self._calculate_nonlinearity_score(y, u)
        
        # 5. 推荐模型类型
        result.recommended_model = self._recommend_nonlinear_model(result)
        
        return result
    
    def _detect_deadband(self, y: np.ndarray, u: np.ndarray) -> Tuple[bool, float]:
        """
        检测死区特征
        
        死区特征：MV变化但PV无响应的区域
        """
        # 计算MV变化
        du = np.diff(u)
        dy = np.diff(y)
        
        # 找到MV有变化但PV无明显响应的点
        mv_threshold = np.std(du) * 0.5
        pv_threshold = np.std(dy) * 0.3
        
        # MV变化显著但PV无响应的比例
        mv_active = np.abs(du) > mv_threshold
        pv_inactive = np.abs(dy) < pv_threshold
        
        deadband_ratio = np.sum(mv_active & pv_inactive) / (np.sum(mv_active) + self._epsilon)
        
        has_deadband = deadband_ratio > self._config['deadband_detection_threshold']
        
        # 估计死区大小
        if has_deadband:
            # 找到PV开始响应时MV的变化量
            response_starts = []
            in_deadband = True
            accumulated_du = 0
            
            for i in range(len(du)):
                if mv_active[i]:
                    if in_deadband and not pv_inactive[i]:
                        # PV开始响应
                        response_starts.append(abs(accumulated_du))
                        in_deadband = False
                        accumulated_du = 0
                    elif in_deadband:
                        accumulated_du += du[i]
                else:
                    in_deadband = True
                    accumulated_du = 0
            
            deadband_size = np.median(response_starts) if response_starts else 0.0
        else:
            deadband_size = 0.0
        
        return has_deadband, deadband_size
    
    def _detect_saturation(self, y: np.ndarray, u: np.ndarray) -> Tuple[bool, float, float]:
        """
        检测饱和特征
        
        饱和特征：MV在极端值时PV不再随MV变化
        """
        # 分析MV在高位和低位时的响应
        u_sorted_idx = np.argsort(u)
        n = len(u)
        
        # 取MV最低10%和最高10%的数据
        low_idx = u_sorted_idx[:max(10, n // 10)]
        high_idx = u_sorted_idx[-max(10, n // 10):]
        
        # 计算这些区域内的MV-PV相关性
        def local_correlation(indices):
            if len(indices) < 5:
                return 1.0
            u_local = u[indices]
            y_local = y[indices]
            if np.std(u_local) < self._epsilon or np.std(y_local) < self._epsilon:
                return 0.0
            return abs(np.corrcoef(u_local, y_local)[0, 1])
        
        low_corr = local_correlation(low_idx)
        high_corr = local_correlation(high_idx)
        mid_idx = u_sorted_idx[n // 4: 3 * n // 4]
        mid_corr = local_correlation(mid_idx)
        
        # 如果极端区域相关性明显低于中间区域，可能存在饱和
        sat_threshold = self._config['saturation_detection_threshold']
        has_low_saturation = low_corr < mid_corr * (1 - sat_threshold)
        has_high_saturation = high_corr < mid_corr * (1 - sat_threshold)
        
        has_saturation = has_low_saturation or has_high_saturation
        
        # 估计饱和限
        if has_low_saturation:
            sat_low = np.percentile(u, 10)
        else:
            sat_low = np.min(u)
        
        if has_high_saturation:
            sat_high = np.percentile(u, 90)
        else:
            sat_high = np.max(u)
        
        return has_saturation, sat_low, sat_high
    
    def _detect_hysteresis(self, y: np.ndarray, u: np.ndarray) -> bool:
        """
        检测滞回特征（阀门黏滞）
        
        滞回特征：MV上升和下降时，相同MV对应的PV不同
        """
        # 找到MV变化方向
        du = np.diff(u)
        
        # 分离上升段和下降段
        rising_mask = np.concatenate([[False], du > 0])
        falling_mask = np.concatenate([[False], du < 0])
        
        # 将MV分箱，比较上升和下降时对应的PV
        n_bins = 10
        u_bins = np.linspace(np.min(u), np.max(u), n_bins + 1)
        
        hysteresis_score = 0
        valid_bins = 0
        
        for i in range(n_bins):
            bin_mask = (u >= u_bins[i]) & (u < u_bins[i + 1])
            rising_in_bin = bin_mask & rising_mask
            falling_in_bin = bin_mask & falling_mask
            
            if np.sum(rising_in_bin) > 2 and np.sum(falling_in_bin) > 2:
                y_rising = np.mean(y[rising_in_bin])
                y_falling = np.mean(y[falling_in_bin])
                pv_range = np.ptp(y)
                
                if pv_range > self._epsilon:
                    hysteresis_score += abs(y_rising - y_falling) / pv_range
                    valid_bins += 1
        
        if valid_bins > 0:
            avg_hysteresis = hysteresis_score / valid_bins
            return avg_hysteresis > 0.1  # 滞回超过PV范围的10%
        
        return False
    
    def _calculate_nonlinearity_score(self, y: np.ndarray, u: np.ndarray) -> float:
        """
        计算整体非线性程度
        
        方法：将数据分成多个区间，比较各区间的局部增益
        """
        # 按MV分成多个区间
        n_segments = 5
        u_percentiles = np.percentile(u, np.linspace(0, 100, n_segments + 1))
        
        local_gains = []
        for i in range(n_segments):
            mask = (u >= u_percentiles[i]) & (u <= u_percentiles[i + 1])
            if np.sum(mask) > 10:
                u_local = u[mask]
                y_local = y[mask]
                
                if np.std(u_local) > self._epsilon:
                    # 线性拟合估计局部增益
                    coeffs = np.polyfit(u_local, y_local, 1)
                    local_gains.append(coeffs[0])
        
        if len(local_gains) < 2:
            return 0.0
        
        # 非线性程度 = 增益变异系数
        gain_mean = np.mean(np.abs(local_gains))
        gain_std = np.std(local_gains)
        
        if gain_mean > self._epsilon:
            nonlinearity = min(1.0, gain_std / gain_mean)
        else:
            nonlinearity = 0.0
        
        return nonlinearity
    
    def _recommend_nonlinear_model(self, detection: NonlinearDetectionResult) -> str:
        """根据检测结果推荐非线性模型类型"""
        if detection.has_deadband and detection.deadband_size > 1.0:
            return ModelType.DEADBAND_FOPDT
        elif detection.has_saturation:
            return ModelType.SATURATION_FOPDT
        elif detection.nonlinearity_score > self._config['nonlinearity_threshold']:
            return ModelType.HAMMERSTEIN
        else:
            return ""  # 推荐使用线性模型
    
    # ============================================================
    # 非线性模型拟合
    # ============================================================
    
    def fit_nonlinear_models(self, y: np.ndarray, u: np.ndarray, 
                            detection: NonlinearDetectionResult,
                            linear_r2: float = 0.0) -> List[NonlinearFitResult]:
        """
        拟合非线性模型
        
        Args:
            y: PV数据
            u: MV数据
            detection: 非线性检测结果
            linear_r2: 线性模型的R²（用于比较）
        
        Returns:
            非线性模型拟合结果列表
        """
        results = []
        
        if not self._config['enable']:
            return results
        
        # 根据检测结果选择要尝试的模型
        models_to_try = []
        
        if detection.has_deadband:
            models_to_try.append(ModelType.DEADBAND_FOPDT)
        
        if detection.has_saturation:
            models_to_try.append(ModelType.SATURATION_FOPDT)
        
        if detection.nonlinearity_score > self._config['nonlinearity_threshold']:
            models_to_try.append(ModelType.HAMMERSTEIN)
        
        # 如果没有明显非线性，也尝试Hammerstein（可能捕获轻微非线性）
        if not models_to_try and detection.nonlinearity_score > 0.2:
            models_to_try.append(ModelType.HAMMERSTEIN)
        
        # 拟合每种模型
        for model_type in models_to_try:
            try:
                if model_type == ModelType.HAMMERSTEIN:
                    result = self._fit_hammerstein(y, u, linear_r2)
                elif model_type == ModelType.DEADBAND_FOPDT:
                    result = self._fit_deadband_fopdt(y, u, detection.deadband_size, linear_r2)
                elif model_type == ModelType.SATURATION_FOPDT:
                    result = self._fit_saturation_fopdt(
                        y, u, detection.saturation_low, detection.saturation_high, linear_r2
                    )
                else:
                    continue
                
                if result is not None:
                    results.append(result)
                    self.log(f"   {model_type}: R²={result.r2:.4f}, "
                            f"提升={result.improvement_over_linear:.4f}")
            except Exception as e:
                self.log(f"   ⚠️ {model_type} 拟合失败: {e}")
        
        return results
    
    def _fit_hammerstein(self, y: np.ndarray, u: np.ndarray, 
                        linear_r2: float) -> Optional[NonlinearFitResult]:
        """
        拟合Hammerstein模型
        
        模型结构: f(u) -> FOPDT
        f(u) = a1*u + a2*u^2 + a3*u^3
        """
        n = len(y)
        y0 = y[0]
        u0 = u[0]
        
        # 归一化输入
        u_norm = (u - u0) / (np.std(u) + self._epsilon)
        
        def hammerstein_residuals(params):
            K, T1, L, a1, a2, a3 = params
            
            # 非线性变换
            u_nl = a1 * u_norm + a2 * u_norm**2 + a3 * u_norm**3
            
            # FOPDT仿真
            y_sim = self._simulate_fopdt_incremental(y0, u_nl, K, T1, L)
            
            return y_sim - y
        
        # 获取边界
        bounds = Config.MODEL_BOUNDS.get('HAMMERSTEIN', {})
        lb = bounds.get('initial', ([-10, 1, 0, 0.1, -1, -0.5], [10, 500, 50, 5, 1, 0.5]))[0]
        ub = bounds.get('initial', ([-10, 1, 0, 0.1, -1, -0.5], [10, 500, 50, 5, 1, 0.5]))[1]
        
        # 初始猜测
        pv_range = np.ptp(y)
        mv_range = np.ptp(u)
        k_guess = pv_range / (mv_range + self._epsilon)
        
        x0 = [k_guess, 10.0, 1.0, 1.0, 0.0, 0.0]
        
        try:
            result = least_squares(
                hammerstein_residuals, x0,
                bounds=(lb, ub),
                method='trf',
                max_nfev=500
            )
            
            K, T1, L, a1, a2, a3 = result.x
            
            # 计算拟合优度
            u_nl = a1 * u_norm + a2 * u_norm**2 + a3 * u_norm**3
            y_sim = self._simulate_fopdt_incremental(y0, u_nl, K, T1, L)
            r2 = calculate_r2(y, y_sim)
            rmse = calculate_rmse(y, y_sim)
            
            # 等效线性化（在工作点附近）
            # f'(u) = a1 + 2*a2*u + 3*a3*u^2，在u=0处 f'(0) = a1
            linear_gain = K * a1
            
            improvement = r2 - linear_r2
            is_recommended = improvement > self._config['r2_improvement_threshold']
            
            return NonlinearFitResult(
                model_type=ModelType.HAMMERSTEIN,
                params={'K': K, 'T1': T1, 'L': L, 'a1': a1, 'a2': a2, 'a3': a3},
                r2=r2,
                rmse=rmse,
                linear_equivalent={'K': linear_gain, 'T1': T1, 'L': L},
                improvement_over_linear=improvement,
                is_recommended=is_recommended
            )
        except Exception as e:
            self.log(f"   Hammerstein拟合异常: {e}")
            return None
    
    def _fit_deadband_fopdt(self, y: np.ndarray, u: np.ndarray,
                           deadband_guess: float, linear_r2: float) -> Optional[NonlinearFitResult]:
        """
        拟合死区+FOPDT模型
        
        模型结构: deadband(u) -> FOPDT
        """
        y0 = y[0]
        u0 = u[0]
        
        def deadband_transform(u_val, u_center, deadband):
            """死区变换"""
            u_rel = u_val - u_center
            if abs(u_rel) < deadband / 2:
                return 0.0
            elif u_rel > 0:
                return u_rel - deadband / 2
            else:
                return u_rel + deadband / 2
        
        deadband_vec = np.vectorize(deadband_transform)
        
        def deadband_residuals(params):
            K, T1, L, deadband = params
            
            # 死区变换
            u_db = deadband_vec(u, u0, deadband)
            
            # FOPDT仿真
            y_sim = self._simulate_fopdt_incremental(y0, u_db, K, T1, L)
            
            return y_sim - y
        
        # 边界
        bounds = Config.MODEL_BOUNDS.get('DEADBAND_FOPDT', {})
        lb = bounds.get('initial', ([-10, 1, 0, 0.5], [10, 500, 50, 20]))[0]
        ub = bounds.get('initial', ([-10, 1, 0, 0.5], [10, 500, 50, 20]))[1]
        
        # 初始猜测
        pv_range = np.ptp(y)
        mv_range = np.ptp(u)
        k_guess = pv_range / (mv_range + self._epsilon)
        
        x0 = [k_guess, 10.0, 1.0, max(deadband_guess, 1.0)]
        
        try:
            result = least_squares(
                deadband_residuals, x0,
                bounds=(lb, ub),
                method='trf',
                max_nfev=500
            )
            
            K, T1, L, deadband = result.x
            
            # 计算拟合优度
            u_db = deadband_vec(u, u0, deadband)
            y_sim = self._simulate_fopdt_incremental(y0, u_db, K, T1, L)
            r2 = calculate_r2(y, y_sim)
            rmse = calculate_rmse(y, y_sim)
            
            improvement = r2 - linear_r2
            is_recommended = improvement > self._config['r2_improvement_threshold']
            
            return NonlinearFitResult(
                model_type=ModelType.DEADBAND_FOPDT,
                params={'K': K, 'T1': T1, 'L': L, 'deadband': deadband},
                r2=r2,
                rmse=rmse,
                linear_equivalent={'K': K, 'T1': T1, 'L': L},
                improvement_over_linear=improvement,
                is_recommended=is_recommended
            )
        except Exception as e:
            self.log(f"   DeadbandFOPDT拟合异常: {e}")
            return None
    
    def _fit_saturation_fopdt(self, y: np.ndarray, u: np.ndarray,
                             sat_low_guess: float, sat_high_guess: float,
                             linear_r2: float) -> Optional[NonlinearFitResult]:
        """
        拟合饱和+FOPDT模型
        
        模型结构: saturation(u) -> FOPDT
        """
        y0 = y[0]
        u0 = u[0]
        
        def saturation_residuals(params):
            K, T1, L, sat_low, sat_high = params
            
            # 饱和变换
            u_sat = np.clip(u, sat_low, sat_high) - u0
            
            # FOPDT仿真
            y_sim = self._simulate_fopdt_incremental(y0, u_sat, K, T1, L)
            
            return y_sim - y
        
        # 边界
        bounds = Config.MODEL_BOUNDS.get('SAT_FOPDT', {})
        lb = list(bounds.get('initial', ([-10, 1, 0, 0, 50], [10, 500, 50, 50, 100]))[0])
        ub = list(bounds.get('initial', ([-10, 1, 0, 0, 50], [10, 500, 50, 50, 100]))[1])
        
        # 调整边界以适应数据（使用副本避免修改原始配置）
        # 确保 sat_low 和 sat_high 的边界合理
        u_min, u_max = np.min(u), np.max(u)
        
        # sat_low 边界: 允许在数据最小值附近
        lb[3] = max(0, u_min - 10)
        ub[3] = max(lb[3] + 1, sat_high_guess - 1)  # sat_low 必须小于 sat_high
        
        # sat_high 边界: 允许在数据最大值附近  
        lb[4] = max(ub[3] + 1, sat_low_guess + 1)  # sat_high 必须大于 sat_low
        ub[4] = max(lb[4] + 1, u_max + 10, 100)
        
        # 最终验证：确保所有 lb[i] < ub[i]
        for i in range(len(lb)):
            if lb[i] >= ub[i]:
                # 如果边界无效，使用默认合理值
                self.log(f"   ⚠️ 边界无效: lb[{i}]={lb[i]} >= ub[{i}]={ub[i]}, 使用默认值")
                if i == 3:  # sat_low
                    lb[i], ub[i] = 0, 50
                elif i == 4:  # sat_high
                    lb[i], ub[i] = 51, 100
        
        # 初始猜测
        pv_range = np.ptp(y)
        mv_range = np.ptp(u)
        k_guess = pv_range / (mv_range + self._epsilon)
        
        # 确保初始值在边界内
        sat_low_init = np.clip(sat_low_guess, lb[3], ub[3])
        sat_high_init = np.clip(sat_high_guess, lb[4], ub[4])
        
        x0 = [k_guess, 10.0, 1.0, sat_low_init, sat_high_init]
        
        try:
            result = least_squares(
                saturation_residuals, x0,
                bounds=(lb, ub),
                method='trf',
                max_nfev=500
            )
            
            K, T1, L, sat_low, sat_high = result.x
            
            # 计算拟合优度
            u_sat = np.clip(u, sat_low, sat_high) - u0
            y_sim = self._simulate_fopdt_incremental(y0, u_sat, K, T1, L)
            r2 = calculate_r2(y, y_sim)
            rmse = calculate_rmse(y, y_sim)
            
            improvement = r2 - linear_r2
            is_recommended = improvement > self._config['r2_improvement_threshold']
            
            return NonlinearFitResult(
                model_type=ModelType.SATURATION_FOPDT,
                params={'K': K, 'T1': T1, 'L': L, 'sat_low': sat_low, 'sat_high': sat_high},
                r2=r2,
                rmse=rmse,
                linear_equivalent={'K': K, 'T1': T1, 'L': L},
                improvement_over_linear=improvement,
                is_recommended=is_recommended
            )
        except Exception as e:
            self.log(f"   SaturationFOPDT拟合异常: {e}")
            return None
    
    def _simulate_fopdt_incremental(self, y0: float, u: np.ndarray, 
                                    K: float, T1: float, L: float) -> np.ndarray:
        """
        FOPDT增量形式仿真
        
        y[k] = y[k-1] + (K*u[k-L] - (y[k-1]-y0)) / T1
        """
        n = len(u)
        y = np.zeros(n)
        y[0] = y0
        
        L_int = max(0, int(round(L)))
        T1 = max(T1, 0.1)
        
        for k in range(1, n):
            u_delayed = u[k - L_int] if k >= L_int else u[0]
            y[k] = y[k-1] + (K * u_delayed - (y[k-1] - y0)) / T1
        
        return y
    
    # ============================================================
    # 最佳模型选择
    # ============================================================
    
    def select_best_model(self, linear_result: Dict, 
                         nonlinear_results: List[NonlinearFitResult]) -> Tuple[str, Dict, bool]:
        """
        选择最佳模型（线性或非线性）
        
        Args:
            linear_result: 线性模型结果 {model_type, r2, params}
            nonlinear_results: 非线性模型结果列表
        
        Returns:
            (best_model_type, best_params, is_nonlinear)
        """
        linear_r2 = linear_result.get('r2', 0)
        
        # 找最佳非线性模型
        best_nonlinear = None
        for result in nonlinear_results:
            if result.is_recommended:
                if best_nonlinear is None or result.r2 > best_nonlinear.r2:
                    best_nonlinear = result
        
        # 比较线性和非线性
        if best_nonlinear is None:
            return linear_result.get('model_type', 'FOPDT'), linear_result.get('params', {}), False
        
        # 非线性模型需要显著优于线性模型
        if best_nonlinear.improvement_over_linear > self._config['r2_improvement_threshold']:
            self.log(f"   ✅ 选择非线性模型 {best_nonlinear.model_type}，"
                    f"R²提升 {best_nonlinear.improvement_over_linear:.4f}")
            return best_nonlinear.model_type, best_nonlinear.params, True
        else:
            self.log(f"   📊 非线性模型提升不足，保持线性模型")
            return linear_result.get('model_type', 'FOPDT'), linear_result.get('params', {}), False
    
    def get_equivalent_linear_params(self, nonlinear_result: NonlinearFitResult) -> Dict[str, float]:
        """
        获取非线性模型的等效线性参数（用于PID整定）
        """
        return nonlinear_result.linear_equivalent
