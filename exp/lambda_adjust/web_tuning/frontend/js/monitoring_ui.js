/**
 * Monitoring UI - 实时监控界面逻辑
 */

console.log(' monitoring_ui.js ');

// API基础URL
const apiBaseUrl = window.API_BASE_URL || 'http://localhost:8000';

// 全局变量
let monitoringManager = null;
let alarmManager = null;
let performanceTracker = null;
let currentLoopId = null;
let currentLoopInfo = null;  // 当前回路信息（包含整定结果和模型参数）
let realtimeChart = null;  // 实时图表
let performanceTrendChart = null;  // 性能趋势图表
let chartData = {
    time: [],
    pv: [],
    sv: [],
    mv: [],
    simulated_pv: [],  // 新增：仿真PV数据
    steady_states: [],  // 稳态标记
    param_updates: [],  // 参数更新标记
    convergence_zones: []  // 收敛区域标记
};
let performanceHistory = {
    timestamps: [],
    scores: [],
    errors: [],
    oscillations: []
};
const MAX_CHART_POINTS = 100;  // 图表最多显示100个点
const MAX_PERFORMANCE_POINTS = 100;  // 性能趋势最多显示100个点

// 仿真相关变量
let simulationState = {
    lastPV: null,
    lastMV: null,
    integral: 0,
    lastError: 0,
    lastTime: null,
    delayBuffer: [],  // 延迟缓冲区
    paramUpdateTime: null,  // 参数更新时刻
    convergenceStartTime: null,  // 开始收敛时刻
    isConverged: false  // 是否已收敛
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initMonitoringUI();
    initRealtimeChart();
    initPerformanceTrendChart();
});

function initMonitoringUI() {
    // 初始化管理器
    monitoringManager = new MonitoringManager();
    alarmManager = new AlarmManager();
    performanceTracker = new PerformanceTracker();
    
    // 加载回路列表
    loadLoopsForMonitoring();
    
    // 绑定事件
    bindMonitoringEvents();
}

// 加载回路列表到下拉框
async function loadLoopsForMonitoring() {
    try {
        const response = await fetch('http://localhost:8000/api/loops');
        const data = await response.json();
        
        const select = document.getElementById('monitorLoopSelect');
        select.innerHTML = '<option value="">-- 选择回路 --</option>';
        
        if (data.loops && data.loops.length > 0) {
            data.loops.forEach(loop => {
                const option = document.createElement('option');
                option.value = loop.id;
                option.textContent = `${loop.name} (${loop.area || '未分类'})`;
                select.appendChild(option);
            });
            console.log('✅ 成功加载回路列表:', data.loops.length, '个回路');
        }
    } catch (error) {
        console.error('❌ 加载回路列表失败:', error);
        
        // 临时方案：手动添加一些测试回路选项
        const select = document.getElementById('monitorLoopSelect');
        select.innerHTML = `
            <option value="">-- 选择回路 --</option>
            <option value="test">test (默认区域)</option>
            <option value="tmp">tmp (默认区域)</option>
            <option value="demo">demo (默认区域)</option>
        `;
        console.log('🔧 使用临时回路列表');
        showNotification('后端API不可用，使用临时回路列表', 'warning');
    }
}

// 绑定事件
function bindMonitoringEvents() {
    // 刷新回路列表
    document.getElementById('refreshLoopsBtn').addEventListener('click', loadLoopsForMonitoring);
    
    // 创建监控
    document.getElementById('createMonitorBtn').addEventListener('click', createMonitor);
    
    // 启动监控
    document.getElementById('startMonitorBtn').addEventListener('click', startMonitor);
    
    // 停止监控
    document.getElementById('stopMonitorBtn').addEventListener('click', stopMonitor);
    
    // 删除监控
    document.getElementById('deleteMonitorBtn').addEventListener('click', deleteMonitor);
    
    // 配置报警
    document.getElementById('configureAlarmBtn').addEventListener('click', showAlarmConfig);
    
    // 保存报警配置
    document.getElementById('saveAlarmConfigBtn').addEventListener('click', saveAlarmConfig);
    
    // 取消报警配置
    document.getElementById('cancelAlarmConfigBtn').addEventListener('click', hideAlarmConfig);
}

// 创建监控
async function createMonitor() {
    const loopId = document.getElementById('monitorLoopSelect').value;
    const loopName = document.getElementById('monitorLoopSelect').selectedOptions[0]?.textContent;
    const samplingInterval = parseFloat(document.getElementById('samplingInterval').value);
    
    if (!loopId) {
        alert('请选择回路');
        return;
    }
    
    try {
        // 先检查是否已存在
        const statusResult = await monitoringManager.getMonitorStatus(loopId);
        
        if (statusResult.success && statusResult.exists) {
            // 实例已存在，直接使用
            currentLoopId = loopId;
            
            // 启用按钮
            document.getElementById('startMonitorBtn').disabled = false;
            document.getElementById('deleteMonitorBtn').disabled = false;
            
            // 如果已经在运行，启用停止按钮
            if (statusResult.status === 'running') {
                document.getElementById('startMonitorBtn').disabled = true;
                document.getElementById('stopMonitorBtn').disabled = false;
                
                // 启动自动更新和模拟数据
                const updateInterval = parseInt(document.getElementById('updateInterval').value);
                startAutoUpdate(updateInterval);
                startSimulatedData();
            }
            
            showNotification('监控实例已存在，已加载', 'info');
            return;
        }
        
        // 创建新的监控实例
        const result = await monitoringManager.createMonitor(loopId, loopName, samplingInterval);
        
        if (result.success) {
            currentLoopId = loopId;
            
            // 创建性能跟踪器
            await performanceTracker.createTracker(loopId, loopName, {
                ise: 50.0,
                overshoot: 5.0,
                settling_time: 100
            });
            
            // 配置默认报警
            await configureDefaultAlarms(loopId);
            
            // 启用按钮
            document.getElementById('startMonitorBtn').disabled = false;
            document.getElementById('deleteMonitorBtn').disabled = false;
            
            showNotification('监控创建成功', 'success');
        } else {
            // 如果是"已存在"错误，也当作成功处理
            if (result.error && result.error.includes('已存在')) {
                currentLoopId = loopId;
                document.getElementById('startMonitorBtn').disabled = false;
                document.getElementById('deleteMonitorBtn').disabled = false;
                showNotification('监控实例已存在，已加载', 'info');
            } else {
                showNotification('创建失败: ' + result.error, 'error');
            }
        }
    } catch (error) {
        console.error('创建监控失败:', error);
        showNotification('创建失败: ' + error.message, 'error');
    }
}

// 启动监控（优化版）
async function startMonitor() {
    if (!currentLoopId) {
        showNotification('请先选择回路', 'warning');
        return;
    }
    
    try {
        // 显示加载状态
        showNotification('正在启动监控...', 'info');
        
        const result = await monitoringManager.startMonitor(currentLoopId);
        
        if (!result.success) {
            showNotification('启动失败: ' + result.error, 'error');
            return;
        }
        
        // 更新按钮状态
        updateMonitorButtons('running');
        
        // 启动自动更新
        const updateInterval = parseInt(document.getElementById('updateInterval').value) || 1000;
        startAutoUpdate(updateInterval);
        
        // 获取回路信息并启动相应的数据源
        const loopInfo = await getLoopInfo(currentLoopId);
        const dataSource = determineDataSource(loopInfo);
        
        await startDataSource(dataSource, loopInfo);
        
    } catch (error) {
        console.error('启动监控失败:', error);
        showNotification('启动失败: ' + error.message, 'error');
        updateMonitorButtons('stopped');
    }
}

// 更新监控按钮状态
function updateMonitorButtons(status) {
    const startBtn = document.getElementById('startMonitorBtn');
    const stopBtn = document.getElementById('stopMonitorBtn');
    const deleteBtn = document.getElementById('deleteMonitorBtn');
    
    if (status === 'running') {
        if (startBtn) startBtn.disabled = true;
        if (stopBtn) stopBtn.disabled = false;
        if (deleteBtn) deleteBtn.disabled = false;
    } else if (status === 'stopped') {
        if (startBtn) startBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = true;
        if (deleteBtn) deleteBtn.disabled = false;
    } else if (status === 'initial') {
        if (startBtn) startBtn.disabled = true;
        if (stopBtn) stopBtn.disabled = true;
        if (deleteBtn) deleteBtn.disabled = true;
    }
}

