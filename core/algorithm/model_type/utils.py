"""公共工具方法模块 - 计算指标、数据处理、时间戳解析"""

import numpy as np
from typing import Optional, Any, Tuple, List
from datetime import datetime

from .config import Config


class MetricsCalculator:
    """评估指标计算器"""
    
    @staticmethod
    def calculate_r2(y_true: np.ndarray, y_pred: np.ndarray, 
                     epsilon: float = Config.EPSILON) -> float:
        """计算决定系数 R²"""
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        if ss_tot < epsilon:
            return 0.0
        r2 = 1 - ss_res / ss_tot
        return float(np.clip(r2, 0.0, 1.0))
    
    @staticmethod
    def calculate_rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算均方根误差 RMSE"""
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    
    @staticmethod
    def calculate_rss(y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算残差平方和 RSS"""
        return float(np.sum((y_true - y_pred) ** 2))
    
    @staticmethod
    def calculate_aic(rss: float, n: int, k: int) -> float:
        """计算 AIC (Akaike Information Criterion)"""
        if rss <= 0 or n <= k:
            return float('inf')
        return n * np.log(rss / n) + 2 * k
    
    @staticmethod
    def calculate_bic(rss: float, n: int, k: int) -> float:
        """计算 BIC (Bayesian Information Criterion)"""
        if rss <= 0 or n <= k:
            return float('inf')
        return n * np.log(rss / n) + k * np.log(n)
    
    @staticmethod
    def safe_cv(values: List[float], epsilon: float = Config.EPSILON) -> float:
        """安全计算变异系数 CV = std / |mean|"""
        arr = np.array(values)
        mean_abs = np.abs(np.mean(arr))
        if mean_abs < epsilon:
            return 0.0
        return float(np.std(arr) / mean_abs)


class TimestampParser:
    """时间戳解析器"""
    
    SUPPORTED_FORMATS = [
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
        '%Y-%m-%d %H:%M:%S.%f',
    ]
    
    @staticmethod
    def parse(ts: Any) -> Optional[float]:
        """
        解析时间戳为毫秒
        
        支持类型：
        - int/float: 直接返回
        - str: 尝试多种格式解析
        - datetime: 转换为时间戳
        """
        if ts is None:
            return None
        
        if isinstance(ts, (int, float)):
            return float(ts)
        
        if isinstance(ts, str):
            # 清理时区信息
            ts_clean = ts.replace('Z', '').split('+')[0]
            
            for fmt in TimestampParser.SUPPORTED_FORMATS:
                try:
                    dt = datetime.strptime(ts_clean, fmt)
                    return dt.timestamp() * 1000
                except ValueError:
                    continue
            return None
        
        if hasattr(ts, 'timestamp'):
            return ts.timestamp() * 1000
        
        return None


class DataValidator:
    """数据验证工具"""
    
    @staticmethod
    def check_data_validity(y: np.ndarray, u: np.ndarray, 
                            min_points: int = Config.MIN_DATA_POINTS,
                            min_pv_range: float = Config.MIN_PV_RANGE,
                            min_mv_range: float = Config.MIN_MV_RANGE) -> Tuple[bool, str]:
        """
        检查数据有效性
        
        Returns:
            (is_valid, reason)
        """
        if len(y) < min_points:
            return False, f"数据点不足({len(y)}<{min_points})"
        
        pv_range = np.ptp(y)
        if pv_range < min_pv_range and np.std(y) < 0.1:
            return False, f"PV无变化(range={pv_range:.2f})"
        
        mv_range = np.ptp(u)
        if mv_range < min_mv_range:
            return False, f"MV无变化(range={mv_range:.2f})"
        
        return True, ""
    
    @staticmethod
    def check_step_response_shape(y: np.ndarray, u: np.ndarray) -> Tuple[bool, str]:
        """
        检查是否具有阶跃响应的基本形状特征
        
        Returns:
            (is_valid, reason)
        """
        n = len(y)
        if n < 20:
            return False, "数据太短"
        
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


class SimulationHelper:
    """仿真辅助工具"""
    
    @staticmethod
    def detect_sv_change_points(sv: np.ndarray, 
                                 threshold_factor: float = 0.5) -> List[int]:
        """
        检测SV变化点
        
        Args:
            sv: 设定值数组
            threshold_factor: 阈值因子（相对于标准差）
        
        Returns:
            变化点索引列表
        """
        if sv is None or len(sv) < 2:
            return []
        
        sv_diff = np.abs(np.diff(sv))
        sv_std = np.std(sv)
        threshold = max(0.1, sv_std * threshold_factor) if sv_std > 0 else 0.1
        
        change_points = np.where(sv_diff > threshold)[0] + 1
        return change_points.tolist()
    
    @staticmethod
    def get_segment_reset_points(n: int, sv: np.ndarray = None,
                                  max_segment: int = Config.MAX_SEGMENT_LENGTH) -> List[int]:
        """
        获取分段重置点列表
        
        包含：
        1. 起始点 (0)
        2. SV变化点
        3. 长段分割点
        4. 终点 (n)
        """
        reset_points = [0]
        
        # 添加SV变化点
        if sv is not None:
            sv_changes = SimulationHelper.detect_sv_change_points(sv)
            reset_points.extend(sv_changes)
        
        # 添加长段分割点
        for start in range(0, n, max_segment):
            if start > 0 and start not in reset_points:
                reset_points.append(start)
        
        reset_points = sorted(set(reset_points))
        reset_points.append(n)
        
        return reset_points
