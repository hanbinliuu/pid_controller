"""
路由层 - 装置管理API接口
提供装置的新增、修改、删除等管理功能
"""
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Depends, Body, Query
from sqlmodel import Session

from core.database.database import get_db
from core.utils.idass import UserInfo, get_current_user
from api.middleware.response_model import success_response, error_response
from api.services.device_manage_service import DeviceManageService

router = APIRouter(prefix="/api/v1/device_manage")
logger = logging.getLogger(__name__)

# 初始化装置管理服务
device_manage_service = DeviceManageService()


@router.post(
    "/create",
    summary="新增装置",
    operation_id="create_device",
    description="在指定目标位置创建新装置节点"
)
async def create_device(
    target_uri: str = Body(..., description="目标父节点URI"),
    display_name: str = Body(..., description="装置显示名称"),
    browse_name: str = Body(..., description="装置浏览名称"),
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    新增装置节点

    Args:
        project_uri: 项目URI
        source_uri: 源URI（装置类型模板）
        target_uri: 目标父节点URI
        display_name: 装置显示名称
        browse_name: 装置浏览名称
        data_source_uri: 数据源URI（可选）
        table_name: 表名（可选）
        user: 当前用户信息
        db: 数据库会话

    Returns:
        装置创建结果，包含新装置的URI

    Example:
        ```json
        {
            "project_uri": "/pid_zd/root",
            "source_uri": "/system/401",
            "target_uri": "/pid_zd/053f3c45413b48bbafacec609d142e57",
            "display_name": "常减压装置",
            "browse_name": "CDJ_Device",
            "data_source_uri": "",
            "table_name": ""
        }
        ```
    """
    try:
        logger.info(f"请求创建装置: {display_name}")

        # 调用装置管理服务创建装置
        result = device_manage_service.create_device(
            creator=user.user_name if user else None,
            target_uri=target_uri,
            display_name=display_name,
            browse_name=browse_name
        )

        # 检查接口返回结果
        if result.get("success"):
            device_uri = result.get("result", {}).get("uri")
            logger.info(f"装置创建成功: {display_name}, URI: {device_uri}")
            return success_response(
                data={
                    "device_uri": device_uri,
                    "display_name": display_name,
                    "browse_name": browse_name,
                    "message": result.get("message", "装置创建成功")
                },
                message="装置创建成功"
            )
        else:
            logger.error(f"装置创建失败: {result.get('message')}")
            return error_response(
                message=result.get("message", "装置创建失败"),
                code=result.get("code", -1)
            )

    except Exception as e:
        logger.error(f"创建装置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"创建装置失败: {str(e)}")


@router.put(
    "/update",
    summary="修改装置",
    operation_id="update_device",
    description="修改装置的显示名称等属性"
)
async def update_device(
    device_uri: str = Body(..., description="装置URI"),
    display_name: str = Body(..., description="新的显示名称"),
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    修改装置信息

    Args:
        device_uri: 装置URI
        display_name: 新的显示名称
        user: 当前用户信息
        db: 数据库会话

    Returns:
        装置修改结果

    Example:
        ```json
        {
            "device_uri": "/pid_zd/eb65b27e4ff94a4da9a82d577f5cf3d9",
            "display_name": "常减压装置_新"
        }
        ```
    """
    try:
        logger.info(f"请求修改装置: {device_uri}")

        # 调用装置管理服务更新装置
        result = device_manage_service.update_device(
            modifier=user.user_name if user else None,
            device_uri=device_uri,
            display_name=display_name
        )

        # 检查接口返回结果
        if result.get("success"):
            logger.info(f"装置修改成功: {device_uri}")
            return success_response(
                data={
                    "device_uri": device_uri,
                    "display_name": display_name,
                    "message": result.get("message", "装置修改成功")
                },
                message="装置修改成功"
            )
        else:
            logger.error(f"装置修改失败: {result.get('message')}")
            return error_response(
                message=result.get("message", "装置修改失败"),
                code=result.get("code", -1)
            )

    except Exception as e:
        logger.error(f"修改装置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"修改装置失败: {str(e)}")


@router.delete(
    "/delete",
    summary="删除装置",
    operation_id="delete_device",
    description="删除指定的装置节点"
)
async def delete_device(
    device_uri: str = Query(..., description="装置URI"),
    user: UserInfo = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    删除装置节点

    Args:
        device_uri: 装置URI
        user: 当前用户信息
        db: 数据库会话

    Returns:
        装置删除结果

    Example:
        DELETE /api/v1/device_manage/delete?device_uri=/pid_zd/eb65b27e4ff94a4da9a82d577f5cf3d9
    """
    try:
        logger.info(f"请求删除装置: {device_uri}")

        # 调用装置管理服务删除装置
        result = device_manage_service.delete_device(
            modifier=user.user_name if user else None,
            device_uri=device_uri
        )
        
        # 检查接口返回结果
        if result.get("success"):
            logger.info(f"装置删除成功: {device_uri}")
            return success_response(
                data={
                    "device_uri": device_uri,
                    "message": result.get("message", "装置删除成功")
                },
                message="装置删除成功"
            )
        else:
            logger.error(f"装置删除失败: {result.get('message')}")
            return error_response(
                message=result.get("message", "装置删除失败"),
                code=result.get("code", -1)
            )
            
    except Exception as e:
        logger.error(f"删除装置失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"删除装置失败: {str(e)}")


