# 如何使用 - 自动整定系统

## 🎯 两种使用方式

### 方式1: 先测试新的OPC UA服务器（推荐）⭐

这种方式最简单，先体验真实的PID控制循环场景。

### 方式2: 完整集成自动整定系统

需要修改后端和前端代码，实现完全自动化。

---

## 🚀 方式1: 测试新的OPC UA服务器（5分钟）

### Step 1: 启动新的OPC UA服务器

```bash
cd /Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/web_tuning

# 启动优化后的OPC UA服务器
python opcua_realistic_server.py
```

你会看到：
```
================================================================================
🚀 启动OPC UA真实场景模拟服务器
================================================================================
✅ OPC UA服务器启动成功
ℹ️  📡 端点: opc.tcp://localhost:4840/freeopcua/server/
ℹ️  🔢 命名空间: 2

================================================================================
🔄 开始真实场景模拟
================================================================================
ℹ️  场景流程: 稳态 → 非稳态 → 重整定 → 新参数稳定 → 循环

[10:47:00] ✅ STABLE       | PV=25.12, SV=25.00, MV=48.5% | PID(100/50/0) | 时长=10s
```

### Step 2: 启动Web后端

打开新终端：

```bash
cd /Users/lhb/Documents/pycharmProject/hollicube/pid-agent-mvp/exp/lambda_adjust/web_tuning/backend

# 启动后端
python app.py
```

### Step 3: 打开浏览器

访问: `http://localhost:8000`

### Step 4: 添加OPC UA回路

1. 进入"回路管理"页面
2. 点击"添加回路"
3. 填写信息：
   - **回路名称**: `tmp`
   - **数据源**: 选择 `OPC UA`
   - **OPC UA端点**: `opc.tcp://localhost:4840/freeopcua/server/`
   - **PV节点**: `ns=2;i=1001`
   - **SV节点**: `ns=2;i=1005`
   - **MV节点**: `ns=2;i=1006`
   - **PID参数节点**（可选，用于自动下发参数）:
     - Pb节点: `ns=2;i=1007`
     - Ti节点: `ns=2;i=1008`
     - Td节点: `ns=2;i=1009`
     - 💡 **说明**：如果不填写，可以正常整定，但无法自动下发参数到OPC UA

4. 点击"保存"

### Step 5: 开始采集

1. 在回路卡片上点击"开始采集"
2. 观察状态显示"✓ 稳态"（绿色）

### Step 6: 观察自动整定流程

#### 6.1 等待扰动（约2-3分钟）

OPC UA服务器会自动进入扰动阶段，你会看到：

**OPC UA服务器日志**:
```
================================================================================
🚨 周期 0: 进入扰动阶段
================================================================================
ℹ️     扰动类型: load_change
ℹ️     持续时间: 60秒
```

**前端界面**:
- 状态从"✓ 稳态"变为"🚨 非稳态"（红色）
- 延迟: 5-10秒（当前轮询机制）

#### 6.2 手动触发整定

当看到"🚨 非稳态"后：

1. 点击回路卡片上的"整定"按钮
2. 等待整定完成
3. 观察新的PID参数

#### 6.3 观察参数下发

**OPC UA服务器日志**:
```
🔧 检测到PID参数更新:
   旧参数: Pb=100.0, Ti=50.0, Td=0.0
   新参数: Pb=85.0, Ti=42.0, Td=3.5
🔧 PID参数已更新: Pb=85.0%, Ti=42.0s, Td=3.5s
✅ 新PID参数已应用
```

**前端界面**:
- 回路卡片显示新的PID参数
- 状态变为"✓ 稳态"

#### 6.4 观察新参数效果

OPC UA服务器会：
1. 应用新的PID参数
2. 进入稳定期（90秒）
3. 重新回到稳态
4. 等待下一个扰动周期

### 🎉 完成！

你已经体验了完整的PID控制循环：
- ✅ 真实的扰动场景
- ✅ PID整定
- ✅ 参数下发到OPC UA
- ✅ 新参数生效

---

## 🔧 方式2: 完整集成自动整定系统（15分钟）

如果你想实现**完全自动化**（无需手动点击整定按钮），按照以下步骤：

