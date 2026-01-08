// 装置管理功能模块
class DeviceManager {
    constructor(app) {
        this.app = app;
        this.contextMenuNode = null;
        this.isEditMode = false;
        this.init();
    }

    init() {
        this.bindContextMenuEvents();
        this.bindModalEvents();
        this.bindDeleteModalEvents();
        this.bindMessageModalEvents();

        // 点击其他地方关闭右键菜单
        document.addEventListener('click', () => {
            this.hideContextMenu();
        });
    }

    bindContextMenuEvents() {
        const menuAddChild = document.getElementById('menuAddChild');
        const menuEdit = document.getElementById('menuEdit');
        const menuDelete = document.getElementById('menuDelete');

        menuAddChild.addEventListener('click', (e) => {
            e.stopPropagation();
            this.hideContextMenu();
            this.showAddModal();
        });

        menuEdit.addEventListener('click', (e) => {
            e.stopPropagation();
            this.hideContextMenu();
            this.showEditModal();
        });

        menuDelete.addEventListener('click', (e) => {
            e.stopPropagation();
            this.hideContextMenu();
            this.showDeleteModal();
        });
    }

    bindModalEvents() {
        const modalOverlay = document.getElementById('modalOverlay');
        const modalClose = document.getElementById('modalClose');
        const modalCancel = document.getElementById('modalCancel');
        const modalConfirm = document.getElementById('modalConfirm');

        modalClose.addEventListener('click', () => this.hideModal());
        modalCancel.addEventListener('click', () => this.hideModal());
        modalConfirm.addEventListener('click', () => this.handleModalConfirm());

        // 点击遮罩层关闭
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                this.hideModal();
            }
        });
    }

    bindDeleteModalEvents() {
        const deleteModalOverlay = document.getElementById('deleteModalOverlay');
        const deleteModalClose = document.getElementById('deleteModalClose');
        const deleteModalCancel = document.getElementById('deleteModalCancel');
        const deleteModalConfirm = document.getElementById('deleteModalConfirm');

        deleteModalClose.addEventListener('click', () => this.hideDeleteModal());
        deleteModalCancel.addEventListener('click', () => this.hideDeleteModal());
        deleteModalConfirm.addEventListener('click', () => this.handleDeleteConfirm());

        // 点击遮罩层关闭
        deleteModalOverlay.addEventListener('click', (e) => {
            if (e.target === deleteModalOverlay) {
                this.hideDeleteModal();
            }
        });
    }

    bindMessageModalEvents() {
        const modalOverlay = document.getElementById('genericMessageModal');
        const modalClose = document.getElementById('genericMessageClose');
        const modalConfirm = document.getElementById('genericMessageConfirm');

        const hideMessageModal = () => {
            modalOverlay.style.display = 'none';
        };

        modalClose.addEventListener('click', hideMessageModal);
        modalConfirm.addEventListener('click', hideMessageModal);

        // 点击遮罩层关闭
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                hideMessageModal();
            }
        });
    }

    showSuccessMessage(title, message) {
        const modal = document.getElementById('genericMessageModal');
        const titleEl = document.getElementById('genericMessageTitle');
        const contentEl = document.getElementById('genericMessageContent');

        titleEl.textContent = title || '操作成功';
        contentEl.className = 'result-message success-message';
        contentEl.innerHTML = `
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                <polyline points="22 4 12 14.01 9 11.01"></polyline>
            </svg>
            <h4>${message}</h4>
        `;

        modal.style.display = 'flex';
    }

    showErrorMessage(title, message) {
        const modal = document.getElementById('genericMessageModal');
        const titleEl = document.getElementById('genericMessageTitle');
        const contentEl = document.getElementById('genericMessageContent');

        titleEl.textContent = title || '操作失败';
        contentEl.className = 'result-message error-message';
        contentEl.innerHTML = `
            <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="15" y1="9" x2="9" y2="15"></line>
                <line x1="9" y1="9" x2="15" y2="15"></line>
            </svg>
            <h4>${message}</h4>
        `;

        modal.style.display = 'flex';
    }

    showContextMenu(event, nodeData, isRoot = false) {
        this.contextMenuNode = nodeData;
        const contextMenu = document.getElementById('contextMenu');
        const menuDelete = document.getElementById('menuDelete');

        // 根节点不显示删除选项
        if (isRoot) {
            menuDelete.style.display = 'none';
        } else {
            menuDelete.style.display = 'flex';
        }

        // 定位菜单
        contextMenu.style.display = 'block';
        contextMenu.style.left = event.pageX + 'px';
        contextMenu.style.top = event.pageY + 'px';

        // 确保菜单不超出屏幕
        const rect = contextMenu.getBoundingClientRect();
        if (rect.right > window.innerWidth) {
            contextMenu.style.left = (event.pageX - rect.width) + 'px';
        }
        if (rect.bottom > window.innerHeight) {
            contextMenu.style.top = (event.pageY - rect.height) + 'px';
        }
    }

    hideContextMenu() {
        const contextMenu = document.getElementById('contextMenu');
        contextMenu.style.display = 'none';
    }

    showAddModal() {
        this.isEditMode = false;
        const modalTitle = document.getElementById('modalTitle');
        const browseName = document.getElementById('browseName');
        const displayName = document.getElementById('displayName');

        modalTitle.textContent = '新增下级节点';
        browseName.value = '';
        browseName.disabled = false;
        displayName.value = '';

        document.getElementById('modalOverlay').style.display = 'flex';
    }

    showEditModal() {
        this.isEditMode = true;
        const modalTitle = document.getElementById('modalTitle');
        const browseName = document.getElementById('browseName');
        const displayName = document.getElementById('displayName');

        modalTitle.textContent = '编辑节点';
        browseName.value = this.contextMenuNode.browseName || '';
        browseName.disabled = true; // 编辑时浏览名称不可编辑
        displayName.value = this.contextMenuNode.displayName || '';

        document.getElementById('modalOverlay').style.display = 'flex';
    }

    showDeleteModal() {
        const deleteNodeName = document.getElementById('deleteNodeName');
        deleteNodeName.textContent = this.contextMenuNode.displayName || this.contextMenuNode.browseName;
        document.getElementById('deleteModalOverlay').style.display = 'flex';
    }

    hideModal() {
        document.getElementById('modalOverlay').style.display = 'none';
    }

    hideDeleteModal() {
        document.getElementById('deleteModalOverlay').style.display = 'none';
    }

    async handleModalConfirm() {
        const browseName = document.getElementById('browseName').value.trim();
        const displayName = document.getElementById('displayName').value.trim();

        // 验证输入
        if (!browseName || !displayName) {
            this.showErrorMessage('验证失败', '请填写所有必填项');
            return;
        }

        if (this.isEditMode) {
            await this.updateDevice(displayName);
        } else {
            await this.createDevice(browseName, displayName);
        }
    }

    async createDevice(browseName, displayName) {
        try {
            const targetUri = this.contextMenuNode.uri;
            const response = await fetch('/api/v1/device_manage/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    target_uri: targetUri,
                    browse_name: browseName,
                    display_name: displayName
                })
            });

            const result = await response.json();

            if (result.code === 0) {
                this.hideModal();
                this.showSuccessMessage('创建成功', '新增下级节点成功！');
                // 刷新树
                this.app.loadTreeData();
            } else {
                this.showErrorMessage('创建失败', result.message || '未知错误');
            }
        } catch (error) {
            console.error('创建装置失败:', error);
            this.showErrorMessage('创建失败', error.message);
        }
    }

    async updateDevice(displayName) {
        try {
            const deviceUri = this.contextMenuNode.uri;
            const response = await fetch('/api/v1/device_manage/update', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    device_uri: deviceUri,
                    display_name: displayName
                })
            });

            const result = await response.json();

            if (result.code === 0) {
                this.hideModal();
                this.showSuccessMessage('更新成功', '节点信息更新成功！');
                // 刷新树
                this.app.loadTreeData();
            } else {
                this.showErrorMessage('更新失败', result.message || '未知错误');
            }
        } catch (error) {
            console.error('更新装置失败:', error);
            this.showErrorMessage('更新失败', error.message);
        }
    }

    async handleDeleteConfirm() {
        try {
            const deviceUri = this.contextMenuNode.uri;
            const response = await fetch(`/api/v1/device_manage/delete?device_uri=${encodeURIComponent(deviceUri)}`, {
                method: 'DELETE'
            });

            const result = await response.json();

            if (result.code === 0) {
                this.hideDeleteModal();
                this.showSuccessMessage('删除成功', '节点已成功删除！');
                // 刷新树
                this.app.loadTreeData();
            } else {
                this.showErrorMessage('删除失败', result.message || '未知错误');
            }
        } catch (error) {
            console.error('删除装置失败:', error);
            this.showErrorMessage('删除失败', error.message);
        }
    }
}

// 导出供主应用使用
window.DeviceManager = DeviceManager;
