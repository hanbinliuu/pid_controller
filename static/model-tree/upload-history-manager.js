// 上传历史管理模块
class UploadHistoryManager {
    constructor() {
        this.tasks = [];
        this.init();
    }

    init() {
        this.bindEvents();
        this.bindErrorModalEvents();
    }

    bindEvents() {
        // 历史按钮点击
        document.getElementById('historyBtn').addEventListener('click', () => {
            this.showHistoryModal();
        });

        // 刷新按钮
        document.getElementById('historyRefreshBtn').addEventListener('click', () => {
            this.loadHistory();
        });

        // 关闭按钮
        document.getElementById('historyModalClose').addEventListener('click', () => {
            this.hideHistoryModal();
        });

        document.getElementById('historyModalConfirm').addEventListener('click', () => {
            this.hideHistoryModal();
        });

        // 点击遮罩层关闭
        document.getElementById('historyModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('historyModal')) {
                this.hideHistoryModal();
            }
        });
    }

    async showHistoryModal() {
        document.getElementById('historyModal').style.display = 'flex';
        await this.loadHistory();
    }

    hideHistoryModal() {
        document.getElementById('historyModal').style.display = 'none';
    }

    async loadHistory() {
        try {
            const tbody = document.getElementById('historyTableBody');
            tbody.innerHTML = '<tr class="loading-row"><td colspan="7">加载中...</td></tr>';

            const response = await fetch('/api/loop/import-tasks');
            const result = await response.json();

            if (result.code === 0 && result.data) {
                this.tasks = result.data;
                this.renderTasks();
            } else {
                tbody.innerHTML = '<tr class="empty-row"><td colspan="7">加载失败：' + (result.message || '未知错误') + '</td></tr>';
            }
        } catch (error) {
            console.error('加载历史任务失败:', error);
            const tbody = document.getElementById('historyTableBody');
            tbody.innerHTML = '<tr class="empty-row"><td colspan="7">加载失败：' + error.message + '</td></tr>';
        }
    }

    renderTasks() {
        const tbody = document.getElementById('historyTableBody');

        if (!this.tasks || this.tasks.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="7">暂无上传历史</td></tr>';
            return;
        }

        tbody.innerHTML = this.tasks.map((task, index) => {
            const hasFailed = task.failed_count > 0;
            const rowClass = hasFailed ? 'task-row-failed' : '';
            const failedClass = hasFailed ? 'count-failed' : '';

            return `
            <tr data-task-id="${task.task_id}" class="${rowClass}">
                <td title="${this.escapeHtml(task.file_info?.file_name || '')}">${this.truncate(task.file_info?.file_name || '-', 25)}</td>
                <td>${this.renderStatus(task.status)}</td>
                <td>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${task.progress_percentage}%"></div>
                    </div>
                    <div style="font-size: 11px; margin-top: 2px; color: var(--text-muted);">${task.progress_percentage}%</div>
                </td>
                <td class="count-text">
                    <span class="count-success">${task.success_count}</span> / 
                    <span class="${failedClass}">${task.failed_count}</span>
                </td>
                <td>${task.duration_display || '-'}</td>
                <td>${this.formatTime(task.start_time)}</td>
                <td>
                    ${task.error_messages && task.error_messages.length > 0
                    ? `<button class="btn btn-secondary detail-btn" onclick="window.uploadHistoryManager.showErrors('${task.task_id}')">查看错误</button>`
                    : '-'}
                </td>
            </tr>
        `;
        }).join('');
    }

    renderStatus(status) {
        const statusMap = {
            'completed': { text: '已完成', class: 'completed' },
            'running': { text: '进行中', class: 'running' },
            'failed': { text: '失败', class: 'failed' }
        };

        const statusInfo = statusMap[status] || { text: status, class: 'default' };
        return `<span class="status-badge ${statusInfo.class}">${statusInfo.text}</span>`;
    }

    formatTime(timeStr) {
        if (!timeStr) return '-';
        try {
            const date = new Date(timeStr);
            return date.toLocaleString('zh-CN', {
                year: 'numeric',
                month: '2-digit',
                day: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
        } catch (e) {
            return timeStr;
        }
    }

    truncate(str, maxLen) {
        if (str.length <= maxLen) return this.escapeHtml(str);
        return this.escapeHtml(str.substring(0, maxLen)) + '...';
    }

    showErrors(taskId) {
        const task = this.tasks.find(t => t.task_id === taskId);
        if (!task || !task.error_messages || task.error_messages.length === 0) {
            return;
        }

        this.showErrorDetailsModal(task);
    }

    showErrorDetailsModal(task) {
        // 设置任务ID和错误总数
        document.getElementById('errorTaskId').textContent = task.task_id;
        document.getElementById('errorTotalCount').textContent = task.error_messages.length;

        // 生成错误列表
        const errorList = document.getElementById('errorList');
        errorList.innerHTML = task.error_messages.map((err, index) => `
            <div class="error-item">
                <div class="error-item-header">
                    <span class="error-item-index">#${index + 1}</span>
                    ${err.loop_name ? `<span class="error-item-loop">回路: ${this.escapeHtml(err.loop_name)}</span>` : ''}
                </div>
                ${err.row_number ? `<div style="font-size: 12px; color: var(--text-muted); margin-bottom: 4px;">行号: ${err.row_number}</div>` : ''}
                <div class="error-item-message">${this.escapeHtml(err.error)}</div>
            </div>
        `).join('');

        // 显示模态框
        document.getElementById('errorDetailsModal').style.display = 'flex';
    }

    hideErrorDetailsModal() {
        document.getElementById('errorDetailsModal').style.display = 'none';
    }

    bindErrorModalEvents() {
        // 关闭按钮
        document.getElementById('errorDetailsClose').addEventListener('click', () => {
            this.hideErrorDetailsModal();
        });

        document.getElementById('errorDetailsConfirm').addEventListener('click', () => {
            this.hideErrorDetailsModal();
        });

        // 点击遮罩层关闭
        document.getElementById('errorDetailsModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('errorDetailsModal')) {
                this.hideErrorDetailsModal();
            }
        });
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// 导出供主应用使用
window.UploadHistoryManager = UploadHistoryManager;