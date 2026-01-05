"""
输出构建模块 (Output Builder Module)
====================================

本模块负责构建最终的整定结果输出。

核心功能
--------
1. **常规整定输出**: 基于模型辨识结果构建完整输出
2. **振荡整定输出**: 基于振荡临界法构建输出
3. **空结果生成**: 当辨识失败时生成默认输出
4. **闭环验证**: 对PID参数进行闭环稳定性验证
5. **评分计算**: 计算模型综合评分 (model_rating)
6. **段信息构建**: 构建段信息用于可视化（统一方法）

输出结构
--------
- success: 是否成功
- model_type: 模型类型
- model_rating: 综合评分 (0-10)
- model_parameters: 模型参数 {K, T1, T2, L}
- pid_parameters: PID参数 {Kp, Ki, Kd}
- fitting_result: 拟合结果 {timestamp, sv, pv, mv, pv_model, r_squared, rmse}
- fusion_info: 融合信息
- closed_loop_verification: 闭环验证结果
- rating_details: 评分详情
- segment_info: 段信息（用于可视化）
"""

import numpy as np
from typing import List, Dict, Any, Optional

from .config import Config, ModelType
from .data_models import FusionResult, HistoricalData, TuningInput
from .logger import LoggerMixin
from .utils import calculate_r2, calculate_rmse


