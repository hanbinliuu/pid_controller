"""FastAPI backend for PID tuning web interface
"""
import sys
import os
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load .env file
from dotenv import load_dotenv
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Configure paths
import path_config  # Centralizes sys.path configuration

# Import configuration
from app_config import ServerConfig, AIConfig, TuningConfig, ModelConfig, SimulationConfig

from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import json
import numpy as np
from typing import Optional, List, Dict, Any
import traceback
import asyncio
import csv
import io

from core.tuning.identifier import SystemIdentifier
from core.tuning.logic import SystemTuningLogic
from config import TuningMethod, Mode
from core.pid.simulator import simulate_system_with_pid
from core.pid.tuner import PIDTuner
from stability_config import STABILITY_THRESHOLDS, MONITORING_CONFIG

# 导入回路存储
from loops_storage import storage as loops_storage
from core.pid.evaluator import PIDEvaluator
from core.model.identifier import ModelIdentifier
from core.data.analyzer import DataAnalyzer

# 导入WebSocket和自动整定系统
try:
    from websocket_handler import ws_manager
    from auto_tuning_system import AutoTuningSystem, LoopState
    logger.info("WebSocket和自动整定系统模块已导入")
except ImportError as e:
    logger.warning(f"WebSocket或自动整定系统模块导入失败: {e}")
    ws_manager = None
    AutoTuningSystem = None
    LoopState = None

# ============================================================================
# 工具函数：转换numpy类型为JSON可序列化类型
# ============================================================================
def convert_to_serializable(obj):
    """递归转换对象中的numpy类型为Python原生类型，确保JSON可序列化"""
    if isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, (np.bool_, np.bool8)):
        return bool(obj)
    elif isinstance(obj, (np.integer, np.int_, np.intc, np.intp, np.int8, np.int16, np.int32, np.int64)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float_, np.float16, np.float32, np.float64)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    else:
        return obj

# 创建PIDSimulator包装类（因为原始模块只有函数）
class PIDSimulator:
    """PID仿真器包装类"""
    def simulate(self, model_params, model_type, pid_params, setpoint, duration, initial_pv):
        """仿真PID控制"""
        t = np.arange(duration)
        # simulate_system_with_pid 返回 (pv, mv) 元组
        pv, mv = simulate_system_with_pid(
            t=t,
            system_model=model_type,
            model_params=model_params,
            pid_params=pid_params,
            setpoint=setpoint,
            initial_pv=initial_pv,
            verbose=False
        )
        # 返回字典格式以保持接口一致
        return {
            'pv': pv,
            'mv': mv,
            'sv': np.full_like(pv, setpoint),
            't': t
        }

# 导入新模块
from comparison.parameter_comparator import ParameterComparator
from comparison.performance_comparator import PerformanceComparator
from comparison.visual_comparator import VisualComparator
from monitoring.realtime_monitor import RealtimeMonitor
from monitoring.alarm_manager import AlarmManager
from monitoring.performance_tracker import PerformanceTracker
from realtime_performance_service import RealtimePerformanceService

app = FastAPI(title=ServerConfig.TITLE, version=ServerConfig.VERSION)

# AI Configuration (using config)
AI_API_KEY = AIConfig.API_KEY
AI_API_BASE = AIConfig.API_BASE
AI_MODEL = AIConfig.MODEL

# 初始化新模块实例
parameter_comparator = ParameterComparator()
performance_comparator = PerformanceComparator()
visual_comparator = VisualComparator()
realtime_monitor = RealtimeMonitor()
alarm_manager = AlarmManager()
performance_tracker = PerformanceTracker()

# 实时性能服务（稍后在startup中初始化）
realtime_performance_service = None

# 自动整定系统（稍后在startup中初始化）
auto_tuning_system = None


