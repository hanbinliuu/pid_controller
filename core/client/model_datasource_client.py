#!/usr/bin/env python3
"""
模型数据源客户端
用于调用模型数据源相关的接口（设备绑定等）
"""

import requests
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging
from urllib.parse import urlencode

from core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class DeviceBindInfo:
    """设备绑定信息"""
    device_id: str
    product_id: str

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "deviceId": self.device_id,
            "productId": self.product_id
        }


@dataclass
class BatchBindDeviceRequest:
    """批量绑定设备请求参数"""
    uri: str
    devices: List[DeviceBindInfo]
    operator: str = "管理员"
    include_sub: bool = False

    def to_device_list(self) -> List[Dict[str, Any]]:
        """转换设备列表为字典列表"""
        return [device.to_dict() for device in self.devices]


class ModelDataSourceClient:
    """模型数据源客户端"""

    # 默认配置
    DEFAULT_BASE_URL = Config.get_config('model_datasource.base_url', Config.MODEL_DATASOURCE_BASE_URL)
    DEFAULT_TIMEOUT = Config.MODEL_CORE_TIMEOUT
    
    # 接口路径
    BIND_DEVICE_PATH = "/model/datasource/v4/model/bindDevice"

    def __init__(self, base_url: Optional[str] = None, timeout: int = None):
        """
        初始化模型数据源客户端
        
        Args:
            base_url: 服务基础URL，如果为None则从配置文件读取
            timeout: 请求超时时间（秒），如果为None则从配置文件读取
        """
        self.base_url = base_url if base_url is not None else self.DEFAULT_BASE_URL
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self.session = requests.Session()
        
        # 设置默认请求头
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'PID-Agent-ModelDataSource-Client/1.0'
        })
        
        logger.info(f"初始化模型数据源客户端，连接到: {self.base_url}")

    def batch_bind_device(
            self,
            uri: str,
            devices: List[Dict[str, str]],
            operator: str = "PID",
            include_sub: bool = False
    ) -> Dict[str, Any]:
        """
        批量绑定设备到回路
        
        Args:
            uri: 回路URI，如 "/pid_zd/b6e8a760281b4af8901003e567321b5e"
            devices: 设备列表，每个设备包含 deviceId 和 productId
                    例如: [{"deviceId": "sdf", "productId": "d612edaa23a9475dbe76921a7b46276b"}]
            operator: 操作者，默认为"管理员"
            include_sub: 是否包含子节点，默认为False
            
        Returns:
            接口响应结果:
            {
                "success": true,
                "message": "操作成功",
                "result": null,
                "code": 0
            }
            
        Raises:
            requests.exceptions.RequestException: 请求失败时抛出
            
        Example:
            >>> client = ModelDataSourceClient()
            >>> devices = [
            ...     {"deviceId": "device001", "productId": "d612edaa23a9475dbe76921a7b46276b"},
            ...     {"deviceId": "device002", "productId": "d612edaa23a9475dbe76921a7b46276b"}
            ... ]
            >>> result = client.batch_bind_device(
            ...     uri="/pid_zd/b6e8a760281b4af8901003e567321b5e",
            ...     devices=devices,
            ...     operator="管理员"
            ... )
        """
        # 构建查询参数
        query_params = {
            "operator": operator,
            "includeSub": str(include_sub).lower(),
            "uri": uri
        }
        
        # 构建完整URL
        url = f"{self.base_url}{self.BIND_DEVICE_PATH}?{urlencode(query_params)}"
        
        # 请求体为设备列表
        payload = devices
        
        try:
            logger.info(
                f"调用批量绑定设备接口，回路URI: {uri}, "
                f"设备数量: {len(devices)}, 操作者: {operator}"
            )
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求体: {payload}")
            
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('success'):
                logger.info(f"批量绑定设备成功: {len(devices)} 个设备")
            else:
                logger.warning(f"批量绑定设备响应异常: {result.get('message')}")
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"模型数据源接口调用失败: {str(e)}")
            raise

    def batch_bind_device_by_request(
            self,
            request: BatchBindDeviceRequest
    ) -> Dict[str, Any]:
        """
        使用请求对象批量绑定设备
        
        Args:
            request: 批量绑定设备请求对象
            
        Returns:
            接口响应结果
            
        Example:
            >>> devices = [
            ...     DeviceBindInfo(device_id="device001", product_id="d612edaa23a9475dbe76921a7b46276b"),
            ...     DeviceBindInfo(device_id="device002", product_id="d612edaa23a9475dbe76921a7b46276b")
            ... ]
            >>> request = BatchBindDeviceRequest(
            ...     uri="/pid_zd/b6e8a760281b4af8901003e567321b5e",
            ...     devices=devices,
            ...     operator="管理员",
            ...     include_sub=False
            ... )
            >>> client = ModelDataSourceClient()
            >>> result = client.batch_bind_device_by_request(request)
        """
        return self.batch_bind_device(
            uri=request.uri,
            devices=request.to_device_list(),
            operator=request.operator,
            include_sub=request.include_sub
        )

    def bind_single_device(
            self,
            uri: str,
            device_id: str,
            product_id: str,
            operator: str = "PID",
            include_sub: bool = False
    ) -> Dict[str, Any]:
        """
        绑定单个设备到回路（batch_bind_device的便捷方法）
        
        Args:
            uri: 回路信息节点URI
            device_id: 设备ID
            product_id: 产品ID
            operator: 操作者，默认为"管理员"
            include_sub: 是否包含子节点，默认为False
            
        Returns:
            接口响应结果
            
        Example:
            >>> client = ModelDataSourceClient()
            >>> result = client.bind_single_device(
            ...     uri="/pid_zd/b6e8a760281b4af8901003e567321b5e",
            ...     device_id="device001",
            ...     product_id="d612edaa23a9475dbe76921a7b46276b"
            ... )
        """
        devices = [{"deviceId": device_id, "productId": product_id}]
        return self.batch_bind_device(
            uri=uri,
            devices=devices,
            operator=operator,
            include_sub=include_sub
        )

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


