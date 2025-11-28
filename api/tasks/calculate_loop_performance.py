import logging

from api.services.loop_monitoring_service import LoopMonitoringService

logger = logging.getLogger(__name__)

def calculate_loop_performance(max_workers: int = 5) -> dict:
    """
    计算全部回路的性能状态

    Args:
        max_workers: 并行计算的最大线程数

    Returns:
        计算结果
    """
    try:
        logger.info("开始计算全部回路的性能状态...")

        # 使用BFF客户端获取所有回路
        from core.data.bff_model_client import BFFModelClient

        with BFFModelClient() as client:
            model_identifier_list = ['/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243']

            result = client.list_instances_under_tree(
                model_identifier_list=model_identifier_list,
                start_identifier_list=[],
                contain_sub_model=True,
                page_no=1,
                page_size=1000
            )

            instances = result.get('instances', [])
            loop_uris = [instance.get('uri') for instance in instances if instance.get('uri')]

        if not loop_uris:
            logger.warning("未获取到任何回路")
            return {
                "status": "失败",
                "message": "未获取到任何回路",
                "loop_count": 0
            }

        logger.info(f"获取到 {len(loop_uris)} 个回路，开始计算性能状态...")

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
