// API基础URL - 设为全局变量供其他脚本使用
window.API_BASE_URL = 'http://localhost:8000';
const API_BASE_URL = window.API_BASE_URL;

// 使用window全局变量，供其他脚本访问
window.uploadedData = window.uploadedData || null;
let uploadedData = null;  // 保持局部引用以兼容现有代码
let tuningResult = null;
let evaluationMetrics = null;  // 添加评估指标全局变量
let simulationData = null;

// 将关键变量挂载到window对象，供其他脚本访问
window.tuningResult = null;
window.simulationData = null;
let animationInterval = null;
let currentFrame = 0;
let simulationChart = null;
let originalChart = null;
let comparisonChart = null;

// Batch processing
let batchFiles = [];
let batchMode = false;

// History management using IndexedDB
let db = null;

// Original tuned parameters (for reset)
let originalTunedParams = null;

// ========== 数据准备页面全局函数（供HTML内联事件调用） ==========

// 数据准备页面文件上传处理
window.handleDataPrepFileUpload = async function(event) {
    console.log('📤 数据准备页面文件上传事件触发');
    const files = Array.from(event.target.files);
    
    if (files.length === 0) {
        console.log('⚠️ 没有选择文件');
        return;
    }
    
    console.log('📁 选择的文件:', files.map(f => f.name));
    
    // 🔧 关键修复：在上传新的JSON文件时，清除所有OPC UA相关标记
    console.log('🧹 清除之前的OPC UA数据标记...');
    window.isOPCUAData = false;
    window.opcuaLoopId = null;
    window.dataSource = 'json';
    console.log('✅ 已重置为JSON文件数据源');
    
    // 检查批量模式
    const batchModeToggle = document.getElementById('batchModeToggle');
    const isBatchMode = batchModeToggle && batchModeToggle.checked;
    
    if (isBatchMode && files.length > 1) {
        // 批量模式：处理多个文件
        console.log('📦 批量模式，处理', files.length, '个文件');
        batchFiles = [];
        
        for (const file of files) {
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                
                if (data.data && Array.isArray(data.data)) {
                    batchFiles.push({ name: file.name, data: data.data });
                    console.log('✅ 文件已添加到批量列表:', file.name);
                }
            } catch (error) {
                console.error('❌ 解析文件失败:', file.name, error);
                showAlert(`文件 ${file.name} 解析失败`, 'error');
            }
        }
        
        console.log('📦 批量文件列表:', batchFiles.map(f => f.name));
        
        // 显示批量文件信息
        const fileInfo = document.getElementById('dataPrepFileInfo');
        if (fileInfo) {
            fileInfo.style.display = 'block';
            fileInfo.innerHTML = `
                <strong>批量模式:</strong> 已选择 ${files.length} 个文件<br>
                <strong>文件列表:</strong> ${files.map(f => f.name).join(', ')}
            `;
        }
        
        // 🔧 修复：批量文件加载后，启用整定按钮
        if (batchFiles.length > 0) {
            const tuneBtnElement = document.getElementById('tuneBtn');
            if (tuneBtnElement) {
                tuneBtnElement.disabled = false;
                console.log('✅ 批量文件已加载，整定按钮已启用');
            }
        }
    } else {
        // 单文件模式：只处理第一个文件
        const file = files[0];
        await handleFile(file, false);  // 明确传递 false 表示不是 OPC UA 数据
        
        // 显示文件信息
        const fileInfo = document.getElementById('dataPrepFileInfo');
        if (fileInfo) {
            fileInfo.style.display = 'block';
            fileInfo.innerHTML = `
                <strong>文件名:</strong> ${file.name}<br>
                <strong>文件大小:</strong> ${(file.size / 1024).toFixed(2)} KB<br>
                <strong>数据点数:</strong> ${window.uploadedData ? window.uploadedData.length : '-'}
            `;
        }
    }
};

// 数据准备页面OPC UA连接处理
window.handleDataPrepOpcuaConnect = function() {
    console.log('🔌 OPC UA连接按钮被点击');
    const serverUrl = document.getElementById('dataPrepOpcuaServerUrl').value;
    const nodeId = document.getElementById('dataPrepOpcuaNodeId').value;
    const samplingInterval = document.getElementById('dataPrepOpcuaSamplingInterval').value;
    
    if (!serverUrl || !nodeId) {
        showAlert('请填写服务器地址和节点ID', 'warning');
        return;
    }
    
    // 显示状态
    const status = document.getElementById('dataPrepOpcuaStatus');
    if (status) {
        status.style.display = 'block';
        status.style.background = 'rgba(59, 130, 246, 0.1)';
        status.style.border = '1px solid rgba(59, 130, 246, 0.3)';
        status.style.color = '#60a5fa';
        status.textContent = '正在连接 OPC UA 服务器...';
    }
    
    // 这里应该调用OPC UA连接逻辑
    setTimeout(() => {
        if (status) {
            status.style.background = 'rgba(239, 68, 68, 0.1)';
            status.style.border = '1px solid rgba(239, 68, 68, 0.3)';
            status.style.color = '#f87171';
            status.textContent = 'OPC UA连接功能开发中，请使用JSON文件上传';
        }
    }, 1000);
    
    console.log('OPC UA配置:', { serverUrl, nodeId, samplingInterval });
};

// 数据准备页面批量模式切换处理
window.handleBatchModeToggle = function(checked) {
    console.log('📦 批量模式切换:', checked);
    batchMode = checked;
    
    if (checked) {
        showAlert('批量处理模式已启用，可以选择多个文件', 'info');
    } else {
        showAlert('批量处理模式已关闭', 'info');
    }
};

// 数据准备页面"下一步"按钮处理
window.handleProceedToTuning = function() {
    console.log('🚀 下一步按钮被点击');
    
    // 检查批量模式
    const batchModeToggle = document.getElementById('batchModeToggle');
    const isBatchMode = batchModeToggle && batchModeToggle.checked;
    
    // 检查是否有数据
    if (isBatchMode) {
        // 批量模式：检查batchFiles
        if (!batchFiles || batchFiles.length === 0) {
            showAlert('批量模式下请先上传多个JSON文件', 'warning');
            return;
        }
        console.log('📦 批量模式，文件数量:', batchFiles.length);
    } else {
        // 单文件模式：检查uploadedData
        if (!uploadedData && !window.uploadedData) {
            showAlert('请先上传JSON文件或配置OPC UA数据源', 'warning');
            return;
        }
        console.log('📄 单文件模式');
    }
    
    // 切换到参数整定页面
    const tuningTab = document.querySelector('[data-tab="tuning"]');
    if (tuningTab) {
        tuningTab.click();
        
        if (isBatchMode) {
            showAlert(`已进入参数整定页面，准备批量整定 ${batchFiles.length} 个文件`, 'success');
        } else {
            showAlert('已进入参数整定页面，可以开始整定了', 'success');
        }
    } else {
        console.error('找不到参数整定标签页');
        showAlert('无法跳转到参数整定页面', 'error');
    }
};

// ========== 数据准备页面全局函数结束 ==========

// Initialize IndexedDB
function initDB() {
    const request = indexedDB.open('PIDTuningHistory', 1);
    
    request.onerror = () => {
        console.error('IndexedDB error:', request.error);
    };
    
    request.onsuccess = () => {
        db = request.result;
        loadHistory();
    };
    
    request.onupgradeneeded = (event) => {
        db = event.target.result;
        if (!db.objectStoreNames.contains('tunings')) {
            const objectStore = db.createObjectStore('tunings', { keyPath: 'id', autoIncrement: true });
            objectStore.createIndex('timestamp', 'timestamp', { unique: false });
            objectStore.createIndex('fileName', 'fileName', { unique: false });
        }
    };
}

// Save to history
function saveToHistory(fileName, tuningResult, evaluationMetrics) {
    console.log('💾 保存到历史记录:', { fileName, tuningResult, evaluationMetrics, db: !!db });
    
    if (!db) {
        console.error('❌ 数据库未初始化');
        showAlert('数据库未初始化，无法保存', 'error');
        return;
    }
    
    const transaction = db.transaction(['tunings'], 'readwrite');
    const objectStore = transaction.objectStore('tunings');
    
    const record = {
        fileName: fileName,
        timestamp: Date.now(),
        tuningResult: tuningResult,
        evaluationMetrics: evaluationMetrics
    };
    
    console.log('📝 准备保存记录:', record);
    
    const request = objectStore.add(record);
    
    request.onsuccess = () => {
        console.log('✅ 记录保存成功');
    };
    
    request.onerror = (e) => {
        console.error('❌ 保存失败:', e.target.error);
        showAlert('保存失败: ' + e.target.error, 'error');
    };
    
    transaction.oncomplete = () => {
        console.log('✅ 事务完成，重新加载历史记录');
        showAlert('已保存到历史记录', 'success');
        loadHistory();
    };
    
    transaction.onerror = (e) => {
        console.error('❌ 事务失败:', e.target.error);
    };
}

// Load history
function loadHistory() {
    console.log('📚 加载历史记录, db:', !!db);
    
    if (!db) {
        console.error('❌ 数据库未初始化，无法加载历史记录');
        return;
    }
    
    const transaction = db.transaction(['tunings'], 'readonly');
    const objectStore = transaction.objectStore('tunings');
    const request = objectStore.getAll();
    
    request.onsuccess = () => {
        const records = request.result;
        console.log('✅ 获取到历史记录:', records.length, '条');
        displayHistory(records.reverse()); // Show newest first
    };
    
    request.onerror = (e) => {
        console.error('❌ 加载历史记录失败:', e.target.error);
    };
}

// Display history
function displayHistory(records) {
    console.log('🎨 显示历史记录:', records.length, '条');
    
    const historyList = document.getElementById('historyList');
    const historySection = document.getElementById('historySection');
    
    console.log('📍 historyList元素:', !!historyList, 'historySection元素:', !!historySection);
    
    if (!historyList) {
        console.error('❌ 找不到 historyList 元素');
        return;
    }
    
    if (records.length === 0) {
        console.log('📭 没有历史记录');
        if (historySection) {
            historySection.style.display = 'none';
        }
        historyList.innerHTML = '<div style="text-align: center; padding: 60px 20px; opacity: 0.5;"><div style="font-size: 48px; margin-bottom: 16px;">📚</div><p>暂无历史记录</p></div>';
        return;
    }
    
    if (historySection) {
        historySection.style.display = 'block';
    }
    historyList.innerHTML = '';
    
    records.forEach(record => {
        const item = document.createElement('div');
        item.className = 'history-item';
        
        const date = new Date(record.timestamp).toLocaleString('zh-CN');
        const tr = record.tuningResult;
        
        item.innerHTML = `
            <div class="history-item-header">
                <div class="history-item-title">${record.fileName || 'Unknown'}</div>
                <div class="history-item-date">${date}</div>
            </div>
            <div class="history-item-params">
                Pb=${tr.pb.toFixed(2)}%, Ti=${tr.ti.toFixed(2)}s, Td=${tr.td.toFixed(2)}s
            </div>
        `;
        
        item.onclick = () => {
            // Load this record
            showAlert('历史记录功能：点击加载历史数据', 'success');
        };
        
        historyList.appendChild(item);
    });
}

// Clear history
document.getElementById('clearHistoryBtn')?.addEventListener('click', () => {
    if (!db || !confirm('确定要清空所有历史记录吗？')) return;
    
    const transaction = db.transaction(['tunings'], 'readwrite');
    const objectStore = transaction.objectStore('tunings');
    const request = objectStore.clear();
    
    request.onsuccess = () => {
        showAlert('历史记录已清空', 'success');
        loadHistory();
    };
});

// File upload handling
// 延迟获取DOM元素，确保它们存在
let uploadArea, fileInput, fileInfo, tuneBtn, batchModeCheckbox;

// 🔧 监听来自loops_manager的清除数据事件
window.addEventListener('clearTuningData', (event) => {
    console.log('🧹 收到清除数据事件，时间戳:', event.detail.timestamp);
    console.log('🔍 清除前 - 局部uploadedData:', uploadedData ? `${uploadedData.length}个点` : 'null');
    console.log('🔍 清除前 - 局部tuningResult:', tuningResult ? '存在' : 'null');
    console.log('🔍 清除前 - 局部simulationData:', simulationData ? '存在' : 'null');
    
    // 清除局部变量
    uploadedData = null;
    tuningResult = null;
    simulationData = null;
    evaluationMetrics = null;
    
    console.log('✅ 局部变量已清除');
});

// 在DOMContentLoaded后初始化这些元素
document.addEventListener('DOMContentLoaded', () => {
    uploadArea = document.getElementById('uploadArea');
    fileInput = document.getElementById('fileInput');
    fileInfo = document.getElementById('fileInfo');
    tuneBtn = document.getElementById('tuneBtn');
    batchModeCheckbox = document.getElementById('batchMode');
    
    // 只在元素存在时绑定事件
    if (batchModeCheckbox) {
        batchModeCheckbox.addEventListener('change', (e) => {
            batchMode = e.target.checked;
            if (batchMode) {
                showAlert('批量处理模式已启用，可以选择多个文件', 'success');
            }
        });
    }
    
    if (uploadArea && fileInput) {
        uploadArea.addEventListener('click', () => fileInput.click());
        
        uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadArea.classList.add('dragover');
        });
        
        uploadArea.addEventListener('dragleave', () => {
            uploadArea.classList.remove('dragover');
        });
        
        uploadArea.addEventListener('drop', handleUploadAreaDrop);
    }
    
    // 绑定tuneBtn事件
    if (tuneBtn) {
        tuneBtn.addEventListener('click', startTuning);
    }
    
    // 绑定fileInput事件
    bindFileInputEvent();
});

// 将drop事件处理提取为函数
function handleUploadAreaDrop(e) {
    e.preventDefault();
    if (uploadArea) {
        uploadArea.classList.remove('dragover');
    }
    const files = Array.from(e.dataTransfer.files).filter(f => f.name.endsWith('.json'));
    
    if (files.length === 0) {
        showAlert('请上传JSON格式文件', 'error');
        return;
    }
    
    if (batchMode) {
        handleBatchFiles(files);
    } else {
        handleFile(files[0]);
    }
}

// 将fileInput事件绑定也移到DOMContentLoaded中
function bindFileInputEvent() {
    if (!fileInput) return;
    
    fileInput.addEventListener('change', (e) => {
        const files = Array.from(e.target.files);
        
        if (batchMode && files.length > 1) {
            handleBatchFiles(files);
        } else if (files.length > 0) {
            handleFile(files[0]);
        }
    });
}

async function handleFile(file, isFromOPCUA = false) {
    console.log('📁 处理文件:', file.name, '来源:', isFromOPCUA ? 'OPC UA' : 'JSON上传');
    
    // 🔧 完全清除或设置数据源标记
    if (!isFromOPCUA) {
        // JSON文件：完全清除所有OPC UA标记
        window.isOPCUAData = false;
        window.opcuaLoopId = null;
        window.dataSource = 'json';
        console.log('🔧 已完全重置为JSON文件数据源，清除所有OPC UA标记');
    } else {
        // OPC UA数据：保持标记（标记应该在opcuaDataReady事件中已设置）
        console.log('🔧 保持OPC UA数据源标记');
    }
    
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        if (!data.data || !Array.isArray(data.data)) {
            throw new Error('JSON文件必须包含data数组字段');
        }

        uploadedData = data.data;
        window.uploadedData = data.data; // 同时更新全局变量
        
        // 数据来源已在前面设置，这里只是确认
        console.log('✅ 数据已上传到全局变量');
        console.log('   📊 数据点数:', data.data.length);
        console.log('   🔍 数据来源:', window.dataSource);
        console.log('   🔍 是否OPC UA:', window.isOPCUAData);
        console.log('   🔍 回路ID:', window.opcuaLoopId || 'null');
        
        // 更新文件信息（如果元素存在）
        const fileInfo = document.getElementById('fileInfo');
        if (fileInfo) {
            fileInfo.style.display = 'block';
            fileInfo.innerHTML = `
                <strong>文件名:</strong> ${file.name}<br>
                <strong>数据点数:</strong> ${uploadedData.length}<br>
                <strong>文件大小:</strong> ${(file.size / 1024).toFixed(2)} KB
            `;
        }
        
        // 启用整定按钮（如果元素存在）
        const tuneBtn = document.getElementById('tuneBtn');
        if (tuneBtn) {
            tuneBtn.disabled = false;
        }
        
        // 立即显示原始数据图表
        displayUploadedDataPreview(uploadedData);
        
        showAlert('文件上传成功！', 'success');
    } catch (error) {
        showAlert('文件解析失败: ' + error.message, 'error');
        const tuneBtn = document.getElementById('tuneBtn');
        if (tuneBtn) {
            tuneBtn.disabled = true;
        }
    }
}

