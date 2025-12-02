/**
 * Frontend Configuration File
 * 所有硬编码的配置参数集中管理
 */

const AppConfig = {
    /**
     * API配置
     */
    api: {
        // 基础URL（支持环境变量覆盖）
        baseURL: window.API_BASE_URL || 'http://localhost:8000',
        
        // 请求超时（毫秒）
        timeout: 30000,
        
        // 重试配置
        retry: {
            maxRetries: 3,
            delay: 1000
        },
        
        // 请求头
        headers: {
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    },
    
    /**
     * WebSocket配置
     */
    websocket: {
        // WebSocket URL（自动根据当前host构建）
        getUrl: (loopId) => `ws://${window.location.hostname}:8000/ws/loops/${loopId}`,
        
        // 重连配置
        reconnect: {
            maxAttempts: 5,
            delay: 2000
        }
    },
    
    /**
     * OPC UA配置
     */
    opcua: {
        // 默认连接参数
        defaultUrl: 'opc.tcp://localhost:4840',
        
        // 默认采集参数
        collection: {
            defaultDuration: 60,      // 默认采集时长（秒）
            defaultInterval: 1000,    // 默认采样间隔（毫秒）
            minDuration: 10,          // 最小采集时长
            maxDuration: 600,         // 最大采集时长
            minInterval: 100,         // 最小采样间隔
            maxInterval: 10000        // 最大采样间隔
        },
        
        // 节点浏览
        browse: {
            defaultNodeId: 'i=85',    // Objects文件夹
            maxDepth: 1
        },
        
        // 进度显示
        progress: {
            updateInterval: 100       // 进度更新间隔（毫秒）
        }
    },
    
    /**
     * 图表配置
     */
    chart: {
        // Chart.js默认配置
        defaults: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 300
            }
        },
        
        // 颜色方案
        colors: {
            pv: 'rgb(102, 126, 234)',      // PV曲线颜色
            sv: 'rgb(237, 100, 166)',      // SV曲线颜色
            mv: 'rgb(16, 185, 129)',       // MV曲线颜色
            simulation: 'rgb(251, 146, 60)', // 仿真曲线颜色
            grid: 'rgba(148, 163, 184, 0.1)', // 网格颜色
            text: '#94a3b8'                // 文字颜色
        },
        
        // 线条样式
        lineStyles: {
            pv: {
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0
            },
            sv: {
                borderWidth: 2,
                borderDash: [5, 5],
                tension: 0,
                pointRadius: 0
            },
            mv: {
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0
            },
            simulation: {
                borderWidth: 2,
                borderDash: [10, 5],
                tension: 0.4,
                pointRadius: 0
            }
        },
        
        // 数据限制
        maxDataPoints: 10000,
        
        // 实时图表更新间隔
        realtimeUpdateInterval: 1000
    },
    
    /**
     * UI配置
     */
    ui: {
        // 通知配置
        notification: {
            duration: 3000,           // 通知显示时长（毫秒）
            position: 'top-right'     // 通知位置
        },
        
        // 加载动画
        loading: {
            minDuration: 500,         // 最小显示时长（避免闪烁）
            spinnerSize: 'medium'
        },
        
        // 表格配置
        table: {
            pageSize: 10,             // 每页显示数量
            pageSizeOptions: [10, 20, 50, 100]
        },
        
        // 模态框
        modal: {
            animationDuration: 300,   // 动画时长
            backdropOpacity: 0.7
        }
    },
    
    /**
     * 整定配置
     */
    tuning: {
        // 默认参数
        defaults: {
            tuningMethod: 'LAMBDA',
            controlMode: 'STANDARD',
            enableSegmentation: true,
            modelType: 'auto'
        },
        
        // 可选项
        methods: ['LAMBDA', 'COHEN_COON'],
        modes: ['STANDARD', 'AGGRESSIVE', 'CONSERVATIVE'],
        modelTypes: ['auto', 'fopdt', 'second_order', 'integral_delay', 'fopdt_with_heat_loss'],
        
        // 参数范围
        paramRanges: {
            pb: { min: 1, max: 500, default: 100 },
            ti: { min: 0, max: 1000, default: 20 },
            td: { min: 0, max: 100, default: 0 }
        },
        
        // 文件上传
        upload: {
            maxFileSize: 10 * 1024 * 1024,  // 10MB
            acceptedFormats: ['.json', '.csv'],
            maxDataPoints: 100000
        }
    },
    
    /**
     * 仿真配置
     */
    simulation: {
        // 默认参数
        defaults: {
            duration: 100,
            initialPv: 0,
            initialMv: 50
        },
        
        // 参数范围
        ranges: {
            duration: { min: 10, max: 1000 },
            initialPv: { min: -100, max: 100 },
            initialMv: { min: 0, max: 100 }
        }
    },
    
    /**
     * 回路管理配置
     */
    loops: {
        // 刷新间隔
        refreshInterval: 5000,        // 回路列表刷新间隔（毫秒）
        
        // 状态颜色
        statusColors: {
            STABLE: '#10b981',        // 绿色
            DISTURBANCE: '#f59e0b',   // 橙色
            TUNING: '#3b82f6',        // 蓝色
            STABILIZING: '#8b5cf6',   // 紫色
            UNKNOWN: '#6b7280'        // 灰色
        },
        
        // 状态文本
        statusText: {
            STABLE: '稳定',
            DISTURBANCE: '扰动',
            TUNING: '整定中',
            STABILIZING: '稳定期',
            UNKNOWN: '未知'
        },
        
        // 数据源
        dataSources: {
            manual: '手动上传',
            opcua: 'OPC UA'
        }
    },
    
    /**
     * 监控配置
     */
    monitoring: {
        // 实时数据更新间隔
        realtimeUpdateInterval: 1000,
        
        // 性能指标阈值
        thresholds: {
            score: {
                excellent: 90,
                good: 80,
                fair: 70,
                poor: 60
            },
            steadyError: {
                excellent: 0.01,
                good: 0.02,
                fair: 0.05,
                poor: 0.1
            }
        },
        
        // 告警配置
        alarm: {
            enabled: true,
            soundEnabled: false,
            repeatInterval: 60000     // 重复告警间隔（毫秒）
        }
    },
    
    /**
     * 比较配置
     */
    comparison: {
        // 最大比较数量
        maxComparisons: 5,
        
        // 图表配置
        chart: {
            showLegend: true,
            showGrid: true,
            opacity: 0.7
        }
    },
    
    /**
     * 日志配置
     */
    logging: {
        // 日志级别
        level: 'INFO',  // DEBUG, INFO, WARN, ERROR
        
        // 控制台输出
        console: true,
        
        // 日志保留
        maxLogs: 1000,
        
        // 颜色配置
        colors: {
            DEBUG: '#94a3b8',
            INFO: '#3b82f6',
            WARN: '#f59e0b',
            ERROR: '#ef4444'
        }
    },
    
    /**
     * 本地存储配置
     */
    storage: {
        // 键名前缀
        prefix: 'pid_tuning_',
        
        // 存储项
        keys: {
            loops: 'loops',
            settings: 'settings',
            history: 'history',
            opcuaConfig: 'opcua_config'
        },
        
        // 历史记录限制
        maxHistoryItems: 100
    },
    
    /**
     * 性能优化配置
     */
    performance: {
        // 防抖延迟
        debounce: {
            search: 300,
            resize: 200,
            input: 500
        },
        
        // 节流间隔
        throttle: {
            scroll: 100,
            mousemove: 50
        },
        
        // 虚拟滚动
        virtualScroll: {
            enabled: true,
            itemHeight: 50,
            bufferSize: 10
        }
    },
    
    /**
     * 开发配置
     */
    dev: {
        // 调试模式
        debug: false,
        
        // Mock数据
        useMockData: false,
        
        // 性能监控
        performanceMonitoring: false
    }
};

// 挂载到window对象
if (typeof window !== 'undefined') {
    window.AppConfig = AppConfig;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AppConfig;
}
