#!/usr/bin/env python3
"""
文件导入服务
用于检查目标服务状态和连通性，以及文件的定期维护任务
"""
import logging
import requests
from sqlmodel import Session
from typing import List

from api.pid_data_mgr.block_util import BlockUtil
from api.pid_data_mgr.file_meta_dao import FileMetaService
from api.pid_data_mgr.file_db_models import PIDDataFile, FileStatus
from api.pid_data_mgr.file_settings import settings
from api.pid_data_mgr.file_store_service import FileStoreService
from core.database.database import get_db as get_session

logger = logging.getLogger(__name__)

# Pong响应常量
K_PONG = "pong"


class FileImportService:
    """
    文件导入服务
    """
    
    @staticmethod
    def build_url(host_port: str) -> str:
        """
        构建Ping接口的URL
        
        Args:
            host_port: 主机和端口，格式如 "localhost:8001" 或 "192.168.1.1:8080"
        
        Returns:
            完整的URL字符串
        """
        return f"http://{host_port}/api/v1/ping"
    
    @staticmethod
    def is_target_alive(host_port: str, timeout: int = 5) -> bool:
        """
        检查目标服务是否存活
        
        Args:
            host_port: 主机和端口，格式如 "localhost:8001" 或 "192.168.1.1:8080"
            timeout: 请求超时时间（秒），默认5秒
        
        Returns:
            True 表示服务存活，False 表示服务不可用
        """
        # 检查hostPort是否为空
        if not host_port or not host_port.strip():
            logger.warning("host_port 参数为空")
            return False
        
        try:
            # 构建URL
            url = FileImportService.build_url(host_port)
            
            # 发送GET请求
            response = requests.get(url, timeout=timeout)
            
            # 检查响应状态码为200，且响应体为"pong"
            if response.status_code == 200 and response.text:
                # 尝试解析JSON响应
                try:
                    data = response.json()
                    # 检查message字段是否为"pong"
                    if isinstance(data, dict) and data.get("message") == K_PONG:
                        logger.debug(f"目标服务 {host_port} 存活")
                        return True
                except ValueError:
                    # 如果不是JSON，直接比较文本
                    if response.text.strip() == K_PONG:
                        logger.debug(f"目标服务 {host_port} 存活")
                        return True
            
            logger.warning(f"目标服务 {host_port} 响应异常: status={response.status_code}")
            return False
            
        except requests.exceptions.Timeout:
            logger.warning(f"连接目标服务 {host_port} 超时")
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"无法连接到目标服务 {host_port}")
            return False
        except Exception as e:
            logger.error(f"检查目标服务 {host_port} 时发生异常: {str(e)}")
            return False
    
    @staticmethod
    def do_import_file():
        """
        文件导入定期维护任务
        每10秒被调用一次，执行以下三个任务：
        1. 清理过期文件（超过保留时间的上传中文件）
        2. 合并已上传完成的文件
        3. 清理已合并的文件块
        """
        logger.info("开始执行文件维护任务")
        
        try:
            with get_session() as session:
                # 任务1: 清理过期文件
                count = FileImportService._clean_expired_files(session)
                logger.info(f"清理过期文件完成，共清理 {count} 个文件")
                
                # 任务2: 合并已上传完成的文件
                count = FileImportService._merge_uploaded_files(session)
                logger.info(f"合并已上传完成的文件完成，共合并 {count} 个文件")
                
                # 任务3: 清理已合并的文件块
                count = FileImportService._clean_merged_file_blocks(session)
                logger.info(f"清理已合并的文件块完成，共清理 {count} 个文件块")
                
            logger.info("文件维护任务执行完成")
            
        except Exception as e:
            logger.error(f"文件维护任务执行失败: {str(e)}")
    
    @staticmethod
    def _clean_expired_files(session: Session):
        """
        清理过期的上传中文件
        
        Args:
            session: 数据库会话
        """
        count = 0
        try:
            # 读取 uploading 状态文件
            expired_files = FileMetaService.select_expired_uploading_files(session)
            
            if not expired_files:
                expired_files = list()

            # 读取 deleted 状态文件
            deleted_files = FileMetaService.get_files_by_status(session, FileStatus.DELETED)
            if deleted_files:
                expired_files.extend(deleted_files)

            if len(expired_files) == 0:
                return count
            
            logger.info(f"发现 {len(expired_files)} 个过期文件")
            
            # 删除过期文件
            for file in expired_files:
                try:
                    if file.status == FileStatus.UPLOADING:
                        # 检查是否传输完成
                        blocks_count = BlockUtil.calc_blocks_count(file.total_size, file.block_size)
                        uploaded_blocks_count = FileMetaService.count_blocks(file.fid)
                        if uploaded_blocks_count == blocks_count:
                            # 上传完成
                            FileMetaService.mark_as(session, file.fid, FileStatus.UPLOADED)
                            continue

                    logger.info(f"清理过期文件: {file.name} (fid={file.fid}, upload_id={file.upload_id})")

                    if settings.host_port == file.host_port:
                        FileImportService._delete_blocks_and_file(session, file)
                        # 防止删除数据块及物理文件异常
                        FileMetaService.reset_host_port(session, file.fid)
                        count += 1
                        continue

                    if FileImportService.is_target_alive(file.host_port):
                        continue

                    if not FileMetaService.set_host_port(session, file.fid, file.host_port):
                        continue

                    FileImportService._delete_blocks_and_file(session, file)

                    # 防止删除数据块及物理文件异常
                    FileMetaService.reset_host_port(session, file.fid)
                    count += 1
                    
                    logger.info(f"过期文件已清理: fid={file.fid}")
                    
                except Exception as e:
                    logger.error(f"清理过期文件失败 (fid={file.fid}): {str(e)}")
                    
        except Exception as e:
            logger.error(f"清理过期文件任务失败: {str(e)}")
        return count
    
    @staticmethod
    def _merge_uploaded_files(session: Session):
        """
        合并已上传完成的文件
        
        Args:
            session: 数据库会话
        """
        count = 0
        try:
            # 查询所有已上传中的文件
            uploaded_files = FileMetaService.get_files_by_status(session, FileStatus.UPLOADED)
            
            if not uploaded_files:
                return 0
            
            for file in uploaded_files:
                try:
                    if settings.host_port == file.host_port:
                        FileImportService._merge_file_blocks(session, file)
                        FileMetaService.reset_host_port(session, file.fid)
                        count += 1
                        continue

                    if FileImportService.is_target_alive(file.host_port):
                        continue

                    if not FileMetaService.set_host_port(session, file.fid, file.host_port):
                        continue

                    FileImportService._merge_file_blocks(session, file)
                    FileMetaService.reset_host_port(session, file.fid)
                    count += 1
                except Exception as e:
                    logger.error(f"合并文件失败 (fid={file.fid}): {str(e)}")
                    
        except Exception as e:
            logger.error(f"合并文件任务失败: {str(e)}")
        return count
    
    @staticmethod
    def _clean_merged_file_blocks(session: Session):
        """
        清理已合并文件的块记录
        
        Args:
            session: 数据库会话
        """
        count = 0
        try:
            # 查询所有已合并的文件
            merged_files = FileMetaService.get_files_by_status(session, FileStatus.MERGED)
            
            if not merged_files:
                return 0
            
            for file in merged_files:
                try:
                    if settings.host_port == file.host_port:
                        FileImportService.clean_blocks(session, file)
                        FileMetaService.reset_host_port(session, file.fid)
                        count += 1
                        continue

                    if FileImportService.is_target_alive(file.host_port):
                        continue

                    if not FileMetaService.set_host_port(session, file.fid, file.host_port):
                        continue

                    FileImportService.clean_blocks(session, file)
                    FileMetaService.reset_host_port(session, file.fid)
                    count += 1
                except Exception as e:
                    logger.error(f"清理文件块失败 (fid={file.fid}): {str(e)}")
                    
        except Exception as e:
            logger.error(f"清理文件块任务失败: {str(e)}")

        return count
    
    @staticmethod
    def _merge_file_blocks(session: Session, file: PIDDataFile):
        """
        合并文件块为完整文件
        
        Args:
            session: 数据库会话
            file: 文件对象
            
        Raises:
            Exception: 合并失败时抛出异常
        """
        import os
        
        # 获取所有块
        blocks = FileMetaService.get_blocks(session, file.fid)
        if blocks:
            logger.debug(f"正在合并文件块: {file.name} (fid={file.fid})")
            block_names = [b.block_name for b in blocks]
            FileStoreService.merge_blocks(file, block_names)
        FileMetaService.mark_as(session, file.fid, FileStatus.MERGED)
        
        logger.debug(f"文件块合并完成: {file.name} (fid={file.fid})")

    @staticmethod
    def _delete_blocks_and_file(session: Session, file: PIDDataFile):
        logger.info(f"清理过期文件: {file.name} (fid={file.fid}, upload_id={file.upload_id})")
        try:
            # 删除文件块元数据
            FileMetaService.delete_file_blocks(session, file.fid)
            # 删除物理文件块
            FileStoreService.delete_file_directory(file.fid)
            # 删除文件元数据
            FileMetaService.delete_file(session, file.fid)
        except Exception as e:
            logger.error(f"清理文件块失败 (fid={file.fid}): {str(e)}")

    @staticmethod
    def clean_blocks(session: Session, file: PIDDataFile):
        """
        清理文件块

        Args:
            session: 数据库会话
            file: 文件对象
        """
        logger.info(f"清理文件块: {file.name} (fid={file.fid})")
        try:
            FileStoreService.clean_file_blocks(file)
            FileMetaService.delete_file_blocks(session, file.fid)
            FileMetaService.mark_as(session, file.fid, FileStatus.CLEANED)
        except Exception as e:
            logger.error(f"清理文件块失败 (fid={file.fid}): {str(e)}")
        pass

    @staticmethod
    def run_import():
        """
        运行文件导入定期维护任务
        每10秒调用一次 do_import_file，该函数将被一个独立的进程调用
        """
        import time
        
        logger.info("开始运行文件导入定期维护任务")
        
        while True:
            try:
                # 执行文件导入维护任务
                FileImportService.do_import_file()
                
                # 等待10秒后再次执行
                time.sleep(10)
                
            except KeyboardInterrupt:
                logger.info("收到中断信号，停止文件导入定期维护任务")
                break
            except Exception as e:
                logger.error(f"执行文件导入定期维护任务时发生异常: {str(e)}")
                
                # 发生异常后等待10秒再继续
                time.sleep(10)
        
        logger.info("文件导入定期维护任务已停止")