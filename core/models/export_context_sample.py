"""
导出一份真实的 SemanticProvider 语义上下文样本 JSON
用于发送给 A公司（大模型厂商）作为 API 接口契约文档
"""
import json
import sys
import os
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.models import SemanticProvider

def export_sample(device_id: str = '2216_LIC_50104'):
    provider = SemanticProvider()
    ctx = provider.get_tuning_context(device_id)
    
    # 将 dataclass 对象序列化为纯字典
    serializable_ctx = {}
    for key, value in ctx.items():
        if hasattr(value, '__dataclass_fields__'):
            serializable_ctx[key] = asdict(value)
        else:
            serializable_ctx[key] = value
    
    # 追加一个说明性的"API调用约定"头部
    api_contract = {
        "_meta": {
            "version": "1.0.0",
            "description": "HolliCube OS 语义层 -> PID 整定上下文 (TuningContext) 标准数据契约",
            "usage": "A公司大模型整定接口必须接受此结构作为输入，并返回标准 PID 结果 JSON",
            "generated_for_device": device_id
        },
        "tuning_context": serializable_ctx,
        "_expected_response_format": {
            "success": True,
            "pid_parameters": {
                "Kp": 2.50,
                "Ti": 208.0,
                "Td": 0.0,
                "pb": 40.0
            },
            "tuning_features": {
                "tuning_method": "llm_xxx",
                "reasoning_summary": "大模型推理过程摘要文本"
            },
            "model_rating": 8.5,
            "confidence_score": 0.85
        }
    }
    
    output_path = os.path.join(os.path.dirname(__file__), 'api_contract_sample.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(api_contract, f, ensure_ascii=False, indent=2, default=str)
    
    print(f"✅ API 契约样本已导出: {output_path}")
    print(f"📦 包含 {len(serializable_ctx)} 个顶层字段")
    print(f"\n请将此文件发送给 A公司，作为大模型整定 API 的输入规范。")

if __name__ == '__main__':
    device = sys.argv[1] if len(sys.argv) > 1 else '2216_LIC_50104'
    export_sample(device)