// 判断数据源类型
function determineDataSource(loopInfo) {
    // 优先级：全局JSON数据 > OPC UA > 文件 > 模拟
    console.log('🔍 判断数据源类型...');
    console.log('  - window.uploadedData:', window.uploadedData ? `${window.uploadedData.length}个点` : '无');
    console.log('  - loopInfo.data_source:', loopInfo?.data_source);
    
    if (window.uploadedData && window.uploadedData.length > 0) {
        console.log('✅ 使用数据源: global_json');
        return 'global_json';
    }
    if (loopInfo && loopInfo.data_source === 'opcua') {
        console.log('✅ 使用数据源: opcua');
        return 'opcua';
    }
    if (loopInfo && loopInfo.data_source === 'file') {
        console.log('✅ 使用数据源: file');
        return 'file';
    }
    console.log('✅ 使用数据源: simulated');
    return 'simulated';
}

// 启动数据源
async function startDataSource(dataSource, loopInfo) {
    // 检查全局标志
    const startFromLatest = window.shouldStartFromLatest || false;
    console.log(`🔍 检查全局标志 shouldStartFromLatest: ${startFromLatest}`);
    
    // 重置标志
    if (startFromLatest) {
        window.shouldStartFromLatest = false;
        console.log('🔄 已重置全局标志');
    }
    
    switch (dataSource) {
        case 'global_json':
        case 'file':
            console.log(`🎯 启动JSON数据源: ${dataSource}, startFromLatest: ${startFromLatest}`);
            await startJSONDataPlayback(startFromLatest);
            showNotification('监控已启动 (实时数据)', 'success');
            break;
            
        case 'opcua':
            console.log('🔌 启动OPC UA数据源');
            await startOPCUADataSource(loopInfo);
            showNotification('监控已启动 (OPC UA)', 'success');
            break;
            
        case 'simulated':
            console.log('🎲 启动模拟数据源');
            startSimulatedData();
            showNotification('监控已启动 (模拟数据)', 'success');
            break;
            
        default:
            throw new Error('未知的数据源类型: ' + dataSource);
    }
}

// 启动OPC UA数据源（提取为独立函数）
async function startOPCUADataSource(loopInfo) {
    const opcuaConfig = loopInfo?.opcua_config || {};
    const isCollecting = opcuaConfig.is_collecting;
    
    if (!isCollecting) {
        console.warn('⚠️  OPC UA采集未启动，尝试自动启动...');
        showNotification('OPC UA采集未启动，正在启动...', 'warning');
        
        try {
            if (typeof window.startOPCUACollection === 'function') {
                await window.startOPCUACollection(currentLoopId);
                console.log('✅ OPC UA采集已启动');
                await new Promise(resolve => setTimeout(resolve, 1000));
            } else {
                throw new Error('startOPCUACollection 函数未定义');
            }
        } catch (error) {
            console.error('❌ 启动OPC UA采集失败:', error);
            throw new Error('无法启动OPC UA采集: ' + error.message);
        }
    }
    
    startOPCUADataSync();
}

// 原来的代码继续...
// 旧的startMonitor代码已被优化重构

// 获取回路信息（包含整定结果和模型参数）
async function getLoopInfo(loopId) {
    try {
        const response = await fetch(`${apiBaseUrl}/api/loops/${loopId}`);
        const result = await response.json();
        if (result.success) {
            currentLoopInfo = result.loop;
            console.log('📊 获取到回路信息:', currentLoopInfo);
            
            // 只在仿真未运行时重置状态
            if (simulationState.lastPV === null) {
                resetSimulationState();
            }
            
            return currentLoopInfo;
        }
        return null;
    } catch (error) {
        console.error('获取回路信息失败:', error);
        
        // 备用方案：从全局变量获取回路信息
        if (typeof window.getAllLoops === 'function') {
            const allLoops = window.getAllLoops();
            const loop = allLoops.find(l => l.id === loopId || l.name === loopId);
            if (loop) {
                currentLoopInfo = loop;
                console.log('📊 从全局变量获取到回路信息:', currentLoopInfo);
                
                // 只在仿真未运行时重置状态
                if (simulationState.lastPV === null) {
                    resetSimulationState();
                }
                
                return currentLoopInfo;
            }
        }
        
        // 如果还是没有，创建一个基本的回路信息对象
        currentLoopInfo = {
            id: loopId,
            name: loopId,
            data_source: 'file',
            pid_params: null,  // 等待整定完成后更新
            model_params: null
        };
        
        // 尝试从全局变量加载最新的整定参数
        if (window.latestTuningParams) {
            currentLoopInfo.pid_params = window.latestTuningParams.pid_params;
            currentLoopInfo.model_params = window.latestTuningParams.model_params;
            console.log('✅ 从全局变量加载了最新的整定参数:', window.latestTuningParams);
        }
        
        console.log('⚠️ 创建临时回路信息对象:', currentLoopInfo);
        
        // 只在仿真未运行时重置状态
        if (simulationState.lastPV === null) {
            resetSimulationState();
        }
        
        return currentLoopInfo;
    }
}

// 重置仿真状态
function resetSimulationState() {
    simulationState = {
        lastPV: null,
        lastMV: null,
        integral: 0,
        lastError: 0,
        lastTime: null
    };
}

// 更新回路的整定参数（当整定完成后调用）
function updateLoopTuningParams(pidParams, modelParams) {
    // 如果当前没有回路信息，创建一个临时对象
    if (!currentLoopInfo) {
        currentLoopInfo = {
            id: 'temp',
            name: '临时回路',
            data_source: 'file',
            pid_params: null,
            model_params: null
        };
        console.log('⚠️ 创建临时回路信息以保存整定参数');
    }
    
    currentLoopInfo.pid_params = pidParams;
    currentLoopInfo.model_params = modelParams;
    console.log('🎯 回路整定参数已更新:', pidParams);
    console.log('🎯 回路模型参数已更新:', modelParams);
    
    // 同时保存到全局变量，供后续使用
    window.latestTuningParams = {
        pid_params: pidParams,
        model_params: modelParams,
        timestamp: Date.now()
    };
    console.log('💾 整定参数已保存到全局变量');
    
    // 只在第一次设置参数时重置仿真状态
    // 如果仿真已经在运行，不要重置，让它继续
    if (simulationState.lastPV === null) {
        console.log('🔄 首次设置参数，重置仿真状态');
        resetSimulationState();
    } else {
        console.log('✅ 参数已更新，仿真继续运行（不重置状态）');
    }
    
    showNotification('整定参数已更新，仿真PV将持续显示', 'success');
}

// 暴露函数供其他模块调用
window.updateLoopTuningParams = updateLoopTuningParams;

// 测试函数：手动设置测试参数
window.testSimulationParams = function(pb = 100.0, ti = 10.0, td = 2.0) {
    console.log('🧪 设置测试仿真参数');
    const pidParams = { pb, ti, td };
    const modelParams = [1.0, 10.0, 1.0]; // K, tau, L
    
    // 使用updateLoopTuningParams函数来设置参数
    updateLoopTuningParams(pidParams, modelParams);
    
    console.log('✅ 测试参数已设置:', { pidParams, modelParams });
    console.log('💡 提示：如果仿真PV还是不显示，请检查监控是否已启动');
};

// 调试函数：查看当前状态
window.debugSimulationState = function() {
    console.log('🔍 当前仿真状态:', {
        currentLoopInfo,
        simulationState,
        latestTuningParams: window.latestTuningParams,
        chartData: {
            pv_length: chartData.pv.length,
            simulated_pv_length: chartData.simulated_pv.length,
            last_5_simulated: chartData.simulated_pv.slice(-5)
        }
    });
};

