"""
OPC UA 客户端 - 简化版
用于从 OPC UA 服务器读取过程数据
"""

from asyncua import Client, ua
import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OPCUAClient:
    """OPC UA 客户端（通用版 - 支持仿真和生产环境）
    
    设计说明：
    - 仿真环境：连接到本地仿真 OPC UA Server（用于开发测试）
    - 生产环境：连接到真实工业 OPC UA Server（如西门子、施耐德等）
    - 同一套代码，通过配置区分环境
    """
    
    def __init__(self, mode: str = 'production'):
        """
        初始化 OPC UA 客户端
        
        Args:
            mode: 运行模式
                - 'simulation': 仿真模式（连接仿真服务器，用于开发测试）
                - 'production': 生产模式（连接真实 OPC UA Server）
        """
        self.client: Optional[Client] = None
        self.connected = False
        self.url = None
        self.mode = mode  # 运行模式
        
        # 持续采集相关
        self.collection_tasks = {}  # {loop_id: task}
        self.collection_data = {}   # {loop_id: {"timestamps": [], "pv": [], "sv": [], "mv": []}}
        self.collection_status = {} # {loop_id: {"is_collecting": bool, "node_id": str, ...}}
        
    async def connect(self, url: str, username: str = None, password: str = None):
        """
        连接到 OPC UA 服务器
        
        Args:
            url: OPC UA 服务器地址，如 'opc.tcp://localhost:4840'
            username: 用户名（可选）
            password: 密码（可选）
        """
        try:
            # 根据模式显示不同的连接信息
            if self.mode == 'simulation':
                logger.info(f"🧪 [仿真模式] 正在连接到仿真 OPC UA 服务器: {url}")
                logger.info(f"   💡 提示: 仅用于开发测试，生产环境请使用 production 模式")
            else:
                logger.info(f"🏭 [生产模式] 正在连接到工业 OPC UA 服务器: {url}")
                logger.info(f"   🔒 提示: 连接到真实工业系统，请确保配置正确")
            
            self.client = Client(url=url)
            self.url = url
            
            # 设置认证
            if username and password:
                self.client.set_user(username)
                self.client.set_password(password)
                logger.info(f"使用用户名: {username}")
            
            # 设置安全策略（简化版使用 None）
            self.client.set_security_string("None")
            
            # 连接
            await self.client.connect()
            self.connected = True
            
            if self.mode == 'simulation':
                logger.info("✅ [仿真模式] OPC UA 连接成功 - 使用仿真数据")
            else:
                logger.info("✅ [生产模式] OPC UA 连接成功 - 连接到真实工业系统")
            
            return {
                "success": True,
                "message": f"成功连接到 {url}",
                "url": url
            }
            
        except Exception as e:
            logger.error(f"❌ 连接失败: {str(e)}")
            self.connected = False
            return {
                "success": False,
                "message": f"连接失败: {str(e)}"
            }
    
    async def disconnect(self):
        """断开连接"""
        try:
            if self.client and self.connected:
                await self.client.disconnect()
                self.connected = False
                logger.info("✅ 已断开 OPC UA 连接")
                return {"success": True, "message": "已断开连接"}
            return {"success": False, "message": "未连接"}
        except Exception as e:
            logger.error(f"❌ 断开连接失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def read_node_value(self, node_id: str):
        """
        读取单个节点的当前值
        
        Args:
            node_id: 节点ID，如 'ns=2;s=MyVariable'
        """
        if not self.connected:
            return {"success": False, "message": "未连接到服务器"}
        
        try:
            node = self.client.get_node(node_id)
            value = await node.read_value()
            
            logger.info(f"📊 读取节点 {node_id}: {value}")
            
            return {
                "success": True,
                "node_id": node_id,
                "value": float(value) if isinstance(value, (int, float)) else value,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ 读取节点失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def write_node_value(self, node_id: str, value):
        """
        写入单个节点的值（自动匹配数据类型）
        
        Args:
            node_id: 节点ID，如 'ns=2;i=1007'
            value: 要写入的值
        """
        if not self.connected:
            logger.warning(f"未连接到服务器，无法写入节点 {node_id}")
            return {"success": False, "message": "未连接到服务器"}
        
        try:
            node = self.client.get_node(node_id)
            
            # 读取节点的数据类型
            data_type = await node.read_data_type()
            data_type_as_variant_type = await node.read_data_type_as_variant_type()
            
            logger.info(f"📝 节点 {node_id} 的数据类型: {data_type_as_variant_type}, 写入值: {value} (类型: {type(value).__name__})")
            
            # 根据数据类型创建正确的Variant
            variant_value = None
            
            # 常见的数据类型映射
            if data_type_as_variant_type == ua.VariantType.Double:
                # 确保转换为浮点数，即使输入是整数0
                variant_value = ua.Variant(float(value), ua.VariantType.Double)
            elif data_type_as_variant_type == ua.VariantType.Float:
                variant_value = ua.Variant(float(value), ua.VariantType.Float)
            elif data_type_as_variant_type == ua.VariantType.Int64:
                variant_value = ua.Variant(int(value), ua.VariantType.Int64)
            elif data_type_as_variant_type == ua.VariantType.Int32:
                variant_value = ua.Variant(int(value), ua.VariantType.Int32)
            elif data_type_as_variant_type == ua.VariantType.Int16:
                variant_value = ua.Variant(int(value), ua.VariantType.Int16)
            elif data_type_as_variant_type == ua.VariantType.UInt64:
                variant_value = ua.Variant(int(value), ua.VariantType.UInt64)
            elif data_type_as_variant_type == ua.VariantType.UInt32:
                variant_value = ua.Variant(int(value), ua.VariantType.UInt32)
            elif data_type_as_variant_type == ua.VariantType.UInt16:
                variant_value = ua.Variant(int(value), ua.VariantType.UInt16)
            elif data_type_as_variant_type == ua.VariantType.Boolean:
                variant_value = ua.Variant(bool(value), ua.VariantType.Boolean)
            elif data_type_as_variant_type == ua.VariantType.String:
                variant_value = ua.Variant(str(value), ua.VariantType.String)
            else:
                # 默认使用Double类型（适用于大多数PID参数）
                logger.warning(f"⚠️ 未知数据类型 {data_type_as_variant_type}，使用Double")
                variant_value = ua.Variant(float(value), ua.VariantType.Double)
            
            # 写入值
            await node.write_value(variant_value)
            
            # 根据模式显示不同的日志
            if self.mode == 'simulation':
                logger.info(f"   🧪 [仿真] 参数已写入仿真服务器")
            else:
                logger.info(f"   🏭 [生产] 参数已写入真实 PLC/DCS")
            
            logger.info(f"✅ 写入节点 {node_id}: {value} (类型: {data_type_as_variant_type})")
            
            return {
                "success": True,
                "node_id": node_id,
                "value": value,
                "data_type": str(data_type_as_variant_type),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"❌ 写入节点失败: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}
    
    async def read_multiple_nodes(self, node_ids: List[str]):
        """
        批量读取多个节点的值
        
        Args:
            node_ids: 节点ID列表
        """
        if not self.connected:
            return {"success": False, "message": "未连接到服务器"}
        
        results = []
        for node_id in node_ids:
            result = await self.read_node_value(node_id)
            results.append(result)
        
        return {
            "success": True,
            "data": results,
            "count": len(results)
        }
    
    async def collect_data(
        self, 
        node_id: str, 
        duration_seconds: int = 60,
        interval_ms: int = 1000
    ):
        """
        采集一段时间的数据
        
        Args:
            node_id: 要采集的节点ID
            duration_seconds: 采集时长（秒）
            interval_ms: 采样间隔（毫秒）
        """
        if not self.connected:
            return {"success": False, "message": "未连接到服务器"}
        
        try:
            logger.info(f"🔄 开始采集数据: {node_id}, 时长: {duration_seconds}秒, 间隔: {interval_ms}ms")
            
            node = self.client.get_node(node_id)
            timestamps = []
            values = []
            
            start_time = datetime.now()
            end_time = start_time + timedelta(seconds=duration_seconds)
            
            while datetime.now() < end_time:
                try:
                    value = await node.read_value()
                    current_time = datetime.now()
                    
                    timestamps.append(current_time.isoformat())
                    values.append(float(value) if isinstance(value, (int, float)) else value)
                    
                    # 等待下一个采样间隔
                    await asyncio.sleep(interval_ms / 1000.0)
                    
                except Exception as e:
                    logger.warning(f"⚠️ 采样失败: {str(e)}")
                    continue
            
            logger.info(f"✅ 数据采集完成，共 {len(values)} 个数据点")
            
            return {
                "success": True,
                "node_id": node_id,
                "data": {
                    "timestamps": timestamps,
                    "values": values,
                    "count": len(values)
                },
                "metadata": {
                    "duration_seconds": duration_seconds,
                    "interval_ms": interval_ms,
                    "start_time": start_time.isoformat(),
                    "end_time": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"❌ 数据采集失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def browse_nodes(self, node_id: str = "i=85", max_depth: int = 1):
        """
        浏览节点树（简化版）
        
        Args:
            node_id: 起始节点ID，默认为 Objects 文件夹
            max_depth: 浏览深度
        """
        if not self.connected:
            return {"success": False, "message": "未连接到服务器"}
        
        try:
            node = self.client.get_node(node_id)
            children = await node.get_children()
            
            nodes = []
            for child in children:
                try:
                    browse_name = await child.read_browse_name()
                    node_class = await child.read_node_class()
                    
                    nodes.append({
                        "id": child.nodeid.to_string(),
                        "name": browse_name.Name,
                        "class": node_class.name,
                        "has_children": len(await child.get_children()) > 0 if max_depth > 0 else False
                    })
                except Exception as e:
                    logger.warning(f"⚠️ 跳过节点: {str(e)}")
                    continue
            
            logger.info(f"📁 浏览节点 {node_id}，找到 {len(nodes)} 个子节点")
            
            return {
                "success": True,
                "parent_id": node_id,
                "nodes": nodes,
                "count": len(nodes)
            }
            
        except Exception as e:
            logger.error(f"❌ 浏览节点失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    def get_status(self):
        """获取连接状态"""
        return {
            "connected": self.connected,
            "url": self.url if self.connected else None
        }
    
    async def start_continuous_collection(
        self, 
        pv_node_id: str,
        sv_node_id: str,
        mv_node_id: str,
        interval_ms: int = 1000,
        loop_id: str = None
    ):
        """
        启动持续采集（无时间限制）
        
        Args:
            pv_node_id: PV节点ID（过程变量）
            sv_node_id: SV节点ID（设定值）
            mv_node_id: MV节点ID（操作变量）
            interval_ms: 采样间隔（毫秒）
            loop_id: 关联的回路ID
        """
        if not self.connected:
            return {"success": False, "message": "未连接到服务器"}
        
        if not loop_id:
            loop_id = pv_node_id  # 如果没有loop_id，使用pv_node_id
        
        # 如果已经在采集，先停止
        if loop_id in self.collection_tasks:
            await self.stop_continuous_collection(loop_id)
        
        try:
            # 🔧 强制清空旧数据，确保每次采集都是全新的数据
            if loop_id in self.collection_data:
                logger.info(f"🧹 清空回路 {loop_id} 的旧采集数据（共{len(self.collection_data[loop_id]['pv'])}个点）")
            
            # 初始化数据存储
            self.collection_data[loop_id] = {
                "timestamps": [],
                "pv": [],
                "sv": [],
                "mv": [],
                "start_time": datetime.now().isoformat()
            }
            
            logger.info(f"✅ 回路 {loop_id} 数据存储已重置")
            
            self.collection_status[loop_id] = {
                "is_collecting": True,
                "pv_node_id": pv_node_id,
                "sv_node_id": sv_node_id,
                "mv_node_id": mv_node_id,
                "interval_ms": interval_ms,
                "start_time": datetime.now().isoformat(),
                "sample_count": 0
            }
            
            # 创建采集任务
            task = asyncio.create_task(
                self._continuous_collection_loop(pv_node_id, sv_node_id, mv_node_id, interval_ms, loop_id)
            )
            self.collection_tasks[loop_id] = task
            
            logger.info(f"🔄 启动持续采集: PV={pv_node_id}, SV={sv_node_id}, MV={mv_node_id} (loop_id: {loop_id})")
            
            return {
                "success": True,
                "message": "采集已启动",
                "loop_id": loop_id,
                "pv_node_id": pv_node_id,
                "sv_node_id": sv_node_id,
                "mv_node_id": mv_node_id
            }
            
        except Exception as e:
            logger.error(f"❌ 启动采集失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def _continuous_collection_loop(self, pv_node_id: str, sv_node_id: str, mv_node_id: str, interval_ms: int, loop_id: str):
        """持续采集循环 - 从三个节点读取数据"""
        try:
            logger.info(f"🔍 尝试获取节点: PV={pv_node_id}, SV={sv_node_id}, MV={mv_node_id}")
            pv_node = self.client.get_node(pv_node_id)
            sv_node = self.client.get_node(sv_node_id)
            mv_node = self.client.get_node(mv_node_id)
            logger.info(f"✅ 节点获取成功，开始采集...")
            
            while loop_id in self.collection_status and self.collection_status[loop_id]["is_collecting"]:
                try:
                    # 读取三个节点的值
                    pv_value = await pv_node.read_value()
                    sv_value = await sv_node.read_value()
                    mv_value = await mv_node.read_value()
                    current_time = datetime.now()
                    
                    # 存储数据
                    data = self.collection_data[loop_id]
                    data["timestamps"].append(current_time.isoformat())
                    data["pv"].append(float(pv_value) if isinstance(pv_value, (int, float)) else pv_value)
                    data["sv"].append(float(sv_value) if isinstance(sv_value, (int, float)) else sv_value)
                    data["mv"].append(float(mv_value) if isinstance(mv_value, (int, float)) else mv_value)
                    
                    # 限制数据量，只保留最近1000个点
                    if len(data["pv"]) > 1000:
                        data["timestamps"] = data["timestamps"][-1000:]
                        data["pv"] = data["pv"][-1000:]
                        data["sv"] = data["sv"][-1000:]
                        data["mv"] = data["mv"][-1000:]
                    
                    # 更新状态
                    self.collection_status[loop_id]["sample_count"] = len(data["pv"])
                    self.collection_status[loop_id]["last_pv"] = data["pv"][-1]
                    self.collection_status[loop_id]["last_sv"] = data["sv"][-1]
                    self.collection_status[loop_id]["last_mv"] = data["mv"][-1]
                    self.collection_status[loop_id]["last_update"] = current_time.isoformat()
                    
                    # 🚀 实时推送数据到WebSocket
                    await self._push_realtime_data(loop_id, {
                        "timestamp": current_time.isoformat(),
                        "pv": float(pv_value) if isinstance(pv_value, (int, float)) else pv_value,
                        "sv": float(sv_value) if isinstance(sv_value, (int, float)) else sv_value,
                        "mv": float(mv_value) if isinstance(mv_value, (int, float)) else mv_value,
                        "sample_count": len(data["pv"])
                    })
                    
                    # 等待下一个采样间隔
                    await asyncio.sleep(interval_ms / 1000.0)
                    
                except Exception as e:
                    logger.error(f"❌ 采样失败: {str(e)}")
                    logger.error(f"   PV节点: {pv_node_id}")
                    logger.error(f"   SV节点: {sv_node_id}")
                    logger.error(f"   MV节点: {mv_node_id}")
                    import traceback
                    logger.error(traceback.format_exc())
                    await asyncio.sleep(interval_ms / 1000.0)
                    continue
                    
        except Exception as e:
            logger.error(f"❌ 采集循环异常: {str(e)}")
            if loop_id in self.collection_status:
                self.collection_status[loop_id]["is_collecting"] = False
    
    async def stop_continuous_collection(self, loop_id: str = None):
        """
        停止持续采集
        
        Args:
            loop_id: 回路ID，如果为None则停止所有采集
        """
        try:
            if loop_id:
                # 停止指定回路的采集
                if loop_id in self.collection_tasks:
                    task = self.collection_tasks[loop_id]
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    del self.collection_tasks[loop_id]
                
                if loop_id in self.collection_status:
                    self.collection_status[loop_id]["is_collecting"] = False
                
                logger.info(f"⏹️ 停止采集: {loop_id}")
                
                return {
                    "success": True,
                    "message": f"已停止采集: {loop_id}"
                }
            else:
                # 停止所有采集
                for lid in list(self.collection_tasks.keys()):
                    await self.stop_continuous_collection(lid)
                
                return {
                    "success": True,
                    "message": "已停止所有采集"
                }
                
        except Exception as e:
            logger.error(f"❌ 停止采集失败: {str(e)}")
            return {"success": False, "message": str(e)}
    
    async def get_collection_status(self, loop_id: str = None):
        """获取采集状态"""
        if loop_id:
            status = self.collection_status.get(loop_id, {
                "is_collecting": False,
                "message": "未找到采集任务"
            })
            return {
                "success": True,
                "loop_id": loop_id,
                "status": status
            }
        else:
            return {
                "success": True,
                "all_status": self.collection_status
            }
    
    async def get_collected_data(self, loop_id: str = None, limit: int = 100):
        """
        获取已采集的数据
        
        Args:
            loop_id: 回路ID
            limit: 返回最近的N个数据点
        """
        if not loop_id or loop_id not in self.collection_data:
            return {
                "success": False,
                "message": "未找到数据"
            }
        
        data = self.collection_data[loop_id]
        
        # 返回最近的limit个数据点
        return {
            "success": True,
            "loop_id": loop_id,
            "data": {
                "timestamps": data["timestamps"][-limit:],
                "pv": data["pv"][-limit:],
                "sv": data["sv"][-limit:],
                "mv": data["mv"][-limit:],
                "count": min(len(data["pv"]), limit),
                "total_count": len(data["pv"])
            },
            "status": self.collection_status.get(loop_id, {})
        }
    
    async def clear_collected_data(self, loop_id: str, reset_server_counter: bool = True):
        """
        清空指定回路的已采集数据
        用于在进入DISTURBANCE状态时重置数据，从0开始累积新的扰动数据
        
        Args:
            loop_id: 回路ID
            reset_server_counter: 是否重置OPC UA Server端的扰动数据计数器
        """
        if loop_id in self.collection_data:
            self.collection_data[loop_id] = {
                "timestamps": [],
                "pv": [],
                "sv": [],
                "mv": []
            }
            
            # 🆕 重置采集状态中的sample_count，确保计数从0开始
            if loop_id in self.collection_status:
                self.collection_status[loop_id]["sample_count"] = 0
                logger.info(f"🔄 已重置回路 {loop_id} 的采样计数器")
            
            logger.info(f"🗑️  已清空回路 {loop_id} 的采集数据")
            
            # 重置OPC UA Server端的扰动数据计数器
            if reset_server_counter and self.connected:
                try:
                    # 从 loops_storage 获取回路配置
                    from loops_storage import storage as loops_storage
                    loop = loops_storage.get_loop(loop_id)
                    if loop:
                        opcua_config = loop.get('opcua_config', {})
                        # 查找扰动计数器节点ID（如果配置了）
                        disturb_counter_node = opcua_config.get('disturb_counter_node_id')
                        if disturb_counter_node:
                            # 将计数器重置为0
                            result = await self.write_node_value(disturb_counter_node, 0)
                            if result and result.get('success'):
                                logger.info(f"✅ 已重置OPC UA Server端的扰动计数器")
                            else:
                                logger.warning(f"⚠️  重置扰动计数器失败")
                        else:
                            logger.debug(f"ℹ️  回路 {loop_id} 未配置扰动计数器节点")
                except Exception as e:
                    logger.warning(f"⚠️  重置扰动计数器失败: {e}")
            
            return {"success": True, "message": "数据已清空"}
        else:
            return {"success": False, "message": "回路不存在"}
    
    async def _push_realtime_data(self, loop_id: str, data_point: dict):
        """
        推送实时数据到WebSocket
        
        Args:
            loop_id: 回路ID
            data_point: 数据点 {'timestamp', 'pv', 'sv', 'mv', 'sample_count'}
        """
        try:
            # 导入ws_manager（延迟导入避免循环依赖）
            try:
                from websocket_handler import ws_manager
            except ImportError:
                return  # WebSocket功能不可用
            
            # 构建消息
            message = {
                "type": "realtime_data",
                "loop_id": loop_id,
                "data": data_point
            }
            
            # 广播到该回路的所有WebSocket连接
            await ws_manager.broadcast_to_loop(loop_id, message)
            
        except Exception as e:
            # 静默失败，不影响数据采集
            logger.debug(f"推送实时数据失败: {e}")


# 全局 OPC UA 客户端实例
opcua_client = OPCUAClient()
