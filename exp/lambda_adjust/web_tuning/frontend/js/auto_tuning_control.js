/**
 * 自动整定控制模块
 * 管理自动整定开关和手动触发整定
 */

class AutoTuningControl {
    constructor() {
        this.currentLoopId = null;
        this.autoTuningEnabled = false;
        this.initEventListeners();
    }

    /**
     * 初始化事件监听器
     */
    initEventListeners() {
        // 自动整定开关
        const autoTuningSwitch = document.getElementById('autoTuningSwitch');
        if (autoTuningSwitch) {
            autoTuningSwitch.addEventListener('change', (e) => {
                this.handleAutoTuningToggle(e.target.checked);
            });
        }

        // 手动整定按钮
        const manualTuningBtn = document.getElementById('manualTuningBtn');
        if (manualTuningBtn) {
            manualTuningBtn.addEventListener('click', () => {
                this.handleManualTuning();
            });
        }
    }

    /**
     * 设置当前回路
     * @param {string} loopId - 回路ID
     * @param {object} loopInfo - 回路信息
     */
    setCurrentLoop(loopId, loopInfo) {
        this.currentLoopId = loopId;
        
        // 检查是否是OPC UA数据源
        const isOpcua = loopInfo && loopInfo.data_source === 'opcua';
        const autoTuningControl = document.getElementById('autoTuningControl');
        
        if (isOpcua && autoTuningControl) {
            // 显示自动整定控制
            autoTuningControl.style.display = 'block';
            
            // 加载当前开关状态
            const enabled = loopInfo.opcua_config?.auto_tuning_enabled || false;
            this.updateUI(enabled);
        } else if (autoTuningControl) {
            // 隐藏自动整定控制（非OPC UA数据源）
            autoTuningControl.style.display = 'none';
        }
    }

    /**
     * 更新UI状态
     * @param {boolean} enabled - 是否启用
     */
    updateUI(enabled) {
        this.autoTuningEnabled = enabled;
        
        const autoTuningSwitch = document.getElementById('autoTuningSwitch');
        const autoTuningStatus = document.getElementById('autoTuningStatus');
        const manualTuningSection = document.getElementById('manualTuningSection');
        
        if (autoTuningSwitch) {
            autoTuningSwitch.checked = enabled;
        }
        
        if (autoTuningStatus) {
            autoTuningStatus.textContent = enabled ? '已启用' : '已禁用';
            autoTuningStatus.className = enabled ? 'enabled' : 'disabled';
        }
        
        if (manualTuningSection) {
            // 启用自动整定时隐藏手动整定按钮
            manualTuningSection.style.display = enabled ? 'none' : 'block';
        }
    }

    /**
     * 处理自动整定开关切换
     * @param {boolean} enabled - 是否启用
     */
    async handleAutoTuningToggle(enabled) {
        if (!this.currentLoopId) {
            console.error('未选择回路');
            return;
        }

        try {
            console.log(`${enabled ? '启用' : '禁用'}自动整定...`);
            
            const response = await fetch(`${API_BASE_URL}/api/loops/${this.currentLoopId}/toggle_auto_tuning`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ enabled })
            });

            const result = await response.json();
            
            if (result.success) {
                this.updateUI(enabled);
                this.showNotification(result.message, 'success');
                console.log(`✅ ${result.message}`);
            } else {
                // 恢复开关状态
                this.updateUI(!enabled);
                this.showNotification(result.message || '切换失败', 'error');
                console.error('❌ 切换失败:', result.message);
            }
        } catch (error) {
            console.error('切换自动整定失败:', error);
            // 恢复开关状态
            this.updateUI(!enabled);
            this.showNotification('切换失败: ' + error.message, 'error');
        }
    }

    /**
     * 处理手动触发整定
     */
    async handleManualTuning() {
        if (!this.currentLoopId) {
            this.showNotification('请先选择回路', 'warning');
            return;
        }

        // 确认对话框
        if (!confirm('确定要手动触发整定吗？\n\n系统将采集当前数据并计算新的PID参数。')) {
            return;
        }

        try {
            console.log('手动触发整定...');
            this.showNotification('正在触发整定...', 'info');
            
            const response = await fetch(`${API_BASE_URL}/api/loops/${this.currentLoopId}/trigger_retuning`, {
                method: 'POST'
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('整定已触发，请等待计算完成', 'success');
                console.log('✅ 整定已触发');
            } else {
                this.showNotification(result.message || '触发失败', 'error');
                console.error('❌ 触发失败:', result.message);
            }
        } catch (error) {
            console.error('手动触发整定失败:', error);
            this.showNotification('触发失败: ' + error.message, 'error');
        }
    }

    /**
     * 显示通知
     * @param {string} message - 消息内容
     * @param {string} type - 消息类型 (success, error, warning, info)
     */
    showNotification(message, type = 'info') {
        // 使用现有的通知系统或创建简单的通知
        const colors = {
            success: '#10b981',
            error: '#ef4444',
            warning: '#f59e0b',
            info: '#3b82f6'
        };

        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };

        // 创建通知元素
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(15, 23, 42, 0.95);
            color: white;
            padding: 16px 24px;
            border-radius: 8px;
            border-left: 4px solid ${colors[type]};
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            z-index: 10000;
            animation: slideIn 0.3s ease-out;
            max-width: 400px;
        `;
        
        notification.innerHTML = `
            <div style="display: flex; align-items: center; gap: 12px;">
                <span style="font-size: 20px;">${icons[type]}</span>
                <span style="font-size: 14px;">${message}</span>
            </div>
        `;

        document.body.appendChild(notification);

        // 3秒后自动移除
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    /**
     * 清除当前回路
     */
    clearCurrentLoop() {
        this.currentLoopId = null;
        const autoTuningControl = document.getElementById('autoTuningControl');
        if (autoTuningControl) {
            autoTuningControl.style.display = 'none';
        }
    }
}

// 创建全局实例
const autoTuningControl = new AutoTuningControl();

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateX(100%);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }

    @keyframes slideOut {
        from {
            opacity: 1;
            transform: translateX(0);
        }
        to {
            opacity: 0;
            transform: translateX(100%);
        }
    }
`;
document.head.appendChild(style);
