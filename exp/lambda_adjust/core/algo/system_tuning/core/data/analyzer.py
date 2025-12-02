"""数据分析模块：负责数据分析和非稳态检测"""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from config import Config
from core.model.stability import StabilityDetector


class DataAnalyzer:
    """数据分析和非稳态检测工具：负责case分类、稳态检测、扰动检测等"""
    
    def __init__(self, tol=0.5, std_tol=0.2, min_len=10):
        """
        初始化数据分析器
        
        Args:
            tol: 容差（PV与设定值的允许偏差）
            std_tol: 标准差阈值
            min_len: 最小数据长度
        """
        self._stability_detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=min_len)
    
    def classify_case(self, temp_data, setpoint, tol=1.0, std_tol=0.5, min_len=10, sv_array=None):
        """
        判断JSON数据属于哪种情形（重构版，针对不启用分段整定时的严格检测）
        
        分类结果：
        - CASE_1: 冷启动，没有历史数据，一开始设定的pid值就是有问题的，所以一开始就是非稳态（需要整定）
        - CASE_2: 目标温度（sv）会手动调整（上升或者下降），但调整时候的变化不属于非稳态（需要检查是否最终稳态）
        - CASE_3: 旧的pid参数作用下是稳态的，但是后面会出现非稳态（需要整定）
        - ALREADY_STABLE: 全程稳态（无需整定）
        - UNKNOWN: 无法判断
        
        重构优化点（针对不启用分段整定）：
        1. 使用更严格的稳态检测阈值（tol=0.5, std_tol=0.3）
        2. 增加绝对振荡幅度检测（>2.0即为非稳态）
        3. 增加相对振荡幅度检测（>15%设定值即为非稳态）
        4. 增加标准差检测（>0.8即为非稳态）
        5. 多重检测机制，任一条件满足即判定为非稳态
        """
        n = len(temp_data)
        if n < 30:  # 数据太少，无法判断
            return "UNKNOWN"

        temp_data = np.array(temp_data)
        
        # ===== 重构：针对不启用分段整定的严格检测 =====
        # 使用更严格的阈值进行初步检测
        strict_tol = 0.5  # 从1.0降到0.5
        strict_std_tol = 0.3  # 从0.5降到0.3
        
        # 特征1：数据质量评估（优先检查）
        data_range = np.max(temp_data) - np.min(temp_data)
        data_std = np.std(temp_data)
        data_mean = np.mean(temp_data)
        
        # 新增：绝对振荡检测（核心优化）
        # 如果数据波动范围超过2.0，直接判定为非稳态
        if data_range > 2.0:
            print(f"⚠️  检测到大幅振荡: range={data_range:.2f} > 2.0")
            # 进一步判断是CASE_1还是CASE_3
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"  # 冷启动
            else:
                return "CASE_3"  # 后期扰动
        
        # 新增：相对振荡检测
        # 如果数据波动范围超过设定值的15%，判定为非稳态
        if setpoint > 0 and data_range > abs(setpoint) * 0.15:
            print(f"⚠️  检测到相对振荡: range={data_range:.2f} > {abs(setpoint) * 0.15:.2f} (15%SV)")
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"
            else:
                return "CASE_3"
        
        # 新增：标准差检测
        # 如果标准差超过0.8，判定为非稳态
        if data_std > 0.8:
            print(f"⚠️  检测到高标准差: std={data_std:.2f} > 0.8")
            initial_dev = abs(temp_data[0] - setpoint)
            if initial_dev > strict_tol * 3:
                return "CASE_1"
            else:
                return "CASE_3"
        
        # 新增：平均偏差检测
        # 如果平均值偏离设定值超过1.5，判定为非稳态
        mean_dev = abs(data_mean - setpoint)
        if mean_dev > 1.5:
            print(f"⚠️  检测到平均偏差: mean_dev={mean_dev:.2f} > 1.5")
            return "CASE_1"  # 持续偏离，通常是冷启动或参数不当
        
        # 如果数据变化太小，可能是噪声或无效数据
        has_dynamic = data_range > strict_tol * 2
        if not has_dynamic:
            return "UNKNOWN"
        
        # 特征2：前段是否稳态（前50点或1/3数据，但至少20点）
        # 使用严格阈值检测
        head_len = max(20, min(50, n // 3))
        head_steady = self.is_steady_state(temp_data[:head_len], setpoint, strict_tol, strict_std_tol, min_len)

        # 特征3：尾段是否稳态（最后30点或1/4数据，但至少20点）
        # 使用严格阈值检测
        tail_len = max(20, min(30, n // 4))
        tail_steady = self.is_steady_state(temp_data[-tail_len:], setpoint, strict_tol, strict_std_tol, min_len)

        # 特征4：初始点是否远离设定点（使用相对偏差）
        initial_dev = abs(temp_data[0] - setpoint)
        initial_dev_ratio = initial_dev / max(strict_tol, 0.1)  # 相对于严格容差的倍数
        is_cold_start = initial_dev_ratio > 3.0  # 初始偏差超过3倍容差

        # 特征5：是否存在中间扰动（先稳后乱）
        has_disturbance = False
        if head_steady:
            # 使用改进的扰动检测，使用严格阈值
            disturbance_start = self.find_disturbance_start(temp_data, setpoint, head_len, threshold=strict_tol * 2)
            has_disturbance = disturbance_start is not None

        # 特征6：检查是否有明显的非稳态段（使用严格阈值）
        non_steady_segments = self._detect_non_steady_segments(temp_data, setpoint, strict_tol, strict_std_tol, sv_array=sv_array)
        has_significant_non_steady = len(non_steady_segments) > 0
        
        # 特征7：检查中间段是否有振荡（加强版）
        # 即使前段和尾段都是稳态，如果中间有明显振荡，也不应该认为是全程稳态
        has_middle_oscillation = False
        if n > 60:  # 降低检测门槛，从100降到60
            # 检查中间段（排除前段和尾段）
            middle_start = head_len
            middle_end = n - tail_len
            if middle_end > middle_start + 30:  # 中间段至少有30个点（从50降到30）
                middle_segment = temp_data[middle_start:middle_end]
                # 检查中间段是否有大幅振荡（使用严格阈值）
                middle_range = np.max(middle_segment) - np.min(middle_segment)
                middle_std = np.std(middle_segment)
                # 加强检测：降低阈值
                if middle_range > strict_tol * 2.0 or middle_std > strict_std_tol * 1.0:  # 从2.5/1.2降到2.0/1.0
                    has_middle_oscillation = True
                    print(f"⚠️  中间段振荡: range={middle_range:.2f}, std={middle_std:.2f}")
                # 绝对振荡幅度检测（降低阈值）
                elif middle_range > 1.5:  # 从2.0降到1.5
                    has_middle_oscillation = True
                    print(f"⚠️  中间段绝对振荡: range={middle_range:.2f} > 1.5")
                # 或者使用is_steady_state检查中间段（使用严格阈值）
                elif not self.is_steady_state(middle_segment, setpoint, strict_tol, strict_std_tol, min_len=15):
                    has_middle_oscillation = True
                    print(f"⚠️  中间段非稳态")

        # 检查是否有设定值变化（用于区分CASE_2）
        has_setpoint_change = False
        if sv_array is not None and len(sv_array) == len(temp_data):
            sv_segments = self.detect_setpoint_changes(sv_array, min_change=0.5, min_stable_points=20)
            has_setpoint_change = len(sv_segments) > 1
        
        # 分类逻辑（优化版，明确区分三种情况）
        # 1. 全程稳态 - 最简单的情况（但必须确保中间没有振荡）
        if head_steady and tail_steady and not has_disturbance and not has_significant_non_steady and not has_middle_oscillation:
            return "ALREADY_STABLE"
        
        # 2. CASE_2: 目标温度（sv）会手动调整，但调整时候的变化不属于非稳态
        # 判断条件：有设定值变化，且前段稳态
        if has_setpoint_change and head_steady:
            # 检查设定值变化后是否最终稳态
            # 如果最终稳态，可能不需要整定（但需要进一步检查）
            return "CASE_2"
        
        # 3. CASE_3: 旧的pid参数作用下是稳态的，但是后面会出现非稳态
        # 判断条件：前段稳态，但后面出现非稳态（不是设定值变化引起的）
        if head_steady and (has_disturbance or has_middle_oscillation or has_significant_non_steady) and not has_setpoint_change:
            return "CASE_3"
        
        # 4. CASE_1: 冷启动，没有历史数据，一开始设定的pid值就是有问题的
        # 判断条件：初始远离设定点且未达到稳态，或者前段非稳态
        if is_cold_start and not tail_steady:
            return "CASE_1"
        
        # 5. 前段非稳态但有明显非稳态段 - 按CASE_1处理
        if not head_steady and has_significant_non_steady:
            return "CASE_1"
        
        # 6. 前段非稳态但尾段稳态 - 可能是数据质量问题，按CASE_1处理（全程非稳态）
        if not head_steady and tail_steady:
            # 这种情况理论上不应该存在（完整升温+稳态），但实际数据可能有
            # 按CASE_1处理，使用整段数据进行整定
            return "CASE_1"
        
        # 7. 其他模糊情况 - 如果有非稳态段或中间振荡，按CASE_3处理；否则按CASE_1处理
        if has_significant_non_steady or has_middle_oscillation:
            return "CASE_3"
        else:
            # 默认按CASE_1处理（全程非稳态）
            return "CASE_1"

    def is_steady_state(self, temps, setpoint, tol=1.0, std_tol=0.5, min_len=10, for_level=False):
        """
        判断一段数据是否处于稳态
        
        直接调用 StabilityDetector 的方法
        
        Args:
            temps: 数据数组
            setpoint: 设定值
            tol: 容差（默认1.0，放宽以适应OPC UA实时数据）
            std_tol: 标准差阈值（默认0.5，放宽以适应OPC UA实时数据）
            min_len: 最小数据长度
            for_level: 是否为液位控制（使用更宽松的判断）
        """
        # 更新检测器的参数（如果与默认值不同）
        if self._stability_detector.tol != tol or self._stability_detector.std_tol != std_tol or self._stability_detector.min_len != min_len:
            self._stability_detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=min_len)
        
        # 直接调用 StabilityDetector 的方法
        return self._stability_detector.is_steady_state(temps, setpoint, for_level=for_level)

    def find_first_steady_entry(self, temp_data, setpoint, window=50, tol=1.0, std_tol=0.5):
        """
        找到首次进入稳态的时间点（优化版）
        
        使用滑动窗口检测，要求连续多个窗口都是稳态才认为进入稳态
        """
        n = len(temp_data)
        if n < window * 2:
            return None
        
        # 使用滑动窗口，要求连续3个窗口都是稳态
        steady_windows = 0
        required_steady_windows = 3
        
        for i in range(window, n):
            window_data = temp_data[i - window + 1:i + 1]
            if self.is_steady_state(window_data, setpoint, tol, std_tol, min_len=window//2):
                steady_windows += 1
                if steady_windows >= required_steady_windows:
                    # 返回第一个稳态窗口的起始位置
                    return i - window * required_steady_windows + 1
            else:
                steady_windows = 0  # 重置计数
        
        return None
    
    def _detect_non_steady_segments(self, temp_data, setpoint, tol=1.0, std_tol=0.5, min_segment_len=10, sv_array=None):
        """
        检测数据中的非稳态段（辅助方法）
        
        直接调用 StabilityDetector 的方法
        
        Returns:
            List[Tuple[int, int, float]]: 非稳态段的起始、结束索引和设定值列表
        """
        # 更新检测器的参数（如果与默认值不同）
        if self._stability_detector.tol != tol or self._stability_detector.std_tol != std_tol or self._stability_detector.min_len != min_segment_len:
            self._stability_detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=min_segment_len)
        
        # 如果没有提供 sv_array，创建一个与 temp_data 长度相同的数组，值都为 setpoint
        if sv_array is None:
            sv_array = np.full_like(temp_data, setpoint)
        
        # 直接调用 StabilityDetector 的方法
        non_steady_segments = self._stability_detector.detect_non_steady_segments(
            temp_data, sv_array, min_segment_len=min_segment_len
        )
        
        # 为了保持向后兼容，如果调用者期望的是 (start_idx, end_idx) 格式，可以转换
        # 但这里保持 (start_idx, end_idx, setpoint) 格式，因为这是更完整的信息
        return non_steady_segments

    def find_disturbance_start(self, temp_data, setpoint, steady_head_len, threshold=1.0):
        """
        定位扰动起始点
        
        直接调用 StabilityDetector 的方法
        
        Args:
            temp_data: 温度数据
            setpoint: 设定值
            steady_head_len: 稳态段长度
            threshold: 偏差阈值
            
        Returns:
            扰动起始点索引，如果未找到返回None
        """
        # 直接调用 StabilityDetector 的方法
        return self._stability_detector.find_disturbance_start(
            temp_data, setpoint, steady_head_len, threshold=threshold
        )

    def detect_setpoint_changes(self, sv_array, min_change=0.5, min_stable_points=20):
        """
        检测设定值变化点
        
        直接调用 StabilityDetector 的方法
        
        Args:
            sv_array: 设定值数组
            min_change: 设定值变化的最小阈值（超过此值才认为是变化）
            min_stable_points: 每个设定值段的最小稳定点数
            
        Returns:
            list: 设定值变化点索引列表，每个元素为 (start_idx, end_idx, setpoint_value)
            例如: [(0, 100, 3.0), (100, 200, 5.0)] 表示：
            - 0-100点：设定值为3.0
            - 100-200点：设定值为5.0
        """
        # 直接调用 StabilityDetector 的方法
        return self._stability_detector.detect_setpoint_segments(
            sv_array, min_change=min_change, min_stable_points=min_stable_points
        )

    def is_setpoint_changing(self, sv_array, start_idx, end_idx, threshold=0.1):
        """
        检测指定区间内设定值是否正在变化
        
        直接调用 StabilityDetector 的方法
        
        用于在非稳态检测时排除设定值变化期间的数据。
        当目标温度从低调到高或从高调到低的过程，都不应该算非稳态。
        
        Args:
            sv_array: 设定值数组
            start_idx: 起始索引
            end_idx: 结束索引
            threshold: 变化阈值（设定值变化超过此值认为在变化）
            
        Returns:
            bool: 如果设定值正在变化返回True，否则返回False
        """
        # 直接调用 StabilityDetector 的方法
        return self._stability_detector.is_setpoint_changing(
            sv_array, start_idx, end_idx, threshold=threshold
        )

    def extract_tuning_segment(self, case, t, temp_data, setpoint, u_data=None, 
                               sv_array=None, segment_indices=None):
        """
        根据情形提取有效整定段
        
        Args:
            case: 数据情形
            t: 时间数组
            temp_data: 温度/输出数据
            setpoint: 设定值（如果segment_indices提供，此参数可能被忽略）
            u_data: 输入数据（可选）
            sv_array: 设定值数组（可选，用于设定值变化场景）
            segment_indices: 分段索引 (start_idx, end_idx)（可选，如果提供则直接使用）
        """
        # 如果提供了分段索引，直接使用（用于设定值变化场景）
        if segment_indices is not None:
            start_idx, end_idx = segment_indices
            if u_data is not None:
                return t[start_idx:end_idx], temp_data[start_idx:end_idx], u_data[start_idx:end_idx]
            return t[start_idx:end_idx], temp_data[start_idx:end_idx], None
        
        # 原有逻辑
        if case == "CASE_1":
            # 全程非稳态，但需要检查尾部是否已经稳定
            # 如果尾部已经稳定在设定值附近，说明响应正常，不需要整定
            if len(temp_data) >= 50:
                tail_len = max(30, len(temp_data) // 4)
                tail_segment = temp_data[-tail_len:]
                tail_pv_mean = np.mean(tail_segment)
                tail_error = abs(tail_pv_mean - setpoint)
                
                # 检查尾部是否稳态
                is_tail_steady = self.is_steady_state(tail_segment, setpoint, tol=0.5, std_tol=0.2, min_len=20)
                
                if is_tail_steady or tail_error < 0.5:
                    # 尾部已稳定，返回None表示无需整定
                    return None, None, None
            
            # 尾部未稳定，使用整段作为整定段
            if u_data is not None:
                return t, temp_data, u_data
            return t, temp_data, None
        elif case == "CASE_2":
            # 扰动后恢复段
            head_len = min(50, len(temp_data) // 3)
            start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
            if start_idx is not None:
                if u_data is not None:
                    return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                return t[start_idx:], temp_data[start_idx:], None
            else:
                # 如果没找到扰动点，可能数据有问题，返回后半段
                mid = len(t) // 2
                if u_data is not None:
                    return t[mid:], temp_data[mid:], u_data[mid:]
                return t[mid:], temp_data[mid:], None
        elif case in ["CASE_3", "CASE_3_FALLBACK"]:
            # CASE_3: 旧的pid参数作用下是稳态的，但是后面会出现非稳态
            # 需要找到非稳态开始的位置（从稳态到非稳态的转折点）
            # 策略：先找到稳态段，然后找到稳态段结束后非稳态开始的位置
            
            # 1. 找到前段稳态的长度
            head_len = max(50, len(temp_data) // 3)
            head_len = min(head_len, len(temp_data) - 50)  # 确保后面还有足够的数据
            
            # 检查前段是否稳态
            head_steady = self.is_steady_state(temp_data[:head_len], setpoint, tol=0.5, std_tol=0.2, min_len=20)
            
            if head_steady:
                # 前段稳态，找到非稳态开始的位置
                # 使用find_disturbance_start方法，但需要从稳态段之后开始查找
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len, threshold=0.5)
                
                if start_idx is not None:
                    # 找到了非稳态开始位置，从该位置开始提取整定段
                    if u_data is not None:
                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                    return t[start_idx:], temp_data[start_idx:], None
                else:
                    # 如果没找到明确的扰动点，使用滑动窗口检测非稳态开始
                    # 从head_len开始向后扫描，找到第一个非稳态窗口
                    window_size = min(30, len(temp_data) // 10)
                    for i in range(head_len, len(temp_data) - window_size, window_size // 2):
                        window_data = temp_data[i:i+window_size]
                        if not self.is_steady_state(window_data, setpoint, tol=0.5, std_tol=0.2, min_len=10):
                            # 找到非稳态开始位置
                            start_idx = i
                            if u_data is not None:
                                return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                            return t[start_idx:], temp_data[start_idx:], None
                    
                    # 如果一直没找到，返回后半段
                    mid = len(t) // 2
                    if u_data is not None:
                        return t[mid:], temp_data[mid:], u_data[mid:]
                    return t[mid:], temp_data[mid:], None
            else:
                # 前段不稳态，可能判断有误，按CASE_2处理
                head_len = min(50, len(temp_data) // 3)
                start_idx = self.find_disturbance_start(temp_data, setpoint, head_len)
                if start_idx is not None:
                    if u_data is not None:
                        return t[start_idx:], temp_data[start_idx:], u_data[start_idx:]
                    return t[start_idx:], temp_data[start_idx:], None
                else:
                    # 如果都找不到，返回后半段
                    mid = len(t) // 2
                    if u_data is not None:
                        return t[mid:], temp_data[mid:], u_data[mid:]
                    return t[mid:], temp_data[mid:], None
        else:
            # UNKNOWN 或 ALREADY_STABLE，返回 None
            return None, None, None

