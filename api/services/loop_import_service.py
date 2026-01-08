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
import pandas as pd

from api.bean.import_task import ImportTask
from api.bean.import_status import ImportStatus
from api.services.loop_service import LoopService
from api.dao.import_task_dao import ImportTaskDAO
from core.config import Config

logger = logging.getLogger(__name__)


class LoopImportService:
    """回路批量导入服务（使用数据库存储任务状态）"""

    @classmethod
    def parse_excel_content(cls, file_content: bytes) -> List[Dict[str, Any]]:
        """
        解析 Excel 内容

        Args:
            file_content: Excel文件二进制内容

        Returns:
            List[Dict]: 回路数据列表
        """
        loops = []
        try:
            # 读取 Excel 文件
            df = pd.read_excel(io.BytesIO(file_content))
            
            # 标准化列名（去除前后空格）
            df.columns = df.columns.astype(str).str.strip()
            
            # 字段映射配置
            field_aliases = {
                "loop_type": ["loop_type", "回路类型"],
                "loop_display_name": ["loop_display_name", "回路名称"],
                "loop_browse_name": ["loop_browse_name", "回路标识"],
            }
            required_fields = ["loop_type", "loop_display_name", "loop_browse_name"]
            
            # 检查缺失字段
            missing_fields = []
            column_mapping = {}
            
            for field in required_fields:
                found = False
                for alias in field_aliases.get(field, []):
                    if alias in df.columns:
                        column_mapping[alias] = field
                        found = True
                        break
                if not found:
                    missing_fields.append(field)
            
            if missing_fields:
                 display_names = {
                    "loop_type": "回路类型(loop_type)",
                    "loop_display_name": "回路名称(loop_display_name)",
                    "loop_browse_name": "回路标识(loop_browse_name)"
                }
                 missing_display = [display_names.get(f, f) for f in missing_fields]
                 raise ValueError(f"Excel缺少必需字段: {', '.join(missing_display)}")

            # 重命名列以便统一处理
            df = df.rename(columns=column_mapping)
            
            # 替换 NaN 为 None 或空字符串，便于后续处理
            df = df.where(pd.notnull(df), None)

            # 遍历行
            for index, row in df.iterrows():
                row_num = index + 2  # Excel 行号（假设第一行是标题）
                
                loop_data = {
                    'loop_type': str(row.get('loop_type', '') or '').strip(),
                    'loop_display_name': str(row.get('loop_display_name', '') or '').strip(),
                    'loop_browse_name': str(row.get('loop_browse_name', '') or '').strip(),
                    'row_number': row_num
                }
                
                # 检查必填字段是否为空
                if not all([loop_data['loop_type'], loop_data['loop_display_name'],
                            loop_data['loop_browse_name']]):
                     logger.warning(f"第 {row_num} 行数据不完整，跳过")
                     continue
                
                loops.append(loop_data)
            
            logger.info(f"Excel解析成功，共解析 {len(loops)} 条有效回路数据")
            return loops

        except Exception as e:
            logger.error(f"Excel解析失败: {str(e)}")
            raise ValueError(f"Excel解析失败: {str(e)}")

    @classmethod
    def parse_csv_content(cls, csv_content: str) -> List[Dict[str, Any]]:
        """
        解析CSV内容
        
        Args:
            csv_content: CSV文件内容字符串

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
                }

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
    def create_single_loop(cls, loop_data: Dict[str, Any], loop_service: LoopService, parent_uri: str , gateway_device_id: str = None) -> Dict[str, Any]:
        """
        创建单个回路
        
        Args:
            loop_data: 回路数据
            loop_service: 回路服务实例
            parent_uri: 所属装置URI
            
        Returns:
            Dict: 创建结果
        """
        try:
            start_time = datetime.now()

            result = loop_service.instantiate_loop(
                loop_type=loop_data['loop_type'],
                loop_displayName=loop_data['loop_display_name'],
                loop_browseName=loop_data['loop_browse_name'],
                parent_uri=parent_uri,
                gateway_device_id=gateway_device_id
            )
            logger.info(f"回路创建成功: {result}")
            end_time = datetime.now()
            logger.info(f"回路{loop_data['loop_browse_name']}创建耗时: {end_time - start_time}")
            return {
                'success': result.get('success', False),
                'row_number': loop_data.get('row_number'),
                'loop_name': loop_data['loop_display_name'],
                'message': result.get('message', ''),
                'uri': result.get('data', {}).get('loop_uri') if result.get('success') else None
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
    def import_loops_async(cls,
                           task_id: str,
                           loops: List[Dict[str, Any]],
                           parent_uri: str,
                           max_workers: int = 5,
                           gateway_device_id: str = None
                           ):
        """
        异步导入回路（多线程）
        
        Args:
            task_id: 任务ID
            loops: 回路数据列表
            max_workers: 最大线程数
            parent_uri: 父节点URI
            gateway_device_id: 网关设备ID
        """
        try:
            # 更新任务状态为运行中
            start_time = datetime.now()
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.RUNNING.value,
                start_time=start_time
            )

            logger.info(f"开始导入任务 {task_id}，共 {len(loops)} 个回路，使用 {max_workers} 个线程")

            # 创建线程池
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 为每个回路创建LoopService实例（避免共享状态）
                futures = []
                for loop_data in loops:
                    loop_service = LoopService()
                    future = executor.submit(cls.create_single_loop, loop_data=loop_data, loop_service=loop_service, parent_uri=parent_uri, gateway_device_id=gateway_device_id)
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
            # 同步回路列表信息同步
            logger.info("导入任务完成，同步回路信息")
            from api.tasks.load_loop_info import load_loop_list_and_sync
            load_loop_list_and_sync()
            # 更新任务完成状态
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.COMPLETED.value,
                end_time=end_time,
                duration=duration
            )

            logger.info(f"导入任务完成: {task_id}")

        except Exception as e:
            logger.error(f"导入任务异常: {task_id}, 错误: {str(e)}")
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds() if 'start_time' in locals() else 0
            ImportTaskDAO.update_task_status(
                task_id=task_id,
                status=ImportStatus.FAILED.value,
                end_time=end_time,
                duration=duration
            )

    @classmethod
    def start_import_task(cls,
                          file_content: bytes,
                          file_name: str = "",
                          parent_uri: str = "",
                          max_workers: int = 5,
                          gateway_device_id: str = None
                          ) -> str:
        """
        启动导入任务

        Args:
            file_content: 文件内容（二进制）
            file_name: 文件名称（必须包含扩展名以区分 CSV/Excel）
            parent_uri: 父节点URI
            max_workers: 最大线程数
            gateway_device_id : 子设备所属网关设备ID

        Returns:
            str: 任务ID
        """
        # 生成任务ID
        task_id = str(uuid.uuid4())

        # 计算文件信息
        file_size = len(file_content)
        file_hash = hashlib.md5(file_content).hexdigest()

        # 解析文件
        try:
            if file_name.lower().endswith('.xlsx'):
                loops = cls.parse_excel_content(file_content)
            elif file_name.lower().endswith('.csv'):
                 # 尝试解码 CSV
                try:
                    csv_text = file_content.decode('utf-8-sig')
                except UnicodeDecodeError:
                    # 如果 utf-8-sig 失败，尝试 gbk
                     csv_text = file_content.decode('gbk')
                loops = cls.parse_csv_content(csv_text)
            else:
                 raise ValueError("不支持的文件格式，仅支持 .csv 和 .xlsx")

            if not loops:
                raise ValueError("文件中没有有效的回路数据")
        except Exception as e:
            logger.error(f"文件解析失败: {str(e)}")
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
            args=(task_id, loops,parent_uri, max_workers, gateway_device_id),
            daemon=True
        )
        thread.start()

        logger.info(
            f"导入任务已启动: {task_id}, 回路数量: {len(loops)}, 文件: {file_name}, 父节点URI: {parent_uri if parent_uri else '默认'}")
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
