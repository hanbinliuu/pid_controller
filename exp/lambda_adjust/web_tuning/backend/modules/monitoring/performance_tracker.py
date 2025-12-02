"""
Performance Tracker - 性能跟踪器
"""
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from collections import deque


class PerformanceTracker:
    """性能跟踪器 - 持续跟踪和评估控制性能"""
    
    def __init__(self, window_size: int = 300):
        """
        初始化性能跟踪器
        
        Args:
            window_size: 滑动窗口大小（用于计算性能指标）
        """
        self.window_size = window_size
        self.trackers: Dict[str, Dict[str, Any]] = {}
    
    def create_tracker(
        self,
        loop_id: str,
        loop_name: str,
        target_metrics: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        创建性能跟踪器
        
        Args:
            loop_id: 回路ID
            loop_name: 回路名称
            target_metrics: 目标性能指标 {'ise': 10.0, 'overshoot': 5.0, ...}
            
        Returns:
            创建结果
        """
        if loop_id in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器已存在: {loop_id}'
            }
        
        self.trackers[loop_id] = {
            'loop_id': loop_id,
            'loop_name': loop_name,
            'created_at': datetime.now().isoformat(),
            'target_metrics': target_metrics or {},
            'performance_history': [],
            'current_window': {
                'pv': deque(maxlen=self.window_size),
                'sv': deque(maxlen=self.window_size),
                'mv': deque(maxlen=self.window_size),
                'error': deque(maxlen=self.window_size),
                'time': deque(maxlen=self.window_size)
            },
            'metrics': {},
            'trends': {},
            'quality_score': 0.0
        }
        
        return {
            'success': True,
            'loop_id': loop_id,
            'message': f'性能跟踪器创建成功: {loop_name}'
        }
    
    def update_data(
        self,
        loop_id: str,
        timestamp: float,
        pv: float,
        sv: float,
        mv: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        更新数据并计算性能指标
        
        Args:
            loop_id: 回路ID
            timestamp: 时间戳
            pv: 过程变量
            sv: 设定值
            mv: 操纵变量
            
        Returns:
            更新结果
        """
        if loop_id not in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器不存在: {loop_id}'
            }
        
        tracker = self.trackers[loop_id]
        window = tracker['current_window']
        
        # 添加数据到窗口
        window['time'].append(timestamp)
        window['pv'].append(pv)
        window['sv'].append(sv)
        if mv is not None:
            window['mv'].append(mv)
        
        error = sv - pv
        window['error'].append(error)
        
        # 如果窗口已满，计算性能指标
        if len(window['pv']) >= self.window_size:
            metrics = self._calculate_performance_metrics(tracker)
            tracker['metrics'] = metrics
            
            # 保存到历史
            tracker['performance_history'].append({
                'timestamp': datetime.now().isoformat(),
                'metrics': metrics
            })
            
            # 限制历史记录数量
            if len(tracker['performance_history']) > 100:
                tracker['performance_history'] = tracker['performance_history'][-100:]
            
            # 计算趋势
            tracker['trends'] = self._calculate_trends(tracker)
            
            # 计算质量得分
            tracker['quality_score'] = self._calculate_quality_score(tracker)
        
        return {
            'success': True,
            'loop_id': loop_id,
            'window_filled': len(window['pv']) >= self.window_size,
            'metrics': tracker['metrics']
        }
    
    def get_performance(self, loop_id: str) -> Dict[str, Any]:
        """获取当前性能指标"""
        if loop_id not in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器不存在: {loop_id}'
            }
        
        tracker = self.trackers[loop_id]
        
        return {
            'success': True,
            'loop_id': loop_id,
            'loop_name': tracker['loop_name'],
            'metrics': tracker['metrics'],
            'quality_score': tracker['quality_score'],
            'trends': tracker['trends'],
            'target_metrics': tracker['target_metrics']
        }
    
    def get_performance_history(
        self,
        loop_id: str,
        limit: int = 50
    ) -> Dict[str, Any]:
        """获取性能历史"""
        if loop_id not in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器不存在: {loop_id}'
            }
        
        tracker = self.trackers[loop_id]
        history = tracker['performance_history'][-limit:]
        
        return {
            'success': True,
            'loop_id': loop_id,
            'history': history,
            'count': len(history)
        }
    
    def get_quality_assessment(self, loop_id: str) -> Dict[str, Any]:
        """获取控制质量评估"""
        if loop_id not in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器不存在: {loop_id}'
            }
        
        tracker = self.trackers[loop_id]
        metrics = tracker['metrics']
        
        if not metrics:
            return {
                'success': True,
                'loop_id': loop_id,
                'assessment': '数据不足，无法评估'
            }
        
        # 生成评估报告
        assessment = {
            'overall_score': tracker['quality_score'],
            'rating': self._get_rating(tracker['quality_score']),
            'strengths': [],
            'weaknesses': [],
            'recommendations': []
        }
        
        # 分析各项指标
        if 'ise' in metrics:
            if metrics['ise'] < 50:
                assessment['strengths'].append('误差积分较小，控制精度高')
            elif metrics['ise'] > 200:
                assessment['weaknesses'].append('误差积分较大，控制精度不足')
                assessment['recommendations'].append('建议优化PID参数以减小误差')
        
        if 'overshoot' in metrics:
            if metrics['overshoot'] < 5:
                assessment['strengths'].append('超调量小，响应平稳')
            elif metrics['overshoot'] > 20:
                assessment['weaknesses'].append('超调量较大')
                assessment['recommendations'].append('建议降低Kp或增加Kd以减小超调')
        
        if 'settling_time' in metrics:
            if metrics['settling_time'] < 50:
                assessment['strengths'].append('调节时间短，响应快速')
            elif metrics['settling_time'] > 150:
                assessment['weaknesses'].append('调节时间过长')
                assessment['recommendations'].append('建议增加Ki以加快响应')
        
        if 'oscillation_index' in metrics:
            if metrics['oscillation_index'] < 0.1:
                assessment['strengths'].append('振荡小，控制稳定')
            elif metrics['oscillation_index'] > 0.3:
                assessment['weaknesses'].append('存在明显振荡')
                assessment['recommendations'].append('建议降低Kp和Kd以减小振荡')
        
        # 趋势分析
        trends = tracker['trends']
        if trends:
            if trends.get('quality_trend') == 'improving':
                assessment['strengths'].append('控制质量持续改善')
            elif trends.get('quality_trend') == 'degrading':
                assessment['weaknesses'].append('控制质量下降')
                assessment['recommendations'].append('建议检查系统状态或重新整定参数')
        
        return {
            'success': True,
            'loop_id': loop_id,
            'loop_name': tracker['loop_name'],
            'assessment': assessment
        }
    
    def compare_with_target(self, loop_id: str) -> Dict[str, Any]:
        """与目标性能对比"""
        if loop_id not in self.trackers:
            return {
                'success': False,
                'error': f'跟踪器不存在: {loop_id}'
            }
        
        tracker = self.trackers[loop_id]
        current_metrics = tracker['metrics']
        target_metrics = tracker['target_metrics']
        
        if not target_metrics:
            return {
                'success': False,
                'error': '未设置目标性能指标'
            }
        
        if not current_metrics:
            return {
                'success': False,
                'error': '当前性能数据不足'
            }
        
        comparison = {
            'loop_id': loop_id,
            'metrics_comparison': {},
            'achievement_rate': 0.0,
            'status': 'unknown'
        }
        
        achieved_count = 0
        total_count = 0
        
        for metric, target_value in target_metrics.items():
            if metric in current_metrics:
                current_value = current_metrics[metric]
                
                # 判断是否达标（假设越小越好）
                is_achieved = current_value <= target_value
                achievement = (target_value / current_value * 100) if current_value > 0 else 100
                
                comparison['metrics_comparison'][metric] = {
                    'target': target_value,
                    'current': current_value,
                    'achieved': is_achieved,
                    'achievement_percent': min(100, achievement),
                    'gap': current_value - target_value
                }
                
                if is_achieved:
                    achieved_count += 1
                total_count += 1
        
        if total_count > 0:
            comparison['achievement_rate'] = achieved_count / total_count * 100
            
            if comparison['achievement_rate'] >= 80:
                comparison['status'] = 'excellent'
            elif comparison['achievement_rate'] >= 60:
                comparison['status'] = 'good'
            elif comparison['achievement_rate'] >= 40:
                comparison['status'] = 'fair'
            else:
                comparison['status'] = 'poor'
        
        return {
            'success': True,
            **comparison
        }
    
    def _calculate_performance_metrics(self, tracker: Dict[str, Any]) -> Dict[str, Any]:
        """计算性能指标"""
        window = tracker['current_window']
        
        pv_array = np.array(list(window['pv']))
        sv_array = np.array(list(window['sv']))
        error_array = np.array(list(window['error']))
        time_array = np.array(list(window['time']))
        
        metrics = {}
        
        # 基本误差指标
        metrics['iae'] = float(np.sum(np.abs(error_array)))
        metrics['ise'] = float(np.sum(error_array ** 2))
        metrics['itae'] = float(np.sum(np.abs(error_array) * time_array))
        
        # 统计指标
        metrics['mean_error'] = float(np.mean(error_array))
        metrics['std_error'] = float(np.std(error_array))
        metrics['max_error'] = float(np.max(np.abs(error_array)))
        
        # 超调量
        if len(sv_array) > 0:
            mean_sv = np.mean(sv_array)
            if mean_sv != 0:
                overshoot = (np.max(pv_array) - mean_sv) / abs(mean_sv) * 100
                metrics['overshoot'] = float(max(0, overshoot))
        
        # 调节时间（简化计算：误差进入±5%范围的时间）
        if len(sv_array) > 0:
            mean_sv = np.mean(sv_array)
            tolerance = abs(mean_sv) * 0.05
            
            # 从后往前找第一个超出容差的点
            settling_idx = len(error_array)
            for i in range(len(error_array) - 1, -1, -1):
                if abs(error_array[i]) > tolerance:
                    settling_idx = i + 1
                    break
            
            metrics['settling_time'] = float(settling_idx)
        
        # 振荡指数（标准差与均值的比值）
        if abs(np.mean(pv_array)) > 0:
            metrics['oscillation_index'] = float(np.std(pv_array) / abs(np.mean(pv_array)))
        
        # MV相关指标
        if len(window['mv']) > 0:
            mv_array = np.array(list(window['mv']))
            metrics['mv_mean'] = float(np.mean(mv_array))
            metrics['mv_std'] = float(np.std(mv_array))
            
            # MV变化率
            if len(mv_array) > 1:
                mv_changes = np.abs(np.diff(mv_array))
                metrics['mv_variability'] = float(np.mean(mv_changes))
        
        return metrics
    
    def _calculate_trends(self, tracker: Dict[str, Any]) -> Dict[str, Any]:
        """计算性能趋势"""
        history = tracker['performance_history']
        
        if len(history) < 3:
            return {}
        
        # 提取最近的质量得分
        recent_scores = [h.get('metrics', {}).get('ise', 0) for h in history[-10:]]
        
        if len(recent_scores) < 2:
            return {}
        
        # 简单趋势判断
        score_trend = np.mean(np.diff(recent_scores))
        
        trends = {
            'quality_trend': 'improving' if score_trend < 0 else 'degrading' if score_trend > 0 else 'stable',
            'trend_value': float(score_trend)
        }
        
        return trends
    
    def _calculate_quality_score(self, tracker: Dict[str, Any]) -> float:
        """计算控制质量综合得分 (0-100)"""
        metrics = tracker['metrics']
        
        if not metrics:
            return 0.0
        
        score = 100.0
        
        # ISE惩罚
        if 'ise' in metrics:
            ise_penalty = min(50, metrics['ise'] / 10)
            score -= ise_penalty
        
        # 超调惩罚
        if 'overshoot' in metrics:
            overshoot_penalty = min(20, metrics['overshoot'])
            score -= overshoot_penalty
        
        # 调节时间惩罚
        if 'settling_time' in metrics:
            settling_penalty = min(15, metrics['settling_time'] / 10)
            score -= settling_penalty
        
        # 振荡惩罚
        if 'oscillation_index' in metrics:
            osc_penalty = min(15, metrics['oscillation_index'] * 50)
            score -= osc_penalty
        
        return max(0.0, min(100.0, score))
    
    def _get_rating(self, score: float) -> str:
        """获取评级"""
        if score >= 90:
            return 'A - 优秀'
        elif score >= 80:
            return 'B - 良好'
        elif score >= 70:
            return 'C - 中等'
        elif score >= 60:
            return 'D - 及格'
        else:
            return 'F - 不及格'
    
    def delete_tracker(self, loop_id: str) -> Dict[str, Any]:
        """删除跟踪器"""
        if loop_id in self.trackers:
            del self.trackers[loop_id]
            return {
                'success': True,
                'loop_id': loop_id,
                'message': '跟踪器已删除'
            }
        
        return {
            'success': False,
            'error': f'跟踪器不存在: {loop_id}'
        }
