// 模型树应用
class ModelTreeApp {
    constructor() {
        this.treeData = null;
        this.expandedNodes = new Set();
        this.selectedNode = null;
        this.searchTerm = '';
        this.init();
    }

    init() {
        this.bindEvents();
        this.loadTreeData();
    }

    bindEvents() {
        // 刷新按钮
        document.getElementById('refreshBtn').addEventListener('click', () => {
            this.loadTreeData();
        });

        // 重试按钮
        document.getElementById('retryBtn').addEventListener('click', () => {
            this.loadTreeData();
        });

        // 搜索输入
        document.getElementById('searchInput').addEventListener('input', (e) => {
            this.searchTerm = e.target.value.toLowerCase();
            this.renderTree();
        });
    }

    async loadTreeData() {
        this.showLoading();
        try {
            const response = await fetch('/api/bff/model-tree', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({})
            });
            const result = await response.json();

            if (result.code === 0 && result.data) {
                // 处理可能存在的result嵌套
                this.treeData = result.data.result || result.data;
                console.log('Tree Data Loaded:', this.treeData);
                this.renderTree();
            } else {
                this.showError(result.message || '加载失败');
            }
        } catch (error) {
            console.error('加载模型树失败:', error);
            this.showError('网络错误，请稍后重试');
        }
    }

    showLoading() {
        document.getElementById('loading').style.display = 'flex';
        document.getElementById('treeContent').style.display = 'none';
        document.getElementById('errorMessage').style.display = 'none';
    }

    showError(message) {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('treeContent').style.display = 'none';
        document.getElementById('errorMessage').style.display = 'flex';
        document.getElementById('errorText').textContent = message;
    }

    renderTree() {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('errorMessage').style.display = 'none';
        document.getElementById('treeContent').style.display = 'block';

        const container = document.getElementById('treeContent');
        container.innerHTML = '';

        if (!this.treeData) {
            return;
        }

        // 渲染根节点
        const rootNode = this.createTreeNode(this.treeData.node, 0, 'root', this.treeData.children);
        container.appendChild(rootNode);
    }

    createTreeNode(nodeData, level, type, children = []) {
        const nodeDiv = document.createElement('div');
        nodeDiv.className = 'tree-node';
        nodeDiv.style.paddingLeft = `${level * 8}px`;

        const hasChildren = children && children.length > 0;
        const uri = nodeData.uri;
        const displayName = nodeData.displayName || nodeData.browseName || uri;

        // 搜索过滤
        if (this.searchTerm && !this.matchesSearch(nodeData, children)) {
            nodeDiv.style.display = 'none';
            return nodeDiv;
        }

        const isExpanded = this.expandedNodes.has(uri) || this.searchTerm;
        const isSelected = this.selectedNode === uri;

        // 创建内容容器
        const contentDiv = document.createElement('div');
        contentDiv.className = `tree-node-content ${isSelected ? 'selected' : ''}`;
        contentDiv.dataset.uri = uri;

        // 展开图标
        const expandIcon = this.createExpandIcon(hasChildren, isExpanded);
        contentDiv.appendChild(expandIcon);

        // 节点图标
        const nodeIcon = this.createNodeIcon(type, hasChildren);
        contentDiv.appendChild(nodeIcon);

        // 节点名称
        const label = document.createElement('span');
        label.className = 'node-label';
        label.textContent = displayName;
        label.title = displayName;
        contentDiv.appendChild(label);

        // 保存原始节点数据用于后续操作
        const actualNodeData = {
            uri: uri,
            browseName: nodeData.browseName,
            displayName: displayName
        };

        // 子节点数量徽章
        if (hasChildren) {
            const badge = document.createElement('span');
            badge.className = 'node-badge';
            badge.textContent = children.length;
            contentDiv.appendChild(badge);
        }

        // 点击事件
        contentDiv.addEventListener('click', (e) => {
            e.stopPropagation();

            if (hasChildren) {
                this.toggleNode(uri);
            }

            this.selectNode(uri, actualNodeData);
        });

        // 右键菜单事件
        contentDiv.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
            if (window.deviceManager) {
                window.deviceManager.showContextMenu(e, actualNodeData, type === 'root');
            }
        });

        nodeDiv.appendChild(contentDiv);

        // 创建子节点容器
        if (hasChildren) {
            const childrenDiv = document.createElement('div');
            childrenDiv.className = `tree-node-children ${isExpanded ? '' : 'collapsed'}`;

            if (isExpanded || this.searchTerm) {
                children.forEach(child => {
                    const childType = this.getNodeType(child, type);
                    const childNode = this.createTreeNode(child.node || child, level + 1, childType, child.children);
                    childrenDiv.appendChild(childNode);
                });
            }

            nodeDiv.appendChild(childrenDiv);
        }

        return nodeDiv;
    }

    createExpandIcon(hasChildren, isExpanded) {
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('class', `expand-icon ${isExpanded ? 'expanded' : ''} ${!hasChildren ? 'hidden' : ''}`);
        icon.setAttribute('width', '20');
        icon.setAttribute('height', '20');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('fill', 'none');
        icon.setAttribute('stroke', 'currentColor');
        icon.setAttribute('stroke-width', '2');

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', 'M9 18l6-6-6-6');
        icon.appendChild(path);

        return icon;
    }

    createNodeIcon(type, hasChildren) {
        const icon = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        icon.setAttribute('class', `node-icon ${type}`);
        icon.setAttribute('width', '20');
        icon.setAttribute('height', '20');
        icon.setAttribute('viewBox', '0 0 24 24');
        icon.setAttribute('fill', 'none');
        icon.setAttribute('stroke', 'currentColor');
        icon.setAttribute('stroke-width', '2');

        let pathData = '';

        switch (type) {
            case 'root':
                pathData = 'M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z';
                break;
            case 'node':
                if (hasChildren) {
                    pathData = 'M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z';
                } else {
                    pathData = 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z';
                }
                break;
            default:
                pathData = 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z';
        }

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', pathData);
        icon.appendChild(path);

        return icon;
    }

    getNodeType(child, parentType) {
        return 'node';
    }

    matchesSearch(nodeData, children) {
        const displayName = (nodeData.displayName || nodeData.browseName || '').toLowerCase();
        if (displayName.includes(this.searchTerm)) {
            return true;
        }

        if (children && children.length > 0) {
            return children.some(child => {
                const childNode = child.node || child;
                return this.matchesSearch(childNode, child.children);
            });
        }

        return false;
    }

    toggleNode(uri) {
        if (this.expandedNodes.has(uri)) {
            this.expandedNodes.delete(uri);
        } else {
            this.expandedNodes.add(uri);
        }
        this.renderTree();
    }

    selectNode(uri, nodeData) {
        this.selectedNode = uri;
        this.renderTree();

        // 触发节点选择事件
        const event = new CustomEvent('nodeSelected', {
            detail: { uri, nodeData }
        });
        document.dispatchEvent(event);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => {
    // 初始化模型树应用
    window.modelTreeApp = new ModelTreeApp();

    // 初始化装置管理器
    if (window.DeviceManager) {
        window.deviceManager = new window.DeviceManager(window.modelTreeApp);
    }

    // 初始化回路列表管理器
    if (window.LoopListManager) {
        window.loopListManager = new window.LoopListManager();
    }

    // 初始化上传历史管理器
    if (window.UploadHistoryManager) {
        window.uploadHistoryManager = new window.UploadHistoryManager();
    }

    // 监听节点选择事件
    document.addEventListener('nodeSelected', (e) => {
        console.log('节点已选择:', e.detail);

        // 更新回路列表，传入节点URI和显示名称
        if (window.loopListManager && e.detail.uri) {
            const displayName = e.detail.nodeData ? e.detail.nodeData.displayName : '';
            window.loopListManager.onNodeSelected(e.detail.uri, displayName);
        }
    });
});
