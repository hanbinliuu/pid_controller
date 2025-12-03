import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional, Union
from datetime import datetime
import json
import logging

from api.routes.time_util import parse_time_to_milliseconds
from core.agent.tools import process_query_tsdb_data_interpolated, detect_and_visualize
from core.algorithm.ktl_simulator import KTLSimulator
from api.services.expert_tuning_service import ExpertTuningService
from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database, query_raw_data
from core.utils.model_type import ModelType

router = APIRouter()
logger = logging.getLogger(__name__)

#获取整定模型类型接口

model_type = ModelType.get_model_type()

@router.post("/tuning-windows",
             summary="常规整定-自动筛选时间区间",
             operation_id="常规整定自动筛选时间区间",
             description="自动识别温度曲线中高波动时段，输出适合经典整定分析的时间窗口列表")
async def get_tuning_windows(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"] ),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[30, 60]),
        variability_threshold: float = Query(0.8, description="波动性阈值分位数(0-1)", examples=[0.8]),
        analyst_column: Optional[str] = Query("pv", description="用于波动判断的列名", examples=["pv", "mv", "sv"]),
        window_sec: int = Query(60, description="插值采样间隔（分钟）", examples=[1, 60]),
        is_filter: bool = Query(False, description="是否对历史数据进行优化过滤（按最新参数）", examples=[False])
):
    """
    根据历史数据自动筛选适合常规整定的分析时间区间：
    - 计算温度(PV)在滑动窗口内的方差，识别高波动区间
    - 每个窗口附带 group_key = "{pb}_{ti}_{td}_{sv}", 用于后续分组分析
    """
    try:
        # 调用Service层获取整定时间窗口
        result = ExpertTuningService.get_tuning_windows(
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time,
            window_size=window_size,
            step_size=step_size,
            variability_threshold=variability_threshold,
            analyst_column=analyst_column,
            window_sec=window_sec,
            is_filter=is_filter
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"时间区间筛选失败: {str(e)}")

@router.post("/auto-tuning",
             summary="常规整定-自动筛选时间整定",
             operation_id="常规整定-自动筛选整定与手动时间范围整定",
             description="支持两种模式：1.自动筛选最佳时间窗口并整定 2.手动指定时间范围整定")
async def auto_tuning(
        mode: str = Query("auto", description="整定模式：auto(自动筛选) 或 manual(手动指定时间范围)",
                          examples=["auto", "manual"]),
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"] ),
        start_time: Union[int, str] = Query(None, required=False,
                                            description="开始时间（manual模式必填），支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False,
                                          description="结束时间（manual模式必填），支持毫秒时间戳或字符串格式"),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=ModelType.get_model_type()),
        lambda_val: Optional[float] = Query(None, description="Lambda参数值（可选），未指定时自动计算"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[10, 30]),
        confidence_threshold: float = Query(0.6, description="置信度阈值（仅auto模式有效，0-1）", examples=[0.6, 0.7]),
        window_sec: int = Query(60, description="插值采样间隔（秒）", examples=[60, 120]),
        is_filter: bool = Query(False, description="是否对历史数据进行优化过滤", examples=[False])
):
    """
    **智能PID参数整定接口**

    支持两种整定模式：

    **1. 自动筛选模式 (mode="auto")：**
    - 自动识别历史数据中的高质量时间窗口
    - 基于阶跃响应检测选择最佳辨识区间
    - 自动执行参数辨识与Lambda整定
    - 返回推荐的PID参数及窗口信息

    **2. 手动指定模式 (mode="manual")：**
    - 用户指定具体时间范围 (start_time, end_time)
    - 直接对指定区间进行参数辨识
    - 执行Lambda整定计算
    - 返回PID参数建议

    **Lambda整定参数：**
    - lambda_val: 期望闭环时间常数，影响响应速度与稳健性
    - 未指定时自动根据模型类型计算最优值
    """
    try:
        # 调用Service层执行自动整定
        result = ExpertTuningService.auto_tuning(
            mode=mode,
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time,
            model_type=model_type,
            lambda_val=lambda_val,
            window_size=window_size,
            step_size=step_size,
            confidence_threshold=confidence_threshold,
            window_sec=window_sec,
            is_filter=is_filter
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动整定失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"参数整定失败: {str(e)}")

@router.get("/detect_and_visualize",
            summary="设备状态识别",
            operation_id="设备状态识别",
            description="智能识别时间区间数据状态（稳态、非稳态）")
async def auto_detect_and_visualize(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                                 examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式")
):
    try:
        # 调用Service层执行状态识别
        result = ExpertTuningService.detect_and_visualize_service(
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")

@router.post("/calculate-pid",
             summary="PID计算",
             operation_id="根据KTL和模型类型计算PID参数",
             description="根据输入的模型参数(K、T、L)和模型类型，直接计算对应的PID参数")
async def calculate_pid(
        K: float = Query(..., description="增益系数 K", examples=[0.5, 1.0, 2.0]),
        T1: float = Query(..., description="时间常数 T1 (秒)", examples=[10.0, 30.0, 50.0]),
        T2: Optional[float] = Query(None, description="二阶时间常数 T2 (秒，仅二阶模型需要)", examples=[10.0, 20.0]),
        L: Optional[float] = Query(0, description="滞后时间 L (秒)", examples=[0, 1.0, 5.0]),
        lambda_val: Optional[float] = Query(None, description="Lambda值（期望闭环时间常数），不指定时自动计算",
                                            examples=[10.0, 30.0]),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=ModelType.get_model_type())
):
    """
    **直接PID参数计算接口**

    根据输入的系统模型参数(K、T、L等)和模型类型，使用Lambda方法直接计算PID参数。

    **参数说明：**
    - K: 系统增益，值越大系统反应越灵敏
    - T: 时间常数，决定系统响应速度
    - T2: 仅用于二阶模型(SOPDT, SO, SO_INTEGRATOR)
    - L: 滞后时间，仅用于带滞后的模型(FOPDT, SOPDT)
    - lambda_val: Lambda值，越小响应越快但风险越大；越大响应越慢但更稳定
    - model_type: 选择对应的模型类型

    **模型类型说明：**
    - FOPDT: 一阶加纯滞后模型 G(s) = K/(Ts+1)*e^(-Ls) - 通用工业过程
    - FO: 一阶模型 G(s) = K/(Ts+1) - 无滞后系统
    - SOPDT: 二阶加纯滞后模型 G(s) = K/((T1s+1)(T2s+1))*e^(-Ls) - 温度、化学过程
    - SO: 纯二阶模型 G(s) = K/((T1s+1)(T2s+1)) - 无滞后二阶系统
    - FO_INTEGRATOR: 一阶积分模型 G(s) = K/(s(Ts+1)) - 流量累积、液位控制
    - SO_INTEGRATOR: 二阶积分模型 G(s) = K/(s^2(T1s+1)(T2s+1)) - 双积分过程

    **返回值：**
    - params: 计算的PID参数 (Kp, Ki, Kd)
    - model_type: 使用的模型类型
    - lambda: 实际使用的Lambda值
    - recommendations: 针对选定模型类型的应用建议
    """
    try:
        # 调用Service层计算PID参数
        result = ExpertTuningService.calculate_pid(
            K=K,
            T1=T1,
            T2=T2,
            L=L,
            lambda_val=lambda_val,
            model_type=model_type
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PID参数计算失败: {str(e)}"
        )