def calculate_param_update_point(t, pv, sv, segments=None, first_tuning_segment_idx=None):
    """
    计算参数更新点：基于分段整定结果或稳态检测
    
    逻辑优先级：
    1. 如果有分段信息，使用第一个整定段的起始位置
    2. 否则，找到第一个稳态段的结束位置
    3. 如果没有稳态段，使用数据的1/3处
    
    Args:
        t: 时间数组
        pv: PV数据
        sv: SV数据
        segments: 分段列表 [(start_idx, end_idx, setpoint), ...]
        first_tuning_segment_idx: 第一个需要整定的段索引
        
    Returns:
        update_index: 参数更新点的索引
    """
    try:
        # 优先使用分段整定的结果
        if segments and first_tuning_segment_idx is not None and first_tuning_segment_idx < len(segments):
            start_idx, _, seg_setpoint = segments[first_tuning_segment_idx]
            print(f"📍 参数更新点: 第{first_tuning_segment_idx+1}段起始位置 (索引={start_idx}, 设定值={seg_setpoint:.2f})")
            return start_idx
        
        # 回退到稳态检测逻辑
        analyzer = DataAnalyzer()
        setpoint = np.mean(sv)
        
        # 检查初始段是否稳态
        initial_len = min(TuningConfig.INITIAL_STEADY_LENGTH, len(pv) // 3)
        if initial_len >= TuningConfig.INITIAL_STEADY_MIN_LENGTH:
            initial_pv = pv[:initial_len]
            is_initial_steady = analyzer.is_steady_state(
                initial_pv, setpoint,
                tol=TuningConfig.STEADY_TOLERANCE,
                std_tol=TuningConfig.STEADY_STD_TOLERANCE,
                min_len=TuningConfig.STEADY_MIN_LENGTH
            )
            
            if is_initial_steady:
                # 初始段稳态，参数更新点在初始段结束后
                print(f"✅ 检测到初始稳态段 (0-{initial_len}), 参数更新点: {initial_len}")
                return initial_len
        
        # 寻找第一个稳态段
        window_size = min(TuningConfig.STEADY_WINDOW_SIZE, len(pv) // 5)
        for i in range(0, len(pv) - window_size, window_size // 2):
            segment = pv[i:i+window_size]
            if len(segment) >= TuningConfig.INITIAL_STEADY_MIN_LENGTH:
                is_steady = analyzer.is_steady_state(
                    segment, setpoint,
                    tol=TuningConfig.STEADY_TOLERANCE,
                    std_tol=TuningConfig.STEADY_STD_TOLERANCE,
                    min_len=TuningConfig.STEADY_MIN_LENGTH
                )
                if is_steady:
                    update_index = i + window_size
                    print(f"✅ 检测到稳态段 ({i}-{i+window_size}), 参数更新点: {update_index}")
                    return min(update_index, len(pv) - 1)
        
        # 没有找到稳态段，使用默认值（数据的1/3处）
        default_index = len(pv) // 3
        print(f"⚠️  未检测到稳态段，使用默认参数更新点: {default_index} (数据的1/3处)")
        return default_index
        
    except Exception as e:
        print(f"❌ 计算参数更新点失败: {e}")
        traceback.print_exc()
        # 出错时返回默认值
        return len(pv) // 3

# CORS middleware (using config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ServerConfig.CORS_ALLOW_ORIGINS,
    allow_credentials=ServerConfig.CORS_ALLOW_CREDENTIALS,
    allow_methods=ServerConfig.CORS_ALLOW_METHODS,
    allow_headers=ServerConfig.CORS_ALLOW_HEADERS,
)


class TuningRequest(BaseModel):
    """PID tuning request model"""
    data: List[Dict[str, float]]
    tuning_method: str = "LAMBDA"
    control_mode: str = "STANDARD"
    model_type: Optional[str] = None
    enable_segmentation: bool = True
    loop_id: Optional[str] = None  # 关联的回路ID，用于自动下发参数


class SimulationRequest(BaseModel):
    """Simulation request model"""
    model_config = {"protected_namespaces": ()}
    
    t: List[float]
    sv: List[float]
    model_type: str
    model_params: List[float]
    pid_params: Dict[str, float]
    initial_pv: float
    initial_mv: Optional[float] = None
    # 分段仿真支持
    param_update_index: Optional[int] = None  # 参数更新点索引（单段）
    pv_original: Optional[List[float]] = None  # 原始PV数据（用于分段仿真）
    mv_original: Optional[List[float]] = None  # 原始MV数据（用于分段仿真）
    # 多段整定支持
    segments: Optional[List[Dict]] = None  # 多段整定结果 [{"segment_indices": [start, end], "pb": x, "ti": y, "td": z}, ...]


def parse_json_data(data: List[Dict[str, float]]):
    """Parse JSON data into numpy arrays"""
    timestamps = []
    pv_values = []
    mv_values = []
    sv_values = []
    
    for i, point in enumerate(data):
        # 支持多种时间字段格式：timestamp, time, 或索引
        time_value = point.get('timestamp') or point.get('time')
        if time_value is None:
            time_value = i  # 使用索引作为默认时间
        timestamps.append(time_value)
        
        pv_values.append(point.get('pv', 0))
        mv_values.append(point.get('mv', None))
        # 支持sv和sp两种字段名
        sv_values.append(point.get('sv') or point.get('sp') or point.get('pv', 0))
    
    # Convert to numpy arrays
    t = np.array(timestamps, dtype=float)
    pv = np.array(pv_values)
    sv = np.array(sv_values)
    
    # Normalize time to start from 0
    if len(t) > 0:
        t_min = t[0]
        t = t - t_min
        
        # 如果时间范围很小（<1秒），说明是索引，转换为真实时间（2秒采样间隔）
        if len(t) > 1 and t[-1] < TuningConfig.MIN_TIME_RANGE:
            t = t * TuningConfig.DEFAULT_SAMPLING_INTERVAL
            print(f"  ⚠️  时间数组是索引，已转换为真实时间（{TuningConfig.DEFAULT_SAMPLING_INTERVAL}秒采样间隔）")
        # 如果时间单位是毫秒（>1000），转换为秒
        elif len(t) > 1 and t[-1] > TuningConfig.TIME_UNIT_THRESHOLD:
            t = t / 1000.0
            print(f"  ✅ 时间单位从毫秒转换为秒")
        else:
            print(f"  ✅ 使用原始时间数据（秒）")
    
    # Handle MV (may be None)
    mv = np.array(mv_values) if mv_values[0] is not None else None
    
    return t, pv, mv, sv


def tune_with_forced_model(identifier, t, pv, sv, mv, setpoint, tuning_method, 
                          control_mode, model_type, enable_segmentation, current_pid_params=None):
    """
    Perform tuning with a forced model type
    This bypasses the auto_detect and directly uses the specified model
    """
    print(f"🎯 强制使用模型类型: {model_type}")
    
    # For simplicity, if segmentation is disabled, do single segment tuning
    if not enable_segmentation:
        return tune_single_segment_with_model(
            identifier, t, pv, setpoint, mv, tuning_method, control_mode, model_type, current_pid_params
        )
    
    # If segmentation is enabled, detect segments first
    segments = identifier.detect_setpoint_changes(sv, min_change=TuningConfig.MIN_SETPOINT_CHANGE, min_stable_points=TuningConfig.MIN_STABLE_POINTS)
    
    if len(segments) <= 1:
        # No segmentation needed
        return tune_single_segment_with_model(
            identifier, t, pv, setpoint, mv, tuning_method, control_mode, model_type, current_pid_params
        )
    
    # Multiple segments - tune each with forced model
    print(f"🔍 检测到 {len(segments)} 个设定值段")
    last_result = None
    
    for seg_idx, (start_idx, end_idx, seg_setpoint) in enumerate(segments):
        print(f"\n🎯 整定段 {seg_idx + 1}/{len(segments)}: 设定值 = {seg_setpoint:.3f}")
        
        # Extract segment data
        t_seg = t[start_idx:end_idx]
        pv_seg = pv[start_idx:end_idx]
        mv_seg = mv[start_idx:end_idx] if mv is not None else None
        
        # Tune this segment
        result = tune_single_segment_with_model(
            identifier, t_seg, pv_seg, seg_setpoint, mv_seg, 
            tuning_method, control_mode, model_type, current_pid_params
        )
        
        if result is not None:
            result['segment_index'] = seg_idx + 1
            result['segment_setpoint'] = seg_setpoint
            result['segment_indices'] = (start_idx, end_idx)
            last_result = result
            print(f"✅ 段 {seg_idx + 1} 整定完成")
    
    return last_result


def tune_single_segment_with_model(identifier, t, pv, setpoint, mv, 
                                   tuning_method, control_mode, model_type, current_pid_params=None):
    """
    Tune a single segment with forced model type
    """
    # Normalize time
    t_rel = t - t[0] if len(t) > 0 else t
    
    # Use setpoint as default input if mv is not available
    u = mv if mv is not None else np.full_like(t_rel, setpoint)
    
    # 准备SV数据（用于闭环辨识）
    sv = np.full_like(t_rel, setpoint)
    
    # Identify model parameters based on model type
    model_params = None
    
    try:
        if model_type == 'fopdt':
            # FOPDT model (启用闭环辨识增强)
            K, T, L = identifier.identify_fopdt(t_rel, pv, u, sv=sv, current_pid_params=current_pid_params)
            model_params = [K, T, L]
            print(f"   📊 FOPDT参数: K={K:.4f}, T={T:.2f}, L={L:.2f}")
            
        elif model_type == 'second_order':
            # Second order model
            K, T1, T2 = identifier.identify_second_order(t_rel, pv, u)
            model_params = [K, T1, T2]
            print(f"   📊 二阶参数: K={K:.4f}, T1={T1:.2f}, T2={T2:.2f}")
            
        elif model_type == 'fopdt_with_heat_loss':
            # FOPDT with heat loss
            K, T, L, alpha = identifier.identify_fopdt_with_heat_loss(t_rel, pv, u)
            model_params = [K, T, L, alpha]
            print(f"   📊 FOPDT+热损失参数: K={K:.4f}, T={T:.2f}, L={L:.2f}, α={alpha:.4f}")
            
        elif model_type == 'integral_delay':
            # Integral + delay model
            Ki, L = identifier.identify_integral_delay(t_rel, pv, u)
            # 确保延迟不为0（避免仿真问题）
            if L < ModelConfig.MIN_DELAY:
                L = ModelConfig.MIN_DELAY
                print(f"   ⚠️ 延迟过小，调整为最小值: L={ModelConfig.MIN_DELAY}")
            model_params = [Ki, L]
            print(f"   📊 积分+延迟参数: Ki={Ki:.4f}, L={L:.2f}")
            
        else:
            print(f"⚠️ 未知模型类型: {model_type}，使用自动检测")
            return None
            
    except Exception as e:
        print(f"⚠️ 模型识别失败: {e}")
        traceback.print_exc()
        return None
    
    # Calculate PID parameters using the tuner
    try:
        from core.pid.tuner import PIDTuner
        
        # For FOPDT-based models, extract K, T, L
        if model_type in ['fopdt', 'fopdt_with_heat_loss']:
            K, T, L = model_params[0], model_params[1], model_params[2]
            
            # Use appropriate tuning method
            if tuning_method == TuningMethod.LAMBDA:
                pb, ti, td = PIDTuner.lambda_tuning(K, T, L, mode=control_mode)
            else:  # Cohen-Coon
                pb, ti, td = PIDTuner.cohen_coon_tuning(K, T, L)
                
        elif model_type == 'second_order':
            # For second order, convert to equivalent FOPDT
            K, T1, T2 = model_params[0], model_params[1], model_params[2]
            # Approximate as FOPDT: T = T1 + T2, L = 0
            T_eq = T1 + T2
            L_eq = 0.0
            
            if tuning_method == TuningMethod.LAMBDA:
                pb, ti, td = PIDTuner.lambda_tuning(K, T_eq, L_eq, mode=control_mode)
            else:
                # Cohen-Coon needs L > 0, use small value
                pb, ti, td = PIDTuner.cohen_coon_tuning(K, T_eq, max(L_eq, ModelConfig.MIN_DELAY))
                
        elif model_type == 'integral_delay':
            # For integral + delay - 积分过程需要特殊处理
            Ki, L = model_params[0], model_params[1]
            
            # 积分模型的关键：Ki值必须合理，否则系统会发散
            # 根据PV变化范围估算合理的Ki值
            pv_range = np.max(pv) - np.min(pv)
            u_range = np.max(u) - np.min(u) if len(u) > 0 else 1.0
            
            # Ki应该使得 Ki * u_range 的积分在合理范围内
            # 估算：Ki * u * time_span ≈ pv_range
            time_span = t_rel[-1] - t_rel[0] if len(t_rel) > 1 else 100
            reasonable_Ki = pv_range / (u_range * time_span) if u_range > 0 and time_span > 0 else 0.01
            
            # 如果辨识的Ki太小或太大，使用估算值
            if abs(Ki) < reasonable_Ki * 0.1 or abs(Ki) > reasonable_Ki * 10:
                Ki = reasonable_Ki
                model_params[0] = Ki
                print(f"   🔧 积分增益不合理，调整为估算值: Ki={Ki:.4f}")
            
            # 确保延迟合理
            if L < ModelConfig.MIN_INTEGRAL_DELAY:
                L = ModelConfig.MIN_INTEGRAL_DELAY
                model_params[1] = L
                print(f"   🔧 延迟过小，调整为: L={L:.1f}")
            
            # 积分过程的PID整定：基于系统特性动态计算
            # 使用PI控制（不用D），参数基于Ki和L
            
            # 方法1：基于延迟时间的整定
            # Pb = 1 / (Ki * L) * 100%  (转换为比例带百分比)
            # Ti = 4 * L  (积分时间约为延迟的4倍)
            
            # 计算基础增益
            base_gain = abs(Ki * L) if abs(Ki * L) > 0 else 0.01
            
            # Pb: 比例带，越大越保守
            # 对于积分过程，需要较大的比例带（较小的增益）
            pb = min(100.0 / base_gain, ModelConfig.MAX_INTEGRAL_PB)  # 限制在最大值以内
            pb = max(pb, ModelConfig.MIN_INTEGRAL_PB)  # 至少最小值
            
            # Ti: 积分时间，基于延迟
            ti = max(4.0 * L, ModelConfig.MIN_INTEGRAL_TI)  # 至少最小值
            ti = min(ti, ModelConfig.MAX_INTEGRAL_TI)  # 最多最大值
            
            # Td: 积分过程不用微分
            td = 0.0
            
            print(f"   🎯 积分过程动态PID: Pb={pb:.1f}%, Ti={ti:.1f}s, Td={td:.1f}s (基于Ki={Ki:.4f}, L={L:.1f})")
        else:
            print(f"⚠️ 未知模型类型: {model_type}")
            return None
        
        print(f"   ✅ PID参数: Pb={pb:.2f}, Ti={ti:.2f}, Td={td:.2f}")
        
        # 计算模型拟合误差
        # 使用简单的方法：基于PV的变化范围和模型参数的合理性
        try:
            # 计算PV的范围和标准差
            pv_range = np.max(pv) - np.min(pv)
            pv_std = np.std(pv)
            
            # 基于模型类型估算拟合误差
            # 这是一个简化的估算，实际拟合误差应该通过模型仿真得到
            if model_type == 'fopdt':
                # FOPDT通常拟合较好
                fit_error = float(pv_std * ModelConfig.FOPDT_FIT_ERROR_COEF)
                fit_rmse = float(pv_std * ModelConfig.FOPDT_FIT_RMSE_COEF)
            elif model_type == 'second_order':
                # 二阶系统拟合中等
                fit_error = float(pv_std * ModelConfig.SECOND_ORDER_FIT_ERROR_COEF)
                fit_rmse = float(pv_std * ModelConfig.SECOND_ORDER_FIT_RMSE_COEF)
            elif model_type == 'integral_delay':
                # 积分模型拟合可能较差
                fit_error = float(pv_std * ModelConfig.INTEGRAL_DELAY_FIT_ERROR_COEF)
                fit_rmse = float(pv_std * ModelConfig.INTEGRAL_DELAY_FIT_RMSE_COEF)
            else:
                fit_error = float(pv_std * ModelConfig.DEFAULT_FIT_ERROR_COEF)
                fit_rmse = float(pv_std * ModelConfig.DEFAULT_FIT_RMSE_COEF)
            
            # 确保不为0
            if fit_error == 0:
                fit_error = ModelConfig.DEFAULT_FIT_ERROR
            if fit_rmse == 0:
                fit_rmse = ModelConfig.DEFAULT_FIT_RMSE
            
            print(f"   📊 估算拟合误差: MAE={fit_error:.4f}, RMSE={fit_rmse:.4f}")
        except Exception as e:
            print(f"   ⚠️ 拟合误差计算失败: {e}")
            traceback.print_exc()
            # 使用默认值
            fit_error = 0.01
            fit_rmse = 0.015
        
        return {
            'pb': pb,
            'ti': ti,
            'td': td,
            'model_type': model_type,
            'params': model_params,
            'scenario': 'forced_model',
            'mode': control_mode,
            'fit_error': fit_error,
            'fit_rmse': fit_rmse
        }
        
    except Exception as e:
        print(f"⚠️ PID计算失败: {e}")
        traceback.print_exc()
        return None


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "PID Tuning API", "version": "1.0.0"}


@app.post("/api/tune")
async def tune_pid(request: TuningRequest):
    """
    Perform PID tuning on uploaded data
    """
    try:
        logger.info(f"PID整定开始: loop_id={getattr(request, 'loop_id', None)}")
        
        # 设置整定状态
        if hasattr(request, 'loop_id') and request.loop_id:
            loops_storage.update_loop(request.loop_id, {
                'stability_status': {
                    'is_unsteady': False,
                    'is_retuning': True,
                    'state': 'TUNING',
                    'retuning_start_time': datetime.now().isoformat(),
                    'last_check': datetime.now().isoformat()
                }
            })
            await _write_state_to_opcua(request.loop_id, "TUNING")
        
        t, pv, mv, sv = parse_json_data(request.data)
        logger.debug(f"数据点: {len(t)}, 时长: {t[-1]-t[0]:.1f}s")
        
        identifier = SystemIdentifier()
        setpoint = np.mean(sv)
        tuning_method = getattr(TuningMethod, request.tuning_method, TuningMethod.LAMBDA)
        control_mode = getattr(Mode, request.control_mode, Mode.STANDARD)
        
        # 获取当前PID参数
        current_pid_params = None
        if hasattr(request, 'loop_id') and request.loop_id:
            loop = loops_storage.get_loop(request.loop_id)
            if loop:
                current_pid_params = {
                    'pb': loop.get('pb', 100.0),
                    'ti': loop.get('ti', 20.0),
                    'td': loop.get('td', 0.0)
                }
        
        # Handle model type selection
        if request.model_type and request.model_type != 'auto':
            # User specified a model type - use custom tuning with forced model
            tuning_result = tune_with_forced_model(
                identifier, t, pv, sv, mv, setpoint,
                tuning_method, control_mode, request.model_type,
                request.enable_segmentation,
                current_pid_params  # 传入当前PID参数
            )
        else:
            # Auto detect model type
            tuning_result = identifier.auto_tune_from_json(
                t, pv, setpoint, tuning_method,
                mode=control_mode,
                u_data=mv,
                auto_detect=True,
                sv_array=sv,
                enable_setpoint_segmentation=request.enable_segmentation,
                current_pid_params=current_pid_params  # 传入当前PID参数
            )
        
        if tuning_result is None:
            logger.info("数据已稳态，无需整定")
            return JSONResponse({
                "success": True,
                "is_steady_state": True,
                "message": "数据已处于稳态，无需整定",
                "data": {
                    "t": t.tolist(),
                    "pv": pv.tolist(),
                    "mv": mv.tolist() if mv is not None else None,
                    "sv": sv.tolist()
                }
            })
        
        param_update_index = calculate_param_update_point(t, pv, sv)
        param_update_time = float(t[param_update_index])
        
        logger.info(f"整定结果: Pb={tuning_result.get('pb', 0):.1f}%, Ti={tuning_result.get('ti', 0):.1f}s, Td={tuning_result.get('td', 0):.1f}s")
        
        # Extract results
        response = {
            "success": True,
            "is_steady_state": False,
            "tuning_result": {
                "pb": float(tuning_result.get('pb', 0)),
                "ti": float(tuning_result.get('ti', 0)),
                "td": float(tuning_result.get('td', 0)),
                "model_type": tuning_result.get('model_type', 'fopdt'),
                "model_params": [float(p) for p in tuning_result.get('params', [])],
                "scenario": tuning_result.get('scenario', 'unknown'),
                "mode": tuning_result.get('mode', 'unknown'),
                "param_update_index": param_update_index,
                "param_update_time": param_update_time,
            },
            "data": {
                "t": t.tolist(),
                "pv": pv.tolist(),
                "mv": mv.tolist() if mv is not None else None,
                "sv": sv.tolist()
            }
        }
        
        # Handle segmented results
        if 'all_segments_results' in tuning_result:
            segments = []
            for idx, seg in enumerate(tuning_result['all_segments_results'], 1):
                segments.append({
                    "segment_index": idx,
                    "segment_indices": seg.get('segment_indices', [0, len(t)]),
                    "pb": float(seg.get('pb', 0)),
                    "ti": float(seg.get('ti', 0)),
                    "td": float(seg.get('td', 0)),
                })
            response["segments"] = segments
            logger.debug(f"分段整定: {len(segments)} 段")
        
        # 如果有关联的回路ID，更新回路参数并下发到OPC UA
        if hasattr(request, 'loop_id') and request.loop_id:
            try:
                new_pb = float(tuning_result.get('pb', 0))
                new_ti = float(tuning_result.get('ti', 0))
                new_td = float(tuning_result.get('td', 0))
                
                # 更新回路参数
                loops_storage.update_loop(request.loop_id, {
                    'pid_params': {'pb': new_pb, 'ti': new_ti, 'td': new_td},
                    'updated_at': datetime.now().isoformat()
                })
                
                # 下发参数到OPC UA
                await _write_pid_to_opcua(request.loop_id, new_pb, new_ti, new_td, force_write=True)
                
                # 进入稳定期状态
                loops_storage.update_loop(request.loop_id, {
                    'stability_status': {
                        'is_unsteady': False,
                        'is_retuning': True,
                        'state': 'STABILIZING',
                        'retuning_start_time': datetime.now().isoformat(),
                        'last_check': datetime.now().isoformat()
                    }
                })
                await _write_state_to_opcua(request.loop_id, "STABILIZING")
                
                # 同步清空 auto_tuning_system 的 disturb_data
                if auto_tuning_system and request.loop_id in auto_tuning_system.loop_states:
                    state_info = auto_tuning_system.loop_states[request.loop_id]
                    await auto_tuning_system._force_clear_disturb_data(request.loop_id, state_info)
                    if LoopState:
                        await auto_tuning_system._update_loop_state(request.loop_id, LoopState.STABILIZING)
                        state_info['stabilization_start_time'] = datetime.now()
                
                logger.info(f"回路 {request.loop_id} 整定完成，进入稳定期")
                
            except Exception as e:
                logger.error(f"更新回路参数失败: {e}")
        
        return JSONResponse(response)
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate")
async def simulate_pid(request: SimulationRequest):
    """
    Simulate PID control with given parameters
    """
    try:
        t = np.array(request.t)
        sv = np.array(request.sv)
        
        # ============================================================
        # 1. SV数据预处理
        # ============================================================
        sv_range = float(sv.max() - sv.min())
        sv_mean = float(np.mean(sv))
        sv_variation = sv_range / (abs(sv_mean) + 1e-6)
        use_fixed_sv = bool(sv_variation < 0.15)
        sv_original_min = float(np.array(request.sv).min())
        sv_original_max = float(np.array(request.sv).max())
        
        logger.debug(f"PID仿真: 数据点{len(request.t)}, SV变化率{sv_variation*100:.1f}%")
        
        if use_fixed_sv:
            sv = np.full_like(sv, sv_mean)
        
        # Model mapping
        MODEL_TYPE_MAP = {
            'fopdt': ModelIdentifier.fopdt_model,
            'first_order': ModelIdentifier.fopdt_model,
            'second_order': ModelIdentifier.second_order_model,
            'integral_delay': ModelIdentifier.integral_delay_model
        }
        
        system_model = MODEL_TYPE_MAP.get(request.model_type, ModelIdentifier.fopdt_model)
        model_params = tuple(request.model_params)
        
        # Handle first order model
        if request.model_type in ['fopdt', 'first_order'] and len(model_params) == 2:
            model_params = (model_params[0], model_params[1], 0.0)
        
        # Simulate
        pv_sim, mv_sim = simulate_system_with_pid(
            t, system_model, model_params, request.pid_params,
            setpoint=np.mean(sv),
            initial_pv=request.initial_pv,
            initial_mv=request.initial_mv,
            verbose=False,
            setpoint_array=sv
        )
        
        # 数据质量检查与修复
        nan_count_pv = np.sum(np.isnan(pv_sim))
        nan_count_mv = np.sum(np.isnan(mv_sim))
        
        if nan_count_pv > 0:
            nan_mask = np.isnan(pv_sim)
            valid_indices = np.where(~nan_mask)[0]
            if len(valid_indices) > 0:
                pv_sim = np.interp(np.arange(len(pv_sim)), valid_indices, pv_sim[valid_indices])
            else:
                pv_sim = np.full_like(pv_sim, request.initial_pv)
            logger.debug(f"PV修复: {nan_count_pv}个NaN")
        
        if nan_count_mv > 0:
            nan_mask = np.isnan(mv_sim)
            valid_indices = np.where(~nan_mask)[0]
            if len(valid_indices) > 0:
                mv_sim = np.interp(np.arange(len(mv_sim)), valid_indices, mv_sim[valid_indices])
            else:
                mv_sim = np.full_like(mv_sim, request.initial_mv)
            logger.debug(f"MV修复: {nan_count_mv}个NaN")
        
        return JSONResponse({
            "success": True,
            "pv": pv_sim.tolist(),
            "mv": mv_sim.tolist(),
            "sv": sv.tolist(),  # 返回处理后的SV（如果使用了固定值，这里就是固定值数组）
            "sv_fixed": use_fixed_sv,  # 标记是否使用了固定SV（已经是Python bool）
            "sv_original_range": [sv_original_min, sv_original_max]  # 原始SV范围（已经是Python float）
        })
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class EvaluationRequest(BaseModel):
    """Evaluation request model"""
    pv: List[float]
    sv: List[float]
    mv: List[float]
    pid_params: Optional[Dict[str, float]] = None  # PID参数 {pb, ti, td}


class BatchTuningRequest(BaseModel):
    """Batch tuning request model"""
    files: List[Dict[str, Any]]  # List of {name, data}
    tuning_method: str = "LAMBDA"
    control_mode: str = "STANDARD"
    model_type: Optional[str] = None
    enable_segmentation: bool = True


class ParameterComparisonRequest(BaseModel):
    """Parameter comparison request model"""
    scenarios: List[Dict[str, Any]]  # List of {name, pv, sv, mv}


@app.post("/api/evaluate")
async def evaluate_pid(request: EvaluationRequest):
    """
    Evaluate PID performance on simulated data
    
    重要：此接口评估的是新PID参数下的仿真数据，不是历史数据
    
    Args:
        request.pv: 使用新PID参数仿真得到的PV数据
        request.sv: 原始的设定值数据
        request.mv: 使用新PID参数仿真得到的MV数据
    
    Returns:
        评估指标，包括综合评分、稳态误差、IAE等
    """
    try:
        # 转换为numpy数组
        pv_array = np.array(request.pv)  # 仿真PV（新参数）
        sv_array = np.array(request.sv)  # 原始SV
        mv_array = np.array(request.mv)  # 仿真MV（新参数）
        
        print(f"📊 评估新参数性能:")
        print(f"   - PV数据点数: {len(pv_array)}")
        print(f"   - SV数据点数: {len(sv_array)}")
        print(f"   - MV数据点数: {len(mv_array)}")
        
        # 使用PIDEvaluator评估性能
        evaluator = PIDEvaluator(settling_band=0.02, settling_duration=50)
        
        # 显示排除信息（与测试脚本保持一致）
        eval_start = evaluator._find_steady_state_start(pv_array, sv_array)
        if eval_start > 0:
            print(f"   ℹ️  排除SV调整期间: 前 {eval_start} 个点（索引 0-{eval_start-1}）")
            print(f"   ℹ️  实际评估点数: {len(pv_array) - eval_start} 个点")
        else:
            print(f"   ℹ️  无需排除，全段评估: {len(pv_array)} 个点")
        
        # 传递PID参数给评估器
        pid_params = request.pid_params if hasattr(request, 'pid_params') else None
        metrics = evaluator.evaluate(pv_array, sv_array, mv_array, exclude_sv_transition=True, pid_params=pid_params)
        
        # 如果有参数惩罚，打印详情
        if pid_params:
            penalty = evaluator._calculate_parameter_penalty(pid_params)
            if penalty > 0:
                print(f"   ⚠️  参数合理性惩罚: -{penalty:.1f}分")
                print(f"      Pb={pid_params.get('pb', 'N/A')}, Ti={pid_params.get('ti', 'N/A')}, Td={pid_params.get('td', 'N/A')}")
        
        # 计算高级指标
        advanced_metrics = calculate_advanced_metrics(pv_array, sv_array, mv_array)
        
        print(f"   ✅ 评估完成，综合评分: {metrics.overall_score:.1f} ({metrics.grade})")
        
        return JSONResponse({
            "success": True,
            "metrics": {
                "overall_score": float(metrics.overall_score),
                "grade": metrics.grade,
                "steady_state_error": float(metrics.steady_state_error),
                "iae": float(metrics.iae),
                "oscillation_count": int(metrics.oscillation_count),
                "tv": float(metrics.tv),
                "ise": float(metrics.ise),
                "max_control_effort": float(metrics.max_control_effort),
                "max_oscillation_amplitude": float(metrics.max_oscillation_amplitude),
                **advanced_metrics
            }
        })
        
    except Exception as e:
        print(f"❌ 评估失败: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Upload JSON file for tuning
    """
    try:
        content = await file.read()
        data = json.loads(content)
        
        if 'data' not in data:
            raise HTTPException(status_code=400, detail="JSON must contain 'data' field")
        
        return JSONResponse({
            "success": True,
            "data": data['data'],
            "filename": file.filename
        })
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def calculate_advanced_metrics(pv: np.ndarray, sv: np.ndarray, mv: np.ndarray) -> Dict[str, float]:
    """
    计算高级性能指标：调节时间、超调量、上升时间等
    """
    metrics = {}
    
    try:
        # 1. 调节时间 (Settling Time) - 进入并保持在±2%误差带内的时间
        settling_band = 0.02
        final_value = sv[-1] if len(sv) > 0 else 0
        errors = np.abs(pv - final_value) / (abs(final_value) + 1e-6)
        
        settling_index = len(pv) - 1
        for i in range(len(pv) - 1, -1, -1):
            if errors[i] > settling_band:
                settling_index = i
                break
        
        metrics['settling_time_index'] = int(settling_index)
        metrics['settling_time_percentage'] = float(settling_index / len(pv) * 100)
        
        # 2. 超调量 (Overshoot) - 最大超出设定值的百分比
        if len(sv) > 0:
            sv_changes = np.where(np.abs(np.diff(sv)) > 0.1)[0]
            if len(sv_changes) > 0:
                change_idx = sv_changes[0]
                pv_after_change = pv[change_idx:]
                sv_after_change = sv[change_idx:]
                
                if len(pv_after_change) > 0 and len(sv_after_change) > 0:
                    target = sv_after_change[-1]
                    if sv_after_change[0] < target:  # 上升
                        overshoot = (np.max(pv_after_change) - target) / (abs(target) + 1e-6) * 100
                    else:  # 下降
                        overshoot = (target - np.min(pv_after_change)) / (abs(target) + 1e-6) * 100
                    metrics['overshoot_percentage'] = float(max(0, overshoot))
                else:
                    metrics['overshoot_percentage'] = 0.0
            else:
                metrics['overshoot_percentage'] = 0.0
        else:
            metrics['overshoot_percentage'] = 0.0
        
        # 3. 上升时间 (Rise Time) - 从10%到90%的时间
        if len(sv) > 0:
            sv_changes = np.where(np.abs(np.diff(sv)) > 0.1)[0]
            if len(sv_changes) > 0:
                change_idx = sv_changes[0]
                pv_after_change = pv[change_idx:]
                sv_after_change = sv[change_idx:]
                
                if len(pv_after_change) > 10 and len(sv_after_change) > 0:
                    initial = pv_after_change[0]
                    target = sv_after_change[-1]
                    range_val = target - initial
                    
                    ten_percent = initial + 0.1 * range_val
                    ninety_percent = initial + 0.9 * range_val
                    
                    rise_start = 0
                    rise_end = len(pv_after_change) - 1
                    
                    for i, val in enumerate(pv_after_change):
                        if (range_val > 0 and val >= ten_percent) or (range_val < 0 and val <= ten_percent):
                            rise_start = i
                            break
                    
                    for i, val in enumerate(pv_after_change):
                        if (range_val > 0 and val >= ninety_percent) or (range_val < 0 and val <= ninety_percent):
                            rise_end = i
                            break
                    
                    metrics['rise_time_index'] = int(rise_end - rise_start)
                    metrics['rise_time_percentage'] = float((rise_end - rise_start) / len(pv_after_change) * 100)
                else:
                    metrics['rise_time_index'] = 0
                    metrics['rise_time_percentage'] = 0.0
            else:
                metrics['rise_time_index'] = 0
                metrics['rise_time_percentage'] = 0.0
        else:
            metrics['rise_time_index'] = 0
            metrics['rise_time_percentage'] = 0.0
        
        # 4. 峰值时间 (Peak Time) - 达到最大值的时间
        if len(pv) > 0:
            peak_index = int(np.argmax(np.abs(pv - sv)))
            metrics['peak_time_index'] = peak_index
            metrics['peak_time_percentage'] = float(peak_index / len(pv) * 100)
        else:
            metrics['peak_time_index'] = 0
            metrics['peak_time_percentage'] = 0.0
        
        # 5. 稳态误差带宽
        if len(pv) > 10:
            tail_pv = pv[-min(100, len(pv)//4):]
            tail_sv = sv[-min(100, len(sv)//4):]
            steady_error_band = float(np.std(tail_pv - tail_sv))
            metrics['steady_error_band'] = steady_error_band
        else:
            metrics['steady_error_band'] = 0.0
        
    except Exception as e:
        print(f"⚠️ 计算高级指标失败: {e}")
        traceback.print_exc()
    
    return metrics


@app.post("/api/batch_tune")
async def batch_tune(request: BatchTuningRequest):
    """
    批量处理多个文件的PID整定
    """
    try:
        results = []
        
        for file_data in request.files:
            file_name = file_data.get('name', 'unknown')
            data = file_data.get('data', [])
            
            print(f"\n处理文件: {file_name}")
            
            try:
                # Parse data
                t, pv, mv, sv = parse_json_data(data)
                
                # Initialize tuning
                identifier = SystemIdentifier()
                setpoint = np.mean(sv)
                tuning_method = getattr(TuningMethod, request.tuning_method, TuningMethod.LAMBDA)
                control_mode = getattr(Mode, request.control_mode, Mode.STANDARD)
                
                # Tune
                if request.model_type and request.model_type != 'auto':
                    tuning_result = tune_with_forced_model(
                        identifier, t, pv, sv, mv, setpoint,
                        tuning_method, control_mode, request.model_type,
                        request.enable_segmentation
                    )
                else:
                    tuning_result = identifier.auto_tune_from_json(
                        t, pv, setpoint, tuning_method,
                        mode=control_mode,
                        u_data=mv,
                        auto_detect=True,
                        sv_array=sv,
                        enable_setpoint_segmentation=request.enable_segmentation
                    )
                
                if tuning_result:
                    results.append({
                        'file_name': file_name,
                        'success': True,
                        'is_steady': False,
                        'pb': float(tuning_result.get('pb', 0)),
                        'ti': float(tuning_result.get('ti', 0)),
                        'td': float(tuning_result.get('td', 0)),
                        'model_type': tuning_result.get('model_type', 'unknown'),
                        'data_points': len(t),
                        'scenario': tuning_result.get('scenario', 'unknown')
                    })
                else:
                    # 检查是否是稳态情况
                    # 如果是稳态，标记为成功但无需整定
                    results.append({
                        'file_name': file_name,
                        'success': True,
                        'is_steady': True,
                        'pb': None,
                        'ti': None,
                        'td': None,
                        'model_type': 'steady_state',
                        'data_points': len(t),
                        'message': '数据已稳态，无需整定'
                    })
                    
            except Exception as e:
                error_msg = str(e)
                # 提供更详细的错误信息
                if 'infeasible' in error_msg.lower():
                    error_msg = '模型辨识失败：数据不适合当前模型类型，建议尝试其他模型或检查数据质量'
                elif 'timeout' in error_msg.lower():
                    error_msg = '处理超时：数据量过大或计算复杂度过高'
                elif 'json' in error_msg.lower():
                    error_msg = '数据格式错误：JSON文件格式不正确'
                
                results.append({
                    'file_name': file_name,
                    'success': False,
                    'is_steady': False,
                    'error': error_msg,
                    'data_points': len(t) if 't' in locals() else 0
                })
                print(f"❌ 处理文件 {file_name} 失败: {error_msg}")
        
        # 统计
        success_count = sum(1 for r in results if r.get('success', False))
        
        return JSONResponse({
            'success': True,
            'results': results,
            'statistics': {
                'total': len(results),
                'success': success_count,
                'failed': len(results) - success_count
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/compare_parameters")
async def compare_parameters(request: ParameterComparisonRequest):
    """
    对比多组PID参数的性能
    """
    try:
        evaluator = PIDEvaluator(settling_band=0.02, settling_duration=50)
        
        comparison_results = []
        
        for scenario in request.scenarios:
            name = scenario.get('name', 'Unknown')
            pv = np.array(scenario.get('pv', []))
            sv = np.array(scenario.get('sv', []))
            mv = np.array(scenario.get('mv', []))
            
            metrics = evaluator.evaluate(pv, sv, mv, exclude_sv_transition=True)
            advanced = calculate_advanced_metrics(pv, sv, mv)
            
            comparison_results.append({
                'name': name,
                'score': float(metrics.overall_score),
                'grade': metrics.grade,
                'steady_state_error': float(metrics.steady_state_error),
                'iae': float(metrics.iae),
                'oscillation_count': int(metrics.oscillation_count),
                'overshoot': advanced.get('overshoot_percentage', 0.0),
                'settling_time': advanced.get('settling_time_percentage', 0.0)
            })
        
        # 排序
        comparison_results.sort(key=lambda x: x['score'], reverse=True)
        
        return JSONResponse({
            'success': True,
            'results': comparison_results,
            'best': comparison_results[0] if comparison_results else None
        })
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class ModelComparisonRequest(BaseModel):
    """Model comparison request"""
    data: List[Dict[str, Any]]
    tuning_method: str = "LAMBDA"
    control_mode: str = "STANDARD"

class AIQuestionRequest(BaseModel):
    question: str
    context: Optional[Dict[str, Any]] = None  # 当前整定结果、指标等上下文

class AIOptimizeRequest(BaseModel):
    current_params: Dict[str, float]  # 当前PID参数
    metrics: Dict[str, Any]  # 性能指标
    data: List[Dict[str, Any]]  # 原始数据
    constraints: Optional[Dict[str, Any]] = None  # 优化约束


@app.post("/api/compare_models")
async def compare_models(request: ModelComparisonRequest):
    """
    对比多种模型的拟合效果
    """
    try:
        print("\n" + "="*60)
        print("🔬 多模型对比分析")
        print("="*60)
        
        # Parse data
        t, pv, mv, sv = parse_json_data(request.data)
        
        identifier = SystemIdentifier()
        setpoint = np.mean(sv)
        tuning_method = getattr(TuningMethod, request.tuning_method, TuningMethod.LAMBDA)
        control_mode = getattr(Mode, request.control_mode, Mode.STANDARD)
        
        # 要对比的模型类型
        model_types = ['fopdt', 'second_order', 'integral_delay']
        model_names = {
            'fopdt': '一阶惯性+纯滞后 (FOPDT)',
            'second_order': '二阶系统',
            'integral_delay': '积分+延迟'
        }
        results = []
        
        for model_type in model_types:
            print(f"\n📊 测试模型: {model_type}")
            
            try:
                # 强制使用指定模型进行整定
                tuning_result = tune_with_forced_model(
                    identifier, t, pv, sv, mv, setpoint,
                    tuning_method, control_mode, model_type,
                    enable_segmentation=False  # 对比时不分段
                )
                
                if tuning_result:
                    # 1. 获取模型参数和拟合误差
                    model_params = tuning_result.get('params', [])
                    fit_error = tuning_result.get('fit_error', 0.0)
                    fit_rmse = tuning_result.get('fit_rmse', 0.0)
                    
                    print(f"  📊 模型拟合: MAE={fit_error:.4f}, RMSE={fit_rmse:.4f}")
                    
                    # 2. 使用整定的PID参数进行仿真（评估控制性能）
                    pid_params = {
                        'pb': tuning_result.get('pb', 100),
                        'ti': tuning_result.get('ti', 50),
                        'td': tuning_result.get('td', 0)
                    }
                    
                    # 验证模型参数
                    if len(model_params) == 0 or any(np.isnan(p) or np.isinf(p) for p in model_params):
                        print(f"  ⚠️ {model_type}: 模型参数无效，跳过")
                        raise ValueError("模型参数包含无效值")
                    
                    # 计算合理的初始PV值
                    # 策略：使用接近SV的PV值作为初始值，而不是数据集第一个点
                    # 1. 优先使用整定段前的稳态均值
                    initial_pv = pv[0]
                    param_update_idx = tuning_result.get('param_update_index', None)
                    
                    if param_update_idx and param_update_idx > 0:
                        # 使用整定段前70%-100%区间的PV均值
                        steady_start = max(0, int(param_update_idx * 0.7))
                        steady_end = param_update_idx
                        if steady_end > steady_start:
                            initial_pv = float(np.mean(pv[steady_start:steady_end]))
                            print(f"  📍 使用稳态PV均值作为初始值: {initial_pv:.3f} (索引 {steady_start}-{steady_end})")
                    else:
                        # 2. 如果没有整定段信息，使用最接近SV的PV段的均值
                        # 找到PV最接近SV的连续段（至少30个点）
                        window_size = min(30, len(pv) // 10)
                        if window_size > 0:
                            # 计算滑动窗口的均值
                            pv_means = np.convolve(pv, np.ones(window_size)/window_size, mode='valid')
                            # 找到最接近SV的窗口
                            closest_idx = np.argmin(np.abs(pv_means - setpoint))
                            # 使用该窗口的PV均值
                            initial_pv = float(np.mean(pv[closest_idx:closest_idx+window_size]))
                            print(f"  📍 使用最接近SV的PV段均值作为初始值: {initial_pv:.3f} (目标SV={setpoint:.3f})")
                    
                    # 执行PID控制仿真
                    try:
                        sim_pv, sim_mv = simulate_system_with_pid(
                            t=t,
                            system_model=tuning_result.get('model_type', model_type),
                            model_params=model_params,
                            pid_params=pid_params,
                            setpoint=setpoint,
                            initial_pv=initial_pv,
                            initial_mv=mv[0] if mv is not None and len(mv) > 0 else 0,
                            setpoint_array=sv,
                            verbose=False
                        )
                    except Exception as sim_error:
                        print(f"  ⚠️ {model_type}: 仿真异常 - {str(sim_error)}")
                        raise ValueError(f"仿真失败: {str(sim_error)}")
                    
                    # 验证仿真数据
                    if np.any(np.isnan(sim_pv)) or np.any(np.isinf(sim_pv)):
                        print(f"  ⚠️ {model_type}: 仿真PV包含NaN或Inf值")
                        print(f"     模型参数: {model_params}")
                        print(f"     PID参数: Pb={pid_params['pb']}, Ti={pid_params['ti']}, Td={pid_params['td']}")
                        print(f"     仿真前几个值: {sim_pv[:min(10, len(sim_pv))]}")
                        raise ValueError("仿真数据包含无效值")
                    
                    # 3. 评估PID控制性能（仿真PV vs SV）
                    evaluator = PIDEvaluator(settling_band=0.02, settling_duration=50)
                    metrics = evaluator.evaluate(sim_pv, sv, sim_mv, exclude_sv_transition=True)
                    
                    print(f"  📊 仿真PV范围: {np.min(sim_pv):.2f} ~ {np.max(sim_pv):.2f}")
                    
                    results.append({
                        'model_type': model_type,
                        'model_name': model_names.get(model_type, model_type),
                        'success': True,
                        'pid_params': {
                            'pb': float(tuning_result.get('pb', 0)),
                            'ti': float(tuning_result.get('ti', 0)),
                            'td': float(tuning_result.get('td', 0))
                        },
                        'model_params': [float(p) for p in tuning_result.get('params', [])],
                        'fit_error': float(fit_error),
                        'fit_rmse': float(fit_rmse),
                        'performance': {
                            'score': float(metrics.overall_score),
                            'grade': metrics.grade,
                            'iae': float(metrics.iae),
                            'oscillation_count': int(metrics.oscillation_count)
                        },
                        'simulated_pv': sim_pv.tolist(),
                        'simulated_mv': sim_mv.tolist()
                    })
                    
                    print(f"  ✅ {model_type}: 拟合误差={fit_error:.4f}, 评分={metrics.overall_score:.1f}")
                else:
                    results.append({
                        'model_type': model_type,
                        'model_name': model_names.get(model_type, model_type),
                        'success': False,
                        'error': '模型辨识失败'
                    })
                    print(f"  ❌ {model_type}: 辨识失败")
                    
            except Exception as e:
                results.append({
                    'model_type': model_type,
                    'model_name': model_names.get(model_type, model_type),
                    'success': False,
                    'error': str(e)
                })
                print(f"  ❌ {model_type}: {str(e)}")
                traceback.print_exc()
        
        # 排序：按拟合误差排序
        successful_results = [r for r in results if r.get('success', False)]
        if successful_results:
            successful_results.sort(key=lambda x: x.get('fit_error', float('inf')))
            best_model = successful_results[0]
        else:
            best_model = None
        
        print("\n" + "="*60)
        print(f"✅ 对比完成，成功: {len(successful_results)}/{len(results)}")
        if best_model:
            print(f"🏆 最佳模型: {best_model['model_name']}")
            print(f"   拟合误差: {best_model['fit_error']:.4f}")
        print("="*60)
        
        # 清理NaN值，避免JSON序列化错误
        def clean_nan(obj):
            if isinstance(obj, dict):
                return {k: clean_nan(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [clean_nan(item) for item in obj]
            elif isinstance(obj, float):
                if np.isnan(obj) or np.isinf(obj):
                    return None
                return obj
            return obj
        
        results = clean_nan(results)
        best_model = clean_nan(best_model)
        
        return JSONResponse({
            'success': True,
            'results': results,
            'best_model': best_model,
            'original_data': {
                't': t.tolist(),
                'pv': pv.tolist(),
                'sv': sv.tolist()
            }
        })
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai/question")
async def ai_question(request: AIQuestionRequest):
    """
    AI智能问答系统
    """
    try:
        if not AI_API_KEY:
            return JSONResponse({
                "success": False,
                "error": "AI API Key未配置，请设置OPENAI_API_KEY环境变量"
            })
        
        import httpx
        
        # 构建系统提示词
        system_prompt = """你是一个专业的PID控制系统专家和参数优化顾问。

【核心要求 - 必须严格遵守】
1. 当用户要求参数优化时，你**必须**给出**唯一的、具体的数值**，不能给范围
2. 例如：正确 ✅ "Pb: 25.0% → 30.0%"，错误 ❌ "Pb调整到30%或35%"
3. 例如：正确 ✅ "Ti: 60.0s → 45.0s"，错误 ❌ "Ti调整至40-50秒"
4. 每个参数只能有一个建议值，不能有"或"、"范围"等表述
5. 如果用户提供了当前参数值，你必须在建议中明确写出"当前值 → 建议值"

PID参数说明：
- Pb (比例带): 控制器的比例增益，单位%，值越小增益越大，典型范围10-200%
- Ti (积分时间): 消除稳态误差的时间常数，单位秒，典型范围5-300s
- Td (微分时间): 预测和抑制偏差变化的时间常数，单位秒，典型范围0-50s

性能指标说明：
- overall_score: 综合评分(0-100)，反映整体控制质量
- steady_state_error: 稳态误差，越小越好
- iae: 积分绝对误差，反映累积偏差
- oscillation_count: 振荡次数，越少越好
- tv: 控制变化总和，反映控制平滑性

参数优化策略：
1. **超调过大** (overshoot > 20%):
   - 增大Pb (比例带) 10-20%，降低增益
   - 或增大Td (微分时间) 20-50%，增强阻尼
   
2. **响应太慢** (settling_time > 目标时间):
   - 减小Pb 10-15%，增大增益
   - 或减小Ti 15-25%，加快积分作用
   
3. **振荡不稳** (oscillation_count > 10):
   - 增大Pb 15-25%，降低增益
   - 减小Td 30-50%或设为0，减少微分作用
   
4. **稳态误差大** (steady_state_error > 0.02):
   - 减小Ti 20-30%，增强积分作用
   - 检查是否存在积分饱和
   
5. **控制变化剧烈** (tv值很大):
   - 增大Pb 10-20%，降低控制强度
   - 减小Td 或设为0，减少微分噪声

**分析步骤**：
1. 查看仿真数据摘要中的final_error（最终误差）
2. 查看metrics中的overall_score和各项指标
3. 识别主要问题（超调、振荡、稳态误差等）
4. 给出具体的参数调整建议（包括调整方向和幅度）
5. 解释为什么这样调整

**输出格式要求（必须严格遵守）**：
📊 **走势分析**：
- 当前PV最终值：[具体数值]
- 目标SV：[具体数值]
- 最终误差：[具体数值]
- 综合评分：[具体分数]分（[等级]）
- 主要表现：[描述]

⚠️ **主要问题**：
1. [具体问题1，包含数值]
2. [具体问题2，包含数值]

🎯 **优化建议**（必须给出具体数值）：
- Pb: [当前值]% → [建议值]% (调整[+/-X]%，理由：[具体原因])
- Ti: [当前值]s → [建议值]s (调整[+/-X]%，理由：[具体原因])
- Td: [当前值]s → [建议值]s (调整[+/-X]%，理由：[具体原因])

📈 **预期效果**：
- 稳态误差：[当前值] → [预期值]
- 综合评分：[当前分] → [预期分]
- 其他改进：[具体描述]

**重要**：
1. 必须从context中读取当前的pid_params值（Pb、Ti、Td）
2. 必须从context中读取metrics值（overall_score、steady_state_error等）
3. 必须从context中读取simulation_summary值（pv_final、sv_final、final_error）
4. 所有建议值必须是具体数字，不能用"适当增加"等模糊表述
5. 如果某个参数不需要调整，也要明确写出"保持X.XX不变"

**正确示例** ✅：
🎯 **优化建议**：
- Pb: 25.00% → 30.00% (增加20%，理由：当前振荡次数15次偏多，增大比例带可降低增益)
- Ti: 46.25s → 35.00s (减少24%，理由：稳态误差0.097偏大，减小积分时间可加快消除误差)
- Td: 0.00s → 0.00s (保持0.00s不变，理由：当前系统无超调问题，不需要微分作用)

**错误示例** ❌（绝对不要这样写）：
- Pb: 当前为25%，可以调整到30%或35%  ← 错误！不能给范围
- Ti: 建议调整至40-50秒  ← 错误！必须给出唯一值
- Td: 可以设定一个适当的微分时间，如1-5秒  ← 错误！必须给出具体数值

**记住**：每个参数必须有且只有一个建议值！格式必须是"当前值 → 建议值"！"""

        # 构建用户消息
        user_message = request.question
        if request.context:
            # 格式化context，使其更易读
            context_str = "\n\n=== 当前系统状态（请仔细阅读并使用这些数据） ===\n"
            
            if 'pid_params' in request.context:
                params = request.context['pid_params']
                context_str += f"\n【当前PID参数】\n"
                context_str += f"- Pb (比例带): {params.get('pb', 'N/A')}%\n"
                context_str += f"- Ti (积分时间): {params.get('ti', 'N/A')}s\n"
                context_str += f"- Td (微分时间): {params.get('td', 'N/A')}s\n"
            
            if 'model_info' in request.context:
                model = request.context['model_info']
                context_str += f"\n【模型信息】\n"
                context_str += f"- 模型类型: {model.get('model_type', 'N/A')}\n"
                context_str += f"- 模型参数: {model.get('model_params', 'N/A')}\n"
            
            if 'metrics' in request.context:
                metrics = request.context['metrics']
                context_str += f"\n【性能指标】\n"
                context_str += f"- 综合评分: {metrics.get('overall_score', 'N/A')}分\n"
                context_str += f"- 等级: {metrics.get('grade', 'N/A')}\n"
                context_str += f"- 稳态误差: {metrics.get('steady_state_error', 'N/A')}\n"
                context_str += f"- 振荡次数: {metrics.get('oscillation_count', 'N/A')}\n"
                context_str += f"- IAE: {metrics.get('iae', 'N/A')}\n"
                context_str += f"- TV: {metrics.get('tv', 'N/A')}\n"
            
            if 'simulation_summary' in request.context:
                sim = request.context['simulation_summary']
                context_str += f"\n【仿真数据摘要】\n"
                context_str += f"- PV最终值: {sim.get('pv_final', 'N/A')}\n"
                context_str += f"- SV最终值: {sim.get('sv_final', 'N/A')}\n"
                context_str += f"- 最终误差: {sim.get('final_error', 'N/A')}\n"
                context_str += f"- PV范围: {sim.get('pv_range', 'N/A')}\n"
                context_str += f"- MV范围: {sim.get('mv_range', 'N/A')}\n"
            
            context_str += "\n=== 请基于以上数据给出具体的参数调整数值 ===\n"
            context_str += "\n⚠️ 重要提醒：\n"
            context_str += "- 你必须给出唯一的具体数值，格式：Pb: X.XX% → Y.YY%\n"
            context_str += "- 不能给范围（如30-35%），不能用'或'（如30%或35%）\n"
            context_str += "- 每个参数只能有一个建议值\n"
            user_message += context_str
            
            # 打印日志，方便调试
            print(f"\n📤 发送给AI的上下文信息:")
            print(context_str)
        
        # 调用AI API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{AI_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,  # 降低温度，使输出更精确和确定
                    "max_tokens": 1500   # 增加token限制，允许更详细的回答
                }
            )
        
        if response.status_code == 200:
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            return JSONResponse({
                "success": True,
                "answer": answer,
                "model": AI_MODEL
            })
        else:
            return JSONResponse({
                "success": False,
                "error": f"AI API调用失败: {response.status_code} - {response.text}"
            })
            
    except Exception as e:
        print(f"AI问答错误: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/ai/optimize")
async def ai_optimize(request: AIOptimizeRequest):
    """
    AI参数优化建议
    """
    try:
        if not AI_API_KEY:
            return JSONResponse({
                "success": False,
                "error": "AI API Key未配置"
            })
        
        import httpx
        
        # 构建优化请求的提示词
        system_prompt = """你是一个PID控制参数优化专家。根据当前参数和性能指标，提供优化建议。

你需要：
1. 分析当前参数的问题
2. 提供具体的参数调整建议
3. 解释调整的原因
4. 预测调整后的效果

返回JSON格式：
{
    "analysis": "当前参数分析",
    "issues": ["问题1", "问题2"],
    "suggestions": [
        {
            "parameter": "pb/ti/td",
            "current": 当前值,
            "suggested": 建议值,
            "reason": "调整原因"
        }
    ],
    "expected_improvement": "预期改进效果"
}"""

        # 构建用户消息
        user_message = f"""请分析并优化以下PID参数：

当前参数：
- Pb (比例带): {request.current_params.get('pb', 0)}%
- Ti (积分时间): {request.current_params.get('ti', 0)}s
- Td (微分时间): {request.current_params.get('td', 0)}s

性能指标：
{json.dumps(request.metrics, indent=2, ensure_ascii=False)}

请提供优化建议。"""

        if request.constraints:
            user_message += f"\n\n约束条件：\n{json.dumps(request.constraints, indent=2, ensure_ascii=False)}"
        
        # 调用AI API
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{AI_API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.3,  # 较低温度，更确定性的输出
                    "max_tokens": 1500
                }
            )
        
        if response.status_code == 200:
            result = response.json()
            answer = result["choices"][0]["message"]["content"]
            
            # 尝试解析JSON
            try:
                # 提取JSON部分
                import re
                json_match = re.search(r'\{.*\}', answer, re.DOTALL)
                if json_match:
                    optimization = json.loads(json_match.group())
                else:
                    optimization = {"raw_answer": answer}
            except:
                optimization = {"raw_answer": answer}
            
            return JSONResponse({
                "success": True,
                "optimization": optimization,
                "model": AI_MODEL
            })
        else:
            return JSONResponse({
                "success": False,
                "error": f"AI API调用失败: {response.status_code}"
            })
            
    except Exception as e:
        print(f"AI优化错误: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.get("/api/ai/config")
async def get_ai_config():
    """
    获取AI配置状态
    """
    return JSONResponse({
        "enabled": bool(AI_API_KEY),
        "model": AI_MODEL if AI_API_KEY else None,
        "api_base": AI_API_BASE if AI_API_KEY else None
    })


# ============================================================================
# 多回路管理API
# ============================================================================

class LoopCreateRequest(BaseModel):
    """创建回路请求"""
    name: str
    description: str = ""
    area: str = "默认区域"
    data_source: str = "file"  # "file" 或 "opcua"
    opcua_config: Optional[Dict] = None  # OPC UA配置


class LoopUpdateRequest(BaseModel):
    """更新回路请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    area: Optional[str] = None
    pid_params: Optional[Dict] = None
    performance: Optional[Dict] = None
    status: Optional[str] = None
    stability_status: Optional[Dict] = None  # 添加稳定性状态字段


@app.get("/api/loops/statistics/summary")
async def get_loops_statistics():
    """获取回路统计信息"""
    try:
        stats = loops_storage.get_statistics()
        return JSONResponse({
            "success": True,
            "statistics": stats
        })
    except Exception as e:
        print(f"获取统计信息失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.get("/api/loops")
async def get_loops(area: Optional[str] = None):
    """获取回路列表"""
    try:
        if area:
            loops = loops_storage.get_loops_by_area(area)
        else:
            loops = loops_storage.get_all_loops()
        
        # 🔧 调试：打印每个回路的稳定性状态
        for loop in loops:
            if loop.get('data_source') == 'opcua':
                stability = loop.get('stability_status', {})
                print(f"  📊 [{loop.get('name')}] API返回状态: is_unsteady={stability.get('is_unsteady')}, is_retuning={stability.get('is_retuning')}")
        
        return JSONResponse({
            "success": True,
            "loops": loops,
            "total": len(loops)
        })
    except Exception as e:
        print(f"获取回路列表失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.get("/api/loops/{loop_id}")
async def get_loop(loop_id: str):
    """获取单个回路"""
    try:
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        return JSONResponse({
            "success": True,
            "loop": loop
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取回路失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops")
async def create_loop(request: LoopCreateRequest):
    """创建回路"""
    try:
        loop_data = {
            "name": request.name,
            "description": request.description,
            "area": request.area,
            "data_source": request.data_source,  # 添加数据源类型
            "pid_params": {
                "pb": 100.0,
                "ti": 50.0,
                "td": 0.0
            },
            "performance": {
                "score": 0,
                "grade": "N/A",
                "steady_error": 0
            },
            "status": "inactive"
        }
        
        # 如果是OPC UA数据源，添加配置
        if request.opcua_config:
            loop_data["opcua_config"] = request.opcua_config
        
        loop = loops_storage.add_loop(loop_data)
        
        return JSONResponse({
            "success": True,
            "loop": loop,
            "message": f"回路 '{request.name}' 创建成功"
        })
    except Exception as e:
        print(f"创建回路失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.put("/api/loops/{loop_id}")
async def update_loop(loop_id: str, request: LoopUpdateRequest):
    """更新回路"""
    try:
        updates = {}
        if request.name is not None:
            updates["name"] = request.name
        if request.description is not None:
            updates["description"] = request.description
        if request.area is not None:
            updates["area"] = request.area
        if request.pid_params is not None:
            updates["pid_params"] = request.pid_params
        if request.performance is not None:
            updates["performance"] = request.performance
        if request.status is not None:
            updates["status"] = request.status
        if request.stability_status is not None:
            updates["stability_status"] = request.stability_status
        
        loop = loops_storage.update_loop(loop_id, updates)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        return JSONResponse({
            "success": True,
            "loop": loop,
            "message": "回路更新成功"
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"更新回路失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops/{loop_id}/apply_tuning")
async def apply_tuning_to_loop(loop_id: str, request: Dict[str, Any]):
    """
    将整定结果应用到回路
    
    Args:
        loop_id: 回路ID
        request: 整定结果，包含 pid_params 和可选的 performance
    """
    try:
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        # 提取PID参数
        pid_params = request.get('pid_params', {})
        if not pid_params:
            raise HTTPException(status_code=400, detail="缺少PID参数")
        
        # 提取性能指标（如果有）
        performance = request.get('performance', {})
        
        # 更新回路
        updates = {
            'pid_params': pid_params,
            'updated_at': datetime.now().isoformat()
        }
        
        if performance:
            updates['performance'] = performance
        
        updated_loop = loops_storage.update_loop(loop_id, updates)
        
        print(f"✅ 应用整定结果到回路 {loop['name']}: Pb={pid_params.get('pb')}, Ti={pid_params.get('ti')}, Td={pid_params.get('td')}")
        
        return JSONResponse({
            "success": True,
            "loop": updated_loop,
            "message": f"整定结果已应用到回路 {loop['name']}"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"应用整定结果失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops/batch_import")
async def batch_import_loops(file: UploadFile = File(...)):
    """
    批量导入回路
    
    支持CSV/Excel格式，必需字段：
    - name: 回路名称
    - area: 所属区域
    - pv_node_id: PV节点ID
    - sv_node_id: SV节点ID
    - mv_node_id: MV节点ID
    
    可选字段：
    - description: 描述
    - pb: 比例带
    - ti: 积分时间
    - td: 微分时间
    - pid_pb_node_id: PID Pb节点ID
    - pid_ti_node_id: PID Ti节点ID
    - pid_td_node_id: PID Td节点ID
    - state_node_id: 状态节点ID
    - auto_tuning_enabled: 是否启用自动整定
    """
    try:
        # 读取文件内容
        content = await file.read()
        
        # 检测文件类型
        if file.filename.endswith('.csv'):
            # CSV文件
            text_content = content.decode('utf-8-sig')  # 支持带BOM的UTF-8
            csv_reader = csv.DictReader(io.StringIO(text_content))
            rows = list(csv_reader)
        elif file.filename.endswith(('.xlsx', '.xls')):
            # Excel文件
            import pandas as pd
            df = pd.read_excel(io.BytesIO(content))
            rows = df.to_dict('records')
        else:
            raise HTTPException(status_code=400, detail="不支持的文件格式，请使用CSV或Excel文件")
        
        if not rows:
            raise HTTPException(status_code=400, detail="文件为空或格式错误")
        
        # 批量创建回路
        created_loops = []
        failed_loops = []
        
        for idx, row in enumerate(rows, start=1):
            try:
                # 必需字段验证
                required_fields = ['name', 'area', 'pv_node_id', 'sv_node_id', 'mv_node_id']
                missing_fields = [f for f in required_fields if not row.get(f)]
                
                if missing_fields:
                    failed_loops.append({
                        'row': idx,
                        'name': row.get('name', f'第{idx}行'),
                        'error': f"缺少必需字段: {', '.join(missing_fields)}"
                    })
                    continue
                
                # 构建回路数据
                loop_data = {
                    "name": str(row['name']).strip(),
                    "description": str(row.get('description', '')).strip(),
                    "area": str(row['area']).strip(),
                    "data_source": "opcua",
                    "pid_params": {
                        "pb": float(row.get('pb', 100.0)),
                        "ti": float(row.get('ti', 50.0)),
                        "td": float(row.get('td', 0.0))
                    },
                    "performance": {
                        "score": 0,
                        "grade": "N/A",
                        "steady_error": 0
                    },
                    "status": "inactive",
                    "opcua_config": {
                        "pv_node_id": str(row['pv_node_id']).strip(),
                        "sv_node_id": str(row['sv_node_id']).strip(),
                        "mv_node_id": str(row['mv_node_id']).strip(),
                        "auto_tuning_enabled": str(row.get('auto_tuning_enabled', 'false')).lower() in ['true', '1', 'yes', '是']
                    }
                }
                
                # 可选的PID节点ID
                if row.get('pid_pb_node_id'):
                    loop_data["opcua_config"]["pid_pb_node_id"] = str(row['pid_pb_node_id']).strip()
                if row.get('pid_ti_node_id'):
                    loop_data["opcua_config"]["pid_ti_node_id"] = str(row['pid_ti_node_id']).strip()
                if row.get('pid_td_node_id'):
                    loop_data["opcua_config"]["pid_td_node_id"] = str(row['pid_td_node_id']).strip()
                if row.get('state_node_id'):
                    loop_data["opcua_config"]["state_node_id"] = str(row['state_node_id']).strip()
                
                # 创建回路
                loop = loops_storage.add_loop(loop_data)
                created_loops.append({
                    'id': loop['id'],
                    'name': loop['name'],
                    'area': loop['area']
                })
                
            except Exception as e:
                failed_loops.append({
                    'row': idx,
                    'name': row.get('name', f'第{idx}行'),
                    'error': str(e)
                })
        
        # 返回结果
        return JSONResponse({
            "success": True,
            "message": f"批量导入完成：成功 {len(created_loops)} 个，失败 {len(failed_loops)} 个",
            "created_count": len(created_loops),
            "failed_count": len(failed_loops),
            "created_loops": created_loops,
            "failed_loops": failed_loops
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"批量导入失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops/{loop_id}/trigger_retuning")
async def manual_trigger_retuning(loop_id: str):
    """手动触发重整定"""
    try:
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        # 获取采集的数据
        # 🔧 如果回路在监控中且处于DISTURBANCE状态，使用更大的limit
        data_limit = 100
        if auto_tuning_system and auto_tuning_system.is_monitoring(loop_id):
            loop_state = auto_tuning_system.loop_states.get(loop_id, {})
            current_state = loop_state.get('state')
            if current_state and current_state.name == 'DISTURBANCE':
                data_limit = 150  # 扰动状态下获取更多数据
        
        collected_data = await opcua_client.get_collected_data(loop_id, limit=data_limit)
        if not collected_data or not collected_data.get('success'):
            return JSONResponse({
                "success": False,
                "message": "无法获取采集数据"
            })
        
        data = collected_data.get('data', {})
        pv_data = np.array(data.get('pv', []))
        sv_data = np.array(data.get('sv', []))
        mv_data = np.array(data.get('mv', []))
        timestamps = data.get('timestamps', [])  # 提取时间戳
        
        if len(pv_data) < 20:
            return JSONResponse({
                "success": False,
                "message": f"数据点不足（{len(pv_data)} < 20）"
            })
        
        # 如果使用AutoTuningSystem，通过它触发
        if auto_tuning_system and auto_tuning_system.is_monitoring(loop_id):
            print(f"🎯 手动触发重整定（通过AutoTuningSystem）: {loop['name']} (ID: {loop_id})")
            success = await auto_tuning_system.manual_trigger_tuning(loop_id, pv_data, sv_data, mv_data)
            
            if success:
                return JSONResponse({
                    "success": True,
                    "message": f"已触发回路 {loop['name']} 的重整定"
                })
            else:
                return JSONResponse({
                    "success": False,
                    "message": "触发整定失败，请检查回路状态"
                })
        else:
            # 使用传统方式触发（手动整定，强制下发）
            print(f"🔄 手动触发重整定（传统方式）: {loop['name']} (ID: {loop_id})")
            asyncio.create_task(trigger_auto_retuning(loop_id, loop['name'], pv_data, sv_data, mv_data, timestamps, force_write=True))
            
            return JSONResponse({
                "success": True,
                "message": f"已触发回路 {loop['name']} 的重整定"
            })
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"触发重整定失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops/{loop_id}/toggle_auto_tuning")
async def toggle_auto_tuning(loop_id: str, request: Dict[str, Any]):
    """
    切换自动整定开关
    
    Args:
        loop_id: 回路ID
        request: {"enabled": true/false}
    """
    try:
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        enabled = request.get("enabled", False)
        
        # ═══════════════════════════════════════════════════════════
        # 🔧 自动整定开关切换逻辑
        # ═══════════════════════════════════════════════════════════
        
        # 1. 检查是否正在整定中
        stability_status = loop.get('stability_status', {})
        is_retuning = stability_status.get('is_retuning', False)
        
        if is_retuning:
            # 正在整定中，不允许切换开关
            print(f"⚠️  回路 {loop['name']} 正在整定中，拒绝切换开关")
            return JSONResponse({
                "success": False,
                "message": "回路正在整定中，请等待整定完成后再切换"
            })
        
        # 2. 更新OPC UA配置中的自动整定开关
        if loop.get("data_source") == "opcua":
            opcua_config = loop.get("opcua_config", {})
            previous_enabled = opcua_config.get("auto_tuning_enabled", False)
            
            # 🔧 添加切换中标志，防止并发切换
            opcua_config["auto_tuning_switching"] = True
            opcua_config["auto_tuning_enabled"] = enabled
            
            updates = {"opcua_config": opcua_config}
            loop = loops_storage.update_loop(loop_id, updates)
            
            status_text = "启用" if enabled else "禁用"
            print(f"🔧 回路 {loop['name']} (ID: {loop_id}) 自动整定: {previous_enabled} → {enabled}")
            print(f"   🚦 切换标志已设置，开始切换流程...")
            
            if enabled:
                # ─────────────────────────────────────────────────────
                # 启用自动整定
                # ─────────────────────────────────────────────────────
                print(f"   ✅ 启用自动整定")
                
                # 2.1 检查OPC UA连接状态
                if not opcua_client.connected:
                    print(f"   ⚠️  OPC UA未连接，尝试重新连接...")
                    # 如果有保存的连接信息，尝试重连
                    # 这里简化处理，提示用户检查连接
                    print(f"   💡 提示：请确保OPC UA服务器已连接")
                
                # 2.2 下发当前PID参数到OPC UA（确保参数同步）
                pid_params = loop.get('pid_params', {})
                if pid_params and opcua_client.connected:
                    pb = pid_params.get('pb', 0)
                    ti = pid_params.get('ti', 0)
                    td = pid_params.get('td', 0)
                    
                    if pb > 0 or ti > 0 or td > 0:
                        print(f"   📡 下发当前PID参数到OPC UA: Pb={pb}, Ti={ti}, Td={td}")
                        try:
                            await _write_pid_to_opcua(loop_id, pb, ti, td, force_write=True)
                            print(f"   ✅ PID参数已下发")
                        except Exception as e:
                            print(f"   ⚠️  下发参数失败: {e}")
                            # 继续执行，不影响开关状态
                
                # 2.2 启动自动整定监控
                if auto_tuning_system:
                    is_collecting = opcua_config.get('is_collecting', False)
                    
                    if is_collecting:
                        # 正在采集，立即启动监控
                        try:
                            if auto_tuning_system.is_monitoring(loop_id):
                                print(f"   ℹ️  回路已在监控中，重新初始化")
                                await auto_tuning_system.stop_monitoring(loop_id)
                            
                            await auto_tuning_system.start_monitoring(loop_id)
                            print(f"   ✅ 已启动自动整定监控")
                        except Exception as e:
                            print(f"   ⚠️  启动监控失败: {e}")
                    else:
                        # 未采集，等待用户启动采集时再启动监控
                        print(f"   ℹ️  回路未采集，将在启动采集时自动启动监控")
                else:
                    print(f"   ⚠️  auto_tuning_system 不可用")
            else:
                # ─────────────────────────────────────────────────────
                # 禁用自动整定
                # ─────────────────────────────────────────────────────
                print(f"   ⏸️  禁用自动整定")
                
                # 2.3 停止自动整定监控
                if auto_tuning_system:
                    if auto_tuning_system.is_monitoring(loop_id):
                        try:
                            await auto_tuning_system.stop_monitoring(loop_id)
                            print(f"   ✅ 已停止自动整定监控")
                        except Exception as e:
                            print(f"   ⚠️  停止监控失败: {e}")
                    else:
                        print(f"   ℹ️  回路未在监控中")
                
                # 2.4 清理可能的整定状态（避免状态残留）
                # 注意：只清理 auto_tuning_system 相关的状态，不影响手动整定
                stability_status = loop.get('stability_status', {})
                if stability_status.get('is_retuning'):
                    # 如果当前正在整定，这里不应该到达（前面已经检查过）
                    # 但为了安全，再次检查
                    print(f"   ⚠️  检测到整定状态残留，但已被前面的检查拦截")
                else:
                    print(f"   ✅ 状态正常，无需清理")
            
            # 🔧 清除切换标志
            opcua_config["auto_tuning_switching"] = False
            loops_storage.update_loop(loop_id, {"opcua_config": opcua_config})
            print(f"   ✅ 切换完成，标志已清除")
            
            return JSONResponse({
                "success": True,
                "enabled": enabled,
                "message": f"自动整定已{status_text}"
            })
        else:
            return JSONResponse({
                "success": False,
                "message": "仅OPC UA数据源支持自动整定"
            })
            
    except HTTPException:
        raise
    except Exception as e:
        print(f"切换自动整定失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.delete("/api/loops/{loop_id}")
async def delete_loop(loop_id: str):
    """删除回路"""
    try:
        success = loops_storage.delete_loop(loop_id)
        if not success:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        return JSONResponse({
            "success": True,
            "message": "回路删除成功"
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"删除回路失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.post("/api/loops/{loop_id}/tuning-history")
async def save_tuning_history(loop_id: str, request: Dict[str, Any]):
    """保存整定历史记录"""
    try:
        # 获取回路
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        # 初始化历史记录列表
        if 'tuning_history' not in loop:
            loop['tuning_history'] = []
        
        # 添加新记录
        loop['tuning_history'].insert(0, request)  # 插入到开头，保持最新的在前
        
        # 限制历史记录数量（保留最近50条）
        if len(loop['tuning_history']) > 50:
            loop['tuning_history'] = loop['tuning_history'][:50]
        
        # 更新回路
        loops_storage.update_loop(loop_id, loop)
        
        return JSONResponse({
            "success": True,
            "message": "整定记录已保存",
            "total_records": len(loop['tuning_history'])
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"保存整定历史记录失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


@app.get("/api/loops/{loop_id}/tuning-history")
async def get_tuning_history(loop_id: str):
    """获取整定历史记录"""
    try:
        # 获取回路
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        # 获取历史记录
        records = loop.get('tuning_history', [])
        
        return JSONResponse({
            "success": True,
            "records": records,
            "total": len(records)
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"获取整定历史记录失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e),
            "records": []
        })


@app.delete("/api/loops/{loop_id}/tuning-history")
async def clear_tuning_history(loop_id: str):
    """清空整定历史记录"""
    try:
        # 获取回路
        loop = loops_storage.get_loop(loop_id)
        if not loop:
            raise HTTPException(status_code=404, detail="回路不存在")
        
        # 清空历史记录
        loop['tuning_history'] = []
        
        # 更新回路
        loops_storage.update_loop(loop_id, loop)
        
        return JSONResponse({
            "success": True,
            "message": "已清空所有整定历史记录"
        })
    except HTTPException:
        raise
    except Exception as e:
        print(f"清空整定历史记录失败: {str(e)}")
        traceback.print_exc()
        return JSONResponse({
            "success": False,
            "error": str(e)
        })


# ============================================================================
# OPC UA 数据源接口
# ============================================================================

try:
    from opcua_client import opcua_client
except ImportError:
    # 如果从项目根目录运行，使用 backend. 前缀
    from backend.opcua_client import opcua_client

class OPCUAConnectRequest(BaseModel):
    url: str
    username: Optional[str] = None
    password: Optional[str] = None

class OPCUACollectRequest(BaseModel):
    pv_node_id: str  # PV节点ID
    sv_node_id: str  # SV节点ID
    mv_node_id: str  # MV节点ID
    interval_ms: int = 1000
    loop_id: Optional[str] = None  # 关联的回路ID

@app.post("/api/opcua/connect")
async def connect_opcua(request: OPCUAConnectRequest):
    """连接 OPC UA 服务器"""
    try:
        result = await opcua_client.connect(
            request.url,
            request.username,
            request.password
        )
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"连接异常: {str(e)}"
        }

@app.post("/api/opcua/disconnect")
async def disconnect_opcua():
    """断开 OPC UA 连接"""
    try:
        result = await opcua_client.disconnect()
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"断开连接异常: {str(e)}"
        }

@app.get("/api/opcua/status")
async def get_opcua_status():
    """获取 OPC UA 连接状态"""
    return opcua_client.get_status()

@app.get("/api/opcua/browse")
async def browse_opcua_nodes(node_id: str = "i=85"):
    """浏览 OPC UA 节点"""
    try:
        result = await opcua_client.browse_nodes(node_id)
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"浏览节点异常: {str(e)}"
        }

@app.get("/api/opcua/read")
async def read_opcua_node(node_id: str):
    """读取单个节点的值"""
    try:
        result = await opcua_client.read_node_value(node_id)
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"读取节点异常: {str(e)}"
        }

@app.post("/api/opcua/start_collect")
async def start_opcua_collection(request: OPCUACollectRequest):
    """
    启动 OPC UA 数据采集（持续采集，无时间限制）
    支持三个节点：PV、SV、MV
    """
    try:
        result = await opcua_client.start_continuous_collection(
            request.pv_node_id,
            request.sv_node_id,
            request.mv_node_id,
            request.interval_ms,
            request.loop_id
        )
        
        # 如果有关联回路，更新回路状态
        if request.loop_id:
            loop = loops_storage.get_loop(request.loop_id)
            if loop and loop.get("opcua_config"):
                opcua_config = loop["opcua_config"]
                opcua_config["is_collecting"] = True
                loops_storage.update_loop(request.loop_id, {
                    "opcua_config": opcua_config
                })
                
                # 🔧 启动自动整定监控（仅在启用自动整定时）
                if auto_tuning_system and opcua_config.get('auto_tuning_enabled', False):
                    try:
                        await auto_tuning_system.start_monitoring(request.loop_id)
                        print(f"✅ 已启动回路 {request.loop_id} 的自动整定监控")
                    except Exception as e:
                        print(f"⚠️  启动自动整定监控失败: {e}")
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "message": f"启动采集异常: {str(e)}"
        }

@app.post("/api/opcua/stop_collect")
async def stop_opcua_collection(loop_id: Optional[str] = None, clear_data: bool = False):
    """
    停止 OPC UA 数据采集
    
    Args:
        loop_id: 回路ID
        clear_data: 是否清空已采集的数据
    """
    try:
        result = await opcua_client.stop_continuous_collection(loop_id)
        
        # 如果需要清空数据
        if clear_data and loop_id and loop_id in opcua_client.collection_data:
            old_count = len(opcua_client.collection_data[loop_id].get('pv', []))
            opcua_client.collection_data[loop_id] = {
                "timestamps": [],
                "pv": [],
                "sv": [],
                "mv": [],
                "start_time": datetime.now().isoformat()
            }
            print(f"🧹 已清空回路 {loop_id} 的采集数据（原有{old_count}个点）")
            result["data_cleared"] = True
            result["cleared_count"] = old_count
        
        # 如果有关联回路，更新回路状态
        if loop_id:
            loop = loops_storage.get_loop(loop_id)
            if loop and loop.get("opcua_config"):
                opcua_config = loop["opcua_config"]
                opcua_config["is_collecting"] = False
                loops_storage.update_loop(loop_id, {
                    "opcua_config": opcua_config
                })
                
                # 🔧 停止自动整定监控（如果正在监控）
                if auto_tuning_system and auto_tuning_system.is_monitoring(loop_id):
                    try:
                        await auto_tuning_system.stop_monitoring(loop_id)
                        print(f"✅ 已停止回路 {loop_id} 的自动整定监控")
                    except Exception as e:
                        print(f"⚠️  停止自动整定监控失败: {e}")
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "message": f"停止采集异常: {str(e)}"
        }

@app.get("/api/opcua/collect_status")
async def get_collection_status(loop_id: Optional[str] = None):
    """
    获取采集状态
    """
    try:
        result = await opcua_client.get_collection_status(loop_id)
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"获取状态异常: {str(e)}"
        }

@app.get("/api/opcua/collected_data")
async def get_collected_data(loop_id: Optional[str] = None, limit: int = 100):
    """
    获取已采集的数据
    """
    try:
        result = await opcua_client.get_collected_data(loop_id, limit)
        return result
    except Exception as e:
        return {
            "success": False,
            "message": f"获取数据异常: {str(e)}"
        }

@app.get("/api/opcua/collection_status")
async def get_collection_status():
    """
    获取所有采集任务的状态
    """
    try:
        return {
            "success": True,
            "all_status": opcua_client.collection_status
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"获取采集状态异常: {str(e)}"
        }


# ==================== 稳定性检测配置 API ====================

@app.get("/api/stability/config")
async def get_stability_config():
    """获取稳定性检测配置"""
    from stability_config import get_all_thresholds, MONITORING_CONFIG
    return {
        "success": True,
        "thresholds": get_all_thresholds(),
        "monitoring": MONITORING_CONFIG
    }

@app.post("/api/stability/config")
async def update_stability_config(config: Dict[str, Any]):
    """更新稳定性检测配置"""
    try:
        from stability_config import update_threshold
        
        updated = []
        failed = []
        
        for key, value in config.items():
            if update_threshold(key, float(value)):
                updated.append(key)
            else:
                failed.append(key)
        
        return {
            "success": True,
            "updated": updated,
            "failed": failed,
            "message": f"已更新 {len(updated)} 个配置项"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"更新配置失败: {str(e)}"
        }


# ==================== 对比分析模块 API ====================

@app.post("/api/comparison/parameters")
async def compare_parameters_api(request: Dict[str, Any]):
    """对比多组PID参数"""
    try:
        params_list = request.get('params_list', [])
        labels = request.get('labels')
        
        result = parameter_comparator.compare_parameters(params_list, labels)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/comparison/before_after")
async def compare_before_after_api(request: Dict[str, Any]):
    """对比整定前后的参数"""
    try:
        original = request.get('original_params', {})
        tuned = request.get('tuned_params', {})
        
        result = parameter_comparator.compare_before_after(original, tuned)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/comparison/methods")
async def compare_methods_api(request: Dict[str, Any]):
    """对比不同整定方法"""
    try:
        method_results = request.get('method_results', {})
        
        result = parameter_comparator.compare_methods(method_results)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/comparison/performance")
async def compare_performance_api(request: Dict[str, Any]):
    """对比性能指标"""
    try:
        performance_list = request.get('performance_list', [])
        labels = request.get('labels')
        
        result = performance_comparator.compare_performance(performance_list, labels)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/comparison/baseline")
async def compare_with_baseline_api(request: Dict[str, Any]):
    """与基准性能对比"""
    try:
        baseline = request.get('baseline', {})
        current = request.get('current', {})
        
        result = performance_comparator.compare_with_baseline(baseline, current)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/comparison/visualize")
async def visualize_comparison_api(request: Dict[str, Any]):
    """生成对比可视化图表"""
    try:
        params_list = request.get('params_list', [])
        labels = request.get('labels', [])
        chart_type = request.get('chart_type', 'radar')
        
        result = visual_comparator.generate_parameter_comparison_chart(
            params_list, labels, chart_type
        )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


# ==================== 实时监控模块 API ====================

@app.post("/api/monitor/create")
async def create_monitor_api(request: Dict[str, Any]):
    """创建监控实例"""
    try:
        loop_id = request.get('loop_id')
        loop_name = request.get('loop_name')
        sampling_interval = request.get('sampling_interval', 1.0)
        
        result = realtime_monitor.create_monitor(loop_id, loop_name, sampling_interval)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/monitor/start/{loop_id}")
async def start_monitor_api(loop_id: str):
    """启动监控"""
    try:
        result = realtime_monitor.start_monitor(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/monitor/stop/{loop_id}")
async def stop_monitor_api(loop_id: str):
    """停止监控"""
    try:
        result = realtime_monitor.stop_monitor(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/monitor/data")
async def add_monitor_data_api(request: Dict[str, Any]):
    """添加监控数据"""
    try:
        loop_id = request.get('loop_id')
        timestamp = request.get('timestamp')
        pv = request.get('pv')
        sv = request.get('sv')
        mv = request.get('mv')
        
        result = realtime_monitor.add_data_point(loop_id, timestamp, pv, sv, mv)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/monitor/batch_data")
async def add_batch_monitor_data_api(request: Dict[str, Any]):
    """批量添加监控数据"""
    try:
        loop_id = request.get('loop_id')
        time_data = request.get('time_data', [])
        pv_data = request.get('pv_data', [])
        sv_data = request.get('sv_data', [])
        mv_data = request.get('mv_data')
        
        result = realtime_monitor.add_batch_data(
            loop_id, time_data, pv_data, sv_data, mv_data
        )
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/monitor/realtime/{loop_id}")
async def get_realtime_data_api(loop_id: str, last_n: Optional[int] = None):
    """获取实时数据"""
    try:
        result = realtime_monitor.get_realtime_data(loop_id, last_n)
        # 转换numpy类型为JSON可序列化类型
        serializable_result = convert_to_serializable(result)
        return JSONResponse(content=serializable_result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/monitor/status/{loop_id}")
async def get_monitor_status_api(loop_id: str):
    """获取监控状态"""
    try:
        result = realtime_monitor.get_monitor_status(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/monitor/all")
async def get_all_monitors_api():
    """获取所有监控实例"""
    try:
        result = realtime_monitor.get_all_monitors()
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/monitor/disturb_data/{loop_id}")
async def get_disturb_data_status(loop_id: str):
    """获取 disturb_data 状态（用于验证清空）
    
    返回:
    - state: 当前状态 (STABLE, DISTURBANCE, STABILIZING, TUNING)
    - disturb_data_count: disturb_data 缓冲区中的数据点数
    - current_disturb_count: 当前扰动计数
    - last_sample_count: 上次采样计数
    - is_cleared: disturb_data 是否为空
    """
    try:
        if not auto_tuning_system:
            return JSONResponse(content={
                'success': False,
                'error': 'auto_tuning_system 未初始化'
            })
        
        if not auto_tuning_system.is_monitoring(loop_id):
            return JSONResponse(content={
                'success': False,
                'error': f'回路 {loop_id} 未在监控中'
            })
        
        loop_state = auto_tuning_system.loop_states.get(loop_id, {})
        state = loop_state.get('state')
        disturb_data = loop_state.get('disturb_data', [])
        disturbance_start_time = loop_state.get('disturbance_start_time')
        
        # state 可能是字符串或枚举
        state_str = state if isinstance(state, str) else (state.name if state else 'UNKNOWN')
        
        return JSONResponse(content={
            'success': True,
            'loop_id': loop_id,
            'state': state_str,
            'disturbance_start_time': str(disturbance_start_time) if disturbance_start_time else None,
            'disturb_data_count': len(disturb_data),
            'current_disturb_count': loop_state.get('current_disturb_count', 0),
            'last_sample_count': loop_state.get('last_sample_count', 0),
            'is_cleared': len(disturb_data) == 0,
            'message': '✅ disturb_data 已清空' if len(disturb_data) == 0 else f'⚠️ disturb_data 有 {len(disturb_data)} 个数据点'
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.delete("/api/monitor/{loop_id}")
async def delete_monitor_api(loop_id: str):
    """删除监控实例"""
    try:
        result = realtime_monitor.delete_monitor(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


# ==================== 报警管理 API ====================

@app.post("/api/alarm/configure")
async def configure_alarms_api(request: Dict[str, Any]):
    """配置报警规则"""
    try:
        loop_id = request.get('loop_id')
        config = request.get('config', {})
        
        result = alarm_manager.configure_alarms(loop_id, config)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/alarm/check")
async def check_alarms_api(request: Dict[str, Any]):
    """检查报警"""
    try:
        loop_id = request.get('loop_id')
        pv = request.get('pv')
        sv = request.get('sv')
        mv = request.get('mv')
        pv_history = request.get('pv_history', [])
        
        # 如果alarm_manager不存在或未初始化，返回空结果
        if not hasattr(alarm_manager, 'check_alarms'):
            return JSONResponse(content={
                'success': True,
                'alarms': [],
                'has_alarm': False
            })
        
        result = alarm_manager.check_alarms(loop_id, pv, sv, mv, pv_history)
        
        # 转换numpy类型为Python原生类型，确保JSON可序列化
        serializable_result = convert_to_serializable(result)
        return JSONResponse(content=serializable_result)
    except Exception as e:
        print(f"❌ 告警检查失败: {str(e)}")
        import traceback
        traceback.print_exc()
        # 返回空结果而不是500错误
        return JSONResponse(content={
            'success': True,
            'alarms': [],
            'has_alarm': False,
            'error': str(e)
        })


@app.get("/api/alarm/active/{loop_id}")
async def get_active_alarms_api(loop_id: str):
    """获取活动报警"""
    try:
        result = alarm_manager.get_active_alarms(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/alarm/history")
async def get_alarm_history_api(loop_id: Optional[str] = None, limit: int = 100):
    """获取报警历史"""
    try:
        result = alarm_manager.get_alarm_history(loop_id, limit)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/alarm/acknowledge")
async def acknowledge_alarm_api(request: Dict[str, Any]):
    """确认报警"""
    try:
        loop_id = request.get('loop_id')
        alarm_id = request.get('alarm_id')
        
        result = alarm_manager.acknowledge_alarm(loop_id, alarm_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.delete("/api/alarm/clear/{loop_id}")
async def clear_alarms_api(loop_id: str):
    """清除报警"""
    try:
        result = alarm_manager.clear_alarms(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


# ==================== 性能跟踪 API ====================

@app.post("/api/performance/create_tracker")
async def create_performance_tracker_api(request: Dict[str, Any]):
    """创建性能跟踪器"""
    try:
        loop_id = request.get('loop_id')
        loop_name = request.get('loop_name')
        target_metrics = request.get('target_metrics')
        
        result = performance_tracker.create_tracker(loop_id, loop_name, target_metrics)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.post("/api/performance/update")
async def update_performance_data_api(request: Dict[str, Any]):
    """更新性能数据"""
    try:
        loop_id = request.get('loop_id')
        timestamp = request.get('timestamp')
        pv = request.get('pv')
        sv = request.get('sv')
        mv = request.get('mv')
        
        result = performance_tracker.update_data(loop_id, timestamp, pv, sv, mv)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/performance/{loop_id}")
async def get_performance_api(loop_id: str):
    """获取性能指标"""
    try:
        result = performance_tracker.get_performance(loop_id)
        serializable_result = convert_to_serializable(result)
        return JSONResponse(content=serializable_result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/performance/history/{loop_id}")
async def get_performance_history_api(loop_id: str, limit: Optional[int] = 100):
    """获取性能历史"""
    try:
        result = performance_tracker.get_performance_history(loop_id, limit)
        serializable_result = convert_to_serializable(result)
        return JSONResponse(content=serializable_result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/performance/assessment/{loop_id}")
async def get_quality_assessment_api(loop_id: str):
    """获取控制质量评估"""
    try:
        result = performance_tracker.get_quality_assessment(loop_id)
        serializable_result = convert_to_serializable(result)
        return JSONResponse(content=serializable_result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


@app.get("/api/performance/compare_target/{loop_id}")
async def compare_with_target_api(loop_id: str):
    """与目标性能对比"""
    try:
        result = performance_tracker.compare_with_target(loop_id)
        return JSONResponse(content=result)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': str(e)}
        )


# ============================================================================
# 非稳态检测后台任务
# ============================================================================

import asyncio
from datetime import datetime

# 自动重整定配置常量
STEADY_STATE_THRESHOLD = 1.0  # 稳态误差阈值
STEADY_PORTION_RATIO = 0.8    # 用于判断稳态的数据比例
DEFAULT_MV_VALUE = 50.0       # 默认MV值
DEFAULT_MODEL_PARAMS = [1.0, 10.0, 1.0]  # 默认FOPDT参数 [K, T, L]


def _prepare_data(pv_data: list, sv_data: list, mv_data: list, timestamps: list = None):
    """准备数据"""
    pv = np.array(pv_data)
    sv = np.array(sv_data) if sv_data else np.full_like(pv, pv[0])
    mv = np.array(mv_data) if mv_data else np.full_like(pv, 50.0)
    setpoint = sv[0] if len(sv) > 0 else pv[0]
    
    # 生成时间数组
    if timestamps and len(timestamps) == len(pv_data):
        # 使用真实时间戳，转换为相对时间（秒）
        from datetime import datetime as dt
        try:
            t0 = dt.fromisoformat(timestamps[0])
            t = np.array([(dt.fromisoformat(ts) - t0).total_seconds() for ts in timestamps])
            print(f"  ✅ 使用真实时间戳: {len(timestamps)}个点, 时长{t[-1]:.1f}秒")
        except Exception as e:
            print(f"  ⚠️  时间戳解析失败: {e}, 使用默认采样间隔")
            t = np.arange(len(pv_data)) * 2.0  # 假设2秒采样间隔
    else:
        # 没有时间戳，使用默认采样间隔（2秒）
        t = np.arange(len(pv_data)) * 2.0
        print(f"  ⚠️  未提供时间戳，使用默认采样间隔2秒")
    
    return t, pv, sv, mv, setpoint


def _print_data_statistics(pv: np.ndarray, setpoint: float):
    """打印数据统计信息"""
    print(f"  数据: {len(pv)}点, PV={pv.min():.1f}~{pv.max():.1f}, SV={setpoint:.1f}, 误差={abs(pv[-1] - setpoint):.2f}")


def _identify_and_tune(t: np.ndarray, pv: np.ndarray, mv: np.ndarray, setpoint: float):
    """系统辨识和PID整定
    
    Returns:
        tuple: (model_params, model_type, new_pb, new_ti, new_td, step_start_index)
    """
    print(f"\n🔍 系统辨识开始...")
    print(f"  数据范围: PV=[{pv.min():.2f}, {pv.max():.2f}], MV=[{mv.min():.2f}, {mv.max():.2f}]")
    print(f"  设定值: SV={setpoint:.2f}")
    
    # 系统辨识
    model_identifier = ModelIdentifier()
    model_params = model_identifier.identify_fopdt(t, pv, mv)
    model_type = 'fopdt'
    step_start_index = 0  # 🔧 默认从第一个点开始
    
    if model_params is None:
        print("⚠️  辨识失败，使用默认参数")
        model_params = DEFAULT_MODEL_PARAMS
    else:
        K, T, L = model_params
        print(f"✅ 模型辨识成功: K={K:.3f}, T={T:.1f}s, L={L:.1f}s")
        
        # 🔧 尝试检测阶跃起点（整定点）
        try:
            # 检测MV的阶跃变化点
            mv_diff = np.abs(np.diff(mv))
            if len(mv_diff) > 0:
                # 找到最大变化点
                step_start_index = np.argmax(mv_diff)
                print(f"  🔍 检测到阶跃起点: 索引={step_start_index}, PV={pv[step_start_index]:.2f}")
        except Exception as e:
            print(f"  ⚠️  阶跃起点检测失败: {e}，使用第一个点")
            step_start_index = 0
        
        # 检查模型参数合理性
        if abs(K) < 0.01:
            print(f"⚠️  增益K过小 ({K:.3f})，可能导致仿真偏差")
        if T < 1:
            print(f"⚠️  时间常数T过小 ({T:.1f}s)，可能导致仿真不稳定")
    
    # PID整定
    K, T, L = model_params
    print(f"\n🎯 PID整定开始...")
    pid_params = PIDTuner.lambda_tuning(K, T, L, mode=Mode.STANDARD)
    
    if pid_params is None:
        print("⚠️  整定失败，使用默认参数")
        return DEFAULT_MODEL_PARAMS, 'fopdt', DEFAULT_PID_PB, DEFAULT_PID_TI, DEFAULT_PID_TD, 0
    
    new_kp, new_ti, new_td = pid_params
    new_pb = 100.0 / new_kp if new_kp != 0 else 100.0
    print(f"✅ PID整定成功:")
    print(f"  Kp={new_kp:.3f} (Pb={new_pb:.1f}%)")
    print(f"  Ti={new_ti:.1f}s")
    print(f"  Td={new_td:.1f}s")
    
    return model_params, model_type, new_pb, new_ti, new_td, step_start_index


def _simulate_and_evaluate(model_params, model_type: str, new_pb: float, new_ti: float, 
                          new_td: float, setpoint: float, t: np.ndarray, pv: np.ndarray, step_start_index: int = 0):
    """仿真和评估
    
    Args:
        step_start_index: 阶跃起点索引（整定开始点，用于参考）
    
    Note:
        仿真应该从"新参数生效点"开始，即原始数据的最后一个点
        这样才能对比新参数的效果
    """
    print(f"\n📊 仿真开始...")
    K, T, L = model_params
    print(f"  模型参数: K={K:.3f}, T={T:.1f}s, L={L:.1f}s")
    print(f"  PID参数: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
    print(f"  设定值: {setpoint:.2f}")
    
    # 🔧 使用原始数据的最后一个点作为初始值
    # 这代表"新参数开始生效"的时刻
    initial_pv = pv[-1] if len(pv) > 0 else setpoint
    print(f"  整定开始点索引: {step_start_index}, PV={pv[step_start_index]:.2f}" if 0 <= step_start_index < len(pv) else "")
    print(f"  新参数生效点: 最后一个点, PV={initial_pv:.2f}")
    print(f"  📌 仿真从新参数生效点开始，initial_pv={initial_pv:.2f}")
    
    # 使用FOPDT模型（已在顶部导入）
    system_model = ModelIdentifier.fopdt_model
    
    sim_pv, sim_mv = simulate_system_with_pid(
        t=t,
        system_model=system_model,
        model_params=(K, T, L),
        pid_params={'pb': new_pb, 'ti': new_ti, 'td': new_td},
        setpoint=setpoint,
        initial_pv=initial_pv  # 🔧 使用最后一个点的PV值（新参数生效点）
    )
    
    # 检查仿真结果
    print(f"  仿真PV范围: [{sim_pv.min():.2f}, {sim_pv.max():.2f}]")
    print(f"  最终PV: {sim_pv[-1]:.2f}")
    print(f"  最终误差: {abs(sim_pv[-1] - setpoint):.2f}")
    
    # 检查仿真是否合理
    final_error = abs(sim_pv[-1] - setpoint)
    if final_error > 5.0:
        print(f"⚠️  仿真最终误差过大 ({final_error:.2f})，可能模型辨识不准确")
    
    # 评估
    evaluator = PIDEvaluator()
    sv_sim = np.full_like(sim_pv, setpoint)
    metrics = evaluator.evaluate(pv=sim_pv, sv=sv_sim, cv=sim_mv)
    
    print(f"\n📊 评估结果:")
    print(f"  评分: {metrics.overall_score:.0f} ({metrics.grade})")
    print(f"  稳态误差: {metrics.steady_state_error:.3f}")
    print(f"  振荡次数: {metrics.oscillation_count}")
    
    return {'pv': sim_pv, 'sv': sv_sim, 'mv': sim_mv}, metrics


def _determine_stability_status(sim_result: dict) -> dict:
    """根据仿真结果判断稳定性状态"""
    sim_pv = sim_result['pv']
    sim_sv = sim_result['sv']
    
    # 计算最后20%数据的误差
    n = len(sim_pv)
    start_idx = int(n * 0.8)
    final_errors = np.abs(sim_pv[start_idx:] - sim_sv[start_idx:])
    final_error = np.mean(final_errors)
    
    # 无论仿真结果如何，都保持“正在整定”状态
    # 等待实际数据检测到稳态后才恢复
    return {
        'is_unsteady': False,
        'is_retuning': True,
        'retuning_start_time': datetime.now().isoformat(),
        'last_check': datetime.now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════
# 🔧 OPC UA 写入锁（避免并发写入冲突）
# ═══════════════════════════════════════════════════════════
_opcua_write_locks = {}  # {loop_id: asyncio.Lock()}

async def _write_state_to_opcua(loop_id: str, state: str):
    """将状态写入OPC UA状态节点
    
    Args:
        loop_id: 回路ID
        state: 状态值（STABLE, DISTURBANCE, TUNING, STABILIZING）
    """
    try:
        loop = loops_storage.get_loop(loop_id)
        if not loop or loop.get('data_source') != 'opcua':
            return
        
        opcua_config = loop.get('opcua_config', {})
        state_node_id = opcua_config.get('state_node_id')
        
        # 如果没有配置状态节点，跳过
        if not state_node_id:
            return
        
        # 检查OPC UA连接
        if not opcua_client.connected:
            return
        
        # 写入状态节点
        print(f"   📡 写入OPC UA状态节点: {state_node_id} = {state}")
        result = await opcua_client.write_node_value(state_node_id, state)
        if result and result.get('success'):
            print(f"   ✅ OPC UA状态节点已更新: {state}")
        else:
            error_msg = result.get('error', '未知错误') if result else '无返回结果'
            print(f"   ❌ OPC UA状态节点更新失败: {error_msg}")
        
    except Exception as e:
        # 状态节点写入失败不应影响主流程
        print(f"   ⚠️  写入OPC UA状态节点失败: {e}")


async def _write_pid_to_opcua(loop_id: str, new_pb: float, new_ti: float, new_td: float, force_write: bool = False):
    """将新PID参数写入OPC UA服务器
    
    Args:
        loop_id: 回路 ID
        new_pb: 新的比例带
        new_ti: 新的积分时间
        new_td: 新的微分时间
        force_write: 是否强制下发（忽略参数差异检查）
    
    Note:
        使用锁机制避免并发写入冲突
    """
    # 🔧 获取或创建该回路的写入锁
    if loop_id not in _opcua_write_locks:
        _opcua_write_locks[loop_id] = asyncio.Lock()
    
    # 🔧 使用锁保护写入操作
    async with _opcua_write_locks[loop_id]:
        try:
            loop = loops_storage.get_loop(loop_id)
            if not loop or loop.get('data_source') != 'opcua':
                return
            
            opcua_config = loop.get('opcua_config', {})
            
            # 🔧 检查OPC UA连接状态（移除is_collecting检查，允许在未采集时也能下发参数）
            if not opcua_client.connected:
                print(f"\n⚠️  OPC UA未连接，无法下发参数")
                print(f"   💡 提示：请检查OPC UA服务器连接状态")
                print(f"   💡 如果服务器正常运行，后端重启后需要重新连接")
                return
            
            # 获取配置的PID参数节点ID
            pid_pb_node = opcua_config.get('pid_pb_node_id')
            pid_ti_node = opcua_config.get('pid_ti_node_id')
            pid_td_node = opcua_config.get('pid_td_node_id')
            
            # 检查是否配置了PID参数节点
            if not all([pid_pb_node, pid_ti_node, pid_td_node]):
                print(f"\nℹ️  回路 {loop_id} 未配置PID参数节点，跳过参数下发")
                print(f"💡 提示：在回路配置中添加PID参数节点以启用自动下发功能")
                return
            
            # 获取当前PID参数（用于对比）
            current_pid = loop.get('pid_params', {})
            current_pb = current_pid.get('pb', 0)
            current_ti = current_pid.get('ti', 0)
            current_td = current_pid.get('td', 0)
            
            # 确保所有值都是浮点数（避免类型不匹配错误）
            new_pb = float(new_pb)
            new_ti = float(new_ti)
            new_td = float(new_td)
            
            print(f"\n📡 准备下发PID参数到OPC UA...")
            print(f"  当前参数: Pb={current_pb:.1f}%, Ti={current_ti:.1f}s, Td={current_td:.1f}s")
            print(f"  新参数: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
            if force_write:
                print(f"  🔴 强制下发模式（手动整定）")
            
            # 🔧 检查参数是否有变化（仅在非强制模式下）
            if not force_write:
                pb_diff = abs(new_pb - current_pb)
                ti_diff = abs(new_ti - current_ti)
                td_diff = abs(new_td - current_td)
                
                # 阈值设置：Pb差异<0.1%，Ti/Td差异<0.1秒时跳过下发
                # 这样可以避免微小的参数变化导致频繁下发
                if pb_diff < 0.1 and ti_diff < 0.1 and td_diff < 0.1:
                    print(f"\n⚠️  新参数与当前参数几乎相同，跳过下发")
                    print(f"  差异: ΔPb={pb_diff:.3f}%, ΔTi={ti_diff:.3f}s, ΔTd={td_diff:.3f}s")
                    print(f"  💡 可能原因：模型辨识不准确或数据质量不佳")
                    print(f"  💡 建议：采集更长时间的数据，或手动制造扰动后再整定")
                    print(f"  💡 如需强制下发，请使用手动整定功能")
                    return
                
                print(f"  参数差异: ΔPb={pb_diff:.2f}%, ΔTi={ti_diff:.2f}s, ΔTd={td_diff:.2f}s")
            else:
                print(f"  🔴 强制下发模式：忽略参数差异检查")
            
            print(f"  节点信息:")
            print(f"    Pb: {pid_pb_node}")
            print(f"    Ti: {pid_ti_node}")
            print(f"    Td: {pid_td_node}")
            
            # 使用已导入的opcua_client（顶部已导入）
            await opcua_client.write_node_value(pid_pb_node, new_pb)
            await opcua_client.write_node_value(pid_ti_node, new_ti)
            await opcua_client.write_node_value(pid_td_node, new_td)
            
            print(f"\n✅ PID参数已成功下发到OPC UA服务器")
            
        except Exception as e:
            print(f"\n❌ 写入OPC UA失败: {str(e)}")
            import traceback
            traceback.print_exc()


def _update_loop_with_results(loop_id: str, new_pb: float, new_ti: float, new_td: float,
                             metrics, stability_status: dict):
    """更新回路参数和状态"""
    loops_storage.update_loop(loop_id, {
        'pid_params': {
            'pb': new_pb,
            'ti': new_ti,
            'td': new_td
        },
        'performance': {
            'score': float(metrics.overall_score),
            'grade': metrics.grade,
            'steady_error': float(metrics.steady_state_error),
            'iae': float(metrics.iae),
            'oscillation_count': int(metrics.oscillation_count)
        },
        'stability_status': stability_status,
        'updated_at': datetime.now().isoformat()
    })


async def trigger_auto_retuning(loop_id: str, loop_name: str, pv_data, sv_data, mv_data, timestamps=None, force_write: bool = False):
    """触发自动重整定
    
    Args:
        loop_id: 回路 ID
        loop_name: 回路名称
        pv_data: PV数据
        sv_data: SV数据
        mv_data: MV数据
        timestamps: 时间戳数据
        force_write: 是否强制下发参数（手动整定时为True）
    
    Returns:
        dict: {"success": bool, "message": str, "data": dict}
    """
    try:
        print(f"\n{'='*60}")
        print(f"{'手动' if force_write else '自动'}重整定: {loop_name}")
        print(f"{'='*60}")
        
        # 🔧 检查扰动数据点数（手动整定也需要足够的扰动数据）
        if force_write and auto_tuning_system and auto_tuning_system.is_monitoring(loop_id):
            # 🔧 关键修复：无论当前状态如何，都要检查扰动数据
            # 如果回路在监控中，检查扰动数据点数
            loop_state = auto_tuning_system.loop_states.get(loop_id, {})
            current_state = loop_state.get('state')
            
            # 🔧 关键改进：如果当前不在DISTURBANCE状态，先检测是否有扰动
            if not current_state or current_state.name != 'DISTURBANCE':
                print(f"🔍 手动整定: 当前状态为 {current_state.name if current_state else 'UNKNOWN'}，检测扰动...")
                
                # 检测扰动（使用 auto_tuning_system 的方法）
                is_unsteady = auto_tuning_system._detect_unsteady(pv_data, sv_data)
                
                if not is_unsteady:
                    error_msg = f"⚠️  当前系统处于稳态，未检测到扰动"
                    print(error_msg)
                    print(f"   💡 手动整定需要在扰动发生后进行")
                    print(f"   💡 请等待系统出现扰动或人为施加扰动")
                    
                    # 恢复状态
                    loops_storage.update_loop(loop_id, {
                        'stability_status': {
                            'is_unsteady': False,
                            'is_retuning': False,
                            'last_check': datetime.now().isoformat()
                        }
                    })
                    return {
                        "success": False,
                        "message": "当前系统处于稳态，未检测到扰动",
                        "reason": "no_disturbance",
                        "suggestion": "请等待系统出现扰动或人为施加扰动"
                    }
                else:
                    logger.info(f"回路 {loop_id} 检测到扰动，重新积累数据")
                    await auto_tuning_system.opcua_client.clear_collected_data(loop_id)
                    
                    loop_state['state'] = auto_tuning_system.LoopState.DISTURBANCE
                    loop_state['disturbance_start_time'] = datetime.now()
                    loop_state['disturbance_start_data_count'] = 0
                    loop_state['disturbance_triggered'] = False
                    
                    loops_storage.update_loop(loop_id, {
                        'stability_status': {
                            'is_unsteady': True,
                            'is_retuning': False,
                            'last_check': datetime.now().isoformat()
                        }
                    })
                    return {
                        "success": False,
                        "message": "已检测到扰动，但数据不足",
                        "reason": "insufficient_data",
                        "required": 100,
                        "current": 0,
                        "wait_seconds": 200,
                        "suggestion": "请等待采集足够的扰动数据后再次点击整定"
                    }
            
            # 如果当前在DISTURBANCE状态，检查新数据点数
            if current_state and current_state.name == 'DISTURBANCE':
                initial_data_count = loop_state.get('disturbance_start_data_count', 0)
                current_data_count = len(pv_data)
                new_data_points = current_data_count - initial_data_count
                MIN_NEW_DATA_POINTS = 100
                
                if new_data_points < MIN_NEW_DATA_POINTS:
                    error_msg = f"⚠️  扰动数据点不足，无法进行整定"
                    print(error_msg)
                    print(f"   📊 当前已采集 {new_data_points} 个新扰动数据点")
                    print(f"   🎯 至少需要 {MIN_NEW_DATA_POINTS} 个新扰动数据点")
                    print(f"   ⏳ 还需等待约 {(MIN_NEW_DATA_POINTS - new_data_points) * 2} 秒")
                    print(f"   💡 请等待采集足够的扰动数据后再进行手动整定")
                    
                    # 恢复状态
                    loops_storage.update_loop(loop_id, {
                        'stability_status': {
                            'is_unsteady': True,
                            'is_retuning': False,
                            'last_check': datetime.now().isoformat()
                        }
                    })
                    return
                else:
                    print(f"✅ 扰动数据点检查通过: {new_data_points}/{MIN_NEW_DATA_POINTS} 个新数据点")
                    
                    # 🔧 截取最近100个数据点，确保使用纯净的扰动数据
                    if len(pv_data) > 100:
                        print(f"   🔧 数据截取: 使用最近 100 个数据点（约200秒，共 {len(pv_data)} 个）")
                        print(f"   💡 100%使用进入扰动后采集的新数据，确保反映新过程特性")
                        pv_data = pv_data[-100:]
                        sv_data = sv_data[-100:]
                        mv_data = mv_data[-100:]
                        if timestamps:
                            timestamps = timestamps[-100:]
        
        # 更新状态为重整定中（添加retuning_start_time）
        loops_storage.update_loop(loop_id, {
            'stability_status': {
                'is_unsteady': True,
                'is_retuning': True,
                'retuning_start_time': datetime.now().isoformat(),
                'last_check': datetime.now().isoformat()
            }
        })
        
        # 1. 准备数据
        t, pv, sv, mv, setpoint = _prepare_data(pv_data, sv_data, mv_data, timestamps)
        _print_data_statistics(pv, setpoint)
        
        # 2. 系统辨识 + PID整定（使用SystemIdentifier，与参数整定界面保持一致）
        print(f"\n🔍 系统辨识开始...")
        print(f"  数据范围: PV=[{pv.min():.2f}, {pv.max():.2f}], MV=[{mv.min():.2f}, {mv.max():.2f}]")
        print(f"  设定值: SV={setpoint:.2f}")
        
        # 获取当前PID参数（用于闭环辨识增强）
        loop = loops_storage.get_loop(loop_id)
        current_pid_params = None
        if loop:
            current_pid_params = {
                'pb': loop.get('pb', 100.0),
                'ti': loop.get('ti', 20.0),
                'td': loop.get('td', 0.0)
            }
            print(f"  当前PID: Pb={current_pid_params['pb']:.1f}%, Ti={current_pid_params['ti']:.1f}s, Td={current_pid_params['td']:.1f}s")
        
        # 使用SystemIdentifier进行整定（启用自动检测）
        identifier = SystemIdentifier()
        tuning_result = identifier.auto_tune_from_json(
            t, pv, setpoint,
            tuning_method=TuningMethod.LAMBDA,
            mode=None,  # 自动检测控制模式
            u_data=mv,
            auto_detect=True,  # 启用自动检测
            sv_array=sv,
            enable_setpoint_segmentation=False,
            current_pid_params=current_pid_params
        )
        
        if not tuning_result or 'pb' not in tuning_result:
            print(f"   ❌ 系统辨识失败，使用默认参数")
            model_params = DEFAULT_MODEL_PARAMS
            model_type = 'fopdt'
            new_pb = DEFAULT_PID_PB
            new_ti = DEFAULT_PID_TI
            new_td = DEFAULT_PID_TD
            step_start_index = 0
        else:
            # 提取整定结果
            model_params = tuning_result.get('model_params', DEFAULT_MODEL_PARAMS)
            model_type = tuning_result.get('model_type', 'fopdt')
            new_pb = float(tuning_result['pb'])
            new_ti = float(tuning_result['ti'])
            new_td = float(tuning_result['td'])
            step_start_index = tuning_result.get('step_start_index', 0)
            
            print(f"✅ 整定成功:")
            print(f"  模型类型: {model_type}")
            print(f"  模型参数: {model_params}")
            print(f"  PID参数: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
        
        # 3. 仿真 + 评估
        sim_result, metrics = _simulate_and_evaluate(
            model_params, model_type, new_pb, new_ti, new_td, setpoint, t, pv, step_start_index
        )
        
        # 4. 更新回路
        stability_status = _determine_stability_status(sim_result)
        _update_loop_with_results(loop_id, new_pb, new_ti, new_td, metrics, stability_status)
        
        # 5. 写入OPC UA（传递force_write参数）
        await _write_pid_to_opcua(loop_id, new_pb, new_ti, new_td, force_write=force_write)
        
        print(f"{'='*60}")
        print(f"✅ 整定完成: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ 整定失败: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # 恢复状态
        loops_storage.update_loop(loop_id, {
            'stability_status': {
                'is_unsteady': True,
                'is_retuning': False,
                'last_check': datetime.now().isoformat()
            }
        })


# 非稳态检测任务
async def stability_monitoring_task():
    """后台任务：定期检测OPC UA回路的稳定性"""
    print("✅ 稳定性监控任务已启动")
    while True:
        try:
            await asyncio.sleep(1)  # 每1秒检查一次（优化：实时响应OPC UA状态变化）
            
            # 获取所有OPC UA回路
            all_loops = loops_storage.get_all_loops()
            opcua_loops = [loop for loop in all_loops if loop.get('data_source') == 'opcua']
            
            # 简化日志：只在有回路时打印
            # if opcua_loops:
            #     print(f"🔍 检查 {len(opcua_loops)} 个回路...")
            
            for loop in opcua_loops:
                loop_id = loop['id']
                
                # 🔧 检查是否由AutoTuningSystem监控
                # 如果AutoTuningSystem正在监控，跳过（避免冲突）
                opcua_config = loop.get('opcua_config', {})
                auto_tuning_enabled = opcua_config.get('auto_tuning_enabled', False)
                if auto_tuning_enabled and auto_tuning_system and auto_tuning_system.is_monitoring(loop_id):
                    # 由AutoTuningSystem管理，跳过
                    continue
                
                # 🔧 修复：检查是否需要监控
                # 1. 如果正在整定中（is_retuning=True），必须监控以恢复状态
                # 2. 如果正在采集（is_collecting=True），需要监控稳定性
                stability_status = loop.get('stability_status', {})
                is_retuning = stability_status.get('is_retuning', False)
                is_collecting = opcua_config.get('is_collecting', False)
                
                # 如果既不在整定中，也不在采集中，跳过
                if not is_retuning and not is_collecting:
                    continue
                
                # 获取最近的数据
                try:
                    # 🔧 优先读取OPC UA Server的State节点（实时状态）
                    opcua_config = loop.get('opcua_config', {})
                    state_node_id = opcua_config.get('state_node_id')  # 例如: "ns=2;i=1010"
                    opcua_state = None
                    
                    if state_node_id and opcua_client.connected:
                        try:
                            state_result = await opcua_client.read_node_value(state_node_id)
                            if state_result.get('success'):
                                opcua_state = state_result.get('value')
                                print(f"  📡 [{loop['name']}] OPC UA State节点: {opcua_state}")
                        except Exception as e:
                            print(f"  ⚠️ [{loop['name']}] State节点读取失败: {e}")
                            pass  # State节点读取失败，回退到数据检测
                    
                    collected_data = await opcua_client.get_collected_data(loop_id, limit=60)
                    
                    # 检查数据是否足够
                    if not collected_data or not collected_data.get('success'):
                        # 🔧 修复：即使无数据，也要检查整定状态
                        # 如果有 OPC UA State，可以根据 State 判断是否结束整定
                        if opcua_state and is_retuning:
                            # 有 State 节点，可以判断
                            is_unsteady = opcua_state == 'DISTURBANCE'
                            
                            # 检查是否应该结束整定状态
                            current_status = loop.get('stability_status', {})
                            retuning_start_time = current_status.get('retuning_start_time')
                            
                            if retuning_start_time and not is_unsteady:
                                # 系统已稳定（OPC UA State 不是 DISTURBANCE）
                                # 检查是否超过最小观察时间
                                from datetime import datetime as dt
                                start_time = dt.fromisoformat(retuning_start_time)
                                elapsed_seconds = (datetime.now() - start_time).total_seconds()
                                min_observation_time = 10  # 最小观察时间：10秒
                                
                                if elapsed_seconds >= min_observation_time:
                                    # 超过观察期且已稳定，结束整定
                                    print(f"  ✅ [{loop['name']}] 无采集数据，但OPC UA State={opcua_state}（稳定），结束整定状态 (用时: {elapsed_seconds:.0f}s)")
                                    loops_storage.update_loop(loop_id, {
                                        'stability_status': {
                                            'is_unsteady': False,
                                            'is_retuning': False,
                                            'last_check': datetime.now().isoformat(),
                                            'data_points': 0
                                        }
                                    })
                                    continue
                                else:
                                    # 还在观察期内
                                    print(f"  ⏳ [{loop['name']}] 无采集数据，OPC UA State={opcua_state}（稳定），但仍在观察期({elapsed_seconds:.0f}s/{min_observation_time}s)")
                            elif retuning_start_time and is_unsteady:
                                # 系统仍不稳定
                                print(f"  ⏳ [{loop['name']}] 无采集数据，OPC UA State={opcua_state}（不稳定），继续'正在整定'")
                        
                        # 无法判断，保持当前状态
                        current_status = loop.get('stability_status', {})
                        loops_storage.update_loop(loop_id, {
                            'stability_status': {
                                'is_unsteady': False,
                                'last_check': datetime.now().isoformat(),
                                'is_retuning': current_status.get('is_retuning', False),
                                'data_points': 0
                            }
                        })
                        continue
                    
                    # 从嵌套的data字段中获取数据
                    data = collected_data.get('data', {})
                    pv_data = data.get('pv', [])
                    sv_data = data.get('sv', [])
                    data_count = len(pv_data)
                    
                    # 如果数据不足20个点，暂时认为是稳态（数据不足以判断）
                    if data_count < 20:
                        current_status = loop.get('stability_status', {})
                        loops_storage.update_loop(loop_id, {
                            'stability_status': {
                                'is_unsteady': False,
                                'last_check': datetime.now().isoformat(),
                                'is_retuning': current_status.get('is_retuning', False),
                                'data_points': data_count
                            }
                        })
                        continue
                    
                    # 获取当前状态（重新从数据库读取，确保获取最新状态）
                    loop = loops_storage.get_loop(loop_id)  # 🔧 重新读取，获取最新状态
                    current_status = loop.get('stability_status', {})
                    previous_is_unsteady = current_status.get('is_unsteady', False)
                    previous_is_retuning = current_status.get('is_retuning', False)
                    
                    # 检查整定时间
                    retuning_start_time = current_status.get('retuning_start_time')
                    elapsed_seconds = 0  # 🔧 初始化
                    
                    if previous_is_retuning:
                        if retuning_start_time:
                            # 计算整定已用时间
                            from datetime import datetime as dt
                            start_time = dt.fromisoformat(retuning_start_time)
                            elapsed_seconds = (datetime.now() - start_time).total_seconds()
                        else:
                            # 🔧 如果正在整定但没有开始时间，说明数据不一致，强制结束整定状态
                            print(f"  ⚠️  [{loop['name']}] 检测到整定状态异常（无开始时间），强制结束")
                            previous_is_retuning = False
                    
                    # 🔧 稳定性检测逻辑（根据实际数据判断）
                    # 优先级：OPC UA State > 数据检测
                    if opcua_state:
                        # 使用OPC UA Server的实时状态
                        is_unsteady = opcua_state == 'DISTURBANCE'
                        # print(f"  ✅ [{loop['name']}] OPC UA State: {opcua_state} -> is_unsteady={is_unsteady}")
                    else:
                        # 回退到数据检测
                        is_unsteady = detect_unsteady_state(pv_data, sv_data)
                        # print(f"  🔍 [{loop['name']}] 数据检测: is_unsteady={is_unsteady}")
                    
                    # ═══════════════════════════════════════════════════════════
                    # 🔧 状态机：稳态 ↔ 非稳态 ↔ 正在整定
                    # ═══════════════════════════════════════════════════════════
                    # 
                    # 状态定义：
                    # 1. 🟢 稳态 (STABLE):      is_retuning=False, is_unsteady=False
                    # 2. 🔴 非稳态 (DISTURBANCE): is_retuning=False, is_unsteady=True
                    # 3. 🔵 正在整定 (TUNING):    is_retuning=True,  is_unsteady=False (强制)
                    #
                    # 转换规则：
                    # - 稳态 → 非稳态：检测到扰动 (is_unsteady=True)
                    # - 非稳态 → 正在整定：触发整定（手动/自动，由其他接口设置）
                    # - 正在整定 → 稳态：系统稳定 且 超过观察期 (10秒)
                    # - 正在整定中的波动：不切换到非稳态，继续整定
                    # ═══════════════════════════════════════════════════════════
                    
                    MIN_OBSERVATION_TIME = 10  # 最小观察时间：10秒
                    MAX_TUNING_TIME = 120  # 🔧 最大整定时间：120秒（2分钟）
                    
                    new_is_retuning = False
                    new_is_unsteady = False
                    state_changed = False
                    
                    if previous_is_retuning:
                        # ─────────────────────────────────────────────────────────
                        # 当前状态：🔵 正在整定
                        # ─────────────────────────────────────────────────────────
                        
                        # 🔧 检查是否超过最大整定时间
                        if elapsed_seconds >= MAX_TUNING_TIME:
                            # 超过最大整定时间，强制结束整定
                            new_is_retuning = False
                            new_is_unsteady = is_unsteady  # 根据实际状态设置
                            state_changed = True
                            if is_unsteady:
                                print(f"  ⚠️  [{loop['name']}] 整定超时（{elapsed_seconds:.0f}s），系统仍不稳定 → 非稳态")
                                # 🔧 写入OPC UA状态节点
                                await _write_state_to_opcua(loop_id, "DISTURBANCE")
                            else:
                                print(f"  ✅ [{loop['name']}] 整定超时（{elapsed_seconds:.0f}s），系统已稳定 → 稳态")
                                # 🔧 写入OPC UA状态节点
                                await _write_state_to_opcua(loop_id, "STABLE")
                        elif is_unsteady:
                            # 整定中检测到波动 → 继续整定（不切换到非稳态）
                            new_is_retuning = True
                            new_is_unsteady = False  # 强制不显示"非稳态"
                            if elapsed_seconds % 10 == 0 or elapsed_seconds < 5:  # 每10秒打印一次
                                print(f"  ⏳ [{loop['name']}] 整定中检测到波动（正常），继续整定 (已用时: {elapsed_seconds:.0f}s/{MAX_TUNING_TIME}s)")
                        else:
                            # 整定中系统稳定 → 检查是否可以结束整定
                            if elapsed_seconds < MIN_OBSERVATION_TIME:
                                # 还在观察期 → 继续整定
                                new_is_retuning = True
                                new_is_unsteady = False
                                if elapsed_seconds % 5 == 0:  # 每5秒打印一次
                                    print(f"  ⏳ [{loop['name']}] 系统稳定，观察期({elapsed_seconds:.0f}s/{MIN_OBSERVATION_TIME}s)")
                            else:
                                # 超过观察期且稳定 → 结束整定，进入稳态
                                new_is_retuning = False
                                new_is_unsteady = False
                                state_changed = True
                                print(f"  ✅ [{loop['name']}] 整定完成 → 稳态 (用时: {elapsed_seconds:.0f}s)")
                                # 🔧 写入OPC UA状态节点
                                await _write_state_to_opcua(loop_id, "STABLE")
                    else:
                        # ─────────────────────────────────────────────────────────
                        # 当前状态：🟢 稳态 或 🔴 非稳态
                        # ─────────────────────────────────────────────────────────
                        if is_unsteady:
                            # 检测到扰动 → 非稳态
                            new_is_retuning = False
                            new_is_unsteady = True
                            if not previous_is_unsteady:  # 状态变化时才打印
                                state_changed = True
                                print(f"  🚨 [{loop['name']}] 稳态 → 非稳态 (检测到扰动)")
                                # 🔧 写入OPC UA状态节点
                                await _write_state_to_opcua(loop_id, "DISTURBANCE")
                        else:
                            # 系统稳定 → 稳态
                            new_is_retuning = False
                            new_is_unsteady = False
                            if previous_is_unsteady:  # 状态变化时才打印
                                state_changed = True
                                print(f"  ✅ [{loop['name']}] 非稳态 → 稳态 (扰动消失)")
                                # 🔧 写入OPC UA状态节点
                                await _write_state_to_opcua(loop_id, "STABLE")
                    
                    # 构建新的状态
                    new_status = {
                        'is_unsteady': new_is_unsteady,
                        'last_check': datetime.now().isoformat(),
                        'is_retuning': new_is_retuning
                    }
                    
                    # 🔧 整定时间管理
                    if new_is_retuning:
                        # 正在整定中，保留开始时间
                        if retuning_start_time:
                            new_status['retuning_start_time'] = retuning_start_time
                    # 未在整定中时，不设置 retuning_start_time，让它自动清除
                    
                    # 始终更新状态（即使状态未变化，也要更新last_check）
                    loops_storage.update_loop(loop_id, {
                        'stability_status': new_status
                    })
                    
                    # 打印状态变化（仅在状态改变时）
                    if new_is_unsteady != previous_is_unsteady or new_is_retuning != previous_is_retuning:
                        status_desc = "正在整定" if new_is_retuning else ("非稳态" if new_is_unsteady else "稳态")
                        print(f"  📊 [{loop['name']}] 状态更新: {status_desc} (OPC UA: {opcua_state or 'N/A'})")
                        print(f"      → 回路管理状态已同步: is_unsteady={new_is_unsteady}, is_retuning={new_is_retuning}")
                    
                    # 🔧 注意：自动整定触发由 auto_tuning_system 负责
                    # stability_monitoring_task 只负责状态检测和更新
                
                except Exception as e:
                    print(f"⚠️ 检测回路 {loop_id} 稳定性时出错: {str(e)}")
                    continue
        
        except Exception as e:
            print(f"❌ 稳定性监控任务错误: {str(e)}")
            await asyncio.sleep(5)


def calculate_performance_metrics(pv_data, sv_data, mv_data, window=20):
    """
    计算实时性能指标
    
    Args:
        pv_data: PV数据列表
        sv_data: SV数据列表
        mv_data: MV数据列表
        window: 计算窗口大小
    
    Returns:
        dict: 性能指标
    """
    if len(pv_data) < window:
        return {
            'score': 0,
            'grade': 'N/A',
            'error': 0.0,
            'last_update': datetime.now().isoformat()
        }
    
    # 取最近的数据
    recent_pv = np.array(pv_data[-window:])
    recent_sv = np.array(sv_data[-window:])
    recent_mv = np.array(mv_data[-window:])
    
    # 计算误差
    error = recent_pv - recent_sv
    mae = np.mean(np.abs(error))  # 平均绝对误差
    rmse = np.sqrt(np.mean(error ** 2))  # 均方根误差
    error_std = np.std(error)  # 误差标准差
    
    # 计算振荡指标
    pv_range = np.max(recent_pv) - np.min(recent_pv)
    sv_mean = np.mean(recent_sv)
    oscillation = pv_range / (sv_mean + 1e-6) if sv_mean > 0 else 0
    
    # 计算MV变化率（控制平滑度）
    mv_changes = np.abs(np.diff(recent_mv))
    mv_smoothness = np.mean(mv_changes)
    
    # 综合评分 (0-100)
    # 误差越小越好，振荡越小越好，MV变化越小越好
    error_score = max(0, 100 - mae * 10)  # 误差评分
    oscillation_score = max(0, 100 - oscillation * 100)  # 振荡评分
    smoothness_score = max(0, 100 - mv_smoothness * 2)  # 平滑度评分
    
    # 加权平均
    total_score = int(error_score * 0.5 + oscillation_score * 0.3 + smoothness_score * 0.2)
    total_score = max(0, min(100, total_score))  # 限制在0-100
    
    # 评级
    if total_score >= 90:
        grade = 'A'
    elif total_score >= 80:
        grade = 'B'
    elif total_score >= 70:
        grade = 'C'
    elif total_score >= 60:
        grade = 'D'
    else:
        grade = 'F'
    
    return {
        'score': total_score,
        'grade': grade,
        'error': round(mae, 3),
        'rmse': round(rmse, 3),
        'oscillation': round(oscillation * 100, 2),  # 百分比
        'mv_smoothness': round(mv_smoothness, 3),
        'last_update': datetime.now().isoformat()
    }


def detect_unsteady_state(pv_data, sv_data, window=20):
    """
    检测非稳态（优化版，与StabilityDetector保持一致）
    
    Args:
        pv_data: PV数据列表
        sv_data: SV数据列表
        window: 检测窗口大小
    
    Returns:
        bool: 是否为非稳态
    """
    if len(pv_data) < window:
        return False
    
    # 取最近的数据
    recent_pv = np.array(pv_data[-window:])
    recent_sv = np.array(sv_data[-window:])
    
    # 计算误差
    error = recent_pv - recent_sv
    
    # 计算误差的标准差
    error_std = np.std(error)
    
    # 计算误差的平均值
    error_mean = np.abs(np.mean(error))
    
    # 计算PV的波动范围（新增：直接检测PV振荡）
    pv_range = np.max(recent_pv) - np.min(recent_pv)
    pv_std = np.std(recent_pv)
    
    # 计算SV的范围
    sv_range = np.max(recent_sv) - np.min(recent_sv)
    sv_mean = np.mean(recent_sv) if len(recent_sv) > 0 else 25.0
    
    # 非稳态判断条件（加强检测）
    # 1. 误差标准差过大（振荡）
    # 2. 平均误差过大（偏离设定值）
    # 3. SV变化过大（设定值频繁变化）
    # 4. PV波动范围过大（新增：直接检测振荡）
    # 5. PV标准差过大（新增：检测持续波动）
    
    # 使用配置文件中的阈值
    is_oscillating = error_std > STABILITY_THRESHOLDS['oscillation_std']
    is_offset = error_mean > STABILITY_THRESHOLDS['offset_mean']
    is_sv_changing = sv_range > STABILITY_THRESHOLDS['sv_change_range']
    
    # 新增：PV波动检测（与StabilityDetector保持一致）
    # 绝对波动阈值：2.0个单位
    # 相对波动阈值：20%的设定值
    is_pv_oscillating = (pv_range > 2.0) or (pv_range > sv_mean * 0.2)
    is_pv_unstable = pv_std > 0.5  # PV标准差阈值
    
    # 判断是否非稳态
    is_unsteady = bool(is_oscillating or is_offset or is_sv_changing or is_pv_oscillating or is_pv_unstable)
    
    # 打印调试信息（仅在检测到非稳态时打印，减少日志噪音）
    if is_unsteady:
        print(f"  📊 检测指标: error_std={error_std:.2f}, error_mean={error_mean:.2f}, pv_range={pv_range:.2f}, pv_std={pv_std:.2f}")
        print(f"  📊 判断结果: 误差振荡={is_oscillating}, 偏差={is_offset}, SV变化={is_sv_changing}, PV振荡={is_pv_oscillating}")
    
    return is_unsteady


@app.on_event("startup")
async def startup_event():
    """应用启动时执行"""
    global realtime_performance_service, auto_tuning_system
    
    print("🚀 启动后端服务...")
    
    # 🔧 为所有OPC UA回路添加默认状态节点ID（如果缺失）
    print("🔧 检查并配置OPC UA状态节点...")
    all_loops = loops_storage.get_all_loops()
    opcua_loops = [loop for loop in all_loops if loop.get('data_source') == 'opcua']
    for loop in opcua_loops:
        opcua_config = loop.get('opcua_config', {})
        if not opcua_config.get('state_node_id'):
            # 添加默认状态节点ID（与OPC UA Server保持一致）
            opcua_config['state_node_id'] = 'ns=2;i=1010'
            loops_storage.update_loop(loop['id'], {'opcua_config': opcua_config})
            print(f"   ✅ 为回路 {loop.get('name', loop['id'])} 添加状态节点: ns=2;i=1010")
    
    # 初始化自动整定系统（如果可用）
    if AutoTuningSystem:
        print("🔧 初始化自动整定系统...")
        auto_tuning_system = AutoTuningSystem(
            loops_storage=loops_storage,
            opcua_client=opcua_client
        )
        print("✅ 自动整定系统已初始化")
        print("🔍 启动自动整定监控任务...")
        asyncio.create_task(auto_tuning_monitoring_task())
    
    # 🔧 修复：始终启动稳定性监控任务
    # 用于处理手动整定后的状态恢复，以及未被 auto_tuning_system 监控的回路
    print("🔍 启动稳定性监控任务...")
    asyncio.create_task(stability_monitoring_task())
    
    # 恢复OPC UA采集任务
    print("🔄 恢复OPC UA采集任务...")
    await restore_opcua_collections()
    
    # 启动实时性能计算服务
    print("📊 启动实时性能计算服务...")
    realtime_performance_service = RealtimePerformanceService(opcua_client)
    asyncio.create_task(realtime_performance_service.start())
    
    print("✅ 后端服务启动完成")

async def restore_opcua_collections():
    """恢复所有标记为采集中的OPC UA回路"""
    try:
        all_loops = loops_storage.get_all_loops()
        opcua_loops = [loop for loop in all_loops if loop.get('data_source') == 'opcua']
        
        restored_count = 0
        for loop in opcua_loops:
            opcua_config = loop.get('opcua_config', {})
            if opcua_config.get('is_collecting'):
                loop_id = loop['id']
                pv_node = opcua_config.get('pv_node_id')
                sv_node = opcua_config.get('sv_node_id')
                mv_node = opcua_config.get('mv_node_id')
                
                # 检查节点配置是否完整
                if not all([pv_node, sv_node, mv_node]):
                    print(f"  ⚠️  回路 {loop['name']} 节点配置不完整，跳过")
                    # 重置采集标志
                    opcua_config['is_collecting'] = False
                    loops_storage.update_loop(loop_id, {'opcua_config': opcua_config})
                    continue
                
                # 尝试启动采集
                try:
                    result = await opcua_client.start_continuous_collection(
                        pv_node,
                        sv_node,
                        mv_node,
                        opcua_config.get('sampling_interval', 1000),
                        loop_id
                    )
                    
                    if result.get('success'):
                        print(f"  ✅ 恢复回路 {loop['name']} 的采集")
                        restored_count += 1
                    else:
                        print(f"  ❌ 恢复回路 {loop['name']} 失败: {result.get('message')}")
                        # 重置采集标志
                        opcua_config['is_collecting'] = False
                        loops_storage.update_loop(loop_id, {'opcua_config': opcua_config})
                        
                except Exception as e:
                    print(f"  ❌ 恢复回路 {loop['name']} 异常: {str(e)}")
                    # 重置采集标志
                    opcua_config['is_collecting'] = False
                    loops_storage.update_loop(loop_id, {'opcua_config': opcua_config})
        
        if restored_count > 0:
            print(f"✅ 成功恢复 {restored_count} 个采集任务")
        else:
            print("ℹ️  没有需要恢复的采集任务")
            
    except Exception as e:
        print(f"❌ 恢复采集任务失败: {str(e)}")


async def auto_tuning_monitoring_task():
    """自动整定监控任务"""
    print("✅ 自动整定监控任务已启动")
    
    # 等待系统初始化
    while auto_tuning_system is None:
        await asyncio.sleep(1)
    
    # 启动所有OPC UA回路的监控
    while True:
        try:
            all_loops = loops_storage.get_all_loops()
            
            for loop in all_loops:
                if loop.get('data_source') == 'opcua':
                    opcua_config = loop.get('opcua_config', {})
                    
                    # 如果正在采集且未监控，启动监控
                    if opcua_config.get('is_collecting'):
                        loop_id = loop['id']
                        
                        if not auto_tuning_system.is_monitoring(loop_id):
                            await auto_tuning_system.start_monitoring(loop_id)
                            print(f"✅ 已启动回路 {loop_id} 的自动整定监控")
        
        except Exception as e:
            print(f"❌ 监控任务错误: {e}")
        
        await asyncio.sleep(10)  # 每10秒检查一次


# ============================================================================
# WebSocket端点 - 实时状态推送
# ============================================================================

@app.websocket("/ws/loops/{loop_id}")
async def websocket_endpoint(websocket: WebSocket, loop_id: str):
    """WebSocket端点 - 实时状态推送"""
    if not ws_manager:
        await websocket.close(code=1011, reason="WebSocket功能不可用")
        return
    
    await ws_manager.connect(websocket, loop_id)
    
    try:
        while True:
            # 保持连接活跃，接收客户端消息
            data = await websocket.receive_text()
            # 可以处理客户端发来的消息（如心跳包）
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, loop_id)
    except Exception as e:
        print(f"❌ WebSocket错误: {e}")
        ws_manager.disconnect(websocket, loop_id)


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时执行"""
    print("👋 关闭后端服务...")


def kill_port(port: int, force: bool = False):
    """
    清理占用指定端口的进程
    
    Args:
        port: 要清理的端口号
        force: 是否强制终止（使用SIGKILL）
    """
    import subprocess
    import signal
    import time
    
    try:
        # 查找占用端口的进程
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split('\n')
            for pid_str in pids:
                try:
                    pid = int(pid_str)
                    print(f"🔧 发现端口 {port} 被进程 {pid} 占用，正在清理...")
                    
                    # 先尝试优雅终止
                    os.kill(pid, signal.SIGTERM)
                    
                    # 等待进程终止
                    time.sleep(0.5)
                    
                    # 检查进程是否还存在
                    try:
                        os.kill(pid, 0)  # 发送信号0检查进程是否存在
                        if force:
                            print(f"⚠️  进程 {pid} 未响应SIGTERM，使用SIGKILL强制终止...")
                            os.kill(pid, signal.SIGKILL)
                            print(f"✅ 已强制终止进程 {pid}")
                        else:
                            print(f"⚠️  进程 {pid} 可能仍在运行")
                    except ProcessLookupError:
                        print(f"✅ 已终止进程 {pid}")
                        
                except (ValueError, ProcessLookupError) as e:
                    print(f"⚠️  清理进程 {pid_str} 失败: {e}")
        else:
            print(f"✅ 端口 {port} 未被占用")
            
    except FileNotFoundError:
        # lsof 命令不存在（Windows系统）
        print(f"⚠️  无法检查端口占用（lsof命令不可用）")
        print(f"💡 提示: Windows系统请手动检查端口占用")
    except Exception as e:
        print(f"⚠️  清理端口时出错: {e}")


if __name__ == "__main__":
    import uvicorn
    import signal
    
    # 配置
    PORT = 8000
    HOST = "0.0.0.0"
    
    print("=" * 60)
    print("🎛️  PID参数整定系统 - 后端服务")
    print("=" * 60)
    
    # 启动前先清理端口
    print(f"\n🔍 检查端口 {PORT} 占用情况...")
    kill_port(PORT, force=True)  # 使用force=True确保清理成功
    
    # 启动服务
    print(f"\n🚀 在 {HOST}:{PORT} 启动服务...")
    print(f"📚 API文档: http://localhost:{PORT}/docs")
    print(f"🔧 健康检查: http://localhost:{PORT}/health")
    print("=" * 60)
    print()
    
    try:
        uvicorn.run(
            app, 
            host=HOST, 
            port=PORT,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\n👋 收到中断信号，正在关闭服务...")
    except Exception as e:
        print(f"\n\n❌ 服务启动失败: {e}")
        import traceback
        traceback.print_exc()
