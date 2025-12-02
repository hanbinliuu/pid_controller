"""
WebSocket处理器
实现实时状态推送
"""
from fastapi import WebSocket, WebSocketDisconnect
import json
from typing import Dict, Set


class WebSocketManager:
    """WebSocket连接管理器"""
    
    def __init__(self):
        # 存储所有活动连接: {loop_id: set(websockets)}
        self.active_connections: Dict[str, Set[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, loop_id: str):
        """接受WebSocket连接"""
        await websocket.accept()
        
        if loop_id not in self.active_connections:
            self.active_connections[loop_id] = set()
        
        self.active_connections[loop_id].add(websocket)
        print(f"📡 WebSocket连接: 回路 {loop_id}, 当前连接数: {len(self.active_connections[loop_id])}")
    
    def disconnect(self, websocket: WebSocket, loop_id: str):
        """断开WebSocket连接"""
        if loop_id in self.active_connections:
            self.active_connections[loop_id].discard(websocket)
            
            # 如果没有连接了，删除该回路的记录
            if not self.active_connections[loop_id]:
                del self.active_connections[loop_id]
            
            print(f"📡 WebSocket断开: 回路 {loop_id}")
    
    async def broadcast_to_loop(self, loop_id: str, message: dict):
        """向指定回路的所有客户端广播消息"""
        if loop_id not in self.active_connections:
            return
        
        dead_connections = set()
        
        for websocket in self.active_connections[loop_id]:
            try:
                await websocket.send_json(message)
            except Exception as e:
                print(f"⚠️  发送WebSocket消息失败: {e}")
                dead_connections.add(websocket)
        
        # 清理断开的连接
        for websocket in dead_connections:
            self.disconnect(websocket, loop_id)
    
    async def broadcast_to_all(self, message: dict):
        """向所有客户端广播消息"""
        for loop_id in list(self.active_connections.keys()):
            await self.broadcast_to_loop(loop_id, message)
    
    def get_connection_count(self, loop_id: str = None) -> int:
        """获取连接数"""
        if loop_id:
            return len(self.active_connections.get(loop_id, set()))
        else:
            return sum(len(conns) for conns in self.active_connections.values())


# 全局WebSocket管理器实例
ws_manager = WebSocketManager()
