"""
振荡段检测器 (Oscillation Segment Detector) - Level 2
=====================================================

在历史数据中检测"PV 围绕 SV 持续周期性振荡"的区间。
这是三级优选中的第二优先级检测器。

检测逻辑:
1. 计算误差信号 e(t) = PV(t) - SV(t)
2. 检测过零点，统计振荡频率
3. 评估振荡质量（周期一致性、幅度持续性）
4. 要求至少 3 个完整振荡周期
"""

import numpy as np
from typing import List, Tuple, Optional


class OscillationSegmentDetector:
    """
    Level 2 振荡段检测器
    
    检测 PV 围绕 SV 持续来回振荡的区间。
    这类数据适合用临界法整定 (Ziegler-Nichols)。
    """
    
    def __init__(self,
                 min_oscillation_cycles: int = 3,
                 min_segment_points: int = 60,
                 scan_window: int = 200,
                 scan_step: int = 50,
                 min_quality_score: float = 0.4):
        """
        Args:
            min_oscillation_cycles: 最少需要的完整振荡周期数
            min_segment_points: 振荡段的最小数据点数
            scan_window: 扫描窗口大小
            scan_step: 扫描步进
            min_quality_score: 振荡段质量评分的最低合格阈值
        """
        self.min_oscillation_cycles = min_oscillation_cycles
        self.min_segment_points = min_segment_points
        self.scan_window = scan_window
        self.scan_step = scan_step
        self.min_quality_score = min_quality_score
    
    def detect(self, pv_data: np.ndarray, 
               sv_data: np.ndarray) -> List[Tuple[int, int, float, float]]:
        """
        检测振荡段
        
        Args:
            pv_data: PV 数据数组
            sv_data: SV 数据数组
            
        Returns:
            振荡段列表，每个元素为 (start_idx, end_idx, setpoint, quality_score)
            按 quality_score 降序排列
        """
        n = len(pv_data)
        if n < self.min_segment_points:
            return []
        
        # Step 1: 用滑动窗口扫描，找到振荡候选区间
        candidates = []
        
        i = 0
        while i <= n - self.scan_window:
            window_pv = pv_data[i:i + self.scan_window]
            window_sv = sv_data[i:i + self.scan_window]
            
            # 检查 SV 是否稳定（振荡检测要求 SV 不变）
            sv_range = np.ptp(window_sv)
            if sv_range > 2.0:
                i += self.scan_step
                continue
            
            setpoint = float(np.median(window_sv))
            quality = self._evaluate_oscillation(window_pv, setpoint)
            
            if quality >= self.min_quality_score:
                # 找到候选区域，向前后扩展找到完整的振荡段
                seg_start, seg_end = self._expand_segment(
                    pv_data, sv_data, i, i + self.scan_window, setpoint
                )
                candidates.append((seg_start, seg_end, setpoint, quality))
                i = seg_end  # 跳过已检测到的区域
            else:
                i += self.scan_step
        
        if not candidates:
            return []
        
        # Step 2: 合并相邻/重叠的振荡段
        merged = self._merge_adjacent(candidates)
        
        # Step 3: 重新评估合并后的段并排序
        results = []
        for seg_start, seg_end, setpoint, _ in merged:
            seg_pv = pv_data[seg_start:seg_end]
            quality = self._evaluate_oscillation(seg_pv, setpoint)
            if quality >= self.min_quality_score:
                results.append((seg_start, seg_end, setpoint, quality))
        
        results.sort(key=lambda x: x[3], reverse=True)
        return results
    
    def _evaluate_oscillation(self, pv_data: np.ndarray, 
                               setpoint: float) -> float:
        """
        评估一段 PV 数据的振荡质量 (0~1)
        
        评估维度:
        1. 过零频率（是否有足够的振荡周期）(0.30)
        2. 振荡周期一致性（各周期长度是否接近）(0.25)
        3. 振荡幅度持续性（振幅是否稳定，非衰减）(0.25)
        4. 振荡幅度显著性（相对于噪声）(0.20)
        """
        n = len(pv_data)
        if n < self.min_segment_points:
            return 0.0
        
        # 误差信号
        error = pv_data - setpoint
        
        # 检测过零点
        zero_crossings = self._find_zero_crossings(error)
        num_crossings = len(zero_crossings)
        
        # 完整振荡周期数 = 过零次数 / 2
        num_cycles = num_crossings / 2.0
        
        # 1. 过零频率评分
        if num_cycles < self.min_oscillation_cycles:
            cycle_score = num_cycles / self.min_oscillation_cycles * 0.5  # 不够则打折
        else:
            cycle_score = min(1.0, num_cycles / (self.min_oscillation_cycles * 2))
        
        if num_cycles < 1.5:
            return 0.0  # 连 1.5 个周期都不到，直接判定不是振荡
        
        # 2. 周期一致性
        if len(zero_crossings) >= 4:
            half_periods = np.diff(zero_crossings)
            period_cv = np.std(half_periods) / (np.mean(half_periods) + 1e-8)
            consistency_score = max(0, 1 - period_cv * 2)  # CV < 0.5 → 满分
        else:
            consistency_score = 0.3
        
        # 3. 振荡幅度持续性（非衰减）
        if len(zero_crossings) >= 4:
            # 计算每半周期的峰值
            amplitudes = []
            for j in range(len(zero_crossings) - 1):
                seg = error[zero_crossings[j]:zero_crossings[j + 1]]
                if len(seg) > 0:
                    amplitudes.append(np.max(np.abs(seg)))
            
            if len(amplitudes) >= 3:
                # 如果幅度衰减超过 50%，减分
                first_half = np.mean(amplitudes[:len(amplitudes) // 2])
                second_half = np.mean(amplitudes[len(amplitudes) // 2:])
                
                if first_half > 0.01:
                    decay_ratio = second_half / first_half
                    persistence_score = min(1.0, decay_ratio)
                else:
                    persistence_score = 0.3
            else:
                persistence_score = 0.3
        else:
            persistence_score = 0.0
        
        # 4. 振荡幅度显著性
        amplitude = np.std(error)
        pv_noise_baseline = self._estimate_noise(pv_data)
        
        if pv_noise_baseline > 0.01:
            snr = amplitude / pv_noise_baseline
            if snr < 1.5:
                return 0.0  # 纯噪声引起的过零，非宏观振荡
            significance_score = min(1.0, snr / 4.0)
        else:
            significance_score = 1.0 if amplitude > 0.5 else 0.3
        
        # 综合加权评分
        quality = (
            cycle_score * 0.30 +
            consistency_score * 0.25 +
            persistence_score * 0.25 +
            significance_score * 0.20
        )
        
        return quality
    
    def _find_zero_crossings(self, error: np.ndarray) -> List[int]:
        """
        检测误差信号的过零点
        """
        crossings = []
        for i in range(1, len(error)):
            if error[i - 1] * error[i] < 0:
                crossings.append(i)
            elif error[i] == 0 and i > 0 and error[i - 1] != 0:
                crossings.append(i)
        return crossings
    
    def _estimate_noise(self, pv_data: np.ndarray) -> float:
        """
        估计 PV 的背景噪声水平（用高频差分法）
        """
        if len(pv_data) < 10:
            return 0.0
        diff = np.diff(pv_data)
        # 高频噪声估计: std(diff) / sqrt(2)
        return np.std(diff) / np.sqrt(2)
    
    def _expand_segment(self, pv_data: np.ndarray, sv_data: np.ndarray,
                        start: int, end: int, setpoint: float) -> Tuple[int, int]:
        """
        从种子区间向前后扩展，找到完整的振荡段边界
        """
        n = len(pv_data)
        check_window = self.scan_window // 2
        
        # 向前扩展
        seg_start = start
        while seg_start - check_window >= 0:
            chunk = pv_data[seg_start - check_window:seg_start]
            sv_chunk = sv_data[seg_start - check_window:seg_start]
            
            if np.ptp(sv_chunk) > 2.0:
                break
            
            quality = self._evaluate_oscillation(chunk, setpoint)
            if quality >= self.min_quality_score * 0.7:
                seg_start -= check_window
            else:
                break
        
        # 向后扩展
        seg_end = end
        while seg_end + check_window <= n:
            chunk = pv_data[seg_end:seg_end + check_window]
            sv_chunk = sv_data[seg_end:seg_end + check_window]
            
            if np.ptp(sv_chunk) > 2.0:
                break
            
            quality = self._evaluate_oscillation(chunk, setpoint)
            if quality >= self.min_quality_score * 0.7:
                seg_end += check_window
            else:
                break
        
        return seg_start, seg_end
    
    def _merge_adjacent(self, candidates: List[Tuple[int, int, float, float]]) -> List[Tuple[int, int, float, float]]:
        """
        合并相邻或重叠的振荡段
        """
        if not candidates:
            return []
        
        sorted_cands = sorted(candidates, key=lambda x: x[0])
        merged = [sorted_cands[0]]
        
        for c in sorted_cands[1:]:
            last = merged[-1]
            gap = c[0] - last[1]
            
            if gap <= self.scan_window:
                # 合并：取更宽的范围，保留较高的评分
                merged[-1] = (
                    last[0], 
                    max(last[1], c[1]),
                    last[2],
                    max(last[3], c[3])
                )
            else:
                merged.append(c)
        
        return merged
