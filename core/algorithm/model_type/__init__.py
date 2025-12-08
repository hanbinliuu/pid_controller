"""
模型类型选择模块

流程：
1. 剔除无效/扰动段
2. 对每个有效段尝试多种模型拟合
3. 基于AIC/RSS/形状特征选择最优模型结构
4. 融合各段参数 → 唯一K, T, L
5. 验证一致性与仿真匹配度
"""

from .model_selector import ModelSelector, SegmentResult, FusionResult

__all__ = ['ModelSelector', 'SegmentResult', 'FusionResult']