@router.post("/generate-all-curves",
             summary="仿真曲线生成（拟合、闭环、阶跃响应）",
             operation_id="统一生成拟合、闭环、阶跃响应三种曲线",
             description="根据模型参数和PID参数，一次性生成拟合曲线、闭环仿真曲线和阶跃响应曲线")
async def generate_all_curves(
        # loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
        #                          examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间"),
        # 模型参数
        K: float = Query(..., description="系统增益 K", examples=[0.5, 1.0, 2.0]),
        T1: float = Query(..., description="时间常数 T (秒)", examples=[10.0, 30.0, 50.0]),
        T2: Optional[float] = Query(None, description="二阶时间常数 T2 (秒)", examples=[10.0, 20.0]),
        L: Optional[float] = Query(0, description="滞后时间 L (秒)", examples=[0, 1.0, 5.0]),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=ModelType.get_model_type()),
        # PID参数
        Kp: Optional[float] = Query(..., description="PID比例系数", examples=[1.0]),
        Ki: Optional[float] = Query(..., description="PID积分系数", examples=[0.1]),
        Kd: Optional[float] = Query(..., description="PID微分系数", examples=[0]),
        # 数据源参数 - 用于拟合和初始值

        step_value: float = Query(1.0, description="阶跃输入幅值", examples=[1.0, 10.0]),
        duration: float = Query(600.0, description="仿真时长(秒)", examples=[300.0, 600.0]),
        dt: float = Query(1.0, description="采样时间间隔(秒)", examples=[0.1, 1.0]),
        initial_output: float = Query(0.0, description="初始输出值", examples=[0.0]),
        setpoint: Optional[float] = Query(None, description="PID设定值", examples=[100.0]),
):
    """
    **三种仿真曲线统一生成接口**

    一个统一接口，同时生成：
    1. **拟合曲线**: 模型与实际数据的拟合效果
    2. **闭环仿真曲线**: 使用PID参数的闭环控制响应
    3. **阶跃响应曲线**: 系统的开环阶跃响应特性

    **数据源模式:**
    - 支持数据库查询模式(start_time, end_time)或直接数据模式(t_data, y_actual)
    """
    try:
        from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier, PIDController

        # 参数验证
        if K <= 0 or T1 <= 0:
            raise HTTPException(status_code=400, detail="K和T1必须大于0")
        if (L and L < 0) or (Ki and Ki <= 0) or (Kd and Kd < 0):
            raise HTTPException(status_code=400, detail="参数值无效")

        mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

        result = {
            "model_type": mt_str,
            "start_time": start_time,
            "end_time": end_time,
            "model_parameters": {
                "K": K,
                "T1": T1,
                "T2": float(T2) if T2 else 0.0,
                "L": float(L) if L else 0.0
            },
            "pid_parameters": {
                "Kp": float(Kp),
                "Ki": float(Ki),
                "Kd": float(Kd),
            }
        }
        # 时间默认值：最近2小时
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 2 * 60 * 60 * 1000  # 默认2小时

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")
        # 从数据库查询
        # db = get_default_database()
        # table = "PID_FEP_Gateway_Device_001default"
        # required_fields = DEFAULT_FIELD_MAPPING
        # table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # data_list = process_query_tsdb_data_interpolated(
        #     db=db,
        #     table_name=table,
        #     required_fields=required_fields,
        #     start_time=start_time_ms,
        #     end_time=end_time_ms,
        #     window=1,
        #     is_filter=False
        # )
        # 获取实际数据

        # if data_list:
        #     t_list, pv_list, mv_list = [], [], []
        #     for item in data_list:
        #         if 'timestamp' in item and 'pv' in item:
        #             t_list.append(item['timestamp'])
        #             pv_list.append(float(item.get('pv', 0.0)))
        #
        #     if t_list and len(t_list) > 0:
        #         t_fit = np.array(t_list, dtype=float) / 1000.0
        #         # 确保数组不为空再进行减法操作
        #         if len(t_fit) > 0:
        #             t_fit = t_fit - t_fit[0]
        #         y_fit = np.array(pv_list, dtype=float)
        #     else:
        #         raise ValueError("数据中缺少timestamp或pv字段")
        # else:
        #     raise ValueError("查询数据为空")
        # ==================== 1. 生成模拟拟合曲线 ====================
        # fitting_result = {}
        # try:
        #     fitting_result = KTLSimulator.simulation_curve(
        #         data_list=data_list,
        #         model_params={'K': K, 'T1': T1, 'T2': T2, 'L': L},
        #         model_type=ModelType.FOPDT.value
        #     )
        # except Exception as e:
        #     fitting_result = {"status": "error", "detail": f"拟合曲线生成失败: {str(e)}"}

        # ==================== 2. 生成闭环仿真曲线 ====================
        closed_loop_result = {}
        try:
            closed_loop_result = KTLSimulator.generate_closed_loop_response(
                model_type=ModelType.FOPDT.value,
                parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
                Kp=Kp,
                Ki=Ki,
                Kd=Kd,
                setpoint=setpoint,
                duration=duration,
                dt=dt
            )
        except Exception as e:
            closed_loop_result = {"status": "error", "detail": f"闭环曲线生成失败: {str(e)}"}

        # ==================== 3. 生成阶跃响应曲线 ====================
        step_response_result = {}
        try:
            # 生成开环阶跃响应
            step_response_result = KTLSimulator.generate_response(
                model_type=ModelType.FOPDT.value,
                parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
                step_value=step_value,
                duration=duration,
                dt=dt,
                initial_output=initial_output
            )

            # 计算性能指标
            # generate_response_result = KTLSimulator.calculate_performance_metrics(
            #     t=step_response_result["time"],
            #     y=step_response_result["output"],
            #     step_value=step_value,
            #     K=K
            # )
        except Exception as e:
            step_response_result = {"status": "error", "detail": f"阶跃响应曲线生成失败: {str(e)}"}

        # 组合结果
        # result["fitting_curve"] = fitting_result
        result["closed_loop_curve"] = closed_loop_result
        result["step_response_curve"] = step_response_result

        # # 生成三合一图片
        # plot_path = None
        # try:
        #     import matplotlib.pyplot as plt
        #     import os
        #     from datetime import datetime
        #
        #     # 配置中文字体
        #     plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS']
        #     plt.rcParams['axes.unicode_minus'] = False
        #
        #     # 创建图片保存目录
        #     output_dir = "data/plots"
        #     os.makedirs(output_dir, exist_ok=True)
        #
        #     # 创建包含3个子图的figure，尺寸参考_plot_model_comparison
        #     fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 14))
        #
        #     # ========== 子图1: 拟合曲线 ==========
        #     if fitting_result.get("status") != "error":
        #         # simulation_curve 返回：{timestamp, time, sv, pv, mv, pv_model, r_squared, rmse}
        #         if "timestamp" in fitting_result and "pv" in fitting_result and "pv_model" in fitting_result:
        #             # 使用真实时间戳
        #             timestamps = fitting_result["timestamp"]
        #             # 将毫秒时间戳转为秒级相对时间用于绘图
        #             if len(timestamps) > 0:
        #                 t0 = timestamps[0]
        #                 time_for_plot = [(t - t0) / 1000.0 for t in timestamps]
        #             else:
        #                 time_for_plot = timestamps
        #
        #             # 绘制PV曲线，样式参考_plot_model_comparison
        #             ax1.plot(time_for_plot, fitting_result["pv"], 'b-', linewidth=2, label='PV (实际值)', alpha=0.8)
        #             ax1.plot(time_for_plot, fitting_result["pv_model"], 'r--', linewidth=2, label='PV (模型拟合)', alpha=0.8)
        #
        #             # 如果有SV，绘制SV曲线
        #             if "sv" in fitting_result and len(fitting_result["sv"]) > 0:
        #                 ax1.plot(time_for_plot, fitting_result["sv"], 'g--', linewidth=1.5, label='SV (目标值)', alpha=0.7)
        #
        #             ax1.set_ylabel('PV / SV', fontsize=12)
        #             ax1.set_xlabel('时间 (秒)', fontsize=12)
        #             ax1.grid(True, alpha=0.3)
        #             r2 = fitting_result.get('r_squared', 0)
        #             rmse_val = fitting_result.get('rmse', 0)
        #             ax1.set_title(f'模式1: 拟合模式 - 实际数据 vs 模型预测 (R²={r2:.4f}, RMSE={rmse_val:.4f})',
        #                          fontsize=12, fontweight='bold')
        #             ax1.legend(loc='best', fontsize=10)
        #         else:
        #             ax1.text(0.5, 0.5, '拟合曲线数据不完整',
        #                     ha='center', va='center', fontsize=14, transform=ax1.transAxes, color='gray')
        #             ax1.set_title('模式1: 拟合模式', fontsize=12, fontweight='bold')
        #     else:
        #         ax1.text(0.5, 0.5, f"拟合曲线生成失败\n{fitting_result.get('detail', '')}",
        #                 ha='center', va='center', fontsize=14, transform=ax1.transAxes, color='gray')
        #         ax1.set_title('模式1: 拟合模式', fontsize=12, fontweight='bold')
        #     ax1.grid(True, alpha=0.3)
        #
        #     # ========== 子图2: 闭环仿真曲线 ==========
        #     if closed_loop_result.get("status") != "error":
        #         # generate_closed_loop_response 返回：{time, setpoint, process_value, control_output}
        #         if "time" in closed_loop_result and "process_value" in closed_loop_result:
        #             ax2.plot(closed_loop_result["time"], closed_loop_result["process_value"],
        #                     'purple', linewidth=2, label='PV (闭环仿真)', alpha=0.8)
        #
        #             if "control_output" in closed_loop_result:
        #                 ax2.plot(closed_loop_result["time"], closed_loop_result["control_output"],
        #                         'orange', linewidth=1.5, label='MV (闭环控制)', alpha=0.7, linestyle='--')
        #
        #             if "setpoint" in closed_loop_result:
        #                 ax2.plot(closed_loop_result["time"], closed_loop_result["setpoint"],
        #                         'g--', linewidth=1.5, label='SV (目标值)', alpha=0.7)
        #
        #             ax2.set_ylabel('PV / SV / MV', fontsize=12)
        #             ax2.set_xlabel('时间 (秒)', fontsize=12)
        #             ax2.set_title('模式2: 闭环仿真 - 使用推荐PID参数的控制效果',
        #                          fontsize=12, fontweight='bold')
        #             ax2.legend(loc='best', fontsize=10)
        #         else:
        #             ax2.text(0.5, 0.5, '闭环仿真数据不完整',
        #                     ha='center', va='center', fontsize=14, transform=ax2.transAxes, color='gray')
        #             ax2.set_title('模式2: 闭环仿真', fontsize=12, fontweight='bold')
        #     else:
        #         ax2.text(0.5, 0.5, f"闭环曲线生成失败\n{closed_loop_result.get('detail', '')}",
        #                 ha='center', va='center', fontsize=14, transform=ax2.transAxes, color='gray')
        #         ax2.set_title('模式2: 闭环仿真', fontsize=12, fontweight='bold')
        #     ax2.grid(True, alpha=0.3)
        #
        #     # ========== 子图3: 阶跃响应曲线 ==========
        #     if step_response_result.get("status") != "error":
        #         # generate_response 返回：{time, input, output}
        #         if "time" in step_response_result and "output" in step_response_result:
        #             ax3.plot(step_response_result["time"], step_response_result["output"],
        #                     'teal', linewidth=2, label='PV (阶跃响应)', alpha=0.8)
        #
        #             if "input" in step_response_result:
        #                 ax3.plot(step_response_result["time"], step_response_result["input"],
        #                         'brown', linewidth=1.5, label='MV (阶跃输入)', alpha=0.7, linestyle='--')
        #
        #             ax3.set_ylabel('PV / MV', fontsize=12)
        #             ax3.set_xlabel('时间 (秒)', fontsize=12)
        #
        #             # 在标题中显示PID参数
        #             pid_info = ''
        #             if Kp is not None and Ki is not None and Kd is not None:
        #                 pid_info = f' (PID: Kp={Kp:.3f}, Ki={Ki:.3f}, Kd={Kd:.3f})'
        #
        #             ax3.set_title(f'模式3: 阶跃响应 - 系统开环阶跃响应特性{pid_info}',
        #                          fontsize=12, fontweight='bold')
        #             ax3.legend(loc='best', fontsize=10)
        #         else:
        #             ax3.text(0.5, 0.5, '阶跃响应数据不完整',
        #                     ha='center', va='center', fontsize=14, transform=ax3.transAxes, color='gray')
        #             ax3.set_title('模式3: 阶跃响应', fontsize=12, fontweight='bold')
        #     else:
        #         ax3.text(0.5, 0.5, f"阶跃响应曲线生成失败\n{step_response_result.get('detail', '')}",
        #                 ha='center', va='center', fontsize=14, transform=ax3.transAxes, color='gray')
        #         ax3.set_title('模式3: 阶跃响应', fontsize=12, fontweight='bold')
        #     ax3.grid(True, alpha=0.3)
        #
        #     # 总标题：包含模型参数和拟合指标
        #     title = f'模型辨识结果 ({mt_str})\n'
        #     title += f'K={K:.3f}, T1={T1:.2f}s'
        #     if T2:
        #         title += f', T2={T2:.2f}s'
        #     if L:
        #         title += f', L={L:.2f}s'
        #
        #     # 添加拟合指标
        #     if fitting_result.get("status") != "error" and "r_squared" in fitting_result:
        #         r2 = fitting_result.get('r_squared', 0)
        #         rmse_val = fitting_result.get('rmse', 0)
        #         title += f' | R²={r2:.4f}, RMSE={rmse_val:.4f}'
        #
        #     fig.suptitle(title, fontsize=14, fontweight='bold', y=0.995)
        #
        #     # 调整子图间距
        #     plt.tight_layout()
        #
        #     # 保存图片
        #     timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        #     plot_filename = f"{mt_str}_three_curves_{timestamp}.png"
        #     plot_path = os.path.join(output_dir, plot_filename)
        #     plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        #     plt.close(fig)
        #
        #     logger.info(f"三合一曲线图已保存: {plot_path}")
        #
        # except Exception as e:
        #     logger.error(f"生成三合一曲线图失败: {str(e)}")
        #     plot_path = None
        #
        # # 添加图片路径到结果
        # result["plot_generated"] = plot_path is not None
        # result["plot_path"] = plot_path

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"曲线生成失败: {str(e)}")


