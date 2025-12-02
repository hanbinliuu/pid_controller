# 🔄 PID参数下发流程说明

## 📋 概述

在实际工业场景中，PID参数更新后需要下发到真实的PLC/DCS控制器。本文档详细说明参数下发的完整流程。

---

## 🎯 参数下发的三种场景

### 1. **自动整定后下发** 🤖
系统自动计算出新参数后，自动下发到PLC

### 2. **手动整定后下发** 👤
用户手动触发整定，系统计算后下发

### 3. **手动修改后下发** ✏️
用户直接修改参数值，手动下发到PLC

---

## 🔄 完整下发流程

### 流程图

```
┌─────────────────────────────────────────────────────────────┐
│  1. 参数计算/修改                                             │
│     - 自动整定计算新参数                                       │
│     - 或用户手动修改参数                                       │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  2. 参数验证                                                  │
│     - 检查参数合理性                                          │
│     - 计算与当前参数的差异                                     │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  3. OPC UA连接检查                                            │
│     - 检查是否连接到OPC UA Server                             │
│     - 仿真模式：连接到本地仿真服务器                           │
│     - 生产模式：连接到真实PLC的OPC UA Server                  │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  4. 批量写入PID参数                                           │
│     - 写入 Pb (比例带) 到 PLC                                 │
│     - 写入 Ti (积分时间) 到 PLC                               │
│     - 写入 Td (微分时间) 到 PLC                               │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  5. 验证写入结果                                              │
│     - 检查每个参数是否写入成功                                 │
│     - 记录成功/失败日志                                        │
└─────────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────────┐
│  6. 更新系统状态                                              │
│     - 更新数据库中的参数记录                                   │
│     - 通过WebSocket推送给前端                                 │
│     - 写入OPC UA状态节点（可选）                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 💻 代码实现

### 核心方法：`_write_pid_to_opcua`

```python
async def _write_pid_to_opcua(
    self, 
    loop_id: str, 
    pb: float,      # 新的比例带
    ti: float,      # 新的积分时间
    td: float,      # 新的微分时间
    force_write: bool = False  # 是否强制下发
):
    """将PID参数写入OPC UA（下发到PLC）"""
    
    # 1. 获取回路配置
    loop = self.loops_storage.get_loop(loop_id)
    opcua_config = loop.get('opcua_config', {})
    
    # 2. 获取PID参数节点ID（PLC中的地址）
    pid_pb_node = opcua_config.get('pid_pb_node_id')  # 例如: "ns=3;s=DB100.PID.Pb"
    pid_ti_node = opcua_config.get('pid_ti_node_id')  # 例如: "ns=3;s=DB100.PID.Ti"
    pid_td_node = opcua_config.get('pid_td_node_id')  # 例如: "ns=3;s=DB100.PID.Td"
    
    # 3. 检查OPC UA连接
    if not self.opcua_client.connected:
        print("❌ OPC UA未连接，无法下发参数")
        return
    
    # 4. 批量写入参数到PLC
    await self.opcua_client.write_node_value(pid_pb_node, float(pb))
    await self.opcua_client.write_node_value(pid_ti_node, float(ti))
    await self.opcua_client.write_node_value(pid_td_node, float(td))
    
    print("✅ 所有PID参数已成功写入OPC UA")
```

---

## 🔍 详细步骤说明

### 步骤1: 参数计算/修改

#### 自动整定场景
```python
# 系统自动计算新参数
new_pb, new_ti, new_td = self.identifier.auto_tune_from_json(...)

# 自动下发
await self._write_pid_to_opcua(loop_id, new_pb, new_ti, new_td, force_write=True)
```

#### 手动修改场景
```python
# 用户通过前端修改参数
# POST /api/loops/{loop_id}/pid_params
{
    "pb": 50.0,
    "ti": 120.0,
    "td": 30.0
}

# 后端接收后下发
await self._write_pid_to_opcua(loop_id, pb, ti, td, force_write=True)
```

---

### 步骤2: 参数验证

```python
# 获取当前参数
current_pid = loop.get('pid_params', {})
current_pb = current_pid.get('pb', 0)
current_ti = current_pid.get('ti', 0)
current_td = current_pid.get('td', 0)

# 计算差异
pb_diff = abs(new_pb - current_pb)
ti_diff = abs(new_ti - current_ti)
td_diff = abs(new_td - current_td)

# 日志输出
print(f"当前: Pb={current_pb:.1f}%, Ti={current_ti:.1f}s, Td={current_td:.1f}s")
print(f"新值: Pb={new_pb:.1f}%, Ti={new_ti:.1f}s, Td={new_td:.1f}s")
print(f"差异: ΔPb={pb_diff:.2f}%, ΔTi={ti_diff:.2f}s, ΔTd={td_diff:.2f}s")
```

---

### 步骤3: OPC UA连接检查

```python
# 检查连接状态
if not self.opcua_client.connected:
    print("❌ OPC UA未连接，无法下发参数")
    return

