import logging
import time
from typing import Optional, Dict, List, Union, Any
import json  # 移到全局导入
import traceback  # 添加traceback导入
import sys
import os
from datetime import datetime

import numpy as np
import matplotlib

from api.commond.time_util import parse_time_to_milliseconds
from core.algorithm.detector import StabilityDetector
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import query_raw_data, query_read_interpolated
from core.utils import pid_converter
from core.utils.model_type import ModelType
from core.utils.pid_converter import process_lists_optimized

matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt

from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier
from core.algorithm.ktl_simulator import KTLSimulator

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
logger = logging.getLogger(__name__)


class TemperatureAnalysisTool():
    name: str = "temperature_curve_analysis"
    description: str = """
    分析温度曲线特性的工具。
    分析指标包括：上升时间、超调量、稳态误差、温度波动等。
    输入参数: :param history_data: 必要参数, List[Dict]类型, get_pid_history_data返回的历史数据列表
    输出参数：
            - `current_value`: 当前值
            - `target_value`: 目标值
            - `max_value`: 最高值
            - `min_value`: 最低值
            - `avg_value`: 平均值
            - `temp_std`: 标准差(波动程度)
            - `steady_state`: 稳态值
            - `steady_error`: 稳态误差
            - `overshoot`: 超调量(%)
            - `rise_time`: 上升时间
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _run(self, history_data: str) -> str:
        try:
            # 解析输入的历史数据
            if isinstance(history_data, str):
                try:
                    # 尝试解析JSON格式的历史数据
                    parsed_data = json.loads(history_data)
                    # 处理不同的数据格式
                    if isinstance(parsed_data, list):
                        data_list = parsed_data
                    elif isinstance(parsed_data, dict) and 'data' in parsed_data:
                        data_list = parsed_data['data']
                    else:
                        return json.dumps({"error": "无效的JSON数据格式"})
                except json.JSONDecodeError:
                    return json.dumps({"error": "无效的历史数据格式，请提供JSON格式的数据"})
            elif isinstance(history_data, list):
                data_list = history_data
            else:
                return json.dumps({"error": "历史数据必须是JSON字符串或列表格式"})

            logging.info(f"\nDebug - TemperatureAnalysisTool 分析历史数据:")
            print(f"获取到的数据条数: {len(data_list)}")

            if not data_list:
                print("无历史数据")
                return json.dumps({"error": "无历史数据可分析"})

            # 检查数据格式，确保包含必要字段
            required_fields = ['pv', 'sv']
            first_record = data_list[0]
            #todo 过滤掉异常数据
            missing_fields = [field for field in required_fields if field not in first_record]
            if missing_fields:
                return json.dumps({"error": f"数据缺少必要字段: {missing_fields}"})

            # 提取温度数据和目标温度
            temp_data = [float(record.get('pv', 0)) for record in data_list]
            target_value = float(data_list[-1].get('sv', 0))

            print(f"数据点数: {len(temp_data)}")
            print(f"数据范围: {min(temp_data):.2f} - {max(temp_data):.2f}")
            print(f"目标值: {target_value}")

            # 计算基本统计指标
            metrics = {
                "current_value": float(temp_data[-1]),
                "target_value": float(target_value),
                "max_value": float(max(temp_data)),
                "min_value": float(min(temp_data)),
                "avg_value": float(sum(temp_data) / len(temp_data)),
                "temp_std": self._calculate_std(temp_data),
                "steady_state": float(sum(temp_data[-5:]) / min(5, len(temp_data))),
                "data_points": int(len(temp_data))
            }

            # 计算性能指标
            metrics["steady_error"] = float(metrics["target_value"] - metrics["steady_state"])
            if metrics["target_value"] != 0:
                metrics["overshoot"] = float(((metrics["max_value"] - metrics["target_value"]) / metrics["target_value"]) * 100)
            else:
                metrics["overshoot"] = 0.0

            # 计算上升时间
            temp_range = metrics["max_value"] - metrics["min_value"]
            if temp_range > 0:
                t_90 = metrics["min_value"] + 0.9 * temp_range
                rise_time = None
                for i, temp in enumerate(temp_data):
                    if temp >= t_90:
                        rise_time = i
                        break
                metrics["rise_time"] = rise_time
            else:
                metrics["rise_time"] = None

            print(f"分析结果: {json.dumps(metrics, indent=2)}")
            return json.dumps(metrics)

        except Exception as e:
            print(f"分析失败，错误: {str(e)}")
            print(f"错误堆栈: {traceback.format_exc()}")
            return json.dumps({"error": f"分析失败: {str(e)}"})

    def _calculate_std(self, data_list):
        """计算标准差"""
        if len(data_list) <= 1:
            return 0.0
        mean = sum(data_list) / len(data_list) if len(data_list) > 0 else 0.0
        variance = sum((x - mean) ** 2 for x in data_list) / len(data_list) if len(data_list) > 0 else 0.0
        return variance ** 0.5

class PIDOptimizationTool():
    name: str = "pid_parameter_optimization"
    description: str = """
    优化PID参数的工具。基于设备实时曲线分析结果，给出具体的PID参数调整建议。
    输入参数:
        :param history_data: 必要参数, List[Dict]类型, get_pid_history_data返回的历史数据列表
    输出参数：
        - `current_params`: 当前PID参数
        - `performance`: 性能指标
          - `steady_error`: 稳态误差
          - `stability`: 稳定性
          - `data_points`: 数据点数
        - `status`: 系统状态评估
          - `response_speed`: 响应速度(fast/slow)
          - `stability`: 稳定性(unstable/stable)
          - `accuracy`: 精度 (good/poor)
        - `tuning_suggestions` ：建议参数值
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _run(self, history_data, is_lambda: bool, model_type: ModelType = ModelType.FOPI) -> str:
        try:
            # 解析输入的历史数据
            if isinstance(history_data, str):
                try:
                    # 尝试解析JSON格式的历史数据
                    parsed_data = json.loads(history_data)
                    # 处理不同的数据格式
                    if isinstance(parsed_data, list):
                        data_list = parsed_data
                    elif isinstance(parsed_data, dict) and 'data' in parsed_data:
                        data_list = parsed_data['data']
                    else:
                        return json.dumps({"error": "无效的JSON数据格式"})
                except json.JSONDecodeError:
                    return json.dumps({"error": "无效的历史数据格式，请提供JSON格式的数据"})
            elif isinstance(history_data, list):
                data_list = history_data
            else:
                return json.dumps({"error": "历史数据必须是JSON字符串或列表格式"})

            print(f"\nDebug - PIDOptimizationTool 分析历史数据:")
            print(f"获取到的数据条数: {len(data_list)}")

            if not data_list:
                print("无历史数据")
                return json.dumps({"error": "无历史数据可分析"})

            # 检查数据格式，确保包含PID相关字段
            required_fields = ['pv', 'sv', 'kp', 'ki', 'kd']
            first_record = data_list[0]
            missing_fields = [field for field in required_fields if field not in first_record]
            if missing_fields:
                return json.dumps({"error": f"数据缺少必要字段: {missing_fields}"})

            # 提取当前PID参数（使用最后一条记录）
            last_record = data_list[-1]
            current_params = {
                "kp": float(last_record.get('kp', 1.0)),
                "ki": float(last_record.get('ki', 0.1)),
                "kd": float(last_record.get('kd', 0.05)),
                "sv": float(last_record.get('sv', 25.0))
            }

            # 提取数据进行性能分析
            pv_data = [float(record.get('pv', 25.0)) for record in data_list]

            # 计算性能指标
            temp_std = self._calculate_std(pv_data) #标准差
            steady_state_value = sum(pv_data[-5:]) / min(5, len(pv_data)) #稳态值
            steady_error = float(current_params["sv"] - steady_state_value) #稳态误差

            # 评估系统性能
            #响应速度
            response_speed = "fast" if len(pv_data) > 0 and pv_data[-1] >= current_params["sv"] * 0.9 else "slow"
            #稳定性
            stability = "stable" if temp_std < 0.5 else "unstable"
            #精度
            accuracy = "good" if abs(steady_error) < 0.5 else "poor"
            # 生成调优建议
            tuning_suggestions = self._generate_tuning_suggestions(
                current_params, steady_error, temp_std, response_speed, stability, accuracy
            )
            if is_lambda:
                # 基于Lambda方法的整定建议（支持 mv 与 timestamp）
                try:
                    # 传入model_type参数，默认为'integrator'（一阶积分模型）
                    # 可选：'integrator', 'fopdt', 'first_order', 'second_order'
                    lambda_suggestions = self._compute_lambda_suggestions(data_list, model_type=model_type)
                    if lambda_suggestions is not None:
                        # 检查是否包含错误
                        if lambda_suggestions.get('error', False):
                            # 将错误信息添加到tuning_suggestions中
                            tuning_suggestions["lambda_error"] = {
                                "error_message": lambda_suggestions.get('error_message'),
                                "error_detail": lambda_suggestions.get('error_detail'),
                                "note": lambda_suggestions.get('note')
                            }
                        else:
                            # 成功时添加lambda参数
                            tuning_suggestions["lambda_suggested_params"] = lambda_suggestions
                except Exception as e:
                    # 外层异常捕获（如果_compute_lambda_suggestions抛出异常）
                    tuning_suggestions["lambda_error"] = {
                        "error_message": str(e),
                        "error_detail": traceback.format_exc(),
                        "note": f"Lambda整定调用失败: {str(e)}"
                    }
                    print(f"优化分析失败，错误: {str(e)}")
                    print(f"错误堆栈: {traceback.format_exc()}")
            # 生成分析结果
            analysis_result = {
                "current_params": current_params,
                "performance": {
                    "steady_error": steady_error, #稳态误差
                    "stability": temp_std, #稳定性
                    "steady_state_value": steady_state_value, #稳态温度
                    "data_points": len(pv_data) #测点数量
                },
                "status": {
                    "response_speed": response_speed, #响应速度
                    "stability": stability,#稳定性
                    "accuracy": accuracy #精度
                }
                ,"tuning_suggestions": tuning_suggestions #调参建议
            }

            # print(f"优化分析结果: {json.dumps(analysis_result, indent=2,ensure_ascii=False)}")
            return json.dumps(analysis_result)

        except Exception as e:
            print(f"优化分析失败，错误: {str(e)}")
            print(f"错误堆栈: {traceback.format_exc()}")
            return json.dumps({"error": f"优化分析失败: {str(e)}"})

    def pid_suggested(self, history_data: str, model_type: ModelType = ModelType.FOPI) -> str:
        try:
            # 解析输入的历史数据
            if isinstance(history_data, str):
                try:
                    # 尝试解析JSON格式的历史数据
                    parsed_data = json.loads(history_data)
                    # 处理不同的数据格式
                    if isinstance(parsed_data, list):
                        data_list = parsed_data
                    elif isinstance(parsed_data, dict) and 'data' in parsed_data:
                        data_list = parsed_data['data']
                    else:
                        return json.dumps({"error": "无效的JSON数据格式"})
                except json.JSONDecodeError:
                    return json.dumps({"error": "无效的历史数据格式，请提供JSON格式的数据"})
            elif isinstance(history_data, list):
                data_list = history_data
            else:
                return json.dumps({"error": "历史数据必须是JSON字符串或列表格式"})

            print(f"\nDebug - PIDOptimizationTool 分析历史数据:")
            print(f"获取到的数据条数: {len(data_list)}")

            if not data_list:
                print("无历史数据")
                return json.dumps({"error": "无历史数据可分析"})

            # 检查数据格式，确保包含PID相关字段
            required_fields = ['pv', 'sv', 'kp', 'ki', 'kd']
            first_record = data_list[0]
            missing_fields = [field for field in required_fields if field not in first_record]
            if missing_fields:
                return json.dumps({"error": f"数据缺少必要字段: {missing_fields}"})

            # 提取当前PID参数（使用最后一条记录）
            last_record = data_list[-1]
            current_params = {
                "kp": float(last_record.get('kp', 1.0)),
                "ki": float(last_record.get('ki', 0.1)),
                "kd": float(last_record.get('kd', 0.05)),
                "sv": float(last_record.get('sv', 25.0))
            }

            # 进行性能分析
            temp_data = [float(record.get('pv', 25.0)) for record in data_list]

            # 计算性能指标
            temp_std = self._calculate_std(temp_data)  # 标准差
            steady_state_value = sum(temp_data[-5:]) / min(5, len(temp_data))  # 稳态值
            steady_error = float(current_params["sv"] - steady_state_value)  # 稳态误差

            # 评估系统性能
            # 响应速度
            response_speed = "fast" if len(temp_data) > 0 and temp_data[-1] >= current_params["sv"] * 0.9 else "slow"
            # 稳定性
            stability = "stable" if temp_std < 0.5 else "unstable"
            # 精度
            accuracy = "good" if abs(steady_error) < 0.5 else "poor"


            # 基于Lambda方法的整定建议（支持 mv 与 timestamp）
            # 传入model_type参数，默认为'integrator'（一阶积分模型）
            # 可选：'integrator', 'fopdt', 'first_order', 'second_order'
            lambda_suggestions = self._compute_lambda_suggestions(data_list, model_type=model_type)

            # 生成分析结果
            analysis_result = {
                "current_params": current_params,
                "performance": {
                    "steady_error": steady_error,  # 稳态误差
                    "stability": temp_std,  # 稳定性
                    "steady_state_value": steady_state_value,  # 稳态温度
                    "data_points": len(temp_data)  # 测点数量
                },
                "status": {
                    "response_speed": response_speed,  # 响应速度
                    "stability": stability,  # 稳定性
                    "accuracy": accuracy  # 精度
                }
                , "lambda_suggestions": lambda_suggestions  # 调参建议
            }

            print(f"优化分析结果: {json.dumps(analysis_result, indent=2, ensure_ascii=False)}")
            return json.dumps(analysis_result)
        except Exception as e:
            print(f"优化分析失败，错误: {str(e)}")
            print(f"错误堆栈: {traceback.format_exc()}")
            return json.dumps({"error": f"优化分析失败: {str(e)}"})


    def _calculate_std(self, data_list):
        """计算标准差"""
        if len(data_list) <= 1:
            return 0.0
        mean = sum(data_list) / len(data_list)
        variance = sum((x - mean) ** 2 for x in data_list) / len(data_list)
        return variance ** 0.5

    def _generate_tuning_suggestions(self, current_params, steady_error, temp_std, response_speed, stability, accuracy):
        """生成PID调优建议"""
        suggestions = []

        # 基于稳态误差的建议
        if abs(steady_error) > 1.0:
            if steady_error > 0:  # 当前值低于目标
                suggestions.append("增加Kp参数或Ki参数以提高当前值")
            else:  # 温度高于目标
                suggestions.append("减小Kp参数或Ki参数以降低当前值")

        # 基于稳定性的建议
        if stability == "unstable":
            suggestions.append("系统振荡，建议减小Kp参数或增加Kd参数")

        # 基于响应速度的建议
        if response_speed == "slow":
            suggestions.append("响应过慢，建议适度增加Kp参数")

        return {
            "recommendations": suggestions, #调参建议
            # "suggested_params": suggested_params, #建议值
            "priority": "high" if (abs(steady_error) > 2.0 or stability == "unstable") else "medium" #优先级
        }

    # lambda整定建议 by liuhanbin
    def _compute_lambda_suggestions(self, data_list: List[Dict], model_type: ModelType = ModelType.FOPDT) -> Optional[Dict]:
        """从数据中提取t(秒)、y(pv)、u(mv)，进行模型辨识并返回Lambda整定建议及模型模拟曲线

        Args:
            data_list: 历史数据列表
            model_type: 模型类型，可选值：
                - 'integrator': 一阶积分模型（适合流量累积、液位等系统）
                - 'fopdt': 一阶加纯滞后模型（通用工业过程）
                - 'first_order': 纯一阶模型（无滞后系统）
                - 'second_order': 二阶模型（温度、化学过程）

        Returns:
            包含PID参数、模型参数、拟合指标和图表路径的字典
        """
        mt_str = ''  # 初始化，用于异常处理
        try:
            n = len(data_list)
            # if n < 20:
            #     print(f"数据量少于20组{len(data_list)},无法进行整定分析")
            #     return None

            # 时间轴: 使用timestamp毫秒，转为相对秒
            if 'timestamp' in data_list[0]:
                ts0 = float(data_list[0]['timestamp'])
                t = np.array([(float(r['timestamp']) - ts0) / 1000.0 for r in data_list], dtype=float)
            else:
                t = np.arange(n, dtype=float)

            # 输出y: 使用pv为过程变量
            pv_list = np.array([float(r.get('pv', r.get('temperature', 0.0))) for r in data_list], dtype=float)

            # 输入u: 优先使用mv(操纵量/阀门开度)
            mv_list = None
            if 'mv' in data_list[0]:
                mv_list = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)

            if mv_list is None or np.max(np.abs(mv_list)) < 1e-6:
                return None

            # 统一处理枚举或字符串类型
            mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

            # 判断是否使用瞬态模式：检查末段是否达到稳态
            # 如果末段MV或PV变化剧烈，使用瞬态模式
            u_tail_std = np.std(mv_list[-30:]) if len(mv_list) > 30 else np.std(mv_list)
            y_tail_std = np.std(pv_list[-30:]) if len(pv_list) > 30 else np.std(pv_list)
            y_mean = np.mean(pv_list)
            # 阈值：末段标准差 > 5% 均值时认为未稳定，使用瞬态模式
            transient_mode = (y_tail_std > 0.05 * abs(y_mean)) or (u_tail_std > 0.05 * np.mean(mv_list))

            if transient_mode:
                print("检测到瞬态数据，使用瞬态模式进行辨识")

            # 系统模型参数辨识（根据model_type返回不同数量的参数）
            K, T1, T2, L = SystemIdentifier.identify(t, pv_list, mv_list, model_type=mt_str, transient_mode=bool(transient_mode))
            model_params = {'K': K, 'T1': T1, 'T2': T2, 'L': L}

            # Lambda整定（根据模型类型调用）
            sopdt_params_options = None
            if mt_str == 'FO_INTEGRATOR':
                # 一阶积分模型：传入 K, T
                lambda_val = max(T1 * 1.0, 0.2)
                Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1,
                    model_type=mt_str,
                    lambda_val=lambda_val,
                    mode="flow_control"
                )
            elif mt_str == 'SO_INTEGRATOR':
                # 二阶积分模型：传入 K, T1, T2
                T_eq = T1 + T2
                lambda_val = max(T_eq * 1.0, 0.5)
                Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1, T2,
                    model_type=mt_str,
                    lambda_val=lambda_val,
                    mode="flow_control"
                )
            elif mt_str == 'SOPDT':
                # 二阶模型：传入 K, T1, T2, L
                T_eq = T1 + T2
                # 按要求生成两套参数：λ=T_eq 与 λ=1.5*T_eq
                lambda_val_1 = T_eq * 1.0
                lambda_val_2 = T_eq * 1.5
                Kp1, Ti1, Td1 = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1, T2, L,
                    model_type=mt_str,
                    lambda_val=lambda_val_1,
                    mode="flow_control"
                )
                Kp2, Ti2, Td2 = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1, T2, L,
                    model_type=mt_str,
                    lambda_val=lambda_val_2,
                    mode="flow_control"
                )
                # 默认采用 λ=T_eq 的参数为主返回
                Kp, Ti, Td = Kp1, Ti1, Td1
                lambda_val = lambda_val_1
            elif mt_str == 'SO':
                # 纯二阶模型（无滞后）：传入 K, T1, T2
                T_eq = T1 + T2
                lambda_val = max(T_eq * 1.0, 0.1)
                Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1, T2,
                    model_type=mt_str,
                    lambda_val=lambda_val,
                    mode="flow_control"
                )
            else:
                # FOPDT或一阶模型：传入 K, T, L
                lambda_val = max(T1 * 0.8, 0.1)
                Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(
                    K, T1, L,
                    model_type=mt_str,
                    lambda_val=lambda_val,
                    mode="flow_control"
                )

            #生成模型模拟曲线
            #todo 初始值取值
            y0 = np.mean(pv_list[:30]) if len(pv_list) > 30 else np.mean(pv_list[:min(10, len(pv_list))])
            # 生成模型曲线
            y_model, r_squared, rmse, y_model = self._simulation_curve(data_list,model_params,model_type=mt_str,y0=y0)
            #
            # # 生成闭环仿真曲线（使用推荐的PID参数）
            # pv_closed_loop, mv_closed_loop = self._simulate_closed_loop(
            #     t, data_list, model_params, mt_str, Kp, Ti, Td, y0
            # )
            #
            # # 生成阶跃响应仿真曲线
            # pv_step_response, mv_step_response, t_step = self._simulate_step_response(
            #     model_params, mt_str, y0
            # )
            #
            # # # 绘制对比图（传入三条仿真曲线和PID参数）
            # plot_path = self._plot_model_comparison(
            #     t, mv_list, pv_list, y_model,
            #     model_params, model_type,
            #     r_squared, rmse, data_list,
            #     pv_closed_loop, mv_closed_loop,
            #     pv_step_response, mv_step_response, t_step,
            #     Kp, Ti, Td
            # )

            # 清理和验证所有数值，确保JSON可序列化
            def sanitize_value(val):
                """清理单个数值，替换inf/nan为None或有限值"""
                if isinstance(val, (int, float, np.number)):
                    if not np.isfinite(val):
                        return 0.0  # 将无效值替换为0
                    return float(val)
                return val
            
            def sanitize_array(arr):
                """清理数组中的无效值"""
                if arr is None:
                    return []
                arr = np.asarray(arr)
                # 替换inf和nan为有限值
                arr = np.where(np.isfinite(arr), arr, 0.0)
                return arr.tolist()

            # 构建返回结果（根据model_type适配model字段）
            result = {
                "params": {
                    "Kp": float(Kp),
                    "ki": float(Kp / Ti) if Ti > 1e-6 and np.isfinite(Ti) else 0.0,
                    "kd": float(Kp * Td),
                    "Pb": float(1/Kp* 100) if Kp > 1e-6 and np.isfinite(Kp) else 0.0,
                    "Ti": float(Ti),
                    "Td": float(Td)
                },
                "pid_form": "Kp-Ti-Td",
                "model": {k: float(v) for k, v in model_params.items()},
                "model_type": mt_str,
                "model_evaluation": {
                    "r_squared": float(r_squared),
                    "rmse": float(rmse),
                    "quality": "优秀" if r_squared > 0.95 else ("良好" if r_squared > 0.85 else ("一般" if r_squared > 0.70 else "较差")),
                    "description": f"R²={r_squared:.4f}（越接近1越好），RMSE={rmse:.4f}（越小越好）"
                },
                "lambda": float(lambda_val),
                "simulation": {
                    "fit_metrics": {
                        "r_squared": float(r_squared),
                        "rmse": float(rmse)
                    }
                },
                # "params_options": sopdt_params_options,
                # "plot_saved": plot_path is not None,
                # "plot_path": plot_path,
                "note": f"基于{model_type}模型辨识与Lambda方法的推荐值"
            }
            return result
        except Exception as e:
            # 返回错误信息结构，而不是仅打印
            import traceback
            error_message = str(e)
            error_traceback = traceback.format_exc()
            print(f"Lambda整定计算失败: {error_message}")
            print(f"错误堆栈: {error_traceback}")

            # 返回包含错误信息的结构化数据
            return {
                "error": True,
                "error_message": error_message,
                "error_detail": error_traceback,
                "params": None,
                "model": None,
                "model_type": mt_str,
                "simulation": None,
                "plot_saved": False,
                "plot_path": None,
                "note": f"Lambda整定失败: {error_message}"
            }

    def _simulation_curve(self, data_list, model_params, model_type, y0):
        """
               获取模拟曲线

               Args:
                   data_list: 设备数据
                   model_params: 模型参数字典[K、T1、T2、L]
                   model_type: 模型类型
                   y0: 初始值
               Returns:
                   tuple: (y_model, r_squared, rmse) 模拟曲线和拟合指标
        """
        # 时间轴: 使用timestamp毫秒，转为相对秒
        if 'timestamp' in data_list[0]:
            ts0 = float(data_list[0]['timestamp'])
            t = np.array([(float(r['timestamp']) - ts0) / 1000.0 for r in data_list], dtype=float)
        else:
            t = np.arange(len(data_list), dtype=float) #生成0-n的数组

        # 输出y: 使用pv为过程变量
        pv_list = np.array([float(r.get('pv', r.get('temperature', 0.0))) for r in data_list], dtype=float)

        # 输入u: 优先使用mv(操纵量/阀门开度)
        mv = None
        if 'mv' in data_list[0]:
            mv = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)

        if mv is None or np.max(np.abs(mv)) < 1e-6:
            return None

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
        ss_res = np.sum((pv_list - y_model) ** 2)
        ss_tot = np.sum((pv_list - np.mean(pv_list)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
        rmse = np.sqrt(np.mean((pv_list - y_model) ** 2))  # 均方根误差
        return y_model, r_squared, rmse, y_model

    def _simulate_closed_loop(self, t, data_list, model_params, model_type, Kp, Ti, Td, y0):
        """
        使用推荐的PID参数进行闭环控制仿真

        Args:
            t: 时间序列
            data_list: 原始数据列表
            model_params: 模型参数
            model_type: 模型类型
            Kp, Ti, Td: 推荐的PID参数
            y0: 初始值

        Returns:
            pv_closed_loop: 闭环PV曲线
            mv_closed_loop: 闭环MV曲线
        """
        try:
            from core.algorithm.ls_pid_autotune_v5 import PIDController

            # 时间轴: 使用timestamp毫秒，转为相对秒
            # if 'timestamp' in data_list[0]:
            #     ts0 = float(data_list[0]['timestamp'])
            #     t = np.array([(float(r['timestamp']) - ts0) / 1000.0 for r in data_list], dtype=float)
            # else:
            #     t = np.arange(len(data_list), dtype=float)  # 生成0-n的数组
            #
            # # 输出y: 使用pv为过程变量
            # pv_list = np.array([float(r.get('pv', r.get('temperature', 0.0))) for r in data_list], dtype=float)
            #
            # # 输入u: 优先使用mv(操纵量/阀门开度)
            # mv = None
            # if 'mv' in data_list[0]:
            #     mv = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)
            #
            # if mv is None or np.max(np.abs(mv)) < 1e-6:
            #     return None
            # # 提取SV目标值
            if data_list and 'sv' in data_list[0]:
                sv_values = np.array([float(r.get('sv', y0)) for r in data_list], dtype=float)
            else:
                sv_values = []


            # 闭环仿真
            pv_closed = np.zeros_like(t)
            mv_closed = np.zeros_like(t)
            pv_closed[0] = y0
            mv_closed[0] = 0.0

            K = model_params.get('K', 0.5)
            T1 = model_params.get('T1', 30.0)
            T2 = model_params.get('T2', 0.0)
            L = model_params.get('L', 0.0)

            # 初始化PID控制器
            dt = float(t[1] - t[0]) if len(t) > 1 else 1.0
            pid = PIDController(Kp=Kp, Ti=Ti, Td=Td, dt=dt, u_min=0, u_max=100)
            # 引入纯滞后步数
            delay_steps = int(max(0, np.round(L / dt))) if dt > 1e-6 and np.isfinite(dt) else 0
            # 模拟闭环控制过程
            for i in range(1, len(t)):
                # PID计算控制输出
                mv_closed[i] = pid.compute(sv_values[i], pv_closed[i-1])

                # 使用过程模型计算下一时刻的PV
                # 简化为一阶惯性环节
                if model_type == 'FO_INTEGRATOR' or model_type == 'SO_INTEGRATOR':
                    # 积分模型：输出随时间积分
                    delta_pv = K * mv_closed[i] * dt
                    pv_closed[i] = pv_closed[i-1] + delta_pv / T1 if T1 > 0 and np.isfinite(T1) else pv_closed[i-1]
                else:
                    # 一阶或二阶模型
                    steady_state = y0 + K * mv_closed[i]
                    tau = T1 if T1 > 0 and np.isfinite(T1) else 1.0
                    pv_closed[i] = pv_closed[i-1] + (steady_state - pv_closed[i-1]) * dt / tau if tau > 1e-6 and np.isfinite(tau) else pv_closed[i-1]

            return pv_closed, mv_closed

        except Exception as e:
            print(f"闭环仿真失败: {str(e)}")
            return None, None

    def _simulate_step_response(self, model_params, model_type, y0):
        """
        生成系统阶跃响应曲线（开环）

        Args:
            model_params: 模型参数
            model_type: 模型类型
            y0: 初始值
            data_list: 原始数据列表

        Returns:
            pv_step: 阶跃响应PV曲线
            mv_step: 阶跃响应MV曲线
            t_step: 阶跃响应时间序列
        """
        try:
            # 生成阶跃响应时间序列（300秒，每秒1秒采样）
            t_step = np.arange(0, 300, 1.0)
            n = len(t_step)

            # 阶跃输入：前50秒为0，后面为固定值
            mv_step = np.zeros(n)
            mv_step[50:] = 20.0  # 20%的阶跃

            K = model_params.get('K', 0.5)
            T1 = model_params.get('T1', 30.0)
            T2 = model_params.get('T2', 0.0)
            L = model_params.get('L', 0.0)

            # 根据模型类型生成响应
            if model_type == 'FO_INTEGRATOR':
                pv_step = SystemIdentifier.first_order_integrator_model([K, T1], t_step, mv_step, y0)
            elif model_type == 'SO_INTEGRATOR':
                pv_step = SystemIdentifier.second_order_integrator_model([K, T1, T2], t_step, mv_step, y0)
            elif model_type == 'SOPDT':
                pv_step = SystemIdentifier.second_order_model([K, T1, T2, L], t_step, mv_step, y0)
            elif model_type == 'SO':
                pv_step = SystemIdentifier.second_order_no_delay_model([K, T1, T2], t_step, mv_step, y0)
            elif model_type == 'FO':
                pv_step = SystemIdentifier.first_order_model([K, T1], t_step, mv_step, y0)
            else:  # FOPDT
                pv_step = SystemIdentifier.fopdt_model([K, T1, L], t_step, mv_step, y0)

            return pv_step, mv_step, t_step

        except Exception as e:
            print(f"阶跃响应仿真失败: {str(e)}")
            return None, None, None

    def _plot_model_comparison(self, t, u, y_actual, y_predicted, model_params, model_type, r_squared, rmse, data_list,
                               pv_closed_loop=None, mv_closed_loop=None,
                               pv_step_response=None, mv_step_response=None, t_step=None,
                               Kp=None, Ti=None, Td=None):
        """绘制模型对比图：三个独立网格分别显示三种仿真模式

        Args:
            t: 时间数组
            u: 输入信号（MV）
            y_actual: 实际输出（PV）
            y_predicted: 模型预测输出（拟合模式）
            model_params: 模型参数字典
            model_type: 模型类型
            r_squared: R²拟合指标
            rmse: RMSE拟合指标
            data_list: 原始数据列表
            pv_closed_loop: 闭环PV曲线
            mv_closed_loop: 闭环MV曲线
            pv_step_response: 阶跃响应PV曲线
            mv_step_response: 阶跃响应MV曲线
            t_step: 阶跃响应时间序列
            Kp, Ti, Td: 推荐的PID参数
        """
        try:
            # 配置中文字体
            plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False

            # 将时间转换为年月日时分秒格式（用于图表X轴显示）
            if data_list and 'timestamp' in data_list[0]:
                ts0 = float(data_list[0]['timestamp'])
                time_labels = [datetime.fromtimestamp(ts0 / 1000.0 + t_val).strftime('%Y-%m-%d %H:%M:%S')
                              for t_val in t]
            else:
                # 如果没有timestamp，使用相对秒数
                time_labels = [f'{t_val:.1f}s' for t_val in t]

            # 创建3个垂直排列的子图：拟合模式 + 闭环仿真 + 阶跃响应
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 14))

            # 提取SV目标值曲线
            sv_values = None
            if data_list and 'sv' in data_list[0]:
                sv_values = np.array([float(r.get('sv', 0.0)) for r in data_list], dtype=float)

            # ========== 子图1：拟合模式 ==========
            ax1.plot(t, y_actual, 'b-', linewidth=2, label='PV (实际值)', alpha=0.8)
            ax1.plot(t, y_predicted, 'r--', linewidth=2, label='PV (模型拟合)', alpha=0.8)

            if sv_values is not None:
                ax1.plot(t, sv_values, 'g--', linewidth=1.5, label='SV (目标值)', alpha=0.7)

            ax1.set_ylabel('PV / SV', fontsize=12)
            ax1.set_xlabel('时间 (秒)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.set_title(f'模式1: 拟合模式 - 实际数据 vs 模型预测 (R²={r_squared:.4f}, RMSE={rmse:.4f})',
                         fontsize=12, fontweight='bold')
            ax1.legend(loc='best', fontsize=10)

            # ========== 子图2：闭环仿真 ==========
            if pv_closed_loop is not None and len(pv_closed_loop) > 0:
                ax2.plot(t, pv_closed_loop, 'purple', linewidth=2, label='PV (闭环仿真)', alpha=0.8)

                if mv_closed_loop is not None and len(mv_closed_loop) > 0:
                    ax2.plot(t, mv_closed_loop, 'orange', linewidth=1.5,
                            label='MV (闭环控制)', alpha=0.7, linestyle='--')

                if data_list and sv_values is not None:
                    ax2.plot(t, sv_values, 'g--', linewidth=1.5, label='SV (目标值)', alpha=0.7)

                ax2.set_ylabel('PV / SV / MV', fontsize=12)
                ax2.set_xlabel('时间 (秒)', fontsize=12)
                ax2.set_title('模式2: 闭环仿真 - 使用推荐PID参数的控制效果',
                             fontsize=12, fontweight='bold')
                ax2.legend(loc='best', fontsize=10)
            else:
                ax2.text(0.5, 0.5, '闭环仿真数据不可用',
                        ha='center', va='center', fontsize=14, transform=ax2.transAxes, color='gray')
                ax2.set_title('模式2: 闭环仿真', fontsize=12, fontweight='bold')
            ax2.grid(True, alpha=0.3)

            # ========== 子图3：阶跃响应 ==========
            if pv_step_response is not None and t_step is not None and len(pv_step_response) > 0:
                ax3.plot(t_step, pv_step_response, 'teal', linewidth=2,
                        label='PV (阶跃响应)', alpha=0.8)

                if mv_step_response is not None and len(mv_step_response) > 0:
                    ax3.plot(t_step, mv_step_response, 'brown', linewidth=1.5,
                            label='MV (阶跃输入)', alpha=0.7, linestyle='--')

                ax3.set_ylabel('PV / MV', fontsize=12)
                ax3.set_xlabel('时间 (秒)', fontsize=12)

                # 在标题中显示PID参数
                pid_info = ''
                if Kp is not None and Ti is not None and Td is not None:
                    pid_info = f' (PID: Kp={Kp:.3f}, Ti={Ti:.2f}, Td={Td:.2f})'

                ax3.set_title(f'模式3: 阶跃响应 - 系统开环阶跃响应特性{pid_info}',
                             fontsize=12, fontweight='bold')
                ax3.legend(loc='best', fontsize=10)
            else:
                ax3.text(0.5, 0.5, '阶跃响应数据不可用',
                        ha='center', va='center', fontsize=14, transform=ax3.transAxes, color='gray')
                ax3.set_title('模式3: 阶跃响应', fontsize=12, fontweight='bold')
            ax3.grid(True, alpha=0.3)

            # 总标题：包含模型参数和拟合指标
            title = f'模型辨识结果 ({model_type})\n'

            # 根据模型类型显示不同的参数
            mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

            if mt_str == 'FO_INTEGRATOR':
                K = model_params.get('K', 0)
                T = model_params.get('T1', 0)
                title += f'K={K:.3f}, T={T:.2f}s | '
            elif mt_str == 'SO_INTEGRATOR':
                K = model_params.get('K', 0)
                T1 = model_params.get('T1', 0)
                T2 = model_params.get('T2', 0)
                title += f'K={K:.3f}, T1={T1:.2f}s, T2={T2:.2f}s | '
            elif mt_str == 'SOPDT':
                K = model_params.get('K', 0)
                T1 = model_params.get('T1', 0)
                T2 = model_params.get('T2', 0)
                L = model_params.get('L', 0)
                title += f'K={K:.3f}, T1={T1:.2f}s, T2={T2:.2f}s, L={L:.2f}s | '
            elif mt_str == 'SO':
                K = model_params.get('K', 0)
                T1 = model_params.get('T1', 0)
                T2 = model_params.get('T2', 0)
                title += f'K={K:.3f}, T1={T1:.2f}s, T2={T2:.2f}s | '
            else:  # FOPDT or FO
                K = model_params.get('K', 0)
                T = model_params.get('T1', 0)
                L = model_params.get('L', 0)
                title += f'K={K:.3f}, T={T:.2f}s, L={L:.2f}s | '

            title += f'R^2={r_squared:.4f}, RMSE={rmse:.4f}'
            fig.suptitle(title, fontsize=14, fontweight='bold', y=0.995)

            plt.tight_layout()

            # 保存图片
            os.makedirs('data/plots', exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            plot_filename = f'{model_type}_model_comparison_{timestamp}.png'
            plot_path = os.path.join('data/plots', plot_filename)
            plt.savefig(plot_path, dpi=150, bbox_inches='tight')
            plt.close(fig)

            print(f"模型对比图已保存: {plot_path}")
            return plot_path

        except Exception as e:
            print(f"绘图失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def generate_valve_process_simulation(self, data_list: List[Dict],model_type: ModelType = ModelType.FOPDT, simulation_type: str = "open_loop",
                                         duration: float = 600.0, dt: float = 1.0) -> Optional[Dict]:
        """
        启动阀门过程模型仿真，封装参数辨识、仿真、绘图流程

        Args:
            data_list: 历史数据列表
            simulation_type: 仿真类型，"open_loop"（开环阶跃响应）或 "closed_loop"（PID闭环响应）
            duration: 仿真时长(秒)
            dt: 采样间隔(秒)

        Returns:
            包含仿真数据、模型参数、PID参数、图片路径的字典
        """
        try:
            # 1. 提取历史数据
            n = len(data_list)
            if n < 20:
                print("数据量不足，无法进行模型辨识")
                return None

            # 时间序列
            if 'timestamp' in data_list[0]:
                ts0 = float(data_list[0]['timestamp'])
                t_hist = np.array([(float(r['timestamp']) - ts0) / 1000.0 for r in data_list], dtype=float)
            else:
                t_hist = np.arange(n, dtype=float)

            # 输出 y (PV)
            y_hist = np.array([float(r.get('pv', r.get('temperature', 0.0))) for r in data_list], dtype=float)

            # 输入 u (MV)
            if 'mv' not in data_list[0]:
                print("数据缺少mv字段，无法进行仿真")
                return None
            u_hist = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)

            # 2. 参数辨识
            print(f"⚙️ 开始辨识过程模型参数...")
            # 使用统一的identify接口
            K, T1,T2, L = SystemIdentifier.identify(t_hist, y_hist, u_hist, model_type='fopdt', transient_mode=False)
            print(f"辨识结果: K={K:.3f}, T1={T1:.2f}s, T2={T2:.2f}s, L={L:.2f}s")

            # 3. Lambda整定
            lambda_val = max(T1 * 0.4, 0.1)
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(K, T1, L, lambda_val, mode="flow_control")
            Ki = Kp / Ti if Ti > 1e-6 and np.isfinite(Ti) else 0.0
            Kd = Kp * Td
            print(f"Lambda整定: Kp={Kp:.3f}, Ki={Ki:.4f}, Kd={Kd:.4f}")

            # 4. 生成仿真曲线
            y0 = np.mean(y_hist[:30]) if len(y_hist) > 30 else np.mean(y_hist[:min(10, len(y_hist))])

            if simulation_type == "open_loop":
                # 开环仿真：阶跃输入
                print(f"生成开环阶跃响应...")
                step_value = float(np.mean(u_hist[-30:])) if len(u_hist) > 30 else float(np.mean(u_hist))
                sim_data = KTLSimulator.generate_response(
                    model_type=model_type.value,
                    parameters={'K': K, 'T1': T1, 'T2': T2, 'L': L},
                    step_value=step_value,
                    duration=duration,
                    dt=dt,
                    initial_output=float(y0)
                )
                # 保存图片
                plot_path = KTLSimulator.save_plot(
                    data=sim_data,
                    simulation_type="open_loop",
                    output_dir="data/plots"
                )

            else:  # closed_loop
                # 闭环PID仿真
                print(f"生成PID闭环响应...")
                # 提取设定值
                if 'sv' in data_list[0]:
                    setpoint = float(np.median([float(r.get('sv', 0.0)) for r in data_list]))
                elif 'sp' in data_list[0]:
                    setpoint = float(np.median([float(r.get('sp', 0.0)) for r in data_list]))
                else:
                    setpoint = float(np.mean(y_hist[-30:]))  # 默认使用末尾均值
                # 生成闭环PID曲线
                sim_data = KTLSimulator.generate_closed_loop_response(
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
                plot_path = KTLSimulator.save_plot(
                    data=sim_data,
                    simulation_type="closed_loop",
                    output_dir="data/plots"
                )

            print(f"仿真完成，图片已保存: {plot_path}")

            # 5. 返回结果
            return {
                "simulation_type": simulation_type,
                "model_parameters": {
                    "K": float(K),
                    "T": float(T1),
                    "L": float(L)
                },
                "pid_parameters": {
                    "Kp": float(Kp),
                    "Ki": float(Ki),
                    "Kd": float(Kd),
                    "Ti": float(Ti),
                    "Td": float(Td),
                    "lambda": float(lambda_val)
                },
                "simulation_data": sim_data,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path,
                "note": f"基于{model_type.value}模型的{simulation_type}仿真结果"
            }

        except Exception as e:
            print(f"阀门过程模型仿真失败: {e}")
            import traceback
            traceback.print_exc()
            return None


def detect_and_visualize(data_list: List[Dict], output_path=None, tol=0.5, std_tol=0.2)-> Optional[Dict]:
    """
    检测非稳态段并可视化

    Args:
        json_file_path: JSON文件路径
        output_path: 输出图片路径（如果为None，自动生成）
        tol: 容差
        std_tol: 标准差阈值

    Returns:
        dict: 包含检测结果的字典
            - non_steady_segments: 非稳态段列表（包含原始时间戳）
            - disturbance_starts: 扰动起始点列表（包含原始时间戳）
            - disturbance_ends: 扰动结束点列表（包含原始时间戳）
    """
    # 1. 提取历史数据
    t, t_original, pv, mv, sv = load_json(data_list)

    # 创建检测器
    detector = StabilityDetector(tol=tol, std_tol=std_tol, min_len=10)

    # 检测非稳态段
    print(f"\n🔍 检测非稳态段...")
    non_steady_segments = detector.detect_non_steady_segments(pv, sv, min_segment_len=20)
    print(f" 检测到 {len(non_steady_segments)} 个非稳态段")

    # 检测扰动起始点
    print(f"\n🔍 检测扰动起始点...")
    disturbance_starts = detector.detect_all_disturbances(pv, sv, non_steady_segments=non_steady_segments)
    print(f" 检测到 {len(disturbance_starts)} 个扰动起始点")

    # 提取扰动结束点（从非稳态段中提取）
    disturbance_ends = []
    for start_idx, end_idx, setpoint in non_steady_segments:
        # 结束点就是非稳态段的结束索引
        if end_idx < len(t_original):
            end_timestamp = t_original[end_idx]
        else:
            end_timestamp = t_original[-1]
        disturbance_ends.append((end_idx, end_timestamp, setpoint))

    # 将起始点和结束点转换为原始时间戳
    starts_with_timestamp = []
    for start_idx, setpoint in disturbance_starts:
        if start_idx < len(t_original):
            start_timestamp = t_original[start_idx]
        else:
            start_timestamp = t_original[0]
        starts_with_timestamp.append((start_idx, start_timestamp, setpoint))

    # 将非稳态段转换为原始时间戳
    segments_with_timestamp = []
    for start_idx, end_idx, setpoint in non_steady_segments:
        start_timestamp = t_original[start_idx] if start_idx < len(t_original) else t_original[0]
        end_timestamp = t_original[end_idx] if end_idx < len(t_original) else t_original[-1]
        segments_with_timestamp.append((start_idx, end_idx, start_timestamp, end_timestamp, setpoint))

    # 打印结果（使用原始时间戳）
    print(f"\n 检测结果（原始时间戳）:")
    for idx, (start_idx, end_idx, start_ts, end_ts, setpoint) in enumerate(segments_with_timestamp, 1):
        print(f"   非稳态段 {idx}:")
        print(f"     索引: [{start_idx}, {end_idx}]")
        print(f"     时间戳: [{start_ts:.0f}, {end_ts:.0f}]")
        print(f"     相对时间: [{t[start_idx]:.1f}s, {t[min(end_idx, len(t) - 1)]:.1f}s]")
        print(f"     设定值: {setpoint:.2f}")

    for idx, (start_idx, start_ts, setpoint) in enumerate(starts_with_timestamp, 1):
        print(f"   扰动起始点 {idx}:")
        print(f"     索引: {start_idx}")
        print(f"     时间戳: {start_ts:.0f}")
        print(f"     相对时间: {t[start_idx]:.1f}s")
        print(f"     设定值: {setpoint:.2f}")

    for idx, (end_idx, end_ts, setpoint) in enumerate(disturbance_ends, 1):
        print(f"   扰动结束点 {idx}:")
        print(f"     索引: {end_idx}")
        print(f"     时间戳: {end_ts:.0f}")
        print(f"     相对时间: {t[min(end_idx, len(t) - 1)]:.1f}s")
        print(f"     设定值: {setpoint:.2f}")

    # 可视化（使用相对时间）
    print(f"\n 生成可视化...")
    plt.rcParams["font.family"] = ["Heiti TC"]
    plt.rcParams['font.sans-serif'] = ["Heiti TC", "Arial Unicode MS", "SimHei", "DejaVu Sans"]
    plt.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    fig.suptitle('稳定性检测结果', fontsize=16, fontweight='bold')

    # PV和SV
    ax1 = axes[0]
    ax1.plot(t, pv, 'b-', linewidth=2, label='过程值PV', alpha=0.7)
    ax1.plot(t, sv, 'r--', linewidth=2.5, label='设定值SV', alpha=0.9)

    # 标注非稳态段
    for idx, (start_idx, end_idx, _, _, _) in enumerate(segments_with_timestamp):
        start_time = t[start_idx]
        end_time = t[min(end_idx, len(t) - 1)]
        ax1.axvspan(start_time, end_time, alpha=0.2, color='red',
                    label='非稳态段' if idx == 0 else None, zorder=0)
        ax1.text((start_time + end_time) / 2, ax1.get_ylim()[1] * 0.95,
                 f'段{idx + 1}\n{start_time:.1f}s-{end_time:.1f}s',
                 ha='center', va='top', fontsize=9,
                 bbox=dict(boxstyle='round', facecolor='yellow', alpha=0.7))

    # 标注扰动起始点
    for idx, (start_idx, _, _) in enumerate(starts_with_timestamp):
        if start_idx < len(t):
            start_time = t[start_idx]
            ax1.axvline(start_time, color='orange', linestyle='--', linewidth=2, alpha=0.8)
            ax1.text(start_time, ax1.get_ylim()[1] * 0.85,
                     f'起始{idx + 1}\n{start_time:.1f}s',
                     ha='center', va='top', fontsize=9,
                     bbox=dict(boxstyle='round', facecolor='orange', alpha=0.7))

    # 标注扰动结束点
    for idx, (end_idx, _, _) in enumerate(disturbance_ends):
        if end_idx < len(t):
            end_time = t[end_idx]
            ax1.axvline(end_time, color='green', linestyle='--', linewidth=2, alpha=0.8)
            ax1.text(end_time, ax1.get_ylim()[1] * 0.75,
                     f'结束{idx + 1}\n{end_time:.1f}s',
                     ha='center', va='top', fontsize=9,
                     bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.7))

    ax1.set_xlabel('时间 (s)', fontsize=12)
    ax1.set_ylabel('过程值 (PV)', fontsize=12)
    ax1.set_title('过程值对比：PV vs SV', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='best', fontsize=10)

    # MV
    ax2 = axes[1]
    if mv is not None:
        ax2.plot(t, mv, 'g-', linewidth=2, label='控制输出MV', alpha=0.7)
        # 标注非稳态段和起始点、结束点
        for start_idx, end_idx, _, _, _ in segments_with_timestamp:
            ax2.axvspan(t[start_idx], t[min(end_idx, len(t) - 1)],
                        alpha=0.2, color='red', zorder=0)
        for start_idx, _, _ in starts_with_timestamp:
            if start_idx < len(t):
                ax2.axvline(t[start_idx], color='orange', linestyle='--', linewidth=2, alpha=0.8)
        for end_idx, _, _ in disturbance_ends:
            if end_idx < len(t):
                ax2.axvline(t[end_idx], color='green', linestyle='--', linewidth=2, alpha=0.8)
        ax2.legend(loc='best', fontsize=10)
    else:
        ax2.text(0.5, 0.5, '无MV数据', ha='center', va='center',
                 transform=ax2.transAxes, fontsize=14)

    ax2.set_xlabel('时间 (s)', fontsize=12)
    ax2.set_ylabel('控制输出 (MV)', fontsize=12)
    ax2.set_title('控制输出', fontsize=13, fontweight='bold')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    if output_path is None:
        base_name =datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = os.path.join('data/plots')
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"stability_detection_{base_name}.png")

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f" 图片已保存: {output_path}")

    # 将所有numpy类型转换为Python原生类型以便JSON序列化
    serializable_segments = []
    for start_idx, end_idx, start_ts, end_ts, setpoint in segments_with_timestamp:
        serializable_segments.append((
            int(start_idx),
            int(end_idx),
            float(start_ts),
            float(end_ts),
            float(setpoint)
        ))
    
    serializable_starts = []
    for start_idx, start_ts, setpoint in starts_with_timestamp:
        serializable_starts.append((
            int(start_idx),
            float(start_ts),
            float(setpoint)
        ))
    
    serializable_ends = []
    for end_idx, end_ts, setpoint in disturbance_ends:
        serializable_ends.append((
            int(end_idx),
            float(end_ts),
            float(setpoint)
        ))
    
    return {
        'non_steady_segments': serializable_segments,
        # (start_idx, end_idx, start_timestamp, end_timestamp, setpoint)
        'disturbance_starts': serializable_starts,  # (start_idx, start_timestamp, setpoint)
        'disturbance_ends': serializable_ends  # (end_idx, end_timestamp, setpoint)
    }


