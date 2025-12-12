#!/usr/bin/env python3
"""
回路性能评估业务逻辑层 - Service层
将路由层的性能评估业务逻辑封装到这里
"""

import logging
from typing import Dict, Any, List, Union
import json
from datetime import datetime

from core.agent.tools import TemperatureAnalysisTool, PIDOptimizationTool
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from api.commond.time_util import parse_time_to_milliseconds
from core.agent.tools import process_query_tsdb_data_interpolated
from core.utils.model_type import ModelType

logger = logging.getLogger(__name__)


class AnalysisService:
    """回路性能评估业务服务"""
    
    @staticmethod
    def analyze_temperature_curve(
        start_time: Union[int, str, None],
        end_time: Union[int, str, None],
        loop_uri: str
    ) -> Dict[str, Any]:
        """
        温度曲线智能分析
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
            loop_uri: 回路URI
            
        Returns:
            Dict: 分析结果
        """
        try:
            # 默认查询2小时
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)

            if start_time is None:
                end_time_ms = parse_time_to_milliseconds(end_time)
                start_time = end_time_ms - 2 * 60 * 60 * 1000  # 默认2小时
            else:
                start_time = parse_time_to_milliseconds(start_time)
                end_time = parse_time_to_milliseconds(end_time)

            # 根据loop_uri查询表名和测点列表
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
            
            # 使用环境变量中的数据库名
            db = get_default_database()

            # 使用新的查询方法
            history_data = process_query_tsdb_data_interpolated(
                db=db,
                table_name=table,
                required_fields=required_fields,
                start_time=start_time,
                end_time=end_time
            )
            
            if not history_data:
                return {
                    "table": table,
                    "message": "指定时间范围内无数据"
                }

            # 创建温度分析工具实例
            analysis_tool = TemperatureAnalysisTool()

            # 执行分析（传入历史数据列表）
            analysis_result = analysis_tool._run(json.dumps(history_data))

            # 解析分析结果
            try:
                result_data = json.loads(analysis_result)
                return {
                    "table": table,
                    "start_time": start_time,
                    "end_time": end_time,
                    "analysis_result": result_data
                }
            except json.JSONDecodeError:
                # 如果返回的不是JSON格式（可能是错误信息）
                raise Exception('json解析异常')

        except Exception as e:
            logger.error(f"曲线分析失败: {str(e)}")
            raise Exception(f"曲线分析失败: {str(e)}")
    
    @staticmethod
    def optimize_pid_parameters(
        start_time: Union[int, str, None],
        end_time: Union[int, str, None],
        loop_uri: str,
        is_filter: bool = True,
        is_lambda: bool = False,
        model_type: ModelType = ModelType.FOPDT
    ) -> Dict[str, Any]:
        """
        PID参数智能优化分析
        
        Args:
            start_time: 开始时间
            end_time: 结束时间
            loop_uri: 回路URI
            is_filter: 是否过滤数据
            is_lambda: 是否增加lambda整定建议
            model_type: 模型类型
            
        Returns:
            Dict: 优化结果
        """
        try:
            # 默认查询2小时
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)

            if start_time is None:
                end_time_ms = parse_time_to_milliseconds(end_time)
                start_time = end_time_ms - 2 * 60 * 60 * 1000  # 默认2小时
            else:
                start_time = parse_time_to_milliseconds(start_time)
                end_time = parse_time_to_milliseconds(end_time)

            # 根据loop_uri查询表名和测点列表
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)
            
            # 使用环境变量中的数据库名
            db = get_default_database()

            # 使用新的查询方法
            history_data: List[Dict] = process_query_tsdb_data_interpolated(
                db=db,
                table_name=table,
                required_fields=required_fields,
                start_time=start_time,
                end_time=end_time,
                is_filter=is_filter
            )
            
            if not history_data:
                return {
                    "table": table,
                    "message": "指定时间范围内无数据"
                }

            # 创建PID优化工具实例
            optimization_tool = PIDOptimizationTool()

            # 执行优化分析（传入历史数据列表）
            optimization_result = optimization_tool._run(
                history_data=history_data,
                is_lambda=is_lambda,
                model_type=model_type
            )

            # 解析优化结果
            try:
                result_data = json.loads(optimization_result)
                return {
                    "table": table,
                    "start_time": start_time,
                    "end_time": end_time,
                    "optimization_result": result_data
                }
            except json.JSONDecodeError:
                # 如果返回的不是JSON格式（可能是错误信息）
                return {
                    "table": table,
                    "message": optimization_result
                }

        except Exception as e:
            logger.error(f"PID优化失败: {str(e)}")
            raise Exception(f"PID优化失败: {str(e)}")
    
    @staticmethod
    def get_model_recommendations(model_type: str) -> Dict[str, str]:
        """
        获取不同模型类型的应用建议
        
        Args:
            model_type: 模型类型
            
        Returns:
            Dict: 模型推荐信息
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