# 仿真模式
if self.opcua_client.mode == 'simulation':
    print("🧪 [仿真] 参数将写入仿真服务器")
    
# 生产模式
else:
    print("🏭 [生产] 参数将写入真实 PLC/DCS")
```

---

### 步骤4: 批量写入参数

```python
# 定义要写入的参数
params_to_write = [
    ('Pb', pid_pb_node, pb, '%'),      # 比例带
    ('Ti', pid_ti_node, ti, 's'),      # 积分时间
    ('Td', pid_td_node, td, 's')       # 微分时间
]

# 逐个写入
results = []
for param_name, node_id, value, unit in params_to_write:
    try:
        # 调用OPC UA Client写入节点
        result = await self.opcua_client.write_node_value(node_id, float(value))
        success = result and result.get('success')
        results.append(success)
        
        if success:
            print(f"✅ {param_name}={value:.1f}{unit}")
        else:
            print(f"❌ {param_name} 写入失败")
    except Exception as e:
        print(f"❌ {param_name} 写入异常: {e}")
        results.append(False)
```

---

### 步骤5: 验证写入结果

```python
# 检查所有参数是否都写入成功
all_success = all(results)

if all_success:
    print("✅ 所有PID参数已成功写入OPC UA")
else:
    failed_count = results.count(False)
    print(f"⚠️  {failed_count}/3 个参数写入失败")
```

---

### 步骤6: 更新系统状态

```python
# 1. 更新数据库
self.loops_storage.update_loop_pid_params(loop_id, {
    'pb': pb,
    'ti': ti,
    'td': td,
    'last_updated': datetime.now()
})

# 2. 推送给前端（WebSocket）
await self.ws_manager.broadcast_to_loop(loop_id, {
    'type': 'pid_params_updated',
    'data': {
        'pb': pb,
        'ti': ti,
        'td': td
    }
})

# 3. 写入OPC UA状态节点（可选）
await self._write_state_to_opcua(loop_id, 'TUNING_COMPLETED')
```

---

## 🏭 实际场景示例

### 场景1: 西门子 PLC

```python
# 配置文件 (config/production.py)
LOOP_CONFIG = {
    "loop_id": "reactor_temp_001",
    "name": "反应釜温度控制",
    
    "opcua_config": {
        # 西门子 S7-1500 PLC 的 OPC UA 节点
        "pid_pb_node_id": "ns=3;s=DB100.PID.Pb",    # PLC数据块DB100中的Pb
        "pid_ti_node_id": "ns=3;s=DB100.PID.Ti",    # PLC数据块DB100中的Ti
        "pid_td_node_id": "ns=3;s=DB100.PID.Td"     # PLC数据块DB100中的Td
    }
}

# 下发流程
# 1. 系统计算出新参数: Pb=45%, Ti=100s, Td=25s
# 2. 通过OPC UA写入到西门子PLC的DB100数据块
# 3. PLC接收到新参数，立即应用到温度控制回路
# 4. 控制器开始使用新参数执行PID控制
```

**日志输出**:
```
🏭 [生产模式] 正在连接到工业 OPC UA 服务器: opc.tcp://192.168.1.100:4840
✅ [生产模式] OPC UA 连接成功 - 连接到真实工业系统

📡 准备下发PID参数...
   当前: Pb=50.0%, Ti=120.0s, Td=30.0s
   新值: Pb=45.0%, Ti=100.0s, Td=25.0s
   差异: ΔPb=5.00%, ΔTi=20.00s, ΔTd=5.00s
   🔴 强制下发模式：确保参数同步到OPC UA

   ✅ Pb=45.0%
   🏭 [生产] 参数已写入真实 PLC/DCS
   ✅ Ti=100.0s
   🏭 [生产] 参数已写入真实 PLC/DCS
   ✅ Td=25.0s
   🏭 [生产] 参数已写入真实 PLC/DCS

✅ 所有PID参数已成功写入OPC UA
```

---

### 场景2: 施耐德 DCS

```python
# 配置文件
LOOP_CONFIG = {
    "loop_id": "column_pressure_001",
    "name": "精馏塔压力控制",
    
    "opcua_config": {
        # 施耐德 Modicon 的 OPC UA 节点
        "pid_pb_node_id": "ns=2;i=2001",  # 使用数字标识符
        "pid_ti_node_id": "ns=2;i=2002",
        "pid_td_node_id": "ns=2;i=2003"
    }
}

