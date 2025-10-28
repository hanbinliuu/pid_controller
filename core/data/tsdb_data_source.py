from dataclasses import dataclass
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


@dataclass
class TableQuery:
    """表查询配置"""
    db: str  # 必填，数据库名
    table: str  # 必填，表名
    fields: Optional[List[str]] = None  # 非必填，字段列表
    tags: Optional[Dict[str, str]] = None  # 非必填，标签过滤
    continuation_point: Optional[str] = None  # 续传点


@dataclass
class QueryDetail:
    """查询详细配置"""
    start_time: int  # 必填，查询开始时间（毫秒时间戳）
    end_time: Optional[int] = None  # 非必填，查询结束时间
    limit: int = 1500  # 非必填，每个表返回的最大数据条数
    return_bounds: bool = False  # 非必填，是否返回边界


@dataclass
class QueryRequest:
    """查询请求"""
    tables: List[TableQuery]  # 表查询列表
    detail: QueryDetail  # 查询详细配置

    def validate(self) -> bool:
        """验证请求参数"""
        # 检查 tables 中是否有重复的 table
        table_names = [t.table for t in self.tables]
        if len(table_names) != len(set(table_names)):
            raise ValueError("tables 中不可以有相同的 table")

        # 检查必填字段
        for table_query in self.tables:
            if not table_query.table:
                raise ValueError("table 字段为必填项")

        if not self.detail.start_time:
            raise ValueError("startTime 字段为必填项")

        return True


@dataclass
class DataPoint:
    """数据点"""
    tags: Optional[Dict[str, str]] = None
    columns: Optional[List[str]] = None
    values: Optional[List[List[Any]]] = None


@dataclass
class TableResult:
    """表查询结果"""
    table: str
    data: List[DataPoint]
    continuation_point: Optional[str] = None


@dataclass
class QueryResponse:
    """查询响应"""
    code: int = 0
    message: str = ""
    results: Optional[List[TableResult]] = None

    def to_dict(self) -> Dict:
        """转换为字典格式"""
        result = {
            "code": self.code,
            "message": self.message,
            "results": []
        }

        if self.results:
            for table_result in self.results:
                table_dict = {
                    "table": table_result.table,
                    "data": []
                }

                for data_point in table_result.data:
                    point_dict = {
                        "columns": data_point.columns or [],
                        "values": data_point.values or []
                    }
                    if data_point.tags:
                        point_dict["tags"] = data_point.tags
                    table_dict["data"].append(point_dict)

                if table_result.continuation_point:
                    table_dict["continuation_point"] = table_result.continuation_point

                result["results"].append(table_dict)

        return result


class TSDBDataSource(ABC):
    """时序数据库数据源抽象接口"""

    @abstractmethod
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
        """ todo 查询原始数据"""
        pass

    @abstractmethod
    def query_read_interpolated(
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
        """ todo 查询历史插值数据"""
        pass
