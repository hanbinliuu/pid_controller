import logging

from core.client import BFFModelClient, ModelCoreClient
from core.config import Config


class ModelUtil:
    """模型工具类"""
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.bff_client = BFFModelClient()
        self.model_client = ModelCoreClient()

    @staticmethod
    def get_loop_types() -> dict:
        """
        获取回路类型列表（以 Map 形式返回）
        
        从BFF获取单回路模型的下一级子模型，即所有回路类型（流量、温度、压力等）
        
        注意：这里返回的是回路模型/类型（模板），不是具体的回路实例
        
        Returns:
            dict: 回路类型映射表，key 为 loop_type，value 为 uri
            {
                '流量': '/pid_zd/xxx1',
                '温度': '/pid_zd/xxx2',
                '压力': '/pid_zd/xxx3',
                ...
            }
            
        Example:
            >>> result = ModelUtil.get_loop_types()
            >>> for loop_type, uri in result.items():
            ...     print(f"类型: {loop_type}, URI: {uri}")
        """
        ModelUtil.logger.info("获取回路类型列表")
        
        try:
            # 使用 BFF 客户端获取回路模型的下一级子模型
            with BFFModelClient() as client:
                # 获取单回路模型URI（父节点）
                loop_model_uri = Config.BFF_MODEL_LOOP_MODEL_URI
                # ModelUtil.logger.info(f"回路模型URI: {loop_model_uri}")
                
                # 获取下一级子模型（各种回路类型）
                bff_result = client.get_next_level_submodel(identifier=loop_model_uri)
                
                # 提取 submodels 列表
                submodels = bff_result.get('submodels', [])
                
                # 构建 Map: loop_type -> uri
                result = {}
                for model in submodels:
                    uri = model.get('uri')
                    extended_attr = model.get('extendedAttr', {})
                    loop_type = extended_attr.get('loop_type')
                    if loop_type and uri:  # 确保 loop_type 和 uri 都不为空
                        result[loop_type] = uri
                
                ModelUtil.logger.info(f"成功获取 {len(result)} 个回路类型")
                return result
                
        except Exception as e:
            ModelUtil.logger.error(f"获取回路类型列表失败: {str(e)}")
            raise