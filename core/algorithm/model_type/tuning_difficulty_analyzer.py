"""
整定难度分析器 (Tuning Difficulty Analyzer)
=============================================

根据回路历史数据分析整定难度，识别问题类型。

输出:
- difficulty_score: 整定难度评分 (1-10)
- difficulty_level: 难度等级 (easy/medium/hard/extreme)
- issue_types: 检测到的问题类型列表
- recommendations: 整定建议
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class IssueType:
    """问题类型定义"""
    name: str           # 名称
    name_cn: str        # 中文名称
    severity: str       # 严重程度: low/medium/high
    confidence: float   # 置信度 0-1
    evidence: str       # 证据描述


# 问题类型定义 (与 test_synthetic_tuning.py 对齐)
# 难度加分参考:
#   - 滞后: L/T1 > 0.5 (+1), > 1.0 (+2), > 2.0 (+3)
#   - 增益变化: > 2x (+1), > 5x (+2), > 10x (+3)
#   - 噪声: > 0.4 (+1), > 0.8 (+2), > 1.5 (+3)
ISSUE_TYPES = {
    # 阀门问题 - 需要机械检修
    "valve_stiction": {"name_cn": "阀门粘滞", "base_difficulty": 2.5},
    "valve_deadband": {"name_cn": "阀门死区", "base_difficulty": 1.5},
    "saturation": {"name_cn": "执行器饱和", "base_difficulty": 1.5},
    
    # 滞后问题 - 需要保守整定
    "medium_delay": {"name_cn": "中等滞后", "base_difficulty": 1.0},  # L/T1 > 0.5
    "large_delay": {"name_cn": "大滞后", "base_difficulty": 2.0},     # L/T1 > 1.0
    "extreme_delay": {"name_cn": "极大滞后", "base_difficulty": 3.0}, # L/T1 > 2.0
    
    # 增益问题
    "gain_change_small": {"name_cn": "增益变化", "base_difficulty": 1.0},    # > 2x
    "gain_change_large": {"name_cn": "增益大变", "base_difficulty": 2.0},    # > 5x
    "gain_change_extreme": {"name_cn": "增益剧变", "base_difficulty": 3.0},  # > 10x
    
    # 噪声问题
    "noise_medium": {"name_cn": "中等噪声", "base_difficulty": 1.0},  # > 0.4
    "noise_high": {"name_cn": "高噪声", "base_difficulty": 2.0},      # > 0.8
    "noise_extreme": {"name_cn": "极高噪声", "base_difficulty": 3.0}, # > 1.5
    
    # 过程特性
    "reverse_action": {"name_cn": "反作用特性", "base_difficulty": 1.0},
    "reverse_sudden": {"name_cn": "反向突变", "base_difficulty": 4.0},  # 突然变为反向
    "nonlinearity": {"name_cn": "非线性特性", "base_difficulty": 2.0},
    "integrating_process": {"name_cn": "积分/慢系统", "base_difficulty": 2.0},  # T1 > 100s
    "fast_system": {"name_cn": "快系统", "base_difficulty": 1.0},  # T1 < 5s
    
    # 振荡问题
    "oscillation_mild": {"name_cn": "轻微振荡", "base_difficulty": 1.0},
    "oscillation_severe": {"name_cn": "严重振荡", "base_difficulty": 2.5},
    
    # 其他
    "coupling": {"name_cn": "回路耦合", "base_difficulty": 2.0},
}


class TuningDifficultyAnalyzer:
    """整定难度分析器"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
    
    def analyze(self, pv: np.ndarray, mv: np.ndarray, sv: np.ndarray,
                timestamps: np.ndarray, loop_type: str = "unknown") -> Dict:
        """
        分析整定难度
        
        Args:
            pv: 过程值数组
            mv: 操作值数组
            sv: 设定值数组
            timestamps: 时间戳数组 (毫秒)
            loop_type: 回路类型
            
        Returns:
            分析结果字典
        """
        # 计算采样周期
        dt = np.median(np.diff(timestamps)) / 1000  # 秒
        
        # 检测各类问题
        issues = []
        
        # 1. 振荡分析
        osc_issue = self._detect_oscillation(pv, sv, dt)
        if osc_issue:
            issues.append(osc_issue)
        
        # 2. 阀门问题检测
        valve_issues = self._detect_valve_issues(pv, mv, dt)
        issues.extend(valve_issues)
        
        # 3. 过程特性检测
        process_issues = self._detect_process_characteristics(pv, mv, sv, dt)
        issues.extend(process_issues)
        
        # 4. 动态特性检测
        dynamics_issues = self._detect_dynamics(pv, mv, dt, loop_type)
        issues.extend(dynamics_issues)
        
        # 5. 噪声检测
        noise_issue = self._detect_noise(pv, sv)
        if noise_issue:
            issues.append(noise_issue)
        
        # 计算总体难度
        difficulty_score = self._calculate_difficulty_score(issues)
        difficulty_level = self._get_difficulty_level(difficulty_score)
        
        # 生成建议
        recommendations = self._generate_recommendations(issues, loop_type)
        
        return {
            "difficulty_score": difficulty_score,
            "difficulty_level": difficulty_level,
            "difficulty_level_cn": self._level_to_cn(difficulty_level),
            "issue_count": len(issues),
            "issues": [self._issue_to_dict(issue) for issue in issues],
            "issue_types": [issue.name for issue in issues],
            "issue_types_cn": [issue.name_cn for issue in issues],
            "recommendations": recommendations,
            "summary": self._generate_summary(difficulty_score, issues)
        }
    
    def _detect_oscillation(self, pv: np.ndarray, sv: np.ndarray, dt: float) -> Optional[IssueType]:
        """检测振荡"""
        error = pv - sv
        
        # 零交叉计数
        zero_crossings = np.where(np.diff(np.sign(error)))[0]
        n_crossings = len(zero_crossings)
        
        # 估算振荡周期
        if n_crossings >= 4:
            periods = np.diff(zero_crossings[::2]) * dt * 2
            period = float(np.median(periods)) if len(periods) > 0 else 0
        else:
            period = 0
        
        # 振荡比例
        expected_crossings = len(pv) / (period / dt + 1) if period > 0 else 0
        oscillation_ratio = n_crossings / (expected_crossings + 1) if expected_crossings > 0 else 0
        
        # 振荡幅度
        amplitude = np.std(error)
        sv_range = np.ptp(sv) if np.ptp(sv) > 0 else np.mean(np.abs(sv))
        relative_amplitude = amplitude / (sv_range + 1e-6) if sv_range > 0 else amplitude
        
        if oscillation_ratio > 0.5 and relative_amplitude > 0.1:
            severity = "high" if oscillation_ratio > 0.7 else "medium"
            return IssueType(
                name="oscillation_severe",
                name_cn="严重振荡",
                severity=severity,
                confidence=min(1.0, oscillation_ratio),
                evidence=f"振荡周期约{period:.1f}s，振荡比{oscillation_ratio:.2f}"
            )
        return None
    
    def _detect_valve_issues(self, pv: np.ndarray, mv: np.ndarray, dt: float) -> List[IssueType]:
        """检测阀门问题"""
        issues = []
        
        mv_diff = np.diff(mv)
        pv_diff = np.diff(pv)
        
        # 1. 阀门粘滞检测
        # 特征：MV 变化但 PV 无响应，之后 PV 突变
        stiction_count = 0
        for i in range(1, len(mv_diff) - 1):
            if abs(mv_diff[i]) > 0.5 and abs(pv_diff[i]) < 0.1:
                if abs(pv_diff[i + 1]) > 0.3:
                    stiction_count += 1
        
        stiction_confidence = min(1.0, stiction_count / 10)
        if stiction_confidence > 0.3:
            issues.append(IssueType(
                name="valve_stiction",
                name_cn="阀门粘滞",
                severity="high" if stiction_confidence > 0.6 else "medium",
                confidence=stiction_confidence,
                evidence=f"检测到{stiction_count}次粘滞-滑动模式"
            ))
        
        # 2. 阀门死区检测
        # 特征：MV 小幅变化时 PV 无响应
        small_mv_changes = np.abs(mv_diff) < 1.0
        small_mv_no_response = small_mv_changes & (np.abs(pv_diff) < 0.05)
        deadband_ratio = np.sum(small_mv_no_response) / (np.sum(small_mv_changes) + 1)
        
        if deadband_ratio > 0.6:
            issues.append(IssueType(
                name="valve_deadband",
                name_cn="阀门死区",
                severity="medium" if deadband_ratio > 0.8 else "low",
                confidence=float(deadband_ratio),
                evidence=f"小幅MV变化中{deadband_ratio*100:.0f}%无PV响应"
            ))
        
        # 3. 执行器饱和检测
        mv_at_limits = np.sum((mv >= 95) | (mv <= 5)) / len(mv)
        if mv_at_limits > 0.1:
            issues.append(IssueType(
                name="saturation",
                name_cn="执行器饱和",
                severity="high" if mv_at_limits > 0.3 else "medium",
                confidence=float(mv_at_limits),
                evidence=f"MV在极限位置时间占比{mv_at_limits*100:.0f}%"
            ))
        
        return issues
    
    def _detect_process_characteristics(self, pv: np.ndarray, mv: np.ndarray,
                                         sv: np.ndarray, dt: float) -> List[IssueType]:
        """检测过程特性"""
        issues = []
        
        # 1. 延迟检测（互相关）
        if len(pv) > 20:
            correlation = np.correlate(pv - np.mean(pv), mv - np.mean(mv), mode='full')
            lag_idx = np.argmax(np.abs(correlation)) - len(pv) + 1
            delay = max(0, lag_idx * dt)
            
            # 估算时间常数（使用方差衰减）
            pv_diff = np.diff(pv)
            tau_estimate = 1 / (np.std(pv_diff) / (np.std(pv) + 1e-6) + 1e-6) * dt
            
            delay_ratio = delay / (tau_estimate + 1e-6)
            
            # 阈值与 test_synthetic_tuning.py 对齐: >0.5(中等), >1.0(大), >2.0(极大)
            if delay_ratio > 2.0:
                issues.append(IssueType(
                    name="extreme_delay",
                    name_cn="极大滞后",
                    severity="high",
                    confidence=min(1.0, delay_ratio / 3.0),
                    evidence=f"L/T1={delay_ratio:.1f}，延迟{delay:.1f}s"
                ))
            elif delay_ratio > 1.0:
                issues.append(IssueType(
                    name="large_delay",
                    name_cn="大滞后",
                    severity="high",
                    confidence=min(1.0, delay_ratio / 2.0),
                    evidence=f"L/T1={delay_ratio:.1f}，延迟{delay:.1f}s"
                ))
            elif delay_ratio > 0.5:
                issues.append(IssueType(
                    name="medium_delay",
                    name_cn="中等滞后",
                    severity="medium",
                    confidence=delay_ratio,
                    evidence=f"L/T1={delay_ratio:.2f}，延迟{delay:.1f}s"
                ))
        
        # 2. 增益变化检测
        half = len(pv) // 2
        if half > 20:
            gain_first = np.std(pv[:half]) / (np.std(mv[:half]) + 1e-6)
            gain_second = np.std(pv[half:]) / (np.std(mv[half:]) + 1e-6)
            gain_ratio = gain_second / (gain_first + 1e-6) if gain_first > 0 else gain_first / (gain_second + 1e-6)
            gain_ratio = max(gain_ratio, 1/gain_ratio) if gain_ratio > 0 else 1.0  # 取较大的变化比
            
            # 阈值与 test_synthetic_tuning.py 对齐: >2x(+1), >5x(+2), >10x(+3)
            if gain_ratio > 10.0:
                issues.append(IssueType(
                    name="gain_change_extreme",
                    name_cn="增益剧变",
                    severity="high",
                    confidence=min(1.0, gain_ratio / 15.0),
                    evidence=f"增益变化{gain_ratio:.0f}倍"
                ))
            elif gain_ratio > 5.0:
                issues.append(IssueType(
                    name="gain_change_large",
                    name_cn="增益大变",
                    severity="high",
                    confidence=min(1.0, gain_ratio / 10.0),
                    evidence=f"增益变化{gain_ratio:.1f}倍"
                ))
            elif gain_ratio > 2.0:
                issues.append(IssueType(
                    name="gain_change_small",
                    name_cn="增益变化",
                    severity="medium",
                    confidence=min(1.0, gain_ratio / 5.0),
                    evidence=f"增益变化{gain_ratio:.1f}倍"
                ))
        
        # 3. 非线性检测
        error = pv - sv
        if len(error) > 30:
            # 正负偏差区域的响应对比
            pos_idx = error > 0
            neg_idx = error < 0
            if np.sum(pos_idx) > 10 and np.sum(neg_idx) > 10:
                try:
                    corr_pos = np.corrcoef(mv[:-1][pos_idx[:-1]], pv_diff[pos_idx[:-1]])[0, 1]
                    corr_neg = np.corrcoef(mv[:-1][neg_idx[:-1]], pv_diff[neg_idx[:-1]])[0, 1]
                    nonlinearity = abs(corr_pos - corr_neg) if not (np.isnan(corr_pos) or np.isnan(corr_neg)) else 0
                    
                    if nonlinearity > 0.4:
                        issues.append(IssueType(
                            name="nonlinearity",
                            name_cn="非线性特性",
                            severity="medium" if nonlinearity > 0.6 else "low",
                            confidence=float(nonlinearity),
                            evidence=f"正负偏差区响应差异{nonlinearity:.2f}"
                        ))
                except Exception:
                    pass
        
        # 4. 积分过程检测
        # 特征：PV 趋势性漂移
        if len(pv) > 50:
            x = np.arange(len(pv))
            try:
                slope, _ = np.polyfit(x, pv, 1)
                drift_rate = abs(slope) * len(pv) / (np.std(pv) + 1e-6)
                
                if drift_rate > 0.5:
                    issues.append(IssueType(
                        name="integrating_process",
                        name_cn="积分过程",
                        severity="medium",
                        confidence=min(1.0, drift_rate),
                        evidence=f"漂移率{drift_rate:.2f}"
                    ))
            except Exception:
                pass
        
        # 5. 反作用检测
        # 特征：MV 增加导致 PV 减少
        mv_pv_corr = np.corrcoef(mv, pv)[0, 1] if len(mv) > 10 else 0
        if mv_pv_corr < -0.3:
            issues.append(IssueType(
                name="reverse_action",
                name_cn="反作用特性",
                severity="low",  # 不是问题，只是需要注意
                confidence=abs(mv_pv_corr),
                evidence=f"MV-PV相关性{mv_pv_corr:.2f}"
            ))
        
        return issues
    
    def _detect_dynamics(self, pv: np.ndarray, mv: np.ndarray, dt: float,
                         loop_type: str) -> List[IssueType]:
        """检测动态特性"""
        issues = []
        
        # 估算响应时间
        pv_diff = np.diff(pv)
        response_rate = np.mean(np.abs(pv_diff)) / dt if dt > 0 else 0
        
        # 根据回路类型判断快慢
        if loop_type == "temperature":
            if response_rate < 0.01:  # 很慢
                issues.append(IssueType(
                    name="slow_dynamics",
                    name_cn="慢动态响应",
                    severity="medium",
                    confidence=0.7,
                    evidence="温度回路响应缓慢，需延长仿真时间"
                ))
        elif loop_type == "flow":
            if response_rate > 1.0:  # 很快
                issues.append(IssueType(
                    name="fast_dynamics",
                    name_cn="快动态响应",
                    severity="low",
                    confidence=0.7,
                    evidence="流量回路响应快速"
                ))
        
        return issues
    
    def _detect_noise(self, pv: np.ndarray, sv: np.ndarray) -> Optional[IssueType]:
        """检测噪声 (阈值与 test_synthetic_tuning.py 对齐: >0.4, >0.8, >1.5)"""
        pv_diff = np.diff(pv)
        noise_ratio = np.std(pv_diff) / (np.std(pv) + 1e-6)
        
        if noise_ratio > 1.5:
            return IssueType(
                name="noise_extreme",
                name_cn="极高噪声",
                severity="high",
                confidence=min(1.0, noise_ratio / 2.0),
                evidence=f"噪声比{noise_ratio:.2f}"
            )
        elif noise_ratio > 0.8:
            return IssueType(
                name="noise_high",
                name_cn="高噪声",
                severity="medium",
                confidence=min(1.0, noise_ratio / 1.5),
                evidence=f"噪声比{noise_ratio:.2f}"
            )
        elif noise_ratio > 0.4:
            return IssueType(
                name="noise_medium",
                name_cn="中等噪声",
                severity="low",
                confidence=noise_ratio,
                evidence=f"噪声比{noise_ratio:.2f}"
            )
        return None
    
    def _calculate_difficulty_score(self, issues: List[IssueType]) -> float:
        """计算难度评分 (1-10)"""
        if not issues:
            return 2.0  # 无明显问题，基础难度
        
        base_score = 2.0
        
        for issue in issues:
            issue_config = ISSUE_TYPES.get(issue.name, {"base_difficulty": 1})
            base_diff = issue_config["base_difficulty"]
            
            # 根据严重程度调整
            severity_multiplier = {"low": 0.6, "medium": 1.0, "high": 1.4}.get(issue.severity, 1.0)
            
            # 根据置信度调整
            contribution = base_diff * severity_multiplier * issue.confidence
            base_score += contribution
        
        return min(10.0, max(1.0, base_score))
    
    def _get_difficulty_level(self, score: float) -> str:
        """获取难度等级"""
        if score <= 3:
            return "easy"
        elif score <= 5:
            return "medium"
        elif score <= 7:
            return "hard"
        else:
            return "extreme"
    
    def _level_to_cn(self, level: str) -> str:
        """难度等级转中文"""
        return {
            "easy": "简单",
            "medium": "中等",
            "hard": "困难",
            "extreme": "极难"
        }.get(level, "未知")
    
    def _issue_to_dict(self, issue: IssueType) -> Dict:
        """Issue 转字典"""
        return {
            "name": issue.name,
            "name_cn": issue.name_cn,
            "severity": issue.severity,
            "confidence": round(issue.confidence, 2),
            "evidence": issue.evidence
        }
    
    def _generate_recommendations(self, issues: List[IssueType], loop_type: str) -> List[str]:
        """生成整定建议"""
        recommendations = []
        
        issue_names = [i.name for i in issues]
        
        if "valve_stiction" in issue_names:
            recommendations.append("阀门粘滞：检查阀门定位器，考虑增大死区补偿")
        
        if "valve_deadband" in issue_names:
            recommendations.append("阀门死区：增大PB避免小幅调节，或调整阀门参数")
        
        # 滞后问题
        if "extreme_delay" in issue_names:
            recommendations.append("极大滞后(L/T1>2)：使用极保守整定，PB增大100-150%，禁用微分")
        elif "large_delay" in issue_names:
            recommendations.append("大滞后(L/T1>1)：使用保守整定，PB增大50-100%，避免使用微分")
        elif "medium_delay" in issue_names:
            recommendations.append("中等滞后(L/T1>0.5)：适当增大PB 30-50%")
        
        # 增益变化
        if any(name in issue_names for name in ["gain_change_extreme", "gain_change_large", "gain_change_small"]):
            recommendations.append("增益变化：考虑增益调度或自适应控制")
        
        if "oscillation_severe" in issue_names:
            recommendations.append("严重振荡：先增大PB 30-50% 消除振荡，再逐步优化")
        
        if "saturation" in issue_names:
            recommendations.append("执行器饱和：检查设定值是否合理，评估执行器容量")
        
        # 噪声问题
        if "noise_extreme" in issue_names:
            recommendations.append("极高噪声：大幅增大Ti，考虑硬件滤波或传感器检修")
        elif "noise_high" in issue_names:
            recommendations.append("高噪声：增大Ti减少调节频率，考虑增加滤波")
        elif "noise_medium" in issue_names:
            recommendations.append("中等噪声：可适当增大Ti")
        
        if "integrating_process" in issue_names:
            recommendations.append("积分/慢系统：使用专用积分过程整定规则（如SIMC）")
        
        if "fast_system" in issue_names:
            recommendations.append("快系统：注意采样频率和执行器响应速度")
        
        if not recommendations:
            recommendations.append("无明显问题，可使用标准Lambda整定方法")
        
        return recommendations
    
    def _generate_summary(self, score: float, issues: List[IssueType]) -> str:
        """生成摘要"""
        level_cn = self._level_to_cn(self._get_difficulty_level(score))
        
        if not issues:
            return f"整定难度: {level_cn} ({score:.1f}/10)，无明显异常特征"
        
        main_issues = [i.name_cn for i in issues if i.severity in ["high", "medium"]][:3]
        if main_issues:
            return f"整定难度: {level_cn} ({score:.1f}/10)，主要问题: {', '.join(main_issues)}"
        else:
            return f"整定难度: {level_cn} ({score:.1f}/10)，存在轻微问题"


# 便捷函数
def analyze_tuning_difficulty(pv, mv, sv, timestamps, loop_type="unknown") -> Dict:
    """便捷函数：分析整定难度"""
    analyzer = TuningDifficultyAnalyzer()
    return analyzer.analyze(
        np.array(pv), np.array(mv), np.array(sv),
        np.array(timestamps), loop_type
    )
