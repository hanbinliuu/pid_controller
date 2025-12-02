"""
Realtime Monitor - 实时数据监控
"""
import numpy as np
from typing import Dict, List, Any, Optional, Deque
from datetime import datetime, timedelta
from collections import deque
import asyncio


class RealtimeMonitor:
    """实时数据监控器"""
    
    def __init__(self, buffer_size: int = 1000):
        """
        初始化监控器
        
        Args:
            buffer_size: 数据缓冲区大小
        """
        self.buffer_size = buffer_size
        self.monitors: Dict[str, Dict[str, Any]] = {}
        self.active_monitors: set = set()
    
    def create_monitor(
        self,
        loop_id: str,
        loop_name: str,
        sampling_interval: float = 1.0
    ) -> Dict[str, Any]:
        """
        创建监控实例
        
        Args:
            loop_id: 回路ID
            loop_name: 回路名称
            sampling_interval: 采样间隔（秒）
            
        Returns:
            监控实例信息
        """
        if loop_id in self.monitors:
            return {
                'success': False,
                'error': f'监控实例已存在: {loop_id}'
            }
        
        self.monitors[loop_id] = {
            'loop_id': loop_id,
            'loop_name': loop_name,
            'sampling_interval': sampling_interval,
            'created_at': datetime.now().isoformat(),
            'status': 'created',
            'data_buffer': {
                'time': deque(maxlen=self.buffer_size),
                'pv': deque(maxlen=self.buffer_size),
                'sv': deque(maxlen=self.buffer_size),
                'mv': deque(maxlen=self.buffer_size),
                'error': deque(maxlen=self.buffer_size)
            },
            'statistics': {
                'total_samples': 0,
                'last_update': None
            },
            'realtime_metrics': {}
        }
        
        return {
            'success': True,
            'loop_id': loop_id,
            'message': f'监控实例创建成功: {loop_name}'
        }
    
    def start_monitor(self, loop_id: str) -> Dict[str, Any]:
        """启动监控"""
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        self.monitors[loop_id]['status'] = 'running'
        self.monitors[loop_id]['started_at'] = datetime.now().isoformat()
        self.active_monitors.add(loop_id)
        
        return {
            'success': True,
            'loop_id': loop_id,
            'status': 'running'
        }
    
    def stop_monitor(self, loop_id: str) -> Dict[str, Any]:
        """停止监控"""
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        self.monitors[loop_id]['status'] = 'stopped'
        self.monitors[loop_id]['stopped_at'] = datetime.now().isoformat()
        self.active_monitors.discard(loop_id)
        
        return {
            'success': True,
            'loop_id': loop_id,
            'status': 'stopped'
        }
    
    def add_data_point(
        self,
        loop_id: str,
        timestamp: float,
        pv: float,
        sv: float,
        mv: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        添加数据点
        
        Args:
            loop_id: 回路ID
            timestamp: 时间戳
            pv: 过程变量
            sv: 设定值
            mv: 操纵变量
            
        Returns:
            添加结果
        """
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        monitor = self.monitors[loop_id]
        buffer = monitor['data_buffer']
        
        # 添加数据
        buffer['time'].append(timestamp)
        buffer['pv'].append(pv)
        buffer['sv'].append(sv)
        if mv is not None:
            buffer['mv'].append(mv)
        
        # 计算误差
        error = sv - pv
        buffer['error'].append(error)
        
        # 更新统计
        monitor['statistics']['total_samples'] += 1
        monitor['statistics']['last_update'] = datetime.now().isoformat()
        
        # 计算实时指标
        monitor['realtime_metrics'] = self._calculate_realtime_metrics(monitor)
        
        return {
            'success': True,
            'loop_id': loop_id,
            'sample_count': monitor['statistics']['total_samples']
        }
    
    def add_batch_data(
        self,
        loop_id: str,
        time_data: List[float],
        pv_data: List[float],
        sv_data: List[float],
        mv_data: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        批量添加数据
        
        Args:
            loop_id: 回路ID
            time_data: 时间数据
            pv_data: PV数据
            sv_data: SV数据
            mv_data: MV数据
            
        Returns:
            添加结果
        """
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        if len(time_data) != len(pv_data) or len(time_data) != len(sv_data):
            return {
                'success': False,
                'error': '数据长度不一致'
            }
        
        monitor = self.monitors[loop_id]
        buffer = monitor['data_buffer']
        
        # 批量添加
        for i in range(len(time_data)):
            buffer['time'].append(time_data[i])
            buffer['pv'].append(pv_data[i])
            buffer['sv'].append(sv_data[i])
            
            if mv_data and i < len(mv_data):
                buffer['mv'].append(mv_data[i])
            
            error = sv_data[i] - pv_data[i]
            buffer['error'].append(error)
        
        # 更新统计
        monitor['statistics']['total_samples'] += len(time_data)
        monitor['statistics']['last_update'] = datetime.now().isoformat()
        
        # 计算实时指标
        monitor['realtime_metrics'] = self._calculate_realtime_metrics(monitor)
        
        return {
            'success': True,
            'loop_id': loop_id,
            'added_count': len(time_data),
            'total_samples': monitor['statistics']['total_samples']
        }
    
    def get_realtime_data(
        self,
        loop_id: str,
        last_n: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        获取实时数据
        
        Args:
            loop_id: 回路ID
            last_n: 获取最近N个数据点，None则返回全部
            
        Returns:
            实时数据
        """
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        monitor = self.monitors[loop_id]
        buffer = monitor['data_buffer']
        
        # 获取数据
        if last_n is None:
            data = {
                'time': list(buffer['time']),
                'pv': list(buffer['pv']),
                'sv': list(buffer['sv']),
                'mv': list(buffer['mv']),
                'error': list(buffer['error'])
            }
        else:
            data = {
                'time': list(buffer['time'])[-last_n:],
                'pv': list(buffer['pv'])[-last_n:],
                'sv': list(buffer['sv'])[-last_n:],
                'mv': list(buffer['mv'])[-last_n:],
                'error': list(buffer['error'])[-last_n:]
            }
        
        return {
            'success': True,
            'loop_id': loop_id,
            'loop_name': monitor['loop_name'],
            'status': monitor['status'],
            'data': data,
            'metrics': monitor['realtime_metrics'],
            'statistics': monitor['statistics']
        }
    
    def get_monitor_status(self, loop_id: str) -> Dict[str, Any]:
        """获取监控状态"""
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        monitor = self.monitors[loop_id]
        
        return {
            'success': True,
            'loop_id': loop_id,
            'loop_name': monitor['loop_name'],
            'status': monitor['status'],
            'created_at': monitor['created_at'],
            'started_at': monitor.get('started_at'),
            'stopped_at': monitor.get('stopped_at'),
            'sampling_interval': monitor['sampling_interval'],
            'statistics': monitor['statistics'],
            'metrics': monitor['realtime_metrics']
        }
    
    def get_all_monitors(self) -> Dict[str, Any]:
        """获取所有监控实例"""
        monitors_list = []
        
        for loop_id, monitor in self.monitors.items():
            monitors_list.append({
                'loop_id': loop_id,
                'loop_name': monitor['loop_name'],
                'status': monitor['status'],
                'total_samples': monitor['statistics']['total_samples'],
                'last_update': monitor['statistics']['last_update']
            })
        
        return {
            'success': True,
            'count': len(monitors_list),
            'active_count': len(self.active_monitors),
            'monitors': monitors_list
        }
    
    def delete_monitor(self, loop_id: str) -> Dict[str, Any]:
        """删除监控实例"""
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        # 先停止监控
        if loop_id in self.active_monitors:
            self.stop_monitor(loop_id)
        
        # 删除实例
        del self.monitors[loop_id]
        
        return {
            'success': True,
            'loop_id': loop_id,
            'message': '监控实例已删除'
        }
    
    def clear_buffer(self, loop_id: str) -> Dict[str, Any]:
        """清空数据缓冲区"""
        if loop_id not in self.monitors:
            return {
                'success': False,
                'error': f'监控实例不存在: {loop_id}'
            }
        
        monitor = self.monitors[loop_id]
        buffer = monitor['data_buffer']
        
        # 清空所有缓冲区
        for key in buffer:
            buffer[key].clear()
        
        # 重置统计
        monitor['statistics']['total_samples'] = 0
        monitor['statistics']['last_update'] = None
        monitor['realtime_metrics'] = {}
        
        return {
            'success': True,
            'loop_id': loop_id,
            'message': '数据缓冲区已清空'
        }
    
    def _calculate_realtime_metrics(self, monitor: Dict[str, Any]) -> Dict[str, Any]:
        """计算实时性能指标"""
        buffer = monitor['data_buffer']
        
        if len(buffer['pv']) < 2:
            return {}
        
        pv_array = np.array(list(buffer['pv']))
        sv_array = np.array(list(buffer['sv']))
        error_array = np.array(list(buffer['error']))
        
        metrics = {
            'current_pv': float(pv_array[-1]),
            'current_sv': float(sv_array[-1]),
            'current_error': float(error_array[-1]),
            'mean_pv': float(np.mean(pv_array)),
            'std_pv': float(np.std(pv_array)),
            'min_pv': float(np.min(pv_array)),
            'max_pv': float(np.max(pv_array)),
            'mean_error': float(np.mean(error_array)),
            'abs_mean_error': float(np.mean(np.abs(error_array))),
            'std_error': float(np.std(error_array)),
            'max_abs_error': float(np.max(np.abs(error_array)))
        }
        
        # 计算误差积分
        if len(error_array) > 1:
            metrics['iae'] = float(np.sum(np.abs(error_array)))
            metrics['ise'] = float(np.sum(error_array ** 2))
        
        # 计算变化率
        if len(pv_array) > 1:
            pv_diff = np.diff(pv_array)
            metrics['pv_change_rate'] = float(np.mean(np.abs(pv_diff)))
            metrics['max_pv_change'] = float(np.max(np.abs(pv_diff)))
        
        # 稳态判断
        if len(pv_array) >= 30:
            recent_pv = pv_array[-30:]
            recent_sv = sv_array[-30:]
            
            pv_std = np.std(recent_pv)
            mean_sv = np.mean(recent_sv)
            
            # 简单稳态判断：标准差小于设定值的5%
            is_steady = pv_std < abs(mean_sv) * 0.05 if mean_sv != 0 else pv_std < 0.1
            
            metrics['is_steady'] = bool(is_steady)
            metrics['recent_std'] = float(pv_std)
        
        # MV相关指标
        if len(buffer['mv']) > 0:
            mv_array = np.array(list(buffer['mv']))
            metrics['current_mv'] = float(mv_array[-1])
            metrics['mean_mv'] = float(np.mean(mv_array))
            metrics['std_mv'] = float(np.std(mv_array))
            
            if len(mv_array) > 1:
                mv_diff = np.diff(mv_array)
                metrics['mv_change_rate'] = float(np.mean(np.abs(mv_diff)))
        
        return metrics
