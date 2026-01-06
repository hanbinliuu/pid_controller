#!/usr/bin/env python3
"""
回路管理路由
回路管理相关的API接口
"""


import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, Any, List, Union
from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File
from sqlmodel import Session

from api.response.loop_response import LoopListResponse, LoopInfoResponse
from api.response.bff_response import SubmodelListResponse
from api.services.loop_info_service import LoopInfoService
from api.services.loop_service import LoopService
from api.services.loop_import_service import LoopImportService
from core.config import Config
from pydantic import BaseModel, Field

from core.database import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


class PointValuesRequest(BaseModel):
    """测点值查询请求模型"""
    point_names: List[str] = Field(..., description="测点名称列表")
    loop_uri: Optional[str] = Query(
        None,
        description="回路 URI，默认从 BFF_MODEL_LOOP_URI 读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
    )
    class Config:
        json_schema_extra = {
            "example": {
                "point_names": ["PB", "TI", "TD", "PV", "SV", "MV"],
                "loop_uri": "/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
            }
        }


class InstantiateLoopRequest(BaseModel):
    """回路实例化请求模型"""
    loop_type: str = Field(..., description="回路类型，如：流量、温度、压力等")
    loop_display_name: str = Field(..., description="回路显示名称")
    loop_browse_name: str = Field(..., description="回路标识（唯一）")
    
    class Config:
        json_schema_extra = {
            "example": {
                "loop_type": "流量",
                "loop_display_name": "FIC101A流量控制回路",
                "loop_browse_name": "FIC101A"
            }
        }


class LoopValuesResponse(BaseModel):
    """回路测点值响应模型"""
    PB: Optional[float] = Field(None, description="比例带")
    TI: Optional[float] = Field(None, description="积分时间")
    TD: Optional[float] = Field(None, description="微分时间")
    PV: Optional[float] = Field(None, description="过程值")
    SV: Optional[float] = Field(None, description="设定值")
    MV: Optional[float] = Field(None, description="阀位值")
    
    class Config:
        json_schema_extra = {
            "example": {
                "PB": 71.43,
                "TI": 3.11,
                "TD": 2.0,
                "PV": 10.0,
                "SV": 10.0,
                "MV": 15.979299
            }
        }


@router.post(
    "/list-loop",
    summary="查询对应节点下的回路列表-bff",
    operation_id="查询对应节点下的回路列表",
    description="根据回路类型URI和起始节点URI查询节点下的回路列表，支持分页",
    response_model=LoopListResponse
)
async def list_instances_by_uri(
        node_uri: str = Query(
            None,
            description="起始节点URI",
            examples=[Config.BFF_MODEL_ROOT_URI]
        ),
        type_uri: str = Query(
            None,
            description="类型uri",
        ),
        page_no: int = Query(
            1,
            description="页码",
            ge=1
        ),
        page_size: int = Query(
            10,
            description="每页数量",
            ge=1,
            le=100
        )
) -> LoopListResponse:
    """
    查询实例树下的实例列表

    功能说明：
    - 根据模型标识符和起始标识符查询实例树
    - 支持分页查询
    - 返回简化后的实例信息
    - 自动查询每个回路的PID参数最新值 (PB, TI, TD)

    返回格式：参考 LoopListResponse 模型
    """
    try:
        if node_uri is None:
            node_uri = [Config.BFF_MODEL_ROOT_URI]
        else:
            node_uri = [node_uri]
        if type_uri is None:
            type_uri = [Config.BFF_MODEL_LOOP_MODEL_URI]
        else:
            type_uri = [type_uri]

        # 调用Service层查询回路列表
        result = LoopService.list_instances_by_node(
            model_identifier_list=type_uri,
            start_identifier_list=node_uri,
            # name=name,
            page_no=page_no,
            page_size=page_size
        )



        return result

    except Exception as e:
        logger.error(f"查询实例树失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询实例树失败: {str(e)}"
        )

@router.post(
    "/loop-info",
    summary="查询回路属性",
    operation_id="查询回路属性",
    description="根据回路URI查询回路的详细属性信息，包括回路名称、类型、自控情况、正反作用等",
    response_model=LoopInfoResponse
)
async def query_loop_info(
        loop_uri: Optional[str] = Query(
            ...,
            description="回路 URI",
            example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca"
        )
) -> LoopInfoResponse:
    """
    查询回路详细属性
    
    功能说明：
    - 查询回路的基本信息（名称、类型、描述等）
    - 查询回路的控制参数（自控情况、正反作用）
    - 查询回路的量程信息（目标值量程、阀位值量程）
    
    返回格式：参考 LoopInfoResponse 模型
    """
    try:
        # 调用Service层查询回路信息
        result = LoopService.query_loop_info(loop_uri=loop_uri)
        
        return result
    
    except Exception as e:
        logger.error(f"查询回路属性失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路属性失败: {str(e)}"
        )

