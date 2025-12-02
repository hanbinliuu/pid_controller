// AI Assistant Module
// 🤖 AI智能助手功能

let aiEnabled = false;
let aiModel = '';

// Check AI configuration
async function checkAIConfig() {
    try {
        const response = await axios.get(`${API_BASE_URL}/api/ai/config`);
        if (response.data.enabled) {
            aiEnabled = true;
            aiModel = response.data.model;
            updateAIStatus(true);
            console.log(`✅ AI助手已启用 (模型: ${aiModel})`);
        } else {
            aiEnabled = false;
            updateAIStatus(false);
            console.log('⚠️ AI助手未配置');
        }
    } catch (error) {
        console.error('检查AI配置失败:', error);
        aiEnabled = false;
        updateAIStatus(false);
    }
}

// Update AI status indicator
function updateAIStatus(enabled) {
    const statusEl = document.getElementById('aiStatus');
    if (statusEl) {
        if (enabled) {
            statusEl.textContent = `✅ 已启用 (${aiModel})`;
            statusEl.className = 'ai-status';
        } else {
            statusEl.textContent = '❌ 未配置';
            statusEl.className = 'ai-status disabled';
        }
    }
}

// AI Parameter Optimization
async function aiOptimizeParameters() {
    console.log('🔍 AI参数优化被调用');
    console.log('AI启用状态:', aiEnabled);
    console.log('tuningResult:', typeof tuningResult !== 'undefined' ? tuningResult : 'undefined');
    console.log('evaluationMetrics:', typeof evaluationMetrics !== 'undefined' ? evaluationMetrics : 'undefined');
    
    if (!aiEnabled) {
        console.error('❌ AI功能未启用');
        showAlert('AI功能未启用，请配置OPENAI_API_KEY环境变量', 'error');
        return;
    }

    // 检查变量是否存在
    if (typeof tuningResult === 'undefined' || !tuningResult || 
        typeof evaluationMetrics === 'undefined' || !evaluationMetrics) {
        console.error('❌ 整定数据不存在');
        showAlert('请先完成PID整定后再使用AI优化功能', 'error');
        return;
    }

    console.log('✅ 开始AI优化...');
    const btn = document.getElementById('aiOptimizeBtn');
    const resultDiv = document.getElementById('aiOptimizeResult');
    
    if (!btn) {
        console.error('❌ 找不到AI优化按钮');
        return;
    }
    
    btn.disabled = true;
    btn.innerHTML = '<span>⏳ AI分析中...</span>';
    resultDiv.style.display = 'none';

    try {
        console.log('📤 发送AI优化请求...');
        const response = await axios.post(`${API_BASE_URL}/api/ai/optimize`, {
            current_params: {
                pb: tuningResult.tuning_result.pb,
                ti: tuningResult.tuning_result.ti,
                td: tuningResult.tuning_result.td
            },
            metrics: evaluationMetrics,
            data: typeof uploadedData !== 'undefined' ? uploadedData : []
        });
        
        console.log('📥 收到AI响应:', response.data);

        if (response.data.success) {
            displayAIOptimization(response.data.optimization);
            resultDiv.style.display = 'block';
            showAlert('AI优化建议已生成', 'success');
        } else {
            showAlert('AI优化失败: ' + response.data.error, 'error');
        }
    } catch (error) {
        console.error('AI优化错误:', error);
        showAlert('AI优化失败: ' + error.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>✨ AI参数优化</span>';
    }
}

// Display AI optimization results
function displayAIOptimization(optimization) {
    const resultDiv = document.getElementById('aiOptimizeResult');
    
    let html = '<h4>🤖 AI优化建议</h4>';
    
    // 如果有结构化的优化建议
    if (optimization.analysis) {
        html += `<div class="analysis">
            <strong>📊 分析：</strong><br>
            ${optimization.analysis}
        </div>`;
    }
    
    if (optimization.issues && optimization.issues.length > 0) {
        html += '<div class="issues"><strong>⚠️ 发现的问题：</strong><ul>';
        optimization.issues.forEach(issue => {
            html += `<li>${issue}</li>`;
        });
        html += '</ul></div>';
    }
    
    if (optimization.suggestions && optimization.suggestions.length > 0) {
        html += '<div class="suggestions"><strong>💡 参数调整建议：</strong>';
        optimization.suggestions.forEach(sug => {
            const paramName = sug.parameter.toUpperCase();
            html += `<div class="ai-suggestion-item">
                <div class="param-name">${paramName}</div>
                <div class="values">
                    <span>当前值: <strong>${sug.current}</strong></span>
                    <span>→</span>
                    <span>建议值: <strong style="color: #28a745;">${sug.suggested}</strong></span>
                </div>
                <div class="reason">${sug.reason}</div>
            </div>`;
        });
        html += '</div>';
    }
    
    if (optimization.expected_improvement) {
        html += `<div class="analysis" style="margin-top: 15px; background: #e8f5e9;">
            <strong>📈 预期改进：</strong><br>
            ${optimization.expected_improvement}
        </div>`;
    }
    
    // 如果只有原始回答
    if (optimization.raw_answer && !optimization.analysis) {
        html += `<div class="analysis">${optimization.raw_answer.replace(/\n/g, '<br>')}</div>`;
    }
    
    resultDiv.innerHTML = html;
}

// AI Question & Answer
async function askAI(question) {
    if (!aiEnabled) {
        showAlert('AI功能未启用，请配置OPENAI_API_KEY环境变量', 'error');
        return;
    }

    const messagesDiv = document.getElementById('aiChatMessages');
    
    // Add user message
    addChatMessage('user', question);
    
    // Add loading indicator
    const loadingId = 'loading-' + Date.now();
    messagesDiv.innerHTML += `<div id="${loadingId}" class="ai-loading">AI思考中...</div>`;
    messagesDiv.scrollTop = messagesDiv.scrollHeight;

    try {
        // Prepare context (检查变量是否存在)
        const context = {};
        if (typeof tuningResult !== 'undefined' && tuningResult) {
            context.pid_params = tuningResult.tuning_result;
            context.model_info = {
                model_type: tuningResult.tuning_result.model_type,
                model_params: tuningResult.tuning_result.model_params
            };
        }
        if (typeof evaluationMetrics !== 'undefined' && evaluationMetrics) {
            context.metrics = evaluationMetrics;
        }
        if (typeof simulationData !== 'undefined' && simulationData) {
            // 添加仿真数据摘要（不发送全部数据，只发送关键统计信息）
            const pv = simulationData.pv || [];
            const sv = tuningResult?.data?.sv || [];
            const mv = simulationData.mv || [];
            
            if (pv.length > 0) {
                context.simulation_summary = {
                    pv_range: [Math.min(...pv).toFixed(2), Math.max(...pv).toFixed(2)],
                    pv_final: pv[pv.length - 1].toFixed(2),
                    sv_final: sv.length > 0 ? sv[sv.length - 1].toFixed(2) : 'N/A',
                    final_error: sv.length > 0 ? Math.abs(pv[pv.length - 1] - sv[sv.length - 1]).toFixed(4) : 'N/A',
                    mv_range: mv.length > 0 ? [Math.min(...mv).toFixed(2), Math.max(...mv).toFixed(2)] : 'N/A',
                    data_points: pv.length
                };
            }
        }

        const response = await axios.post(`${API_BASE_URL}/api/ai/question`, {
            question: question,
            context: Object.keys(context).length > 0 ? context : null
        });

        // Remove loading indicator
        document.getElementById(loadingId)?.remove();

        if (response.data.success) {
            addChatMessage('assistant', response.data.answer);
        } else {
            addChatMessage('assistant', '抱歉，我遇到了一些问题：' + response.data.error);
        }
    } catch (error) {
        document.getElementById(loadingId)?.remove();
        console.error('AI问答错误:', error);
        addChatMessage('assistant', '抱歉，发生了错误：' + error.message);
    }
}

// Add chat message to UI
function addChatMessage(role, content) {
    const messagesDiv = document.getElementById('aiChatMessages');
    const time = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `ai-message ${role}`;
    messageDiv.innerHTML = `
        <div class="message-bubble">${content.replace(/\n/g, '<br>')}</div>
        <div class="message-time">${time}</div>
    `;
    
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

// Event Listeners
document.getElementById('aiOptimizeBtn')?.addEventListener('click', aiOptimizeParameters);

document.getElementById('aiAskBtn')?.addEventListener('click', () => {
    const input = document.getElementById('aiQuestionInput');
    const question = input.value.trim();
    if (question) {
        askAI(question);
        input.value = '';
    }
});

document.getElementById('aiQuestionInput')?.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
        const question = e.target.value.trim();
        if (question) {
            askAI(question);
            e.target.value = '';
        }
    }
});

// Quick question buttons
document.querySelectorAll('.quick-question-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const question = btn.getAttribute('data-question');
        askAI(question);
    });
});

// Show AI assistant when tuning is complete
function showAIAssistant() {
    const container = document.getElementById('aiAssistantContainer');
    if (container) {
        container.style.display = 'block';
        console.log('✅ AI助手界面已显示');
        
        if (!aiEnabled) {
            console.log('⚠️ AI功能未配置，请设置OPENAI_API_KEY环境变量');
        }
    }
}

// Show AI button click handler
document.getElementById('showAIBtn')?.addEventListener('click', () => {
    showAIAssistant();
    // 滚动到AI助手区域
    const container = document.getElementById('aiAssistantContainer');
    if (container) {
        container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
});

// Initialize AI on page load
document.addEventListener('DOMContentLoaded', () => {
    checkAIConfig();
});

console.log('🤖 AI助手模块已加载');
