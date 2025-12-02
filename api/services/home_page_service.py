from datetime import datetime, date
from typing import List

from sqlmodel import Session

from api.dao.home_page_dao import HomePageDAO
from api.response.loop_response import OptimizableLoop
from api.services.loop_service import LoopService
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
    def get_device_stats(session: Session):
        """
        Get device statistics
        """
        pass

    @staticmethod
    def get_perf_reduction_top10_loops(session: Session):
        """
        Get top 10 performance reduction loops
        """
        pass

    @staticmethod
    def get_optimizable_loops(session: Session, page_no: int = 1, page_size: int = 10) -> List[OptimizableLoop]:
        """
        Get optimizable loops
        """
        query_date = date.today()
        offset = (page_no - 1) * page_size
        limit = page_size
        return HomePageDAO.get_optimizable_loops(session, query_date, offset, limit)

if __name__ == '__main__':
    results = HomePageService.get_perf_stats(create_db_session())
    print(results)

    results = HomePageService.get_optimizable_loops(create_db_session(), page_no=1, page_size=10)
    for result in results:
        print(result)

    # pid = LoopService.query_loop_values(["PB", "TI", "TD"], "/pid_zd/e7fd8af67d3d472ba6c8478eeb692af6")
    # print(pid)