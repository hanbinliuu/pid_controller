/**
 * 多回路管理 - 前端JS
 */

console.log('🎛️ loops_manager.js 文件已加载');

// 确保API_BASE_URL已定义（在app.js中定义）
if (!window.API_BASE_URL) {
    window.API_BASE_URL = 'http://localhost:8000';
}

// 显示提示消息
function showAlert(message, type = 'info') {
    const colors = {
        'success': '#10b981',
        'error': '#ef4444',
        'warning': '#f59e0b',
        'info': '#3b82f6'
    };
    
    const color = colors[type] || colors.info;
    
    // 使用浏览器原生alert或者自定义通知
    if (window.showNotification) {
        window.showNotification(message, type);
    } else {
        alert(message);
    }
}

// 分组过滤函数
function filterByGroup(group) {
    filterOptions.group = group;
    
    // 更新按钮状态
    document.querySelectorAll('.group-filter-btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.dataset.group === group) {
            btn.classList.add('active');
        }
    });
    
    // 重新渲染回路列表
    renderLoopCards();
}

// 全局变量
let allLoops = [];
let currentLoop = null;
let selectedLoops = new Set(); // 选中的回路ID集合
let filterOptions = {
    area: 'all',
    status: 'all',
    searchText: '',
    sortBy: 'name',
    sortOrder: 'asc',
    tags: [], // 标签筛选
    group: 'all' // 分组筛选
};

// 回路模板库
const loopTemplates = {
    temperature: {
        name: '温度控制模板',
        description: '适用于温度控制回路',
        pid_params: { pb: 100, ti: 60, td: 15 },
        control_mode: 'STANDARD',
        alarm_thresholds: { high: 5, low: -5 }
    },
    flow: {
        name: '流量控制模板',
        description: '适用于流量控制回路',
        pid_params: { pb: 50, ti: 30, td: 5 },
        control_mode: 'FLOW_CONTROL',
        alarm_thresholds: { high: 10, low: -10 }
    },
    pressure: {
        name: '压力控制模板',
        description: '适用于压力控制回路',
        pid_params: { pb: 80, ti: 45, td: 10 },
        control_mode: 'ANTI_DISTURBANCE',
        alarm_thresholds: { high: 3, low: -3 }
    },
    level: {
        name: '液位控制模板',
        description: '适用于液位控制回路',
        pid_params: { pb: 120, ti: 90, td: 20 },
        control_mode: 'STANDARD',
        alarm_thresholds: { high: 8, low: -8 }
    }
};

// 标签颜色映射
const tagColors = {
    'critical': '#ef4444',
    'important': '#f59e0b',
    'normal': '#3b82f6',
    'test': '#8b5cf6',
    'production': '#10b981',
    'maintenance': '#6b7280'
};

// 初始化
async function initLoopsManager() {
    console.log('🎛️ 初始化回路管理器...');
    await loadLoops();
    setupEventListeners();
}

// 加载所有回路
async function loadLoops() {
    try {
        const response = await axios.get(`${window.API_BASE_URL}/api/loops`);
        if (response.data.success) {
            allLoops = response.data.loops;
            updateAreaFilterOptions(); // 更新区域筛选选项
            displayLoops(allLoops);
            updateStatistics();
        }
    } catch (error) {
        console.error('加载回路失败:', error);
        showAlert('加载回路失败: ' + error.message, 'error');
    }
}

