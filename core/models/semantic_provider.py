import json
import os
from typing import Dict, Any, Optional

from .ontology_model import OntologyModel
from .mechanism_model import MechanismModel
from .knowledge_model import KnowledgeModel
from .characterization_model import CharacterizationModel
from .data_model import DataModel
from .metrics_model import MetricsModel

class SemanticProvider:
    """
    语义模型供应网关 (Semantic Provider)
    ----------------------------------
    取代原有的 ModelProvider，严格按照 OS 数据抽象层组装业务实体。
    它负责将五大基础引擎（本体、表征、机理、指标、数据）和顶层引擎（知识图谱）缝合。
    """
    def __init__(self):
        # 预留给未来 OS API 客户端的插槽
        self._os_database_client = None
        
        # 本地模拟使用（仅架构前期联调用，后期抹除）
        # 这里为了快速验证，我们直接给死假数据或从老的 json 中勉强映射。
        # 实际开发中，这里直接调底座 API。
        pass
        

    def _get_ontology(self, device_id: str) -> OntologyModel:
        # TODO: 从 OS 台账库 GET 获取
        if "50108" in device_id:
            return OntologyModel(device_id=device_id, loop_type="level", tank_volume_m3=80.0, valve_cv_max=150.0)
        return OntologyModel(device_id=device_id, loop_type="level", tank_volume_m3=50.0, valve_cv_max=100.0)

    def _get_mechanism(self, loop_type: str) -> MechanismModel:
        # TODO: 从 OS 机理库 GET 获取
        if loop_type == "level":
            return MechanismModel(process_nature="integrating", preferred_simulation_model="FO_INTEGRATOR")
        return MechanismModel(process_nature="self_regulating", preferred_simulation_model="FOPDT")

    def _get_knowledge(self, loop_type: str) -> KnowledgeModel:
        # TODO: 从 OS 知识图谱 获取
        if loop_type == "level":
            return KnowledgeModel(td_enable=False, max_overshoot_percent=40.0, pb_range=[10.0, 1000.0])
        return KnowledgeModel(td_enable=True, max_overshoot_percent=10.0)

    def _get_characterization(self, device_id: str) -> CharacterizationModel:
        # TODO: 从 OS 时序特征库 获取
        import datetime
        return CharacterizationModel(
            device_id=device_id, 
            timestamp=datetime.datetime.now().isoformat()
        )

    def _get_data(self, device_id: str) -> DataModel:
        # TODO: 从 OS 点位映射库 获取
        return DataModel(device_id=device_id, pv_tag=f"{device_id}.PV", sv_tag=f"{device_id}.SV")

    def _get_metrics(self, device_id: str) -> MetricsModel:
        # TODO: 从 OS 指标库 获取
        return MetricsModel(device_id=device_id, auto_control_rate=0.98, steady_state_rate=0.85)


    def get_tuning_context(self, device_id: str) -> Dict[str, Any]:
        """
        组合出供大模型和传统算法消费的全息 Context 集装箱。
        """
        # 1. 抓取本尊设备的本体，进而得知类型
        ontology = self._get_ontology(device_id)
        loop_type = ontology.loop_type

        # 2. 从五大仓库平行并发抓取领域数据
        mechanism = self._get_mechanism(loop_type)
        data_model = self._get_data(device_id)
        metrics = self._get_metrics(device_id)
        characterization = self._get_characterization(device_id)

        # 3. 从顶层专家系统获取图谱偏好
        knowledge = self._get_knowledge(loop_type)
        
        # 4. 组装集装箱
        ctx = {
            'loop_name': device_id,
            'loop_type': loop_type,
            
            # 直接铺平注入 6 大原生 Atomic 模型对象
            'ontology_model': ontology,
            'mechanism_model': mechanism,
            'knowledge_model': knowledge,
            'characterization_model': characterization,
            'data_model': data_model,
            'metrics_model': metrics,
            
            # 【重要】为了照顾传统老代码（不改动原来 stage 里面的 json 读取点位）
            # 我们做一层向下兼容映射
            'constraints': {
                'pb_range': knowledge.pb_range,
                'gain_range': knowledge.gain_range,
                'max_overshoot_percent': knowledge.max_overshoot_percent,
                'td_enable': knowledge.td_enable,
                'control_strategy': knowledge.tuning_strategy
            },
            'physical': {
                'tank_volume_m3': ontology.tank_volume_m3,
                'valve_cv_max': ontology.valve_cv_max
            }
        }
        
        return ctx
