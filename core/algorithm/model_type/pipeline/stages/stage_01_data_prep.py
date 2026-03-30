from typing import Dict, Any, Union

from ...data_models import HistoricalData, TuningInput
from ...config.loop_type_inferrer import infer_loop_type_from_data, format_inference_log
from ..context import TuningContext
from .base_stage import PipelineStage


class DataPrepStage(PipelineStage):
    """
    数据预处理阶段:
    1. 解析输入数据
    2. 检查边界条件（如果没有数据或者没有扰动段，直接返回 empty result）
    3. 组装 HistoricalData
    4. 提取当前 PID 的 Kp 符号作为先验
    5. 早期推断回路类型
    """

    def _parse_input(self, input_data: Union[Dict, TuningInput]) -> TuningInput:
        """解析输入数据"""
        if isinstance(input_data, dict):
            return TuningInput.from_dict(input_data)
        return input_data

    def _empty_result(self, input_data: TuningInput) -> Dict[str, Any]:
        """构建兼容旧格式的空结果（借用原来 output_builder 或者直接从 orchestrator 拿）
        在流水线里我们只需给 final_result 赋值即可。
        """
        return {
            'success': False,
            'model_type': 'FOPDT',
            'model_rating': 0.0,
            'start_time': input_data.start_time if input_data else None,
            'end_time': input_data.end_time if input_data else None,
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            },
            'fusion_info': {
                'method': 'none', 'n_segments': 0, 'consistency_score': 0.0
            },
            'rating_details': {
                'r2_score': 0.0, 'consistency_score': 0.0, 'validity_score': 0.0,
                'coverage_score': 0.0, 'n_segments': 0, 'total_data_points': 0
            },
            'segment_info': []
        }

    def _early_infer_loop_type(self, context: TuningContext):
        """早期回路类型推断（基于原始数据特征或外部传入）"""
        
        loop_type_str = None
        # 1. 尝试从 input_data.params 提取 (API层传入)
        if isinstance(context.tuning_input_raw, dict):
            params = context.tuning_input_raw.get('params', {})
            loop_type_str = params.get('loop_type')
            
        # 2. 如果 params 没有，尝试 process_context (本地脚本传入)
        if not loop_type_str and context.process_context:
            loop_type_str = context.process_context.get('loop_type')
            
        if loop_type_str:
            # 统一映射中文名字母到英文标准名
            mapping = {
                '液位': 'level', '液位控制': 'level',
                '流量': 'flow', '流量控制': 'flow',
                '压力': 'pressure', '压力控制': 'pressure',
                '温度': 'temperature', '温度控制': 'temperature'
            }
            mapped_type = mapping.get(loop_type_str, loop_type_str)
            if mapped_type in ['flow', 'level', 'pressure', 'temperature']:
                context.loop_type = mapped_type
                if context.process_context is None:
                    context.process_context = {}
                context.process_context['loop_type'] = mapped_type
                context.process_context['loop_type_source'] = 'user_input'
                
                self.log(f"\\n{'='*60}")
                self.log("📊 Step 0.5: 回路类型确认")
                self.log('='*60)
                self.log(f"   ✓ 外部已知回路类型: {mapped_type} (来源: {loop_type_str})，跳过数据特征推断")
                return

        # 3. 未知回路类型，基于数据特征推断
        if not context.hist_data or len(context.hist_data.sv) == 0:
            return

        loop_type, confidence, reason = infer_loop_type_from_data(
            context.hist_data.pv, context.hist_data.mv, context.hist_data.timestamp
        )
        
        self.log(f"\\n{'='*60}")
        self.log("📊 Step 0.5: 早期回路类型推断（基于数据特征）")
        self.log('='*60)
        self.log(f"   {format_inference_log(loop_type, confidence, reason)}")

        if context.process_context is None:
            context.process_context = {}
        context.process_context['loop_type'] = loop_type
        context.process_context['loop_type_inferred'] = True
        context.process_context['loop_type_confidence'] = confidence
        context.process_context['loop_type_source'] = 'early_data'

        context.loop_type = loop_type

    def execute(self, context: TuningContext) -> TuningContext:
        """执行数据准备阶段"""
        tuning_input = self._parse_input(context.tuning_input_raw)
        context.input_data = tuning_input
        
        if tuning_input is None or not tuning_input.tuning_window or not context.raw_data:
            context.final_result = self._empty_result(tuning_input)
            return context
            
        # 提取当前控制器 Kp 符号作为辨识先验 (Phase G)
        base_kp = 1.0
        if context.current_pid:
            base_kp = context.current_pid.get('Kp', context.current_pid.get('kp', 1.0))
        context.current_kp_sign = 1 if base_kp >= 0 else -1
        
        context.time_range = {'start_time': tuning_input.start_time, 'end_time': tuning_input.end_time}
        context.hist_data = HistoricalData.from_json(context.raw_data)
        
        self.log(f"📥 输入: {len(tuning_input.tuning_window)} 个扰动窗口, {len(context.raw_data)} 条数据")
        
        # 执行早期推断
        self._early_infer_loop_type(context)
        
        return context
