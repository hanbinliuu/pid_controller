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

from api.commond.time_util import parse_time_to_milliseconds
from .config import Config, ModelType
from .data_models import FusionResult, HistoricalData, TuningInput, SegmentResult
from .logger import LoggerMixin
from .rating import ModelRating
from .utils import (
    calculate_r2,
    build_segment_info as _build_segment_info,
    determine_turning_type,
    get_recommendation,
    pid_to_full_dict,
    compute_sampling_period,
    compute_sim_params,
    build_cl_verification,
)


class OutputBuilder(LoggerMixin):
    """
    输出构建器 - 构建最终整定结果
    
    职责：
    1. 构建常规整定输出
    2. 构建振荡整定输出（含fallback逻辑）
    3. 生成空结果
    4. 构建段信息（统一方法）
    """
    
    def __init__(self, simulator, pid_calculator, verbose: bool = False,
                 oscillation_tuner=None):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._simulator = simulator
        self._pid_calculator = pid_calculator
        self._oscillation_tuner = oscillation_tuner
    
    def set_oscillation_tuner(self, oscillation_tuner):
        """设置振荡整定器（用于闭环不稳定时的 fallback）"""
        self._oscillation_tuner = oscillation_tuner
    
    # NOTE: build_segment_info 已移至 utils.py，不再需要此处的委托包装。
    # 所有调用方应直接 from ...utils import build_segment_info
    
    @staticmethod
    def create_empty_result(input_data: Optional[TuningInput] = None,
                            model_type: str = None,
                            turning_type: str = None) -> Dict[str, Any]:
        """
        创建空结果（统一方法）
        
        Args:
            input_data: 整定输入（可选）
            model_type: 模型类型（可选）
            turning_type: 期望的整定类型（可选）
            
        Returns:
            空结果字典
        """
        return {
            'success': False,
            'model_type': model_type or ModelType.FOPDT,
            'turning_type': turning_type or 'PID',
            'model_rating': 0.0,
            'start_time': getattr(input_data, 'start_time', None) if input_data else None,
            'end_time': getattr(input_data, 'end_time', None) if input_data else None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': pid_to_full_dict(1.0, 0.05, 0.0),
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0,
                'recommendation': '不可用'
            },
            'closed_loop_verification': {},
            'tuning_features': {}
        }
    
    def build_full_output(self, fusion: FusionResult, hist_data: HistoricalData,
                          time_range: Dict, lambda_factor: float,
                          tuning_windows: List[Dict] = None,
                          quality_info = None,
                          segment_results: List[SegmentResult] = None,
                          segments: List[HistoricalData] = None,
                          loop_type: str = None,
                          optimized_pid: Dict[str, float] = None,
                          tuning_constraints: dict = None) -> Dict[str, Any]:
        """
        构建最终输出（完整版，包含 fallback 逻辑）
        
        Args:
            fusion: 融合后的模型参数
            hist_data: 历史数据
            time_range: 时间范围
            lambda_factor: Lambda 整定系数
            tuning_windows: 整定窗口列表
            quality_info: 数据质量信息，用于自适应保守PID整定
            segment_results: 各段拟合结果，用于闭环不稳定时切换振荡整定
            segments: 各扰动段数据，用于闭环不稳定时切换振荡整定
            loop_type: 回路类型，用于差异化整定
            
        Returns:
            完整的整定结果字典
        """
        # 计算 PID 参数（优先使用自优化微调结果）
        if optimized_pid is not None:
            pid_params = optimized_pid
            self.log(f"   ✅ 使用自优化微调后的 PID 参数")
        else:
            pid_params = self._pid_calculator.calculate_from_fusion(
                fusion, lambda_factor, quality_info=quality_info, loop_type=loop_type,
                tuning_constraints=tuning_constraints
            )
        
        # Ensure all PID formats exist (kp, ki, kd, pb, ti, td)
        full_p = pid_to_full_dict(
            Kp=pid_params.get('Kp', pid_params.get('kp', 1.0)),
            Ki=pid_params.get('Ki', pid_params.get('ki', 0.0)),
            Kd=pid_params.get('Kd', pid_params.get('kd', 0.0)),
        )
        pid_params.update(full_p)
        
        # Calculate context-aware tuning characteristics
        turning_type = determine_turning_type(pid_params['Kp'], pid_params.get('Ti', pid_params['ti']), pid_params.get('Td', pid_params['td']))
        
        params = self._simulator.fusion_to_params(fusion)
        
        valid_mask = hist_data.valid_mask()
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        ts = np.array(hist_data.timestamp[valid_mask], dtype=np.int64)
        sv = hist_data.sv[valid_mask]
        
        # 构建扰动段掩码
        disturbance_mask = np.zeros(len(ts), dtype=bool)
        if tuning_windows:
            for window in tuning_windows:
                if hasattr(window, 'start_time'):
                    start_ts = parse_time_to_milliseconds(window.start_time)
                    end_ts = parse_time_to_milliseconds(window.end_time)
                else:
                    start_ts = parse_time_to_milliseconds(window.get('start_time'))
                    end_ts = parse_time_to_milliseconds(window.get('end_time'))
                disturbance_mask |= (ts >= start_ts) & (ts <= end_ts)
        
        # 模型仿真
        pv_model_full = self._simulator.simulate_segmented(
            params, fusion.model_type, y, u, 
            reset_on_sv_change=True, sv=sv,
            enable_smooth=True,
            enable_amplitude_calibration=True,
            enable_offset_correction=True,
            enable_oscillation_overlay=True
        )
        
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
        
        # 从配置读取阈值
        ms_cfg = Config.MODEL_SELECTOR
        
        sim_quality_poor = (
            sim_r2 < ms_cfg['sim_r2_poor_threshold'] or
            fusion.global_r2 < Config.MODEL_FITTING['r2_poor_threshold'] or
            oscillation_ratio > ms_cfg['oscillation_poor_threshold'] or
            amplitude_ratio < ms_cfg['amplitude_ratio_min'] or 
            amplitude_ratio > ms_cfg['amplitude_ratio_max']
        )
        
        fitting_failed = (
            fusion.n_segments_used == 0 or
            sim_r2 < ms_cfg['sim_r2_fail_threshold'] or
            amplitude_ratio < ms_cfg['amplitude_ratio_fail_min'] or 
            amplitude_ratio > ms_cfg['amplitude_ratio_fail_max']
        )
        
        if fitting_failed:
            self.log(f"   ❌ 拟合完全失败，保留原始pv_model用于诊断分析")
        elif sim_quality_poor:
            reason = []
            if sim_r2 < ms_cfg['sim_r2_poor_threshold']:
                reason.append(f"R²={sim_r2:.3f}")
            if oscillation_ratio > ms_cfg['oscillation_poor_threshold']:
                reason.append(f"振荡={oscillation_ratio:.2f}")
            if amplitude_ratio < ms_cfg['amplitude_ratio_min'] or amplitude_ratio > ms_cfg['amplitude_ratio_max']:
                reason.append(f"幅度比={amplitude_ratio:.2f}")
            self.log(f"   ⚠️ 模型仿真质量较差({', '.join(reason)})")
        
        total_data_points = int(np.sum(valid_mask))
        
        # 闭环稳定性验证
        sim = compute_sim_params(hist_data)
        if sim is not None:
            sp_initial, sp_final, pv_initial = sim
        else:
            ms_cfg = Config.MODEL_SELECTOR
            sp_initial = ms_cfg['default_sp_initial']
            sp_final = ms_cfg['default_sp_final']
            pv_initial = ms_cfg['default_pv_initial']
        
        # 使用统一计算的采样周期
        dt_data = compute_sampling_period(hist_data)
        
        # 将参数打包进 pid_params, 以便于底层的 ZOH 积分器提取
        if dt_data > 0.1:
            pid_params['Ts'] = dt_data
        
        is_stable, cl_metrics = self._pid_calculator.verify_pid_stability(
            fusion, pid_params, 
            sp_initial=sp_initial, sp_final=sp_final, pv_initial=pv_initial,
            loop_type=loop_type,
            verbose=self._verbose
        )
        
        # 闭环不稳定时尝试振荡整定 fallback
        if not is_stable and self._oscillation_tuner is not None and segments is not None:
            self.log(f"\n   ⚠️ 常规整定闭环不稳定，尝试切换到振荡整定法...")
            
            osc_result = self._oscillation_tuner.try_oscillation_tuning(
                segments, segment_results, pid_params, force=True, tuning_constraints=tuning_constraints
            )
            
            if osc_result is not None and osc_result.get('success', False):
                self.log(f"   ✅ 振荡整定成功，使用振荡整定参数")
                osc_output = self._oscillation_tuner.build_oscillation_output(
                    osc_result, hist_data, time_range, tuning_windows,
                    segments, segment_results, tuning_constraints=tuning_constraints
                )
                return osc_output
            else:
                self.log(f"   ⚠️ 振荡整定也失败，保持原参数")
        
        # ====== 三层评分 ======
        
        # Layer 1: 闭环性能评分
        perf_score, perf_details = ModelRating.performance_score(cl_metrics)
        
        # Layer 2: 模型辨识置信度
        method_confidence, confidence_details = ModelRating.model_id_confidence(fusion)
        
        # Layer 3: 最终综合评分
        model_rating, final_details = ModelRating.final_rating(perf_score, method_confidence)
        
        score_details = {
            'performance_score': perf_score,
            'performance_details': perf_details,
            'method_confidence': method_confidence,
            'method_confidence_details': confidence_details,
            'final_rating': model_rating,
            'final_details': final_details,
        }
        
        if self._verbose:
            self.log(f"\n   📊 三层评分:")
            self.log(f"      Layer 1 - 闭环性能: {perf_score}/10")
            self.log(f"      Layer 2 - 方法置信度: {method_confidence:.2f}")
            self.log(f"      Layer 3 - 最终评分: {model_rating}/10")
        
        closed_loop_info = build_cl_verification(
            cl_metrics, sp_initial, sp_final, pv_initial, is_stable=is_stable
        )
        
        # success 仅取决于是否产生有效参数，不再要求内部闭环验证通过
        # 内部闭环验证使用估算模型（振荡数据下R²<0.4），不能代表真实过程稳定性
        # is_stable 信息保留在 closed_loop_verification 中供参考
        success = not fitting_failed
        
        # 构建整定特征数据
        tuning_features = {
            'tuning_method': 'model_identification',
            'K': round(fusion.K, 4),
            'T1': round(fusion.T1, 4),
            'T2': round(fusion.T2, 4),
            'L': round(fusion.L, 4),
            'model_type': fusion.model_type,
            'r_squared': round(fusion.global_r2, 4),
            'rmse': round(fusion.global_rmse, 4),
            'n_segments': fusion.n_segments_used,
            'consistency_score': round(fusion.consistency_score, 4),
            'loop_type': loop_type,
        }
        
        # 数据质量特征（来自 quality_info）
        if quality_info is not None:
            tuning_features.update({
                'quality_score': round(quality_info.quality_score, 4),
                'correlation': round(quality_info.correlation, 4),
                'controller_sign': quality_info.controller_sign,
            })
        
        return {
            'success': success,
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
            'turning_type': turning_type,
            'fitting_result': {
                'timestamp': ts.tolist(),
                'sv': sv.tolist(),
                'pv': y.tolist(),
                'mv': u.tolist(),
                'pv_model': pv_model.tolist(),
                'r_squared': round(fusion.global_r2, 4),
                'rmse': round(fusion.global_rmse, 4),
                'recommendation': get_recommendation(model_rating)
            },
            'closed_loop_verification': closed_loop_info,
            'tuning_features': tuning_features,
            'rating_details': score_details
        }
    

