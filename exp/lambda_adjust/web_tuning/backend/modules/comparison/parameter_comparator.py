"""
Parameter Comparator - PID参数对比分析
"""
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime


class ParameterComparator:
    """PID参数对比分析器"""
    
    def __init__(self):
        self.comparison_history = []
    
    def compare_parameters(
        self,
        params_list: List[Dict[str, Any]],
        labels: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        对比多组PID参数
        
        Args:
            params_list: 参数列表 [{'kp': 1.0, 'ki': 0.5, 'kd': 0.1, 'name': 'Original'}, ...]
            labels: 标签列表，如果未提供则使用params中的name或自动生成
            
        Returns:
            对比结果字典
        """
        if not params_list or len(params_list) < 2:
            return {
                'success': False,
                'error': '至少需要2组参数进行对比'
            }
        
        # 提取标签
        if labels is None:
            labels = [p.get('name', f'参数组{i+1}') for i, p in enumerate(params_list)]
        
        # 提取参数值
        kp_values = [p.get('kp', 0) for p in params_list]
        ki_values = [p.get('ki', 0) for p in params_list]
        kd_values = [p.get('kd', 0) for p in params_list]
        
        # 计算统计信息
        comparison_result = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'count': len(params_list),
            'labels': labels,
            'parameters': {
                'kp': {
                    'values': kp_values,
                    'min': float(np.min(kp_values)),
                    'max': float(np.max(kp_values)),
                    'mean': float(np.mean(kp_values)),
                    'std': float(np.std(kp_values)),
                    'range': float(np.max(kp_values) - np.min(kp_values)),
                    'cv': float(np.std(kp_values) / np.mean(kp_values) * 100) if np.mean(kp_values) != 0 else 0
                },
                'ki': {
                    'values': ki_values,
                    'min': float(np.min(ki_values)),
                    'max': float(np.max(ki_values)),
                    'mean': float(np.mean(ki_values)),
                    'std': float(np.std(ki_values)),
                    'range': float(np.max(ki_values) - np.min(ki_values)),
                    'cv': float(np.std(ki_values) / np.mean(ki_values) * 100) if np.mean(ki_values) != 0 else 0
                },
                'kd': {
                    'values': kd_values,
                    'min': float(np.min(kd_values)),
                    'max': float(np.max(kd_values)),
                    'mean': float(np.mean(kd_values)),
                    'std': float(np.std(kd_values)),
                    'range': float(np.max(kd_values) - np.min(kd_values)),
                    'cv': float(np.std(kd_values) / np.mean(kd_values) * 100) if np.mean(kd_values) != 0 else 0
                }
            },
            'details': []
        }
        
        # 详细对比每组参数
        for i, (params, label) in enumerate(zip(params_list, labels)):
            detail = {
                'index': i,
                'label': label,
                'kp': params.get('kp', 0),
                'ki': params.get('ki', 0),
                'kd': params.get('kd', 0),
                'kp_diff_from_mean': float(params.get('kp', 0) - comparison_result['parameters']['kp']['mean']),
                'ki_diff_from_mean': float(params.get('ki', 0) - comparison_result['parameters']['ki']['mean']),
                'kd_diff_from_mean': float(params.get('kd', 0) - comparison_result['parameters']['kd']['mean']),
            }
            
            # 添加额外信息
            if 'method' in params:
                detail['method'] = params['method']
            if 'timestamp' in params:
                detail['timestamp'] = params['timestamp']
            if 'score' in params:
                detail['score'] = params['score']
                
            comparison_result['details'].append(detail)
        
        # 生成对比分析
        comparison_result['analysis'] = self._generate_analysis(comparison_result)
        
        # 保存到历史
        self.comparison_history.append(comparison_result)
        
        return comparison_result
    
    def compare_before_after(
        self,
        original_params: Dict[str, float],
        tuned_params: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        对比整定前后的参数变化
        
        Args:
            original_params: 原始参数 {'kp': 1.0, 'ki': 0.5, 'kd': 0.1}
            tuned_params: 整定后参数
            
        Returns:
            对比结果
        """
        result = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'original': original_params,
            'tuned': tuned_params,
            'changes': {},
            'improvements': []
        }
        
        # 计算变化
        for param in ['kp', 'ki', 'kd']:
            orig = original_params.get(param, 0)
            tuned = tuned_params.get(param, 0)
            
            change = tuned - orig
            change_percent = (change / orig * 100) if orig != 0 else 0
            
            result['changes'][param] = {
                'original': float(orig),
                'tuned': float(tuned),
                'absolute_change': float(change),
                'percent_change': float(change_percent),
                'direction': 'increased' if change > 0 else 'decreased' if change < 0 else 'unchanged'
            }
        
        # 生成改进建议
        result['improvements'] = self._generate_improvement_suggestions(result['changes'])
        
        return result
    
    def compare_methods(
        self,
        method_results: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        对比不同整定方法的结果
        
        Args:
            method_results: {
                'ziegler_nichols': {'kp': 1.0, 'ki': 0.5, 'kd': 0.1, 'score': 85},
                'cohen_coon': {'kp': 1.2, 'ki': 0.6, 'kd': 0.15, 'score': 88},
                ...
            }
            
        Returns:
            对比结果
        """
        if not method_results or len(method_results) < 2:
            return {
                'success': False,
                'error': '至少需要2种方法进行对比'
            }
        
        result = {
            'success': True,
            'timestamp': datetime.now().isoformat(),
            'methods': list(method_results.keys()),
            'count': len(method_results),
            'comparison': {},
            'ranking': []
        }
        
        # 对比每种方法
        for method_name, method_data in method_results.items():
            result['comparison'][method_name] = {
                'kp': method_data.get('kp', 0),
                'ki': method_data.get('ki', 0),
                'kd': method_data.get('kd', 0),
                'score': method_data.get('score', 0),
                'performance': method_data.get('performance', {})
            }
        
        # 排名（基于score）
        ranked = sorted(
            method_results.items(),
            key=lambda x: x[1].get('score', 0),
            reverse=True
        )
        
        for rank, (method_name, method_data) in enumerate(ranked, 1):
            result['ranking'].append({
                'rank': rank,
                'method': method_name,
                'score': method_data.get('score', 0),
                'kp': method_data.get('kp', 0),
                'ki': method_data.get('ki', 0),
                'kd': method_data.get('kd', 0)
            })
        
        # 推荐最佳方法
        if result['ranking']:
            result['recommended'] = result['ranking'][0]['method']
        
        return result
    
    def _generate_analysis(self, comparison_result: Dict[str, Any]) -> List[str]:
        """生成对比分析"""
        analysis = []
        
        params = comparison_result['parameters']
        
        # Kp分析
        kp_cv = params['kp']['cv']
        if kp_cv < 10:
            analysis.append(f"✅ Kp参数变化较小 (变异系数: {kp_cv:.1f}%)，各组参数一致性好")
        elif kp_cv < 30:
            analysis.append(f"⚠️ Kp参数存在中等差异 (变异系数: {kp_cv:.1f}%)，建议关注")
        else:
            analysis.append(f"❌ Kp参数差异较大 (变异系数: {kp_cv:.1f}%)，需要仔细评估")
        
        # Ki分析
        ki_cv = params['ki']['cv']
        if ki_cv < 10:
            analysis.append(f"✅ Ki参数变化较小 (变异系数: {ki_cv:.1f}%)，各组参数一致性好")
        elif ki_cv < 30:
            analysis.append(f"⚠️ Ki参数存在中等差异 (变异系数: {ki_cv:.1f}%)，建议关注")
        else:
            analysis.append(f"❌ Ki参数差异较大 (变异系数: {ki_cv:.1f}%)，需要仔细评估")
        
        # Kd分析
        kd_cv = params['kd']['cv']
        if kd_cv < 10:
            analysis.append(f"✅ Kd参数变化较小 (变异系数: {kd_cv:.1f}%)，各组参数一致性好")
        elif kd_cv < 30:
            analysis.append(f"⚠️ Kd参数存在中等差异 (变异系数: {kd_cv:.1f}%)，建议关注")
        else:
            analysis.append(f"❌ Kd参数差异较大 (变异系数: {kd_cv:.1f}%)，需要仔细评估")
        
        return analysis
    
    def _generate_improvement_suggestions(self, changes: Dict[str, Dict]) -> List[str]:
        """生成改进建议"""
        suggestions = []
        
        for param, change_data in changes.items():
            percent = change_data['percent_change']
            direction = change_data['direction']
            
            if direction == 'unchanged':
                suggestions.append(f"📌 {param.upper()}参数未调整，保持原值")
            elif abs(percent) < 10:
                suggestions.append(f"📊 {param.upper()}参数微调 ({percent:+.1f}%)，属于精细调整")
            elif abs(percent) < 50:
                suggestions.append(f"🔧 {param.upper()}参数中度调整 ({percent:+.1f}%)，建议验证效果")
            else:
                suggestions.append(f"⚠️ {param.upper()}参数大幅调整 ({percent:+.1f}%)，需要充分测试")
        
        return suggestions
    
    def get_comparison_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取对比历史"""
        return self.comparison_history[-limit:]
    
    def clear_history(self):
        """清空历史记录"""
        self.comparison_history.clear()
