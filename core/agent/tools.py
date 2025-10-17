from typing import Optional, Dict, List
import json  # 移到全局导入
import traceback  # 添加traceback导入
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class TemperatureAnalysisTool():
    name: str = "temperature_curve_analysis"
    description: str = """
    分析温度曲线特性的工具。
    分析指标包括：上升时间、超调量、稳态误差、温度波动等。
    输入参数: :param history_data: 必要参数, List[Dict]类型, get_pid_history_data返回的历史数据列表
    输出参数：
            - `current_temp`: 当前温度
            - `target_temp`: 目标温度
            - `max_temp`: 最高温度
            - `min_temp`: 最低温度
            - `avg_temp`: 平均温度
            - `temp_std`: 温度标准差(波动程度)
            - `steady_state`: 稳态温度
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
            required_fields = ['temperature', 'target_temp']
            first_record = data_list[0]
            #todo 过滤掉异常数据
            missing_fields = [field for field in required_fields if field not in first_record]
            if missing_fields:
                return json.dumps({"error": f"数据缺少必要字段: {missing_fields}"})
                
            # 提取温度数据和目标温度
            temp_data = [float(record.get('temperature', 25.0)) for record in data_list]
            target_temp = float(data_list[-1].get('target_temp', 25.0))
            
            print(f"温度数据点数: {len(temp_data)}")
            print(f"温度数据范围: {min(temp_data):.2f} - {max(temp_data):.2f}")
            print(f"目标温度: {target_temp}")
            
            # 计算基本统计指标
            metrics = {
                "current_temp": float(temp_data[-1]),
                "target_temp": float(target_temp),
                "max_temp": float(max(temp_data)),
                "min_temp": float(min(temp_data)),
                "avg_temp": float(sum(temp_data) / len(temp_data)),
                "temp_std": self._calculate_std(temp_data),
                "steady_state": float(sum(temp_data[-5:]) / min(5, len(temp_data))),
                "data_points": int(len(temp_data))
            }
            
            # 计算性能指标
            metrics["steady_error"] = float(metrics["target_temp"] - metrics["steady_state"])
            if metrics["target_temp"] != 0:
                metrics["overshoot"] = float(((metrics["max_temp"] - metrics["target_temp"]) / metrics["target_temp"]) * 100)
            else:
                metrics["overshoot"] = 0.0
            
            # 计算上升时间
            temp_range = metrics["max_temp"] - metrics["min_temp"]
            if temp_range > 0:
                t_90 = metrics["min_temp"] + 0.9 * temp_range
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
                
            print(f"\nDebug - PIDOptimizationTool 分析历史数据:")
            print(f"获取到的数据条数: {len(data_list)}")
            
            if not data_list:
                print("无历史数据")
                return json.dumps({"error": "无历史数据可分析"})
            
            # 检查数据格式，确保包含PID相关字段
            required_fields = ['temperature', 'target_temp', 'kp', 'ki', 'kd']
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
                "target_temp": float(last_record.get('target_temp', 25.0))
            }
            
            # 提取温度数据进行性能分析
            temp_data = [float(record.get('temperature', 25.0)) for record in data_list]
            
            # 计算性能指标
            temp_std = self._calculate_std(temp_data) #标准差
            steady_state_temp = sum(temp_data[-5:]) / min(5, len(temp_data))
            steady_error = float(current_params["target_temp"] - steady_state_temp)
            
            # 评估系统性能
            response_speed = "fast" if len(temp_data) > 0 and temp_data[-1] >= current_params["target_temp"] * 0.9 else "slow"
            stability = "stable" if temp_std < 0.5 else "unstable"
            accuracy = "good" if abs(steady_error) < 0.5 else "poor"
            
            # 生成PID调优建议
            # tuning_suggestions = self._generate_tuning_suggestions(
            #     current_params, steady_error, temp_std, response_speed, stability, accuracy
            # )
            
            # 生成分析结果
            analysis_result = {
                "current_params": current_params,
                "performance": {
                    "steady_error": steady_error, #稳态误差
                    "stability": temp_std, #稳定性
                    "steady_state_temp": steady_state_temp, #稳态温度
                    "data_points": len(temp_data) #测点数量
                },
                "status": {
                    "response_speed": response_speed, #响应速度
                    "stability": stability,#稳定性
                    "accuracy": accuracy #准确度
                }
                # ,"tuning_suggestions": tuning_suggestions #调参建议
            }
            
            print(f"优化分析结果: {json.dumps(analysis_result, indent=2)}")
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
            if steady_error > 0:  # 温度低于目标
                suggestions.append("增加Kp参数或Ki参数以提高温度")
            else:  # 温度高于目标
                suggestions.append("减小Kp参数或Ki参数以降低温度")
        
        # 基于稳定性的建议
        if stability == "unstable":
            suggestions.append("系统振荡，建议减小Kp参数或增加Kd参数")
        
        # 基于响应速度的建议
        if response_speed == "slow":
            suggestions.append("响应过慢，建议适度增加Kp参数")
        
        # 建议的参数调整值
        suggested_params = current_params.copy()
        
        if abs(steady_error) > 1.0:
            if steady_error > 0:
                suggested_params["kp"] = min(current_params["kp"] * 1.1, 10.0)
                suggested_params["ki"] = min(current_params["ki"] * 1.05, 1.0)
            else:
                suggested_params["kp"] = max(current_params["kp"] * 0.9, 0.1)
                suggested_params["ki"] = max(current_params["ki"] * 0.95, 0.01)

        if stability == "unstable":
            suggested_params["kp"] = max(suggested_params["kp"] * 0.8, 0.1)
            suggested_params["kd"] = min(suggested_params["kd"] * 1.2, 1.0)
        
        return {
            "recommendations": suggestions, #调参建议
            "suggested_params": suggested_params, #建议值
            "priority": "high" if (abs(steady_error) > 2.0 or stability == "unstable") else "medium" #优先级
        }

def get_tools() -> List:
    """创建工具实例
    
    Returns:
        工具列表
    """
    return [
        TemperatureAnalysisTool(),
        PIDOptimizationTool()
    ]