// 显示回路列表
function displayLoops(loops) {
    console.log('🔄 displayLoops 被调用，回路数量:', loops.length);
    console.log('📦 selectedLoops 状态:', selectedLoops);
    const container = document.getElementById('loopsListContainer');
    if (!container) {
        console.error('❌ 找不到 loopsListContainer');
        return;
    }
    
    // 应用分组过滤
    let filteredLoops = loops;
    if (filterOptions.group && filterOptions.group !== 'all') {
        filteredLoops = loops.filter(loop => loop.group === filterOptions.group);
        console.log(`🔍 分组过滤: ${filterOptions.group}, 结果: ${filteredLoops.length}个回路`);
    }
    
    if (filteredLoops.length === 0) {
        container.innerHTML = `
            <div style="text-align: center; padding: 40px; color: #94a3b8;">
                <p style="font-size: 18px; margin-bottom: 10px;">📭 ${filterOptions.group !== 'all' ? '该分组下没有回路' : '还没有控制回路'}</p>
                <p style="font-size: 14px;">${filterOptions.group !== 'all' ? '请选择其他分组或新建回路' : '点击"新建回路"开始添加'}</p>
            </div>
        `;
        return;
    }
    
    // 按区域分组
    const loopsByArea = {};
    filteredLoops.forEach(loop => {
        const area = loop.area || '未分类';
        if (!loopsByArea[area]) {
            loopsByArea[area] = [];
        }
        loopsByArea[area].push(loop);
    });
    
    // 生成HTML
    let html = '';
    Object.keys(loopsByArea).forEach(area => {
        html += `
            <div class="area-group" style="margin-bottom: 24px;">
                <h3 style="color: #e2e8f0; font-size: 16px; margin-bottom: 12px; padding-left: 8px; border-left: 3px solid #667eea;">
                    📍 ${area}
                </h3>
                <div class="loops-grid">
        `;
        
        loopsByArea[area].forEach(loop => {
            const statusColor = loop.status === 'active' ? '#10b981' : '#6b7280';
            const statusIcon = loop.status === 'active' ? '🟢' : '⚪';
            const score = loop.performance?.score || 0;
            const grade = loop.performance?.grade || 'N/A';
            const isSelected = selectedLoops.has(loop.id);
            
            // 数据源类型标识
            const dataSourceIcon = loop.data_source === 'opcua' ? '🔌' : '📄';
            const dataSourceLabel = loop.data_source === 'opcua' ? 'OPC UA' : 'JSON';
            const dataSourceColor = loop.data_source === 'opcua' ? '#3b82f6' : '#6b7280';
            
            // OPC UA采集状态
            const isCollecting = loop.opcua_config?.is_collecting || false;
            // 🔧 移除采集状态标签，不再显示
            const collectingBadge = '';
            
            // 稳定性状态显示（三种状态：稳态、非稳态、正在整定）
            const stabilityStatus = loop.stability_status || {};
            const isUnsteady = stabilityStatus.is_unsteady || false;
            const isRetuning = stabilityStatus.is_retuning || false;
            
            // 调试日志（仅在状态异常时打印）
            if (isRetuning || isUnsteady) {
                console.log(`[${loop.name}] 状态:`, isRetuning ? '正在整定' : '非稳态');
            }
            
            let stabilityBadge = '';
            if (isRetuning) {
                // 正在整定（优先级最高）
                stabilityBadge = `<span style="font-size: 11px; padding: 2px 8px; background: #3b82f6; border-radius: 4px; color: white; animation: pulse 2s infinite;">
                    🔄 正在整定
                </span>`;
            } else if (isUnsteady) {
                // 非稳态
                stabilityBadge = `<span class="unsteady-alert" style="font-size: 11px; padding: 2px 8px; background: #ef4444; border-radius: 4px; color: white; animation: pulse 2s infinite;">
                    🚨 非稳态
                </span>`;
            } else if (loop.data_source === 'opcua' && isCollecting) {
                // 稳态（只在OPC UA采集中时显示）
                stabilityBadge = `<span style="font-size: 11px; padding: 2px 8px; background: #10b981; border-radius: 4px; color: white;">
                    ✓ 稳态
                </span>`;
            }
            
            // 🔧 移除状态指示灯
            
            html += `
                <div class="loop-card ${isSelected ? 'selected' : ''}" data-loop-id="${loop.id}" style="position: relative;">
                    
                    <div class="loop-header">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <input type="checkbox" 
                                   class="loop-checkbox" 
                                   data-loop-id="${loop.id}"
                                   ${isSelected ? 'checked' : ''}
                                   onclick="toggleLoopSelection('${loop.id}', event)">
                            <h4 style="color: #e2e8f0; font-size: 15px; margin: 0;">${statusIcon} ${loop.name}</h4>
                            <span style="font-size: 11px; padding: 2px 6px; background: ${dataSourceColor}; border-radius: 4px; color: white;">
                                ${dataSourceIcon} ${dataSourceLabel}
                            </span>
                            ${collectingBadge}
                            ${stabilityBadge}
                        </div>
                        <span class="status-badge" style="background: ${statusColor}20; color: ${statusColor}; padding: 2px 8px; border-radius: 12px; font-size: 12px;">
                            ${loop.status}
                        </span>
                    </div>
                    
                    <p style="color: #94a3b8; font-size: 13px; margin: 8px 0;">${loop.description || '无描述'}</p>
                    
                    <div class="loop-params" style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 12px 0;">
                        <div style="background: rgba(102, 126, 234, 0.1); padding: 6px; border-radius: 6px; text-align: center;">
                            <div style="font-size: 11px; color: #94a3b8;">Pb</div>
                            <div style="font-size: 14px; color: #e2e8f0; font-weight: 600;">${loop.pid_params?.pb?.toFixed(1) || '-'}%</div>
                        </div>
                        <div style="background: rgba(102, 126, 234, 0.1); padding: 6px; border-radius: 6px; text-align: center;">
                            <div style="font-size: 11px; color: #94a3b8;">Ti</div>
                            <div style="font-size: 14px; color: #e2e8f0; font-weight: 600;">${loop.pid_params?.ti?.toFixed(1) || '-'}s</div>
                        </div>
                        <div style="background: rgba(102, 126, 234, 0.1); padding: 6px; border-radius: 6px; text-align: center;">
                            <div style="font-size: 11px; color: #94a3b8;">Td</div>
                            <div style="font-size: 14px; color: #e2e8f0; font-weight: 600;">${loop.pid_params?.td?.toFixed(1) || '-'}s</div>
                        </div>
                    </div>
                    
                    <div class="loop-performance" style="display: flex; justify-content: space-between; align-items: center; margin: 12px 0; padding: 8px; background: rgba(0,0,0,0.2); border-radius: 6px;">
                        <div>
                            <span style="color: #94a3b8; font-size: 12px;">评分</span>
                            <span style="color: #e2e8f0; font-size: 16px; font-weight: 600; margin-left: 8px;">${score.toFixed(0)}</span>
                            <span style="color: #94a3b8; font-size: 12px; margin-left: 4px;">(${grade})</span>
                        </div>
                        <div>
                            <span style="color: #94a3b8; font-size: 12px;">误差</span>
                            <span style="color: #e2e8f0; font-size: 14px; margin-left: 8px;">${loop.performance?.steady_error?.toFixed(3) || '-'}</span>
                        </div>
                    </div>
                    
                    <!-- 标签显示 -->
                    ${loop.tags && loop.tags.length > 0 ? `
                        <div style="display: flex; gap: 4px; margin: 8px 0; flex-wrap: wrap;">
                            ${loop.tags.map(tag => {
                                const color = tagColors[tag] || '#6b7280';
                                return `<span style="font-size: 10px; padding: 2px 6px; background: ${color}; border-radius: 3px; color: white;" onclick="removeTagFromLoop('${loop.id}', '${tag}')" title="点击移除标签">${tag} ×</span>`;
                            }).join('')}
                        </div>
                    ` : ''}
                    
                    <div class="loop-actions" style="display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap;">
                        <button class="btn-small btn-primary" onclick="viewLoopDetails('${loop.id}')">查看</button>
                        <button class="btn-small btn-secondary" onclick="tuneLoop('${loop.id}')">整定</button>
                        <button class="btn-small" style="background: #667eea; color: white;" onclick="viewRetuningHistory('${loop.id}')">📊 整定记录</button>
                        ${loop.data_source === 'opcua' ? 
                            (isCollecting ? 
                                `<button class="btn-small btn-warning" onclick="stopOPCUACollection('${loop.id}')">⏸️ 停止采集</button>` :
                                `<button class="btn-small btn-success" onclick="startOPCUACollection('${loop.id}')">▶️ 开始采集</button>`
                            ) : ''
                        }
                    </div>
                    
                    <!-- 自动整定开关（仅OPC UA回路显示） -->
                    ${loop.data_source === 'opcua' ? `
                        <div style="margin-top: 12px; padding: 10px; background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div style="flex: 1;">
                                    <div style="color: #10b981; font-size: 12px; font-weight: 600; margin-bottom: 2px;">🔧 自动整定</div>
                                    <div style="color: #94a3b8; font-size: 10px;">检测扰动时自动触发</div>
                                </div>
                                <label class="switch-small">
                                    <input type="checkbox" 
                                           id="autoTuningSwitch_${loop.id}"
                                           ${loop.opcua_config?.auto_tuning_enabled ? 'checked' : ''}
                                           onchange="toggleAutoTuning('${loop.id}', this.checked)">
                                    <span class="slider-small"></span>
                                </label>
                            </div>
                        </div>
                    ` : ''}
                    
                    <!-- 快捷操作菜单 -->
                    <div style="display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap;">
                        <button class="btn-small" style="font-size: 11px; padding: 4px 8px; background: rgba(102, 126, 234, 0.2); color: #a5b4fc;" onclick="cloneLoop('${loop.id}')" title="克隆回路">📋</button>
                        <button class="btn-small" style="font-size: 11px; padding: 4px 8px; background: rgba(102, 126, 234, 0.2); color: #a5b4fc;" onclick="addTagToLoop('${loop.id}')" title="添加标签">🏷️</button>
                        <button class="btn-small" style="font-size: 11px; padding: 4px 8px; background: rgba(102, 126, 234, 0.2); color: #a5b4fc;" onclick="configureAlarmThresholds('${loop.id}')" title="告警配置">⚠️</button>
                        <button class="btn-small" style="font-size: 11px; padding: 4px 8px; background: rgba(102, 126, 234, 0.2); color: #a5b4fc;" onclick="showPerformanceTrend('${loop.id}')" title="性能趋势">📈</button>
                        <button class="btn-small btn-danger" style="font-size: 11px; padding: 4px 8px;" onclick="deleteLoop('${loop.id}')" title="删除回路">🗑️</button>
                    </div>
                </div>
            `;
        });
        
        html += `
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    console.log('✅ displayLoops 完成，HTML已更新');
    console.log('🔍 复选框数量:', document.querySelectorAll('.loop-checkbox').length);
}

// 更新统计信息
async function updateStatistics() {
    try {
        const response = await axios.get(`${window.API_BASE_URL}/api/loops/statistics/summary`);
        if (response.data.success) {
            const stats = response.data.statistics;
            const statsContainer = document.getElementById('loopsStatistics');
            if (statsContainer) {
                statsContainer.innerHTML = `
                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 16px;">
                        <div class="stat-card">
                            <div class="stat-label">总回路数</div>
                            <div class="stat-value">${stats.total_loops}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">运行中</div>
                            <div class="stat-value">${stats.active_loops}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">平均评分</div>
                            <div class="stat-value">${stats.average_score.toFixed(1)}</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-label">区域数</div>
                            <div class="stat-value">${stats.areas.length}</div>
                        </div>
                    </div>
                `;
            }
        }
    } catch (error) {
        console.error('更新统计信息失败:', error);
    }
}

// 新建回路
window.createNewLoop = async function createNewLoop() {
    // 显示创建回路对话框
    showCreateLoopDialog();
}

// 显示创建回路对话框
function showCreateLoopDialog() {
    const dialogHtml = `
        <div id="createLoopDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center;">
            <div style="background: #1e293b; padding: 30px; border-radius: 12px; max-width: 500px; width: 90%; border: 1px solid rgba(102, 126, 234, 0.3);">
                <h3 style="color: #e2e8f0; margin-bottom: 20px;">➕ 新建回路</h3>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">回路名称 *</label>
                    <input type="text" id="newLoopName" class="input-field" placeholder="例如：温度控制回路1" style="width: 100%;">
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">回路描述</label>
                    <input type="text" id="newLoopDesc" class="input-field" placeholder="可选" style="width: 100%;">
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">所属区域</label>
                    <input type="text" id="newLoopArea" class="input-field" placeholder="默认区域" value="默认区域" style="width: 100%;">
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">数据源类型 *</label>
                    <select id="newLoopDataSource" class="input-field" style="width: 100%;" onchange="toggleOPCUAConfig()">
                        <option value="file">JSON文件</option>
                        <option value="opcua">OPC UA实时数据</option>
                    </select>
                    <div id="jsonDataStatus" style="margin-top: 8px; padding: 8px; border-radius: 6px; font-size: 12px;">
                        ${window.uploadedData && window.uploadedData.length > 0 ? 
                            `<span style="color: #10b981;">✅ 已检测到JSON数据 (${window.uploadedData.length}个数据点)</span>` :
                            `<span style="color: #f59e0b;">⚠️ 未检测到JSON数据，请先在参数整定页面上传JSON文件</span>`
                        }
                    </div>
                </div>
                
                <div id="opcuaConfigSection" style="display: none; margin-bottom: 15px; padding: 15px; background: rgba(102, 126, 234, 0.1); border-radius: 8px; border: 1px solid rgba(102, 126, 234, 0.3);">
                    <h4 style="color: #667eea; margin-bottom: 10px; font-size: 14px;">🔌 OPC UA配置</h4>
                    <div style="margin-bottom: 10px;">
                        <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">PV节点ID (过程变量) *</label>
                        <input type="text" id="newLoopPVNodeId" class="input-field" placeholder="例如：ns=2;s=Temperature" style="width: 100%;">
                    </div>
                    <div style="margin-bottom: 10px;">
                        <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">SV节点ID (设定值) *</label>
                        <input type="text" id="newLoopSVNodeId" class="input-field" placeholder="例如：ns=2;s=Setpoint" style="width: 100%;">
                    </div>
                    <div style="margin-bottom: 10px;">
                        <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">MV节点ID (操作变量) *</label>
                        <input type="text" id="newLoopMVNodeId" class="input-field" placeholder="例如：ns=2;s=ManipulatedVariable" style="width: 100%;">
                    </div>
                    
                    <!-- PID参数节点（可选，用于自动下发参数） -->
                    <div style="margin-bottom: 10px; padding: 10px; background: rgba(59, 130, 246, 0.1); border-radius: 6px; border: 1px solid rgba(59, 130, 246, 0.3);">
                        <div style="color: #93c5fd; font-size: 12px; margin-bottom: 8px;">
                            📡 PID参数节点（可选）- 用于自动下发整定参数
                        </div>
                        <div style="margin-bottom: 8px;">
                            <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">Pb节点ID (比例带)</label>
                            <input type="text" id="newLoopPIDPbNodeId" class="input-field" placeholder="例如：ns=2;i=1007" style="width: 100%;">
                        </div>
                        <div style="margin-bottom: 8px;">
                            <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">Ti节点ID (积分时间)</label>
                            <input type="text" id="newLoopPIDTiNodeId" class="input-field" placeholder="例如：ns=2;i=1008" style="width: 100%;">
                        </div>
                        <div>
                            <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">Td节点ID (微分时间)</label>
                            <input type="text" id="newLoopPIDTdNodeId" class="input-field" placeholder="例如：ns=2;i=1009" style="width: 100%;">
                        </div>
                        <div style="color: #94a3b8; font-size: 11px; margin-top: 8px;">
                            💡 提示：填写后可自动下发整定参数到OPC UA服务器
                        </div>
                    </div>
                    
                    <div>
                        <label style="color: #e2e8f0; display: block; margin-bottom: 5px; font-size: 13px;">采样间隔 (毫秒)</label>
                        <input type="number" id="newLoopSamplingInterval" class="input-field" value="1000" min="100" step="100" style="width: 100%;">
                    </div>
                </div>
                
                <div style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button class="btn btn-secondary" onclick="closeCreateLoopDialog()">取消</button>
                    <button class="btn btn-primary" onclick="submitCreateLoop()">创建</button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', dialogHtml);
}

// 切换OPC UA配置显示
window.toggleOPCUAConfig = function() {
    const dataSource = document.getElementById('newLoopDataSource').value;
    const opcuaSection = document.getElementById('opcuaConfigSection');
    opcuaSection.style.display = dataSource === 'opcua' ? 'block' : 'none';
}

// 关闭创建回路对话框
window.closeCreateLoopDialog = function() {
    const dialog = document.getElementById('createLoopDialog');
    if (dialog) {
        dialog.remove();
    }
}

// 提交创建回路
window.submitCreateLoop = async function() {
    const name = document.getElementById('newLoopName').value.trim();
    const description = document.getElementById('newLoopDesc').value.trim();
    const area = document.getElementById('newLoopArea').value.trim() || '默认区域';
    const dataSource = document.getElementById('newLoopDataSource').value;
    
    if (!name) {
        showAlert('请输入回路名称', 'warning');
        return;
    }
    
    const loopData = {
        name: name,
        description: description,
        area: area,
        data_source: dataSource
    };
    
    // 如果是JSON文件数据源，添加原始数据
    if (dataSource === 'file' && window.uploadedData && window.uploadedData.length > 0) {
        loopData.original_data = window.uploadedData;
        console.log('📊 保存原始JSON数据到回路，数据点数:', window.uploadedData.length);
    }
    
    // 如果是OPC UA数据源，添加配置
    if (dataSource === 'opcua') {
        const pvNodeId = document.getElementById('newLoopPVNodeId').value.trim();
        const svNodeId = document.getElementById('newLoopSVNodeId').value.trim();
        const mvNodeId = document.getElementById('newLoopMVNodeId').value.trim();
        const samplingInterval = parseInt(document.getElementById('newLoopSamplingInterval').value);
        
        // 获取PID参数节点（可选）
        const pidPbNodeId = document.getElementById('newLoopPIDPbNodeId').value.trim();
        const pidTiNodeId = document.getElementById('newLoopPIDTiNodeId').value.trim();
        const pidTdNodeId = document.getElementById('newLoopPIDTdNodeId').value.trim();
        
        if (!pvNodeId || !svNodeId || !mvNodeId) {
            showAlert('请输入所有OPC UA节点ID（PV、SV、MV）', 'warning');
            return;
        }
        
        loopData.opcua_config = {
            pv_node_id: pvNodeId,
            sv_node_id: svNodeId,
            mv_node_id: mvNodeId,
            sampling_interval: samplingInterval,
            is_collecting: false
        };
        
        // 如果填写了PID参数节点，添加到配置中
        if (pidPbNodeId && pidTiNodeId && pidTdNodeId) {
            loopData.opcua_config.pid_pb_node_id = pidPbNodeId;
            loopData.opcua_config.pid_ti_node_id = pidTiNodeId;
            loopData.opcua_config.pid_td_node_id = pidTdNodeId;
            console.log('✅ 已配置PID参数节点，支持自动下发参数');
        } else if (pidPbNodeId || pidTiNodeId || pidTdNodeId) {
            showAlert('PID参数节点必须全部填写或全部留空', 'warning');
            return;
        } else {
            console.log('ℹ️  未配置PID参数节点，将无法自动下发参数');
        }
        
        console.log('🔌 OPC UA配置:', loopData.opcua_config);
    }
    
    try {
        const response = await axios.post(`${window.API_BASE_URL}/api/loops`, loopData);
        
        if (response.data.success) {
            showAlert(response.data.message, 'success');
            closeCreateLoopDialog();
            await loadLoops();
        }
    } catch (error) {
        console.error('创建回路失败:', error);
        showAlert('创建回路失败: ' + error.message, 'error');
    }
}

// 查看回路详情
window.viewLoopDetails = async function viewLoopDetails(loopId) {
    console.log('👁️ 查看回路详情:', loopId);
    try {
        const response = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}`);
        if (response.data.success) {
            currentLoop = response.data.loop;
            console.log('✅ 获取回路详情成功:', currentLoop);
            showLoopDetailsModal(currentLoop);
        }
    } catch (error) {
        console.error('获取回路详情失败:', error);
        showAlert('获取回路详情失败: ' + error.message, 'error');
    }
}

// 显示回路详情模态框
function showLoopDetailsModal(loop) {
    console.log('📋 显示回路详情模态框:', loop);
    const modal = document.getElementById('loopDetailsModal');
    console.log('🔍 模态框元素:', modal);
    if (!modal) {
        console.error('❌ 找不到模态框元素');
        return;
    }
    
    document.getElementById('loopDetailsContent').innerHTML = `
        <h3 style="color: #e2e8f0; margin-bottom: 16px;">${loop.name}</h3>
        
        <div style="margin-bottom: 16px;">
            <div style="color: #94a3b8; font-size: 13px; margin-bottom: 4px;">描述</div>
            <div style="color: #e2e8f0;">${loop.description || '无'}</div>
        </div>
        
        <div style="margin-bottom: 16px;">
            <div style="color: #94a3b8; font-size: 13px; margin-bottom: 4px;">区域</div>
            <div style="color: #e2e8f0;">${loop.area}</div>
        </div>
        
        <div style="margin-bottom: 16px;">
            <div style="color: #94a3b8; font-size: 13px; margin-bottom: 8px;">PID参数</div>
            <div style="background: rgba(102, 126, 234, 0.1); padding: 12px; border-radius: 8px;">
                <div>Pb: ${loop.pid_params?.pb?.toFixed(2)}%</div>
                <div>Ti: ${loop.pid_params?.ti?.toFixed(2)}s</div>
                <div>Td: ${loop.pid_params?.td?.toFixed(2)}s</div>
            </div>
        </div>
        
        <div style="margin-bottom: 16px;">
            <div style="color: #94a3b8; font-size: 13px; margin-bottom: 8px;">性能指标</div>
            <div style="background: rgba(102, 126, 234, 0.1); padding: 12px; border-radius: 8px;">
                <div>评分: ${loop.performance?.score || 0} (${loop.performance?.grade || 'N/A'})</div>
                <div>稳态误差: ${loop.performance?.steady_error?.toFixed(4) || 'N/A'}</div>
            </div>
        </div>
        
        <div style="display: flex; gap: 8px; margin-top: 16px;">
            <button class="btn btn-primary" onclick="window.tuneLoop('${loop.id}'); console.log('按钮点击: ${loop.id}');">开始整定</button>
            <button class="btn btn-secondary" onclick="window.closeLoopDetailsModal()">关闭</button>
        </div>
    `;
    
    modal.style.display = 'flex';
    console.log('✅ 模态框已显示，回路ID:', loop.id);
}

// 关闭详情模态框
window.closeLoopDetailsModal = function closeLoopDetailsModal() {
    const modal = document.getElementById('loopDetailsModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 数据质量检查
async function checkDataQuality(loopId) {
    try {
        const dataResponse = await axios.get(`${window.API_BASE_URL}/api/opcua/collected_data?loop_id=${loopId}&limit=2000`);
        
        if (!dataResponse.data.success || !dataResponse.data.data) {
            return { isReady: false, reason: '无法获取采集数据', dataCount: 0 };
        }
        
        const data = dataResponse.data.data;
        const count = data.count || data.pv?.length || 0;
        
        // 检查1：最小数据点数量（降低要求，支持非稳态快速整定）
        if (count < 100) {
            return { 
                isReady: false, 
                reason: `数据点不足（当前${count}个，至少需要100个）`,
                dataCount: count,
                suggestion: '继续采集数据...'
            };
        }
        
        // 检查2：检测设定值变化或扰动
        const sv = data.sv || [];
        const pv = data.pv || [];
        const svChanges = detectSetpointChanges(sv);
        
        // 计算数据变化范围
        const pvRange = Math.max(...pv) - Math.min(...pv);
        const pvMean = pv.reduce((a, b) => a + b, 0) / pv.length;
        const pvVariation = pvRange / (Math.abs(pvMean) || 1);
        
        // 如果检测到扰动（PV变化大），即使数据点少也可以整定
        if (pvVariation > 0.05) {
            console.log(`✅ 检测到明显扰动（变化率${(pvVariation * 100).toFixed(2)}%），数据可用于整定`);
            return {
                isReady: true,
                dataCount: count,
                svChanges: svChanges.length,
                pvVariation: (pvVariation * 100).toFixed(2) + '%',
                message: `检测到扰动：${count}个数据点，变化率${(pvVariation * 100).toFixed(2)}%`
            };
        }
        
        // 如果没有明显扰动，需要更多数据点
        if (svChanges.length === 0 && count < 300) {
            return {
                isReady: false,
                reason: `未检测到明显的设定值变化或扰动（数据点：${count}）`,
                dataCount: count,
                suggestion: '建议：1) 等待扰动发生 2) 改变设定值 3) 继续采集更多数据'
            };
        }
        
        // 数据变化太小，可能处于完全稳态
        if (pvVariation < 0.01 && count < 500) {
            return {
                isReady: false,
                reason: `数据变化范围太小（变化率：${(pvVariation * 100).toFixed(2)}%）`,
                dataCount: count,
                suggestion: '系统处于完全稳态，建议等待扰动或改变设定值'
            };
        }
        
        // 数据质量良好
        return {
            isReady: true,
            dataCount: count,
            svChanges: svChanges.length,
            pvVariation: (pvVariation * 100).toFixed(2) + '%',
            message: `数据质量良好：${count}个数据点，${svChanges.length}次设定值变化`
        };
        
    } catch (error) {
        console.error('数据质量检查失败:', error);
        return { 
            isReady: false, 
            reason: '数据质量检查失败: ' + error.message,
            dataCount: 0
        };
    }
}

// 检测设定值变化
function detectSetpointChanges(sv) {
    if (!sv || sv.length < 10) return [];
    
    const changes = [];
    const threshold = 0.5; // 变化阈值
    
    for (let i = 10; i < sv.length; i++) {
        const prevAvg = sv.slice(i - 10, i).reduce((a, b) => a + b, 0) / 10;
        const diff = Math.abs(sv[i] - prevAvg);
        
        if (diff > threshold) {
            // 避免连续检测
            if (changes.length === 0 || i - changes[changes.length - 1] > 50) {
                changes.push(i);
            }
        }
    }
    
    return changes;
}

// 智能等待数据采集
let intelligentWaitingInterval = null;

function startIntelligentWaiting(loopId, loopName) {
    // 清除之前的等待
    if (intelligentWaitingInterval) {
        clearInterval(intelligentWaitingInterval);
    }
    
    console.log('🕐 启动智能等待，回路:', loopName);
    
    let checkCount = 0;
    const maxChecks = 60; // 最多检查60次（10分钟）
    
    intelligentWaitingInterval = setInterval(async () => {
        checkCount++;
        console.log(`🔍 数据质量检查 #${checkCount}...`);
        
        const qualityCheck = await checkDataQuality(loopId);
        
        // 更新回路状态显示
        updateLoopTuningStatus(loopId, {
            status: 'waiting',
            message: `等待数据 (${qualityCheck.dataCount}个点)`,
            checkCount: checkCount
        });
        
        if (qualityCheck.isReady) {
            // 数据就绪
            clearInterval(intelligentWaitingInterval);
            intelligentWaitingInterval = null;
            
            console.log('✅ 数据质量检查通过:', qualityCheck.message);
            showAlert(`✅ 数据已就绪！\n${qualityCheck.message}\n\n即将开始整定...`, 'success');
            
            // 自动开始整定
            setTimeout(() => {
                performTuningWithData(loopId);
            }, 1000);
            
        } else if (checkCount >= maxChecks) {
            // 超时
            clearInterval(intelligentWaitingInterval);
            intelligentWaitingInterval = null;
            
            console.warn('⏰ 智能等待超时');
            showAlert(`⏰ 等待超时\n\n当前状态：${qualityCheck.reason}\n数据点数：${qualityCheck.dataCount}\n\n您可以：\n1. 继续等待并手动点击整定\n2. 使用当前数据强制整定`, 'warning');
            
            updateLoopTuningStatus(loopId, {
                status: 'timeout',
                message: '等待超时'
            });
        } else {
            // 继续等待
            console.log(`⏳ 继续等待... ${qualityCheck.reason}`);
        }
        
    }, 10000); // 每10秒检查一次
}

