from datetime import datetime, date
from typing import List

from sqlmodel import Session

from api.dao.home_page_dao import HomePageDAO
from api.response.loop_response import PerfReductionLoop, DeviceRealTimeStats, \
    OptimizableLoopsWithPagination, Pagination
from api.services.device_evaluation_service import DeviceEvaluationService
from core.config import Config
from core.database.database import create_db_session


class HomePageService:
    """
    Home page service
    """

    @staticmethod
    def get_perf_stats(session: Session):
        """
        Get performance statistics
        """
        now = datetime.now().date()
        return HomePageDAO.get_perf_stats(session, now)

    @staticmethod
    def get_device_stats(session: Session,device_uri: str=None) -> List[DeviceRealTimeStats]:
        """
        Get device statistics
        """
        results = []
        if device_uri is None:
            device_uri = Config.BFF_MODEL_ROOT_URI
        root_result = DeviceEvaluationService.get_evaluation_by_device_uri_now(session, device_uri)
        if root_result is not None:
            results.append(
                DeviceRealTimeStats(
                    device_uri=root_result.device_uri,
                    parent_device_uri=root_result.parent_device_uri,
                    group_name=root_result.device_name,
                    loop_count=root_result.loop_count,
                    auto_control_rate=root_result.auto_control_rate,
                    stability_rate=root_result.stability_rate
                )
            )

        child_results = DeviceEvaluationService.get_evaluation_by_parent_device_uri_now(session, device_uri)
        for child_result in child_results:
            results.append(
                DeviceRealTimeStats(
                    device_uri=child_result.device_uri,
                    parent_device_uri=child_result.parent_device_uri,
                    group_name=child_result.device_name,
                    loop_count=child_result.loop_count,
                    auto_control_rate=child_result.auto_control_rate,
                    stability_rate=child_result.stability_rate
                )
            )
        return results

    @staticmethod
    def get_perf_reduction_top10_loops(session: Session) -> List[PerfReductionLoop]:
        """
        Get top 10 performance reduction loops
        """
        now = datetime.now().date()
        return HomePageDAO.get_perf_reduction_top10_loops(session, now, 1)

    @staticmethod
    def get_optimizable_loops(
            session: Session,
            page_no: int = 1,
            page_size: int = 10) -> OptimizableLoopsWithPagination:
        """
        Get optimizable loops
        """
        query_date = date.today()
        offset = (page_no - 1) * page_size
        limit = page_size
        results = HomePageDAO.get_optimizable_loops(session, query_date, offset, limit)
        if results[0]:
            total = results[1]
            pages = (total + page_size - 1) // page_size if total > 0 else 0
            return OptimizableLoopsWithPagination(
                loops=results[0],
                pagination=Pagination(
                    pageNo=page_no,
                    pageSize=page_size,
                    total=total,
                    pages=pages
                )
            )
        else:
            return OptimizableLoopsWithPagination(
                loops=[],
                pagination=Pagination(
                    pageNo=page_no,
                    pageSize=page_size,
                    total=0,
                    pages=0
                )
            )


if __name__ == '__main__':
    # results = HomePageService.get_perf_stats(create_db_session())
    # print(results)
    #
    results = HomePageService.get_optimizable_loops(create_db_session(), page_no=1, page_size=10)
    print(results)

    # pid = LoopService.query_loop_values(["PB", "TI", "TD"], "/pid_zd/e7fd8af67d3d472ba6c8478eeb692af6")
    # print(pid)

    # results = HomePageService.get_perf_reduction_top10_loops(create_db_session())
    # for result in results:
    #     print(result)

    # results = HomePageService.get_device_stats(create_db_session())
    # for result in results:
    #     print(result)
    pass