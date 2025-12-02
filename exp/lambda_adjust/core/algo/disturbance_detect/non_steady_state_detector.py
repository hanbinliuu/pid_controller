import json
import os
import numpy as np
from typing import List, Dict, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum
import matplotlib.pyplot as plt


class SegmentType(str, Enum):
    """段类型枚举"""
    STEADY_STATE = "steady_state"  # 稳态段
    NON_STEADY_STATE = "non_steady_state"  # 非稳态段（需要重新整定）
    SETPOINT_CHANGE = "setpoint_change"  # 设定值调整过程（不算非稳态）
    RECOVERED_NON_STEADY = "recovered_non_steady"  # 已恢复的非稳态段（稳态->非稳态->稳态，不需要重新整定）


@dataclass
class Segment:
    """数据段信息"""
    start_idx: int  # 起始索引
    end_idx: int  # 结束索引
    start_time: float  # 起始时间（秒）
    end_time: float  # 结束时间（秒）
    segment_type: SegmentType  # 段类型
    description: str  # 描述信息
    setpoint_direction: Optional[str] = None  # 设定值变化方向（仅用于SETPOINT_CHANGE类型）: "up", "down", None


@dataclass
class DetectionResult:
    """检测结果"""
    segments: List[Segment]  # 所有段
    non_steady_segments: List[Segment]  # 非稳态段（需要重新整定的段）
    steady_state_segments: List[Segment]  # 稳态段
    setpoint_change_segments: List[Segment]  # 设定值调整段
    recovered_non_steady_segments: List[Segment]  # 已恢复的非稳态段（不需要重新整定）
    scenario_type: str  # 场景类型：scenario_1, scenario_2, scenario_3
    metadata: Dict  # 元数据


