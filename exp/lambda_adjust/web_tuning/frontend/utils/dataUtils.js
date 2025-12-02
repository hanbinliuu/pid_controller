/**
 * 数据工具模块
 * 提供数据验证、转换、格式化等通用功能
 */

const DataUtils = {
    /**
     * 验证JSON数据格式
     * @param {Object} data - JSON数据
     * @returns {Object} - {valid: boolean, error: string}
     */
    validateJSONData(data) {
        if (!data || typeof data !== 'object') {
            return { valid: false, error: 'JSON数据格式错误' };
        }
        
        if (!data.data || !Array.isArray(data.data)) {
            return { valid: false, error: 'JSON文件必须包含data数组字段' };
        }
        
        if (data.data.length === 0) {
            return { valid: false, error: '数据数组为空' };
        }
        
        // 检查必要字段
        const firstItem = data.data[0];
        const requiredFields = ['pv'];
        const missingFields = requiredFields.filter(field => !(field in firstItem));
        
        if (missingFields.length > 0) {
            return { 
                valid: false, 
                error: `缺少必要字段: ${missingFields.join(', ')}` 
            };
        }
        
        return { valid: true };
    },
    
    /**
     * 获取数据统计信息
     * @param {Array} data - 数据数组
     * @returns {Object} - 统计信息
     */
    getDataStats(data) {
        if (!Array.isArray(data) || data.length === 0) {
            return null;
        }
        
        const values = data.filter(v => typeof v === 'number' && !isNaN(v));
        if (values.length === 0) {
            return null;
        }
        
        const min = Math.min(...values);
        const max = Math.max(...values);
        const sum = values.reduce((a, b) => a + b, 0);
        const mean = sum / values.length;
        const variance = values.reduce((sq, n) => sq + Math.pow(n - mean, 2), 0) / values.length;
        const std = Math.sqrt(variance);
        
        return {
            count: values.length,
            min,
            max,
            range: max - min,
            mean,
            std,
            variance
        };
    },
    
    /**
     * 格式化数字
     * @param {number} value - 数值
     * @param {number} decimals - 小数位数
     * @returns {string} - 格式化后的字符串
     */
    formatNumber(value, decimals = 2) {
        if (typeof value !== 'number' || isNaN(value)) {
            return 'N/A';
        }
        return value.toFixed(decimals);
    },
    
    /**
     * 格式化百分比
     * @param {number} value - 数值（0-1）
     * @param {number} decimals - 小数位数
     * @returns {string} - 格式化后的字符串
     */
    formatPercent(value, decimals = 1) {
        if (typeof value !== 'number' || isNaN(value)) {
            return 'N/A';
        }
        return `${(value * 100).toFixed(decimals)}%`;
    },
    
    /**
     * 检查数据源类型
     * @returns {Object} - {isOPCUA: boolean, isFile: boolean}
     */
    getDataSourceType() {
        return {
            isOPCUA: window.isOPCUAData === true,
            isFile: window.isOPCUAData !== true,
            loopId: window.opcuaLoopId || null
        };
    },
    
    /**
     * 获取SV数据（根据数据源类型）
     * @param {Object} tuningResult - 整定结果
     * @param {Object} simulationData - 仿真数据
     * @returns {Array} - SV数据数组
     */
    getSVData(tuningResult, simulationData) {
        const sourceType = this.getDataSourceType();
        
        if (sourceType.isOPCUA) {
            // OPC UA数据：使用原始SV
            if (simulationData && simulationData.original_sv) {
                return simulationData.original_sv;
            } else if (window.uploadedData) {
                return window.uploadedData.map(item => item.sp);
            } else if (tuningResult && tuningResult.data) {
                return tuningResult.data.sv;
            }
        } else {
            // 文件数据：使用处理后的SV
            if (simulationData && simulationData.sv_processed) {
                return simulationData.sv_processed;
            } else if (simulationData && simulationData.sv) {
                return simulationData.sv;
            } else if (tuningResult && tuningResult.data) {
                return tuningResult.data.sv;
            }
        }
        
        return null;
    },
    
    /**
     * 深拷贝对象
     * @param {Object} obj - 要拷贝的对象
     * @returns {Object} - 拷贝后的对象
     */
    deepClone(obj) {
        if (obj === null || typeof obj !== 'object') {
            return obj;
        }
        
        if (Array.isArray(obj)) {
            return obj.map(item => this.deepClone(item));
        }
        
        const cloned = {};
        for (const key in obj) {
            if (obj.hasOwnProperty(key)) {
                cloned[key] = this.deepClone(obj[key]);
            }
        }
        return cloned;
    },
    
    /**
     * 安全地获取嵌套属性
     * @param {Object} obj - 对象
     * @param {string} path - 属性路径（如 'data.pv.length'）
     * @param {*} defaultValue - 默认值
     * @returns {*} - 属性值或默认值
     */
    safeGet(obj, path, defaultValue = null) {
        const keys = path.split('.');
        let result = obj;
        
        for (const key of keys) {
            if (result && typeof result === 'object' && key in result) {
                result = result[key];
            } else {
                return defaultValue;
            }
        }
        
        return result;
    },
    
    /**
     * 检查数据是否有效
     * @param {*} data - 数据
     * @returns {boolean} - 是否有效
     */
    isValidData(data) {
        return data !== null && data !== undefined && data !== '';
    },
    
    /**
     * 数组去重
     * @param {Array} arr - 数组
     * @returns {Array} - 去重后的数组
     */
    unique(arr) {
        return [...new Set(arr)];
    },
    
    /**
     * 数组分块
     * @param {Array} arr - 数组
     * @param {number} size - 块大小
     * @returns {Array} - 分块后的数组
     */
    chunk(arr, size) {
        const chunks = [];
        for (let i = 0; i < arr.length; i += size) {
            chunks.push(arr.slice(i, i + size));
        }
        return chunks;
    }
};

// 挂载到window对象
if (typeof window !== 'undefined') {
    window.DataUtils = DataUtils;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = DataUtils;
}
