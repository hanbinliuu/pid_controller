"""
自动重整定服务
实时监控回路稳定性，检测非稳态并自动触发重整定
"""
import asyncio
from datetime import datetime
import numpy as np

# Configure paths
import path_config  # Centralizes sys.path configuration

from system_tuning.core.data.analyzer import DataAnalyzer
from system_tuning.core.tuning.identifier import SystemIdentifier
from system_tuning.core.pid.tuner import PIDTuner
from system_tuning.core.pid.evaluator import PIDEvaluator
from system_tuning.core.pid.simulator import PIDSimulator


class AutoRetuningService:
    """自动重整定服务"""
    
    def __init__(self, loop_manager, opcua_client):
        """
        初始化自动重整定服务
        
        Args:
            loop_manager: 回路管理器实例
            opcua_client: OPC UA客户端实例
        """
        self.loop_manager = loop_manager
        self.opcua_client = opcua_client
        self.analyzer = DataAnalyzer()
        self.identifier = SystemIdentifier()
        self.tuner = PIDTuner()
        self.evaluator = PIDEvaluator()
        self.simulator = PIDSimulator()
        
        # 监控配置
        self.monitoring_loops = {}  # {loop_id: monitoring_config}
        self.data_buffers = {}  # {loop_id: data_buffer}
        
        # 非稳态检测参数
        self.check_interval = 5  # 每5秒检查一次
        self.buffer_size = 60  # 保留60个数据点（5秒*60=5分钟）
        self.steady_tolerance = 0.3  # 稳态容差
        self.steady_std_tolerance = 0.15  # 稳态标准差容差
        
        print("✅ 自动重整定服务已初始化")
    
    async def start_monitoring(self, loop_id):
        """
        开始监控指定回路
        
        Args:
            loop_id: 回路ID
        """
        if loop_id in self.monitoring_loops:
            print(f"⚠️  回路 {loop_id} 已在监控中")
            return
        
        # 获取回路信息
        loop_info = await self.loop_manager.get_loop(loop_id)
        if not loop_info:
            print(f"❌ 找不到回路 {loop_id}")
            return
        
        if loop_info.get('data_source') != 'opcua':
            print(f"⚠️  回路 {loop_id} 不是OPC UA数据源，无法监控")
            return
        
        # 初始化监控配置
        self.monitoring_loops[loop_id] = {
            'loop_info': loop_info,
            'is_active': True,
            'last_check': None,
            'consecutive_unsteady_count': 0
        }
        
        # 初始化数据缓冲区
        self.data_buffers[loop_id] = {
            'timestamps': [],
            'pv': [],
            'sv': [],
            'mv': []
        }
        
        print(f"✅ 开始监控回路 {loop_id}: {loop_info['name']}")
        
        # 启动监控任务
        asyncio.create_task(self._monitor_loop(loop_id))
    
    async def stop_monitoring(self, loop_id):
        """停止监控指定回路"""
        if loop_id in self.monitoring_loops:
            self.monitoring_loops[loop_id]['is_active'] = False
            del self.monitoring_loops[loop_id]
            del self.data_buffers[loop_id]
            print(f"⏹️  停止监控回路 {loop_id}")
    
    async def _monitor_loop(self, loop_id):
        """
        监控回路的主循环
        
        Args:
            loop_id: 回路ID
        """
        while self.monitoring_loops.get(loop_id, {}).get('is_active', False):
            try:
                # 从OPC UA读取数据
                loop_info = self.monitoring_loops[loop_id]['loop_info']
                opcua_config = loop_info.get('opcua_config', {})
                
                # 读取PV, SV, MV
                pv_node_id = opcua_config.get('pv_node_id')
                sv_node_id = opcua_config.get('sv_node_id')
                mv_node_id = opcua_config.get('mv_node_id')
                
                if not all([pv_node_id, sv_node_id, mv_node_id]):
                    print(f"⚠️  回路 {loop_id} 缺少节点配置")
                    await asyncio.sleep(self.check_interval)
                    continue
                
                # 读取当前值
                pv_value = await self.opcua_client.read_node(pv_node_id)
                sv_value = await self.opcua_client.read_node(sv_node_id)
                mv_value = await self.opcua_client.read_node(mv_node_id)
                
                # 添加到缓冲区
                buffer = self.data_buffers[loop_id]
                buffer['timestamps'].append(datetime.now())
                buffer['pv'].append(pv_value)
                buffer['sv'].append(sv_value)
                buffer['mv'].append(mv_value)
                
                # 限制缓冲区大小
                if len(buffer['pv']) > self.buffer_size:
                    buffer['timestamps'] = buffer['timestamps'][-self.buffer_size:]
                    buffer['pv'] = buffer['pv'][-self.buffer_size:]
                    buffer['sv'] = buffer['sv'][-self.buffer_size:]
                    buffer['mv'] = buffer['mv'][-self.buffer_size:]
                
                # 检查是否有足够的数据进行分析
                if len(buffer['pv']) >= 30:  # 至少30个数据点
                    await self._check_stability(loop_id)
                
                # 等待下一次检查
                await asyncio.sleep(self.check_interval)
                
            except Exception as e:
                print(f"❌ 监控回路 {loop_id} 时出错: {str(e)}")
                await asyncio.sleep(self.check_interval)
    
    async def _check_stability(self, loop_id):
        """
        检查回路稳定性
        
        Args:
            loop_id: 回路ID
        """
        buffer = self.data_buffers[loop_id]
        pv_data = np.array(buffer['pv'])
        sv_data = np.array(buffer['sv'])
        
        # 获取当前设定值
        current_setpoint = sv_data[-1]
        
        # 检查最近的数据是否稳态
        recent_window = 30  # 检查最近30个点
        recent_pv = pv_data[-recent_window:]
        
        is_steady = self.analyzer.is_steady_state(
            recent_pv,
            current_setpoint,
            tol=self.steady_tolerance,
            std_tol=self.steady_std_tolerance,
            min_len=20
        )
        
        monitoring_config = self.monitoring_loops[loop_id]
        
        if not is_steady:
            # 检测到非稳态
            monitoring_config['consecutive_unsteady_count'] += 1
            
            print(f"⚠️  回路 {loop_id} 检测到非稳态 "
                  f"(连续{monitoring_config['consecutive_unsteady_count']}次)")
            
            # 连续3次检测到非稳态，触发重整定
            if monitoring_config['consecutive_unsteady_count'] >= 3:
                print(f"🚨 回路 {loop_id} 持续非稳态，触发自动重整定")
                
                # 更新回路状态为非稳态
                await self.loop_manager.update_loop_stability_status(
                    loop_id,
                    is_unsteady=True,
                    is_retuning=False
                )
                
                # 触发重整定
                await self._trigger_retuning(loop_id)
                
                # 重置计数器
                monitoring_config['consecutive_unsteady_count'] = 0
        else:
            # 稳态，重置计数器
            if monitoring_config['consecutive_unsteady_count'] > 0:
                print(f"✅ 回路 {loop_id} 恢复稳态")
                monitoring_config['consecutive_unsteady_count'] = 0
                
                # 更新回路状态为稳态
                await self.loop_manager.update_loop_stability_status(
                    loop_id,
                    is_unsteady=False,
                    is_retuning=False
                )
    
    async def _trigger_retuning(self, loop_id):
        """
        触发自动重整定
        
        Args:
            loop_id: 回路ID
        """
        try:
            print(f"🔄 开始对回路 {loop_id} 进行自动重整定...")
            
            # 更新状态为重整定中
            await self.loop_manager.update_loop_stability_status(
                loop_id,
                is_unsteady=True,
                is_retuning=True
            )
            
            # 获取数据
            buffer = self.data_buffers[loop_id]
            pv_data = np.array(buffer['pv'])
            sv_data = np.array(buffer['sv'])
            mv_data = np.array(buffer['mv'])
            
            # 1. 系统辨识
            print(f"   📊 步骤1: 系统辨识...")
            identification_result = self.identifier.identify(
                pv=pv_data,
                sv=sv_data,
                mv=mv_data
            )
            
            if not identification_result['success']:
                print(f"   ❌ 系统辨识失败: {identification_result.get('error')}")
                await self.loop_manager.update_loop_stability_status(
                    loop_id,
                    is_unsteady=True,
                    is_retuning=False
                )
                return
            
            best_model = identification_result['best_model']
            print(f"   ✅ 最佳模型: {best_model['model_name']}")
            
            # 2. PID整定
            print(f"   🎯 步骤2: PID参数整定...")
            tuning_result = self.tuner.tune(
                model_params=best_model['model_params'],
                model_type=best_model['model_type'],
                method='LAMBDA',
                control_mode='STANDARD'
            )
            
            new_pid_params = tuning_result['pid_params']
            print(f"   ✅ 新PID参数: Pb={new_pid_params['pb']:.1f}%, "
                  f"Ti={new_pid_params['ti']:.1f}s, Td={new_pid_params['td']:.1f}s")
            
            # 3. 仿真验证
            print(f"   📈 步骤3: 仿真验证...")
            simulation_result = self.simulator.simulate(
                model_params=best_model['model_params'],
                model_type=best_model['model_type'],
                pid_params=new_pid_params,
                setpoint=sv_data[-1],
                duration=len(pv_data),
                initial_pv=pv_data[0]
            )
            
            # 4. 性能评估
            print(f"   📊 步骤4: 性能评估...")
            evaluation = self.evaluator.evaluate(
                pv=simulation_result['pv'],
                sv=simulation_result['sv'],
                mv=simulation_result['mv'],
                pid_params=new_pid_params
            )
            
            print(f"   ✅ 评估结果: 综合评分={evaluation.overall_score:.1f}, "
                  f"等级={evaluation.grade}")
            
            # 5. 更新回路参数
            print(f"   💾 步骤5: 更新回路参数...")
            await self.loop_manager.update_loop_pid_params(
                loop_id,
                pid_params=new_pid_params,
                model_params=best_model['model_params'],
                model_type=best_model['model_type'],
                performance={
                    'score': evaluation.overall_score,
                    'grade': evaluation.grade,
                    'steady_error': evaluation.steady_state_error,
                    'iae': evaluation.iae,
                    'oscillation_count': evaluation.oscillation_count
                }
            )
            
            # 6. 保存重整定记录
            retuning_record = {
                'timestamp': datetime.now().isoformat(),
                'trigger': 'auto',
                'reason': 'unsteady_detected',
                'old_params': self.monitoring_loops[loop_id]['loop_info'].get('pid_params'),
                'new_params': new_pid_params,
                'performance': {
                    'score': evaluation.overall_score,
                    'grade': evaluation.grade
                },
                'simulation_data': {
                    'pv': simulation_result['pv'].tolist(),
                    'sv': simulation_result['sv'].tolist(),
                    'mv': simulation_result['mv'].tolist(),
                    't': simulation_result['t'].tolist()
                }
            }
            
            await self.loop_manager.add_retuning_record(loop_id, retuning_record)
            
            # 7. 更新状态
            await self.loop_manager.update_loop_stability_status(
                loop_id,
                is_unsteady=False,
                is_retuning=False
            )
            
            print(f"✅ 回路 {loop_id} 自动重整定完成！")
            print(f"   新参数已应用，系统应恢复稳态")
            
        except Exception as e:
            print(f"❌ 自动重整定失败: {str(e)}")
            import traceback
            traceback.print_exc()
            
            # 更新状态
            await self.loop_manager.update_loop_stability_status(
                loop_id,
                is_unsteady=True,
                is_retuning=False
            )
    
    def get_monitoring_status(self):
        """获取所有监控回路的状态"""
        status = {}
        for loop_id, config in self.monitoring_loops.items():
            buffer = self.data_buffers.get(loop_id, {})
            status[loop_id] = {
                'loop_name': config['loop_info']['name'],
                'is_active': config['is_active'],
                'buffer_size': len(buffer.get('pv', [])),
                'consecutive_unsteady_count': config['consecutive_unsteady_count'],
                'last_check': config['last_check']
            }
        return status


# 全局实例（将在主服务器中初始化）
auto_retuning_service = None


def initialize_service(loop_manager, opcua_client):
    """初始化自动重整定服务"""
    global auto_retuning_service
    auto_retuning_service = AutoRetuningService(loop_manager, opcua_client)
    return auto_retuning_service
