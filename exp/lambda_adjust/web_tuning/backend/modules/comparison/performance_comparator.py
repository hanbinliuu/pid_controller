"""
Performance Comparator - 性能指标对比分析
"""
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime


class PerformanceComparator:
    """性能指标对比分析器"""
    
    def __init__(self):
        self.metrics_weights = {
            'ise': 0.25,      # 积分平方误差
            'iae': 0.20,      # 积分绝对误差
            'overshoot': 0.20,  # 超调量
            'settling_time': 0.20,  # 调节时间
            'rise_time': 0.15   # 上升时间
        }
    
    def compare_performance(
        self,
        performance_list: List[Dict[str, Any]],
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        对比多组性能指标
        
        Args:
            performance_list: 性能指标列表
            labels: 标签列表
            
        Returns:
            对比结果
        """
        if not performance_list or len(performance_list) < 2:
            return {
                'success': False,
                'error': '至少需要2组性能指标进行对比'
            }
        
        if labels is None:
            labels = [f'方案{i+1}' for i in range(len(performance_list))]
        
        result = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'count': len(performance_list),
            'labels': labels,
            'metrics': {},
            'ranking': [],
            'best_in_category': {}
        }
        
        # 提取所有指标
        metric_keys = set()
        for perf in performance_list:
            metric_keys.update(perf.keys())
        
        # 对比每个指标
        for metric in metric_keys:
            values = []
            for perf in performance_list:
                val = perf.get(metric, None)
                if val is not None and isinstance(val, (int, float)):
                    values.append(float(val))
                else:
                    values.append(None)
            
            # 过滤None值进行统计
            valid_values = [v for v in values if v is not None]
            
            if valid_values:
                result['metrics'][metric] = {
                    'values': values,
                    'min': float(np.min(valid_values)),
                    'max': float(np.max(valid_values)),
                    'mean': float(np.mean(valid_values)),
                    'std': float(np.std(valid_values)),
                    'best_index': int(np.argmin(valid_values)) if metric in ['ise', 'iae', 'settling_time', 'rise_time'] else int(np.argmax(valid_values))
                }
                
                # 记录最佳值
                best_idx = result['metrics'][metric]['best_index']
                result['best_in_category'][metric] = {
                    'label': labels[best_idx],
                    'value': valid_values[best_idx],
                    'index': best_idx
                }
        
        # 计算综合得分并排名
        result['ranking'] = self._calculate_ranking(performance_list, labels)
        
        # 生成对比分析
        result['analysis'] = self._generate_performance_analysis(result)
        
        return result
    
    def compare_scenarios(
        self,
        scenarios: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        对比不同场景下的性能
        
        Args:
            scenarios: {
                'scenario1': {'ise': 10.5, 'overshoot': 5.2, ...},
                'scenario2': {'ise': 8.3, 'overshoot': 3.1, ...},
                ...
            }
            
        Returns:
            对比结果
        """
        if not scenarios or len(scenarios) < 2:
            return {
                'success': False,
                'error': '至少需要2个场景进行对比'
            }
        
        labels = list(scenarios.keys())
        performance_list = list(scenarios.values())
        
        return self.compare_performance(performance_list, labels)
    
    def compare_with_baseline(
        self,
        baseline: Dict[str, float],
        current: Dict[str, float],
        baseline_label: str = "基准",
        current_label: str = "当前"
    ) -> Dict[str, Any]:
        """
        与基准性能对比
        
        Args:
            baseline: 基准性能指标
            current: 当前性能指标
            baseline_label: 基准标签
            current_label: 当前标签
            
        Returns:
            对比结果
        """
        result = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'baseline': baseline,
            'current': current,
            'improvements': {},
            'summary': {}
        }
        
        # 计算改进情况
        improved_count = 0
        degraded_count = 0
        unchanged_count = 0
        
        for metric in set(list(baseline.keys()) + list(current.keys())):
            base_val = baseline.get(metric, None)
            curr_val = current.get(metric, None)
            
            if base_val is None or curr_val is None:
                continue
            
            # 判断是越小越好还是越大越好
            is_lower_better = metric in ['ise', 'iae', 'settling_time', 'rise_time', 'overshoot']
            
            change = curr_val - base_val
            change_percent = (change / base_val * 100) if base_val != 0 else 0
            
            if is_lower_better:
                improvement = -change_percent  # 降低是改进
            else:
                improvement = change_percent   # 增加是改进
            
            result['improvements'][metric] = {
                'baseline': float(base_val),
                'current': float(curr_val),
                'change': float(change),
                'change_percent': float(change_percent),
                'improvement_percent': float(improvement),
                'status': 'improved' if improvement > 0 else 'degraded' if improvement < 0 else 'unchanged'
            }
            
            if improvement > 0:
                improved_count += 1
            elif improvement < 0:
                degraded_count += 1
            else:
                unchanged_count += 1
        
        # 生成总结
        result['summary'] = {
            'total_metrics': len(result['improvements']),
            'improved': improved_count,
            'degraded': degraded_count,
            'unchanged': unchanged_count,
            'improvement_rate': (improved_count / len(result['improvements']) * 100) if result['improvements'] else 0
        }
        
        # 生成建议
        result['recommendations'] = self._generate_baseline_recommendations(result)
        
        return result
    
    def _calculate_ranking(
        self,
        performance_list: List[Dict[str, Any]],
        labels: List[str]
    ) -> List[Dict[str, Any]]:
        """计算综合排名"""
        scores = []
        
        for idx, (perf, label) in enumerate(zip(performance_list, labels)):
            # 计算综合得分（归一化后加权）
            score = 0
            weight_sum = 0
            
            for metric, weight in self.metrics_weights.items():
                if metric in perf and perf[metric] is not None:
                    # 简化评分：越小越好的指标取倒数
                    val = perf[metric]
                    if metric in ['ise', 'iae', 'settling_time', 'rise_time', 'overshoot']:
                        # 越小越好，转换为0-100分
                        metric_score = max(0, 100 - val)
                    else:
                        # 越大越好
                        metric_score = min(100, val)
                    
                    score += metric_score * weight
                    weight_sum += weight
            
            if weight_sum > 0:
                score = score / weight_sum
            
            scores.append({
                'index': idx,
                'label': label,
                'score': float(score),
                'metrics': perf
            })
        
        # 排序
        scores.sort(key=lambda x: x['score'], reverse=True)
        
        # 添加排名
        for rank, item in enumerate(scores, 1):
            item['rank'] = rank
        
        return scores
    
    def _generate_performance_analysis(self, result: Dict[str, Any]) -> List[str]:
        """生成性能分析"""
        analysis = []
        
        if not result['ranking']:
            return analysis
        
        best = result['ranking'][0]
        worst = result['ranking'][-1]
        
        analysis.append(f"🏆 最佳方案: {best['label']} (综合得分: {best['score']:.1f})")
        
        if len(result['ranking']) > 1:
            score_diff = best['score'] - worst['score']
            analysis.append(f"📊 最佳与最差方案得分差距: {score_diff:.1f}分")
        
        # 分析各项最佳
        for metric, best_info in result['best_in_category'].items():
            analysis.append(f"✨ {metric}最优: {best_info['label']} ({best_info['value']:.3f})")
        
        return analysis
    
    def _generate_baseline_recommendations(self, result: Dict[str, Any]) -> List[str]:
        """生成基准对比建议"""
        recommendations = []
        
        summary = result['summary']
        improvement_rate = summary['improvement_rate']
        
        if improvement_rate >= 70:
            recommendations.append("✅ 整体性能显著提升，建议采用当前参数")
        elif improvement_rate >= 50:
            recommendations.append("✅ 整体性能有所提升，建议进一步优化")
        elif improvement_rate >= 30:
            recommendations.append("⚠️ 部分指标改善，建议评估关键指标后决策")
        else:
            recommendations.append("❌ 整体性能未明显改善，建议重新整定")
        
        # 分析具体指标
        for metric, improvement in result['improvements'].items():
            if improvement['status'] == 'improved' and abs(improvement['improvement_percent']) > 20:
                recommendations.append(f"✅ {metric}显著改善 ({improvement['improvement_percent']:+.1f}%)")
            elif improvement['status'] == 'degraded' and abs(improvement['improvement_percent']) > 20:
                recommendations.append(f"⚠️ {metric}明显下降 ({improvement['improvement_percent']:+.1f}%)，需要关注")
        
        return recommendations
    
    def calculate_composite_score(
        self,
        metrics: Dict[str, float],
        weights: Optional[Dict[str, float]] = None
    ) -> float:
        """
        计算综合得分
        
        Args:
            metrics: 性能指标字典
            weights: 自定义权重
            
        Returns:
            综合得分 (0-100)
        """
        if weights is None:
            weights = self.metrics_weights
        
        score = 0
        weight_sum = 0
        
        for metric, weight in weights.items():
            if metric in metrics and metrics[metric] is not None:
                val = metrics[metric]
                
                # 归一化到0-100
                if metric in ['ise', 'iae', 'settling_time', 'rise_time', 'overshoot']:
                    metric_score = max(0, 100 - val)
                else:
                    metric_score = min(100, val)
                
                score += metric_score * weight
                weight_sum += weight
        
        if weight_sum > 0:
            return score / weight_sum
        
        return 0.0
