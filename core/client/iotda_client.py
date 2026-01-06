#!/usr/bin/env python3
"""
IoTDA客户端
用于调用IoT设备接入（IoTDA）相关的接口
"""

import requests
from typing import Dict, Any, Optional
from dataclasses import dataclass
import logging

from core.config import Config

logger = logging.getLogger(__name__)


@dataclass
class CreateSubDeviceRequest:
    """创建子设备的请求参数"""
    name: str
    identification: str
    resource_space_id: str
    product_id: str
    gateway_id: str
    device_id: str = ""
    description: str = ""
    secret: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "name": self.name,
            "deviceId": self.device_id,
            "identification": self.identification,
            "description": self.description,
            "resourceSpaceId": self.resource_space_id,
            "productId": self.product_id,
            "secret": self.secret,
            "gatewayId": self.gateway_id
        }


class IoTDAClient:
    """IoTDA（IoT设备接入）客户端"""

    # 默认配置
    DEFAULT_BASE_URL = Config.TSDB_CORE_BASE_URL
    DEFAULT_TIMEOUT = Config.TSDB_TIMEOUT
    
    # 接口路径
    CREATE_SUB_DEVICE_PATH = "/iot-core/v1/devices/subDevice"
    GET_DEVICE_PATH = "/iot-core/v1/devices/noauth/{device_id}"
    DELETE_DEVICE_PATH = "/iot-core/v1/devices/{device_id}"

    def __init__(self, base_url: Optional[str] = None, timeout: int = None):
        """
        初始化IoTDA客户端
        
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
            'User-Agent': 'PID-Agent-IoTDA-Client/1.0'
        })
        
        logger.info(f"初始化IoTDA客户端，连接到: {self.base_url}")

    def create_sub_device(
            self,
            name: str,
            identification: str,
            resource_space_id: str,
            product_id: str,
            gateway_id: str,
            device_id: str = "",
            description: str = "",
            secret: str = ""
    ) -> Dict[str, Any]:
        """
        创建网关子设备
        
        Args:
            name: 设备名称
            identification: 设备标识
            resource_space_id: 资源空间ID
            product_id: 产品ID
            gateway_id: 网关设备ID
            device_id: 设备ID（可选）
            description: 设备描述（可选）
            secret: 设备密钥（可选）
            
        Returns:
            接口响应结果:
            {
                "code": 0,
                "message": "成功",
                "results": null
            }
            
        Raises:
            requests.exceptions.RequestException: 请求失败时抛出
            
        Example:
             client = IoTDAClient()
             result = client.create_sub_device(
                 name="testaa",
                 identification="testaa",
                 resource_space_id="ea1e6deab5ac49aeae01177a66b4f9b4",
                 product_id="d612edaa23a9475dbe76921a7b46276b",
                 gateway_id="1b592bee3d0d4e2985d8877b9b098a04_XN_WGSSB"
             )
        """
        url = f"{self.base_url}{self.CREATE_SUB_DEVICE_PATH}"
        
        # 构建请求体
        payload = {
            "name": name,
            "deviceId": device_id,
            "identification": identification,
            "resourceSpaceId": resource_space_id,
            "productId": product_id,
            "gatewayId": gateway_id,
            "secret": secret,
            "description": description
        }

        try:
            logger.info(f"调用创建子设备接口，设备名称: {name}, 网关ID: {gateway_id}")
            logger.debug(f"请求URL: {url}")
            logger.debug(f"请求体: {payload}")
            
            response = self.session.post(
                url,
                headers={'Authorization': f'Bearer {Config.TSDB_AUTH_TOKEN}'}, #内置通用token
                json=payload,
                timeout=self.timeout
            )

            
            response.raise_for_status()
            result = response.json()
            
            if result.get('code') == 0:
                logger.info(f"子设备创建成功: {name}")
            else:
                logger.warning(f"子设备创建响应异常: {result.get('message')}")
            return result
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"IoTDA接口调用失败: {str(e)}")
            raise

    def get_device(
            self,
            device_id: str
    ) -> Dict[str, Any]:
        """
        查询设备详情
        
        Args:
            device_id: 设备ID
            
        Returns:
            接口响应结果:
            {
              "code": 0,
              "message": "成功",
              "results": {
                "id": "FIC101A",
                "productId": "d612edaa23a9475dbe76921a7b46276b",
                "name": "FIC101A",
                "identification": "FIC101A",
                "secret": "",
                "deviceId": "FIC101A",
                "description": "FIC101A",
                "resourceSpaceId": "ea1e6deab5ac49aeae01177a66b4f9b4",
                "resourceSpaceName": "PID",
                "createBy": "管理员",
                "createTime": 1767601119890,
                "isSendModel": 0,
                "createType": 0,
                "productName": "PID控制回路模型",
                "deviceType": "网关子设备",
                "protocol": null,
                "status": "INACTIVE",
                "secretStatus": "ACTIVE",
                "gatewayId": "XN_WG",
                "gatewayName": null,
                "gatewayProtocol": null,
                "longitude": "",
                "latitude": "",
                "version": null,
                "deviceStatusCheckTime": 0,
                "orgName": "测试",
                "reportDataCount": 0,
                "groupName": null
              }
            }
        Raises:
            requests.exceptions.RequestException: 请求失败时抛出
            
        Example:
            >>> client = IoTDAClient()
            >>> result = client.get_device(device_id="FIC101A11")
        """
        url = f"{self.base_url}{self.GET_DEVICE_PATH.format(device_id=device_id)}"
        
        try:
            logger.info(f"查询设备详情，设备ID: {device_id}")
            logger.debug(f"请求URL: {url}")
            
            response = self.session.get(
                url,
                headers={'Authorization': f'Bearer {Config.TSDB_AUTH_TOKEN}'},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            reponse_json = response.json()
            
            if reponse_json.get('code') == 0:
                logger.info(f"设备查询成功: {device_id}")
            else:
                logger.warning(f"设备查询响应异常: {reponse_json.get('message')}")
            return reponse_json.get('results')
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            return {}
            # raise
        except requests.exceptions.RequestException as e:
            logger.error(f"IoTDA设备查询异常: {str(e)}")
            return {}
            # raise

    def delete_device(
            self,
            device_id: str
    ) -> Dict[str, Any]:
        """
        删除设备
        
        Args:
            device_id: 设备ID
            
        Returns:
            接口响应结果:
            {
                "code": 0,
                "message": "成功",
                "results": null
            }
            
        Raises:
            requests.exceptions.RequestException: 请求失败时抛出
            
        Example:
            >>> client = IoTDAClient()
            >>> result = client.delete_device(device_id="FIC101A11")
        """
        url = f"{self.base_url}{self.DELETE_DEVICE_PATH.format(device_id=device_id)}"
        
        try:
            logger.info(f"删除设备，设备ID: {device_id}")
            logger.debug(f"请求URL: {url}")
            
            response = self.session.delete(
                url,
                headers={'Authorization': f'Bearer {Config.TSDB_AUTH_TOKEN}'},
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            if result.get('code') == 0:
                logger.info(f"设备删除成功: {device_id}")
            else:
                logger.warning(f"设备删除响应异常: {result.get('message')}")
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"请求超时（{self.timeout}秒）")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"IoTDA设备删除失败: {str(e)}")
            raise

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
    测试IoTDA客户端接口
    
    运行方式：
    python -m core.client.iotda_client
    """
    import sys
    
    # 设置日志级别
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("=" * 60)
    print("IoTDA客户端接口测试")
    print("=" * 60)
    
    # 配置信息（请根据实际情况修改）
    BASE_URL = "http://core-iotda-infra-system.sit-cloud.ieccloud.hollicube.com"  # IoTDA服务地址
    device_id = "test_aa"
    # 测试数据
    test_device = {
        "name": device_id,
        "identification": device_id,
        'device_id': device_id,
        "resource_space_id": "ea1e6deab5ac49aeae01177a66b4f9b4",
        "product_id": "d612edaa23a9475dbe76921a7b46276b",
        "gateway_id": "1b592bee3d0d4e2985d8877b9b098a04_XN_WGSSB",
        "description": "测试子设备"
    }
    
    try:
        # 测试方式1：直接调用方法
        print("\n测试方式1：直接调用 create_sub_device() 方法")
        print("-" * 60)
        
        with IoTDAClient(base_url=BASE_URL) as client:
            result = client.create_sub_device(
                name=test_device["name"],
                identification=test_device["identification"],
                device_id=test_device["device_id"],
                resource_space_id=test_device["resource_space_id"],
                product_id=test_device["product_id"],
                gateway_id=test_device["gateway_id"],
                description=test_device["description"]
            )
            
            print(f"\n响应结果：")
            print(f"  Code: {result.get('code')}")
            print(f"  Message: {result.get('message')}")
            print(f"  Results: {result.get('results')}")
            
            if result.get('code') == 0:
                print("\n✅ 子设备创建成功！")
            else:
                print(f"\n⚠️  子设备创建失败: {result.get('message')}")

        
    except requests.exceptions.ConnectionError:
        print("\n❌ 连接失败：无法连接到IoTDA服务")
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
    