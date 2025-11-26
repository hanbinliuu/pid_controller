#!/usr/bin/env python3
"""
BFF模型查询客户端
用于调用BFF聚合查询接口获取模型实时值
"""

import requests
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
import logging

from fastapi import HTTPException

from core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class InstanceInfo:
    """实例信息对象"""
    uri: str
    browseName: str
    displayName: str
    uriPath: str
    description: Optional[str] = None
    extendedAttr: Dict[str, Any] = field(default_factory=dict)


    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'InstanceInfo':
        """从BFF响应数据创建实例对象"""
        return cls(
            uri=data.get('uri', ''),
            browseName=data.get('browseName', ''),
            displayName=data.get('displayName', ''),
            uriPath=data.get('uriPath', ''),
            description=data.get('description'),
            extendedAttr=data.get('extendedAttr', {})
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'uri': self.uri,
            'browseName': self.browseName,
            'displayName': self.displayName,
            'uriPath': self.uriPath,
            'description': self.description,
            'extendedAttr': self.extendedAttr
        }


@dataclass
class PaginationInfo:
    """分页信息对象"""
    total: int = 0
    pages: int = 0
    pageNo: int = 1
    pageSize: int = 10

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'PaginationInfo':
        """从BFF响应数据创建分页对象"""
        return cls(
            total=data.get('total', 0),
            pages=data.get('pages', 0),
            pageNo=data.get('pageNo', 1),
            pageSize=data.get('pageSize', 10)
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'total': self.total,
            'pages': self.pages,
            'pageNo': self.pageNo,
            'pageSize': self.pageSize
        }





@dataclass
class PointInfo:
    """测点信息"""
    project_uri: str
    point_path: str
    point_name: str

    @classmethod
    def get_browse_path(self):
        """获取测点browse_path"""
        return f"{self.project_uri}/{self.point_path}/{self.point_name}"
    @classmethod
    def to_point_info(cls,project_uri: str,point_path:str,point_browse_path: str) -> 'PointInfo':
        """从BrowsePath获取PointInfo对象"""
        point = point_browse_path.split('/')
        if len(point) != 3:
            return PointInfo()

        """转换为PointInfo对象"""
        return cls(
            project_uri=project_uri,
            point_path=point_path,
            point_name=point[-1]
        )

@dataclass
class InstanceListResult:
    """实例列表查询结果对象"""
    instances: List[InstanceInfo] = field(default_factory=list)
    pagination: PaginationInfo = field(default_factory=PaginationInfo)
    error: Optional[str] = None

    @classmethod
    def from_bff_response(cls, result_data: Dict[str, Any], error: Optional[str] = None) -> 'InstanceListResult':
        """从BFF完整响应创建结果对象"""
        data_list = result_data.get('data', [])
        instances = [InstanceInfo.from_dict(item) for item in data_list]

        pagination = PaginationInfo.from_dict(result_data)

        return cls(
            instances=instances,
            pagination=pagination,
            error=error
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            'instances': [inst.to_dict() for inst in self.instances],
            'pagination': self.pagination.to_dict()
        }
        if self.error:
            result['error'] = self.error
        return result

    def __len__(self) -> int:
        """返回实例数量"""
        return len(self.instances)

    def __iter__(self):
        """支持迭代"""
        return iter(self.instances)

    def __getitem__(self, index: int) -> InstanceInfo:
        """支持索引访问"""
        return self.instances[index]


