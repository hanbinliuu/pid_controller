// Global state
let resourceSpacesList = [];
let resourceSpaceMap = {}; // ID -> Name
let currentResourceInput = null;

// Initialization
document.addEventListener('DOMContentLoaded', loadConfigs);

async function loadConfigs() {
    const loading = document.getElementById('loading');
    const errorDiv = document.getElementById('error');
    const table = document.getElementById('configTable');
    const tbody = document.getElementById('configTableBody');

    // Reset state
    loading.style.display = 'block';
    errorDiv.style.display = 'none';
    table.style.display = 'none';
    tbody.innerHTML = '';

    try {
        // Parallel fetch configs and resource spaces
        const [configResponse, spaces] = await Promise.all([
            fetch('/api/v1/dynamic-config/list-all'),
            fetchResourceSpacesList()
        ]);

        if (!configResponse.ok) {
            throw new Error(`加载配置失败: ${configResponse.status}`);
        }

        const configData = await configResponse.json();
        const configs = (configData.data && configData.data.configs) ? configData.data.configs : [];

        // Build Map for easy lookup
        resourceSpaceMap = {};
        if (spaces && Array.isArray(spaces)) {
            resourceSpacesList = spaces;
            spaces.forEach(space => {
                resourceSpaceMap[space.id] = space.name;
            });
        }

        // Render table
        if (configs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: #666;">暂无配置数据</td></tr>';
        } else {
            tbody.innerHTML = configs.map(config => renderConfigRow(config)).join('');
        }

        table.style.display = 'table';
    } catch (err) {
        console.error('加载失败:', err);
        errorDiv.textContent = '加载失败，请刷新重试';
        errorDiv.style.display = 'block';
    } finally {
        loading.style.display = 'none';
    }
}

async function fetchResourceSpacesList() {
    try {
        const response = await fetch('/api/v1/proxy/resource-spaces');
        if (!response.ok) return [];
        const data = await response.json();

        let spaces = [];
        if (data.data && Array.isArray(data.data.results)) {
            spaces = data.data.results;
        } else if (Array.isArray(data)) {
            spaces = data;
        } else if (Array.isArray(data.data)) {
            spaces = data.data;
        }
        return spaces;
    } catch (e) {
        console.error('Fetch resource spaces failed:', e);
        return [];
    }
}

function renderConfigRow(config) {
    let inputHtml;
    if (config.config_key === 'default_resource_space') {
        const id = config.config_value;
        const name = resourceSpaceMap[id] || id; // Show name if found, else ID
        inputHtml = `
            <input type="text" 
                   class="config-input" 
                   data-key="${escapeHtml(config.config_key)}" 
                   data-real-value="${escapeHtml(id)}"
                   value="${escapeHtml(name)}"
                   readonly
                   style="cursor: pointer; background-color: #f8fafc;"
                   onclick="openResourceSpaceModal(this)"
                   placeholder="点击选择资源空间">
        `;
    } else {
        inputHtml = `
            <input type="text" 
                   class="config-input" 
                   data-key="${escapeHtml(config.config_key)}" 
                   value="${escapeHtml(config.config_value)}"
                   placeholder="请输入配置值">
        `;
    }

    return `
    <tr>
        <td>${escapeHtml(config.config_name || '-')}</td>
        <td style="font-family: monospace; color: #2563eb;">${escapeHtml(config.config_key)}</td>
        <td>${inputHtml}</td>
        <td><span style="background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-size: 12px;">${escapeHtml(config.config_group || 'DEFAULT')}</span></td>
        <td style="font-size: 13px; color: #64748b;">${formatDate(config.updated_time || config.created_time)}</td>
    </tr>`;
}

async function saveConfigs() {
    const saveBtn = document.querySelector('.save-btn');
    const inputs = document.querySelectorAll('.config-input');
    const configData = {};

    inputs.forEach(input => {
        const key = input.getAttribute('data-key');
        // Use data-real-value if present (for resource space), else value
        const value = input.hasAttribute('data-real-value') ? input.getAttribute('data-real-value') : input.value.trim();

        if (key) {
            configData[key] = value;
        }
    });

    if (Object.keys(configData).length === 0) {
        showToast('没有任何配置项可保存', 'error');
        return;
    }

    try {
        saveBtn.disabled = true;
        saveBtn.textContent = '保存中...';

        const response = await fetch('/api/v1/dynamic-config/batch-update', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(configData)
        });

        if (!response.ok) {
            throw new Error(`保存失败: ${response.status}`);
        }

        const result = await response.json();

        if (result.failed_count > 0) {
            const failedItems = result.results
                .filter(r => r.status === 'failed')
                .map(r => `${r.config_key}: ${r.message}`)
                .join('\n');
            alert(`部分保存失败:\n${failedItems}`);
        } else {
            showToast('保存成功', 'success');
        }

        // Reload to refresh view/data
        loadConfigs();

    } catch (err) {
        console.error('保存失败:', err);
        showToast('保存失败，请检查网络或服务器日志', 'error');
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '保存配置';
    }
}

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    void toast.offsetWidth; // Force reflow
    toast.classList.add('show');
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

function escapeHtml(text) {
    if (!text && text !== 0) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(isoString) {
    if (!isoString) return '-';
    // Format: YYYY-MM-DD HH:mm:ss
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN', { hour12: false });
}

// Resource Space Modal Logic

function openResourceSpaceModal(input) {
    console.log('Opening resource space modal');
    currentResourceInput = input;
    const modal = document.getElementById('resourceSpaceModal');
    modal.style.display = 'flex';
    loadResourceSpaces();
}

function closeResourceSpaceModal() {
    const modal = document.getElementById('resourceSpaceModal');
    modal.style.display = 'none';
    currentResourceInput = null;
}

async function loadResourceSpaces() {
    console.log('Loading resource spaces...');
    const tbody = document.getElementById('resourceTableBody');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px; color:#666;">加载中...</td></tr>';

    // If we have cached list, verify if we should just use it? 
    // Usually safe to re-fetch or use cached. 
    // Let's use cached if available to save network, or fetch if empty.
    let spaces = resourceSpacesList;
    if (spaces.length === 0) {
        spaces = await fetchResourceSpacesList();
        resourceSpacesList = spaces; // update cache
        // update map
        spaces.forEach(space => resourceSpaceMap[space.id] = space.name);
    }

    if (spaces.length === 0) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding:20px; color:#666;">无数据</td></tr>';
        return;
    }

    tbody.innerHTML = spaces.map((space, index) => {
        const seq = index + 1;
        // Escape quotes properly for onclick
        const safeName = escapeHtml(space.name).replace(/'/g, "\\'");
        return `
        <tr onclick="selectResourceSpace('${escapeHtml(space.id)}', '${safeName}')">
            <td>${seq}</td>
            <td>${escapeHtml(space.name)}</td>
            <td>${escapeHtml(space.tenantName || '-')}</td>
            <td>${escapeHtml(space.orgName || '-')}</td>
        </tr>
    `}).join('');
}

function selectResourceSpace(spaceId, spaceName) {
    console.log('Selected resource space:', spaceId, spaceName);
    if (currentResourceInput) {
        // Display Name, Store ID
        currentResourceInput.value = spaceName;
        currentResourceInput.setAttribute('data-real-value', spaceId);
    }
    closeResourceSpaceModal();
}

// Ensure functions are global
window.openResourceSpaceModal = openResourceSpaceModal;
window.closeResourceSpaceModal = closeResourceSpaceModal;
window.selectResourceSpace = selectResourceSpace;
