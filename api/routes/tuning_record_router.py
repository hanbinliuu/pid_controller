#!/usr/bin/env python3
"""
整定记录管理路由 - 使用SQLModel
用于保存和查询PID整定记录
"""
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query, Depends, Body
from sqlmodel import Session

from api.middleware.exceptions import RuntimeException
from api.response.loop_response import LoopInfoResponse
from api.routes.device_data_route import DeviceCommand
from api.services.bff_service import BFFService
from api.services.device_data_service import DeviceDataService
from api.services.loop_service import LoopService
from core.client.bff_model_client import BFFModelClient
from core.database.database import get_db
from api.services.tuning_record_service import TuningRecordService
from api.bean.tuning_record import TuningRecord
from core.utils.idass import UserInfo, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# SQLModel已在models.py中定义TuningRecord，可直接用作请求和响应模型

@router.post(
    "/send-device-command",
    summary="整定下发",
    operation_id="整定下发",
    description="常规整定或大模型整定的参数下发及记录保存",
    response_model=TuningRecord
)
async def send_device_command(
    loop_uri: str  = Body(..., description="URI列表"),
    tuning_method: str = Body(..., description="整定方法", example=["常规整定", "大模型整定"]),
    tuning_type: str = Body(..., description="整定类型", example=["PID", "PI"]),
    before_params: str = Body(None, description="整定前参数", example={"pb": 18.5443, "ti": 1.0431, "td": 0.0, "kp": 5.3925, "ki": 5.1699, "kd": 0.0}),
    after_params: str = Body(None, description="整定后参数", example={"pb": 18.5443, "ti": 1.0431, "td": 0.0, "kp": 5.3925, "ki": 5.1699, "kd": 0.0}),
    # status: str = Body(..., description="整定状态", example=["成功", "失败"]),
    remark: Optional[str] = Body(..., description="描述", example="参数已下发"),
    user: UserInfo = Depends(get_current_user)
) -> TuningRecord:
    """
    创建整定记录 - 优化版本

    功能说明：
    - 创建整定记录
    - 使用SQLModel自动验证和序列化

    返回格式：直接返回TuningRecord对象（自动序列化为JSON）
    """
    logger.info(f"整定下发: {loop_uri}")
    # 获取回路信息

    loop_info:LoopInfoResponse = LoopService.query_loop_info(loop_uri)
    json_data = json.loads(after_params)
    #获取测点信息
    commands = []
    with BFFModelClient(loop_uri=loop_uri) as client:
        table, field_mapping = client.query_table_and_points_by_loop_uri(loop_uri=loop_uri)
        # 查询常用字段
        query_result = client.query_common_fields(field_mapping.values())

        # 提取table名称和测点列表
        table_and_points = BFFModelClient.extract_table_and_points_from_paths(query_result)

        table_name = table_and_points.get('table_name').split("default")[0]

        points = table_and_points.get('points', {})
        send_points = ["pb", "ti", "td"]
        param = {}
        for point_name in send_points:
            if point_name in points:
                value = json_data.get(point_name)
                iot_point_name = points.get(point_name)
                param[iot_point_name] = value
        command = DeviceCommand(
            object_device_id=table_name,
            paras=param
        )
        commands.append(command)
    # #参数下发
    try:
        send_result = await DeviceDataService.send_device_command_batch(commands=commands)
        logger.info(f"参数下发结果: {send_result}")
        user_id= None
        user_name = None
        if user:
            user_id = user.user_id
            user_name = user.user_name

        record = TuningRecordService.create_record(
            loop_uri=loop_uri,
            loop_status=loop_info.auto_control_status,
            tuning_method=tuning_method,
            operator=user_name,
            operator_id=user_id,
            before_params=before_params,
            after_params=after_params,
            description=loop_info.description,
            status='成功',
            remark=remark,
            tuning_details=f"整定方法：{tuning_method},整定类型：{tuning_type}"
        )
        return record
    except Exception as e:
        logger.error(f"参数下发异常: {str(e)}")
        record = TuningRecordService.create_record(
            loop_uri=loop_uri,
            loop_status=loop_info.auto_control_status,
            tuning_method=tuning_method,
            operator=user_name,
            operator_id=user_id,
            before_params=before_params,
            after_params=after_params,
            description=loop_info.description,
            status='失败',
            remark='参数下发失败',
            tuning_details=f"参数下发异常: {str(e)}"
        )
        # return record
        raise RuntimeException(
            f"参数下发异常: {str(e)}"
        )

