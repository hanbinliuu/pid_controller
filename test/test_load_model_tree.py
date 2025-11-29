#!/usr/bin/env python3
"""
测试模型树加载任务
"""
import sys
import os
import logging

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from api.tasks.load_loop_info import load_loop_list_and_sync

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_load_model_tree():
    """测试加载模型树并同步到数据库"""
    logger.info("=" * 70)
    logger.info("测试：加载模型树并同步到数据库")
    logger.info("=" * 70)
    
    try:
        # 执行任务
        result = load_loop_list_and_sync()
        
        # 输出结果
        logger.info("\n任务执行结果:")
        logger.info(f"  开始时间: {result.get('start_time')}")
        logger.info(f"  结束时间: {result.get('end_time')}")
        logger.info(f"  总实例数: {result.get('total_instances')}")
        logger.info(f"  新增回路: {result.get('new_loops')}")
        logger.info(f"  更新回路: {result.get('updated_loops')}")
        logger.info(f"  失败回路: {result.get('failed_loops')}")
        
        if result.get('errors'):
            logger.warning(f"\n错误列表:")
            for error in result.get('errors'):
                logger.warning(f"  - {error}")
        
        logger.info("\n✓ 测试完成")
        return True
        
    except Exception as e:
        logger.error(f"✗ 测试失败: {str(e)}", exc_info=True)
        return False


if __name__ == '__main__':
    success = test_load_model_tree()
    sys.exit(0 if success else 1)
