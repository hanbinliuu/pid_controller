import logging
from datetime import date, timedelta
from operator import or_
from typing import List

from sqlmodel import Session, select, func,desc

from api.bean.loop_evaluation import LoopEvaluation
from api.bean.loop_info import LoopInfo
from api.response.loop_response import OptimizableLoop, PerfReductionLoop
from core.global_constants import LOOP_PERFORMANCE_THRESHOLD, LOOP_STABILITY_THRESHOLD

logger = logging.getLogger(__name__)


class HomePageDAO:
    """
    Home page service
    """

    @staticmethod
    def get_perf_stats(session: Session, query_date: date, device_uri: str):
        """
        Get performance statistics
        """
        stmt = select(
            LoopEvaluation.status,
            func.count(LoopEvaluation.id).label("count")
        ).join(
            LoopInfo, LoopEvaluation.loop_uri == LoopInfo.loop_uri
        ).where(
            LoopEvaluation.assessment_time == query_date,

        )
        if device_uri is not None:
            stmt=stmt.where(LoopInfo.loop_path.like(f"%{device_uri}%"))
        stmt=stmt.group_by(LoopEvaluation.status)
        return session.exec(stmt).all()

    @staticmethod
    def get_perf_reduction_top10_loops(
            session: Session,
            query_date: date,
            days_limit: int = 1) -> List[PerfReductionLoop]:
        """
        Get top 10 performance reduction loops
        """
        # 查询回路过去 days_limit 天的综合评分平均值
        start_date = query_date - timedelta(days=days_limit)
        stmt = (select(
            LoopEvaluation.loop_uri,
            func.avg(LoopEvaluation.performance_score).label("avg_perf_score")
        ).where(
            LoopEvaluation.assessment_time >= start_date,
            LoopEvaluation.assessment_time < query_date,
            LoopEvaluation.status != "开环",
            LoopEvaluation.status != "条件剔除"
        ).group_by(LoopEvaluation.loop_uri)
                .order_by(desc('avg_perf_score')))
        results = session.exec(stmt).all()
        prev_avg_scores = {}
        for item in results:
            prev_avg_scores[item[0]] = item[1]

        # 查询回路当天的综合评分
        stmt = select(
            LoopEvaluation.loop_uri,
            LoopEvaluation.performance_score,
        ).where(
            LoopEvaluation.assessment_time == query_date,
            LoopEvaluation.status != "开环",
            LoopEvaluation.status != "条件剔除"
        )
        results = session.exec(stmt).all()

        scores = []
        for item in results:
            if item[0] not in prev_avg_scores:
                continue
            prev_score = prev_avg_scores[item[0]]
            if not prev_score:
                continue
            delta = prev_score - item[1]
            if delta > 0:
                scores.append((item[0], round(delta / item[1] * 100, 2), item[1]))

        if len(scores) == 0:
            return []

        new_scores = sorted(scores, key=lambda x: x[1], reverse=True)[:10]
        pert_reduction_loops = {}
        for item in new_scores:
            pert_reduction_loops[item[0]] = PerfReductionLoop(
                loop_uri=item[0],
                performance_score=item[2],
                reduction_rate=item[1]
            )
        # 查询回路信息
        stmt = select(LoopInfo).where(LoopInfo.loop_uri.in_([item[0] for item in new_scores]))
        loop_infos = session.exec(stmt).all()

        results = []
        for loop_info in loop_infos:
            loop_uri = loop_info.loop_uri
            if loop_uri not in pert_reduction_loops:
                continue
            pert_reduction_loop = pert_reduction_loops[loop_uri]
            if pert_reduction_loop is None:
                continue
            pert_reduction_loop.loop_name = loop_info.loop_name
            pert_reduction_loop.loop_desc = loop_info.description
            pert_reduction_loop.loop_type = loop_info.loop_type
            results.append(pert_reduction_loop)
        return results

    @staticmethod
    def get_optimizable_loops(
            session: Session,
            query_date: date,
            offset: int,
            limit: int) -> (List[OptimizableLoop], int):
        """
        Get optimizable loops
        """
        # 查询需要整定回路总数
        stmt = select(func.count()).where(
            LoopEvaluation.assessment_time == query_date,
            LoopEvaluation.status != "开环",
            LoopEvaluation.status != "条件剔除"
        ).where(
            or_(
                LoopEvaluation.performance_score < LOOP_PERFORMANCE_THRESHOLD,
                LoopEvaluation.stability_rate < LOOP_STABILITY_THRESHOLD
            )
        )
        total = session.exec(stmt).one()
        if total <= 0:
            return [], total

        # 查询需要整定的回路
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
                LoopEvaluation.performance_score < LOOP_PERFORMANCE_THRESHOLD,
                LoopEvaluation.stability_rate < LOOP_STABILITY_THRESHOLD
            )
        ).offset(offset).limit(limit).order_by(LoopEvaluation.id)

        selected_loops = session.exec(stmt).all()
        if not isinstance(selected_loops, list) or len(selected_loops) == 0:
            return [], total

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
            if loop_uri not in optimizable_loops:
                continue
            optimizable_loop = optimizable_loops[loop_uri]
            if optimizable_loop is None:
                continue
            optimizable_loop.loop_type = loop_info.loop_type
            optimizable_loop.loop_desc = loop_info.description
            results.append(optimizable_loop)
        return results, total