from typing import Optional, Dict, List, cast
import json  # 移到全局导入
import traceback  # 添加traceback导入
import sys
import os
from datetime import datetime

import numpy as np
import matplotlib

from core.algorithm.detector import StabilityDetector

matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt

from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier, ModelType, MODEL_CONFIG
from core.algorithm.ktl_simulator import KTLSimulator

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


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
                
            print(f"\nDebug - TemperatureAnalysisTool 分析历史数据:")
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
        mean = sum(data_list) / len(data_list)
        variance = sum((x - mean) ** 2 for x in data_list) / len(data_list)
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
    
    def _run(self, history_data: str,is_lambda: bool, model_type: ModelType = ModelType.INTEGRATOR) -> str:
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
            
            # 提取温度数据进行性能分析
            temp_data = [float(record.get('pv', 25.0)) for record in data_list]
            
            # 计算性能指标
            temp_std = self._calculate_std(temp_data) #标准差
            steady_state_value = sum(temp_data[-5:]) / min(5, len(temp_data)) #稳态值
            steady_error = float(current_params["sv"] - steady_state_value) #稳态误差
            
            # 评估系统性能
            #响应速度
            response_speed = "fast" if len(temp_data) > 0 and temp_data[-1] >= current_params["sv"] * 0.9 else "slow"
            #稳定性
            stability = "stable" if temp_std < 0.5 else "unstable"
            #精度
            accuracy = "good" if abs(steady_error) < 0.5 else "poor"
            
            # 生成PID调优建议
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
                    "data_points": len(temp_data) #测点数量
                },
                "status": {
                    "response_speed": response_speed, #响应速度
                    "stability": stability,#稳定性
                    "accuracy": accuracy #精度
                }
                ,"tuning_suggestions": tuning_suggestions #调参建议
            }
            
            print(f"优化分析结果: {json.dumps(analysis_result, indent=2,ensure_ascii=False)}")
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
            y = np.array([float(r.get('pv', r.get('temperature', 0.0))) for r in data_list], dtype=float)

            # 输入u: 优先使用mv(操纵量/阀门开度)
            u = None
            if 'mv' in data_list[0]:
                u = np.array([float(r.get('mv', 0.0)) for r in data_list], dtype=float)

            if u is None or np.max(np.abs(u)) < 1e-6:
                return None
            
            # 统一处理枚举或字符串类型
            mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

            # 判断是否使用瞬态模式：检查末段是否达到稳态
            # 如果末段MV或PV变化剧烈，使用瞬态模式
            u_tail_std = np.std(u[-30:]) if len(u) > 30 else np.std(u)
            y_tail_std = np.std(y[-30:]) if len(y) > 30 else np.std(y)
            y_mean = np.mean(y)
            # 阈值：末段标准差 > 5% 均值时认为未稳定，使用瞬态模式
            transient_mode = (y_tail_std > 0.05 * abs(y_mean)) or (u_tail_std > 0.05 * np.mean(u))

            if transient_mode:
                print("检测到瞬态数据，使用瞬态模式进行辨识")

            # 系统模型参数辨识（根据model_type返回不同数量的参数）
            K, T1, T2, L = SystemIdentifier.identify(t, y, u, model_type=mt_str, transient_mode=bool(transient_mode))
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
                sopdt_params_options = [
                    {"lambda": float(lambda_val_1), "Kp": float(Kp1), "Ti": float(Ti1), "Td": float(Td1)},
                    {"lambda": float(lambda_val_2), "Kp": float(Kp2), "Ti": float(Ti2), "Td": float(Td2)}
                ]
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
            y0 = np.mean(y[:30]) if len(y) > 30 else np.mean(y[:min(10, len(y))])

            if mt_str == 'FO_INTEGRATOR':
                y_model = SystemIdentifier.first_order_integrator_model([K, T1], t, u, y0)
            elif mt_str == 'SO_INTEGRATOR':
                y_model = SystemIdentifier.second_order_integrator_model([K, T1, T2], t, u, y0)
            elif mt_str == 'SOPDT':
                y_model = SystemIdentifier.second_order_model([K, T1, T2, L], t, u, y0)
            elif mt_str == 'SO':
                y_model = SystemIdentifier.second_order_no_delay_model([K, T1, T2], t, u, y0)
            elif mt_str == 'FO':
                y_model = SystemIdentifier.first_order_model([K, T1], t, u, y0)
            else:  # FOPDT
                y_model = SystemIdentifier.fopdt_model([K, T1, L], t, u, y0)

            # 计算拟合指标
            ss_res = np.sum((y - y_model) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            rmse = np.sqrt(np.mean((y - y_model) ** 2)) #均方根误差

            # 绘制对比图（传入原始数据列表以便在图中显示格式化时间）
            plot_path = self._plot_model_comparison(
                t, u, y, y_model,
                model_params, model_type,
                r_squared, rmse, data_list
            )

            # 构建返回结果（根据model_type适配model字段）
            result = {
                "params": {
                    "Kp": float(Kp),
                    "ki": float(Kp / Ti) if Ti > 1e-6 else 0.0,
                    "kd": float(Kp * Td),
                    "Pb": float(1/Kp* 100),
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
                "params_options": sopdt_params_options,
                "plot_saved": plot_path is not None,
                "plot_path": plot_path,
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

    def _plot_model_comparison(self, t, u, y_actual, y_predicted, model_params, model_type, r_squared, rmse, data_list):
        """绘制模型对比图：实际值与预测值合并在一个网格，MV单独一个网格

        Args:
            t: 时间数组
            u: 输入信号（MV）
            y_actual: 实际输出（PV）
            y_predicted: 模型预测输出
            model_params: 模型参数字典 (e.g., {'K': 1.2, 'T': 30.0} for integrator)
            model_type: 模型类型 ('fopdt', 'first_order', 'second_order', 'integrator')
            r_squared: R²拟合指标
            rmse: RMSE拟合指标
            data_list: 原始数据列表
        """
        try:
            # 配置中文字体
            plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
            plt.rcParams['axes.unicode_minus'] = False

            # 将时间转换为年月日时分秒格式（用于图表X轴显示）
            if data_list and 'timestamp' in data_list[0]:
                ts0 = float(data_list[0]['timestamp'])
                time_labels = [datetime.datetime.fromtimestamp(ts0 / 1000.0 + t_val).strftime('%Y-%m-%d %H:%M:%S')
                              for t_val in t]
            else:
                # 如果没有timestamp，使用相对秒数
                time_labels = [f'{t_val:.1f}s' for t_val in t]

            # 创建2个垂直排列的子图：PV对比 + MV
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

            # 子图1: PV 实际值、预测值、SV 目标值
            ax1.plot(t, y_actual, 'b-', linewidth=2, label='PV (实际值)', alpha=0.8)
            ax1.plot(t, y_predicted, 'r--', linewidth=2, label='PV (模型预测)', alpha=0.8)
            
            # 提取并绘制SV目标值曲线（移动到PV网格）
            if data_list and 'sv' in data_list[0]:
                sv_values = np.array([float(r.get('sv', 0.0)) for r in data_list], dtype=float)
                ax1.plot(t, sv_values, 'g--', linewidth=2, label='SV (目标值)', alpha=0.7)
            
            ax1.set_ylabel('PV / SV', fontsize=12)
            ax1.grid(True, alpha=0.3)
            ax1.set_title('PV 实际值、模型预测值 与 SV 目标值对比', fontsize=11, fontweight='bold')
            ax1.legend(loc='best', fontsize=10)

            # 子图2: MV (操纵量)
            ax2.plot(t, u, 'g-', linewidth=2, label='MV (操纵量)', alpha=0.8)
            ax2.set_xlabel('时间', fontsize=12)
            ax2.set_ylabel('MV', fontsize=12, color='green')
            ax2.tick_params(axis='y', labelcolor='green')
            ax2.grid(True, alpha=0.3)
            ax2.set_title('MV 操纵量', fontsize=11, fontweight='bold')
            ax2.legend(loc='best', fontsize=10)

            # 设置X轴刻度标签（显示格式化的时间）
            n_points = len(t)
            if n_points > 50:
                step = n_points // 10  # 最多显示10个刻度
            else:
                step = max(1, n_points // 5)

            tick_indices = range(0, n_points, step)
            ax2.set_xticks([t[i] for i in tick_indices])
            ax2.set_xticklabels([time_labels[i] for i in tick_indices], rotation=45, ha='right', fontsize=9)

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
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
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

    def generate_valve_process_simulation(self, data_list: List[Dict], simulation_type: str = "open_loop", 
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
            Ki = Kp / Ti if Ti > 1e-6 else 0.0
            Kd = Kp * Td
            print(f"Lambda整定: Kp={Kp:.3f}, Ki={Ki:.4f}, Kd={Kd:.4f}")
            
            # 4. 生成仿真曲线
            y0 = np.mean(y_hist[:30]) if len(y_hist) > 30 else np.mean(y_hist[:min(10, len(y_hist))])
            
            if simulation_type == "open_loop":
                # 开环仿真：阶跃输入
                print(f"生成开环阶跃响应...")
                step_value = float(np.mean(u_hist[-30:])) if len(u_hist) > 30 else float(np.mean(u_hist))
                sim_data = KTLSimulator.generate_fopdt_response(
                    K=K, T=T1, L=L,
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
                
                sim_data = KTLSimulator.generate_pid_response(
                    K=K, T=T1, L=L,
                    Kp=Kp, Ki=Ki, Kd=Kd,
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
                "note": f"基于FOPDT模型的{simulation_type}仿真结果"
            }
            
        except Exception as e:
            print(f"阀门过程模型仿真失败: {e}")
            import traceback
            traceback.print_exc()
            return None


def detect_and_visualize(data_list: List[Dict], output_path=None, tol=0.5, std_tol=0.2):
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
    print(f"📊 检测到 {len(non_steady_segments)} 个非稳态段")

    # 检测扰动起始点
    print(f"\n🔍 检测扰动起始点...")
    disturbance_starts = detector.detect_all_disturbances(pv, sv, non_steady_segments=non_steady_segments)
    print(f"📊 检测到 {len(disturbance_starts)} 个扰动起始点")

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
    print(f"\n📋 检测结果（原始时间戳）:")
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
    print(f"\n🎨 生成可视化...")
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
        base_name = datetime.now().time().strftime("%Y%m%d-%H%M%S")
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"stability_detection_{base_name}.png")

    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close(fig)
    print(f"✅ 图片已保存: {output_path}")

    return {
        'non_steady_segments': segments_with_timestamp,
        # (start_idx, end_idx, start_timestamp, end_timestamp, setpoint)
        'disturbance_starts': starts_with_timestamp,  # (start_idx, start_timestamp, setpoint)
        'disturbance_ends': disturbance_ends  # (end_idx, end_timestamp, setpoint)
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