class NonSteadyStateDetector:
    """
    PID非稳态段检测器
    
    用于检测PID控制数据中的非稳态段。
    假设数据一开始在旧的PID参数下是稳态的，检测后续出现的非稳态或设定值调整。
    """
    
    # 常量定义
    _POINTS_IN_THRESHOLD_RATIO = 0.95  # 稳态判断：至少95%的点在阈值范围内
    _MAX_DEVIATION_MULTIPLIER = 1.8  # 最大偏差倍数
    _OSCILLATION_RANGE_MULTIPLIER = 2.0  # 振荡幅度倍数
    _LARGE_DEVIATION_MULTIPLIER = 1.5  # 大偏差倍数
    _LARGE_DEVIATION_RATIO = 0.1  # 大偏差点占比阈值
    _THRESHOLD_MULTIPLIER = 1.2  # 阈值检查倍数
    _MIN_CHECK_POINTS = 10  # 最小检查点数
    _SETPOINT_CHANGE_WINDOW = 100  # 设定值变化检测窗口
    _SETPOINT_SLOPE_DIVISOR = 100  # 设定值斜率归一化除数
    _SETPOINT_STABLE_WINDOW = 30  # 设定值稳定检测窗口（用于判断设定值调整是否结束）
    _SETPOINT_STABLE_THRESHOLD = 0.1  # 设定值稳定阈值（设定值变化小于此值认为稳定）
    
    def __init__(self, 
                 steady_state_window: int = 100,
                 steady_state_threshold: float = 0.5,
                 steady_state_std_threshold: float = 0.3,
                 min_non_steady_duration: int = 30,
                 setpoint_change_threshold: float = 0.3):
        """
        初始化检测器
        
        Args:
            steady_state_window: 稳态判断窗口大小（数据点数量）
                - 用于判断稳态的滑动窗口大小，窗口越大判断越稳定但响应越慢
                - 推荐值：30-100，根据采样频率调整（如1秒1个点，50点=50秒）
            
            steady_state_threshold: PV波动阈值（与设定值的允许偏差）
                - **这是最重要的参数**：控制过程值(PV)相对于目标温度(设定值)的允许偏差
                - 例如：如果目标温度是5.0，threshold=0.5，则PV在4.5-5.5范围内被认为是稳态
                - 推荐值：
                  * 温度控制：0.3-0.8（根据精度要求）
                  * 流量控制：0.1-0.3（通常需要更高精度）
                  * 压力控制：0.2-0.5
            
            steady_state_std_threshold: 稳态标准差阈值
                - 控制PV波动的标准差上限，越小越严格
                - 推荐值：steady_state_threshold的0.5-0.8倍
            
            min_non_steady_duration: 非稳态段最小持续时间（数据点数量）
                - 小于此持续时间的非稳态段会被忽略（可能是噪声）
                - 推荐值：20-50，根据采样频率调整
            
            setpoint_change_threshold: 设定值变化检测阈值
                - 如果设定值变化超过此值，认为是目标温度调整过程
                - 推荐值：steady_state_threshold的0.5-1.0倍
        
        使用示例：
            # 对于温度控制，目标温度5.0，允许±0.5的波动
            detector = NonSteadyStateDetector(
                steady_state_threshold=0.5,  # PV允许偏差±0.5
                steady_state_std_threshold=0.3,  # 标准差阈值0.3
            )
            
            # 对于高精度控制，目标温度5.0，只允许±0.2的波动
            detector = NonSteadyStateDetector(
                steady_state_threshold=0.2,  # PV允许偏差±0.2（更严格）
                steady_state_std_threshold=0.15,  # 标准差阈值0.15
            )
        """
        self.steady_state_window = steady_state_window
        self.steady_state_threshold = steady_state_threshold
        self.steady_state_std_threshold = steady_state_std_threshold
        self.min_non_steady_duration = min_non_steady_duration
        self.setpoint_change_threshold = setpoint_change_threshold
    
    def is_steady_state(self, pv_data: np.ndarray, setpoint: float, 
                       start_idx: int, end_idx: int) -> bool:
        """
        判断指定区间是否为稳态
        
        稳态的判断标准：
        1. 均值接近设定值
        2. 波动足够小（标准差小）
        3. 大部分点在阈值范围内
        4. 最大偏差在可接受范围内
        5. 振荡幅度不能太大（峰值到峰值的范围）
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            bool: 是否为稳态
        """
        if end_idx - start_idx < self.steady_state_window:
            return False
        
        segment_pv = pv_data[start_idx:end_idx]
        deviations = np.abs(segment_pv - setpoint)
        
        # 1. 检查均值是否接近设定值
        mean_pv = np.mean(segment_pv)
        if abs(mean_pv - setpoint) > self.steady_state_threshold:
            return False
        
        # 2. 检查波动是否足够小（标准差）
        std_dev = np.std(deviations)
        if std_dev > self.steady_state_std_threshold:
            return False
        
        # 3. 检查大部分点是否在阈值范围内
        threshold_check = self.steady_state_threshold * self._THRESHOLD_MULTIPLIER
        points_in_threshold = np.sum(deviations < threshold_check)
        if points_in_threshold < len(deviations) * self._POINTS_IN_THRESHOLD_RATIO:
            return False
        
        # 4. 检查最大偏差是否在可接受范围内
        max_deviation = np.max(deviations)
        if max_deviation > self.steady_state_threshold * self._MAX_DEVIATION_MULTIPLIER:
            return False
        
        # 5. 检查振荡幅度（峰值到峰值的范围）
        pv_range = np.max(segment_pv) - np.min(segment_pv)
        if pv_range > self.steady_state_threshold * self._OSCILLATION_RANGE_MULTIPLIER:
            return False
        
        # 6. 检查是否有持续的大偏差
        large_deviation_threshold = self.steady_state_threshold * self._LARGE_DEVIATION_MULTIPLIER
        large_deviation_mask = deviations > large_deviation_threshold
        if np.sum(large_deviation_mask) > len(deviations) * self._LARGE_DEVIATION_RATIO:
            return False
        
        return True
    
    def is_setpoint_changing(self, sv_data: np.ndarray, 
                            start_idx: int, end_idx: int) -> bool:
        """
        判断指定区间内设定值是否在变化
        
        Args:
            sv_data: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            bool: 如果设定值在变化返回True，否则返回False
        """
        if end_idx - start_idx < 5:
            return False
        
        segment_sv = sv_data[start_idx:end_idx]
        
        # 计算设定值的变化范围
        sv_range = np.max(segment_sv) - np.min(segment_sv)
        
        # 如果设定值变化超过阈值，认为是设定值调整过程
        if sv_range > self.setpoint_change_threshold:
            return True
        
        # 检查是否有明显的趋势性变化
        if len(segment_sv) > self._MIN_CHECK_POINTS:
            x = np.arange(len(segment_sv))
            coeffs = np.polyfit(x, segment_sv, 1)
            slope = abs(coeffs[0])
            
            # 如果斜率足够大，认为设定值在变化
            if slope > self.setpoint_change_threshold / self._SETPOINT_SLOPE_DIVISOR:
                return True
        
        return False
    
    def is_setpoint_stable(self, sv_data: np.ndarray, 
                          start_idx: int, end_idx: int) -> bool:
        """
        判断指定区间内设定值是否已稳定（用于检测设定值调整是否结束）
        
        Args:
            sv_data: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            bool: 如果设定值已稳定返回True，否则返回False
        """
        if end_idx - start_idx < self._SETPOINT_STABLE_WINDOW:
            return False
        
        segment_sv = sv_data[start_idx:end_idx]
        
        # 计算设定值的变化范围
        sv_range = np.max(segment_sv) - np.min(segment_sv)
        
        # 如果设定值变化小于稳定阈值，认为已稳定
        if sv_range < self._SETPOINT_STABLE_THRESHOLD:
            return True
        
        # 检查是否有明显的趋势性变化（如果没有明显趋势，认为稳定）
        if len(segment_sv) > self._MIN_CHECK_POINTS:
            x = np.arange(len(segment_sv))
            coeffs = np.polyfit(x, segment_sv, 1)
            slope = abs(coeffs[0])
            
            # 如果斜率很小，认为设定值已稳定
            if slope < self._SETPOINT_STABLE_THRESHOLD / self._SETPOINT_SLOPE_DIVISOR:
                return True
        
        return False
    
    def get_setpoint_change_direction(self, sv_data: np.ndarray,
                                     start_idx: int, end_idx: int) -> Optional[str]:
        """
        获取设定值变化方向
        
        Args:
            sv_data: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            Optional[str]: "up"表示上升, "down"表示下降, None表示无法判断
        """
        if end_idx - start_idx < 2:
            return None
        
        start_sv = sv_data[start_idx]
        end_sv = sv_data[end_idx - 1]
        
        if end_sv > start_sv + self._SETPOINT_STABLE_THRESHOLD:
            return "up"
        elif end_sv < start_sv - self._SETPOINT_STABLE_THRESHOLD:
            return "down"
        else:
            return None
    
    def detect_segments(self, pv_data: np.ndarray, 
                       sv_data: Optional[np.ndarray] = None,
                       setpoint: Optional[float] = None,
                       time_data: Optional[np.ndarray] = None) -> List[Segment]:
        """
        检测数据中的所有段（稳态、非稳态、设定值调整、已恢复的非稳态）
        
        假设数据一开始在旧的PID参数下是稳态的，检测后续出现的非稳态或设定值调整。
        
        Args:
            pv_data: 过程值数组
            sv_data: 设定值数组（可选），如果提供则用于检测设定值变化
            setpoint: 设定值（可选），如果sv_data未提供则使用此固定值
            time_data: 时间数组（可选）
            
        Returns:
            List[Segment]: 检测到的段列表
        """
        n = len(pv_data)
        if time_data is None:
            time_data = np.arange(n)
        
        if n < self.steady_state_window:
            # 数据太短，无法判断
            return []
        
        # 处理设定值数据
        if sv_data is None:
            if setpoint is None:
                raise ValueError("必须提供sv_data或setpoint参数")
            # 创建固定设定值数组
            sv_data = np.full(n, setpoint)
        else:
            sv_data = np.array(sv_data)
            if len(sv_data) != n:
                raise ValueError(f"sv_data长度({len(sv_data)})与pv_data长度({n})不匹配")
            # 如果没有提供setpoint，使用第一个设定值
            if setpoint is None:
                setpoint = sv_data[0]
        
        # 使用滑动窗口标记每个点的状态
        # 使用整数映射：1=稳态, 2=非稳态, 3=设定值调整, 4=已恢复的非稳态, -1=未分类
        type_map = {
            SegmentType.STEADY_STATE: 1,
            SegmentType.NON_STEADY_STATE: 2,
            SegmentType.SETPOINT_CHANGE: 3,
            SegmentType.RECOVERED_NON_STEADY: 4
        }
        reverse_map = {v: k for k, v in type_map.items()}
        
        segment_labels = np.full(n, -1, dtype=int)  # -1表示未分类
        
        # 第一步：检测设定值变化段（优先于其他检测）
        self._detect_setpoint_changes(sv_data, n, segment_labels, type_map)
        
        # 第一步半：检查设定值调整段内是否出现非稳态特征
        # 如果设定值调整后PV出现大幅振荡，应该标记为非稳态段而不是设定值调整段
        self._check_non_steady_in_setpoint_changes(pv_data, sv_data, n, segment_labels, type_map)
        
        # 第二步：使用滑动窗口检测稳态段
        # 假设数据一开始在旧的PID参数下是稳态的
        window = self.steady_state_window
        
        # 对于每个窗口，使用窗口结束时刻的设定值来判断稳态（而不是平均值）
        # 这样可以更准确地反映当前时刻的设定值
        # 优化：设定值调整结束后，应该能够检测到新的稳态
        for i in range(window, n + 1):
            window_start = i - window
            window_end = i
            # 检查窗口内是否有设定值调整段
            window_labels = segment_labels[window_start:window_end]
            has_setpoint_change = np.any(window_labels == type_map[SegmentType.SETPOINT_CHANGE])
            
            # 如果窗口内没有设定值调整段，或者设定值调整已结束，可以检测稳态
            # 对于设定值调整后的稳态检测，需要确保使用新的设定值
            if not has_setpoint_change:
                # 使用窗口结束时刻的设定值来判断稳态（更准确）
                current_setpoint = sv_data[window_end - 1]
                if self.is_steady_state(pv_data, current_setpoint, window_start, window_end):
                    # 只标记未分类的点为稳态（设定值调整段保持不变）
                    mask = segment_labels[window_start:window_end] == -1
                    segment_labels[window_start:window_end][mask] = type_map[SegmentType.STEADY_STATE]
            else:
                # 窗口内有设定值调整段，但检查设定值调整是否已结束
                # 如果设定值调整已结束，且PV已接近新设定值，可以标记为稳态
                # 这处理了设定值调整后的过渡期
                current_setpoint = sv_data[window_end - 1]
                # 检查窗口后半部分是否设定值已稳定
                check_start = max(window_start, window_end - self._SETPOINT_STABLE_WINDOW)
                if self.is_setpoint_stable(sv_data, check_start, window_end):
                    # 设定值已稳定，检查PV是否接近新设定值
                    # 使用较小的窗口检查PV是否已稳定在新设定值附近
                    pv_check_start = max(window_start, window_end - window // 2)
                    if self.is_steady_state(pv_data, current_setpoint, pv_check_start, window_end):
                        # PV已稳定在新设定值附近，标记为稳态
                        mask = (segment_labels[pv_check_start:window_end] == -1)
                        segment_labels[pv_check_start:window_end][mask] = type_map[SegmentType.STEADY_STATE]
        
        # 第三步：对于数据开始部分，如果检测到稳态，则标记为稳态
        self._mark_initial_steady_state(pv_data, sv_data, n, window, segment_labels, type_map)
        
        # 第五步：剩余未分类的点标记为非稳态
        segment_labels[segment_labels == -1] = type_map[SegmentType.NON_STEADY_STATE]
        
        # 第六步：将连续的同类型段合并
        segments = self._merge_continuous_segments(segment_labels, reverse_map, time_data, n, sv_data)
        
        # 第七步：检测被两个稳态段包围的非稳态段，标记为已恢复的非稳态
        for i in range(len(segments)):
            seg = segments[i]
            if seg.segment_type == SegmentType.NON_STEADY_STATE:
                # 检查前后是否有稳态段
                prev_steady = False
                next_steady = False
                
                if i > 0:
                    prev_seg = segments[i-1]
                    if prev_seg.segment_type == SegmentType.STEADY_STATE:
                        prev_steady = True
                
                if i < len(segments) - 1:
                    next_seg = segments[i+1]
                    if next_seg.segment_type == SegmentType.STEADY_STATE:
                        next_steady = True
                
                # 如果前后都是稳态段，标记为已恢复的非稳态（不需要重新整定）
                if prev_steady and next_steady:
                    seg.segment_type = SegmentType.RECOVERED_NON_STEADY
                    seg.description = self._get_segment_description(SegmentType.RECOVERED_NON_STEADY)
        
        return segments
    
    def _detect_setpoint_changes(self, sv_data: np.ndarray, n: int, 
                                 segment_labels: np.ndarray, type_map: Dict) -> None:
        """
        检测并标记设定值变化段
        
        优化点：
        1. 检测设定值何时开始变化
        2. 检测设定值何时稳定下来（调整结束）
        3. 更精确地标记设定值调整段的边界
        """
        setpoint_changes = []
        in_change = False
        change_start = None
        
        for i in range(self._MIN_CHECK_POINTS, n + 1):
            # 使用滑动窗口检测设定值变化
            window_start = max(0, i - self._SETPOINT_CHANGE_WINDOW)
            window_end = i
            
            if not in_change:
                # 检测设定值是否开始变化
                if self.is_setpoint_changing(sv_data, window_start, window_end):
                    in_change = True
                    change_start = window_start
            else:
                # 检测设定值是否已稳定（调整结束）
                # 使用较小的窗口检测稳定性
                stable_window_start = max(change_start, i - self._SETPOINT_STABLE_WINDOW)
                if self.is_setpoint_stable(sv_data, stable_window_start, window_end):
                    # 设定值已稳定，结束调整段
                    setpoint_changes.append([change_start, window_end])
                    in_change = False
                    change_start = None
                elif i == n:
                    # 数据结束，如果还在变化中，标记到最后
                    setpoint_changes.append([change_start, n])
        
        # 标记所有设定值变化区间
        for start, end in setpoint_changes:
            end_idx = min(end, n)
            mask = segment_labels[start:end_idx] == -1
            segment_labels[start:end_idx][mask] = type_map[SegmentType.SETPOINT_CHANGE]
    
    def _has_oscillation_pattern(self, pv_data: np.ndarray, setpoint: float, 
                                  start_idx: int, end_idx: int) -> bool:
        """
        检测是否有明显的振荡模式
        
        振荡的特征：
        1. PV围绕设定值上下波动（不是单向偏离）
        2. 有多个峰值和谷值（至少2个完整的振荡周期）
        3. 振荡幅度持续较大
        4. 必须是围绕设定值的振荡，而不是正常跟随设定值的变化
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            bool: 是否存在振荡模式
        """
        if end_idx - start_idx < 20:  # 至少需要20个点才能可靠检测振荡
            return False
        
        segment_pv = pv_data[start_idx:end_idx]
        deviations = segment_pv - setpoint
        
        # 1. 检查振荡幅度（必须足够大才能认为是非稳态）
        pv_range = np.max(segment_pv) - np.min(segment_pv)
        oscillation_threshold = self.steady_state_threshold * self._OSCILLATION_RANGE_MULTIPLIER * 2.0  # 提高阈值
        if pv_range < oscillation_threshold:
            return False
        
        # 2. 检测峰值和谷值（寻找振荡周期）
        # 使用差分检测局部极值
        diff = np.diff(deviations)
        sign_changes = 0
        for i in range(1, len(diff)):
            if diff[i] * diff[i-1] < 0:  # 符号变化，表示极值点
                sign_changes += 1
        
        # 至少需要4个符号变化（2个峰值+2个谷值，即至少2个完整振荡周期）才能认为是振荡
        # 这样可以避免将正常的设定值跟随过程误判为振荡
        if sign_changes < 4:
            return False
        
        # 3. 检查是否围绕设定值振荡（而不是单向偏离或正常跟随）
        above_setpoint = np.sum(deviations > 0)
        below_setpoint = np.sum(deviations < 0)
        # 上下波动应该都有，且比例不能太极端（至少30%的点在设定值上方，30%在下方）
        if above_setpoint < len(deviations) * 0.3 or below_setpoint < len(deviations) * 0.3:
            return False
        
        # 4. 检查最大偏差（必须足够大）
        max_deviation = np.max(np.abs(deviations))
        deviation_threshold = self.steady_state_threshold * self._MAX_DEVIATION_MULTIPLIER * 2.0  # 提高阈值
        if max_deviation < deviation_threshold:
            return False
        
        # 5. 检查是否有明显的振荡趋势（而不是单调变化）
        # 计算PV的变化方向变化次数
        pv_diff = np.diff(segment_pv)
        direction_changes = 0
        for i in range(1, len(pv_diff)):
            if pv_diff[i] * pv_diff[i-1] < 0:  # 方向变化
                direction_changes += 1
        
        # 如果方向变化太少，可能是单调变化（正常跟随设定值），不是振荡
        if direction_changes < 3:
            return False
        
        return True
    
    def _check_non_steady_in_setpoint_changes(self, pv_data: np.ndarray, sv_data: np.ndarray,
                                              n: int, segment_labels: np.ndarray, type_map: Dict) -> None:
        """
        检查设定值调整段内是否出现非稳态特征
        
        如果设定值调整后PV出现大幅振荡（非稳态特征），应该将该部分重新标记为非稳态段。
        关键改进：只有当出现明显的振荡模式时，才标记为非稳态，而不是简单的偏差。
        这样可以更准确地识别振荡开始的时刻（如绿色框区域）。
        
        Args:
            pv_data: 过程值数组
            sv_data: 设定值数组
            n: 数据长度
            segment_labels: 段标签数组
            type_map: 类型映射字典
        """
        setpoint_change_type = type_map[SegmentType.SETPOINT_CHANGE]
        non_steady_type = type_map[SegmentType.NON_STEADY_STATE]
        
        # 找到所有设定值调整段的区间
        setpoint_segments = []
        i = 0
        while i < n:
            if segment_labels[i] == setpoint_change_type:
                start = i
                # 找到连续段
                while i < n and segment_labels[i] == setpoint_change_type:
                    i += 1
                end = i
                setpoint_segments.append((start, end))
            else:
                i += 1
        
        # 对每个设定值调整段，检查是否出现非稳态特征
        window = self.steady_state_window
        min_check_window = max(window // 2, 20)  # 使用足够大的窗口来可靠检测振荡（至少20个点）
        
        for seg_start, seg_end in setpoint_segments:
            if seg_end - seg_start < min_check_window:
                continue
            
            # 找到设定值开始稳定的位置
            setpoint_stable_start = seg_start
            for i in range(seg_start, seg_end):
                if i + self._SETPOINT_STABLE_WINDOW <= seg_end:
                    if self.is_setpoint_stable(sv_data, i, min(i + self._SETPOINT_STABLE_WINDOW, seg_end)):
                        setpoint_stable_start = i
                        break
            
            # 从设定值稳定后开始检查振荡
            # 设定值调整初期（设定值还在变化时），PV正常跟随设定值是正常的，不应该标记为非稳态
            # 只有当设定值稳定后，PV仍然出现振荡，才应该标记为非稳态
            check_start = max(seg_start, setpoint_stable_start)  # 从设定值稳定后开始检查
            
            # 记录第一个检测到振荡的位置
            first_oscillation_start = None
            
            # 使用滑动窗口检查非稳态
            for i in range(check_start + min_check_window, seg_end + 1):
                window_start = max(check_start, i - min_check_window)
                window_end = i
                
                # 使用当前时刻的设定值来判断
                current_setpoint = sv_data[window_end - 1]
                
                # 检查是否有明显的振荡模式（必须是围绕设定值的振荡，而不是正常跟随）
                if self._has_oscillation_pattern(pv_data, current_setpoint, window_start, window_end):
                    if first_oscillation_start is None:
                        first_oscillation_start = window_start
                    
                    # 标记为非稳态段（从振荡开始的位置到当前）
                    # 但只标记当前窗口内的点，避免重复标记
                    mask = (segment_labels[window_start:window_end] == setpoint_change_type)
                    segment_labels[window_start:window_end][mask] = non_steady_type
            
            # 如果检测到振荡，将振荡开始位置之后的所有设定值调整段都标记为非稳态
            if first_oscillation_start is not None:
                # 从振荡开始位置到段结束，都标记为非稳态
                mask = (segment_labels[first_oscillation_start:seg_end] == setpoint_change_type)
                segment_labels[first_oscillation_start:seg_end][mask] = non_steady_type
    
    def _mark_initial_steady_state(self, pv_data: np.ndarray, sv_data: np.ndarray,
                                    n: int, window: int, segment_labels: np.ndarray,
                                    type_map: Dict) -> None:
        """标记数据开始部分的稳态段"""
        initial_window = min(window, n)
        if initial_window >= self._MIN_CHECK_POINTS:
            initial_setpoint = sv_data[0]
            check_window = min(initial_window, window)
            if (check_window >= self._MIN_CHECK_POINTS and 
                self.is_steady_state(pv_data, initial_setpoint, 0, check_window)):
                mask = segment_labels[:initial_window] == -1
                segment_labels[:initial_window][mask] = type_map[SegmentType.STEADY_STATE]
    
    def _merge_continuous_segments(self, segment_labels: np.ndarray, reverse_map: Dict,
                                   time_data: np.ndarray, n: int, sv_data: Optional[np.ndarray] = None) -> List[Segment]:
        """将连续的同类型段合并"""
        segments = []
        current_start = 0
        current_type_val = segment_labels[0]
        current_type = reverse_map[current_type_val]
        
        for i in range(1, n):
            if segment_labels[i] != current_type_val:
                seg = self._create_segment(current_start, i, current_type, time_data, sv_data)
                segments.append(seg)
                current_start = i
                current_type_val = segment_labels[i]
                current_type = reverse_map[current_type_val]
        
        if current_start < n:
            seg = self._create_segment(current_start, n, current_type, time_data, sv_data)
            segments.append(seg)
        
        # 合并太短的非稳态段
        return self._merge_short_non_steady_segments(segments)
    
    def _create_segment(self, start_idx: int, end_idx: int, segment_type: SegmentType,
                       time_data: np.ndarray, sv_data: Optional[np.ndarray] = None) -> Segment:
        """创建段对象"""
        setpoint_direction = None
        if segment_type == SegmentType.SETPOINT_CHANGE and sv_data is not None:
            setpoint_direction = self.get_setpoint_change_direction(sv_data, start_idx, end_idx)
        
        description = self._get_segment_description(segment_type, setpoint_direction)
        
        return Segment(
            start_idx=start_idx,
            end_idx=end_idx,
            start_time=time_data[start_idx],
            end_time=time_data[end_idx - 1] if end_idx > 0 else time_data[start_idx],
            segment_type=segment_type,
            description=description,
            setpoint_direction=setpoint_direction
        )
    
    def _merge_short_non_steady_segments(self, segments: List[Segment]) -> List[Segment]:
        """合并太短的非稳态段"""
        if not segments:
            return segments
        
        # 第一遍：合并到前一段
        merged = []
        for seg in segments:
            if (seg.segment_type == SegmentType.NON_STEADY_STATE and
                seg.end_idx - seg.start_idx < self.min_non_steady_duration):
                if merged:
                    prev_seg = merged[-1]
                    prev_seg.end_idx = seg.end_idx
                    prev_seg.end_time = seg.end_time
                else:
                    merged.append(seg)
            else:
                merged.append(seg)
        
        # 第二遍：处理剩余太短的段
        i = 0
        while i < len(merged):
            seg = merged[i]
            if (seg.segment_type == SegmentType.NON_STEADY_STATE and
                seg.end_idx - seg.start_idx < self.min_non_steady_duration):
                if i > 0:
                    merged[i-1].end_idx = seg.end_idx
                    merged[i-1].end_time = seg.end_time
                    merged.pop(i)
                    continue
                elif i < len(merged) - 1:
                    merged[i+1].start_idx = seg.start_idx
                    merged[i+1].start_time = seg.start_time
                    merged.pop(i)
                    continue
            i += 1
        
        return merged
    
    def _get_segment_description(self, segment_type: SegmentType, setpoint_direction: Optional[str] = None) -> str:
        """获取段的描述信息"""
        base_descriptions = {
            SegmentType.STEADY_STATE: "稳态段",
            SegmentType.NON_STEADY_STATE: "非稳态段（需要重新整定PID参数）",
            SegmentType.SETPOINT_CHANGE: "设定值调整过程（不算非稳态）",
            SegmentType.RECOVERED_NON_STEADY: "已恢复的非稳态段（稳态->非稳态->稳态，不需要重新整定）"
        }
        
        base_desc = base_descriptions.get(segment_type, "未知类型")
        
        # 为设定值调整段添加方向信息
        if segment_type == SegmentType.SETPOINT_CHANGE and setpoint_direction:
            direction_desc = "上升" if setpoint_direction == "up" else "下降"
            return f"{base_desc}（{direction_desc}）"
        
        return base_desc
    
    def identify_scenario(self, segments: List[Segment]) -> str:
        """
        识别场景类型
        
        假设数据一开始在旧的PID参数下是稳态的。
        
        Args:
            segments: 段列表
            
        Returns:
            str: 场景类型（scenario_1: 稳态->非稳态, scenario_2: 稳态->设定值调整, scenario_3: 一开始就是非稳态）
        """
        if not segments:
            return "unknown"
        
        # 检查第一个段
        first_segment = segments[0]
        
        # 场景3：一开始就是非稳态（虽然按照新逻辑这应该很少见）
        if first_segment.segment_type == SegmentType.NON_STEADY_STATE:
            return "scenario_3"
        
        # 检查是否有稳态段，然后出现非稳态段或设定值调整
        has_steady_state = any(seg.segment_type == SegmentType.STEADY_STATE for seg in segments)
        has_non_steady_after_steady = False
        has_setpoint_change_after_steady = False
        
        found_steady = False
        for seg in segments:
            if seg.segment_type == SegmentType.STEADY_STATE:
                found_steady = True
            elif found_steady:
                if seg.segment_type == SegmentType.NON_STEADY_STATE:
                    has_non_steady_after_steady = True
                    break
                elif seg.segment_type == SegmentType.SETPOINT_CHANGE:
                    has_setpoint_change_after_steady = True
                    break
        
        if has_steady_state:
            # 场景1：稳态 -> 非稳态
            if has_non_steady_after_steady:
                return "scenario_1"
            # 场景2：稳态 -> 设定值调整
            elif has_setpoint_change_after_steady:
                return "scenario_2"
            # 只有稳态，没有后续变化
            else:
                return "steady_only"
        
        return "unknown"
    
    def _extract_data_from_json(self, json_data: Union[str, Dict]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict]:
        """从JSON数据中提取时间、PV、SV数据"""
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
        
        timestamps = [item.get("timestamp", 0) / 1000.0 for item in data_list]
        pv_data = np.array([item.get("pv", 0) for item in data_list])
        sv_data = np.array([item.get("sv", 0) for item in data_list])
        time_data = np.array(timestamps)
        
        if len(time_data) > 0:
            time_data = time_data - time_data[0]
        
        return time_data, pv_data, sv_data, data
    
    def detect_from_json(self, json_data: Union[str, Dict]) -> DetectionResult:
        """
        从JSON数据中检测非稳态段
        
        Args:
            json_data: JSON数据（可以是文件路径字符串或字典）
            
        Returns:
            DetectionResult: 检测结果
        """
        time_data, pv_data, sv_data, data = self._extract_data_from_json(json_data)
        setpoint = sv_data[0] if len(sv_data) > 0 else np.mean(sv_data)
        
        segments = self.detect_segments(pv_data, sv_data=sv_data, setpoint=setpoint, time_data=time_data)
        
        # 分类段
        segment_type_map = {
            SegmentType.NON_STEADY_STATE: [],
            SegmentType.STEADY_STATE: [],
            SegmentType.SETPOINT_CHANGE: [],
            SegmentType.RECOVERED_NON_STEADY: []
        }
        for seg in segments:
            segment_type_map[seg.segment_type].append(seg)
        
        metadata = {
            "table": data.get("table", ""),
            "start_time": data.get("start_time", ""),
            "end_time": data.get("end_time", ""),
            "totalRecords": data.get("totalRecords", len(data.get("data", []))),
            "setpoint": setpoint,
            "setpoint_range": float(np.max(sv_data) - np.min(sv_data)) if len(sv_data) > 0 else 0.0
        }
        
        return DetectionResult(
            segments=segments,
            non_steady_segments=segment_type_map[SegmentType.NON_STEADY_STATE],
            steady_state_segments=segment_type_map[SegmentType.STEADY_STATE],
            setpoint_change_segments=segment_type_map[SegmentType.SETPOINT_CHANGE],
            recovered_non_steady_segments=segment_type_map[SegmentType.RECOVERED_NON_STEADY],
            scenario_type=self.identify_scenario(segments),
            metadata=metadata
        )
    
    def get_non_steady_starts(self, detection_result: DetectionResult) -> List[Dict]:
        """
        获取所有非稳态段的起点信息
        
        Args:
            detection_result: 检测结果
            
        Returns:
            List[Dict]: 非稳态段起点列表，每个元素包含：
                - start_idx: 起始索引
                - start_time: 起始时间（秒）
                - duration: 持续时间（数据点数量）
                - description: 描述信息
        """
        starts = []
        for seg in detection_result.non_steady_segments:
            starts.append({
                "start_idx": seg.start_idx,
                "start_time": seg.start_time,
                "duration": seg.end_idx - seg.start_idx,
                "description": seg.description,
                "scenario_type": detection_result.scenario_type
            })
        return starts

    def visualize_detection_result(self, result: DetectionResult, time_data: np.ndarray,
                                   pv_data: np.ndarray, sv_data: np.ndarray,
                                   output_path: Optional[str] = None, show: bool = True) -> None:
        """
        可视化检测结果
        
        Args:
            result: 检测结果
            time_data: 时间数组
            pv_data: 过程值数组
            sv_data: 设定值数组
            output_path: 输出文件路径（可选）
            show: 是否显示图片（默认True），False时只保存不显示
        """
        plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        
        fig, ax = plt.subplots(1, 1, figsize=(16, 8))
        setpoint = sv_data[0] if len(sv_data) > 0 else np.mean(sv_data)
        
        ax.plot(time_data, pv_data, 'b-', linewidth=1.5, alpha=0.7, label='过程值 (PV)')
        
        if len(np.unique(sv_data)) == 1:
            ax.axhline(y=sv_data[0], color='r', linestyle='--', linewidth=2, label='设定值 (SV)')
        else:
            ax.plot(time_data, sv_data, 'r--', linewidth=2, alpha=0.8, label='设定值 (SV)')
        
        colors = {
            SegmentType.STEADY_STATE: 'blue',
            SegmentType.NON_STEADY_STATE: 'red',
            SegmentType.SETPOINT_CHANGE: 'orange',
            SegmentType.RECOVERED_NON_STEADY: 'purple'
        }
        
        added_labels = set()
        for seg in result.segments:
            seg_time = time_data[seg.start_idx:seg.end_idx]
            seg_pv = pv_data[seg.start_idx:seg.end_idx]
            color = colors.get(seg.segment_type, 'gray')
            alpha = 0.2 if seg.segment_type == SegmentType.STEADY_STATE else 0.3
            
            label = None
            if seg.segment_type not in added_labels:
                label = seg.description
                added_labels.add(seg.segment_type)
            
            if len(seg_time) > 0:
                y_min = min(seg_pv.min(), setpoint) - 1
                y_max = max(seg_pv.max(), setpoint) + 1
                ax.fill_between(seg_time, y_min, y_max, alpha=alpha, color=color, label=label)
        
        for i, seg in enumerate(result.non_steady_segments, 1):
            start_time = time_data[seg.start_idx]
            start_pv = pv_data[seg.start_idx]
            ax.plot(start_time, start_pv, 'ro', markersize=15, zorder=10,
                   markeredgecolor='darkred', markeredgewidth=2,
                   label='非稳态起点' if i == 1 else "")
            ax.annotate(f'起点 {i}\n索引: {seg.start_idx}\n时间: {start_time:.1f}s',
                       xy=(start_time, start_pv), xytext=(20, 30),
                       textcoords='offset points',
                       bbox=dict(boxstyle='round,pad=0.8', fc='yellow', alpha=0.9,
                               edgecolor='red', linewidth=2),
                       arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2',
                                     color='red', lw=2),
                       fontsize=10, fontweight='bold', ha='left')
        
        ax.set_xlabel('时间 (秒)', fontsize=12, fontweight='bold')
        ax.set_ylabel('过程值 (PV)', fontsize=12, fontweight='bold')
        title = (f'非稳态段检测结果\n场景类型: {result.scenario_type} | '
                f"非稳态段数: {len(result.non_steady_segments)} | 设定值: {setpoint:.2f}")
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3, linestyle='--')
        plt.tight_layout()
        
        if output_path:
            plt.savefig(output_path, dpi=150, bbox_inches='tight')
        
        if show:
            plt.show()
        else:
            plt.close(fig)
    
    def print_detection_summary(self, result: DetectionResult) -> None:
        """打印检测结果摘要"""
        starts = self.get_non_steady_starts(result)
        print("=" * 60)
        print("非稳态段检测结果")
        print("=" * 60)
        print(f"场景类型: {result.scenario_type}")
        print(f"目标温度（设定值）: {result.metadata.get('setpoint', 'N/A'):.2f}")
        print(f"\nPV波动阈值配置:")
        print(f"  - 允许偏差: ±{self.steady_state_threshold:.2f}")
        print(f"  - 标准差阈值: {self.steady_state_std_threshold:.2f}")
        print(f"  - 最大偏差限制: ±{self.steady_state_threshold * self._MAX_DEVIATION_MULTIPLIER:.2f}")
        print(f"  - 振荡幅度限制: {self.steady_state_threshold * self._OSCILLATION_RANGE_MULTIPLIER:.2f}")
        print(f"\n检测结果:")
        print(f"  - 总段数: {len(result.segments)}")
        print(f"  - 稳态段数: {len(result.steady_state_segments)}")
        print(f"  - 设定值调整段数: {len(result.setpoint_change_segments)}")
        print(f"  - 已恢复的非稳态段数: {len(result.recovered_non_steady_segments)}")
        print(f"  - 非稳态段数（需要重新整定）: {len(result.non_steady_segments)}")
        print()
        
        if starts:
            print("非稳态段起点（需要重新整定PID参数）:")
            for i, start in enumerate(starts, 1):
                print(f"  起点 {i}: 索引={start['start_idx']}, 时间={start['start_time']:.2f}s, "
                     f"持续时间={start['duration']}个数据点")
        
        if result.recovered_non_steady_segments:
            print("\n已恢复的非稳态段（不需要重新整定，系统已自动恢复）:")
            for i, seg in enumerate(result.recovered_non_steady_segments, 1):
                print(f"  段 {i}: 索引={seg.start_idx}-{seg.end_idx}, "
                     f"时间={seg.start_time:.2f}s-{seg.end_time:.2f}s")
        
        if result.setpoint_change_segments:
            print("\n设定值调整段（不算非稳态）:")
            for i, seg in enumerate(result.setpoint_change_segments, 1):
                direction_info = ""
                if seg.setpoint_direction:
                    direction_info = f", 方向={seg.setpoint_direction}（{'上升' if seg.setpoint_direction == 'up' else '下降'}）"
                print(f"  段 {i}: 索引={seg.start_idx}-{seg.end_idx}, "
                     f"时间={seg.start_time:.2f}s-{seg.end_time:.2f}s{direction_info}")
    
    def result_to_dict(self, result: DetectionResult) -> Dict:
        """将检测结果转换为字典（用于JSON序列化）"""
        def convert_to_native(obj):
            """将numpy类型转换为Python原生类型"""
            if isinstance(obj, (np.integer, np.int64, np.int32)):
                return int(obj)
            elif isinstance(obj, (np.floating, np.float64, np.float32)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, dict):
                return {k: convert_to_native(v) for k, v in obj.items()}
            elif isinstance(obj, (list, tuple)):
                return [convert_to_native(item) for item in obj]
            else:
                return obj
        
        def segment_to_dict(seg: Segment) -> Dict:
            return {
                "start_idx": int(seg.start_idx),
                "end_idx": int(seg.end_idx),
                "start_time": float(seg.start_time),
                "end_time": float(seg.end_time),
                "segment_type": seg.segment_type.value,
                "description": seg.description,
                "setpoint_direction": seg.setpoint_direction
            }
        
        # 转换metadata中的numpy类型
        metadata = convert_to_native(result.metadata)
        
        return {
            "scenario_type": result.scenario_type,
            "metadata": metadata,
            "segments": [segment_to_dict(seg) for seg in result.segments],
            "non_steady_segments": [segment_to_dict(seg) for seg in result.non_steady_segments],
            "steady_state_segments": [segment_to_dict(seg) for seg in result.steady_state_segments],
            "setpoint_change_segments": [segment_to_dict(seg) for seg in result.setpoint_change_segments],
            "recovered_non_steady_segments": [segment_to_dict(seg) for seg in result.recovered_non_steady_segments],
            "summary": {
                "total_segments": len(result.segments),
                "non_steady_count": len(result.non_steady_segments),
                "steady_state_count": len(result.steady_state_segments),
                "setpoint_change_count": len(result.setpoint_change_segments),
                "recovered_non_steady_count": len(result.recovered_non_steady_segments)
            }
        }


