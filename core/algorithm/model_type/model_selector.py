"""模型选择器模块 - 多模型拟合与参数融合"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime
from scipy.optimize import minimize, least_squares
from scipy.ndimage import uniform_filter1d

from .config import Config, ModelType
from .identifier import ModelIdentifier
from .fusion_strategy import PIDFusionStrategy, WindowResult as FusionWindowResult
from .data_preprocessor import DataPreprocessor, DataQuality


# ============================================================
# 数据结构定义
# ============================================================

@dataclass
class SegmentResult:
    """单个扰动段的拟合结果"""
    segment_idx: int                    # 段索引
    start_idx: int                      # 起始索引
    end_idx: int                        # 结束索引
    data_points: int                    # 数据点数
    is_valid: bool                      # 是否有效
    invalid_reason: str = ""            # 无效原因
    
    # 各模型的拟合结果
    model_results: Dict[str, Dict] = field(default_factory=dict)
    # 格式: {model_type: {K, T1, T2, L, r2, rss, aic, bic, params_raw}}
    
    # 最佳模型（该段）
    best_model: str = ""
    best_r2: float = 0.0
    best_aic: float = float('inf')


@dataclass
class FusionResult:
    """参数融合结果"""
    model_type: str                     # 最终模型类型
    K: float = 0.0
    T1: float = 0.0
    T2: float = 0.0
    L: float = 0.0
    
    # 融合统计
    fusion_method: str = ""             # 融合方法
    n_segments_used: int = 0            # 使用的段数
    segment_weights: List[float] = field(default_factory=list)
    
    # 一致性评估
    K_std: float = 0.0                  # K的标准差
    T1_std: float = 0.0                 # T1的标准差
    consistency_score: float = 0.0      # 一致性评分 (0-1)
    
    # 验证结果
    global_r2: float = 0.0              # 全局R²
    global_rmse: float = 0.0            # 全局RMSE


@dataclass
class TuningWindow:
    """整定窗口"""
    start_time: Any
    end_time: Any


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


@dataclass
class HistoricalData:
    """历史数据"""
    timestamp: np.ndarray
    pv: np.ndarray
    sv: np.ndarray
    mv: np.ndarray
    
    @classmethod
    def from_json(cls, data: List[Dict]) -> 'HistoricalData':
        if not data:
            raise ValueError("输入数据为空")
        timestamps = np.array([item.get('timestamp', 0) for item in data], dtype=np.float64)
        pvs = np.array([item.get('pv', 0.0) for item in data], dtype=np.float64)
        svs = np.array([item.get('sv', 0.0) for item in data], dtype=np.float64)
        mvs = np.array([item.get('mv', 0.0) for item in data], dtype=np.float64)
        return cls(timestamp=timestamps, pv=pvs, sv=svs, mv=mvs)
    
    def __len__(self) -> int:
        return len(self.pv)


# ============================================================
# 模型选择器主类
# ============================================================

class ModelSelector:
    """
    模型类型选择器
    
    核心流程：
    1. 剔除无效/扰动段 → 有效段筛选
    2. 对每个有效段尝试多种模型拟合 → 获取各段各模型的KTL
    3. 基于AIC/RSS/形状特征选择最优模型结构 → 确定模型类型
    4. 融合各段参数 → 唯一K, T, L（加权平均 / 全局优化）
    5. 验证一致性与仿真匹配度 → 最终输出
    """
    
    # 候选模型
    CANDIDATE_MODELS = [
        ModelType.FOPDT,    # 一阶加滞后（最常用）
        ModelType.FO,       # 纯一阶
        ModelType.SO,       # 二阶
        ModelType.SOPDT,    # 二阶加滞后
        ModelType.FOPI,     # 积分过程
    ]
    
    # 模型参数数量（用于AIC/BIC计算）
    MODEL_PARAM_COUNT = {
        ModelType.FOPDT: 3,   # K, T, L
        ModelType.FO: 2,      # K, T
        ModelType.SO: 3,      # K, T1, T2
        ModelType.SOPDT: 4,   # K, T1, T2, L
        ModelType.FOPI: 2,    # K, L
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
    
    # 评分等级阈值
    RATING_THRESHOLDS = {
        'excellent': (8.0, '优秀'),
        'good': (6.0, '良好'),
        'acceptable': (4.0, '可接受'),
        'poor': (2.0, '较差'),
        'unavailable': (0.0, '不可用')
    }
    
    # 验证阈值常量
    MIN_DATA_POINTS = 20          # 最小数据点数
    MIN_PV_RANGE = 0.5            # 最小PV变化范围
    MIN_MV_RANGE = 0.1            # 最小MV变化范围
    MIN_R2_FOR_VOTE = 0.3         # 投票所需最小R²
    MIN_R2_FOR_QUALITY = 0.4      # 高质量段最小R²
    R2_THRESHOLDS = [0.5, 0.3, 0.15, 0.0]  # 参数融合阈值序列
    
    def __init__(self, verbose: bool = False):
        self._verbose = verbose
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(verbose=verbose)
    
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
        """根据评分获取推荐等级"""
        if model_rating >= 8.0:
            return '优秀'
        elif model_rating >= 6.0:
            return '良好'
        elif model_rating >= 4.0:
            return '可接受'
        elif model_rating >= 2.0:
            return '较差'
        else:
            return '不可用'
    
    def _determine_turning_type(self, Kp: float, Ti: float, Td: float) -> str:
        """根据 PID 参数确定整定类型"""
        if Td > self._epsilon:
            return 'PID'
        elif Ti > self._epsilon:
            return 'PI'
        else:
            return 'P'
    
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
        return self._build_output(fusion_result, hist_data, time_range, lambda_factor)
    
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
            if len(seg) < self.MIN_DATA_POINTS:
                self._mark_invalid(result, f"数据点不足({len(seg)}<{self.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            # 过滤PV=0的点
            valid_mask = seg.pv != 0
            valid_count = np.sum(valid_mask)
            
            if valid_count < self.MIN_DATA_POINTS:
                self._mark_invalid(result, f"有效点不足({valid_count}<{self.MIN_DATA_POINTS})", i, segment_results)
                continue
            
            y, u = seg.pv[valid_mask], seg.mv[valid_mask]
            pv_range, mv_range = np.ptp(y), np.ptp(u)  # ptp = max - min
            
            # 检查2: PV变化
            if pv_range < self.MIN_PV_RANGE and np.std(y) < 0.1:
                self._mark_invalid(result, f"PV无变化(range={pv_range:.2f})", i, segment_results)
                continue
            
            # 检查3: MV变化
            if mv_range < self.MIN_MV_RANGE:
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
            
            # 计算理论K值范围（用于校验）
            pv_range = np.max(y) - np.min(y)
            mv_range = np.max(u) - np.min(u)
            k_expected = pv_range / (mv_range + self._epsilon) if mv_range > 0.1 else 1.0
            
            self.log(f"\n📊 段{i+1}: {len(y)}点")
            
            # 分析数据质量（使用 DataPreprocessor）
            quality = self._preprocessor.analyze_quality(y, u)
            use_multi_start = quality.is_noisy or not quality.is_correlated
            
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
                    
                    result.model_results[model_type] = {
                        'K': params_dict['K'],
                        'T1': params_dict['T1'],
                        'T2': params_dict['T2'],
                        'L': params_dict['L'],
                        'params_raw': params_raw,
                        'r2': r2,
                        'rss': rss,
                        'aic': aic,
                        'bic': bic,
                        'y_pred': y_pred
                    }
                    
                    self.log(f"   {model_type}: R²={r2:.4f}, AIC={aic:.1f}, "
                             f"K={params_dict['K']:.4f}, T1={params_dict['T1']:.2f}")
                    
                except Exception as e:
                    self.log(f"   {model_type}: 拟合失败 - {e}")
                    result.model_results[model_type] = {
                        'r2': 0.0, 'rss': float('inf'), 'aic': float('inf')
                    }
            
            # 选择该段的最佳模型（要求R²>=0.4）
            if result.model_results:
                # 过滤R²过低的模型
                valid_models = {m: r for m, r in result.model_results.items() 
                               if r.get('r2', 0) >= 0.4}
                
                if valid_models:
                    best_model = min(valid_models.keys(),
                                    key=lambda m: valid_models[m].get('aic', float('inf')))
                    result.best_model = best_model
                    result.best_r2 = result.model_results[best_model].get('r2', 0)
                    result.best_aic = result.model_results[best_model].get('aic', float('inf'))
                else:
                    # 所有模型R²都<0.4，选R²最高的但标记为低质量
                    best_model = max(result.model_results.keys(),
                                    key=lambda m: result.model_results[m].get('r2', 0))
                    result.best_model = best_model
                    result.best_r2 = result.model_results[best_model].get('r2', 0)
                    result.best_aic = result.model_results[best_model].get('aic', float('inf'))
                    self.log(f"   ⚠️ 段{i+1}所有模型R²<0.4，拟合质量差")
        
        return segment_results
    
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
        
        # 统计各模型的得分
        model_r2_scores = {m: [] for m in self.CANDIDATE_MODELS}
        model_votes = {m: 0 for m in self.CANDIDATE_MODELS}
        
        valid_results = [r for r in segment_results if r.is_valid and r.model_results]
        
        if not valid_results:
            self.log("   无有效段结果，默认使用 FOPDT")
            return ModelType.FOPDT
        
        # 统计高质量段数
        high_quality_count = 0
        
        for result in valid_results:
            # 收集R²
            for model_type, fit_result in result.model_results.items():
                r2 = fit_result.get('r2', 0)
                if r2 >= self.MIN_R2_FOR_VOTE:
                    model_r2_scores[model_type].append(r2)
            
            # 只有高质量段才投票
            if result.best_r2 >= self.MIN_R2_FOR_VOTE and result.best_model:
                model_votes[result.best_model] += 1
                high_quality_count += 1
        
        self.log(f"\n   高质量段(R²≥{self.MIN_R2_FOR_VOTE}): {high_quality_count}/{len(valid_results)}")
        
        # 计算各模型的平均R²
        self.log("\n   模型评估汇总:")
        self.log(f"   {'模型':<15} | {'平均R²':>10} | {'有效段':>6} | {'投票':>6} | {'综合分':>10}")
        self.log("   " + "-" * 60)
        
        model_composite_scores = {}
        
        for model_type in self.CANDIDATE_MODELS:
            r2_scores = model_r2_scores[model_type]
            votes = model_votes[model_type]
            
            if r2_scores:
                avg_r2 = np.mean(r2_scores)
                n_valid = len(r2_scores)
                
                # 综合得分: R² 70%, 投票 30%
                vote_normalized = votes / max(high_quality_count, 1)
                composite = 0.7 * avg_r2 + 0.3 * vote_normalized
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
        
        for threshold in self.R2_THRESHOLDS:
            for result in segment_results:
                if not result.is_valid or result.segment_idx in added_indices:
                    continue
                
                fit_result = result.model_results.get(model_type)
                if fit_result is None:
                    continue
                
                r2 = fit_result.get('r2', 0)
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
                if threshold < self.R2_THRESHOLDS[0]:
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
        
        策略：
        1. 分段计算R²，然后加权平均（避免段间基准不同的问题）
        2. 如果R² < 阈值，尝试全局优化
        3. 评估最终匹配度
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
        
        # 分段计算R²，加权平均
        segment_r2s = []
        segment_weights = []
        all_y_true = []
        all_y_pred = []
        
        for seg in segments:
            valid_mask = seg.pv != 0
            y = seg.pv[valid_mask]
            u = seg.mv[valid_mask]
            t = np.arange(len(y), dtype=float)
            y0 = y[0]
            
            sim_method = self.SIMULATE_METHODS.get(model_type)
            y_pred = sim_method(params, t, u, y0)
            
            r2 = self._calculate_r2(y, y_pred)
            segment_r2s.append(r2)
            segment_weights.append(len(y))
            
            all_y_true.append(y)
            all_y_pred.append(y_pred)
        
        # 加权平均R²（按数据点数加权）
        total_weight = sum(segment_weights)
        global_r2 = sum(r * w for r, w in zip(segment_r2s, segment_weights)) / total_weight
        
        # 计算全局RMSE
        y_true_concat = np.concatenate(all_y_true)
        y_pred_concat = np.concatenate(all_y_pred)
        global_rmse = self._calculate_rmse(y_true_concat, y_pred_concat)
        
        self.log(f"   分段R²: {[f'{r:.3f}' for r in segment_r2s]}")
        self.log(f"   加权平均R²: {global_r2:.4f}, RMSE: {global_rmse:.4f}")
        
        # 如果R²较低，尝试全局优化
        if global_r2 < 0.6 and len(segments) > 1:
            self.log("   → R²较低，尝试全局优化...")
            
            optimized_params = self._global_optimize(segments, model_type, params)
            
            if optimized_params is not None:
                # 重新计算
                all_y_pred_opt = []
                for seg in segments:
                    valid_mask = seg.pv != 0
                    y = seg.pv[valid_mask]
                    u = seg.mv[valid_mask]
                    t = np.arange(len(y), dtype=float)
                    y0 = y[0]
                    
                    y_pred = self.SIMULATE_METHODS[model_type](optimized_params, t, u, y0)
                    all_y_pred_opt.append(y_pred)
                
                y_pred_opt_concat = np.concatenate(all_y_pred_opt)
                r2_opt = self._calculate_r2(y_true_concat, y_pred_opt_concat)
                rmse_opt = self._calculate_rmse(y_true_concat, y_pred_opt_concat)
                
                self.log(f"   优化后全局R²: {r2_opt:.4f}, RMSE: {rmse_opt:.4f}")
                
                if r2_opt > global_r2:
                    global_r2 = r2_opt
                    global_rmse = rmse_opt
                    fusion = self._params_to_fusion(optimized_params, model_type, fusion)
                    fusion.fusion_method += " + 全局优化"
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
        
        return fusion
    
    def _global_optimize(self, segments: List[HistoricalData],
                         model_type: str,
                         initial_params: tuple) -> Optional[tuple]:
        """
        全局优化：在所有段上同时优化参数
        """
        try:
            def objective(params):
                total_residuals = []
                
                for seg in segments:
                    valid_mask = seg.pv != 0
                    y = seg.pv[valid_mask]
                    u = seg.mv[valid_mask]
                    t = np.arange(len(y), dtype=float)
                    y0 = y[0]
                    
                    sim_method = self.SIMULATE_METHODS.get(model_type)
                    y_pred = sim_method(tuple(params), t, u, y0)
                    
                    residuals = (y - y_pred) / (np.std(y) + self._epsilon)
                    total_residuals.extend(residuals.tolist())
                
                return np.array(total_residuals)
            
            # 设置边界
            bounds = self._get_bounds(model_type)
            
            result = least_squares(objective, initial_params, bounds=bounds, 
                                   method='trf', max_nfev=1000)
            
            if result.success:
                return tuple(result.x)
            
        except Exception as e:
            self.log(f"   全局优化失败: {e}")
        
        return None
    
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
        """解析时间戳为毫秒"""
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str):
            for fmt in ['%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S']:
                try:
                    dt = datetime.strptime(ts.replace('Z', '').split('+')[0], fmt)
                    return dt.timestamp() * 1000
                except ValueError:
                    continue
            return None
        if hasattr(ts, 'timestamp'):
            return ts.timestamp() * 1000
        return None
    
    def _calculate_r2(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        if ss_tot < self._epsilon:
            return 0.0
        r2 = 1 - ss_res / ss_tot
        return float(np.clip(r2, 0.0, 1.0))
    
    def _calculate_rmse(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    
    def _calculate_rss(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        return float(np.sum((y_true - y_pred) ** 2))
    
    def _calculate_aic(self, rss: float, n: int, k: int) -> float:
        """计算AIC (Akaike Information Criterion)"""
        if rss <= 0 or n <= k:
            return float('inf')
        return n * np.log(rss / n) + 2 * k
    
    def _calculate_bic(self, rss: float, n: int, k: int) -> float:
        """计算BIC (Bayesian Information Criterion)"""
        if rss <= 0 or n <= k:
            return float('inf')
        return n * np.log(rss / n) + k * np.log(n)
    
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
        """计算PID参数（Lambda方法）"""
        K = max(abs(K), self._epsilon)
        T1 = max(T1, self._epsilon)
        L = max(L, 0.0)
        T_eq = T1 + T2 if T2 > 0 else T1
        lambda_val = T_eq * lambda_factor
        
        if model_type in [ModelType.FOPDT, ModelType.FO]:
            denom = K * (lambda_val + L / 2)
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = (T1 + L / 2) / denom
                Ti = T1 + L / 2
                Td = (T1 * L) / (2 * T1 + L) if (2 * T1 + L) > self._epsilon else 0.0
        
        elif model_type in [ModelType.SO, ModelType.SOPDT]:
            denom = K * (lambda_val + L / 2) if L > 0 else K * lambda_val
            if denom < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                Kp = T_eq / denom
                Ti = T_eq
                Td = (T1 * T2) / T_eq if T_eq > self._epsilon else 0.0
        
        elif model_type == ModelType.FOPI:
            if K < self._epsilon:
                Kp, Ti, Td = 1.0, 20.0, 0.0
            else:
                lv = max(T1 * 0.8, 0.2) if T1 > 0 else 0.2
                Kp = T1 / (K * lv) if T1 > 0 else 1.0 / (K * lv)
                Ti, Td = max(T1, 1.0), 0.0
        else:
            Kp, Ti, Td = 1.0, 20.0, 0.0
        
        Kp, Ti, Td = max(0.01, Kp), max(0.1, Ti), max(0.0, Td)
        Ki = Kp / Ti if Ti > self._epsilon else 0.0
        Kd = Kp * Td
        
        return {
            'Kp': round(float(Kp), 4),
            'Ki': round(float(Ki), 4),
            'Kd': round(float(Kd), 4)
        }
    
    def _build_output(self, fusion: FusionResult, hist_data: HistoricalData,
                      time_range: Dict, lambda_factor: float) -> Dict[str, Any]:
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
        
        # 分段仿真
        pv_model = self._simulate_segmented(params, fusion.model_type, y, u)
        
        return {
            'model_type': fusion.model_type,
            'model_rating': round(fusion.global_r2 * 10, 2),
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
                'T1_std': round(fusion.T1_std, 4)
            }
        }
    
    def _simulate_segmented(self, params: tuple, model_type: str,
                            y: np.ndarray, u: np.ndarray) -> np.ndarray:
        """分段仿真（避免长时间漂移）"""
        SEGMENT_SIZE = 100
        y_pred_all = np.zeros_like(y)
        sim_method = self.SIMULATE_METHODS.get(model_type)
        
        for start_idx in range(0, len(y), SEGMENT_SIZE):
            end_idx = min(start_idx + SEGMENT_SIZE, len(y))
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
            }
        }
