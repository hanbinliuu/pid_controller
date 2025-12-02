from datetime import datetime

from sqlmodel import Session

from api.dao.home_page_dao import HomePageDAO


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
    def get_optimizable_loops(session: Session, page_no: int = 1, page_size: int = 10):
        """
        Get optimizable loops
        """
        pass