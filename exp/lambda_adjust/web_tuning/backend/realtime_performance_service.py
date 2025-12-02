"""
实时性能监控服务
负责计算和跟踪回路的实时性能指标
"""

import asyncio
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional

# Configure paths
import path_config  # Centralizes sys.path configuration

from core.pid.evaluator import PIDEvaluator
from loops_storage import storage as loops_storage


class RealtimePerformanceService:
    """实时性能计算服务"""
    
    def __init__(self, opcua_client):
        self.opcua_client = opcua_client
        self.is_running = False
        self.update_interval = 10  # 每10秒更新一次
        self.evaluator = PIDEvaluator()  # 使用统一的评估器
    
    async def start(self):
        """启动实时性能计算任务"""
        if self.is_running:
            print("⚠️  实时性能计算任务已在运行")
            return
        
        self.is_running = True
        print("✅ 实时性能计算任务已启动")
        
        while self.is_running:
            try:
                await self._update_all_loops_performance()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                print(f"❌ 实时性能计算异常: {str(e)}")
                await asyncio.sleep(self.update_interval)
    
    def stop(self):
        """停止实时性能计算任务"""
        self.is_running = False
        print("🛑 实时性能计算任务已停止")
    
    async def _update_all_loops_performance(self):
        """更新所有回路的性能指标"""
        all_loops = loops_storage.get_all_loops()
        opcua_loops = [loop for loop in all_loops if loop.get('data_source') == 'opcua']
        
        if not opcua_loops:
            return
        
        print(f"🔄 更新 {len(opcua_loops)} 个回路的性能指标...")
        
        for loop in opcua_loops:
            loop_id = loop['id']
            opcua_config = loop.get('opcua_config', {})
            
            # 只处理正在采集的回路
            if not opcua_config.get('is_collecting'):
                continue
            
            try:
                # 获取采集的数据
                collected_data = await self.opcua_client.get_collected_data(loop_id, limit=100)
                
                if not collected_data or not collected_data.get('success'):
                    continue
                
                data = collected_data.get('data', {})
                pv_data = data.get('pv', [])
                sv_data = data.get('sv', [])
                mv_data = data.get('mv', [])
                
                if len(pv_data) < 20:
                    # 数据不足，跳过
                    continue
                
                # 获取回路的PID参数
                pid_params = loop.get('pid_params')
                
                # 计算性能指标
                performance = self.calculate_performance_metrics(pv_data, sv_data, mv_data, pid_params)
                
                # 更新回路
                loops_storage.update_loop(loop_id, {
                    'performance': performance,
                    'updated_at': datetime.now().isoformat()
                })
                
                print(f"  ✅ {loop['name']}: 评分={performance['score']:.1f}, 误差={performance['steady_error']:.3f}")
                
            except Exception as e:
                print(f"  ❌ 更新回路 {loop['name']} 性能失败: {str(e)}")
    
    def calculate_performance_metrics(self, pv_data: List[float], sv_data: List[float], mv_data: List[float], pid_params: Optional[Dict] = None) -> Dict:
        """
        计算性能指标（使用统一的PIDEvaluator算法）
        
        Args:
            pv_data: PV数据列表
            sv_data: SV数据列表
            mv_data: MV数据列表
            pid_params: PID参数字典（可选，用于参数合理性检查）
            
        Returns:
            性能指标字典
        """
        pv = np.array(pv_data)
        sv = np.array(sv_data)
        mv = np.array(mv_data)
        
        # 使用统一的PIDEvaluator进行评估
        try:
            metrics = self.evaluator.evaluate(
                pv=pv,
                sv=sv,
                cv=mv,
                pid_params=pid_params,
                exclude_sv_transition=True  # 排除设定值变化期间
            )
            
            # 转换为字典格式
            return {
                'score': round(float(metrics.overall_score), 1),
                'grade': self._convert_grade_to_chinese(metrics.grade),
                'steady_error': round(float(metrics.steady_state_error), 3),
                'iae': round(float(metrics.iae), 2),
                'ise': round(float(metrics.ise), 2),
                'tv': round(float(metrics.tv), 2),
                'oscillation_count': int(metrics.oscillation_count),
                'max_oscillation_amplitude': round(float(metrics.max_oscillation_amplitude), 3),
                'max_control_effort': round(float(metrics.max_control_effort), 2),
                'last_update': datetime.now().isoformat()
            }
        except Exception as e:
            print(f"⚠️  性能评估失败: {str(e)}")
            # 返回默认值
            return {
                'score': 0.0,
                'grade': '未知',
                'steady_error': 0.0,
                'iae': 0.0,
                'ise': 0.0,
                'tv': 0.0,
                'oscillation_count': 0,
                'max_oscillation_amplitude': 0.0,
                'max_control_effort': 0.0,
                'last_update': datetime.now().isoformat()
            }
    
    def _convert_grade_to_chinese(self, grade: str) -> str:
        """将英文等级转换为中文"""
        grade_map = {
            'A': '优秀',
            'B': '良好',
            'C': '中等',
            'D': '及格',
            'F': '较差'
        }
        return grade_map.get(grade, grade)
    
    async def update_loop_pid_params(self, loop_id: str, new_params: Dict[str, float]):
        """
        更新回路的PID参数
        
        Args:
            loop_id: 回路ID
            new_params: 新的PID参数 {'pb': ..., 'ti': ..., 'td': ...}
        """
        try:
            loop = loops_storage.get_loop(loop_id)
            if not loop:
                print(f"❌ 找不到回路: {loop_id}")
                return False
            
            # 更新PID参数
            loops_storage.update_loop(loop_id, {
                'pid_params': new_params,
                'updated_at': datetime.now().isoformat()
            })
            
            print(f"✅ 更新回路 {loop['name']} PID参数: Pb={new_params.get('pb')}, Ti={new_params.get('ti')}, Td={new_params.get('td')}")
            return True
            
        except Exception as e:
            print(f"❌ 更新PID参数失败: {str(e)}")
            return False


# 全局实例（将在app.py中初始化）
realtime_performance_service = None
