"""
自动整定系统
检测扰动 → 自动整定 → 下发参数 → 实时状态同步
"""
import asyncio
import logging
import numpy as np
from datetime import datetime
from typing import Dict, Optional, List
import traceback

# Configure paths
import path_config  # Centralizes sys.path configuration

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import configuration
from app_config import AutoTuningConfig as Config

from system_tuning.core.data.analyzer import DataAnalyzer
from system_tuning.core.tuning.identifier import SystemIdentifier
from system_tuning.core.model.identifier import ModelIdentifier
from system_tuning.core.pid.tuner import PIDTuner, TuningMethod, Mode
from system_tuning.core.pid.evaluator import PIDEvaluator
from system_tuning.core.pid.simulator import simulate_system_with_pid


class LoopState:
    """回路状态枚举"""
    STABLE = "STABLE"
    DISTURBANCE = "DISTURBANCE"
    TUNING = "TUNING"
    STABILIZING = "STABILIZING"


class AutoTuningSystem:
    """自动整定系统"""
    
    def __init__(self, loops_storage, opcua_client):
        """
        初始化自动整定系统
        
        Args:
            loops_storage: 回路存储实例
            opcua_client: OPC UA客户端实例
        """
        self.loops_storage = loops_storage
        self.opcua_client = opcua_client
        
        # 系统组件
        self.analyzer = DataAnalyzer()
        self.identifier = SystemIdentifier()
        self.tuner = PIDTuner()
        self.evaluator = PIDEvaluator()
        
        # 使用配置常量 (from app_config.py)
        self.check_interval = Config.CHECK_INTERVAL
        self.buffer_size = Config.BUFFER_SIZE
        self.steady_tolerance = Config.STEADY_TOLERANCE
        self.steady_std_tolerance = Config.STEADY_STD_TOLERANCE
        self.disturbance_threshold = Config.DISTURBANCE_THRESHOLD
        self.stabilization_window = Config.STABILIZATION_WINDOW
        self.max_tuning_duration = Config.MAX_TUNING_DURATION
        self.min_observation_time = Config.MIN_OBSERVATION_TIME
        self.max_stabilizing_duration = Config.MAX_STABILIZING_DURATION
        
        # 回路状态跟踪
        self.loop_states: Dict[str, Dict] = {}
        
        # WebSocket连接管理
        self.websocket_connections: Dict[str, List] = {}  # {loop_id: [websocket1, websocket2, ...]}
    
    async def start_monitoring(self, loop_id: str):
        """开始监控指定回路"""
        if loop_id in self.loop_states:
            return
        
        loop = self.loops_storage.get_loop(loop_id)
        if not loop or loop.get('data_source') != 'opcua':
            logger.warning(f"回路 {loop_id} 不存在或非OPC UA数据源")
            return
        
        # 检测当前系统状态
        initial_state = LoopState.STABLE
        try:
            collected_data = await self.opcua_client.get_collected_data(loop_id, limit=self.buffer_size)
            if collected_data and collected_data.get('success'):
                data = collected_data.get('data', {})
                pv_data = np.array(data.get('pv', []))
                sv_data = np.array(data.get('sv', []))
                if len(pv_data) >= 20 and self._detect_unsteady(pv_data, sv_data):
                    initial_state = LoopState.DISTURBANCE
        except Exception:
            pass
        
        # 初始化回路状态
        self.loop_states[loop_id] = {
            'state': initial_state,
            'consecutive_unsteady_count': 0,
            'last_check': None,
            'tuning_start_time': None,
            'stabilization_start_time': None,
            'loop_info': loop,
            # 🔒 状态锁定机制，防止非稳态-稳态振荡
            'unsteady_locked': False,
            'last_tuning_params': None,
            'stable_since': None,
            # 🆕 扰动数据相关字段
            'disturb_data': [],  # 扰动数据缓冲区
            'disturbance_start_time': None,  # 扰动开始时间（关键：必须初始化为 None）
            'disturbance_triggered': False,  # 是否已触发整定
            'current_disturb_count': 0,  # 当前扰动数据计数
            'last_sample_count': 0,  # 上次采样计数
            'tuning_ready_warned': False,  # 是否已警告整定就绪
            'last_progress_log': 0,  # 上次进度日志的数据点数
            'last_progress_time': None,  # 上次进度日志的时间
        }
        
        logger.info(f"开始监控回路 {loop_id} ({loop['name']}), 初始状态: {initial_state}")
        
        await self._update_loop_state(loop_id, initial_state)
        
        if initial_state == LoopState.DISTURBANCE:
            asyncio.create_task(self._trigger_immediate_tuning(loop_id))
        
        asyncio.create_task(self._monitor_loop(loop_id))
    
    async def stop_monitoring(self, loop_id: str):
        """停止监控指定回路"""
        if loop_id in self.loop_states:
            del self.loop_states[loop_id]
            logger.info(f"停止监控回路 {loop_id}")
    
    async def _monitor_loop(self, loop_id: str):
        """监控回路的主循环"""
        while loop_id in self.loop_states:
            try:
                # 🚀 优化: 降低检查间隔，提高实时性
                await asyncio.sleep(self.check_interval)
                
                # 🔧 再次检查回路是否仍在监控中（避免竞态条件）
                if loop_id not in self.loop_states:
                    print(f"⏹️  回路 {loop_id} 已停止监控，退出监控循环")
                    break
                
                state_info = self.loop_states[loop_id]
                current_state = state_info['state']
                
                # 🔧 根据状态动态调整数据获取限制
                # DISTURBANCE状态下：由于进入时已清空数据，从0开始累积，只需要150个点的limit
                # 其他状态：使用默认buffer大小
                if current_state == LoopState.DISTURBANCE:
                    data_limit = 150  # 100个新点 + 50个余量
                else:
                    data_limit = self.buffer_size  # 其他状态使用默认buffer大小
                
                # 获取最近的数据
                collected_data = await self.opcua_client.get_collected_data(loop_id, limit=data_limit)
                
                if not collected_data or not collected_data.get('success'):
                    continue
                
                data = collected_data.get('data', {})
                pv_data = np.array(data.get('pv', []))
                sv_data = np.array(data.get('sv', []))
                mv_data = np.array(data.get('mv', []))
                
                if len(pv_data) < 20:
                    continue
                
                # 状态机逻辑
                if current_state == LoopState.STABLE:
                    await self._handle_stable_state(loop_id, pv_data, sv_data, mv_data)
                
                elif current_state == LoopState.DISTURBANCE:
                    await self._handle_disturbance_state(loop_id, pv_data, sv_data, mv_data)
                
                elif current_state == LoopState.TUNING:
                    # 整定中，检查是否超时
                    await self._handle_tuning_state(loop_id)
                
                elif current_state == LoopState.STABILIZING:
                    await self._handle_stabilizing_state(loop_id, pv_data, sv_data)
                
            except KeyError:
                break
            except Exception as e:
                logger.error(f"监控回路 {loop_id} 出错: {e}")
    
    async def _handle_stable_state(self, loop_id: str, pv_data, sv_data, mv_data):
        """处理稳态状态"""
        if loop_id not in self.loop_states:
            return
        state_info = self.loop_states[loop_id]
        
        # 确保稳态时 disturb_data 为空
        if len(state_info.get('disturb_data', [])) > 0:
            await self._force_clear_disturb_data(loop_id, state_info)
        
        is_unsteady = self._detect_unsteady(pv_data, sv_data)
        
        if is_unsteady:
            state_info['consecutive_unsteady_count'] += 1
            if state_info['consecutive_unsteady_count'] >= self.disturbance_threshold:
                logger.info(f"回路 {loop_id} 检测到持续扰动")
                await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
                state_info['consecutive_unsteady_count'] = 0
                if Config.UNSTEADY_LOCK_ENABLED:
                    state_info['unsteady_locked'] = True
                state_info['disturbance_triggered'] = False
                state_info['disturbance_warned'] = False
                state_info['disturbance_start_time'] = None
                state_info['stable_since'] = None
        else:
            if state_info['consecutive_unsteady_count'] > 0:
                state_info['consecutive_unsteady_count'] = 0
    
    async def _handle_disturbance_state(self, loop_id: str, pv_data, sv_data, mv_data):
        """处理扰动状态 - 收集数据并触发整定"""
        if loop_id not in self.loop_states:
            return
        state_info = self.loop_states[loop_id]
        
        # 检查是否已恢复稳态（未锁定时）
        if not state_info.get('unsteady_locked', False):
            is_stable = not self._detect_unsteady(pv_data, sv_data)
            disturb_count = len(state_info.get('disturb_data', []))
            
            loop = self.loops_storage.get_loop(loop_id)
            auto_tuning_enabled = loop.get('opcua_config', {}).get('auto_tuning_enabled', False) if loop else False
            
            if is_stable:
                if disturb_count < Config.MIN_DISTURB_DATA_POINTS:
                    logger.info(f"回路 {loop_id} 扰动消失（数据不足），回到稳态")
                    await self._force_clear_disturb_data(loop_id, state_info)
                    await self._update_loop_state(loop_id, LoopState.STABLE)
                    return
                
                elif not auto_tuning_enabled:
                    logger.info(f"回路 {loop_id} 扰动消失，保留 {disturb_count} 个数据点供手动整定")
                    await self._update_loop_state(loop_id, LoopState.STABLE)
                    return
        
        # 初始化（首次进入扰动状态）
        if state_info.get('disturbance_start_time') is None:
            await self._init_disturbance_state(loop_id, state_info)
        
        # 收集数据并检查整定条件
        await self._collect_disturb_data(loop_id, state_info, pv_data, sv_data, mv_data)
        await self._check_and_trigger_tuning(loop_id, state_info)
    
    async def _init_disturbance_state(self, loop_id: str, state_info: dict):
        """初始化扰动状态 - 清空数据并准备收集"""
        logger.info(f"回路 {loop_id} 进入扰动状态，开始收集数据")
        
        await self._clear_disturb_data(loop_id, state_info)
        state_info['disturbance_start_time'] = datetime.now()
        state_info['tuning_ready_warned'] = False
        state_info['last_progress_log'] = 0
        state_info['last_progress_time'] = datetime.now()
    
    async def _clear_disturb_data(self, loop_id: str, state_info: dict = None):
        """清空 disturb_data 缓冲区"""
        await self.opcua_client.clear_collected_data(loop_id)
        
        if state_info is None and loop_id in self.loop_states:
            state_info = self.loop_states[loop_id]
        
        if state_info:
            state_info['disturb_data'] = []
            state_info['current_disturb_count'] = 0
            state_info['last_sample_count'] = 0
            state_info['disturbance_start_time'] = None
            state_info['disturbance_triggered'] = False
    
    async def _force_clear_disturb_data(self, loop_id: str, state_info: dict = None):
        """强制清空 disturb_data 并验证"""
        if state_info is None and loop_id in self.loop_states:
            state_info = self.loop_states[loop_id]
        
        await self._clear_disturb_data(loop_id, state_info)
        
        # 验证并重试
        if state_info and len(state_info.get('disturb_data', [])) > 0:
            logger.warning(f"回路 {loop_id} disturb_data 清空失败，强制重试")
            state_info['disturb_data'] = []
            state_info['current_disturb_count'] = 0
            state_info['last_sample_count'] = 0
            state_info['disturbance_start_time'] = None
            state_info['disturbance_triggered'] = False
            await self.opcua_client.clear_collected_data(loop_id)
        
        logger.debug(f"回路 {loop_id} disturb_data 已清空")
    
    async def _collect_disturb_data(self, loop_id: str, state_info: dict, pv_data, sv_data, mv_data):
        """收集扰动数据到 disturb_data 缓冲区"""
        # 获取 OPC UA 客户端的采集计数（不受 limit 限制）
        collection_result = await self.opcua_client.get_collection_status(loop_id)
        status = collection_result.get('status', {}) if collection_result else {}
        current_sample_count = status.get('sample_count', 0)
        last_sample_count = state_info.get('last_sample_count', 0)
        
        # 如果有新数据，从 pv_data 末尾提取并添加到 disturb_data
        if current_sample_count > last_sample_count and len(pv_data) > 0:
            new_points = min(current_sample_count - last_sample_count, len(pv_data))
            start_idx = max(0, len(pv_data) - new_points)
            
            for i in range(start_idx, len(pv_data)):
                state_info['disturb_data'].append({
                    'pv': float(pv_data[i]),
                    'sv': float(sv_data[i]),
                    'mv': float(mv_data[i]),
                    'timestamp': datetime.now().isoformat()
                })
            
            state_info['last_sample_count'] = current_sample_count
        
        # 更新计数
        state_info['current_disturb_count'] = len(state_info['disturb_data'])
    
    async def _check_and_trigger_tuning(self, loop_id: str, state_info: dict):
        """检查是否满足整定条件并触发整定"""
        disturb_count = len(state_info['disturb_data'])
        min_points = Config.MIN_DISTURB_DATA_POINTS
        
        # 数据不足，打印进度并返回
        if disturb_count < min_points:
            self._log_collection_progress(loop_id, state_info, disturb_count, min_points)
            return
        
        # 已经触发过整定，等待完成
        if state_info.get('disturbance_triggered', False):
            return
        
        # 检查自动整定是否启用
        loop = self.loops_storage.get_loop(loop_id)
        if not loop:
            return
        
        auto_tuning_enabled = loop.get('opcua_config', {}).get('auto_tuning_enabled', False)
        
        if not auto_tuning_enabled:
            if not state_info.get('tuning_ready_warned', False):
                logger.info(f"回路 {loop_id} 数据已就绪 ({disturb_count}个)，自动整定未启用，请手动触发")
                state_info['tuning_ready_warned'] = True
            return
        
        # 触发自动整定
        await self._trigger_auto_tuning(loop_id, state_info, loop)
    
    def _log_collection_progress(self, loop_id: str, state_info: dict, count: int, target: int):
        """打印数据收集进度（每10个点或每15秒打印一次）"""
        last_log = state_info.get('last_progress_log', 0)
        last_time = state_info.get('last_progress_time', datetime.now())
        elapsed = (datetime.now() - last_time).total_seconds()
        
        if (count - last_log >= 10 and count > 0) or elapsed >= 15:
            logger.info(f"回路 {loop_id} 收集进度: {count}/{target} ({count*100//target}%)")
            state_info['last_progress_log'] = count
            state_info['last_progress_time'] = datetime.now()
    
    async def _trigger_auto_tuning(self, loop_id: str, state_info: dict, loop: dict):
        """触发自动整定"""
        # 互斥检查
        for other_loop_id, other_state in self.loop_states.items():
            if other_loop_id != loop_id and other_state.get('state') == LoopState.TUNING:
                logger.debug(f"回路 {other_loop_id} 正在整定中，等待")
                return
        
        disturb_count = len(state_info['disturb_data'])
        logger.info(f"回路 {loop_id} ({loop['name']}) 触发自动整定，数据点: {disturb_count}")
        
        # 标记已触发
        state_info['disturbance_triggered'] = True
        
        # 更新状态
        await self._update_loop_state(loop_id, LoopState.TUNING)
        state_info['tuning_start_time'] = datetime.now()
        
        # 从 disturb_data 提取数据进行整定
        pv_data = np.array([d['pv'] for d in state_info['disturb_data']])
        sv_data = np.array([d['sv'] for d in state_info['disturb_data']])
        mv_data = np.array([d['mv'] for d in state_info['disturb_data']])
        
        # 执行整定
        result = await self._perform_auto_tuning(loop_id, pv_data, sv_data, mv_data, force_write=True)
        
        if loop_id not in self.loop_states:
            return
        
        if result.get('success'):
            await self._force_clear_disturb_data(loop_id, self.loop_states[loop_id])
            self.loop_states[loop_id]['tuning_start_time'] = None
            
            # 根据整定结果智能决定状态
            if result.get('skip_stabilizing'):
                logger.info(f"回路 {loop_id} 参数变化小，直接进入稳态")
                await self._update_loop_state(loop_id, LoopState.STABLE)
                if Config.UNSTEADY_LOCK_ENABLED:
                    self.loop_states[loop_id]['unsteady_locked'] = False
            else:
                await self._update_loop_state(loop_id, LoopState.STABILIZING)
                self.loop_states[loop_id]['stabilization_start_time'] = datetime.now()
        else:
            await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
            if loop_id in self.loop_states:
                self.loop_states[loop_id]['disturbance_triggered'] = False
                self.loop_states[loop_id]['disturbance_start_time'] = None
    
    async def _handle_tuning_state(self, loop_id: str):
        """处理整定中状态 - 检查是否超时"""
        if loop_id not in self.loop_states:
            return
        state_info = self.loop_states[loop_id]
        
        # 检查整定是否超时
        tuning_start = state_info.get('tuning_start_time')
        if tuning_start:
            elapsed = (datetime.now() - tuning_start).total_seconds()
            
            if elapsed >= self.max_tuning_duration:
                # 整定超时，强制结束
                print(f"⚠️  回路 {loop_id} 整定超时（{elapsed:.0f}秒 > {self.max_tuning_duration}秒），强制结束")
                await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
                # 🔧 关键：重置扰动开始时间，确保重新初始化
                if loop_id in self.loop_states:
                    self.loop_states[loop_id]['disturbance_start_time'] = None
                    self.loop_states[loop_id]['disturbance_triggered'] = False
    
    async def _handle_stabilizing_state(self, loop_id: str, pv_data, sv_data):
        """处理稳定期状态 - 基于实际稳定情况动态判断"""
        if loop_id not in self.loop_states:
            return
        state_info = self.loop_states[loop_id]
        
        stabilization_start = state_info.get('stabilization_start_time')
        if not stabilization_start:
            return
            
        elapsed = (datetime.now() - stabilization_start).total_seconds()
        
        # 超时强制结束
        if elapsed >= self.max_stabilizing_duration:
            logger.warning(f"回路 {loop_id} 稳定期超时 ({elapsed:.0f}s)")
            await self._finish_stabilizing(loop_id, state_info, elapsed)
            return
        
        # 计算当前误差
        current_error = self._calculate_steady_error(pv_data, sv_data)
        is_stable = not self._detect_unsteady(pv_data, sv_data)
        
        # 快速稳定检测：误差很小时可以更快确认稳态
        fast_stable_threshold = getattr(Config, 'FAST_STABLE_ERROR_THRESHOLD', 0.5)
        fast_stable_duration = getattr(Config, 'FAST_STABLE_DURATION', 10)
        is_fast_stable = current_error < fast_stable_threshold and is_stable
        
        # 初始观察期后开始检测
        if elapsed >= self.stabilization_window or is_fast_stable:
            if is_stable:
                if state_info.get('stable_since') is None:
                    state_info['stable_since'] = datetime.now()
                    logger.debug(f"回路 {loop_id} 开始稳定检测, 误差={current_error:.2f}%")
                
                stable_duration = (datetime.now() - state_info['stable_since']).total_seconds()
                
                # 根据误差大小动态调整所需稳定时间
                if is_fast_stable:
                    required_duration = fast_stable_duration
                else:
                    required_duration = Config.MIN_STABLE_DURATION
                
                if stable_duration >= required_duration:
                    logger.info(f"回路 {loop_id} 稳定确认: 总时长={elapsed:.0f}s, 误差={current_error:.2f}%")
                    await self._finish_stabilizing(loop_id, state_info, elapsed)
            else:
                if state_info.get('stable_since') is not None:
                    logger.debug(f"回路 {loop_id} 检测到波动，重置稳定计时")
                    state_info['stable_since'] = None
    
    def _calculate_steady_error(self, pv_data, sv_data) -> float:
        """计算稳态误差百分比"""
        if len(pv_data) < 10 or len(sv_data) < 10:
            return 100.0
        # 使用最近的数据计算误差
        recent_pv = np.mean(pv_data[-20:])
        recent_sv = np.mean(sv_data[-20:])
        if abs(recent_sv) < 1e-6:
            return abs(recent_pv - recent_sv) * 100
        return abs(recent_pv - recent_sv) / abs(recent_sv) * 100
    
    async def _finish_stabilizing(self, loop_id: str, state_info: dict, elapsed: float):
        """完成稳定期，回到稳态"""
        await self._force_clear_disturb_data(loop_id, state_info)
        if Config.UNSTEADY_LOCK_ENABLED:
            state_info['unsteady_locked'] = False
        await self._update_loop_state(loop_id, LoopState.STABLE)
    
    async def _trigger_immediate_tuning(self, loop_id: str):
        """立即触发整定（用于启动监控时检测到非稳态的情况）"""
        try:
            # 等待一小段时间，确保监控任务已启动
            await asyncio.sleep(1)
            
            # 检查回路是否仍在监控中
            if loop_id not in self.loop_states:
                return
            
            # 获取最新数据
            collected_data = await self.opcua_client.get_collected_data(loop_id, limit=self.buffer_size)
            if not collected_data or not collected_data.get('success'):
                print(f"   ⚠️  无法获取数据，取消立即整定")
                return
            
            data = collected_data.get('data', {})
            pv_data = np.array(data.get('pv', []))
            sv_data = np.array(data.get('sv', []))
            mv_data = np.array(data.get('mv', []))
            
            if len(pv_data) < 20:
                print(f"   ⚠️  数据不足，取消立即整定")
                return
            
            # 执行整定
            await self._update_loop_state(loop_id, LoopState.TUNING)
            
            # 🔧 记录整定开始时间
            if loop_id in self.loop_states:
                self.loop_states[loop_id]['tuning_start_time'] = datetime.now()
            
            result = await self._perform_auto_tuning(loop_id, pv_data, sv_data, mv_data, force_write=True)
            
            if result.get('success') and loop_id in self.loop_states:
                await self._force_clear_disturb_data(loop_id, self.loop_states[loop_id])
                self.loop_states[loop_id]['tuning_start_time'] = None
                
                if result.get('skip_stabilizing'):
                    logger.info(f"回路 {loop_id} 参数变化小，直接进入稳态")
                    await self._update_loop_state(loop_id, LoopState.STABLE)
                    if Config.UNSTEADY_LOCK_ENABLED:
                        self.loop_states[loop_id]['unsteady_locked'] = False
                else:
                    await self._update_loop_state(loop_id, LoopState.STABILIZING)
                    self.loop_states[loop_id]['stabilization_start_time'] = datetime.now()
            elif loop_id in self.loop_states:
                await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
                self.loop_states[loop_id]['disturbance_start_time'] = None
                self.loop_states[loop_id]['disturbance_triggered'] = False
        except Exception as e:
            print(f"   ❌ 立即整定失败: {e}")
            traceback.print_exc()
    
    async def _perform_auto_tuning(self, loop_id: str, pv_data, sv_data, mv_data, force_write: bool = False) -> dict:
        """执行自动整定
        
        Returns:
            dict: {
                'success': bool,
                'param_change': float,  # 参数变化程度 (0-1)
                'steady_error': float,  # 稳态误差
                'skip_stabilizing': bool  # 是否可以跳过稳定期
            }
        """
        try:
            print(f"   📊 步骤1: 数据准备...")
            
            # 准备时间序列
            t = np.arange(len(pv_data))
            setpoint = np.mean(sv_data)
            
            # 获取当前PID参数（用于闭环辨识增强）
            loop = self.loops_storage.get_loop(loop_id)
            current_pid_params = None
            if loop:
                # 🔧 修复：从 pid_params 字典中获取参数
                pid_params = loop.get('pid_params', {})
                current_pid_params = {
                    'pb': pid_params.get('pb', 100.0),
                    'ti': pid_params.get('ti', 20.0),
                    'td': pid_params.get('td', 0.0)
                }
            
            # 系统辨识
            tuning_result = self.identifier.auto_tune_from_json(
                t, pv_data, setpoint,
                tuning_method=TuningMethod.LAMBDA,
                mode=Mode.STANDARD,
                u_data=mv_data,
                auto_detect=True,
                sv_array=sv_data,
                enable_setpoint_segmentation=False,
                current_pid_params=current_pid_params  # 传入当前PID参数
            )
            
            if not tuning_result or 'pb' not in tuning_result:
                logger.error(f"回路 {loop_id} 系统辨识失败")
                return {'success': False}
            
            new_pb = float(tuning_result['pb'])
            new_ti = float(tuning_result['ti'])
            new_td = float(tuning_result['td'])
            logger.info(f"回路 {loop_id} 新PID: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
            
            # 仿真验证
            model_type = tuning_result.get('model_type', 'fopdt')
            model_params = tuning_result.get('model_params', [1.0, 10.0, 2.0])
            
            # 获取模型函数
            MODEL_TYPE_MAP = {
                'fopdt': ModelIdentifier.fopdt_model,
                'first_order': ModelIdentifier.fopdt_model,
                'second_order': ModelIdentifier.second_order_model,
                'integral_delay': ModelIdentifier.integral_delay_model
            }
            system_model = MODEL_TYPE_MAP.get(model_type, ModelIdentifier.fopdt_model)
            
            # 仿真
            pv_sim, mv_sim = simulate_system_with_pid(
                t, system_model, tuple(model_params),
                {'pb': new_pb, 'ti': new_ti, 'td': new_td},
                setpoint=setpoint,
                initial_pv=pv_data[0],
                initial_mv=mv_data[0] if len(mv_data) > 0 else 50.0,
                verbose=False,
                setpoint_array=sv_data
            )
            
            # 性能评估
            evaluation = self.evaluator.evaluate(
                pv_sim, sv_data, mv_sim,
                pid_params={'pb': new_pb, 'ti': new_ti, 'td': new_td}
            )
            logger.info(f"回路 {loop_id} 评分: {evaluation.overall_score:.1f} ({evaluation.grade})")
            
            # 参数验证
            param_validation = self._validate_new_parameters(
                loop_id, new_pb, new_ti, new_td, evaluation
            )
            if not param_validation['valid']:
                logger.warning(f"回路 {loop_id} 参数验证: {param_validation['reason']}")
            
            # 更新回路参数
            self.loops_storage.update_loop(loop_id, {
                'pid_params': {
                    'pb': new_pb,
                    'ti': new_ti,
                    'td': new_td
                },
                'model_type': model_type,
                'model_params': model_params,
                'performance': {
                    'score': float(evaluation.overall_score),
                    'grade': evaluation.grade,
                    'steady_error': float(evaluation.steady_state_error),
                    'iae': float(evaluation.iae),
                    'oscillation_count': int(evaluation.oscillation_count)
                },
                'param_validation': param_validation,  # 新增：记录参数验证结果
                'updated_at': datetime.now().isoformat()
            })
            
            # 记录本次整定参数
            if loop_id in self.loop_states:
                self.loop_states[loop_id]['last_tuning_params'] = {
                    'pb': new_pb, 'ti': new_ti, 'td': new_td,
                    'score': float(evaluation.overall_score),
                    'timestamp': datetime.now().isoformat()
                }
            
            # 下发参数到OPC UA
            await self._write_pid_to_opcua(loop_id, new_pb, new_ti, new_td, force_write=force_write)
            
            # 清空数据缓冲区
            await self._clear_disturb_data(loop_id)
            
            # 计算参数变化程度
            param_change = self._calculate_param_change(current_pid_params, new_pb, new_ti, new_td)
            steady_error = float(evaluation.steady_state_error)
            
            # 判断是否可以跳过稳定期
            skip_stabilizing = (
                param_change < 0.1 and  # 参数变化<10%
                steady_error < 0.02 and  # 稳态误差<2%
                evaluation.overall_score >= 70  # 评分>=70
            )
            
            logger.info(f"回路 {loop_id} 整定完成: 参数变化={param_change*100:.1f}%, 误差={steady_error*100:.2f}%")
            
            return {
                'success': True,
                'param_change': param_change,
                'steady_error': steady_error,
                'score': float(evaluation.overall_score),
                'skip_stabilizing': skip_stabilizing
            }
            
        except Exception as e:
            logger.error(f"回路 {loop_id} 自动整定失败: {e}")
            return {'success': False}
    
    def _calculate_param_change(self, old_params: dict, new_pb: float, new_ti: float, new_td: float) -> float:
        """计算参数变化程度 (0-1)"""
        if not old_params:
            return 1.0
        
        old_pb = old_params.get('pb', 100.0)
        old_ti = old_params.get('ti', 20.0)
        old_td = old_params.get('td', 0.0)
        
        # 计算各参数的相对变化
        pb_change = abs(new_pb - old_pb) / max(abs(old_pb), 1.0)
        ti_change = abs(new_ti - old_ti) / max(abs(old_ti), 1.0)
        td_change = abs(new_td - old_td) / max(abs(old_td), 0.1) if old_td > 0 else 0
        
        # 加权平均 (Pb和Ti更重要)
        return 0.4 * pb_change + 0.4 * ti_change + 0.2 * td_change
    
    async def _write_pid_to_opcua(self, loop_id: str, pb: float, ti: float, td: float, force_write: bool = False):
        """将PID参数写入OPC UA
        
        Args:
            loop_id: 回路ID
            pb: 比例带
            ti: 积分时间
            td: 微分时间
            force_write: 是否强制下发（忽略参数差异检查）
        """
        try:
            loop = self.loops_storage.get_loop(loop_id)
            opcua_config = loop.get('opcua_config', {})
            
            # 获取PID参数节点ID
            pid_pb_node = opcua_config.get('pid_pb_node_id')
            pid_ti_node = opcua_config.get('pid_ti_node_id')
            pid_td_node = opcua_config.get('pid_td_node_id')
            
            if not all([pid_pb_node, pid_ti_node, pid_td_node]):
                logger.warning(f"回路 {loop_id} 缺少PID节点配置")
                return
            
            if not self.opcua_client.connected:
                logger.error(f"回路 {loop_id} OPC UA未连接")
                return
            
            # 批量写入参数
            params_to_write = [
                ('Pb', pid_pb_node, pb, '%'),
                ('Ti', pid_ti_node, ti, 's'),
                ('Td', pid_td_node, td, 's')
            ]
            
            results = []
            for param_name, node_id, value, unit in params_to_write:
                try:
                    result = await self.opcua_client.write_node_value(node_id, float(value))
                    results.append(result and result.get('success'))
                except Exception as e:
                    logger.error(f"回路 {loop_id} {param_name} 写入异常: {e}")
                    results.append(False)
            
            if all(results):
                logger.debug(f"回路 {loop_id} PID参数已写入OPC UA")
            else:
                logger.warning(f"回路 {loop_id} 部分PID参数写入失败")
            
        except Exception as e:
            logger.error(f"回路 {loop_id} 写入OPC UA失败: {e}")
    
    def _detect_unsteady(self, pv_data, sv_data) -> bool:
        """检测是否非稳态"""
        if len(pv_data) < 20:
            return False
        
        # 使用最近30个点进行检测
        recent_window = min(30, len(pv_data))
        recent_pv = pv_data[-recent_window:]
        current_setpoint = sv_data[-1]
        
        is_steady = self.analyzer.is_steady_state(
            recent_pv,
            current_setpoint,
            tol=self.steady_tolerance,
            std_tol=self.steady_std_tolerance,
            min_len=20
        )
        
        return not is_steady
    
    async def _write_state_to_opcua(self, loop_id: str, state: str):
        """将状态写入OPC UA状态节点
        
        Args:
            loop_id: 回路ID
            state: 状态值（STABLE, DISTURBANCE, TUNING, STABILIZING）
        """
        try:
            loop = self.loops_storage.get_loop(loop_id)
            if not loop:
                print(f"   ⚠️  回路 {loop_id} 不存在，跳过状态节点写入")
                return
            
            opcua_config = loop.get('opcua_config', {})
            state_node_id = opcua_config.get('state_node_id')
            
            # 如果没有配置状态节点，跳过
            if not state_node_id:
                print(f"   ⚠️  回路 {loop_id} 未配置状态节点ID，跳过状态节点写入")
                return
            
            # 检查OPC UA连接
            if not self.opcua_client.connected:
                print(f"   ⚠️  OPC UA未连接，跳过状态节点写入")
                return
            
            # 状态映射（OPC UA Server可能需要特定格式）
            # 根据您的OPC UA Server实现，可能需要调整这个映射
            state_mapping = {
                LoopState.STABLE: "STABLE",
                LoopState.DISTURBANCE: "DISTURBANCE",
                LoopState.TUNING: "TUNING",
                LoopState.STABILIZING: "STABILIZING"
            }
            
            opcua_state = state_mapping.get(state, state)
            
            # 写入状态节点
            print(f"   📡 写入OPC UA状态节点: {state_node_id} = {opcua_state}")
            result = await self.opcua_client.write_node_value(state_node_id, opcua_state)
            if result and result.get('success'):
                print(f"   ✅ OPC UA状态节点已更新: {opcua_state}")
            else:
                error_msg = result.get('error', '未知错误') if result else '无返回结果'
                print(f"   ❌ OPC UA状态节点更新失败: {error_msg}")
            
        except Exception as e:
            # 状态节点写入失败不应影响主流程
            print(f"   ⚠️  写入OPC UA状态节点失败: {e}")
    
    async def _update_loop_state(self, loop_id: str, new_state: str):
        """更新回路状态（数据库 + WebSocket实时推送 + OPC UA状态节点）"""
        try:
            # 更新内存状态
            if loop_id in self.loop_states:
                self.loop_states[loop_id]['state'] = new_state
                self.loop_states[loop_id]['last_check'] = datetime.now()
            
            # 🔧 同步状态到OPC UA状态节点
            await self._write_state_to_opcua(loop_id, new_state)
            
            # ═══════════════════════════════════════════════════════════
            # 状态映射规则
            # ═══════════════════════════════════════════════════════════
            # STABLE:      稳态，无扰动，无整定
            # DISTURBANCE: 非稳态，检测到扰动
            # TUNING:      整定中，系统正在计算新参数
            # STABILIZING: 稳定期，等待新参数生效
            # ═══════════════════════════════════════════════════════════
            
            is_unsteady = new_state == LoopState.DISTURBANCE
            is_retuning = new_state in [LoopState.TUNING, LoopState.STABILIZING]
            
            # 构建状态更新数据
            now = datetime.now().isoformat()
            status_update = {
                'stability_status': {
                    'is_unsteady': is_unsteady,
                    'is_retuning': is_retuning,
                    'state': new_state,
                    'last_check': now
                }
            }
            
            # 记录整定开始时间
            if new_state in [LoopState.TUNING, LoopState.STABILIZING]:
                status_update['stability_status']['retuning_start_time'] = now
            
            # 更新数据库
            self.loops_storage.update_loop(loop_id, status_update)
            
            # 状态图标
            state_icons = {
                LoopState.STABLE: "✅",
                LoopState.DISTURBANCE: "⚠️",
                LoopState.TUNING: "🔄",
                LoopState.STABILIZING: "🔄"
            }
            icon = state_icons.get(new_state, "❓")
            
            # 打印状态变化（简化日志）
            print(f"{icon} 回路 {loop_id} → {new_state} (unsteady={is_unsteady}, retuning={is_retuning})")
            
        except Exception as e:
            print(f"   ❌ 状态更新失败: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # 实时推送到WebSocket客户端
        await self._broadcast_state_update(loop_id, new_state, is_unsteady, is_retuning)
    
    async def _broadcast_state_update(self, loop_id: str, state: str, is_unsteady: bool, is_retuning: bool):
        """广播状态更新到所有WebSocket客户端"""
        if loop_id not in self.websocket_connections:
            return
        
        message = {
            'type': 'state_update',
            'loop_id': loop_id,
            'state': state,
            'is_unsteady': is_unsteady,
            'is_retuning': is_retuning,
            'timestamp': datetime.now().isoformat()
        }
        
        # 发送到所有连接的客户端
        dead_connections = []
        for ws in self.websocket_connections[loop_id]:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)
        
        # 清理断开的连接
        for ws in dead_connections:
            self.websocket_connections[loop_id].remove(ws)
    
    def register_websocket(self, loop_id: str, websocket):
        """注册WebSocket连接"""
        if loop_id not in self.websocket_connections:
            self.websocket_connections[loop_id] = []
        self.websocket_connections[loop_id].append(websocket)
        print(f"📡 WebSocket已注册: 回路 {loop_id}")
    
    def unregister_websocket(self, loop_id: str, websocket):
        """注销WebSocket连接"""
        if loop_id in self.websocket_connections:
            try:
                self.websocket_connections[loop_id].remove(websocket)
                print(f"📡 WebSocket已注销: 回路 {loop_id}")
            except ValueError:
                pass
    
    async def manual_trigger_tuning(self, loop_id: str, pv_data, sv_data, mv_data) -> bool:
        """手动触发整定"""
        if loop_id not in self.loop_states:
            logger.warning(f"回路 {loop_id} 未在监控中")
            return False
        
        state_info = self.loop_states[loop_id]
        current_state = state_info['state']
        
        if current_state == LoopState.TUNING:
            logger.warning(f"回路 {loop_id} 正在整定中")
            return False
        
        # 互斥检查
        loop = self.loops_storage.get_loop(loop_id)
        if loop and loop.get('opcua_config', {}).get('auto_tuning_enabled', False):
            logger.warning(f"回路 {loop_id} 自动整定已开启，请先关闭")
            return False
        
        logger.info(f"回路 {loop_id} 手动整定开始")
        
        # 停止其他回路的自动整定
        for other_loop_id in list(self.loop_states.keys()):
            if other_loop_id != loop_id:
                other_loop = self.loops_storage.get_loop(other_loop_id)
                if other_loop:
                    other_opcua_config = other_loop.get('opcua_config', {})
                    if other_opcua_config.get('auto_tuning_enabled', False):
                        other_opcua_config['auto_tuning_enabled'] = False
                        self.loops_storage.update_loop(other_loop_id, {'opcua_config': other_opcua_config})
                        await self.stop_monitoring(other_loop_id)
        
        # 检查数据是否充足
        disturb_data = state_info.get('disturb_data', [])
        disturb_data_count = len(disturb_data)
        min_points = Config.MIN_DISTURB_DATA_POINTS
        
        if disturb_data_count < min_points:
            logger.warning(f"回路 {loop_id} 数据不足: {disturb_data_count}/{min_points}")
            return False
        
        # 提取数据
        pv_disturbance = np.array([d['pv'] for d in disturb_data])
        sv_disturbance = np.array([d['sv'] for d in disturb_data])
        mv_disturbance = np.array([d['mv'] for d in disturb_data])
        
        # 数据质量验证
        quality_check = self._validate_tuning_data_quality(pv_disturbance, sv_disturbance, mv_disturbance)
        if not quality_check['valid']:
            logger.warning(f"回路 {loop_id} 数据质量不足: {quality_check['issues']}")
            return False
        
        # 更新状态
        if current_state in [LoopState.STABILIZING, LoopState.STABLE]:
            await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
            state_info['consecutive_unsteady_count'] = 0
            state_info['stabilization_start_time'] = None
            state_info['disturbance_triggered'] = False
        
        # 执行整定
        await self._update_loop_state(loop_id, LoopState.TUNING)
        state_info['tuning_start_time'] = datetime.now()
        
        result = await self._perform_auto_tuning(
            loop_id, pv_disturbance, sv_disturbance, mv_disturbance, force_write=True
        )
        
        if result.get('success'):
            logger.info(f"回路 {loop_id} 手动整定成功")
            await self._force_clear_disturb_data(loop_id, state_info)
            state_info['tuning_start_time'] = None
            
            if result.get('skip_stabilizing'):
                logger.info(f"回路 {loop_id} 参数变化小，直接进入稳态")
                await self._update_loop_state(loop_id, LoopState.STABLE)
                if Config.UNSTEADY_LOCK_ENABLED:
                    state_info['unsteady_locked'] = False
            else:
                await self._update_loop_state(loop_id, LoopState.STABILIZING)
                state_info['stabilization_start_time'] = datetime.now()
        else:
            logger.error(f"回路 {loop_id} 手动整定失败")
            await self._update_loop_state(loop_id, LoopState.DISTURBANCE)
            state_info['disturbance_start_time'] = None
        
        return result.get('success', False)
    
    async def _detect_disturbance_for_manual_tuning(self, loop_id: str, pv_data, sv_data) -> tuple:
        """为手动整定检测扰动
        
        Returns:
            (is_disturbed, disturbance_info): 是否检测到扰动，扰动信息字典
        """
        if len(pv_data) < 50:
            return False, {
                'reason': '数据点数不足（少于50个）',
                'suggestion': '请等待采集更多数据',
                'disturbance_start_idx': 0
            }
        
        # 使用滑动窗口检测扰动起始点
        # 策略：找到最后一个稳定段的结束位置，作为扰动起始点
        window_size = 20
        tolerance = 1.0  # 稳态容差
        std_tolerance = 0.5  # 标准差容差
        
        disturbance_start_idx = 0
        found_stable_region = False
        
        # 从后向前扫描，找到最后一个稳定段
        for i in range(len(pv_data) - window_size, window_size, -window_size // 2):
            window_pv = pv_data[i:i+window_size]
            window_sv = sv_data[i:i+window_size]
            
            # 检查这个窗口是否稳定
            mean_error = np.mean(np.abs(window_pv - window_sv))
            std_error = np.std(window_pv)
            
            if mean_error < tolerance and std_error < std_tolerance:
                # 找到稳定段，扰动起始点在这之后
                disturbance_start_idx = i + window_size
                found_stable_region = True
                break
        
        # 如果没有找到稳定段，检查整体是否处于扰动状态
        if not found_stable_region:
            # 检查最近的数据是否处于扰动状态
            recent_window = min(50, len(pv_data))
            recent_pv = pv_data[-recent_window:]
            recent_sv = sv_data[-recent_window:]
            
            mean_error = np.mean(np.abs(recent_pv - recent_sv))
            std_error = np.std(recent_pv)
            
            if mean_error > tolerance or std_error > std_tolerance:
                # 整体处于扰动状态，从头开始
                disturbance_start_idx = 0
                return True, {
                    'reason': '',
                    'message': f'整体处于扰动状态（误差={mean_error:.2f}, 标准差={std_error:.2f}）',
                    'suggestion': '',
                    'disturbance_start_idx': disturbance_start_idx
                }
            else:
                # 当前处于稳态，无扰动
                return False, {
                    'reason': '当前系统处于稳态，未检测到扰动',
                    'suggestion': '手动整定需要在扰动发生后进行，请等待系统出现扰动或人为施加扰动',
                    'disturbance_start_idx': 0
                }
        
        # 验证扰动段确实是非稳态的
        disturbance_pv = pv_data[disturbance_start_idx:]
        disturbance_sv = sv_data[disturbance_start_idx:]
        
        if len(disturbance_pv) < 20:
            return False, {
                'reason': '扰动段数据点太少',
                'suggestion': '请等待采集更多扰动数据',
                'disturbance_start_idx': disturbance_start_idx
            }
        
        disturbance_error = np.mean(np.abs(disturbance_pv - disturbance_sv))
        disturbance_std = np.std(disturbance_pv)
        
        if disturbance_error < tolerance and disturbance_std < std_tolerance:
            return False, {
                'reason': '扰动段数据显示系统已稳定',
                'suggestion': '当前系统已恢复稳态，无需整定',
                'disturbance_start_idx': disturbance_start_idx
            }
        
        return True, {
            'reason': '',
            'message': f'检测到扰动段（起始索引={disturbance_start_idx}，误差={disturbance_error:.2f}，标准差={disturbance_std:.2f}）',
            'suggestion': '',
            'disturbance_start_idx': disturbance_start_idx
        }
    
    def _validate_tuning_data_quality(self, pv_data, sv_data, mv_data) -> dict:
        """验证整定数据质量
        
        Returns:
            dict: {'valid': bool, 'issues': list, 'checks': list}
        """
        issues = []
        checks = []
        
        # 1. 数据长度检查
        if len(pv_data) < 100:
            issues.append(f"数据点数不足: {len(pv_data)} < 100")
        else:
            checks.append(f"数据点数充足: {len(pv_data)} 个点")
        
        # 2. 数据一致性检查
        if not (len(pv_data) == len(sv_data) == len(mv_data)):
            issues.append(f"数据长度不一致: PV={len(pv_data)}, SV={len(sv_data)}, MV={len(mv_data)}")
        else:
            checks.append("数据长度一致")
        
        # 3. NaN和Inf检查
        if np.any(np.isnan(pv_data)) or np.any(np.isinf(pv_data)):
            issues.append("PV数据包含NaN或Inf")
        else:
            checks.append("PV数据无异常值")
        
        if np.any(np.isnan(sv_data)) or np.any(np.isinf(sv_data)):
            issues.append("SV数据包含NaN或Inf")
        else:
            checks.append("SV数据无异常值")
        
        if np.any(np.isnan(mv_data)) or np.any(np.isinf(mv_data)):
            issues.append("MV数据包含NaN或Inf")
        else:
            checks.append("MV数据无异常值")
        
        # 4. 数据变化检查（确保有动态响应）
        pv_range = np.max(pv_data) - np.min(pv_data)
        mv_range = np.max(mv_data) - np.min(mv_data)
        
        if pv_range < 0.1:
            issues.append(f"PV变化范围太小: {pv_range:.3f}")
        else:
            checks.append(f"PV变化范围合理: {pv_range:.2f}")
        
        if mv_range < 1.0:
            issues.append(f"MV变化范围太小: {mv_range:.3f}")
        else:
            checks.append(f"MV变化范围合理: {mv_range:.2f}")
        
        # 5. 信噪比检查
        pv_std = np.std(pv_data)
        pv_mean = np.mean(np.abs(pv_data))
        if pv_mean > 0:
            snr = pv_range / (pv_std + 1e-6)
            if snr < 2.0:
                issues.append(f"信噪比过低: {snr:.2f}")
            else:
                checks.append(f"信噪比合格: {snr:.2f}")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'checks': checks
        }
    
    def _validate_new_parameters(self, loop_id: str, new_pb: float, new_ti: float, 
                                 new_td: float, evaluation) -> dict:
        """验证新参数的有效性
        
        🔧 验证逻辑：
        1. 参数是否在合理范围内
        2. 相比上次整定是否有改善
        3. 性能评分是否达标
        
        Returns:
            dict: {'valid': bool, 'reason': str, 'message': str, 'suggestion': str}
        """
        # 1. 参数范围检查
        if new_pb <= 0 or new_pb > 500:
            return {
                'valid': False,
                'reason': f'比例带超出合理范围: {new_pb:.1f}% (应在0-500%)',
                'message': '',
                'suggestion': '检查系统辨识结果，可能需要更多或更好的数据'
            }
        
        if new_ti < 0 or new_ti > 1000:
            return {
                'valid': False,
                'reason': f'积分时间超出合理范围: {new_ti:.1f}s (应在0-1000s)',
                'message': '',
                'suggestion': '检查系统辨识结果，可能需要更多或更好的数据'
            }
        
        if new_td < 0 or new_td > 100:
            return {
                'valid': False,
                'reason': f'微分时间超出合理范围: {new_td:.1f}s (应在0-100s)',
                'message': '',
                'suggestion': '检查系统辨识结果，可能需要更多或更好的数据'
            }
        
        # 2. 性能评分检查
        min_score = 60.0  # 最低可接受评分
        if evaluation.overall_score < min_score:
            return {
                'valid': False,
                'reason': f'性能评分过低: {evaluation.overall_score:.1f} < {min_score}',
                'message': '',
                'suggestion': '建议收集更多扰动数据或检查数据质量'
            }
        
        # 3. 与当前运行参数对比
        # 🔧 修复：应该对比当前运行的参数，而不是上次整定的参数
        loop = self.loops_storage.get_loop(loop_id)
        if loop:
            pid_params = loop.get('pid_params', {})
            current_pb = pid_params.get('pb', 100.0)
            current_ti = pid_params.get('ti', 20.0)
            current_td = pid_params.get('td', 0.0)
            
            # 计算参数变化
            pb_change = abs(new_pb - current_pb) / current_pb * 100 if current_pb > 0 else 0
            ti_change = abs(new_ti - current_ti) / current_ti * 100 if current_ti > 0 else 0
            td_change = abs(new_td - current_td) / current_td * 100 if current_td > 0 else 0
            
            threshold = Config.PARAM_IMPROVEMENT_THRESHOLD * 100  # 转为百分比
            
            # 如果参数变化很小
            if pb_change < threshold and ti_change < threshold and td_change < threshold:
                return {
                    'valid': True,  # 仍然有效，但给出警告
                    'reason': '',
                    'message': f'参数变化较小（Pb:{pb_change:.1f}%, Ti:{ti_change:.1f}%, Td:{td_change:.1f}%），当前参数已接近最优',
                    'suggestion': '系统已稳定在最优参数附近，无需频繁调整'
                }
            
            # 参数有显著变化
            return {
                'valid': True,
                'reason': '',
                'message': f'参数有效，相比当前参数变化显著（Pb:{pb_change:.1f}%, Ti:{ti_change:.1f}%, Td:{td_change:.1f}%），性能评分{evaluation.overall_score:.1f}',
                'suggestion': ''
            }
        
        # 首次整定，只要参数合理且评分达标就通过
        return {
            'valid': True,
            'reason': '',
            'message': f'首次整定，参数合理，性能评分{evaluation.overall_score:.1f}',
            'suggestion': ''
        }
    
    def is_monitoring(self, loop_id: str) -> bool:
        """检查回路是否在监控中"""
        return loop_id in self.loop_states
    
    def get_disturb_data_count(self, loop_id: str) -> int:
        """获取指定回路的扰动数据缓冲区数量
        
        Args:
            loop_id: 回路ID
            
        Returns:
            int: 扰动数据点数量，如果回路不存在则返回0
        """
        if loop_id not in self.loop_states:
            return 0
        return len(self.loop_states[loop_id].get('disturb_data', []))


# 全局实例
auto_tuning_system: Optional[AutoTuningSystem] = None


def initialize_system(loops_storage, opcua_client):
    """初始化自动整定系统"""
    global auto_tuning_system
    auto_tuning_system = AutoTuningSystem(loops_storage, opcua_client)
    return auto_tuning_system