// 模拟数据生成（用于演示）
let simulationInterval = null;
function startSimulatedData() {
    if (simulationInterval) {
        clearInterval(simulationInterval);
    }
    
    let time = 0;
    let setpoint = 25.0;
    
    // 如果是基于JSON数据的回路，使用更真实的数据模式
    const isJSONBasedLoop = currentLoopInfo && currentLoopInfo.data_source === 'file';
    
    simulationInterval = setInterval(async () => {
        if (isJSONBasedLoop) {
            // 基于JSON数据的回路：模拟更真实的工业过程
            // 添加设定值变化
            if (time === 50) setpoint = 30.0;  // 50秒时设定值变化
            if (time === 150) setpoint = 20.0; // 150秒时再次变化
            
            // 模拟实际PV响应（带有延迟和惯性）
            const noise = (Math.random() - 0.5) * 0.3;
            const disturbance = time > 100 && time < 120 ? 5.0 : 0; // 100-120秒有扰动
            
            // 简单的一阶惯性响应
            const tau = 15.0; // 时间常数
            const K = 0.8;    // 增益
            const dt = 1.0;
            
            const steadyPV = simulationState.lastPV || setpoint;
            const alpha = dt / (tau + dt);
            const pv = steadyPV + alpha * K * (setpoint - steadyPV) + noise + disturbance;
            
            const mv = 50 + (setpoint - pv) * 2 + Math.sin(time / 10) * 3; // 简单的控制器响应
            
            simulationState.lastPV = pv;
        } else {
            // 普通演示模式
            const noise = (Math.random() - 0.5) * 0.5;
            const trend = Math.sin(time / 20) * 2;
            const pv = setpoint + trend + noise;
            const mv = 45 + Math.sin(time / 15) * 10;
        }
        
        const finalPV = simulationState.lastPV || (setpoint + (Math.random() - 0.5) * 0.5);
        const finalMV = Math.max(0, Math.min(100, 50 + (setpoint - finalPV) * 2));
        
        // 添加数据点
        await monitoringManager.addDataPoint(
            currentLoopId,
            time,
            finalPV,
            setpoint,
            finalMV
        );
        
        // 更新图表
        updateRealtimeChart(time, finalPV, setpoint, finalMV);
        
        time += 1;
    }, 1000);
}

function stopSimulatedData() {
    if (simulationInterval) {
        clearInterval(simulationInterval);
        simulationInterval = null;
    }
}

// OPC UA数据同步
let opcuaSyncInterval = null;
let lastSyncedIndex = 0;

async function startOPCUADataSync() {
    if (opcuaSyncInterval) {
        clearInterval(opcuaSyncInterval);
    }
    
    lastSyncedIndex = 0;
    console.log('🔄 启动OPC UA数据同步，回路ID:', currentLoopId);
    
    // 立即执行一次同步，避免等待2秒
    await syncOPCUAData();
    
    // 每2秒从OPC UA采集数据中同步（降低频率）
    opcuaSyncInterval = setInterval(async () => {
        await syncOPCUAData();
    }, 2000); // 每2秒一次，降低请求频率
    
    console.log('✅ OPC UA数据同步已启动');
}

// OPC UA数据同步核心逻辑（提取为独立函数）
async function syncOPCUAData() {
    try {
        // 获取OPC UA采集的数据
        const response = await fetch(`${apiBaseUrl}/api/opcua/collected_data?loop_id=${currentLoopId}&limit=1000`);
        const result = await response.json();
        
        console.log('📊 OPC UA数据响应:', result);
        
        if (result.success && result.data) {
            const data = result.data;
            
            // 验证数据结构
            if (!data.pv || !Array.isArray(data.pv) || data.pv.length === 0) {
                console.warn('⚠️  暂无OPC UA数据，请确保采集已启动');
                console.log('📊 数据结构:', data);
                return;
            }
            
            const totalCount = data.pv.length;
            
            // 更新当前数据展示（最新的一个点）
            const lastIndex = totalCount - 1;
            const pv = data.pv[lastIndex];
            const sv = data.sv && data.sv[lastIndex] !== undefined ? data.sv[lastIndex] : 0;
            const mv = data.mv && data.mv[lastIndex] !== undefined ? data.mv[lastIndex] : 0;
            const time = (data.time && data.time[lastIndex]) || lastIndex;
            
            console.log(`📍 最新数据点: PV=${pv}, SV=${sv}, MV=${mv}, Time=${time}`);
            
            // 添加到监控系统
            await monitoringManager.addDataPoint(currentLoopId, time, pv, sv, mv);
            
            // 更新实时图表
            updateRealtimeChart(time, pv, sv, mv);
            
            // 同步新增数据点到图表（如果有未同步的历史数据）
            if (totalCount > lastSyncedIndex) {
                const newDataCount = totalCount - lastSyncedIndex;
                console.log(`📈 发现 ${newDataCount} 个新数据点，开始同步...`);
                
                // 批量同步新数据（避免一次性同步太多）
                const batchSize = Math.min(newDataCount, 50); // 每次最多同步50个点
                const startIdx = Math.max(lastSyncedIndex, totalCount - batchSize);
                
                for (let i = startIdx; i < totalCount - 1; i++) { // -1 因为最后一个点已经在上面处理了
                    const t = (data.time && data.time[i]) || i;
                    const p = data.pv[i];
                    const s = data.sv && data.sv[i] !== undefined ? data.sv[i] : 0;
                    const m = data.mv && data.mv[i] !== undefined ? data.mv[i] : 0;
                    
                    await monitoringManager.addDataPoint(currentLoopId, t, p, s, m);
                    updateRealtimeChart(t, p, s, m);
                }
                
                lastSyncedIndex = totalCount;
                console.log(`✅ 同步完成，当前索引: ${lastSyncedIndex}`);
            }
            
            // 手动触发一次实时数据显示更新（确保显示区域有内容）
            const monitorData = await monitoringManager.getRealtimeData(currentLoopId, 100);
            console.log('📊 获取监控数据用于显示:', monitorData);
            if (monitorData && monitorData.success) {
                updateRealtimeDisplay(monitorData);
                console.log('✅ 实时数据显示已更新');
            } else {
                console.warn('⚠️  获取监控数据失败，无法更新显示');
            }
            
        } else {
            console.warn('⚠️  OPC UA数据获取失败:', result.message || '未知错误');
        }
    } catch (error) {
        console.error('❌ OPC UA数据同步失败:', error);
    }
}

function stopOPCUADataSync() {
    if (opcuaSyncInterval) {
        clearInterval(opcuaSyncInterval);
        opcuaSyncInterval = null;
    }
    lastSyncedIndex = 0;
}

// JSON历史数据播放
let jsonPlaybackInterval = null;
let jsonDataIndex = 0;
let jsonHistoryData = null;

// 全局标志：是否从最新数据开始
let shouldStartFromLatest = false;
window.shouldStartFromLatest = shouldStartFromLatest;

