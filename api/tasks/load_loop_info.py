#!/usr/bin/env python3
"""
定时加载模型树任务
定时从BFF模型服务加载模型树，并将回路信息写入loop_info表
"""
import logging
from typing import Dict, Any, List
from datetime import datetime

from core.client.bff_model_client import BFFModelClient
from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO
from core.config import Config

logger = logging.getLogger(__name__)

# 模型树配置（从配置文件中加载）
MODEL_IDENTIFIER_LIST = [Config.BFF_MODEL_LOOP_MODEL_URI]  # 单回路模型URI
START_IDENTIFIER_LIST = [Config.BFF_MODEL_ROOT_URI]  # 从根节点开始
DEFAULT_POINT_PATH = Config.BFF_MODEL_POINT_PATH  # 测点相对路径（point_path）


def load_loop_list_and_sync() -> Dict[str, Any]:
    """
    加载模型树并同步到数据库
    
    Returns:
        执行结果统计
    """
    try:
        logger.info("=" * 70)
        logger.info("开始执行定时任务：加载模型树并同步到数据库")
        logger.info("=" * 70)
        
        # 统计信息
        stats = {
            "start_time": datetime.now().isoformat(),
            "total_instances": 0,
            "new_loops": 0,
            "updated_loops": 0,
            "deactivated_loops": 0,  # 新增：逻辑删除的回路数
            "failed_loops": 0,
            "errors": []
        }
        
        # 1. 从BFF加载模型树
        logger.info(f"正在从BFF加载模型树...")
        logger.info(f"  模型标识符: {MODEL_IDENTIFIER_LIST}")
        logger.info(f"  起始标识符: {START_IDENTIFIER_LIST}")
        
        instances = _load_instances_from_bff()
        stats["total_instances"] = len(instances)
        
        if not instances:
            logger.warning("未获取到任何实例")
            stats["end_time"] = datetime.now().isoformat()
            return stats
        
        logger.info(f"成功加载 {len(instances)} 个回路实例")
        
        # 2. 同步到数据库
        logger.info(f"正在同步回路信息到数据库...")
        
        # 收集本次查询到的所有loop_uri
        current_loop_uris = set()
        
        with get_db_session() as db:
            for instance in instances:
                try:
                    loop_uri = instance.get('uri')
                    if loop_uri:
                        current_loop_uris.add(loop_uri)
                    
                    result = _sync_loop_to_db(db, instance)
                    
                    if result == "created":
                        stats["new_loops"] += 1
                    elif result == "updated":
                        stats["updated_loops"] += 1
                        
                except Exception as e:
                    stats["failed_loops"] += 1
                    error_msg = f"同步回路失败 [{instance.get('uri')}]: {str(e)}"
                    logger.error(error_msg)
                    stats["errors"].append(error_msg)
            
            # 3. 逻辑删除未查询到的回路
            logger.info(f"正在检查并逻辑删除未查询到的回路...")
            try:
                deactivated_count = _deactivate_missing_loops(db, current_loop_uris)
                stats["deactivated_loops"] = deactivated_count
                logger.info(f"逻辑删除了 {deactivated_count} 个未查询到的回路")
            except Exception as e:
                error_msg = f"逻辑删除未查询回路失败: {str(e)}"
                logger.error(error_msg)
                stats["errors"].append(error_msg)
        
        stats["end_time"] = datetime.now().isoformat()
        
        # 输出统计结果
        logger.info("=" * 70)
        logger.info("定时任务执行完成")
        logger.info(f"  总实例数: {stats['total_instances']}")
        logger.info(f"  新增回路: {stats['new_loops']}")
        logger.info(f"  更新回路: {stats['updated_loops']}")
        logger.info(f"  逻辑删除: {stats['deactivated_loops']}")
        logger.info(f"  失败回路: {stats['failed_loops']}")
        logger.info("=" * 70)
        
        return stats
        
    except Exception as e:
        logger.error(f"加载模型树任务执行失败: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "end_time": datetime.now().isoformat()
        }


def _load_instances_from_bff() -> List[Dict[str, Any]]:
    """
    从BFF加载所有实例
    
    Returns:
        实例列表
    """
    all_instances = []
    page_no = 1
    page_size = 100  # 每页100条
    
    try:
        with BFFModelClient() as client:
            while True:
                result = client.list_instances_under_tree(
                    model_identifier_list=MODEL_IDENTIFIER_LIST,
                    start_identifier_list=START_IDENTIFIER_LIST,
                    contain_sub_model=True,
                    page_no=page_no,
                    page_size=page_size
                )
                
                instances = result.get('instances', [])
                if not instances:
                    break
                
                all_instances.extend(instances)
                
                # 检查是否还有更多页
                pagination = result.get('pagination', {})
                total_pages = pagination.get('pages', 0)
                
                logger.info(f"已加载第 {page_no}/{total_pages} 页，当前总数: {len(all_instances)}")
                
                if page_no >= total_pages:
                    break
                
                page_no += 1
        
        return all_instances
        
    except Exception as e:
        logger.error(f"从BFF加载实例失败: {str(e)}")
        raise


