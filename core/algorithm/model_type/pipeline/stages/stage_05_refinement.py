import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from scipy.optimize import least_squares

from ..context import TuningContext
from .base_stage import PipelineStage
from ...data_models import FusionResult, HistoricalData
from ...utils import calculate_r2, calculate_rmse, build_segment_info
from ...config import Config, ModelType
from ...tuning import TuningMethod


class RefinementStage(PipelineStage):
    """
    模型优化与冗余兜底阶段:
    1. 验证一致性与仿真匹配度 (_validate_and_refine)
    2. 恢复闭环修正T1
    3. 检查融合参数有效性 (尝试 Oscillation Fallback)
    4. 继电反馈法 (Relay Feedback) 的方法竞争如果更优秀则采用其参数
    """
    def __init__(self, simulator, oscillation_tuner, method_selector, pid_calculator, verbose=False, logger_mixin=None):
        super().__init__(logger_mixin)
        self._simulator = simulator
        self._oscillation_tuner = oscillation_tuner
        self._method_selector = method_selector
        self._pid_calculator = pid_calculator
        self._verbose = verbose
        self._epsilon = 1e-6

    def _compute_segment_metrics(self, segments: List[HistoricalData], params: tuple,
                                  model_type: str, enhanced: bool = False
                                  ) -> Tuple[List[float], List[float], List[int]]:
        """计算扰动段的R²和RMSE指标"""
        r2_list = []
        rmse_list = []
        points_list = []
        
        for seg in segments:
            seg_valid = seg.pv != 0
            y = seg.pv[seg_valid]
            u = seg.mv[seg_valid]
            sv = seg.sv[seg_valid] if hasattr(seg, 'sv') and seg.sv is not None else None
            if len(y) < 5:
                continue
            
            y_pred = self._simulator.simulate_segmented(
                params, model_type, y, u,
                reset_on_sv_change=True, sv=sv,
                enable_smooth=True,
                enable_amplitude_calibration=enhanced,
                enable_offset_correction=enhanced,
                enable_oscillation_overlay=enhanced
            )
            
            r2_list.append(calculate_r2(y, y_pred))
            rmse_list.append(calculate_rmse(y, y_pred))
            points_list.append(len(y))
        
        return r2_list, rmse_list, points_list
    
    def _compute_weighted_metrics(self, r2_list: List[float], rmse_list: List[float],
                                   points_list: List[int]) -> Tuple[float, float]:
        """计算加权平均R²和RMSE"""
        if not r2_list:
            return 0.0, 0.0
        total_pts = sum(points_list)
        weighted_r2 = sum(r2 * pts for r2, pts in zip(r2_list, points_list)) / total_pts
        weighted_rmse = sum(rmse * pts for rmse, pts in zip(rmse_list, points_list)) / total_pts
        return weighted_r2, weighted_rmse

    def _get_bounds(self, model_type: str) -> Tuple[List, List]:
        """获取参数边界（委托给 ModelType.get_bounds）"""
        return ModelType.get_bounds(model_type)

    def _global_optimize_full(self, y_full: np.ndarray, u_full: np.ndarray,
                               sv_full: np.ndarray, model_type: str,
                               initial_params: tuple) -> Optional[tuple]:
        """全量数据优化"""
        try:
            from ...fitting import ModelIdentifier
            
            oscillation_info = ModelIdentifier.detect_high_oscillation(y_full, u_full)
            
            if oscillation_info['is_oscillating']:
                filter_size = oscillation_info['recommended_filter_size']
                y_opt, u_opt = ModelIdentifier.preprocess_oscillating_data(y_full, u_full, filter_size)
                self.log(f"   检测到高振荡数据(振荡比={oscillation_info['oscillation_ratio']:.2f})，使用滤波预处理")
            else:
                y_opt, u_opt = y_full, u_full
            
            reset_points = [0]
            if sv_full is not None and len(sv_full) > 0:
                sv_diff = np.abs(np.diff(sv_full))
                sv_threshold = max(0.1, np.std(sv_full) * 0.5) if np.std(sv_full) > 0 else 0.1
                change_points = np.where(sv_diff > sv_threshold)[0] + 1
                reset_points.extend(change_points.tolist())
            
            MAX_SEGMENT = 500
            for start in range(0, len(y_full), MAX_SEGMENT):
                if start not in reset_points and start > 0:
                    reset_points.append(start)
            
            reset_points = sorted(set(reset_points))
            reset_points.append(len(y_full))
            
            pv_range = np.max(y_full) - np.min(y_full)
            mv_range = np.max(u_full) - np.min(u_full)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 0.5 else 0.5
            k_min = k_expected * 0.2
            k_max = k_expected * 3.0
            
            def objective(params):
                y_pred_all = np.zeros_like(y_opt)
                
                for i in range(len(reset_points) - 1):
                    start_idx = reset_points[i]
                    end_idx = reset_points[i + 1]
                    
                    if end_idx <= start_idx:
                        continue
                    
                    y0 = y_opt[start_idx]
                    t_seg = np.arange(end_idx - start_idx, dtype=float)
                    u_seg = u_opt[start_idx:end_idx]
                    
                    y_seg = self._simulator.simulate(tuple(params), model_type, t_seg, u_seg, y0)
                    y_pred_all[start_idx:end_idx] = y_seg
                
                y_std = np.std(y_opt)
                if y_std < self._epsilon:
                    y_std = 1.0
                
                residuals = (y_opt - y_pred_all) / y_std
                
                K = abs(params[0])
                if K < k_min or K > k_max:
                    k_penalty = min(abs(K - k_expected) / k_expected, 1.0) * 0.1
                    residuals = residuals * (1 + k_penalty)
                
                return residuals
            
            bounds = self._get_bounds(model_type)
            
            best_params = None
            best_cost = float('inf')
            
            init_points = [
                initial_params,
                self._simulator.create_init_params(model_type, k_expected, 5.0),
                self._simulator.create_init_params(model_type, k_expected * 0.7, 10.0),
                self._simulator.create_init_params(model_type, k_expected * 0.5, 15.0),
            ]
            
            corr = np.corrcoef(u_full, y_full)[0, 1] if len(u_full) > 2 else 0
            if not np.isnan(corr) and corr < -0.3:
                init_points.append(self._simulator.create_init_params(model_type, -k_expected, 5.0))
            
            for init_p in init_points:
                try:
                    result = least_squares(objective, init_p, bounds=bounds,
                                           method='trf', max_nfev=1000)
                    
                    if result.success and result.cost < best_cost:
                        y_pred_check = self._simulator.simulate_segmented(
                            tuple(result.x), model_type, y_full, u_full,
                            reset_on_sv_change=True, sv=sv_full,
                            enable_amplitude_calibration=False,
                            enable_offset_correction=False,
                            enable_smooth=False
                        )
                        pred_range = np.ptp(y_pred_check)
                        amplitude_ratio = pred_range / (pv_range + self._epsilon)
                        
                        amp_min = Config.OPTIMIZATION['amplitude_ratio_min']
                        amp_max = Config.OPTIMIZATION['amplitude_ratio_max']
                        if amp_min < amplitude_ratio < amp_max:
                            best_cost = result.cost
                            best_params = tuple(result.x)
                except Exception:
                    continue
            
            if best_params is not None:
                y_pred_final = self._simulator.simulate_segmented(
                    best_params, model_type, y_full, u_full,
                    reset_on_sv_change=True, sv=sv_full,
                    enable_amplitude_calibration=False,
                    enable_offset_correction=False,
                    enable_smooth=False
                )
                pred_range = np.ptp(y_pred_final)
                
                if pred_range > self._epsilon and pv_range > self._epsilon:
                    amplitude_ratio = pred_range / pv_range
                    if amplitude_ratio > 1.5 or amplitude_ratio < 0.5:
                        K_correction = pv_range / pred_range
                        best_params = list(best_params)
                        best_params[0] = best_params[0] * K_correction
                        best_params = tuple(best_params)
                        self.log(f"   K值校正: 幅度比={amplitude_ratio:.2f}, 校正因子={K_correction:.2f}")
            
            return best_params
            
        except Exception as e:
            self.log(f"   全量优化失败: {e}")
        
        return None

    def _validate_and_refine(self, fusion: FusionResult,
                              segments: List[HistoricalData],
                              hist_data: HistoricalData) -> FusionResult:
        """验证融合参数，必要时进行全局优化"""
        self.log(f"\\n{'='*60}")
        self.log("📊 Step 5: 验证与优化")
        self.log('='*60)
        
        model_type = fusion.model_type
        params = self._simulator.fusion_to_params(fusion)
        
        if abs(fusion.K) < self._epsilon or fusion.T1 < self._epsilon:
            self.log("   ⚠️ 参数无效(K或T1为0)")
            fusion.global_r2 = 0.0
            fusion.global_rmse = 0.0
            return fusion
        
        valid_mask = hist_data.pv != 0
        y_full = hist_data.pv[valid_mask]
        u_full = hist_data.mv[valid_mask]
        sv_full = hist_data.sv[valid_mask] if hist_data.sv is not None else None
        
        y_pred_full = self._simulator.simulate_segmented(
            params, model_type, y_full, u_full, 
            reset_on_sv_change=True, sv=sv_full,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=False
        )
        global_r2 = calculate_r2(y_full, y_pred_full)
        global_rmse = calculate_rmse(y_full, y_pred_full)
        
        self.log(f"   全量数据R²: {global_r2:.4f}, RMSE: {global_rmse:.4f}")
        
        segment_r2s_pure, segment_rmses, segment_points = self._compute_segment_metrics(
            segments, params, model_type, enhanced=False
        )
        segment_r2s_enhanced, _, _ = self._compute_segment_metrics(
            segments, params, model_type, enhanced=True
        )
        
        weighted_r2, weighted_rmse = self._compute_weighted_metrics(
            segment_r2s_pure, segment_rmses, segment_points
        )
        weighted_r2_enhanced, _ = self._compute_weighted_metrics(
            segment_r2s_enhanced, segment_rmses, segment_points
        )
        
        segment_r2s = segment_r2s_pure
        
        if segment_r2s:
            self.log(f"   扰动段R²(纯模型): {[f'{r:.3f}' for r in segment_r2s_pure]}, 加权R²: {weighted_r2:.4f}")
            if any(r2_e > r2_p + 0.1 for r2_e, r2_p in zip(segment_r2s_enhanced, segment_r2s_pure)):
                self.log(f"   扰动段R²(增强后): {[f'{r:.3f}' for r in segment_r2s_enhanced]}, 加权R²: {weighted_r2_enhanced:.4f}")
        
        opt_config = Config.OPTIMIZATION
        r2_threshold = opt_config['r2_threshold']
        min_seg_r2_threshold = opt_config['min_segment_r2']
        seg_r2_std_max = opt_config['segment_r2_std_max']
        
        min_segment_r2 = min(segment_r2s) if segment_r2s else 0
        segment_r2_std = np.std(segment_r2s) if len(segment_r2s) > 1 else 0
        
        need_optimization = (
            global_r2 < r2_threshold or
            min_segment_r2 < min_seg_r2_threshold or
            segment_r2_std > seg_r2_std_max
        )
        
        if need_optimization:
            self.log(f"   → R²<{r2_threshold}，尝试全量数据优化...")
            optimized_params = self._global_optimize_full(y_full, u_full, sv_full, model_type, params)
            
            if optimized_params is not None:
                y_pred_opt = self._simulator.simulate_segmented(
                    optimized_params, model_type, y_full, u_full,
                    reset_on_sv_change=True, sv=sv_full,
                    enable_smooth=True,
                    enable_amplitude_calibration=True,
                    enable_offset_correction=True,
                    enable_oscillation_overlay=False
                )
                r2_opt = calculate_r2(y_full, y_pred_opt)
                rmse_opt = calculate_rmse(y_full, y_pred_opt)
                
                self.log(f"   优化后全量R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                K_original = params[0]
                K_optimized = optimized_params[0]
                k_reasonable = True
                
                k_min = Config.PARAMETER_CONSTRAINTS['k_reasonable_min']
                k_ratio_max = opt_config['k_magnitude_ratio_max']
                
                if abs(K_original) > k_min:
                    if opt_config['k_sign_check'] and K_original * K_optimized < 0:
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值符号反转({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) < abs(K_original) / k_ratio_max:
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过小({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) > abs(K_original) * k_ratio_max:
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过大({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                
                if r2_opt > global_r2 and k_reasonable:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._simulator.params_to_fusion(optimized_params, model_type, fusion)
                    
                    param_constraints = Config.PARAMETER_CONSTRAINTS
                    if fusion.T1 > param_constraints['T1_max']:
                        fusion.T1 = param_constraints['T1_max']
                    if fusion.L > param_constraints['L_max']:
                        fusion.L = param_constraints['L_max']
                    
                    fusion.fusion_method += " + 全量优化"
                    self.log(f"   → 采用优化结果")
        
        if segment_r2s:
            current_params = self._simulator.fusion_to_params(fusion)
            new_segment_r2s, new_segment_rmses, new_segment_points = self._compute_segment_metrics(
                segments, current_params, model_type, enhanced=False
            )
            if new_segment_r2s:
                weighted_r2, weighted_rmse = self._compute_weighted_metrics(
                    new_segment_r2s, new_segment_rmses, new_segment_points
                )
        
        fusion.global_r2 = weighted_r2 if segment_r2s else global_r2
        fusion.global_rmse = weighted_rmse if segment_r2s else global_rmse
        fusion.full_data_r2 = global_r2
        
        eval_r2 = fusion.global_r2
        if eval_r2 >= 0.9:
            quality = "优秀"
        elif eval_r2 >= 0.7:
            quality = "良好"
        elif eval_r2 >= 0.5:
            quality = "一般"
        else:
            quality = "较差"
        
        self.log(f"\\n   最终评估: 扰动段R²={eval_r2:.4f} ({quality}), 全量R²={global_r2:.4f}")
        
        if eval_r2 < 0.5:
            self.log(f"\\n   ⚠️ 模型拟合质量较差，可能原因：")
            if min_segment_r2 < 0.1:
                self.log(f"      - 扰动段数据不符合阶跃响应特征")
            if segment_r2_std > 0.3:
                self.log(f"      - 各段响应特性差异大，可能存在非线性")
            self.log(f"   💡 建议：")
            self.log(f"      - 确认数据来自开环阶跃测试")
            self.log(f"      - 检查是否存在多个扰动叠加")
            self.log(f"      - 考虑使用更长的稳定响应数据")
        
        return fusion

    def _build_method_selector_output(self, context: TuningContext, method_result, fusion_result: FusionResult,
                                       hist_data: HistoricalData, time_range: Dict,
                                       tuning_windows: List, segments: List,
                                       segment_results: List) -> Dict[str, Any]:
        """构建方法选择器的输出结果 (继电反馈法采用时)"""
        pid_params = method_result.pid_params
        model_params = method_result.model_params or {
            'K': fusion_result.K, 'T1': fusion_result.T1,
            'T2': fusion_result.T2, 'L': fusion_result.L
        }
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = np.array(hist_data.timestamp[valid_mask], dtype=np.int64)
        sv = hist_data.sv[valid_mask]
        
        params = (model_params.get('K', 1.0), model_params.get('T1', 10.0), model_params.get('L', 1.0))
        pv_model = self._simulator.simulate_segmented(
            params, 'FOPDT', y, u, reset_on_sv_change=True, sv=sv,
            enable_smooth=True, enable_amplitude_calibration=True,
            enable_offset_correction=True, enable_oscillation_overlay=True
        )
        
        r2 = calculate_r2(y, pv_model)
        rmse = calculate_rmse(y, pv_model)
        
        temp_fusion = FusionResult(
            model_type=ModelType.FOPDT,
            K=model_params.get('K', 1.0),
            T1=model_params.get('T1', 10.0),
            T2=model_params.get('T2', 0.0),
            L=model_params.get('L', 1.0),
            global_r2=r2, global_rmse=rmse
        )
        
        sv_mean = float(np.mean(sv))
        pv_std = float(np.std(y))
        sp_initial = sv_mean
        sp_final = sv_mean + max(pv_std * 2, 1.0)
        pv_initial = float(np.mean(y))
        
        process_ctx = context.process_context or {}
        loop_type = process_ctx.get('loop_type', '')
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            temp_fusion, pid_params,
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            loop_type=loop_type, verbose=self._verbose
        )
        
        from ...rating import ModelRating
        
        perf_score, perf_details = ModelRating.performance_score(cl_metrics)
        
        margins = method_result.stability_margins
        closed_loop_info = {
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
            'gain_margin': margins.gain_margin if margins else 0,
            'gain_margin_db': margins.gain_margin_db if margins else 0,
            'phase_margin': margins.phase_margin if margins else 0,
        }
        
        gm = margins.gain_margin if margins else 1.0
        pm = margins.phase_margin if margins else 0.0
        method_confidence, confidence_details = ModelRating.relay_confidence(
            data_confidence=method_result.confidence,
            gain_margin=gm, phase_margin=pm
        )
        
        model_rating, final_details = ModelRating.final_rating(perf_score, method_confidence)
        
        tuning_features = {
            'tuning_method': 'relay_feedback',
            'Ku': (method_result.critical_params or {}).get('Ku', 0),
            'Pu': (method_result.critical_params or {}).get('Pu', 0),
            'gain_margin': margins.gain_margin if margins else 0,
            'phase_margin': margins.phase_margin if margins else 0,
            'K': round(model_params.get('K', 0), 4),
            'T1': round(model_params.get('T1', 0), 4),
            'L': round(model_params.get('L', 0), 4),
            'r_squared': round(r2, 4),
            'method': method_result.method.value,
            'confidence': method_result.confidence,
            'loop_type': loop_type,
        }
        
        return {
            'success': True,
            'model_type': 'FOPDT',
            'model_rating': model_rating,
            'method_confidence': method_confidence,
            'method_confidence_details': confidence_details,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {
                'K': round(model_params.get('K', 0), 4),
                'T1': round(model_params.get('T1', 0), 4),
                'T2': round(model_params.get('T2', 0), 4),
                'L': round(model_params.get('L', 0), 4)
            },
            'pid_parameters': pid_params,
            'fitting_result': {
                'timestamp': ts.tolist(),
                'sv': sv.tolist(),
                'pv': y.tolist(),
                'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': round(r2, 4),
                'rmse': round(rmse, 4)
            },
            'fusion_info': {
                'method': method_result.method.value,
                'n_segments': len(segments) if segments else 0,
                'consistency_score': method_result.confidence,
                'tuning_method': method_result.method.value,
                'critical_params': method_result.critical_params
            },
            'closed_loop_verification': closed_loop_info,
            'rating_details': {
                'performance_score': perf_score,
                'method_confidence': method_confidence,
                'method_confidence_details': confidence_details,
                'final_rating': model_rating,
                'final_details': final_details,
                'method': method_result.method.value,
                'reasoning': method_result.reasoning,
                'warnings': method_result.warnings,
            },
            'tuning_features': tuning_features,
            'segment_info': build_segment_info(segments, segment_results) if segments else []
        }

    def execute(self, context: TuningContext) -> TuningContext:
        if context.is_fallback_triggered or context.final_result is not None:
            return context

        # 1. 验证一致性与仿真匹配度
        fusion_result = self._validate_and_refine(
            context.fusion_result, context.segments_for_fitting, context.hist_data
        )

        # 2. 恢复闭环修正值
        if context.corrected_T1 is not None:
            if abs(fusion_result.T1 - context.corrected_T1) > 0.01:
                self.log(f"   ⚠️ Step 5优化改变了闭环修正值 (T1: {context.corrected_T1:.2f} → {fusion_result.T1:.2f})")
                self.log(f"   → 恢复闭环修正 T1={context.corrected_T1:.2f}s, K={context.corrected_K:.4f}")
                fusion_result.T1 = context.corrected_T1
                fusion_result.K = context.corrected_K

        # 把改动放回 context
        context.fusion_result = fusion_result

        # 3. 检查融合参数是否有效 (K或T1不能为0)
        if abs(fusion_result.K) < self._epsilon or fusion_result.T1 < self._epsilon:
            self.log("\\n   ⚠️ 参数融合失败（K或T1为0），尝试振荡整定fallback...")
            fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                context.segments_for_fitting, context.segment_results_fitted, context.current_pid, force=True
            )
            if fallback_result is not None:
                self.log("   ✅ 振荡整定fallback成功")
                context.final_result = self._oscillation_tuner.build_oscillation_output(
                    fallback_result, context.hist_data, context.time_range, context.input_data.tuning_window,
                    context.original_segments, context.original_results
                )
            else:
                self.log("   ❌ 振荡整定fallback也失败")
                context.is_fallback_triggered = True
            return context

        # 4. 使用方法选择器验证稳定性，必要时使用继电反馈法(Relay Feedback)
        model_params = {
            'K': fusion_result.K, 'T1': fusion_result.T1,
            'T2': fusion_result.T2, 'L': fusion_result.L
        }
        method_result = self._method_selector.select_and_tune(
            context.segments_for_fitting, context.segment_results_fitted,
            model_params=model_params, lambda_factor=context.lambda_factor,
            loop_type=context.loop_type
        )
        
        # 继电反馈法胜利条件判断
        use_relay = False
        if (method_result.method == TuningMethod.RELAY_FEEDBACK and 
            method_result.stability_margins and 
            method_result.stability_margins.is_stable):
            
            relay_pm = method_result.stability_margins.phase_margin
            relay_gm = method_result.stability_margins.gain_margin
            Pu_relay = (method_result.critical_params or {}).get('Pu', 0)
            
            if Pu_relay >= 500:
                self.log(f"\\n   ⚠️ 继电反馈法 Pu={Pu_relay:.1f}s 触达上限，放弃使用")
            else:
                from ...tuning.verification.stability_analyzer import StabilityAnalyzer
                model_pid = self._pid_calculator.calculate_from_fusion(fusion_result, context.lambda_factor)
                model_margins = StabilityAnalyzer.check_stability(model_params, model_pid)
                model_pm = model_margins.phase_margin if model_margins else 0
                model_gm = model_margins.gain_margin if model_margins else 0
                
                pm_advantage = relay_pm - model_pm
                gm_ok = (model_gm < 0.01) or (relay_gm >= model_gm * 0.5)
                
                if pm_advantage >= 10 and gm_ok:
                    use_relay = True
                    self.log(f"\\n🎯 继电反馈法显著更优 (PM={relay_pm:.1f}° vs {model_pm:.1f}°, "
                            f"GM={relay_gm:.2f} vs {model_gm:.2f})，使用继电反馈法参数")
                else:
                    self.log(f"\\n   继电反馈法未显著优于模型辨识法 "
                            f"(PM差={pm_advantage:.1f}°, GM比={relay_gm:.2f}/{model_gm:.2f})，使用模型辨识法")

        if use_relay:
            # 继电反馈法胜出：走 _build_method_selector_output 结束整个流程
            context.final_result = self._build_method_selector_output(
                context, method_result, fusion_result, context.hist_data, context.time_range,
                context.input_data.tuning_window, context.original_segments, context.original_results
            )
            
        return context
