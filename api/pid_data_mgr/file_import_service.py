#!/usr/bin/env python3
"""
文件导入服务
用于检查目标服务状态和连通性，以及文件的定期维护任务
"""
import logging
import os
import pandas as pd

import requests
from sqlmodel import Session

from api.pid_data_mgr.addressing import Addressing
from api.pid_data_mgr.block_util import BlockUtil
from api.pid_data_mgr.file_meta_dao import FileMetaService
from api.pid_data_mgr.file_db_models import PIDDataFile, FileStatus
from api.pid_data_mgr.file_settings import settings
from api.pid_data_mgr.file_store_service import FileStoreService
from core.database.database import get_db_session as get_session
from core.config import Config as config

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
        每10秒被调用一次，执行以下4个任务：
        1. 清理过期文件（超过保留时间的上传中文件）
        2. 合并已上传完成的文件
        3. 清理已合并的文件块
        4. 将合并后的文件写入时序数据库
        """
        logger.info("=" * 60)
        logger.info("开始执行PID文件维护任务")
        logger.info("=" * 60)
        
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

                # 任务4: 将合并后的文件写入时序数据库
                FileImportService._import_cleaned_file_to_tsdb(session)

            logger.info("PID文件维护任务执行完成")
            
        except Exception as e:
            logger.error(f"PID文件维护任务执行失败: {str(e)}")
    
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
        # 获取所有块
        blocks = FileMetaService.get_blocks(session, file.fid)
        if blocks:
            logger.debug(f"正在合并文件块: {file.name} (fid={file.fid})")
            block_names = [b.block_name for b in blocks]
            try:
                FileStoreService.merge_blocks(file, block_names)
            except Exception as e:
                msg = f"文件块合并失败 (fid={file.fid}): {str(e)}"
                FileMetaService.mark_as(session, file.fid, FileStatus.MERGE_FAILED, msg[:512])
                raise e
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
    def _import_cleaned_file_to_tsdb(session: Session):
        """
        将数据文件导入 TSDB

        Args:
            session: 数据库会话
        """
        # 查询所有状态为CLEANED的文件
        cleaned_files = FileMetaService.get_files_by_status(session, FileStatus.CLEANED)

        if not cleaned_files:
            logger.info("没有状态为CLEANED的文件需要导入到时序数据库")
            return

        logger.info(f"发现 {len(cleaned_files)} 个CLEANED状态的文件需要导入到时序数据库")

        for file in cleaned_files:
            try:
                # 构建文件路径
                file_path = FileStoreService.get_block_file_path(file.fid, file.upload_id)

                # 检查文件是否存在
                if not os.path.exists(file_path):
                    logger.error(f"文件不存在: {file_path}")
                    continue

                # 读取CSV文件
                try:
                    df = pd.read_csv(file_path)
                except Exception as e:
                    msg = f"读取CSV文件失败 (fid={file.fid}): {str(e)}"
                    FileMetaService.mark_as(session, file.fid, FileStatus.IMPORT_FAILED, msg[:512])
                    logger.error(msg)
                    continue

                # 验证表头
                expected_columns = ["timestamp", "loop_tag", "SV", "PV", "MV", "PB", "TI", "TD"]
                if list(df.columns) != expected_columns:
                    msg = f"CSV文件表头不正确 (fid={file.fid})，期望: {expected_columns}，实际: {list(df.columns)}"
                    FileMetaService.mark_as(session, file.fid, FileStatus.IMPORT_FAILED, msg[:512])
                    logger.error(msg)
                    continue

                # 处理数据导入
                num_records = len(df)
                FileImportService._send_data_to_tsdb(session, df, file.fid)

                # 成功导入后，将文件状态更新为IMPORTED
                FileMetaService.mark_as(session, file.fid, FileStatus.IMPORTED)
                logger.info(f"文件成功导入到时序数据库: {file.name} (fid={file.fid}), 导入记录数: {num_records}")
            except requests.exceptions.RequestException as e:
                logger.error(f"导入文件到时序数据库失败 (fid={file.fid}): {str(e)}")
            except Exception as e:
                logger.error(f"导入文件到时序数据库失败 (fid={file.fid}): {str(e)}")
                # 发生异常时，可以考虑将文件状态更新为导入失败
                FileMetaService.mark_as(session, file.fid, FileStatus.IMPORT_FAILED, str(e))

        pass

    @staticmethod
    def _send_data_to_tsdb(session, df, fid):
        """
        将DataFrame数据发送到时序数据库

        Args:
            session: 数据库会话
            df: 包含PID数据的DataFrame
            file: 文件对象，用于获取设备信息
        """
        # 处理时间戳格式 - 智能识别时间戳单位
        FileImportService._process_timestamps(df)

        count = 0
        progress_limit = 5000
        # 获取 df 记录数量
        total_records = len(df)

        # 按设备（loop_tag）分组处理数据
        for device_name in df['loop_tag'].unique():
            device_data = df[df['loop_tag'] == device_name]

            # 按1000条记录为一批次处理数据
            batch_size = 1000
            num_records = len(device_data)

            for start_idx in range(0, num_records, batch_size):
                end_idx = min(start_idx + batch_size, num_records)
                batch_data = device_data.iloc[start_idx:end_idx]

                # 获取批次的毫秒时间戳
                timestamps = [ts for ts in batch_data['ts']]

                # 定义测量值和数据类型
                measurements = ["SV", "PV", "MV", "PB", "TI", "TD"]
                data_types = ["DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE", "DOUBLE"]

                # 组装values数组
                values = []
                for measurement in measurements:
                    measurement_values = batch_data[measurement].tolist()
                    # 处理空值
                    processed_values = []
                    for val in measurement_values:
                        if pd.isna(val):
                            processed_values.append(None)
                        else:
                            processed_values.append(val)
                    values.append(processed_values)

                # 构建请求体
                request_body = {
                    "timestamps": timestamps,
                    "measurements": measurements,
                    "data_types": data_types,
                    "values": values,
                    "is_aligned": False,
                    "device": f"{device_name}default"
                }

                # 发送HTTP请求
                db_name = settings.db_name
                url = f"{settings.db_base_url}/api/v1/telemetry/insertTablet?db={db_name}"

                response = requests.post(
                    url,
                    json=request_body,
                    headers={"Content-Type": "application/json"},
                    timeout=30  # 设置超时时间
                )

                if response.status_code != 200:
                    logger.error(f"发送数据到时序数据库失败, 响应: {response.text}")
                else:
                    count += len(timestamps)
                    if count >= progress_limit:
                        progress_limit += 5000
                        logger.info(f"(fid={fid})已导入 {count} 条数据, 总记录数量 {total_records}")

    @staticmethod
    def _process_timestamps(df):
        """
        处理时间戳格式，将timestamp列转换为毫秒时间戳并存储到ts列

        Args:
            df: 包含timestamp列的DataFrame

        Returns:
            处理后的时间戳DataFrame
        """
        # 处理timestamp列，将其转换为毫秒时间戳
        processed_timestamps = []

        for ts_str in df['timestamp']:
            # 使用pandas解析时间戳，支持 "2026-01-04 15:20:30.000" 和 "2026-01-04 15:20:30" 两种格式
            parsed_ts = pd.to_datetime(ts_str).tz_localize('Asia/Shanghai')
            # 转换为毫秒时间戳
            timestamp_ms = int(parsed_ts.timestamp() * 1000)
            processed_timestamps.append(timestamp_ms)

        # 添加新的ts列（毫秒时间戳）
        df['ts'] = processed_timestamps

    @staticmethod
    def run_import():
        """
        运行文件导入定期维护任务
        每10秒调用一次 do_import_file，该函数将被一个独立的进程调用
        """
        import time

        # 设置主机端口
        host = Addressing.get_ipv4_address()
        port = config.SERVER_PORT
        settings.host_port = Addressing.create_host_and_port_str(host, port)

        # 设置存储目录
        settings.storage_dir = config.PID_DATA_FILE_DIR

        # 设置数据库信息
        settings.db_base_url = config.PID_DATA_DB_BASE_URL
        settings.db_name = config.PID_DATA_DB_NAME

        # 输出配置信息
        logger.info(f"PID文件导入配置信息: {settings}")
        
        logger.info(f"开始运行PID文件导入定期维护任务")

        # TODO: 添加任务队列
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