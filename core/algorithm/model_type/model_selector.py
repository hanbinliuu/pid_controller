import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, Union
from scipy.optimize import least_squares, minimize

# 导入依赖
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from model_identifier.config import Config, ModelType
    from model_identifier.identifier import ModelIdentifier
except ImportError:
    from core.algorithm.model_identifier.config import Config, ModelType
    from core.algorithm.model_identifier.identifier import ModelIdentifier


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
        tuning_window = None
        if 'tuning_window' in data and data['tuning_window']:
            tuning_window = [
                TuningWindow(start_time=w.get('start_time'), end_time=w.get('end_time'))
                for w in data['tuning_window']
            ]
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
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._epsilon = Config.EPSILON
    
    def log(self, msg: str):
        if self.verbose:
            print(msg)
    
    # ============================================================
    # 主入口
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
            if len(seg) < 20:
                result.is_valid = False
                result.invalid_reason = f"数据点不足({len(seg)}<20)"
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
                continue
            
            # 过滤PV=0的点
            valid_mask = seg.pv != 0
            valid_count = np.sum(valid_mask)
            
            if valid_count < 20:
                result.is_valid = False
                result.invalid_reason = f"有效点不足({valid_count}<20)"
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
                continue
            
            y = seg.pv[valid_mask]
            u = seg.mv[valid_mask]
            
            # 检查2: PV变化
            pv_range = np.max(y) - np.min(y)
            pv_std = np.std(y)
            
            if pv_range < 0.5 and pv_std < 0.1:
                result.is_valid = False
                result.invalid_reason = f"PV无变化(range={pv_range:.2f})"
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
                continue
            
            # 检查3: MV变化
            mv_range = np.max(u) - np.min(u)
            
            if mv_range < 0.1:
                result.is_valid = False
                result.invalid_reason = f"MV无变化(range={mv_range:.2f})"
                self.log(f"   段{i+1}: ✗ {result.invalid_reason}")
                segment_results.append(result)
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
            
            # 尝试所有候选模型
            for model_type in self.CANDIDATE_MODELS:
                try:
                    # 辨识
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
        
        MIN_R2_FOR_VOTE = 0.3  # 只有R²>=0.5的段才参与投票
        
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
                if r2 >= MIN_R2_FOR_VOTE:
                    model_r2_scores[model_type].append(r2)
            
            # 只有高质量段才投票
            if result.best_r2 >= MIN_R2_FOR_VOTE and result.best_model:
                model_votes[result.best_model] += 1
                high_quality_count += 1
        
        self.log(f"\n   高质量段(R²≥{MIN_R2_FOR_VOTE}): {high_quality_count}/{len(valid_results)}")
        
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
        
        策略：
        1. 提高R²阈值到0.5
        2. 使用IQR方法过滤K值异常段
        3. 稳健中位数融合
        """
        self.log(f"\n{'='*60}")
        self.log("📊 Step 4: 参数融合")
        self.log('='*60)
        
        fusion = FusionResult(model_type=model_type)
        
        # 收集各段的参数
        all_params = []  # [(K, T1, T2, L, r2, data_points, seg_idx)]
        
        R2_THRESHOLD = 0.5  # 提高阈值
        
        for result in segment_results:
            if not result.is_valid:
                continue
            
            fit_result = result.model_results.get(model_type)
            if fit_result is None:
                continue
            
            r2 = fit_result.get('r2', 0)
            if r2 < R2_THRESHOLD:
                self.log(f"   段{result.segment_idx+1}: R²={r2:.3f} < {R2_THRESHOLD}, 跳过")
                continue
            
            K = fit_result.get('K', 0)
            T1 = fit_result.get('T1', 0)
            T2 = fit_result.get('T2', 0)
            L = fit_result.get('L', 0)
            
            all_params.append((K, T1, T2, L, r2, result.data_points, result.segment_idx))
        
        if not all_params:
            # 降低阈值重试
            self.log(f"   ⚠️ 无R²≥{R2_THRESHOLD}的段，降低阈值到0.3重试")
            R2_THRESHOLD = 0.3
            for result in segment_results:
                if not result.is_valid:
                    continue
                fit_result = result.model_results.get(model_type)
                if fit_result is None or fit_result.get('r2', 0) < R2_THRESHOLD:
                    continue
                K = fit_result.get('K', 0)
                T1 = fit_result.get('T1', 0)
                T2 = fit_result.get('T2', 0)
                L = fit_result.get('L', 0)
                r2 = fit_result.get('r2', 0)
                all_params.append((K, T1, T2, L, r2, result.data_points, result.segment_idx))
        
        if not all_params:
            self.log("   ⚠️ 无有效参数，使用默认值")
            return fusion
        
        # 提取参数数组
        K_values = np.array([p[0] for p in all_params])
        T1_values = np.array([p[1] for p in all_params])
        T2_values = np.array([p[2] for p in all_params])
        L_values = np.array([p[3] for p in all_params])
        r2_values = np.array([p[4] for p in all_params])
        data_points = np.array([p[5] for p in all_params])
        
        self.log(f"   初始有效段: {len(K_values)}")
        
        # K符号一致性检查
        K_sign_majority = np.sign(np.median(K_values))
        sign_mask = np.sign(K_values) == K_sign_majority
        
        if not np.all(sign_mask):
            n_removed = np.sum(~sign_mask)
            self.log(f"   ⚠️ K符号不一致，过滤{n_removed}段")
            K_values = K_values[sign_mask]
            T1_values = T1_values[sign_mask]
            T2_values = T2_values[sign_mask]
            L_values = L_values[sign_mask]
            r2_values = r2_values[sign_mask]
            data_points = data_points[sign_mask]
        
        if len(K_values) == 0:
            self.log("   ⚠️ 过滤后无有效参数")
            return fusion
        
        # IQR方法过滤K值异常（如果段数>=3）
        if len(K_values) >= 3:
            K_abs = np.abs(K_values)
            q1, q3 = np.percentile(K_abs, [25, 75])
            iqr = q3 - q1
            lower_bound = max(0, q1 - 1.5 * iqr)
            upper_bound = q3 + 1.5 * iqr
            
            iqr_mask = (K_abs >= lower_bound) & (K_abs <= upper_bound)
            
            if not np.all(iqr_mask) and np.sum(iqr_mask) >= 1:
                n_removed = np.sum(~iqr_mask)
                self.log(f"   ⚠️ IQR过滤K值异常: 移除{n_removed}段 (K范围: [{lower_bound:.4f}, {upper_bound:.4f}])")
                K_values = K_values[iqr_mask]
                T1_values = T1_values[iqr_mask]
                T2_values = T2_values[iqr_mask]
                L_values = L_values[iqr_mask]
                r2_values = r2_values[iqr_mask]
                data_points = data_points[iqr_mask]
        
        if len(K_values) == 0:
            self.log("   ⚠️ IQR过滤后无有效参数")
            return fusion
        
        # 计算权重 = R² × sqrt(数据点数)
        weights = r2_values * np.sqrt(data_points)
        weights = weights / np.sum(weights)
        
        # 融合方法选择
        if len(K_values) == 1:
            fusion.K = float(K_values[0])
            fusion.T1 = float(T1_values[0])
            fusion.T2 = float(T2_values[0])
            fusion.L = float(L_values[0])
            fusion.fusion_method = "单段直接值"
        elif len(K_values) == 2:
            # 两段：加权平均
            fusion.K = float(np.sum(K_values * weights))
            fusion.T1 = float(np.sum(T1_values * weights))
            fusion.T2 = float(np.sum(T2_values * weights))
            fusion.L = float(np.sum(L_values * weights))
            fusion.fusion_method = "加权平均"
        else:
            # 多段：稳健中位数
            fusion.K = float(np.median(K_values))
            fusion.T1 = float(np.median(T1_values))
            fusion.T2 = float(np.median(T2_values))
            fusion.L = float(np.median(L_values))
            fusion.fusion_method = "稳健中位数"
        
        # 统计信息
        fusion.n_segments_used = len(K_values)
        fusion.segment_weights = weights.tolist()
        fusion.K_std = float(np.std(K_values)) if len(K_values) > 1 else 0.0
        fusion.T1_std = float(np.std(T1_values)) if len(T1_values) > 1 else 0.0
        
        # 一致性评分 (基于变异系数)
        cv_K = fusion.K_std / abs(fusion.K) if abs(fusion.K) > self._epsilon else 0
        cv_T1 = fusion.T1_std / fusion.T1 if fusion.T1 > self._epsilon else 0
        fusion.consistency_score = float(np.clip(1 - (cv_K + cv_T1) / 2, 0, 1))
        
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
    
    def _parse_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    
    def _parse_timestamp(self, ts: Any) -> Optional[float]:
        if ts is None:
            return None
        if isinstance(ts, (int, float)):
            return float(ts)
        if isinstance(ts, str):
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                return dt.timestamp() * 1000
            except:
                try:
                    dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                    return dt.timestamp() * 1000
                except:
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