class OutputBuilder(LoggerMixin):
    """
    输出构建器 - 构建最终整定结果
    
    职责：
    1. 构建常规整定输出
    2. 构建振荡整定输出
    3. 生成空结果
    4. 构建段信息（统一方法）
    """
    
    def __init__(self, simulator, pid_calculator, verbose: bool = False):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._simulator = simulator
        self._pid_calculator = pid_calculator
    
    @staticmethod
    def build_segment_info(segments: List, segment_results: List) -> List[Dict]:
        """
        构建段信息用于可视化（统一方法）
        
        Args:
            segments: 段数据列表 (HistoricalData)
            segment_results: 段结果列表 (SegmentResult)
            
        Returns:
            段信息列表
        """
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
                
                # 判断段类型：阶跃特征好且振荡低 → 整定段
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
    
    @staticmethod
    def create_empty_result(input_data: Optional[TuningInput] = None,
                            model_type: str = None) -> Dict[str, Any]:
        """
        创建空结果（统一方法）
        
        Args:
            input_data: 整定输入（可选）
            model_type: 模型类型（可选）
            
        Returns:
            空结果字典
        """
        return {
            'success': False,
            'model_type': model_type or ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': getattr(input_data, 'start_time', None) if input_data else None,
            'end_time': getattr(input_data, 'end_time', None) if input_data else None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            },
            'fusion_info': {
                'method': 'none',
                'n_segments': 0,
                'consistency_score': 0.0
            },
            'rating_details': {
                'r2_score': 0.0,
                'consistency_score': 0.0,
                'validity_score': 0.0,
                'coverage_score': 0.0,
                'n_segments': 0,
                'total_data_points': 0
            },
            'segment_info': []
        }
    
    def build_output(self, fusion: FusionResult, hist_data: HistoricalData,
                     time_range: Dict, lambda_factor: float,
                     tuning_windows: List[Dict] = None) -> Dict[str, Any]:
        """构建最终输出"""
        pid_params = self._pid_calculator.calculate_from_fusion(fusion, lambda_factor)
        
        params = self._simulator.fusion_to_params(fusion)
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = np.array(hist_data.timestamp[valid_mask], dtype=np.int64)  # 确保是 int64 类型
        sv = hist_data.sv[valid_mask]
        
        # 构建扰动段掩码
        disturbance_mask = np.zeros(len(ts), dtype=bool)
        if tuning_windows:
            for window in tuning_windows:
                if hasattr(window, 'start_time'):
                    start_ts = int(window.start_time)
                    end_ts = int(window.end_time)
                else:
                    start_ts = int(window.get('start_time', 0))
                    end_ts = int(window.get('end_time', 0))
                disturbance_mask |= (ts >= start_ts) & (ts <= end_ts)
        
        # 对全量数据进行模型仿真
        pv_model_full = self._simulator.simulate_segmented(
            params, fusion.model_type, y, u, 
            reset_on_sv_change=True, sv=sv,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=True
        )
        
        # pv_model: 扰动段用模型拟合，稳态段用实际PV
        pv_model = y.copy()
        pv_model[disturbance_mask] = pv_model_full[disturbance_mask]
        
        sim_r2 = calculate_r2(y, pv_model)
        
        pv_diff = np.diff(y)
        sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
        oscillation_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
        
        pv_range = np.ptp(y)
        model_range = np.ptp(pv_model)
        amplitude_ratio = model_range / (pv_range + self._epsilon) if pv_range > 0.1 else 1.0
        
        self.log(f"   pv_model检查: sim_R²={sim_r2:.3f}, 振荡={oscillation_ratio:.2f}, "
                f"PV范围={pv_range:.2f}, 模型范围={model_range:.2f}, 幅度比={amplitude_ratio:.2f}")
        
        sim_quality_poor = (
            sim_r2 < 0.5 or
            fusion.global_r2 < 0.3 or
            oscillation_ratio > 0.4 or
            amplitude_ratio < 0.5 or amplitude_ratio > 2.0
        )
        
        fitting_failed = (
            fusion.n_segments_used == 0 or
            sim_r2 < 0.1 or
            amplitude_ratio < 0.3 or amplitude_ratio > 3.0
        )
        
        if fitting_failed:
            self.log(f"   ❌ 拟合完全失败，保留原始pv_model用于诊断分析")
        elif sim_quality_poor:
            reason = []
            if sim_r2 < 0.5:
                reason.append(f"R²={sim_r2:.3f}")
            if oscillation_ratio > 0.4:
                reason.append(f"振荡={oscillation_ratio:.2f}")
            if amplitude_ratio < 0.5 or amplitude_ratio > 2.0:
                reason.append(f"幅度比={amplitude_ratio:.2f}")
            self.log(f"   ⚠️ 模型仿真质量较差({', '.join(reason)})")
        
        total_data_points = int(np.sum(valid_mask))
        
        # 闭环稳定性验证
        sp_initial = float(sv[0]) if len(sv) > 0 else 50.0
        sp_final = float(sv[-1]) if len(sv) > 0 else 60.0
        pv_initial = float(y[0]) if len(y) > 0 else sp_initial
        
        sp_change = abs(sp_final - sp_initial)
        pv_sp_diff = abs(pv_initial - sp_initial)
        
        if sp_change < 5.0 or pv_sp_diff > sp_change * 2:
            sp_initial = 50.0
            sp_final = 60.0
            pv_initial = 50.0
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            fusion, pid_params, 
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            verbose=self._verbose
        )
        
        # 计算 model_rating
        model_rating, score_details = self._pid_calculator.calculate_model_rating(
            fusion, total_data_points, cl_metrics=cl_metrics, verbose=self._verbose
        )
        
        if self._verbose:
            self.log(f"\n   📊 评分详情:")
            self.log(f"      拟合质量 (R²={fusion.global_r2:.3f}): {score_details.get('r2_score', 0):.1f}/10 × 30%")
            self.log(f"      参数一致性: {score_details.get('consistency_score', 0):.1f}/10 × 20%")
            self.log(f"      参数合理性: {score_details.get('validity_score', 0):.1f}/10 × 15%")
            self.log(f"      数据覆盖度 ({fusion.n_segments_used}段/{total_data_points}点): {score_details.get('coverage_score', 0):.1f}/10 × 10%")
            self.log(f"      闭环稳定性: {score_details.get('stability_score', 0):.1f}/10 × 25%")
            self.log(f"      → 综合评分: {model_rating}/10")
        
        closed_loop_info = {
            'is_stable': is_stable,
            'settling_time': cl_metrics.settling_time if cl_metrics.settling_time < float('inf') else -1,
            'overshoot': cl_metrics.overshoot,
            'rise_time': cl_metrics.rise_time if cl_metrics.rise_time < float('inf') else -1,
            'steady_state_error': cl_metrics.steady_state_error,
            'oscillation_count': cl_metrics.oscillation_count,
            'decay_ratio': cl_metrics.decay_ratio
        }
        
        return {
            'success': not fitting_failed,
            'model_type': fusion.model_type,
            'model_rating': model_rating,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {
                'K': round(fusion.K, 4),
                'T1': round(fusion.T1, 4),
                'T2': round(fusion.T2, 4),
                'L': round(fusion.L, 4)
            },
            'pid_parameters': pid_params,
            'fitting_result': {
                'timestamp': ts.tolist(),
                'sv': sv.tolist(),
                'pv': y.tolist(),
                'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': round(fusion.global_r2, 4),
                'rmse': round(fusion.global_rmse, 4)
            },
            'fusion_info': {
                'method': fusion.fusion_method,
                'n_segments': fusion.n_segments_used,
                'consistency_score': round(fusion.consistency_score, 4),
                'K_std': round(fusion.K_std, 4),
                'T1_std': round(fusion.T1_std, 4)
            },
            'closed_loop_verification': closed_loop_info,
            'rating_details': score_details
        }
    
    def empty_result(self, input_data: Optional[TuningInput] = None) -> Dict[str, Any]:
        """空结果"""
        return {
            'success': False,
            'model_type': ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': getattr(input_data, 'start_time', None) if input_data else None,
            'end_time': getattr(input_data, 'end_time', None) if input_data else None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            },
            'fusion_info': {
                'method': 'none',
                'n_segments': 0,
                'consistency_score': 0.0
            },
            'rating_details': {
                'r2_score': 0.0,
                'consistency_score': 0.0,
                'validity_score': 0.0,
                'coverage_score': 0.0,
                'n_segments': 0,
                'total_data_points': 0
            }
        }
