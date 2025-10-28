#!/usr/bin/env python3
"""
时序数据库历史原始值查询模块
实现 TSDB v4 历史原始值查询接口
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from core.data.tsdb_data_source import TSDBDataSource, DataPoint, QueryRequest, QueryResponse, TableResult, QueryDetail,TableQuery

class MockTSDBDataSource(TSDBDataSource):
    """模拟时序数据库数据源（从CSV文件读取数据）"""
    
    def __init__(self):
        import os
        # 设置CSV文件目录路径
        self.csv_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "simulated")
        
        # 缓存已读取的CSV数据，避免重复读取
        self._csv_cache = {}
        
        # 模拟数据存储（保留原有测试数据作为备用）
        self.mock_data = {
            "cpu": {
                "fields": ["time", "f1", "f2"],
                "data": [
                    {"time": "2022-07-08 13:36:02.523", "f1": 1, "f2": None, "host": "node1"},
                    {"time": "2022-07-08 13:36:03.523", "f1": 1, "f2": 2, "host": "node1"},
                    {"time": "2022-07-08 13:36:04.523", "f1": 2, "f2": 3, "host": "node2"},
                ]
            },
            "ns-01f-001": {
                "fields": ["time", "s", "v"],
                "data": [
                    {"time": "2022-07-01 08:49:10.000", "s": 0, "v": 12.3},
                    {"time": "2022-07-01 08:49:11.000", "s": 1, "v": 13.5},
                ]
            }
        }
    
    def _load_csv_data(self, table: str) -> Optional[Dict]:
        """从CSV文件加载数据"""
        try:
            import pandas as pd
        except ImportError:
            print("警告: pandas 未安装，无法读取 CSV 文件")
            return None
            
        import os
        
        # 检查缓存
        if table in self._csv_cache:
            return self._csv_cache[table]
        
        # 构造CSV文件路径
        csv_file = os.path.join(self.csv_dir, f"{table}.csv")
        
        if not os.path.exists(csv_file):
            return None
        
        try:
            # 读取CSV文件
            df = pd.read_csv(csv_file)
            
            # 转换为字典格式
            data_records = []
            for _, row in df.iterrows():
                record = row.to_dict()
                data_records.append(record)
            
            # 获取字段列表
            fields = list(df.columns)
            
            csv_data = {
                "fields": fields,
                "data": data_records
            }
            
            # 缓存数据
            self._csv_cache[table] = csv_data
            return csv_data
            
        except Exception as e:
            print(f"读取CSV文件失败: {csv_file}, 错误: {str(e)}")
            return None
    
    def query_raw_data(
        self, 
        db: Optional[str] = None,
        table: Optional[str] = None, 
        fields: Optional[List[str]] = None,
        tags: Optional[Dict[str, str]] = None,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1500,
        continuation_point: Optional[str] = None
    ) -> DataPoint:
        """查询原始数据"""
        # 检查必需参数
        if not table:
            return DataPoint(columns=[], values=[])
            
        # 首先尝试从CSV文件加载数据
        table_info = self._load_csv_data(table)
        
        # 如果CSV文件不存在，则使用内置的模拟数据
        if table_info is None:
            if table not in self.mock_data:
                return DataPoint(columns=[], values=[])
            table_info = self.mock_data[table]
        
        data_records = table_info["data"]
        
        # 处理字段过滤
        if fields is None:
            fields = table_info["fields"]
        else:
            # 确保请求的字段在数据中存在
            available_fields = table_info["fields"]
            fields = [f for f in fields if f in available_fields]
            
            # 如果是CSV数据且包含time/timestamp字段，确保时间字段包含在内
            if "timestamp" in available_fields and "timestamp" not in fields:
                fields = ["timestamp"] + fields
            elif "time" in available_fields and "time" not in fields:
                fields = ["time"] + fields
        
        # 时间范围过滤（针对CSV数据）
        filtered_data = []
        for record in data_records:
            # 时间过滤
            if start_time is not None or end_time is not None:
                record_time = None
                # 尝试获取时间戳
                if "timestamp" in record:
                    record_time = record["timestamp"]
                elif "time" in record:
                    # 如果time字段是字符串，尝试转换为时间戳
                    time_value = record["time"]
                    if isinstance(time_value, str):
                        try:
                            from datetime import datetime
                            dt = datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S.%f")
                            record_time = int(dt.timestamp() * 1000)
                        except:
                            try:
                                from datetime import datetime
                                dt = datetime.strptime(time_value, "%Y-%m-%d %H:%M:%S")
                                record_time = int(dt.timestamp() * 1000)
                            except:
                                record_time = None
                    else:
                        record_time = time_value
                
                # 应用时间过滤
                if record_time is not None:
                    if start_time is not None and record_time < start_time:
                        continue
                    if end_time is not None and record_time > end_time:
                        continue
            
            # 处理标签过滤
            if tags:
                match = True
                for tag_key, tag_value in tags.items():
                    if record.get(tag_key) != tag_value:
                        match = False
                        break
                if match:
                    filtered_data.append(record)
            else:
                filtered_data.append(record)
        
        # 应用 limit
        if len(filtered_data) > limit:
            filtered_data = filtered_data[:limit]
        
        # 构造返回数据
        values = []
        if fields:  # 检查 fields 不为 None
            for record in filtered_data:
                row = []
                for field in fields:
                    row.append(record.get(field))
                values.append(row)
        
        # 构造 tags（如果有的话）
        result_tags = None
        if tags and filtered_data:
            result_tags = tags
        
        return DataPoint(
            tags=result_tags,
            columns=fields or [],
            values=values
        )

class TimeParamQueryEngine:
    """时序参数查询引擎"""
    
    def __init__(self, data_source: Optional[TSDBDataSource] = None, use_real_tsdb: bool = False):
        """
        初始化查询引擎
        
        Args:
            data_source: 数据源实例，如果为None则根据use_real_tsdb参数选择
            use_real_tsdb: 是否使用真实TSDB服务
        """
        if data_source is not None:
            self.data_source = data_source
        elif use_real_tsdb:
            # 尝试导入实际TSDB客户端
            try:
                from .real_tsdb_client import TSDBClientFactory
                self.data_source = TSDBClientFactory.create_real_client()
                print("️ 使用实际TSDB客户端")
            except ImportError as e:
                print(f" 无法导入实际TSDB客户端: {e}，回退到模拟数据源")
                self.data_source = MockTSDBDataSource()
        else:
            self.data_source = MockTSDBDataSource()

    """
    读取历史原始值
    """
    def read_raw(self, request: QueryRequest, db: Optional[str] = None) -> QueryResponse:
        try:
            # 验证请求参数
            request.validate()
            
            results = []
            
            # 处理每个表的查询
            for table_query in request.tables:
                try:
                    # 查询单个表的数据
                    data_point = self.data_source.query_raw_data(
                        db=db,
                        table=table_query.table,
                        fields=table_query.fields,
                        tags=table_query.tags,
                        start_time=request.detail.start_time,
                        end_time=request.detail.end_time,
                        limit=request.detail.limit,
                        continuation_point=table_query.continuation_point
                    )
                    
                    # 构造表结果
                    table_result = TableResult(
                        table=table_query.table,
                        data=[data_point] if data_point.values else [],
                        continuation_point=None  # 实际实现中应该根据数据量来设置
                    )
                    
                    # 检查是否需要设置 continuation_point
                    if (data_point.values and 
                        len(data_point.values) >= request.detail.limit):
                        # 生成续传点（实际实现中应该包含表名和时间戳）
                        last_time = data_point.values[-1][0] if data_point.values else ""
                        table_result.continuation_point = f"{table_query.table}--{last_time}"
                    
                    results.append(table_result)
                    
                except Exception as e:
                    # 单个表查询失败不影响其他表
                    print(f"查询表 {table_query.table} 时出错: {str(e)}")
                    continue
            
            return QueryResponse(code=0, message="", results=results)
            
        except ValueError as e:
            return QueryResponse(code=400, message=str(e), results=[])
        except Exception as e:
            return QueryResponse(code=500, message=f"服务器内部错误: {str(e)}", results=[])

    """
    解析请求数据
    """
    def parse_request(self, request_data: Dict) -> QueryRequest:

        # 解析表查询列表
        tables = []
        for table_data in request_data.get("tables", []):
            table_query = TableQuery(
                db:=table_data.get("db"),
                table=table_data.get("table"),
                fields=table_data.get("fields"),
                tags=table_data.get("tags"),
                continuation_point=table_data.get("continuationPoint")
            )
            tables.append(table_query)
        
        # 解析查询详情
        detail_data = request_data.get("detail", {})
        detail = QueryDetail(
            start_time=detail_data.get("startTime"),
            end_time=detail_data.get("endTime"),
            limit=detail_data.get("limit", 1500),
            return_bounds=detail_data.get("returnBounds", False)
        )
        
        return QueryRequest(tables=tables, detail=detail)


# 工具函数
def timestamp_to_datetime_str(timestamp_ms: int) -> str:
    """将毫秒时间戳转换为日期时间字符串"""
    dt = datetime.fromtimestamp(timestamp_ms / 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def datetime_str_to_timestamp(datetime_str: str) -> int:
    """将日期时间字符串转换为毫秒时间戳"""
    try:
        # 尝试解析带毫秒的格式
        dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            # 尝试解析不带毫秒的格式
            dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(f"无法解析日期时间格式: {datetime_str}")
    
    return int(dt.timestamp() * 1000)


# 全局查询引擎实例
_query_engine = None

def get_query_engine(use_real_tsdb: Optional[bool] = None) -> TimeParamQueryEngine:
    """获取查询引擎实例（单例模式）
    
    Args:
        use_real_tsdb: 是否使用真实TSDB，如果为None则从环境变量读取
        
    Returns:
        TimeParamQueryEngine: 查询引擎实例
    """
    global _query_engine
    
    # 如果没有指定，从环境变量读取
    if use_real_tsdb is None:
        import os
        use_real_tsdb = os.getenv('USE_REAL_TSDB', 'false').lower() in ['true', '1', 'yes', 'on']
    
    # 如果已有实例且配置不变，直接返回
    if _query_engine is not None:
        # 检查是否需要更改数据源类型
        current_is_real = not isinstance(_query_engine.data_source, MockTSDBDataSource)
        if current_is_real == use_real_tsdb:
            return _query_engine
    
    # 创建新的查询引擎实例
    _query_engine = TimeParamQueryEngine(use_real_tsdb=use_real_tsdb)
    return _query_engine


def query_raw_data(request_data: Dict) -> Dict:
    """查询历史原始值的便捷函数
    
    Args:
        request_data: 请求数据字典（现在支持db参数）
        
    Returns:
        Dict: 响应数据字典
    """
    engine = get_query_engine()
    request = engine.parse_request(request_data)
    db = request_data.get("db")
    response = engine.read_raw(request, db=db)
    return response.to_dict()