if __name__ == '__main__':
    # 配置参数
    data_dir = 'exp/lambda_adjust/data_simulation/zhongkong'
    output_dir = 'exp/lambda_adjust/core/algo/disturbance_detect/output'
    visualize = False  # 设置为 True 来启用可视化，False 来禁用
    
    # 检测器配置
    detector = NonSteadyStateDetector(
        steady_state_threshold=0.3,
        steady_state_std_threshold=0.3,
    )
    
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 获取所有JSON文件
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    json_files.sort()
    
    if not json_files:
        print(f"在目录 {data_dir} 中未找到JSON文件")
    else:
        print(f"找到 {len(json_files)} 个JSON文件，开始批量检测...")
        print("=" * 80)
        
        all_results = []
        
        for idx, json_file in enumerate(json_files, 1):
            json_path = os.path.join(data_dir, json_file)
            print(f"\n[{idx}/{len(json_files)}] 处理文件: {json_file}")
            print("-" * 80)
            
            try:
                # 检测非稳态段
                result = detector.detect_from_json(json_path)
                
                # 打印摘要
                detector.print_detection_summary(result)
                
                # 保存检测结果到JSON
                result_dict = detector.result_to_dict(result)
                result_filename = os.path.basename(json_path).replace('.json', '_detection_result.json')
                result_path = os.path.join(output_dir, result_filename)
                with open(result_path, 'w', encoding='utf-8') as f:
                    json.dump(result_dict, f, ensure_ascii=False, indent=2)
                print(f"\n检测结果已保存到: {result_path}")
                
                # 如果启用可视化，生成可视化图片
                if visualize:
                    time_data, pv_data, sv_data, _ = detector._extract_data_from_json(json_path)
                    output_filename = os.path.basename(json_path).replace('.json', '_non_steady_detection.png')
                    output_path = os.path.join(output_dir, output_filename)
                    detector.visualize_detection_result(result, time_data, pv_data, sv_data, output_path, show=visualize)
                    print(f"可视化结果已保存到: {output_path}")
                
                # 保存到汇总列表
                all_results.append({
                    "file": json_file,
                    "scenario_type": result.scenario_type,
                    "non_steady_count": len(result.non_steady_segments),
                    "steady_state_count": len(result.steady_state_segments),
                    "setpoint_change_count": len(result.setpoint_change_segments),
                    "recovered_non_steady_count": len(result.recovered_non_steady_segments),
                    "result_file": result_filename
                })
                
            except Exception as e:
                print(f"处理文件 {json_file} 时出错: {str(e)}")
                import traceback
                traceback.print_exc()
                all_results.append({
                    "file": json_file,
                    "error": str(e)
                })
        
        # 保存汇总结果
        summary_path = os.path.join(output_dir, 'batch_detection_summary.json')
        summary = {
            "total_files": len(json_files),
            "processed_files": len([r for r in all_results if "error" not in r]),
            "failed_files": len([r for r in all_results if "error" in r]),
            "results": all_results
        }
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        
        print("\n" + "=" * 80)
        print("批量检测完成！")
        print(f"汇总结果已保存到: {summary_path}")
        print(f"成功处理: {summary['processed_files']} 个文件")
        print(f"失败: {summary['failed_files']} 个文件")