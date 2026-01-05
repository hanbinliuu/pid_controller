import json
import numpy as np
from typing import List, Dict, Tuple, Optional, Union
from dataclasses import dataclass
from enum import Enum
import matplotlib.pyplot as plt


class SegmentType(str, Enum):
    """段类型枚举"""
    INITIAL_TRANSIENT = "initial_transient"  # 初始过渡过程（不算非稳态）
    STEADY_STATE = "steady_state"  # 稳态段
    NON_STEADY_STATE = "non_steady_state"  # 非稳态段（需要重新整定）


@dataclass
class Segment:
    """数据段信息"""
    start_idx: int  # 起始索引
    end_idx: int  # 结束索引
    start_time: float  # 起始时间（秒）
    end_time: float  # 结束时间（秒）
    segment_type: SegmentType  # 段类型
    description: str  # 描述信息


@dataclass
class DetectionResult:
    """检测结果"""
    segments: List[Segment]  # 所有段
    non_steady_segments: List[Segment]  # 非稳态段（需要重新整定的段）
    initial_transient_segments: List[Segment]  # 初始过渡段
    steady_state_segments: List[Segment]  # 稳态段
    scenario_type: str  # 场景类型：scenario_1, scenario_2, scenario_3
    metadata: Dict  # 元数据


