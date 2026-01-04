 #!/usr/bin/env python3
"""
路由层 - 动态配置参数API接口
只提供查询和更新接口，配置通过初始化方法创建
"""
import logging
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, Body
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
from api.response.dynamic_config_response import (
    DynamicConfigData,
    InitializeResponse,
    ConfigValueResponse,
    ConfigListResponse,
    ConfigGroupResponse,
    ConfigsResponse,
    UpdateConfigResponse,
    BatchUpdateResponse
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/v1/dynamic-config")


# 请求体模型
class UpdateConfigRequest(BaseModel):
    """更新配置请求"""
    config_value: str


class BatchUpdateConfigRequest(BaseModel):
    """批量更新配置请求"""
    configs: Dict[str, str]


@router.post("/initialize",
            summary="初始化配置项",
            operation_id="initialize_fixed_configs",
            response_model=InitializeResponse)
def initialize_configs(
    db: Session = Depends(get_db)
):
    """
    初始化固定配置参数：
    - virtual_gateway_device_id: 虚拟网关设备ID
    - product_model_id: 产品（设备模型）ID
    - default_resource_space: 默认资源空间
    
    此方法应在系统启动时调用一次，如果配置已存在则不会重复创建
    """
    try:
        result = DynamicConfigService.initialize_fixed_configs(db)
        
        return {
            "message": "初始化成功",
            "created_count": result["created_count"],
            "skipped_count": result["skipped_count"],
            "configs": result["configs"]
        }
    except Exception as e:
        logger.error(f"初始化配置参数失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"初始化配置参数失败: {str(e)}"
        )


@router.get("/get-by-key",
           summary="根据配置键查询配置",
           operation_id="get_config_by_key",
           response_model=DynamicConfigData)
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
            "config_key": config.config_key,
            "config_value": config.config_value,
            "config_group": config.config_group,
            "config_name": config.config_name,
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

@router.get("/list",
           summary="分页查询配置列表",
           operation_id="list_dynamic_configs",
           response_model=ConfigListResponse)
async def list_configs(
    config_key: Optional[str] = Query(None, description="配置键（模糊匹配）"),
    config_group: Optional[str] = Query(None, description="配置分组"),
    page_no: int = Query(1, description="页码，从1开始"),
    page_size: int = Query(10, description="每页数量"),
    db: Session = Depends(get_db)
):
    """
    分页查询配置参数列表
    
    支持的筛选条件：
    - config_key: 配置键模糊查询
    - config_group: 配置分组精确匹配
    """
    try:
        result = DynamicConfigService.list_configs(
            db,
            config_key=config_key,
            config_group=config_group,
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
           response_model=ConfigGroupResponse)
async def list_configs_by_group(
    config_group: str = Query(..., description="配置分组"),
    db: Session = Depends(get_db)
):
    """
    根据配置分组查询配置列表
    """
    try:
        configs = DynamicConfigService.get_configs_by_group(db, config_group)
        
        return {
            "config_group": config_group,
            "configs": [
                {
                    "config_key": config.config_key,
                    "config_value": config.config_value,
                    "config_name": config.config_name,
                    "config_group": config.config_group,
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


@router.get("/list-all",
           summary="查询所有配置",
           operation_id="list_all_configs",
           response_model=ConfigsResponse)
async def list_all_configs(
    db: Session = Depends(get_db)
):
    """
    查询所有配置参数
    """
    try:
        configs = DynamicConfigService.get_all_configs(db)
        
        return {
            "configs": [
                {
                    "config_key": config.config_key,
                    "config_value": config.config_value,
                    "config_group": config.config_group,
                    "config_name": config.config_name,
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

@router.put("/batch-update",
           summary="批量更新配置",
           operation_id="batch_update_configs",
           response_model=BatchUpdateResponse)
async def batch_update_configs(
    request: Dict[str, str] = Body(..., description="批量更新配置请求"),
    db: Session = Depends(get_db)
):
    """
    批量更新配置参数
    
    使用 key:value 形式批量更新配置值
    
    请求体示例：
    ```json
    {
        "configs": {
            "virtual_gateway_device_id": "new_gateway_id",
            "product_model_id": "new_product_id",
            "default_resource_space": "new_resource_space"
        }
    }
    ```
    
    返回示例：
    ```json
    {
        "message": "批量更新完成",
        "success_count": 2,
        "failed_count": 1,
        "results": [
            {
                "config_key": "virtual_gateway_device_id",
                "config_value": "new_gateway_id",
                "status": "success",
                "message": "更新成功"
            },
            {
                "config_key": "invalid_key",
                "status": "failed",
                "message": "配置键 'invalid_key' 不存在"
            }
        ]
    }
    ```
    """
    try:
        if not request:
            raise ValidationException(
                message="配置字典不能为空",
                data={"configs": request}
            )
        
        result = DynamicConfigService.batch_update_configs(db, request)
        
        return {
            "message": "批量更新完成",
            "success_count": result["success_count"],
            "failed_count": result["failed_count"],
            "results": result["results"]
        }
    except BusinessException:
        raise
    except Exception as e:
        logger.error(f"批量更新配置失败: {str(e)}", exc_info=True)
        raise DataProcessException(
            message=f"批量更新配置失败: {str(e)}"
        )


