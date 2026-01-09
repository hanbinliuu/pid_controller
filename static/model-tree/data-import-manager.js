/**
 * 数据导入及历史管理模块
 * 依赖: md5.js
 */
class DataImportManager {
    constructor() {
        this.currentFile = null;
        this.uploadId = null;
        this.chunkSize = 0;
        this.blockList = [];
        this.uploadedChunks = 0;
        this.pagination = {
            page: 1,
            pageSize: 10,
            total: 0
        };

        this.init();
    }

    init() {
        this.bindEvents();
        this.bindHistoryEvents();
    }

    bindEvents() {
        // 打开导入模态框
        document.getElementById('dataImportBtn').addEventListener('click', () => {
            this.showImportModal();
        });

        // 关闭导入模态框
        document.getElementById('dataImportClose').addEventListener('click', () => {
            this.hideImportModal();
        });
        document.getElementById('dataImportCancel').addEventListener('click', () => {
            this.hideImportModal();
        });
        document.getElementById('dataImportOverlay').addEventListener('click', (e) => {
            if (e.target === document.getElementById('dataImportOverlay')) {
                this.hideImportModal();
            }
        });

        // 文件与拖拽区域交互
        const dropArea = document.getElementById('dataImportDropArea');
        const fileInput = document.getElementById('dataImportFile');

        // 点击区域触发文件选择
        dropArea.addEventListener('click', () => {
            fileInput.click();
        });

        // 拖拽效果
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        ['dragenter', 'dragover'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.add('dragover'), false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropArea.addEventListener(eventName, () => dropArea.classList.remove('dragover'), false);
        });

        // 处理文件拖放
        dropArea.addEventListener('drop', (e) => {
            const dt = e.dataTransfer;
            const files = dt.files;
            if (files.length > 0) {
                this.handleFileSelect(files[0]);
            }
        });

