import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple, Union, Callable

try:
    from .config import Config, ModelType
    from .identifier import ModelIdentifier
    from .preprocessor import DataPreprocessor
    from .pid_fusion_strategy import PIDFusionStrategy, WindowResult, FusionStrategy
except ImportError:
    from config import Config, ModelType
    from identifier import ModelIdentifier
    from preprocessor import DataPreprocessor
    from pid_fusion_strategy import PIDFusionStrategy, WindowResult, FusionStrategy


# ============================================================
# 数据结构
# ============================================================

@dataclass
class TuningWindow:
    """整定窗口"""
    start_time: Any  # datetime
    end_time: Any    # datetime


@dataclass 
class TuningParams:
    """整定参数"""
    window_size: int = 20
    step_size: int = 10
    variability_threshold: float = 0.2
    analyst_column: str = "pv"
    window_sec: int = 60
    is_filter: bool = True


@dataclass
class TuningInput:
    """整定输入数据结构"""
    start_time: Any                              # datetime - 开始时间
    end_time: Any                                # datetime - 结束时间
    params: Optional[TuningParams] = None        # 整定参数
    total_windows: int = 0                       # 窗口总数
    tuning_window: Optional[List[TuningWindow]] = None  # 整定窗口列表
    model_type: Optional[str] = None             # 模型类型
    controller_type: Optional[str] = None        # 控制器类型
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TuningInput':
        """从字典创建"""
        params = None
        if 'params' in data and data['params']:
            params = TuningParams(**data['params'])
        
        tuning_window = None
        if 'tuning_window' in data and data['tuning_window']:
            # 只提取 TuningWindow 需要的字段，忽略额外字段
            tuning_window = [
                TuningWindow(start_time=w.get('start_time'), end_time=w.get('end_time'))
                for w in data['tuning_window']
            ]
        
        return cls(
            start_time=data.get('start_time'),
            end_time=data.get('end_time'),
            params=params,
            total_windows=data.get('total_windows', 0),
            tuning_window=tuning_window,
            model_type=data.get('model_type'),
            controller_type=data.get('controller_type')
        )


@dataclass
class HistoricalData:
    """历史数据结构（时序数据）"""
    timestamp: np.ndarray
    pv: np.ndarray
    sv: np.ndarray
    mv: np.ndarray
    
    @classmethod
    def from_json(cls, data: List[Dict[str, Any]]) -> 'HistoricalData':
        """从JSON格式数据创建（向量化）"""
        if not data:
            raise ValueError("输入数据为空")
        
        n = len(data)
        timestamps = np.empty(n, dtype=np.float64)
        pvs = np.empty(n, dtype=np.float64)
        svs = np.empty(n, dtype=np.float64)
        mvs = np.empty(n, dtype=np.float64)
        
        for i, item in enumerate(data):
            timestamps[i] = item.get('timestamp', 0)
            pvs[i] = item.get('pv', 0.0)
            svs[i] = item.get('sv', 0.0)
            mvs[i] = item.get('mv', 0.0)
        
        return cls(timestamp=timestamps, pv=pvs, sv=svs, mv=mvs)
    
    def to_time_array(self) -> np.ndarray:
        """转换为相对时间数组（秒）"""
        if len(self.timestamp) == 0:
            return np.array([])
        
        t0 = self.timestamp[0]
        scale = 1000.0 if t0 > 1e10 else 1.0  # 毫秒 or 秒
        return (self.timestamp - t0) / scale
    
    def slice(self, start_idx: int, end_idx: int) -> 'HistoricalData':
        """切片获取子数据"""
        return HistoricalData(
            timestamp=self.timestamp[start_idx:end_idx],
            pv=self.pv[start_idx:end_idx],
            sv=self.sv[start_idx:end_idx],
            mv=self.mv[start_idx:end_idx]
        )
    
    def __len__(self) -> int:
        return len(self.pv)    


# ============================================================
# 模型操作基类
# ============================================================

