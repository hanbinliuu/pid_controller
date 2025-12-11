#!/usr/bin/env python3
"""
批量查询优化工具
提供数据批量查询和缓存优化功能
"""

import logging
from typing import List, Dict, Any, Optional
from functools import lru_cache
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BatchQueryOptimizer:
    """批量查询优化器"""
    
    @staticmethod
    def chunk_list(items: List[Any], chunk_size: int = 100) -> List[List[Any]]:
        """
        将列表分块处理
        
        Args:
            items: 待分块的列表
            chunk_size: 每块的大小
            
        Returns:
            分块后的列表
        """
        return [items[i:i + chunk_size] for i in range(0, len(items), chunk_size)]
    
    @staticmethod
    def batch_query_with_cache(
        query_func,
        item_list: List[Any],
        batch_size: int = 100,
        cache_key_func=None
    ) -> Dict[Any, Any]:
        """
        批量查询带缓存
        
        Args:
            query_func: 查询函数
            item_list: 查询项列表
            batch_size: 批量大小
            cache_key_func: 缓存键生成函数
            
        Returns:
            查询结果字典
        """
        results = {}
        chunks = BatchQueryOptimizer.chunk_list(item_list, batch_size)
        
        for i, chunk in enumerate(chunks):
            try:
                chunk_results = query_func(chunk)
                results.update(chunk_results)
                logger.debug(f"批量查询进度: {(i+1)*batch_size}/{len(item_list)}")
            except Exception as e:
                logger.error(f"批量查询失败 (chunk {i+1}): {str(e)}")
        
        return results
    
    @staticmethod
    @lru_cache(maxsize=128)
    def get_cached_query_result(cache_key: str, ttl_seconds: int = 300):
        """
        获取缓存的查询结果
        
        Args:
            cache_key: 缓存键
            ttl_seconds: 缓存时间（秒）
            
        Returns:
            缓存结果或None
        """
        # 这里可以集成Redis或其他缓存系统
        return None
    
    @staticmethod
    def optimize_query_plan(
        query_list: List[Dict[str, Any]],
        merge_similar: bool = True
    ) -> List[Dict[str, Any]]:
        """
        优化查询计划，合并相似查询
        
        Args:
            query_list: 查询列表
            merge_similar: 是否合并相似查询
            
        Returns:
            优化后的查询列表
        """
        if not merge_similar:
            return query_list
        
        # 按时间范围和数据库分组
        grouped_queries = {}
        for query in query_list:
            key = (
                query.get('db'),
                query.get('start_time'),
                query.get('end_time'),
                query.get('window')
            )
            if key not in grouped_queries:
                grouped_queries[key] = []
            grouped_queries[key].append(query)
        
        # 合并同组查询
        optimized_queries = []
        for key, queries in grouped_queries.items():
            if len(queries) == 1:
                optimized_queries.extend(queries)
            else:
                # 合并多个表的查询
                merged_query = {
                    'db': key[0],
                    'start_time': key[1],
                    'end_time': key[2],
                    'window': key[3],
                    'tables': [q.get('table') for q in queries],
                    'fields_map': {q.get('table'): q.get('fields') for q in queries}
                }
                optimized_queries.append(merged_query)
        
        logger.info(f"查询优化: {len(query_list)} -> {len(optimized_queries)}")
        return optimized_queries


class DataPreloader:
    """数据预加载器"""
    
    def __init__(self, max_cache_size: int = 1000):
        """
        初始化预加载器
        
        Args:
            max_cache_size: 最大缓存大小
        """
        self.cache = {}
        self.max_cache_size = max_cache_size
        self.access_count = {}
    
    def preload_data(
        self,
        data_loader,
        keys: List[str],
        batch_size: int = 50
    ):
        """
        预加载数据到缓存
        
        Args:
            data_loader: 数据加载函数
            keys: 数据键列表
            batch_size: 批量加载大小
        """
        chunks = BatchQueryOptimizer.chunk_list(keys, batch_size)
        
        for chunk in chunks:
            try:
                results = data_loader(chunk)
                for key, value in results.items():
                    self._add_to_cache(key, value)
            except Exception as e:
                logger.error(f"数据预加载失败: {str(e)}")
    
    def _add_to_cache(self, key: str, value: Any):
        """添加数据到缓存"""
        if len(self.cache) >= self.max_cache_size:
            # 移除访问次数最少的项
            min_access_key = min(self.access_count, key=self.access_count.get)
            del self.cache[min_access_key]
            del self.access_count[min_access_key]
        
        self.cache[key] = value
        self.access_count[key] = 0
    
    def get_from_cache(self, key: str) -> Optional[Any]:
        """从缓存获取数据"""
        if key in self.cache:
            self.access_count[key] += 1
            return self.cache[key]
        return None
    
    def clear_cache(self):
        """清空缓存"""
        self.cache.clear()
        self.access_count.clear()


# 全局批量查询优化器实例
_global_optimizer = BatchQueryOptimizer()


def get_batch_optimizer() -> BatchQueryOptimizer:
    """获取全局批量查询优化器实例"""
    return _global_optimizer