// 停止智能等待
function stopIntelligentWaiting() {
    if (intelligentWaitingInterval) {
        clearInterval(intelligentWaitingInterval);
        intelligentWaitingInterval = null;
        console.log('⏹️ 智能等待已停止');
    }
}

// 更新回路整定状态显示
function updateLoopTuningStatus(loopId, status) {
    // 更新回路卡片上的状态显示
    const loopCard = document.querySelector(`[data-loop-id="${loopId}"]`);
    if (loopCard) {
        // 可以在这里添加状态指示器
        console.log(`📊 更新回路 ${loopId} 状态:`, status);
    }
}

// 执行整定（使用已采集的数据）
async function performTuningWithData(loopId) {
    console.log('🚀 开始执行整定，回路ID:', loopId);
    console.log('⏰ 整定时间戳:', new Date().toISOString());
    
    try {
        // 🔧 强制重新获取最新采集的数据（不使用缓存）
        const timestamp = Date.now(); // 添加时间戳防止缓存
        console.log('🔄 请求最新数据，时间戳:', timestamp);
        const dataResponse = await axios.get(`${window.API_BASE_URL}/api/opcua/collected_data?loop_id=${loopId}&limit=2000&_t=${timestamp}`, {
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
        });
        
        if (!dataResponse.data.success || !dataResponse.data.data) {
            showAlert('获取采集数据失败', 'error');
            return;
        }
        
        const collectedData = dataResponse.data.data;
        
        // 🔍 调试：查看完整的数据结构
        console.log('📦 后端返回的原始数据:', collectedData);
        console.log('📊 数据字段检查:', {
            'pv存在': !!collectedData.pv,
            'pv长度': collectedData.pv?.length || 0,
            'time存在': !!collectedData.time,
            'time长度': collectedData.time?.length || 0,
            'sv存在': !!collectedData.sv,
            'sv长度': collectedData.sv?.length || 0,
            'mv存在': !!collectedData.mv,
            'mv长度': collectedData.mv?.length || 0
        });
        
        console.log('✅ 获取到最新采集数据:', {
            数据点数: collectedData.pv?.length || 0,
            时间范围: (collectedData.time && collectedData.time.length > 0) ? 
                `${collectedData.time[0]} ~ ${collectedData.time[collectedData.time.length-1]}` : 'N/A',
            PV范围: (collectedData.pv && collectedData.pv.length > 0) ? 
                `${Math.min(...collectedData.pv).toFixed(2)} ~ ${Math.max(...collectedData.pv).toFixed(2)}` : 'N/A'
        });
        
        // 转换为整定所需的格式
        const dataArray = [];
        const pvData = collectedData.pv || [];
        const timeData = collectedData.time || [];
        const svData = collectedData.sv || [];
        const mvData = collectedData.mv || [];
        
        if (pvData.length === 0) {
            showAlert('❌ 采集数据为空，无法进行整定', 'error');
            return;
        }
        
        for (let i = 0; i < pvData.length; i++) {
            dataArray.push({
                time: timeData[i] !== undefined ? timeData[i] : i,
                pv: pvData[i],
                sp: svData[i] !== undefined ? svData[i] : pvData[i],
                mv: mvData[i] !== undefined ? mvData[i] : 0
            });
        }
        
        // 🔧 完全清除所有旧的全局变量和缓存，强制使用新数据
        console.log('🧹 清除所有旧数据和结果...');
        console.log('🔍 清除前 - window.uploadedData:', window.uploadedData ? `${window.uploadedData.length}个点` : 'null');
        
        // 清除全局变量
        window.uploadedData = null;
        window.tuningResult = null;
        window.simulationData = null;
        window.evaluationMetrics = null;
        window.batchResultsData = null;
        window.originalTunedParams = null;
        
        // 🔧 关键：通过window访问app.js中的局部变量并清除
        // 这些变量虽然是局部的，但可以通过特殊方式访问
        try {
            // 触发一个自定义事件来通知app.js清除其局部变量
            window.dispatchEvent(new CustomEvent('clearTuningData', { 
                detail: { timestamp: timestamp }
            }));
            console.log('📢 已发送清除数据事件');
        } catch (e) {
            console.warn('⚠️ 发送清除事件失败:', e);
        }
        
        // 添加一个标记，表示这是新的整定请求
        window.lastTuningTimestamp = timestamp;
        
        // 短暂延迟确保清除完成
        await new Promise(resolve => setTimeout(resolve, 50));
        
        // 存储最新数据到全局变量
        window.uploadedData = dataArray;
        
        // 🔧 标记这是OPC UA数据源，仿真图表应使用原始SV
        window.isOPCUAData = true;
        window.opcuaLoopId = loopId;
        console.log('🔧 已标记为OPC UA数据源，仿真图表将使用原始SV');
        
        // 🔍 调试：检查SV数据
        const svSample = dataArray.slice(0, 5).map(item => item.sp);
        console.log('🔍 OPC UA原始SV样本:', svSample);
        console.log('🔍 SV范围:', {
            min: Math.min(...dataArray.map(item => item.sp)),
            max: Math.max(...dataArray.map(item => item.sp)),
            count: dataArray.length
        });
        
        console.log(`✅ 已更新全局数据：${dataArray.length}个数据点`);
        console.log('📊 数据样本（前3个点）:', dataArray.slice(0, 3));
        console.log('📊 数据样本（后3个点）:', dataArray.slice(-3));
        console.log('🔍 更新后 - window.uploadedData:', window.uploadedData ? `${window.uploadedData.length}个点` : 'null');
        
        // 获取回路信息
        const loopResponse = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}?_t=${timestamp}`);
        const loop = loopResponse.data.loop;
        
        // 切换到整定页面
        navigateToTuningPage(loop, dataArray, timestamp);
        
    } catch (error) {
        console.error('执行整定失败:', error);
        showAlert('执行整定失败: ' + error.message, 'error');
    }
}

// 导航到整定页面
function navigateToTuningPage(loop, dataArray, timestamp) {
    console.log('🔍 切换到整定页面...');
    console.log('📊 传入数据点数:', dataArray.length);
    console.log('⏰ 整定时间戳:', timestamp);
    
    // 关闭模态框
    closeLoopDetailsModal();
    
    // 切换标签页
    const tuningTab = document.querySelector('[data-tab="tuning"]');
    if (tuningTab) {
        tuningTab.click();
        
        setTimeout(() => {
            // 更新文件信息
            const fileInfo = document.getElementById('fileInfo');
            if (fileInfo) {
                fileInfo.style.display = 'block';
                const now = new Date();
                fileInfo.innerHTML = `
                    <strong>数据来源:</strong> OPC UA实时采集 (${loop.name})<br>
                    <strong>数据点数:</strong> ${dataArray.length}<br>
                    <strong>节点ID:</strong> ${loop.opcua_config?.pv_node_id || 'N/A'}<br>
                    <strong>数据更新时间:</strong> <span style="color: #4ade80;">${now.toLocaleString()}</span> ⏱️<br>
                    <strong>整定ID:</strong> <span style="color: #a5b4fc; font-size: 11px;">${timestamp}</span>
                `;
            }
            
            // 更新状态提示
            const dataStatusHint = document.getElementById('dataStatusHint');
            const dataLoadedHint = document.getElementById('dataLoadedHint');
            if (dataStatusHint) dataStatusHint.style.display = 'none';
            if (dataLoadedHint) {
                dataLoadedHint.style.display = 'block';
                dataLoadedHint.innerHTML = '<p style="color: #4ade80; margin: 0; font-size: 14px;">✅ 实时数据已加载，可以开始整定</p>';
            }
            
            // 清除之前的结果显示
            const resultsContainer = document.getElementById('resultsContainer');
            if (resultsContainer) {
                resultsContainer.style.display = 'none';
            }
            
            // 启用整定按钮
            const tuneBtn = document.getElementById('tuneBtn');
            if (tuneBtn) {
                tuneBtn.disabled = false;
                console.log('✅ 整定按钮已启用，等待用户手动点击');
            }
            
            // 显示数据预览
            if (typeof displayUploadedDataPreview === 'function') {
                displayUploadedDataPreview(dataArray);
            }
            
            showAlert(`✅ 已加载 ${dataArray.length} 个实时数据点，请点击"开始整定"按钮进行整定`, 'success');
        }, 200);
    }
    
    // 保存回路信息和时间戳
    window.currentLoopForTuning = loop;
    window.currentLoopTuningTimestamp = timestamp;
}

// 整定回路（重构版）
window.tuneLoop = async function tuneLoop(loopId) {
    console.log('🔧 开始整定流程，回路ID:', loopId);
    
    try {
        // 获取回路信息
        const response = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}`);
        
        if (!response.data.success) {
            showAlert('获取回路信息失败', 'error');
            return;
        }
        
        const loop = response.data.loop;
        console.log('✅ 回路信息:', loop);
        
        // 根据数据源类型处理
        if (loop.data_source === 'opcua') {
            // OPC UA数据源 - 智能整定流程
            console.log('🔌 OPC UA数据源，启动智能整定流程...');
            
            if (!loop.opcua_config?.is_collecting) {
                showAlert('⚠️ 回路未在采集数据\n\n请先点击"开始采集"按钮启动数据采集', 'warning');
                return;
            }
            
            // 步骤1：检查数据质量
            showAlert('🔍 正在检查数据质量...', 'info');
            const qualityCheck = await checkDataQuality(loopId);
            
            console.log('📊 数据质量检查结果:', qualityCheck);
            
            if (qualityCheck.isReady) {
                // 数据质量良好，直接整定
                showAlert(`✅ ${qualityCheck.message}\n\n开始整定...`, 'success');
                await performTuningWithData(loopId);
                
            } else {
                // 数据质量不足，询问用户
                console.log('⚠️ 数据质量不足，显示用户选择对话框');
                
                const userChoice = confirm(
                    `📊 数据质量检查\n\n` +
                    `状态：${qualityCheck.reason}\n` +
                    `当前数据点：${qualityCheck.dataCount}个\n` +
                    `${qualityCheck.suggestion || ''}\n\n` +
                    `━━━━━━━━━━━━━━━━━━━━\n\n` +
                    `推荐操作：\n` +
                    `✅ 点击"确定" - 智能等待数据充足后自动整定\n` +
                    `❌ 点击"取消" - 使用当前数据强制整定\n\n` +
                    `是否启动智能等待？`
                );
                
                console.log('👤 用户选择:', userChoice ? '确定（智能等待）' : '取消（强制整定）');
                
                if (userChoice) {
                    // 启动智能等待
                    console.log('🕐 启动智能等待流程...');
                    showAlert(
                        `🕐 智能等待已启动\n\n` +
                        `系统将每10秒检查一次数据质量\n` +
                        `数据就绪后将自动开始整定\n\n` +
                        `当前：${qualityCheck.dataCount}个数据点`,
                        'info'
                    );
                    startIntelligentWaiting(loopId, loop.name);
                    console.log('✅ 智能等待已启动');
                } else {
                    // 强制整定
                    console.log('⚠️ 用户选择强制整定');
                    if (qualityCheck.dataCount < 100) {
                        showAlert('❌ 数据点太少（少于100个），无法进行整定', 'error');
                        return;
                    }
                    showAlert(`⚠️ 使用当前 ${qualityCheck.dataCount} 个数据点进行整定\n\n整定结果可能不够准确`, 'warning');
                    await performTuningWithData(loopId);
                }
            }
            
        } else if (loop.data_source === 'file' && loop.original_data) {
            // JSON文件数据源 - 直接整定
            console.log('📄 JSON文件数据源，直接加载数据...');
            window.uploadedData = loop.original_data;
            navigateToTuningPage(loop, loop.original_data);
            
        } else {
            showAlert('❌ 无可用数据\n\n请先上传数据文件或配置OPC UA数据源', 'error');
            return;
        }
        
    } catch (error) {
        console.error('❌ 整定流程失败:', error);
        showAlert('整定流程失败: ' + error.message, 'error');
    }
}