def load_json(data_list: List[Dict]):
    """
    从JSON文件加载数据

    Returns:
        t: 相对时间数组（秒）
        t_original: 原始时间戳数组（毫秒或秒）
        pv: 过程值数组
        mv: 控制输出数组
        sv: 设定值数组
    """

    # 提取数据
    timestamps, pv_list, mv_list, sv_list = [], [], [], []
    for item in data_list:
        if 'timestamp' in item:
            timestamps.append(item['timestamp'])
        if 'pv' in item:
            pv_list.append(item['pv'])
        if 'mv' in item:
            mv_list.append(item['mv'])
        if 'sv' in item:
            sv_list.append(item['sv'])

    # 确保数据长度一致
    min_len = min(len(timestamps), len(pv_list))
    t_original = np.array(timestamps[:min_len])  # 原始时间戳
    pv = np.array(pv_list[:min_len])
    mv = np.array(mv_list[:min_len]) if mv_list else None
    sv = np.array(sv_list[:min_len]) if sv_list else None

    # 转换时间戳为相对时间（秒）
    t = t_original.copy()
    if t[0] > 1e10:  # 毫秒时间戳
        t = t / 1000.0
    t = t - t[0]  # 相对时间

    # 如果没有SV，使用PV的平均值
    if sv is None:
        sv = np.full_like(pv, np.mean(pv))

    return t, t_original, pv, mv, sv

