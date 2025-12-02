/**
 * API客户端模块
 * 统一管理所有API调用，提供错误处理和重试机制
 */

const APIClient = {
    /**
     * 基础URL
     */
    baseURL: window.API_BASE_URL || 'http://localhost:8000',
    
    /**
     * 默认请求配置
     */
    defaultConfig: {
        headers: {
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    },
    
    /**
     * POST请求
     * @param {string} endpoint - API端点
     * @param {Object} data - 请求数据
     * @param {Object} config - 额外配置
     * @returns {Promise<Object>} - 响应数据
     */
    async post(endpoint, data, config = {}) {
        try {
            const url = `${this.baseURL}${endpoint}`;
            const mergedConfig = { ...this.defaultConfig, ...config };
            
            if (window.Logger) {
                window.Logger.debug(`POST ${endpoint}`, data);
            }
            
            const response = await axios.post(url, data, mergedConfig);
            
            if (window.Logger) {
                window.Logger.debug(`POST ${endpoint} 成功`, response.data);
            }
            
            return {
                success: true,
                data: response.data,
                status: response.status
            };
        } catch (error) {
            if (window.Logger) {
                window.Logger.error(`POST ${endpoint} 失败`, error);
            }
            
            return {
                success: false,
                error: error.message,
                details: error.response?.data,
                status: error.response?.status
            };
        }
    },
    
    /**
     * GET请求
     * @param {string} endpoint - API端点
     * @param {Object} params - 查询参数
     * @param {Object} config - 额外配置
     * @returns {Promise<Object>} - 响应数据
     */
    async get(endpoint, params = {}, config = {}) {
        try {
            const url = `${this.baseURL}${endpoint}`;
            const mergedConfig = { 
                ...this.defaultConfig, 
                ...config,
                params 
            };
            
            if (window.Logger) {
                window.Logger.debug(`GET ${endpoint}`, params);
            }
            
            const response = await axios.get(url, mergedConfig);
            
            if (window.Logger) {
                window.Logger.debug(`GET ${endpoint} 成功`, response.data);
            }
            
            return {
                success: true,
                data: response.data,
                status: response.status
            };
        } catch (error) {
            if (window.Logger) {
                window.Logger.error(`GET ${endpoint} 失败`, error);
            }
            
            return {
                success: false,
                error: error.message,
                details: error.response?.data,
                status: error.response?.status
            };
        }
    },
    
    /**
     * PUT请求
     * @param {string} endpoint - API端点
     * @param {Object} data - 请求数据
     * @param {Object} config - 额外配置
     * @returns {Promise<Object>} - 响应数据
     */
    async put(endpoint, data, config = {}) {
        try {
            const url = `${this.baseURL}${endpoint}`;
            const mergedConfig = { ...this.defaultConfig, ...config };
            
            if (window.Logger) {
                window.Logger.debug(`PUT ${endpoint}`, data);
            }
            
            const response = await axios.put(url, data, mergedConfig);
            
            if (window.Logger) {
                window.Logger.debug(`PUT ${endpoint} 成功`, response.data);
            }
            
            return {
                success: true,
                data: response.data,
                status: response.status
            };
        } catch (error) {
            if (window.Logger) {
                window.Logger.error(`PUT ${endpoint} 失败`, error);
            }
            
            return {
                success: false,
                error: error.message,
                details: error.response?.data,
                status: error.response?.status
            };
        }
    },
    
    /**
     * DELETE请求
     * @param {string} endpoint - API端点
     * @param {Object} config - 额外配置
     * @returns {Promise<Object>} - 响应数据
     */
    async delete(endpoint, config = {}) {
        try {
            const url = `${this.baseURL}${endpoint}`;
            const mergedConfig = { ...this.defaultConfig, ...config };
            
            if (window.Logger) {
                window.Logger.debug(`DELETE ${endpoint}`);
            }
            
            const response = await axios.delete(url, mergedConfig);
            
            if (window.Logger) {
                window.Logger.debug(`DELETE ${endpoint} 成功`, response.data);
            }
            
            return {
                success: true,
                data: response.data,
                status: response.status
            };
        } catch (error) {
            if (window.Logger) {
                window.Logger.error(`DELETE ${endpoint} 失败`, error);
            }
            
            return {
                success: false,
                error: error.message,
                details: error.response?.data,
                status: error.response?.status
            };
        }
    },
    
    /**
     * 带重试的请求
     * @param {Function} requestFn - 请求函数
     * @param {number} maxRetries - 最大重试次数
     * @param {number} delay - 重试延迟（毫秒）
     * @returns {Promise<Object>} - 响应数据
     */
    async withRetry(requestFn, maxRetries = 3, delay = 1000) {
        let lastError;
        
        for (let i = 0; i < maxRetries; i++) {
            try {
                const result = await requestFn();
                if (result.success) {
                    return result;
                }
                lastError = result.error;
            } catch (error) {
                lastError = error;
            }
            
            if (i < maxRetries - 1) {
                if (window.Logger) {
                    window.Logger.warn(`请求失败，${delay}ms后重试 (${i + 1}/${maxRetries})`);
                }
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        
        if (window.Logger) {
            window.Logger.error(`请求失败，已重试${maxRetries}次`, lastError);
        }
        
        return {
            success: false,
            error: lastError,
            retries: maxRetries
        };
    }
};

// 挂载到window对象
if (typeof window !== 'undefined') {
    window.APIClient = APIClient;
}

// 也支持ES6模块导出
if (typeof module !== 'undefined' && module.exports) {
    module.exports = APIClient;
}
