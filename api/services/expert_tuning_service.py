#!/usr/bin/env python3
"""
专家整定业务服务层
封装专家整定相关的业务逻辑
"""

import logging
import json
from typing import Dict, List, Optional, Union, Any
from datetime import datetime

import pandas as pd
import numpy as np

from api.middleware.exceptions import DataProcessException
from api.services.loop_service import LoopService
from core.agent.tools import PIDOptimizationTool, detect_and_visualize, \
    process_query_tsdb_data_interpolated
from core.algorithm import tuning_segment_selector
from core.algorithm.model_type import ModelSelector
from core.utils import PIDConverter
from core.utils.model_type import ModelType
from core.client.bff_model_client import BFFModelClient
from core.client.real_tsdb_client import get_default_database
from core.database.database import get_db_session
from api.commond.time_util import parse_time_to_milliseconds, format_time_to_string
from core.algorithm.ls_pid_autotune_v5 import SystemIdentifier
from api.dao.tuning_record_dao import TuningRecordDAO
from api.dao.loop_info_dao import LoopInfoDAO

logger = logging.getLogger(__name__)


class ExpertTuningService:
    """专家整定业务服务"""

    @staticmethod
    def get_tuning_windows(
            loop_uri: str = None,
            start_time: Union[int, str] = None,
            end_time: Union[int, str] = None,
            window_size: int = 120,
            step_size: int = 10,
            variability_threshold: float = 0.8,
            analyst_column: Optional[str] = "pv",
            window_sec: int = 60,
            is_filter: bool = False
    ) -> Dict[str, Any]:
        """
        自动识别曲线中高波动时段，输出适合经典整定分析的时间窗口列表

        Args:
            loop_uri: 回路URI
            start_time: 开始时间，支持毫秒时间戳或字符串格式
            end_time: 结束时间，支持毫秒时间戳或字符串格式
            window_size: 窗口大小（分钟）
            step_size: 滑动步长（分钟）
            variability_threshold: 波动性阈值分位数(0-1)
            analyst_column: 用于波动判断的列名
            window_sec: 插值采样间隔（分钟）
            is_filter: 是否对历史数据进行优化过滤（按最新参数）

        Returns:
            Dict[str, Any]: 时间窗口列表
        """
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
                raise ValueError("开始时间必须小于结束时间")

            # 固定设备与字段（与现有分析接口保持一致）
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

            # 查询历史插值数据（数据访问层负责分页与解析）
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
            if not history_data:
                return {
                    "table": table,
                    "start_time": start_time,
                    "end_time": end_time,
                    "total_windows": 0,
                    "windows": []
                }

            # 构建DataFrame用于窗口筛选与分组键计算
            df = pd.DataFrame(history_data)
            column = analyst_column or "pv"
            if "timestamp" not in df.columns or column not in df.columns:
                raise ValueError(f"历史数据缺少必要字段: timestamp 或 {column}")

            # 构建分析序列（索引为datetime）
            ts_index = pd.to_datetime(df["timestamp"], unit="ms")
            series = pd.Series(df[column].values, index=ts_index)

            high_windows = tuning_segment_selector.find_high_variability_periods(
                series,
                window_size=window_size,
                step_size=step_size,
                variability_threshold=variability_threshold
            )
            return high_windows


        except Exception as e:
            logger.error(f"时间区间筛选失败: {str(e)}")
            raise

    @staticmethod
    def liu_pid_tuning(
            mode: str = "auto",
            loop_uri: str = None,
            start_time: Union[int, str] = None,
            end_time: Union[int, str] = None,
            tuning_windows: Optional[List[Dict[str, Any]]] = None,
            model_type: ModelType = ModelType.FOPDT,
            turning_type: str = "PID",
            now_param: Optional[Dict[str, Any]] = None,
            lambda_val: Optional[float] = None,
            window_size: int = 120,
            step_size: int = 10,
            confidence_threshold: float = 0.6,
            window_sec: int = 1,
            is_filter: bool = False,
            operator_id: str = None,
            operator_name: str = None
    ) -> Dict[str, Any]:
        try:
            # 参数验证
            # if mode not in ["auto", "manual"]:
            #     mode = 'auto'
            # 时间范围处理
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)
            if start_time is None:
                start_time = end_time - 24 * 60 * 60 * 1000  # 默认1天
            logger.info(f"将在时间范围 {start_time} - {end_time} 内筛选最佳整定区间")

            # 时间格式转换
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)

            if start_time_ms >= end_time_ms:
                raise ValueError("开始时间必须小于结束时间")

            # 固定设备与字段配置
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

            db = get_default_database()

            # 初始化变量

            # 获取整定前设备参数
            before_pid= LoopService.query_loop_values(["PB", "TI", "TD"], loop_uri)
            pid_convert=PIDConverter.classical_to_pid(before_pid.get("PB"), before_pid.get("TI"), before_pid.get("TD"))
            before_pid_params = {
                "kp": f"{pid_convert.get('kp', 0):.2f}",
                "kd": f"{pid_convert.get('kd', 0):.2f}",
                "ki": f"{pid_convert.get('ki', 0):.2f}",
                "pb": f"{before_pid.get('PB', 0):.2f}",
                "ti": f"{before_pid.get('TI', 0):.2f}",
                "td": f"{before_pid.get('TD', 0):.2f}"
            }
            # 根据模式执行不同逻辑
            # 自动筛选模式
            logger.info(f"执行自动整定，时间范围：{start_time} - {end_time}")

            # 获取历史数据
            history_data = process_query_tsdb_data_interpolated(
                    db=db,
                    table_name=table,
                    required_fields=required_fields,
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                    is_filter=is_filter,
                    window=window_sec
            )

            if not history_data or len(history_data) == 0:
                logger.error("指定时间范围内无数据")
                raise DataProcessException("未查询到回路历史数据")
            model_select = ModelSelector()
            request = {
                "history_data": history_data,
                "params": {
                    "model_type": model_type.value if model_type.value else None,  # 可选，强制使用指定模型
                    "turning_type": turning_type if turning_type else None,  # 可选，整定类型
                    "analyst_column": "pv",
                },
                "qualified_windows": tuning_windows
            }

            treaning_start_time=datetime.now().timestamp()
            #调用整定方法
            model_selector = model_select.run(request)

            treaning_end_time=datetime.now().timestamp()
            logger.info(f"模型整定耗时: {treaning_end_time - treaning_start_time}s")
            suggest_pid_params = model_selector.get("pid_parameters")
            tuning_details = {
                "start_time": model_selector.get("start_time"),
                "end_time": model_selector.get("end_time"),
                "model_type": model_type.value,
                "turning_type": turning_type,
                "model_rating": model_selector.get("model_rating"),
                "model_parameters": model_selector.get("model_parameters"),
                "pid_parameters": {
                    "kd": f"{model_selector.get('pid_parameters.kd', 0):.2f}" ,
                    "ki": f"{model_selector.get('pid_parameters.ki', 0):.2f}" ,
                    "kp": f"{model_selector.get('pid_parameters.kp', 0):.2f}" ,
                    "pb": f"{model_selector.get('pid_parameters.pb', 0):.2f}" ,
                    "td": f"{model_selector.get('pid_parameters.td', 0):.2f}" ,
                    "ti": f"{model_selector.get('pid_parameters.ti', 0):.2f}"
                },
            }

            # #写入整定记录
            # try:
            #     if model_selector.get("success")==False:
            #         logger.error("整定失败，请选择合适时间区间进行整定分析。")
            #         raise RuntimeException("整定失败，请选择合适时间区间进行整定分析。")
            #     _save_tuning_record_liu(
            #         loop_uri=loop_uri,
            #         current_params=before_pid_params,
            #         suggested_params=suggest_pid_params,
            #         mode=mode,
            #         operator=operator_name,
            #         operator_id=operator_id,
            #         model_type=model_type,
            #         tuning_type=turning_type,
            #         status=True,
            #         tuning_details=tuning_details,
            #     )
            # except Exception as e:
            #     logger.error(f"写入整定记录失败: {str(e)}")
            #     raise RuntimeException("写入整定记录失败")

            return model_selector
        except Exception as e:
            logger.error(f"整定失败: {str(e)}")
            # _save_tuning_record_liu(
            #     loop_uri=loop_uri,
            #     current_params=before_pid_params,
            #     suggested_params={},
            #     mode=mode,
            #     operator=operator_name,
            #     operator_id=operator_id,
            #     model_type=model_type,
            #     tuning_type=turning_type,
            #     status=False,
            #     error_message=f"整定异常:{str(e)}",
            # )
            raise

    @staticmethod
    def auto_tuning(
            mode: str = "auto",
            loop_uri: str = None,
            start_time: Union[int, str] = None,
            end_time: Union[int, str] = None,
            tuning_windows: Optional[List[Dict[str, Any]]] = None,
            model_type: ModelType = ModelType.FOPDT,
            turning_type: str = "PID",
            lambda_val: Optional[float] = None,
            window_size: int = 120,
            step_size: int = 10,
            confidence_threshold: float = 0.6,
            window_sec: int = 60,
            is_filter: bool = False
    ) -> Dict[str, Any]:
        """
        智能PID参数整定接口

        Args:
            mode: 整定模式：auto(自动筛选) 或 manual(手动指定时间范围)
            loop_uri: 回路URI
            start_time: 开始时间（manual模式必填），支持毫秒时间戳或字符串格式
            end_time: 结束时间（manual模式必填），支持毫秒时间戳或字符串格式
            model_type: 模型类型
            lambda_val: Lambda参数值（可选），未指定时自动计算
            window_size: 窗口大小（分钟）
            step_size: 滑动步长（分钟）
            confidence_threshold: 置信度阈值（仅auto模式有效，0-1）
            window_sec: 插值采样间隔（秒）
            is_filter: 是否对历史数据进行优化过滤

        Returns:
            Dict[str, Any]: PID参数整定结果
        """
        try:
            # 参数验证
            if mode not in ["auto", "manual"]:
                mode = 'auto'

            # 时间范围处理
            if end_time is None:
                end_time = int(datetime.now().timestamp() * 1000)
            if start_time is None:
                start_time = end_time - 24 * 60 * 60 * 1000  # 默认1天
            logger.info(f"将在时间范围 {start_time} - {end_time} 内筛选最佳整定区间")

            # 时间格式转换
            start_time_ms = parse_time_to_milliseconds(start_time)
            end_time_ms = parse_time_to_milliseconds(end_time)

            if start_time_ms >= end_time_ms:
                raise ValueError("开始时间必须小于结束时间")

            # 固定设备与字段配置
            table, required_fields = BFFModelClient.query_table_and_points_by_loop_uri(loop_uri)

            iot_db = get_default_database()

            # 初始化变量
            qualified_windows = []
            best_window = None
            window_data = []

            # 根据模式执行不同逻辑
            if mode == "auto":
                # 自动筛选模式
                logger.info(f"执行自动整定，时间范围：{start_time} - {end_time}")

                # 获取历史数据
                history_data = process_query_tsdb_data_interpolated(
                    db=iot_db,
                    table_name=table,
                    required_fields=required_fields,
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                    is_filter=is_filter,
                    window=window_sec
                )

                if not history_data or len(history_data) == 0:
                    return {
                        "mode": mode,
                        "message": "指定时间范围内无数据"
                    }

                # 构建DataFrame用于窗口检测
                df = pd.DataFrame(history_data)
                if "timestamp" not in df.columns or "pv" not in df.columns or "mv" not in df.columns:
                    raise ValueError("历史数据缺少必要字段")

                # 滑动窗口检测阶跃响应
                window_size_sec = window_size * 60
                step_size_sec = step_size * 60

                # 转换为numpy数组
                t_array = (df["timestamp"].values - df["timestamp"].values[0]) / 1000  # 相对时间（秒）
                pv_array = df["pv"].values
                mv_array = df["mv"].values

                # 使用采样间隔换算为"点数"窗口与步长
                dt_seconds = float((df["timestamp"].values[1] - df["timestamp"].values[0]) / 1000) if len(
                    df["timestamp"].values) > 1 else 1.0
                window_size_points = max(1, int(window_size_sec / dt_seconds))
                step_size_points = max(1, int(step_size_sec / dt_seconds))

                qualified_windows = []
                total_windows_to_check = len(range(0, max(0, len(t_array) - window_size_points), step_size_points))
                logger.info(f"开始扫描时间窗口，总共需检查 {total_windows_to_check} 个窗口")

                for i in range(0, max(0, len(t_array) - window_size_points), step_size_points):
                    # 窗口范围（按点数）
                    window_start_idx = i
                    window_end_idx = min(i + window_size_points, len(t_array))

                    if window_end_idx - window_start_idx < 60:  # 至少60个点
                        continue

                    t_window = np.array(t_array[window_start_idx:window_end_idx])
                    pv_window = np.array(pv_array[window_start_idx:window_end_idx])
                    mv_window = np.array(mv_array[window_start_idx:window_end_idx])
                    # 检测阶跃响应
                    step_info = SystemIdentifier.detect_step_response_in_window(
                        t_window, pv_window, mv_window,
                        step_threshold=0.05,
                        response_ratio=0.1
                    )

                    if step_info.get('has_step') and step_info.get('confidence', 0) >= confidence_threshold:
                        # 记录窗口信息
                        window_start_ms = int(df["timestamp"].values[window_start_idx])
                        window_end_ms = int(df["timestamp"].values[window_end_idx - 1])

                        qualified_windows.append({
                            "start_timestamp": window_start_ms,
                            "end_timestamp": window_end_ms,
                            "confidence": step_info.get('confidence'),
                            "step_size": step_info.get('step_size'),
                            "response_magnitude": step_info.get('response_magnitude'),
                            "data_indices": (window_start_idx, window_end_idx)
                        })

                if not qualified_windows:
                    logger.warning(f"在 {total_windows_to_check} 个窗口中未找到符合条件的阶跃响应")
                    return {
                        "mode": mode,
                        "message": f"未找到符合条件的阶跃响应窗口（已检查{total_windows_to_check}个窗口），建议：1)降低confidence_threshold（当前{confidence_threshold}）2)增加window_size 3)调整时间范围",
                        "total_windows_checked": total_windows_to_check,
                        "qualified_windows": 0,
                        "suggestion": {
                            "current_confidence_threshold": confidence_threshold,
                            "suggested_confidence_threshold": max(0.3, confidence_threshold - 0.2),
                            "current_window_size_minutes": window_size,
                            "suggested_window_size_minutes": window_size + 60
                        }
                    }

                # 选择置信度最高的窗口
                best_window = max(qualified_windows, key=lambda x: x['confidence'])
                logger.info(
                    f"找到 {len(qualified_windows)} 个合格窗口，选择最佳窗口：置信度={best_window['confidence']:.3f}, 阶跃大小={best_window.get('step_size', 'N/A'):.2f}, 时间范围: {format_time_to_string(best_window['start_timestamp'])} - {format_time_to_string(best_window['end_timestamp'])}")
                # 提取最佳窗口数据用于整定
                window_data = process_query_tsdb_data_interpolated(
                    db=iot_db,
                    table_name=table,
                    required_fields=required_fields,
                    start_time=best_window['start_timestamp'],
                    end_time=best_window['end_timestamp'],
                    is_filter=is_filter
                )

            else:
                # 手动指定模式
                logger.info(f"执行手动整定，时间范围：{start_time} - {end_time}")

                # 直接查询指定时间范围的数据
                window_data = process_query_tsdb_data_interpolated(
                    db=iot_db,
                    table_name=table,
                    required_fields=required_fields,
                    start_time=start_time_ms,
                    end_time=end_time_ms,
                    is_filter=is_filter,
                    window=1
                )

                if not window_data or len(window_data) == 0:
                    return {
                        "mode": mode,
                        "message": "指定时间范围内无数据"
                    }

                best_window = {
                    "start_timestamp": start_time_ms,
                    "end_timestamp": end_time_ms,
                    "confidence": None,
                    "step_size": None,
                    "response_magnitude": None
                }

            # 执行PID参数整定
            optimization_tool = PIDOptimizationTool()
            # 执行整定
            optimization_result = optimization_tool._run(
                history_data=window_data,
                is_lambda=True,
                model_type=model_type
            )

            # model_select =ModelSelector()
            # request={
            #         "history_data": history_data,
            #         "params": {
            #             "model_type": model_type,        # 可选，强制使用指定模型
            #             "turning_type": turning_type,      # 可选，整定类型
            #             "analyst_column": "pv",
            #         },
            #         "qualified_windows": tuning_windows
            #     }
            # model_selector = model_select.run(request)
            # 解析结果
            try:
                result_data = json.loads(optimization_result)

                # 构建返回数据
                response = {
                    "mode": mode,
                    "table": table,
                    "time_range": {
                        "start_time": format_time_to_string(best_window["start_timestamp"]),
                        "end_time": format_time_to_string(best_window["end_timestamp"]),
                        "duration_seconds": (best_window["end_timestamp"] - best_window["start_timestamp"]) / 1000
                    },
                    "model_type": model_type.value,
                    "lambda_tuning_enabled": True,
                    "optimization_result": optimization_result
                }

                # 写入整定成功记录到数据库
                # try:
                    # _save_tuning_record(
                    #     loop_uri=loop_uri,
                    #     result_data=result_data,
                    #     mode=mode,
                    #     model_type=model_type.value,
                    #     turning_type=turning_type,
                    #     status="成功"
                    # )
                # except Exception as record_err:
                #     logger.warning(f"整定记录写入失败（不影响整定结果）: {str(record_err)}")

                return response

            except json.JSONDecodeError as json_err:
                # JSON解析失败，记录失败状态
                error_msg = f"参数整定失败: {optimization_result}"

                # 写入整定失败记录
                # try:
                #     _save_tuning_record(
                #         loop_uri=loop_uri,
                #         result_data=None,
                #         mode=mode,
                #         model_type=model_type.value,
                #         turning_type=turning_type,
                #         error_message=error_msg
                #     )
                # except Exception as record_err:
                #     logger.warning(f"失败记录写入失败: {str(record_err)}")

                return {
                    "mode": mode,
                    "message": error_msg
                }

        except Exception as e:
            error_msg = f"自动整定失败: {str(e)}"
            logger.error(error_msg, exc_info=True)

            # 写入整定失败记录
            # try:
            #     _save_tuning_record(
            #         loop_uri=loop_uri,
            #         result_data=None,
            #         mode=mode,
            #         model_type=model_type.value,
            #         turning_type=turning_type,
            #         status="失败",
            #         error_message=error_msg
            #     )
            # except Exception as record_err:
            #     logger.warning(f"失败记录写入失败: {str(record_err)}")

            raise

    @staticmethod
    def detect_and_visualize_service(
            loop_uri: str = None,
            start_time: Union[int, str] = None,
            end_time: Union[int, str] = None
    ) -> Dict[str, Any]:
        """
        智能识别时间区间数据状态（稳态、非稳态）

        Args:
            loop_uri: 回路URI
            start_time: 开始时间，支持毫秒时间戳或字符串格式
            end_time: 结束时间，支持毫秒时间戳或字符串格式

        Returns:
            Dict[str, Any]: 检测结果
        """
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
                raise ValueError("开始时间必须小于结束时间")

            # 固定设备与字段
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
                raise ValueError("数据不足，无法进行时间窗口筛选")

            # 调用自动筛选方法
            result = detect_and_visualize(history_data)

            return {
                "start_time": start_time,
                "end_time": end_time,
                "result": result,
            }

        except Exception as e:
            logger.error(f"识别失败: {str(e)}")
            raise

    @staticmethod
    def calculate_pid(
            K: float,
            T1: float,
            T2: Optional[float] = None,
            L: Optional[float] = 0,
            lambda_val: Optional[float] = None,
            model_type: ModelType = ModelType.FOPDT
    ) -> Dict[str, Any]:
        """
        根据输入的模型参数(K、T、L)和模型类型，直接计算对应的PID参数

        Args:
            K: 增益系数 K
            T1: 时间常数 T1 (秒)
            T2: 二阶时间常数 T2 (秒，仅二阶模型需要)
            L: 滞后时间 L (秒)
            lambda_val: Lambda值（期望闭环时间常数），不指定时自动计算
            model_type: 模型类型

        Returns:
            Dict[str, Any]: PID参数计算结果
        """
        try:
            # 转换ModelType为字符串
            mt_str = model_type.value if isinstance(model_type, ModelType) else str(model_type)

            # 参数验证
            # if K <= 0:
            #     raise ValueError("K值必须大于0")
            if T1 <= 0:
                raise ValueError("T值必须大于0")
            if L is not None and L < 0:
                raise ValueError("L值不能为负")

            # 确保L有默认值
            if L is None:
                L = 0.0

            # 根据模型类型验证参数
            if mt_str in ['SOPDT', 'SO', 'SO_INTEGRATOR']:
                if T2 is None or T2 <= 0:
                    raise ValueError(f"{mt_str}模型需要有效的T2参数（大于0）")

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
                raise ValueError(f"不支持的模型类型: {mt_str}")

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

        except Exception as e:
            logger.error(f"PID参数计算失败: {str(e)}")
            raise


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


