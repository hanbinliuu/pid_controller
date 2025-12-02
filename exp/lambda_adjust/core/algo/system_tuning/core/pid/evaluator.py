"""
PID参数评估器
用于评估整定后的PID参数质量
"""
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class EvaluationMetrics:
    """评估指标数据类 - 专注于PID稳态控制性能"""
    # 稳态控制性能指标
    steady_state_error: float  # 稳态误差
    iae: float  # 绝对误差积分
    ise: float  # 误差平方积分
    
    # 控制平滑性指标
    tv: float  # 控制输出总变化量
    max_control_effort: float  # 最大控制输出
    
    # 振荡指标
    oscillation_count: int  # 振荡次数
    max_oscillation_amplitude: float  # 最大振荡幅度
    
    # 综合评分
    overall_score: float  # 0-100分
    grade: str  # 等级: A/B/C/D/F
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'steady_state': {
                'steady_state_error': round(self.steady_state_error, 4),
                'iae': round(self.iae, 4),
                'ise': round(self.ise, 4)
            },
            'control_smoothness': {
                'total_variation': round(self.tv, 4),
                'max_control_effort': round(self.max_control_effort, 2)
            },
            'oscillation': {
                'oscillation_count': self.oscillation_count,
                'max_amplitude': round(self.max_oscillation_amplitude, 4)
            },
            'overall': {
                'score': round(self.overall_score, 2),
                'grade': self.grade
            }
        }


