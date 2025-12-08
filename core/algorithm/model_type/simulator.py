"""仿真模块"""

import numpy as np
from typing import Dict, Optional

from .config import Config, ModelType
from .identifier import ModelIdentifier
from .models import FusionResult


class ModelSimulator:
    """模型仿真器"""
    
    # 模型仿真方法映射
    SIMULATE_METHODS = {
        ModelType.FOPDT: ModelIdentifier.fopdt_model,
        ModelType.FO: ModelIdentifier.first_order_model,
        ModelType.SO: ModelIdentifier.second_order_model,
        ModelType.SOPDT: ModelIdentifier.sopdt_model,
        ModelType.FOPI: ModelIdentifier.integral_delay_model,
    }
    
    # 参数格式化映射
    PARAM_FORMATS = {
        ModelType.FOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': p[2]},
        ModelType.FO: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': 0.0},
        ModelType.SO: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': 0.0},
        ModelType.SOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': p[3]},
        ModelType.FOPI: lambda p: {'K': p[0], 'T1': 0.0, 'T2': 0.0, 'L': p[1]},
    }
    
    def __init__(self):
        self._epsilon = Config.EPSILON
    
    def simulate(self, params: tuple, model_type: str, 
                 t: np.ndarray, u: np.ndarray, y0: float) -> np.ndarray:
        """
        执行单次仿真
        
        Args:
            params: 模型参数元组
            model_type: 模型类型
            t: 时间序列
            u: MV输入序列
            y0: 初始PV值
        
        Returns:
            预测的PV序列
        """
        sim_method = self.SIMULATE_METHODS.get(model_type)
        if sim_method is None:
            raise ValueError(f"未知的模型类型: {model_type}")
        return sim_method(params, t, u, y0)
    
    def simulate_segmented(self, params: tuple, model_type: str,
                           y: np.ndarray, u: np.ndarray,
                           reset_on_sv_change: bool = True,
                           sv: np.ndarray = None) -> np.ndarray:
        """
        混合仿真策略：只在SV显著变化时重置，段内连续仿真
        
        Args:
            params: 模型参数
            model_type: 模型类型
            y: 实际PV数据
            u: MV数据
            reset_on_sv_change: 是否在SV变化点重置
            sv: SV数据（用于检测变化点）
        
        Returns:
            预测的PV序列
        """
        sim_method = self.SIMULATE_METHODS.get(model_type)
        n = len(y)
        
        if n == 0:
            return np.array([])
        
        # 检测SV显著变化点作为重置点
        reset_points = [0]
        
        if reset_on_sv_change and sv is not None and len(sv) == n:
            sv_diff = np.abs(np.diff(sv))
            sv_threshold = max(1.0, np.std(sv) * 2.0) if np.std(sv) > 0 else 1.0
            change_points = np.where(sv_diff > sv_threshold)[0] + 1
            reset_points.extend(change_points.tolist())
        
        reset_points = sorted(set(reset_points))
        reset_points.append(n)
        
        y_pred_all = np.zeros(n)
        
        for i in range(len(reset_points) - 1):
            start_idx = reset_points[i]
            end_idx = reset_points[i + 1]
            
            if end_idx <= start_idx:
                continue
            
            y0 = y[start_idx]
            t_seg = np.arange(end_idx - start_idx, dtype=float)
            u_seg = u[start_idx:end_idx]
            
            y_seg = sim_method(params, t_seg, u_seg, y0)
            y_pred_all[start_idx:end_idx] = y_seg
        
        return y_pred_all
    
    def fusion_to_params(self, fusion: FusionResult) -> tuple:
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
    
    def params_to_fusion(self, params: tuple, model_type: str, 
                         base_fusion: Optional[FusionResult] = None) -> FusionResult:
        """参数元组转为FusionResult"""
        fusion = FusionResult(model_type=model_type)
        if base_fusion:
            fusion.n_segments_used = base_fusion.n_segments_used
            fusion.consistency_score = base_fusion.consistency_score
        
        params_dict = self.PARAM_FORMATS[model_type](params)
        fusion.K = params_dict['K']
        fusion.T1 = params_dict['T1']
        fusion.T2 = params_dict['T2']
        fusion.L = params_dict['L']
        
        return fusion
    
    def create_init_params(self, model_type: str, K: float, T: float) -> tuple:
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
