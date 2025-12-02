/**
 * Comparison Manager - 对比分析管理器
 * 前端JavaScript模块，用于调用对比分析API
 */

class ComparisonManager {
    constructor(apiBaseUrl = 'http://localhost:8000') {
        this.apiBaseUrl = apiBaseUrl;
    }

    /**
     * 对比多组PID参数
     */
    async compareParameters(paramsList, labels = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/parameters`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    params_list: paramsList,
                    labels: labels
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('参数对比失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 对比整定前后的参数
     */
    async compareBeforeAfter(originalParams, tunedParams) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/before_after`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    original_params: originalParams,
                    tuned_params: tunedParams
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('整定前后对比失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 对比不同整定方法
     */
    async compareMethods(methodResults) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/methods`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    method_results: methodResults
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('方法对比失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 对比性能指标
     */
    async comparePerformance(performanceList, labels = null) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/performance`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    performance_list: performanceList,
                    labels: labels
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('性能对比失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 与基准性能对比
     */
    async compareWithBaseline(baseline, current) {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/baseline`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    baseline: baseline,
                    current: current
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('基准对比失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 生成对比可视化图表
     */
    async visualizeComparison(paramsList, labels, chartType = 'radar') {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/comparison/visualize`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    params_list: paramsList,
                    labels: labels,
                    chart_type: chartType
                })
            });
            
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('可视化生成失败:', error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 显示参数对比结果
     */
    displayParameterComparison(result, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!result.success) {
            container.innerHTML = `<div class="error">对比失败: ${result.error}</div>`;
            return;
        }

        let html = '<div class="comparison-result">';
        html += '<h3>📊 参数对比分析</h3>';
        
        // 显示统计信息
        html += '<div class="statistics">';
        for (const [param, stats] of Object.entries(result.parameters)) {
            html += `
                <div class="param-stats">
                    <h4>${param.toUpperCase()}</h4>
                    <p>均值: ${stats.mean.toFixed(3)}</p>
                    <p>标准差: ${stats.std.toFixed(3)}</p>
                    <p>范围: ${stats.min.toFixed(3)} ~ ${stats.max.toFixed(3)}</p>
                    <p>变异系数: ${stats.cv.toFixed(1)}%</p>
                </div>
            `;
        }
        html += '</div>';

        // 显示分析结果
        if (result.analysis && result.analysis.length > 0) {
            html += '<div class="analysis">';
            html += '<h4>分析结果:</h4>';
            html += '<ul>';
            result.analysis.forEach(item => {
                html += `<li>${item}</li>`;
            });
            html += '</ul>';
            html += '</div>';
        }

        html += '</div>';
        container.innerHTML = html;
    }

    /**
     * 显示性能对比结果
     */
    displayPerformanceComparison(result, containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        if (!result.success) {
            container.innerHTML = `<div class="error">对比失败: ${result.error}</div>`;
            return;
        }

        let html = '<div class="performance-comparison">';
        html += '<h3>🏆 性能对比排名</h3>';
        
        // 显示排名
        if (result.ranking && result.ranking.length > 0) {
            html += '<table class="ranking-table">';
            html += '<thead><tr><th>排名</th><th>方案</th><th>得分</th></tr></thead>';
            html += '<tbody>';
            result.ranking.forEach(item => {
                const medal = item.rank === 1 ? '🥇' : item.rank === 2 ? '🥈' : item.rank === 3 ? '🥉' : '';
                html += `
                    <tr>
                        <td>${medal} ${item.rank}</td>
                        <td>${item.label}</td>
                        <td>${item.score.toFixed(1)}</td>
                    </tr>
                `;
            });
            html += '</tbody></table>';
        }

        // 显示分析
        if (result.analysis && result.analysis.length > 0) {
            html += '<div class="analysis">';
            html += '<h4>分析结果:</h4>';
            html += '<ul>';
            result.analysis.forEach(item => {
                html += `<li>${item}</li>`;
            });
            html += '</ul>';
            html += '</div>';
        }

        html += '</div>';
        container.innerHTML = html;
    }
}

// 导出为全局变量
if (typeof window !== 'undefined') {
    window.ComparisonManager = ComparisonManager;
}