class ModelBase:
    """模型操作基类 - 提供通用的辨识、仿真、评估方法"""
    
    CANDIDATE_MODELS = [
        ModelType.FOPDT, ModelType.FO, ModelType.SO, 
        ModelType.SOPDT, ModelType.FOPI
    ]
    
    # 模型辨识方法映射
    IDENTIFY_METHODS = {
        ModelType.FOPDT: ModelIdentifier.identify_fopdt,
        ModelType.FO: ModelIdentifier.identify_first_order,
        ModelType.SO: ModelIdentifier.identify_second_order,
        ModelType.SOPDT: ModelIdentifier.identify_sopdt,
        ModelType.FOPI: ModelIdentifier.identify_integral_delay,
    }
    
    # 模型仿真方法映射
    SIMULATE_METHODS = {
        ModelType.FOPDT: ModelIdentifier.fopdt_model,
        ModelType.FO: ModelIdentifier.first_order_model,
        ModelType.SO: ModelIdentifier.second_order_model,
        ModelType.SOPDT: ModelIdentifier.sopdt_model,
        ModelType.FOPI: ModelIdentifier.integral_delay_model,
    }
    
    # 参数格式化映射 (params -> {K, T1, T2, L})
    PARAM_FORMATS = {
        ModelType.FOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': p[2]},
        ModelType.FO: lambda p: {'K': p[0], 'T1': p[1], 'T2': 0.0, 'L': 0.0},
        ModelType.SO: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': 0.0},
        ModelType.SOPDT: lambda p: {'K': p[0], 'T1': p[1], 'T2': p[2], 'L': p[3]},
        ModelType.FOPI: lambda p: {'K': p[0], 'T1': 0.0, 'T2': 0.0, 'L': p[1]},
    }
    
    # 参数字典转元组映射
    PARAMS_TO_TUPLE = {
        ModelType.FOPDT: lambda p: (p['K'], p['T1'], p['L']),
        ModelType.FO: lambda p: (p['K'], p['T1']),
        ModelType.SO: lambda p: (p['K'], p['T1'], p['T2']),
        ModelType.SOPDT: lambda p: (p['K'], p['T1'], p['T2'], p['L']),
        ModelType.FOPI: lambda p: (p['K'], p['L']),
    }
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._epsilon = Config.EPSILON
        self._preprocessor = DataPreprocessor(epsilon=self._epsilon)
    
    def preprocess_data(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                        scenario: str = 'auto') -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """数据预处理（代理到 DataPreprocessor）"""
        return self._preprocessor.preprocess(t, y, u, scenario)
    
    def identify_model(self, t: np.ndarray, y: np.ndarray, 
                       u: np.ndarray, model_type: str) -> tuple:
        """辨识指定类型的模型参数"""
        method = self.IDENTIFY_METHODS.get(model_type, ModelIdentifier.identify_fopdt)
        return method(t, y, u)
    
    def simulate_model(self, params: tuple, t: np.ndarray, u: np.ndarray, 
                       y0: float, model_type: str) -> np.ndarray:
        """仿真指定类型的模型"""
        method = self.SIMULATE_METHODS.get(model_type, ModelIdentifier.fopdt_model)
        return method(params, t, u, y0)
    
    def normalize_params(self, params: tuple, model_type: str) -> Dict[str, float]:
        """统一参数格式"""
        formatter = self.PARAM_FORMATS.get(model_type)
        if formatter:
            return formatter(params)
        return {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0}
    
    def calculate_r2(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算 R²"""
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        if ss_tot < self._epsilon:
            return 0.0
        r2 = 1 - (ss_res / ss_tot)
        return np.clip(r2, 0.0, 1.0)
    
    def calculate_rmse(self, y_true: np.ndarray, y_pred: np.ndarray) -> float:
        """计算 RMSE"""
        return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
    
    def fit_all_models(self, t: np.ndarray, y: np.ndarray, u: np.ndarray,
                       enable_preprocess: bool = True
                       ) -> Dict[str, Dict[str, Any]]:
        """
        拟合所有候选模型，返回各模型的参数和评分
        
        Args:
            t: 时间数组
            y: 输出数据 (PV)
            u: 输入数据 (MV)
            enable_preprocess: 是否启用数据预处理（默认True）
        
        注意：模型仿真函数内部处理基准值，这里直接传入原始 u 值
        """
        # ============================================================
        # 智能数据选择：找到最长的连续有效段（无 PV=0 异常）
        # ============================================================
        if enable_preprocess and len(y) >= 20:
            best_segment = self._find_best_continuous_segment(y, u, min_len=50)
            if best_segment is not None:
                start, end = best_segment
                filtered_count = len(y) - (end - start)
                self.log(f"📊 选择连续有效段: [{start}, {end}] ({end-start} 点, 过滤 {filtered_count} 异常点)")
                t = np.arange(end - start, dtype=float)
                y = y[start:end]
                u = u[start:end]
        
        # 检查数据质量
        y_std = np.std(y)
        u_std = np.std(u)
        if y_std < self._epsilon:
            self.log(f"⚠️ PV 变化太小 (std={y_std:.4f})，可能是稳态数据")
        if u_std < self._epsilon:
            self.log(f"⚠️ MV 变化太小 (std={u_std:.4f})，可能是稳态数据")
        
        # ============================================================
        # 初始值设置：使用第一个点作为基准
        # ============================================================
        y0 = y[0]
        
        results = {}
        
        for model_type in self.CANDIDATE_MODELS:
            try:
                # 直接使用原始数据辨识（模型内部处理基准值）
                params = self.identify_model(t, y, u, model_type)
                
                # 仿真并计算 R²
                y_pred = self.simulate_model(params, t, u, y0, model_type)
                r2 = self.calculate_r2(y, y_pred)
                rmse = self.calculate_rmse(y, y_pred)
                
                results[model_type] = {
                    'params': params,
                    'params_dict': self.normalize_params(params, model_type),
                    'y_pred': y_pred,
                    'r2': r2,
                    'rmse': rmse,
                    'rating': r2 * 10.0
                }
                
                if self.verbose:
                    print(f"   {model_type}: R²={r2:.4f}")
                    
            except Exception as e:
                if self.verbose:
                    print(f"⚠️ {model_type} 拟合失败: {e}")
                results[model_type] = {'r2': 0.0, 'rating': 0.0}
        
        return results
    
    def _find_best_continuous_segment(self, y: np.ndarray, u: np.ndarray, 
                                       min_len: int = 50) -> Optional[Tuple[int, int]]:
        """
        找到最长的连续有效数据段（无 PV=0 或极端异常）
        
        Returns:
            (start_idx, end_idx) 或 None
        """
        n = len(y)
        if n < min_len:
            return None
        
        # 标记有效点（非零且非极端异常）
        valid = y != 0
        
        # 额外过滤极端跳变
        y_diff = np.abs(np.diff(y))
        if len(y_diff) > 0:
            jump_threshold = np.percentile(y_diff[y_diff > 0], 95) * 2
            jump_mask = np.concatenate([[False], y_diff > jump_threshold])
            valid &= ~jump_mask
        
        # 找最长连续有效段
        best_start, best_end = 0, 0
        current_start = 0
        
        for i in range(n + 1):
            if i == n or not valid[i]:
                if i - current_start > best_end - best_start:
                    best_start, best_end = current_start, i
                current_start = i + 1
        
        # 检查是否找到足够长的段
        if best_end - best_start >= min_len:
            return best_start, best_end
        
        # 如果没找到，返回 None（使用原始数据）
        return None
    
    def select_best_model(self, fit_results: Dict[str, Dict]) -> Tuple[str, Dict]:
        """选择最佳模型"""
        if not fit_results:
            return ModelType.FOPDT, {'r2': 0.0, 'rating': 5.0}
        
        best_model = max(fit_results.keys(), key=lambda m: fit_results[m].get('r2', 0))
        return best_model, fit_results[best_model]
    
    def log(self, msg: str):
        """日志输出"""
        if self.verbose:
            print(msg)
    
    def _estimate_u0_baseline(self, u: np.ndarray) -> float:
        """
        智能估计 MV 基准值 u0
        
        处理起始段（从阶跃开始）的边界情况：
        - 如果 MV 有明显阶跃，使用阶跃后的稳态值作为基准
        - 如果无阶跃，使用前 N 个点的均值
        
        Args:
            u: MV 数组
            
        Returns:
            u0: 基准值
        """
        n = len(u)
        if n < 10:
            return float(np.mean(u))
        
        # 检测是否有阶跃（前 10% 的数据变化是否显著）
        n_check = max(10, n // 10)
        u_start = u[:n_check]
        u_end = u[-n_check:]
        
        # 计算前后段的变化
        u_diff = np.abs(np.mean(u_end) - np.mean(u_start))
        u_range = np.max(u) - np.min(u)
        
        # 如果变化超过范围的 30%，说明有阶跃，需要找稳态基准
        if u_range > self._epsilon and u_diff / u_range > 0.3:
            # 找到最长的稳态段作为基准
            # 使用 MV 的众数区间作为基准
            u_median = np.median(u)
            u_std = np.std(u)
            
            # 找到接近中位数的点
            stable_mask = np.abs(u - u_median) < u_std * 0.5
            if np.sum(stable_mask) > 5:
                return float(np.mean(u[stable_mask]))
            
            # 如果没有明显稳态，使用数据的最后 10% 作为基准（假设趋向稳态）
            return float(np.mean(u_end))
        
        # 无阶跃：使用前 N 个点的均值
        n_init = min(10, n // 10)
        return float(np.mean(u[:max(1, n_init)]))


# ============================================================
# 模型类型检测器
# ============================================================

class ModelTypeDetector(ModelBase):
    """模型类型自动检测器"""
    
    def __init__(self, verbose: bool = False, enable_preprocess: bool = False):
        """
        Args:
            verbose: 是否输出详细日志
            enable_preprocess: 是否启用数据预处理（默认关闭，某些数据预处理会破坏阶跃响应）
        """
        super().__init__(verbose)
        self.enable_preprocess = enable_preprocess
    
    def detect(self, data: Union[List[Dict], HistoricalData], 
               return_r2_scores: bool = False) -> Dict[str, Any]:
        """
        检测模型类型（主入口）
        
        Args:
            data: 历史数据
            return_r2_scores: 是否返回各模型 R² 分数
            
        Returns:
            检测结果字典
        """
        # 数据转换
        hist_data = HistoricalData.from_json(data) if isinstance(data, list) else data
        
        if len(hist_data) < 20:
            return self._default_result(hist_data, return_r2_scores)
        
        # 检测整定段
        start_idx, end_idx = self._detect_tuning_segment(hist_data)
        
        self.log(f"🔍 整定段: 索引[{start_idx}, {end_idx}]")
        
        # 提取整定段数据
        seg = hist_data.slice(start_idx, end_idx + 1)
        t_seg = seg.to_time_array()
        
        # 拟合所有模型
        fit_results = self.fit_all_models(t_seg, seg.pv, seg.mv, enable_preprocess=self.enable_preprocess)
        
        # 选择最佳模型
        best_model, best_result = self.select_best_model(fit_results)
        
        # 日志输出
        if self.verbose:
            print("🔍 模型评分:")
            for model, res in fit_results.items():
                marker = "✅" if model == best_model else "  "
                print(f"   {marker} {model}: {res.get('rating', 0):.2f}")
            print(f"🎯 最佳模型: {best_model}, 评分: {best_result.get('rating', 0):.2f}")
        
        # 构建结果
        result = {
            'model_type': best_model,
            'model_rating': round(best_result.get('rating', 0), 2),
            'start_time': int(hist_data.timestamp[start_idx]),
            'end_time': int(hist_data.timestamp[end_idx])
        }
        
        if return_r2_scores:
            result['r2_scores'] = {m: round(r.get('r2', 0), 4) for m, r in fit_results.items()}
        
        return result
    
    def detect_by_r2(self, data: Union[List[Dict], HistoricalData]) -> Dict[str, Any]:
        """基于 R² 检测（兼容旧接口）"""
        return self.detect(data, return_r2_scores=True)
    
    def _detect_tuning_segment(self, hist_data: HistoricalData) -> Tuple[int, int]:
        """检测整定段 - 查找 MV 阶跃后的响应段"""
        n = len(hist_data)
        if n < 30:
            return 0, n - 1
        
        y, mv = hist_data.pv, hist_data.mv
        
        # 检测 MV 阶跃点（变化 > 5%）
        mv_diff = np.abs(np.diff(mv))
        step_threshold = max(5.0, np.percentile(mv_diff, 95))
        step_indices = np.where(mv_diff > step_threshold)[0]
        
        if len(step_indices) == 0:
            # 没有明显阶跃，使用中间 50% 数据
            return int(n * 0.25), int(n * 0.75)
        
        # 找到第一个明显阶跃后的响应段
        # 响应段长度：取数据长度的 10%，但不少于 100 点
        response_len = max(100, min(n // 10, 500))
        
        # 选择最大阶跃点
        max_step_idx = step_indices[np.argmax(mv_diff[step_indices])]
        
        # 响应段：从阶跃点开始，延续 response_len
        start_idx = max(0, max_step_idx - 10)  # 包含阶跃前一小段
        end_idx = min(n - 1, max_step_idx + response_len)
        
        # 确保区间足够长
        if end_idx - start_idx < 50:
            start_idx = max(0, max_step_idx - 25)
            end_idx = min(n - 1, max_step_idx + 75)
        
        return start_idx, end_idx
    
    def _default_result(self, hist_data: HistoricalData, 
                        return_r2_scores: bool) -> Dict[str, Any]:
        """默认结果（数据不足时）"""
        self.log(f"⚠️ 数据点过少({len(hist_data)}), 默认使用FOPDT模型")
        result = {
            'model_type': ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': int(hist_data.timestamp[0]) if len(hist_data) > 0 else 0,
            'end_time': int(hist_data.timestamp[-1]) if len(hist_data) > 0 else 0
        }
        if return_r2_scores:
            result['r2_scores'] = {}
        return result


# ============================================================
# 模型拟合器
# ============================================================

class ModelFitter(ModelBase):
    """
    模型拟合器 - 多扰动段整定
    
    ============================================================
    整定流程（针对多个 tuning_window 扰动段）：
    ============================================================
    
    Step 1: 逐模型、逐窗口计算 KTL 参数，取中位数
    --------------------------------------------------------
        for model_type in [FOPDT, FO, SO, SOPDT, FOPI]:
            for window in tuning_windows:
                计算该窗口的 K, T, L 参数
            取中位数 → 得到该模型的最终 KTL
    
    Step 2: 全量数据评分
    --------------------------------------------------------
        for model_type in all_models:
            用该模型的中位数 KTL 在 [start_time, end_time] 全部数据上仿真
            计算 R² 评分
        
    Step 3: 选择最佳模型
    --------------------------------------------------------
        以 R² 最高的模型作为最终模型
        输出该模型的 KTL 参数、PID 参数、拟合结果
    
    ============================================================
    输入格式：
    ============================================================
        tuning_input = {
            "start_time": datetime,       # 整段数据开始时间
            "end_time": datetime,         # 整段数据结束时间  
            "tuning_window": [            # 扰动段列表
                {"start_time": datetime, "end_time": datetime},
                ...
            ]
        }
    
    ============================================================
    输出格式：
    ============================================================
        {
            "model_type": "模型类型",
            "model_rating": 模型评分,
            "start_time": 开始时间,
            "end_time": 结束时间,
            "model_parameters": {"K": K, "T1": T1, "T2": T2, "L": L},
            "pid_parameters": {"Kp": Kp, "Ki": Ki, "Kd": Kd},
            "fitting_result": {
                "timestamp": 时间列,
                "sv": 设定值数组,
                "pv": 测量值数组,
                "mv": 控制值数组,
                "pv_model": 模拟拟合值,
                "r_squared": R² 值,
                "rmse": RMSE 值
            }
        }
    """
    
    def __init__(self, verbose: bool = False, enable_preprocess: bool = False):
        """
        Args:
            verbose: 是否输出详细日志
            enable_preprocess: 是否启用数据预处理（默认关闭）
        """
        super().__init__(verbose)
        self.enable_preprocess = enable_preprocess
    
    def fit(self, tuning_input: Union[Dict[str, Any], TuningInput], 
            raw_data: List[Dict[str, Any]],
            lambda_factor: float = 0.8) -> Dict[str, Any]:
        """
        多扰动段模型整定主入口
        
        Args:
            tuning_input: 整定输入
            raw_data: 原始时序数据
            lambda_factor: Lambda 整定系数（默认 0.8）
        
        Returns:
            整定结果字典（详见类文档）
        """
        # ============================================================
        # 输入解析与验证
        # ============================================================
        input_data = self._parse_tuning_input(tuning_input)
        if input_data is None or not input_data.tuning_window or not raw_data:
            return self._empty_result({'start_time': getattr(input_data, 'start_time', None) if input_data else None, 
                                        'end_time': getattr(input_data, 'end_time', None) if input_data else None})
        
        time_range = {'start_time': input_data.start_time, 'end_time': input_data.end_time}
        hist_data = HistoricalData.from_json(raw_data)
        
        # ============================================================
        # 提取各扰动段数据
        # ============================================================
        segments = self._extract_all_segments(hist_data, input_data.tuning_window)
        if not segments:
            return self._empty_result(time_range)
        
        self.log(f"📊 提取 {len(segments)} 个有效扰动段")
        
        # ============================================================
        # Step 1: 逐模型、逐窗口计算 KTL，融合参数
        # ============================================================
        model_fused_params = self._compute_median_params_per_model(
            segments, enable_preprocess=self.enable_preprocess
        )
        if not model_fused_params:
            return self._empty_result(time_range)
        
        # ============================================================
        # Step 2: 分段评估（每段单独计算 R²，加权平均）
        # ============================================================
        merged_segments = self._merge_segments(segments)
        best_result = self._evaluate_models_on_segments(merged_segments, model_fused_params, hist_data, segments)
        if best_result is None:
            return self._empty_result(time_range)
        
        # ============================================================
        # Step 3: 构建最终输出
        # ============================================================
        return self._build_final_result(best_result, time_range, lambda_factor)
    
    def _merge_segments(self, segments: List[HistoricalData]) -> HistoricalData:
        """合并多个扰动段数据"""
        if len(segments) == 1:
            return segments[0]
        
        # 合并数据（过滤 PV=0）
        all_pv, all_sv, all_mv, all_ts = [], [], [], []
        for seg in segments:
            valid_mask = seg.pv != 0
            all_pv.append(seg.pv[valid_mask])
            all_sv.append(seg.sv[valid_mask])
            all_mv.append(seg.mv[valid_mask])
            all_ts.append(seg.timestamp[valid_mask])
        
        return HistoricalData(
            timestamp=np.concatenate(all_ts),
            pv=np.concatenate(all_pv),
            sv=np.concatenate(all_sv),
            mv=np.concatenate(all_mv)
        )
    
    def _evaluate_models_on_segments(self, merged_data: HistoricalData,
                                      model_fused_params: Dict[str, Dict],
                                      full_hist_data: HistoricalData,
                                      segments: List[HistoricalData] = None
                                      ) -> Optional[Dict[str, Any]]:
        """
        分段评估模型，加权计算 R²
        
        关键改进：
        - 只在该模型融合时使用的有效窗口上评估 R²
        - 用数据量加权平均各段 R²
        - 避免低质量窗口拖累 R²
        """
        if segments is None:
            segments = [merged_data]
        
        self.log(f"📊 分段评估: 共 {len(segments)} 个扰动段")
        
        best_result = None
        best_weighted_r2 = -np.inf
        all_scores = {}
        
        for model_type, params in model_fused_params.items():
            try:
                raw_params = self._params_dict_to_tuple(params, model_type)
                
                # 获取该模型融合时使用的有效窗口索引
                valid_indices = params.get('valid_window_indices', list(range(1, len(segments) + 1)))
                
                # 只在有效窗口上评估
                segment_r2s = []
                segment_weights = []
                total_rmse = 0
                total_points = 0
                
                for seg_idx, seg in enumerate(segments):
                    # 跳过未被融合使用的窗口
                    if (seg_idx + 1) not in valid_indices:
                        continue
                    
                    # 使用与辨识时相同的数据预处理
                    t_proc, y_proc, u_proc = self._prepare_segment_data(seg, seg_idx, enable_preprocess=True)
                    if t_proc is None or len(y_proc) < 10:
                        continue
                    
                    y0 = y_proc[0]  # 使用滤波后数据的第一个点
                    
                    # 使用滤波后的数据评估R²
                    y_pred = self.simulate_model(raw_params, t_proc, u_proc, y0, model_type)
                    r2 = self.calculate_r2(y_proc, y_pred)
                    rmse = self.calculate_rmse(y_proc, y_pred)
                    
                    segment_r2s.append(max(r2, 0))  # 负 R² 当作 0
                    segment_weights.append(len(y_proc))
                    total_rmse += rmse * len(y_proc)
                    total_points += len(y_proc)
                
                if not segment_r2s:
                    continue
                
                # 加权平均 R²
                weighted_r2 = sum(r * w for r, w in zip(segment_r2s, segment_weights)) / sum(segment_weights)
                avg_rmse = total_rmse / total_points if total_points > 0 else 0
                
                all_scores[model_type] = weighted_r2
                
                self.log(f"🎯 {model_type}: K={params['K']:.4f}, T1={params['T1']:.2f}, "
                         f"R²={weighted_r2:.4f} (窗口{valid_indices})")
                
                if weighted_r2 > best_weighted_r2:
                    best_weighted_r2 = weighted_r2
                    
                    # 在全量数据上生成 pv_model（用于可视化）
                    full_y_pred = self._simulate_on_full_data(full_hist_data, raw_params, model_type)
                    
                    best_result = {
                        'model_type': model_type,
                        'params': params,
                        'r2': weighted_r2,
                        'rmse': avg_rmse,
                        'y_pred': full_y_pred,
                        'hist_data': self._filter_full_data(full_hist_data)
                    }
                    
            except Exception as e:
                self.log(f"⚠️ {model_type} 评估失败: {e}")
                all_scores[model_type] = 0.0
        
        if best_result:
            best_result['all_scores'] = all_scores
            p = best_result['params']
            
            # 评估拟合可信度
            r2 = best_weighted_r2
            if r2 >= 0.9:
                quality = "优秀"
            elif r2 >= 0.8:
                quality = "良好"
            elif r2 >= 0.7:
                quality = "可接受"
            elif r2 >= 0.5:
                quality = "较差"
            else:
                quality = "不可用"
            
            self.log(f"\n✅ 最佳模型: {best_result['model_type']}, R²={r2:.4f} ({quality})")
            self.log(f"   KTL: K={p['K']:.4f}, T1={p['T1']:.4f}, T2={p['T2']:.4f}, L={p['L']:.4f}")
            
            if r2 < 0.5:
                self.log(f"   ⚠️ 警告: R²<0.5，模型可能不适合该数据")
                self.log(f"      可能原因: 数据噪声大 / 扰动响应不明显 / 过程非线性")
        
        return best_result
    
    def _simulate_on_full_data(self, hist_data: HistoricalData, 
                                params: tuple, model_type: str) -> np.ndarray:
        """
        在全量数据上分段仿真（用于生成可视化的 pv_model）
        
        改进：每隔一段时间重置 y0 为实际 PV 值，避免长时间漂移
        """
        y_raw, u_raw = hist_data.pv, hist_data.mv
        valid_mask = y_raw != 0
        y = y_raw[valid_mask]
        u = u_raw[valid_mask]
        
        if len(y) < 10:
            return y.copy()
        
        # 分段仿真：每 100 点重置一次 y0
        SEGMENT_SIZE = 100
        
        y_pred_all = np.zeros_like(y)
        
        for start_idx in range(0, len(y), SEGMENT_SIZE):
            end_idx = min(start_idx + SEGMENT_SIZE, len(y))
            
            # 使用实际 PV 作为该段的初始值
            y0 = y[start_idx]
            
            # 该段的时间和输入（直接使用原始 u）
            t_seg = np.arange(end_idx - start_idx, dtype=float)
            u_seg = u[start_idx:end_idx]
            
            # 仿真该段
            y_seg = self.simulate_model(params, t_seg, u_seg, y0, model_type)
            y_pred_all[start_idx:end_idx] = y_seg
        
        return y_pred_all
    
    def _filter_full_data(self, hist_data: HistoricalData) -> HistoricalData:
        """过滤全量数据（移除 PV=0）"""
        valid_mask = hist_data.pv != 0
        return HistoricalData(
            timestamp=hist_data.timestamp[valid_mask],
            pv=hist_data.pv[valid_mask],
            sv=hist_data.sv[valid_mask],
            mv=hist_data.mv[valid_mask]
        )
    
    def _parse_tuning_input(self, tuning_input: Union[Dict[str, Any], TuningInput, None]
                            ) -> Optional[TuningInput]:
        """解析整定输入"""
        if isinstance(tuning_input, TuningInput):
            return tuning_input
        if isinstance(tuning_input, dict):
            return TuningInput.from_dict(tuning_input)
        return None
    
    def _extract_all_segments(self, hist_data: HistoricalData, 
                               tuning_windows: List[TuningWindow]
                               ) -> List[HistoricalData]:
        """提取所有扰动段数据"""
        segments = []
        for w in tuning_windows:
            window_dict = {'start_time': w.start_time, 'end_time': w.end_time}
            seg = self._extract_segment(hist_data, window_dict)
            if seg is not None and len(seg) >= 20:
                segments.append(seg)
        return segments
    
    def _extract_segment(self, hist_data: HistoricalData, 
                         window: Dict) -> Optional[HistoricalData]:
        """提取时间窗口数据"""
        start_time = window.get('start_time')
        end_time = window.get('end_time')
        
        if start_time is None or end_time is None:
            return None
        
        try:
            # 转换时间为毫秒时间戳
            start_ts = self._to_timestamp_ms(start_time)
            end_ts = self._to_timestamp_ms(end_time)
            
            mask = (hist_data.timestamp >= start_ts) & (hist_data.timestamp <= end_ts)
            indices = np.where(mask)[0]
            
            self.log(f"📍 窗口提取: [{start_ts} ~ {end_ts}] -> {len(indices)} 点")
            
            if len(indices) < 20:
                return None
            
            return HistoricalData(
                timestamp=hist_data.timestamp[indices],
                pv=hist_data.pv[indices],
                sv=hist_data.sv[indices],
                mv=hist_data.mv[indices]
            )
        except Exception as e:
            self.log(f"⚠️ 提取数据段失败: {e}")
            return None
    
    def _to_timestamp_ms(self, time_val) -> float:
        """
        将各种时间格式转换为毫秒时间戳
        
        支持格式：
        - pandas.Timestamp: 处理时区转换问题
        - datetime: 直接转换
        - int/float: 假设已是毫秒时间戳
        
        注意：
            pandas Timestamp 如果经过 tz_convert().tz_localize(None) 处理，
            其 .value 会包含时区偏移，需要特殊处理。
        """
        import calendar
        
        # pandas Timestamp - 需要处理时区问题
        # 使用 timetuple() 获取本地时间组件，再转换为 UTC 时间戳
        if hasattr(time_val, 'timetuple') and hasattr(time_val, 'value'):
            # 将 naive datetime 当作本地时间处理，转换为 UTC 时间戳
            # 使用 calendar.timegm 将时间元组转换为 UTC 秒数（不做本地时区转换）
            tt = time_val.timetuple()
            return calendar.timegm(tt) * 1000
        
        # 标准 datetime 对象
        if hasattr(time_val, 'timestamp'):
            return time_val.timestamp() * 1000
        
        # 数值类型（假设是毫秒）
        return float(time_val)
    
    def _compute_median_params_per_model(self, segments: List[HistoricalData],
                                          enable_preprocess: bool = True
                                          ) -> Dict[str, Dict[str, float]]:
        """
        Step 1: 逐模型、逐窗口计算 KTL 参数，选择最佳窗口的参数
        
        流程（改进版）：
            for model_type in all_models:
                for window in tuning_windows:
                    计算 KTL 参数 + 窗口内 R²
                选择 R² 最高的窗口参数（而非简单取中位数）
        
        Returns:
            {model_type: {K, T1, T2, L, window_count, best_r2}}
        """
        # 存储：每个模型的每个窗口的参数和 R²
        model_window_results = {mt: [] for mt in self.CANDIDATE_MODELS}
        
        # ============================================================
        # 逐窗口遍历
        # ============================================================
        for seg_idx, seg_data in enumerate(segments):
            t, y, u = self._prepare_segment_data(seg_data, seg_idx, enable_preprocess)
            if t is None:
                continue
            
            # 使用第一个点作为初始值（模型内部处理基准值）
            y0 = y[0]
            
            # 逐模型计算 KTL 和 R²
            for model_type in self.CANDIDATE_MODELS:
                try:
                    # 直接使用原始数据（模型内部处理基准值）
                    params = self.identify_model(t, y, u, model_type)
                    params_dict = self.normalize_params(params, model_type)
                    
                    # 计算窗口内 R²
                    y_pred = self.simulate_model(params, t, u, y0, model_type)
                    r2 = self.calculate_r2(y, y_pred)
                    
                    model_window_results[model_type].append({
                        'params': params_dict,
                        'r2': r2,
                        'window_idx': seg_idx + 1,
                        'data_points': len(y)  # 记录数据点数
                    })
                    
                    self.log(f"   {model_type} 窗口{seg_idx+1}: R²={r2:.4f}, K={params_dict['K']:.4f}")
                    
                except Exception as e:
                    self.log(f"⚠️ {model_type} 窗口 {seg_idx+1} 计算失败: {e}")
        
        # ============================================================
        # 选择每个模型 R² 最高的窗口参数
        # ============================================================
        return self._select_best_window_params(model_window_results)
    
    def _prepare_segment_data(self, seg_data: HistoricalData, seg_idx: int, 
                               enable_preprocess: bool
                               ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        准备单个窗口的数据（过滤 + 预处理 + 滤波）
        
        包含：
        1. 过滤 PV=0 的异常数据
        2. 数据质量检查（噪声/ON-OFF检测）
        3. 可选的滤波预处理
        """
        y_raw, u_raw = seg_data.pv.copy(), seg_data.mv.copy()
        
        # ============================================================
        # Step 1: 过滤 PV=0 的异常数据
        # ============================================================
        valid_mask = y_raw != 0
        valid_count = np.sum(valid_mask)
        
        if valid_count < 20:
            self.log(f"⚠️ 窗口 {seg_idx+1}: 有效数据不足 ({valid_count} 点)")
            return None, None, None
        
        y = y_raw[valid_mask]
        u = u_raw[valid_mask]
        
        filtered = len(y_raw) - len(y)
        if filtered > 0:
            self.log(f"📊 窗口 {seg_idx+1}: 过滤 {filtered} 个 PV=0 异常点，剩余 {len(y)} 点")
        
        # ============================================================
        # Step 2: 数据质量检查
        # ============================================================
        data_quality = self._check_data_quality(y, u, seg_idx)
        
        # ============================================================
        # Step 3: 根据数据质量决定是否滤波
        # ============================================================
        if data_quality.get('needs_smoothing', False):
            y, u = self._apply_smoothing(y, u, data_quality)
        
        t = np.arange(len(y), dtype=float)
        
        # ============================================================
        # Step 4: 可选的进一步预处理
        # ============================================================
        if enable_preprocess and len(y) >= 20:
            try:
                _, y_proc, u_proc = self.preprocess_data(t, y, u, scenario='auto')
                if len(y_proc) >= 20 and not np.any(np.isnan(y_proc)) and not np.any(np.isinf(y_proc)):
                    return np.arange(len(y_proc), dtype=float), y_proc, u_proc
            except Exception as e:
                self.log(f"⚠️ 窗口 {seg_idx+1}: 预处理失败 ({e})")
        
        return t, y, u
    
    def _check_data_quality(self, y: np.ndarray, u: np.ndarray, seg_idx: int) -> Dict[str, Any]:
        """
        检查数据质量，识别可能影响辨识的问题
        
        检查项：
        1. PV 噪声水平（相邻点跳变）
        2. MV 是否为 ON-OFF 控制
        3. 数据趋势性
        4. 高频振荡检测
        5. MV是否有明确阶跃变化（用于判断是否适合拟合）
        """
        result = {
            'needs_smoothing': False,
            'needs_heavy_smoothing': False,  # 新增：是否需要强力滤波
            'is_on_off': False,
            'pv_noise_level': 0.0,
            'mv_jump_ratio': 0.0,
            'high_freq_oscillation': False,
            'warnings': []
        }
        
        # 检查 PV 噪声 (降低阈值，更敏感)
        y_diff = np.abs(np.diff(y))
        y_range = np.max(y) - np.min(y)
        if y_range > self._epsilon:
            noise_ratio = np.median(y_diff) / y_range
            result['pv_noise_level'] = noise_ratio
            
            # 更敏感的噪声检测
            if noise_ratio > 0.05:  # 降低阈值从0.1到0.05
                result['needs_smoothing'] = True
                result['warnings'].append(f'PV噪声较大(ratio={noise_ratio:.2f})')
                self.log(f"   ⚠️ 窗口{seg_idx+1}: PV 噪声较大 (ratio={noise_ratio:.2f})，将应用滤波")
            
            # 极高噪声需要强力滤波
            if noise_ratio > 0.15:
                result['needs_heavy_smoothing'] = True
                result['warnings'].append(f'PV噪声极高(ratio={noise_ratio:.2f})，需要强力滤波')
                self.log(f"   🚨 窗口{seg_idx+1}: PV 噪声极高 (ratio={noise_ratio:.2f})，将应用强力滤波")
        
        # 检查高频振荡（连续方向改变）
        if len(y) > 10:
            sign_changes = np.sum(np.diff(np.sign(np.diff(y))) != 0)
            oscillation_ratio = sign_changes / len(y)
            result['oscillation_ratio'] = oscillation_ratio  # 保存用于后续判断
            
            if oscillation_ratio > 0.3:  # 超过30%的点发生方向改变
                result['high_freq_oscillation'] = True
                result['needs_heavy_smoothing'] = True
                result['warnings'].append(f'高频振荡严重(ratio={oscillation_ratio:.2f})')
                self.log(f"   🚨 窗口{seg_idx+1}: 高频振荡严重 (ratio={oscillation_ratio:.2f})，将应用强力滤波")
        
        # 检查 MV 是否为 ON-OFF（改进检测）
        u_at_0 = np.sum(u == 0) / len(u)
        u_at_100 = np.sum(u == 100) / len(u)
        
        # 额外检查：MV是否只在几个离散值上
        u_unique = np.unique(u)
        if len(u_unique) <= 3 and len(u) > 20:
            result['is_on_off'] = True
            result['needs_heavy_smoothing'] = True
            result['warnings'].append(f'MV离散值过少({len(u_unique)}个)，可能为ON-OFF控制')
            self.log(f"   ⚠️ 窗口{seg_idx+1}: MV离散值过少 ({len(u_unique)}个)，可能为ON-OFF控制")
        
        result['mv_jump_ratio'] = u_at_0 + u_at_100
        
        if result['mv_jump_ratio'] > 0.2:  # 降低阈值从0.3到0.2
            result['is_on_off'] = True
            result['needs_smoothing'] = True
            result['warnings'].append(f'MV可能ON-OFF控制(0/100占{result["mv_jump_ratio"]*100:.0f}%)')
            self.log(f"   ⚠️ 窗口{seg_idx+1}: MV 可能是 ON-OFF 控制 (0/100占{result['mv_jump_ratio']*100:.0f}%)，将应用滤波")
        
        return result
    
    def _apply_smoothing(self, y: np.ndarray, u: np.ndarray, 
                          data_quality: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """
        对噪声数据应用平滑滤波
        
        使用组合滤波策略：
        1. ON-OFF数据：提取趋势线（低通滤波 + 降采样）
        2. 高噪声数据：中值滤波 + 移动平均
        3. 一般数据：轻度平滑
        """
        from scipy.signal import medfilt, butter, filtfilt
        
        noise_level = data_quality.get('pv_noise_level', 0)
        is_on_off = data_quality.get('is_on_off', False)
        needs_heavy = data_quality.get('needs_heavy_smoothing', False)
        high_freq = data_quality.get('high_freq_oscillation', False)
        oscillation_ratio = data_quality.get('oscillation_ratio', 0)
        
        # ============================================================
        # 特殊处理：ON-OFF控制数据 - 提取趋势线
        # ============================================================
        if is_on_off and high_freq and oscillation_ratio > 0.5:
            self.log(f"   🔧 ON-OFF模式检测: 应用趋势提取滤波")
            return self._extract_trend_for_onoff(y, u, data_quality)
        
        # ============================================================
        # 普通高噪声数据处理
        # ============================================================
        # 确定滤波窗口大小
        if needs_heavy or high_freq:
            median_window = min(11, len(y) // 15)
            avg_window = min(31, len(y) // 10)
            self.log(f"   🔧 应用强力滤波: 中值窗口={median_window}, 平均窗口={avg_window}")
        elif is_on_off:
            median_window = min(7, len(y) // 20)
            avg_window = min(21, len(y) // 15)
        elif noise_level > 0.1:
            median_window = min(5, len(y) // 30)
            avg_window = min(15, len(y) // 20)
        else:
            median_window = min(3, len(y) // 50)
            avg_window = min(7, len(y) // 30)
        
        # 确保窗口大小为奇数且至少为3
        median_window = max(3, median_window)
        if median_window % 2 == 0:
            median_window += 1
        
        avg_window = max(3, avg_window)
        if avg_window % 2 == 0:
            avg_window += 1
        
        # Step 1: 中值滤波去除脉冲噪声
        try:
            y_median = medfilt(y, kernel_size=median_window)
            u_median = medfilt(u, kernel_size=median_window) if is_on_off else u
        except:
            y_median = y.copy()
            u_median = u.copy()
        
        # Step 2: 移动平均滤波平滑数据
        def moving_average(data, w):
            kernel = np.ones(w) / w
            smoothed = np.convolve(data, kernel, mode='same')
            half_w = w // 2
            smoothed[:half_w] = data[:half_w]
            smoothed[-half_w:] = data[-half_w:]
            return smoothed
        
        y_smooth = moving_average(y_median, avg_window)
        u_smooth = moving_average(u_median, avg_window) if is_on_off else u_median
        
        return y_smooth, u_smooth
    
    def _extract_trend_for_onoff(self, y: np.ndarray, u: np.ndarray, 
                                  data_quality: Dict[str, Any]) -> Tuple[np.ndarray, np.ndarray]:
        """
        ON-OFF控制数据的趋势提取
        
        方法：
        1. 使用超低频低通滤波器提取趋势
        2. 对MV计算移动平均（等效占空比）
        3. 降采样减少数据量
        """
        from scipy.signal import butter, filtfilt, savgol_filter
        
        n = len(y)
        
        # ============================================================
        # Step 1: PV趋势提取 - 使用超大窗口Savitzky-Golay滤波
        # ============================================================
        # 窗口大小：数据长度的5%，但至少51点
        sg_window = max(51, n // 20)
        if sg_window % 2 == 0:
            sg_window += 1
        sg_window = min(sg_window, n - 2)  # 不超过数据长度
        if sg_window % 2 == 0:
            sg_window -= 1
        
        try:
            # 多次滤波以获得更平滑的趋势
            y_trend = savgol_filter(y, sg_window, 3)
            y_trend = savgol_filter(y_trend, sg_window, 3)  # 二次滤波
            
            # 如果数据足够长，尝试低通滤波
            if n > 100:
                try:
                    # 极低截止频率的低通滤波器
                    cutoff = 0.005  # 非常低的截止频率
                    b, a = butter(2, cutoff, 'low')
                    y_trend = filtfilt(b, a, y_trend)
                except:
                    pass
                    
        except Exception as e:
            self.log(f"   ⚠️ SG滤波失败: {e}, 使用移动平均")
            # 回退到超大窗口移动平均
            window = max(101, n // 10)
            if window % 2 == 0:
                window += 1
            kernel = np.ones(window) / window
            y_trend = np.convolve(y, kernel, mode='same')
        
        # ============================================================
        # Step 2: MV趋势提取 - 计算等效占空比
        # ============================================================
        # 对ON-OFF的MV，计算移动平均得到等效连续MV
        mv_window = max(51, n // 20)
        if mv_window % 2 == 0:
            mv_window += 1
        
        kernel = np.ones(mv_window) / mv_window
        u_trend = np.convolve(u, kernel, mode='same')
        
        # 边缘处理
        half_w = mv_window // 2
        u_trend[:half_w] = np.mean(u[:mv_window])
        u_trend[-half_w:] = np.mean(u[-mv_window:])
        
        self.log(f"   🔧 趋势提取: SG窗口={sg_window}, MV窗口={mv_window}")
        self.log(f"      PV趋势范围: [{np.min(y_trend):.2f}, {np.max(y_trend):.2f}]")
        self.log(f"      MV等效范围: [{np.min(u_trend):.2f}, {np.max(u_trend):.2f}]")
        
        return y_trend, u_trend
    
    def _select_best_window_params(self, model_window_results: Dict[str, List[Dict]]
                                    ) -> Dict[str, Dict[str, float]]:
        """
        使用分级融合策略选择最佳参数
        
        分级策略：
        1. K 一致性好 (CV < 20%) → R² 加权融合
        2. K 有差异 (20% ≤ CV < 50%) → 只用最佳窗口
        3. K 差异大 (CV ≥ 50%) → 保守选择
        """
        # 初始化融合策略
        fusion_strategy = PIDFusionStrategy(verbose=self.verbose)
        
        result = {}
        for model_type in self.CANDIDATE_MODELS:
            window_results = model_window_results[model_type]
            if not window_results:
                continue
            
            # 转换为 WindowResult 格式
            window_objs = []
            for w in window_results:
                window_objs.append(WindowResult(
                    window_idx=w['window_idx'],
                    K=w['params']['K'],
                    T1=w['params']['T1'],
                    T2=w['params']['T2'],
                    L=w['params']['L'],
                    r2=w['r2'],
                    data_points=w.get('data_points', 50)
                ))
            
            # 使用分级策略融合
            try:
                fusion_result = fusion_strategy.fuse(window_objs)
                
                result[model_type] = {
                    'K': fusion_result.K,
                    'T1': fusion_result.T1,
                    'T2': fusion_result.T2,
                    'L': fusion_result.L,
                    'window_count': len(fusion_result.windows_used),
                    'best_window': fusion_result.windows_used[0] if fusion_result.windows_used else 1,
                    'best_r2': fusion_result.confidence,
                    'valid_window_indices': fusion_result.windows_used,
                    'fusion_strategy': fusion_result.strategy_used.value,
                    'fusion_reasoning': fusion_result.reasoning
                }
                
                p = result[model_type]
                self.log(f"📊 {model_type}: {fusion_result.strategy_used.value} "
                         f"(窗口{fusion_result.windows_used}), "
                         f"K={p['K']:.4f}, T1={p['T1']:.4f}, L={p['L']:.4f}")
                
            except Exception as e:
                self.log(f"⚠️ {model_type} 融合失败: {e}")
                # 回退到简单的最佳窗口选择
                if window_results:
                    best = max(window_results, key=lambda x: x['r2'])
                    result[model_type] = {
                        'K': best['params']['K'],
                        'T1': best['params']['T1'],
                        'T2': best['params']['T2'],
                        'L': best['params']['L'],
                        'window_count': 1,
                        'best_window': best['window_idx'],
                        'best_r2': best['r2'],
                        'valid_window_indices': [best['window_idx']],
                        'fusion_strategy': 'fallback',
                        'fusion_reasoning': f'融合失败，回退到最佳窗口: {e}'
                    }
        
        return result
    
    def _params_dict_to_tuple(self, params: Dict[str, float], model_type: str) -> tuple:
        """将参数字典转换为模型需要的元组格式"""
        converter = self.PARAMS_TO_TUPLE.get(model_type)
        if converter:
            return converter(params)
        return (params['K'], params['T1'], params['L'])
    
    def _build_final_result(self, best_result: Dict, 
                            time_range: Dict,
                            lambda_factor: float) -> Dict[str, Any]:
        """
        Step 3: 构建最终输出
        
        输出格式严格按照用户要求：
        - model_type: 模型类型
        - model_rating: 模型评分 (R² * 10)
        - start_time / end_time: 整段数据时间范围
        - model_parameters: {K, T1, T2, L}
        - pid_parameters: {Kp, Ki, Kd}
        - fitting_result: {timestamp, sv, pv, mv, pv_model, r_squared, rmse}
        """
        params = best_result['params']
        model_type = best_result['model_type']
        hist_data = best_result['hist_data']
        
        # 计算 PID 参数
        pid_params = self._calculate_pid(
            params['K'], params['T1'], params['T2'], params['L'],
            model_type, lambda_factor
        )
        
        # 构建符合用户要求的输出格式
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
                'timestamp': hist_data.timestamp.tolist(),  # 真实时间戳（毫秒）
                'sv': hist_data.sv.tolist(),                # 设定值数组
                'pv': hist_data.pv.tolist(),                # 测量值数组
                'mv': hist_data.mv.tolist(),                # 控制值数组
                'pv_model': best_result['y_pred'].tolist(), # 模拟拟合值
                'r_squared': round(best_result['r2'], 4),   # R² 值
                'rmse': round(best_result['rmse'], 4)       # RMSE 值
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
        
        # 一阶/二阶模型
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
            'Kd': round(float(Kd), 4),
            'Ti': round(float(Ti), 4),
            'Td': round(float(Td), 4)
        }
    
    def _empty_result(self, stability_result: Dict) -> Dict[str, Any]:
        """空结果"""
        return {
            'model_type': ModelType.FOPDT,
            'model_rating': 0.0,
            'start_time': stability_result.get('start_time'),
            'end_time': stability_result.get('end_time'),
            'model_parameters': {'K': 0.0, 'T1': 0.0, 'T2': 0.0, 'L': 0.0},
            'pid_parameters': {'Kp': 1.0, 'Ki': 0.05, 'Kd': 0.0},
            'fitting_result': {
                'timestamp': [], 'sv': [], 'pv': [], 'mv': [],
                'pv_model': [], 'r_squared': 0.0, 'rmse': 0.0
            }
        }

def detect_model_type(data: List[Dict[str, Any]], verbose: bool = False) -> Dict[str, Any]:
    """便捷函数：检测模型类型"""
    return ModelTypeDetector(verbose=verbose).detect(data)


def fit_model_from_tuning_input(tuning_input: Union[Dict[str, Any], TuningInput],
                                 raw_data: List[Dict[str, Any]],
                                 verbose: bool = False,
                                 lambda_factor: float = 0.8) -> Dict[str, Any]:
    """
    便捷函数：基于整定输入进行模型拟合
    
    Args:
        tuning_input: 整定输入，格式为：
            {
                "start_time": datetime,
                "end_time": datetime,
                "params": {...},
                "total_windows": int,
                "tuning_window": [{"start_time": datetime, "end_time": datetime}, ...]
            }
        raw_data: 原始数据
        verbose: 是否输出详细日志
        lambda_factor: Lambda 整定系数
        
    Returns:
        {
            "model_type": str,
            "model_rating": float,
            "start_time": datetime,
            "end_time": datetime,
            "model_parameters": {"K": float, "T1": float, "T2": float, "L": float},
            "pid_parameters": {"Kp": float, "Ki": float, "Kd": float},
            "fitting_result": {
                "timestamp": list,  # 真实时间戳（毫秒）
                "sv": list, "pv": list, "mv": list,
                "pv_model": list,
                "r_squared": float, "rmse": float
            }
        }
    """
    return ModelFitter(verbose=verbose).fit(tuning_input, raw_data, lambda_factor)


# 保留旧接口兼容性
def fit_model_from_stability(stability_result: Dict[str, Any],
                              raw_data: List[Dict[str, Any]],
                              verbose: bool = False,
                              lambda_factor: float = 0.8) -> Dict[str, Any]:
    """便捷函数：基于稳定性检测结果进行模型拟合（兼容旧接口）"""
    return ModelFitter(verbose=verbose).fit(stability_result, raw_data, lambda_factor)
