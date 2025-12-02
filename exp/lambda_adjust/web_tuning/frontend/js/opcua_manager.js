/**
 * OPC UA 数据源管理器 - 简化版
 */

console.log('🔌 opcua_manager.js 文件已加载');

class OPCUAManager {
    constructor() {
        this.connected = false;
        this.serverUrl = '';
        this.currentNodeId = '';
    }
    
    /**
     * 连接到 OPC UA 服务器
     */
    async connect() {
        const url = document.getElementById('opcuaUrl')?.value;
        const username = document.getElementById('opcuaUsername')?.value || null;
        const password = document.getElementById('opcuaPassword')?.value || null;
        
        if (!url) {
            showAlert('请输入 OPC UA 服务器地址', 'warning');
            return;
        }
        
        try {
            console.log('🔌 正在连接到:', url);
            
            const response = await axios.post(`${API_BASE_URL}/api/opcua/connect`, {
                url: url,
                username: username,
                password: password
            });
            
            if (response.data.success) {
                this.connected = true;
                this.serverUrl = url;
                showAlert('✅ OPC UA 连接成功', 'success');
                this.updateConnectionStatus(true);
                
                // 自动浏览根节点
                await this.browseNodes();
            } else {
                showAlert(`❌ ${response.data.message}`, 'error');
                this.updateConnectionStatus(false);
            }
        } catch (error) {
            console.error('连接失败:', error);
            showAlert(`连接失败: ${error.message}`, 'error');
            this.updateConnectionStatus(false);
        }
    }
    
    /**
     * 断开连接
     */
    async disconnect() {
        try {
            const response = await axios.post(`${API_BASE_URL}/api/opcua/disconnect`);
            
            if (response.data.success) {
                this.connected = false;
                this.serverUrl = '';
                showAlert('已断开 OPC UA 连接', 'info');
                this.updateConnectionStatus(false);
                this.clearNodesList();
            }
        } catch (error) {
            console.error('断开连接失败:', error);
            showAlert(`断开连接失败: ${error.message}`, 'error');
        }
    }
    
    /**
     * 浏览节点
     */
    async browseNodes(nodeId = 'i=85') {
        if (!this.connected) {
            showAlert('请先连接到 OPC UA 服务器', 'warning');
            return;
        }
        
        try {
            console.log('📁 浏览节点:', nodeId);
            
            const response = await axios.get(`${API_BASE_URL}/api/opcua/browse`, {
                params: { node_id: nodeId }
            });
            
            if (response.data.success) {
                this.displayNodes(response.data.nodes);
            } else {
                showAlert(`浏览节点失败: ${response.data.message}`, 'error');
            }
        } catch (error) {
            console.error('浏览节点失败:', error);
            showAlert(`浏览节点失败: ${error.message}`, 'error');
        }
    }
    
    /**
     * 读取节点值
     */
    async readNodeValue(nodeId) {
        if (!this.connected) {
            showAlert('请先连接到 OPC UA 服务器', 'warning');
            return;
        }
        
        try {
            const response = await axios.get(`${API_BASE_URL}/api/opcua/read`, {
                params: { node_id: nodeId }
            });
            
            if (response.data.success) {
                showAlert(`节点值: ${response.data.value}`, 'success');
                return response.data.value;
            } else {
                showAlert(`读取失败: ${response.data.message}`, 'error');
            }
        } catch (error) {
            console.error('读取节点失败:', error);
            showAlert(`读取节点失败: ${error.message}`, 'error');
        }
    }
    