// 删除回路
window.deleteLoop = async function deleteLoop(loopId) {
    if (!confirm('确定要删除这个回路吗？')) {
        return;
    }
    
    try {
        const response = await axios.delete(`${window.API_BASE_URL}/api/loops/${loopId}`);
        if (response.data.success) {
            showAlert(response.data.message, 'success');
            await loadLoops();
        }
    } catch (error) {
        console.error('删除回路失败:', error);
        showAlert('删除回路失败: ' + error.message, 'error');
    }
}

// 启动OPC UA采集
window.startOPCUACollection = async function(loopId) {
    console.log('🚀 startOPCUACollection 被调用, loopId:', loopId);
    try {
        // 1. 检查回路配置
        const loop = allLoops.find(l => l.id === loopId);
        console.log('📋 找到的回路:', loop);
        if (!loop || !loop.opcua_config) {
            console.error('❌ 回路配置错误');
            showAlert('回路配置错误', 'error');
            return;
        }
        console.log('✅ 回路配置正常:', loop.opcua_config);
        
        // 2. 检查OPC UA连接状态
        console.log('🔍 检查OPC UA连接状态...');
        const statusResponse = await axios.get(`${window.API_BASE_URL}/api/opcua/status`);
        console.log('📡 OPC UA状态响应:', statusResponse.data);
        
        if (!statusResponse.data.connected) {
            console.warn('⚠️ OPC UA未连接，尝试自动连接...');
            showAlert('OPC UA未连接，正在自动连接...', 'info');
            
            // 尝试自动连接
            try {
                const connectResponse = await axios.post(`${window.API_BASE_URL}/api/opcua/connect`, {
                    url: 'opc.tcp://localhost:4840/freeopcua/server/'
                });
                
                if (connectResponse.data.success) {
                    console.log('✅ OPC UA自动连接成功');
                    showAlert('OPC UA连接成功！', 'success');
                    // 等待1秒确保连接稳定
                    await new Promise(resolve => setTimeout(resolve, 1000));
                } else {
                    console.error('❌ OPC UA自动连接失败:', connectResponse.data.message);
                    showAlert('OPC UA连接失败: ' + connectResponse.data.message + '\n\n请确保OPC UA服务器正在运行！', 'error');
                    return;
                }
            } catch (error) {
                console.error('❌ OPC UA连接异常:', error);
                showAlert('OPC UA连接失败，请确保服务器正在运行！', 'error');
                return;
            }
        } else {
            console.log('✅ OPC UA已连接');
        }
        
        // 3. 显示加载提示
        console.log('💬 显示加载提示...');
        showAlert('正在启动采集...', 'info');
        
        // 4. 启动采集
        const response = await axios.post(`${window.API_BASE_URL}/api/opcua/start_collect`, {
            pv_node_id: loop.opcua_config.pv_node_id,
            sv_node_id: loop.opcua_config.sv_node_id,
            mv_node_id: loop.opcua_config.mv_node_id,
            interval_ms: loop.opcua_config.sampling_interval,
            loop_id: loopId
        });
        
        if (response.data.success) {
            showAlert(`✅ OPC UA采集已启动\n节点: ${loop.opcua_config.node_id}\n间隔: ${loop.opcua_config.sampling_interval}ms`, 'success');
            await loadLoops();
        } else {
            showAlert('启动采集失败: ' + response.data.message, 'error');
        }
    } catch (error) {
        console.error('❌ 启动OPC UA采集失败:', error);
        console.error('错误详情:', {
            message: error.message,
            response: error.response?.data,
            status: error.response?.status
        });
        showAlert('启动采集失败: ' + (error.response?.data?.message || error.message), 'error');
    }
}