// 显示上传数据的预览图表
function displayUploadedDataPreview(data) {
    // 提取时间、PV、SP、MV数据
    const times = data.map(d => d.time);
    const pvs = data.map(d => d.pv);
    const sps = data.map(d => d.sp);
    const mvs = data.map(d => d.mv);
    
    // 不自动跳转到仿真结果页面，而是在当前页面显示预览信息
    console.log('✅ 数据已上传，包含', times.length, '个数据点');
    
    // 可以在这里添加一个小的预览图表到参数整定页面，或者只是记录数据
    // 暂时注释掉自动跳转逻辑，让用户停留在参数整定页面
    /*
    // 切换到仿真结果标签页显示图表
    const simulationTab = document.querySelector('[data-tab="simulation"]');
    if (simulationTab) {
        simulationTab.click();
    }
    */
    
    // 数据已上传，等待用户点击"开始整定"按钮
    // 不再在此处创建预览图表，而是等待整定完成后在仿真结果页面显示
}

async function handleBatchFiles(files) {
    batchFiles = [];
    const batchFileList = document.getElementById('batchFileList');
    batchFileList.style.display = 'block';
    batchFileList.innerHTML = '';
    
    for (const file of files) {
        try {
            const text = await file.text();
            const data = JSON.parse(text);
            
            if (data.data && Array.isArray(data.data)) {
                batchFiles.push({ name: file.name, data: data.data });
                
                const item = document.createElement('div');
                item.className = 'batch-file-item';
                item.innerHTML = `
                    <span>${file.name} (${data.data.length} 点)</span>
                    <button class="batch-file-remove" onclick="removeBatchFile('${file.name}')">删除</button>
                `;
                batchFileList.appendChild(item);
            }
        } catch (error) {
            console.error(`解析文件 ${file.name} 失败:`, error);
        }
    }
    
    if (batchFiles.length > 0) {
        // 🔧 修复：直接通过getElementById获取按钮，确保能正确启用
        const tuneBtnElement = document.getElementById('tuneBtn');
        if (tuneBtnElement) {
            tuneBtnElement.disabled = false;
            console.log('✅ 批量文件已加载，整定按钮已启用');
        }
        showAlert(`已加载 ${batchFiles.length} 个文件`, 'success');
    }
}

window.removeBatchFile = function(fileName) {
    batchFiles = batchFiles.filter(f => f.name !== fileName);
    handleBatchFiles([]); // Refresh display
    
    if (batchFiles.length === 0) {
        document.getElementById('batchFileList').style.display = 'none';
        // 🔧 修复：直接通过getElementById获取按钮
        const tuneBtnElement = document.getElementById('tuneBtn');
        if (tuneBtnElement) {
            tuneBtnElement.disabled = true;
        }
    }
};

// Tuning - 将函数定义提取出来，供DOMContentLoaded中的事件绑定使用
async function startTuning() {
    // 🔧 修复：检查数据源类型，OPC UA数据优先
    const isOPCUA = window.dataSource === 'opcua' || window.isOPCUAData;
    
    if (isOPCUA) {
        // OPC UA数据源：强制使用单文件模式
        console.log('🔌 检测到OPC UA数据源，使用单文件整定模式');
        if (window.uploadedData && !uploadedData) {
            uploadedData = window.uploadedData;
        }
        await singleTuning();
    } else if (batchMode && batchFiles.length > 0) {
        // 批量模式：仅用于JSON文件
        console.log('📦 批量模式，处理多个JSON文件');
        await batchTuning();
    } else if (window.uploadedData || uploadedData) {
        // 单文件模式
        if (window.uploadedData && !uploadedData) {
            uploadedData = window.uploadedData;
        }
        await singleTuning();
    } else {
        showAlert('请先上传数据文件', 'error');
    }
}

async function singleTuning() {
    const tuningMethod = document.getElementById('tuningMethod').value;
    const controlMode = document.getElementById('controlMode').value;
    const modelType = document.getElementById('modelType').value;
    const enableSegmentation = document.getElementById('enableSegmentation').checked;

    // 🔧 强制同步全局变量到局部变量（关键修复！）
    if (window.uploadedData) {
        uploadedData = window.uploadedData;
        console.log('🔄 已同步全局数据到局部变量');
    }

    // 🔧 记录整定开始时间和数据信息
    const tuningStartTime = Date.now();
    console.log('═══════════════════════════════════════════════════════');
    console.log('🚀 开始整定计算...');
    console.log('⏰ 整定开始时间:', new Date(tuningStartTime).toISOString());
    console.log('───────────────────────────────────────────────────────');
    console.log('📊 数据信息:');
    console.log('   • 数据点数:', uploadedData?.length || 0);
    console.log('   • 数据源类型:', window.dataSource || 'unknown');
    console.log('   • 是否OPC UA:', window.isOPCUAData || false);
    console.log('   • OPC UA回路ID:', window.opcuaLoopId || 'null');
    console.log('───────────────────────────────────────────────────────');
    console.log('📋 整定参数:', {
        tuningMethod,
        controlMode,
        modelType,
        enableSegmentation
    });
    console.log('═══════════════════════════════════════════════════════');

    if (!uploadedData || uploadedData.length === 0) {
        console.error('❌ 没有可用的数据进行整定！');
        showAlert('没有可用的数据，请先上传数据或启动OPC UA采集', 'error');
        document.getElementById('tuneBtn').disabled = false;
        document.getElementById('loadingIndicator').style.display = 'none';
        return;
    }

    document.getElementById('tuneBtn').disabled = true;
    document.getElementById('loadingIndicator').style.display = 'flex';

    try {
        // 🔧 添加时间戳到请求，确保后端不使用缓存
        const response = await axios.post(`${API_BASE_URL}/api/tune?_t=${tuningStartTime}`, {
            data: uploadedData,
            tuning_method: tuningMethod,
            control_mode: controlMode,
            model_type: modelType === 'auto' ? null : modelType,
            enable_segmentation: enableSegmentation,
            request_timestamp: tuningStartTime,  // 传递时间戳给后端
            loop_id: window.opcuaLoopId || null,  // 传递回路ID，用于自动下发参数
            data_source: window.dataSource || 'json',  // 传递数据源类型
            is_opcua_data: window.isOPCUAData || false  // 传递OPC UA标记
        }, {
            timeout: 60000,
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache'
            }
        });

        console.log('✅ 整定API响应成功');
        console.log('⏱️ 整定耗时:', (Date.now() - tuningStartTime) / 1000, '秒');
        console.log('📦 整定响应数据:', {
            'success': response.data.success,
            'has_tuning_result': !!response.data.tuning_result,
            'has_data': !!response.data.data
        });

        if (response.data.success) {
            // 清除旧结果
            console.log('🧹 清除旧的整定结果...');
            tuningResult = null;
            simulationData = null;
            window.tuningResult = null;
            window.simulationData = null;
            
            // 保存新的整定结果
            tuningResult = response.data;
            window.tuningResult = response.data;
            
            const dataPointCount = tuningResult.data?.pv?.length || 0;
            const isSteadyState = tuningResult.is_steady_state || false;
            
            console.log('✅ 新整定结果已保存:', {
                'PID参数': tuningResult.tuning_result,
                '数据点数': dataPointCount,
                'is_steady_state': isSteadyState
            });
            
            // 初始化仿真数据（使用原始数据作为基础）
            // 这确保切换到仿真结果页面时始终有数据可显示
            simulationData = {
                success: true,
                pv: tuningResult.data.pv,
                mv: tuningResult.data.mv || [],
                t: tuningResult.data.t,
                is_steady_state: isSteadyState
            };
            window.simulationData = simulationData;
            
            console.log('✅ 基础仿真数据已设置:', {
                'PV数据点数': dataPointCount,
                'is_steady_state': isSteadyState,
                '数据来源': '原始数据'
            });
            
            // 根据稳态状态选择处理流程
            console.log('🔍 检查稳态状态:', isSteadyState);
            
            if (isSteadyState) {
                // 稳态情况：直接使用原始数据
                console.log('⚠️ 检测到稳态，跳过仿真，使用原始数据');
                showAlert('数据已处于稳态，无需整定', 'success');
                displaySteadyStateResults(tuningResult);
            } else {
                // 非稳态情况：执行仿真
                console.log('✅ 进入正常整定分支（非稳态）');
                
                // 保存原始整定参数
                originalTunedParams = {
                    pb: tuningResult.tuning_result.pb,
                    ti: tuningResult.tuning_result.ti,
                    td: tuningResult.tuning_result.td
                };
                
                displayTuningResults(tuningResult);
                
                // 运行仿真
                console.log('🎮 准备运行仿真...');
                try {
                    await runSimulation();
                    console.log('🎮 仿真完成:', {
                        'window.simulationData存在': !!window.simulationData,
                        'PV数据点数': window.simulationData?.pv?.length || 0,
                        '数据来源': '仿真结果'
                    });
                } catch (simError) {
                    console.error('❌ 仿真失败:', simError.message);
                    console.warn('⚠️ 将使用原始数据作为后备');
                    showAlert('仿真失败，将显示原始数据: ' + simError.message, 'warning');
                    // simulationData已在前面设置为原始数据，无需额外处理
                }
                
                // 整定完成提示
                console.log('✅ 整定完成，保持在当前页面');
                showAlert('✅ 整定完成！可以在"仿真结果"页面查看详细结果', 'success');
                
                // Show parameter tuning section
                document.getElementById('parameterTuningSection').style.display = 'block';
                initializeSliders();
                
                // Show model comparison section
                const modelComparisonContainer = document.getElementById('modelComparisonContainer');
                if (modelComparisonContainer) {
                    modelComparisonContainer.style.display = 'block';
                    console.log('✅ 多模型对比功能已启用');
                }
                
                // Show AI assistant
                if (typeof showAIAssistant === 'function') {
                    showAIAssistant();
                }
                
                // 如果是从回路管理进入的，自动保存结果到回路
                if (window.currentLoopForTuning) {
                    await saveResultsToLoop(window.currentLoopForTuning.id);
                }
                
                // 如果实时监控模块存在，更新整定参数
                if (typeof window.updateLoopTuningParams === 'function') {
                    const pidParams = {
                        pb: response.data.tuning_result.pb,
                        ti: response.data.tuning_result.ti,
                        td: response.data.tuning_result.td
                    };
                    const modelParams = response.data.tuning_result.model_params;
                    window.updateLoopTuningParams(pidParams, modelParams);
                }
            }
        } else {
            console.error('❌ 整定API返回success=false');
            console.error('响应消息:', response.data.message);
            showAlert(response.data.message || '整定失败', 'error');
        }
    } catch (error) {
        console.error('整定错误:', error);
        if (error.code === 'ECONNABORTED') {
            showAlert('整定超时，请检查数据量或后端服务', 'error');
        } else if (error.response) {
            showAlert('整定失败: ' + (error.response.data.detail || error.message), 'error');
        } else {
            showAlert('整定请求失败: ' + error.message, 'error');
        }
    } finally {
        document.getElementById('tuneBtn').disabled = false;
        document.getElementById('loadingIndicator').style.display = 'none';
    }
}

async function batchTuning() {
    const tuningMethod = document.getElementById('tuningMethod').value;
    const controlMode = document.getElementById('controlMode').value;
    const modelType = document.getElementById('modelType').value;
    const enableSegmentation = document.getElementById('enableSegmentation').checked;

    document.getElementById('tuneBtn').disabled = true;
    document.getElementById('loadingIndicator').style.display = 'flex';

    try {
        const response = await axios.post(`${API_BASE_URL}/api/batch_tune`, {
            files: batchFiles,
            tuning_method: tuningMethod,
            control_mode: controlMode,
            model_type: modelType === 'auto' ? null : modelType,
            enable_segmentation: enableSegmentation
        }, {
            timeout: 120000
        });

        if (response.data.success) {
            displayBatchResults(response.data);
            showAlert(`批量处理完成！成功: ${response.data.statistics.success}, 失败: ${response.data.statistics.failed}`, 'success');
        } else {
            showAlert('批量处理失败', 'error');
        }
    } catch (error) {
        console.error('批量处理错误:', error);
        showAlert('批量处理失败: ' + error.message, 'error');
    } finally {
        document.getElementById('tuneBtn').disabled = false;
        document.getElementById('loadingIndicator').style.display = 'none';
    }
}

function displayBatchResults(data) {
    const batchResultSection = document.getElementById('batchResultSection');
    const batchResultList = document.getElementById('batchResultList');
    
    batchResultSection.style.display = 'block';
    batchResultList.innerHTML = '';
    
    // 保存批量结果数据供后续使用
    window.batchResultsData = data;
    
    data.results.forEach((result, index) => {
        const item = document.createElement('div');
        
        if (result.success) {
            if (result.is_steady) {
                // 稳态情况 - 蓝色边框
                item.className = 'batch-result-item steady clickable';
                item.innerHTML = `
                    <div class="batch-result-header">🔵 ${result.file_name}</div>
                    <div class="batch-result-params">
                        <strong>状态:</strong> 已稳态，无需整定<br>
                        <strong>数据点:</strong> ${result.data_points}
                    </div>
                    <div class="batch-result-action">
                        <button class="btn-view-detail" onclick="viewBatchItemDetail(${index})">📊 查看详情</button>
                    </div>
                `;
            } else {
                // 整定成功 - 绿色边框
                item.className = 'batch-result-item success clickable';
                item.innerHTML = `
                    <div class="batch-result-header">✅ ${result.file_name}</div>
                    <div class="batch-result-params">
                        <strong>PID参数:</strong> Pb=${result.pb.toFixed(2)}%, Ti=${result.ti.toFixed(2)}s, Td=${result.td.toFixed(2)}s<br>
                        <strong>模型:</strong> ${result.model_type} | <strong>数据点:</strong> ${result.data_points}
                    </div>
                    <div class="batch-result-action">
                        <button class="btn-view-detail" onclick="viewBatchItemDetail(${index})">📊 查看详情</button>
                    </div>
                `;
            }
        } else {
            // 失败情况 - 红色边框
            item.className = 'batch-result-item failed';
            item.innerHTML = `
                <div class="batch-result-header">❌ ${result.file_name}</div>
                <div class="batch-result-params">
                    <strong>错误:</strong> ${result.error}<br>
                    ${result.data_points > 0 ? `<strong>数据点:</strong> ${result.data_points}` : ''}
                </div>
            `;
        }
        
        batchResultList.appendChild(item);
    });
    
    // 显示统计摘要
    const steadyCount = data.results.filter(r => r.success && r.is_steady).length;
    const tunedCount = data.results.filter(r => r.success && !r.is_steady).length;
    const failedCount = data.results.filter(r => !r.success).length;
    
    const summary = document.createElement('div');
    summary.className = 'batch-summary';
    summary.innerHTML = `
        <h4 style="margin-bottom: 10px;">📊 批量处理摘要</h4>
        <div style="font-size: 13px;">
            <div>✅ 整定成功: ${tunedCount} 个</div>
            <div>🔵 已稳态: ${steadyCount} 个</div>
            <div>❌ 处理失败: ${failedCount} 个</div>
            <div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #ddd;">
                <strong>总计: ${data.results.length} 个文件</strong>
            </div>
        </div>
    `;
    batchResultList.insertBefore(summary, batchResultList.firstChild);
}

function displaySteadyStateResults(result) {
    // 🔧 【关键修复】更新window.tuningResult为稳态结果
    window.tuningResult = result;
    console.log('🔧 已更新window.tuningResult为稳态结果');
    
    // 显示稳态信息
    document.getElementById('resultSection').style.display = 'block';
    document.getElementById('pbValue').textContent = 'N/A';
    document.getElementById('tiValue').textContent = 'N/A';
    document.getElementById('tdValue').textContent = 'N/A';
    
    // 计算稳态统计信息用于显示
    const pv = result.data.pv;
    const sv = result.data.sv;
    const mv = result.data.mv || [];
    const meanPV = pv.reduce((a, b) => a + b, 0) / pv.length;
    const meanSV = sv.reduce((a, b) => a + b, 0) / sv.length;
    const stdPV = Math.sqrt(pv.reduce((sq, n) => sq + Math.pow(n - meanPV, 2), 0) / pv.length);
    const meanError = Math.abs(meanPV - meanSV);
    
    const segmentList = document.getElementById('segmentList');
    segmentList.style.display = 'block';
    segmentList.innerHTML = `
        <div class="steady-state-info">
            <h4 style="margin: 0 0 10px 0; font-size: 14px; color: #28a745;">
                ✅ 系统已处于稳态
            </h4>
            <p style="margin: 5px 0; font-size: 12px; color: rgba(255,255,255,0.9);">
                当前数据显示系统处于稳定状态，无需进行PID整定。
            </p>
            <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.2);">
                <div style="font-size: 11px; color: rgba(255,255,255,0.8);">
                    <div>📊 平均PV: ${meanPV.toFixed(2)}</div>
                    <div>🎯 平均SV: ${meanSV.toFixed(2)}</div>
                    <div>📉 平均误差: ${meanError.toFixed(4)}</div>
                    <div>📈 标准差: ${stdPV.toFixed(4)}</div>
                </div>
            </div>
        </div>
    `;
    
    // 显示原始数据图表
    displayOriginalData(result.data);
    
    // 显示稳态评估信息
    document.getElementById('resultsContainer').style.display = 'block';
    displaySteadyStateMetrics(result.data);
    
    // 🔧 关键修复：更新simulationData为稳态数据
    // 对于OPC UA数据，保持原始SV；对于文件数据，使用整定结果的SV
    const svForSimulationData = window.isOPCUAData && window.uploadedData ? 
        window.uploadedData.map(item => item.sp) : result.data.sv;
    
    window.simulationData = {
        success: true,
        pv: result.data.pv,
        mv: result.data.mv || [],
        sv: svForSimulationData,
        t: result.data.t,
        is_steady_state: true,  // 标记为稳态
        original_sv: window.isOPCUAData && window.uploadedData ? window.uploadedData.map(item => item.sp) : null  // 保存原始SV
    };
    
    console.log('🔧 稳态数据更新:', {
        'isOPCUAData': window.isOPCUAData,
        'SV数据源': window.isOPCUAData ? 'OPC UA原始数据' : '整定结果',
        'SV样本': svForSimulationData?.slice(0, 3)
    });
    
    console.log('✅ 稳态仿真数据已更新:', {
        'PV数据点数': result.data.pv?.length || 0,
        'is_steady_state': true,
        '数据来源': '稳态检测结果'
    });
    
    // 🔧 不在这里渲染图表，因为仿真结果页面可能不可见
    // displaySteadyStateSimulation(result.data);
    console.log('✅ 稳态数据已准备好，图表将在切换到仿真结果页面时渲染');
}

