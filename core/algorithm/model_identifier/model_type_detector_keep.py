import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Union

try:
    from .config import Config, ModelType
    from .identifier import ModelIdentifier
    from .preprocessor import DataPreprocessor
    from .model_type_detector import (
        TuningWindow, TuningParams, TuningInput, HistoricalData, ModelBase
    )
except ImportError:
    from config import Config, ModelType
    from identifier import ModelIdentifier
    from preprocessor import DataPreprocessor
    from model_type_detector import (
        TuningWindow, TuningParams, TuningInput, HistoricalData, ModelBase
    )


class ModelFitterSimple(ModelBase):
    """

    算法流程：
    1. 逐窗口、逐模型辨识 KTL（每个模型类型在每个窗口独立计算参数）
    2. 每种模型取 KTL 中位数（对所有窗口的参数取中位数）
    3. 用中位数 KTL 在全部数据上进行模型拟合，计算 R² 评分
    4. 选 R² 最高的模型作为最终模型，输出其参数
    
    使用示例:
        >>> fitter = ModelFitterSimple(verbose=True)
        >>> result = fitter.fit(tuning_input, raw_data)
    """
    
    def __init__(self, verbose: bool = False, enable_preprocess: bool = True):
        super().__init__(verbose)
        self.enable_preprocess = enable_preprocess
    
    def log(self, msg: str):
        """日志输出"""
        if self.verbose:
            print(msg)
    
    def fit(self, tuning_input: Union[Dict[str, Any], TuningInput], 
            raw_data: List[Dict[str, Any]],
            lambda_factor: float = 0.8) -> Dict[str, Any]:
        """
        简化版模型整定主入口
        
        Args:
            tuning_input: 整定输入（包含 tuning_window 列表）
            raw_data: 原始时序数据
            lambda_factor: Lambda 整定系数
        
        Returns:
            整定结果字典
        """
        # ============================================================
        # 1. 输入解析
        # ============================================================
        input_data = self._parse_tuning_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result({
                'start_time': getattr(input_data, 'start_time', None) if input_data else None,
                'end_time': getattr(input_data, 'end_time', None) if input_data else None
            })
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        self.log(f"📥 输入: {len(input_data.tuning_window)} 个扰动窗口, {len(raw_data)} 条数据")
        
        # ============================================================
        # 2. 提取各窗口数据
        # ============================================================
        segments = self._extract_all_segments(hist_data, input_data.tuning_window)
        if not segments:
            self.log("⚠️ 无有效扰动段")
            return self._empty_result(time_range)
        
        self.log(f"📊 提取 {len(segments)} 个有效扰动段")
        
        # ============================================================
        # 3. 逐窗口、逐模型计算 KTL
        # ============================================================
        model_window_results = self._compute_ktl_per_window(segments)
        
        # ============================================================
        # 4. 每种模型取 KTL 中位数
        # ============================================================
        model_median_params = self._compute_median_ktl(model_window_results)
        
        # ============================================================
        # 5. 用中位数 KTL 在全部数据上评估（分段仿真）
        # ============================================================
        best_result = self._evaluate_on_full_data(hist_data, model_median_params, segments)
        if best_result is None:
            return self._empty_result(time_range)
        
        # ============================================================
        # 6. 构建最终输出
        # ============================================================
        return self._build_final_result(best_result, time_range, lambda_factor)
    
    def _parse_tuning_input(self, tuning_input: Union[Dict, TuningInput]) -> Optional[TuningInput]:
        """解析输入"""
        if tuning_input is None:
            return None
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        return TuningInput.from_dict(tuning_input)
    
    def _extract_all_segments(self, hist_data: HistoricalData, 
                               windows: List[TuningWindow]) -> List[HistoricalData]:
        """提取所有窗口的数据段"""
        segments = []
        timestamps = hist_data.timestamp
        
        for i, window in enumerate(windows):
            # 解析窗口时间
            start_ts = self._parse_timestamp(window.start_time)
            end_ts = self._parse_timestamp(window.end_time)
            
            if start_ts is None or end_ts is None:
                continue
            
            # 查找时间范围内的数据
            mask = (timestamps >= start_ts) & (timestamps <= end_ts)
            indices = np.where(mask)[0]
            
            if len(indices) < 20:
                self.log(f"⚠️ 窗口 {i+1}: 数据不足 ({len(indices)} 点)")
                continue
            
            segment = HistoricalData(
                timestamp=hist_data.timestamp[indices],
                pv=hist_data.pv[indices],
                sv=hist_data.sv[indices],
                mv=hist_data.mv[indices]
            )
            segments.append(segment)
            self.log(f"📍 窗口 {i+1}: {len(indices)} 点")
        
        return segments
    
    def _parse_timestamp(self, ts: Any) -> Optional[float]:
        """解析时间戳"""
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
    
    def _compute_ktl_per_window(self, segments: List[HistoricalData]
                                 ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Step 3: 逐窗口、逐模型计算 KTL
        
        Returns:
            {model_type: [{K, T1, T2, L, r2, window_idx}, ...]}
        """
        results = {model: [] for model in self.CANDIDATE_MODELS}
        
        for win_idx, segment in enumerate(segments):
            # 准备数据
            y, u, t = self._prepare_segment_data(segment)
            if y is None or len(y) < 20:
                continue
            
            self.log(f"\n📊 窗口 {win_idx + 1}: {len(y)} 有效点")
            
            # 计算基准
            y0 = np.mean(y[:max(1, min(10, len(y) // 10))])
            u0 = np.median(u)
            u_delta = u - u0
            
            # 逐模型辨识
            for model_type in self.CANDIDATE_MODELS:
                try:
                    raw_params = self.identify_model(t, y, u_delta, model_type)
                    params = self.normalize_params(raw_params, model_type)
                    
                    # 仿真并计算 R²
                    y_pred = self.simulate_model(raw_params, t, u_delta, y0, model_type)
                    
                    # 计算真实R²（不截断，用于诊断）
                    ss_res = np.sum((y - y_pred) ** 2)
                    ss_tot = np.sum((y - np.mean(y)) ** 2)
                    r2_raw = 1 - (ss_res / ss_tot) if ss_tot > 1e-10 else 0.0
                    r2 = max(0.0, min(1.0, r2_raw))  # 截断后的R²
                    
                    results[model_type].append({
                        'K': params['K'],
                        'T1': params['T1'],
                        'T2': params['T2'],
                        'L': params['L'],
                        'r2': r2,
                        'r2_raw': r2_raw,  # 保留真实R²
                        'window_idx': win_idx + 1
                    })
                    
                    # 显示真实R²（负值说明参数方向错误）
                    r2_info = f"R²={r2:.4f}" if r2_raw >= 0 else f"R²={r2:.4f}(真实:{r2_raw:.2f})"
                    self.log(f"   {model_type}: K={params['K']:.4f}, "
                             f"T1={params['T1']:.2f}, T2={params['T2']:.2f}, "
                             f"L={params['L']:.2f}, {r2_info}")
                    
                except Exception as e:
                    self.log(f"   {model_type}: 辨识失败 - {e}")
        
        # 打印每段 KTL 汇总表
        self._print_ktl_summary(results)
        
        return results
    
    def _print_ktl_summary(self, results: Dict[str, List[Dict]]):
        """打印每段 KTL 汇总表"""
        if not self.verbose:
            return
        
        self.log(f"\n{'='*80}")
        self.log("📋 各窗口 KTL 汇总")
        self.log('='*80)
        
        # 表头
        header = f"{'模型':<15} | {'窗口':<4} | {'K':>10} | {'T1':>10} | {'T2':>10} | {'L':>8} | {'R²':>8}"
        self.log(header)
        self.log("-" * 80)
        
        for model_type in self.CANDIDATE_MODELS:
            window_results = results.get(model_type, [])
            if not window_results:
                continue
            
            for r in window_results:
                row = (f"{model_type:<15} | {r['window_idx']:<4} | "
                       f"{r['K']:>10.4f} | {r['T1']:>10.2f} | "
                       f"{r['T2']:>10.2f} | {r['L']:>8.2f} | {r['r2']:>8.4f}")
                self.log(row)
        
        self.log('='*80)
    
    def _prepare_segment_data(self, segment: HistoricalData
                               ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """准备单段数据（过滤异常）"""
        y, u = segment.pv, segment.mv
        
        # 过滤 PV=0 的异常点
        valid_mask = y != 0
        if np.sum(valid_mask) < 20:
            valid_mask = np.ones(len(y), dtype=bool)
        
        y = y[valid_mask]
        u = u[valid_mask]
        t = np.arange(len(y), dtype=float)
        
        return y, u, t
    
    def _compute_median_ktl(self, model_window_results: Dict[str, List[Dict]]
                            ) -> Dict[str, Dict[str, float]]:
        """
        Step 2: 每种模型取 KTL 中位数
        
        策略：
        1. 过滤异常窗口（R² < 0.3 或 K值符号与多数不一致）
        2. 对过滤后的窗口，计算 K, T1, T2, L 的中位数
        3. 如果过滤后无有效窗口，回退到 R² 最高的窗口
        
        Returns:
            {model_type: {K, T1, T2, L, window_count, method}}
        """
        R2_THRESHOLD = 0.3  # 最低 R² 阈值
        
        median_params = {}
        
        self.log(f"\n{'='*60}")
        self.log("📊 各模型 KTL 中位数计算")
        self.log('='*60)
        
        for model_type, window_results in model_window_results.items():
            if not window_results:
                continue
            
            n_windows = len(window_results)
            
            # 提取各窗口的参数
            K_values = np.array([r['K'] for r in window_results])
            T1_values = np.array([r['T1'] for r in window_results])
            T2_values = np.array([r['T2'] for r in window_results])
            L_values = np.array([r['L'] for r in window_results])
            r2_values = np.array([r['r2'] for r in window_results])
            window_indices = [r['window_idx'] for r in window_results]
            
            # ============================================================
            # 过滤异常窗口
            # ============================================================
            # 条件1: R² >= 阈值
            r2_mask = r2_values >= R2_THRESHOLD
            
            # 条件2: K值符号与多数一致（正/负一致性）
            K_sign_majority = np.sign(np.median(K_values))  # 多数K的符号
            sign_mask = np.sign(K_values) == K_sign_majority
            
            # 组合条件
            valid_mask = r2_mask & sign_mask
            valid_count = np.sum(valid_mask)
            
            self.log(f"\n📊 {model_type}: {n_windows} 个窗口")
            
            # 显示过滤情况
            for i, (r2, K, idx) in enumerate(zip(r2_values, K_values, window_indices)):
                status = "✓" if valid_mask[i] else "✗"
                reason = ""
                if not r2_mask[i]:
                    reason = f"R²<{R2_THRESHOLD}"
                elif not sign_mask[i]:
                    reason = f"K符号异常"
                self.log(f"   窗口{idx}: K={K:.4f}, R²={r2:.4f} {status} {reason}")
            
            # ============================================================
            # 计算中位数
            # ============================================================
            if valid_count >= 1:
                # 在有效窗口中计算中位数
                K_median = float(np.median(K_values[valid_mask]))
                T1_median = float(np.median(T1_values[valid_mask]))
                T2_median = float(np.median(T2_values[valid_mask]))
                L_median = float(np.median(L_values[valid_mask]))
                method = f'中位数({valid_count}/{n_windows}窗口)'
                
                self.log(f"   → 使用 {valid_count} 个有效窗口计算中位数")
            else:
                # 回退：选择 R² 最高的窗口
                best_idx = np.argmax(r2_values)
                K_median = float(K_values[best_idx])
                T1_median = float(T1_values[best_idx])
                T2_median = float(T2_values[best_idx])
                L_median = float(L_values[best_idx])
                method = f'回退到窗口{window_indices[best_idx]}(无有效窗口)'
                
                self.log(f"   → 无有效窗口，回退到R²最高的窗口{window_indices[best_idx]}")
            
            self.log(f"   → 最终KTL: K={K_median:.4f}, T1={T1_median:.2f}, "
                     f"T2={T2_median:.2f}, L={L_median:.2f}")
            
            median_params[model_type] = {
                'K': K_median,
                'T1': T1_median,
                'T2': T2_median,
                'L': L_median,
                'window_count': valid_count if valid_count >= 1 else 1,
                'method': method
            }
        
        return median_params
    
    def _evaluate_on_full_data(self, hist_data: HistoricalData,
                                 model_median_params: Dict[str, Dict],
                                 segments: List[HistoricalData] = None
                                 ) -> Optional[Dict[str, Any]]:
        """
        Step 5: 用中位数 KTL 在全部数据上评估，选择 R² 最高的模型
        
        逻辑：
        1. 对每个模型类型，用其中位数 KTL 在全部扰动段数据上分段仿真
        2. 合并所有段计算总体 R² 评分
        3. 选择 R² 最高的模型作为最终模型
        
        注意：
        - 分段仿真避免长时间序列的漂移问题
        - 每段使用各自的 y0/u0 基准值
        
        Returns:
            最佳模型的结果字典
        """
        self.log(f"\n{'='*60}")
        self.log("📊 全部数据评估（分段仿真）")
        self.log('='*60)
        
        # 如果没有提供 segments，则从 hist_data 整体评估（不推荐）
        if segments is None or len(segments) == 0:
            self.log("⚠️ 无扰动段数据")
            return None
        
        self.log(f"📊 共 {len(segments)} 个扰动段")
        
        best_result = None
        best_r2 = -np.inf
        all_scores = {}
        
        for model_type, params in model_median_params.items():
            try:
                raw_params = self._params_dict_to_tuple(params, model_type)
                
                # 分段仿真，收集所有段的真实值和预测值
                all_y_true = []
                all_y_pred = []
                all_timestamps = []
                all_sv = []
                all_mv = []
                
                for seg_idx, seg in enumerate(segments):
                    # 过滤无效数据
                    valid_mask = seg.pv != 0
                    if np.sum(valid_mask) < 10:
                        continue
                    
                    y = seg.pv[valid_mask]
                    u = seg.mv[valid_mask]
                    
                    # 每段使用各自的基准值
                    n_init = max(1, min(5, len(y) // 10))
                    y0 = np.mean(y[:n_init])
                    u0 = np.median(u)
                    u_delta = u - u0
                    t = np.arange(len(y), dtype=float)
                    
                    # 仿真该段
                    y_pred = self.simulate_model(raw_params, t, u_delta, y0, model_type)
                    
                    all_y_true.append(y)
                    all_y_pred.append(y_pred)
                    all_timestamps.append(seg.timestamp[valid_mask])
                    all_sv.append(seg.sv[valid_mask])
                    all_mv.append(u)
                
                if not all_y_true:
                    continue
                
                # 合并所有段计算总体 R²
                y_merged = np.concatenate(all_y_true)
                y_pred_merged = np.concatenate(all_y_pred)
                
                r2 = self.calculate_r2(y_merged, y_pred_merged)
                rmse = self.calculate_rmse(y_merged, y_pred_merged)
                
                all_scores[model_type] = r2
                rating = "优秀" if r2 >= 0.9 else "良好" if r2 >= 0.7 else "一般" if r2 >= 0.5 else "较差"
                
                self.log(f"🎯 {model_type}: R²={r2:.4f} ({rating}), RMSE={rmse:.4f}")
                self.log(f"   KTL: K={params['K']:.4f}, T1={params['T1']:.2f}, "
                         f"T2={params['T2']:.2f}, L={params['L']:.2f}")
                
                if r2 > best_r2:
                    best_r2 = r2
                    best_result = {
                        'model_type': model_type,
                        'params': params,
                        'r2': r2,
                        'rmse': rmse,
                        'y_pred': y_pred_merged,
                        'hist_data': HistoricalData(
                            timestamp=np.concatenate(all_timestamps),
                            pv=y_merged,
                            sv=np.concatenate(all_sv),
                            mv=np.concatenate(all_mv)
                        )
                    }
                    
            except Exception as e:
                self.log(f"⚠️ {model_type} 评估失败: {e}")
                all_scores[model_type] = 0.0
        
        if best_result:
            p = best_result['params']
            rating = "优秀" if best_r2 >= 0.9 else "良好" if best_r2 >= 0.7 else "一般" if best_r2 >= 0.5 else "较差"
            self.log(f"\n✅ 最佳模型: {best_result['model_type']}, R²={best_r2:.4f} ({rating})")
            self.log(f"   KTL: K={p['K']:.4f}, T1={p['T1']:.4f}, T2={p['T2']:.4f}, L={p['L']:.4f}")
            best_result['all_scores'] = all_scores
        
        return best_result
    
    def _params_dict_to_tuple(self, params: Dict[str, float], model_type: str) -> tuple:
        """参数字典转元组"""
        converter = self.PARAMS_TO_TUPLE.get(model_type)
        if converter:
            return converter(params)
        return (params['K'], params['T1'], params['L'])
    
    def _build_final_result(self, best_result: Dict, 
                            time_range: Dict,
                            lambda_factor: float) -> Dict[str, Any]:
        """构建最终输出"""
        params = best_result['params']
        model_type = best_result['model_type']
        hist_data = best_result['hist_data']
        
        # 计算 PID 参数
        pid_params = self._calculate_pid(
            params['K'], params['T1'], params['T2'], params['L'],
            model_type, lambda_factor
        )
        
        return {
            'model_type': model_type,
            'model_rating': round(best_result['r2'] * 10, 2),
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {
                'K': round(params['K'], 4),
                'T1': round(params['T1'], 4),
                'T2': round(params['T2'], 4),
                'L': round(params['L'], 4)
            },
            'pid_parameters': {
                'Kp': float(pid_params['Kp']),
                'Ki': float(pid_params['Ki']),
                'Kd': float(pid_params['Kd'])
            },
            'fitting_result': {
                'timestamp': hist_data.timestamp.tolist(),
                'sv': hist_data.sv.tolist(),
                'pv': hist_data.pv.tolist(),
                'mv': hist_data.mv.tolist(),
                'pv_model': best_result['y_pred'].tolist(),
                'r_squared': round(best_result['r2'], 4),
                'rmse': round(best_result['rmse'], 4)
            }
        }
    
    def _calculate_pid(self, K: float, T1: float, T2: float, L: float,
                       model_type: str, lambda_factor: float) -> Dict[str, float]:
        """计算 PID 参数（Lambda 方法）"""
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
    
    def _empty_result(self, time_range: Dict) -> Dict[str, Any]:
        """空结果"""
        return {
            'model_type': ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': time_range.get('start_time'),
            'end_time': time_range.get('end_time'),
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            }
        }


# ============================================================
# 便捷函数
# ============================================================

def fit_model_simple(tuning_input: Union[Dict[str, Any], TuningInput],
                     raw_data: List[Dict[str, Any]],
                     verbose: bool = False,
                     lambda_factor: float = 0.8) -> Dict[str, Any]:
    """
    便捷函数：简化版模型拟合
    
    算法：逐窗口计算 KTL → 取中位数 → 全量数据评估 → 选最佳模型
    """
    return ModelFitterSimple(verbose=verbose).fit(tuning_input, raw_data, lambda_factor)


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    
    import numpy as np
    import pandas as pd
    from datetime import datetime
    from core.agent.tools import process_query_tsdb_data_interpolated
    from core.client.bff_model_client import BFFModelClient
    from core.client.real_tsdb_client import get_default_database
    from core.algorithm.tuning_segment.stability_detector import find_high_variability_periods
    
    # ============================================================
    # 数据获取
    # ============================================================
    
    def get_history_data(start_time: int, end_time: int, loop_uri: str = None) -> List[Dict]:
        """获取历史数据"""
        if loop_uri is None:
            loop_uri = '/pid_zd/0b521c82a96d4107a564e4c2678bdeca'
        
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
        db = get_default_database()
        
        history_data = process_query_tsdb_data_interpolated(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time,
            end_time=end_time,
            is_filter=False
        )
        
        if not history_data:
            print("❌ 未获取到历史数据")
            return []
        print(f"✅ 获取到历史数据：{len(history_data)} 条")
        return history_data
    
    def convert_to_arrays(data: List[Dict]) -> tuple:
        """将数据转换为numpy数组"""
        pv_array = np.array([d.get('pv', 0.0) for d in data], dtype=np.float64)
        sv_array = np.array([d.get('sv', 0.0) for d in data], dtype=np.float64)
        mv_array = np.array([d.get('mv', 0.0) for d in data], dtype=np.float64)
        timestamps = np.array([d.get('timestamp', 0) for d in data], dtype=np.int64)
        return pv_array, sv_array, mv_array, timestamps
    
    # ============================================================
    # 扰动段检测（使用 stability_detector）
    # ============================================================
    
    def detect_tuning_windows(data: List[Dict]) -> Dict:
        """
        使用 stability_detector 检测扰动段，返回 tuning_input 格式
        """
        pv_array, sv_array, mv_array, timestamps = convert_to_arrays(data)
        
        # 构建 pandas Series
        time_index = pd.to_datetime(timestamps, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
        pv_series = pd.Series(pv_array, index=time_index)
        sv_series = pd.Series(sv_array, index=time_index)
        
        # 调用 StabilityDetector 获取整定窗口
        result = find_high_variability_periods(
            pv_series=pv_series,
            sv_series=sv_series,
            std_tol=0.2,
            min_len=10,
            min_segment_len=20
        )
        
        # 转换 tuning_window 时间为毫秒时间戳
        if result.get('tuning_window'):
            converted_windows = []
            for w in result['tuning_window']:
                start_dt = w['start_time']
                end_dt = w['end_time']
                
                # 找到最接近的原始时间戳
                start_ms = _find_closest_timestamp(timestamps, time_index, start_dt)
                end_ms = _find_closest_timestamp(timestamps, time_index, end_dt)
                
                converted_windows.append({
                    'start_time': start_ms,
                    'end_time': end_ms,
                    'start_time_str': str(start_dt),
                    'end_time_str': str(end_dt)
                })
            result['tuning_window'] = converted_windows
        
        return result
    
    def _find_closest_timestamp(timestamps: np.ndarray, time_index: pd.DatetimeIndex, 
                                 target_dt: pd.Timestamp) -> int:
        """找到最接近目标时间的原始时间戳"""
        idx = time_index.get_indexer([target_dt], method='nearest')[0]
        if 0 <= idx < len(timestamps):
            return int(timestamps[idx])
        return int(timestamps[0])
    
    # ============================================================
    # 可视化
    # ============================================================
    
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    
    # 设置中文字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
    
    def plot_fitting_result(raw_data: List[Dict], tuning_input: Dict, 
                            fitting_result: Dict, scenario_name: str = None):
        """
        可视化拟合结果
        
        Args:
            raw_data: 原始数据
            tuning_input: 整定输入（包含 tuning_window）
            fitting_result: 拟合结果
            scenario_name: 场景名称（用于文件命名）
        """
        # 提取原始数据
        pv_array, sv_array, mv_array, timestamps = convert_to_arrays(raw_data)
        # 使用本地时间（与 tuning_window 一致）
        time_array = pd.to_datetime(timestamps, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
        
        # 提取拟合结果
        fit_data = fitting_result.get('fitting_result', {})
        fit_timestamps = fit_data.get('timestamp', [])
        fit_pv = fit_data.get('pv', [])
        fit_pv_model = fit_data.get('pv_model', [])
        
        if fit_timestamps:
            fit_time_array = pd.to_datetime(fit_timestamps, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
        else:
            fit_time_array = None
        
        # 创建图表
        fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
        
        model_type = fitting_result.get('model_type', 'Unknown')
        r2 = fit_data.get('r_squared', 0)
        rmse = fit_data.get('rmse', 0)
        fig.suptitle(f'ModelFitterSimple 拟合结果 - {model_type} (R²={r2:.4f}, RMSE={rmse:.4f})', 
                     fontsize=14, fontweight='bold')
        
        # ========== 子图1: PV/SV + 拟合曲线 ==========
        ax1 = axes[0]
        ax1.plot(time_array, pv_array, 'b-', label='PV (实测)', linewidth=0.8, alpha=0.7)
        ax1.plot(time_array, sv_array, 'r--', label='SV (设定值)', linewidth=1.2)
        
        if fit_time_array is not None and fit_pv_model:
            ax1.plot(fit_time_array, fit_pv_model, 'g-', label='PV_model (拟合)', linewidth=1.5, alpha=0.9)
        
        # 标记 tuning_window（扰动段）
        tuning_windows = tuning_input.get('tuning_window', [])
        for i, w in enumerate(tuning_windows):
            start_ts = w.get('start_time')
            end_ts = w.get('end_time')
            if start_ts and end_ts:
                if isinstance(start_ts, (int, float)):
                    # 毫秒时间戳转换为本地时间（与 time_array 一致）
                    start_dt = pd.to_datetime(start_ts, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
                    end_dt = pd.to_datetime(end_ts, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
                else:
                    start_dt = start_ts
                    end_dt = end_ts
                ax1.axvspan(start_dt, end_dt, alpha=0.2, color='orange', 
                           label='扰动段' if i == 0 else None)
        
        ax1.set_ylabel('PV / SV')
        ax1.set_title('过程值与模型拟合对比')
        ax1.legend(loc='upper right')
        ax1.grid(True, alpha=0.3)
        
        # ========== 子图2: MV ==========
        ax2 = axes[1]
        ax2.plot(time_array, mv_array, 'g-', label='MV', linewidth=0.8)
        
        for i, w in enumerate(tuning_windows):
            start_ts = w.get('start_time')
            end_ts = w.get('end_time')
            if start_ts and end_ts:
                if isinstance(start_ts, (int, float)):
                    start_dt = pd.to_datetime(start_ts, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
                    end_dt = pd.to_datetime(end_ts, unit='ms', utc=True).tz_convert('Asia/Shanghai').tz_localize(None)
                else:
                    start_dt = start_ts
                    end_dt = end_ts
                ax2.axvspan(start_dt, end_dt, alpha=0.2, color='orange')
        
        ax2.set_ylabel('MV')
        ax2.set_title('操作值(MV)')
        ax2.legend(loc='upper right')
        ax2.grid(True, alpha=0.3)
        
        # ========== 子图3: 拟合误差 ==========
        ax3 = axes[2]
        if fit_time_array is not None and fit_pv and fit_pv_model:
            error = np.array(fit_pv) - np.array(fit_pv_model)
            ax3.plot(fit_time_array, error, 'r-', label='误差 (PV - PV_model)', linewidth=0.8)
            ax3.axhline(y=0, color='black', linestyle='--', linewidth=0.5)
            ax3.fill_between(fit_time_array, error, 0, alpha=0.3, color='red')
        
        ax3.set_ylabel('误差')
        ax3.set_xlabel('时间')
        ax3.set_title('拟合误差')
        ax3.legend(loc='upper right')
        ax3.grid(True, alpha=0.3)
        
        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        
        plt.tight_layout()
        
        if scenario_name:
            filename = f'model_fitter_simple_{scenario_name}.png'
        else:
            filename = 'model_fitter_simple_result.png'
        
        filepath = f'/Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/test/{filename}'
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        print(f"\n📊 图表已保存至: test/{filename}")
        plt.close()
    
    # ============================================================
    # 主测试流程
    # ============================================================
    
    test_scenario = {
        'start_time': '2025-12-04 08:55:58', 
        'end_time': '2025-12-04 10:30:58'
    }
    
    print("="*60)
    print(f"场景: {test_scenario['start_time']} ~ {test_scenario['end_time']}")
    print("="*60)
    
    start_ts = int(datetime.strptime(test_scenario['start_time'], '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
    end_ts = int(datetime.strptime(test_scenario['end_time'], '%Y-%m-%d %H:%M:%S').timestamp() * 1000)
    
    # 1. 获取数据
    raw_data = get_history_data(start_ts, end_ts)
    if not raw_data:
        print("无数据，退出")
        sys.exit(1)
    
    # 2. 使用 stability_detector 检测扰动窗口
    print("\n📊 检测扰动窗口...")
    tuning_input = detect_tuning_windows(raw_data)
    
    if not tuning_input.get('tuning_window'):
        print("❌ 未检测到扰动窗口")
        sys.exit(1)
    
    print(f"✅ 检测到 {tuning_input.get('total_windows', 0)} 个扰动窗口:")
    for i, w in enumerate(tuning_input['tuning_window'], 1):
        print(f"   [{i}] {w.get('start_time_str', w['start_time'])} ~ {w.get('end_time_str', w['end_time'])}")
    
    # 3. 运行简化版拟合
    print("\n" + "="*60)
    print("ModelFitterSimple 测试")
    print("="*60)
    
    fitter = ModelFitterSimple(verbose=True)
    result = fitter.fit(tuning_input, raw_data, lambda_factor=0.8)
    
    # 4. 输出结果
    print(f"\n{'='*60}")
    print("📤 最终输出")
    print('='*60)
    print(f"模型类型: {result['model_type']}")
    print(f"模型评分: {result['model_rating']}")
    print(f"KTL: K={result['model_parameters']['K']}, "
          f"T1={result['model_parameters']['T1']}, "
          f"T2={result['model_parameters']['T2']}, "
          f"L={result['model_parameters']['L']}")
    print(f"PID: Kp={result['pid_parameters']['Kp']}, "
          f"Ki={result['pid_parameters']['Ki']}, "
          f"Kd={result['pid_parameters']['Kd']}")
    print(f"R²={result['fitting_result']['r_squared']}, "
          f"RMSE={result['fitting_result']['rmse']}")
    
    # 5. 可视化
    plot_fitting_result(raw_data, tuning_input, result, 
                        scenario_name=test_scenario['start_time'].replace(' ', '_').replace(':', '-'))
