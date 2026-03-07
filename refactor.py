import re

with open('core/algorithm/model_type/pipeline/orchestrator.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Rename ModelSelector to TuningOrchestrator
content = content.replace('class ModelSelector(LoggerMixin):', 'class TuningOrchestrator(LoggerMixin):')

# We need to add imports for the pipeline stages at the top
import_str = """
from .context import TuningContext
from .stages.stage_01_data_prep import DataPrepStage
from .stages.stage_02_segmentation import SegmentationStage
from .stages.stage_03_identification import IdentificationStage
from .stages.stage_04_fusion import FusionStage
from .stages.stage_05_refinement import RefinementStage
from .stages.stage_06_output import OutputVerificationStage
"""
content = re.sub(r'(import numpy as np)', r'\1\n' + import_str, content, count=1)


# Rename ModelSelector.__init__ 
content = content.replace('def __init__(self, verbose: bool = False, llm_client=None, process_context: dict = None):', 'def __init__(self, verbose: bool = False, llm_client=None, process_context: dict = None):\n        # Initialize stages pipeline here next time')


# Replace the entire fit method with the pipeline execution
# We match from 'def fit(' to just before 'def _apply_closed_loop_correction('
import re
pattern = r"def fit\(self, tuning_input: Union\[Dict, TuningInput\],.*?(?=def _apply_closed_loop_correction\()"

replacement = """def fit(self, tuning_input: Union[Dict, TuningInput],
            raw_data: List[Dict],
            lambda_factor: float = None,
            current_pid: Dict = None,
            enable_downsample: bool = None,
            downsample_target: int = None) -> Dict[str, Any]:
        \"\"\"模型整定主入口（流水线架构重构版）\"\"\"
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
            enable_downsample=enable_downsample,
            downsample_target=downsample_target
        )
        
        # 2. 注册流水线阶段
        stages = [
            DataPrepStage(logger_mixin=self),
            SegmentationStage(self._segment_processor, self._oscillation_tuner, logger_mixin=self),
            IdentificationStage(self._segment_fitter, self._oscillation_tuner, logger_mixin=self),
            FusionStage(self._unified_selector, self._param_fusion, self, logger_mixin=self),
            RefinementStage(self, self._oscillation_tuner, self._method_selector, self._pid_calculator, logger_mixin=self),
            OutputVerificationStage(self, logger_mixin=self)
        ]
        
        # 3. 按序执行流水线
        self.log(f"\\n{'='*60}\\n🚀 开始 PID Agent 智能整定流水线\\n{'='*60}")
        for stage in stages:
            context = stage.execute(context)
            if context.final_result is not None:
                return context.final_result
                
        # 正常情况下最后阶段一定会生成 final_result，这只是安全兜底
        return context.final_result or self._empty_result(self._parse_input(tuning_input))

    """

new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
with open('core/algorithm/model_type/pipeline/orchestrator.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
