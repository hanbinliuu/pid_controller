import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Union

try:
    from .config import Config, ModelType
    from .identifier import ModelIdentifier
except ImportError:
    from config import Config, ModelType
    from identifier import ModelIdentifier


@dataclass
class HistoricalData:
    """历史数据结构"""
    timestamp: np.ndarray  # 时间戳数组（毫秒或秒）
    pv: np.ndarray         # 过程值
    sv: np.ndarray         # 设定值
    mv: np.ndarray         # 操作值
    
    @classmethod
    def from_json(cls, data: List[Dict[str, Any]]) -> 'HistoricalData':
        """从JSON格式数据创建HistoricalData对象
        
        Args:
            data: JSON数组，每个元素包含 timestamp, sv, pv, mv 等字段
            
        Returns:
            HistoricalData对象
        """
        if not data or len(data) == 0:
            raise ValueError("输入数据为空")
        
        timestamps = []
        pvs = []
        svs = []
        mvs = []
        
        for item in data:
            timestamps.append(item.get('timestamp', 0))
            pvs.append(item.get('pv', 0.0))
            svs.append(item.get('sv', 0.0))
            mvs.append(item.get('mv', 0.0))
        
        return cls(
            timestamp=np.array(timestamps, dtype=np.float64),
            pv=np.array(pvs, dtype=np.float64),
            sv=np.array(svs, dtype=np.float64),
            mv=np.array(mvs, dtype=np.float64)
        )
    
    def to_time_array(self) -> np.ndarray:
        """将时间戳转换为相对时间数组（秒）"""
        if len(self.timestamp) == 0:
            return np.array([])
        
        # 检测时间戳单位（毫秒或秒）
        # 如果时间戳值本身大于1e10，则认为是毫秒级
        if self.timestamp[0] > 1e10:  # 毫秒级时间戳 (Unix时间戳毫秒大约是1.7e12)
            t = (self.timestamp - self.timestamp[0]) / 1000.0
        else:
            t = self.timestamp - self.timestamp[0]
        return t


@dataclass
class ModelDetectionResult:
    """模型检测结果"""
    model_type: str          # 模型类型
    model_rating: float      # 模型评分 (0-10)
    start_time: int          # 整定段起始时间戳（毫秒）
    end_time: int            # 整定段结束时间戳（毫秒）
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'model_type': self.model_type,
            'model_rating': round(self.model_rating, 2),
            'start_time': self.start_time,
            'end_time': self.end_time
        }