// 停止OPC UA采集
window.stopOPCUACollection = async function(loopId) {
    try {
        const response = await axios.post(`${window.API_BASE_URL}/api/opcua/stop_collect?loop_id=${loopId}`);
        
        if (response.data.success) {
            showAlert('OPC UA采集已停止', 'info');
            await loadLoops();
        } else {
            showAlert('停止采集失败: ' + response.data.message, 'error');
        }
    } catch (error) {
        console.error('停止OPC UA采集失败:', error);
        showAlert('停止采集失败: ' + error.message, 'error');
    }
}

// 设置事件监听
function setupEventListeners() {
    // 新建回路按钮
    const createBtn = document.getElementById('createLoopBtn');
    if (createBtn) {
        createBtn.addEventListener('click', createNewLoop);
    }
    
    // 刷新按钮
    const refreshBtn = document.getElementById('refreshLoopsBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', loadLoops);
    }
    
    // 导入按钮
    const importBtn = document.getElementById('importLoopsBtn');
    if (importBtn) {
        importBtn.addEventListener('click', importLoops);
    }
    
    // 筛选功能
    const searchInput = document.getElementById('loopSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', applyFilters);
    }
    
    const areaFilter = document.getElementById('areaFilter');
    if (areaFilter) {
        areaFilter.addEventListener('change', applyFilters);
    }
    
    const statusFilter = document.getElementById('statusFilter');
    if (statusFilter) {
        statusFilter.addEventListener('change', applyFilters);
    }
    
    const sortBy = document.getElementById('sortBy');
    if (sortBy) {
        sortBy.addEventListener('change', applyFilters);
    }
}

// 应用筛选
function applyFilters() {
    const searchText = document.getElementById('loopSearchInput')?.value.toLowerCase() || '';
    const selectedArea = document.getElementById('areaFilter')?.value || 'all';
    const selectedStatus = document.getElementById('statusFilter')?.value || 'all';
    const sortBy = document.getElementById('sortBy')?.value || 'name';
    
    console.log('🔍 应用筛选:', { searchText, selectedArea, selectedStatus, sortBy });
    
    // 筛选回路
    let filtered = allLoops.filter(loop => {
        // 搜索文本筛选
        if (searchText) {
            const matchName = loop.name.toLowerCase().includes(searchText);
            const matchDesc = loop.description?.toLowerCase().includes(searchText);
            if (!matchName && !matchDesc) return false;
        }
        
        // 区域筛选
        if (selectedArea !== 'all') {
            const loopArea = loop.area || '未分类';
            if (loopArea !== selectedArea) return false;
        }
        
        // 状态筛选
        if (selectedStatus !== 'all') {
            if (loop.status !== selectedStatus) return false;
        }
        
        return true;
    });
    
    // 排序
    filtered.sort((a, b) => {
        let aVal, bVal;
        switch (sortBy) {
            case 'name':
                aVal = a.name.toLowerCase();
                bVal = b.name.toLowerCase();
                return aVal > bVal ? 1 : -1;
            case 'score':
                aVal = a.performance?.score || 0;
                bVal = b.performance?.score || 0;
                return bVal - aVal; // 降序
            case 'updated':
                aVal = new Date(a.updated_at || 0);
                bVal = new Date(b.updated_at || 0);
                return bVal - aVal; // 降序
            default:
                return 0;
        }
    });
    
    console.log('✅ 筛选结果:', filtered.length, '个回路');
    displayLoops(filtered);
}

// 更新区域筛选下拉框选项
function updateAreaFilterOptions() {
    const areaFilter = document.getElementById('areaFilter');
    if (!areaFilter) return;
    
    // 获取所有唯一的区域
    const areas = [...new Set(allLoops.map(l => l.area || '未分类'))];
    
    // 保存当前选中的值
    const currentValue = areaFilter.value;
    
    // 更新选项
    areaFilter.innerHTML = '<option value="all">全部区域</option>' +
        areas.map(area => `<option value="${area}">${area}</option>`).join('');
    
    // 恢复选中的值
    if (currentValue && areas.includes(currentValue)) {
        areaFilter.value = currentValue;
    }
}

// ============================================================================
// 批量选择功能
// ============================================================================

window.toggleLoopSelection = function(loopId, event) {
    console.log('✅ toggleLoopSelection 被调用，回路ID:', loopId);
    event.stopPropagation();
    
    if (selectedLoops.has(loopId)) {
        selectedLoops.delete(loopId);
        console.log('➖ 取消选中:', loopId);
    } else {
        selectedLoops.add(loopId);
        console.log('➕ 选中:', loopId);
    }
    
    console.log('📦 当前选中的回路:', Array.from(selectedLoops));
    updateBatchActionsUI();
    
    // 更新卡片样式
    const card = document.querySelector(`[data-loop-id="${loopId}"]`);
    if (card) {
        if (selectedLoops.has(loopId)) {
            card.classList.add('selected');
        } else {
            card.classList.remove('selected');
        }
    }
}

window.deselectAll = function() {
    selectedLoops.clear();
    displayLoops(allLoops);
    updateBatchActionsUI();
}

function updateBatchActionsUI() {
    const batchActionsBar = document.getElementById('batchActionsBar');
    const selectedCount = document.getElementById('selectedCount');
    
    console.log('🔄 updateBatchActionsUI 被调用');
    console.log('📊 批量操作栏元素:', batchActionsBar);
    console.log('🔢 选中数量元素:', selectedCount);
    console.log('📦 选中的回路数:', selectedLoops.size);
    
    if (batchActionsBar && selectedCount) {
        if (selectedLoops.size > 0) {
            batchActionsBar.style.display = 'flex';
            selectedCount.textContent = selectedLoops.size;
            console.log('✅ 批量操作栏已显示，选中数量:', selectedLoops.size);
        } else {
            batchActionsBar.style.display = 'none';
            console.log('❌ 批量操作栏已隐藏');
        }
    } else {
        console.error('❌ 找不到批量操作栏或选中数量元素');
    }
}

// ============================================================================
// 批量操作功能
// ============================================================================

window.batchTuneLoops = async function() {
    if (selectedLoops.size === 0) {
        showAlert('请先选择要整定的回路', 'warning');
        return;
    }
    
    if (!confirm(`确定要批量整定 ${selectedLoops.size} 个回路吗？`)) {
        return;
    }
    
    showAlert(`批量整定功能开发中，已选中 ${selectedLoops.size} 个回路`, 'info');
    // TODO: 实现批量整定逻辑
}

