from typing import Optional, Dict, List
import json  # 移到全局导入
import traceback  # 添加traceback导入
import sys
import os

import numpy as np

from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier

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
            - `avg_value`: 平均温度
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
    优化PID参数的工具。基于温度曲线分析结果，给出具体的PID参数调整建议。
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
    
    def _run(self, history_data: str,is_lambda: bool) -> str:
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
                    lambda_suggestions = self._compute_lambda_suggestions(data_list)
                    if lambda_suggestions is not None:
                        tuning_suggestions["lambda_suggested_params"] = lambda_suggestions
                except Exception as e:
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
        
        # 建议的参数调整值
        # suggested_params = current_params.copy()
        
        # if abs(steady_error) > 1.0:#稳态误差>1
        #     if steady_error > 0:
        #         suggested_params["kp"] = min(current_params["kp"] * 1.1, 10.0)
        #         suggested_params["ki"] = min(current_params["ki"] * 1.05, 1.0)
        #     else:
        #         suggested_params["kp"] = max(current_params["kp"] * 0.9, 0.1)
        #         suggested_params["ki"] = max(current_params["ki"] * 0.95, 0.01)
        #
        # if stability == "unstable": #不稳定
        #     suggested_params["kp"] = max(suggested_params["kp"] * 0.8, 0.1)
        #     suggested_params["kd"] = min(suggested_params["kd"] * 1.2, 1.0)

        return {
            "recommendations": suggestions, #调参建议
            # "suggested_params": suggested_params, #建议值
            "priority": "high" if (abs(steady_error) > 2.0 or stability == "unstable") else "medium" #优先级
        }

    # lambda整定建议 by liu hanbin
    def _compute_lambda_suggestions(self, data_list: List[Dict]) -> Optional[Dict]:
        """从数据中提取t(秒)、y(pv)、u(mv)，进行FOPDT辨识并返回Lambda整定建议"""
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

            # KTLBatchProcessor.plot_comparison(t=t, y=y, u=u,methods=None)
            #todo 基于历史值推断系统模型类型

            #FOPDT参数辨识与Lambda整定
            K, T= SystemIdentifier.identify_first_order(t,y,u)
            lambda_val = max(T * 0.4, 0.1)
            Kp, Ti, Td = SystemIdentifier.lambda_tuning_for_flow(K, T,0,lambda_val, mode="flow_control")

            # K, T= FlowValveLambdaTuner.identify_first_order(t, y, u)
            # lambda_val = T * 0.3 #
            # Kp, Ti, Td = FlowValveLambdaTuner.lambda_tuning(K, T, mode="standard")
            # Pb=1/Kp
            return {
                "params": {"Kp": float(Kp), "ki": float(Kp / Ti) if Ti > 1e-6 else 0.0, "kd": float(Kp * Td),"Pb": float(1/Kp* 100),"Ti": float(Ti),"Td": float(Td)},
                "pid_form": "Kp-Ti-Td",
                "model": {"K": float(K), "T": float(T), "L": float(0)},
                "lambda": float(lambda_val),
                "note": "基于一阶相应模型辨识与Lambda方法的推荐值"
            }
        except Exception as e:
            print(f"Lambda整定计算失败: {e}")
            return None

def get_tools() -> List:
    """创建工具实例
    
    Returns:
        工具列表
    """
    return [
        TemperatureAnalysisTool(),
        PIDOptimizationTool()
    ]