def _save_tuning_record(
        loop_uri: str,
        result_data: Optional[Dict[str, Any]],
        mode: str,
        model_type: str,
        operator: str,
        turning_type: str,
        status: str = "成功",
        error_message: Optional[str] = None
) -> None:
    """
    保存整定记录到数据库（支持成功和失败状态）

    Args:
        loop_uri: 回路URI
        result_data: 整定结果数据（失败时为None）
        mode: 整定模式 (auto/manual)
        model_type: 模型类型（FOPDI/FO....）
        turning_type: 整定类型（PID/PI）
        operator: 操作人
        status: 整定状态 (成功/失败)
        error_message: 错误信息（失败时使用）
    """
    try:
        with get_db_session() as db:
            # 获取回路名称
            loop_info = LoopInfoDAO.get_by_loop_uri(db, loop_uri, include_inactive=True)
            loop_name = loop_info.loop_name if loop_info else None
            description = loop_info.description if loop_info else None

            # 根据状态处理参数
            if status == "成功":
                # 提取整定前后参数
                # current_params = result_data.get('current_params', {})
                # tuning_suggestions = result_data.get('tuning_suggestions', {})
                # lambda_params = tuning_suggestions.get('lambda_suggested_params', {})
                # suggested_params = lambda_params.get('params', {})

                # 格式化参数字符串
                # before_params_str = f"Kp:{current_params.get('Kp', 0):.2f}, Ti:{current_params.get('Ti', 0):.2f}, Td:{current_params.get('Td', 0):.2f}"
                # after_params_str = f"Kp:{suggested_params.get('Kp', 0):.2f}, Ti:{suggested_params.get('Ti', 0):.2f}, Td:{suggested_params.get('Td', 0):.2f}"
                remark = f"模式: {mode}, 模型类型: {model_type},整定类型: {turning_type}"
            else:
                # 失败情况
                before_params_str = None
                after_params_str = None
                remark = f"模式: {mode}, 模型类型: {model_type},整定类型: {turning_type}, 错误: {error_message or '未知错误'}"

            # 创建整定记录
            record_data = {
                "loop_uri": loop_uri,
                "description": description,
                "tuning_method": f"常规整定",
                "tuning_time": datetime.now(),
                "operator": "system",  # 操作人
                "before_params": before_params_str,
                "after_params": after_params_str,
                "status": status,
                "remark": remark,
                "tuning_details": result_data if result_data else {"error": error_message},  # 存储完整的整定结果或错误信息
                "created_time": datetime.now(),
                "updated_time": datetime.now()
            }

            # 写入数据库
            TuningRecordDAO.create(db, record_data)
            logger.info(
                f"整定记录写入成功: loop_uri={loop_uri}, method=常规整定,整定类型={turning_type}, status={status}, status={status}")

    except Exception as e:
        logger.error(f"保存整定记录失败: {str(e)}")
        raise


