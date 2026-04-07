from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class DataModel:
    """
    数据模型 (Data Model)
    ---------------------
    DCS系统上的底层测点/点位映射关系工程。
    """
    device_id: str
    pv_tag: str = ""                         # 过程变量的点位号
    sv_tag: str = ""                         # 设定值的点位号
    out_tag: str = ""                        # 输出值的点位号
    
    historical_table_ref: str = ""           # 存储在哪个时序大宽表
    db_source: str = "os_historian"          # 数据源

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DataModel':
        return cls(
            device_id=data.get('device_id', 'unknown'),
            pv_tag=data.get('pv_tag', ''),
            sv_tag=data.get('sv_tag', ''),
            out_tag=data.get('out_tag', ''),
            historical_table_ref=data.get('historical_table_ref', ''),
            db_source=data.get('db_source', 'os_historian')
        )
