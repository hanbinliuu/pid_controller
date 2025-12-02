"""
PID评估器集成示例
演示如何将PIDEvaluator集成到现有的system_tuning流程中
"""
import sys
import os
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

# 使用importlib导入evaluator模块（避免core模块冲突）
import importlib.util
current_dir = os.path.dirname(os.path.abspath(__file__))
tests_dir = os.path.dirname(current_dir)  # tests目录
system_tuning_dir = os.path.dirname(tests_dir)  # system_tuning目录
evaluator_path = os.path.join(system_tuning_dir, 'core', 'pid', 'evaluator.py')

spec = importlib.util.spec_from_file_location("pid_evaluator", evaluator_path)
pid_evaluator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pid_evaluator_module)

PIDEvaluator = pid_evaluator_module.PIDEvaluator
EvaluationMetrics = pid_evaluator_module.EvaluationMetrics


class EnhancedSystemTuner:
    """
    增强的系统整定器
    在原有整定流程基础上增加参数评估功能
    """
    
    def __init__(self):
        self.evaluator = PIDEvaluator(
            settling_band=0.02,
            settling_duration=50
        )
        self.tuning_history = []
        self.evaluation_history = []
    
    def tune_and_evaluate(self,
                         pv: np.ndarray,
                         sv: np.ndarray,
                         cv: np.ndarray,
                         segment_start: int,
                         segment_end: int,
                         new_pid_params: Dict[str, float],
                         segment_name: str = "") -> Tuple[Dict, EvaluationMetrics]:
        """
        整定并评估PID参数
        
        Args:
            pv, sv, cv: 过程数据
            segment_start, segment_end: 评估段范围
            new_pid_params: 新的PID参数 {'kp': x, 'ki': y, 'kd': z}
            segment_name: 段名称
            
        Returns:
            (参数字典, 评估指标)
        """
        # 评估新参数的性能
        metrics = self.evaluator.evaluate(
            pv, sv, cv,
            segment_start=segment_start,
            segment_end=segment_end
        )
        
        # 记录历史
        tuning_record = {
            'segment_name': segment_name,
            'segment_range': (segment_start, segment_end),
            'pid_params': new_pid_params.copy(),
            'metrics': metrics,
            'timestamp': pd.Timestamp.now()
        }
        
        self.tuning_history.append(tuning_record)
        self.evaluation_history.append(metrics)
        
        return new_pid_params, metrics
    
    def compare_with_baseline(self,
                             baseline_pv: np.ndarray,
                             baseline_sv: np.ndarray,
                             baseline_cv: np.ndarray,
                             tuned_pv: np.ndarray,
                             tuned_sv: np.ndarray,
                             tuned_cv: np.ndarray,
                             baseline_params: Dict[str, float],
                             tuned_params: Dict[str, float]) -> Dict:
        """
        比较基线参数和整定后参数的性能
        
        Args:
            baseline_*: 基线参数的响应数据
            tuned_*: 整定后参数的响应数据
            baseline_params: 基线PID参数
            tuned_params: 整定后PID参数
            
        Returns:
            比较结果字典
        """
        # 评估基线
        baseline_metrics = self.evaluator.evaluate(baseline_pv, baseline_sv, baseline_cv)
        
        # 评估整定后
        tuned_metrics = self.evaluator.evaluate(tuned_pv, tuned_sv, tuned_cv)
        
        # 计算改进百分比
        improvements = {
            'overshoot': self._calc_improvement(
                baseline_metrics.overshoot, 
                tuned_metrics.overshoot, 
                lower_is_better=True
            ),
            'settling_time': self._calc_improvement(
                baseline_metrics.settling_time,
                tuned_metrics.settling_time,
                lower_is_better=True
            ),
            'steady_state_error': self._calc_improvement(
                baseline_metrics.steady_state_error,
                tuned_metrics.steady_state_error,
                lower_is_better=True
            ),
            'iae': self._calc_improvement(
                baseline_metrics.iae,
                tuned_metrics.iae,
                lower_is_better=True
            ),
            'overall_score': self._calc_improvement(
                baseline_metrics.overall_score,
                tuned_metrics.overall_score,
                lower_is_better=False
            )
        }
        
        return {
            'baseline': {
                'params': baseline_params,
                'metrics': baseline_metrics.to_dict(),
                'score': baseline_metrics.overall_score,
                'grade': baseline_metrics.grade
            },
            'tuned': {
                'params': tuned_params,
                'metrics': tuned_metrics.to_dict(),
                'score': tuned_metrics.overall_score,
                'grade': tuned_metrics.grade
            },
            'improvements': improvements,
            'is_better': tuned_metrics.overall_score > baseline_metrics.overall_score
        }
    
    def _calc_improvement(self, baseline: float, tuned: float, lower_is_better: bool = True) -> float:
        """计算改进百分比"""
        if baseline == 0:
            return 0.0
        
        if lower_is_better:
            # 数值越小越好（如误差）
            improvement = (baseline - tuned) / baseline * 100
        else:
            # 数值越大越好（如评分）
            improvement = (tuned - baseline) / baseline * 100
        
        return improvement
    
    def select_best_parameters(self,
                              candidate_params: List[Dict[str, float]],
                              pv_responses: List[np.ndarray],
                              sv_responses: List[np.ndarray],
                              cv_responses: List[np.ndarray]) -> Tuple[Dict, EvaluationMetrics, int]:
        """
        从多组候选参数中选择最佳参数
        
        Args:
            candidate_params: 候选参数列表
            pv_responses: 对应的PV响应列表
            sv_responses: 对应的SV响应列表
            cv_responses: 对应的CV响应列表
            
        Returns:
            (最佳参数, 最佳评估指标, 最佳参数索引)
        """
        best_score = -1
        best_idx = 0
        best_params = None
        best_metrics = None
        
        for i, (params, pv, sv, cv) in enumerate(zip(
            candidate_params, pv_responses, sv_responses, cv_responses
        )):
            metrics = self.evaluator.evaluate(pv, sv, cv)
            
            if metrics.overall_score > best_score:
                best_score = metrics.overall_score
                best_idx = i
                best_params = params
                best_metrics = metrics
        
        return best_params, best_metrics, best_idx
    
    def generate_tuning_report(self) -> str:
        """生成整定历史报告"""
        if not self.tuning_history:
            return "暂无整定历史记录"
        
        report = """
╔══════════════════════════════════════════════════════════════╗
║                    PID整定历史报告                            ║
╚══════════════════════════════════════════════════════════════╝

"""
        for i, record in enumerate(self.tuning_history, 1):
            params = record['pid_params']
            metrics = record['metrics']
            
            report += f"""
【整定记录 {i}】
  段名称: {record['segment_name']}
  时间范围: {record['segment_range']}
  PID参数: Kp={params.get('kp', 'N/A'):.4f}, Ki={params.get('ki', 'N/A'):.4f}, Kd={params.get('kd', 'N/A'):.4f}
  
  性能评估:
    综合评分: {metrics.overall_score:.2f} ({metrics.grade})
    超调量:   {metrics.overshoot:.2f}%
    调节时间: {metrics.settling_time:.1f} 点
    稳态误差: {metrics.steady_state_error:.4f}
    IAE:      {metrics.iae:.4f}
    
  时间: {record['timestamp']}
{'─' * 62}
"""
        
        # 添加趋势分析
        if len(self.evaluation_history) > 1:
            scores = [m.overall_score for m in self.evaluation_history]
            avg_score = np.mean(scores)
            trend = "上升" if scores[-1] > scores[0] else "下降"
            
            report += f"""
【趋势分析】
  平均评分: {avg_score:.2f}
  评分趋势: {trend}
  最高评分: {max(scores):.2f}
  最低评分: {min(scores):.2f}
"""
        
        return report
    
    def get_tuning_summary(self) -> Dict:
        """获取整定摘要统计"""
        if not self.evaluation_history:
            return {}
        
        scores = [m.overall_score for m in self.evaluation_history]
        overshoots = [m.overshoot for m in self.evaluation_history]
        settling_times = [m.settling_time for m in self.evaluation_history]
        sse_values = [m.steady_state_error for m in self.evaluation_history]
        
        return {
            'total_tunings': len(self.tuning_history),
            'average_score': np.mean(scores),
            'best_score': max(scores),
            'worst_score': min(scores),
            'average_overshoot': np.mean(overshoots),
            'average_settling_time': np.mean(settling_times),
            'average_sse': np.mean(sse_values),
            'grade_distribution': {
                'A': sum(1 for m in self.evaluation_history if m.grade == 'A'),
                'B': sum(1 for m in self.evaluation_history if m.grade == 'B'),
                'C': sum(1 for m in self.evaluation_history if m.grade == 'C'),
                'D': sum(1 for m in self.evaluation_history if m.grade == 'D'),
                'F': sum(1 for m in self.evaluation_history if m.grade == 'F'),
            }
        }