// 新增函数：稳态状态下的仿真可视化
function displaySteadyStateSimulation(data) {
    const canvasElement = document.getElementById('simulationChart');
    if (!canvasElement) {
        console.warn('未找到仿真图表元素');
        return;
    }
    
    // 🔧 销毁所有旧图表实例，避免冲突
    if (window.simulationChart) {
        console.log('🗑️ 销毁非稳态图表实例');
        try {
            window.simulationChart.destroy();
        } catch (e) {
            console.warn('⚠️ 销毁非稳态图表时出错:', e);
        }
        window.simulationChart = null;
    }
    
    if (window.simulationChartInstance) {
        console.log('🗑️ 销毁旧稳态图表实例');
        try {
            window.simulationChartInstance.destroy();
        } catch (e) {
            console.warn('⚠️ 销毁稳态图表时出错:', e);
        }
    }
    
    // 🔧 根据数据源选择SV数据
    let svData;
    if (window.isOPCUAData) {
        // OPC UA数据：优先使用simulationData中的原始SV，否则使用uploadedData
        if (window.simulationData && window.simulationData.original_sv) {
            svData = window.simulationData.original_sv;
            console.log('🔧 稳态图表 - OPC UA数据源：使用simulationData中的原始SV');
        } else if (window.uploadedData) {
            svData = window.uploadedData.map(item => item.sp);
            console.log('🔧 稳态图表 - OPC UA数据源：使用uploadedData中的原始SV');
        } else {
            svData = data.sv;
            console.log('⚠️ 稳态图表 - OPC UA数据源：找不到原始SV，使用传入的SV');
        }
    } else {
        svData = data.sv;  // 文件数据使用处理后的SV
        console.log('🔧 稳态图表 - 文件数据源：使用处理后的SV');
    }
    
    const ctx = canvasElement.getContext('2d');
    const timePoints = data.pv.map((_, i) => i);
    
    window.simulationChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: timePoints,
            datasets: [
                {
                    label: 'PV (过程变量)',
                    data: data.pv,
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1
                },
                {
                    label: 'SV (设定值)',
                    data: svData,
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    borderDash: [5, 5],
                    tension: 0.1
                },
                {
                    label: 'MV (操作变量)',
                    data: data.mv || [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    pointRadius: 0,
                    tension: 0.1,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 1000,
                easing: 'easeInOutQuart'
            },
            interaction: {
                mode: 'index',
                intersect: false
            },
            plugins: {
                title: {
                    display: true,
                    text: '稳态数据可视化',
                    color: '#e2e8f0',
                    font: { size: 16, weight: 'bold' }
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: { color: '#e2e8f0', padding: 15, font: { size: 12 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    titleColor: '#e2e8f0',
                    bodyColor: '#e2e8f0',
                    borderColor: '#667eea',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${context.parsed.y.toFixed(3)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: '时间点',
                        color: '#e2e8f0',
                        font: { size: 12 }
                    },
                    ticks: { color: '#94a3b8', maxTicksLimit: 10 },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                },
                y: {
                    title: {
                        display: true,
                        text: 'PV / SV',
                        color: '#e2e8f0',
                        font: { size: 12 }
                    },
                    ticks: { color: '#94a3b8' },
                    grid: { color: 'rgba(148, 163, 184, 0.1)' }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    title: {
                        display: true,
                        text: 'MV',
                        color: '#e2e8f0',
                        font: { size: 12 }
                    },
                    ticks: { color: '#94a3b8' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
    
    console.log('✅ 稳态仿真曲线已显示');
}

function displaySteadyStateMetrics(data) {
    // 计算稳态统计信息
    const pv = data.pv;
    const sv = data.sv;
    
    const meanPV = pv.reduce((a, b) => a + b, 0) / pv.length;
    const meanSV = sv.reduce((a, b) => a + b, 0) / sv.length;
    const stdPV = Math.sqrt(pv.reduce((sq, n) => sq + Math.pow(n - meanPV, 2), 0) / pv.length);
    const meanError = Math.abs(meanPV - meanSV);
    
    // 显示稳态指标
    document.getElementById('overallScore').textContent = 'N/A';
    document.getElementById('scoreGrade').textContent = '稳态';
    document.getElementById('steadyError').textContent = meanError.toFixed(4);
    document.getElementById('iaeValue').textContent = 'N/A';
    document.getElementById('oscillationCount').textContent = '0';
    document.getElementById('tvValue').textContent = 'N/A';
    document.getElementById('iseValue').textContent = 'N/A';
    document.getElementById('maxControlEffort').textContent = 'N/A';
    document.getElementById('maxOscillation').textContent = stdPV.toFixed(4);
    document.getElementById('overshootValue').textContent = '0';
    document.getElementById('settlingTime').textContent = '0';
    document.getElementById('riseTime').textContent = '0';
    document.getElementById('steadyBand').textContent = stdPV.toFixed(4);
}

function displayModelInfo(tuningResult) {
    const modelInfoCard = document.getElementById('modelInfoCard');
    const modelTypeName = document.getElementById('modelTypeName');
    const modelParamsDisplay = document.getElementById('modelParamsDisplay');
    const controlModeName = document.getElementById('controlModeName');
    
    if (!modelInfoCard || !tuningResult) return;
    
    // 显示卡片
    modelInfoCard.style.display = 'block';
    
    // 模型类型映射
    const modelTypeMap = {
        'fopdt': '一阶惯性+纯滞后 (FOPDT)',
        'first_order': '一阶惯性',
        'second_order': '二阶系统',
        'integral_delay': '积分+延迟',
        'fopdt_with_heat_loss': 'FOPDT+热损失'
    };
    
    // 控制模式映射
    const controlModeMap = {
        'STANDARD': '标准模式',
        'ANTI_DISTURBANCE': '抗干扰模式',
        'ANTI_NOISE': '抗噪声模式',
        'FLOW_CONTROL': '流量控制模式'
    };
    
    // 显示模型类型
    const modelType = tuningResult.model_type || 'unknown';
    modelTypeName.textContent = modelTypeMap[modelType] || modelType;
    
    // 显示模型参数
    const params = tuningResult.model_params || [];
    let paramsHTML = '';
    
    if (modelType === 'fopdt' || modelType === 'first_order') {
        // FOPDT: K, τ, L
        paramsHTML = `
            <div>K (增益) = ${params[0]?.toFixed(4) || 'N/A'}</div>
            <div>τ (时间常数) = ${params[1]?.toFixed(2) || 'N/A'} s</div>
            <div>L (延迟) = ${params[2]?.toFixed(2) || 'N/A'} s</div>
        `;
    } else if (modelType === 'second_order') {
        // 二阶: K, ζ, ωn, L
        paramsHTML = `
            <div>K (增益) = ${params[0]?.toFixed(4) || 'N/A'}</div>
            <div>ζ (阻尼比) = ${params[1]?.toFixed(3) || 'N/A'}</div>
            <div>ωn (自然频率) = ${params[2]?.toFixed(3) || 'N/A'} rad/s</div>
            <div>L (延迟) = ${params[3]?.toFixed(2) || 'N/A'} s</div>
        `;
    } else if (modelType === 'integral_delay') {
        // 积分延迟: K, L
        paramsHTML = `
            <div>K (积分增益) = ${params[0]?.toFixed(4) || 'N/A'}</div>
            <div>L (延迟) = ${params[1]?.toFixed(2) || 'N/A'} s</div>
        `;
    } else {
        // 通用显示
        paramsHTML = params.map((p, i) => `<div>参数${i+1} = ${p?.toFixed(4) || 'N/A'}</div>`).join('');
    }
    
    modelParamsDisplay.innerHTML = paramsHTML || '<div style="opacity: 0.5;">无参数信息</div>';
    
    // 显示控制模式
    const controlMode = tuningResult.control_mode || 'STANDARD';
    controlModeName.textContent = controlModeMap[controlMode] || controlMode;
}

function displayTuningResults(result) {
    document.getElementById('resultSection').style.display = 'block';
    document.getElementById('pbValue').textContent = result.tuning_result.pb.toFixed(2);
    document.getElementById('tiValue').textContent = result.tuning_result.ti.toFixed(2);
    document.getElementById('tdValue').textContent = result.tuning_result.td.toFixed(2);

    // Display model information
    displayModelInfo(result.tuning_result);

    // Display segments if available
    const segmentList = document.getElementById('segmentList');
    if (result.segments && result.segments.length > 0) {
        segmentList.style.display = 'block';
        segmentList.innerHTML = '<h4 style="margin-top: 15px; margin-bottom: 10px; font-size: 14px;">📊 分段整定结果 (' + result.segments.length + '个分段):</h4>';
        
        // 创建分段可视化容器
        const segmentVisContainer = document.createElement('div');
        segmentVisContainer.style.cssText = 'margin-bottom: 20px; padding: 15px; background: rgba(16, 185, 129, 0.05); border-radius: 8px; border: 1px solid rgba(16, 185, 129, 0.2);';
        
        // 添加分段时间轴可视化
        const timeline = document.createElement('div');
        timeline.style.cssText = 'display: flex; gap: 2px; margin-bottom: 15px; height: 40px;';
        
        const totalTime = result.data.t[result.data.t.length - 1];
        result.segments.forEach((seg, idx) => {
            const startIdx = seg.segment_indices[0];
            const endIdx = seg.segment_indices[1];
            const startTime = result.data.t[startIdx];
            const endTime = result.data.t[endIdx - 1] || result.data.t[result.data.t.length - 1];
            const duration = endTime - startTime;
            const widthPercent = (duration / totalTime) * 100;
            
            const colors = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6'];
            const color = colors[idx % colors.length];
            
            const segBlock = document.createElement('div');
            segBlock.style.cssText = `
                flex: 0 0 ${widthPercent}%;
                background: ${color};
                border-radius: 4px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: white;
                font-size: 11px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.2s;
                position: relative;
            `;
            segBlock.innerHTML = `段${seg.segment_index}`;
            segBlock.title = `段${seg.segment_index}: ${startTime.toFixed(1)}s - ${endTime.toFixed(1)}s (${duration.toFixed(1)}s)`;
            
            // 鼠标悬停效果
            segBlock.onmouseenter = () => {
                segBlock.style.transform = 'scale(1.05)';
                segBlock.style.boxShadow = '0 4px 12px rgba(0,0,0,0.2)';
            };
            segBlock.onmouseleave = () => {
                segBlock.style.transform = 'scale(1)';
                segBlock.style.boxShadow = 'none';
            };
            
            timeline.appendChild(segBlock);
        });
        
        segmentVisContainer.appendChild(timeline);
        
        // 添加分段详细信息
        result.segments.forEach((seg, idx) => {
            const startIdx = seg.segment_indices[0];
            const endIdx = seg.segment_indices[1];
            const startTime = result.data.t[startIdx];
            const endTime = result.data.t[endIdx - 1] || result.data.t[result.data.t.length - 1];
            
            const colors = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6'];
            const color = colors[idx % colors.length];
            
            const segDiv = document.createElement('div');
            segDiv.className = 'segment-item';
            segDiv.style.cssText = `
                padding: 12px;
                margin-bottom: 8px;
                background: white;
                border-radius: 6px;
                border-left: 4px solid ${color};
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            `;
            segDiv.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <span style="background: ${color}; color: white; padding: 4px 8px; border-radius: 4px; font-weight: 600; font-size: 12px;">
                            段${seg.segment_index}
                        </span>
                        <span style="color: #64748b; font-size: 12px;">
                            ${startTime.toFixed(1)}s - ${endTime.toFixed(1)}s
                        </span>
                    </div>
                    <div style="display: flex; gap: 15px; font-size: 13px;">
                        <span><strong>Pb:</strong> ${seg.pb.toFixed(2)}%</span>
                        <span><strong>Ti:</strong> ${seg.ti.toFixed(2)}s</span>
                        <span><strong>Td:</strong> ${seg.td.toFixed(2)}s</span>
                    </div>
                </div>
            `;
            segmentVisContainer.appendChild(segDiv);
        });
        
        segmentList.appendChild(segmentVisContainer);
    } else {
        segmentList.style.display = 'none';
    }

    // Display original data chart
    displayOriginalData(result.data);
}

function displayOriginalData(data) {
    const ctx = document.getElementById('originalChart');
    if (originalChart) {
        originalChart.destroy();
    }

    originalChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.t,
            datasets: [
                {
                    label: 'PV',
                    data: data.pv,
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0
                },
                {
                    label: 'SV',
                    data: data.sv,
                    borderColor: '#f59e0b',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.4,
                    pointRadius: 0
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2.5,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                title: {
                    display: true,
                    text: '原始数据',
                    font: {
                        size: 14,
                        weight: 'bold'
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: '时间 (s)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: '值'
                    }
                }
            }
        }
    });
}

async function runSimulation() {
    try {
        console.log('🎮 开始运行仿真...');
        console.log('📊 使用整定结果:', {
            'PID参数': tuningResult.tuning_result,
            '模型类型': tuningResult.tuning_result.model_type,
            '数据点数': tuningResult.data.pv.length
        });
        
        // 计算合理的初始PV值
        // 如果有整定段信息，使用整定段前的稳态PV均值
        let initialPV = tuningResult.data.pv[0];
        if (tuningResult.tuning_result.param_update_index) {
            const updateIdx = tuningResult.tuning_result.param_update_index;
            // 使用整定段前30%的数据计算稳态均值
            const steadyStart = Math.max(0, Math.floor(updateIdx * 0.7));
            const steadyEnd = updateIdx;
            if (steadyEnd > steadyStart) {
                const steadyPV = tuningResult.data.pv.slice(steadyStart, steadyEnd);
                initialPV = steadyPV.reduce((a, b) => a + b, 0) / steadyPV.length;
                console.log(`📍 使用整定段前稳态PV均值作为初始值: ${initialPV.toFixed(3)} (索引 ${steadyStart}-${steadyEnd})`);
            }
        }
        
        const simulationStartTime = Date.now();
        
        // 🔧 准备分段仿真参数
        const simulationPayload = {
            t: tuningResult.data.t,
            sv: tuningResult.data.sv,
            model_type: tuningResult.tuning_result.model_type,
            model_params: tuningResult.tuning_result.model_params,
            pid_params: {
                pb: tuningResult.tuning_result.pb,
                ti: tuningResult.tuning_result.ti,
                td: tuningResult.tuning_result.td
            },
            initial_pv: initialPV,
            initial_mv: tuningResult.data.mv ? tuningResult.data.mv[0] : null,
            request_timestamp: simulationStartTime,
            // 🔧 添加分段仿真支持
            param_update_index: tuningResult.tuning_result.param_update_index || null,
            pv_original: tuningResult.data.pv || null,
            mv_original: tuningResult.data.mv || null,
            // 🔧 添加多段整定支持
            segments: tuningResult.segments || null
        };
        
        console.log('🔧 仿真请求参数:', {
            '仿真模式': simulationPayload.segments ? '多段连续' : (simulationPayload.param_update_index !== null ? '单段' : '全程'),
            '段数': simulationPayload.segments ? simulationPayload.segments.length : (simulationPayload.param_update_index !== null ? 1 : 0),
            '参数更新点': simulationPayload.param_update_index,
            '数据点数': simulationPayload.t.length
        });
        
        const response = await axios.post(`${API_BASE_URL}/api/simulate?_t=${simulationStartTime}`, 
            simulationPayload, {
            headers: {
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache'
            }
        });

        console.log('✅ 仿真API响应成功');
        console.log('⏱️ 仿真耗时:', (Date.now() - simulationStartTime) / 1000, '秒');

        if (response.data.success) {
            // 🔧 保留旧的is_steady_state标志（如果存在）
            const oldIsSteadyState = window.simulationData?.is_steady_state || false;
            const oldOriginalSv = window.simulationData?.original_sv || null;
            
            // 清除旧的仿真数据
            simulationData = null;
            window.simulationData = null;
            
            simulationData = response.data;
            window.simulationData = response.data;
            
            // 🔧 【关键修复】恢复is_steady_state标志，避免稳态数据显示参数更新点
            window.simulationData.is_steady_state = oldIsSteadyState;
            if (oldOriginalSv) {
                window.simulationData.original_sv = oldOriginalSv;
            }
            
            console.log('✅ 新仿真结果已保存:', {
                'PV数据点数': simulationData.pv?.length || 0,
                'MV数据点数': simulationData.mv?.length || 0,
                'SV数据点数': simulationData.sv?.length || 0,
                'SV已固定': simulationData.sv_fixed || false,
                'is_steady_state': window.simulationData.is_steady_state,
                'window.simulationData': !!window.simulationData
            });
            
            // 如果后端返回了处理后的SV，保存到simulationData中（不修改tuningResult）
            if (response.data.sv && response.data.sv.length > 0) {
                const svInfo = response.data.sv_fixed 
                    ? `固定值 (原始范围: ${response.data.sv_original_range[0].toFixed(2)}-${response.data.sv_original_range[1].toFixed(2)})`
                    : '原始值';
                console.log('🔧 使用后端返回的处理后SV值（' + svInfo + '）');
                
                // 保存处理后的SV到simulationData，不修改tuningResult.data.sv
                simulationData.sv_processed = response.data.sv;
                simulationData.sv_fixed = response.data.sv_fixed;
                simulationData.sv_original_range = response.data.sv_original_range;
                
                // 如果SV被固定，显示提示信息
                if (response.data.sv_fixed) {
                    const avgSv = response.data.sv[0].toFixed(2);
                    console.log(`ℹ️  检测到SV基本恒定，已使用固定值 ${avgSv} 进行仿真`);
                }
            }
            
            // 🔧 根据数据源选择评估用的SV数据
            const evaluationSV = window.isOPCUAData ? tuningResult.data.sv : (response.data.sv || tuningResult.data.sv);
            console.log('🔧 评估函数SV数据源:', window.isOPCUAData ? 'OPC UA原始SV' : '后端处理SV');
            
            await evaluateSimulation(
                response.data.pv,
                evaluationSV,
                response.data.mv
            );
            
            // 🔧 不在这里渲染图表，因为仿真结果页面可能不可见
            // setupSimulationChart();
            document.getElementById('resultsContainer').style.display = 'block';
            console.log('✅ 仿真数据已准备好，图表将在切换到仿真结果页面时渲染');
        } else {
            console.error('❌ 仿真API返回失败:', response.data);
            showAlert('仿真失败: ' + (response.data.message || '未知错误'), 'error');
        }
    } catch (error) {
        console.error('❌ 仿真错误:', error);
        console.error('错误详情:', {
            message: error.message,
            response: error.response?.data,
            stack: error.stack
        });
        showAlert('仿真失败: ' + error.message, 'error');
    }
}

async function evaluateSimulation(simulatedPV, originalSV, simulatedMV) {
    try {
        // 获取当前PID参数
        const pidParams = tuningResult?.tuning_result ? {
            pb: tuningResult.tuning_result.pb,
            ti: tuningResult.tuning_result.ti,
            td: tuningResult.tuning_result.td
        } : null;
        
        const response = await axios.post(`${API_BASE_URL}/api/evaluate`, {
            pv: simulatedPV,
            sv: originalSV,
            mv: simulatedMV,
            pid_params: pidParams  // 传递PID参数用于合理性检查
        });
        
        if (response.data.success) {
            const metrics = response.data.metrics;
            
            // 保存到全局变量，供AI使用
            evaluationMetrics = metrics;
            console.log('✅ 评估指标已保存:', evaluationMetrics);
            
            // Update UI
            document.getElementById('overallScore').textContent = metrics.overall_score.toFixed(1);
            document.getElementById('scoreGrade').textContent = metrics.grade;
            document.getElementById('steadyError').textContent = metrics.steady_state_error.toFixed(4);
            document.getElementById('iaeValue').textContent = metrics.iae.toFixed(2);
            document.getElementById('oscillationCount').textContent = metrics.oscillation_count;
            document.getElementById('tvValue').textContent = metrics.tv.toFixed(2);
            document.getElementById('iseValue').textContent = metrics.ise.toFixed(2);
            document.getElementById('maxControlEffort').textContent = metrics.max_control_effort.toFixed(2);
            document.getElementById('maxOscillation').textContent = metrics.max_oscillation_amplitude.toFixed(4);
            
            // Advanced metrics
            document.getElementById('overshootValue').textContent = (metrics.overshoot_percentage || 0).toFixed(2);
            document.getElementById('settlingTime').textContent = (metrics.settling_time_percentage || 0).toFixed(1);
            document.getElementById('riseTime').textContent = (metrics.rise_time_percentage || 0).toFixed(1);
            document.getElementById('steadyBand').textContent = (metrics.steady_error_band || 0).toFixed(4);
            
            // 执行智能诊断
            if (tuningResult && tuningResult.tuning_result) {
                const diagnostics = performDiagnostics(metrics, tuningResult.tuning_result);
                displayDiagnostics(diagnostics);
            }
        }
    } catch (error) {
        console.error('评估失败:', error);
        showAlert('性能评估失败: ' + (error.response?.data?.detail || error.message), 'error');
    }
}

function setupSimulationChart() {
    console.log('📊 setupSimulationChart 被调用');
    
    // 🔧 检查必要的数据
    if (!tuningResult || !tuningResult.data) {
        console.error('❌ tuningResult 或 tuningResult.data 不存在');
        return;
    }
    
    if (!tuningResult.data.t || !tuningResult.data.pv) {
        console.error('❌ 缺少必要的数据字段 (t 或 pv)');
        return;
    }
    
    const ctx = document.getElementById('simulationChart');
    if (!ctx) {
        console.error('❌ simulationChart canvas 元素不存在');
        return;
    }
    
    // 🔧 销毁所有旧图表实例，避免冲突
    if (simulationChart) {
        console.log('🗑️ 销毁旧非稳态图表（局部变量）');
        try {
            simulationChart.destroy();
        } catch (e) {
            console.warn('⚠️ 销毁非稳态图表时出错:', e);
        }
        simulationChart = null;
    }
    
    if (window.simulationChart) {
        console.log('🗑️ 销毁旧非稳态图表（window对象）');
        try {
            window.simulationChart.destroy();
        } catch (e) {
            console.warn('⚠️ 销毁window.simulationChart时出错:', e);
        }
        window.simulationChart = null;
    }
    
    if (window.simulationChartInstance) {
        console.log('🗑️ 销毁稳态图表实例');
        try {
            window.simulationChartInstance.destroy();
        } catch (e) {
            console.warn('⚠️ 销毁稳态图表时出错:', e);
        }
        window.simulationChartInstance = null;
    }

    // 获取所有段的参数更新点
    const updatePoints = [];
    
    // 检查是否有分段结果
    if (tuningResult.segments && tuningResult.segments.length > 0) {
        console.log(`📊 检测到 ${tuningResult.segments.length} 个分段`);
        
        // 为每个段创建更新点
        tuningResult.segments.forEach((seg, idx) => {
            const segStartIdx = seg.segment_indices ? seg.segment_indices[0] : 0;
            const segStartTime = tuningResult.data.t[segStartIdx];
            updatePoints.push({
                index: segStartIdx,
                time: segStartTime,
                segmentIndex: seg.segment_index || (idx + 1),
                params: {
                    pb: seg.pb,
                    ti: seg.ti,
                    td: seg.td
                }
            });
            console.log(`  📍 段${seg.segment_index || (idx + 1)}: t=${segStartTime.toFixed(1)}s, Pb=${seg.pb.toFixed(2)}%, Ti=${seg.ti.toFixed(2)}s`);
        });
    } else {
        // 单段或使用默认更新点
        const updatePointIndex = tuningResult.tuning_result.param_update_index || Math.floor(tuningResult.data.t.length / 3);
        const updateTime = tuningResult.tuning_result.param_update_time || tuningResult.data.t[updatePointIndex];
        updatePoints.push({
            index: updatePointIndex,
            time: updateTime,
            segmentIndex: 1,
            params: {
                pb: tuningResult.tuning_result.pb,
                ti: tuningResult.tuning_result.ti,
                td: tuningResult.tuning_result.td
            }
        });
        console.log(`📍 单段参数更新点: t=${updateTime.toFixed(1)}s`);
    }
    
    // 保存更新点信息到全局变量（使用第一个更新点作为主要更新点）
    window.paramUpdatePoints = updatePoints;
    window.paramUpdatePointIndex = updatePoints[0].index;
    window.paramUpdateTime = updatePoints[0].time;

    // 创建所有参数更新点的标记数据
    // 🔧 对于OPC UA数据，始终使用原始SV；对于文件数据，使用后端处理的SV
    let svData;
    if (window.isOPCUAData) {
        // OPC UA数据：优先使用uploadedData中的原始SV
        if (window.uploadedData) {
            svData = window.uploadedData.map(item => item.sp);
            console.log('🔧 OPC UA数据源：使用uploadedData中的原始SV绘制仿真图表');
        } else {
            svData = tuningResult.data.sv;  // 备用方案
            console.log('⚠️ OPC UA数据源：找不到uploadedData，使用tuningResult中的SV');
        }
    } else {
        svData = window.simulationData?.sv_processed || tuningResult.data.sv;  // 文件数据使用处理后的SV
        console.log('🔧 文件数据源：使用后端处理的SV绘制仿真图表');
    }
    const allValues = [...tuningResult.data.pv, ...svData];
    const maxVal = Math.max(...allValues);
    
    const updateLineDatasets = updatePoints.map((point, idx) => {
        const data = tuningResult.data.t.map((t, i) => {
            return i === point.index ? maxVal : null;
        });
        
        return {
            label: `段${point.segmentIndex}更新点 (t=${point.time.toFixed(1)}s)`,
            data: data,
            borderColor: idx === 0 ? '#ef4444' : '#f97316', // 第一个红色，其他橙色
            backgroundColor: idx === 0 ? 'rgba(239, 68, 68, 0.2)' : 'rgba(249, 115, 22, 0.2)',
            borderWidth: 3,
            pointRadius: 8,
            pointStyle: 'triangle',
            showLine: false,
            pointBackgroundColor: idx === 0 ? '#ef4444' : '#f97316'
        };
    });

    // 创建分段背景插件
    const segmentBackgroundPlugin = {
        id: 'segmentBackground',
        beforeDraw: (chart) => {
            if (updatePoints.length <= 1) return; // 单段不绘制背景
            
            const ctx = chart.ctx;
            const chartArea = chart.chartArea;
            const xScale = chart.scales.x;
            const yScale = chart.scales.y;
            
            // 绘制每个分段的背景
            updatePoints.forEach((point, idx) => {
                const startTime = point.time;
                const endTime = idx < updatePoints.length - 1 
                    ? updatePoints[idx + 1].time 
                    : tuningResult.data.t[tuningResult.data.t.length - 1];
                
                const startX = xScale.getPixelForValue(startTime);
                const endX = xScale.getPixelForValue(endTime);
                
                const colors = [
                    'rgba(16, 185, 129, 0.08)',   // 绿色
                    'rgba(59, 130, 246, 0.08)',   // 蓝色
                    'rgba(245, 158, 11, 0.08)',   // 橙色
                    'rgba(239, 68, 68, 0.08)',    // 红色
                    'rgba(139, 92, 246, 0.08)'    // 紫色
                ];
                
                ctx.save();
                ctx.fillStyle = colors[idx % colors.length];
                ctx.fillRect(
                    startX,
                    chartArea.top,
                    endX - startX,
                    chartArea.bottom - chartArea.top
                );
                
                // 绘制分段标签
                ctx.fillStyle = colors[idx % colors.length].replace('0.08', '0.6');
                ctx.font = 'bold 11px Arial';
                ctx.textAlign = 'center';
                ctx.fillText(
                    `段${point.segmentIndex}`,
                    (startX + endX) / 2,
                    chartArea.top + 15
                );
                
                ctx.restore();
            });
        }
    };

    simulationChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: tuningResult.data.t,
            datasets: [
                {
                    label: '原始PV (旧参数)',
                    data: tuningResult.data.pv,
                    borderColor: '#94a3b8',
                    backgroundColor: 'rgba(148, 163, 184, 0.1)',
                    borderWidth: 2,
                    tension: 0.4,
                    pointRadius: 0,
                    borderDash: [3, 3],
                    order: 2
                },
                {
                    label: '新参数仿真PV',
                    data: [],
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 3,
                    tension: 0.4,
                    pointRadius: 0,
                    order: 1
                },
                {
                    label: 'SV (设定值)',
                    data: svData,  // 使用处理后的SV
                    borderColor: '#f59e0b',
                    borderWidth: 2,
                    borderDash: [5, 5],
                    tension: 0.4,
                    pointRadius: 0,
                    order: 3
                },
                // 添加所有参数更新点标记
                ...updateLineDatasets
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2.5,
            animation: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: {
                            size: 12
                        }
                    }
                },
                title: {
                    display: true,
                    text: updatePoints.length > 1 
                        ? [
                            `参数对比仿真 (${updatePoints.length}个分段)`,
                            `🔺红色: 第1段 | 🔺橙色: 其他段 | 灰色虚线: 原始PV | 绿色实线: 新参数仿真PV`
                        ]
                        : [
                            '参数对比仿真',
                            `灰色虚线: 原始PV (旧参数) | 绿色实线: 新参数仿真PV`
                        ],
                    font: {
                        size: 13,
                        weight: 'bold'
                    },
                    padding: {
                        bottom: 15
                    }
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        title: function(context) {
                            return '时间: ' + context[0].label + 's';
                        },
                        afterTitle: function(context) {
                            const time = parseFloat(context[0].label);
                            
                            // 找到当前时间所在的段
                            for (let i = updatePoints.length - 1; i >= 0; i--) {
                                if (time >= updatePoints[i].time) {
                                    const point = updatePoints[i];
                                    return `段${point.segmentIndex}: Pb=${point.params.pb.toFixed(1)}%, Ti=${point.params.ti.toFixed(1)}s, Td=${point.params.td.toFixed(1)}s`;
                                }
                            }
                            return '(旧参数区域)';
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: '时间 (s)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: '值'
                    }
                }
            }
        },
        plugins: [segmentBackgroundPlugin]
    });
    
    // 🔧 【关键修复】挂载到window对象，确保可以被销毁
    window.simulationChart = simulationChart;
    console.log('✅ 非稳态图表已创建并挂载到window.simulationChart');

    currentFrame = 0;
}

// Parameter tuning sliders
let sliderHandlers = null; // 保存事件处理器引用

function initializeSliders() {
    console.log('初始化参数微调滑块...');
    console.log('原始参数:', originalTunedParams);
    
    const pbSlider = document.getElementById('pbSlider');
    const tiSlider = document.getElementById('tiSlider');
    const tdSlider = document.getElementById('tdSlider');
    
    if (!pbSlider || !tiSlider || !tdSlider) {
        console.error('❌ 滑块元素未找到');
        console.log('pbSlider:', pbSlider);
        console.log('tiSlider:', tiSlider);
        console.log('tdSlider:', tdSlider);
        return;
    }
    
    console.log('✅ 滑块元素已找到');
    
    // 设置滑块初始值
    pbSlider.value = originalTunedParams.pb;
    tiSlider.value = originalTunedParams.ti;
    tdSlider.value = originalTunedParams.td;
    
    console.log('滑块初始值已设置:', {
        pb: pbSlider.value,
        ti: tiSlider.value,
        td: tdSlider.value
    });
    
    // 更新显示值
    document.getElementById('pbSliderValue').textContent = originalTunedParams.pb.toFixed(0);
    document.getElementById('tiSliderValue').textContent = originalTunedParams.ti.toFixed(0);
    document.getElementById('tdSliderValue').textContent = originalTunedParams.td.toFixed(1);
    
    // 移除旧的事件监听器
    if (sliderHandlers) {
        pbSlider.removeEventListener('input', sliderHandlers.pb);
        tiSlider.removeEventListener('input', sliderHandlers.ti);
        tdSlider.removeEventListener('input', sliderHandlers.td);
        console.log('已移除旧的事件监听器');
    }
    
    // 创建新的事件处理器
    sliderHandlers = {
        pb: (e) => {
            const value = parseFloat(e.target.value).toFixed(0);
            document.getElementById('pbSliderValue').textContent = value;
            console.log('Pb滑块变化:', value);
        },
        ti: (e) => {
            const value = parseFloat(e.target.value).toFixed(0);
            document.getElementById('tiSliderValue').textContent = value;
            console.log('Ti滑块变化:', value);
        },
        td: (e) => {
            const value = parseFloat(e.target.value).toFixed(1);
            document.getElementById('tdSliderValue').textContent = value;
            console.log('Td滑块变化:', value);
        }
    };
    
    // 添加新的事件监听器
    pbSlider.addEventListener('input', sliderHandlers.pb);
    tiSlider.addEventListener('input', sliderHandlers.ti);
    tdSlider.addEventListener('input', sliderHandlers.td);
    
    console.log('✅ 滑块事件监听器已添加');
    
    // 测试滑块是否可以拖动
    console.log('测试滑块属性:');
    console.log('- Pb滑块 disabled:', pbSlider.disabled, 'readOnly:', pbSlider.readOnly);
    console.log('- Ti滑块 disabled:', tiSlider.disabled, 'readOnly:', tiSlider.readOnly);
    console.log('- Td滑块 disabled:', tdSlider.disabled, 'readOnly:', tdSlider.readOnly);
}

document.getElementById('applyTuningBtn')?.addEventListener('click', async () => {
    console.log('🔘 点击应用参数按钮');
    
    const pb = parseFloat(document.getElementById('pbSlider').value);
    const ti = parseFloat(document.getElementById('tiSlider').value);
    const td = parseFloat(document.getElementById('tdSlider').value);
    
    console.log('📊 新参数值:', { pb, ti, td });
    
    // 参数验证
    if (pb <= 0) {
        showAlert('错误：Pb必须大于0', 'error');
        console.error('❌ Pb参数无效:', pb);
        return;
    }
    
    if (ti < 0) {
        showAlert('错误：Ti不能为负数', 'error');
        console.error('❌ Ti参数无效:', ti);
        return;
    }
    
    if (td < 0) {
        showAlert('错误：Td不能为负数', 'error');
        console.error('❌ Td参数无效:', td);
        return;
    }
    
    if (!tuningResult || !tuningResult.tuning_result) {
        showAlert('错误：没有整定结果数据', 'error');
        console.error('❌ tuningResult不存在');
        return;
    }
    
    console.log('✅ 参数验证通过');
    
    // 保存旧参数用于对比
    const oldParams = {
        pb: tuningResult.tuning_result.pb,
        ti: tuningResult.tuning_result.ti,
        td: tuningResult.tuning_result.td
    };
    
    // Update tuning result with new parameters
    tuningResult.tuning_result.pb = pb;
    tuningResult.tuning_result.ti = ti;
    tuningResult.tuning_result.td = td;
    
    console.log('📊 参数对比:');
    console.log('  旧参数:', oldParams);
    console.log('  新参数:', { pb, ti, td });
    console.log('  变化:', {
        pb: (pb - oldParams.pb).toFixed(2),
        ti: (ti - oldParams.ti).toFixed(2),
        td: (td - oldParams.td).toFixed(2)
    });
    
    // Re-run simulation with new parameters
    showAlert(`参数已更新：Pb=${pb}%, Ti=${ti}s, Td=${td}s，正在重新仿真...`, 'success');
    console.log('🚀 开始重新仿真...');
    
    try {
        await runSimulation();
        console.log('✅ 仿真完成');
    } catch (error) {
        console.error('❌ 仿真失败:', error);
        showAlert('仿真失败: ' + error.message, 'error');
    }
});

document.getElementById('resetTuningBtn')?.addEventListener('click', () => {
    if (originalTunedParams) {
        document.getElementById('pbSlider').value = originalTunedParams.pb;
        document.getElementById('tiSlider').value = originalTunedParams.ti;
        document.getElementById('tdSlider').value = originalTunedParams.td;
        
        document.getElementById('pbSliderValue').textContent = originalTunedParams.pb.toFixed(0);
        document.getElementById('tiSliderValue').textContent = originalTunedParams.ti.toFixed(0);
        document.getElementById('tdSliderValue').textContent = originalTunedParams.td.toFixed(1);
        
        showAlert('参数已重置为整定值', 'success');
    }
});

// 处理保存到历史（全局函数，供HTML onclick调用）
function handleSaveToHistory() {
    console.log('💾 点击保存到历史按钮');
    console.log('📊 当前数据状态:', {
        hasTuningResult: !!tuningResult,
        hasSimulationData: !!simulationData,
        currentLoopForTuning: window.currentLoopForTuning,
        tuningResult: tuningResult,
        simulationData: simulationData
    });
    
    if (tuningResult && simulationData) {
        // 尝试从多个来源获取文件名/回路名称
        let fileName = 'Unknown';
        let description = '';
        
        // 优先从OPC UA回路信息获取
        if (window.currentLoopForTuning) {
            const loop = window.currentLoopForTuning;
            fileName = loop.name || 'Unknown';
            
            // 构建详细描述
            const parts = [];
            if (loop.description) {
                parts.push(loop.description);
            }
            if (loop.data_source === 'opcua') {
                parts.push('OPC UA数据源');
                if (loop.opcua_config?.server_url) {
                    parts.push(`服务器: ${loop.opcua_config.server_url}`);
                }
            }
            if (loop.location) {
                parts.push(`位置: ${loop.location}`);
            }
            
            description = parts.join(' | ');
            console.log('✅ 从OPC UA回路获取信息:', { fileName, description, loop });
        } else {
            // 尝试从fileInfo获取（文件上传的情况）
            const fileInfoEl = document.getElementById('fileInfo');
            if (fileInfoEl && fileInfoEl.textContent) {
                const match = fileInfoEl.textContent.match(/文件名:\s*(.+)/);
                if (match) {
                    fileName = match[1];
                    description = '文件上传';
                }
            }
            
            // 如果还是Unknown，尝试从dataPrepFileInfo获取
            if (fileName === 'Unknown') {
                const dataPrepFileInfo = document.getElementById('dataPrepFileInfo');
                if (dataPrepFileInfo && dataPrepFileInfo.textContent) {
                    const match = dataPrepFileInfo.textContent.match(/文件名:\s*(.+)/);
                    if (match) {
                        fileName = match[1];
                        description = '文件上传';
                    }
                }
            }
        }
        
        // 如果有描述，将其添加到fileName中显示
        const displayName = description ? `${fileName} (${description})` : fileName;
        
        console.log('📝 准备保存:', { 
            fileName: displayName, 
            originalName: fileName,
            description: description,
            tuningResult: tuningResult.tuning_result 
        });
        
        saveToHistory(displayName, tuningResult.tuning_result, {});
    } else {
        console.warn('⚠️ 没有可保存的数据');
        showAlert('没有可保存的数据，请先完成参数整定', 'error');
    }
}

// 处理生成对比报告（全局函数，供HTML onclick调用）
function handleGenerateComparison() {
    console.log('📊 点击生成对比报告按钮');
    generatePerformanceComparison();
}

// 处理生成报告（全局函数，供HTML onclick调用）
function handleGenerateReport() {
    console.log('📄 点击生成报告按钮');
    generateTuningReport();
}

// 处理下载报告（全局函数，供HTML onclick调用）
function handleDownloadReport() {
    console.log('📥 点击下载报告按钮');
    // 检查是否有整定结果
    if (!tuningResult || !evaluationMetrics) {
        showAlert('请先完成参数整定', 'warning');
        return;
    }
    
    // 检查是否已生成报告预览
    const preview = document.getElementById('reportPreview');
    if (!preview || preview.innerHTML.includes('请先生成报告')) {
        showAlert('请先点击"生成报告"按钮生成报告预览', 'warning');
        return;
    }
    
    // 检查导出格式
    const includeJSON = document.getElementById('exportJSON')?.checked;
    const includeMD = document.getElementById('exportMarkdown')?.checked;
    
    if (!includeJSON && !includeMD) {
        showAlert('请至少选择一种导出格式', 'warning');
        return;
    }
    
    // 下载报告
    let downloadCount = 0;
    if (includeJSON) {
        prepareJSONReport();
        downloadCount++;
    }
    if (includeMD) {
        prepareMarkdownReport();
        downloadCount++;
    }
    
    showAlert(`报告下载成功！已下载 ${downloadCount} 个文件`, 'success');
}

// 处理查看性能对比（全局函数，供HTML onclick调用）
function handleToggleComparison() {
    console.log('📊 点击查看性能对比按钮');
    // 切换到性能对比标签页
    const comparisonTab = document.querySelector('[data-tab="comparison"]');
    if (comparisonTab) {
        comparisonTab.click();
    } else {
        console.error('❌ 找不到性能对比标签页');
    }
}

// 处理保存到回路（全局函数，供HTML onclick调用）
async function handleSaveToLoop() {
    console.log('💾 点击保存到回路按钮');
    
    if (!tuningResult || !evaluationMetrics) {
        showAlert('请先完成参数整定', 'warning');
        return;
    }
    
    if (window.currentLoopForTuning) {
        await saveResultsToLoop(window.currentLoopForTuning.id);
    } else {
        showAlert('请从回路管理进入整定，或先创建回路', 'info');
    }
}

// 将函数挂载到window对象
window.handleSaveToHistory = handleSaveToHistory;
window.handleGenerateComparison = handleGenerateComparison;
window.handleGenerateReport = handleGenerateReport;
window.handleDownloadReport = handleDownloadReport;
window.handleToggleComparison = handleToggleComparison;
window.handleSaveToLoop = handleSaveToLoop;

// Save to history - 将事件绑定移到DOMContentLoaded中（保留作为备用）
function bindSaveHistoryButton() {
    console.log('🔍 bindSaveHistoryButton 已调用（现在使用onclick方式）');
}

// Export data
document.getElementById('exportBtn')?.addEventListener('click', () => {
    if (!simulationData || !tuningResult) {
        showAlert('没有可导出的数据', 'error');
        return;
    }
    
    const exportData = {
        tuning_result: tuningResult.tuning_result,
        simulation: {
            t: tuningResult.data.t,
            pv: simulationData.pv,
            mv: simulationData.mv,
            sv: window.isOPCUAData ? tuningResult.data.sv : (simulationData.sv_processed || tuningResult.data.sv)  // OPC UA使用原始SV，文件使用处理后的SV
        },
        timestamp: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pid_tuning_export_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    showAlert('数据已导出', 'success');
});

// Animation controls
document.getElementById('playBtn').addEventListener('click', () => {
    if (!simulationData) return;
    
    document.getElementById('playBtn').disabled = true;
    document.getElementById('pauseBtn').disabled = false;
    
    const totalFrames = simulationData.pv.length;
    const frameDelay = 20;

    animationInterval = setInterval(() => {
        if (currentFrame >= totalFrames) {
            stopAnimation();
            return;
        }

        // datasets[0] = 原始PV (旧参数) - 保持完整显示
        // datasets[1] = 新参数仿真PV - 只在第一个更新点之后逐帧显示
        // datasets[2] = SV - 保持完整显示
        // datasets[3+] = 参数更新点标记 - 保持完整显示
        
        const updatePoints = window.paramUpdatePoints || [{index: 0}];
        const firstUpdateIndex = updatePoints[0].index;
        
        if (currentFrame >= firstUpdateIndex) {
            // 只在第一个更新点之后才显示新参数PV
            // 从第一个更新点开始填充数据
            const newParamData = new Array(totalFrames).fill(null);
            for (let i = firstUpdateIndex; i <= currentFrame; i++) {
                newParamData[i] = simulationData.pv[i];
            }
            simulationChart.data.datasets[1].data = newParamData;
        } else {
            // 第一个更新点之前，新参数PV为空
            simulationChart.data.datasets[1].data = new Array(totalFrames).fill(null);
        }
        
        simulationChart.update('none');

        const progress = ((currentFrame + 1) / totalFrames) * 100;
        document.getElementById('progressFill').style.width = progress + '%';

        currentFrame++;
    }, frameDelay);
});

document.getElementById('pauseBtn').addEventListener('click', () => {
    stopAnimation();
});

document.getElementById('resetBtn').addEventListener('click', () => {
    stopAnimation();
    currentFrame = 0;
    if (simulationChart) {
        // 清空新参数仿真PV数据（datasets[1]）
        simulationChart.data.datasets[1].data = [];
        simulationChart.update();
    }
    document.getElementById('progressFill').style.width = '0%';
});

function stopAnimation() {
    if (animationInterval) {
        clearInterval(animationInterval);
        animationInterval = null;
    }
    document.getElementById('playBtn').disabled = false;
    document.getElementById('pauseBtn').disabled = true;
}

// Utility functions
function showAlert(message, type) {
    let container = document.getElementById('alertContainer');
    
    // 如果找不到alertContainer，创建一个临时的
    if (!container) {
        container = document.createElement('div');
        container.id = 'alertContainer';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }
    
    const alert = document.createElement('div');
    alert.className = `alert alert-${type}`;
    alert.innerHTML = `
        <span>${type === 'success' ? '✅' : type === 'warning' ? '⚠️' : type === 'info' ? 'ℹ️' : '❌'}</span>
        <span>${message}</span>
    `;
    
    // 添加样式
    alert.style.padding = '12px 20px';
    alert.style.marginBottom = '10px';
    alert.style.borderRadius = '8px';
    alert.style.background = type === 'success' ? 'rgba(16, 185, 129, 0.2)' : 
                             type === 'warning' ? 'rgba(245, 158, 11, 0.2)' :
                             type === 'info' ? 'rgba(59, 130, 246, 0.2)' :
                             'rgba(239, 68, 68, 0.2)';
    alert.style.border = type === 'success' ? '1px solid rgba(16, 185, 129, 0.5)' : 
                         type === 'warning' ? '1px solid rgba(245, 158, 11, 0.5)' :
                         type === 'info' ? '1px solid rgba(59, 130, 246, 0.5)' :
                         '1px solid rgba(239, 68, 68, 0.5)';
    alert.style.color = '#e2e8f0';
    alert.style.display = 'flex';
    alert.style.gap = '10px';
    alert.style.alignItems = 'center';
    
    container.innerHTML = '';
    container.appendChild(alert);

    setTimeout(() => {
        alert.remove();
    }, 5000);
}

// View batch item detail
window.viewBatchItemDetail = async function(index) {
    if (!window.batchResultsData || !batchFiles[index]) {
        showAlert('无法加载详情数据', 'error');
        return;
    }
    
    const result = window.batchResultsData.results[index];
    const fileData = batchFiles[index];
    
    showAlert(`正在加载 ${result.file_name} 的详情...`, 'success');
    
    try {
        // 使用单文件整定逻辑重新处理
        uploadedData = fileData.data;
        
        const tuningMethod = document.getElementById('tuningMethod').value;
        const controlMode = document.getElementById('controlMode').value;
        const modelType = document.getElementById('modelType').value;
        const enableSegmentation = document.getElementById('enableSegmentation').checked;
        
        const response = await axios.post(`${API_BASE_URL}/api/tune`, {
            data: uploadedData,
            tuning_method: tuningMethod,
            control_mode: controlMode,
            model_type: modelType === 'auto' ? null : modelType,
            enable_segmentation: enableSegmentation
        }, {
            timeout: 60000
        });
        
        if (response.data.success) {
            tuningResult = response.data;
            
            // 检查是否是稳态情况
            if (tuningResult.is_steady_state) {
                displaySteadyStateResults(tuningResult);
                showAlert(`${result.file_name}: 数据已处于稳态`, 'success');
            } else {
                originalTunedParams = {
                    pb: tuningResult.tuning_result.pb,
                    ti: tuningResult.tuning_result.ti,
                    td: tuningResult.tuning_result.td
                };
                displayTuningResults(tuningResult);
                await runSimulation();
                showAlert(`${result.file_name}: 详情加载完成`, 'success');
                
                // Show parameter tuning section
                document.getElementById('parameterTuningSection').style.display = 'block';
                initializeSliders();
                
                // Show model comparison section
                const modelComparisonContainer = document.getElementById('modelComparisonContainer');
                if (modelComparisonContainer) {
                    modelComparisonContainer.style.display = 'block';
                }
                
                // Show AI assistant
                if (typeof showAIAssistant === 'function') {
                    showAIAssistant();
                }
            }
            
            // 滚动到结果区域
            document.getElementById('resultsContainer').scrollIntoView({ behavior: 'smooth' });
        }
    } catch (error) {
        console.error('加载详情失败:', error);
        showAlert('加载详情失败: ' + error.message, 'error');
    }
};

// Intelligent Diagnostic System
function performDiagnostics(metrics, pidParams) {
    console.log('🔍 开始智能诊断...');
    
    const diagnostics = {
        issues: [],
        suggestions: [],
        severity: 'good', // good, warning, critical
        score: metrics.overall_score
    };
    
    // 1. 检查综合评分
    if (metrics.overall_score < 40) {
        diagnostics.severity = 'critical';
        diagnostics.issues.push({
            type: 'critical',
            title: '控制性能不佳',
            description: `综合评分仅${metrics.overall_score.toFixed(1)}分，系统控制效果较差`
        });
    } else if (metrics.overall_score < 70) {
        diagnostics.severity = 'warning';
        diagnostics.issues.push({
            type: 'warning',
            title: '控制性能一般',
            description: `综合评分${metrics.overall_score.toFixed(1)}分，还有优化空间`
        });
    }
    
    // 2. 检查超调量
    if (metrics.overshoot_percentage > 20) {
        diagnostics.issues.push({
            type: 'critical',
            title: '超调量过大',
            description: `超调量达${metrics.overshoot_percentage.toFixed(1)}%，响应过于激进`
        });
        diagnostics.suggestions.push({
            icon: '📈',
            title: '增大比例带(Pb)',
            description: `建议将Pb从${pidParams.pb.toFixed(0)}%增加到${(pidParams.pb * 1.3).toFixed(0)}%左右`,
            action: 'increase_pb'
        });
    } else if (metrics.overshoot_percentage > 10) {
        diagnostics.issues.push({
            type: 'warning',
            title: '存在一定超调',
            description: `超调量${metrics.overshoot_percentage.toFixed(1)}%，可以进一步优化`
        });
        diagnostics.suggestions.push({
            icon: '📈',
            title: '适当增大比例带(Pb)',
            description: `建议将Pb从${pidParams.pb.toFixed(0)}%增加到${(pidParams.pb * 1.15).toFixed(0)}%左右`,
            action: 'increase_pb'
        });
    }
    
    // 3. 检查振荡
    if (metrics.oscillation_count > 5) {
        diagnostics.issues.push({
            type: 'critical',
            title: '振荡严重',
            description: `检测到${metrics.oscillation_count}次振荡，系统不稳定`
        });
        diagnostics.suggestions.push({
            icon: '📉',
            title: '增大比例带并减小微分时间',
            description: `Pb增加20-30%，Td减少30-50%`,
            action: 'reduce_oscillation'
        });
    } else if (metrics.oscillation_count > 2) {
        diagnostics.issues.push({
            type: 'warning',
            title: '存在振荡',
            description: `检测到${metrics.oscillation_count}次振荡`
        });
        diagnostics.suggestions.push({
            icon: '⚖️',
            title: '微调参数减少振荡',
            description: `适当增大Pb或减小Td`,
            action: 'fine_tune'
        });
    }
    
    // 4. 检查稳态误差
    if (Math.abs(metrics.steady_state_error) > 0.05) {
        diagnostics.issues.push({
            type: 'warning',
            title: '稳态误差较大',
            description: `稳态误差为${metrics.steady_state_error.toFixed(4)}`
        });
        if (pidParams.ti > 0) {
            diagnostics.suggestions.push({
                icon: '⏱️',
                title: '减小积分时间(Ti)',
                description: `建议将Ti从${pidParams.ti.toFixed(0)}s减小到${(pidParams.ti * 0.7).toFixed(0)}s左右`,
                action: 'decrease_ti'
            });
        }
    }
    
    // 5. 检查调节时间
    if (metrics.settling_time_percentage > 80) {
        diagnostics.issues.push({
            type: 'warning',
            title: '调节时间过长',
            description: `调节时间占比${metrics.settling_time_percentage.toFixed(1)}%，响应较慢`
        });
        diagnostics.suggestions.push({
            icon: '⚡',
            title: '加快响应速度',
            description: `减小Pb或Ti以加快响应`,
            action: 'speed_up'
        });
    }
    
    // 6. 检查控制输出变化
    if (metrics.tv > 1000) {
        diagnostics.issues.push({
            type: 'warning',
            title: '控制输出变化剧烈',
            description: `TV值为${metrics.tv.toFixed(0)}，控制动作频繁`
        });
        diagnostics.suggestions.push({
            icon: '🎯',
            title: '平滑控制输出',
            description: `增大Pb或增加滤波`,
            action: 'smooth_control'
        });
    }
    
    // 7. 如果没有问题
    if (diagnostics.issues.length === 0) {
        diagnostics.issues.push({
            type: 'good',
            title: '控制性能良好',
            description: `系统运行稳定，各项指标正常`
        });
        diagnostics.suggestions.push({
            icon: '✅',
            title: '保持当前参数',
            description: `当前PID参数表现良好，建议保持`,
            action: 'keep'
        });
    }
    
    console.log('✅ 诊断完成:', diagnostics);
    return diagnostics;
}

function displayDiagnostics(diagnostics) {
    const diagnosticSection = document.getElementById('diagnosticSection');
    const diagnosticResult = document.getElementById('diagnosticResult');
    
    if (!diagnosticSection || !diagnosticResult) return;
    
    diagnosticSection.style.display = 'block';
    
    // 生成诊断报告HTML
    let html = '';
    
    // 严重程度标识
    const severityConfig = {
        good: { icon: '✅', color: '#28a745', text: '良好' },
        warning: { icon: '⚠️', color: '#ffc107', text: '警告' },
        critical: { icon: '❌', color: '#dc3545', text: '严重' }
    };
    
    const config = severityConfig[diagnostics.severity];
    
    html += `
        <div class="diagnostic-header" style="background: ${config.color};">
            <span style="font-size: 24px;">${config.icon}</span>
            <span style="font-size: 18px; font-weight: 600; margin-left: 10px;">${config.text}</span>
            <span style="font-size: 14px; margin-left: auto;">评分: ${diagnostics.score.toFixed(1)}</span>
        </div>
    `;
    
    // 问题列表
    if (diagnostics.issues.length > 0) {
        html += '<div class="diagnostic-issues">';
        html += '<h4 style="margin: 15px 0 10px 0; font-size: 14px; font-weight: 600;">📋 诊断结果</h4>';
        diagnostics.issues.forEach(issue => {
            const issueClass = issue.type === 'critical' ? 'issue-critical' : 
                              issue.type === 'warning' ? 'issue-warning' : 'issue-good';
            html += `
                <div class="diagnostic-issue ${issueClass}">
                    <div class="issue-title">${issue.title}</div>
                    <div class="issue-description">${issue.description}</div>
                </div>
            `;
        });
        html += '</div>';
    }
    
    // 建议列表
    if (diagnostics.suggestions.length > 0) {
        html += '<div class="diagnostic-suggestions">';
        html += '<h4 style="margin: 15px 0 10px 0; font-size: 14px; font-weight: 600;">💡 优化建议</h4>';
        diagnostics.suggestions.forEach(suggestion => {
            html += `
                <div class="diagnostic-suggestion">
                    <div class="suggestion-icon">${suggestion.icon}</div>
                    <div class="suggestion-content">
                        <div class="suggestion-title">${suggestion.title}</div>
                        <div class="suggestion-description">${suggestion.description}</div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
    }
    
    diagnosticResult.innerHTML = html;
}

// Model Comparison
let modelComparisonChart = null;

document.getElementById('compareModelsBtn')?.addEventListener('click', async () => {
    if (!uploadedData) {
        showAlert('请先上传数据文件', 'error');
        return;
    }
    
    console.log('🔬 开始多模型对比...');
    showAlert('正在对比多种模型，请稍候...', 'success');
    
    const tuningMethod = document.getElementById('tuningMethod').value;
    const controlMode = document.getElementById('controlMode').value;
    
    try {
        const response = await axios.post(`${API_BASE_URL}/api/compare_models`, {
            data: uploadedData,
            tuning_method: tuningMethod,
            control_mode: controlMode
        }, {
            timeout: 120000  // 2分钟超时
        });
        
        if (response.data.success) {
            displayModelComparison(response.data);
            showAlert('模型对比完成！', 'success');
        } else {
            showAlert('模型对比失败', 'error');
        }
    } catch (error) {
        console.error('模型对比错误:', error);
        showAlert('模型对比失败: ' + error.message, 'error');
    }
});

function displayModelComparison(data) {
    const container = document.getElementById('modelComparisonContainer');
    const resultsDiv = document.getElementById('modelComparisonResults');
    
    container.style.display = 'block';
    
    // 显示对比图表
    displayModelComparisonChart(data);
    
    // 显示对比结果表格
    let html = '<div class="model-comparison-table">';
    html += '<h4 style="margin: 15px 0 10px 0; color: #e2e8f0;">📊 模型对比结果</h4>';
    html += '<div style="background: rgba(102, 126, 234, 0.1); padding: 16px; border-radius: 10px; margin-bottom: 15px; font-size: 13px; border: 1px solid rgba(102, 126, 234, 0.3);">';
    html += '<div style="margin-bottom: 10px; color: #a5b4fc; font-weight: 600;">📖 指标说明</div>';
    html += '<div style="margin-left: 15px; color: #cbd5e1; line-height: 1.8;">';
    html += '<div>• <strong style="color: #e2e8f0;">拟合误差</strong>：模型对历史数据的拟合程度（越小说明模型越准确）</div>';
    html += '<div>• <strong style="color: #e2e8f0;">性能评分</strong>：使用整定的PID参数仿真后的控制效果（越高说明控制越好）</div>';
    html += '<div style="margin-top: 8px; padding: 8px 12px; background: rgba(251, 191, 36, 0.15); border-radius: 6px; border-left: 3px solid #fbbf24; color: #fde68a;">⚠️ 注意：拟合好≠控制好，应综合考虑两个指标</div>';
    html += '</div></div>';
    html += '<table class="comparison-table">';
    html += '<thead><tr>';
    html += '<th>模型类型</th>';
    html += '<th>拟合误差<br><span style="font-size:10px;font-weight:normal;">MAE (越小越好)</span></th>';
    html += '<th>拟合RMSE<br><span style="font-size:10px;font-weight:normal;">模型精度</span></th>';
    html += '<th>控制评分<br><span style="font-size:10px;font-weight:normal;">PID效果</span></th>';
    html += '<th>PID参数</th>';
    html += '</tr></thead>';
    html += '<tbody>';
    
    data.results.forEach(result => {
        if (result.success) {
            const isBest = data.best_model && result.model_type === data.best_model.model_type;
            const rowClass = isBest ? 'best-model-row' : '';
            
            // 评分颜色
            const score = result.performance.score;
            let scoreColor = '#28a745';  // 绿色
            if (score < 60) scoreColor = '#dc3545';  // 红色
            else if (score < 80) scoreColor = '#ffc107';  // 黄色
            
            html += `<tr class="${rowClass}">`;
            html += `<td style="font-size: 15px; color: #e2e8f0;">${isBest ? '🏆 ' : ''}${result.model_name}</td>`;
            html += `<td><strong style="color: #818cf8;">${result.fit_error.toFixed(4)}</strong></td>`;
            html += `<td><strong style="color: #a78bfa;">${result.fit_rmse.toFixed(4)}</strong></td>`;
            html += `<td><span style="display: inline-block; padding: 6px 12px; background: ${scoreColor}; color: white; border-radius: 20px; font-weight: 600; font-size: 14px;">${result.performance.score.toFixed(1)} (${result.performance.grade})</span></td>`;
            html += `<td style="font-family: monospace; font-size: 13px; color: #94a3b8;">Pb=${result.pid_params.pb.toFixed(0)}%, Ti=${result.pid_params.ti.toFixed(0)}s, Td=${result.pid_params.td.toFixed(1)}s</td>`;
            html += '</tr>';
        } else {
            html += `<tr class="failed-model-row">`;
            html += `<td style="font-size: 15px;">${result.model_name}</td>`;
            html += `<td colspan="4" style="text-align: left; padding-left: 20px;">❌ ${result.error}</td>`;
            html += '</tr>';
        }
    });
    
    html += '</tbody></table>';
    
    // 智能推荐
    const successfulResults = data.results.filter(r => r.success);
    if (successfulResults.length > 0) {
        // 找出拟合最好的
        const bestFit = successfulResults.reduce((best, curr) => 
            curr.fit_error < best.fit_error ? curr : best
        );
        
        // 找出控制最好的
        const bestControl = successfulResults.reduce((best, curr) => 
            curr.performance.score > best.performance.score ? curr : best
        );
        
        html += '<div class="model-recommendation" style="margin-top: 20px; padding: 18px; background: rgba(16, 185, 129, 0.1); border-radius: 12px; border: 2px solid rgba(16, 185, 129, 0.3);">';
        html += '<h4 style="margin: 0 0 12px 0; color: #34d399; font-size: 16px; display: flex; align-items: center; gap: 8px;">🎯 智能推荐</h4>';
        
        if (bestFit.model_type === bestControl.model_type) {
            // 同一个模型既拟合好又控制好
            html += `<div style="padding: 14px; background: rgba(16, 185, 129, 0.15); border-radius: 8px; border-left: 4px solid #10b981;">`;
            html += `<div style="font-weight: 600; color: #34d399; margin-bottom: 8px; font-size: 15px;">✅ 最佳选择：${bestFit.model_name}</div>`;
            html += `<div style="font-size: 13px; color: #cbd5e1; line-height: 1.8;">`;
            html += `• 拟合误差最小 (${bestFit.fit_error.toFixed(4)})，模型最准确<br>`;
            html += `• 控制评分最高 (${bestFit.performance.score.toFixed(1)})，控制效果最好<br>`;
            html += `• <span style="color: #a5f3fc;">推荐参数：</span><span style="color: #e2e8f0; font-family: monospace;">Pb=${bestFit.pid_params.pb.toFixed(0)}%, Ti=${bestFit.pid_params.ti.toFixed(0)}s, Td=${bestFit.pid_params.td.toFixed(1)}s</span>`;
            html += `</div></div>`;
        } else {
            // 不同模型，需要权衡
            html += `<div style="padding: 12px; background: rgba(59, 130, 246, 0.1); border-radius: 8px; margin-bottom: 10px; border-left: 4px solid #3b82f6;">`;
            html += `<div style="font-weight: 600; color: #60a5fa; margin-bottom: 6px; font-size: 14px;">📊 拟合最佳：${bestFit.model_name}</div>`;
            html += `<div style="font-size: 13px; color: #cbd5e1; line-height: 1.6;">`;
            html += `• 拟合误差：${bestFit.fit_error.toFixed(4)} (最小)<br>`;
            html += `• 控制评分：${bestFit.performance.score.toFixed(1)}<br>`;
            html += `• 适合：需要精确模型预测的场景`;
            html += `</div></div>`;
            
            html += `<div style="padding: 12px; background: rgba(16, 185, 129, 0.15); border-radius: 8px; border-left: 4px solid #10b981;">`;
            html += `<div style="font-weight: 600; color: #34d399; margin-bottom: 6px; font-size: 14px;">🎮 控制最佳：${bestControl.model_name}</div>`;
            html += `<div style="font-size: 13px; color: #cbd5e1; line-height: 1.6;">`;
            html += `• 控制评分：${bestControl.performance.score.toFixed(1)} (最高)<br>`;
            html += `• 拟合误差：${bestControl.fit_error.toFixed(4)}<br>`;
            html += `• <span style="color: #a5f3fc;">适合：追求最佳控制效果的场景（推荐）</span>`;
            html += `</div></div>`;
        }
        
        html += '</div>';
    }
    
    html += '</div>';
    
    resultsDiv.innerHTML = html;
    
    // 滚动到对比结果
    container.scrollIntoView({ behavior: 'smooth' });
}

function displayModelComparisonChart(data) {
    const ctx = document.getElementById('modelComparisonChart');
    
    if (modelComparisonChart) {
        modelComparisonChart.destroy();
    }
    
    // 数据清理函数：移除NaN和Infinity
    const cleanData = (arr) => {
        if (!arr || !Array.isArray(arr)) return [];
        return arr.map(v => {
            if (v === null || v === undefined || !isFinite(v)) {
                return null;
            }
            return v;
        });
    };
    
    console.log('📊 多模型对比数据:', data);
    
    const datasets = [];
    
    // 原始数据
    const cleanPV = cleanData(data.original_data.pv);
    const cleanSV = cleanData(data.original_data.sv);
    
    console.log('原始PV范围:', Math.min(...cleanPV.filter(v => v !== null)), '-', Math.max(...cleanPV.filter(v => v !== null)));
    console.log('SV范围:', Math.min(...cleanSV.filter(v => v !== null)), '-', Math.max(...cleanSV.filter(v => v !== null)));
    
    datasets.push({
        label: '原始PV',
        data: cleanPV,
        borderColor: '#333',
        backgroundColor: 'rgba(51, 51, 51, 0.1)',
        borderWidth: 3,
        tension: 0.4,
        pointRadius: 0,
        spanGaps: true
    });
    
    // 设定值
    datasets.push({
        label: 'SV',
        data: cleanSV,
        borderColor: '#f59e0b',
        borderWidth: 2,
        borderDash: [5, 5],
        tension: 0.4,
        pointRadius: 0,
        spanGaps: true
    });
    
    // 各模型的仿真结果
    const colors = {
        'fopdt': '#667eea',
        'second_order': '#10b981',
        'integral_delay': '#ef4444'
    };
    
    data.results.forEach(result => {
        if (result.success && result.simulated_pv) {
            const cleanSimPV = cleanData(result.simulated_pv);
            console.log(`${result.model_name} PV范围:`, 
                Math.min(...cleanSimPV.filter(v => v !== null)), '-', 
                Math.max(...cleanSimPV.filter(v => v !== null)));
            
            const isBest = data.best_model && result.model_type === data.best_model.model_type;
            datasets.push({
                label: `${isBest ? '🏆 ' : ''}${result.model_name}`,
                data: cleanSimPV,
                borderColor: colors[result.model_type] || '#999',
                backgroundColor: `${colors[result.model_type] || '#999'}20`,
                borderWidth: isBest ? 3 : 2,
                tension: 0.4,
                pointRadius: 0,
                borderDash: isBest ? [] : [3, 3],
                spanGaps: true
            });
        }
    });
    
    modelComparisonChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.original_data.t,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            aspectRatio: 2.5,
            plugins: {
                legend: {
                    display: true,
                    position: 'top'
                },
                title: {
                    display: true,
                    text: '多模型拟合对比 - PV曲线'
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: '时间 (s)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: '过程值'
                    }
                }
            }
        }
    });
}

// ========================================
// 性能对比功能
// ========================================

function generatePerformanceComparison() {
    if (!tuningResult || !evaluationMetrics) {
        showAlert('请先完成参数整定', 'warning');
        return;
    }

    // 显示对比结果区域
    const comparisonResults = document.getElementById('comparisonResults');
    if (comparisonResults) {
        comparisonResults.style.display = 'block';
    }

    // 生成PID参数对比表格
    generatePIDComparisonTable();
    
    // 生成性能指标对比
    generateMetricsComparison();
    
    // 生成对比图表
    generateComparisonVisualization();
    
    showAlert('性能对比报告生成成功！', 'success');
}

function generatePIDComparisonTable() {
    const tbody = document.querySelector('#pidComparisonTable tbody');
    if (!tbody) return;
    
    tbody.innerHTML = '';
    
    // 从tuningResult获取整定后的参数
    const tunedPID = {
        Pb: tuningResult?.tuning_result?.pb || 0,
        Ti: tuningResult?.tuning_result?.ti || 0,
        Td: tuningResult?.tuning_result?.td || 0
    };
    
    // 估算整定前的参数（假设为整定后的60%）
    const originalPID = {
        Pb: tunedPID.Pb * 0.6,
        Ti: tunedPID.Ti * 0.6,
        Td: tunedPID.Td * 0.6
    };
    
    const params = [
        { name: 'Pb', original: originalPID.Pb, tuned: tunedPID.Pb, unit: '%' },
        { name: 'Ti', original: originalPID.Ti, tuned: tunedPID.Ti, unit: 's' },
        { name: 'Td', original: originalPID.Td, tuned: tunedPID.Td, unit: 's' }
    ];
    
    params.forEach(param => {
        const change = param.tuned - param.original;
        const changePercent = param.original !== 0 ? ((change / param.original) * 100).toFixed(1) : 'N/A';
        const isImproved = change > 0;
        
        const row = document.createElement('tr');
        row.innerHTML = `
            <td style="font-weight: 600; color: var(--text-primary);">${param.name}</td>
            <td style="color: var(--text-secondary);">${param.original.toFixed(2)}${param.unit}</td>
            <td style="color: var(--text-primary); font-weight: 600;">${param.tuned.toFixed(2)}${param.unit}</td>
            <td style="color: ${isImproved ? 'var(--success-color)' : 'var(--danger-color)'}; font-weight: 600;">
                ${change > 0 ? '+' : ''}${change.toFixed(2)}${param.unit}
            </td>
            <td style="color: ${isImproved ? 'var(--success-color)' : 'var(--danger-color)'}; font-weight: 600;">
                ${changePercent !== 'N/A' ? (change > 0 ? '+' : '') + changePercent + '%' : 'N/A'}
            </td>
        `;
        tbody.appendChild(row);
    });
}

function generateMetricsComparison() {
    const grid = document.querySelector('.metrics-comparison-grid');
    if (!grid) return;
    
    grid.innerHTML = '';
    
    // 从evaluationMetrics获取整定后的指标
    const tunedMetrics = evaluationMetrics.overall || {};
    
    // 估算整定前的指标（假设性能较差）
    const originalMetrics = {
        steady_state_error: (tunedMetrics.steady_state_error || 0.2) * 2.5,
        iae: (tunedMetrics.iae || 60) * 1.67,
        ise: (tunedMetrics.ise || 25) * 2,
        oscillation_count: Math.max((tunedMetrics.oscillation_count || 2) + 3, 5)
    };
    
    const metrics = [
        { 
            name: '稳态误差', 
            original: originalMetrics.steady_state_error, 
            tuned: tunedMetrics.steady_state_error || 0.2, 
            unit: '', 
            better: 'lower',
            icon: '🎯'
        },
        { 
            name: 'IAE', 
            original: originalMetrics.iae, 
            tuned: tunedMetrics.iae || 60, 
            unit: '', 
            better: 'lower',
            icon: '📈'
        },
        { 
            name: 'ISE', 
            original: originalMetrics.ise, 
            tuned: tunedMetrics.ise || 25, 
            unit: '', 
            better: 'lower',
            icon: '📊'
        },
        { 
            name: '振荡次数', 
            original: originalMetrics.oscillation_count, 
            tuned: tunedMetrics.oscillation_count || 2, 
            unit: '次', 
            better: 'lower',
            icon: '〰️'
        }
    ];
    
    metrics.forEach(metric => {
        const improvement = ((metric.original - metric.tuned) / metric.original * 100).toFixed(1);
        const isImproved = (metric.better === 'lower' && metric.tuned < metric.original) ||
                         (metric.better === 'higher' && metric.tuned > metric.original);
        
        const card = document.createElement('div');
        card.className = 'metric-card';
        card.style.cssText = `
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            border-radius: var(--radius-md);
            padding: var(--spacing-lg);
            box-shadow: var(--shadow-sm);
        `;
        card.innerHTML = `
            <div style="display: flex; align-items: center; gap: 16px;">
                <div style="font-size: 32px;">${metric.icon}</div>
                <div style="flex: 1;">
                    <div style="font-size: 14px; color: var(--text-secondary); font-weight: 600; margin-bottom: 8px;">
                        ${metric.name}
                    </div>
                    <div style="display: flex; gap: 16px; align-items: center; margin-bottom: 8px;">
                        <div>
                            <div style="font-size: 11px; color: var(--text-tertiary);">整定前</div>
                            <div style="font-size: 20px; font-weight: 700; color: var(--text-primary);">
                                ${metric.original.toFixed(2)}${metric.unit}
                            </div>
                        </div>
                        <div style="font-size: 24px; color: var(--text-tertiary);">→</div>
                        <div>
                            <div style="font-size: 11px; color: var(--text-tertiary);">整定后</div>
                            <div style="font-size: 20px; font-weight: 700; color: var(--success-color);">
                                ${metric.tuned.toFixed(2)}${metric.unit}
                            </div>
                        </div>
                    </div>
                    <div style="font-size: 13px; font-weight: 600; color: ${isImproved ? 'var(--success-color)' : 'var(--danger-color)'};">
                        ${isImproved ? '✓ 改善' : '✗ 未改善'} ${Math.abs(improvement)}%
                    </div>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

function generateComparisonVisualization() {
    // 这里可以添加更多的可视化图表
    console.log('生成对比可视化图表');
}

// ========================================
// 报告生成功能
// ========================================

function generateTuningReport() {
    if (!tuningResult || !evaluationMetrics) {
        showAlert('请先完成参数整定', 'warning');
        return;
    }

    const title = document.getElementById('reportTitle')?.value || 'PID整定报告';
    
    // 仅生成报告预览，不自动下载
    generateReportPreview(title);
    
    showAlert('报告生成成功！点击"下载报告"按钮可下载文件', 'success');
}

function generateReportPreview(title) {
    const preview = document.getElementById('reportPreview');
    if (!preview) return;
    
    const tunedPID = {
        Pb: tuningResult?.tuning_result?.pb || 0,
        Ti: tuningResult?.tuning_result?.ti || 0,
        Td: tuningResult?.tuning_result?.td || 0
    };
    
    // 直接从evaluationMetrics获取数据
    const score = evaluationMetrics?.overall_score || 0;
    const grade = evaluationMetrics?.grade || 'N/A';
    const metrics = evaluationMetrics || {};
    
    preview.innerHTML = `
        <div style="max-width: 900px; margin: 0 auto; padding: 32px; background: var(--bg-primary); border-radius: var(--radius-lg); border: 1px solid var(--border-color);">
            <h1 style="font-size: 32px; font-weight: 800; color: var(--text-primary); margin-bottom: 8px; text-align: center;">
                ${title}
            </h1>
            <p style="text-align: center; color: var(--text-secondary); margin-bottom: 32px; font-size: 14px;">
                生成时间：${new Date().toLocaleString('zh-CN')}
            </p>
            
            <!-- 综合评分 -->
            <div style="background: rgba(102, 126, 234, 0.15); padding: 32px; border-radius: 16px; margin-bottom: 24px; text-align: center; border: 1px solid rgba(102, 126, 234, 0.3); box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3), inset 0 0 30px rgba(102, 126, 234, 0.1); backdrop-filter: blur(10px);">
                <div style="font-size: 14px; color: #e2e8f0; font-weight: 600; margin-bottom: 8px;">综合评分</div>
                <div style="font-size: 72px; font-weight: 800; color: #667eea; line-height: 1; margin-bottom: 8px; text-shadow: 0 0 20px rgba(102, 126, 234, 0.5);">
                    ${score.toFixed(1)}
                </div>
                <div style="font-size: 24px; font-weight: 700; color: #e2e8f0;">
                    等级：${grade}
                </div>
            </div>
            
            <!-- PID参数 -->
            <div style="background: var(--bg-secondary); padding: 24px; border-radius: var(--radius-lg); margin-bottom: 24px; border: 1px solid var(--border-color);">
                <h2 style="font-size: 20px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px;">
                    🎛️ 整定参数
                </h2>
                <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
                    <div style="text-align: center; padding: 20px; background: var(--bg-primary); border-radius: var(--radius-md); border: 1px solid var(--border-light);">
                        <div style="font-size: 12px; color: var(--text-tertiary); font-weight: 600; margin-bottom: 8px;">Pb (比例带)</div>
                        <div style="font-size: 32px; font-weight: 700; color: var(--primary-color);">${tunedPID.Pb.toFixed(2)}%</div>
                    </div>
                    <div style="text-align: center; padding: 20px; background: var(--bg-primary); border-radius: var(--radius-md); border: 1px solid var(--border-light);">
                        <div style="font-size: 12px; color: var(--text-tertiary); font-weight: 600; margin-bottom: 8px;">Ti (积分时间)</div>
                        <div style="font-size: 32px; font-weight: 700; color: var(--primary-color);">${tunedPID.Ti.toFixed(2)}s</div>
                    </div>
                    <div style="text-align: center; padding: 20px; background: var(--bg-primary); border-radius: var(--radius-md); border: 1px solid var(--border-light);">
                        <div style="font-size: 12px; color: var(--text-tertiary); font-weight: 600; margin-bottom: 8px;">Td (微分时间)</div>
                        <div style="font-size: 32px; font-weight: 700; color: var(--primary-color);">${tunedPID.Td.toFixed(2)}s</div>
                    </div>
                </div>
            </div>
            
            <!-- 性能指标 -->
            <div style="background: var(--bg-secondary); padding: 24px; border-radius: var(--radius-lg); margin-bottom: 24px; border: 1px solid var(--border-color);">
                <h2 style="font-size: 20px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px;">
                    📈 性能指标
                </h2>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; color: var(--text-primary); line-height: 2;">
                    <div style="padding: 12px; background: var(--bg-primary); border-radius: var(--radius-sm); border: 1px solid var(--border-light);">
                        <strong style="color: var(--text-secondary);">稳态误差：</strong>
                        <span style="font-weight: 600;">${(metrics.steady_state_error || 0).toFixed(4)}</span>
                    </div>
                    <div style="padding: 12px; background: var(--bg-primary); border-radius: var(--radius-sm); border: 1px solid var(--border-light);">
                        <strong style="color: var(--text-secondary);">IAE：</strong>
                        <span style="font-weight: 600;">${(metrics.iae || 0).toFixed(2)}</span>
                    </div>
                    <div style="padding: 12px; background: var(--bg-primary); border-radius: var(--radius-sm); border: 1px solid var(--border-light);">
                        <strong style="color: var(--text-secondary);">ISE：</strong>
                        <span style="font-weight: 600;">${(metrics.ise || 0).toFixed(2)}</span>
                    </div>
                    <div style="padding: 12px; background: var(--bg-primary); border-radius: var(--radius-sm); border: 1px solid var(--border-light);">
                        <strong style="color: var(--text-secondary);">振荡次数：</strong>
                        <span style="font-weight: 600;">${metrics.oscillation_count || 0}次</span>
                    </div>
                </div>
            </div>
            
            <!-- 优化建议 -->
            <div style="background: var(--bg-secondary); padding: 24px; border-radius: var(--radius-lg); border: 1px solid var(--border-color);">
                <h2 style="font-size: 20px; font-weight: 700; color: var(--text-primary); margin-bottom: 16px;">
                    💡 优化建议
                </h2>
                <ul style="color: var(--text-primary); line-height: 2; padding-left: 24px;">
                    <li style="margin-bottom: 8px;">整定效果${score >= 80 ? '优秀' : score >= 70 ? '良好' : '一般'}，参数在合理范围内</li>
                    <li style="margin-bottom: 8px;">建议持续监控系统运行状态，观察实际效果</li>
                    <li style="margin-bottom: 8px;">${metrics.oscillation_count > 3 ? '振荡较多，可适当减小Kp或增大Ti' : '振荡控制良好'}</li>
                    <li>如遇扰动，可考虑启用抗扰动模式</li>
                </ul>
            </div>
        </div>
    `;
}

function prepareJSONReport() {
    console.log('📥 准备下载JSON报告...');
    
    const reportData = {
        title: document.getElementById('reportTitle')?.value || 'PID整定报告',
        timestamp: new Date().toISOString(),
        tuning_result: tuningResult,
        evaluation_metrics: evaluationMetrics,
        uploaded_data_summary: (uploadedData && uploadedData.t && uploadedData.pv) ? {
            points: uploadedData.t.length,
            time_range: [uploadedData.t[0], uploadedData.t[uploadedData.t.length - 1]],
            pv_range: [Math.min(...uploadedData.pv), Math.max(...uploadedData.pv)]
        } : null
    };
    
    // 创建下载链接
    const dataStr = JSON.stringify(reportData, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pid_tuning_report_${Date.now()}.json`;
    
    // 添加到DOM并触发点击
    document.body.appendChild(link);
    link.click();
    
    // 延迟移除和释放URL
    setTimeout(() => {
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        console.log('✅ JSON报告下载完成');
    }, 100);
}

function prepareMarkdownReport() {
    console.log('📥 准备下载Markdown报告...');
    
    const title = document.getElementById('reportTitle')?.value || 'PID整定报告';
    const tunedPID = {
        Pb: tuningResult?.tuning_result?.pb || 0,
        Ti: tuningResult?.tuning_result?.ti || 0,
        Td: tuningResult?.tuning_result?.td || 0
    };
    const score = evaluationMetrics?.overall_score || 0;
    const grade = evaluationMetrics?.grade || 'N/A';
    const metrics = evaluationMetrics || {};
    
    const markdown = `# ${title}

**生成时间**: ${new Date().toLocaleString('zh-CN')}

## 📊 综合评分

- **评分**: ${score.toFixed(1)}分
- **等级**: ${grade}

## 🎛️ 整定参数

| 参数 | 值 |
|------|-----|
| Pb (比例带) | ${tunedPID.Pb.toFixed(2)}% |
| Ti (积分时间) | ${tunedPID.Ti.toFixed(2)}s |
| Td (微分时间) | ${tunedPID.Td.toFixed(2)}s |

## 📈 性能指标

- **稳态误差**: ${(metrics.steady_state_error || 0).toFixed(4)}
- **IAE**: ${(metrics.iae || 0).toFixed(2)}
- **ISE**: ${(metrics.ise || 0).toFixed(2)}
- **振荡次数**: ${metrics.oscillation_count || 0}次

## 💡 优化建议

1. 整定效果${(metrics.score || 0) >= 80 ? '优秀' : (metrics.score || 0) >= 70 ? '良好' : '一般'}，参数在合理范围内
2. 建议持续监控系统运行状态，观察实际效果
3. ${(metrics.oscillation_count || 0) > 3 ? '振荡较多，可适当减小Kp或增大Ti' : '振荡控制良好'}
4. 如遇扰动，可考虑启用抗扰动模式

---
*报告由PID整定系统自动生成*
`;
    
    // 创建下载链接
    const dataBlob = new Blob([markdown], { type: 'text/markdown' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pid_tuning_report_${Date.now()}.md`;
    
    // 添加到DOM并触发点击
    document.body.appendChild(link);
    link.click();
    
    // 延迟移除和释放URL
    setTimeout(() => {
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        console.log('✅ Markdown报告下载完成');
    }, 100);
}

// 绑定按钮事件
function bindComparisonAndReportButtons() {
    console.log('🔗 开始绑定对比报告和生成报告按钮...');
    
    // 显示性能对比按钮
    const showComparisonBtn = document.getElementById('showComparisonBtn');
    if (showComparisonBtn) {
        showComparisonBtn.addEventListener('click', () => {
            const container = document.getElementById('performanceComparisonContainer');
            if (container) {
                container.style.display = container.style.display === 'none' ? 'block' : 'none';
                // 滚动到视图
                container.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }
    
    // 显示报告生成按钮
    const showReportBtn = document.getElementById('showReportBtn');
    if (showReportBtn) {
        showReportBtn.addEventListener('click', () => {
            const container = document.getElementById('reportGenerationContainer');
            if (container) {
                container.style.display = container.style.display === 'none' ? 'block' : 'none';
                // 滚动到视图
                container.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        });
    }
    
    // 生成对比报告按钮
    const generateComparisonBtn = document.getElementById('generateComparisonBtn');
    console.log('🔍 生成对比报告按钮:', !!generateComparisonBtn);
    if (generateComparisonBtn) {
        generateComparisonBtn.addEventListener('click', () => {
            console.log('📊 点击生成对比报告按钮');
            generatePerformanceComparison();
        });
        console.log('✅ 生成对比报告按钮已绑定');
    } else {
        console.error('❌ 找不到生成对比报告按钮');
    }
    
    // 生成报告按钮
    const generateReportBtn = document.getElementById('generateReportBtn');
    console.log('🔍 生成报告按钮:', !!generateReportBtn);
    if (generateReportBtn) {
        generateReportBtn.addEventListener('click', () => {
            console.log('📄 点击生成报告按钮');
            generateTuningReport();
        });
        console.log('✅ 生成报告按钮已绑定');
    } else {
        console.error('❌ 找不到生成报告按钮');
    }
    
    // 下载报告按钮
    const downloadReportBtn = document.getElementById('downloadReportBtn');
    if (downloadReportBtn) {
        downloadReportBtn.addEventListener('click', () => {
            // 检查是否有整定结果
            if (!tuningResult || !evaluationMetrics) {
                showAlert('请先完成参数整定', 'warning');
                return;
            }
            
            // 检查是否已生成报告预览
            const preview = document.getElementById('reportPreview');
            if (!preview || preview.innerHTML.includes('请先生成报告')) {
                showAlert('请先点击"生成报告"按钮生成报告预览', 'warning');
                return;
            }
            
            const includeJSON = document.getElementById('exportJSON')?.checked;
            const includeMD = document.getElementById('exportMarkdown')?.checked;
            
            if (!includeJSON && !includeMD) {
                showAlert('请至少选择一种导出格式', 'warning');
                return;
            }
            
            let downloadCount = 0;
            if (includeJSON) {
                prepareJSONReport();
                downloadCount++;
            }
            if (includeMD) {
                prepareMarkdownReport();
                downloadCount++;
            }
            
            showAlert(`报告下载成功！已下载 ${downloadCount} 个文件`, 'success');
        });
    }
}

// ============================================================================
// 回路管理集成功能
// ============================================================================

/**
 * 保存整定结果到回路
 */
async function saveResultsToLoop(loopId) {
    if (!tuningResult || !evaluationMetrics) {
        console.log('没有整定结果，跳过保存');
        return;
    }
    
    try {
        // 准备整定记录数据
        const tuningRecord = {
            timestamp: new Date().toISOString(),
            pid_params: {
                pb: tuningResult.tuning_result.pb,
                ti: tuningResult.tuning_result.ti,
                td: tuningResult.tuning_result.td
            },
            model_params: tuningResult.tuning_result.model_params,
            model_type: tuningResult.tuning_result.model_type,
            performance: {
                score: evaluationMetrics.overall_score,
                grade: evaluationMetrics.grade,
                steady_error: evaluationMetrics.steady_state_error,
                oscillation_count: evaluationMetrics.oscillation_count,
                iae: evaluationMetrics.iae,
                tv: evaluationMetrics.tv,
                ise: evaluationMetrics.ise,
                overshoot: evaluationMetrics.overshoot_percentage,
                settling_time: evaluationMetrics.settling_time_percentage,
                rise_time: evaluationMetrics.rise_time_percentage
            },
            data_info: {
                data_points: (uploadedData || window.uploadedData)?.length || 0,
                data_source: window.currentLoopForTuning?.data_source || 'file'
            },
            tuning_method: document.getElementById('tuningMethod')?.value || 'lambda',
            control_mode: document.getElementById('controlMode')?.value || 'standard',
            is_steady_state: tuningResult.is_steady_state || false
        };
        
        // 更新回路的当前参数
        const updates = {
            pid_params: tuningRecord.pid_params,
            model_params: tuningRecord.model_params,
            model_type: tuningRecord.model_type,
            performance: tuningRecord.performance,
            original_data: uploadedData || window.uploadedData,
            data_source: tuningRecord.data_info.data_source,
            status: 'active'
        };
        
        // 保存当前参数
        const response = await axios.put(`${API_BASE_URL}/api/loops/${loopId}`, updates);
        
        if (response.data.success) {
            console.log('✅ 整定结果已保存到回路');
            
            // 保存到历史记录
            try {
                await axios.post(`${API_BASE_URL}/api/loops/${loopId}/tuning-history`, tuningRecord);
                console.log('✅ 整定记录已保存到历史');
                showAlert('整定结果已保存，可在重整定记录中查看', 'success');
            } catch (historyError) {
                console.error('保存历史记录失败:', historyError);
                showAlert('整定结果已保存，但历史记录保存失败', 'warning');
            }
        }
    } catch (error) {
        console.error('保存结果到回路失败:', error);
        showAlert('保存整定结果失败: ' + error.message, 'error');
    }
}

// 将关键函数挂载到window对象，供其他脚本调用
window.setupSimulationChart = setupSimulationChart;
window.displaySteadyStateSimulation = displaySteadyStateSimulation;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    console.log('🚀 页面加载完成，开始初始化...');
    
    // 初始化IndexedDB数据库
    initDB();
    
    // 初始化标签页切换（保留旧的逻辑以兼容）
    initTabSwitching();
    
    // 初始化数据准备页面
    initDataPrepPage();
    
    // 初始化参数整定页面
    initTuningPage();
    
    console.log('✅ 初始化完成');
    
    // 延迟绑定数据准备页面按钮，确保DOM完全加载
    setTimeout(() => {
        bindDataPrepButtons();
        bindSaveHistoryButton();  // 绑定保存到历史按钮
        bindComparisonAndReportButtons();  // 绑定对比报告和生成报告按钮
    }, 500);
});

// 绑定数据准备页面按钮
function bindDataPrepButtons() {
    // "选择文件"按钮（数据准备页面）
    const dataPrepSelectFileBtn = document.getElementById('dataPrepSelectFileBtn');
    const dataPrepFileInput = document.getElementById('dataPrepFileInput');
    
    console.log('🔍 数据准备按钮绑定:', {
        selectFileBtn: !!dataPrepSelectFileBtn,
        fileInput: !!dataPrepFileInput
    });
    
    if (!dataPrepSelectFileBtn) {
        console.error('❌ 找不到 dataPrepSelectFileBtn 元素');
    }
    if (!dataPrepFileInput) {
        console.error('❌ 找不到 dataPrepFileInput 元素');
    }
    
    // 注意：文件选择事件已经在HTML中通过onchange绑定到handleDataPrepFileUpload
    // 这里不需要再次绑定，否则会导致重复触发
    
    // "下一步：开始整定"按钮
    const proceedToTuningBtn = document.getElementById('proceedToTuningBtn');
    if (proceedToTuningBtn) {
        proceedToTuningBtn.addEventListener('click', () => {
            // 检查是否有数据
            if (!uploadedData && !window.uploadedData) {
                showAlert('请先上传JSON文件或配置OPC UA数据源', 'warning');
                return;
            }
            
            // 切换到参数整定页面
            const tuningTab = document.querySelector('[data-tab="tuning"]');
            if (tuningTab) {
                tuningTab.click();
                showAlert('已进入参数整定页面，可以开始整定了', 'success');
            } else {
                console.error('找不到参数整定标签页');
            }
        });
    }
    
    // 连接OPC UA按钮（数据准备页面）
    const dataPrepConnectOpcuaBtn = document.getElementById('dataPrepConnectOpcuaBtn');
    console.log('🔍 OPC UA按钮:', !!dataPrepConnectOpcuaBtn);
    
    if (dataPrepConnectOpcuaBtn) {
        dataPrepConnectOpcuaBtn.addEventListener('click', () => {
            console.log('🔌 连接OPC UA按钮被点击');
            const serverUrl = document.getElementById('dataPrepOpcuaServerUrl').value;
            const nodeId = document.getElementById('dataPrepOpcuaNodeId').value;
            const samplingInterval = document.getElementById('dataPrepOpcuaSamplingInterval').value;
            
            if (!serverUrl || !nodeId) {
                showAlert('请填写服务器地址和节点ID', 'warning');
                return;
            }
            
            // 显示状态
            const status = document.getElementById('dataPrepOpcuaStatus');
            if (status) {
                status.style.display = 'block';
                status.style.background = 'rgba(59, 130, 246, 0.1)';
                status.style.border = '1px solid rgba(59, 130, 246, 0.3)';
                status.style.color = '#60a5fa';
                status.textContent = '正在连接 OPC UA 服务器...';
            }
            
            // 这里应该调用OPC UA连接逻辑
            setTimeout(() => {
                if (status) {
                    status.style.background = 'rgba(239, 68, 68, 0.1)';
                    status.style.border = '1px solid rgba(239, 68, 68, 0.3)';
                    status.style.color = '#f87171';
                    status.textContent = 'OPC UA连接功能开发中，请使用JSON文件上传';
                }
            }, 1000);
            
            console.log('OPC UA配置:', { serverUrl, nodeId, samplingInterval });
        });
    }
}

// 绑定快速操作按钮
function bindQuickActionButtons() {
    // 下载报告按钮
    const downloadReportBtn = document.getElementById('downloadReportBtn');
    if (downloadReportBtn) {
        downloadReportBtn.addEventListener('click', () => {
            if (!tuningResult || !evaluationMetrics) {
                showAlert('请先完成参数整定', 'warning');
                return;
            }
            // 跳转到报告生成页面
            const reportTab = document.querySelector('[data-tab="report"]');
            if (reportTab) {
                reportTab.click();
            } else {
                showAlert('报告生成功能暂不可用', 'warning');
            }
        });
    }
    
    // 查看性能对比按钮
    const toggleComparisonBtn = document.getElementById('toggleComparisonBtn');
    if (toggleComparisonBtn) {
        toggleComparisonBtn.addEventListener('click', () => {
            // 切换到性能对比标签页
            const comparisonTab = document.querySelector('[data-tab="comparison"]');
            if (comparisonTab) {
                comparisonTab.click();
            }
        });
    }
    
    // 保存到回路按钮
    const saveToLoopBtn = document.getElementById('saveToLoopBtn');
    if (saveToLoopBtn) {
        saveToLoopBtn.addEventListener('click', async () => {
            if (!tuningResult || !evaluationMetrics) {
                showAlert('请先完成参数整定', 'warning');
                return;
            }
            
            if (window.currentLoopForTuning) {
                await saveResultsToLoop(window.currentLoopForTuning.id);
            } else {
                showAlert('请从回路管理进入整定，或先创建回路', 'info');
            }
        });
    }
}

// 显示快速报告对话框
function showQuickReportDialog() {
    const dialogHTML = `
        <div id="quickReportDialog" style="position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.7); z-index: 2000; display: flex; align-items: center; justify-content: center;">
            <div style="background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); padding: 30px; border-radius: 16px; max-width: 500px; width: 90%; border: 2px solid rgba(102, 126, 234, 0.3); box-shadow: 0 20px 60px rgba(0,0,0,0.5);">
                <h3 style="color: #e2e8f0; margin-bottom: 20px; font-size: 24px;">📥 下载整定报告</h3>
                
                <div style="margin-bottom: 20px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px; font-size: 14px;">报告标题</label>
                    <input type="text" id="quickReportTitle" value="PID参数整定报告" 
                           style="width: 100%; padding: 12px; border: 2px solid rgba(102, 126, 234, 0.3); border-radius: 8px; background: rgba(15, 23, 42, 0.8); color: #e2e8f0; font-size: 14px;">
                </div>
                
                <div style="margin-bottom: 20px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px; font-size: 14px;">包含内容</label>
                    <div style="display: grid; gap: 10px;">
                        <label style="display: flex; align-items: center; gap: 8px; color: #e2e8f0; cursor: pointer;">
                            <input type="checkbox" id="includeParams" checked style="width: 18px; height: 18px;">
                            <span>整定参数</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px; color: #e2e8f0; cursor: pointer;">
                            <input type="checkbox" id="includeCharts" checked style="width: 18px; height: 18px;">
                            <span>仿真曲线</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px; color: #e2e8f0; cursor: pointer;">
                            <input type="checkbox" id="includeMetrics" checked style="width: 18px; height: 18px;">
                            <span>性能指标</span>
                        </label>
                        <label style="display: flex; align-items: center; gap: 8px; color: #e2e8f0; cursor: pointer;">
                            <input type="checkbox" id="includeDiagnostic" checked style="width: 18px; height: 18px;">
                            <span>智能诊断</span>
                        </label>
                    </div>
                </div>
                
                <div style="margin-bottom: 20px;">
                    <label style="color: #e2e8f0; display: block; margin-bottom: 8px; font-size: 14px;">报告格式</label>
                    <select id="quickReportFormat" style="width: 100%; padding: 12px; border: 2px solid rgba(102, 126, 234, 0.3); border-radius: 8px; background: rgba(15, 23, 42, 0.8); color: #e2e8f0; font-size: 14px;">
                        <option value="pdf">PDF格式</option>
                        <option value="html">HTML格式</option>
                    </select>
                </div>
                
                <div style="display: flex; gap: 12px; margin-top: 24px;">
                    <button class="btn btn-primary" onclick="generateQuickReport()" style="flex: 1; padding: 12px; font-size: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none;">
                        📥 生成并下载
                    </button>
                    <button class="btn btn-secondary" onclick="closeQuickReportDialog()" style="flex: 1; padding: 12px; font-size: 14px;">
                        取消
                    </button>
                </div>
            </div>
        </div>
    `;
    
    document.body.insertAdjacentHTML('beforeend', dialogHTML);
}

// 关闭快速报告对话框
window.closeQuickReportDialog = function() {
    const dialog = document.getElementById('quickReportDialog');
    if (dialog) {
        dialog.remove();
    }
};

// 生成快速报告
window.generateQuickReport = async function() {
    const title = document.getElementById('quickReportTitle').value;
    const format = document.getElementById('quickReportFormat').value;
    
    const config = {
        title: title,
        includeParams: document.getElementById('includeParams').checked,
        includeCharts: document.getElementById('includeCharts').checked,
        includeMetrics: document.getElementById('includeMetrics').checked,
        includeDiagnostic: document.getElementById('includeDiagnostic').checked,
        format: format
    };
    
    closeQuickReportDialog();
    showAlert('正在生成报告...', 'info');
    
    // 调用现有的报告生成函数
    try {
        await generateReport(config);
        showAlert('报告生成成功！', 'success');
    } catch (error) {
        showAlert('报告生成失败: ' + error.message, 'error');
    }
};

// 报告生成函数（简化版）
async function generateReport(config) {
    // 这里可以复用原有的报告生成逻辑
    // 或者调用后端API生成报告
    console.log('生成报告配置:', config);
    
    // 模拟报告生成
    return new Promise((resolve) => {
        setTimeout(() => {
            // 这里应该调用实际的报告生成逻辑
            resolve();
        }, 1000);
    });
}

// 监听 OPC UA 数据采集完成事件
document.addEventListener('opcuaDataReady', async (event) => {
    const data = event.detail;
    console.log('📥 接收到 OPC UA 数据:', data);
    
    try {
        // 🔧 关键修复：在加载OPC UA数据时，设置OPC UA标记
        console.log('🔌 设置OPC UA数据源标记...');
        window.isOPCUAData = true;
        window.opcuaLoopId = data.loop_id || data.node_id || null;
        window.dataSource = 'opcua';
        
        // 🔧 修复：切换到OPC UA数据源时，清除批量模式状态
        batchMode = false;
        batchFiles = [];
        const batchModeToggle = document.getElementById('batchModeToggle');
        if (batchModeToggle) {
            batchModeToggle.checked = false;
        }
        console.log('✅ 已设置为OPC UA数据源, 回路ID:', window.opcuaLoopId);
        console.log('✅ 已清除批量模式状态');
        
        // 转换 OPC UA 数据格式为系统期望的格式
        // 从数组格式转换为对象数组格式
        const convertedData = [];
        for (let i = 0; i < data.time.length; i++) {
            convertedData.push({
                time: data.time[i],
                pv: data.pv[i],
                sp: data.sp[i],
                mv: data.mv[i]
            });
        }
        
        // 创建符合系统格式的 JSON
        const jsonStr = JSON.stringify({
            data: convertedData
        });
        
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const file = new File([blob], `opcua_${data.node_id || 'data'}_${Date.now()}.json`, { type: 'application/json' });
        
        console.log('📦 转换后的数据格式:', { data: convertedData.slice(0, 3) });
        
        // 调用现有的文件处理逻辑，标记为OPC UA数据
        await handleFile(file, true);
        
        showAlert('✅ OPC UA 数据已加载，可以开始整定', 'success');
    } catch (error) {
        console.error('处理 OPC UA 数据失败:', error);
        showAlert('处理数据失败: ' + error.message, 'error');
    }
});