@router.post(
    "/",
    summary="创建整定下发记录",
    operation_id="创建整定下发记录",
    description="保存常规整定或大模型整定的参数整定下发结果",
    response_model=TuningRecord
)
async def create_tuning_record(
    loop_uri: str  = Body(..., description="URI列表"),
    loop_status: str = Body(..., description="回路状态", example=["自动", "手动"]),
    tuning_type: str = Body(..., description="整定类型"),
    tuning_method: str = Body(..., description="整定方法", example=["常规整定", "大模型整定"]),
    before_params: str = Body(None, description="整定前参数", example={"pb": 18.5443, "ti": 1.0431, "td": 0.0, "kp": 5.3925, "ki": 5.1699, "kd": 0.0}),
    after_params: str = Body(None, description="整定后参数", example={"pb": 18.5443, "ti": 1.0431, "td": 0.0, "kp": 5.3925, "ki": 5.1699, "kd": 0.0}),
    description: Optional[str]  = Body(None, description="整定描述"),
    status: str = Body(..., description="整定状态", example=["成功", "失败"]),
    remark: Optional[str] = Body(..., description="描述", example="参数已下发"),
    tuning_details: str = Body(..., description="整定详情"),
    user: UserInfo = Depends(get_current_user)
) -> TuningRecord:
    """
    创建整定记录 - SQLModel优化版本

    功能说明：
    - 保存整定操作的详细信息
    - 记录整定前后的参数对比
    - 支持常规整定和大模型整定两种方式
    - 使用SQLModel自动验证和序列化

    返回格式：直接返回TuningRecord对象（自动序列化为JSON）
    """
    try:
        # 调用Service层创建记录
        record = TuningRecordService.create_record(
            loop_uri=loop_uri,
            loop_status=loop_status,
            tuning_method=tuning_method,
            operator=user.user_name,
            operator_id=user.user_id,
            before_params=before_params,
            after_params=after_params,
            description=description,
            status=status,
            remark=remark,
            tuning_details=tuning_details
        )

        return record

    except Exception as e:
        logger.error(f"创建整定下发记录异常: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"创建整定下发记录异常: {str(e)}"
        )


@router.get(
    "/page",
    summary="查询整定记录列表",
    operation_id="查询整定记录列表",
    description="查询整定记录列表，支持筛选和分页"
)
async def query_tuning_records(
    loop_type: Optional[str] = Query(
            None,
            description="回路类型筛选"
    ),
    device_uri: Optional[str] = Query(
            None,
            description="设备URI筛选"
    ),
    loop_name: Optional[str] = Query(
        None,
        description="回路名称筛选",
    ),
    tuning_method: Optional[str] = Query(
        None,
        description="整定方法筛选（预整定/常规整定/大模型整定）",
        example="常规整定"
    ),

    start_time: Optional[str] = Query(
        None,
        description="开始时间",
        example="2025-01-01"
    ),
    end_time: Optional[str] = Query(
        None,
        description="结束时间",
        example="2025-12-31"
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
    ),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    查询整定记录列表
    
    功能说明：
    - 查询所有整定记录
    - 支持按回路名称、整定方法、时间范围筛选
    - 支持分页查询
    
    返回格式：
    {
        "records": [
            {
                "sequence": 1,
                "loop_name": "LIC-401",
                "description": "T801流位控制",
                "tuning_method": "常规整定",
                "tuning_time": "2025-01-15 14:38:25",
                "operator": "张三",
                "before_params": "68.00/800.00/5.00",
                "after_params": "46.97/160.00/0.00",
                "status": "成功",
                "remark": "参数已落地CS"
            }
        ],
        "pagination": {
            "total": 5,
            "pages": 1,
            "pageNo": 1,
            "pageSize": 10
        }
    }
    """
    try:
        # 调用Service层查询
        result = TuningRecordService.query_records(
            db=db,
            loop_type=loop_type,
            device_uri=device_uri,
            loop_name=loop_name,
            tuning_method=tuning_method,
            start_time=start_time,
            end_time=end_time,
            page_no=page_no,
            page_size=page_size
        )
        
        return result
    
    except Exception as e:
        logger.error(f"查询整定记录失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询整定记录失败: {str(e)}"
        )


@router.get(
    "/{record_id}",
    summary="查询整定记录详情",
    operation_id="查询整定记录详情",
    description="根据ID查询整定记录的详细信息",
    response_model=TuningRecord
)
async def get_tuning_record(
    record_id: str,
    db: Session = Depends(get_db)
) -> TuningRecord:
    """
    查询整定记录详情
    
    功能说明：
    - 根据记录ID查询详细信息
    - 包含完整的整定过程数据
    
    返回格式：
    {
        "id": 1,
        "loop_name": "LIC-401",
        "tuning_method": "常规整定",
        "tuning_details": { ... },
        ...
    }
    """
    try:
        # 调用Service层查询
        record = TuningRecordService.get_record_by_id(db, record_id)
        
        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"未找到ID为 {record_id} 的整定记录"
            )
        
        return record
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询整定记录详情失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"查询整定记录详情失败: {str(e)}"
        )
