"""
Alarm Manager - 报警管理
"""
import numpy as np
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from enum import Enum


class AlarmLevel(Enum):
    """报警级别"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlarmType(Enum):
    """报警类型"""
    HIGH_ERROR = "high_error"           # 误差过大
    LOW_PV = "low_pv"                   # PV过低
    HIGH_PV = "high_pv"                 # PV过高
    OSCILLATION = "oscillation"         # 振荡
    SATURATION = "saturation"           # 饱和
    DEVIATION = "deviation"             # 偏差
    STEADY_ERROR = "steady_error"       # 稳态误差
    RESPONSE_SLOW = "response_slow"     # 响应缓慢


class AlarmManager:
    """报警管理器"""
    
    def __init__(self):
        self.alarms: Dict[str, List[Dict[str, Any]]] = {}  # loop_id -> alarms
        self.alarm_configs: Dict[str, Dict[str, Any]] = {}  # loop_id -> config
        self.alarm_history: List[Dict[str, Any]] = []
        self.max_history = 1000
    
    def configure_alarms(
        self,
        loop_id: str,
        config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        配置报警规则
        
        Args:
            loop_id: 回路ID
            config: 报警配置
                {
                    'high_error_threshold': 10.0,
                    'low_pv_threshold': 0.0,
                    'high_pv_threshold': 100.0,
                    'oscillation_threshold': 5,
                    'saturation_threshold': 95.0,
                    'steady_error_threshold': 2.0,
                    'enabled': True
                }
                
        Returns:
            配置结果
        """
        default_config = {
            'high_error_threshold': 10.0,
            'low_pv_threshold': None,
            'high_pv_threshold': None,
            'oscillation_threshold': 5,
            'oscillation_window': 50,
            'saturation_threshold': 95.0,
            'steady_error_threshold': 2.0,
            'steady_window': 30,
            'enabled': True
        }
        
        # 合并配置
        default_config.update(config)
        self.alarm_configs[loop_id] = default_config
        
        # 初始化报警列表
        if loop_id not in self.alarms:
            self.alarms[loop_id] = []
        
        return {
            'success': True,
            'loop_id': loop_id,
            'config': default_config
        }
    
    def check_alarms(
        self,
        loop_id: str,
        pv: float,
        sv: float,
        mv: Optional[float] = None,
        pv_history: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        检查报警条件
        
        Args:
            loop_id: 回路ID
            pv: 当前PV值
            sv: 当前SV值
            mv: 当前MV值
            pv_history: PV历史数据（用于振荡检测）
            
        Returns:
            报警检查结果
        """
        if loop_id not in self.alarm_configs:
            return {
                'success': False,
                'error': f'未配置报警规则: {loop_id}'
            }
        
        config = self.alarm_configs[loop_id]
        
        if not config['enabled']:
            return {
                'success': True,
                'loop_id': loop_id,
                'alarms': [],
                'message': '报警功能已禁用'
            }
        
        triggered_alarms = []
        error = sv - pv
        
        # 1. 检查误差过大
        if abs(error) > config['high_error_threshold']:
            alarm = self._create_alarm(
                loop_id,
                AlarmType.HIGH_ERROR,
                AlarmLevel.WARNING if abs(error) < config['high_error_threshold'] * 2 else AlarmLevel.ERROR,
                f"误差过大: {error:.2f} (阈值: ±{config['high_error_threshold']})",
                {'error': error, 'threshold': config['high_error_threshold']}
            )
            triggered_alarms.append(alarm)
        
        # 2. 检查PV过低
        if config['low_pv_threshold'] is not None and pv < config['low_pv_threshold']:
            alarm = self._create_alarm(
                loop_id,
                AlarmType.LOW_PV,
                AlarmLevel.WARNING,
                f"PV值过低: {pv:.2f} (阈值: {config['low_pv_threshold']})",
                {'pv': pv, 'threshold': config['low_pv_threshold']}
            )
            triggered_alarms.append(alarm)
        
        # 3. 检查PV过高
        if config['high_pv_threshold'] is not None and pv > config['high_pv_threshold']:
            alarm = self._create_alarm(
                loop_id,
                AlarmType.HIGH_PV,
                AlarmLevel.WARNING,
                f"PV值过高: {pv:.2f} (阈值: {config['high_pv_threshold']})",
                {'pv': pv, 'threshold': config['high_pv_threshold']}
            )
            triggered_alarms.append(alarm)
        
        # 4. 检查振荡
        if pv_history and len(pv_history) >= config['oscillation_window']:
            oscillation_result = self._check_oscillation(
                pv_history[-config['oscillation_window']:],
                config['oscillation_threshold']
            )
            if oscillation_result['is_oscillating']:
                alarm = self._create_alarm(
                    loop_id,
                    AlarmType.OSCILLATION,
                    AlarmLevel.WARNING,
                    f"检测到振荡 (周期: {oscillation_result['period']:.2f})",
                    oscillation_result
                )
                triggered_alarms.append(alarm)
        
        # 5. 检查MV饱和
        if mv is not None:
            if mv >= config['saturation_threshold']:
                alarm = self._create_alarm(
                    loop_id,
                    AlarmType.SATURATION,
                    AlarmLevel.WARNING,
                    f"MV接近上限饱和: {mv:.2f}%",
                    {'mv': mv, 'threshold': config['saturation_threshold']}
                )
                triggered_alarms.append(alarm)
            elif mv <= (100 - config['saturation_threshold']):
                alarm = self._create_alarm(
                    loop_id,
                    AlarmType.SATURATION,
                    AlarmLevel.WARNING,
                    f"MV接近下限饱和: {mv:.2f}%",
                    {'mv': mv, 'threshold': 100 - config['saturation_threshold']}
                )
                triggered_alarms.append(alarm)
        
        # 6. 检查稳态误差
        if pv_history and len(pv_history) >= config['steady_window']:
            recent_pv = pv_history[-config['steady_window']:]
            pv_std = np.std(recent_pv)
            
            # 如果PV稳定但误差较大，说明存在稳态误差
            if pv_std < abs(sv) * 0.05 and abs(error) > config['steady_error_threshold']:
                alarm = self._create_alarm(
                    loop_id,
                    AlarmType.STEADY_ERROR,
                    AlarmLevel.INFO,
                    f"存在稳态误差: {error:.2f}",
                    {'error': error, 'std': pv_std, 'threshold': config['steady_error_threshold']}
                )
                triggered_alarms.append(alarm)
        
        # 保存触发的报警
        if triggered_alarms:
            if loop_id not in self.alarms:
                self.alarms[loop_id] = []
            self.alarms[loop_id].extend(triggered_alarms)
            
            # 添加到历史
            self.alarm_history.extend(triggered_alarms)
            if len(self.alarm_history) > self.max_history:
                self.alarm_history = self.alarm_history[-self.max_history:]
        
        return {
            'success': True,
            'loop_id': loop_id,
            'timestamp': datetime.now().isoformat(),
            'alarms': triggered_alarms,
            'alarm_count': len(triggered_alarms)
        }
    
    def get_active_alarms(self, loop_id: str) -> Dict[str, Any]:
        """获取活动报警"""
        if loop_id not in self.alarms:
            return {
                'success': True,
                'loop_id': loop_id,
                'alarms': [],
                'count': 0
            }
        
        return {
            'success': True,
            'loop_id': loop_id,
            'alarms': self.alarms[loop_id],
            'count': len(self.alarms[loop_id])
        }
    
    def get_alarm_history(
        self,
        loop_id: Optional[str] = None,
        limit: int = 100
    ) -> Dict[str, Any]:
        """获取报警历史"""
        if loop_id:
            history = [a for a in self.alarm_history if a['loop_id'] == loop_id]
        else:
            history = self.alarm_history
        
        return {
            'success': True,
            'loop_id': loop_id,
            'history': history[-limit:],
            'count': len(history)
        }
    
    def acknowledge_alarm(
        self,
        loop_id: str,
        alarm_id: str
    ) -> Dict[str, Any]:
        """确认报警"""
        if loop_id not in self.alarms:
            return {
                'success': False,
                'error': f'回路无报警: {loop_id}'
            }
        
        for alarm in self.alarms[loop_id]:
            if alarm['id'] == alarm_id:
                alarm['acknowledged'] = True
                alarm['acknowledged_at'] = datetime.now().isoformat()
                return {
                    'success': True,
                    'alarm_id': alarm_id,
                    'message': '报警已确认'
                }
        
        return {
            'success': False,
            'error': f'未找到报警: {alarm_id}'
        }
    
    def clear_alarms(self, loop_id: str) -> Dict[str, Any]:
        """清除报警"""
        if loop_id in self.alarms:
            count = len(self.alarms[loop_id])
            self.alarms[loop_id] = []
            return {
                'success': True,
                'loop_id': loop_id,
                'cleared_count': count
            }
        
        return {
            'success': True,
            'loop_id': loop_id,
            'cleared_count': 0
        }
    
    def get_alarm_statistics(self, loop_id: str) -> Dict[str, Any]:
        """获取报警统计"""
        if loop_id not in self.alarms:
            return {
                'success': True,
                'loop_id': loop_id,
                'statistics': {
                    'total': 0,
                    'by_level': {},
                    'by_type': {}
                }
            }
        
        alarms = self.alarms[loop_id]
        
        # 按级别统计
        by_level = {}
        for alarm in alarms:
            level = alarm['level']
            by_level[level] = by_level.get(level, 0) + 1
        
        # 按类型统计
        by_type = {}
        for alarm in alarms:
            alarm_type = alarm['type']
            by_type[alarm_type] = by_type.get(alarm_type, 0) + 1
        
        return {
            'success': True,
            'loop_id': loop_id,
            'statistics': {
                'total': len(alarms),
                'by_level': by_level,
                'by_type': by_type,
                'acknowledged': sum(1 for a in alarms if a.get('acknowledged', False))
            }
        }
    
    def _create_alarm(
        self,
        loop_id: str,
        alarm_type: AlarmType,
        level: AlarmLevel,
        message: str,
        details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """创建报警"""
        alarm_id = f"{loop_id}_{alarm_type.value}_{datetime.now().timestamp()}"
        
        return {
            'id': alarm_id,
            'loop_id': loop_id,
            'type': alarm_type.value,
            'level': level.value,
            'message': message,
            'details': details,
            'timestamp': datetime.now().isoformat(),
            'acknowledged': False
        }
    
    def _check_oscillation(
        self,
        data: List[float],
        threshold: int
    ) -> Dict[str, Any]:
        """检查振荡"""
        if len(data) < 10:
            return {'is_oscillating': False}
        
        # 简单的振荡检测：计算过零点次数
        data_array = np.array(data)
        mean_val = np.mean(data_array)
        centered = data_array - mean_val
        
        # 检测符号变化
        sign_changes = np.sum(np.diff(np.sign(centered)) != 0)
        
        # 如果符号变化次数超过阈值，认为是振荡
        is_oscillating = sign_changes >= threshold
        
        # 估算周期（保留两位小数）
        period = len(data) / (sign_changes / 2) if sign_changes > 0 else 0
        
        return {
            'is_oscillating': is_oscillating,
            'sign_changes': int(sign_changes),
            'period': round(float(period), 2),  # 保留两位小数
            'amplitude': round(float(np.std(data_array)), 2)  # 振幅也保留两位小数
        }
