from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from core.algorithm.model_type.data_models import HistoricalData, SegmentResult, FusionResult, TuningInput
from core.models import StandardProcessModel, InstanceProcessModel, CharacterizationModel

@dataclass
class TuningContext:
    """
    整定流水线上下文 (Tuning Pipeline Context)
    
    用于在各个整定阶段 (Stage) 之间传递状态、数据和中间结果，
    消除原本在 `model_selector` 中的超级庞大的局部变量表。
    """
    # ---------------- 1. 外部输入 (Inputs) ----------------
    raw_data: List[Dict] = field(default_factory=list)
    input_data: Optional[TuningInput] = None
    tuning_input_raw: Any = None
    
    # 整定配置参数
    lambda_factor: float = 0.8
    current_pid: Optional[Dict[str, float]] = None
    process_context: Dict[str, Any] = field(default_factory=dict)
    
    # 语义模型 (New OS semantic models)
    standard_model: Optional[StandardProcessModel] = None
    instance_model: Optional[InstanceProcessModel] = None
    characterization_model: Optional[CharacterizationModel] = None
    
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
