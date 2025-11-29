#!/usr/bin/env python3
"""
回路监控路由
回路监控的API接口
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException, Query

from api.services.loop_monitoring_service import LoopMonitoringService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/realtime-status",
    summary="查询回路实时状态",
    operation_id="查询回路实时状态",
    description="根据装置筛选、回路名称模糊查询、状态筛选条件查询回路实时状态列表"
)
async def get_loop_realtime_status(
        plant_uri: Optional[str] = Query(
            None,
            description="装置URI，用于筛选指定装置下的回路",
            example="/pid_zd/1f59615dc9d44b4388e29829f95a49c6"
        ),
        loop_name: Optional[str] = Query(
            None,
            description="回路名称模糊查询",
            example="TIC"
        ),
        status: Optional[str] = Query(
            None,
            description="状态筛选（自动/手动/异常）",
            example="自动"
        ),
        page_no: int = Query(
            1,
            description="页码",
            ge=1
        ),
        page_size: int = Query(
            20,
            description="每页数量",
            ge=1,
            le=100
        )
) -> Dict[str, Any]:
    """
    查询回路实时状态列表
    
    功能说明：
    - 支持装置筛选
    - 支持回路名称模糊查询
    - 支持状态筛选（自动/手动/异常）
    - 返回回路列表及实时数据
    """
    try:
        result = LoopMonitoringService.get_loop_realtime_status(
            plant_uri=plant_uri,
            loop_name=loop_name,
            status=status,
            page_no=page_no,
            page_size=page_size
        )
        
        return {
            "status": "success",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"查询回路实时状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路实时状态失败: {str(e)}"
        )


@router.get(
    "/trend-data",
    summary="查询回路趋势数据",
    operation_id="查询回路趋势数据",
    description="根据回路URI查询近1小时/4小时/12小时的趋势数据"
)
async def get_loop_trend_data(
        loop_uri: str = Query(
            ...,
            description="回路URI",
            example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
        ),
        time_range: int = Query(
            1,
            description="时间范围（小时），支持1/4/12",
            ge=1,
            le=12
        )
) -> Dict[str, Any]:
    """
    查询回路趋势数据
    
    功能说明：
    - 根据回路URI查询趋势数据
    - 支持不同时间范围（1小时/4小时/12小时）
    - 返回PV/SV/MV的历史数据用于绘制趋势图
    """
    try:
        # 计算时间范围
        end_time = int(datetime.now().timestamp() * 1000)
        start_time = end_time - time_range * 60 * 60 * 1000
        
        trend_data = LoopMonitoringService.get_loop_trend_data(
            loop_uri=loop_uri,
            start_time=start_time,
            end_time=end_time
        )
        
        return {
            "status": "success",
            "data": trend_data
        }
        
    except Exception as e:
        logger.error(f"查询回路趋势数据失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路趋势数据失败: {str(e)}"
        )


@router.get(
    "/performance-status",
    summary="查询回路性能状态",
    operation_id="查询回路性能状态",
    description="根据历史数据计算回路的性能等级，稳定性，精确性，高效性等指标"
)
async def get_performance_status_last_24h(
    loop_uri: str = Query(
        ...,
        description="回路 URI",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    )
) -> Dict[str, Any]:
    """
    查询回路过去24小时的性能状态
    
    功能说明：
    - 计算自控率（投入度维度）
    - 计算平稳率（稳定性维度）
    - 计算标准偏差（精确性维度）
    - 计算阀门活动度（高效性维度）
    - 上述指标的综合评分
    - 性能等级：优秀/良好/一般/差
    """
    try:
        result = LoopMonitoringService.calculate_performance_status(
            loop_uri=loop_uri
        )
        
        return {
            "status": "success",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"查询回路性能状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路性能状态失败: {str(e)}"
        )


@router.post(
    "/performance-status-batch-24h",
    summary="批量查询多个回路24小时性能状态（并行计算）",
    operation_id="批量查询回路24小时性能状态",
    description="批量查询多个回路的性能状态，使用线程池并行计算以提高效率"
)
async def get_performance_status_batch_24h(
    loop_uris: List[str] = Query(
        ...,
        description="回路 URI 列表",
        example=["/pid_zd/0b521c82a96d4107a564e4c2678bdeca", "/pid_zd/1b521c82a96d4107a564e4c2678bdecb"]
    ),
    max_workers: int = Query(
        5,
        description="并行计算的最大线程数",
        ge=1,
        le=20
    )
) -> Dict[str, Any]:
    """
    批量查询多个回路的24小时性能状态
    
    功能说明：
    - 支持同时查询多个回路的性能状态
    - 使用线程池并行计算，提高效率
    - 返回每个回路的详细性能指标
    - 提供汇总统计信息（平均评分、状态分布等）
    - 记录计算失败的回路详情
    """
    try:
        if not loop_uris:
            raise HTTPException(
                status_code=400,
                detail="回路 URI 列表不能为空"
            )
        
        result = LoopMonitoringService.calculate_performance_status_batch(
            loop_uris=loop_uris,
            max_workers=max_workers,
            data_span=24
        )
        
        return {
            "status": "success",
            "data": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量查询回路性能状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"批量查询回路性能状态失败: {str(e)}"
        )


@router.get(
    "/performance-status-by-plant-24h",
    summary="查询层级内所有回路24小时性能状态（并行计算）",
    operation_id="查询层级内回路24小时性能状态",
    description="查询指定层级内下所有回路的性能状态，自动获取层级内所有回路并并行计算"
)
async def get_performance_status_by_plant_24h(
    plant_uri: Optional[str] = Query(
        ...,
        description="层级URI",
        example="/pid_zd/1f59615dc9d44b4388e29829f95a49c6"
    ),
    max_workers: int = Query(
        5,
        description="并行计算的最大线程数",
        ge=1,
        le=20
    )
) -> Dict[str, Any]:
    """
    查询装置内所有回路的24小时性能状态
    
    功能说明：
    - 自动获取装置下的所有回路
    - 使用线程池并行计算所有回路的性能状态
    - 返回装置内所有回路的详细性能指标
    - 提供汇总统计信息（总数、成功率、平均评分等）
    - 记录计算失败的回路详情
    """
    try:
        result = LoopMonitoringService.calculate_performance_status_by_plant_24h(
            plant_uri=plant_uri,
            max_workers=max_workers
        )
        
        return {
            "status": "success",
            "data": result
        }
        
    except Exception as e:
        logger.error(f"查询装置回路性能状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询装置回路性能状态失败: {str(e)}"
        )

    #装置回路性能评估统计