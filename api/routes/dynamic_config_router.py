 #!/usr/bin/env python3
"""
路由层 - 动态配置参数API接口
"""
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlmodel import Session
from pydantic import BaseModel

from core.database.database import get_db
from api.services.dynamic_config_service import DynamicConfigService
from api.bean.dynamic_config import DynamicConfig
from api.middleware.exceptions import (
    BusinessException,
    ValidationException,
    DataProcessException,
    NotFoundException
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1/dynamic-config")


# 请求体模型
class CreateConfigRequest(BaseModel):
    """创建配置请求"""
    config_key: str
    config_value: Optional[str] = None
    config_type: Optional[str] = "string"
    config_group: Optional[str] = None
    description: Optional[str] = None
    is_enabled: bool = True
    created_by: Optional[str] = None


class UpdateConfigRequest(BaseModel):
    """更新配置请求"""
    config_value: Optional[str] = None
    config_type: Optional[str] = None
    config_group: Optional[str] = None
    description: Optional[str] = None
    is_enabled: Optional[bool] = None
    updated_by: Optional[str] = None


class BatchCreateConfigRequest(BaseModel):
    """批量创建配置请求"""
    configs: List[CreateConfigRequest]


@router.post("/create",
            summary="创建配置参数",
            operation_id="create_dynamic_config",
            response_model=Dict[str, Any])
async def create_config(
    request: CreateConfigRequest = Body(..., description="创建配置请求"),
    db: Session = Depends(get_db)
):
    """
    创建新的配置参数
    
    请求体示例：
    ```json
    {
        "config_key": "max_workers",
        "config_value": "10",
        "config_type": "number",
        "config_group": "performance",
        "description": "最大工作线程数",
        "is_enabled": true,
        "created_by": "admin"
    }
    ```
    """
    try:
        config = DynamicConfigService.create_config(
            db,
            config_key=request.config_key,
            config_value=request.config_value,
            config_type=request.config_type,
            config_group=request.config_group,
            description=request.description,
            is_enabled=request.is_enabled,
            created_by=request.created_by
        )
        
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_type": config.config_type,
            "config_group": config.config_group,
            "description": config.description,
            "is_enabled": config.is_enabled,
            "created_by": config.created_by,
            "created_time": config.created_time.isoformat() if config.created_time else None,
            "updated_time": config.updated_time.isoformat() if config.updated_time else None
        }
    except ValueError as e:
        logger.error(f"参数验证失败: {str(e)}", exc_info=True)
        raise ValidationException(
            message=f"参数验证失败: {str(e)}",
            data={"config_key": request.config_key}
        )
    except Exception as e:
        logger.error(f"创建配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"创建配置参数失败: {str(e)}",
            data={"config_key": request.config_key}
        )


@router.get("/get-by-key",
           summary="根据配置键查询配置",
           operation_id="get_config_by_key",
           response_model=Dict[str, Any])
async def get_config_by_key(
    config_key: str = Query(..., description="配置键"),
    db: Session = Depends(get_db)
):
    """
    根据配置键查询配置参数
    """
    try:
        config = DynamicConfigService.get_config_by_key(db, config_key)
        
        if not config:
            raise NotFoundException(
                message=f"未找到配置键为 {config_key} 的配置",
                data={"config_key": config_key}
            )
        
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_type": config.config_type,
            "config_group": config.config_group,
            "description": config.description,
            "is_enabled": config.is_enabled,
            "created_by": config.created_by,
            "updated_by": config.updated_by,
            "created_time": config.created_time.isoformat() if config.created_time else None,
            "updated_time": config.updated_time.isoformat() if config.updated_time else None
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"查询配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询配置参数失败: {str(e)}",
            data={"config_key": config_key}
        )


@router.get("/get-by-id",
           summary="根据ID查询配置",
           operation_id="get_config_by_id",
           response_model=Dict[str, Any])
async def get_config_by_id(
    config_id: str = Query(..., description="配置ID"),
    db: Session = Depends(get_db)
):
    """
    根据配置ID查询配置参数
    """
    try:
        config = DynamicConfigService.get_config_by_id(db, config_id)
        
        if not config:
            raise NotFoundException(
                message=f"未找到ID为 {config_id} 的配置",
                data={"config_id": config_id}
            )
        
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_type": config.config_type,
            "config_group": config.config_group,
            "description": config.description,
            "is_enabled": config.is_enabled,
            "created_by": config.created_by,
            "updated_by": config.updated_by,
            "created_time": config.created_time.isoformat() if config.created_time else None,
            "updated_time": config.updated_time.isoformat() if config.updated_time else None
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"查询配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询配置参数失败: {str(e)}",
            data={"config_id": config_id}
        )


@router.get("/get-value",
           summary="获取配置值（自动类型转换）",
           operation_id="get_config_value",
           response_model=Dict[str, Any])