@router.post(
    "/loop-values",
    summary="查询回路测点当前最新值",
    description="根据回路 URI 和测点名称查询测点的当前最新值",
    response_model=Dict[str, Any]
)
async def query_loop_values(
    point_names: List[str] = Query(..., description="测点名称列表", example=["PB", "TI", "TD", "PV", "SV", "MV"]),
    loop_uri: Optional[str] = Query(
        None,
        description="回路 URI，默认从 BFF_MODEL_LOOP_URI 读取",
        example="/pid_zd/0b521c82a96d4107a564e4c2678bdeca")
) -> Dict[str, Any]:
    """
    查询测点当前原始值

    功能说明：
    - 提供公共的 loop_uri 和 point_path，只需传入测点名称列表
    - 自动拼接完整的浏览路径
    - 返回测点名称到值的映射
    - 只返回v值（数值）

    请求体示例：
    [
        "PB",
        "TI",
        "TD",
        "PV",
        "SV",
        "MV"
    ]

    返回格式：
    {
        "PB": 71.43,
        "TI": 3.11,
        "TD": 2,
        "PV": 10,
        "SV": 10,
        "MV": 15.979299
    }
    """
    try:
        # 调用Service层查询回路测点值
        result = LoopService.query_loop_values(
            point_names=point_names,
            loop_uri=loop_uri
        )

        logger.info(f"查询成功，测点数量: {len(result)}")

        return result

    except Exception as e:
        logger.error(f"查询测点当前值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点当前值失败: {str(e)}"
        )
@router.post(
    "/loop-values-new",
    summary="查询回路测点当前最新值-new",
    description="根据回路 URI 和测点名称查询测点的当前最新值",
    response_model=Dict[str, Any]
)
async def query_loop_values_new(
        request: PointValuesRequest,
) -> Dict[str, Any]:
    """
    查询测点当前原始值

    功能说明：
    - 提供公共的 loop_uri 和 point_path，只需传入测点名称列表
    - 自动拼接完整的浏览路径
    - 返回测点名称到值的映射
    - 只返回v值（数值）
    """
    try:
        # 调用Service层查询回路测点值
        result = LoopService.query_loop_values(
            point_names=request.point_names,
            loop_uri=request.loop_uri
        )

        logger.info(f"查询成功，测点数量: {len(result)}")

        return result

    except Exception as e:
        logger.error(f"查询测点当前值失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询测点当前值失败: {str(e)}"
        )

@router.get(
    "/next-loop-type",
    summary="获取回路类型",
    operation_id="获取回路类型",
    description="根据模型标识符获取子回路列表",
    response_model=SubmodelListResponse
)
async def get_next_loop_type(
        identifier: str = Query(
            ...,
            description="模型标识符，URI路径",
            example="/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"
        )
) -> Dict[str, Any]:
    """
    获取下一级子模型

    功能说明：
    - 查询指定模型标识符下的所有子模型
    - 返回简化后的模型信息

    返回格式：
    {
        "submodels": [
            {
                "uri": "/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1",
                "browseName": "flow_loop_model",
                "displayName": "流量单回路模型",
                "extendedAttr": {"loop_type": "流量"},
                "parentUri": "/pid_zd/d4d2d8c4906846818c91e4fe06a290a2"
            }
        ],
        "total": 1
    }
    """
    try:
        # 调用Service层获取下一级子模型
        result = LoopService.get_next_loop_type(identifier=identifier)

        logger.info(f"子类型查询成功: {identifier}, 回路类型数量: {result.get('total', 0)}")

        return result

    except Exception as e:
        logger.error(f"回路子类型查询失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询回路子类型失败: {str(e)}"
        )


