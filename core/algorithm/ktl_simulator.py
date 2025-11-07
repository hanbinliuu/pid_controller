#!/usr/bin/env python3
"""
KTL模型仿真曲线生成器
基于K(增益)、T(时间常数)、L(纯滞后)参数生成一阶惯性加纯滞后(FOPDT)模型的阶跃响应曲线
"""

import numpy as np
from typing import Dict, List, Tuple, Optional, Any
import logging
import matplotlib
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
    """KTL模型仿真器：生成基于FOPDT模型的阶跃响应曲线"""
    
    @staticmethod
    def generate_fopdt_response(
        K: float,
        T: float,
        L: float = 0.0,
        step_value: float = 1.0,
        duration: float = 600.0,
        dt: float = 1.0,
        initial_output: float = 0.0
    ) -> Dict[str, Any]:
        """
        生成一阶惯性加纯滞后(FOPDT)模型的阶跃响应曲线
        
        模型传递函数: G(s) = K * exp(-L*s) / (T*s + 1)
        
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
        try:
            # 参数验证
            if K <= 0:
                raise ValueError(f"增益K必须大于0，当前值: {K}")
            if T <= 0:
                raise ValueError(f"时间常数T必须大于0，当前值: {T}")
            if L < 0:
                raise ValueError(f"纯滞后L不能为负，当前值: {L}")
            if dt <= 0 or dt > duration:
                raise ValueError(f"采样间隔dt必须在(0, {duration}]范围内，当前值: {dt}")
                
            # 生成时间序列
            t = np.arange(0, duration + dt, dt)
            n = len(t)
            
            # 输入信号（阶跃信号）
            u = np.ones(n) * step_value
            
            # 输出信号初始化
            y = np.ones(n) * initial_output
            
            # 计算纯滞后对应的采样点数
            delay_steps = int(L / dt)
            
            # 一阶惯性系统仿真（使用欧拉法）
            for i in range(1, n):
                # 考虑纯滞后：使用delay_steps前的输入
                if i > delay_steps:
                    u_delayed = u[i - delay_steps]
                else:
                    u_delayed = 0.0  # 滞后期间输入为0
                
                # 一阶惯性微分方程: dy/dt = (K*u - y) / T
                # 离散化: y[i] = y[i-1] + (K*u_delayed - y[i-1]) / T * dt
                dy = (K * u_delayed - y[i-1]) / T * dt
                y[i] = y[i-1] + dy
            
            logger.info(f"生成FOPDT响应曲线: K={K}, T={T}, L={L}, 数据点数={n}")
            
            return {
                "time": t.tolist(),
                "input": u.tolist(),
                "output": y.tolist(),
                "parameters": {
                    "K": float(K),
                    "T": float(T),
                    "L": float(L),
                    "step_value": float(step_value),
                    "duration": float(duration),
                    "dt": float(dt)
                }
            }
            
        except Exception as e:
            logger.error(f"生成FOPDT响应曲线失败: {str(e)}")
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
            y: 输出序列
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
    def generate_pid_response(
        K: float,
        T: float,
        L: float,
        Kp: float,
        Ki: float,
        Kd: float,
        setpoint: float = 100.0,
        duration: float = 600.0,
        dt: float = 1.0
    ) -> Dict[str, Any]:
        """
        生成PID控制下的闭环响应曲线
        
        参数:
            K, T, L: 被控对象FOPDT模型参数
            Kp, Ki, Kd: PID控制器参数
            setpoint: 设定值
            duration: 仿真时长 (秒)
            dt: 采样时间间隔 (秒)
            
        返回:
            包含时间、设定值、过程值、控制输出的字典
        """
        try:
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
            
            # 纯滞后缓冲区
            delay_steps = int(L / dt)
            u_buffer = np.zeros(max(delay_steps, 1))
            
            for i in range(1, n):
                # 计算误差
                error = sp[i-1] - pv[i-1]
                
                # PID控制
                integral += error * dt
                derivative = (error - prev_error) / dt if i > 1 else 0.0
                
                u[i] = Kp * error + Ki * integral + Kd * derivative
                
                # 控制输出限幅 (0-100%)
                u[i] = np.clip(u[i], 0.0, 100.0)
                
                prev_error = error
                
                # 获取延迟后的控制输出
                if delay_steps > 0:
                    u_delayed = u_buffer[0]
                    u_buffer = np.roll(u_buffer, -1)
                    u_buffer[-1] = u[i]
                else:
                    u_delayed = u[i]
                
                # 一阶惯性过程响应
                dy = (K * u_delayed - pv[i-1]) / T * dt
                pv[i] = pv[i-1] + dy
            
            logger.info(f"生成PID闭环响应: Kp={Kp}, Ki={Ki}, Kd={Kd}, 数据点数={n}")
            
            return {
                "time": t.tolist(),
                "setpoint": sp.tolist(),
                "process_value": pv.tolist(),
                "control_output": u.tolist(),
                "parameters": {
                    "K": float(K),
                    "T": float(T),
                    "L": float(L),
                    "Kp": float(Kp),
                    "Ki": float(Ki),
                    "Kd": float(Kd),
                    "setpoint": float(setpoint),
                    "duration": float(duration),
                    "dt": float(dt)
                }
            }
            
        except Exception as e:
            logger.error(f"生成PID闭环响应失败: {str(e)}")
            raise
    
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
                ax.set_title(f'PID闭环响应曲线 (Kp={params.get("Kp", 0):.2f}, Ki={params.get("Ki", 0):.3f}, Kd={params.get("Kd", 0):.3f})', 
                           fontsize=14, fontweight='bold')
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
                ax.set_title(f'FOPDT模型阶跃响应 (K={params.get("K", 0):.2f}, T={params.get("T", 0):.1f}s, L={params.get("L", 0):.1f}s)', 
                           fontsize=14, fontweight='bold')
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