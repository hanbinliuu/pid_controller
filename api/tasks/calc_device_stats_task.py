#!/usr/bin/env python3
"""
装置性能定时统计任务
按天统计各装置下回路的性能状态
"""
import logging
from datetime import datetime, date
from typing import Dict, List, Any

from api.bean.loop_evaluation import LoopEvaluation
from api.bean.loop_info import LoopInfo
from core.database.database import get_db_session
from api.dao.loop_info_dao import LoopInfoDAO
from api.dao.loop_evaluation_dao import LoopEvaluationDAO
from api.dao.device_evaluation_dao import DeviceEvaluationDAO
from api.services.bff_service import BFFService
from core.config import Config
from sqlmodel import select, or_

logger = logging.getLogger(__name__)


def calc_device_statistics(statistics_date: date = None) -> Dict[str, Any]:
    """
    计算装置性能统计
    
    统计逻辑：
    1. 从BFF获取所有装置列表（使用BFFService.get_all_devices()）
    2. 对每个装置，查询其下的回路列表
    3. 查询回路评估数据并按装置汇总统计
    4. 批量写入装置评估表（按天和装置URI更新）
    
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
        device_info_map = {}  # 装置URI -> 装置信息
        device_loops_map = {}  # 装置URI -> 回路列表
        
        try:
            # 使用封装的BFFService获取所有装置列表
            all_devices = BFFService.get_all_devices()
            logger.info(f"从BFF查询到 {len(all_devices)} 个装置")
            
            # 获取所有激活的回路
            with get_db_session() as db:
                active_loops = LoopInfoDAO.get_active_loops(db)
                active_loop_uris = set(loop.loop_uri for loop in active_loops if loop.loop_uri)
                logger.info(f"数据库中有 {len(active_loop_uris)} 个激活回路")
            
            # 直接解析装置回路关系
            # 收集所有装置URI，一次性查询所有回路信息
            device_uris = [device.get('uri') for device in all_devices]
            
            # 一次性查询所有装置下的回路
            with get_db_session() as db:
                # 构建OR查询条件
                conditions = [LoopInfo.loop_path.like(f"%{device_uri}%") for device_uri in device_uris]
                statement = select(LoopInfo).where(or_(*conditions)).where(LoopInfo.is_active == True)
                all_device_loops = db.exec(statement).all()
                
                # 创建URI到回路列表的映射
                uri_to_loops = {}
                for loop in all_device_loops:
                    for device in all_devices:
                        device_uri = device.get('uri')
                        if device_uri and loop.loop_path and device_uri in loop.loop_path:
                            if device_uri not in uri_to_loops:
                                uri_to_loops[device_uri] = []
                            uri_to_loops[device_uri].append(loop)
                
                # 构建最终的device_info_map和device_loops_map
                for device in all_devices:
                    device_uri = device.get('uri')
                    device_name = device.get('displayName', device.get('browseName', ''))
                    parent_device_uri = device.get('parentUri', '')
                    device_info_map[device_uri] = {
                        "device_uri": device_uri,
                        "device_name": device_name,
                        "parent_device_uri": parent_device_uri
                    }
                    device_loops_map[device_uri] = []
                    device_loops = uri_to_loops.get(device_uri, [])
                    for loop in device_loops:
                        if loop.loop_uri:
                            device_loops_map[device_uri].append({
                                'loop_uri': loop.loop_uri,
                                'loop_name': loop.loop_name,
                                'description': loop.description,
                                'loop_type': loop.loop_type
                            })
        except Exception as e:
            logger.error(f"从BFF查询装置列表失败: {str(e)}")
            return {
                "status": "失败",
                "message": f"查询装置列表失败: {str(e)}",
                "error": str(e)
            }
        
        if not device_info_map:
            logger.warning("未查询到任何装置或装置下没有回路")
            return {
                "status": "失败",
                "message": "未查询到任何装置或装置下没有回路",
                "device_count": 0
            }
        
        # 2. 查询回路评估数据并在同一会话中处理统计数据
        logger.info("正在查询回路评估数据...")
        all_loop_uris = set()
        for loops in device_loops_map.values():
            for loop in loops:
                all_loop_uris.add(loop['loop_uri'])
        
        logger.info(f"需要查询 {len(all_loop_uris)} 个回路的评估数据")
        
        # 3. 在同一数据库会话中查询评估数据并统计性能指标
        with get_db_session() as db:
            # 批量查询回路评估数据
            loop_evaluations = {}
            batch_size = 100  # 批量查询大小
            
            all_loop_uris_list = list(all_loop_uris)
            for i in range(0, len(all_loop_uris_list), batch_size):
                batch_uris = all_loop_uris_list[i:i + batch_size]
                batch_evaluations = LoopEvaluationDAO.get_by_uris_and_date(
                    db, batch_uris, statistics_date
                )
                
                # 将结果添加到字典中
                for evaluation in batch_evaluations:
                    loop_evaluations[evaluation.loop_uri] = evaluation
                
                logger.debug(f"批量查询进度: {min(i + batch_size, len(all_loop_uris))}/{len(all_loop_uris)}")
            
            logger.info(f"查询到 {len(loop_evaluations)} 个回路的评估数据")
            
            # 将评估数据关联到装置回路映射中
            for device_uri, loops in device_loops_map.items():
                for loop in loops:
                    loop['evaluation'] = loop_evaluations.get(loop['loop_uri'])
            
            # 按装置统计性能指标
            device_stats = {}
            
            for device_uri, loops in device_loops_map.items():
                total_loops = len(loops)
                auto_control_loops = 0
                stable_loops = 0
                conditional_excluded_loops = 0
                
                # 统计各项指标
                for loop_data in loops:
                    evaluation = loop_data.get('evaluation')
                
                    # 条件剔除判断
                    if not evaluation or evaluation.status == '条件剔除':
                        conditional_excluded_loops += 1
                        continue

                    # 自控率判断：auto_control_rate >= 80%
                    if evaluation.auto_control_rate and evaluation.auto_control_rate >= 0.8:
                        auto_control_loops += 1

                    # 平稳率判断：stability_rate >= 80%
                    if evaluation.stability_rate and evaluation.stability_rate >= 0.8:
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
        
        # 4. 批量写入装置评估数据到数据库
        persisted_count = 0
        failed_count = 0
        
        # 准备批量upsert数据
        upsert_data_list = []
        for device_uri, stats in device_stats.items():
            # 从device_info_map中获取装置信息
            device_info = device_info_map.get(device_uri, {})
            if device_info:
                device_name = device_info.get('device_name', device_uri)
                parent_device_uri = device_info.get('parent_device_uri')
            else:
                device_name = device_uri
                parent_device_uri = None
            
            upsert_data_list.append({
                'device_uri': device_uri,
                'device_name': device_name,
                'parent_device_uri': parent_device_uri,
                'statistics_date': statistics_date,
                'loop_count': stats['total_loops'],
                'auto_loop_count': stats['auto_control_loops'],
                'auto_control_rate': stats['auto_control_rate'],
                'stable_loop_count': stats['stable_loops'],
                'stability_rate': stats['stability_rate'],
                'conditional_excluded_loop_count': stats['conditional_excluded_loops']
            })
        
        # 批量写入数据库
        try:
            batch_results = DeviceEvaluationDAO.batch_upsert_by_device_uri_and_date(
                db, upsert_data_list
            )
            persisted_count = len(batch_results)
            
            logger.info(f"批量写入装置评估数据成功: {persisted_count} 条记录")
        except Exception as e:
            logger.error(f"批量写入装置评估数据失败: {str(e)}")
            failed_count = len(upsert_data_list)
        
        result = {
            "status": "成功" if failed_count == 0 else "部分失败",
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
