"""
整定结果对比器
对比整定前后的PID参数和性能指标
"""

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime


class ResultComparator:
    """PID整定结果对比器"""
    
    def __init__(self):
        self.comparison_data = {}
    
    def compare_results(self,
                       original_pid: Dict[str, float],
                       tuned_pid: Dict[str, float],
                       original_performance: Optional[Dict] = None,
                       tuned_performance: Optional[Dict] = None,
                       pv_original: Optional[np.ndarray] = None,
                       pv_tuned: Optional[np.ndarray] = None,
                       sv: Optional[np.ndarray] = None,
                       mv_original: Optional[np.ndarray] = None,
                       mv_tuned: Optional[np.ndarray] = None,
                       time: Optional[np.ndarray] = None) -> Dict:
        """
        对比整定前后的结果
        
        Args:
            original_pid: 原始PID参数 {'Kp': x, 'Ki': y, 'Kd': z}
            tuned_pid: 整定后PID参数
            original_performance: 原始性能指标（可选）
            tuned_performance: 整定后性能指标（可选）
            pv_original: 原始过程值数据（可选）
            pv_tuned: 整定后过程值数据（可选）
            sv: 设定值数据（可选）
            mv_original: 原始控制输出（可选）
            mv_tuned: 整定后控制输出（可选）
            time: 时间数组（可选）
            
        Returns:
            对比结果字典
        """
        self.comparison_data = {
            'metadata': {
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'comparison_type': 'before_after'
            },
            'pid_comparison': self._compare_pid_parameters(original_pid, tuned_pid),
            'performance_comparison': None,
            'time_domain_analysis': None,
            'improvement_summary': None
        }
        
        # 性能指标对比
        if original_performance and tuned_performance:
            self.comparison_data['performance_comparison'] = self._compare_performance_metrics(
                original_performance, tuned_performance
            )
        
        # 时域分析对比
        if pv_original is not None and pv_tuned is not None and sv is not None:
            self.comparison_data['time_domain_analysis'] = self._analyze_time_domain(
                pv_original, pv_tuned, sv, mv_original, mv_tuned, time
            )
        
        # 生成改进总结
        self.comparison_data['improvement_summary'] = self._generate_improvement_summary()
        
        return self.comparison_data
    
    def _compare_pid_parameters(self, original: Dict, tuned: Dict) -> Dict:
        """对比PID参数"""
        comparison = {
            'original': original.copy(),
            'tuned': tuned.copy(),
            'changes': {},
            'change_summary': []
        }
        
        for key in ['Kp', 'Ki', 'Kd']:
            if key in original and key in tuned:
                orig_val = float(original[key])
                tuned_val = float(tuned[key])
                
                abs_change = tuned_val - orig_val
                if orig_val != 0:
                    pct_change = (abs_change / orig_val) * 100
                else:
                    pct_change = 0 if tuned_val == 0 else float('inf')
                
                comparison['changes'][key] = {
                    'absolute': round(abs_change, 4),
                    'percentage': round(pct_change, 2),
                    'direction': 'increased' if abs_change > 0 else ('decreased' if abs_change < 0 else 'unchanged')
                }
                
                # 生成变化摘要
                if abs(pct_change) > 5:  # 变化超过5%才记录
                    direction = '增加' if abs_change > 0 else '减少'
                    comparison['change_summary'].append(
                        f"{key} {direction} {abs(pct_change):.1f}% (从 {orig_val:.4f} 到 {tuned_val:.4f})"
                    )
        
        return comparison
    
    def _compare_performance_metrics(self, original: Dict, tuned: Dict) -> Dict:
        """对比性能指标"""
        comparison = {
            'original': {},
            'tuned': {},
            'improvements': {},
            'improvement_summary': []
        }
        
        # 定义需要对比的指标（值越小越好的指标）
        lower_is_better = ['steady_state_error', 'iae', 'ise', 'tv', 'oscillation_count', 'overshoot']
        
        # 提取overall性能
        orig_overall = original.get('overall', {})
        tuned_overall = tuned.get('overall', {})
        
        comparison['original'] = orig_overall.copy()
        comparison['tuned'] = tuned_overall.copy()
        
        # 对比评分
        if 'score' in orig_overall and 'score' in tuned_overall:
            orig_score = float(orig_overall['score'])
            tuned_score = float(tuned_overall['score'])
            score_improvement = tuned_score - orig_score
            
            comparison['improvements']['score'] = {
                'original': orig_score,
                'tuned': tuned_score,
                'absolute_change': round(score_improvement, 2),
                'percentage_change': round((score_improvement / orig_score * 100) if orig_score > 0 else 0, 2),
                'improved': score_improvement > 0
            }
            
            if abs(score_improvement) > 1:
                direction = '提升' if score_improvement > 0 else '下降'
                comparison['improvement_summary'].append(
                    f"综合评分{direction} {abs(score_improvement):.1f}分 ({orig_score:.1f} → {tuned_score:.1f})"
                )
        
        # 对比具体指标
        for metric in lower_is_better:
            if metric in orig_overall and metric in tuned_overall:
                orig_val = float(orig_overall[metric])
                tuned_val = float(tuned_overall[metric])
                
                if orig_val > 0:
                    improvement_pct = ((orig_val - tuned_val) / orig_val) * 100
                    
                    comparison['improvements'][metric] = {
                        'original': orig_val,
                        'tuned': tuned_val,
                        'improvement_percentage': round(improvement_pct, 2),
                        'improved': tuned_val < orig_val
                    }
                    
                    if abs(improvement_pct) > 10:  # 改进超过10%才记录
                        direction = '降低' if improvement_pct > 0 else '增加'
                        comparison['improvement_summary'].append(
                            f"{metric} {direction} {abs(improvement_pct):.1f}%"
                        )
        
        return comparison
    
    def _analyze_time_domain(self, 
                            pv_original: np.ndarray,
                            pv_tuned: np.ndarray,
                            sv: np.ndarray,
                            mv_original: Optional[np.ndarray],
                            mv_tuned: Optional[np.ndarray],
                            time: Optional[np.ndarray]) -> Dict:
        """时域分析对比"""
        analysis = {
            'error_analysis': {},
            'response_analysis': {},
            'control_effort_analysis': {}
        }
        
        # 误差分析
        error_original = pv_original - sv
        error_tuned = pv_tuned - sv
        
        analysis['error_analysis'] = {
            'original': {
                'mean_error': float(np.mean(np.abs(error_original))),
                'max_error': float(np.max(np.abs(error_original))),
                'std_error': float(np.std(error_original))
            },
            'tuned': {
                'mean_error': float(np.mean(np.abs(error_tuned))),
                'max_error': float(np.max(np.abs(error_tuned))),
                'std_error': float(np.std(error_tuned))
            }
        }
        
        # 计算改进百分比
        orig_mae = analysis['error_analysis']['original']['mean_error']
        tuned_mae = analysis['error_analysis']['tuned']['mean_error']
        if orig_mae > 0:
            error_improvement = ((orig_mae - tuned_mae) / orig_mae) * 100
            analysis['error_analysis']['improvement_percentage'] = round(error_improvement, 2)
        
        # 响应分析（如果有时间数据）
        if time is not None and len(time) > 0:
            # 计算稳定时间（误差小于5%的时间）
            sv_mean = np.mean(sv)
            threshold = 0.05 * sv_mean if sv_mean > 0 else 0.05
            
            # 原始稳定时间
            stable_original = np.where(np.abs(error_original) < threshold)[0]
            settling_time_original = float(time[stable_original[0]]) if len(stable_original) > 0 else float(time[-1])
            
            # 整定后稳定时间
            stable_tuned = np.where(np.abs(error_tuned) < threshold)[0]
            settling_time_tuned = float(time[stable_tuned[0]]) if len(stable_tuned) > 0 else float(time[-1])
            
            analysis['response_analysis'] = {
                'settling_time_original': settling_time_original,
                'settling_time_tuned': settling_time_tuned,
                'improvement': settling_time_original - settling_time_tuned
            }
        
        # 控制量分析
        if mv_original is not None and mv_tuned is not None:
            analysis['control_effort_analysis'] = {
                'original': {
                    'mean_mv': float(np.mean(mv_original)),
                    'std_mv': float(np.std(mv_original)),
                    'total_variation': float(np.sum(np.abs(np.diff(mv_original))))
                },
                'tuned': {
                    'mean_mv': float(np.mean(mv_tuned)),
                    'std_mv': float(np.std(mv_tuned)),
                    'total_variation': float(np.sum(np.abs(np.diff(mv_tuned))))
                }
            }
        
        return analysis
    
    def _generate_improvement_summary(self) -> Dict:
        """生成改进总结"""
        summary = {
            'overall_assessment': '',
            'key_improvements': [],
            'concerns': [],
            'recommendation': ''
        }
        
        # 从PID参数变化总结
        pid_comp = self.comparison_data.get('pid_comparison', {})
        if pid_comp.get('change_summary'):
            summary['key_improvements'].extend(pid_comp['change_summary'])
        
        # 从性能指标总结
        perf_comp = self.comparison_data.get('performance_comparison', {})
        if perf_comp and perf_comp.get('improvement_summary'):
            summary['key_improvements'].extend(perf_comp['improvement_summary'])
        
        # 评估整体改进
        if perf_comp and 'improvements' in perf_comp:
            score_imp = perf_comp['improvements'].get('score', {})
            if score_imp.get('improved'):
                score_change = score_imp.get('absolute_change', 0)
                if score_change > 10:
                    summary['overall_assessment'] = '显著改进'
                    summary['recommendation'] = '强烈建议采用整定后的参数'
                elif score_change > 5:
                    summary['overall_assessment'] = '明显改进'
                    summary['recommendation'] = '建议采用整定后的参数'
                else:
                    summary['overall_assessment'] = '轻微改进'
                    summary['recommendation'] = '可以考虑采用整定后的参数'
            else:
                summary['overall_assessment'] = '性能下降'
                summary['recommendation'] = '不建议采用整定后的参数，需要重新整定'
                summary['concerns'].append('整定后评分低于原始评分')
        else:
            summary['overall_assessment'] = '无法评估'
            summary['recommendation'] = '缺少性能指标，建议进行完整测试'
        
        # 检查是否有负面影响
        if perf_comp and 'improvements' in perf_comp:
            for metric, data in perf_comp['improvements'].items():
                if metric != 'score' and not data.get('improved', True):
                    summary['concerns'].append(f'{metric}指标变差')
        
        return summary
    
    def print_summary(self):
        """打印对比摘要"""
        if not self.comparison_data:
            print("⚠️ 没有对比数据")
            return
        
        print("\n" + "="*60)
        print("PID整定性能对比摘要")
        print("="*60)
        
        # PID参数变化
        pid_comp = self.comparison_data.get('pid_comparison', {})
        if pid_comp.get('change_summary'):
            print("\n📊 PID参数变化:")
            for change in pid_comp['change_summary']:
                print(f"   • {change}")
        
        # 性能改进
        perf_comp = self.comparison_data.get('performance_comparison', {})
        if perf_comp and perf_comp.get('improvement_summary'):
            print("\n📈 性能改进:")
            for improvement in perf_comp['improvement_summary']:
                print(f"   • {improvement}")
        
        # 整体评估
        summary = self.comparison_data.get('improvement_summary', {})
        if summary:
            print(f"\n🎯 整体评估: {summary.get('overall_assessment', '未知')}")
            
            if summary.get('concerns'):
                print("\n⚠️  需要注意:")
                for concern in summary['concerns']:
                    print(f"   • {concern}")
            
            print(f"\n💡 建议: {summary.get('recommendation', '无')}")
        
        print("="*60 + "\n")
    
    def export_to_dict(self) -> Dict:
        """导出为字典"""
        return self.comparison_data.copy()
