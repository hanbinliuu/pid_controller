#!/usr/bin/env python3
"""
控制系统性能评估算法
提供多种评估指标，包括稳定性、响应速度、控制精度等
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Union
import logging
from scipy import signal
from scipy.stats import pearsonr

logger = logging.getLogger(__name__)


class PerformanceEvaluator:
    """控制系统性能评估器"""

    @staticmethod
    def calculate_stability_metrics(
        time: List[float],
        PV: List[float],
        SV: List[float],
        MV: List[float]
    ) -> Dict[str, Any]:
        """
        计算稳定性相关指标
        
        参数:
            time: 时间序列 (秒)
            PV: 过程变量 (PV)
            SV: 设定值 (SP)
            MV: 控制输出 (MV)
            
        返回:
            稳定性指标字典
        """
        try:
            t = np.array(time)
            pv = np.array(PV)
            sv = np.array(SV)
            mv = np.array(MV)
            
            # 计算误差
            error = sv - pv
            abs_error = np.abs(error)
            
            # 1. 平均绝对误差 (MAE)
            mae = np.mean(abs_error)
            
            # 2. 均方误差 (MSE)
            mse = np.mean(error ** 2)
            
            # 3. 均方根误差 (RMSE)
            rmse = np.sqrt(mse)
            
            # 4. 平均绝对百分比误差 (MAPE)
            mape = np.mean(np.abs(error / (sv + 1e-8))) * 100  # 避免除零
            
            # 5. 标准差 (衡量波动性)
            pv_std = np.std(pv)
            mv_std = np.std(mv)
            
            # 6. 变异系数 (无量纲波动性指标)
            pv_cv = (pv_std / (np.mean(np.abs(pv)) + 1e-8)) * 100
            mv_cv = (mv_std / (np.mean(np.abs(mv)) + 1e-8)) * 100
            
            # 7. 超调量 (%)
            steady_state = np.mean(sv[-10:]) if len(sv) >= 10 else sv[-1]
            max_pv = np.max(pv)
            overshoot = ((max_pv - steady_state) / (steady_state + 1e-8)) * 100 if steady_state > 0 else 0
            
            # 8. 控制信号变化率 (衡量控制动作剧烈程度)
            mv_diff = np.diff(mv)
            mv_rate = np.mean(np.abs(mv_diff)) if len(mv_diff) > 0 else 0
            
            return {
                "mae": float(mae),
                "mse": float(mse),
                "rmse": float(rmse),
                "mape": float(mape),
                "pv_std": float(pv_std),
                "mv_std": float(mv_std),
                "pv_cv": float(pv_cv),
                "mv_cv": float(mv_cv),
                "overshoot_percent": float(overshoot), #超调率
                "control_variation_rate": float(mv_rate)
            }
            
        except Exception as e:
            logger.error(f"计算稳定性指标失败: {str(e)}")
            return {}

    @staticmethod
    def calculate_response_metrics(
        time: List[float],
        PV: List[float],
        SV: List[float]
    ) -> Dict[str, Any]:
        """
        计算响应性能指标（）
        
        参数:
            time: 时间序列 (秒)
            PV: 过程变量 (PV)
            SV: 设定值 (SP)
            
        返回:
            响应性能指标字典
        """
        try:
            t = np.array(time)
            pv = np.array(PV)
            sv = np.array(SV)
            
            # 稳态值
            steady_state = np.mean(sv[-10:]) if len(sv) >= 10 else sv[-1]
            initial_value = np.mean(pv[:10]) if len(pv) >= 10 else pv[0]
            
            # 上升时间 (10% -> 90%)
            rise_start = initial_value + 0.1 * (steady_state - initial_value)
            rise_end = initial_value + 0.9 * (steady_state - initial_value)
            
            rise_start_idx = np.where(pv >= rise_start)[0]
            rise_end_idx = np.where(pv >= rise_end)[0]
            
            if len(rise_start_idx) > 0 and len(rise_end_idx) > 0:
                rise_time = t[rise_end_idx[0]] - t[rise_start_idx[0]]
            else:
                rise_time = None
            
            # 调节时间 (进入±2%稳态误差带)
            tolerance = 0.02 * abs(steady_state - initial_value) if steady_state != initial_value else 0.01
            settling_indices = np.where(np.abs(pv - steady_state) <= tolerance)[0]
            
            if len(settling_indices) > 0:
                settling_time = t[settling_indices[0]]
            else:
                settling_time = None
            
            # 峰值时间和峰值
            peak_idx = np.argmax(np.abs(pv - initial_value))
            peak_time = t[peak_idx] if len(t) > peak_idx else None
            peak_value = pv[peak_idx] if len(pv) > peak_idx else None
            
            # 超调量
            if steady_state > 0 and peak_value is not None:
                overshoot = ((peak_value - steady_state) / steady_state) * 100
            else:
                overshoot = 0.0
            
            # 稳态误差
            steady_state_error = abs(steady_state - sv[-1]) if len(sv) > 0 else 0
            
            return {
                "rise_time": float(rise_time) if rise_time is not None else None,
                "settling_time": float(settling_time) if settling_time is not None else None,
                "peak_time": float(peak_time) if peak_time is not None else None,
                "peak_value": float(peak_value) if peak_value is not None else None,
                "overshoot_percent": float(overshoot),
                "steady_state_error": float(steady_state_error)
            }
            
        except Exception as e:
            logger.error(f"计算响应指标失败: {str(e)}")
            return {}

    @staticmethod
    def calculate_control_efficiency_metrics(
        time: List[float],
        PV: List[float],
        SV: List[float],
        MV: List[float],
        energy_cost_weight: float = 1.0
    ) -> Dict[str, Any]:
        """
        计算控制效率指标（自控率）
        
        参数:
            time: 时间序列 (秒)
            PV: 过程变量 (PV)
            SV: 设定值 (SP)
            MV: 控制输出 (MV)
            energy_cost_weight: 能耗权重系数
            
        返回:
            控制效率指标字典
        """
        try:
            t = np.array(time)
            pv = np.array(PV)
            sv = np.array(SV)
            mv = np.array(MV)
            
            # 时间间隔
            dt = np.diff(t) if len(t) > 1 else np.array([1.0])
            if len(dt) == 0:
                dt = np.array([1.0])
            
            # 1. 积分绝对误差 (IAE)
            error = np.abs(sv[:len(pv)] - pv)
            iae = np.sum(error[:-1] * dt) if len(error) > 1 else 0
            
            # 2. 积分时间绝对误差 (ITAE)
            itae = np.sum(t[:len(error)] * error * dt) if len(error) > 1 else 0
            
            # 3. 积分平方误差 (ISE)
            error_sq = (sv[:len(pv)] - pv) ** 2
            ise = np.sum(error_sq[:-1] * dt) if len(error_sq) > 1 else 0
            
            # 4. 控制能量消耗 (控制信号平方积分)
            mv_sq = mv ** 2
            control_energy = np.sum(mv_sq[:-1] * dt) if len(mv_sq) > 1 else 0
            
            # 5. 加权性能指标 (考虑能耗)
            weighted_performance = iae + energy_cost_weight * control_energy
            
            # 6. 控制动作次数 (控制信号变化次数)
            mv_diff = np.diff(mv)
            control_actions = np.sum(np.abs(mv_diff) > 0.1)  # 大于0.1的变化视为一次动作
            
            return {
                "iae": float(iae),
                "itae": float(itae),
                "ise": float(ise),
                "control_energy": float(control_energy),
                "weighted_performance": float(weighted_performance),
                "control_actions": int(control_actions)
            }
            
        except Exception as e:
            logger.error(f"计算控制效率指标失败: {str(e)}")
            return {}

    @staticmethod
    def calculate_correlation_metrics(
        PV: List[float],
        MV: List[float]
    ) -> Dict[str, Any]:
        """
        计算相关性指标(平稳率)
        
        参数:
            PV: 过程变量 (PV)
            MV: 控制输出 (MV)
            
        返回:
            相关性指标字典
        """
        try:
            pv = np.array(PV)
            mv = np.array(MV)
            
            # 确保长度一致
            min_len = min(len(pv), len(mv))
            if min_len < 2:
                return {}
            
            pv = pv[:min_len]
            mv = mv[:min_len]
            
            # 计算皮尔逊相关系数
            correlation, p_value = pearsonr(pv, mv)
            
            # 计算互相关 (最大相关性及延迟)
            cross_corr = signal.correlate(pv - np.mean(pv), mv - np.mean(mv), mode='full')
            lags = signal.correlation_lags(len(pv), len(mv), mode='full')
            max_corr_idx = np.argmax(np.abs(cross_corr))
            max_correlation = cross_corr[max_corr_idx]
            delay = lags[max_corr_idx]
            
            return {
                "pearson_correlation": float(correlation),
                "correlation_p_value": float(p_value),
                "max_cross_correlation": float(max_correlation),
                "correlation_delay": int(delay)
            }
            
        except Exception as e:
            logger.error(f"计算相关性指标失败: {str(e)}")
            return {}

    @staticmethod
    def comprehensive_performance_assessment(
        time: List[float],
        PV: List[float],
        SV: List[float],
        MV: List[float],
        energy_cost_weight: float = 1.0
    ) -> Dict[str, Any]:
        """
        综合性能评估
        
        参数:
            time: 时间序列 (秒)
            PV: 过程变量 (PV)
            SV: 设定值 (SP)
            MV: 控制输出 (MV)
            energy_cost_weight: 权重系数
            
        返回:
            综合性能评估结果
        """
        try:
            # 计算各类指标
            stability_metrics = PerformanceEvaluator.calculate_stability_metrics(
                time, PV, SV, MV
            )
            
            response_metrics = PerformanceEvaluator.calculate_response_metrics(
                time, PV, SV
            )
            
            efficiency_metrics = PerformanceEvaluator.calculate_control_efficiency_metrics(
                time, PV, SV, MV, energy_cost_weight
            )
            
            correlation_metrics = PerformanceEvaluator.calculate_correlation_metrics(
                PV, MV
            )
            
            # 计算综合评分 (0-100分)
            # 基于关键指标进行加权计算
            score_components = []
            
            # 稳定性评分 (权重30%)
            if "mae" in stability_metrics:
                # MAE越小越好，假设合理范围是0-5，转换为0-100分
                mae_score = max(0, 100 - (stability_metrics["mae"] * 20))
                score_components.append(mae_score * 0.3)
            
            # 响应速度评分 (权重25%)
            if "settling_time" in response_metrics and response_metrics["settling_time"] is not None:
                # 调节时间越短越好，假设合理范围是0-300秒，转换为0-100分
                settling_score = max(0, 100 - (response_metrics["settling_time"] / 3))
                score_components.append(settling_score * 0.25)
            
            # 超调量评分 (权重20%)
            if "overshoot_percent" in stability_metrics:
                # 超调量越小越好，假设合理范围是0-50%，转换为0-100分
                overshoot_score = max(0, 100 - stability_metrics["overshoot_percent"] * 2)
                score_components.append(overshoot_score * 0.2)
            
            # 控制能量评分 (权重15%)
            if "control_energy" in efficiency_metrics:
                # 控制能量越小越好，假设合理范围是0-10000，转换为0-100分
                energy_score = max(0, 100 - (efficiency_metrics["control_energy"] / 100))
                score_components.append(energy_score * 0.15)
            
            # 控制动作评分 (权重10%)
            if "control_actions" in efficiency_metrics:
                # 控制动作越少越好，假设合理范围是0-100次，转换为0-100分
                actions_score = max(0, 100 - efficiency_metrics["control_actions"])
                score_components.append(actions_score * 0.1)
            
            # 计算综合评分
            overall_score = sum(score_components) if score_components else 0
            
            return {
                "overall_score": float(overall_score),
                "stability_metrics": stability_metrics,
                "response_metrics": response_metrics,
                "efficiency_metrics": efficiency_metrics,
                "correlation_metrics": correlation_metrics,
                "score_breakdown": {
                    "stability_weight": 0.3,
                    "response_weight": 0.25,
                    "overshoot_weight": 0.2,
                    "energy_weight": 0.15,
                    "actions_weight": 0.1
                }
            }
            
        except Exception as e:
            logger.error(f"综合性能评估失败: {str(e)}")
            return {
                "overall_score": 0.0,
                "error": str(e)
            }

    @staticmethod
    def compare_control_strategies(
        strategy_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        比较不同控制策略的性能
        
        参数:
            strategy_results: 不同策略的评估结果列表，每个元素应包含'name'和'overall_score'字段
            
        返回:
            策略比较结果
        """
        try:
            if not strategy_results:
                return {}
            
            # 按综合评分排序
            sorted_results = sorted(strategy_results, key=lambda x: x.get('overall_score', 0), reverse=True)
            
            # 找出最佳策略
            best_strategy = sorted_results[0] if sorted_results else None
            
            # 计算相对性能
            if best_strategy and 'overall_score' in best_strategy:
                best_score = best_strategy['overall_score']
                for result in sorted_results:
                    if 'overall_score' in result:
                        result['relative_performance'] = (result['overall_score'] / best_score * 100) if best_score > 0 else 0
            
            return {
                "ranked_strategies": sorted_results,
                "best_strategy": best_strategy,
                "performance_comparison": {
                    result['name']: {
                        'score': result.get('overall_score', 0),
                        'relative_performance': result.get('relative_performance', 0)
                    } for result in sorted_results if 'name' in result
                }
            }
            
        except Exception as e:
            logger.error(f"控制策略比较失败: {str(e)}")
            return {}

    @staticmethod
    def calculate_auto_control_rate(
        time: List[float],
        auto_status: List[Union[int, str, bool]]
    ) -> Dict[str, Any]:
        """
        投入度维度：自控率 = 自动运行时间 / 总生产时间
        """
        try:
            t = np.array(time, dtype=float)
            # 归一化自动状态
            is_auto = []
            for s in auto_status:
                if isinstance(s, (int, float)):
                    is_auto.append(bool(s))
                elif isinstance(s, str):
                    is_auto.append(s.lower() in ["auto","1","255","true","自动"])
                elif isinstance(s, bool):
                    is_auto.append(s)
                else:
                    is_auto.append(False)
            is_auto = np.array(is_auto, dtype=bool)
            # 时间间隔
            if len(t) > 1:
                dt = np.diff(t)
            else:
                dt = np.array([], dtype=float)
            # 自动期步进掩码（相邻两点都为自动）
            auto_pairs = (is_auto[:-1] & is_auto[1:]) if len(is_auto) > 1 else np.array([], dtype=bool)
            auto_time = float(np.sum(dt[auto_pairs])) if len(dt) else 0.0
            total_time = float(t[-1] - t[0]) if len(t) > 1 else 0.0
            rate = (auto_time / total_time * 100.0) if total_time > 0 else 0.0
            return {
                "auto_control_rate": float(rate),
                "auto_control_time": int(auto_time),
                "total_time": int(total_time)
            }
        except Exception as e:
            logger.error(f"自控率计算失败: {str(e)}")
            return {"auto_control_rate": 0.0, "auto_control_time": 0, "total_time": 0, "error": str(e)}

    @staticmethod
    def calculate_stability_rate_auto(
        time: List[float],
        PV: List[float],
        SV: List[float],
        auto_status: List[Union[int, str, bool]],
        threshold_percent: float = 2.0
    ) -> Dict[str, Any]:
        """
        稳定性维度：平稳率 = PV在目标范围内的累计时间 / 自动运行时间
        """
        try:
            t = np.array(time)
            pv = np.array(PV)
            sv = np.array(SV)
            # 归一化自动状态
            is_auto = []
            for s in auto_status:
                if isinstance(s, (int, float)):
                    is_auto.append(bool(s))
                elif isinstance(s, str):
                    is_auto.append(s.lower() in ["auto","1","255","true","自动"])
                elif isinstance(s, bool):
                    is_auto.append(s)
                else:
                    is_auto.append(False)
            is_auto = np.array(is_auto, dtype=bool)
            # 时间间隔
            if len(t) > 1:
                dt = np.diff(t)
            else:
                dt = np.array([], dtype=float)
            # 自动期步进掩码
            auto_pairs = (is_auto[:-1] & is_auto[1:]) if len(is_auto) > 1 else np.array([], dtype=bool)
            auto_time = float(np.sum(dt[auto_pairs])) if len(dt) else 0.0
            # 阈值
            threshold = np.abs(sv) * (threshold_percent / 100.0)
            threshold = np.maximum(threshold, 0.01)
            # 稳定掩码（相邻两点都在阈值内）
            if len(pv) > 1:
                err = np.abs(pv - sv)
                stable_pairs = (err[:-1] <= threshold[:-1]) & (err[1:] <= threshold[1:])
            else:
                stable_pairs = np.array([], dtype=bool)
            # 自动且稳定的时长累计
            stable_in_auto_pairs = auto_pairs & stable_pairs
            stable_time = float(np.sum(dt[stable_in_auto_pairs])) if len(dt) else 0.0
            rate = (stable_time / auto_time * 100.0) if auto_time > 0 else 0.0
            return {
                "stability_rate": float(rate),
                "stable_time": int(stable_time),
                "auto_time": int(auto_time),
                "threshold_percent": float(threshold_percent)
            }
        except Exception as e:
            logger.error(f"自动期平稳率计算失败: {str(e)}")
            return {"stability_rate": 0.0, "stable_time": 0, "auto_time": 0, "error": str(e)}

    @staticmethod
    def calculate_precision_std_auto(
        PV: List[float],
        SV: List[float],
        auto_status: List[Union[int, str, bool]],
        use_SV: bool = True
    ) -> Dict[str, Any]:
        """
        精确性维度：自动运行期间的标准偏差（相对SP或相对均值）
        """
        try:
            pv = np.array(PV, dtype=float)
            sv = np.array(SV, dtype=float)
            # 自动掩码
            is_auto = []
            for s in auto_status:
                if isinstance(s, (int, float)):
                    is_auto.append(bool(s))
                elif isinstance(s, str):
                    is_auto.append(s.lower() in ["auto","1","true","自动"]) 
                elif isinstance(s, bool):
                    is_auto.append(s)
                else:
                    is_auto.append(False)
            is_auto = np.array(is_auto, dtype=bool)
            # 自动期数据
            pv_auto = pv[is_auto] if np.any(is_auto) else np.array([], dtype=float)
            sv_auto = sv [is_auto] if np.any(is_auto) else np.array([], dtype=float)
            if pv_auto.size < 2:
                return {"sigma_sv ": None, "sigma_mean": None}
            # 基于设定值的标准差
            sigma_sv = float(np.sqrt(np.mean((pv_auto - sv_auto) ** 2))) if use_SV else None
            # 基于平均值的标准差
            pv_mean = float(np.mean(pv_auto))
            sigma_mean = float(np.sqrt(np.mean((pv_auto - pv_mean) ** 2)))
            return {
                "sigma_sv ": sigma_sv ,
                "sigma_mean": sigma_mean,
                "pv_mean": pv_mean,
                "pv_sum_value": float(np.sum(pv_auto)),
                "pv_sum_squares": float(np.sum(pv_auto ** 2)),
            }
        except Exception as e:
            logger.error(f"自动期精确性(标准差)计算失败: {str(e)}")
            return {"sigma_sv ": None, "sigma_mean": None, "error": str(e)}

    @staticmethod
    def calculate_valve_activity_auto(
        time: List[float],
        MV: List[float],
        auto_status: List[Union[int, str, bool]]
    ) -> Dict[str, Any]:
        """
        高效性维度：自动运行期间阀门活动度（累计绝对变化CAC与输出标准差σ_op）
        """
        try:
            t = np.array(time, dtype=float)
            op = np.array(MV, dtype=float)
            # 自动掩码
            is_auto = []
            for s in auto_status:
                if isinstance(s, (int, float)):
                    is_auto.append(bool(s))
                elif isinstance(s, str):
                    is_auto.append(s.lower() in ["auto","1","true","自动"]) 
                elif isinstance(s, bool):
                    is_auto.append(s)
                else:
                    is_auto.append(False)
            is_auto = np.array(is_auto, dtype=bool)
            # 步进掩码（相邻两点都自动）
            auto_pairs = (is_auto[:-1] & is_auto[1:]) if len(is_auto) > 1 else np.array([], dtype=bool)
            # 累计绝对变化 CAC （在自动期步进内累加）
            if len(op) > 1:
                op_diff = np.diff(op)
                cac = float(np.sum(np.abs(op_diff[auto_pairs])))
            else:
                cac = 0.0
            # 输出标准差（自动期样本）
            op_auto = op[is_auto] if np.any(is_auto) else np.array([], dtype=float)
            sigma_op = float(np.std(op_auto)) if op_auto.size > 1 else None
            return {
                "cac": cac,
                "sigma_op": sigma_op,
                "mv_sum_value": float(np.sum(op_auto)),
                "mv_sum_squares": float(np.sum(op_auto ** 2)),
            }
        except Exception as e:
            logger.error(f"自动期阀门活动度计算失败: {str(e)}")
            return {"cac": 0.0, "sigma_op": None, "error": str(e)}

    @staticmethod
    def evaluate_loop_metrics(
        time: List[float],
        PV: List[float],
        SV: List[float],
        MV: List[float],
        auto_status: List[Union[int, str, bool]],
        threshold_percent: float = 2.0
    ) -> Dict[str, Any]:
        """
        汇总四个维度的核心指标（投入度/稳定性/精确性/高效性）
        """
        try:
            # 投入度（自控率）
            auto_res = PerformanceEvaluator.calculate_auto_control_rate(time, auto_status)
            # 稳定性（自动期平稳率）
            stable_res = PerformanceEvaluator.calculate_stability_rate_auto(time, PV, SV, auto_status, threshold_percent)
            # 精确性（自动期标准差）
            precision_res = PerformanceEvaluator.calculate_precision_std_auto(PV, SV, auto_status, use_SV=True)
            # 高效性（自动期阀门活动度）
            activity_res = PerformanceEvaluator.calculate_valve_activity_auto(time, MV, auto_status)
            return {
                "auto_control": auto_res,
                "stability": stable_res,
                "precision": precision_res,
                "valve_activity": activity_res
            }
        except Exception as e:
            logger.error(f"回路指标汇总计算失败: {str(e)}")
            return {"error": str(e)}

    @staticmethod
    def score_metric_auto_control(auto_control_rate: float) -> float:
        """
        自控率得分：直接使用百分比值作为得分 (0-100)
        """
        return max(0.0, min(100.0, auto_control_rate))

    @staticmethod
    def score_metric_stability(stability_rate: float) -> float:
        """
        平稳率得分：直接使用百分比值作为得分 (0-100)
        """
        return max(0.0, min(100.0, stability_rate))

    @staticmethod
    def score_metric_precision(sigma_sp: float, range_span: float, low_threshold: float = 0.5, high_threshold: float = 2.0) -> float:
        """
        精确性得分：基于标准差与量程百分比的线性映射
        - sigma_sp: 标准差
        - range_span: 量程范围 (max - min)
        - low_threshold: 得满分的阈值百分比 (默认0.5%量程)
        - high_threshold: 得0分的阈值百分比 (默认2.0%量程)
        """
        if sigma_sp is None or range_span <= 0:
            return 0.0
        # 转换为占量程的百分比
        sigma_percent = (sigma_sp / range_span) * 100.0
        # 线性映射
        if sigma_percent <= low_threshold:
            return 100.0
        elif sigma_percent >= high_threshold:
            return 0.0
        else:
            # 线性插值
            return 100.0 * (high_threshold - sigma_percent) / (high_threshold - low_threshold)

    @staticmethod
    def score_metric_efficiency(cac: float, low_threshold: float = 1000.0, high_threshold: float = 5000.0) -> float:
        """
        高效性得分：基于阀门累计绝对变化(CAC)的线性映射
        - cac: 累计绝对变化
        - low_threshold: 得满分的阈值 (默认1000)
        - high_threshold: 得0分的阈值 (默认5000)
        """
        if cac is None:
            return 0.0
        # 线性映射
        if cac <= low_threshold:
            return 100.0
        elif cac >= high_threshold:
            return 0.0
        else:
            # 线性插值
            return 100.0 * (high_threshold - cac) / (high_threshold - low_threshold)

    @staticmethod
    def calculate_comprehensive_score(
        metrics: Dict[str, Any],
        weights: Dict[str, float],
        range_span: float = 100.0
    ) -> Dict[str, Any]:
        """
        综合评分模型：加权平均法
        
        参数:
        - metrics: evaluate_loop_metrics返回的指标字典
        - weights: 权重字典 {"auto": W1, "stability": W2, "precision": W3, "efficiency": W4}
        - range_span: 量程范围，用于精确性评分
        
        权重建议:
        - 关键质量回路: {"auto": 0.2, "stability": 0.4, "precision": 0.3, "efficiency": 0.1}
        - 关键安全回路: {"auto": 0.4, "stability": 0.4, "precision": 0.1, "efficiency": 0.1}
        - 普通辅助回路: {"auto": 0.3, "stability": 0.3, "precision": 0.2, "efficiency": 0.2}
        """
        try:
            # 提取各维度指标
            auto_control_rate = metrics.get("auto_control", {}).get("auto_control_rate", 0.0)
            stability_rate = metrics.get("stability", {}).get("stability_rate", 0.0)
            sigma_sp = metrics.get("precision", {}).get("sigma_sp")
            cac = metrics.get("valve_activity", {}).get("cac")
            
            # 计算各维度得分
            score_auto = PerformanceEvaluator.score_metric_auto_control(auto_control_rate)
            score_stability = PerformanceEvaluator.score_metric_stability(stability_rate)
            score_precision = PerformanceEvaluator.score_metric_precision(sigma_sp, range_span)
            score_efficiency = PerformanceEvaluator.score_metric_efficiency(cac)
            
            # 加权平均
            w_auto = weights.get("auto", 0.25)
            w_stability = weights.get("stability", 0.25)
            w_precision = weights.get("precision", 0.25)
            w_efficiency = weights.get("efficiency", 0.25)
            
            # 确保权重和为1
            total_weight = w_auto + w_stability + w_precision + w_efficiency
            if total_weight > 0:
                w_auto /= total_weight
                w_stability /= total_weight
                w_precision /= total_weight
                w_efficiency /= total_weight
            
            comprehensive_score = (
                w_auto * score_auto +
                w_stability * score_stability +
                w_precision * score_precision +
                w_efficiency * score_efficiency
            )
            
            return {
                "comprehensive_score": float(comprehensive_score),
                "scores": {
                    "auto_control": float(score_auto),
                    "stability": float(score_stability),
                    "precision": float(score_precision),
                    "efficiency": float(score_efficiency)
                },
                "weights": {
                    "auto": float(w_auto),
                    "stability": float(w_stability),
                    "precision": float(w_precision),
                    "efficiency": float(w_efficiency)
                }
            }
        except Exception as e:
            logger.error(f"综合评分计算失败: {str(e)}")
            return {"comprehensive_score": 0.0, "error": str(e)}

