/**
 * Monitoring Manager - 实时监控管理器
 * 前端JavaScript模块，用于调用监控API
 */

class MonitoringManager {
    constructor(apiBaseUrl = 'http://localhost:8000') {
        this.apiBaseUrl = apiBaseUrl;
        this.activeMonitors = new Map();
        this.updateIntervals = new Map();
    }

    /**
     * 创建监控实例
     */
    async createMonitor(loopId, loopName, samplingInterval = 1.0) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/create`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    loop_name: loopName,
                    sampling_interval: samplingInterval
                })
            });
            
            const result = await response.json();
            if (result.success) {
                this.activeMonitors.set(loopId, { loopName, samplingInterval });
            }
            return result;
        } catch (error) {
            console.error('创建监控失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 启动监控
     */
    async startMonitor(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/start/${loopId}`, {
                method: 'POST'
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('启动监控失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 停止监控
     */
    async stopMonitor(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/stop/${loopId}`, {
                method: 'POST'
            });
            
            const result = await response.json();
            
            // 停止自动更新
            if (this.updateIntervals.has(loopId)) {
                clearInterval(this.updateIntervals.get(loopId));
                this.updateIntervals.delete(loopId);
            }
            
            return result;
        } catch (error) {
            console.error('停止监控失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 添加单个数据点
     */
    async addDataPoint(loopId, timestamp, pv, sv, mv = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/data`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    timestamp: timestamp,
                    pv: pv,
                    sv: sv,
                    mv: mv
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('添加数据失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 批量添加数据
     */
    async addBatchData(loopId, timeData, pvData, svData, mvData = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/batch_data`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    time_data: timeData,
                    pv_data: pvData,
                    sv_data: svData,
                    mv_data: mvData
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('批量添加数据失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取实时数据
     */
    async getRealtimeData(loopId, lastN = null) {
        try {
            let url = `${this.apiBaseUrl}/api/monitor/realtime/${loopId}`;
            if (lastN !== null) {
                url += `?last_n=${lastN}`;
            }
            
            const response = await fetch(url);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取实时数据失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取监控状态
     */
    async getMonitorStatus(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/status/${loopId}`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取监控状态失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取所有监控实例
     */
    async getAllMonitors() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/all`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取监控列表失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 删除监控实例
     */
    async deleteMonitor(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/monitor/${loopId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.activeMonitors.delete(loopId);
                if (this.updateIntervals.has(loopId)) {
                    clearInterval(this.updateIntervals.get(loopId));
                    this.updateIntervals.delete(loopId);
                }
            }
            
            return result;
        } catch (error) {
            console.error('删除监控失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 启动自动更新（定时获取实时数据）
     */
    startAutoUpdate(loopId, updateCallback, intervalMs = 1000) {
        // 清除已存在的定时器
        if (this.updateIntervals.has(loopId)) {
            clearInterval(this.updateIntervals.get(loopId));
        }

        // 创建新的定时器
        const intervalId = setInterval(async () => {
            const data = await this.getRealtimeData(loopId, 100);
            if (data.success && updateCallback) {
                updateCallback(data);
            }
        }, intervalMs);

        this.updateIntervals.set(loopId, intervalId);
    }

    /**
     * 停止自动更新
     */
    stopAutoUpdate(loopId) {
        if (this.updateIntervals.has(loopId)) {
            clearInterval(this.updateIntervals.get(loopId));
            this.updateIntervals.delete(loopId);
        }
    }

    /**
     * 显示实时数据
     */
    displayRealtimeData(data, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!data.success) {
            container.innerHTML = `<div class="error">获取数据失败: ${data.error}</div>`;
            return;
        }

        const metrics = data.metrics || {};
        
        let html = '<div class="realtime-monitor">';
        html += `<h3>📡 ${data.loop_name} - 实时监控</h3>`;
        html += `<p class="status">状态: <span class="badge ${data.status}">${data.status}</span></p>`;
        
        // 当前值
        html += '<div class="current-values">';
        html += `<div class="metric"><label>当前PV:</label> <span>${metrics.current_pv?.toFixed(2) || 'N/A'}</span></div>`;
        html += `<div class="metric"><label>当前SV:</label> <span>${metrics.current_sv?.toFixed(2) || 'N/A'}</span></div>`;
        html += `<div class="metric"><label>当前误差:</label> <span>${metrics.current_error?.toFixed(2) || 'N/A'}</span></div>`;
        if (metrics.current_mv !== undefined) {
            html += `<div class="metric"><label>当前MV:</label> <span>${metrics.current_mv.toFixed(2)}%</span></div>`;
        }
        html += '</div>';

        // 统计指标
        html += '<div class="statistics">';
        html += `<div class="stat"><label>平均误差:</label> ${metrics.mean_error?.toFixed(3) || 'N/A'}</div>`;
        html += `<div class="stat"><label>误差标准差:</label> ${metrics.std_error?.toFixed(3) || 'N/A'}</div>`;
        html += `<div class="stat"><label>最大误差:</label> ${metrics.max_abs_error?.toFixed(3) || 'N/A'}</div>`;
        if (metrics.is_steady !== undefined) {
            html += `<div class="stat"><label>稳态:</label> ${metrics.is_steady ? '✅ 是' : '❌ 否'}</div>`;
        }
        html += '</div>';

        html += '</div>';
        container.innerHTML = html;
    }
}

/**
 * Alarm Manager - 报警管理器
 */
class AlarmManager {
    constructor(apiBaseUrl = 'http://localhost:8000') {
        this.apiBaseUrl = apiBaseUrl;
    }

    /**
     * 配置报警规则
     */
    async configureAlarms(loopId, config) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/alarm/configure`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    config: config
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('配置报警失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 检查报警
     */
    async checkAlarms(loopId, pv, sv, mv = null, pvHistory = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/alarm/check`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    pv: pv,
                    sv: sv,
                    mv: mv,
                    pv_history: pvHistory
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('检查报警失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取活动报警
     */
    async getActiveAlarms(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/alarm/active/${loopId}`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取报警失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取报警历史
     */
    async getAlarmHistory(loopId = null, limit = 100) {
        try {
            let url = `${this.apiBaseUrl}/api/alarm/history?limit=${limit}`;
            if (loopId) {
                url += `&loop_id=${loopId}`;
            }
            
            const response = await fetch(url);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取报警历史失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 确认报警
     */
    async acknowledgeAlarm(loopId, alarmId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/alarm/acknowledge`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    alarm_id: alarmId
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('确认报警失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 清除报警
     */
    async clearAlarms(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/alarm/clear/${loopId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('清除报警失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 显示报警列表
     */
    displayAlarms(alarms, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!alarms || alarms.length === 0) {
            container.innerHTML = '<div class="no-alarms">✅ 无报警</div>';
            return;
        }

        let html = '<div class="alarm-list">';
        alarms.forEach(alarm => {
            const levelClass = alarm.level;
            const icon = this.getAlarmIcon(alarm.level);
            
            html += `
                <div class="alarm-item ${levelClass}">
                    <div class="alarm-header">
                        <span class="alarm-icon">${icon}</span>
                        <span class="alarm-type">${alarm.type}</span>
                        <span class="alarm-time">${new Date(alarm.timestamp).toLocaleString()}</span>
                    </div>
                    <div class="alarm-message">${alarm.message}</div>
                    ${!alarm.acknowledged ? `<button class="ack-btn" onclick="acknowledgeAlarm('${alarm.id}')">确认</button>` : '<span class="acknowledged">✓ 已确认</span>'}
                </div>
            `;
        });
        html += '</div>';
        
        container.innerHTML = html;
    }

    getAlarmIcon(level) {
        const icons = {
            'info': 'ℹ️',
            'warning': '⚠️',
            'error': '❌',
            'critical': '🚨'
        };
        return icons[level] || '⚠️';
    }
}

/**
 * Performance Tracker - 性能跟踪器
 */
class PerformanceTracker {
    constructor(apiBaseUrl = 'http://localhost:8000') {
        this.apiBaseUrl = apiBaseUrl;
    }

    /**
     * 创建性能跟踪器
     */
    async createTracker(loopId, loopName, targetMetrics = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/performance/create_tracker`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    loop_name: loopName,
                    target_metrics: targetMetrics
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('创建跟踪器失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 更新性能数据
     */
    async updateData(loopId, timestamp, pv, sv, mv = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/performance/update`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    loop_id: loopId,
                    timestamp: timestamp,
                    pv: pv,
                    sv: sv,
                    mv: mv
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('更新性能数据失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取性能指标
     */
    async getPerformance(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/performance/${loopId}`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取性能指标失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 获取控制质量评估
     */
    async getQualityAssessment(loopId) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/performance/assessment/${loopId}`);
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('获取质量评估失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 显示性能评估
     */
    displayAssessment(assessment, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!assessment.success) {
            container.innerHTML = `<div class="error">获取评估失败: ${assessment.error}</div>`;
            return;
        }

        const data = assessment.assessment;
        
        let html = '<div class="quality-assessment">';
        html += `<h3>📈 ${assessment.loop_name} - 控制质量评估</h3>`;
        html += `<div class="overall-score">综合得分: <span class="score">${data.overall_score.toFixed(1)}</span> - ${data.rating}</div>`;
        
        // 优势
        if (data.strengths && data.strengths.length > 0) {
            html += '<div class="strengths"><h4>✅ 优势:</h4><ul>';
            data.strengths.forEach(item => {
                html += `<li>${item}</li>`;
            });
            html += '</ul></div>';
        }

        // 不足
        if (data.weaknesses && data.weaknesses.length > 0) {
            html += '<div class="weaknesses"><h4>⚠️ 不足:</h4><ul>';
            data.weaknesses.forEach(item => {
                html += `<li>${item}</li>`;
            });
            html += '</ul></div>';
        }

        // 建议
        if (data.recommendations && data.recommendations.length > 0) {
            html += '<div class="recommendations"><h4>💡 建议:</h4><ul>';
            data.recommendations.forEach(item => {
                html += `<li>${item}</li>`;
            });
            html += '</ul></div>';
        }

        html += '</div>';
        container.innerHTML = html;
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.MonitoringManager = MonitoringManager;
    window.AlarmManager = AlarmManager;
    window.PerformanceTracker = PerformanceTracker;
}