        // 文件选择变化
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleFileSelect(e.target.files[0]);
            }
        });

        // 开始导入
        document.getElementById('dataImportStartBtn').addEventListener('click', () => {
            if (this.currentFile) {
                this.startImport();
            }
        });
    }

    bindHistoryEvents() {
        // 打开历史模态框
        document.getElementById('dataImportHistoryBtn').addEventListener('click', () => {
            this.showHistoryModal();
        });

        // 关闭历史模态框
        document.getElementById('dataImportHistoryClose').addEventListener('click', () => {
            this.hideHistoryModal();
        });
        document.getElementById('dataImportHistoryOverlay').addEventListener('click', (e) => {
            if (e.target === document.getElementById('dataImportHistoryOverlay')) {
                this.hideHistoryModal();
            }
        });

        // 搜索/筛选
        document.getElementById('dataHistorySearchBtn').addEventListener('click', () => {
            this.pagination.page = 1;
            this.loadHistory();
        });

        // 分页
        document.getElementById('dataHistoryPrev').addEventListener('click', () => {
            if (this.pagination.page > 1) {
                this.pagination.page--;
                this.loadHistory();
            }
        });
        document.getElementById('dataHistoryNext').addEventListener('click', () => {
            const totalPages = Math.ceil(this.pagination.total / this.pagination.pageSize);
            if (this.pagination.page < totalPages) {
                this.pagination.page++;
                this.loadHistory();
            }
        });
    }

    handleFileSelect(file) {
        if (file) {
            this.currentFile = file;
            const fileNameDisplay = document.getElementById('dataImportFileName');
            fileNameDisplay.textContent = file.name;
            fileNameDisplay.style.display = 'block';

            document.getElementById('dataImportStartBtn').disabled = false;

            // Reset progress
            this.updateProgress(0);
            document.getElementById('dataImportProgress').style.display = 'none';
            document.getElementById('dataImportStatus').textContent = '';
            document.getElementById('dataImportStatus').className = 'status-text';
            document.getElementById('dataImportPercent').textContent = '0%';
        }
    }

    showImportModal() {
        document.getElementById('dataImportOverlay').style.display = 'flex';
        // Reset UI
        document.getElementById('dataImportFile').value = '';
        document.getElementById('dataImportFileName').textContent = '未选择文件';
        document.getElementById('dataImportFileName').style.display = 'none';
        document.getElementById('dataImportDesc').value = '';
        document.getElementById('dataImportStartBtn').disabled = true;
        document.getElementById('dataImportProgress').style.display = 'none';
        this.currentFile = null;
    }

    hideImportModal() {
        document.getElementById('dataImportOverlay').style.display = 'none';
    }

    async startImport() {
        if (!this.currentFile) return;

        const startBtn = document.getElementById('dataImportStartBtn');
        const fileInput = document.getElementById('dataImportFile');
        const descInput = document.getElementById('dataImportDesc');

        startBtn.disabled = true;
        fileInput.disabled = true;
        descInput.disabled = true;

        document.getElementById('dataImportProgress').style.display = 'block';
        this.updateProgress(0, '正在初始化上传...');

        try {
            // 1. 创建上传任务
            const initResponse = await fetch('/api/v1/history/data/files', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    file_name: this.currentFile.name,
                    file_size: this.currentFile.size,
                    desc: descInput.value || ''
                })
            });

            if (!initResponse.ok) {
                const error = await initResponse.json();
                throw new Error(error.detail || '初始化上传失败');
            }

            const result = await initResponse.json();

            if (result.code !== 0 && result.code !== 200) { // Support both just in case, but usually 0 is success in this system
                throw new Error(result.message || '初始化上传失败');
            }

            const initData = result.data;
            this.uploadId = initData.upload_id;
            this.blockList = initData.block_list;
            this.chunkSize = initData.block_size;

            // 2. 分块上传
            await this.uploadChunks();

            this.updateProgress(100, '上传完成！');
            document.getElementById('dataImportStatus').className = 'status-text success';

            // 稍后关闭并刷新列表(如果有打开历史)
            setTimeout(() => {
                this.hideImportModal();
                fileInput.disabled = false;
                descInput.disabled = false;
                // Optionally open history or refresh it
            }, 1000);

        } catch (error) {
            console.error('上传失败:', error);
            this.updateProgress(0, '上传失败: ' + error.message);
            document.getElementById('dataImportStatus').className = 'status-text error';
            startBtn.disabled = false;
            fileInput.disabled = false;
            descInput.disabled = false;
        }
    }

    async uploadChunks() {
        const totalBlocks = this.blockList.length;
        this.uploadedChunks = 0;

        // Process blocks sequentially to keep it simple, or parallel restricted
        // Since block_list is a list of IDs, we iterate it.
        // Assuming block_list is numeric usually 0, 1, 2... but API says Set[int].

        // Sort block list to be safe
        const sortedBlocks = this.blockList.sort((a, b) => a - b);

        for (const blockId of sortedBlocks) {
            const start = blockId * this.chunkSize;
            const end = Math.min(start + this.chunkSize, this.currentFile.size);
            const chunk = this.currentFile.slice(start, end);

            await this.uploadSingleChunk(chunk, blockId);

            this.uploadedChunks++;
            const percent = Math.round((this.uploadedChunks / totalBlocks) * 100);
            this.updateProgress(percent, `正在上传... ${percent}%`);
        }
    }

    async uploadSingleChunk(chunkBlob, blockId) {
        // Calculate MD5 of chunk
        const arrayBuffer = await chunkBlob.arrayBuffer();
        const md5Hash = SparkMD5.ArrayBuffer.hash(arrayBuffer);

        // Debug logging
        console.log(`[Upload Debug] Block ${blockId}: size=${arrayBuffer.byteLength}, md5=${md5Hash}`);

        // CRITICAL: 后端使用 request.body() 读取原始字节，不能用 FormData
        // FormData 会添加 multipart 边界和头部，导致大小和MD5不匹配
        // 必须发送原始 ArrayBuffer，匹配 Python 测试代码的行为
        const headers = {
            'Content-Type': 'application/octet-stream'
        };

        // Construct query params
        const params = new URLSearchParams({
            upload_id: this.uploadId,
            block_id: blockId,
            md5: md5Hash
        });

        const response = await fetch(`/api/v1/history/data/files?${params.toString()}`, {
            method: 'PUT',
            headers: headers,
            body: arrayBuffer  // 发送与MD5计算相同的数据
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `块 ${blockId} 上传失败`);
        }

        // Check response for success
        const result = await response.json();
        if (result.code !== 0) {
            throw new Error(result.message || `块 ${blockId} 上传失败`);
        }
    }


    updateProgress(percent, text) {
        const bar = document.getElementById('dataImportProgressBar');
        const status = document.getElementById('dataImportStatus');
        const percentText = document.getElementById('dataImportPercent');

        if (bar) bar.style.width = `${percent}%`;
        if (status && text) status.textContent = text;
        if (percentText) percentText.textContent = `${percent}%`;
    }

    // --- History Logic ---

    showHistoryModal() {
        document.getElementById('dataImportHistoryOverlay').style.display = 'flex';
        this.pagination.page = 1;
        this.loadHistory();
    }

    hideHistoryModal() {
        document.getElementById('dataImportHistoryOverlay').style.display = 'none';
    }

    async loadHistory() {
        const tbody = document.getElementById('dataImportHistoryTableBody');
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">加载中...</td></tr>';

        const fileName = document.getElementById('dataHistoryNameSearch').value.trim();
        const startTime = document.getElementById('dataHistoryDateStart').value;
        const endTime = document.getElementById('dataHistoryDateEnd').value;

        const params = new URLSearchParams({
            page_num: this.pagination.page,
            page_size: this.pagination.pageSize
        });

        if (fileName) params.append('file_name', fileName);
        // datetime-local value is "YYYY-MM-DDTHH:mm", backend expects "YYYY-MM-DDTHH:mm:ss"
        if (startTime) params.append('start_time', startTime.includes(':') && startTime.length === 16 ? startTime + ':00' : startTime);
        if (endTime) params.append('end_time', endTime.includes(':') && endTime.length === 16 ? endTime + ':00' : endTime);

        try {
            const response = await fetch(`/api/v1/history/data/files?${params.toString()}`);
            if (!response.ok) throw new Error('加载失败');

            const result = await response.json();
            if (result.code !== 0) {
                throw new Error(result.message || '加载失败');
            }
            const data = result.data;

            this.pagination.total = data.total;
            this.renderHistoryTable(data.files);
            this.updatePagination();
        } catch (error) {
            console.error(error);
            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:red;">加载失败: ${error.message}</td></tr>`;
        }
    }

    renderHistoryTable(files) {
        const tbody = document.getElementById('dataImportHistoryTableBody');
        if (!files || files.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;">暂无数据</td></tr>';
            return;
        }

        tbody.innerHTML = files.map((file, index) => `
            <tr>
                <td>${(this.pagination.page - 1) * this.pagination.pageSize + index + 1}</td>
                <td>${this.escapeHtml(file.name)}</td>
                <td>${this.formatSize(file.size)}</td>
                <td>${this.formatStatus(file.status)}</td>
                <td>${file.imported_records || 0} / ${file.total_records || 0}</td>
                <td title="${this.escapeHtml(file.failed_reason || '')}" style="color: #ff4d4f;">${this.truncateText(file.failed_reason || '-', 15)}</td>
                <td>${file.create_time}</td>
                <td title="${this.escapeHtml(file.description || '')}">${this.truncateText(file.description || '-', 15)}</td>
                <td>
                    <button class="btn btn-sm btn-primary" onclick="window.dataImportManager.downloadHistory(${file.fid})">下载</button>
                    <button class="btn btn-sm btn-secondary" onclick="window.dataImportManager.reimportHistory(${file.fid})">重新导入</button>
                    <button class="btn btn-sm btn-danger" onclick="window.dataImportManager.deleteHistory(${file.fid})">删除</button>
                </td>
            </tr>
        `).join('');
    }

    updatePagination() {
        const totalPages = Math.ceil(this.pagination.total / this.pagination.pageSize) || 1;
        document.getElementById('dataHistoryTotal').textContent = this.pagination.total;
        document.getElementById('dataHistoryPage').textContent = `${this.pagination.page}/${totalPages}`;
        document.getElementById('dataHistoryPrev').disabled = this.pagination.page <= 1;
        document.getElementById('dataHistoryNext').disabled = this.pagination.page >= totalPages;
    }

    downloadHistory(fid) {
        window.location.href = `/api/v1/history/data/files/${fid}`;
    }

    async deleteHistory(fid) {
        if (!confirm('确定要删除该条记录吗？')) return;
        try {
            const response = await fetch(`/api/v1/history/data/files/${fid}`, {
                method: 'DELETE'
            });
            if (response.ok) {
                alert('删除成功');
                this.loadHistory();
            } else {
                alert('删除失败');
            }
        } catch (e) {
            alert('删除失败');
        }
    }

    async reimportHistory(fid) {
        try {
            const response = await fetch(`/api/v1/history/data/reimport/files/${fid}`);
            if (response.ok) {
                alert('已触发重新导入');
                this.loadHistory();
            } else {
                const err = await response.json();
                alert('重新导入失败: ' + err.detail);
            }
        } catch (e) {
            alert('操作失败');
        }
    }

    formatSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    formatStatus(status) {
        const statusMap = {
            'IMPORTED': '<span style="color: #52c41a; font-weight: 500;">已导入</span>',
            'PENDING': '<span style="color: #faad14; font-weight: 500;">等待中</span>',
            'IMPORTING': '<span style="color: #1890ff; font-weight: 500;">导入中</span>',
            'FAILED': '<span style="color: #ff4d4f; font-weight: 500;">失败</span>',
        };
        return statusMap[status] || `<span style="color: #8c8c8c;">${status || '未知'}</span>`;
    }

    truncateText(text, maxLength) {
        if (!text || text.length <= maxLength) {
            return text;
        }
        return text.substring(0, maxLength) + '...';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Export instance
window.DataImportManager = DataImportManager;