def get_tools() -> List:
    """创建工具实例

    Returns:
        工具列表
    """
    return [
        TemperatureAnalysisTool(),
        PIDOptimizationTool()
    ]


# 查询时序数据-插值查询
def process_query_tsdb_data_interpolated(db: str,
                                         table_name: str,
                                         required_fields: Dict[str, str],
                                         start_time: int,
                                         end_time: int,
                                         tags: Optional[Dict[str, str]] = None,
                                         window: int = 1,
                                         is_filter: Optional[bool] = True
                                         ) -> List[Dict]:

    begin = time.time()

    field_mapping = required_fields
    fields = list(field_mapping.values())

    response = query_read_interpolated(
        db=db,
        table=table_name,
        fields=fields,
        start_time=start_time,
        end_time=end_time,
        tags=tags,
        window=window,
        continuation_point=None
    )

    if not response or not response.values:
        return []

    values = response.values
    columns = response.columns

    # 数据过滤
    if is_filter:
        values = process_lists_optimized(values)[0]
        if not values:
            return []

    # ---------- 列索引预解析 ----------
    rev_map = {v: k for k, v in field_mapping.items()}
    idx_map = {}

    for i, col in enumerate(columns):
        if col == "time":
            idx_map["timestamp"] = i
        elif col in rev_map:
            idx_map[rev_map[col]] = i

    ts_idx = idx_map.get("timestamp")
    pv_idx = idx_map.get("pv")
    mv_idx = idx_map.get("mv")
    sv_idx = idx_map.get("sv")
    pb_idx = idx_map.get("pb")
    ti_idx = idx_map.get("ti")
    td_idx = idx_map.get("td")

    n = len(values)

    # ---------- PID 向量化 ----------
    has_pid = pb_idx is not None and ti_idx is not None and td_idx is not None

    if has_pid:
        import numpy as np

        pb = np.asarray([row[pb_idx] for row in values], dtype=np.float64)
        ti = np.asarray([row[ti_idx] for row in values], dtype=np.float64)
        td = np.asarray([row[td_idx] for row in values], dtype=np.float64)
        
        # 处理NaN值，将其替换为0以避免计算错误
        pb = np.nan_to_num(pb, nan=0.0, posinf=0.0, neginf=0.0)
        ti = np.nan_to_num(ti, nan=0.0, posinf=0.0, neginf=0.0)
        td = np.nan_to_num(td, nan=0.0, posinf=0.0, neginf=0.0)
        
        # 安全计算PID参数，避免除零和无效值
        kp = np.where((pb != 0) & np.isfinite(pb), 100.0 / pb, 0.0)
        ki = np.where((ti != 0) & np.isfinite(ti) & np.isfinite(kp), kp / ti, 0.0)
        kd = np.where((td != 0) & np.isfinite(td) & np.isfinite(kp), kp / td, 0.0)

    # ---------- 构建最终结果 ----------
    result = []
    append = result.append

    for i in range(n):
        row = values[i]
        record = {
            "timestamp": row[ts_idx] if ts_idx is not None else None,
            "pv": row[pv_idx] if pv_idx is not None else None,
            "mv": row[mv_idx] if mv_idx is not None else None,
            "sv": row[sv_idx] if sv_idx is not None else None,
        }

        if has_pid:
            record["kp"] = float(kp[i])
            record["ki"] = float(ki[i])
            record["kd"] = float(kd[i])

        append(record)

    logger.info(
        f"插值查询完成，数据量={len(result)}，耗时={time.time() - begin:.3f}s"
    )
    return result



