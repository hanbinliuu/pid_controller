// UI增强功能：折叠面板、快速导航、紧凑模式

// 折叠面板功能
function initCollapsibleSections() {
    // 将主要的chart-container转换为可折叠
    const containers = document.querySelectorAll('.chart-container');
    
    containers.forEach((container, index) => {
        // 跳过已经处理的
        if (container.classList.contains('collapsible-processed')) return;
        
        const title = container.querySelector('.chart-title');
        if (!title) return;
        
        // 创建折叠结构
        const section = document.createElement('div');
        section.className = 'collapsible-section';
        
        const header = document.createElement('div');
        header.className = 'collapsible-header';
        header.innerHTML = `
            <span>${title.textContent}</span>
            <span class="toggle-icon">▼</span>
        `;
        
        const content = document.createElement('div');
        content.className = 'collapsible-content';
        
        // 移动原内容
        const originalContent = container.innerHTML;
        content.innerHTML = originalContent;
        
        // 组装
        section.appendChild(header);
        section.appendChild(content);
        container.parentNode.replaceChild(section, container);
        
        // 默认展开第一个和最后一个
        if (index === 0 || index === containers.length - 1) {
            header.classList.add('active');
            content.classList.add('active');
        }
        
        // 点击切换
        header.addEventListener('click', () => {
            header.classList.toggle('active');
            content.classList.toggle('active');
        });
        
        container.classList.add('collapsible-processed');
    });
}

// 快速导航
function initQuickNav() {
    const nav = document.createElement('div');
    nav.className = 'quick-nav';
    nav.id = 'quickNav';
    
    const sections = [
        { id: 'uploadSection', name: '📁 上传', icon: '📁' },
        { id: 'resultsContainer', name: '📊 结果', icon: '📊' },
        { id: 'parameterTuningSection', name: '🎛️ 微调', icon: '🎛️' },
        { id: 'modelComparisonContainer', name: '🔬 对比', icon: '🔬' },
        { id: 'aiAssistantContainer', name: '🤖 AI', icon: '🤖' }
    ];
    
    sections.forEach(section => {
        const item = document.createElement('a');
        item.className = 'quick-nav-item';
        item.href = '#';
        item.textContent = section.icon;
        item.title = section.name;
        item.onclick = (e) => {
            e.preventDefault();
            const target = document.getElementById(section.id);
            if (target && target.style.display !== 'none') {
                target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                
                // 更新active状态
                document.querySelectorAll('.quick-nav-item').forEach(i => i.classList.remove('active'));
                item.classList.add('active');
            }
        };
        nav.appendChild(item);
    });
    
    document.body.appendChild(nav);
    
    // 滚动时显示/隐藏导航
    let scrollTimeout;
    window.addEventListener('scroll', () => {
        clearTimeout(scrollTimeout);
        if (window.scrollY > 300) {
            nav.classList.add('visible');
        }
        scrollTimeout = setTimeout(() => {
            if (window.scrollY < 300) {
                nav.classList.remove('visible');
            }
        }, 1000);
    });
}

// 紧凑模式切换
function toggleCompactMode() {
    document.body.classList.toggle('compact-mode');
    const isCompact = document.body.classList.contains('compact-mode');
    localStorage.setItem('compactMode', isCompact);
    
    // 更新按钮文本
    const btn = document.getElementById('compactModeBtn');
    if (btn) {
        btn.textContent = isCompact ? '📏 标准模式' : '📐 紧凑模式';
    }
}

// 添加紧凑模式按钮到header
function addCompactModeButton() {
    const header = document.querySelector('header .header-content');
    if (!header || document.getElementById('compactModeBtn')) return;
    
    const btn = document.createElement('button');
    btn.id = 'compactModeBtn';
    btn.className = 'btn btn-secondary';
    btn.style.cssText = 'margin-left: 15px; padding: 8px 16px; font-size: 13px;';
    btn.textContent = '📐 紧凑模式';
    btn.onclick = toggleCompactMode;
    
    header.appendChild(btn);
    
    // 恢复之前的设置
    if (localStorage.getItem('compactMode') === 'true') {
        toggleCompactMode();
    }
}

// 智能折叠：自动折叠不常用的区域
function smartCollapse() {
    // 整定完成后，自动折叠上传区域
    const uploadSection = document.getElementById('uploadSection');
    if (uploadSection && uploadedData) {
        const header = uploadSection.previousElementSibling;
        if (header && header.classList.contains('collapsible-header')) {
            header.classList.remove('active');
            uploadSection.classList.remove('active');
        }
    }
}

// 回到顶部按钮
function addBackToTop() {
    const btn = document.createElement('button');
    btn.id = 'backToTop';
    btn.innerHTML = '↑';
    btn.style.cssText = `
        position: fixed;
        right: 20px;
        bottom: 20px;
        width: 50px;
        height: 50px;
        border-radius: 50%;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        font-size: 24px;
        cursor: pointer;
        display: none;
        z-index: 99;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    `;
    
    btn.onclick = () => {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };
    
    document.body.appendChild(btn);
    
    window.addEventListener('scroll', () => {
        if (window.scrollY > 500) {
            btn.style.display = 'block';
        } else {
            btn.style.display = 'none';
        }
    });
    
    btn.addEventListener('mouseenter', () => {
        btn.style.transform = 'scale(1.1)';
    });
    
    btn.addEventListener('mouseleave', () => {
        btn.style.transform = 'scale(1)';
    });
}

// 初始化所有UI增强
function initUIEnhancements() {
    console.log('🎨 初始化UI增强功能...');
    
    // 延迟执行，确保DOM完全加载
    setTimeout(() => {
        addCompactModeButton();
        initQuickNav();
        addBackToTop();
        
        // 监听内容变化，动态添加折叠功能
        const observer = new MutationObserver(() => {
            // 当新内容出现时，可以添加折叠功能
            // 这里暂时不自动折叠，避免影响用户体验
        });
        
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }, 1000);
}

// 页面加载时初始化
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initUIEnhancements);
} else {
    initUIEnhancements();
}

console.log('✨ UI增强模块已加载');