def _save_tuning_record_liu(
        loop_uri: str,
        current_params: Dict[str, Any],
        suggested_params: Dict[str, Any],
        mode: str,
        model_type: ModelType,
        tuning_type: str,
        operator: str,
        operator_id: Optional[str] = None,
        status: bool = True,
        tuning_details: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None
) -> None:
    """
    保存整定记录到数据库（支持成功和失败状态）

    Args:
        loop_uri: 回路URI
        result_data: 整定结果数据（失败时为None）
        mode: 整定模式 (手动/自动)
        model_type: 模型类型(FODPT....)
        tuning_type: 整定类型 (PID/PI)
        operator: 操作人
        operator_id: 操作人ID
        status: 整定状态 (成功/失败)
        error_message: 错误信息（失败时使用）
    """
    try:
        with get_db_session() as db:
            # 获取回路名称
            loop_info = LoopInfoDAO.get_by_loop_uri(db, loop_uri, include_inactive=True)
            loop_name = loop_info.loop_name if loop_info else None
            description = loop_info.description if loop_info else None
            status_str = "成功" if status else "失败"
            # 根据状态处理参数
            if status:
                # 格式化参数字符串
                # before_params_str = f"Kp:{current_params.get('Kp', 0):.2f}, Ti:{current_params.get('Ti', 0):.2f}, Td:{current_params.get('Td', 0):.2f}"
                # after_params_str = f"Kp:{suggested_params.get('Kp', 0):.2f}, Ti:{suggested_params.get('Ti', 0):.2f}, Td:{suggested_params.get('Td', 0):.2f}"
                before_params_str=json.dumps(current_params)
                after_params_str=json.dumps(suggested_params)
                remark = f"整定模式: {mode}, 模型类型: {model_type.value}, 整定类型: {tuning_type}"
            else:
                # 失败情况
                before_params_str = None
                after_params_str = None
                remark = f"整定模式: {mode}, 模型类型: {model_type.value}, 整定类型: {tuning_type}, 错误: {error_message or '未知错误'}"
            # 创建整定记录
            record_data = {
                "loop_uri": loop_uri,
                "tuning_method": f"常规整定",
                "tuning_time": datetime.now(),
                "operator": operator,
                "operator_id":operator_id,# 操作人
                "before_params": before_params_str,
                "after_params": after_params_str,
                "status": status_str,
                "remark": remark,
                "tuning_details": json.dumps(tuning_details) if tuning_details else {"error": error_message},
                "created_time": datetime.now(),
                "updated_time": datetime.now()
            }

            # 写入数据库
            TuningRecordDAO.create(db, record_data)
            logger.info(f"整定记录写入成功: loop_name={loop_name}, method=常规整定, status={status}")

    except Exception as e:
        logger.error(f"保存整定记录失败: {str(e)}")
        raise