class ModelTypeDetector:
    """模型类型自动检测器
    
    通过拟合多种模型并比较拟合优度，自动选择最佳模型类型。
    
    输出格式:
    {
        "model_type": "FOPDT",
        "model_rating": 7.8,
        "start_time": 1764752400000,
        "end_time": 1764752900000
    }
    """
    
    # 候选模型类型列表
    CANDIDATE_MODELS = [
        ModelType.FOPDT,     # 一阶加纯滞后
        ModelType.FO,        # 纯一阶
        ModelType.SO,        # 纯二阶
        ModelType.SOPDT,     # 二阶加纯滞后
        ModelType.FOPI       # 一阶积分
    ]
    
    def __init__(self, verbose: bool = False):
        """初始化检测器
        
        Args:
            verbose: 是否输出详细日志
        """
        self.verbose = verbose
        self._epsilon = Config.EPSILON
    
    def detect(self, data: Union[List[Dict[str, Any]], HistoricalData]) -> Dict[str, Any]:
        """检测模型类型（主入口）
        
        Args:
            data: 历史数据，可以是JSON数组或HistoricalData对象
            
        Returns:
            {
                "model_type": "fopdt",
                "model_rating": 7.8,
                "start_time": 1764752400000,
                "end_time": 1764752900000
            }
        """
        # 转换数据格式
        if isinstance(data, list):
            hist_data = HistoricalData.from_json(data)
        else:
            hist_data = data
        
        # 提取数组
        t = hist_data.to_time_array()
        y = hist_data.pv
        u = hist_data.mv
        sv = hist_data.sv
        timestamps = hist_data.timestamp
        
        # 数据验证
        if len(y) < 20:
            if self.verbose:
                print(f"⚠️ 数据点过少({len(y)}), 默认使用FOPDT模型")
            return ModelDetectionResult(
                model_type=ModelType.FOPDT,
                model_rating=0.0,
                start_time=int(timestamps[0]) if len(timestamps) > 0 else 0,
                end_time=int(timestamps[-1]) if len(timestamps) > 0 else 0
            ).to_dict()
        
        # 1. 检测整定段（非稳态区间）
        start_idx, end_idx = self._detect_tuning_segment(t, y, sv, u)
        start_time = int(timestamps[start_idx])
        end_time = int(timestamps[end_idx])
        
        if self.verbose:
            print(f"🔍 整定段: 索引[{start_idx}, {end_idx}], 时间[{start_time}, {end_time}]")
        
        # 提取整定段数据
        t_seg = t[start_idx:end_idx+1] - t[start_idx]
        y_seg = y[start_idx:end_idx+1]
        u_seg = u[start_idx:end_idx+1]
        
        # 2. 对所有候选模型进行拟合，计算评分
        best_model_type, best_rating, all_scores = self._compare_all_models(t_seg, y_seg, u_seg)
        
        if self.verbose:
            print(f"🔍 模型评分:")
            for model, score in all_scores.items():
                marker = "✅" if model == best_model_type else "  "
                print(f"   {marker} {model}: {score:.2f}")
            print(f"🎯 最佳模型: {best_model_type}, 评分: {best_rating:.2f}")
        
        return ModelDetectionResult(
            model_type=best_model_type,
            model_rating=best_rating,
            start_time=start_time,
            end_time=end_time
        ).to_dict()
    
    def detect_by_r2(self, data: Union[List[Dict[str, Any]], HistoricalData]) -> Dict[str, Any]:
        """仅基于 R² 拟合度检测模型类型
        
        只使用 R² 决定系数来评分，选择拟合度最高的模型。
        
        Args:
            data: 历史数据，可以是JSON数组或HistoricalData对象
            
        Returns:
            {
                "model_type": "FOPDT",
                "model_rating": 8.5,
                "r2_scores": {"FOPDT": 0.85, "FO": 0.72, ...},
                "start_time": 1764752400000,
                "end_time": 1764752900000
            }
        """
        # 转换数据格式
        if isinstance(data, list):
            hist_data = HistoricalData.from_json(data)
        else:
            hist_data = data
        
        # 提取数组
        t = hist_data.to_time_array()
        y = hist_data.pv
        u = hist_data.mv
        sv = hist_data.sv
        timestamps = hist_data.timestamp
        
        # 数据验证
        if len(y) < 20:
            if self.verbose:
                print(f"⚠️ 数据点过少({len(y)}), 默认使用FOPDT模型")
            return {
                'model_type': ModelType.FOPDT,
                'model_rating': 0.0,
                'r2_scores': {},
                'start_time': int(timestamps[0]) if len(timestamps) > 0 else 0,
                'end_time': int(timestamps[-1]) if len(timestamps) > 0 else 0
            }
        
        # 检测整定段
        start_idx, end_idx = self._detect_tuning_segment(t, y, sv, u)
        start_time = int(timestamps[start_idx])
        end_time = int(timestamps[end_idx])
        
        if self.verbose:
            print(f"🔍 整定段: 索引[{start_idx}, {end_idx}], 时间[{start_time}, {end_time}]")
        
        # 提取整定段数据
        t_seg = t[start_idx:end_idx+1] - t[start_idx]
        y_seg = y[start_idx:end_idx+1]
        u_seg = u[start_idx:end_idx+1]
        y0 = y_seg[0]
        
        # 对所有候选模型进行拟合，仅计算 R²
        r2_scores = {}
        for model_type in self.CANDIDATE_MODELS:
            try:
                # 辨识模型参数
                params = self._identify_model(t_seg, y_seg, u_seg, model_type)
                
                # 仿真预测
                y_pred = self._simulate_model(params, t_seg, u_seg, y0, model_type)
                
                # 计算 R²
                r2 = self._calculate_r2(y_seg, y_pred)
                r2_scores[model_type] = r2
                
                if self.verbose:
                    print(f"   {model_type}: R²={r2:.4f}")
                
            except Exception as e:
                if self.verbose:
                    print(f"⚠️ {model_type} 拟合失败: {e}")
                r2_scores[model_type] = 0.0
        
        # 选择 R² 最高的模型
        if not r2_scores:
            return {
                'model_type': ModelType.FOPDT,
                'model_rating': 5.0,
                'r2_scores': {},
                'start_time': start_time,
                'end_time': end_time
            }
        
        best_model = max(r2_scores, key=r2_scores.get)
        best_r2 = r2_scores[best_model]
        best_rating = best_r2 * 10.0  # R² 转为 0-10 评分
        
        if self.verbose:
            print(f"🔍 R² 评分:")
            for model, r2 in r2_scores.items():
                marker = "✅" if model == best_model else "  "
                print(f"   {marker} {model}: R²={r2:.4f}")
            print(f"🎯 最佳模型(纯R²): {best_model}, R²={best_r2:.4f}, 评分={best_rating:.2f}")
        
        return {
            'model_type': best_model,
            'model_rating': round(best_rating, 2),
            'r2_scores': {k: round(v, 4) for k, v in r2_scores.items()},
            'start_time': start_time,
            'end_time': end_time
        }
    
    def _detect_tuning_segment(self, t: np.ndarray, y: np.ndarray, 
                               sv: np.ndarray, u: np.ndarray) -> Tuple[int, int]:
        """检测整定段（非稳态区间）
        
        Args:
            t: 时间数组
            y: PV数组
            sv: SV数组
            u: MV数组
            
        Returns:
            (start_idx, end_idx) 整定段的起止索引
        """
        n = len(y)
        if n < 30:
            return 0, n - 1
        
        # 计算误差
        error = np.abs(y - sv)
        
        # 使用滑动窗口检测非稳态段
        window_size = max(10, n // 20)
        
        # 计算每个窗口的标准差
        stds = []
        for i in range(n - window_size + 1):
            window = y[i:i+window_size]
            stds.append(np.std(window))
        stds = np.array(stds)
        
        # 计算误差的移动平均
        error_ma = np.convolve(error, np.ones(window_size)/window_size, mode='valid')
        
        # 非稳态判断: 标准差大 或 误差大
        std_threshold = np.percentile(stds, 50)  # 中位数作为阈值
        error_threshold = np.percentile(error_ma, 50)
        
        non_steady_mask = (stds > std_threshold) | (error_ma > error_threshold)
        
        # 找到非稳态区间
        if not np.any(non_steady_mask):
            # 没有明显非稳态，使用全部数据
            return 0, n - 1
        
        # 找到第一个和最后一个非稳态点
        non_steady_indices = np.where(non_steady_mask)[0]
        start_idx = max(0, non_steady_indices[0] - window_size // 2)
        end_idx = min(n - 1, non_steady_indices[-1] + window_size)
        
        # 确保区间足够长
        if end_idx - start_idx < 30:
            # 扩展区间
            center = (start_idx + end_idx) // 2
            start_idx = max(0, center - 50)
            end_idx = min(n - 1, center + 50)
        
        return start_idx, end_idx
    
    def _compare_all_models(self, t: np.ndarray, y: np.ndarray, 
                           u: np.ndarray) -> Tuple[str, float, Dict[str, float]]:
        """拟合所有候选模型，返回最佳模型和评分
        
        仅使用 R² 拟合优度来选择模型
        
        Args:
            t: 时间数组（相对时间）
            y: PV数组（原始历史数据）
            u: MV数组
            
        Returns:
            (best_model_type, best_rating, all_scores)
        """
        y0 = y[0]
        scores = {}
        
        for model_type in self.CANDIDATE_MODELS:
            try:
                # 辨识模型参数
                params = self._identify_model(t, y, u, model_type)
                
                # 仿真预测
                y_pred = self._simulate_model(params, t, u, y0, model_type)
                
                # 计算 R²
                r2 = self._calculate_r2(y, y_pred)
                rating = r2 * 10.0  # 转为 0-10 评分
                
                scores[model_type] = max(0.0, rating)
                
                if self.verbose:
                    print(f"   {model_type}: R²={r2:.4f}, 评分={rating:.2f}")
                
            except Exception as e:
                if self.verbose:
                    print(f"⚠️ {model_type} 拟合失败: {e}")
                scores[model_type] = 0.0
        
        # 找出最佳模型
        if not scores:
            return ModelType.FOPDT, 5.0, {ModelType.FOPDT: 5.0}
        
        best_model = max(scores, key=scores.get)
        best_rating = scores[best_model]
        
        return best_model, best_rating, scores
    
    def _identify_model(self, t: np.ndarray, y: np.ndarray, 
                       u: np.ndarray, model_type: str) -> tuple:
        """辨识指定类型的模型参数"""
        if model_type == ModelType.FOPDT:
            return ModelIdentifier.identify_fopdt(t, y, u)
        elif model_type == ModelType.FO:
            return ModelIdentifier.identify_first_order(t, y, u)
        elif model_type == ModelType.SO:
            return ModelIdentifier.identify_second_order(t, y, u)
        elif model_type == ModelType.SOPDT:
            return ModelIdentifier.identify_sopdt(t, y, u)
        elif model_type == ModelType.FOPI:
            return ModelIdentifier.identify_integral_delay(t, y, u)
        else:
            return ModelIdentifier.identify_fopdt(t, y, u)
    
    def _simulate_model(self, params: tuple, t: np.ndarray, u: np.ndarray, 
                       y0: float, model_type: str) -> np.ndarray:
        """仿真指定类型的模型"""
        if model_type == ModelType.FOPDT:
            return ModelIdentifier.fopdt_model(params, t, u, y0)
        elif model_type == ModelType.FO:
            return ModelIdentifier.first_order_model(params, t, u, y0)
        elif model_type == ModelType.SO:
            return ModelIdentifier.second_order_model(params, t, u, y0)
        elif model_type == ModelType.SOPDT:
            return ModelIdentifier.sopdt_model(params, t, u, y0)
        elif model_type == ModelType.FOPI:
            return ModelIdentifier.integral_delay_model(params, t, u, y0)
        else:
            return ModelIdentifier.fopdt_model(params, t, u, y0)
    
    def _calculate_r2(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算R²（决定系数）"""
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        
        if ss_tot < self._epsilon:
            return 0.0
        
        r2 = 1 - (ss_res / ss_tot)
        return max(0.0, min(1.0, r2))  # 限制在 [0, 1]
    
    def detect_with_details(self, data: Union[List[Dict[str, Any]], HistoricalData]) -> Dict[str, Any]:
        """检测模型类型并返回详细信息（扩展版本）
        
        Args:
            data: 历史数据
            
        Returns:
            包含模型类型、评分、时间区间和其他细节的字典
        """
        # 转换数据格式
        if isinstance(data, list):
            hist_data = HistoricalData.from_json(data)
        else:
            hist_data = data
        
        t = hist_data.to_time_array()
        y = hist_data.pv
        u = hist_data.mv
        sv = hist_data.sv
        timestamps = hist_data.timestamp
        
        # 数据验证
        if len(y) < 20:
            return {
                'model_type': ModelType.FOPDT,
                'model_rating': 0.0,
                'start_time': int(timestamps[0]) if len(timestamps) > 0 else 0,
                'end_time': int(timestamps[-1]) if len(timestamps) > 0 else 0,
                'all_scores': {},
                'scenario': 'unknown',
                'reason': '数据点过少，使用默认FOPDT模型'
            }
        
        # 检测整定段
        start_idx, end_idx = self._detect_tuning_segment(t, y, sv, u)
        start_time = int(timestamps[start_idx])
        end_time = int(timestamps[end_idx])
        
        # 提取整定段数据
        t_seg = t[start_idx:end_idx+1] - t[start_idx]
        y_seg = y[start_idx:end_idx+1]
        u_seg = u[start_idx:end_idx+1]
        
        # 检测场景
        scenario = self._detect_control_scenario(t_seg, y_seg, u_seg)
        
        # 对比所有模型
        best_model_type, best_rating, all_scores = self._compare_all_models(t_seg, y_seg, u_seg)
        
        return {
            'model_type': best_model_type,
            'model_rating': round(best_rating, 2),
            'start_time': start_time,
            'end_time': end_time,
            'all_scores': {k: round(v, 2) for k, v in all_scores.items()},
            'scenario': scenario,
            'tuning_segment_indices': (start_idx, end_idx)
        }
    
    def _compute_integral_correlation(self, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> float:
        """计算输出与输入积分的相关性（用于检测积分特性）
        
        Args:
            t: 时间数组
            y: 输出数组
            u: 输入数组
            
        Returns:
            相关系数
        """
        if len(u) != len(y) or len(t) < 2:
            return 0.0
        
        try:
            dt = t[1] - t[0]
            u_integral = np.cumsum(u) * dt
            correlation = np.corrcoef(y, u_integral)[0, 1]
            if np.isnan(correlation):
                return 0.0
            return correlation
        except Exception:
            return 0.0
    
    def _detect_control_scenario(self, t: np.ndarray, y: np.ndarray, u: np.ndarray) -> str:
        """检测控制场景类型
        
        Args:
            t: 时间数组
            y: 输出数据
            u: 输入数据
            
        Returns:
            场景类型：'temperature' 或 'level'
        """
        if len(y) < 20:
            return 'temperature'
        
        # 响应速度分析
        dy_dt = np.gradient(y, t)
        avg_response_speed = np.mean(np.abs(dy_dt))
        max_response_speed = np.max(np.abs(dy_dt))
        
        # 信噪比分析
        noise_level = np.std(np.diff(y))
        signal_level = np.std(y)
        snr = signal_level / noise_level if noise_level > self._epsilon else 100
        
        # 估计时间常数
        y_range = np.max(y) - np.min(y)
        estimated_T = y_range / max_response_speed if max_response_speed > self._epsilon else 30.0
        
        # 积分特性检测
        correlation_with_integral = self._compute_integral_correlation(t, y, u)
        
        # 场景判断逻辑
        if estimated_T > 20 and snr > 10 and avg_response_speed < 0.5:
            return 'temperature'
        elif estimated_T < 10 and (snr < 8 or correlation_with_integral > 0.7):
            return 'level'
        elif estimated_T < 10:
            return 'level'
        else:
            return 'temperature'


def detect_model_type(data: List[Dict[str, Any]], verbose: bool = False) -> Dict[str, Any]:

    detector = ModelTypeDetector(verbose=verbose)
    return detector.detect(data)
