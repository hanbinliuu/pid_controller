import logging

from api.services.loop_monitoring_service import LoopMonitoringService
from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO

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

        logger.info(f"性能计算完成，成功: {result.get('summary', {}).get('successful_loops', 0)}, "
                    f"失败: {result.get('summary', {}).get('failed_loops', 0)}")

        return result

    except Exception as e:
        logger.error(f"计算回路性能失败: {str(e)}")
        return {
            "status": "异常",
            "error": str(e)
        }