### Step 1: 后端集成（5分钟）

#### 1.1 修改 `backend/app.py`

在文件顶部添加导入：

```python
# 在现有导入后添加（约第40行）
from fastapi import WebSocket, WebSocketDisconnect
from backend.websocket_handler import ws_manager
from backend.auto_tuning_system import initialize_system, auto_tuning_system
```

#### 1.2 添加启动事件

找到 `@app.on_event("startup")` 函数，在末尾添加：

```python
@app.on_event("startup")
async def startup_event():
    # ... 现有代码 ...
    
    # 初始化自动整定系统
    initialize_system(loops_storage, opcua_client)
    print("✅ 自动整定系统已启动")
```

#### 1.3 添加WebSocket端点

在文件末尾（约第3358行后）添加：

```python
# ============================================================================
# WebSocket实时状态推送
# ============================================================================

@app.websocket("/ws/loops/{loop_id}")
async def websocket_endpoint(websocket: WebSocket, loop_id: str):
    """WebSocket端点 - 实时状态推送"""
    await ws_manager.connect(websocket, loop_id)
    
    try:
        while True:
            # 保持连接活跃
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, loop_id)
```

#### 1.4 替换稳态检测任务

找到 `stability_monitoring_task` 函数（约第3001行），替换为：

```python
async def stability_monitoring_task():
    """使用新的自动整定系统"""
    print("✅ 稳定性监控任务已启动")
    
    # 等待系统初始化
    while auto_tuning_system is None:
        await asyncio.sleep(1)
    
    # 启动所有OPC UA回路的监控
    all_loops = loops_storage.get_all_loops()
    for loop in all_loops:
        if loop.get('data_source') == 'opcua' and loop.get('opcua_config', {}).get('is_collecting'):
            await auto_tuning_system.start_monitoring(loop['id'])
    
    # 保持任务运行
    while True:
        await asyncio.sleep(60)
```

#### 1.5 修改OPC UA采集接口

找到 `start_opcua_collection` 函数（约第1958行），在返回前添加：

```python
@app.post("/api/opcua/start-collection/{loop_id}")
async def start_opcua_collection(loop_id: str):
    # ... 现有代码 ...
    
    # 启动自动整定监控
    if auto_tuning_system:
        await auto_tuning_system.start_monitoring(loop_id)
    
    return {"success": True, "message": "采集已开始"}
```

找到 `stop_opcua_collection` 函数，在返回前添加：

```python
@app.post("/api/opcua/stop-collection/{loop_id}")
async def stop_opcua_collection(loop_id: str):
    # ... 现有代码 ...
    
    # 停止自动整定监控
    if auto_tuning_system:
        await auto_tuning_system.stop_monitoring(loop_id)
    
    return {"success": True, "message": "采集已停止"}
```

### Step 2: 前端集成（5分钟）

#### 2.1 添加WebSocket客户端

在 `pid_tuning_interface_v2.html` 中，找到其他脚本引用的位置，添加：

```html
<!-- WebSocket客户端 -->
<script src="utils/websocketClient.js"></script>
```

#### 2.2 修改 `loops_manager.js`

在文件末尾添加：