async function startJSONDataPlayback(startFromLatest = false) {
    console.log(`🎬 startJSONDataPlayback 被调用，startFromLatest: ${startFromLatest}`);
    
    if (jsonPlaybackInterval) {
        clearInterval(jsonPlaybackInterval);
        console.log('🔄 清除旧的播放定时器');
    }
    
    // 如果是从最新数据开始，不清空现有图表数据
    if (!startFromLatest) {
        // 只有从头播放时才清空图表
        console.log('🧹 从头播放，清空图表');
        clearRealtimeChart();
    } else {
        console.log('🚀 从最新数据开始，不清空图表');
    }
    
    // 尝试从回路信息中获取原始数据，或从专门的API获取历史数据
    try {
        let historyData = null;
        
        // 方法0：尝试从全局变量获取当前上传的数据（临时方案）
        if (window.uploadedData && window.uploadedData.length > 0) {
            historyData = window.uploadedData;
            console.log('📊 从全局变量获取JSON数据，数据点数:', historyData.length);
        }
        // 方法1：尝试从回路信息中获取原始数据
        else if (currentLoopInfo && currentLoopInfo.original_data) {
            historyData = currentLoopInfo.original_data;
            console.log('📊 从回路信息获取原始数据，数据点数:', historyData.length);
        } else {
            console.log('🔍 检查回路信息:', currentLoopInfo);
            console.log('🔍 数据源类型:', currentLoopInfo?.data_source);
            console.log('🔍 原始数据:', currentLoopInfo?.original_data ? `${currentLoopInfo.original_data.length}个点` : '无数据');
            console.log('🔍 全局数据:', window.uploadedData ? `${window.uploadedData.length}个点` : '无数据');
            // 方法2：尝试从专门的API获取历史数据
            const response = await fetch(`${apiBaseUrl}/api/loops/${currentLoopId}/history_data`);
            const result = await response.json();
            
            if (result.success && result.data) {
                historyData = result.data;
                console.log('📊 从API获取历史数据，数据点数:', historyData.length);
            }
        }
        
        if (historyData && historyData.length > 0) {
            jsonHistoryData = historyData;
            
            // 根据参数决定从哪里开始
            if (startFromLatest) {
                // 从最新数据开始（倒数第50个点，或者从头开始如果数据不足50个）
                const startOffset = Math.max(0, historyData.length - 50);
                jsonDataIndex = startOffset;
                console.log(`🚀 从最新数据开始，起始索引: ${jsonDataIndex}/${historyData.length}`);
                
                // 先清空图表数据，确保从干净状态开始
                console.log('🧹 清空旧图表数据...');
                chartData.time = [];
                chartData.pv = [];
                chartData.sv = [];
                chartData.mv = [];
                chartData.sv_upper = [];
                chartData.sv_lower = [];
                chartData.simulated_pv = [];
                chartData.steady_states = [];
                
                // 快速填充前面的数据点到图表（优化版：批量处理）
                console.log('⚡ 快速填充最新50个数据点到图表...');
                const endIndex = Math.min(startOffset + 50, historyData.length);
                const fillCount = endIndex - startOffset;
                
                // 预分配数组空间（性能优化）
                const times = new Array(fillCount);
                const pvs = new Array(fillCount);
                const svs = new Array(fillCount);
                const mvs = new Array(fillCount);
                const svUppers = new Array(fillCount);
                const svLowers = new Array(fillCount);
                const steadyStates = new Array(fillCount);
                
                // 批量处理数据
                for (let i = 0; i < fillCount; i++) {
                    const dataPoint = historyData[startOffset + i];
                    const time = dataPoint.time || (startOffset + i);
                    const pv = dataPoint.pv;
                    const sv = dataPoint.sp || dataPoint.sv || dataPoint.setpoint;
                    const mv = dataPoint.mv;
                    
                    times[i] = time;
                    pvs[i] = pv;
                    svs[i] = sv;
                    mvs[i] = mv;
                    
                    // 计算容差带
                    const tolerance = Math.max(Math.abs(sv) * 0.03, 0.3);
                    svUppers[i] = sv + tolerance;
                    svLowers[i] = sv - tolerance;
                    steadyStates[i] = Math.abs(pv - sv) <= tolerance;
                }
                
                // 批量添加到chartData
                chartData.time.push(...times);
                chartData.pv.push(...pvs);
                chartData.sv.push(...svs);
                chartData.mv.push(...mvs);
                chartData.sv_upper.push(...svUppers);
                chartData.sv_lower.push(...svLowers);
                chartData.steady_states.push(...steadyStates);
                
                // 一次性更新图表（性能优化）
                if (realtimeChart) {
                    realtimeChart.data.labels = chartData.time;
                    realtimeChart.data.datasets[0].data = chartData.pv;
                    realtimeChart.data.datasets[2].data = chartData.sv;
                    realtimeChart.data.datasets[3].data = chartData.sv_upper;
                    realtimeChart.data.datasets[4].data = chartData.sv_lower;
                    realtimeChart.data.datasets[5].data = chartData.mv;
                    realtimeChart.update('none');
                }
                
                // 设置起始索引为已填充数据的下一个
                jsonDataIndex = Math.min(startOffset + 50, historyData.length);
                console.log(`✅ 已填充 ${fillCount} 个数据点`);
                console.log(`📍 图表当前显示范围: ${startOffset} - ${jsonDataIndex}`);
                console.log(`▶️  继续播放起始索引: ${jsonDataIndex}/${historyData.length}`);
                
                // 如果已经到达数据末尾，保持在最后一个点
                if (jsonDataIndex >= historyData.length) {
                    jsonDataIndex = historyData.length - 1;
                    console.log('⚠️  已到达数据末尾，保持在最后一个点');
                }
            } else {
                // 从头开始
                jsonDataIndex = 0;
                console.log('🔄 从头开始播放历史数据');
            }
            
            // 显示播放进度条
            const progressElement = document.getElementById('playbackProgress');
            if (progressElement) {
                progressElement.style.display = 'block';
                updatePlaybackProgress();
            }
            
            // 开始播放历史数据
            const speedMultiplier = parseFloat(document.getElementById('playbackSpeed').value) || 1.0;
            const playbackSpeed = Math.max(100, 1000 / speedMultiplier); // 根据倍速调整间隔
            
            console.log(`⏱️  播放速度: ${speedMultiplier}x, 间隔: ${playbackSpeed}ms`);
            console.log(`🎬 开始播放，当前索引: ${jsonDataIndex}/${jsonHistoryData.length}`);
            
            jsonPlaybackInterval = setInterval(async () => {
                if (jsonDataIndex >= jsonHistoryData.length) {
                    // 数据播放完毕
                    if (startFromLatest) {
                        // 如果是从最新数据开始的，停止播放（已经到末尾）
                        console.log('✅ 已播放到最新数据，停止播放');
                        clearInterval(jsonPlaybackInterval);
                        jsonPlaybackInterval = null;
                        return;
                    } else {
                        // 如果是从头播放的，循环播放
                        jsonDataIndex = 0;
                        console.log('🔄 历史数据播放完毕，重新开始');
                        resetSimulationState();
                    }
                }
                
                const dataPoint = jsonHistoryData[jsonDataIndex];
                const time = dataPoint.time || jsonDataIndex;
                const pv = dataPoint.pv;
                const sv = dataPoint.sp || dataPoint.sv || dataPoint.setpoint;
                const mv = dataPoint.mv;
                
                // 添加数据点到监控系统
                await monitoringManager.addDataPoint(
                    currentLoopId,
                    time,
                    pv,
                    sv,
                    mv
                );
                
                // 更新图表（包含仿真计算）
                updateRealtimeChart(time, pv, sv, mv);
                
                jsonDataIndex++;
                
                // 更新播放进度
                updatePlaybackProgress();
            }, playbackSpeed);
            
        } else {
            console.error('无法获取历史数据');
            console.log('🚨 回路信息获取失败，可能原因：');
            console.log('1. 后端API不可用');
            console.log('2. 回路ID不正确:', currentLoopId);
            console.log('3. 回路没有保存original_data');
            showNotification('无法获取历史数据，使用模拟数据', 'warning');
            startSimulatedData();
        }
    } catch (error) {
        console.error('获取历史数据失败:', error);
        showNotification('获取历史数据失败，使用模拟数据', 'warning');
        startSimulatedData();
    }
}

function stopJSONDataPlayback() {
    if (jsonPlaybackInterval) {
        clearInterval(jsonPlaybackInterval);
        jsonPlaybackInterval = null;
    }
    jsonDataIndex = 0;
    jsonHistoryData = null;
    
    // 隐藏播放进度条
    const progressElement = document.getElementById('playbackProgress');
    if (progressElement) {
        progressElement.style.display = 'none';
    }
}

// 更新播放进度
function updatePlaybackProgress() {
    if (!jsonHistoryData || jsonHistoryData.length === 0) return;
    
    const progressBar = document.getElementById('playbackProgressBar');
    const progressInfo = document.getElementById('playbackInfo');
    
    if (progressBar && progressInfo) {
        const progress = (jsonDataIndex / jsonHistoryData.length) * 100;
        progressBar.style.width = `${progress}%`;
        progressInfo.textContent = `${jsonDataIndex} / ${jsonHistoryData.length}`;
    }
}

// ============================================================================
// 实时图表功能
// ============================================================================

// 初始化性能趋势图表
function initPerformanceTrendChart() {
    const canvas = document.getElementById('performanceTrendChart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    performanceTrendChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: '评分',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.2)',
                    borderWidth: 3,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#10b981',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: '#fff',
                    pointHoverBorderColor: '#10b981',
                    yAxisID: 'y',
                    fill: true
                },
                {
                    label: '误差',
                    data: [],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.2)',
                    borderWidth: 3,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#f59e0b',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: '#fff',
                    pointHoverBorderColor: '#f59e0b',
                    yAxisID: 'y1',
                    fill: true
                },
                {
                    label: '振荡次数',
                    data: [],
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.2)',
                    borderWidth: 3,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: '#ef4444',
                    pointBorderColor: '#fff',
                    pointBorderWidth: 2,
                    pointHoverBackgroundColor: '#fff',
                    pointHoverBorderColor: '#ef4444',
                    yAxisID: 'y2',
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#e2e8f0',
                        font: { size: 13, weight: '600' },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 15,
                        boxWidth: 15,
                        boxHeight: 15
                    },
                    onHover: function(e) {
                        e.native.target.style.cursor = 'pointer';
                    },
                    onLeave: function(e) {
                        e.native.target.style.cursor = 'default';
                    }
                },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleColor: '#e2e8f0',
                    titleFont: { size: 14, weight: 'bold' },
                    bodyColor: '#cbd5e1',
                    bodyFont: { size: 13 },
                    borderColor: 'rgba(102, 126, 234, 0.6)',
                    borderWidth: 2,
                    padding: 15,
                    cornerRadius: 10,
                    displayColors: true,
                    boxWidth: 12,
                    boxHeight: 12,
                    boxPadding: 6,
                    callbacks: {
                        title: function(context) {
                            return '🕒 ' + context[0].label;
                        },
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                if (context.dataset.label === '评分') {
                                    label += context.parsed.y.toFixed(1) + ' 分';
                                } else if (context.dataset.label === '振荡次数') {
                                    label += context.parsed.y.toFixed(0) + ' 次';
                                } else {
                                    label += context.parsed.y.toFixed(3);
                                }
                            }
                            return label;
                        },
                        afterBody: function(context) {
                            const score = context[0].parsed.y;
                            if (context[0].dataset.label === '评分') {
                                let grade = '';
                                if (score >= 80) grade = 'A (优秀)';
                                else if (score >= 65) grade = 'B (良好)';
                                else if (score >= 50) grade = 'C (中等)';
                                else if (score >= 35) grade = 'D (合格)';
                                else grade = 'F (不合格)';
                                return ['', '🎯 等级: ' + grade];
                            }
                            return '';
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: '时间',
                        color: '#94a3b8'
                    },
                    grid: {
                        color: 'rgba(148, 163, 184, 0.1)'
                    },
                    ticks: {
                        color: '#94a3b8',
                        maxRotation: 45,
                        minRotation: 45
                    }
                },
                y: {
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: '评分',
                        color: '#10b981'
                    },
                    grid: {
                        color: 'rgba(148, 163, 184, 0.1)'
                    },
                    ticks: {
                        color: '#10b981'
                    },
                    min: 0,
                    max: 100
                },
                y1: {
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: '误差',
                        color: '#f59e0b'
                    },
                    grid: {
                        drawOnChartArea: false
                    },
                    ticks: {
                        color: '#f59e0b'
                    }
                },
                y2: {
                    display: false,
                    position: 'right',
                    grid: {
                        drawOnChartArea: false
                    }
                }
            }
        }
    });
}