async def get_config_value(
    config_key: str = Query(..., description="配置键"),
    default_value: Optional[str] = Query(None, description="默认值（字符串格式）"),
    db: Session = Depends(get_db)
):
    """
    获取配置值，并根据配置类型自动进行类型转换
    
    支持的类型转换：
    - number: 转换为整数或浮点数
    - boolean: 转换为布尔值
    - json: 解析为JSON对象
    - string: 返回字符串
    """
    try:
        value = DynamicConfigService.get_config_value(db, config_key, default_value)
        
        return {
            "config_key": config_key,
            "value": value,
            "value_type": type(value).__name__
        }
    except Exception as e:
        logger.error(f"获取配置值失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"获取配置值失败: {str(e)}",
            data={"config_key": config_key}
        )


@router.get("/list",
           summary="分页查询配置列表",
           operation_id="list_dynamic_configs",
           response_model=Dict[str, Any])
async def list_configs(
    config_key: Optional[str] = Query(None, description="配置键（模糊匹配）"),
    config_group: Optional[str] = Query(None, description="配置分组"),
    config_type: Optional[str] = Query(None, description="配置类型"),
    is_enabled: Optional[bool] = Query(None, description="是否启用"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    分页查询配置参数列表
    
    支持的筛选条件：
    - config_key: 配置键模糊查询
    - config_group: 配置分组精确匹配
    - config_type: 配置类型精确匹配
    - is_enabled: 是否启用
    """
    try:
        result = DynamicConfigService.list_configs(
            db,
            config_key=config_key,
            config_group=config_group,
            config_type=config_type,
            is_enabled=is_enabled,
            page_no=page_no,
            page_size=page_size
        )
        
        return result

    except Exception as e:
        logger.error(f"查询配置列表失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询配置列表失败: {str(e)}"
        )


@router.get("/list-by-group",
           summary="根据分组查询配置列表",
           operation_id="list_configs_by_group",
           response_model=Dict[str, Any])
async def list_configs_by_group(
    config_group: str = Query(..., description="配置分组"),
    include_disabled: bool = Query(False, description="是否包含已禁用的配置"),
    db: Session = Depends(get_db)
):
    """
    根据配置分组查询配置列表
    """
    try:
        configs = DynamicConfigService.get_configs_by_group(db, config_group, include_disabled)
        
        return {
            "config_group": config_group,
            "configs": [
                {
                    "id": config.id,
                    "config_key": config.config_key,
                    "config_value": config.config_value,
                    "config_type": config.config_type,
                    "description": config.description,
                    "is_enabled": config.is_enabled,
                    "created_time": config.created_time.isoformat() if config.created_time else None,
                    "updated_time": config.updated_time.isoformat() if config.updated_time else None
                }
                for config in configs
            ]
        }
    except Exception as e:
        logger.error(f"查询配置列表失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询配置列表失败: {str(e)}",
            data={"config_group": config_group}
        )


@router.get("/list-enabled",
           summary="查询所有启用的配置",
           operation_id="list_enabled_configs",
           response_model=Dict[str, Any])
async def list_enabled_configs(
    db: Session = Depends(get_db)
):
    """
    查询所有启用的配置参数
    """
    try:
        configs = DynamicConfigService.get_all_enabled_configs(db)
        
        return {
            "configs": [
                {
                    "id": config.id,
                    "config_key": config.config_key,
                    "config_value": config.config_value,
                    "config_type": config.config_type,
                    "config_group": config.config_group,
                    "description": config.description,
                    "created_time": config.created_time.isoformat() if config.created_time else None,
                    "updated_time": config.updated_time.isoformat() if config.updated_time else None
                }
                for config in configs
            ]
        }
    except Exception as e:
        logger.error(f"查询启用的配置列表失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"查询启用的配置列表失败: {str(e)}"
        )


@router.put("/update-by-key",
           summary="根据配置键更新配置",
           operation_id="update_config_by_key",
           response_model=Dict[str, Any])
async def update_config_by_key(
    config_key: str = Query(..., description="配置键"),
    request: UpdateConfigRequest = Body(..., description="更新配置请求"),
    db: Session = Depends(get_db)
):
    """
    根据配置键更新配置参数
    
    请求体示例：
    ```json
    {
        "config_value": "20",
        "config_type": "number",
        "description": "更新后的描述",
        "is_enabled": true,
        "updated_by": "admin"
    }
    ```
    """
    try:
        config = DynamicConfigService.update_config(
            db,
            config_key=config_key,
            config_value=request.config_value,
            config_type=request.config_type,
            config_group=request.config_group,
            description=request.description,
            is_enabled=request.is_enabled,
            updated_by=request.updated_by
        )
        
        if not config:
            raise NotFoundException(
                message=f"未找到配置键为 {config_key} 的配置",
                data={"config_key": config_key}
            )
        
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_type": config.config_type,
            "config_group": config.config_group,
            "description": config.description,
            "is_enabled": config.is_enabled,
            "updated_by": config.updated_by,
            "updated_time": config.updated_time.isoformat() if config.updated_time else None
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"更新配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"更新配置参数失败: {str(e)}",
            data={"config_key": config_key}
        )


@router.put("/update-by-id",
           summary="根据ID更新配置",
           operation_id="update_config_by_id",
           response_model=Dict[str, Any])
async def update_config_by_id(
    config_id: str = Query(..., description="配置ID"),
    request: UpdateConfigRequest = Body(..., description="更新配置请求"),
    db: Session = Depends(get_db)
):
    """
    根据配置ID更新配置参数
    """
    try:
        config = DynamicConfigService.update_config_by_id(
            db,
            config_id=config_id,
            config_value=request.config_value,
            config_type=request.config_type,
            config_group=request.config_group,
            description=request.description,
            is_enabled=request.is_enabled,
            updated_by=request.updated_by
        )
        
        if not config:
            raise NotFoundException(
                message=f"未找到ID为 {config_id} 的配置",
                data={"config_id": config_id}
            )
        
        return {
            "id": config.id,
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_type": config.config_type,
            "config_group": config.config_group,
            "description": config.description,
            "is_enabled": config.is_enabled,
            "updated_by": config.updated_by,
            "updated_time": config.updated_time.isoformat() if config.updated_time else None
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"更新配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"更新配置参数失败: {str(e)}",
            data={"config_id": config_id}
        )


@router.delete("/delete-by-key",
             summary="根据配置键删除配置",
             operation_id="delete_config_by_key",
             response_model=Dict[str, Any])
async def delete_config_by_key(
    config_key: str = Query(..., description="配置键"),
    db: Session = Depends(get_db)
):
    """
    根据配置键删除配置参数
    """
    try:
        success = DynamicConfigService.delete_config(db, config_key)
        
        if not success:
            raise NotFoundException(
                message=f"未找到配置键为 {config_key} 的配置",
                data={"config_key": config_key}
            )
        
        return {
            "config_key": config_key,
            "message": "删除成功"
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"删除配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"删除配置参数失败: {str(e)}",
            data={"config_key": config_key}
        )


@router.delete("/delete-by-id",
             summary="根据ID删除配置",
             operation_id="delete_config_by_id",
             response_model=Dict[str, Any])
async def delete_config_by_id(
    config_id: str = Query(..., description="配置ID"),
    db: Session = Depends(get_db)
):
    """
    根据配置ID删除配置参数
    """
    try:
        success = DynamicConfigService.delete_config_by_id(db, config_id)
        
        if not success:
            raise NotFoundException(
                message=f"未找到ID为 {config_id} 的配置",
                data={"config_id": config_id}
            )
        
        return {
            "config_id": config_id,
            "message": "删除成功"
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"删除配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"删除配置参数失败: {str(e)}",
            data={"config_id": config_id}
        )


@router.post("/batch-create",
           summary="批量创建配置",
           operation_id="batch_create_configs",
           response_model=Dict[str, Any])
async def batch_create_configs(
    request: BatchCreateConfigRequest = Body(..., description="批量创建配置请求"),
    db: Session = Depends(get_db)
):
    """
    批量创建配置参数
    
    请求体示例：
    ```json
    {
        "configs": [
            {
                "config_key": "max_workers",
                "config_value": "10",
                "config_type": "number",
                "config_group": "performance"
            },
            {
                "config_key": "timeout",
                "config_value": "30",
                "config_type": "number",
                "config_group": "performance"
            }
        ]
    }
    ```
    """
    try:
        if not request.configs:
            raise ValidationException(
                message="配置列表不能为空",
                data={"configs": request.configs}
            )
        
        config_list = [
            {
                "config_key": item.config_key,
                "config_value": item.config_value,
                "config_type": item.config_type,
                "config_group": item.config_group,
                "description": item.description,
                "is_enabled": item.is_enabled,
                "created_by": item.created_by
            }
            for item in request.configs
        ]
        
        created_configs = DynamicConfigService.batch_create_configs(db, config_list)
        
        return {
            "count": len(created_configs),
            "configs": [
                {
                    "id": config.id,
                    "config_key": config.config_key,
                    "config_value": config.config_value,
                    "config_type": config.config_type,
                    "config_group": config.config_group
                }
                for config in created_configs
            ]
        }
    except BusinessException:
        raise
    except ValueError as e:
        logger.error(f"参数验证失败: {str(e)}", exc_info=True)
        raise ValidationException(
            message=f"参数验证失败: {str(e)}",
            data={"config_count": len(request.configs) if request.configs else 0}
        )
    except Exception as e:
        logger.error(f"批量创建配置失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"批量创建配置失败: {str(e)}",
            data={"config_count": len(request.configs) if request.configs else 0}
        )