# 下发流程相同
# 1. 计算新参数
# 2. 通过OPC UA写入到施耐德DCS
# 3. DCS接收并应用新参数
```

---

## 🔒 安全机制

### 1. **参数合理性检查**

```python
# 检查参数范围
if not (0 < pb < 500):
    raise ValueError(f"比例带超出范围: {pb}")
if not (0 < ti < 3600):
    raise ValueError(f"积分时间超出范围: {ti}")
if not (0 <= td < 600):
    raise ValueError(f"微分时间超出范围: {td}")
```

### 2. **连接状态检查**

```python
# 确保OPC UA已连接
if not self.opcua_client.connected:
    print("❌ OPC UA未连接，无法下发参数")
    return False
```

### 3. **写入结果验证**

```python
# 验证每个参数是否写入成功
for param in params:
    result = await write_param(param)
    if not result.success:
        # 记录失败日志
        # 可选：回滚已写入的参数
        pass
```

### 4. **强制下发模式**

```python
# force_write=True: 手动整定时强制下发
# force_write=False: 自动整定时，参数差异小则跳过
await self._write_pid_to_opcua(
    loop_id, pb, ti, td, 
    force_write=True  # 确保参数同步
)
```

---

## 📊 日志示例

### 成功下发

```
📡 准备下发PID参数...
   当前: Pb=50.0%, Ti=120.0s, Td=30.0s
   新值: Pb=45.0%, Ti=100.0s, Td=25.0s
   差异: ΔPb=5.00%, ΔTi=20.00s, ΔTd=5.00s
   🔴 强制下发模式：确保参数同步到OPC UA
   
   ✅ Pb=45.0%
   ✅ Ti=100.0s
   ✅ Td=25.0s

✅ 所有PID参数已成功写入OPC UA
```

### 部分失败

```
📡 准备下发PID参数...
   ✅ Pb=45.0%
   ❌ Ti 写入失败: Connection timeout
   ✅ Td=25.0s

⚠️  1/3 个参数写入失败
```

### OPC UA未连接

```
📡 准备下发PID参数...
❌ OPC UA未连接，无法下发参数
💡 提示：请检查OPC UA服务器连接状态
```

---

## 🔄 重新下发机制

### 自动重试

```python
# 如果写入失败，可以配置自动重试
MAX_RETRIES = 3
retry_count = 0

while retry_count < MAX_RETRIES:
    result = await self._write_pid_to_opcua(loop_id, pb, ti, td)
    if result:
        break
    retry_count += 1
    await asyncio.sleep(1)  # 等待1秒后重试
```

### 手动重新下发

```python
# 前端提供"重新下发"按钮
# POST /api/loops/{loop_id}/resend_pid_params

@app.post("/api/loops/{loop_id}/resend_pid_params")
async def resend_pid_params(loop_id: str):
    """重新下发当前PID参数到PLC"""
    loop = loops_storage.get_loop(loop_id)
    pid_params = loop.get('pid_params', {})
    
    # 强制下发当前参数
    await auto_tuning_system._write_pid_to_opcua(
        loop_id,
        pid_params['pb'],
        pid_params['ti'],
        pid_params['td'],
        force_write=True
    )
    
    return {"success": True, "message": "参数已重新下发"}
```

---

## 🎯 关键点总结

### ✅ 参数下发流程

1. **计算/修改参数** → 自动整定或手动修改
2. **参数验证** → 检查合理性和差异
3. **连接检查** → 确保OPC UA已连接
4. **批量写入** → 依次写入Pb、Ti、Td
5. **结果验证** → 检查写入是否成功
6. **状态更新** → 更新数据库和前端

### ✅ 仿真 vs 生产

| 项目 | 仿真模式 | 生产模式 |
|------|---------|---------|
| **OPC UA Server** | 本地仿真服务器 | 真实PLC的OPC UA Server |
| **节点地址** | 仿真节点 | 真实PLC地址 |
| **参数下发** | 写入仿真服务器 | 写入真实PLC/DCS |
| **日志标识** | 🧪 [仿真] | 🏭 [生产] |
| **影响范围** | 无实际影响 | 直接影响生产过程 |

### ✅ 安全保障

- ✅ 参数合理性检查
- ✅ 连接状态验证
- ✅ 写入结果确认
- ✅ 详细日志记录
- ✅ 失败重试机制

---

## 📚 相关文档

- **[快速开始.md](./快速开始.md)** - 系统启动指南
- **[环境配置说明.md](./环境配置说明.md)** - 环境配置详解
- **[opcua_client.py](./opcua_client.py)** - OPC UA客户端实现
- **[auto_tuning_system.py](./auto_tuning_system.py)** - 自动整定系统

---

**参数下发是工业控制的关键环节，务必确保配置正确！** 🎯
