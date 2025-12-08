# --------------
# 首页 API 接口
# --------------
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from api.response.loop_response import DeviceRealTimeStats, PerfReductionLoop, \
    OptimizableLoopsWithPagination
from api.services.home_page_service import HomePageService
from core.config import Config
from core.database.database import get_db

home_page_router = APIRouter(tags=["首页"])


# @home_page_router.get("/perf-stats", summary="获取综合性能统计结果")
# async def get_perf_stats(session: Session = Depends(get_db)) -> Dict[str, int]:
#     results = HomePageService.get_perf_stats(session)
#     if not results or len(results) == 0:
#         return None
#
#     data = {}
#     for item in results:
#         data[item[0]] = item[1]
#     return data

@home_page_router.get("/perf-stats", summary="获取综合性能统计结果")
async def get_perf_stats(
        session: Session = Depends(get_db),
        device_uri: Optional[str] = Query(None, description="装置uri")
) -> Dict[str, int]:
    if device_uri:
        device_uri=Config.BFF_MODEL_ROOT_URI
    results = HomePageService.get_perf_stats(session, device_uri)
    if not results or len(results) == 0:
        return None

    data = {}
    for item in results:
        data[item[0]] = item[1]
    return data
@home_page_router.get("/device-stats", summary="获取装置实时统计结果")
async def get_device_stats(session: Session = Depends(get_db)) -> List[DeviceRealTimeStats]:
    results = HomePageService.get_device_stats(session)
    if not results or len(results) == 0:
        return []
    return results


@home_page_router.get("/perf-reduction-top10-loops", summary="获取性能下降Top10的回路")
async def get_perf_reduction_top10_loops(session: Session = Depends(get_db)) -> List[PerfReductionLoop]:
    results = HomePageService.get_perf_reduction_top10_loops(session)
    if not results or len(results) == 0:
        return []
    return results


@home_page_router.get("/optimizable-loops", summary="获取可优化的回路")
async def get_optimizable_loops(page_no: int = Query(1, description="页码，从1开始"),
                                page_size: int = Query(10, description="每页数量"),
                                session: Session = Depends(get_db)) -> OptimizableLoopsWithPagination:
    return HomePageService.get_optimizable_loops(session, page_no, page_size)
