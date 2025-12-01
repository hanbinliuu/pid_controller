#!/usr/bin/env python3
"""
装置性能定时统计任务
按天统计各装置下回路的性能状态
"""
import logging
from datetime import datetime, date
from typing import Dict, List, Any

from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO
from api.dao.loop_evaluation_dao import LoopEvaluationDAO
from api.dao.device_evaluation_dao import DeviceEvaluationDAO
from api.services.bff_service import BFFService
from core.client.bff_model_client import BFFModelClient
from core.config import Config

logger = logging.getLogger(__name__)


def _parse_device_loops_from_tree(
    tree_result: Dict[str, Any],
    active_loop_uris: set
) -> Dict[str, List[Dict[str, Any]]]:
    """
    从BFF树形结构中解析装置和回路的关系
    
    逻辑：
    1. 遍历树形结构的所有节点
    2. 识别装置节点（有子节点且子节点是回路）
    3. 收集每个装置下的回路列表
    
    Args:
        tree_result: BFF返回的树形结构
        active_loop_uris: 激活的回路URI集合（用于过滤）
        
    Returns:
        装置URI -> 回路列表的映射
        回路对象格式: {
            'loop_uri': str,
            'loop_name': str,
            'device_uri': str,
            'device_name': str,
            'parent_device_uri': str
        }
    """
    device_loops_map = {}
    
    def traverse_tree(node: Dict[str, Any], parent_node: Dict[str, Any] = None):
        """
        递归遍历树形结构
        
        Args:
            node: 当前节点
            parent_node: 父节点
        """
        if not node:
            return
        
        node_info = node.get('node', {})
        node_uri = node_info.get('uri')
        node_name = node_info.get('displayName', node_info.get('browseName', ''))
        children = node.get('children', [])
        
        # 如果当前节点是回路（在激活回路列表中）
        if node_uri in active_loop_uris:
            # 父节点就是装置
            if parent_node:
                parent_info = parent_node.get('node', {})
                device_uri = parent_info.get('uri')
                device_name = parent_info.get('displayName', parent_info.get('browseName', ''))
                
                # 获取装置的父节点（用于parent_device_uri）
                parent_device_uri = parent_info.get('parentUri')
                
                if device_uri:
                    if device_uri not in device_loops_map:
                        device_loops_map[device_uri] = []
                    
                    device_loops_map[device_uri].append({
                        'loop_uri': node_uri,
                        'loop_name': node_name,
                        'device_uri': device_uri,
                        'device_name': device_name,
                        'parent_device_uri': parent_device_uri
                    })
        
        # 继续遍历子节点
        for child in children:
            traverse_tree(child, node)
    
    # 从根节点开始遍历
    result = tree_result.get('result', {})
    if result:
        traverse_tree(result)
    
    logger.info(f"从树形结构中解析出 {len(device_loops_map)} 个装置")
    for device_uri, loops in device_loops_map.items():
        logger.debug(f"  装置 {device_uri}: {len(loops)} 个回路")
    
    return device_loops_map


