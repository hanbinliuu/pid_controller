/**
 * WebSocket客户端 - 实时状态同步
 * 用于接收OPC UA回路的实时状态更新
 */

class LoopWebSocketClient {
    constructor(loopId, onStateUpdate) {
        this.loopId = loopId;
        this.onStateUpdate = onStateUpdate;
        this.ws = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 2000; // 2秒
        this.isManualClose = false;
    }
    
    /**
     * 连接WebSocket
     */
    connect() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            console.log(`📡 WebSocket已连接: ${this.loopId}`);
            return;
        }
        
        const wsUrl = `ws://${window.location.hostname}:8000/ws/loops/${this.loopId}`;
        console.log(`📡 连接WebSocket: ${wsUrl}`);
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log(`✅ WebSocket已连接: ${this.loopId}`);
                this.reconnectAttempts = 0;
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    console.log(`📨 收到状态更新:`, data);
                    
                    if (data.type === 'state_update' && this.onStateUpdate) {
                        this.onStateUpdate(data);
                    }
                } catch (error) {
                    console.error('❌ 解析WebSocket消息失败:', error);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error(`❌ WebSocket错误: ${this.loopId}`, error);
            };
            
            this.ws.onclose = () => {
                console.log(`📡 WebSocket已断开: ${this.loopId}`);
                
                // 如果不是手动关闭，尝试重连
                if (!this.isManualClose && this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    console.log(`🔄 尝试重连 (${this.reconnectAttempts}/${this.maxReconnectAttempts})...`);
                    
                    setTimeout(() => {
                        this.connect();
                    }, this.reconnectDelay);
                }
            };
            
        } catch (error) {
            console.error(`❌ 创建WebSocket失败: ${this.loopId}`, error);
        }
    }
    
    /**
     * 断开连接
     */
    disconnect() {
        this.isManualClose = true;
        
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        console.log(`📡 已断开WebSocket: ${this.loopId}`);
    }
    
    /**
     * 发送消息
     */
    send(message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(message));
        } else {
            console.warn('⚠️  WebSocket未连接，无法发送消息');
        }
    }
}


/**
 * WebSocket管理器 - 管理多个回路的WebSocket连接
 */
class WebSocketManager {
    constructor() {
        this.clients = new Map(); // loopId -> LoopWebSocketClient
    }
    
    /**
     * 订阅回路状态更新
     */
    subscribe(loopId, onStateUpdate) {
        // 如果已经存在，先断开
        if (this.clients.has(loopId)) {
            this.unsubscribe(loopId);
        }
        
        // 创建新的WebSocket客户端
        const client = new LoopWebSocketClient(loopId, onStateUpdate);
        client.connect();
        
        this.clients.set(loopId, client);
        
        console.log(`✅ 已订阅回路状态: ${loopId}`);
    }
    
    /**
     * 取消订阅
     */
    unsubscribe(loopId) {
        const client = this.clients.get(loopId);
        if (client) {
            client.disconnect();
            this.clients.delete(loopId);
            console.log(`✅ 已取消订阅: ${loopId}`);
        }
    }
    
    /**
     * 取消所有订阅
     */
    unsubscribeAll() {
        for (const [loopId, client] of this.clients.entries()) {
            client.disconnect();
        }
        this.clients.clear();
        console.log('✅ 已取消所有订阅');
    }
    
    /**
     * 获取连接状态
     */
    isConnected(loopId) {
        const client = this.clients.get(loopId);
        return client && client.ws && client.ws.readyState === WebSocket.OPEN;
    }
}


// 创建全局WebSocket管理器实例
const wsManager = new WebSocketManager();

// 挂载到window对象
if (typeof window !== 'undefined') {
    window.wsManager = wsManager;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { WebSocketManager, LoopWebSocketClient };
}