def example_integration():
    """集成使用示例"""
    print("=" * 70)
    print("PID评估器集成示例")
    print("=" * 70)
    
    # 创建增强的整定器
    tuner = EnhancedSystemTuner()
    
    # 模拟场景：有3个扰动段需要整定
    print("\n【场景】检测到3个扰动段，需要分别整定和评估\n")
    
    # 模拟数据（实际使用时从真实数据或模拟器获取）
    np.random.seed(42)
    
    # 段1: 保守参数
    pv1 = np.random.randn(300) * 0.5 + 10
    sv1 = np.ones(300) * 10
    cv1 = np.random.randn(300) * 2 + 50
    
    params1 = {'kp': 0.8, 'ki': 0.05, 'kd': 0.03}
    tuner.tune_and_evaluate(pv1, sv1, cv1, 0, 300, params1, "扰动段1")
    
    # 段2: 中等参数
    pv2 = np.random.randn(300) * 0.3 + 20
    sv2 = np.ones(300) * 20
    cv2 = np.random.randn(300) * 1.5 + 60
    
    params2 = {'kp': 1.2, 'ki': 0.08, 'kd': 0.05}
    tuner.tune_and_evaluate(pv2, sv2, cv2, 300, 600, params2, "扰动段2")
    
    # 段3: 激进参数
    pv3 = np.random.randn(400) * 0.4 + 15
    sv3 = np.ones(400) * 15
    cv3 = np.random.randn(400) * 3 + 55
    
    params3 = {'kp': 1.8, 'ki': 0.12, 'kd': 0.08}
    tuner.tune_and_evaluate(pv3, sv3, cv3, 600, 1000, params3, "扰动段3")
    
    # 打印整定报告
    print(tuner.generate_tuning_report())
    
    # 打印摘要统计
    summary = tuner.get_tuning_summary()
    print("\n【整定摘要统计】")
    print(f"  总整定次数: {summary['total_tunings']}")
    print(f"  平均评分: {summary['average_score']:.2f}")
    print(f"  最佳评分: {summary['best_score']:.2f}")
    print(f"  平均超调: {summary['average_overshoot']:.2f}%")
    print(f"  平均调节时间: {summary['average_settling_time']:.1f} 点")
    print(f"\n  等级分布:")
    for grade, count in summary['grade_distribution'].items():
        if count > 0:
            print(f"    {grade}: {count} 次")


