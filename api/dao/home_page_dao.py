import logging
from datetime import date
from operator import or_
from typing import List

from sqlmodel import Session, select, func

from api.bean.loop_evaluation import LoopEvaluation
from api.bean.loop_info import LoopInfo
from api.response.loop_response import OptimizableLoop

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
        stmt = select(
            LoopEvaluation.status,
            func.count(LoopEvaluation.id).label("count")
        ).where(LoopEvaluation.assessment_time == query_date).group_by(LoopEvaluation.status)
        return session.exec(stmt).all()

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
    def get_optimizable_loops(session: Session, query_date: date, offset: int, limit: int) -> List[OptimizableLoop]:
        """
        Get optimizable loops
        """
        # 查询需要整定的回路
        # todo: 80, 90 这两个阈值需要从配置文件中获取
        stmt = select(
            LoopEvaluation.loop_uri,
            LoopEvaluation.loop_name,
            LoopEvaluation.performance_score,
            LoopEvaluation.pb,
            LoopEvaluation.ti,
            LoopEvaluation.td
        ).where(
            LoopEvaluation.assessment_time == query_date,
            LoopEvaluation.status != "开环",
            LoopEvaluation.status != "条件剔除"
        ).where(
            or_(
                LoopEvaluation.performance_score < 80,
                LoopEvaluation.stability_rate < 90
            )
        ).offset(offset).limit(limit).order_by(LoopEvaluation.id)

        selected_loops = session.exec(stmt).all()
        if not isinstance(selected_loops, list) or len(selected_loops) == 0:
            return []

        # 查询回路信息
        optimizable_loops = {}
        for item in selected_loops:
            optimizable_loops[item[0]] = OptimizableLoop(
                loop_uri=item[0],
                loop_name=item[1],
                performance_score=item[2],
                current_pid=f"{item[3]}/{item[4]}/{item[5]}",
            )
        stmt = select(LoopInfo).where(LoopInfo.loop_uri.in_(optimizable_loops.keys()))
        loop_infos = session.exec(stmt).all()

        results = []
        for loop_info in loop_infos:
            loop_uri = loop_info.loop_uri
            optimizable_loop = optimizable_loops[loop_uri]
            if optimizable_loop is None:
                continue
            optimizable_loop.loop_type = loop_info.loop_type
            optimizable_loop.loop_desc = loop_info.description
            results.append(optimizable_loop)
        return results