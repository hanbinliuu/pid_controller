"""
统一模型选择器模块 (Unified Model Selector Module)
==================================================

本模块解决多扰动段模型类型不一致的问题。

核心理念
--------
同一回路应该只有一种模型类型，使用高质量段决定模型类型，
参数融合时考虑各段的可信度。

主要功能
--------
1. **统一模型类型选择**: 使用R²加权的综合评分选择最优模型类型
2. **复杂度惩罚**: 应用奥卡姆剃刀原则，简单模型优先
3. **可靠性计算**: 综合考虑R²、数据质量、非线性程度等
4. **参数融合**: 基于可靠性加权融合各段参数
5. **不一致性诊断**: 分析各段之间的差异并给出建议

模型复杂度排序
--------------
1. FO (2参数) - 最简单
2. FOPDT (3参数)
3. SO (3参数)
4. FOPI (2参数，积分器)
5. SOPDT (4参数) - 最复杂
"""

import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field

from ..config import Config, ModelType
from ..data_models import SegmentResult, FusionResult
from ..logger import LoggerMixin


@dataclass
class SegmentModelFit:
    """单段的多模型拟合结果"""
    segment_idx: int
    data_points: int
    quality_score: float          # 数据质量分
    nonlinearity_score: float     # 非线性程度
    is_nonlinear: bool
    
    # 各模型的拟合结果 {model_type: {r2, K, T1, T2, L, aic, k_reasonable}}
    model_fits: Dict[str, Dict] = field(default_factory=dict)
    
    @property
    def best_r2(self) -> float:
        """该段所有模型中的最佳R²"""
        if not self.model_fits:
            return 0.0
        return max(f.get('r2', 0) for f in self.model_fits.values())
    
    @property
    def is_high_quality(self) -> bool:
        """是否为高质量段"""
        return self.best_r2 >= 0.5 and self.quality_score >= 0.4 and not self.is_nonlinear


