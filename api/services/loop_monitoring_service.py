#!/usr/bin/env python3
"""
回路监控业务服务层
封装回路监控相关的业务逻辑
"""

import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from api.services.device_data_service import DeviceDataService
from core.client.bff_model_client import BFFModelClient
from core.algorithm.stability_rate import PerformanceEvaluator

logger = logging.getLogger(__name__)


class LoopMonitoringService:
    """回路监控业务服务"""

    @staticmethod
    def get_loop_realtime_status(
            plant_uri: Optional[str] = None,
            loop_name: Optional[str] = None,
            status: Optional[str] = None,
            page_no: int = 1,
            page_size: int = 20
    ) -> Dict[str, Any]:
        """
        获取回路实时状态列表
        
        Args:
            plant_uri: 装置URI，用于筛选指定装置下的回路
            loop_name: 回路名称模糊查询
            status: 状态筛选（自动/手动/异常）
            page_no: 页码
            page_size: 每页数量
            
        Returns:
            包含回路列表和分页信息的字典
        """
        try:
            # 使用BFF客户端查询回路列表
            with BFFModelClient() as client:
                # 如果指定了装置URI，则查询该装置下的回路
                start_identifier_list = [plant_uri] if plant_uri else []
                model_identifier_list = ['/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243']
                result = client.list_instances_under_tree(
                    model_identifier_list=model_identifier_list,
                    start_identifier_list=start_identifier_list,
                    contain_sub_model=True,
                    page_no=page_no,
                    page_size=page_size
                )

                logger.info(
                    f"BFF查询成功，实例数量: {len(result.get('instances', []))}"
                )

                # 获取回路列表
                instances = result.get('instances', [])

                # 过滤回路名称
                if loop_name:
                    instances = [instance for instance in instances
                                 if loop_name.lower() in instance.get('displayName', '').lower()]

                # 获取实时数据
                loop_list = []
                for instance in instances:
                    loop_uri = instance.get('uri')

                    # 查询回路的实时数据 (PV, SV, MV)
                    try:
                        point_values = client.query_current_raw_values(
                            point_names=['PV', 'SV', 'MV', 'AUTO'],
                            loop_uri=loop_uri
                        )

                        # 获取量程信息
                        range_values = client.query_current_raw_values(
                            point_names=['PVH', 'PVL', 'SVH', 'SVL', 'MVH', 'MVL'],
                            loop_uri=loop_uri
                        )

                        # 判断回路类型
                        extended_attr = instance.get('extendedAttr', {})
                        loop_type = extended_attr.get('loop_type', '未知')

                        # 获取自控情况
                        auto_status = point_values.get('AUTO', 0)  # 1表示自动，0表示手动
                        control_status = "自动" if auto_status == 1 else "手动"

                        # 获取当前值
                        current_pv = point_values.get('PV')
                        current_sv = point_values.get('SV')
                        current_mv = point_values.get('MV')

                        # 获取量程
                        pv_range_max = range_values.get('PVH', 100)
                        pv_range_min = range_values.get('PVL', 0)
                        sv_range_max = range_values.get('SVH', 100)
                        sv_range_min = range_values.get('SVL', 0)
                        mv_range_max = range_values.get('MVH', 100)
                        mv_range_min = range_values.get('MVL', 0)

                        # 格式化当前值显示
                        pv_display = f"{current_pv:.1f} ({pv_range_min}-{pv_range_max})" if current_pv is not None else "--"
                        sv_display = f"{current_sv:.1f}" if current_sv is not None else "--"
                        mv_display = f"{current_mv:.1f}%" if current_mv is not None else "--"

                        # 判断运行状态（简化实现，实际应根据数据质量等判断）
                        running_status = "运行" if current_pv is not None else "停止"

                        # 判断平稳情况（简化实现，实际应根据历史数据分析）
                        stability = "稳定" if current_pv is not None else "未知"

                        loop_item = {
                            "loop_uri": loop_uri,
                            "loop_name": instance.get('displayName', ''),
                            "description": instance.get('description', ''),
                            "loop_type": loop_type,
                            "control_status": control_status,  # 自控情况
                            "exclusion_condition": "",  # 剔除条件
                            "running_status": running_status,  # 运行状态
                            "loop_characteristics": "",  # 回路特性
                            "current_pv": pv_display,
                            "current_sv": sv_display,
                            "current_mv": mv_display,
                            "stability": stability,  # 平稳情况
                        }

                        # 状态筛选
                        if status is None or status == "" or control_status == status:
                            loop_list.append(loop_item)

                    except Exception as e:
                        logger.warning(f"查询回路 {loop_uri} 实时数据失败: {str(e)}")
                        # 即使某个回路数据查询失败，也添加基本信息
                        loop_item = {
                            "loop_uri": loop_uri,
                            "loop_name": instance.get('displayName', ''),
                            "description": instance.get('description', ''),
                            "loop_type": extended_attr.get('loop_type', ''),
                            "control_status": "",  # 自控情况
                            "exclusion_condition": "",  # 剔除条件
                            "running_status": "",  # 运行状态
                            "loop_characteristics": "",  # 回路特性
                            "current_pv": "--",
                            "current_sv": "--",
                            "current_mv": "--",
                            "stability": "",  # 平稳情况
                        }
                        loop_list.append(loop_item)

                # 计算分页信息
                total = len(loop_list)
                pages = (total + page_size - 1) // page_size if total > 0 else 0

                # 分页截取
                start_index = (page_no - 1) * page_size
                end_index = start_index + page_size
                paginated_loops = loop_list[start_index:end_index]

                return {
                    "loops": paginated_loops,
                    "pagination": {
                        "total": total,
                        "pages": pages,
                        "pageNo": page_no,
                        "pageSize": page_size
                    }
                }

        except Exception as e:
            logger.error(f"查询回路实时状态失败: {str(e)}")
            raise

    @staticmethod
    def get_loop_trend_data(
            loop_uri: str,
            start_time: int,
            end_time: int
    ) -> Dict[str, Any]:
        """
        获取回路趋势数据
        
        Args:
            loop_uri: 回路URI
            start_time: 开始时间（毫秒时间戳）
            end_time: 结束时间（毫秒时间戳）
            
        Returns:
            包含趋势数据的字典
        """
        try:
                # 查询历史插值数据
                history_data = DeviceDataService.query_history_data_interpolated(
                    loop_uri=loop_uri,
                    start_time=start_time,
                    end_time=end_time,
                    window=1000  # 限制数据点数量
                )

                # 检查是否有数据
                if not history_data or not history_data.get('data'):
                    return {
                        "message": "暂无实时数据",
                        "trend_data": {
                            "timestamps": [],
                            "pv_values": [],
                            "sv_values": [],
                            "mv_values": []
                        }
                    }

                data_points = history_data.get('data', [])

                # 提取趋势数据
                timestamps = []
                pv_values = []
                sv_values = []
                mv_values = []

                for point in data_points:
                    if isinstance(point, dict):
                        timestamp = point.get('timestamp')
                        pv = point.get('PV')
                        sv = point.get('SV')
                        mv = point.get('MV')

                        # 只有当时间戳存在时才添加数据点
                        if timestamp is not None:
                            timestamps.append(timestamp)
                            pv_values.append(pv if pv is not None else None)
                            sv_values.append(sv if sv is not None else None)
                            mv_values.append(mv if mv is not None else None)

                # 检查数据是否为空
                if not timestamps:
                    return {
                        "message": "暂无实时数据",
                        "trend_data": {
                            "timestamps": [],
                            "pv_values": [],
                            "sv_values": [],
                            "mv_values": []
                        }
                    }

                return {
                    "message": "数据加载成功",
                    "trend_data": {
                        "timestamps": timestamps,
                        "pv_values": pv_values,
                        "sv_values": sv_values,
                        "mv_values": mv_values
                    }
                }

        except Exception as e:
            logger.error(f"查询回路趋势数据失败: {str(e)}")
            return {
                "message": f"错误描述：趋势图数据加载超时",
                "trend_data": {
                    "timestamps": [],
                    "pv_values": [],
                    "sv_values": [],
                    "mv_values": []
                }
            }

    @staticmethod
    def calculate_performance_status(
            loop_uri: str,
            time_span: int = 24
    ) -> Dict[str, Any]:
        """
        根据过去历史数据计算回路的性能状态ÒÒ
        
        计算四个维度的性能指标：
        1. 投入度维度：自控率
        2. 稳定性维度：平稳率
        3. 精确性维度：标准偏差
        4. 高效性维度：阀门活动度
        
        Args:
            loop_uri: 回路URI
            
        Returns:
            包含性能指标的字典，包括：
            - auto_control_rate: 自控率
            - stability_rate: 平稳率
            - precision_std: 标准偏差
            - valve_activity: 阀门活动度
            - comprehensive_score: 综合评分
            - status: 性能等级（优秀/良好/一般/差）
        """
        try:
            # 计算时间范围
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=time_span)
            #
            end_time_ms = int(end_time.timestamp() * 1000)
            start_time_ms = int(start_time.timestamp() * 1000)
            # 查询历史数据
            history_data = DeviceDataService.query_history_data_interpolated(
                loop_uri=loop_uri,
                start_time=start_time_ms,
                end_time=end_time_ms,
                is_filter=False,
                window=60
            )


            # 检查数据有效性
            if not history_data or not history_data.get('data'):
                logger.warning(f"回路 {loop_uri} 无历史数据")
                return {
                    "loop_uri": loop_uri,
                    "status": "无数据",
                    "message": "没有足够的历史数据进行评估",
                    "auto_control_rate": None,
                    "stability_rate": None,
                    "precision_std": None,
                    "valve_activity": None,
                    "comprehensive_score": None
                }

            data_points = history_data.get('data', [])

            # 提取时间序列数据
            timestamps = []
            pv_values = []
            sv_values = []
            mv_values = []
            auto_status_values = []

            for point in data_points:
                if isinstance(point, dict):
                    ts = point.get('timestamp')
                    pv = point.get('pv')
                    sv = point.get('sv')
                    mv = point.get('mv')
                    auto_status = point.get('auto', 255)  # 默认为自动
                    timestamps.append(ts)
                    pv_values.append(pv)
                    sv_values.append(sv)
                    mv_values.append(mv)
                    auto_status_values.append(auto_status)
                    # if ts is not None and pv is not None and sv is not None:


            # 检查是否有足够的数据点
            if len(timestamps) < 10:
                logger.warning(f"回路 {loop_uri} 数据点过少（{len(timestamps)}<10）")
                return {
                    "loop_uri": loop_uri,
                    "status": "数据不足",
                    "message": f"只有 {len(timestamps)} 个数据点，无法进行完整评估",
                    "auto_control_rate": None,
                    "stability_rate": None,
                    "precision_std": None,
                    "valve_activity": None,
                    "comprehensive_score": None
                }

            # 转换时间序列为相对时间（秒）
            time_seconds = [(ts - timestamps[0]) / 1000.0 for ts in timestamps]

            # 1. 计算自控率（投入度维度）
            auto_control_result = PerformanceEvaluator.calculate_auto_control_rate(
                time=time_seconds,
                auto_status=auto_status_values
            )
            auto_control_rate = auto_control_result.get('auto_control_rate', 0)

            # 2. 计算平稳率（稳定性维度）
            stability_result = PerformanceEvaluator.calculate_stability_rate_auto(
                time=time_seconds,
                PV=pv_values,
                SV=sv_values,
                auto_status=auto_status_values,
                threshold_percent=2.0
            )
            stability_rate = stability_result.get('stability_rate', 0)

            # 3. 计算精确性（标准偏差）
            precision_result = PerformanceEvaluator.calculate_precision_std_auto(
                PV=pv_values,
                SV=sv_values,
                auto_status=auto_status_values,
                use_SV=True
            )
            precision_std = precision_result.get('sigma_sp', 0)  # 相对设定值的标准差

            # 4. 计算高效性（阀门活动度）
            efficiency_result = PerformanceEvaluator.calculate_valve_activity_auto(
                time=time_seconds,
                MV=mv_values,
                auto_status=auto_status_values
            )
            valve_activity_cac = efficiency_result.get('cac', 0)  # 累计绝对变化

            # 计算综合评分（四维度加权）
            # 权重：自控率 20%，平稳率 40%，精确性 30%，高效性 10%
            auto_score = min(100, auto_control_rate)  # 直接使用百分比
            stability_score = min(100, stability_rate)  # 直接使用百分比

            # 精确性评分：标准差越小越好
            # 假设 σ < 0.5% 得100分，σ > 2.0% 得0分
            if precision_std < 0.5:
                precision_score = 100
            elif precision_std > 2.0:
                precision_score = 0
            else:
                precision_score = 100 - (precision_std - 0.5) / (2.0 - 0.5) * 100

            # 高效性评分：阀门活动度越低越好
            # 假设 CAC < 1000 得100分，CAC > 5000 得0分
            if valve_activity_cac < 1000:
                efficiency_score = 100
            elif valve_activity_cac > 5000:
                efficiency_score = 0
            else:
                efficiency_score = 100 - (valve_activity_cac - 1000) / (5000 - 1000) * 100

            # 综合评分
            comprehensive_score = (
                    auto_score * 0.2 +
                    stability_score * 0.4 +
                    precision_score * 0.3 +
                    efficiency_score * 0.1
            )

            # 判断性能等级
            if comprehensive_score >= 85:
                status = "优秀"
            elif comprehensive_score >= 70:
                status = "良好"
            elif comprehensive_score >= 50:
                status = "一般"
            else:
                status = "差"

            return {
                "loop_uri": loop_uri,
                "status": status,
                "comprehensive_score": round(comprehensive_score, 2),
                "performance_metrics": {
                    "auto_control_rate": round(auto_control_rate, 2),
                    "stability_rate": round(stability_rate, 2),
                    "precision_std": round(precision_std, 4),
                    "valve_activity_cac": round(valve_activity_cac, 2)
                },
                "performance_scores": {
                    "auto_control_score": round(auto_score, 2),
                    "stability_score": round(stability_score, 2),
                    "precision_score": round(precision_score, 2),
                    "efficiency_score": round(efficiency_score, 2)
                },
                "weights": {
                    "auto_control": 0.2,
                    "stability": 0.4,
                    "precision": 0.3,
                    "efficiency": 0.1
                },
                "data_points_count": len(timestamps),
                "time_range": {
                    "start": start_time.isoformat(),
                    "end": end_time.isoformat()
                }
            }

        except Exception as e:
            logger.error(f"计算回路 {loop_uri} 过去性能状态失败: {str(e)}")
            return {
                "loop_uri": loop_uri,
                "status": "计算失败",
                "error": str(e),
                "auto_control_rate": None,
                "stability_rate": None,
                "precision_std": None,
                "valve_activity": None,
                "comprehensive_score": None
            }

    @staticmethod
    def calculate_performance_status_batch(
            loop_uris: List[str],
            max_workers: int = 5,
            data_span: int = 24
    ) -> Dict[str, Any]:
        """
        批量计算多个回路性能状态（并行计算）
        
        使用线程池并行计算多个回路的性能指标，提高计算效率。
        
        Args:
            loop_uris: 回路URI列表
            max_workers: 线程池最大工作线程数，默认5个
            data_span: 时间跨度
            
        Returns:
            包含所有回路性能状态的列表和统计汇总信息
        """
        if not loop_uris:
            return {
                "status": "失败",
                "message": "回路URI列表为空",
                "results": [],
                "summary": {}
            }

        try:
            results = []
            failed_loops = []

            # 使用线程池并行计算
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                future_to_uri = {
                    executor.submit(
                        LoopMonitoringService.calculate_performance_status,
                        loop_uri,data_span
                    ): loop_uri for loop_uri in loop_uris
                }

                # 收集结果
                for future in as_completed(future_to_uri):
                    loop_uri = future_to_uri[future]
                    try:
                        result = future.result()
                        results.append(result)

                        # 记录失败的回路
                        if result.get('status') in ['计算失败', '无数据', '数据不足']:
                            failed_loops.append({
                                "loop_uri": loop_uri,
                                "reason": result.get('status', '未知原因')
                            })
                    except Exception as e:
                        logger.error(f"计算回路 {loop_uri} 性能状态异常: {str(e)}")
                        failed_loops.append({
                            "loop_uri": loop_uri,
                            "reason": str(e)
                        })
                        results.append({
                            "loop_uri": loop_uri,
                            "status": "异常",
                            "error": str(e)
                        })

            # 计算汇总统计
            successful_results = [r for r in results if r.get('status') in ['优秀', '良好', '一般', '差']]

            summary = {
                "total_loops": len(loop_uris),
                "successful_loops": len(successful_results),
                "failed_loops": len(failed_loops),
                "success_rate": round(len(successful_results) / len(loop_uris) * 100, 2) if loop_uris else 0,
                "average_comprehensive_score": None,
                "status_distribution": {
                    "优秀": 0,
                    "良好": 0,
                    "一般": 0,
                    "差": 0
                }
            }

            # 计算平均综合评分和状态分布
            if successful_results:
                scores = [r.get('comprehensive_score', 0) for r in successful_results if
                          r.get('comprehensive_score') is not None]
                if scores:
                    summary["average_comprehensive_score"] = round(sum(scores) / len(scores), 2)

                # 统计状态分布
                for result in successful_results:
                    status = result.get('status', '未知')
                    if status in summary["status_distribution"]:
                        summary["status_distribution"][status] += 1

            return {
                "status": "成功" if not failed_loops else "部分成功",
                "message": f"已处理 {len(loop_uris)} 个回路，其中 {len(successful_results)} 个成功",
                "results": results,
                "summary": summary,
                "failed_details": failed_loops if failed_loops else None
            }

        except Exception as e:
            logger.error(f"批量计算回路性能状态失败: {str(e)}")
            return {
                "status": "失败",
                "message": f"批量计算失败: {str(e)}",
                "results": [],
                "summary": {}
            }

    @staticmethod
    def calculate_performance_status_plant(
            plant_uri: Optional[str] = None,
            max_workers: int = 5,
            data_span: int = 24
    ) -> Dict[str, Any]:
        """
        计算指定装置下所有回路的性能状态（并行计算）
        
        Args:
            plant_uri: 装置URI，如果为None则查询所有装置
            max_workers: 线程池最大工作线程数，默认5个
            
        Returns:
            包含装置内所有回路性能状态的字典和统计信息
        """
        try:
            # 首先获取装置下的所有回路
            with BFFModelClient() as client:
                start_identifier_list = [plant_uri] if plant_uri else []
                model_identifier_list = ['/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243']

                result = client.list_instances_under_tree(
                    model_identifier_list=model_identifier_list,
                    start_identifier_list=start_identifier_list,
                    contain_sub_model=True,
                    page_no=1,
                    page_size=1000  # 一次性获取更多回路
                )

                instances = result.get('instances', [])

            if not instances:
                return {
                    "status": "无回路",
                    "message": f"装置 {plant_uri} 下没有找到回路",
                    "results": [],
                    "summary": {}
                }

            # 提取回路URI列表
            loop_uris = [instance.get('uri') for instance in instances if instance.get('uri')]

            logger.info(f"装置 {plant_uri} 找到 {len(loop_uris)} 个回路，开始并行计算...")

            # 使用批量计算方法
            return LoopMonitoringService.calculate_performance_status_batch(
                loop_uris=loop_uris,
                max_workers=max_workers,
                data_span=data_span
            )

        except Exception as e:
            logger.error(f"计算装置 {plant_uri} 回路性能状态失败: {str(e)}")
            return {
                "status": "失败",
                "message": f"计算失败: {str(e)}",
                "results": [],
                "summary": {}
            }