@router.post(
    "/instantiate-loop",
    summary="实例化回路",
    operation_id="实例化回路",
    description="根据回路类型创建回路实例，支持批量实例化",
    response_model=Dict[str, Any]
)
async def instantiate_loop(
        request: Union[List[InstantiateLoopRequest]],
        parent_uri: str = Query(
            ...,
            description="父节点URI（必填，所有回路在同一装置下创建）",
            example=Config.BFF_MODEL_ROOT_URI
        ),
        max_workers: int = Query(
            5,
            description="批量实例化的最大线程数（仅批量生效）",
            ge=1,
            le=20
        )
) -> Dict[str, Any]:
    """
    实例化回路
    
    功能说明：
    - 根据回路类型（流量、温度等）创建回路实例
    - 在指定的父节点（装置）下创建回路
    - 返回创建结果和新回路的URI
    - 支持批量实例化（请求体为数组）
    
    请求参数：
    - loop_type: 回路类型，如"流量"、"温度"、"压力"等
    - loop_display_name: 回路的显示名称
    - loop_browse_name: 回路的浏览名称（唯一标识）
    - parent_uri: 父节点URI（必填，通常是装置URI，通过公共参数传入）
    - max_workers: 批量实例化线程数（仅批量生效）

    批量请求示例：
    [
        {
            "loop_type": "温度",
            "loop_display_name": "聚合反应器床层温度控制回路",
            "loop_browse_name": "TIC-108"
        },
        {
            "loop_type": "流量",
            "loop_display_name": "醚化反应原料醇烯比调节回路",
            "loop_browse_name": "FIC-215"
        }
    ]
    
    返回格式：
    {
        "success": true,
        "message": "操作成功",
        "data": {
            "loop_uri": "/pid_zd/xxx",
            "loop_type": "流量",
            "loop_displayName": "FIC101A流量控制回路",
            "loop_browseName": "FIC101A"
        },
        "code": 0
    }

    批量返回说明：
    - data.total / data.success_count / data.failed_count
    - data.items: 每个回路的执行结果
    """
    try:
        def build_result(loop_request: InstantiateLoopRequest) -> Dict[str, Any]:
            try:
                result = LoopService().instantiate_loop(
                    loop_type=loop_request.loop_type,
                    loop_displayName=loop_request.loop_display_name,
                    loop_browseName=loop_request.loop_browse_name,
                    parent_uri=parent_uri
                )

                if result.get("success"):
                    logger.info(
                        "回路实例化成功: 类型=%s, 名称=%s, URI=%s",
                        loop_request.loop_type,
                        loop_request.loop_display_name,
                        result.get('data', {}).get('loop_uri')
                    )
                else:
                    logger.error(
                        "回路实例化失败: 类型=%s, 名称=%s, 原因=%s",
                        loop_request.loop_type,
                        loop_request.loop_display_name,
                        result.get('message')
                    )
                return {
                    "loop_type": loop_request.loop_type,
                    "loop_display_name": loop_request.loop_display_name,
                    "loop_browse_name": loop_request.loop_browse_name,
                    "parent_uri": parent_uri,
                    "success": result.get("success", False),
                    "code": result.get("code"),
                    "message": result.get("message"),
                    "data": result.get("data")
                }
            except Exception as exc:
                logger.error(
                    "回路实例化异常: 类型=%s, 名称=%s, 错误=%s",
                    loop_request.loop_type,
                    loop_request.loop_display_name,
                    str(exc)
                )
                return {
                    "loop_type": loop_request.loop_type,
                    "loop_display_name": loop_request.loop_display_name,
                    "loop_browse_name": loop_request.loop_browse_name,
                    "parent_uri": parent_uri,
                    "success": False,
                    "code": 500,
                    "message": str(exc),
                    "data": None
                }

        if isinstance(request, list):
            if not request:
                raise HTTPException(
                    status_code=400,
                    detail="回路列表不能为空"
                )
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                results = list(executor.map(build_result, request))
            success_count = sum(1 for item in results if item.get("success"))
            failed_count = len(results) - success_count
            return {
                "success": failed_count == 0,
                "message": "批量实例化完成",
                "data": {
                    "total": len(results),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "items": results
                },
                "code": 0 if failed_count == 0 else -1
            }

        result = LoopService().instantiate_loop(
            loop_type=request.loop_type,
            loop_displayName=request.loop_display_name,
            loop_browseName=request.loop_browse_name,
            parent_uri=parent_uri
        )

        if result.get("success"):
            logger.info(
                f"回路实例化成功: 类型={request.loop_type}, "
                f"名称={request.loop_display_name}, "
                f"URI={result.get('data', {}).get('loop_uri')}"
            )
        else:
            logger.error(f"回路实例化失败: {result.get('message')}")

        return result
    
    except Exception as e:
        logger.error(f"回路实例化失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"回路实例化失败: {str(e)}"
        )


