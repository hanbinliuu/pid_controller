"""
控制回路数据存储 - 使用JSON文件
"""

import json
import os
from typing import List, Dict, Optional
from datetime import datetime
import uuid
import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """自定义JSON编码器，处理NumPy类型"""
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)


class LoopsStorage:
    """回路存储管理"""
    
    def __init__(self, storage_file: str = "loops_data.json"):
        self.storage_file = storage_file
        self._ensure_storage_file()
    
    def _ensure_storage_file(self):
        """确保存储文件存在"""
        if not os.path.exists(self.storage_file):
            self._save_data({"loops": []})
    
    def _load_data(self) -> Dict:
        """加载数据"""
        try:
            with open(self.storage_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"加载数据失败: {e}")
            return {"loops": []}
    
    def _save_data(self, data: Dict):
        """保存数据"""
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
        except Exception as e:
            print(f"保存数据失败: {e}")
            import traceback
            traceback.print_exc()
    
    def get_all_loops(self) -> List[Dict]:
        """获取所有回路"""
        data = self._load_data()
        return data.get("loops", [])
    
    def get_loop(self, loop_id: str) -> Optional[Dict]:
        """获取单个回路"""
        loops = self.get_all_loops()
        for loop in loops:
            if loop["id"] == loop_id:
                return loop
        return None
    
    def add_loop(self, loop_data: Dict) -> Dict:
        """添加回路"""
        data = self._load_data()
        loops = data.get("loops", [])
        
        # 生成ID
        if "id" not in loop_data:
            loop_data["id"] = str(uuid.uuid4())[:8]
        
        # 添加时间戳
        loop_data["created_at"] = datetime.now().isoformat()
        loop_data["updated_at"] = datetime.now().isoformat()
        
        # 默认值
        if "status" not in loop_data:
            loop_data["status"] = "active"
        
        # 数据源类型：file（JSON文件）或 opcua（OPC UA实时数据）
        if "data_source" not in loop_data:
            loop_data["data_source"] = "file"
        
        # 如果是OPC UA数据源，添加OPC UA配置
        if loop_data.get("data_source") == "opcua":
            if "opcua_config" not in loop_data:
                loop_data["opcua_config"] = {
                    "node_id": "",
                    "sampling_interval": 1000,
                    "is_collecting": False,
                    "auto_tuning_enabled": False  # 是否启用自动整定
                }
        
        loops.append(loop_data)
        data["loops"] = loops
        self._save_data(data)
        
        return loop_data
    
    def update_loop(self, loop_id: str, updates: Dict) -> Optional[Dict]:
        """更新回路"""
        data = self._load_data()
        loops = data.get("loops", [])
        
        for i, loop in enumerate(loops):
            if loop["id"] == loop_id:
                # 更新字段
                loop.update(updates)
                loop["updated_at"] = datetime.now().isoformat()
                loops[i] = loop
                data["loops"] = loops
                self._save_data(data)
                return loop
        
        return None
    
    def delete_loop(self, loop_id: str) -> bool:
        """删除回路"""
        data = self._load_data()
        loops = data.get("loops", [])
        
        original_count = len(loops)
        loops = [loop for loop in loops if loop["id"] != loop_id]
        
        if len(loops) < original_count:
            data["loops"] = loops
            self._save_data(data)
            return True
        
        return False
    
    def get_loops_by_area(self, area: str) -> List[Dict]:
        """按区域获取回路"""
        loops = self.get_all_loops()
        return [loop for loop in loops if loop.get("area") == area]
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        loops = self.get_all_loops()
        
        total = len(loops)
        active = len([l for l in loops if l.get("status") == "active"])
        
        # 计算平均评分
        scores = [l.get("performance", {}).get("score", 0) for l in loops]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        return {
            "total_loops": total,
            "active_loops": active,
            "average_score": avg_score,
            "areas": list(set(l.get("area", "未分类") for l in loops))
        }


# 全局实例 - 使用data目录下的文件
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_storage_file = os.path.join(_data_dir, "loops_data.json")
storage = LoopsStorage(_storage_file)
