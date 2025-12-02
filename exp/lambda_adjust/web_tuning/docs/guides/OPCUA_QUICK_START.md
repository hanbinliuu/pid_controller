# OPC UA 功能快速开始指南

## 🚀 快速开始

### 1. 安装依赖

```bash
cd backend
pip install asyncua
```

### 2. 启动后端服务

```bash
cd backend
python app.py
```

### 3. 在前端HTML中添加OPC UA标签页

已经创建了 `opcua_manager.js`，需要在 HTML 中引入并添加UI。

## 📝 使用步骤

### Step 1: 连接 OPC UA 服务器

1. 打开 Web 界面
2. 输入服务器地址，例如：`opc.tcp://localhost:4840`
3. 如果需要认证，输入用户名和密码
4. 点击"连接"按钮

### Step 2: 浏览节点

连接成功后，系统会自动浏览根节点，显示可用的数据点。

### Step 3: 选择数据节点

1. 浏览节点树，找到需要采集的过程变量（PV）
2. 点击"选择"按钮

### Step 4: 采集数据

1. 设置采集时长（默认60秒）
2. 设置采样间隔（默认1000毫秒）
3. 点击"采集并整定"按钮

### Step 5: 自动整定

数据采集完成后，系统会自动：
1. 切换到参数整定页面
2. 使用采集的数据进行模型识别
3. 计算最优PID参数

## 🧪 测试环境

### 使用 OPC UA 模拟服务器

如果没有真实的 OPC UA 服务器，可以使用模拟器：

#### 方法1: 使用 Python 模拟服务器

```python
# test_opcua_server.py
from asyncua import Server
import asyncio

async def main():
    server = Server()
    await server.init()
    server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")
    
    # 创建命名空间
    uri = "http://examples.freeopcua.github.io"
    idx = await server.register_namespace(uri)
    
    # 创建对象
    objects = server.get_objects_node()
    myobj = await objects.add_object(idx, "MyObject")
    
    # 创建变量（模拟过程变量）
    myvar = await myobj.add_variable(idx, "Temperature", 25.0)
    await myvar.set_writable()
    
    print("✅ OPC UA 服务器启动成功: opc.tcp://localhost:4840")
    
    async with server:
        while True:
            await asyncio.sleep(1)
            # 模拟温度变化
            current_value = await myvar.get_value()
            new_value = current_value + (random.random() - 0.5) * 2
            await myvar.write_value(new_value)

if __name__ == "__main__":
    import random
    asyncio.run(main())
```

运行：
```bash
python test_opcua_server.py
```

#### 方法2: 使用 UaExpert 客户端测试

下载 UaExpert（免费的 OPC UA 客户端）来测试连接。

## 📊 API 接口说明

### 1. 连接服务器
```http
POST /api/opcua/connect
Content-Type: application/json

{
  "url": "opc.tcp://localhost:4840",
  "username": "admin",  // 可选
  "password": "password"  // 可选
}
```

### 2. 浏览节点
```http
GET /api/opcua/browse?node_id=i:85
```

### 3. 读取节点值
```http
GET /api/opcua/read?node_id=ns=2;s=MyVariable
```

### 4. 采集数据
```http
POST /api/opcua/collect
Content-Type: application/json

{
  "node_id": "ns=2;s=Temperature",
  "duration_seconds": 60,
  "interval_ms": 1000
}
```

### 5. 断开连接
```http
POST /api/opcua/disconnect
```

### 6. 获取连接状态
```http
GET /api/opcua/status
```

## 🔧 配置说明

### 常见 OPC UA 服务器地址格式

```
opc.tcp://localhost:4840
opc.tcp://192.168.1.100:4840
opc.tcp://plc.example.com:4840
```

### 节点ID格式

```
i=85                    # 数字节点ID
ns=2;s=MyVariable      # 字符串节点ID
ns=2;i=1001            # 带命名空间的数字ID
```

## ⚠️ 注意事项

1. **网络连接**：确保能访问 OPC UA 服务器
2. **防火墙**：检查端口是否开放（默认4840）
3. **安全策略**：简化版使用 None 安全策略，生产环境需要配置
4. **数据质量**：采集前确认节点数据质量良好
5. **采样频率**：根据过程特性设置合适的采样间隔

## 🐛 常见问题

### Q1: 连接超时
- 检查服务器地址是否正确
- 检查网络连接
- 检查防火墙设置

### Q2: 认证失败
- 确认用户名和密码正确
- 检查服务器是否需要认证

### Q3: 找不到节点
- 使用 UaExpert 等工具确认节点ID
- 检查命名空间索引

### Q4: 数据采集失败
- 确认节点可读
- 检查数据类型是否为数值
- 查看后端日志

## 📚 下一步

1. **添加UI界面** - 在 HTML 中集成 OPC UA 配置面板
2. **测试连接** - 使用模拟服务器测试功能
3. **实际应用** - 连接真实的工业设备
4. **功能扩展** - 添加实时监控、报警等功能

## 🎯 完整示例

```javascript
// 1. 连接服务器
await opcuaManager.connect();

// 2. 浏览节点
await opcuaManager.browseNodes('i=85');

// 3. 选择节点
opcuaManager.selectNode('ns=2;s=Temperature', 'Temperature');

// 4. 采集数据并整定
await opcuaManager.collectAndTune();
```

## 📞 技术支持

如有问题，请查看：
- 后端日志：`backend/backend.log`
- 浏览器控制台
- OPC UA 服务器日志
