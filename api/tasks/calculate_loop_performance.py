import logging
from datetime import datetime

from api.services.loop_monitoring_service import LoopMonitoringService
from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO
from api.dao.loop_evaluation_dao import LoopEvaluationDAO

logger = logging.getLogger(__name__)

def calculate_loop_performance(max_workers: int = 5) -> dict:
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
        with get_db_session() as db:
            active_loops = LoopInfoDAO.get_all_active(db)
            loop_uris = [loop.loop_uri for loop in active_loops if loop.loop_uri]


        if not loop_uris:
            logger.warning("未获取到任何激活的回路")
            return {
                "status": "失败",
                "message": "未获取到任何激活的回路",
                "loop_count": 0
            }

        logger.info(f"从数据库加载到 {len(loop_uris)} 个激活回路，开始计算性能状态...")

        # 批量计算性能状态
        result = LoopMonitoringService.calculate_performance_status_batch(
            loop_uris=loop_uris,
            max_workers=max_workers
        )

        # 将成功的评估结果写入回路评估明细表
        persisted_count = 0
        try:
            with get_db_session() as db:
                for item in result.get('results', []):
                    status = item.get('status')
                    loop_uri = item.get('loop_uri')
                    # if status not in ['优秀', '良好', '一般', '差']:
                    #     # 跳过失败或异常结果
                    #     continue

                    # 获取回路名称
                    mapping = LoopInfoDAO.get_by_loop_uri(db, loop_uri, include_inactive=True)
                    loop_name = mapping.loop_name if mapping else None

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

                    metrics = item.get('performance_metrics') or {}

                    evaluation_data = {
                        "loop_uri": loop_uri,
                        "loop_name": loop_name,
                        "tuning_method": "PerformanceEvaluation",
                        "tuning_time": datetime.now(),
                        "status": status,
                        "performance_score": item.get('comprehensive_score'),
                        "auto_control_rate": metrics.get('auto_control_rate'),
                        "stability_rate": metrics.get('stability_rate'),
                        "total_time": total_seconds,
                        "pt_count": item.get('data_points_count'),
                        "tuning_details": item  # 保存完整评估明细
                    }

                    try:
                        LoopEvaluationDAO.create(db, evaluation_data)
                        persisted_count += 1
                    except Exception as e:
                        logger.warning(f"写入评估明细失败 [{loop_uri}]: {str(e)}")
        except Exception as e:
            logger.error(f"写入评估结果到数据库失败: {str(e)}")

        # 附加写入统计到返回结果
        result["persisted_count"] = persisted_count

        logger.info(f"性能计算完成，成功: {result.get('summary', {}).get('successful_loops', 0)}, "
                    f"失败: {result.get('summary', {}).get('failed_loops', 0)}, "
                    f"写入: {persisted_count}")

        return result

    except Exception as e:
        logger.error(f"计算回路性能失败: {str(e)}")
        return {
            "status": "异常",
            "error": str(e)
        }
