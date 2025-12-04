#!/usr/bin/env python3
"""
KTL模型仿真曲线生成器
支持多种模型类型：
- FOPDT: 一阶加纯滞后模型
- FO: 纯一阶模型
- SOPDT: 二阶加纯滞后模型
- SO: 纯二阶模型
- FO_INTEGRATOR: 一阶积分模型
- SO_INTEGRATOR: 二阶积分模型
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any, Union
import logging
import matplotlib

from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier

matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
import os
from datetime import datetime

# 配置中文字体支持
try:
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False
except:
    pass

logger = logging.getLogger(__name__)


class KTLSimulator:
    """KTL模型仿真器：支持多种模型类型的阶跃响应曲线生成"""

    @staticmethod
    def simulation_curve(data_list: List[Dict], model_params: Dict[str, float], model_type: str):
        """
            获取模拟曲线
            Args:
                data_list: 设备数据
                model_params: 模型参数字典[K、T1、T2、L]
                model_type: 模型类型
            Returns:
                dict: 包含时间、实际值、模型值和拟合指标
        """
        # 时间轴: 使用timestamp毫秒，转为相对秒
        if 'timestamp' in data_list[0]:
            ts0 = float(data_list[0]['timestamp'])
            t = np.array([(float(r['timestamp']) - ts0) / 1000.0 for r in data_list], dtype=float)
            # 保存真实时间戳（毫秒）
            timestamp_list = np.array([float(r['timestamp']) for r in data_list], dtype=float)
        else:
            t = np.arange(len(data_list), dtype=float)  # 生成相对秒
            timestamp_list = t.copy()  # 如果没有timestamp，使用相对时间

        # 输出y: 使用pv为过程变量
        pv = np.array([float(r.get('pv')) for r in data_list], dtype=float)

        # 初始值y0
        y0 = pv[0]
        # 输入u: 优先使用mv(操纵量/阀门开度)
        mv = []
        if 'mv' in data_list[0]:
            mv = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)
        sv = []
        if 'sv' in data_list[0]:
            sv = np.array([float(r.get('sv')) for r in data_list], dtype=float)

        K = model_params.get('K', 0.5)
        T1 = model_params.get('T1', 30.0)
        T2 = model_params.get('T2', 0.0)
        L = model_params.get('L', 0.0)

        if model_type == 'FO_INTEGRATOR':
            y_model = SystemIdentifier.first_order_integrator_model([K, T1], t, mv, y0)
        elif model_type == 'SO_INTEGRATOR':
            y_model = SystemIdentifier.second_order_integrator_model([K, T1, T2], t, mv, y0)
        elif model_type == 'SOPDT':
            y_model = SystemIdentifier.second_order_model([K, T1, T2, L], t, mv, y0)
        elif model_type == 'SO':
            y_model = SystemIdentifier.second_order_no_delay_model([K, T1, T2], t, mv, y0)
        elif model_type == 'FO':
            y_model = SystemIdentifier.first_order_model([K, T1], t, mv, y0)
        else:  # FOPDT
            y_model = SystemIdentifier.fopdt_model([K, T1, L], t, mv, y0)

        # 计算拟合指标
        ss_res = np.sum((pv - y_model) ** 2)
        ss_tot = np.sum((pv - np.mean(pv)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        rmse = np.sqrt(np.mean((pv - y_model) ** 2))  # 均方根误差

        return {
            "timestamp": timestamp_list.tolist(),  # 真实时间戳（毫秒）
            # "time": t.tolist(),  # 相对时间（秒），保留兼容性
            "sv": sv.tolist() if len(sv) > 0 else [],
            "pv": pv.tolist(),
            "mv": mv.tolist() if len(mv) > 0 else [],
            "pv_model": y_model.tolist(),
            "r_squared": float(r_squared),
            "rmse": float(rmse),
            "model_name": model_type,
            "parameters": model_params
        }

    @staticmethod
    def generate_response(
        model_type: str,
        parameters: Dict[str, float],
        step_value: float = 1.0,
        duration: float = 600.0,
        dt: float = 1.0,
        initial_output: float = 0.0
    ) -> Dict[str, Any]:
        """
        生成指定模型类型的阶跃响应曲线（统一接口）
        
        参数:
            model_type: 模型类型
                - 'fopdt' 或 'FOPDT': 一阶加纯滞后模型 G(s) = K / (T1*s + 1) * e^(-L*s)
                - 'fo' 或 'FO': 纯一阶模型 G(s) = K / (T1*s + 1)
                - 'sopdt' 或 'SOPDT': 二阶加纯滞后模型 G(s) = K / ((T1*s + 1)(T2*s + 1)) * e^(-L*s)
                - 'so' 或 'SO': 纯二阶模型 G(s) = K / ((T1*s + 1)(T2*s + 1))
                - 'fo_integrator' 或 'FO_INTEGRATOR': 一阶积分模型 G(s) = K / (s(T*s + 1))
                - 'so_integrator' 或 'SO_INTEGRATOR': 二阶积分模型 G(s) = K / (s^2 * (T1*s + 1)(T2*s + 1))
            parameters: 模型参数字典
                - FOPDT/FO: {'K': 增益, 'T': 时间常数, 'L': 纯滞后(可选)}
                - SOPDT/SO: {'K': 增益, 'T1': 时间常数1, 'T2': 时间常数2, 'L': 纯滞后(可选)}
                - FO_INTEGRATOR: {'K': 增益, 'T': 时间常数}
                - SO_INTEGRATOR: {'K': 增益, 'T1': 时间常数1, 'T2': 时间常数2}
            step_value: 阶跃输入幅值
            duration: 仿真时长 (秒)
            dt: 采样时间间隔 (秒)
            initial_output: 初始输出值
            
        返回:
            包含时间、输入、输出序列及模型信息的字典
        """
        try:
            # 标准化模型类型
            model_type = model_type.upper()
            
            # 提取公共参数
            K = parameters.get('K')
            if K is None or K <= 0:
                raise ValueError(f"增益K必须大于0，当前值: {K}")
            
            # 生成时间序列
            t = np.arange(0, duration + dt, dt)
            n = len(t)
            u = np.ones(n) * step_value
            y = np.ones(n) * initial_output
            
            # 根据模型类型进行仿真
            if model_type in ['FOPDT', 'FO']:
                # 一阶模型
                T1 = parameters.get('T1')
                L = parameters.get('L', 0.0)
                if T1 is None or T1 <= 0:
                    raise ValueError(f"时间常数T必须大于0，当前值: {T1}")
                if L < 0:
                    raise ValueError(f"纯滞后L不能为负，当前值: {L}")
                
                delay_steps = int(L / dt)
                for i in range(1, n):
                    u_delayed = u[i - delay_steps] if i > delay_steps else 0.0
                    dy = (K * u_delayed - y[i-1]) / T1 * dt
                    y[i] = y[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'L': float(L)}
                
            elif model_type in ['SOPDT', 'SO']:
                # 二阶模型
                T1 = parameters.get('T1')
                T2 = parameters.get('T2')
                L = parameters.get('L', 0.0)
                if T1 is None or T1 <= 0 or T2 is None or T2 <= 0:
                    raise ValueError(f"时间常数T1和T2必须大于0，当前值: T1={T1}, T2={T2}")
                if L < 0:
                    raise ValueError(f"纯滞后L不能为负，当前值: {L}")
                
                delay_steps = int(L / dt)
                y1 = np.ones(n) * initial_output  # 第一阶环节输出
                
                for i in range(1, n):
                    u_delayed = u[i - delay_steps] if i > delay_steps else 0.0
                    dy1 = (K * u_delayed - y1[i-1]) / T1 * dt
                    y1[i] = y1[i-1] + dy1
                    dy = (y1[i] - y[i-1]) / T2 * dt
                    y[i] = y[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'T2': float(T2), 'L': float(L)}
                
            elif model_type == 'FO_INTEGRATOR':
                # 一阶积分模型
                T1 = parameters.get('T1')
                if T1 is None or T1 <= 0:
                    raise ValueError(f"时间常数T必须大于0，当前值: {T1}")
                
                y_int = 0.0  # 积分态
                for i in range(1, n):
                    y_int += K * u[i] * dt
                    dy = (y_int - y[i-1]) / T1 * dt
                    y[i] = y[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1)}
                
            elif model_type == 'SO_INTEGRATOR':
                # 二阶积分模型
                T1 = parameters.get('T1')
                T2 = parameters.get('T2')
                if T1 is None or T1 <= 0 or T2 is None or T2 <= 0:
                    raise ValueError(f"时间常数T1和T2必须大于0，当前值: T1={T1}, T2={T2}")
                
                y_int1 = 0.0  # 一重积分
                y_int2 = 0.0  # 二重积分
                y1 = 0.0      # 第一阶环节输出
                
                for i in range(1, n):
                    y_int1 += K * u[i] * dt
                    y_int2 += y_int1 * dt
                    dy1 = (y_int2 - y1) / T1 * dt
                    y1 = y1 + dy1
                    dy = (y1 - y[i-1]) / T2 * dt
                    y[i] = y[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'T2': float(T2)}
                
            else:
                raise ValueError(f"不支持的模型类型: {model_type}。支持的类型: FOPDT, FO, SOPDT, SO, FO_INTEGRATOR, SO_INTEGRATOR")
            
            # 添加公共参数
            params_dict.update({
                'step_value': float(step_value),
                'duration': float(duration),
                'dt': float(dt)
            })
            
            logger.info(f"生成{model_type}响应曲线: {params_dict}, 数据点数={n}")
            return {
                "time": t.tolist(),
                "input": u.tolist(),
                "output": y.tolist(),
                "model_type": model_type,
                "parameters": params_dict
            }
            
        except Exception as e:
            logger.error(f"生成{model_type}响应曲线失败: {str(e)}")
            raise

    @staticmethod
    def calculate_performance_metrics(
        t: List[float],
        y: List[float],
        step_value: float,
        K: float
    ) -> Dict[str, Any]:
        """
        计算阶跃响应的性能指标
        
        参数:
            t: 时间序列
            y: 输出序列(pv)
            step_value: 阶跃输入幅值
            K: 系统增益
            
        返回:
            性能指标字典
        """
        try:
            y_arr = np.array(y)
            t_arr = np.array(t)
            
            # 稳态值
            steady_state = K * step_value
            
            # 上升时间 (10% -> 90%)
            y_10 = 0.1 * steady_state
            y_90 = 0.9 * steady_state
            
            idx_10 = np.where(y_arr >= y_10)[0]
            idx_90 = np.where(y_arr >= y_90)[0]
            
            if len(idx_10) > 0 and len(idx_90) > 0:
                rise_time = t_arr[idx_90[0]] - t_arr[idx_10[0]]
            else:
                rise_time = None
            
            # 调节时间 (进入±2%稳态误差带)
            tolerance = 0.02 * steady_state
            settling_idx = np.where(np.abs(y_arr - steady_state) <= tolerance)[0]
            
            if len(settling_idx) > 0:
                settling_time = t_arr[settling_idx[0]]
            else:
                settling_time = None
            
            # 超调量
            max_value = np.max(y_arr)
            if steady_state > 0:
                overshoot = ((max_value - steady_state) / steady_state) * 100
            else:
                overshoot = 0.0
            
            # 峰值时间
            peak_idx = np.argmax(y_arr)
            peak_time = t_arr[peak_idx]
            
            return {
                "steady_state": float(steady_state),
                "rise_time": float(rise_time) if rise_time is not None else None,
                "settling_time": float(settling_time) if settling_time is not None else None,
                "overshoot_percent": float(overshoot),
                "peak_time": float(peak_time),
                "peak_value": float(max_value)
            }
            
        except Exception as e:
            logger.error(f"计算性能指标失败: {str(e)}")
            return {}
    
    @staticmethod
    def generate_closed_loop_response(
        model_type: str,
        parameters: Dict[str, float],
        Kp: float,
        Ki: float,
        Kd: float,
        setpoint: float = 100.0,
        duration: float = 600.0,
        dt: float = 1.0
    ) -> Dict[str, Any]:
        """
        生成PID控制下的闭环响应曲线（支持多种模型类型）
        
        参数:
            model_type: 模型类型（'fopdt', 'fo', 'sopdt', 'so', 'fo_integrator', 'so_integrator'）
            parameters: 模型参数字典
                - FOPDT/FO: {'K': 增益, 'T1': 时间常数, 'L': 纯滞后(可选)}
                - SOPDT/SO: {'K': 增益, 'T1': 时间常数1, 'T2': 时间常数2, 'L': 纯滞后(可选)}
                - FO_INTEGRATOR: {'K': 增益, 'T1': 时间常数}
                - SO_INTEGRATOR: {'K': 增益, 'T1': 时间常数1, 'T2': 时间常数2}
            Kp: PID比例增益
            Ki: PID积分增益
            Kd: PID微分增益
            setpoint: 设定值
            duration: 仿真时长 (秒)
            dt: 采样时间间隔 (秒)
            
        返回:
            包含时间、设定值、过程值、控制输出的字典
        """
        try:
            # 标准化模型类型
            model_type = model_type.upper()
            
            # 提取公共参数
            K = parameters.get('K')
            if K is None or K <= 0:
                raise ValueError(f"增益K必须大于0，当前值: {K}")
            
            # 生成时间序列
            t = np.arange(0, duration + dt, dt)
            n = len(t)
            
            # 初始化变量
            pv = np.zeros(n)  # 过程变量
            u = np.zeros(n)   # 控制输出
            sp = np.ones(n) * setpoint  # 设定值
            
            # PID控制器状态变量
            integral = 0.0
            prev_error = 0.0
            
            # 根据模型类型进行闭环仿真
            if model_type in ['FOPDT', 'FO']:
                # 一阶模型
                T1 = parameters.get('T1') or parameters.get('T')
                L = parameters.get('L', 0.0)
                if T1 is None or T1 <= 0:
                    raise ValueError(f"时间常数T1必须大于0，当前值: {T1}")
                if L < 0:
                    raise ValueError(f"纯滞后L不能为负，当前值: {L}")
                
                delay_steps = int(L / dt)
                u_buffer = np.zeros(max(delay_steps, 1))
                
                for i in range(1, n):
                    # PID控制
                    error = sp[i-1] - pv[i-1]
                    integral += error * dt
                    derivative = (error - prev_error) / dt if i > 1 else 0.0
                    u[i] = Kp * error + Ki * integral + Kd * derivative
                    u[i] = np.clip(u[i], 0.0, 100.0)
                    prev_error = error
                    
                    # 获取延迟后的控制输出
                    u_delayed = u_buffer[0] if delay_steps > 0 else u[i]
                    if delay_steps > 0:
                        u_buffer = np.roll(u_buffer, -1)
                        u_buffer[-1] = u[i]
                    
                    # 一阶惯性过程响应
                    dy = (K * u_delayed - pv[i-1]) / T1 * dt
                    pv[i] = pv[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'L': float(L)}
                
            elif model_type in ['SOPDT', 'SO']:
                # 二阶模型
                T1 = parameters.get('T1')
                T2 = parameters.get('T2')
                L = parameters.get('L', 0.0)
                if T1 is None or T1 <= 0 or T2 is None or T2 <= 0:
                    raise ValueError(f"时间常数T1和T2必须大于0，当前值: T1={T1}, T2={T2}")
                if L < 0:
                    raise ValueError(f"纯滞后L不能为负，当前值: {L}")
                
                delay_steps = int(L / dt)
                u_buffer = np.zeros(max(delay_steps, 1))
                pv1 = 0.0  # 第一阶环节输出
                
                for i in range(1, n):
                    # PID控制
                    error = sp[i-1] - pv[i-1]
                    integral += error * dt
                    derivative = (error - prev_error) / dt if i > 1 else 0.0
                    u[i] = Kp * error + Ki * integral + Kd * derivative
                    u[i] = np.clip(u[i], 0.0, 100.0)
                    prev_error = error
                    
                    # 获取延迟后的控制输出
                    u_delayed = u_buffer[0] if delay_steps > 0 else u[i]
                    if delay_steps > 0:
                        u_buffer = np.roll(u_buffer, -1)
                        u_buffer[-1] = u[i]
                    
                    # 二阶过程响应
                    dy1 = (K * u_delayed - pv1) / T1 * dt
                    pv1 = pv1 + dy1
                    dy = (pv1 - pv[i-1]) / T2 * dt
                    pv[i] = pv[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'T2': float(T2), 'L': float(L)}
                
            elif model_type == 'FO_INTEGRATOR':
                # 一阶积分模型
                T1 = parameters.get('T1') or parameters.get('T')
                if T1 is None or T1 <= 0:
                    raise ValueError(f"时间常数T1必须大于0，当前值: {T1}")
                
                pv_int = 0.0  # 积分态
                
                for i in range(1, n):
                    # PID控制
                    error = sp[i-1] - pv[i-1]
                    integral += error * dt
                    derivative = (error - prev_error) / dt if i > 1 else 0.0
                    u[i] = Kp * error + Ki * integral + Kd * derivative
                    u[i] = np.clip(u[i], 0.0, 100.0)
                    prev_error = error
                    
                    # 积分环节
                    pv_int += K * u[i] * dt
                    # 一阶惯性环节
                    dy = (pv_int - pv[i-1]) / T1 * dt
                    pv[i] = pv[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1)}
                
            elif model_type == 'SO_INTEGRATOR':
                # 二阶积分模型
                T1 = parameters.get('T1')
                T2 = parameters.get('T2')
                if T1 is None or T1 <= 0 or T2 is None or T2 <= 0:
                    raise ValueError(f"时间常数T1和T2必须大于0，当前值: T1={T1}, T2={T2}")
                
                pv_int1 = 0.0  # 一重积分
                pv_int2 = 0.0  # 二重积分
                pv1 = 0.0      # 第一阶环节输出
                
                for i in range(1, n):
                    # PID控制
                    error = sp[i-1] - pv[i-1]
                    integral += error * dt
                    derivative = (error - prev_error) / dt if i > 1 else 0.0
                    u[i] = Kp * error + Ki * integral + Kd * derivative
                    u[i] = np.clip(u[i], 0.0, 100.0)
                    prev_error = error
                    
                    # 二重积分
                    pv_int1 += K * u[i] * dt
                    pv_int2 += pv_int1 * dt
                    # 第一阶环节
                    dy1 = (pv_int2 - pv1) / T1 * dt
                    pv1 = pv1 + dy1
                    # 第二阶环节
                    dy = (pv1 - pv[i-1]) / T2 * dt
                    pv[i] = pv[i-1] + dy
                
                params_dict = {'K': float(K), 'T1': float(T1), 'T2': float(T2)}
                
            else:
                raise ValueError(f"不支持的模型类型: {model_type}。支持的类型: FOPDT, FO, SOPDT, SO, FO_INTEGRATOR, SO_INTEGRATOR")
            
            # 添加PID参数和公共参数
            params_dict.update({
                'Kp': float(Kp),
                'Ki': float(Ki),
                'Kd': float(Kd),
                'setpoint': float(setpoint),
                'duration': float(duration),
                'dt': float(dt)
            })
            
            logger.info(f"生成{model_type}模型PID闭环响应: Kp={Kp}, Ki={Ki}, Kd={Kd}, 数据点数={n}")
            
            return {
                "time": t.tolist(),
                "setpoint": sp.tolist(),
                "process_value": pv.tolist(),
                "control_output": u.tolist(),
                "model_type": model_type,
                "parameters": params_dict
            }
            
        except Exception as e:
            logger.error(f"生成PID闭环响应失败: {str(e)}")
            raise

    @staticmethod
    def generate_fopdt_response(
            K: float,
            T1: float,
            T2: float,
            L: float = 0.0,
            step_value: float = 1.0,
            duration: float = 600.0,
            dt: float = 1.0,
            initial_output: float = 0.0
    ) -> Dict[str, Any]:
        """
        生成FOPDT模型的阶跃响应曲线（向后兼容接口）

        此方法保留用于向后兼容，建议使用 generate_response() 统一接口

        模型传递函数: G(s) = K * exp2(-L*s) / (T*s + 1)

        参数:
            K: 系统增益 (过程增益)
            T: 时间常数 (秒)
            L: 纯滞后时间 (秒)
            step_value: 阶跃输入幅值
            duration: 仿真时长 (秒)
            dt: 采样时间间隔 (秒)
            initial_output: 初始输出值

        返回:
            包含时间、输入、输出序列的字典
        """
        return KTLSimulator.generate_response(
            model_type='FOPDT',
            parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
            step_value=step_value,
            duration=duration,
            dt=dt,
            initial_output=initial_output
        )

    @staticmethod
    def save_plot(
        data: Dict[str, Any],
        simulation_type: str = "open_loop",
        output_dir: str = "data/simulated/plots",
        filename: Optional[str] = None,
        figsize: Tuple[int, int] = (12, 8),
        dpi: int = 100
    ) -> str:
        """
        生成仿真曲线图片并保存到文件系统
        
        参数:
            data: 仿真数据字典（包含time、output等字段）
            simulation_type: 仿真类型（"open_loop" 或 "closed_loop"）
            output_dir: 输出目录路径
            filename: 文件名（不指定则自动生成）
            figsize: 图片尺寸（宽, 高）
            dpi: 图片分辨率
            
        返回:
            保存的图片文件路径
        """
        try:
            # 创建输出目录
            os.makedirs(output_dir, exist_ok=True)
            
            # 生成文件名
            if filename is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ktl_{simulation_type}_{timestamp}.png"
            
            output_path = os.path.join(output_dir, filename)
            
            # 创建单个图表
            fig, ax = plt.subplots(figsize=figsize, dpi=dpi)
            
            if simulation_type == "closed_loop":
                # PID闭环响应图 - 所有曲线在一个图中
                time = data.get("time", [])
                setpoint = data.get("setpoint", [])
                pv = data.get("process_value", [])
                mv = data.get("control_output", [])
                params = data.get("parameters", {})
                
                # 绘制所有曲线
                ax.plot(time, setpoint, 'r--', label='设定值(SP)', linewidth=2, alpha=0.8)
                ax.plot(time, pv, 'b-', label='过程变量(PV)', linewidth=1.5)
                ax.plot(time, mv, 'g-', label='控制输出(MV)', linewidth=1.5, alpha=0.7)
                
                ax.set_xlabel('时间 (秒)', fontsize=12)
                ax.set_ylabel('数值', fontsize=12)
                
                # 根据模型类型生成标题
                model_type = data.get("model_type", "FOPDT")
                if model_type == "FOPDT":
                    title = f'PID闭环响应 - FOPDT (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, L={params.get("L", 0):.1f}s, Kp={params.get("Kp", 0):.2f})'
                elif model_type == "FO":
                    title = f'PID闭环响应 - 一阶模型 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, Kp={params.get("Kp", 0):.2f})'
                elif model_type == "SOPDT":
                    title = f'PID闭环响应 - 二阶加纯滞后 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s, L={params.get("L", 0):.1f}s)'
                elif model_type == "SO":
                    title = f'PID闭环响应 - 二阶模型 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s, Kp={params.get("Kp", 0):.2f})'
                elif model_type == "FO_INTEGRATOR":
                    title = f'PID闭环响应 - 一阶积分 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, Kp={params.get("Kp", 0):.2f})'
                elif model_type == "SO_INTEGRATOR":
                    title = f'PID闭环响应 - 二阶积分 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s)'
                else:
                    title = f'PID闭环响应曲线 (Kp={params.get("Kp", 0):.2f}, Ki={params.get("Ki", 0):.3f}, Kd={params.get("Kd", 0):.3f})'
                
                ax.set_title(title, fontsize=14, fontweight='bold')
                ax.legend(loc='best', fontsize=10)
                ax.grid(True, alpha=0.3)
                
            else:
                # 开环阶跃响应图 - 所有曲线在一个图中
                time = data.get("time", [])
                input_signal = data.get("input", [])
                output = data.get("output", [])
                params = data.get("parameters", {})
                
                # 绘制输入和输出曲线
                ax.plot(time, input_signal, 'r-', label='输入信号', linewidth=2, alpha=0.8)
                ax.plot(time, output, 'b-', label='输出响应', linewidth=1.5)
                
                ax.set_xlabel('时间 (秒)', fontsize=12)
                ax.set_ylabel('数值', fontsize=12)
                # 根据模型类型生成标题
                model_type = data.get("model_type", "FOPDT")
                if model_type == "FOPDT":
                    title = f'FOPDT模型阶跃响应 (K={params.get("K", 0):.2f}, T={params.get("T", 0):.1f}s, L={params.get("L", 0):.1f}s)'
                elif model_type == "FO":
                    title = f'一阶模型阶跃响应 (K={params.get("K", 0):.2f}, T={params.get("T", 0):.1f}s)'
                elif model_type == "SOPDT":
                    title = f'二阶加纯滞后模型阶跃响应 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s, L={params.get("L", 0):.1f}s)'
                elif model_type == "SO":
                    title = f'二阶模型阶跃响应 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s)'
                elif model_type == "FO_INTEGRATOR":
                    title = f'一阶积分模型阶跃响应 (K={params.get("K", 0):.2f}, T={params.get("T", 0):.1f}s)'
                elif model_type == "SO_INTEGRATOR":
                    title = f'二阶积分模型阶跃响应 (K={params.get("K", 0):.2f}, T1={params.get("T1", 0):.1f}s, T2={params.get("T2", 0):.1f}s)'
                else:
                    title = f'{model_type}模型阶跃响应'
                
                ax.set_title(title, fontsize=14, fontweight='bold')
                ax.legend(loc='best', fontsize=10)
                ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # 保存图片
            plt.savefig(output_path, format='png', bbox_inches='tight', dpi=dpi)
            plt.close('all')
            
            logger.info(f"成功保存{simulation_type}类型的仿真曲线图片: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"保存图片失败: {str(e)}")
            plt.close('all')
            raise