window.batchExportLoops = function() {
    if (selectedLoops.size === 0) {
        showAlert('请先选择要导出的回路', 'warning');
        return;
    }
    
    const selectedLoopsData = allLoops.filter(l => selectedLoops.has(l.id));
    
    const exportData = {
        export_time: new Date().toISOString(),
        total_loops: selectedLoopsData.length,
        loops: selectedLoopsData
    };
    
    const dataStr = JSON.stringify(exportData, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `loops_export_${Date.now()}.json`;
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    
    showAlert(`已导出 ${selectedLoopsData.length} 个回路`, 'success');
}

window.batchDeleteLoops = async function() {
    if (selectedLoops.size === 0) {
        showAlert('请先选择要删除的回路', 'warning');
        return;
    }
    
    if (!confirm(`确定要删除 ${selectedLoops.size} 个回路吗？此操作不可恢复！`)) {
        return;
    }
    
    let successCount = 0;
    let failCount = 0;
    
    for (const loopId of selectedLoops) {
        try {
            const response = await axios.delete(`${window.API_BASE_URL}/api/loops/${loopId}`);
            if (response.data.success) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (error) {
            console.error(`删除回路 ${loopId} 失败:`, error);
            failCount++;
        }
    }
    
    selectedLoops.clear();
    showAlert(`批量删除完成！成功: ${successCount}, 失败: ${failCount}`, 'success');
    await loadLoops();
}

// ============================================================================
// 回路对比功能
// ============================================================================

window.compareSelectedLoops = function() {
    if (selectedLoops.size < 2) {
        showAlert('请至少选择2个回路进行对比', 'warning');
        return;
    }
    
    if (selectedLoops.size > 5) {
        showAlert('最多只能对比5个回路', 'warning');
        return;
    }
    
    const selectedLoopsData = allLoops.filter(l => selectedLoops.has(l.id));
    showLoopComparisonModal(selectedLoopsData);
}

function showLoopComparisonModal(loops) {
    const modal = document.getElementById('loopComparisonModal');
    if (!modal) {
        console.error('找不到对比模态框');
        return;
    }
    
    let html = `
        <div style="padding: 24px;">
            <h3 style="color: #e2e8f0; margin-bottom: 20px;">📊 回路对比 (${loops.length}个)</h3>
            
            <table style="width: 100%; border-collapse: collapse; color: #e2e8f0;">
                <thead>
                    <tr style="background: rgba(102, 126, 234, 0.2);">
                        <th style="padding: 12px; text-align: left; border-bottom: 2px solid rgba(102, 126, 234, 0.3);">指标</th>
                        ${loops.map(loop => `<th style="padding: 12px; text-align: center; border-bottom: 2px solid rgba(102, 126, 234, 0.3);">${loop.name}</th>`).join('')}
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">区域</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">${loop.area}</td>`).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">状态</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">${loop.status === 'active' ? '🟢 运行中' : '⚪ 停止'}</td>`).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">Pb (%)</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2); font-family: monospace;">${loop.pid_params?.pb?.toFixed(2) || '-'}</td>`).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">Ti (s)</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2); font-family: monospace;">${loop.pid_params?.ti?.toFixed(2) || '-'}</td>`).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">Td (s)</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2); font-family: monospace;">${loop.pid_params?.td?.toFixed(2) || '-'}</td>`).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">评分</td>
                        ${loops.map(loop => {
                            const score = loop.performance?.score || 0;
                            const color = score >= 80 ? '#10b981' : score >= 60 ? '#fbbf24' : '#ef4444';
                            return `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2);"><span style="color: ${color}; font-weight: 600; font-size: 16px;">${score.toFixed(0)}</span></td>`;
                        }).join('')}
                    </tr>
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid rgba(148, 163, 184, 0.2);">稳态误差</td>
                        ${loops.map(loop => `<td style="padding: 10px; text-align: center; border-bottom: 1px solid rgba(148, 163, 184, 0.2); font-family: monospace;">${loop.performance?.steady_error?.toFixed(4) || '-'}</td>`).join('')}
                    </tr>
                </tbody>
            </table>
            
            <div style="display: flex; gap: 12px; margin-top: 20px; justify-content: flex-end;">
                <button class="btn btn-secondary" onclick="closeLoopComparisonModal()">关闭</button>
            </div>
        </div>
    `;
    
    document.getElementById('loopComparisonContent').innerHTML = html;
    modal.style.display = 'flex';
}

window.closeLoopComparisonModal = function() {
    const modal = document.getElementById('loopComparisonModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

// 查看重整定历史记录
window.viewRetuningHistory = async function(loopId) {
    try {
        // 获取回路信息
        const loopResponse = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}`);
        const loop = loopResponse.data.loop;
        
        // 获取整定历史记录
        const historyResponse = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}/tuning-history`);
        
        if (historyResponse.data.success) {
            const records = historyResponse.data.records || [];
            
            if (records.length === 0) {
                showAlert('该回路暂无整定历史记录', 'info');
                return;
            }
            
            // 显示历史记录对话框
            showTuningHistoryDialog(loop, records);
        } else {
            showAlert('获取整定历史记录失败: ' + historyResponse.data.error, 'error');
        }
    } catch (error) {
        console.error('获取整定历史记录失败:', error);
        showAlert('获取整定历史记录失败: ' + error.message, 'error');
    }
}

// 显示整定历史记录对话框
function showTuningHistoryDialog(loop, records) {
    const dialogHTML = `
        <div id="tuningHistoryDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.8); backdrop-filter: blur(10px); z-index: 3000; display: flex; align-items: center; justify-content: center; animation: fadeIn 0.3s;">
            <div style="background: rgba(15, 23, 42, 0.98); padding: 30px; border-radius: 20px; max-width: 1200px; width: 90%; max-height: 85vh; overflow-y: auto; border: 1px solid rgba(102, 126, 234, 0.3); box-shadow: 0 0 60px rgba(102, 126, 234, 0.4);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 25px; padding-bottom: 15px; border-bottom: 2px solid rgba(102, 126, 234, 0.3);">
                    <h3 style="color: #e2e8f0; margin: 0; font-size: 24px; display: flex; align-items: center; gap: 10px;">
                        <span style="font-size: 28px;">📊</span>
                        <span>整定历史记录 - ${loop.name}</span>
                    </h3>
                    <button onclick="closeTuningHistoryDialog()" style="background: none; border: none; color: #94a3b8; font-size: 28px; cursor: pointer; padding: 0; width: 40px; height: 40px; display: flex; align-items: center; justify-content: center; border-radius: 8px; transition: all 0.3s;" onmouseover="this.style.background='rgba(239, 68, 68, 0.2)'; this.style.color='#ef4444';" onmouseout="this.style.background='none'; this.style.color='#94a3b8';">×</button>
                </div>
                
                <div style="margin-bottom: 20px; padding: 15px; background: rgba(102, 126, 234, 0.1); border-radius: 12px; border-left: 4px solid #667eea;">
                    <p style="margin: 0; color: #cbd5e1; font-size: 14px;">
                        <strong style="color: #667eea;">共 ${records.length} 条整定记录</strong> | 
                        最新整定时间: ${new Date(records[0].timestamp).toLocaleString('zh-CN')}
                    </p>
                </div>
                
                <div id="tuningHistoryList" style="display: grid; gap: 15px;">
                    ${records.map((record, index) => generateRecordCard(record, index, records.length)).join('')}
                </div>
                
                <div style="margin-top: 25px; padding-top: 20px; border-top: 1px solid rgba(102, 126, 234, 0.2); display: flex; gap: 12px; justify-content: space-between;">
                    <button class="btn btn-warning" onclick="clearAllTuningHistory('${loop.id}')" style="padding: 12px 24px; background: #ef4444; border: none;">
                        🗑️ 清空所有记录
                    </button>
                    <button class="btn btn-secondary" onclick="closeTuningHistoryDialog()" style="padding: 12px 24px;">关闭</button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', dialogHTML);
}

// 生成单条记录卡片
function generateRecordCard(record, index, total) {
    const date = new Date(record.timestamp);
    const isLatest = index === 0;
    const performance = record.performance || {};
    
    return `
        <div style="background: rgba(30, 41, 59, 0.6); backdrop-filter: blur(10px); padding: 20px; border-radius: 12px; border: 1px solid ${isLatest ? 'rgba(16, 185, 129, 0.5)' : 'rgba(102, 126, 234, 0.3)'}; box-shadow: 0 4px 12px rgba(0,0,0,0.3); transition: all 0.3s; position: relative; overflow: hidden;" onmouseover="this.style.transform='translateX(5px)'; this.style.boxShadow='0 6px 20px rgba(102, 126, 234, 0.4)';" onmouseout="this.style.transform='translateX(0)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.3)';">
            ${isLatest ? '<div style="position: absolute; top: 15px; right: 15px; background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600; box-shadow: 0 2px 8px rgba(16, 185, 129, 0.4);">最新</div>' : ''}
            
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 15px;">
                <div>
                    <div style="font-size: 18px; font-weight: 600; color: #e2e8f0; margin-bottom: 5px;">
                        记录 #${total - index}
                    </div>
                    <div style="font-size: 13px; color: #94a3b8;">
                        ${date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </div>
                </div>
                <div style="text-align: right;">
                    <div style="font-size: 32px; font-weight: 700; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">
                        ${performance.score?.toFixed(1) || 'N/A'}
                    </div>
                    <div style="font-size: 12px; color: #94a3b8;">${performance.grade || 'N/A'}</div>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 15px;">
                <div style="background: rgba(102, 126, 234, 0.15); padding: 12px; border-radius: 8px; border: 1px solid rgba(102, 126, 234, 0.3);">
                    <div style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">Pb (%)</div>
                    <div style="font-size: 18px; font-weight: 600; color: #667eea;">${record.pid_params.pb.toFixed(2)}</div>
                </div>
                <div style="background: rgba(139, 92, 246, 0.15); padding: 12px; border-radius: 8px; border: 1px solid rgba(139, 92, 246, 0.3);">
                    <div style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">Ti (s)</div>
                    <div style="font-size: 18px; font-weight: 600; color: #8b5cf6;">${record.pid_params.ti.toFixed(2)}</div>
                </div>
                <div style="background: rgba(59, 130, 246, 0.15); padding: 12px; border-radius: 8px; border: 1px solid rgba(59, 130, 246, 0.3);">
                    <div style="font-size: 11px; color: #94a3b8; margin-bottom: 4px;">Td (s)</div>
                    <div style="font-size: 18px; font-weight: 600; color: #3b82f6;">${record.pid_params.td.toFixed(2)}</div>
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; padding: 12px; background: rgba(0, 0, 0, 0.3); border-radius: 8px;">
                <div style="text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">稳态误差</div>
                    <div style="font-size: 14px; font-weight: 600; color: #e2e8f0;">${performance.steady_error?.toFixed(4) || 'N/A'}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">振荡次数</div>
                    <div style="font-size: 14px; font-weight: 600; color: #e2e8f0;">${performance.oscillation_count || 0}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">IAE</div>
                    <div style="font-size: 14px; font-weight: 600; color: #e2e8f0;">${performance.iae?.toFixed(2) || 'N/A'}</div>
                </div>
                <div style="text-align: center;">
                    <div style="font-size: 10px; color: #94a3b8;">TV</div>
                    <div style="font-size: 14px; font-weight: 600; color: #e2e8f0;">${performance.tv?.toFixed(2) || 'N/A'}</div>
                </div>
            </div>
            
            <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                <span style="font-size: 11px; padding: 4px 10px; background: rgba(102, 126, 234, 0.2); border-radius: 12px; color: #a5b4fc; border: 1px solid rgba(102, 126, 234, 0.3);">
                    ${record.model_type || 'FOPDT'}
                </span>
                <span style="font-size: 11px; padding: 4px 10px; background: rgba(139, 92, 246, 0.2); border-radius: 12px; color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.3);">
                    ${record.tuning_method || 'Lambda'}
                </span>
                <span style="font-size: 11px; padding: 4px 10px; background: rgba(59, 130, 246, 0.2); border-radius: 12px; color: #93c5fd; border: 1px solid rgba(59, 130, 246, 0.3);">
                    ${record.control_mode || 'Standard'}
                </span>
                ${record.is_steady_state ? '<span style="font-size: 11px; padding: 4px 10px; background: rgba(16, 185, 129, 0.2); border-radius: 12px; color: #6ee7b7; border: 1px solid rgba(16, 185, 129, 0.3);">稳态</span>' : ''}
            </div>
        </div>
    `;
}

// 关闭整定历史记录对话框
window.closeTuningHistoryDialog = function() {
    const dialog = document.getElementById('tuningHistoryDialog');
    if (dialog) {
        dialog.style.animation = 'fadeOut 0.3s';
        setTimeout(() => dialog.remove(), 300);
    }
}

// 清空所有整定历史记录
window.clearAllTuningHistory = async function(loopId) {
    if (!confirm('⚠️ 确定要清空该回路的所有整定历史记录吗？\n\n此操作不可恢复！')) {
        return;
    }
    
    try {
        const response = await axios.delete(`${window.API_BASE_URL}/api/loops/${loopId}/tuning-history`);
        
        if (response.data.success) {
            showAlert('✅ 已清空所有整定历史记录', 'success');
            closeTuningHistoryDialog();
        } else {
            showAlert('清空失败: ' + response.data.error, 'error');
        }
    } catch (error) {
        console.error('清空整定历史记录失败:', error);
        showAlert('清空失败: ' + error.message, 'error');
    }
}

// 定时刷新回路状态（用于更新非稳态告警）
let autoRefreshInterval = null;

function startAutoRefresh() {
    // 每1秒自动刷新一次回路列表（优化：实时显示状态变化）
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    autoRefreshInterval = setInterval(async () => {
        try {
            await loadLoops();
            // console.log('🔄 自动刷新回路状态');  // 减少日志输出
        } catch (error) {
            console.error('自动刷新失败:', error);
        }
    }, 1000); // 1秒刷新，确保实时显示OPC UA状态变化
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
    }
}