```javascript
// ============================================================
// WebSocket实时状态同步
// ============================================================

/**
 * 订阅回路WebSocket
 */
function subscribeLoopWebSocket(loopId) {
    if (!window.wsManager) {
        console.warn('⚠️  WebSocket管理器未初始化');
        return;
    }
    
    window.wsManager.subscribe(loopId, (data) => {
        console.log(`📨 收到回路 ${loopId} 状态更新:`, data);
        updateLoopStateUI(data.loop_id, data.state, data.is_unsteady, data.is_retuning);
    });
}

/**
 * 实时更新回路状态UI
 */
function updateLoopStateUI(loopId, state, isUnsteady, isRetuning) {
    const loopCard = document.querySelector(`[data-loop-id="${loopId}"]`);
    if (!loopCard) return;
    
    // 查找状态徽章容器
    const loopHeader = loopCard.querySelector('.loop-header');
    if (!loopHeader) return;
    
    // 查找或创建稳定性徽章
    let stabilityBadge = loopHeader.querySelector('.stability-badge');
    if (!stabilityBadge) {
        stabilityBadge = document.createElement('span');
        stabilityBadge.className = 'stability-badge';
        stabilityBadge.style.marginLeft = '10px';
        loopHeader.appendChild(stabilityBadge);
    }
    
    // 根据状态更新徽章
    if (isRetuning) {
        stabilityBadge.innerHTML = `<span style="font-size: 11px; padding: 2px 8px; background: #3b82f6; border-radius: 4px; color: white; animation: pulse 2s infinite;">
            🔄 正在整定
        </span>`;
    } else if (isUnsteady) {
        stabilityBadge.innerHTML = `<span style="font-size: 11px; padding: 2px 8px; background: #ef4444; border-radius: 4px; color: white; animation: pulse 2s infinite;">
            🚨 非稳态
        </span>`;
    } else {
        stabilityBadge.innerHTML = `<span style="font-size: 11px; padding: 2px 8px; background: #10b981; border-radius: 4px; color: white;">
            ✓ 稳态
        </span>`;
    }
    
    console.log(`✅ 实时更新回路 ${loopId} 状态: ${state}`);
}

// 页面卸载时清理WebSocket
window.addEventListener('beforeunload', () => {
    if (window.wsManager) {
        window.wsManager.unsubscribeAll();
    }
});
```

在 `renderLoops` 函数末尾添加：

```javascript
async function renderLoops(loops) {
    // ... 现有代码 ...
    
    // 为OPC UA回路订阅WebSocket
    loops.forEach(loop => {
        if (loop.data_source === 'opcua' && loop.opcua_config?.is_collecting) {
            subscribeLoopWebSocket(loop.id);
        }
    });
}
```

### Step 3: 重启服务

```bash
# 停止现有服务（Ctrl+C）

# 重新启动OPC UA服务器
python opcua_realistic_server.py

# 重新启动后端（新终端）
cd backend
python app.py
```

### Step 4: 测试自动整定

1. 刷新浏览器页面
2. 添加OPC UA回路（如果还没有）
3. 开始采集
4. **等待扰动（2-3分钟）**
5. 观察：
   - ✅ 前端**立即**显示"🚨 非稳态"（<100ms）
   - ✅ 15秒后**自动**触发整定
   - ✅ 显示"🔄 正在整定"
   - ✅ 整定完成后**自动**下发参数
   - ✅ 显示"🔄 稳定期"
   - ✅ 90秒后显示"✓ 稳态"

### 🎉 完成！

现在你有了完全自动化的整定系统！

---

## 📊 对比两种方式

| 特性 | 方式1（测试） | 方式2（完整集成） |
|------|--------------|------------------|
| 扰动检测 | ✅ 自动 | ✅ 自动 |
| 触发整定 | ⚠️ 手动点击 | ✅ 自动触发 |
| 参数下发 | ✅ 自动 | ✅ 自动 |
| 状态更新 | ⚠️ 5-10秒延迟 | ✅ <100ms实时 |
| 修改代码 | ❌ 不需要 | ✅ 需要 |
| 推荐场景 | 快速测试 | 生产使用 |

## 🐛 常见问题

### Q1: OPC UA连接失败

**A**: 检查端口4840是否被占用：
```bash
lsof -i :4840
```

### Q2: WebSocket连接失败

**A**: 检查后端是否正确启动，查看是否有错误日志。

### Q3: 状态不更新

**A**: 
1. 打开浏览器控制台，查看是否有错误
2. 检查WebSocket是否连接成功
3. 刷新页面重试

### Q4: 参数未下发到OPC UA

**A**: 
1. 检查回路配置中的PID节点ID是否正确
2. 查看OPC UA服务器日志
3. 确认OPC UA服务器正在运行

## 📚 相关文档

- `AUTO_TUNING_OPTIMIZATION.md` - 详细的系统架构
- `QUICK_INTEGRATION_GUIDE.md` - 详细的集成步骤
- `OPCUA_REALISTIC_SCENARIO.md` - OPC UA场景说明

## 💡 建议

1. **先用方式1测试**，熟悉整个流程
2. **确认无误后**，再进行方式2的完整集成
3. **保留git备份**，方便回滚

祝你使用愉快！🚀