# 固定 pid值与目标温度，实时数据查询方法
def process_query_tsdb_data_raw(db: str,
                                table_name: str,
                                required_fields: Dict[str, str],
                                start_time: int,
                                end_time: int,
                                tags: Optional[Dict[str, str]] = None) -> List[Dict]:
    """
    查询时序数据原始数据
    
    Args:
        required_fields: 字段映射map，例如:
            {"mv": "ns=100;s=FIC101A_MV.In_Channel0", "pv": "ns=100;s=FIC101A_PV.In_Channel0", ...}
    """
    # 使用传入的字段映射
    field_mapping = required_fields
    query_field_list = list(field_mapping.values())
    
    # 定义仅查询必要的字段（不包括PID参数）
    pid_fields = [field_mapping.get(key) for key in ['mv', 'pv', 'sv', 'pb', 'ti', 'td','auto'] if field_mapping.get(key)]
    query_fields = [field for field in query_field_list if field not in pid_fields]
    
    begin_time = datetime.now().timestamp()

    # 调用时序数据查询接口
    response = query_raw_data(
        db=db,
        table=table_name,
        fields=query_field_list,
        start_time=start_time,
        end_time=end_time,
        tags=tags
    )

    # 解析查询结果
    history_data = []

    # 如果查询有结果，处理数据
    if hasattr(response, 'values') and response.values:
        columns = response.columns or []
        values = response.values

        # 将数据转换为字典格式
        for value_row in values:
            record = {}
            for i, column in enumerate(columns):
                if i < len(value_row):
                    if column == "time":
                        record["timestamp"] = value_row[i]
                    # 使用field_mapping进行动态匹配
                    elif column == field_mapping.get("mv"):
                        record["mv"] = value_row[i]
                    elif column == field_mapping.get("pv"):
                        record["pv"] = value_row[i]
                    elif column == field_mapping.get("sv"):
                        record["sv"] = value_row[i]
                    elif column == field_mapping.get("pb"):
                        record["pb"] = value_row[i]
                    elif column == field_mapping.get("ti"):
                        record["ti"] = value_row[i]
                    elif column == field_mapping.get("td"):
                        record["td"] = value_row[i]
                    elif column == field_mapping.get("auto"):
                        record["auto"] = value_row[i]
                    else:
                        record[column] = value_row[i]

            # 确保包含查询字段的默认值
            for field in query_fields:
                if field not in record:
                    record[field] = None

            history_data.append(record)
    
    over_time = datetime.now().timestamp()
    logger.info(f"总耗时: {over_time - begin_time:.2f}秒")
    return history_data