// 初始化实时图表
function initRealtimeChart() {
    const canvas = document.getElementById('realtimeChart');
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    realtimeChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'PV (实际值)',
                    data: [],
                    borderColor: '#3b82f6',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    hidden: false,
                    order: 2,
                    segment: {
                        borderColor: ctx => {
                            const index = ctx.p0DataIndex;
                            if (chartData.steady_states[index]) {
                                return '#10b981'; // 稳态时绿色
                            }
                            return '#3b82f6'; // 非稳态时蓝色
                        },
                        borderWidth: ctx => {
                            const index = ctx.p0DataIndex;
                            return chartData.steady_states[index] ? 2.5 : 2;
                        }
                    }
                },
                {
                    label: 'PV (新参数预测)',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.15)',
                    borderWidth: 3,
                    tension: 0.4,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    hidden: false,
                    spanGaps: true,
                    order: 1,
                    segment: {
                        borderColor: ctx => {
                            const index = ctx.p0DataIndex;
                            // 如果在收敛区域，使用更亮的绿色
                            if (chartData.convergence_zones && chartData.convergence_zones[index]) {
                                return '#22c55e';
                            }
                            return '#10b981';
                        },
                        borderWidth: ctx => {
                            const index = ctx.p0DataIndex;
                            return chartData.convergence_zones && chartData.convergence_zones[index] ? 3.5 : 3;
                        }
                    }
                },
                {
                    label: 'SV (设定值)',
                    data: [],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.15)',
                    borderWidth: 2.5,
                    tension: 0,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    hidden: false,
                    order: 3
                },
                {
                    label: 'SV 容差带上限',
                    data: [],
                    borderColor: 'rgba(245, 158, 11, 0.3)',
                    backgroundColor: 'rgba(245, 158, 11, 0.08)',
                    borderWidth: 1,
                    borderDash: [3, 3],
                    tension: 0,
                    pointRadius: 0,
                    fill: '+1',
                    hidden: false,
                    order: 4
                },
                {
                    label: 'SV 容差带下限',
                    data: [],
                    borderColor: 'rgba(245, 158, 11, 0.3)',
                    backgroundColor: 'rgba(245, 158, 11, 0.08)',
                    borderWidth: 1,
                    borderDash: [3, 3],
                    tension: 0,
                    pointRadius: 0,
                    hidden: false,
                    order: 4
                },
                {
                    label: 'MV',
                    data: [],
                    borderColor: '#a78bfa',
                    backgroundColor: 'rgba(167, 139, 250, 0.15)',
                    borderWidth: 2.5,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    hidden: false,
                    yAxisID: 'y1',
                    order: 5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            interaction: {
                intersect: false,
                mode: 'index'
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: '#e2e8f0',
                        font: { size: 12, weight: '500' },
                        filter: function(item) {
                            return !item.text.includes('容差带');
                        },
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 12,
                        boxWidth: 12,
                        boxHeight: 12
                    },
                    onHover: function(e) {
                        e.native.target.style.cursor = 'pointer';
                    },
                    onLeave: function(e) {
                        e.native.target.style.cursor = 'default';
                    }
                },
                tooltip: {
                    enabled: true,
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleColor: '#e2e8f0',
                    titleFont: { size: 13, weight: 'bold' },
                    bodyColor: '#cbd5e1',
                    bodyFont: { size: 12 },
                    borderColor: 'rgba(102, 126, 234, 0.5)',
                    borderWidth: 2,
                    padding: 12,
                    cornerRadius: 8,
                    displayColors: true,
                    callbacks: {
                        title: function(context) {
                            return '时间: ' + context[0].label + 's';
                        },
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += context.parsed.y.toFixed(2);
                            }
                            return label;
                        },
                        afterBody: function(context) {
                            const index = context[0].dataIndex;
                            if (chartData.steady_states[index] !== undefined) {
                                const status = chartData.steady_states[index] ? '✅ 稳态' : '⚠️ 非稳态';
                                const pv = chartData.pv[index];
                                const sv = chartData.sv[index];
                                const error = Math.abs(pv - sv);
                                return [
                                    '',
                                    status,
                                    `误差: ${error.toFixed(3)}`
                                ];
                            }
                            return '';
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    title: {
                        display: true,
                        text: '时间 (s)',
                        color: '#94a3b8'
                    },
                    grid: {
                        color: 'rgba(148, 163, 184, 0.1)'
                    },
                    ticks: {
                        color: '#94a3b8'
                    }
                },
                y: {
                    display: true,
                    position: 'left',
                    title: {
                        display: true,
                        text: 'PV / SV',
                        color: '#94a3b8'
                    },
                    grid: {
                        color: 'rgba(148, 163, 184, 0.1)'
                    },
                    ticks: {
                        color: '#94a3b8'
                    }
                },
                y1: {
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: 'MV (%)',
                        color: '#94a3b8'
                    },
                    grid: {
                        drawOnChartArea: false
                    },
                    ticks: {
                        color: '#94a3b8'
                    }
                }
            }
        }
    });
    
    // 设置图表显示/隐藏控制
    setupChartControls();
}

// 设置图表控制
function setupChartControls() {
    const showPV = document.getElementById('showPV');
    const showSimulatedPV = document.getElementById('showSimulatedPV');
    const showSV = document.getElementById('showSV');
    const showMV = document.getElementById('showMV');
    
    if (showPV) {
        showPV.addEventListener('change', (e) => {
            realtimeChart.data.datasets[0].hidden = !e.target.checked;  // PV (实际数据)
            realtimeChart.update();
        });
    }
    
    if (showSimulatedPV) {
        showSimulatedPV.addEventListener('change', (e) => {
            realtimeChart.data.datasets[1].hidden = !e.target.checked;  // PV (新参数仿真)
            realtimeChart.update();
        });
    }
    
    if (showSV) {
        showSV.addEventListener('change', (e) => {
            realtimeChart.data.datasets[2].hidden = !e.target.checked;  // SV (设定值)
            realtimeChart.update();
        });
    }
    
    if (showMV) {
        showMV.addEventListener('change', (e) => {
            realtimeChart.data.datasets[5].hidden = !e.target.checked;  // MV (正确的索引)
            realtimeChart.update();
        });
    }
    
    // 添加容差带显示/隐藏控制
    const showToleranceBand = document.getElementById('showToleranceBand');
    if (showToleranceBand) {
        showToleranceBand.addEventListener('change', (e) => {
            realtimeChart.data.datasets[3].hidden = !e.target.checked;  // SV 容差带上限
            realtimeChart.data.datasets[4].hidden = !e.target.checked;  // SV 容差带下限
            realtimeChart.update();
        });
    }
}

