"""
系统整定核心逻辑模块
按照三种CASE清晰处理非稳态检测和整定判断
"""
import numpy as np
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
from core.data.analyzer import DataAnalyzer


class SystemTuningLogic:
    """系统整定核心逻辑：处理三种CASE的非稳态检测和整定判断"""
    
    def __init__(self):
        self._analyzer = DataAnalyzer()
    
    def detect_case_type(self, temp_data, setpoint, sv_array=None):
        """
        检测数据属于哪种CASE
        
        Returns:
            case_type: 'CASE_1', 'CASE_2', 'CASE_3', 'ALREADY_STABLE'
            case_info: 包含case相关信息的字典
        """
        # 使用DataAnalyzer的classify_case方法
        case = self._analyzer.classify_case(temp_data, setpoint, sv_array=sv_array)
        
        case_info = {
            'case': case,
            'non_steady_segments': []  # 用于存储非稳态段
        }
        
        return case, case_info
    
    def check_segment_steady_state(self, temp_data, sv_array, segments):
        """
        检查每个段的稳态情况，并判断是否需要整定
        
        Args:
            temp_data: PV数据
            sv_array: SV数据
            segments: 分段列表 [(start_idx, end_idx, setpoint), ...]
            
        Returns:
            tuning_needed: 是否需要整定
            first_tuning_segment_idx: 第一个需要整定的段索引
            non_steady_segments: 所有非稳态段列表（用于标注）
        """
        non_steady_segments = []
        first_tuning_segment_idx = None
        
        for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(segments):
            y_seg = temp_data[start_idx:end_idx]
            segment_len = len(y_seg)
            
            if segment_len < 20:
                continue
            
            # 检查该段内设定值是否在变化（CASE_2的特殊处理）
            if sv_array is not None and len(sv_array) == len(temp_data):
                sv_seg = sv_array[start_idx:end_idx]
                is_sv_changing = self._analyzer.is_setpoint_changing(
                    sv_seg, 0, len(sv_seg), threshold=0.1
                )
                
                if is_sv_changing:
                    # CASE_2: SV正在变化，这是正常的过渡过程
                    # 检查变化后是否最终稳态
                    if self._check_final_steady_after_sv_change(y_seg, sv_seg, seg_setpoint):
                        print(f"   ✅ 段 {seg_idx + 1}: SV调整后最终已稳态，无需整定")
                        continue
                    else:
                        # SV变化后未稳态，需要整定
                        print(f"   ❌ 段 {seg_idx + 1}: SV调整后未稳态，需要整定")
                        non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                        if first_tuning_segment_idx is None:
                            first_tuning_segment_idx = seg_idx
                        continue
            
            # 检查该段是否稳态
            tail_len = max(30, int(segment_len * 0.3)) if segment_len >= 50 else min(20, segment_len)
            tail_segment = y_seg[-tail_len:] if segment_len >= tail_len else y_seg
            
            is_steady = self._analyzer.is_steady_state(
                tail_segment, seg_setpoint, tol=1.0, std_tol=0.5, min_len=20
            )
            
            if not is_steady:
                # 检查是否有振荡
                has_oscillation = self._check_oscillation(y_seg, seg_setpoint)
                
                if has_oscillation:
                    print(f"   ❌ 段 {seg_idx + 1}: 存在振荡，需要整定")
                    non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                    if first_tuning_segment_idx is None:
                        first_tuning_segment_idx = seg_idx
                else:
                    # 检查是否是正常的响应过程
                    initial_error = abs(y_seg[0] - seg_setpoint)
                    final_error = abs(np.mean(tail_segment) - seg_setpoint)
                    
                    if final_error < 1.0 or (initial_error > final_error and final_error < initial_error * 0.5):
                        print(f"   ✅ 段 {seg_idx + 1}: 响应正常，视为稳态")
                    else:
                        print(f"   ❌ 段 {seg_idx + 1}: 未达到设定值，需要整定")
                        non_steady_segments.append((start_idx, end_idx, seg_setpoint))
                        if first_tuning_segment_idx is None:
                            first_tuning_segment_idx = seg_idx
            else:
                print(f"   ✅ 段 {seg_idx + 1}: 已稳态")
        
        tuning_needed = first_tuning_segment_idx is not None
        
        # 记录所有稳态段的索引（用于后续跳过整定）
        # 稳态段包括：初始检查时已稳态的段，以及SV调整后最终已稳态的段
        # 创建非稳态段的索引集合（用于快速查找）
        non_steady_segment_indices = set()
        for seg_start, seg_end, _ in non_steady_segments:
            # 找到对应的段索引
            for seg_idx, (start_idx, end_idx, _) in enumerate(segments):
                if start_idx == seg_start and end_idx == seg_end:
                    non_steady_segment_indices.add(seg_idx)
                    break
        
        steady_segment_indices = set()
        for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(segments):
            # 跳过非稳态段和第一个需要整定的段
            if seg_idx in non_steady_segment_indices or seg_idx == first_tuning_segment_idx:
                continue
            
            # 检查该段是否在初始检查时是稳态的
            y_seg = temp_data[start_idx:end_idx]
            segment_len = len(y_seg)
            if segment_len >= 20:
                tail_len = max(30, int(segment_len * 0.3)) if segment_len >= 50 else min(20, segment_len)
                tail_segment = y_seg[-tail_len:] if segment_len >= tail_len else y_seg
                is_steady = self._analyzer.is_steady_state(
                    tail_segment, seg_setpoint, tol=1.0, std_tol=0.5, min_len=20
                )
                if is_steady:
                    steady_segment_indices.add(seg_idx)
        
        return tuning_needed, first_tuning_segment_idx, non_steady_segments, steady_segment_indices
    
    def _check_final_steady_after_sv_change(self, y_seg, sv_seg, seg_setpoint):
        """
        检查SV变化后是否最终稳态（CASE_2的特殊判断）
        
        逻辑：如果SV调整前后最终是稳态，不需要整定
        例如：稳态->非稳态->稳态，不需要整定
        """
        # 找到SV稳定后的部分
        stable_window = min(30, len(sv_seg) // 3)
        stable_part_start = None
        
        # 从后往前找SV稳定的部分
        for i in range(len(sv_seg) - stable_window, stable_window, -stable_window):
            if i < 0:
                break
            sv_stable_part = sv_seg[i:]
            if not self._analyzer.is_setpoint_changing(sv_stable_part, 0, len(sv_stable_part), threshold=0.1):
                stable_part_start = i
                stable_sv = np.median(sv_stable_part)
                break
        
        if stable_part_start is not None and stable_part_start < len(sv_seg) - 10:
            # 检查稳定部分的PV是否已经稳定在新设定值附近
            stable_pv_part = y_seg[stable_part_start:]
            if len(stable_pv_part) >= 20:
                is_stable = self._analyzer.is_steady_state(
                    stable_pv_part, stable_sv, tol=1.0, std_tol=0.5, min_len=20
                )
                return is_stable
        
        return False
    
    def _check_oscillation(self, y_seg, setpoint):
        """检查数据是否有振荡"""
        if len(y_seg) < 10:
            return False
        
        # 检查数据范围
        data_range = np.max(y_seg) - np.min(y_seg)
        if data_range > 2.0 or data_range > abs(setpoint) * 0.3:
            return True
        
        # 检查尾部数据范围
        tail_len = min(30, len(y_seg) // 3)
        if tail_len >= 10:
            tail_seg = y_seg[-tail_len:]
            tail_range = np.max(tail_seg) - np.min(tail_seg)
            if tail_range > 2.0 or tail_range > abs(setpoint) * 0.3:
                return True
        
        return False