class NonSteadyStateDetector:
    """
    PID非稳态段检测器
    #  by LiuHanBin

    用于检测PID控制数据中的非稳态段，能够区分初始过渡过程和真正的非稳态。
    """
    
    def __init__(self, 
                 steady_state_window: int = 50,
                 steady_state_threshold: float = 0.5,
                 steady_state_std_threshold: float = 0.3,
                 initial_transient_max_duration: int = 200,
                 min_non_steady_duration: int = 30):
        """
        初始化检测器
        
        Args:
            steady_state_window: 稳态判断窗口大小（数据点数量）
            steady_state_threshold: 稳态判断阈值（与设定值的偏差）
            steady_state_std_threshold: 稳态标准差阈值
            initial_transient_max_duration: 初始过渡过程最大持续时间（数据点数量）
            min_non_steady_duration: 非稳态段最小持续时间（数据点数量）
        """
        self.steady_state_window = steady_state_window
        self.steady_state_threshold = steady_state_threshold
        self.steady_state_std_threshold = steady_state_std_threshold
        self.initial_transient_max_duration = initial_transient_max_duration
        self.min_non_steady_duration = min_non_steady_duration
    
    def is_steady_state(self, pv_data: np.ndarray, setpoint: float, 
                       start_idx: int, end_idx: int) -> bool:
        """
        判断指定区间是否为稳态
        
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
        
        # 检查均值是否接近设定值
        mean_pv = np.mean(segment_pv)
        if abs(mean_pv - setpoint) > self.steady_state_threshold:
            return False
        
        # 检查波动是否足够小
        deviations = np.abs(segment_pv - setpoint)
        std_dev = np.std(deviations)
        if std_dev > self.steady_state_std_threshold:
            return False
        
        # 检查大部分点是否在阈值范围内（允许少量点超出，因为可能有小的振荡）
        # 至少90%的点应该在阈值范围内
        points_in_threshold = np.sum(deviations < self.steady_state_threshold * 1.5)
        if points_in_threshold < len(deviations) * 0.9:
            return False
        
        # 检查最大偏差是否在可接受范围内（允许小的超调）
        max_deviation = np.max(deviations)
        if max_deviation > self.steady_state_threshold * 2.5:
            return False
        
        return True
    
    def is_initial_transient(self, pv_data: np.ndarray, setpoint: float,
                            start_idx: int, end_idx: int) -> bool:
        """
        判断是否为初始过渡过程（初始温度到目标温度的过程，不算非稳态）
        
        初始过渡过程的特征：
        1. 从远离设定值逐渐接近设定值（有明显的收敛趋势）
        2. 持续时间有限
        3. 有明显的趋势性变化（单调或接近单调地向设定值靠近）
        4. 波动相对较小（不是参数乱调导致的非稳态）
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
            start_idx: 起始索引
            end_idx: 结束索引
            
        Returns:
            bool: 是否为初始过渡过程
        """
        if end_idx - start_idx < 10:
            return False
        
        segment_pv = pv_data[start_idx:end_idx]
        
        # 检查是否从远离设定值开始（必须明显远离）
        initial_pv = segment_pv[0]
        initial_error = abs(initial_pv - setpoint)
        if initial_error < self.steady_state_threshold * 2:  # 必须明显远离设定值
            return False
        
        # 检查是否有明显的趋势性变化（向设定值靠近）
        if len(segment_pv) > 20:
            # 计算趋势斜率
            x = np.arange(len(segment_pv))
            coeffs = np.polyfit(x, segment_pv, 1)
            slope = coeffs[0]
            
            # 如果初始值小于设定值，斜率应该为正；如果初始值大于设定值，斜率应该为负
            if initial_pv < setpoint:
                has_trend = slope > 0
            else:
                has_trend = slope < 0
            
            if not has_trend:
                return False
            
            # 检查是否真的在接近设定值（最终值应该比初始值更接近设定值）
            final_pv = segment_pv[-1]
            final_error = abs(final_pv - setpoint)
            if final_error >= initial_error:  # 如果没有更接近设定值，不是初始过渡
                return False
            
            # 检查波动是否相对较小（初始过渡过程不应该有太大的波动）
            # 如果波动太大，可能是参数乱调导致的非稳态
            segment_std = np.std(segment_pv)
            if segment_std > self.steady_state_threshold * 3:  # 波动太大，可能是非稳态
                return False
        
        # 检查持续时间是否在合理范围内
        duration = end_idx - start_idx
        if duration > self.initial_transient_max_duration:
            return False
        
        return True
    
    def detect_segments(self, pv_data: np.ndarray, setpoint: float,
                       time_data: Optional[np.ndarray] = None) -> List[Segment]:
        """
        检测数据中的所有段（初始过渡、稳态、非稳态）
        
        使用滑动窗口方法，逐步识别每个段的类型。
        优化版本：减少重复计算，提高性能。
        
        Args:
            pv_data: 过程值数组
            setpoint: 设定值
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
        
        # 使用滑动窗口标记每个点的状态
        # 使用整数映射：0=初始过渡, 1=稳态, 2=非稳态, -1=未分类
        type_map = {
            SegmentType.INITIAL_TRANSIENT: 0,
            SegmentType.STEADY_STATE: 1,
            SegmentType.NON_STEADY_STATE: 2
        }
        reverse_map = {v: k for k, v in type_map.items()}
        
        segment_labels = np.full(n, -1, dtype=int)  # -1表示未分类
        
        # 预计算误差数组，避免重复计算
        errors = np.abs(pv_data - setpoint)
        
        # 第一步：识别稳态段（优化：减少重复计算）
        # 使用滑动窗口检测稳态段
        window = self.steady_state_window
        
        # 优化：使用布尔数组标记，然后一次性转换，减少重复赋值
        for i in range(window, n + 1):
            window_start = i - window
            window_end = i
            if self.is_steady_state(pv_data, setpoint, window_start, window_end):
                # 标记窗口内的点为稳态（保持原逻辑，确保准确性）
                segment_labels[window_start:window_end] = type_map[SegmentType.STEADY_STATE]
        
        # 第二步：识别初始过渡段（优化：使用二分查找减少重复计算）
        check_end = min(self.initial_transient_max_duration, n)
        initial_transient_end = 0
        
        # 优化：先快速检查是否可能是初始过渡段
        if check_end >= 10:
            # 检查初始条件：必须从远离设定值开始
            initial_error = errors[0]
            if initial_error >= self.steady_state_threshold * 2:
                # 使用二分查找找到最长的初始过渡段
                # 这样可以减少 is_initial_transient 的调用次数
                left, right = 10, check_end
                best_end = 0
                
                while left <= right:
                    mid = (left + right) // 2
                    # 只检查未分类的部分
                    unclassified_mask = segment_labels[:mid] == -1
                    if np.any(unclassified_mask) and self.is_initial_transient(pv_data, setpoint, 0, mid):
                        best_end = mid
                        left = mid + 1
                    else:
                        right = mid - 1
                
                if best_end > 0:
                    # 标记初始过渡段（只标记未分类的点）
                    mask = segment_labels[:best_end] == -1
                    segment_labels[:best_end][mask] = type_map[SegmentType.INITIAL_TRANSIENT]
                    initial_transient_end = best_end
        
        # 第三步：检查数据开始部分是否真的是非稳态（场景3：优化逻辑）
        if initial_transient_end == 0:  # 没有识别到初始过渡段
            check_window = min(100, n)
            if check_window >= 20:
                # 优化：使用预计算的误差数组
                initial_error = errors[:check_window]
                mean_error = np.mean(initial_error)
                std_error = np.std(initial_error)
                
                # 快速判断是否可能是非稳态
                if mean_error > self.steady_state_threshold * 2 and std_error > self.steady_state_threshold:
                    initial_segment = pv_data[:check_window]
                    
                    # 优化：只在需要时计算趋势
                    is_non_steady = False
                    if len(initial_segment) > 20:
                        # 使用更高效的斜率计算
                        x = np.arange(len(initial_segment))
                        slope = np.polyfit(x, initial_segment, 1)[0]
                        initial_pv = initial_segment[0]
                        final_pv = initial_segment[-1]
                        
                        # 判断是否为非稳态
                        if (abs(slope) < 0.01 or 
                            abs(final_pv - setpoint) >= abs(initial_pv - setpoint) or
                            std_error > self.steady_state_threshold * 2):
                            is_non_steady = True
                    
                    if is_non_steady:
                        # 优化：使用向量化操作找到非稳态段的结束位置
                        # 找到第一个稳态段的位置
                        steady_indices = np.where(segment_labels == type_map[SegmentType.STEADY_STATE])[0]
                        
                        if len(steady_indices) > 0:
                            # 如果存在稳态段，非稳态段在第一个稳态段之前结束
                            non_steady_end = steady_indices[0]
                        else:
                            # 否则，向后查找收敛点
                            non_steady_end = check_window
                            # 优化：使用更大的步长减少检查次数
                            for j in range(check_window + 50, n, 20):
                                if j >= n:
                                    break
                                recent_error = errors[check_window:j]
                                if np.mean(recent_error) < self.steady_state_threshold * 1.5:
                                    non_steady_end = j
                                    break
                            else:
                                # 如果没找到收敛点，检查到数据末尾
                                if n > check_window + 50:
                                    recent_error = errors[check_window:]
                                    if np.mean(recent_error) < self.steady_state_threshold * 1.5:
                                        non_steady_end = n
                        
                        # 只标记未分类的点为非稳态
                        mask = segment_labels[:non_steady_end] == -1
                        segment_labels[:non_steady_end][mask] = type_map[SegmentType.NON_STEADY_STATE]
        
        # 第四步：剩余未分类的点标记为非稳态
        segment_labels[segment_labels == -1] = type_map[SegmentType.NON_STEADY_STATE]
        
        # 第五步：将连续的同类型段合并（优化：合并段合并和过滤为一步）
        segments = []
        current_start = 0
        current_type_val = segment_labels[0]
        current_type = reverse_map[current_type_val]
        
        for i in range(1, n):
            if segment_labels[i] != current_type_val:
                # 段类型改变，保存前一段
                seg = Segment(
                    start_idx=current_start,
                    end_idx=i,
                    start_time=time_data[current_start],
                    end_time=time_data[i-1],
                    segment_type=current_type,
                    description=self._get_segment_description(current_type)
                )
                
                # 优化：在合并时直接过滤太短的非稳态段
                if (seg.segment_type == SegmentType.NON_STEADY_STATE and 
                    seg.end_idx - seg.start_idx < self.min_non_steady_duration):
                    # 太短的非稳态段，合并到前一段
                    if segments:
                        prev_seg = segments[-1]
                        prev_seg.end_idx = seg.end_idx
                        prev_seg.end_time = seg.end_time
                    # 如果前面没有段，则合并到下一段（延迟处理）
                    # 这里先不添加，等下一段时再处理
                else:
                    segments.append(seg)
                
                current_start = i
                current_type_val = segment_labels[i]
                current_type = reverse_map[current_type_val]
        
        # 添加最后一段
        if current_start < n:
            seg = Segment(
                start_idx=current_start,
                end_idx=n,
                start_time=time_data[current_start],
                end_time=time_data[n-1],
                segment_type=current_type,
                description=self._get_segment_description(current_type)
            )
            
            # 同样处理太短的非稳态段
            if (seg.segment_type == SegmentType.NON_STEADY_STATE and 
                seg.end_idx - seg.start_idx < self.min_non_steady_duration):
                if segments:
                    prev_seg = segments[-1]
                    prev_seg.end_idx = seg.end_idx
                    prev_seg.end_time = seg.end_time
                else:
                    # 如果这是唯一一段且太短，仍然保留
                    segments.append(seg)
            else:
                segments.append(seg)
        
        # 处理延迟合并的情况：检查最后一段是否需要合并到前一段
        if len(segments) >= 2:
            last_seg = segments[-1]
            if (last_seg.segment_type == SegmentType.NON_STEADY_STATE and
                last_seg.end_idx - last_seg.start_idx < self.min_non_steady_duration):
                prev_seg = segments[-2]
                prev_seg.end_idx = last_seg.end_idx
                prev_seg.end_time = last_seg.end_time
                segments.pop()
        
        return segments
    
    def _get_segment_description(self, segment_type: SegmentType) -> str:
        """获取段的描述信息"""
        descriptions = {
            SegmentType.INITIAL_TRANSIENT: "初始过渡过程（不算非稳态）",
            SegmentType.STEADY_STATE: "稳态段",
            SegmentType.NON_STEADY_STATE: "非稳态段（需要重新整定PID参数）"
        }
        return descriptions.get(segment_type, "未知类型")
    
    def identify_scenario(self, segments: List[Segment]) -> str:
        """
        识别场景类型
        
        Args:
            segments: 段列表
            
        Returns:
            str: 场景类型（scenario_1, scenario_2, scenario_3）
        """
        if not segments:
            return "unknown"
        
        # 检查第一个段
        first_segment = segments[0]
        
        # 场景3：一开始就是非稳态
        if first_segment.segment_type == SegmentType.NON_STEADY_STATE:
            return "scenario_3"
        
        # 场景1和场景2：需要检查是否有稳态段，然后出现非稳态段
        has_steady_state = any(seg.segment_type == SegmentType.STEADY_STATE for seg in segments)
        has_non_steady_after_steady = False
        
        found_steady = False
        for seg in segments:
            if seg.segment_type == SegmentType.STEADY_STATE:
                found_steady = True
            elif found_steady and seg.segment_type == SegmentType.NON_STEADY_STATE:
                has_non_steady_after_steady = True
                break
        
        if has_steady_state and has_non_steady_after_steady:
            # 场景1：初始过渡 -> 稳态 -> 非稳态
            if first_segment.segment_type == SegmentType.INITIAL_TRANSIENT:
                return "scenario_1"
            # 场景2：稳态 -> 非稳态
            else:
                return "scenario_2"
        
        return "unknown"
    
    def detect_from_json(self, data_list: Union[str, Dict]) -> DetectionResult:
        """
        从JSON数据中检测非稳态段
        
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
        sv_data = []
        
        for item in data_list:
            timestamp = item.get("timestamp", 0)
            pv = item.get("pv", 0)
            sv = item.get("sv", 0)
            
            timestamps.append(timestamp / 1000.0)  # 转换为秒
            pv_data.append(pv)
            sv_data.append(sv)
        
        # 转换为numpy数组
        time_data = np.array(timestamps)
        pv_data = np.array(pv_data)
        sv_data = np.array(sv_data)
        
        # 转换为相对时间（从0开始）
        if len(time_data) > 0:
            time_data = time_data - time_data[0]
        
        # 获取设定值（通常设定值是固定的，取第一个值）
        setpoint = sv_data[0] if len(sv_data) > 0 else np.mean(sv_data)
        
        # 检测段
        segments = self.detect_segments(pv_data, setpoint, time_data)
        
        # 分类段
        non_steady_segments = [seg for seg in segments if seg.segment_type == SegmentType.NON_STEADY_STATE]
        initial_transient_segments = [seg for seg in segments if seg.segment_type == SegmentType.INITIAL_TRANSIENT]
        steady_state_segments = [seg for seg in segments if seg.segment_type == SegmentType.STEADY_STATE]
        
        # 识别场景类型
        scenario_type = self.identify_scenario(segments)
        
        # 构建元数据
        metadata = {
            "table": data.get("table", ""),
            "start_time": data.get("start_time", ""),
            "end_time": data.get("end_time", ""),
            "totalRecords": data.get("totalRecords", len(data_list)),
            "setpoint": setpoint
        }
        
        return DetectionResult(
            segments=segments,
            non_steady_segments=non_steady_segments,
            initial_transient_segments=initial_transient_segments,
            steady_state_segments=steady_state_segments,
            scenario_type=scenario_type,
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




if __name__=='__main__':

    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans', 'sans-serif']
    plt.rcParams['axes.unicode_minus'] = False
    
    json_path = '/Users/dingzhenying/project/pythonProject/pid-agent-mvp/data/response_1762241923959.json'
    detector = NonSteadyStateDetector()
    result = detector.detect_from_json(json_path)

    # 获取非稳态段起点
    starts = detector.get_non_steady_starts(result)
    print("=" * 60)
    print("非稳态段检测结果")
    print("=" * 60)
    print(f"场景类型: {result.scenario_type}")
    print(f"总段数: {len(result.segments)}")
    print(f"初始过渡段数: {len(result.initial_transient_segments)}")
    print(f"稳态段数: {len(result.steady_state_segments)}")
    print(f"非稳态段数: {len(result.non_steady_segments)}")
    print()
    
    if starts:
        print("非稳态段起点（需要重新整定PID参数）:")
        for i, start in enumerate(starts, 1):
            print(f"  起点 {i}: 索引={start['start_idx']}, 时间={start['start_time']:.2f}s, 持续时间={start['duration']}个数据点")
    print()
    
    # 可视化
    # 重新加载数据用于可视化
    with open(json_path, 'r', encoding='utf-8') as f:
        json_data = json.load(f)
    
    data_list = json_data["data"]
    timestamps = []
    pv_data = []
    sv_data = []
    
    for item in data_list:
        timestamp = item.get("timestamp", 0)
        pv = item.get("pv", 0)
        sv = item.get("sv", 0)
        
        timestamps.append(timestamp / 1000.0)
        pv_data.append(pv)
        sv_data.append(sv)
    
    time_data = np.array(timestamps)
    pv_data = np.array(pv_data)
    sv_data = np.array(sv_data)
    
    if len(time_data) > 0:
        time_data = time_data - time_data[0]
    
    setpoint = sv_data[0] if len(sv_data) > 0 else np.mean(sv_data)
    
    # 绘制图表
    fig, ax = plt.subplots(1, 1, figsize=(16, 8))
    
    # 绘制过程值
    ax.plot(time_data, pv_data, 'b-', linewidth=1.5, alpha=0.7, label='过程值 (PV)')
    
    # 绘制设定值
    if len(np.unique(sv_data)) == 1:
        ax.axhline(y=sv_data[0], color='r', linestyle='--', linewidth=2, label='设定值 (SV)')
    else:
        ax.plot(time_data, sv_data, 'r--', linewidth=2, alpha=0.8, label='设定值 (SV)')
    
    colors = {
        SegmentType.INITIAL_TRANSIENT: 'green',
        SegmentType.STEADY_STATE: 'blue',
        SegmentType.NON_STEADY_STATE: 'red'
    }
    
    # 用于跟踪已添加的标签
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
    
    # 特别标记非稳态段起点
    for i, seg in enumerate(result.non_steady_segments, 1):
        start_time = time_data[seg.start_idx]
        start_pv = pv_data[seg.start_idx]
        
        ax.plot(start_time, start_pv, 'ro', markersize=15, zorder=10, 
                markeredgecolor='darkred', markeredgewidth=2, label='非稳态起点' if i == 1 else "")
        
        ax.annotate(f'起点 {i}\n索引: {seg.start_idx}\n时间: {start_time:.1f}s', 
                   xy=(start_time, start_pv),
                   xytext=(20, 30), textcoords='offset points',
                   bbox=dict(boxstyle='round,pad=0.8', fc='yellow', alpha=0.9, edgecolor='red', linewidth=2),
                   arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.2', 
                                 color='red', lw=2),
                   fontsize=10, fontweight='bold',
                   ha='left')
    
    ax.set_xlabel('时间 (秒)', fontsize=12, fontweight='bold')
    ax.set_ylabel('过程值 (PV)', fontsize=12, fontweight='bold')
    title = f'非稳态段检测结果\n'
    title += f"场景类型: {result.scenario_type} | "
    title += f"非稳态段数: {len(result.non_steady_segments)} | "
    title += f"设定值: {setpoint:.2f}"
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(loc='best', fontsize=10)
    ax.grid(True, alpha=0.3, linestyle='--')
    
    plt.tight_layout()
    
    output_path = json_path.replace('.json', '_non_steady_detection.png')
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"可视化结果已保存到: {output_path}")
    
    plt.show()