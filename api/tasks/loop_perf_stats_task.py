import logging
from datetime import datetime, timedelta

from api.dao.excluded_loop_dao import ExcludedLoopDAO
from api.services.loop_monitoring_service import LoopMonitoringService
from api.services.loop_service import LoopService
from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO
from api.dao.loop_evaluation_dao import LoopEvaluationDAO


logger = logging.getLogger(__name__)

# -------------------
# 回路性能定时统计任务
# -------------------

def calc_loop_performance(max_workers: int = 5) -> dict:
    # 计算时间范围
    end_time = datetime.now()
    start_time = end_time - timedelta(hours=24)
    return _calc_loop_performance(start_time, end_time, max_workers)


def _calc_loop_performance(start_time: datetime, end_time: datetime, max_workers: int = 5) -> dict:
    """
    计算全部回路的性能状态
    从数据库loop_info表中加载激活的回路列表

    Args:
        max_workers: 并行计算的最大线程数

    Returns:
        计算结果
    """
    try:
        logger.info("开始计算全部回路的性能状态...")

        # 从数据库加载所有激活的回路

        # 回路 URI 列表
        loop_uris = []
        # 回路URI -> 回路名称 映射
        loop_names = {}
        with get_db_session() as db:
            # 从 loop_info 表中加载所有激活的回路
            active_loops = LoopInfoDAO.get_active_loops(db)
            for loop in active_loops:
                loop_uris.append(loop.loop_uri)
                loop_names[loop.loop_uri] = loop.loop_name

        if not loop_uris:
            logger.warning("未获取到任何激活的回路")
            return {
                "status": "失败",
                "message": "未获取到任何激活的回路",
                "loop_count": 0
            }

        # 条件剔除回路不参与计算
        excluded_loop_uris = ExcludedLoopDAO.get_all_uris(db)

        logger.info(f"从数据库加载到{len(loop_uris)}个回路, {len(excluded_loop_uris)}个剔除回路, 开始计算性能状态...")

        # 批量计算性能状态
        result = LoopMonitoringService.calculate_performance_status_batch_by_time_range(
            loop_uris=loop_uris,
            start_time=start_time,
            end_time=end_time,
            max_workers=max_workers
        )

        # 将成功的评估结果写入回路评估明细表
        persisted_count = 0
        try:
            with get_db_session() as db:
                for item in result.get('results', []):
                    status = item.get('status')
                    # 将异常状态统一归类为未知状态
                    if status not in ['优', '良', '中', '差', '开环', '条件剔除', '未知']:
                        status = '未知'

                    loop_uri = item.get('loop_uri')
                    if isinstance(excluded_loop_uris, list) and loop_uri in excluded_loop_uris:
                        status = '条件剔除'

                    # 获取回路名称
                    loop_name = loop_names.get(loop_uri)

                    # 解析时间范围，计算总秒数
                    time_range = item.get('time_range') or {}
                    start_iso = time_range.get('start')
                    end_iso = time_range.get('end')
                    total_seconds = None
                    try:
                        if start_iso and end_iso:
                            start_dt = datetime.fromisoformat(start_iso)
                            end_dt = datetime.fromisoformat(end_iso)
                            total_seconds = int((end_dt - start_dt).total_seconds())
                    except Exception:
                        total_seconds = None

                    # 查询回路对应的PID参数
                    pid = LoopService.query_loop_values(["PB", "TI", "TD"], loop_uri)
                    pb = ti = td = None
                    if pid:
                        pb = pid.get("PB")
                        ti = pid.get("TI")
                        td = pid.get("TD")

                    metrics = item.get('performance_metrics') or {}
                    assessment_time = end_time.date()
                    evaluation_data = {
                        "loop_uri": loop_uri,
                        "loop_name": loop_name,
                        "status": status,
                        "assessment_time": assessment_time,
                        "performance_score": item.get('comprehensive_score'),
                        "auto_control_rate": metrics.get('auto_control_rate'),
                        "stability_rate": metrics.get('stability_rate'),
                        "auto_control_time": item.get('t_auto'),
                        "stable_time": item.get('t_stable'),
                        "total_time": total_seconds,
                        "pt_count": item.get('pt_count'),
                        "pv_sum_value": item.get("pv_sum_value"),
                        "pv_sum_squares": item.get("pv_sum_squares"),
                        "mv_sum_value": item.get("mv_sum_value"),
                        "mv_sum_squares": item.get("mv_sum_squares"),
                        "pb": pb,
                        "ti": ti,
                        "td": td,
                    }

                    try:
                        LoopEvaluationDAO.upsert_by_loop_uri_and_date(db, loop_uri, assessment_time, evaluation_data)
                        persisted_count += 1
                    except Exception as e:
                        logger.warning(f"写入评估明细失败 [{loop_uri}]: {str(e)}")
        except Exception as e:
            logger.error(f"写入评估结果到数据库失败: {str(e)}")

        # 附加写入统计到返回结果
        result["persisted_count"] = persisted_count

        logger.info(f"性能计算完成，成功: {result.get('summary', {}).get('successful_loops', 0)}, "
                    f"失败: {result.get('summary', {}).get('failed_loops', 0)}, "
                    f"写入: {persisted_count} "
                    )

        return result

    except Exception as e:
        logger.error(f"计算回路性能失败: {str(e)}")
        return {
            "status": "异常",
            "error": str(e)
        }