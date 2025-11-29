#!/usr/bin/env python3
"""
按模型类型查询实例的测试脚本
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.client.bff_model_client import BFFModelClient, search_instances_by_models
from api.services.bff_service import BFFService

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_search_by_models():
    """测试按模型查询实例"""
    logger.info("=== 测试按模型类型查询实例 ===\n")
    
    # 测试参数
    model_uri_list = ["/system/401", "/pid_zd/31512b195f3f4cca9a08a9aeeb3bb243"]
    start_uri = "/pid_zd/053f3c45413b48bbafacec609d142e57"
    
    try:
        # 方式1: 直接使用客户端
        logger.info("方式1: 使用BFFModelClient")
        with BFFModelClient() as client:
            result = client.search_instances_by_models(
                model_uri_list=model_uri_list,
                start_uri=start_uri,
                include_sub_type=True
            )
            logger.info(f"✓ 查询成功\n")
        
        # 方式2: 使用便捷函数
        logger.info("方式2: 使用便捷函数")
        result = search_instances_by_models(
            model_uri_list=model_uri_list,
            start_uri=start_uri
        )
        logger.info(f"✓ 查询成功\n")
        
        # 方式3: 使用服务层
        logger.info("方式3: 使用BFFService")
        result = BFFService.search_instances_by_models(
            model_uri_list=model_uri_list,
            start_uri=start_uri,
            include_sub_type=True
        )
        logger.info(f"✓ 查询成功\n")
        
        logger.info("所有测试通过！")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试失败: {str(e)}")
        return False


if __name__ == '__main__':
    success = test_search_by_models()
    sys.exit(0 if success else 1)
