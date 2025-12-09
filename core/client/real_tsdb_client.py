#!/usr/bin/env python3
"""
实际时序数据库客户端
用于连接真实的时序数据库服务，执行HTTP查询
"""

import os
from datetime import datetime

import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from api.routes.time_util import format_time_to_string
from core.client.tsdb_data_source import DataPoint, TSDBDataSource
from core.config import Config

# 设置日志
logger = logging.getLogger(__name__)


@dataclass
class TSDBConfig:
    """时序数据库配置"""
    base_url: str
    timeout: int = 30
    max_retries: int = 3
    auth_token: Optional[str] = None
    headers: Optional[Dict[str, str]] = None


class RealTSDBDataSource(TSDBDataSource):
    """实际时序数据库数据源（通过HTTP API查询）"""
    
    def __init__(self, config: Optional[TSDBConfig] = None):
        """
        初始化实际时序数据库客户端
        
        Args:
            config: 时序数据库配置，如果为None则从环境变量或默认配置读取
        """
        if config is None:
            config = self._load_config_from_env()
        
        self.config = config
        self.session = requests.Session()
        
        # 设置默认请求头
        default_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'PID-Agent-TSDB-Client/1.0'
        }
        
        if config.headers:
            default_headers.update(config.headers)
            
        if config.auth_token:
            default_headers['Authorization'] = f'Bearer {config.auth_token}'
            
        self.session.headers.update(default_headers)
        
        # 设置超时（注意：requests.Session 没有 timeout 属性，需要在请求时传递）
        self.default_timeout = config.timeout
        
        logger.info(f"初始化TSDB客户端，连接到: {config.base_url}")
    
    def _load_config_from_env(self) -> TSDBConfig:
        """从环境变量加载配置"""
        # 优先从环境变量读取
        base_url = Config.TSDB_BASE_URL
        
        # 如果环境变量没有设置，使用默认配置
        if not base_url:
            # 使用代码中的默认URL
            base_url = 'http://tsdb-select-infra-system.sit-cloud.ieccloud.hollicube.com'
            logger.warning(f"未找到TSDB_BASE_URL环境变量，使用默认URL: {base_url}")
        
        return TSDBConfig(
            base_url=base_url,
            timeout=int(os.getenv('TSDB_TIMEOUT', '30')),
            max_retries=int(os.getenv('TSDB_MAX_RETRIES', '3')),
            auth_token=os.getenv('TSDB_AUTH_TOKEN')
        )
    
    def query_raw_data(
        self,
        db: Optional[str] = None,
        table: Optional[str] = None, 
        fields: Optional[List[str]] = None,
        tags: Optional[Dict[str, str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 1500,
        continuation_point: Optional[str] = None
    ) -> DataPoint:
        """
        查询实际时序数据库的原始数据
        
        Args:
            db: 数据库名称
            table: 表名
            fields: 字段列表
            tags: 标签过滤
            start_time: 开始时间（毫秒时间戳）
            end_time: 结束时间（毫秒时间戳）
            limit: 数据条数限制
            continuation_point: 续传点
            
        Returns:
            DataPoint: 查询到的数据点
        """
        # 检查必需参数
        if not table:
            return DataPoint(columns=[], values=[])
        
        try:
            # 构造查询请求
            request_payload = {
                "tables": [
                    {
                        "table": table,
                        "fields": fields,
                        "tags": tags,
                        "continuationPoint": continuation_point
                    }
                ],
                "detail": {
                    "startTime": start_time,
                    "endTime": end_time,
                    "limit": limit,
                    "returnBounds": False
                }
            }
            
            # 发送HTTP请求
            url = f"{self.config.base_url}/tsdb/v4/read_raw"
            if db:
                url += f"?db={db}"
            logger.info(f"发送TSDB查询请求到: {url}")
            # logger.info(f"请求参数: {json.dumps(request_payload, indent=2)}")
            
            response = self._make_request_with_retry('POST', url, json=request_payload)
            
            if response.status_code == 200:
                result = response.json()
                # logger.info(f"发送TSDB查询请求到: {result}")
                return self._parse_response(result, table)
            else:
                logger.error(f"TSDB查询失败，状态码: {response.status_code}, 响应: {response.text}")
                return DataPoint(columns=[], values=[])
                
        except Exception as e:
            logger.error(f"查询TSDB数据时发生异常: {str(e)}")
            return DataPoint(columns=[], values=[])

    #时序差值数据查询
    def query_read_interpolated(
        self,
        db: Optional[str] = None,
        table: Optional[str] = None,
        fields: Optional[List[str]] = None,
        tags: Optional[Dict[str, str]] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 3000,
        window: int= 1,
        continuation_point: Optional[str] = None
    ) -> DataPoint:
        """
               查询实际时序数据库的插值数据（支持分页查询）

               Args:
                   db: 数据库名称
                   table: 表名
                   fields: 字段列表
                   tags: 标签过滤
                   start_time: 开始时间（毫秒时间戳），未传则默认为最近1小时前
                   end_time: 结束时间（毫秒时间戳），未传则默认为当前时间
                   limit: 数据条数限制
                   window: 插值间隔（s）
                   continuation_point: 续传点

               Returns:
                   DataPoint: 查询到的数据点（包含所有分页数据）
               """
        begin_time = datetime.now().timestamp()

        # 检查必需参数
        if not table:
            return DataPoint(columns=[], values=[])

        try:
            all_values = []  # 存储所有分页的数据
            all_columns = None  # 存储列信息
            all_tags = None  # 存储标签信息
            current_continuation_point = continuation_point
            page_count = 0
            max_pages = 100  # 最大分页数
            
            logger.info(f"开始循环分页查询TSDB数据，表: {table}, 时间范围: {format_time_to_string(start_time)} - {format_time_to_string(end_time)}")

            while page_count < max_pages:
                page_count += 1
                # logger.info(f"========== 第{page_count}页查询开始 ==========" )
                # logger.info(f"当前continuation_point: {current_continuation_point}")
                
                # 构造查询请求
                request_payload = {
                    "tables": [
                        {
                            "table": table,
                            "fields": fields,
                            "tags": tags,
                            "continuationPoint": current_continuation_point
                        }
                    ],
                    "detail": {
                        "startTime": start_time,
                        "endTime": end_time,
                        "limit": limit,
                        "window": window
                    }
                }

                # 发送HTTP请求
                url = f"{self.config.base_url}/tsdb/v4/read_interpolated"
                if db:
                    url += f"?db={db}"
                # logger.info(f"发送TSDB查询请求到: {url}")
                response = self._make_request_with_retry('POST', url, json=request_payload)
                if response.status_code == 200:
                    result = response.json()
                    # 解析当前页数据
                    page_data = self._parse_response(result, table)
                    # 如果当前页无数据，退出循环
                    if not page_data.values:
                        # logger.warning(f"第{page_count}页无数据返回，查询结束")
                        break
                    # 保存列信息和标签信息（第一页）
                    if all_columns is None:
                        all_columns = page_data.columns
                        all_tags = page_data.tags
                    # 合并当前页数据
                    all_values.extend(page_data.values)
                    if page_data.continuation_point:
                        current_continuation_point = page_data.continuation_point
                    else:
                        break
                else:
                    logger.error(f"TSDB查询失败，状态码: {response.status_code}, 响应: {response.text}")
                    break
            
            # if page_count >= max_pages:
                # logger.warning(f"达到最大分页数限制({max_pages})，停止查询")
            
            # logger.info(f"========== 循环查询完成 ==========" )
            # # logger.info(f"数据: {all_values}")
            # logger.info(f"总查询页数: {page_count}")
            # logger.info(f"总数据条数: {len(all_values)}")
            over_time = datetime.now().timestamp()
            logger.info(f"表: {table},时序查询总耗时: {(over_time)-(begin_time)}")

            # 返回合并后的所有数据
            return DataPoint(
                tags=all_tags,
                columns=all_columns,
                values=all_values,
                continuation_point=None  # 已获取全部数据，不再有续传点
            )

        except Exception as e:
            logger.error(f"查询TSDB数据时发生异常: {str(e)}")
            return DataPoint(columns=[], values=[])

    
    def _parse_response(self, response_data: Dict, table: str) -> DataPoint:
        """
        解析TSDB响应数据
        
        Args:
            response_data: TSDB响应数据
            table: 查询的表名
            
        Returns:
            DataPoint: 解析后的数据点
        """
        try:
            if response_data.get('code') != 0:
                logger.error(f"TSDB返回错误: {response_data.get('message', '未知错误')}")
                return DataPoint(columns=[], values=[])
            
            results = response_data.get('results', [])
            if not results:
                logger.warning(f"未找到表 {table} 的数据")
                return DataPoint(columns=[], values=[])
            
            # 查找对应表的结果
            table_result = None
            for result in results:
                if result.get('table') == table:
                    table_result = result
                    break
            
            if not table_result:
                logger.warning(f"未找到表 {table} 的查询结果")
                return DataPoint(columns=[], values=[])
            
            # 解析数据
            data_list = table_result.get('data', [])
            if not data_list:
                return DataPoint(columns=[], values=[])
            
            # 获取第一个数据块（通常只有一个）
            data_point = data_list[0]
            
            # 提取续传点（如果存在）
            continuation_point = table_result.get('continuationPoint')

            return DataPoint(
                tags=data_point.get('tags'),
                columns=data_point.get('columns', []),
                values=data_point.get('values', []),
                continuation_point=continuation_point
            )
            
        except Exception as e:
            logger.error(f"解析TSDB响应时发生异常: {str(e)}")
            return DataPoint(columns=[], values=[])
    
    def _make_request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        """
        带重试机制的HTTP请求
        
        Args:
            method: HTTP方法
            url: 请求URL
            **kwargs: 其他请求参数
            
        Returns:
            requests.Response: HTTP响应
        """
        last_exception = None
        
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.request(method, url, timeout=self.default_timeout, **kwargs)
                
                # 如果是成功响应或客户端错误（不需要重试），直接返回
                if response.status_code < 500:
                    return response
                    
                logger.warning(f"TSDB请求失败 (尝试 {attempt + 1}/{self.config.max_retries}): "
                             f"状态码 {response.status_code}")
                
            except requests.exceptions.RequestException as e:
                last_exception = e
                logger.warning(f"TSDB请求异常 (尝试 {attempt + 1}/{self.config.max_retries}): {str(e)}")
                
                # 如果不是最后一次尝试，等待一下再重试
                if attempt < self.config.max_retries - 1:
                    import time
                    time.sleep(1)
        
        # 所有重试都失败了
        if last_exception:
            raise last_exception
        else:
            raise requests.exceptions.RequestException(f"TSDB请求失败，已重试 {self.config.max_retries} 次")
    

    # todo 连接测试
    def test_connection(self) -> bool:
        """
        测试与TSDB服务的连接
        
        Returns:
            bool: 连接是否成功
        """
        try:
            # 尝试访问健康检查接口
            health_endpoints = [
                f"{self.config.base_url}/health",
            ]
            
            for endpoint in health_endpoints:
                try:
                    response = self.session.get(endpoint, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"TSDB连接测试成功: {endpoint}")
                        return True
                except requests.exceptions.RequestException:
                    continue
            
            return False
        except Exception as e:
            logger.error(f"TSDB连接测试异常: {str(e)}")
            return False
    
    def get_db_data_size(self, database: Optional[str] = None) -> str:
        """
        获取数据库表列表
        
        Args:
            database: 数据库名称
            
        Returns:
            List[str]: 表名列表
        """
        try:
            url = f"{self.config.base_url}/get/disk/used"
            if database:
                url += f"?db={database}"
            
            response = self._make_request_with_retry('GET', url)
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get('code') == 0:
                    data = result.get('results', {})
                    return data
                else:
                    logger.error(f"获取表列表失败: {result.get('message', '未知错误')}")
            else:
                logger.error(f"获取表列表失败，状态码: {response.status_code}")
                
        except Exception as e:
            logger.error(f"获取表列表时发生异常: {str(e)}")
        
        return ""


class TSDBClientFactory:
    """时序数据库客户端工厂"""
    
    @staticmethod
    def create_client( config: Optional[TSDBConfig] = None) -> TSDBDataSource:
        """
        创建时序数据库客户端
        
        Args:
            config: TSDB配置
        Returns:
            TSDBDataSource: 数据源实例
        """
        # 如果没有指定，从环境变量读取
        return RealTSDBDataSource(config)
    
    @staticmethod
    def create_real_client(
        base_url: Optional[str] = None,
        timeout: int = 30,
        auth_token: Optional[str] = None
    ) -> RealTSDBDataSource:
        """
        创建实际TSDB客户端的便捷方法
        
        Args:
            base_url: TSDB服务地址
            timeout: 超时时间
            auth_token: 认证令牌
            
        Returns:
            RealTSDBDataSource: 实际TSDB数据源
        """
        if base_url is None:
            base_url = Config.TSDB_BASE_URL
        
        config = TSDBConfig(
            base_url=base_url,
            timeout=timeout,
            auth_token=auth_token
        )
        
        return RealTSDBDataSource(config)


# 全局客户端实例缓存
_global_tsdb_client = None


def get_configured_tsdb_client() -> TSDBDataSource:
    """
    获取配置的TSDB客户端实例（单例模式）
    
    Returns:
        TSDBDataSource: 配置的TSDB客户端
    """
    global _global_tsdb_client
    if _global_tsdb_client is None:
        _global_tsdb_client = TSDBClientFactory.create_client()
    
    return _global_tsdb_client

def get_default_database() -> str:
    """
    获取默认数据库名称，优先从环境变量读取

    Returns:
        str: 数据库名称
    """
    return os.getenv('DEFAULT_TSDB_DATABASE', 'platform')

# 单点位
def query_raw_data(
    db:str,
    table: str,
    fields: Optional[List[str]] = None,
    tags: Optional[Dict[str, str]] = None,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    limit: int = 1500
) -> DataPoint:
    """
    查询TSDB数据的便捷函数
    
    Args:
        db: 命名空间
        table: 表名
        fields: 字段列表
        tags: 标签过滤
        start_time: 开始时间（毫秒时间戳）
        end_time: 结束时间（毫秒时间戳）
        limit: 数据条数限制
        use_real_tsdb: 是否使用真实TSDB
        
    Returns:
        DataPoint: 查询结果
    """
    client = TSDBClientFactory.create_client()
    return client.query_raw_data(
        db=db,
        table=table,
        fields=fields,
        tags=tags,
        start_time=start_time,
        end_time=end_time,
        limit=limit
    )


# 间隔值
def query_read_interpolated(
        db: str,
        table: str,
        fields: Optional[List[str]] = None,
        tags: Optional[Dict[str, str]] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 3000,
        window: int = 1,
        continuation_point: Optional[str] = None
) -> DataPoint:
    """
    查询TSDB插值数据的便捷函数

    Args:
        db: 命名空间
        table: 表名
        fields: 字段列表
        tags: 标签过滤
        start_time: 开始时间（毫秒时间戳），未传则默认为最近1小时前
        end_time: 结束时间（毫秒时间戳），未传则默认为当前时间
        limit: 数据条数限制
        window: 插值间隔（s）
        continuation_point: 续传点，用于分页查询

    Returns:
        DataPoint: 查询结果（如未传时间参数，默认查询最近1小时数据）
    """
    client = TSDBClientFactory.create_client()
    return client.query_read_interpolated(
        db=db,
        table=table,
        fields=fields,
        tags=tags,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        window=window,
        continuation_point=continuation_point
    )