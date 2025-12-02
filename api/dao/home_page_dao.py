import logging
from datetime import date
from typing import List

from sqlmodel import Session, select, func

from api.bean.loop_evaluation import LoopEvaluation
from core.database.database import create_db_session

logger = logging.getLogger(__name__)


class HomePageDAO:
    """
    Home page service
    """

    @staticmethod
    def get_perf_stats(session: Session, query_date: date):
        """
        Get performance statistics
        """
        print(query_date)
        stmt = select(
            LoopEvaluation.status,
            func.count(LoopEvaluation.id).label("count")
        ).where(LoopEvaluation.assessment_time == query_date).group_by(LoopEvaluation.status)
        return session.exec(stmt).all()


if __name__ == '__main__':
    results = HomePageDAO.get_perf_stats(create_db_session(), query_date=date.today())
    print(results)
    pass