// 回路列表管理模块
class LoopListManager {
    constructor() {
        this.currentNodeUri = null;
        this.currentNodeName = '';
        this.searchParams = {
            loopName: '',
            loopType: ''
        };
        this.pagination = {
            page: 1,
            pageSize: 10,
            total: 0
        };
        this.init();
    }

    init() {
        this.bindEvents();
        this.bindResultModalEvents();
    }

    bindEvents() {
        // 搜索按钮
        document.getElementById('searchBtn').addEventListener('click', () => {
            this.handleSearch();
        });

        // 重置按钮
        document.getElementById('resetBtn').addEventListener('click', () => {
            this.handleReset();
        });

        // 分页按钮
        document.getElementById('prevPage').addEventListener('click', () => {
            if (this.pagination.page > 1) {
                this.pagination.page--;
                this.loadLoopList();
            }
        });

        document.getElementById('nextPage').addEventListener('click', () => {
            const totalPages = Math.ceil(this.pagination.total / this.pagination.pageSize);
            if (this.pagination.page < totalPages) {
                this.pagination.page++;
                this.loadLoopList();
            }
        });

        // 上传按钮
        document.getElementById('uploadBtn').addEventListener('click', () => {
            if (!this.currentNodeUri) {
                alert('请先选择一个节点');
                return;
            }
            this.showUploadConfirmModal();
        });

        // 上传确认模态框事件
        document.getElementById('uploadModalClose').addEventListener('click', () => {
            this.hideUploadConfirmModal();
        });

        document.getElementById('uploadModalCancel').addEventListener('click', () => {
            this.hideUploadConfirmModal();
        });

        document.getElementById('uploadModalConfirm').addEventListener('click', () => {
            this.hideUploadConfirmModal();
            document.getElementById('csvFileInput').click();
        });

        document.getElementById('uploadModalOverlay').addEventListener('click', (e) => {
            if (e.target === document.getElementById('uploadModalOverlay')) {
                this.hideUploadConfirmModal();
            }
        });

        // 文件选择
        document.getElementById('csvFileInput').addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                this.handleFileUpload(file);
            }
            e.target.value = '';
        });
    }

    bindResultModalEvents() {
        // 成功模态框事件
        document.getElementById('uploadSuccessClose').addEventListener('click', () => {
            this.hideSuccessModal();
        });

        document.getElementById('uploadSuccessConfirm').addEventListener('click', () => {
            this.hideSuccessModal();
        });

        document.getElementById('uploadSuccessModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('uploadSuccessModal')) {
                this.hideSuccessModal();
            }
        });

        // 错误模态框事件
        document.getElementById('uploadErrorClose').addEventListener('click', () => {
            this.hideErrorModal();
        });

        document.getElementById('uploadErrorConfirm').addEventListener('click', () => {
            this.hideErrorModal();
        });

        document.getElementById('uploadErrorModal').addEventListener('click', (e) => {
            if (e.target === document.getElementById('uploadErrorModal')) {
                this.hideErrorModal();
            }
        });

        // 回路删除确认模态框事件
        const deleteModal = document.getElementById('loopDeleteModalOverlay');
        const deleteClose = document.getElementById('loopDeleteModalClose');
        const deleteCancel = document.getElementById('loopDeleteModalCancel');
        const deleteConfirm = document.getElementById('loopDeleteModalConfirm');

        const hideDeleteModal = () => {
            deleteModal.style.display = 'none';
            this.loopToDelete = null;
        };

        deleteClose.addEventListener('click', hideDeleteModal);
        deleteCancel.addEventListener('click', hideDeleteModal);

        deleteModal.addEventListener('click', (e) => {
            if (e.target === deleteModal) {
                hideDeleteModal();
            }
        });

        deleteConfirm.addEventListener('click', () => {
            if (this.loopToDelete) {
                this.handleDeleteLoop(this.loopToDelete);
                hideDeleteModal();
            }
        });
    }

    handleSearch() {
        this.searchParams.loopName = document.getElementById('loopNameSearch').value.trim();
        this.searchParams.loopType = document.getElementById('loopTypeSearch').value;
        this.pagination.page = 1;
        this.loadLoopList();
    }

    handleReset() {
        document.getElementById('loopNameSearch').value = '';
        document.getElementById('loopTypeSearch').value = '';
        this.searchParams = { loopName: '', loopType: '' };
        this.pagination.page = 1;
        this.loadLoopList();
    }

    onNodeSelected(uri, displayName) {
        this.currentNodeUri = uri;
        this.currentNodeName = displayName || '';
        this.pagination.page = 1;

        // 更新标题
        const headerTitle = document.querySelector('.loop-list-header h2');
        if (headerTitle) {
            headerTitle.textContent = displayName ? `${displayName}_回路列表` : '回路列表';
        }

        this.loadLoopList();
    }

    async loadLoopList() {
        if (!this.currentNodeUri) {
            return;
        }

        const tbody = document.getElementById('loopTableBody');
        tbody.innerHTML = '<tr class="loading-row"><td colspan="4">加载中...</td></tr>';

        try {
            const params = new URLSearchParams({
                loop_path: this.currentNodeUri,
                page: this.pagination.page,
                page_size: this.pagination.pageSize
            });

            if (this.searchParams.loopName) {
                params.append('loop_name', this.searchParams.loopName);
            }
            if (this.searchParams.loopType) {
                params.append('loop_type', this.searchParams.loopType);
            }

            const response = await fetch(`/api/v1/loop-info/list?${params}`);
            const result = await response.json();

            if (result.code === 0) {
                this.pagination.total = result.data.pagination?.total || 0;
                this.renderTable(result.data.mappings || []);
                this.updatePagination();
            } else {
                tbody.innerHTML = '<tr class="empty-row"><td colspan="4">加载失败：' + (result.message || '未知错误') + '</td></tr>';
            }
        } catch (error) {
            console.error('加载回路列表失败:', error);
            tbody.innerHTML = '<tr class="empty-row"><td colspan="4">加载失败：' + error.message + '</td></tr>';
        }
    }

    renderTable(loops) {
        const tbody = document.getElementById('loopTableBody');

        if (!loops || loops.length === 0) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="4">暂无数据</td></tr>';
            return;
        }

        const startIndex = (this.pagination.page - 1) * this.pagination.pageSize;

        tbody.innerHTML = loops.map((loop, index) => `
            <tr>
                <td>${startIndex + index + 1}</td>
                <td>${this.escapeHtml(loop.loop_name || '-')}</td>
                <td>${this.escapeHtml(loop.description || '-')}</td>
                <td>${this.escapeHtml(loop.loop_type || '-')}</td>
                <td>
                    <button class="btn btn-sm btn-secondary delete-loop-btn" data-uri="${loop.loop_uri}" data-name="${this.escapeHtml(loop.loop_name)}">
                        删除
                    </button>
                </td>
            </tr>
        `).join('');

        // 绑定删除按钮事件
        this.bindTableEvents();
    }

    updatePagination() {
        const totalPages = Math.ceil(this.pagination.total / this.pagination.pageSize) || 1;
        const paginationEl = document.getElementById('pagination');

        if (this.pagination.total > 0) {
            paginationEl.style.display = 'flex';
            document.getElementById('totalCount').textContent = this.pagination.total;
            document.getElementById('currentPage').textContent = this.pagination.page;
            document.getElementById('totalPages').textContent = totalPages;
            document.getElementById('prevPage').disabled = this.pagination.page <= 1;
            document.getElementById('nextPage').disabled = this.pagination.page >= totalPages;
        } else {
            paginationEl.style.display = 'none';
        }
    }

    async handleFileUpload(file) {
        // 验证文件类型
        if (!file.name.endsWith('.csv') && !file.name.endsWith('.xlsx')) {
            this.showErrorModal('只支持CSV或Excel(.xlsx)文件格式');
            return;
        }

        try {
            // 创建FormData
            const formData = new FormData();
            formData.append('file', file);

            // 禁用上传按钮
            const uploadBtn = document.getElementById('uploadBtn');
            uploadBtn.disabled = true;

            // 调用批量导入API
            const response = await fetch(`/api/loop/batch-import?parent_uri=${encodeURIComponent(this.currentNodeUri)}`, {
                method: 'POST',
                body: formData
            });

            const result = await response.json();

            // 检查返回的code字段
            if (result.code === 0) {
                // 任务提交成功 - 显示成功模态框
                this.showSuccessModal(result.data);

                // 3秒后刷新列表
                setTimeout(() => {
                    this.loadLoopList();
                }, 3000);
            } else {
                // 任务提交失败 - 显示错误模态框
                this.showErrorModal(result.message || '未知错误');
            }
        } catch (error) {
            console.error('文件上传失败:', error);
            this.showErrorModal(error.message || '网络错误，请稍后重试');
        } finally {
            // 恢复按钮状态
            const uploadBtn = document.getElementById('uploadBtn');
            uploadBtn.disabled = false;
        }
    }

    showUploadConfirmModal() {
        const uploadNodeName = document.getElementById('uploadNodeName');
        uploadNodeName.textContent = this.currentNodeName || '未知节点';
        document.getElementById('uploadModalOverlay').style.display = 'flex';
    }

    hideUploadConfirmModal() {
        document.getElementById('uploadModalOverlay').style.display = 'none';
    }

    showSuccessModal(data) {
        document.getElementById('successFileName').textContent = data.file_name || '';
        document.getElementById('successTotalCount').textContent = data.total_count || 0;
        document.getElementById('successTaskId').textContent = data.task_id || '';
        document.getElementById('uploadSuccessModal').style.display = 'flex';
    }

    hideSuccessModal() {
        document.getElementById('uploadSuccessModal').style.display = 'none';
    }

    showErrorModal(message) {
        document.getElementById('errorMessage').textContent = message;
        document.getElementById('uploadErrorModal').style.display = 'flex';
    }

    hideErrorModal() {
        document.getElementById('uploadErrorModal').style.display = 'none';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    bindTableEvents() {
        document.querySelectorAll('.delete-loop-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const uri = e.target.getAttribute('data-uri'); // use getAttribute for potentially custom data
                const name = e.target.getAttribute('data-name');
                this.showDeleteConfirm(uri, name);
            });
        });
    }

    showDeleteConfirm(uri, name) {
        this.loopToDelete = uri;
        document.getElementById('loopDeleteName').textContent = name;
        document.getElementById('loopDeleteModalOverlay').style.display = 'flex';
    }

    async handleDeleteLoop(uri) {
        try {
            const response = await fetch(`/api/loop/delete?loop_uri=${encodeURIComponent(uri)}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.code === 0) {
                // 使用 Generic Message Modal (如果存在) 或 alert
                if (window.deviceManager && window.deviceManager.showSuccessMessage) {
                    window.deviceManager.showSuccessMessage('删除成功', '回路已成功删除！');
                } else {
                    alert('删除成功！');
                }
                this.loadLoopList();
            } else {
                if (window.deviceManager && window.deviceManager.showErrorMessage) {
                    window.deviceManager.showErrorMessage('删除失败', result.message || '未知错误');
                } else {
                    alert('删除失败：' + (result.message || '未知错误'));
                }
            }
        } catch (error) {
            console.error('删除回路失败:', error);
            if (window.deviceManager && window.deviceManager.showErrorMessage) {
                window.deviceManager.showErrorMessage('删除失败', error.message);
            } else {
                alert('删除失败：' + error.message);
            }
        }
    }
}

// 导出供主应用使用
window.LoopListManager = LoopListManager;