// 计算仿真PV值（使用新的PID参数）- 优化版
function calculateSimulatedPV(time, sv, currentPV, actualMV = null) {
    // 只有当回路有整定结果时才进行仿真计算
    if (!currentLoopInfo || !currentLoopInfo.pid_params) {
        return null;
    }
    
    const pidParams = currentLoopInfo.pid_params;
    if (!pidParams.pb || !pidParams.ti || pidParams.td === undefined) {
        return null;
    }
    
    const dt = 1.0; // 时间步长（秒）
    
    // 初始化仿真状态
    if (simulationState.lastPV === null) {
        simulationState.lastPV = currentPV;
        simulationState.lastTime = time;
        simulationState.paramUpdateTime = time;
        console.log('🎯 仿真初始化:', {
            pidParams,
            modelParams: currentLoopInfo.model_params,
            initialPV: currentPV,
            initialSV: sv
        });
        return currentPV;
    }
    
    // PID参数
    const Kp = 100.0 / pidParams.pb;
    const Ki = pidParams.ti > 0 ? Kp / pidParams.ti : 0;
    const Kd = Kp * pidParams.td;
    
    // 模型参数（支持FOPDT和二阶模型）
    const modelParams = currentLoopInfo.model_params || [1.0, 10.0, 1.0];
    const modelType = currentLoopInfo.model_type || 'fopdt';
    
    let newPV;
    
    if (modelType === 'second_order' && modelParams.length >= 3) {
        // 二阶模型仿真
        const K = modelParams[0] || 1.0;
        const tau1 = modelParams[1] || 10.0;
        const tau2 = modelParams[2] || 5.0;
        
        // 计算误差和PID输出
        const error = sv - simulationState.lastPV;
        simulationState.integral += error * dt;
        
        // 抗积分饱和
        const integralMax = 100.0;
        simulationState.integral = Math.max(-integralMax, Math.min(integralMax, simulationState.integral));
        
        const derivative = simulationState.lastError !== null ? 
            (error - simulationState.lastError) / dt : 0;
        
        const mvOutput = Kp * error + Ki * simulationState.integral + Kd * derivative;
        const mvLimited = Math.max(0, Math.min(100, mvOutput));
        
        // 二阶系统响应（串联两个一阶惯性环节）
        const alpha1 = dt / (tau1 + dt);
        const alpha2 = dt / (tau2 + dt);
        
        // 使用实际MV或仿真MV
        const mv = actualMV !== null ? actualMV : mvLimited;
        
        // 第一个惯性环节
        const intermediate = simulationState.lastPV + alpha1 * K * (mv - simulationState.lastPV);
        // 第二个惯性环节
        newPV = intermediate + alpha2 * (intermediate - simulationState.lastPV);
        
        simulationState.lastMV = mvLimited;
        simulationState.lastError = error;
        
    } else {
        // FOPDT模型仿真（带延迟）
        const K = modelParams[0] || 1.0;
        const tau = modelParams[1] || 10.0;
        const L = modelParams[2] || 1.0;
        
        // 计算误差和PID输出
        const error = sv - simulationState.lastPV;
        simulationState.integral += error * dt;
        
        // 抗积分饱和
        const integralMax = 100.0;
        simulationState.integral = Math.max(-integralMax, Math.min(integralMax, simulationState.integral));
        
        const derivative = simulationState.lastError !== null ? 
            (error - simulationState.lastError) / dt : 0;
        
        const mvOutput = Kp * error + Ki * simulationState.integral + Kd * derivative;
        const mvLimited = Math.max(0, Math.min(100, mvOutput));
        
        // 延迟处理
        const delaySteps = Math.round(L / dt);
        simulationState.delayBuffer.push(mvLimited);
        
        if (simulationState.delayBuffer.length > delaySteps) {
            simulationState.delayBuffer.shift();
        }
        
        const delayedMV = simulationState.delayBuffer[0] || mvLimited;
        
        // 使用实际MV或延迟后的仿真MV
        const mv = actualMV !== null ? actualMV : delayedMV;
        
        // 一阶惯性环节
        const alpha = dt / (tau + dt);
        newPV = simulationState.lastPV + alpha * K * (mv / 100.0) * (sv - simulationState.lastPV);
        
        simulationState.lastMV = mvLimited;
        simulationState.lastError = error;
    }
    
    // 检测收敛状态
    const tolerance = Math.max(Math.abs(sv) * 0.03, 0.3);
    const isInTolerance = Math.abs(newPV - sv) <= tolerance;
    
    if (isInTolerance && !simulationState.isConverged) {
        if (simulationState.convergenceStartTime === null) {
            simulationState.convergenceStartTime = time;
        } else if (time - simulationState.convergenceStartTime > 10) {
            // 持续10秒在容差内才认为收敛
            simulationState.isConverged = true;
            const convergenceTime = time - (simulationState.paramUpdateTime || 0);
            console.log(`✅ 仿真曲线已收敛! 收敛时间: ${convergenceTime.toFixed(1)}s`);
        }
    } else if (!isInTolerance) {
        simulationState.convergenceStartTime = null;
    }
    
    // 更新状态
    simulationState.lastPV = newPV;
    simulationState.lastTime = time;
    
    return newPV;
}

// 更新图表数据
function updateRealtimeChart(time, pv, sv, mv) {
    if (!realtimeChart) return;
    
    // 计算仿真PV（只有在有整定参数时才计算）
    const simulatedPV = calculateSimulatedPV(time, sv, pv, mv);
    
    // 计算容差带（±3%的设定值，或绝对值0.3，取较大者）
    const tolerance = Math.max(Math.abs(sv) * 0.03, 0.3);
    const svUpper = sv + tolerance;
    const svLower = sv - tolerance;
    
    // 判断当前是否稳态
    const isSteady = Math.abs(pv - sv) <= tolerance;
    
    // 判断仿真曲线是否在收敛区域
    const isSimulatedConverging = simulatedPV !== null && 
        Math.abs(simulatedPV - sv) <= tolerance &&
        simulationState.convergenceStartTime !== null;
    
    // 添加新数据
    chartData.time.push(time);
    chartData.pv.push(pv);
    chartData.sv.push(sv);
    chartData.mv.push(mv);
    chartData.steady_states.push(isSteady);
    chartData.convergence_zones.push(isSimulatedConverging);
    
    // 只有当仿真PV有效时才添加到数据中
    if (simulatedPV !== null) {
        chartData.simulated_pv.push(simulatedPV);
    } else {
        chartData.simulated_pv.push(null); // 没有整定参数时推入null
    }
    
    // 限制数据点数量
    if (chartData.time.length > MAX_CHART_POINTS) {
        chartData.time.shift();
        chartData.pv.shift();
        chartData.sv.shift();
        chartData.mv.shift();
        chartData.simulated_pv.shift();
        chartData.steady_states.shift();
        chartData.convergence_zones.shift();
    }
    
    // 更新图表
    realtimeChart.data.labels = chartData.time;
    realtimeChart.data.datasets[0].data = chartData.pv;        // PV (实际数据)
    realtimeChart.data.datasets[1].data = chartData.simulated_pv; // PV (新参数仿真)
    realtimeChart.data.datasets[2].data = chartData.sv;        // SV (设定值)
    realtimeChart.data.datasets[3].data = chartData.sv.map(() => svUpper);  // 容差带上限
    realtimeChart.data.datasets[4].data = chartData.sv.map(() => svLower);  // 容差带下限
    realtimeChart.data.datasets[5].data = chartData.mv;        // MV
    realtimeChart.update('none');  // 'none'模式不使用动画，更流畅
    
    // 更新稳态指示器和收敛信息
    updateSteadyStateIndicator(isSteady, pv, sv, tolerance);
    updateConvergenceInfo(simulatedPV, sv, tolerance);
}

// 更新稳态指示器
function updateSteadyStateIndicator(isSteady, pv, sv, tolerance) {
    const indicator = document.getElementById('steadyStateIndicator');
    const icon = document.getElementById('steadyStateIcon');
    const text = document.getElementById('steadyStateText');
    
    if (!indicator || !icon || !text) return;
    
    const error = Math.abs(pv - sv);
    const errorPercent = (error / Math.abs(sv) * 100).toFixed(2);
    
    if (isSteady) {
        // 稳态
        icon.textContent = '✅';
        text.textContent = `稳态 (误差: ${errorPercent}%)`;
        text.style.color = '#10b981';
        indicator.style.borderColor = 'rgba(16, 185, 129, 0.5)';
        indicator.style.background = 'rgba(16, 185, 129, 0.1)';
    } else {
        // 非稳态
        icon.textContent = '⚠️';
        text.textContent = `非稳态 (误差: ${errorPercent}%)`;
        text.style.color = '#f59e0b';
        indicator.style.borderColor = 'rgba(245, 158, 11, 0.5)';
        indicator.style.background = 'rgba(245, 158, 11, 0.1)';
    }
}