def calc_device_statistics(statistics_date: date = None) -> Dict[str, Any]:
    """
    计算装置性能统计
    
    统计逻辑：
    1. 从BFF获取所有装置列表（使用BFFService.get_all_devices()）
    2. 对每个装置，查询其下的回路列表
    3. 查询回路评估数据并按装置汇总统计
    4. 写入装置评估表（按天和装置URI更新）
    
    Args:
        statistics_date: 统计日期，默认为今天
        
    Returns:
        统计结果字典
    """
    try:
        if statistics_date is None:
            statistics_date = date.today()
        
        logger.info(f"开始计算装置性能统计，统计日期: {statistics_date}")
        
        # 1. 从BFF获取所有装置列表
        logger.info("正在从BFF查询装置列表...")
        device_loops_map = {}  # 装置URI -> 回路列表
        
        try:
            # 获取所有激活的回路（用于过滤）
            with get_db_session() as db:
                active_loops = LoopInfoDAO.get_all_active(db)
                active_loop_uris = set(loop.loop_uri for loop in active_loops if loop.loop_uri)
            
            logger.info(f"数据库中有 {len(active_loop_uris)} 个激活回路")
            
            # 使用封装的BFFService获取所有装置列表
            all_devices = BFFService.get_all_devices()
            logger.info(f"从BFF查询到 {len(all_devices)} 个装置")

            # todo  获取装置的回路列表
            device_loops_map={}
            for device in all_devices:
                device_uri = device.get('uri')
                device_name = device.get('displayName', device.get('browseName', ''))
                device_loops_map[device_uri] = []
                device_loops_map[device_uri].append({
                    'loop_uri': device_uri,
                    'loop_name': device_name,
                    'device_uri': device_uri,
                    'device_name': device_name,
                })

        
        except Exception as e:
            logger.error(f"从BFF查询装置列表失败: {str(e)}")
            return {
                "status": "失败",
                "message": f"查询装置列表失败: {str(e)}",
                "error": str(e)
            }
        
        if not device_loops_map:
            logger.warning("未查询到任何装置或装置下没有回路")
            return {
                "status": "失败",
                "message": "未查询到任何装置或装置下没有回路",
                "device_count": 0
            }
        
        # 2. 查询回路评估数据
        logger.info("正在查询回路评估数据...")
        all_loop_uris = []
        for loops in device_loops_map.values():
            all_loop_uris.extend([loop['loop_uri'] for loop in loops])
        
        logger.info(f"需要查询 {len(all_loop_uris)} 个回路的评估数据")
        
        with get_db_session() as db:
            loop_evaluations = {}
            for loop_uri in all_loop_uris:
                evaluation = LoopEvaluationDAO.get_by_loop_uri_and_date(
                    db, loop_uri, statistics_date
                )
                if evaluation:
                    loop_evaluations[loop_uri] = evaluation
        
        logger.info(f"查询到 {len(loop_evaluations)} 个回路的评估数据")
        
        # 将评估数据关联到装置回路映射中
        for device_uri, loops in device_loops_map.items():
            for loop in loops:
                loop['evaluation'] = loop_evaluations.get(loop['loop_uri'])
        
        # 3. 按装置统计性能指标
        device_stats = {}
        
        for device_uri, loops in device_loops_map.items():
            total_loops = len(loops)
            auto_control_loops = 0
            stable_loops = 0
            conditional_excluded_loops = 0
            
            # 统计各项指标
            for loop_data in loops:
                evaluation = loop_data.get('evaluation')
                if not evaluation:
                    # 没有评估数据的回路，条件剔除
                    conditional_excluded_loops += 1
                    continue
                
                # 自控率判断：auto_control_rate >= 80%
                if evaluation.auto_control_rate and evaluation.auto_control_rate >= 80:
                    auto_control_loops += 1
                
                # 平稳率判断：stability_rate >= 80%
                if evaluation.stability_rate and evaluation.stability_rate >= 80:
                    stable_loops += 1
            
            # 计算比率
            auto_control_rate = (auto_control_loops / total_loops * 100) if total_loops > 0 else 0.0
            stability_rate = (stable_loops / total_loops * 100) if total_loops > 0 else 0.0
            
            device_stats[device_uri] = {
                'total_loops': total_loops,
                'auto_control_loops': auto_control_loops,
                'stable_loops': stable_loops,
                'conditional_excluded_loops': conditional_excluded_loops,
                'auto_control_rate': round(auto_control_rate, 2),
                'stability_rate': round(stability_rate, 2)
            }
        
        logger.info(f"完成 {len(device_stats)} 个装置的性能统计")
        
        # 4. 写入装置评估数据到数据库
        persisted_count = 0
        failed_count = 0
        
        # 写入装置评估数据
        with get_db_session() as db:
            for device_uri, stats in device_stats.items():
                try:
                    # 从device_loops_map中获取装置信息
                    device_loops = device_loops_map.get(device_uri, [])
                    device_name = device_loops[0]['device_name'] if device_loops else device_uri
                    parent_device_uri = device_loops[0].get('parent_device_uri')
                    
                    evaluation_data = {
                        'device_uri': device_uri,
                        'device_name': device_name,
                        'parent_device_uri': parent_device_uri,
                        'statistics_time': datetime.combine(statistics_date, datetime.min.time()),
                        'loop_count': stats['total_loops'],
                        'auto_loop_count': stats['auto_control_loops'],
                        'auto_control_rate': stats['auto_control_rate'],
                        'stable_loop_count': stats['stable_loops'],
                        'stability_rate': stats['stability_rate'],
                        'conditional_excluded_loop_count': stats['conditional_excluded_loops']
                    }
                    
                    # 使用upsert方法，按天和装置URI更新
                    DeviceEvaluationDAO.upsert_by_device_uri_and_date(
                        db,
                        device_uri=device_uri,
                        statistics_date=statistics_date,
                        evaluation_data=evaluation_data
                    )
                    
                    persisted_count += 1
                    logger.debug(f"写入装置评估成功: {device_name} ({device_uri})")
                    
                except Exception as e:
                    failed_count += 1
                    logger.warning(f"写入装置评估失败 [{device_uri}]: {str(e)}")
        
        result = {
            "status": "成功",
            "message": "装置性能统计完成",
            "statistics_date": statistics_date.isoformat(),
            "summary": {
                "total_loops": len(all_loop_uris),
                "evaluated_loops": len(loop_evaluations),
                "total_devices": len(device_stats),
                "persisted_devices": persisted_count,
                "failed_devices": failed_count
            },
            "device_stats": device_stats
        }
        
        logger.info(
            f"装置性能统计完成 - 日期: {statistics_date}, "
            f"装置数: {len(device_stats)}, "
            f"成功写入: {persisted_count}, "
            f"失败: {failed_count}"
        )
        
        return result
        
    except Exception as e:
        logger.error(f"计算装置性能统计失败: {str(e)}", exc_info=True)
        return {
            "status": "异常",
            "message": "装置性能统计失败",
            "error": str(e)
        }
