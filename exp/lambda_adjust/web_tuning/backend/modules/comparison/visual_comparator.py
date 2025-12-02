"""
Visual Comparator - 可视化对比图表生成
"""
import numpy as np
from typing import Dict, List, Any, Optional
import base64
from io import BytesIO


class VisualComparator:
    """可视化对比图表生成器"""
    
    def __init__(self):
        self.chart_configs = {
            'parameter_radar': {
                'title': 'PID参数雷达图',
                'type': 'radar'
            },
            'performance_bar': {
                'title': '性能指标对比',
                'type': 'bar'
            },
            'trend_line': {
                'title': '参数变化趋势',
                'type': 'line'
            }
        }
    
    def generate_parameter_comparison_chart(
        self,
        params_list: List[Dict[str, Any]],
        labels: List[str],
        chart_type: str = 'radar'
    ) -> Dict[str, Any]:
        """
        生成参数对比图表数据
        
        Args:
            params_list: 参数列表
            labels: 标签列表
            chart_type: 图表类型 ('radar', 'bar', 'line')
            
        Returns:
            图表配置数据（用于前端渲染）
        """
        if chart_type == 'radar':
            return self._generate_radar_chart(params_list, labels)
        elif chart_type == 'bar':
            return self._generate_bar_chart(params_list, labels)
        elif chart_type == 'line':
            return self._generate_line_chart(params_list, labels)
        else:
            return {'error': f'不支持的图表类型: {chart_type}'}
    
    def _generate_radar_chart(
        self,
        params_list: List[Dict[str, Any]],
        labels: List[str]
    ) -> Dict[str, Any]:
        """生成雷达图配置"""
        # 归一化参数值到0-100范围
        kp_values = [p.get('kp', 0) for p in params_list]
        ki_values = [p.get('ki', 0) for p in params_list]
        kd_values = [p.get('kd', 0) for p in params_list]
        
        kp_max = max(kp_values) if kp_values else 1
        ki_max = max(ki_values) if ki_values else 1
        kd_max = max(kd_values) if kd_values else 1
        
        series_data = []
        for i, (params, label) in enumerate(zip(params_list, labels)):
            normalized_data = [
                (params.get('kp', 0) / kp_max * 100) if kp_max > 0 else 0,
                (params.get('ki', 0) / ki_max * 100) if ki_max > 0 else 0,
                (params.get('kd', 0) / kd_max * 100) if kd_max > 0 else 0
            ]
            
            series_data.append({
                'name': label,
                'value': normalized_data,
                'original_values': {
                    'kp': params.get('kp', 0),
                    'ki': params.get('ki', 0),
                    'kd': params.get('kd', 0)
                }
            })
        
        return {
            'type': 'radar',
            'title': 'PID参数对比雷达图',
            'indicator': [
                {'name': 'Kp', 'max': 100},
                {'name': 'Ki', 'max': 100},
                {'name': 'Kd', 'max': 100}
            ],
            'series': series_data,
            'legend': labels
        }
    
    def _generate_bar_chart(
        self,
        params_list: List[Dict[str, Any]],
        labels: List[str]
    ) -> Dict[str, Any]:
        """生成柱状图配置"""
        kp_values = [p.get('kp', 0) for p in params_list]
        ki_values = [p.get('ki', 0) for p in params_list]
        kd_values = [p.get('kd', 0) for p in params_list]
        
        return {
            'type': 'bar',
            'title': 'PID参数对比柱状图',
            'xAxis': labels,
            'series': [
                {
                    'name': 'Kp',
                    'data': kp_values,
                    'type': 'bar'
                },
                {
                    'name': 'Ki',
                    'data': ki_values,
                    'type': 'bar'
                },
                {
                    'name': 'Kd',
                    'data': kd_values,
                    'type': 'bar'
                }
            ],
            'legend': ['Kp', 'Ki', 'Kd']
        }
    
    def _generate_line_chart(
        self,
        params_list: List[Dict[str, Any]],
        labels: List[str]
    ) -> Dict[str, Any]:
        """生成折线图配置"""
        kp_values = [p.get('kp', 0) for p in params_list]
        ki_values = [p.get('ki', 0) for p in params_list]
        kd_values = [p.get('kd', 0) for p in params_list]
        
        return {
            'type': 'line',
            'title': 'PID参数变化趋势',
            'xAxis': labels,
            'series': [
                {
                    'name': 'Kp',
                    'data': kp_values,
                    'type': 'line',
                    'smooth': True
                },
                {
                    'name': 'Ki',
                    'data': ki_values,
                    'type': 'line',
                    'smooth': True
                },
                {
                    'name': 'Kd',
                    'data': kd_values,
                    'type': 'line',
                    'smooth': True
                }
            ],
            'legend': ['Kp', 'Ki', 'Kd']
        }
    
    def generate_performance_comparison_chart(
        self,
        performance_list: List[Dict[str, Any]],
        labels: List[str],
        metrics: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        生成性能指标对比图表
        
        Args:
            performance_list: 性能指标列表
            labels: 标签列表
            metrics: 要对比的指标列表，None则使用所有指标
            
        Returns:
            图表配置数据
        """
        if metrics is None:
            # 提取所有可用的数值型指标
            metrics = []
            for perf in performance_list:
                for key, val in perf.items():
                    if isinstance(val, (int, float)) and key not in metrics:
                        metrics.append(key)
        
        series_data = []
        for metric in metrics:
            values = [p.get(metric, 0) for p in performance_list]
            series_data.append({
                'name': metric,
                'data': values,
                'type': 'bar'
            })
        
        return {
            'type': 'bar',
            'title': '性能指标对比',
            'xAxis': labels,
            'series': series_data,
            'legend': metrics
        }
    
    def generate_before_after_chart(
        self,
        original_data: Dict[str, Any],
        tuned_data: Dict[str, Any],
        time_data: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        生成整定前后对比图表
        
        Args:
            original_data: 原始数据 {'pv': [...], 'sv': [...], 'mv': [...]}
            tuned_data: 整定后数据
            time_data: 时间数据
            
        Returns:
            图表配置数据
        """
        if time_data is None:
            time_data = list(range(max(
                len(original_data.get('pv', [])),
                len(tuned_data.get('pv', []))
            )))
        
        return {
            'type': 'line',
            'title': '整定前后对比',
            'xAxis': time_data,
            'series': [
                {
                    'name': '原始PV',
                    'data': original_data.get('pv', []),
                    'type': 'line',
                    'lineStyle': {'type': 'dashed'}
                },
                {
                    'name': '整定后PV',
                    'data': tuned_data.get('pv', []),
                    'type': 'line',
                    'lineStyle': {'type': 'solid'}
                },
                {
                    'name': 'SV',
                    'data': original_data.get('sv', []) or tuned_data.get('sv', []),
                    'type': 'line',
                    'lineStyle': {'type': 'dotted'}
                }
            ],
            'legend': ['原始PV', '整定后PV', 'SV']
        }
    
    def generate_multi_scenario_chart(
        self,
        scenarios: Dict[str, Dict[str, List[float]]],
        time_data: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        生成多场景对比图表
        
        Args:
            scenarios: {
                'scenario1': {'pv': [...], 'sv': [...]},
                'scenario2': {'pv': [...], 'sv': [...]},
                ...
            }
            time_data: 时间数据
            
        Returns:
            图表配置数据
        """
        if not scenarios:
            return {'error': '没有场景数据'}
        
        # 确定时间轴
        if time_data is None:
            max_len = max(len(data.get('pv', [])) for data in scenarios.values())
            time_data = list(range(max_len))
        
        series_data = []
        for scenario_name, scenario_data in scenarios.items():
            series_data.append({
                'name': f'{scenario_name} - PV',
                'data': scenario_data.get('pv', []),
                'type': 'line',
                'smooth': True
            })
        
        return {
            'type': 'line',
            'title': '多场景性能对比',
            'xAxis': time_data,
            'series': series_data,
            'legend': [s['name'] for s in series_data]
        }
    
    def generate_heatmap_chart(
        self,
        data_matrix: List[List[float]],
        x_labels: List[str],
        y_labels: List[str],
        title: str = '参数影响热力图'
    ) -> Dict[str, Any]:
        """
        生成热力图
        
        Args:
            data_matrix: 数据矩阵
            x_labels: X轴标签
            y_labels: Y轴标签
            title: 图表标题
            
        Returns:
            图表配置数据
        """
        # 转换为热力图数据格式
        heatmap_data = []
        for i, row in enumerate(data_matrix):
            for j, value in enumerate(row):
                heatmap_data.append([j, i, value])
        
        return {
            'type': 'heatmap',
            'title': title,
            'xAxis': x_labels,
            'yAxis': y_labels,
            'data': heatmap_data,
            'visualMap': {
                'min': float(np.min(data_matrix)),
                'max': float(np.max(data_matrix)),
                'calculable': True
            }
        }
    
    def generate_scatter_chart(
        self,
        data_points: List[Dict[str, Any]],
        x_key: str,
        y_key: str,
        label_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        生成散点图
        
        Args:
            data_points: 数据点列表
            x_key: X轴数据键
            y_key: Y轴数据键
            label_key: 标签键
            
        Returns:
            图表配置数据
        """
        scatter_data = []
        for point in data_points:
            x_val = point.get(x_key)
            y_val = point.get(y_key)
            if x_val is not None and y_val is not None:
                item = [x_val, y_val]
                if label_key and label_key in point:
                    item.append(point[label_key])
                scatter_data.append(item)
        
        return {
            'type': 'scatter',
            'title': f'{y_key} vs {x_key}',
            'xAxis': {'name': x_key},
            'yAxis': {'name': y_key},
            'series': [{
                'name': f'{y_key}-{x_key}',
                'data': scatter_data,
                'type': 'scatter'
            }]
        }