def _plot_history_data(history_data: List[Dict], table_name: str,
                       start_time: Union[int, str], end_time: Union[int, str]) -> Optional[str]:
    """
    绘制历史数据曲线并保存为图片

    Args:
        history_data: 历史数据列表，包含timestamp, pv, mv, sv等字段
        table_name: 设备表名
        start_time: 开始时间
        end_time: 结束时间

    Returns:
        保存的图片路径，如果失败则返回None
    """
    try:
        import matplotlib
        matplotlib.use('Agg')  # 非交互式后端
        import matplotlib.pyplot as plt

        # 配置中文字体
        plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        # 提取数据
        timestamps = []
        pv_values = []
        mv_values = []
        sv_values = []

        for record in history_data:
            if 'timestamp' in record:
                # 将毫秒时间戳转换为相对秒数
                timestamps.append(record['timestamp'])
                pv_values.append(record.get('pv', 0.0))
                mv_values.append(record.get('mv', 0.0))
                sv_values.append(record.get('sv', 0.0))

        if len(timestamps) == 0:
            print("无有效数据点，跳过绘图")
            return None

        # 转换时间为相对秒数
        t0 = timestamps[0]
        t_relative = [(t - t0) / 1000.0 for t in timestamps]

        # 创建3个子图网格（垂直排列）
        fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

        # 子图1: PV (过程变量)
        ax1.plot(t_relative, pv_values, 'b-', linewidth=2, label='PV (实际值)', alpha=0.8)
        ax1.set_ylabel('PV (过程变量)', fontsize=12, color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='upper right', fontsize=10)
        ax1.set_title('过程变量 (PV)', fontsize=11, fontweight='bold')

        # 子图2: SV (设定值)
        ax2.plot(t_relative, sv_values, 'g-', linewidth=2, label='SV (设定值)', alpha=0.8)
        ax2.set_ylabel('SV (设定值)', fontsize=12, color='green')
        ax2.tick_params(axis='y', labelcolor='green')
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc='upper right', fontsize=10)
        ax2.set_title('设定值 (SV)', fontsize=11, fontweight='bold')

        # 子图3: MV (操纵量)
        ax3.plot(t_relative, mv_values, 'r-', linewidth=2, label='MV (阀门开度)', alpha=0.8)
        ax3.set_xlabel('时间 (秒)', fontsize=12)
        ax3.set_ylabel('MV (操纵量)', fontsize=12, color='red')
        ax3.tick_params(axis='y', labelcolor='red')
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc='upper right', fontsize=10)
        ax3.set_title('操纵量 (MV)', fontsize=11, fontweight='bold')

        # 总标题
        fig.suptitle(f'设备历史数据曲线\n设备: {table_name} | 时间: {start_time} ~ {end_time}',
                     fontsize=14, fontweight='bold', y=0.995)

        plt.tight_layout()

        # 保存图片
        plot_dir = os.path.join(os.getcwd(), "data", "plots")
        os.makedirs(plot_dir, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        plot_filename = f"history_data_{timestamp_str}.png"
        plot_path = os.path.join(plot_dir, plot_filename)

        plt.savefig(plot_path, dpi=150, bbox_inches='tight')
        plt.close()

        return plot_path

    except Exception as e:
        print(f"绘图失败: {e}")
        import traceback
        traceback.print_exc()
        return None


# 便捷函数，用于其他模块调用
def query_historical_data(
        table: str,
        fields: Optional[List[str]] = None,
        start_time: Optional[Union[int, str]] = None,
        end_time: Optional[Union[int, str]] = None,
        limit: int = 1500
) -> Dict:
    """
    查询历史数据的便捷函数 - 支持多种时间格式

    Args:
        table: 表名
        fields: 字段列表
        start_time: 开始时间，支持毫秒时间戳或字符串格式
        end_time: 结束时间，支持毫秒时间戳或字符串格式
        limit: 限制条数

    Returns:
        Dict: 查询结果

    Examples:
        >>> # 使用毫秒时间戳
        >>> query_historical_data("temperature", start_time=1640995200000, end_time=1641081600000)

        >>> # 使用字符串格式
        >>> query_historical_data("temperature", start_time="2022-01-01 12:00:00", end_time="2022-01-02 12:00:00")

        >>> # 使用ISO格式
        >>> query_historical_data("temperature", start_time="2022-01-01T12:00:00", end_time="2022-01-02T12:00:00")
    """
    # 转换时间格式
    start_ms = None
    end_ms = None

    if start_time is not None:
        try:
            start_ms = parse_time_to_milliseconds(start_time)
        except ValueError as e:
            raise ValueError(f"开始时间格式错误: {str(e)}")

    if end_time is not None:
        try:
            end_ms = parse_time_to_milliseconds(end_time)
        except ValueError as e:
            raise ValueError(f"结束时间格式错误: {str(e)}")

    request_data = {
        "tables": [
            {
                "table": table,
                "fields": fields,
                "continuationPoint": None
            }
        ],
        "detail": {
            "startTime": start_ms,
            "endTime": end_ms or int(datetime.now().timestamp() * 1000),
            "limit": limit,
            "returnBounds": False
        }
    }

    return query_raw_data(request_data)


def query_table_and_points(
    project_path: Optional[str] = None,
    point_path: Optional[str] = None
) -> Dict[str, Any]:
    """
    查询表名和测点映射的便捷函数
    
    Args:
        project_path: 项目路径前缀，默认从环境变量读取
        point_path: 测点路径，默认从环境变量读取
        
    Returns:
        Dict: 包含table名称和测点映射的字典
            {
                "status": "success",
                "table_name": "PID_FEP_Gateway_Device_001default",
                "points": {
                    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
                    "pv": "ns=100;s=FIC101A_PV.In_Channel0",
                    "sv": "ns=100;s=FIC101A_SV.In_Channel0",
                    "pb": "ns=100;s=FIC101A_PB.In_Channel0",
                    "ti": "ns=100;s=FIC101A_TI.In_Channel0",
                    "td": "ns=100;s=FIC101A_TD.In_Channel0"
                },
                "total_points": 6
            }
    """
    try:
        with BFFModelClient(loop_uri=project_path, point_path=point_path) as client:
            # 查询常用字段
            query_result = client.query_common_fields()
            
            # 提取原始响应
            raw_response = query_result.get('raw_response', {})
            # 提取查询路径
            browse_paths = query_result.get('browse_paths', [])
            
            # 处理raw_response为None的情况
            if raw_response is None:
                raw_response = {}
            
            # 提取result字段
            result_paths = raw_response.get('result', []) if isinstance(raw_response, dict) else []
            if result_paths is None or not result_paths:
                logger.warning("响应中未找到result字段或为空")
                return {
                    "status": "warning",
                    "message": "查询成功但未解析到测点路径",
                    "table_name": None,
                    "points": {},
                    "total_points": 0
                }
            
            # 提取table名称和测点列表，传入query_paths和result_paths
            table_and_points = BFFModelClient.extract_table_and_points_from_paths(browse_paths, result_paths)
            
            table_name = table_and_points.get('table_name')
            points = table_and_points.get('points', {})
            
            return {
                "status": "success" if table_name else "warning",
                "message": "查询成功" if table_name else "查询成功但未解析到table名称",
                "project_path": client.deafult_device_uri,
                "point_path": client.deafult_point_path,
                "table_name": table_name,
                "points": points,
                "total_points": len(points) if isinstance(points, dict) else 0
            }
    
    except Exception as e:
        logger.error(f"查询表名和测点列表失败: {str(e)}")
        return {
            "status": "error",
            "message": f"查询失败: {str(e)}",
            "table_name": None,
            "points": {},
            "total_points": 0
        }