def example_baseline_comparison():
    """基线对比示例"""
    print("\n" + "=" * 70)
    print("基线参数对比示例")
    print("=" * 70)
    
    tuner = EnhancedSystemTuner()
    
    # 模拟基线和整定后的数据
    np.random.seed(42)
    
    # 基线参数（较差）
    baseline_pv = np.random.randn(500) * 1.0 + 10
    baseline_sv = np.ones(500) * 10
    baseline_cv = np.random.randn(500) * 5 + 50
    baseline_params = {'kp': 0.5, 'ki': 0.03, 'kd': 0.01}
    
    # 整定后参数（较好）
    tuned_pv = np.random.randn(500) * 0.3 + 10
    tuned_sv = np.ones(500) * 10
    tuned_cv = np.random.randn(500) * 2 + 50
    tuned_params = {'kp': 1.2, 'ki': 0.08, 'kd': 0.05}
    
    # 比较
    comparison = tuner.compare_with_baseline(
        baseline_pv, baseline_sv, baseline_cv,
        tuned_pv, tuned_sv, tuned_cv,
        baseline_params, tuned_params
    )
    
    # 打印结果
    print("\n【基线参数】")
    print(f"  Kp={baseline_params['kp']}, Ki={baseline_params['ki']}, Kd={baseline_params['kd']}")
    print(f"  评分: {comparison['baseline']['score']:.2f} ({comparison['baseline']['grade']})")
    
    print("\n【整定后参数】")
    print(f"  Kp={tuned_params['kp']}, Ki={tuned_params['ki']}, Kd={tuned_params['kd']}")
    print(f"  评分: {comparison['tuned']['score']:.2f} ({comparison['tuned']['grade']})")
    
    print("\n【改进情况】")
    improvements = comparison['improvements']
    for metric, improvement in improvements.items():
        symbol = "↑" if improvement > 0 else "↓"
        print(f"  {metric:20s}: {symbol} {abs(improvement):6.2f}%")
    
    if comparison['is_better']:
        print("\n✓ 整定后参数性能更优！")
    else:
        print("\n✗ 整定后参数性能未改善")


if __name__ == '__main__':
    example_integration()
    example_baseline_comparison()
    
    print("\n" + "=" * 70)
    print("集成示例运行完成！")
    print("=" * 70)