@router.get("/step-response-windows",
            summary="常规整定-阶跃响应时间窗口获取",
            # operation_id="获取含有阶跃响应的时间窗口",
            description="常规整定-基于阶跃响应检测自动识别并筛选高质量参数辨识窗口")
async def get_step_response_windows(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                                 examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[10, 30]),
        step_threshold: float = Query(0.05, description="阶跃检测阈值（占输入范围的百分比）", ge=0.01, le=0.5),
        min_response_ratio: float = Query(0.1, description="最小响应比例（响应幅值/输入变化）", ge=0.05, le=1.0),
        confidence_min: float = Query(0.5, description="最小置信度要求（0-1）", ge=0, le=1),
        analyst_column: Optional[str] = Query("pv", description="用于分析的列名", examples=["pv", "mv", "sv"]),
        window_sec: int = Query(60, description="插值采样间隔（分钟）", examples=[1, 60]),
        is_filter: bool = Query(False, description="是否对历史数据进行优化过滤", examples=[False])
):
    """
    基于阶跃响应检测的专用时间窗口获取接口

    **功能说明:**
    - 在历史数据中识别含有明显阶跃响应的时间窗口
    - 通过置信度过滤确保数据质量
    - 返回的每个窗口都包含完整的阶跃响应特征信息
    - 特别适用于FOPDT等模型的参数辨识

    **返回窗口信息:**
    - start_time / end_time: 窗口时间范围（毫秒）
    - step_detected: 是否检测到阶跃
    - confidence: 置信度评分（0-1）
    - response_magnitude: 响应幅值
    - response_ratio: 响应比例
    - rise_time: 上升时间（秒）
    - settling_time: 稳定时间（秒）
    - group_key: 参数分组键
    - last_pid: 窗口内最后的PID参数
    - recommendation: 推荐等级（优秀/良好/可接受/不推荐）
    """
    try:
        from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier

        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24 * 60 * 60 * 1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        # table = "PID_FEP_Gateway_Device_001default"
        # required_fields = DEFAULT_FIELD_MAPPING
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # 查询历史数据
        db = get_default_database()
        history_data = process_query_tsdb_data_interpolated(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=is_filter,
            window=window_sec
        )
        if not history_data or len(history_data) < 20:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行阶跃响应检测"
            )

        # 构建DataFrame
        df = pd.DataFrame(history_data)
        column = analyst_column or "pv"
        if "timestamp" not in df.columns or column not in df.columns:
            raise HTTPException(status_code=500, detail=f"历史数据缺少必要字段: timestamp 或 {column}")

        if "mv" not in df.columns:
            raise HTTPException(status_code=500, detail="历史数据缺少MV字段")

        # 生成滑动窗口
        timestamps = np.array(df["timestamp"].values, dtype=float)
        t_sec = (timestamps - timestamps[0]) / 1000.0  # 转换为相对秒数

        window_size_sec = window_size * 60
        step_size_sec = step_size * 60
        dt = float(t_sec[1] - t_sec[0]) if len(t_sec) > 1 else 1.0

        window_size_points = int(window_size_sec / dt) if dt > 0 else 120
        step_size_points = int(step_size_sec / dt) if dt > 0 else 10

        windows = []
        for i in range(0, len(t_sec) - window_size_points, max(1, step_size_points)):
            window_end_idx = min(i + window_size_points, len(t_sec) - 1)
            if window_end_idx - i < 20:
                continue

            windows.append({
                'start_idx': i,
                'end_idx': window_end_idx,
                'start_time': int(timestamps[i]),
                'end_time': int(timestamps[window_end_idx])
            })

        # 对每个窗口进行阶跃检测
        qualified_windows = []
        for win in windows:
            start_idx = win['start_idx']
            end_idx = win['end_idx']

            t_win = t_sec[start_idx:end_idx + 1]
            y_win = np.array(df[column].values[start_idx:end_idx + 1], dtype=float)
            u_win = np.array(df["mv"].values[start_idx:end_idx + 1], dtype=float)

            # 检测阶跃响应
            step_result = SystemIdentifier.detect_step_response_in_window(
                t_window=t_win,
                y_window=y_win,
                u_window=u_win,
                step_threshold=step_threshold,
                response_ratio=min_response_ratio
            )

            if step_result['has_step'] and step_result['confidence'] >= confidence_min:
                confidence = step_result['confidence']
                if confidence >= 0.85:
                    recommendation = "优秀"
                elif confidence >= 0.70:
                    recommendation = "良好"
                elif confidence >= 0.50:
                    recommendation = "可接受"
                else:
                    recommendation = "不推荐"

                # 获取窗口内的PID参数
                win_df = df.iloc[start_idx:end_idx + 1]
                if len(win_df) > 0:
                    last = win_df.iloc[-1]
                    pb = last.get("pb")
                    ti = last.get("ti")
                    td = last.get("td")
                    sv = last.get("sv")
                    group_key = f"{pb}_{ti}_{td}_{sv}"
                    kp = last.get("kp")
                    ki = last.get("ki")
                    kd = last.get("kd")
                else:
                    group_key = None
                    kp = ki = kd = None

                qualified_window = {
                    'start_time': win['start_time'],
                    'end_time': win['end_time'],
                    'step_detected': step_result['has_step'],
                    'step_idx': int(step_result['step_idx']),
                    'response_magnitude': float(step_result['response_magnitude']),
                    'response_ratio': float(step_result['response_ratio']),
                    'rise_time': float(step_result['rise_time']),
                    'settling_time': float(step_result['settling_time']),
                    'confidence': float(step_result['confidence']),
                    'recommendation': recommendation,
                    'group_key': group_key,
                    'last_pid': {"kp": kp, "ki": ki, "kd": kd}
                }
                qualified_windows.append(qualified_window)

        # 选择最优窗口
        optimal_window = None
        if qualified_windows:
            optimal_window = max(qualified_windows, key=lambda x: x['confidence'])

        return {
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "step_threshold": step_threshold,
                "min_response_ratio": min_response_ratio,
                "confidence_min": confidence_min,
                "analyst_column": analyst_column or "pv",
                "window_sec": window_sec,
                "is_filter": is_filter
            },
            "total_windows": len(windows),
            "qualified_windows": qualified_windows,
            "analysis_summary": {
                "total_examined": len(windows),
                "with_step_response": len(qualified_windows),
                "optimal_window": optimal_window
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"阶跃响应窗口获取失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"阶跃响应窗口获取失败: {str(e)}")


@router.get("/detect_and_visualize",
            summary="设备状态识别",
            operation_id="设备状态识别",
            description="智能识别时间区间数据状态（稳态、非稳态）")
async def auto_detect_and_visualize(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                                 examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式")
):
    try:
        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24 * 60 * 60 * 1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        # table = "PID_FEP_Gateway_Device_001default"
        # required_fields = DEFAULT_FIELD_MAPPING
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # 查询历史数据
        db = get_default_database()
        history_data = process_query_tsdb_data_interpolated(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=False,
            window=1
        )
        if not history_data or len(history_data) < 10:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行时间窗口筛选"
            )

        # 调用自动筛选方法
        result = detect_and_visualize(history_data)

        return {
            "start_time": start_time,
            "end_time": end_time,
            "result": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"识别失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"识别失败: {str(e)}")


@router.post("/calculate-pid",
             summary="PID计算",
             operation_id="根据KTL和模型类型计算PID参数",
             description="根据输入的模型参数(K、T、L)和模型类型，直接计算对应的PID参数")
async def calculate_pid(
        K: float = Query(..., description="增益系数 K", examples=[0.5, 1.0, 2.0]),
        T1: float = Query(..., description="时间常数 T1 (秒)", examples=[10.0, 30.0, 50.0]),
        T2: Optional[float] = Query(None, description="二阶时间常数 T2 (秒，仅二阶模型需要)", examples=[10.0, 20.0]),
        L: Optional[float] = Query(0, description="滞后时间 L (秒)", examples=[0, 1.0, 5.0]),
        lambda_val: Optional[float] = Query(None, description="Lambda值（期望闭环时间常数），不指定时自动计算",
                                            examples=[10.0, 30.0]),
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=["FOPDT", "FO", "SOPDT", "SO", "FO_INTEGRATOR", "SO_INTEGRATOR"])
):
    """
    **直接PID参数计算接口**

    根据输入的系统模型参数(K、T、L等)和模型类型，使用Lambda方法直接计算PID参数。

    **参数说明：**
    - K: 系统增益，值越大系统反应越灵敏
    - T: 时间常数，决定系统响应速度
    - T2: 仅用于二阶模型(SOPDT, SO, SO_INTEGRATOR)
    - L: 滞后时间，仅用于带滞后的模型(FOPDT, SOPDT)
    - lambda_val: Lambda值，越小响应越快但风险越大；越大响应越慢但更稳定
    - model_type: 选择对应的模型类型

    **模型类型说明：**
    - FOPDT: 一阶加纯滞后模型 G(s) = K/(Ts+1)*e^(-Ls) - 通用工业过程
    - FO: 一阶模型 G(s) = K/(Ts+1) - 无滞后系统
    - SOPDT: 二阶加纯滞后模型 G(s) = K/((T1s+1)(T2s+1))*e^(-Ls) - 温度、化学过程
    - SO: 纯二阶模型 G(s) = K/((T1s+1)(T2s+1)) - 无滞后二阶系统
    - FO_INTEGRATOR: 一阶积分模型 G(s) = K/(s(Ts+1)) - 流量累积、液位控制
    - SO_INTEGRATOR: 二阶积分模型 G(s) = K/(s^2(T1s+1)(T2s+1)) - 双积分过程

    **返回值：**
    - params: 计算的PID参数 (Kp, Ki, Kd)
    - model_type: 使用的模型类型
    - lambda: 实际使用的Lambda值
    - recommendations: 针对选定模型类型的应用建议
    """
    try:
        # 转换ModelType为字符串
        mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

        # 参数验证
        if K <= 0:
            raise HTTPException(status_code=400, detail="K值必须大于0")
        if T1 <= 0:
            raise HTTPException(status_code=400, detail="T值必须大于0")
        if L is not None and L < 0:
            raise HTTPException(status_code=400, detail="L值不能为负")

        # 确保L有默认值
        if L is None:
            L = 0.0

        # 根据模型类型验证参数
        if mt_str in ['SOPDT', 'SO', 'SO_INTEGRATOR']:
            if T2 is None or T2 <= 0:
                raise HTTPException(status_code=400, detail=f"{mt_str}模型需要有效的T2参数（大于0）")

        # 调用Lambda整定
        if mt_str in ['FOPDT', 'FO']:
            # 一阶模型
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                K, T1, L if L else 0,
                model_type=mt_str,
                lambda_val=lambda_val,
                mode="flow_control"
            )
        elif mt_str in ['SOPDT', 'SO']:
            # 二阶模型
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                K, T1, T2, L if L else 0,
                model_type=mt_str,
                lambda_val=lambda_val,
                mode="flow_control"
            )
        elif mt_str == 'FO_INTEGRATOR':
            # 一阶积分模型
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                K, T1,
                model_type=mt_str,
                lambda_val=lambda_val,
                mode="flow_control"
            )
        elif mt_str == 'SO_INTEGRATOR':
            # 二阶积分模型
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                K, T1, T2,
                model_type=mt_str,
                lambda_val=lambda_val,
                mode="flow_control"
            )
        else:
            raise HTTPException(status_code=400, detail=f"不支持的模型类型: {mt_str}")

        # 计算Ki和Kd
        Ki = Kp / Ti if Ti > 1e-6 else 0.0
        Kd = Kp * Td

        # 实际使用的Lambda值
        actual_lambda = lambda_val
        if actual_lambda is None:
            if mt_str == 'FO_INTEGRATOR':
                actual_lambda = max(T1 * 1.0, 0.2)
            elif mt_str == 'SO_INTEGRATOR':
                T2_val = T2 if T2 is not None else T1
                T_eq = T1 + T2_val
                actual_lambda = max(T_eq * 1.0, 0.5)
            elif mt_str in ['SOPDT', 'SO']:
                T2_val = T2 if T2 is not None else T1
                T_eq = T1 + T2_val
                actual_lambda = T_eq * 1.0
            else:  # FOPDT, FO
                actual_lambda = T1 * 0.8

        # 生成应用建议
        recommendations = _get_model_recommendations(mt_str)

        response = {
            "model_type": mt_str,
            "input_parameters": {
                "K": float(K),
                "T": float(T1),
                "T2": float(T2) if T2 else None,
                "L": float(L) if L else 0.0,
                "lambda_input": float(lambda_val) if lambda_val else None
            },
            "params": {
                "Kp": float(Kp),
                "Ki": float(Ki),
                "Kd": float(Kd),
                "Ti": float(Ti),
                "Td": float(Td),
                "Pb": float(100 / Kp) if Kp > 1e-6 else None
            },
            "pid_form": "Kp-Ki-Kd",
            "lambda": float(actual_lambda),
            "recommendations": recommendations,
            "note": f"基于{mt_str}模型使用Lambda方法({actual_lambda:.2f}s)的PID参数计算"
        }

        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PID参数计算失败: {str(e)}"
        )

