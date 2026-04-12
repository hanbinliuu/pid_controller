"""
整定段检测器 (Tuning Segment Detector) - Level 1
=================================================

在历史数据中检测"MV 阶跃 → PV 响应"的高质量整定窗口。
这是三级优选中最高优先级的检测器。

检测逻辑:
1. 先估计过程的特征时间尺度（自相关时间），自适应调整最小窗口长度
2. 扫描 MV 序列，找到所有阶跃变化点
3. 对每个阶跃点，截取 PV 响应窗口并评估质量
4. 按质量评分排序，返回最优的整定段列表

质量评分维度:
- MV 阶跃纯净度（前后是否稳定）
- PV 响应方向一致性（与 MV 方向是否吻合）
- PV 响应信噪比（响应幅度 vs 背景噪声）
- SV 稳定性（整定期间 SV 是否无变化）
- 窗口长度充分性（相对于过程时间尺度是否足够）
"""

import numpy as np
from typing import List, Tuple, Optional


class TuningSegmentDetector:
    """
    Level 1 整定段检测器
    
    检测 MV 产生了清晰阶跃、PV 随之产生可辨识响应的黄金窗口。
    这类数据最适合做模型辨识（FOPDT/SOPDT 最小二乘拟合）。
    
    关键特性：
    - 自适应过程时间尺度：自动估计 PV 的特征时间常数，
      确保选出的窗口有足够的数据点覆盖完整的响应过程。
      液位/温度等慢过程会自动要求更长的窗口。
    """
    
    # 绝对最小值和最大值（硬红线）
    MIN_RESPONSE_FLOOR = 50     # 任何过程至少需要 50 点
    MIN_RESPONSE_CEILING = 2000  # 不超过 2000 点（避免窗口过大）
    
    def __init__(self, 
                 mv_step_threshold: float = 1.0,
                 mv_stable_window: int = 30,
                 pv_response_window_multiplier: float = 5.0,
                 min_response_points: int = 50,
                 min_quality_score: float = 0.4):
        """
        Args:
            mv_step_threshold: MV 阶跃检测的最小变化幅度
            mv_stable_window: 判断 MV 稳定所需的数据点数
            pv_response_window_multiplier: PV 响应窗口长度 = 估计时间常数 × 此倍数
            min_response_points: PV 响应窗口的最小点数（会被自适应覆盖）
            min_quality_score: 整定段质量评分的最低合格阈值
        """
        self.mv_step_threshold = mv_step_threshold
        self.mv_stable_window = mv_stable_window
        self.pv_response_window_multiplier = pv_response_window_multiplier
        self.min_response_points = min_response_points
        self.min_quality_score = min_quality_score
    
    def detect(self, pv_data: np.ndarray, sv_data: np.ndarray, 
               mv_data: np.ndarray) -> List[Tuple[int, int, float, float]]:
        """
        检测整定段
        
        Args:
            pv_data: PV 数据数组
            sv_data: SV 数据数组
            mv_data: MV 数据数组
            
        Returns:
            整定段列表，每个元素为 (start_idx, end_idx, setpoint, quality_score)
            按 quality_score 降序排列
        """
        # Step 0: 自适应过程时间尺度，动态调整 min_response_points
        self._adapt_to_process_timescale(pv_data)
        
        if len(pv_data) < self.adaptive_min_response * 2:
            return []
        
        # Step 1: 检测 MV 阶跃点
        step_points = self._detect_mv_steps(mv_data)
        
        if not step_points:
            return []
        
        # Step 1.5: 合并密集阶跃
        # 如果多个阶跃点间距 < adaptive_min_response，说明 MV 在持续移动
        # 不是独立的阶跃实验,应该合并为一个大段
        step_points = self._merge_clustered_steps(step_points)
        
        print(f"   检测到 {len(step_points)} 个MV阶跃变化点")
        
        # Step 2: 针对每个阶跃点，截取并评估 PV 响应窗口
        candidates = []
        for step_idx, step_size in step_points:
            result = self._evaluate_step_response(
                pv_data, sv_data, mv_data, step_idx, step_size
            )
            if result is not None:
                candidates.append(result)
            else:
                print(f"   阶跃@{step_idx}: MV↑{step_size:.1f}, "
                      f"响应={min(len(pv_data)-step_idx, self.adaptive_response_length)}点, "
                      f"质量=0.00 ✗")
        
        print(f"   📊 检测到 {len(candidates)} 个有效整定段")
        
        # Step 3: 按质量评分降序排序
        candidates.sort(key=lambda x: x[3], reverse=True)
        
        # Step 4: 去除重叠的段（贪心法，优先保留高分段）
        filtered = self._remove_overlapping(candidates)
        
        # Step 5: 限制最终返回数量（最多 5 个最优段）
        MAX_SEGMENTS = 5
        if len(filtered) > MAX_SEGMENTS:
            filtered = filtered[:MAX_SEGMENTS]
        
        return filtered
    
    def _adapt_to_process_timescale(self, pv_data: np.ndarray):
        """
        根据 PV 数据的自相关特征，自适应调整最小窗口长度。
        
        对于快过程（flow/pressure）：PV 变化快，自相关衰减快 → 短窗口即可
        对于慢过程（level/temperature）：PV 变化慢，自相关衰减慢 → 需要长窗口
        """
        n = len(pv_data)
        
        # 估计 PV 的特征时间常数（自相关降到 1/e 的时间）
        tau = self._estimate_characteristic_time(pv_data)
        
        # 自适应最小响应点数 = 特征时间 × 倍数（确保覆盖完整响应）
        # 至少需要 3 倍特征时间才能看到 95% 的阶跃响应
        adaptive_min = int(tau * 3.0)
        
        # 用总数据长度的比例做额外约束（选段不应超过总长的 30%）
        max_by_data = int(n * 0.3)
        
        # 综合取值
        self.adaptive_min_response = max(
            self.MIN_RESPONSE_FLOOR,
            min(adaptive_min, max_by_data, self.MIN_RESPONSE_CEILING)
        )
        
        # 响应窗口长度也自适应
        self.adaptive_response_length = max(
            self.adaptive_min_response,
            int(tau * self.pv_response_window_multiplier)
        )
        self.adaptive_response_length = min(
            self.adaptive_response_length, 
            max_by_data,
            self.MIN_RESPONSE_CEILING
        )
        
        print(f"📊 数据质量: "
              f"特征时间τ={tau:.0f}点, "
              f"自适应最小窗口={self.adaptive_min_response}点, "
              f"响应窗口={self.adaptive_response_length}点")
    
    def _estimate_characteristic_time(self, pv_data: np.ndarray) -> float:
        """
        估计 PV 数据的特征时间常数（自相关函数降到 1/e 所需的滞后步数）
        
        Returns:
            特征时间（以数据点数为单位）
        """
        n = len(pv_data)
        
        # 去均值
        pv_centered = pv_data - np.mean(pv_data)
        var = np.var(pv_centered)
        
        if var < 1e-10:
            return float(self.min_response_points)  # 数据几乎不变
        
        # 计算自相关函数（只算前 1/4 数据长度的滞后）
        max_lag = min(n // 4, 2000)
        target = 1.0 / np.e  # ~0.368
        
        tau = float(self.min_response_points)  # 默认值
        
        for lag in range(1, max_lag):
            # 自相关系数
            if lag < n:
                autocorr = np.mean(pv_centered[:n-lag] * pv_centered[lag:]) / var
            else:
                break
            
            if autocorr < target:
                tau = float(lag)
                break
        else:
            # 自相关一直没有衰减到 1/e → 非常慢的过程（积分器/液位）
            # 用一个较为保守的估计
            tau = float(max_lag)
        
        return tau

    def _detect_mv_steps(self, mv_data: np.ndarray) -> List[Tuple[int, float]]:
        """
        检测 MV 序列中的阶跃变化点
        
        Returns:
            阶跃点列表，每个元素为 (阶跃发生的索引, 阶跃幅度)
        """
        n = len(mv_data)
        step_points = []
        
        # 自适应阈值：基于 MV 整体范围
        mv_range = np.ptp(mv_data)
        if mv_range < 0.1:
            return []  # MV 几乎没有变化，不可能有阶跃
        
        adaptive_threshold = max(self.mv_step_threshold, mv_range * 0.02)
        
        i = self.mv_stable_window
        while i < n - self.mv_stable_window:
            # 前窗和后窗
            pre_window = mv_data[max(0, i - self.mv_stable_window):i]
            post_start = i
            
            # 找到阶跃结束点（MV 重新稳定的位置）
            post_end = min(i + self.mv_stable_window, n)
            for j in range(i + 1, min(i + 10, n)):
                # 阶跃通常在几个点内完成
                if j + self.mv_stable_window <= n:
                    post_window_check = mv_data[j:j + self.mv_stable_window]
                    if np.std(post_window_check) < np.std(pre_window) * 2 + 0.5:
                        post_start = j
                        break
            
            post_window = mv_data[post_start:min(post_start + self.mv_stable_window, n)]
            
            if len(pre_window) < 5 or len(post_window) < 5:
                i += 1
                continue
            
            pre_mean = np.mean(pre_window)
            post_mean = np.mean(post_window)
            step_size = post_mean - pre_mean
            
            if abs(step_size) > adaptive_threshold:
                # 验证阶跃前后 MV 确实稳定
                pre_std = np.std(pre_window)
                post_std = np.std(post_window)
                
                pre_stable = pre_std < abs(step_size) * 0.3
                post_stable = post_std < abs(step_size) * 0.3
                
                if pre_stable and post_stable:
                    step_points.append((i, step_size))
                    # 跳过这个阶跃的影响区域
                    i = post_start + self.mv_stable_window
                    continue
            
            i += max(1, self.mv_stable_window // 3)
        
        return step_points
    
    def _evaluate_step_response(self, pv_data: np.ndarray, sv_data: np.ndarray,
                                 mv_data: np.ndarray, step_idx: int, 
                                 step_size: float) -> Optional[Tuple[int, int, float, float]]:
        """
        评估某个 MV 阶跃点对应的 PV 响应质量
        
        Returns:
            (start_idx, end_idx, setpoint, quality_score) 或 None
        """
        n = len(pv_data)
        
        # 确定前置稳态段（用于计算基线噪声）
        pre_start = max(0, step_idx - self.mv_stable_window * 2)
        pre_end = step_idx
        
        # 使用自适应的响应窗口长度
        response_length = max(self.adaptive_min_response, self.adaptive_response_length)
        response_length = min(response_length, n - step_idx)
        
        if response_length < self.adaptive_min_response:
            return None
        
        resp_end = step_idx + response_length
        
        # 动态缩短：如果 PV 已经稳定就提前截止
        resp_end = self._find_response_end(pv_data, sv_data, step_idx, resp_end)
        
        if resp_end - step_idx < self.adaptive_min_response:
            return None
        
        # 整定段 = 前置稳态 + 响应窗口
        seg_start = pre_start
        seg_end = resp_end
        setpoint = float(np.median(sv_data[seg_start:seg_end]))
        
        # 计算质量评分
        quality = self._compute_quality_score(
            pv_data, sv_data, mv_data, seg_start, step_idx, seg_end, step_size
        )
        
        if quality < self.min_quality_score:
            return None
        
        seg_length = seg_end - seg_start
        print(f"   阶跃@{step_idx}: MV↑{step_size:.1f}, "
              f"响应={seg_length}点, 质量={quality:.2f} ✓")
        
        return (seg_start, seg_end, setpoint, quality)
    
    def _find_response_end(self, pv_data: np.ndarray, sv_data: np.ndarray,
                           step_idx: int, max_end: int) -> int:
        """
        动态查找 PV 响应结束点（PV 重新趋于稳态的位置）
        """
        window = 20
        # 至少等到自适应最小窗口之后才开始检查稳态
        check_start = step_idx + self.adaptive_min_response
        
        for i in range(check_start, max_end - window, window // 2):
            chunk = pv_data[i:i + window]
            chunk_std = np.std(chunk)
            chunk_range = np.ptp(chunk)
            
            # 如果这段 PV 已经非常平稳，认为响应结束
            sv_local = np.median(sv_data[i:i + window])
            chunk_mean = np.mean(chunk)
            deviation = abs(chunk_mean - sv_local)
            
            if chunk_std < 0.5 and chunk_range < 2.0 and deviation < 2.0:
                # 再向后延伸一小段确认
                confirm_end = min(i + window * 2, max_end)
                if confirm_end > i + window:
                    confirm_chunk = pv_data[i + window:confirm_end]
                    if np.std(confirm_chunk) < 1.0:
                        return confirm_end
        
        return max_end
    
    def _compute_quality_score(self, pv_data: np.ndarray, sv_data: np.ndarray,
                                mv_data: np.ndarray, seg_start: int, 
                                step_idx: int, seg_end: int,
                                step_size: float) -> float:
        """
        计算整定段的综合质量评分 (0~1)
        
        评估维度:
        1. MV 阶跃纯净度 (0.20)
        2. PV 响应方向一致性 (0.20)
        3. PV 响应信噪比 (0.20)
        4. SV 稳定性 (0.20)
        5. 窗口长度充分性 (0.20)
        """
        scores = []
        
        # 1. MV 阶跃纯净度 (阶跃前后 MV 的稳定程度)
        pre_mv = mv_data[seg_start:step_idx]
        post_mv = mv_data[step_idx:min(step_idx + self.mv_stable_window, seg_end)]
        
        if len(pre_mv) > 2 and len(post_mv) > 2:
            pre_std = np.std(pre_mv)
            post_std = np.std(post_mv)
            noise_ratio = (pre_std + post_std) / (2 * abs(step_size) + 1e-8)
            purity = max(0, 1 - noise_ratio * 5)  # noise_ratio < 0.2 → 满分
        else:
            purity = 0.0
        scores.append(purity)
        
        # 2. PV 响应方向一致性
        pv_before = np.mean(pv_data[max(seg_start, step_idx - 20):step_idx])
        pv_after = np.mean(pv_data[min(step_idx + 20, seg_end):min(step_idx + 60, seg_end)])
        pv_change = pv_after - pv_before
        
        if abs(pv_change) > 0.1 and abs(step_size) > 0.1:
            direction_match = 1.0 if (pv_change * step_size > 0) else 0.0
        else:
            direction_match = 0.3  # 变化太小，不确定
        scores.append(direction_match)
        
        # 3. PV 响应信噪比
        pre_pv = pv_data[seg_start:step_idx]
        resp_pv = pv_data[step_idx:seg_end]
        
        if len(pre_pv) > 5:
            noise_level = np.std(pre_pv)
            response_amplitude = abs(np.mean(resp_pv[-20:]) - np.mean(pre_pv)) if len(resp_pv) >= 20 else abs(pv_change)
            
            if noise_level > 0.01:
                snr = response_amplitude / noise_level
                snr_score = min(1.0, snr / 5.0)  # SNR > 5 → 满分
            else:
                snr_score = 1.0 if response_amplitude > 0.5 else 0.5
        else:
            snr_score = 0.3
        scores.append(snr_score)
        
        # 4. SV 稳定性（整定期间 SV 不应变化）
        sv_segment = sv_data[seg_start:seg_end]
        if len(sv_segment) > 5:
            sv_range = np.ptp(sv_segment)
            sv_std = np.std(sv_segment)
            sv_stable = 1.0 if (sv_range < 1.0 and sv_std < 0.5) else max(0, 1.0 - sv_range / 5.0)
        else:
            sv_stable = 0.5
        scores.append(sv_stable)
        
        # 5. 窗口长度充分性（相对于过程时间尺度）
        seg_length = seg_end - seg_start
        length_ratio = seg_length / self.adaptive_min_response
        if length_ratio >= 3.0:
            length_score = 1.0  # 窗口 >= 3x最小值 → 满分
        elif length_ratio >= 1.5:
            length_score = 0.7  # 窗口 1.5x-3x → 良好
        elif length_ratio >= 1.0:
            length_score = 0.4  # 刚刚够用
        else:
            length_score = 0.0  # 不够
        scores.append(length_score)
        
        # 综合加权
        return np.mean(scores)
    
    def _merge_clustered_steps(self, step_points: List[Tuple[int, float]]) -> List[Tuple[int, float]]:
        """
        合并密集的 MV 阶跃点。
        
        如果多个阶跃点之间的间距 < adaptive_min_response，认为它们不是
        独立的阶跃实验，而是 MV 在持续连续变动（如操作员多次小幅调阀），
        应该合并为一个"复合阶跃"，取代表性的那个点。
        
        合并策略：
        - 同方向的密集阶跃：取累计总变化量最大的时段的第一个阶跃点
        - 反方向的阶跃：视为独立事件，不合并
        """
        if len(step_points) <= 1:
            return step_points
        
        merge_gap = self.adaptive_min_response  # 间距门槛
        
        # 按索引排序
        sorted_steps = sorted(step_points, key=lambda x: x[0])
        
        # 分组：间距 < merge_gap 的归为一组
        clusters = []
        current_cluster = [sorted_steps[0]]
        
        for i in range(1, len(sorted_steps)):
            gap = sorted_steps[i][0] - current_cluster[-1][0]
            if gap < merge_gap:
                current_cluster.append(sorted_steps[i])
            else:
                clusters.append(current_cluster)
                current_cluster = [sorted_steps[i]]
        clusters.append(current_cluster)
        
        # 每个 cluster 合并为一个代表阶跃
        merged = []
        for cluster in clusters:
            if len(cluster) == 1:
                merged.append(cluster[0])
            else:
                # 取簇中第一个阶跃点作为代表（保持原始检测行为）
                first = cluster[0]
                merged.append(first)  # 保持原始 step_size
        
        if len(merged) < len(step_points):
            print(f"   📊 合并密集阶跃: {len(step_points)} → {len(merged)} "
                  f"(合并间距<{merge_gap}点的阶跃簇)")
        
        return merged
    
    def _remove_overlapping(self, candidates: List[Tuple[int, int, float, float]]) -> List[Tuple[int, int, float, float]]:
        """
        贪心法去除重叠的段（优先保留高分段）
        """
        if not candidates:
            return []
        
        selected = [candidates[0]]
        for c in candidates[1:]:
            c_start, c_end = c[0], c[1]
            overlap = False
            for s in selected:
                s_start, s_end = s[0], s[1]
                if not (c_end <= s_start or c_start >= s_end):
                    overlap = True
                    break
            if not overlap:
                selected.append(c)
        
        return selected
