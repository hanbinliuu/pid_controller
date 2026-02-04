import numpy as np
from typing import List, Dict, Any, Optional, Tuple, Union
from scipy.optimize import least_squares

from api.commond.time_util import parse_time_to_milliseconds
from .config import Config, ModelType
from .data_models import SegmentResult, FusionResult, TuningInput, HistoricalData
from .utils import (
    calculate_r2, calculate_rmse, calculate_rss, calculate_aic, calculate_bic,
    get_recommendation, determine_turning_type
)

# 子模块导入
from .preprocessing import DataPreprocessor, SegmentProcessor, SegmentManager
from .fitting import (
    ModelIdentifier, SegmentFitter, UnifiedModelSelector, SegmentModelFit, ParameterFusion
)
from .tuning import PIDCalculator, DataQualityInfo, OscillationTuner, TuningMethodSelector, StabilityAnalyzer
from .simulation import ModelSimulator

# 其他模块
from .output_builder import OutputBuilder
from .logger import LoggerMixin


class ModelSelector(LoggerMixin):
    """
    模型类型选择器
    
    核心流程：
    1. 剔除无效/扰动段 → 有效段筛选
    2. 对每个有效段尝试多种模型拟合 → 获取各段各模型的KTL
    3. 基于AIC/RSS/形状特征选择最优模型结构 → 确定模型类型
    4. 融合各段参数 → 唯一K, T, L（加权平均 / 全局优化）
    5. 验证一致性与仿真匹配度 → 最终输出
    
    LLM 增强:
    - 支持使用大模型决策保守策略
    - 通过构造函数或 set_llm_client() 启用
    """
    
    # 使用统一的常量定义（来自 ModelType）
    CANDIDATE_MODELS = ModelType.CANDIDATE_MODELS
    MODEL_PARAM_COUNT = ModelType.MODEL_PARAM_COUNT
    
    # 验证阈值常量 (从配置读取)
    MIN_R2_FOR_VOTE = Config.MODEL_SELECTOR['min_r2_for_vote']
    MIN_R2_FOR_QUALITY = Config.MODEL_SELECTOR['min_r2_for_quality']
    R2_THRESHOLDS = Config.MODEL_SELECTOR['r2_thresholds']
    
    def __init__(self, verbose: bool = False, llm_client=None, process_context: dict = None):
        """
        Args:
            verbose: 是否输出详细日志
            llm_client: LLM 客户端，用于决策保守策略
                       需实现 chat(prompt) -> str 方法
            process_context: 工艺上下文信息（可选）
                - loop_type: 回路类型 (flow/temperature/pressure/level)
                - loop_name: 回路名称
                - safety_critical: 是否安全关键
                - allow_overshoot: 是否允许超调
        """
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
        self._llm_client = llm_client
        self._process_context = process_context
        
        # 初始化子模块
        self._preprocessor = DataPreprocessor(verbose=verbose)
        self._segment_processor = SegmentProcessor(verbose=verbose)
        self._simulator = ModelSimulator()
        
        # PIDCalculator（正常整定用规则引擎，不需要 LLM）
        self._pid_calculator = PIDCalculator()
        
        self._unified_selector = UnifiedModelSelector(verbose=verbose)
        
        # 拆分后的子模块
        self._segment_fitter = SegmentFitter(
            self._simulator, self._preprocessor, self._pid_calculator, verbose
        )
        self._output_builder = OutputBuilder(
            self._simulator, self._pid_calculator, verbose
        )
        
        # 段管理器（从 model_selector 拆分出来）
        self._segment_manager = SegmentManager(self._preprocessor, verbose)
        
        # 参数融合器（从 model_selector 拆分出来）
        self._param_fusion = ParameterFusion(self._segment_processor, verbose)
        
        # OscillationTuner 支持 LLM 决策（临界法整定专用）
        loop_type = process_context.get('loop_type', '') if process_context else ''
        loop_name = process_context.get('loop_name', '') if process_context else ''
        self._oscillation_tuner = OscillationTuner(
            self._pid_calculator, self._simulator, verbose,
            llm_client=llm_client, loop_type=loop_type, loop_name=loop_name
        )
        
        # 设置 OutputBuilder 的 oscillation_tuner（用于 fallback）
        self._output_builder.set_oscillation_tuner(self._oscillation_tuner)
        
        # 整定方法选择器（自动选择模型辨识法/继电反馈法/混合方法）
        self._method_selector = TuningMethodSelector(
            self._pid_calculator, self._simulator, verbose
        )
    
    def set_llm_client(self, llm_client, process_context: dict = None):
        """
        设置 LLM 客户端，启用 LLM 决策保守策略
        
        注意：LLM 只在临界法整定时使用，正常数据质量好的整定不需要 LLM。
        
        Args:
            llm_client: LLM 客户端
            process_context: 工艺上下文信息
                - loop_type: 回路类型 (flow/temperature/pressure/level)
                - loop_name: 回路名称
                - safety_critical: 是否安全关键
        
        使用示例:
            selector = ModelSelector(verbose=True)
            selector.set_llm_client(
                llm_client=OllamaClient(model="qwen2.5:7b"),
                process_context={'loop_type': 'temperature', 'loop_name': '反应釜温度'}
            )
            result = selector.run(input_data)
        """
        self._llm_client = llm_client
        self._process_context = process_context
        
        # 更新 OscillationTuner（临界法整定专用）
        loop_type = process_context.get('loop_type', '') if process_context else ''
        loop_name = process_context.get('loop_name', '') if process_context else ''
        self._oscillation_tuner.set_llm_client(llm_client, loop_type, loop_name)
    
    @property
    def verbose(self) -> bool:
        return self._verbose
    
    # ============================================================
    # 主入口（新格式）
    # ============================================================
    
    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """模型整定主入口（新格式）
        
        Args:
            input_data: 输入数据字典
                - history_data: 历史数据列表
                - params: 参数配置
                - qualified_windows: 扰动窗口列表
                - current_pid: 当前 PID 参数（可选）
                - process_context: 工艺上下文（可选，会覆盖构造函数中的设置）
        """
        history_data = input_data.get('history_data', [])
        params = input_data.get('params', {})
        qualified_windows = input_data.get('qualified_windows', [])
        current_pid = input_data.get('current_pid', None)  # 当前 PID 参数
        
        if not history_data:
            return self._empty_result_new(params)
        
        if not qualified_windows:
            return self._empty_result_new(params)
        
        tuning_input = {
            'start_time': history_data[0].get('timestamp') if history_data else None,
            'end_time': history_data[-1].get('timestamp') if history_data else None,
            'tuning_window': [
                {'start_time': w.get('start_time'), 'end_time': w.get('end_time')}
                for w in qualified_windows
            ]
        }
        
        result = self.fit(tuning_input, history_data, lambda_factor=0.8, 
                          current_pid=current_pid)
        return self._convert_output_format(result, params)
    
    def _convert_output_format(self, result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """转换为新输出格式"""
        model_rating = result.get('model_rating', 0)
        recommendation = get_recommendation(model_rating)
        
        pid_params = result.get('pid_parameters', {})
        Kp = pid_params.get('Kp', 1.0)
        Ki = pid_params.get('Ki', 0.0)
        Kd = pid_params.get('Kd', 0.0)
        
        # 优先使用pid_params中已计算的Ti/Td（避免四舍五入误差）
        if 'Ti' in pid_params and pid_params['Ti'] > 0:
            Ti = pid_params['Ti']
        else:
            Ti = Kp / Ki if abs(Ki) > self._epsilon else 0.0
        
        if 'Td' in pid_params:
            Td = pid_params['Td']
        else:
            Td = Kd / Kp if abs(Kp) > self._epsilon else 0.0
        
        # 优先使用pid_params中已计算的pb（避免四舍五入误差）
        if 'pb' in pid_params and pid_params['pb'] > 0:
            Pb = pid_params['pb']
        else:
            Pb = 100.0 / abs(Kp) if abs(Kp) > self._epsilon else 100.0
        
        turning_type = params.get('turning_type') or determine_turning_type(Kp, Ti, Td)
        
        fitting_result = result.get('fitting_result', {})
        fitting_result['recommendation'] = recommendation
        
        # 构建新的 pid_parameters
        new_pid_params = {
            'pb': round(float(Pb), 2),
            'ti': round(float(Ti), 2),
            'td': round(float(Td), 2),
            'kp': round(float(Kp), 2),
            'ki': round(float(Ki), 2),
            'kd': round(float(Kd), 2)
        }
        
        # 输出最终 PID 参数（verbose 模式）
        self.log(f"\n{'='*60}")
        self.log(f"📋 最终整定参数输出:")
        self.log(f"   PB = {Pb:.2f}%")
        self.log(f"   TI = {Ti:.2f}s")
        self.log(f"   TD = {Td:.2f}s")
        self.log(f"   (Kp={Kp:.4f}, Ki={Ki:.4f}, Kd={Kd:.4f})")
        self.log(f"{'='*60}")
        
        return {
            'success': result.get('success', False),
            'model_type': result.get('model_type', 'FOPDT'),
            'turning_type': turning_type,
            'model_rating': model_rating,
            'start_time': result.get('start_time'),
            'end_time': result.get('end_time'),
            'model_parameters': result.get('model_parameters', {}),
            'pid_parameters': new_pid_params,
            'fitting_result': fitting_result,
            'fusion_info': result.get('fusion_info', {}),
            'closed_loop_verification': result.get('closed_loop_verification', {}),
            'rating_details': result.get('rating_details', {}),
            'segment_info': result.get('segment_info', [])
        }
    
    def _empty_result_new(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """新格式空结果"""
        return {
            'success': False,
            'model_type': params.get('model_type') or 'FOPDT',
            'turning_type': params.get('turning_type') or 'PID',
            'model_rating': 0.0,
            'start_time': None,
            'end_time': None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {
                'pb': 100.0, 'ti': 0.0, 'td': 0.0,
                'kp': 1.0, 'ki': 0.0, 'kd': 0.0
            },
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0,
                'recommendation': '不可用'
            }
        }
    
    # ============================================================
    # 原有入口（保持兼容）
    # ============================================================
    
    def fit(self, tuning_input: Union[Dict, TuningInput],
            raw_data: List[Dict],
            lambda_factor: float = None,
            current_pid: Dict = None,
            enable_downsample: bool = None,
            downsample_target: int = None) -> Dict[str, Any]:
        """模型整定主入口
        
        Args:
            tuning_input: 整定输入
            raw_data: 原始数据
            lambda_factor: Lambda整定系数
            current_pid: 当前PID参数 {'Kp': ..., 'Ki': ..., 'Kd': ...}，用于振荡分析
            enable_downsample: 是否启用智能降采样
            downsample_target: 降采样目标点数
        """
        # 使用配置默认值
        tuning_defaults = Config.TUNING_DEFAULTS
        if lambda_factor is None:
            lambda_factor = tuning_defaults['lambda_factor']
        if enable_downsample is None:
            enable_downsample = tuning_defaults['enable_downsample']
        if downsample_target is None:
            downsample_target = tuning_defaults['downsample_target']
        
        input_data = self._parse_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result(input_data)
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        self.log(f"📥 输入: {len(input_data.tuning_window)} 个扰动窗口, {len(raw_data)} 条数据")
        
        # Step 1: 检测扰动段（原有逻辑）
        segments = self._segment_processor.extract_segments(hist_data, input_data.tuning_window)
        disturbance_segs, disturbance_results = self._segment_processor.filter_invalid_segments(segments)
        
        if not disturbance_segs:
            self.log("⚠️ 无有效扰动段")
            return self._empty_result(input_data)
        
        self.log(f"📊 检测到 {len(disturbance_segs)} 个有效扰动段")
        
        # Step 1.5: 有扰动发生，尝试找整定段（基于MV阶跃变化）
        tuning_segs_mv, tuning_results_mv = self._segment_processor.detect_tuning_segments(hist_data)
        
        # Step 1.6: 决定使用哪种段进行整定
        if tuning_segs_mv:
            # 找到整定段：优先使用整定段，并尝试与扰动段合并时间窗口
            self.log(f"✅ 找到 {len(tuning_segs_mv)} 个整定段")
            valid_segments, segment_results = self._merge_tuning_and_disturbance(
                tuning_segs_mv, tuning_results_mv,
                disturbance_segs, disturbance_results,
                hist_data  # 传入原始数据用于重新提取合并段
            )
            use_tuning_segments = True
        else:
            # 没找到整定段：使用扰动段（原有逻辑）
            self.log(f"⚠️ 未找到整定段，使用 {len(disturbance_segs)} 个扰动段")
            valid_segments = disturbance_segs
            segment_results = disturbance_results
            use_tuning_segments = False
        
        # 保存原始段数据用于可视化（降采样前）
        # 使用深拷贝避免后续修改影响原始数据
        original_segments = [
            HistoricalData(
                timestamp=seg.timestamp.copy(),
                pv=seg.pv.copy(),
                sv=seg.sv.copy(),
                mv=seg.mv.copy()
            ) for seg in valid_segments
        ]
        original_results = [SegmentResult(
            segment_idx=r.segment_idx,
            start_idx=r.start_idx,
            end_idx=r.end_idx,
            data_points=r.data_points,
            is_valid=r.is_valid,
            invalid_reason=r.invalid_reason,
            quality_score=r.quality_score,
            nonlinearity_score=r.nonlinearity_score,
            step_response_score=r.step_response_score,
            oscillation_ratio=r.oscillation_ratio,
            is_nonlinear=r.is_nonlinear
        ) for r in segment_results]
        
        # Step 1.7: 智能降采样（加速整定）
        if enable_downsample and valid_segments:
            valid_segments = self._apply_smart_downsample(valid_segments, downsample_target)
        
        if not valid_segments:
            self.log("⚠️ 无有效段")
            return self._empty_result(input_data)
        
        # Step 1.8: 检查MV是否有变化（无变化无法辨识）
        mv_no_change = self._check_mv_no_change(valid_segments)
        if mv_no_change:
            self.log("❌ MV无变化，无法进行模型辨识")
            return self._empty_result(input_data)
        
        self.log(f"📊 最终有效段: {len(valid_segments)} 个")
        
        # Step 1.9: 分类段 - 区分整定段（阶跃特征好）和振荡段
        tuning_segs, tuning_results, osc_segs, osc_results = self._classify_and_prioritize_segments(
            valid_segments, segment_results
        )
        
        # 决定使用哪些段进行模型辨识
        if tuning_segs:
            # 有整定段：优先使用整定段进行模型辨识
            self.log(f"✅ 使用 {len(tuning_segs)} 个整定段进行模型辨识")
            segments_for_fitting = tuning_segs
            results_for_fitting = tuning_results
        else:
            # 没有整定段：检查是否应该使用原始扰动段
            # 如果 valid_segments 是短段（<100点）且有振荡，使用原始扰动段
            use_disturbance = False
            if osc_segs and len(osc_segs) > 0:
                # 检查振荡段是否太短
                total_osc_points = sum(len(seg.pv) for seg in osc_segs)
                if total_osc_points < 100 and disturbance_segs:
                    # 振荡段太短，使用原始扰动段
                    self.log(f"⚠️ 振荡段太短({total_osc_points}点)，使用原始扰动段({sum(len(s.pv) for s in disturbance_segs)}点)")
                    segments_for_fitting = disturbance_segs
                    results_for_fitting = disturbance_results
                    use_disturbance = True
            
            if not use_disturbance:
                self.log(f"⚠️ 无整定段，使用全部 {len(valid_segments)} 个段")
                segments_for_fitting = valid_segments
                results_for_fitting = segment_results
        
        # Step 1.95: 振荡预检 - 在模型拟合前过滤高振荡段
        fitting_segs, fitting_results, precheck_osc_segs, precheck_osc_results = \
            self._precheck_oscillation(segments_for_fitting, results_for_fitting)
        
        # 如果全部是高振荡段，直接走振荡整定
        if not fitting_segs:
            self.log("⚠️ 所有段均为高振荡，直接启用振荡整定")
            oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
                segments_for_fitting, results_for_fitting, current_pid, force=True
            )
            if oscillation_result is not None:
                return self._oscillation_tuner.build_oscillation_output(
                    oscillation_result, hist_data, time_range, input_data.tuning_window,
                    original_segments, original_results
                )
            return self._empty_result(input_data)
        
        # Step 2: 只对正常段尝试模型拟合（使用 SegmentFitter）
        segment_results_fitted = self._segment_fitter.fit_all_segments(fitting_segs, fitting_results)
        
        # Step 2.5: 检查是否需要振荡整定
        # 如果整定段拟合效果差，或者只有振荡段，尝试振荡整定
        oscillation_result = self._oscillation_tuner.try_oscillation_tuning(
            fitting_segs, segment_results_fitted, current_pid
        )
        if oscillation_result is not None:
            # 使用振荡分析结果，跳过后续的模型融合
            return self._oscillation_tuner.build_oscillation_output(
                oscillation_result, hist_data, time_range, input_data.tuning_window,
                original_segments, original_results
            )
        
        # Step 2.6: 检查模型拟合是否全部失败
        all_fitting_failed = self._check_all_fitting_failed(segment_results_fitted)
        if all_fitting_failed:
            if use_tuning_segments and disturbance_segs:
                self.log("🔄 整定段拟合失败，回退使用扰动段尝试临界法整定")
                fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                    disturbance_segs, disturbance_results, current_pid, force=True
                )
                if fallback_result is not None:
                    return self._oscillation_tuner.build_oscillation_output(
                        fallback_result, hist_data, time_range, input_data.tuning_window,
                        disturbance_segs, disturbance_results
                    )
            self.log("❌ 所有模型拟合和振荡检测均失败，无法整定")
            return self._empty_result(input_data)
        
        # Step 3: 基于AIC/RSS/形状特征选择最优模型结构
        best_model_type = self._select_best_model_type(segment_results_fitted, hist_data)
        self.log(f"🎯 选择模型类型: {best_model_type}")
        
        # Step 4: 融合各段参数（只使用拟合成功的正常段）
        fusion_result = self._fuse_parameters(segment_results_fitted, best_model_type, fitting_segs)
        
        # Step 5: 验证一致性与仿真匹配度
        fusion_result = self._validate_and_refine(fusion_result, fitting_segs, hist_data)
        
        # Step 5.5: 检查融合参数是否有效
        if abs(fusion_result.K) < self._epsilon or fusion_result.T1 < self._epsilon:
            self.log("\n   ⚠️ 参数融合失败（K或T1为0），尝试振荡整定fallback...")
            fallback_result = self._oscillation_tuner.try_oscillation_tuning(
                fitting_segs, segment_results_fitted, current_pid, force=True
            )
            if fallback_result is not None:
                self.log("   ✅ 振荡整定fallback成功")
                return self._oscillation_tuner.build_oscillation_output(
                    fallback_result, hist_data, time_range, input_data.tuning_window,
                    original_segments, original_results
                )
            else:
                self.log("   ❌ 振荡整定fallback也失败")
        
        # Step 5.6: 使用方法选择器验证稳定性，必要时使用继电反馈法
        model_params = {
            'K': fusion_result.K, 'T1': fusion_result.T1,
            'T2': fusion_result.T2, 'L': fusion_result.L
        }
        method_result = self._method_selector.select_and_tune(
            fitting_segs, segment_results_fitted,
            model_params=model_params, lambda_factor=lambda_factor
        )
        
        # 只有当继电反馈法的稳定性明显更好时才使用
        from .tuning import TuningMethod
        if (method_result.method == TuningMethod.RELAY_FEEDBACK and 
            method_result.stability_margins and 
            method_result.stability_margins.is_stable and
            method_result.stability_margins.phase_margin > 50):
            self.log(f"\n🎯 继电反馈法稳定性更好 (PM={method_result.stability_margins.phase_margin:.1f}°)")
            return self._build_method_selector_output(
                method_result, fusion_result, hist_data, time_range,
                input_data.tuning_window, original_segments, original_results
            )
        
        # 构建数据质量信息，用于自适应保守PID整定
        quality_info = self._build_quality_info(fitting_segs, segment_results_fitted, fusion_result)
        
        # 构建最终输出（传入扰动段信息和质量信息）
        # 使用原始段数据（降采样前）用于可视化
        return self._build_output(fusion_result, hist_data, time_range, lambda_factor, 
                                  input_data.tuning_window, quality_info,
                                  original_results, original_segments)
    
    def _build_quality_info(self, valid_segments: List[HistoricalData],
                            segment_results: List[SegmentResult],
                            fusion_result: FusionResult) -> DataQualityInfo:
        """
        构建数据质量信息，用于自适应保守PID整定
        
        评估因素:
        1. 数据质量评分 - 基于噪声、相关性等
        2. 振荡比 - 数据振荡程度
        3. 拟合R² - 模型拟合质量
        4. 参数一致性 - 多段参数一致程度
        """
        # 计算平均振荡比和质量评分（一次遍历，避免重复调用 analyze_quality）
        oscillation_ratios = []
        quality_scores = []
        is_noisy = False
        
        for seg in valid_segments:
            y = seg.pv
            pv_diff = np.diff(y)
            sign_changes = np.sum(np.abs(np.diff(np.sign(pv_diff))) > 0)
            osc_ratio = sign_changes / (len(y) - 2) if len(y) > 2 else 0
            oscillation_ratios.append(osc_ratio)
            
            # 使用预处理器分析质量（只调用一次）
            quality = self._preprocessor.analyze_quality(y, seg.mv)
            quality_scores.append(quality.quality_score if hasattr(quality, 'quality_score') else 0.5)
            
            # 检查是否有高噪声段
            if hasattr(quality, 'is_noisy') and quality.is_noisy:
                is_noisy = True
        
        avg_oscillation = np.mean(oscillation_ratios) if oscillation_ratios else 0.0
        avg_quality = np.mean(quality_scores) if quality_scores else 0.5
        
        quality_info = DataQualityInfo(
            quality_score=avg_quality,
            oscillation_ratio=avg_oscillation,
            r_squared=fusion_result.global_r2,
            is_noisy=is_noisy,
            consistency_score=fusion_result.consistency_score
        )
        
        # 日志输出保守等级信息
        conservative_level, pb_min = self._pid_calculator._calculate_conservative_level(quality_info)
        self.log(f"   📊 自适应保守调整: 质量={avg_quality:.2f}, 振荡={avg_oscillation:.2f}, "
                f"R²={fusion_result.global_r2:.2f}, 一致性={fusion_result.consistency_score:.2f}")
        self.log(f"   → 保守等级={conservative_level:.1f}, pb最小值={pb_min:.0f}")
        
        return quality_info
    
    # ============================================================
    # Step 1.5: 智能降采样（委托给 SegmentManager）
    # ============================================================
    
    def _apply_smart_downsample(self, segments: List[HistoricalData], 
                                 target_points: int = 1000) -> List[HistoricalData]:
        """对每个扰动段应用智能降采样（委托给 SegmentManager）"""
        return self._segment_manager.apply_smart_downsample(segments, target_points)
    
    # ============================================================
    # Step 2.5: 振荡分析与临界法整定（已移至 oscillation_tuner.py）
    # ============================================================
    
    # 以下方法已移至 OscillationTuner 类，保留为代理调用以保持向后兼容
    
    def _get_conservative_pid_params(self, Pu: float, Ku: float, 
                                      K_approx: float = 1.0,
                                      reason: str = 'generic') -> Dict[str, Any]:
        """获取保守PID参数（代理到 OscillationTuner）"""
        return self._oscillation_tuner.get_conservative_pid_params(Pu, Ku, K_approx, reason)
    
    def _try_oscillation_tuning(self, segments: List[HistoricalData], 
                                segment_results: List[SegmentResult],
                                current_pid: Dict = None) -> Optional[Dict]:
        """尝试振荡分析整定（代理到 OscillationTuner）"""
        return self._oscillation_tuner.try_oscillation_tuning(segments, segment_results, current_pid)
    
    def _build_oscillation_output(self, osc_result: Dict, hist_data: HistoricalData,
                                  time_range: Dict, tuning_windows: List,
                                  segments: List = None, segment_results: List = None) -> Dict[str, Any]:
        """构建振荡整定输出（代理到 OscillationTuner）"""
        return self._oscillation_tuner.build_oscillation_output(
            osc_result, hist_data, time_range, tuning_windows, segments, segment_results
        )
    
    # ============================================================
    # Step 3: 模型选择（使用统一模型选择器）
    # ============================================================
    
    def _select_best_model_type(self, segment_results: List[SegmentResult],
                                 hist_data: 'HistoricalData' = None) -> str:
        """
        选择最优模型结构（统一模型选择）
        
        改进：
        1. 使用质量加权投票而非简单计数
        2. 应用复杂度惩罚（奥卡姆剃刀）
        3. 处理各段模型不一致的情况
        4. 扰动段无法判断时，使用全量数据验证
        """
        # 转换为SegmentModelFit格式
        segment_fits = self._convert_to_segment_fits(segment_results)
        
        if not segment_fits:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        # 使用统一模型选择器
        best_model, reasoning, need_fulldata = self._unified_selector.select_unified_model_type(segment_fits)
        
        # 诊断不一致性
        diagnosis = self._unified_selector.handle_inconsistent_segments(segment_fits)
        if diagnosis['has_inconsistency']:
            self.log("\n   ⚠️ 检测到段间不一致:")
            for issue in diagnosis['issues']:
                self.log(f"      - {issue}")
            if diagnosis['recommendations']:
                self.log("   💡 建议:")
                for rec in diagnosis['recommendations']:
                    self.log(f"      - {rec}")
        
        self.log(f"\n🎯 统一模型选择: {best_model}")
        
        # 如果扰动段无法有效判断且有全量数据，使用全量数据验证
        if need_fulldata and hist_data is not None:
            fulldata_model = self._validate_model_type_with_fulldata(best_model, hist_data)
            if fulldata_model != best_model:
                self.log(f"   📊 全量数据验证: {best_model} → {fulldata_model}")
                best_model = fulldata_model
        
        return best_model
    
    def _validate_model_type_with_fulldata(self, current_model: str, 
                                            hist_data: 'HistoricalData') -> str:
        """
        使用全量数据验证/选择模型类型
        
        当扰动段拟合质量差时，用全量数据做多模型拟合来辅助判断
        """
        self.log("\n   📊 全量数据模型验证:")
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        
        if len(y) < 50:
            self.log("      数据点数不足，保持原选择")
            return current_model
        
        t = np.arange(len(y))
        y0 = y[0]
        
        model_r2s = {}
        
        for model_type in self.CANDIDATE_MODELS:
            try:
                method = SegmentFitter.IDENTIFY_METHODS.get(model_type)
                if method is None:
                    continue
                
                params_raw = method(t, y, u)
                y_pred = self._simulator.simulate(params_raw, model_type, t, u, y0)
                r2 = calculate_r2(y, y_pred)
                
                # 应用复杂度惩罚
                penalty = self._unified_selector.COMPLEXITY_PENALTY.get(model_type, 0)
                adjusted_r2 = r2 - penalty
                
                model_r2s[model_type] = {
                    'r2': r2,
                    'adjusted_r2': adjusted_r2
                }
                self.log(f"      {model_type}: R²={r2:.4f}, 调整R²={adjusted_r2:.4f}")
                
            except Exception as e:
                self.log(f"      {model_type}: 拟合失败 - {e}")
        
        if not model_r2s:
            return current_model
        
        # 选择调整R²最高的模型
        best_fulldata_model = max(model_r2s.keys(), 
                                   key=lambda m: model_r2s[m]['adjusted_r2'])
        best_r2 = model_r2s[best_fulldata_model]['adjusted_r2']
        current_r2 = model_r2s.get(current_model, {}).get('adjusted_r2', 0)
        
        # 只有当全量数据选择的模型明显更好时才替换
        if best_r2 > current_r2 + 0.05:
            self.log(f"      → 全量数据选择: {best_fulldata_model} (R²提升: {best_r2 - current_r2:.4f})")
            return best_fulldata_model
        else:
            self.log(f"      → 保持原选择: {current_model}")
            return current_model
    
    def _convert_to_segment_fits(self, segment_results: List[SegmentResult]) -> List[SegmentModelFit]:
        """将SegmentResult转换为SegmentModelFit格式"""
        segment_fits = []
        
        for result in segment_results:
            if not result.is_valid or not result.model_results:
                continue
            
            fit = SegmentModelFit(
                segment_idx=result.segment_idx,
                data_points=result.data_points,
                quality_score=result.quality_score,
                nonlinearity_score=result.nonlinearity_score,
                is_nonlinear=result.is_nonlinear,
                model_fits=result.model_results
            )
            segment_fits.append(fit)
        
        return segment_fits
    
    # ============================================================
    # Step 1.95: 振荡预检
    # ============================================================
    
    def _precheck_oscillation(self, segments: List['HistoricalData'], 
                               results: List['SegmentResult'],
                               threshold: float = 0.7) -> tuple:
        """
        Step 1.95: 振荡预检 - 在模型拟合前识别高振荡段
        
        高振荡段的模型拟合通常会失败(R²≈0)，提前识别可以：
        1. 避免无意义的拟合计算
        2. 防止错误的K/T/L污染融合池
        
        Args:
            segments: 数据段列表
            results: 对应的分析结果列表
            threshold: 振荡比阈值，超过此值视为高振荡段
            
        Returns:
            fitting_segs, fitting_results: 正常段，待拟合
            osc_segs, osc_results: 高振荡段，跳过拟合
        """
        fitting_segs, fitting_results = [], []
        osc_segs, osc_results = [], []
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1.95: 振荡预检（跳过高振荡段的模型拟合）")
        self.log('='*60)
        
        for seg, res in zip(segments, results):
            osc_ratio = getattr(res, 'oscillation_ratio', 0.0)
            
            if osc_ratio > threshold:
                self.log(f"   段{res.segment_idx+1}: 振荡比={osc_ratio:.2f} > {threshold}，跳过拟合")
                osc_segs.append(seg)
                osc_results.append(res)
            else:
                fitting_segs.append(seg)
                fitting_results.append(res)
        
        self.log(f"   📊 预检结果: {len(fitting_segs)} 个正常段, {len(osc_segs)} 个高振荡段")
        
        return fitting_segs, fitting_results, osc_segs, osc_results
    
    # ============================================================
    # Step 4: 参数融合
    # ============================================================

    
    def _fuse_parameters(self, segment_results: List[SegmentResult],
                         model_type: str,
                         segments: List[HistoricalData] = None) -> FusionResult:
        """融合各段参数（委托给 ParameterFusion）"""
        return self._param_fusion.fuse(segment_results, model_type, segments)
    
    # ============================================================
    # Step 5: 验证与优化
    # ============================================================
    
    def _compute_segment_metrics(self, segments: List[HistoricalData], params: tuple,
                                  model_type: str, enhanced: bool = False
                                  ) -> Tuple[List[float], List[float], List[int]]:
        """
        计算扰动段的R²和RMSE指标
        
        Args:
            segments: 扰动段数据列表
            params: 模型参数
            model_type: 模型类型
            enhanced: 是否使用增强仿真（幅度校准+偏移校正+振荡叠加）
        
        Returns:
            (r2_list, rmse_list, points_list)
        """
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
    
    def _validate_and_refine(self, fusion: FusionResult,
                              segments: List[HistoricalData],
                              hist_data: HistoricalData) -> FusionResult:
        """验证融合参数，必要时进行全局优化"""
        self.log(f"\n{'='*60}")
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
        
        # 验证阶段：不使用振荡叠加，计算原始模型的R²
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
        
        # 计算扰动段指标（纯模型用于评分，增强用于参考）
        segment_r2s_pure, segment_rmses, segment_points = self._compute_segment_metrics(
            segments, params, model_type, enhanced=False
        )
        segment_r2s_enhanced, _, _ = self._compute_segment_metrics(
            segments, params, model_type, enhanced=True
        )
        
        # 计算加权平均
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
        
        # 从集中化配置获取优化阈值
        opt_config = Config.OPTIMIZATION
        r2_threshold = opt_config['r2_threshold']
        min_seg_r2_threshold = opt_config['min_segment_r2']
        seg_r2_std_max = opt_config['segment_r2_std_max']
        
        min_segment_r2 = min(segment_r2s) if segment_r2s else 0
        segment_r2_std = np.std(segment_r2s) if len(segment_r2s) > 1 else 0
        
        # 保存当前参数，用于后续重新计算
        current_params = params
        
        need_optimization = (
            global_r2 < r2_threshold or
            min_segment_r2 < min_seg_r2_threshold or
            segment_r2_std > seg_r2_std_max
        )
        
        if need_optimization:
            self.log(f"   → R²<{r2_threshold}，尝试全量数据优化...")
            
            optimized_params = self._global_optimize_full(y_full, u_full, sv_full, 
                                                           model_type, params)
            
            if optimized_params is not None:
                y_pred_opt = self._simulator.simulate_segmented(
                    optimized_params, model_type, y_full, u_full,
                    reset_on_sv_change=True, sv=sv_full,
                    enable_smooth=True,
                    enable_amplitude_calibration=True,
                    enable_offset_correction=True,
                    enable_oscillation_overlay=False  # 验证时不叠加振荡
                )
                r2_opt = calculate_r2(y_full, y_pred_opt)
                rmse_opt = calculate_rmse(y_full, y_pred_opt)
                
                self.log(f"   优化后全量R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                # 检查优化后K值是否合理
                K_original = params[0]
                K_optimized = optimized_params[0]
                k_reasonable = True
                
                # K值合理性检查（从配置获取阈值）
                k_min = Config.PARAMETER_CONSTRAINTS['k_reasonable_min']
                k_ratio_max = opt_config['k_magnitude_ratio_max']
                
                if abs(K_original) > k_min:
                    if opt_config['k_sign_check'] and K_original * K_optimized < 0:  # 符号反转
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值符号反转({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) < abs(K_original) / k_ratio_max:  # K变得太小
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过小({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                    elif abs(K_optimized) > abs(K_original) * k_ratio_max:  # K变得太大
                        k_reasonable = False
                        self.log(f"   ⚠️ 优化后K值过大({K_original:.4f} → {K_optimized:.4f})，不采用优化结果")
                
                if r2_opt > global_r2 and k_reasonable:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._simulator.params_to_fusion(optimized_params, model_type, fusion)
                    
                    # 优化后也应用参数约束（从配置获取）
                    param_constraints = Config.PARAMETER_CONSTRAINTS
                    if fusion.T1 > param_constraints['T1_max']:
                        fusion.T1 = param_constraints['T1_max']
                    if fusion.L > param_constraints['L_max']:
                        fusion.L = param_constraints['L_max']
                    
                    fusion.fusion_method += " + 全量优化"
                    self.log(f"   → 采用优化结果")
        
        # 使用扰动段加权平均R²作为最终评估指标（更能反映模型在整定数据上的拟合质量）
        # 如果优化后全量R²更高，也重新计算扰动段R²（使用纯模型，不叠加振荡）
        if segment_r2s:
            # 重新计算扰动段R²（使用可能优化后的参数）
            current_params = self._simulator.fusion_to_params(fusion)
            new_segment_r2s, new_segment_rmses, new_segment_points = self._compute_segment_metrics(
                segments, current_params, model_type, enhanced=False
            )
            if new_segment_r2s:
                weighted_r2, weighted_rmse = self._compute_weighted_metrics(
                    new_segment_r2s, new_segment_rmses, new_segment_points
                )
        
        # 输出使用扰动段加权平均R²（更准确反映模型质量）
        fusion.global_r2 = weighted_r2 if segment_r2s else global_r2
        fusion.global_rmse = weighted_rmse if segment_r2s else global_rmse
        
        # 同时保存全量R²用于参考
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
        
        self.log(f"\n   最终评估: 扰动段R²={eval_r2:.4f} ({quality}), 全量R²={global_r2:.4f}")
        
        if eval_r2 < 0.5:
            self.log(f"\n   ⚠️ 模型拟合质量较差，可能原因：")
            if min_segment_r2 < 0.1:
                self.log(f"      - 扰动段数据不符合阶跃响应特征")
            if segment_r2_std > 0.3:
                self.log(f"      - 各段响应特性差异大，可能存在非线性")
            self.log(f"   💡 建议：")
            self.log(f"      - 确认数据来自开环阶跃测试")
            self.log(f"      - 检查是否存在多个扰动叠加")
            self.log(f"      - 考虑使用更长的稳定响应数据")
        
        return fusion
    
    def _global_optimize_full(self, y_full: np.ndarray, u_full: np.ndarray,
                               sv_full: np.ndarray, model_type: str,
                               initial_params: tuple) -> Optional[tuple]:
        """
        全量数据优化
        
        增强：
        1. 检测高振荡数据并预处理
        2. 添加幅度约束确保K值合理
        3. 多起点优化提高鲁棒性
        """
        try:
            from .fitting import ModelIdentifier
            
            # 检测是否为高振荡数据
            oscillation_info = ModelIdentifier.detect_high_oscillation(y_full, u_full)
            
            if oscillation_info['is_oscillating']:
                # 对高振荡数据预处理
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
            
            # 计算期望的K值范围用于约束
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
                
                # 添加K值范围惩罚
                K = abs(params[0])
                if K < k_min or K > k_max:
                    k_penalty = min(abs(K - k_expected) / k_expected, 1.0) * 0.1
                    residuals = residuals * (1 + k_penalty)
                
                return residuals
            
            bounds = self._get_bounds(model_type)
            
            best_params = None
            best_cost = float('inf')
            
            # 使用更合理的初始点
            init_points = [
                initial_params,
                self._simulator.create_init_params(model_type, k_expected, 5.0),
                self._simulator.create_init_params(model_type, k_expected * 0.7, 10.0),
                self._simulator.create_init_params(model_type, k_expected * 0.5, 15.0),
            ]
            
            # 如果检测到负相关，添加负增益初始点
            corr = np.corrcoef(u_full, y_full)[0, 1] if len(u_full) > 2 else 0
            if not np.isnan(corr) and corr < -0.3:
                init_points.append(self._simulator.create_init_params(model_type, -k_expected, 5.0))
            
            for init_p in init_points:
                try:
                    result = least_squares(objective, init_p, bounds=bounds,
                                           method='trf', max_nfev=1000)
                    
                    if result.success and result.cost < best_cost:
                        # 验证结果的幅度合理性
                        y_pred_check = self._simulator.simulate_segmented(
                            tuple(result.x), model_type, y_full, u_full,
                            reset_on_sv_change=True, sv=sv_full,
                            enable_amplitude_calibration=False,
                            enable_offset_correction=False,
                            enable_smooth=False
                        )
                        pred_range = np.ptp(y_pred_check)
                        amplitude_ratio = pred_range / (pv_range + self._epsilon)
                        
                        # 只接受幅度合理的结果（从配置获取阈值）
                        amp_min = Config.OPTIMIZATION['amplitude_ratio_min']
                        amp_max = Config.OPTIMIZATION['amplitude_ratio_max']
                        if amp_min < amplitude_ratio < amp_max:
                            best_cost = result.cost
                            best_params = tuple(result.x)
                except Exception:
                    # 优化失败，尝试下一个初始点
                    continue
            
            # 如果优化结果的K值不合理，进行校正
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
                        # 校正K值
                        K_correction = pv_range / pred_range
                        best_params = list(best_params)
                        best_params[0] = best_params[0] * K_correction
                        best_params = tuple(best_params)
                        self.log(f"   K值校正: 幅度比={amplitude_ratio:.2f}, 校正因子={K_correction:.2f}")
            
            return best_params
            
        except Exception as e:
            self.log(f"   全量优化失败: {e}")
        
        return None
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _parse_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        """解析整定输入"""
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    
    def _get_bounds(self, model_type: str) -> Tuple[List, List]:
        """获取参数边界（委托给 ModelType.get_bounds）"""
        return ModelType.get_bounds(model_type)
    
    def _build_method_selector_output(self, method_result, fusion_result: FusionResult,
                                       hist_data: HistoricalData, time_range: Dict,
                                       tuning_windows: List, segments: List,
                                       segment_results: List) -> Dict[str, Any]:
        """
        构建方法选择器的输出结果
        
        当继电反馈法或混合方法的稳定性更好时使用
        """
        from .tuning import TuningMethod
        from .utils import calculate_r2, calculate_rmse
        
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
        
        # 使用模型参数进行仿真
        params = (model_params.get('K', 1.0), model_params.get('T1', 10.0), model_params.get('L', 1.0))
        pv_model = self._simulator.simulate_segmented(
            params, 'FOPDT', y, u, reset_on_sv_change=True, sv=sv,
            enable_smooth=True, enable_amplitude_calibration=True,
            enable_offset_correction=True, enable_oscillation_overlay=True
        )
        
        r2 = calculate_r2(y, pv_model)
        rmse = calculate_rmse(y, pv_model)
        
        # 稳定性信息
        margins = method_result.stability_margins
        stability_info = {
            'is_stable': margins.is_stable if margins else False,
            'gain_margin': margins.gain_margin if margins else 0,
            'gain_margin_db': margins.gain_margin_db if margins else 0,
            'phase_margin': margins.phase_margin if margins else 0,
        }
        
        # 评分：基于稳定性裕度
        if margins and margins.is_stable:
            gm_score = min(10, margins.gain_margin * 2)  # GM=2 -> 4分, GM=5 -> 10分
            pm_score = min(10, margins.phase_margin / 9)  # PM=45 -> 5分, PM=90 -> 10分
            model_rating = round((gm_score + pm_score) / 2, 1)
        else:
            model_rating = 3.0
        
        return {
            'success': True,
            'model_type': 'FOPDT',
            'model_rating': model_rating,
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
            'closed_loop_verification': stability_info,
            'rating_details': {
                'method': method_result.method.value,
                'reasoning': method_result.reasoning,
                'warnings': method_result.warnings
            },
            'segment_info': OutputBuilder.build_segment_info(segments, segment_results) if segments else []
        }
    
    def _build_output(self, fusion: FusionResult, hist_data: HistoricalData,
                      time_range: Dict, lambda_factor: float,
                      tuning_windows: List[Dict] = None,
                      quality_info: DataQualityInfo = None,
                      segment_results: List[SegmentResult] = None,
                      segments: List[HistoricalData] = None) -> Dict[str, Any]:
        """构建最终输出（委托给 OutputBuilder）"""
        return self._output_builder.build_full_output(
            fusion, hist_data, time_range, lambda_factor,
            tuning_windows, quality_info, segment_results, segments
        )
    
    def _build_segment_info(self, segments: List[HistoricalData], 
                             segment_results: List[SegmentResult]) -> List[Dict]:
        """构建段信息用于可视化（委托给 OutputBuilder）"""
        return OutputBuilder.build_segment_info(segments, segment_results)
    
    def _check_mv_no_change(self, valid_segments: List[HistoricalData]) -> bool:
        """检查MV是否无变化（委托给 SegmentManager）"""
        return self._segment_manager.check_mv_no_change(valid_segments)
    
    def _check_all_fitting_failed(self, segment_results: List[SegmentResult]) -> bool:
        """检查是否所有模型拟合都失败（委托给 SegmentManager）"""
        return self._segment_manager.check_all_fitting_failed(segment_results)
    
    def _merge_tuning_and_disturbance(
        self,
        tuning_segs: List[HistoricalData],
        tuning_results: List[SegmentResult],
        disturbance_segs: List[HistoricalData],
        disturbance_results: List[SegmentResult],
        hist_data: HistoricalData
    ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """合并整定段和扰动段的时间窗口（委托给 SegmentManager）"""
        return self._segment_manager.merge_tuning_and_disturbance(
            tuning_segs, tuning_results,
            disturbance_segs, disturbance_results,
            hist_data
        )
    
    def _classify_and_prioritize_segments(
        self, 
        valid_segments: List[HistoricalData], 
        segment_results: List[SegmentResult]
    ) -> Tuple[List[HistoricalData], List[SegmentResult], List[HistoricalData], List[SegmentResult]]:
        """将扰动段分类为整定段和振荡段（委托给 SegmentManager）"""
        return self._segment_manager.classify_and_prioritize_segments(valid_segments, segment_results)
    
    def _empty_result(self, input_data: Optional[TuningInput]) -> Dict[str, Any]:
        """空结果（委托给 OutputBuilder）"""
        return OutputBuilder.create_empty_result(input_data)
