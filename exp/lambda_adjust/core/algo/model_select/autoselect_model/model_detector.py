"""
模型检测器

基于最小二乘法检测数据属于哪个模型类型（一阶、一阶加纯滞后、二阶）。
"""

import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum
from scipy.optimize import least_squares
import warnings
warnings.filterwarnings('ignore')

from .model_types import ModelType
from .model_selector import ModelSelector


@dataclass
class DetectionResult:
    """检测结果"""
    detected_model: ModelType  # 检测到的模型类型
    confidence: float  # 置信度（0-1）
    all_results: Dict[ModelType, Dict]  # 所有模型的拟合结果
    parameters: Dict[str, float]  # 检测到的模型参数
    r2: float  # 决定系数
    rmse: float  # 均方根误差


class ModelDetector:
    """模型检测器"""
    
    def __init__(self, config=None):
        """
        初始化检测器
        
        Args:
            config: 模型选择配置，如果为None则使用默认配置
        """
        self.selector = ModelSelector(config)
    
    @staticmethod
    def first_order_model(params: np.ndarray, t: np.ndarray, u: np.ndarray, y0: float) -> np.ndarray:
        """一阶模型"""
        K, T = params
        T = max(T, 1e-6)
        y = np.zeros_like(t)
        y[0] = y0
        
        for i in range(1, len(t)):
            dt = t[i] - t[i - 1]
            if dt <= 0:
                y[i] = y[i - 1]
                continue
            dy_dt = (K * u[i] - y[i - 1]) / T
            y[i] = y[i - 1] + dy_dt * dt
        
        return y
    
    @staticmethod
    def fopdt_model(params: np.ndarray, t: np.ndarray, u: np.ndarray, y0: float) -> np.ndarray:
        """一阶加纯滞后模型"""
        K, T, L = params
        T = max(T, 1e-6)
        L = max(L, 0.0)
        y = np.zeros_like(t)
        y[0] = y0
        
        if len(t) > 1:
            dt_avg = np.mean(np.diff(t))
            lag_samples = max(0, int(np.round(L / dt_avg))) if dt_avg > 0 else 0
        else:
            lag_samples = 0
        
        for i in range(1, len(t)):
            dt = t[i] - t[i - 1]
            if dt <= 0:
                y[i] = y[i - 1]
                continue
            
            lag_idx = max(0, i - lag_samples)
            u_delay = u[lag_idx]
            dy_dt = (K * u_delay - y[i - 1]) / T
            y[i] = y[i - 1] + dy_dt * dt
        
        return y
    
    @staticmethod
    def second_order_model(params: np.ndarray, t: np.ndarray, u: np.ndarray, y0: float) -> np.ndarray:
        """二阶模型"""
        K, T1, T2 = params
        T1 = max(T1, 1e-6)
        T2 = max(T2, 1e-6)
        y = np.zeros_like(t)
        x1 = y0
        y[0] = y0
        
        for i in range(1, len(t)):
            dt = t[i] - t[i - 1]
            if dt <= 0:
                y[i] = y[i - 1]
                continue
            
            u_eff = K * u[i]
            dx1_dt = (u_eff - x1) / T1
            x1 = x1 + dx1_dt * dt
            
            dy_dt = (x1 - y[i - 1]) / T2
            y[i] = y[i - 1] + dy_dt * dt
        
        return y
    
    def residuals(self, params: np.ndarray, t: np.ndarray, u: np.ndarray,
                  y_measured: np.ndarray, y0: float, model_type: ModelType) -> np.ndarray:
        """最小二乘优化的残差函数"""
        if model_type == ModelType.FIRST_ORDER:
            y_predicted = self.first_order_model(params, t, u, y0)
        elif model_type == ModelType.FOPDT:
            y_predicted = self.fopdt_model(params, t, u, y0)
        elif model_type == ModelType.SECOND_ORDER:
            y_predicted = self.second_order_model(params, t, u, y0)
        else:
            raise ValueError(f"未知的模型类型: {model_type}")
        
        return y_predicted - y_measured
    
    def fit_model(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                  model_type: ModelType) -> Dict:
        """
        拟合指定类型的模型
        
        Args:
            t: 时间数组
            y: 输出数组
            u: 输入数组
            model_type: 模型类型
            
        Returns:
            拟合结果字典
        """
        n = len(y)
        if n < 10:
            return {
                "success": False,
                "r2": 0.0,
                "rmse": np.inf,
                "parameters": {},
                "y_predicted": np.array([])
            }
        
        # 估计初始值
        init_window = max(10, int(0.1 * n))
        y0 = np.mean(y[:init_window])
        
        # 计算时间跨度
        if len(t) > 1:
            time_span = t[-1] - t[0]
        else:
            time_span = 1.0
        
        # 估计增益
        u_range = np.max(u) - np.min(u)
        y_range = np.max(y) - np.min(y)
        
        if u_range > 1e-6:
            u_centered = u - np.mean(u)
            y_centered = y - np.mean(y)
            if np.sum(u_centered ** 2) > 1e-6:
                gain_guess = np.sum(u_centered * y_centered) / np.sum(u_centered ** 2)
            else:
                gain_guess = y_range / u_range if u_range > 1e-6 else 0.5
        else:
            gain_guess = 0.5
        
        gain_guess = np.clip(gain_guess, 0.01, 10.0)
        time_constant_guess = max(time_span / 10.0, 1.0)
        
        # 根据模型类型设置初始猜测和边界
        if model_type == ModelType.FIRST_ORDER:
            initial_guess = [gain_guess, time_constant_guess]
            bounds = ([0.001, 0.1], [100.0, 10000.0])
            param_names = ['K', 'T']
        elif model_type == ModelType.FOPDT:
            if len(t) > 1:
                dt_avg = np.mean(np.diff(t))
                lag_guess = max(dt_avg * 5, 1.0)
            else:
                lag_guess = 5.0
            initial_guess = [gain_guess, time_constant_guess, lag_guess]
            bounds = ([0.001, 0.1, 0.0], [100.0, 10000.0, min(1000.0, time_span * 0.5)])
            param_names = ['K', 'T', 'L']
        elif model_type == ModelType.SECOND_ORDER:
            initial_guess = [gain_guess, time_constant_guess * 0.8, time_constant_guess * 0.6]
            bounds = ([0.001, 0.1, 0.1], [100.0, 5000.0, 5000.0])
            param_names = ['K', 'T1', 'T2']
        else:
            raise ValueError(f"未知的模型类型: {model_type}")
        
        # 最小二乘优化
        try:
            result = least_squares(
                self.residuals,
                initial_guess,
                args=(t, u, y, y0, model_type),
                bounds=bounds,
                verbose=0,
                max_nfev=1000
            )
            
            params_opt = result.x
            success = result.success
            
        except Exception as e:
            params_opt = initial_guess
            success = False
        
        # 计算预测值
        if model_type == ModelType.FIRST_ORDER:
            y_pred = self.first_order_model(params_opt, t, u, y0)
        elif model_type == ModelType.FOPDT:
            y_pred = self.fopdt_model(params_opt, t, u, y0)
        elif model_type == ModelType.SECOND_ORDER:
            y_pred = self.second_order_model(params_opt, t, u, y0)
        else:
            y_pred = np.zeros_like(y)
        
        # 计算拟合度指标
        sse = np.sum((y - y_pred) ** 2)
        ss_total = np.sum((y - np.mean(y)) ** 2)
        r2 = 1 - (sse / ss_total) if ss_total > 1e-10 else 0.0
        rmse = np.sqrt(np.mean((y - y_pred) ** 2))
        
        # 计算AIC和BIC（用于模型选择）
        n_params = len(params_opt)
        n = len(y)
        if sse > 1e-10 and n > n_params:
            # AIC = n * ln(SSE/n) + 2 * k
            # BIC = n * ln(SSE/n) + k * ln(n)
            # 其中 n 是样本数，k 是参数个数，SSE 是残差平方和
            aic = n * np.log(sse / n) + 2 * n_params
            bic = n * np.log(sse / n) + n_params * np.log(n)
        else:
            aic = np.inf
            bic = np.inf
        
        # 构建参数字典
        parameters = {name: float(val) for name, val in zip(param_names, params_opt)}
        
        return {
            "success": success,
            "r2": r2,
            "rmse": rmse,
            "sse": sse,
            "aic": aic,
            "bic": bic,
            "parameters": parameters,
            "y_predicted": y_pred
        }
    
    def detect(self, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> DetectionResult:
        """
        检测模型类型
        
        Args:
            t: 时间数组
            y: 输出数组
            u: 输入数组
            
        Returns:
            DetectionResult: 检测结果
        """
        # 拟合所有模型
        all_results = {}
        for model_type in [ModelType.FIRST_ORDER, ModelType.FOPDT, ModelType.SECOND_ORDER]:
            result = self.fit_model(t, y, u, model_type)
            all_results[model_type] = result
        
        # 后处理：检查是否有模型应该降级
        # 例如：二阶模型拟合得到 T1 ≈ T2，应该降级为一阶
        # 例如：FOPDT模型拟合得到 L ≈ 0，应该降级为一阶
        for model_type, result in all_results.items():
            if result["success"] and "parameters" in result:
                degraded_model = self.selector.should_degrade_model(model_type, result["parameters"])
                if degraded_model is not None:
                    # 如果应该降级，标记这个拟合结果，在选择时优先考虑降级后的模型
                    result["should_degrade_to"] = degraded_model
        
        # 选择最佳模型（基于R²和BIC的综合评分）
        valid_results = {k: v for k, v in all_results.items() 
                        if v["success"] and np.isfinite(v["r2"])}
        
        if not valid_results:
            # 如果没有成功的拟合，选择R²最高的
            best_model = max(all_results.items(), 
                           key=lambda x: x[1]["r2"] if np.isfinite(x[1]["r2"]) else -np.inf)[0]
            best_result = all_results[best_model]
        else:
            # 使用改进的模型选择策略
            # 1. 首先使用BIC选择候选模型
            # 2. 如果BIC差异很小（<10），优先选择更简单的模型（奥卡姆剃刀原则）
            # 3. 只有当更复杂模型的BIC明显更优时才选择它
            
            # 计算每个模型的BIC和参数数量
            model_info = {}
            for model_type, result in valid_results.items():
                bic = result.get("bic", np.inf)
                n_params = len(result["parameters"])
                if np.isfinite(bic):
                    model_info[model_type] = {
                        "bic": bic,
                        "n_params": n_params,
                        "r2": result["r2"],
                        "result": result
                    }
            
            if model_info:
                # 检查是否有模型应该降级
                # 如果复杂模型拟合得到简单模型的参数特征，优先选择简单模型
                for model_type, info in model_info.items():
                    result = info["result"]
                    if "should_degrade_to" in result:
                        degraded_to = result["should_degrade_to"]
                        # 如果降级目标模型也存在且拟合成功，优先选择降级后的模型
                        if degraded_to in model_info:
                            degraded_info = model_info[degraded_to]
                            # 如果降级后的模型R²也还可以（差异<0.01），优先选择简单模型
                            if abs(info["r2"] - degraded_info["r2"]) < 0.01:
                                # 标记应该优先选择降级后的模型
                                info["prefer_degraded"] = True
                
                # 按参数数量排序（从简单到复杂）
                sorted_models = sorted(model_info.items(), key=lambda x: x[1]["n_params"])
                
                # 从最简单的模型开始，检查是否有更复杂的模型明显更好
                best_model = sorted_models[0][0]
                best_bic = sorted_models[0][1]["bic"]
                best_r2 = sorted_models[0][1]["r2"]
                best_info = sorted_models[0][1].copy()
                best_info["model_type"] = best_model
                
                # 使用模型选择器进行选择
                for model_type, info in sorted_models[1:]:
                    # 如果这个模型应该降级，且降级后的模型是当前最佳，跳过
                    if info.get("prefer_degraded", False):
                        result = info["result"]
                        if "should_degrade_to" in result and result["should_degrade_to"] == best_model:
                            continue
                    
                    bic_diff = best_bic - info["bic"]  # 如果info["bic"]更小，diff为正
                    r2_diff = info["r2"] - best_r2  # 如果info["r2"]更大，diff为正
                    
                    # 准备候选模型信息
                    candidate_info = info.copy()
                    candidate_info["model_type"] = model_type
                    
                    # 使用选择器判断是否应该选择候选模型
                    if self.selector.should_select_model(candidate_info, best_info, bic_diff, r2_diff):
                        best_model = model_type
                        best_bic = info["bic"]
                        best_r2 = info["r2"]
                        best_info = candidate_info
                    # 如果差异不够大，保持更简单的模型（奥卡姆剃刀）
                
                best_result = best_info["result"]
            else:
                # 如果BIC都无效，使用R²选择（但给予复杂度惩罚）
                scores = {}
                for model_type, result in valid_results.items():
                    r2 = result["r2"]
                    n_params = len(result["parameters"])
                    # 只有当R²差异足够大时才选择更复杂的模型
                    # 如果R²差异小于0.01，优先选择更简单的模型
                    r2_bonus = r2
                    if n_params > 2:
                        # 对于更复杂的模型，需要R²至少高0.01才考虑
                        complexity_threshold = 0.01 * (n_params - 2)
                        # 如果R²不够高，给予惩罚
                        if r2 < 0.99:  # 如果R²不是非常高
                            r2_bonus = r2 - complexity_threshold
                    scores[model_type] = r2_bonus
                
                best_model = max(scores.items(), key=lambda x: x[1])[0]
                best_result = valid_results[best_model]
        
        # 计算置信度（基于R²和与其他模型的差异）
        r2_best = best_result["r2"]
        r2_others = [r["r2"] for m, r in all_results.items() if m != best_model and r["success"]]
        
        if r2_others:
            r2_diff = r2_best - max(r2_others)
            # 置信度：R²越高，与其他模型差异越大，置信度越高
            confidence = min(1.0, max(0.0, r2_best * 0.7 + r2_diff * 0.3))
        else:
            confidence = min(1.0, max(0.0, r2_best))
        
        return DetectionResult(
            detected_model=best_model,
            confidence=confidence,
            all_results={k.value: {
                "r2": v["r2"],
                "rmse": v["rmse"],
                "aic": v.get("aic", np.inf),
                "bic": v.get("bic", np.inf),
                "parameters": v["parameters"]
            } for k, v in all_results.items()},
            parameters=best_result["parameters"],
            r2=best_result["r2"],
            rmse=best_result["rmse"]
        )
    
    def detect_from_json(self, json_data: Union[str, Dict]) -> DetectionResult:
        """
        从JSON数据中检测模型类型
        
        Args:
            json_data: JSON数据（可以是文件路径字符串或字典）
            
        Returns:
            DetectionResult: 检测结果
        """
        # 加载JSON数据
        if isinstance(json_data, str):
            with open(json_data, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = json_data
        
        if data.get("status") != "success":
            raise ValueError(f"JSON数据状态不是success: {data.get('status')}")
        
        if "data" not in data:
            raise ValueError("JSON数据缺少data字段")
        
        data_list = data["data"]
        if not data_list:
            raise ValueError("JSON数据data字段为空")
        
        # 提取数据
        timestamps = []
        pv_data = []
        mv_data = []
        
        for item in data_list:
            timestamp = item.get("timestamp", 0)
            pv = item.get("pv", 0)
            mv = item.get("mv", 0)
            
            if not isinstance(timestamp, (int, float)) or not np.isfinite(timestamp):
                continue
            if not isinstance(pv, (int, float)) or not np.isfinite(pv):
                continue
            if not isinstance(mv, (int, float)) or not np.isfinite(mv):
                continue
            
            timestamps.append(float(timestamp) / 1000.0)  # 转换为秒
            pv_data.append(float(pv))
            mv_data.append(float(mv))
        
        if len(timestamps) < 10:
            raise ValueError(f"有效数据点太少（{len(timestamps)}个），至少需要10个数据点")
        
        # 转换为numpy数组
        time_data = np.array(timestamps, dtype=np.float64)
        pv_data = np.array(pv_data, dtype=np.float64)
        mv_data = np.array(mv_data, dtype=np.float64)
        
        # 转换为相对时间（从0开始）
        if len(time_data) > 0:
            time_data = time_data - time_data[0]
        
        # 检测模型类型
        return self.detect(time_data, pv_data, mv_data)

