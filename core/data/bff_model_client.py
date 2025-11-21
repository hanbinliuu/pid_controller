#!/usr/bin/env python3
"""
BFF模型查询客户端
用于调用BFF聚合查询接口获取模型实时值
"""

import requests
from typing import List, Dict, Any, Optional
import logging

from core.config import Config

logger = logging.getLogger(__name__)


class BFFModelClient:
    """BFF模型查询客户端"""
    
    # 默认配置（从环境变量读取）
    DEFAULT_BASE_URL = Config.BFF_MODEL_BASE_URL
    DEFAULT_QUERY_PATH_VALUE_PATH = "/bff/aggquery/v2/model/queryValueByBrowsePath"
    DEFAULT_TIMEOUT = Config.BFF_MODEL_TIMEOUT
    DEFAULT_PROJECT_PATH = Config.BFF_MODEL_PROJECT_PATH
    DEFAULT_POINT_PATH= Config.BFF_MODEL_POINT_PATH
    
    # 固定的路径后缀模板（写死）//todo 测点路径
    PATH_SUFFIXES = {
        'mv': 'mv',
        'pv': 'pv',
        'sv': 'sv',
        'pb': 'pb',
        'ti': 'ti',
        'td': 'td'
    }
    
    def __init__(self, project_path: Optional[str] = None, point_path: Optional[str] = None, timeout: int = None):
        """
        初始化BFF模型查询客户端
        
        Args:
            project_path: 项目路径前缀（如：/pid_zd/ce716ffbade5426e8faf18467d1d5a83），默认从环境变量 BFF_MODEL_PROJECT_PATH 读取
            base_url: BFF服务基础URL，默认从环境变量 BFF_MODEL_BASE_URL 读取
            timeout: 请求超时时间（秒），默认从环境变量 BFF_MODEL_TIMEOUT 读取
        """
        self.project_path = project_path if project_path is not None else self.DEFAULT_PROJECT_PATH
        self.base_url = self.DEFAULT_BASE_URL
        self.point_path = point_path if point_path is not None else self.DEFAULT_POINT_PATH
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.session = requests.Session()
        self.session.headers.update({
            'accept': '*/*',
            'Content-Type': 'application/json'
        })
    
    def query_values_by_browse_path(
        self, 
        browse_paths: List[str]
    ) -> Dict[str, Any]:
        """
        根据浏览路径查询模型值
        
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
            #调用bff接口查询模型测点值
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
    
    def query_common_fields(self) -> Dict[str, Any]:
        """
        查询常用PID控制字段（MV, PV, SV, PB, TI, TD）
        
        Returns:
            查询结果字典，包含原始响应和路径映射
        """
        # 确保 project_path 和 point_path 不为 None
        project_path = self.project_path if self.project_path is not None else ""
        point_path = self.point_path if self.point_path is not None else ""
        
        browse_paths = [
            project_path + point_path + "/" + suffix
            for suffix in self.PATH_SUFFIXES.values()
        ]
        
        # 调用API获取原始结果
        raw_result = self.query_values_by_browse_path(browse_paths)
        
        # 将browse_paths和raw_result一并返回，供后续处理
        return {
            'raw_response': raw_result,
            'browse_paths': browse_paths
        }
    
    def query_custom_fields(self, field_keys: List[str]) -> Dict[str, Any]:
        """
        查询自定义字段
        
        Args:
            field_keys: 字段键列表，如 ['mv', 'pv', 'sv']
            
        Returns:
            查询结果字典
        """
        browse_paths = []
        for key in field_keys:
            if key in self.PATH_SUFFIXES:
                browse_paths.append(
                    self.project_path +self.point_path+'/'+ self.PATH_SUFFIXES[key]
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
        return self.project_path +self.point_path+"/"+ path_suffix
    
    def query_by_custom_suffixes(self, path_suffixes: List[str]) -> Dict[str, Any]:
        """
        根据自定义路径后缀查询
        
        Args:
            path_suffixes: 路径后缀列表，如 ['/SBCS/ns_100_s_XXX_In_Channel0', ...]
            
        Returns:
            查询结果字典
        """
        browse_paths = [
            self.project_path +self.point_path+"/"+ suffix
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
            >>> response = client.query_common_fields()
            >>> values = client.parse_response(response)
            >>> print(values)
            {'mv': 45.2, 'pv': 23.1, 'sv': 25.0, ...}
        """
        result = {}
        
        if not isinstance(response_data, list):
            logger.warning("响应数据格式不是列表，尝试直接解析")
            response_data = [response_data]
        
        # 反向映射：从路径后缀到键
        suffix_to_key = {}
        for key, suffix in self.PATH_SUFFIXES.items():
            # 从后缀中提取字段标识（如FIC101A_MV）
            suffix_to_key[key] = key
        
        for item in response_data:
            if isinstance(item, dict):
                # 尝试提取路径和值
                path = item.get('browsePath') or item.get('path') or ''
                value = item.get('value')
                
                # 从路径中匹配字段键
                for key in self.PATH_SUFFIXES.keys():
                    if self.PATH_SUFFIXES[key] in path:
                        try:
                            result[key] = float(value) if value is not None else None
                        except (ValueError, TypeError):
                            result[key] = value
                        break
        
        return result
    
    @staticmethod
    def parse_path_list_to_field_mapping(path_list: List[str]) -> Dict[str, str]:
        """
        解析BFF返回的路径列表，生成字段键到IoT格式字段名的映射
        
        Args:
            path_list: BFF返回的路径列表，如:
                ["/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0", ...]
            
        Returns:
            映射字典，key为字段键(如'mv', 'pv')，value为IoT格式字段名
            
        Example:
            >>> paths = [
            ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
            ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0"
            ... ]
            >>> mapping = BFFModelClient.parse_path_list_to_field_mapping(paths)
            >>> print(mapping)
            {'mv': 'ns=100;s=FIC101A_MV.In_Channel0', 'pv': 'ns=100;s=FIC101A_PV.In_Channel0'}
        """
        mapping = {}
        
        # 字段名到键的映射规则
        field_name_patterns = {
            'mv': 'MV',
            'pv': 'PV',
            'sv': 'SV',
            'pb': 'PB',
            'ti': 'TI',
            'td': 'TD'
        }
        
        for path in path_list:
            # 提取路径最后一部分（IoT格式字段名）
            # 例如: "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0"
            # 提取出: "ns=100;s=FIC101A_MV.In_Channel0"
            if '/' in path:
                iot_field = path.split('/')[-1]
            else:
                iot_field = path
            
            # 根据字段名中的标识（MV, PV, SV等）确定键
            for key, pattern in field_name_patterns.items():
                if f'_{pattern}.' in iot_field or f'_{pattern}_' in iot_field:
                    mapping[key] = iot_field
                    break
        
        return mapping
    
    @staticmethod
    def parse_bff_response_to_mapping(response_data: Dict[str, Any]) -> Dict[str, str]:
        """
        解析BFF完整响应，生成字段映射
        
        Args:
            response_data: BFF API完整响应，如:
                {
                    "code": "0x00000000",
                    "msg": "operation succeed",
                    "result": ["/device/ns=100;s=FIC101A_MV.In_Channel0", ...]
                }
            
        Returns:
            映射字典，key为字段键(如'mv', 'pv')，value为IoT格式字段名
            
        Example:
            # >>> response = {
            # ...     "code": "0x00000000",
            # ...     "result": ["/device/ns=100;s=FIC101A_MV.In_Channel0"]
            # ... }
            # >>> mapping = BFFModelClient.parse_bff_response_to_mapping(response)
            # >>> print(mapping['mv'])
            'ns=100;s=FIC101A_MV.In_Channel0'
        """
        if not isinstance(response_data, dict):
            logger.error("响应数据格式错误，应为字典类型")
            return {}
        
        # 提取result字段中的路径列表
        path_list = response_data.get('result', [])
        if not path_list:
            logger.warning("响应中未找到result字段或为空")
            return {}
        
        return BFFModelClient.parse_path_list_to_field_mapping(path_list)
    
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
        mapping = {}
        
        # 按顺序一一对应
        for i, browse_path in enumerate(browse_paths):
            if i < len(result_paths):
                # 提取浏览路径的最后一级作为key
                # 例如: "/pid_zd/xxx/SBCS/ns_100_s_FIC101A_MV_In_Channel0" -> "ns_100_s_FIC101A_MV_In_Channel0"
                if '/' in browse_path:
                    browse_key = browse_path.split('/')[-1]
                else:
                    browse_key = browse_path
                
                # value保持完整的result路径，不做拆分
                result_path = result_paths[i]
                
                mapping[browse_key] = result_path
            else:
                logger.warning(f"浏览路径索引 {i} 超出返回结果范围")
        
        return mapping
    
    @staticmethod
    def extract_table_and_points_from_paths(
        result_paths: List[str]
    ) -> Dict[str, Any]:
        """
        从BFF返回的测点路径中提取table名称和测点名称映射
        
        Args:
            result_paths: BFF返回的测点路径列表，如:
                ["/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0", ...]
        
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
            >>> paths = [
            ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0",
            ...     "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_PV.In_Channel0"
            ... ]
            >>> result = BFFModelClient.extract_table_and_points_from_paths(paths)
            >>> print(result)
            {
                "table_name": "PID_FEP_Gateway_Device_001default",
                "points": {
                    "mv": "ns=100;s=FIC101A_MV.In_Channel0",
                    "pv": "ns=100;s=FIC101A_PV.In_Channel0"
                }
            }
        """
        if result_paths is None or not result_paths:
            logger.warning("输入的路径列表为空或None")
            return {
                "table_name": None,
                "points": {}
            }
        
        table_name = None
        points = {}
        
        # 字段名到键的映射规则
        field_name_patterns = {
            'mv': 'MV',
            'pv': 'PV',
            'sv': 'SV',
            'pb': 'PB',
            'ti': 'TI',
            'td': 'TD'
        }
        
        for path in result_paths:
            # 跳过None值
            if path is None:
                path=''
            
            # 路径格式: "/table_name/point_name"
            # 例如: "/PID_FEP_Gateway_Device_001default/ns=100;s=FIC101A_MV.In_Channel0"
            if '/' in path:
                parts = path.split('/')
                # 过滤掉空字符串
                parts = [p for p in parts if p]
                
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
                    
                    # 根据字段名中的标识（MV, PV, SV等）确定键
                    for key, pattern in field_name_patterns.items():
                        if f'_{pattern}.' in point_name or f'_{pattern}_' in point_name:
                            points[key] = point_name
                            break
                elif len(parts) == 1:
                    # 如果只有一部分，尝试匹配字段模式
                    point_name = parts[0]
                    for key, pattern in field_name_patterns.items():
                        if f'_{pattern}.' in point_name or f'_{pattern}_' in point_name:
                            points[key] = point_name
                            break
            else:
                # 如果没有'/'，尝试匹配字段模式
                for key, pattern in field_name_patterns.items():
                    if f'_{pattern}.' in path or f'_{pattern}_' in path:
                        points[key] = path
                        break
        
        return {
            "table_name": table_name,
            "points": points
        }
    
    def close(self):
        """关闭会话"""
        if self.session:
            self.session.close()
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()

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
        for key, bff_path in cls.PATH_SUFFIXES.items():
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
    with BFFModelClient(project_path=project_path, point_path=point_path, timeout=timeout) as client:
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
    with BFFModelClient(project_path=project_path, point_path=point_path, timeout=timeout) as client:
        response = client.query_custom_fields(field_keys)
        return client.parse_response(response)

