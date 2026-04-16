from .context import TuningContext
from .fallback_manager import PipelineFallbackManager
from .stages.stage_01_data_prep import DataPrepStage
from .stages.stage_02_segmentation import SegmentationStage
from .stages.stage_03_identification import IdentificationStage
from .stages.stage_04_fusion import FusionStage
from .stages.stage_05_refinement import RefinementStage
from .stages.stage_05b_self_optimize import SelfOptimizeStage
from .stages.stage_06_output import OutputVerificationStage

from typing import List, Dict, Any, Optional, Union, Tuple
import numpy as np

from ..config import Config, ModelType
from ..data_models import TuningInput
from ..utils import get_recommendation, determine_turning_type

# 子模块导入
from ..preprocessing import DataPreprocessor, SegmentProcessor, SegmentManager
from ..fitting import SegmentFitter, UnifiedModelSelector, ParameterFusion
from ..tuning import PIDCalculator, OscillationTuner, TuningMethodSelector
from ..simulation import ModelSimulator

# 其他模块
from ..output_builder import OutputBuilder
from ..logger import LoggerMixin



class TuningOrchestrator(LoggerMixin):
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
        # Initialize stages pipeline here next time
        # Initialize stages pipeline here next time
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
        self._fallback_manager = PipelineFallbackManager(self._oscillation_tuner, logger_mixin=self)
        
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
                    - sliding_window: 是否启用滑动窗口寻优（可选，覆盖全局配置）
                    - window_hours: 窗口时长小时（可选）
                    - step_hours: 步长小时（可选）
                - qualified_windows: 扰动窗口列表
                - current_pid: 当前 PID 参数（可选）
                - process_context: 工艺上下文（可选，会覆盖构造函数中的设置）
                - response_mode: 响应模式（可选）
        """
        history_data = input_data.get('history_data', [])
        params = input_data.get('params', {})
        qualified_windows = input_data.get('qualified_windows', [])
        current_pid = input_data.get('current_pid', None)
        # 动态提取外部(后端)传入的最新的工艺/语义上下文
        ext_process_context = input_data.get('process_context', None)
        
        
        turning_type = params.get('turning_type')
        model_type = params.get('model_type')

        if not history_data:
            return OutputBuilder.create_empty_result(model_type=model_type, turning_type=turning_type)
        
        # ============================================================
        # 窗口策略路由 (Window Strategy Router)
        # ============================================================
        # 内部自动分类数据所属阶段:
        #   Stage 1: MV 阶跃响应 → 三阶段窗口流水线
        #   Stage 2: SV 阶跃响应 → 三阶段窗口流水线 (+ 闭环修正)
        #   Stage 3: 无明确阶跃 / 自然扰动 → 滑动窗口寻优
        # ============================================================
        sw_config = Config.SLIDING_WINDOW
        enable_sw = params.get('sliding_window', sw_config.get('enabled', False))
        exact_window_mode = params.get('exact_window', False)
        detected_stage = 3  # 默认假设 Stage 3
        
        if qualified_windows and not exact_window_mode:
            for w in qualified_windows:
                w_start = w.get('start_time', 0)
                w_end = w.get('end_time', float('inf'))
                w_data = [d for d in history_data if w_start <= d.get('timestamp', 0) <= w_end]
                
                if not w_data:
                    continue
                
                sv_values = [d.get('sv', d.get('SV', 0)) for d in w_data]
                mv_values = [d.get('mv', d.get('MV', 0)) for d in w_data]
                
                sv_range = max(sv_values) - min(sv_values) if sv_values else 0
                mv_range = max(mv_values) - min(mv_values) if mv_values else 0
                
                # Stage 1: MV 有显著阶跃且 SV 无变化 → 开环 MV 阶跃测试
                if mv_range > 0.5 and sv_range < 0.5:
                    detected_stage = 1
                    break
                # Stage 2: SV 有显著阶跃 → 闭环 SV 阶跃响应
                elif sv_range > 0.5:
                    detected_stage = 2
                    break
                # 否则保持 Stage 3
        
        if exact_window_mode:
            detected_stage = 0  # 标记为强制模式，不做阶段路由

        # [NEW] 对上游 detector 给出的窗口做质量去重，避免同质重叠窗口污染后续整定
        if qualified_windows and not exact_window_mode:
            qualified_windows = self._refine_detected_windows(
                qualified_windows,
                max_keep=sw_config.get('top_n', 3),
                max_overlap=sw_config.get('max_overlap_ratio', 0.8),
                min_quality=sw_config.get('min_window_quality', 0.2),
            )
        
        self.log(f"   📋 数据阶段自动分类: Stage {detected_stage}"
                 f"{' (MV阶跃→三阶段流水线)' if detected_stage == 1 else ''}"
                 f"{' (SV阶跃→三阶段流水线)' if detected_stage == 2 else ''}"
                 f"{' (无明确阶跃→滑窗寻优)' if detected_stage == 3 else ''}"
                 f"{' (exact_window强制模式)' if detected_stage == 0 else ''}")
        
        # Stage 1/2: 有明确阶跃 → 不需要滑窗，直接走三阶段窗口流水线
        if detected_stage in (1, 2):
            enable_sw = False
        # Stage 3: 无明确阶跃 → 自动开启滑窗寻优
        elif detected_stage == 3:
            enable_sw = True
        
        if enable_sw and history_data:
            self.log("   🔍 Stage 3: 未检测到明确阶跃特征，启动 Grid Search 滑窗寻优...")
            
            top_windows = self._sliding_window_search(
                history_data, params, current_pid, sw_config
            )
            if top_windows:
                qualified_windows = top_windows
        
        if not qualified_windows:
            self.log("⚠️ 无扰动窗口（tuning_segment未检测到振荡），跳过整定")
            return OutputBuilder.create_empty_result(model_type=model_type, turning_type=turning_type)
        
        tuning_input = {
            'start_time': history_data[0].get('timestamp') if history_data else None,
            'end_time': history_data[-1].get('timestamp') if history_data else None,
            'tuning_window': [
                {'start_time': w.get('start_time'), 'end_time': w.get('end_time')}
                for w in qualified_windows
            ]
        }
        
        # 补充：提取 fast_mode (供 sliding_window 极速探针模式使用)
        fast_mode = params.get('fast_mode', False)
        
        result = self.fit(tuning_input, history_data,
                          lambda_factor=Config.TUNING_DEFAULTS['lambda_factor'],
                          current_pid=current_pid,
                          process_context=ext_process_context,
                          fast_mode=fast_mode)
                          
        # 补全可能丢失的前端强行指定的参数
        if not result.get('success'):
            if model_type: result['model_type'] = model_type
            if turning_type: result['turning_type'] = turning_type
            
        return result
    
    # ============================================================
    # 滑动窗口寻优引擎
    # ============================================================
    
    def _sliding_window_search(self, history_data: List[Dict],
                                params: Dict, current_pid: Dict,
                                sw_config: Dict) -> List[Dict]:
        """
        在历史数据上进行滑动窗口快速筛选，返回 Top-N 高分窗口用于多段融合。
        
        流程:
        1. 将连续数据切成 N 个重叠窗口
        2. 对每个窗口运行快速整定（verbose=False）
        3. 按评分排序，返回 Top-N 窗口
        
        Args:
            history_data: 完整历史数据
            params: 参数配置
            current_pid: 当前PID参数
            sw_config: 滑动窗口配置
            
        Returns:
            Top-N 窗口列表 [{'start_time': ms, 'end_time': ms}, ...] 或空列表
        """
        window_h = params.get('window_hours', sw_config.get('window_hours', 6.0))
        step_h = params.get('step_hours', sw_config.get('step_hours', 2.0))
        max_windows = sw_config.get('max_windows', 20)
        min_windows = sw_config.get('min_windows', 2)
        fast_verbose = sw_config.get('fast_screen_verbose', False)
        
        w_ms = window_h * 3600 * 1000
        step_ms = step_h * 3600 * 1000
        
        data_start = history_data[0].get('timestamp', 0)
        data_end = history_data[-1].get('timestamp', 0)
        
        # 生成候选窗口
        search_windows = []
        curr_start = data_start
        while curr_start + w_ms <= data_end and len(search_windows) < max_windows:
            search_windows.append({
                'start_time': int(curr_start),
                'end_time': int(curr_start + w_ms)
            })
            curr_start += step_ms
        
        if len(search_windows) < min_windows:
            self.log(f"   ℹ️ 滑窗: 数据时长不足，仅能切出 {len(search_windows)} 个窗口（需≥{min_windows}），跳过滑窗寻优")
            return []
        
        self.log(f"\n{'='*60}")
        self.log(f"🔍 滑动窗口寻优: {len(search_windows)} 个候选窗口 (窗口={window_h}h, 步长={step_h}h)")
        self.log('='*60)
        
        # 快速筛选：对每个窗口跑一次完整管线（并发执行）
        import concurrent.futures
        import os
        from datetime import datetime
        
        candidates = []
        
        loop_constraints = self._get_loop_constraints()
        diversity_overlap = sw_config.get('max_overlap_ratio', 0.8)

        def _extract_kp(candidate_pid: Dict[str, Any]) -> float:
            if not isinstance(candidate_pid, dict):
                return 0.0
            for k in ('Kp', 'kp'):
                if k in candidate_pid and candidate_pid.get(k) is not None:
                    try:
                        return float(candidate_pid.get(k))
                    except Exception:
                        pass
            pb = candidate_pid.get('pb', candidate_pid.get('Pb', 0.0))
            try:
                pb = float(pb)
                if abs(pb) > 1e-9:
                    return 100.0 / pb
            except Exception:
                pass
            return 0.0

        current_kp = _extract_kp(current_pid or {})

        def evaluate_window(i, window):
            try:
                fast_input = {
                    'history_data': history_data,
                    'params': {**params, 'sliding_window': False, 'fast_mode': True},  # 极速模式（跳过Phase2精调和多起点模拟）
                    'qualified_windows': [window],
                    'current_pid': current_pid,
                }
                # 构建轻量级 orchestrator（复用已有工艺上下文，只关日志）
                fast_orc = TuningOrchestrator(
                    verbose=fast_verbose, 
                    process_context=self._process_context
                )
                result = fast_orc.run(fast_input)
                
                score = result.get('model_rating', 0.0)
                pid = result.get('pid_parameters', {})
                kp = pid.get('kp', pid.get('Kp', 0.0))
                pb = pid.get('pb', pid.get('Pb', 0.0))
                ti = pid.get('ti', pid.get('Ti', 0.0))

                rating_details = result.get('rating_details', {}) or {}
                perf_score = float(rating_details.get('performance_score', 0.0) or 0.0)
                method_conf = float(rating_details.get('method_confidence', 0.5) or 0.5)

                penalty, p_detail = self._window_boundary_penalty(pid, loop_constraints)
                stability_bonus = 0.0
                clv = result.get('closed_loop_verification', {}) or {}
                if clv.get('is_stable') is True:
                    stability_bonus = 0.05
                elif clv.get('is_stable') is False:
                    stability_bonus = -0.15

                # 对“模型分高但闭环性能偏低”的窗口增加扣分，避免误选假优窗口
                perf_penalty = max(0.0, (7.0 - perf_score) * 0.08)  # perf<7 才惩罚
                conf_penalty = max(0.0, (0.45 - method_conf) * 0.15)

                # 若可用 current_pid，符号冲突通常意味着窗口方向性不稳定
                sign_penalty = 0.0
                if abs(current_kp) > 1e-9 and abs(kp) > 1e-9 and (current_kp * float(kp) < 0):
                    sign_penalty = 0.25

                settling_penalty = 0.0
                st = clv.get('settling_time')
                if st is not None:
                    try:
                        if not np.isfinite(float(st)):
                            settling_penalty = 0.20
                    except Exception:
                        pass

                success_penalty = 0.0 if result.get('success', False) else 0.4
                adjusted_score = (
                    score - penalty - perf_penalty - conf_penalty - sign_penalty - settling_penalty
                    + stability_bonus - success_penalty
                )
                
                return {
                    'window': window,
                    'score': score,
                    'adjusted_score': adjusted_score,
                    'kp': kp,
                    'pb': pb,
                    'ti': ti,
                    'edge_penalty': penalty,
                    'perf_penalty': perf_penalty,
                    'conf_penalty': conf_penalty,
                    'sign_penalty': sign_penalty,
                    'settling_penalty': settling_penalty,
                    'edge_detail': p_detail,
                    'idx': i,
                    'error': None
                }
            except Exception as e:
                return {'idx': i, 'error': str(e)}

        self.log(f"   🚀 正在启动 {os.cpu_count() or 4} 线程并发提速评估...")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as executor:
            futures = {executor.submit(evaluate_window, i, w): i for i, w in enumerate(search_windows)}
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res.get('error'):
                    self.log(f"   窗口 {res['idx']+1}: 评估异常 ({res['error']})")
                else:
                    candidates.append(res)
                    st_str = datetime.fromtimestamp(res['window']['start_time']/1000).strftime('%m-%d %H:%M')
                    et_str = datetime.fromtimestamp(res['window']['end_time']/1000).strftime('%m-%d %H:%M')
                    self.log(
                        f"   窗口 {res['idx']+1:2d}/{len(search_windows)}: {st_str} ~ {et_str} | "
                        f"评分={res['score']:5.2f} | 调整后={res['adjusted_score']:5.2f} | "
                        f"Perf罚={res['perf_penalty']:.2f} | Pb={res['pb']:.1f}%"
                    )
        
        if not candidates:
            self.log("   ⚠️ 所有窗口评估失败，跳过滑窗寻优")
            return []
        
        # 按“窗口综合分”排序（评分 - 贴边惩罚 + 稳定奖励）
        candidates.sort(key=lambda c: c['adjusted_score'], reverse=True)
        
        # 选取 Top N 个分数达标的窗口用于多段融合
        top_n = sw_config.get('top_n', 1)
        min_score_ratio = sw_config.get('top_n_min_score_ratio', 0.85)
        best_score = candidates[0]['adjusted_score']
        score_threshold = best_score * min_score_ratio

        # 先阈值过滤，再做重叠抑制，保证窗口多样性
        prefiltered = [c for c in candidates if c['adjusted_score'] >= score_threshold]
        top_candidates = []
        for c in prefiltered:
            if len(top_candidates) >= top_n:
                break
            if any(self._window_overlap_ratio(c['window'], kept['window']) > diversity_overlap for kept in top_candidates):
                continue
            top_candidates.append(c)
        
        from datetime import datetime
        self.log(f"\n   🏆 Top {len(top_candidates)} 窗口 (最高调整分={best_score:.2f}, 阈值={score_threshold:.2f}):")
        for rank, c in enumerate(top_candidates, 1):
            st_str = datetime.fromtimestamp(c['window']['start_time']/1000).strftime('%m-%d %H:%M')
            et_str = datetime.fromtimestamp(c['window']['end_time']/1000).strftime('%m-%d %H:%M')
            self.log(
                f"      #{rank}: {st_str} ~ {et_str} "
                f"(评分={c['score']:.2f}, 调整后={c['adjusted_score']:.2f}, 边界惩罚={c['edge_penalty']:.2f})"
            )
        
        return [c['window'] for c in top_candidates]
    

    
    # ============================================================
    # 原有入口（保持兼容）
    # ============================================================
    
    def fit(self, tuning_input: Union[Dict, TuningInput],
            raw_data: List[Dict],
            lambda_factor: float = None,
            current_pid: Dict = None,
            enable_downsample: bool = None,
            downsample_target: int = None,
            process_context: Dict = None,
            fast_mode: bool = False) -> Dict[str, Any]:
        """模型整定主入口（流水线架构重构版）"""
        tuning_defaults = Config.TUNING_DEFAULTS
        if lambda_factor is None:
            lambda_factor = tuning_defaults['lambda_factor']
        if enable_downsample is None:
            enable_downsample = tuning_defaults['enable_downsample']
        if downsample_target is None:
            downsample_target = tuning_defaults['downsample_target']
            
        # 使用显式传入的 process_context，若无则使用由构造函数传入的默认 self._process_context
        active_context = process_context if process_context is not None else (self._process_context or {})
        
        # 1. 组装上下文
        context = TuningContext(
            raw_data=raw_data,
            tuning_input_raw=tuning_input,
            lambda_factor=lambda_factor,
            current_pid=current_pid,
            process_context=active_context,
            ontology_model=active_context.get('ontology_model'),
            mechanism_model=active_context.get('mechanism_model'),
            knowledge_model=active_context.get('knowledge_model'),
            characterization_model=active_context.get('characterization_model'),
            data_model=active_context.get('data_model'),
            metrics_model=active_context.get('metrics_model'),
            enable_downsample=enable_downsample,
            downsample_target=downsample_target
        )
        
        # 2. 注册流水线阶段
        #    前置阶段: 可能提前产出 final_result（振荡整定/fallback）
        #    后置阶段: SelfOptimizeStage 必须对所有路径的结果做自优化
        pre_stages = [
            DataPrepStage(logger_mixin=self),
            SegmentationStage(self._segment_processor, self._segment_manager, self._oscillation_tuner, fallback_manager=self._fallback_manager, logger_mixin=self),
            IdentificationStage(self._segment_fitter, self._oscillation_tuner, fallback_manager=self._fallback_manager, logger_mixin=self),
            FusionStage(self._unified_selector, self._param_fusion, self._simulator, self._segment_processor, self._oscillation_tuner, logger_mixin=self),
            RefinementStage(self._simulator, self._oscillation_tuner, self._method_selector, self._pid_calculator, fallback_manager=self._fallback_manager, verbose=self._verbose, logger_mixin=self),
        ]
        
        post_stages = [
            SelfOptimizeStage(self._pid_calculator, verbose=self._verbose, logger_mixin=self, fast_mode=fast_mode),
            OutputVerificationStage(self._preprocessor, self._output_builder, logger_mixin=self),
        ]
        
        # 3. 按序执行流水线
        self.log(f"\n{'='*60}\n🚀 开始 PID Agent 智能整定流水线\n{'='*60}")
        
        # 前置阶段：遇到 final_result 可提前跳出
        for stage in pre_stages:
            context = stage.execute(context)
            if context.final_result is not None:
                break
        
        # 安全兜底：如果 fallback 已触发但 final_result 未设置，
        # 生成空结果防止后续 Stage 访问 None 导致异常
        if context.is_fallback_triggered and context.final_result is None:
            self.log("   ⚠️ fallback 已触发但无整定结果，生成空结果")
            context.final_result = OutputBuilder.create_empty_result(
                self._parse_input(tuning_input)
            )
        
        # 后置阶段：始终执行（SelfOptimize 对所有路径的结果做优化）
        for stage in post_stages:
            context = stage.execute(context)
                
        # 正常情况下最后阶段一定会生成 final_result，这只是安全兜底
        return context.final_result or OutputBuilder.create_empty_result(self._parse_input(tuning_input))


    
    def _parse_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        """解析整定输入"""
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    


    @staticmethod
    def _window_overlap_ratio(w1: Dict[str, Any], w2: Dict[str, Any]) -> float:
        s1, e1 = int(w1.get('start_time', 0)), int(w1.get('end_time', 0))
        s2, e2 = int(w2.get('start_time', 0)), int(w2.get('end_time', 0))
        inter = max(0, min(e1, e2) - max(s1, s2))
        if inter <= 0:
            return 0.0
        d1 = max(1, e1 - s1)
        d2 = max(1, e2 - s2)
        return inter / min(d1, d2)

    def _get_loop_constraints(self) -> Dict[str, float]:
        """基于 process_context 获取回路约束，用于窗口筛选贴边惩罚。"""
        try:
            from ..config.loop_presets import get_loop_preset
            loop_type = (self._process_context or {}).get('loop_type', 'default')
            return get_loop_preset(loop_type)
        except Exception:
            return {}

    def _window_boundary_penalty(self, pid: Dict[str, Any], loop_constraints: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
        """窗口级贴边惩罚：用于滑窗阶段过滤“高分但贴边”的脆弱解。"""
        pb = float(pid.get('pb', pid.get('Pb', 0.0)) or 0.0)
        ti = float(pid.get('ti', pid.get('Ti', 0.0)) or 0.0)
        pb_min = float(loop_constraints.get('pb_min', 0.0) or 0.0)
        ti_min = float(loop_constraints.get('ti_min', 0.1) or 0.1)
        ti_max = float(loop_constraints.get('ti_max', 300.0) or 300.0)

        loop_type = (self._process_context or {}).get('loop_type', '')
        if loop_type == 'level':
            ti_min = max(ti_min, 60.0)
        elif loop_type == 'flow':
            ti_min = max(ti_min, 2.0)
            ti_max = min(ti_max, 20.0)
        elif loop_type == 'pressure':
            ti_min = max(ti_min, 3.0)
            ti_max = min(ti_max, 60.0)

        def near_lower(value: float, lower: float, ratio: float, weight: float) -> float:
            if lower <= 0:
                return 0.0
            band = max(lower * ratio, 1e-6)
            gap = value - lower
            if gap <= 0:
                return weight
            if gap >= band:
                return 0.0
            return weight * (1.0 - gap / band)

        def near_upper(value: float, upper: float, ratio: float, weight: float) -> float:
            if upper <= 0:
                return 0.0
            band = max(upper * ratio, 1e-6)
            gap = upper - value
            if gap <= 0:
                return weight
            if gap >= band:
                return 0.0
            return weight * (1.0 - gap / band)

        p_pb = near_lower(pb, pb_min, 0.25, 0.28)
        p_ti = near_lower(ti, ti_min, 0.25, 0.22) + near_upper(ti, ti_max, 0.25, 0.10)
        penalty = min(0.45, max(0.0, p_pb + p_ti))
        return penalty, {'pb': pb, 'ti': ti, 'pb_min': pb_min, 'ti_min': ti_min, 'ti_max': ti_max}

    def _refine_detected_windows(
        self,
        windows: List[Dict[str, Any]],
        max_keep: int = 5,
        max_overlap: float = 0.8,
        min_quality: float = 0.2
    ) -> List[Dict[str, Any]]:
        """
        对 detector 返回窗口做质量排序 + 重叠抑制。
        """
        if not windows:
            return windows
        ranked = sorted(windows, key=lambda w: float(w.get('quality_score', 0.0)), reverse=True)
        qualified = [w for w in ranked if float(w.get('quality_score', 0.0)) >= min_quality]
        if qualified:
            ranked = qualified
        picked: List[Dict[str, Any]] = []
        for w in ranked:
            if len(picked) >= max_keep:
                break
            if any(self._window_overlap_ratio(w, p) > max_overlap for p in picked):
                continue
            picked.append(w)
        return picked or windows[:max_keep]