if __name__ == '__main__':
    """
    测试模型数据源客户端接口
    
    运行方式：
    python -m core.client.model_datasource_client
    """
    import sys
    
    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("模型数据源客户端接口测试")
    print("=" * 60)
    
    # 配置信息（请根据实际情况修改）
    BASE_URL = "http://localhost:8080"  # 模型数据源服务地址
    
    # 测试数据
    test_uri = "/pid_zd/b6e8a760281b4af8901003e567321b5e"
    test_devices = [
        {"deviceId": "sdf", "productId": "d612edaa23a9475dbe76921a7b46276b"}
    ]
    
    try:
        # 测试方式1：批量绑定设备
        print("\n测试方式1：批量绑定多个设备")
        print("-" * 60)
        
        with ModelDataSourceClient(base_url=BASE_URL) as client:
            result = client.batch_bind_device(
                uri=test_uri,
                devices=test_devices,
                operator="PID",
                include_sub=False
            )
            
            print(f"\n响应结果：")
            print(f"  Success: {result.get('success')}")
            print(f"  Message: {result.get('message')}")
            print(f"  Code: {result.get('code')}")
            print(f"  Result: {result.get('result')}")
            
            if result.get('success'):
                print("\n✅ 设备绑定成功！")
            else:
                print(f"\n⚠️  设备绑定失败: {result.get('message')}")
        
        # 测试方式2：绑定单个设备
        print("\n" + "=" * 60)
        print("测试方式2：绑定单个设备（便捷方法）")
        print("-" * 60)
        
        with ModelDataSourceClient(base_url=BASE_URL) as client:
            result = client.bind_single_device(
                uri=test_uri,
                device_id="single_device_001",
                product_id="d612edaa23a9475dbe76921a7b46276b",
                operator="管理员"
            )
            
            print(f"\n响应结果：")
            print(f"  Success: {result.get('success')}")
            print(f"  Message: {result.get('message')}")
            print(f"  Code: {result.get('code')}")
            
            if result.get('success'):
                print("\n✅ 设备绑定成功！")
            else:
                print(f"\n⚠️  设备绑定失败: {result.get('message')}")
        
        # 测试方式3：使用请求对象
        print("\n" + "=" * 60)
        print("测试方式3：使用 BatchBindDeviceRequest 对象")
        print("-" * 60)
        
        devices = [
            DeviceBindInfo(device_id="device001", product_id="d612edaa23a9475dbe76921a7b46276b"),
            DeviceBindInfo(device_id="device002", product_id="d612edaa23a9475dbe76921a7b46276b")
        ]
        request = BatchBindDeviceRequest(
            uri=test_uri,
            devices=devices,
            operator="PID",
            include_sub=False
        )
        
        with ModelDataSourceClient(base_url=BASE_URL) as client:
            result = client.batch_bind_device_by_request(request)
            
            print(f"\n响应结果：")
            print(f"  Success: {result.get('success')}")
            print(f"  Message: {result.get('message')}")
            print(f"  Code: {result.get('code')}")
            
            if result.get('success'):
                print("\n✅ 批量设备绑定成功！")
            else:
                print(f"\n⚠️  批量设备绑定失败: {result.get('message')}")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
        
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接失败：无法连接到模型数据源服务")
        print(f"   请检查服务地址: {BASE_URL}")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("\n❌ 请求超时")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)