class PIDEvaluator:
    """PID参数评估器"""
    
    def __init__(self, 
                 settling_band: float = 0.02,  # 稳态误差带 (2%)
                 settling_duration: int = 50):  # 稳态持续时间
        """
        初始化评估器
        
        Args:
            settling_band: 稳态误差带，默认2%
            settling_duration: 判定稳态需要持续的点数
        """
        self.settling_band = settling_band
        self.settling_duration = settling_duration
    
    def evaluate(self,
                 pv: np.ndarray,
                 sv: np.ndarray,
                 cv: Optional[np.ndarray] = None,
                 segment_start: int = 0,
                 segment_end: Optional[int] = None,
                 exclude_sv_transition: bool = True,
                 pid_params: Optional[Dict] = None) -> EvaluationMetrics:
        """
        评估PID稳态控制性能
        
        专注于评估：
        1. 稳态误差：系统是否能稳定在设定值附近
        2. 控制平滑性：控制输出是否平滑，不频繁变化
        3. 振荡抑制：是否能有效抑制振荡
        
        Args:
            pv: 过程变量数组
            sv: 设定值数组
            cv: 控制输出数组（可选）
            segment_start: 评估段起始索引
            segment_end: 评估段结束索引
            exclude_sv_transition: 是否排除SV调整期间（默认True）
            
        Returns:
            评估指标对象
        """
        if segment_end is None:
            segment_end = len(pv)
        
        # 提取评估段数据
        pv_seg = pv[segment_start:segment_end]
        sv_seg = sv[segment_start:segment_end]
        cv_seg = cv[segment_start:segment_end] if cv is not None else None
        
        # 智能排除SV调整期间，只评估稳态控制性能
        eval_start_offset = 0
        if exclude_sv_transition:
            eval_start_offset = self._find_steady_state_start(pv_seg, sv_seg)
        
        # 使用稳态段数据计算所有指标
        pv_steady = pv_seg[eval_start_offset:] if eval_start_offset > 0 else pv_seg
        sv_steady = sv_seg[eval_start_offset:] if eval_start_offset > 0 else sv_seg
        cv_steady = cv_seg[eval_start_offset:] if cv_seg is not None and eval_start_offset > 0 else cv_seg
        
        # 1. 稳态误差指标
        steady_state_error = self._calculate_steady_state_error(pv_steady, sv_steady)
        iae = self._calculate_iae(pv_steady, sv_steady)
        ise = self._calculate_ise(pv_steady, sv_steady)
        
        # 2. 控制平滑性指标
        tv = self._calculate_tv(cv_steady) if cv_steady is not None else 0.0
        max_control_effort = np.max(np.abs(cv_steady)) if cv_steady is not None else 0.0
        
        # 3. 振荡指标
        oscillation_count, max_oscillation_amplitude = self._calculate_oscillation_metrics(pv_steady, sv_steady)
        
        # 4. 计算综合评分
        overall_score, grade = self._calculate_overall_score(
            steady_state_error, iae, ise, tv,
            oscillation_count, max_oscillation_amplitude,
            data_length=len(pv_steady),
            pid_params=pid_params
        )
        
        return EvaluationMetrics(
            steady_state_error=steady_state_error,
            iae=iae,
            ise=ise,
            tv=tv,
            max_control_effort=max_control_effort,
            oscillation_count=oscillation_count,
            max_oscillation_amplitude=max_oscillation_amplitude,
            overall_score=overall_score,
            grade=grade
        )
    
    def _find_steady_state_start(self, pv: np.ndarray, sv: np.ndarray) -> int:
        """
        智能检测稳态段起始点，完全排除SV调整期间的数据
        
        优化策略：
        1. 检测SV变化（阈值降低到0.05，更敏感）
        2. 找到PV开始接近目标值的位置
        3. 排除整个响应过程，只评估稳态段
        
        Args:
            pv: 过程变量数组
            sv: 设定值数组
            
        Returns:
            稳态段起始点的偏移量
        """
        if len(pv) < 20 or len(sv) < 20:
            return 0
        
        # 1. 检测SV是否有变化（降低阈值，更敏感）
        sv_changes = np.where(np.abs(np.diff(sv)) > 0.05)[0]
        if len(sv_changes) == 0:
            # 没有SV变化，检查PV是否偏离SV太多
            mean_error = np.mean(np.abs(pv - sv))
            if mean_error > 0.5:
                # PV偏离SV较大，可能是初始响应阶段，排除前30%
                return int(len(pv) * 0.3)
            return 0
        
        # 找到第一个SV变化点
        sv_change_idx = sv_changes[0]
        if sv_change_idx >= len(pv) - 10:
            return 0
        
        # 2. 获取SV变化前后的值
        sv_before = sv[max(0, sv_change_idx - 2)]
        sv_after = sv[min(sv_change_idx + 5, len(sv) - 1)]
        sv_change_magnitude = abs(sv_after - sv_before)
        
        # 3. 根据SV变化幅度调整策略
        if sv_change_magnitude < 0.1:
            # SV变化很小，但仍可能有响应过程，排除前20%
            return min(sv_change_idx + int((len(pv) - sv_change_idx) * 0.2), len(pv) - 10)
        
        # 4. 找到PV接近目标值的位置
        # 动态调整容差：基于SV变化幅度
        tolerance = max(abs(sv_after) * 0.08, sv_change_magnitude * 0.15, 0.2)
        stable_window = min(15, (len(pv) - sv_change_idx) // 4)  # 动态窗口大小
        
        # 策略A: 找到连续稳定的点
        for i in range(sv_change_idx, len(pv) - stable_window):
            window = pv[i:i + stable_window]
            errors = np.abs(window - sv_after)
            
            # 检查：大部分点（80%）在容差范围内
            in_tolerance = np.sum(errors <= tolerance) / len(errors)
            if in_tolerance >= 0.8:
                eval_start = max(0, i - 3)
                return eval_start
        
        # 策略B: 找到误差开始减小的拐点
        errors_after_change = np.abs(pv[sv_change_idx:] - sv_after)
        if len(errors_after_change) > 20:
            # 计算误差的移动平均
            window_size = min(10, len(errors_after_change) // 5)
            moving_avg = np.convolve(errors_after_change, 
                                    np.ones(window_size)/window_size, 
                                    mode='valid')
            
            # 找到误差开始稳定（变化率小）的位置
            if len(moving_avg) > 10:
                error_changes = np.abs(np.diff(moving_avg))
                stable_threshold = np.percentile(error_changes, 25)  # 25%分位数
                
                for i in range(len(error_changes) - 5):
                    if np.all(error_changes[i:i+5] <= stable_threshold):
                        eval_start = sv_change_idx + i + window_size
                        return min(eval_start, len(pv) - 10)
        
        # 策略C: 使用尾部30%的数据
        tail_start = max(sv_change_idx, len(pv) - int(len(pv) * 0.3))
        tail_pv = pv[tail_start:]
        tail_errors = np.abs(tail_pv - sv_after)
        
        if np.mean(tail_errors) <= tolerance * 2:
            return tail_start
        
        # 策略D: 保守策略 - 排除前40%的响应过程
        response_length = len(pv) - sv_change_idx
        return min(sv_change_idx + int(response_length * 0.4), len(pv) - 10)
    
    def _calculate_oscillation_metrics(self, pv: np.ndarray, sv: np.ndarray) -> Tuple[int, float]:
        """
        计算振荡指标
        
        Returns:
            (振荡次数, 最大振荡幅度)
        """
        if len(pv) < 10 or len(sv) < 10:
            return 0, 0.0
        
        # 计算误差
        errors = pv - sv
        
        # 找到所有过零点（振荡）
        zero_crossings = 0
        for i in range(1, len(errors)):
            if errors[i-1] * errors[i] < 0:  # 符号改变
                zero_crossings += 1
        
        # 振荡次数 = 过零点数 / 2
        oscillation_count = zero_crossings // 2
        
        # 最大振荡幅度
        max_amplitude = np.max(np.abs(errors))
        
        return oscillation_count, max_amplitude
    
    
    def _calculate_steady_state_error(self, pv: np.ndarray, sv: np.ndarray) -> float:
        """计算稳态误差 - 使用全部稳态段数据"""
        if len(pv) == 0:
            return 0.0
        return np.mean(np.abs(pv - sv))
    
    def _calculate_iae(self, pv: np.ndarray, sv: np.ndarray) -> float:
        """计算绝对误差积分"""
        errors = np.abs(pv - sv)
        return np.sum(errors)
    
    def _calculate_ise(self, pv: np.ndarray, sv: np.ndarray) -> float:
        """计算误差平方积分"""
        errors = pv - sv
        return np.sum(errors ** 2)
    
    def _calculate_tv(self, cv: np.ndarray) -> float:
        """计算控制输出总变化量"""
        if cv is None or len(cv) < 2:
            return 0.0
        return np.sum(np.abs(np.diff(cv)))
    
    def _calculate_overall_score(self,
                                 steady_state_error: float,
                                 iae: float,
                                 ise: float,
                                 tv: float,
                                 oscillation_count: int,
                                 max_oscillation_amplitude: float,
                                 data_length: int = 1,
                                 pid_params: Optional[Dict] = None) -> Tuple[float, str]:
        """
        计算综合评分 (0-100) - 专注于PID稳态控制性能
        
        评分权重：
        - 稳态误差: 40% (最重要)
        - 振荡抑制: 30%
        - 控制平滑性: 30%
        """
        score = 100.0
        
        # 1. 稳态误差评分 (0-40分) - 核心指标
        # 使用平均误差进行评分（宽松标准，适合工业应用）
        avg_error = iae / data_length if data_length > 0 else iae
        
        if avg_error < 0.2:
            sse_score = 40  # 优秀：误差小于0.2
        elif avg_error < 0.5:
            sse_score = 38  # 很好：误差0.2-0.5（你的情况）
        elif avg_error < 1.0:
            sse_score = 35  # 良好：误差0.5-1.0
        elif avg_error < 2.0:
            sse_score = 28  # 一般：误差1.0-2.0
        elif avg_error < 3.0:
            sse_score = 20  # 较差：误差2.0-3.0
        else:
            sse_score = max(0, 20 - (avg_error - 3.0) * 3)  # 很差
        
        # 2. 振荡抑制评分 (0-30分) - 宽松标准
        # 2.1 振荡次数评分 (0-15分)
        if oscillation_count == 0:
            osc_count_score = 15  # 无振荡
        elif oscillation_count <= 2:
            osc_count_score = 13  # 1-2次振荡可接受（仅扣2分）
        elif oscillation_count <= 5:
            osc_count_score = 10  # 3-5次振荡
        elif oscillation_count <= 8:
            osc_count_score = 6   # 6-8次振荡
        else:
            osc_count_score = max(0, 6 - (oscillation_count - 8) * 0.5)
        
        # 2.2 振荡幅度评分 (0-15分) - 宽松标准
        if max_oscillation_amplitude < 0.2:
            osc_amp_score = 15  # 幅度很小
        elif max_oscillation_amplitude < 0.5:
            osc_amp_score = 13  # 幅度小（可接受）
        elif max_oscillation_amplitude < 1.0:
            osc_amp_score = 10  # 幅度中等
        elif max_oscillation_amplitude < 2.0:
            osc_amp_score = 6   # 幅度较大
        else:
            osc_amp_score = max(0, 6 - (max_oscillation_amplitude - 2.0) * 1.5)
        
        oscillation_score = osc_count_score + osc_amp_score
        
        # 3. 控制平滑性评分 (0-30分) - 宽松标准
        # 归一化TV：TV/数据点数
        avg_tv = tv / data_length if data_length > 0 else tv
        
        if avg_tv < 1.0:
            smoothness_score = 30  # 非常平滑
        elif avg_tv < 2.0:
            smoothness_score = 28  # 平滑（可接受）
        elif avg_tv < 3.0:
            smoothness_score = 25  # 较平滑
        elif avg_tv < 5.0:
            smoothness_score = 20  # 一般
        elif avg_tv < 8.0:
            smoothness_score = 12  # 较差
        else:
            smoothness_score = max(0, 12 - (avg_tv - 8.0) * 1.5)
        
        # 综合评分
        total_score = sse_score + oscillation_score + smoothness_score
        
        # 4. 参数合理性惩罚 (扣除0-20分)
        if pid_params is not None:
            param_penalty = self._calculate_parameter_penalty(pid_params)
            total_score -= param_penalty
        
        # 确定等级（宽松标准，适合工业应用）
        if total_score >= 80:
            grade = 'A'  # 优秀
        elif total_score >= 65:
            grade = 'B'  # 良好
        elif total_score >= 50:
            grade = 'C'  # 中等（可接受）
        elif total_score >= 35:
            grade = 'D'  # 合格
        else:
            grade = 'F'  # 不合格
        
        return max(0, min(100, total_score)), grade  # 确保在0-100分之间
    
    def _calculate_parameter_penalty(self, pid_params: Dict) -> float:
        """
        计算PID参数合理性惩罚
        
        检查项：
        1. 参数是否在合理范围内
        2. 参数比例关系是否合理
        3. 参数组合是否可能导致不稳定
        
        Returns:
            惩罚分数 (0-20分)
        """
        penalty = 0.0
        
        # 提取参数（支持Pb/Ti/Td和Kp/Ki/Kd两种格式）
        pb = pid_params.get('pb', pid_params.get('Pb', None))
        ti = pid_params.get('ti', pid_params.get('Ti', None))
        td = pid_params.get('td', pid_params.get('Td', None))
        
        if pb is None or ti is None or td is None:
            return 0.0  # 如果参数不完整，不惩罚
        
        # 1. 极端参数惩罚
        # Pb (比例带) 合理范围: 5-300%
        if pb < 5:
            penalty += 8  # Pb过小，控制作用太强，容易振荡
        elif pb > 300:
            penalty += 5  # Pb过大，控制作用太弱
        
        # Ti (积分时间) 合理范围: 0-300s
        if ti > 300:
            penalty += 5  # Ti过大，积分作用太弱，稳态误差大
        elif ti > 0 and ti < 5:
            penalty += 3  # Ti过小，积分作用太强，容易振荡
        
        # Td (微分时间) 合理范围: 0-100s
        if td > 100:
            penalty += 5  # Td过大，对噪声敏感
        elif td > 50:
            penalty += 2  # Td较大，需要注意
        
        # 2. 参数比例关系检查
        if ti > 0:
            pb_ti_ratio = pb / ti
            # Pb/Ti 合理范围: 0.1-5
            if pb_ti_ratio > 10:
                penalty += 5  # 比例作用相对积分作用过强
            elif pb_ti_ratio < 0.05:
                penalty += 3  # 积分作用相对比例作用过强
        
        if ti > 0 and td > 0:
            ti_td_ratio = ti / td
            # Ti/Td 合理范围: 2-20
            if ti_td_ratio < 1:
                penalty += 4  # 微分时间过大，可能导致不稳定
            elif ti_td_ratio > 50:
                penalty += 2  # 微分作用太弱
        
        # 3. 特殊组合惩罚
        # 纯P控制（Ti=0, Td=0）但Pb很小
        if ti == 0 and td == 0 and pb < 20:
            penalty += 6  # 纯P控制且比例作用很强，容易振荡
        
        # 强积分+强微分组合
        if ti > 0 and ti < 10 and td > 20:
            penalty += 4  # 这种组合容易不稳定
        
        return min(penalty, 20)  # 最多扣20分
    
    def compare_parameters(self,
                          pv_list: List[np.ndarray],
                          sv_list: List[np.ndarray],
                          cv_list: List[Optional[np.ndarray]],
                          param_names: List[str]) -> Dict:
        """
        比较多组PID参数的性能
        
        Args:
            pv_list: PV数组列表
            sv_list: SV数组列表
            cv_list: CV数组列表
            param_names: 参数组名称列表
            
        Returns:
            比较结果字典
        """
        results = {}
        
        for i, (pv, sv, cv, name) in enumerate(zip(pv_list, sv_list, cv_list, param_names)):
            metrics = self.evaluate(pv, sv, cv)
            results[name] = metrics.to_dict()
        
        # 找出最佳参数
        best_param = max(results.items(), 
                        key=lambda x: x[1]['overall']['score'])
        
        return {
            'individual_results': results,
            'best_parameter': {
                'name': best_param[0],
                'score': best_param[1]['overall']['score'],
                'grade': best_param[1]['overall']['grade']
            },
            'ranking': sorted(results.items(), 
                            key=lambda x: x[1]['overall']['score'], 
                            reverse=True)
        }
    
    def generate_report(self, metrics: EvaluationMetrics) -> str:
        """生成评估报告 - 专注于稳态控制性能"""
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║           PID稳态控制性能评估报告                             ║
╚══════════════════════════════════════════════════════════════╝

【综合评分】
  评分: {metrics.overall_score:.2f} / 100
  等级: {metrics.grade}

【稳态控制性能】
  稳态误差:       {metrics.steady_state_error:.4f}
  IAE:           {metrics.iae:.4f}
  ISE:           {metrics.ise:.4f}

【振荡抑制】
  振荡次数:       {metrics.oscillation_count}
  最大振幅:       {metrics.max_oscillation_amplitude:.4f}

【控制平滑性】
  控制变化量:     {metrics.tv:.4f}
  最大控制输出:   {metrics.max_control_effort:.2f}

【评价建议】
"""
        # 根据各项指标给出建议
        suggestions = []
        
        # 稳态误差建议
        if metrics.steady_state_error > 0.5:
            suggestions.append("  ⚠ 稳态误差过大，建议增大Ki或检查系统模型")
        elif metrics.steady_state_error > 0.1:
            suggestions.append("  ⚡ 稳态误差偏大，可适当增大Ki")
        else:
            suggestions.append("  ✓ 稳态误差控制良好")
        
        # 振荡建议
        if metrics.oscillation_count > 5:
            suggestions.append("  ⚠ 振荡次数过多，建议增大Kd或减小Kp")
        elif metrics.oscillation_count > 2:
            suggestions.append("  ⚡ 存在振荡，可适当增大Kd")
        else:
            suggestions.append("  ✓ 振荡抑制良好")
        
        # 控制平滑性建议
        avg_tv = metrics.tv / 100 if metrics.tv > 0 else 0  # 粗略估算
        if avg_tv > 5.0:
            suggestions.append("  ⚠ 控制输出变化频繁，建议减小Kp或增大滤波")
        elif avg_tv > 2.0:
            suggestions.append("  ⚡ 控制输出略频繁，可适当优化")
        else:
            suggestions.append("  ✓ 控制输出平滑")
        
        report += "\n".join(suggestions)
        report += "\n" + "═" * 62
        
        return report