# @router.get("/auto-select-windows",
#             summary="自动筛选参数辨识时间区间",
#             operation_id="自动筛选时间窗口",
#             description="智能识别含有阶跃响应的高质量时间窗口，适用于FOPDT参数辨识")
async def auto_select_time_windows(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca', required=False, description="回路URI",
                                 examples=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca"]),
        start_time: Union[int, str] = Query(None, required=False, description="开始时间，支持毫秒时间戳或字符串格式"),
        end_time: Union[int, str] = Query(None, required=False, description="结束时间，支持毫秒时间戳或字符串格式"),
        window_size: int = Query(120, description="窗口大小（分钟）", examples=[120, 240]),
        step_size: int = Query(10, description="滑动步长（分钟）", examples=[10, 30]),
        min_confidence: float = Query(0.5, description="最小置信度要求（0-1）", ge=0, le=1),
        step_threshold: float = Query(0.05, description="阶跃检测阈值（0-1）", ge=0, le=1),
        min_response_ratio: float = Query(0.1, description="最小响应比例（0-1）", ge=0, le=1)
):
    """
    自动筛选适合参数辨识的时间区间

    **功能说明:**
    - 自动识别含有明显阶跃响应的时间窗口
    - 综合评估输入信号、输出响应、响应特征
    - 返回评分最高的最优窗口

    **返回窗口信息:**
    - start_time / end_time: 窗口时间范围（毫秒）
    - step_detected: 是否检测到阶跃
    - confidence: 置信度评分（0-1）
    - response_magnitude: 响应幅值
    - response_ratio: 响应比例
    - rise_time: 上升时间（秒）
    - settling_time: 稳定时间（秒）
    - recommendation: 推荐等级（优秀/良好/可接受/不推荐）
    """
    try:
        from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier

        # 时间默认值：最近一天
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)
        if start_time is None:
            start_time = end_time - 24 * 60 * 60 * 1000  # 1天

        # 时间转换与校验
        start_time_ms = parse_time_to_milliseconds(start_time)
        end_time_ms = parse_time_to_milliseconds(end_time)
        if start_time_ms >= end_time_ms:
            raise HTTPException(status_code=400, detail="开始时间必须小于结束时间")

        # 固定设备与字段
        # table = "PID_FEP_Gateway_Device_001default"
        # required_fields = DEFAULT_FIELD_MAPPING
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # 查询历史数据
        db = get_default_database()
        history_data = process_query_tsdb_data_interpolated(
            db=db,
            table_name=table,
            required_fields=required_fields,
            start_time=start_time_ms,
            end_time=end_time_ms,
            is_filter=False,
            window=1
        )
        if not history_data or len(history_data) < 10:
            raise HTTPException(
                status_code=404,
                detail="数据不足，无法进行时间窗口筛选"
            )

        # 调用自动筛选方法
        result = SystemIdentifier.auto_select_time_windows(
            history_data=history_data,
            window_size=window_size,
            step_size=step_size,
            min_response_ratio=min_response_ratio,
            step_threshold=step_threshold,
            confidence_min=min_confidence
        )

        # 提取筛选结果中的最优窗口
        optimal_window = result.get("analysis_summary", {}).get("optimal_window") if result.get(
            "status") == "success" else None

        if not optimal_window:
            raise HTTPException(
                status_code=404,
                detail="未找到符条件的时间窗口。请检查时间范围、上基门槛或参数配置是否合理。"
            )

        return {
            "start_time": start_time,
            "end_time": end_time,
            "params": {
                "window_size": window_size,
                "step_size": step_size,
                "step_threshold": step_threshold,
                "min_response_ratio": min_response_ratio,
                "min_confidence": min_confidence
            },
            "total_windows": result.get("total_windows", 0),
            "qualified_windows_count": len(result.get("qualified_windows", [])),
            "optimal_window": optimal_window,
            "analysis_summary": result.get("analysis_summary", {})
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"自动筛选时间窗口失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"自动筛选时间窗口失败: {str(e)}")




# @router.get("/history-data",
#             summary="历史数据查询",
#             operation_id="IOTDA历史数据查询",
#             description="查询指定设备在指定时间范围内的历史数据，支持多种时间格式")
async def get_history_data(
        loop_uri: str = Query('/pid_zd/0b521c82a96d4107a564e4c2678bdeca',required=False,description="回路URI",
                                          examples=["/pid_zd/935cf045bd254867bdfeb113c31467da"] ),
        start_time: Union[int, str] = Query(..., description="开始时间，支持毫秒时间戳或字符串格式",
                                            examples=[1640995200000, "2022-01-01 12:00:00", "2022-01-01T12:00:00",
                                                      "2022-01-01"]),
        end_time: Union[int, str] = Query(..., description="结束时间，支持毫秒时间戳或字符串格式",
                                          examples=[1641081600000, "2022-01-02 12:00:00", "2022-01-02T12:00:00",
                                                    "2022-01-02"])
):
    """
    **获取设备历史数据 - HistoryDataTool**

    从时序数据库(TSDB)中获取指定设备在特定时间范围内的历史数据。

    **时间格式支持：**
    - 毫秒时间戳: 1640995200000
    - 秒时间戳: 1640995200
    - 标准格式: '2022-01-01 12:00:00'
    - ISO 8601格式: '2022-01-01T12:00:00'
    - 日期格式: '2022-01-01'

    **参数验证：**
    - kp > 0 (比例系数必须为正数)
    - ki >= 0 (积分系数不能为负数)
    - kd >= 0 (微分系数不能为负数)

    **返回数据：**
    - timestamp: 时间戳（毫秒）
    - temperature: 实际温度值
    - target_temp: 目标温度设定值
    - kp, ki, kd: PID控制参数
    - control_period: 控制周期
    - max_duty: 最大占空比
    """
    try:
        table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

        # 参数验证
        if not table or not table.strip():
            raise HTTPException(
                status_code=400,
                detail="表名参数不能为空"
            )
        if end_time is None:
            end_time = int(datetime.now().timestamp() * 1000)

        if start_time is None:
            start_time = end_time - 30000  # 1小时前（30秒 * 1000毫秒）
        # 时间格式转换和验证
        try:
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"时间格式错误: {str(e)}"
            )

        # 验证时间范围
        if start_time_ms >= end_time_ms:
            raise HTTPException(
                status_code=400,
                detail="开始时间必须小于结束时间"
            )

        # 使用环境变量中的数据库名
        db = get_default_database()
        # # 将字段列表转换为字段映射map
        # field_list = (list(fields) + ["time"]) if fields is not None else ["time"]
        # # 使用字段名作为key，字段路径作为value
        # required_fields = {f"field_{i}": field for i, field in enumerate(field_list)}

        # 使用新的查询方法
        history_data = query_raw_data(
            db=db,
            table=table,
            fields=list(required_fields.values()),
            start_time=start_time_ms,
            end_time=end_time_ms,
        )

        # 格式化响应数据
        response_data = {
            "table": table,
            "start_time": start_time,
            "end_time": end_time,
            "totalRecords": len(history_data),
            "data": history_data
        }

        return response_data

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取历史数据失败: {str(e)}"
        )