// 切换自动整定开关
async function toggleAutoTuning(loopId, enabled) {
    try {
        console.log(`${enabled ? '启用' : '禁用'}自动整定: ${loopId}`);
        
        const response = await axios.post(
            `${window.API_BASE_URL}/api/loops/${loopId}/toggle_auto_tuning`,
            { enabled }
        );
        
        if (response.data.success) {
            showAlert(response.data.message, 'success');
            console.log(`✅ ${response.data.message}`);
            
            // 刷新回路列表以更新UI
            await loadLoops();
        } else {
            showAlert(response.data.message || '切换失败', 'error');
            console.error('❌ 切换失败:', response.data.message);
            
            // 恢复开关状态
            const switchElement = document.getElementById(`autoTuningSwitch_${loopId}`);
            if (switchElement) {
                switchElement.checked = !enabled;
            }
        }
    } catch (error) {
        console.error('切换自动整定失败:', error);
        showAlert('切换失败: ' + error.message, 'error');
        
        // 恢复开关状态
        const switchElement = document.getElementById(`autoTuningSwitch_${loopId}`);
        if (switchElement) {
            switchElement.checked = !enabled;
        }
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    // 如果在回路管理页面，则初始化
    if (document.getElementById('loopsListContainer')) {
        initLoopsManager();
        // 启动自动刷新
        startAutoRefresh();
        console.log('✅ 已启动回路状态自动刷新（每2秒，低延迟模式）');
    }
    
    // 验证全局函数是否已注册
    console.log('✅ 全局函数已注册:', {
        viewLoopDetails: typeof window.viewLoopDetails,
        tuneLoop: typeof window.tuneLoop,
        deleteLoop: typeof window.deleteLoop,
        createNewLoop: typeof window.createNewLoop,
        closeLoopDetailsModal: typeof window.closeLoopDetailsModal,
        batchTuneLoops: typeof window.batchTuneLoops,
        batchExportLoops: typeof window.batchExportLoops,
        batchDeleteLoops: typeof window.batchDeleteLoops,
        compareSelectedLoops: typeof window.compareSelectedLoops,
        toggleLoopSelection: typeof window.toggleLoopSelection,
        deselectAll: typeof window.deselectAll
    });
});

// 页面卸载时停止自动刷新
window.addEventListener('beforeunload', () => {
    stopAutoRefresh();
});

// ============================================================================
// 新增功能：回路模板管理
// ============================================================================

window.createLoopFromTemplate = function(templateKey) {
    const template = loopTemplates[templateKey];
    if (!template) {
        showAlert('模板不存在', 'error');
        return;
    }
    
    // 预填充模板数据到创建对话框
    showCreateLoopDialog();
    
    setTimeout(() => {
        const descInput = document.getElementById('newLoopDesc');
        if (descInput) {
            descInput.value = template.description;
        }
    }, 100);
}

window.showTemplateSelector = function() {
    const dialogHtml = `
        <div id="templateSelectorDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center;">
            <div style="background: #1e293b; padding: 30px; border-radius: 12px; max-width: 600px; width: 90%; border: 1px solid rgba(102, 126, 234, 0.3);">
                <h3 style="color: #e2e8f0; margin-bottom: 20px;">📋 选择回路模板</h3>
                
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;">
                    ${Object.entries(loopTemplates).map(([key, template]) => `
                        <div onclick="createLoopFromTemplate('${key}'); closeTemplateSelectorDialog();" 
                             style="padding: 16px; background: rgba(102, 126, 234, 0.1); border-radius: 8px; border: 2px solid rgba(102, 126, 234, 0.3); cursor: pointer; transition: all 0.2s;"
                             onmouseover="this.style.borderColor='rgba(102, 126, 234, 0.6)'"
                             onmouseout="this.style.borderColor='rgba(102, 126, 234, 0.3)'">
                            <h4 style="color: #667eea; margin-bottom: 8px; font-size: 15px;">${template.name}</h4>
                            <p style="color: #94a3b8; font-size: 13px; margin-bottom: 12px;">${template.description}</p>
                            <div style="font-size: 11px; color: #cbd5e1;">
                                Pb: ${template.pid_params.pb}% | Ti: ${template.pid_params.ti}s | Td: ${template.pid_params.td}s
                            </div>
                        </div>
                    `).join('')}
                </div>
                
                <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;">
                    <button class="btn btn-secondary" onclick="closeTemplateSelectorDialog()">取消</button>
                    <button class="btn btn-primary" onclick="closeTemplateSelectorDialog(); createNewLoop();">自定义创建</button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', dialogHtml);
}

window.closeTemplateSelectorDialog = function() {
    const dialog = document.getElementById('templateSelectorDialog');
    if (dialog) {
        dialog.remove();
    }
}

// ============================================================================
// 新增功能：标签管理
// ============================================================================

window.addTagToLoop = async function(loopId) {
    const tag = prompt('输入标签名称（如：critical, important, test等）:');
    if (!tag) return;
    
    try {
        const loop = allLoops.find(l => l.id === loopId);
        if (!loop) return;
        
        if (!loop.tags) loop.tags = [];
        if (!loop.tags.includes(tag)) {
            loop.tags.push(tag);
            
            // 更新到后端
            await axios.put(`${window.API_BASE_URL}/api/loops/${loopId}`, {
                tags: loop.tags
            });
            
            showAlert('标签添加成功', 'success');
            await loadLoops();
        } else {
            showAlert('标签已存在', 'warning');
        }
    } catch (error) {
        console.error('添加标签失败:', error);
        showAlert('添加标签失败', 'error');
    }
}

window.removeTagFromLoop = async function(loopId, tag) {
    try {
        const loop = allLoops.find(l => l.id === loopId);
        if (!loop || !loop.tags) return;
        
        loop.tags = loop.tags.filter(t => t !== tag);
        
        await axios.put(`${window.API_BASE_URL}/api/loops/${loopId}`, {
            tags: loop.tags
        });
        
        showAlert('标签移除成功', 'success');
        await loadLoops();
    } catch (error) {
        console.error('移除标签失败:', error);
        showAlert('移除标签失败', 'error');
    }
}

// ============================================================================
// 新增功能：快速克隆回路
// ============================================================================

window.cloneLoop = async function(loopId) {
    try {
        const loop = allLoops.find(l => l.id === loopId);
        if (!loop) return;
        
        const newName = prompt('输入新回路名称:', loop.name + ' (副本)');
        if (!newName) return;
        
        const clonedLoop = {
            name: newName,
            description: loop.description,
            area: loop.area,
            data_source: loop.data_source,
            pid_params: { ...loop.pid_params },
            opcua_config: loop.opcua_config ? { ...loop.opcua_config, is_collecting: false } : null,
            tags: loop.tags ? [...loop.tags] : [],
            alarm_thresholds: loop.alarm_thresholds ? { ...loop.alarm_thresholds } : null
        };
        
        const response = await axios.post(`${window.API_BASE_URL}/api/loops`, clonedLoop);
        
        if (response.data.success) {
            showAlert('回路克隆成功', 'success');
            await loadLoops();
        }
    } catch (error) {
        console.error('克隆回路失败:', error);
        showAlert('克隆回路失败', 'error');
    }
}

// ============================================================================
// 新增功能：告警阈值配置
// ============================================================================

window.configureAlarmThresholds = function(loopId) {
    const loop = allLoops.find(l => l.id === loopId);
    if (!loop) return;
    
    const currentThresholds = loop.alarm_thresholds || { high: 5, low: -5 };
    
    const dialogHtml = `
        <div id="alarmConfigDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center;">
            <div style="background: #1e293b; padding: 30px; border-radius: 12px; max-width: 400px; width: 90%; border: 1px solid rgba(102, 126, 234, 0.3);">
                <h3 style="color: #e2e8f0; margin-bottom: 20px;">⚠️ 告警阈值配置</h3>
                <p style="color: #94a3b8; font-size: 13px; margin-bottom: 16px;">回路: ${loop.name}</p>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">高限告警阈值</label>
                    <input type="number" id="alarmHighThreshold" value="${currentThresholds.high}" step="0.1" class="input-field" style="width: 100%;">
                </div>
                
                <div style="margin-bottom: 15px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 5px;">低限告警阈值</label>
                    <input type="number" id="alarmLowThreshold" value="${currentThresholds.low}" step="0.1" class="input-field" style="width: 100%;">
                </div>
                
                <div style="padding: 12px; background: rgba(59, 130, 246, 0.1); border-radius: 8px; margin-bottom: 16px;">
                    <p style="color: #60a5fa; font-size: 12px; margin: 0;">💡 当PV偏离SV超过阈值时将触发告警</p>
                </div>
                
                <div style="display: flex; gap: 10px; justify-content: flex-end;">
                    <button class="btn btn-secondary" onclick="closeAlarmConfigDialog()">取消</button>
                    <button class="btn btn-primary" onclick="saveAlarmThresholds('${loopId}')">保存</button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', dialogHtml);
}

window.closeAlarmConfigDialog = function() {
    const dialog = document.getElementById('alarmConfigDialog');
    if (dialog) dialog.remove();
}

window.saveAlarmThresholds = async function(loopId) {
    const high = parseFloat(document.getElementById('alarmHighThreshold').value);
    const low = parseFloat(document.getElementById('alarmLowThreshold').value);
    
    if (isNaN(high) || isNaN(low)) {
        showAlert('请输入有效的数值', 'warning');
        return;
    }
    
    if (low >= high) {
        showAlert('低限阈值必须小于高限阈值', 'warning');
        return;
    }
    
    try {
        await axios.put(`${window.API_BASE_URL}/api/loops/${loopId}`, {
            alarm_thresholds: { high, low }
        });
        
        showAlert('告警阈值保存成功', 'success');
        closeAlarmConfigDialog();
        await loadLoops();
    } catch (error) {
        console.error('保存告警阈值失败:', error);
        showAlert('保存失败', 'error');
    }
}

// ============================================================================
// 新增功能：性能趋势图
// ============================================================================

