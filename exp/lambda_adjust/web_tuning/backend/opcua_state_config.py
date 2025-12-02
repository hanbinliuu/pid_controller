"""
OPC UA State节点配置

用于实时状态同步，减少状态延迟
"""

# State节点配置
OPCUA_STATE_NODE_CONFIG = {
    # 默认的State节点ID（可在创建回路时覆盖）
    'default_state_node_id': 'ns=2;i=1010',
    
    # State值映射
    'state_mapping': {
        'STABLE': {
            'is_unsteady': False,
            'description': '稳态'
        },
        'DISTURBANCE': {
            'is_unsteady': True,
            'description': '非稳态（扰动）'
        },
        'STABILIZING': {
            'is_unsteady': True,  # 正在稳定期间视为非稳态
            'description': '正在稳定'
        }
    },
    
    # 检测频率配置
    'monitoring_interval_seconds': 1,  # 后端检测间隔：1秒
    'frontend_refresh_interval_ms': 1000,  # 前端刷新间隔：1000ms
}

# 使用说明
"""
## 配置OPC UA回路时添加State节点

在创建或更新回路时，在opcua_config中添加state_node_id：

```python
loop_data = {
    'name': 'tmp',
    'data_source': 'opcua',
    'opcua_config': {
        'pv_node_id': 'ns=2;i=1001',
        'sv_node_id': 'ns=2;i=1005',
        'mv_node_id': 'ns=2;i=1006',
        'state_node_id': 'ns=2;i=1010',  # 添加State节点
        'is_collecting': True
    }
}
```

## State节点值规范

OPC UA Server的State节点应返回以下字符串值之一：
- "STABLE": 稳态
- "DISTURBANCE": 非稳态（扰动中）
- "STABILIZING": 正在稳定（新参数应用后的稳定期）

## 优势

1. **零延迟**：直接读取OPC UA Server的实时状态，无需等待数据采集和分析
2. **状态一致**：OPC UA Server、Backend、Frontend三者状态完全同步
3. **降低负载**：减少复杂的数据分析计算
4. **可靠回退**：当State节点不可用时，自动回退到数据检测模式
"""