    /**
     * 采集数据并整定
     */
    async collectAndTune() {
        const nodeId = document.getElementById('opcuaNodeId')?.value;
        const duration = parseInt(document.getElementById('opcuaDuration')?.value) || 60;
        const interval = parseInt(document.getElementById('opcuaInterval')?.value) || 1000;
        
        if (!nodeId) {
            showAlert('请输入节点ID', 'warning');
            return;
        }
        
        if (!this.connected) {
            showAlert('请先连接到 OPC UA 服务器', 'warning');
            return;
        }
        
        try {
            // 显示进度条
            this.showCollectionProgress(duration);
            
            const response = await axios.post(`${API_BASE_URL}/api/opcua/collect`, {
                node_id: nodeId,
                duration_seconds: duration,
                interval_ms: interval
            }).catch(error => {
                // 捕获404等错误
                if (error.response && error.response.status === 404) {
                    throw new Error('OPC UA数据采集API未实现。请使用JSON文件上传功能进行整定。');
                }
                throw error;
            });
            
            // 隐藏进度条
            this.hideCollectionProgress();
            
            if (response.data.success) {
                const data = response.data.data;
                showAlert(`✅ 数据采集完成，共 ${data.pv.length} 个数据点`, 'success');
                
                // 将数据传递给整定模块
                window.opcuaCollectedData = data;
                
                // 切换到参数整定页面
                const tuningTab = document.querySelector('[data-tab="tuning"]');
                if (tuningTab) {
                    tuningTab.click();
                }
                
                // 等待页面切换完成后填充数据
                setTimeout(() => {
                    // 触发文件上传事件，模拟上传了数据
                    if (typeof window.handleOPCUAData === 'function') {
                        window.handleOPCUAData(data);
                    } else {
                        // 直接调用 app.js 中的处理函数
                        console.log('📊 OPC UA 数据已准备好:', data);
                        
                        // 创建一个自定义事件
                        const event = new CustomEvent('opcuaDataReady', { 
                            detail: data 
                        });
                        document.dispatchEvent(event);
                    }
                }, 500);
                
                return data;
            } else {
                showAlert(`❌ ${response.data.message}`, 'error');
            }
        } catch (error) {
            console.error('数据采集失败:', error);
            showAlert(`数据采集失败: ${error.message}`, 'error');
        } finally {
            // 无论成功还是失败，都隐藏进度条
            this.hideCollectionProgress();
        }
    }
    
