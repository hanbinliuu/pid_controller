"""模型选择器模块 - 多模型拟合与参数融合协调器"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union
from scipy.optimize import least_squares

from .config import Config, ModelType
from .identifier import ModelIdentifier
from .fusion_strategy import PIDFusionStrategy, WindowResult as FusionWindowResult
from .data_preprocessor import DataPreprocessor
from .segment_validator import SegmentValidator, HistoricalData, TuningWindow
from .pid_calculator import PIDCalculator
from .model_evaluator import ModelEvaluator
from .utils import MetricsCalculator, TimestampParser, SimulationHelper


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class SegmentResult:
    """单个扰动段的拟合结果"""
    segment_idx: int
    start_idx: int
    end_idx: int
    data_points: int
    is_valid: bool
    invalid_reason: str = ""
    model_results: Dict[str, Dict] = field(default_factory=dict)
    best_model: str = ""
    best_r2: float = 0.0
    best_aic: float = float('inf')


@dataclass
class FusionResult:
    """参数融合结果"""
    model_type: str
    K: float = 0.0
    T1: float = 0.0
    T2: float = 0.0
    L: float = 0.0
    fusion_method: str = ""
    n_segments_used: int = 0
    segment_weights: List[float] = field(default_factory=list)
    K_std: float = 0.0
    T1_std: float = 0.0
    consistency_score: float = 0.0
    global_r2: float = 0.0
    global_rmse: float = 0.0


@dataclass
class TuningInput:
    """整定输入"""
    start_time: Any
    end_time: Any
    tuning_window: Optional[List[TuningWindow]] = None
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'TuningInput':
        windows = data.get('tuning_window', [])
        tuning_window = [
            TuningWindow(start_time=w.get('start_time'), end_time=w.get('end_time'))
            for w in windows
        ] if windows else None
        return cls(
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            tuning_window=tuning_window
        )


# ============================================================
# 模型选择器主类
# ============================================================

class ModelSelector:
    """
    模型类型选择器 - 协调器模式
    
    核心流程：
    1. 剔除无效/扰动段 → 有效段筛选 (SegmentValidator)
    2. 对每个有效段尝试多种模型拟合 → 获取各段各模型的KTL
    3. 基于AIC/RSS/形状特征选择最优模型结构 → 确定模型类型
    4. 融合各段参数 → 唯一K, T, L (PIDFusionStrategy)
    5. 验证一致性与仿真匹配度 → 最终输出 (ModelEvaluator)
    """
    
    # 候选模型
    CANDIDATE_MODELS = [
        ModelType.FOPDT,
        ModelType.FO,
        ModelType.SO,
        ModelType.SOPDT,
        ModelType.FOPI,
    ]
    
    # 模型参数数量（用于AIC/BIC计算）
    MODEL_PARAM_COUNT = {
        ModelType.FOPDT: 3,
        ModelType.FO: 2,
        ModelType.SO: 3,
        ModelType.SOPDT: 4,
        ModelType.FOPI: 2,
    }
    
    # 参数格式化
    PARAM_FORMATS = {
        ModelType.FOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': p[2]},
        ModelType.FO: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': 0.0},
        ModelType.SO: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': 0.0},
        ModelType.SOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': p[3]},
        ModelType.FOPI: lambda p: {'K': p[0], 'T1': 0.0, 'T2': 0.0, 'L': p[1]},
    }
    
    # 模型辨识方法
    IDENTIFY_METHODS = {
        ModelType.FOPDT: ModelIdentifier.identify_fopdt,
        ModelType.FO: ModelIdentifier.identify_first_order,
        ModelType.SO: ModelIdentifier.identify_second_order,
        ModelType.SOPDT: ModelIdentifier.identify_sopdt,
        ModelType.FOPI: ModelIdentifier.identify_integral_delay,
    }
    
    # 模型仿真方法
    SIMULATE_METHODS = {
        ModelType.FOPDT: ModelIdentifier.fopdt_model,
        ModelType.FO: ModelIdentifier.first_order_model,
        ModelType.SO: ModelIdentifier.second_order_model,
        ModelType.SOPDT: ModelIdentifier.sopdt_model,
        ModelType.FOPI: ModelIdentifier.integral_delay_model,
    }
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        
        # 组件初始化
        self._preprocessor = DataPreprocessor(verbose=verbose)
        self._segment_validator = SegmentValidator(verbose=verbose)
        self._pid_calculator = PIDCalculator()
        self._evaluator = ModelEvaluator(verbose=verbose)
    
    @property
    def verbose(self) -> bool:
        return self._verbose
    
    def log(self, msg: str):
        if self._verbose:
            print(msg)
    
    # ============================================================
    # 主入口（新格式）
    # ============================================================
    
    def run(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        模型整定主入口（新格式）
        
        Args:
            input_data: 输入数据字典，格式为:
                {
                    "history_data": [
                        {"timestamp": 1764752401000, "sv": 3, "pv": 1.9, "mv": 8.742, ...},
                        ...
                    ],
                    "params": {
                        "model_type": None,        # 可选，强制使用指定模型
                        "turning_type": None,      # 可选，整定类型
                        "analyst_column": "pv"     # 可选，分析列
                    },
                    "qualified_windows": [
                        {"start_time": 1764766845007, "end_time": 1764774045007},
                        ...
                    ]
                }
        
        Returns:
            整定结果字典
        """
        # 解析输入
        history_data = input_data.get('history_data', [])
        params = input_data.get('params', {})
        qualified_windows = input_data.get('qualified_windows', [])
        
        if not history_data:
            return self._empty_result_new(params)
        
        if not qualified_windows:
            return self._empty_result_new(params)
        
        # 转换为内部格式
        tuning_input = {
            'start_time': history_data[0].get('timestamp') if history_data else None,
            'end_time': history_data[-1].get('timestamp') if history_data else None,
            'tuning_window': [
                {'start_time': w.get('start_time'), 'end_time': w.get('end_time')}
                for w in qualified_windows
            ]
        }
        
        # 调用原有的 fit 方法
        result = self.fit(tuning_input, history_data, lambda_factor=0.8)
        
        # 转换为新输出格式
        return self._convert_output_format(result, params)
    
    def _convert_output_format(self, result: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        """转换为新输出格式"""
        # 计算评分等级
        r_squared = result.get('fitting_result', {}).get('r_squared', 0)
        model_rating = result.get('model_rating', 0)
        recommendation = self._get_recommendation(model_rating)
        
        # 获取 PID 参数并转换格式
        pid_params = result.get('pid_parameters', {})
        Kp = pid_params.get('Kp', 1.0)
        Ki = pid_params.get('Ki', 0.0)
        Kd = pid_params.get('Kd', 0.0)
        
        # 计算 pb, ti, td
        Ti = Kp / Ki if Ki > self._epsilon else 0.0
        Td = Kd / Kp if Kp > self._epsilon else 0.0
        Pb = 100.0 / Kp if Kp > self._epsilon else 100.0
        
        # 确定整定类型
        turning_type = params.get('turning_type') or self._determine_turning_type(Kp, Ti, Td)
        
        # 构建新格式输出
        fitting_result = result.get('fitting_result', {})
        fitting_result['recommendation'] = recommendation
        
        return {
            'model_type': result.get('model_type', 'FOPDT'),
            'turning_type': turning_type,
            'model_rating': model_rating,
            'start_time': result.get('start_time'),
            'end_time': result.get('end_time'),
            'model_parameters': result.get('model_parameters', {}),
            'pid_parameters': {
                'pb': round(float(Pb), 4),
                'ti': round(float(Ti), 4),
                'td': round(float(Td), 4),
                'kp': round(float(Kp), 4),
                'ki': round(float(Ki), 4),
                'kd': round(float(Kd), 4)
            },
            'fitting_result': fitting_result
        }
    
    def _get_recommendation(self, model_rating: float) -> str:
        """根据评分获取推荐等级（委托给ModelEvaluator）"""
        return self._evaluator.get_recommendation(model_rating)
    
    def _determine_turning_type(self, Kp: float, Ti: float, Td: float) -> str:
        """根据 PID 参数确定整定类型（委托给PIDCalculator）"""
        return self._pid_calculator.determine_tuning_type(Kp, Ti, Td)
    
    def _empty_result_new(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """新格式空结果"""
        return {
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
            lambda_factor: float = 0.8) -> Dict[str, Any]:
        """
        模型整定主入口
        
        Args:
            tuning_input: 整定输入（包含tuning_window列表）
            raw_data: 原始时序数据
            lambda_factor: Lambda整定系数
        
        Returns:
            整定结果字典
        """
        # 解析输入
        input_data = self._parse_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result(input_data)
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        self.log(f"📥 输入: {len(input_data.tuning_window)} 个扰动窗口, {len(raw_data)} 条数据")
        
        # ============================================================
        # Step 1: 剔除无效扰动段
        # ============================================================
        segments = self._extract_segments(hist_data, input_data.tuning_window)
        valid_segments, segment_results = self._filter_invalid_segments(segments)
        
        if not valid_segments:
            self.log("⚠️ 无有效扰动段")
            return self._empty_result(input_data)
        
        self.log(f"📊 有效扰动段: {len(valid_segments)}/{len(segments)}")
        
        # ============================================================
        # Step 2: 对每个有效段尝试多种模型拟合
        # ============================================================
        segment_results = self._fit_all_segments(valid_segments, segment_results)
        
        # ============================================================
        # Step 3: 基于AIC/RSS/形状特征选择最优模型结构
        # ============================================================
        best_model_type = self._select_best_model_type(segment_results)
        self.log(f"🎯 选择模型类型: {best_model_type}")
        
        # ============================================================
        # Step 4: 融合各段参数 → 唯一K, T, L
        # ============================================================
        fusion_result = self._fuse_parameters(segment_results, best_model_type)
        
        # ============================================================
        # Step 5: 验证一致性与仿真匹配度
        # ============================================================
        fusion_result = self._validate_and_refine(fusion_result, valid_segments, hist_data)
        
        # ============================================================
        # 构建最终输出
        # ============================================================
        # 传递segment_results以便PIECEWISE模型使用分段拟合的y_pred
        return self._build_output(fusion_result, hist_data, time_range, lambda_factor, segment_results)
    
    # ============================================================
    # Step 1: 剔除无效扰动段
    # ============================================================
    
    def _extract_segments(self, hist_data: HistoricalData, 
                          windows: List[TuningWindow]) -> List[HistoricalData]:
        """提取所有扰动段数据"""
        segments = []
        timestamps = hist_data.timestamp
        
        for i, w in enumerate(windows):
            start_ts = self._parse_timestamp(w.start_time)
            end_ts = self._parse_timestamp(w.end_time)
            
            if start_ts is None or end_ts is None:
                continue
            
            mask = (timestamps >= start_ts) & (timestamps <= end_ts)
            indices = np.where(mask)[0]
            
            if len(indices) < 10:
                continue
            
            segment = HistoricalData(
                timestamp=hist_data.timestamp[indices],
                pv=hist_data.pv[indices],
                sv=hist_data.sv[indices],
                mv=hist_data.mv[indices]
            )
            segments.append(segment)
        
        return segments
    
    def _filter_invalid_segments(self, segments: List[HistoricalData]
                                  ) -> Tuple[List[HistoricalData], List[SegmentResult]]:
        """
        过滤无效扰动段
        
        无效条件：
        1. 数据点过少 (< 20)
        2. PV变化过小（无响应）
        3. MV变化过小（无激励）
        4. PV=0 异常点过多
        5. 数据趋势不合理（非阶跃响应特征）
        """
        valid_segments = []
        segment_results = []
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 1: 扰动段有效性检查")
        self.log('='*60)
        
        for i, seg in enumerate(segments):
            result = SegmentResult(
                segment_idx=i,
                start_idx=0,
                end_idx=len(seg),
                data_points=len(seg),
                is_valid=True
            )
            
            # 检查1: 数据点数
            if len(seg) < Config.MIN_DATA_POINTS:
                self._mark_invalid(result, f"数据点不足({len(seg)}<{Config.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            # 过滤PV=0的点
            valid_mask = seg.pv != 0
            valid_count = np.sum(valid_mask)
            
            if valid_count < Config.MIN_DATA_POINTS:
                self._mark_invalid(result, f"有效点不足({valid_count}<{Config.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            y, u = seg.pv[valid_mask], seg.mv[valid_mask]
            pv_range, mv_range = np.ptp(y), np.ptp(u)  # ptp = max - min
            
            # 检查2: PV变化
            if pv_range < Config.MIN_PV_RANGE and np.std(y) < 0.1:
                self._mark_invalid(result, f"PV无变化(range={pv_range:.2f})", i, segment_results)
                continue
            
            # 检查3: MV变化
            if mv_range < Config.MIN_MV_RANGE:
                self._mark_invalid(result, f"MV无变化(range={mv_range:.2f})", i, segment_results)
                continue
            
            # 检查4: 阶跃响应形状特征
            shape_valid, shape_reason = self._check_step_response_shape(y, u)
            if not shape_valid:
                result.is_valid = False
                result.invalid_reason = shape_reason
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
                continue
            
            # 有效段
            result.is_valid = True
            result.data_points = valid_count
            self.log(f"   段{i+1}: ✓ 有效 ({valid_count}点, PV范围={pv_range:.2f}, MV范围={mv_range:.2f})")
            
            valid_segments.append(seg)
            segment_results.append(result)
        
        return valid_segments, segment_results
    
    def _check_step_response_shape(self, y: np.ndarray, u: np.ndarray) -> Tuple[bool, str]:
        """
        检查是否具有阶跃响应的基本形状特征
        
        Returns:
            (is_valid, reason)
        """
        n = len(y)
        if n < 20:
            return False, "数据太短"
        
        # 计算相关系数
        try:
            corr = np.corrcoef(u, y)[0, 1]
            if np.isnan(corr):
                corr = 0.0
        except:
            corr = 0.0
        
        # 允许正相关或负相关（正向/反向作用系统）
        if abs(corr) < 0.1:
            # 检查是否是积分过程（累积效应）
            y_cumsum = np.cumsum(u - np.mean(u))
            try:
                corr_cumsum = np.corrcoef(y_cumsum, y)[0, 1]
                if np.isnan(corr_cumsum):
                    corr_cumsum = 0.0
            except:
                corr_cumsum = 0.0
            
            if abs(corr_cumsum) < 0.2:
                return False, f"无明显响应(corr={corr:.2f})"
        
        return True, ""
    
    # ============================================================
    # Step 2: 对每个有效段尝试多种模型拟合
    # ============================================================
    
    def _fit_all_segments(self, segments: List[HistoricalData],
                          segment_results: List[SegmentResult]) -> List[SegmentResult]:
        """对每个有效段拟合所有候选模型"""
        
        self.log(f"\n{'='*60}")
        self.log("📊 Step 2: 多模型拟合")
        self.log('='*60)
        
        valid_idx = 0
        for i, result in enumerate(segment_results):
            if not result.is_valid:
                continue
            
            seg = segments[valid_idx]
            valid_idx += 1
            
            # 准备数据
            valid_mask = seg.pv != 0
            y = seg.pv[valid_mask]
            u = seg.mv[valid_mask]
            t = np.arange(len(y), dtype=float)
            y0 = y[0]
            
            # 计算理论K值范围（用于校验和约束）
            pv_range = np.max(y) - np.min(y)
            mv_range = np.max(u) - np.min(u)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 0.1 else 1.0
            # K值合理范围: 理论值的0.1x ~ 5x
            k_min = k_expected * 0.1
            k_max = k_expected * 5.0
            
            self.log(f"\n📊 段{i+1}: {len(y)}点")
            
            # 分析数据质量（使用 DataPreprocessor）
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated
            
            # 非线性分析
            nonlinearity = self._preprocessor.analyze_nonlinearity(y, u)
            if nonlinearity.is_nonlinear:
                self.log(f"   ⚠️ 检测到非线性特征: {nonlinearity.description}")
                # 保存非线性信息到result
                result.model_results['_nonlinearity'] = {
                    'is_nonlinear': nonlinearity.is_nonlinear,
                    'score': nonlinearity.nonlinearity_score,
                    'gain_variation': nonlinearity.gain_variation,
                    'recommended_model': nonlinearity.recommended_model,
                    'segment_count': nonlinearity.segment_count
                }
            
            # 尝试所有候选模型
            for model_type in self.CANDIDATE_MODELS:
                try:
                    # 根据数据质量选择拟合策略
                    if use_multi_start:
                        params_raw, _ = self._multi_start_fit(t, y, u, model_type)
                    else:
                        method = self.IDENTIFY_METHODS.get(model_type)
                        params_raw = method(t, y, u)
                    
                    # 格式化参数
                    params_dict = self.PARAM_FORMATS[model_type](params_raw)
                    
                    # 仿真
                    sim_method = self.SIMULATE_METHODS.get(model_type)
                    y_pred = sim_method(params_raw, t, u, y0)
                    
                    # 计算评估指标
                    r2 = self._calculate_r2(y, y_pred)
                    rss = self._calculate_rss(y, y_pred)
                    n_params = self.MODEL_PARAM_COUNT[model_type]
                    aic = self._calculate_aic(rss, len(y), n_params)
                    bic = self._calculate_bic(rss, len(y), n_params)
                    
                    # 检查K值是否在合理范围内
                    fitted_k = abs(params_dict['K'])
                    k_reasonable = k_min <= fitted_k <= k_max
                    
                    # 如果K值不合理，降低该模型的可信度
                    if not k_reasonable and r2 > 0:
                        r2_adjusted = r2 * 0.3  # 大幅降权
                        self.log(f"   {model_type}: K={params_dict['K']:.4f} 超出合理范围[{k_min:.4f}, {k_max:.4f}], R²降权")
                    else:
                        r2_adjusted = r2
                    
                    result.model_results[model_type] = {
                        'K': params_dict['K'],
                        'T1': params_dict['T1'],
                        'T2': params_dict['T2'],
                        'L': params_dict['L'],
                        'params_raw': params_raw,
                        'r2': r2,
                        'r2_adjusted': r2_adjusted,  # 调整后的R²
                        'rss': rss,
                        'aic': aic,
                        'bic': bic,
                        'y_pred': y_pred,
                        'k_expected': k_expected,
                        'k_reasonable': k_reasonable
                    }
                    
                    k_flag = "✓" if k_reasonable else "✗"
                    self.log(f"   {model_type}: R²={r2:.4f}, AIC={aic:.1f}, "
                             f"K={params_dict['K']:.4f} {k_flag}, T1={params_dict['T1']:.2f}")
                    
                except Exception as e:
                    self.log(f"   {model_type}: 拟合失败 - {e}")
                    result.model_results[model_type] = {
                        'r2': 0.0, 'rss': float('inf'), 'aic': float('inf')
                    }
            
            # 选择该段的最佳模型（优先选择K值合理且R²高的）
            if result.model_results:
                # 优先选择K值合理且R²>=0.4的模型
                valid_models = {m: r for m, r in result.model_results.items() 
                               if r.get('r2_adjusted', r.get('r2', 0)) >= 0.4 and r.get('k_reasonable', True)}
                
                if valid_models:
                    # 使用调整后的R²选择最佳模型
                    best_model = max(valid_models.keys(),
                                    key=lambda m: valid_models[m].get('r2_adjusted', 0))
                    result.best_model = best_model
                    # 修复：保存调整后的R²，保持一致性
                    result.best_r2 = result.model_results[best_model].get('r2_adjusted', 
                                                                          result.model_results[best_model].get('r2', 0))
                    result.best_aic = result.model_results[best_model].get('aic', float('inf'))
                else:
                    # 没有满足条件的，选调整后R²最高的
                    best_model = max(result.model_results.keys(),
                                    key=lambda m: result.model_results[m].get('r2_adjusted', 
                                                  result.model_results[m].get('r2', 0)))
                    result.best_model = best_model
                    # 修复：保存调整后的R²，保持一致性
                    result.best_r2 = result.model_results[best_model].get('r2_adjusted',
                                                                          result.model_results[best_model].get('r2', 0))
                    result.best_aic = result.model_results[best_model].get('aic', float('inf'))
                
                # 触发PIECEWISE分段拟合的条件（移到if/else外面，确保始终检查）：
                # 1. R²<0.4 且检测到非线性
                # 2. 或者非线性评分>=0.25（检测到非线性即尝试）
                should_try_piecewise = (
                    nonlinearity.is_nonlinear and 
                    (result.best_r2 < 0.4 or nonlinearity.nonlinearity_score >= 0.25)
                )
                
                if should_try_piecewise:
                    reason = "R²<0.4" if result.best_r2 < 0.4 else f"非线性评分={nonlinearity.nonlinearity_score:.2f}"
                    self.log(f"   ⚠️ 段{i+1}尝试分段拟合（{reason}）")
                    # 确定分段数：如果推荐分段=1但有非线性，强制尝试3段
                    n_segments = nonlinearity.segment_count if nonlinearity.segment_count > 1 else 3
                    self.log(f"   → 尝试分段线性拟合 ({n_segments}段)...")
                    piecewise_result = self._try_piecewise_fit(y, u, t, y0, n_segments)
                    if piecewise_result is not None:
                        result.model_results['PIECEWISE'] = piecewise_result
                        if piecewise_result['r2'] > result.best_r2:
                            result.best_model = 'PIECEWISE'
                            result.best_r2 = piecewise_result['r2']
                            self.log(f"   ✓ 分段拟合R²={piecewise_result['r2']:.4f}")
                        else:
                            self.log(f"   ✗ 分段拟合R²={piecewise_result['r2']:.4f}未改善")
        
        return segment_results
    
    def _try_piecewise_fit(self, y: np.ndarray, u: np.ndarray, t: np.ndarray,
                           y0: float, n_segments: int) -> Optional[Dict]:
        """
        尝试分段线性拟合
        
        将数据按工作点分成多段，每段独立拟合FOPDT模型，
        然后组合成分段线性模型。
        
        Args:
            y: PV数据
            u: MV数据
            t: 时间数组
            y0: 初始值
            n_segments: 分段数
        
        Returns:
            拟合结果字典，包含分段参数和整体R²
        """
        try:
            # 方案1: 按PV值分段
            segments = self._preprocessor.segment_for_nonlinear(y, u, n_segments)
            
            # 方案2: 按时间分段（如果按PV分段失败或效果不好）
            if len(segments) < 2:
                self.log(f"      按PV分段不足，尝试按时间分段")
                segments = self._segment_by_time(y, u, n_segments)
            
            if len(segments) < 2:
                self.log(f"      分段数不足")
                return None
            
            self.log(f"      分成{len(segments)}段进行拟合")
            
            segment_params = []
            segment_r2s = []
            
            for i, seg_data in enumerate(segments):
                # 兼容两种分段格式
                if len(seg_data) == 4:
                    seg_y, seg_u, pv_center, indices = seg_data
                else:
                    seg_y, seg_u, start_idx, end_idx = seg_data
                    pv_center = np.mean(seg_y)
                    indices = np.arange(start_idx, end_idx)
                
                if len(seg_y) < 20:
                    self.log(f"      段{i+1}: 数据点不足({len(seg_y)})")
                    continue
                
                seg_t = np.arange(len(seg_y), dtype=float)
                seg_y0 = seg_y[0]
                
                # 对每段独立拟合FOPDT
                try:
                    params = ModelIdentifier.identify_fopdt(seg_t, seg_y, seg_u)
                    y_pred = ModelIdentifier.fopdt_model(params, seg_t, seg_u, seg_y0)
                    r2 = self._calculate_r2(seg_y, y_pred)
                    
                    self.log(f"      段{i+1}: K={params[0]:.4f}, T1={params[1]:.2f}, R²={r2:.4f}")
                    
                    segment_params.append({
                        'pv_center': pv_center,
                        'pv_range': (np.min(seg_y), np.max(seg_y)),
                        'K': params[0],
                        'T1': params[1],
                        'L': params[2],
                        'r2': r2,
                        'n_points': len(seg_y),
                        'indices': indices
                    })
                    segment_r2s.append(r2)
                except Exception as e:
                    self.log(f"      段{i+1}: 拟合失败 - {e}")
                    continue
            
            if len(segment_params) < 1:
                self.log(f"      无有效分段")
                return None
            
            # 如果只有1个有效段，直接使用该段参数
            if len(segment_params) == 1:
                p = segment_params[0]
                return {
                    'K': p['K'],
                    'T1': p['T1'],
                    'T2': 0.0,
                    'L': p['L'],
                    'r2': p['r2'],
                    'rss': 0.0,
                    'aic': 0.0,
                    'y_pred': None,
                    'segment_params': segment_params,
                    'segment_r2s': segment_r2s,
                    'is_piecewise': True
                }
            
            # 计算整体拟合效果（使用分段仿真）
            y_pred_all = self._simulate_piecewise_by_indices(segment_params, y, u)
            overall_r2 = self._calculate_r2(y, y_pred_all)
            overall_rmse = self._calculate_rmse(y, y_pred_all)
            
            self.log(f"      整体R²={overall_r2:.4f}")
            
            # 计算加权平均参数（用于PID计算）
            # 优化：同时考虑数据点数和拟合质量
            weights = np.array([
                p['n_points'] * (p['r2'] ** 2)  # R²平方，让高质量段权重更大
                for p in segment_params
            ], dtype=float)
            
            # 避免权重全为0
            if weights.sum() < 1e-8:
                weights = np.array([p['n_points'] for p in segment_params], dtype=float)
            
            weights /= weights.sum()
            
            avg_K = sum(p['K'] * w for p, w in zip(segment_params, weights))
            avg_T1 = sum(p['T1'] * w for p, w in zip(segment_params, weights))
            avg_L = sum(p['L'] * w for p, w in zip(segment_params, weights))
            
            return {
                'K': avg_K,
                'T1': avg_T1,
                'T2': 0.0,
                'L': avg_L,
                'r2': overall_r2,
                'r2_adjusted': overall_r2,  # 添加r2_adjusted字段
                'rss': self._calculate_rss(y, y_pred_all),
                'aic': self._calculate_aic(self._calculate_rss(y, y_pred_all), len(y), 3 * len(segment_params)),
                'y_pred': y_pred_all,
                'segment_params': segment_params,
                'segment_r2s': segment_r2s,
                'is_piecewise': True,
                'k_reasonable': True  # PIECEWISE模型默认K值合理
            }
            
        except Exception as e:
            self.log(f"   分段拟合失败: {e}")
            import traceback
            self.log(f"   {traceback.format_exc()}")
            return None
    
    def _segment_by_time(self, y: np.ndarray, u: np.ndarray, 
                          n_segments: int) -> list:
        """按时间均匀分段"""
        n = len(y)
        segment_size = n // n_segments
        segments = []
        
        for i in range(n_segments):
            start = i * segment_size
            end = (i + 1) * segment_size if i < n_segments - 1 else n
            
            if end - start >= 20:
                segments.append((y[start:end], u[start:end], start, end))
        
        return segments
    
    def _simulate_piecewise_by_indices(self, segment_params: List[Dict], 
                                        y: np.ndarray, u: np.ndarray) -> np.ndarray:
        """
        使用分段参数按索引进行仿真
        
        优化：
        1. 按时间顺序仿真，保持状态连续性
        2. 使用前一段的最终状态作为下一段的初值
        3. 在段边界处进行平滑过渡（加权平均）
        4. 处理段间重叠区域
        """
        n = len(y)
        y_pred = np.zeros(n)
        weights_map = np.zeros(n)  # 记录每个点的权重累积
        
        # 按索引起始位置排序，确保时间顺序
        sorted_params = sorted(segment_params, key=lambda p: np.min(p.get('indices', [n])))
        
        last_y_pred = None  # 上一段的最终预测值
        last_indices = None  # 上一段的索引
        
        for i, p in enumerate(sorted_params):
            indices = p.get('indices')
            if indices is None or len(indices) == 0:
                continue
            
            # 确保indices是有序的
            indices = np.sort(indices)
            
            # 获取该段数据
            seg_y = y[indices]
            seg_u = u[indices]
            seg_t = np.arange(len(seg_y), dtype=float)
            
            # 优化：使用前一段的最终状态作为初值（如果有的话）
            if last_y_pred is not None and i > 0:
                seg_y0 = last_y_pred
            else:
                seg_y0 = seg_y[0]
            
            # 使用该段的参数进行仿真
            params = (p['K'], p['T1'], p['L'])
            seg_pred = ModelIdentifier.fopdt_model(params, seg_t, seg_u, seg_y0)
            
            # 检测与上一段的重叠区域
            overlap_start = None
            overlap_end = None
            if last_indices is not None and len(last_indices) > 0:
                overlap = np.intersect1d(last_indices, indices)
                if len(overlap) > 0:
                    overlap_start = overlap[0]
                    overlap_end = overlap[-1]
            
            # 填充预测值（处理重叠区域的平滑过渡）
            for j, idx in enumerate(indices):
                if j >= len(seg_pred):
                    continue
                
                # 如果在重叠区域，使用加权平均
                if overlap_start is not None and overlap_start <= idx <= overlap_end:
                    # 计算权重：离边界越近，权重越小
                    if overlap_end > overlap_start:
                        alpha = (idx - overlap_start) / (overlap_end - overlap_start)
                    else:
                        alpha = 0.5
                    
                    # 加权融合：当前段权重alpha，上一段权重(1-alpha)
                    if weights_map[idx] > 0:  # 已有预测值
                        y_pred[idx] = (1 - alpha) * y_pred[idx] + alpha * seg_pred[j]
                    else:
                        y_pred[idx] = seg_pred[j]
                        weights_map[idx] = 1.0
                else:
                    # 非重叠区域，直接使用
                    if weights_map[idx] == 0:  # 避免覆盖
                        y_pred[idx] = seg_pred[j]
                        weights_map[idx] = 1.0
            
            # 保存最终状态和索引
            if len(seg_pred) > 0:
                last_y_pred = seg_pred[-1]
            last_indices = indices
        
        return y_pred
    
    
    # ============================================================
    # Step 3: 基于AIC/RSS/形状特征选择最优模型结构
    # ============================================================
    
    def _select_best_model_type(self, segment_results: List[SegmentResult]) -> str:
        """
        选择最优模型结构
        
        策略：
        1. 只统计R²>=0.5的高质量段
        2. 使用投票法选择整体最优模型
        3. R²权重最高
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 3: 模型结构选择")
        self.log('='*60)
        
        # 统计各模型的得分（包括PIECEWISE）
        all_model_types = list(self.CANDIDATE_MODELS) + ['PIECEWISE']
        model_r2_scores = {m: [] for m in all_model_types}
        model_votes = {m: 0 for m in all_model_types}
        
        valid_results = [r for r in segment_results if r.is_valid and r.model_results]
        
        if not valid_results:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        # 检查是否有非线性检测结果
        has_nonlinear = any(
            r.model_results.get('_nonlinearity', {}).get('is_nonlinear', False)
            for r in valid_results
        )
        
        # 统计高质量段数
        high_quality_count = 0
        
        for result in valid_results:
            # 收集R²（排除非线性信息字段）
            # 优化：只收集best_model的R²，避免差模型污染平均值
            if result.best_model and not result.best_model.startswith('_'):
                # 使用调整后的R²（如果有的话）
                best_fit = result.model_results.get(result.best_model, {})
                r2 = best_fit.get('r2_adjusted', best_fit.get('r2', 0))
                if r2 >= Config.MIN_R2_FOR_VOTE:
                    model_r2_scores[result.best_model].append(r2)
            
            # 只有高质量段才投票
            if result.best_r2 >= Config.MIN_R2_FOR_VOTE and result.best_model:
                model_votes[result.best_model] += 1
                high_quality_count += 1
        
        self.log(f"\n   高质量段(R²≥{Config.MIN_R2_FOR_VOTE}): {high_quality_count}/{len(valid_results)}")
        
        # 计算各模型的平均R²
        self.log("\n   模型评估汇总:")
        self.log(f"   {'模型':<15} | {'平均R²':>10} | {'有效段':>6} | {'投票':>6} | {'综合分':>10}")
        self.log("   " + "-" * 60)
        
        model_composite_scores = {}
        
        for model_type in all_model_types:
            r2_scores = model_r2_scores.get(model_type, [])
            votes = model_votes.get(model_type, 0)
            
            if r2_scores:
                avg_r2 = np.mean(r2_scores)
                n_valid = len(r2_scores)
                
                # 综合得分: R² 70%, 投票 30%
                vote_normalized = votes / max(high_quality_count, 1)
                composite = 0.7 * avg_r2 + 0.3 * vote_normalized
                
                # 如果是PIECEWISE且检测到非线性，给予额外加分
                if model_type == 'PIECEWISE' and has_nonlinear:
                    composite *= 1.1  # 10%加成
                
                model_composite_scores[model_type] = composite
                
                self.log(f"   {model_type:<15} | {avg_r2:>10.4f} | {n_valid:>6} | {votes:>6} | {composite:>10.4f}")
            else:
                # 没有高质量段，用所有段的平均R²但降权
                all_r2 = [r.model_results.get(model_type, {}).get('r2', 0) 
                         for r in valid_results if r.model_results.get(model_type)]
                if all_r2:
                    avg_r2 = np.mean(all_r2) * 0.5  # 降权50%
                    model_composite_scores[model_type] = avg_r2
                    self.log(f"   {model_type:<15} | {np.mean(all_r2):>10.4f}* | {0:>6} | {votes:>6} | {avg_r2:>10.4f}")
        
        # 选择综合得分最高的模型
        if model_composite_scores:
            best_model = max(model_composite_scores.keys(), 
                           key=lambda m: model_composite_scores[m])
            best_score = model_composite_scores[best_model]
            
            # 如果最高分也很低，警告
            if best_score < 0.4:
                self.log(f"\n   ⚠️ 所有模型拟合质量都较差")
        else:
            best_model = ModelType.FOPDT
        
        self.log(f"\n   → 选择模型: {best_model}")
        return best_model
    
    # ============================================================
    # Step 4: 融合各段参数 → 唯一K, T, L
    # ============================================================
    
    def _fuse_parameters(self, segment_results: List[SegmentResult],
                         model_type: str) -> FusionResult:
        """
        融合各段参数，得到唯一的K, T, L
        
        使用 PIDFusionStrategy 进行智能融合，策略包括：
        - weighted_fusion: R²加权融合（K一致性好时）
        - best_window: 最佳窗口（K有差异时）
        - conservative: 保守选择（K差异大时）
        - robust_fusion: 鲁棒融合（数据量差异大时）
        - cross_validation: 交叉验证（多窗口时）
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 4: 参数融合")
        self.log('='*60)
        
        fusion = FusionResult(model_type=model_type)
        
        # Step 1: 收集所有有效段的参数（降低阈值逐级尝试）
        window_results = []
        added_indices = set()
        
        for threshold in Config.R2_THRESHOLDS:
            for result in segment_results:
                if not result.is_valid or result.segment_idx in added_indices:
                    continue
                
                fit_result = result.model_results.get(model_type)
                if fit_result is None:
                    continue
                
                # 优化：使用调整后的R²（如果有的话），保持与Step 2一致
                r2 = fit_result.get('r2_adjusted', fit_result.get('r2', 0))
                if r2 < threshold:
                    continue
                
                K, T1 = fit_result.get('K', 0), fit_result.get('T1', 0)
                if K == 0 and T1 == 0:  # 跳过无效参数
                    continue
                
                window_results.append(FusionWindowResult(
                    window_idx=result.segment_idx,
                    K=K, T1=T1, 
                    T2=fit_result.get('T2', 0), 
                    L=fit_result.get('L', 0),
                    r2=r2,
                    data_points=result.data_points
                ))
                added_indices.add(result.segment_idx)
            
            if window_results:
                if threshold < Config.R2_THRESHOLDS[0]:
                    self.log(f"   ⚠️ 使用阈值 R²≥{threshold} 收集到 {len(window_results)} 个有效段")
                break
        
        if not window_results:
            self.log("   ⚠️ 无有效参数，使用默认值")
            return fusion
        
        self.log(f"   收集到 {len(window_results)} 个有效段:")
        for w in window_results:
            self.log(f"      段{w.window_idx+1}: K={w.K:.4f}, T1={w.T1:.2f}, R²={w.r2:.3f}, 数据点={w.data_points}")
        
        # Step 2: 使用 PIDFusionStrategy 进行智能融合
        try:
            fusion_strategy = PIDFusionStrategy(verbose=self._verbose)
            fusion_result = fusion_strategy.fuse(window_results)
            
            # 转换结果
            fusion.K = fusion_result.K
            fusion.T1 = fusion_result.T1
            fusion.T2 = fusion_result.T2
            fusion.L = fusion_result.L
            fusion.fusion_method = fusion_result.strategy_used.value
            fusion.consistency_score = fusion_result.confidence
            fusion.n_segments_used = len(fusion_result.windows_used)
            
            # 计算标准差
            if len(window_results) > 1:
                fusion.K_std = float(np.std([w.K for w in window_results]))
                fusion.T1_std = float(np.std([w.T1 for w in window_results]))
            else:
                fusion.K_std = 0.0
                fusion.T1_std = 0.0
            
            self.log(f"\n   融合策略: {fusion.fusion_method}")
            self.log(f"   决策原因: {fusion_result.reasoning}")
            self.log(f"   使用窗口: {[i+1 for i in fusion_result.windows_used]}")
            
        except Exception as e:
            self.log(f"   ⚠️ PIDFusionStrategy 失败: {e}，使用备用逻辑")
            # 备用逻辑：简单取最佳R²的段
            best_window = max(window_results, key=lambda w: w.r2)
            fusion.K = best_window.K
            fusion.T1 = best_window.T1
            fusion.T2 = best_window.T2
            fusion.L = best_window.L
            fusion.fusion_method = "best_window_fallback"
            fusion.consistency_score = best_window.r2
            fusion.n_segments_used = 1
            fusion.K_std = 0.0
            fusion.T1_std = 0.0
        
        self.log(f"\n   融合结果 ({fusion.fusion_method}, {fusion.n_segments_used}段):")
        self.log(f"   K  = {fusion.K:.4f} ± {fusion.K_std:.4f}")
        self.log(f"   T1 = {fusion.T1:.2f} ± {fusion.T1_std:.2f}")
        self.log(f"   T2 = {fusion.T2:.2f}")
        self.log(f"   L  = {fusion.L:.2f}")
        self.log(f"   一致性评分: {fusion.consistency_score:.2f}")
        
        return fusion
    
    # ============================================================
    # Step 5: 验证一致性与仿真匹配度
    # ============================================================
    
    def _validate_and_refine(self, fusion: FusionResult,
                              segments: List[HistoricalData],
                              hist_data: HistoricalData) -> FusionResult:
        """
        验证融合参数，必要时进行全局优化
        
        优化策略：
        1. 首先在全量数据上计算R²
        2. 如果R² < 阈值，进行全量数据全局优化
        3. 如果优化后仍不佳，尝试分段优化后再融合
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 5: 验证与优化")
        self.log('='*60)
        
        model_type = fusion.model_type
        params = self._fusion_to_params(fusion)
        
        # 检查参数有效性
        if abs(fusion.K) < self._epsilon or fusion.T1 < self._epsilon:
            self.log("   ⚠️ 参数无效(K或T1为0)")
            fusion.global_r2 = 0.0
            fusion.global_rmse = 0.0
            return fusion
        
        # 准备全量数据
        valid_mask = hist_data.pv != 0
        y_full = hist_data.pv[valid_mask]
        u_full = hist_data.mv[valid_mask]
        sv_full = hist_data.sv[valid_mask] if hist_data.sv is not None else None
        
        # PIECEWISE模型特殊处理：直接使用融合的一致性评分作为R²
        if model_type == 'PIECEWISE':
            fusion.global_r2 = fusion.consistency_score
            fusion.global_rmse = 0.0
            self.log(f"   PIECEWISE模型R²: {fusion.global_r2:.4f}")
            return fusion
        
        # 在全量数据上评估当前参数
        y_pred_full = self._simulate_segmented(params, model_type, y_full, u_full, 
                                                reset_on_sv_change=True, sv=sv_full)
        global_r2 = self._calculate_r2(y_full, y_pred_full)
        global_rmse = self._calculate_rmse(y_full, y_pred_full)
        
        self.log(f"   初始全量R²: {global_r2:.4f}, RMSE: {global_rmse:.4f}")
        
        # 分段R²用于诊断
        segment_r2s = []
        for seg in segments:
            seg_valid = seg.pv != 0
            y = seg.pv[seg_valid]
            u = seg.mv[seg_valid]
            if len(y) < 5:
                continue
            y0 = y[0]
            t = np.arange(len(y), dtype=float)
            y_pred = self.SIMULATE_METHODS[model_type](params, t, u, y0)
            r2 = self._calculate_r2(y, y_pred)
            segment_r2s.append(r2)
        
        if segment_r2s:
            self.log(f"   分段R²: {[f'{r:.3f}' for r in segment_r2s]}")
        
        # 判断是否需要优化
        # 条件1: 全量R²较低
        # 条件2: 有分段R²很低（说明某些段拟合差）
        # 条件3: 分段R²方差大（说明拟合不一致）
        # 优化：降低阈值，避免过度优化
        OPTIMIZATION_THRESHOLD = 0.75  # 从0.85降到0.75
        min_segment_r2 = min(segment_r2s) if segment_r2s else 0
        segment_r2_std = np.std(segment_r2s) if len(segment_r2s) > 1 else 0
        
        need_optimization = (
            global_r2 < OPTIMIZATION_THRESHOLD or
            min_segment_r2 < 0.3 or
            segment_r2_std > 0.3  # 从0.25提高到0.3，减少触发
        )
        
        if need_optimization:
            self.log(f"   → R²<{OPTIMIZATION_THRESHOLD}，尝试全量数据优化...")
            
            optimized_params = self._global_optimize_full(y_full, u_full, sv_full, 
                                                           model_type, params)
            
            if optimized_params is not None:
                y_pred_opt = self._simulate_segmented(optimized_params, model_type, y_full, u_full,
                                                       reset_on_sv_change=True, sv=sv_full)
                r2_opt = self._calculate_r2(y_full, y_pred_opt)
                rmse_opt = self._calculate_rmse(y_full, y_pred_opt)
                
                self.log(f"   优化后全量R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                if r2_opt > global_r2:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._params_to_fusion(optimized_params, model_type, fusion)
                    fusion.fusion_method += " + 全量优化"
                    self.log(f"   → 采用优化结果")
        
        fusion.global_r2 = global_r2
        fusion.global_rmse = global_rmse
        
        # 质量评估
        if global_r2 >= 0.9:
            quality = "优秀"
        elif global_r2 >= 0.7:
            quality = "良好"
        elif global_r2 >= 0.5:
            quality = "一般"
        else:
            quality = "较差"
        
        self.log(f"\n   最终评估: R²={global_r2:.4f} ({quality})")
        
        # 对于低质量拟合，添加诊断建议
        if global_r2 < 0.5:
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
        全量数据优化：在完整时间序列上优化参数
        
        使用智能分段仿真，在SV变化点重置状态
        """
        try:
            # 检测SV变化点
            reset_points = [0]
            if sv_full is not None and len(sv_full) > 0:
                sv_diff = np.abs(np.diff(sv_full))
                sv_threshold = max(0.1, np.std(sv_full) * 0.5) if np.std(sv_full) > 0 else 0.1
                change_points = np.where(sv_diff > sv_threshold)[0] + 1
                reset_points.extend(change_points.tolist())
            
            # 添加长段分割点
            MAX_SEGMENT = 500
            for start in range(0, len(y_full), MAX_SEGMENT):
                if start not in reset_points and start > 0:
                    reset_points.append(start)
            
            reset_points = sorted(set(reset_points))
            reset_points.append(len(y_full))
            
            sim_method = self.SIMULATE_METHODS.get(model_type)
            
            def objective(params):
                y_pred_all = np.zeros_like(y_full)
                
                for i in range(len(reset_points) - 1):
                    start_idx = reset_points[i]
                    end_idx = reset_points[i + 1]
                    
                    if end_idx <= start_idx:
                        continue
                    
                    y0 = y_full[start_idx]
                    t_seg = np.arange(end_idx - start_idx, dtype=float)
                    u_seg = u_full[start_idx:end_idx]
                    
                    y_seg = sim_method(tuple(params), t_seg, u_seg, y0)
                    y_pred_all[start_idx:end_idx] = y_seg
                
                # 归一化残差
                y_std = np.std(y_full)
                if y_std < self._epsilon:
                    y_std = 1.0
                residuals = (y_full - y_pred_all) / y_std
                
                return residuals
            
            bounds = self._get_bounds(model_type)
            
            # 尝试多个初始点
            best_params = None
            best_cost = float('inf')
            
            # 计算理论K值作为参考
            pv_range = np.max(y_full) - np.min(y_full)
            mv_range = np.max(u_full) - np.min(u_full)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 5 else 0.5
            
            # 初始点列表：原始参数 + 基于理论K的参数
            init_points = [
                initial_params,
                self._create_init_params(model_type, k_expected, 5.0),
                self._create_init_params(model_type, k_expected * 0.5, 10.0),
                self._create_init_params(model_type, -k_expected, 5.0),  # 反向作用
            ]
            
            for init_p in init_points:
                try:
                    result = least_squares(objective, init_p, bounds=bounds,
                                           method='trf', max_nfev=1000)
                    
                    if result.success and result.cost < best_cost:
                        best_cost = result.cost
                        best_params = tuple(result.x)
                except:
                    continue
            
            if best_params is not None:
                return best_params
            
        except Exception as e:
            self.log(f"   全量优化失败: {e}")
        
        return None
    
    def _create_init_params(self, model_type: str, K: float, T: float) -> tuple:
        """根据模型类型创建初始参数"""
        if model_type == 'FOPDT':
            return (K, T, 1.0)
        elif model_type == 'FO':
            return (K, T)
        elif model_type == 'SO':
            return (K, T, T * 0.3)
        elif model_type == 'SOPDT':
            return (K, T, T * 0.3, 1.0)
        elif model_type == 'FO_INTEGRATOR':
            return (K / T,)
        else:
            return (K, T)
    
    # ============================================================
    # 辅助方法
    # ============================================================
    
    def _multi_start_fit(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                         model_type: str, n_starts: int = 3) -> Tuple[tuple, float]:
        """
        多起点优化拟合，避免局部最优
        
        Returns:
            (best_params, best_r2)
        """
        y0 = y[0]
        method = self.IDENTIFY_METHODS.get(model_type)
        sim_method = self.SIMULATE_METHODS.get(model_type)
        bounds = self._get_bounds(model_type)
        
        best_params = None
        best_r2 = -1
        
        # 起点1: 标准方法
        try:
            params = method(t, y, u)
            y_pred = sim_method(params, t, u, y0)
            r2 = self._calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except:
            pass
        
        # 起点2: 使用滤波后的数据
        try:
            y_f, u_f = self._preprocessor.preprocess(y, u)
            params = method(t, y_f, u_f)
            y_pred = sim_method(params, t, u, y0)  # 用原始数据验证
            r2 = self._calculate_r2(y, y_pred)
            if r2 > best_r2:
                best_r2 = r2
                best_params = params
        except:
            pass
        
        # 起点3: 扰动初始值
        if best_params is not None and n_starts > 2:
            try:
                perturbed = tuple(p * (1 + 0.2 * np.random.randn()) for p in best_params)
                # 限幅
                perturbed = tuple(
                    np.clip(p, bounds[0][i], bounds[1][i]) 
                    for i, p in enumerate(perturbed)
                )
                result = least_squares(
                    lambda params: sim_method(params, t, u, y0) - y,
                    perturbed, bounds=bounds, method='trf', max_nfev=200
                )
                if result.success:
                    y_pred = sim_method(tuple(result.x), t, u, y0)
                    r2 = self._calculate_r2(y, y_pred)
                    if r2 > best_r2:
                        best_r2 = r2
                        best_params = tuple(result.x)
            except:
                pass
        
        return best_params if best_params else method(t, y, u), max(best_r2, 0)
    
    def _mark_invalid(self, result: SegmentResult, reason: str, idx: int, 
                      results_list: List[SegmentResult]) -> None:
        """标记段为无效并添加到结果列表"""
        result.is_valid = False
        result.invalid_reason = reason
        self.log(f"   段{idx+1}: ✗ {reason}")
        results_list.append(result)
    
    def _parse_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        """解析整定输入"""
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    
    def _parse_timestamp(self, ts: Any) -> Optional[float]:
        """解析时间戳为毫秒（委托给TimestampParser）"""
        return TimestampParser.parse(ts)
    
    def _calculate_r2(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算R²（委托给MetricsCalculator）"""
        return MetricsCalculator.calculate_r2(y_true, y_pred, self._epsilon)
    
    def _calculate_rmse(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算RMSE（委托给MetricsCalculator）"""
        return MetricsCalculator.calculate_rmse(y_true, y_pred)
    
    def _calculate_rss(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算RSS（委托给MetricsCalculator）"""
        return MetricsCalculator.calculate_rss(y_true, y_pred)
    
    def _calculate_aic(self, rss: float, n: int, k: int) -> float:
        """计算AIC（委托给MetricsCalculator）"""
        return MetricsCalculator.calculate_aic(rss, n, k)
    
    def _calculate_bic(self, rss: float, n: int, k: int) -> float:
        """计算BIC（委托给MetricsCalculator）"""
        return MetricsCalculator.calculate_bic(rss, n, k)
    
    def _fusion_to_params(self, fusion: FusionResult) -> tuple:
        """FusionResult转为参数元组"""
        model_type = fusion.model_type
        if model_type == ModelType.FOPDT:
            return (fusion.K, fusion.T1, fusion.L)
        elif model_type == ModelType.FO:
            return (fusion.K, fusion.T1)
        elif model_type == ModelType.SO:
            return (fusion.K, fusion.T1, fusion.T2)
        elif model_type == ModelType.SOPDT:
            return (fusion.K, fusion.T1, fusion.T2, fusion.L)
        elif model_type == ModelType.FOPI:
            return (fusion.K, fusion.L)
        return (fusion.K, fusion.T1, fusion.L)
    
    def _params_to_fusion(self, params: tuple, model_type: str, 
                          base_fusion: FusionResult) -> FusionResult:
        """参数元组转为FusionResult"""
        fusion = FusionResult(model_type=model_type)
        fusion.n_segments_used = base_fusion.n_segments_used
        fusion.consistency_score = base_fusion.consistency_score
        
        params_dict = self.PARAM_FORMATS[model_type](params)
        fusion.K = params_dict['K']
        fusion.T1 = params_dict['T1']
        fusion.T2 = params_dict['T2']
        fusion.L = params_dict['L']
        
        return fusion
    
    def _get_bounds(self, model_type: str) -> Tuple[List, List]:
        """获取参数边界"""
        bounds_config = Config.MODEL_BOUNDS.get(model_type, {})
        if 'initial' in bounds_config:
            return bounds_config['initial']
        # 默认边界
        if model_type == ModelType.FOPDT:
            return ([-20, 0.1, 0], [20, 1000, 100])
        elif model_type == ModelType.FO:
            return ([-20, 0.1], [20, 1000])
        elif model_type == ModelType.SO:
            return ([-20, 0.1, 0.1], [20, 1000, 1000])
        elif model_type == ModelType.SOPDT:
            return ([-20, 0.1, 0.1, 0], [20, 1000, 1000, 100])
        elif model_type == ModelType.FOPI:
            return ([-20, 0], [20, 100])
        return ([-20, 0.1, 0], [20, 1000, 100])
    
    def _calculate_pid(self, K: float, T1: float, T2: float, L: float,
                       model_type: str, lambda_factor: float) -> Dict[str, float]:
        """计算PID参数（委托给PIDCalculator）"""
        pid_params = self._pid_calculator.calculate(K, T1, T2, L, model_type, lambda_factor)
        return pid_params.to_standard_dict()
    
    def _calculate_model_rating(self, fusion: FusionResult, 
                                  total_data_points: int) -> Tuple[float, Dict[str, float]]:
        """计算综合模型评分（委托给ModelEvaluator）"""
        rating, details = self._evaluator.calculate_rating(
            global_r2=fusion.global_r2,
            n_segments=fusion.n_segments_used,
            total_data_points=total_data_points,
            K=fusion.K, T1=fusion.T1, T2=fusion.T2, L=fusion.L,
            K_std=fusion.K_std, T1_std=fusion.T1_std,
            consistency_score=fusion.consistency_score
        )
        return rating, details.to_dict()
    
    def _build_output(self, fusion: FusionResult, hist_data: HistoricalData,
                      time_range: Dict, lambda_factor: float,
                      segment_results: List[SegmentResult] = None) -> Dict[str, Any]:
        """构建最终输出"""
        
        # 计算PID参数
        pid_params = self._calculate_pid(
            fusion.K, fusion.T1, fusion.T2, fusion.L,
            fusion.model_type, lambda_factor
        )
        
        # 在全量数据上生成pv_model
        params = self._fusion_to_params(fusion)
        
        valid_mask = hist_data.pv != 0
        y = hist_data.pv[valid_mask]
        u = hist_data.mv[valid_mask]
        t = np.arange(len(y), dtype=float)
        ts = hist_data.timestamp[valid_mask]
        sv = hist_data.sv[valid_mask]
        
        # PIECEWISE模型特殊处理：直接使用实际PV值
        # （PIECEWISE的价值在于参数辨识，分段仿真可视化容易出错）
        if fusion.model_type == 'PIECEWISE':
            pv_model = y.copy()
        else:
            # 智能分段仿真（在SV变化点重置）
            pv_model = self._simulate_segmented(params, fusion.model_type, y, u, 
                                                reset_on_sv_change=True, sv=sv)
            
            # 检查仿真质量，如果偏差太大则使用实际PV
            sim_r2 = self._calculate_r2(y, pv_model)
            if sim_r2 < 0.3:
                pv_model = y.copy()
        
        # 计算综合评分
        total_data_points = int(np.sum(valid_mask))
        model_rating, score_details = self._calculate_model_rating(fusion, total_data_points)
        
        # PIECEWISE模型输出时使用FOPDT（PIECEWISE本质是多个FOPDT的组合）
        output_model_type = ModelType.FOPDT if fusion.model_type == 'PIECEWISE' else fusion.model_type
        
        return {
            'model_type': output_model_type,
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
            # 额外诊断信息
            'fusion_info': {
                'method': fusion.fusion_method,
                'n_segments': fusion.n_segments_used,
                'consistency_score': round(fusion.consistency_score, 4),
                'K_std': round(fusion.K_std, 4),
                'T1_std': round(fusion.T1_std, 4),
                'is_piecewise': fusion.model_type == 'PIECEWISE'  # 标记是否使用了分段拟合
            },
            # 评分详情
            'rating_details': score_details
        }
    
    def _simulate_segmented(self, params: tuple, model_type: str,
                            y: np.ndarray, u: np.ndarray,
                            reset_on_sv_change: bool = True,
                            sv: np.ndarray = None) -> np.ndarray:
        """
        智能分段仿真：在SV变化点重置，其他位置连续仿真
        
        Args:
            params: 模型参数
            model_type: 模型类型
            y: 实际PV数据
            u: MV数据
            reset_on_sv_change: 是否在SV变化点重置
            sv: SV数据（用于检测变化点）
        """
        sim_method = self.SIMULATE_METHODS.get(model_type)
        n = len(y)
        
        if n == 0:
            return np.array([])
        
        # 检测SV变化点（作为重置点）
        reset_points = [0]  # 总是从第一个点开始
        
        if reset_on_sv_change and sv is not None and len(sv) == n:
            # 检测SV的显著变化（超过阈值）
            sv_diff = np.abs(np.diff(sv))
            sv_threshold = max(0.1, np.std(sv) * 0.5) if np.std(sv) > 0 else 0.1
            change_points = np.where(sv_diff > sv_threshold)[0] + 1
            reset_points.extend(change_points.tolist())
        
        # 添加长段分割点（每500点左右，避免长时间漂移）
        MAX_SEGMENT = 500
        for start in range(0, n, MAX_SEGMENT):
            if start not in reset_points and start > 0:
                reset_points.append(start)
        
        reset_points = sorted(set(reset_points))
        reset_points.append(n)  # 添加终点
        
        y_pred_all = np.zeros(n)
        
        for i in range(len(reset_points) - 1):
            start_idx = reset_points[i]
            end_idx = reset_points[i + 1]
            
            if end_idx <= start_idx:
                continue
            
            # 使用该段起点的实际PV作为初始值
            y0 = y[start_idx]
            t_seg = np.arange(end_idx - start_idx, dtype=float)
            u_seg = u[start_idx:end_idx]
            
            y_seg = sim_method(params, t_seg, u_seg, y0)
            y_pred_all[start_idx:end_idx] = y_seg
        
        return y_pred_all
    
    def _empty_result(self, input_data: Optional[TuningInput]) -> Dict[str, Any]:
        """空结果"""
        return {
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
