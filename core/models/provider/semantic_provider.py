import json
import os
from typing import Dict, Any, Optional

from ..schemas.ontology_model import OntologyModel
from ..schemas.mechanism_model import MechanismModel
from ..schemas.knowledge_model import KnowledgeModel
from ..schemas.characterization_model import CharacterizationModel
from ..schemas.data_model import DataModel
from ..schemas.metrics_model import MetricsModel


# JSON 数据目录
_DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
_INSTANCE_DIR = os.path.join(_DATA_DIR, 'instance_models')
_STANDARD_DIR = os.path.join(_DATA_DIR, 'standard_models')


class SemanticProvider:
    """
    语义模型供应网关 (Semantic Provider)
    ----------------------------------
    严格按照 OS 数据抽象层组装业务实体。
    
    当前阶段（OS 中台尚未就绪）：从本地 JSON 文件读取真实数据。
    未来阶段（OS 中台上线后）：将 _load_instance_json / _load_standard_json
                              替换为 requests.get(...) 即可，上层零改动。
    """

    def __init__(self):
        self._instance_cache: Dict[str, dict] = {}
        self._standard_cache: Dict[str, dict] = {}

    # ================================================================
    # 底层 JSON 加载（未来替换为 OS API 调用）
    # ================================================================

    def _load_instance_json(self, device_id: str) -> dict:
        """加载设备实例 JSON（未来替换为: OS台账API.get(device_id)）"""
        if device_id in self._instance_cache:
            return self._instance_cache[device_id]

        # 尝试多种命名格式匹配
        candidates = [
            f"{device_id}.json",
            f"2216_LIC_{device_id}.json",
        ]
        for name in candidates:
            path = os.path.join(_INSTANCE_DIR, name)
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._instance_cache[device_id] = data
                return data

        print(f"⚠️ [SemanticProvider] 未找到设备 {device_id} 的实例模型 JSON，使用空壳默认值")
        return {}

    def _load_standard_json(self, loop_type: str) -> dict:
        """加载标准模型 JSON（未来替换为: OS知识图谱API.get(loop_type)）"""
        if loop_type in self._standard_cache:
            return self._standard_cache[loop_type]

        path = os.path.join(_STANDARD_DIR, f"{loop_type}.json")
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._standard_cache[loop_type] = data
            return data

        print(f"⚠️ [SemanticProvider] 未找到类型 {loop_type} 的标准模型 JSON，使用空壳默认值")
        return {}

    # ================================================================
    # 从 JSON 拆解映射到 6 大原子模型
    # ================================================================

    def _get_ontology(self, device_id: str) -> OntologyModel:
        """本体模型：从实例 JSON 中提取硬件/物理实体信息"""
        inst = self._load_instance_json(device_id)
        if not inst:
            return OntologyModel(device_id=device_id)

        phys = inst.get('physical_params', {})
        valve = inst.get('valve_params', {})
        return OntologyModel(
            device_id=inst.get('device_id', device_id),
            device_type='tank',
            loop_type=inst.get('standard_model_ref', 'default'),
            tank_volume_m3=phys.get('tank_volume_m3'),
            tank_cross_section_m2=phys.get('tank_cross_section_m2'),
            valve_cv_max=valve.get('cv_max'),
            valve_type=valve.get('characteristic', 'unknown'),
            extra_attributes={
                'plant': inst.get('plant', ''),
                'unit': inst.get('unit', ''),
                'tag_name': inst.get('tag_name', ''),
                'pv_range': [phys.get('pv_range_min', 0), phys.get('pv_range_max', 100)],
                'valve_action': valve.get('action_type', ''),
                'valve_deadband': valve.get('deadband_percent', 0),
                'valve_time_constant_s': valve.get('time_constant_s', 0),
            }
        )

    def _get_mechanism(self, loop_type: str) -> MechanismModel:
        """
        机理模型：根据回路类型使用标准工厂方法获取完整机理定义。

        工厂方法已内置四大回路的物理规则、仿真模型偏好、守恒约束等完整定义。
        如实例 JSON 有覆盖配置（如密闭容器压力改为积分过程），可在此处叠加修正。
        """
        try:
            mechanism = MechanismModel.for_loop_type(loop_type)
        except ValueError:
            # 未知回路类型，返回通用默认值
            mechanism = MechanismModel()

        # 从标准 JSON 读取覆盖项（如有特殊配置）
        std = self._load_standard_json(loop_type)
        if std:
            model_struct = std.get('model_structure', {})
            preferred = model_struct.get('preferred')
            if preferred:
                mechanism.preferred_simulation_model = preferred
            process_nature = std.get('process_nature')
            if process_nature:
                mechanism.process_nature = process_nature

        return mechanism

    def _get_knowledge(self, loop_type: str, inst: dict = None) -> KnowledgeModel:
        """
        知识图谱：从标准 JSON 的三大块完整灌入 KnowledgeModel
        
        数据来源映射：
          - pid_constraints    → td_enable, pb_range, ti_max, td_ratio, td_max, aggressive
          - tuning_strategy    → tau_c_factor, safety_factor, ti_multiplier, integrating_mode
          - quality_thresholds → max_overshoot, settling_time_factor, overshoot_discount, oscillation_tolerance
          - 实例 JSON          → pb_min/max 覆盖（DCS 现场限制优先）
        """
        std = self._load_standard_json(loop_type)
        pid_c = std.get('pid_constraints', {})
        strategy = std.get('tuning_strategy', {})
        quality = std.get('quality_thresholds', {})

        # 实例级别的 DCS 限制可以覆盖标准值
        dcs = (inst or {}).get('dcs_config', {})
        op_constraints = (inst or {}).get('operating_constraints', {})

        pb_min = dcs.get('pb_min_limit', pid_c.get('pb_min', 10.0))
        pb_max = dcs.get('pb_max_limit', pid_c.get('pb_max', 500.0))
        max_overshoot = op_constraints.get('max_overshoot_percent',
                                           quality.get('max_overshoot', 10.0))

        return KnowledgeModel(
            # --- pid_constraints ---
            td_enable=pid_c.get('td_enable', True),
            td_ratio=pid_c.get('td_ratio', 0.0),
            td_max=pid_c.get('td_max', 0.0),
            ti_max=pid_c.get('ti_max', 60.0),
            pb_range=[pb_min, pb_max],
            gain_range=[std.get('gain_range', {}).get('K_min', 0.1),
                        std.get('gain_range', {}).get('K_max', 10.0)],
            tuning_strategy='aggressive' if pid_c.get('aggressive', False) else 'conservative',
            # --- tuning_strategy ---
            tau_c_factor=strategy.get('tau_c_factor', 1.5),
            safety_factor=strategy.get('safety_factor', 1.05),
            ti_multiplier=strategy.get('ti_multiplier', 1.0),
            integrating_mode=strategy.get('integrating_mode', False),
            # --- quality_thresholds ---
            max_overshoot_percent=max_overshoot,
            settling_time_factor=quality.get('settling_time_factor', 3.0),
            overshoot_discount=quality.get('overshoot_discount', 1.0),
            oscillation_tolerance=quality.get('oscillation_tolerance', 0.2),
            # --- 历史 ---
            historical_best_kp=(inst or {}).get('history', {}).get('best_kp') or 0.0,
            expert_notes=std.get('description', ''),
        )

    def _get_characterization(self, device_id: str) -> CharacterizationModel:
        """表征模型：当前 OS 尚未提供批处理，返回空壳等待运行时回填"""
        # [架构债 TODO] 未来由 OS 时序分析引擎提供，届时替换为 API 调用
        import datetime
        print(f"ℹ️ [SemanticProvider] 表征模型: OS 尚未提供 {device_id} 的动态特征，使用默认空值（将由算法运行时回填）")
        return CharacterizationModel(
            device_id=device_id,
            timestamp=datetime.datetime.now().isoformat()
        )

    def _get_data(self, device_id: str) -> DataModel:
        """数据模型：从实例 JSON 中提取 DCS 点位映射"""
        inst = self._load_instance_json(device_id)
        tag = inst.get('tag_name', device_id)
        return DataModel(
            device_id=device_id,
            pv_tag=f"{tag}.PV",
            sv_tag=f"{tag}.SV",
            out_tag=f"{tag}.OUT",
            db_source='os_historian'
        )

    def _get_metrics(self, device_id: str) -> MetricsModel:
        """指标模型：当前 OS 尚未提供 KPI 服务，返回空壳"""
        # [架构债 TODO] 未来由 OS 指标计算引擎提供
        return MetricsModel(device_id=device_id)

    # ================================================================
    # 对外唯一入口：组装集装箱
    # ================================================================

    def get_tuning_context(self, device_id: str) -> Dict[str, Any]:
        """
        组合出供大模型和传统算法消费的全息 Context 集装箱。
        
        从本地 JSON（模拟 OS）中读取真实的设备参数和标准约束，
        拆解映射到 6 大原子模型后，拼装成统一的上下文字典。
        """
        # 1. 加载原始 JSON
        inst_raw = self._load_instance_json(device_id)

        # 2. 本体模型 → 确定回路类型
        ontology = self._get_ontology(device_id)
        loop_type = ontology.loop_type

        # 3. 从各库抓取领域数据
        mechanism = self._get_mechanism(loop_type)
        knowledge = self._get_knowledge(loop_type, inst_raw)
        characterization = self._get_characterization(device_id)
        data_model = self._get_data(device_id)
        metrics = self._get_metrics(device_id)

        # 4. 组装集装箱
        ctx = {
            'loop_name': device_id,
            'loop_type': loop_type,

            # 6 大原生 Atomic 模型对象
            'ontology_model': ontology,
            'mechanism_model': mechanism,
            'knowledge_model': knowledge,
            'characterization_model': characterization,
            'data_model': data_model,
            'metrics_model': metrics,

            # 向下兼容映射（供尚未迁移的老 Stage 代码读取）
            'constraints': {
                'pb_range': knowledge.pb_range,
                'gain_range': knowledge.gain_range,
                'max_overshoot_percent': knowledge.max_overshoot_percent,
                'td_enable': knowledge.td_enable,
                'control_strategy': knowledge.tuning_strategy
            },
            'physical': {
                'tank_volume_m3': ontology.tank_volume_m3,
                'tank_cross_section_m2': ontology.tank_cross_section_m2,
                'valve_cv_max': ontology.valve_cv_max,
            },
            # DCS 当前参数（供算法做初始化参考）
            'current_pid': {
                'kp': inst_raw.get('dcs_config', {}).get('current_kp', 0),
                'ti': inst_raw.get('dcs_config', {}).get('current_ti', 0),
                'td': inst_raw.get('dcs_config', {}).get('current_td', 0),
                'pb': inst_raw.get('dcs_config', {}).get('current_pb', 0),
            } if inst_raw.get('dcs_config') else None,
        }

        return ctx