window.showPerformanceTrend = async function(loopId) {
    // 创建优化的进度提示元素
    const progressDiv = document.createElement('div');
    progressDiv.id = 'monitorJumpProgress';
    progressDiv.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(30, 41, 59, 0.98);
        padding: 35px 45px;
        border-radius: 16px;
        border: 2px solid rgba(102, 126, 234, 0.6);
        z-index: 10000;
        box-shadow: 0 12px 48px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.1);
        min-width: 320px;
        text-align: center;
        backdrop-filter: blur(10px);
        animation: fadeIn 0.2s ease-out;
    `;
    progressDiv.innerHTML = `
        <div style="color: #e2e8f0; font-size: 16px; margin-bottom: 18px;">
            <span style="font-size: 32px; display: block; margin-bottom: 12px; animation: pulse 1.5s ease-in-out infinite;">🚀</span>
            <span id="jumpProgressText" style="font-weight: 500;">正在跳转...</span>
        </div>
        <div style="width: 100%; height: 6px; background: rgba(148, 163, 184, 0.2); border-radius: 3px; overflow: hidden;">
            <div id="jumpProgressBar" style="width: 0%; height: 100%; background: linear-gradient(90deg, #667eea, #764ba2); transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);"></div>
        </div>
    `;
    
    // 添加CSS动画
    if (!document.getElementById('jumpProgressStyles')) {
        const style = document.createElement('style');
        style.id = 'jumpProgressStyles';
        style.textContent = `
            @keyframes fadeIn {
                from { opacity: 0; transform: translate(-50%, -45%); }
                to { opacity: 1; transform: translate(-50%, -50%); }
            }
            @keyframes pulse {
                0%, 100% { transform: scale(1); }
                50% { transform: scale(1.1); }
            }
        `;
        document.head.appendChild(style);
    }
    
    document.body.appendChild(progressDiv);
    
    const updateProgress = (percent, text) => {
        const progressBar = document.getElementById('jumpProgressBar');
        const progressText = document.getElementById('jumpProgressText');
        if (progressBar) {
            progressBar.style.width = `${Math.min(percent, 100)}%`;
        }
        if (progressText) {
            progressText.textContent = text;
            console.log(`📊 进度: ${percent}% - ${text}`);
        }
    };
    
    // 错误处理函数
    const handleError = (error, step) => {
        console.error(`❌ 跳转失败 (${step}):`, error);
        const progress = document.getElementById('monitorJumpProgress');
        if (progress) {
            progress.innerHTML = `
                <div style="color: #ef4444; font-size: 16px; margin-bottom: 15px;">
                    <span style="font-size: 32px; display: block; margin-bottom: 10px;">❌</span>
                    <span style="font-weight: 500;">${step}失败</span>
                    <div style="font-size: 12px; color: #94a3b8; margin-top: 8px;">${error.message}</div>
                </div>
                <button onclick="document.getElementById('monitorJumpProgress').remove()" 
                    style="padding: 8px 20px; background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 6px; cursor: pointer; font-size: 14px;">
                    关闭
                </button>
            `;
        }
        showAlert(`${step}失败: ${error.message}`, 'error');
    };
    
    try {
        console.log('🎯 性能趋势跳转 - 回路ID:', loopId);
        
        // 设置全局标志：从最新数据开始
        if (typeof window.shouldStartFromLatest !== 'undefined') {
            window.shouldStartFromLatest = true;
        }
        
        updateProgress(5, '准备切换页面...');
        
        // 1. 切换到实时监控标签页
        const monitoringTab = document.querySelector('[data-tab="monitoring"]');
        if (!monitoringTab) {
            throw new Error('找不到实时监控标签页');
        }
        
        // 添加平滑过渡效果
        const currentTab = document.querySelector('.tab-button.active');
        if (currentTab) {
            currentTab.style.transition = 'all 0.3s ease';
        }
        
        monitoringTab.click();
        updateProgress(15, '正在切换页面...');
        
        // 2. 等待DOM更新和动画完成
        await new Promise(resolve => setTimeout(resolve, 150));
        updateProgress(25, '页面切换完成');
        
        // 3. 选择目标回路
        const loopSelect = document.getElementById('monitorLoopSelect');
        if (!loopSelect) {
            throw new Error('找不到回路选择器');
        }
        
        // 检查回路是否存在
        const targetOption = Array.from(loopSelect.options).find(opt => opt.value === loopId);
        if (!targetOption) {
            throw new Error('目标回路不存在，请刷新回路列表');
        }
        
        updateProgress(35, `正在选择回路: ${targetOption.text}`);
        
        // 添加选择动画效果
        loopSelect.style.transition = 'all 0.3s ease';
        loopSelect.style.transform = 'scale(1.02)';
        
        loopSelect.value = loopId;
        loopSelect.dispatchEvent(new Event('change', { bubbles: true }));
        
        setTimeout(() => {
            loopSelect.style.transform = 'scale(1)';
        }, 200);
        
        console.log(`✅ 已选择回路: ${loopId} (${targetOption.text})`);
        updateProgress(45, '已选择目标回路');
        
        // 4. 等待回路选择完成
        await new Promise(resolve => setTimeout(resolve, 200));
        
        // 5. 智能处理现有监控状态
        const stopMonitorBtn = document.getElementById('stopMonitorBtn');
        const deleteMonitorBtn = document.getElementById('deleteMonitorBtn');
        const createMonitorBtn = document.getElementById('createMonitorBtn');
        const startMonitorBtn = document.getElementById('startMonitorBtn');
        
        // 检查是否有正在运行的监控
        const isMonitorRunning = stopMonitorBtn && !stopMonitorBtn.disabled;
        const hasMonitor = deleteMonitorBtn && !deleteMonitorBtn.disabled;
        
        if (isMonitorRunning) {
            console.log('⏸️  停止现有监控...');
            updateProgress(50, '停止现有监控...');
            stopMonitorBtn.click();
            await new Promise(resolve => setTimeout(resolve, 250));
            updateProgress(55, '监控已停止');
        }
        
        if (hasMonitor) {
            console.log('🗑️  清理旧监控...');
            updateProgress(60, '清理旧监控...');
            deleteMonitorBtn.click();
            await new Promise(resolve => setTimeout(resolve, 250));
            updateProgress(65, '清理完成');
        }
        
        updateProgress(70, '准备创建监控...');
        
        // 6. 创建新监控
        if (!createMonitorBtn) {
            throw new Error('找不到创建监控按钮');
        }
        
        console.log('🔧 创建监控实例...');
        updateProgress(75, '创建监控实例...');
        createMonitorBtn.click();
        
        // 7. 等待监控创建完成（优化的轮询检测）
        let retries = 0;
        const maxRetries = 15;
        const checkInterval = 150;
        
        while (retries < maxRetries) {
            await new Promise(resolve => setTimeout(resolve, checkInterval));
            
            // 检查按钮状态
            const currentStartBtn = document.getElementById('startMonitorBtn');
            if (currentStartBtn && !currentStartBtn.disabled) {
                console.log('✅ 监控实例就绪');
                break;
            }
            
            retries++;
            const progress = 75 + (retries / maxRetries) * 15;
            updateProgress(progress, `等待监控就绪... (${retries}/${maxRetries})`);
        }
        
        if (retries >= maxRetries) {
            throw new Error('监控创建超时，请稍后重试');
        }
        
        console.log('✅ 监控实例创建成功');
        updateProgress(92, '监控创建成功');
        
        // 8. 启动监控
        const finalStartBtn = document.getElementById('startMonitorBtn');
        if (finalStartBtn && !finalStartBtn.disabled) {
            console.log('▶️  启动实时监控...');
            updateProgress(95, '启动监控...');
            finalStartBtn.click();
            
            // 等待监控启动
            await new Promise(resolve => setTimeout(resolve, 250));
            
            updateProgress(100, '✨ 完成！');
            
            const loopName = loopSelect.options[loopSelect.selectedIndex].text;
            console.log(`🎉 成功启动回路 "${loopName}" 的实时监控`);
            
            // 添加成功动画
            const progress = document.getElementById('monitorJumpProgress');
            if (progress) {
                progress.style.transition = 'all 0.3s ease';
                progress.style.opacity = '0';
                progress.style.transform = 'translate(-50%, -45%) scale(0.95)';
                
                setTimeout(() => {
                    progress.remove();
                }, 300);
            }
            
            // 显示成功提示
            setTimeout(() => {
                showAlert(`✅ 已启动 "${loopName}" 的实时监控`, 'success');
            }, 200);
        } else {
            // 移除进度条
            const progress = document.getElementById('monitorJumpProgress');
            if (progress) {
                progress.style.opacity = '0';
                setTimeout(() => progress.remove(), 300);
            }
            showAlert('监控已在运行中', 'info');
        }
        
        return;
        
        // 以下是原来的性能趋势对话框代码（已注释，如需恢复可取消注释）
        /*
        const response = await axios.get(`${window.API_BASE_URL}/api/loops/${loopId}/performance-history`);
        
        if (!response.data.success || !response.data.history || response.data.history.length === 0) {
            showAlert('暂无性能历史数据', 'info');
            return;
        }
        
        const history = response.data.history;
        const loop = allLoops.find(l => l.id === loopId);
        
        const dialogHtml = `
            <div id="performanceTrendDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center;">
                <div style="background: #1e293b; padding: 30px; border-radius: 12px; max-width: 800px; width: 90%; border: 1px solid rgba(102, 126, 234, 0.3);">
                    <h3 style="color: #e2e8f0; margin-bottom: 20px;">📈 性能趋势 - ${loop.name}</h3>
                    
                    <canvas id="performanceTrendChart" style="max-height: 400px;"></canvas>
                    
                    <div style="display: flex; gap: 10px; justify-content: flex-end; margin-top: 20px;">
                        <button class="btn btn-secondary" onclick="closePerformanceTrendDialog()">关闭</button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', dialogHtml);
        
        // 绘制趋势图
        const ctx = document.getElementById('performanceTrendChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: history.map(h => new Date(h.timestamp).toLocaleString()),
                datasets: [
                    {
                        label: '综合评分',
                        data: history.map(h => h.score),
                        borderColor: '#667eea',
                        backgroundColor: 'rgba(102, 126, 234, 0.1)',
                        tension: 0.4
                    },
                    {
                        label: '稳态误差',
                        data: history.map(h => h.steady_error * 100),
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245, 158, 11, 0.1)',
                        tension: 0.4,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                scales: {
                    y: {
                        type: 'linear',
                        display: true,
                        position: 'left',
                        title: { display: true, text: '评分', color: '#e2e8f0' },
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(148, 163, 184, 0.1)' }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: { display: true, text: '误差 (%)', color: '#e2e8f0' },
                        ticks: { color: '#94a3b8' },
                        grid: { drawOnChartArea: false }
                    },
                    x: {
                        ticks: { color: '#94a3b8' },
                        grid: { color: 'rgba(148, 163, 184, 0.1)' }
                    }
                },
                plugins: {
                    legend: {
                        labels: { color: '#e2e8f0' }
                    }
                }
            }
        });
    } catch (error) {
        console.error('获取性能趋势失败:', error);
        showAlert('获取性能趋势失败', 'error');
    }
    */
    } catch (error) {
        handleError(error, '跳转');
        console.error('❌ 跳转到实时监控失败:', error);
        console.error('错误堆栈:', error.stack);
        
        // 移除进度条
        const progress = document.getElementById('monitorJumpProgress');
        if (progress) progress.remove();
        
        // 提供详细的错误信息和建议
        let errorMsg = '跳转失败';
        if (error.message.includes('找不到')) {
            errorMsg = `${error.message}，请刷新页面后重试`;
        } else if (error.message.includes('超时')) {
            errorMsg = '监控创建超时，请检查网络连接或稍后重试';
        } else if (error.message.includes('不存在')) {
            errorMsg = error.message;
        } else {
            errorMsg = `跳转失败: ${error.message}`;
        }
        
        showAlert(errorMsg, 'error');
    }
}

window.closePerformanceTrendDialog = function() {
    const dialog = document.getElementById('performanceTrendDialog');
    if (dialog) dialog.remove();
}

// ============================================================================
// 新增功能：批量备份与恢复
// ============================================================================

window.backupAllLoops = async function() {
    try {
        const response = await axios.get(`${window.API_BASE_URL}/api/loops`);
        if (!response.data.success) {
            showAlert('获取回路数据失败', 'error');
            return;
        }
        
        const backupData = {
            version: '1.0',
            timestamp: new Date().toISOString(),
            total_loops: response.data.loops.length,
            loops: response.data.loops
        };
        
        const dataStr = JSON.stringify(backupData, null, 2);
        const dataBlob = new Blob([dataStr], { type: 'application/json' });
        const url = URL.createObjectURL(dataBlob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `loops_backup_${Date.now()}.json`;
        
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        
        showAlert(`已备份 ${backupData.total_loops} 个回路`, 'success');
    } catch (error) {
        console.error('备份失败:', error);
        showAlert('备份失败', 'error');
    }
}

window.importLoops = function() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            
            if (!data.loops || !Array.isArray(data.loops)) {
                showAlert('无效的备份文件格式', 'error');
                return;
            }
            
            if (!confirm(`确定要导入 ${data.loops.length} 个回路吗？`)) {
                return;
            }
            
            let successCount = 0;
            let failCount = 0;
            
            for (const loop of data.loops) {
                try {
                    // 移除ID，让后端生成新ID
                    const { id, ...loopData } = loop;
                    loopData.name = loopData.name + ' (导入)';
                    
                    const response = await axios.post(`${window.API_BASE_URL}/api/loops`, loopData);
                    if (response.data.success) {
                        successCount++;
                    } else {
                        failCount++;
                    }
                } catch (error) {
                    console.error('导入回路失败:', error);
                    failCount++;
                }
            }
            
            showAlert(`导入完成！成功: ${successCount}, 失败: ${failCount}`, 'success');
            await loadLoops();
        } catch (error) {
            console.error('解析备份文件失败:', error);
            showAlert('解析备份文件失败', 'error');
        }
    };
    
    input.click();
}
