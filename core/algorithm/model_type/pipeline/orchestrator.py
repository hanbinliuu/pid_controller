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
                - qualified_windows: 扰动窗口列表
                - current_pid: 当前 PID 参数（可选）
                - process_context: 工艺上下文（可选，会覆盖构造函数中的设置）
        """
        history_data = input_data.get('history_data', [])
        params = input_data.get('params', {})
        qualified_windows = input_data.get('qualified_windows', [])
        current_pid = input_data.get('current_pid', None)  # 当前 PID 参数
        
        turning_type = params.get('turning_type')
        model_type = params.get('model_type')

        if not history_data:
            return OutputBuilder.create_empty_result(model_type=model_type, turning_type=turning_type)
        
        if not qualified_windows:
            # 没有扰动窗口（tuning_segment未检测到振荡）→ 不需要整定
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
        
        result = self.fit(tuning_input, history_data,
                          lambda_factor=Config.TUNING_DEFAULTS['lambda_factor'],
                          current_pid=current_pid)
                          
        # 补全可能丢失的前端强行指定的参数
        if not result.get('success'):
            if model_type: result['model_type'] = model_type
            if turning_type: result['turning_type'] = turning_type
            
        return result
    

    
    # ============================================================
    # 原有入口（保持兼容）
    # ============================================================
    
    def fit(self, tuning_input: Union[Dict, TuningInput],
            raw_data: List[Dict],
            lambda_factor: float = None,
            current_pid: Dict = None,
            enable_downsample: bool = None,
            downsample_target: int = None) -> Dict[str, Any]:
        """模型整定主入口（流水线架构重构版）"""
        tuning_defaults = Config.TUNING_DEFAULTS
        if lambda_factor is None:
            lambda_factor = tuning_defaults['lambda_factor']
        if enable_downsample is None:
            enable_downsample = tuning_defaults['enable_downsample']
        if downsample_target is None:
            downsample_target = tuning_defaults['downsample_target']
            
        # 1. 组装上下文
        context = TuningContext(
            raw_data=raw_data,
            tuning_input_raw=tuning_input,
            lambda_factor=lambda_factor,
            current_pid=current_pid,
            process_context=self._process_context or {},
            standard_model=(self._process_context or {}).get('standard_model'),
            instance_model=(self._process_context or {}).get('instance_model'),
            characterization_model=(self._process_context or {}).get('characterization_model'),
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
            SelfOptimizeStage(self._pid_calculator, verbose=self._verbose, logger_mixin=self),
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
    



