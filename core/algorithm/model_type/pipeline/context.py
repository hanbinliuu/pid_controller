from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from core.algorithm.model_type.data_models import HistoricalData, SegmentResult, FusionResult, TuningInput
from core.models import OntologyModel, MechanismModel, KnowledgeModel, CharacterizationModel, DataModel, MetricsModel

@dataclass
class TuningContext:
    """
    整定流水线上下文 (Tuning Pipeline Context)
    
    用于在各个整定阶段 (Stage) 之间传递状态、数据和中间结果，
    消除原本在 `model_selector` 中的超级庞大的局部变量表。
    
    桥接层说明
    ----------
    底部的 ``get_*`` 方法是**语义模型 → 算法配置**的桥接层：
    - 优先从语义模型读取（OS 中台提供的结构化数据）
    - 如果语义模型为 None，fallback 到 ``loop_presets`` / ``Config`` 硬编码
    
    后续迁移时，各 Stage 只需将 ``Config.XXX`` / ``loop_presets.get_loop_preset()``
    替换为 ``context.get_xxx()``，语义层自动生效，无需其他改动。
    """
    # ---------------- 1. 外部输入 (Inputs) ----------------
    raw_data: List[Dict] = field(default_factory=list)
    input_data: Optional[TuningInput] = None
    tuning_input_raw: Any = None
    
    # 整定配置参数
    lambda_factor: float = 0.8
    current_pid: Optional[Dict[str, float]] = None
    process_context: Dict[str, Any] = field(default_factory=dict)
    
    # 语义原子模型 (Atomic Domain Primitive Models)
    ontology_model: Optional[OntologyModel] = None
    mechanism_model: Optional[MechanismModel] = None
    knowledge_model: Optional[KnowledgeModel] = None
    characterization_model: Optional[CharacterizationModel] = None
    data_model: Optional[DataModel] = None
    metrics_model: Optional[MetricsModel] = None
    
    enable_downsample: bool = True
    downsample_target: int = 1000
    
    # ---------------- 2. 运行时状态/标识 (Runtime State) ----------------
    current_kp_sign: int = 1
    loop_type: str = 'default'
    is_fallback_triggered: bool = False
    dt_data: float = 1.0  # 数据采样周期(秒)，在 DataPrepStage 中计算
    
    # ---------------- 3. 中间辨识结果 (Intermediate Results) ----------------
    hist_data: Optional[HistoricalData] = None
    time_range: Dict[str, Any] = field(default_factory=dict)
    
    # 段提取与筛选
    valid_segments: List[HistoricalData] = field(default_factory=list)
    segment_results: List[SegmentResult] = field(default_factory=list)
    
    # SV阶跃段 (特殊标注)
    sv_step_segs: List[HistoricalData] = field(default_factory=list)
    from_sv_step: bool = False
    
    # 用于拟合的最终段（经过优先级策略筛选）
    segments_for_fitting: List[HistoricalData] = field(default_factory=list)
    results_for_fitting: List[SegmentResult] = field(default_factory=list)
    
    # 原始段备份（降采样前，用于可视化和最终输出拼接）
    original_segments: List[HistoricalData] = field(default_factory=list)
    original_results: List[SegmentResult] = field(default_factory=list)
    
    # 模型辨识拟合后结果
    segment_results_fitted: List[SegmentResult] = field(default_factory=list)
    best_model_type: str = 'FOPDT'
    
    # ---------------- 4. 融合与验证结果 (Fusion & Verification) ----------------
    fusion_result: Optional[FusionResult] = None
    corrected_T1: Optional[float] = None
    corrected_K: Optional[float] = None
    
    # ---------------- 5. 最终输出数据 (Final Outputs) ----------------
    final_result: Optional[Dict[str, Any]] = None
    
    # Rating 自优化结果（SelfOptimizeStage Phase 2 微调后的 PID 参数）
    optimized_pid: Optional[Dict[str, float]] = None

    def add_log(self, message: str):
        """记录流水线执行日志（仅做占位或挂载外部 logger）"""
        pass

    # ================================================================
    # 桥接层 (Bridge Accessors)
    # ================================================================
    # 规则：语义模型有值 → 用语义模型；语义模型为 None → fallback 到老配置
    # 后续迁移：Stage 把 Config.XXX / loop_presets 替换为 context.get_xxx() 即可
    # ================================================================

    def _get_preset(self) -> dict:
        """获取当前回路类型的 loop_presets 配置（fallback 用）"""
        from ..config.loop_presets import get_loop_preset
        return get_loop_preset(self.loop_type)

    # ---- 回路基础信息 ----

    def get_loop_type(self) -> str:
        """回路类型：优先 ontology_model，fallback process_context/loop_type"""
        if self.ontology_model and self.ontology_model.loop_type:
            return self.ontology_model.loop_type
        if self.process_context and self.process_context.get('loop_type'):
            return self.process_context['loop_type']
        return self.loop_type

    def get_process_nature(self) -> str:
        """过程性质（self_regulating / integrating）：优先 mechanism_model"""
        if self.mechanism_model:
            return self.mechanism_model.process_nature
        preset = self._get_preset()
        if preset.get('integrating_mode'):
            return 'integrating'
        return 'self_regulating'

    # ---- PID 约束参数 ----

    def get_pb_range(self) -> Tuple[float, float]:
        """PB 范围 [min, max]：优先 knowledge_model"""
        if self.knowledge_model and self.knowledge_model.pb_range:
            return tuple(self.knowledge_model.pb_range)
        preset = self._get_preset()
        return (preset.get('pb_min', 40.0), preset.get('pb_max', 300.0))

    def get_gain_range(self) -> Tuple[float, float]:
        """过程增益合理范围 [min, max]：优先 knowledge_model"""
        if self.knowledge_model and self.knowledge_model.gain_range:
            return tuple(self.knowledge_model.gain_range)
        return (0.1, 10.0)  # Config 默认值

    def get_td_enable(self) -> bool:
        """是否启用微分项：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.td_enable
        return self._get_preset().get('td_enable', False)

    def get_current_pid(self) -> Optional[Dict[str, float]]:
        """获取当前 DCS 中的 PID 参数，优先从 input_data 获取，否则从 process_context 获取"""
        if self.process_context and self.process_context.get('disable_current_pid_in_tuning'):
            return None
        if self.current_pid:
            return self.current_pid
        if self.process_context and self.process_context.get('current_pid'):
            pid = self.process_context['current_pid']
            return {
                'Kp': pid.get('kp', pid.get('Kp', 0.0)),
                'Ti': pid.get('ti', pid.get('Ti', 0.0)),
                'Td': pid.get('td', pid.get('Td', 0.0)),
                'action_type': pid.get('action_type', '')
            }
        return None

    def get_max_overshoot(self) -> float:
        """最大允许超调量（%）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.max_overshoot_percent
        return 10.0  # 默认 10%

    def get_tuning_strategy(self) -> str:
        """整定策略（conservative / aggressive）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.tuning_strategy
        preset = self._get_preset()
        return 'aggressive' if preset.get('aggressive', False) else 'conservative'

    # ---- 仿真模型参数 ----

    def get_preferred_model(self) -> str:
        """首选仿真模型结构：优先 mechanism_model"""
        if self.mechanism_model:
            return self.mechanism_model.preferred_simulation_model
        return 'FOPDT'

    def get_allowed_models(self) -> List[str]:
        """允许使用的仿真模型备选列表：优先 mechanism_model"""
        if self.mechanism_model and self.mechanism_model.allowed_simulation_models:
            return self.mechanism_model.allowed_simulation_models
        return ['FOPDT']

    def get_time_constant_range(self) -> Tuple[float, float]:
        """典型时间常数范围 [min, max]（秒）：优先 mechanism_model"""
        if self.mechanism_model:
            r = self.mechanism_model.typical_time_constant_range_s
            if r and len(r) == 2:
                return tuple(r)
        return (0.0, 9999.0)

    def get_dead_time_range(self) -> Tuple[float, float]:
        """典型纯滞后范围 [min, max]（秒）：优先 mechanism_model"""
        if self.mechanism_model:
            r = self.mechanism_model.typical_dead_time_range_s
            if r and len(r) == 2:
                return tuple(r)
        return (0.0, 9999.0)

    # ---- 安全/物理约束 ----

    def get_output_bounds(self) -> Tuple[float, float]:
        """PV 物理边界 [min, max]：优先 mechanism_model"""
        if self.mechanism_model:
            b = self.mechanism_model.output_physical_bounds
            if b and len(b) == 2:
                return tuple(b)
        return (0.0, 100.0)

    def get_coupling_risk(self) -> str:
        """耦合风险等级：优先 mechanism_model"""
        if self.mechanism_model:
            return self.mechanism_model.coupling_risk
        return 'none'

    def is_dead_time_dominant(self) -> bool:
        """是否为大纯滞后系统：优先 mechanism_model"""
        if self.mechanism_model:
            return self.mechanism_model.dead_time_dominant
        return False

    # ---- 整定策略参数（优先 knowledge_model → fallback loop_presets）----

    def get_tau_c_factor(self) -> float:
        """λ 调节系数（tau_c_factor）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.tau_c_factor
        return self._get_preset().get('tau_c_factor', 1.5)

    def get_safety_factor(self) -> float:
        """安全余量系数：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.safety_factor
        return self._get_preset().get('safety_factor', 1.05)

    def get_ti_multiplier(self) -> float:
        """积分时间乘数：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.ti_multiplier
        return self._get_preset().get('ti_multiplier', 1.0)

    def get_ti_max(self) -> float:
        """积分时间上限（秒）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.ti_max
        return self._get_preset().get('ti_max', 60.0)

    def get_overshoot_discount(self) -> float:
        """超调折扣系数（评分用）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.overshoot_discount
        return 1.0

    def get_settling_time_factor(self) -> float:
        """整定时间因子（评分用）：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.settling_time_factor
        return 3.0

    def get_oscillation_tolerance(self) -> float:
        """振荡容忍度：优先 knowledge_model"""
        if self.knowledge_model:
            return self.knowledge_model.oscillation_tolerance
        return 0.2

    def export_tuning_constraints(self) -> dict:
        """
        导出完整的整定约束字典（供底层无状态算子使用）。
        
        这是 OS 语义层 → 整定算法的核心桥接出口。
        优先级: OS 传入的语义模型(mechanism/knowledge/characterization)
               → 没有则 fallback 到 loop_presets 硬编码兜底。
        
        消费方: stage_03 (模型辨识), stage_05 (优化), stage_05b (自优化), stage_06 (输出)
        """
        preset = self._get_preset()
        pb_range = self.get_pb_range()
        tc_range = self.get_time_constant_range()
        dt_range = self.get_dead_time_range()
        ob_range = self.get_output_bounds()
        
        return {
            # ---- 基础 PID 约束 (knowledge_model → preset) ----
            'pb_min': pb_range[0],
            'pb_max': pb_range[1],
            'tau_c_factor': self.get_tau_c_factor(),
            'safety_factor': self.get_safety_factor(),
            'ti_multiplier': self.get_ti_multiplier(),
            'ti_max': self.get_ti_max(),
            'td_enable': self.get_td_enable(),
            'td_ratio': preset.get('td_ratio', 0.15),
            'td_max': preset.get('td_max', 999.0),
            'aggressive': self.get_tuning_strategy() == 'aggressive',
            
            # ---- 过程物理性质 (mechanism_model → preset) ----
            'process_nature': self.get_process_nature(),
            'integrating_mode': self.get_process_nature() == 'integrating',
            'preferred_model': self.get_preferred_model(),
            'allowed_models': self.get_allowed_models(),
            'coupling_risk': self.get_coupling_risk(),
            'dead_time_dominant': self.is_dead_time_dominant(),
            
            # ---- 物理范围约束 (mechanism_model → 宽松默认) ----
            'time_constant_min': tc_range[0],
            'time_constant_max': tc_range[1],
            'dead_time_min': dt_range[0],
            'dead_time_max': dt_range[1],
            'output_bound_min': ob_range[0],
            'output_bound_max': ob_range[1],
            
            # ---- 评分/策略约束 (knowledge_model → 默认) ----
            'max_overshoot': self.get_max_overshoot(),
            'tuning_strategy': self.get_tuning_strategy(),
            'overshoot_discount': self.get_overshoot_discount(),
            'settling_time_factor': self.get_settling_time_factor(),
            'oscillation_tolerance': self.get_oscillation_tolerance(),
            
            # ---- 表征特征 (characterization_model → 0.0 默认) ----
            'oscillation_ratio': self.get_oscillation_ratio(),
            'noise_level': self.get_noise_level(),
            'stiction_index': self.get_stiction_index(),
        }

    # ---- 表征特征（运行时回填）----

    def get_oscillation_ratio(self) -> float:
        """近期振荡比例：优先 characterization_model"""
        if self.characterization_model:
            return self.characterization_model.signal.oscillation_ratio
        return 0.0

    def get_noise_level(self) -> float:
        """噪声水平：优先 characterization_model"""
        if self.characterization_model:
            return self.characterization_model.signal.noise_level
        return 0.0

    def get_stiction_index(self) -> float:
        """阀门卡涩指数：优先 characterization_model"""
        if self.characterization_model:
            return self.characterization_model.valve.stiction_index_estimated
        return 0.0