# @router.get("/ktl-simulation",
#             summary="基于KTL参数生成仿真模型曲线",
#             operation_id="KTL仿真曲线生成",
#             description="根据K(增益)、T(时间常数)、L(纯滞后)参数生成模型的阶跃响应曲线")
async def generate_ktl_simulation(
        model_type: ModelType = Query(ModelType.FOPDT, description="模型类型",
                                      examples=ModelType.get_model_type()),
        K: float = Query(..., description="增益系数 K", examples=[0.5, 1.0, 2.0]),
        T1: float = Query(..., description="时间常数 T1 (秒)", examples=[10.0, 30.0, 50.0]),
        T2: Optional[float] = Query(None, description="二阶时间常数 T2 (秒，仅二阶模型需要)", examples=[10.0, 20.0]),
        L: Optional[float] = Query(0, description="滞后时间 L (秒)", examples=[0, 1.0, 5.0]),
        Kp: Optional[float] = Query(None, description="PID比例系数", examples=[1.0]),
        Ki: Optional[float] = Query(None, description="PID积分系数", examples=[0.1]),
        Kd: Optional[float] = Query(None, description="PID微分系数", examples=[0.01]),
        step_value: float = Query(1.0, description="阶跃输入幅值", examples=[1.0, 10.0]),
        duration: float = Query(600.0, description="仿真时长(秒)", examples=[300.0, 600.0]),
        dt: float = Query(1.0, description="采样时间间隔(秒)", examples=[0.1, 1.0]),
        initial_output: float = Query(0.0, description="初始输出值", examples=[0.0]),
        with_pid: bool = Query(False, description="是否生成PID闭环响应", examples=[False]),
        setpoint: Optional[float] = Query(None, description="PID设定值", examples=[100.0]),
        save_plot: bool = Query(True, description="是否保存图片", examples=[True])
):
    """
    基于KTL参数生成模型仿真曲线

    **功能说明:**
    - 生成一阶惯性加纯滞后(FOPDT)模型的阶跃响应曲线
    - 支持开环阶跃响应和PID闭环响应
    - 自动计算性能指标（上升时间、调节时间、超调量等）

    **FOPDT模型:**
    传递函数: G(s) = K * exp(-L*s) / (T*s + 1)
    - K: 系统增益（输出变化/输入变化）
    - T: 时间常数（系统响应速度）
    - L: 纯滞后时间（输入到输出的延迟）
    """
    try:
        plot_path = None

        if with_pid:
            # 生成PID闭环响应
            if Kp is None or Ki is None or Kd is None or setpoint is None:
                raise HTTPException(
                    status_code=400,
                    detail="生成PID闭环响应时必须提供Kp, Ki, Kd和setpoint参数"
                )

            result = KTLSimulator.generate_closed_loop_response(
                model_type=model_type.value,
                parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
                Kp=Kp,
                Ki=Ki,
                Kd=Kd,
                setpoint=setpoint,
                duration=duration,
                dt=dt
            )

            # 保存图片
            if save_plot:
                plot_path = KTLSimulator.save_plot(
                    data=result,
                    simulation_type="closed_loop"
                )

            return {
                "simulation_type": "pid_closed_loop",
                "data": result,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path
            }
        else:
            # 生成开环阶跃响应
            result = KTLSimulator.generate_response(
                model_type=ModelType.FOPDT.value,
                parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
                step_value=step_value,
                duration=duration,
                dt=dt,
                initial_output=initial_output
            )

            # 计算性能指标
            metrics = KTLSimulator.calculate_performance_metrics(
                t=result["time"],
                y=result["output"],
                step_value=step_value,
                K=K
            )

            # 保存图片
            if save_plot:
                plot_path = KTLSimulator.save_plot(
                    data=result,
                    simulation_type="open_loop"
                )

            return {
                "simulation_type": "open_loop_step",
                "data": result,
                "performance_metrics": metrics,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"KTL仿真生成失败: {str(e)}")