def _sync_loop_to_db(db, instance: Dict[str, Any]) -> str:
    """
    同步单个回路信息到数据库
    
    数据来源说明：
    - loop_uri: 从模型实例中获取
    - loop_path: 优先从模型的uriPath获取，如为空则使用配置文件默认值
    - point_path: 从配置文件获取（测点相对路径）
    - 测点字段: 通过BFF客户端查询回路的测点映射
    
    Args:
        db: 数据库会话
        instance: BFF返回的实例对象
        
    Returns:
        'created' 或 'updated'
    """
    loop_uri = instance.get('uri')
    
    if not loop_uri:
        raise ValueError("实例URI为空")
    
    # 查询是否已存在（包括已逻辑删除的回路）
    existing_loop = LoopInfoDAO.get_by_loop_uri(db, loop_uri, include_inactive=True)
    
    # 提取实例信息
    loop_name = instance.get('displayName', instance.get('browseName', ''))
    uri_path = instance.get('uriPath', '')  # 从模型中获取完整URI路径
    description = instance.get('description', '')
    
    # 查询回路的测点信息
    point_mapping = _query_loop_points(loop_uri)
    
    # 准备数据
    loop_data = {
        "loop_uri": loop_uri,
        "loop_path": uri_path,  # URI路径：优先从模型获取，否则使用配置
        "loop_name": loop_name,
        "point_path": DEFAULT_POINT_PATH,  # 测点相对路径：从配置文件中获取
        "description": description,
        "is_active": True,
        "updated_time": datetime.now()
    }
    
    # 添加测点字段
    if point_mapping:
        loop_data.update({
            "pv_field": point_mapping.get('PV'),
            "sv_field": point_mapping.get('SV'),
            "mv_field": point_mapping.get('MV'),
            "pb_field": point_mapping.get('PB'),
            "ti_field": point_mapping.get('TI'),
            "td_field": point_mapping.get('TD'),
            "auto_status_field": point_mapping.get('AUTO')
        })
    
    if existing_loop:
        # 更新现有记录
        LoopInfoDAO.update_by_loop_uri(db, loop_uri, loop_data)
        logger.debug(f"更新回路: {loop_name} ({loop_uri})")
        return "updated"
    else:
        # 创建新记录
        loop_data["created_time"] = datetime.now()
        LoopInfoDAO.create(db, loop_data)
        logger.debug(f"新增回路: {loop_name} ({loop_uri})")
        return "created"


def _query_loop_points(loop_uri: str) -> Dict[str, str]:
    """
    查询回路的测点映射信息
    
    Args:
        loop_uri: 回路URI
        
    Returns:
        测点名称映射字典，如 {'MV': 'ns=100;s=xxx', 'PV': 'ns=100;s=yyy', ...}
    """
    try:
        with BFFModelClient(device_uri=loop_uri) as client:
            # 查询常用PID控制字段
            # query_common_fields 返回字典，键为字段名（如 'MV', 'PV'），值为测点路径
            point_mapping = client.query_common_fields()
            
            if point_mapping and isinstance(point_mapping, dict):
                logger.debug(f"成功查询回路测点: {loop_uri}, 测点数: {len(point_mapping)}")
                return point_mapping
            else:
                logger.warning(f"未查询到回路测点: {loop_uri}")
                return {}
                
    except Exception as e:
        logger.warning(f"查询回路测点失败 [{loop_uri}]: {str(e)}")
        return {}


def _deactivate_missing_loops(db, current_loop_uris: set) -> int:
    """
    逻辑删除未在本次查询中出现的回路
    
    Args:
        db: 数据库会话
        current_loop_uris: 本次查询到的所有loop_uri集合
        
    Returns:
        逻辑删除的回路数量
    """
    try:
        # 获取数据库中所有激活的回路
        all_active_loops = LoopInfoDAO.get_all_active(db)
        
        deactivated_count = 0
        for loop in all_active_loops:
            # 如果数据库中的回路不在本次查询结果中，则逻辑删除
            if loop.loop_uri not in current_loop_uris:
                update_data = {
                    "is_active": False,
                    "updated_time": datetime.now()
                }
                LoopInfoDAO.update_by_loop_uri(db, loop.loop_uri, update_data)
                logger.info(f"逻辑删除回路: {loop.loop_name} ({loop.loop_uri})")
                deactivated_count += 1
        
        return deactivated_count
        
    except Exception as e:
        logger.error(f"逻辑删除回路失败: {str(e)}")
        raise