    /**
     * 显示节点列表
     */
    displayNodes(nodes) {
        const container = document.getElementById('opcuaNodesContainer');
        if (!container) return;
        
        if (nodes.length === 0) {
            container.innerHTML = '<p style="color: #94a3b8; text-align: center;">没有找到节点</p>';
            return;
        }
        
        let html = '<div class="nodes-list" style="max-height: 400px; overflow-y: auto;">';
        
        nodes.forEach(node => {
            const icon = node.has_children ? '📁' : '📄';
            const canRead = node.class === 'Variable';
            
            html += `
                <div class="node-item" style="padding: 8px; border-bottom: 1px solid rgba(148, 163, 184, 0.2); display: flex; justify-content: space-between; align-items: center;">
                    <div style="flex: 1;">
                        <span style="margin-right: 8px;">${icon}</span>
                        <span style="color: #e2e8f0;">${node.name}</span>
                        <span style="color: #94a3b8; font-size: 12px; margin-left: 8px;">(${node.class})</span>
                    </div>
                    <div style="display: flex; gap: 4px;">
                        ${node.has_children ? `<button class="btn-small btn-secondary" onclick="opcuaManager.browseNodes('${node.id}')">浏览</button>` : ''}
                        ${canRead ? `<button class="btn-small btn-primary" onclick="opcuaManager.selectNode('${node.id}', '${node.name}')">选择</button>` : ''}
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        container.innerHTML = html;
    }
    
    /**
     * 选择节点
     */
    selectNode(nodeId, nodeName) {
        this.currentNodeId = nodeId;
        
        const nodeIdInput = document.getElementById('opcuaNodeId');
        if (nodeIdInput) {
            nodeIdInput.value = nodeId;
        }
        
        showAlert(`已选择节点: ${nodeName}`, 'success');
    }
    
    /**
     * 更新连接状态显示
     */
    updateConnectionStatus(connected) {
        const statusIndicator = document.getElementById('opcuaStatus');
        const connectBtn = document.getElementById('opcuaConnectBtn');
        const disconnectBtn = document.getElementById('opcuaDisconnectBtn');
        
        if (statusIndicator) {
            if (connected) {
                statusIndicator.innerHTML = '🟢 已连接';
                statusIndicator.style.color = '#10b981';
            } else {
                statusIndicator.innerHTML = '⚪ 未连接';
                statusIndicator.style.color = '#6b7280';
            }
        }
        
        if (connectBtn) connectBtn.disabled = connected;
        if (disconnectBtn) disconnectBtn.disabled = !connected;
    }
    
    /**
     * 清空节点列表
     */
    clearNodesList() {
        const container = document.getElementById('opcuaNodesContainer');
        if (container) {
            container.innerHTML = '<p style="color: #94a3b8; text-align: center;">请先连接到服务器</p>';
        }
    }
    
    /**
     * 显示数据预览
     */
    displayDataPreview(data) {
        console.log('📊 OPC UA 采集的数据:', data);
        // 可以在这里添加数据预览图表
    }
    
    /**
     * 显示采集进度
     */
    showCollectionProgress(totalSeconds) {
        // 创建进度显示元素
        const progressHtml = `
            <div id="opcuaProgressOverlay" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 9999; display: flex; align-items: center; justify-content: center;">
                <div style="background: #1e293b; padding: 32px; border-radius: 16px; border: 2px solid rgba(102, 126, 234, 0.5); min-width: 400px; text-align: center;">
                    <h3 style="color: #e2e8f0; margin: 0 0 24px 0; font-size: 20px;">🔄 正在采集 OPC UA 数据</h3>
                    
                    <div style="margin-bottom: 20px;">
                        <div style="font-size: 48px; font-weight: bold; color: #667eea; font-family: monospace;" id="opcuaProgressTime">00:00</div>
                        <div style="color: #94a3b8; margin-top: 8px;">已采集 <span id="opcuaProgressPercent">0</span>%</div>
                    </div>
                    
                    <div style="background: rgba(15, 23, 42, 0.8); height: 8px; border-radius: 4px; overflow: hidden; margin-bottom: 16px;">
                        <div id="opcuaProgressBar" style="height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); width: 0%; transition: width 0.3s;"></div>
                    </div>
                    
                    <div style="color: #94a3b8; font-size: 14px;">
                        总时长: ${totalSeconds} 秒
                    </div>
                </div>
            </div>
        `;
        
        // 添加到页面
        const overlay = document.createElement('div');
        overlay.innerHTML = progressHtml;
        document.body.appendChild(overlay.firstElementChild);
        
        // 启动计时器
        this.progressStartTime = Date.now();
        this.progressTotalSeconds = totalSeconds;
        this.progressInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - this.progressStartTime) / 1000);
            const percent = Math.min(Math.floor((elapsed / totalSeconds) * 100), 100);
            
            // 更新显示
            const minutes = Math.floor(elapsed / 60);
            const seconds = elapsed % 60;
            const timeStr = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            
            document.getElementById('opcuaProgressTime').textContent = timeStr;
            document.getElementById('opcuaProgressPercent').textContent = percent;
            document.getElementById('opcuaProgressBar').style.width = percent + '%';
            
            // 如果超过总时长，停止计时器
            if (elapsed >= totalSeconds) {
                clearInterval(this.progressInterval);
            }
        }, 100);
    }
    
    /**
     * 隐藏采集进度
     */
    hideCollectionProgress() {
        // 清除计时器
        if (this.progressInterval) {
            clearInterval(this.progressInterval);
            this.progressInterval = null;
        }
        
        // 移除进度显示
        const overlay = document.getElementById('opcuaProgressOverlay');
        if (overlay) {
            overlay.remove();
        }
    }
}

// 全局实例
const opcuaManager = new OPCUAManager();

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    console.log('✅ OPC UA Manager 已初始化');
    opcuaManager.updateConnectionStatus(false);
});