class BFFModelClient:
    """BFF模型查询客户端"""

    # 默认配置（从环境变量读取）
    DEFAULT_BASE_URL = Config.BFF_MODEL_BASE_URL
    DEFAULT_QUERY_PATH_VALUE_PATH = "/bff/aggquery/v2/model/queryValueByBrowsePath"
    DEFAULT_QUERY_CURRENT_RAW_VALUE_PATH = "/bff/aggquery/v2/query/v2/queryCurrentRawValueByBrowsePath"
    DEFAULT_LIST_INSTANCE_PATH = "/bff/v2/instance/listInstanceUnderInstanceTree"
    DEFAULT_GET_NEXT_LEVEL_SUBMODEL_PATH = "/bff/v2/model/getNextLevelSubModel"
    DEFAULT_QUERY_NODES_BY_URIS_PATH = "/bff/aggquery/v2/model/queryNodesByUris"
    DEFAULT_TIMEOUT = Config.BFF_MODEL_TIMEOUT
    DEFAULT_DEVICE_URI = Config.BFF_MODEL_PROJECT_PATH
    DEFAULT_POINT_PATH = Config.BFF_MODEL_POINT_PATH

    # pid控制字段与模型browse_name名称映照关系
    DEFAULT_PID_POINT_MAP = {
        'mv': 'MV',
        'pv': 'PV',
        'sv': 'SV',
        'pb': 'PB',
        'ti': 'TI',
        'td': 'TD'
    }

    def __init__(self, device_uri: Optional[str] = None, point_path: Optional[str] = None, pid_point_map:Dict[str, str] = None, timeout: int = None):
        """
        初始化BFF模型查询客户端
        
        Args:
            device_uri: 设备URI（如：/pid_zd/ce716ffbade5426e8faf18467d1d5a83），默认从环境变量 DEFAULT_DEVICE_URI 读取
            point_path: 测点相对路径，默认从环境变量 DEFAULT_POINT_PATH 读取
            pid_point_map：pid查询参数与测点名称映射关系，默认从DEFAULT_PID_POINT_MAP 读取
            timeout: 请求超时时间（秒），默认从环境变量 BFF_MODEL_TIMEOUT 读取
        """
        self.base_url = self.DEFAULT_BASE_URL
        self.device_uri = device_uri if device_uri is not None else self.DEFAULT_DEVICE_URI
        self.point_path = point_path if point_path is not None else self.DEFAULT_POINT_PATH
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.session = requests.Session()
        self.point_map = pid_point_map if pid_point_map is not None else self.DEFAULT_PID_POINT_MAP
        self.session.headers.update({
            'accept': '*/*',
            'Content-Type': 'application/json'
        })


    def query_values_by_browse_path(
            self,
            browse_paths: List[str]
    ) -> Dict[str, Any]:
        """
        根据浏览路径查询模型值（绑定测点路径）
        
        Args:
            browse_paths: 浏览路径列表
            
        Returns:
            查询结果字典
            
        Raises:
            requests.exceptions.RequestException: 请求失败时抛出
        """
        url = f"{self.base_url}{self.DEFAULT_QUERY_PATH_VALUE_PATH}"

        try:
            logger.info(f"查询BFF模型值，路径数量: {len(browse_paths)}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"浏览路径: {browse_paths[:3]}..." if len(browse_paths) > 3 else f"浏览路径: {browse_paths}")
            # 调用bff接口查询模型测点值
            response = self.session.post(
                url,
                json=browse_paths,
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

            logger.info(f"成功查询到 {len(result) if isinstance(result, list) else 1} 条数据")
            return result

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF模型查询失败: {str(e)}")
            raise

    def query_common_fields(self,model_point_names:List[str]=None) -> Dict[str, Any]:
        """
        查询常用PID默认控制字段（MV, PV, SV, PB, TI, TD）
        
        Returns:
            {
            "project_uri": self.device_uri,
            "point_path": self.point_path,
            "pid_point_map":  {
                  "MV": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
                  "PV": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0",
                  "SV": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_SV.In_Channel0",
                  "PB": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PB.In_Channel0",
                  "TI": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TI.In_Channel0",
                  "TD": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_TD.In_Channel0"
                }
            }
        """
        # 确保 project_path 和 point_path 不为 None
        project_path = self.device_uri if self.device_uri is not None else ""
        point_path = self.point_path if self.point_path is not None else ""
        body_data = {
            "project_uri": self.device_uri,
            "point_path": self.point_path,
            "pid_point_map": {}
        }
        browse_paths = []
        if model_point_names:
            browse_paths = [project_path + point_path + "/" + name for name in model_point_names]
        else:
            #pid 控制字段模型浏览路径
            browse_paths = [
                project_path + point_path + "/" + suffix
                for suffix in self.DEFAULT_PID_POINT_MAP.values()
            ]

        # 调用API获取原始结果
        raw_result = self.query_values_by_browse_path(browse_paths)
        # 提取原始响应和浏览路径

        logger.debug(f"BFF响应数据: {raw_result}")
        logger.debug(f"浏览路径: {browse_paths}")

        # 提取result字段
        result_paths = raw_result.get('result', [])
        #未查询到测点信息
        if not result_paths:
            return body_data

        # 按顺序映射浏览路径到时序测点路径
        point_path_mapping = self.map_browse_paths_to_result(
            browse_paths=browse_paths,
            result_paths=result_paths
        )
        pid_point_map = self.process_pid_point_map(point_path_mapping)
        body_data["pid_point_map"] = pid_point_map
        # 将browse_paths和raw_result一并返回，供后续处理
        return pid_point_map

    def query_custom_fields(self, pid_keys: List[str]) -> Dict[str, Any]:
        """
        查询自定义字段
        
        Args:
            field_keys: 字段键列表，如 ['mv', 'pv', 'sv']
            
        Returns:
            查询结果字典
        """
        browse_paths = []
        for key in pid_keys:
            if key in self.DEFAULT_PID_POINT_MAP:
                browse_paths.append(
                    self.device_uri + self.point_path + '/' + self.DEFAULT_PID_POINT_MAP[key]
                )
            else:
                logger.warning(f"未知字段键: {key}, 跳过")

        if not browse_paths:
            raise ValueError("没有有效的字段键")

        return self.query_values_by_browse_path(browse_paths)

    def build_browse_path(self, path_suffix: str) -> str:
        """
        构建完整浏览路径
        
        Args:
            path_suffix: 路径后缀，如 '/SBCS/ns_100_s_FIC101A_MV_In_Channel0'
            
        Returns:
            完整的浏览路径
        """
        return self.device_uri + self.point_path + "/" + path_suffix

    def query_by_custom_suffixes(self, path_suffixes: List[str]) -> Dict[str, Any]:
        """
        根据自定义路径后缀查询
        
        Args:
            path_suffixes: 路径后缀列表，如 ['/SBCS/ns_100_s_XXX_In_Channel0', ...]
            
        Returns:
            查询结果字典
        """
        browse_paths = [
            self.device_uri + self.point_path + "/" + suffix
            for suffix in path_suffixes
        ]

        return self.query_values_by_browse_path(browse_paths)

    def parse_response(self, response_data: Any) -> Dict[str, float]:
        """
        解析响应数据，提取字段值
        
        Args:
            response_data: API响应数据
            
        Returns:
            字段名到值的映射字典
            
        Example:
            # >>> response = client.query_common_fields()
            # >>> values = client.parse_response(response)
            # >>> print(values)
            {'mv': 45.2, 'pv': 23.1, 'sv': 25.0, ...}
        """
        result = {}

        if not isinstance(response_data, list):
            logger.warning("响应数据格式不是列表，尝试直接解析")
            response_data = [response_data]

        # 反向映射：从路径后缀到键
        suffix_to_key = {}
        for key, suffix in self.DEFAULT_PID_POINT_MAP.items():
            # 从后缀中提取字段标识（如FIC101A_MV）
            suffix_to_key[key] = key

        for item in response_data:
            if isinstance(item, dict):
                # 尝试提取路径和值
                path = item.get('browsePath') or item.get('path') or ''
                value = item.get('value')

                # 从路径中匹配字段键
                for key in self.DEFAULT_PID_POINT_MAP.keys():
                    if self.DEFAULT_PID_POINT_MAP[key] in path:
                        try:
                            result[key] = float(value) if value is not None else None
                        except (ValueError, TypeError):
                            result[key] = value
                        break

        return result

    @staticmethod
    def map_browse_paths_to_result(
            browse_paths: List[str],
            result_paths: List[str]
    ) -> Dict[str, str]:
        """
        将传入的浏览路径与BFF返回的测点路径按顺序一一映射
        
        Args:
            browse_paths: 传入的浏览路径列表（完整路径），如:
                ["/pid_zd/xxx/SBCS/ns_100_s_FIC101A_MV_In_Channel0", ...]
            result_paths: BFF返回的测点路径列表，如:
                ["/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0", ...]
        
        Returns:
            映射字典，key为浏览路径的最后一级，value为完整的result路径
            
        Example:
            # >>> browse = ["/pid_zd/xxx/SBCS/ns_100_s_FIC101A_MV_In_Channel0"]
            # >>> result = ["/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0"]
            # >>> mapping = BFFModelClient.map_browse_paths_to_result(browse, result)
            # >>> print(mapping)
            {
                "ns_100_s_FIC101A_MV_In_Channel0": "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0"
            }
        """
        point_path_mapping = {}

        # 按顺序一一对应
        for i, browse_path in enumerate(browse_paths):
            if i < len(result_paths):

                # value保持完整的result路径，不做拆分
                result_path = result_paths[i]

                point_path_mapping[browse_path] = result_path
            else:
                logger.warning(f"浏览路径索引 {i} 超出返回结果范围")

        return point_path_mapping

    def process_pid_point_map(self,path_point_map: Dict[str, str]) -> Dict[str, Any]:
        """
        处理PID点映射表，将字段名和路径映射为表名和测点名称
        """
        # 提取浏览路径的最后一级作为key
        # 例如: "/pid_zd/xxx/SBCS/ns_100_s_FIC101A_MV_In_Channel0" -> "ns_100_s_FIC101A_MV_In_Channel0"
        name_point_map={}
        for key, value in path_point_map.items():
            key_parts = key.split("/")
            if len(key_parts) > 0:
                name_point_map[key_parts[-1]] = value
        return name_point_map

    @staticmethod
    def extract_table_and_points_from_paths(
            query_paths: Any,
            result_paths: Any = None
    ) -> Dict[str, Any]:
        """
        从BFF返回的测点路径中提取table名称和测点名称映射
        支持两种输入格式：
        1. 列表格式：query_paths和result_paths都是列表，根据索引位置匹配
        2. 字典格式：query_paths是字典（键为字段名如MV/PV，值为路径），result_paths可选
        
        Args:
            query_paths: 查询路径，支持两种格式：
                - List[str]: 查询时使用的browse_paths列表，顺序为 [MV, PV, SV, PB, TI, TD]
                - Dict[str, str]: 字段名到路径的映射，如 {'MV': '/table/point', 'PV': '/table/point2'}
            result_paths: BFF返回的测点路径列表（仅在query_paths为列表时使用）
        
        Returns:
            包含table名称和测点映射的字典:
            {
                "table_name": "PID_FEP_Gateway_Device_001default",
                "points": {
                    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
                    "pv": "ns=100;s=FIC101A_PV.In_Channel0",
                    "sv": "ns=100;s=FIC101A_SV.In_Channel0",
                    "pb": "ns=100;s=FIC101A_PB.In_Channel0",
                    "ti": "ns=100;s=FIC101A_TI.In_Channel0",
                    "td": "ns=100;s=FIC101A_TD.In_Channel0"
                }
            }

        Example:
            # 列表格式
            # >>> query_paths = ["/project/point/MV", "/project/point/PV"]
            # >>> result_paths = [
            # ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
            # ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0"
            # ... ]
            # >>> result = BFFModelClient.extract_table_and_points_from_paths(query_paths, result_paths)
            #
            # # 字典格式
            # >>> path_dict = {
            # ...     'MV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0',
            # ...     'PV': '/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0'
            # ... }
            # >>> result = BFFModelClient.extract_table_and_points_from_paths(path_dict)
        """
        # 如果是字典格式输入
        if isinstance(query_paths, dict):
            return BFFModelClient._extract_from_dict(query_paths)

        # 如果是列表格式输入
        if isinstance(query_paths, list):
            if result_paths is None:
                logger.warning("列表格式输入需要同时提供result_paths")
                return {
                    "table_name": None,
                    "points": {}
                }
            return BFFModelClient._extract_from_lists(query_paths, result_paths)

        logger.warning(f"不支持的输入格式: {type(query_paths)}")
        return {
            "table_name": None,
            "points": {}
        }

    @staticmethod
    def query_table_and_points_by_loop_uri(
            loop_uri: str,
    ) -> tuple[str, Dict[str, str]]:
        """
        根据loop_uri查询表名和测点列表

        Args:
            loop_uri: 回路URI，如 '/pid_zd/0b521c82a96d4107a564e4c2678bdeca'
            point_path: 测点路径，默认为 'loop_state_parameters'

        Returns:
            tuple: (table_name, points_mapping)

        Raises:
            HTTPException: 查询失败时抛出异常
        """
        try:
            logger.info(f"根据loop_uri查询测点: {loop_uri}")

            with BFFModelClient(device_uri=loop_uri) as client:
                # 查询常用字段
                query_result = client.query_common_fields()

                # 提取table名称和测点列表
                table_and_points = BFFModelClient.extract_table_and_points_from_paths(query_result)

                table_name = table_and_points.get('table_name')
                points = table_and_points.get('points', {})

                if not table_name:
                    logger.warning(f"未能从回路URI解析出回路: {loop_uri}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"未能从回路URI解析出回路: {loop_uri}"
                    )

                if not points:
                    logger.warning(f"未解析出测点列表: {loop_uri}")
                    raise HTTPException(
                        status_code=400,
                        detail=f"未能从回路URI解析出测点列表: {loop_uri}"
                    )

                logger.info(f"查询成功 - table: {table_name}, points: {len(points)}个")
                return table_name, points

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"查询设备和测点列表失败: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"查询设备和测点列表失败: {str(e)}"
            )

    @staticmethod
    def _extract_from_dict(path_dict: Dict[str, str]) -> Dict[str, Any]:
        """
        从字典格式的路径映射中提取table名称和测点
        
        Args:
            path_dict: 字段名到路径的映射，键为大写字段名（MV, PV等），值为完整路径
            
        Returns:
            包含table名称和测点映射的字典
        """
        if not path_dict:
            logger.warning("输入的路径字典为空")
            return {
                "table_name": None,
                "points": {}
            }

        table_name = None
        points = {}

        # 字段名映射：大写到小写
        field_mapping = BFFModelClient.DEFAULT_PID_POINT_MAP

        for field_upper, path in path_dict.items():
            if not path:
                continue

            # 获取小写字段名
            field_key = field_mapping.get(field_upper)
            if field_key is None:
                # 如果不在映射中，尝试转换为小写
                field_key = field_upper.lower()
                logger.debug(f"字段 {field_upper} 不在标准映射中，使用小写形式: {field_key}")

            # 从路径中提取table名称和测点名称
            if '/' in path:
                parts = path.split('/')
                parts = [p for p in parts if p]  # 过滤掉空字符串

                if len(parts) >= 2:
                    # 第一部分是table名称
                    current_table = parts[0]
                    # 第二部分是测点名称
                    point_name = parts[1]

                    # 设置或验证table名称
                    if table_name is None:
                        table_name = current_table
                    elif table_name != current_table:
                        logger.warning(f"检测到不同的table名称: {table_name} vs {current_table}")

                    # 存储测点名称
                    points[field_key] = point_name

                elif len(parts) == 1:
                    # 如果只有一部分，直接作为测点名称
                    points[field_key] = parts[0]
            else:
                # 如果没有'/'，直接作为测点名称
                points[field_key] = path

        return {
            "table_name": table_name,
            "points": points
        }

    @staticmethod
    def _extract_from_lists(
            query_names: List[str],
            result_paths: List[str]
    ) -> Dict[str, Any]:
        """
        从列表格式的路径中提取table名称和测点（原有逻辑）
        
        Args:
            query_names: 查询时使用的browse_names列表
            result_paths: BFF返回的测点路径列表
            
        Returns:
            包含table名称和测点映射的字典
        """
        if result_paths is None or not result_paths:
            logger.warning("输入的路径列表为空或None")
            return {
                "table_name": None,
                "points": {}
            }

        if query_names is None or not query_names:
            logger.warning("查询路径列表为空或None")
            return {
                "table_name": None,
                "points": {}
            }

        table_name = None
        points = {}

        # 字段名模式映射（用于从query_path中识别字段类型）
        field_map = BFFModelClient.DEFAULT_PID_POINT_MAP
        field_patterns = list(field_map.values())
        field_keys = list(field_map.keys())
        # 根据索引位置匹配query_paths和result_paths
        for i in range(min(len(query_names), len(result_paths))):
            query_path = query_names[i]
            result_path = result_paths[i]

            # 跳过None值
            if result_path is None:
                result_path = ''

            if query_path is None:
                continue

            # 从query_path中识别字段类型
            field_key = None
            for j, pattern in enumerate(field_patterns):
                if pattern in query_path:
                    field_key = field_keys[j]
                    break

            if field_key is None:
                logger.warning(f"无法从查询路径识别字段类型: {query_path}")
                continue

            # 从result_path中提取table名称和测点名称
            if '/' in result_path:
                parts = result_path.split('/')
                parts = [p for p in parts if p]  # 过滤掉空字符串

                if len(parts) >= 2:
                    # 第一部分是table名称
                    current_table = parts[0]
                    # 第二部分是测点名称
                    point_name = parts[1]

                    # 设置或验证table名称
                    if table_name is None:
                        table_name = current_table
                    elif table_name != current_table:
                        logger.warning(f"检测到不同的table名称: {table_name} vs {current_table}")

                    # 根据query_path的位置确定字段键，存储测点名称
                    points[field_key] = point_name

                elif len(parts) == 1:
                    # 如果只有一部分，直接作为测点名称
                    point_name = parts[0]
                    points[field_key] = point_name
            elif result_path:  # 如果没有'/'且不为空
                # 直接作为测点名称
                points[field_key] = result_path

        return {
            "table_name": table_name,
            "points": points
        }

    def close(self):
        """关闭会话"""
        if self.session:
            self.session.close()

    def list_instances_under_tree(
            self,
            model_identifier_list: List[str],
            start_identifier_list: List[str],
            contain_sub_model: bool = True,
            page_no: int = 1,
            page_size: int = 10
    ) -> Dict[str, Any]:
        """
        查询实例树下的实例列表

        Args:
            model_identifier_list: 模型标识符列表，如 ['/pid_zd/460b81c8e216459c9fd159dbacfc9b10']
            start_identifier_list: 起始标识符列表，如 ['/pid_zd/5cf9d861d28240ce82da84fe43946fde']
            contain_sub_model: 是否包含子模型，默认True
            page_no: 页码，默认1
            page_size: 每页数量，默认10

        Returns:
            简化后的实例列表，包含uri, browseName, displayName, description, extendedAttr

        Example:
            >>> client = BFFModelClient()
            >>> result = client.list_instances_under_tree(
            ...     model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
            ...     start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde']
            ... )
            >>> print(result)
            {
                'instances': [
                    {
                        'uri': '/pid_zd/2ed6242e40be4cb1b439942d59d21114',
                        'browseName': 'YWHL2',
                        'displayName': '液位回路2',
                        'description': '创建根节点，用于组织模型结构',
                        'extendedAttr': {'HLLX': '液企2'}
                    }
                ],
                'pagination': {
                    'total': 2,
                    'pages': 1,
                    'pageNo': 1,
                    'pageSize': 10
                }
            }
        """
        url = f"{self.base_url}{self.DEFAULT_LIST_INSTANCE_PATH}"

        # 构建请求参数
        params = {
            'pageNo': page_no,
            'pageSize': page_size
        }

        # 构建请求体
        payload = {
            'containSubModel': contain_sub_model,
            'modelIdentifierList': model_identifier_list,
            'startIdentifierList': start_identifier_list
        }

        try:
            logger.info(f"查询BFF实例树，模型标识符: {model_identifier_list}, 起始标识符: {start_identifier_list}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求参数: {params}")
            logger.debug(f"请求体: {payload}")

            response = self.session.post(
                url,
                params=params,
                json=payload,
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

            # 解析响应
            if result.get('code') != 200:
                logger.error(f"BFF返回错误: {result.get('message')}")
                return {
                    'instances': [],
                    'pagination': {
                        'total': 0,
                        'pages': 0,
                        'pageNo': page_no,
                        'pageSize': page_size
                    },
                    'error': result.get('message')
                }

            # 提取结果数据
            result_data = result.get('result', {})
            data_list = result_data.get('data', [])

            # 简化数据，只保留需要的字段
            instances = []
            for item in data_list:
                simplified_item = {
                    'uri': item.get('uri'),
                    'browseName': item.get('browseName'),
                    'displayName': item.get('displayName'),
                    'description': item.get('description'),
                    'extendedAttr': item.get('extendedAttr', {}),
                    'uriPath': item.get('uriPath'),
                    'browsePath': item.get('browsePath'),
                    'displayNamePath': item.get('displayNamePath')
                }
                instances.append(simplified_item)

            logger.info(f"成功查询到 {len(instances)} 个实例")

            return {
                'instances': instances,
                'pagination': {
                    'total': result_data.get('total', 0),
                    'pages': result_data.get('pages', 0),
                    'pageNo': result_data.get('pageNo', page_no),
                    'pageSize': result_data.get('pageSize', page_size)
                }
            }

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF实例查询失败: {str(e)}")
            raise

    def __enter__(self):
        """上下文管理器入口"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

    def get_next_level_submodel(
            self,
            identifier: str
    ) -> Dict[str, Any]:
        """
        获取下一级子模型

        Args:
            identifier: 模型标识符，如 '/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243'

        Returns:
            简化后的子模型列表，包含uri, browseName, displayName, extendedAttr, parentUri

        Example:
            >>> client = BFFModelClient()
            >>> result = client.get_next_level_submodel(
            ...     identifier='/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243'
            ... )
            >>> print(result)
            {
                'submodels': [
                    {
                        'uri': '/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1',
                        'browseName': 'flow_loop_model',
                        'displayName': '流量单回路模型',
                        'extendedAttr': {'loop_type': '流量'},
                        'parentUri': '/pid_zd/d4d2d8c4906846818c91e4fe06a290a2'
                    }
                ],
                'total': 1
            }
        """
        url = f"{self.base_url}{self.DEFAULT_GET_NEXT_LEVEL_SUBMODEL_PATH}"

        # 构建请求参数
        params = {
            'identifier': identifier
        }

        try:
            logger.info(f"查询下一级子模型，标识符: {identifier}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求参数: {params}")

            response = self.session.get(
                url,
                params=params,
                timeout=self.timeout
            )

            response.raise_for_status()
            result = response.json()

            # 解析响应
            if result.get('code') != 200:
                logger.error(f"BFF返回错误: {result.get('message')}")
                return {
                    'submodels': [],
                    'error': result.get('message'),
                    'total': 0
                }

            # 提取结果数据
            result_data = result.get('result', [])
            
            # 简化数据，只提取指定字段：uri、displayName、extendedAttr、browseName、parentUri
            submodels = []
            for item in result_data:
                simplified_item = {
                    'uri': item.get('uri'),
                    'browseName': item.get('browseName'),
                    'displayName': item.get('displayName'),
                    'description': item.get('description'),
                    'uriPath': item.get('uriPath'),
                    'extendedAttr': item.get('extendedAttr', {}),
                    'parentUri': item.get('parentUri')
                }
                submodels.append(simplified_item)

            logger.info(f"成功查询到 {len(submodels)} 个子模型")

            return {
                'submodels': submodels,
                'total': len(submodels)
            }

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF子模型查询失败: {str(e)}")
            raise

    def query_nodes_by_uris(
            self,
            uris: List[str]
    ) -> Dict[str, Any]:
        """
        根据URI列表查询节点详细信息

        Args:
            uris: URI列表，如 ['/pid_zd/0b521c82a96d4107a564e4c2678bdeca']

        Returns:
            节点详细信息列表

        Example:
            >>> client = BFFModelClient()
            >>> result = client.query_nodes_by_uris(
            ...     uris=['/pid_zd/0b521c82a96d4107a564e4c2678bdeca']
            ... )
            >>> print(result)
            {
                'nodes': [
                    {
                        'uri': '/pid_zd/0b521c82a96d4107a564e4c2678bdeca',
                        'browseName': 'flow_loop_model_1',
                        'displayName': '流量单回路实例_1',
                        'description': '催化车间-流量回路1',
                        'extendedAttr': {'loop_type': '流量'},
                        'parentUri': '/pid_zd/1f59615dc9d44b4388e29829f95a49c6',
                        'typeUri': '/pid_zd/49ccb5882d9b4c8d91885a55e4cbcda1',
                        'displayNamePath': 'root,PID参数整定_勿删,...',
                        'browseNamePath': 'root,pid_zd,instance,...'
                    }
                ],
                'total': 1
            }
        """
        url = f"{self.base_url}{self.DEFAULT_QUERY_NODES_BY_URIS_PATH}"

        try:
            logger.info(f"根据URI查询节点详细信息，URI数量: {len(uris)}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"URI列表: {uris[:3]}..." if len(uris) > 3 else f"URI列表: {uris}")

            response = self.session.post(
                url,
                json=uris,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            # 检查响应状态
            if result.get('code') != '0x00000000':
                logger.error(f"BFF返回错误: {result.get('msg')}")
                return {
                    'nodes': [],
                    'error': result.get('msg'),
                    'total': 0
                }

            # 提取结果数据
            result_data = result.get('result', [])
            
            # 简化数据，只提取关键字段
            nodes = []
            for item in result_data:
                simplified_item = {
                    'uri': item.get('uri'),
                    'browseName': item.get('browseName'),
                    'displayName': item.get('displayName'),
                    'description': item.get('description'),
                    'extendedAttr': item.get('extendedAttr', {}),
                    'parentUri': item.get('parentUri'),
                    'typeUri': item.get('typeUri'),
                    'displayNamePath': item.get('displayNamePath'),
                    'browseNamePath': item.get('browseNamePath'),
                    'uriPath': item.get('uriPath')

                }
                nodes.append(simplified_item)

            logger.info(f"成功查询到 {len(nodes)} 个节点")

            return {
                'nodes': nodes,
                'error': None,
                'total': len(nodes)
            }

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF节点查询失败: {str(e)}")
            raise

    def query_current_raw_values(
            self,
            point_names: List[str],
            loop_uri: Optional[str] = None,
            point_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        查询测点当前原始值（最新值）
        """
        loop_uri = loop_uri if loop_uri is not None else self.device_uri
        point_path = point_path if point_path is not None else self.point_path
        if point_path and not point_path.startswith('/'):
            point_path = f"/{point_path}"
        browse_paths = [
            f"{loop_uri}{point_path}/{point_name}"
            for point_name in point_names
        ]
        url = f"{self.base_url}{self.DEFAULT_QUERY_CURRENT_RAW_VALUE_PATH}"

        try:
            logger.info(f"查询测点当前原始值，路径数量: {len(browse_paths)}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"浏览路径: {browse_paths[:3]}..." if len(browse_paths) > 3 else f"浏览路径: {browse_paths}")

            response = self.session.post(
                url,
                json=browse_paths,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            # 兼容非字典响应或包含None的项
            result_data: List[Any] = []
            if isinstance(result, dict):
                if result.get('code') != '0x00000000':
                    logger.error(f"BFF返回错误: {result.get('msg')}")
                    return {}
                result_data = result.get('result', []) or []
            elif isinstance(result, list):
                result_data = result
            else:
                logger.warning(f"未知响应类型: {type(result)}")
                result_data = []

            values_map = {}
            for i, point_name in enumerate(point_names):
                item = result_data[i] if i < len(result_data) else None
                value = item.get('v') if isinstance(item, dict) else None
                if i >= len(result_data):
                    logger.warning(f"测点索引 {i} 超出返回结果范围")
                values_map[point_name] = value

            logger.info(f"成功查询到 {len(values_map)} 个测点值")
            return values_map

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF测点值查询失败: {str(e)}")
            raise

    def query_multi_loop_current_values(
            self,
            loop_configs: List[Dict[str, Any]],
            point_path: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        一次查询多个回路的测点实时值
        """
        point_path = point_path if point_path is not None else self.point_path
        if point_path and not point_path.startswith('/'):
            point_path = f"/{point_path}"
        all_browse_paths = []
        path_mapping = []
        for config in loop_configs:
            loop_uri = config.get('loop_uri')
            point_names = config.get('point_names', [])
            for point_name in point_names:
                browse_path = f"{loop_uri}{point_path}/{point_name}"
                all_browse_paths.append(browse_path)
                path_mapping.append({'loop_uri': loop_uri, 'point_name': point_name})

        url = f"{self.base_url}{self.DEFAULT_QUERY_CURRENT_RAW_VALUE_PATH}"

        try:
            logger.info(f"查询多回路测点当前值，回路数: {len(loop_configs)}, 总测点数: {len(all_browse_paths)}")
            logger.debug(f"请求URL: {url}")

            response = self.session.post(
                url,
                json=all_browse_paths,
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()

            result_data: List[Any] = []
            if isinstance(result, dict):
                if result.get('code') != '0x00000000':
                    logger.error(f"BFF返回错误: {result.get('msg')}")
                    return {}
                result_data = result.get('result', []) or []
            elif isinstance(result, list):
                result_data = result
            else:
                logger.warning(f"未知响应类型: {type(result)}")
                result_data = []

            loop_values: Dict[str, Dict[str, Any]] = {}
            for i, mapping in enumerate(path_mapping):
                loop_uri = mapping['loop_uri']
                point_name = mapping['point_name']
                if loop_uri not in loop_values:
                    loop_values[loop_uri] = {}
                item = result_data[i] if i < len(result_data) else None
                value = item.get('v') if isinstance(item, dict) else None
                if i >= len(result_data):
                    logger.warning(f"测点索引 {i} 超出返回结果范围")
                loop_values[loop_uri][point_name] = value

            logger.info(f"成功查询到 {len(loop_values)} 个回路的测点值")
            return loop_values

        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"BFF多回路测点值查询失败: {str(e)}")
            raise

    @staticmethod
    def convert_bff_path_to_iot_field(bff_path: str) -> str:
        """
        将BFF模型路径转换为IoT客户端所需的字段格式

        Args:
            bff_path: BFF模型路径，如 '/SBCS/ns_100_s_FIC101A_MV_In_Channel0'

        Returns:
            IoT格式字段名，如 'ns=100;s=FIC101A_MV.In_Channel0'

        Example:
            # >>> path = '/SBCS/ns_100_s_FIC101A_MV_In_Channel0'
            # >>> field = BFFModelClient.convert_bff_path_to_iot_field(path)
            # >>> print(field)  # 'ns=100;s=FIC101A_MV.In_Channel0'
        """
        import re

        # 匹配模式: ns_{数字}_s_{字段名}_{通道名}
        match = re.search(r'ns_(\d+)_s_(.+?)_(In_Channel\d+)', bff_path)
        if match:
            ns_num = match.group(1)
            field_name = match.group(2)
            channel = match.group(3)
            # 转换格式: ns=100;s=FIC101A_MV.In_Channel0
            return f"ns={ns_num};s={field_name}.{channel}"

        # 如果无法匹配，返回原路径
        logger.warning(f"无法解析BFF路径格式: {bff_path}")
        return bff_path

    @classmethod
    def get_iot_field_mapping(cls) -> Dict[str, str]:
        """
        获取BFF路径后缀到IoT字段的映射关系

        Returns:
            映射字典，key为字段键(如'mv', 'pv')，value为IoT格式字段名

        Example:
            # >>> mapping = BFFModelClient.get_iot_field_mapping()
            # >>> print(mapping)
            {
                'mv': 'ns=100;s=FIC101A_MV.In_Channel0',
                'pv': 'ns=100;s=FIC101A_PV.In_Channel0',
                'sv': 'ns=100;s=FIC101A_SV.In_Channel0',
                'pb': 'ns=100;s=FIC101A_PB.In_Channel0',
                'ti': 'ns=100;s=FIC101A_TI.In_Channel0',
                'td': 'ns=100;s=FIC101A_TD.In_Channel0'
            }
        """
        mapping = {}
        for key, bff_path in cls.DEFAULT_PID_POINT_MAP.items():
            mapping[key] = cls.convert_bff_path_to_iot_field(bff_path)
        return mapping


# 便捷函数
def query_pid_values(
        point_path: Optional[str] = None,
        project_path: Optional[str] = None,
        timeout: int = None
) -> Dict[str, float]:
    """
    便捷函数：查询PID控制相关的所有字段值
    
    Args:
        project_path: 项目路径前缀，默认从环境变量 BFF_MODEL_PROJECT_PATH 读取
        base_url: BFF服务基础URL，默认从环境变量 BFF_MODEL_BASE_URL 读取
        timeout: 请求超时时间，默认从环境变量 BFF_MODEL_TIMEOUT 读取
        
    Returns:
        字段值字典
        
    Example:
        >>> # 使用默认配置（从环境变量）
        >>> values = query_pid_values()
        >>> print(f"MV={values['mv']}, PV={values['pv']}")
        
        >>> # 覆盖项目路径
        >>> values = query_pid_values(project_path="/pid_zd/custom_project_id")
    """
    with BFFModelClient(device_uri=project_path, point_path=point_path, timeout=timeout) as client:
        query_result = client.query_common_fields()
        raw_response = query_result.get('raw_response', {})
        return client.parse_response(raw_response)


def query_specific_fields(
        field_keys: List[str],
        project_path: Optional[str] = None,
        point_path: Optional[str] = None,
        timeout: int = None
) -> Dict[str, float]:
    """
    便捷函数：查询指定字段的值
    
    Args:
        field_keys: 字段键列表，如 ['mv', 'pv']
        project_path: 项目路径前缀，默认从环境变量读取
        base_url: BFF服务基础URL，默认从环境变量读取
        timeout: 请求超时时间，默认从环境变量读取
        
    Returns:
        字段值字典
        
    Example:
        >>> # 使用默认配置
        >>> values = query_specific_fields(['mv', 'pv', 'sv'])
        
        >>> # 覆盖项目路径
        >>> values = query_specific_fields(['mv', 'pv'], project_path="/pid_zd/custom_project_id")
    """
    with BFFModelClient(device_uri=project_path, point_path=point_path, timeout=timeout) as client:
        response = client.query_custom_fields(field_keys)
        return client.parse_response(response)


def list_instances(
        model_identifier_list: List[str],
        start_identifier_list: List[str],
        contain_sub_model: bool = True,
        page_no: int = 1,
        page_size: int = 10,
        timeout: int = None
) -> Dict[str, Any]:
    """
    便捷函数：查询实例树下的实例列表
    
    Args:
        model_identifier_list: 模型标识符列表
        start_identifier_list: 起始标识符列表
        contain_sub_model: 是否包含子模型
        page_no: 页码
        page_size: 每页数量
        timeout: 请求超时时间
        
    Returns:
        实例列表字典
        
    Example:
        >>> # 查询实例列表
        >>> result = list_instances(
        ...     model_identifier_list=['/pid_zd/460b81c8e216459c9fd159dbacfc9b10'],
        ...     start_identifier_list=['/pid_zd/5cf9d861d28240ce82da84fe43946fde']
        ... )
        >>> print(f"找到 {len(result['instances'])} 个实例")
    """
    with BFFModelClient(timeout=timeout) as client:
        return client.list_instances_under_tree(
            model_identifier_list=model_identifier_list,
            start_identifier_list=start_identifier_list,
            contain_sub_model=contain_sub_model,
            page_no=page_no,
            page_size=page_size
        )