// 更新收敛信息显示
function updateConvergenceInfo(simulatedPV, sv, tolerance) {
    const convergenceInfo = document.getElementById('convergenceInfo');
    if (!convergenceInfo) return;
    
    if (simulatedPV === null) {
        convergenceInfo.style.display = 'none';
        return;
    }
    
    convergenceInfo.style.display = 'block';
    const error = Math.abs(simulatedPV - sv);
    const isInTolerance = error <= tolerance;
    
    if (simulationState.isConverged) {
        const convergenceTime = simulationState.lastTime - (simulationState.paramUpdateTime || 0);
        convergenceInfo.innerHTML = `
            <span style="color: #22c55e;">✅ 新参数已收敛</span>
            <span style="color: #94a3b8; margin-left: 10px;">收敛时间: ${convergenceTime.toFixed(1)}s</span>
        `;
    } else if (isInTolerance && simulationState.convergenceStartTime !== null) {
        const timeInTolerance = simulationState.lastTime - simulationState.convergenceStartTime;
        convergenceInfo.innerHTML = `
            <span style="color: #10b981;">🔄 正在收敛...</span>
            <span style="color: #94a3b8; margin-left: 10px;">已稳定: ${timeInTolerance.toFixed(1)}s / 10s</span>
        `;
    } else {
        convergenceInfo.innerHTML = `
            <span style="color: #f59e0b;">⏳ 等待收敛</span>
            <span style="color: #94a3b8; margin-left: 10px;">误差: ${error.toFixed(3)}</span>
        `;
    }
}

// 更新性能趋势图表
function updatePerformanceTrend(performance) {
    if (!performanceTrendChart || !performance) return;
    
    const now = new Date().toLocaleTimeString();
    const score = performance.score || 0;
    const error = performance.steady_error || 0;
    const oscillations = performance.oscillation_count || 0;
    
    // 添加新数据
    performanceHistory.timestamps.push(now);
    performanceHistory.scores.push(score);
    performanceHistory.errors.push(error);
    performanceHistory.oscillations.push(oscillations);
    
    // 限制数据点数量
    if (performanceHistory.timestamps.length > MAX_PERFORMANCE_POINTS) {
        performanceHistory.timestamps.shift();
        performanceHistory.scores.shift();
        performanceHistory.errors.shift();
        performanceHistory.oscillations.shift();
    }
    
    // 更新图表
    performanceTrendChart.data.labels = performanceHistory.timestamps;
    performanceTrendChart.data.datasets[0].data = performanceHistory.scores;
    performanceTrendChart.data.datasets[1].data = performanceHistory.errors;
    performanceTrendChart.data.datasets[2].data = performanceHistory.oscillations;
    performanceTrendChart.update('none');
}

// 清空图表数据
function clearRealtimeChart(resetSimulation = false) {
    chartData.time = [];
    chartData.pv = [];
    chartData.sv = [];
    chartData.mv = [];
    chartData.simulated_pv = [];
    chartData.steady_states = [];
    chartData.param_updates = [];
    chartData.convergence_zones = [];
    
    if (realtimeChart) {
        realtimeChart.data.labels = [];
        realtimeChart.data.datasets[0].data = [];  // PV (实际数据)
        realtimeChart.data.datasets[1].data = [];  // PV (新参数仿真)
        realtimeChart.data.datasets[2].data = [];  // SV (设定值)
        realtimeChart.data.datasets[3].data = [];  // 容差带上限
        realtimeChart.data.datasets[4].data = [];  // 容差带下限
        realtimeChart.data.datasets[5].data = [];  // MV
        realtimeChart.update();
    }
    
    // 只在明确要求时才重置仿真状态
    // 这样可以保留整定参数，让仿真在重新启动时继续
    if (resetSimulation) {
        console.log('🔄 清空图表并重置仿真状态');
        resetSimulationState();
    } else {
        console.log('🔄 清空图表但保留仿真参数');
    }
}

// 重置仿真状态
function resetSimulationState() {
    simulationState.lastPV = null;
    simulationState.lastMV = null;
    simulationState.integral = 0;
    simulationState.lastError = 0;
    simulationState.lastTime = null;
    simulationState.delayBuffer = [];
    simulationState.paramUpdateTime = null;
    simulationState.convergenceStartTime = null;
    simulationState.isConverged = false;
    console.log('🔄 仿真状态已重置');
}

// 页面可见性变化处理（优化性能）
document.addEventListener('visibilitychange', function() {
    if (document.hidden) {
        // 页面隐藏时，降低请求频率
        console.log('📴 页面已隐藏，降低请求频率');
    } else {
        // 页面可见时，恢复正常频率
        console.log('📱 页面已显示，恢复正常频率');
    }
});

// 停止监控
async function stopMonitor() {
    console.log('⏸️  停止监控...');
    
    // 先停止所有定时器（即使没有currentLoopId）
    stopSimulatedData();
    stopOPCUADataSync();
    stopJSONDataPlayback();
    
    if (!currentLoopId) {
        console.log('⚠️  没有当前回路ID，仅清除定时器');
        return;
    }
    
    try {
        const result = await monitoringManager.stopMonitor(currentLoopId);
        
        if (result.success) {
            // 启用启动按钮，禁用停止按钮
            document.getElementById('startMonitorBtn').disabled = false;
            document.getElementById('stopMonitorBtn').disabled = true;
            
            // 停止自动更新
            monitoringManager.stopAutoUpdate(currentLoopId);
            
            // 清空图表
            clearRealtimeChart();
            
            console.log('✅ 监控已停止');
            showNotification('监控已停止', 'info');
        } else {
            showNotification('停止失败: ' + result.error, 'error');
        }
    } catch (error) {
        console.error('停止监控失败:', error);
        showNotification('停止失败: ' + error.message, 'error');
    }
}

// 删除监控
async function deleteMonitor() {
    console.log('🗑️  删除监控...');
    
    // 先停止所有定时器
    stopSimulatedData();
    stopOPCUADataSync();
    stopJSONDataPlayback();
    
    if (!currentLoopId) {
        console.log('⚠️  没有当前回路ID');
        return;
    }
    
    // 从showPerformanceTrend调用时不需要确认
    const needConfirm = !window.shouldStartFromLatest;
    if (needConfirm && !confirm('确定要删除此监控实例吗？')) {
        return;
    }
    
    try {
        const result = await monitoringManager.deleteMonitor(currentLoopId);
        
        if (result.success) {
            currentLoopId = null;
            
            // 重置按钮状态
            document.getElementById('startMonitorBtn').disabled = true;
            document.getElementById('stopMonitorBtn').disabled = true;
            document.getElementById('deleteMonitorBtn').disabled = true;
            
            // 清空显示
            document.getElementById('realtimeDataDisplay').innerHTML = 
                '<p style="color: #94a3b8; text-align: center; padding: 40px;">请先创建并启动监控...</p>';
            document.getElementById('alarmDisplay').innerHTML = 
                '<div class="no-alarms" style="color: #94a3b8; text-align: center; padding: 20px;">✅ 无报警</div>';
            document.getElementById('qualityAssessmentDisplay').innerHTML = 
                '<p style="color: #94a3b8; text-align: center; padding: 40px;">等待数据采集...</p>';
            
            console.log('✅ 监控已删除');
            if (needConfirm) {
                showNotification('监控已删除', 'info');
            }
        } else {
            showNotification('删除失败: ' + result.error, 'error');
        }
    } catch (error) {
        console.error('删除监控失败:', error);
        showNotification('删除失败: ' + error.message, 'error');
    }
}

// 启动自动更新
function startAutoUpdate(intervalMs) {
    monitoringManager.startAutoUpdate(currentLoopId, async (data) => {
        // 更新实时数据显示
        updateRealtimeDisplay(data);
        
        // 检查报警
        if (data.data && data.data.pv.length > 0) {
            await checkAlarms(data);
        }
        
        // 更新性能跟踪
        if (data.data && data.data.pv.length > 0) {
            await updatePerformanceTracking(data);
        }
    }, intervalMs);
}