@router.post(
    "/batch-import",
    summary="批量导入回路（CSV）",
    operation_id="批量导入回路",
    description="通过上传CSV文件批量导入回路，支持异步多线程处理",
    response_model=Dict[str, Any]
)
async def batch_import_loops(
        file: UploadFile = File(..., description="CSV文件"),
        max_workers: int = Query(5, description="最大线程数", ge=1, le=20),
        parent_uri: str = Query(..., description="父节点URI（必填）")
) -> Dict[str, Any]:
    """
    批量导入回路（CSV文件）
    
    功能说明：
    - 上传CSV文件进行批量导入
    - 支持异步多线程处理，提高导入效率
    - 返回任务ID，可通过任务ID查询导入进度
    
    必填参数：
    - parent_uri: 父节点URI（必填，通常是装置URI）
    
    CSV文件格式（中文表头）：
    ```csv
    回路标识,回路名称,回路类型
    TIC-108,聚合反应器床层温度控制回路,温度
    FIC-215,醚化反应原料醇烯比调节回路,流量
    PIC-309,催化蒸馏塔塔顶压力控制回路,压力
    ```
    
    必填字段：
    - loop_type: 回路类型
    - loop_display_name: 回路显示名称
    - loop_browse_name: 回路标识（唯一）
    
    可选字段：
    - parent_uri: 父节点URI（CSV中的值可覆盖接口参数）
    - description: 回路描述
    
    返回格式：
    {
        "task_id": "uuid-string",
        "message": "导入任务已启动，请使用task_id查询进度",
        "total_count": 100,
        "file_name": "loops.csv"
    }
    """
    try:
        # 验证文件类型
        if not file.filename.endswith('.csv'):
            raise HTTPException(
                status_code=400,
                detail="只支持CSV文件格式"
            )
        
        # 读取文件内容
        content = await file.read()
        csv_content = content.decode('utf-8-sig')  # 支持BOM
        
        # 启动导入任务（传递文件名和父节点URI）
        task_id = LoopImportService.start_import_task(
            csv_content=csv_content,
            file_name=file.filename,
            parent_uri=parent_uri,
            max_workers=max_workers
        )
        
        # 获取任务状态
        task_status = LoopImportService.get_task_status(task_id)
        
        logger.info(f"批量导入任务已启动: {task_id}, 总计: {task_status.get('total_count')} 个回路, 文件: {file.filename}")
        
        return {
            "task_id": task_id,
            "message": "导入任务已启动，请使用task_id查询进度",
            "total_count": task_status.get('total_count'),
            "file_name": file.filename
        }
    
    except ValueError as e:
        logger.error(f"CSV解析失败: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"批量导入失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"批量导入失败: {str(e)}"
        )


@router.get(
    "/import-task/{task_id}",
    summary="查询导入任务状态",
    operation_id="查询导入任务状态",
    description="根据任务ID查询批量导入任务的进度和状态",
    response_model=Dict[str, Any]
)
async def get_import_task_status(
        task_id: str
) -> Dict[str, Any]:
    """
    查询导入任务状态
    
    功能说明：
    - 查询任务的实时进度
    - 返回成功、失败数量统计
    - 返回最近10条错误信息
    
    返回格式：
    {
        "task_id": "uuid-string",
        "status": "running",  # pending/running/completed/failed
        "total_count": 100,
        "success_count": 80,
        "failed_count": 20,
        "current_index": 100,
        "progress_percentage": 100.0,
        "error_messages": [
            {
                "row_number": 5,
                "loop_name": "FIC101A",
                "error": "错误信息"
            }
        ],
        "start_time": "2024-01-01T12:00:00",
        "end_time": "2024-01-01T12:05:00"
    }
    """
    try:
        task_status = LoopImportService.get_task_status(task_id)
        
        if not task_status:
            raise HTTPException(
                status_code=404,
                detail=f"任务不存在: {task_id}"
            )
        
        return task_status
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询任务状态失败: {str(e)}"
        )


@router.get(
    "/import-tasks",
    summary="查询所有导入任务",
    operation_id="查询所有导入任务",
    description="查询所有批量导入任务的状态列表",
    response_model=List[Dict[str, Any]]
)
async def get_all_import_tasks() -> List[Dict[str, Any]]:
    """
    查询所有导入任务
    
    功能说明：
    - 返回所有任务的状态列表
    - 按时间倒序排列
    
    返回格式：
    [
        {
            "task_id": "uuid-string",
            "status": "completed",
            "total_count": 100,
            "success_count": 95,
            "failed_count": 5,
            "progress_percentage": 100.0,
            "start_time": "2024-01-01T12:00:00",
            "end_time": "2024-01-01T12:05:00"
        }
    ]
    """
    try:
        tasks = LoopImportService.get_all_tasks()
        return tasks
    
    except Exception as e:
        logger.error(f"查询任务列表失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询任务列表失败: {str(e)}"
        )