class UnifiedModelSelector(LoggerMixin):
    """
    统一模型选择器
    
    核心理念：
    1. 同一回路应该只有一种模型类型
    2. 使用高质量段决定模型类型
    3. 参数融合时考虑各段的可信度
    """
    
    # 候选模型（按复杂度从低到高排序）
    MODELS_BY_COMPLEXITY = [
        ModelType.FO,        # 2参数
        ModelType.FOPDT,     # 3参数
        ModelType.SO,        # 3参数
        ModelType.FOPI,      # 2参数（积分器）
        ModelType.SOPDT,     # 4参数
    ]
    
    # 常规模型（非积分器）
    REGULAR_MODELS = [ModelType.FO, ModelType.FOPDT, ModelType.SO, ModelType.SOPDT]
    
    # 模型复杂度惩罚系数（奥卡姆剃刀）
    COMPLEXITY_PENALTY = {
        ModelType.FO: 0.0,
        ModelType.FOPDT: 0.02,
        ModelType.SO: 0.02,
        ModelType.FOPI: 0.05,  # 积分器需要更高阈值
        ModelType.SOPDT: 0.04,
    }
    
    def __init__(self, verbose: bool = False):
        self._init_logger(verbose)
        self._epsilon = Config.EPSILON
    
    def select_unified_model_type(self, segment_fits: List[SegmentModelFit], 
                                   return_need_fulldata: bool = False) -> Tuple[str, str, bool]:
        """
        统一模型类型选择
        
        策略：
        1. 只使用高质量段进行投票
        2. 使用R²加权的AIC最小化
        3. 应用复杂度惩罚（奥卡姆剃刀）
        4. 处理边界情况
        5. 当扰动段无法判断时，标记需要全量数据验证
        
        Returns:
            (best_model_type, reasoning, need_fulldata_validation)
        """
        self.log(f"\n{'='*60}")
        self.log("🎯 统一模型类型选择")
        self.log('='*60)
        
        # 1. 筛选高质量段
        high_quality_segments = [s for s in segment_fits if s.is_high_quality]
        usable_segments = high_quality_segments if high_quality_segments else segment_fits
        
        self.log(f"   高质量段: {len(high_quality_segments)}/{len(segment_fits)}")
        
        if not usable_segments:
            return ModelType.FOPDT, "无有效数据，使用默认FOPDT", True
        
        # 2. 计算每个模型的综合得分
        model_scores = {}
        
        for model_type in self.REGULAR_MODELS:
            scores = []
            weights = []
            
            for seg in usable_segments:
                fit = seg.model_fits.get(model_type, {})
                r2 = fit.get('r2', 0)
                k_reasonable = fit.get('k_reasonable', True)
                
                if r2 > 0.1:  # 至少有一些拟合
                    # 如果K值不合理，降低权重
                    weight = r2 if k_reasonable else r2 * 0.3
                    
                    # 质量加权
                    weight *= seg.quality_score
                    
                    # 非线性惩罚
                    weight *= (1 - seg.nonlinearity_score * 0.5)
                    
                    scores.append(r2)
                    weights.append(weight)
            
            if scores:
                # 加权平均R²
                weighted_r2 = sum(s * w for s, w in zip(scores, weights)) / (sum(weights) + self._epsilon)
                
                # 应用复杂度惩罚
                penalty = self.COMPLEXITY_PENALTY.get(model_type, 0)
                adjusted_score = weighted_r2 - penalty
                
                model_scores[model_type] = {
                    'weighted_r2': weighted_r2,
                    'adjusted_score': adjusted_score,
                    'n_valid_segments': len(scores),
                    'total_weight': sum(weights)
                }
        
        # 3. 显示评估结果
        self.log("\n   模型评估:")
        self.log(f"   {'模型':<12} | {'加权R²':>10} | {'调整分':>10} | {'有效段':>6} | {'权重和':>8}")
        self.log("   " + "-" * 55)
        
        for model_type, info in sorted(model_scores.items(), 
                                        key=lambda x: x[1]['adjusted_score'], 
                                        reverse=True):
            self.log(f"   {model_type:<12} | {info['weighted_r2']:>10.4f} | "
                    f"{info['adjusted_score']:>10.4f} | {info['n_valid_segments']:>6} | "
                    f"{info['total_weight']:>8.2f}")
        
        # 4. 选择最佳模型
        if not model_scores:
            return ModelType.FOPDT, "无有效拟合结果，使用默认FOPDT", True
        
        best_model = max(model_scores.keys(), 
                        key=lambda m: model_scores[m]['adjusted_score'])
        best_info = model_scores[best_model]
        
        # 5. 检查是否需要回退到更简单模型
        if best_info['adjusted_score'] < 0.4:
            # 拟合质量都不好，检查是否有更简单的模型接近
            simpler_models = [m for m in [ModelType.FO, ModelType.FOPDT] 
                            if m in model_scores]
            for simpler in simpler_models:
                simpler_score = model_scores[simpler]['adjusted_score']
                if simpler_score > best_info['adjusted_score'] * 0.85:
                    self.log(f"\n   ⚠️ 拟合质量较差，回退到更简单的 {simpler}")
                    # 调整分<0.4且回退到简单模型，标记需要全量数据验证
                    return simpler, f"质量较差，使用简单模型{simpler}", True
        
        reasoning = (f"加权R²={best_info['weighted_r2']:.4f}, "
                    f"调整分={best_info['adjusted_score']:.4f}, "
                    f"使用{best_info['n_valid_segments']}个有效段")
        
        # 调整分<0.4时仍标记需要全量数据验证
        need_fulldata = best_info['adjusted_score'] < 0.4
        
        self.log(f"\n   → 选择: {best_model} ({reasoning})")
        return best_model, reasoning, need_fulldata
    
    def compute_segment_reliability(self, seg: SegmentModelFit, 
                                     model_type: str) -> float:
        """
        计算段的可靠性分数
        
        综合考虑：
        - 该模型的拟合R²
        - 数据质量
        - 非线性程度
        - K值合理性
        - 数据点数
        """
        fit = seg.model_fits.get(model_type, {})
        r2 = fit.get('r2', 0)
        k_reasonable = fit.get('k_reasonable', True)
        
        if r2 < 0.1:
            return 0.0
        
        # 基础分 = R²
        score = r2
        
        # K值不合理惩罚
        if not k_reasonable:
            score *= 0.3
        
        # 质量分加权
        score *= seg.quality_score
        
        # 非线性惩罚
        score *= (1 - seg.nonlinearity_score * 0.6)
        
        # 数据点加权（适量奖励）
        data_factor = min(np.sqrt(seg.data_points / 50), 2.0)
        score *= data_factor
        
        return score
    
    def fuse_parameters(self, segment_fits: List[SegmentModelFit],
                        model_type: str) -> Tuple[FusionResult, Dict]:
        """
        统一参数融合
        
        策略：
        1. 计算每段对选定模型的可靠性
        2. 使用可靠性加权融合
        3. 排除异常段
        4. 鲁棒性处理
        
        Returns:
            (fusion_result, fusion_info)
        """
        self.log(f"\n{'='*60}")
        self.log(f"🔧 参数融合 (模型: {model_type})")
        self.log('='*60)
        
        # 1. 计算每段的可靠性和参数
        segment_params = []
        
        for seg in segment_fits:
            fit = seg.model_fits.get(model_type, {})
            r2 = fit.get('r2', 0)
            
            if r2 < 0.05:  # 跳过完全无效的拟合
                continue
            
            reliability = self.compute_segment_reliability(seg, model_type)
            
            segment_params.append({
                'segment_idx': seg.segment_idx,
                'K': fit.get('K', 0),
                'T1': fit.get('T1', 1),
                'T2': fit.get('T2', 0),
                'L': fit.get('L', 0),
                'r2': r2,
                'reliability': reliability,
                'k_reasonable': fit.get('k_reasonable', True),
                'is_nonlinear': seg.is_nonlinear
            })
        
        if not segment_params:
            self.log("   ⚠️ 无有效段，使用默认参数")
            return FusionResult(model_type=model_type), {'method': 'default'}
        
        self.log(f"\n   段参数:")
        for p in segment_params:
            flag = ""
            if not p['k_reasonable']:
                flag += " ⚠️K异常"
            if p['is_nonlinear']:
                flag += " ⚠️非线性"
            self.log(f"   段{p['segment_idx']+1}: K={p['K']:.4f}, T1={p['T1']:.2f}, "
                    f"R²={p['r2']:.3f}, 可靠性={p['reliability']:.3f}{flag}")
        
        # 2. 异常值检测和过滤
        K_values = np.array([p['K'] for p in segment_params])
        K_median = np.median(K_values)
        
        # 使用MAD (Median Absolute Deviation) 检测异常值
        K_mad = np.median(np.abs(K_values - K_median))
        K_threshold = max(K_mad * 3, abs(K_median) * 0.5)  # 至少允许50%偏差
        
        filtered_params = []
        for p in segment_params:
            if abs(p['K'] - K_median) > K_threshold and len(segment_params) > 1:
                self.log(f"   段{p['segment_idx']+1}: K={p['K']:.4f} 偏离中位数过大，降权")
                p['reliability'] *= 0.2
            filtered_params.append(p)
        
        # 3. 加权融合
        total_weight = sum(p['reliability'] for p in filtered_params)
        
        if total_weight < self._epsilon:
            # 回退到简单平均
            self.log("   ⚠️ 所有段可靠性都很低，使用简单平均")
            K = np.mean([p['K'] for p in filtered_params])
            T1 = np.mean([p['T1'] for p in filtered_params])
            T2 = np.mean([p['T2'] for p in filtered_params])
            L = np.mean([p['L'] for p in filtered_params])
            confidence = 0.3
        else:
            K = sum(p['K'] * p['reliability'] for p in filtered_params) / total_weight
            T1 = sum(p['T1'] * p['reliability'] for p in filtered_params) / total_weight
            T2 = sum(p['T2'] * p['reliability'] for p in filtered_params) / total_weight
            L = sum(p['L'] * p['reliability'] for p in filtered_params) / total_weight
            
            # 置信度 = 加权R² × 覆盖度因子
            weighted_r2 = sum(p['r2'] * p['reliability'] for p in filtered_params) / total_weight
            coverage_factor = min(len(filtered_params) / 3, 1.0)  # 3段以上满分
            confidence = weighted_r2 * (0.7 + 0.3 * coverage_factor)
        
        # 4. 计算一致性
        K_std = np.std([p['K'] for p in filtered_params]) if len(filtered_params) > 1 else 0
        T1_std = np.std([p['T1'] for p in filtered_params]) if len(filtered_params) > 1 else 0
        
        # 5. 构建结果
        fusion = FusionResult(model_type=model_type)
        fusion.K = float(K)
        fusion.T1 = float(T1)
        fusion.T2 = float(T2)
        fusion.L = float(L)
        fusion.K_std = float(K_std)
        fusion.T1_std = float(T1_std)
        fusion.n_segments_used = len(filtered_params)
        fusion.consistency_score = float(confidence)
        fusion.fusion_method = "unified_reliability_weighted"
        
        windows_used = [p['segment_idx'] for p in filtered_params 
                       if p['reliability'] > total_weight * 0.1 / len(filtered_params)]
        if not windows_used:
            windows_used = [max(filtered_params, key=lambda p: p['reliability'])['segment_idx']]
        fusion.segment_weights = [p['reliability'] / total_weight for p in filtered_params]
        
        self.log(f"\n   融合结果:")
        self.log(f"   K  = {K:.4f} ± {K_std:.4f}")
        self.log(f"   T1 = {T1:.2f} ± {T1_std:.2f}")
        self.log(f"   T2 = {T2:.2f}")
        self.log(f"   L  = {L:.2f}")
        self.log(f"   置信度 = {confidence:.3f}")
        self.log(f"   主要贡献段: {[i+1 for i in windows_used]}")
        
        fusion_info = {
            'method': 'unified_reliability_weighted',
            'segments_used': len(filtered_params),
            'windows_used': windows_used,
            'total_weight': total_weight,
            'k_median': float(K_median),
            'k_mad': float(K_mad)
        }
        
        return fusion, fusion_info
    
    def handle_inconsistent_segments(self, segment_fits: List[SegmentModelFit]) -> Dict:
        """
        分析段之间的不一致性并给出诊断
        
        Returns:
            诊断信息字典
        """
        diagnosis = {
            'has_inconsistency': False,
            'issues': [],
            'recommendations': []
        }
        
        if len(segment_fits) < 2:
            return diagnosis
        
        # 1. 检查模型类型一致性
        best_models = {}
        for seg in segment_fits:
            if seg.model_fits:
                best_model = max(seg.model_fits.keys(), 
                               key=lambda m: seg.model_fits[m].get('r2', 0))
                best_r2 = seg.model_fits[best_model].get('r2', 0)
                if best_r2 > 0.3:
                    best_models[seg.segment_idx] = best_model
        
        unique_models = set(best_models.values())
        if len(unique_models) > 1:
            diagnosis['has_inconsistency'] = True
            diagnosis['issues'].append(
                f"各段最佳模型不一致: {dict(best_models)}"
            )
            diagnosis['recommendations'].append(
                "建议使用更长的稳定数据段，或确认系统是否存在非线性"
            )
        
        # 2. 检查K值一致性
        k_values = {}
        for seg in segment_fits:
            for model_type, fit in seg.model_fits.items():
                if fit.get('r2', 0) > 0.3 and fit.get('k_reasonable', True):
                    if model_type not in k_values:
                        k_values[model_type] = []
                    k_values[model_type].append((seg.segment_idx, fit.get('K', 0)))
        
        for model_type, values in k_values.items():
            if len(values) > 1:
                ks = [v[1] for v in values]
                k_cv = np.std(ks) / (abs(np.mean(ks)) + 1e-8)
                if k_cv > 0.5:
                    diagnosis['has_inconsistency'] = True
                    diagnosis['issues'].append(
                        f"{model_type}的K值变异系数={k_cv:.2f}，各段差异大"
                    )
        
        # 3. 检查非线性问题
        nonlinear_count = sum(1 for s in segment_fits if s.is_nonlinear)
        if nonlinear_count > 0:
            diagnosis['issues'].append(
                f"{nonlinear_count}/{len(segment_fits)}个段检测到非线性"
            )
            if nonlinear_count > len(segment_fits) // 2:
                diagnosis['recommendations'].append(
                    "多数段呈现非线性特征，建议考虑分段模型或非线性辨识"
                )
        
        # 4. 检查数据质量
        low_quality_count = sum(1 for s in segment_fits if s.quality_score < 0.4)
        if low_quality_count > len(segment_fits) // 2:
            diagnosis['issues'].append(
                f"{low_quality_count}/{len(segment_fits)}个段数据质量较低"
            )
            diagnosis['recommendations'].append(
                "建议使用更干净的阶跃响应数据"
            )
        
        return diagnosis