// 更新实时数据显示
function updateRealtimeDisplay(data) {
    if (!data.success) return;
    
    const metrics = data.metrics || {};
    const stats = data.statistics || {};
    
    let html = '<div class="realtime-monitor">';
    html += `<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">`;
    html += `<h4 style="margin: 0; color: #e2e8f0; font-size: 20px;">${data.loop_name}</h4>`;
    html += `<span class="status-badge ${data.status}">${data.status === 'running' ? '运行中' : '已停止'}</span>`;
    html += `</div>`;
    
    // 当前值 - 使用新的metric-card样式
    html += '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">';
    html += createMetricCard('当前PV', metrics.current_pv?.toFixed(2) || 'N/A', '#3b82f6');
    html += createMetricCard('当前SV', metrics.current_sv?.toFixed(2) || 'N/A', '#10b981');
    html += createMetricCard('当前误差', metrics.current_error?.toFixed(2) || 'N/A', Math.abs(metrics.current_error) > 1 ? '#ef4444' : '#10b981');
    if (metrics.current_mv !== undefined) {
        html += createMetricCard('当前MV', metrics.current_mv.toFixed(2) + '%', '#f59e0b');
    }
    html += '</div>';
    
    // 统计指标 - 使用stats-grid样式
    html += '<div class="stats-grid">';
    html += '<h5 style="grid-column: 1 / -1; margin: 0 0 10px 0; color: #e2e8f0; font-size: 16px;">📈 统计指标</h5>';
    html += createStatItem('平均误差', metrics.mean_error?.toFixed(3) || 'N/A');
    html += createStatItem('误差标准差', metrics.std_error?.toFixed(3) || 'N/A');
    html += createStatItem('最大误差', metrics.max_abs_error?.toFixed(3) || 'N/A');
    html += createStatItem('IAE', metrics.iae?.toFixed(2) || 'N/A');
    html += createStatItem('ISE', metrics.ise?.toFixed(2) || 'N/A');
    if (metrics.is_steady !== undefined) {
        html += createStatItem('稳态', metrics.is_steady ? '✅ 是' : '❌ 否');
    }
    html += '</div>';
    
    // 采样统计 - 使用monitor-info-bar样式
    html += `<div class="monitor-info-bar">`;
    html += `<div class="info-item">📊 总采样数: <span class="info-value">${stats.total_samples || 0}</span></div>`;
    html += `<div class="info-item">🕐 最后更新: <span class="info-value">${stats.last_update ? new Date(stats.last_update).toLocaleTimeString() : 'N/A'}</span></div>`;
    html += `</div>`;
    
    html += '</div>';
    
    document.getElementById('realtimeDataDisplay').innerHTML = html;
}

// 创建指标卡片
function createMetricCard(label, value, color) {
    return `
        <div class="metric-card" style="border-left-color: ${color};">
            <div class="metric-label">${label}</div>
            <div class="metric-value">${value}</div>
        </div>
    `;
}

// 创建统计项
function createStatItem(label, value) {
    return `
        <div class="stat-item">
            <span class="stat-label">${label}</span>
            <span class="stat-value">${value}</span>
        </div>
    `;
}

// 检查报警
async function checkAlarms(data) {
    const lastIdx = data.data.pv.length - 1;
    
    const result = await alarmManager.checkAlarms(
        currentLoopId,
        data.data.pv[lastIdx],
        data.data.sv[lastIdx],
        data.data.mv[lastIdx],
        data.data.pv
    );
    
    if (result.success && result.alarms && result.alarms.length > 0) {
        displayAlarms(result.alarms);
    }
}

// 显示报警
function displayAlarms(alarms) {
    if (!alarms || alarms.length === 0) {
        document.getElementById('alarmDisplay').innerHTML = 
            '<div class="no-alarms">✅ 无报警</div>';
        return;
    }
    
    let html = '<div class="alarm-list">';
    alarms.forEach(alarm => {
        const levelIcons = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '❌',
            'critical': '🚨'
        };
        
        const icon = levelIcons[alarm.level] || '⚠️';
        
        html += `
            <div class="alarm-item ${alarm.level}">
                <div class="alarm-header">
                    <span class="alarm-type">${icon} ${alarm.type}</span>
                    <span class="alarm-time">${new Date(alarm.timestamp).toLocaleTimeString()}</span>
                </div>
                <div class="alarm-message">${alarm.message}</div>
            </div>
        `;
    });
    html += '</div>';
    
    document.getElementById('alarmDisplay').innerHTML = html;
}

// 更新性能跟踪
async function updatePerformanceTracking(data) {
    const lastIdx = data.data.pv.length - 1;
    
    await performanceTracker.updateData(
        currentLoopId,
        data.data.time[lastIdx],
        data.data.pv[lastIdx],
        data.data.sv[lastIdx],
        data.data.mv[lastIdx]
    );
    
    // 定期获取质量评估（每5秒）
    if (data.statistics.total_samples % 5 === 0) {
        const assessment = await performanceTracker.getQualityAssessment(currentLoopId);
        if (assessment.success && assessment.assessment) {
            displayQualityAssessment(assessment);
        }
    }
    
    // 更新性能趋势图（每次都更新）
    try {
        const response = await fetch(`${apiBaseUrl}/api/loops/${currentLoopId}`);
        const loopData = await response.json();
        if (loopData.success && loopData.loop && loopData.loop.performance) {
            updatePerformanceTrend(loopData.loop.performance);
        }
    } catch (error) {
        console.error('获取回路性能数据失败:', error);
    }
}

// 显示质量评估
function displayQualityAssessment(assessment) {
    const data = assessment.assessment;
    
    if (typeof data === 'string') {
        document.getElementById('qualityAssessmentDisplay').innerHTML = 
            `<p style="color: #94a3b8; text-align: center; padding: 40px;">${data}</p>`;
        return;
    }
    
    let html = '<div class="quality-assessment">';
    
    // 得分显示
    html += `<div class="quality-score-display">`;
    html += `<div class="quality-score">${data.overall_score.toFixed(1)}</div>`;
    html += `<div class="quality-rating">${data.rating}</div>`;
    html += `</div>`;
    
    // 优势
    if (data.strengths && data.strengths.length > 0) {
        html += '<div class="quality-section strengths">';
        html += '<h5>✅ 优势</h5>';
        html += '<ul>';
        data.strengths.forEach(item => {
            html += `<li>${item}</li>`;
        });
        html += '</ul></div>';
    }
    
    // 不足
    if (data.weaknesses && data.weaknesses.length > 0) {
        html += '<div class="quality-section weaknesses">';
        html += '<h5>⚠️ 不足</h5>';
        html += '<ul>';
        data.weaknesses.forEach(item => {
            html += `<li>${item}</li>`;
        });
        html += '</ul></div>';
    }
    
    // 建议
    if (data.recommendations && data.recommendations.length > 0) {
        html += '<div class="quality-section recommendations">';
        html += '<h5>💡 建议</h5>';
        html += '<ul>';
        data.recommendations.forEach(item => {
            html += `<li>${item}</li>`;
        });
        html += '</ul></div>';
    }
    
    html += '</div>';
    
    document.getElementById('qualityAssessmentDisplay').innerHTML = html;
}

// 配置默认报警
async function configureDefaultAlarms(loopId) {
    const config = {
        high_error_threshold: parseFloat(document.getElementById('highErrorThreshold').value),
        oscillation_threshold: parseInt(document.getElementById('oscillationThreshold').value),
        saturation_threshold: parseFloat(document.getElementById('saturationThreshold').value),
        steady_error_threshold: parseFloat(document.getElementById('steadyErrorThreshold').value),
        enabled: true
    };
    
    const lowPv = document.getElementById('lowPvThreshold').value;
    const highPv = document.getElementById('highPvThreshold').value;
    
    if (lowPv) config.low_pv_threshold = parseFloat(lowPv);
    if (highPv) config.high_pv_threshold = parseFloat(highPv);
    
    await alarmManager.configureAlarms(loopId, config);
}

// 显示报警配置面板
function showAlarmConfig() {
    document.getElementById('alarmConfigPanel').style.display = 'block';
}

// 隐藏报警配置面板
function hideAlarmConfig() {
    document.getElementById('alarmConfigPanel').style.display = 'none';
}

// 保存报警配置
async function saveAlarmConfig() {
    if (!currentLoopId) {
        alert('请先创建监控');
        return;
    }
    
    await configureDefaultAlarms(currentLoopId);
    hideAlarmConfig();
    showNotification('报警配置已保存', 'success');
}

// 显示通知
function showNotification(message, type = 'info') {
    // 简单的通知实现，可以替换为更好的UI组件
    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };
    
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${colors[type]};
        color: white;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
    `;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// 添加CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(400px); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(400px); opacity: 0; }
    }
`;
document.head.appendChild(style);
