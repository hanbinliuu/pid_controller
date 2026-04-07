"""
模型服务提供者 (Model Provider)
===============================

统一的模型获取接口。向下对接具体的数据源（当前是本地JSON，未来是OS API），
向上给 TuningOrchestrator 以及 大模型整定路径 提供语义化的字典和对象。

用法::
    provider = ModelProvider()
    context_dict = provider.get_tuning_context('2216_LIC_50104')
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

from .standard_model import StandardProcessModel
from .instance_model import InstanceProcessModel
from .characterization_model import CharacterizationModel


class ModelProvider:
    def __init__(self, data_dir: Optional[str] = None):
        """初始化"""
        if data_dir is None:
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)
            
        self.standard_models_dir = self.data_dir / "standard_models"
        self.instance_models_dir = self.data_dir / "instance_models"
        
        # 缓存
        self._standard_models: Dict[str, StandardProcessModel] = {}
        self._instance_models: Dict[str, InstanceProcessModel] = {}
        
    def get_standard_model(self, loop_type: str) -> StandardProcessModel:
        """获取标准模型 (如 'level')"""
        if loop_type in self._standard_models:
            return self._standard_models[loop_type]
            
        json_path = self.standard_models_dir / f"{loop_type}.json"
        if not json_path.exists():
            raise ValueError(f"找不到标准模型配置文件: {json_path}")
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        model = StandardProcessModel.from_dict(data)
        self._standard_models[loop_type] = model
        return model

    def get_instance_model(self, device_id: str) -> InstanceProcessModel:
        """获取实例模型 (如 '2216_LIC_50104')"""
        if device_id in self._instance_models:
            return self._instance_models[device_id]
            
        json_path = self.instance_models_dir / f"{device_id}.json"
        if not json_path.exists():
            # 允许临时降级：返回一个仅带 device_id 和 standard_model_ref 取巧默认值的空实例
            # 方便临时测试其他尚未建工单的回路
            print(f"⚠️ [ModelProvider] 找不到实例模型 {json_path.name}，生成默认空壳")
            return InstanceProcessModel(
                device_id=device_id,
                tag_name=device_id.split('_')[-1] if '_' in device_id else device_id,
                standard_model_ref='pressure'  # 默认降级为压力回路
            )
            
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        model = InstanceProcessModel.from_dict(data)
        self._instance_models[device_id] = model
        return model

    def get_characterization_model(self, device_id: str) -> CharacterizationModel:
        """获取设备当前的动态表征模型 (未来由 OS 实时查库返回)"""
        import datetime
        # 当前架构初期，由于没有OS中台下发数据，默认给出一个健康的数据快照
        print(f"ℹ️ [ModelProvider] 模拟获取 {device_id} 最新表征模型切片")
        return CharacterizationModel(
            device_id=device_id,
            timestamp=datetime.datetime.now().isoformat()
        )

    def get_tuning_context(self, device_id: str) -> Dict[str, Any]:
        """
        组合出供流水线直接消费的 context 上下文字典。
        - 优先从实例模型提取专属配置 (如具体的 pb 范围、最大超调要求)
        - 实例缺失的部分从关联的标准模型继承
        """
        instance = self.get_instance_model(device_id)
        
        # 允许降级/找不到标准模型时，容错处理
        try:
            standard = self.get_standard_model(instance.standard_model_ref)
        except ValueError:
            print(f"⚠️ [ModelProvider] 实例指向的标准模型 '{instance.standard_model_ref}' 不存在，降级为默认 'pressure'")
            standard = self.get_standard_model('pressure')
            
        # [NEW] 表征模型接入，动态获取最新工况
        characterization = self.get_characterization_model(device_id)
            
        # 这里把需要被 orchestrator, rating, segmentation 等层级消费的具体参数铺平
        # 为了与当前旧代码最大程度兼容，优先映射到 process_context
        
        ctx = {
            # === 原有字段兼容 ===
            'loop_name': instance.device_id,
            'loop_type': standard.loop_type,          # 明确的类型（不再需要推断）
            
            # === 模型对象本身 ===
            'standard_model': standard,
            'instance_model': instance,
            'characterization_model': characterization,
            
            # === 组合铺平配置 (供流水线各 stage 方便拿取) ===
            'constraints': {
                # DCS运行范围优先 (如果配置了)
                'pb_min': instance.dcs_config.pb_min_limit,
                'pb_max': instance.dcs_config.pb_max_limit,
                'max_overshoot': instance.operating_constraints.max_overshoot_percent or standard.quality_thresholds.max_overshoot,
                'lambda_default': standard.tuning_strategy.lambda_default,
                'gain_range': (standard.gain_range.K_min, standard.gain_range.K_max),
                'integrating_gain_range': (standard.gain_range.K_int_min, standard.gain_range.K_int_max)
            },
            
            # OS API提供的物理参数
            'physical': __import__('dataclasses').asdict(instance.physical_params),
        }
        
        return ctx
