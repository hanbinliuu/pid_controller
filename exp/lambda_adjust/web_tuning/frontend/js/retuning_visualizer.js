/**
 * 重整定可视化模块
 * 显示原参数vs新参数的仿真对比
 */

class RetuningVisualizer {
    constructor() {
        this.comparisonChart = null;
    }
    
    /**
     * 显示重整定对比
     * @param {Object} retuningRecord - 重整定记录
     */
    showRetuningComparison(retuningRecord) {
        const modal = this.createComparisonModal(retuningRecord);
        document.body.appendChild(modal);
        
        // 延迟渲染图表，确保DOM已加载
        setTimeout(() => {
            this.renderComparisonChart(retuningRecord);
        }, 100);
    }
    
    /**
     * 创建对比模态框
     */
    createComparisonModal(record) {
        const modal = document.createElement('div');
        modal.id = 'retuningComparisonModal';
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            animation: fadeIn 0.3s;
        `;
        
        const oldParams = record.old_params || {};
        const newParams = record.new_params || {};
        const performance = record.performance || {};
        
        modal.innerHTML = `
            <div style="background: #1e293b; border-radius: 16px; padding: 32px; max-width: 1200px; width: 90%; max-height: 90vh; overflow-y: auto; box-shadow: 0 20px 60px rgba(0,0,0,0.5);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px;">
                    <h2 style="color: #e2e8f0; margin: 0; font-size: 24px;">🔄 自动重整定结果对比</h2>
                    <button onclick="document.getElementById('retuningComparisonModal').remove()" 
                            style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: none; padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600;">
                        ✖ 关闭
                    </button>
                </div>
                
                <!-- 重整定信息 -->
                <div style="background: rgba(102, 126, 234, 0.1); padding: 20px; border-radius: 12px; margin-bottom: 24px; border-left: 4px solid #667eea;">
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
                        <div>
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 4px;">触发时间</div>
                            <div style="color: #e2e8f0; font-size: 14px; font-weight: 600;">${new Date(record.timestamp).toLocaleString('zh-CN')}</div>
                        </div>
                        <div>
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 4px;">触发原因</div>
                            <div style="color: #e2e8f0; font-size: 14px; font-weight: 600;">
                                ${record.reason === 'unsteady_detected' ? '🚨 检测到非稳态' : '手动触发'}
                            </div>
                        </div>
                        <div>
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 4px;">新参数评分</div>
                            <div style="color: #10b981; font-size: 18px; font-weight: 700;">
                                ${performance.score?.toFixed(1) || '-'} (${performance.grade || '-'})
                            </div>
                        </div>
                    </div>
                </div>
                
                <!-- PID参数对比 -->
                <div style="margin-bottom: 24px;">
                    <h3 style="color: #e2e8f0; font-size: 18px; margin-bottom: 16px;">📊 PID参数对比</h3>
                    <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;">
                        ${this.createParamComparisonCard('Pb (比例带)', oldParams.pb, newParams.pb, '%')}
                        ${this.createParamComparisonCard('Ti (积分时间)', oldParams.ti, newParams.ti, 's')}
                        ${this.createParamComparisonCard('Td (微分时间)', oldParams.td, newParams.td, 's')}
                    </div>
                </div>
                
                <!-- 仿真曲线对比 -->
                <div style="margin-bottom: 24px;">
                    <h3 style="color: #e2e8f0; font-size: 18px; margin-bottom: 16px;">📈 新参数仿真曲线</h3>
                    <div style="background: rgba(15, 23, 42, 0.6); padding: 20px; border-radius: 12px; border: 1px solid rgba(148, 163, 184, 0.2);">
                        <canvas id="retuningComparisonChart" style="max-height: 400px;"></canvas>
                    </div>
                </div>
                
                <!-- 性能指标对比 -->
                <div>
                    <h3 style="color: #e2e8f0; font-size: 18px; margin-bottom: 16px;">📊 性能指标</h3>
                    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;">
                        <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 10px; text-align: center;">
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 8px;">稳态误差</div>
                            <div style="color: #10b981; font-size: 20px; font-weight: 700;">${performance.steady_error?.toFixed(4) || '-'}</div>
                        </div>
                        <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 10px; text-align: center;">
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 8px;">IAE</div>
                            <div style="color: #10b981; font-size: 20px; font-weight: 700;">${performance.iae?.toFixed(2) || '-'}</div>
                        </div>
                        <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 10px; text-align: center;">
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 8px;">振荡次数</div>
                            <div style="color: #10b981; font-size: 20px; font-weight: 700;">${performance.oscillation_count || 0}</div>
                        </div>
                        <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 10px; text-align: center;">
                            <div style="color: #94a3b8; font-size: 12px; margin-bottom: 8px;">综合评分</div>
                            <div style="color: #667eea; font-size: 20px; font-weight: 700;">${performance.score?.toFixed(1) || '-'}</div>
                        </div>
                    </div>
                </div>
                
                <!-- 操作按钮 -->
                <div style="margin-top: 24px; display: flex; gap: 12px; justify-content: flex-end;">
                    <button onclick="document.getElementById('retuningComparisonModal').remove()" 
                            class="btn btn-secondary">
                        取消
                    </button>
                    <button onclick="retuningVisualizer.applyNewParams('${record.loop_id}')" 
                            class="btn btn-primary">
                        ✅ 应用新参数
                    </button>
                </div>
            </div>
        `;
        
        return modal;
    }
    
    /**
     * 创建参数对比卡片
     */
    createParamComparisonCard(label, oldValue, newValue, unit) {
        const change = newValue && oldValue ? ((newValue - oldValue) / oldValue * 100) : 0;
        const changeColor = change > 0 ? '#10b981' : change < 0 ? '#ef4444' : '#6b7280';
        const changeIcon = change > 0 ? '↑' : change < 0 ? '↓' : '→';
        
        return `
            <div style="background: rgba(15, 23, 42, 0.6); padding: 16px; border-radius: 10px; border: 1px solid rgba(148, 163, 184, 0.2);">
                <div style="color: #94a3b8; font-size: 13px; margin-bottom: 12px; font-weight: 600;">${label}</div>
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <div>
                        <div style="color: #6b7280; font-size: 11px;">原参数</div>
                        <div style="color: #94a3b8; font-size: 16px; font-weight: 600;">${oldValue?.toFixed(1) || '-'}${unit}</div>
                    </div>
                    <div style="color: ${changeColor}; font-size: 24px;">${changeIcon}</div>
                    <div>
                        <div style="color: #6b7280; font-size: 11px;">新参数</div>
                        <div style="color: #10b981; font-size: 16px; font-weight: 700;">${newValue?.toFixed(1) || '-'}${unit}</div>
                    </div>
                </div>
                ${change !== 0 ? `
                    <div style="text-align: center; padding: 4px 8px; background: rgba(${change > 0 ? '16, 185, 129' : '239, 68, 68'}, 0.1); border-radius: 6px;">
                        <span style="color: ${changeColor}; font-size: 12px; font-weight: 600;">
                            ${change > 0 ? '+' : ''}${change.toFixed(1)}%
                        </span>
                    </div>
                ` : ''}
            </div>
        `;
    }
    
    /**
     * 渲染对比图表
     */
    renderComparisonChart(record) {
        const canvas = document.getElementById('retuningComparisonChart');
        if (!canvas) {
            console.error('找不到图表canvas元素');
            return;
        }
        
        const ctx = canvas.getContext('2d');
        const simulationData = record.simulation_data || {};
        
        // 销毁旧图表
        if (this.comparisonChart) {
            this.comparisonChart.destroy();
        }
        
        this.comparisonChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: simulationData.t || [],
                datasets: [
                    {
                        label: 'PV (新参数)',
                        data: simulationData.pv || [],
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        borderWidth: 2,
                        tension: 0.4,
                        pointRadius: 0
                    },
                    {
                        label: 'SV (设定值)',
                        data: simulationData.sv || [],
                        borderColor: '#667eea',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        borderDash: [5, 5],
                        tension: 0,
                        pointRadius: 0
                    },
                    {
                        label: 'MV (控制输出)',
                        data: simulationData.mv || [],
                        borderColor: '#f59e0b',
                        backgroundColor: 'rgba(245, 158, 11, 0.1)',
                        borderWidth: 2,
                        tension: 0.4,
                        pointRadius: 0,
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        position: 'top',
                        labels: {
                            color: '#e2e8f0',
                            font: {
                                size: 12
                            },
                            usePointStyle: true,
                            padding: 15
                        }
                    },
                    tooltip: {
                        backgroundColor: 'rgba(15, 23, 42, 0.9)',
                        titleColor: '#e2e8f0',
                        bodyColor: '#cbd5e1',
                        borderColor: '#667eea',
                        borderWidth: 1,
                        padding: 12,
                        displayColors: true
                    }
                },
                scales: {
                    x: {
                        title: {
                            display: true,
                            text: '时间 (s)',
                            color: '#94a3b8'
                        },
                        grid: {
                            color: 'rgba(148, 163, 184, 0.1)'
                        },
                        ticks: {
                            color: '#94a3b8'
                        }
                    },
                    y: {
                        title: {
                            display: true,
                            text: 'PV / SV',
                            color: '#94a3b8'
                        },
                        grid: {
                            color: 'rgba(148, 163, 184, 0.1)'
                        },
                        ticks: {
                            color: '#94a3b8'
                        }
                    },
                    y1: {
                        type: 'linear',
                        display: true,
                        position: 'right',
                        title: {
                            display: true,
                            text: 'MV (%)',
                            color: '#94a3b8'
                        },
                        grid: {
                            drawOnChartArea: false
                        },
                        ticks: {
                            color: '#94a3b8'
                        }
                    }
                }
            }
        });
    }
    
    /**
     * 应用新参数
     */
    async applyNewParams(loopId) {
        try {
            const response = await axios.post(`${window.API_BASE_URL}/api/loops/${loopId}/apply-retuning`);
            
            if (response.data.success) {
                showAlert('✅ 新参数已应用到回路', 'success');
                document.getElementById('retuningComparisonModal').remove();
                
                // 刷新回路列表
                if (typeof loadLoops === 'function') {
                    loadLoops();
                }
            } else {
                showAlert('❌ 应用参数失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            console.error('应用参数失败:', error);
            showAlert('❌ 应用参数失败', 'error');
        }
    }
}

// 创建全局实例
const retuningVisualizer = new RetuningVisualizer();

// 导出到window
window.retuningVisualizer = retuningVisualizer;