def _get_default_value(field: str):
    """获取PID字段默认值"""
    defaults = {
        "temperature": 25.0,
        "kp": 1.0,
        "ki": 0.1,
        "kd": 0.05,
        "target_temp": 25.0,
        "control_period": 100,
        "max_duty": 100
    }
    return defaults.get(field, 0)


def _get_model_recommendations(model_type: str) -> Dict[str, str]:
    """
    获取不同模型类型的应用建议
    """
    recommendations = {
        "FOPDT": "适用于大多数工业过程，具有一定滞后特性。建议用于温度、压力等缓变过程",
        "FO": "适用于无明显滞后的一阶系统。响应较快，适合响应速度要求不高的场景",
        "SOPDT": "适用于复杂工业过程（如温度、化学反应）。具有多惯性和滞后特性",
        "SO": "适用于快速响应的二阶系统。无滞后，可能存在超调，需适当调节Lambda",
        "FO_INTEGRATOR": "适用于流量控制、液位控制等积分特性系统。需要较强的反馈",
        "SO_INTEGRATOR": "适用于复杂的双积分过程。需要更大的Lambda值以保证稳定性"
    }
    return {
        "model_description": recommendations.get(model_type, "未知模型类型"),
        "lambda_selection_tip": "可通过调整lambda_val参数：减小使响应快但波动增加，增大使响应慢但更稳定"
    }
