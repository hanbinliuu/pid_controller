/**
 * 图表工具模块
 * 统一管理Chart.js图表的创建、销毁和更新
 */

const ChartUtils = {
    /**
     * 已知的图表实例名称列表
     */
    CHART_INSTANCES: [
        'simulationChart',
        'simulationChartInstance',
        'originalChart',
        'comparisonChart',
        'modelComparisonChart'
    ],
    
    /**
     * 销毁指定的图表实例
     * @param {string} chartName - 图表实例名称
     * @returns {boolean} - 是否成功销毁
     */
    destroyChart(chartName) {
        try {
            // 检查window对象中的图表
            if (window[chartName]) {
                window[chartName].destroy();
                window[chartName] = null;
                if (window.Logger) {
                    window.Logger.debug(`销毁图表: ${chartName}`);
                }
                return true;
            }
            return false;
        } catch (error) {
            if (window.Logger) {
                window.Logger.warn(`销毁图表${chartName}失败:`, error);
            }
            return false;
        }
    },
    
    /**
     * 销毁所有已知的图表实例
     * @returns {number} - 成功销毁的图表数量
     */
    destroyAllCharts() {
        let destroyedCount = 0;
        
        if (window.Logger) {
            window.Logger.debug('开始销毁所有图表...');
        }
        
        this.CHART_INSTANCES.forEach(chartName => {
            if (this.destroyChart(chartName)) {
                destroyedCount++;
            }
        });
        
        if (window.Logger) {
            window.Logger.success(`已销毁 ${destroyedCount} 个图表`);
        }
        
        return destroyedCount;
    },
    
    /**
     * 清空Canvas画布
     * @param {string} canvasId - Canvas元素ID
     */
    clearCanvas(canvasId) {
        const canvas = document.getElementById(canvasId);
        if (canvas) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            if (window.Logger) {
                window.Logger.debug(`清空Canvas: ${canvasId}`);
            }
        }
    },
    
    /**
     * 清空所有已知的Canvas画布
     */
    clearAllCanvas() {
        const canvasIds = ['simulationChart', 'originalDataChart', 'comparisonChart'];
        canvasIds.forEach(id => this.clearCanvas(id));
    },
    
    /**
     * 检查图表实例是否存在
     * @param {string} chartName - 图表实例名称
     * @returns {boolean}
     */
    chartExists(chartName) {
        return window[chartName] !== null && window[chartName] !== undefined;
    },
    
    /**
     * 获取所有存在的图表实例
     * @returns {Array} - 存在的图表实例名称列表
     */
    getExistingCharts() {
        return this.CHART_INSTANCES.filter(name => this.chartExists(name));
    },
    
    /**
     * 打印图表状态信息（调试用）
     */
    printChartStatus() {
        if (!window.Logger) return;
        
        window.Logger.group('📊 图表状态');
        this.CHART_INSTANCES.forEach(chartName => {
            const exists = this.chartExists(chartName);
            const status = exists ? '✅ 存在' : '❌ 不存在';
            window.Logger.debug(`${chartName}: ${status}`);
        });
        window.Logger.groupEnd();
    },
    
    /**
     * 安全地创建图表（先销毁旧图表）
     * @param {string} chartName - 图表实例名称
     * @param {Function} createFn - 创建图表的函数
     * @returns {Object} - 创建的图表实例
     */
    safeCreateChart(chartName, createFn) {
        // 先销毁旧图表
        this.destroyChart(chartName);
        
        // 创建新图表
        const chart = createFn();
        
        // 保存到window对象
        window[chartName] = chart;
        
        if (window.Logger) {
            window.Logger.success(`创建图表: ${chartName}`);
        }
        
        return chart;
    },
    
    /**
     * 更新图表数据
     * @param {string} chartName - 图表实例名称
     * @param {Object} newData - 新数据
     */
    updateChartData(chartName, newData) {
        if (this.chartExists(chartName)) {
            const chart = window[chartName];
            chart.data = newData;
            chart.update();
            
            if (window.Logger) {
                window.Logger.debug(`更新图表数据: ${chartName}`);
            }
        } else {
            if (window.Logger) {
                window.Logger.warn(`图表不存在，无法更新: ${chartName}`);
            }
        }
    }
};

// 挂载到window对象
if (typeof window !== 'undefined') {
    window.ChartUtils = ChartUtils;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ChartUtils;
}
