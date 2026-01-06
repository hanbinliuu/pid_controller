#!/usr/bin/env python3
"""
回路批量导入服务
支持CSV文件解析和异步多线程导入
使用数据库存储任务状态
"""

import csv
import io
import logging
import uuid
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, Any, List, Optional

from api.bean.import_task import ImportTask
from api.bean.import_status import ImportStatus
from api.services.loop_service import LoopService
from api.dao.import_task_dao import ImportTaskDAO
from core.config import Config

logger = logging.getLogger(__name__)


class LoopImportService:
    """回路批量导入服务（使用数据库存储任务状态）"""

    @classmethod
    def parse_csv_content(cls, csv_content: str, default_parent_uri: str = "") -> List[Dict[str, Any]]:
        """
        解析CSV内容
        
        Args:
            csv_content: CSV文件内容字符串
            default_parent_uri: 默认父节点URI（可选，若为空则使用配置中的默认值）
            
        Returns:
            List[Dict]: 回路数据列表
            
        CSV格式示例（中文表头，parent_uri 可省略）:
        回路标识,回路名称,回路类型
        FIC-101,测试流量回路,流量
        TIC-102,测试温度回路,温度
        """
        loops = []
        
        try:
            # 使用StringIO处理CSV内容
            csv_file = io.StringIO(csv_content)
            sample = csv_content[:1024]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel
            csv_reader = csv.DictReader(csv_file, dialect=dialect)
            
            raw_fieldnames = csv_reader.fieldnames or []

            def normalize_header(header: Optional[str]) -> str:
                if not header:
                    return ""
                return header.lstrip("\ufeff").strip()

            normalized_fieldnames = [normalize_header(name) for name in raw_fieldnames]
            field_aliases = {
                "loop_type": ["loop_type", "回路类型"],
                "loop_display_name": ["loop_display_name", "回路名称"],
                "loop_browse_name": ["loop_browse_name", "回路标识"],
                "parent_uri": ["parent_uri", "父节点URI", "父节点uri", "父节点Uri"],
                "description": ["description", "回路描述"]
            }
            required_fields = ["loop_type", "loop_display_name", "loop_browse_name"]

            def has_field(field_key: str) -> bool:
                return any(
                    normalize_header(alias) in normalized_fieldnames
                    for alias in field_aliases.get(field_key, [])
                )

            missing_fields = [field for field in required_fields if not has_field(field)]
            if missing_fields:
                display_names = {
                    "loop_type": "回路类型(loop_type)",
                    "loop_display_name": "回路名称(loop_display_name)",
                    "loop_browse_name": "回路标识(loop_browse_name)"
                }
                missing_display = [display_names.get(field, field) for field in missing_fields]
                raise ValueError(f"CSV缺少必需字段: {', '.join(missing_display)}")
            
            # 读取所有行
            for row_num, row in enumerate(csv_reader, start=2):  # 从第2行开始（第1行是标题）
                # 验证必填字段
                normalized_row = {
                    normalize_header(key): value for key, value in (row or {}).items()
                }

                def get_value(field_key: str) -> str:
                    for alias in field_aliases.get(field_key, []):
                        normalized_alias = normalize_header(alias)
                        if normalized_alias in normalized_row:
                            value = normalized_row.get(normalized_alias)
                            return (value or "").strip()
                    return ""

                loop_data = {
                    'loop_type': get_value('loop_type'),
                    'loop_display_name': get_value('loop_display_name'),
                    'loop_browse_name': get_value('loop_browse_name'),
                    'parent_uri': get_value('parent_uri'),
                    'description': get_value('description'),
                    'row_number': row_num
                }

                # 如果CSV中未提供parent_uri，优先使用接口参数的默认值，否则使用配置中的默认值
                if not loop_data['parent_uri']:
                    if default_parent_uri:
                        loop_data['parent_uri'] = default_parent_uri
                        logger.debug(f"第 {row_num} 行使用接口参数的父节点URI: {default_parent_uri}")
                    else:
                        loop_data['parent_uri'] = Config.BFF_MODEL_ROOT_URI
                        if has_field("parent_uri"):
                            logger.warning(f"第 {row_num} 行 parent_uri 为空，使用默认父节点URI")
                
                # 检查必填字段是否为空
                if not all([loop_data['loop_type'], loop_data['loop_display_name'], 
                           loop_data['loop_browse_name']]):
                    logger.warning(f"第 {row_num} 行数据不完整，跳过")
                    continue
                
                loops.append(loop_data)
            
            logger.info(f"CSV解析成功，共解析 {len(loops)} 条有效回路数据")
            return loops
            
        except Exception as e:
            logger.error(f"CSV解析失败: {str(e)}")
            raise ValueError(f"CSV解析失败: {str(e)}")

    @classmethod
    def create_single_loop(cls, loop_data: Dict[str, Any], loop_service: LoopService) -> Dict[str, Any]:
        """
        创建单个回路
        
        Args:
            loop_data: 回路数据
            loop_service: 回路服务实例
            
        Returns:
            Dict: 创建结果
        """
        try:
            result = loop_service.instantiate_loop(
                loop_type=loop_data['loop_type'],
                loop_displayName=loop_data['loop_display_name'],
                loop_browseName=loop_data['loop_browse_name'],
                parent_uri=loop_data['parent_uri']
            )
            logger.info(f"回路创建成功: {result}")
            
            return {
                'success': result.get('success', False),
                'row_number': loop_data.get('row_number'),
                'loop_name': loop_data['loop_display_name'],
                'message': result.get('message', ''),
                'uri': result.get('result', {}).get('loop_uri') if result.get('success') else None
            }
            
        except Exception as e:
            logger.error(f"创建回路失败: {loop_data['loop_display_name']}, 错误: {str(e)}")
            return {
                'success': False,
                'row_number': loop_data.get('row_number'),
                'loop_name': loop_data['loop_display_name'],
                'message': str(e),
                'uri': None
            }

    @classmethod
    def import_loops_async(cls, task_id: str, loops: List[Dict[str, Any]], max_workers: int = 5):
        """
        异步导入回路（多线程）
        
        Args:
            task_id: 任务ID
            loops: 回路数据列表
            max_workers: 最大线程数
        """
        try:
            # 更新任务状态为运行中
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.RUNNING.value,
                start_time=datetime.now()
            )
            
            logger.info(f"开始导入任务 {task_id}，共 {len(loops)} 个回路，使用 {max_workers} 个线程")
            
            # 创建线程池
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 为每个回路创建LoopService实例（避免共享状态）
                futures = []
                for loop_data in loops:
                    loop_service = LoopService()
                    future = executor.submit(cls.create_single_loop, loop_data, loop_service)
                    futures.append(future)
                
                # 处理完成的任务
                for future in as_completed(futures):
                    try:
                        result = future.result()
                        
                        # 更新数据库中的任务进度
                        error_msg = None if result['success'] else {
                            'row_number': result['row_number'],
                            'loop_name': result['loop_name'],
                            'error': result['message']
                        }
                        
                        ImportTaskDAO.increment_progress(
                            task_id=task_id,
                            success=result['success'],
                            error_msg=error_msg
                        )
                        
                        if result['success']:
                            logger.info(f"回路创建成功: {result['loop_name']}, URI: {result['uri']}")
                        else:
                            logger.warning(f"回路创建失败: {result['loop_name']}, 原因: {result['message']}")
                    
                    except Exception as e:
                        # 处理异常
                        ImportTaskDAO.increment_progress(
                            task_id=task_id,
                            success=False,
                            error_msg={
                                'row_number': 'unknown',
                                'loop_name': 'unknown',
                                'error': str(e)
                            }
                        )
                        logger.error(f"处理回路时发生异常: {str(e)}")
            
            # 更新任务完成状态
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.COMPLETED.value,
                end_time=datetime.now()
            )
            
            logger.info(f"导入任务完成: {task_id}")
            
        except Exception as e:
            logger.error(f"导入任务异常: {task_id}, 错误: {str(e)}")
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.FAILED.value,
                end_time=datetime.now()
            )

    @classmethod
    def start_import_task(cls, csv_content: str, file_name: str = "", parent_uri: str = "", max_workers: int = 5) -> str:
        """
        启动导入任务
        
        Args:
            csv_content: CSV文件内容
            file_name: 文件名称（可选）
            parent_uri: 父节点URI（可选，缺省时在parse_csv_content中使用默认根节点）
            max_workers: 最大线程数（默认5）
            
        Returns:
            str: 任务ID
        """
        # 生成任务ID
        task_id = str(uuid.uuid4())
        
        # 计算文件信息
        file_size = len(csv_content.encode('utf-8'))
        file_hash = hashlib.md5(csv_content.encode('utf-8')).hexdigest()
        
        # 解析CSV
        try:
            loops = cls.parse_csv_content(csv_content, default_parent_uri=parent_uri)
            if not loops:
                raise ValueError("CSV文件中没有有效的回路数据")
        except Exception as e:
            logger.error(f"CSV解析失败: {str(e)}")
            raise
        
        # 在数据库中创建任务（包括文件信息）
        ImportTaskDAO.create_task(
            task_id=task_id,
            total_count=len(loops),
            file_name=file_name,
            file_size=file_size,
            file_hash=file_hash
        )
        
        # 在新线程中执行导入任务
        import threading
        thread = threading.Thread(
            target=cls.import_loops_async,
            args=(task_id, loops, max_workers),
            daemon=True
        )
        thread.start()
        
        logger.info(f"导入任务已启动: {task_id}, 回路数量: {len(loops)}, 文件: {file_name}, 父节点URI: {parent_uri if parent_uri else '默认'}")
        return task_id

    @classmethod
    def get_task_status(cls, task_id: str) -> Optional[Dict[str, Any]]:
        """
        获取任务状态
        
        Args:
            task_id: 任务ID
            
        Returns:
            Dict: 任务状态信息
        """
        return ImportTaskDAO.get_task_by_id(task_id)

    @classmethod
    def get_all_tasks(cls) -> List[Dict[str, Any]]:
        """
        获取所有任务状态
        
        Returns:
            List[Dict]: 所有任务列表
        """
        return ImportTaskDAO.get_all_tasks(limit=100)

    @classmethod
    def clear_old_tasks(cls, keep_days: int = 7) -> int:
        """
        清理旧任务
        
        Args:
            keep_days: 保留天数
            
        Returns:
            int: 删除的任务数量
        """
        return ImportTaskDAO.delete_old_tasks(keep_days=keep_days)
