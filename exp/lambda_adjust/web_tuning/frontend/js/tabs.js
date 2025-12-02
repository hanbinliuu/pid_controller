// 标签页切换功能
document.addEventListener('DOMContentLoaded', function() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const tabName = btn.dataset.tab;
            
            // 移除所有active类
            tabBtns.forEach(b => b.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            // 添加active类到当前标签
            btn.classList.add('active');
            document.getElementById(`${tabName}-tab`).classList.add('active');
            
            // 保存当前标签到localStorage
            localStorage.setItem('currentTab', tabName);
            
            // 🔧 标签页切换后的特殊处理
            handleTabSwitch(tabName);
        });
    });
    
    // 恢复上次打开的标签
    const savedTab = localStorage.getItem('currentTab');
    if (savedTab) {
        const savedBtn = document.querySelector(`[data-tab="${savedTab}"]`);
        if (savedBtn) {
            savedBtn.click();
        }
    }
});

// 处理标签页切换后的逻辑
function handleTabSwitch(tabName) {
    console.log('🔄 标签页切换到:', tabName);
    
    // 当切换到仿真结果页面时
    if (tabName === 'simulation') {
        // 详细检查数据状态
        console.log('📊 仿真数据检查:', {
            'window.simulationData': !!window.simulationData,
            'window.tuningResult': !!window.tuningResult,
            'simulationData.pv': window.simulationData?.pv?.length || 0,
            'tuningResult.data': !!window.tuningResult?.data
        });
        
        // 检查是否有仿真数据
        if (window.simulationData && window.tuningResult) {
            console.log('✅ 检测到仿真数据，准备渲染图表');
            
            // 🔧 优化：使用requestAnimationFrame确保DOM完全渲染
            requestAnimationFrame(() => {
                setTimeout(() => {
                    // 确保结果容器可见
                    const resultsContainer = document.getElementById('resultsContainer');
                    if (resultsContainer) {
                        resultsContainer.style.display = 'block';
                        console.log('✅ resultsContainer 已设置为可见');
                    }
                    
                    // 🔧 检查canvas元素是否存在且可见
                    const canvas = document.getElementById('simulationChart');
                    if (!canvas) {
                        console.error('❌ simulationChart canvas 元素不存在');
                        return;
                    }
                    
                    // 🔧 检查canvas是否在可见区域
                    const rect = canvas.getBoundingClientRect();
                    console.log('📐 Canvas尺寸:', {
                        width: rect.width,
                        height: rect.height,
                        visible: rect.width > 0 && rect.height > 0
                    });
                    
                    if (rect.width === 0 || rect.height === 0) {
                        console.warn('⚠️ Canvas尺寸为0，延迟渲染');
                        // 再次延迟尝试
                        setTimeout(() => renderSimulationChart(), 200);
                        return;
                    }
                    
                    // 渲染图表
                    renderSimulationChart();
                    
                }, 150); // 增加延迟到150ms
            });
        } else {
            console.warn('⚠️ 没有仿真数据可显示');
            if (!window.simulationData) {
                console.warn('  - window.simulationData 为空');
            }
            if (!window.tuningResult) {
                console.warn('  - window.tuningResult 为空');
            }
        }
    }
}

// 🔧 提取图表渲染逻辑为独立函数
function renderSimulationChart() {
    console.log('🎨 开始渲染仿真图表...');
    
    try {
        // 检查是否是稳态情况
        if (window.simulationData.is_steady_state) {
            console.log('📊 稳态情况，渲染稳态图表');
            console.log('🔍 稳态图表数据来源:', {
                'tuningResult存在': !!window.tuningResult,
                'tuningResult.data存在': !!window.tuningResult?.data,
                'simulationData存在': !!window.simulationData
            });
            
            if (typeof window.displaySteadyStateSimulation === 'function') {
                // 🔧 使用simulationData而不是tuningResult.data，确保使用最新数据
                window.displaySteadyStateSimulation(window.simulationData);
                console.log('✅ 稳态图表已渲染（使用simulationData）');
            } else {
                console.error('❌ displaySteadyStateSimulation 函数不存在');
            }
        } else {
            console.log('📊 正常情况，渲染仿真图表');
            if (typeof window.setupSimulationChart === 'function') {
                window.setupSimulationChart();
                console.log('✅ 仿真图表已渲染');
                
                // 🔧 强制Chart.js重新计算尺寸
                if (window.simulationChart) {
                    setTimeout(() => {
                        window.simulationChart.resize();
                        console.log('🔄 图表尺寸已更新');
                    }, 50);
                }
            } else {
                console.error('❌ setupSimulationChart 函数不存在');
            }
        }
    } catch (error) {
        console.error('❌ 渲染图表时出错:', error);
    }
}
