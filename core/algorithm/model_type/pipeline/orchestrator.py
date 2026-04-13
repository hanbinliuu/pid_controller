from .context import TuningContext
from .stages.stage_01_data_prep import DataPrepStage
from .stages.stage_02_segmentation import SegmentationStage
from .stages.stage_03_identification import IdentificationStage
from .stages.stage_04_fusion import FusionStage
from .stages.stage_05_refinement import RefinementStage
from .stages.stage_05b_self_optimize import SelfOptimizeStage
from .stages.stage_06_output import OutputVerificationStage

from typing import List, Dict, Any, Optional, Union

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
        # 滑动窗口寻优：当启用时，自动生成重叠窗口并选出最优
        # ============================================================
        sw_config = Config.SLIDING_WINDOW
        enable_sw = params.get('sliding_window', sw_config.get('enabled', False))
        
        # [NEW] 混合架构拦截器 (Hybrid Auto-Enable)
        # 前端可能传来了由探测器选出的 qualified_windows，我们需要快速验明正身
        exact_window_mode = params.get('exact_window', False)
        has_high_quality_step = False
        
        if qualified_windows and not exact_window_mode:
            for w in qualified_windows:
                sv_values = [d.get('sv', d.get('SV', 0)) for d in history_data 
                             if w.get('start_time', 0) <= d.get('timestamp', 0) <= w.get('end_time', float('inf'))]
                # SV阶跃幅度 > 0.5 视为高质量的明确阶跃变动 (Level 1/2)
                if sv_values and (max(sv_values) - min(sv_values)) > 0.5:
                    has_high_quality_step = True
                    break
                    
        # 如果既不是强制模式，且里面没有找到明确阶跃(说明是 Level 3 瞎猜的兜底段)
        if not has_high_quality_step and not exact_window_mode:
            # 直接在主入口“静默”开启 Grid Search 洗地，无需提示用户，用户自动获得最高收益
            enable_sw = True
        
        if enable_sw and history_data:
            if not has_high_quality_step:
                self.log("   🔍 未检测到高质量阶跃特征，系统已在后台自动升级为 Grid Search 滑窗寻优模式...")
            
            best_window = self._sliding_window_search(
                history_data, params, current_pid, sw_config
            )
            if best_window is not None:
                # 用最优窗口无缝覆盖掉前端传进来的 qualified_windows，走后续正常流程
                qualified_windows = [best_window]
        
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
                                sw_config: Dict) -> Optional[Dict]:
        """
        在历史数据上进行滑动窗口快速筛选，返回评分最高的窗口。
        
        流程:
        1. 将连续数据切成 N 个重叠窗口
        2. 对每个窗口运行快速整定（verbose=False）
        3. 按评分排序，返回最优窗口
        
        Args:
            history_data: 完整历史数据
            params: 参数配置
            current_pid: 当前PID参数
            sw_config: 滑动窗口配置
            
        Returns:
            最优窗口 dict {'start_time': ms, 'end_time': ms} 或 None
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
            return None
        
        self.log(f"\n{'='*60}")
        self.log(f"🔍 滑动窗口寻优: {len(search_windows)} 个候选窗口 (窗口={window_h}h, 步长={step_h}h)")
        self.log('='*60)
        
        # 快速筛选：对每个窗口跑一次完整管线（并发执行）
        import concurrent.futures
        import os
        from datetime import datetime
        
        candidates = []
        
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
                
                return {
                    'window': window,
                    'score': score,
                    'kp': kp,
                    'pb': pb,
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
                    self.log(f"   窗口 {res['idx']+1:2d}/{len(search_windows)}: {st_str} ~ {et_str} | 评分={res['score']:5.2f} | Pb={res['pb']:.1f}%")
        
        if not candidates:
            self.log("   ⚠️ 所有窗口评估失败，跳过滑窗寻优")
            return None
        
        # 按评分降序排列
        candidates.sort(key=lambda c: c['score'], reverse=True)
        best = candidates[0]
        
        from datetime import datetime
        best_st = datetime.fromtimestamp(best['window']['start_time']/1000).strftime('%m-%d %H:%M')
        best_et = datetime.fromtimestamp(best['window']['end_time']/1000).strftime('%m-%d %H:%M')
        self.log(f"\n   🏆 最优窗口: {best_st} ~ {best_et} (评分={best['score']:.2f})")
        
        return best['window']
    

    
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
            SegmentationStage(self._segment_processor, self._segment_manager, self._oscillation_tuner, logger_mixin=self),
            IdentificationStage(self._segment_fitter, self._oscillation_tuner, logger_mixin=self),
            FusionStage(self._unified_selector, self._param_fusion, self._simulator, self._segment_processor, self._oscillation_tuner, logger_mixin=self),
            RefinementStage(self._simulator, self._oscillation_tuner, self._method_selector, self._pid_calculator, verbose=self._verbose, logger_mixin=self),
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
    



